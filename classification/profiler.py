"""Neurological impact scoring for classified songs.

Computes parasympathetic, sympathetic, and grounding scores from song
properties (BPM, energy, acousticness, etc.) using sigmoid and Gaussian
functions derived from ANS research. See docs/RESEARCH.md Section 7.2.
"""

import math

# ---------------------------------------------------------------------------
# Neutral defaults — used when a property is None (unknown)
# Chosen to produce mid-range scores that don't bias toward any state.
# ---------------------------------------------------------------------------
NEUTRAL_BPM = 100
NEUTRAL_FLOAT = 0.5


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
) -> float:
    """Parasympathetic activation score (0.0–1.0, higher = more calming).

    Weights: tempo 0.35, energy 0.25, acousticness 0.10, instrumentalness 0.10,
    valence 0.10, mode 0.05, danceability 0.05.
    """
    tempo_score = sigmoid_decay(bpm, plateau_below=70, decay_above=110) * 0.35
    energy_score = (1.0 - energy) * 0.25
    acoustic_score = acousticness * 0.10
    instrum_score = instrumentalness * 0.10
    valence_score = gaussian(valence, center=0.35, sigma=0.2) * 0.10
    mode_score = (1.0 if mode == "major" else 0.5) * 0.05
    dance_score = gaussian(danceability, center=0.3, sigma=0.2) * 0.05

    return (
        tempo_score + energy_score + acoustic_score
        + instrum_score + valence_score + mode_score + dance_score
    )


def compute_sympathetic(
    bpm: float,
    energy: float,
    acousticness: float,
    instrumentalness: float,
    valence: float,
    mode: str | None,
    danceability: float,
) -> float:
    """Sympathetic activation score (0.0–1.0, higher = more energizing).

    Weights: tempo 0.35, energy 0.25, acousticness 0.10, instrumentalness 0.10,
    valence 0.10, mode 0.05, danceability 0.05.
    """
    tempo_score = sigmoid_rise(bpm, decay_below=100, plateau_above=130) * 0.35
    energy_score = energy * 0.25
    acoustic_score = (1.0 - acousticness) * 0.10
    instrum_score = (1.0 - instrumentalness) * 0.10
    valence_score = valence * 0.10
    mode_score = (0.8 if mode == "major" else 1.0) * 0.05
    dance_score = danceability * 0.05

    return (
        tempo_score + energy_score + acoustic_score
        + instrum_score + valence_score + mode_score + dance_score
    )


def compute_grounding(
    bpm: float,
    energy: float,
    acousticness: float,
    instrumentalness: float,
    valence: float,
    mode: str | None,
    danceability: float,
) -> float:
    """Emotional grounding score (0.0–1.0, higher = more grounding).

    Uses Gaussians for tempo/energy/valence/instrumentalness/danceability
    because grounding has a genuine peak (too slow loses engagement, too fast loses calm).
    """
    tempo_score = gaussian(bpm, center=85, sigma=10) * 0.30
    energy_score = gaussian(energy, center=0.35, sigma=0.15) * 0.20
    acoustic_score = acousticness * 0.15
    valence_score = gaussian(valence, center=0.45, sigma=0.2) * 0.15
    instrum_score = gaussian(instrumentalness, center=0.3, sigma=0.3) * 0.10
    mode_score = (1.0 if mode == "major" else 0.6) * 0.05
    dance_score = gaussian(danceability, center=0.4, sigma=0.2) * 0.05

    return (
        tempo_score + energy_score + acoustic_score
        + instrum_score + valence_score + mode_score + dance_score
    )


def compute_neurological_profile(
    bpm: float | int | None,
    energy: float | None,
    acousticness: float | None,
    instrumentalness: float | None,
    valence: float | None,
    mode: str | None,
    danceability: float | None,
) -> dict[str, float]:
    """Public API: compute all three neurological scores from song properties.

    Handles None inputs by substituting neutral defaults (BPM=100, floats=0.5)
    so songs with partial data still get scored. Returns dict with keys:
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
        ), 4),
        "sympathetic": round(compute_sympathetic(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
        ), 4),
        "grounding": round(compute_grounding(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
        ), 4),
    }
