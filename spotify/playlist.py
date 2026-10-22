"""Thin Spotipy wrapper for playlist creation.

Uses /me/playlists (via Spotipy's internal call) instead of the deprecated
/users/{id}/playlists endpoint, which returns 403 in dev-mode apps.
"""

import logging

import spotipy

logger = logging.getLogger(__name__)

SPOTIFY_DESCRIPTION_MAX_LENGTH = 300


class SpotifyPlaylistError(Exception):
    """Raised when Spotify playlist API calls fail.

    http_status is Spotify's HTTP status (e.g. 404 for a playlist that no longer
    exists), or None when the failure didn't come with one.
    """

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


def _truncate_description(description: str) -> str:
    """Spotify rejects descriptions over SPOTIFY_DESCRIPTION_MAX_LENGTH characters."""
    if len(description) > SPOTIFY_DESCRIPTION_MAX_LENGTH:
        return description[:SPOTIFY_DESCRIPTION_MAX_LENGTH - 1] + "\u2026"
    return description


def create_playlist(
    sp: spotipy.Spotify,
    name: str,
    description: str,
    track_uris: list[str],
    public: bool = False,
) -> dict[str, str]:
    """Create a Spotify playlist and add tracks.

    Returns {"playlist_id": str, "playlist_url": str}.
    Truncates description to 300 chars as safety net.
    Raises SpotifyPlaylistError on API failure.
    """
    description = _truncate_description(description)

    try:
        # Use /me/playlists — the /users/{id}/playlists endpoint returns 403
        # in Spotify dev-mode apps even with correct scopes.
        payload = {"name": name, "public": public, "description": description}
        playlist = sp._post("me/playlists", payload=payload)
        playlist_id = playlist["id"]
        playlist_url = playlist["external_urls"]["spotify"]

        if track_uris:
            sp.playlist_add_items(playlist_id, track_uris)

        logger.info("Created playlist '%s' with %d tracks", name, len(track_uris))
        return {"playlist_id": playlist_id, "playlist_url": playlist_url}

    except spotipy.SpotifyException as e:
        raise SpotifyPlaylistError(f"Failed to create playlist: {e}", e.http_status) from e


def replace_playlist_tracks(sp: spotipy.Spotify, playlist_id: str, track_uris: list[str]) -> None:
    """Set an existing playlist's tracks to exactly track_uris, in order.

    Raises SpotifyPlaylistError on API failure.
    """
    try:
        sp.playlist_replace_items(playlist_id, track_uris)
        logger.info("Replaced tracks of playlist %s (%d tracks)", playlist_id, len(track_uris))
    except spotipy.SpotifyException as e:
        raise SpotifyPlaylistError(f"Failed to replace tracks: {e}", e.http_status) from e


def change_playlist_details(sp: spotipy.Spotify, playlist_id: str, name: str, description: str) -> None:
    """Rename an existing playlist and set its description (truncated to Spotify's limit).

    Raises SpotifyPlaylistError on API failure.
    """
    try:
        sp.playlist_change_details(playlist_id, name=name, description=_truncate_description(description))
        logger.info("Changed details of playlist %s to '%s'", playlist_id, name)
    except spotipy.SpotifyException as e:
        raise SpotifyPlaylistError(f"Failed to change details: {e}", e.http_status) from e
