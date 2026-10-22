"""Tests for the `main.py feeling-score` command."""

import json
import sys

import pytest

import main
from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from db.schema import get_connection


def _run(monkeypatch, capsys, db_path, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", "feeling-score", *args])
    main._cmd_feeling_score(db_path)
    return capsys.readouterr().out


class TestFeelingScoreCommand:
    def test_json_output_is_page_contract(self, monkeypatch, capsys, db_path):
        conn = get_connection(db_path)
        upsert_whoop_recovery(conn, cycle_id=1, date="2026-06-01", recovery_score=60,
                              hrv_rmssd_milli=45, resting_heart_rate=55)
        upsert_whoop_sleep(conn, sleep_id="s", date="2026-06-01", nap=False,
                           deep_sleep_ms=5_000_000, rem_sleep_ms=6_000_000, light_sleep_ms=14_000_000)
        conn.close()
        day = json.loads(_run(monkeypatch, capsys, db_path, "--date", "2026-06-01", "--json"))
        assert day["date"] == "2026-06-01"
        assert day["whoop"] == {"recovery": 60, "band": "yellow"}
        assert day["attuned"]["score"] is None  # no history yet
        assert day["attuned"]["reason"]
        assert day["playlist"] is None

    def test_text_output_explains_missing_score(self, monkeypatch, capsys, db_path):
        get_connection(db_path).close()
        out = _run(monkeypatch, capsys, db_path, "--date", "2026-06-01")
        assert "no score" in out
        assert "No WHOOP data" in out

    def test_rejects_bad_date(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, capsys, db_path, "--date", "06/01/2026")
        assert "YYYY-MM-DD" in capsys.readouterr().out

    def test_rejects_missing_date_value(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            _run(monkeypatch, capsys, db_path, "--date")
