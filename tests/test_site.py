"""Tests for the static showcase site: page copy, track enrichment, day assembly, rendering."""

import json
import sys
import urllib.error
from unittest.mock import patch

import pytest

import main
from db.queries import upsert_song, upsert_song_classification, upsert_whoop_recovery
from matching.generator import GenerationError
from web import site
from web.site import (
    DATA_PLACEHOLDER,
    OembedArtCache,
    build_site_days,
    compare_copy,
    enrich_track,
    format_duration,
    format_total_time,
    join_and,
    kinds_line,
    load_published,
    playlist_summary,
    reason_line,
    render,
)


def _driver(signal, effect):
    return {"signal": signal, "label": signal, "value": "1", "usual": "1", "z": 1.0, "effect": effect}


def _attuned(score, drivers=(), state="grounding", band=None, reason=None):
    return {"score": score, "band": band, "state": state, "drivers": list(drivers), "reason": reason}


# ─── join_and ────────────────────────────────────────────────────────────────


class TestJoinAnd:
    def test_empty_is_empty_string(self):
        assert join_and([]) == ""

    def test_one_item_alone(self):
        assert join_and(["a"]) == "a"

    def test_two_items_joined_by_and(self):
        assert join_and(["a", "b"]) == "a and b"

    def test_three_items_comma_then_and(self):
        assert join_and(["a", "b", "c"]) == "a, b and c"


# ─── compare_copy ────────────────────────────────────────────────────────────


class TestCompareCopy:
    def test_worse_when_heart_good_and_sleep_bad(self):
        a = _attuned(57, [_driver("sleep_efficiency_z", "down"), _driver("rem_sleep_z", "down"),
                          _driver("hrv_z", "up")])
        copy = compare_copy(a, {"recovery": 81})
        assert copy["title"] == "Why you'll likely feel worse than WHOOP says"
        assert copy["line"] == ("You had a higher HRV, which WHOOP leans on. But you also had "
                                "more broken sleep and less REM, which Attuned weighs more for how you'll feel.")

    def test_better_when_heart_bad_and_sleep_good(self):
        a = _attuned(70, [_driver("deep_sleep_z", "up"), _driver("rhr_z", "down"),
                          _driver("hrv_trend_z", "down")])
        copy = compare_copy(a, {"recovery": 40})
        assert copy["title"] == "Why you'll likely feel better than WHOOP says"
        assert copy["line"] == ("You had a higher resting heart rate and HRV drifting down this week, "
                                "which pulls WHOOP down. But you also had more deep sleep, "
                                "which Attuned weighs more for how you'll feel.")

    def test_agree_within_ten_points(self):
        a = _attuned(60, [_driver("total_sleep_z", "up")])
        copy = compare_copy(a, {"recovery": 51})
        assert copy["title"] == "WHOOP and Attuned roughly agree today"
        assert copy["line"] == "A longer night than usual."

    def test_ten_point_gap_is_not_agreement(self):
        copy = compare_copy(_attuned(50, [_driver("rem_sleep_z", "down")]), {"recovery": 60})
        assert copy["title"] == "Why you'll likely feel worse than WHOOP says"

    def test_worse_without_both_groups_falls_back_to_reason_line(self):
        a = _attuned(40, [_driver("rem_sleep_z", "down"), _driver("deep_sleep_z", "down")])
        copy = compare_copy(a, {"recovery": 70})
        assert copy["title"] == "Why you'll likely feel worse than WHOOP says"
        assert copy["line"] == "Less REM and less deep sleep than usual."

    def test_better_without_heart_bad_falls_back_to_reason_line(self):
        a = _attuned(80, [_driver("deep_sleep_z", "up"), _driver("rhr_z", "up")])
        copy = compare_copy(a, {"recovery": 50})
        assert copy["title"] == "Why you'll likely feel better than WHOOP says"
        assert copy["line"] == "More deep sleep and a lower resting heart rate than usual."

    def test_no_score_uses_reason(self):
        copy = compare_copy(_attuned(None, reason="No WHOOP data for 2026-10-21 yet."), {"recovery": None})
        assert copy == {"title": "No Attuned score today", "line": "No WHOOP data for 2026-10-21 yet.", "note": ""}

    def test_no_score_no_reason_is_empty_line(self):
        assert compare_copy(_attuned(None), {"recovery": 50})["line"] == ""

    def test_missing_whoop_recovery_counts_as_zero(self):
        copy = compare_copy(_attuned(30, [_driver("hrv_z", "up")]), {"recovery": None})
        assert copy["title"] == "Why you'll likely feel better than WHOOP says"

    def test_unknown_signal_ignored(self):
        a = _attuned(57, [_driver("mystery_z", "up"), _driver("rem_sleep_z", "down")])
        assert compare_copy(a, {"recovery": 60})["line"] == "Less REM than usual."

    def test_note_for_big_gap(self):
        assert compare_copy(_attuned(57), {"recovery": 81})["note"] == \
            "A 24-point gap: body readiness and mood can point different ways."

    def test_note_for_small_gap(self):
        assert compare_copy(_attuned(57), {"recovery": 62})["note"] == \
            "Within 5 points: today the two scores roughly agree."

    def test_note_at_twenty_points_is_a_gap(self):
        assert compare_copy(_attuned(40), {"recovery": 60})["note"].startswith("A 20-point gap")


