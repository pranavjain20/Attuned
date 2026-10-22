"""Tests for intelligence/signals.py — today's signals as "vs my normal" z-scores."""

import ast
import random
from datetime import date as date_cls, timedelta
from pathlib import Path

import pytest

from db.queries import upsert_whoop_recovery, upsert_whoop_sleep
from intelligence.baselines import (
    compute_sleep_debt,
    compute_sleep_debt_baseline,
    compute_sleep_efficiency_baseline,
    compute_sleep_stage_baselines,
)
from intelligence.signals import (
    SIGNALS,
    SLEEP_DEBT_POSITIVE_THRESHOLD,
    Z_CLAMP,
    _safe_z,
    compute_z_scores,
    read_day,
    z_scores,
)
from tests.test_feeling_score import HOUR, TARGET, _insert_day, _seed_history

INTELLIGENCE = Path(__file__).resolve().parent.parent / "intelligence"


def _history(conn, days=40):
    _seed_history(conn, TARGET, days)


def _today(conn, hours, eff, **kwargs):
    _insert_day(conn, TARGET, 1, total_ms=hours * HOUR, eff=eff, hrv=48, rhr=56, recovery=55, **kwargs)


# ---------------------------------------------------------------------------
# Which signals, and one read per day
# ---------------------------------------------------------------------------


class TestSignals:
    def test_eleven_signals_without_whoop_recovery(self, db_conn):
        _history(db_conn)
        _today(db_conn, 7, 88)
        z = compute_z_scores(db_conn, TARGET)
        assert set(z) == set(SIGNALS)
        assert len(SIGNALS) == 11
        assert "recovery_z" not in z and "recovery_delta_z" not in z

    def test_every_signal_present_on_a_full_day(self, db_conn):
        _history(db_conn)
        _today(db_conn, 7, 88)
        assert all(v is not None for v in compute_z_scores(db_conn, TARGET).values())

    def test_no_recovery_row_returns_empty(self, db_conn):
        _history(db_conn)
        assert compute_z_scores(db_conn, TARGET) == {}

    def test_compute_z_scores_is_z_scores_of_the_days_readings(self, db_conn):
        _history(db_conn)
        _today(db_conn, 6.5, 85)
        assert compute_z_scores(db_conn, TARGET) == z_scores(read_day(db_conn, TARGET))

    def test_total_sleep_is_the_main_sleep_vs_its_baseline(self, db_conn):
        _history(db_conn)
        _today(db_conn, 5, 85)
        stages = compute_sleep_stage_baselines(db_conn, TARGET)
        expected = _safe_z(int(5 * HOUR), stages["total_sleep_ms"]["mean"], stages["total_sleep_ms"]["sd"])
        assert compute_z_scores(db_conn, TARGET)["total_sleep_z"] == pytest.approx(expected)

    def test_short_night_gives_strongly_negative_total_sleep(self, db_conn):
        _history(db_conn)
        _today(db_conn, 3.9, 92)
        assert compute_z_scores(db_conn, TARGET)["total_sleep_z"] < -2.0

    def test_nap_does_not_change_any_sleep_signal(self, db_conn):
        _history(db_conn)
        _today(db_conn, 5, 82)
        before = compute_z_scores(db_conn, TARGET)
        upsert_whoop_sleep(db_conn, sleep_id="nap-today", date=TARGET, nap=True,
                           deep_sleep_ms=2 * HOUR, rem_sleep_ms=0, light_sleep_ms=0,
                           sleep_efficiency=99.0)
        after = compute_z_scores(db_conn, TARGET)
        for s in ("deep_sleep_z", "rem_sleep_z", "total_sleep_z", "sleep_efficiency_z", "deep_ratio_z"):
            assert after[s] == pytest.approx(before[s])

    def test_missing_stages_leave_stage_signals_empty(self, db_conn):
        _history(db_conn)
        upsert_whoop_recovery(db_conn, cycle_id=1, date=TARGET, recovery_score=50,
                              hrv_rmssd_milli=48, resting_heart_rate=56)
        upsert_whoop_sleep(db_conn, sleep_id=f"s-{TARGET}", date=TARGET, recovery_cycle_id=1, nap=False,
                           deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None, sleep_efficiency=90.0)
        z = compute_z_scores(db_conn, TARGET)
        for s in ("deep_sleep_z", "rem_sleep_z", "total_sleep_z", "deep_ratio_z"):
            assert z[s] is None
        assert z["sleep_efficiency_z"] is not None and z["hrv_z"] is not None

    def test_rhr_is_inverted(self, db_conn):
        """A lower resting heart rate than usual is good news: positive z."""
        _history(db_conn)
        _insert_day(db_conn, TARGET, 1, total_ms=7 * HOUR, eff=88, hrv=48, rhr=50, recovery=55)
        assert compute_z_scores(db_conn, TARGET)["rhr_z"] > 1.0

    def test_read_day_has_yesterday(self, db_conn):
        _history(db_conn)
        _today(db_conn, 7, 88)
        readings = read_day(db_conn, TARGET)
        yesterday = (date_cls.fromisoformat(TARGET) - timedelta(days=1)).isoformat()
        assert readings["yesterday"]["date"] == yesterday
        assert readings["recovery"]["date"] == TARGET


