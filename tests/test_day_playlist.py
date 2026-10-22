"""Tests for replaying a past day's playlist: rewinding the library, rotation, page JSON."""

import json
from unittest.mock import patch

import pytest

from config import BASELINE_CALM_ANCHOR
from db.queries import insert_generated_playlist, upsert_song, upsert_song_classification
from matching.day_playlist import build_day_playlist, build_day_playlists
from matching.generator import GenerationError, select_day_songs
from matching.query_engine import (
    FRESHNESS_NUDGE,
    is_current_banger,
    merge_prior_days_ago,
    play_dates_before,
    rewind_songs_to_date,
    select_songs,
)

DAY = "2026-04-08"


def _add_song(conn, i, plays_at, para=0.8, current_play_count=99, last_played="2026-10-20",
              mood_tags=("romantic", "nostalgic")):
    uri = f"spotify:track:t{i:03d}"
    upsert_song(conn, uri, f"Song {i}", f"Artist {i}", sources=["test"], last_played=last_played)
    conn.execute("UPDATE songs SET play_count = ? WHERE spotify_uri = ?", (current_play_count, uri))
    upsert_song_classification(conn, {
        "spotify_uri": uri, "parasympathetic": para, "sympathetic": 0.1, "grounding": 0.3,
        "confidence": 0.8, "bpm": 80.0, "energy": 0.3, "valence": 0.4, "acousticness": 0.5,
        "genre_tags": ["bollywood"], "mood_tags": list(mood_tags),
        "classification_source": "test",
    })
    for ts in plays_at:
        conn.execute(
            "INSERT INTO listening_history (spotify_uri, played_at, ms_played, platform) "
            "VALUES (?, ?, 60000, 'ios')", (uri, ts))
    return uri


@pytest.fixture
def library(db_conn):
    """20 songs heard before DAY, plus one discovered after it."""
    uris = [_add_song(db_conn, i, [f"2026-03-{(i % 28) + 1:02d}T12:00:00Z", "2026-10-01T12:00:00Z"])
            for i in range(20)]
    later = _add_song(db_conn, 99, ["2026-06-01T12:00:00Z"], para=0.95)
    db_conn.commit()
    return db_conn, uris, later


class TestRewindSongsToDate:
    def test_restates_play_count_and_last_played(self, library):
        conn, uris, _ = library
        from db.queries import get_all_classified_songs
        rewound = {s["spotify_uri"]: s for s in rewind_songs_to_date(conn, get_all_classified_songs(conn), DAY)}
        assert rewound[uris[0]]["play_count"] == 1          # only the March play counts
        assert rewound[uris[0]]["last_played"].startswith("2026-03")
        assert rewound[uris[0]]["first_played"].startswith("2026-03")

    def test_drops_songs_first_heard_after_date(self, library):
        conn, _, later = library
        from db.queries import get_all_classified_songs
        rewound = rewind_songs_to_date(conn, get_all_classified_songs(conn), DAY)
        assert later not in {s["spotify_uri"] for s in rewound}

    def test_plays_on_the_day_itself_excluded(self, db_conn):
        uri = _add_song(db_conn, 1, [f"{DAY}T07:00:00Z"])
        from db.queries import get_all_classified_songs
        assert rewind_songs_to_date(db_conn, get_all_classified_songs(db_conn), DAY) == []
        assert uri

    def test_short_plays_ignored(self, db_conn):
        uri = _add_song(db_conn, 1, [])
        db_conn.execute("INSERT INTO listening_history (spotify_uri, played_at, ms_played, platform) "
                        "VALUES (?, '2026-03-01T10:00:00Z', 5000, 'ios')", (uri,))
        db_conn.execute("INSERT INTO listening_history (spotify_uri, played_at, ms_played, platform) "
                        "VALUES (?, '2026-10-01T10:00:00Z', 60000, 'ios')", (uri,))
        from db.queries import get_all_classified_songs
        assert rewind_songs_to_date(db_conn, get_all_classified_songs(db_conn), DAY) == []

    def test_does_not_mutate_input(self, library):
        conn, _, _ = library
        from db.queries import get_all_classified_songs
        songs = get_all_classified_songs(conn)
        before = [dict(s) for s in songs]
        rewind_songs_to_date(conn, songs, DAY)
        assert songs == before


