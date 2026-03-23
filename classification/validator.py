"""Post-classification validation layer.

Sits between merge+blend and DB upsert. Catches contradictory properties,
Essentia/LLM disagreements, and impossible neuro score combinations by
reducing confidence — never mutating properties.

Suspicious songs get lower confidence, which maps to lower weight in the
matching engine. No auto-corrections, no re-querying the LLM.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationFlag:
    """A single validation issue found on a classification."""
    rule: str
    penalty: float
    detail: str


@dataclass
class ValidationResult:
    """Result of validating a single song classification."""
    original_confidence: float
    adjusted_confidence: float
    flags: list[ValidationFlag] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Calm/energetic mood tags for mood-BPM mismatch check
# ---------------------------------------------------------------------------

_CALM_MOOD_TAGS = frozenset({
    "calm", "calming", "soothing", "peaceful", "serene", "gentle", "tranquil",
    "relaxing", "lullaby", "meditative",
})

_ENERGETIC_MOOD_TAGS = frozenset({
    "energetic", "party", "hype", "pumped", "aggressive", "intense",
    "explosive", "wild", "rave", "turnt",
})


# ---------------------------------------------------------------------------
# Check 1: Cross-property coherence
# ---------------------------------------------------------------------------

def _check_cross_property_coherence(
    classification: dict[str, Any],
) -> list[ValidationFlag]:
    """Flag contradictory property combinations."""
    flags: list[ValidationFlag] = []
    bpm = classification.get("bpm")
    energy = classification.get("energy")
    acousticness = classification.get("acousticness")
    mood_tags = classification.get("mood_tags") or []

    if isinstance(mood_tags, str):
        try:
            mood_tags = json.loads(mood_tags)
        except (json.JSONDecodeError, TypeError):
            mood_tags = []

    mood_set = frozenset(str(t).strip().lower() for t in mood_tags if t)

    # Low BPM + high energy
    if bpm is not None and energy is not None:
        if bpm < 70 and energy > 0.7:
            flags.append(ValidationFlag(
                rule="low_bpm_high_energy",
                penalty=0.10,
                detail=f"BPM={bpm} < 70 but energy={energy:.2f} > 0.7",
            ))

    # High BPM + low energy
    if bpm is not None and energy is not None:
        if bpm > 140 and energy < 0.3:
            flags.append(ValidationFlag(
                rule="high_bpm_low_energy",
                penalty=0.10,
                detail=f"BPM={bpm} > 140 but energy={energy:.2f} < 0.3",
            ))

    # High acousticness + high energy
    if acousticness is not None and energy is not None:
        if acousticness > 0.7 and energy > 0.8:
            flags.append(ValidationFlag(
                rule="high_acoustic_high_energy",
                penalty=0.08,
                detail=f"acousticness={acousticness:.2f} > 0.7 but energy={energy:.2f} > 0.8",
            ))

    # Mood-BPM mismatch
    if bpm is not None and mood_set:
        has_calm = bool(mood_set & _CALM_MOOD_TAGS)
        has_energetic = bool(mood_set & _ENERGETIC_MOOD_TAGS)
        if has_calm and bpm > 120:
            flags.append(ValidationFlag(
                rule="mood_bpm_mismatch",
                penalty=0.08,
                detail=f"Calm mood tags but BPM={bpm} > 120",
            ))
        elif has_energetic and bpm < 70:
            flags.append(ValidationFlag(
                rule="mood_bpm_mismatch",
                penalty=0.08,
                detail=f"Energetic mood tags but BPM={bpm} < 70",
            ))

    return flags


# ---------------------------------------------------------------------------
# Check 2: Essentia vs LLM disagreement
# ---------------------------------------------------------------------------

def _check_essentia_llm_disagreement(
    classification: dict[str, Any],
    essentia_energy: float | None,
    essentia_acousticness: float | None,
    llm_energy: float | None,
    llm_acousticness: float | None,
) -> list[ValidationFlag]:
    """Flag when Essentia and LLM disagree significantly on energy/acousticness.

    Compares original Essentia vs original LLM values (not merged). The merge
    logic handles correction; this flags uncertainty for confidence scoring.
    Only applies to essentia+llm songs where we have both sources' values.
    """
    flags: list[ValidationFlag] = []
    source = classification.get("classification_source", "")
    if "essentia" not in source:
        return flags

    # Energy gap
    if essentia_energy is not None and llm_energy is not None:
        gap = abs(essentia_energy - llm_energy)
        if gap > 0.3:
            flags.append(ValidationFlag(
                rule="essentia_llm_energy_gap",
                penalty=0.10,
                detail=f"Essentia energy={essentia_energy:.2f} vs LLM energy={llm_energy:.2f} (gap={gap:.2f})",
            ))

    # Acousticness gap
    if essentia_acousticness is not None and llm_acousticness is not None:
        gap = abs(essentia_acousticness - llm_acousticness)
        if gap > 0.3:
            flags.append(ValidationFlag(
                rule="essentia_llm_acousticness_gap",
                penalty=0.08,
                detail=f"Essentia acousticness={essentia_acousticness:.2f} vs LLM acousticness={llm_acousticness:.2f} (gap={gap:.2f})",
            ))

    return flags


# ---------------------------------------------------------------------------
# Check 3: Neuro score sanity
# ---------------------------------------------------------------------------

def _check_neuro_sanity(
    classification: dict[str, Any],
) -> list[ValidationFlag]:
    """Flag physiologically impossible neuro score combinations.

    Mutually exclusive: stronger rule (all_neuro_high) wins over weaker
    (para_symp_both_high).
    """
    para = classification.get("parasympathetic")
    symp = classification.get("sympathetic")
    grnd = classification.get("grounding")

    if para is None or symp is None or grnd is None:
        return []

    # All three high — stronger rule
    if para > 0.6 and symp > 0.6 and grnd > 0.6:
        return [ValidationFlag(
            rule="all_neuro_high",
            penalty=0.10,
            detail=f"All neuro scores > 0.6: para={para:.2f}, symp={symp:.2f}, grnd={grnd:.2f}",
        )]

    # Para + symp both high — weaker rule
    if para > 0.6 and symp > 0.6:
        return [ValidationFlag(
            rule="para_symp_both_high",
            penalty=0.08,
            detail=f"Both para={para:.2f} and symp={symp:.2f} > 0.6",
        )]

    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_classification(
    classification: dict[str, Any],
    essentia_energy: float | None = None,
    essentia_acousticness: float | None = None,
    llm_energy: float | None = None,
    llm_acousticness: float | None = None,
) -> ValidationResult:
    """Run all validation checks on a single classification.

    Returns ValidationResult with adjusted confidence and list of flags.
    Never mutates the input dict.
    """
    original_confidence = classification.get("confidence", 0.5)

    flags: list[ValidationFlag] = []
    flags.extend(_check_cross_property_coherence(classification))
    flags.extend(_check_essentia_llm_disagreement(
        classification, essentia_energy, essentia_acousticness,
        llm_energy, llm_acousticness,
    ))
    flags.extend(_check_neuro_sanity(classification))

    total_penalty = sum(f.penalty for f in flags)
    adjusted = max(0.0, original_confidence - total_penalty)

    return ValidationResult(
        original_confidence=original_confidence,
        adjusted_confidence=round(adjusted, 4),
        flags=flags,
    )


def validate_all_classifications(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Validate all existing classifications in the DB. Returns flagged songs.

    Used by the CLI validate-classifications command for dry-run analysis.
    Each returned dict has: spotify_uri, name, artist, original_confidence,
    adjusted_confidence, flags (list of dicts).

    Now reads essentia_energy/essentia_acousticness from the DB, so the
    Essentia-LLM disagreement check works in dry-run mode.
    """
    rows = conn.execute(
        """SELECT sc.*, s.name, s.artist
           FROM song_classifications sc
           JOIN songs s ON sc.spotify_uri = s.spotify_uri
           WHERE sc.valence IS NOT NULL"""
    ).fetchall()

    flagged: list[dict[str, Any]] = []

    for row in rows:
        d = dict(row)

        # Deserialize tags
        if d.get("mood_tags") and isinstance(d["mood_tags"], str):
            try:
                d["mood_tags"] = json.loads(d["mood_tags"])
            except (json.JSONDecodeError, TypeError):
                d["mood_tags"] = None
        if d.get("genre_tags") and isinstance(d["genre_tags"], str):
            try:
                d["genre_tags"] = json.loads(d["genre_tags"])
            except (json.JSONDecodeError, TypeError):
                d["genre_tags"] = None

        # Extract LLM energy/acousticness from raw_response
        llm_energy = None
        llm_acousticness = None
        song_name = (d.get("name") or "").lower().strip()
        song_artist = (d.get("artist") or "").lower().strip()
        if d.get("raw_response"):
            try:
                raw = json.loads(d["raw_response"])
                for song_result in raw.get("songs", []):
                    r_title = str(song_result.get("title", "")).lower().strip()
                    r_artist = str(song_result.get("artist", "")).lower().strip()
                    if r_title == song_name and r_artist == song_artist:
                        llm_energy = song_result.get("energy")
                        llm_acousticness = song_result.get("acousticness")
                        break
            except (json.JSONDecodeError, KeyError):
                pass

        result = validate_classification(
            d,
            essentia_energy=d.get("essentia_energy"),
            essentia_acousticness=d.get("essentia_acousticness"),
            llm_energy=llm_energy,
            llm_acousticness=llm_acousticness,
        )

        if result.flags:
            flagged.append({
                "spotify_uri": d["spotify_uri"],
                "name": d.get("name", ""),
                "artist": d.get("artist", ""),
                "original_confidence": result.original_confidence,
                "adjusted_confidence": result.adjusted_confidence,
                "flags": [
                    {"rule": f.rule, "penalty": f.penalty, "detail": f.detail}
                    for f in result.flags
                ],
            })

    # Sort by penalty magnitude (worst first)
    flagged.sort(key=lambda x: x["original_confidence"] - x["adjusted_confidence"], reverse=True)
    return flagged
