"""Spotify data synchronization — extended history ingestion and API-based sync."""

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from config import MIN_PLAY_DURATION_MS
from db import queries

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extended streaming history ingestion (Tier 1 — no API keys)
# ---------------------------------------------------------------------------

def ingest_extended_history(conn: sqlite3.Connection, history_dir: str | Path) -> dict[str, int]:
    """Parse Streaming_History_Audio_*.json files, insert into listening_history + songs.

    Returns summary dict with counts: total_records, inserted_history, total_songs.
    """
    history_dir = Path(history_dir)
    audio_files = sorted(history_dir.glob("Streaming_History_Audio_*.json"))
    if not audio_files:
        raise FileNotFoundError(f"No Streaming_History_Audio_*.json files in {history_dir}")

    all_records: list[dict[str, Any]] = []
    songs_seen: dict[str, dict[str, Any]] = {}  # uri -> song info

    for filepath in audio_files:
        logger.info("Parsing %s", filepath.name)
        with open(filepath) as f:
            raw_entries = json.load(f)

        for entry in raw_entries:
            parsed = _parse_history_record(entry)
            if parsed is None:
                continue
            all_records.append(parsed["history"])
            uri = parsed["history"]["spotify_uri"]
            song = parsed["song"]

            if uri in songs_seen:
                existing = songs_seen[uri]
                if song["first_played"] and (
                    existing["first_played"] is None
                    or song["first_played"] < existing["first_played"]
                ):
                    existing["first_played"] = song["first_played"]
                if song["last_played"] and (
                    existing["last_played"] is None
                    or song["last_played"] > existing["last_played"]
                ):
                    existing["last_played"] = song["last_played"]
            else:
                songs_seen[uri] = song

    logger.info("Parsed %d records, %d unique songs", len(all_records), len(songs_seen))

    inserted = queries.insert_listening_history_batch(conn, all_records)
    logger.info("Inserted %d new listening_history rows", inserted)

    queries.upsert_songs_batch(conn, list(songs_seen.values()))
    logger.info("Upserted %d songs", len(songs_seen))

    _compute_basic_song_stats(conn)

    return {
        "total_records": len(all_records),
        "inserted_history": inserted,
        "total_songs": len(songs_seen),
    }