class TestReasonLine:
    def test_no_drivers_is_a_usual_night(self):
        assert reason_line(_attuned(50), {"recovery": 50}) == "A night close to your usual."

    def test_lead_with_bad_when_at_or_below_whoop_and_add_despite(self):
        a = _attuned(50, [_driver("rem_sleep_z", "down"), _driver("hrv_z", "up")])
        assert reason_line(a, {"recovery": 50}) == "Less REM, despite a higher HRV."

    def test_lead_with_good_when_above_whoop(self):
        a = _attuned(70, [_driver("rem_sleep_z", "down"), _driver("hrv_z", "up")])
        assert reason_line(a, {"recovery": 50}) == "A higher HRV, despite less REM."

    def test_falls_back_to_other_side_when_lead_empty(self):
        a = _attuned(40, [_driver("hrv_z", "up")])
        assert reason_line(a, {"recovery": 50}) == "A higher HRV than usual."

    def test_no_score_uses_reason_or_default(self):
        assert reason_line(_attuned(None), {}) == "No feeling score for this day."


# ─── playlist summary ────────────────────────────────────────────────────────


def _track(moods=(), genres=(), duration_ms=None):
    return {"moods": list(moods), "genres": list(genres), "duration_ms": duration_ms}


class TestKindsLine:
    def test_top_two_moods_and_majority_genre(self):
        tracks = [_track(["calm", "romantic"], ["bollywood"]), _track(["calm"], ["bollywood"]),
                  _track(["romantic"], ["indie"])]
        assert kinds_line(tracks) == "calm, romantic Bollywood songs from your library"

    def test_no_majority_genre_names_top_two(self):
        tracks = [_track([], ["indie"]), _track([], ["rock"]), _track([], ["indie"]),
                  _track([], ["jazz"]), _track([], ["rock"])]
        assert kinds_line(tracks) == "indie and rock songs from your library"

    def test_only_first_genre_of_each_track_counts(self):
        tracks = [_track([], ["pop", "bollywood"]), _track([], ["pop", "bollywood"])]
        assert kinds_line(tracks) == "pop songs from your library"

    def test_ties_keep_first_seen_order(self):
        tracks = [_track(["warm"]), _track(["calm"]), _track(["dreamy"])]
        assert kinds_line(tracks) == "warm, calm songs from your library"

    def test_no_tags(self):
        assert kinds_line([_track(), _track()]) == "songs from your library"


