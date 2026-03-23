"""Tests for classification/validator.py — post-classification validation layer."""

import json
import sqlite3

import pytest

from classification.validator import (
    ValidationFlag,
    ValidationResult,
    _check_cross_property_coherence,
    _check_essentia_llm_disagreement,
    _check_neuro_sanity,
    validate_all_classifications,
    validate_classification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_classification(**overrides) -> dict:
    """Build a classification dict with sensible defaults."""
    base = {
        "spotify_uri": "spotify:track:test",
        "bpm": 100,
        "energy": 0.5,
        "acousticness": 0.5,
        "valence": 0.5,
        "danceability": 0.5,
        "instrumentalness": 0.3,
        "mood_tags": ["reflective"],
        "genre_tags": ["pop"],
        "confidence": 0.5,
        "parasympathetic": 0.4,
        "sympathetic": 0.3,
        "grounding": 0.5,
        "classification_source": "llm",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Check 1: Cross-property coherence
# ---------------------------------------------------------------------------

class TestCrossPropertyCoherence:
    def test_low_bpm_high_energy_flagged(self):
        c = _make_classification(bpm=65, energy=0.75)
        flags = _check_cross_property_coherence(c)
        assert any(f.rule == "low_bpm_high_energy" for f in flags)
        assert any(f.penalty == 0.10 for f in flags)

    def test_low_bpm_moderate_energy_not_flagged(self):
        c = _make_classification(bpm=65, energy=0.65)
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "low_bpm_high_energy" for f in flags)

    def test_high_bpm_low_energy_flagged(self):
        c = _make_classification(bpm=145, energy=0.25)
        flags = _check_cross_property_coherence(c)
        assert any(f.rule == "high_bpm_low_energy" for f in flags)

    def test_high_bpm_moderate_energy_not_flagged(self):
        c = _make_classification(bpm=145, energy=0.35)
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "high_bpm_low_energy" for f in flags)

    def test_high_acoustic_high_energy_flagged(self):
        c = _make_classification(acousticness=0.75, energy=0.85)
        flags = _check_cross_property_coherence(c)
        assert any(f.rule == "high_acoustic_high_energy" for f in flags)

    def test_high_acoustic_moderate_energy_not_flagged(self):
        c = _make_classification(acousticness=0.75, energy=0.75)
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "high_acoustic_high_energy" for f in flags)

    def test_calm_mood_high_bpm_flagged(self):
        c = _make_classification(bpm=125, mood_tags=["calm", "peaceful"])
        flags = _check_cross_property_coherence(c)
        assert any(f.rule == "mood_bpm_mismatch" for f in flags)

    def test_energetic_mood_low_bpm_flagged(self):
        c = _make_classification(bpm=65, mood_tags=["energetic", "hype"])
        flags = _check_cross_property_coherence(c)
        assert any(f.rule == "mood_bpm_mismatch" for f in flags)

    def test_calm_mood_normal_bpm_not_flagged(self):
        c = _make_classification(bpm=80, mood_tags=["calm", "soothing"])
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "mood_bpm_mismatch" for f in flags)

    def test_energetic_mood_normal_bpm_not_flagged(self):
        c = _make_classification(bpm=120, mood_tags=["energetic", "party"])
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "mood_bpm_mismatch" for f in flags)

    def test_no_mood_tags_no_mismatch(self):
        c = _make_classification(bpm=65, mood_tags=[])
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "mood_bpm_mismatch" for f in flags)

    def test_none_bpm_no_flags(self):
        c = _make_classification(bpm=None, energy=0.9)
        flags = _check_cross_property_coherence(c)
        assert len(flags) == 0

    def test_none_energy_no_flags(self):
        c = _make_classification(bpm=60, energy=None)
        flags = _check_cross_property_coherence(c)
        assert len(flags) == 0

    def test_multiple_flags_can_accumulate(self):
        """A song can fail multiple coherence checks."""
        c = _make_classification(bpm=60, energy=0.85, acousticness=0.75)
        flags = _check_cross_property_coherence(c)
        rules = {f.rule for f in flags}
        assert "low_bpm_high_energy" in rules
        assert "high_acoustic_high_energy" in rules

    def test_json_string_mood_tags_handled(self):
        c = _make_classification(bpm=125, mood_tags=json.dumps(["calm", "peaceful"]))
        flags = _check_cross_property_coherence(c)
        assert any(f.rule == "mood_bpm_mismatch" for f in flags)

    def test_boundary_bpm_70_energy_0_7_not_flagged(self):
        """Exactly at threshold: BPM=70 and energy=0.7 should NOT be flagged (< 70, > 0.7)."""
        c = _make_classification(bpm=70, energy=0.7)
        flags = _check_cross_property_coherence(c)
        assert not any(f.rule == "low_bpm_high_energy" for f in flags)


