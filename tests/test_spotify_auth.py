"""Tests for spotify/auth.py — SQLite cache handler, client creation, rate limit wrapper."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
import spotipy

from db import queries
from spotify.auth import (
    SQLiteCacheHandler,
    SpotifyRateLimitError,
    _RateLimitedSpotify,
    _refresh_spotify_token,
)


class TestSQLiteCacheHandler:
    def test_returns_none_when_no_token(self, db_conn):
        handler = SQLiteCacheHandler(db_conn)
        assert handler.get_cached_token() is None

    def test_returns_token_dict(self, db_conn):
        queries.save_token(db_conn, "spotify", "access123", "refresh456", 9999999999.0)
        handler = SQLiteCacheHandler(db_conn)
        token = handler.get_cached_token()
        assert token is not None
        assert token["access_token"] == "access123"
        assert token["refresh_token"] == "refresh456"
        assert token["expires_at"] == 9999999999
        assert token["token_type"] == "Bearer"

    def test_saves_token(self, db_conn):
        handler = SQLiteCacheHandler(db_conn)
        handler.save_token_to_cache({
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_at": 1234567890,
        })
        token = queries.get_token(db_conn, "spotify")
        assert token["access_token"] == "new_access"
        assert token["refresh_token"] == "new_refresh"

    def test_roundtrip(self, db_conn):
        handler = SQLiteCacheHandler(db_conn)
        original = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": 9999999999,
        }
        handler.save_token_to_cache(original)
        loaded = handler.get_cached_token()
        assert loaded["access_token"] == "access"
        assert loaded["refresh_token"] == "refresh"


class TestRefreshSpotifyTokenErrors:
    @patch("spotify.auth.get_spotify_client_id", return_value="id")
    @patch("spotify.auth.get_spotify_client_secret", return_value="secret")
    @patch("spotify.auth.httpx.post")
    def test_refresh_token_handles_http_error(self, mock_post, mock_secret, mock_id, db_conn):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_response,
        )
        mock_post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            _refresh_spotify_token(db_conn, "valid_refresh_token")

    def test_refresh_token_missing_token_raises(self, db_conn):
        with pytest.raises(RuntimeError, match="No Spotify refresh token"):
            _refresh_spotify_token(db_conn, None)


def _make_spotify_exception(status: int, retry_after: int | None = None) -> spotipy.SpotifyException:
    """Build a SpotifyException with optional Retry-After header."""
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return spotipy.SpotifyException(status, -1, "test error", headers=headers)


@patch("spotify.auth.time.sleep")
class TestRateLimitedSpotify:
    def _make_wrapper(self, side_effect):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.side_effect = side_effect
        return _RateLimitedSpotify(sp)

    def test_success_no_retry(self, mock_sleep):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.return_value = {"name": "Song"}
        wrapper = _RateLimitedSpotify(sp)
        result = wrapper.track("abc")
        assert result == {"name": "Song"}
        mock_sleep.assert_not_called()

    def test_429_short_retry_after_retries(self, mock_sleep):
        """429 with Retry-After <= 60s should wait and retry."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(429, retry_after=5),
            {"name": "Song"},
        ])
        result = wrapper.track("abc")
        assert result == {"name": "Song"}
        mock_sleep.assert_called_once_with(10)  # 5 + 5 buffer

    def test_429_long_retry_after_raises_circuit_breaker(self, mock_sleep):
        """429 with Retry-After > 60s should raise SpotifyRateLimitError immediately."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(429, retry_after=84580),
        ])
        with pytest.raises(SpotifyRateLimitError, match="Daily API quota exhausted"):
            wrapper.track("abc")
        mock_sleep.assert_not_called()

    def test_429_missing_header_circuit_breaks(self, mock_sleep):
        """429 without Retry-After header → circuit break (header stripped by MaxRetryError)."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(429, retry_after=None),
        ])
        with pytest.raises(SpotifyRateLimitError, match="header stripped"):
            wrapper.track("abc")
        mock_sleep.assert_not_called()

    def test_429_at_circuit_breaker_boundary_retries(self, mock_sleep):
        """429 with Retry-After exactly at boundary (55+5=60) should still retry."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(429, retry_after=55),
            {"name": "Song"},
        ])
        result = wrapper.track("abc")
        assert result == {"name": "Song"}
        mock_sleep.assert_called_once_with(60)

    def test_429_just_over_circuit_breaker_aborts(self, mock_sleep):
        """429 with Retry-After just over boundary (56+5=61) should abort."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(429, retry_after=56),
        ])
        with pytest.raises(SpotifyRateLimitError):
            wrapper.track("abc")
        mock_sleep.assert_not_called()

    def test_500_retries_with_delay(self, mock_sleep):
        """Server errors should retry with 5s delay."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(500),
            {"name": "Song"},
        ])
        result = wrapper.track("abc")
        assert result == {"name": "Song"}
        mock_sleep.assert_called_once_with(5)

    def test_502_retries(self, mock_sleep):
        wrapper = self._make_wrapper([
            _make_spotify_exception(502),
            _make_spotify_exception(502),
            {"name": "Song"},
        ])
        result = wrapper.track("abc")
        assert result == {"name": "Song"}
        assert mock_sleep.call_count == 2

    def test_server_error_exhausts_retries(self, mock_sleep):
        """After MAX_RETRIES server errors, final attempt raises."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(500),
            _make_spotify_exception(500),
            _make_spotify_exception(500),
            _make_spotify_exception(500),  # final attempt
        ])
        with pytest.raises(spotipy.SpotifyException):
            wrapper.track("abc")

    def test_403_raises_immediately(self, mock_sleep):
        """403 Forbidden should not retry — raises immediately."""
        wrapper = self._make_wrapper([
            _make_spotify_exception(403),
        ])
        with pytest.raises(spotipy.SpotifyException):
            wrapper.track("abc")
        mock_sleep.assert_not_called()

    def test_non_callable_attribute_passthrough(self, mock_sleep):
        """Non-callable attributes should pass through without wrapping."""
        sp = MagicMock(spec=spotipy.Spotify)
        sp.prefix = "https://api.spotify.com/v1/"
        wrapper = _RateLimitedSpotify(sp)
        assert wrapper.prefix == "https://api.spotify.com/v1/"
