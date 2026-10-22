"""Tests for intelligence/dates.py — moving a YYYY-MM-DD date by whole days."""

import pytest

from intelligence.dates import shift_date


class TestShiftDate:
    @pytest.mark.parametrize("date, days, expected", [
        ("2026-06-01", -1, "2026-05-31"),
        ("2026-06-01", 0, "2026-06-01"),
        ("2026-06-01", 1, "2026-06-02"),
        ("2026-06-01", -30, "2026-05-02"),
        ("2026-01-01", -1, "2025-12-31"),       # across a year
        ("2028-02-28", 1, "2028-02-29"),        # leap day
        ("2026-03-08", 1, "2026-03-09"),        # US DST change: dates, not clock time
    ])
    def test_moves_by_whole_days(self, date, days, expected):
        assert shift_date(date, days) == expected

    @pytest.mark.parametrize("bad", ["2026/06/01", "20260601", "2026-13-01", ""])
    def test_rejects_a_malformed_date(self, bad):
        with pytest.raises(ValueError):
            shift_date(bad, 1)
