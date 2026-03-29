"""Tests for matching/cohesion.py — playlist cohesion via seed-and-expand."""

import pytest

from config import COHESION_MIN_SIMILARITY
from matching.cohesion import (
    compute_bpm_similarity,
    compute_era_similarity,
    compute_neighborhood_density,
    compute_pairwise_similarity,
    compute_property_similarity,
    compute_tag_similarity,
    expand_cluster,
    select_cohesive_songs,
    select_seed,
)


# ---------------------------------------------------------------------------
# compute_tag_similarity
# ---------------------------------------------------------------------------

class TestTagSimilarity:

    def test_identical_tags(self):
        assert compute_tag_similarity(["rock", "indie"], ["rock", "indie"]) == 1.0

    def test_disjoint_tags(self):
        assert compute_tag_similarity(["rock"], ["jazz"]) == 0.0

    def test_partial_overlap(self):
        sim = compute_tag_similarity(["rock", "indie", "alternative"], ["rock", "pop"])
        assert sim == pytest.approx(1 / 4)  # 1 shared / 4 unique

    def test_empty_list_a(self):
        assert compute_tag_similarity([], ["rock"]) == 0.0

    def test_empty_list_b(self):
        assert compute_tag_similarity(["rock"], []) == 0.0

    def test_none_a(self):
        assert compute_tag_similarity(None, ["rock"]) == 0.0

    def test_none_b(self):
        assert compute_tag_similarity(["rock"], None) == 0.0

    def test_both_none(self):
        assert compute_tag_similarity(None, None) == 0.0

    def test_case_insensitive(self):
        assert compute_tag_similarity(["Rock", "INDIE"], ["rock", "indie"]) == 1.0

    def test_whitespace_stripped(self):
        assert compute_tag_similarity(["rock "], [" rock"]) == 1.0

    def test_single_shared_tag(self):
        sim = compute_tag_similarity(["rock", "indie"], ["rock", "jazz"])
        assert sim == pytest.approx(1 / 3)  # 1 shared / 3 unique


# ---------------------------------------------------------------------------
# compute_bpm_similarity
# ---------------------------------------------------------------------------

class TestBpmSimilarity:

    def test_identical_bpm(self):
        assert compute_bpm_similarity(120.0, 120.0) == 1.0

    def test_20_apart(self):
        sim = compute_bpm_similarity(120.0, 140.0)
        assert sim < 0.15  # e^(-400/200) = e^-2 ≈ 0.135

    def test_10_apart_moderate(self):
        sim = compute_bpm_similarity(120.0, 130.0)
        assert 0.55 < sim < 0.65  # e^(-100/200) = e^-0.5 ≈ 0.607

    def test_none_a(self):
        assert compute_bpm_similarity(None, 120.0) == 0.5

    def test_none_b(self):
        assert compute_bpm_similarity(120.0, None) == 0.5

    def test_both_none(self):
        assert compute_bpm_similarity(None, None) == 0.5

    def test_symmetric(self):
        assert compute_bpm_similarity(100.0, 120.0) == compute_bpm_similarity(120.0, 100.0)


# ---------------------------------------------------------------------------
# compute_property_similarity
# ---------------------------------------------------------------------------

class TestPropertySimilarity:

    def test_identical(self):
        assert compute_property_similarity(0.7, 0.7) == 1.0

    def test_distant(self):
        sim = compute_property_similarity(0.0, 1.0)
        assert sim < 0.01  # e^(-1/0.045) very small

    def test_close(self):
        sim = compute_property_similarity(0.5, 0.55)
        assert sim > 0.9

    def test_none_returns_neutral(self):
        assert compute_property_similarity(None, 0.5) == 0.5
        assert compute_property_similarity(0.5, None) == 0.5
        assert compute_property_similarity(None, None) == 0.5

    def test_symmetric(self):
        assert compute_property_similarity(0.3, 0.8) == compute_property_similarity(0.8, 0.3)