class TestPlaylistSummary:
    TRACKS = [_track(["calm"], ["bollywood"])]

    def test_rest(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(20, state="rest", band="red"))
        assert s == {
            "lead": "You'll likely feel low today, so this playlist is built to help you settle.",
            "kinds": "Slower, softer, mostly calm Bollywood songs from your library.",
            "why": "Studies find slower music tends to bring heart rate down and calm the body.",
            "cites": [["Bernardi 2006", "https://doi.org/10.1136/hrt.2005.064600"],
                      ["Ooishi 2017", "https://doi.org/10.1371/journal.pone.0189075"]],
        }

    def test_energy(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(80, state="energy", band="green"))
        assert s["lead"] == "You'll likely feel good today, so this playlist is built to give you a lift."
        assert s["kinds"].startswith("Brighter, faster, mostly ")
        assert s["why"] == ("Studies find faster music tends to raise heart rate and breathing, "
                            "in step with the tempo.")
        assert s["cites"] == [["Bernardi 2006", "https://doi.org/10.1136/hrt.2005.064600"]]

    def test_grounding(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(50, state="grounding", band="yellow"))
        assert s["lead"] == "You'll likely feel middling today, so this playlist is built to keep you level."
        assert s["kinds"].startswith("Steady, familiar, mostly ")
        assert s["cites"] == [["Salimpoor 2011", "https://doi.org/10.1038/nn.2726"],
                              ["Hennessy 2025", "https://doi.org/10.1002/hbm.70181"]]

    def test_unknown_state_uses_grounding_plan(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(50, state=None, band="yellow"))
        assert s["why"].startswith("Studies find music you love")

    def test_band_falls_back_to_score(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(70, band=None))
        assert s["lead"].startswith("You'll likely feel good today")

    def test_no_score_says_okay(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(None))
        assert s["lead"].startswith("You'll likely feel okay today")


class TestDurations:
    def test_mmss_pads_seconds(self):
        assert format_duration(185_000) == "3:05"

    def test_mmss_rounds_to_nearest_second(self):
        assert format_duration(59_600) == "1:00"

    def test_missing_duration_is_blank(self):
        assert format_duration(None) == ""

    def test_total_under_an_hour(self):
        assert format_total_time([_track(duration_ms=600_000), _track(duration_ms=330_000)]) == "16 min"

    def test_total_over_an_hour(self):
        assert format_total_time([_track(duration_ms=3_900_000)]) == "1 hr 5 min"

    def test_total_ignores_missing(self):
        assert format_total_time([_track(), _track(duration_ms=60_000)]) == "1 min"


# ─── enrichment ──────────────────────────────────────────────────────────────


TRACK = {"title": "Saibo", "artist": "Sachin-Jigar", "spotify_url": "https://open.spotify.com/track/abc",
         "why": "Soft."}


class TestEnrichTrack:
    def test_adds_art_duration_and_tags(self, db_conn):
        upsert_song(db_conn, "spotify:track:abc", "Saibo", "Sachin-Jigar", sources=["test"], duration_ms=185_000)
        upsert_song_classification(db_conn, {
            "spotify_uri": "spotify:track:abc", "mood_tags": ["calm", "romantic", "warm", "sad"],
            "genre_tags": ["bollywood", "pop", "indie"], "classification_source": "test"})
        t = enrich_track(db_conn, TRACK, lambda url: f"art-for-{url}")
        assert t == {**TRACK, "art": "art-for-https://open.spotify.com/track/abc", "duration_ms": 185_000,
                     "duration": "3:05", "moods": ["calm", "romantic", "warm"], "genres": ["bollywood", "pop"]}

    def test_unknown_song_has_no_duration_or_tags(self, db_conn):
        t = enrich_track(db_conn, TRACK, lambda url: None)
        assert (t["art"], t["duration_ms"], t["duration"], t["moods"], t["genres"]) == (None, None, "", [], [])

    def test_does_not_mutate_input(self, db_conn):
        original = dict(TRACK)
        enrich_track(db_conn, TRACK, lambda url: "x")
        assert TRACK == original


