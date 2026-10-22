"""Tests for whoop/client.py — API calls, parsing, date derivation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from whoop.client import (
    _paginated_get,
    _parse_recovery_response,
    _parse_sleep_response,
    get_all_records,
    get_records_near_date,
    local_date,
)


class TestLocalDate:
    """WHOOP sends UTC times plus the wearer's offset; the date is the wearer's own."""

    def test_india_night_ending_before_0530_local_keeps_its_own_date(self):
        # 04:00 in India on Mar 17 is 22:30 UTC on Mar 16
        assert local_date("2026-03-16T22:30:00.000Z", "+05:30") == "2026-03-17"

    def test_us_evening_is_still_the_same_local_day(self):
        # 01:00 UTC Mar 18 is 21:00 on Mar 17 in New York (-04:00)
        assert local_date("2026-03-18T01:00:00.000Z", "-04:00") == "2026-03-17"

    def test_morning_in_us_matches_utc_date(self):
        assert local_date("2026-03-17T11:00:00.000Z", "-04:00") == "2026-03-17"

    def test_half_hour_negative_offset(self):
        assert local_date("2026-03-17T02:00:00.000Z", "-03:30") == "2026-03-16"

    def test_zero_offset(self):
        assert local_date("2026-03-17T23:59:59.999Z", "+00:00") == "2026-03-17"

    def test_exactly_midnight_local_is_the_new_day(self):
        assert local_date("2026-03-16T18:30:00.000Z", "+05:30") == "2026-03-17"

    def test_missing_offset_uses_the_timestamps_own_offset(self):
        assert local_date("2026-03-17T20:00:00.000-05:00", None) == "2026-03-17"

    def test_missing_offset_on_utc_timestamp_gives_utc_date(self):
        assert local_date("2026-03-16T22:30:00.000Z", None) == "2026-03-16"

    def test_malformed_offset_falls_back_to_timestamp(self, caplog):
        assert local_date("2026-03-16T22:30:00.000Z", "India") == "2026-03-16"
        assert "timezone offset" in caplog.text

    def test_timestamp_without_offset_is_read_as_utc(self):
        assert local_date("2026-03-16T22:30:00", "+05:30") == "2026-03-17"

    def test_empty_string(self):
        assert local_date("", "+05:30") == ""

    def test_none_returns_empty(self):
        assert local_date(None, "+05:30") == ""

    def test_malformed_timestamp_returns_truncated_fallback(self):
        # Defensive fallback: returns first 10 chars when parsing fails
        assert len(local_date("not-a-timestamp", "+05:30")) == 10

    # The far ends of the world's offsets: a local date runs from UTC−12 to UTC+14.

    @pytest.mark.parametrize("utc, expected", [
        ("2026-03-16T09:59:59.999Z", "2026-03-16"),   # 23:59:59 local, Mar 16
        ("2026-03-16T10:00:00.000Z", "2026-03-17"),   # midnight local, Mar 17
    ])
    def test_utc_plus_14(self, utc, expected):
        assert local_date(utc, "+14:00") == expected

    @pytest.mark.parametrize("utc, expected", [
        ("2026-03-18T11:59:59.999Z", "2026-03-17"),   # 23:59:59 local, Mar 17
        ("2026-03-18T12:00:00.000Z", "2026-03-18"),   # midnight local, Mar 18
    ])
    def test_utc_minus_12(self, utc, expected):
        assert local_date(utc, "-12:00") == expected

    def test_same_instant_is_two_days_apart_at_the_extremes(self):
        instant = "2026-03-17T11:00:00.000Z"
        assert (local_date(instant, "-12:00"), local_date(instant, "+14:00")) == ("2026-03-16", "2026-03-18")

    @pytest.mark.parametrize("utc, offset, expected", [
        ("2026-03-16T18:15:00.000Z", "+05:45", "2026-03-17"),   # Nepal midnight
        ("2026-03-16T11:15:00.000Z", "+12:45", "2026-03-17"),   # Chatham Islands midnight
        ("2026-03-17T03:29:59.000Z", "-03:30", "2026-03-16"),   # Newfoundland, a second to midnight
    ])
    def test_odd_offsets(self, utc, offset, expected):
        assert local_date(utc, offset) == expected

    # Daylight saving: each record carries the offset in force at that moment, so the
    # date follows that offset — never this machine's zone or a fixed one.

    @pytest.mark.parametrize("utc, offset, expected", [
        # US spring forward, 2026-03-08 02:00 EST → 03:00 EDT
        ("2026-03-08T04:30:00.000Z", "-05:00", "2026-03-07"),   # 23:30 EST, the night before
        ("2026-03-08T04:30:00.000Z", "-04:00", "2026-03-08"),   # same instant read as EDT
        ("2026-03-08T06:59:59.000Z", "-05:00", "2026-03-08"),   # 01:59:59 EST, last second before
        ("2026-03-08T07:00:00.000Z", "-04:00", "2026-03-08"),   # 03:00 EDT, first second after
        # US fall back, 2026-11-01 02:00 EDT → 01:00 EST (01:xx happens twice)
        ("2026-11-01T05:30:00.000Z", "-04:00", "2026-11-01"),   # first 01:30
        ("2026-11-01T06:30:00.000Z", "-05:00", "2026-11-01"),   # second 01:30
        ("2026-11-01T04:30:00.000Z", "-04:00", "2026-11-01"),   # 00:30 EDT
        ("2026-11-01T04:30:00.000Z", "-05:00", "2026-10-31"),   # same instant, a wrong offset → day before
        # UK spring forward, 2026-03-29 01:00 GMT → 02:00 BST
        ("2026-03-28T23:30:00.000Z", "+01:00", "2026-03-29"),
        ("2026-03-28T23:30:00.000Z", "+00:00", "2026-03-28"),
    ])
    def test_dst_transitions_follow_the_records_offset(self, utc, offset, expected):
        assert local_date(utc, offset) == expected


class TestParseRecoveryResponse:
    def test_parses_valid_response(self, sample_whoop_recovery):
        result = _parse_recovery_response(sample_whoop_recovery, {67890: "2026-03-17"})
        assert result is not None
        assert result["cycle_id"] == 12345
        assert result["recovery_score"] == 72.0
        assert result["hrv_rmssd_milli"] == 55.3
        assert result["resting_heart_rate"] == 58.0
        assert result["spo2"] == 97.5
        assert result["skin_temp"] == 33.2
        assert result["date"] == "2026-03-17"

    def test_returns_none_for_no_score(self):
        assert _parse_recovery_response({"cycle_id": 1}, {}) is None

    def test_returns_none_for_no_cycle_id(self):
        assert _parse_recovery_response({"score": {"recovery_score": 50}}, {}) is None

    def test_handles_missing_optional_fields(self):
        raw = {
            "cycle_id": 1,
            "score": {"recovery_score": 50.0, "hrv_rmssd_milli": 40.0,
                       "resting_heart_rate": 60.0},
            "created_at": "2026-03-17T06:00:00Z",
        }
        result = _parse_recovery_response(raw, {})
        assert result is not None
        assert result["spo2"] is None
        assert result["skin_temp"] is None

    def test_date_is_its_sleeps_local_date_not_utc(self, sample_whoop_recovery):
        """India: created 23:10 UTC Mar 16 = 04:40 Mar 17 local; the night it scores is Mar 17's."""
        raw = {**sample_whoop_recovery, "created_at": "2026-03-16T23:10:00.000Z"}
        assert _parse_recovery_response(raw, {67890: "2026-03-17"})["date"] == "2026-03-17"

    def test_unknown_sleep_falls_back_to_created_at_date(self, sample_whoop_recovery, caplog):
        result = _parse_recovery_response(sample_whoop_recovery, {"some-other-sleep": "2026-03-20"})
        assert result["date"] == "2026-03-17"
        assert "no known sleep" in caplog.text


