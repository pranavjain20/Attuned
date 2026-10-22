"""Tests for classification/soundcharts.py — Soundcharts tempo for no-clip songs."""

from unittest.mock import MagicMock

import httpx
import pytest

from classification.soundcharts import (
    SoundchartsResponse,
    SoundchartsStop,
    backfill_soundcharts_tempos,
    fetch_soundcharts_song,
    get_songs_needing_soundcharts_tempo,
    parse_soundcharts_tempo,
)
from db import queries


def _http_response(status: int, json_body=None, quota: str | None = "845", text: str = ""):
    response = MagicMock()
    response.status_code = status
    response.headers = {"x-quota-remaining": quota} if quota is not None else {}
    response.text = text
    if isinstance(json_body, Exception):
        response.json.side_effect = json_body
    else:
        response.json.return_value = json_body
    return response


class TestFetchSoundchartsSong:
    def test_calls_by_spotify_id_with_credentials(self):
        http_get = MagicMock(return_value=_http_response(200, {"object": {"audio": {"tempo": 152.0}}}))

        result = fetch_soundcharts_song("spotify:track:abc123", "app", "key", http_get=http_get)

        url = http_get.call_args.args[0]
        assert url.endswith("/song/by-platform/spotify/abc123")
        assert http_get.call_args.kwargs["headers"] == {"x-app-id": "app", "x-api-key": "key"}
        assert result == SoundchartsResponse({"audio": {"tempo": 152.0}}, 845)

    def test_not_found_returns_no_song(self):
        http_get = MagicMock(return_value=_http_response(404, quota="844"))
        result = fetch_soundcharts_song("spotify:track:x", "a", "k", http_get=http_get)
        assert result == SoundchartsResponse(None, 844)

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_auth_or_quota_refusal_stops_the_run(self, status):
        http_get = MagicMock(return_value=_http_response(status, text="nope"))
        with pytest.raises(SoundchartsStop, match=str(status)):
            fetch_soundcharts_song("spotify:track:x", "a", "k", http_get=http_get)

    def test_network_error_returns_no_song(self):
        http_get = MagicMock(side_effect=httpx.ConnectTimeout("slow"))
        result = fetch_soundcharts_song("spotify:track:x", "a", "k", http_get=http_get)
        assert result == SoundchartsResponse(None, None)

    def test_malformed_json_returns_no_song(self):
        http_get = MagicMock(return_value=_http_response(200, ValueError("bad json")))
        assert fetch_soundcharts_song("spotify:track:x", "a", "k", http_get=http_get).song is None

    def test_missing_quota_header(self):
        http_get = MagicMock(return_value=_http_response(200, {"object": {}}, quota=None))
        assert fetch_soundcharts_song("spotify:track:x", "a", "k", http_get=http_get).quota_remaining is None


class TestParseSoundchartsTempo:
    def test_reads_audio_tempo(self):
        assert parse_soundcharts_tempo({"audio": {"tempo": 108.02}}) == 108.02

    @pytest.mark.parametrize("song", [
        None, {}, {"audio": None}, {"audio": {}}, {"audio": {"tempo": None}},
        {"audio": {"tempo": "fast"}}, {"audio": {"tempo": 0}}, {"audio": {"tempo": 400}},
    ])
    def test_missing_or_implausible_tempo_is_none(self, song):
        assert parse_soundcharts_tempo(song) is None


def _seed(db_conn, uri, *, engagement=1.0, **columns):
    queries.upsert_song(db_conn, uri, f"Song {uri}", "Artist")
    db_conn.execute("UPDATE songs SET engagement_score = ? WHERE spotify_uri = ?", (engagement, uri))
    queries.upsert_song_classification(db_conn, {"spotify_uri": uri, "bpm": 100, "valence": 0.5})
    if columns:
        sets = ", ".join(f"{k} = ?" for k in columns)
        db_conn.execute(f"UPDATE song_classifications SET {sets} WHERE spotify_uri = ?",
                        (*columns.values(), uri))
    db_conn.commit()


