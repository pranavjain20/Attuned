"""Continuous neuro profile from physiological metrics.

Replaces the state-machine → static-profile → modifier chain with a single
weighted function. Every metric contributes continuously to the parasympathetic,
sympathetic, and grounding components. No thresholds, no cliffs, no gates.

The state classifier still runs for display labels ("Rest & Repair" vs
"Fuel Up") but does NOT drive the neuro profile.
"""

import logging
import sqlite3
from typing import Any

from intelligence.baselines import (
    compute_hrv_baseline,
    compute_recovery_delta,
    compute_recovery_delta_baseline,
    compute_rhr_baseline,
    compute_sleep_debt,
    compute_sleep_debt_baseline,
    compute_sleep_stage_baselines,
)
from intelligence.sleep_analysis import analyze_sleep
from intelligence.trends import compute_hrv_trend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weight table: research-backed, sleep-dominant
#
# Sleep architecture correlates with next-morning subjective state at r=0.4-0.6
# (Vitale 2015, PMC6456824). HRV correlates at r=0.2-0.3 (Hynynen 2011).
# Aggregate sleep:autonomic weight ratio targets ~2:1 to match the research.
#
# Previous table had this inverted (2.5:1 autonomic over sleep) because the
# Day 10 sleep dampener was architecturally bypassed by the Day 12 continuous
# profile. See PRODUCT_DECISIONS.md "Day 20: Weight Rebalance" for full history.
#
# Each signal's z-score pushes the profile. Negative weight on para means
# a negative z (bad metric) INCREASES para (calming). Double negative = calming.
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    #                          para    symp    grnd
    "recovery_z":            {"para": -0.07, "symp":  0.07, "grnd":  0.00},
    "recovery_delta_z":      {"para": -0.04, "symp":  0.04, "grnd":  0.00},
    "hrv_z":                 {"para": -0.05, "symp":  0.05, "grnd":  0.00},
    "hrv_delta_z":           {"para": -0.02, "symp":  0.02, "grnd":  0.00},
    "rhr_z":                 {"para": -0.04, "symp":  0.04, "grnd":  0.00},
    "rhr_delta_z":           {"para": -0.02, "symp":  0.02, "grnd":  0.00},
    "deep_sleep_z":          {"para": -0.15, "symp":  0.10, "grnd": -0.05},
    "deep_ratio_z":          {"para":  0.00, "symp":  0.00, "grnd": -0.09},
    "rem_sleep_z":           {"para": -0.06, "symp":  0.00, "grnd": -0.14},
    "sleep_efficiency_z":    {"para": -0.18, "symp":  0.18, "grnd":  0.00},
    "sleep_debt_z":          {"para": -0.10, "symp":  0.06, "grnd": -0.04},
    "hrv_trend_z":           {"para": -0.03, "symp":  0.03, "grnd":  0.00},
}

# Interaction bonuses: when multiple signals are simultaneously bad
INTERACTION_THRESHOLD = -1.0
INTERACTION_PARA_BOOST = 0.05

# Neutral starting point
NEUTRAL_PROFILE = {"para": 0.33, "symp": 0.34, "grnd": 0.33}

# z-score clamp: prevent extreme outliers from dominating
Z_CLAMP = 2.5

# Global sensitivity: scales all weights. 1.0 = full sensitivity (too aggressive
# when many signals align). 0.2 = moderate sensitivity, tested across scenarios:
# - Great day (85% recovery): Para ~0.22, Symp ~0.44 (energetic)
# - Okay day (54%): Para ~0.34, Symp ~0.33 (balanced, slightly calm)
# - Bad day (44%): Para ~0.37, Symp ~0.29 (noticeably calmer)
# - Terrible day (15%): Para ~0.53, Symp ~0.08 (deep rest, more grounded)
# - Divergence (81% recovery, bad sleep): Para ~0.33, Symp ~0.32 (balanced, not energy)
WEIGHT_SENSITIVITY = 0.20

