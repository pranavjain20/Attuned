"""Tests for intelligence/state_classifier.py — recovery-first, 5-tier system."""

import pytest

from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from intelligence.state_classifier import classify_state


def _generate_dates(end_date, count):
    """Generate dates ending the day before end_date (for baseline window)."""
    from datetime import datetime, timedelta
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [(end - timedelta(days=count - i)).strftime("%Y-%m-%d") for i in range(count)]


def _generate_dates_inclusive(end_date, count):
    """Generate dates ending on end_date (inclusive, for trend window)."""
    from datetime import datetime, timedelta
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [(end - timedelta(days=count - 1 - i)).strftime("%Y-%m-%d") for i in range(count)]


TARGET = "2026-03-17"


def _seed_healthy_baseline(conn, hrv_milli=55.0, rhr=58.0,
                           deep_ms=5_400_000, rem_ms=7_200_000,
                           light_ms=14_400_000, days=20, skip_last_n=0,
                           recovery_score=75.0, sleep_needed_ms=27_000_000):
    """Seed baseline data before TARGET date.

    skip_last_n: skip the N days closest to TARGET to avoid overlap with trend data.
    """
    dates = _generate_dates(TARGET, days + skip_last_n)[:days]
    for i, date in enumerate(dates):
        upsert_whoop_recovery(
            conn, cycle_id=i + 1, date=date,
            recovery_score=recovery_score, hrv_rmssd_milli=hrv_milli,
            resting_heart_rate=rhr,
        )
        upsert_whoop_sleep(
            conn, sleep_id=i + 100, date=date,
            deep_sleep_ms=deep_ms, rem_sleep_ms=rem_ms,
            light_sleep_ms=light_ms,
            sleep_needed_baseline_ms=sleep_needed_ms,
        )


def _seed_trend_days(conn, dates, hrv_values, rhr_values, recovery_scores=None,
                     start_cycle_id=500):
    """Seed recovery records for trend days (including today)."""
    if recovery_scores is None:
        recovery_scores = [70.0] * len(dates)
    for i, (date, hrv, rhr, score) in enumerate(
        zip(dates, hrv_values, rhr_values, recovery_scores)
    ):
        upsert_whoop_recovery(
            conn, cycle_id=start_cycle_id + i, date=date,
            recovery_score=score, hrv_rmssd_milli=hrv,
            resting_heart_rate=rhr,
        )


def _seed_today_sleep(conn, deep_ms=5_400_000, rem_ms=7_200_000,
                      light_ms=14_400_000, sleep_needed_baseline_ms=27_000_000):
    """Seed sleep for TARGET date."""
    upsert_whoop_sleep(
        conn, sleep_id=999, date=TARGET,
        deep_sleep_ms=deep_ms, rem_sleep_ms=rem_ms,
        light_sleep_ms=light_ms,
        sleep_needed_baseline_ms=sleep_needed_baseline_ms,
    )


