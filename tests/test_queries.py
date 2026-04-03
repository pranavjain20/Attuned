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


class TestGetUnclassifiedSongs:
    def _insert_song(self, db_conn, uri, play_count):
        queries.upsert_song(db_conn, uri, f"Song {uri}", f"Artist {uri}")
        db_conn.execute(
            "UPDATE songs SET play_count = ? WHERE spotify_uri = ?",
            (play_count, uri),
        )
        db_conn.commit()

    def test_returns_eligible_songs(self, db_conn):
        self._insert_song(db_conn, "uri:1", 10)
        self._insert_song(db_conn, "uri:2", 5)
        result = queries.get_unclassified_songs(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:1" in uris
        assert "uri:2" in uris

    def test_excludes_low_play_count(self, db_conn):
        self._insert_song(db_conn, "uri:high", 10)
        self._insert_song(db_conn, "uri:low", 1)
        result = queries.get_unclassified_songs(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:high" in uris
        assert "uri:low" not in uris

    def test_excludes_already_classified(self, db_conn):
        self._insert_song(db_conn, "uri:1", 10)
        self._insert_song(db_conn, "uri:2", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 120, "classification_source": "essentia",
        })
        result = queries.get_unclassified_songs(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:1" not in uris
        assert "uri:2" in uris

    def test_ordered_by_play_count_desc(self, db_conn):
        self._insert_song(db_conn, "uri:low", 5)
        self._insert_song(db_conn, "uri:high", 50)
        self._insert_song(db_conn, "uri:mid", 20)
        result = queries.get_unclassified_songs(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert uris == ["uri:high", "uri:mid", "uri:low"]

    def test_returns_empty_when_all_classified(self, db_conn):
        self._insert_song(db_conn, "uri:1", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 120, "classification_source": "essentia",
        })
        assert queries.get_unclassified_songs(db_conn) == []


class TestGetSongsNeedingLlm:
    def _insert_song(self, db_conn, uri, play_count):
        queries.upsert_song(db_conn, uri, f"Song {uri}", f"Artist {uri}")
        db_conn.execute(
            "UPDATE songs SET play_count = ? WHERE spotify_uri = ?",
            (play_count, uri),
        )
        db_conn.commit()

    def test_returns_unclassified_songs(self, db_conn):
        """Songs not in song_classifications at all should be returned."""
        self._insert_song(db_conn, "uri:1", 10)
        self._insert_song(db_conn, "uri:2", 5)
        result = queries.get_songs_needing_llm(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:1" in uris
        assert "uri:2" in uris

    def test_returns_essentia_only_songs(self, db_conn):
        """Songs with Essentia classification but no valence should be returned."""
        self._insert_song(db_conn, "uri:1", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "classification_source": "essentia",
            # No valence — Essentia can't compute it
        })
        result = queries.get_songs_needing_llm(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:1" in uris

    def test_essentia_only_returns_essentia_values(self, db_conn):
        """Returned rows should include existing Essentia values for merge."""
        self._insert_song(db_conn, "uri:1", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "essentia_energy": 0.7, "essentia_acousticness": 0.3,
            "classification_source": "essentia",
        })
        result = queries.get_songs_needing_llm(db_conn)
        assert len(result) == 1
        assert result[0]["essentia_bpm"] == 120
        assert result[0]["essentia_key"] == "A"
        assert result[0]["essentia_mode"] == "minor"
        assert result[0]["essentia_energy"] == 0.7
        assert result[0]["essentia_acousticness"] == 0.3

    def test_excludes_fully_classified(self, db_conn):
        """Songs with valence set should NOT be returned (fully classified)."""
        self._insert_song(db_conn, "uri:1", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "valence": 0.6,
            "classification_source": "essentia+llm",
        })
        result = queries.get_songs_needing_llm(db_conn)
        assert len(result) == 0

    def test_excludes_low_play_count(self, db_conn):
        self._insert_song(db_conn, "uri:high", 10)
        self._insert_song(db_conn, "uri:low", 1)
        result = queries.get_songs_needing_llm(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:high" in uris
        assert "uri:low" not in uris

    def test_ordered_by_play_count_desc(self, db_conn):
        self._insert_song(db_conn, "uri:low", 3)
        self._insert_song(db_conn, "uri:high", 50)
        self._insert_song(db_conn, "uri:mid", 20)
        result = queries.get_songs_needing_llm(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert uris == ["uri:high", "uri:mid", "uri:low"]

    def test_unclassified_has_null_essentia_values(self, db_conn):
        """Songs never classified should have NULL Essentia columns."""
        self._insert_song(db_conn, "uri:1", 10)
        result = queries.get_songs_needing_llm(db_conn)
        assert result[0]["essentia_bpm"] is None
        assert result[0]["essentia_key"] is None
        assert result[0]["classification_source"] is None

    def test_mix_of_unclassified_and_essentia_only(self, db_conn):
        """Both types should be returned together."""
        self._insert_song(db_conn, "uri:new", 10)
        self._insert_song(db_conn, "uri:essentia", 20)
        self._insert_song(db_conn, "uri:done", 30)

        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:essentia",
            "bpm": 120, "energy": 0.7,
            "classification_source": "essentia",
        })
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:done",
            "bpm": 120, "valence": 0.6,
            "classification_source": "essentia+llm",
        })

        result = queries.get_songs_needing_llm(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:essentia" in uris
        assert "uri:new" in uris
        assert "uri:done" not in uris

    def test_exact_min_classification_listens_boundary(self, db_conn):
        """Song at exactly MIN_CLASSIFICATION_LISTENS should be included."""
        from config import MIN_CLASSIFICATION_LISTENS
        self._insert_song(db_conn, "uri:at_boundary", MIN_CLASSIFICATION_LISTENS)
        self._insert_song(db_conn, "uri:below", MIN_CLASSIFICATION_LISTENS - 1)
        result = queries.get_songs_needing_llm(db_conn)
        uris = [r["spotify_uri"] for r in result]
        assert "uri:at_boundary" in uris
        assert "uri:below" not in uris

    def test_valence_zero_is_not_null(self, db_conn):
        """Song with valence=0.0 should be excluded (fully classified, not NULL)."""
        self._insert_song(db_conn, "uri:1", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "valence": 0.0,
            "classification_source": "essentia+llm",
        })
        result = queries.get_songs_needing_llm(db_conn)
        assert len(result) == 0

    def test_reclassify_returns_all_eligible(self, db_conn):
        """reclassify=True returns ALL eligible songs, including fully classified."""
        self._insert_song(db_conn, "uri:new", 10)
        self._insert_song(db_conn, "uri:done", 20)
        self._insert_song(db_conn, "uri:low", 1)  # Below threshold

        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:done",
            "bpm": 120, "valence": 0.6,
            "classification_source": "essentia+llm",
        })

        # Default: only uri:new (uri:done has valence, uri:low below threshold)
        default = queries.get_songs_needing_llm(db_conn, reclassify=False)
        uris_default = [r["spotify_uri"] for r in default]
        assert "uri:new" in uris_default
        assert "uri:done" not in uris_default

        # Reclassify: both uri:new and uri:done (uri:low still excluded)
        reclass = queries.get_songs_needing_llm(db_conn, reclassify=True)
        uris_reclass = [r["spotify_uri"] for r in reclass]
        assert "uri:new" in uris_reclass
        assert "uri:done" in uris_reclass
        assert "uri:low" not in uris_reclass

    def test_reclassify_returns_essentia_values(self, db_conn):
        """Reclassify mode should still return existing Essentia values for merge."""
        self._insert_song(db_conn, "uri:1", 10)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "essentia_energy": 0.7, "essentia_acousticness": 0.3,
            "valence": 0.6,
            "classification_source": "essentia+llm",
        })
        result = queries.get_songs_needing_llm(db_conn, reclassify=True)
        assert len(result) == 1
        assert result[0]["essentia_bpm"] == 120
        assert result[0]["essentia_key"] == "A"
        assert result[0]["essentia_energy"] == 0.7