class TestParseSleepResponse:
    def test_parses_valid_response(self, sample_whoop_sleep):
        result = _parse_sleep_response(sample_whoop_sleep)
        assert result is not None
        assert result["sleep_id"] == 67890
        assert result["date"] == "2026-03-17"
        assert result["deep_sleep_ms"] == 5400000
        assert result["rem_sleep_ms"] == 7200000
        assert result["sleep_efficiency"] == 92.5
        assert result["sleep_cycle_count"] == 5
        assert result["sleep_needed_baseline_ms"] == 28800000

    def test_date_is_local_end_date_not_utc(self, sample_whoop_sleep):
        """Night ending 04:00 in India (22:30 UTC the day before) belongs to the local date."""
        raw = {**sample_whoop_sleep, "end": "2026-03-16T22:30:00.000Z", "timezone_offset": "+05:30"}
        assert _parse_sleep_response(raw)["date"] == "2026-03-17"

    def test_returns_none_for_no_score(self):
        assert _parse_sleep_response({"id": 1}) is None

    def test_returns_none_for_no_id(self):
        assert _parse_sleep_response({"score": {}}) is None

    def test_parses_nap_true(self, sample_whoop_sleep):
        assert _parse_sleep_response({**sample_whoop_sleep, "nap": True})["nap"] is True

    def test_parses_nap_false(self, sample_whoop_sleep):
        assert _parse_sleep_response({**sample_whoop_sleep, "nap": False})["nap"] is False

    def test_missing_nap_is_unknown(self, sample_whoop_sleep):
        """No nap field → None (unknown), never silently False."""
        assert _parse_sleep_response(sample_whoop_sleep)["nap"] is None

    def test_non_boolean_nap_is_unknown(self, sample_whoop_sleep):
        assert _parse_sleep_response({**sample_whoop_sleep, "nap": "yes"})["nap"] is None

    def test_handles_missing_stage_summary(self):
        raw = {
            "id": 1,
            "end": "2026-03-17T07:00:00Z",
            "score": {"sleep_efficiency_percentage": 90.0},
        }
        result = _parse_sleep_response(raw)
        assert result is not None
        assert result["deep_sleep_ms"] is None


