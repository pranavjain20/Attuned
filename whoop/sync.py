"""WHOOP data synchronization — pull and store recovery + sleep data."""

import logging
import sqlite3
from datetime import date

from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from whoop.auth import get_valid_token
from whoop.client import get_recovery_for_date, get_sleep_for_date, _paginated_get, _parse_recovery_response, _parse_sleep_response
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

    recovery = get_recovery_for_date(token, target_date)
    if recovery:
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
        result["recovery"] = True
        logger.info("Stored recovery for %s: score=%.0f%%, HRV=%.1fms",
                     target_date, recovery["recovery_score"] or 0,
                     recovery["hrv_rmssd_milli"] or 0)
    else:
        logger.warning("No recovery data found for %s", target_date)

    sleep = get_sleep_for_date(token, target_date)
    if sleep:
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
        )
        result["sleep"] = True
        logger.info("Stored sleep for %s: deep=%dms, REM=%dms",
                     target_date, sleep.get("deep_sleep_ms") or 0,
                     sleep.get("rem_sleep_ms") or 0)
    else:
        logger.warning("No sleep data found for %s", target_date)

    return result


def sync_full_history(conn: sqlite3.Connection) -> dict[str, int]:
    """Pull ALL recovery and sleep history from WHOOP and store in DB.

    Returns counts of records stored.
    """
    token = get_valid_token(conn)
    counts = {"recovery": 0, "sleep": 0}

    # Pull all recovery records
    logger.info("Pulling full WHOOP recovery history...")
    raw_recoveries = _paginated_get(token, f"{WHOOP_BASE_URL}/v2/recovery", params={})
    for raw in raw_recoveries:
        parsed = _parse_recovery_response(raw)
        if parsed and parsed.get("date"):
            upsert_whoop_recovery(
                conn,
                cycle_id=parsed["cycle_id"],
                date=parsed["date"],
                recovery_score=parsed["recovery_score"],
                hrv_rmssd_milli=parsed["hrv_rmssd_milli"],
                resting_heart_rate=parsed["resting_heart_rate"],
                spo2=parsed.get("spo2"),
                skin_temp=parsed.get("skin_temp"),
            )
            counts["recovery"] += 1
    logger.info("Stored %d recovery records", counts["recovery"])

    # Pull all sleep records
    logger.info("Pulling full WHOOP sleep history...")
    raw_sleeps = _paginated_get(token, f"{WHOOP_BASE_URL}/v2/activity/sleep", params={})
    for raw in raw_sleeps:
        parsed = _parse_sleep_response(raw)
        if parsed and parsed.get("date"):
            upsert_whoop_sleep(
                conn,
                sleep_id=parsed["sleep_id"],
                date=parsed["date"],
                recovery_cycle_id=parsed.get("recovery_cycle_id"),
                deep_sleep_ms=parsed.get("deep_sleep_ms"),
                rem_sleep_ms=parsed.get("rem_sleep_ms"),
                light_sleep_ms=parsed.get("light_sleep_ms"),
                awake_ms=parsed.get("awake_ms"),
                sleep_efficiency=parsed.get("sleep_efficiency"),
                sleep_performance=parsed.get("sleep_performance"),
                sleep_consistency=parsed.get("sleep_consistency"),
                respiratory_rate=parsed.get("respiratory_rate"),
                disturbance_count=parsed.get("disturbance_count"),
                sleep_cycle_count=parsed.get("sleep_cycle_count"),
                sleep_needed_baseline_ms=parsed.get("sleep_needed_baseline_ms"),
                sleep_needed_debt_ms=parsed.get("sleep_needed_debt_ms"),
                sleep_needed_strain_ms=parsed.get("sleep_needed_strain_ms"),
                sleep_needed_nap_ms=parsed.get("sleep_needed_nap_ms"),
            )
            counts["sleep"] += 1
    logger.info("Stored %d sleep records", counts["sleep"])

    return counts
