"""Tests for whoop/sync.py — orchestration of WHOOP data pull and storage."""

from unittest.mock import patch

import pytest

from db import queries
from whoop.client import _parse_recovery_response, _parse_sleep_response
from whoop.sync import sync_date, sync_full_history, sync_today


class TestSyncDate:
    @patch("whoop.sync.get_sleeps_for_date")
    @patch("whoop.sync.get_recovery_for_date")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_stores_recovery_and_sleep(
        self, mock_token, mock_recovery, mock_sleep, db_conn,
        sample_whoop_recovery, sample_whoop_sleep,
    ):
        mock_recovery.return_value = _parse_recovery_response(sample_whoop_recovery)
        mock_sleep.return_value = [_parse_sleep_response(sample_whoop_sleep)]

        result = sync_date(db_conn, "2026-03-17")
        assert result["recovery"] is True
        assert result["sleep"] is True

        recovery = queries.get_recovery_by_date(db_conn, "2026-03-17")
        assert recovery is not None
        assert recovery["recovery_score"] == 72.0

        sleep = queries.get_sleep_by_date(db_conn, "2026-03-17")
        assert sleep is not None
        assert sleep["deep_sleep_ms"] == 5400000

    @patch("whoop.sync.get_sleeps_for_date")
    @patch("whoop.sync.get_recovery_for_date", return_value=None)
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_stores_every_sleep_record_with_nap_flag(
        self, mock_token, mock_recovery, mock_sleep, db_conn, sample_whoop_sleep,
    ):
        """Nap + night on one date: both stored, each with its own nap flag."""
        mock_sleep.return_value = [
            _parse_sleep_response({**sample_whoop_sleep, "id": "nap", "nap": True}),
            _parse_sleep_response({**sample_whoop_sleep, "id": "night", "nap": False}),
        ]
        sync_date(db_conn, "2026-03-17")
        rows = queries.get_sleeps_in_range(db_conn, "2026-03-17", "2026-03-17")
        assert {r["sleep_id"]: r["nap"] for r in rows} == {"nap": 1, "night": 0}

    @patch("whoop.sync.get_sleeps_for_date", return_value=[])
    @patch("whoop.sync.get_recovery_for_date", return_value=None)
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_handles_no_data(self, mock_token, mock_recovery, mock_sleep, db_conn):
        result = sync_date(db_conn, "2026-03-17")
        assert result["recovery"] is False
        assert result["sleep"] is False

    @patch("whoop.sync.get_valid_token")
    def test_sync_today_calls_sync_date(self, mock_token, db_conn):
        mock_token.return_value = "test_token"
        with patch("whoop.sync.get_recovery_for_date", return_value=None), \
             patch("whoop.sync.get_sleeps_for_date", return_value=[]):
            result = sync_today(db_conn)
            assert "recovery" in result
            assert "sleep" in result


class TestSyncFullHistory:
    @patch("whoop.sync._paginated_get")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_stores_nap_flag(self, mock_token, mock_paginate, db_conn, sample_whoop_sleep):
        """Full history sync carries WHOOP's nap flag through to the DB."""
        sleeps = [
            {**sample_whoop_sleep, "id": "nap", "nap": True},
            {**sample_whoop_sleep, "id": "night", "nap": False},
        ]
        mock_paginate.side_effect = [[], sleeps]  # recoveries, then sleeps
        counts = sync_full_history(db_conn)
        assert counts["sleep"] == 2
        rows = queries.get_sleeps_in_range(db_conn, "2026-03-17", "2026-03-17")
        assert {r["sleep_id"]: r["nap"] for r in rows} == {"nap": 1, "night": 0}
