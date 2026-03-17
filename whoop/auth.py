"""WHOOP OAuth 2.0 token management."""

import logging
import sqlite3
import time
from urllib.parse import urlencode

import httpx

from config import (
    TOKEN_EXPIRY_BUFFER_SECONDS,
    WHOOP_AUTH_URL,
    WHOOP_SCOPES,
    WHOOP_TOKEN_URL,
    get_whoop_client_id,
    get_whoop_client_secret,
    get_whoop_redirect_uri,
)
from db.queries import get_token, save_token

logger = logging.getLogger(__name__)


def get_authorization_url() -> str:
    """Build the WHOOP OAuth authorization URL for the user to visit."""
    params = {
        "client_id": get_whoop_client_id(),
        "redirect_uri": get_whoop_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(WHOOP_SCOPES),
    }
    return f"{WHOOP_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str, conn: sqlite3.Connection) -> dict:
    """Exchange an authorization code for access + refresh tokens. Stores in DB."""
    response = httpx.post(
        WHOOP_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": get_whoop_redirect_uri(),
            "client_id": get_whoop_client_id(),
            "client_secret": get_whoop_client_secret(),
        },
    )
    response.raise_for_status()
    data = response.json()

    expires_at = time.time() + data["expires_in"]
    save_token(
        conn,
        provider="whoop",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
    )
    logger.info("WHOOP tokens stored (expires in %ds)", data["expires_in"])
    return data


def get_valid_token(conn: sqlite3.Connection) -> str:
    """Get a valid WHOOP access token, refreshing if needed.

    Raises RuntimeError if no token exists.
    """
    token_row = get_token(conn, "whoop")
    if not token_row:
        raise RuntimeError(
            "No WHOOP token stored. Run OAuth flow first: python main.py auth-whoop"
        )

    if _is_token_expired(token_row["expires_at"]):
        if not token_row["refresh_token"]:
            raise RuntimeError("WHOOP token expired and no refresh token available")
        return _refresh_token(conn, token_row["refresh_token"])

    return token_row["access_token"]


def _is_token_expired(expires_at: float | None) -> bool:
    """Check if token is expired or will expire within the buffer window."""
    if expires_at is None:
        return True
    return time.time() >= (expires_at - TOKEN_EXPIRY_BUFFER_SECONDS)


def _refresh_token(conn: sqlite3.Connection, refresh_token: str) -> str:
    """Use refresh token to get a new access token. Updates DB."""
    response = httpx.post(
        WHOOP_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": get_whoop_client_id(),
            "client_secret": get_whoop_client_secret(),
        },
    )
    response.raise_for_status()
    data = response.json()

    expires_at = time.time() + data["expires_in"]
    save_token(
        conn,
        provider="whoop",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token),
        expires_at=expires_at,
    )
    logger.info("WHOOP token refreshed (expires in %ds)", data["expires_in"])
    return data["access_token"]
