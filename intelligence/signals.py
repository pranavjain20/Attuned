"""Today's physiological signals, each as a "vs my normal" z-score.

A z-score here is how far today sits from your own last-30-day average, in
units of your usual day-to-day wobble (the standard deviation), clamped to
±Z_CLAMP and signed so positive always means better. The Attuned feeling score
(intelligence/feeling_score.py) is a weighted average of these.

WHOOP's recovery score is not among them: it is built from HRV, resting heart
rate and sleep, which are already here, so including it would count those
twice and make the score a partial copy of the WHOOP ring shown next to it.

Sleep signals use last night's main sleep only (naps excluded, see
intelligence/main_sleep.py), and so do their "usual" values. After a night
under 6 h asleep, neither sleep efficiency nor deep-sleep share can count as
good news: a short night is naturally unbroken and front-loaded with deep sleep.
"""

import logging
import sqlite3

from db.queries import get_recovery_by_date
from intelligence.baselines import (
    compute_hrv_baseline,
    compute_rhr_baseline,
    compute_sleep_debt,
    compute_sleep_debt_baseline,
    compute_sleep_efficiency_baseline,
)
from intelligence.dates import shift_date
from intelligence.main_sleep import asleep_ms, is_short_night
from intelligence.sleep_analysis import analyze_sleep
from intelligence.trends import compute_hrv_trend

logger = logging.getLogger(__name__)

SIGNALS = (
    "sleep_efficiency_z", "deep_sleep_z", "rem_sleep_z", "total_sleep_z", "sleep_debt_z", "deep_ratio_z",
    "hrv_z", "rhr_z", "hrv_trend_z", "hrv_delta_z", "rhr_delta_z",
)

# z-score clamp: prevent extreme outliers from dominating
Z_CLAMP = 2.5

# Sleep debt z-score cap: debt above this threshold (7-day rolling hours) cannot
# produce a positive z-score. "Less debt than your chronic pattern" ≠ "good."
# The 7h threshold is my design choice (~1h/night short); no study gives it.
SLEEP_DEBT_POSITIVE_THRESHOLD = 7.0


def _safe_z(value: float | None, mean: float | None, sd: float | None) -> float | None:
    """Compute z-score, returning None if inputs are missing or sd is zero."""
    if value is None or mean is None or sd is None or sd == 0:
        return None
    z = (value - mean) / sd
    return max(-Z_CLAMP, min(Z_CLAMP, z))


def _vs_baseline(value: float | None, baseline: dict | None) -> float | None:
    """z of `value` against a baseline dict(mean, sd); None if either is missing."""
    return _safe_z(value, baseline["mean"], baseline["sd"]) if baseline else None


def _negated(z: float | None) -> float | None:
    """For signals where higher is worse (resting heart rate, debt): flip so positive = better."""
    return None if z is None else -z


def _not_good_news(z: float | None, cap: bool) -> float | None:
    """When `cap` holds, the signal may count against the day but never for it."""
    return min(z, 0.0) if z is not None and cap else z


def read_day(conn: sqlite3.Connection, date: str) -> dict:
    """Everything the signals and their explanations need for `date`, read once.

    Today's and yesterday's WHOOP recovery rows, last night's main sleep, and
    each personal baseline. Missing pieces are None.
    """
    sleep = analyze_sleep(conn, date)
    return {
        "recovery": get_recovery_by_date(conn, date),
        "yesterday": get_recovery_by_date(conn, shift_date(date, -1)),
        "last_night": sleep["last_night"] if sleep else None,
        "stage_baselines": sleep["baselines"] if sleep else None,
        "efficiency_baseline": compute_sleep_efficiency_baseline(conn, date),
        "debt": compute_sleep_debt(conn, date),
        "debt_baseline": compute_sleep_debt_baseline(conn, date),
        "hrv_baseline": compute_hrv_baseline(conn, date),
        "rhr_baseline": compute_rhr_baseline(conn, date),
        "hrv_trend": compute_hrv_trend(conn, date),
    }


def z_scores(day: dict) -> dict[str, float | None]:
    """The day's signals from its readings (see read_day): {signal: z or None}.

    Empty when there is no WHOOP recovery row for the day.
    """
    today = day["recovery"]
    if today is None:
        return {}
    yesterday = day["yesterday"] or {}
    night = day["last_night"] or {}
    stages = day["stage_baselines"] or {}
    hrv_bl, rhr_bl, debt = day["hrv_baseline"], day["rhr_baseline"], day["debt"]
    short_night = is_short_night(day["last_night"])

    ln_rmssd, rhr = today.get("ln_rmssd"), today.get("resting_heart_rate")
    ln_yesterday, rhr_yesterday = yesterday.get("ln_rmssd"), yesterday.get("resting_heart_rate")
    hrv_sd = hrv_bl["sd"] if hrv_bl else None
    rhr_sd = rhr_bl["sd"] if rhr_bl else None

    total_ms = asleep_ms(night)
    deep_ms = night.get("deep_sleep_ms")
    deep_ratio = deep_ms / total_ms if total_ms else None
    slope = (day["hrv_trend"] or {}).get("slope")

    return {
        # A short sleep is naturally unbroken, so high efficiency there is not good
        # news. Missing stage data → length unknown → no cap.
        "sleep_efficiency_z": _not_good_news(
            _vs_baseline(night.get("sleep_efficiency"), day["efficiency_baseline"]), short_night),
        "deep_sleep_z": _vs_baseline(deep_ms, stages.get("deep_ms")),
        "rem_sleep_z": _vs_baseline(night.get("rem_sleep_ms"), stages.get("rem_ms")),
        "total_sleep_z": _vs_baseline(total_ms, stages.get("total_sleep_ms")),
        # Less debt than your chronic pattern is not good news while you still
        # carry more than SLEEP_DEBT_POSITIVE_THRESHOLD hours of it.
        "sleep_debt_z": _not_good_news(
            _negated(_vs_baseline(debt, day["debt_baseline"])),
            debt is not None and debt > SLEEP_DEBT_POSITIVE_THRESHOLD),
        # Deep sleep comes early in the night, so a short night is mostly deep sleep
        # by default: a big share there means the night was cut short.
        "deep_ratio_z": _not_good_news(_vs_baseline(deep_ratio, stages.get("deep_ratio")), short_night),
        "hrv_z": _vs_baseline(ln_rmssd, hrv_bl),
        "rhr_z": _negated(_vs_baseline(rhr, rhr_bl)),
        # 7-day slope (per day) × 7 = the week's change, in units of your HRV wobble.
        "hrv_trend_z": _safe_z(7 * slope, 0, hrv_sd) if slope is not None else None,
        "hrv_delta_z": (_safe_z(ln_rmssd - ln_yesterday, 0, hrv_sd)
                        if ln_rmssd is not None and ln_yesterday is not None else None),
        "rhr_delta_z": (_negated(_safe_z(rhr - rhr_yesterday, 0, rhr_sd))
                        if rhr is not None and rhr_yesterday is not None else None),
    }


def compute_z_scores(conn: sqlite3.Connection, date: str) -> dict[str, float | None]:
    """All feeling-score signals for `date`: {signal: z or None}, empty with no WHOOP row."""
    if get_recovery_by_date(conn, date) is None:
        logger.warning("No recovery data for %s", date)
        return {}
    return z_scores(read_day(conn, date))