class TestPlayDatesBefore:
    def test_distinct_meaningful_days_before_date(self, db_conn):
        uri = _add_song(db_conn, 1, ["2026-03-01T08:00:00Z", "2026-03-01T20:00:00Z",
                                     "2026-03-05T08:00:00Z", f"{DAY}T01:00:00Z"])
        db_conn.execute("INSERT INTO listening_history (spotify_uri, played_at, ms_played, platform) "
                        "VALUES (?, '2026-03-09T10:00:00Z', 5000, 'ios')", (uri,))
        assert play_dates_before(db_conn, DAY) == ["2026-03-01", "2026-03-05"]

    def test_empty(self, db_conn):
        assert play_dates_before(db_conn, DAY) == []


class TestSelectSongsPointInTime:
    def test_excludes_later_discoveries(self, library):
        conn, _, later = library
        replay = select_songs(conn, "rest", DAY, BASELINE_CALM_ANCHOR, point_in_time=True)
        assert later not in {s["spotify_uri"] for s in replay["songs"]}
        assert replay["match_stats"]["total_candidates"] == 20
        live = select_songs(conn, "rest", DAY, BASELINE_CALM_ANCHOR)
        assert live["match_stats"]["total_candidates"] == 21  # default behaviour unchanged

    def test_result_songs_carry_why_line_fields(self, library):
        conn, _, _ = library
        song = select_songs(conn, "rest", DAY, BASELINE_CALM_ANCHOR, point_in_time=True)["songs"][0]
        for key in ("valence", "acousticness", "tempo", "tempo_confidence",
                    "original_release_year", "is_anchor", "first_played"):
            assert key in song

    def test_anchor_flag_set_for_recent_plays(self, library):
        conn, _, _ = library
        songs = select_songs(conn, "rest", DAY, BASELINE_CALM_ANCHOR, point_in_time=True)["songs"]
        assert any(s["is_anchor"] for s in songs)  # March plays are within 90 days of DAY
        assert all(isinstance(s["is_anchor"], bool) for s in songs)

    @staticmethod
    def _nudged(conn):
        songs = select_songs(conn, "rest", DAY, BASELINE_CALM_ANCHOR, point_in_time=True)["songs"]
        return {s["spotify_uri"] for s in songs if s["breakdown"]["freshness_nudge"] > 0}

    def test_rotation_ignores_playlists_after_date(self, library):
        conn, uris, _ = library
        # Pushed playlists on the day itself or later must not count; the day before must.
        for later_day in (DAY, "2026-04-09"):
            insert_generated_playlist(conn, date=later_day, detected_state="baseline",
                                      track_uris=uris, reasoning="", whoop_metrics=None,
                                      description="", spotify_playlist_id="laterplaylist")
        assert self._nudged(conn) == set()
        insert_generated_playlist(conn, date="2026-04-07", detected_state="baseline",
                                  track_uris=uris[:5], reasoning="", whoop_metrics=None,
                                  description="", spotify_playlist_id="earlierplaylist")
        assert self._nudged(conn) == set(uris[:5])


