"""WHOOP data synchronization — pull and store recovery + sleep data."""

import logging
import sqlite3
from datetime import date

from db.queries import replace_whoop_recovery_history, upsert_whoop_sleep
from whoop.auth import get_valid_token
from whoop.client import get_all_records, get_records_near_date

logger = logging.getLogger(__name__)


def sync_today(conn: sqlite3.Connection) -> dict[str, bool]:
    """Pull today's recovery and sleep data from WHOOP and store in DB."""
    return sync_date(conn, date.today().isoformat())


def sync_date(conn: sqlite3.Connection, target_date: str) -> dict[str, bool]:
    """Pull recovery and sleep data for a specific date from WHOOP.

    Every record WHOOP returns around the date is stored the way
    sync_full_history stores the whole history (see _store_records): WHOOP
    decides each record's date, so a row still under an old date moves to its
    local date instead of blocking the right recovery.

    Returns dict indicating whether `target_date` itself got a recovery / sleep.
    """
    records = get_records_near_date(get_valid_token(conn), target_date)
    _store_records(conn, records)

    recoveries = [r for r in records["recoveries"] if r["date"] == target_date]
    for recovery in recoveries:
        logger.info("Stored recovery for %s: score=%.0f%%, HRV=%.1fms",
                    target_date, recovery["recovery_score"] or 0, recovery["hrv_rmssd_milli"] or 0)
    if not recoveries:
        logger.warning("No recovery data found for %s", target_date)

    sleeps = [s for s in records["sleeps"] if s["date"] == target_date]
    for sleep in sleeps:
        logger.info("Stored %s for %s: deep=%dms, REM=%dms",
                    "nap" if sleep.get("nap") else "sleep", target_date,
                    sleep.get("deep_sleep_ms") or 0, sleep.get("rem_sleep_ms") or 0)
    if not sleeps:
        logger.warning("No sleep data found for %s", target_date)

    return {"recovery": bool(recoveries), "sleep": bool(sleeps)}


def sync_full_history(conn: sqlite3.Connection) -> dict[str, int]:
    """Pull ALL recovery and sleep history from WHOOP and store in DB.

    Returns counts of records stored.
    """
    logger.info("Pulling full WHOOP sleep and recovery history...")
    counts = _store_records(conn, get_all_records(get_valid_token(conn)))
    logger.info("Stored %d recovery records, %d sleep records", counts["recovery"], counts["sleep"])
    return counts


def _store_records(conn: sqlite3.Connection, records: dict[str, list[dict]]) -> dict[str, int]:
    """Store parsed WHOOP records; WHOOP's records decide every date they cover.

    Recoveries go through replace_whoop_recovery_history, which moves stored rows
    to their dates (e.g. from old UTC dates to local ones). They are written
    before sleeps, which link to them. Returns counts written.
    """
    recovery_count = replace_whoop_recovery_history(conn, records["recoveries"])
    for sleep in records["sleeps"]:
        _store_sleep(conn, sleep)
    return {"recovery": recovery_count, "sleep": len(records["sleeps"])}


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