# ---------------------------------------------------------------------------
# Check 2: Essentia vs LLM disagreement
# ---------------------------------------------------------------------------

class TestEssentiaLlmDisagreement:
    def test_large_energy_gap_flagged(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.8, essentia_acousticness=None,
            llm_energy=0.3, llm_acousticness=None,
        )
        assert any(f.rule == "essentia_llm_energy_gap" for f in flags)

    def test_large_acousticness_gap_flagged(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=None, essentia_acousticness=0.2,
            llm_energy=None, llm_acousticness=0.7,
        )
        assert any(f.rule == "essentia_llm_acousticness_gap" for f in flags)

    def test_small_gap_not_flagged(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.5, essentia_acousticness=0.5,
            llm_energy=0.55, llm_acousticness=0.45,
        )
        assert len(flags) == 0

    def test_exactly_at_threshold_not_flagged(self):
        """Gap of exactly 0.3 should NOT be flagged (> 0.3 required)."""
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.6, essentia_acousticness=None,
            llm_energy=0.3, llm_acousticness=None,
        )
        assert not any(f.rule == "essentia_llm_energy_gap" for f in flags)

    def test_llm_only_source_skipped(self):
        """Songs without Essentia data are not checked."""
        c = _make_classification(classification_source="llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.8, essentia_acousticness=None,
            llm_energy=0.1, llm_acousticness=None,
        )
        assert len(flags) == 0

    def test_none_essentia_values_no_flags(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=None, essentia_acousticness=None,
            llm_energy=0.8, llm_acousticness=0.2,
        )
        assert len(flags) == 0

    def test_none_llm_values_no_flags(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.8, essentia_acousticness=0.5,
            llm_energy=None, llm_acousticness=None,
        )
        assert len(flags) == 0

    def test_both_gaps_flagged(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.9, essentia_acousticness=0.1,
            llm_energy=0.2, llm_acousticness=0.8,
        )
        rules = {f.rule for f in flags}
        assert "essentia_llm_energy_gap" in rules
        assert "essentia_llm_acousticness_gap" in rules

    def test_energy_penalty_is_0_10(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.9, essentia_acousticness=None,
            llm_energy=0.1, llm_acousticness=None,
        )
        assert flags[0].penalty == 0.10

    def test_acousticness_penalty_is_0_08(self):
        c = _make_classification(classification_source="essentia+llm")
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=None, essentia_acousticness=0.1,
            llm_energy=None, llm_acousticness=0.9,
        )
        assert flags[0].penalty == 0.08

    def test_compares_original_values_not_merged(self):
        """The check compares raw Essentia vs raw LLM, ignoring DB merged values."""
        c = _make_classification(
            energy=0.55,  # merged value (irrelevant to check)
            classification_source="essentia+llm",
        )
        flags = _check_essentia_llm_disagreement(
            c, essentia_energy=0.8, essentia_acousticness=None,
            llm_energy=0.3, llm_acousticness=None,
        )
        assert any(f.rule == "essentia_llm_energy_gap" for f in flags)
        assert "0.80" in flags[0].detail
        assert "0.30" in flags[0].detail


# ---------------------------------------------------------------------------
# Check 3: Neuro score sanity
# ---------------------------------------------------------------------------

class TestNeuroSanity:
    def test_all_neuro_high_flagged(self):
        c = _make_classification(parasympathetic=0.7, sympathetic=0.7, grounding=0.7)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 1
        assert flags[0].rule == "all_neuro_high"
        assert flags[0].penalty == 0.10

    def test_para_symp_both_high_flagged(self):
        c = _make_classification(parasympathetic=0.7, sympathetic=0.7, grounding=0.3)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 1
        assert flags[0].rule == "para_symp_both_high"
        assert flags[0].penalty == 0.08

    def test_all_high_wins_over_para_symp(self):
        """Mutually exclusive: all_neuro_high takes precedence."""
        c = _make_classification(parasympathetic=0.7, sympathetic=0.7, grounding=0.7)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 1
        assert flags[0].rule == "all_neuro_high"

    def test_normal_scores_no_flags(self):
        c = _make_classification(parasympathetic=0.7, sympathetic=0.3, grounding=0.5)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 0

    def test_exactly_at_threshold_not_flagged(self):
        """Scores of exactly 0.6 should NOT be flagged (> 0.6 required)."""
        c = _make_classification(parasympathetic=0.6, sympathetic=0.6, grounding=0.6)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 0

    def test_none_scores_no_flags(self):
        c = _make_classification(parasympathetic=None, sympathetic=None, grounding=None)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 0

    def test_partial_none_no_flags(self):
        c = _make_classification(parasympathetic=0.7, sympathetic=0.7, grounding=None)
        flags = _check_neuro_sanity(c)
        assert len(flags) == 0


