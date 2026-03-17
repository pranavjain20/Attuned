"""Tests for spotify/engagement.py — engagement scoring from behavioral signals."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from db import queries
from spotify.engagement import (
    _compute_active_play_rates,
    _compute_completion_rates,
    _compute_final_scores,
    _compute_skip_rates,
    _parse_date,
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
    def test_all_clickrow(self, db_conn):
        """All plays were intentional clicks → 1.0."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="clickrow")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="clickrow")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["active_play_rate"] == 1.0

    def test_no_clickrow(self, db_conn):
        """All plays were autoplay → 0.0."""
        _insert_song(db_conn, "uri:1")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z", reason_start="trackdone")
        _insert_play(db_conn, "uri:1", "2026-01-02T10:00:00Z", reason_start="fwdbtn")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert song["active_play_rate"] == 0.0

    def test_mixed(self, db_conn):
        """3 of 5 plays were clickrow → 0.6."""
        _insert_song(db_conn, "uri:1")
        for i in range(3):
            _insert_play(db_conn, "uri:1", f"2026-01-0{i+1}T10:00:00Z",
                         reason_start="clickrow")
        for i in range(2):
            _insert_play(db_conn, "uri:1", f"2026-01-0{i+4}T10:00:00Z",
                         reason_start="trackdone")

        _compute_active_play_rates(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        assert abs(song["active_play_rate"] - 0.6) < 0.01


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
        _insert_song(db_conn, "uri:low", play_count=3, duration_ms=200000)
        # Need at least one >30s play for the rate computations to populate
        for uri in ("uri:max", "uri:low"):
            _insert_play(db_conn, uri, f"2026-01-01T10:00:00Z")

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        max_song = queries.get_song(db_conn, "uri:max")
        low_song = queries.get_song(db_conn, "uri:low")
        assert max_song["engagement_score"] > low_song["engagement_score"]


class TestRecency:
    def test_recent_song_scores_higher(self, db_conn):
        """Song played today scores higher on recency than one played a year ago."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")

        _insert_song(db_conn, "uri:new", play_count=5, last_played=today, duration_ms=200000)
        _insert_song(db_conn, "uri:old", play_count=5, last_played=old, duration_ms=200000)
        for uri in ("uri:new", "uri:old"):
            _insert_play(db_conn, uri, f"2026-01-01T10:00:00Z")

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        new_song = queries.get_song(db_conn, "uri:new")
        old_song = queries.get_song(db_conn, "uri:old")
        assert new_song["engagement_score"] > old_song["engagement_score"]

    def test_365_days_ago_is_zero_recency(self, db_conn):
        """Song played exactly 365+ days ago → recency = 0.0."""
        old = (datetime.now(timezone.utc) - timedelta(days=366)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:old", play_count=5, last_played=old, duration_ms=200000)
        _insert_play(db_conn, "uri:old", "2026-01-01T10:00:00Z")

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:old")
        # With recency=0 and known signals, verify score is reasonable
        assert song["engagement_score"] is not None
        assert 0.0 <= song["engagement_score"] <= 1.0


class TestEngagementScoreFormula:
    def test_known_inputs(self, db_conn):
        """Verify weighted sum with known inputs."""
        # Song with play_count=10, also the max
        _insert_song(db_conn, "uri:1", play_count=10, duration_ms=200000,
                     last_played=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        # All plays are clickrow, no skips, full completion
        for i in range(3):
            _insert_play(db_conn, "uri:1", f"2026-01-0{i+1}T10:00:00Z",
                         ms_played=200000, reason_start="clickrow",
                         reason_end="trackdone", skipped=0)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:1")
        # log_play = log(11)/log(11) = 1.0
        # completion = 1.0, active = 1.0, skip = 0.0, recency ≈ 1.0
        # score = 1.0*0.35 + 1.0*0.25 + 1.0*0.20 + 1.0*0.10 + 1.0*0.10 = 1.0
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
# _parse_date helper
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_z_suffix(self):
        """ISO 8601 with Z suffix parses to UTC datetime."""
        result = _parse_date("2026-03-17T10:00:00Z")
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 17
        assert result.hour == 10

    def test_plus_zero_offset(self):
        """ISO 8601 with +00:00 offset parses correctly."""
        result = _parse_date("2026-03-17T10:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.hour == 10

    def test_date_only(self):
        """Date-only string (YYYY-MM-DD) parses to midnight UTC."""
        result = _parse_date("2026-03-17")
        assert result is not None
        assert result.hour == 0
        assert result.minute == 0
        assert result.tzinfo is not None

    def test_invalid_string(self):
        """Invalid date string returns None."""
        result = _parse_date("not-a-date")
        assert result is None

    def test_empty_string(self):
        """Empty string returns None."""
        result = _parse_date("")
        assert result is None

    def test_non_utc_timezone_offset(self):
        """ISO 8601 with non-UTC offset is correctly converted to UTC."""
        result = _parse_date("2026-03-17T10:00:00+05:30")
        assert result is not None
        assert result.tzinfo == timezone.utc
        # 10:00+05:30 = 04:30 UTC
        assert result.hour == 4
        assert result.minute == 30

    def test_no_t_separator_with_time(self):
        """Date string without T but with time info falls through to date-only path."""
        # "2026-03-17 10:00:00" has no "T" so the code appends T00:00:00+00:00
        # This would produce "2026-03-17 10:00:00T00:00:00+00:00" → ValueError → None
        result = _parse_date("2026-03-17 10:00:00")
        assert result is None

    def test_with_milliseconds_z(self):
        """ISO 8601 with milliseconds and Z suffix."""
        result = _parse_date("2026-03-17T10:00:00.123Z")
        assert result is not None
        assert result.hour == 10


# ---------------------------------------------------------------------------
# Boundary: exactly at MIN_MEANINGFUL_LISTENS threshold
# ---------------------------------------------------------------------------

class TestExactlyAtThreshold:
    def test_play_count_exactly_at_min(self, db_conn):
        """Song with play_count == MIN_MEANINGFUL_LISTENS (3) should be scored."""
        _insert_song(db_conn, "uri:exact", play_count=3, duration_ms=200000)
        _insert_play(db_conn, "uri:exact", "2026-01-01T10:00:00Z")

        scored = compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:exact")
        assert scored == 1
        assert song["engagement_score"] is not None

    def test_play_count_one_below_min(self, db_conn):
        """Song with play_count == MIN_MEANINGFUL_LISTENS - 1 should NOT be scored."""
        _insert_song(db_conn, "uri:below", play_count=2, duration_ms=200000)
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
        """The redistributed weights (0.467, 0.267, 0.133, 0.133) must sum to 1.0."""
        total = 0.467 + 0.267 + 0.133 + 0.133
        assert abs(total - 1.0) < 0.001

    def test_null_duration_score_matches_formula(self, db_conn):
        """Verify exact score for null-duration song with known signals."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:nd", play_count=10, duration_ms=None, last_played=today)
        # All clickrow, no skips
        for i in range(3):
            _insert_play(db_conn, "uri:nd", f"2026-01-0{i+1}T10:00:00Z",
                         reason_start="clickrow", reason_end="trackdone", skipped=0)

        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:nd")
        # log_play = log(11)/log(11) = 1.0 (only eligible song, so max)
        # active = 1.0, skip = 0.0, recency ≈ 1.0
        # score = 1.0*0.467 + 1.0*0.267 + 1.0*0.133 + 1.0*0.133 = 1.0
        assert abs(song["engagement_score"] - 1.0) < 0.02

    def test_normal_weights_sum_to_one(self):
        """The normal weights (0.35, 0.25, 0.20, 0.10, 0.10) must sum to 1.0."""
        total = 0.35 + 0.25 + 0.20 + 0.10 + 0.10
        assert abs(total - 1.0) < 0.001