class TestGetSongsNeedingSoundchartsTempo:
    def test_only_engaged_songs_without_audio_or_soundcharts(self, db_conn):
        _seed(db_conn, "uri:need")
        _seed(db_conn, "uri:clip", essentia_bpm=120.0)
        _seed(db_conn, "uri:cnn_only", tempocnn_bpm=60.0)
        _seed(db_conn, "uri:done", soundcharts_tempo=99.0)
        _seed(db_conn, "uri:unengaged", engagement=None)
        uris = [s["spotify_uri"] for s in get_songs_needing_soundcharts_tempo(db_conn, 10)]
        assert uris == ["uri:need"]

    def test_most_engaged_first_and_limited(self, db_conn):
        _seed(db_conn, "uri:low", engagement=0.1)
        _seed(db_conn, "uri:high", engagement=0.9)
        _seed(db_conn, "uri:mid", engagement=0.5)
        uris = [s["spotify_uri"] for s in get_songs_needing_soundcharts_tempo(db_conn, 2)]
        assert uris == ["uri:high", "uri:mid"]


class TestBackfillSoundchartsTempos:
    def _tempo(self, db_conn, uri):
        return db_conn.execute(
            "SELECT soundcharts_tempo FROM song_classifications WHERE spotify_uri = ?", (uri,)
        ).fetchone()[0]

    def test_stores_tempo_and_counts_calls(self, db_conn):
        _seed(db_conn, "uri:1")
        _seed(db_conn, "uri:2")
        fetch = MagicMock(side_effect=[
            SoundchartsResponse({"audio": {"tempo": 164.0}}, 845),
            SoundchartsResponse(None, 844),
        ])
        stats = backfill_soundcharts_tempos(db_conn, fetch, limit=10, delay_seconds=0)
        assert stats == {"calls": 2, "stored": 1, "no_tempo": 1, "quota_remaining": 844, "stopped": None}
        tempos = {self._tempo(db_conn, u) for u in ("uri:1", "uri:2")}
        assert tempos == {164.0, None}

    def test_never_writes_bpm_or_tempo(self, db_conn):
        _seed(db_conn, "uri:1")
        fetch = MagicMock(return_value=SoundchartsResponse({"audio": {"tempo": 164.0}}, 1))
        backfill_soundcharts_tempos(db_conn, fetch, limit=1, delay_seconds=0)
        row = db_conn.execute("SELECT bpm, tempo FROM song_classifications").fetchone()
        assert tuple(row) == (100, None)

    def test_respects_limit(self, db_conn):
        for i in range(5):
            _seed(db_conn, f"uri:{i}")
        fetch = MagicMock(return_value=SoundchartsResponse({"audio": {"tempo": 100.0}}, 1))
        stats = backfill_soundcharts_tempos(db_conn, fetch, limit=3, delay_seconds=0)
        assert fetch.call_count == 3
        assert stats["calls"] == 3

    def test_stops_on_refusal_and_keeps_what_was_stored(self, db_conn):
        _seed(db_conn, "uri:a", engagement=0.9)
        _seed(db_conn, "uri:b", engagement=0.5)
        _seed(db_conn, "uri:c", engagement=0.1)
        fetch = MagicMock(side_effect=[
            SoundchartsResponse({"audio": {"tempo": 90.0}}, 2),
            SoundchartsStop("Soundcharts returned 429"),
        ])
        stats = backfill_soundcharts_tempos(db_conn, fetch, limit=10, delay_seconds=0)
        assert stats["stopped"] == "Soundcharts returned 429"
        assert stats["calls"] == 1
        assert fetch.call_count == 2
        assert self._tempo(db_conn, "uri:a") == 90.0

    def test_nothing_to_fetch_makes_no_calls(self, db_conn):
        fetch = MagicMock()
        stats = backfill_soundcharts_tempos(db_conn, fetch, limit=10, delay_seconds=0)
        assert stats["calls"] == 0
        fetch.assert_not_called()