# ---------------------------------------------------------------------------
# compute_era_similarity
# ---------------------------------------------------------------------------

class TestEraSimilarity:

    def test_same_year_returns_one(self):
        assert compute_era_similarity(2020, 2020, ["rock"], ["rock"]) == 1.0

    def test_none_year_returns_neutral(self):
        assert compute_era_similarity(None, 2020, ["rock"], ["rock"]) == 0.5
        assert compute_era_similarity(2020, None, ["rock"], ["rock"]) == 0.5
        assert compute_era_similarity(None, None, ["rock"], ["rock"]) == 0.5

    def test_hip_hop_tight_sigma(self):
        """20 years apart with hip-hop sigma=2 should be near zero."""
        sim = compute_era_similarity(2003, 2023, ["hip-hop"], ["hip-hop"])
        assert sim < 0.01

    def test_ghazal_wide_sigma(self):
        """20 years apart with ghazal sigma=12 should still be moderate."""
        sim = compute_era_similarity(2003, 2023, ["ghazal"], ["ghazal"])
        assert sim > 0.15

    def test_hip_hop_tighter_than_ghazal(self):
        """Same year gap, hip-hop should decay faster than ghazal."""
        sim_hiphop = compute_era_similarity(2010, 2020, ["hip-hop"], ["hip-hop"])
        sim_ghazal = compute_era_similarity(2010, 2020, ["ghazal"], ["ghazal"])
        assert sim_ghazal > sim_hiphop

    def test_uses_larger_sigma_of_two_songs(self):
        """When genres differ, the more permissive sigma wins."""
        sim_mixed = compute_era_similarity(2010, 2020, ["hip-hop"], ["ghazal"])
        sim_tight = compute_era_similarity(2010, 2020, ["hip-hop"], ["hip-hop"])
        assert sim_mixed > sim_tight

    def test_symmetric(self):
        sim_ab = compute_era_similarity(2010, 2020, ["rock"], ["bollywood"])
        sim_ba = compute_era_similarity(2020, 2010, ["bollywood"], ["rock"])
        assert sim_ab == pytest.approx(sim_ba)

    def test_no_genre_tags_uses_default(self):
        """No genre tags falls back to ERA_SIGMA_DEFAULT=5."""
        sim = compute_era_similarity(2015, 2020, None, None)
        assert 0.3 < sim < 0.7  # 5 years apart with sigma=5 → ~0.607


# ---------------------------------------------------------------------------
# compute_pairwise_similarity
# ---------------------------------------------------------------------------

class TestPairwiseSimilarity:

    def test_same_song_high(self):
        song = {
            "genre_tags": ["rock", "indie"],
            "mood_tags": ["energetic", "uplifting"],
            "bpm": 120.0, "energy": 0.8, "acousticness": 0.2,
            "danceability": 0.7, "valence": 0.6,
            "release_year": 2020,
        }
        sim = compute_pairwise_similarity(song, song)
        # Tags=1.0, BPM=1.0, release_year=1.0, properties=1.0 → weighted sum = 1.0
        assert sim == pytest.approx(1.0, abs=0.01)

    def test_completely_different_low(self):
        song_a = {
            "genre_tags": ["bollywood"], "mood_tags": ["calm"],
            "bpm": 70.0, "energy": 0.2, "acousticness": 0.9,
            "danceability": 0.1, "valence": 0.2,
        }
        song_b = {
            "genre_tags": ["hip-hop"], "mood_tags": ["aggressive"],
            "bpm": 150.0, "energy": 0.95, "acousticness": 0.05,
            "danceability": 0.9, "valence": 0.9,
        }
        sim = compute_pairwise_similarity(song_a, song_b)
        assert sim < 0.15

    def test_same_genre_higher_than_cross_genre(self):
        base = {
            "mood_tags": ["energetic"], "bpm": 120.0,
            "energy": 0.7, "acousticness": 0.3, "danceability": 0.6, "valence": 0.5,
        }
        same = {**base, "genre_tags": ["rock", "indie"]}
        other = {**base, "genre_tags": ["jazz", "fusion"]}
        target = {**base, "genre_tags": ["rock", "alternative"]}

        sim_same = compute_pairwise_similarity(same, target)
        sim_cross = compute_pairwise_similarity(other, target)
        assert sim_same > sim_cross

    def test_missing_all_tags(self):
        song_a = {"bpm": 120.0, "energy": 0.7}
        song_b = {"bpm": 120.0, "energy": 0.7}
        sim = compute_pairwise_similarity(song_a, song_b)
        # genre_tags=0, mood_tags=0, bpm=1.0, release_year=0.5(None),
        # energy=1.0 (0.5*energy_sim+0.5*opening_sim, both 1.0), acousticness=0.5, dance=0.5, valence=0.5
        # 0*0.30 + 0*0.15 + 1.0*0.15 + 0.5*0.20 + 1.0*0.10 + 0.5*0.05 + 0.5*0.05 + 0.5*0.00
        # = 0.15 + 0.10 + 0.10 + 0.025 + 0.025 = 0.40
        assert sim == pytest.approx(0.40, abs=0.01)


