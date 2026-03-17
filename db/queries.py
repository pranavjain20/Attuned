"""Database read/write functions for all tables."""

import json
import math
import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Listening history
# ---------------------------------------------------------------------------

def insert_listening_history_batch(
    conn: sqlite3.Connection,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert listening history records. Returns count of rows inserted.

    Uses INSERT OR IGNORE so re-runs are idempotent (unique on uri+played_at).
    """
    sql = """
        INSERT OR IGNORE INTO listening_history
            (spotify_uri, played_at, ms_played, reason_start, reason_end,
             skipped, shuffle, platform)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            r["spotify_uri"],
            r["played_at"],
            r["ms_played"],
            r.get("reason_start"),
            r.get("reason_end"),
            int(r["skipped"]) if r.get("skipped") is not None else None,
            int(r["shuffle"]) if r.get("shuffle") is not None else None,
            r.get("platform"),
        )
        for r in records
    ]
    cursor = conn.executemany(sql, rows)
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Songs — helpers
# ---------------------------------------------------------------------------

def _merge_sources(existing_json: str, new_sources: list[str]) -> str:
    """Merge existing sources JSON with new source list, return sorted JSON."""
    existing = json.loads(existing_json)
    return json.dumps(sorted(set(existing) | set(new_sources)))


def _earlier_date(a: str | None, b: str | None) -> str | None:
    """Return the earlier of two ISO date strings, ignoring None."""
    dates = [d for d in (a, b) if d]
    return min(dates) if dates else None


def _later_date(a: str | None, b: str | None) -> str | None:
    """Return the later of two ISO date strings, ignoring None."""
    dates = [d for d in (a, b) if d]
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------

def upsert_song(
    conn: sqlite3.Connection,
    uri: str,
    name: str,
    artist: str,
    album: str | None = None,
    sources: list[str] | None = None,
    first_played: str | None = None,
    last_played: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Insert or update a song. Merges sources via set union."""
    sources = sources or []
    existing = conn.execute(
        "SELECT sources FROM songs WHERE spotify_uri = ?", (uri,)
    ).fetchone()

    if existing:
        merged = _merge_sources(existing["sources"], sources)
        updates = ["sources = ?"]
        params: list[Any] = [merged]
        if duration_ms is not None:
            updates.append("duration_ms = ?")
            params.append(duration_ms)
        if last_played is not None:
            updates.append("last_played = MAX(COALESCE(last_played, ''), ?)")
            params.append(last_played)
        params.append(uri)
        conn.execute(
            f"UPDATE songs SET {', '.join(updates)} WHERE spotify_uri = ?",
            params,
        )
    else:
        conn.execute(
            """INSERT INTO songs (spotify_uri, name, artist, album, duration_ms,
                                  sources, first_played, last_played)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (uri, name, artist, album, duration_ms,
             json.dumps(sorted(set(sources))), first_played, last_played),
        )
    conn.commit()


