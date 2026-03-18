"""Tests for intelligence/sleep_analysis.py — sleep architecture analysis."""

import pytest

from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from intelligence.sleep_analysis import analyze_sleep


def _generate_dates(end_date, count):
    """Generate dates ending the day before end_date (for baseline window)."""
    from datetime import datetime, timedelta
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [(end - timedelta(days=count - i)).strftime("%Y-%m-%d") for i in range(count)]


def _seed_baseline(conn, target_date, deep_ms=5_400_000, rem_ms=7_200_000,
                   light_ms=14_400_000, days=20):
    """Seed enough sleep+recovery data to build baselines."""
    dates = _generate_dates(target_date, days)
    for i, date in enumerate(dates):
        upsert_whoop_recovery(
            conn, cycle_id=i + 1, date=date,
            recovery_score=70.0, hrv_rmssd_milli=50.0, resting_heart_rate=60.0,
        )
        upsert_whoop_sleep(
            conn, sleep_id=i + 100, date=date,
            deep_sleep_ms=deep_ms, rem_sleep_ms=rem_ms,
            light_sleep_ms=light_ms,
            sleep_needed_baseline_ms=28_800_000,
        )


def _insert_today_sleep(conn, date, deep_ms, rem_ms, light_ms, **kwargs):
    """Insert sleep for the target date."""
    upsert_whoop_sleep(
        conn, sleep_id=999, date=date,
        deep_sleep_ms=deep_ms, rem_sleep_ms=rem_ms,
        light_sleep_ms=light_ms, **kwargs,
    )


