"""Tests for whatsapp/handler.py — conversational DJ over WhatsApp."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _fresh_state():
    """Each test starts with no pending clarifications and no cached body context."""
    from whatsapp import handler
    handler._conversations.clear()
    handler._context_cache.clear()
    yield
    handler._conversations.clear()
    handler._context_cache.clear()


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 22)


class TestHandleMessage:

    @patch("whatsapp.handler.threading")
    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_clear_request_returns_dj_message_and_spawns_thread(
        self, mock_conn, mock_context, mock_get_songs, mock_select, mock_threading,
    ):
        from whatsapp.handler import handle_message, _conversations

        mock_conn.return_value = MagicMock()
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
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_ambiguous_request_asks_clarification(
        self, mock_conn, mock_context, mock_get_songs, mock_select,
    ):
        from whatsapp.handler import handle_message, _conversations

        _conversations.clear()
        mock_conn.return_value = MagicMock()
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
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_clarification_reply_combines_and_generates(
        self, mock_conn, mock_context, mock_get_songs, mock_select, mock_threading,
    ):
        from whatsapp.handler import handle_message, _conversations

        import time
        _conversations["+1111"] = {"original_query": "im feeling sad", "timestamp": time.time()}

        mock_conn.return_value = MagicMock()
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
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_expired_conversation_treated_as_new(
        self, mock_conn, mock_context, mock_get_songs, mock_select,
    ):
        from whatsapp.handler import handle_message, _conversations, CONVERSATION_TTL_SECONDS

        import time
        _conversations["+1111"] = {
            "original_query": "old message",
            "timestamp": time.time() - CONVERSATION_TTL_SECONDS - 1,
        }

        mock_conn.return_value = MagicMock()
        mock_select.return_value = {
            "needs_clarification": True,
            "clarifying_question": "Tell me more?",
        }

        reply = handle_message("+1111", "new message")

        assert "Tell me more?" in reply
        assert _conversations["+1111"]["original_query"] == "new message"


class TestBodyContext:
    """The DJ is told today's Attuned score — and a broken lookup is never hidden."""

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_todays_context_is_passed_to_the_dj(
        self, mock_conn, mock_context, mock_get_songs, mock_select,
    ):
        from whatsapp.handler import handle_message

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_select.return_value = {"needs_clarification": True, "clarifying_question": "Mellow?"}

        with patch("whatsapp.handler.date", _FrozenDate):  # a run across midnight can't flake
            handle_message("+1111", "something chill")

        mock_context.assert_called_once_with(conn, "2026-10-22")
        assert mock_select.call_args.args[2] == "BODY CONTEXT"

    @patch("whatsapp.handler.threading")
    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_forced_reselection_keeps_the_context(
        self, mock_conn, mock_context, mock_get_songs, mock_select, mock_threading,
    ):
        import time

        from whatsapp.handler import handle_message, _conversations

        _conversations["+1111"] = {"original_query": "sad", "timestamp": time.time()}
        mock_conn.return_value = MagicMock()
        mock_select.side_effect = [
            {"needs_clarification": True, "clarifying_question": "Which sad?"},
            {"needs_clarification": False, "dj_message": "Here.", "songs": [], "playlist_name": "X"},
        ]

        handle_message("+1111", "missing someone")

        assert [c.args[2] for c in mock_select.call_args_list] == ["BODY CONTEXT", "BODY CONTEXT"]

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_connection")
    def test_real_context_call_reaches_the_dj(self, mock_conn, mock_select, db_path):
        """Regression: the old handler called classify_state(conn) without its date;
        the TypeError was swallowed and the DJ ran blind. With the real
        attuned_context and a real (empty) database, the DJ must get a real
        'no score' context — any wrong call signature fails this test."""
        from db.schema import get_connection
        from whatsapp.handler import handle_message, _conversations

        _conversations.clear()
        mock_conn.return_value = get_connection(db_path)
        mock_select.return_value = {"needs_clarification": True, "clarifying_question": "Mellow?"}

        reply = handle_message("+1111", "something chill")

        assert reply == "🎵 Mellow?"
        context = mock_select.call_args.args[2]
        assert context.startswith("THEIR BODY TODAY: no Attuned score today (No WHOOP data for")
        _conversations.clear()

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", side_effect=TypeError("bad call"))
    @patch("whatsapp.handler.get_connection")
    def test_context_error_is_logged_loudly_and_the_request_still_answered(
        self, mock_conn, mock_context, mock_get_songs, mock_select, caplog,
    ):
        """The request comes first: a broken body context mustn't cost the reply, but it
        must never pass silently either (full traceback in the log)."""
        from whatsapp.handler import NO_BODY_CONTEXT, handle_message

        mock_conn.return_value = MagicMock()
        mock_select.return_value = {"needs_clarification": True, "clarifying_question": "Mellow?"}

        reply = handle_message("+1111", "something chill")

        assert reply == "🎵 Mellow?"
        assert mock_select.call_args.args[2] == NO_BODY_CONTEXT
        assert "no body data today" in NO_BODY_CONTEXT.lower()
        record = next(r for r in caplog.records if "body context" in r.getMessage())
        assert record.levelname == "ERROR" and record.exc_info is not None
        assert "bad call" in caplog.text

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", side_effect=[TypeError("bad call"), "BODY CONTEXT"])
    @patch("whatsapp.handler.get_connection")
    def test_failed_context_is_not_cached(self, mock_conn, mock_context, mock_get_songs, mock_select):
        from whatsapp.handler import handle_message

        mock_conn.return_value = MagicMock()
        mock_select.return_value = {"needs_clarification": True, "clarifying_question": "Mellow?"}

        handle_message("+1111", "something chill")
        handle_message("+1111", "still chill")

        assert mock_context.call_count == 2
        assert mock_select.call_args.args[2] == "BODY CONTEXT"


