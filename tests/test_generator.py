"""Tests for matching/generator.py — end-to-end playlist generation."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy

from intelligence.continuous_profile import pick_state, profile_at
from matching.generator import (
    NAME_DEEP_SHARE,
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

CALM = {"para": 0.60, "symp": 0.10, "grnd": 0.30}
STEADY = {"para": 0.25, "symp": 0.25, "grnd": 0.50}
LIFT = {"para": 0.10, "symp": 0.60, "grnd": 0.30}


class TestFormatPlaylistName:
    def test_date_then_label(self):
        assert format_playlist_name("2026-03-19", CALM, 0.05) == "Mar 19 — Rest & Repair"

    def test_single_digit_day_not_padded(self):
        assert format_playlist_name("2026-03-05", LIFT, 0.95) == "Mar 5 — Stay Sharp"

    def test_unscored_day(self):
        assert format_playlist_name("2026-12-25", STEADY, None) == "Dec 25 — Ground Yourself"


class TestPickNameLabel:
    """The name follows the day's state (the profile's lead) and the Attuned score's position
    (0 = your lowest day so far, 1 = your best), never WHOOP recovery."""

    @pytest.mark.parametrize("position, label", [
        (0.0, "Rest & Repair"), (NAME_DEEP_SHARE - 0.001, "Rest & Repair"),
        (NAME_DEEP_SHARE, "Settle In"), (0.28, "Settle In"),
    ])
    def test_rest(self, position, label):
        assert _pick_name_label(CALM, position) == label

    @pytest.mark.parametrize("position, label", [
        (1.0, "Stay Sharp"), (1 - NAME_DEEP_SHARE + 0.001, "Stay Sharp"),
        (1 - NAME_DEEP_SHARE, "Fuel Up"), (0.72, "Fuel Up"),
    ])
    def test_energy(self, position, label):
        assert _pick_name_label(LIFT, position) == label

    @pytest.mark.parametrize("position, label", [
        (0.30, "Ground Yourself"), (0.499, "Ground Yourself"), (0.5, "Ease Into It"), (0.70, "Ease Into It"),
    ])
    def test_grounding_leans_by_side_of_your_usual(self, position, label):
        assert _pick_name_label(STEADY, position) == label

    @pytest.mark.parametrize("profile, label", [
        (CALM, "Settle In"), (LIFT, "Fuel Up"), (STEADY, "Ground Yourself"),
    ])
    def test_no_position_gets_the_plain_name_for_the_state(self, profile, label):
        assert _pick_name_label(profile, None) == label

    def test_every_real_position_names_its_own_state(self):
        """Across the whole score line, the name always belongs to the playlist's state."""
        names = {"rest": {"Rest & Repair", "Settle In"}, "energy": {"Stay Sharp", "Fuel Up"},
                 "grounding": {"Ground Yourself", "Ease Into It"}}
        seen = set()
        for i in range(1001):
            profile = profile_at(i / 1000)
            label = _pick_name_label(profile, i / 1000)
            assert label in names[pick_state(profile)[0]], i
            seen.add(label)
        assert seen == set().union(*names.values())  # every name is reachable

    def test_lower_position_never_gets_a_more_upbeat_name(self):
        order = ["Rest & Repair", "Settle In", "Ground Yourself", "Ease Into It", "Fuel Up", "Stay Sharp"]
        ranks = [order.index(_pick_name_label(profile_at(i / 1000), i / 1000)) for i in range(1001)]
        assert ranks == sorted(ranks)


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
        assert "Built to help you settle" in desc
        assert "Bollywood" in desc

    def test_symp_dominant_description(self):
        desc = generate_description(
            neuro_profile={"para": 0.15, "symp": 0.50, "grnd": 0.35},
            songs=self._make_songs(["energetic", "uplifting"]),
            cohesion_stats={"dominant_genre": "rock"},
        )
        assert "Built to give you a lift" in desc
        assert "Rock" in desc

    def test_grnd_dominant_description(self):
        desc = generate_description(
            neuro_profile={"para": 0.10, "symp": 0.00, "grnd": 0.90},
            songs=self._make_songs(["reflective", "nostalgic"]),
            cohesion_stats={"dominant_genre": "bollywood"},
        )
        assert "Built to keep you level" in desc

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
        assert _get_neuro_purpose({"para": 0.9, "symp": 0.0, "grnd": 0.1}) == "Built to help you settle"

    def test_symp(self):
        assert _get_neuro_purpose({"para": 0.1, "symp": 0.8, "grnd": 0.1}) == "Built to give you a lift"

    def test_grnd(self):
        assert _get_neuro_purpose({"para": 0.1, "symp": 0.0, "grnd": 0.9}) == "Built to keep you level"


# ---------------------------------------------------------------------------
# format_reasoning
# ---------------------------------------------------------------------------

