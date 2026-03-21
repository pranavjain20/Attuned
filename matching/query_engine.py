"""Score and select songs for a given physiological state.

Uses neuro-score dot product (parasympathetic, sympathetic, grounding) against
state profiles. Scores by neuro_match × confidence. After scoring, a cohesion
layer (seed-and-expand) selects a sonically coherent subset from the top
candidates. No engagement in the formula — every classified song (2+ listens)
already passed the quality bar.
"""

import logging
import math
import re
import sqlite3
from typing import Any

from config import (
    MAX_PLAYLIST_SIZE,
    MIN_MATCH_FLOOR,
)
from db.queries import get_all_classified_songs, get_recent_playlist_track_uris
from matching.cohesion import select_cohesive_songs
from matching.state_mapper import get_state_neuro_profile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

# Strips "(From 'Movie Name')" and '(From "Movie Name")' — Bollywood album variants.
# Does NOT strip "(Remix)", "(Acoustic)", "(Live)" — those are genuinely different.
_FROM_PATTERN = re.compile(r"""\s*\(From\s+['"].*?['"]\)""", re.IGNORECASE)


def _normalize_title(name: str) -> str:
    """Normalize song title for near-duplicate detection.

    Strips "(From 'X')" / '(From "X")' suffixes and lowercases.
    """
    return _FROM_PATTERN.sub("", name).strip().lower()


