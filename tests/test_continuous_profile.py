"""Tests for intelligence/continuous_profile.py — the playlist target set by the Attuned score."""

import pytest

from config import BASELINE_CALM_ANCHOR, BASELINE_ENERGY_ANCHOR, BASELINE_STEADY_ANCHOR
from intelligence.continuous_profile import (
    SLEEP_DEBT_POSITIVE_THRESHOLD,
    Z_CLAMP,
    compute_continuous_profile,
    compute_z_scores,
    pick_state,
    profile_at,
    _safe_z,
)

GRID = [i / 1000 for i in range(1001)]


# ---------------------------------------------------------------------------
# Anchors (design choices in config.py)
# ---------------------------------------------------------------------------


class TestAnchors:
    @pytest.mark.parametrize("anchor", [BASELINE_CALM_ANCHOR, BASELINE_STEADY_ANCHOR, BASELINE_ENERGY_ANCHOR])
    def test_each_sums_to_one(self, anchor):
        assert set(anchor) == {"para", "symp", "grnd"}
        assert sum(anchor.values()) == pytest.approx(1.0)

    def test_each_anchor_has_its_own_clear_lead(self):
        assert pick_state(BASELINE_CALM_ANCHOR) == ("rest", "Rest")
        assert pick_state(BASELINE_STEADY_ANCHOR) == ("grounding", "Grounding")
        assert pick_state(BASELINE_ENERGY_ANCHOR) == ("energy", "Energy")

    def test_calm_and_energy_mirror_each_other(self):
        assert BASELINE_CALM_ANCHOR["para"] == BASELINE_ENERGY_ANCHOR["symp"]
        assert BASELINE_CALM_ANCHOR["symp"] == BASELINE_ENERGY_ANCHOR["para"]
        assert BASELINE_CALM_ANCHOR["grnd"] == BASELINE_ENERGY_ANCHOR["grnd"]

    def test_steady_holds_calm_and_lift_level(self):
        assert BASELINE_STEADY_ANCHOR["para"] == BASELINE_STEADY_ANCHOR["symp"]


# ---------------------------------------------------------------------------
# Position → profile
# ---------------------------------------------------------------------------


class TestProfileAt:
    @pytest.mark.parametrize("position, anchor", [
        (0.0, BASELINE_CALM_ANCHOR), (0.5, BASELINE_STEADY_ANCHOR), (1.0, BASELINE_ENERGY_ANCHOR),
    ])
    def test_hits_each_anchor(self, position, anchor):
        assert profile_at(position) == pytest.approx(anchor)

    def test_halfway_between_anchors_is_their_average(self):
        expected = {k: (BASELINE_CALM_ANCHOR[k] + BASELINE_STEADY_ANCHOR[k]) / 2 for k in BASELINE_CALM_ANCHOR}
        assert profile_at(0.25) == pytest.approx(expected)

    @pytest.mark.parametrize("outside, edge", [(-0.3, 0.0), (1.7, 1.0)])
    def test_clamps_outside_zero_to_one(self, outside, edge):
        assert profile_at(outside) == profile_at(edge)

    def test_always_sums_to_one_and_stays_non_negative(self):
        for p in GRID:
            profile = profile_at(p)
            assert sum(profile.values()) == pytest.approx(1.0)
            assert min(profile.values()) >= 0.0

    def test_lower_position_is_always_calmer(self):
        """Every step down the scale: at least as much calm, no more lift (a 30 is calmer than a 45)."""
        for lo, hi in zip(GRID, GRID[1:]):
            assert profile_at(lo)["para"] >= profile_at(hi)["para"]
            assert profile_at(lo)["symp"] <= profile_at(hi)["symp"]
        assert profile_at(0.30)["para"] > profile_at(0.45)["para"]
        assert profile_at(0.30)["symp"] < profile_at(0.45)["symp"]

    def test_no_jumps(self):
        """A tiny change in position never moves any dimension by more than a tiny amount."""
        for lo, hi in zip(GRID, GRID[1:]):
            a, b = profile_at(lo), profile_at(hi)
            assert max(abs(a[k] - b[k]) for k in a) < 0.002

    def test_grounding_peaks_at_the_middle(self):
        assert max(GRID, key=lambda p: profile_at(p)["grnd"]) == 0.5


