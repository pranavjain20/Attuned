"""`--date` on match-songs and generate goes through main._parse_date_flag like every other command."""

import sys
from datetime import date
from unittest.mock import patch

import pytest

import main


def _run(monkeypatch, command, db_path, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", command, *args])
    {"match-songs": main._cmd_match_songs, "generate": main._cmd_generate}[command](db_path)


@pytest.mark.parametrize("command", ["match-songs", "generate"])
class TestDateFlag:
    @pytest.mark.parametrize("bad", ["21/10/2026", "2026-13-01", "yesterday"])
    def test_malformed_date_exits_before_any_work(self, monkeypatch, capsys, db_path, command, bad):
        with patch("matching.generator.select_day_songs") as select, \
             patch("matching.generator.generate_playlist") as generate, pytest.raises(SystemExit):
            _run(monkeypatch, command, db_path, "--date", bad, "--dry-run")
        assert "YYYY-MM-DD" in capsys.readouterr().out
        select.assert_not_called()
        generate.assert_not_called()

    def test_date_is_passed_through(self, monkeypatch, capsys, db_path, command):
        with patch("matching.generator.select_day_songs", side_effect=main_generation_error()) as select, \
             patch("matching.generator.generate_playlist", side_effect=main_generation_error()) as generate, \
             patch("whoop.sync.sync_today"):
            try:
                _run(monkeypatch, command, db_path, "--date", "2026-04-07", "--dry-run")
            except SystemExit:
                pass
        called = select if command == "match-songs" else generate
        args = called.call_args
        assert "2026-04-07" in list(args.args) + list(args.kwargs.values())

    def test_defaults_to_today(self, monkeypatch, capsys, db_path, command):
        with patch("matching.generator.select_day_songs", side_effect=main_generation_error()) as select, \
             patch("matching.generator.generate_playlist", side_effect=main_generation_error()) as generate, \
             patch("whoop.sync.sync_today"):
            try:
                _run(monkeypatch, command, db_path, "--dry-run")
            except SystemExit:
                pass
        called = select if command == "match-songs" else generate
        args = called.call_args
        assert date.today().isoformat() in list(args.args) + list(args.kwargs.values())


def main_generation_error():
    from matching.generator import GenerationError
    return GenerationError("stop here")
