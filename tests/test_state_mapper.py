"""Tests for matching/state_mapper.py — state to neuro profile mapping."""

import pytest

from config import BASELINE_CALM_ANCHOR, BASELINE_ENERGY_ANCHOR, STATE_NEURO_PROFILES
from matching.state_mapper import (
    MATCHABLE_STATES,
    _blend_baseline_profile,
    _compute_sleep_quality_z,
    apply_recovery_delta_modifier,
    get_state_neuro_profile,
)


class TestGetStateNeuroProfile:
    """Tests for get_state_neuro_profile()."""

    def test_returns_profile_for_all_matchable_states(self):
        for state in MATCHABLE_STATES:
            profile = get_state_neuro_profile(state)
            assert isinstance(profile, dict)
            assert "para" in profile
            assert "symp" in profile
            assert "grnd" in profile

    def test_all_weights_in_valid_range(self):
        for state in MATCHABLE_STATES:
            profile = get_state_neuro_profile(state)
            for key, val in profile.items():
                assert 0.0 <= val <= 1.0, f"{state}.{key} = {val} out of [0, 1]"

    def test_weights_sum_to_one(self):
        for state in MATCHABLE_STATES:
            profile = get_state_neuro_profile(state)
            total = profile["para"] + profile["symp"] + profile["grnd"]
            assert total == pytest.approx(1.0, abs=0.01), (
                f"{state}: weights sum to {total}, expected ~1.0"
            )

    def test_fatigue_is_para_dominant(self):
        profile = get_state_neuro_profile("accumulated_fatigue")
        assert profile["para"] > profile["symp"]
        assert profile["para"] > profile["grnd"]

    def test_peak_is_symp_dominant(self):
        profile = get_state_neuro_profile("peak_readiness")
        assert profile["symp"] > profile["para"]
        assert profile["symp"] > profile["grnd"]

    def test_poor_sleep_is_para_and_grnd_balanced(self):
        profile = get_state_neuro_profile("poor_sleep")
        assert profile["para"] >= profile["grnd"] - 0.10
        assert profile["grnd"] >= profile["para"] - 0.10
        assert profile["symp"] < profile["para"]

    def test_poor_recovery_is_peaceful(self):
        profile = get_state_neuro_profile("poor_recovery")
        assert profile["para"] > profile["symp"]
        assert profile["grnd"] > profile["symp"]

    def test_fatigue_para_higher_than_poor_sleep_para(self):
        fatigue = get_state_neuro_profile("accumulated_fatigue")
        poor_sleep = get_state_neuro_profile("poor_sleep")
        assert fatigue["para"] > poor_sleep["para"]

    def test_poor_sleep_has_more_grounding_than_fatigue(self):
        fatigue = get_state_neuro_profile("accumulated_fatigue")
        poor_sleep = get_state_neuro_profile("poor_sleep")
        assert poor_sleep["grnd"] > fatigue["grnd"]

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError, match="insufficient_data"):
            get_state_neuro_profile("insufficient_data")

    def test_unknown_state_raises(self):
        with pytest.raises(ValueError, match="Unknown state"):
            get_state_neuro_profile("nonexistent_state")

    def test_old_states_raise(self):
        with pytest.raises(ValueError, match="Unknown state"):
            get_state_neuro_profile("physical_recovery_deficit")
        with pytest.raises(ValueError, match="Unknown state"):
            get_state_neuro_profile("emotional_processing_deficit")

    def test_matchable_states_excludes_insufficient_data(self):
        assert "insufficient_data" not in MATCHABLE_STATES

    def test_matchable_states_covers_all_profiles(self):
        assert MATCHABLE_STATES == frozenset(STATE_NEURO_PROFILES.keys())

    def test_returns_same_object_as_config(self):
        profile = get_state_neuro_profile("baseline")
        assert profile is STATE_NEURO_PROFILES["baseline"]

    def test_five_states_defined(self):
        assert len(MATCHABLE_STATES) == 5


