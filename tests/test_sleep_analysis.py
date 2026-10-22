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

    def test_unflagged_second_record_does_not_add_to_last_night(self, db_conn):
        """Two records with unknown nap flag → longest is last night; stages never summed."""
        _seed_baseline(db_conn, "2026-03-17", deep_ms=5_400_000, rem_ms=7_200_000,
                       light_ms=14_400_000)

        # Primary sleep: low deep (deficit on its own)
        upsert_whoop_sleep(
            db_conn, sleep_id=999, date="2026-03-17",
            deep_sleep_ms=3_000_000, rem_sleep_ms=6_000_000,
            light_sleep_ms=12_000_000,
        )
        # Shorter second record: used to be added in and hide the deficit
        upsert_whoop_sleep(
            db_conn, sleep_id=998, date="2026-03-17",
            deep_sleep_ms=3_000_000, rem_sleep_ms=1_200_000,
            light_sleep_ms=2_400_000,
        )

        result = analyze_sleep(db_conn, "2026-03-17")
        assert result is not None
        assert result["last_night"]["deep_sleep_ms"] == 3_000_000
        assert result["last_night"]["rem_sleep_ms"] == 6_000_000
        assert result["deep_sleep_deficit"] is True

class TestLastNightIsMainSleepOnly:
    """'Last night' = WHOOP's non-nap sleep(s); naps never leak into it."""

    def test_nap_listed_first_then_night_uses_night_only(self, db_conn):
        _seed_baseline(db_conn, "2026-03-17")
        # Nap inserted first (WHOOP lists newest first, so naps often come first)
        upsert_whoop_sleep(db_conn, sleep_id="nap", date="2026-03-17", nap=True,
                           deep_sleep_ms=1_800_000, rem_sleep_ms=600_000,
                           light_sleep_ms=1_200_000, sleep_efficiency=99.0,
                           sleep_performance=20.0)
        upsert_whoop_sleep(db_conn, sleep_id="night", date="2026-03-17", nap=False,
                           deep_sleep_ms=3_000_000, rem_sleep_ms=6_000_000,
                           light_sleep_ms=12_000_000, sleep_efficiency=82.0,
                           sleep_performance=40.0)

        last_night = analyze_sleep(db_conn, "2026-03-17")["last_night"]
        assert last_night["sleep_id"] == "night"
        assert last_night["deep_sleep_ms"] == 3_000_000
        assert last_night["sleep_efficiency"] == 82.0
        assert last_night["sleep_performance"] == 40.0

    def test_nap_cannot_hide_a_deep_sleep_deficit(self, db_conn):
        _seed_baseline(db_conn, "2026-03-17", deep_ms=5_400_000)
        upsert_whoop_sleep(db_conn, sleep_id="night", date="2026-03-17", nap=False,
                           deep_sleep_ms=2_000_000, rem_sleep_ms=7_200_000,
                           light_sleep_ms=14_400_000)
        upsert_whoop_sleep(db_conn, sleep_id="nap", date="2026-03-17", nap=True,
                           deep_sleep_ms=3_400_000, rem_sleep_ms=0, light_sleep_ms=1_000_000)
        assert analyze_sleep(db_conn, "2026-03-17")["deep_sleep_deficit"] is True

    def test_night_only(self, db_conn):
        _seed_baseline(db_conn, "2026-03-17")
        upsert_whoop_sleep(db_conn, sleep_id="night", date="2026-03-17", nap=False,
                           deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                           light_sleep_ms=14_400_000, sleep_efficiency=91.0)
        last_night = analyze_sleep(db_conn, "2026-03-17")["last_night"]
        assert last_night["sleep_efficiency"] == 91.0
        assert last_night["deep_sleep_ms"] == 5_400_000

    def test_nap_only_day_has_no_last_night(self, db_conn):
        """Only a nap recorded (strap off overnight, or no night sleep) → no analysis."""
        _seed_baseline(db_conn, "2026-03-17")
        upsert_whoop_sleep(db_conn, sleep_id="nap", date="2026-03-17", nap=True,
                           deep_sleep_ms=1_800_000, rem_sleep_ms=600_000,
                           light_sleep_ms=1_200_000)
        assert analyze_sleep(db_conn, "2026-03-17") is None

    def test_two_main_records_uses_longest(self, db_conn):
        """Two non-nap records on one date → the longer one is last night, not their sum."""
        _seed_baseline(db_conn, "2026-03-17")
        upsert_whoop_sleep(db_conn, sleep_id="short", date="2026-03-17", nap=False,
                           deep_sleep_ms=3_000_000, rem_sleep_ms=3_000_000,
                           light_sleep_ms=6_000_000, sleep_efficiency=100.0)
        upsert_whoop_sleep(db_conn, sleep_id="long", date="2026-03-17", nap=False,
                           deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                           light_sleep_ms=14_400_000, sleep_efficiency=83.3)
        last_night = analyze_sleep(db_conn, "2026-03-17")["last_night"]
        assert last_night["sleep_id"] == "long"
        assert last_night["deep_sleep_ms"] == 5_400_000
        assert last_night["sleep_efficiency"] == 83.3

    def test_night_with_null_stages_plus_nap(self, db_conn):
        """Night has no stage data; the nap's stages must not stand in for it."""
        upsert_whoop_sleep(db_conn, sleep_id="night", date="2026-03-17", nap=False,
                           deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None,
                           sleep_efficiency=85.0)
        upsert_whoop_sleep(db_conn, sleep_id="nap", date="2026-03-17", nap=True,
                           deep_sleep_ms=1_800_000, rem_sleep_ms=600_000,
                           light_sleep_ms=1_200_000)
        result = analyze_sleep(db_conn, "2026-03-17")
        assert result["insufficient_baseline"] is True
        assert result["last_night"]["sleep_id"] == "night"
        assert result["last_night"]["deep_sleep_ms"] is None
