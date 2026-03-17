"""Shared test fixtures for Attuned."""

import json
import sqlite3
from pathlib import Path

import pytest

from db.schema import get_connection

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_conn(tmp_path):
    """Fresh in-memory database with schema created."""
    conn = get_connection(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    """Path to a temporary database file."""
    return tmp_path / "test.db"


@pytest.fixture
def db_conn_file(db_path):
    """Database connection backed by a temp file (for testing persistence)."""
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def sample_history_records():
    """Sample extended streaming history records matching Spotify export format."""
    return [
        {
            "ts": "2023-01-15T10:30:00Z",
            "platform": "iOS 16.0 (iPhone14,5)",
            "ms_played": 210000,
            "master_metadata_track_name": "Song Alpha",
            "master_metadata_album_artist_name": "Artist One",
            "master_metadata_album_album_name": "Album One",
            "spotify_track_uri": "spotify:track:aaa111",
            "reason_start": "clickrow",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False,
        },
        {
            "ts": "2023-01-15T10:35:00Z",
            "platform": "iOS 16.0 (iPhone14,5)",
            "ms_played": 185000,
            "master_metadata_track_name": "Song Beta",
            "master_metadata_album_artist_name": "Artist Two",
            "master_metadata_album_album_name": "Album Two",
            "spotify_track_uri": "spotify:track:bbb222",
            "reason_start": "trackdone",
            "reason_end": "fwdbtn",
            "shuffle": True,
            "skipped": True,
        },
        {
            "ts": "2023-01-16T08:00:00Z",
            "platform": "android",
            "ms_played": 5000,
            "master_metadata_track_name": "Song Alpha",
            "master_metadata_album_artist_name": "Artist One",
            "master_metadata_album_album_name": "Album One",
            "spotify_track_uri": "spotify:track:aaa111",
            "reason_start": "fwdbtn",
            "reason_end": "fwdbtn",
            "shuffle": False,
            "skipped": True,
        },
        {
            # No URI — should be skipped
            "ts": "2023-01-16T09:00:00Z",
            "platform": "web",
            "ms_played": 120000,
            "master_metadata_track_name": "Podcast Episode",
            "master_metadata_album_artist_name": None,
            "master_metadata_album_album_name": None,
            "spotify_track_uri": None,
            "reason_start": "clickrow",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False,
        },
        {
            "ts": "2023-06-01T20:00:00Z",
            "platform": "iOS 16.0 (iPhone14,5)",
            "ms_played": 45000,
            "master_metadata_track_name": "Song Alpha",
            "master_metadata_album_artist_name": "Artist One",
            "master_metadata_album_album_name": "Album One",
            "spotify_track_uri": "spotify:track:aaa111",
            "reason_start": "clickrow",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False,
        },
    ]


@pytest.fixture
def sample_history_dir(tmp_path, sample_history_records):
    """Create a temp directory with sample streaming history JSON files."""
    filepath = tmp_path / "Streaming_History_Audio_2023_0.json"
    filepath.write_text(json.dumps(sample_history_records))
    return tmp_path


@pytest.fixture
def sample_whoop_recovery():
    """Sample WHOOP recovery API response."""
    return {
        "cycle_id": 12345,
        "score": {
            "recovery_score": 72.0,
            "hrv_rmssd_milli": 55.3,
            "resting_heart_rate": 58.0,
            "spo2_percentage": 97.5,
            "skin_temp_celsius": 33.2,
        },
        "created_at": "2026-03-17T06:30:00.000-05:00",
    }


@pytest.fixture
def sample_whoop_sleep():
    """Sample WHOOP sleep API response."""
    return {
        "id": 67890,
        "end": "2026-03-17T07:00:00.000-05:00",
        "score_state_id": 12345,
        "score": {
            "stage_summary": {
                "total_slow_wave_sleep_time_milli": 5400000,
                "total_rem_sleep_time_milli": 7200000,
                "total_light_sleep_time_milli": 14400000,
                "total_awake_time_milli": 1800000,
                "sleep_cycle_count": 5,
            },
            "sleep_efficiency_percentage": 92.5,
            "sleep_performance_percentage": 88.0,
            "sleep_consistency_percentage": 75.0,
            "respiratory_rate": 15.2,
            "disturbance_count": 8,
            "sleep_needed": {
                "baseline_milli": 28800000,
                "need_from_sleep_debt_milli": 3600000,
                "need_from_recent_strain_milli": 1800000,
                "need_from_recent_nap_milli": -1200000,
            },
        },
    }


@pytest.fixture
def sample_spotify_track():
    """Sample Spotify track object from the API."""
    return {
        "uri": "spotify:track:xyz789",
        "name": "Test Track",
        "artists": [{"name": "Test Artist"}],
        "album": {"name": "Test Album"},
        "duration_ms": 240000,
    }