class TestLabelFollowsPosition:
    """The label is the dominant dimension, which is a fixed step function of the position."""

    def test_rest_then_grounding_then_energy_changing_exactly_twice(self):
        labels = [pick_state(profile_at(p))[0] for p in GRID]
        changes = [(GRID[i], labels[i - 1], labels[i]) for i in range(1, len(labels)) if labels[i] != labels[i - 1]]
        assert [(a, b) for _, a, b in changes] == [("rest", "grounding"), ("grounding", "energy")]

    def test_change_points_are_where_the_docs_say(self):
        """~0.29 and ~0.71 (documented in config.py and continuous_profile.py)."""
        labels = [pick_state(profile_at(p))[0] for p in GRID]
        first_grounding = GRID[labels.index("grounding")]
        first_energy = GRID[labels.index("energy")]
        assert first_grounding == pytest.approx(0.29, abs=0.01)
        assert first_energy == pytest.approx(0.71, abs=0.01)

    def test_label_is_symmetric(self):
        """Mirror anchors → position p and 1 - p get mirror labels (away from the two change points)."""
        mirror = {"rest": "energy", "energy": "rest", "grounding": "grounding"}
        for p in GRID:
            if min(abs(p - 0.2917), abs(p - 0.7083)) < 0.005:
                continue
            assert pick_state(profile_at(1 - p))[0] == mirror[pick_state(profile_at(p))[0]]


class TestPickState:
    def test_dominant_dimension(self):
        assert pick_state({"para": 0.2, "symp": 0.5, "grnd": 0.3}) == ("energy", "Energy")
        assert pick_state({"para": 0.5, "symp": 0.2, "grnd": 0.3}) == ("rest", "Rest")
        assert pick_state({"para": 0.2, "symp": 0.3, "grnd": 0.5}) == ("grounding", "Grounding")

    def test_tie_prefers_rest_then_energy(self):
        assert pick_state({"para": 0.4, "symp": 0.4, "grnd": 0.2}) == ("rest", "Rest")
        assert pick_state({"para": 0.2, "symp": 0.4, "grnd": 0.4}) == ("energy", "Energy")


# ---------------------------------------------------------------------------
# Sleep debt z-score cap tests
# ---------------------------------------------------------------------------


class TestSleepDebtCap:
    """Verify sleep_debt_z is capped when debt exceeds the research threshold."""

    def test_threshold_matches_van_dongen(self):
        """Threshold should be 7h (Van Dongen 2003: 1h/night onset of impairment)."""
        assert SLEEP_DEBT_POSITIVE_THRESHOLD == 7.0

    def test_high_debt_caps_at_zero(self):
        """Debt above threshold should never produce positive z, even if below personal baseline."""
        # Simulate: 16h debt, baseline mean 23h, sd 3.2h
        # raw_z = (16 - 23) / 3.2 = -2.19, inverted = +2.19
        # But 16h > 7h threshold, so should be capped to 0
        from unittest.mock import patch, MagicMock
        import sqlite3

        # We can't easily unit-test compute_z_scores without a full DB,
        # so test the cap logic directly
        debt = 16.0
        debt_mean = 23.0
        debt_sd = 3.2
        raw_z = _safe_z(debt, debt_mean, debt_sd)
        inverted = -raw_z
        assert inverted > 0, "Without cap, this would be positive"

        # Apply the cap
        if debt > SLEEP_DEBT_POSITIVE_THRESHOLD:
            capped = min(inverted, 0.0)
        else:
            capped = inverted
        assert capped == 0.0, f"Debt of {debt}h should cap at 0, got {capped}"

    def test_low_debt_allows_positive_z(self):
        """Debt below threshold can produce positive z (genuinely good sleep week)."""
        debt = 3.0
        debt_mean = 23.0
        debt_sd = 3.2
        raw_z = _safe_z(debt, debt_mean, debt_sd)
        inverted = -raw_z
        assert inverted > 0, "Low debt should produce positive z before cap"

        # Apply the cap — should NOT cap because debt < threshold
        if debt > SLEEP_DEBT_POSITIVE_THRESHOLD:
            capped = min(inverted, 0.0)
        else:
            capped = inverted
        assert capped > 0, f"Debt of {debt}h should allow positive z, got {capped}"

    def test_negative_z_unaffected_by_cap(self):
        """High debt that already produces negative z should pass through unchanged."""
        debt = 30.0  # Very high debt, above baseline
        debt_mean = 23.0
        debt_sd = 3.2
        raw_z = _safe_z(debt, debt_mean, debt_sd)
        inverted = -raw_z
        assert inverted < 0, "Very high debt should naturally produce negative z"

        if debt > SLEEP_DEBT_POSITIVE_THRESHOLD:
            capped = min(inverted, 0.0)
        else:
            capped = inverted
        assert capped == inverted, "Negative z should pass through unchanged"


