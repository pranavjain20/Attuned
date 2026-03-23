"""Tests for matching/state_mapper.py — state to neuro profile mapping."""

import pytest

from config import STATE_NEURO_PROFILES
from matching.state_mapper import (
    MATCHABLE_STATES,
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
        assert "boosting energy" in reason
        assert "++" not in reason  # no double plus sign

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
        assert "boosting calming" in reason

    def test_significant_negative_sums_to_one(self):
        profile = self._baseline_profile()
        adjusted, _ = apply_recovery_delta_modifier(profile, delta=-50.0, delta_sd=25.4, state="baseline")
        total = adjusted["para"] + adjusted["symp"] + adjusted["grnd"]
        assert total == pytest.approx(1.0, abs=0.001)

    def test_normal_delta_no_change(self):
        profile = self._baseline_profile()
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=10.0, delta_sd=25.4, state="baseline")
        assert reason is None
        assert adjusted == profile

    def test_exactly_at_threshold_no_change(self):
        """Must exceed threshold, not equal."""
        profile = self._baseline_profile()
        # z = 30.0 / 20.0 = 1.5 exactly → should NOT trigger
        adjusted, reason = apply_recovery_delta_modifier(profile, delta=30.0, delta_sd=20.0, state="baseline")
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

    def test_all_weights_in_valid_range(self):
        profile = self._baseline_profile()
        adjusted, _ = apply_recovery_delta_modifier(profile, delta=56.0, delta_sd=25.4, state="baseline")
        for key, val in adjusted.items():
            assert 0.0 <= val <= 1.0, f"{key} = {val} out of [0, 1]"