class TestPriorPlaylistsChaining:
    """Replayed (never pushed) days feed rotation exactly like pushed playlists."""

    def _nudges(self, conn, prior):
        songs = select_songs(conn, "rest", DAY, BASELINE_CALM_ANCHOR, point_in_time=True, prior_playlists=prior)["songs"]
        return {s["spotify_uri"]: s["breakdown"]["freshness_nudge"] for s in songs}

    def test_yesterdays_replay_nudges_its_songs(self, library):
        conn, uris, _ = library
        nudges = self._nudges(conn, {"2026-04-07": uris[:5]})
        assert {u for u, n in nudges.items() if n > 0} == set(uris[:5])
        assert all(nudges[u] == FRESHNESS_NUDGE[1] for u in uris[:5] if u in nudges)

    def test_prior_on_or_after_the_day_ignored(self, library):
        conn, uris, _ = library
        nudges = self._nudges(conn, {DAY: uris, "2026-04-09": uris})
        assert not any(nudges.values())

    def test_combines_with_pushed_playlists_most_recent_wins(self, library):
        conn, uris, _ = library
        insert_generated_playlist(conn, date="2026-04-05", detected_state="baseline",
                                  track_uris=uris[:8], reasoning="", whoop_metrics=None,
                                  description="", spotify_playlist_id="pushed")
        nudges = self._nudges(conn, {"2026-04-07": uris[:3]})
        expected = {u: FRESHNESS_NUDGE[1] for u in uris[:3]}       # replayed yesterday
        expected.update({u: FRESHNESS_NUDGE[3] for u in uris[3:8]})  # pushed 3 days ago
        for uri, nudge in nudges.items():
            assert nudge == expected.get(uri, 0.0), uri


class TestMergeDaysAgo:
    def test_min_days_and_window(self):
        prior = {"2026-04-07": ["a", "b"], "2026-04-01": ["c"], "2026-04-08": ["d"], "2026-03-01": ["e"]}
        merged = merge_prior_days_ago({"a": 3, "z": 2}, prior, DAY, max_days=7)
        assert merged == {"a": 1, "b": 1, "c": 7, "z": 2}

    def test_no_prior_returns_db_map(self):
        assert merge_prior_days_ago({"a": 2}, None, DAY, max_days=4) == {"a": 2}


class TestBuildDayPlaylists:
    def _fake(self, calls, fail_on=(), histories=None):
        def fake(conn, date_str, point_in_time, prior_playlists=None, history=None):
            calls.append((date_str, {d: list(u) for d, u in (prior_playlists or {}).items()}))
            if histories is not None:
                histories.append(history)
            if date_str in fail_on:
                raise GenerationError("insufficient WHOOP data")
            classification, match = _fake_selection()
            for s in match["songs"]:
                s["spotify_uri"] = f"spotify:track:{date_str}-{s['spotify_uri'].split(':')[-1]}"
            return classification, match
        return fake

    def test_chains_oldest_first(self, db_conn):
        calls = []
        with patch("matching.day_playlist.select_day_songs", side_effect=self._fake(calls)):
            results = build_day_playlists(db_conn, "2026-10-01", "2026-10-03")
        assert [r["date"] for r in results] == ["2026-10-01", "2026-10-02", "2026-10-03"]
        assert calls[0][1] == {}
        assert list(calls[1][1]) == ["2026-10-01"]
        assert len(calls[1][1]["2026-10-01"]) == 20  # the 20 songs actually shown, not the buffer
        assert sorted(calls[2][1]) == ["2026-10-01", "2026-10-02"]
        assert all(r["playlist"] and r["error"] is None for r in results)

    def test_failed_day_reported_and_chain_continues(self, db_conn):
        calls = []
        with patch("matching.day_playlist.select_day_songs",
                   side_effect=self._fake(calls, fail_on={"2026-10-02"})):
            results = build_day_playlists(db_conn, "2026-10-01", "2026-10-03")
        assert results[1] == {"date": "2026-10-02", "playlist": None, "error": "insufficient WHOOP data"}
        assert sorted(calls[2][1]) == ["2026-10-01"]
        assert results[2]["playlist"]

    def test_single_day_range(self, db_conn):
        with patch("matching.day_playlist.select_day_songs", side_effect=self._fake([])):
            assert len(build_day_playlists(db_conn, DAY, DAY)) == 1

    def test_reversed_range_rejected(self, db_conn):
        with pytest.raises(ValueError):
            build_day_playlists(db_conn, "2026-10-03", "2026-10-01")

    def test_score_history_built_once_and_shared(self, db_conn):
        """Scoring a day replays every earlier day: do that once per range, not once per day."""
        histories, shared = [], {"2026-09-30": {"composite": 0.1, "recovery": 50}}
        with patch("matching.day_playlist.compute_composite_history", return_value=shared) as build, \
             patch("matching.day_playlist.select_day_songs", side_effect=self._fake([], histories=histories)):
            build_day_playlists(db_conn, "2026-10-01", "2026-10-03")
        build.assert_called_once_with(db_conn, "2026-10-04")  # covers every day in the range
        assert len(histories) == 3 and all(h is shared for h in histories)

    def test_given_history_is_used_as_is(self, db_conn):
        histories, given = [], {}
        with patch("matching.day_playlist.compute_composite_history") as build, \
             patch("matching.day_playlist.select_day_songs", side_effect=self._fake([], histories=histories)):
            build_day_playlists(db_conn, "2026-10-01", "2026-10-02", history=given)
        build.assert_not_called()
        assert all(h is given for h in histories)


