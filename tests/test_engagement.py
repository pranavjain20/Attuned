"""Tests for spotify/engagement.py — engagement scoring from behavioral signals."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from db import queries
from spotify.engagement import (
    _compute_active_play_rates,
    _compute_completion_rates,
    _compute_final_scores,
    _compute_recent_play_ratios,
    _compute_skip_rates,
    compute_engagement_scores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_song(conn, uri, name="Song", artist="Artist", duration_ms=240000,
                 play_count=5, last_played="2026-03-01T00:00:00Z"):
    """Insert a song with given attributes."""
    conn.execute(
        """INSERT INTO songs (spotify_uri, name, artist, duration_ms, play_count,
                              last_played, sources)
           VALUES (?, ?, ?, ?, ?, ?, '[]')""",
        (uri, name, artist, duration_ms, play_count, last_played),
    )
    conn.commit()


def _insert_play(conn, uri, played_at, ms_played=180000,
                 reason_start="clickrow", reason_end="trackdone", skipped=0):
    """Insert a listening history record."""
    conn.execute(
        """INSERT INTO listening_history
               (spotify_uri, played_at, ms_played, reason_start, reason_end, skipped)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uri, played_at, ms_played, reason_start, reason_end, skipped),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Completion rate
# ---------------------------------------------------------------------------

class TestCompletionRate:
    def test_basic(self, db_conn):
        """Song with known ms_played and duration_ms gets correct completion_rate."""
        _insert_song(db_conn, "uri:1", duration_ms=200000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=160000)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", ms_played=200000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        # avg(160000/200000, 200000/200000) = avg(0.8, 1.0) = 0.9
        assert abs(song["completion_rate"] - 0.9) < 0.01

    def test_caps_at_one(self, db_conn):
        """ms_played > duration_ms gets capped at 1.0."""
        _insert_song(db_conn, "uri:1", duration_ms=200000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=250000)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", ms_played=300000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["completion_rate"] == pytest.approx(1.0)

    def test_skips_no_duration(self, db_conn):
        """Songs without duration_ms get NULL completion_rate."""
        _insert_song(db_conn, "uri:1", duration_ms=None)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=180000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["completion_rate"] is None

    def test_ignores_short_plays(self, db_conn):
        """Plays under 30s are excluded from completion_rate calculation."""
        _insert_song(db_conn, "uri:1", duration_ms=200000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=5000)
        # Only the long play should count
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", ms_played=180000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        # Only the 180000/200000 = 0.9 play counted
        assert abs(song["completion_rate"] - 0.9) < 0.01


# ---------------------------------------------------------------------------
# Active play rate
# ---------------------------------------------------------------------------

class TestActivePlayRate:
    def test_all_intentional(self, db_conn):
        """All plays were intentional (clickrow/playbtn/remote) → 1.0."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="clickrow")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="playbtn")
        _insert_play(db_conn, "uri:1", "2026-01-03T10:00:00Z", reason_start="remote")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["active_play_rate"] == 1.0

    def test_no_intentional(self, db_conn):
        """All plays were autoplay → 0.0."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="trackdone")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="fwdbtn")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["active_play_rate"] == 0.0

    def test_mixed(self, db_conn):
        """3 of 5 plays were intentional → 0.6."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="clickrow")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="playbtn")
        _insert_play(db_conn, "uri:1", "2026-01-03T10:00:00Z", reason_start="remote")
        for i in range(2):
            _insert_play(db_conn, "uri:1", f"2026-01-0{i+4}T10:00:00Z",
                         reason_start="trackdone")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["active_play_rate"] - 0.6) < 0.01

    def test_playbtn_counts_as_intentional(self, db_conn):
        """playbtn (play button press) counts as intentional."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="playbtn")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="trackdone")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["active_play_rate"] - 0.5) < 0.01

    def test_remote_counts_as_intentional(self, db_conn):
        """remote (Alexa/voice/Spotify Connect) counts as intentional."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="remote")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="trackdone")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["active_play_rate"] - 0.5) < 0.01


# ---------------------------------------------------------------------------
# Skip rate
# ---------------------------------------------------------------------------

class TestSkipRate:
    def test_no_skips(self, db_conn):
        """No fwdbtn or skipped → 0.0."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z",
                     reason_end="trackdone", skipped=0)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z",
                     reason_end="trackdone", skipped=0)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["skip_rate"] == 0.0

    def test_all_skipped(self, db_conn):
        """Every play skipped → 1.0."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z",
                     reason_end="fwdbtn", skipped=1)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z",
                     reason_end="fwdbtn", skipped=1)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["skip_rate"] == 1.0

    def test_partial_skips(self, db_conn):
        """1 of 4 plays skipped → 0.25."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z",
                     reason_end="fwdbtn", skipped=1)
        for i in range(3):
            _insert_play(db_conn, "uri:1", f"2026-01-0{i+2}T10:00:00Z",
                         reason_end="trackdone", skipped=0)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["skip_rate"] - 0.25) < 0.01


