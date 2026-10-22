"""Daily neuro profile: the playlist target, set by the Attuned feeling score.

Two jobs:

1. compute_z_scores: today's physiological signals as "vs my normal" z-scores
   (how far today sits from your own last-30-day average, in units of your usual
   day-to-day wobble). The feeling score (intelligence/feeling_score.py) is built
   from these.

2. compute_continuous_profile: the playlist target (para = calming, symp =
   energising, grnd = grounding). It follows the Attuned score. The score's
   position is where today sits among your own earlier days (0 = below every
   earlier day, 1 = above every one), and the position picks a point on one line:

       position 0.0  BASELINE_CALM_ANCHOR    low day: built to help you settle
       position 0.5  BASELINE_STEADY_ANCHOR  usual day: steady, keeps you level
       position 1.0  BASELINE_ENERGY_ANCHOR  high day: built to give you a lift

   Between anchors it blends the two nearest in a straight line, so a lower
   score always gives a calmer target, with no thresholds or jumps. WHOOP
   recovery is not an input: the score leaves it out.

   The day's label is the target's largest dimension. Because the target is a
   fixed function of the position, the label is too: with the anchors in
   config.py it is Rest below position ~0.29, Energy above ~0.71, Grounding in
   between. A near-tie only happens right at those two points and is settled by
   the position, never by day-to-day noise.

   A day with no score (no night's sleep recorded, or fewer than
   MIN_CALIBRATION_DAYS of scored history) gets the steady anchor.
"""

import logging
import sqlite3
from typing import Any

from config import (
    BASELINE_CALM_ANCHOR,
    BASELINE_ENERGY_ANCHOR,
    BASELINE_STEADY_ANCHOR,
    VALENCE_TARGET_GRND,
    VALENCE_TARGET_PARA,
    VALENCE_TARGET_SYMP,
)
from intelligence.baselines import (
    compute_hrv_baseline,
    compute_rhr_baseline,
    compute_sleep_debt,
    compute_sleep_debt_baseline,
    compute_sleep_efficiency_baseline,
)
from intelligence.main_sleep import is_short_night
from intelligence.sleep_analysis import analyze_sleep
from intelligence.trends import compute_hrv_trend

logger = logging.getLogger(__name__)

DIMENSIONS = ("para", "symp", "grnd")

# Dominant dimension → (state, display label). Ties: rest, then energy, then grounding.
STATES = {"para": ("rest", "Rest"), "symp": ("energy", "Energy"), "grnd": ("grounding", "Grounding")}

# What the music does on each state's days, finishing "built to …". The one wording behind
# the playlist description, the score explanation and the showcase page.
STATE_PURPOSE = {"rest": "help you settle", "energy": "give you a lift", "grounding": "keep you level"}

# A rest day among your lowest NAME_DEEP_SHARE of days (energy: your highest) gets the
# stronger name of its pair. Design choice: splits each end state roughly in half.
NAME_DEEP_SHARE = 0.15

# z-score clamp: prevent extreme outliers from dominating
Z_CLAMP = 2.5

# Sleep debt z-score cap: debt above this threshold (7-day rolling hours) cannot
# produce a positive z-score. "Less debt than your chronic pattern" ≠ "good."
# The 7h threshold is a design choice (~1h/night short); no study gives it.
SLEEP_DEBT_POSITIVE_THRESHOLD = 7.0


def _safe_z(value: float | None, mean: float, sd: float) -> float | None:
    """Compute z-score, returning None if inputs are missing or sd is zero."""
    if value is None or mean is None or sd is None or sd == 0:
        return None
    z = (value - mean) / sd
    return max(-Z_CLAMP, min(Z_CLAMP, z))


