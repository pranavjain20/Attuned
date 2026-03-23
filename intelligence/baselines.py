"""Personal baseline computations from WHOOP recovery and sleep data.

Computes rolling averages, standard deviations, and coefficients of variation
for HRV, RHR, and sleep architecture over configurable windows.
"""

import sqlite3
from datetime import datetime, timedelta

import numpy as np

from config import BASELINE_WINDOW_DAYS, MIN_BASELINE_DAYS, ROLLING_WINDOW_DAYS
from db.queries import get_recoveries_in_range, get_recovery_by_date, get_sleeps_in_range


def _date_range(date: str, window: int) -> tuple[str, str]:
    """Return (start_date, end_date) excluding `date` itself.

    Window covers [date - window, date - 1].
    """
    d = datetime.strptime(date, "%Y-%m-%d")
    end = d - timedelta(days=1)
    start = d - timedelta(days=window)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def compute_hrv_baseline(
    conn: sqlite3.Connection,
    date: str,
    window: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """Compute HRV baseline (ln_rmssd) over a window ending the day before `date`.

    Returns dict(mean, sd, cv, count, values) or None if fewer than MIN_BASELINE_DAYS
    valid days.
    """
    start, end = _date_range(date, window)
    recoveries = get_recoveries_in_range(conn, start, end)
    values = [r["ln_rmssd"] for r in recoveries if r["ln_rmssd"] is not None]
    if len(values) < MIN_BASELINE_DAYS:
        return None
    arr = np.array(values, dtype=np.float64)
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1))
    cv = sd / mean if mean != 0 else 0.0
    return {"mean": mean, "sd": sd, "cv": cv, "count": len(values), "values": values}


def compute_rhr_baseline(
    conn: sqlite3.Connection,
    date: str,
    window: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """Compute RHR baseline over a window ending the day before `date`.

    Returns dict(mean, sd, count) or None if fewer than MIN_BASELINE_DAYS valid days.
    """
    start, end = _date_range(date, window)
    recoveries = get_recoveries_in_range(conn, start, end)
    values = [r["resting_heart_rate"] for r in recoveries if r["resting_heart_rate"] is not None]
    if len(values) < MIN_BASELINE_DAYS:
        return None
    arr = np.array(values, dtype=np.float64)
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1))
    return {"mean": mean, "sd": sd, "count": len(values)}