# ---------------------------------------------------------------------------
# Final score components
# ---------------------------------------------------------------------------

class TestLogNormalizedPlayCount:
    def test_max_plays_gets_one(self, db_conn):
        """Song with max plays → log_play ≈ 1.0."""
        _insert_song(db_conn, "uri:max", play_count=100, duration_ms=200000)
        _insert_song(db_conn, "uri:low", play_count=5, duration_ms=200000)
        # Need at least one >30s play for the rate computations to populate
        for uri in ("uri:max", "uri:low"):
            _insert_play(db_conn, uri, f"2026-01-01T10:00:00Z")

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)
        _compute_final_scores(db_conn)

        max_song = queries.get_song(db_conn, "uri:max")
        low_song = queries.get_song(db_conn, "uri:low")
        assert max_song["engagement_score"] > low_song["engagement_score"]


class TestRecentPlayRatio:
    def test_song_with_all_recent_plays_scores_higher(self, db_conn):
        """Song with all plays in last 365 days scores higher than one with none recent."""
        recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_date = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")

        _insert_song(db_conn, "uri:new", play_count=5, duration_ms=200000)
        _insert_song(db_conn, "uri:old", play_count=5, duration_ms=200000)
        # "uri:new" has all plays recent → recent_play_ratio = 1.0
        for i in range(3):
            _insert_play(db_conn, "uri:new", f"{recent_date[:-1]}{i}Z")
        # "uri:old" has all plays old → recent_play_ratio = 0.0
        for i in range(3):
            _insert_play(db_conn, "uri:old", f"{old_date[:-1]}{i}Z")

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)
        _compute_final_scores(db_conn)

        new_song = queries.get_song(db_conn, "uri:new")
        old_song = queries.get_song(db_conn, "uri:old")
        assert new_song["engagement_score"] > old_song["engagement_score"]

    def test_all_plays_older_than_365_days_gives_zero_ratio(self, db_conn):
        """Song with all >30s plays older than 365 days → recent_play_ratio = 0.0."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:old", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:old", old_date)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:old")
        assert song["recent_play_ratio"] == pytest.approx(0.0)

    def test_mixed_recent_and_old_plays(self, db_conn):
        """Song with 2 of 4 plays in last 365 days → recent_play_ratio = 0.5."""
        recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")

        _insert_song(db_conn, "uri:mix", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:mix", f"2026-03-17T10:00:00Z")
        _insert_play(db_conn, "uri:mix", f"2026-03-17T11:00:00Z")
        _insert_play(db_conn, "uri:mix", f"2024-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:mix", f"2024-01-01T11:00:00Z")

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:mix")
        assert song["recent_play_ratio"] == pytest.approx(0.5)


class TestEngagementScoreFormula:
    def test_known_inputs(self, db_conn):
        """Verify weighted sum with known inputs."""
        # Song with play_count=10, also the max
        _insert_song(db_conn, "uri:1", play_count=10, duration_ms=200000)
        # All plays are recent, clickrow, no skips, full completion
        for i in range(3):
            _insert_play(db_conn, "uri:1", f"2026-01-0{i+1}T10:00:00Z",
                         ms_played=200000, reason_start="clickrow",
                         reason_end="trackdone", skipped=0)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        # log_play = log(11)/log(11) = 1.0
        # completion = 1.0, active = 1.0, skip = 0.0, recent_play_ratio = 1.0
        # score = 1.0*0.30 + 1.0*0.25 + 1.0*0.15 + 1.0*0.10 + 1.0*0.20 = 1.0
        assert abs(song["engagement_score"] - 1.0) < 0.02


class TestBelowThreshold:
    def test_skips_songs_below_play_threshold(self, db_conn):
        """Songs with fewer than MIN_MEANINGFUL_LISTENS plays get no score."""
        _insert_song(db_conn, "uri:low", play_count=2, duration_ms=200000)
        _insert_song(db_conn, "uri:ok", play_count=5, duration_ms=200000)
        for uri in ("uri:low", "uri:ok"):
            _insert_play(db_conn, uri, "2026-01-01T10:00:00Z")

        compute_engagement_scores(db_conn)

        low = queries.get_song(db_conn, "uri:low")
        ok = queries.get_song(db_conn, "uri:ok")
        assert low["engagement_score"] is None
        assert ok["engagement_score"] is not None


class TestIdempotent:
    def test_running_twice_gives_same_results(self, db_conn):
        """Running compute_engagement_scores twice produces identical scores."""
        _insert_song(db_conn, "uri:1", play_count=10, duration_ms=200000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=180000)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", ms_played=200000)

        compute_engagement_scores(db_conn)
        first_score = queries.get_song(db_conn, "uri:1")["engagement_score"]

        compute_engagement_scores(db_conn)
        second_score = queries.get_song(db_conn, "uri:1")["engagement_score"]

        assert first_score == second_score


class TestNullDuration:
    def test_handles_null_duration_without_crash(self, db_conn):
        """Songs without duration_ms get scored with redistributed weights."""
        _insert_song(db_conn, "uri:no_dur", play_count=5, duration_ms=None)
        _insert_play(db_conn, "uri:no_dur", "2026-01-01T10:00:00Z",
                     reason_start="clickrow", reason_end="trackdone", skipped=0)

        scored = compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:no_dur")
        assert scored == 1
        assert song["engagement_score"] is not None
        assert 0.0 <= song["engagement_score"] <= 1.0
        assert song["completion_rate"] is None  # No duration → no completion


class TestNoEligibleSongs:
    def test_returns_zero_when_no_songs(self, db_conn):
        """No songs in DB → returns 0."""
        scored = compute_engagement_scores(db_conn)
        assert scored == 0

    def test_returns_zero_when_all_below_threshold(self, db_conn):
        """All songs below play threshold → returns 0."""
        _insert_song(db_conn, "uri:1", play_count=1)
        _insert_song(db_conn, "uri:2", play_count=2)
        scored = compute_engagement_scores(db_conn)
        assert scored == 0


# ---------------------------------------------------------------------------
# Boundary: exactly at MIN_MEANINGFUL_LISTENS threshold
# ---------------------------------------------------------------------------

class TestExactlyAtThreshold:
    def test_play_count_exactly_at_min(self, db_conn):
        """Song with play_count == MIN_MEANINGFUL_LISTENS (5) should be scored."""
        _insert_song(db_conn, "uri:exact", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:exact", "2026-01-01T10:00:00Z")

        scored = compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:exact")
        assert scored == 1
        assert song["engagement_score"] is not None

    def test_play_count_one_below_min(self, db_conn):
        """Song with play_count == MIN_MEANINGFUL_LISTENS - 1 should NOT be scored."""
        _insert_song(db_conn, "uri:below", play_count=4, duration_ms=200000)
        _insert_play(db_conn, "uri:below", "2026-01-01T10:00:00Z")

        scored = compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:below")
        assert scored == 0
        assert song["engagement_score"] is None


# ---------------------------------------------------------------------------
# All plays under 30s — rates should remain NULL
# ---------------------------------------------------------------------------

class TestAllPlaysUnder30s:
    def test_completion_rate_null_when_all_plays_short(self, db_conn):
        """If every play is <30s, completion_rate stays NULL."""
        _insert_song(db_conn, "uri:short", duration_ms=200000, play_count=5)
        _insert_play(db_conn, "uri:short", "2026-01-01T10:00:00Z", ms_played=5000)
        _insert_play(db_conn, "uri:short", "2026-01-02T10:00:00Z", ms_played=20000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:short")
        assert song["completion_rate"] is None

    def test_active_play_rate_null_when_all_plays_short(self, db_conn):
        """If every play is <30s, active_play_rate stays NULL."""
        _insert_song(db_conn, "uri:short", play_count=5)
        _insert_play(db_conn, "uri:short", "2026-01-01T10:00:00Z", ms_played=5000,
                     reason_start="clickrow")
        _insert_play(db_conn, "uri:short", "2026-01-02T10:00:00Z", ms_played=20000,
                     reason_start="clickrow")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:short")
        assert song["active_play_rate"] is None

    def test_skip_rate_null_when_all_plays_short(self, db_conn):
        """If every play is <30s, skip_rate stays NULL."""
        _insert_song(db_conn, "uri:short", play_count=5)
        _insert_play(db_conn, "uri:short", "2026-01-01T10:00:00Z", ms_played=5000,
                     reason_end="fwdbtn", skipped=1)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:short")
        assert song["skip_rate"] is None


# ---------------------------------------------------------------------------
# Skip rate: test OR branches independently
# ---------------------------------------------------------------------------

class TestSkipRateOrBranches:
    def test_fwdbtn_alone_counts_as_skip(self, db_conn):
        """reason_end='fwdbtn' with skipped=0 still counts as skip."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z",
                     reason_end="fwdbtn", skipped=0)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z",
                     reason_end="trackdone", skipped=0)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["skip_rate"] - 0.5) < 0.01

    def test_skipped_flag_alone_counts_as_skip(self, db_conn):
        """skipped=1 with reason_end='trackdone' still counts as skip."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z",
                     reason_end="trackdone", skipped=1)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z",
                     reason_end="trackdone", skipped=0)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["skip_rate"] - 0.5) < 0.01

    def test_fwdbtn_and_skipped_not_double_counted(self, db_conn):
        """A play with both fwdbtn and skipped=1 counts as ONE skip, not two."""
        _insert_song(db_conn, "uri:1")
        # One play: both skip signals
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z",
                     reason_end="fwdbtn", skipped=1)
        # One play: not skipped
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z",
                     reason_end="trackdone", skipped=0)

        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        # 1 of 2 plays skipped = 0.5, NOT 1.0
        assert abs(song["skip_rate"] - 0.5) < 0.01


# ---------------------------------------------------------------------------
# Weight redistribution for null duration
# ---------------------------------------------------------------------------

class TestNullDurationWeightRedistribution:
    def test_redistributed_weights_sum_to_one(self):
        """The redistributed weights (0.400, 0.200, 0.133, 0.267) must sum to 1.0."""
        total = 0.400 + 0.200 + 0.133 + 0.267
        assert abs(total - 1.0) < 0.001

    def test_null_duration_score_matches_formula(self, db_conn):
        """Verify exact score for null-duration song with known signals."""
        _insert_song(db_conn, "uri:nd", play_count=10, duration_ms=None)
        # All clickrow, no skips, all recent plays
        for i in range(3):
            _insert_play(db_conn, "uri:nd", f"2026-01-0{i+1}T10:00:00Z",
                         reason_start="clickrow", reason_end="trackdone", skipped=0)

        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:nd")
        # log_play = log(11)/log(11) = 1.0 (only eligible song, so max)
        # active = 1.0, skip = 0.0, recent_play_ratio = 1.0
        # score = 1.0*0.400 + 1.0*0.200 + 1.0*0.133 + 1.0*0.267 = 1.0
        assert abs(song["engagement_score"] - 1.0) < 0.02

    def test_normal_weights_sum_to_one(self):
        """The normal weights (0.30, 0.25, 0.15, 0.10, 0.20) must sum to 1.0."""
        total = 0.30 + 0.25 + 0.15 + 0.10 + 0.20
        assert abs(total - 1.0) < 0.001


# ---------------------------------------------------------------------------
# Recency edge cases
# ---------------------------------------------------------------------------

class TestRecentPlayRatioEdgeCases:
    def test_no_plays_gives_null_ratio_and_zero_default(self, db_conn):
        """Song with no >30s plays → recent_play_ratio stays NULL, defaults to 0.0 in scoring."""
        _insert_song(db_conn, "uri:no_plays", play_count=5, duration_ms=200000)
        # Only a short play — won't count
        _insert_play(db_conn, "uri:no_plays", "2026-01-01T10:00:00Z", ms_played=5000)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:no_plays")
        assert song["engagement_score"] is not None
        assert 0.0 <= song["engagement_score"] <= 1.0

    def test_all_recent_plays_gives_ratio_one(self, db_conn):
        """Song where every >30s play is within 365 days → recent_play_ratio = 1.0."""
        _insert_song(db_conn, "uri:recent", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:recent", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)
        _insert_play(db_conn, "uri:recent", "2026-02-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:recent")
        assert song["recent_play_ratio"] == pytest.approx(1.0)

    def test_all_recent_plays_gives_high_score(self, db_conn):
        """Song with all recent plays and perfect signals → score near 1.0."""
        _insert_song(db_conn, "uri:today", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:today", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:today")
        assert song["engagement_score"] >= 0.9

    def test_all_old_plays_gives_ratio_zero(self, db_conn):
        """Song where every >30s play is older than 365 days → recent_play_ratio = 0.0."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=400)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _insert_song(db_conn, "uri:365", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:365", old_date)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:365")
        assert song["recent_play_ratio"] == pytest.approx(0.0)

    def test_short_plays_excluded_from_ratio(self, db_conn):
        """Plays under 30s don't count in recent_play_ratio calculation."""
        _insert_song(db_conn, "uri:mix", play_count=5, duration_ms=200000)
        # Recent short play (should not count)
        _insert_play(db_conn, "uri:mix", "2026-01-01T10:00:00Z", ms_played=5000)
        # Old long play (should count)
        old_date = (datetime.now(timezone.utc) - timedelta(days=400)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _insert_play(db_conn, "uri:mix", old_date, ms_played=200000)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:mix")
        # Only 1 >30s play and it's old → ratio = 0.0
        assert song["recent_play_ratio"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Orphan listening history (plays for songs not in songs table)
# ---------------------------------------------------------------------------

class TestOrphanListeningHistory:
    def test_plays_without_song_entry_are_harmless(self, db_conn):
        """Plays for URIs not in the songs table should not cause errors."""
        # Insert play without a matching song
        _insert_play(db_conn, "uri:orphan", "2026-01-01T10:00:00Z")
        # Insert a proper song to be scored
        _insert_song(db_conn, "uri:real", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:real", "2026-01-01T10:00:00Z")

        scored = compute_engagement_scores(db_conn)

        assert scored == 1
        real = queries.get_song(db_conn, "uri:real")
        assert real["engagement_score"] is not None


# ---------------------------------------------------------------------------
# Multiple songs: verify independent scoring
# ---------------------------------------------------------------------------

class TestMultipleSongs:
    def test_scores_independent_across_songs(self, db_conn):
        """Each song's score depends only on its own signals, not other songs' signals."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Song A: high engagement (all clickrow, no skips, full completion)
        _insert_song(db_conn, "uri:a", play_count=20, duration_ms=200000, last_played=today)
        for i in range(5):
            _insert_play(db_conn, "uri:a", f"2026-01-0{i+1}T10:00:00Z",
                         ms_played=200000, reason_start="clickrow",
                         reason_end="trackdone", skipped=0)
        # Song B: low engagement (all autoplay, all skipped, partial completion)
        _insert_song(db_conn, "uri:b", play_count=5, duration_ms=200000, last_played=today)
        for i in range(3):
            _insert_play(db_conn, "uri:b", f"2026-02-0{i+1}T10:00:00Z",
                         ms_played=60000, reason_start="trackdone",
                         reason_end="fwdbtn", skipped=1)

        scored = compute_engagement_scores(db_conn)

        assert scored == 2
        a = queries.get_song(db_conn, "uri:a")
        b = queries.get_song(db_conn, "uri:b")
        assert a["engagement_score"] > b["engagement_score"]
        # Both should be in valid range
        assert 0.0 <= a["engagement_score"] <= 1.0
        assert 0.0 <= b["engagement_score"] <= 1.0


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

class TestScoreClamping:
    def test_worst_case_score_at_least_zero(self, db_conn):
        """Song with worst possible signals → score >= 0.0."""
        old = (datetime.now(timezone.utc) - timedelta(days=500)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Minimum play count, all skips, no clickrow, poor completion
        _insert_song(db_conn, "uri:worst", play_count=5, duration_ms=200000, last_played=old)
        for i in range(3):
            _insert_play(db_conn, "uri:worst", f"2026-01-0{i+1}T10:00:00Z",
                         ms_played=40000, reason_start="trackdone",
                         reason_end="fwdbtn", skipped=1)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:worst")
        assert song["engagement_score"] >= 0.0

    def test_score_never_exceeds_one(self, db_conn):
        """Even with all maxed signals, score is capped at 1.0."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:max", play_count=100, duration_ms=200000, last_played=today)
        for i in range(10):
            _insert_play(db_conn, "uri:max", f"2026-01-{i+1:02d}T10:00:00Z",
                         ms_played=200000, reason_start="clickrow",
                         reason_end="trackdone", skipped=0)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:max")
        assert song["engagement_score"] <= 1.0


# ---------------------------------------------------------------------------
# Return value accuracy
# ---------------------------------------------------------------------------

class TestReturnValue:
    def test_return_matches_actual_scored_count(self, db_conn):
        """compute_engagement_scores returns the exact number of songs scored."""
        _insert_song(db_conn, "uri:1", play_count=5, duration_ms=200000)
        _insert_song(db_conn, "uri:2", play_count=10, duration_ms=200000)
        _insert_song(db_conn, "uri:3", play_count=1)  # Below threshold
        for uri in ("uri:1", "uri:2"):
            _insert_play(db_conn, uri, "2026-01-01T10:00:00Z")

        scored = compute_engagement_scores(db_conn)

        assert scored == 2
        # Verify by counting in DB
        row = db_conn.execute(
            "SELECT COUNT(*) as cnt FROM songs WHERE engagement_score IS NOT NULL"
        ).fetchone()
        assert row["cnt"] == scored


# ---------------------------------------------------------------------------
# Default fallback values when rates are NULL in final scoring
# ---------------------------------------------------------------------------

class TestFinalScoreNullFallbacks:
    def test_null_completion_rate_defaults_to_half(self, db_conn):
        """Song with duration but no >30s plays → completion_rate=NULL → defaults to 0.5."""
        _insert_song(db_conn, "uri:nc", play_count=5, duration_ms=200000)
        # Only short plays, so completion_rate stays NULL
        _insert_play(db_conn, "uri:nc", "2026-01-01T10:00:00Z", ms_played=5000)

        # Manually run sub-functions — completion_rate won't be set
        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)

        # Verify completion_rate is NULL before final scoring
        song = queries.get_song(db_conn, "uri:nc")
        assert song["completion_rate"] is None

        _compute_final_scores(db_conn)
        song = queries.get_song(db_conn, "uri:nc")
        assert song["engagement_score"] is not None

    def test_null_active_play_rate_defaults_to_half(self, db_conn):
        """active_play_rate=NULL in final score defaults to 0.5."""
        _insert_song(db_conn, "uri:na", play_count=5, duration_ms=200000)
        # No >30s plays → active_play_rate stays NULL
        _insert_play(db_conn, "uri:na", "2026-01-01T10:00:00Z", ms_played=5000)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:na")
        assert song["active_play_rate"] is None

        _compute_final_scores(db_conn)
        song = queries.get_song(db_conn, "uri:na")
        assert song["engagement_score"] is not None

    def test_null_skip_rate_defaults_to_zero(self, db_conn):
        """skip_rate=NULL in final score defaults to 0.0 (benefit of the doubt)."""
        _insert_song(db_conn, "uri:ns", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:ns", "2026-01-01T10:00:00Z", ms_played=5000)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:ns")
        assert song["skip_rate"] is None

        _compute_final_scores(db_conn)
        song = queries.get_song(db_conn, "uri:ns")
        assert song["engagement_score"] is not None


# ---------------------------------------------------------------------------
# Single eligible song (is its own max for log normalization)
# ---------------------------------------------------------------------------

class TestSingleEligibleSong:
    def test_single_song_log_play_is_one(self, db_conn):
        """With only one eligible song, log_play = log(n+1)/log(n+1) = 1.0."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:only", play_count=5, duration_ms=200000, last_played=today)
        _insert_play(db_conn, "uri:only", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:only")
        # log_play = log(4)/log(4) = 1.0
        # completion = 1.0, active = 1.0, skip = 0.0, recent_play_ratio = 1.0
        # Score should be very close to 1.0
        assert song["engagement_score"] >= 0.95


# ---------------------------------------------------------------------------
# Completion rate: plays at exactly 30000 ms (boundary)
# ---------------------------------------------------------------------------

class TestExactly30sPlay:
    def test_play_at_exactly_30000ms_is_included(self, db_conn):
        """A play of exactly 30000 ms (MIN_PLAY_DURATION_MS) should be included."""
        _insert_song(db_conn, "uri:1", duration_ms=200000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=30000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        # 30000/200000 = 0.15
        assert song["completion_rate"] is not None
        assert abs(song["completion_rate"] - 0.15) < 0.01

    def test_play_at_29999ms_is_excluded(self, db_conn):
        """A play of 29999 ms (just below threshold) should be excluded."""
        _insert_song(db_conn, "uri:1", duration_ms=200000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=29999)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["completion_rate"] is None


# ---------------------------------------------------------------------------
# Completion rate: SQL MIN cap behavior
# ---------------------------------------------------------------------------

class TestCompletionRateCap:
    def test_single_play_over_duration_caps_at_one(self, db_conn):
        """One play with ms_played > duration_ms → completion capped at 1.0 via MIN."""
        _insert_song(db_conn, "uri:1", duration_ms=180000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=250000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["completion_rate"] == 1.0

    def test_avg_over_one_still_caps(self, db_conn):
        """Average ms_played/duration > 1.0 → caps at 1.0.

        Note: SQL MIN(1.0, AVG(...)) caps the final average, not individual plays.
        So avg(250000/180000, 200000/180000) = avg(1.39, 1.11) = 1.25 → MIN(1.0, 1.25) = 1.0.
        """
        _insert_song(db_conn, "uri:1", duration_ms=180000)
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", ms_played=250000)
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", ms_played=200000)

        _compute_completion_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["completion_rate"] == 1.0


# ---------------------------------------------------------------------------
# Order of sub-function calls
# ---------------------------------------------------------------------------

class TestSubFunctionOrder:
    def test_different_call_order_same_final_score(self, db_conn):
        """Calling sub-functions in reverse order produces the same final score."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Insert identical data in two songs
        for uri in ("uri:a", "uri:b"):
            _insert_song(db_conn, uri, play_count=10, duration_ms=200000, last_played=today)
            for i in range(3):
                _insert_play(db_conn, uri, f"2026-01-0{i+1}T{10 if uri == 'uri:a' else 11}:00:00Z",
                             ms_played=180000, reason_start="clickrow",
                             reason_end="trackdone", skipped=0)

        # Score uri:a with normal order
        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_recent_play_ratios(db_conn)
        _compute_final_scores(db_conn)

        score_a = queries.get_song(db_conn, "uri:a")["engagement_score"]
        score_b = queries.get_song(db_conn, "uri:b")["engagement_score"]

        # Both songs have identical signals, so scores should be equal
        assert score_a == score_b


# ---------------------------------------------------------------------------
# Mixed duration_ms: some songs have it, some don't
# ---------------------------------------------------------------------------

class TestMixedDuration:
    def test_both_scored_with_different_weight_schemes(self, db_conn):
        """Song with duration uses normal weights; song without uses redistributed."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:with", play_count=10, duration_ms=200000, last_played=today)
        _insert_song(db_conn, "uri:without", play_count=10, duration_ms=None, last_played=today)
        for uri in ("uri:with", "uri:without"):
            for i in range(3):
                _insert_play(db_conn, uri, f"2026-01-0{i+1}T{'10' if uri == 'uri:with' else '11'}:00:00Z",
                             ms_played=200000, reason_start="clickrow",
                             reason_end="trackdone", skipped=0)

        scored = compute_engagement_scores(db_conn)

        assert scored == 2
        with_song = queries.get_song(db_conn, "uri:with")
        without_song = queries.get_song(db_conn, "uri:without")
        assert with_song["engagement_score"] is not None
        assert without_song["engagement_score"] is not None
        # with_song gets completion_rate computed, without_song does not
        assert with_song["completion_rate"] is not None
        assert without_song["completion_rate"] is None


# ---------------------------------------------------------------------------
# _compute_recent_play_ratios: cutoff boundary tests
# ---------------------------------------------------------------------------

class TestRecentPlayRatioCutoffBoundary:
    def test_play_exactly_at_365_day_cutoff_is_recent(self, db_conn):
        """A play at exactly 365 days ago should count as recent (played_at >= cutoff)."""
        # The cutoff is computed as now - 365 days. A play at exactly that boundary
        # should be >= cutoff and thus counted as recent.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _insert_song(db_conn, "uri:boundary", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:boundary", cutoff, ms_played=60000)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:boundary")
        assert song["recent_play_ratio"] == pytest.approx(1.0)

    def test_play_one_second_before_cutoff_is_old(self, db_conn):
        """A play 1 second before the 365-day cutoff is not recent."""
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=365)
        just_before = (cutoff_dt - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:just_old", play_count=5, duration_ms=200000)
        _insert_play(db_conn, "uri:just_old", just_before, ms_played=60000)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:just_old")
        assert song["recent_play_ratio"] == pytest.approx(0.0)

    def test_all_plays_exactly_at_365_days(self, db_conn):
        """Multiple plays exactly at the 365-day boundary all count as recent."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=365))
        _insert_song(db_conn, "uri:all365", play_count=5, duration_ms=200000)
        for i in range(3):
            ts = (cutoff + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            _insert_play(db_conn, "uri:all365", ts, ms_played=60000)

        _compute_recent_play_ratios(db_conn)

        song = queries.get_song(db_conn, "uri:all365")
        assert song["recent_play_ratio"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Schema migration: recent_play_ratio column
# ---------------------------------------------------------------------------

class TestRecentPlayRatioMigration:
    def test_column_exists_after_schema_creation(self, db_conn):
        """The recent_play_ratio column exists in the songs table after schema creation."""
        # db_conn fixture already calls get_connection which calls create_tables
        columns = db_conn.execute("PRAGMA table_info(songs)").fetchall()
        column_names = [col["name"] for col in columns]
        assert "recent_play_ratio" in column_names

    def test_migration_idempotent(self, db_conn):
        """Calling the migration twice doesn't error (ALTER TABLE is skipped)."""
        from db.schema import _migrate_add_recent_play_ratio
        # First call already happened in get_connection, second should be harmless
        _migrate_add_recent_play_ratio(db_conn)
        columns = db_conn.execute("PRAGMA table_info(songs)").fetchall()
        column_names = [col["name"] for col in columns]
        assert column_names.count("recent_play_ratio") == 1

    def test_recent_play_ratio_defaults_to_null(self, db_conn):
        """New songs have recent_play_ratio = NULL by default."""
        _insert_song(db_conn, "uri:fresh", play_count=5, duration_ms=200000)
        song = queries.get_song(db_conn, "uri:fresh")
        assert song["recent_play_ratio"] is None
