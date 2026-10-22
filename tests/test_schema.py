"""Tests for db/schema.py — table creation, constraints, indexes."""

import sqlite3

import pytest

from db.schema import get_connection


class TestGetConnection:
    def test_creates_tables(self, db_conn):
        tables = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "songs", "whoop_recovery", "whoop_sleep", "listening_history",
            "song_classifications", "generated_playlists", "tokens",
        }
        assert expected.issubset(tables)

    def test_wal_mode_enabled(self, db_conn_file):
        mode = db_conn_file.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, db_conn):
        fk = db_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_songs_primary_key_is_uri(self, db_conn):
        db_conn.execute(
            "INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:1', 'Song', 'Artist')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:1', 'Dup', 'Dup')"
            )

    def test_listening_history_unique_constraint(self, db_conn):
        db_conn.execute(
            """INSERT INTO listening_history (spotify_uri, played_at, ms_played)
               VALUES ('uri:1', '2023-01-01T00:00:00Z', 30000)"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                """INSERT INTO listening_history (spotify_uri, played_at, ms_played)
                   VALUES ('uri:1', '2023-01-01T00:00:00Z', 50000)"""
            )

    def test_whoop_recovery_date_unique(self, db_conn):
        db_conn.execute(
            """INSERT INTO whoop_recovery (cycle_id, date) VALUES (1, '2026-03-17')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                """INSERT INTO whoop_recovery (cycle_id, date) VALUES (2, '2026-03-17')"""
            )

    def test_indexes_created(self, db_conn):
        indexes = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_songs_engagement" in indexes
        assert "idx_classifications_bpm" in indexes
        assert "idx_classifications_energy" in indexes
        assert "idx_listening_history_uri" in indexes

    def test_idempotent_creation(self, db_conn):
        """Calling create_tables twice should not error."""
        from db.schema import create_tables
        create_tables(db_conn)
        tables = db_conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        assert tables >= 7

    def test_availability_columns_exist(self, db_conn):
        """Migration adds is_available and availability_checked_at to songs."""
        cols = {r[1] for r in db_conn.execute("PRAGMA table_info(songs)").fetchall()}
        assert "is_available" in cols
        assert "availability_checked_at" in cols

    def test_availability_defaults_null(self, db_conn):
        """New songs have NULL availability (never checked)."""
        db_conn.execute(
            "INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:new', 'New', 'Art')"
        )
        row = db_conn.execute(
            "SELECT is_available, availability_checked_at FROM songs WHERE spotify_uri = 'uri:new'"
        ).fetchone()
        assert row["is_available"] is None
        assert row["availability_checked_at"] is None

    def test_whoop_sleep_has_nap_column(self, db_conn):
        """whoop_sleep stores WHOOP's nap flag so naps can be told apart from the night."""
        cols = {r[1] for r in db_conn.execute("PRAGMA table_info(whoop_sleep)").fetchall()}
        assert "nap" in cols

    def test_nap_migration_adds_column_to_existing_table(self):
        """A database created before the nap column existed gains it on connect."""
        import sqlite3
        from db.schema import create_tables
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE whoop_sleep (sleep_id TEXT PRIMARY KEY, date TEXT NOT NULL)")
        conn.execute("INSERT INTO whoop_sleep (sleep_id, date) VALUES ('old', '2026-03-17')")
        create_tables(conn)
        row = conn.execute("SELECT nap FROM whoop_sleep WHERE sleep_id = 'old'").fetchone()
        assert row[0] is None
        conn.close()

    def test_song_classifications_has_tempo_columns(self, db_conn):
        """Raw tempo readings and the decided tempo live in their own columns."""
        cols = {r[1] for r in db_conn.execute("PRAGMA table_info(song_classifications)").fetchall()}
        assert {"essentia_bpm", "essentia_bpm_confidence", "essentia_degara_bpm",
                "tempocnn_bpm", "soundcharts_tempo", "tempo", "tempo_source",
                "tempo_confidence"} <= cols

    def test_tempo_migration_keeps_existing_bpm(self):
        """An existing database gains the tempo columns; bpm is untouched, tempo starts NULL."""
        import sqlite3
        from db.schema import create_tables
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE song_classifications (spotify_uri TEXT PRIMARY KEY, bpm REAL, energy REAL)")
        conn.execute("INSERT INTO song_classifications VALUES ('uri:old', 154, 0.4)")
        create_tables(conn)
        row = conn.execute(
            "SELECT bpm, tempo, essentia_bpm FROM song_classifications WHERE spotify_uri = 'uri:old'"
        ).fetchone()
        assert tuple(row) == (154, None, None)
        conn.close()