def upsert_songs_batch(
    conn: sqlite3.Connection,
    songs: list[dict[str, Any]],
) -> None:
    """Batch upsert songs. For initial history ingestion where source is always 'extended_history'."""
    for song in songs:
        existing = conn.execute(
            "SELECT sources, first_played, last_played FROM songs WHERE spotify_uri = ?",
            (song["spotify_uri"],),
        ).fetchone()

        if existing:
            merged = _merge_sources(existing["sources"], song.get("sources", []))
            new_first = _earlier_date(existing["first_played"], song.get("first_played"))
            new_last = _later_date(existing["last_played"], song.get("last_played"))
            conn.execute(
                """UPDATE songs SET sources = ?, first_played = ?, last_played = ?
                   WHERE spotify_uri = ?""",
                (merged, new_first, new_last, song["spotify_uri"]),
            )
        else:
            conn.execute(
                """INSERT INTO songs (spotify_uri, name, artist, album, sources,
                                      first_played, last_played)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    song["spotify_uri"],
                    song["name"],
                    song["artist"],
                    song.get("album"),
                    json.dumps(sorted(set(song.get("sources", [])))),
                    song.get("first_played"),
                    song.get("last_played"),
                ),
            )
    conn.commit()


def get_song(conn: sqlite3.Connection, uri: str) -> dict[str, Any] | None:
    """Get a single song by URI."""
    row = conn.execute("SELECT * FROM songs WHERE spotify_uri = ?", (uri,)).fetchone()
    return dict(row) if row else None


def get_songs_missing_duration(conn: sqlite3.Connection) -> list[str]:
    """Return URIs of songs that don't have duration_ms yet."""
    rows = conn.execute(
        "SELECT spotify_uri FROM songs WHERE duration_ms IS NULL"
    ).fetchall()
    return [r["spotify_uri"] for r in rows]


def update_song_duration(conn: sqlite3.Connection, uri: str, duration_ms: int) -> None:
    """Set duration_ms for a song."""
    conn.execute(
        "UPDATE songs SET duration_ms = ? WHERE spotify_uri = ?",
        (duration_ms, uri),
    )
    conn.commit()


def update_song_durations_batch(
    conn: sqlite3.Connection,
    durations: dict[str, int],
) -> None:
    """Batch update duration_ms for multiple songs."""
    conn.executemany(
        "UPDATE songs SET duration_ms = ? WHERE spotify_uri = ?",
        [(ms, uri) for uri, ms in durations.items()],
    )
    conn.commit()


def update_song_play_stats(
    conn: sqlite3.Connection,
    uri: str,
    play_count: int,
    first_played: str | None,
    last_played: str | None,
) -> None:
    """Update play_count, first_played, last_played for a song."""
    conn.execute(
        """UPDATE songs SET play_count = ?, first_played = ?, last_played = ?
           WHERE spotify_uri = ?""",
        (play_count, first_played, last_played, uri),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# WHOOP recovery
# ---------------------------------------------------------------------------

def upsert_whoop_recovery(
    conn: sqlite3.Connection,
    cycle_id: int,
    date: str,
    recovery_score: float | None,
    hrv_rmssd_milli: float | None,
    resting_heart_rate: float | None,
    spo2: float | None = None,
    skin_temp: float | None = None,
) -> None:
    """Insert or update a WHOOP recovery record. Computes ln_rmssd on write."""
    ln_rmssd = math.log(hrv_rmssd_milli) if hrv_rmssd_milli and hrv_rmssd_milli > 0 else None
    conn.execute(
        """INSERT INTO whoop_recovery
               (cycle_id, date, recovery_score, hrv_rmssd_milli, ln_rmssd,
                resting_heart_rate, spo2, skin_temp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(cycle_id) DO UPDATE SET
               date = excluded.date,
               recovery_score = excluded.recovery_score,
               hrv_rmssd_milli = excluded.hrv_rmssd_milli,
               ln_rmssd = excluded.ln_rmssd,
               resting_heart_rate = excluded.resting_heart_rate,
               spo2 = excluded.spo2,
               skin_temp = excluded.skin_temp""",
        (cycle_id, date, recovery_score, hrv_rmssd_milli, ln_rmssd,
         resting_heart_rate, spo2, skin_temp),
    )
    conn.commit()


def get_recovery_by_date(conn: sqlite3.Connection, date: str) -> dict[str, Any] | None:
    """Get recovery record for a given date (YYYY-MM-DD)."""
    row = conn.execute(
        "SELECT * FROM whoop_recovery WHERE date = ?", (date,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# WHOOP sleep
# ---------------------------------------------------------------------------

def upsert_whoop_sleep(
    conn: sqlite3.Connection,
    sleep_id: int | str,
    date: str,
    recovery_cycle_id: int | None = None,
    deep_sleep_ms: int | None = None,
    rem_sleep_ms: int | None = None,
    light_sleep_ms: int | None = None,
    awake_ms: int | None = None,
    sleep_efficiency: float | None = None,
    sleep_performance: float | None = None,
    sleep_consistency: float | None = None,
    respiratory_rate: float | None = None,
    disturbance_count: int | None = None,
    sleep_cycle_count: int | None = None,
    sleep_needed_baseline_ms: int | None = None,
    sleep_needed_debt_ms: int | None = None,
    sleep_needed_strain_ms: int | None = None,
    sleep_needed_nap_ms: int | None = None,
) -> None:
    """Insert or update a WHOOP sleep record."""
    conn.execute(
        """INSERT INTO whoop_sleep
               (sleep_id, date, recovery_cycle_id, deep_sleep_ms, rem_sleep_ms,
                light_sleep_ms, awake_ms, sleep_efficiency, sleep_performance,
                sleep_consistency, respiratory_rate, disturbance_count,
                sleep_cycle_count, sleep_needed_baseline_ms, sleep_needed_debt_ms,
                sleep_needed_strain_ms, sleep_needed_nap_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sleep_id) DO UPDATE SET
               date = excluded.date,
               recovery_cycle_id = excluded.recovery_cycle_id,
               deep_sleep_ms = excluded.deep_sleep_ms,
               rem_sleep_ms = excluded.rem_sleep_ms,
               light_sleep_ms = excluded.light_sleep_ms,
               awake_ms = excluded.awake_ms,
               sleep_efficiency = excluded.sleep_efficiency,
               sleep_performance = excluded.sleep_performance,
               sleep_consistency = excluded.sleep_consistency,
               respiratory_rate = excluded.respiratory_rate,
               disturbance_count = excluded.disturbance_count,
               sleep_cycle_count = excluded.sleep_cycle_count,
               sleep_needed_baseline_ms = excluded.sleep_needed_baseline_ms,
               sleep_needed_debt_ms = excluded.sleep_needed_debt_ms,
               sleep_needed_strain_ms = excluded.sleep_needed_strain_ms,
               sleep_needed_nap_ms = excluded.sleep_needed_nap_ms""",
        (sleep_id, date, recovery_cycle_id, deep_sleep_ms, rem_sleep_ms,
         light_sleep_ms, awake_ms, sleep_efficiency, sleep_performance,
         sleep_consistency, respiratory_rate, disturbance_count,
         sleep_cycle_count, sleep_needed_baseline_ms, sleep_needed_debt_ms,
         sleep_needed_strain_ms, sleep_needed_nap_ms),
    )
    conn.commit()


def get_sleep_by_date(conn: sqlite3.Connection, date: str) -> dict[str, Any] | None:
    """Get sleep record for a given date (YYYY-MM-DD)."""
    row = conn.execute(
        "SELECT * FROM whoop_sleep WHERE date = ?", (date,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def save_token(
    conn: sqlite3.Connection,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: float | None = None,
) -> None:
    """Store or update an OAuth token."""
    conn.execute(
        """INSERT INTO tokens (provider, access_token, refresh_token, expires_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(provider) DO UPDATE SET
               access_token = excluded.access_token,
               refresh_token = COALESCE(excluded.refresh_token, tokens.refresh_token),
               expires_at = excluded.expires_at""",
        (provider, access_token, refresh_token, expires_at),
    )
    conn.commit()


def get_token(conn: sqlite3.Connection, provider: str) -> dict[str, Any] | None:
    """Get stored token for a provider."""
    row = conn.execute(
        "SELECT * FROM tokens WHERE provider = ?", (provider,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

_ALLOWED_TABLES = frozenset({
    "songs", "whoop_recovery", "whoop_sleep", "listening_history",
    "song_classifications", "generated_playlists", "tokens",
})


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Return the row count of a table."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()  # noqa: S608
    return row["cnt"]
