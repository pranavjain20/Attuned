"""7-day trend analysis: slopes, consecutive-day detection for HRV and RHR."""

import sqlite3
from datetime import datetime, timedelta

import numpy as np

from config import HRV_DECLINE_DAYS, HRV_DECLINE_SD, RHR_ELEVATED_BPM, ROLLING_WINDOW_DAYS
from db.queries import get_recoveries_in_range


def _date_range(date: str, window: int) -> tuple[str, str]:
    """Return (start_date, end_date) where end_date = date itself (inclusive)."""
    d = datetime.strptime(date, "%Y-%m-%d")
    start = d - timedelta(days=window - 1)
    return start.strftime("%Y-%m-%d"), date


def compute_hrv_trend(
    conn: sqlite3.Connection,
    date: str,
    window: int = ROLLING_WINDOW_DAYS,
) -> dict | None:
    """Compute HRV trend (ln_rmssd) over `window` days ending on `date`.

    Returns dict(slope, mean, sd, cv, values, count) or None if <3 valid days.
    """
    start, end = _date_range(date, window)
    recoveries = get_recoveries_in_range(conn, start, end)
    values = [r["ln_rmssd"] for r in recoveries if r["ln_rmssd"] is not None]
    if len(values) < 3:
        return None
    arr = np.array(values, dtype=np.float64)
    x = np.arange(len(arr), dtype=np.float64)
    slope = float(np.polyfit(x, arr, 1)[0])
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1))
    cv = sd / mean if mean != 0 else 0.0
    return {"slope": slope, "mean": mean, "sd": sd, "cv": cv, "values": values, "count": len(values)}


def compute_rhr_trend(
    conn: sqlite3.Connection,
    date: str,
    window: int = ROLLING_WINDOW_DAYS,
) -> dict | None:
    """Compute RHR trend over `window` days ending on `date`.

    Returns dict(slope, mean, values, count) or None if <3 valid days.
    """
    start, end = _date_range(date, window)
    recoveries = get_recoveries_in_range(conn, start, end)
    values = [r["resting_heart_rate"] for r in recoveries if r["resting_heart_rate"] is not None]
    if len(values) < 3:
        return None
    arr = np.array(values, dtype=np.float64)
    x = np.arange(len(arr), dtype=np.float64)
    slope = float(np.polyfit(x, arr, 1)[0])
    mean = float(np.mean(arr))
    return {"slope": slope, "mean": mean, "values": values, "count": len(values)}


def is_hrv_declining(hrv_trend: dict, hrv_baseline: dict) -> dict:
    """Determine if HRV is in a declining pattern.

    Counts consecutive days below threshold from most recent day backward.
    Threshold = baseline_mean - HRV_DECLINE_SD * baseline_sd.
    Declining if consecutive_days_below >= HRV_DECLINE_DAYS.
    """
    threshold = hrv_baseline["mean"] - HRV_DECLINE_SD * hrv_baseline["sd"]
    consecutive = 0
    for value in reversed(hrv_trend["values"]):
        if value < threshold:
            consecutive += 1
        else:
            break
    return {
        "declining": consecutive >= HRV_DECLINE_DAYS,
        "consecutive_days_below": consecutive,
        "threshold": threshold,
    }


def is_rhr_rising(rhr_trend: dict, rhr_baseline: dict) -> dict:
    """Determine if RHR is in a rising pattern.

    Counts consecutive days above threshold from most recent day backward.
    Threshold = baseline_mean + RHR_ELEVATED_BPM.
    Rising if consecutive_days_above >= HRV_DECLINE_DAYS (same threshold).
    """
    threshold = rhr_baseline["mean"] + RHR_ELEVATED_BPM
    consecutive = 0
    for value in reversed(rhr_trend["values"]):
        if value > threshold:
            consecutive += 1
        else:
            break
    return {
        "rising": consecutive >= HRV_DECLINE_DAYS,
        "consecutive_days_above": consecutive,
        "threshold": threshold,
    }
