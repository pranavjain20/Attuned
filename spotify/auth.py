"""Spotify OAuth via Spotipy with SQLite-backed token storage."""

import logging
import sqlite3
import time

import httpx
import spotipy
from spotipy.cache_handler import CacheHandler

from config import (
    SPOTIFY_SCOPES,
    TOKEN_EXPIRY_BUFFER_SECONDS,
    get_spotify_client_id,
    get_spotify_client_secret,
    get_spotify_redirect_uri,
)
from db.queries import get_token, save_token

logger = logging.getLogger(__name__)


class SQLiteCacheHandler(CacheHandler):
    """Spotipy CacheHandler that reads/writes tokens to our SQLite tokens table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_cached_token(self) -> dict | None:
        token_row = get_token(self.conn, "spotify")
        if not token_row or not token_row["access_token"]:
            return None
        return {
            "access_token": token_row["access_token"],
            "refresh_token": token_row["refresh_token"],
            "expires_at": int(token_row["expires_at"]) if token_row["expires_at"] else 0,
            "token_type": "Bearer",
            "scope": " ".join(SPOTIFY_SCOPES),
        }

    def save_token_to_cache(self, token_info: dict) -> None:
        save_token(
            self.conn,
            provider="spotify",
            access_token=token_info["access_token"],
            refresh_token=token_info.get("refresh_token"),
            expires_at=float(token_info.get("expires_at", 0)),
        )


def get_spotify_client(conn: sqlite3.Connection) -> spotipy.Spotify:
    """Return an authenticated Spotipy client.

    Uses stored token directly, refreshing via Spotify token endpoint if expired.
    Bypasses Spotipy's interactive auth flow entirely.
    """
    token_row = get_token(conn, "spotify")
    if not token_row:
        raise RuntimeError(
            "No Spotify token stored. Run OAuth flow first: python oauth_server.py spotify"
        )

    access_token = token_row["access_token"]
    expires_at = token_row["expires_at"]

    # Refresh if expired
    if expires_at and time.time() >= (expires_at - TOKEN_EXPIRY_BUFFER_SECONDS):
        access_token = _refresh_spotify_token(conn, token_row["refresh_token"])

    return _wrap_with_rate_limit(spotipy.Spotify(auth=access_token))


class _RateLimitedSpotify:
    """Wrapper around spotipy.Spotify that handles 429 rate limits globally.

    Every Spotify API call goes through this. On 429, reads Retry-After header,
    waits, and retries automatically. No individual command needs its own rate
    limit handling.
    """

    MAX_RETRIES = 3

    def __init__(self, sp: spotipy.Spotify) -> None:
        self._sp = sp

    def __getattr__(self, name: str):
        attr = getattr(self._sp, name)
        if not callable(attr):
            return attr

        def rate_limited_call(*args, **kwargs):
            for attempt in range(self.MAX_RETRIES):
                try:
                    return attr(*args, **kwargs)
                except spotipy.SpotifyException as e:
                    if e.http_status == 429:
                        retry_after = int(e.headers.get("Retry-After", 30)) + 5
                        logger.warning(
                            "Spotify 429 on %s (attempt %d/%d). Waiting %ds.",
                            name, attempt + 1, self.MAX_RETRIES, retry_after,
                        )
                        time.sleep(retry_after)
                    else:
                        raise
            # Final attempt — let it raise
            return attr(*args, **kwargs)

        return rate_limited_call


def _wrap_with_rate_limit(sp: spotipy.Spotify) -> spotipy.Spotify:
    """Wrap a Spotipy client with global rate limit handling."""
    return _RateLimitedSpotify(sp)


def _refresh_spotify_token(conn: sqlite3.Connection, refresh_token: str) -> str:
    """Refresh the Spotify access token and update the DB."""
    if not refresh_token:
        raise RuntimeError("No Spotify refresh token stored — re-run: python main.py auth-spotify")
    response = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": get_spotify_client_id(),
            "client_secret": get_spotify_client_secret(),
        },
    )
    response.raise_for_status()
    data = response.json()

    expires_at = time.time() + data.get("expires_in", 3600)
    save_token(
        conn,
        provider="spotify",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token),
        expires_at=expires_at,
    )
    logger.info("Spotify token refreshed")
    return data["access_token"]
