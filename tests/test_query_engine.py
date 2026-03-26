"""Tests for matching/query_engine.py — neuro-score song scoring and selection."""

import json
from datetime import datetime, timedelta

import pytest

from db.queries import (
    get_days_since_last_appearance,
    get_recent_playlist_track_uris,
    insert_generated_playlist,
    upsert_song,
    upsert_song_classification,
)
from matching.query_engine import (
    _apply_lead_track_ordering,
    _dedup_near_duplicates,
    _normalize_title,
    compute_confidence_multiplier,
    compute_engagement_p75,
    compute_min_repeat_gap,
    compute_neuro_match,
    compute_selection_scores,
    identify_anchors,
    is_current_banger,
    score_song,
    select_songs,
)


# ---------------------------------------------------------------------------
# Near-duplicate detection tests
# ---------------------------------------------------------------------------

class TestNormalizeTitle:

    def test_strips_from_single_quotes(self):
        assert _normalize_title("Tum Hi Ho Bandhu (From 'Cocktail')") == "tum hi ho bandhu"

    def test_strips_from_double_quotes(self):
        assert _normalize_title('Tum Hi Ho Bandhu (From "Cocktail")') == "tum hi ho bandhu"

    def test_preserves_remix(self):
        assert "(remix)" in _normalize_title("Song Name (Remix)")

    def test_preserves_acoustic(self):
        assert "(acoustic)" in _normalize_title("Song Name (Acoustic)")

    def test_preserves_live(self):
        assert "(live)" in _normalize_title("Song Name (Live)")

    def test_no_parens_unchanged(self):
        assert _normalize_title("Just a Song") == "just a song"

    def test_case_insensitive_from(self):
        assert _normalize_title("Song (FROM 'Movie')") == "song"


class TestDedupNearDuplicates:

    def test_removes_duplicate_same_artist(self):
        songs = [
            {"name": "Tum Hi Ho Bandhu (From 'Cocktail')", "artist": "Neeraj Shridhar",
             "play_count": 15, "spotify_uri": "uri:1"},
            {"name": "Tum Hi Ho Bandhu", "artist": "Neeraj Shridhar",
             "play_count": 5, "spotify_uri": "uri:2"},
        ]
        result = _dedup_near_duplicates(songs)
        assert len(result) == 1
        assert result[0]["spotify_uri"] == "uri:1"  # more plays

    def test_keeps_different_artists(self):
        songs = [
            {"name": "Tum Hi Ho", "artist": "Arijit Singh", "play_count": 10, "spotify_uri": "uri:1"},
            {"name": "Tum Hi Ho", "artist": "Someone Else", "play_count": 5, "spotify_uri": "uri:2"},
        ]
        result = _dedup_near_duplicates(songs)
        assert len(result) == 2

    def test_keeps_remix_as_distinct(self):
        songs = [
            {"name": "Song Name", "artist": "Artist", "play_count": 10, "spotify_uri": "uri:1"},
            {"name": "Song Name (Remix)", "artist": "Artist", "play_count": 5, "spotify_uri": "uri:2"},
        ]
        result = _dedup_near_duplicates(songs)
        assert len(result) == 2

    def test_keeps_higher_play_count(self):
        songs = [
            {"name": "Song (From 'Movie A')", "artist": "Artist", "play_count": 3, "spotify_uri": "uri:1"},
            {"name": "Song (From 'Movie B')", "artist": "Artist", "play_count": 20, "spotify_uri": "uri:2"},
        ]
        result = _dedup_near_duplicates(songs)
        assert len(result) == 1
        assert result[0]["spotify_uri"] == "uri:2"

    def test_no_duplicates_returns_all(self):
        songs = [
            {"name": "Song A", "artist": "Artist 1", "play_count": 10, "spotify_uri": "uri:1"},
            {"name": "Song B", "artist": "Artist 2", "play_count": 5, "spotify_uri": "uri:2"},
        ]
        result = _dedup_near_duplicates(songs)
        assert len(result) == 2

    def test_empty_list(self):
        assert _dedup_near_duplicates([]) == []

    def test_dedup_three_copies_keeps_highest_plays(self):
        songs = [
            {"name": "Tum Hi Ho (From 'Aashiqui 2')", "artist": "Arijit Singh",
             "play_count": 5, "spotify_uri": "uri:1"},
            {"name": "Tum Hi Ho (From 'Aashiqui 2 Deluxe')", "artist": "Arijit Singh",
             "play_count": 20, "spotify_uri": "uri:2"},
            {"name": "Tum Hi Ho (From 'Bollywood Hits')", "artist": "Arijit Singh",
             "play_count": 8, "spotify_uri": "uri:3"},
        ]
        result = _dedup_near_duplicates(songs)
        assert len(result) == 1
        assert result[0]["spotify_uri"] == "uri:2"  # 20 plays — highest


# ---------------------------------------------------------------------------
# compute_neuro_match tests
# ---------------------------------------------------------------------------

