"""SQLite schema definitions and connection management."""

import sqlite3
from pathlib import Path

from config import DB_PATH


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create or open a SQLite database, enable WAL + foreign keys, ensure tables exist."""
    path = str(db_path) if db_path else str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    create_tables(conn)
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    conn.executescript(_SCHEMA_SQL)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS songs (
    spotify_uri     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    artist          TEXT NOT NULL,
    album           TEXT,
    duration_ms     INTEGER,
    sources         TEXT NOT NULL DEFAULT '[]',   -- JSON list, e.g. ["liked","extended_history"]
    play_count      INTEGER DEFAULT 0,
    completion_rate REAL,
    active_play_rate REAL,
    skip_rate       REAL,
    engagement_score REAL,
    first_played    TEXT,                          -- ISO 8601
    last_played     TEXT                           -- ISO 8601
);

CREATE TABLE IF NOT EXISTS whoop_recovery (
    cycle_id            INTEGER PRIMARY KEY,
    date                TEXT NOT NULL UNIQUE,      -- YYYY-MM-DD, derived from cycle end time
    recovery_score      REAL,
    hrv_rmssd_milli     REAL,
    ln_rmssd            REAL,                      -- log(hrv_rmssd_milli), computed on storage
    resting_heart_rate  REAL,
    spo2                REAL,
    skin_temp           REAL
);

CREATE TABLE IF NOT EXISTS whoop_sleep (
    sleep_id            INTEGER PRIMARY KEY,
    date                TEXT NOT NULL,             -- YYYY-MM-DD, derived from sleep end time
    recovery_cycle_id   INTEGER,
    deep_sleep_ms       INTEGER,
    rem_sleep_ms        INTEGER,
    light_sleep_ms      INTEGER,
    awake_ms            INTEGER,
    sleep_efficiency    REAL,
    sleep_performance   REAL,
    sleep_consistency   REAL,
    respiratory_rate    REAL,
    disturbance_count   INTEGER,
    sleep_cycle_count   INTEGER,
    sleep_needed_baseline_ms  INTEGER,
    sleep_needed_debt_ms      INTEGER,
    sleep_needed_strain_ms    INTEGER,
    sleep_needed_nap_ms       INTEGER,
    FOREIGN KEY (recovery_cycle_id) REFERENCES whoop_recovery(cycle_id)
);

CREATE TABLE IF NOT EXISTS listening_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_uri     TEXT NOT NULL,
    played_at       TEXT NOT NULL,                -- ISO 8601
    ms_played       INTEGER NOT NULL,
    reason_start    TEXT,
    reason_end      TEXT,
    skipped         INTEGER,                      -- 0 or 1
    shuffle         INTEGER,                      -- 0 or 1
    platform        TEXT,
    UNIQUE(spotify_uri, played_at)
);

CREATE TABLE IF NOT EXISTS song_classifications (
    spotify_uri     TEXT PRIMARY KEY,
    bpm             REAL,
    key             TEXT,
    mode            TEXT,
    energy          REAL,
    valence         REAL,
    acousticness    REAL,
    danceability    REAL,
    instrumentalness REAL,
    mood_tags       TEXT,                          -- JSON list
    genre_tags      TEXT,                          -- JSON list
    confidence      REAL,
    parasympathetic REAL,
    sympathetic     REAL,
    grounding       REAL,
    classification_source TEXT,
    raw_response    TEXT,
    FOREIGN KEY (spotify_uri) REFERENCES songs(spotify_uri)
);

CREATE TABLE IF NOT EXISTS generated_playlists (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_playlist_id TEXT,
    date                TEXT NOT NULL,
    detected_state      TEXT NOT NULL,
    reasoning           TEXT,
    whoop_metrics       TEXT,                      -- JSON blob
    track_uris          TEXT,                      -- JSON array
    description         TEXT
);

CREATE TABLE IF NOT EXISTS tokens (
    provider        TEXT PRIMARY KEY,              -- 'whoop' or 'spotify'
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    expires_at      REAL                           -- Unix timestamp
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_songs_engagement ON songs(engagement_score);
CREATE INDEX IF NOT EXISTS idx_classifications_bpm ON song_classifications(bpm);
CREATE INDEX IF NOT EXISTS idx_classifications_energy ON song_classifications(energy);
CREATE INDEX IF NOT EXISTS idx_listening_history_uri ON listening_history(spotify_uri);
CREATE INDEX IF NOT EXISTS idx_listening_history_played_at ON listening_history(played_at);
CREATE INDEX IF NOT EXISTS idx_whoop_recovery_date ON whoop_recovery(date);
CREATE INDEX IF NOT EXISTS idx_whoop_sleep_date ON whoop_sleep(date);
"""