# ---------------------------------------------------------------------------
# compute_neighborhood_density
# ---------------------------------------------------------------------------

class TestNeighborhoodDensity:

    def test_single_song(self):
        assert compute_neighborhood_density(0, [[1.0]]) == 0.0

    def test_uniform_similarity(self):
        # 3 songs, all 0.5 similar to each other
        matrix = [[1.0, 0.5, 0.5], [0.5, 1.0, 0.5], [0.5, 0.5, 1.0]]
        assert compute_neighborhood_density(0, matrix) == pytest.approx(0.5)

    def test_isolated_vs_connected(self):
        # Song 0 similar to 1,2; Song 3 isolated
        matrix = [
            [1.0, 0.8, 0.7, 0.1],
            [0.8, 1.0, 0.6, 0.1],
            [0.7, 0.6, 1.0, 0.1],
            [0.1, 0.1, 0.1, 1.0],
        ]
        assert compute_neighborhood_density(0, matrix) > compute_neighborhood_density(3, matrix)


# ---------------------------------------------------------------------------
# select_seed
# ---------------------------------------------------------------------------

class TestSelectSeed:

    def test_prefers_dense_neighborhood(self):
        # Song 0: high neuro, isolated. Song 1: medium neuro, dense.
        neuro = [0.95, 0.80]
        matrix = [
            [1.0, 0.1],
            [0.1, 1.0],
        ]
        # With only 2 songs, density = similarity to the other one.
        # Song 0: 0.95 * 0.1 = 0.095. Song 1: 0.80 * 0.1 = 0.080
        # In this 2-song case, neuro dominates. Need more songs.
        # Let's do a 4-song case:
        neuro = [0.95, 0.70, 0.60, 0.55]
        matrix = [
            [1.0, 0.1, 0.1, 0.1],  # song 0: isolated
            [0.1, 1.0, 0.8, 0.7],  # song 1: dense cluster
            [0.1, 0.8, 1.0, 0.9],  # song 2: dense cluster
            [0.1, 0.7, 0.9, 1.0],  # song 3: dense cluster
        ]
        # Song 0: 0.95 * avg(0.1,0.1,0.1) = 0.95 * 0.1 = 0.095
        # Song 1: 0.70 * avg(0.1,0.8,0.7) = 0.70 * 0.533 = 0.373
        seed = select_seed(neuro, matrix)
        assert seed == 1  # Dense neighborhood wins despite lower neuro score

    def test_single_song(self):
        assert select_seed([0.9], [[1.0]]) == 0


# ---------------------------------------------------------------------------
# expand_cluster
# ---------------------------------------------------------------------------