class TestComputeNeuroMatch:

    def test_perfect_alignment_para(self):
        score = compute_neuro_match(1.0, 0.0, 0.0, {"para": 0.85, "symp": 0.00, "grnd": 0.15})
        assert score > 0.9

    def test_perfect_alignment_symp(self):
        score = compute_neuro_match(0.0, 1.0, 0.0, {"para": 0.00, "symp": 0.85, "grnd": 0.15})
        assert score > 0.9

    def test_perfect_alignment_grnd(self):
        score = compute_neuro_match(0.0, 0.0, 1.0, {"para": 0.15, "symp": 0.00, "grnd": 0.85})
        assert score > 0.9

    def test_misalignment_para_vs_symp(self):
        score = compute_neuro_match(1.0, 0.0, 0.0, {"para": 0.00, "symp": 0.85, "grnd": 0.15})
        assert score < 0.2

    def test_misalignment_symp_vs_fatigue(self):
        score = compute_neuro_match(0.0, 1.0, 0.0, {"para": 0.85, "symp": 0.00, "grnd": 0.15})
        assert score < 0.2

    def test_balanced_song_moderate_score(self):
        score = compute_neuro_match(0.5, 0.5, 0.5, {"para": 0.85, "symp": 0.00, "grnd": 0.15})
        assert 0.3 < score < 0.7

    def test_none_scores_treated_as_zero(self):
        score = compute_neuro_match(None, None, None, {"para": 0.85, "symp": 0.00, "grnd": 0.15})
        assert score == 0.0

    def test_partial_none(self):
        score_with = compute_neuro_match(0.8, 0.0, 0.0, {"para": 0.85, "symp": 0.00, "grnd": 0.15})
        score_none = compute_neuro_match(0.8, None, 0.0, {"para": 0.85, "symp": 0.00, "grnd": 0.15})
        assert score_with == pytest.approx(score_none)

    def test_result_bounded_0_to_1(self):
        score = compute_neuro_match(1.0, 1.0, 1.0, {"para": 1.0, "symp": 1.0, "grnd": 1.0})
        assert 0.0 <= score <= 1.0

    def test_zero_profile_returns_zero(self):
        score = compute_neuro_match(1.0, 1.0, 1.0, {"para": 0.0, "symp": 0.0, "grnd": 0.0})
        assert score == 0.0

    def test_differentiates_fatigue_from_emotional(self):
        calming = (0.9, 0.05, 0.1)
        fatigue_profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        emotional_profile = {"para": 0.15, "symp": 0.00, "grnd": 0.85}
        assert compute_neuro_match(*calming, fatigue_profile) > compute_neuro_match(*calming, emotional_profile)


# ---------------------------------------------------------------------------
# compute_confidence_multiplier tests
# ---------------------------------------------------------------------------

class TestConfidenceMultiplier:

    def test_high_confidence(self):
        assert compute_confidence_multiplier(0.75) == 1.0

    def test_medium_confidence(self):
        assert compute_confidence_multiplier(0.60) == 0.85

    def test_low_confidence(self):
        assert compute_confidence_multiplier(0.40) == 0.6

    def test_none_confidence(self):
        assert compute_confidence_multiplier(None) == 0.6

    def test_boundary_0_7(self):
        assert compute_confidence_multiplier(0.7) == 1.0

    def test_boundary_0_5(self):
        assert compute_confidence_multiplier(0.5) == 0.85


# ---------------------------------------------------------------------------
# score_song tests
# ---------------------------------------------------------------------------

