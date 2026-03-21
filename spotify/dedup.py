"""Duplicate song consolidation — merge songs with same name+artist but different Spotify URIs."""

import json
import logging
import sqlite3

from config import MIN_PLAY_DURATION_MS

logger = logging.getLogger(__name__)


def consolidate_duplicate_songs(conn: sqlite3.Connection) -> dict[str, int]:
    """Find and merge duplicate songs that share (name, artist) but have different URIs.

    Spotify re-releases tracks with new URIs. This splits play counts across duplicates.
    For each group, picks a canonical URI (most meaningful listens), reassigns all
    listening_history rows, merges song metadata, and deletes non-canonical rows.

    Returns dict with 'groups' (number of duplicate groups found) and
    'songs_merged' (number of non-canonical songs removed).
    """
    groups = _find_duplicate_groups(conn)
    if not groups:
        logger.info("No duplicate song groups found")
        return {"groups": 0, "songs_merged": 0}

    logger.info("Found %d duplicate groups to consolidate", len(groups))
    total_merged = 0

    conn.execute("BEGIN")
    try:
        for name, artist, uris in groups:
            canonical = _pick_canonical_uri(conn, uris)
            others = [u for u in uris if u != canonical]
            logger.info(
                "Merging '%s' by %s: keeping %s, merging %d duplicates",
                name, artist, canonical, len(others),
            )
            _reassign_listening_history(conn, canonical, others)
            _merge_song_metadata(conn, canonical, others)
            _delete_duplicate_classifications(conn, others)
            _delete_duplicate_songs(conn, others)
            total_merged += len(others)

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Recompute play stats now that listening_history URIs have changed
    from spotify.sync import _compute_basic_song_stats
    _compute_basic_song_stats(conn)

    logger.info("Consolidated %d groups, merged %d duplicate songs", len(groups), total_merged)
    return {"groups": len(groups), "songs_merged": total_merged}


def _find_duplicate_groups(conn: sqlite3.Connection) -> list[tuple[str, str, list[str]]]:
    """Find all (name, artist) pairs with multiple URIs.

    Returns list of (name, artist, [uri1, uri2, ...]) tuples.
    """
    rows = conn.execute("""
        SELECT LOWER(TRIM(name)) as norm_name, LOWER(TRIM(artist)) as norm_artist,
               GROUP_CONCAT(spotify_uri) as uris
        FROM songs
        GROUP BY norm_name, norm_artist
        HAVING COUNT(*) > 1
    """).fetchall()

    return [
        (row["norm_name"], row["norm_artist"], row["uris"].split(","))
        for row in rows
    ]


def _pick_canonical_uri(conn: sqlite3.Connection, uris: list[str]) -> str:
    """Pick the canonical URI from a group of duplicates.

    Priority: most listening_history rows (>= 30s plays).
    Tiebreaker: prefer URIs whose song has 'liked' or 'top_track' in sources.
    Final tiebreaker: lexicographic (deterministic).
    """
    placeholders = ",".join("?" for _ in uris)

    # Count meaningful plays per URI
    play_counts = conn.execute(f"""
        SELECT spotify_uri, COUNT(*) as cnt
        FROM listening_history
        WHERE spotify_uri IN ({placeholders})
          AND ms_played >= ?
        GROUP BY spotify_uri
    """, (*uris, MIN_PLAY_DURATION_MS)).fetchall()

    counts: dict[str, int] = {row["spotify_uri"]: row["cnt"] for row in play_counts}

    # Check sources for tiebreaker
    source_rows = conn.execute(f"""
        SELECT spotify_uri, sources
        FROM songs
        WHERE spotify_uri IN ({placeholders})
    """, uris).fetchall()

    preferred_sources: dict[str, bool] = {}
    for row in source_rows:
        sources = json.loads(row["sources"])
        preferred_sources[row["spotify_uri"]] = (
            "liked" in sources or "top_track" in sources
        )

    def sort_key(uri: str) -> tuple[int, int, str]:
        return (
            counts.get(uri, 0),
            1 if preferred_sources.get(uri, False) else 0,
            uri,  # lexicographic tiebreaker — max() picks highest URI
        )

    # Sort descending by play count, then preferred source, then ascending URI
    return max(uris, key=sort_key)


