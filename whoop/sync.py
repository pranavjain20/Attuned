"""WHOOP data synchronization — pull and store recovery + sleep data."""

import logging
import sqlite3
from datetime import date

from db.queries import replace_whoop_recovery_history, upsert_whoop_recovery, upsert_whoop_sleep
from whoop.auth import get_valid_token
from whoop.client import get_records_for_date, _paginated_get, _parse_recovery_response, _parse_sleep_response
from config import WHOOP_BASE_URL

logger = logging.getLogger(__name__)


def sync_today(conn: sqlite3.Connection) -> dict[str, bool]:
    """Pull today's recovery and sleep data from WHOOP and store in DB."""
    return sync_date(conn, date.today().isoformat())


def sync_date(conn: sqlite3.Connection, target_date: str) -> dict[str, bool]:
    """Pull recovery and sleep data for a specific date from WHOOP.

    Returns dict indicating which records were found/stored.
    """
    token = get_valid_token(conn)
    result = {"recovery": False, "sleep": False}

    records = get_records_for_date(token, target_date)
    for recovery in records["recoveries"]:
        upsert_whoop_recovery(
            conn,
            cycle_id=recovery["cycle_id"],
            date=recovery["date"],
            recovery_score=recovery["recovery_score"],
            hrv_rmssd_milli=recovery["hrv_rmssd_milli"],
            resting_heart_rate=recovery["resting_heart_rate"],
            spo2=recovery.get("spo2"),
            skin_temp=recovery.get("skin_temp"),
        )
        logger.info("Stored recovery for %s: score=%.0f%%, HRV=%.1fms",
                     target_date, recovery["recovery_score"] or 0,
                     recovery["hrv_rmssd_milli"] or 0)
    result["recovery"] = bool(records["recoveries"])
    if not records["recoveries"]:
        logger.warning("No recovery data found for %s", target_date)

    sleeps = records["sleeps"]
    for sleep in sleeps:
        _store_sleep(conn, sleep)
        logger.info("Stored %s for %s: deep=%dms, REM=%dms",
                     "nap" if sleep.get("nap") else "sleep", target_date,
                     sleep.get("deep_sleep_ms") or 0, sleep.get("rem_sleep_ms") or 0)
    result["sleep"] = bool(sleeps)
    if not sleeps:
        logger.warning("No sleep data found for %s", target_date)

    return result


def sync_full_history(conn: sqlite3.Connection) -> dict[str, int]:
    """Pull ALL recovery and sleep history from WHOOP and store in DB.

    Returns counts of records stored.
    """
    token = get_valid_token(conn)
    counts = {"recovery": 0, "sleep": 0}

    # Sleeps first: each recovery takes the local date of the sleep it scores
    logger.info("Pulling full WHOOP sleep history...")
    sleeps = [_parse_sleep_response(raw)
              for raw in _paginated_get(token, f"{WHOOP_BASE_URL}/v2/activity/sleep", params={})]
    sleeps = [s for s in sleeps if s and s.get("date")]
    sleep_dates = {s["sleep_id"]: s["date"] for s in sleeps}

    logger.info("Pulling full WHOOP recovery history...")
    recoveries = [_parse_recovery_response(raw, sleep_dates)
                  for raw in _paginated_get(token, f"{WHOOP_BASE_URL}/v2/recovery", params={})]
    # Recoveries are written before sleeps, which link to them
    counts["recovery"] = replace_whoop_recovery_history(conn, [r for r in recoveries if r and r.get("date")])
    logger.info("Stored %d recovery records", counts["recovery"])

    for sleep in sleeps:
        _store_sleep(conn, sleep)
    counts["sleep"] = len(sleeps)
    logger.info("Stored %d sleep records", counts["sleep"])

    return counts


def _store_sleep(conn: sqlite3.Connection, sleep: dict) -> None:
    """Upsert one parsed WHOOP sleep record (main sleep or nap)."""
    upsert_whoop_sleep(
        conn,
        sleep_id=sleep["sleep_id"],
        date=sleep["date"],
        recovery_cycle_id=sleep.get("recovery_cycle_id"),
        deep_sleep_ms=sleep.get("deep_sleep_ms"),
        rem_sleep_ms=sleep.get("rem_sleep_ms"),
        light_sleep_ms=sleep.get("light_sleep_ms"),
        awake_ms=sleep.get("awake_ms"),
        sleep_efficiency=sleep.get("sleep_efficiency"),
        sleep_performance=sleep.get("sleep_performance"),
        sleep_consistency=sleep.get("sleep_consistency"),
        respiratory_rate=sleep.get("respiratory_rate"),
        disturbance_count=sleep.get("disturbance_count"),
        sleep_cycle_count=sleep.get("sleep_cycle_count"),
        sleep_needed_baseline_ms=sleep.get("sleep_needed_baseline_ms"),
        sleep_needed_debt_ms=sleep.get("sleep_needed_debt_ms"),
        sleep_needed_strain_ms=sleep.get("sleep_needed_strain_ms"),
        sleep_needed_nap_ms=sleep.get("sleep_needed_nap_ms"),
        nap=sleep.get("nap"),
    )