# ---------------------------------------------------------------------------
# Sleep efficiency: main-sleep baseline + short-night cap
# ---------------------------------------------------------------------------


class TestSleepEfficiencyBaseline:
    def test_usual_is_the_main_sleep_baseline(self, db_conn):
        _history(db_conn)
        _today(db_conn, 7, 92)
        bl = compute_sleep_efficiency_baseline(db_conn, TARGET)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == pytest.approx(
            _safe_z(92, bl["mean"], bl["sd"]))

    def test_naps_in_the_window_do_not_move_usual(self, db_conn):
        """Naps run ~99% efficient; counting them would make every night look broken."""
        _history(db_conn)
        _today(db_conn, 7, 88)
        before = compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"]
        for i in range(1, 31):
            d = (date_cls.fromisoformat(TARGET) - timedelta(days=i)).isoformat()
            upsert_whoop_sleep(db_conn, sleep_id=f"nap-{i}", date=d, nap=True, deep_sleep_ms=1,
                               rem_sleep_ms=1, light_sleep_ms=1, sleep_efficiency=99.0)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == pytest.approx(before)


class TestShortNightEfficiencyCap:
    """Under 6 h asleep, high efficiency is not good news: a short sleep is naturally unbroken."""

    def test_short_efficient_night_caps_at_zero(self, db_conn):
        _history(db_conn)
        _today(db_conn, 2.5, 99)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] == 0.0

    def test_exactly_six_hours_is_not_capped(self, db_conn):
        _history(db_conn)
        _today(db_conn, 6, 99)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] > 1.0

    def test_short_broken_night_keeps_its_negative_z(self, db_conn):
        _history(db_conn)
        _today(db_conn, 4, 75)
        bl = compute_sleep_efficiency_baseline(db_conn, TARGET)
        z = compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"]
        assert z < 0 and z == pytest.approx(_safe_z(75, bl["mean"], bl["sd"]))

    def test_missing_stages_leave_efficiency_uncapped(self, db_conn):
        """Without stage data the night's length is unknown, so no cap is applied."""
        _history(db_conn)
        _today(db_conn, 2.5, 99)
        upsert_whoop_sleep(db_conn, sleep_id=f"s-{TARGET}", date=TARGET, recovery_cycle_id=1, nap=False,
                           deep_sleep_ms=None, rem_sleep_ms=None, light_sleep_ms=None, sleep_efficiency=99.0)
        assert compute_z_scores(db_conn, TARGET)["sleep_efficiency_z"] > 1.0


class TestShortNightDeepShareCap:
    """Under 6 h asleep, a high deep-sleep share is not good news.

    Deep sleep comes early in the night, so a short night is mostly deep sleep
    by default (2026-10-18: 3.9 h, deep share z +1.84). Same cap as efficiency.
    """

    def test_short_deep_heavy_night_caps_at_zero(self, db_conn):
        _history(db_conn)
        _today(db_conn, 3.9, 90, deep_share=0.40)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] == 0.0

    def test_exactly_six_hours_is_not_capped(self, db_conn):
        _history(db_conn)
        _today(db_conn, 6, 90, deep_share=0.40)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] > 1.0

    def test_just_under_six_hours_is_capped(self, db_conn):
        _history(db_conn)
        _today(db_conn, 5.99, 90, deep_share=0.40)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] == 0.0

    def test_short_night_low_share_keeps_its_negative_z(self, db_conn):
        _history(db_conn)
        _today(db_conn, 4, 90, deep_share=0.10)
        assert compute_z_scores(db_conn, TARGET)["deep_ratio_z"] < -1.0


# ---------------------------------------------------------------------------
# Sleep debt cap: carrying more than 7 h of debt is never good news
# ---------------------------------------------------------------------------


def _seed_short_sleeper(conn, days=60, hours=5.0):
    """`days` of ~`hours`-h nights against an 8 h need: ~3 h/night of debt, ~21 h a week."""
    rng = random.Random(3)
    end = date_cls.fromisoformat(TARGET)
    for offset in range(days, 0, -1):
        d = (end - timedelta(days=offset)).isoformat()
        _insert_day(conn, d, cycle_id=20_000 + offset, total_ms=(hours + 0.3 * rng.gauss(0, 1)) * HOUR,
                    eff=88, hrv=48 + 4 * rng.gauss(0, 1), rhr=56 + rng.gauss(0, 1), recovery=50)


