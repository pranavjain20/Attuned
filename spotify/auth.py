"""Spotify OAuth via Spotipy with SQLite-backed token storage."""

import json
import logging
import sqlite3

import spotipy
from spotipy.cache_handler import CacheHandler

from config import SPOTIFY_SCOPES, get_spotify_client_id, get_spotify_client_secret, get_spotify_redirect_uri
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
    """Return an authenticated Spotipy client using our SQLite token storage."""
    cache_handler = SQLiteCacheHandler(conn)
    auth_manager = spotipy.SpotifyOAuth(
        client_id=get_spotify_client_id(),
        client_secret=get_spotify_client_secret(),
        redirect_uri=get_spotify_redirect_uri(),
        scope=" ".join(SPOTIFY_SCOPES),
        cache_handler=cache_handler,
    )
    return spotipy.Spotify(auth_manager=auth_manager)
