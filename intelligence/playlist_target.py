"""The playlist target for a score position, and the day's state label.

The target has three dimensions: para = calming, symp = energising, grnd =
grounding. It is a fixed function of the Attuned score's position: where today
sits among your own earlier days (0 = below every earlier day, 1 = above every
one). The position picks a point on one line:

    position 0.0  BASELINE_CALM_ANCHOR    low day: built to help you settle
    position 0.5  BASELINE_STEADY_ANCHOR  usual day: steady, keeps you level
    position 1.0  BASELINE_ENERGY_ANCHOR  high day: built to give you a lift

Between anchors it blends the two nearest in a straight line, so a lower score
always gives a calmer target, with no thresholds or jumps.

The day's label is the target's largest dimension. Because the target is a
fixed function of the position, the label is too: with the anchors in config.py
it is Rest below position ~0.29, Energy above ~0.71, Grounding in between. A
near-tie only happens right at those two points and is settled by the position,
never by day-to-day noise.

Pure functions of the position: nothing here reads the database or the score.
"""

from config import BASELINE_CALM_ANCHOR, BASELINE_ENERGY_ANCHOR, BASELINE_STEADY_ANCHOR

DIMENSIONS = ("para", "symp", "grnd")

# Dominant dimension → (state, display label). Ties: rest, then energy, then grounding.
STATES = {"para": ("rest", "Rest"), "symp": ("energy", "Energy"), "grnd": ("grounding", "Grounding")}

# What the music does on each state's days, finishing "built to …". The one wording behind
# the playlist description, the score explanation and the showcase page.
STATE_PURPOSE = {"rest": "help you settle", "energy": "give you a lift", "grounding": "keep you level"}


def profile_at(position: float) -> dict[str, float]:
    """Playlist target for a score position (0 = lowest day so far, 1 = highest).

    Straight-line blend calm → steady over [0, 0.5] and steady → energy over
    [0.5, 1]. Positions outside [0, 1] are clamped. Sums to 1.
    """
    p = max(0.0, min(1.0, position))
    if p <= 0.5:
        start, end, t = BASELINE_CALM_ANCHOR, BASELINE_STEADY_ANCHOR, p / 0.5
    else:
        start, end, t = BASELINE_STEADY_ANCHOR, BASELINE_ENERGY_ANCHOR, (p - 0.5) / 0.5
    return {k: start[k] + t * (end[k] - start[k]) for k in DIMENSIONS}


def pick_state(profile: dict[str, float]) -> tuple[str, str]:
    """Today's state = the profile's largest dimension. Ties: rest, then energy, then grounding."""
    dominant = max(DIMENSIONS, key=lambda k: profile[k])
    return STATES[dominant]
