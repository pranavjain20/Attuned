"""Tests for spotify/sync.py — extended history ingestion and stats computation."""

import json
from unittest.mock import MagicMock, patch

import pytest

from config import MIN_PLAY_DURATION_MS
from db import queries
from spotify.sync import _parse_history_record, ingest_extended_history, _compute_basic_song_stats, fetch_track_metadata


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


@patch("spotify.client.time.sleep")
class TestFetchTrackMetadata:
    """Tests for fetch_track_metadata — fetches metadata for all songs missing duration_ms or release_year."""

    def _make_sp_mock(self, track_responses: list[dict]) -> MagicMock:
        """Create a mock Spotify client that returns tracks from sp.track() via side_effect."""
        sp = MagicMock()
        sp.track.side_effect = track_responses
        return sp

    def _set_play_count(self, db_conn, uri: str, count: int = 5) -> None:
        db_conn.execute("UPDATE songs SET play_count = ? WHERE spotify_uri = ?", (count, uri))
        db_conn.commit()

    def _spotify_track(self, uri: str, duration_ms: int = 200000, release_year: int = 2020) -> dict:
        """Build a Spotify API track response object."""
        return {
            "uri": uri,
            "name": f"Track {uri}",
            "artists": [{"name": "Artist"}],
            "album": {"name": "Album", "release_date": f"{release_year}-01-01"},
            "duration_ms": duration_ms,
        }

    def test_fetches_songs_missing_release_year_but_having_duration(self, mock_sleep, db_conn):
        """Songs with duration_ms but no release_year should still be fetched."""
        queries.upsert_song(db_conn, "spotify:track:a1", "Song A", "Artist A",
                            duration_ms=180000)
        self._set_play_count(db_conn, "spotify:track:a1")
        sp = self._make_sp_mock([self._spotify_track("spotify:track:a1", duration_ms=180000, release_year=2019)])

        updated = fetch_track_metadata(db_conn, sp)

        assert updated == 1
        song = queries.get_song(db_conn, "spotify:track:a1")
        assert song["release_year"] == 2019
        assert song["duration_ms"] == 180000

    def test_skips_songs_with_both_fields_present(self, mock_sleep, db_conn):
        """Songs that already have both duration_ms and release_year should not be fetched."""
        queries.upsert_song(db_conn, "spotify:track:complete", "Complete", "Artist",
                            duration_ms=200000, release_year=2021)

        sp = MagicMock()
        updated = fetch_track_metadata(db_conn, sp)

        assert updated == 0
        sp.track.assert_not_called()

    def test_skips_songs_below_min_listens(self, mock_sleep, db_conn):
        """Songs with play_count below threshold should not be fetched."""
        queries.upsert_song(db_conn, "spotify:track:low", "Low Plays", "Artist")
        # play_count defaults to 0, below min_listens=2

        sp = MagicMock()
        updated = fetch_track_metadata(db_conn, sp)

        assert updated == 0
        sp.track.assert_not_called()

    def test_updates_both_duration_and_release_year(self, mock_sleep, db_conn):
        """Both duration_ms and release_year should be set from metadata."""
        queries.upsert_song(db_conn, "spotify:track:bare", "Bare", "Artist")
        self._set_play_count(db_conn, "spotify:track:bare")
        sp = self._make_sp_mock([self._spotify_track("spotify:track:bare", 250000, 2018)])

        fetch_track_metadata(db_conn, sp)

        song = queries.get_song(db_conn, "spotify:track:bare")
        assert song["duration_ms"] == 250000
        assert song["release_year"] == 2018

    def test_preserves_existing_values_when_api_returns_none(self, mock_sleep, db_conn):
        """COALESCE logic: existing values should not be overwritten with NULL."""
        queries.upsert_song(db_conn, "spotify:track:partial", "Partial", "Artist",
                            duration_ms=180000)
        self._set_play_count(db_conn, "spotify:track:partial")
        track_resp = {
            "uri": "spotify:track:partial",
            "name": "Partial",
            "artists": [{"name": "Artist"}],
            "album": {"name": "Album", "release_date": ""},
            "duration_ms": 180000,
        }
        sp = self._make_sp_mock([track_resp])

        fetch_track_metadata(db_conn, sp)

        song = queries.get_song(db_conn, "spotify:track:partial")
        assert song["duration_ms"] == 180000

    def test_returns_zero_when_no_songs_missing_metadata(self, mock_sleep, db_conn):
        """No songs missing metadata means no API calls and returns 0."""
        queries.upsert_song(db_conn, "spotify:track:full", "Full", "Artist",
                            duration_ms=200000, release_year=2021)

        sp = MagicMock()
        result = fetch_track_metadata(db_conn, sp)

        assert result == 0

    def test_handles_multiple_songs(self, mock_sleep, db_conn):
        """Multiple songs missing metadata should all be processed."""
        for i in range(3):
            queries.upsert_song(db_conn, f"spotify:track:m{i}", f"Song {i}", "Artist")
            self._set_play_count(db_conn, f"spotify:track:m{i}")

        tracks = [self._spotify_track(f"spotify:track:m{i}", 200000 + i * 1000, 2015 + i)
                  for i in range(3)]
        sp = self._make_sp_mock(tracks)

        updated = fetch_track_metadata(db_conn, sp)

        assert updated == 3
        for i in range(3):
            song = queries.get_song(db_conn, f"spotify:track:m{i}")
            assert song["duration_ms"] == 200000 + i * 1000
            assert song["release_year"] == 2015 + i

    def test_fetches_song_missing_only_duration(self, mock_sleep, db_conn):
        """Songs with release_year but missing duration_ms should be fetched."""
        queries.upsert_song(db_conn, "spotify:track:nodur", "No Duration", "Artist",
                            release_year=2022)
        self._set_play_count(db_conn, "spotify:track:nodur")
        sp = self._make_sp_mock([self._spotify_track("spotify:track:nodur", 195000, 2022)])

        updated = fetch_track_metadata(db_conn, sp)

        assert updated == 1
        song = queries.get_song(db_conn, "spotify:track:nodur")
        assert song["duration_ms"] == 195000
        assert song["release_year"] == 2022