class TestApplyRecoveryDeltaModifier:
    """Tests for apply_recovery_delta_modifier()."""

    def _baseline_profile(self):
        return {"para": 0.15, "symp": 0.50, "grnd": 0.35}

    def test_significant_positive_boosts_symp(self):
        profile = self._baseline_profile()
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        assert adjusted["symp"] > profile["symp"]
        assert reason is not None
        assert "leaning up" in reason

    def test_significant_positive_sums_to_one(self):
        profile = self._baseline_profile()
        adjusted, _ = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        total = adjusted["para"] + adjusted["symp"] + adjusted["grnd"]
        assert total == pytest.approx(1.0, abs=0.001)

    def test_significant_negative_boosts_para(self):
        profile = self._baseline_profile()
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=-50.0, delta_sd=25.4, state="baseline")
        assert adjusted["para"] > profile["para"]
        assert reason is not None
        assert "leaning down" in reason

    def test_significant_negative_sums_to_one(self):
        profile = self._baseline_profile()
        adjusted, _ = apply_recovery_delta_modifier(profile, delta=-50.0, delta_sd=25.4, state="baseline")
        total = adjusted["para"] + adjusted["symp"] + adjusted["grnd"]
        assert total == pytest.approx(1.0, abs=0.001)

    def test_normal_delta_no_change_non_baseline(self):
        """Non-baseline state with z < 1.5 threshold gets no nudge."""
        profile = self._baseline_profile()
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=10.0, delta_sd=25.4, state="poor_recovery")
        assert reason is None
        assert adjusted == profile

    def test_exactly_at_threshold_no_change_non_baseline(self):
        """Must exceed threshold, not equal (non-baseline states)."""
        profile = self._baseline_profile()
        # z = 30.0 / 20.0 = 1.5 exactly → should NOT trigger for non-baseline
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=30.0, delta_sd=20.0, state="poor_recovery")
        assert reason is None
        assert adjusted == profile

    def test_exempt_state_accumulated_fatigue(self):
        profile = {"para": 0.95, "symp": 0.00, "grnd": 0.05}
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4,
                                                         state="accumulated_fatigue")
        assert reason is None
        assert adjusted == profile

    def test_exempt_state_peak_readiness(self):
        profile = {"para": 0.00, "symp": 0.90, "grnd": 0.10}
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=-50.0, delta_sd=25.4,
                                                         state="peak_readiness")
        assert reason is None
        assert adjusted == profile

    def test_zero_sd_no_change(self):
        profile = self._baseline_profile()
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=0.0, state="baseline")
        assert reason is None
        assert adjusted == profile

    def test_no_weight_goes_negative(self):
        """Even extreme nudges should not produce negative weights."""
        profile = {"para": 0.01, "symp": 0.01, "grnd": 0.98}
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        for key in adjusted:
            assert adjusted[key] >= 0.0, f"{key} went negative: {adjusted[key]}"
        total = sum(adjusted.values())
        assert total == pytest.approx(1.0, abs=0.001)

    def test_input_dict_not_mutated(self):
        profile = self._baseline_profile()
        original = dict(profile)
        apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        assert profile == original

    def test_non_exempt_states_can_trigger(self):
        """poor_sleep, poor_recovery, baseline should all allow modifier."""
        for state in ["poor_sleep", "poor_recovery", "baseline"]:
            profile = self._baseline_profile()
            _, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state=state)
            assert reason is not None, f"{state} should allow modifier"

    def test_baseline_large_positive_uses_continuous_blend(self):
        """Baseline with large positive z uses blending, not threshold nudge."""
        profile = self._baseline_profile()
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        assert "leaning up" in reason
        # z_rec=2.2, z_sleep=0.0 (no sleep data) → z_eff=1.1 — above baseline but dampened
        assert adjusted["symp"] > 0.55

    def test_baseline_moderate_positive_uses_continuous_blend(self):
        """Baseline with moderate z (below old threshold) still triggers."""
        profile = self._baseline_profile()
        # z = 20.0 / 25.4 = 0.79 — below old 1.5 threshold, above 0.1 deadzone
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=20.0, delta_sd=25.4, state="baseline")
        assert reason is not None
        assert "leaning up" in reason
        assert adjusted["symp"] > profile["symp"]

    def test_all_weights_in_valid_range(self):
        profile = self._baseline_profile()
        adjusted, _ = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        for key, val in adjusted.items():
            assert 0.0 <= val <= 1.0, f"{key} = {val} out of [0, 1]"


