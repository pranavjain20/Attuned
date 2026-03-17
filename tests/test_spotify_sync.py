"""Tests for spotify/sync.py — extended history ingestion and stats computation."""

import json

import pytest

from config import MIN_PLAY_DURATION_MS
from db import queries
from spotify.sync import _parse_history_record, ingest_extended_history, _compute_basic_song_stats


class TestParseHistoryRecord:
    def test_parses_valid_record(self, sample_history_records):
        result = _parse_history_record(sample_history_records[0])
        assert result is not None
        assert result["history"]["spotify_uri"] == "spotify:track:aaa111"
        assert result["history"]["ms_played"] == 210000
        assert result["history"]["reason_start"] == "clickrow"
        assert result["song"]["name"] == "Song Alpha"
        assert result["song"]["artist"] == "Artist One"

    def test_returns_none_for_no_uri(self, sample_history_records):
        result = _parse_history_record(sample_history_records[3])
        assert result is None

    def test_returns_none_for_no_track_name(self):
        record = {
            "ts": "2023-01-01T00:00:00Z",
            "ms_played": 30000,
            "master_metadata_track_name": None,
            "master_metadata_album_artist_name": "Artist",
            "spotify_track_uri": "spotify:track:abc",
        }
        assert _parse_history_record(record) is None

    def test_returns_none_for_no_artist(self):
        record = {
            "ts": "2023-01-01T00:00:00Z",
            "ms_played": 30000,
            "master_metadata_track_name": "Song",
            "master_metadata_album_artist_name": None,
            "spotify_track_uri": "spotify:track:abc",
        }
        assert _parse_history_record(record) is None

    def test_maps_boolean_fields(self, sample_history_records):
        result = _parse_history_record(sample_history_records[1])
        assert result["history"]["skipped"] is True
        assert result["history"]["shuffle"] is True

    def test_captures_platform(self, sample_history_records):
        result = _parse_history_record(sample_history_records[0])
        assert result["history"]["platform"] == "iOS 16.0 (iPhone14,5)"

    def test_sets_played_at_from_ts(self, sample_history_records):
        result = _parse_history_record(sample_history_records[0])
        assert result["history"]["played_at"] == "2023-01-15T10:30:00Z"

    def test_sets_song_timestamps(self, sample_history_records):
        result = _parse_history_record(sample_history_records[0])
        assert result["song"]["first_played"] == "2023-01-15T10:30:00Z"
        assert result["song"]["last_played"] == "2023-01-15T10:30:00Z"


class TestIngestExtendedHistory:
    def test_ingests_sample_history(self, db_conn, sample_history_dir):
        result = ingest_extended_history(db_conn, sample_history_dir)
        # 5 records total, 1 has no URI, 1 has no artist — 3 valid unique URIs? No...
        # Record 0: aaa111 ✓, Record 1: bbb222 ✓, Record 2: aaa111 ✓, Record 3: no URI, Record 4: aaa111 ✓
        # So 4 valid records, 2 unique songs
        assert result["total_records"] == 4
        assert result["total_songs"] == 2

    def test_creates_listening_history_rows(self, db_conn, sample_history_dir):
        ingest_extended_history(db_conn, sample_history_dir)
        count = queries.count_rows(db_conn, "listening_history")
        assert count == 4

    def test_creates_song_entries(self, db_conn, sample_history_dir):
        ingest_extended_history(db_conn, sample_history_dir)
        assert queries.count_rows(db_conn, "songs") == 2

    def test_song_has_extended_history_source(self, db_conn, sample_history_dir):
        ingest_extended_history(db_conn, sample_history_dir)
        song = queries.get_song(db_conn, "spotify:track:aaa111")
        sources = json.loads(song["sources"])
        assert "extended_history" in sources

    def test_song_first_last_played(self, db_conn, sample_history_dir):
        ingest_extended_history(db_conn, sample_history_dir)
        song = queries.get_song(db_conn, "spotify:track:aaa111")
        assert song["first_played"] == "2023-01-15T10:30:00Z"
        assert song["last_played"] == "2023-06-01T20:00:00Z"

    def test_idempotent_on_rerun(self, db_conn, sample_history_dir):
        result1 = ingest_extended_history(db_conn, sample_history_dir)
        result2 = ingest_extended_history(db_conn, sample_history_dir)
        # Second run should insert 0 new history rows (INSERT OR IGNORE)
        assert queries.count_rows(db_conn, "listening_history") == 4
        assert queries.count_rows(db_conn, "songs") == 2

    def test_raises_for_missing_directory(self, db_conn, tmp_path):
        with pytest.raises(FileNotFoundError):
            ingest_extended_history(db_conn, tmp_path / "nonexistent")

    def test_raises_for_empty_directory(self, db_conn, tmp_path):
        with pytest.raises(FileNotFoundError, match="No Streaming_History_Audio"):
            ingest_extended_history(db_conn, tmp_path)

    def test_skips_video_files(self, db_conn, tmp_path):
        """Video files should not be picked up by the Audio glob."""
        video = tmp_path / "Streaming_History_Video_2021-2026.json"
        video.write_text('[{"ts":"2023-01-01T00:00:00Z","ms_played":1000,'
                         '"master_metadata_track_name":"Vid",'
                         '"master_metadata_album_artist_name":"VidArtist",'
                         '"spotify_track_uri":"spotify:track:vid1"}]')
        with pytest.raises(FileNotFoundError, match="No Streaming_History_Audio"):
            ingest_extended_history(db_conn, tmp_path)


class TestComputeBasicSongStats:
    def test_computes_play_count_for_meaningful_listens(self, db_conn):
        # Insert songs
        queries.upsert_song(db_conn, "uri:1", "A", "X")
        # Insert history: 2 meaningful (>30s), 1 short
        records = [
            {"spotify_uri": "uri:1", "played_at": "2023-01-01T00:00:00Z", "ms_played": 210000},
            {"spotify_uri": "uri:1", "played_at": "2023-01-02T00:00:00Z", "ms_played": 45000},
            {"spotify_uri": "uri:1", "played_at": "2023-01-03T00:00:00Z", "ms_played": 5000},
        ]
        queries.insert_listening_history_batch(db_conn, records)
        _compute_basic_song_stats(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["play_count"] == 2  # only >30s

    def test_sets_first_and_last_played(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "A", "X")
        records = [
            {"spotify_uri": "uri:1", "played_at": "2023-06-01T00:00:00Z", "ms_played": 50000},
            {"spotify_uri": "uri:1", "played_at": "2023-01-01T00:00:00Z", "ms_played": 50000},
        ]
        queries.insert_listening_history_batch(db_conn, records)
        _compute_basic_song_stats(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["first_played"] == "2023-01-01T00:00:00Z"
        assert song["last_played"] == "2023-06-01T00:00:00Z"

    def test_song_with_no_meaningful_listens_keeps_zero(self, db_conn):
        queries.upsert_song(db_conn, "uri:1", "A", "X")
        records = [
            {"spotify_uri": "uri:1", "played_at": "2023-01-01T00:00:00Z", "ms_played": 5000},
        ]
        queries.insert_listening_history_batch(db_conn, records)
        _compute_basic_song_stats(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["play_count"] == 0  # no meaningful listens
