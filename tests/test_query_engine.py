"""Tests for matching/query_engine.py — neuro-score song scoring and selection."""

import json

import pytest

from db.queries import (
    get_recent_playlist_track_uris,
    insert_generated_playlist,
    upsert_song,
    upsert_song_classification,
)
from matching.query_engine import (
    _dedup_near_duplicates,
    _normalize_title,
    compute_confidence_multiplier,
    compute_neuro_match,
    compute_selection_scores,
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
        assert bd["freshness_nudge"] == pytest.approx(0.02)
        assert score_nudged == pytest.approx(score_clean - 0.02, abs=0.001)

    def test_freshness_nudge_for_two_days_ago(self):
        profile = {"para": 0.85, "symp": 0.00, "grnd": 0.15}
        song = self._make_song("uri:1", para=0.8)
        _, bd = score_song(song, profile, {"uri:1": 2})
        assert bd["freshness_nudge"] == pytest.approx(0.01)

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