class TestUpsertSongClassification:
    def test_inserts_new_classification(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 128,
            "key": "C",
            "mode": "major",
            "energy": 0.75,
            "acousticness": 0.2,
            "danceability": 0.8,
            "instrumentalness": 0.1,
            "classification_source": "essentia",
            "classified_at": "2026-03-18T10:00:00",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert len(rows) == 1
        assert rows[0]["bpm"] == 128
        assert rows[0]["key"] == "C"
        assert rows[0]["mode"] == "major"

    def test_updates_existing_classification(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 100, "classification_source": "essentia",
        })
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 128, "classification_source": "essentia",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert len(rows) == 1
        assert rows[0]["bpm"] == 128

    def test_json_roundtrip_for_tags(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "mood_tags": ["melancholy", "introspective"],
            "genre_tags": ["bollywood", "romantic"],
            "classification_source": "llm",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["mood_tags"] == ["melancholy", "introspective"]
        assert rows[0]["genre_tags"] == ["bollywood", "romantic"]

    def test_null_tags_remain_none(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 100, "classification_source": "essentia",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["mood_tags"] is None
        assert rows[0]["genre_tags"] is None

    def test_felt_tempo_stored_and_retrieved(self, db_conn):
        """Felt tempo should roundtrip through upsert + get."""
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "felt_tempo": 60,
            "classification_source": "llm",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["felt_tempo"] == 60

    def test_felt_tempo_null_when_not_set(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1",
            "bpm": 120, "classification_source": "llm",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["felt_tempo"] is None

    def test_felt_tempo_updated_on_reclassify(self, db_conn):
        """Reclassification should update felt_tempo."""
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 120, "classification_source": "llm",
        })
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 120, "felt_tempo": 80,
            "classification_source": "llm",
        })
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["felt_tempo"] == 80


