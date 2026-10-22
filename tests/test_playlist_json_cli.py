"""Tests for the `main.py playlist-json` command."""

import json
import sys
from unittest.mock import patch

import pytest

import main
from matching.generator import GenerationError

PAGE = {"name": "Apr 8 — Settle In", "spotify_url": None, "state": "rest",
        "tracks": [{"title": "Saibo", "artist": "Sachin-Jigar",
                    "spotify_url": "https://open.spotify.com/track/x", "why": "Soft — suits a rest day."}]}


def _run(monkeypatch, db_path, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", "playlist-json", *args])
    main._cmd_playlist_json(db_path)


class TestPlaylistJsonCommand:
    def test_prints_page_json_for_date(self, monkeypatch, capsys, db_path):
        with patch("matching.day_playlist.build_day_playlist", return_value=PAGE) as build:
            _run(monkeypatch, db_path, "--date", "2026-04-08")
        assert build.call_args.args[1] == "2026-04-08"
        assert json.loads(capsys.readouterr().out) == PAGE

    def test_keeps_non_ascii(self, monkeypatch, capsys, db_path):
        with patch("matching.day_playlist.build_day_playlist", return_value=PAGE):
            _run(monkeypatch, db_path, "--date", "2026-04-08")
        assert "—" in capsys.readouterr().out

    def test_generation_error_exits_cleanly(self, monkeypatch, capsys, db_path):
        with patch("matching.day_playlist.build_day_playlist",
                   side_effect=GenerationError("insufficient WHOOP data")):
            with pytest.raises(SystemExit) as exc:
                _run(monkeypatch, db_path, "--date", "2026-04-08")
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "insufficient WHOOP data" in captured.err

    def test_rejects_bad_date(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--date", "04/08/2026")
        assert "YYYY-MM-DD" in capsys.readouterr().out

    def test_rejects_missing_date_value(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--date")

    def test_never_touches_spotify(self, monkeypatch, capsys, db_path):
        with patch("matching.day_playlist.build_day_playlist", return_value=PAGE), \
             patch("spotify.auth.get_spotify_client") as client, \
             patch("spotify.playlist.create_playlist") as create:
            _run(monkeypatch, db_path, "--date", "2026-04-08")
        client.assert_not_called()
        create.assert_not_called()

    def test_listed_in_usage(self):
        assert "playlist-json" in main.COMMANDS


class TestPlaylistJsonRange:
    RESULTS = [
        {"date": "2026-10-01", "playlist": PAGE, "error": None},
        {"date": "2026-10-02", "playlist": None, "error": "insufficient WHOOP data"},
        {"date": "2026-10-03", "playlist": PAGE, "error": None},
    ]

    def test_writes_one_file_per_day(self, monkeypatch, capsys, db_path, tmp_path):
        out = tmp_path / "out"
        with patch("matching.day_playlist.build_day_playlists", return_value=self.RESULTS[:1]) as build:
            _run(monkeypatch, db_path, "--from", "2026-10-01", "--to", "2026-10-01", "--out", str(out))
        assert build.call_args.args[1:] == ("2026-10-01", "2026-10-01")
        assert json.loads((out / "2026-10-01.json").read_text()) == PAGE

    def test_failed_day_reported_others_written(self, monkeypatch, capsys, db_path, tmp_path):
        with patch("matching.day_playlist.build_day_playlists", return_value=self.RESULTS):
            with pytest.raises(SystemExit) as exc:
                _run(monkeypatch, db_path, "--from", "2026-10-01", "--to", "2026-10-03",
                     "--out", str(tmp_path))
        assert exc.value.code == 1
        assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-10-01.json", "2026-10-03.json"]
        assert "2026-10-02" in capsys.readouterr().err

    def test_requires_out(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--from", "2026-10-01", "--to", "2026-10-03")
        assert "--out" in capsys.readouterr().out

    def test_requires_both_ends(self, monkeypatch, capsys, db_path, tmp_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--from", "2026-10-01", "--out", str(tmp_path))

    def test_rejects_reversed_range(self, monkeypatch, capsys, db_path, tmp_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--from", "2026-10-03", "--to", "2026-10-01", "--out", str(tmp_path))
        assert "before" in capsys.readouterr().out

    def test_rejects_date_with_range(self, monkeypatch, capsys, db_path, tmp_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--date", "2026-10-01", "--from", "2026-10-01",
                 "--to", "2026-10-02", "--out", str(tmp_path))

    def test_rejects_bad_range_date(self, monkeypatch, capsys, db_path, tmp_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, db_path, "--from", "10/01/2026", "--to", "2026-10-02", "--out", str(tmp_path))
        assert "YYYY-MM-DD" in capsys.readouterr().out

    def test_listed_in_usage_with_range(self):
        assert "--from" in main.COMMANDS["playlist-json"]