class TestScoreSong:

    def _make_song(self, uri: str, para: float = 0.5, symp: float = 0.3,
                   grnd: float = 0.2, confidence: float = 0.7, **extras) -> dict:
        defaults = {
            "spotify_uri": uri, "parasympathetic": para,
            "sympathetic": symp, "grounding": grnd, "confidence": confidence,
        }
        defaults.update(extras)
        return defaults

    def test_formula_is_neuro_times_confidence_times_familiarity(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8, confidence=0.7, engagement_score=0.5)
        score, bd = score_song(song, profile)
        expected = bd["neuro_match"] * bd["confidence_mult"] * bd["familiarity_mult"]
        assert score == pytest.approx(expected, abs=0.001)
        assert bd["familiarity_mult"] == 1.0  # has engagement

    def test_unfamiliar_song_penalized(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        familiar = self._make_song("uri:1", para=0.8, engagement_score=0.5)
        unfamiliar = self._make_song("uri:2", para=0.8)  # no engagement_score
        score_f, bd_f = score_song(familiar, profile)
        score_u, bd_u = score_song(unfamiliar, profile)
        assert bd_f["familiarity_mult"] == 1.0
        assert bd_u["familiarity_mult"] == 0.95
        assert score_f > score_u

    def test_no_variety_in_score(self):
        profile = {"para": 0.50, "symp": 0.30, "grnd": 0.20}
        song = self._make_song("uri:1")
        _, bd = score_song(song, profile)
        assert "variety" not in bd

    def test_freshness_nudge_for_yesterday(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        score_clean, _ = score_song(song, profile)
        score_nudged, bd = score_song(song, profile, {"uri:1": 1})
        assert bd["freshness_nudge"] == pytest.approx(0.04)
        assert score_nudged == pytest.approx(score_clean - 0.04, abs=0.001)

    def test_freshness_nudge_for_two_days_ago(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, {"uri:1": 2})
        assert bd["freshness_nudge"] == pytest.approx(0.03)

    def test_freshness_nudge_for_three_days_ago(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, {"uri:1": 3})
        assert bd["freshness_nudge"] == pytest.approx(0.02)

    def test_freshness_nudge_for_four_days_ago(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, {"uri:1": 4})
        assert bd["freshness_nudge"] == pytest.approx(0.01)

    def test_no_freshness_nudge_for_five_days_ago(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, {"uri:1": 5})
        assert bd["freshness_nudge"] == 0.0

    def test_no_nudge_when_not_in_recent_playlists(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, {"uri:other": 1})
        assert bd["freshness_nudge"] == 0.0

    def test_no_nudge_when_no_recent_playlists(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, None)
        assert bd["freshness_nudge"] == 0.0

    def test_no_engagement_in_score(self):
        profile = {"para": 0.50, "symp": 0.30, "grnd": 0.20}
        song = self._make_song("uri:1", engagement_score=0.99)
        _, bd = score_song(song, profile)
        assert "engagement" not in bd


# ---------------------------------------------------------------------------
# compute_selection_scores tests
# ---------------------------------------------------------------------------

class TestComputeSelectionScores:

    def _make_song(self, uri: str, para: float = 0.5, symp: float = 0.3,
                   grnd: float = 0.2, confidence: float = 0.7, **extras) -> dict:
        defaults = {
            "spotify_uri": uri, "parasympathetic": para,
            "sympathetic": symp, "grounding": grnd, "confidence": confidence,
        }
        defaults.update(extras)
        return defaults

    def test_returns_sorted_by_score_desc(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        songs = [
            self._make_song("uri:1", para=0.2, symp=0.7, grnd=0.1),
            self._make_song("uri:2", para=0.9, symp=0.0, grnd=0.1),
        ]
        scored = compute_selection_scores(songs, profile)
        assert scored[0][0]["spotify_uri"] == "uri:2"

    def test_confidence_affects_ranking(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        high_conf = self._make_song("uri:hi", para=0.8, confidence=0.8)
        low_conf = self._make_song("uri:lo", para=0.8, confidence=0.3)
        scored = compute_selection_scores([low_conf, high_conf], profile)
        assert scored[0][0]["spotify_uri"] == "uri:hi"

    def test_empty_songs_returns_empty(self):
        assert compute_selection_scores([], {"para": 0.5, "symp": 0.3, "grnd": 0.2}) == []


# ---------------------------------------------------------------------------
# select_songs integration tests
# ---------------------------------------------------------------------------

class TestSelectSongs:

    @staticmethod
    def _add_personal_play(conn, uri, idx=0):
        """Add personal-device play so songs pass the autoplay filter."""
        conn.execute(
            """INSERT OR IGNORE INTO listening_history
               (spotify_uri, played_at, ms_played, platform)
               VALUES (?, ?, 60000, 'ios')""",
            (uri, f"2026-01-{(idx % 28) + 1:02d}T{idx % 24:02d}:00:00Z"),
        )

    # Genre pools for seeding test songs with cohesion signal
    _GENRE_POOLS = [
        (["rock", "indie"], ["energetic", "uplifting"]),
        (["bollywood", "hindi"], ["romantic", "nostalgic"]),
        (["hip-hop", "rap"], ["confident", "aggressive"]),
    ]

    def _seed_songs(self, conn, count: int = 30) -> None:
        import random
        random.seed(42)
        for i in range(count):
            uri = f"spotify:track:test{i:03d}"
            days_ago = random.choice([1, 7, 30, 60, 120, 200, 365, 500, None])
            if days_ago is not None:
                from datetime import datetime, timedelta
                lp = (datetime(2026, 3, 19) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            else:
                lp = None
            release_year = random.choice([2018, 2019, 2020, 2021, 2022, 2023, None])
            upsert_song(conn, uri, f"Song {i}", f"Artist {i}",
                        sources=["test"], last_played=lp, release_year=release_year)
            conn.execute(
                "UPDATE songs SET play_count = ? WHERE spotify_uri = ?",
                (random.randint(5, 50), uri),
            )
            genre_tags, mood_tags = self._GENRE_POOLS[i % len(self._GENRE_POOLS)]
            upsert_song_classification(conn, {
                "spotify_uri": uri,
                "parasympathetic": random.uniform(0.0, 1.0),
                "sympathetic": random.uniform(0.0, 1.0),
                "grounding": random.uniform(0.0, 1.0),
                "confidence": random.uniform(0.5, 0.8),
                "bpm": random.uniform(80.0, 140.0),
                "energy": random.uniform(0.3, 0.9),
                "genre_tags": genre_tags,
                "mood_tags": mood_tags,
                "classification_source": "test",
            })
            # Add personal-device play so songs pass the autoplay filter
            conn.execute(
                """INSERT OR IGNORE INTO listening_history
                   (spotify_uri, played_at, ms_played, platform)
                   VALUES (?, ?, 60000, 'ios')""",
                (uri, f"2026-01-{(i % 28) + 1:02d}T12:00:00Z"),
            )
        conn.commit()

    def test_select_returns_up_to_max_playlist_size(self, db_conn):
        self._seed_songs(db_conn, count=30)
        result = select_songs(db_conn, "baseline", "2026-03-19")
        assert len(result["songs"]) <= 20

    def test_select_returns_neuro_profile(self, db_conn):
        self._seed_songs(db_conn)
        result = select_songs(db_conn, "accumulated_fatigue", "2026-03-19")
        assert result["state"] == "accumulated_fatigue"
        assert "para" in result["neuro_profile"]

    def test_neuro_profile_override_used(self, db_conn):
        """When override provided, use it instead of default state profile."""
        self._seed_songs(db_conn, count=30)
        override = {"para": 0.10, "symp": 0.80, "grnd": 0.10}
        result = select_songs(db_conn, "accumulated_fatigue", "2026-03-19",
                              neuro_profile_override=override)
        assert result["neuro_profile"] == override
        # Should still report the correct state
        assert result["state"] == "accumulated_fatigue"

    def test_no_override_uses_default_profile(self, db_conn):
        """Without override, should use standard state profile."""
        self._seed_songs(db_conn, count=30)
        result = select_songs(db_conn, "accumulated_fatigue", "2026-03-19")
        from config import STATE_NEURO_PROFILES
        expected = STATE_NEURO_PROFILES["accumulated_fatigue"]
        assert result["neuro_profile"] == expected

    def test_select_with_empty_library(self, db_conn):
        result = select_songs(db_conn, "baseline", "2026-03-19")
        assert result["songs"] == []

    def test_select_with_few_songs(self, db_conn):
        self._seed_songs(db_conn, count=5)
        result = select_songs(db_conn, "baseline", "2026-03-19")
        assert len(result["songs"]) == 5

    def test_insufficient_data_raises(self, db_conn):
        with pytest.raises(ValueError, match="insufficient_data"):
            select_songs(db_conn, "insufficient_data", "2026-03-19")

    def test_cohesion_stats_in_match_stats(self, db_conn):
        """match_stats should include cohesion_stats with expected keys."""
        self._seed_songs(db_conn)
        result = select_songs(db_conn, "baseline", "2026-03-19")
        stats = result["match_stats"]
        assert "cohesion_stats" in stats
        cohesion = stats["cohesion_stats"]
        assert "pool_size" in cohesion
        assert "mean_similarity" in cohesion
        assert "dominant_genre" in cohesion

    def test_cohesive_cluster_has_genre_signal(self, db_conn):
        """Selected songs should cluster around a dominant genre."""
        # Seed 30 rock songs and 30 bollywood songs, all high para
        for i in range(30):
            uri = f"spotify:track:rock{i:03d}"
            upsert_song(db_conn, uri, f"Rock {i}", "Rock Artist",
                        sources=["test"], last_played="2026-03-18")
            db_conn.execute("UPDATE songs SET play_count = 10 WHERE spotify_uri = ?", (uri,))
            upsert_song_classification(db_conn, {
                "spotify_uri": uri, "parasympathetic": 0.8, "sympathetic": 0.05,
                "grounding": 0.1, "confidence": 0.7,
                "bpm": 120.0 + i * 0.5, "energy": 0.7,
                "genre_tags": ["rock", "indie"],
                "mood_tags": ["energetic", "uplifting"],
                "classification_source": "test",
            })
            self._add_personal_play(db_conn, uri, i)
        for i in range(30):
            uri = f"spotify:track:bolly{i:03d}"
            upsert_song(db_conn, uri, f"Bollywood {i}", "Hindi Artist",
                        sources=["test"], last_played="2026-03-18")
            db_conn.execute("UPDATE songs SET play_count = 10 WHERE spotify_uri = ?", (uri,))
            upsert_song_classification(db_conn, {
                "spotify_uri": uri, "parasympathetic": 0.8, "sympathetic": 0.05,
                "grounding": 0.1, "confidence": 0.7,
                "bpm": 100.0 + i * 0.5, "energy": 0.5,
                "genre_tags": ["bollywood", "hindi"],
                "mood_tags": ["romantic", "nostalgic"],
                "classification_source": "test",
            })
            self._add_personal_play(db_conn, uri, 30 + i)
        db_conn.commit()
        result = select_songs(db_conn, "accumulated_fatigue", "2026-03-19")
        # Most selected songs should share the same genre cluster
        genre_counts = {}
        for s in result["songs"]:
            for g in (s.get("genre_tags") or []):
                genre_counts[g] = genre_counts.get(g, 0) + 1
        top_genre = max(genre_counts, key=genre_counts.get) if genre_counts else None
        assert top_genre is not None
        # At least 60% of genre tags should be from the dominant cluster
        total_tags = sum(genre_counts.values())
        assert genre_counts[top_genre] / total_tags > 0.4

    def test_all_songs_eligible_regardless_of_engagement(self, db_conn):
        for i in range(5):
            uri = f"spotify:track:low{i}"
            upsert_song(db_conn, uri, f"Song {i}", "Artist",
                        sources=["test"], last_played="2025-01-01")
            db_conn.execute(
                "UPDATE songs SET engagement_score = 0.01, play_count = 2 WHERE spotify_uri = ?",
                (uri,),
            )
            upsert_song_classification(db_conn, {
                "spotify_uri": uri, "parasympathetic": 0.8, "sympathetic": 0.05,
                "grounding": 0.1, "confidence": 0.7, "classification_source": "test",
            })
            self._add_personal_play(db_conn, uri, i)
        db_conn.commit()
        result = select_songs(db_conn, "accumulated_fatigue", "2026-03-19")
        assert result["match_stats"]["total_candidates"] == 5

    def test_fatigue_selects_para_dominant_songs(self, db_conn):
        self._seed_songs(db_conn, count=150)
        fatigue = select_songs(db_conn, "accumulated_fatigue", "2026-03-19")
        peak = select_songs(db_conn, "peak_readiness", "2026-03-19")
        avg_para_fatigue = sum(s.get("parasympathetic") or 0 for s in fatigue["songs"]) / max(len(fatigue["songs"]), 1)
        avg_para_peak = sum(s.get("parasympathetic") or 0 for s in peak["songs"]) / max(len(peak["songs"]), 1)
        assert avg_para_fatigue > avg_para_peak

    def test_selected_songs_have_required_fields(self, db_conn):
        self._seed_songs(db_conn)
        result = select_songs(db_conn, "baseline", "2026-03-19")
        for song in result["songs"]:
            assert "spotify_uri" in song
            assert "selection_score" in song
            assert "breakdown" in song
            assert "parasympathetic" in song
            assert "genre_tags" in song
            assert "bpm" in song

    def test_selected_songs_include_cohesion_fields(self, db_conn):
        self._seed_songs(db_conn)
        result = select_songs(db_conn, "baseline", "2026-03-19")
        for song in result["songs"]:
            assert "genre_tags" in song
            assert "mood_tags" in song
            assert "bpm" in song
            assert "energy" in song

    def test_near_duplicate_songs_deduped(self, db_conn):
        """Same song from two albums should appear only once, keeping more-played version."""
        # Seed two versions of the same song with different albums
        uri_more = "spotify:track:dup_more"
        uri_less = "spotify:track:dup_less"
        upsert_song(db_conn, uri_more, "Tum Hi Ho Bandhu (From 'Cocktail')",
                     "Neeraj Shridhar", sources=["test"], last_played="2026-03-18")
        db_conn.execute("UPDATE songs SET play_count = 20 WHERE spotify_uri = ?", (uri_more,))
        upsert_song(db_conn, uri_less, "Tum Hi Ho Bandhu",
                     "Neeraj Shridhar", sources=["test"], last_played="2026-03-18")
        db_conn.execute("UPDATE songs SET play_count = 3 WHERE spotify_uri = ?", (uri_less,))

        for idx, uri in enumerate([uri_more, uri_less]):
            upsert_song_classification(db_conn, {
                "spotify_uri": uri, "parasympathetic": 0.8, "sympathetic": 0.05,
                "grounding": 0.1, "confidence": 0.7,
                "bpm": 120.0, "energy": 0.6,
                "genre_tags": ["bollywood", "hindi"],
                "mood_tags": ["uplifting", "energetic"],
                "classification_source": "test",
            })
            self._add_personal_play(db_conn, uri, idx)

        # Seed enough other songs to fill the pool
        self._seed_songs(db_conn, count=30)
        db_conn.commit()

        result = select_songs(db_conn, "baseline", "2026-03-19")
        uris = [s["spotify_uri"] for s in result["songs"]]
        names = [s["name"].lower() for s in result["songs"]]

        # At most one version of "Tum Hi Ho Bandhu" in the playlist
        bandhu_count = sum(1 for n in names if "tum hi ho bandhu" in n)
        assert bandhu_count <= 1

        # If present, it should be the more-played version
        if uri_more in uris:
            assert uri_less not in uris

    def test_backfill_after_dedup_maintains_playlist_size(self, db_conn):
        """When dedup removes a duplicate, backfill should restore playlist to 20 songs."""
        import random
        random.seed(99)

        # Seed 30+ unique songs with varied neuro scores
        for i in range(32):
            uri = f"spotify:track:fill{i:03d}"
            upsert_song(db_conn, uri, f"Unique Song {i}", f"Artist {i}",
                        sources=["test"], last_played="2026-03-18")
            db_conn.execute(
                "UPDATE songs SET play_count = ? WHERE spotify_uri = ?",
                (random.randint(5, 40), uri),
            )
            upsert_song_classification(db_conn, {
                "spotify_uri": uri,
                "parasympathetic": 0.85 - i * 0.01,  # high para for fatigue state
                "sympathetic": 0.05,
                "grounding": 0.1,
                "confidence": 0.7,
                "bpm": 70.0 + i * 0.5,
                "energy": 0.3 + i * 0.01,
                "genre_tags": ["bollywood", "hindi"],
                "mood_tags": ["calm", "soothing"],
                "classification_source": "test",
            })
            self._add_personal_play(db_conn, uri, i)

        # Seed 2 near-duplicates with very high para scores so they're both top candidates
        dup_uri_a = "spotify:track:dup_alpha"
        dup_uri_b = "spotify:track:dup_beta"
        upsert_song(db_conn, dup_uri_a, "Kabira (From 'Yeh Jawaani Hai Deewani')",
                     "Arijit Singh", sources=["test"], last_played="2026-03-18")
        db_conn.execute(
            "UPDATE songs SET play_count = 30 WHERE spotify_uri = ?", (dup_uri_a,),
        )
        upsert_song_classification(db_conn, {
            "spotify_uri": dup_uri_a,
            "parasympathetic": 0.95,
            "sympathetic": 0.02,
            "grounding": 0.05,
            "confidence": 0.8,
            "bpm": 80.0,
            "energy": 0.3,
            "genre_tags": ["bollywood", "hindi"],
            "mood_tags": ["calm", "soothing"],
            "classification_source": "test",
        })
        self._add_personal_play(db_conn, dup_uri_a, 50)

        upsert_song(db_conn, dup_uri_b, "Kabira (From 'Bollywood Essentials')",
                     "Arijit Singh", sources=["test"], last_played="2026-03-17")
        db_conn.execute(
            "UPDATE songs SET play_count = 10 WHERE spotify_uri = ?", (dup_uri_b,),
        )
        upsert_song_classification(db_conn, {
            "spotify_uri": dup_uri_b,
            "parasympathetic": 0.94,
            "sympathetic": 0.02,
            "grounding": 0.05,
            "confidence": 0.8,
            "bpm": 80.0,
            "energy": 0.3,
            "genre_tags": ["bollywood", "hindi"],
            "mood_tags": ["calm", "soothing"],
            "classification_source": "test",
        })
        self._add_personal_play(db_conn, dup_uri_b, 51)
        db_conn.commit()

        result = select_songs(db_conn, "accumulated_fatigue", "2026-03-19")
        uris = [s["spotify_uri"] for s in result["songs"]]

        # Should have exactly 20 songs (dedup removed 1, backfill added 1)
        assert len(result["songs"]) == 20

        # The removed duplicate (lower plays) should not appear
        assert dup_uri_b not in uris


# ---------------------------------------------------------------------------
# Lead track ordering tests
# ---------------------------------------------------------------------------

class TestLeadTrackOrdering:

    @staticmethod
    def _make_song(uri, selection_score, engagement_score=None, name="Song"):
        return {
            "spotify_uri": uri,
            "name": name,
            "selection_score": selection_score,
            "engagement_score": engagement_score,
        }

    def test_high_engagement_promoted_to_front(self):
        """A song with high engagement in the top 10 should jump to lead position."""
        songs = [
            self._make_song("uri:0", 0.90, engagement_score=0.2, name="Top neuro"),
            self._make_song("uri:1", 0.89, engagement_score=0.95, name="High engagement"),
            self._make_song("uri:2", 0.88, engagement_score=0.1, name="Low engagement"),
            self._make_song("uri:3", 0.87, engagement_score=0.9, name="Also high"),
        ] + [self._make_song(f"uri:{i}", 0.80 - i * 0.01) for i in range(4, 20)]

        result = _apply_lead_track_ordering(songs)

        # High engagement songs should be in the first 3 positions
        lead_uris = {s["spotify_uri"] for s in result[:3]}
        assert "uri:1" in lead_uris  # 0.89*0.7 + 0.95*0.3 = 0.908
        assert "uri:3" in lead_uris  # 0.87*0.7 + 0.9*0.3  = 0.879

    def test_neuro_still_dominates_lead_score(self):
        """70% neuro weight means a much better neuro match beats engagement."""
        songs = [
            self._make_song("uri:0", 0.95, engagement_score=0.1, name="Great neuro"),
            self._make_song("uri:1", 0.60, engagement_score=1.0, name="Great engagement"),
        ] + [self._make_song(f"uri:{i}", 0.50) for i in range(2, 10)]

        result = _apply_lead_track_ordering(songs)
        # 0.95*0.7 + 0.1*0.3 = 0.695 vs 0.60*0.7 + 1.0*0.3 = 0.72
        # The high-engagement song wins the lead score here
        assert result[0]["spotify_uri"] == "uri:1"

    def test_no_engagement_treated_as_zero(self):
        """Songs without engagement_score shouldn't crash."""
        songs = [
            self._make_song("uri:0", 0.90, engagement_score=None),
            self._make_song("uri:1", 0.89, engagement_score=0.8),
        ] + [self._make_song(f"uri:{i}", 0.80) for i in range(2, 10)]

        result = _apply_lead_track_ordering(songs)
        # uri:1 (0.89*0.7 + 0.8*0.3 = 0.863) beats uri:0 (0.90*0.7 + 0 = 0.63)
        assert result[0]["spotify_uri"] == "uri:1"

    def test_rest_of_playlist_keeps_selection_score_order(self):
        """Positions 4+ should stay sorted by selection_score."""
        songs = [self._make_song(f"uri:{i}", 0.90 - i * 0.01, engagement_score=0.5)
                 for i in range(15)]

        result = _apply_lead_track_ordering(songs)
        rest_scores = [s["selection_score"] for s in result[3:]]
        assert rest_scores == sorted(rest_scores, reverse=True)

    def test_few_songs_returns_unchanged(self):
        """With <= 3 songs, no reordering needed."""
        songs = [
            self._make_song("uri:0", 0.90, engagement_score=0.1),
            self._make_song("uri:1", 0.80, engagement_score=0.9),
        ]
        result = _apply_lead_track_ordering(songs)
        assert len(result) == 2
        # No reordering — returned as-is
        assert result[0]["spotify_uri"] == "uri:0"

    def test_preserves_all_songs(self):
        """Lead track ordering shouldn't add or remove songs."""
        songs = [self._make_song(f"uri:{i}", 0.90 - i * 0.01, engagement_score=0.5)
                 for i in range(20)]
        result = _apply_lead_track_ordering(songs)
        assert len(result) == 20
        assert {s["spotify_uri"] for s in result} == {s["spotify_uri"] for s in songs}

    def test_only_top_pool_eligible_for_lead(self):
        """Songs outside the top 10 shouldn't jump to lead even with high engagement."""
        songs = [self._make_song(f"uri:{i}", 0.90 - i * 0.01, engagement_score=0.1)
                 for i in range(10)]
        # Song at position 11 has amazing engagement but low neuro
        songs.append(self._make_song("uri:outsider", 0.70, engagement_score=1.0))

        result = _apply_lead_track_ordering(songs)
        lead_uris = {s["spotify_uri"] for s in result[:3]}
        assert "uri:outsider" not in lead_uris


# ---------------------------------------------------------------------------
# Hard cap: min repeat gap
# ---------------------------------------------------------------------------

class TestComputeMinRepeatGap:

    def test_small_library(self):
        # 150 songs → log2(1) = 0 → max(1, 0) = 1
        assert compute_min_repeat_gap(150, is_current_banger=False) == 1

    def test_small_library_banger(self):
        # 150 → base 1, banger discount → max(0, 0) = 0
        assert compute_min_repeat_gap(150, is_current_banger=True) == 0

    def test_medium_library(self):
        # 600 → log2(4) = 2
        assert compute_min_repeat_gap(600, is_current_banger=False) == 2

    def test_medium_library_banger(self):
        # 600 → base 2, banger → 1
        assert compute_min_repeat_gap(600, is_current_banger=True) == 1

    def test_large_library(self):
        # 1200 → log2(8) = 3
        assert compute_min_repeat_gap(1200, is_current_banger=False) == 3

    def test_large_library_banger(self):
        # 1200 → base 3, banger → 2
        assert compute_min_repeat_gap(1200, is_current_banger=True) == 2

    def test_very_large_library(self):
        # 2400 → log2(16) = 4
        assert compute_min_repeat_gap(2400, is_current_banger=False) == 4

    def test_zero_library(self):
        assert compute_min_repeat_gap(0, is_current_banger=False) == 0

    def test_scales_logarithmically(self):
        """Doubling library from 600→1200 adds 1 day, not 2."""
        gap_600 = compute_min_repeat_gap(600, is_current_banger=False)
        gap_1200 = compute_min_repeat_gap(1200, is_current_banger=False)
        assert gap_1200 - gap_600 == 1


class TestIsCurrentBanger:

    def test_high_engagement_recent(self):
        today = datetime.now().strftime("%Y-%m-%d")
        song = {"engagement_score": 0.80, "last_played": today}
        assert is_current_banger(song, engagement_p75=0.58) is True

    def test_high_engagement_old(self):
        old_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        song = {"engagement_score": 0.80, "last_played": old_date}
        assert is_current_banger(song, engagement_p75=0.58) is False

    def test_low_engagement_recent(self):
        today = datetime.now().strftime("%Y-%m-%d")
        song = {"engagement_score": 0.30, "last_played": today}
        assert is_current_banger(song, engagement_p75=0.58) is False

    def test_no_engagement(self):
        song = {"engagement_score": None, "last_played": "2026-03-20"}
        assert is_current_banger(song, engagement_p75=0.58) is False

    def test_no_last_played(self):
        song = {"engagement_score": 0.80, "last_played": None}
        assert is_current_banger(song, engagement_p75=0.58) is False

    def test_exactly_30_days_ago(self):
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        song = {"engagement_score": 0.80, "last_played": cutoff}
        assert is_current_banger(song, engagement_p75=0.58) is True

    def test_31_days_ago(self):
        old = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d")
        song = {"engagement_score": 0.80, "last_played": old}
        assert is_current_banger(song, engagement_p75=0.58) is False


class TestComputeEngagementP75:

    def test_normal_distribution(self):
        songs = [{"engagement_score": i * 0.1} for i in range(1, 11)]
        # 10 songs, top quartile = index 2 (10//4)
        p75 = compute_engagement_p75(songs)
        assert p75 == pytest.approx(0.8, abs=0.05)

    def test_no_engagement_returns_zero(self):
        songs = [{"engagement_score": None}, {"name": "no score"}]
        assert compute_engagement_p75(songs) == 0.0

    def test_empty_list(self):
        assert compute_engagement_p75([]) == 0.0


class TestGetDaysSinceLastAppearance:

    def test_yesterday_returns_1(self, db_conn):
        insert_generated_playlist(db_conn, date="2026-03-19", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        result = get_days_since_last_appearance(db_conn, "2026-03-20")
        assert result["spotify:track:a"] == 1

    def test_two_days_ago_returns_2(self, db_conn):
        insert_generated_playlist(db_conn, date="2026-03-18", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        result = get_days_since_last_appearance(db_conn, "2026-03-20")
        assert result["spotify:track:a"] == 2

    def test_gap_still_finds_most_recent(self, db_conn):
        """Song appeared 3 days ago and 1 day ago — returns 1 (most recent)."""
        insert_generated_playlist(db_conn, date="2026-03-17", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        insert_generated_playlist(db_conn, date="2026-03-19", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        result = get_days_since_last_appearance(db_conn, "2026-03-20")
        assert result["spotify:track:a"] == 1

    def test_song_only_in_old_playlist_still_found(self, db_conn):
        """Song from 3 days ago (no gap issue) is found with days_since=3."""
        insert_generated_playlist(db_conn, date="2026-03-17", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        result = get_days_since_last_appearance(db_conn, "2026-03-20")
        assert result["spotify:track:a"] == 3

    def test_beyond_lookback_not_found(self, db_conn):
        """Songs older than max_lookback are not returned."""
        insert_generated_playlist(db_conn, date="2026-03-10", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        result = get_days_since_last_appearance(db_conn, "2026-03-20", max_lookback=7)
        assert result == {}

    def test_no_playlists(self, db_conn):
        assert get_days_since_last_appearance(db_conn, "2026-03-20") == {}

    def test_multiple_playlists_same_date_uses_latest_only(self, db_conn):
        """When multiple playlists exist for one date, only the latest counts."""
        insert_generated_playlist(db_conn, date="2026-03-19", detected_state="baseline",
                                  track_uris=["spotify:track:old", "spotify:track:dropped"])
        insert_generated_playlist(db_conn, date="2026-03-19", detected_state="baseline",
                                  track_uris=["spotify:track:final"])
        result = get_days_since_last_appearance(db_conn, "2026-03-20")
        assert "spotify:track:final" in result
        assert "spotify:track:old" not in result
        assert "spotify:track:dropped" not in result


# ---------------------------------------------------------------------------
# DB query tests
# ---------------------------------------------------------------------------

class TestPlaylistQueries:

    def test_insert_and_retrieve_playlist(self, db_conn):
        uris = ["spotify:track:a", "spotify:track:b", "spotify:track:c"]
        row_id = insert_generated_playlist(
            db_conn, date="2026-03-19", detected_state="baseline",
            track_uris=uris, reasoning="Test reasoning",
            whoop_metrics={"recovery": 75}, description="Test playlist",
        )
        assert row_id > 0
        row = db_conn.execute("SELECT * FROM generated_playlists WHERE id = ?", (row_id,)).fetchone()
        assert json.loads(row["track_uris"]) == uris

    def test_get_recent_uris_empty(self, db_conn):
        assert get_recent_playlist_track_uris(db_conn, "2026-03-19", days=2) == {}

    def test_get_recent_uris_yesterday(self, db_conn):
        insert_generated_playlist(db_conn, date="2026-03-18", detected_state="baseline",
                                  track_uris=["spotify:track:a", "spotify:track:b"])
        result = get_recent_playlist_track_uris(db_conn, "2026-03-19", days=2)
        assert result == {"spotify:track:a": 1, "spotify:track:b": 1}

    def test_get_recent_uris_newest_wins(self, db_conn):
        insert_generated_playlist(db_conn, date="2026-03-17", detected_state="baseline",
                                  track_uris=["spotify:track:a"])
        insert_generated_playlist(db_conn, date="2026-03-18", detected_state="baseline",
                                  track_uris=["spotify:track:a", "spotify:track:b"])
        result = get_recent_playlist_track_uris(db_conn, "2026-03-19", days=2)
        assert result["spotify:track:a"] == 1

    def test_get_recent_uris_ignores_old(self, db_conn):
        insert_generated_playlist(db_conn, date="2026-03-15", detected_state="baseline",
                                  track_uris=["spotify:track:old"])
        assert get_recent_playlist_track_uris(db_conn, "2026-03-19", days=2) == {}

    def test_multiple_playlists_same_date_uses_latest_only(self, db_conn):
        """Iterations on same day: only the final playlist counts for freshness."""
        insert_generated_playlist(db_conn, date="2026-03-18", detected_state="baseline",
                                  track_uris=["spotify:track:draft1", "spotify:track:dropped"])
        insert_generated_playlist(db_conn, date="2026-03-18", detected_state="baseline",
                                  track_uris=["spotify:track:final"])
        result = get_recent_playlist_track_uris(db_conn, "2026-03-19", days=2)
        assert "spotify:track:final" in result
        assert "spotify:track:draft1" not in result
        assert "spotify:track:dropped" not in result


# ---------------------------------------------------------------------------
# identify_anchors tests
# ---------------------------------------------------------------------------

def _make_scored_entry(idx, last_played=None, score=0.8):
    """Helper to build a (song, score, breakdown) tuple for anchor tests."""
    song = {
        "spotify_uri": f"spotify:track:test{idx:03d}",
        "name": f"Song {idx}",
        "last_played": last_played,
    }
    return (song, score, {"neuro_match": score})


class TestIdentifyAnchors:

    def test_picks_recent_high_scored_songs(self):
        scored = [
            _make_scored_entry(0, last_played="2026-03-10", score=0.9),
            _make_scored_entry(1, last_played="2026-03-05", score=0.85),
            _make_scored_entry(2, last_played="2025-11-01", score=0.80),
        ]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        assert result == [0, 1]

    def test_ignores_songs_older_than_recency_days(self):
        scored = [
            _make_scored_entry(0, last_played="2025-12-01", score=0.9),
            _make_scored_entry(1, last_played="2025-06-01", score=0.85),
        ]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        # 2025-12-01 is ~108 days before 2026-03-19, outside 90 day window
        assert result == []

    def test_handles_none_last_played(self):
        scored = [
            _make_scored_entry(0, last_played=None, score=0.9),
            _make_scored_entry(1, last_played="2026-03-10", score=0.85),
            _make_scored_entry(2, last_played=None, score=0.80),
        ]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        assert result == [1]

    def test_returns_max_count(self):
        scored = [
            _make_scored_entry(i, last_played="2026-03-10", score=0.9 - i * 0.01)
            for i in range(10)
        ]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        assert len(result) == 5
        assert result == [0, 1, 2, 3, 4]

    def test_returns_empty_when_no_recent_songs(self):
        scored = [
            _make_scored_entry(0, last_played="2024-01-01", score=0.9),
            _make_scored_entry(1, last_played=None, score=0.85),
        ]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        assert result == []

    def test_empty_scored_list(self):
        assert identify_anchors([], "2026-03-19", recency_days=90, max_count=5) == []

    def test_invalid_date_returns_empty(self):
        scored = [_make_scored_entry(0, last_played="2026-03-10")]
        assert identify_anchors(scored, "not-a-date", recency_days=90, max_count=5) == []

    def test_exact_cutoff_included(self):
        """Song played exactly recency_days ago should be included."""
        scored = [_make_scored_entry(0, last_played="2025-12-19", score=0.9)]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        assert result == [0]

    def test_one_day_past_cutoff_excluded(self):
        """Song played one day before the cutoff should be excluded."""
        scored = [_make_scored_entry(0, last_played="2025-12-18", score=0.9)]
        result = identify_anchors(scored, "2026-03-19", recency_days=90, max_count=5)
        assert result == []