# Sleep debt z-score cap: debt above this threshold (7-day rolling hours) cannot
# produce a positive z-score. "Less debt than your chronic pattern" ≠ "good."
# Van Dongen 2003: 1h/night deficit (7h/week) is onset of measurable impairment.
# Belenky 2003 corroborates: 7h/night stable, 5h/night significant decline.
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

    Returns dict of signal_name → z_score (or None if data unavailable).
    """
    from db.queries import get_recovery_by_date

    # --- Fetch today's metrics ---
    today = get_recovery_by_date(conn, date)
    if today is None:
        logger.warning("No recovery data for %s", date)
        return {}

    recovery = today.get("recovery_score")
    ln_rmssd = today.get("ln_rmssd")
    rhr = today.get("resting_heart_rate")

    # --- Baselines ---
    hrv_bl = compute_hrv_baseline(conn, date)
    rhr_bl = compute_rhr_baseline(conn, date)
    sleep_bl = compute_sleep_stage_baselines(conn, date)
    debt_bl = compute_sleep_debt_baseline(conn, date)
    delta_bl = compute_recovery_delta_baseline(conn, date)
    hrv_trend = compute_hrv_trend(conn, date)

    # --- Recovery baselines (from recovery scores, not HRV) ---
    from intelligence.baselines import _date_range
    from db.queries import get_recoveries_in_range
    from config import BASELINE_WINDOW_DAYS, MIN_BASELINE_DAYS
    import numpy as np

    start, end = _date_range(date, BASELINE_WINDOW_DAYS)
    recs = get_recoveries_in_range(conn, start, end)
    rec_values = [r["recovery_score"] for r in recs if r["recovery_score"] is not None]
    rec_mean = float(np.mean(rec_values)) if len(rec_values) >= MIN_BASELINE_DAYS else None
    rec_sd = float(np.std(rec_values, ddof=1)) if len(rec_values) >= MIN_BASELINE_DAYS else None

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

    # --- Sleep efficiency baseline (compute from last 30 days) ---
    from db.queries import get_sleeps_in_range
    sleep_start, sleep_end = _date_range(date, BASELINE_WINDOW_DAYS)
    all_sleeps = get_sleeps_in_range(conn, sleep_start, sleep_end)
    eff_values = [s["sleep_efficiency"] for s in all_sleeps if s.get("sleep_efficiency") is not None]
    eff_mean = float(np.mean(eff_values)) if len(eff_values) >= MIN_BASELINE_DAYS else None
    eff_sd = float(np.std(eff_values, ddof=1)) if len(eff_values) >= MIN_BASELINE_DAYS else None

    # --- Debt ---
    debt = compute_sleep_debt(conn, date)

    # --- Recovery delta ---
    delta = compute_recovery_delta(conn, date)

    # --- Yesterday's metrics for day-over-day deltas ---
    from datetime import datetime, timedelta
    d = datetime.strptime(date, "%Y-%m-%d")
    yesterday_str = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday = get_recovery_by_date(conn, yesterday_str)
    yesterday_ln = yesterday.get("ln_rmssd") if yesterday else None
    yesterday_rhr = yesterday.get("resting_heart_rate") if yesterday else None

    # --- Compute z-scores ---
    scores: dict[str, float | None] = {}

    # Recovery z
    scores["recovery_z"] = _safe_z(recovery, rec_mean, rec_sd) if rec_mean else None

    # Recovery delta z
    if delta is not None and delta_bl:
        scores["recovery_delta_z"] = _safe_z(delta, delta_bl["mean"], delta_bl["sd"])
    else:
        scores["recovery_delta_z"] = None

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
    if deep_ratio is not None and sleep_baselines:
        scores["deep_ratio_z"] = _safe_z(
            deep_ratio, sleep_baselines["deep_ratio"]["mean"], sleep_baselines["deep_ratio"]["sd"]
        )
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
    scores["sleep_efficiency_z"] = _safe_z(efficiency, eff_mean, eff_sd) if eff_mean else None

    # Sleep debt z (INVERTED: high debt = bad = negative z)
    # Cap: debt above SLEEP_DEBT_POSITIVE_THRESHOLD cannot produce positive z.
    # "Less debt than your chronic pattern" is not a good signal when you still
    # carry meaningful debt. Van Dongen 2003: 7h/week is onset of impairment.
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


def compute_continuous_profile(
    conn: sqlite3.Connection,
    date: str,
) -> dict[str, Any]:
    """Compute continuous neuro profile from physiological metrics.

    Returns dict with:
        profile: {para, symp, grnd} summing to 1.0
        z_scores: all computed z-scores
        signals_used: count of non-None signals
        interactions: list of triggered interaction terms
    """
    z_scores = compute_z_scores(conn, date)

    profile = dict(NEUTRAL_PROFILE)
    interactions: list[str] = []

    # Apply weighted z-scores
    signals_used = 0
    for signal_name, weights in SIGNAL_WEIGHTS.items():
        z = z_scores.get(signal_name)
        if z is None:
            continue
        signals_used += 1
        for component in ("para", "symp", "grnd"):
            profile[component] += z * weights[component] * WEIGHT_SENSITIVITY

    # Interaction terms: multiplicative stress signals
    hrv_z = z_scores.get("hrv_z")
    rhr_z = z_scores.get("rhr_z")
    deep_z = z_scores.get("deep_sleep_z")
    rem_z = z_scores.get("rem_sleep_z")

    if hrv_z is not None and rhr_z is not None:
        if hrv_z < INTERACTION_THRESHOLD and rhr_z < INTERACTION_THRESHOLD:
            profile["para"] += INTERACTION_PARA_BOOST
            interactions.append(f"HRV+RHR both stressed (hrv_z={hrv_z:.2f}, rhr_z={rhr_z:.2f})")

    if deep_z is not None and rem_z is not None:
        if deep_z < INTERACTION_THRESHOLD and rem_z < INTERACTION_THRESHOLD:
            profile["para"] += INTERACTION_PARA_BOOST
            interactions.append(f"Deep+REM both deficit (deep_z={deep_z:.2f}, rem_z={rem_z:.2f})")

    # Clamp to [0, 1]
    for k in profile:
        profile[k] = max(0.0, profile[k])

    # Normalize to sum to 1.0
    total = sum(profile.values())
    if total > 0:
        for k in profile:
            profile[k] = round(profile[k] / total, 4)
    else:
        profile = dict(NEUTRAL_PROFILE)

    # Compute target valence — what emotional tone fits this body state.
    # Weighted sum: each neuro dimension targets a different valence.
    from config import VALENCE_TARGET_PARA, VALENCE_TARGET_SYMP, VALENCE_TARGET_GRND
    target_valence = (
        profile["para"] * VALENCE_TARGET_PARA
        + profile["symp"] * VALENCE_TARGET_SYMP
        + profile["grnd"] * VALENCE_TARGET_GRND
    )

    logger.info(
        "Continuous profile: para=%.2f symp=%.2f grnd=%.2f (target_valence=%.2f, %d signals, %d interactions)",
        profile["para"], profile["symp"], profile["grnd"],
        target_valence, signals_used, len(interactions),
    )

    return {
        "profile": profile,
        "target_valence": target_valence,
        "z_scores": z_scores,
        "signals_used": signals_used,
        "interactions": interactions,
    }
