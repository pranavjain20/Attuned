"""Tests for web/publish.py and `main.py publish-playlists`: public Spotify playlists for the latest days only."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
import spotipy

import main
from spotify.auth import SpotifyRateLimitError
from spotify.playlist import SpotifyPlaylistError
from web import publish
from web.publish import MAX_RECENT, check_recent, describe, plan_publish, publish_steps, track_uris
from web.site import load_published, save_published


def _track(track_id):
    return {"title": track_id, "artist": "A", "spotify_url": f"https://open.spotify.com/track/{track_id}"}


def _day(date, state="rest", tracks=("a", "b"), name=None):
    playlist = None if tracks is None else {
        "name": name or f"{date} — Settle In", "state": state, "tracks": [_track(t) for t in tracks]}
    return {"date": date, "playlist": playlist}


DAYS = [_day("2026-04-08"), _day("2026-10-18"), _day("2026-10-19", tracks=None),
        _day("2026-10-20", state="energy"), _day("2026-10-21", tracks=()), _day("2026-10-22", state="grounding")]


def _url(playlist_id):
    return f"https://open.spotify.com/playlist/{playlist_id}"


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


# ─── small pieces ────────────────────────────────────────────────────────────


class TestPieces:
    def test_track_uris_in_order(self):
        assert track_uris(_day("d", tracks=("b", "a"))["playlist"]) == ["spotify:track:b", "spotify:track:a"]

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


# ─── plan_publish ────────────────────────────────────────────────────────────


class TestPlan:
    def test_picks_latest_days_that_have_songs(self):
        steps = plan_publish(DAYS, {}, 3)
        # 10-21 has an empty playlist and 10-19 none: skipped, so 10-18 is the third most recent.
        assert [s["date"] for s in steps] == ["2026-10-18", "2026-10-20", "2026-10-22"]
        assert {s["action"] for s in steps} == {"create"}

    def test_step_carries_page_name_description_and_tracks(self):
        step = plan_publish(DAYS, {}, 1)[0]
        assert step == {"date": "2026-10-22", "action": "create", "name": "2026-10-22 — Settle In",
                        "description": "Attuned · keep you level · built from my WHOOP data",
                        "track_uris": ["spotify:track:a", "spotify:track:b"]}

    def test_published_with_same_tracks_is_unchanged(self):
        published = {"2026-10-22": {"url": _url("x"), "track_uris": ["spotify:track:a", "spotify:track:b"]}}
        assert plan_publish(DAYS, published, 1)[0]["action"] == "unchanged"

    def test_published_with_different_tracks_is_replaced(self):
        published = {"2026-10-22": {"url": _url("x"), "track_uris": ["spotify:track:b", "spotify:track:a"]}}
        assert plan_publish(DAYS, published, 1)[0]["action"] == "replace"

    def test_never_reaches_past_the_window_even_when_recent_days_are_published(self):
        published = {d: {"url": _url(d), "track_uris": ["spotify:track:a", "spotify:track:b"]}
                     for d in ("2026-10-18", "2026-10-20", "2026-10-22")}
        steps = plan_publish(DAYS, published, 3)
        assert [s["date"] for s in steps] == ["2026-10-18", "2026-10-20", "2026-10-22"]
        assert {s["action"] for s in steps} == {"unchanged"}

    def test_fewer_days_than_asked(self):
        assert [s["date"] for s in plan_publish(DAYS[:2], {}, 3)] == ["2026-04-08", "2026-10-18"]

    def test_cap_enforced(self):
        with pytest.raises(ValueError):
            plan_publish(DAYS, {}, 4)


# ─── publish_steps ───────────────────────────────────────────────────────────


class TestPublish:
    def test_creates_public_playlist_then_sets_tracks_and_records_it(self, sp, path):
        steps = plan_publish(DAYS, {}, 1)
        result, _ = _publish(sp, steps, {}, path)
        sp._post.assert_called_once_with("me/playlists", payload={
            "name": "2026-10-22 — Settle In", "public": True,
            "description": "Attuned · keep you level · built from my WHOOP data"})
        sp.playlist_add_items.assert_not_called()
        sp.playlist_replace_items.assert_called_once_with("p1", ["spotify:track:a", "spotify:track:b"])
        record = {"url": _url("p1"), "track_uris": ["spotify:track:a", "spotify:track:b"]}
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

    def test_changed_tracks_replace_the_existing_playlist(self, sp, path):
        published = {"2026-10-22": {"url": _url("old") + "?si=abc", "track_uris": ["spotify:track:z"]}}
        save_published(published, path)
        result, _ = _publish(sp, plan_publish(DAYS, published, 1), published, path)
        sp._post.assert_not_called()
        sp.playlist_replace_items.assert_called_once_with("old", ["spotify:track:a", "spotify:track:b"])
        assert load_published(path)["2026-10-22"] == {
            "url": _url("old") + "?si=abc", "track_uris": ["spotify:track:a", "spotify:track:b"]}
        assert result == load_published(path)

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
            "2026-10-18": {"url": _url("p1"), "track_uris": ["spotify:track:a", "spotify:track:b"]},
            "2026-10-20": {"url": _url("p2"), "track_uris": []},
        }

    def test_retry_after_partial_failure_fills_tracks_without_a_second_playlist(self, sp, path):
        sp.playlist_replace_items.side_effect = [None, spotipy.SpotifyException(500, -1, "boom")]
        with pytest.raises(SpotifyPlaylistError):
            _publish(sp, plan_publish(DAYS, {}, 2), {}, path)
        sp.reset_mock()
        sp.playlist_replace_items.side_effect = None
        published = load_published(path)
        steps = plan_publish(DAYS, published, 2)
        assert [s["action"] for s in steps] == ["unchanged", "replace"]
        _publish(sp, steps, published, path)
        sp._post.assert_not_called()
        sp.playlist_replace_items.assert_called_once_with("p2", ["spotify:track:a", "spotify:track:b"])

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
        build = MagicMock(return_value=DAYS)
        monkeypatch.setattr("web.site.build_site_days", build)
        client = MagicMock(return_value=sp)
        monkeypatch.setattr("spotify.auth.get_spotify_client", client)
        monkeypatch.setattr("web.publish.THROTTLE_S", 0)
        return {"path": path, "build": build, "client": client, "sp": sp}

    def test_dry_run_writes_nothing_and_never_touches_spotify(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "3", "--dry-run")
        out = capsys.readouterr().out
        assert "2026-10-22" in out and "create" in out and "Dry run" in out
        env["client"].assert_not_called()
        assert not env["path"].exists()

    def test_publishes_and_records(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "3")
        assert sorted(load_published(env["path"])) == ["2026-10-18", "2026-10-20", "2026-10-22"]
        assert env["sp"]._post.call_count == 3

    def test_builds_the_same_window_as_the_site(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "1", "--days", "30", "--end", "2026-10-22", "--dry-run")
        assert env["build"].call_args.args[1:3] == ("2026-10-22", 30)

    def test_defaults_to_three_and_30_days(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--dry-run")
        assert env["build"].call_args.args[2] == 30
        assert capsys.readouterr().out.count("create") == 3

    def test_nothing_to_do_skips_spotify_login(self, monkeypatch, capsys, db_path, env):
        save_published({d: {"url": _url(d), "track_uris": ["spotify:track:a", "spotify:track:b"]}
                        for d in ("2026-10-18", "2026-10-20", "2026-10-22")}, env["path"])
        self._run(monkeypatch, db_path, "--recent", "3")
        env["client"].assert_not_called()

    def test_refuses_more_than_three_before_any_work(self, monkeypatch, capsys, db_path, env):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", "4")
        assert "--allow-more" in capsys.readouterr().out
        env["build"].assert_not_called()
        env["client"].assert_not_called()

    def test_allow_more_lifts_the_cap(self, monkeypatch, capsys, db_path, env):
        self._run(monkeypatch, db_path, "--recent", "4", "--allow-more", "--dry-run")
        assert capsys.readouterr().out.count("create") == 4

    @pytest.mark.parametrize("bad", ["0", "abc", "-1"])
    def test_rejects_bad_recent(self, monkeypatch, capsys, db_path, env, bad):
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", bad)
        env["build"].assert_not_called()

    def test_rate_limit_exits_with_message_and_keeps_file_valid(self, monkeypatch, capsys, db_path, env):
        env["sp"].playlist_replace_items.side_effect = SpotifyRateLimitError(3600)
        with pytest.raises(SystemExit):
            self._run(monkeypatch, db_path, "--recent", "3")
        assert "quota" in capsys.readouterr().out
        assert json.loads(env["path"].read_text()) == {"2026-10-18": {"url": _url("p1"), "track_uris": []}}

    def test_listed_in_usage(self):
        assert "publish-playlists" in main.COMMANDS
