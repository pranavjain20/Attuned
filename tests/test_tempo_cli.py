"""Tests for the tempo commands in main.py: update-tempos, set-tempo,
fetch-soundcharts-tempos, and recompute-scores scoring at the corrected tempo."""

import json
import sys
from unittest.mock import patch

import pytest

import main
from classification.soundcharts import SoundchartsResponse
from db import queries
from db.schema import get_connection

_BALLAD_URI = "spotify:track:ballad"


def _seed_ballad(db_path, **columns):
    """Tere Mast Mast Do Nain as stored before the fix: bpm 154, trackers 152, LLM 80."""
    conn = get_connection(db_path)
    queries.upsert_song(conn, _BALLAD_URI, "Tere Mast Mast Do Nain", "Rahat")
    conn.execute("UPDATE songs SET engagement_score = 0.8 WHERE spotify_uri = ?", (_BALLAD_URI,))
    raw = json.dumps({"songs": [{
        "title": "Tere Mast Mast Do Nain", "artist": "Rahat", "bpm": 80,
        "energy": 0.4, "acousticness": 0.5,
        "para_score": 0.6, "symp_score": 0.3, "grounding_score": 0.6,
    }]})
    queries.upsert_song_classification(conn, {
        "spotify_uri": _BALLAD_URI, "bpm": 154, "energy": 0.45, "acousticness": 0.5,
        "essentia_energy": 0.45, "essentia_acousticness": 0.5,
        "danceability": 0.5, "instrumentalness": 0.0, "valence": 0.5, "mode": "major",
        "mood_tags": ["romantic", "nostalgic"], "genre_tags": ["bollywood"],
        "classification_source": "essentia+llm", "raw_response": raw,
    })
    queries.update_tempo_readings(conn, _BALLAD_URI, {
        "essentia_bpm": 152.0, "essentia_degara_bpm": 152.2, "tempocnn_bpm": 152.0,
    })
    if columns:
        sets = ", ".join(f"{k} = ?" for k in columns)
        conn.execute(f"UPDATE song_classifications SET {sets} WHERE spotify_uri = ?",
                     (*columns.values(), _BALLAD_URI))
    conn.commit()
    conn.close()


def _row(db_path):
    conn = get_connection(db_path)
    row = dict(conn.execute(
        """SELECT bpm, tempo, tempo_source, tempo_confidence,
                  parasympathetic, sympathetic, grounding, energy, acousticness
           FROM song_classifications WHERE spotify_uri = ?""", (_BALLAD_URI,),
    ).fetchone())
    conn.close()
    return row