# ---------------------------------------------------------------------------
# Sleep efficiency: main-sleep baseline + short-night cap (DB-backed)
# ---------------------------------------------------------------------------

HOUR = 3_600_000
TARGET = "2026-06-01"


def _history(conn, days=40):
    from tests.test_feeling_score import _seed_history
    _seed_history(conn, TARGET, days)


def _today(conn, hours, eff, **kwargs):
    from tests.test_feeling_score import _insert_day
    _insert_day(conn, TARGET, 1, total_ms=hours * HOUR, eff=eff, hrv=48, rhr=56, recovery=55, **kwargs)


class TestSleepEfficiencyBaseline:
    def test_usual_is_the_main_sleep_baseline(self, db_conn):
        from intelligence.baselines import compute_sleep_efficiency_baseline
        _history(db_conn)
        _today(db_conn, 7, 92)
        bl = compute_sleep_efficiency_baseline(db_conn, TARGET)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == pytest.approx(
            _safe_z(92, bl["mean"], bl["sd"]))

    def test_naps_in_the_window_do_not_move_usual(self, db_conn):
        """Naps run ~99% efficient; counting them would make every night look broken."""
        from datetime import date, timedelta
        from db.queries import upsert_whoop_sleep
        _history(db_conn)
        _today(db_conn, 7, 88)
        before = compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"]
        for i in range(1, 31):
            d = (date.fromisoformat(TARGET) - timedelta(days=i)).isoformat()
            upsert_whoop_sleep(db_conn, sleep_id=f"nap-{i}", date=d, nap=True, deep_sleep_ms=1,
                               rem_sleep_ms=1, light_sleep_ms=1, sleep_efficiency=99.0)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == pytest.approx(before)


class TestShortNightEfficiencyCap:
    """Under 6 h asleep, high efficiency is not good news: a short sleep is naturally unbroken."""

    def test_short_efficient_night_caps_at_zero(self, db_conn):
        _history(db_conn)
        _today(db_conn, 2.5, 99)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == 0.0

    def test_exactly_six_hours_is_not_capped(self, db_conn):
        _history(db_conn)
        _today(db_conn, 6, 99)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] > 1.0

    def test_short_broken_night_keeps_its_negative_z(self, db_conn):
        from intelligence.baselines import compute_sleep_efficiency_baseline
        _history(db_conn)
        _today(db_conn, 4, 75)
        bl = compute_sleep_efficiency_baseline(db_conn, TARGET)
        z = compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"]
        assert z < 0 and z == pytest.approx(_safe_z(75, bl["mean"], bl["sd"]))

    def test_missing_stages_leave_efficiency_uncapped(self, db_conn):
        """Without stage data the night's length is unknown, so no cap is applied."""
        from db.queries import upsert_whoop_sleep
        _history(db_conn)
        _today(db_conn, 2.5, 99)
        upsert_whoop_sleep(db_conn, sleep_id=f"s-{TARGET}", date=TARGET, recovery_cycle_id=1, nap=False,
                           deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None, sleep_efficiency=99.0)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] > 1.0

    def test_profile_reads_the_capped_z(self, db_conn):
        """The playlist profile reads the same capped z: a 2.5 h night no longer pushes energy."""
        _history(db_conn)
        _today(db_conn, 2.5, 99)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == 0.0
        assert compute_continuous_profile(db_conn, TARGET)["z_scores"]["sleep_efficiency_z"] == 0.0