class TestPaginatedGet:
    @patch("whoop.client.httpx.get")
    def test_single_page(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "records": [{"id": 1}, {"id": 2}],
            "next_token": None,
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = _paginated_get("token", "https://api.example.com/v1/data")
        assert len(results) == 2
        mock_get.assert_called_once()

    @patch("whoop.client.httpx.get")
    def test_multiple_pages(self, mock_get):
        page1 = MagicMock()
        page1.json.return_value = {
            "records": [{"id": 1}],
            "next_token": "abc123",
        }
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.json.return_value = {
            "records": [{"id": 2}],
            "next_token": None,
        }
        page2.raise_for_status = MagicMock()

        mock_get.side_effect = [page1, page2]
        results = _paginated_get("token", "https://api.example.com/v1/data")
        assert len(results) == 2
        assert mock_get.call_count == 2

    @patch("whoop.client.httpx.get")
    def test_empty_results(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"records": [], "next_token": None}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = _paginated_get("token", "https://api.example.com/v1/data")
        assert results == []


class TestGetRecordsNearDate:
    @staticmethod
    def _api(recoveries, sleeps):
        """Fake _paginated_get: answers the recovery and sleep endpoints."""
        def fake(token, endpoint, params=None):
            return recoveries if endpoint.endswith("/v2/recovery") else sleeps
        return fake

    @patch("whoop.client._paginated_get")
    def test_returns_the_dates_recovery_and_sleep(self, mock_paginate, sample_whoop_recovery, sample_whoop_sleep):
        mock_paginate.side_effect = self._api([sample_whoop_recovery], [sample_whoop_sleep])
        result = get_records_near_date("token", "2026-03-17")
        assert [(r["cycle_id"], r["date"]) for r in result["recoveries"]] == [(12345, "2026-03-17")]
        assert [(s["sleep_id"], s["date"]) for s in result["sleeps"]] == [(67890, "2026-03-17")]

    @patch("whoop.client._paginated_get")
    def test_nothing_found(self, mock_paginate):
        mock_paginate.side_effect = self._api([], [])
        assert get_records_near_date("token", "2026-03-17") == {"recoveries": [], "sleeps": []}

    @patch("whoop.client._paginated_get")
    def test_window_reaches_every_time_zone(self, mock_paginate):
        """The whole of local Mar 17 anywhere on Earth: from 00:00 at UTC+14 to 23:59:59 at UTC−12."""
        mock_paginate.side_effect = self._api([], [])
        get_records_near_date("token", "2026-03-17")
        earliest = datetime(2026, 3, 17, tzinfo=timezone(timedelta(hours=14)))
        latest = datetime(2026, 3, 17, 23, 59, 59, tzinfo=timezone(timedelta(hours=-12)))
        assert len(mock_paginate.call_args_list) == 2
        for call in mock_paginate.call_args_list:
            params = call.kwargs.get("params") or call.args[2]
            start = datetime.fromisoformat(params["start"])
            end = datetime.fromisoformat(params["end"])
            assert start.tzinfo is not None and end.tzinfo is not None
            assert start <= earliest
            assert end >= latest

    @patch("whoop.client._paginated_get")
    def test_india_night_ending_before_0530_gets_its_local_date(
        self, mock_paginate, sample_whoop_recovery, sample_whoop_sleep,
    ):
        sleep = {**sample_whoop_sleep, "end": "2026-03-16T22:30:00.000Z", "timezone_offset": "+05:30"}
        recovery = {**sample_whoop_recovery, "created_at": "2026-03-16T23:00:00.000Z"}
        mock_paginate.side_effect = self._api([recovery], [sleep])
        result = get_records_near_date("token", "2026-03-17")
        assert [r["date"] for r in result["recoveries"]] == ["2026-03-17"]
        assert [s["date"] for s in result["sleeps"]] == ["2026-03-17"]

    @patch("whoop.client._paginated_get")
    def test_returns_every_sleep_record(self, mock_paginate, sample_whoop_sleep):
        """A nap and the night on the same date are both returned, not just the first."""
        nap = {**sample_whoop_sleep, "id": "nap-1", "nap": True}
        night = {**sample_whoop_sleep, "id": "night-1", "nap": False}
        mock_paginate.side_effect = self._api([], [nap, night])
        result = get_records_near_date("token", "2026-03-17")
        assert [(r["sleep_id"], r["nap"]) for r in result["sleeps"]] == [("nap-1", True), ("night-1", False)]

    @patch("whoop.client._paginated_get")
    def test_keeps_neighbouring_dates_each_with_its_own_date(
        self, mock_paginate, sample_whoop_recovery, sample_whoop_sleep,
    ):
        """The sync stores the whole window so neighbouring rows can move to their local dates."""
        other_sleep = {**sample_whoop_sleep, "id": "other", "end": "2026-03-18T11:00:00.000Z"}
        other_recovery = {**sample_whoop_recovery, "cycle_id": 2, "sleep_id": "other"}
        mock_paginate.side_effect = self._api([sample_whoop_recovery, other_recovery],
                                              [sample_whoop_sleep, other_sleep])
        result = get_records_near_date("token", "2026-03-17")
        assert {r["sleep_id"]: r["date"] for r in result["sleeps"]} == {67890: "2026-03-17", "other": "2026-03-18"}
        assert {r["cycle_id"]: r["date"] for r in result["recoveries"]} == {12345: "2026-03-17", 2: "2026-03-18"}

    @patch("whoop.client._paginated_get")
    def test_drops_unscored_and_undated_records(self, mock_paginate, sample_whoop_recovery, sample_whoop_sleep):
        unscored = {**sample_whoop_sleep, "id": "pending", "score": {}}
        undated = {**sample_whoop_sleep, "id": "no-end", "end": ""}
        mock_paginate.side_effect = self._api([{**sample_whoop_recovery, "score": {}}],
                                              [sample_whoop_sleep, unscored, undated])
        result = get_records_near_date("token", "2026-03-17")
        assert [s["sleep_id"] for s in result["sleeps"]] == [67890]
        assert result["recoveries"] == []


class TestGetAllRecords:
    @patch("whoop.client._paginated_get")
    def test_asks_for_everything_and_dates_like_the_window(
        self, mock_paginate, sample_whoop_recovery, sample_whoop_sleep,
    ):
        mock_paginate.side_effect = TestGetRecordsNearDate._api([sample_whoop_recovery], [sample_whoop_sleep])
        result = get_all_records("token")
        assert [c.kwargs["params"] for c in mock_paginate.call_args_list] == [{}, {}]
        assert [(r["cycle_id"], r["date"]) for r in result["recoveries"]] == [(12345, "2026-03-17")]
        assert [(s["sleep_id"], s["date"]) for s in result["sleeps"]] == [(67890, "2026-03-17")]