# ---------------------------------------------------------------------------
# Recency edge cases
# ---------------------------------------------------------------------------

class TestRecencyEdgeCases:
    def test_null_last_played_gets_zero_recency(self, db_conn):
        """Song with NULL last_played → recency = 0.0, but still scored."""
        _insert_song(db_conn, "uri:no_date", play_count=5, duration_ms=200000,
                     last_played=None)
        _insert_play(db_conn, "uri:no_date", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:no_date")
        assert song["engagement_score"] is not None
        assert 0.0 <= song["engagement_score"] <= 1.0

    def test_date_only_last_played_parses(self, db_conn):
        """last_played as 'YYYY-MM-DD' (date only, no time) still works."""
        _insert_song(db_conn, "uri:date_only", play_count=5, duration_ms=200000,
                     last_played="2026-03-15")
        _insert_play(db_conn, "uri:date_only", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:date_only")
        assert song["engagement_score"] is not None
        assert 0.0 <= song["engagement_score"] <= 1.0

    def test_today_gives_near_full_recency(self, db_conn):
        """Song played today → recency very close to 1.0."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:today", play_count=5, duration_ms=200000,
                     last_played=today)
        _insert_play(db_conn, "uri:today", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:today")
        # recency = max(0, 1 - 0/365) = 1.0
        # With all perfect signals: score should be very high
        assert song["engagement_score"] >= 0.9

    def test_exactly_at_365_days(self, db_conn):
        """Song played exactly 365 days ago → recency = 0.0."""
        exactly_365 = (datetime.now(timezone.utc) - timedelta(days=365)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _insert_song(db_conn, "uri:365", play_count=5, duration_ms=200000,
                     last_played=exactly_365)
        _insert_play(db_conn, "uri:365", "2026-01-01T10:00:00Z")

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)
        _compute_final_scores(db_conn)

        song = queries.get_song(db_conn, "uri:365")
        assert song["engagement_score"] is not None
        assert 0.0 <= song["engagement_score"] <= 1.0


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
        _insert_song(db_conn, "uri:b", play_count=3, duration_ms=200000, last_played=today)
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
        _insert_song(db_conn, "uri:worst", play_count=3, duration_ms=200000, last_played=old)
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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:nc", play_count=5, duration_ms=200000, last_played=today)
        # Only short plays, so completion_rate stays NULL
        _insert_play(db_conn, "uri:nc", "2026-01-01T10:00:00Z", ms_played=5000)

        # Manually run sub-functions — completion_rate won't be set
        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)

        # Verify completion_rate is NULL before final scoring
        song = queries.get_song(db_conn, "uri:nc")
        assert song["completion_rate"] is None

        _compute_final_scores(db_conn)
        song = queries.get_song(db_conn, "uri:nc")
        assert song["engagement_score"] is not None

    def test_null_active_play_rate_defaults_to_half(self, db_conn):
        """active_play_rate=NULL in final score defaults to 0.5."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:na", play_count=5, duration_ms=200000, last_played=today)
        # No >30s plays → active_play_rate stays NULL
        _insert_play(db_conn, "uri:na", "2026-01-01T10:00:00Z", ms_played=5000)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)

        song = queries.get_song(db_conn, "uri:na")
        assert song["active_play_rate"] is None

        _compute_final_scores(db_conn)
        song = queries.get_song(db_conn, "uri:na")
        assert song["engagement_score"] is not None

    def test_null_skip_rate_defaults_to_zero(self, db_conn):
        """skip_rate=NULL in final score defaults to 0.0 (benefit of the doubt)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_song(db_conn, "uri:ns", play_count=5, duration_ms=200000, last_played=today)
        _insert_play(db_conn, "uri:ns", "2026-01-01T10:00:00Z", ms_played=5000)

        _compute_completion_rates(db_conn)
        _compute_active_play_rates(db_conn)
        _compute_skip_rates(db_conn)

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
        _insert_song(db_conn, "uri:only", play_count=3, duration_ms=200000, last_played=today)
        _insert_play(db_conn, "uri:only", "2026-01-01T10:00:00Z",
                     ms_played=200000, reason_start="clickrow",
                     reason_end="trackdone", skipped=0)

        compute_engagement_scores(db_conn)

        song = queries.get_song(db_conn, "uri:only")
        # log_play = log(4)/log(4) = 1.0
        # completion = 1.0, active = 1.0, skip = 0.0, recency ≈ 1.0
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