class TestExpandCluster:

    def test_adds_most_similar_first(self):
        # 4 songs. Seed=0. Song 1 is most similar to 0.
        matrix = [
            [1.0, 0.9, 0.3, 0.1],
            [0.9, 1.0, 0.3, 0.1],
            [0.3, 0.3, 1.0, 0.2],
            [0.1, 0.1, 0.2, 1.0],
        ]
        selected = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=3, min_similarity=0.0)
        assert selected[0] == 0
        assert selected[1] == 1  # Most similar to seed

    def test_stops_at_target_size(self):
        matrix = [[1.0, 0.9, 0.8], [0.9, 1.0, 0.7], [0.8, 0.7, 1.0]]
        selected = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=2, min_similarity=0.0)
        assert len(selected) == 2

    def test_stops_below_min_similarity(self):
        matrix = [
            [1.0, 0.8, 0.05],
            [0.8, 1.0, 0.05],
            [0.05, 0.05, 1.0],
        ]
        selected = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=3, min_similarity=0.1)
        assert len(selected) == 2  # Song 2 is too dissimilar
        assert 2 not in selected

    def test_single_song_returns_seed(self):
        selected = expand_cluster(seed_idx=0, sim_matrix=[[1.0]], target_size=5, min_similarity=0.0)
        assert selected == [0]


# ---------------------------------------------------------------------------
# select_cohesive_songs (integration)
# ---------------------------------------------------------------------------

def _make_candidate(
    idx: int,
    neuro_score: float = 0.7,
    genre_tags: list[str] | None = None,
    mood_tags: list[str] | None = None,
    bpm: float | None = 120.0,
    energy: float | None = 0.7,
    acousticness: float | None = 0.3,
    danceability: float | None = 0.6,
    valence: float | None = 0.5,
) -> tuple[dict, float, dict]:
    song = {
        "spotify_uri": f"spotify:track:test{idx:03d}",
        "name": f"Song {idx}",
        "artist": f"Artist {idx}",
        "genre_tags": genre_tags,
        "mood_tags": mood_tags,
        "bpm": bpm,
        "energy": energy,
        "acousticness": acousticness,
        "danceability": danceability,
        "valence": valence,
    }
    breakdown = {"neuro_match": neuro_score, "confidence_mult": 1.0}
    return (song, neuro_score, breakdown)