def compute_z_scores(
    conn: sqlite3.Connection,
    date: str,
) -> dict[str, float | None]:
    """Compute all physiological z-scores for a given date.

    WHOOP's recovery score is not among them: it is built from HRV, resting
    heart rate and sleep, which are already here (see feeling_score.py).

    Returns dict of signal_name → z_score (or None if data unavailable).
    """
    from db.queries import get_recovery_by_date

    # --- Fetch today's metrics ---
    today = get_recovery_by_date(conn, date)
    if today is None:
        logger.warning("No recovery data for %s", date)
        return {}

    ln_rmssd = today.get("ln_rmssd")
    rhr = today.get("resting_heart_rate")

    # --- Baselines ---
    hrv_bl = compute_hrv_baseline(conn, date)
    rhr_bl = compute_rhr_baseline(conn, date)
    debt_bl = compute_sleep_debt_baseline(conn, date)
    hrv_trend = compute_hrv_trend(conn, date)

    # --- Sleep data ---
    sleep = analyze_sleep(conn, date)
    last_night = sleep.get("last_night") if sleep else None
    sleep_baselines = sleep.get("baselines") if sleep else None

    deep_ms = last_night.get("deep_sleep_ms") if last_night else None
    rem_ms = last_night.get("rem_sleep_ms") if last_night else None
    light_ms = last_night.get("light_sleep_ms") if last_night else None
    efficiency = last_night.get("sleep_efficiency") if last_night else None

    total_ms = None
    if deep_ms is not None and rem_ms is not None and light_ms is not None:
        total_ms = deep_ms + rem_ms + light_ms

    deep_ratio = deep_ms / total_ms if total_ms and total_ms > 0 and deep_ms is not None else None

    # --- Sleep efficiency baseline (last 30 days, main sleep only — naps excluded) ---
    eff_bl = compute_sleep_efficiency_baseline(conn, date)

    # --- Debt ---
    debt = compute_sleep_debt(conn, date)

    # --- Yesterday's metrics for day-over-day deltas ---
    from datetime import datetime, timedelta
    d = datetime.strptime(date, "%Y-%m-%d")
    yesterday_str = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday = get_recovery_by_date(conn, yesterday_str)
    yesterday_ln = yesterday.get("ln_rmssd") if yesterday else None
    yesterday_rhr = yesterday.get("resting_heart_rate") if yesterday else None

    # --- Compute z-scores ---
    scores: dict[str, float | None] = {}

    # HRV z
    scores["hrv_z"] = _safe_z(ln_rmssd, hrv_bl["mean"], hrv_bl["sd"]) if hrv_bl else None

    # HRV delta z (today - yesterday, normalized by HRV baseline SD)
    if ln_rmssd is not None and yesterday_ln is not None and hrv_bl:
        hrv_delta = ln_rmssd - yesterday_ln
        scores["hrv_delta_z"] = _safe_z(hrv_delta, 0, hrv_bl["sd"])
    else:
        scores["hrv_delta_z"] = None

    # RHR z (INVERTED: high RHR = bad = negative z)
    if rhr is not None and rhr_bl:
        raw_rhr_z = _safe_z(rhr, rhr_bl["mean"], rhr_bl["sd"])
        scores["rhr_z"] = -raw_rhr_z if raw_rhr_z is not None else None
    else:
        scores["rhr_z"] = None

    # RHR delta z (INVERTED: rising RHR = bad = negative z)
    if rhr is not None and yesterday_rhr is not None and rhr_bl:
        rhr_delta = rhr - yesterday_rhr
        raw_delta_z = _safe_z(rhr_delta, 0, rhr_bl["sd"])
        scores["rhr_delta_z"] = -raw_delta_z if raw_delta_z is not None else None
    else:
        scores["rhr_delta_z"] = None

    # Deep sleep z
    if deep_ms is not None and sleep_baselines:
        scores["deep_sleep_z"] = _safe_z(
            deep_ms, sleep_baselines["deep_ms"]["mean"], sleep_baselines["deep_ms"]["sd"]
        )
    else:
        scores["deep_sleep_z"] = None

    # Deep ratio z
    # Cap: after a short night (under RESTORATIVE_SLEEP_TOTAL_MIN_MS asleep) a high
    # deep-sleep share cannot produce a positive z. Deep sleep comes early in the
    # night, so a short night is mostly deep sleep by default: a big share there is
    # a sign of the night being cut short, not good news. Same cap as efficiency.
    if deep_ratio is not None and sleep_baselines:
        z = _safe_z(deep_ratio, sleep_baselines["deep_ratio"]["mean"], sleep_baselines["deep_ratio"]["sd"])
        if z is not None and is_short_night(last_night):
            z = min(z, 0.0)
        scores["deep_ratio_z"] = z
    else:
        scores["deep_ratio_z"] = None

    # REM sleep z
    if rem_ms is not None and sleep_baselines:
        scores["rem_sleep_z"] = _safe_z(
            rem_ms, sleep_baselines["rem_ms"]["mean"], sleep_baselines["rem_ms"]["sd"]
        )
    else:
        scores["rem_sleep_z"] = None

    # Sleep efficiency z
    # Cap: after a short night (under RESTORATIVE_SLEEP_TOTAL_MIN_MS asleep) efficiency
    # cannot produce a positive z. A short sleep is naturally unbroken, so high
    # efficiency there is not good news. The 6h line is the existing design choice
    # in config.py. Missing stage data → length unknown → no cap.
    z = _safe_z(efficiency, eff_bl["mean"], eff_bl["sd"]) if eff_bl else None
    if z is not None and is_short_night(last_night):
        z = min(z, 0.0)
    scores["sleep_efficiency_z"] = z

    # Sleep debt z (INVERTED: high debt = bad = negative z)
    # Cap: debt above SLEEP_DEBT_POSITIVE_THRESHOLD cannot produce positive z.
    # "Less debt than your chronic pattern" is not a good signal when you still
    # carry meaningful debt. The 7h threshold is a design choice.
    if debt is not None and debt_bl:
        raw_debt_z = _safe_z(debt, debt_bl["mean"], debt_bl["sd"])
        z = -raw_debt_z if raw_debt_z is not None else None
        if z is not None and debt > SLEEP_DEBT_POSITIVE_THRESHOLD:
            z = min(z, 0.0)
        scores["sleep_debt_z"] = z
    else:
        scores["sleep_debt_z"] = None

    # HRV trend z (7-day slope normalized)
    if hrv_trend and hrv_trend.get("slope") is not None and hrv_bl and hrv_bl["sd"] > 0:
        # Normalize slope: divide by baseline SD so it's in "SD per day" units
        scores["hrv_trend_z"] = max(-Z_CLAMP, min(Z_CLAMP,
            hrv_trend["slope"] / hrv_bl["sd"] * 7  # scale to weekly magnitude
        ))
    else:
        scores["hrv_trend_z"] = None

    return scores