class _FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestOembedArtCache:
    URL = "https://open.spotify.com/track/abc"

    def _cache(self, tmp_path, fetch):
        return OembedArtCache(tmp_path / "art.json", fetch=fetch, throttle_s=0)

    def test_fetches_thumbnail_and_saves(self, tmp_path):
        calls = []
        cache = self._cache(tmp_path, lambda u, timeout: calls.append(u) or _FakeResponse(b'{"thumbnail_url": "T"}'))
        assert cache(self.URL) == "T"
        cache.save()
        assert json.loads((tmp_path / "art.json").read_text()) == {self.URL: "T"}
        assert calls == ["https://open.spotify.com/oembed?url=https%3A%2F%2Fopen.spotify.com%2Ftrack%2Fabc"]

    def test_cached_url_is_not_refetched(self, tmp_path):
        (tmp_path / "art.json").write_text(json.dumps({self.URL: "T"}))
        cache = self._cache(tmp_path, lambda u, timeout: pytest.fail("should not fetch"))
        assert cache(self.URL) == "T"

    def test_http_error_is_cached_as_none(self, tmp_path):
        def fetch(u, timeout):
            raise urllib.error.HTTPError(u, 404, "Not Found", {}, None)
        cache = self._cache(tmp_path, fetch)
        assert cache(self.URL) is None
        cache.save()
        assert json.loads((tmp_path / "art.json").read_text()) == {self.URL: None}

    def test_network_failure_not_cached_and_stops_further_fetches(self, tmp_path):
        calls = []

        def fetch(u, timeout):
            calls.append(u)
            raise urllib.error.URLError("offline")
        cache = self._cache(tmp_path, fetch)
        assert cache(self.URL) is None
        assert cache("https://open.spotify.com/track/def") is None
        cache.save()
        assert len(calls) == 1
        assert json.loads((tmp_path / "art.json").read_text()) == {}

    def test_malformed_response_is_none(self, tmp_path):
        cache = self._cache(tmp_path, lambda u, timeout: _FakeResponse(b"not json"))
        assert cache(self.URL) is None

    def test_corrupt_cache_file_starts_empty(self, tmp_path):
        (tmp_path / "art.json").write_text("{broken")
        cache = self._cache(tmp_path, lambda u, timeout: _FakeResponse(b'{"thumbnail_url": "T"}'))
        assert cache(self.URL) == "T"


# ─── published playlists ─────────────────────────────────────────────────────


class TestLoadPublished:
    def test_missing_file_is_empty(self, tmp_path):
        assert load_published(tmp_path / "published.json") == {}

    def test_reads_mapping(self, tmp_path):
        path = tmp_path / "published.json"
        path.write_text(json.dumps({"2026-04-08": "https://open.spotify.com/playlist/p"}))
        assert load_published(path) == {"2026-04-08": "https://open.spotify.com/playlist/p"}


# ─── render ──────────────────────────────────────────────────────────────────


class TestRender:
    def test_injects_json(self):
        html = render(f"<script>{DATA_PLACEHOLDER}</script>", [{"date": "2026-10-21"}])
        assert html == '<script>[{"date": "2026-10-21"}]</script>'

    def test_escapes_closing_tags(self):
        html = render(f"<script>{DATA_PLACEHOLDER}</script>", [{"title": "</script><b>x"}])
        assert html.count("</script>") == 1
        assert json.loads(html[len("<script>"):-len("</script>")]) == [{"title": "</script><b>x"}]

    def test_keeps_non_ascii(self):
        assert "—" in render(DATA_PLACEHOLDER, [{"name": "Apr 8 — Settle In"}])

    def test_template_without_placeholder_raises(self):
        with pytest.raises(ValueError):
            render("<html></html>", [])

    def test_real_template_has_one_placeholder(self):
        assert site.TEMPLATE_PATH.read_text().count(DATA_PLACEHOLDER) == 1