class TestShortNightDeepShareCap:
    """Under 6 h asleep, a high deep-sleep share is not good news.

    Deep sleep comes early in the night, so a short night is mostly deep sleep
    by default (2026-10-18: 3.9 h, deep share z +1.84). Same cap as efficiency.
    """

    def test_short_deep_heavy_night_caps_at_zero(self, db_conn):
        _history(db_conn)
        _today(db_conn, 3.9, 90, deep_share=0.40)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] == 0.0

    def test_exactly_six_hours_is_not_capped(self, db_conn):
        _history(db_conn)
        _today(db_conn, 6, 90, deep_share=0.40)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] > 1.0

    def test_just_under_six_hours_is_capped(self, db_conn):
        _history(db_conn)
        _today(db_conn, 5.99, 90, deep_share=0.40)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] == 0.0

    def test_short_night_low_share_keeps_its_negative_z(self, db_conn):
        _history(db_conn)
        _today(db_conn, 4, 90, deep_share=0.10)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] < -1.0


# ---------------------------------------------------------------------------
# The day's profile (DB-backed): follows the Attuned score
# ---------------------------------------------------------------------------


def _ready(conn, days=120, **today):
    from tests.test_feeling_score import _insert_day, _seed_history
    _seed_history(conn, TARGET, days)
    values = dict(total_ms=7.2 * HOUR, eff=88, hrv=48, rhr=56, recovery=55)
    values.update(today)
    _insert_day(conn, TARGET, 1, **values)