class TestBlendBaselineProfile:
    """Tests for _blend_baseline_profile() — continuous baseline scaling."""

    def test_blend_baseline_z_zero_returns_current_baseline(self):
        result = _blend_baseline_profile(0.0)
        expected = STATE_NEURO_PROFILES["baseline"]
        for k in expected:
            assert result[k] == pytest.approx(expected[k], abs=1e-9), (
                f"{k}: expected {expected[k]}, got {result[k]}"
            )

    def test_blend_baseline_positive_z_boosts_symp(self):
        result = _blend_baseline_profile(1.0)
        baseline = STATE_NEURO_PROFILES["baseline"]
        assert result["symp"] > baseline["symp"]

    def test_blend_baseline_negative_z_boosts_para(self):
        result = _blend_baseline_profile(-1.0)
        baseline = STATE_NEURO_PROFILES["baseline"]
        assert result["para"] > baseline["para"]

    def test_blend_baseline_z_plus_two_matches_energy_anchor(self):
        result = _blend_baseline_profile(2.0)
        for k in BASELINE_ENERGY_ANCHOR:
            assert result[k] == pytest.approx(BASELINE_ENERGY_ANCHOR[k], abs=1e-9), (
                f"{k}: expected {BASELINE_ENERGY_ANCHOR[k]}, got {result[k]}"
            )

    def test_blend_baseline_z_minus_two_matches_calm_anchor(self):
        result = _blend_baseline_profile(-2.0)
        for k in BASELINE_CALM_ANCHOR:
            assert result[k] == pytest.approx(BASELINE_CALM_ANCHOR[k], abs=1e-9), (
                f"{k}: expected {BASELINE_CALM_ANCHOR[k]}, got {result[k]}"
            )

    def test_blend_baseline_z_clamped(self):
        """z=+5 should produce same result as z=+2 (clamped)."""
        at_clamp = _blend_baseline_profile(2.0)
        beyond_clamp = _blend_baseline_profile(5.0)
        for k in at_clamp:
            assert beyond_clamp[k] == pytest.approx(at_clamp[k], abs=1e-9)

    @pytest.mark.parametrize("z", [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0])
    def test_blend_baseline_weights_sum_to_one(self, z):
        result = _blend_baseline_profile(z)
        total = sum(result.values())
        assert total == pytest.approx(1.0, abs=1e-9), (
            f"z={z}: weights sum to {total}, expected 1.0"
        )


class TestContinuousBaselineModifier:
    """Integration tests: apply_recovery_delta_modifier with baseline + continuous blending."""

    def _baseline_profile(self):
        return {"para": 0.15, "symp": 0.50, "grnd": 0.35}

    def test_baseline_modifier_near_zero_no_reason(self):
        """z=0.05 is in the deadzone (|z| < 0.1) — no modification."""
        profile = self._baseline_profile()
        # z = 1.0 / 20.0 = 0.05
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=1.0, delta_sd=20.0, state="baseline")
        assert reason is None
        assert adjusted == profile

    def test_baseline_modifier_moderate_z_returns_reason(self):
        """z=1.0 should return a reason containing 'leaning'."""
        profile = self._baseline_profile()
        # z = 25.4 / 25.4 = 1.0
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=25.4, delta_sd=25.4, state="baseline")
        assert reason is not None
        assert "leaning" in reason

    def test_non_baseline_still_uses_threshold(self):
        """poor_recovery at z=1.0 (below 1.5 threshold) should NOT trigger."""
        profile = self._baseline_profile()
        # z = 25.4 / 25.4 = 1.0 — below 1.5 threshold
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=25.4, delta_sd=25.4, state="poor_recovery")
        assert reason is None
        assert adjusted == profile

    def test_exempt_states_still_exempt(self):
        """accumulated_fatigue is unchanged regardless of z."""
        profile = {"para": 0.95, "symp": 0.00, "grnd": 0.05}
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4,
                                                         state="accumulated_fatigue")
        assert reason is None
        assert adjusted == profile


