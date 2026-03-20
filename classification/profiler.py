"""Neurological impact scoring for classified songs.

Computes parasympathetic, sympathetic, and grounding scores from song
properties (BPM, energy, acousticness, etc.) and mood tags using sigmoid
and Gaussian functions derived from ANS research.

Audio properties provide the base signal. Mood tags add a semantic dimension
orthogonal to audio — "reflective" vs "melancholy" can't be heard in BPM
or energy, but they differentiate grounding from parasympathetic.
"""

import math

from config import (
    GRND_MOOD_TAGS,
    MOOD_TAG_WEIGHT,
    PARA_MOOD_TAGS,
    SYMP_MOOD_TAGS,
)

# ---------------------------------------------------------------------------
# Neutral defaults — used when a property is None (unknown)
# Chosen to produce mid-range scores that don't bias toward any state.
# ---------------------------------------------------------------------------
NEUTRAL_BPM = 100
NEUTRAL_FLOAT = 0.5
NEUTRAL_MOOD = 0.5  # No mood tags → neutral contribution


def compute_mood_score(mood_tags: list[str] | None, target_tags: frozenset[str]) -> float:
    """Compute mood alignment score (0.0-1.0) for a set of target tags.

    Returns fraction of the song's mood tags that match the target dimension.
    No tags → NEUTRAL_MOOD (0.5) to avoid penalizing untagged songs.
    """
    if not mood_tags:
        return NEUTRAL_MOOD

    matching = sum(1 for tag in mood_tags if tag.lower() in target_tags)
    return matching / len(mood_tags)


# ---------------------------------------------------------------------------
# Primitive math functions
# ---------------------------------------------------------------------------

def sigmoid_decay(x: float, plateau_below: float, decay_above: float) -> float:
    """Monotonically decreasing sigmoid: ~1.0 below plateau, ~0.0 above decay.

    Used for parasympathetic tempo scoring (slower = better).
    midpoint = average of bounds, steepness = (range / 6) for smooth transition.
    """
    midpoint = (plateau_below + decay_above) / 2
    steepness = (decay_above - plateau_below) / 6
    if steepness == 0:
        return 1.0 if x <= midpoint else 0.0
    return 1.0 / (1.0 + math.exp((x - midpoint) / steepness))


def sigmoid_rise(x: float, decay_below: float, plateau_above: float) -> float:
    """Monotonically increasing sigmoid: ~0.0 below decay, ~1.0 above plateau.

    Used for sympathetic tempo scoring (faster = better).
    """
    midpoint = (decay_below + plateau_above) / 2
    steepness = (plateau_above - decay_below) / 6
    if steepness == 0:
        return 0.0 if x <= midpoint else 1.0
    return 1.0 / (1.0 + math.exp(-(x - midpoint) / steepness))


def gaussian(x: float, center: float, sigma: float) -> float:
    """Gaussian peak at center with spread sigma. Returns 1.0 at center, decays."""
    if sigma == 0:
        return 1.0 if x == center else 0.0
    return math.exp(-0.5 * ((x - center) / sigma) ** 2)


# ---------------------------------------------------------------------------
# Score computation — formulas from RESEARCH.md Section 7.2
# ---------------------------------------------------------------------------

def compute_parasympathetic(
    bpm: float,
    energy: float,
    acousticness: float,
    instrumentalness: float,
    valence: float,
    mode: str | None,
    danceability: float,
    mood_tags: list[str] | None = None,
) -> float:
    """Parasympathetic activation score (0.0–1.0, higher = more calming).

    Audio weights (scaled to 0.85): tempo, energy, acousticness, instrumentalness,
    valence, mode, danceability. Mood weight: 0.15.
    """
    aw = 1.0 - MOOD_TAG_WEIGHT  # audio weight scale factor

    tempo_score = sigmoid_decay(bpm, plateau_below=70, decay_above=110) * 0.35 * aw
    energy_score = (1.0 - energy) * 0.25 * aw
    acoustic_score = acousticness * 0.10 * aw
    instrum_score = instrumentalness * 0.10 * aw
    valence_score = gaussian(valence, center=0.35, sigma=0.2) * 0.10 * aw
    mode_score = (1.0 if mode == "major" else 0.5) * 0.05 * aw
    dance_score = gaussian(danceability, center=0.3, sigma=0.2) * 0.05 * aw

    mood_score = compute_mood_score(mood_tags, PARA_MOOD_TAGS) * MOOD_TAG_WEIGHT

    return (
        tempo_score + energy_score + acoustic_score
        + instrum_score + valence_score + mode_score + dance_score
        + mood_score
    )


