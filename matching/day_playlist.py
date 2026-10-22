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
from intelligence.feeling_score import pick_state
from matching.generator import GenerationError, format_playlist_name, select_day_songs
from matching.query_engine import play_dates_before, rewind_songs_to_date
from matching.why_lines import build_context, explain_playlist

SPOTIFY_TRACK_URL = "https://open.spotify.com/track/{}"


def build_day_playlist(
    conn: sqlite3.Connection,
    date_str: str,
    prior_playlists: dict[str, list[str]] | None = None,
) -> dict:
    """The playlist the daily pipeline picks for date_str, with a why-line per song.

    prior_playlists: earlier replayed days ({date: track URIs}) that count for
    rotation as if pushed. Pushed playlists in the DB always count.

    Returns {"name", "spotify_url" (None until a real playlist exists),
    "state" (rest|energy|grounding), "tracks": [{title, artist, spotify_url, why}]}.
    Raises GenerationError when the day can't be generated (e.g. too little WHOOP data).
    """
    page, _uris = _build(conn, date_str, prior_playlists)
    return page


def build_day_playlists(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Replay every day from start to end (inclusive), oldest first, chaining rotation.

    Returns [{"date", "playlist" (page dict or None), "error" (str or None)}].
    A day that can't be generated is reported and skipped; the chain continues.
    """
    first, last = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    if first > last:
        raise ValueError(f"start {start} is after end {end}")

    prior: dict[str, list[str]] = {}
    results = []
    day = first
    while day <= last:
        date_str = day.isoformat()
        try:
            page, uris = _build(conn, date_str, prior)
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
) -> tuple[dict, list[str]]:
    """(page, track URIs shown) for one day."""
    classification, match_result = select_day_songs(
        conn, date_str, point_in_time=True, prior_playlists=prior_playlists,
    )
    songs = match_result["songs"][:MAX_PLAYLIST_SIZE]
    profile = match_result["neuro_profile"]
    state, _label = pick_state(profile)

    library = rewind_songs_to_date(conn, get_all_classified_songs(conn), date_str)
    context = build_context(library, date_str, play_dates_before(conn, date_str))
    whys = explain_playlist(songs, state, context)

    recovery = classification.get("metrics", {}).get("recovery_score")
    page = {
        "name": format_playlist_name(date_str, profile, recovery),
        "spotify_url": None,
        "state": state,
        "tracks": [
            {
                "title": song.get("name", ""),
                "artist": song.get("artist", ""),
                "spotify_url": SPOTIFY_TRACK_URL.format(song["spotify_uri"].split(":")[-1]),
                "why": why,
            }
            for song, why in zip(songs, whys)
        ],
    }
    return page, [s["spotify_uri"] for s in songs]