class TestAnalyzeSleep:
    def test_no_deficits(self, db_conn):
        """Normal sleep matching baselines → no deficits, both adequate."""
        _seed_baseline(db_conn, "2026-03-17")
        _insert_today_sleep(db_conn, "2026-03-17", 5_400_000, 7_200_000, 14_400_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result is not None
        assert result["deep_sleep_deficit"] is False
        assert result["rem_sleep_deficit"] is False
        assert result["deep_adequate"] is True
        assert result["rem_adequate"] is True

    def test_deep_deficit_by_sd(self, db_conn):
        """Deep sleep far below baseline mean → deficit."""
        _seed_baseline(db_conn, "2026-03-17", deep_ms=5_400_000)
        # Deep way below baseline (baseline mean=5.4M, give only 2M)
        _insert_today_sleep(db_conn, "2026-03-17", 2_000_000, 7_200_000, 14_400_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["deep_sleep_deficit"] is True
        assert result["deep_adequate"] is False

    def test_deep_deficit_by_ratio(self, db_conn):
        """Deep sleep <10% of total → deficit by ratio."""
        _seed_baseline(db_conn, "2026-03-17", deep_ms=5_400_000)
        # Deep = 2M out of total 30M = 6.7% < 10%
        _insert_today_sleep(db_conn, "2026-03-17", 2_000_000, 10_000_000, 18_000_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["deep_sleep_deficit"] is True

    def test_deep_deficit_by_absolute(self, db_conn):
        """Deep sleep <1 hour → deficit by absolute floor."""
        _seed_baseline(db_conn, "2026-03-17", deep_ms=5_400_000)
        # Deep = 3M ms = 50 min < 1 hour, but ratio may be OK
        _insert_today_sleep(db_conn, "2026-03-17", 3_000_000, 7_200_000, 7_800_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["deep_sleep_deficit"] is True

    def test_rem_deficit_by_sd(self, db_conn):
        """REM sleep far below baseline → deficit."""
        _seed_baseline(db_conn, "2026-03-17", rem_ms=7_200_000)
        _insert_today_sleep(db_conn, "2026-03-17", 5_400_000, 2_000_000, 14_400_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["rem_sleep_deficit"] is True
        assert result["rem_adequate"] is False

    def test_rem_deficit_by_ratio(self, db_conn):
        """REM <15% of total → deficit by ratio."""
        _seed_baseline(db_conn, "2026-03-17", rem_ms=7_200_000)
        # REM = 3M out of 30M = 10% < 15%
        _insert_today_sleep(db_conn, "2026-03-17", 9_000_000, 3_000_000, 18_000_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["rem_sleep_deficit"] is True

    def test_adequate_within_1sd(self, db_conn):
        """Sleep slightly below mean but within 1 SD → adequate."""
        # Baseline: deep=5.4M with SD~0 (all identical). 1SD below = 5.4M
        # So we need variation. Use varied baseline.
        dates = _generate_dates("2026-03-17", 15)
        for i, date in enumerate(dates):
            upsert_whoop_recovery(
                db_conn, cycle_id=i + 1, date=date,
                recovery_score=70.0, hrv_rmssd_milli=50.0, resting_heart_rate=60.0,
            )
            # Vary deep: mean ~5.4M, SD ~500K
            deep = 5_400_000 + (300_000 if i % 2 == 0 else -300_000)
            upsert_whoop_sleep(
                db_conn, sleep_id=i + 100, date=date,
                deep_sleep_ms=deep, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=28_800_000,
            )

        # Sleep slightly below mean but within 1 SD
        _insert_today_sleep(db_conn, "2026-03-17", 5_200_000, 7_200_000, 14_400_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["deep_sleep_deficit"] is False
        assert result["deep_adequate"] is True

    def test_both_deficits(self, db_conn):
        """Both deep and REM below thresholds."""
        _seed_baseline(db_conn, "2026-03-17")
        _insert_today_sleep(db_conn, "2026-03-17", 2_000_000, 2_000_000, 20_000_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["deep_sleep_deficit"] is True
        assert result["rem_sleep_deficit"] is True

    def test_no_sleep_data(self, db_conn):
        """No sleep record for date → None."""
        result = analyze_sleep(db_conn, "2026-03-17")
        assert result is None

    def test_insufficient_baseline_uses_absolute_thresholds(self, db_conn):
        """<14 days of history → only absolute thresholds."""
        # Only 5 days of baseline — not enough
        dates = _generate_dates("2026-03-17", 5)
        for i, date in enumerate(dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=i + 100, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
            )
        # Good sleep today → no deficits by absolute thresholds
        _insert_today_sleep(db_conn, "2026-03-17", 5_400_000, 7_200_000, 14_400_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result is not None
        assert result["insufficient_baseline"] is True
        assert result["deep_sleep_deficit"] is False
        assert result["rem_sleep_deficit"] is False

    def test_insufficient_baseline_detects_absolute_deficit(self, db_conn):
        """Insufficient baseline but deep <1h → still catches deficit."""
        _insert_today_sleep(db_conn, "2026-03-17", 3_000_000, 7_200_000, 14_400_000)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["insufficient_baseline"] is True
        assert result["deep_sleep_deficit"] is True

    def test_zero_total_sleep(self, db_conn):
        """All stages = 0 → both deficits."""
        _seed_baseline(db_conn, "2026-03-17")
        _insert_today_sleep(db_conn, "2026-03-17", 0, 0, 0)

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["deep_sleep_deficit"] is True
        assert result["rem_sleep_deficit"] is True
        assert result["deep_adequate"] is False
        assert result["rem_adequate"] is False

    def test_null_stages(self, db_conn):
        """Null stage data → no crash, handled gracefully."""
        upsert_whoop_sleep(
            db_conn, sleep_id=999, date="2026-03-17",
            deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None,
        )

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result is not None
        assert result["insufficient_baseline"] is True

    def test_aggregates_multiple_sleep_records(self, db_conn):
        """Primary sleep + nap on same date → stages summed before analysis."""
        _seed_baseline(db_conn, "2026-03-17", deep_ms=5_400_000, rem_ms=7_200_000,
                       light_ms=14_400_000)

        # Primary sleep: low deep (would be deficit alone)
        upsert_whoop_sleep(
            db_conn, sleep_id=999, date="2026-03-17",
            deep_sleep_ms=3_000_000, rem_sleep_ms=6_000_000,
            light_sleep_ms=12_000_000,
        )
        # Nap: adds deep sleep, pushing total above deficit threshold
        upsert_whoop_sleep(
            db_conn, sleep_id=998, date="2026-03-17",
            deep_sleep_ms=3_000_000, rem_sleep_ms=1_200_000,
            light_sleep_ms=2_400_000,
        )

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result is not None
        # Aggregated: deep=6M, rem=7.2M, light=14.4M — healthy, no deficits
        assert result["last_night"]["deep_sleep_ms"] == 6_000_000
        assert result["last_night"]["rem_sleep_ms"] == 7_200_000
        assert result["deep_sleep_deficit"] is False
        assert result["rem_sleep_deficit"] is False
