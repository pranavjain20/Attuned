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


def fetch_batch_metadata(conn: sqlite3.Connection, sp: Any) -> int:
    """Fetch duration_ms and release_year for all songs missing either field.

    Fetches metadata for every song in the songs table that is missing
    duration_ms or release_year, regardless of play count. Uses the Spotify
    tracks batch endpoint (50 per call).

    Returns count of songs updated.
    """
    from spotify.client import get_tracks_metadata
    from config import SPOTIFY_BATCH_SIZE

    missing_rows = queries.get_songs_missing_metadata(conn)
    raw_uris = [r["spotify_uri"] for r in missing_rows]

    # Validate URI format before hitting the API — one malformed URI fails the batch
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

    updated = 0
    for i in range(0, len(missing), SPOTIFY_BATCH_SIZE):
        batch_uris = missing[i : i + SPOTIFY_BATCH_SIZE]
        # Spotify tracks endpoint expects track IDs, not full URIs
        track_ids = [uri.split(":")[-1] for uri in batch_uris]
        metadata = get_tracks_metadata(sp, track_ids)
        queries.update_song_metadata_batch(conn, metadata)
        updated += len(metadata)

    logger.info("Fetched metadata for %d songs", updated)
    return updated
