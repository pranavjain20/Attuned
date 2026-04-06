"""Tests for intelligence/state_classifier.py — display-label classifier, 5-state system."""

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

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0, 75.0, 45.0, 50.0, 55.0, 45.0, 50.0]
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


# ─── Restorative Sleep Gate ──────────────────────────────────────────────────


def _seed_fatigue_pattern_with_sleep(conn, today_sleep_kwargs):
    """Set up accumulated fatigue conditions (recovery <60, 3 of 5 bad)
    with configurable sleep for today."""
    _seed_healthy_baseline(conn, skip_last_n=7)

    trend_dates = _generate_dates_inclusive(TARGET, 7)
    hrv_vals = [55.0] * 7
    rhr_vals = [58.0] * 7
    # 3 of last 5 days before today are bad → fatigue pattern
    scores = [75.0, 75.0, 45.0, 50.0, 55.0, 45.0, 50.0]
    _seed_trend_days(conn, trend_dates, hrv_vals, rhr_vals, scores)

    # Seed sleep for trend days (non-today) — normal sleep
    for i, date in enumerate(trend_dates[:-1]):
        upsert_whoop_sleep(
            conn, sleep_id=700 + i, date=date,
            deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
            light_sleep_ms=14_400_000,
            sleep_needed_baseline_ms=27_000_000,
        )

    # Seed today's sleep with specified params
    upsert_whoop_sleep(
        conn, sleep_id=799, date=TARGET,
        sleep_needed_baseline_ms=27_000_000,
        **today_sleep_kwargs,
    )