class TestComputeSleepQualityZ:
    """Tests for _compute_sleep_quality_z() — continuous scoring."""

    def _make_sleep_analysis(self, deep_ms, rem_ms, deep_mean=5_400_000, deep_sd=900_000,
                              rem_mean=6_480_000, rem_sd=1_944_000):
        """Helper: build sleep_analysis with baselines for continuous scoring."""
        return {
            "deep_sleep_deficit": False, "rem_sleep_deficit": False,
            "deep_adequate": True, "rem_adequate": True,
            "last_night": {"deep_sleep_ms": deep_ms, "rem_sleep_ms": rem_ms, "sleep_efficiency": 90.0},
            "baselines": {
                "deep_ms": {"mean": deep_mean, "sd": deep_sd},
                "rem_ms": {"mean": rem_mean, "sd": rem_sd},
            },
        }

    def test_at_baseline_mean_returns_zero(self):
        """Deep and REM exactly at personal mean → 0.0."""
        sa = self._make_sleep_analysis(deep_ms=5_400_000, rem_ms=6_480_000)
        assert _compute_sleep_quality_z(sa) == 0.0

    def test_above_mean_returns_positive(self):
        """Deep and REM above mean → positive (capped at 1.0 each)."""
        sa = self._make_sleep_analysis(deep_ms=6_300_000, rem_ms=8_424_000)  # +1 SD each
        result = _compute_sleep_quality_z(sa)
        assert result > 0.0
        assert result <= 1.0

    def test_below_mean_returns_negative(self):
        """Deep at mean - 0.8 SD, REM at mean - 0.5 SD → negative."""
        deep_ms = 5_400_000 - int(0.8 * 900_000)  # mean - 0.8 SD
        rem_ms = 6_480_000 - int(0.5 * 1_944_000)  # mean - 0.5 SD
        sa = self._make_sleep_analysis(deep_ms=deep_ms, rem_ms=rem_ms)
        result = _compute_sleep_quality_z(sa)
        assert result < 0.0  # Below mean = negative

    def test_severe_deficit_clamped_at_minus_two(self):
        """Deep and REM at 3 SD below mean → clamped to -2.0 each, avg = -2.0."""
        sa = self._make_sleep_analysis(deep_ms=1_000_000, rem_ms=1_000_000)  # far below
        result = _compute_sleep_quality_z(sa)
        assert result == -2.0

    def test_well_above_mean_clamped_at_one(self):
        """Deep and REM at 3 SD above mean → clamped to +1.0 each, avg = 1.0."""
        sa = self._make_sleep_analysis(deep_ms=10_000_000, rem_ms=15_000_000)  # far above
        result = _compute_sleep_quality_z(sa)
        assert result == 1.0

    def test_no_data_returns_zero(self):
        assert _compute_sleep_quality_z(None) == 0.0

    def test_fallback_binary_when_no_baselines(self):
        """Without baselines, falls back to binary flags."""
        sa = {
            "deep_sleep_deficit": True, "rem_sleep_deficit": True,
            "deep_adequate": False, "rem_adequate": False,
            "last_night": {"deep_sleep_ms": 2_000_000, "rem_sleep_ms": 2_000_000},
        }
        assert _compute_sleep_quality_z(sa) == -1.0

    def test_fallback_binary_one_deficit(self):
        sa = {
            "deep_sleep_deficit": True, "rem_sleep_deficit": False,
            "deep_adequate": False, "rem_adequate": True,
        }
        assert _compute_sleep_quality_z(sa) == -0.5

    def test_fallback_binary_both_adequate(self):
        sa = {
            "deep_sleep_deficit": False, "rem_sleep_deficit": False,
            "deep_adequate": True, "rem_adequate": True,
        }
        assert _compute_sleep_quality_z(sa) == 0.5

    def test_todays_real_case(self):
        """Mar 25: deep=1.3h (mean=1.5h, sd=0.25h), REM=1.4h (mean=1.7h, sd=0.54h).
        Both below mean → z_sleep should be negative, dampening energy lean."""
        sa = self._make_sleep_analysis(
            deep_ms=4_680_000,  # 1.3h
            rem_ms=5_040_000,   # 1.4h
            deep_mean=5_400_000, deep_sd=900_000,   # 1.5h ± 0.25h
            rem_mean=6_120_000, rem_sd=1_944_000,    # 1.7h ± 0.54h
        )
        result = _compute_sleep_quality_z(sa)
        assert result < 0.0  # Below mean = dampens energy


