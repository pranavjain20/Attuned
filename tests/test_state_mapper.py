"""Tests for matching/state_mapper.py — state to neuro profile mapping."""

import pytest

from config import STATE_NEURO_PROFILES
from matching.state_mapper import MATCHABLE_STATES, get_state_neuro_profile


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

    def test_emotional_processing_is_grnd_dominant(self):
        profile = get_state_neuro_profile("emotional_processing_deficit")
        assert profile["grnd"] > profile["para"]
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

    def test_matchable_states_excludes_insufficient_data(self):
        assert "insufficient_data" not in MATCHABLE_STATES

    def test_matchable_states_covers_all_profiles(self):
        assert MATCHABLE_STATES == frozenset(STATE_NEURO_PROFILES.keys())

    def test_returns_same_object_as_config(self):
        profile = get_state_neuro_profile("baseline")
        assert profile is STATE_NEURO_PROFILES["baseline"]

    def test_seven_states_defined(self):
        assert len(MATCHABLE_STATES) == 7
