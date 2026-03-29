"""Playlist cohesion: seed-and-expand selection for sonic coherence.

After neurological scoring produces a pool of candidates, this module
selects a cohesive subset that sounds like it belongs in the same room.
Uses pairwise similarity across genre, mood, BPM, and production properties.
"""

import logging
import math
from typing import Any

from config import (
    BPM_HARD_CAP_SIMILARITY,
    BPM_HARD_CAP_THRESHOLD,
    COHESION_BPM_SIGMA,
    COHESION_MIN_SIMILARITY,
    COHESION_POOL_SIZE,
    COHESION_PROPERTY_SIGMA,
    VIBE_HARD_CAP_SIMILARITY,
    VIBE_SIM_FLOOR,
    COHESION_RELAXATION_MAX,
    COHESION_RELAXATION_STEP,
    COHESION_WEIGHTS,
    ERA_HARD_CAP_SIMILARITY,
    ERA_SIGMA_BY_GENRE,
    ERA_SIGMA_DEFAULT,
    ERA_SIM_FLOOR,
    MAX_PLAYLIST_SIZE,
    MIN_PLAYLIST_SIZE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Similarity primitives
# ---------------------------------------------------------------------------

def compute_tag_similarity(
    tags_a: list[str] | None,
    tags_b: list[str] | None,
    idf: dict[str, float] | None = None,
) -> float:
    """IDF-weighted tag similarity (falls back to Jaccard when no IDF provided).

    With IDF: sum(idf[shared]) / sum(idf[union]). Rare tags contribute more.
    Without IDF: plain Jaccard (len(intersection) / len(union)).
    None or empty = 0.0 (no signal means we can't assume similar).
    """
    if not tags_a or not tags_b:
        return 0.0
    set_a = set(t.lower().strip() for t in tags_a)
    set_b = set(t.lower().strip() for t in tags_b)
    if not set_a or not set_b:
        return 0.0
    shared = set_a & set_b
    union = set_a | set_b
    if idf is None:
        return len(shared) / len(union)
    shared_weight = sum(idf.get(t, 1.0) for t in shared)
    union_weight = sum(idf.get(t, 1.0) for t in union)
    if union_weight == 0.0:
        return 0.0
    return shared_weight / union_weight


def compute_bpm_similarity(bpm_a: float | None, bpm_b: float | None) -> float:
    """Gaussian decay similarity for BPM. sigma=COHESION_BPM_SIGMA.

    None = 0.5 (neutral — don't penalize or reward missing data).
    """
    if bpm_a is None or bpm_b is None:
        return 0.5
    diff = bpm_a - bpm_b
    return math.exp(-(diff ** 2) / (2 * COHESION_BPM_SIGMA ** 2))


def compute_property_similarity(val_a: float | None, val_b: float | None) -> float:
    """Gaussian decay similarity for a 0-1 property. sigma=COHESION_PROPERTY_SIGMA.

    None = 0.5 (neutral).
    """
    if val_a is None or val_b is None:
        return 0.5
    diff = val_a - val_b
    return math.exp(-(diff ** 2) / (2 * COHESION_PROPERTY_SIGMA ** 2))


def _resolve_era_sigma(genre_tags: list[str] | None) -> float:
    """Find the best era sigma for a song's genre tags.

    Returns the minimum sigma across all recognized genre tags
    (most specific genre wins). Falls back to ERA_SIGMA_DEFAULT.
    """
    if not genre_tags:
        return ERA_SIGMA_DEFAULT
    sigmas = [ERA_SIGMA_BY_GENRE[t.lower().strip()]
              for t in genre_tags if t.lower().strip() in ERA_SIGMA_BY_GENRE]
    return min(sigmas) if sigmas else ERA_SIGMA_DEFAULT


def compute_era_similarity(
    year_a: int | None,
    year_b: int | None,
    genre_tags_a: list[str] | None,
    genre_tags_b: list[str] | None,
) -> float:
    """Genre-aware Gaussian decay on release year difference.

    Sigma varies by genre: hip-hop sigma=2 (tight), ghazal sigma=12 (loose).
    Uses the LARGER sigma of the two songs (more permissive wins).
    None year = 0.5 (neutral — don't penalize or reward missing data).
    """
    if year_a is None or year_b is None:
        return 0.5
    sigma_a = _resolve_era_sigma(genre_tags_a)
    sigma_b = _resolve_era_sigma(genre_tags_b)
    sigma = max(sigma_a, sigma_b)
    diff = year_a - year_b
    return math.exp(-(diff ** 2) / (2 * sigma ** 2))


def compute_pairwise_similarity(
    song_a: dict[str, Any],
    song_b: dict[str, Any],
    genre_idf: dict[str, float] | None = None,
) -> float:
    """Weighted similarity between two songs across all cohesion dimensions.

    Returns 0.0-1.0. Uses COHESION_WEIGHTS for dimension weighting.
    Hard caps: era, vibe, and BPM gaps override all other similarity —
    certain mismatches are too jarring for any other dimension to compensate.
    """
    w = COHESION_WEIGHTS
    score = 0.0

    score += w["genre_tags"] * compute_tag_similarity(
        song_a.get("genre_tags"), song_b.get("genre_tags"), idf=genre_idf)
    score += w["mood_tags"] * compute_tag_similarity(
        song_a.get("mood_tags"), song_b.get("mood_tags"))

    bpm_sim = compute_bpm_similarity(
        song_a.get("bpm"), song_b.get("bpm"))
    score += w["bpm"] * bpm_sim

    year_a = song_a.get("original_release_year") or song_a.get("release_year")
    year_b = song_b.get("original_release_year") or song_b.get("release_year")
    era_sim = compute_era_similarity(
        year_a, year_b,
        song_a.get("genre_tags"), song_b.get("genre_tags"))
    score += w["release_year"] * era_sim

    # Energy: blend overall energy with opening energy (intro feel matters for transitions)
    energy_sim = compute_property_similarity(
        song_a.get("energy"), song_b.get("energy"))
    opening_sim = compute_property_similarity(
        song_a.get("opening_energy") or song_a.get("energy"),
        song_b.get("opening_energy") or song_b.get("energy"))
    score += w["energy"] * (0.5 * energy_sim + 0.5 * opening_sim)

    acoustic_sim = compute_property_similarity(
        song_a.get("acousticness"), song_b.get("acousticness"))
    score += w["acousticness"] * acoustic_sim
    dance_sim = compute_property_similarity(
        song_a.get("danceability"), song_b.get("danceability"))
    score += w["danceability"] * dance_sim
    score += w["valence"] * compute_property_similarity(
        song_a.get("valence"), song_b.get("valence"))

    # Hard cap: production era gaps override all other similarity
    if era_sim < ERA_SIM_FLOOR:
        score = min(score, ERA_HARD_CAP_SIMILARITY)

    # Hard cap: vibe gaps (energy + opening + acousticness + danceability) override similarity.
    # A party banger next to an acoustic ballad is jarring regardless of BPM/genre match.
    avg_vibe_sim = (energy_sim + opening_sim + acoustic_sim + dance_sim) / 4.0
    if avg_vibe_sim < VIBE_SIM_FLOOR:
        score = min(score, VIBE_HARD_CAP_SIMILARITY)

    # Hard cap: BPM gaps — wildly different tempos don't belong together
    if bpm_sim < BPM_HARD_CAP_THRESHOLD:
        score = min(score, BPM_HARD_CAP_SIMILARITY)

    return score


# ---------------------------------------------------------------------------
# Seed-and-expand
# ---------------------------------------------------------------------------

def compute_neighborhood_density(idx: int, sim_matrix: list[list[float]]) -> float:
    """Average similarity of song at idx to all other songs in the matrix."""
    row = sim_matrix[idx]
    n = len(row)
    if n <= 1:
        return 0.0
    total = sum(row[j] for j in range(n) if j != idx)
    return total / (n - 1)


def select_seed(
    neuro_scores: list[float],
    sim_matrix: list[list[float]],
) -> int:
    """Pick the seed: argmax(neuro_score * neighborhood_density).

    A song must be both neurologically correct AND have many similar neighbors.
    """
    best_idx = 0
    best_val = -1.0
    for i in range(len(neuro_scores)):
        density = compute_neighborhood_density(i, sim_matrix)
        val = neuro_scores[i] * density
        if val > best_val:
            best_val = val
            best_idx = i
    return best_idx


def expand_cluster(
    seed_idx: int,
    sim_matrix: list[list[float]],
    target_size: int,
    min_similarity: float,
    pre_selected: list[int] | None = None,
) -> list[int]:
    """Greedily expand from seed, adding the most similar candidate each step.

    At each step, picks the candidate with highest average similarity to all
    songs already in the cluster. Stops at target_size or when no candidate
    exceeds min_similarity.

    If pre_selected is provided, those indices are guaranteed in the cluster
    from the start (after the seed).
    """
    n = len(sim_matrix)
    if pre_selected:
        selected = [seed_idx] + [i for i in pre_selected if i != seed_idx]
    else:
        selected = [seed_idx]
    remaining = set(range(n)) - set(selected)

    while len(selected) < target_size and remaining:
        best_idx = -1
        best_avg_sim = -1.0

        for candidate in remaining:
            avg_sim = sum(sim_matrix[candidate][s] for s in selected) / len(selected)
            if avg_sim > best_avg_sim:
                best_avg_sim = avg_sim
                best_idx = candidate

        if best_avg_sim < min_similarity:
            break

        selected.append(best_idx)
        remaining.discard(best_idx)

    return selected


def select_cohesive_songs(
    scored_candidates: list[tuple[dict[str, Any], float, dict[str, float]]],
    pool_size: int = COHESION_POOL_SIZE,
    target_size: int = MAX_PLAYLIST_SIZE,
    min_size: int = MIN_PLAYLIST_SIZE,
    anchor_indices: list[int] | None = None,
) -> tuple[list[int], dict[str, Any]]:
    """Select a cohesive subset from scored candidates.

    Args:
        scored_candidates: List of (song, selection_score, breakdown) sorted by score desc.
        pool_size: How many top candidates to consider for cohesion.
        target_size: Desired playlist size.
        min_size: Minimum acceptable playlist size (triggers relaxation).
        anchor_indices: Indices into scored_candidates that must appear in the result.
            Anchors outside the pool are appended to it.

    Returns:
        (selected_indices, stats) where indices refer to positions in scored_candidates.
        Stats include pool_size, seed info, similarity metrics, relaxation info.
    """
    # Take top pool_size candidates (all neurologically correct)
    pool = scored_candidates[:pool_size]
    n = len(pool)

    # pool_to_scored maps pool index → scored_candidates index.
    # For the first pool_size entries, pool index == scored index.
    pool_to_scored: dict[int, int] = {}

    # Bring anchor songs into the pool if they fall outside it
    anchor_pool_indices: list[int] | None = None
    if anchor_indices:
        anchor_pool_indices = []
        for ai in anchor_indices:
            if ai < n:
                anchor_pool_indices.append(ai)
            elif ai < len(scored_candidates):
                # Append to pool so cohesion can see it
                pool.append(scored_candidates[ai])
                pool_idx = len(pool) - 1
                pool_to_scored[pool_idx] = ai
                anchor_pool_indices.append(pool_idx)
        n = len(pool)

    def _remap(pool_indices: list[int]) -> list[int]:
        """Convert pool indices back to scored_candidates indices."""
        return [pool_to_scored.get(i, i) for i in pool_indices]

    if n == 0:
        return [], {"pool_size": 0, "seed_idx": -1, "relaxations": 0,
                    "mean_similarity": 0.0, "min_similarity_used": COHESION_MIN_SIMILARITY,
                    "anchor_count": 0}

    if n <= target_size:
        # Fewer candidates than target — take all, no cohesion filtering needed
        indices = _remap(list(range(n)))
        return indices, {
            "pool_size": n, "seed_idx": 0, "relaxations": 0,
            "mean_similarity": 0.0, "min_similarity_used": 0.0,
            "anchor_count": len(anchor_pool_indices) if anchor_pool_indices else 0,
        }

    # Build pairwise similarity matrix
    songs = [entry[0] for entry in pool]
    neuro_scores = [entry[1] for entry in pool]

    # Compute genre tag IDF across all candidate songs in the pool.
    # Rare genres get higher weight — "qawwali" shared is more meaningful than "pop" shared.
    genre_tag_counts: dict[str, int] = {}
    for song in songs:
        for tag in (song.get("genre_tags") or []):
            t = tag.lower().strip()
            genre_tag_counts[t] = genre_tag_counts.get(t, 0) + 1
    genre_idf: dict[str, float] = {
        tag: math.log(n / count) for tag, count in genre_tag_counts.items()
    } if genre_tag_counts else {}

    sim_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim_matrix[i][i] = 1.0
        for j in range(i + 1, n):
            sim = compute_pairwise_similarity(songs[i], songs[j], genre_idf=genre_idf)
            sim_matrix[i][j] = sim
            sim_matrix[j][i] = sim

    # Seed: best neuro_score * neighborhood_density
    seed_idx = select_seed(neuro_scores, sim_matrix)

    # Expand with progressive relaxation if needed
    min_sim = COHESION_MIN_SIMILARITY
    relaxations = 0

    selected = expand_cluster(
        seed_idx, sim_matrix, target_size, min_sim,
        pre_selected=anchor_pool_indices,
    )

    while len(selected) < min_size and relaxations < COHESION_RELAXATION_MAX:
        relaxations += 1
        min_sim -= COHESION_RELAXATION_STEP
        min_sim = max(min_sim, 0.0)
        selected = expand_cluster(
            seed_idx, sim_matrix, target_size, min_sim,
            pre_selected=anchor_pool_indices,
        )
        logger.info(
            "Cohesion relaxation %d: min_similarity=%.3f, got %d songs",
            relaxations, min_sim, len(selected),
        )

    # Drop anchors that are multi-dimensional vibe outliers.
    # An anchor whose energy, acousticness, or danceability is >1.5 SD from the
    # cluster mean on 2+ dimensions sounds wrong even if genre/BPM/era match.
    from config import ANCHOR_VIBE_OUTLIER_MIN_DIMS, ANCHOR_VIBE_OUTLIER_SD

    if anchor_pool_indices and len(selected) > min_size:
        # Compute cluster vibe stats (mean + SD for energy, acousticness, danceability)
        non_anchor = [s for s in selected if s not in set(anchor_pool_indices)]
        if len(non_anchor) < 3:
            non_anchor = selected  # fallback if too few non-anchors

        import statistics
        vibe_dims = ["energy", "acousticness", "danceability"]
        cluster_stats: dict[str, dict[str, float]] = {}
        for dim in vibe_dims:
            vals = [songs[i].get(dim) for i in non_anchor if songs[i].get(dim) is not None]
            if len(vals) >= 2:
                cluster_stats[dim] = {"mean": statistics.mean(vals), "sd": statistics.stdev(vals)}

        dropped = []
        for ai in anchor_pool_indices:
            if ai not in selected:
                continue
            outlier_dims = 0
            for dim in vibe_dims:
                if dim not in cluster_stats or cluster_stats[dim]["sd"] == 0:
                    continue
                val = songs[ai].get(dim)
                if val is None:
                    continue
                z = abs(val - cluster_stats[dim]["mean"]) / cluster_stats[dim]["sd"]
                if z > ANCHOR_VIBE_OUTLIER_SD:
                    outlier_dims += 1

            if outlier_dims >= ANCHOR_VIBE_OUTLIER_MIN_DIMS:
                selected.remove(ai)
                dropped.append(ai)
                logger.info(
                    "Dropped anchor '%s' — vibe outlier on %d dimensions (threshold: %d)",
                    songs[ai].get("name", "?"), outlier_dims, ANCHOR_VIBE_OUTLIER_MIN_DIMS,
                )

        # Backfill dropped slots from the expansion pool
        if dropped:
            remaining = [i for i in range(n) if i not in set(selected)]
            for r in remaining:
                if len(selected) >= target_size:
                    break
                avg_sim = sum(sim_matrix[r][s] for s in selected) / len(selected)
                if avg_sim >= min_sim:
                    selected.append(r)

    # Compute cohesion stats
    if len(selected) >= 2:
        pair_sims = []
        for i, a in enumerate(selected):
            for b in selected[i + 1:]:
                pair_sims.append(sim_matrix[a][b])
        mean_sim = sum(pair_sims) / len(pair_sims)
    else:
        mean_sim = 0.0

    # Dominant genre in selected cluster
    genre_counts: dict[str, int] = {}
    for idx in selected:
        tags = songs[idx].get("genre_tags") or []
        for tag in tags:
            t = tag.lower().strip()
            genre_counts[t] = genre_counts.get(t, 0) + 1
    dominant_genre = max(genre_counts, key=genre_counts.get) if genre_counts else None

    stats = {
        "pool_size": n,
        "seed_idx": seed_idx,
        "seed_song": songs[seed_idx].get("name", ""),
        "relaxations": relaxations,
        "min_similarity_used": round(min_sim, 3),
        "mean_similarity": round(mean_sim, 4),
        "dominant_genre": dominant_genre,
        "anchor_count": len(anchor_pool_indices) if anchor_pool_indices else 0,
    }

    return _remap(selected), stats
