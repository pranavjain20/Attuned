"""Soundcharts tempo for songs that have no audio clip.

Soundcharts' song endpoint returns Spotify's old audio features, including
`audio.tempo`. That is a beat-tracker number, so it has the same octave errors
as our own trackers (Tere Mast Mast Do Nain is listed at 152, clapped at 76).
classification.tempo treats it the same way: the number is trusted, the octave
comes from the LLM. Calls cost quota, so each song is asked about once: its
tempo goes in song_classifications.soundcharts_tempo, and soundcharts_checked_at
records that Soundcharts answered (even with no tempo), so it isn't asked again
unless forced. A run stops when the quota header reaches 0.
"""

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
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
    # Soundcharts gave a definite answer about this song (found it, or 404). False for
    # network errors, 5xx and malformed bodies: those say nothing, so ask again later.
    answered: bool = True


def fetch_soundcharts_song(
    spotify_uri: str,
    app_id: str,
    api_key: str,
    http_get: Callable[..., httpx.Response] = httpx.get,
) -> SoundchartsResponse:
    """Look one song up on Soundcharts by its Spotify id.

    Raises SoundchartsStop on 401/403/429. Other failures (404, 5xx, network)
    return song=None so one bad song doesn't end the run; only a 404 counts as
    an answer (see SoundchartsResponse.answered).
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
        return SoundchartsResponse(None, None, answered=False)

    quota = response.headers.get("x-quota-remaining")
    quota_remaining = int(quota) if quota and quota.isdigit() else None
    if response.status_code in _STOP_STATUSES:
        raise SoundchartsStop(f"Soundcharts returned {response.status_code}: {response.text[:200]}")
    if response.status_code != 200:
        logger.warning("Soundcharts %s for %s", response.status_code, spotify_uri)
        return SoundchartsResponse(None, quota_remaining, answered=response.status_code == 404)
    try:
        song = response.json().get("object")
    except ValueError:
        logger.warning("Soundcharts returned malformed JSON for %s", spotify_uri)
        return SoundchartsResponse(None, quota_remaining, answered=False)
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
    force: bool = False,
) -> list[dict[str, Any]]:
    """Engaged, classified songs with no audio readings and no Soundcharts tempo yet.

    Songs Soundcharts already answered for (soundcharts_checked_at set) are left
    out unless `force`. Most-engaged first, so a small quota goes to the songs
    played most.
    """
    no_readings = " AND ".join(f"sc.{c} IS NULL" for c in READING_COLUMNS)
    rows = conn.execute(
        f"""SELECT sc.spotify_uri, s.name, s.artist
            FROM song_classifications sc
            JOIN songs s ON sc.spotify_uri = s.spotify_uri
            WHERE {no_readings}
              AND sc.soundcharts_tempo IS NULL
              AND (? OR sc.soundcharts_checked_at IS NULL)
              AND s.engagement_score IS NOT NULL
            ORDER BY s.engagement_score DESC
            LIMIT ?""",  # noqa: S608
        (force, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def backfill_soundcharts_tempos(
    conn: sqlite3.Connection,
    fetch_song: Callable[[str], SoundchartsResponse],
    limit: int,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch and store Soundcharts tempo for up to `limit` songs (one call each).

    Stores only soundcharts_tempo and soundcharts_checked_at; run update-tempos
    afterwards to use the tempo. `force` re-asks songs already answered with no
    tempo. Stops early (stats["stopped"] = reason) if Soundcharts refuses the
    keys or quota, or reports 0 calls left.
    """
    stats: dict[str, Any] = {"calls": 0, "stored": 0, "no_tempo": 0,
                             "quota_remaining": None, "stopped": None}
    for i, song in enumerate(get_songs_needing_soundcharts_tempo(conn, limit, force)):
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
        else:
            stats["stored"] += 1
        if response.answered:
            conn.execute(
                """UPDATE song_classifications
                   SET soundcharts_tempo = ?, soundcharts_checked_at = ?
                   WHERE spotify_uri = ?""",
                (tempo, datetime.now(timezone.utc).isoformat(), song["spotify_uri"]),
            )
            conn.commit()

        if response.quota_remaining == 0:
            stats["stopped"] = "Soundcharts quota used up (x-quota-remaining is 0)"
            logger.error("Stopping Soundcharts backfill: %s", stats["stopped"])
            break
    return stats
