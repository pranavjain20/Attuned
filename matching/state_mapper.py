"""Map physiological state to neuro profile weights.

Given a detected state from the classifier, returns the target neuro profile
(parasympathetic, sympathetic, grounding weights) used by the query engine
to score songs via dot product against their neuro scores.
"""

from config import STATE_NEURO_PROFILES

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