class TestRestorativeSleepGate:
    """Restorative sleep gate: if last night was genuinely restorative,
    skip accumulated_fatigue classification even when multi-day pattern qualifies."""

    def test_restorative_sleep_skips_fatigue(self, db_conn):
        """Good deep, good REM, high efficiency, 7.5h → NOT fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 6_300_000,     # 1.75h
            "rem_sleep_ms": 8_460_000,      # 2.35h
            "light_sleep_ms": 12_240_000,   # 3.4h → 7.5h total
            "sleep_efficiency": 92.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] != "accumulated_fatigue"
        assert "restorative" in result["reasoning"][0].lower()

    def test_poor_efficiency_stays_fatigue(self, db_conn):
        """Good stages but low efficiency (75%) → still fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 6_300_000,
            "rem_sleep_ms": 8_460_000,
            "light_sleep_ms": 12_240_000,
            "sleep_efficiency": 75.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_short_sleep_stays_fatigue(self, db_conn):
        """High efficiency but only 5.5h total → still fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 5_400_000,     # 1.5h
            "rem_sleep_ms": 5_400_000,      # 1.5h
            "light_sleep_ms": 9_000_000,    # 2.5h → 5.5h total
            "sleep_efficiency": 92.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_deep_deficit_stays_fatigue(self, db_conn):
        """Low deep sleep (ratio < 10%) even with good REM/efficiency → still fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 1_800_000,     # 0.5h — will be deficit
            "rem_sleep_ms": 8_460_000,
            "light_sleep_ms": 16_740_000,
            "sleep_efficiency": 92.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_rem_deficit_stays_fatigue(self, db_conn):
        """Low REM (ratio < 15%) even with good deep/efficiency → still fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 6_300_000,
            "rem_sleep_ms": 2_700_000,      # 0.75h — will be deficit
            "light_sleep_ms": 18_000_000,
            "sleep_efficiency": 92.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_no_sleep_data_stays_fatigue(self, db_conn):
        """No sleep record for today → still fatigue."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)
        trend_dates = _generate_dates_inclusive(TARGET, 7)
        scores = [75.0, 75.0, 45.0, 50.0, 55.0, 45.0, 50.0]
        _seed_trend_days(db_conn, trend_dates, [55.0]*7, [58.0]*7, scores)
        # No sleep seeded for today
        for i, date in enumerate(trend_dates[:-1]):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_borderline_efficiency_84_stays_fatigue(self, db_conn):
        """Efficiency at 84% (just under 85% threshold) → still fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 6_300_000,
            "rem_sleep_ms": 8_460_000,
            "light_sleep_ms": 12_240_000,
            "sleep_efficiency": 84.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] == "accumulated_fatigue"

    def test_exactly_6h_and_85_efficiency_passes_gate(self, db_conn):
        """Exactly at thresholds: 6h total, 85% efficiency → passes gate."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 5_400_000,     # 1.5h
            "rem_sleep_ms": 7_200_000,      # 2.0h
            "light_sleep_ms": 9_000_000,    # 2.5h → 6.0h total
            "sleep_efficiency": 85.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] != "accumulated_fatigue"

    def test_restorative_gate_lands_on_correct_downstream_state(self, db_conn):
        """When gate fires with recovery 50% and no deficits, should land on
        poor_recovery (one-off) or baseline, not accumulated_fatigue."""
        _seed_fatigue_pattern_with_sleep(db_conn, {
            "deep_sleep_ms": 6_300_000,
            "rem_sleep_ms": 8_460_000,
            "light_sleep_ms": 12_240_000,
            "sleep_efficiency": 92.0,
        })
        result = classify_state(db_conn, TARGET)
        assert result["state"] in ("baseline", "poor_recovery")


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

    def test_deep_deficit_only_triggers_poor_sleep(self, db_conn):
        """Deep deficit + REM fine → poor_sleep."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_sleep"

    def test_rem_deficit_only_triggers_poor_sleep(self, db_conn):
        """REM deficit + deep fine → poor_sleep."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=5_400_000, rem_ms=2_000_000, light_ms=14_400_000)

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

    def test_no_deficit_does_not_trigger_poor_sleep(self, db_conn):
        """No sleep deficits → NOT poor_sleep."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["state"] != "poor_sleep"

    def test_fatigue_overrides_poor_sleep(self, db_conn):
        """When fatigue conditions met + both sleep deficit, fatigue wins (P1 > P2)."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
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

    def test_reasoning_mentions_both_when_both_deficit(self, db_conn):
        """Both deficits → reasoning mentions both."""
        _seed_healthy_baseline(db_conn)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=2_000_000, light_ms=20_000_000)

        result = classify_state(db_conn, TARGET)
        reasoning_text = " ".join(result["reasoning"])
        assert "deep" in reasoning_text.lower()
        assert "rem" in reasoning_text.lower()

    def test_reasoning_mentions_deep_only_when_deep_deficit(self, db_conn):
        """Deep deficit only → reasoning mentions deep."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        reasoning_text = " ".join(result["reasoning"])
        assert "deep" in reasoning_text.lower()

    def test_reasoning_mentions_rem_only_when_rem_deficit(self, db_conn):
        """REM deficit only → reasoning mentions REM."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000)

        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )
        _seed_today_sleep(db_conn, deep_ms=5_400_000, rem_ms=2_000_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        reasoning_text = " ".join(result["reasoning"])
        assert "rem" in reasoning_text.lower()


# ─── Poor Recovery ─────────────────────────────────────────────────────────


class TestPoorRecovery:
    def test_acute_bad_day_no_sleep_deficit_triggers(self, db_conn):
        """Recovery < 40 + no sleep deficit → poor_recovery."""
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

    def test_acute_bad_day_with_sleep_deficit_is_poor_sleep(self, db_conn):
        """Recovery < 40 + sleep deficit → poor_sleep (P2 > P3)."""
        _seed_healthy_baseline(db_conn, deep_ms=5_400_000, rem_ms=7_200_000, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [25.0]  # Today: 25%
        _seed_trend_days(db_conn, trend_dates, hrv_vals, rhr_vals, scores)

        for i, date in enumerate(trend_dates[:-1]):
            upsert_whoop_sleep(
                db_conn, sleep_id=700 + i, date=date,
                deep_sleep_ms=5_400_000, rem_sleep_ms=7_200_000,
                light_sleep_ms=14_400_000,
                sleep_needed_baseline_ms=27_000_000,
            )
        # Today: deep deficit
        _seed_today_sleep(db_conn, deep_ms=2_000_000, rem_ms=7_200_000, light_ms=14_400_000)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "poor_sleep"

    def test_mild_bad_day_one_off_triggers(self, db_conn):
        """Recovery 40-59 with ≤1 recent bad day → poor_recovery."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
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
        """Recovery 70% (tier 4) → NOT peak_readiness."""
        _seed_healthy_baseline(db_conn, hrv_milli=55.0, rhr=58.0, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0]
        rhr_vals = [58.0] * 7
        scores = [80.0] * 6 + [70.0]
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
        """When fatigue + deep deficit, fatigue wins (P1 > P2)."""
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

    def test_no_whoop_data_today_warns_in_reasoning(self, db_conn):
        """No recovery AND no sleep for today → baseline with sync warning."""
        _seed_healthy_baseline(db_conn)

        result = classify_state(db_conn, TARGET)
        assert result["state"] == "baseline"
        reasoning_text = " ".join(result["reasoning"])
        assert "No WHOOP data" in reasoning_text
        assert "sync-whoop" in reasoning_text

    def test_partial_data_today_no_warning(self, db_conn):
        """Recovery exists but no sleep → no sync warning (partial data is fine)."""
        _seed_healthy_baseline(db_conn)
        upsert_whoop_recovery(
            db_conn, cycle_id=500, date=TARGET,
            recovery_score=70.0, hrv_rmssd_milli=55.0, resting_heart_rate=58.0,
        )

        result = classify_state(db_conn, TARGET)
        reasoning_text = " ".join(result["reasoning"])
        assert "No WHOOP data" not in reasoning_text

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

    def test_old_states_removed_from_states_list(self, db_conn):
        """Verify collapsed states are gone."""
        from intelligence.state_classifier import STATES
        assert "physical_recovery_deficit" not in STATES
        assert "emotional_processing_deficit" not in STATES

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
        # 40 is NOT < 40, so P3 doesn't fire. But 40 IS < 60, so P4 checks.
        # With 0 recent bad days, P4 fires → poor_recovery
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
        """Gray zone (2 of 5 bad) explicitly lands on baseline."""
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
        """Recovery 20% + no recent bad days + both deficits → poor_sleep."""
        _seed_healthy_baseline(db_conn, skip_last_n=7)

        trend_dates = _generate_dates_inclusive(TARGET, 7)
        hrv_vals = [55.0] * 7
        rhr_vals = [58.0] * 7
        scores = [75.0] * 6 + [20.0]
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
        assert result["state"] != "accumulated_fatigue"
