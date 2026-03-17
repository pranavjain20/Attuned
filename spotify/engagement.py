"""Engagement scoring — compute a 0.0-1.0 score per song from behavioral signals."""

import logging
import math
import sqlite3
from datetime import datetime, timezone

from config import MIN_MEANINGFUL_LISTENS, MIN_PLAY_DURATION_MS

logger = logging.getLogger(__name__)


def compute_engagement_scores(conn: sqlite3.Connection) -> int:
    """Compute and store engagement scores for all eligible songs.

    Eligible = play_count >= MIN_MEANINGFUL_LISTENS.
    Songs with duration_ms get the full 5-component formula.
    Songs missing duration_ms get scored with redistributed weights (no completion_rate).

    Returns count of songs scored.
    """
    _compute_completion_rates(conn)
    _compute_active_play_rates(conn)
    _compute_skip_rates(conn)
    scored = _compute_final_scores(conn)
    logger.info("Computed engagement scores for %d songs", scored)
    return scored


def _compute_completion_rates(conn: sqlite3.Connection) -> None:
    """Set completion_rate = avg(ms_played / duration_ms) for >30s plays, capped at 1.0."""
    conn.execute("""
        UPDATE songs SET completion_rate = sub.rate
        FROM (
            SELECT
                lh.spotify_uri,
                MIN(1.0, AVG(CAST(lh.ms_played AS REAL) / s.duration_ms)) as rate
            FROM listening_history lh
            JOIN songs s ON s.spotify_uri = lh.spotify_uri
            WHERE lh.ms_played >= ?
              AND s.duration_ms IS NOT NULL
              AND s.duration_ms > 0
            GROUP BY lh.spotify_uri
        ) sub
        WHERE songs.spotify_uri = sub.spotify_uri
    """, (MIN_PLAY_DURATION_MS,))
    conn.commit()


def _compute_active_play_rates(conn: sqlite3.Connection) -> None:
    """Set active_play_rate = fraction of >30s plays started by clickrow."""
    conn.execute("""
        UPDATE songs SET active_play_rate = sub.rate
        FROM (
            SELECT
                spotify_uri,
                CAST(SUM(CASE WHEN reason_start = 'clickrow' THEN 1 ELSE 0 END) AS REAL)
                    / COUNT(*) as rate
            FROM listening_history
            WHERE ms_played >= ?
            GROUP BY spotify_uri
        ) sub
        WHERE songs.spotify_uri = sub.spotify_uri
    """, (MIN_PLAY_DURATION_MS,))
    conn.commit()


def _compute_skip_rates(conn: sqlite3.Connection) -> None:
    """Set skip_rate = fraction of >30s plays that ended via fwdbtn or skipped=1."""
    conn.execute("""
        UPDATE songs SET skip_rate = sub.rate
        FROM (
            SELECT
                spotify_uri,
                CAST(SUM(CASE WHEN reason_end = 'fwdbtn' OR skipped = 1 THEN 1 ELSE 0 END) AS REAL)
                    / COUNT(*) as rate
            FROM listening_history
            WHERE ms_played >= ?
            GROUP BY spotify_uri
        ) sub
        WHERE songs.spotify_uri = sub.spotify_uri
    """, (MIN_PLAY_DURATION_MS,))
    conn.commit()


def _compute_final_scores(conn: sqlite3.Connection) -> int:
    """Compute weighted engagement_score for eligible songs. Returns count scored."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get max play count for log normalization
    row = conn.execute(
        "SELECT MAX(play_count) as max_pc FROM songs WHERE play_count >= ?",
        (MIN_MEANINGFUL_LISTENS,),
    ).fetchone()
    max_play_count = row["max_pc"] if row and row["max_pc"] else 0

    if max_play_count == 0:
        return 0

    log_max = math.log(max_play_count + 1)

    eligible = conn.execute("""
        SELECT spotify_uri, play_count, completion_rate, active_play_rate,
               skip_rate, last_played, duration_ms
        FROM songs
        WHERE play_count >= ?
    """, (MIN_MEANINGFUL_LISTENS,)).fetchall()

    scored = 0
    for song in eligible:
        log_play = math.log(song["play_count"] + 1) / log_max

        # Recency: linear decay over 365 days
        recency = 0.0
        if song["last_played"]:
            last = _parse_date(song["last_played"])
            if last:
                days_ago = (datetime.now(timezone.utc) - last).days
                recency = max(0.0, min(1.0, 1.0 - days_ago / 365))

        has_duration = song["duration_ms"] is not None and song["duration_ms"] > 0

        if has_duration:
            completion = min(1.0, song["completion_rate"]) if song["completion_rate"] is not None else 0.5
            active = song["active_play_rate"] if song["active_play_rate"] is not None else 0.5
            skip = song["skip_rate"] if song["skip_rate"] is not None else 0.0

            score = (
                log_play * 0.35
                + completion * 0.25
                + active * 0.20
                + (1 - skip) * 0.10
                + recency * 0.10
            )
        else:
            # No duration → can't compute completion_rate. Redistribute 0.25 weight.
            active = song["active_play_rate"] if song["active_play_rate"] is not None else 0.5
            skip = song["skip_rate"] if song["skip_rate"] is not None else 0.0

            score = (
                log_play * 0.467
                + active * 0.267
                + (1 - skip) * 0.133
                + recency * 0.133
            )

        # Clamp to [0.0, 1.0]
        score = max(0.0, min(1.0, score))

        conn.execute(
            "UPDATE songs SET engagement_score = ? WHERE spotify_uri = ?",
            (round(score, 4), song["spotify_uri"]),
        )
        scored += 1

    conn.commit()
    return scored


def _parse_date(iso_str: str) -> datetime | None:
    """Parse an ISO 8601 date string to a timezone-aware datetime."""
    try:
        # Handle both 'YYYY-MM-DDTHH:MM:SSZ' and 'YYYY-MM-DD' formats
        if "T" in iso_str:
            if iso_str.endswith("Z"):
                return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc)
            return dt.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(iso_str + "T00:00:00+00:00")
    except (ValueError, TypeError):
        return None
