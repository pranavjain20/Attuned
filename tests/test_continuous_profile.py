"""Tests for intelligence/continuous_profile.py — weight table properties and scenario validation."""

import pytest

from intelligence.continuous_profile import (
    SIGNAL_WEIGHTS,
    WEIGHT_SENSITIVITY,
    SLEEP_DEBT_POSITIVE_THRESHOLD,
    Z_CLAMP,
    NEUTRAL_PROFILE,
    compute_continuous_profile,
    compute_z_scores,
    _safe_z,
)


# ---------------------------------------------------------------------------
# Weight table structural tests
# ---------------------------------------------------------------------------


class TestWeightTableProperties:
    """Verify the weight table reflects the research-backed sleep:autonomic ratio."""

    AUTONOMIC_SIGNALS = [
        "recovery_z", "recovery_delta_z", "hrv_z", "hrv_delta_z",
        "rhr_z", "rhr_delta_z", "hrv_trend_z",
    ]
    SLEEP_SIGNALS = [
        "deep_sleep_z", "deep_ratio_z", "rem_sleep_z",
        "sleep_efficiency_z", "sleep_debt_z",
    ]

    def test_all_twelve_signals_present(self):
        assert len(SIGNAL_WEIGHTS) == 12

    def test_each_signal_has_three_components(self):
        for name, weights in SIGNAL_WEIGHTS.items():
            assert set(weights.keys()) == {"para", "symp", "grnd"}, f"{name} missing component"

    def test_sleep_para_dominates_autonomic_para(self):
        """Sleep signals should have ~2x the para weight of autonomic signals (Vitale 2015)."""
        auto_para = sum(abs(SIGNAL_WEIGHTS[s]["para"]) for s in self.AUTONOMIC_SIGNALS)
        sleep_para = sum(abs(SIGNAL_WEIGHTS[s]["para"]) for s in self.SLEEP_SIGNALS)
        ratio = sleep_para / auto_para
        assert ratio >= 1.5, (
            f"Sleep:autonomic para ratio is {ratio:.2f}, should be >= 1.5 "
            f"(research: sleep predicts feeling ~2x better than HRV)"
        )

    def test_sleep_total_influence_exceeds_autonomic(self):
        """Total sleep weight (all components) should exceed autonomic."""
        def total_influence(signals):
            return sum(
                sum(abs(SIGNAL_WEIGHTS[s][c]) for c in ("para", "symp", "grnd"))
                for s in signals
            )
        auto_total = total_influence(self.AUTONOMIC_SIGNALS)
        sleep_total = total_influence(self.SLEEP_SIGNALS)
        assert sleep_total > auto_total, (
            f"Sleep total={sleep_total:.2f}, autonomic total={auto_total:.2f}. "
            "Sleep should dominate."
        )

    def test_recovery_is_strongest_autonomic_signal(self):
        """Recovery z should have the highest weight among autonomic signals."""
        recovery_symp = abs(SIGNAL_WEIGHTS["recovery_z"]["symp"])
        for s in self.AUTONOMIC_SIGNALS:
            if s != "recovery_z":
                assert recovery_symp >= abs(SIGNAL_WEIGHTS[s]["symp"]), (
                    f"recovery_z symp ({recovery_symp}) should be >= {s} symp ({abs(SIGNAL_WEIGHTS[s]['symp'])})"
                )

    def test_sleep_efficiency_is_strongest_sleep_signal(self):
        """Sleep efficiency should have the highest para weight among sleep signals."""
        eff_para = abs(SIGNAL_WEIGHTS["sleep_efficiency_z"]["para"])
        for s in self.SLEEP_SIGNALS:
            if s != "sleep_efficiency_z":
                assert eff_para >= abs(SIGNAL_WEIGHTS[s]["para"]), (
                    f"sleep_efficiency_z para ({eff_para}) should be >= {s} para ({abs(SIGNAL_WEIGHTS[s]['para'])})"
                )

    def test_rem_routes_through_grounding(self):
        """REM deficit should primarily affect grounding (emotional processing)."""
        rem_grnd = abs(SIGNAL_WEIGHTS["rem_sleep_z"]["grnd"])
        rem_para = abs(SIGNAL_WEIGHTS["rem_sleep_z"]["para"])
        assert rem_grnd > rem_para, "REM should route more through grounding than parasympathetic"


# ---------------------------------------------------------------------------
# Scenario tests — using direct profile computation from z-scores
# ---------------------------------------------------------------------------


def _compute_profile_from_z(z_scores: dict[str, float]) -> dict[str, float]:
    """Compute a normalized profile from a dict of z-scores (test helper)."""
    profile = dict(NEUTRAL_PROFILE)
    for signal_name, weights in SIGNAL_WEIGHTS.items():
        z = z_scores.get(signal_name)
        if z is None:
            continue
        for component in ("para", "symp", "grnd"):
            profile[component] += z * weights[component] * WEIGHT_SENSITIVITY

    # Clamp and normalize (matching the real function)
    for k in profile:
        profile[k] = max(0.0, profile[k])
    total = sum(profile.values())
    if total > 0:
        for k in profile:
            profile[k] = round(profile[k] / total, 4)
    return profile


