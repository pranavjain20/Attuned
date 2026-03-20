"""Tests for matching/generator.py — end-to-end playlist generation."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy

from matching.generator import (
    GenerationError,
    format_playlist_name,
    format_reasoning,
    generate_description,
    generate_playlist,
)
from spotify.playlist import SpotifyPlaylistError


# ---------------------------------------------------------------------------
# format_playlist_name
# ---------------------------------------------------------------------------

class TestFormatPlaylistName:
    def test_basic_format(self):
        assert format_playlist_name("2026-03-19", "accumulated_fatigue") == \
            "Mar 19 — Accumulated Fatigue"

    def test_single_digit_day(self):
        result = format_playlist_name("2026-03-05", "peak_readiness")
        assert result == "Mar 5 — Peak Readiness"

    def test_baseline_state(self):
        assert format_playlist_name("2026-01-01", "baseline") == "Jan 1 — Baseline"

    def test_poor_recovery(self):
        result = format_playlist_name("2026-12-25", "poor_recovery")
        assert result == "Dec 25 — Poor Recovery"

    def test_emotional_processing_deficit(self):
        result = format_playlist_name("2026-06-15", "emotional_processing_deficit")
        assert result == "Jun 15 — Emotional Processing Deficit"


# ---------------------------------------------------------------------------
# generate_description
# ---------------------------------------------------------------------------

class TestGenerateDescription:
    def test_full_metrics(self):
        desc = generate_description(
            state="accumulated_fatigue",
            metrics={"recovery_score": 35.0, "hrv_rmssd_milli": 42.5},
            neuro_profile={"para": 0.95, "symp": 0.00, "grnd": 0.05},
            match_stats={"selected": 18},
        )
        assert "Accumulated Fatigue" in desc
        assert "Recovery 35%" in desc
        assert "HRV 42ms" in desc  # rounded
        assert "parasympathetic" in desc
        assert "18 tracks" in desc

    def test_missing_recovery(self):
        desc = generate_description(
            state="baseline",
            metrics={},
            neuro_profile={"para": 0.15, "symp": 0.50, "grnd": 0.35},
            match_stats={"selected": 20},
        )
        assert "Recovery" not in desc
        assert "HRV" not in desc
        assert "sympathetic" in desc

    def test_missing_hrv(self):
        desc = generate_description(
            state="poor_recovery",
            metrics={"recovery_score": 28.0},
            neuro_profile={"para": 0.25, "symp": 0.30, "grnd": 0.45},
            match_stats={"selected": 15},
        )
        assert "Recovery 28%" in desc
        assert "HRV" not in desc

    def test_grounding_dominant(self):
        desc = generate_description(
            state="emotional_processing_deficit",
            metrics={},
            neuro_profile={"para": 0.10, "symp": 0.00, "grnd": 0.90},
            match_stats={"selected": 17},
        )
        assert "grounding" in desc

    def test_under_300_chars(self):
        desc = generate_description(
            state="accumulated_fatigue",
            metrics={"recovery_score": 35.0, "hrv_rmssd_milli": 42.5},
            neuro_profile={"para": 0.95, "symp": 0.00, "grnd": 0.05},
            match_stats={"selected": 20},
        )
        assert len(desc) <= 300

    def test_none_metric_values_handled(self):
        desc = generate_description(
            state="baseline",
            metrics={"recovery_score": None, "hrv_rmssd_milli": None},
            neuro_profile={"para": 0.15, "symp": 0.50, "grnd": 0.35},
            match_stats={"selected": 15},
        )
        assert "Recovery" not in desc
        assert "HRV" not in desc


# ---------------------------------------------------------------------------
# format_reasoning
# ---------------------------------------------------------------------------

class TestFormatReasoning:
    def test_includes_state_and_confidence(self):
        classification = {
            "state": "accumulated_fatigue",
            "confidence": "high",
            "reasoning": ["Multi-day stress pattern"],
            "metrics": {"recovery_score": 35.0},
        }
        match_result = {
            "match_stats": {"total_candidates": 500, "selected": 18,
                            "cohesion_stats": {
                                "pool_size": 60, "mean_similarity": 0.42,
                                "dominant_genre": "rock", "relaxations": 0,
                            }},
            "neuro_profile": {"para": 0.95, "symp": 0.00, "grnd": 0.05},
        }
        reasoning = format_reasoning(classification, match_result)
        assert "State: accumulated_fatigue" in reasoning
        assert "Confidence: high" in reasoning
        assert "Multi-day stress pattern" in reasoning
        assert "Candidates: 500" in reasoning
        assert "Selected: 18" in reasoning
        assert "Para: 0.95" in reasoning
        assert "Cohesion pool: 60" in reasoning
        assert "Mean similarity: 0.4200" in reasoning
        assert "Dominant genre: rock" in reasoning

    def test_empty_reasoning_list(self):
        classification = {
            "state": "baseline",
            "confidence": "medium",
            "reasoning": [],
            "metrics": {},
        }
        match_result = {
            "match_stats": {"total_candidates": 100, "selected": 20,
                            "cohesion_stats": {}},
            "neuro_profile": {"para": 0.15, "symp": 0.50, "grnd": 0.35},
        }
        reasoning = format_reasoning(classification, match_result)
        assert "State: baseline" in reasoning
        # Should not have the "Classifier reasoning:" header with empty list
        assert "Classifier reasoning:" not in reasoning

    def test_no_metrics(self):
        classification = {
            "state": "baseline",
            "confidence": "medium",
            "reasoning": [],
            "metrics": {},
        }
        match_result = {
            "match_stats": {},
            "neuro_profile": {},
        }
        reasoning = format_reasoning(classification, match_result)
        assert "State: baseline" in reasoning


# ---------------------------------------------------------------------------
# generate_playlist (pipeline tests with mocks)
# ---------------------------------------------------------------------------

def _make_classification(state="baseline", metrics=None, reasoning=None):
    return {
        "state": state,
        "confidence": "medium",
        "reasoning": reasoning or [],
        "metrics": metrics or {},
        "baselines": {"hrv": None, "rhr": None},
        "trends": {"hrv": None, "rhr": None},
        "sleep_analysis": None,
        "insufficient_data": state == "insufficient_data",
    }


def _make_match_result(n_songs=18, state="baseline"):
    songs = [
        {
            "spotify_uri": f"spotify:track:{i}",
            "name": f"Song {i}",
            "artist": f"Artist {i}",
            "album": f"Album {i}",
            "parasympathetic": 0.5,
            "sympathetic": 0.3,
            "grounding": 0.4,
            "confidence": 0.7,
            "last_played": "2026-03-01",
            "bpm": 120.0,
            "energy": 0.7,
            "genre_tags": ["rock", "indie"],
            "mood_tags": ["energetic"],
            "selection_score": 0.8 - i * 0.01,
            "breakdown": {"neuro_match": 0.8},
        }
        for i in range(n_songs)
    ]
    return {
        "songs": songs,
        "state": state,
        "neuro_profile": {"para": 0.15, "symp": 0.50, "grnd": 0.35},
        "match_stats": {
            "total_candidates": 500,
            "selected": n_songs,
            "cohesion_stats": {
                "pool_size": 60,
                "seed_idx": 0,
                "seed_song": "Song 0",
                "relaxations": 0,
                "min_similarity_used": 0.15,
                "mean_similarity": 0.42,
                "dominant_genre": "rock",
            },
        },
    }


def _make_mock_sp():
    sp = MagicMock(spec=spotipy.Spotify)
    sp._post.return_value = {
        "id": "pl_generated",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl_generated"},
    }
    return sp


class TestGeneratePlaylist:
    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_dry_run_no_spotify_call(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()

        result = generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)

        assert result["dry_run"] is True
        assert result["playlist_id"] is None
        assert result["playlist_url"] is None
        assert result["state"] == "baseline"
        assert len(result["songs"]) == 18
        assert "Baseline" in result["name"]
        assert "Mar 19" in result["name"]
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_dry_run_logs_to_db(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()

        generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)

        row = conn.execute("SELECT * FROM generated_playlists").fetchone()
        assert row is not None
        assert row["date"] == "2026-03-19"
        assert row["detected_state"] == "baseline"
        assert row["spotify_playlist_id"] is None
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_live_creates_spotify_playlist(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()
        sp = _make_mock_sp()

        result = generate_playlist(conn, sp=sp, date_str="2026-03-19", dry_run=False)

        assert result["playlist_id"] == "pl_generated"
        assert result["playlist_url"] == "https://open.spotify.com/playlist/pl_generated"
        sp._post.assert_called_once()
        sp.playlist_add_items.assert_called_once()

        row = conn.execute("SELECT * FROM generated_playlists").fetchone()
        assert row["spotify_playlist_id"] == "pl_generated"
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_insufficient_data_raises(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification(state="insufficient_data")

        with pytest.raises(GenerationError, match="insufficient WHOOP data"):
            generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_no_songs_raises(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result(n_songs=0)

        with pytest.raises(GenerationError, match="No songs matched"):
            generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_spotify_failure_logs_and_raises(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()
        sp = _make_mock_sp()
        sp._post.side_effect = spotipy.SpotifyException(
            http_status=500, code=-1, msg="Server error"
        )

        with pytest.raises(GenerationError, match="Spotify API failed"):
            generate_playlist(conn, sp=sp, date_str="2026-03-19", dry_run=False)

        # Should still log the failed attempt to DB
        row = conn.execute("SELECT * FROM generated_playlists").fetchone()
        assert row is not None
        assert "FAILED" in row["reasoning"]
        assert row["spotify_playlist_id"] is None
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_no_sp_for_live_raises(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()

        with pytest.raises(GenerationError, match="Spotify client required"):
            generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=False)
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_defaults_to_today(self, mock_classify, mock_select, tmp_path):
        from datetime import date
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()

        generate_playlist(conn, sp=None, dry_run=True)

        mock_classify.assert_called_once_with(conn, date.today().isoformat())
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_description_in_result(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification(
            metrics={"recovery_score": 72.0, "hrv_rmssd_milli": 55.0}
        )
        mock_select.return_value = _make_match_result()

        result = generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)

        assert len(result["description"]) <= 300
        assert "Recovery 72%" in result["description"]
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_multiple_playlists_per_day(self, mock_classify, mock_select, tmp_path):
        """PRD says each generation creates a NEW playlist — no conflicts."""
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        mock_select.return_value = _make_match_result()

        generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)
        generate_playlist(conn, sp=None, date_str="2026-03-19", dry_run=True)

        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM generated_playlists WHERE date = '2026-03-19'"
        ).fetchone()["cnt"]
        assert count == 2
        conn.close()

    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_track_uris_passed_to_spotify(self, mock_classify, mock_select, tmp_path):
        from db.schema import get_connection

        conn = get_connection(tmp_path / "test.db")
        mock_classify.return_value = _make_classification()
        match = _make_match_result(n_songs=5)
        mock_select.return_value = match
        sp = _make_mock_sp()

        generate_playlist(conn, sp=sp, date_str="2026-03-19", dry_run=False)

        expected_uris = [s["spotify_uri"] for s in match["songs"]]
        sp.playlist_add_items.assert_called_once_with("pl_generated", expected_uris)
        conn.close()
