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
    SAME_BAND_HEADLINE,
    SIGNAL_PHRASES,
    SIGNAL_TEXT,
    SLEEP_CHANGES,
    SLEEP_SIGNALS,
    _describe_drivers,
    _explain_direction,
    _headline,
    _sentence,
    _value_and_usual,
    band,
    build_page_day,
    compute_composite,
    compute_composite_history,
    compute_feeling_score,
    hrv_change,
    hrv_week_endpoints,
    locate_day,
    map_to_score,
    percentile_position,
    pick_drivers,
    sleep_changes,
)
from intelligence.playlist_target import pick_state, profile_at
from intelligence.signals import SIGNALS

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


class TestPercentilePosition:
    def test_below_every_reference_is_zero(self):
        assert percentile_position(-9.0, [0.0, 1.0, 2.0]) == 0.0

    def test_above_every_reference_is_one(self):
        assert percentile_position(9.0, [0.0, 1.0, 2.0]) == 1.0

    def test_middle(self):
        assert percentile_position(1.5, [0.0, 1.0, 2.0, 3.0]) == 0.5

    def test_ties_count_half(self):
        assert percentile_position(0.0, [0.0, 0.0, 0.0, 0.0]) == 0.5

    def test_is_the_rank_map_to_score_uses(self):
        refs, recoveries = [0.0, 1.0, 2.0, 3.0], [10.0, 20.0, 30.0, 40.0]
        assert map_to_score(1.5, refs, recoveries) == 25  # recovery at position 0.5


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


class TestHeadline:
    def test_above_whoop_led_by_sleep(self):
        assert _headline("green", "yellow", [{"signal": "deep_sleep_z"}]) == \
            "Better than WHOOP's number: your sleep held up"

    def test_above_whoop_after_short_night_credits_body_not_sleep(self):
        assert _headline("green", "yellow", [{"signal": "deep_ratio_z"}], short_night=True) == \
            "Better than WHOOP's number: your body held up"

    def test_below_whoop_after_short_night_still_blames_sleep(self):
        assert _headline("yellow", "green", [{"signal": "total_sleep_z"}], short_night=True) == \
            "WHOOP says ready, but your sleep says go easy"

    def test_same_band(self):
        assert _headline("yellow", "yellow", [], short_night=True) == "A middle-of-the-road day"

    def test_below_whoop_with_no_drivers_does_not_invent_a_cause(self):
        assert _headline("yellow", "green", []) == "An ordinary night for you, and WHOOP rated it higher"

    def test_above_whoop_with_no_drivers_does_not_invent_a_cause(self):
        assert _headline("yellow", "red", []) == "An ordinary night for you, and WHOOP rated it lower"

    def test_below_a_green_whoop_says_ready_but(self):
        assert _headline("yellow", "green", [{"signal": "rem_sleep_z"}]) == \
            "WHOOP says ready, but your sleep says go easy"

    def test_below_a_yellow_whoop_does_not_claim_whoop_says_ready(self):
        """WHOOP yellow isn't 'ready': the wording follows WHOOP's band."""
        headline = _headline("red", "yellow", [{"signal": "rem_sleep_z"}])
        assert headline == "Lower than WHOOP's number: your sleep says go easy"
        assert "ready" not in headline

    def test_below_led_by_heart_blames_the_body(self):
        assert _headline("red", "green", [{"signal": "hrv_z"}]) == \
            "WHOOP says ready, but your body says go easy"
        assert _headline("red", "yellow", [{"signal": "hrv_z"}]) == \
            "Lower than WHOOP's number: your body says go easy"

    def test_below_with_no_drivers_blames_the_body(self):
        assert _headline("red", "green", []) == "WHOOP says ready, but your body says go easy"

    @pytest.mark.parametrize("attuned", ["red", "yellow", "green"])
    def test_no_whoop_band_describes_the_band(self, attuned):
        assert _headline(attuned, None, [{"signal": "hrv_z"}]) == SAME_BAND_HEADLINE[attuned]