# ---------------------------------------------------------------------------
# validate_classification (integration of all checks)
# ---------------------------------------------------------------------------

class TestValidateClassification:
    def test_clean_song_no_flags(self):
        c = _make_classification()
        result = validate_classification(c)
        assert result.flags == []
        assert result.adjusted_confidence == 0.5

    def test_confidence_reduced_by_penalty(self):
        c = _make_classification(bpm=60, energy=0.85, confidence=0.7)
        result = validate_classification(c)
        assert result.adjusted_confidence < 0.7
        total_penalty = sum(f.penalty for f in result.flags)
        assert abs(result.adjusted_confidence - (0.7 - total_penalty)) < 0.001

    def test_confidence_floors_at_zero(self):
        """Even with massive penalties, confidence can't go negative."""
        c = _make_classification(
            bpm=60, energy=0.9, acousticness=0.8,
            mood_tags=["calm", "soothing"],
            parasympathetic=0.7, sympathetic=0.7, grounding=0.7,
            confidence=0.1,
            classification_source="essentia+llm",
        )
        result = validate_classification(
            c,
            essentia_energy=0.9, essentia_acousticness=0.8,
            llm_energy=0.1, llm_acousticness=0.1,
        )
        assert result.adjusted_confidence >= 0.0

    def test_multiple_checks_accumulate(self):
        """Penalties from different checks are additive."""
        c = _make_classification(
            bpm=60, energy=0.85, acousticness=0.75,
            parasympathetic=0.7, sympathetic=0.7, grounding=0.3,
            confidence=0.7,
        )
        result = validate_classification(c)
        # low_bpm_high_energy (0.10) + high_acoustic_high_energy (0.08) + para_symp_both_high (0.08)
        expected = 0.7 - 0.10 - 0.08 - 0.08
        assert abs(result.adjusted_confidence - expected) < 0.001

    def test_original_confidence_preserved(self):
        c = _make_classification(confidence=0.8, bpm=60, energy=0.85)
        result = validate_classification(c)
        assert result.original_confidence == 0.8

    def test_essentia_llm_disagreement_passed_through(self):
        c = _make_classification(classification_source="essentia+llm")
        result = validate_classification(
            c, essentia_energy=0.9, llm_energy=0.2,
        )
        assert any(f.rule == "essentia_llm_energy_gap" for f in result.flags)


# ---------------------------------------------------------------------------
# validate_all_classifications (DB integration)
# ---------------------------------------------------------------------------

