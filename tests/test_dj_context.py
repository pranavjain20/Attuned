"""Tests for intelligence/dj_context.py — the Attuned body context the DJ is given."""

from unittest.mock import patch

import pytest

from intelligence.dj_context import CALIBRATION, attuned_context
from tests.test_feeling_score import HOUR, TARGET, _insert_day, _seed_history

# Phrases from the old WHOOP-recovery buckets; none may reach the DJ again.
OLD_WHOOP_PHRASES = (
    "Rough day", "Moderate day", "Decent day", "Great day", "Gentle is the default",
    "Middle-of-the-road energy", "Full energy is fair game", "fully charged",
)


def _scored(state, label, score, band, explanation):
    return {"score": score, "band": band, "state": state, "state_label": label,
            "explanation": explanation, "reason": None, "whoop_recovery": 91.0}


REST_DAY = _scored("rest", "Rest", 22, "red", [
    "You got 1.1 h of REM sleep, less than your usual 1.8 h.",
    "Your sleep was broken: asleep for only 79% of your time in bed (usual 89%).",
    "So today leans rest: you're likely to feel below your normal, so the music is built to help you settle.",
])
ENERGY_DAY = _scored("energy", "Energy", 84, "green", [
    "You slept 8.6 h, more than your usual 7.2 h.",
    "Your HRV was 61 ms, above your usual 48 ms.",
    "So today leans energy: you're likely to feel better than your normal, so the music is built to give you a lift.",
])
GROUNDING_DAY = _scored("grounding", "Grounding", 52, "yellow", [
    "Nothing stood out: your sleep and heart signals were all close to your normal.",
    "So today leans grounding: you're likely to feel close to your normal, so the music stays steady to keep you level.",
])
NO_SCORE_DAY = {"score": None, "band": None, "state": None, "state_label": None,
                "explanation": [], "reason": "No WHOOP data for 2026-10-21 yet.", "whoop_recovery": None}


def _context_for(scored):
    with patch("intelligence.dj_context.compute_feeling_score", return_value=scored) as score:
        text = attuned_context("conn", "2026-10-21")
    score.assert_called_once_with("conn", "2026-10-21")
    return text


class TestScoredDays:
    def test_rest_day(self):
        text = _context_for(REST_DAY)
        assert "Attuned score: 22/100 (red)." in text
        assert "State: Rest, music built to help you settle." in text
        assert "- You got 1.1 h of REM sleep, less than your usual 1.8 h." in text
        assert "- Your sleep was broken" in text
        assert f"Calibration: {CALIBRATION['rest']}" in text
        assert "unless they explicitly ask for energy" in text

    def test_energy_day(self):
        text = _context_for(ENERGY_DAY)
        assert "Attuned score: 84/100 (green)." in text
        assert "State: Energy, music built to give you a lift." in text
        assert "- Your HRV was 61 ms, above your usual 48 ms." in text
        assert f"Calibration: {CALIBRATION['energy']}" in text

    def test_grounding_day(self):
        text = _context_for(GROUNDING_DAY)
        assert "Attuned score: 52/100 (yellow)." in text
        assert "State: Grounding, music built to keep you level." in text
        assert "- Nothing stood out" in text
        assert f"Calibration: {CALIBRATION['grounding']}" in text

    @pytest.mark.parametrize("scored", [REST_DAY, ENERGY_DAY, GROUNDING_DAY])
    def test_state_line_not_repeated_from_explanation(self, scored):
        assert "So today leans" not in _context_for(scored)

    @pytest.mark.parametrize("scored", [REST_DAY, ENERGY_DAY, GROUNDING_DAY])
    def test_request_still_comes_first(self, scored):
        assert "Their request comes first" in _context_for(scored)

    @pytest.mark.parametrize("scored", [REST_DAY, ENERGY_DAY, GROUNDING_DAY, NO_SCORE_DAY])
    def test_no_whoop_recovery_numbers_or_buckets(self, scored):
        text = _context_for(scored)
        assert "recovery" not in text.lower()
        assert "91" not in text  # the day's WHOOP recovery in every fixture
        for phrase in OLD_WHOOP_PHRASES:
            assert phrase.lower() not in text.lower()

    def test_every_state_has_a_calibration(self):
        from intelligence.continuous_profile import STATES
        assert set(CALIBRATION) == {name for name, _label in STATES.values()}


class TestNoScore:
    def test_says_so_plainly_and_does_not_calibrate(self):
        text = _context_for(NO_SCORE_DAY)
        assert text == ("THEIR BODY TODAY: no Attuned score today (No WHOOP data for 2026-10-21 yet).\n"
                        "Don't adjust for their body. Go by what they tell you.")
        assert "Calibration" not in text

    def test_missing_reason_still_reads_cleanly(self):
        text = _context_for({**NO_SCORE_DAY, "reason": None})
        assert "no Attuned score today (no reason given)." in text


class TestErrorsSurface:
    def test_scoring_error_is_not_swallowed(self):
        """The old DJ hid a TypeError as 'no body data'. That must never happen again."""
        with patch("intelligence.dj_context.compute_feeling_score", side_effect=TypeError("boom")):
            with pytest.raises(TypeError):
                attuned_context("conn", "2026-10-21")


class TestRealScore:
    """End to end through compute_feeling_score on a seeded database."""

    def test_empty_database_has_no_score(self, db_conn):
        text = attuned_context(db_conn, TARGET)
        assert text.startswith("THEIR BODY TODAY: no Attuned score today (No WHOOP data for 2026-06-01 yet).")

    def test_terrible_night_leans_rest_even_with_high_whoop_recovery(self, db_conn):
        _seed_history(db_conn, TARGET, 120)
        _insert_day(db_conn, TARGET, 1, total_ms=3.9 * HOUR, eff=78, hrv=40, rhr=60, recovery=97)
        text = attuned_context(db_conn, TARGET)
        assert "(red)." in text
        assert "State: Rest, music built to help you settle." in text
        assert f"Calibration: {CALIBRATION['rest']}" in text
        assert "97" not in text
        assert "recovery" not in text.lower()
        why = [line for line in text.splitlines() if line.startswith("- ")]
        assert 1 <= len(why) <= 3