# ─── build_site_days ─────────────────────────────────────────────────────────


PLAYLIST = {"name": "P", "spotify_url": None, "state": "rest", "tracks": [dict(TRACK)]}


def _page_day(conn, date, history=None):
    return {"date": date, "whoop": {"recovery": 60, "band": "yellow"},
            "attuned": _attuned(40, [_driver("rem_sleep_z", "down")], state="rest", band="yellow"),
            "metrics": {}, "playlist": None}


def _range_playlists(conn, start, end):
    from datetime import date, timedelta
    d, out = date.fromisoformat(start), []
    while d <= date.fromisoformat(end):
        failed = d.isoformat() == "2026-10-19"
        out.append({"date": d.isoformat(), "playlist": None if failed else PLAYLIST,
                    "error": "no data" if failed else None})
        d += timedelta(days=1)
    return out


@pytest.fixture
def recoveries(db_conn):
    """WHOOP recoveries on Oct 18–21 (Oct 17 missing), plus the two notable April days."""
    for i, d in enumerate(["2026-04-07", "2026-04-08", "2026-10-16", "2026-10-18",
                           "2026-10-19", "2026-10-20", "2026-10-21"]):
        upsert_whoop_recovery(db_conn, cycle_id=i + 1, date=d, recovery_score=60,
                              hrv_rmssd_milli=50, resting_heart_rate=55)
    db_conn.commit()
    return db_conn


@pytest.fixture
def stubbed(monkeypatch):
    calls = {"single": [], "range": [], "history": []}
    monkeypatch.setattr(site, "compute_composite_history",
                        lambda conn, before: calls["history"].append(before) or {})
    monkeypatch.setattr(site, "build_page_day", _page_day)
    monkeypatch.setattr(site, "build_day_playlists",
                        lambda c, s, e: calls["range"].append((s, e)) or _range_playlists(c, s, e))

    def single(conn, date):
        calls["single"].append(date)
        if date == "2026-04-07":
            raise GenerationError("too little data")
        return PLAYLIST
    monkeypatch.setattr(site, "build_day_playlist", single)
    return calls


def _build(conn, **kw):
    kw.setdefault("notable_dates", ("2026-04-07", "2026-04-08"))
    return build_site_days(conn, "2026-10-21", 4, art_lookup=lambda u: None, **kw)


