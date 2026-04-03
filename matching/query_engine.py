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
    ANCHOR_MAX_COUNT,
    ANCHOR_RECENCY_DAYS,
    MAX_PLAYLIST_SIZE,
    MIN_MATCH_FLOOR,
    MIN_PLAYLIST_SIZE,
    MOOD_CLUSTERS,
    VALENCE_MATCH_WEIGHT,
)
from db.queries import (
    get_all_classified_songs,
    get_days_since_last_appearance,
    get_recent_playlist_track_uris,
)
from matching.cohesion import select_cohesive_songs
from matching.state_mapper import get_state_neuro_profile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

# Strips "(From 'Movie Name')" and '(From "Movie Name")' — Bollywood album variants.
_FROM_PATTERN = re.compile(r"""\s*\(From\s+['"].*?['"]\)""", re.IGNORECASE)

# Strips variant suffixes: "- Acoustic", "(Remix)", "- Live", "(Unplugged)", etc.
# Two versions of the same song by the same artist shouldn't both appear in a playlist.
_VARIANT_SUFFIXES = {"acoustic", "remix", "live", "unplugged", "lofi", "lofi flip",
                     "slowed", "reverb", "slowed + reverb", "sped up",
                     "deluxe", "remastered", "remaster", "radio edit"}
_VARIANT_PATTERN = re.compile(
    r"""\s*[-–—]\s*(?:"""
    + "|".join(re.escape(s) for s in sorted(_VARIANT_SUFFIXES, key=len, reverse=True))
    + r""")\s*$""",
    re.IGNORECASE,
)
_PAREN_VARIANT_PATTERN = re.compile(
    r"""\s*\(\s*(?:"""
    + "|".join(re.escape(s) for s in sorted(_VARIANT_SUFFIXES, key=len, reverse=True))
    + r""")\s*\)\s*$""",
    re.IGNORECASE,
)


def _normalize_title(name: str) -> str:
    """Normalize song title for near-duplicate detection.

    Strips "(From 'X')" / '(From "X")' album suffixes, variant suffixes like
    "- Acoustic", "(Remix)", "(Live)", "(Unplugged)", and lowercases.
    Two versions of the same song by the same artist collapse to the same key.
    """
    result = _FROM_PATTERN.sub("", name)
    result = _VARIANT_PATTERN.sub("", result)
    result = _PAREN_VARIANT_PATTERN.sub("", result)
    return result.strip().lower()


