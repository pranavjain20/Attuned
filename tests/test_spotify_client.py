"""Tests for spotify/client.py — data extraction from Spotify API responses."""

from unittest.mock import MagicMock, patch

import pytest

from spotify.client import parse_track, get_liked_songs, get_top_tracks, get_tracks_metadata


class TestParseTrack:
    def test_parses_valid_track(self, sample_spotify_track):
        result = parse_track(sample_spotify_track)
        assert result is not None
        assert result["uri"] == "spotify:track:xyz789"
        assert result["name"] == "Test Track"
        assert result["artist"] == "Test Artist"
        assert result["album"] == "Test Album"
        assert result["duration_ms"] == 240000

    def test_returns_none_for_none(self):
        assert parse_track(None) is None

    def test_returns_none_for_no_uri(self):
        assert parse_track({"name": "Track"}) is None

    def test_handles_empty_artists(self):
        track = {"uri": "spotify:track:abc", "name": "Song", "artists": []}
        result = parse_track(track)
        assert result["artist"] == "Unknown"

    def test_handles_no_album(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}]}
        result = parse_track(track)
        assert result["album"] is None

    def test_handles_missing_duration(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}], "album": {"name": "Alb"}}
        result = parse_track(track)
        assert result["duration_ms"] is None

    def test_release_year_zero_becomes_none(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}],
                 "album": {"name": "Alb", "release_date": "0000"}}
        result = parse_track(track)
        assert result["release_year"] is None

    def test_release_year_valid(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}],
                 "album": {"name": "Alb", "release_date": "2020-01-15"}}
        result = parse_track(track)
        assert result["release_year"] == 2020

    def test_release_year_1900_becomes_none(self):
        track = {"uri": "spotify:track:abc", "name": "Song",
                 "artists": [{"name": "Artist"}],
                 "album": {"name": "Alb", "release_date": "1900"}}
        result = parse_track(track)
        assert result["release_year"] is None


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


@patch("spotify.client.time.sleep")
class TestPaginationThrottle:
    def _make_track(self, uri="spotify:track:abc"):
        return {
            "uri": uri, "name": "Song", "artists": [{"name": "Artist"}],
            "album": {"name": "Album", "release_date": "2020-01-01"},
            "duration_ms": 200000,
        }

    def test_liked_songs_throttles_between_pages(self, mock_sleep):
        """Multi-page liked songs should sleep between pages."""
        page2 = {"items": [{"track": self._make_track("spotify:track:b")}], "next": None}
        page1 = {"items": [{"track": self._make_track("spotify:track:a")}], "next": "url"}
        sp = MagicMock()
        sp.current_user_saved_tracks.return_value = page1
        sp.next.return_value = page2
        tracks = get_liked_songs(sp)
        assert len(tracks) == 2
        mock_sleep.assert_called_once_with(1)

    def test_liked_songs_no_throttle_on_single_page(self, mock_sleep):
        """Single page should not sleep."""
        page1 = {"items": [{"track": self._make_track()}], "next": None}
        sp = MagicMock()
        sp.current_user_saved_tracks.return_value = page1
        get_liked_songs(sp)
        mock_sleep.assert_not_called()

    def test_top_tracks_throttles_between_pages(self, mock_sleep):
        """Multi-page top tracks should sleep between pages."""
        page2 = {"items": [self._make_track("spotify:track:b")], "next": None}
        page1 = {"items": [self._make_track("spotify:track:a")], "next": "url"}
        sp = MagicMock()
        sp.current_user_top_tracks.return_value = page1
        sp.next.return_value = page2
        tracks = get_top_tracks(sp, "short_term")
        assert len(tracks) == 2
        mock_sleep.assert_called_once_with(1)