class TestValidateAllClassifications:
    def _setup_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE song_classifications (
                spotify_uri TEXT PRIMARY KEY,
                bpm REAL, energy REAL, acousticness REAL, valence REAL,
                danceability REAL, instrumentalness REAL,
                genre_tags TEXT, mood_tags TEXT, confidence REAL,
                parasympathetic REAL, sympathetic REAL, grounding REAL,
                classification_source TEXT, raw_response TEXT,
                classified_at TEXT, key TEXT, mode TEXT, felt_tempo INTEGER,
                essentia_energy REAL, essentia_acousticness REAL
            )
        """)
        conn.execute("""
            CREATE TABLE songs (
                spotify_uri TEXT PRIMARY KEY,
                name TEXT, artist TEXT, album TEXT, duration_ms INTEGER,
                play_count INTEGER, engagement_score REAL, last_played TEXT,
                release_year INTEGER, sources TEXT, first_played TEXT
            )
        """)
        return conn

    def test_returns_only_flagged_songs(self):
        conn = self._setup_db()
        # Clean song
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source)
               VALUES ('uri:clean', 100, 0.5, 0.5, 0.7, 0.4, 0.3, 0.5, 'llm')"""
        )
        conn.execute("INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:clean', 'Clean', 'Artist')")
        # Flagged song
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source)
               VALUES ('uri:bad', 60, 0.9, 0.5, 0.5, 0.7, 0.7, 0.7, 'llm')"""
        )
        conn.execute("INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:bad', 'Bad', 'Artist')")
        conn.commit()

        flagged = validate_all_classifications(conn)
        assert len(flagged) == 1
        assert flagged[0]["spotify_uri"] == "uri:bad"

    def test_sorted_by_worst_penalty_first(self):
        conn = self._setup_db()
        # Mildly flagged
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source)
               VALUES ('uri:mild', 60, 0.75, 0.5, 0.5, 0.4, 0.3, 0.5, 'llm')"""
        )
        conn.execute("INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:mild', 'Mild', 'Artist')")
        # Heavily flagged
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source)
               VALUES ('uri:severe', 60, 0.9, 0.5, 0.5, 0.7, 0.7, 0.7, 'llm')"""
        )
        conn.execute("INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:severe', 'Severe', 'Artist')")
        conn.commit()

        flagged = validate_all_classifications(conn)
        assert len(flagged) == 2
        assert flagged[0]["spotify_uri"] == "uri:severe"

    def test_extracts_llm_values_from_raw_response(self):
        """validate_all still extracts LLM values for cross-property checks."""
        conn = self._setup_db()
        raw = json.dumps({"songs": [{"title": "Test", "artist": "Art", "energy": 0.2, "acousticness": 0.9}]})
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, acousticness, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source, raw_response)
               VALUES ('uri:gap', 60, 0.85, 0.2, 0.5, 0.7, 0.4, 0.3, 0.5, 'llm', ?)""",
            (raw,),
        )
        conn.execute("INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:gap', 'Test', 'Art')")
        conn.commit()

        flagged = validate_all_classifications(conn)
        # Should flag low_bpm_high_energy and high_acoustic_high_energy
        assert len(flagged) == 1
        rules = {f["rule"] for f in flagged[0]["flags"]}
        assert "low_bpm_high_energy" in rules

    def test_essentia_llm_disagreement_with_essentia_columns(self):
        """validate_all_classifications uses essentia_energy/essentia_acousticness
        for the Essentia-LLM disagreement check."""
        conn = self._setup_db()
        raw = json.dumps({"songs": [{
            "title": "Essentia Test", "artist": "Art",
            "energy": 0.20, "acousticness": 0.80,
        }]})
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, acousticness, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source,
                raw_response, essentia_energy, essentia_acousticness)
               VALUES ('uri:ess', 100, 0.55, 0.45, 0.5, 0.7, 0.4, 0.3, 0.5,
                       'essentia+llm', ?, 0.90, 0.10)""",
            (raw,),
        )
        conn.execute(
            "INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:ess', 'Essentia Test', 'Art')"
        )
        conn.commit()

        flagged = validate_all_classifications(conn)
        assert len(flagged) == 1
        rules = {f["rule"] for f in flagged[0]["flags"]}
        # Essentia energy=0.90 vs LLM energy=0.20 → gap=0.70 > 0.3
        assert "essentia_llm_energy_gap" in rules
        # Essentia acousticness=0.10 vs LLM acousticness=0.80 → gap=0.70 > 0.3
        assert "essentia_llm_acousticness_gap" in rules

    def test_essentia_columns_null_skips_disagreement_check(self):
        """When essentia_* columns are NULL, disagreement check is skipped."""
        conn = self._setup_db()
        raw = json.dumps({"songs": [{
            "title": "No Ess", "artist": "Art",
            "energy": 0.20, "acousticness": 0.80,
        }]})
        conn.execute(
            """INSERT INTO song_classifications
               (spotify_uri, bpm, energy, acousticness, valence, confidence,
                parasympathetic, sympathetic, grounding, classification_source,
                raw_response)
               VALUES ('uri:noess', 100, 0.55, 0.45, 0.5, 0.7, 0.4, 0.3, 0.5,
                       'essentia+llm', ?)""",
            (raw,),
        )
        conn.execute(
            "INSERT INTO songs (spotify_uri, name, artist) VALUES ('uri:noess', 'No Ess', 'Art')"
        )
        conn.commit()

        flagged = validate_all_classifications(conn)
        # No essentia_* columns → disagreement check skipped → no flags from that check
        for song in flagged:
            for f in song["flags"]:
                assert f["rule"] not in ("essentia_llm_energy_gap", "essentia_llm_acousticness_gap")

    def test_empty_db_returns_empty(self):
        conn = self._setup_db()
        flagged = validate_all_classifications(conn)
        assert flagged == []