def _dedup_near_duplicates(songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove near-duplicate songs, keeping the version with more plays.

    Two passes:
    1. Same normalized title AND same artist (case-insensitive) — classic dedup.
    2. Same normalized title, different artists — avoids two "Ziddi Dil" in one playlist.
    """
    # Pass 1: same title + same artist
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
    result = list(seen.values())

    # Pass 2: same title, different artists — keep higher-scored version
    seen_titles: dict[str, dict[str, Any]] = {}
    deduped = []
    for song in result:
        title = _normalize_title(song.get("name", ""))
        existing = seen_titles.get(title)
        if existing is None:
            seen_titles[title] = song
            deduped.append(song)
        else:
            existing_score = existing.get("selection_score") or existing.get("play_count") or 0
            new_score = song.get("selection_score") or song.get("play_count") or 0
            if new_score > existing_score:
                logger.info(
                    "Title dedup: keeping '%s' — %s over '%s' — %s (same title)",
                    song.get("name"), song.get("artist"),
                    existing.get("name"), existing.get("artist"),
                )
                deduped = [s for s in deduped if s is not existing]
                deduped.append(song)
                seen_titles[title] = song
            else:
                logger.info(
                    "Title dedup: keeping '%s' — %s over '%s' — %s (same title)",
                    existing.get("name"), existing.get("artist"),
                    song.get("name"), song.get("artist"),
                )
    return deduped


# ---------------------------------------------------------------------------
# Neuro match scoring
# ---------------------------------------------------------------------------

def compute_neuro_match(
    song_para: float | None,
    song_symp: float | None,
    song_grnd: float | None,
    state_profile: dict[str, float],
) -> float:
    """Cosine similarity between song neuro scores and target profile.

    Measures directional alignment: a song that points in the same direction
    as the target scores high regardless of magnitude. A song that's "too much"
    in one dimension gets penalized — it's pointing slightly off-axis.

    Returns 0.0-1.0. None scores are treated as 0.0 (no signal = no match).
    """
    para = song_para if song_para is not None else 0.0
    symp = song_symp if song_symp is not None else 0.0
    grnd = song_grnd if song_grnd is not None else 0.0

    w_para = state_profile["para"]
    w_symp = state_profile["symp"]
    w_grnd = state_profile["grnd"]

    dot = para * w_para + symp * w_symp + grnd * w_grnd

    mag_song = math.sqrt(para ** 2 + symp ** 2 + grnd ** 2)
    mag_profile = math.sqrt(w_para ** 2 + w_symp ** 2 + w_grnd ** 2)

    if mag_song == 0 or mag_profile == 0:
        return 0.0

    return min(dot / (mag_song * mag_profile), 1.0)


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

# Hard cap: minimum days since last appearance before a song can return.
# Scales logarithmically with library size — more songs = longer gap because
# there's more depth to rotate through. Current bangers (top quartile
# engagement + played in last 30 days) get a 1-day discount.
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


def compute_valence_match(song_valence: float | None, target_valence: float | None) -> float:
    """Gaussian similarity between song's valence and target valence.

    Returns 1.0 when perfectly matched, decays with distance (sigma=0.20).
    Returns 1.0 (neutral) if either value is missing.
    """
    if song_valence is None or target_valence is None:
        return 1.0
    diff = abs(song_valence - target_valence)
    return math.exp(-0.5 * (diff / 0.20) ** 2)


def score_song(
    song: dict[str, Any],
    state_profile: dict[str, float],
    recent_playlist_uris: dict[str, int] | None = None,
    target_valence: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Score a single song. Returns (score, breakdown).

    Formula: (neuro_blend * confidence_mult * familiarity_mult) - freshness_nudge
    where neuro_blend = (1 - VALENCE_MATCH_WEIGHT) * neuro_match + VALENCE_MATCH_WEIGHT * valence_match
    """
    neuro_match = compute_neuro_match(
        song.get("parasympathetic"),
        song.get("sympathetic"),
        song.get("grounding"),
        state_profile,
    )

    valence_match = compute_valence_match(song.get("valence"), target_valence)

    # Blend neuro and valence signals
    if target_valence is not None:
        neuro_blend = (1 - VALENCE_MATCH_WEIGHT) * neuro_match + VALENCE_MATCH_WEIGHT * valence_match
    else:
        neuro_blend = neuro_match

    confidence_mult = compute_confidence_multiplier(song.get("confidence"))

    # Familiarity: penalize songs with < 5 plays (no engagement data)
    familiarity_mult = 1.0 if song.get("engagement_score") is not None else UNFAMILIAR_PENALTY

    base_score = neuro_blend * confidence_mult * familiarity_mult

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
        "valence_match": round(valence_match, 4),
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
    target_valence: float | None = None,
) -> list[tuple[dict[str, Any], float, dict[str, float]]]:
    """Score all songs and return sorted list of (song, score, breakdown)."""
    scored = []
    for song in songs:
        selection_score, breakdown = score_song(song, state_profile, recent_playlist_uris, target_valence=target_valence)
        scored.append((song, selection_score, breakdown))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Recent anchors
# ---------------------------------------------------------------------------

CONTEXT_EXCLUDE_TAGS = frozenset({"motivational", "patriotic"})

# Bollywood motivational songs are tied to specific movie scenes (training
# montages, sports anthems). Hearing them evokes the scene, not the mood.
# English motivational songs don't carry this baggage — Western pop isn't
# written for a specific film scene. Exclude Bollywood motivational from
# all playlists except peak_readiness, where the pump-up context fits.
BOLLYWOOD_GENRE_TAGS = frozenset({
    "bollywood", "punjabi", "bhangra", "soundtrack", "inspirational",
})


def is_context_specific_bollywood(song: dict) -> bool:
    """Check if a song is context-specific Bollywood (motivational, patriotic).

    These songs are tied to specific emotional contexts (training montages,
    army/national pride) that don't fit recovery/calming playlists.

    Two detection paths:
    1. Tag-based: mood includes motivational/patriotic AND genre is Bollywood/Punjabi
    2. Manual override: songs the LLM missed tagging but are known context-specific
    """
    uri = song.get("spotify_uri", "")
    if uri in _MOTIVATIONAL_OVERRIDES:
        return True
    mood_tags = song.get("mood_tags") or []
    genre_tags = song.get("genre_tags") or []
    has_context_tag = any(t.lower() in CONTEXT_EXCLUDE_TAGS for t in mood_tags)
    has_bollywood_genre = any(t.lower() in BOLLYWOOD_GENRE_TAGS for t in genre_tags)
    return has_context_tag and has_bollywood_genre


# Songs the LLM didn't tag as motivational but are context-specific
# (sports anthems, training montages). Add URIs here as you spot them.
_MOTIVATIONAL_OVERRIDES = frozenset({
    "spotify:track:3DYE6xs5FgGqkFZzlxjd1D",  # Halla Bol — Pritam
    "spotify:track:3E0D36S3MKA9e3f8yCOFR3",  # Chak Lein De — Kailash Kher
})