class TestContextCache:
    """Building the context replays the score history (~3 s): once per profile and day, not per message."""

    def _message(self, mock_select, phone, text):
        """A fresh request that gets a clarifying question back (no playlist thread)."""
        from whatsapp.handler import _conversations, handle_message
        _conversations.clear()
        mock_select.return_value = {"needs_clarification": True, "clarifying_question": "Mellow?"}
        return handle_message(phone, text)

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser", "+2222": "other"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", return_value="BODY CONTEXT")
    @patch("whatsapp.handler.get_connection")
    def test_second_message_reuses_the_days_context(self, mock_conn, mock_context, mock_get_songs, mock_select):
        mock_conn.return_value = MagicMock()
        with patch("whatsapp.handler.date", _FrozenDate):
            self._message(mock_select, "+1111", "something chill")
            self._message(mock_select, "+1111", "something upbeat")
        assert mock_context.call_count == 1
        assert [c.args[2] for c in mock_select.call_args_list] == ["BODY CONTEXT", "BODY CONTEXT"]

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser", "+2222": "other"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", side_effect=["MINE", "THEIRS"])
    @patch("whatsapp.handler.get_connection")
    def test_each_profile_has_its_own_context(self, mock_conn, mock_context, mock_get_songs, mock_select):
        mock_conn.return_value = MagicMock()
        with patch("whatsapp.handler.date", _FrozenDate):
            self._message(mock_select, "+1111", "a")
            self._message(mock_select, "+2222", "b")
        assert [c.args[2] for c in mock_select.call_args_list] == ["MINE", "THEIRS"]

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", side_effect=["MONDAY", "TUESDAY"])
    @patch("whatsapp.handler.get_connection")
    def test_a_new_day_builds_a_new_context(self, mock_conn, mock_context, mock_get_songs, mock_select):
        class NextDay(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 23)
        mock_conn.return_value = MagicMock()
        with patch("whatsapp.handler.date", _FrozenDate):
            self._message(mock_select, "+1111", "a")
        with patch("whatsapp.handler.date", NextDay):
            self._message(mock_select, "+1111", "b")
        assert [c.args[2] for c in mock_select.call_args_list] == ["MONDAY", "TUESDAY"]
        assert mock_context.call_args.args[1] == "2026-10-23"

    @patch("whatsapp.handler.PHONE_TO_PROFILE", {"+1111": "testuser"})
    @patch("whatsapp.handler.select_songs_nl")
    @patch("whatsapp.handler.get_all_classified_songs", return_value=[])
    @patch("whatsapp.handler.attuned_context", side_effect=["BEFORE SYNC", "AFTER SYNC"])
    @patch("whatsapp.handler.get_connection")
    def test_context_expires_so_a_later_whoop_sync_is_seen(
        self, mock_conn, mock_context, mock_get_songs, mock_select,
    ):
        """Morning WHOOP data can land after the first message; the cache must not hide it all day."""
        from whatsapp.handler import CONTEXT_TTL_SECONDS
        mock_conn.return_value = MagicMock()
        with patch("whatsapp.handler.date", _FrozenDate), patch("whatsapp.handler.time.time", return_value=1000.0):
            self._message(mock_select, "+1111", "a")
        later = 1000.0 + CONTEXT_TTL_SECONDS + 1
        with patch("whatsapp.handler.date", _FrozenDate), patch("whatsapp.handler.time.time", return_value=later):
            self._message(mock_select, "+1111", "b")
        assert [c.args[2] for c in mock_select.call_args_list] == ["BEFORE SYNC", "AFTER SYNC"]


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