class TestGetSongClassifications:
    def test_fetch_by_uris(self, db_conn):
        for uri in ["uri:1", "uri:2", "uri:3"]:
            queries.upsert_song(db_conn, uri, f"Song {uri}", "Artist")
            queries.upsert_song_classification(db_conn, {
                "spotify_uri": uri, "bpm": 100, "classification_source": "essentia",
            })
        results = queries.get_song_classifications(db_conn, ["uri:1", "uri:3"])
        uris = {r["spotify_uri"] for r in results}
        assert uris == {"uri:1", "uri:3"}

    def test_empty_list_returns_empty(self, db_conn):
        assert queries.get_song_classifications(db_conn, []) == []

    def test_missing_uris_not_returned(self, db_conn):
        results = queries.get_song_classifications(db_conn, ["uri:nonexistent"])
        assert results == []


class TestGetAllClassifiedSongs:
    @staticmethod
    def _add_personal_play(conn, uri):
        """Add a personal-device listening history entry so the song passes the autoplay filter."""
        conn.execute(
            """INSERT OR IGNORE INTO listening_history
               (spotify_uri, played_at, ms_played, platform)
               VALUES (?, '2026-01-01T12:00:00Z', 60000, 'ios')""",
            (uri,),
        )
        conn.commit()

    def test_joins_song_metadata(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "My Song", "My Artist", "My Album")
        db_conn.execute(
            "UPDATE songs SET engagement_score = 0.85, play_count = 25 WHERE spotify_uri = 'uri:1'"
        )
        db_conn.commit()
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 120, "energy": 0.7,
            "classification_source": "essentia",
        })
        self._add_personal_play(db_conn, "uri:1")
        results = queries.get_all_classified_songs(db_conn)
        assert len(results) == 1
        assert results[0]["name"] == "My Song"
        assert results[0]["artist"] == "My Artist"
        assert results[0]["bpm"] == 120
        assert results[0]["engagement_score"] == 0.85

    def test_ordered_by_engagement_desc(self, db_conn):
        for uri, score in [("uri:1", 0.5), ("uri:2", 0.9), ("uri:3", 0.3)]:
            queries.upsert_song(db_conn, uri, f"Song {uri}", "Artist")
            db_conn.execute(
                "UPDATE songs SET engagement_score = ? WHERE spotify_uri = ?",
                (score, uri),
            )
            queries.upsert_song_classification(db_conn, {
                "spotify_uri": uri, "bpm": 100, "classification_source": "essentia",
            })
            self._add_personal_play(db_conn, uri)
        db_conn.commit()
        results = queries.get_all_classified_songs(db_conn)
        scores = [r["engagement_score"] for r in results]
        assert scores == [0.9, 0.5, 0.3]

    def test_empty_when_no_classifications(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        assert queries.get_all_classified_songs(db_conn) == []

    def test_excludes_speaker_only_songs(self, db_conn):
        """Songs with only smart speaker plays are excluded."""
        queries.upsert_song(db_conn, "uri:1", "Real Song", "Artist")
        queries.upsert_song(db_conn, "uri:2", "Alexa Song", "Artist")
        for uri in ["uri:1", "uri:2"]:
            queries.upsert_song_classification(db_conn, {
                "spotify_uri": uri, "bpm": 100, "classification_source": "essentia",
            })
        # uri:1 has a phone play
        self._add_personal_play(db_conn, "uri:1")
        # uri:2 only has Alexa plays
        db_conn.execute(
            """INSERT OR IGNORE INTO listening_history
               (spotify_uri, played_at, ms_played, platform)
               VALUES ('uri:2', '2026-01-01T12:00:00Z', 60000,
                       'Partner amazon_salmon Amazon;Echo_Dot')""",
        )
        db_conn.commit()
        results = queries.get_all_classified_songs(db_conn)
        uris = [r["spotify_uri"] for r in results]
        assert "uri:1" in uris
        assert "uri:2" not in uris

    def test_excludes_unavailable_songs(self, db_conn):
        """Songs marked is_available=0 are excluded from matching."""
        queries.upsert_song(db_conn, "uri:avail", "Available", "Artist")
        queries.upsert_song(db_conn, "uri:unavail", "Unavailable", "Artist")
        queries.upsert_song(db_conn, "uri:unchecked", "Unchecked", "Artist")
        for uri in ["uri:avail", "uri:unavail", "uri:unchecked"]:
            queries.upsert_song_classification(db_conn, {
                "spotify_uri": uri, "bpm": 100, "classification_source": "essentia",
            })
            self._add_personal_play(db_conn, uri)
        # Mark one available, one unavailable, one unchecked (NULL)
        db_conn.execute("UPDATE songs SET is_available = 1 WHERE spotify_uri = 'uri:avail'")
        db_conn.execute("UPDATE songs SET is_available = 0 WHERE spotify_uri = 'uri:unavail'")
        db_conn.commit()
        results = queries.get_all_classified_songs(db_conn)
        uris = [r["spotify_uri"] for r in results]
        assert "uri:avail" in uris
        assert "uri:unchecked" in uris  # NULL passes through
        assert "uri:unavail" not in uris

    def test_includes_availability_fields(self, db_conn):
        """Result includes is_available and availability_checked_at for cache logic."""
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 100, "classification_source": "essentia",
        })
        self._add_personal_play(db_conn, "uri:1")
        queries.update_song_availability(db_conn, "uri:1", True)
        results = queries.get_all_classified_songs(db_conn)
        assert len(results) == 1
        assert results[0]["is_available"] == 1
        assert results[0]["availability_checked_at"] is not None