# Songs that passed engagement thresholds but the user doesn't recognize
# as part of their library (background/autoplay). Excluded from all playlists.
_USER_BLOCKLIST = frozenset({
    "spotify:track:7le3d8qTpRB5Lfwr79ARx4",  # Yeh Dil Deewana (Cover) — Gurnazar
})


def _expand_mood_filter(tags: list[str]) -> set[str]:
    """Expand mood filter tags to include semantically related tags via MOOD_CLUSTERS.

    E.g. ["motivational"] → {"motivational", "empowering", "inspirational", ...}
    Tags not in any cluster are kept as-is.
    """
    expanded = set()
    for tag in tags:
        tag_lower = tag.lower()
        if tag_lower in MOOD_CLUSTERS:
            expanded.update(MOOD_CLUSTERS[tag_lower])
        else:
            # Check if this tag appears in any cluster's values
            found = False
            for cluster_key, cluster_tags in MOOD_CLUSTERS.items():
                if tag_lower in cluster_tags:
                    expanded.update(cluster_tags)
                    found = True
                    break
            if not found:
                expanded.add(tag_lower)
    return expanded


def _apply_nl_filters(
    songs: list[dict],
    mood_filter: list[str] | None,
    genre_filter: list[str] | None,
    era_filter: str | None,
) -> list[dict]:
    """Restrict candidates by NL-requested mood, genre, or era filters.

    Applies each filter in order. If any filter would reduce the pool below
    MIN_PLAYLIST_SIZE, that filter is skipped (keeping what passed so far).
    If the very first filter already produces too few, falls back to unfiltered.
    """
    if not mood_filter and not genre_filter and not era_filter:
        return songs

    result = songs

    if mood_filter:
        mood_set = _expand_mood_filter(mood_filter)
        candidate = [
            s for s in result
            if any(t.lower() in mood_set for t in (s.get("mood_tags") or []))
        ]
        logger.info("Mood filter %s (expanded: %s): %d → %d songs", mood_filter, sorted(mood_set), len(result), len(candidate))
        if len(candidate) >= MIN_PLAYLIST_SIZE:
            result = candidate
        else:
            logger.warning("Mood filter too restrictive (%d < %d) — skipping", len(candidate), MIN_PLAYLIST_SIZE)

    if genre_filter:
        genre_set = {t.lower() for t in genre_filter}
        candidate = [
            s for s in result
            if any(t.lower() in genre_set for t in (s.get("genre_tags") or []))
        ]
        logger.info("Genre filter %s: %d → %d songs", genre_filter, len(result), len(candidate))
        if len(candidate) >= MIN_PLAYLIST_SIZE:
            result = candidate
        else:
            logger.warning("Genre filter too restrictive (%d < %d) — skipping", len(candidate), MIN_PLAYLIST_SIZE)

    if era_filter:
        candidate = _filter_by_era(result, era_filter)
        logger.info("Era filter '%s': %d → %d songs", era_filter, len(result), len(candidate))
        if len(candidate) >= MIN_PLAYLIST_SIZE:
            result = candidate
        else:
            logger.warning("Era filter too restrictive (%d < %d) — skipping", len(candidate), MIN_PLAYLIST_SIZE)

    return result


def _filter_by_era(songs: list[dict], era: str) -> list[dict]:
    """Filter songs by era string (e.g. '1990s', '2010s', 'pre-2005')."""
    era_lower = era.lower().strip()
    if era_lower.endswith("s") and era_lower[:-1].isdigit():
        # Decade: "1990s" → 1990-1999
        decade_start = int(era_lower[:-1])
        return [s for s in songs if s.get("release_year") and decade_start <= s["release_year"] < decade_start + 10]
    if era_lower.startswith("pre-") and era_lower[4:].isdigit():
        # "pre-2005" → before 2005
        cutoff = int(era_lower[4:])
        return [s for s in songs if s.get("release_year") and s["release_year"] < cutoff]
    if era_lower.startswith("post-") and era_lower[5:].isdigit():
        # "post-2010" → 2010 and later
        cutoff = int(era_lower[5:])
        return [s for s in songs if s.get("release_year") and s["release_year"] >= cutoff]
    logger.warning("Unrecognized era filter format: '%s' — ignoring", era)
    return songs