def _run(monkeypatch, capsys, command, db_path, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", command, *args])
    {
        "update-tempos": main._cmd_update_tempos,
        "set-tempo": main._cmd_set_tempo,
        "recompute-scores": main._cmd_recompute_scores,
        "fetch-soundcharts-tempos": main._cmd_fetch_soundcharts_tempos,
    }[command](db_path)
    return capsys.readouterr().out


class TestUpdateTemposCommand:
    def test_writes_tempo_and_reports_counts(self, monkeypatch, capsys, db_path):
        _seed_ballad(db_path)
        out = _run(monkeypatch, capsys, "update-tempos", db_path)
        assert _row(db_path)["tempo"] == pytest.approx(76.0, abs=0.2)
        assert _row(db_path)["bpm"] == 154
        assert "Decided tempo for 1 songs" in out
        assert "audio+llm_octave 1" in out


class TestRecomputeScoresReadsTempo:
    def test_scores_at_corrected_tempo_not_bpm(self, monkeypatch, capsys, db_path):
        """Halving 154 → 76 must make the ballad less energising (lower symp)."""
        _seed_ballad(db_path)
        _run(monkeypatch, capsys, "recompute-scores", db_path)
        at_bpm = _row(db_path)  # no tempo yet → falls back to bpm 154

        _run(monkeypatch, capsys, "update-tempos", db_path)
        _run(monkeypatch, capsys, "recompute-scores", db_path)
        at_tempo = _row(db_path)

        assert at_tempo["sympathetic"] < at_bpm["sympathetic"]
        assert at_tempo["parasympathetic"] > at_bpm["parasympathetic"]

    def test_update_then_recompute_twice_is_idempotent(self, monkeypatch, capsys, db_path):
        _seed_ballad(db_path)
        _run(monkeypatch, capsys, "update-tempos", db_path)
        _run(monkeypatch, capsys, "recompute-scores", db_path)
        first = _row(db_path)
        _run(monkeypatch, capsys, "update-tempos", db_path)
        _run(monkeypatch, capsys, "recompute-scores", db_path)
        assert _row(db_path) == first


class TestSetTempoCommand:
    def test_pins_tempo_by_title(self, monkeypatch, capsys, db_path):
        _seed_ballad(db_path)
        out = _run(monkeypatch, capsys, "set-tempo", db_path, "tere mast mast do nain", "150")
        row = _row(db_path)
        assert (row["tempo"], row["tempo_source"], row["tempo_confidence"]) == (150.0, "manual", "high")
        assert "→ 150 (manual)" in out

    def test_manual_tempo_survives_update_tempos(self, monkeypatch, capsys, db_path):
        _seed_ballad(db_path)
        _run(monkeypatch, capsys, "set-tempo", db_path, _BALLAD_URI, "150")
        _run(monkeypatch, capsys, "update-tempos", db_path)
        assert _row(db_path)["tempo"] == 150.0

    @pytest.mark.parametrize("args, message", [
        ((), "Usage"),
        (("Tere Mast Mast Do Nain",), "Usage"),
        (("Tere Mast Mast Do Nain", "fast"), "must be a number"),
        (("Tere Mast Mast Do Nain", "500"), "between 30 and 300"),
        (("Unknown Song", "100"), "No classified song"),
    ])
    def test_rejects_bad_input_without_writing(self, monkeypatch, capsys, db_path, args, message):
        _seed_ballad(db_path)
        with pytest.raises(SystemExit):
            _run(monkeypatch, capsys, "set-tempo", db_path, *args)
        assert message in capsys.readouterr().out
        assert _row(db_path)["tempo"] is None


class TestFetchSoundchartsTemposCommand:
    def _seed_no_clip(self, db_path):
        _seed_ballad(db_path)
        conn = get_connection(db_path)
        queries.update_tempo_readings(conn, _BALLAD_URI, {})  # no audio clip
        conn.commit()
        conn.close()

    def test_fetches_and_stores_with_limit(self, monkeypatch, capsys, db_path):
        self._seed_no_clip(db_path)
        monkeypatch.setenv("SOUNDCHARTS_APP_ID", " app ")
        monkeypatch.setenv("SOUNDCHARTS_API_KEY", "key")
        with patch("classification.soundcharts.fetch_soundcharts_song",
                   return_value=SoundchartsResponse({"audio": {"tempo": 152.0}}, 700)) as fetch:
            out = _run(monkeypatch, capsys, "fetch-soundcharts-tempos", db_path, "--limit", "5")
        fetch.assert_called_once_with(_BALLAD_URI, "app", "key")
        assert "1 tempos stored" in out
        assert "Quota remaining: 700" in out

    @pytest.mark.parametrize("limit", ["0", "-3", "ten"])
    def test_rejects_bad_limit(self, monkeypatch, capsys, db_path, limit):
        with pytest.raises(SystemExit):
            _run(monkeypatch, capsys, "fetch-soundcharts-tempos", db_path, "--limit", limit)
        assert "--limit must be a positive whole number" in capsys.readouterr().out

    def test_missing_credentials_fail_loudly(self, monkeypatch, capsys, db_path):
        monkeypatch.delenv("SOUNDCHARTS_APP_ID", raising=False)
        with pytest.raises(RuntimeError, match="SOUNDCHARTS_APP_ID"):
            _run(monkeypatch, capsys, "fetch-soundcharts-tempos", db_path)
