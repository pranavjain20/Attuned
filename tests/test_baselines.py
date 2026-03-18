"""Tests for intelligence/baselines.py — personal baseline computations."""

import math

import pytest

from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from intelligence.baselines import (
    compute_hrv_baseline,
    compute_rhr_baseline,
    compute_sleep_debt,
    compute_sleep_debt_baseline,
    compute_sleep_stage_baselines,
)


def _insert_recoveries(conn, dates, hrv_values, rhr_values=None):
    """Helper to insert recovery records for given dates."""
    if rhr_values is None:
        rhr_values = [60.0] * len(dates)
    for i, (date, hrv) in enumerate(zip(dates, hrv_values)):
        upsert_whoop_recovery(
            conn, cycle_id=i + 1, date=date,
            recovery_score=70.0, hrv_rmssd_milli=hrv,
            resting_heart_rate=rhr_values[i],
        )


def _insert_sleeps(conn, dates, deep_ms, rem_ms, light_ms,
                   baseline_ms=None, debt_ms=None, strain_ms=None):
    """Helper to insert sleep records for given dates."""
    for i, date in enumerate(dates):
        upsert_whoop_sleep(
            conn, sleep_id=i + 100, date=date,
            deep_sleep_ms=deep_ms[i] if deep_ms else None,
            rem_sleep_ms=rem_ms[i] if rem_ms else None,
            light_sleep_ms=light_ms[i] if light_ms else None,
            sleep_needed_baseline_ms=baseline_ms[i] if baseline_ms else None,
            sleep_needed_debt_ms=debt_ms[i] if debt_ms else None,
            sleep_needed_strain_ms=strain_ms[i] if strain_ms else None,
        )


def _generate_dates(end_date, count):
    """Generate a list of YYYY-MM-DD dates ending at end_date (exclusive)."""
    from datetime import datetime, timedelta
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [(end - timedelta(days=count - i)).strftime("%Y-%m-%d") for i in range(count)]


# ─── HRV Baseline ────────────────────────────────────────────────────────────


class TestComputeHrvBaseline:
    def test_happy_path(self, db_conn):
        dates = _generate_dates("2026-03-17", 20)
        hrv_values = [50.0 + i for i in range(20)]
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 20
        # Verify it uses ln_rmssd (log values)
        expected_values = [math.log(50.0 + i) for i in range(20)]
        assert len(result["values"]) == 20
        for actual, expected in zip(result["values"], expected_values):
            assert abs(actual - expected) < 0.001

    def test_excludes_today(self, db_conn):
        dates = _generate_dates("2026-03-17", 15) + ["2026-03-17"]
        hrv_values = [50.0] * 15 + [999.0]
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        # The 999.0 value for today should NOT be in the values
        assert all(abs(v - math.log(50.0)) < 0.001 for v in result["values"])

    def test_returns_none_below_min_days(self, db_conn):
        dates = _generate_dates("2026-03-17", 10)
        _insert_recoveries(db_conn, dates, [50.0] * 10)

        result = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert result is None

    def test_skips_null_ln_rmssd(self, db_conn):
        dates = _generate_dates("2026-03-17", 20)
        hrv_values = [50.0] * 15 + [None] * 5
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 15

    def test_custom_window(self, db_conn):
        # Insert 25 days of data
        dates = _generate_dates("2026-03-17", 25)
        _insert_recoveries(db_conn, dates, [50.0] * 25)

        # 30-day window gets all 25 days
        full = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert full is not None
        assert full["count"] == 25

        # 20-day window gets fewer days
        narrow = compute_hrv_baseline(db_conn, "2026-03-17", window=20)
        assert narrow is not None
        assert narrow["count"] < full["count"]
        assert narrow["count"] <= 20

    def test_cv_correctness(self, db_conn):
        dates = _generate_dates("2026-03-17", 15)
        _insert_recoveries(db_conn, dates, [50.0] * 15)

        result = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        # All identical values → SD = 0, CV = 0
        assert result["sd"] == 0.0
        assert result["cv"] == 0.0

    def test_cv_with_variation(self, db_conn):
        dates = _generate_dates("2026-03-17", 15)
        hrv_values = [40.0, 50.0, 60.0] * 5
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["cv"] > 0
        assert abs(result["cv"] - result["sd"] / result["mean"]) < 0.0001

    def test_empty_db(self, db_conn):
        result = compute_hrv_baseline(db_conn, "2026-03-17")
        assert result is None


