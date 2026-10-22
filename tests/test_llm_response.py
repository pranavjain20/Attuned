"""Tests for classification/llm_response.py — finding one song in a stored LLM batch."""

import json

import pytest

from classification.llm_response import find_llm_song_result

_BATCH = json.dumps({"songs": [
    {"title": "Zara Sa", "artist": "KK", "bpm": 90},
    {"title": "Tere Bina", "artist": "A.R. Rahman", "bpm": 90},
]})


class TestFindLlmSongResult:
    def test_finds_song_by_title_and_artist(self):
        assert find_llm_song_result(_BATCH, "Tere Bina", "A.R. Rahman")["bpm"] == 90

    def test_ignores_case_and_surrounding_spaces(self):
        assert find_llm_song_result(_BATCH, "  zara sa ", "kk")["title"] == "Zara Sa"

    def test_same_title_different_artist_does_not_match(self):
        assert find_llm_song_result(_BATCH, "Tere Bina", "Zaeden") is None

    @pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]", '{"songs": ["x"]}'])
    def test_missing_or_malformed_response_returns_none(self, raw):
        assert find_llm_song_result(raw, "Zara Sa", "KK") is None
