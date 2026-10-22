"""A day's playlist as page data — the showcase "what played today and why" list.

Read-only replay: runs the same selection as `generate`, but with the library
rewound to that morning, no Spotify calls and no row written to
generated_playlists. Replaying a range chains rotation in memory, so each day
behaves as if every earlier replayed day had really been pushed.
"""

import sqlite3
from datetime import date as date_cls, timedelta

from config import MAX_PLAYLIST_SIZE
from db.queries import get_all_classified_songs
from intelligence.feeling_score import compute_composite_history
from matching.generator import GenerationError, format_playlist_name, select_day_songs
from matching.query_engine import play_dates_before, rewind_songs_to_date
from matching.why_lines import build_context, explain_playlist

SPOTIFY_TRACK_URL = "https://open.spotify.com/track/{}"


def track_uri(track: dict) -> str:
    """A page track's Spotify URI, from its spotify_url ('.../track/ID' -> 'spotify:track:ID')."""
    return "spotify:track:" + track["spotify_url"].rsplit("/", 1)[-1]


def build_day_playlist(
    conn: sqlite3.Connection,
    date_str: str,
    prior_playlists: dict[str, list[str]] | None = None,
    history: dict[str, dict] | None = None,
) -> dict:
    """The playlist the daily pipeline picks for date_str, with a why-line per song.

    prior_playlists: earlier replayed days ({date: track URIs}) that count for
    rotation as if pushed. Pushed playlists in the DB always count.
    history: the Attuned score history (feeling_score.compute_composite_history,
    built up to at least date_str); saves rescoring every earlier day.

    Returns {"name", "state" (rest|energy|grounding),
    "tracks": [{title, artist, spotify_url, why}] (the MAX_PLAYLIST_SIZE songs),
    "spares": [same shape] (the over-selected buffer, in order: the songs that
    stand in when publishing finds one Spotify no longer plays)}.
    Raises GenerationError when the day can't be generated (e.g. too little WHOOP data).
    """
    page, _uris = _build(conn, date_str, prior_playlists, history)
    return page


def build_day_playlists(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    history: dict[str, dict] | None = None,
    fixed: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Replay every day from start to end (inclusive), oldest first, chaining rotation.

    fixed: days whose playlists were already decided ({date: track URIs}). They are
    not rebuilt and get no result; they count for rotation as if pushed.

    history: the Attuned score history, built up to at least end; computed once
    here when not given, so scoring each day doesn't replay every earlier day.

    Returns [{"date", "playlist" (page dict or None), "error" (str or None)}].
    A day that can't be generated is reported and skipped; the chain continues.
    """
    first, last = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    if first > last:
        raise ValueError(f"start {start} is after end {end}")
    if history is None:
        history = compute_composite_history(conn, (last + timedelta(days=1)).isoformat())

    prior: dict[str, list[str]] = dict(fixed or {})
    results = []
    day = first
    while day <= last:
        date_str = day.isoformat()
        if fixed and date_str in fixed:
            day += timedelta(days=1)
            continue
        try:
            page, uris = _build(conn, date_str, prior, history)
        except GenerationError as e:
            results.append({"date": date_str, "playlist": None, "error": str(e)})
        else:
            prior[date_str] = uris
            results.append({"date": date_str, "playlist": page, "error": None})
        day += timedelta(days=1)
    return results


def _build(
    conn: sqlite3.Connection,
    date_str: str,
    prior_playlists: dict[str, list[str]] | None,
    history: dict[str, dict] | None,
) -> tuple[dict, list[str]]:
    """(page, track URIs shown) for one day."""
    library = rewind_songs_to_date(conn, get_all_classified_songs(conn), date_str)
    match_result = select_day_songs(
        conn, date_str, prior_playlists=prior_playlists, history=history, library=library,
    )
    songs = match_result["songs"]  # the playlist plus its availability buffer
    context = build_context(library, date_str, play_dates_before(conn, date_str))
    # Lines are written down the list, so the first MAX_PLAYLIST_SIZE read the same with or without spares.
    whys = explain_playlist(songs, match_result["state"], context)
    tracks = [
        {
            "title": song.get("name", ""),
            "artist": song.get("artist", ""),
            "spotify_url": SPOTIFY_TRACK_URL.format(song["spotify_uri"].split(":")[-1]),
            "why": why,
        }
        for song, why in zip(songs, whys)
    ]
    page = {
        "name": format_playlist_name(date_str, match_result["neuro_profile"], match_result["position"]),
        "state": match_result["state"],
        "tracks": tracks[:MAX_PLAYLIST_SIZE],
        "spares": tracks[MAX_PLAYLIST_SIZE:],
    }
    return page, [s["spotify_uri"] for s in songs[:MAX_PLAYLIST_SIZE]]
