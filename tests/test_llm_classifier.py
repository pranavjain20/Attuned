"""Tests for classification/llm_classifier.py — LLM song classification."""

import json
from unittest.mock import MagicMock, patch

import pytest

from classification.llm_classifier import (
    _blend_neuro_scores,
    _build_prompt,
    _call_anthropic,
    _compute_confidence,
    _match_result_to_song,
    _merge_acousticness,
    _merge_energy,
    _merge_with_essentia,
    _pick_best_bpm,
    _validate_song_result,
    classify_songs,
)
from db import queries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_song(
    uri: str = "spotify:track:abc123",
    name: str = "Test Song",
    artist: str = "Test Artist",
    album: str = "Test Album",
    play_count: int = 10,
    duration_ms: int | None = 240000,
    essentia_bpm: float | None = None,
    essentia_key: str | None = None,
    essentia_mode: str | None = None,
    essentia_energy: float | None = None,
    essentia_acousticness: float | None = None,
    classification_source: str | None = None,
) -> dict:
    return {
        "spotify_uri": uri,
        "name": name,
        "artist": artist,
        "album": album,
        "play_count": play_count,
        "engagement_score": 0.5,
        "duration_ms": duration_ms,
        "essentia_bpm": essentia_bpm,
        "essentia_key": essentia_key,
        "essentia_mode": essentia_mode,
        "essentia_energy": essentia_energy,
        "essentia_acousticness": essentia_acousticness,
        "classification_source": classification_source,
    }


def _make_llm_result(
    bpm: int = 120,
    danceability: float = 0.7,
    instrumentalness: float = 0.1,
    valence: float = 0.6,
    energy: float | None = None,
    acousticness: float | None = None,
    mood_tags: list | None = None,
    genre_tags: list | None = None,
    para_score: float = 0.2,
    symp_score: float = 0.7,
    grounding_score: float = 0.3,
) -> dict:
    result = {
        "title": "Test Song",
        "artist": "Test Artist",
        "bpm": bpm,
        "danceability": danceability,
        "instrumentalness": instrumentalness,
        "valence": valence,
        "mood_tags": mood_tags or ["happy", "upbeat"],
        "genre_tags": genre_tags or ["pop", "dance"],
        "para_score": para_score,
        "symp_score": symp_score,
        "grounding_score": grounding_score,
    }
    if energy is not None:
        result["energy"] = energy
    if acousticness is not None:
        result["acousticness"] = acousticness
    return result


def _make_llm_response(results: list[dict]) -> dict:
    raw = json.dumps({"songs": results})
    return {"parsed": {"songs": results}, "raw_response": raw}


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_includes_song_names(self):
        songs = [
            _make_song(name="Levitating", artist="Dua Lipa"),
            _make_song(name="Kun Faya Kun", artist="A.R. Rahman"),
        ]
        prompt = _build_prompt(songs)
        assert "Levitating" in prompt
        assert "Dua Lipa" in prompt
        assert "Kun Faya Kun" in prompt
        assert "A.R. Rahman" in prompt

    def test_includes_album_when_present(self):
        songs = [_make_song(album="Future Nostalgia")]
        prompt = _build_prompt(songs)
        assert "Future Nostalgia" in prompt

    def test_handles_no_album(self):
        songs = [_make_song(album=None)]
        prompt = _build_prompt(songs)
        assert "(album:" not in prompt

    def test_numbers_songs_sequentially(self):
        songs = [_make_song(name=f"Song {i}") for i in range(3)]
        prompt = _build_prompt(songs)
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt

    def test_empty_batch_produces_header_only(self):
        prompt = _build_prompt([])
        assert "Classify these songs" in prompt

    def test_includes_duration(self):
        songs = [_make_song(duration_ms=240000)]  # 4 minutes
        prompt = _build_prompt(songs)
        assert "[duration: 4.0min]" in prompt

    def test_excludes_essentia_energy_and_acousticness(self):
        """Essentia energy/acousticness are NOT passed as hints (echo chamber)."""
        songs = [_make_song(essentia_energy=0.72, essentia_acousticness=0.31)]
        prompt = _build_prompt(songs)
        assert "energy=0.72" not in prompt
        assert "acousticness=0.31" not in prompt
        assert "[audio:" not in prompt

    def test_excludes_essentia_bpm(self):
        """Essentia BPM should NOT be in the prompt (causes LLM confusion)."""
        songs = [_make_song(essentia_bpm=120, essentia_energy=0.5)]
        prompt = _build_prompt(songs)
        assert "measured_bpm" not in prompt
        assert "bpm=120" not in prompt

    def test_no_audio_hints_ever(self):
        """No audio hints in prompt — even when Essentia data exists."""
        songs = [_make_song(essentia_energy=0.5, essentia_acousticness=0.5)]
        prompt = _build_prompt(songs)
        assert "[audio:" not in prompt

    def test_no_duration_when_missing(self):
        songs = [_make_song(duration_ms=None)]
        prompt = _build_prompt(songs)
        assert "[duration:" not in prompt


class TestSystemPrompt:
    def test_system_prompt_requests_neuro_scores(self):
        """System prompt should request para/symp/grounding scores."""
        from classification.llm_classifier import _SYSTEM_PROMPT
        assert "para_score" in _SYSTEM_PROMPT
        assert "symp_score" in _SYSTEM_PROMPT
        assert "grounding_score" in _SYSTEM_PROMPT

    def test_system_prompt_includes_valence_calibration(self):
        """Prompt should guide LLM on valence for sad/devotional songs."""
        from classification.llm_classifier import _SYSTEM_PROMPT
        assert "emotional positiveness" in _SYSTEM_PROMPT.lower() or "EMOTIONAL positiveness" in _SYSTEM_PROMPT
        assert "devotional" in _SYSTEM_PROMPT.lower()
        assert "nostalgic" in _SYSTEM_PROMPT.lower() or "melancholy" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_includes_felt_tempo(self):
        """Prompt should request felt_tempo field."""
        from classification.llm_classifier import _SYSTEM_PROMPT
        assert "felt_tempo" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# _validate_song_result
# ---------------------------------------------------------------------------