def compute_sleep_stage_baselines(
    conn: sqlite3.Connection,
    date: str,
    window: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """Compute sleep stage baselines over a window ending the day before `date`.

    Ratios are computed per-day then averaged (not from averaged totals).
    Skips days where total_sleep = 0.

    Returns dict with keys: deep_ms, rem_ms, light_ms, total_sleep_ms, deep_ratio,
    rem_ratio — each a dict(mean, sd). Plus 'count'. Or None if <MIN_BASELINE_DAYS.
    """
    start, end = _date_range(date, window)
    sleeps = get_sleeps_in_range(conn, start, end)

    # Group by date: sum stages across all sleep records (naps + primary) per day.
    by_date: dict[str, dict] = {}
    for s in sleeps:
        d = s["date"]
        deep = s["deep_sleep_ms"]
        rem = s["rem_sleep_ms"]
        light = s["light_sleep_ms"]
        if deep is None or rem is None or light is None:
            continue
        if d not in by_date:
            by_date[d] = {"deep": 0, "rem": 0, "light": 0}
        by_date[d]["deep"] += deep
        by_date[d]["rem"] += rem
        by_date[d]["light"] += light

    deep_vals, rem_vals, light_vals, total_vals = [], [], [], []
    deep_ratios, rem_ratios = [], []

    for day_data in by_date.values():
        deep, rem, light = day_data["deep"], day_data["rem"], day_data["light"]
        total = deep + rem + light
        if total == 0:
            continue
        deep_vals.append(deep)
        rem_vals.append(rem)
        light_vals.append(light)
        total_vals.append(total)
        deep_ratios.append(deep / total)
        rem_ratios.append(rem / total)

    if len(deep_vals) < MIN_BASELINE_DAYS:
        return None

    def _stats(values: list) -> dict:
        arr = np.array(values, dtype=np.float64)
        return {"mean": float(np.mean(arr)), "sd": float(np.std(arr, ddof=1))}

    return {
        "deep_ms": _stats(deep_vals),
        "rem_ms": _stats(rem_vals),
        "light_ms": _stats(light_vals),
        "total_sleep_ms": _stats(total_vals),
        "deep_ratio": _stats(deep_ratios),
        "rem_ratio": _stats(rem_ratios),
        "count": len(deep_vals),
    }


def compute_sleep_debt(
    conn: sqlite3.Connection,
    date: str,
    window: int = ROLLING_WINDOW_DAYS,
) -> float | None:
    """Compute rolling sleep debt in hours over the last `window` days.

    daily_debt = max(0, sleep_needed - actual_sleep)
    sleep_needed = baseline + debt + strain (nap offset NOT subtracted — conservative)
    actual_sleep = deep + rem + light

    Returns total debt in hours, or None if no valid days.
    """
    start, end = _date_range(date, window)
    sleeps = get_sleeps_in_range(conn, start, end)

    # Group by date: a day can have multiple sleep records (naps + primary).
    # Per date: sum actual sleep across records, take max needed (primary session).
    by_date: dict[str, dict] = {}
    for s in sleeps:
        d = s["date"]
        if d not in by_date:
            by_date[d] = {"needed": 0, "actual": 0, "has_needed": False}

        baseline_ms = s["sleep_needed_baseline_ms"]
        if baseline_ms is not None:
            debt_ms = s["sleep_needed_debt_ms"] or 0
            strain_ms = s["sleep_needed_strain_ms"] or 0
            record_needed = baseline_ms + debt_ms + strain_ms
            by_date[d]["needed"] = max(by_date[d]["needed"], record_needed)
            by_date[d]["has_needed"] = True

        deep = s["deep_sleep_ms"] or 0
        rem = s["rem_sleep_ms"] or 0
        light = s["light_sleep_ms"] or 0
        by_date[d]["actual"] += deep + rem + light

    total_debt_ms = 0
    valid_days = 0

    for day_data in by_date.values():
        if not day_data["has_needed"]:
            continue
        daily_debt = max(0, day_data["needed"] - day_data["actual"])
        total_debt_ms += daily_debt
        valid_days += 1

    if valid_days == 0:
        return None
    return total_debt_ms / 3_600_000


def compute_sleep_debt_baseline(
    conn: sqlite3.Connection,
    date: str,
    window: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """Compute personal sleep debt baseline over a window ending the day before `date`.

    For each of the `window` days before `date`, computes that day's 7-day rolling debt.
    Then takes mean + SD of those debt values.

    Returns dict(mean, sd, count) or None if fewer than MIN_BASELINE_DAYS valid days.
    """
    d = datetime.strptime(date, "%Y-%m-%d")

    debt_values = []
    for offset in range(1, window + 1):
        day = (d - timedelta(days=offset)).strftime("%Y-%m-%d")
        debt = compute_sleep_debt(conn, day)
        if debt is not None:
            debt_values.append(debt)

    if len(debt_values) < MIN_BASELINE_DAYS:
        return None

    arr = np.array(debt_values, dtype=np.float64)
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1))
    return {"mean": mean, "sd": sd, "count": len(debt_values)}


def compute_recovery_delta(
    conn: sqlite3.Connection,
    date: str,
) -> float | None:
    """Compute today's recovery minus yesterday's recovery.

    Returns float delta, or None if either day's recovery is missing.
    """
    d = datetime.strptime(date, "%Y-%m-%d")
    yesterday = (d - timedelta(days=1)).strftime("%Y-%m-%d")

    today_rec = get_recovery_by_date(conn, date)
    yesterday_rec = get_recovery_by_date(conn, yesterday)

    if today_rec is None or yesterday_rec is None:
        return None
    today_score = today_rec["recovery_score"]
    yesterday_score = yesterday_rec["recovery_score"]
    if today_score is None or yesterday_score is None:
        return None
    return float(today_score - yesterday_score)


def compute_recovery_delta_baseline(
    conn: sqlite3.Connection,
    date: str,
    window: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """Compute personal recovery delta statistics over a window ending the day before `date`.

    Looks at consecutive-day recovery pairs in [date - window, date - 1].
    Only computes a delta when two adjacent dates both have recovery scores.

    Returns dict(mean, sd, count) or None if fewer than MIN_BASELINE_DAYS valid delta pairs.
    """
    start, end = _date_range(date, window)
    recoveries = get_recoveries_in_range(conn, start, end)

    # Build date→score map, skipping nulls
    scores_by_date: dict[str, float] = {}
    for r in recoveries:
        if r["recovery_score"] is not None:
            scores_by_date[r["date"]] = float(r["recovery_score"])

    # Compute deltas only for consecutive calendar days
    deltas: list[float] = []
    sorted_dates = sorted(scores_by_date.keys())
    for i in range(1, len(sorted_dates)):
        prev_d = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
        curr_d = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
        if (curr_d - prev_d).days == 1:
            deltas.append(scores_by_date[sorted_dates[i]] - scores_by_date[sorted_dates[i - 1]])

    if len(deltas) < MIN_BASELINE_DAYS:
        return None

    arr = np.array(deltas, dtype=np.float64)
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1))
    return {"mean": mean, "sd": sd, "count": len(deltas)}
