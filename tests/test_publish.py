"""Tests for web/publish.py and `main.py publish-playlists`: public Spotify playlists for the latest days only."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
import spotipy

import main
from db.queries import upsert_song
from spotify.auth import SpotifyRateLimitError
from spotify.playlist import SpotifyPlaylistError
from web import publish
from web.publish import (
    candidate_uris,
    check_recent,
    describe,
    find_unavailable,
    plan_publish,
    publish_steps,
    recent_days,
)
from web.site import load_published, save_published


def _track(track_id):
    return {"title": track_id, "artist": "A", "spotify_url": f"https://open.spotify.com/track/{track_id}"}


def _day(date, state="rest", tracks=("a", "b"), name=None, spares=()):
    playlist = None if tracks is None else {
        "name": name or f"{date} — Settle In", "state": state, "tracks": [_track(t) for t in tracks],
        "spares": [_track(t) for t in spares]}
    return {"date": date, "playlist": playlist}


DAYS = [_day("2026-04-08"), _day("2026-10-18"), _day("2026-10-19", tracks=None),
        _day("2026-10-20", state="energy"), _day("2026-10-21", tracks=()), _day("2026-10-22", state="grounding")]
AB = ["spotify:track:a", "spotify:track:b"]


def _url(playlist_id):
    return f"https://open.spotify.com/playlist/{playlist_id}"


def _record(day, playlist_id=None, uris=AB):
    """The record publishing leaves for one of DAYS: current name/description and tracks."""
    playlist = next(d for d in DAYS if d["date"] == day)["playlist"]
    return {"url": _url(playlist_id or day), "track_uris": list(uris),
            "name": playlist["name"], "description": describe(playlist)}


@pytest.fixture
def sp():
    client = MagicMock(spec=spotipy.Spotify)
    ids = iter(["p1", "p2", "p3", "p4"])

    def post(endpoint, payload):
        playlist_id = next(ids)
        return {"id": playlist_id, "external_urls": {"spotify": _url(playlist_id)}}
    client._post.side_effect = post
    return client


@pytest.fixture
def path(tmp_path):
    return tmp_path / "published.json"


def _publish(sp, steps, published, path):
    sleeps = []
    result = publish_steps(sp, steps, published, path, sleep=sleeps.append)
    return result, sleeps


def _not_found():
    return spotipy.SpotifyException(404, -1, "Not found")


# ─── small pieces ────────────────────────────────────────────────────────────


class TestPieces:
    def test_candidates_are_the_tracks_then_the_spares_in_order(self):
        playlist = _day("d", tracks=("b", "a"), spares=("c", "d"))["playlist"]
        assert candidate_uris(playlist) == ["spotify:track:b", "spotify:track:a", "spotify:track:c", "spotify:track:d"]

    def test_candidates_without_spares(self):
        assert candidate_uris({"tracks": [_track("a")]}) == ["spotify:track:a"]

    @pytest.mark.parametrize("state, purpose", [
        ("rest", "help you settle"), ("energy", "give you a lift"), ("grounding", "keep you level")])
    def test_description_names_the_purpose(self, state, purpose):
        assert describe({"state": state}) == f"Attuned · {purpose} · built from my WHOOP data"

    @pytest.mark.parametrize("n", [1, 2, 3])
    def test_up_to_three_allowed(self, n):
        check_recent(n)

    @pytest.mark.parametrize("n", [4, 30])
    def test_more_than_three_refused(self, n):
        with pytest.raises(ValueError, match="--allow-more"):
            check_recent(n)

    def test_more_than_three_allowed_only_explicitly(self):
        check_recent(4, allow_more=True)

    @pytest.mark.parametrize("n", [0, -1])
    def test_non_positive_refused(self, n):
        with pytest.raises(ValueError):
            check_recent(n, allow_more=True)

    def test_recent_days_are_the_latest_with_songs(self):
        assert [d["date"] for d in recent_days(DAYS, 3)] == ["2026-10-18", "2026-10-20", "2026-10-22"]

    def test_recent_days_enforces_the_cap(self):
        with pytest.raises(ValueError):
            recent_days(DAYS, 4)


# ─── find_unavailable ────────────────────────────────────────────────────────


@patch("matching.generator.time.sleep")
class TestFindUnavailable:
    """Reuses the daily pipeline's availability check (and its cache and 3 s spacing)."""

    def _sp(self, unplayable=()):
        client = MagicMock(spec=spotipy.Spotify)
        client.track.side_effect = lambda track_id: {"name": track_id, "artists": [{"name": "A"}],
                                                     "is_playable": track_id not in unplayable}
        return client

    def test_returns_the_songs_spotify_no_longer_plays(self, _sleep, db_conn):
        days = [_day("2026-10-22", tracks=("a", "b"), spares=("c",))]
        client = self._sp(unplayable={"b"})
        assert find_unavailable(db_conn, client, days, sleep=lambda s: None) == {"spotify:track:b"}

    def test_checks_each_song_once_across_days(self, _sleep, db_conn):
        days = [_day("2026-10-21", tracks=("a", "b")), _day("2026-10-22", tracks=("b", "c"))]
        client = self._sp()
        find_unavailable(db_conn, client, days, sleep=lambda s: None)
        assert sorted(c.args[0] for c in client.track.call_args_list) == ["a", "b", "c"]

    def test_spaces_the_checks_and_pauses_before_the_writes(self, track_sleep, db_conn):
        sleeps = []
        find_unavailable(db_conn, self._sp(), [_day("2026-10-22", tracks=("a", "b", "c"))], sleep=sleeps.append)
        assert track_sleep.call_count == 2           # between the three checks
        assert sleeps == [publish.THROTTLE_S]        # then once before publishing writes

    def test_recently_confirmed_songs_skip_the_call(self, _sleep, db_conn):
        from datetime import datetime, timezone
        upsert_song(db_conn, "spotify:track:a", "A", "A", sources=["test"])
        db_conn.execute("UPDATE songs SET is_available = 1, availability_checked_at = ? WHERE spotify_uri = ?",
                        (datetime.now(timezone.utc).isoformat(), "spotify:track:a"))
        client = self._sp()
        find_unavailable(db_conn, client, [_day("2026-10-22", tracks=("a", "b"))], sleep=lambda s: None)
        assert [c.args[0] for c in client.track.call_args_list] == ["b"]

    def test_result_is_saved_for_the_page_and_later_runs(self, _sleep, db_conn):
        upsert_song(db_conn, "spotify:track:b", "B", "A", sources=["test"])
        find_unavailable(db_conn, self._sp(unplayable={"b"}), [_day("2026-10-22")], sleep=lambda s: None)
        row = db_conn.execute("SELECT is_available FROM songs WHERE spotify_uri = 'spotify:track:b'").fetchone()
        assert row["is_available"] == 0

    def test_rate_limit_propagates(self, _sleep, db_conn):
        client = MagicMock(spec=spotipy.Spotify)
        client.track.side_effect = SpotifyRateLimitError(3600)
        with pytest.raises(SpotifyRateLimitError):
            find_unavailable(db_conn, client, [_day("2026-10-22")], sleep=lambda s: None)

    def test_no_days_no_calls(self, _sleep, db_conn):
        client = self._sp()
        assert find_unavailable(db_conn, client, [], sleep=lambda s: None) == set()
        client.track.assert_not_called()


