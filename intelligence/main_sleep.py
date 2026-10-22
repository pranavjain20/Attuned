"""Which WHOOP sleep record counts as "last night".

WHOOP stores each sleep as its own record and flags naps (`nap` = 1). One date
can hold the night plus naps, and sometimes two non-nap records. Only the night
says how you slept last night: a nap adds deep sleep a night can't and usually
has near-perfect efficiency, so mixing it in makes a nap day look like a great
night.

Rules:
- Naps (`nap` = 1) are dropped.
- `nap` = NULL (rows synced before the flag was stored) counts as main sleep.
- If several non-nap records share a date, the longest one (most time asleep)
  is last night. Records are never added together: when sleep dates still
  came from the UTC end time, every such date in this history was two separate
  nights landing on one date, and summing them invented an 11-hour night.
  Dates are now the wearer's local date, but the rule stays: picking one can
  at worst undercount a genuinely split night; it can never invent sleep.
"""

from config import RESTORATIVE_SLEEP_TOTAL_MIN_MS

STAGE_KEYS = ("deep_sleep_ms", "rem_sleep_ms", "light_sleep_ms")


def is_nap(record: dict) -> bool:
    """True only when WHOOP explicitly flagged the record as a nap."""
    return record.get("nap") == 1


def asleep_ms(record: dict) -> int | None:
    """Total time asleep (deep + REM + light), or None if any stage is missing."""
    stages = [record.get(key) for key in STAGE_KEYS]
    if None in stages:
        return None
    return sum(stages)


def is_short_night(record: dict | None) -> bool:
    """True when the night had less than RESTORATIVE_SLEEP_TOTAL_MIN_MS (6 h) asleep.

    False when there is no night or its stages are missing: length unknown.
    """
    total = asleep_ms(record) if record else None
    return total is not None and total < RESTORATIVE_SLEEP_TOTAL_MIN_MS


def select_main_sleep(records: list[dict]) -> dict | None:
    """Return a copy of one date's main sleep record, or None if there is none.

    Longest non-nap record wins; records with stage data beat ones without.
    Ties keep the earlier record in `records`.
    """
    main = [r for r in records if not is_nap(r)]
    if not main:
        return None
    longest = max(main, key=lambda r: (asleep_ms(r) is not None, asleep_ms(r) or 0))
    return dict(longest)


def main_sleep_by_date(records: list[dict]) -> dict[str, dict]:
    """Group records by date and select each date's main sleep. Nap-only dates are left out."""
    by_date: dict[str, list[dict]] = {}
    for r in records:
        by_date.setdefault(r["date"], []).append(r)
    selected = {date: select_main_sleep(recs) for date, recs in by_date.items()}
    return {date: s for date, s in selected.items() if s is not None}
