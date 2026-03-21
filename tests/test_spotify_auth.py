"""Tests for spotify/auth.py — SQLite cache handler and client creation."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from db import queries
from spotify.auth import SQLiteCacheHandler, _refresh_spotify_token


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