# ─── plan_publish ────────────────────────────────────────────────────────────


class TestPlan:
    def test_picks_latest_days_that_have_songs(self):
        steps = plan_publish(DAYS, {}, 3)
        # 10-21 has an empty playlist and 10-19 none: skipped, so 10-18 is the third most recent.
        assert [s["date"] for s in steps] == ["2026-10-18", "2026-10-20", "2026-10-22"]
        assert {s["action"] for s in steps} == {"create"}

    def test_step_carries_page_name_description_and_tracks(self):
        step = plan_publish(DAYS, {}, 1)[0]
        assert step == {"date": "2026-10-22", "action": "create", "changes": [], "name": "2026-10-22 — Settle In",
                        "description": "Attuned · keep you level · built from my WHOOP data",
                        "track_uris": AB}

    def test_published_with_same_tracks_and_details_is_unchanged(self):
        step = plan_publish(DAYS, {"2026-10-22": _record("2026-10-22")}, 1)[0]
        assert (step["action"], step["changes"]) == ("unchanged", [])

    def test_published_with_different_tracks_is_updated(self):
        published = {"2026-10-22": _record("2026-10-22", uris=AB[::-1])}
        step = plan_publish(DAYS, published, 1)[0]
        assert (step["action"], step["changes"]) == ("update", ["tracks"])

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_published_with_a_changed_name_or_description_is_updated(self, field):
        published = {"2026-10-22": {**_record("2026-10-22"), field: "old"}}
        step = plan_publish(DAYS, published, 1)[0]
        assert (step["action"], step["changes"]) == ("update", ["details"])

    def test_record_from_before_details_were_kept_gets_them(self):
        published = {"2026-10-22": {"url": _url("x"), "track_uris": AB}}
        assert plan_publish(DAYS, published, 1)[0]["changes"] == ["details"]

    def test_tracks_and_details_both_changed(self):
        published = {"2026-10-22": {"url": _url("x"), "track_uris": ["spotify:track:z"]}}
        assert plan_publish(DAYS, published, 1)[0]["changes"] == ["tracks", "details"]

    def test_never_reaches_past_the_window_even_when_recent_days_are_published(self):
        published = {d: _record(d) for d in ("2026-10-18", "2026-10-20", "2026-10-22")}
        steps = plan_publish(DAYS, published, 3)
        assert [s["date"] for s in steps] == ["2026-10-18", "2026-10-20", "2026-10-22"]
        assert {s["action"] for s in steps} == {"unchanged"}

    def test_fewer_days_than_asked(self):
        assert [s["date"] for s in plan_publish(DAYS[:2], {}, 3)] == ["2026-04-08", "2026-10-18"]

    def test_cap_enforced(self):
        with pytest.raises(ValueError):
            plan_publish(DAYS, {}, 4)

    def test_unavailable_song_replaced_by_the_first_spare(self):
        days = [_day("2026-10-22", tracks=("a", "b", "c"), spares=("s1", "s2"))]
        step = plan_publish(days, {}, 1, unavailable={"spotify:track:b"})[0]
        assert step["track_uris"] == ["spotify:track:a", "spotify:track:c", "spotify:track:s1", "spotify:track:s2"]

    def test_trimmed_to_the_playlist_size(self):
        tracks = tuple(f"t{i}" for i in range(20))
        days = [_day("2026-10-22", tracks=tracks, spares=("s1", "s2", "s3", "s4", "s5"))]
        uris = plan_publish(days, {}, 1, unavailable={"spotify:track:t3", "spotify:track:t7"})[0]["track_uris"]
        assert len(uris) == 20
        assert uris[-2:] == ["spotify:track:s1", "spotify:track:s2"]
        assert "spotify:track:t3" not in uris and "spotify:track:s3" not in uris

    def test_with_nothing_unavailable_the_spares_stay_out(self):
        tracks = tuple(f"t{i}" for i in range(20))
        days = [_day("2026-10-22", tracks=tracks, spares=("s1",))]
        assert "spotify:track:s1" not in plan_publish(days, {}, 1)[0]["track_uris"]

    def test_more_unavailable_than_spares_publishes_fewer_songs(self):
        days = [_day("2026-10-22", tracks=("a", "b", "c"), spares=("s1",))]
        uris = plan_publish(days, {}, 1, unavailable={"spotify:track:a", "spotify:track:b"})[0]["track_uris"]
        assert uris == ["spotify:track:c", "spotify:track:s1"]

    def test_day_with_every_song_unavailable_is_left_out(self, caplog):
        days = [_day("2026-10-21", tracks=("c",)), _day("2026-10-22", tracks=("a",))]
        steps = plan_publish(days, {}, 2, unavailable={"spotify:track:a"})
        assert [s["date"] for s in steps] == ["2026-10-21"]
        assert "2026-10-22" in caplog.text


