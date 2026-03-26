"""Tests for matching/generator.py — end-to-end playlist generation."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy

from matching.generator import (
    GenerationError,
    _filter_unavailable_tracks,
    _get_dominant_moods,
    _get_neuro_purpose,
    _pick_name_label,
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
    def test_fatigue_slow_down(self):
        name = format_playlist_name(
            "2026-03-19", {"para": 0.95, "symp": 0.00, "grnd": 0.05}, 19.0)
        assert name == "Mar 19 — Slow Down"

    def test_peak_full_send(self):
        name = format_playlist_name(
            "2026-03-05", {"para": 0.00, "symp": 0.90, "grnd": 0.10}, 92.0)
        assert name == "Mar 5 — Full Send"

    def test_baseline_high_recovery_stay_sharp(self):
        name = format_playlist_name(
            "2026-01-01", {"para": 0.15, "symp": 0.50, "grnd": 0.35}, 78.0)
        assert name == "Jan 1 — Stay Sharp"

    def test_baseline_low_recovery_fuel_up(self):
        name = format_playlist_name(
            "2026-12-25", {"para": 0.15, "symp": 0.50, "grnd": 0.35}, 62.0)
        assert name == "Dec 25 — Fuel Up"

    def test_emotional_sit_with_it(self):
        name = format_playlist_name(
            "2026-06-15", {"para": 0.10, "symp": 0.00, "grnd": 0.90}, 45.0)
        assert name == "Jun 15 — Sit With It"

    def test_poor_recovery_ease_into_it(self):
        name = format_playlist_name(
            "2026-03-10", {"para": 0.25, "symp": 0.30, "grnd": 0.45}, 35.0)
        assert name == "Mar 10 — Ease Into It"

    def test_poor_sleep_ground_yourself(self):
        name = format_playlist_name(
            "2026-03-10", {"para": 0.55, "symp": 0.00, "grnd": 0.45}, 55.0)
        assert name == "Mar 10 — Settle In"

    def test_physical_recovery_rest_and_repair(self):
        name = format_playlist_name(
            "2026-03-10", {"para": 0.60, "symp": 0.00, "grnd": 0.40}, 40.0)
        assert name == "Mar 10 — Rest & Repair"

    def test_none_recovery_uses_default(self):
        name = format_playlist_name(
            "2026-03-10", {"para": 0.15, "symp": 0.50, "grnd": 0.35})
        assert "Fuel Up" in name  # default recovery 50 → not > 70


class TestPickNameLabel:
    def test_para_very_high(self):
        assert _pick_name_label({"para": 0.95, "symp": 0.00, "grnd": 0.05}) == "Slow Down"

    def test_para_moderate_low_recovery(self):
        assert _pick_name_label({"para": 0.60, "symp": 0.00, "grnd": 0.40}, 35.0) == "Rest & Repair"

    def test_para_moderate_high_recovery(self):
        assert _pick_name_label({"para": 0.55, "symp": 0.00, "grnd": 0.45}, 65.0) == "Settle In"

    def test_symp_very_high(self):
        assert _pick_name_label({"para": 0.00, "symp": 0.90, "grnd": 0.10}) == "Full Send"

    def test_symp_moderate_high_recovery(self):
        assert _pick_name_label({"para": 0.15, "symp": 0.50, "grnd": 0.35}, 75.0) == "Stay Sharp"

    def test_symp_moderate_low_recovery(self):
        assert _pick_name_label({"para": 0.15, "symp": 0.50, "grnd": 0.35}, 60.0) == "Fuel Up"

    def test_grnd_very_high(self):
        assert _pick_name_label({"para": 0.10, "symp": 0.00, "grnd": 0.90}) == "Sit With It"

    def test_grnd_moderate_with_symp(self):
        assert _pick_name_label({"para": 0.25, "symp": 0.30, "grnd": 0.45}) == "Ease Into It"

    def test_grnd_moderate_without_symp(self):
        assert _pick_name_label({"para": 0.15, "symp": 0.10, "grnd": 0.45}) == "Ground Yourself"


# ---------------------------------------------------------------------------
# generate_description
# ---------------------------------------------------------------------------

class TestGenerateDescription:
    def _make_songs(self, mood_tags=None, genre_tags=None, n=5):
        return [
            {"mood_tags": mood_tags or ["energetic", "uplifting"],
             "genre_tags": genre_tags or ["bollywood"]}
            for _ in range(n)
        ]

    def test_para_dominant_description(self):
        desc = generate_description(
            neuro_profile={"para": 0.95, "symp": 0.00, "grnd": 0.05},
            songs=self._make_songs(["calm", "soothing", "peaceful"]),
            cohesion_stats={"dominant_genre": "bollywood"},
        )
        assert "Calming your nervous system" in desc
        assert "Bollywood" in desc

    def test_symp_dominant_description(self):
        desc = generate_description(
            neuro_profile={"para": 0.15, "symp": 0.50, "grnd": 0.35},
            songs=self._make_songs(["energetic", "uplifting"]),
            cohesion_stats={"dominant_genre": "rock"},
        )
        assert "Matching your energy" in desc
        assert "Rock" in desc

    def test_grnd_dominant_description(self):
        desc = generate_description(
            neuro_profile={"para": 0.10, "symp": 0.00, "grnd": 0.90},
            songs=self._make_songs(["reflective", "nostalgic"]),
            cohesion_stats={"dominant_genre": "bollywood"},
        )
        assert "Grounding your emotions" in desc

    def test_includes_mood_tags(self):
        desc = generate_description(
            neuro_profile={"para": 0.95, "symp": 0.00, "grnd": 0.05},
            songs=self._make_songs(["romantic", "nostalgic", "warm"]),
            cohesion_stats={"dominant_genre": "bollywood"},
        )
        assert "Romantic" in desc

    def test_no_genre_graceful(self):
        desc = generate_description(
            neuro_profile={"para": 0.50, "symp": 0.30, "grnd": 0.20},
            songs=self._make_songs(),
            cohesion_stats={},
        )
        assert len(desc) > 0

    def test_no_mood_tags_graceful(self):
        desc = generate_description(
            neuro_profile={"para": 0.50, "symp": 0.30, "grnd": 0.20},
            songs=[{"mood_tags": None} for _ in range(5)],
            cohesion_stats={"dominant_genre": "rock"},
        )
        assert "Rock" in desc

    def test_under_300_chars(self):
        desc = generate_description(
            neuro_profile={"para": 0.95, "symp": 0.00, "grnd": 0.05},
            songs=self._make_songs(["calm", "soothing", "peaceful", "relaxed", "serene"]),
            cohesion_stats={"dominant_genre": "bollywood"},
        )
        assert len(desc) <= 300


class TestGetDominantMoods:
    def test_counts_across_songs(self):
        songs = [
            {"mood_tags": ["calm", "soothing"]},
            {"mood_tags": ["calm", "peaceful"]},
            {"mood_tags": ["calm", "soothing", "warm"]},
        ]
        moods = _get_dominant_moods(songs, top_n=2)
        assert moods[0] == "calm"  # 3 occurrences
        assert len(moods) == 2

    def test_empty_songs(self):
        assert _get_dominant_moods([]) == []

    def test_none_mood_tags(self):
        assert _get_dominant_moods([{"mood_tags": None}]) == []


class TestGetNeuroPurpose:
    def test_para(self):
        assert _get_neuro_purpose({"para": 0.9, "symp": 0.0, "grnd": 0.1}) == "Calming your nervous system"

    def test_symp(self):
        assert _get_neuro_purpose({"para": 0.1, "symp": 0.8, "grnd": 0.1}) == "Matching your energy"

    def test_grnd(self):
        assert _get_neuro_purpose({"para": 0.1, "symp": 0.0, "grnd": 0.9}) == "Grounding your emotions"


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


# ---------------------------------------------------------------------------
# _filter_unavailable_tracks
# ---------------------------------------------------------------------------

@patch("matching.generator.time.sleep")
class TestFilterUnavailableTracks:

    def _make_songs(self, uris):
        return [{"spotify_uri": uri, "name": f"Song {i}"} for i, uri in enumerate(uris)]

    def test_filters_unavailable_tracks(self, mock_sleep):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.side_effect = [
            {"uri": "spotify:track:a", "name": "A", "artists": [{"name": "Art"}], "is_playable": True},
            {"uri": "spotify:track:b", "name": "B", "artists": [{"name": "Art"}], "is_playable": False},
            {"uri": "spotify:track:c", "name": "C", "artists": [{"name": "Art"}], "is_playable": True},
        ]
        songs = self._make_songs(["spotify:track:a", "spotify:track:b", "spotify:track:c"])
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 2
        assert all(s["spotify_uri"] != "spotify:track:b" for s in result)

    def test_all_available_no_change(self, mock_sleep):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.side_effect = [
            {"uri": "spotify:track:a", "name": "A", "artists": [{"name": "Art"}], "is_playable": True},
            {"uri": "spotify:track:b", "name": "B", "artists": [{"name": "Art"}], "is_playable": True},
        ]
        songs = self._make_songs(["spotify:track:a", "spotify:track:b"])
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 2

    def test_api_failure_returns_all_songs(self, mock_sleep):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.side_effect = Exception("API error")
        songs = self._make_songs(["spotify:track:a", "spotify:track:b"])
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 2  # graceful fallback

    def test_empty_songs_returns_empty(self, mock_sleep):
        sp = MagicMock(spec=spotipy.Spotify)
        result = _filter_unavailable_tracks(sp, [])
        assert result == []
        sp.track.assert_not_called()

    def test_missing_is_playable_treated_as_available(self, mock_sleep):
        """Tracks without is_playable field default to available (True)."""
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.return_value = {"uri": "spotify:track:a", "name": "A", "artists": [{"name": "Art"}]}
        songs = self._make_songs(["spotify:track:a"])
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 1

    def test_null_track_treated_as_available(self, mock_sleep):
        """sp.track() returning None should not crash — treat as available."""
        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.return_value = None
        songs = self._make_songs(["spotify:track:a"])
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 1  # no crash, treated as available


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
        assert "Mar 19" in result["name"]
        assert "Fuel Up" in result["name"]  # baseline symp-dominant, no recovery → default
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
        assert "Matching your energy" in result["description"]  # symp-dominant baseline
        assert "Rock" in result["description"]  # dominant genre from mock
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