class TestSelectCohesiveSongs:

    def test_returns_target_size(self):
        # 40 bollywood songs — should cluster easily
        candidates = [
            _make_candidate(
                i, neuro_score=0.8 - i * 0.005,
                genre_tags=["bollywood", "hindi"],
                mood_tags=["energetic", "uplifting"],
                bpm=120.0 + i * 0.5,
            )
            for i in range(40)
        ]
        selected, stats = select_cohesive_songs(candidates, pool_size=40, target_size=20)
        assert len(selected) == 20

    def test_returns_all_when_pool_smaller_than_target(self):
        candidates = [_make_candidate(i) for i in range(5)]
        selected, stats = select_cohesive_songs(candidates, pool_size=10, target_size=20)
        assert len(selected) == 5

    def test_empty_candidates(self):
        selected, stats = select_cohesive_songs([])
        assert selected == []
        assert stats["pool_size"] == 0

    def test_stats_complete(self):
        candidates = [
            _make_candidate(
                i, genre_tags=["rock"], mood_tags=["energetic"], bpm=120.0,
            )
            for i in range(30)
        ]
        _, stats = select_cohesive_songs(candidates, pool_size=30, target_size=15)
        assert "pool_size" in stats
        assert "seed_idx" in stats
        assert "mean_similarity" in stats
        assert "dominant_genre" in stats
        assert "relaxations" in stats
        assert "min_similarity_used" in stats

    def test_cluster_tighter_than_random(self):
        # Create 20 rock songs + 20 jazz songs + 20 bollywood songs
        candidates = []
        for i in range(20):
            candidates.append(_make_candidate(
                i, neuro_score=0.8, genre_tags=["rock", "indie"],
                mood_tags=["energetic"], bpm=130.0 + i,
            ))
        for i in range(20, 40):
            candidates.append(_make_candidate(
                i, neuro_score=0.75, genre_tags=["jazz", "fusion"],
                mood_tags=["calm", "smooth"], bpm=90.0 + (i - 20),
            ))
        for i in range(40, 60):
            candidates.append(_make_candidate(
                i, neuro_score=0.7, genre_tags=["bollywood", "hindi"],
                mood_tags=["romantic", "nostalgic"], bpm=110.0 + (i - 40),
            ))

        selected, stats = select_cohesive_songs(candidates, pool_size=60, target_size=15)

        # Selected songs should mostly be from one genre cluster
        selected_genres = set()
        for idx in selected:
            tags = candidates[idx][0].get("genre_tags", [])
            for t in tags:
                selected_genres.add(t)

        # Should not span all three genre worlds
        all_genre_sets = [{"rock", "indie"}, {"jazz", "fusion"}, {"bollywood", "hindi"}]
        represented = sum(1 for gs in all_genre_sets if gs & selected_genres)
        assert represented <= 2  # At most 2 genre worlds, not all 3

    def test_relaxation_triggers_when_too_few(self):
        # Create diverse candidates that struggle to cluster
        candidates = []
        for i in range(30):
            candidates.append(_make_candidate(
                i, neuro_score=0.8 - i * 0.005,
                genre_tags=[f"genre_{i}"],  # All unique genres = low similarity
                mood_tags=[f"mood_{i}"],
                bpm=60.0 + i * 3,
            ))
        selected, stats = select_cohesive_songs(
            candidates, pool_size=30, target_size=20, min_size=15,
        )
        # Should have attempted relaxation
        assert stats["min_similarity_used"] <= COHESION_MIN_SIMILARITY

    def test_dominant_genre_in_stats(self):
        candidates = [
            _make_candidate(
                i, genre_tags=["bollywood", "hindi"],
                mood_tags=["energetic"],
            )
            for i in range(25)
        ]
        _, stats = select_cohesive_songs(candidates, pool_size=25, target_size=15)
        assert stats["dominant_genre"] in ("bollywood", "hindi")

    def test_anchor_count_in_stats(self):
        """anchor_count should appear in stats even without anchors."""
        candidates = [
            _make_candidate(
                i, genre_tags=["rock"], mood_tags=["energetic"], bpm=120.0,
            )
            for i in range(30)
        ]
        _, stats = select_cohesive_songs(candidates, pool_size=30, target_size=15)
        assert "anchor_count" in stats
        assert stats["anchor_count"] == 0


# ---------------------------------------------------------------------------
# Anchor-aware cohesion tests
# ---------------------------------------------------------------------------