# ─── publish_steps ───────────────────────────────────────────────────────────


class TestPublish:
    def test_creates_public_playlist_then_sets_tracks_and_records_it(self, sp, path):
        steps = plan_publish(DAYS, {}, 1)
        result, _ = _publish(sp, steps, {}, path)
        sp._post.assert_called_once_with("me/playlists", payload={
            "name": "2026-10-22 — Settle In", "public": True,
            "description": "Attuned · keep you level · built from my WHOOP data"})
        sp.playlist_add_items.assert_not_called()
        sp.playlist_replace_items.assert_called_once_with("p1", AB)
        record = _record("2026-10-22", "p1")
        assert result == {"2026-10-22": record}
        assert load_published(path) == {"2026-10-22": record}

    def test_throttles_every_call(self, sp, path):
        _, sleeps = _publish(sp, plan_publish(DAYS, {}, 3), {}, path)
        assert len(sleeps) == 6 and all(s == publish.THROTTLE_S for s in sleeps)

    def test_idempotent_second_run_makes_no_calls(self, sp, path):
        first, _ = _publish(sp, plan_publish(DAYS, {}, 3), {}, path)
        sp.reset_mock()
        second, sleeps = _publish(sp, plan_publish(DAYS, load_published(path), 3), load_published(path), path)
        assert second == first and sleeps == []
        sp._post.assert_not_called()
        sp.playlist_replace_items.assert_not_called()
        sp.playlist_change_details.assert_not_called()

    def test_changed_tracks_replace_the_existing_playlist(self, sp, path):
        published = {"2026-10-22": {**_record("2026-10-22"), "url": _url("old") + "?si=abc",
                                    "track_uris": ["spotify:track:z"]}}
        save_published(published, path)
        result, sleeps = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        sp._post.assert_not_called()
        sp.playlist_change_details.assert_not_called()
        sp.playlist_replace_items.assert_called_once_with("old", AB)
        assert load_published(path)["2026-10-22"] == {**published["2026-10-22"], "track_uris": AB}
        assert result == load_published(path)
        assert sleeps == [publish.THROTTLE_S]

    def test_changed_name_updates_the_details_only(self, sp, path):
        published = {"2026-10-22": {**_record("2026-10-22"), "name": "Oct 22 — Fuel Up"}}
        result, sleeps = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        sp.playlist_change_details.assert_called_once_with(
            "2026-10-22", name="2026-10-22 — Settle In",
            description="Attuned · keep you level · built from my WHOOP data")
        sp.playlist_replace_items.assert_not_called()
        sp._post.assert_not_called()
        assert result["2026-10-22"] == _record("2026-10-22")
        assert load_published(path) == result
        assert sleeps == [publish.THROTTLE_S]

    def test_old_record_gets_its_details_written_down(self, sp, path):
        published = {"2026-10-22": {"url": _url("x"), "track_uris": AB}}
        result, _ = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        sp.playlist_change_details.assert_called_once()
        assert result["2026-10-22"] == _record("2026-10-22", "x")

    def test_playlist_deleted_on_spotify_is_made_again(self, sp, path):
        """404 on replace: the recorded playlist is gone, so make a new one and record its URL."""
        published = {"2026-10-22": _record("2026-10-22", "gone", uris=["spotify:track:z"])}
        sp.playlist_replace_items.side_effect = [_not_found(), None]
        result, _ = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        assert sp._post.call_count == 1
        assert [c.args for c in sp.playlist_replace_items.call_args_list] == [("gone", AB), ("p1", AB)]
        assert result["2026-10-22"] == _record("2026-10-22", "p1")
        assert load_published(path) == result

    def test_playlist_deleted_found_by_a_details_change_is_made_again(self, sp, path):
        published = {"2026-10-22": {**_record("2026-10-22", "gone"), "name": "old"}}
        sp.playlist_change_details.side_effect = _not_found()
        result, _ = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        sp.playlist_replace_items.assert_called_once_with("p1", AB)
        assert result["2026-10-22"] == _record("2026-10-22", "p1")

    def test_recreating_stays_within_the_planned_days(self, sp, path):
        published = {d: _record(d, uris=["spotify:track:z"]) for d in ("2026-04-08", "2026-10-22")}
        sp.playlist_replace_items.side_effect = [_not_found(), None]
        result, _ = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        assert sp._post.call_count == 1
        assert result["2026-04-08"] == published["2026-04-08"]  # outside the window: untouched

    @pytest.mark.parametrize("status", [403, 500])
    def test_other_errors_on_update_stop_the_run(self, sp, path, status):
        published = {"2026-10-22": _record("2026-10-22", uris=["spotify:track:z"])}
        save_published(published, path)
        sp.playlist_replace_items.side_effect = spotipy.SpotifyException(status, -1, "boom")
        with pytest.raises(SpotifyPlaylistError):
            _publish(sp, plan_publish(DAYS, published, 1), published, path)
        sp._post.assert_not_called()
        assert load_published(path) == published

    def test_does_not_mutate_callers_mapping(self, sp, path):
        published = {}
        _publish(sp, plan_publish(DAYS, published, 1), published, path)
        assert published == {}

    def test_rate_limit_aborts_and_keeps_finished_days(self, sp, path):
        calls = {"n": 0}

        def replace(playlist_id, uris):
            calls["n"] += 1
            if calls["n"] == 2:
                raise SpotifyRateLimitError(3600)
        sp.playlist_replace_items.side_effect = replace
        with pytest.raises(SpotifyRateLimitError):
            _publish(sp, plan_publish(DAYS, {}, 3), {}, path)
        assert sp._post.call_count == 2  # third day never attempted
        # Day 1 done; day 2's playlist exists but has no tracks yet, so the file says so.
        assert load_published(path) == {
            "2026-10-18": _record("2026-10-18", "p1"),
            "2026-10-20": _record("2026-10-20", "p2", uris=[]),
        }

    def test_retry_after_partial_failure_fills_tracks_without_a_second_playlist(self, sp, path):
        sp.playlist_replace_items.side_effect = [None, spotipy.SpotifyException(500, -1, "boom")]
        with pytest.raises(SpotifyPlaylistError):
            _publish(sp, plan_publish(DAYS, {}, 2), {}, path)
        sp.reset_mock()
        sp.playlist_replace_items.side_effect = None
        published = load_published(path)
        steps = plan_publish(DAYS, published, 2)
        assert [(s["action"], s["changes"]) for s in steps] == [("unchanged", []), ("update", ["tracks"])]
        _publish(sp, steps, published, path)
        sp._post.assert_not_called()
        sp.playlist_replace_items.assert_called_once_with("p2", AB)

    def test_create_failure_writes_nothing(self, sp, path):
        sp._post.side_effect = spotipy.SpotifyException(403, -1, "Forbidden")
        with pytest.raises(SpotifyPlaylistError):
            _publish(sp, plan_publish(DAYS, {}, 1), {}, path)
        assert not path.exists()


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestPublishCommand:
    def _run(self, monkeypatch, db_path, *args):
        monkeypatch.setattr(sys, "argv", ["main.py", "publish-playlists", *args])
        main._cmd_publish_playlists(db_path)

    @pytest.fixture
    def env(self, monkeypatch, tmp_path, sp):
        path = tmp_path / "published.json"
        monkeypatch.setattr("web.site.PUBLISHED_PATH", path)
        dates = MagicMock(return_value=[d["date"] for d in DAYS])
        monkeypatch.setattr("web.site.window_dates", dates)
        replay = MagicMock(return_value={d["date"]: d["playlist"] for d in DAYS})
        monkeypatch.setattr("web.site.replay_playlists", replay)
        client = MagicMock(return_value=sp)
        monkeypatch.setattr("spotify.auth.get_spotify_client", client)
        unavailable = MagicMock(return_value=set())
        monkeypatch.setattr("web.publish.find_unavailable", unavailable)
        monkeypatch.setattr("web.publish.THROTTLE_S", 0)
        return {"path": path, "dates": dates, "replay": replay, "client": client, "sp": sp,
                "unavailable": unavailable}

    def test_dry_run_writes_nothing_and_never_touches_spotify(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "3", "--dry-run")
        out = capsys.readouterr().out
        assert "2026-10-22" in out and "create" in out and "Dry run" in out
        assert "availability" in out  # says the dry run didn't check what Spotify still plays
        env["client"].assert_not_called()
        env["unavailable"].assert_not_called()
        assert not env["path"].exists()

    def test_publishes_and_records(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "3")
        assert sorted(load_published(env["path"])) == ["2026-10-18", "2026-10-20", "2026-10-22"]
        assert env["sp"]._post.call_count == 3

    def test_checks_availability_of_the_published_days_only(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "2")
        checked = env["unavailable"].call_args.args[2]
        assert [d["date"] for d in checked] == ["2026-10-20", "2026-10-22"]

    def test_unavailable_songs_are_not_published(self, monkeypatch, capsys, db_path, env):
        env["unavailable"].return_value = {"spotify:track:a"}
        self._run(monkeypatch, db_path, "--recent", "1")
        env["sp"].playlist_replace_items.assert_called_once_with("p1", ["spotify:track:b"])

    def test_replays_the_same_window_as_the_site(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "1", "--days", "30", "--end", "2026-10-22", "--dry-run")
        assert env["dates"].call_args.args[1:3] == ("2026-10-22", 30)
        assert env["replay"].call_args.args[1] == [d["date"] for d in DAYS]

    def test_defaults_to_three_and_30_days(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--dry-run")
        assert env["dates"].call_args.args[2] == 30
        assert capsys.readouterr().out.count(" create ") == 3

    def test_nothing_to_do_writes_nothing(self, monkeypatch, capsys, db_path, env):
        published = {d: _record(d) for d in ("2026-10-18", "2026-10-20", "2026-10-22")}
        save_published(published, env["path"])
        self._run(monkeypatch, db_path, "--recent", "3")
        assert "Nothing to publish" in capsys.readouterr().out
        env["sp"]._post.assert_not_called()
        env["sp"].playlist_replace_items.assert_not_called()
        assert load_published(env["path"]) == published

    def test_refuses_more_than_three_before_any_work(self, monkeypatch, capsys, db_path, env):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", "4")
        assert "--allow-more" in capsys.readouterr().out
        env["replay"].assert_not_called()
        env["client"].assert_not_called()

    def test_allow_more_lifts_the_cap(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "4", "--allow-more", "--dry-run")
        assert capsys.readouterr().out.count(" create ") == 4

    @pytest.mark.parametrize("bad", ["0", "abc", "-1"])
    def test_rejects_bad_recent(self, monkeypatch, capsys, db_path, env, bad):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", bad)
        env["replay"].assert_not_called()

    def test_rate_limit_exits_with_message_and_keeps_file_valid(self, monkeypatch, capsys, db_path, env):
        env["sp"].playlist_replace_items.side_effect = SpotifyRateLimitError(3600)
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", "3")
        assert "quota" in capsys.readouterr().out
        assert json.loads(env["path"].read_text()) == {"2026-10-18": _record("2026-10-18", "p1", uris=[])}

    def test_rate_limit_during_the_availability_check_exits_cleanly(self, monkeypatch, capsys, db_path, env):
        env["unavailable"].side_effect = SpotifyRateLimitError(3600)
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", "3")
        assert "quota" in capsys.readouterr().out
        env["sp"]._post.assert_not_called()
        assert not env["path"].exists()

    def test_listed_in_usage(self):
        assert "publish-playlists" in main.COMMANDS
