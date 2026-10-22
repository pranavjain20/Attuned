"""WHOOP API client — recovery, sleep, and cycle data (v2 API)."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from config import WHOOP_BASE_URL, WHOOP_PAGE_SIZE

logger = logging.getLogger(__name__)


def get_records_for_date(token: str, date: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch every recovery and sleep record whose local date is `date` (YYYY-MM-DD).

    Returns {"recoveries": [...], "sleeps": [...]}. Sleeps include naps — a date
    can hold a night plus naps, and keeping only the first would store whichever
    the API listed first (often a nap). A recovery is dated by the sleep it scores.

    WHOOP filters by UTC time, and a local date spans UTC from the day before to
    the day after (UTC+14 to UTC−12), so a three-day window is asked for and the
    records are kept by their local date.
    """
    day = datetime.strptime(date, "%Y-%m-%d")
    params = {
        "start": f"{(day - timedelta(days=2)):%Y-%m-%d}T00:00:00.000Z",
        "end": f"{(day + timedelta(days=1)):%Y-%m-%d}T23:59:59.999Z",
    }
    sleeps = [_parse_sleep_response(r) for r in _paginated_get(token, f"{WHOOP_BASE_URL}/v2/activity/sleep", params=params)]
    sleeps = [s for s in sleeps if s]
    sleep_dates = {s["sleep_id"]: s["date"] for s in sleeps}
    recoveries = [_parse_recovery_response(r, sleep_dates)
                  for r in _paginated_get(token, f"{WHOOP_BASE_URL}/v2/recovery", params=params)]
    return {
        "recoveries": [r for r in recoveries if r and r["date"] == date],
        "sleeps": [s for s in sleeps if s["date"] == date],
    }


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

        if not isinstance(data, dict):
            logger.error(
                "WHOOP API returned non-dict response from %s: %s",
                endpoint, type(data).__name__,
            )
            return results

        if "records" not in data:
            logger.warning(
                "WHOOP API response from %s missing 'records' key (keys: %s)",
                endpoint, list(data.keys()),
            )
            return results

        records = data["records"]
        results.extend(records)

        next_token = data.get("next_token")
        if not next_token or not records:
            break

    return results


def _parse_recovery_response(raw: dict[str, Any], sleep_dates: dict[Any, str]) -> dict[str, Any] | None:
    """Parse a WHOOP v2 recovery API response into our schema format.

    A recovery has no time zone of its own; it scores one sleep (`sleep_id`), so it
    takes that sleep's local date from `sleep_dates` ({sleep_id: date}). That keeps
    a night and its recovery on the same date, even when WHOOP scored the recovery
    hours later. If the sleep is unknown, falls back to the UTC date of created_at.
    """
    score = raw.get("score", {})
    if not score:
        return None

    cycle_id = raw.get("cycle_id")
    if cycle_id is None:
        return None

    date = sleep_dates.get(raw.get("sleep_id"))
    if date is None:
        logger.warning("WHOOP recovery %s has no known sleep (%s) — dating it by UTC created_at",
                       cycle_id, raw.get("sleep_id"))
        date = local_date(raw.get("created_at", ""), None)

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

    # A sleep belongs to the local date it ended on (the morning you woke up)
    date = local_date(raw.get("end", ""), raw.get("timezone_offset"))

    stage_summary = score.get("stage_summary", {})
    sleep_needed = score.get("sleep_needed", {})
    nap = raw.get("nap")
    if nap is not None and not isinstance(nap, bool):
        logger.warning("WHOOP sleep %s has non-boolean nap flag %r — storing as unknown", sleep_id, nap)
        nap = None

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
        "nap": nap,
    }


def local_date(timestamp: str | None, timezone_offset: str | None) -> str:
    """The wearer's own calendar date at `timestamp`.

    WHOOP sends times in UTC ("...Z") and the wearer's offset from UTC as a
    separate `timezone_offset` field (e.g. "+05:30", "-04:00"). The UTC date is
    wrong far from UTC: a night ending at 04:00 in India is 22:30 the previous
    day in UTC. With no usable offset, the timestamp's own offset is used (UTC
    for "Z" or no offset). Returns "" for an empty timestamp; if it can't be parsed, its
    first 10 characters.
    """
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        logger.warning("Could not parse WHOOP timestamp: %s", timestamp)
        return timestamp[:10] if len(timestamp) >= 10 else ""
    if dt.tzinfo is None:  # WHOOP times are UTC; never read a bare time as this machine's zone
        dt = dt.replace(tzinfo=timezone.utc)
    if timezone_offset:
        try:
            dt = dt.astimezone(datetime.strptime(timezone_offset, "%z").tzinfo)
        except ValueError:
            logger.warning("Could not parse WHOOP timezone offset %r — using the timestamp's own", timezone_offset)
    return dt.date().isoformat()
