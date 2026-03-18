"""Tests for db/queries.py — all database read/write functions."""

import json
import math

import pytest

from db import queries


class TestInsertListeningHistoryBatch:
    def test_inserts_records(self, db_conn):
        records = [
            {"spotify_uri": "uri:1", "played_at": "2023-01-01T00:00:00Z",
             "ms_played": 30000, "reason_start": "clickrow", "reason_end": "trackdone",
             "skipped": False, "shuffle": False, "platform": "iOS"},
            {"spotify_uri": "uri:2", "played_at": "2023-01-01T01:00:00Z",
             "ms_played": 45000, "reason_start": "trackdone", "reason_end": "fwdbtn",
             "skipped": True, "shuffle": True, "platform": "android"},
        ]
        inserted = queries.insert_listening_history_batch(db_conn, records)
        assert inserted == 2
        assert queries.count_rows(db_conn, "listening_history") == 2

    def test_ignores_duplicates(self, db_conn):
        records = [
            {"spotify_uri": "uri:1", "played_at": "2023-01-01T00:00:00Z",
             "ms_played": 30000},
        ]
        queries.insert_listening_history_batch(db_conn, records)
        inserted = queries.insert_listening_history_batch(db_conn, records)
        # INSERT OR IGNORE — rowcount is 0 for ignored rows
        assert queries.count_rows(db_conn, "listening_history") == 1

    def test_handles_empty_list(self, db_conn):
        inserted = queries.insert_listening_history_batch(db_conn, [])
        assert queries.count_rows(db_conn, "listening_history") == 0

    def test_handles_none_optional_fields(self, db_conn):
        records = [
            {"spotify_uri": "uri:1", "played_at": "2023-01-01T00:00:00Z",
             "ms_played": 30000},
        ]
        queries.insert_listening_history_batch(db_conn, records)
        row = db_conn.execute("SELECT * FROM listening_history").fetchone()
        assert row["reason_start"] is None
        assert row["skipped"] is None


class TestUpsertSong:
    def test_insert_new_song(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist", "Album",
                            sources=["liked"], first_played="2023-01-01")
        song = queries.get_song(db_conn, "uri:1")
        assert song["name"] == "Song"
        assert json.loads(song["sources"]) == ["liked"]

    def test_merges_sources(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist",
                            sources=["liked"])
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist",
                            sources=["extended_history"])
        song = queries.get_song(db_conn, "uri:1")
        sources = json.loads(song["sources"])
        assert "liked" in sources
        assert "extended_history" in sources

    def test_updates_duration(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        assert queries.get_song(db_conn, "uri:1")["duration_ms"] is None
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist", duration_ms=240000)
        assert queries.get_song(db_conn, "uri:1")["duration_ms"] == 240000

    def test_updates_last_played(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist",
                            last_played="2023-01-01")
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist",
                            last_played="2023-06-01")
        song = queries.get_song(db_conn, "uri:1")
        assert song["last_played"] == "2023-06-01"


class TestUpsertSongsBatch:
    def test_batch_insert(self, db_conn):
        songs = [
            {"spotify_uri": "uri:1", "name": "A", "artist": "X",
             "sources": ["extended_history"], "first_played": "2023-01-01",
             "last_played": "2023-06-01"},
            {"spotify_uri": "uri:2", "name": "B", "artist": "Y",
             "sources": ["extended_history"], "first_played": "2023-02-01",
             "last_played": "2023-05-01"},
        ]
        queries.upsert_songs_batch(db_conn, songs)
        assert queries.count_rows(db_conn, "songs") == 2

    def test_batch_merges_dates(self, db_conn):
        songs1 = [
            {"spotify_uri": "uri:1", "name": "A", "artist": "X",
             "sources": ["extended_history"],
             "first_played": "2023-03-01", "last_played": "2023-06-01"},
        ]
        songs2 = [
            {"spotify_uri": "uri:1", "name": "A", "artist": "X",
             "sources": ["liked"],
             "first_played": "2023-01-01", "last_played": "2023-09-01"},
        ]
        queries.upsert_songs_batch(db_conn, songs1)
        queries.upsert_songs_batch(db_conn, songs2)
        song = queries.get_song(db_conn, "uri:1")
        assert song["first_played"] == "2023-01-01"
        assert song["last_played"] == "2023-09-01"
        sources = json.loads(song["sources"])
        assert "extended_history" in sources
        assert "liked" in sources


