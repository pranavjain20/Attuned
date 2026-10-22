"""Tests for intelligence/feeling_score.py — the 0–100 Attuned feeling score."""

import math
import random
from datetime import date as date_cls, timedelta

import pytest

from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from intelligence.feeling_score import (
    FEELING_WEIGHTS,
    HEART_SIGNALS,
    MIN_CALIBRATION_DAYS,
    SLEEP_SIGNALS,
    band,
    build_page_day,
    compute_composite,
    compute_composite_history,
    compute_feeling_score,
    compute_feeling_signals,
    hrv_week_endpoints,
    map_to_score,
    pick_drivers,
    pick_state,
)

HOUR = 3_600_000


# ─── Weight table ─────────────────────────────────────────────────────────────


class TestWeights:
    def test_whoop_recovery_is_not_an_input(self):
        assert "recovery_z" not in FEELING_WEIGHTS
        assert "recovery_delta_z" not in FEELING_WEIGHTS

    def test_total_sleep_is_an_input(self):
        assert "total_sleep_z" in SLEEP_SIGNALS

    def test_groups_cover_every_weight_exactly_once(self):
        assert SLEEP_SIGNALS | HEART_SIGNALS == set(FEELING_WEIGHTS)
        assert not SLEEP_SIGNALS & HEART_SIGNALS

    def test_sleep_to_heart_ratio_is_about_two_to_one(self):
        sleep = sum(FEELING_WEIGHTS[s] for s in SLEEP_SIGNALS)
        heart = sum(FEELING_WEIGHTS[s] for s in HEART_SIGNALS)
        assert sleep / heart == pytest.approx(2.0, abs=0.05)

    def test_deep_and_rem_weigh_the_same(self):
        assert FEELING_WEIGHTS["deep_sleep_z"] == FEELING_WEIGHTS["rem_sleep_z"]

    def test_all_weights_positive(self):
        assert all(w > 0 for w in FEELING_WEIGHTS.values())


# ─── Composite ───────────────────────────────────────────────────────────────


def _all_z(value=0.0):
    return {s: value for s in FEELING_WEIGHTS}


class TestComputeComposite:
    def test_normal_day_is_zero(self):
        composite, _ = compute_composite(_all_z(0.0))
        assert composite == pytest.approx(0.0)

    def test_all_signals_equal_gives_that_value(self):
        composite, _ = compute_composite(_all_z(1.5))
        assert composite == pytest.approx(1.5)

    def test_contributions_sum_to_composite(self):
        z = {s: (i - 5) * 0.3 for i, s in enumerate(FEELING_WEIGHTS)}
        composite, contributions = compute_composite(z)
        assert sum(contributions.values()) == pytest.approx(composite)

    def test_weighted_average_hand_computed(self):
        z = _all_z(0.0)
        z["sleep_efficiency_z"] = -1.0
        composite, contributions = compute_composite(z)
        total = sum(FEELING_WEIGHTS.values())
        assert composite == pytest.approx(-FEELING_WEIGHTS["sleep_efficiency_z"] / total)
        assert contributions["sleep_efficiency_z"] == pytest.approx(composite)

    def test_missing_signals_reweighted(self):
        """Missing day-over-day signals: the rest are re-weighted, score barely moves."""
        z = _all_z(1.0)
        z["hrv_delta_z"] = None
        z["rhr_delta_z"] = None
        composite, contributions = compute_composite(z)
        assert composite == pytest.approx(1.0)
        assert "hrv_delta_z" not in contributions

    def test_too_little_weight_present_returns_none(self):
        """No night's sleep → only heart signals + debt → below the 70% weight floor."""
        z = {s: 0.5 for s in HEART_SIGNALS}
        z["sleep_debt_z"] = 0.0
        assert compute_composite(z) == (None, {})

    def test_empty_returns_none(self):
        assert compute_composite({}) == (None, {})

    def test_ignores_signals_outside_the_table(self):
        z = _all_z(0.0)
        z["recovery_z"] = 2.5
        composite, contributions = compute_composite(z)
        assert composite == pytest.approx(0.0)
        assert "recovery_z" not in contributions

    def test_extreme_values_stay_within_clamp(self):
        composite, _ = compute_composite(_all_z(-2.5))
        assert composite == pytest.approx(-2.5)


# ─── Percentile mapping ──────────────────────────────────────────────────────


