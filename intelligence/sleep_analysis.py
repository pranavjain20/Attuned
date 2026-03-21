"""Sleep architecture analysis: deficits and adequacy vs personal norms."""

import logging
import sqlite3

logger = logging.getLogger(__name__)

from config import (
    DEEP_SLEEP_MIN_MS,
    DEEP_SLEEP_MIN_RATIO,
    REM_SLEEP_MIN_RATIO,
    SLEEP_ADEQUATE_SD,
    SLEEP_DEFICIT_SD,
)
from db.queries import get_sleeps_in_range
from intelligence.baselines import compute_sleep_debt, compute_sleep_stage_baselines


def _aggregate_sleep_records(sleeps: list[dict]) -> dict | None:
    """Aggregate multiple sleep records for a date into one summary.

    Sums deep/rem/light across all records. Returns None if no records.
    """
    if not sleeps:
        return None

    deep = 0
    rem = 0
    light = 0
    has_stage_data = False

    for s in sleeps:
        d, r, l = s["deep_sleep_ms"], s["rem_sleep_ms"], s["light_sleep_ms"]
        if d is not None and r is not None and l is not None:
            deep += d
            rem += r
            light += l
            has_stage_data = True

    if not has_stage_data:
        # All records have null stages — return first record as-is
        return dict(sleeps[0])

    # Build aggregated record based on first record, with summed stages
    aggregated = dict(sleeps[0])
    aggregated["deep_sleep_ms"] = deep
    aggregated["rem_sleep_ms"] = rem
    aggregated["light_sleep_ms"] = light
    return aggregated


def analyze_sleep(conn: sqlite3.Connection, date: str) -> dict | None:
    """Analyze last night's sleep architecture against personal baselines.

    Aggregates all sleep records for the date (primary + naps) before analysis.
    Returns dict with deficit/adequacy flags, debt, last night's data, and baselines.
    Returns None if no sleep data exists for `date`.
    """
    sleeps = get_sleeps_in_range(conn, date, date)
    if not sleeps:
        return None

    last_night = _aggregate_sleep_records(sleeps)

    deep = last_night["deep_sleep_ms"]
    rem = last_night["rem_sleep_ms"]
    light = last_night["light_sleep_ms"]

    # Handle missing stage data — track for data quality monitoring
    if deep is None or rem is None or light is None:
        logger.info("Sleep record for %s has null stage data — using insufficient baseline path", date)
        return {
            "deep_sleep_deficit": False,
            "rem_sleep_deficit": False,
            "deep_adequate": False,
            "rem_adequate": False,
            "sleep_debt_hours": compute_sleep_debt(conn, date),
            "last_night": last_night,
            "baselines": None,
            "insufficient_baseline": True,
        }

    total = deep + rem + light
    baselines = compute_sleep_stage_baselines(conn, date)
    debt = compute_sleep_debt(conn, date)
    insufficient = baselines is None

    if total == 0:
        return {
            "deep_sleep_deficit": True,
            "rem_sleep_deficit": True,
            "deep_adequate": False,
            "rem_adequate": False,
            "sleep_debt_hours": debt,
            "last_night": dict(last_night),
            "baselines": baselines,
            "insufficient_baseline": insufficient,
        }

    deep_ratio = deep / total
    rem_ratio = rem / total

    if insufficient:
        # Only absolute thresholds available
        deep_deficit = deep_ratio < DEEP_SLEEP_MIN_RATIO or deep < DEEP_SLEEP_MIN_MS
        rem_deficit = rem_ratio < REM_SLEEP_MIN_RATIO
        deep_ok = deep_ratio >= DEEP_SLEEP_MIN_RATIO and deep >= DEEP_SLEEP_MIN_MS
        rem_ok = rem_ratio >= REM_SLEEP_MIN_RATIO
    else:
        deep_mean = baselines["deep_ms"]["mean"]
        deep_sd = baselines["deep_ms"]["sd"]
        rem_mean = baselines["rem_ms"]["mean"]
        rem_sd = baselines["rem_ms"]["sd"]

        # Deficit: below mean-1.5*SD OR below absolute floor
        deep_deficit = (
            deep < deep_mean - SLEEP_DEFICIT_SD * deep_sd
            or deep_ratio < DEEP_SLEEP_MIN_RATIO
            or deep < DEEP_SLEEP_MIN_MS
        )
        rem_deficit = (
            rem < rem_mean - SLEEP_DEFICIT_SD * rem_sd
            or rem_ratio < REM_SLEEP_MIN_RATIO
        )

        # Adequate: above mean-1.0*SD AND above absolute floor
        deep_ok = (
            deep >= deep_mean - SLEEP_ADEQUATE_SD * deep_sd
            and deep_ratio >= DEEP_SLEEP_MIN_RATIO
            and deep >= DEEP_SLEEP_MIN_MS
        )
        rem_ok = (
            rem >= rem_mean - SLEEP_ADEQUATE_SD * rem_sd
            and rem_ratio >= REM_SLEEP_MIN_RATIO
        )

    return {
        "deep_sleep_deficit": deep_deficit,
        "rem_sleep_deficit": rem_deficit,
        "deep_adequate": deep_ok,
        "rem_adequate": rem_ok,
        "sleep_debt_hours": debt,
        "last_night": last_night,
        "baselines": baselines,
        "insufficient_baseline": insufficient,
    }