def identify_anchors(
    scored: list[tuple[dict, float, dict]],
    date: str,
    recency_days: int,
    max_count: int,
) -> list[int]:
    """Identify anchor candidates: top-scored songs played within recency_days.

    Skips songs that don't fit the playlist:
    - Context-specific moods (motivational, patriotic)
    - Era outliers: songs whose release year is too far from the top candidates'
      median era. Anchors must be coherent with the playlist, not just recent.

    Returns list of indices into the scored list (already sorted by score descending).
    """
    from datetime import datetime as dt, timedelta
    from statistics import median

    try:
        ref_date = dt.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return []

    # Compute median era of top 20 candidates (the likely playlist core)
    top_years = [
        s.get("original_release_year")
        for s, _, _ in scored[:20]
        if s.get("original_release_year")
    ]
    median_year = median(top_years) if top_years else None

    cutoff = ref_date - timedelta(days=recency_days)
    anchors: list[int] = []

    for idx, (song, _score, _breakdown) in enumerate(scored):
        if len(anchors) >= max_count:
            break
        last_played = song.get("last_played")
        if not last_played:
            continue
        try:
            lp_date = dt.strptime(last_played[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if lp_date < cutoff:
            continue
        # Skip context-specific songs (gym/workout) from anchor slots
        mood_tags = song.get("mood_tags") or []
        if any(t.lower() in CONTEXT_EXCLUDE_TAGS for t in mood_tags):
            continue
        # Skip era outliers — anchor must fit the playlist's era
        song_year = song.get("original_release_year")
        if median_year and song_year and abs(song_year - median_year) > 15:
            continue
        anchors.append(idx)

    return anchors


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
    target_valence: float | None = None,
    allow_motivational: bool = False,
    target_size: int | None = None,
    mood_filter: list[str] | None = None,
    genre_filter: list[str] | None = None,
    era_filter: str | None = None,
) -> dict[str, Any]:
    """Select songs matching the given physiological state.

    Algorithm:
    1. Score ALL songs by neuro_match × confidence, blended with valence match.
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
        target_valence: Target valence from continuous profile (0.0-1.0).
        mood_filter: If provided, restrict to songs with at least one matching mood tag.
        genre_filter: If provided, restrict to songs with at least one matching genre tag.
        era_filter: If provided, restrict to songs from that era (e.g. "1990s").

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

    # Exclude user-blocklisted songs
    all_songs = [s for s in all_songs if s.get("spotify_uri") not in _USER_BLOCKLIST]

    # Exclude Bollywood motivational songs unless peak_readiness or explicitly allowed
    if state != "peak_readiness" and not allow_motivational:
        before_count = len(all_songs)
        all_songs = [s for s in all_songs if not is_context_specific_bollywood(s)]
        excluded = before_count - len(all_songs)
        if excluded:
            logger.info("Excluded %d Bollywood motivational song(s) (state=%s)", excluded, state)

    # Apply NL filters (mood, genre, era) — restrict candidates when user specifies
    all_songs = _apply_nl_filters(all_songs, mood_filter, genre_filter, era_filter)

    # Get recent playlist URIs for freshness nudge
    recent_playlist_uris = get_recent_playlist_track_uris(conn, before_date=date, days=4)

    # Hard cap: exclude songs that appeared too recently
    days_since = get_days_since_last_appearance(conn, before_date=date)
    blocked_uris: set[str] = set()
    if days_since:
        library_size = len(all_songs)
        eng_p75 = compute_engagement_p75(all_songs)
        for uri, last_days_ago in days_since.items():
            song_data = next((s for s in all_songs if s["spotify_uri"] == uri), None)
            banger = song_data is not None and is_current_banger(song_data, eng_p75)
            min_gap = compute_min_repeat_gap(library_size, banger)
            if last_days_ago < min_gap and min_gap > 0:
                blocked_uris.add(uri)
        if blocked_uris:
            all_songs = [s for s in all_songs if s["spotify_uri"] not in blocked_uris]
            logger.info(
                "Hard cap: blocked %d song(s) — appeared within %d-day gap (library=%d)",
                len(blocked_uris), min_gap, library_size,
            )

    # Score and rank all songs (unified ranking, with freshness nudge)
    scored = compute_selection_scores(all_songs, neuro_profile, recent_playlist_uris, target_valence=target_valence)

    # Identify recent anchors — songs played within ANCHOR_RECENCY_DAYS
    # When mood_filter is active, only anchor songs that match the filter
    anchor_indices = identify_anchors(
        scored, date, ANCHOR_RECENCY_DAYS, ANCHOR_MAX_COUNT,
    )
    if anchor_indices and mood_filter:
        expanded_moods = _expand_mood_filter(mood_filter)
        anchor_indices = [
            i for i in anchor_indices
            if any(t.lower() in expanded_moods for t in (scored[i][0].get("mood_tags") or []))
        ]
    if anchor_indices:
        anchor_names = [
            f"'{scored[i][0].get('name', '?')}'" for i in anchor_indices
        ]
        logger.info("Anchors (%d): %s", len(anchor_indices), ", ".join(anchor_names))

    # Cohesion: seed-and-expand from top candidates
    effective_size = target_size if target_size is not None else MAX_PLAYLIST_SIZE
    cohesion_indices, cohesion_stats = select_cohesive_songs(
        scored, anchor_indices=anchor_indices if anchor_indices else None,
        target_size=effective_size,
    )

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
            if len(selected_songs) >= effective_size:
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
