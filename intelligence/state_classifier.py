"""Composite physiological state classifier.

Recovery-first, 5-tier system. Trusts WHOOP's recovery score as the primary
signal, then looks at individual metrics to determine HOW to help.

Priority order:
0. insufficient_data — <14 days HRV
1. accumulated_fatigue — recovery < 60 AND ≥3 of last 5 days also < 60
2. poor_sleep — both deep AND REM deficit (any recovery level)
3. physical_recovery_deficit — deep deficit only (any recovery level)
4. emotional_processing_deficit — REM deficit only (any recovery level)
5. poor_recovery — recovery < 40 (acute), or < 60 one-off (≤1 recent bad)
6. peak_readiness — recovery ≥ 80, HRV ≥ baseline, no deficits, low debt
7. baseline — default
"""

import sqlite3
from datetime import datetime, timedelta

from config import (
    FATIGUE_BAD_DAYS_MIN,
    FATIGUE_RECENT_DAYS,
    RECOVERY_TIER_2_MAX,
    RECOVERY_TIER_3_MAX,
    RECOVERY_TIER_4_MAX,
    RHR_PEAK_MAX_BPM,
    SLEEP_DEBT_PEAK_HOURS,
)
from db.queries import get_recoveries_in_range, get_recovery_by_date
from intelligence.baselines import (
    compute_hrv_baseline,
    compute_rhr_baseline,
    compute_sleep_debt_baseline,
)
from intelligence.sleep_analysis import analyze_sleep
from intelligence.trends import compute_hrv_trend, compute_rhr_trend

STATES = [
    "insufficient_data",
    "accumulated_fatigue",
    "poor_sleep",
    "physical_recovery_deficit",
    "emotional_processing_deficit",
    "poor_recovery",
    "peak_readiness",
    "baseline",
]


