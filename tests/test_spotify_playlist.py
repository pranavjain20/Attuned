"""Tests for spotify/playlist.py — Spotipy wrapper for playlist creation."""

from unittest.mock import MagicMock

import pytest
import spotipy

from spotify.playlist import (
    SPOTIFY_DESCRIPTION_MAX_LENGTH,
    SpotifyPlaylistError,
    change_playlist_details,
    create_playlist,
    replace_playlist_tracks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_sp():
    """Return a mock Spotipy client with standard responses."""
    sp = MagicMock(spec=spotipy.Spotify)
    sp._post.return_value = {
        "id": "pl_abc",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl_abc"},
    }
    return sp


# ---------------------------------------------------------------------------
# create_playlist
# ---------------------------------------------------------------------------

class TestCreatePlaylist:
    def test_creates_playlist_with_tracks(self, mock_sp):
        uris = ["spotify:track:1", "spotify:track:2"]
        result = create_playlist(mock_sp, "Test Playlist", "A description", uris)

        assert result == {
            "playlist_id": "pl_abc",
            "playlist_url": "https://open.spotify.com/playlist/pl_abc",
        }
        mock_sp._post.assert_called_once_with(
            "me/playlists",
            payload={"name": "Test Playlist", "public": False, "description": "A description"},
        )
        mock_sp.playlist_add_items.assert_called_once_with("pl_abc", uris)

    def test_creates_private_playlist_by_default(self, mock_sp):
        create_playlist(mock_sp, "Name", "Desc", ["spotify:track:1"])
        payload = mock_sp._post.call_args[1]["payload"]
        assert payload["public"] is False

    def test_creates_public_playlist_when_requested(self, mock_sp):
        create_playlist(mock_sp, "Name", "Desc", ["spotify:track:1"], public=True)
        payload = mock_sp._post.call_args[1]["payload"]
        assert payload["public"] is True

    def test_truncates_long_description(self, mock_sp):
        long_desc = "x" * 400
        create_playlist(mock_sp, "Name", long_desc, ["spotify:track:1"])
        payload = mock_sp._post.call_args[1]["payload"]
        assert len(payload["description"]) <= SPOTIFY_DESCRIPTION_MAX_LENGTH
        assert payload["description"].endswith("\u2026")

    def test_does_not_truncate_short_description(self, mock_sp):
        desc = "Short description"
        create_playlist(mock_sp, "Name", desc, ["spotify:track:1"])
        payload = mock_sp._post.call_args[1]["payload"]
        assert payload["description"] == desc

    def test_exactly_300_char_description_not_truncated(self, mock_sp):
        desc = "x" * 300
        create_playlist(mock_sp, "Name", desc, ["spotify:track:1"])
        payload = mock_sp._post.call_args[1]["payload"]
        assert payload["description"] == desc
        assert len(payload["description"]) == 300

    def test_empty_track_list_skips_add(self, mock_sp):
        create_playlist(mock_sp, "Name", "Desc", [])
        mock_sp._post.assert_called_once()
        mock_sp.playlist_add_items.assert_not_called()

    def test_raises_on_create_failure(self, mock_sp):
        mock_sp._post.side_effect = spotipy.SpotifyException(
            http_status=403, code=-1, msg="Forbidden"
        )
        with pytest.raises(SpotifyPlaylistError, match="Failed to create playlist"):
            create_playlist(mock_sp, "Name", "Desc", ["spotify:track:1"])

    def test_raises_on_add_items_failure(self, mock_sp):
        mock_sp.playlist_add_items.side_effect = spotipy.SpotifyException(
            http_status=500, code=-1, msg="Server error"
        )
        with pytest.raises(SpotifyPlaylistError, match="Failed to create playlist"):
            create_playlist(mock_sp, "Name", "Desc", ["spotify:track:1"])


# ---------------------------------------------------------------------------
# replace_playlist_tracks
# ---------------------------------------------------------------------------

class TestReplacePlaylistTracks:
    def test_replaces_tracks_in_order(self, mock_sp):
        uris = ["spotify:track:2", "spotify:track:1"]
        replace_playlist_tracks(mock_sp, "pl_abc", uris)
        mock_sp.playlist_replace_items.assert_called_once_with("pl_abc", uris)

    def test_raises_on_failure(self, mock_sp):
        mock_sp.playlist_replace_items.side_effect = spotipy.SpotifyException(
            http_status=404, code=-1, msg="Not found"
        )
        with pytest.raises(SpotifyPlaylistError, match="Failed to replace tracks") as raised:
            replace_playlist_tracks(mock_sp, "pl_abc", ["spotify:track:1"])
        assert raised.value.http_status == 404  # callers tell a deleted playlist from other failures


class TestHttpStatus:
    def test_create_failure_keeps_the_status(self, mock_sp):
        mock_sp._post.side_effect = spotipy.SpotifyException(http_status=403, code=-1, msg="Forbidden")
        with pytest.raises(SpotifyPlaylistError) as raised:
            create_playlist(mock_sp, "Name", "Desc", [])
        assert raised.value.http_status == 403

    def test_status_is_none_when_not_from_spotify(self):
        assert SpotifyPlaylistError("x").http_status is None


# ---------------------------------------------------------------------------
# change_playlist_details
# ---------------------------------------------------------------------------

class TestChangePlaylistDetails:
    def test_sets_name_and_description(self, mock_sp):
        change_playlist_details(mock_sp, "pl_abc", "Oct 22 — Settle In", "Attuned · help you settle")
        mock_sp.playlist_change_details.assert_called_once_with(
            "pl_abc", name="Oct 22 — Settle In", description="Attuned · help you settle")

    def test_truncates_long_description(self, mock_sp):
        change_playlist_details(mock_sp, "pl_abc", "N", "x" * 400)
        description = mock_sp.playlist_change_details.call_args.kwargs["description"]
        assert len(description) == SPOTIFY_DESCRIPTION_MAX_LENGTH and description.endswith("\u2026")

    def test_raises_with_status_on_failure(self, mock_sp):
        mock_sp.playlist_change_details.side_effect = spotipy.SpotifyException(
            http_status=404, code=-1, msg="Not found")
        with pytest.raises(SpotifyPlaylistError, match="Failed to change details") as raised:
            change_playlist_details(mock_sp, "pl_abc", "N", "D")
        assert raised.value.http_status == 404
