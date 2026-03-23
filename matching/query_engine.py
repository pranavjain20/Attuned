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
from db.queries import (
    get_all_classified_songs,
    get_consecutive_playlist_days,
    get_recent_playlist_track_uris,
)
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
FRESHNESS_NUDGE = {1: 0.04, 2: 0.03, 3: 0.02, 4: 0.01}  # days_ago → subtraction

# Familiarity multiplier: songs without engagement data (< 5 meaningful
# plays) get a small penalty. Doesn't override a genuinely better neuro
# match, but when scores are similar, songs you actually know and love
# float up. Songs with engagement are unaffected (1.0).
UNFAMILIAR_PENALTY = 0.95

# Hard cap: minimum days between repeat appearances. Scales logarithmically
# with library size — more songs = longer gap because there's more depth
# to rotate through. Current bangers (top quartile engagement + played in
# last 30 days) get a 1-day discount.
BANGER_RECENCY_DAYS = 30


def compute_min_repeat_gap(library_size: int, is_current_banger: bool) -> int:
    """Minimum days between a song's playlist appearances.

    Base gap scales with log2(library_size / 150), floored at 1.
    Current bangers get a 1-day discount (can be 0 = nudge only).
    """
    if library_size <= 0:
        return 0
    base = max(1, round(math.log2(library_size / 150)))
    if is_current_banger:
        return max(0, base - 1)
    return base


def is_current_banger(
    song: dict[str, Any],
    engagement_p75: float,
) -> bool:
    """Check if a song is a current banger (high engagement + recent).

    Top quartile engagement AND played in the last 30 days.
    """
    engagement = song.get("engagement_score")
    if engagement is None or engagement < engagement_p75:
        return False
    last_played = song.get("last_played")
    if not last_played:
        return False
    from datetime import date as date_cls, datetime, timedelta
    try:
        lp_date = datetime.strptime(last_played[:10], "%Y-%m-%d").date()
        cutoff = date_cls.today() - timedelta(days=BANGER_RECENCY_DAYS)
        return lp_date >= cutoff
    except (ValueError, TypeError):
        return False


def compute_engagement_p75(songs: list[dict[str, Any]]) -> float:
    """Compute the 75th percentile engagement score from the song pool."""
    scores = sorted(
        (s.get("engagement_score") for s in songs if s.get("engagement_score") is not None),
        reverse=True,
    )
    if not scores:
        return 0.0
    idx = len(scores) // 4
    return scores[idx]


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
        "engagement_score": song.get("engagement_score"),
        "bpm": song.get("bpm"),
        "energy": song.get("energy"),
        "genre_tags": song.get("genre_tags"),
        "mood_tags": song.get("mood_tags"),
        "release_year": song.get("release_year"),
        "selection_score": round(sel_score, 4),
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Lead track ordering
# ---------------------------------------------------------------------------

# The first few songs set the emotional tone before you press play.
# Re-rank the top candidates by blending neuro score with engagement
# so songs you genuinely love float to the front.
LEAD_TRACK_COUNT = 3
LEAD_POOL_SIZE = 10
LEAD_NEURO_WEIGHT = 0.7
LEAD_ENGAGEMENT_WEIGHT = 0.3


def _apply_lead_track_ordering(songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Promote high-engagement songs to the first few playlist positions.

    Takes the top LEAD_POOL_SIZE songs (already sorted by selection_score),
    re-ranks them by a blend of neuro score and engagement, and places the
    top LEAD_TRACK_COUNT at the front. The rest stays in selection_score order.
    """
    if len(songs) <= LEAD_TRACK_COUNT:
        return songs

    pool_size = min(LEAD_POOL_SIZE, len(songs))
    pool = songs[:pool_size]
    rest = songs[pool_size:]

    # Score the pool by blended lead score
    def lead_score(s: dict[str, Any]) -> float:
        neuro = s.get("selection_score", 0)
        engagement = s.get("engagement_score") or 0
        return neuro * LEAD_NEURO_WEIGHT + engagement * LEAD_ENGAGEMENT_WEIGHT

    pool.sort(key=lead_score, reverse=True)

    leads = pool[:LEAD_TRACK_COUNT]
    remaining_pool = pool[LEAD_TRACK_COUNT:]
    # Re-sort the non-lead pool songs back by selection_score
    remaining_pool.sort(key=lambda s: s["selection_score"], reverse=True)

    result = leads + remaining_pool + rest

    # Log if lead ordering changed anything
    lead_names = [f"'{s.get('name', '?')}'" for s in leads]
    logger.info("Lead tracks: %s", ", ".join(lead_names))

    return result


# ---------------------------------------------------------------------------
# Selection: neuro scoring + cohesion-based seed-and-expand
# ---------------------------------------------------------------------------

def select_songs(
    conn: sqlite3.Connection,
    state: str,
    date: str,
    neuro_profile_override: dict[str, float] | None = None,
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
        neuro_profile_override: If provided, use instead of state's default profile.

    Returns:
        Dict with keys: songs, state, neuro_profile, match_stats.
    """
    neuro_profile = neuro_profile_override if neuro_profile_override is not None else get_state_neuro_profile(state)

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
    recent_playlist_uris = get_recent_playlist_track_uris(conn, before_date=date, days=4)

    # Hard cap: exclude songs that have hit their consecutive appearance limit
    consecutive_days = get_consecutive_playlist_days(conn, before_date=date)
    blocked_uris: set[str] = set()
    if consecutive_days:
        library_size = len(all_songs)
        eng_p75 = compute_engagement_p75(all_songs)
        for uri, streak in consecutive_days.items():
            # Find the song to check banger status
            song_data = next((s for s in all_songs if s["spotify_uri"] == uri), None)
            banger = song_data is not None and is_current_banger(song_data, eng_p75)
            min_gap = compute_min_repeat_gap(library_size, banger)
            if streak >= min_gap and min_gap > 0:
                blocked_uris.add(uri)
        if blocked_uris:
            all_songs = [s for s in all_songs if s["spotify_uri"] not in blocked_uris]
            logger.info(
                "Hard cap: blocked %d song(s) from repeat (library=%d, p75=%.3f)",
                len(blocked_uris), library_size, eng_p75,
            )

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

    # Sort by score, then promote high-engagement songs to lead positions
    selected_songs.sort(key=lambda s: s["selection_score"], reverse=True)
    selected_songs = _apply_lead_track_ordering(selected_songs)

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