class TestGetSongsMissingDuration:
    def test_returns_uris_without_duration(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "A", "X")
        queries.upsert_song(db_conn, "uri:2", "B", "Y", duration_ms=240000)
        missing = queries.get_songs_missing_duration(db_conn)
        assert missing == ["uri:1"]

    def test_returns_empty_when_all_have_duration(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "A", "X", duration_ms=200000)
        assert queries.get_songs_missing_duration(db_conn) == []


class TestWhoopRecovery:
    def test_upsert_inserts_with_ln_rmssd(self, db_conn):
        queries.upsert_whoop_recovery(
            db_conn, cycle_id=1, date="2026-03-17",
            recovery_score=72.0, hrv_rmssd_milli=55.3,
            resting_heart_rate=58.0, spo2=97.5, skin_temp=33.2,
        )
        row = queries.get_recovery_by_date(db_conn, "2026-03-17")
        assert row is not None
        assert row["recovery_score"] == 72.0
        assert row["hrv_rmssd_milli"] == 55.3
        assert abs(row["ln_rmssd"] - math.log(55.3)) < 0.001
        assert row["resting_heart_rate"] == 58.0

    def test_upsert_updates_existing(self, db_conn):
        queries.upsert_whoop_recovery(
            db_conn, cycle_id=1, date="2026-03-17",
            recovery_score=72.0, hrv_rmssd_milli=55.3, resting_heart_rate=58.0,
        )
        queries.upsert_whoop_recovery(
            db_conn, cycle_id=1, date="2026-03-17",
            recovery_score=80.0, hrv_rmssd_milli=62.1, resting_heart_rate=55.0,
        )
        row = queries.get_recovery_by_date(db_conn, "2026-03-17")
        assert row["recovery_score"] == 80.0
        assert row["hrv_rmssd_milli"] == 62.1

    def test_ln_rmssd_none_when_hrv_is_none(self, db_conn):
        queries.upsert_whoop_recovery(
            db_conn, cycle_id=1, date="2026-03-17",
            recovery_score=50.0, hrv_rmssd_milli=None, resting_heart_rate=60.0,
        )
        row = queries.get_recovery_by_date(db_conn, "2026-03-17")
        assert row["ln_rmssd"] is None

    def test_returns_none_for_missing_date(self, db_conn):
        assert queries.get_recovery_by_date(db_conn, "2026-01-01") is None


class TestGetRecoveriesInRange:
    def test_returns_records_in_range(self, db_conn):
        for i, date in enumerate(["2026-03-10", "2026-03-12", "2026-03-14"]):
            queries.upsert_whoop_recovery(
                db_conn, cycle_id=i + 1, date=date,
                recovery_score=70.0, hrv_rmssd_milli=50.0, resting_heart_rate=60.0,
            )
        results = queries.get_recoveries_in_range(db_conn, "2026-03-10", "2026-03-13")
        assert len(results) == 2
        assert results[0]["date"] == "2026-03-10"
        assert results[1]["date"] == "2026-03-12"

    def test_inclusive_boundaries(self, db_conn):
        queries.upsert_whoop_recovery(
            db_conn, cycle_id=1, date="2026-03-10",
            recovery_score=70.0, hrv_rmssd_milli=50.0, resting_heart_rate=60.0,
        )
        results = queries.get_recoveries_in_range(db_conn, "2026-03-10", "2026-03-10")
        assert len(results) == 1

    def test_empty_for_no_data(self, db_conn):
        results = queries.get_recoveries_in_range(db_conn, "2026-03-01", "2026-03-31")
        assert results == []

    def test_ordered_ascending(self, db_conn):
        for i, date in enumerate(["2026-03-15", "2026-03-11", "2026-03-13"]):
            queries.upsert_whoop_recovery(
                db_conn, cycle_id=i + 1, date=date,
                recovery_score=70.0, hrv_rmssd_milli=50.0, resting_heart_rate=60.0,
            )
        results = queries.get_recoveries_in_range(db_conn, "2026-03-01", "2026-03-31")
        dates = [r["date"] for r in results]
        assert dates == ["2026-03-11", "2026-03-13", "2026-03-15"]


