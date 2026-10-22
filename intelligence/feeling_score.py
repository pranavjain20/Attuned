"""Attuned feeling score: one 0–100 number for how you're likely to feel today.

The daily playlist follows this score: its position among your own days sets
the playlist target (see intelligence/playlist_target.py).

How a day is scored:
1. Signals. Each is a z-score — how far today sits from your own last-30-day
   average, in units of your typical day-to-day wobble, clamped to ±2.5, signed
   so positive always means better. They come from intelligence/signals.py:
   sleep (efficiency, deep, REM, total, 7-night debt, deep share) and heart
   (HRV, resting heart rate, HRV's 7-day trend, both changes since yesterday).
   WHOOP's recovery is not an input (see signals.py for why).
2. Composite = weighted average of the signals present that day. Positive =
   better than your normal. No score if the signals present carry less than
   MIN_WEIGHT_SHARE of the total weight (e.g. no night's sleep recorded).
3. 0–100 by percentile matching against your own history: today's composite is
   ranked among all earlier days' composites (its position: 0 = below every
   earlier day, 1 = above every one), and the score is the WHOOP
   recovery at that same rank in those days' WHOOP recoveries. So Attuned has
   the same share of red / yellow / green days as WHOOP — same bands, same
   meaning — only which days land where differs. Only earlier days are used, so
   a day's score never changes as new data arrives.

Weights are my design choice, not a published formula. The sleep group carries
about twice the weight of the heart group (1.55 vs 0.78, ~2:1), informed by
research linking sleep to next-day mood; no study gives the ratio. Deep sleep,
REM and total sleep — the three per-night amounts — weigh the same.
"""

import logging
import math
import sqlite3
from typing import NamedTuple

import numpy as np

from config import MIN_BASELINE_DAYS
from db.queries import get_recoveries_in_range
from intelligence.dates import shift_date
from intelligence.main_sleep import asleep_ms, is_short_night
from intelligence.playlist_target import STATE_PURPOSE, pick_state, profile_at
from intelligence.signals import compute_z_scores, read_day, z_scores

logger = logging.getLogger(__name__)

# Weights: my design choice. Sleep group 1.55, heart group 0.78 → ~2:1.
FEELING_WEIGHTS: dict[str, float] = {
    "sleep_efficiency_z": 0.36,
    "deep_sleep_z": 0.30,
    "rem_sleep_z": 0.30,
    "total_sleep_z": 0.30,
    "sleep_debt_z": 0.20,
    "deep_ratio_z": 0.09,
    "hrv_z": 0.24,
    "rhr_z": 0.19,
    "hrv_trend_z": 0.15,
    "hrv_delta_z": 0.10,
    "rhr_delta_z": 0.10,
}
SLEEP_SIGNALS = frozenset({
    "sleep_efficiency_z", "deep_sleep_z", "rem_sleep_z", "total_sleep_z",
    "sleep_debt_z", "deep_ratio_z",
})
HEART_SIGNALS = frozenset({"hrv_z", "rhr_z", "hrv_trend_z", "hrv_delta_z", "rhr_delta_z"})

MIN_WEIGHT_SHARE = 0.70        # signals present must carry ≥70% of total weight
MIN_CALIBRATION_DAYS = 60      # earlier scored days needed to map onto 0–100
MIN_Z_TO_MENTION = 0.5         # smaller wobbles are noise, never named as a reason
MIN_COUNTERWEIGHT = 0.08       # contribution an opposing signal needs to be mentioned
MAX_DRIVERS = 3

BAND_ORDER = ("red", "yellow", "green")
STATE_WHY = {
    "rest": f"you're likely to feel below your normal, so the music is built to {STATE_PURPOSE['rest']}",
    "energy": f"you're likely to feel better than your normal, so the music is built to {STATE_PURPOSE['energy']}",
    "grounding": f"you're likely to feel close to your normal, so the music stays steady to {STATE_PURPOSE['grounding']}",
}
SAME_BAND_HEADLINE = {
    "green": "You should feel good today",
    "yellow": "A middle-of-the-road day",
    "red": "Expect to feel flat today",
}
HOUR_MS = 3_600_000


