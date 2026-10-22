"""Push the page's most recent day playlists to Spotify as real public playlists.

Every day on the page has a computed playlist; only the latest few are worth a
real Spotify playlist. This publishes the N most recent page days that have
songs (N is capped at MAX_RECENT), records each in web/published.json, and is
safe to re-run: a recorded day never gets a second playlist, only its tracks
replaced when they changed.
"""

import time
from collections.abc import Callable
from pathlib import Path

import spotipy

from intelligence.continuous_profile import STATE_PURPOSE
from spotify.playlist import create_playlist, replace_playlist_tracks
from web.site import PUBLISHED_PATH, save_published

MAX_RECENT = 3                # hard cap on days published per run, unless explicitly lifted
THROTTLE_S = 2.0              # pause after every Spotify call (tasks/lessons.md: throttle all calls)
DESCRIPTION = "Attuned · {purpose} · built from my WHOOP data"


def check_recent(n: int, allow_more: bool = False) -> None:
    """Raise ValueError unless 1 <= n <= MAX_RECENT (allow_more lifts only the upper cap)."""
    if n < 1:
        raise ValueError(f"--recent must be at least 1, got {n}")
    if n > MAX_RECENT and not allow_more:
        raise ValueError(f"--recent is capped at {MAX_RECENT}; pass --allow-more to publish {n} days")


def track_uris(playlist: dict) -> list[str]:
    """Spotify URIs of the playlist's tracks, in page order."""
    return ["spotify:track:" + t["spotify_url"].rsplit("/", 1)[-1] for t in playlist["tracks"]]


def describe(playlist: dict) -> str:
    return DESCRIPTION.format(purpose=STATE_PURPOSE[playlist["state"]])


def _playlist_id(url: str) -> str:
    """'https://open.spotify.com/playlist/ID?si=x' -> 'ID'."""
    return url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]


def plan_publish(days: list[dict], published: dict[str, dict], n: int,
                 allow_more: bool = False) -> list[dict]:
    """What to do for each of the n most recent days (oldest first) whose playlist has songs.

    Each step is {date, action, name, description, track_uris}; action is
    "create" (not yet published), "replace" (published, tracks changed) or
    "unchanged". Days outside those n are never touched, published or not.
    """
    check_recent(n, allow_more)
    with_songs = [d for d in days if d["playlist"] and d["playlist"]["tracks"]]
    steps = []
    for day in with_songs[-n:]:
        playlist, uris = day["playlist"], track_uris(day["playlist"])
        record = published.get(day["date"])
        action = "create" if record is None else "unchanged" if record["track_uris"] == uris else "replace"
        steps.append({"date": day["date"], "action": action, "name": playlist["name"],
                      "description": describe(playlist), "track_uris": uris})
    return steps


def publish_steps(sp: spotipy.Spotify, steps: list[dict], published: dict[str, dict],
                  path: Path = PUBLISHED_PATH, sleep: Callable[[float], None] = time.sleep) -> dict[str, dict]:
    """Carry out the plan; returns the updated mapping (the caller's dict is left as is).

    The file is saved after every Spotify write, so a failure part-way (rate
    limit, API error) leaves it describing exactly what exists on Spotify. A new
    playlist is created empty and recorded before its tracks go in: if setting
    the tracks fails, the next run sees the recorded playlist and fills it
    instead of creating a second one. Any error stops the run and propagates.
    """
    published = {date: dict(record) for date, record in published.items()}
    for step in steps:
        if step["action"] == "unchanged":
            continue
        date = step["date"]
        if step["action"] == "create":
            created = create_playlist(sp, step["name"], step["description"], [], public=True)
            sleep(THROTTLE_S)
            published[date] = {"url": created["playlist_url"], "track_uris": []}
            save_published(published, path)
        replace_playlist_tracks(sp, _playlist_id(published[date]["url"]), step["track_uris"])
        sleep(THROTTLE_S)
        published[date]["track_uris"] = step["track_uris"]
        save_published(published, path)
    return published