class TestHrvWeekEndpoints:
    def test_exact_endpoints_of_the_fitted_line(self):
        """7 days, slope 0.02 ln-ms/day around ln 50: the line runs ±3 days × 0.02 from the middle."""
        start, end = hrv_week_endpoints({"slope": 0.02, "mean": math.log(50), "values": [0.0] * 7})
        assert start == pytest.approx(47.0882267, abs=1e-6)   # 50 · e^−0.06
        assert end == pytest.approx(53.0918273, abs=1e-6)     # 50 · e^+0.06

    def test_exact_endpoints_for_a_six_day_week(self):
        """A missing day: the line spans 5 days, ±2.5 from the middle."""
        start, end = hrv_week_endpoints({"slope": -0.04, "mean": math.log(40), "values": [0.0] * 6})
        assert start == pytest.approx(44.2068367, abs=1e-6)   # 40 · e^+0.10
        assert end == pytest.approx(36.1934967, abs=1e-6)     # 40 · e^−0.10

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

    def test_short_efficient_night_never_credits_sleep(self, db_conn):
        """2026-09-04 shape: 2.5 h at 99% efficiency, HRV well above usual, WHOOP red."""
        self._ready(db_conn, total_ms=2.5 * HOUR, eff=99, hrv=70, rhr=50, recovery=10, deep_share=0.40)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["headline"].startswith("Better than WHOOP's number")  # the branch under test
        text = " ".join([result["headline"]] + result["explanation"]).lower()
        assert "sleep held up" not in text
        assert "unbroken" not in text
        assert all(d["signal"] != "sleep_efficiency_z" for d in result["drivers"])

    def test_position_and_state_follow_the_score(self, db_conn):
        """Low score → rest, high → energy; the state is the playlist's (profile_at(position))."""
        self._ready(db_conn, total_ms=3.9 * HOUR, eff=78, hrv=40, rhr=60)
        low = compute_feeling_score(db_conn, TARGET)
        _insert_day(db_conn, TARGET, 1, total_ms=9.0 * HOUR, eff=95, hrv=55, rhr=53, recovery=55)
        high = compute_feeling_score(db_conn, TARGET)
        assert 0.0 <= low["position"] < high["position"] <= 1.0
        assert (low["state"], high["state"]) == ("rest", "energy")
        assert low["state"] == pick_state(profile_at(low["position"]))[0]
        assert low["explanation"][-1] == (
            "So today leans rest: you're likely to feel below your normal, "
            "so the music is built to help you settle.")

    def test_unscored_day_has_no_position(self, db_conn):
        self._ready(db_conn, days=40)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["position"] is None and result["state"] is None

    def test_extreme_day_stays_in_range(self, db_conn):
        self._ready(db_conn, total_ms=12 * HOUR, eff=100, hrv=120, rhr=40)
        assert 0 <= compute_feeling_score(db_conn, TARGET)["score"] <= 100


class TestLocateDay:
    def test_matches_the_score(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=6 * HOUR, eff=85, hrv=45, rhr=57, recovery=40)
        day = locate_day(db_conn, TARGET)
        scored = compute_feeling_score(db_conn, TARGET)
        assert (day["score"], day["position"], day["composite"]) == \
            (scored["score"], scored["position"], scored["composite"])
        assert day["position"] == percentile_position(day["composite"], day["ref_composites"])
        assert day["whoop_recovery"] == 40 and day["reason"] is None

    def test_no_whoop_row(self, db_conn):
        day = locate_day(db_conn, TARGET)
        assert day["position"] is None and day["z"] == {} and "No WHOOP data" in day["reason"]

    def test_ignores_history_on_or_after_the_date(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=6 * HOUR, eff=85, hrv=45, rhr=57, recovery=40)
        history = compute_composite_history(db_conn, TARGET)
        polluted = dict(history, **{TARGET: {"composite": 99.0, "recovery": 1.0},
                                    "2026-06-02": {"composite": -99.0, "recovery": 99.0}})
        assert locate_day(db_conn, TARGET, polluted) == locate_day(db_conn, TARGET, history)


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
                                       "explanation", "drivers", "reason", "sleep_changes", "hrv_change"}
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


# ─── Signal wording ──────────────────────────────────────────────────────────


VALUES = {
    "eff": 91.0, "usual_eff": 87.0, "deep_h": 1.6, "usual_deep_h": 1.4,
    "rem_h": 1.9, "usual_rem_h": 1.7, "total_h": 7.5, "usual_total_h": 7.0,
    "debt_h": 3.0, "usual_debt_h": 5.5, "deep_share": 0.21, "usual_deep_share": 0.19,
    "hrv_ms": 52.0, "usual_hrv_ms": 47.0, "rhr": 54.0, "usual_rhr": 56.0,
    "hrv_week": (45.0, 52.0), "hrv_yesterday": 44.0, "rhr_yesterday": 57.0,
}