class TestBuildSiteDays:
    def test_includes_recovery_days_in_window_plus_notable_sorted(self, recoveries, stubbed):
        dates = [d["date"] for d in _build(recoveries)]
        assert dates == ["2026-04-07", "2026-04-08", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"]

    def test_marks_only_notable_days(self, recoveries, stubbed):
        notable = {d["date"]: d.get("notable", False) for d in _build(recoveries)}
        assert notable == {"2026-04-07": True, "2026-04-08": True, "2026-10-18": False,
                           "2026-10-19": False, "2026-10-20": False, "2026-10-21": False}

    def test_notable_day_inside_window_is_marked_not_duplicated(self, recoveries, stubbed):
        days = _build(recoveries, notable_dates=("2026-10-20",))
        assert [d["date"] for d in days].count("2026-10-20") == 1
        assert next(d for d in days if d["date"] == "2026-10-20")["notable"] is True

    def test_range_replayed_once_and_notable_days_singly(self, recoveries, stubbed):
        _build(recoveries)
        assert stubbed["range"] == [("2026-10-18", "2026-10-21")]
        assert stubbed["single"] == ["2026-04-07", "2026-04-08"]

    def test_history_computed_once(self, recoveries, stubbed):
        _build(recoveries)
        assert stubbed["history"] == ["2026-10-22"]

    def test_failed_playlist_is_none(self, recoveries, stubbed):
        days = {d["date"]: d for d in _build(recoveries)}
        assert days["2026-10-19"]["playlist"] is None
        assert days["2026-04-07"]["playlist"] is None

    def test_attaches_copy_and_enriched_playlist(self, recoveries, stubbed):
        day = next(d for d in _build(recoveries) if d["date"] == "2026-10-21")
        assert day["attuned"]["compare"]["title"] == "Why you'll likely feel worse than WHOOP says"
        pl = day["playlist"]
        assert pl["summary"]["lead"].endswith("built to help you settle.")
        assert pl["total_time"] == "0 min"
        assert pl["tracks"][0]["duration"] == "" and pl["tracks"][0]["art"] is None

    def test_does_not_mutate_shared_playlist(self, recoveries, stubbed):
        _build(recoveries)
        assert PLAYLIST["tracks"][0] == TRACK and "summary" not in PLAYLIST

    def test_published_url_used_when_mapped(self, recoveries, stubbed):
        url = "https://open.spotify.com/playlist/p"
        days = {d["date"]: d for d in _build(recoveries, published={"2026-10-20": url})}
        assert days["2026-10-20"]["playlist"]["spotify_url"] == url
        assert days["2026-10-21"]["playlist"]["spotify_url"] is None

    def test_no_recoveries_in_window_still_builds_notable(self, db_conn, stubbed):
        days = _build(db_conn)
        assert [d["date"] for d in days] == ["2026-04-07", "2026-04-08"]
        assert stubbed["range"] == []

    def test_rejects_non_positive_days(self, db_conn):
        with pytest.raises(ValueError):
            build_site_days(db_conn, "2026-10-21", 0, art_lookup=lambda u: None)


class TestBuildSiteDaysIntegration:
    """Real scoring + playlist code on a sparse DB: too little data to score or generate."""

    def test_sparse_db_yields_unscored_days_without_playlists(self, recoveries):
        days = build_site_days(recoveries, "2026-10-21", 4, notable_dates=("2026-04-08",),
                               art_lookup=lambda u: None)
        assert [d["date"] for d in days] == ["2026-04-08", "2026-10-18", "2026-10-19",
                                             "2026-10-20", "2026-10-21"]
        assert all(d["attuned"]["score"] is None for d in days)
        assert all(d["attuned"]["compare"]["title"] == "No Attuned score today" for d in days)
        assert all(d["playlist"] is None for d in days)

    def test_renders_into_real_template(self, recoveries):
        days = build_site_days(recoveries, "2026-10-21", 2, notable_dates=(), art_lookup=lambda u: None)
        html = render(site.TEMPLATE_PATH.read_text(), days)
        assert DATA_PLACEHOLDER not in html and "2026-10-21" in html


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestBuildSiteCommand:
    def _run(self, monkeypatch, db_path, *args):
        monkeypatch.setattr(sys, "argv", ["main.py", "build-site", *args])
        main._cmd_build_site(db_path)

    def test_writes_index_html(self, monkeypatch, capsys, db_path, tmp_path):
        out = tmp_path / "dist"
        with patch("web.site.build_site_days", return_value=[{"date": "2026-10-21", "playlist": None}]) as build:
            self._run(monkeypatch, db_path, "--days", "7", "--end", "2026-10-21", "--out", str(out))
        assert build.call_args.args[1:3] == ("2026-10-21", 7)
        html = (out / "index.html").read_text()
        assert '"date": "2026-10-21"' in html and DATA_PLACEHOLDER not in html

    def test_defaults_to_30_days(self, monkeypatch, capsys, db_path, tmp_path):
        with patch("web.site.build_site_days", return_value=[]) as build:
            self._run(monkeypatch, db_path, "--out", str(tmp_path))
        assert build.call_args.args[2] == 30

    def test_rejects_bad_days(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--days", "abc")
        assert "--days" in capsys.readouterr().out

    def test_rejects_zero_days(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--days", "0")

    def test_rejects_bad_end(self, monkeypatch, capsys, db_path):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--end", "21/10/2026")
        assert "YYYY-MM-DD" in capsys.readouterr().out

    def test_listed_in_usage(self):
        assert "build-site" in main.COMMANDS
