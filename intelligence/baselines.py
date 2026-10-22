"""Personal baseline computations from WHOOP recovery and sleep data.

Computes rolling averages, standard deviations, and coefficients of variation
for HRV, RHR, and sleep architecture over configurable windows.
"""

import sqlite3

import numpy as np

from config import BASELINE_WINDOW_DAYS, MIN_BASELINE_DAYS, ROLLING_WINDOW_DAYS
from db.queries import get_recoveries_in_range, get_recovery_by_date, get_sleeps_in_range
from intelligence.dates import shift_date
from intelligence.main_sleep import asleep_ms, is_nap, main_sleep_by_date


def _date_range(date: str, window: int) -> tuple[str, str]:
    """Return (start_date, end_date) excluding `date` itself.

    Window covers [date - window, date - 1].
    """
    return shift_date(date, -window), shift_date(date, -1)


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
    Each day is its main sleep only (naps excluded — see intelligence/main_sleep.py),
    so "usual" is measured the same way as "last night".
    Skips days with missing stages or total_sleep = 0.

    Returns dict with keys: deep_ms, rem_ms, light_ms, total_sleep_ms, deep_ratio,
    rem_ratio — each a dict(mean, sd). Plus 'count'. Or None if <MIN_BASELINE_DAYS.
    """
    start, end = _date_range(date, window)
    nights = main_sleep_by_date(get_sleeps_in_range(conn, start, end)).values()

    deep_vals, rem_vals, light_vals, total_vals = [], [], [], []
    deep_ratios, rem_ratios = [], []

    for night in nights:
        total = asleep_ms(night)
        if not total:  # missing stages (None) or zero sleep
            continue
        deep, rem, light = night["deep_sleep_ms"], night["rem_sleep_ms"], night["light_sleep_ms"]
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
    """Compute rolling sleep debt in hours over the last `window` nights.

    The window ends on `date` itself: a date's sleep is the night that ended
    that morning ("last night"), so its shortfall counts the same day. Window
    covers [date - window + 1, date]. (Baselines, by contrast, stop the day
    before so today is compared against its past.)

    daily_debt = max(0, sleep_needed - actual_sleep)
    sleep_needed = baseline + debt + strain (nap offset NOT subtracted — conservative)
    actual_sleep = deep + rem + light, summed over every record that day, naps
                   included (a nap is real sleep and pays debt down)

    sleep_needed comes from the day's main-sleep record(s): a nap record can carry
    a different need. If no main record has a need (e.g. a nap-only day) the
    nap's need is used — the day still needed sleep; the nap is all that was got.

    Returns total debt in hours, or None if no valid days.
    """
    sleeps = get_sleeps_in_range(conn, shift_date(date, 1 - window), date)

    by_date: dict[str, list[dict]] = {}
    for s in sleeps:
        by_date.setdefault(s["date"], []).append(s)

    total_debt_ms = 0
    valid_days = 0
    for records in by_date.values():
        needed = _sleep_need_ms(records)
        if needed is None:
            continue
        actual = sum(
            (r["deep_sleep_ms"] or 0) + (r["rem_sleep_ms"] or 0) + (r["light_sleep_ms"] or 0)
            for r in records
        )
        total_debt_ms += max(0, needed - actual)
        valid_days += 1

    if valid_days == 0:
        return None
    return total_debt_ms / 3_600_000


def _sleep_need_ms(records: list[dict]) -> int | None:
    """WHOOP's sleep need for one day: from its main sleep, else from any record.

    Need = baseline + debt + strain. Falls back to nap records only when no main
    record carries a need (e.g. a nap-only day). None if no record has one.
    """
    main = [r for r in records if not is_nap(r)]
    for candidates in (main, records):
        needs = [
            r["sleep_needed_baseline_ms"] + (r["sleep_needed_debt_ms"] or 0)
            + (r["sleep_needed_strain_ms"] or 0)
            for r in candidates
            if r["sleep_needed_baseline_ms"] is not None
        ]
        if needs:
            return max(needs)
    return None


def compute_sleep_efficiency_baseline(
    conn: sqlite3.Connection,
    date: str,
    window: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """Compute sleep efficiency baseline over a window ending the day before `date`.

    One value per day from its main sleep (naps excluded — see
    intelligence/main_sleep.py), matching how last night's efficiency is measured.

    Returns dict(mean, sd, count) or None if fewer than MIN_BASELINE_DAYS valid days.
    """
    start, end = _date_range(date, window)
    nights = main_sleep_by_date(get_sleeps_in_range(conn, start, end)).values()
    values = [n["sleep_efficiency"] for n in nights if n.get("sleep_efficiency") is not None]
    if len(values) < MIN_BASELINE_DAYS:
        return None
    arr = np.array(values, dtype=np.float64)
    return {"mean": float(np.mean(arr)), "sd": float(np.std(arr, ddof=1)), "count": len(values)}


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
    debt_values = []
    for offset in range(1, window + 1):
        debt = compute_sleep_debt(conn, shift_date(date, -offset))
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
    today_rec = get_recovery_by_date(conn, date)
    yesterday_rec = get_recovery_by_date(conn, shift_date(date, -1))

    if today_rec is None or yesterday_rec is None:
        return None
    today_score = today_rec["recovery_score"]
    yesterday_score = yesterday_rec["recovery_score"]
    if today_score is None or yesterday_score is None:
        return None
    return float(today_score - yesterday_score)
