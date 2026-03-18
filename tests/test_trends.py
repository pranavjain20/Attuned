"""Tests for intelligence/trends.py — 7-day slopes and consecutive-day detection."""

import math

import pytest

from db.queries import upsert_whoop_recovery
from intelligence.trends import (
    compute_hrv_trend,
    compute_rhr_trend,
    is_hrv_declining,
    is_rhr_rising,
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


def _generate_dates(end_date, count):
    """Generate a list of YYYY-MM-DD dates ending at end_date (inclusive)."""
    from datetime import datetime, timedelta
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [(end - timedelta(days=count - 1 - i)).strftime("%Y-%m-%d") for i in range(count)]


# ─── HRV Trend ────────────────────────────────────────────────────────────────


class TestComputeHrvTrend:
    def test_happy_path(self, db_conn):
        dates = _generate_dates("2026-03-17", 7)
        hrv_values = [50.0, 52.0, 54.0, 56.0, 58.0, 60.0, 62.0]
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_trend(db_conn, "2026-03-17")
        assert result is not None
        assert result["count"] == 7
        assert result["slope"] > 0  # increasing HRV

    def test_declining_slope(self, db_conn):
        dates = _generate_dates("2026-03-17", 7)
        hrv_values = [70.0, 65.0, 60.0, 55.0, 50.0, 45.0, 40.0]
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_trend(db_conn, "2026-03-17")
        assert result is not None
        assert result["slope"] < 0  # declining HRV

    def test_returns_none_below_3_days(self, db_conn):
        dates = _generate_dates("2026-03-17", 2)
        _insert_recoveries(db_conn, dates, [50.0, 55.0])

        result = compute_hrv_trend(db_conn, "2026-03-17")
        assert result is None

    def test_skips_null_ln_rmssd(self, db_conn):
        dates = _generate_dates("2026-03-17", 7)
        hrv_values = [50.0, None, 55.0, None, 60.0, None, 65.0]
        _insert_recoveries(db_conn, dates, hrv_values)

        result = compute_hrv_trend(db_conn, "2026-03-17")
        assert result is not None
        assert result["count"] == 4  # 3 Nones skipped

    def test_includes_today(self, db_conn):
        dates = _generate_dates("2026-03-17", 3)
        _insert_recoveries(db_conn, dates, [50.0, 55.0, 60.0])

        result = compute_hrv_trend(db_conn, "2026-03-17")
        assert result is not None
        assert result["count"] == 3

    def test_empty_db(self, db_conn):
        result = compute_hrv_trend(db_conn, "2026-03-17")
        assert result is None


# ─── RHR Trend ────────────────────────────────────────────────────────────────


class TestComputeRhrTrend:
    def test_happy_path(self, db_conn):
        dates = _generate_dates("2026-03-17", 5)
        rhr_values = [58.0, 59.0, 60.0, 61.0, 62.0]
        _insert_recoveries(db_conn, dates, [50.0] * 5, rhr_values)

        result = compute_rhr_trend(db_conn, "2026-03-17")
        assert result is not None
        assert result["slope"] > 0  # rising RHR

    def test_returns_none_below_3_days(self, db_conn):
        dates = _generate_dates("2026-03-17", 2)
        _insert_recoveries(db_conn, dates, [50.0] * 2, [60.0, 62.0])

        result = compute_rhr_trend(db_conn, "2026-03-17")
        assert result is None

    def test_skips_null_rhr(self, db_conn):
        dates = _generate_dates("2026-03-17", 5)
        rhr_values = [60.0, None, 62.0, None, 64.0]
        _insert_recoveries(db_conn, dates, [50.0] * 5, rhr_values)

        result = compute_rhr_trend(db_conn, "2026-03-17")
        assert result is not None
        assert result["count"] == 3

    def test_declining_slope(self, db_conn):
        dates = _generate_dates("2026-03-17", 5)
        rhr_values = [65.0, 63.0, 61.0, 59.0, 57.0]
        _insert_recoveries(db_conn, dates, [50.0] * 5, rhr_values)

        result = compute_rhr_trend(db_conn, "2026-03-17")
        assert result["slope"] < 0

    def test_empty_db(self, db_conn):
        result = compute_rhr_trend(db_conn, "2026-03-17")
        assert result is None


# ─── is_hrv_declining ─────────────────────────────────────────────────────────


class TestIsHrvDeclining:
    def test_declining_3_consecutive_days(self):
        baseline = {"mean": 4.0, "sd": 0.2}
        # Threshold = 4.0 - 1.0*0.2 = 3.8
        trend = {"values": [4.1, 4.0, 3.7, 3.6, 3.5]}  # last 3 below
        result = is_hrv_declining(trend, baseline)
        assert result["declining"] is True
        assert result["consecutive_days_below"] == 3
        assert abs(result["threshold"] - 3.8) < 0.001

    def test_not_declining_interrupted(self):
        baseline = {"mean": 4.0, "sd": 0.2}
        trend = {"values": [3.7, 3.6, 4.1, 3.5, 3.4]}  # gap at idx 2
        result = is_hrv_declining(trend, baseline)
        assert result["declining"] is False
        assert result["consecutive_days_below"] == 2

    def test_not_declining_above_threshold(self):
        baseline = {"mean": 4.0, "sd": 0.2}
        trend = {"values": [3.9, 3.9, 3.9, 3.9, 3.9]}  # all above 3.8
        result = is_hrv_declining(trend, baseline)
        assert result["declining"] is False
        assert result["consecutive_days_below"] == 0

    def test_sd_zero_any_value_below_mean_triggers(self):
        baseline = {"mean": 4.0, "sd": 0.0}
        # Threshold = 4.0; values below 4.0 count
        trend = {"values": [3.9, 3.9, 3.9]}
        result = is_hrv_declining(trend, baseline)
        assert result["declining"] is True

    def test_exactly_at_threshold_not_below(self):
        baseline = {"mean": 4.0, "sd": 0.2}
        # Threshold = 3.8; value exactly at 3.8 is NOT < 3.8
        trend = {"values": [3.8, 3.8, 3.8]}
        result = is_hrv_declining(trend, baseline)
        assert result["declining"] is False
        assert result["consecutive_days_below"] == 0


# ─── is_rhr_rising ────────────────────────────────────────────────────────────


class TestIsRhrRising:
    def test_rising_3_consecutive_days(self):
        baseline = {"mean": 58.0}
        # Threshold = 58 + 5 = 63
        trend = {"values": [60.0, 64.0, 65.0, 66.0]}
        result = is_rhr_rising(trend, baseline)
        assert result["rising"] is True
        assert result["consecutive_days_above"] == 3
        assert abs(result["threshold"] - 63.0) < 0.001

    def test_not_rising_interrupted(self):
        baseline = {"mean": 58.0}
        trend = {"values": [64.0, 65.0, 60.0, 64.0, 65.0]}
        result = is_rhr_rising(trend, baseline)
        assert result["rising"] is False
        assert result["consecutive_days_above"] == 2

    def test_not_rising_all_below_threshold(self):
        baseline = {"mean": 58.0}
        trend = {"values": [60.0, 61.0, 62.0, 63.0]}  # at/below 63
        result = is_rhr_rising(trend, baseline)
        assert result["rising"] is False

    def test_exactly_at_threshold_not_above(self):
        baseline = {"mean": 58.0}
        # Threshold = 63; exactly 63 is NOT > 63
        trend = {"values": [63.0, 63.0, 63.0]}
        result = is_rhr_rising(trend, baseline)
        assert result["rising"] is False
        assert result["consecutive_days_above"] == 0

    def test_all_above_threshold(self):
        baseline = {"mean": 58.0}
        trend = {"values": [64.0, 65.0, 66.0, 67.0, 68.0]}
        result = is_rhr_rising(trend, baseline)
        assert result["rising"] is True
        assert result["consecutive_days_above"] == 5


# ─── Integration: DB → Trend → Decline Chain ─────────────────────────────────


class TestTrendDeclineIntegration:
    def test_db_to_hrv_decline_chain(self, db_conn):
        """Full chain: insert DB data → compute_hrv_trend → is_hrv_declining."""
        dates = _generate_dates("2026-03-17", 7)
        # HRV declining over 7 days
        hrv_values = [60.0, 55.0, 50.0, 45.0, 40.0, 35.0, 30.0]
        _insert_recoveries(db_conn, dates, hrv_values)

        trend = compute_hrv_trend(db_conn, "2026-03-17")
        assert trend is not None

        # Baseline with higher mean
        baseline = {"mean": 4.0, "sd": 0.1}
        result = is_hrv_declining(trend, baseline)
        # All ln values are below 4.0 - 0.1 = 3.9 (ln(30)≈3.4, ln(60)≈4.1)
        # At least the last few should be below threshold
        assert result["consecutive_days_below"] >= 3

    def test_db_to_rhr_rise_chain(self, db_conn):
        """Full chain: insert DB data → compute_rhr_trend → is_rhr_rising."""
        dates = _generate_dates("2026-03-17", 5)
        rhr_values = [58.0, 60.0, 64.0, 66.0, 68.0]
        _insert_recoveries(db_conn, dates, [50.0] * 5, rhr_values)

        trend = compute_rhr_trend(db_conn, "2026-03-17")
        assert trend is not None

        baseline = {"mean": 58.0}
        result = is_rhr_rising(trend, baseline)
        # Threshold = 58 + 5 = 63. Last 3 values (64, 66, 68) are above.
        assert result["rising"] is True
        assert result["consecutive_days_above"] == 3