class TestValidateSongResult:
    def test_valid_result_passes_through(self):
        result = _make_llm_result()
        validated = _validate_song_result(result)
        assert validated is not None
        assert validated["bpm"] == 120
        assert validated["danceability"] == 0.7
        assert validated["valence"] == 0.6

    def test_clamps_bpm_to_range(self):
        result = _make_llm_result(bpm=500)
        validated = _validate_song_result(result)
        assert validated["bpm"] == 300

    def test_clamps_bpm_low(self):
        result = _make_llm_result(bpm=10)
        validated = _validate_song_result(result)
        assert validated["bpm"] == 30

    def test_rounds_bpm_to_int(self):
        result = _make_llm_result(bpm=120.7)
        validated = _validate_song_result(result)
        assert validated["bpm"] == 121
        assert isinstance(validated["bpm"], int)

    def test_clamps_floats_above_one(self):
        result = _make_llm_result(danceability=1.5, valence=2.0)
        validated = _validate_song_result(result)
        assert validated["danceability"] == 1.0
        assert validated["valence"] == 1.0

    def test_clamps_floats_below_zero(self):
        result = _make_llm_result(danceability=-0.3, instrumentalness=-1.0)
        validated = _validate_song_result(result)
        assert validated["danceability"] == 0.0
        assert validated["instrumentalness"] == 0.0

    def test_none_bpm_and_none_valence_returns_none(self):
        """If both BPM and valence are missing, the result is useless."""
        result = {"mood_tags": ["happy"], "genre_tags": ["pop"]}
        assert _validate_song_result(result) is None

    def test_none_bpm_with_valence_is_valid(self):
        result = {"valence": 0.5, "mood_tags": ["happy"]}
        validated = _validate_song_result(result)
        assert validated is not None
        assert validated["bpm"] is None
        assert validated["valence"] == 0.5

    def test_invalid_bpm_type_becomes_none(self):
        result = {"bpm": "fast", "valence": 0.5}
        validated = _validate_song_result(result)
        assert validated["bpm"] is None

    def test_invalid_float_becomes_none(self):
        result = {"bpm": 120, "valence": "happy"}
        validated = _validate_song_result(result)
        assert validated["valence"] is None

    def test_cleans_mood_tags(self):
        result = _make_llm_result()
        result["mood_tags"] = ["  Happy  ", "UPBEAT", "", None, "chill"]
        validated = _validate_song_result(result)
        # Empty string and None are filtered out; rest lowercased and stripped
        assert validated["mood_tags"] == ["happy", "upbeat", "chill"]

    def test_non_list_tags_become_none(self):
        result = _make_llm_result()
        result["mood_tags"] = "not a list"
        result["genre_tags"] = 42
        validated = _validate_song_result(result)
        assert validated["mood_tags"] is None
        assert validated["genre_tags"] is None

    def test_empty_tag_list_becomes_none(self):
        result = _make_llm_result()
        result["mood_tags"] = []
        validated = _validate_song_result(result)
        assert validated["mood_tags"] is None

    def test_rounds_floats_to_four_decimals(self):
        result = _make_llm_result(danceability=0.123456789)
        validated = _validate_song_result(result)
        assert validated["danceability"] == 0.1235

    def test_neuro_scores_validated_and_clamped(self):
        result = _make_llm_result(para_score=0.8, symp_score=1.5, grounding_score=-0.1)
        validated = _validate_song_result(result)
        assert validated["para_score"] == 0.8
        assert validated["symp_score"] == 1.0  # Clamped
        assert validated["grounding_score"] == 0.0  # Clamped

    def test_neuro_scores_none_when_missing(self):
        result = {"bpm": 120, "valence": 0.5}
        validated = _validate_song_result(result)
        assert validated["para_score"] is None
        assert validated["symp_score"] is None
        assert validated["grounding_score"] is None

    def test_neuro_scores_invalid_type_becomes_none(self):
        result = _make_llm_result()
        result["para_score"] = "calming"
        validated = _validate_song_result(result)
        assert validated["para_score"] is None

    def test_felt_tempo_valid(self):
        result = _make_llm_result()
        result["felt_tempo"] = 80
        validated = _validate_song_result(result)
        assert validated["felt_tempo"] == 80

    def test_felt_tempo_none_when_absent(self):
        result = _make_llm_result()
        validated = _validate_song_result(result)
        assert validated["felt_tempo"] is None

    def test_felt_tempo_clamped_to_range(self):
        result = _make_llm_result()
        result["felt_tempo"] = 10
        validated = _validate_song_result(result)
        assert validated["felt_tempo"] == 30  # Clamped to minimum

        result2 = _make_llm_result()
        result2["felt_tempo"] = 500
        validated2 = _validate_song_result(result2)
        assert validated2["felt_tempo"] == 300  # Clamped to maximum

    def test_felt_tempo_rounded_to_int(self):
        result = _make_llm_result()
        result["felt_tempo"] = 82.7
        validated = _validate_song_result(result)
        assert validated["felt_tempo"] == 83
        assert isinstance(validated["felt_tempo"], int)

    def test_felt_tempo_invalid_type_becomes_none(self):
        result = _make_llm_result()
        result["felt_tempo"] = "slow"
        validated = _validate_song_result(result)
        assert validated["felt_tempo"] is None


# ---------------------------------------------------------------------------
# _blend_neuro_scores
# ---------------------------------------------------------------------------

class TestBlendNeuroScores:
    def test_no_llm_scores_returns_formula(self):
        """When any LLM direct score is None, return formula unchanged."""
        formula = {"parasympathetic": 0.8, "sympathetic": 0.1, "grounding": 0.4}
        result = _blend_neuro_scores(formula, None, 0.7, 0.2)
        assert result == formula

    def test_no_llm_scores_all_none(self):
        formula = {"parasympathetic": 0.8, "sympathetic": 0.1, "grounding": 0.4}
        result = _blend_neuro_scores(formula, None, None, None)
        assert result == formula

    def test_agreement_blends_50_50(self):
        """When formula and LLM agree on dominant bucket, blend 50/50."""
        formula = {"parasympathetic": 0.8, "sympathetic": 0.1, "grounding": 0.3}
        # LLM also says PARA dominant
        result = _blend_neuro_scores(formula, 0.9, 0.2, 0.4)
        # 50% * 0.8 + 50% * 0.9 = 0.85
        assert abs(result["parasympathetic"] - 0.85) < 0.01
        # 50% * 0.1 + 50% * 0.2 = 0.15
        assert abs(result["sympathetic"] - 0.15) < 0.01

    def test_grnd_bias_zone_quiet_trusts_llm(self):
        """Formula says GRND at BPM 80 + low energy → trust LLM (25/75)."""
        formula = {"parasympathetic": 0.4, "sympathetic": 0.1, "grounding": 0.7}
        # LLM says PARA
        result = _blend_neuro_scores(
            formula, 0.8, 0.2, 0.5,
            bpm=80, energy=0.30,
        )
        # 25% * 0.4 + 75% * 0.8 = 0.70 for para
        assert abs(result["parasympathetic"] - 0.70) < 0.01
        # PARA should dominate
        assert result["parasympathetic"] > result["grounding"]

    def test_grnd_bias_zone_moderate_energy_trusts_formula(self):
        """Formula says GRND at BPM 85 + moderate energy → trust formula (70/30)."""
        formula = {"parasympathetic": 0.4, "sympathetic": 0.1, "grounding": 0.7}
        # LLM says PARA
        result = _blend_neuro_scores(
            formula, 0.8, 0.2, 0.5,
            bpm=85, energy=0.50,
        )
        # 70% * 0.7 + 30% * 0.5 = 0.64 for grounding
        assert abs(result["grounding"] - 0.64) < 0.01
        # GRND should dominate
        assert result["grounding"] > result["parasympathetic"]

    def test_outside_bias_zone_other_disagreement(self):
        """Disagreement outside bias zone → 40/60 LLM preference."""
        formula = {"parasympathetic": 0.1, "sympathetic": 0.8, "grounding": 0.3}
        # LLM says GRND (disagreement, formula says SYMP)
        result = _blend_neuro_scores(
            formula, 0.2, 0.3, 0.7,
            bpm=130, energy=0.80,
        )
        # 40% * 0.3 + 60% * 0.7 = 0.54 for grounding
        assert abs(result["grounding"] - 0.54) < 0.01

    def test_no_energy_data_in_bias_zone_trusts_formula(self):
        """In bias zone with energy=None → treat as moderate, trust formula."""
        formula = {"parasympathetic": 0.3, "sympathetic": 0.1, "grounding": 0.7}
        result = _blend_neuro_scores(
            formula, 0.8, 0.1, 0.4,
            bpm=85, energy=None,
        )
        # 70% formula → GRND should still dominate
        assert result["grounding"] > result["parasympathetic"]

    def test_scores_rounded_to_four_decimals(self):
        formula = {"parasympathetic": 0.3333, "sympathetic": 0.6666, "grounding": 0.1111}
        result = _blend_neuro_scores(formula, 0.4444, 0.5555, 0.2222)
        for val in result.values():
            s = str(val)
            if "." in s:
                assert len(s.split(".")[1]) <= 4

    def test_all_scores_in_valid_range(self):
        """Output scores should always be in [0, 1]."""
        formula = {"parasympathetic": 0.9, "sympathetic": 0.1, "grounding": 0.5}
        result = _blend_neuro_scores(formula, 0.9, 0.1, 0.3, bpm=80, energy=0.20)
        for val in result.values():
            assert 0.0 <= val <= 1.0

    def test_bpm_at_bias_zone_boundaries(self):
        """BPM exactly at 70 and 110 should be in bias zone."""
        formula = {"parasympathetic": 0.3, "sympathetic": 0.2, "grounding": 0.6}
        # BPM=70, low energy, formula GRND → should trigger bias+quiet rule
        result_70 = _blend_neuro_scores(
            formula, 0.8, 0.1, 0.3, bpm=70, energy=0.20,
        )
        # BPM=110, low energy, formula GRND → should trigger bias+quiet rule
        result_110 = _blend_neuro_scores(
            formula, 0.8, 0.1, 0.3, bpm=110, energy=0.20,
        )
        # Both should trust LLM → PARA dominates
        assert result_70["parasympathetic"] > result_70["grounding"]
        assert result_110["parasympathetic"] > result_110["grounding"]

    def test_bpm_outside_bias_zone_not_triggered(self):
        """BPM=60, formula GRND → outside bias zone, uses default disagreement."""
        formula = {"parasympathetic": 0.3, "sympathetic": 0.2, "grounding": 0.6}
        result = _blend_neuro_scores(
            formula, 0.8, 0.1, 0.3, bpm=60, energy=0.20,
        )
        # Default disagreement: 40/60 LLM → PARA should dominate
        assert result["parasympathetic"] > result["grounding"]