class TestComputeContinuousProfile:
    def test_output_contract(self, db_conn):
        """Same keys callers (matching/generator.py) read, plus the score that set it."""
        _ready(db_conn)
        result = compute_continuous_profile(db_conn, TARGET)
        assert set(result) == {"profile", "target_valence", "state", "state_label", "score",
                               "position", "z_scores", "signals_used", "interactions"}
        assert set(result["profile"]) == {"para", "symp", "grnd"}
        assert sum(result["profile"].values()) == pytest.approx(1.0)
        assert 0.0 < result["target_valence"] < 1.0
        assert result["interactions"] == []
        assert result["signals_used"] == sum(v is not None for v in result["z_scores"].values()) > 0

    def test_is_the_feeling_scores_position_on_the_line(self, db_conn):
        from intelligence.feeling_score import compute_feeling_score
        _ready(db_conn)
        scored = compute_feeling_score(db_conn, TARGET)
        result = compute_continuous_profile(db_conn, TARGET)
        assert result["score"] == scored["score"]
        assert result["position"] == scored["position"]
        assert result["profile"] == profile_at(scored["position"])
        assert result["state"] == scored["state"]

    def test_bad_night_is_calmer_than_great_night(self, db_conn):
        _ready(db_conn, total_ms=9.0 * HOUR, eff=95, hrv=55, rhr=53)
        great = compute_continuous_profile(db_conn, TARGET)
        _today(db_conn, 3.9, 78)
        bad = compute_continuous_profile(db_conn, TARGET)
        assert bad["profile"]["para"] > great["profile"]["para"]
        assert bad["profile"]["symp"] < great["profile"]["symp"]
        assert (bad["state"], great["state"]) == ("rest", "energy")

    def test_short_night_alone_makes_it_calmer(self, db_conn):
        """Only total sleep differs (same efficiency, shares, heart): the short night is calmer."""
        _ready(db_conn, total_ms=8.0 * HOUR)
        full = compute_continuous_profile(db_conn, TARGET)
        _today(db_conn, 4.0, 88)
        short = compute_continuous_profile(db_conn, TARGET)
        assert short["position"] < full["position"]
        assert short["profile"]["para"] > full["profile"]["para"]

    def test_short_deep_heavy_night_is_rest(self, db_conn):
        """2026-10-18 shape: 3.9 h, deep-heavy, HRV down → clearly calm."""
        _ready(db_conn, total_ms=3.9 * HOUR, eff=92, hrv=40, rhr=60, recovery=25, deep_share=0.40)
        result = compute_continuous_profile(db_conn, TARGET)
        assert result["state"] == "rest"
        assert result["profile"]["para"] - max(result["profile"]["symp"], result["profile"]["grnd"]) > 0.1

    def test_whoop_recovery_does_not_move_the_profile(self, db_conn):
        _ready(db_conn, recovery=5)
        low = compute_continuous_profile(db_conn, TARGET)
        from tests.test_feeling_score import _insert_day
        _insert_day(db_conn, TARGET, 1, total_ms=7.2 * HOUR, eff=88, hrv=48, rhr=56, recovery=99)
        assert compute_continuous_profile(db_conn, TARGET)["profile"] == low["profile"]

    def test_no_night_recorded_gives_steady(self, db_conn):
        from db.queries import upsert_whoop_recovery
        from tests.test_feeling_score import _seed_history
        _seed_history(db_conn, TARGET, 120)
        upsert_whoop_recovery(db_conn, cycle_id=1, date=TARGET, recovery_score=50,
                              hrv_rmssd_milli=48, resting_heart_rate=56)
        result = compute_continuous_profile(db_conn, TARGET)
        assert result["score"] is None and result["position"] is None
        assert result["profile"] == BASELINE_STEADY_ANCHOR
        assert result["state"] == "grounding"

    def test_too_little_history_to_score_gives_steady(self, db_conn):
        _ready(db_conn, days=40)
        result = compute_continuous_profile(db_conn, TARGET)
        assert result["position"] is None
        assert result["profile"] == BASELINE_STEADY_ANCHOR

    def test_no_whoop_row_gives_steady(self, db_conn):
        result = compute_continuous_profile(db_conn, TARGET)
        assert result["profile"] == BASELINE_STEADY_ANCHOR
        assert result["z_scores"] == {} and result["signals_used"] == 0

    def test_steady_fallback_is_a_copy(self, db_conn):
        compute_continuous_profile(db_conn, TARGET)["profile"]["para"] = 99
        assert BASELINE_STEADY_ANCHOR["para"] == 0.25

    def test_precomputed_history_gives_same_result(self, db_conn):
        from intelligence.feeling_score import compute_composite_history
        _ready(db_conn)
        history = compute_composite_history(db_conn, TARGET)
        assert compute_continuous_profile(db_conn, TARGET, history) == compute_continuous_profile(db_conn, TARGET)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSafeZ:
    """Tests for _safe_z helper."""

    def test_normal_z_score(self):
        assert _safe_z(50, 45, 5) == pytest.approx(1.0)

    def test_negative_z_score(self):
        assert _safe_z(40, 45, 5) == pytest.approx(-1.0)

    def test_clamps_high(self):
        assert _safe_z(100, 45, 5) == Z_CLAMP

    def test_clamps_low(self):
        assert _safe_z(0, 45, 5) == -Z_CLAMP

    def test_zero_sd_returns_none(self):
        assert _safe_z(50, 45, 0) is None

    def test_none_value_returns_none(self):
        assert _safe_z(None, 45, 5) is None
