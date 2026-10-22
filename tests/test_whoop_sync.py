"""Tests for whoop/sync.py — orchestration of WHOOP data pull and storage."""

from unittest.mock import patch

import pytest

from db import queries
from whoop.client import _parse_recovery_response, _parse_sleep_response
from whoop.sync import sync_date, sync_full_history, sync_today


class TestSyncDate:
    @patch("whoop.sync.get_records_for_date")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_stores_recovery_and_sleep(
        self, mock_token, mock_records, db_conn,
        sample_whoop_recovery, sample_whoop_sleep,
    ):
        mock_records.return_value = {
            "recoveries": [_parse_recovery_response(sample_whoop_recovery, {67890: "2026-03-17"})],
            "sleeps": [_parse_sleep_response(sample_whoop_sleep)],
        }

        result = sync_date(db_conn, "2026-03-17")
        assert result["recovery"] is True
        assert result["sleep"] is True

        recovery = queries.get_recovery_by_date(db_conn, "2026-03-17")
        assert recovery is not None
        assert recovery["recovery_score"] == 72.0

        sleep = queries.get_sleep_by_date(db_conn, "2026-03-17")
        assert sleep is not None
        assert sleep["deep_sleep_ms"] == 5400000
        assert sleep["recovery_cycle_id"] == 12345

    @patch("whoop.sync.get_records_for_date")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_stores_every_sleep_record_with_nap_flag(
        self, mock_token, mock_records, db_conn, sample_whoop_sleep,
    ):
        """Nap + night on one date: both stored, each with its own nap flag."""
        mock_records.return_value = {"recoveries": [], "sleeps": [
            _parse_sleep_response({**sample_whoop_sleep, "id": "nap", "nap": True}),
            _parse_sleep_response({**sample_whoop_sleep, "id": "night", "nap": False}),
        ]}
        sync_date(db_conn, "2026-03-17")
        rows = queries.get_sleeps_in_range(db_conn, "2026-03-17", "2026-03-17")
        assert {r["sleep_id"]: r["nap"] for r in rows} == {"nap": 1, "night": 0}

    @patch("whoop.sync.get_records_for_date", return_value={"recoveries": [], "sleeps": []})
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_handles_no_data(self, mock_token, mock_records, db_conn):
        result = sync_date(db_conn, "2026-03-17")
        assert result["recovery"] is False
        assert result["sleep"] is False

    @patch("whoop.sync.get_valid_token")
    def test_sync_today_calls_sync_date(self, mock_token, db_conn):
        mock_token.return_value = "test_token"
        with patch("whoop.sync.get_records_for_date", return_value={"recoveries": [], "sleeps": []}):
            result = sync_today(db_conn)
            assert "recovery" in result
            assert "sleep" in result


def _fake_api(recoveries, sleeps):
    """Fake _paginated_get answering the recovery and sleep endpoints."""
    def fake(token, endpoint, params=None):
        return recoveries if endpoint.endswith("/v2/recovery") else sleeps
    return fake


def _night(sample_sleep, sample_recovery, n, end_utc, offset, score=50.0):
    """One API night: sleep `s{n}` + its recovery (cycle n)."""
    sleep = {**sample_sleep, "id": f"s{n}", "cycle_id": n, "end": end_utc,
             "timezone_offset": offset, "nap": False}
    recovery = {**sample_recovery, "cycle_id": n, "sleep_id": f"s{n}", "created_at": end_utc,
                "score": {**sample_recovery["score"], "recovery_score": score}}
    return recovery, sleep


