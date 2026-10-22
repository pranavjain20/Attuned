"""Push the page's most recent day playlists to Spotify as real public playlists.

Every day on the page has a computed playlist; only the latest few are worth a
real Spotify playlist. This publishes the N most recent page days that have
songs (N is capped at MAX_RECENT), records each in web/published.json, and is
safe to re-run: a recorded day never gets a second playlist, only its tracks,
name or description updated when they changed (or a new playlist when the
recorded one is gone from Spotify).

Before publishing, songs Spotify no longer plays are dropped and the day's
spares (the replay's over-selected buffer) take their places, as in the daily
pipeline.
"""

import logging
import sqlite3
import time
from collections.abc import Callable, Collection
from pathlib import Path

import spotipy

from config import MAX_PLAYLIST_SIZE
from db.queries import get_song
from intelligence.playlist_target import STATE_PURPOSE
from matching.day_playlist import track_uri
from matching.generator import filter_unavailable_tracks
from spotify.playlist import SpotifyPlaylistError, change_playlist_details, create_playlist, replace_playlist_tracks
from web.site import PUBLISHED_PATH, save_published

logger = logging.getLogger(__name__)

MAX_RECENT = 3                # hard cap on days published per run, unless explicitly lifted
THROTTLE_S = 2.0              # pause after every Spotify write, so a run never bursts the API
DESCRIPTION = "Attuned · {purpose} · built from my WHOOP data"
NOT_FOUND = 404


def check_recent(n: int, allow_more: bool = False) -> None:
    """Raise ValueError unless 1 <= n <= MAX_RECENT (allow_more lifts only the upper cap)."""
    if n < 1:
        raise ValueError(f"--recent must be at least 1, got {n}")
    if n > MAX_RECENT and not allow_more:
        raise ValueError(f"--recent is capped at {MAX_RECENT}; pass --allow-more to publish {n} days")


def recent_days(days: list[dict], n: int, allow_more: bool = False) -> list[dict]:
    """The n most recent days (oldest first) whose playlist has songs."""
    check_recent(n, allow_more)
    return [d for d in days if d["playlist"] and d["playlist"]["tracks"]][-n:]


def candidate_uris(playlist: dict) -> list[str]:
    """Spotify URIs of the playlist's tracks, then its spares, in order."""
    return [track_uri(t) for t in playlist["tracks"] + playlist.get("spares", [])]


def describe(playlist: dict) -> str:
    return DESCRIPTION.format(purpose=STATE_PURPOSE[playlist["state"]])


def _playlist_id(url: str) -> str:
    """'https://open.spotify.com/playlist/ID?si=x' -> 'ID'."""
    return url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]


def find_unavailable(conn: sqlite3.Connection, sp: spotipy.Spotify, days: list[dict],
                     sleep: Callable[[float], None] = time.sleep) -> set[str]:
    """URIs among the days' candidates that Spotify no longer plays.

    The daily pipeline's check (generator.filter_unavailable_tracks): one
    sp.track call per song, 3 s apart, skipping songs confirmed playable in the
    last AVAILABILITY_CACHE_DAYS, and saving every answer to the songs table (so
    the page's replay leaves known-unavailable songs out too). A song shared by
    several days is checked once. Pauses THROTTLE_S afterwards, before any write.
    An exhausted quota (SpotifyRateLimitError) propagates.
    """
    uris = list(dict.fromkeys(uri for day in days for uri in candidate_uris(day["playlist"])))
    if not uris:
        return set()
    songs = [get_song(conn, uri) or {"spotify_uri": uri} for uri in uris]
    playable = {s["spotify_uri"] for s in filter_unavailable_tracks(sp, songs, conn=conn)}
    sleep(THROTTLE_S)
    return set(uris) - playable