class TestSleepDampener:
    """Tests for sleep quality dampening in the baseline modifier."""

    def _baseline_profile(self):
        return {"para": 0.15, "symp": 0.50, "grnd": 0.35}

    def test_recovery_up_sleep_good(self):
        """z_rec=1.0, good sleep (above mean) → z_eff strongly positive."""
        profile = self._baseline_profile()
        sa = {
            "deep_adequate": True, "rem_adequate": True,
            "deep_sleep_deficit": False, "rem_sleep_deficit": False,
            "last_night": {
                "deep_sleep_ms": 6_300_000, "rem_sleep_ms": 8_424_000,  # +1 SD each
                "sleep_efficiency": 92.0,
            },
            "baselines": {
                "deep_ms": {"mean": 5_400_000, "sd": 900_000},
                "rem_ms": {"mean": 6_480_000, "sd": 1_944_000},
            },
        }
        adjusted, reason = apply_recovery_delta_modifier(
            profile, delta=25.4, delta_sd=25.4, state="baseline", sleep_analysis=sa,
        )
        assert reason is not None
        assert "leaning up" in reason
        assert adjusted["symp"] > profile["symp"]

    def test_recovery_up_sleep_bad(self):
        """z_rec=1.0, z_sleep=-1.0 → z_eff=0.0 (neutralized)."""
        profile = self._baseline_profile()
        sa = {
            "deep_sleep_deficit": True, "rem_sleep_deficit": True,
            "deep_adequate": False, "rem_adequate": False,
        }
        # z_rec = 25.4 / 25.4 = 1.0, z_sleep = -1.0
        # z_eff = 0.5 * 1.0 + 0.5 * (-1.0) = 0.0
        adjusted, reason = apply_recovery_delta_modifier(
            profile, delta=25.4, delta_sd=25.4, state="baseline", sleep_analysis=sa,
        )
        # z_eff=0.0 → abs < 0.1 → no change
        assert reason is None
        assert adjusted == profile

    def test_recovery_up_sleep_neutral(self):
        """z_rec=0.7, z_sleep=0.0 → z_eff=0.35 (dampened)."""
        profile = self._baseline_profile()
        sa = {
            "deep_adequate": True, "rem_adequate": False,
            "deep_sleep_deficit": False, "rem_sleep_deficit": False,
        }
        # z_rec = 17.78 / 25.4 ≈ 0.7, z_sleep = 0.0 (mixed neutral)
        # z_eff = 0.5 * 0.7 + 0.5 * 0.0 = 0.35
        adjusted, reason = apply_recovery_delta_modifier(
            profile, delta=17.78, delta_sd=25.4, state="baseline", sleep_analysis=sa,
        )
        assert reason is not None
        assert "z_eff=0.4" in reason or "z_eff=0.3" in reason
        assert "leaning up" in reason
        # Dampened but still leaning up — symp should be above baseline but less than without dampening
        assert adjusted["symp"] > profile["symp"]

    def test_non_baseline_ignores_sleep(self):
        """Non-baseline state ignores sleep_analysis entirely."""
        profile = self._baseline_profile()
        sa = {
            "deep_sleep_deficit": True, "rem_sleep_deficit": True,
            "deep_adequate": False, "rem_adequate": False,
        }
        # z = 50.0 / 25.4 ≈ 1.97 — above 1.5 threshold for non-baseline
        adjusted_with, reason_with = apply_recovery_delta_modifier(
            profile, delta=50.0, delta_sd=25.4, state="poor_recovery", sleep_analysis=sa,
        )
        adjusted_without, reason_without = apply_recovery_delta_modifier(
            profile, delta=50.0, delta_sd=25.4, state="poor_recovery",
        )
        # Both should produce the same result — sleep_analysis is ignored for non-baseline
        assert reason_with == reason_without
        assert adjusted_with == adjusted_without