def _dedup_near_duplicates(songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove near-duplicate songs, keeping the version with more plays.

    Two songs are near-duplicates if they share the same normalized title
    AND the same artist (case-insensitive).
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for song in songs:
        key = (
            _normalize_title(song.get("name", "")),
            (song.get("artist") or "").lower(),
        )
        existing = seen.get(key)
        if existing is None:
            seen[key] = song
        else:
            # Keep the version with more plays (engagement_score as proxy)
            existing_plays = existing.get("play_count") or 0
            new_plays = song.get("play_count") or 0
            if new_plays > existing_plays:
                logger.info(
                    "Dedup: keeping '%s' (%s plays) over '%s' (%s plays)",
                    song.get("name"), new_plays,
                    existing.get("name"), existing_plays,
                )
                seen[key] = song
            else:
                logger.info(
                    "Dedup: keeping '%s' (%s plays) over '%s' (%s plays)",
                    existing.get("name"), existing_plays,
                    song.get("name"), new_plays,
                )
    return list(seen.values())


# ---------------------------------------------------------------------------
# Neuro match scoring
# ---------------------------------------------------------------------------

def compute_neuro_match(
    song_para: float | None,
    song_symp: float | None,
    song_grnd: float | None,
    state_profile: dict[str, float],
) -> float:
    """Compute normalized dot product between song neuro scores and state profile.

    Returns 0.0-1.0. None scores are treated as 0.0 (no signal = no match).
    """
    para = song_para if song_para is not None else 0.0
    symp = song_symp if song_symp is not None else 0.0
    grnd = song_grnd if song_grnd is not None else 0.0

    w_para = state_profile["para"]
    w_symp = state_profile["symp"]
    w_grnd = state_profile["grnd"]

    dot = para * w_para + symp * w_symp + grnd * w_grnd

    magnitude = math.sqrt(w_para ** 2 + w_symp ** 2 + w_grnd ** 2)
    if magnitude == 0:
        return 0.0

    return min(dot / magnitude, 1.0)


# ---------------------------------------------------------------------------
# Confidence multiplier
# ---------------------------------------------------------------------------

def compute_confidence_multiplier(confidence: float | None) -> float:
    """Map classification confidence to a scoring multiplier.

    >= 0.7: 1.0 (Essentia + LLM agreement)
    >= 0.5: 0.85 (LLM-only or partial validation)
    < 0.5:  0.6 (shouldn't happen but defensive)
    """
    if confidence is None:
        return 0.6
    if confidence >= 0.7:
        return 1.0
    if confidence >= 0.5:
        return 0.85
    return 0.6


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# Gentle freshness nudge: subtractive (not multiplicative) so it only
# breaks ties among similarly-scored songs, never overrides a clearly
# better neurological match. Typical adjacent-song gap is 0.005-0.012.
FRESHNESS_NUDGE = {1: 0.02, 2: 0.01}  # days_ago → subtraction

# Familiarity multiplier: songs without engagement data (< 5 meaningful
# plays) get a small penalty. Doesn't override a genuinely better neuro
# match, but when scores are similar, songs you actually know and love
# float up. Songs with engagement are unaffected (1.0).
UNFAMILIAR_PENALTY = 0.95


def score_song(
    song: dict[str, Any],
    state_profile: dict[str, float],
    recent_playlist_uris: dict[str, int] | None = None,
) -> tuple[float, dict[str, float]]:
    """Score a single song. Returns (score, breakdown).

    Formula: neuro_match * confidence_mult * familiarity_mult - freshness_nudge
    """
    neuro_match = compute_neuro_match(
        song.get("parasympathetic"),
        song.get("sympathetic"),
        song.get("grounding"),
        state_profile,
    )

    confidence_mult = compute_confidence_multiplier(song.get("confidence"))

    # Familiarity: penalize songs with < 5 plays (no engagement data)
    familiarity_mult = 1.0 if song.get("engagement_score") is not None else UNFAMILIAR_PENALTY

    base_score = neuro_match * confidence_mult * familiarity_mult

    # Freshness nudge: tiny subtraction for recent playlist songs
    nudge = 0.0
    if recent_playlist_uris:
        uri = song.get("spotify_uri", "")
        days_ago = recent_playlist_uris.get(uri)
        if days_ago is not None:
            nudge = FRESHNESS_NUDGE.get(days_ago, 0.0)

    selection_score = base_score - nudge

    breakdown = {
        "neuro_match": round(neuro_match, 4),
        "confidence_mult": confidence_mult,
        "familiarity_mult": familiarity_mult,
        "freshness_nudge": round(nudge, 4),
        "selection_score": round(selection_score, 4),
    }
    return selection_score, breakdown


def compute_selection_scores(
    songs: list[dict[str, Any]],
    state_profile: dict[str, float],
    recent_playlist_uris: dict[str, int] | None = None,
) -> list[tuple[dict[str, Any], float, dict[str, float]]]:
    """Score all songs and return sorted list of (song, score, breakdown)."""
    scored = []
    for song in songs:
        selection_score, breakdown = score_song(song, state_profile, recent_playlist_uris)
        scored.append((song, selection_score, breakdown))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Result building
# ---------------------------------------------------------------------------

def _build_result_song(
    song: dict[str, Any],
    sel_score: float,
    breakdown: dict[str, float],
) -> dict[str, Any]:
    """Build a result dict for a selected song."""
    return {
        "spotify_uri": song["spotify_uri"],
        "name": song.get("name", ""),
        "artist": song.get("artist", ""),
        "album": song.get("album", ""),
        "parasympathetic": song.get("parasympathetic"),
        "sympathetic": song.get("sympathetic"),
        "grounding": song.get("grounding"),
        "confidence": song.get("confidence"),
        "last_played": song.get("last_played"),
        "play_count": song.get("play_count"),
        "bpm": song.get("bpm"),
        "energy": song.get("energy"),
        "genre_tags": song.get("genre_tags"),
        "mood_tags": song.get("mood_tags"),
        "release_year": song.get("release_year"),
        "selection_score": round(sel_score, 4),
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Selection: neuro scoring + cohesion-based seed-and-expand
# ---------------------------------------------------------------------------

def select_songs(
    conn: sqlite3.Connection,
    state: str,
    date: str,
) -> dict[str, Any]:
    """Select 15-20 songs matching the given physiological state.

    Algorithm:
    1. Score ALL songs by neuro_match × confidence.
    2. Take the top 60 candidates (all neurologically correct).
    3. Run seed-and-expand cohesion to pick a sonically coherent subset of 20.
    4. Progressive relaxation if <15 songs pass the similarity threshold.

    A gentle freshness nudge (tiny subtraction) gives a slight edge to
    songs not in yesterday's playlist — enough to break ties among
    similarly-scored songs, never enough to override a better match.

    Args:
        conn: Database connection.
        state: Detected physiological state (from classifier).
        date: Date string (YYYY-MM-DD) for freshness check.

    Returns:
        Dict with keys: songs, state, neuro_profile, match_stats.
    """
    neuro_profile = get_state_neuro_profile(state)

    all_songs = get_all_classified_songs(conn)
    if not all_songs:
        logger.warning("No classified songs in database")
        return {
            "songs": [],
            "state": state,
            "neuro_profile": neuro_profile,
            "match_stats": {"total_candidates": 0, "selected": 0,
                            "cohesion_stats": {}},
        }

    # Get recent playlist URIs for freshness nudge
    recent_playlist_uris = get_recent_playlist_track_uris(conn, before_date=date, days=2)

    # Score and rank all songs (unified ranking, with freshness nudge)
    scored = compute_selection_scores(all_songs, neuro_profile, recent_playlist_uris)

    # Cohesion: seed-and-expand from top candidates
    cohesion_indices, cohesion_stats = select_cohesive_songs(scored)

    # Check match floor on the best candidate
    if scored and scored[0][1] < MIN_MATCH_FLOOR:
        logger.warning(
            "Insufficient library coverage for state '%s' — "
            "best score %.3f below floor %.3f",
            state, scored[0][1], MIN_MATCH_FLOOR,
        )

    # Build result from cohesion-selected indices
    selected_songs = []
    for idx in cohesion_indices:
        song, sel_score, breakdown = scored[idx]
        selected_songs.append(_build_result_song(song, sel_score, breakdown))

    # Dedup near-duplicates (e.g., same song from different albums)
    pre_dedup_count = len(selected_songs)
    selected_songs = _dedup_near_duplicates(selected_songs)
    removed_count = pre_dedup_count - len(selected_songs)

    # Backfill from scored pool if dedup shrunk the playlist
    if removed_count > 0:
        logger.info(
            "Removed %d near-duplicate(s) from playlist, backfilling",
            removed_count,
        )
        selected_uris = {s["spotify_uri"] for s in selected_songs}
        selected_keys = {
            (_normalize_title(s.get("name", "")), (s.get("artist") or "").lower())
            for s in selected_songs
        }
        already_selected = set(cohesion_indices)
        for idx in range(len(scored)):
            if len(selected_songs) >= MAX_PLAYLIST_SIZE:
                break
            if idx in already_selected:
                continue
            song, sel_score, breakdown = scored[idx]
            if song["spotify_uri"] in selected_uris:
                continue
            key = (_normalize_title(song.get("name", "")), (song.get("artist") or "").lower())
            if key in selected_keys:
                continue
            selected_songs.append(_build_result_song(song, sel_score, breakdown))
            selected_uris.add(song["spotify_uri"])
            selected_keys.add(key)
            logger.info(
                "Backfilled: '%s' — %s (score=%.4f)",
                song.get("name"), song.get("artist"), sel_score,
            )

    # Sort final selection by score descending for display
    selected_songs.sort(key=lambda s: s["selection_score"], reverse=True)

    if selected_songs:
        scores = [s["selection_score"] for s in selected_songs]
        logger.info(
            "Selected %d songs for state '%s' (cohesion: mean_sim=%.3f, "
            "genre=%s): score range %.3f-%.3f",
            len(selected_songs), state,
            cohesion_stats.get("mean_similarity", 0),
            cohesion_stats.get("dominant_genre", "?"),
            min(scores), max(scores),
        )

    return {
        "songs": selected_songs,
        "state": state,
        "neuro_profile": neuro_profile,
        "match_stats": {
            "total_candidates": len(all_songs),
            "selected": len(selected_songs),
            "cohesion_stats": cohesion_stats,
        },
    }