def profile_at(position: float) -> dict[str, float]:
    """Playlist target for a score position (0 = lowest day so far, 1 = highest).

    Straight-line blend calm → steady over [0, 0.5] and steady → energy over
    [0.5, 1]. Positions outside [0, 1] are clamped. Sums to 1.
    """
    p = max(0.0, min(1.0, position))
    if p <= 0.5:
        start, end, t = BASELINE_CALM_ANCHOR, BASELINE_STEADY_ANCHOR, p / 0.5
    else:
        start, end, t = BASELINE_STEADY_ANCHOR, BASELINE_ENERGY_ANCHOR, (p - 0.5) / 0.5
    return {k: start[k] + t * (end[k] - start[k]) for k in DIMENSIONS}


def pick_state(profile: dict[str, float]) -> tuple[str, str]:
    """Today's state = the profile's largest dimension. Ties: rest, then energy, then grounding."""
    dominant = max(DIMENSIONS, key=lambda k: profile[k])
    return STATES[dominant]


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
        state, state_label: the profile's dominant dimension (see STATES)
        score: the Attuned 0-100 score (None when the day can't be scored)
        position: where the score sits among earlier days, 0-1 (None likewise)
        z_scores: the feeling-score signals behind the score
        signals_used: count of those signals present
    """
    # Imported here, not at the top: feeling_score builds on this module's z-scores.
    from intelligence.feeling_score import locate_day

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