# ─── RHR Baseline ─────────────────────────────────────────────────────────────


class TestComputeRhrBaseline:
    def test_happy_path(self, db_conn):
        dates = _generate_dates("2026-03-17", 20)
        rhr_values = [58.0 + (i % 5) for i in range(20)]
        _insert_recoveries(db_conn, dates, [50.0] * 20, rhr_values)

        result = compute_rhr_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 20
        assert result["mean"] > 0
        assert result["sd"] >= 0

    def test_returns_none_below_min_days(self, db_conn):
        dates = _generate_dates("2026-03-17", 10)
        _insert_recoveries(db_conn, dates, [50.0] * 10, [60.0] * 10)

        result = compute_rhr_baseline(db_conn, "2026-03-17", window=30)
        assert result is None

    def test_skips_null_rhr(self, db_conn):
        dates = _generate_dates("2026-03-17", 20)
        rhr_values = [60.0] * 15 + [None] * 5
        _insert_recoveries(db_conn, dates, [50.0] * 20, rhr_values)

        result = compute_rhr_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 15

    def test_excludes_today(self, db_conn):
        dates = _generate_dates("2026-03-17", 15) + ["2026-03-17"]
        rhr_values = [60.0] * 15 + [999.0]
        _insert_recoveries(db_conn, dates, [50.0] * 16, rhr_values)

        result = compute_rhr_baseline(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert abs(result["mean"] - 60.0) < 0.001

    def test_empty_db(self, db_conn):
        result = compute_rhr_baseline(db_conn, "2026-03-17")
        assert result is None

    def test_identical_values_sd_zero(self, db_conn):
        dates = _generate_dates("2026-03-17", 15)
        _insert_recoveries(db_conn, dates, [50.0] * 15, [60.0] * 15)

        result = compute_rhr_baseline(db_conn, "2026-03-17", window=30)
        assert result["sd"] == 0.0


# ─── Sleep Stage Baselines ────────────────────────────────────────────────────


class TestComputeSleepStageBaselines:
    def test_happy_path(self, db_conn):
        dates = _generate_dates("2026-03-17", 15)
        deep = [5_400_000] * 15
        rem = [7_200_000] * 15
        light = [14_400_000] * 15
        _insert_sleeps(db_conn, dates, deep, rem, light)

        result = compute_sleep_stage_baselines(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 15
        assert abs(result["deep_ms"]["mean"] - 5_400_000) < 1
        assert abs(result["rem_ms"]["mean"] - 7_200_000) < 1
        total = 5_400_000 + 7_200_000 + 14_400_000
        assert abs(result["deep_ratio"]["mean"] - 5_400_000 / total) < 0.001

    def test_returns_none_below_min_days(self, db_conn):
        dates = _generate_dates("2026-03-17", 10)
        _insert_sleeps(db_conn, dates, [5_000_000] * 10, [6_000_000] * 10, [14_000_000] * 10)

        result = compute_sleep_stage_baselines(db_conn, "2026-03-17", window=30)
        assert result is None

    def test_skips_null_stages(self, db_conn):
        dates = _generate_dates("2026-03-17", 20)
        deep = [5_000_000] * 15 + [None] * 5
        rem = [6_000_000] * 15 + [None] * 5
        light = [14_000_000] * 15 + [None] * 5
        _insert_sleeps(db_conn, dates, deep, rem, light)

        result = compute_sleep_stage_baselines(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 15

    def test_skips_zero_total_sleep(self, db_conn):
        dates = _generate_dates("2026-03-17", 16)
        deep = [5_000_000] * 15 + [0]
        rem = [6_000_000] * 15 + [0]
        light = [14_000_000] * 15 + [0]
        _insert_sleeps(db_conn, dates, deep, rem, light)

        result = compute_sleep_stage_baselines(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 15  # zero-total day skipped

    def test_ratios_computed_per_day(self, db_conn):
        dates = _generate_dates("2026-03-17", 15)
        # Day 1: deep=50%, Day 2: deep=10%, etc. — ratio mean != ratio of means
        deep = [10_000_000, 2_000_000] * 7 + [10_000_000]
        rem = [5_000_000, 10_000_000] * 7 + [5_000_000]
        light = [5_000_000, 8_000_000] * 7 + [5_000_000]
        _insert_sleeps(db_conn, dates, deep, rem, light)

        result = compute_sleep_stage_baselines(db_conn, "2026-03-17", window=30)
        assert result is not None
        # Verify ratios are per-day averaged (SD > 0 because ratios vary)
        assert result["deep_ratio"]["sd"] > 0

    def test_empty_db(self, db_conn):
        result = compute_sleep_stage_baselines(db_conn, "2026-03-17")
        assert result is None

    def test_multiple_sleep_records_per_date_aggregated(self, db_conn):
        """Nap + primary sleep on same date should sum stages."""
        dates = _generate_dates("2026-03-17", 15)
        for i, date in enumerate(dates):
            # Primary sleep
            upsert_whoop_sleep(
                db_conn, sleep_id=i + 100, date=date,
                deep_sleep_ms=4_000_000, rem_sleep_ms=5_000_000,
                light_sleep_ms=12_000_000,
            )
        # Add a nap on the most recent date (dates[-1])
        upsert_whoop_sleep(
            db_conn, sleep_id=999, date=dates[-1],
            deep_sleep_ms=1_000_000, rem_sleep_ms=500_000,
            light_sleep_ms=1_000_000,
        )

        result = compute_sleep_stage_baselines(db_conn, "2026-03-17", window=30)
        assert result is not None
        assert result["count"] == 15  # 15 unique dates, not 16 records
        # The nap date should have summed stages (5M deep, 5.5M rem, 13M light)
        # All other dates have 4M deep → mean should be slightly above 4M
        assert result["deep_ms"]["mean"] > 4_000_000


# ─── Sleep Debt ───────────────────────────────────────────────────────────────


class TestComputeSleepDebt:
    def test_happy_path(self, db_conn):
        dates = _generate_dates("2026-03-17", 7)
        # Need 8h, got 7h each day → 1h debt/day → 7h total
        needed_baseline = [28_800_000] * 7  # 8h
        actual_deep = [8_400_000] * 7      # 2h20m
        actual_rem = [7_200_000] * 7       # 2h
        actual_light = [9_600_000] * 7     # 2h40m = total 7h
        _insert_sleeps(db_conn, dates, actual_deep, actual_rem, actual_light,
                       baseline_ms=needed_baseline)

        result = compute_sleep_debt(db_conn, "2026-03-17", window=7)
        assert result is not None
        assert abs(result - 7.0) < 0.01

    def test_no_debt_when_enough_sleep(self, db_conn):
        dates = _generate_dates("2026-03-17", 7)
        # Need 8h, got 9h each day → 0 debt
        needed_baseline = [28_800_000] * 7
        deep = [10_800_000] * 7   # 3h
        rem = [10_800_000] * 7    # 3h
        light = [10_800_000] * 7  # 3h = 9h total
        _insert_sleeps(db_conn, dates, deep, rem, light,
                       baseline_ms=needed_baseline)

        result = compute_sleep_debt(db_conn, "2026-03-17", window=7)
        assert result == 0.0

    def test_skips_null_sleep_needed(self, db_conn):
        dates = _generate_dates("2026-03-17", 7)
        deep = [5_000_000] * 7
        rem = [6_000_000] * 7
        light = [14_000_000] * 7
        baseline = [28_800_000] * 5 + [None] * 2
        _insert_sleeps(db_conn, dates, deep, rem, light, baseline_ms=baseline)

        result = compute_sleep_debt(db_conn, "2026-03-17", window=7)
        assert result is not None
        # Only 5 valid days should contribute

    def test_includes_debt_and_strain_components(self, db_conn):
        dates = _generate_dates("2026-03-17", 3)
        # baseline=8h, debt=1h, strain=30m → needed=9.5h
        # actual=9h → daily debt = 0.5h → total = 1.5h
        deep = [10_800_000] * 3     # 3h
        rem = [10_800_000] * 3      # 3h
        light = [10_800_000] * 3    # 3h = 9h
        baseline = [28_800_000] * 3  # 8h
        debt = [3_600_000] * 3       # 1h
        strain = [1_800_000] * 3     # 30m
        _insert_sleeps(db_conn, dates, deep, rem, light,
                       baseline_ms=baseline, debt_ms=debt, strain_ms=strain)

        result = compute_sleep_debt(db_conn, "2026-03-17", window=7)
        assert result is not None
        assert abs(result - 1.5) < 0.01

    def test_returns_none_no_valid_days(self, db_conn):
        result = compute_sleep_debt(db_conn, "2026-03-17", window=7)
        assert result is None

    def test_handles_null_stage_values(self, db_conn):
        dates = _generate_dates("2026-03-17", 3)
        # Null stages treated as 0
        _insert_sleeps(db_conn, dates,
                       [None] * 3, [None] * 3, [None] * 3,
                       baseline_ms=[28_800_000] * 3)

        result = compute_sleep_debt(db_conn, "2026-03-17", window=7)
        assert result is not None
        # Full debt: 28800000ms * 3 / 3600000 = 24h
        assert abs(result - 24.0) < 0.01


# ─── Sleep Debt Baseline ────────────────────────────────────────────────────


class TestComputeSleepDebtBaseline:
    def _seed_consistent_sleep(self, conn, target_date, days=40,
                               needed_ms=28_800_000, actual_total_ms=25_200_000):
        """Seed sleep data producing consistent daily debt across many days.

        Each day: need `needed_ms`, get `actual_total_ms` → predictable debt.
        Need enough days so that each day in the 30-day window has a full 7-day
        rolling debt available.
        """
        from datetime import datetime, timedelta
        d = datetime.strptime(target_date, "%Y-%m-%d")
        for offset in range(1, days + 1):
            date = (d - timedelta(days=offset)).strftime("%Y-%m-%d")
            deep = actual_total_ms // 3
            rem = actual_total_ms // 3
            light = actual_total_ms - deep - rem
            upsert_whoop_sleep(
                conn, sleep_id=2000 + offset, date=date,
                deep_sleep_ms=deep, rem_sleep_ms=rem,
                light_sleep_ms=light,
                sleep_needed_baseline_ms=needed_ms,
            )

    def test_happy_path(self, db_conn):
        """Consistent 1h/day debt → debt baseline mean ≈ 7h, low SD."""
        # 28.8M needed, 25.2M actual = 3.6M = 1h debt/day → 7h rolling
        self._seed_consistent_sleep(db_conn, "2026-03-17", days=40,
                                    needed_ms=28_800_000, actual_total_ms=25_200_000)

        result = compute_sleep_debt_baseline(db_conn, "2026-03-17")
        assert result is not None
        assert result["count"] >= 14
        assert abs(result["mean"] - 7.0) < 0.5
        assert result["sd"] < 1.0  # consistent debt → low variance

    def test_returns_none_insufficient_data(self, db_conn):
        """Fewer than 14 valid debt values → None."""
        # Only 5 days of sleep data — not enough for 14 debt computations
        from datetime import datetime, timedelta
        d = datetime.strptime("2026-03-17", "%Y-%m-%d")
        for offset in range(1, 6):
            date = (d - timedelta(days=offset)).strftime("%Y-%m-%d")
            upsert_whoop_sleep(
                db_conn, sleep_id=2000 + offset, date=date,
                deep_sleep_ms=8_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=9_600_000,
                sleep_needed_baseline_ms=28_800_000,
            )

        result = compute_sleep_debt_baseline(db_conn, "2026-03-17")
        assert result is None

    def test_mean_and_sd_values_correct(self, db_conn):
        """Verify mean/SD math with known debt pattern."""
        # No debt at all: actual >= needed every day
        self._seed_consistent_sleep(db_conn, "2026-03-17", days=40,
                                    needed_ms=25_200_000, actual_total_ms=28_800_000)

        result = compute_sleep_debt_baseline(db_conn, "2026-03-17")
        assert result is not None
        assert result["mean"] == 0.0  # no debt
        assert result["sd"] == 0.0

    def test_excludes_target_date(self, db_conn):
        """Debt baseline should not include target date itself."""
        self._seed_consistent_sleep(db_conn, "2026-03-17", days=40,
                                    needed_ms=28_800_000, actual_total_ms=25_200_000)
        # Add extreme sleep on target date — should not affect baseline
        upsert_whoop_sleep(
            db_conn, sleep_id=9999, date="2026-03-17",
            deep_sleep_ms=0, rem_sleep_ms=0, light_sleep_ms=0,
            sleep_needed_baseline_ms=100_000_000,
        )

        result = compute_sleep_debt_baseline(db_conn, "2026-03-17")
        assert result is not None
        # Mean should still be ~7h, not affected by today's extreme
        assert abs(result["mean"] - 7.0) < 0.5

    def test_empty_db(self, db_conn):
        result = compute_sleep_debt_baseline(db_conn, "2026-03-17")
        assert result is None