class TestMapToScore:
    def test_median_composite_maps_to_median_recovery(self):
        refs = [-1.0, 0.0, 1.0]
        recoveries = [20.0, 50.0, 80.0]
        assert map_to_score(0.0, refs, recoveries) == 50

    def test_best_ever_maps_near_top_of_whoop_range(self):
        refs = [i / 10 for i in range(100)]
        recoveries = list(range(1, 101))
        assert map_to_score(99.0, refs, recoveries) == 100

    def test_worst_ever_maps_to_bottom(self):
        refs = [i / 10 for i in range(100)]
        recoveries = list(range(1, 101))
        assert map_to_score(-99.0, refs, recoveries) == 1

    def test_order_preserved(self):
        refs = [random.Random(1).gauss(0, 1) for _ in range(200)]
        recoveries = [random.Random(2).uniform(0, 100) for _ in range(200)]
        scores = [map_to_score(c, refs, recoveries) for c in (-1.0, 0.0, 1.0)]
        assert scores == sorted(scores)

    def test_band_shares_match_whoop(self):
        """Mapping every reference day reproduces WHOOP's red/yellow/green split."""
        rng = random.Random(7)
        refs = [rng.gauss(0, 1) for _ in range(500)]
        recoveries = [rng.choice([20.0] * 1 + [50.0] * 5 + [80.0] * 4) for _ in range(500)]
        mapped = [band(map_to_score(c, refs, recoveries)) for c in refs]
        for colour in ("red", "yellow", "green"):
            expected = sum(band(r) == colour for r in recoveries)
            assert abs(mapped.count(colour) - expected) <= 5

    def test_ties_use_mid_rank(self):
        refs = [0.0, 0.0, 0.0, 0.0]
        recoveries = [10.0, 20.0, 30.0, 40.0]
        assert map_to_score(0.0, refs, recoveries) == 25

    def test_score_is_int(self):
        assert isinstance(map_to_score(0.1, [0.0, 1.0], [33.0, 70.0]), int)


class TestBand:
    @pytest.mark.parametrize("score, expected", [
        (0, "red"), (33, "red"), (34, "yellow"), (66, "yellow"), (67, "green"), (100, "green"),
    ])
    def test_whoop_band_edges(self, score, expected):
        assert band(score) == expected

    def test_none(self):
        assert band(None) is None


# ─── State ───────────────────────────────────────────────────────────────────


class TestPickState:
    def test_dominant_dimension(self):
        assert pick_state({"para": 0.2, "symp": 0.5, "grnd": 0.3}) == ("energy", "Energy")
        assert pick_state({"para": 0.5, "symp": 0.2, "grnd": 0.3}) == ("rest", "Rest")
        assert pick_state({"para": 0.2, "symp": 0.3, "grnd": 0.5}) == ("grounding", "Grounding")

    def test_tie_prefers_rest_then_energy(self):
        assert pick_state({"para": 0.4, "symp": 0.4, "grnd": 0.2}) == ("rest", "Rest")
        assert pick_state({"para": 0.2, "symp": 0.4, "grnd": 0.4}) == ("energy", "Energy")


# ─── Drivers ─────────────────────────────────────────────────────────────────


class TestPickDrivers:
    def test_biggest_contributions_first(self):
        z = {"sleep_efficiency_z": -1.0, "rem_sleep_z": -2.0, "hrv_z": -0.6}
        contributions = {"sleep_efficiency_z": -0.15, "rem_sleep_z": -0.26, "hrv_z": -0.06}
        picked = pick_drivers(contributions, z, direction=-1)
        assert [p for p, _ in picked] == ["rem_sleep_z", "sleep_efficiency_z", "hrv_z"]

    def test_at_most_three(self):
        z = {s: -2.0 for s in FEELING_WEIGHTS}
        contributions = {s: -FEELING_WEIGHTS[s] for s in FEELING_WEIGHTS}
        assert len(pick_drivers(contributions, z, direction=-1)) == 3

    def test_small_wobbles_never_named(self):
        z = {"sleep_efficiency_z": -0.4}
        assert pick_drivers({"sleep_efficiency_z": -0.2}, z, direction=-1) == []

    def test_includes_multi_day_signals(self):
        z = {"sleep_debt_z": -2.5, "hrv_trend_z": -2.0}
        contributions = {"sleep_debt_z": -0.2, "hrv_trend_z": -0.13}
        assert {s for s, _ in pick_drivers(contributions, z, direction=-1)} == {"sleep_debt_z", "hrv_trend_z"}

    def test_one_strong_counterweight_goes_last(self):
        z = {"rem_sleep_z": -2.0, "sleep_efficiency_z": -1.5, "deep_sleep_z": -1.0, "hrv_z": 2.0}
        contributions = {"rem_sleep_z": -0.26, "sleep_efficiency_z": -0.23,
                         "deep_sleep_z": -0.13, "hrv_z": 0.2}
        picked = pick_drivers(contributions, z, direction=-1)
        assert [s for s, _ in picked] == ["rem_sleep_z", "sleep_efficiency_z", "hrv_z"]

    def test_weak_counterweight_dropped(self):
        z = {"rem_sleep_z": -2.0, "hrv_z": 0.6}
        contributions = {"rem_sleep_z": -0.26, "hrv_z": 0.05}
        assert [s for s, _ in pick_drivers(contributions, z, direction=-1)] == ["rem_sleep_z"]

    def test_only_counterweights_returns_nothing(self):
        """Nothing pushes the explained way → no drivers rather than a misleading one."""
        z = {"hrv_z": 2.0}
        assert pick_drivers({"hrv_z": 0.2}, z, direction=-1) == []

    def test_ties_follow_weight_table_order(self):
        z = {"hrv_z": -1.0, "rem_sleep_z": -1.0}
        contributions = {"hrv_z": -0.1, "rem_sleep_z": -0.1}
        assert [s for s, _ in pick_drivers(contributions, z, direction=-1)] == ["rem_sleep_z", "hrv_z"]


