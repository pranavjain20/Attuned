"""WHOOP API client — recovery, sleep, and cycle data (v2 API)."""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from config import WHOOP_BASE_URL, WHOOP_PAGE_SIZE

logger = logging.getLogger(__name__)


def get_recovery_for_date(token: str, date: str) -> dict[str, Any] | None:
    """Fetch recovery data for a specific date (YYYY-MM-DD).

    Uses the v2 /recovery collection endpoint with date filtering.
    Returns parsed recovery dict or None if not found.
    """
    records = _paginated_get(
        token,
        f"{WHOOP_BASE_URL}/v2/recovery",
        params={"start": f"{date}T00:00:00.000Z", "end": f"{date}T23:59:59.999Z"},
    )
    for record in records:
        parsed = _parse_recovery_response(record)
        if parsed and parsed["date"] == date:
            return parsed
    return None


def get_sleep_for_date(token: str, date: str) -> dict[str, Any] | None:
    """Fetch sleep data for a specific date (YYYY-MM-DD).

    Uses the v2 /activity/sleep endpoint with date filtering.
    Returns parsed sleep dict or None if not found.
    """
    records = _paginated_get(
        token,
        f"{WHOOP_BASE_URL}/v2/activity/sleep",
        params={"start": f"{date}T00:00:00.000Z", "end": f"{date}T23:59:59.999Z"},
    )
    for record in records:
        parsed = _parse_sleep_response(record)
        if parsed and parsed["date"] == date:
            return parsed
    return None


def _paginated_get(
    token: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all pages from a WHOOP API endpoint using nextToken pagination."""
    results: list[dict[str, Any]] = []
    params = dict(params or {})
    params["limit"] = WHOOP_PAGE_SIZE
    next_token = None

    while True:
        if next_token:
            params["nextToken"] = next_token

        response = httpx.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        records = data.get("records", [])
        results.extend(records)

        next_token = data.get("next_token")
        if not next_token or not records:
            break

    return results


def _parse_recovery_response(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a WHOOP v2 recovery API response into our schema format."""
    score = raw.get("score", {})
    if not score:
        return None

    cycle_id = raw.get("cycle_id")
    if cycle_id is None:
        return None

    # Derive date from created_at timestamp
    date = _derive_date_from_timestamp(raw.get("created_at", ""))

    return {
        "cycle_id": cycle_id,
        "date": date,
        "recovery_score": score.get("recovery_score"),
        "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
        "resting_heart_rate": score.get("resting_heart_rate"),
        "spo2": score.get("spo2_percentage"),
        "skin_temp": score.get("skin_temp_celsius"),
    }


def _parse_sleep_response(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a WHOOP v2 sleep API response into our schema format."""
    score = raw.get("score", {})
    if not score:
        return None

    sleep_id = raw.get("id")
    if sleep_id is None:
        return None

    # v2 sleep IDs are UUIDs — use cycle_id (integer) for FK
    cycle_id = raw.get("cycle_id")

    # Derive date from sleep end time
    end_time = raw.get("end", "")
    date = _derive_date_from_timestamp(end_time)

    stage_summary = score.get("stage_summary", {})
    sleep_needed = score.get("sleep_needed", {})

    return {
        "sleep_id": sleep_id,
        "date": date,
        "recovery_cycle_id": cycle_id,
        "deep_sleep_ms": stage_summary.get("total_slow_wave_sleep_time_milli"),
        "rem_sleep_ms": stage_summary.get("total_rem_sleep_time_milli"),
        "light_sleep_ms": stage_summary.get("total_light_sleep_time_milli"),
        "awake_ms": stage_summary.get("total_awake_time_milli"),
        "sleep_efficiency": score.get("sleep_efficiency_percentage"),
        "sleep_performance": score.get("sleep_performance_percentage"),
        "sleep_consistency": score.get("sleep_consistency_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "disturbance_count": stage_summary.get("disturbance_count"),
        "sleep_cycle_count": stage_summary.get("sleep_cycle_count"),
        "sleep_needed_baseline_ms": sleep_needed.get("baseline_milli"),
        "sleep_needed_debt_ms": sleep_needed.get("need_from_sleep_debt_milli"),
        "sleep_needed_strain_ms": sleep_needed.get("need_from_recent_strain_milli"),
        "sleep_needed_nap_ms": sleep_needed.get("need_from_recent_nap_milli"),
    }


def _derive_date_from_timestamp(iso_timestamp: str) -> str:
    """Derive the user's local date from a WHOOP ISO 8601 timestamp.

    WHOOP timestamps include timezone offsets (e.g., '2026-03-17T06:30:00.000-05:00').
    We use the offset to determine the user's local date, NOT UTC.
    Falls back to UTC date if parsing fails.
    """
    if not iso_timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        return dt.date().isoformat()
    except (ValueError, TypeError):
        logger.warning("Could not parse WHOOP timestamp: %s", iso_timestamp)
        return iso_timestamp[:10] if len(iso_timestamp) >= 10 else ""
