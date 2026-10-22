"""Tests for intelligence/main_sleep.py — which WHOOP record counts as last night."""

import pytest

from config import RESTORATIVE_SLEEP_TOTAL_MIN_MS
from intelligence.main_sleep import (
    asleep_ms, is_nap, is_short_night, main_sleep_by_date, select_main_sleep,
)

HOUR = 3_600_000


def _sleep(sleep_id, hours, nap=None, eff=90.0, date="2026-03-17", **extra):
    """A sleep record shaped like a whoop_sleep row; stages split 20/25/55."""
    ms = int(hours * HOUR)
    deep, rem = int(ms * 0.20), int(ms * 0.25)
    return {
        "sleep_id": sleep_id, "date": date, "nap": nap,
        "deep_sleep_ms": deep, "rem_sleep_ms": rem, "light_sleep_ms": ms - deep - rem,
        "awake_ms": 1_800_000, "sleep_efficiency": eff, **extra,
    }


def _unstaged(sleep_id, nap=0, eff=85.0):
    return {"sleep_id": sleep_id, "date": "2026-03-17", "nap": nap, "deep_sleep_ms": None,
            "rem_sleep_ms": None, "light_sleep_ms": None, "sleep_efficiency": eff}


class TestIsNap:
    @pytest.mark.parametrize("flag, expected", [(1, True), (True, True), (0, False),
                                                (False, False), (None, False)])
    def test_only_explicit_nap_flag_counts(self, flag, expected):
        """NULL (synced before the flag existed) is treated as main sleep, not a nap."""
        assert is_nap({"nap": flag}) is expected


class TestAsleepMs:
    def test_sums_stages(self):
        assert asleep_ms({"deep_sleep_ms": 1, "rem_sleep_ms": 2, "light_sleep_ms": 3}) == 6

    def test_none_when_any_stage_missing(self):
        assert asleep_ms({"deep_sleep_ms": 1, "rem_sleep_ms": None, "light_sleep_ms": 3}) is None


class TestIsShortNight:
    """Short = less than RESTORATIVE_SLEEP_TOTAL_MIN_MS (6 h) asleep."""

    def test_threshold_is_six_hours(self):
        assert RESTORATIVE_SLEEP_TOTAL_MIN_MS == 6 * HOUR

    def test_two_and_a_half_hours_is_short(self):
        assert is_short_night(_sleep("a", 2.5)) is True

    def test_just_under_six_hours_is_short(self):
        night = _sleep("a", 6)
        night["light_sleep_ms"] -= 1
        assert is_short_night(night) is True

    def test_exactly_six_hours_is_not_short(self):
        assert asleep_ms(_sleep("a", 6)) == 6 * HOUR
        assert is_short_night(_sleep("a", 6)) is False

    def test_long_night_is_not_short(self):
        assert is_short_night(_sleep("a", 8)) is False

    def test_missing_stages_is_not_called_short(self):
        """Length unknown → no claim either way."""
        assert is_short_night(_unstaged("a")) is False

    def test_no_night(self):
        assert is_short_night(None) is False


class TestSelectMainSleep:
    def test_empty_returns_none(self):
        assert select_main_sleep([]) is None

    def test_night_only_returned_unchanged(self):
        night = _sleep("night", 7.5, nap=0, eff=88.0)
        assert select_main_sleep([night]) == night

    def test_returns_a_copy(self):
        night = _sleep("night", 7.5, nap=0)
        result = select_main_sleep([night])
        result["deep_sleep_ms"] = 0
        assert night["deep_sleep_ms"] != 0

    def test_nap_listed_first_is_ignored(self):
        """The old bug: the first record (a nap) supplied efficiency and had its stages added."""
        nap = _sleep("nap", 1.3, nap=1, eff=99.0)
        night = _sleep("night", 3.9, nap=0, eff=82.0)
        result = select_main_sleep([nap, night])
        assert result["sleep_id"] == "night"
        assert result["sleep_efficiency"] == 82.0
        assert result["deep_sleep_ms"] == night["deep_sleep_ms"]

    def test_nap_longer_than_night_still_ignored(self):
        nap = _sleep("nap", 4.0, nap=1)
        night = _sleep("night", 3.0, nap=0)
        assert select_main_sleep([nap, night])["sleep_id"] == "night"

    def test_nap_only_returns_none(self):
        """A day with only a nap has no 'last night' to describe."""
        assert select_main_sleep([_sleep("nap", 1.5, nap=1)]) is None

    def test_two_main_records_picks_longest_never_sums(self):
        """Two non-nap records on one date: one night is chosen, never an invented 11 h night."""
        a = _sleep("a", 5.6, nap=0, eff=94.6)
        b = _sleep("b", 5.0, nap=0, eff=86.4)
        result = select_main_sleep([b, a])
        assert result["sleep_id"] == "a"
        assert asleep_ms(result) == asleep_ms(a)
        assert result["sleep_efficiency"] == 94.6

    def test_tie_keeps_first_record(self):
        a, b = _sleep("a", 6.0, nap=0), _sleep("b", 6.0, nap=0)
        assert select_main_sleep([a, b])["sleep_id"] == "a"

    def test_unknown_flags_compete_as_main_sleep(self):
        """Rows synced before the nap flag existed (NULL): longest is taken as the night."""
        short, long = _sleep("short", 1.0, nap=None), _sleep("long", 6.0, nap=None)
        assert select_main_sleep([short, long])["sleep_id"] == "long"

    def test_all_null_stages_returns_first_main_record(self):
        result = select_main_sleep([_unstaged("x", eff=91.0), _unstaged("y", eff=50.0)])
        assert result["sleep_id"] == "x"
        assert result["deep_sleep_ms"] is None

    def test_record_with_stages_beats_record_without(self):
        staged = _sleep("staged", 2.0, nap=0, eff=85.0)
        result = select_main_sleep([_unstaged("u", eff=50.0), staged])
        assert result["sleep_id"] == "staged"

    def test_null_stage_night_with_nap_returns_night(self):
        """The nap's stages must not stand in for a night without stage data."""
        result = select_main_sleep([_sleep("nap", 1.0, nap=1), _unstaged("night")])
        assert result["sleep_id"] == "night"


class TestMainSleepByDate:
    def test_one_entry_per_date_naps_dropped(self):
        records = [
            _sleep("n1", 7.0, nap=0, date="2026-03-16"),
            _sleep("nap", 1.0, nap=1, date="2026-03-16"),
            _sleep("n2", 6.0, nap=0, date="2026-03-17"),
            _sleep("nap-only", 1.0, nap=1, date="2026-03-18"),
        ]
        result = main_sleep_by_date(records)
        assert sorted(result) == ["2026-03-16", "2026-03-17"]
        assert result["2026-03-16"]["sleep_id"] == "n1"

    def test_empty(self):
        assert main_sleep_by_date([]) == {}
