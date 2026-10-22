"""Daily neuro profile: the playlist target, set by the Attuned feeling score.

compute_continuous_profile scores the day (intelligence/feeling_score.py) and
turns the score's position into the playlist target (para = calming, symp =
energising, grnd = grounding) along the calm → steady → energy line described
in intelligence/playlist_target.py. WHOOP recovery is not an input: the score
leaves it out.

A day with no score (no night's sleep recorded, or fewer than
MIN_CALIBRATION_DAYS of scored history) gets the steady anchor.
"""

import logging
import sqlite3
from typing import Any

from config import (
    BASELINE_STEADY_ANCHOR,
    VALENCE_TARGET_GRND,
    VALENCE_TARGET_PARA,
    VALENCE_TARGET_SYMP,
)
from intelligence.feeling_score import locate_day
from intelligence.playlist_target import STATE_PURPOSE, pick_state, profile_at  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)

# A rest day among your lowest NAME_DEEP_SHARE of days (energy: your highest) gets the
# stronger name of its pair. My design choice: splits each end state roughly in half.
NAME_DEEP_SHARE = 0.15


def is_top_energy_day(state: str, position: float | None) -> bool:
    """An energy day among your highest NAME_DEEP_SHARE of days: your very best.

    These days get the stronger energy name ("Stay Sharp") and the only ones on
    which scene-tied motivational Bollywood songs play. No score → never.
    """
    return state == "energy" and position is not None and position > 1 - NAME_DEEP_SHARE


def compute_continuous_profile(
    conn: sqlite3.Connection,
    date: str,
    history: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Playlist target for `date`, set by the day's Attuned score position.

    `history` (from feeling_score.compute_composite_history) can be passed to
    avoid recomputing every earlier day (~3 s on three years of data).

    Returns dict with:
        profile: {para, symp, grnd} summing to 1.0
        target_valence: emotional tone that fits the profile (0-1)
        state, state_label: the profile's dominant dimension (see playlist_target.STATES)
        score: the Attuned 0-100 score (None when the day can't be scored)
        position: where the score sits among earlier days, 0-1 (None likewise)
        z_scores: the feeling-score signals behind the score
        signals_used: count of those signals present
    """
    day = locate_day(conn, date, history)
    position = day["position"]
    if position is None:
        profile = dict(BASELINE_STEADY_ANCHOR)
        logger.info("No Attuned score for %s (%s) — steady profile", date, day["reason"])
    else:
        profile = profile_at(position)
    state, state_label = pick_state(profile)

    # Target valence — what emotional tone fits this body state.
    # Weighted sum: each neuro dimension targets a different valence.
    target_valence = (
        profile["para"] * VALENCE_TARGET_PARA
        + profile["symp"] * VALENCE_TARGET_SYMP
        + profile["grnd"] * VALENCE_TARGET_GRND
    )

    logger.info(
        "Profile from Attuned score %s (position %s): para=%.2f symp=%.2f grnd=%.2f → %s",
        day["score"], None if position is None else f"{position:.2f}",
        profile["para"], profile["symp"], profile["grnd"], state,
    )

    z_scores = day["z"]
    return {
        "profile": profile,
        "target_valence": target_valence,
        "state": state,
        "state_label": state_label,
        "score": day["score"],
        "position": position,
        "z_scores": z_scores,
        "signals_used": sum(v is not None for v in z_scores.values()),
    }