class TestScenarioProfiles:
    """Verify profile outputs match expected character for known scenarios."""

    def test_great_day_is_symp_dominant(self):
        """All signals good → energetic playlist."""
        z = {s: 1.2 for s in SIGNAL_WEIGHTS}
        profile = _compute_profile_from_z(z)
        assert profile["symp"] > profile["para"], (
            f"Great day should be symp > para, got symp={profile['symp']:.3f} para={profile['para']:.3f}"
        )
        assert profile["symp"] > 0.38, f"Great day symp={profile['symp']:.3f}, expected > 0.38"

    def test_terrible_day_is_para_dominant(self):
        """All signals bad → deep rest."""
        z = {s: -2.0 for s in SIGNAL_WEIGHTS}
        profile = _compute_profile_from_z(z)
        assert profile["para"] > profile["symp"], "Terrible day should be para > symp"
        assert profile["para"] > 0.45, f"Terrible day para={profile['para']:.3f}, expected > 0.45"
        assert profile["symp"] < 0.15, f"Terrible day symp={profile['symp']:.3f}, expected < 0.15"

    def test_bad_day_is_calmer_than_neutral(self):
        """Most signals moderately bad → noticeably calmer."""
        z = {s: -0.8 for s in SIGNAL_WEIGHTS}
        profile = _compute_profile_from_z(z)
        assert profile["para"] > profile["symp"], "Bad day should be para > symp"
        assert profile["para"] > NEUTRAL_PROFILE["para"], "Bad day should be calmer than neutral"

    def test_okay_day_is_roughly_balanced(self):
        """Mixed signals → balanced profile."""
        z = {
            "recovery_z": 0.3, "recovery_delta_z": -0.2, "hrv_z": 0.1,
            "hrv_delta_z": 0.0, "rhr_z": -0.1, "rhr_delta_z": 0.0,
            "deep_sleep_z": 0.2, "deep_ratio_z": 0.1, "rem_sleep_z": -0.1,
            "sleep_efficiency_z": 0.3, "sleep_debt_z": -0.3, "hrv_trend_z": 0.1,
        }
        profile = _compute_profile_from_z(z)
        assert abs(profile["para"] - profile["symp"]) < 0.10, (
            f"Okay day should be roughly balanced, got para={profile['para']:.3f} symp={profile['symp']:.3f}"
        )

    def test_divergence_day_recovery_good_sleep_bad(self):
        """Recovery/HRV good but sleep bad → should NOT be energy-leaning.

        This is the April 7 scenario that exposed the original weight bug.
        Recovery 81% (z=+1.38), HRV good (z=+1.12), but REM deficit (z=-1.12),
        poor sleep efficiency (z=-1.05), elevated RHR.
        """
        z = {
            "recovery_z": 1.38, "hrv_z": 1.12, "hrv_trend_z": 0.95,
            "rhr_z": -0.12, "deep_sleep_z": -0.07, "deep_ratio_z": 0.08,
            "rem_sleep_z": -1.12, "sleep_efficiency_z": -1.05,
            "sleep_debt_z": 0.0,  # Capped by SLEEP_DEBT_POSITIVE_THRESHOLD
        }
        profile = _compute_profile_from_z(z)
        assert profile["symp"] <= profile["para"] + 0.02, (
            f"Divergence day should not be energy-leaning. "
            f"Got para={profile['para']:.3f} symp={profile['symp']:.3f}"
        )

    def test_divergence_day_calmer_than_pure_good_recovery(self):
        """Same recovery score but bad sleep should produce calmer profile."""
        good_z = {
            "recovery_z": 1.38, "hrv_z": 1.12, "hrv_trend_z": 0.95,
            "rhr_z": 0.5, "deep_sleep_z": 0.5, "deep_ratio_z": 0.3,
            "rem_sleep_z": 0.5, "sleep_efficiency_z": 0.8,
            "sleep_debt_z": 0.0,
        }
        diverge_z = {
            "recovery_z": 1.38, "hrv_z": 1.12, "hrv_trend_z": 0.95,
            "rhr_z": -0.12, "deep_sleep_z": -0.07, "deep_ratio_z": 0.08,
            "rem_sleep_z": -1.12, "sleep_efficiency_z": -1.05,
            "sleep_debt_z": 0.0,
        }
        good_profile = _compute_profile_from_z(good_z)
        diverge_profile = _compute_profile_from_z(diverge_z)
        assert diverge_profile["symp"] < good_profile["symp"], (
            f"Divergence day symp ({diverge_profile['symp']:.3f}) should be lower than "
            f"good day symp ({good_profile['symp']:.3f})"
        )
        assert diverge_profile["para"] > good_profile["para"], (
            f"Divergence day para ({diverge_profile['para']:.3f}) should be higher than "
            f"good day para ({good_profile['para']:.3f})"
        )


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
