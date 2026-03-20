"""Tests for classification/profiler.py — neurological impact scoring."""

import math

import pytest

from classification.profiler import (
    NEUTRAL_BPM,
    NEUTRAL_FLOAT,
    compute_grounding,
    compute_mood_score,
    compute_neurological_profile,
    compute_parasympathetic,
    compute_sympathetic,
    gaussian,
    sigmoid_decay,
    sigmoid_rise,
)


# ---------------------------------------------------------------------------
# Sigmoid decay
# ---------------------------------------------------------------------------

class TestSigmoidDecay:
    def test_well_below_plateau_is_near_one(self):
        assert sigmoid_decay(40, plateau_below=60, decay_above=90) > 0.99

    def test_well_above_decay_is_near_zero(self):
        assert sigmoid_decay(120, plateau_below=60, decay_above=90) < 0.01

    def test_at_midpoint_is_half(self):
        result = sigmoid_decay(75, plateau_below=60, decay_above=90)
        assert abs(result - 0.5) < 0.001

    def test_monotonically_decreasing(self):
        values = [sigmoid_decay(x, 60, 90) for x in range(40, 130, 5)]
        for i in range(len(values) - 1):
            assert values[i] >= values[i + 1]

    def test_at_plateau_boundary(self):
        result = sigmoid_decay(60, plateau_below=60, decay_above=90)
        assert result > 0.93  # Should still be high at plateau boundary

    def test_at_decay_boundary(self):
        result = sigmoid_decay(90, plateau_below=60, decay_above=90)
        assert result < 0.07  # Should be low at decay boundary

    def test_zero_steepness_below_midpoint(self):
        assert sigmoid_decay(5, plateau_below=10, decay_above=10) == 1.0

    def test_zero_steepness_above_midpoint(self):
        assert sigmoid_decay(15, plateau_below=10, decay_above=10) == 0.0

    def test_output_always_between_zero_and_one(self):
        for x in [-100, 0, 50, 75, 100, 200, 500]:
            result = sigmoid_decay(x, 60, 90)
            assert 0.0 <= result <= 1.0


class TestSigmoidRise:
    def test_well_below_decay_is_near_zero(self):
        assert sigmoid_rise(60, decay_below=100, plateau_above=130) < 0.01

    def test_well_above_plateau_is_near_one(self):
        assert sigmoid_rise(170, decay_below=100, plateau_above=130) > 0.99

    def test_at_midpoint_is_half(self):
        result = sigmoid_rise(115, decay_below=100, plateau_above=130)
        assert abs(result - 0.5) < 0.001

    def test_monotonically_increasing(self):
        values = [sigmoid_rise(x, 100, 130) for x in range(60, 180, 5)]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_at_decay_boundary(self):
        result = sigmoid_rise(100, decay_below=100, plateau_above=130)
        assert result < 0.07

    def test_at_plateau_boundary(self):
        result = sigmoid_rise(130, decay_below=100, plateau_above=130)
        assert result > 0.93

    def test_zero_steepness_below_midpoint(self):
        assert sigmoid_rise(5, decay_below=10, plateau_above=10) == 0.0

    def test_zero_steepness_above_midpoint(self):
        assert sigmoid_rise(15, decay_below=10, plateau_above=10) == 1.0

    def test_output_always_between_zero_and_one(self):
        for x in [-100, 0, 80, 115, 150, 200, 500]:
            result = sigmoid_rise(x, 100, 130)
            assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Gaussian
# ---------------------------------------------------------------------------

class TestGaussian:
    def test_peak_at_center(self):
        assert gaussian(75, center=75, sigma=15) == 1.0

    def test_symmetric_around_center(self):
        left = gaussian(60, center=75, sigma=15)
        right = gaussian(90, center=75, sigma=15)
        assert abs(left - right) < 0.0001

    def test_one_sigma_away(self):
        result = gaussian(90, center=75, sigma=15)
        expected = math.exp(-0.5)
        assert abs(result - expected) < 0.0001

    def test_two_sigma_away(self):
        result = gaussian(105, center=75, sigma=15)
        expected = math.exp(-2.0)
        assert abs(result - expected) < 0.0001

    def test_far_from_center_is_near_zero(self):
        assert gaussian(200, center=75, sigma=15) < 0.001

    def test_zero_sigma_at_center(self):
        assert gaussian(75, center=75, sigma=0) == 1.0

    def test_zero_sigma_off_center(self):
        assert gaussian(76, center=75, sigma=0) == 0.0

    def test_output_always_between_zero_and_one(self):
        for x in [-50, 0, 37.5, 75, 112.5, 150, 300]:
            result = gaussian(x, center=75, sigma=15)
            assert 0.0 <= result <= 1.0

    def test_narrow_sigma_concentrates_peak(self):
        narrow = gaussian(76, center=75, sigma=1)
        wide = gaussian(76, center=75, sigma=15)
        assert narrow < wide  # narrow drops faster away from center

    def test_with_float_center(self):
        assert gaussian(0.35, center=0.35, sigma=0.2) == 1.0