class TestUpdateSongAvailability:
    def test_marks_song_available(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.update_song_availability(db_conn, "uri:1", True)
        row = db_conn.execute("SELECT is_available, availability_checked_at FROM songs WHERE spotify_uri = 'uri:1'").fetchone()
        assert row["is_available"] == 1
        assert row["availability_checked_at"] is not None

    def test_marks_song_unavailable(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.update_song_availability(db_conn, "uri:1", False)
        row = db_conn.execute("SELECT is_available FROM songs WHERE spotify_uri = 'uri:1'").fetchone()
        assert row["is_available"] == 0

    def test_batch_update(self, db_conn):
        queries.upsert_song(db_conn, "uri:a", "A", "Artist")
        queries.upsert_song(db_conn, "uri:b", "B", "Artist")
        queries.upsert_song(db_conn, "uri:c", "C", "Artist")
        queries.update_song_availability_batch(db_conn, [
            ("uri:a", True), ("uri:b", False), ("uri:c", True),
        ])
        rows = {r["spotify_uri"]: r["is_available"] for r in db_conn.execute("SELECT spotify_uri, is_available FROM songs").fetchall()}
        assert rows["uri:a"] == 1
        assert rows["uri:b"] == 0
        assert rows["uri:c"] == 1

    def test_updates_checked_at_timestamp(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "Song", "Artist")
        queries.update_song_availability(db_conn, "uri:1", True)
        row = db_conn.execute("SELECT availability_checked_at FROM songs WHERE spotify_uri = 'uri:1'").fetchone()
        # Should be a valid ISO 8601 timestamp
        from datetime import datetime
        dt = datetime.fromisoformat(row["availability_checked_at"])
        assert dt.year >= 2026


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
