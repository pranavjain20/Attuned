"""Tests for the static showcase site: page copy, track enrichment, day assembly, rendering."""

import json
import re
import sys
import urllib.error
from unittest.mock import patch

import pytest

import main
from db.queries import upsert_song, upsert_song_classification, upsert_whoop_recovery
from web import site
from web.site import (
    SHORTCUT_DAYS,
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
    open_link,
    playlist_summary,
    reason_line,
    render,
    save_published,
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

    @pytest.mark.parametrize("score", [5, 30, 95])
    def test_missing_whoop_recovery_is_neutral(self, score):
        """No WHOOP number is not a WHOOP 0: no better/worse claim and no gap note."""
        copy = compare_copy(_attuned(score, [_driver("hrv_z", "up")]), {"recovery": None})
        assert copy == {"title": "No WHOOP recovery to compare today",
                        "line": "A higher HRV than usual.", "note": ""}

    def test_unknown_signal_ignored(self):
        a = _attuned(57, [_driver("mystery_z", "up"), _driver("rem_sleep_z", "down")])
        assert compare_copy(a, {"recovery": 60})["line"] == "Less REM than usual."

    def test_note_for_big_gap(self):
        assert compare_copy(_attuned(57), {"recovery": 81})["note"] == \
            "A 24-point gap: body readiness and mood can point different ways."

    @pytest.mark.parametrize("whoop, note", [(57, "Same score as WHOOP today."),
                                             (58, "Within 1 point: today the two scores roughly agree.")])
    def test_note_says_point_for_one(self, whoop, note):
        assert compare_copy(_attuned(57), {"recovery": whoop})["note"] == note

    def test_note_for_small_gap(self):
        assert compare_copy(_attuned(57), {"recovery": 62})["note"] == \
            "Within 5 points: today the two scores roughly agree."

    def test_note_at_twenty_points_is_a_gap(self):
        assert compare_copy(_attuned(40), {"recovery": 60})["note"].startswith("A 20-point gap")

    @pytest.mark.parametrize("whoop, note", [(39, "An 11-point gap."), (32, "An 18-point gap."),
                                             (36, "A 14-point gap."),
                                             (100, "A 50-point gap: body readiness and mood can point different ways.")])
    def test_gap_note_article_follows_the_spoken_number(self, whoop, note):
        assert compare_copy(_attuned(50), {"recovery": whoop})["note"] == note

    @pytest.mark.parametrize("size, article", [(8, "An"), (11, "An"), (18, "An"), (80, "An"), (88, "An"),
                                               (10, "A"), (12, "A"), (19, "A"), (28, "A"), (100, "A")])
    def test_gap_article(self, size, article):
        assert site._gap_article(size) == article

    def test_medium_gap_title_and_note_agree(self):
        """70 vs 55 used to say "better than WHOOP" above and "roughly agree" below."""
        copy = compare_copy(_attuned(70), {"recovery": 55})
        assert copy["title"] == "Why you'll likely feel better than WHOOP says"
        assert copy["note"] == "A 15-point gap."

    @pytest.mark.parametrize("attuned, whoop", [(50, 60), (60, 50), (40, 59), (59, 40), (55, 64), (64, 55),
                                                (0, 100), (100, 0), (50, 50)])
    def test_title_and_note_never_contradict(self, attuned, whoop):
        copy = compare_copy(_attuned(attuned), {"recovery": whoop})
        agree_title = copy["title"] == "WHOOP and Attuned roughly agree today"
        agree_note = "roughly agree" in copy["note"] or copy["note"] == "Same score as WHOOP today."
        assert agree_title == agree_note
        assert agree_title == (abs(attuned - whoop) < site.AGREE_WITHIN_POINTS)


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

    @pytest.mark.parametrize("first, line", [
        ("down", "Less REM, despite a higher HRV."),   # drivers come explaining-side first
        ("up", "A higher HRV, despite less REM."),
    ])
    def test_without_whoop_leads_with_the_first_driver(self, first, line):
        drivers = [_driver("rem_sleep_z", "down"), _driver("hrv_z", "up")]
        a = _attuned(50, drivers if first == "down" else drivers[::-1])
        assert reason_line(a, {"recovery": None}) == line


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
        # Hennessy 2025: personally nostalgic songs beat merely familiar ones (docs/RESEARCH.md).
        assert s["why"] == ("Studies find music you love triggers the brain's reward system, "
                            "so personally meaningful songs land harder emotionally.")
        assert s["cites"] == [["Salimpoor 2011", "https://doi.org/10.1038/nn.2726"],
                              ["Hennessy 2025", "https://doi.org/10.1002/hbm.70181"]]

    def test_unknown_state_uses_grounding_plan(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(50, state=None, band="yellow"))
        assert s["why"].startswith("Studies find music you love")

    def test_band_falls_back_to_score(self):
        s = playlist_summary({"tracks": self.TRACKS}, _attuned(70, band=None))
        assert s["lead"].startswith("You'll likely feel good today")

    def test_no_score_says_there_is_no_score_yet(self):
        s = playlist_summary({"tracks": self.TRACKS, "state": "grounding"}, _attuned(None, state=None))
        assert s["lead"] == "There's no Attuned score for today yet, so this playlist is built to keep you level."
        assert "feel" not in s["lead"]

    def test_no_score_uses_the_playlists_own_state(self):
        s = playlist_summary({"tracks": self.TRACKS, "state": "rest"}, _attuned(None, state=None))
        assert s["lead"].endswith("built to help you settle.")


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

    def test_not_found_is_cached_as_none(self, tmp_path):
        def fetch(u, timeout):
            raise urllib.error.HTTPError(u, 404, "Not Found", {}, None)
        cache = self._cache(tmp_path, fetch)
        assert cache(self.URL) is None
        cache.save()
        assert json.loads((tmp_path / "art.json").read_text()) == {self.URL: None}

    @pytest.mark.parametrize("code", [500, 502, 503])
    def test_server_error_is_not_cached(self, tmp_path, code):
        """A passing outage must not leave the track without art forever."""
        calls = []

        def fetch(u, timeout):
            calls.append(u)
            raise urllib.error.HTTPError(u, code, "Server Error", {}, None)
        cache = self._cache(tmp_path, fetch)
        assert cache(self.URL) is None
        assert cache("https://open.spotify.com/track/def") is None
        cache.save()
        assert json.loads((tmp_path / "art.json").read_text()) == {}
        assert len(calls) == 2  # one server error doesn't stop the others

    def test_rate_limit_not_cached_and_stops_further_fetches(self, tmp_path):
        """Spotify asked us to slow down: stop asking for the rest of this build."""
        calls = []

        def fetch(u, timeout):
            calls.append(u)
            raise urllib.error.HTTPError(u, 429, "Too Many Requests", {}, None)
        cache = self._cache(tmp_path, fetch)
        assert cache(self.URL) is None
        assert cache("https://open.spotify.com/track/def") is None
        cache.save()
        assert json.loads((tmp_path / "art.json").read_text()) == {}
        assert len(calls) == 1

    def test_retried_after_a_server_error(self, tmp_path):
        replies = iter([urllib.error.HTTPError(self.URL, 503, "x", {}, None), _FakeResponse(b'{"thumbnail_url": "T"}')])

        def fetch(u, timeout):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply
        cache = self._cache(tmp_path, fetch)
        assert cache(self.URL) is None
        assert cache(self.URL) == "T"

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
        record = {"url": "https://open.spotify.com/playlist/p", "track_uris": ["spotify:track:a"]}
        path.write_text(json.dumps({"2026-04-08": record}))
        assert load_published(path) == {"2026-04-08": record}

    def test_reads_name_and_description(self, tmp_path):
        path = tmp_path / "published.json"
        record = {"url": "https://open.spotify.com/playlist/p", "track_uris": [], "name": "N", "description": "D"}
        path.write_text(json.dumps({"2026-04-08": record}))
        assert load_published(path) == {"2026-04-08": record}

    @pytest.mark.parametrize("bad", [
        [],
        {"2026-04-08": "https://open.spotify.com/playlist/p"},
        {"2026-04-08": {"url": "u"}},
        {"2026-04-08": {"url": 1, "track_uris": []}},
        {"2026-04-08": {"url": "u", "track_uris": "spotify:track:a"}},
        {"2026-04-08": {"url": "u", "track_uris": [1]}},
        {"2026-04-08": {"url": "u", "track_uris": [], "name": 1}},
        {"2026-04-08": {"url": "u", "track_uris": [], "description": None}},
    ])
    def test_rejects_malformed(self, tmp_path, bad):
        path = tmp_path / "published.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            load_published(path)

    def test_save_round_trips_and_leaves_no_temp_file(self, tmp_path):
        path = tmp_path / "web" / "published.json"
        published = {"2026-10-21": {"url": "https://open.spotify.com/playlist/p", "track_uris": ["spotify:track:a"]}}
        save_published(published, path)
        assert load_published(path) == published
        assert [f.name for f in path.parent.iterdir()] == ["published.json"]


class TestOpenLink:
    TRACKS = [{"spotify_url": "https://open.spotify.com/track/first"},
              {"spotify_url": "https://open.spotify.com/track/second"}]
    URL = "https://open.spotify.com/playlist/p"

    def _record(self, uris):
        return {"url": self.URL, "track_uris": uris}

    def test_published_with_the_same_tracks_opens_the_playlist(self):
        record = self._record(["spotify:track:first", "spotify:track:second"])
        assert open_link(record, self.TRACKS) == {"label": "Open in Spotify", "url": self.URL}

    @pytest.mark.parametrize("uris", [
        ["spotify:track:second", "spotify:track:first"],  # same songs, other order
        ["spotify:track:first"],                          # fewer
        [],                                               # created, never filled
        ["spotify:track:first", "spotify:track:second", "spotify:track:third"],
    ])
    def test_published_with_other_tracks_plays_the_first_song(self, uris):
        assert open_link(self._record(uris), self.TRACKS) == {
            "label": "Play on Spotify", "url": "https://open.spotify.com/track/first"}

    def test_unpublished_plays_the_first_song(self):
        assert open_link(None, self.TRACKS) == {
            "label": "Play on Spotify", "url": "https://open.spotify.com/track/first"}

    def test_no_tracks_no_link(self):
        assert open_link(None, []) is None
        assert open_link(self._record([]), []) is None


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


SPARE = {"title": "Spare", "artist": "S", "spotify_url": "https://open.spotify.com/track/spare", "why": "Spare."}
PLAYLIST = {"name": "P", "state": "rest", "tracks": [dict(TRACK)], "spares": [dict(SPARE)]}


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
    """WHOOP recoveries on Oct 18–21 (Oct 17 missing), plus older days outside the window."""
    for i, d in enumerate(["2026-04-07", "2026-04-08", "2026-10-16", "2026-10-18",
                           "2026-10-19", "2026-10-20", "2026-10-21"]):
        upsert_whoop_recovery(db_conn, cycle_id=i + 1, date=d, recovery_score=60,
                              hrv_rmssd_milli=50, resting_heart_rate=55)
    db_conn.commit()
    return db_conn


@pytest.fixture
def stubbed(monkeypatch):
    calls = {"range": [], "history": [], "histories": []}
    shared = {"history": "shared"}

    def history(conn, before):
        calls["history"].append(before)
        return shared
    monkeypatch.setattr(site, "compute_composite_history", history)

    def page_day(conn, date, history=None):
        calls["histories"].append(("page", history))
        return _page_day(conn, date, history)
    monkeypatch.setattr(site, "build_page_day", page_day)

    def range_playlists(conn, start, end, history=None):
        calls["range"].append((start, end))
        calls["histories"].append(("range", history))
        return _range_playlists(conn, start, end)
    monkeypatch.setattr(site, "build_day_playlists", range_playlists)
    calls["shared"] = shared
    return calls


def _build(conn, **kw):
    return build_site_days(conn, "2026-10-21", 4, art_lookup=lambda u: None, **kw)


class TestBuildSiteDays:
    def test_includes_only_recovery_days_in_window_sorted(self, recoveries, stubbed):
        dates = [d["date"] for d in _build(recoveries)]
        assert dates == ["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"]

    def test_marks_the_most_recent_days_as_shortcuts(self, recoveries, stubbed):
        shortcut = {d["date"]: d["shortcut"] for d in _build(recoveries)}
        assert shortcut == {"2026-10-18": False, "2026-10-19": True, "2026-10-20": True, "2026-10-21": True}
        assert SHORTCUT_DAYS == 3
        assert all("notable" not in d for d in _build(recoveries))

    def test_fewer_days_than_shortcuts_marks_them_all(self, recoveries, stubbed):
        days = build_site_days(recoveries, "2026-10-21", 1, art_lookup=lambda u: None)
        assert [(d["date"], d["shortcut"]) for d in days] == [("2026-10-21", True)]

    def test_range_replayed_once(self, recoveries, stubbed):
        _build(recoveries)
        assert stubbed["range"] == [("2026-10-18", "2026-10-21")]

    def test_history_computed_once(self, recoveries, stubbed):
        _build(recoveries)
        assert stubbed["history"] == ["2026-10-22"]

    def test_one_history_shared_by_scores_and_playlists(self, recoveries, stubbed):
        _build(recoveries)
        kinds = {kind for kind, _ in stubbed["histories"]}
        assert kinds == {"page", "range"}
        assert all(h is stubbed["shared"] for _, h in stubbed["histories"])

    def test_failed_playlist_is_none(self, recoveries, stubbed):
        days = {d["date"]: d for d in _build(recoveries)}
        assert days["2026-10-19"]["playlist"] is None

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

    def test_page_playlist_carries_no_spotify_url_or_spares(self, recoveries, stubbed):
        """The button is `open`; spares are for publishing only."""
        pl = next(d for d in _build(recoveries) if d["date"] == "2026-10-21")["playlist"]
        assert "spotify_url" not in pl and "spares" not in pl

    def test_open_link_is_playlist_when_published_else_first_song(self, recoveries, stubbed):
        url = "https://open.spotify.com/playlist/p"
        published = {"2026-10-20": {"url": url, "track_uris": ["spotify:track:abc"]}}
        days = {d["date"]: d for d in _build(recoveries, published=published)}
        assert days["2026-10-20"]["playlist"]["open"] == {"label": "Open in Spotify", "url": url}
        assert days["2026-10-21"]["playlist"]["open"] == {
            "label": "Play on Spotify", "url": TRACK["spotify_url"]}

    def test_published_with_a_spare_shows_the_published_songs(self, recoveries, stubbed):
        """Publishing swapped an unavailable song for a spare: the page shows what Spotify has."""
        url = "https://open.spotify.com/playlist/p"
        published = {"2026-10-20": {"url": url, "track_uris": ["spotify:track:spare"]}}
        pl = {d["date"]: d for d in _build(recoveries, published=published)}["2026-10-20"]["playlist"]
        assert [t["title"] for t in pl["tracks"]] == ["Spare"]
        assert pl["tracks"][0]["why"] == "Spare."
        assert pl["open"] == {"label": "Open in Spotify", "url": url}

    def test_published_songs_shown_in_the_published_order(self, recoveries, stubbed):
        published = {"2026-10-20": {"url": "https://open.spotify.com/playlist/p",
                                    "track_uris": ["spotify:track:spare", "spotify:track:abc"]}}
        pl = {d["date"]: d for d in _build(recoveries, published=published)}["2026-10-20"]["playlist"]
        assert [t["title"] for t in pl["tracks"]] == ["Spare", "Saibo"]

    @pytest.mark.parametrize("uris", [["spotify:track:gone"], ["spotify:track:abc", "spotify:track:gone"], []])
    def test_stale_publish_falls_back_to_the_replay_and_first_song(self, recoveries, stubbed, uris):
        """The replay no longer has every published song: show the replay, never link a playlist
        that doesn't match the songs on the page."""
        published = {"2026-10-20": {"url": "https://open.spotify.com/playlist/p", "track_uris": uris}}
        pl = {d["date"]: d for d in _build(recoveries, published=published)}["2026-10-20"]["playlist"]
        assert [t["title"] for t in pl["tracks"]] == ["Saibo"]
        assert pl["open"] == {"label": "Play on Spotify", "url": TRACK["spotify_url"]}

    def test_no_recoveries_in_window_builds_nothing(self, db_conn, stubbed):
        assert _build(db_conn) == []
        assert stubbed["range"] == []

    def test_rejects_non_positive_days(self, db_conn):
        with pytest.raises(ValueError):
            build_site_days(db_conn, "2026-10-21", 0, art_lookup=lambda u: None)


class TestBuildSiteDaysIntegration:
    """Real scoring + playlist code on a sparse DB: too little data to score or generate."""

    def test_sparse_db_yields_unscored_days_without_playlists(self, recoveries):
        days = build_site_days(recoveries, "2026-10-21", 4, art_lookup=lambda u: None)
        assert [d["date"] for d in days] == ["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"]
        assert all(d["attuned"]["score"] is None for d in days)
        assert all(d["attuned"]["compare"]["title"] == "No Attuned score today" for d in days)
        assert all(d["playlist"] is None for d in days)

    def test_template_drives_the_button_from_open_and_has_no_unsaved_note(self):
        template = site.TEMPLATE_PATH.read_text()
        assert "pl.open.url" in template and "pl.open.label" in template
        assert "Not saved to Spotify yet" not in template and "btn-note" not in template

    def test_template_states_carry_only_a_colour(self):
        """No unused per-state copy (and no unchecked "Mid-tempo music" claim) in the page."""
        template = site.TEMPLATE_PATH.read_text()
        assert "meaning:" not in template and "Mid-tempo" not in template and "icon:" not in template
        assert "notable" not in template.lower()

    def test_renders_into_real_template(self, recoveries):
        days = build_site_days(recoveries, "2026-10-21", 2, art_lookup=lambda u: None)
        html = render(site.TEMPLATE_PATH.read_text(), days)
        assert DATA_PLACEHOLDER not in html and "2026-10-21" in html


class TestBuildSiteDaysRealData:
    """Real scoring, replay and enrichment on a seeded DB: 95 days of WHOOP data, 40 songs."""

    END = "2026-06-05"
    WINDOW = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    TITLES = {"WHOOP and Attuned roughly agree today", "Why you'll likely feel worse than WHOOP says",
              "Why you'll likely feel better than WHOOP says"}

    @pytest.fixture(scope="class")
    def seeded(self, tmp_path_factory):
        from db.schema import get_connection
        from tests.test_day_playlist import _add_song
        from tests.test_feeling_score import HOUR, _insert_day, _seed_history

        conn = get_connection(tmp_path_factory.mktemp("site") / "site.db")
        _seed_history(conn, self.WINDOW[0], 90)
        nights = [(4.0, 78, 40, 70), (7.2, 88, 48, 55), (9.0, 95, 56, 30), (6.5, 85, 46, 50), (8.1, 92, 52, 50)]
        for i, (total_h, eff, hrv, recovery) in enumerate(nights):
            _insert_day(conn, self.WINDOW[i], 1 + i, total_ms=total_h * HOUR, eff=eff, hrv=hrv, rhr=56,
                        recovery=recovery)
        for i in range(40):
            uri = _add_song(conn, i, [f"2026-03-{k + 1:02d}T12:00:00Z" for k in range(1 + i % 5)], para=i / 40)
            conn.execute("UPDATE songs SET duration_ms = ? WHERE spotify_uri = ?", (180_000 + i * 1000, uri))
        conn.commit()
        days = build_site_days(conn, self.END, 5, art_lookup=lambda url: f"art:{url}")
        yield conn, days
        conn.close()

    def test_every_window_day_is_scored_with_consistent_bands(self, seeded):
        from intelligence.feeling_score import band
        _, days = seeded
        assert [d["date"] for d in days] == self.WINDOW
        for day in days:
            score, recovery = day["attuned"]["score"], day["whoop"]["recovery"]
            assert isinstance(score, int) and 0 <= score <= 100
            assert day["attuned"]["band"] == band(score)
            assert day["whoop"]["band"] == band(recovery)

    def test_compare_title_and_note_agree_with_the_gap(self, seeded):
        _, days = seeded
        for day in days:
            copy = day["attuned"]["compare"]
            gap = day["attuned"]["score"] - day["whoop"]["recovery"]
            assert copy["title"] in self.TITLES
            if abs(gap) < site.AGREE_WITHIN_POINTS:
                assert "roughly agree" in copy["title"] and "roughly agree" in copy["note"]
            else:
                assert ("worse" if gap < 0 else "better") in copy["title"]
                assert copy["note"].startswith(f"{site._gap_article(abs(gap))} {abs(gap)}-point gap")
            assert copy["line"]

    def test_seed_covers_agree_medium_and_big_gaps(self, seeded):
        _, days = seeded
        gaps = {abs(d["attuned"]["score"] - d["whoop"]["recovery"]) for d in days}
        assert any(g < 10 for g in gaps) and any(10 <= g < 20 for g in gaps) and any(g >= 20 for g in gaps)

    def test_playlists_have_enriched_tracks(self, seeded):
        _, days = seeded
        for day in days:
            pl = day["playlist"]
            assert pl is not None and 15 <= len(pl["tracks"]) <= 20
            assert set(pl) == {"name", "state", "open", "tracks", "total_time", "summary"}
            assert pl["name"].startswith(("Jun 1 ", "Jun 2 ", "Jun 3 ", "Jun 4 ", "Jun 5 "))
            for track in pl["tracks"]:
                assert track["art"] == f"art:{track['spotify_url']}"
                assert re.fullmatch(r"3:\d\d", track["duration"])
                assert track["moods"] == ["romantic", "nostalgic"] and track["genres"] == ["bollywood"]
                assert track["why"]
            assert pl["total_time"].endswith("min")
            assert pl["summary"]["lead"].startswith("You'll likely feel ")

    def test_unpublished_days_play_the_first_song(self, seeded):
        _, days = seeded
        for day in days:
            assert day["playlist"]["open"] == {"label": "Play on Spotify",
                                               "url": day["playlist"]["tracks"][0]["spotify_url"]}

    def test_published_day_opens_its_playlist(self, seeded):
        conn, days = seeded
        tracks = days[3]["playlist"]["tracks"]
        record = {"url": "https://open.spotify.com/playlist/p", "track_uris": [_uri(t) for t in tracks]}
        rebuilt = build_site_days(conn, self.END, 5, art_lookup=lambda url: None, published={self.WINDOW[3]: record})
        assert rebuilt[3]["playlist"]["open"] == {"label": "Open in Spotify", "url": record["url"]}
        assert [t["spotify_url"] for t in rebuilt[3]["playlist"]["tracks"]] == [t["spotify_url"] for t in tracks]
        assert rebuilt[4]["playlist"]["open"]["label"] == "Play on Spotify"

    def test_published_with_a_spare_shows_it_and_opens_the_playlist(self, seeded):
        conn, days = seeded
        replay = site.replay_playlists(conn, self.WINDOW)[self.WINDOW[4]]
        assert replay["spares"], "the replay keeps its buffer for publishing"
        uris = [_uri(t) for t in replay["tracks"][1:]] + [_uri(replay["spares"][0])]
        record = {"url": "https://open.spotify.com/playlist/q", "track_uris": uris}
        rebuilt = build_site_days(conn, self.END, 5, art_lookup=lambda url: None, published={self.WINDOW[4]: record})
        pl = rebuilt[4]["playlist"]
        assert [_uri(t) for t in pl["tracks"]] == uris
        assert pl["tracks"][-1]["why"] == replay["spares"][0]["why"]
        assert pl["open"]["url"] == record["url"]

    def test_stale_published_record_plays_the_first_song(self, seeded):
        conn, days = seeded
        record = {"url": "https://open.spotify.com/playlist/p", "track_uris": ["spotify:track:not-in-the-replay"]}
        rebuilt = build_site_days(conn, self.END, 5, art_lookup=lambda url: None, published={self.WINDOW[2]: record})
        assert rebuilt[2]["playlist"]["open"]["label"] == "Play on Spotify"
        assert rebuilt[2]["playlist"]["tracks"] == [{**t, "art": None} for t in days[2]["playlist"]["tracks"]]

    def test_shortcuts_on_the_last_three_days(self, seeded):
        _, days = seeded
        assert [d["shortcut"] for d in days] == [False, False, True, True, True]

    def test_renders_into_the_real_template(self, seeded):
        _, days = seeded
        html = render(site.TEMPLATE_PATH.read_text(), days)
        assert DATA_PLACEHOLDER not in html and self.END in html


def _uri(track):
    return "spotify:track:" + track["spotify_url"].rsplit("/", 1)[-1]


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
