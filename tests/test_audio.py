"""Tests for classification/audio.py — audio clip acquisition."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from classification.audio import (
    acquire_audio_clips,
    download_from_youtube,
    download_preview,
    fetch_preview_urls,
    uri_to_filename,
)


class TestUriToFilename:
    def test_deterministic(self):
        name1 = uri_to_filename("spotify:track:abc123")
        name2 = uri_to_filename("spotify:track:abc123")
        assert name1 == name2

    def test_different_uris_different_names(self):
        name1 = uri_to_filename("spotify:track:abc")
        name2 = uri_to_filename("spotify:track:xyz")
        assert name1 != name2

    def test_ends_with_mp3(self):
        name = uri_to_filename("spotify:track:abc123")
        assert name.endswith(".mp3")

    def test_16_char_hash_plus_extension(self):
        name = uri_to_filename("spotify:track:abc123")
        assert len(name) == 16 + 4  # 16 hex chars + ".mp3"


@patch("classification.audio.time.sleep")
class TestFetchPreviewUrls:
    def test_returns_preview_urls(self, mock_sleep):
        sp = MagicMock()
        sp.track.side_effect = [
            {"preview_url": "https://example.com/preview1.mp3"},
            {"preview_url": "https://example.com/preview2.mp3"},
        ]
        result = fetch_preview_urls(sp, ["uri:1", "uri:2"])
        assert result["uri:1"] == "https://example.com/preview1.mp3"
        assert result["uri:2"] == "https://example.com/preview2.mp3"
        assert sp.track.call_count == 2

    def test_none_for_missing_preview(self, mock_sleep):
        sp = MagicMock()
        sp.track.side_effect = [
            {"preview_url": "https://example.com/preview1.mp3"},
            {"preview_url": None},
        ]
        result = fetch_preview_urls(sp, ["uri:1", "uri:2"])
        assert result["uri:1"] == "https://example.com/preview1.mp3"
        assert result["uri:2"] is None

    def test_none_for_null_track(self, mock_sleep):
        sp = MagicMock()
        sp.track.return_value = None
        result = fetch_preview_urls(sp, ["uri:1"])
        assert result["uri:1"] is None

    def test_handles_api_error_gracefully(self, mock_sleep):
        sp = MagicMock()
        sp.track.side_effect = Exception("API error")
        result = fetch_preview_urls(sp, ["uri:1", "uri:2"])
        assert result["uri:1"] is None
        assert result["uri:2"] is None

    def test_throttles_between_calls(self, mock_sleep):
        sp = MagicMock()
        sp.track.return_value = {"preview_url": "url"}
        fetch_preview_urls(sp, ["uri:1", "uri:2", "uri:3"])
        assert mock_sleep.call_count == 2  # between 3 tracks, not after last

    def test_single_uri_no_throttle(self, mock_sleep):
        sp = MagicMock()
        sp.track.return_value = {"preview_url": "url"}
        fetch_preview_urls(sp, ["uri:1"])
        mock_sleep.assert_not_called()


class TestDownloadPreview:
    def test_downloads_successfully(self, tmp_path):
        output = tmp_path / "clip.mp3"
        with patch("classification.audio.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.content = b"fake mp3 data"
            mock_client.get.return_value = mock_response
            result = download_preview("https://example.com/preview.mp3", output)
        assert result is True
        assert output.read_bytes() == b"fake mp3 data"

    def test_returns_false_on_failure(self, tmp_path):
        output = tmp_path / "clip.mp3"
        with patch("classification.audio.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = Exception("Connection failed")
            result = download_preview("https://example.com/preview.mp3", output)
        assert result is False
        assert not output.exists()

    def test_creates_parent_directories(self, tmp_path):
        output = tmp_path / "subdir" / "deep" / "clip.mp3"
        with patch("classification.audio.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.content = b"data"
            mock_client.get.return_value = mock_response
            result = download_preview("https://example.com/preview.mp3", output)
        assert result is True
        assert output.exists()


class TestDownloadFromYoutube:
    @patch("classification.audio._find_ytdlp_binary", return_value="/usr/bin/yt-dlp")
    @patch("classification.audio.subprocess.run")
    def test_success(self, mock_run, _mock_binary, tmp_path):
        output = tmp_path / "clip.mp3"
        # Simulate yt-dlp creating the expected temp file
        temp_path = output.with_suffix(".ytdl.mp3")

        def side_effect(*args, **kwargs):
            temp_path.write_bytes(b"fake audio")
            return MagicMock(returncode=0, stderr="")
        mock_run.side_effect = side_effect

        result = download_from_youtube("Tum Hi Ho", "Arijit Singh", output)
        assert result is True
        assert output.exists()

    @patch("classification.audio._find_ytdlp_binary", return_value="/usr/bin/yt-dlp")
    @patch("classification.audio.subprocess.run")
    def test_failure_returns_false(self, mock_run, _mock_binary, tmp_path):
        output = tmp_path / "clip.mp3"
        mock_run.return_value = MagicMock(returncode=1, stderr="Error")
        result = download_from_youtube("Song", "Artist", output)
        assert result is False

    @patch("classification.audio._find_ytdlp_binary", return_value="/usr/bin/yt-dlp")
    @patch("classification.audio.subprocess.run")
    def test_timeout_returns_false(self, mock_run, _mock_binary, tmp_path):
        import subprocess
        output = tmp_path / "clip.mp3"
        mock_run.side_effect = subprocess.TimeoutExpired("yt-dlp", 120)
        result = download_from_youtube("Song", "Artist", output)
        assert result is False

    @patch("classification.audio._find_ytdlp_binary", return_value=None)
    def test_ytdlp_not_installed_returns_false(self, _mock_binary, tmp_path):
        output = tmp_path / "clip.mp3"
        result = download_from_youtube("Song", "Artist", output)
        assert result is False


@patch("classification.audio.time.sleep")
class TestAcquireAudioClips:
    def _make_songs(self, uris):
        return [
            {"spotify_uri": uri, "name": f"Song {i}", "artist": f"Artist {i}",
             "duration_ms": 210000}
            for i, uri in enumerate(uris)
        ]

    def test_skips_already_cached(self, mock_sleep, tmp_path):
        songs = self._make_songs(["uri:1", "uri:2"])
        # Pre-cache one clip
        cached_path = tmp_path / uri_to_filename("uri:1")
        cached_path.write_bytes(b"existing clip data")

        sp = MagicMock()
        sp.track.return_value = {"preview_url": "https://example.com/p.mp3"}

        with patch("classification.audio.download_preview", return_value=True):
            stats = acquire_audio_clips(sp, songs, tmp_path)

        assert stats["already_cached"] == 1
        assert stats["downloaded"] == 1

    def test_preview_success(self, mock_sleep, tmp_path):
        songs = self._make_songs(["uri:1"])
        sp = MagicMock()
        sp.track.return_value = {"preview_url": "https://example.com/p.mp3"}

        with patch("classification.audio.download_preview", return_value=True) as mock_dl:
            stats = acquire_audio_clips(sp, songs, tmp_path)

        assert stats["downloaded"] == 1
        assert stats["preview_count"] == 1
        assert stats["ytdlp_count"] == 0
        mock_dl.assert_called_once()

    def test_falls_back_to_ytdlp_verified(self, mock_sleep, tmp_path):
        songs = self._make_songs(["uri:1"])
        sp = MagicMock()
        sp.track.return_value = {"preview_url": None}

        with patch("classification.audio.download_preview") as mock_preview, \
             patch("classification.audio.download_from_youtube_verified", return_value=True) as mock_yt:
            stats = acquire_audio_clips(sp, songs, tmp_path)

        assert stats["downloaded"] == 1
        assert stats["ytdlp_count"] == 1
        mock_preview.assert_not_called()
        mock_yt.assert_called_once()

    def test_both_fail_counts_as_failed(self, mock_sleep, tmp_path):
        songs = self._make_songs(["uri:1"])
        sp = MagicMock()
        sp.track.return_value = {"preview_url": "https://example.com/p.mp3"}

        with patch("classification.audio.download_preview", return_value=False), \
             patch("classification.audio.download_from_youtube_verified", return_value=False):
            stats = acquire_audio_clips(sp, songs, tmp_path)

        assert stats["downloaded"] == 0
        assert stats["failed"] == 1

    def test_empty_song_list(self, mock_sleep, tmp_path):
        sp = MagicMock()
        stats = acquire_audio_clips(sp, [], tmp_path)
        assert stats["downloaded"] == 0
        assert stats["already_cached"] == 0

    def test_all_cached_skips_preview_fetch(self, mock_sleep, tmp_path):
        songs = self._make_songs(["uri:1"])
        cached_path = tmp_path / uri_to_filename("uri:1")
        cached_path.write_bytes(b"cached")

        sp = MagicMock()
        stats = acquire_audio_clips(sp, songs, tmp_path)

        assert stats["already_cached"] == 1
        assert stats["downloaded"] == 0
        sp.track.assert_not_called()  # No API calls needed

    def test_creates_output_directory(self, mock_sleep, tmp_path):
        output_dir = tmp_path / "new_dir" / "clips"
        songs = self._make_songs(["uri:1"])
        sp = MagicMock()
        sp.track.return_value = {"preview_url": "https://example.com/p.mp3"}

        with patch("classification.audio.download_preview", return_value=True):
            acquire_audio_clips(sp, songs, output_dir)

        assert output_dir.exists()