VALUE_AND_USUAL = {
    "sleep_efficiency_z": ("91%", "87%"),
    "deep_sleep_z": ("1.6 h", "1.4 h"),
    "rem_sleep_z": ("1.9 h", "1.7 h"),
    "total_sleep_z": ("7.5 h", "7.0 h"),
    "sleep_debt_z": ("3.0 h", "5.5 h"),
    "deep_ratio_z": ("21%", "19%"),
    "hrv_z": ("52 ms", "47 ms"),
    "rhr_z": ("54 bpm", "56 bpm"),
    "hrv_trend_z": ("45 → 52 ms", "steady"),
    "hrv_delta_z": ("52 ms", "44 ms yesterday"),
    "rhr_delta_z": ("54 bpm", "57 bpm yesterday"),
}

SENTENCES = {
    ("sleep_efficiency_z", True): "Your sleep was unbroken: asleep for 91% of your time in bed (usual 87%).",
    ("sleep_efficiency_z", False): "Your sleep was broken: asleep for only 91% of your time in bed (usual 87%).",
    ("deep_sleep_z", True): "You got 1.6 h of deep sleep, more than your usual 1.4 h.",
    ("deep_sleep_z", False): "You got 1.6 h of deep sleep, less than your usual 1.4 h.",
    ("rem_sleep_z", True): "You got 1.9 h of REM sleep, more than your usual 1.7 h.",
    ("rem_sleep_z", False): "You got 1.9 h of REM sleep, less than your usual 1.7 h.",
    ("total_sleep_z", True): "You slept 7.5 h, more than your usual 7.0 h.",
    ("total_sleep_z", False): "You slept 7.5 h, less than your usual 7.0 h.",
    ("sleep_debt_z", True): "Over the past 7 nights you've carried less sleep debt than usual (3.0 h vs 5.5 h).",
    ("sleep_debt_z", False): "Over the past 7 nights you've built up 3.0 h of sleep debt, more than your usual 5.5 h.",
    ("deep_ratio_z", True): "Deep sleep made up 21% of your night, above your usual 19%.",
    ("deep_ratio_z", False): "Deep sleep made up 21% of your night, below your usual 19%.",
    ("hrv_z", True): "Your HRV was 52 ms, above your usual 47 ms.",
    ("hrv_z", False): "Your HRV was 52 ms, below your usual 47 ms.",
    # Resting heart rate is inverted: lower than usual is the good direction.
    ("rhr_z", True): "Your resting heart rate was 54 bpm, below your usual 56 bpm.",
    ("rhr_z", False): "Your resting heart rate was 54 bpm, above your usual 56 bpm.",
    ("hrv_trend_z", True): "Your HRV has been climbing over the past week (45 → 52 ms).",
    ("hrv_trend_z", False): "Your HRV has been drifting down over the past week (45 → 52 ms).",
    ("hrv_delta_z", True): "Your HRV rose to 52 ms from 44 ms yesterday.",
    ("hrv_delta_z", False): "Your HRV fell to 52 ms from 44 ms yesterday.",
    ("rhr_delta_z", True): "Your resting heart rate dropped to 54 bpm from 57 bpm yesterday.",
    ("rhr_delta_z", False): "Your resting heart rate rose to 54 bpm from 57 bpm yesterday.",
}


