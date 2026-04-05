"""Tests for whatsapp/handler.py — conversational DJ over WhatsApp."""

from unittest.mock import MagicMock, patch

import pytest


class TestHandleMessage:

    @patch("whatsapp.handler.threading")
    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.classify_state")
    @patch("whatsapp.handler.get_connection")
    def test_clear_request_returns_dj_message_and_spawns_thread(
        self, mock_conn, mock_state, mock_get_songs, mock_select, mock_threading,
    ):
        from whatsapp.handler import handle_message, _conversations

        mock_conn.return_value = MagicMock()
        mock_state.return_value = {"state": "baseline", "metrics": {"recovery_score": 60}}
        mock_select.return_value = {
            "needs_clarification": False,
            "dj_message": "Let's go!",
            "songs": [{"spotify_uri": "uri:1", "name": "Song", "artist": "Art"}] * 20,
            "playlist_name": "Gym Motivation",
        }

        reply = handle_message("+1111", "gym motivational")

        assert "Let's go!" in reply
        assert "Building your playlist" in reply
        assert "+1111" not in _conversations
        mock_threading.Thread.assert_called_once()

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.classify_state")
    @patch("whatsapp.handler.get_connection")
    def test_ambiguous_request_asks_clarification(
        self, mock_conn, mock_state, mock_get_songs, mock_select,
    ):
        from whatsapp.handler import handle_message, _conversations

        _conversations.clear()
        mock_conn.return_value = MagicMock()
        mock_state.return_value = {"state": "baseline", "metrics": {}}
        mock_select.return_value = {
            "needs_clarification": True,
            "clarifying_question": "What kind of sad?",
        }

        reply = handle_message("+1111", "im feeling sad")

        assert "What kind of sad?" in reply
        assert "+1111" in _conversations
        assert _conversations["+1111"]["original_query"] == "im feeling sad"

    @patch("whatsapp.handler.threading")
    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.classify_state")
    @patch("whatsapp.handler.get_connection")
    def test_clarification_reply_combines_and_generates(
        self, mock_conn, mock_state, mock_get_songs, mock_select, mock_threading,
    ):
        from whatsapp.handler import handle_message, _conversations

        import time
        _conversations["+1111"] = {"original_query": "im feeling sad", "timestamp": time.time()}

        mock_conn.return_value = MagicMock()
        mock_state.return_value = {"state": "baseline", "metrics": {}}
        mock_select.return_value = {
            "needs_clarification": False,
            "dj_message": "Heartbreak playlist incoming.",
            "songs": [{"spotify_uri": "uri:1", "name": "Song", "artist": "Art"}] * 20,
            "playlist_name": "Heartbreak Anthems",
        }

        reply = handle_message("+1111", "missing someone")

        mock_select.assert_called_once()
        call_query = mock_select.call_args[0][0]
        assert "im feeling sad" in call_query
        assert "missing someone" in call_query

        assert "Heartbreak playlist incoming." in reply
        assert "+1111" not in _conversations
        mock_threading.Thread.assert_called_once()

    def test_unknown_phone_returns_error(self):
        from whatsapp.handler import handle_message

        reply = handle_message("+9999999", "play something")
        assert "don't recognize" in reply.lower()

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.classify_state")
    @patch("whatsapp.handler.get_connection")
    def test_expired_conversation_treated_as_new(
        self, mock_conn, mock_state, mock_get_songs, mock_select,
    ):
        from whatsapp.handler import handle_message, _conversations, CONVERSATION_TTL_SECONDS

        import time
        _conversations["+1111"] = {
            "original_query": "old message",
            "timestamp": time.time() - CONVERSATION_TTL_SECONDS - 1,
        }

        mock_conn.return_value = MagicMock()
        mock_state.return_value = {"state": "baseline", "metrics": {}}
        mock_select.return_value = {
            "needs_clarification": True,
            "clarifying_question": "Tell me more?",
        }

        reply = handle_message("+1111", "new message")

        assert "Tell me more?" in reply
        assert _conversations["+1111"]["original_query"] == "new message"


class TestWebhookServer:

    def test_health_endpoint(self):
        from whatsapp.server import app

        with app.test_client() as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.data == b"ok"

    @patch("whatsapp.server.handle_message", return_value="Test reply")
    def test_webhook_parses_twilio_format(self, mock_handle):
        from whatsapp.server import app

        with app.test_client() as client:
            resp = client.post("/webhook", data={
                "From": "whatsapp:+1234567890",
                "Body": "play something chill",
            })
            assert resp.status_code == 200
            assert "Test reply" in resp.data.decode()
            mock_handle.assert_called_once_with("+1234567890", "play something chill")

    def test_webhook_empty_body(self):
        from whatsapp.server import app

        with app.test_client() as client:
            resp = client.post("/webhook", data={
                "From": "whatsapp:+1234567890",
                "Body": "",
            })
            assert resp.status_code == 200
            assert "Send me a message" in resp.data.decode()