class TestHrvWeekEndpoints:
    def test_follows_the_slope_not_the_raw_endpoints(self):
        """Zig-zag week whose first and last days are equal but which rises overall."""
        import numpy as np
        values = [math.log(v) for v in (45, 47, 49, 51, 53, 55, 45)]
        slope = float(np.polyfit(range(7), values, 1)[0])
        trend = {"slope": slope, "mean": float(np.mean(values)), "values": values}
        start, end = hrv_week_endpoints(trend)
        assert slope > 0
        assert end > start

    def test_flat_week(self):
        values = [math.log(50)] * 7
        start, end = hrv_week_endpoints({"slope": 0.0, "mean": math.log(50), "values": values})
        assert start == pytest.approx(50) and end == pytest.approx(50)


# ─── DB-backed: synthetic history ────────────────────────────────────────────


def _seed_history(conn, end_date, days, seed=0, recovery_follows_sleep=True):
    """Seed `days` of plausible varying WHOOP data ending the day before end_date."""
    rng = random.Random(seed)
    end = date_cls.fromisoformat(end_date)
    for offset in range(days, 0, -1):
        d = (end - timedelta(days=offset)).isoformat()
        quality = rng.gauss(0, 1)
        total = (7.2 + 0.8 * quality) * HOUR
        _insert_day(conn, d, cycle_id=10_000 + offset, total_ms=total,
                    eff=88 + 3 * quality + rng.gauss(0, 1),
                    hrv=48 + 6 * rng.gauss(0, 1), rhr=56 + 2 * rng.gauss(0, 1),
                    recovery=max(1, min(99, 55 + (20 * quality if recovery_follows_sleep else 0)
                                        + 10 * rng.gauss(0, 1))))


def _insert_day(conn, d, cycle_id, total_ms, eff, hrv, rhr, recovery, deep_share=0.22,
                rem_share=0.25, nap=None):
    upsert_whoop_recovery(conn, cycle_id=cycle_id, date=d, recovery_score=recovery,
                          hrv_rmssd_milli=hrv, resting_heart_rate=rhr)
    deep, rem = int(total_ms * deep_share), int(total_ms * rem_share)
    upsert_whoop_sleep(conn, sleep_id=f"s-{d}", date=d, recovery_cycle_id=cycle_id, nap=False,
                       deep_sleep_ms=deep, rem_sleep_ms=rem, light_sleep_ms=int(total_ms) - deep - rem,
                       awake_ms=1_800_000, sleep_efficiency=eff,
                       sleep_needed_baseline_ms=8 * HOUR)
    if nap:
        upsert_whoop_sleep(conn, sleep_id=f"nap-{d}", date=d, nap=True,
                           deep_sleep_ms=nap, rem_sleep_ms=0, light_sleep_ms=0,
                           sleep_efficiency=99.0, sleep_needed_baseline_ms=8 * HOUR)


TARGET = "2026-06-01"