class TestSignalText:
    def test_one_entry_per_weighted_signal(self):
        assert set(SIGNAL_TEXT) == set(FEELING_WEIGHTS) == set(SIGNALS)

    def test_the_tests_cover_every_signal_both_ways(self):
        assert set(VALUE_AND_USUAL) == set(FEELING_WEIGHTS)
        assert set(SENTENCES) == {(s, up) for s in FEELING_WEIGHTS for up in (True, False)}

    @pytest.mark.parametrize("signal", sorted(VALUE_AND_USUAL))
    def test_value_and_usual(self, signal):
        assert _value_and_usual(signal, VALUES) == VALUE_AND_USUAL[signal]

    @pytest.mark.parametrize("signal, up", sorted(SENTENCES))
    def test_sentence(self, signal, up):
        value, usual = _value_and_usual(signal, VALUES)
        assert _sentence(signal, up, value, usual) == SENTENCES[(signal, up)]

    def test_phrases_are_the_pages_wording(self):
        assert SIGNAL_PHRASES == {
            "deep_sleep_z": ("more deep sleep", "less deep sleep"),
            "deep_ratio_z": ("a bigger share of deep sleep", "a smaller share of deep sleep"),
            "rem_sleep_z": ("more REM", "less REM"),
            "total_sleep_z": ("a longer night", "a shorter night"),
            "sleep_efficiency_z": ("less broken sleep", "more broken sleep"),
            "sleep_debt_z": ("less sleep debt", "built-up sleep debt"),
            "hrv_z": ("a higher HRV", "a lower HRV"),
            "hrv_delta_z": ("HRV up since yesterday", "HRV down since yesterday"),
            "hrv_trend_z": ("HRV trending up this week", "HRV drifting down this week"),
            "rhr_z": ("a lower resting heart rate", "a higher resting heart rate"),
            "rhr_delta_z": ("resting heart rate down since yesterday", "resting heart rate up since yesterday"),
        }

    def test_phrases_come_from_the_table(self):
        assert SIGNAL_PHRASES == {s: (t.helped, t.hurt) for s, t in SIGNAL_TEXT.items()}


class TestDescribeDrivers:
    def test_fills_in_real_numbers(self):
        drivers = _describe_drivers([("hrv_z", -0.12)], {"hrv_z": -1.234}, VALUES)
        assert drivers == [{"signal": "hrv_z", "label": "HRV", "value": "52 ms", "usual": "47 ms",
                            "z": -1.23, "effect": "down", "contribution": -0.12}]

    def test_a_driver_without_its_numbers_is_left_out(self):
        """Never a sentence that says 'None': no number, no mention."""
        values = dict(VALUES, hrv_yesterday=None)
        picked = [("hrv_delta_z", 0.1), ("hrv_z", 0.08)]
        drivers = _describe_drivers(picked, {"hrv_delta_z": 1.0, "hrv_z": 1.0}, values)
        assert [d["signal"] for d in drivers] == ["hrv_z"]


class TestExplainDirection:
    REFS = [-1.0, 0.0, 1.0]   # median 0.0

    def test_at_the_median_explains_up(self):
        assert _explain_direction(0.0, self.REFS, "yellow", "yellow") == 1

    def test_just_below_the_median_explains_down(self):
        assert _explain_direction(-1e-9, self.REFS, "yellow", "yellow") == -1

    def test_attuned_below_whoop_explains_down_even_above_median(self):
        assert _explain_direction(5.0, self.REFS, "red", "yellow") == -1

    def test_attuned_above_whoop_explains_up_even_below_median(self):
        assert _explain_direction(-5.0, self.REFS, "green", "yellow") == 1

    def test_no_whoop_band_uses_the_median(self):
        assert _explain_direction(0.5, self.REFS, "green", None) == 1
        assert _explain_direction(-0.5, self.REFS, "green", None) == -1