class TestBangerReferenceDate:
    def test_recent_relative_to_reference(self):
        song = {"engagement_score": 0.9, "last_played": "2026-04-01"}
        assert is_current_banger(song, 0.5, reference_date="2026-04-08") is True
        assert is_current_banger(song, 0.5, reference_date="2026-10-21") is False


def _fake_selection(n=25):
    songs = [{"spotify_uri": f"spotify:track:id{i}", "name": f"Song {i}", "artist": "A",
              "parasympathetic": 0.8, "sympathetic": 0.1, "grounding": 0.3,
              "mood_tags": ["romantic"], "genre_tags": ["bollywood"], "play_count": 5,
              "engagement_score": None, "last_played": None, "energy": 0.4}
             for i in range(n)]
    classification = {"state": "poor_recovery", "metrics": {"recovery_score": 30.0}}
    match = {"songs": songs, "neuro_profile": {"para": 0.7, "symp": 0.1, "grnd": 0.2}, "position": 0.05}
    return classification, match


class TestBuildDayPlaylist:
    def test_page_shape(self, db_conn):
        with patch("matching.day_playlist.select_day_songs", return_value=_fake_selection()) as sel:
            page = build_day_playlist(db_conn, DAY)
        sel.assert_called_once_with(db_conn, DAY, point_in_time=True, prior_playlists=None, history=None)
        assert page["name"] == "Apr 8 — Rest & Repair"
        assert page["spotify_url"] is None
        assert page["state"] == "rest"
        assert len(page["tracks"]) == 20  # trimmed from the 25-song buffer
        track = page["tracks"][0]
        assert set(track) == {"title", "artist", "spotify_url", "why"}
        assert track["spotify_url"] == "https://open.spotify.com/track/id0"
        assert track["why"]
        json.dumps(page)  # serialisable

    @pytest.mark.parametrize("profile,state", [
        ({"para": 0.1, "symp": 0.7, "grnd": 0.2}, "energy"),
        ({"para": 0.1, "symp": 0.2, "grnd": 0.7}, "grounding"),
    ])
    def test_state_from_profile(self, db_conn, profile, state):
        classification, match = _fake_selection()
        match["neuro_profile"] = profile
        with patch("matching.day_playlist.select_day_songs", return_value=(classification, match)):
            assert build_day_playlist(db_conn, DAY)["state"] == state

    def test_name_follows_attuned_position_not_whoop(self, db_conn):
        """WHOOP recovery 30 used to force "Rest & Repair"; a rest day near the top of the
        rest range is "Settle In" whatever WHOOP says."""
        classification, match = _fake_selection()
        match["position"] = 0.25
        with patch("matching.day_playlist.select_day_songs", return_value=(classification, match)):
            assert build_day_playlist(db_conn, DAY)["name"] == "Apr 8 — Settle In"

    def test_history_passed_through(self, db_conn):
        history = {}
        with patch("matching.day_playlist.select_day_songs", return_value=_fake_selection()) as sel:
            build_day_playlist(db_conn, DAY, history=history)
        assert sel.call_args.kwargs["history"] is history