class TestFormatReasoning:
    def test_includes_attuned_state_and_match_details(self):
        classification = {
            "state": "accumulated_fatigue",
            "confidence": "high",
            "reasoning": ["Multi-day stress pattern"],
            "metrics": {"recovery_score": 35.0},
        }
        match_result = {
            "state": "rest",
            "position": 0.05,
            "match_stats": {"total_candidates": 500, "selected": 18,
                            "cohesion_stats": {
                                "pool_size": 60, "mean_similarity": 0.42,
                                "dominant_genre": "rock", "relaxations": 0,
                            }},
            "neuro_profile": {"para": 0.95, "symp": 0.00, "grnd": 0.05},
        }
        reasoning = format_reasoning(classification, match_result)
        assert "State: rest" in reasoning
        assert "Attuned position: 0.05" in reasoning
        assert "recovery_score: 35.0" in reasoning  # WHOOP metrics kept for the record
        assert "Candidates: 500" in reasoning
        assert "Selected: 18" in reasoning
        assert "Para: 0.95" in reasoning
        assert "Cohesion pool: 60" in reasoning
        assert "Mean similarity: 0.4200" in reasoning
        assert "Dominant genre: rock" in reasoning

    def test_old_classifier_state_and_reasoning_left_out(self):
        classification = {"state": "accumulated_fatigue", "confidence": "high",
                          "reasoning": ["Multi-day stress pattern"], "metrics": {}}
        reasoning = format_reasoning(classification, {"state": "energy", "position": 0.9,
                                                      "match_stats": {}, "neuro_profile": {}})
        assert "accumulated_fatigue" not in reasoning
        assert "Multi-day stress pattern" not in reasoning
        assert "Confidence" not in reasoning

    def test_no_score_no_metrics(self):
        classification = {"state": "baseline", "confidence": "medium", "reasoning": [], "metrics": {}}
        match_result = {"state": "grounding", "position": None, "match_stats": {}, "neuro_profile": {}}
        reasoning = format_reasoning(classification, match_result)
        assert "State: grounding" in reasoning
        assert "Attuned position: none" in reasoning
        assert "Metrics:" not in reasoning


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

    def test_persists_availability_to_db(self, mock_sleep, tmp_path):
        """Results are written to the DB when conn is provided."""
        from db.schema import get_connection
        from db import queries

        conn = get_connection(tmp_path / "test.db")
        queries.upsert_song(conn, "spotify:track:a", "A", "Artist")
        queries.upsert_song(conn, "spotify:track:b", "B", "Artist")

        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.side_effect = [
            {"uri": "spotify:track:a", "name": "A", "artists": [{"name": "Art"}], "is_playable": True},
            {"uri": "spotify:track:b", "name": "B", "artists": [{"name": "Art"}], "is_playable": False},
        ]
        songs = self._make_songs(["spotify:track:a", "spotify:track:b"])
        _filter_unavailable_tracks(sp, songs, conn=conn)

        row_a = conn.execute("SELECT is_available FROM songs WHERE spotify_uri = 'spotify:track:a'").fetchone()
        row_b = conn.execute("SELECT is_available FROM songs WHERE spotify_uri = 'spotify:track:b'").fetchone()
        assert row_a["is_available"] == 1
        assert row_b["is_available"] == 0
        conn.close()

    def test_skips_recently_checked_available_songs(self, mock_sleep):
        """Songs checked within AVAILABILITY_CACHE_DAYS skip the API call."""
        from datetime import datetime, timezone

        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.return_value = {"uri": "spotify:track:b", "name": "B", "artists": [{"name": "Art"}], "is_playable": True}

        recent_ts = datetime.now(timezone.utc).isoformat()
        songs = [
            {"spotify_uri": "spotify:track:a", "name": "A", "is_available": 1, "availability_checked_at": recent_ts},
            {"spotify_uri": "spotify:track:b", "name": "B", "is_available": None, "availability_checked_at": None},
        ]
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 2
        # Only track:b should have been checked via API (track:a was cached)
        assert sp.track.call_count == 1
        sp.track.assert_called_once_with("b")

    def test_rechecks_stale_availability(self, mock_sleep):
        """Songs checked more than AVAILABILITY_CACHE_DAYS ago are re-checked."""
        from datetime import datetime, timezone, timedelta

        sp = MagicMock(spec=spotipy.Spotify)
        sp.track.return_value = {"uri": "spotify:track:a", "name": "A", "artists": [{"name": "Art"}], "is_playable": True}

        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        songs = [
            {"spotify_uri": "spotify:track:a", "name": "A", "is_available": 1, "availability_checked_at": old_ts},
        ]
        result = _filter_unavailable_tracks(sp, songs)
        assert len(result) == 1
        assert sp.track.call_count == 1  # stale, so re-checked


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
        assert result["state"] == "grounding"  # no Attuned score → steady target
        assert len(result["songs"]) == 18
        assert "Mar 19" in result["name"]
        assert "Fuel Up" in result["name"]  # symp-dominant, no Attuned score → plain energy name
        conn.close()

    @pytest.mark.parametrize("position, profile, recovery, name", [
        (0.95, LIFT, 20.0, "Mar 19 — Stay Sharp"),     # WHOOP red, Attuned near your best
        (0.05, CALM, 90.0, "Mar 19 — Rest & Repair"),  # WHOOP green, Attuned near your lowest
    ])
    @patch("matching.generator.select_songs")
    @patch("matching.generator.classify_state")
    def test_name_follows_attuned_score_not_whoop(self, mock_classify, mock_select,
                                                  position, profile, recovery, name, db_conn):
        mock_classify.return_value = _make_classification(metrics={"recovery_score": recovery})
        mock_select.side_effect = lambda *a, **kw: {**_make_match_result(),
                                                    "neuro_profile": kw["neuro_profile"]}
        continuous = {"profile": profile, "target_valence": 0.5, "position": position,
                      "state": pick_state(profile)[0],
                      "z_scores": {}, "signals_used": 0}
        with patch("intelligence.continuous_profile.compute_continuous_profile", return_value=continuous):
            result = generate_playlist(db_conn, sp=None, date_str="2026-03-19", dry_run=True)
        assert result["name"] == name
        assert result["state"] == pick_state(profile)[0]  # Attuned's state, whatever WHOOP says
        row = db_conn.execute("SELECT detected_state FROM generated_playlists").fetchone()
        assert row["detected_state"] == pick_state(profile)[0]

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
        assert row["detected_state"] == "grounding"  # the Attuned state, not the old classifier's
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
        assert "Built to give you a lift" in result["description"]  # symp-dominant baseline
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