class TestSyncFullHistory:
    @patch("whoop.sync._paginated_get")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_stores_nap_flag(self, mock_token, mock_paginate, db_conn, sample_whoop_sleep):
        """Full history sync carries WHOOP's nap flag through to the DB."""
        sleeps = [
            {**sample_whoop_sleep, "id": "nap", "nap": True},
            {**sample_whoop_sleep, "id": "night", "nap": False},
        ]
        mock_paginate.side_effect = _fake_api([], sleeps)
        counts = sync_full_history(db_conn)
        assert counts["sleep"] == 2
        rows = queries.get_sleeps_in_range(db_conn, "2026-03-17", "2026-03-17")
        assert {r["sleep_id"]: r["nap"] for r in rows} == {"nap": 1, "night": 0}

    @patch("whoop.sync._paginated_get")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_india_nights_get_one_local_date_each(
        self, mock_token, mock_paginate, db_conn, sample_whoop_sleep, sample_whoop_recovery,
    ):
        """Two India nights ending 07:00 (Mar 16) and 04:00 (Mar 17) local. Both end on Mar 16
        in UTC, so by UTC they'd share a date and one recovery would be dropped."""
        r1, s1 = _night(sample_whoop_sleep, sample_whoop_recovery, 1, "2026-03-16T01:30:00.000Z", "+05:30", 40.0)
        r2, s2 = _night(sample_whoop_sleep, sample_whoop_recovery, 2, "2026-03-16T22:30:00.000Z", "+05:30", 60.0)
        mock_paginate.side_effect = _fake_api([r2, r1], [s2, s1])
        counts = sync_full_history(db_conn)
        assert counts == {"recovery": 2, "sleep": 2}
        assert queries.get_recovery_by_date(db_conn, "2026-03-16")["cycle_id"] == 1
        assert queries.get_recovery_by_date(db_conn, "2026-03-17")["cycle_id"] == 2
        sleeps = {r["sleep_id"]: r for r in queries.get_sleeps_in_range(db_conn, "2026-03-01", "2026-03-31")}
        assert (sleeps["s1"]["date"], sleeps["s1"]["recovery_cycle_id"]) == ("2026-03-16", 1)
        assert (sleeps["s2"]["date"], sleeps["s2"]["recovery_cycle_id"]) == ("2026-03-17", 2)

    @patch("whoop.sync._paginated_get")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_resync_redates_stored_rows_without_duplicating(
        self, mock_token, mock_paginate, db_conn, sample_whoop_sleep, sample_whoop_recovery,
    ):
        """Rows stored under the old UTC dates move to their local dates, keyed by cycle / sleep id."""
        # Old UTC-dated state: both nights end before 05:30 IST, so each sat one day early.
        r1, s1 = _night(sample_whoop_sleep, sample_whoop_recovery, 1, "2026-03-16T22:30:00.000Z", "+05:30")
        r2, s2 = _night(sample_whoop_sleep, sample_whoop_recovery, 2, "2026-03-17T22:00:00.000Z", "+05:30")
        for cycle_id, d in [(1, "2026-03-16"), (2, "2026-03-17")]:
            queries.upsert_whoop_recovery(db_conn, cycle_id=cycle_id, date=d, recovery_score=50.0,
                                          hrv_rmssd_milli=50.0, resting_heart_rate=60.0)
            queries.upsert_whoop_sleep(db_conn, sleep_id=f"s{cycle_id}", date=d, recovery_cycle_id=cycle_id)
        mock_paginate.side_effect = _fake_api([r2, r1], [s2, s1])
        sync_full_history(db_conn)
        dates = dict(db_conn.execute("SELECT cycle_id, date FROM whoop_recovery").fetchall())
        assert dates == {1: "2026-03-17", 2: "2026-03-18"}
        sleeps = db_conn.execute("SELECT sleep_id, date, recovery_cycle_id FROM whoop_sleep ORDER BY sleep_id").fetchall()
        assert [tuple(r) for r in sleeps] == [("s1", "2026-03-17", 1), ("s2", "2026-03-18", 2)]

    @patch("whoop.sync._paginated_get")
    @patch("whoop.sync.get_valid_token", return_value="test_token")
    def test_recovery_takes_its_sleeps_date(
        self, mock_token, mock_paginate, db_conn, sample_whoop_sleep, sample_whoop_recovery,
    ):
        """WHOOP can score a recovery hours after the night (late strap sync); the night decides the date."""
        r1, s1 = _night(sample_whoop_sleep, sample_whoop_recovery, 1, "2026-03-17T11:00:00.000Z", "-04:00")
        r1["created_at"] = "2026-03-18T05:00:00.000Z"  # synced the next night (01:00 Mar 18 local)
        mock_paginate.side_effect = _fake_api([r1], [s1])
        sync_full_history(db_conn)
        assert queries.get_recovery_by_date(db_conn, "2026-03-17")["cycle_id"] == 1
