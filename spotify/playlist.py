"""Thin Spotipy wrapper for playlist creation.

Uses /me/playlists (via Spotipy's internal call) instead of the deprecated
/users/{id}/playlists endpoint, which returns 403 in dev-mode apps.
"""

import logging

import spotipy

logger = logging.getLogger(__name__)

SPOTIFY_DESCRIPTION_MAX_LENGTH = 300


class SpotifyPlaylistError(Exception):
    """Raised when Spotify playlist API calls fail."""


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
    if len(description) > SPOTIFY_DESCRIPTION_MAX_LENGTH:
        description = description[:SPOTIFY_DESCRIPTION_MAX_LENGTH - 1] + "\u2026"

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
        raise SpotifyPlaylistError(f"Failed to create playlist: {e}") from e