class SignalText(NamedTuple):
    """How one signal reads on the page."""
    label: str    # its name
    up: str       # sentence when it helped; {value} and {usual} are filled in
    down: str     # sentence when it hurt
    helped: str   # short phrase when it helped, e.g. "more REM"
    hurt: str     # short phrase when it hurt, e.g. "less REM"


# The one wording table for every signal: labels, explanation sentences and short phrases.
SIGNAL_TEXT: dict[str, SignalText] = {
    "sleep_efficiency_z": SignalText(
        "Sleep efficiency",
        "Your sleep was unbroken: asleep for {value} of your time in bed (usual {usual}).",
        "Your sleep was broken: asleep for only {value} of your time in bed (usual {usual}).",
        "less broken sleep", "more broken sleep"),
    "deep_sleep_z": SignalText(
        "Deep sleep",
        "You got {value} of deep sleep, more than your usual {usual}.",
        "You got {value} of deep sleep, less than your usual {usual}.",
        "more deep sleep", "less deep sleep"),
    "rem_sleep_z": SignalText(
        "REM sleep",
        "You got {value} of REM sleep, more than your usual {usual}.",
        "You got {value} of REM sleep, less than your usual {usual}.",
        "more REM", "less REM"),
    "total_sleep_z": SignalText(
        "Total sleep",
        "You slept {value}, more than your usual {usual}.",
        "You slept {value}, less than your usual {usual}.",
        "a longer night", "a shorter night"),
    "sleep_debt_z": SignalText(
        "Sleep debt (7 nights)",
        "Over the past 7 nights you've carried less sleep debt than usual ({value} vs {usual}).",
        "Over the past 7 nights you've built up {value} of sleep debt, more than your usual {usual}.",
        "less sleep debt", "built-up sleep debt"),
    "deep_ratio_z": SignalText(
        "Deep sleep share",
        "Deep sleep made up {value} of your night, above your usual {usual}.",
        "Deep sleep made up {value} of your night, below your usual {usual}.",
        "a bigger share of deep sleep", "a smaller share of deep sleep"),
    "hrv_z": SignalText(
        "HRV",
        "Your HRV was {value}, above your usual {usual}.",
        "Your HRV was {value}, below your usual {usual}.",
        "a higher HRV", "a lower HRV"),
    # Resting heart rate is inverted: below your usual is the good direction.
    "rhr_z": SignalText(
        "Resting heart rate",
        "Your resting heart rate was {value}, below your usual {usual}.",
        "Your resting heart rate was {value}, above your usual {usual}.",
        "a lower resting heart rate", "a higher resting heart rate"),
    "hrv_trend_z": SignalText(
        "HRV trend (7 days)",
        "Your HRV has been climbing over the past week ({value}).",
        "Your HRV has been drifting down over the past week ({value}).",
        "HRV trending up this week", "HRV drifting down this week"),
    "hrv_delta_z": SignalText(
        "HRV change since yesterday",
        "Your HRV rose to {value} from {usual}.",
        "Your HRV fell to {value} from {usual}.",
        "HRV up since yesterday", "HRV down since yesterday"),
    "rhr_delta_z": SignalText(
        "Resting HR change since yesterday",
        "Your resting heart rate dropped to {value} from {usual}.",
        "Your resting heart rate rose to {value} from {usual}.",
        "resting heart rate down since yesterday", "resting heart rate up since yesterday"),
}

# {signal: (when it helped, when it hurt)} — how each signal reads in a short phrase.
SIGNAL_PHRASES: dict[str, tuple[str, str]] = {s: (t.helped, t.hurt) for s, t in SIGNAL_TEXT.items()}


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