class TestGetSleepsInRange:
    def test_returns_records_in_range(self, db_conn):
        for i, date in enumerate(["2026-03-10", "2026-03-12", "2026-03-14"]):
            queries.upsert_whoop_sleep(
                db_conn, sleep_id=i + 100, date=date,
                deep_sleep_ms=5_000_000, rem_sleep_ms=6_000_000,
                light_sleep_ms=14_000_000,
            )
        results = queries.get_sleeps_in_range(db_conn, "2026-03-10", "2026-03-13")
        assert len(results) == 2

    def test_inclusive_boundaries(self, db_conn):
        queries.upsert_whoop_sleep(
            db_conn, sleep_id=100, date="2026-03-10",
            deep_sleep_ms=5_000_000,
        )
        results = queries.get_sleeps_in_range(db_conn, "2026-03-10", "2026-03-10")
        assert len(results) == 1

    def test_empty_for_no_data(self, db_conn):
        results = queries.get_sleeps_in_range(db_conn, "2026-03-01", "2026-03-31")
        assert results == []

    def test_ordered_ascending(self, db_conn):
        for i, date in enumerate(["2026-03-15", "2026-03-11", "2026-03-13"]):
            queries.upsert_whoop_sleep(
                db_conn, sleep_id=i + 100, date=date,
                deep_sleep_ms=5_000_000,
            )
        results = queries.get_sleeps_in_range(db_conn, "2026-03-01", "2026-03-31")
        dates = [r["date"] for r in results]
        assert dates == ["2026-03-11", "2026-03-13", "2026-03-15"]


class TestWhoopSleep:
    def test_upsert_inserts(self, db_conn):
        # Need a recovery record for the FK
        queries.upsert_whoop_recovery(
            db_conn, cycle_id=1, date="2026-03-17",
            recovery_score=72.0, hrv_rmssd_milli=55.3, resting_heart_rate=58.0,
        )
        queries.upsert_whoop_sleep(
            db_conn, sleep_id=100, date="2026-03-17", recovery_cycle_id=1,
            deep_sleep_ms=5400000, rem_sleep_ms=7200000,
            light_sleep_ms=14400000, awake_ms=1800000,
            sleep_efficiency=92.5,
        )
        row = queries.get_sleep_by_date(db_conn, "2026-03-17")
        assert row is not None
        assert row["deep_sleep_ms"] == 5400000
        assert row["sleep_efficiency"] == 92.5

    def test_upsert_updates_existing(self, db_conn):
        queries.upsert_whoop_sleep(
            db_conn, sleep_id=100, date="2026-03-17",
            deep_sleep_ms=5000000,
        )
        queries.upsert_whoop_sleep(
            db_conn, sleep_id=100, date="2026-03-17",
            deep_sleep_ms=6000000,
        )
        row = queries.get_sleep_by_date(db_conn, "2026-03-17")
        assert row["deep_sleep_ms"] == 6000000

    def test_returns_none_for_missing_date(self, db_conn):
        assert queries.get_sleep_by_date(db_conn, "2026-01-01") is None


class TestTokens:
    def test_save_and_get_token(self, db_conn):
        queries.save_token(db_conn, "whoop", "access123", "refresh456", 9999999999.0)
        token = queries.get_token(db_conn, "whoop")
        assert token["access_token"] == "access123"
        assert token["refresh_token"] == "refresh456"
        assert token["expires_at"] == 9999999999.0

    def test_update_preserves_refresh_token(self, db_conn):
        queries.save_token(db_conn, "whoop", "access1", "refresh1", 100.0)
        queries.save_token(db_conn, "whoop", "access2", None, 200.0)
        token = queries.get_token(db_conn, "whoop")
        assert token["access_token"] == "access2"
        assert token["refresh_token"] == "refresh1"  # preserved

    def test_returns_none_for_missing_provider(self, db_conn):
        assert queries.get_token(db_conn, "nonexistent") is None


class TestCountRows:
    def test_empty_table(self, db_conn):
        assert queries.count_rows(db_conn, "songs") == 0

    def test_after_inserts(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "A", "X")
        queries.upsert_song(db_conn, "uri:2", "B", "Y")
        assert queries.count_rows(db_conn, "songs") == 2

    def test_rejects_invalid_table_name(self, db_conn):
        with pytest.raises(ValueError, match="Invalid table name"):
            queries.count_rows(db_conn, "songs; DROP TABLE songs;--")