# ---------------------------------------------------------------------------
# Parasympathetic scoring
# ---------------------------------------------------------------------------

class TestComputeParasympathetic:
    def test_quiet_slow_acoustic_scores_high(self):
        """A quiet acoustic ballad at 55 BPM should score very high para."""
        score = compute_parasympathetic(
            bpm=55, energy=0.1, acousticness=0.9,
            instrumentalness=0.8, valence=0.35, mode="major", danceability=0.3,
        )
        assert score > 0.8

    def test_loud_fast_electronic_scores_low(self):
        """Loud fast EDM should score very low para."""
        score = compute_parasympathetic(
            bpm=140, energy=0.95, acousticness=0.05,
            instrumentalness=0.1, valence=0.8, mode="minor", danceability=0.9,
        )
        assert score < 0.15

    def test_weights_sum_to_one(self):
        """Maximum possible score should be ~1.0 when all components + mood are at max."""
        score = compute_parasympathetic(
            bpm=40, energy=0.0, acousticness=1.0,
            instrumentalness=1.0, valence=0.35, mode="major", danceability=0.3,
            mood_tags=["spiritual", "meditative", "calm"],
        )
        assert 0.95 < score <= 1.0

    def test_all_zeros_except_bpm(self):
        score = compute_parasympathetic(
            bpm=60, energy=1.0, acousticness=0.0,
            instrumentalness=0.0, valence=0.0, mode="minor", danceability=0.0,
        )
        # Tempo contributes ~0.35, energy=0, acousticness=0, instrum=0,
        # valence gaussian at 0.0 != 0, mode=0.025
        assert 0.3 < score < 0.5

    def test_mode_major_higher_than_minor(self):
        kwargs = dict(
            bpm=70, energy=0.3, acousticness=0.7,
            instrumentalness=0.5, valence=0.35, danceability=0.3,
        )
        major = compute_parasympathetic(**kwargs, mode="major")
        minor = compute_parasympathetic(**kwargs, mode="minor")
        assert major > minor

    def test_mode_none_treated_as_non_major(self):
        kwargs = dict(
            bpm=70, energy=0.3, acousticness=0.7,
            instrumentalness=0.5, valence=0.35, danceability=0.3,
        )
        none_mode = compute_parasympathetic(**kwargs, mode=None)
        minor = compute_parasympathetic(**kwargs, mode="minor")
        assert none_mode == minor

    def test_score_always_in_range(self):
        """Score should never exceed 1.0 or go below 0.0 for any inputs."""
        extremes = [
            (30, 0.0, 1.0, 1.0, 0.35, "major", 0.3),
            (200, 1.0, 0.0, 0.0, 1.0, "minor", 1.0),
            (75, 0.5, 0.5, 0.5, 0.5, None, 0.5),
        ]
        for args in extremes:
            score = compute_parasympathetic(*args)
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Sympathetic scoring
# ---------------------------------------------------------------------------

class TestComputeSympathetic:
    def test_loud_fast_pop_scores_high(self):
        """Loud fast pop should score high sympathetic."""
        score = compute_sympathetic(
            bpm=140, energy=0.95, acousticness=0.05,
            instrumentalness=0.1, valence=0.9, mode="minor", danceability=0.9,
        )
        assert score > 0.8

    def test_quiet_slow_acoustic_scores_low(self):
        """Quiet slow acoustic should score low sympathetic."""
        score = compute_sympathetic(
            bpm=55, energy=0.1, acousticness=0.9,
            instrumentalness=0.8, valence=0.1, mode="major", danceability=0.1,
        )
        assert score < 0.20

    def test_weights_sum_to_one_at_max(self):
        score = compute_sympathetic(
            bpm=160, energy=1.0, acousticness=0.0,
            instrumentalness=0.0, valence=1.0, mode="minor", danceability=1.0,
            mood_tags=["energetic", "uplifting", "celebratory"],
        )
        assert 0.95 < score <= 1.0

    def test_mode_minor_higher_than_major(self):
        """For sympathetic, minor mode scores higher (1.0 vs 0.8)."""
        kwargs = dict(
            bpm=130, energy=0.7, acousticness=0.2,
            instrumentalness=0.2, valence=0.7, danceability=0.8,
        )
        major = compute_sympathetic(**kwargs, mode="major")
        minor = compute_sympathetic(**kwargs, mode="minor")
        assert minor > major

    def test_score_always_in_range(self):
        extremes = [
            (200, 1.0, 0.0, 0.0, 1.0, "minor", 1.0),
            (30, 0.0, 1.0, 1.0, 0.0, "major", 0.0),
            (115, 0.5, 0.5, 0.5, 0.5, None, 0.5),
        ]
        for args in extremes:
            score = compute_sympathetic(*args)
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Grounding scoring
# ---------------------------------------------------------------------------

