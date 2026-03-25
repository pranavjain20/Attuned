"""Map physiological state to neuro profile weights.

Given a detected state from the classifier, returns the target neuro profile
(parasympathetic, sympathetic, grounding weights) used by the query engine
to score songs via dot product against their neuro scores.
"""

from config import (
    BASELINE_CALM_ANCHOR,
    BASELINE_ENERGY_ANCHOR,
    BASELINE_Z_CLAMP,
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


def _blend_baseline_profile(z: float) -> dict[str, float]:
    """Interpolate baseline neuro profile along calm-to-energy spectrum.

    Piecewise linear: z in [-CLAMP, 0] blends calm_anchor → baseline,
    z in [0, +CLAMP] blends baseline → energy_anchor. Clamped to ±CLAMP.

    Args:
        z: Recovery delta z-score (delta / delta_sd).

    Returns:
        Neuro profile dict (para, symp, grnd) summing to 1.0.
    """
    z_clamped = max(-BASELINE_Z_CLAMP, min(BASELINE_Z_CLAMP, z))
    baseline = STATE_NEURO_PROFILES["baseline"]

    if z_clamped <= 0:
        t = (z_clamped + BASELINE_Z_CLAMP) / BASELINE_Z_CLAMP  # [-2, 0] → [0, 1]
        anchor = BASELINE_CALM_ANCHOR
        profile = {k: anchor[k] + t * (baseline[k] - anchor[k]) for k in baseline}
    else:
        t = z_clamped / BASELINE_Z_CLAMP  # [0, 2] → [0, 1]
        anchor = BASELINE_ENERGY_ANCHOR
        profile = {k: baseline[k] + t * (anchor[k] - baseline[k]) for k in baseline}

    total = sum(profile.values())
    if total > 0:
        profile = {k: v / total for k, v in profile.items()}
    return profile


def apply_recovery_delta_modifier(
    profile: dict[str, float],
    delta: float,
    delta_sd: float,
    state: str,
) -> tuple[dict[str, float], str | None]:
    """Adjust neuro profile weights based on day-over-day recovery change.

    For baseline state: continuous blending along calm-to-energy spectrum using
    recovery delta z-score (see _blend_baseline_profile). Near-zero z (|z| < 0.1)
    returns no change.

    For other non-exempt states: if the recovery delta exceeds the personal
    threshold (>1.5 SD), nudges the profile toward energy or calming.

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

    # --- Baseline: continuous blending ---
    if state == "baseline":
        if abs(z) < 0.1:
            return dict(profile), None

        blended = _blend_baseline_profile(z)
        direction = "leaning up" if z > 0 else "leaning down"
        reason = (
            f"Baseline + recovery delta {delta:+.0f}pp (z={z:.1f}) "
            f"— {direction}"
        )
        return blended, reason

    # --- Non-baseline, non-exempt: threshold-based nudge ---
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
