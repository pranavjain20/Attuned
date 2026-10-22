"""The body context the conversational DJ is given: today's Attuned score in plain words.

The user's request drives the DJ's picks; this block only calibrates them.
It follows the Attuned score (intelligence/feeling_score.py), never WHOOP's
recovery, so the DJ and the daily playlist read the body the same way.
"""

import sqlite3

from intelligence.continuous_profile import STATE_PURPOSE
from intelligence.feeling_score import compute_feeling_score

CALIBRATION = {
    "rest": ("today leans calm. Prefer settling choices (gentler, slower, warmer) "
             "within what they asked for, unless they explicitly ask for energy."),
    "grounding": ("today is close to their normal. Keep picks steady and balanced within "
                  "what they asked for; don't push calmer or harder on your own."),
    "energy": ("today has room for a lift. Within what they asked for, brighter and more "
               "upbeat choices fit, unless they ask for something calm."),
}

_HEADER = ("THEIR BODY TODAY (their Attuned score: how they're likely to feel "
           "compared with their own normal):")

_REQUEST_FIRST = ("Their request comes first: this only tunes choices where the request leaves "
                  "room, and helps you ask a smarter question when it's vague. Don't lecture "
                  "them about their health.")


def attuned_context(conn: sqlite3.Connection, date: str) -> str:
    """Plain-English body context for the DJ prompt, from the day's Attuned score.

    No score (no data yet, too little history) → says so and asks the DJ not to
    adjust for the body. Errors are not caught: a broken body context must
    surface, not quietly turn into "no data".
    """
    scored = compute_feeling_score(conn, date)
    if scored["score"] is None:
        reason = (scored["reason"] or "no reason given").rstrip(".")
        return (f"THEIR BODY TODAY: no Attuned score today ({reason}).\n"
                "Don't adjust for their body. Go by what they tell you.")

    state = scored["state"]
    # The explanation's last line restates the state ("So today leans ..."),
    # which the state line below already covers.
    why = "\n".join(f"- {line}" for line in scored["explanation"][:-1])
    return "\n".join([
        _HEADER,
        f"Attuned score: {scored['score']}/100 ({scored['band']}).",
        f"State: {scored['state_label']}, music built to {STATE_PURPOSE[state]}.",
        "Why (as their Attuned page tells them):",
        why,
        f"Calibration: {CALIBRATION[state]}",
        _REQUEST_FIRST,
    ])