class TestComputeGrounding:
    def test_perfect_grounding_song(self):
        """Song right at all Gaussian centers should score high."""
        score = compute_grounding(
            bpm=90, energy=0.40, acousticness=0.5,
            instrumentalness=0.0, valence=0.55, mode="major", danceability=0.4,
        )
        assert score > 0.85

    def test_extreme_bpm_scores_lower(self):
        """Very fast or very slow BPM should reduce grounding."""
        high_bpm = compute_grounding(
            bpm=160, energy=0.40, acousticness=0.5,
            instrumentalness=0.0, valence=0.55, mode="major", danceability=0.4,
        )
        centered = compute_grounding(
            bpm=90, energy=0.40, acousticness=0.5,
            instrumentalness=0.0, valence=0.55, mode="major", danceability=0.4,
        )
        assert centered > high_bpm

    def test_bpm_gaussian_symmetric(self):
        """BPM 75 and BPM 105 are equidistant from center=90."""
        kwargs = dict(
            energy=0.40, acousticness=0.5,
            instrumentalness=0.0, valence=0.55, mode="major", danceability=0.4,
        )
        low = compute_grounding(bpm=75, **kwargs)
        high = compute_grounding(bpm=105, **kwargs)
        assert abs(low - high) < 0.001

    def test_mode_major_higher_than_minor(self):
        kwargs = dict(
            bpm=90, energy=0.40, acousticness=0.5,
            instrumentalness=0.0, valence=0.55, danceability=0.4,
        )
        major = compute_grounding(**kwargs, mode="major")
        minor = compute_grounding(**kwargs, mode="minor")
        assert major > minor

    def test_vocals_score_higher_than_instrumental(self):
        """Grounding rewards vocals (low instrumentalness) for emotional connection."""
        kwargs = dict(
            bpm=90, energy=0.40, acousticness=0.5,
            valence=0.55, mode="major", danceability=0.4,
        )
        vocal = compute_grounding(**kwargs, instrumentalness=0.0)
        instrum = compute_grounding(**kwargs, instrumentalness=1.0)
        assert vocal > instrum

    def test_score_always_in_range(self):
        extremes = [
            (90, 0.40, 0.5, 0.0, 0.55, "major", 0.4),
            (200, 1.0, 0.0, 1.0, 0.0, "minor", 1.0),
            (30, 0.0, 0.0, 0.0, 1.0, None, 0.0),
        ]
        for args in extremes:
            score = compute_grounding(*args)
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Neurological profile (public API)
# ---------------------------------------------------------------------------