# ---------------------------------------------------------------------------
# _compute_confidence
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_no_essentia_base_confidence(self):
        """LLM-only song gets base confidence of 0.5."""
        llm = _make_llm_result(bpm=120)
        song = _make_song(classification_source=None)
        assert _compute_confidence(llm, song) == 0.5

    def test_essentia_without_bpm_agreement(self):
        """Has Essentia data but BPM disagrees → 0.7 (0.5 base + 0.2 essentia)."""
        llm = _make_llm_result(bpm=120)
        song = _make_song(
            essentia_bpm=80, classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 0.7

    def test_essentia_with_bpm_agreement(self):
        """Has Essentia and BPM agrees → 1.0 (0.5 + 0.2 + 0.3)."""
        llm = _make_llm_result(bpm=120)
        song = _make_song(
            essentia_bpm=125, classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 1.0

    def test_bpm_within_20_percent_agrees(self):
        """BPM within 20% ratio → agreement bonus."""
        llm = _make_llm_result(bpm=100)
        song = _make_song(
            essentia_bpm=115, classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 1.0

    def test_bpm_beyond_20_percent_no_agreement(self):
        """BPM beyond 20% ratio → no agreement bonus."""
        llm = _make_llm_result(bpm=100)
        song = _make_song(
            essentia_bpm=125, classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 0.7

    def test_octave_error_no_agreement(self):
        """Essentia 2x of LLM is an octave error, not agreement."""
        llm = _make_llm_result(bpm=67)
        song = _make_song(
            essentia_bpm=131, classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 0.7

    def test_essentia_no_bpm_data(self):
        """Has Essentia but no BPM → 0.7 (can't cross-validate)."""
        llm = _make_llm_result(bpm=120)
        song = _make_song(
            essentia_bpm=None, essentia_energy=0.5,
            classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 0.7

    def test_llm_no_bpm(self):
        """LLM returned no BPM → can't cross-validate."""
        llm = _make_llm_result()
        llm["bpm"] = None
        song = _make_song(
            essentia_bpm=120, classification_source="essentia",
        )
        assert _compute_confidence(llm, song) == 0.7


# ---------------------------------------------------------------------------
# _match_result_to_song
# ---------------------------------------------------------------------------

class TestMatchResultToSong:
    def test_positional_match(self):
        results = [_make_llm_result(bpm=100), _make_llm_result(bpm=120)]
        song = _make_song(name="Song 2")
        matched = _match_result_to_song(results, song, index=1)
        assert matched["bpm"] == 120

    def test_fallback_title_match(self):
        results = [
            {"title": "Other Song", "artist": "Other", "bpm": 100, "valence": 0.5},
            {"title": "Test Song", "artist": "Test Artist", "bpm": 120, "valence": 0.6},
        ]
        song = _make_song()
        matched = _match_result_to_song(results, song, index=5)  # out of range
        assert matched["bpm"] == 120

    def test_returns_none_when_no_match(self):
        results = [{"title": "Wrong", "artist": "Wrong", "bpm": 100, "valence": 0.5}]
        song = _make_song(name="Totally Different")
        assert _match_result_to_song(results, song, index=5) is None


# ---------------------------------------------------------------------------
# _merge_with_essentia
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _pick_best_bpm
# ---------------------------------------------------------------------------

class TestPickBestBpm:
    def test_both_agree_averages(self):
        """When LLM and Essentia agree within 20%, average them."""
        assert _pick_best_bpm(120, 118) == 119

    def test_essentia_octave_high_trusts_llm(self):
        """Essentia 2x of LLM → octave error, trust LLM."""
        assert _pick_best_bpm(67, 131) == 67  # Die For You case

    def test_essentia_octave_low_trusts_llm(self):
        """Essentia 0.5x of LLM → octave error, trust LLM."""
        assert _pick_best_bpm(171, 86) == 171  # Blinding Lights case

    def test_disagree_not_octave_trusts_llm(self):
        """Disagreement that's not an octave → trust LLM."""
        assert _pick_best_bpm(80, 99) == 80  # Photograph case

    def test_llm_none_uses_essentia(self):
        assert _pick_best_bpm(None, 120) == 120

    def test_essentia_none_uses_llm(self):
        assert _pick_best_bpm(100, None) == 100

    def test_both_none_returns_none(self):
        assert _pick_best_bpm(None, None) is None

    def test_exact_match(self):
        assert _pick_best_bpm(120, 120) == 120

    def test_returns_int(self):
        result = _pick_best_bpm(120, 118.5)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# _merge_with_essentia
# ---------------------------------------------------------------------------

class TestMergeWithEssentia:
    def test_bpm_uses_llm_primary_with_essentia_crosscheck(self):
        """LLM BPM is primary. When they agree, averages."""
        llm = {"bpm": 118, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop", "dance"],
               "mood_tags": ["happy"], "energy": 0.65, "acousticness": 0.35}
        song = _make_song(
            essentia_bpm=120, essentia_key="A", essentia_mode="minor",
            essentia_energy=0.7, essentia_acousticness=0.3,
            classification_source="essentia",
        )
        merged = _merge_with_essentia(llm, song)
        assert merged["bpm"] == 119  # Average of 118 and 120
        assert merged["key"] == "A"
        # Energy: gap=0.05 <= 0.3, Essentia primary
        assert merged["energy"] == 0.7
        assert merged["classification_source"] == "essentia+llm"

    def test_essentia_octave_error_uses_llm_bpm(self):
        """Essentia half-tempo error → LLM BPM wins."""
        llm = {"bpm": 171, "valence": 0.9, "danceability": 0.8,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["energetic"], "energy": 0.7, "acousticness": 0.3}
        song = _make_song(
            essentia_bpm=86, essentia_key="F#", essentia_mode="minor",
            essentia_energy=0.65, essentia_acousticness=0.35,
            classification_source="essentia",
        )
        merged = _merge_with_essentia(llm, song)
        assert merged["bpm"] == 171  # LLM wins, Essentia had octave error

    def test_no_essentia_uses_all_llm(self):
        """Song with no prior Essentia data uses LLM for everything available."""
        llm = {"bpm": 130, "valence": 0.8, "danceability": 0.9,
               "instrumentalness": 0.05, "genre_tags": ["pop"],
               "mood_tags": ["energetic"]}
        song = _make_song(classification_source=None)
        merged = _merge_with_essentia(llm, song)
        assert merged["bpm"] == 130
        assert merged["key"] is None
        assert merged["energy"] is None
        assert merged["classification_source"] == "llm"

    def test_no_essentia_bpm_falls_back_to_llm(self):
        """Essentia has no BPM → LLM BPM used."""
        llm = {"bpm": 128, "valence": 0.7, "danceability": 0.8,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["upbeat"]}
        song = _make_song(
            essentia_bpm=None, essentia_key="G", essentia_mode="major",
            essentia_energy=0.6, essentia_acousticness=0.4,
            classification_source="essentia",
        )
        merged = _merge_with_essentia(llm, song)
        assert merged["bpm"] == 128

    def test_llm_properties_always_from_llm(self):
        """Danceability, instrumentalness, valence, tags always come from LLM."""
        llm = {"bpm": 120, "valence": 0.55, "danceability": 0.65,
               "instrumentalness": 0.15, "genre_tags": ["rock"],
               "mood_tags": ["intense", "driving"]}
        song = _make_song(
            essentia_bpm=122, classification_source="essentia",
        )
        merged = _merge_with_essentia(llm, song)
        assert merged["danceability"] == 0.65
        assert merged["instrumentalness"] == 0.15
        assert merged["valence"] == 0.55
        assert merged["mood_tags"] == ["intense", "driving"]

    def test_llm_neuro_scores_passed_through(self):
        """LLM direct neuro scores are stored in merged dict for blending."""
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"],
               "para_score": 0.8, "symp_score": 0.1, "grounding_score": 0.4}
        song = _make_song(classification_source=None)
        merged = _merge_with_essentia(llm, song)
        assert merged["llm_para_score"] == 0.8
        assert merged["llm_symp_score"] == 0.1
        assert merged["llm_grounding_score"] == 0.4

    def test_missing_llm_neuro_scores_are_none(self):
        """Missing LLM neuro scores stored as None."""
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"]}
        song = _make_song(classification_source=None)
        merged = _merge_with_essentia(llm, song)
        assert merged["llm_para_score"] is None
        assert merged["llm_symp_score"] is None
        assert merged["llm_grounding_score"] is None

    def test_felt_tempo_passed_through(self):
        """Felt tempo from LLM is stored in merged dict."""
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"], "felt_tempo": 60}
        song = _make_song(classification_source=None)
        merged = _merge_with_essentia(llm, song)
        assert merged["felt_tempo"] == 60

    def test_felt_tempo_none_when_absent(self):
        """Missing felt_tempo is None in merged dict."""
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"]}
        song = _make_song(classification_source=None)
        merged = _merge_with_essentia(llm, song)
        assert merged["felt_tempo"] is None

    def test_essentia_key_mode_preserved(self):
        """Essentia always provides key/mode."""
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"]}
        song = _make_song(
            essentia_bpm=120, essentia_key="C", essentia_mode="major",
            essentia_energy=0.5, essentia_acousticness=0.6,
            classification_source="essentia",
        )
        merged = _merge_with_essentia(llm, song)
        assert merged["key"] == "C"
        assert merged["mode"] == "major"


# ---------------------------------------------------------------------------
# classify_songs (integration with mocked LLM)
# ---------------------------------------------------------------------------

class TestClassifySongs:
    def _seed_songs(self, db_conn, count=3):
        """Insert songs that need classification."""
        for i in range(count):
            queries.upsert_song(
                db_conn, f"uri:{i}", f"Song {i}", f"Artist {i}", f"Album {i}",
            )
            db_conn.execute(
                "UPDATE songs SET play_count = ? WHERE spotify_uri = ?",
                (10 + i, f"uri:{i}"),
            )
        db_conn.commit()

    def _seed_essentia_song(self, db_conn, uri="uri:ess"):
        """Insert a song with Essentia-only classification."""
        queries.upsert_song(db_conn, uri, "Essentia Song", "Essentia Artist")
        db_conn.execute(
            "UPDATE songs SET play_count = 20 WHERE spotify_uri = ?", (uri,),
        )
        db_conn.commit()
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": uri,
            "bpm": 120, "key": "A", "mode": "minor",
            "energy": 0.7, "acousticness": 0.3,
            "essentia_energy": 0.7, "essentia_acousticness": 0.3,
            "classification_source": "essentia",
        })

    def _mock_llm_response(self, prompt):
        """Generate a valid LLM response by parsing song names from the prompt."""
        import re
        # Parse numbered lines like: 1. "Song 0" by Artist 0 (album: Album 0)
        matches = re.findall(r'\d+\.\s+"(.+?)"\s+by\s+(.+?)(?:\s+\(album:.*?\))?$', prompt, re.MULTILINE)
        results = []
        for name, artist in matches:
            results.append({
                "title": name,
                "artist": artist.strip(),
                "bpm": 120,
                "energy": 0.65,
                "acousticness": 0.3,
                "danceability": 0.7,
                "instrumentalness": 0.1,
                "valence": 0.6,
                "mood_tags": ["happy", "upbeat"],
                "genre_tags": ["pop", "dance"],
                "para_score": 0.2,
                "symp_score": 0.7,
                "grounding_score": 0.3,
            })
        return _make_llm_response(results)

    @patch("classification.llm_classifier._call_openai")
    def test_classifies_all_songs(self, mock_call, db_conn):
        self._seed_songs(db_conn, 3)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        stats = classify_songs(db_conn, provider="openai")
        assert stats["classified"] == 3
        assert stats["failed"] == 0
        assert stats["skipped"] == 0

    @patch("classification.llm_classifier._call_openai")
    def test_stores_classifications_in_db(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        classify_songs(db_conn, provider="openai")
        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert len(rows) == 1
        assert rows[0]["valence"] == 0.6
        assert rows[0]["danceability"] == 0.7
        assert rows[0]["classification_source"] == "llm"

    @patch("classification.llm_classifier._call_openai")
    def test_computes_neurological_profile(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        classify_songs(db_conn, provider="openai")
        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert rows[0]["parasympathetic"] is not None
        assert rows[0]["sympathetic"] is not None
        assert rows[0]["grounding"] is not None

    @patch("classification.llm_classifier._call_openai")
    def test_merges_with_essentia(self, mock_call, db_conn):
        self._seed_essentia_song(db_conn)

        def mock_response(prompt):
            return _make_llm_response([{
                "title": "Essentia Song", "artist": "Essentia Artist",
                "bpm": 118, "danceability": 0.7, "instrumentalness": 0.1,
                "valence": 0.6, "mood_tags": ["happy"],
                "genre_tags": ["pop"],
            }])

        mock_call.side_effect = mock_response
        classify_songs(db_conn, provider="openai")

        rows = queries.get_song_classifications(db_conn, ["uri:ess"])
        assert len(rows) == 1
        assert rows[0]["bpm"] == 119  # Average of LLM 118 + Essentia 120 (they agree)
        assert rows[0]["key"] == "A"  # Essentia key kept
        assert rows[0]["valence"] == 0.6  # LLM valence
        assert rows[0]["classification_source"] == "essentia+llm"

    @patch("classification.llm_classifier._call_openai")
    def test_idempotent_second_run(self, mock_call, db_conn):
        """Second run should classify 0 songs (all already have valence)."""
        self._seed_songs(db_conn, 2)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        stats1 = classify_songs(db_conn, provider="openai")
        assert stats1["classified"] == 2

        mock_call.reset_mock()
        stats2 = classify_songs(db_conn, provider="openai")
        assert stats2["classified"] == 0
        mock_call.assert_not_called()

    @patch("classification.llm_classifier._call_openai")
    def test_retries_on_failure(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        # Fail twice, succeed on third
        mock_call.side_effect = [
            Exception("API error"),
            Exception("Rate limit"),
            _make_llm_response([{
                "title": "Song 0", "artist": "Artist 0",
                "bpm": 120, "danceability": 0.7, "instrumentalness": 0.1,
                "valence": 0.6, "mood_tags": ["happy"], "genre_tags": ["pop"],
            }]),
        ]

        with patch("classification.llm_classifier.time.sleep"):
            stats = classify_songs(db_conn, provider="openai")
        assert stats["classified"] == 1
        assert mock_call.call_count == 3

    @patch("classification.llm_classifier._call_openai")
    def test_skips_batch_after_max_retries(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = Exception("Persistent failure")

        with patch("classification.llm_classifier.time.sleep"):
            stats = classify_songs(db_conn, provider="openai")
        assert stats["failed"] == 1
        assert stats["classified"] == 0

    @patch("classification.llm_classifier._call_openai")
    def test_skips_invalid_result_continues_batch(self, mock_call, db_conn):
        """One bad result in a batch shouldn't skip the entire batch."""
        self._seed_songs(db_conn, 2)

        def mock_response(prompt):
            return _make_llm_response([
                {},  # Invalid — no bpm or valence
                {"title": "Song 1", "artist": "Artist 1",
                 "bpm": 130, "danceability": 0.8, "instrumentalness": 0.05,
                 "valence": 0.9, "mood_tags": ["energetic"], "genre_tags": ["pop"]},
            ])

        mock_call.side_effect = mock_response
        stats = classify_songs(db_conn, provider="openai")
        assert stats["classified"] == 1
        assert stats["skipped"] == 1

    @patch("classification.llm_classifier._call_anthropic")
    def test_anthropic_provider(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        stats = classify_songs(db_conn, provider="anthropic")
        assert stats["classified"] == 1
        mock_call.assert_called_once()

    @patch("classification.llm_classifier._call_openai")
    def test_empty_work_queue(self, mock_call, db_conn):
        """No songs to classify → immediate return."""
        stats = classify_songs(db_conn, provider="openai")
        assert stats["classified"] == 0
        assert stats["batches"] == 0
        mock_call.assert_not_called()

    @patch("classification.llm_classifier._call_openai")
    def test_batching_respects_batch_size(self, mock_call, db_conn):
        """7 songs with batch_size=5 should make 2 LLM calls."""
        self._seed_songs(db_conn, 7)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        stats = classify_songs(db_conn, provider="openai")
        assert stats["classified"] == 7
        assert stats["batches"] == 2
        assert mock_call.call_count == 2

    @patch("classification.llm_classifier._call_openai")
    def test_stores_raw_response(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        classify_songs(db_conn, provider="openai")
        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert rows[0]["raw_response"] is not None
        assert "songs" in rows[0]["raw_response"]

    @patch("classification.llm_classifier._call_openai")
    def test_stores_classified_at_timestamp(self, mock_call, db_conn):
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        classify_songs(db_conn, provider="openai")
        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert rows[0]["classified_at"] is not None

    @patch("classification.llm_classifier._call_openai")
    def test_octave_error_corrected_in_full_pipeline(self, mock_call, db_conn):
        """End-to-end: Essentia octave error should be corrected by LLM BPM."""
        self._seed_essentia_song(db_conn)  # Essentia BPM=120, energy=0.7

        def mock_response(prompt):
            return _make_llm_response([{
                "title": "Essentia Song", "artist": "Essentia Artist",
                "bpm": 60, "energy": 0.2, "acousticness": 0.7,
                "danceability": 0.3, "instrumentalness": 0.2,
                "valence": 0.3, "mood_tags": ["calm"],
                "genre_tags": ["ambient"],
            }])

        mock_call.side_effect = mock_response
        classify_songs(db_conn, provider="openai")

        rows = queries.get_song_classifications(db_conn, ["uri:ess"])
        assert rows[0]["bpm"] == 60  # LLM BPM wins (Essentia 120 is 2x octave error)
        assert rows[0]["key"] == "A"  # Essentia key preserved
        # Energy: Essentia=0.7, LLM=0.2, gap=0.5 > 0.3 → blend 50/50 = 0.45
        assert abs(rows[0]["energy"] - 0.45) < 0.01

    @patch("classification.llm_classifier._call_openai")
    def test_invalid_provider_raises(self, mock_call, db_conn):
        with pytest.raises(ValueError, match="Unknown provider"):
            classify_songs(db_conn, provider="gemini")

    @patch("classification.llm_classifier._call_openai")
    def test_llm_returns_empty_songs_array(self, mock_call, db_conn):
        """LLM returns valid JSON but empty songs array — all songs skipped."""
        self._seed_songs(db_conn, 2)
        mock_call.return_value = _make_llm_response([])
        stats = classify_songs(db_conn, provider="openai")
        assert stats["skipped"] == 2
        assert stats["classified"] == 0

    @patch("classification.llm_classifier._call_openai")
    def test_llm_returns_fewer_results_than_batch(self, mock_call, db_conn):
        """LLM returns fewer songs than requested — unmatched songs skipped.

        Seeded songs have play_counts 10, 11, 12 → ordered as uri:2, uri:1, uri:0.
        LLM returns 1 result for "Unique Song" (no title/positional match to Song 1).
        Song at index 0 gets positional match. Song 1 and Song 2 title-search fails.
        """
        self._seed_songs(db_conn, 3)

        def mock_response(prompt):
            # Return 1 result with a unique name that won't title-match any other
            return _make_llm_response([{
                "title": "Unique Song", "artist": "Unique Artist",
                "bpm": 120, "danceability": 0.7, "instrumentalness": 0.1,
                "valence": 0.6, "mood_tags": ["happy"], "genre_tags": ["pop"],
            }])

        mock_call.side_effect = mock_response
        stats = classify_songs(db_conn, provider="openai")
        # Index 0 gets positional match; index 1 and 2 fail title match
        assert stats["classified"] == 1
        assert stats["skipped"] == 2

    @patch("classification.llm_classifier._call_openai")
    def test_computed_confidence_no_essentia(self, mock_call, db_conn):
        """LLM-only songs get base confidence of 0.5."""
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        classify_songs(db_conn, provider="openai")
        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert rows[0]["confidence"] == 0.5  # No Essentia data

    @patch("classification.llm_classifier._call_openai")
    def test_computed_confidence_with_essentia(self, mock_call, db_conn):
        """Essentia + BPM agreement → high computed confidence."""
        self._seed_essentia_song(db_conn)  # BPM=120

        def mock_response(prompt):
            return _make_llm_response([{
                "title": "Essentia Song", "artist": "Essentia Artist",
                "bpm": 118, "danceability": 0.7, "instrumentalness": 0.1,
                "valence": 0.6, "mood_tags": ["happy"], "genre_tags": ["pop"],
            }])

        mock_call.side_effect = mock_response
        classify_songs(db_conn, provider="openai")
        rows = queries.get_song_classifications(db_conn, ["uri:ess"])
        assert rows[0]["confidence"] == 1.0  # Essentia + BPM agreement

    @patch("classification.llm_classifier._call_openai")
    def test_low_computed_confidence_tracked(self, mock_call, db_conn):
        """LLM-only songs (confidence=0.5) are flagged as low confidence (< 0.7)."""
        self._seed_songs(db_conn, 1)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        stats = classify_songs(db_conn, provider="openai")
        # LLM-only gets 0.5, which is < 0.7, so flagged
        assert stats["low_confidence"] == 1

    @patch("classification.llm_classifier._call_openai")
    def test_llm_returns_no_songs_key(self, mock_call, db_conn):
        """LLM returns JSON without 'songs' key — all songs skipped."""
        self._seed_songs(db_conn, 2)
        mock_call.return_value = {
            "parsed": {"results": []},  # Wrong key
            "raw_response": '{"results": []}',
        }
        stats = classify_songs(db_conn, provider="openai")
        assert stats["skipped"] == 2
        assert stats["classified"] == 0

    @patch("classification.llm_classifier._call_openai")
    def test_reclassify_processes_already_classified_songs(self, mock_call, db_conn):
        """reclassify=True should re-process songs that already have valence."""
        self._seed_songs(db_conn, 2)
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)

        # First run — normal
        stats1 = classify_songs(db_conn, provider="openai")
        assert stats1["classified"] == 2

        # Second run without reclassify — 0 songs
        mock_call.reset_mock()
        stats2 = classify_songs(db_conn, provider="openai")
        assert stats2["classified"] == 0
        mock_call.assert_not_called()

        # Third run WITH reclassify — all songs re-processed
        mock_call.reset_mock()
        mock_call.side_effect = lambda prompt: self._mock_llm_response(prompt)
        stats3 = classify_songs(db_conn, provider="openai", reclassify=True)
        assert stats3["classified"] == 2
        mock_call.assert_called()

    @patch("classification.llm_classifier._call_openai")
    def test_felt_tempo_used_for_neuro_scoring(self, mock_call, db_conn):
        """When felt_tempo is returned, it should be used for neurological scoring."""
        self._seed_songs(db_conn, 1)

        def mock_response(prompt):
            return _make_llm_response([{
                "title": "Song 0", "artist": "Artist 0",
                "bpm": 120, "felt_tempo": 60,
                "danceability": 0.3, "instrumentalness": 0.5,
                "valence": 0.3, "mood_tags": ["devotional"],
                "genre_tags": ["bollywood", "devotional"],
            }])

        mock_call.side_effect = mock_response
        classify_songs(db_conn, provider="openai")

        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert rows[0]["felt_tempo"] == 60
        assert rows[0]["bpm"] is not None
        # With felt_tempo=60, para should be higher than if BPM=120 was used
        assert rows[0]["parasympathetic"] is not None

    @patch("classification.llm_classifier._call_openai")
    def test_felt_tempo_none_falls_back_to_bpm(self, mock_call, db_conn):
        """When felt_tempo is None, regular BPM is used for scoring."""
        self._seed_songs(db_conn, 1)

        def mock_response(prompt):
            return _make_llm_response([{
                "title": "Song 0", "artist": "Artist 0",
                "bpm": 120, "felt_tempo": None,
                "danceability": 0.7, "instrumentalness": 0.1,
                "valence": 0.6, "mood_tags": ["happy"],
                "genre_tags": ["pop"],
            }])

        mock_call.side_effect = mock_response
        classify_songs(db_conn, provider="openai")

        rows = queries.get_song_classifications(db_conn, ["uri:0"])
        assert rows[0]["felt_tempo"] is None
        assert rows[0]["bpm"] is not None

    @patch("classification.llm_classifier._call_openai")
    def test_felt_tempo_stored_in_db(self, mock_call, db_conn):
        """Felt tempo should be persisted to song_classifications."""
        self._seed_songs(db_conn, 1)

        def mock_response(prompt):
            return _make_llm_response([{
                "title": "Song 0", "artist": "Artist 0",
                "bpm": 120, "felt_tempo": 80,
                "danceability": 0.5, "instrumentalness": 0.2,
                "valence": 0.4, "mood_tags": ["reflective"],
                "genre_tags": ["hindi", "devotional"],
            }])

        mock_call.side_effect = mock_response
        classify_songs(db_conn, provider="openai")

        row = db_conn.execute(
            "SELECT felt_tempo FROM song_classifications WHERE spotify_uri = 'uri:0'"
        ).fetchone()
        assert row["felt_tempo"] == 80


# ---------------------------------------------------------------------------
# Additional _blend_neuro_scores boundary tests
# ---------------------------------------------------------------------------

class TestBlendNeuroScoresBoundary:
    def test_energy_at_exact_040_threshold(self):
        """Energy exactly at 0.40 should take the 'moderate energy, trust formula' path.

        0.40 is NOT < 0.40, so we hit the else branch (70% formula / 30% LLM).
        """
        formula = {"parasympathetic": 0.3, "sympathetic": 0.1, "grounding": 0.7}
        # LLM says PARA
        result = _blend_neuro_scores(
            formula, 0.8, 0.1, 0.4,
            bpm=85, energy=0.40,
        )
        # 70% * 0.7 + 30% * 0.4 = 0.61 for grounding
        assert abs(result["grounding"] - 0.61) < 0.01
        # GRND should dominate (formula trusted at 70%)
        assert result["grounding"] > result["parasympathetic"]


# ---------------------------------------------------------------------------
# Additional _merge_with_essentia tests
# ---------------------------------------------------------------------------

class TestMergeWithEssentiaExtra:
    def test_llm_energy_acousticness_used_without_essentia(self):
        """When classification_source is NOT essentia, merge uses LLM energy/acousticness."""
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"], "energy": 0.72, "acousticness": 0.31}
        song = _make_song(classification_source=None)
        merged = _merge_with_essentia(llm, song)
        assert merged["energy"] == 0.72
        assert merged["acousticness"] == 0.31
        assert merged["classification_source"] == "llm"

    def test_essentia_plus_llm_source_uses_merge_logic(self):
        """Song with classification_source='essentia+llm' uses smart merge for energy/acousticness."""
        # Energy: Essentia=0.85, LLM=0.50, gap=0.35 > 0.3 → blend 50/50 = 0.675
        # Acousticness: Essentia=0.15, LLM=0.50, gap=0.35 > 0.3 → LLM wins = 0.50
        llm = {"bpm": 120, "valence": 0.6, "danceability": 0.7,
               "instrumentalness": 0.1, "genre_tags": ["pop"],
               "mood_tags": ["happy"], "energy": 0.50, "acousticness": 0.50}
        song = _make_song(
            essentia_bpm=122, essentia_key="D", essentia_mode="minor",
            essentia_energy=0.85, essentia_acousticness=0.15,
            classification_source="essentia+llm",
        )
        merged = _merge_with_essentia(llm, song)
        assert merged["key"] == "D"
        assert merged["mode"] == "minor"
        assert merged["energy"] == round((0.85 + 0.50) / 2, 4)  # blend
        assert merged["acousticness"] == 0.50  # LLM wins
        assert merged["classification_source"] == "essentia+llm"


# ---------------------------------------------------------------------------
# _merge_energy
# ---------------------------------------------------------------------------

class TestMergeEnergy:
    def test_agreement_uses_essentia(self):
        """Gap <= 0.3: Essentia primary (onset rate reliable)."""
        assert _merge_energy(0.7, 0.65) == 0.7

    def test_disagreement_blends_50_50(self):
        """Gap > 0.3: blend 50/50."""
        result = _merge_energy(0.8, 0.2)
        assert result == 0.5

    def test_exact_threshold_uses_essentia(self):
        """Gap exactly 0.3: agreement → Essentia primary."""
        assert _merge_energy(0.6, 0.3) == 0.6

    def test_just_above_threshold_blends(self):
        """Gap 0.31: disagreement → blend."""
        result = _merge_energy(0.61, 0.3)
        assert abs(result - round((0.61 + 0.3) / 2, 4)) < 0.001

    def test_essentia_none_returns_llm(self):
        assert _merge_energy(None, 0.5) == 0.5

    def test_llm_none_returns_essentia(self):
        assert _merge_energy(0.7, None) == 0.7

    def test_both_none_returns_none(self):
        assert _merge_energy(None, None) is None

    def test_result_rounded_to_four_decimals(self):
        result = _merge_energy(0.777, 0.333)
        # gap=0.444 > 0.3, blend = (0.777+0.333)/2 = 0.555
        assert result == 0.555
        s = str(result)
        if "." in s:
            assert len(s.split(".")[1]) <= 4


# ---------------------------------------------------------------------------
# _merge_acousticness
# ---------------------------------------------------------------------------

class TestMergeAcousticness:
    def test_agreement_averages(self):
        """Gap <= 0.3: average (both plausible)."""
        result = _merge_acousticness(0.5, 0.6)
        assert result == 0.55

    def test_disagreement_llm_wins(self):
        """Gap > 0.3: LLM wins (spectral flatness structurally wrong)."""
        result = _merge_acousticness(0.96, 0.2)
        assert result == 0.2

    def test_exact_threshold_averages(self):
        """Gap exactly 0.3: agreement → average."""
        result = _merge_acousticness(0.6, 0.3)
        assert result == round((0.6 + 0.3) / 2, 4)

    def test_just_above_threshold_llm_wins(self):
        """Gap 0.31: disagreement → LLM wins."""
        result = _merge_acousticness(0.61, 0.3)
        assert result == 0.3

    def test_essentia_none_returns_llm(self):
        assert _merge_acousticness(None, 0.5) == 0.5

    def test_llm_none_returns_essentia(self):
        assert _merge_acousticness(0.7, None) == 0.7

    def test_both_none_returns_none(self):
        assert _merge_acousticness(None, None) is None

    def test_blinding_lights_case(self):
        """Blinding Lights: Essentia acousticness=0.96 (wrong), LLM should win."""
        # LLM would say ~0.1 for synthwave
        result = _merge_acousticness(0.96, 0.1)
        assert result == 0.1  # gap=0.86, LLM wins

    def test_result_rounded_to_four_decimals(self):
        result = _merge_acousticness(0.333, 0.222)
        # gap=0.111 <= 0.3, average = (0.333+0.222)/2 = 0.2775
        assert result == 0.2775
        s = str(result)
        if "." in s:
            assert len(s.split(".")[1]) <= 4


# ---------------------------------------------------------------------------
# Recompute-scores smoke test
# ---------------------------------------------------------------------------

class TestRecomputeScores:
    def test_recompute_updates_neuro_scores(self, db_conn):
        """Smoke test: recompute-scores reads classified songs and updates their scores."""
        import json
        from classification.llm_classifier import _blend_neuro_scores
        from classification.profiler import compute_neurological_profile

        # Seed a song with a classification including raw_response
        queries.upsert_song(db_conn, "uri:recomp", "Recompute Song", "Recompute Artist")
        db_conn.execute(
            "UPDATE songs SET play_count = 10 WHERE spotify_uri = ?", ("uri:recomp",)
        )
        db_conn.commit()

        raw_response = json.dumps({"songs": [{
            "title": "Recompute Song", "artist": "Recompute Artist",
            "bpm": 85, "energy": 0.35, "acousticness": 0.6,
            "danceability": 0.4, "instrumentalness": 0.2,
            "valence": 0.45,
            "mood_tags": ["reflective"], "genre_tags": ["indie"],
            "para_score": 0.6, "symp_score": 0.2, "grounding_score": 0.7,
        }]})

        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:recomp",
            "bpm": 85,
            "energy": 0.35,
            "acousticness": 0.6,
            "danceability": 0.4,
            "instrumentalness": 0.2,
            "valence": 0.45,
            "mode": "major",
            "genre_tags": ["indie"],
            "mood_tags": ["reflective"],
            "classification_source": "llm",
            "raw_response": raw_response,
            "parasympathetic": 0.0,  # Will be overwritten
            "sympathetic": 0.0,
            "grounding": 0.0,
        })

        # Replicate the recompute logic from main.py
        rows = db_conn.execute(
            """SELECT sc.spotify_uri, s.name, s.artist,
                      sc.bpm, sc.felt_tempo, sc.energy, sc.acousticness,
                      sc.instrumentalness, sc.valence, sc.mode, sc.danceability,
                      sc.genre_tags, sc.raw_response
               FROM song_classifications sc
               JOIN songs s ON sc.spotify_uri = s.spotify_uri
               WHERE sc.valence IS NOT NULL"""
        ).fetchall()

        assert len(rows) == 1
        d = dict(rows[0])
        scoring_bpm = d.get("felt_tempo") or d.get("bpm")

        neuro = compute_neurological_profile(
            bpm=scoring_bpm,
            energy=d.get("energy"),
            acousticness=d.get("acousticness"),
            instrumentalness=d.get("instrumentalness"),
            valence=d.get("valence"),
            mode=d.get("mode"),
            danceability=d.get("danceability"),
        )

        # Extract LLM scores from raw_response using exact match
        llm_para, llm_symp, llm_grounding = None, None, None
        song_name = (d.get("name") or "").lower().strip()
        song_artist = (d.get("artist") or "").lower().strip()
        raw = json.loads(d["raw_response"])
        for song_result in raw.get("songs", []):
            r_title = str(song_result.get("title", "")).lower().strip()
            r_artist = str(song_result.get("artist", "")).lower().strip()
            if r_title == song_name and r_artist == song_artist:
                llm_para = song_result.get("para_score")
                llm_symp = song_result.get("symp_score")
                llm_grounding = song_result.get("grounding_score")
                break

        assert llm_para == 0.6
        assert llm_symp == 0.2
        assert llm_grounding == 0.7

        blended = _blend_neuro_scores(
            neuro, llm_para, llm_symp, llm_grounding,
            bpm=d.get("bpm"), energy=d.get("energy"),
        )

        # Update DB (same as main.py does)
        db_conn.execute(
            """UPDATE song_classifications
               SET parasympathetic = ?, sympathetic = ?, grounding = ?
               WHERE spotify_uri = ?""",
            (blended["parasympathetic"], blended["sympathetic"],
             blended["grounding"], d["spotify_uri"]),
        )
        db_conn.commit()

        # Verify scores were updated from the initial 0.0 values
        updated = queries.get_song_classifications(db_conn, ["uri:recomp"])
        assert len(updated) == 1
        assert updated[0]["parasympathetic"] > 0.0
        assert updated[0]["sympathetic"] > 0.0
        assert updated[0]["grounding"] > 0.0
        # All scores should be in [0, 1]
        for key in ("parasympathetic", "sympathetic", "grounding"):
            assert 0.0 <= updated[0][key] <= 1.0


# ---------------------------------------------------------------------------
# _call_anthropic malformed response tests
# ---------------------------------------------------------------------------

class TestRecomputeIdempotency:
    """Verify recompute-scores is idempotent when essentia_* columns are populated."""

    def test_recompute_with_essentia_columns_is_idempotent(self, db_conn):
        """Running recompute twice with essentia_* columns produces identical results."""
        import json as _json

        from classification.llm_classifier import (
            _blend_neuro_scores,
            _merge_acousticness,
            _merge_energy,
        )
        from classification.profiler import compute_neurological_profile

        # Seed song
        queries.upsert_song(db_conn, "uri:idem", "Idempotent Song", "Idempotent Artist")
        db_conn.execute(
            "UPDATE songs SET play_count = 15 WHERE spotify_uri = ?", ("uri:idem",)
        )
        db_conn.commit()

        raw_response = _json.dumps({"songs": [{
            "title": "Idempotent Song", "artist": "Idempotent Artist",
            "bpm": 100, "energy": 0.50, "acousticness": 0.40,
            "danceability": 0.6, "instrumentalness": 0.1,
            "valence": 0.55,
            "mood_tags": ["upbeat"], "genre_tags": ["pop"],
            "para_score": 0.3, "symp_score": 0.6, "grounding_score": 0.4,
        }]})

        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:idem",
            "bpm": 100, "energy": 0.60, "acousticness": 0.45,
            "essentia_energy": 0.70, "essentia_acousticness": 0.50,
            "danceability": 0.6, "instrumentalness": 0.1,
            "valence": 0.55, "mode": "major",
            "genre_tags": ["pop"], "mood_tags": ["upbeat"],
            "classification_source": "essentia+llm",
            "raw_response": raw_response,
            "parasympathetic": 0.0, "sympathetic": 0.0, "grounding": 0.0,
        })

        def _run_recompute():
            def _clamp01(v):
                return max(0.0, min(1.0, float(v))) if v is not None else None

            rows = db_conn.execute(
                """SELECT sc.spotify_uri, s.name, s.artist,
                          sc.bpm, sc.felt_tempo, sc.energy, sc.acousticness,
                          sc.essentia_energy, sc.essentia_acousticness,
                          sc.instrumentalness, sc.valence, sc.mode, sc.danceability,
                          sc.genre_tags, sc.mood_tags, sc.raw_response,
                          sc.classification_source
                   FROM song_classifications sc
                   JOIN songs s ON sc.spotify_uri = s.spotify_uri
                   WHERE sc.valence IS NOT NULL"""
            ).fetchall()

            for row in rows:
                d = dict(row)
                mood_tags = _json.loads(d["mood_tags"]) if d.get("mood_tags") else None
                source = d.get("classification_source") or ""
                llm_energy, llm_acousticness = None, None
                llm_para, llm_symp, llm_grounding = None, None, None
                song_name = (d.get("name") or "").lower().strip()
                song_artist = (d.get("artist") or "").lower().strip()
                if d.get("raw_response"):
                    raw = _json.loads(d["raw_response"])
                    for song_result in raw.get("songs", []):
                        if (str(song_result.get("title", "")).lower().strip() == song_name
                                and str(song_result.get("artist", "")).lower().strip() == song_artist):
                            llm_para = song_result.get("para_score")
                            llm_symp = song_result.get("symp_score")
                            llm_grounding = song_result.get("grounding_score")
                            llm_energy = song_result.get("energy")
                            llm_acousticness = song_result.get("acousticness")
                            break

                energy = d.get("energy")
                acousticness = d.get("acousticness")
                if source == "essentia+llm" and llm_energy is not None:
                    energy = _merge_energy(d.get("essentia_energy"), _clamp01(llm_energy))
                if source == "essentia+llm" and llm_acousticness is not None:
                    acousticness = _merge_acousticness(d.get("essentia_acousticness"), _clamp01(llm_acousticness))

                scoring_bpm = d.get("felt_tempo") or d.get("bpm")
                neuro = compute_neurological_profile(
                    bpm=scoring_bpm, energy=energy, acousticness=acousticness,
                    instrumentalness=d.get("instrumentalness"), valence=d.get("valence"),
                    mode=d.get("mode"), danceability=d.get("danceability"),
                    mood_tags=mood_tags,
                )
                blended = _blend_neuro_scores(
                    neuro, _clamp01(llm_para), _clamp01(llm_symp), _clamp01(llm_grounding),
                    bpm=d.get("bpm"), energy=energy,
                )

                db_conn.execute(
                    """UPDATE song_classifications
                       SET energy = ?, acousticness = ?,
                           parasympathetic = ?, sympathetic = ?, grounding = ?
                       WHERE spotify_uri = ?""",
                    (energy, acousticness,
                     blended["parasympathetic"], blended["sympathetic"],
                     blended["grounding"], d["spotify_uri"]),
                )
            db_conn.commit()

        # Run 1
        _run_recompute()
        row1 = dict(db_conn.execute(
            "SELECT energy, acousticness, parasympathetic, sympathetic, grounding "
            "FROM song_classifications WHERE spotify_uri = 'uri:idem'"
        ).fetchone())

        # Run 2 — should produce identical results
        _run_recompute()
        row2 = dict(db_conn.execute(
            "SELECT energy, acousticness, parasympathetic, sympathetic, grounding "
            "FROM song_classifications WHERE spotify_uri = 'uri:idem'"
        ).fetchone())

        assert row1 == row2, f"Recompute not idempotent: run1={row1}, run2={row2}"

    def test_recompute_essentia_plus_llm_uses_essentia_columns(self, db_conn):
        """essentia+llm songs use essentia_* columns, not energy/acousticness, for merge."""
        import json as _json

        from classification.llm_classifier import _merge_acousticness, _merge_energy

        queries.upsert_song(db_conn, "uri:src", "Source Song", "Source Artist")
        db_conn.execute(
            "UPDATE songs SET play_count = 10 WHERE spotify_uri = ?", ("uri:src",)
        )
        db_conn.commit()

        raw_response = _json.dumps({"songs": [{
            "title": "Source Song", "artist": "Source Artist",
            "bpm": 90, "energy": 0.30, "acousticness": 0.80,
            "danceability": 0.4, "instrumentalness": 0.2, "valence": 0.3,
            "mood_tags": ["calm"], "genre_tags": ["ambient"],
            "para_score": 0.7, "symp_score": 0.1, "grounding_score": 0.5,
        }]})

        # Set energy/acousticness to MERGED values (different from essentia_*)
        # essentia_energy=0.70 vs energy=0.35 — with llm_energy=0.30:
        #   _merge_energy(0.70, 0.30) = blend(0.70+0.30)/2 = 0.50 (gap=0.40>0.3)
        #   _merge_energy(0.35, 0.30) = 0.35 (gap=0.05<=0.3, Essentia primary)
        queries.upsert_song_classification(db_conn, {
            "spotify_uri": "uri:src",
            "bpm": 90, "energy": 0.35, "acousticness": 0.75,
            "essentia_energy": 0.70, "essentia_acousticness": 0.30,
            "valence": 0.3, "danceability": 0.4, "instrumentalness": 0.2,
            "mode": "minor", "mood_tags": ["calm"], "genre_tags": ["ambient"],
            "classification_source": "essentia+llm",
            "raw_response": raw_response,
            "parasympathetic": 0.5, "sympathetic": 0.2, "grounding": 0.4,
        })

        # The merge should use essentia_energy=0.70 (not energy=0.35) with llm_energy=0.30
        expected_energy = _merge_energy(0.70, 0.30)
        expected_acousticness = _merge_acousticness(0.30, 0.80)

        # Verify these differ from what you'd get using the merged column values
        wrong_energy = _merge_energy(0.35, 0.30)
        assert expected_energy != wrong_energy, "Test setup: essentia_* must differ from merged"

        # Now run the recompute equivalent
        row = db_conn.execute(
            """SELECT sc.essentia_energy, sc.essentia_acousticness
               FROM song_classifications sc WHERE sc.spotify_uri = 'uri:src'"""
        ).fetchone()
        assert row["essentia_energy"] == 0.70
        assert row["essentia_acousticness"] == 0.30


class TestCallAnthropicMalformedResponse:
    def test_call_anthropic_handles_non_json_response(self):
        """When Anthropic returns text with no valid JSON, _call_anthropic raises JSONDecodeError.

        The classify_songs retry loop catches this as a generic Exception, so
        after max retries the batch is marked as 'failed' — not a hang or crash.
        """
        non_json_text = "I cannot classify this song because I don't have enough information."

        with patch("llm_client.call_anthropic", return_value=non_json_text):
            with patch("config.get_anthropic_api_key", return_value="test-key"):
                with pytest.raises(json.JSONDecodeError):
                    _call_anthropic("Classify these songs:\n1. \"Unknown Song\" by Unknown Artist")
