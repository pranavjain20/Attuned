"""Tests for whoop/auth.py — OAuth flow, token storage, refresh."""

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from db import queries
from whoop.auth import (
    _is_token_expired,
    _refresh_token,
    exchange_code_for_tokens,
    get_authorization_url,
    get_valid_token,
)


class TestGetAuthorizationUrl:
    @patch("whoop.auth.get_whoop_client_id", return_value="test_client_id")
    @patch("whoop.auth.get_whoop_redirect_uri", return_value="http://localhost:8080/callback")
    def test_contains_required_params(self, mock_redirect, mock_id):
        url = get_authorization_url()
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "scope=" in url

    @patch("whoop.auth.get_whoop_client_id", return_value="test_id")
    @patch("whoop.auth.get_whoop_redirect_uri", return_value="http://localhost:8080/callback")
    def test_includes_offline_scope(self, mock_redirect, mock_id):
        url = get_authorization_url()
        assert "offline" in url


class TestExchangeCodeForTokens:
    @patch("whoop.auth.get_whoop_client_id", return_value="id")
    @patch("whoop.auth.get_whoop_client_secret", return_value="secret")
    @patch("whoop.auth.get_whoop_redirect_uri", return_value="http://localhost:8080/callback")
    @patch("whoop.auth.httpx.post")
    def test_stores_tokens(self, mock_post, mock_uri, mock_secret, mock_id, db_conn):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = exchange_code_for_tokens("auth_code_123", db_conn)
        assert result["access_token"] == "new_access"

        token = queries.get_token(db_conn, "whoop")
        assert token["access_token"] == "new_access"
        assert token["refresh_token"] == "new_refresh"


class TestIsTokenExpired:
    def test_expired_token(self):
        assert _is_token_expired(time.time() - 100)

    def test_valid_token(self):
        assert not _is_token_expired(time.time() + 600)

    def test_within_buffer_is_expired(self):
        # Token expires in 200s, buffer is 300s — should be "expired"
        assert _is_token_expired(time.time() + 200)

    def test_none_is_expired(self):
        assert _is_token_expired(None)


class TestGetValidToken:
    def test_raises_when_no_token(self, db_conn):
        with pytest.raises(RuntimeError, match="No WHOOP token"):
            get_valid_token(db_conn)

    def test_returns_valid_token(self, db_conn):
        queries.save_token(
            db_conn, "whoop", "access123", "refresh456",
            time.time() + 3600,
        )
        token = get_valid_token(db_conn)
        assert token == "access123"

    @patch("whoop.auth._refresh_token", return_value="refreshed_access")
    def test_refreshes_expired_token(self, mock_refresh, db_conn):
        queries.save_token(
            db_conn, "whoop", "old_access", "refresh456",
            time.time() - 100,  # expired
        )
        token = get_valid_token(db_conn)
        assert token == "refreshed_access"
        mock_refresh.assert_called_once()


class TestRefreshTokenErrors:
    @patch("whoop.auth.get_whoop_client_id", return_value="id")
    @patch("whoop.auth.get_whoop_client_secret", return_value="secret")
    @patch("whoop.auth.httpx.post")
    def test_refresh_token_handles_401_error(self, mock_post, mock_secret, mock_id, db_conn):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_response,
        )
        mock_post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            _refresh_token(db_conn, "stale_refresh_token")

    @patch("whoop.auth.get_whoop_client_id", return_value="id")
    @patch("whoop.auth.get_whoop_client_secret", return_value="secret")
    @patch("whoop.auth.httpx.post")
    def test_refresh_token_handles_network_error(self, mock_post, mock_secret, mock_id, db_conn):
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            _refresh_token(db_conn, "some_refresh_token")