class TestMissingReason:
    """Each reason a day with WHOOP data can't be scored names the real cause."""

    def test_null_stage_data_says_stages_are_missing_not_history(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        upsert_whoop_recovery(db_conn, cycle_id=1, date=TARGET, recovery_score=50,
                              hrv_rmssd_milli=48, resting_heart_rate=56)
        upsert_whoop_sleep(db_conn, sleep_id=f"s-{TARGET}", date=TARGET, recovery_cycle_id=1, nap=False,
                           deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None,
                           sleep_efficiency=90.0, sleep_needed_baseline_ms=8 * HOUR)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert result["reason"] == "Last night's sleep stages are missing, so the night can't be scored."

    def test_too_many_signals_missing(self, db_conn):
        """Night and history are fine, but HRV, resting HR and efficiency are all blank today."""
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=7 * HOUR, eff=None, hrv=None, rhr=None, recovery=50)
        result = compute_feeling_score(db_conn, TARGET)
        assert result["score"] is None
        assert result["reason"] == "Too many signals are missing today to give a fair score."

    def test_short_history_says_so(self, db_conn):
        _seed_history(db_conn, TARGET, 10)
        _insert_day(db_conn, TARGET, 1, total_ms=7 * HOUR, eff=88, hrv=48, rhr=56, recovery=55)
        assert compute_feeling_score(db_conn, TARGET)["reason"] == (
            "Not enough history yet: your personal normal needs at least 14 days of data.")

    def test_no_night_says_so(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        upsert_whoop_recovery(db_conn, cycle_id=1, date=TARGET, recovery_score=50,
                              hrv_rmssd_milli=48, resting_heart_rate=56)
        assert compute_feeling_score(db_conn, TARGET)["reason"] == (
            "No night's sleep recorded for this date (naps don't count).")


class TestReferenceChecks:
    def test_percentile_position_needs_references(self):
        with pytest.raises(ValueError, match="no reference"):
            percentile_position(0.5, [])

    def test_map_to_score_needs_references(self):
        with pytest.raises(ValueError, match="no reference"):
            map_to_score(0.5, [], [])

    def test_map_to_score_needs_one_recovery_per_composite(self):
        with pytest.raises(ValueError, match="2 reference composites but 1 recoveries"):
            map_to_score(0.5, [0.0, 1.0], [50.0])

    @pytest.mark.parametrize("composite", [-1.0, 1.0, 9.0])
    def test_single_reference_maps_to_its_recovery(self, composite):
        """Degenerate but defined: one earlier day, so every score is that day's recovery."""
        assert map_to_score(composite, [1.0], [42.0]) == 42


# compute_feeling_score on _seed_history(seed 0, 120 days) + a 6 h / 85% / HRV 45 / RHR 57 day.
# Identical before and after signals moved into intelligence/signals.py.
PINNED_SCORE = (24, "red", "rest")
PINNED_COMPOSITE = -1.2304830430964468
PINNED_POSITION = 4 / 106         # above 4 of the 106 earlier scored days


class TestRealDays:
    """End to end on a seeded history."""

    def test_happy_path_exact_score(self, db_conn):
        """Regression pin: the seeded history (seed 0, 120 days) and this day give exactly these numbers."""
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=6 * HOUR, eff=85, hrv=45, rhr=57, recovery=40)
        result = compute_feeling_score(db_conn, TARGET)
        assert (result["score"], result["band"], result["state"]) == PINNED_SCORE
        assert result["composite"] == pytest.approx(PINNED_COMPOSITE, abs=1e-9)
        assert result["position"] == pytest.approx(PINNED_POSITION, abs=1e-9)

    @pytest.mark.parametrize("seed", range(6))
    def test_no_sentence_says_none(self, db_conn, seed):
        rng = random.Random(seed)
        _seed_history(db_conn, TARGET, 120, seed=seed)
        _insert_day(db_conn, TARGET, 1, total_ms=rng.uniform(3, 10) * HOUR, eff=rng.uniform(70, 99),
                    hrv=rng.uniform(30, 80), rhr=rng.uniform(48, 66), recovery=rng.uniform(1, 99),
                    deep_share=rng.uniform(0.1, 0.4))
        day = build_page_day(db_conn, TARGET)
        assert day["attuned"]["score"] is not None
        text = [day["attuned"]["headline"]] + day["attuned"]["explanation"]
        assert not any("None" in line for line in text)
        assert all(d["value"] is not None and d["usual"] is not None for d in day["attuned"]["drivers"])


# ─── Sleep changes: why the two scores differ, in plain words ────────────────


def _z_for(contributions, value=0.5):
    return {s: (value if c > 0 else -value) for s, c in contributions.items()}