def _parse_history_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a single extended history JSON record.

    Returns dict with 'history' and 'song' keys, or None if no spotify_track_uri.
    """
    uri = record.get("spotify_track_uri")
    if not uri:
        return None

    track_name = record.get("master_metadata_track_name")
    artist_name = record.get("master_metadata_album_artist_name")
    if not track_name or not artist_name:
        return None

    ts = record.get("ts")
    if not ts:
        return None

    return {
        "history": {
            "spotify_uri": uri,
            "played_at": ts,
            "ms_played": record.get("ms_played", 0),
            "reason_start": record.get("reason_start"),
            "reason_end": record.get("reason_end"),
            "skipped": record.get("skipped"),
            "shuffle": record.get("shuffle"),
            "platform": record.get("platform"),
        },
        "song": {
            "spotify_uri": uri,
            "name": track_name,
            "artist": artist_name,
            "album": record.get("master_metadata_album_album_name"),
            "sources": ["extended_history"],
            "first_played": ts,
            "last_played": ts,
        },
    }


def _compute_basic_song_stats(conn: sqlite3.Connection) -> None:
    """Compute play_count (meaningful listens >30s), first_played, last_played from listening_history."""
    conn.execute("""
        UPDATE songs SET
            play_count = sub.cnt,
            first_played = sub.first_ts,
            last_played = sub.last_ts
        FROM (
            SELECT
                spotify_uri,
                COUNT(*) as cnt,
                MIN(played_at) as first_ts,
                MAX(played_at) as last_ts
            FROM listening_history
            WHERE ms_played >= ?
            GROUP BY spotify_uri
        ) sub
        WHERE songs.spotify_uri = sub.spotify_uri
    """, (MIN_PLAY_DURATION_MS,))
    conn.commit()
    logger.info("Updated play stats for songs (meaningful listens > %dms)", MIN_PLAY_DURATION_MS)


# ---------------------------------------------------------------------------
# Spotify API sync (Tier 3 — needs API keys)
# ---------------------------------------------------------------------------

def sync_liked_songs(conn: sqlite3.Connection, sp: Any) -> int:
    """Pull all liked songs from Spotify and upsert into songs table.

    Returns count of songs processed.
    """
    from spotify.client import get_liked_songs
    tracks = get_liked_songs(sp)
    for track in tracks:
        queries.upsert_song(
            conn,
            uri=track["uri"],
            name=track["name"],
            artist=track["artist"],
            album=track["album"],
            sources=["liked"],
            duration_ms=track.get("duration_ms"),
            release_year=track.get("release_year"),
        )
    logger.info("Synced %d liked songs", len(tracks))
    return len(tracks)


def sync_top_tracks(conn: sqlite3.Connection, sp: Any) -> int:
    """Pull top tracks across all time ranges and upsert into songs table.

    Returns total count of unique tracks processed.
    """
    from spotify.client import get_top_tracks
    seen_uris: set[str] = set()
    for time_range in ("short_term", "medium_term", "long_term"):
        tracks = get_top_tracks(sp, time_range=time_range)
        for track in tracks:
            queries.upsert_song(
                conn,
                uri=track["uri"],
                name=track["name"],
                artist=track["artist"],
                album=track["album"],
                sources=["top_track"],
                duration_ms=track.get("duration_ms"),
                release_year=track.get("release_year"),
            )
            seen_uris.add(track["uri"])
    logger.info("Synced %d unique top tracks", len(seen_uris))
    return len(seen_uris)


def fetch_track_metadata(conn: sqlite3.Connection, sp: Any, min_listens: int = 2) -> int:
    """Fetch duration_ms and release_year for songs missing either field.

    Only fetches songs with at least min_listens plays (default 2 = playlist
    candidates). Songs with 0-1 listens aren't classified and won't be in
    playlists, so fetching their metadata wastes API calls.

    Returns count of songs updated.
    """
    from spotify.client import get_tracks_metadata

    missing_rows = queries.get_songs_missing_metadata(conn, min_listens=min_listens)
    raw_uris = [r["spotify_uri"] for r in missing_rows]

    _SPOTIFY_URI_RE = re.compile(r"^spotify:track:[A-Za-z0-9]+$")
    missing = []
    for uri in raw_uris:
        if _SPOTIFY_URI_RE.match(uri):
            missing.append(uri)
        else:
            logger.warning("Skipping malformed URI: %s", uri)

    logger.info("%d songs missing duration_ms or release_year", len(missing))
    if not missing:
        logger.info("All songs already have metadata")
        return 0

    track_ids = [uri.split(":")[-1] for uri in missing]
    metadata = get_tracks_metadata(sp, track_ids)
    queries.update_song_metadata_batch(conn, metadata)

    logger.info("Fetched metadata for %d songs", len(metadata))
    return len(metadata)


def sync_recently_played(
    conn: sqlite3.Connection,
    sp: Any,
    hours_back: int = 24,
) -> dict[str, int]:
    """Pull recently-played tracks from Spotify and update listening_history + songs.

    Uses sp.current_user_recently_played() to fetch the last 50 plays within
    the lookback window. New songs are upserted; plays are added to
    listening_history (idempotent via UNIQUE constraint).

    Returns dict with plays_added and new_songs counts.
    """
    from datetime import datetime, timedelta, timezone
    from spotify.client import parse_track, SPOTIFY_PAGINATION_THROTTLE_SECONDS
    import time

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    after_ms = int(cutoff.timestamp() * 1000)

    try:
        results = sp.current_user_recently_played(limit=50, after=after_ms)
    except Exception as e:
        logger.warning("Failed to fetch recently-played: %s", e)
        return {"plays_added": 0, "new_songs": 0}

    items = results.get("items", []) if results else []
    if not items:
        logger.info("No recently-played tracks in last %d hours", hours_back)
        return {"plays_added": 0, "new_songs": 0}

    history_records: list[dict] = []
    new_songs = 0

    for item in items:
        track_data = item.get("track")
        played_at = item.get("played_at")
        if not track_data or not played_at:
            continue

        parsed = parse_track(track_data)
        if not parsed:
            continue

        uri = parsed["uri"]
        duration_ms = parsed.get("duration_ms") or 0

        # Upsert song if new
        existing = queries.get_song(conn, uri)
        if not existing:
            queries.upsert_song(
                conn, uri=uri, name=parsed["name"], artist=parsed["artist"],
                album=parsed.get("album"), sources=["recently_played"],
                duration_ms=duration_ms, release_year=parsed.get("release_year"),
                last_played=played_at[:10],
            )
            new_songs += 1

        # Build listening_history record
        # recently-played API doesn't provide ms_played, reason, skipped, etc.
        # Use duration_ms as estimate (if in recently-played, user likely listened)
        history_records.append({
            "spotify_uri": uri,
            "played_at": played_at,
            "ms_played": duration_ms,
            "reason_start": "recently_played",
            "reason_end": None,
            "skipped": 0,
            "shuffle": None,
            "platform": None,
        })

    plays_added = queries.insert_listening_history_batch(conn, history_records)
    logger.info(
        "Recently-played sync: %d plays added, %d new songs (from %d items)",
        plays_added, new_songs, len(items),
    )
    return {"plays_added": plays_added, "new_songs": new_songs}