class TestComputeNeurologicalProfile:
    def test_returns_all_three_scores(self):
        profile = compute_neurological_profile(
            bpm=100, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert "parasympathetic" in profile
        assert "sympathetic" in profile
        assert "grounding" in profile

    def test_all_scores_in_zero_one(self):
        profile = compute_neurological_profile(
            bpm=120, energy=0.7, acousticness=0.3,
            instrumentalness=0.2, valence=0.8, mode="minor", danceability=0.9,
        )
        for key, val in profile.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of range"

    def test_none_bpm_uses_neutral(self):
        """When BPM is None, use NEUTRAL_BPM=100."""
        none_result = compute_neurological_profile(
            bpm=None, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        explicit = compute_neurological_profile(
            bpm=NEUTRAL_BPM, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert none_result == explicit

    def test_none_energy_uses_neutral(self):
        none_result = compute_neurological_profile(
            bpm=100, energy=None, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        explicit = compute_neurological_profile(
            bpm=100, energy=NEUTRAL_FLOAT, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert none_result == explicit

    def test_all_none_produces_mid_range_scores(self):
        """All None inputs → neutral defaults → mid-range scores."""
        profile = compute_neurological_profile(
            bpm=None, energy=None, acousticness=None,
            instrumentalness=None, valence=None, mode=None, danceability=None,
        )
        for key, val in profile.items():
            assert 0.15 < val < 0.85, f"{key}={val} unexpectedly extreme with all-None inputs"

    def test_integer_bpm_accepted(self):
        """BPM can be int or float."""
        profile = compute_neurological_profile(
            bpm=120, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert isinstance(profile["parasympathetic"], float)

    def test_scores_rounded_to_four_decimals(self):
        profile = compute_neurological_profile(
            bpm=87, energy=0.43, acousticness=0.62,
            instrumentalness=0.31, valence=0.55, mode="minor", danceability=0.44,
        )
        for val in profile.values():
            s = str(val)
            if "." in s:
                decimals = len(s.split(".")[1])
                assert decimals <= 4

    # --- Known-song sanity checks ---

    def test_quiet_acoustic_ballad_high_para_low_symp(self):
        """Kun Faya Kun archetype: soft, slow, acoustic, devotional."""
        profile = compute_neurological_profile(
            bpm=60, energy=0.15, acousticness=0.9,
            instrumentalness=0.7, valence=0.3, mode="major", danceability=0.2,
        )
        assert profile["parasympathetic"] > 0.7
        assert profile["sympathetic"] < 0.25

    def test_loud_pop_banger_high_symp_low_para(self):
        """Levitating archetype: loud, fast, electronic, high energy."""
        profile = compute_neurological_profile(
            bpm=135, energy=0.9, acousticness=0.1,
            instrumentalness=0.05, valence=0.85, mode="major", danceability=0.9,
        )
        assert profile["sympathetic"] > 0.7
        assert profile["parasympathetic"] < 0.2

    def test_mid_tempo_acoustic_high_grounding(self):
        """Namo Namo archetype: ~85 BPM, moderate energy, acoustic, warm."""
        profile = compute_neurological_profile(
            bpm=85, energy=0.35, acousticness=0.8,
            instrumentalness=0.3, valence=0.45, mode="major", danceability=0.4,
        )
        assert profile["grounding"] > 0.7

    def test_extreme_bpm_low_grounding(self):
        """Very fast BPM should reduce grounding significantly vs centered BPM."""
        centered = compute_neurological_profile(
            bpm=85, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        extreme = compute_neurological_profile(
            bpm=160, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert centered["grounding"] > extreme["grounding"] + 0.15

    def test_para_and_symp_inversely_correlated(self):
        """A calming song should have higher para than symp, and vice versa."""
        calming = compute_neurological_profile(
            bpm=55, energy=0.1, acousticness=0.9,
            instrumentalness=0.8, valence=0.3, mode="major", danceability=0.2,
        )
        assert calming["parasympathetic"] > calming["sympathetic"]

        energizing = compute_neurological_profile(
            bpm=140, energy=0.9, acousticness=0.1,
            instrumentalness=0.1, valence=0.9, mode="minor", danceability=0.9,
        )
        assert energizing["sympathetic"] > energizing["parasympathetic"]

    def test_none_mode_does_not_crash(self):
        profile = compute_neurological_profile(
            bpm=100, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode=None, danceability=0.5,
        )
        assert all(0 <= v <= 1 for v in profile.values())

    def test_boundary_bpm_zero(self):
        profile = compute_neurological_profile(
            bpm=0, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert profile["parasympathetic"] > profile["sympathetic"]

    def test_boundary_bpm_300(self):
        profile = compute_neurological_profile(
            bpm=300, energy=0.5, acousticness=0.5,
            instrumentalness=0.5, valence=0.5, mode="major", danceability=0.5,
        )
        assert profile["sympathetic"] > profile["parasympathetic"]

    def test_boundary_all_properties_at_zero(self):
        profile = compute_neurological_profile(
            bpm=0, energy=0.0, acousticness=0.0,
            instrumentalness=0.0, valence=0.0, mode="minor", danceability=0.0,
        )
        for val in profile.values():
            assert 0.0 <= val <= 1.0

    def test_boundary_all_properties_at_one(self):
        profile = compute_neurological_profile(
            bpm=300, energy=1.0, acousticness=1.0,
            instrumentalness=1.0, valence=1.0, mode="major", danceability=1.0,
        )
        for val in profile.values():
            assert 0.0 <= val <= 1.0

    def test_mood_tags_boost_para(self):
        """Spiritual/melancholy tags should boost parasympathetic."""
        base = compute_neurological_profile(
            bpm=80, energy=0.4, acousticness=0.5,
            instrumentalness=0.3, valence=0.4, mode="major", danceability=0.4,
        )
        with_tags = compute_neurological_profile(
            bpm=80, energy=0.4, acousticness=0.5,
            instrumentalness=0.3, valence=0.4, mode="major", danceability=0.4,
            mood_tags=["spiritual", "melancholy", "calm"],
        )
        assert with_tags["parasympathetic"] > base["parasympathetic"]

    def test_mood_tags_boost_symp(self):
        """Energetic/uplifting tags should boost sympathetic."""
        base = compute_neurological_profile(
            bpm=100, energy=0.6, acousticness=0.3,
            instrumentalness=0.1, valence=0.7, mode="major", danceability=0.7,
        )
        with_tags = compute_neurological_profile(
            bpm=100, energy=0.6, acousticness=0.3,
            instrumentalness=0.1, valence=0.7, mode="major", danceability=0.7,
            mood_tags=["energetic", "uplifting", "celebratory"],
        )
        assert with_tags["sympathetic"] > base["sympathetic"]

    def test_mood_tags_boost_grnd(self):
        """Reflective/nostalgic tags should boost grounding."""
        base = compute_neurological_profile(
            bpm=90, energy=0.4, acousticness=0.5,
            instrumentalness=0.1, valence=0.5, mode="major", danceability=0.4,
        )
        with_tags = compute_neurological_profile(
            bpm=90, energy=0.4, acousticness=0.5,
            instrumentalness=0.1, valence=0.5, mode="major", danceability=0.4,
            mood_tags=["reflective", "nostalgic", "romantic"],
        )
        assert with_tags["grounding"] > base["grounding"]

    def test_mood_tags_differentiate_para_from_grnd(self):
        """Same audio properties, different mood tags → different dominant score."""
        calming_tags = ["spiritual", "meditative", "calm"]
        grounding_tags = ["reflective", "introspective", "nostalgic"]

        para_song = compute_neurological_profile(
            bpm=75, energy=0.3, acousticness=0.7,
            instrumentalness=0.3, valence=0.4, mode="major", danceability=0.3,
            mood_tags=calming_tags,
        )
        grnd_song = compute_neurological_profile(
            bpm=75, energy=0.3, acousticness=0.7,
            instrumentalness=0.3, valence=0.4, mode="major", danceability=0.3,
            mood_tags=grounding_tags,
        )
        # Same audio → para song should have higher para due to mood tags
        assert para_song["parasympathetic"] > grnd_song["parasympathetic"]
        # Same audio → grnd song should have higher grounding due to mood tags
        assert grnd_song["grounding"] > para_song["grounding"]


# ---------------------------------------------------------------------------
# Mood score computation
# ---------------------------------------------------------------------------

class TestComputeMoodScore:

    def test_all_matching_tags(self):
        from config import PARA_MOOD_TAGS
        score = compute_mood_score(["spiritual", "calm", "meditative"], PARA_MOOD_TAGS)
        assert score == pytest.approx(1.0)

    def test_no_matching_tags(self):
        from config import PARA_MOOD_TAGS
        score = compute_mood_score(["energetic", "uplifting"], PARA_MOOD_TAGS)
        assert score == pytest.approx(0.0)

    def test_partial_matching(self):
        from config import GRND_MOOD_TAGS
        # 2 of 4 tags match grounding
        score = compute_mood_score(["reflective", "energetic", "nostalgic", "upbeat"], GRND_MOOD_TAGS)
        assert score == pytest.approx(0.5)

    def test_none_tags_returns_neutral(self):
        from config import PARA_MOOD_TAGS
        score = compute_mood_score(None, PARA_MOOD_TAGS)
        assert score == pytest.approx(0.5)

    def test_empty_tags_returns_neutral(self):
        from config import PARA_MOOD_TAGS
        score = compute_mood_score([], PARA_MOOD_TAGS)
        assert score == pytest.approx(0.5)

    def test_case_insensitive(self):
        from config import SYMP_MOOD_TAGS
        score = compute_mood_score(["Energetic", "UPLIFTING"], SYMP_MOOD_TAGS)
        assert score == pytest.approx(1.0)
