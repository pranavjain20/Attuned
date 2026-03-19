"""Tests for config.py — constants, thresholds, env var loaders."""

import os
from unittest.mock import patch

import pytest

import config


class TestConstants:
    def test_db_path_is_in_project_root(self):
        assert config.DB_PATH.name == "attuned.db"
        assert config.DB_PATH.parent == config.PROJECT_ROOT

    def test_whoop_page_size(self):
        assert config.WHOOP_PAGE_SIZE == 25

    def test_spotify_batch_size(self):
        assert config.SPOTIFY_BATCH_SIZE == 50

    def test_min_play_duration_ms(self):
        assert config.MIN_PLAY_DURATION_MS == 30_000

    def test_min_meaningful_listens(self):
        assert config.MIN_MEANINGFUL_LISTENS == 5

    def test_baseline_window_days(self):
        assert config.BASELINE_WINDOW_DAYS == 30

    def test_min_baseline_days(self):
        assert config.MIN_BASELINE_DAYS == 14

    def test_token_expiry_buffer(self):
        assert config.TOKEN_EXPIRY_BUFFER_SECONDS == 300

    def test_llm_batch_size(self):
        assert config.LLM_BATCH_SIZE == 5

    def test_llm_max_retries(self):
        assert config.LLM_MAX_RETRIES == 3

    def test_min_classification_listens(self):
        assert config.MIN_CLASSIFICATION_LISTENS == 2

    def test_indian_genre_tags_is_frozenset(self):
        assert isinstance(config.INDIAN_GENRE_TAGS, frozenset)
        assert "bollywood" in config.INDIAN_GENRE_TAGS
        assert "hindi" in config.INDIAN_GENRE_TAGS
        assert "punjabi" in config.INDIAN_GENRE_TAGS


class TestEnvVarGetters:
    def test_whoop_client_id_raises_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            # Also clear dotenv-loaded values
            with patch("config.os.getenv", return_value=None):
                with pytest.raises(RuntimeError, match="WHOOP_CLIENT_ID"):
                    config.get_whoop_client_id()

    def test_whoop_client_id_returns_value(self):
        with patch("config.os.getenv", return_value="test_id"):
            assert config.get_whoop_client_id() == "test_id"

    def test_whoop_client_secret_raises_when_missing(self):
        with patch("config.os.getenv", return_value=None):
            with pytest.raises(RuntimeError, match="WHOOP_CLIENT_SECRET"):
                config.get_whoop_client_secret()

    def test_spotify_client_id_raises_when_missing(self):
        with patch("config.os.getenv", return_value=None):
            with pytest.raises(RuntimeError, match="SPOTIFY_CLIENT_ID"):
                config.get_spotify_client_id()

    def test_spotify_client_secret_raises_when_missing(self):
        with patch("config.os.getenv", return_value=None):
            with pytest.raises(RuntimeError, match="SPOTIFY_CLIENT_SECRET"):
                config.get_spotify_client_secret()

    def test_whoop_redirect_uri_has_default(self):
        assert "localhost" in config.get_whoop_redirect_uri()

    def test_spotify_redirect_uri_has_default(self):
        assert "127.0.0.1" in config.get_spotify_redirect_uri()

    def test_openai_api_key_raises_when_missing(self):
        with patch("config.os.getenv", return_value=None):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                config.get_openai_api_key()

    def test_openai_api_key_returns_value(self):
        with patch("config.os.getenv", return_value="sk-test"):
            assert config.get_openai_api_key() == "sk-test"

    def test_anthropic_api_key_raises_when_missing(self):
        with patch("config.os.getenv", return_value=None):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                config.get_anthropic_api_key()

    def test_anthropic_api_key_returns_value(self):
        with patch("config.os.getenv", return_value="sk-ant-test"):
            assert config.get_anthropic_api_key() == "sk-ant-test"
