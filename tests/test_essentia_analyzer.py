"""Tests for classification/essentia_analyzer.py — Essentia audio analysis."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from classification.essentia_analyzer import VALID_KEYS, analyze_all_songs, analyze_audio
from db import queries


# ---------------------------------------------------------------------------
# Helpers — mock Essentia module before import
# ---------------------------------------------------------------------------

def _make_es_mock(
    *,
    bpm: float = 120.0,
    key: str = "A",
    scale: str = "minor",
    onset_rate: float = 4.0,
    spectral_flatness: float = 0.01,
    danceability: float = 0.65,
    audio_length: int = 44100 * 5,
    load_error: bool = False,
):
    """Create a mock essentia.standard module with configurable return values."""
    es = MagicMock()

    fake_audio = np.random.randn(audio_length).astype(np.float32)

    if load_error:
        es.MonoLoader.return_value = MagicMock(side_effect=Exception("Decode error"))
    else:
        es.MonoLoader.return_value = MagicMock(return_value=fake_audio)

    es.RhythmExtractor2013.return_value = MagicMock(return_value=(bpm, [], 0.8, [], []))
    es.KeyExtractor.return_value = MagicMock(return_value=(key, scale, 0.7))
    es.OnsetRate.return_value = MagicMock(return_value=([], onset_rate))
    es.ZeroCrossingRate.return_value = MagicMock(return_value=0.04)
    es.Danceability.return_value = MagicMock(return_value=(danceability, []))

    # Frame-based processing mocks (for acousticness flatness computation)
    fake_frames = [np.random.randn(2048).astype(np.float32) for _ in range(3)]
    es.FrameGenerator.return_value = fake_frames
    es.Windowing.return_value = MagicMock(
        return_value=np.random.randn(2048).astype(np.float32)
    )
    fake_spec = np.ones(1025, dtype=np.float32)  # sum > 0
    es.Spectrum.return_value = MagicMock(return_value=fake_spec)
    es.Flatness.return_value = MagicMock(return_value=spectral_flatness)

    return es


def _run_analyze_with_mock(audio_path: Path, es_mock):
    """Run analyze_audio with a mocked essentia.standard module."""
    essentia_parent = MagicMock()
    essentia_parent.standard = es_mock
    with patch.dict(sys.modules, {
        "essentia": essentia_parent,
        "essentia.standard": es_mock,
    }):
        return analyze_audio(audio_path)


class TestAnalyzeAudio:
    def test_returns_all_expected_keys(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock())

        assert result is not None
        for key in ("bpm", "key", "mode", "energy", "acousticness",
                     "instrumentalness", "danceability"):
            assert key in result

    def test_bpm_is_positive_int(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(bpm=128.3))

        assert isinstance(result["bpm"], int)
        assert result["bpm"] == 128

    def test_key_is_valid_note(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(key="C#"))
        assert result["key"] == "C#"
        assert result["key"] in VALID_KEYS

    def test_mode_is_major_or_minor(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        for scale in ("major", "minor"):
            result = _run_analyze_with_mock(audio_path, _make_es_mock(scale=scale))
            assert result["mode"] == scale

    def test_float_outputs_clamped_to_0_1(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock())

        for field in ("energy", "acousticness", "instrumentalness", "danceability"):
            assert 0.0 <= result[field] <= 1.0, f"{field}={result[field]} out of [0,1]"

    def test_missing_file_returns_none(self, tmp_path):
        result = analyze_audio(tmp_path / "nonexistent.mp3")
        assert result is None

    def test_corrupt_audio_returns_none(self, tmp_path):
        audio_path = tmp_path / "corrupt.mp3"
        audio_path.write_bytes(b"garbage")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(load_error=True))
        assert result is None

    def test_too_short_audio_returns_none(self, tmp_path):
        audio_path = tmp_path / "short.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(audio_length=100))
        assert result is None

    def test_energy_low_onset_near_zero(self, tmp_path):
        """Low onset rate (calm acoustic) → near-zero energy."""
        audio_path = tmp_path / "calm.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(onset_rate=2.0))
        assert result["energy"] == 0.0

    def test_energy_high_onset_clamped_at_one(self, tmp_path):
        """High onset rate (tabla, electronic beats) → clamped at 1.0."""
        audio_path = tmp_path / "energetic.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(onset_rate=7.0))
        assert result["energy"] == 1.0

    def test_essentia_not_installed_returns_none(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        with patch.dict(sys.modules, {"essentia": None, "essentia.standard": None}):
            result = analyze_audio(audio_path)
        assert result is None

    def test_invalid_key_sets_key_mode_to_none(self, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(key="X#"))
        assert result["key"] is None
        assert result["mode"] is None
        # Other fields should still be present
        assert result["bpm"] is not None
        assert result["energy"] is not None

    def test_high_flatness_means_low_acousticness(self, tmp_path):
        """Electronic/noisy spectrum (high flatness) → low acousticness."""
        audio_path = tmp_path / "electronic.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(
            audio_path, _make_es_mock(spectral_flatness=0.05)
        )
        assert result["acousticness"] == 0.0  # 1.0 - 0.05*20 = 0.0

    def test_low_flatness_means_high_acousticness(self, tmp_path):
        """Tonal/acoustic spectrum (low flatness) → high acousticness."""
        audio_path = tmp_path / "acoustic.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(
            audio_path, _make_es_mock(spectral_flatness=0.002)
        )
        assert result["acousticness"] > 0.9  # 1.0 - 0.002*20 = 0.96

    def test_acousticness_clamps_negative_to_zero(self, tmp_path):
        """Very high flatness (>0.05) should clamp to 0, not go negative."""
        audio_path = tmp_path / "noisy.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(
            audio_path, _make_es_mock(spectral_flatness=0.08)
        )
        assert result["acousticness"] == 0.0  # 1.0 - 0.08*20 = -0.6 → clamped

    def test_acousticness_averages_varying_flatness_across_frames(self, tmp_path):
        """Flatness values differ per frame — result should be the mean."""
        audio_path = tmp_path / "varied.mp3"
        audio_path.write_bytes(b"fake")

        es_mock = _make_es_mock()
        # Three frames with different flatness values
        es_mock.Flatness.return_value = MagicMock(
            side_effect=[0.01, 0.04, 0.01]
        )

        result = _run_analyze_with_mock(audio_path, es_mock)
        # mean(0.01, 0.04, 0.01) = 0.02; acousticness = 1.0 - 0.02*20 = 0.6
        assert abs(result["acousticness"] - 0.6) < 0.01

    def test_acousticness_zero_frames_defaults_to_max(self, tmp_path):
        """Empty frame list → avg_flatness=0 → acousticness=1.0."""
        audio_path = tmp_path / "empty_frames.mp3"
        audio_path.write_bytes(b"fake")

        es_mock = _make_es_mock()
        es_mock.FrameGenerator.return_value = []  # no frames

        result = _run_analyze_with_mock(audio_path, es_mock)
        assert result["acousticness"] == 1.0

    def test_acousticness_skips_zero_sum_spectrum_frames(self, tmp_path):
        """Frames with zero-sum spectrum are skipped in flatness averaging."""
        audio_path = tmp_path / "partial_silence.mp3"
        audio_path.write_bytes(b"fake")

        es_mock = _make_es_mock(spectral_flatness=0.01)
        # Return zero spectrum for all frames — flatness never called
        es_mock.Spectrum.return_value = MagicMock(
            return_value=np.zeros(1025, dtype=np.float32)
        )

        result = _run_analyze_with_mock(audio_path, es_mock)
        # All frames skipped → avg_flatness=0 → acousticness=1.0
        assert result["acousticness"] == 1.0

    def test_energy_at_upper_boundary(self, tmp_path):
        """Onset rate=6.0 → (6-2)/4 = 1.0."""
        audio_path = tmp_path / "boundary.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(onset_rate=6.0))
        assert result["energy"] == 1.0

    def test_energy_just_below_upper(self, tmp_path):
        """Onset rate just below 6.0 → energy < 1.0."""
        audio_path = tmp_path / "below.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(onset_rate=5.8))
        assert 0.9 < result["energy"] < 1.0

    def test_energy_midpoint(self, tmp_path):
        """Onset rate=4.0 → (4-2)/4 = 0.5."""
        audio_path = tmp_path / "mid.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(onset_rate=4.0))
        assert result["energy"] == 0.5

    def test_energy_below_floor_clamped(self, tmp_path):
        """Onset rate below 2.0 → clamped to 0.0."""
        audio_path = tmp_path / "very_calm.mp3"
        audio_path.write_bytes(b"fake")

        result = _run_analyze_with_mock(audio_path, _make_es_mock(onset_rate=1.0))
        assert result["energy"] == 0.0


class TestAnalyzeAllSongs:
    def _insert_song(self, db_conn, uri, play_count=10):
        queries.upsert_song(db_conn, uri, f"Song {uri}", f"Artist {uri}")
        db_conn.execute(
            "UPDATE songs SET play_count = ? WHERE spotify_uri = ?",
            (play_count, uri),
        )
        db_conn.commit()

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_analyzes_unclassified_songs(self, mock_analyze, db_conn, tmp_path):
        self._insert_song(db_conn, "uri:1")
        from classification.audio import uri_to_filename
        (tmp_path / uri_to_filename("uri:1")).write_bytes(b"fake audio")

        mock_analyze.return_value = {
            "bpm": 120, "bpm_confidence": 2.5, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "instrumentalness": 0.2, "danceability": 0.6,
        }

        stats = analyze_all_songs(db_conn, tmp_path)
        assert stats["analyzed"] == 1
        assert stats["failed"] == 0
        assert stats["skipped"] == 0

        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert len(rows) == 1
        assert rows[0]["bpm"] == 120
        assert rows[0]["classification_source"] == "essentia"

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_skips_songs_without_clips(self, mock_analyze, db_conn, tmp_path):
        self._insert_song(db_conn, "uri:1")

        stats = analyze_all_songs(db_conn, tmp_path)
        assert stats["skipped"] == 1
        assert stats["analyzed"] == 0
        mock_analyze.assert_not_called()

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_counts_failed_analysis(self, mock_analyze, db_conn, tmp_path):
        self._insert_song(db_conn, "uri:1")
        from classification.audio import uri_to_filename
        (tmp_path / uri_to_filename("uri:1")).write_bytes(b"corrupt")

        mock_analyze.return_value = None

        stats = analyze_all_songs(db_conn, tmp_path)
        assert stats["failed"] == 1
        assert stats["analyzed"] == 0

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_skips_already_classified(self, mock_analyze, db_conn, tmp_path):
        self._insert_song(db_conn, "uri:1")
        self._insert_song(db_conn, "uri:2")

        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 100, "classification_source": "essentia",
        })

        from classification.audio import uri_to_filename
        for uri in ["uri:1", "uri:2"]:
            (tmp_path / uri_to_filename(uri)).write_bytes(b"audio")

        mock_analyze.return_value = {
            "bpm": 128, "bpm_confidence": 3.0, "key": "C", "mode": "major",
            "energy": 0.5, "acousticness": 0.5,
            "instrumentalness": 0.5, "danceability": 0.5,
        }

        stats = analyze_all_songs(db_conn, tmp_path)
        assert stats["analyzed"] == 1
        mock_analyze.assert_called_once()

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_stores_classified_at_timestamp(self, mock_analyze, db_conn, tmp_path):
        self._insert_song(db_conn, "uri:1")
        from classification.audio import uri_to_filename
        (tmp_path / uri_to_filename("uri:1")).write_bytes(b"audio")

        mock_analyze.return_value = {
            "bpm": 120, "bpm_confidence": 2.5, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "instrumentalness": 0.2, "danceability": 0.6,
        }

        analyze_all_songs(db_conn, tmp_path)

        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["classified_at"] is not None

    def test_empty_when_no_unclassified(self, db_conn, tmp_path):
        stats = analyze_all_songs(db_conn, tmp_path)
        assert stats == {"analyzed": 0, "failed": 0, "skipped": 0}

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_mixed_outcomes(self, mock_analyze, db_conn, tmp_path):
        """uri:1 already classified, uri:2 succeeds, uri:3 fails, uri:4 no clip."""
        for i in range(1, 5):
            self._insert_song(db_conn, f"uri:{i}")

        from classification.audio import uri_to_filename

        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 100, "classification_source": "essentia",
        })

        (tmp_path / uri_to_filename("uri:2")).write_bytes(b"audio")
        (tmp_path / uri_to_filename("uri:3")).write_bytes(b"corrupt")
        # uri:4 — no clip

        mock_analyze.side_effect = [
            {"bpm": 120, "bpm_confidence": 2.5, "key": "A", "mode": "minor",
             "energy": 0.7, "acousticness": 0.3,
             "instrumentalness": 0.2, "danceability": 0.6},
            None,
        ]

        stats = analyze_all_songs(db_conn, tmp_path)
        assert stats["analyzed"] == 1
        assert stats["failed"] == 1
        assert stats["skipped"] == 1

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_force_reanalyzes_classified_songs(self, mock_analyze, db_conn, tmp_path):
        """force=True should re-analyze songs that already have classifications."""
        self._insert_song(db_conn, "uri:1")
        from classification.audio import uri_to_filename
        (tmp_path / uri_to_filename("uri:1")).write_bytes(b"audio")

        # First: classify it
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:1", "bpm": 100, "energy": 0.5,
            "classification_source": "essentia",
        })

        # Without force: already classified, skipped
        stats_normal = analyze_all_songs(db_conn, tmp_path, force=False)
        assert stats_normal["analyzed"] == 0
        mock_analyze.assert_not_called()

        # With force: re-analyzed
        mock_analyze.return_value = {
            "bpm": 120, "bpm_confidence": 2.5, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "instrumentalness": 0.2, "danceability": 0.6,
        }
        stats_force = analyze_all_songs(db_conn, tmp_path, force=True)
        assert stats_force["analyzed"] == 1

        # Verify the classification was updated
        rows = queries.get_song_classifications(db_conn, ["uri:1"])
        assert rows[0]["energy"] == 0.7  # Updated from 0.5 to 0.7

    @patch("classification.essentia_analyzer.analyze_audio")
    def test_force_still_skips_low_play_count(self, mock_analyze, db_conn, tmp_path):
        """force=True should still respect MIN_CLASSIFICATION_LISTENS."""
        self._insert_song(db_conn, "uri:low", play_count=1)  # Below threshold
        from classification.audio import uri_to_filename
        (tmp_path / uri_to_filename("uri:low")).write_bytes(b"audio")

        stats = analyze_all_songs(db_conn, tmp_path, force=True)
        assert stats["analyzed"] == 0
        mock_analyze.assert_not_called()
