"""Tests for the natural-language DJ paths outside WhatsApp:
matching/generator.generate_nl_playlist and the `main.py request` CLI command.

The LLM and Spotify are mocked: no network or API calls.
"""

import json
import sys
from datetime import date
from unittest.mock import patch

import pytest

import main
from matching.generator import generate_nl_playlist

SONGS = [{"spotify_uri": f"spotify:track:{i}", "name": f"Song {i}", "artist": f"Artist {i}"}
         for i in range(20)]


def _picked(context="BODY CONTEXT"):
    return {"needs_clarification": False, "dj_message": "Easy does it.", "songs": SONGS,
            "playlist_name": "Slow Sunday", "body_context": context}


def _stored_playlist(conn):
    return conn.execute("SELECT reasoning, whoop_metrics FROM generated_playlists").fetchone()


class TestGenerateNlPlaylist:
    @patch("intelligence.nl_song_selector.select_songs_nl")
    @patch("db.queries.get_all_classified_songs", return_value=SONGS)
    @patch("matching.generator.attuned_context", return_value="BODY CONTEXT")
    def test_dj_gets_the_attuned_context_for_the_date(self, mock_context, _songs, mock_select, db_conn):
        mock_select.return_value = _picked()

        generate_nl_playlist(db_conn, None, "something chill", date_str="2026-10-19", dry_run=True)

        mock_context.assert_called_once_with(db_conn, "2026-10-19")
        assert mock_select.call_args.args == ("something chill", SONGS, "BODY CONTEXT")

    @patch("intelligence.nl_song_selector.select_songs_nl")
    @patch("db.queries.get_all_classified_songs", return_value=SONGS)
    def test_real_context_call_reaches_the_dj(self, _songs, mock_select, db_conn):
        """Regression: a wrong call signature must fail, not quietly become 'no data'."""
        mock_select.return_value = _picked()

        generate_nl_playlist(db_conn, None, "something chill", date_str="2026-10-19", dry_run=True)

        context = mock_select.call_args.args[2]
        assert context.startswith("THEIR BODY TODAY: no Attuned score today (No WHOOP data for 2026-10-19")

    @patch("matching.generator.attuned_context")
    def test_preselected_result_skips_the_context_lookup(self, mock_context, db_conn):
        generate_nl_playlist(db_conn, None, "q", date_str="2026-10-19", dry_run=True, nl_result=_picked())
        mock_context.assert_not_called()

    @patch("matching.generator.attuned_context", side_effect=TypeError("bad call"))
    @patch("db.queries.get_all_classified_songs", return_value=SONGS)
    def test_context_error_propagates(self, _songs, _context, db_conn):
        with pytest.raises(TypeError, match="bad call"):
            generate_nl_playlist(db_conn, None, "q", date_str="2026-10-19", dry_run=True)

    def test_log_records_what_the_dj_was_told_not_whoop_recovery(self, db_conn):
        generate_nl_playlist(db_conn, None, "something chill", date_str="2026-10-19",
                             dry_run=True, nl_result=_picked("Attuned score: 22/100 (red)."))

        reasoning, metrics = _stored_playlist(db_conn)
        assert reasoning == 'NL request: "something chill"\nAttuned score: 22/100 (red).'
        assert json.loads(metrics) == {"nl_query": "something chill"}

    def test_log_without_recorded_context(self, db_conn):
        nl_result = {k: v for k, v in _picked().items() if k != "body_context"}
        generate_nl_playlist(db_conn, None, "q", date_str="2026-10-19", dry_run=True, nl_result=nl_result)
        assert _stored_playlist(db_conn)[0] == 'NL request: "q"'


class TestRequestCommand:
    def _run(self, monkeypatch, db_path, select_side_effect, answer=""):
        monkeypatch.setattr(sys, "argv", ["main.py", "request", "something", "chill", "--dry-run"])
        monkeypatch.setattr("builtins.input", lambda _prompt: answer)
        result = {"name": "Oct 21 — Slow", "description": "d", "songs": SONGS}
        with patch("intelligence.nl_song_selector.select_songs_nl",
                   side_effect=select_side_effect) as select, \
             patch("db.queries.get_all_classified_songs", return_value=SONGS), \
             patch("matching.generator.generate_nl_playlist", return_value=result):
            main._cmd_request(db_path)
        return select

    def test_dj_gets_todays_context(self, monkeypatch, db_path):
        with patch("intelligence.dj_context.attuned_context", return_value="BODY CONTEXT") as ctx:
            select = self._run(monkeypatch, db_path, [_picked()])
        assert ctx.call_args.args[1] == date.today().isoformat()
        assert select.call_args.args == ("something chill", SONGS, "BODY CONTEXT")

    def test_every_reselection_keeps_the_context(self, monkeypatch, db_path):
        question = {"needs_clarification": True, "clarifying_question": "Mellow?"}
        with patch("intelligence.dj_context.attuned_context", return_value="BODY CONTEXT"):
            select = self._run(monkeypatch, db_path, [question, question, _picked()], answer="mellow")
        assert [c.args[2] for c in select.call_args_list] == ["BODY CONTEXT"] * 3

    def test_real_context_call_reaches_the_dj(self, monkeypatch, db_path):
        """Regression: the old CLI called classify_state(conn) without its date and
        swallowed the TypeError. The real attuned_context must reach the DJ."""
        select = self._run(monkeypatch, db_path, [_picked()])
        assert select.call_args.args[2].startswith("THEIR BODY TODAY: no Attuned score today")

    def test_context_error_is_not_swallowed(self, monkeypatch, db_path):
        with patch("intelligence.dj_context.attuned_context", side_effect=TypeError("bad call")):
            with pytest.raises(TypeError, match="bad call"):
                self._run(monkeypatch, db_path, [_picked()])