def classify_state(conn: sqlite3.Connection, date: str) -> dict:
    """Classify physiological state for a given date.

    Returns dict with: state, confidence, reasoning, metrics, baselines, trends,
    sleep_analysis, insufficient_data.
    """
    recovery = get_recovery_by_date(conn, date)
    hrv_baseline = compute_hrv_baseline(conn, date)
    rhr_baseline = compute_rhr_baseline(conn, date)
    hrv_trend = compute_hrv_trend(conn, date)
    rhr_trend = compute_rhr_trend(conn, date)
    sleep = analyze_sleep(conn, date)
    debt_baseline = compute_sleep_debt_baseline(conn, date)

    metrics = _extract_metrics(recovery, sleep)

    # P0: Insufficient data
    if hrv_baseline is None:
        return _build_result(
            state="insufficient_data",
            confidence="low",
            reasoning=["Fewer than 14 days of HRV data — cannot compute baselines"],
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    recovery_score = recovery["recovery_score"] if recovery else None
    sleep_debt = sleep["sleep_debt_hours"] if sleep else None
    deep_deficit = sleep and sleep["deep_sleep_deficit"]
    rem_deficit = sleep and sleep["rem_sleep_deficit"]

    today_struggling = recovery_score is not None and recovery_score < RECOVERY_TIER_3_MAX
    recent_bad = _count_recent_bad_days(conn, date)

    # P1: Accumulated fatigue — multi-day stress pattern
    if today_struggling and recent_bad >= FATIGUE_BAD_DAYS_MIN:
        reasoning = [
            f"Recovery {recovery_score:.0f}% (below {RECOVERY_TIER_3_MAX}%) "
            f"with {recent_bad} of last {FATIGUE_RECENT_DAYS} days also below {RECOVERY_TIER_3_MAX}%",
            "Multi-day stress pattern — body needs sustained recovery support",
        ]
        return _build_result(
            state="accumulated_fatigue",
            confidence="high" if recent_bad >= 4 else "medium",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P2: Poor sleep — both stages deficient (any recovery level)
    if deep_deficit and rem_deficit:
        reasoning = [
            "Both deep and REM sleep are deficient",
            "Overall poor sleep quality — body needs comprehensive recovery",
        ]
        return _build_result(
            state="poor_sleep",
            confidence="high" if not (sleep and sleep.get("insufficient_baseline")) else "medium",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P3: Physical recovery deficit — deep deficit only
    rem_not_deficit = sleep and not sleep["rem_sleep_deficit"]
    if deep_deficit and rem_not_deficit:
        reasoning = [
            "Deep sleep deficit detected while REM sleep is not deficient",
            "Body needs physical recovery — deep sleep is where tissue repair and growth hormone release happen",
        ]
        return _build_result(
            state="physical_recovery_deficit",
            confidence="high" if not sleep.get("insufficient_baseline") else "medium",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P4: Emotional processing deficit — REM deficit only
    deep_not_deficit = sleep and not sleep["deep_sleep_deficit"]
    if rem_deficit and deep_not_deficit:
        reasoning = [
            "REM sleep deficit detected while deep sleep is not deficient",
            "REM is critical for emotional regulation and memory consolidation",
        ]
        return _build_result(
            state="emotional_processing_deficit",
            confidence="high" if not sleep.get("insufficient_baseline") else "medium",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P5: Acute bad day — tier 1-2 (recovery < 40), definitively bad
    if recovery_score is not None and recovery_score < RECOVERY_TIER_2_MAX:
        reasoning = [
            f"Recovery {recovery_score:.0f}% — body is definitively stressed today",
            "Acute low recovery day",
        ]
        return _build_result(
            state="poor_recovery",
            confidence="medium",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P6: Mild bad day one-off — tier 3 (recovery < 60), not chronic
    if today_struggling and recent_bad <= 1:
        reasoning = [
            f"Recovery {recovery_score:.0f}% — suboptimal but recent days were mostly good",
            "Likely a single off day, not a chronic pattern",
        ]
        return _build_result(
            state="poor_recovery",
            confidence="medium",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P7: Peak readiness — tier 5 (recovery ≥ 80) + all green
    peak_conditions = _check_peak_conditions(
        recovery, hrv_baseline, rhr_baseline, hrv_trend, sleep, sleep_debt, debt_baseline,
    )
    if peak_conditions and all(peak_conditions.values()):
        reasoning = ["All systems go — recovery ≥80%, HRV at/above baseline, good sleep, low debt"]
        return _build_result(
            state="peak_readiness",
            confidence="high",
            reasoning=reasoning,
            metrics=metrics,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
            hrv_trend=hrv_trend,
            rhr_trend=rhr_trend,
            sleep_analysis=sleep,
        )

    # P8: Baseline (default)
    if today_struggling:
        reasoning = [
            f"Recovery {recovery_score:.0f}% with {recent_bad} of last {FATIGUE_RECENT_DAYS} "
            f"days also below {RECOVERY_TIER_3_MAX}% — inconclusive pattern",
        ]
    else:
        reasoning = ["No strong deficit or readiness signals detected — operating near baseline"]
    return _build_result(
        state="baseline",
        confidence="medium",
        reasoning=reasoning,
        metrics=metrics,
        hrv_baseline=hrv_baseline,
        rhr_baseline=rhr_baseline,
        hrv_trend=hrv_trend,
        rhr_trend=rhr_trend,
        sleep_analysis=sleep,
    )


def _count_recent_bad_days(conn: sqlite3.Connection, date: str) -> int:
    """Count days with recovery < RECOVERY_TIER_3_MAX in the FATIGUE_RECENT_DAYS before date."""
    d = datetime.strptime(date, "%Y-%m-%d")
    start = (d - timedelta(days=FATIGUE_RECENT_DAYS)).strftime("%Y-%m-%d")
    end = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    recoveries = get_recoveries_in_range(conn, start, end)
    return sum(
        1 for r in recoveries
        if r["recovery_score"] is not None and r["recovery_score"] < RECOVERY_TIER_3_MAX
    )


def _is_debt_low(sleep_debt: float | None, debt_baseline: dict | None) -> bool:
    """Check if sleep debt is not elevated — at or below personal average, with absolute fallback."""
    if sleep_debt is None:
        return False
    if debt_baseline is not None:
        return sleep_debt <= debt_baseline["mean"]
    return sleep_debt < SLEEP_DEBT_PEAK_HOURS


def _extract_metrics(recovery: dict | None, sleep: dict | None) -> dict:
    """Extract today's key metrics for the result."""
    metrics = {}
    if recovery:
        metrics["recovery_score"] = recovery["recovery_score"]
        metrics["hrv_rmssd_milli"] = recovery["hrv_rmssd_milli"]
        metrics["ln_rmssd"] = recovery["ln_rmssd"]
        metrics["resting_heart_rate"] = recovery["resting_heart_rate"]
    if sleep and sleep.get("last_night"):
        ln = sleep["last_night"]
        metrics["deep_sleep_ms"] = ln.get("deep_sleep_ms")
        metrics["rem_sleep_ms"] = ln.get("rem_sleep_ms")
        metrics["light_sleep_ms"] = ln.get("light_sleep_ms")
        metrics["sleep_debt_hours"] = sleep.get("sleep_debt_hours")
    return metrics


def _check_peak_conditions(
    recovery: dict | None,
    hrv_baseline: dict | None,
    rhr_baseline: dict | None,
    hrv_trend: dict | None,
    sleep: dict | None,
    sleep_debt: float | None,
    debt_baseline: dict | None,
) -> dict | None:
    """Check all Peak Readiness conditions. Returns dict of condition→bool or None if data missing."""
    if recovery is None or hrv_baseline is None or rhr_baseline is None:
        return None
    if recovery.get("ln_rmssd") is None or recovery.get("recovery_score") is None:
        return None
    if recovery.get("resting_heart_rate") is None:
        return None

    # hrv_trend=None → False condition (not enough trend data to confirm peak).
    # This is intentionally different from recovery/baseline=None which bail early,
    # because missing trend data is a softer signal than missing core metrics.
    conditions = {
        "recovery_tier_5": recovery["recovery_score"] >= RECOVERY_TIER_4_MAX,
        "hrv_at_or_above_mean": recovery["ln_rmssd"] >= hrv_baseline["mean"],
        "rhr_controlled": recovery["resting_heart_rate"] <= rhr_baseline["mean"] + RHR_PEAK_MAX_BPM,
        "low_sleep_debt": _is_debt_low(sleep_debt, debt_baseline),
        "trend_stable_or_rising": hrv_trend is not None and hrv_trend["slope"] >= 0,
    }

    if sleep:
        conditions["no_deep_deficit"] = not sleep.get("deep_sleep_deficit", True)
        conditions["no_rem_deficit"] = not sleep.get("rem_sleep_deficit", True)
    else:
        conditions["no_deep_deficit"] = False
        conditions["no_rem_deficit"] = False

    return conditions


def _build_result(
    state: str,
    confidence: str,
    reasoning: list[str],
    metrics: dict,
    hrv_baseline: dict | None,
    rhr_baseline: dict | None,
    hrv_trend: dict | None,
    rhr_trend: dict | None,
    sleep_analysis: dict | None,
) -> dict:
    """Build the standard result dict."""
    return {
        "state": state,
        "confidence": confidence,
        "reasoning": reasoning,
        "metrics": metrics,
        "baselines": {
            "hrv": hrv_baseline,
            "rhr": rhr_baseline,
        },
        "trends": {
            "hrv": hrv_trend,
            "rhr": rhr_trend,
        },
        "sleep_analysis": sleep_analysis,
        "insufficient_data": state == "insufficient_data",
    }