class TestSleepChanges:
    """VALUES: every sleep signal is better than usual, so helped == "more" except sleep debt."""

    def _changes(self, contributions, values=VALUES):
        return sleep_changes(contributions, _z_for(contributions), values)

    def test_percent_of_usual_for_hours(self):
        texts = [c["text"] for c in self._changes({"total_sleep_z": 0.1, "deep_sleep_z": 0.05,
                                                     "rem_sleep_z": 0.02})]
        assert texts == ["You slept 7% more than usual.", "You got 14% more deep sleep than usual.",
                         "Your REM sleep was 12% above usual."]

    def test_efficiency_in_points_not_percent_of_usual(self):
        [change] = self._changes({"sleep_efficiency_z": 0.1})
        assert change["text"] == "You were asleep for 4% more of your time in bed than usual."

    def test_sleep_debt_in_hours(self):
        [change] = self._changes({"sleep_debt_z": 0.1})
        assert change["text"] == "This week you've built up 2.5 fewer hours of sleep debt than usual."
        assert change["effect"] == "up"

    def test_whole_hours_of_debt_keep_the_decimal(self):
        values = {**VALUES, "debt_h": 6.5, "usual_debt_h": 5.5}
        [change] = self._changes({"sleep_debt_z": -0.1}, values)
        assert change["text"] == "This week you've built up 1.0 more hours of sleep debt than usual."

    def test_biggest_effect_first_either_direction(self):
        values = {**VALUES, "rem_h": 1.5}
        signals = [c["signal"] for c in self._changes({"total_sleep_z": 0.02, "rem_sleep_z": -0.09,
                                                        "deep_sleep_z": 0.05}, values)]
        assert signals == ["rem_sleep_z", "deep_sleep_z", "total_sleep_z"]

    def test_meaning_follows_the_effect(self):
        values = {**VALUES, "rem_h": 1.5}
        helped, hurt = self._changes({"rem_sleep_z": 0.09}), self._changes({"rem_sleep_z": -0.09}, values)
        assert helped[0]["meaning"] == SLEEP_CHANGES["rem_sleep_z"].good
        assert hurt[0]["meaning"] == SLEEP_CHANGES["rem_sleep_z"].bad
        assert hurt[0]["text"] == "Your REM sleep was 12% below usual."

    def test_heart_signals_and_deep_share_left_out(self):
        assert self._changes({"hrv_z": 0.2, "rhr_z": 0.1, "deep_ratio_z": 0.1}) == []

    def test_no_effect_left_out(self):
        """A short night caps efficiency at zero: it didn't move the score, so it isn't a reason."""
        assert self._changes({"sleep_efficiency_z": 0.0}) == []

    def test_change_that_rounds_away_left_out(self):
        values = {**VALUES, "total_h": 7.02, "eff": 87.3, "debt_h": 5.53}
        assert self._changes({"total_sleep_z": 0.01, "sleep_efficiency_z": 0.01,
                              "sleep_debt_z": -0.01}, values) == []

    def test_direction_disagreeing_with_effect_left_out(self):
        """More sleep than usual can't be shown with a red arrow."""
        assert self._changes({"total_sleep_z": -0.05}) == []

    @pytest.mark.parametrize("key", ["total_h", "usual_total_h"])
    def test_missing_numbers_left_out(self, key):
        assert self._changes({"total_sleep_z": 0.1}, {**VALUES, key: None}) == []

    def test_zero_usual_left_out(self):
        assert self._changes({"total_sleep_z": 0.1}, {**VALUES, "usual_total_h": 0.0}) == []

    def test_carries_rounded_z(self):
        [change] = sleep_changes({"total_sleep_z": 0.1}, {"total_sleep_z": 0.4567}, VALUES)
        assert change["z"] == 0.46

    def test_every_meaning_is_a_full_sentence(self):
        for wording in SLEEP_CHANGES.values():
            for line in (wording.more, wording.less, wording.good, wording.bad):
                assert line[0].isupper() and line.endswith(".")


class TestHrvChange:
    def test_signed_whole_percents(self):
        assert hrv_change(VALUES) == {"vs_usual": 11, "vs_yesterday": 18}

    def test_drop_is_negative(self):
        assert hrv_change({**VALUES, "hrv_ms": 40.0})["vs_usual"] == -15

    @pytest.mark.parametrize("key", ["hrv_ms", "usual_hrv_ms", "hrv_yesterday"])
    def test_missing_is_none(self, key):
        change = hrv_change({**VALUES, key: None})
        assert None in change.values()
        if key == "hrv_ms":
            assert change == {"vs_usual": None, "vs_yesterday": None}


class TestBuildPageDaySleepChanges:
    def test_short_night_lists_its_changes(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=5 * HOUR, eff=82, hrv=48, rhr=56, recovery=70)
        attuned = build_page_day(db_conn, TARGET)["attuned"]
        texts = [c["text"] for c in attuned["sleep_changes"]]
        assert any(t.startswith("You slept ") and t.endswith("% less than usual.") for t in texts)
        assert set(attuned["hrv_change"]) == {"vs_usual", "vs_yesterday"}

    def test_unscored_day_has_no_changes(self, db_conn):
        attuned = build_page_day(db_conn, TARGET)["attuned"]
        assert attuned["sleep_changes"] == []
        assert attuned["hrv_change"] == {"vs_usual": None, "vs_yesterday": None}