class TestComputeFeelingSignals:
    def test_drops_whoop_recovery_and_adds_total_sleep(self, db_conn):
        _seed_history(db_conn, TARGET, 40)
        _insert_day(db_conn, TARGET, 1, total_ms=7 * HOUR, eff=88, hrv=48, rhr=56, recovery=55)
        z = compute_feeling_signals(db_conn, TARGET)["z"]
        assert "recovery_z" not in z and "recovery_delta_z" not in z
        assert z["total_sleep_z"] is not None

    def test_short_night_gives_strongly_negative_total_sleep(self, db_conn):
        _seed_history(db_conn, TARGET, 40)
        _insert_day(db_conn, TARGET, 1, total_ms=3.9 * HOUR, eff=92, hrv=48, rhr=56, recovery=55)
        assert compute_feeling_signals(db_conn, TARGET)["z"]["total_sleep_z"] < -2.0

    def test_nap_does_not_change_signals(self, db_conn):
        """A nap the same day leaves every sleep signal exactly as the night alone gives."""
        _seed_history(db_conn, TARGET, 40)
        _insert_day(db_conn, TARGET, 1, total_ms=5 * HOUR, eff=82, hrv=48, rhr=56, recovery=55)
        before = compute_feeling_signals(db_conn, TARGET)["z"]
        upsert_whoop_sleep(db_conn, sleep_id="nap-today", date=TARGET, nap=True,
                           deep_sleep_ms=2 * HOUR, rem_sleep_ms=0, light_sleep_ms=0,
                           sleep_efficiency=99.0)
        after = compute_feeling_signals(db_conn, TARGET)["z"]
        for s in ("deep_sleep_z", "rem_sleep_z", "total_sleep_z", "sleep_efficiency_z", "deep_ratio_z"):
            assert after[s] == pytest.approx(before[s])

    def test_efficiency_usual_ignores_naps(self, db_conn):
        """Naps (~99% efficiency) in the baseline window must not raise 'usual'."""
        _seed_history(db_conn, TARGET, 40)
        _insert_day(db_conn, TARGET, 1, total_ms=7 * HOUR, eff=88, hrv=48, rhr=56, recovery=55)
        before = compute_feeling_signals(db_conn, TARGET)["z"]["sleep_efficiency_z"]
        start = date_cls.fromisoformat(TARGET)
        for i in range(1, 31):
            upsert_whoop_sleep(db_conn, sleep_id=f"nap-{i}", date=(start - timedelta(days=i)).isoformat(),
                               nap=True, deep_sleep_ms=1, rem_sleep_ms=1, light_sleep_ms=1,
                               sleep_efficiency=99.0)
        after = compute_feeling_signals(db_conn, TARGET)["z"]["sleep_efficiency_z"]
        assert after == pytest.approx(before)

    def test_no_recovery_row_returns_empty(self, db_conn):
        assert compute_feeling_signals(db_conn, TARGET) == {"z": {}, "profile": None}


