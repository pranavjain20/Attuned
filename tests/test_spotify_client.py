"""Tests for spotify/client.py — data extraction from Spotify API responses."""

import pytest

from spotify.client import _parse_track, get_liked_songs, get_top_tracks, get_tracks_metadata


class TestParseTrack:
    def test_parses_valid_track(self, sample_spotify_track):
        result = _parse_track(sample_spotify_track)
        assert result is not None
        assert result["uri"] == "spotify:track:xyz789"
        assert result["name"] == "Test Track"
        assert result["artist"] == "Test Artist"
        assert result["album"] == "Test Album"
        assert result["duration_ms"] == 240000

    def test_returns_none_for_none(self):
        assert _parse_track(None) is None

    def test_returns_none_for_no_uri(self):
        assert _parse_track({"name": "Track"}) is None

    def test_handles_empty_artists(self):
        track = {"uri": "spotify:track:abc", "name": "Song", "artists": []}
        result = _parse_track(track)
        assert result["artist"] == "Unknown"

    def test_handles_no_album(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}]}
        result = _parse_track(track)
        assert result["album"] is None

    def test_handles_missing_duration(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}], "album": {"name": "Alb"}}
        result = _parse_track(track)
        assert result["duration_ms"] is None


class TestGetLikedSongs:
    def test_fetches_single_page(self, sample_spotify_track):
        sp = _mock_sp_paginated([sample_spotify_track])
        tracks = get_liked_songs(sp)
        assert len(tracks) == 1
        assert tracks[0]["uri"] == "spotify:track:xyz789"

    def test_handles_empty_library(self):
        sp = _mock_sp_paginated([])
        tracks = get_liked_songs(sp)
        assert tracks == []


class TestGetTopTracks:
    def test_fetches_tracks(self, sample_spotify_track):
        sp = _mock_sp_top([sample_spotify_track])
        tracks = get_top_tracks(sp, time_range="short_term")
        assert len(tracks) == 1

    def test_handles_empty(self):
        sp = _mock_sp_top([])
        tracks = get_top_tracks(sp, time_range="medium_term")
        assert tracks == []


class TestGetTracksMetadata:
    def test_fetches_single_tracks(self, sample_spotify_track):
        sp = type("MockSp", (), {
            "track": lambda self, track_id, market=None: sample_spotify_track,
        })()
        results = get_tracks_metadata(sp, ["xyz789"])
        assert len(results) == 1
        assert results[0]["duration_ms"] == 240000

    def test_handles_empty_input(self):
        sp = type("MockSp", (), {})()
        assert get_tracks_metadata(sp, []) == []

    def test_handles_failed_track(self):
        def raise_error(track_id, market=None):
            raise Exception("Not found")
        sp = type("MockSp", (), {"track": raise_error})()
        results = get_tracks_metadata(sp, ["xyz789"])
        assert results == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_sp_paginated(tracks):
    """Create a mock Spotipy client for paginated liked songs."""
    items = [{"track": t} for t in tracks]
    return type("MockSp", (), {
        "current_user_saved_tracks": lambda self, limit=50: {
            "items": items,
            "next": None,
        },
        "next": lambda self, results: None,
    })()


def _mock_sp_top(tracks):
    """Create a mock Spotipy client for top tracks."""
    return type("MockSp", (), {
        "current_user_top_tracks": lambda self, limit=50, time_range="medium_term": {
            "items": tracks,
            "next": None,
        },
        "next": lambda self, results: None,
    })()
