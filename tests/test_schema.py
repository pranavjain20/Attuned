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