def _last_week(conn, hours):
    """Today and the 6 nights before it all at `hours` asleep (need is 8 h)."""
    end = date_cls.fromisoformat(TARGET)
    for offset in range(6, -1, -1):
        d = (end - timedelta(days=offset)).isoformat()
        _insert_day(conn, d, cycle_id=20_000 + offset if offset else 1, total_ms=hours * HOUR,
                    eff=88, hrv=48, rhr=56, recovery=50)


class TestSleepDebtCap:
    def test_threshold_is_seven_hours(self):
        """Design choice: ~1 h a night short over a week. No study gives this number."""
        assert SLEEP_DEBT_POSITIVE_THRESHOLD == 7.0

    def test_debt_over_threshold_but_below_usual_caps_at_zero(self, db_conn):
        """10.5 h of debt is less than this sleeper's usual ~20 h, but still not good news."""
        _seed_short_sleeper(db_conn)
        _last_week(db_conn, 6.5)
        debt, usual = compute_sleep_debt(db_conn, TARGET), compute_sleep_debt_baseline(db_conn, TARGET)
        assert debt == pytest.approx(10.5)
        assert debt < usual["mean"]                         # uncapped, this would be positive
        assert compute_z_scores(db_conn, TARGET)["sleep_debt_z"] == 0.0

    def test_debt_under_threshold_can_be_good_news(self, db_conn):
        _seed_short_sleeper(db_conn)
        _last_week(db_conn, 8.0)
        assert compute_sleep_debt(db_conn, TARGET) == 0.0
        assert compute_z_scores(db_conn, TARGET)["sleep_debt_z"] > 0

    def test_exactly_at_threshold_is_not_capped(self, db_conn):
        _seed_short_sleeper(db_conn)
        _last_week(db_conn, 7.0)
        assert compute_sleep_debt(db_conn, TARGET) == pytest.approx(SLEEP_DEBT_POSITIVE_THRESHOLD)
        assert compute_z_scores(db_conn, TARGET)["sleep_debt_z"] > 0

    def test_debt_above_usual_stays_negative(self, db_conn):
        """The cap only blocks good news; more debt than usual is still bad news."""
        _seed_short_sleeper(db_conn)
        _last_week(db_conn, 3.0)
        usual = compute_sleep_debt_baseline(db_conn, TARGET)
        z = compute_z_scores(db_conn, TARGET)["sleep_debt_z"]
        assert z < 0
        assert z == pytest.approx(-_safe_z(compute_sleep_debt(db_conn, TARGET), usual["mean"], usual["sd"]))


# ---------------------------------------------------------------------------
# _safe_z
# ---------------------------------------------------------------------------


class TestSafeZ:
    def test_normal_z_score(self):
        assert _safe_z(50, 45, 5) == pytest.approx(1.0)

    def test_negative_z_score(self):
        assert _safe_z(40, 45, 5) == pytest.approx(-1.0)

    def test_clamps_high(self):
        assert _safe_z(100, 45, 5) == Z_CLAMP

    def test_clamps_low(self):
        assert _safe_z(0, 45, 5) == -Z_CLAMP

    def test_zero_sd_returns_none(self):
        assert _safe_z(50, 45, 0) is None

    @pytest.mark.parametrize("value, mean, sd", [(None, 45, 5), (50, None, 5), (50, 45, None)])
    def test_any_missing_input_returns_none(self, value, mean, sd):
        assert _safe_z(value, mean, sd) is None


# ---------------------------------------------------------------------------
# Module structure: imports run one way, all at the top
# ---------------------------------------------------------------------------


def _imports(path: Path) -> tuple[set[str], list[str]]:
    """(modules imported at top level, modules imported inside functions)."""
    tree = ast.parse(path.read_text())
    top = {n.module for n in tree.body if isinstance(n, ast.ImportFrom)}
    nested = [n.module for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
              for n in ast.walk(f) if isinstance(n, ast.ImportFrom)]
    return top, nested


class TestModuleStructure:
    """signals → feeling_score → continuous_profile, never back up the chain."""

    @pytest.mark.parametrize("module", ["signals", "playlist_target", "feeling_score", "continuous_profile"])
    def test_no_imports_inside_functions(self, module):
        assert _imports(INTELLIGENCE / f"{module}.py")[1] == []

    def test_signals_import_neither_score_nor_profile(self):
        top, _ = _imports(INTELLIGENCE / "signals.py")
        assert not top & {"intelligence.feeling_score", "intelligence.continuous_profile"}

    def test_feeling_score_does_not_import_the_profile(self):
        top, _ = _imports(INTELLIGENCE / "feeling_score.py")
        assert "intelligence.continuous_profile" not in top

    def test_playlist_target_imports_no_scoring(self):
        top, _ = _imports(INTELLIGENCE / "playlist_target.py")
        assert not {m for m in top if m.startswith("intelligence.")}