class TestComputeFeelingScore:
    def _ready(self, conn, days=120, **today):
        _seed_history(conn, TARGET, days)
        values = dict(total_ms=7.2 * HOUR, eff=88, hrv=48, rhr=56, recovery=55)
        values.update(today)
        _insert_day(conn, TARGET, 1, **values)

    def test_happy_path_shape(self, db_conn):
        self._ready(db_conn)
        result = compute_feeling_score(db_conn, TARGET)
        assert 0 <= result["score"] <= 100
        assert result["band"] == band(result["score"])
        assert result["state"] in ("rest", "energy", "grounding")
        assert result["reason"] is None
        assert result["explanation"][-1].startswith("So today leans")

    def test_great_night_beats_terrible_night(self, db_conn):
        self._ready(db_conn, total_ms=9.0 * HOUR, eff=95, hrv=55, rhr=53)
        great = compute_feeling_score(db_conn, TARGET)["score"]
        _insert_day(db_conn, TARGET, 1, total_ms=3.9 * HOUR, eff=78, hrv=40, rhr=60, recovery=55)
        terrible = compute_feeling_score(db_conn, TARGET)["score"]
        assert great > terrible
        assert band(terrible) == "red"

    def test_whoop_recovery_does_not_move_the_score(self, db_conn):
        """Same body signals, different WHOOP recovery → same Attuned score."""
        self._ready(db_conn, recovery=10)
        low = compute_feeling_score(db_conn, TARGET)["score"]
        _insert_day(db_conn, TARGET, 1, total_ms=7.2 * HOUR, eff=88, hrv=48, rhr=56, recovery=95)
        high = compute_feeling_score(db_conn, TARGET)["score"]
        assert low == high

    def test_never_cites_whoop_recovery(self, db_conn):
        self._ready(db_conn, total_ms=4 * HOUR, eff=80, recovery=95)
        result = compute_feeling_score(db_conn, TARGET)
        assert not any("recovery" in line.lower() for line in result["explanation"])
        assert all(not d["signal"].startswith("recovery") for d in result["drivers"])

    def test_uses_only_past_days_for_calibration(self, db_conn):
        """Adding a future day must not change today's score."""
        self._ready(db_conn)
        before = compute_feeling_score(db_conn, TARGET)["score"]
        future = (date_cls.fromisoformat(TARGET) + timedelta(days=1)).isoformat()
        _insert_day(db_conn, future, 2, total_ms=3 * HOUR, eff=70, hrv=30, rhr=70, recovery=1)
        assert compute_feeling_score(db_conn, TARGET)["score"] == before

    def test_precomputed_history_gives_same_result(self, db_conn):
        self._ready(db_conn)
        history = compute_composite_history(db_conn, TARGET)
        assert compute_feeling_score(db_conn, TARGET, history=history) == compute_feeling_score(db_conn, TARGET)

    def test_no_whoop_data_for_date(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert "No WHOOP data" in result["reason"]

    def test_missing_night_sleep(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        upsert_whoop_recovery(db_conn, cycle_id=1, date=TARGET, recovery_score=50,
                              hrv_rmssd_milli=48, resting_heart_rate=56)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert "No night's sleep" in result["reason"]
        assert result["state"] is None

    def test_nap_only_day_counts_as_missing_night(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        upsert_whoop_recovery(db_conn, cycle_id=1, date=TARGET, recovery_score=50,
                              hrv_rmssd_milli=48, resting_heart_rate=56)
        upsert_whoop_sleep(db_conn, sleep_id="nap", date=TARGET, nap=True,
                           deep_sleep_ms=HOUR, rem_sleep_ms=HOUR, light_sleep_ms=HOUR)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert "naps don't count" in result["reason"]

    def test_first_two_weeks_no_baseline(self, db_conn):
        _seed_history(db_conn, TARGET, 10)
        _insert_day(db_conn, TARGET, 1, total_ms=7 * HOUR, eff=88, hrv=48, rhr=56, recovery=55)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert "14 days" in result["reason"]

    def test_not_enough_days_to_calibrate(self, db_conn):
        """Baselines exist but fewer than MIN_CALIBRATION_DAYS scored days to map onto 0–100."""
        self._ready(db_conn, days=40)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert result["composite"] is not None
        assert str(MIN_CALIBRATION_DAYS) in result["reason"]

    def test_extreme_day_stays_in_range(self, db_conn):
        self._ready(db_conn, total_ms=12 * HOUR, eff=100, hrv=120, rhr=40)
        assert 0 <= compute_feeling_score(db_conn, TARGET)["score"] <= 100


class TestBuildPageDay:
    def test_matches_page_contract(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=5 * HOUR, eff=82, hrv=48, rhr=56, recovery=70)
        day = build_page_day(db_conn, TARGET)
        assert set(day) == {"date", "whoop", "attuned", "metrics", "playlist"}
        assert day["playlist"] is None
        assert set(day["whoop"]) == {"recovery", "band"}
        assert day["whoop"] == {"recovery": 70, "band": "green"}
        assert set(day["attuned"]) == {"score", "band", "state", "state_label", "headline",
                                       "explanation", "drivers", "reason"}
        assert set(day["metrics"]) == {"hrv_ms", "rhr_bpm", "sleep_hours", "rem_hours",
                                       "deep_hours", "sleep_efficiency_pct", "sleep_debt_hours_7d"}
        assert day["metrics"]["sleep_hours"] == pytest.approx(5.0, abs=0.01)
        for d in day["attuned"]["drivers"]:
            assert set(d) == {"signal", "label", "value", "usual", "z", "effect"}

    def test_metrics_ignore_naps(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=5 * HOUR, eff=82, hrv=48, rhr=56, recovery=70,
                    nap=2 * HOUR)
        metrics = build_page_day(db_conn, TARGET)["metrics"]
        assert metrics["sleep_hours"] == pytest.approx(5.0, abs=0.01)
        assert metrics["sleep_efficiency_pct"] == 82.0

    def test_missing_day_still_has_contract_shape(self, db_conn):
        day = build_page_day(db_conn, TARGET)
        assert day["attuned"]["score"] is None
        assert day["attuned"]["reason"]
        assert day["whoop"] == {"recovery": None, "band": None}
        assert day["playlist"] is None
