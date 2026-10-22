"""Soundcharts tempo for songs that have no audio clip.

Soundcharts' song endpoint returns Spotify's old audio features, including
`audio.tempo`. That is a beat-tracker number, so it has the same octave errors
as our own trackers (Tere Mast Mast Do Nain is listed at 152, clapped at 76).
classification.tempo treats it the same way: the number is trusted, the octave
comes from the LLM. Calls cost quota, so each song is fetched once and stored
in song_classifications.soundcharts_tempo.
"""

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from classification.tempo import READING_COLUMNS

logger = logging.getLogger(__name__)

SOUNDCHARTS_SONG_URL = (
    "https://customer.api.soundcharts.com/api/v2.25/song/by-platform/spotify/{track_id}"
)
REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_DELAY_SECONDS = 0.3
# Statuses where another call would only burn quota: bad keys, no plan, quota gone.
_STOP_STATUSES = {401, 403, 429}


class SoundchartsStop(Exception):
    """Soundcharts refused the credentials or the quota — stop the whole run."""


@dataclass(frozen=True)
class SoundchartsResponse:
    song: dict[str, Any] | None   # the response's "object", None if not found
    quota_remaining: int | None


def fetch_soundcharts_song(
    spotify_uri: str,
    app_id: str,
    api_key: str,
    http_get: Callable[..., httpx.Response] = httpx.get,
) -> SoundchartsResponse:
    """Look one song up on Soundcharts by its Spotify id.

    Raises SoundchartsStop on 401/403/429. Other failures (404, 5xx, network)
    return song=None so one bad song doesn't end the run.
    """
    track_id = spotify_uri.split(":")[-1]
    try:
        response = http_get(
            SOUNDCHARTS_SONG_URL.format(track_id=track_id),
            headers={"x-app-id": app_id, "x-api-key": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        logger.warning("Soundcharts request failed for %s: %s", spotify_uri, e)
        return SoundchartsResponse(None, None)

    quota = response.headers.get("x-quota-remaining")
    quota_remaining = int(quota) if quota and quota.isdigit() else None
    if response.status_code in _STOP_STATUSES:
        raise SoundchartsStop(f"Soundcharts returned {response.status_code}: {response.text[:200]}")
    if response.status_code != 200:
        logger.warning("Soundcharts %s for %s", response.status_code, spotify_uri)
        return SoundchartsResponse(None, quota_remaining)
    try:
        song = response.json().get("object")
    except ValueError:
        logger.warning("Soundcharts returned malformed JSON for %s", spotify_uri)
        return SoundchartsResponse(None, quota_remaining)
    return SoundchartsResponse(song if isinstance(song, dict) else None, quota_remaining)


def parse_soundcharts_tempo(song: dict[str, Any] | None) -> float | None:
    """audio.tempo from a Soundcharts song object, or None if absent/implausible."""
    audio = (song or {}).get("audio")
    if not isinstance(audio, dict):
        return None
    try:
        tempo = float(audio.get("tempo"))
    except (TypeError, ValueError):
        return None
    return tempo if 30 <= tempo <= 300 else None


def get_songs_needing_soundcharts_tempo(
    conn: sqlite3.Connection,
    limit: int,
) -> list[dict[str, Any]]:
    """Engaged, classified songs with no audio readings and no Soundcharts tempo yet.

    Most-engaged first, so a small quota goes to the songs played most.
    """
    no_readings = " AND ".join(f"sc.{c} IS NULL" for c in READING_COLUMNS)
    rows = conn.execute(
        f"""SELECT sc.spotify_uri, s.name, s.artist
            FROM song_classifications sc
            JOIN songs s ON sc.spotify_uri = s.spotify_uri
            WHERE {no_readings}
              AND sc.soundcharts_tempo IS NULL
              AND s.engagement_score IS NOT NULL
            ORDER BY s.engagement_score DESC
            LIMIT ?""",  # noqa: S608
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def backfill_soundcharts_tempos(
    conn: sqlite3.Connection,
    fetch_song: Callable[[str], SoundchartsResponse],
    limit: int,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> dict[str, Any]:
    """Fetch and store Soundcharts tempo for up to `limit` songs (one call each).

    Stores only soundcharts_tempo; run update-tempos afterwards to use it.
    Stops early (stats["stopped"] = reason) if Soundcharts refuses the keys or quota.
    """
    stats: dict[str, Any] = {"calls": 0, "stored": 0, "no_tempo": 0,
                             "quota_remaining": None, "stopped": None}
    for i, song in enumerate(get_songs_needing_soundcharts_tempo(conn, limit)):
        if i > 0:
            time.sleep(delay_seconds)
        try:
            response = fetch_song(song["spotify_uri"])
        except SoundchartsStop as e:
            logger.error("Stopping Soundcharts backfill: %s", e)
            stats["stopped"] = str(e)
            break
        stats["calls"] += 1
        if response.quota_remaining is not None:
            stats["quota_remaining"] = response.quota_remaining

        tempo = parse_soundcharts_tempo(response.song)
        if tempo is None:
            stats["no_tempo"] += 1
            logger.warning("No Soundcharts tempo: %s — %s", song["name"], song["artist"])
            continue
        conn.execute(
            "UPDATE song_classifications SET soundcharts_tempo = ? WHERE spotify_uri = ?",
            (tempo, song["spotify_uri"]),
        )
        conn.commit()
        stats["stored"] += 1
    return stats
