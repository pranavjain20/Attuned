"""Map physiological state to neuro profile weights.

Given a detected state from the classifier, returns the target neuro profile
(parasympathetic, sympathetic, grounding weights) used by the query engine
to score songs via dot product against their neuro scores.
"""

from config import (
    RECOVERY_DELTA_EXEMPT_STATES,
    RECOVERY_DELTA_NUDGE,
    RECOVERY_DELTA_THRESHOLD_SD,
    STATE_NEURO_PROFILES,
)

# States that the matching engine can handle (excludes insufficient_data)
MATCHABLE_STATES = frozenset(STATE_NEURO_PROFILES.keys())


def get_state_neuro_profile(state: str) -> dict[str, float]:
    """Return neuro profile weights for a physiological state.

    Args:
        state: One of the 7 matchable states from the classifier.

    Returns:
        Dict with keys: para, symp, grnd (each 0.0-1.0).

    Raises:
        ValueError: If state is insufficient_data or unknown.
    """
    if state == "insufficient_data":
        raise ValueError(
            "Cannot generate playlist with insufficient_data — "
            "need at least 14 days of HRV data"
        )
    if state not in STATE_NEURO_PROFILES:
        raise ValueError(
            f"Unknown state '{state}'. "
            f"Valid states: {', '.join(sorted(MATCHABLE_STATES))}"
        )
    return STATE_NEURO_PROFILES[state]


def apply_recovery_delta_modifier(
    profile: dict[str, float],
    delta: float,
    delta_sd: float,
    state: str,
) -> tuple[dict[str, float], str | None]:
    """Adjust neuro profile weights based on day-over-day recovery change.

    If the recovery delta exceeds the personal threshold (>1.5 SD), nudges
    the profile toward energy (positive jump) or calming (negative drop).

    Args:
        profile: Neuro profile dict with keys para, symp, grnd.
        delta: Today's recovery minus yesterday's recovery.
        delta_sd: Standard deviation of personal recovery deltas.
        state: Detected physiological state.

    Returns:
        (adjusted_profile, reason_string_or_none). Never mutates input dict.
    """
    if state in RECOVERY_DELTA_EXEMPT_STATES:
        return dict(profile), None

    if delta_sd == 0:
        return dict(profile), None

    z = delta / delta_sd
    threshold = RECOVERY_DELTA_THRESHOLD_SD
    nudge = RECOVERY_DELTA_NUDGE

    if z > threshold:
        # Positive jump → boost sympathetic (energy)
        boost_key = "symp"
        shrink_keys = ["para", "grnd"]
        reason = (
            f"Recovery jumped {delta:+.0f}pp (z={z:.1f}), "
            f"boosting energy — your body bounced back"
        )
    elif z < -threshold:
        # Negative drop → boost parasympathetic (calming)
        boost_key = "para"
        shrink_keys = ["symp", "grnd"]
        reason = (
            f"Recovery dropped {delta:+.0f}pp (z={z:.1f}), "
            f"boosting calming — easing the transition"
        )
    else:
        return dict(profile), None

    adjusted = dict(profile)
    adjusted[boost_key] = adjusted[boost_key] + nudge

    # Subtract proportionally from the other two dimensions
    shrink_total = sum(adjusted[k] for k in shrink_keys)
    if shrink_total > 0:
        for k in shrink_keys:
            adjusted[k] -= nudge * (adjusted[k] / shrink_total)

    # Clamp to [0, 1]
    for k in adjusted:
        adjusted[k] = max(0.0, min(1.0, adjusted[k]))

    # Renormalize to sum=1.0
    total = sum(adjusted.values())
    if total > 0:
        for k in adjusted:
            adjusted[k] = adjusted[k] / total

    return adjusted, reason