class TestSelectDaySongs:
    def _patches(self, state="baseline", recovery=None, attuned_state="rest", position=0.1):
        profile = {"rest": {"para": 0.6, "symp": 0.2, "grnd": 0.2},
                   "energy": {"para": 0.05, "symp": 0.65, "grnd": 0.3}}[attuned_state]
        return (
            patch("matching.generator.classify_state",
                  return_value={"state": state, "metrics": {"recovery_score": recovery}}),
            patch("intelligence.continuous_profile.compute_continuous_profile", return_value={
                "profile": profile, "target_valence": None, "state": attuned_state,
                "position": position, "z_scores": {}, "signals_used": 0}),
        )

    def test_state_is_attuneds_not_the_old_classifiers(self, library):
        conn, _, _ = library
        a, b = self._patches(state="peak_readiness")
        with a, b:
            _, match = select_day_songs(conn, DAY)
        assert match["state"] == "rest"

    @pytest.mark.parametrize("old_state, recovery, attuned_state, position, allowed", [
        ("peak_readiness", 99.0, "rest", 0.1, False),     # WHOOP's best day, Attuned low
        ("poor_recovery", 10.0, "energy", 0.95, True),    # WHOOP red, Attuned near your best
    ])
    def test_motivational_follows_attuned_not_whoop(self, library, old_state, recovery,
                                                    attuned_state, position, allowed):
        conn, _, _ = library
        anthem = _add_song(conn, 50, ["2026-03-02T12:00:00Z"], mood_tags=("motivational",))
        conn.commit()
        a, b = self._patches(state=old_state, recovery=recovery,
                             attuned_state=attuned_state, position=position)
        with a, b:
            _, match = select_day_songs(conn, DAY)
        assert (anthem in {s["spotify_uri"] for s in match["songs"]}) is allowed

    def test_passes_history_and_returns_position(self, library):
        conn, _, _ = library
        a, b = self._patches()
        history = {}
        with a, b as profile:
            _, match = select_day_songs(conn, DAY, point_in_time=True, history=history)
        profile.assert_called_once_with(conn, DAY, history)
        assert match["position"] == 0.1

    def test_writes_nothing(self, library):
        conn, _, _ = library
        a, b = self._patches()
        with a, b:
            _, match = select_day_songs(conn, DAY, point_in_time=True)
        assert match["songs"]
        assert conn.execute("SELECT COUNT(*) FROM generated_playlists").fetchone()[0] == 0

    def test_insufficient_data_raises(self, library):
        conn, _, _ = library
        a, b = self._patches(state="insufficient_data")
        with a, b, pytest.raises(GenerationError):
            select_day_songs(conn, DAY)

    def test_no_songs_raises(self, db_conn):
        a, b = self._patches()
        with a, b, pytest.raises(GenerationError):
            select_day_songs(db_conn, DAY, point_in_time=True)


class TestSharedHistoryMatchesPerDay:
    """Real scoring + selection: a range built on one shared score history gives exactly the
    playlists each day gets when it rebuilds its own history."""

    def test_range_identical_with_and_without_shared_history(self, db_conn):
        from tests.test_feeling_score import HOUR, _insert_day, _seed_history
        days = ["2026-06-01", "2026-06-02", "2026-06-03"]
        _seed_history(db_conn, days[0], 90)
        for i, (total_h, eff, hrv) in enumerate([(3.9, 78, 40), (7.2, 88, 48), (9.0, 95, 56)]):
            _insert_day(db_conn, days[i], 1 + i, total_ms=total_h * HOUR, eff=eff, hrv=hrv, rhr=56, recovery=55)
        for i in range(40):
            _add_song(db_conn, i, [f"2026-03-{k + 1:02d}T12:00:00Z" for k in range(1 + i % 5)], para=i / 40)
        db_conn.commit()

        shared = build_day_playlists(db_conn, days[0], days[-1])

        prior, per_day = {}, []
        for d in days:
            page = build_day_playlist(db_conn, d, prior)  # no history: each day rebuilds its own
            prior[d] = ["spotify:track:" + t["spotify_url"].rsplit("/", 1)[-1] for t in page["tracks"]]
            per_day.append({"date": d, "playlist": page, "error": None})

        assert shared == per_day
        assert {r["playlist"]["state"] for r in shared} == {"rest", "grounding", "energy"}