class TestExpandClusterPreSelected:

    def test_pre_selected_guaranteed_in_result(self):
        """Pre-selected indices must appear in the expanded cluster."""
        matrix = [
            [1.0, 0.9, 0.3, 0.1, 0.1],
            [0.9, 1.0, 0.3, 0.1, 0.1],
            [0.3, 0.3, 1.0, 0.8, 0.7],
            [0.1, 0.1, 0.8, 1.0, 0.9],
            [0.1, 0.1, 0.7, 0.9, 1.0],
        ]
        # Seed=0, pre_selected=[3] — song 3 is dissimilar to seed but forced in
        selected = expand_cluster(
            seed_idx=0, sim_matrix=matrix, target_size=4,
            min_similarity=0.0, pre_selected=[3],
        )
        assert 0 in selected
        assert 3 in selected

    def test_pre_selected_no_duplicate_with_seed(self):
        """If seed is in pre_selected, it shouldn't appear twice."""
        matrix = [[1.0, 0.9, 0.3], [0.9, 1.0, 0.3], [0.3, 0.3, 1.0]]
        selected = expand_cluster(
            seed_idx=0, sim_matrix=matrix, target_size=3,
            min_similarity=0.0, pre_selected=[0, 1],
        )
        # No duplicates
        assert len(selected) == len(set(selected))
        assert 0 in selected
        assert 1 in selected

    def test_none_pre_selected_unchanged_behavior(self):
        """Without pre_selected, behavior is identical to before."""
        matrix = [
            [1.0, 0.9, 0.3, 0.1],
            [0.9, 1.0, 0.3, 0.1],
            [0.3, 0.3, 1.0, 0.2],
            [0.1, 0.1, 0.2, 1.0],
        ]
        without = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=3, min_similarity=0.0)
        with_none = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=3,
                                   min_similarity=0.0, pre_selected=None)
        assert without == with_none

    def test_empty_pre_selected_unchanged_behavior(self):
        """Empty pre_selected list = same as None."""
        matrix = [[1.0, 0.9], [0.9, 1.0]]
        without = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=2, min_similarity=0.0)
        with_empty = expand_cluster(seed_idx=0, sim_matrix=matrix, target_size=2,
                                    min_similarity=0.0, pre_selected=[])
        assert without == with_empty


class TestCohesionWithAnchors:

    def test_anchors_guaranteed_in_result(self):
        """Anchor songs within pool must appear in the selected indices."""
        # 40 similar rock songs
        candidates = [
            _make_candidate(
                i, neuro_score=0.8 - i * 0.005,
                genre_tags=["rock", "indie"],
                mood_tags=["energetic", "uplifting"],
                bpm=120.0 + i * 0.5,
            )
            for i in range(40)
        ]
        # Anchor indices 10, 15 — within pool but not necessarily at top
        selected, stats = select_cohesive_songs(
            candidates, pool_size=40, target_size=20,
            anchor_indices=[10, 15],
        )
        assert 10 in selected
        assert 15 in selected
        assert stats["anchor_count"] == 2

    def test_no_anchors_existing_behavior_unchanged(self):
        """Without anchor_indices, result should match previous behavior."""
        candidates = [
            _make_candidate(
                i, neuro_score=0.8 - i * 0.005,
                genre_tags=["bollywood", "hindi"],
                mood_tags=["energetic", "uplifting"],
                bpm=120.0 + i * 0.5,
            )
            for i in range(40)
        ]
        selected_none, stats_none = select_cohesive_songs(
            candidates, pool_size=40, target_size=20, anchor_indices=None,
        )
        selected_default, stats_default = select_cohesive_songs(
            candidates, pool_size=40, target_size=20,
        )
        assert selected_none == selected_default
        assert stats_none["anchor_count"] == 0
        assert stats_default["anchor_count"] == 0

    def test_anchor_outside_pool_still_included(self):
        """Anchor at index beyond pool_size should be brought into the pool."""
        # 30 rock songs in pool, anchor at index 25 (within pool)
        # and anchor at index 35 (outside pool_size=30)
        candidates = [
            _make_candidate(
                i, neuro_score=0.8 - i * 0.005,
                genre_tags=["rock", "indie"],
                mood_tags=["energetic", "uplifting"],
                bpm=120.0 + i * 0.5,
            )
            for i in range(40)
        ]
        selected, stats = select_cohesive_songs(
            candidates, pool_size=30, target_size=20,
            anchor_indices=[5, 35],
        )
        # Index 5 is within pool — should be in result
        assert 5 in selected
        # Index 35 is outside pool — should have been brought in and appear in result
        assert 35 in selected
        assert stats["anchor_count"] == 2

    def test_anchor_count_zero_without_anchors(self):
        candidates = [_make_candidate(i) for i in range(25)]
        _, stats = select_cohesive_songs(candidates, pool_size=25, target_size=15)
        assert stats["anchor_count"] == 0
