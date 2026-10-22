"""Public-playlist support: the OAuth scope and the generate_playlist pass-through."""

from unittest.mock import MagicMock, patch

import pytest

from config import SPOTIFY_SCOPES
from spotify.auth import SQLiteCacheHandler


class TestScopes:
    def test_public_and_private_scopes_requested(self):
        assert "playlist-modify-public" in SPOTIFY_SCOPES
        assert "playlist-modify-private" in SPOTIFY_SCOPES

    def test_cached_token_reports_public_scope(self):
        handler = SQLiteCacheHandler(MagicMock())
        with patch("spotify.auth.get_token", return_value={
                "access_token": "a", "refresh_token": "r", "expires_at": 1}):
            token = handler.get_cached_token()
        assert "playlist-modify-public" in token["scope"].split()


class TestGeneratePlaylistPublic:
    def _run(self, **kwargs):
        from matching import generator
        selection = (
            {"state": "baseline", "confidence": "high", "metrics": {"recovery_score": 60.0}},
            {"songs": [{"spotify_uri": "spotify:track:1", "name": "S", "artist": "A"}],
             "neuro_profile": {"para": 0.6, "symp": 0.2, "grnd": 0.2}, "state": "rest", "position": 0.1,
             "match_stats": {"cohesion_stats": {}}},
        )
        with patch.object(generator, "select_day_songs", return_value=selection), \
             patch.object(generator, "_filter_unavailable_tracks", side_effect=lambda sp, s, conn: s), \
             patch.object(generator, "insert_generated_playlist"), \
             patch.object(generator, "create_playlist",
                          return_value={"playlist_id": "p", "playlist_url": "u"}) as create:
            generator.generate_playlist(MagicMock(), MagicMock(), "2026-10-21", **kwargs)
        return create

    def test_private_by_default(self):
        assert self._run().call_args.kwargs["public"] is False

    @pytest.mark.parametrize("public", [True, False])
    def test_public_passed_through(self, public):
        assert self._run(public=public).call_args.kwargs["public"] is public
