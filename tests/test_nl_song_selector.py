"""Tests for intelligence/nl_song_selector.py — the body context reaches the LLM prompt.

The LLM is mocked: no network or API calls.
"""

import json
from unittest.mock import patch

import pytest

import intelligence.nl_song_selector as selector
from intelligence.nl_song_selector import select_songs_nl

CONTEXT = "THEIR BODY TODAY: Attuned score 22/100 (red). Calibration: today leans calm."
SONGS = [{"name": f"Song {i}", "artist": f"Artist {i % 5}", "spotify_uri": f"uri:{i}",
          "mood_tags": ["calm"], "energy": 0.3, "valence": 0.5, "engagement_score": 0.1}
         for i in range(25)]
PICKED = json.dumps({"needs_clarification": False, "dj_message": "Easy does it.",
                     "song_indices": list(range(1, 21)), "playlist_name": "Slow Sunday"})
QUESTION = json.dumps({"needs_clarification": True, "clarifying_question": "Mellow or upbeat?"})


def _select(reply, context=CONTEXT):
    with patch("llm_client.call_anthropic", return_value=reply) as llm, \
         patch("config.get_anthropic_api_key", return_value="test-key"):
        result = select_songs_nl("something chill", SONGS, context)
    return result, llm.call_args.kwargs["system"]


class TestBodyContextInPrompt:
    def test_context_text_goes_into_the_system_prompt(self):
        _result, system = _select(PICKED)
        assert CONTEXT in system

    def test_prompt_has_no_whoop_recovery_steering(self):
        _result, system = _select(PICKED)
        assert "recovery" not in system.lower()
        assert "WHOOP" not in system

    def test_whoop_bucket_builder_is_gone(self):
        assert not hasattr(selector, "_build_whoop_context")
        assert not hasattr(selector, "_WHOOP_CONTEXT_AVAILABLE")
        assert not hasattr(selector, "_WHOOP_CONTEXT_NONE")

    def test_body_context_is_required(self):
        with pytest.raises(TypeError):
            select_songs_nl("something chill", SONGS)


class TestResultRecordsContext:
    def test_picked_result_carries_the_context(self):
        result, _system = _select(PICKED)
        assert result["body_context"] == CONTEXT
        assert len(result["songs"]) == 20

    def test_clarifying_result_carries_the_context(self):
        result, _system = _select(QUESTION)
        assert result["needs_clarification"] is True
        assert result["body_context"] == CONTEXT