def compute_composite(z: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    """Weighted average of the z-scores present, plus each signal's share of it.

    Returns (composite, contributions) where contributions sum to composite, or
    (None, {}) if the signals present carry less than MIN_WEIGHT_SHARE of the weight.
    """
    present = {s: z[s] for s in FEELING_WEIGHTS if z.get(s) is not None}
    present_weight = sum(FEELING_WEIGHTS[s] for s in present)
    if present_weight < MIN_WEIGHT_SHARE * sum(FEELING_WEIGHTS.values()):
        return None, {}
    contributions = {s: FEELING_WEIGHTS[s] * v / present_weight for s, v in present.items()}
    return sum(contributions.values()), contributions


def compute_composite_history(conn: sqlite3.Connection, before_date: str) -> dict[str, dict]:
    """Composite and WHOOP recovery for every WHOOP day strictly before `before_date`.

    Returns {date: {"composite": float | None, "recovery": float | None}}.
    """
    first = conn.execute("SELECT MIN(date) FROM whoop_recovery").fetchone()[0]
    if first is None:
        return {}
    history = {}
    for row in get_recoveries_in_range(conn, first, shift_date(before_date, -1)):
        composite, _ = compute_composite(compute_z_scores(conn, row["date"]))
        history[row["date"]] = {"composite": composite, "recovery": row["recovery_score"]}
    return history


# ---------------------------------------------------------------------------
# Mapping, band, state
# ---------------------------------------------------------------------------

def percentile_position(composite: float, ref_composites: list[float]) -> float:
    """Share of reference composites below `composite` (ties count half), 0–1.

    Raises ValueError with no reference composites: there is nothing to rank against.
    """
    if not ref_composites:
        raise ValueError("percentile_position: no reference composites to rank against")
    ranked = np.sort(np.asarray(ref_composites, dtype=np.float64))
    below = np.searchsorted(ranked, composite, "left")
    at_or_below = np.searchsorted(ranked, composite, "right")
    return float((below + at_or_below) / 2 / len(ranked))


def map_to_score(composite: float, ref_composites: list[float], ref_recoveries: list[float]) -> int:
    """Percentile-match a composite onto the 0–100 WHOOP recovery scale.

    Score = the WHOOP recovery at the composite's percentile_position among the
    reference recoveries. The two lists are the same earlier days, so they must be
    the same length; ValueError otherwise, or when empty. One reference day is
    allowed: every composite then maps to that day's recovery.
    """
    if not ref_composites:
        raise ValueError("map_to_score: no reference days to map onto")
    if len(ref_composites) != len(ref_recoveries):
        raise ValueError(f"map_to_score got {len(ref_composites)} reference composites "
                         f"but {len(ref_recoveries)} recoveries")
    rank = percentile_position(composite, ref_composites)
    return int(round(float(np.quantile(np.asarray(ref_recoveries, dtype=np.float64), rank))))


def band(score: float | None) -> str | None:
    """WHOOP's colour bands: red 0–33, yellow 34–66, green 67–100."""
    if score is None:
        return None
    if score < 34:
        return "red"
    if score < 67:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Drivers and explanation
# ---------------------------------------------------------------------------

def pick_drivers(
    contributions: dict[str, float],
    z: dict[str, float | None],
    direction: int,
) -> list[tuple[str, float]]:
    """Up to MAX_DRIVERS (signal, contribution) pairs that explain the day.

    Signals pushing `direction` (+1 up, −1 down) come first, biggest |weight × z|
    first; one strong opposing signal may take the last slot. Signals with
    |z| < MIN_Z_TO_MENTION are never named. Ties follow FEELING_WEIGHTS order.
    """
    order = list(FEELING_WEIGHTS)
    ranked = sorted(contributions.items(), key=lambda kv: (-abs(kv[1]), order.index(kv[0])))
    notable = [kv for kv in ranked if abs(z[kv[0]]) >= MIN_Z_TO_MENTION]
    agreeing = [kv for kv in notable if kv[1] * direction > 0]
    if not agreeing:
        return []
    opposing = [kv for kv in notable if kv[1] * direction < 0 and abs(kv[1]) >= MIN_COUNTERWEIGHT][:1]
    return agreeing[: MAX_DRIVERS - len(opposing)] + opposing


def _sentence(signal: str, up: bool, value: str, usual: str) -> str:
    """One fixed plain-English sentence per signal, with real numbers."""
    text = SIGNAL_TEXT[signal]
    return (text.up if up else text.down).format(value=value, usual=usual)


def _headline(attuned_band: str, whoop_band: str | None, drivers: list[dict],
              short_night: bool = False) -> str:
    """Compare with WHOOP's band when they differ; otherwise describe the band.

    Below WHOOP: "WHOOP says ready, but …" only when WHOOP is green.
    After a short night (under 6 h) sleep is never credited for a better-than-WHOOP day.
    """
    if whoop_band is None or attuned_band == whoop_band:
        return SAME_BAND_HEADLINE[attuned_band]
    led_by_sleep = bool(drivers) and drivers[0]["signal"] in SLEEP_SIGNALS
    if BAND_ORDER.index(attuned_band) < BAND_ORDER.index(whoop_band):
        cause = "your sleep" if led_by_sleep else "your body"
        # Only a green WHOOP ring says "ready"; below a yellow one, compare the numbers.
        if whoop_band == "green":
            return f"WHOOP says ready, but {cause} says go easy"
        return f"Lower than WHOOP's number: {cause} says go easy"
    credit_sleep = led_by_sleep and not short_night
    return f"Better than WHOOP's number: {'your sleep' if credit_sleep else 'your body'} held up"


def _explanation(drivers: list[dict], direction: int, state: str) -> list[str]:
    lines = []
    for d in drivers:
        text = _sentence(d["signal"], d["effect"] == "up", d["value"], d["usual"])
        if (d["effect"] == "up") != (direction > 0):
            text = "On the other side, " + text[0].lower() + text[1:]
        lines.append(text)
    if not lines:
        lines.append("Nothing stood out: your sleep and heart signals were all close to your normal.")
    lines.append(f"So today leans {state}: {STATE_WHY[state]}.")
    return lines


# ---------------------------------------------------------------------------
# Display values (real numbers for sentences and the page)
# ---------------------------------------------------------------------------

def _hours(ms: float | None) -> float | None:
    return None if ms is None else ms / HOUR_MS


def _fmt(value: float | None, pattern: str) -> str | None:
    return None if value is None else pattern.format(value)


def _day_values(readings: dict) -> dict:
    """Today's raw numbers and 'usual' numbers from the day's readings (see signals.read_day)."""
    today = readings["recovery"] or {}
    yesterday = readings["yesterday"] or {}
    night = readings["last_night"] or {}
    stages = readings["stage_baselines"]
    eff_bl, debt_bl = readings["efficiency_baseline"], readings["debt_baseline"]
    hrv_bl, rhr_bl, trend = readings["hrv_baseline"], readings["rhr_baseline"], readings["hrv_trend"]

    total = asleep_ms(night)
    return {
        "recovery": today.get("recovery_score"),
        "hrv_ms": today.get("hrv_rmssd_milli"),
        "rhr": today.get("resting_heart_rate"),
        "hrv_yesterday": yesterday.get("hrv_rmssd_milli"),
        "rhr_yesterday": yesterday.get("resting_heart_rate"),
        "total_h": _hours(total),
        "deep_h": _hours(night.get("deep_sleep_ms")) if total is not None else None,
        "rem_h": _hours(night.get("rem_sleep_ms")) if total is not None else None,
        "deep_share": night["deep_sleep_ms"] / total if total else None,
        "eff": night.get("sleep_efficiency"),
        "debt_h": readings["debt"],
        "usual_total_h": _hours(stages["total_sleep_ms"]["mean"]) if stages else None,
        "usual_deep_h": _hours(stages["deep_ms"]["mean"]) if stages else None,
        "usual_rem_h": _hours(stages["rem_ms"]["mean"]) if stages else None,
        "usual_deep_share": stages["deep_ratio"]["mean"] if stages else None,
        "usual_eff": eff_bl["mean"] if eff_bl else None,
        "usual_debt_h": debt_bl["mean"] if debt_bl else None,
        "usual_hrv_ms": math.exp(hrv_bl["mean"]) if hrv_bl else None,
        "usual_rhr": rhr_bl["mean"] if rhr_bl else None,
        "hrv_week": hrv_week_endpoints(trend) if trend else None,
    }


def hrv_week_endpoints(trend: dict) -> tuple[float, float]:
    """Start and end of the 7-day HRV trend line, in ms.

    Read off the fitted line (the slope the score uses), not the first and last
    raw days — on a zig-zag week those two can be equal or point the wrong way.
    """
    half_span = trend["slope"] * (len(trend["values"]) - 1) / 2
    return math.exp(trend["mean"] - half_span), math.exp(trend["mean"] + half_span)


def _value_and_usual(signal: str, v: dict) -> tuple[str | None, str | None]:
    hours, pct, ms, bpm = "{:.1f} h", "{:.0f}%", "{:.0f} ms", "{:.0f} bpm"
    share = lambda x: None if x is None else f"{100 * x:.0f}%"
    return {
        "sleep_efficiency_z": (_fmt(v["eff"], pct), _fmt(v["usual_eff"], pct)),
        "deep_sleep_z": (_fmt(v["deep_h"], hours), _fmt(v["usual_deep_h"], hours)),
        "rem_sleep_z": (_fmt(v["rem_h"], hours), _fmt(v["usual_rem_h"], hours)),
        "total_sleep_z": (_fmt(v["total_h"], hours), _fmt(v["usual_total_h"], hours)),
        "sleep_debt_z": (_fmt(v["debt_h"], hours), _fmt(v["usual_debt_h"], hours)),
        "deep_ratio_z": (share(v["deep_share"]), share(v["usual_deep_share"])),
        "hrv_z": (_fmt(v["hrv_ms"], ms), _fmt(v["usual_hrv_ms"], ms)),
        "rhr_z": (_fmt(v["rhr"], bpm), _fmt(v["usual_rhr"], bpm)),
        "hrv_trend_z": ("{:.0f} → {:.0f} ms".format(*v["hrv_week"]) if v["hrv_week"] else None, "steady"),
        "hrv_delta_z": (_fmt(v["hrv_ms"], ms), _fmt(v["hrv_yesterday"], ms + " yesterday")),
        "rhr_delta_z": (_fmt(v["rhr"], bpm), _fmt(v["rhr_yesterday"], bpm + " yesterday")),
    }[signal]


# ---------------------------------------------------------------------------
# The day's score
# ---------------------------------------------------------------------------

def _missing_reason(readings: dict) -> str:
    """Plain reason a day with WHOOP data still can't be scored."""
    night = readings["last_night"]
    if night is None:
        return "No night's sleep recorded for this date (naps don't count)."
    if asleep_ms(night) is None:
        return "Last night's sleep stages are missing, so the night can't be scored."
    if readings["stage_baselines"] is None or readings["hrv_baseline"] is None:
        return f"Not enough history yet: your personal normal needs at least {MIN_BASELINE_DAYS} days of data."
    return "Too many signals are missing today to give a fair score."


def locate_day(
    conn: sqlite3.Connection,
    date: str,
    history: dict[str, dict] | None = None,
) -> dict:
    """Where `date` sits among your own earlier days: the core of the score.

    `history` (from compute_composite_history) can be passed to avoid
    recomputing earlier days; only its days before `date` are used.

    Returns {"readings", "z", "composite", "contributions", "position", "score",
    "ref_composites", "whoop_recovery", "reason"}. readings is the day's raw
    data (signals.read_day). position (0–1, see percentile_position) and score
    (0–100) are None, with a plain reason, when the day can't be scored.
    """
    readings = read_day(conn, date)
    day = {"readings": readings, "z": {}, "composite": None, "contributions": {}, "position": None,
           "score": None, "ref_composites": [], "whoop_recovery": None, "reason": None}
    if readings["recovery"] is None:
        day["reason"] = f"No WHOOP data for {date} yet."
        return day
    day["whoop_recovery"] = readings["recovery"]["recovery_score"]

    day["z"] = z_scores(readings)
    composite, contributions = compute_composite(day["z"])
    day.update(composite=composite, contributions=contributions)
    if composite is None:
        day["reason"] = _missing_reason(readings)
        return day

    if history is None:
        history = compute_composite_history(conn, date)
    refs = [h for d, h in history.items() if d < date
            and h["composite"] is not None and h["recovery"] is not None]
    if len(refs) < MIN_CALIBRATION_DAYS:
        day["reason"] = (f"Not enough scored days yet to set the 0–100 scale "
                         f"(need {MIN_CALIBRATION_DAYS}, have {len(refs)}).")
        return day

    ref_composites = [h["composite"] for h in refs]
    day.update(
        position=percentile_position(composite, ref_composites),
        score=map_to_score(composite, ref_composites, [h["recovery"] for h in refs]),
        ref_composites=ref_composites,
    )
    return day


def _describe_drivers(
    picked: list[tuple[str, float]],
    z: dict[str, float | None],
    values: dict,
) -> list[dict]:
    """The picked drivers with their real numbers. A driver whose numbers are
    missing is left out (logged): a sentence must never say "None"."""
    drivers = []
    for signal, contribution in picked:
        value, usual = _value_and_usual(signal, values)
        if value is None or usual is None:
            logger.warning("No display numbers for driver %s — left out of the explanation", signal)
            continue
        drivers.append({
            "signal": signal, "label": SIGNAL_TEXT[signal].label, "value": value, "usual": usual,
            "z": round(z[signal], 2), "effect": "up" if contribution > 0 else "down",
            "contribution": round(contribution, 3),
        })
    return drivers


def _score_located_day(date: str, day: dict, values: dict) -> dict:
    """The compute_feeling_score result for a day from locate_day and its _day_values."""
    result = {
        "date": date, "score": None, "band": None, "composite": day["composite"], "position": None,
        "state": None, "state_label": None, "headline": None, "explanation": [],
        "drivers": [], "reason": day["reason"], "whoop_recovery": day["whoop_recovery"],
    }
    if day["score"] is None:
        return result

    score = day["score"]
    attuned_band, whoop_band = band(score), band(day["whoop_recovery"])
    direction = _explain_direction(day["composite"], day["ref_composites"], attuned_band, whoop_band)
    drivers = _describe_drivers(pick_drivers(day["contributions"], day["z"], direction), day["z"], values)
    state, state_label = pick_state(profile_at(day["position"]))
    result.update(
        score=score, band=attuned_band, position=day["position"], state=state, state_label=state_label,
        headline=_headline(attuned_band, whoop_band, drivers,
                           short_night=is_short_night(day["readings"]["last_night"])),
        explanation=_explanation(drivers, direction, state), drivers=drivers,
    )
    return result


def compute_feeling_score(
    conn: sqlite3.Connection,
    date: str,
    history: dict[str, dict] | None = None,
) -> dict:
    """Score one day. `history` (from compute_composite_history) can be passed to
    avoid recomputing earlier days; only its days before `date` are used.

    Returns dict with score/band (None + reason when it can't be scored),
    composite, position, state, state_label, headline, explanation, drivers,
    whoop_recovery. The state is the playlist's (see playlist_target.py).
    """
    day = locate_day(conn, date, history)
    return _score_located_day(date, day, _day_values(day["readings"]))


def _explain_direction(composite: float, ref_composites: list[float],
                       attuned_band: str, whoop_band: str | None) -> int:
    """+1 explain why the day is up, −1 why it's down.

    Bands differ from WHOOP → explain the gap. Same band → explain vs a typical
    day (the median of earlier composites).
    """
    if whoop_band is not None and attuned_band != whoop_band:
        return 1 if BAND_ORDER.index(attuned_band) > BAND_ORDER.index(whoop_band) else -1
    return 1 if composite >= float(np.median(ref_composites)) else -1


# ---------------------------------------------------------------------------
# Page data contract
# ---------------------------------------------------------------------------

def build_page_day(
    conn: sqlite3.Connection,
    date: str,
    history: dict[str, dict] | None = None,
) -> dict:
    """One day in the page data contract (see the feeling-score page). playlist is always None."""
    day = locate_day(conn, date, history)
    v = _day_values(day["readings"])
    scored = _score_located_day(date, day, v)
    rounded = lambda x, n=1: None if x is None else round(x, n)
    recovery = scored["whoop_recovery"]
    return {
        "date": date,
        "whoop": {"recovery": None if recovery is None else int(round(recovery)), "band": band(recovery)},
        "attuned": {
            "score": scored["score"], "band": scored["band"], "state": scored["state"],
            "state_label": scored["state_label"], "headline": scored["headline"],
            "explanation": scored["explanation"],
            "drivers": [{k: d[k] for k in ("signal", "label", "value", "usual", "z", "effect")}
                        for d in scored["drivers"]],
            "reason": scored["reason"],
        },
        "metrics": {
            "hrv_ms": rounded(v["hrv_ms"]), "rhr_bpm": rounded(v["rhr"], 0),
            "sleep_hours": rounded(v["total_h"], 2), "rem_hours": rounded(v["rem_h"], 2),
            "deep_hours": rounded(v["deep_h"], 2), "sleep_efficiency_pct": rounded(v["eff"]),
            "sleep_debt_hours_7d": rounded(v["debt_h"]),
        },
        "playlist": None,
    }