def plan_publish(days: list[dict], published: dict[str, dict], n: int,
                 allow_more: bool = False, unavailable: Collection[str] = frozenset()) -> list[dict]:
    """What to do for each of the n most recent days (oldest first) whose playlist has songs.

    Each step is {date, action, changes, name, description, track_uris}.
    track_uris is the day's candidates minus `unavailable`, cut to
    MAX_PLAYLIST_SIZE, so a spare stands in for each song Spotify no longer
    plays. action is "create" (not yet published), "update" (published, and
    changes lists what differs: "tracks" and/or "details" for the name and
    description) or "unchanged". A day left with no songs is skipped with a
    warning. Days outside those n are never touched, published or not.
    """
    steps = []
    for day in recent_days(days, n, allow_more):
        playlist = day["playlist"]
        uris = [uri for uri in candidate_uris(playlist) if uri not in unavailable][:MAX_PLAYLIST_SIZE]
        if not uris:
            logger.warning("Every song for %s is unavailable on Spotify; not publishing it", day["date"])
            continue
        name, description = playlist["name"], describe(playlist)
        record = published.get(day["date"])
        changes = []
        if record is not None:
            if record["track_uris"] != uris:
                changes.append("tracks")
            if (record.get("name"), record.get("description")) != (name, description):
                changes.append("details")
        action = "create" if record is None else "update" if changes else "unchanged"
        steps.append({"date": day["date"], "action": action, "changes": changes,
                      "name": name, "description": description, "track_uris": uris})
    return steps


def publish_steps(sp: spotipy.Spotify, steps: list[dict], published: dict[str, dict],
                  path: Path = PUBLISHED_PATH, sleep: Callable[[float], None] = time.sleep) -> dict[str, dict]:
    """Carry out the plan; returns the updated mapping (the caller's dict is left as is).

    The file is saved after every Spotify write, so a failure part-way (rate
    limit, API error) leaves it describing exactly what exists on Spotify. A new
    playlist is created empty and recorded before its tracks go in: if setting
    the tracks fails, the next run sees the recorded playlist and fills it
    instead of creating a second one. A recorded playlist Spotify no longer has
    (404) is made again and its new URL recorded. Any other error stops the run
    and propagates.
    """
    published = {date: dict(record) for date, record in published.items()}
    for step in steps:
        if step["action"] == "unchanged":
            continue
        if step["action"] == "update":
            try:
                _update(sp, step, published, path, sleep)
                continue
            except SpotifyPlaylistError as e:
                if e.http_status != NOT_FOUND:
                    raise
                logger.warning("The playlist for %s is gone from Spotify (%s); making a new one", step["date"], e)
        _create(sp, step, published, path, sleep)
    return published


def _create(sp: spotipy.Spotify, step: dict, published: dict[str, dict], path: Path,
            sleep: Callable[[float], None]) -> None:
    date = step["date"]
    created = create_playlist(sp, step["name"], step["description"], [], public=True)
    sleep(THROTTLE_S)
    published[date] = {"url": created["playlist_url"], "track_uris": [],
                       "name": step["name"], "description": step["description"]}
    save_published(published, path)
    _set_tracks(sp, step, published, path, sleep)


def _update(sp: spotipy.Spotify, step: dict, published: dict[str, dict], path: Path,
            sleep: Callable[[float], None]) -> None:
    if "tracks" in step["changes"]:
        _set_tracks(sp, step, published, path, sleep)
    if "details" in step["changes"]:
        record = published[step["date"]]
        change_playlist_details(sp, _playlist_id(record["url"]), step["name"], step["description"])
        sleep(THROTTLE_S)
        record.update(name=step["name"], description=step["description"])
        save_published(published, path)


def _set_tracks(sp: spotipy.Spotify, step: dict, published: dict[str, dict], path: Path,
                sleep: Callable[[float], None]) -> None:
    record = published[step["date"]]
    replace_playlist_tracks(sp, _playlist_id(record["url"]), step["track_uris"])
    sleep(THROTTLE_S)
    record["track_uris"] = step["track_uris"]
    save_published(published, path)