def compute_sympathetic(
    bpm: float,
    energy: float,
    acousticness: float,
    instrumentalness: float,
    valence: float,
    mode: str | None,
    danceability: float,
    mood_tags: list[str] | None = None,
) -> float:
    """Sympathetic activation score (0.0–1.0, higher = more energizing).

    Audio weights (scaled to 0.85): tempo, energy, acousticness, instrumentalness,
    valence, mode, danceability. Mood weight: 0.15.
    """
    aw = 1.0 - MOOD_TAG_WEIGHT

    tempo_score = sigmoid_rise(bpm, decay_below=100, plateau_above=130) * 0.35 * aw
    energy_score = energy * 0.25 * aw
    acoustic_score = (1.0 - acousticness) * 0.10 * aw
    instrum_score = (1.0 - instrumentalness) * 0.10 * aw
    valence_score = valence * 0.10 * aw
    mode_score = (0.8 if mode == "major" else 1.0) * 0.05 * aw
    dance_score = danceability * 0.05 * aw

    mood_score = compute_mood_score(mood_tags, SYMP_MOOD_TAGS) * MOOD_TAG_WEIGHT

    return (
        tempo_score + energy_score + acoustic_score
        + instrum_score + valence_score + mode_score + dance_score
        + mood_score
    )


def compute_grounding(
    bpm: float,
    energy: float,
    acousticness: float,
    instrumentalness: float,
    valence: float,
    mode: str | None,
    danceability: float,
    mood_tags: list[str] | None = None,
) -> float:
    """Emotional grounding score (0.0–1.0, higher = more grounding).

    Grounding = presence of emotional content (lyrics, warmth, moderate energy).
    Distinct from parasympathetic (absence of stimulation) by:
    - Higher BPM center (90 vs para's 70 plateau) — moderate, not slow
    - Higher energy center (0.40 vs para's inverse) — engaged, not silent
    - Moderate acousticness (gaussian, not raw) — warmth, not pure quiet
    - Inverted instrumentalness — vocals/lyrics for emotional connection
    - Warmer valence center (0.55 vs para's 0.35) — emotionally present
    - Mood tags: reflective, introspective, nostalgic, romantic
    """
    aw = 1.0 - MOOD_TAG_WEIGHT

    tempo_score = gaussian(bpm, center=90, sigma=10) * 0.30 * aw
    energy_score = gaussian(energy, center=0.40, sigma=0.15) * 0.20 * aw
    acoustic_score = gaussian(acousticness, center=0.5, sigma=0.25) * 0.15 * aw
    valence_score = gaussian(valence, center=0.55, sigma=0.2) * 0.15 * aw
    instrum_score = (1.0 - instrumentalness) * 0.10 * aw
    mode_score = (1.0 if mode == "major" else 0.6) * 0.05 * aw
    dance_score = gaussian(danceability, center=0.4, sigma=0.2) * 0.05 * aw

    mood_score = compute_mood_score(mood_tags, GRND_MOOD_TAGS) * MOOD_TAG_WEIGHT

    return (
        tempo_score + energy_score + acoustic_score
        + instrum_score + valence_score + mode_score + dance_score
        + mood_score
    )


def compute_neurological_profile(
    bpm: float | int | None,
    energy: float | None,
    acousticness: float | None,
    instrumentalness: float | None,
    valence: float | None,
    mode: str | None,
    danceability: float | None,
    mood_tags: list[str] | None = None,
) -> dict[str, float]:
    """Public API: compute all three neurological scores from song properties.

    Handles None inputs by substituting neutral defaults (BPM=100, floats=0.5)
    so songs with partial data still get scored. Mood tags add semantic signal
    orthogonal to audio properties. Returns dict with keys:
    parasympathetic, sympathetic, grounding — each in [0, 1].
    """
    _bpm = float(bpm) if bpm is not None else NEUTRAL_BPM
    _energy = energy if energy is not None else NEUTRAL_FLOAT
    _acousticness = acousticness if acousticness is not None else NEUTRAL_FLOAT
    _instrumentalness = instrumentalness if instrumentalness is not None else NEUTRAL_FLOAT
    _valence = valence if valence is not None else NEUTRAL_FLOAT
    _danceability = danceability if danceability is not None else NEUTRAL_FLOAT

    return {
        "parasympathetic": round(compute_parasympathetic(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
            mood_tags,
        ), 4),
        "sympathetic": round(compute_sympathetic(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
            mood_tags,
        ), 4),
        "grounding": round(compute_grounding(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
            mood_tags,
        ), 4),
    }