def _seed_recent_days(conn, dates, recovery_scores, start_cycle_id=800):
    """Seed recovery + sleep for recent days (for fatigue lookback window)."""
    for i, (date, score) in enumerate(zip(dates, recovery_scores)):
        upsert_whoop_recovery(
            conn, cycle_id=start_cycle_id + i, date=date,
            recovery_score=score, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        upsert_whoop_sleep(
            conn, sleep_id=start_cycle_id + i, date=date,
            deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
            light_sleep_ms=14_400_000,
            sleep_needed_baseline_ms=27_000_000,
        )


# ─── Insufficient Data ───────────────────────────────────────────────────────


class TestInsufficientData:
    def test_no_data_at_all(self, db_conn):
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "insufficient_data"
        assert result["insufficient_data"] is True
        assert result["confidence"] == "low"

    def test_fewer_than_14_days(self, db_conn):
        dates = _generate_dates(TARGET, 10)
        for i, date in enumerate(dates):
            upsert_whoop_recovery(
                db_conn, cycle_id=i + 1, date=date,
                recovery_score=70.0, hrv_rmssd_milli=50.0, resting_heart_rate=60.0,
            )
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "insufficient_data"


# ─── Accumulated Fatigue ─────────────────────────────────────────────────────


class TestAccumulatedFatigue:
    def test_recovery_below_60_with_3_of_5_recent_bad_triggers(self, db_conn):
        """Today < 60 + 3 of last 5 days < 60 → accumulated_fatigue."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        # Seed 7 trend days for HRV trend computation
        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0, 75.0, 45.0, 50.0, 55.0, 45.0, 50.0]
        # Last 5 days before today: scores[1..5] = [75, 45, 50, 55, 45]
        # That's 3 below 60. Today = 50 (below 60).
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_today_green_recent_bad_does_not_trigger(self, db_conn):
        """Today recovery ≥ 60 → NOT fatigue, even if recent days bad."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # Recent 5 days all bad, but today = 70 (above 60)
        scores = [75.0, 40.0, 45.0, 50.0, 40.0, 45.0, 70.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "accumulated_fatigue"

    def test_today_bad_recent_good_does_not_trigger(self, db_conn):
        """Today < 60 but only 1 of last 5 also bad → NOT fatigue."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # Only 1 of last 5 days bad (index 2), today bad
        scores = [75.0, 75.0, 45.0, 75.0, 75.0, 75.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "accumulated_fatigue"

    def test_4_of_5_recent_bad_high_confidence(self, db_conn):
        """4+ of 5 recent bad → high confidence."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0, 75.0, 40.0, 45.0, 50.0, 55.0, 45.0]
        # Last 5: [75, 40, 45, 50, 55] = 4 below 60. Today = 45 < 60.
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"
        assert result["confidence"] == "high"

    def test_gray_zone_2_of_5_does_not_trigger(self, db_conn):
        """Today < 60 but only 2 of last 5 bad → gray zone, NOT fatigue."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0, 75.0, 45.0, 50.0, 75.0, 75.0, 50.0]
        # Last 5: [75, 45, 50, 75, 75] = 2 below 60. Today = 50 < 60.
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "accumulated_fatigue"


# ─── Poor Sleep ──────────────────────────────────────────────────────────────


class TestPoorSleep:
    def test_both_deficits_triggers_poor_sleep(self, db_conn):
        """Both deep and REM deficit → poor_sleep."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=2_000_000, light_ms=20_000_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_sleep"

    def test_poor_sleep_at_green_recovery(self, db_conn):
        """Poor sleep detected even at high recovery — sleep deficits override recovery level."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=85.0, hrv_rmssd_milli=60.0, resting_heart_rate=55.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=2_000_000, light_ms=20_000_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_sleep"

    def test_one_deficit_does_not_trigger_poor_sleep(self, db_conn):
        """Only deep deficit (not REM) → NOT poor_sleep."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "poor_sleep"

    def test_fatigue_overrides_poor_sleep(self, db_conn):
        """When fatigue conditions met + both sleep deficit, fatigue wins (P1 > P2)."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # 3 of last 5 bad + today bad
        scores = [75.0, 75.0, 45.0, 50.0, 55.0, 45.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=2_000_000, rem_sleep_ms=2_000_000,
                light_sleep_ms=20_000_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"


# ─── Physical Recovery Deficit ────────────────────────────────────────────────


class TestPhysicalRecoveryDeficit:
    def test_deep_deficit_rem_not_deficit(self, db_conn):
        """Deep sleep deficit + REM not deficit → physical recovery deficit."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "physical_recovery_deficit"

    def test_not_triggered_when_rem_also_deficit(self, db_conn):
        """Both deep and REM deficit → NOT physical deficit (→ poor_sleep)."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=2_000_000, light_ms=20_000_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "physical_recovery_deficit"


# ─── Emotional Processing Deficit ────────────────────────────────────────────


class TestEmotionalProcessingDeficit:
    def test_rem_deficit_deep_not_deficit(self, db_conn):
        """REM deficit + deep not deficit → emotional processing deficit."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=5_400_000, rem_ms=2_000_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "emotional_processing_deficit"

    def test_not_triggered_when_deep_also_deficit(self, db_conn):
        """Both stages deficit → NOT emotional deficit (→ poor_sleep)."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=2_000_000, light_ms=20_000_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "emotional_processing_deficit"


# ─── Poor Recovery ─────────────────────────────────────────────────────────


class TestPoorRecovery:
    def test_acute_bad_day_tier_1_2_triggers(self, db_conn):
        """Recovery < 40 (tier 1-2) → poor_recovery regardless of recent history."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [25.0]  # Today: 25% (tier 1)
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_recovery"

    def test_mild_bad_day_one_off_triggers(self, db_conn):
        """Recovery 40-59 with ≤1 recent bad day → poor_recovery."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # Only 1 of last 5 days bad (index 2), today = 55
        scores = [75.0, 75.0, 45.0, 75.0, 75.0, 75.0, 55.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_recovery"

    def test_tier_3_chronic_gray_zone_does_not_trigger(self, db_conn):
        """Recovery < 60 but 2 of last 5 also bad → gray zone, NOT poor_recovery."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # 2 of last 5 bad → gray zone (not fatigue, not one-off)
        scores = [75.0, 75.0, 45.0, 50.0, 75.0, 75.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "poor_recovery"

    def test_sleep_deficit_overrides_acute_bad_day(self, db_conn):
        """Recovery < 40 + deep sleep deficit → physical_recovery_deficit (P3 > P5)."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [30.0]  # Today acute bad
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates[:-1]):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )
        # Today: deep deficit, REM fine
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "physical_recovery_deficit"


# ─── Peak Readiness ──────────────────────────────────────────────────────────


class TestPeakReadiness:
    def test_all_green_tier_5(self, db_conn):
        """Recovery ≥ 80 + all conditions → peak_readiness."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]  # rising
        rhr_vals = [58.0] * 7
        scores = [80.0] * 7
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "peak_readiness"
        assert result["confidence"] == "high"

    def test_recovery_70_not_peak(self, db_conn):
        """Recovery 70% (tier 4) → NOT peak_readiness, even with everything else green."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]
        rhr_vals = [58.0] * 7
        scores = [80.0] * 6 + [70.0]  # Today only 70
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"

    def test_not_peak_with_high_rhr(self, db_conn):
        """Good everything except RHR above threshold → not peak."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]
        rhr_vals = [58.0] * 6 + [65.0]
        scores = [80.0] * 7
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"

    def test_not_peak_with_sleep_deficit(self, db_conn):
        """Deep sleep deficit → not peak even if everything else is green."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]
        rhr_vals = [58.0] * 7
        scores = [80.0] * 7
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates[:-1]):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"


# ─── Baseline (Default) ──────────────────────────────────────────────────────


class TestBaselineState:
    def test_no_strong_signals(self, db_conn):
        """Average metrics, no deficits → baseline."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=5)

        trend_dates = _generate_dates_inclusive(TARGET, 5)
        hrv_vals = [55.0] * 5
        rhr_vals = [58.0] * 5
        scores = [70.0] * 5
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "baseline"

    def test_gray_zone_falls_to_baseline(self, db_conn):
        """Recovery < 60 + 2 of 5 recent bad (gray zone) + no sleep deficit → baseline."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # 2 of last 5 bad → gray zone
        scores = [75.0, 75.0, 45.0, 50.0, 75.0, 75.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "baseline"


# ─── Priority / Edge Cases ───────────────────────────────────────────────────


class TestPriorityAndEdgeCases:
    def test_fatigue_overrides_sleep_deficits(self, db_conn):
        """When fatigue + deep deficit, fatigue wins (P1 > P3)."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0, 75.0, 45.0, 50.0, 55.0, 45.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=2_000_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_sleep_deficit_overrides_poor_recovery(self, db_conn):
        """Deep deficit + acute bad day → physical_recovery_deficit (P3 > P5)."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [30.0]  # Acute bad
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates[:-1]):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "physical_recovery_deficit"

    def test_no_recovery_today(self, db_conn):
        """No recovery record for today → still classifiable."""
        _seed_healthy_baseline(db_conn)
        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["state"] in ["baseline", "insufficient_data"]

    def test_no_sleep_today(self, db_conn):
        """No sleep record for today → still classifiable."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "baseline"

    def test_result_structure(self, db_conn):
        """Verify all expected keys in result dict."""
        _seed_healthy_baseline(db_conn)
        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert "state" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "metrics" in result
        assert "baselines" in result
        assert "trends" in result
        assert "sleep_analysis" in result
        assert "insufficient_data" in result
        assert isinstance(result["reasoning"], list)

    def test_null_stages_no_crash(self, db_conn):
        """Null sleep stages → no crash."""
        _seed_healthy_baseline(db_conn)
        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        upsert_whoop_sleep(
            db_conn, sleep_id=999, date=TARGET,
            deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None,
        )

        result = classify_state(db_conn, TARGET)
        assert result["state"] in ["baseline", "peak_readiness"]

    def test_recovery_score_none_no_crash(self, db_conn):
        """Recovery score is None → no crash."""
        _seed_healthy_baseline(db_conn)
        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=None, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["state"] in ["baseline", "peak_readiness"]

    def test_poor_sleep_state_in_states_list(self, db_conn):
        """Verify poor_sleep is in the STATES list."""
        from intelligence.state_classifier import STATES
        assert "poor_sleep" in STATES

    def test_recovery_exactly_at_boundaries(self, db_conn):
        """Recovery exactly at 40, 60, 80 — boundary behavior."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7

        # Recovery = 60 → NOT struggling (< 60 is the threshold)
        scores = [75.0] * 6 + [60.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)
        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] not in ["accumulated_fatigue", "poor_recovery"]

    def test_recovery_exactly_40_is_acute(self, db_conn):
        """Recovery = 40 → NOT acute bad (threshold is < 40)."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [40.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)
        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        # 40 is NOT < 40, so P5 doesn't fire. But 40 IS < 60, so P6 checks.
        # With 0 recent bad days, P6 fires → poor_recovery
        assert result["state"] == "poor_recovery"

    def test_peak_blocked_by_declining_hrv_trend(self, db_conn):
        """Negative HRV slope blocks peak even with everything else green."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [65.0, 63.0, 61.0, 59.0, 57.0, 55.0, 53.0]  # declining
        rhr_vals = [58.0] * 7
        scores = [80.0] * 7
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"

    def test_peak_blocked_when_hrv_trend_unavailable(self, db_conn):
        """HRV trend returns None (< 3 days in 7-day window) → peak blocked."""
        # Baseline data ends 8 days before TARGET — leaves a gap so the
        # 7-day trend window has only today's data (1 day, needs 3).
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=8)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=90.0, hrv_rmssd_milli=65.0, resting_heart_rate=55.0,
        )
        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"

    def test_peak_skipped_when_hrv_milli_is_none(self, db_conn):
        """hrv_rmssd_milli=None on peak-eligible day → baseline, not crash."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]
        rhr_vals = [58.0] * 7
        scores = [80.0] * 7
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        # Override today with None HRV
        upsert_whoop_recovery(
            db_conn, cycle_id=506, date=TARGET,
            recovery_score=90.0, hrv_rmssd_milli=None, resting_heart_rate=55.0,
        )

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"

    def test_gray_zone_assertion_is_baseline(self, db_conn):
        """Gray zone (2 of 5 bad) explicitly lands on baseline, not just 'not poor_recovery'."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0, 75.0, 45.0, 50.0, 75.0, 75.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "baseline"
        assert "inconclusive" in result["reasoning"][0].lower()

    def test_result_metrics_contain_correct_values(self, db_conn):
        """Verify _extract_metrics populates correct values."""
        _seed_healthy_baseline(db_conn)
        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=72.0, hrv_rmssd_milli=48.5, resting_heart_rate=61.0,
        )
        _seed_today_sleep(db_conn, deep_ms=5_000_000, rem_ms=6_000_000, light_ms=13_000_000)

        result = classify_state(db_conn, TARGET)
        m = result["metrics"]
        assert m["recovery_score"] == 72.0
        assert m["hrv_rmssd_milli"] == 48.5
        assert m["resting_heart_rate"] == 61.0
        assert m["deep_sleep_ms"] == 5_000_000
        assert m["rem_sleep_ms"] == 6_000_000

    def test_fatigue_confidence_medium_at_exactly_3_bad_days(self, db_conn):
        """3 of 5 recent bad → accumulated_fatigue with medium confidence."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # Exactly 3 of last 5 bad
        scores = [75.0, 75.0, 45.0, 50.0, 55.0, 75.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"
        assert result["confidence"] == "medium"

    def test_insufficient_data_flag_false_for_normal_states(self, db_conn):
        """insufficient_data flag is False when state is not insufficient_data."""
        _seed_healthy_baseline(db_conn)
        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["insufficient_data"] is False

    def test_poor_sleep_at_very_low_recovery_no_fatigue(self, db_conn):
        """Recovery 20% + no recent bad days + both deficits → poor_sleep, not poor_recovery."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [20.0]  # Only today bad
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates[:-1]):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )
        # Today: both deficits
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=2_000_000, light_ms=20_000_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_sleep"

    def test_recovery_79_not_peak(self, db_conn):
        """Recovery 79% — just below tier 5 threshold — NOT peak."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]
        rhr_vals = [58.0] * 7
        scores = [80.0] * 6 + [79.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "peak_readiness"

    def test_fatigue_lookback_ignores_null_recovery(self, db_conn):
        """Null recovery_score in lookback window doesn't count as bad or crash."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        # 2 real bad days + 2 None days + 1 good day in the 5-day window
        scores = [75.0, 75.0, 45.0, None, None, 50.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )

        result = classify_state(db_conn, TARGET)
        # Only 2 non-null bad days (45, 50) in lookback — not enough for fatigue
        # Today = 50 < 60, so poor_recovery (one-off) or baseline
        assert result["state"] != "accumulated_fatigue"
