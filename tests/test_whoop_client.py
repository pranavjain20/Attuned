"""Tests for whoop/client.py — API calls, parsing, date derivation."""

from unittest.mock import MagicMock, patch

import pytest

from whoop.client import (
    _derive_date_from_timestamp,
    _paginated_get,
    _parse_recovery_response,
    _parse_sleep_response,
    get_recovery_for_date,
    get_sleep_for_date,
)


class TestDeriveDate:
    def test_timezone_offset_negative(self):
        assert _derive_date_from_timestamp("2026-03-17T06:30:00.000-05:00") == "2026-03-17"

    def test_timezone_offset_positive(self):
        assert _derive_date_from_timestamp("2026-03-17T23:30:00.000+05:30") == "2026-03-17"

    def test_utc_z_suffix(self):
        assert _derive_date_from_timestamp("2026-03-17T06:30:00Z") == "2026-03-17"

    def test_date_boundary_with_offset(self):
        # 2026-03-18T01:00:00 UTC, but -05:00 means local time is still Mar 17
        assert _derive_date_from_timestamp("2026-03-17T20:00:00.000-05:00") == "2026-03-17"

    def test_empty_string(self):
        assert _derive_date_from_timestamp("") == ""

    def test_malformed_timestamp_returns_truncated_fallback(self):
        # Defensive fallback: returns first 10 chars when parsing fails
        result = _derive_date_from_timestamp("not-a-timestamp")
        assert len(result) == 10

    def test_none_returns_empty(self):
        # Shouldn't normally happen but defensive
        assert _derive_date_from_timestamp(None) == ""


class TestParseRecoveryResponse:
    def test_parses_valid_response(self, sample_whoop_recovery):
        result = _parse_recovery_response(sample_whoop_recovery)
        assert result is not None
        assert result["cycle_id"] == 12345
        assert result["recovery_score"] == 72.0
        assert result["hrv_rmssd_milli"] == 55.3
        assert result["resting_heart_rate"] == 58.0
        assert result["spo2"] == 97.5
        assert result["skin_temp"] == 33.2
        assert result["date"] == "2026-03-17"

    def test_returns_none_for_no_score(self):
        assert _parse_recovery_response({"cycle_id": 1}) is None

    def test_returns_none_for_no_cycle_id(self):
        assert _parse_recovery_response({"score": {"recovery_score": 50}}) is None

    def test_handles_missing_optional_fields(self):
        raw = {
            "cycle_id": 1,
            "score": {"recovery_score": 50.0, "hrv_rmssd_milli": 40.0,
                       "resting_heart_rate": 60.0},
            "created_at": "2026-03-17T06:00:00Z",
        }
        result = _parse_recovery_response(raw)
        assert result is not None
        assert result["spo2"] is None
        assert result["skin_temp"] is None


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

    def test_returns_none_for_no_score(self):
        assert _parse_sleep_response({"id": 1}) is None

    def test_returns_none_for_no_id(self):
        assert _parse_sleep_response({"score": {}}) is None

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


class TestGetRecoveryForDate:
    @patch("whoop.client._paginated_get")
    def test_returns_matching_date(self, mock_paginate, sample_whoop_recovery):
        mock_paginate.return_value = [sample_whoop_recovery]
        result = get_recovery_for_date("token", "2026-03-17")
        assert result is not None
        assert result["date"] == "2026-03-17"

    @patch("whoop.client._paginated_get")
    def test_returns_none_when_no_match(self, mock_paginate):
        mock_paginate.return_value = []
        result = get_recovery_for_date("token", "2026-03-17")
        assert result is None


class TestGetSleepForDate:
    @patch("whoop.client._paginated_get")
    def test_returns_matching_date(self, mock_paginate, sample_whoop_sleep):
        mock_paginate.return_value = [sample_whoop_sleep]
        result = get_sleep_for_date("token", "2026-03-17")
        assert result is not None
        assert result["date"] == "2026-03-17"

    @patch("whoop.client._paginated_get")
    def test_returns_none_when_no_match(self, mock_paginate):
        mock_paginate.return_value = []
        result = get_sleep_for_date("token", "2026-03-17")
        assert result is None