def _reassign_listening_history(
    conn: sqlite3.Connection,
    canonical: str,
    others: list[str],
) -> None:
    """Move all listening_history rows from other URIs to the canonical URI.

    Uses INSERT OR IGNORE + DELETE to handle (spotify_uri, played_at) uniqueness
    conflicts — if the canonical already has a play at the same timestamp, the
    duplicate row is silently dropped (it's the same play event from a re-released URI).
    """
    placeholders = ",".join("?" for _ in others)

    # Count rows before reassignment for conflict logging
    before = conn.execute(f"""
        SELECT COUNT(*) as cnt FROM listening_history
        WHERE spotify_uri IN ({placeholders})
    """, others).fetchone()["cnt"]

    # Insert rows that don't conflict
    conn.execute(f"""
        INSERT OR IGNORE INTO listening_history
            (spotify_uri, played_at, ms_played, reason_start, reason_end,
             skipped, shuffle, platform)
        SELECT ?, played_at, ms_played, reason_start, reason_end,
               skipped, shuffle, platform
        FROM listening_history
        WHERE spotify_uri IN ({placeholders})
    """, (canonical, *others))

    # Delete the old rows (including any that conflicted — they're duplicates)
    conn.execute(f"""
        DELETE FROM listening_history
        WHERE spotify_uri IN ({placeholders})
    """, others)

    # Log reassignment
    if before > 0:
        logger.debug("Reassigned %d rows to %s", before, canonical)


def _merge_song_metadata(
    conn: sqlite3.Connection,
    canonical: str,
    others: list[str],
) -> None:
    """Merge sources, first_played, last_played, and duration_ms from duplicates into canonical."""
    all_uris = [canonical] + others
    placeholders = ",".join("?" for _ in all_uris)

    rows = conn.execute(f"""
        SELECT spotify_uri, sources, first_played, last_played, duration_ms
        FROM songs
        WHERE spotify_uri IN ({placeholders})
    """, all_uris).fetchall()

    merged_sources: set[str] = set()
    earliest_played: str | None = None
    latest_played: str | None = None
    canonical_duration: int | None = None

    for row in rows:
        sources = json.loads(row["sources"])
        merged_sources.update(sources)

        fp = row["first_played"]
        lp = row["last_played"]
        if fp and (earliest_played is None or fp < earliest_played):
            earliest_played = fp
        if lp and (latest_played is None or lp > latest_played):
            latest_played = lp

        if row["spotify_uri"] == canonical and row["duration_ms"]:
            canonical_duration = row["duration_ms"]

    # If canonical has no duration, grab from any duplicate that does
    if canonical_duration is None:
        for row in rows:
            if row["duration_ms"]:
                canonical_duration = row["duration_ms"]
                break

    conn.execute("""
        UPDATE songs
        SET sources = ?, first_played = ?, last_played = ?, duration_ms = ?
        WHERE spotify_uri = ?
    """, (
        json.dumps(sorted(merged_sources)),
        earliest_played,
        latest_played,
        canonical_duration,
        canonical,
    ))


def _delete_duplicate_classifications(conn: sqlite3.Connection, others: list[str]) -> None:
    """Remove song_classifications rows for non-canonical URIs."""
    placeholders = ",".join("?" for _ in others)
    conn.execute(f"""
        DELETE FROM song_classifications
        WHERE spotify_uri IN ({placeholders})
    """, others)


def _delete_duplicate_songs(conn: sqlite3.Connection, others: list[str]) -> None:
    """Remove non-canonical song rows."""
    placeholders = ",".join("?" for _ in others)
    conn.execute(f"""
        DELETE FROM songs
        WHERE spotify_uri IN ({placeholders})
    """, others)
