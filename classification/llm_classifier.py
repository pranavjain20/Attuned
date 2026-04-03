"""LLM-based song classification using OpenAI or Anthropic.

Classifies songs for properties that Essentia can't reliably measure:
danceability, instrumentalness, valence, mood_tags, genre_tags, and BPM
for Indian songs. Merges with existing Essentia results where available.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from classification.profiler import compute_neurological_profile
from classification.validator import validate_classification
from config import (
    LLM_BATCH_SIZE,
    LLM_MAX_RETRIES,
    LLM_MODEL_ANTHROPIC,
    LLM_MODEL_OPENAI,
    LLM_RETRY_BASE_SECONDS,
)
from db.queries import get_songs_needing_llm, upsert_song_classification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a music database. For each song, recall the precise values from music databases (Spotify, MusicBrainz, Discogs). Return factual data, not estimates.

Some songs include duration. Use it as an additional signal — e.g. if duration is 10min, it's likely devotional or ambient.

Return a JSON object with a "songs" array. Each element must have:
- "title": exact song title (for matching)
- "artist": exact artist name (for matching)
- "bpm": integer tempo in beats per minute (30-300). The measured/instrument BPM.
- "felt_tempo": integer or null. The tempo the LISTENER perceives, which may differ from measured BPM. Set this when the song has double-time percussion but the vocal/melodic phrase cycles at half speed (common in Indian devotional music with tabla), or half-time feel in hip-hop/trap. If felt tempo equals measured BPM, set to null.
- "energy": float 0.0-1.0 (perceived intensity/loudness. 0.0 = very quiet acoustic, 1.0 = loud aggressive. A soft ballad is 0.1-0.2, a club banger is 0.8-1.0)
- "acousticness": float 0.0-1.0 (how acoustic/organic vs electronic/produced. 1.0 = solo acoustic guitar or piano, 0.0 = fully electronic/synthesized)
- "danceability": float 0.0-1.0 (how suitable for dancing)
- "instrumentalness": float 0.0-1.0 (1.0 = no vocals, 0.0 = full vocals)
- "valence": float 0.0-1.0 (emotional positiveness of the FEELING the song evokes, NOT the melody)
- "mood_tags": list of 2-4 mood descriptors (e.g. ["melancholy", "introspective", "nostalgic"])
- "genre_tags": list of 2-4 genre tags (e.g. ["bollywood", "romantic", "pop"])
- "para_score": float 0.0-1.0 (how calming/parasympathetic — slow, quiet, acoustic, gentle songs score high; fast, loud, electronic songs score low)
- "symp_score": float 0.0-1.0 (how energizing/sympathetic — fast, loud, high-energy, driving songs score high; slow, quiet songs score low)
- "grounding_score": float 0.0-1.0 (how emotionally grounding — moderate tempo ~80-90 BPM, warm, acoustic, reflective songs score high; extremes of fast/slow score low)
- "original_release_year": integer or null — the year this song was ORIGINALLY released. If this is a re-release, compilation, or remaster, estimate the original year. Example: Asha Bhosle's "Jawani Jan-E-Man" was originally ~1973, even if Spotify shows 2021.
- "opening_energy": float 0.0-1.0 — energy level of the FIRST 15 SECONDS only. Use the full range:
  0.0-0.2 = opens with silence, whisper, or solo quiet instrument (e.g., Speak Now opens with quiet narration = 0.15)
  0.2-0.4 = opens with soft acoustic or gentle melody (e.g., Photograph by Ed Sheeran = 0.25)
  0.4-0.6 = opens with moderate energy, clear rhythm present (e.g., Shape of You = 0.55)
  0.6-0.8 = opens with full energy, beat drops immediately (e.g., Si Antes Te Hubiera Conocido = 0.75)
  0.8-1.0 = opens with maximum intensity, instant drop or heavy beat (e.g., Party Rock Anthem = 0.95)
  This should often DIFFER from overall energy. A song that builds slowly has low opening_energy even if average energy is high.

Valence calibration — valence measures EMOTIONAL positiveness, not melodic beauty:
- Sad, nostalgic, or melancholy songs: 0.2-0.4 even if the melody sounds beautiful (e.g. Photograph, Channa Mereya)
- Bitter, angry, or heartbreak songs: 0.1-0.3 even if acoustically gentle (e.g. Love Yourself)
- Devotional/meditative/spiritual songs: 0.2-0.4 (reverent, not "happy")
- Bittersweet or emotionally intense songs: 0.3-0.5 (not the same as positive)
- Genuinely happy, celebratory, or uplifting songs: 0.7-1.0

Rules:
- Use the FULL 0.0-1.0 range. Quiet acoustic ballads should be near 0.1, not 0.5.
- BPM must be an integer. Look up the actual BPM, don't guess from genre.
- For Indian songs: use genre tags like "bollywood", "hindi", "punjabi", "sufi", etc.
- For Bollywood/Indian music: the listed "artist" may be the composer (Pritam, A.R. Rahman) or the singer (Arijit Singh, Atif Aslam). If the listed artist alone doesn't help you identify the song, consider who the other person is (the singer if the artist is the composer, or vice versa) — that may help you recall the song's actual sound and mood.
- Return ONLY valid JSON. No markdown, no explanations."""


def _build_prompt(songs: list[dict[str, Any]]) -> str:
    """Build the user prompt listing songs to classify.

    Includes duration when available. Essentia energy/acousticness are intentionally
    NOT passed as hints — investigation showed the LLM parrots Essentia hints 96%
    of the time, creating an echo chamber. In the 54 cases where the LLM fought
    the hint, it was correct every time. Independent LLM values enable proper
    comparison during merge.
    """
    lines = ["Classify these songs:\n"]
    for i, song in enumerate(songs, 1):
        artist = song.get("artist", "Unknown")
        name = song.get("name", "Unknown")
        album = song.get("album", "")

        release_year = song.get("release_year")

        parts = [f'{i}. "{name}" by {artist}']
        if album:
            parts.append(f"(album: {album})")
        if release_year:
            parts.append(f"({release_year})")

        # Duration
        duration_ms = song.get("duration_ms")
        if duration_ms:
            dur_min = duration_ms / 60000
            parts.append(f"[duration: {dur_min:.1f}min]")

        lines.append(" ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM API calls
# ---------------------------------------------------------------------------

def _call_openai(prompt: str) -> dict[str, Any]:
    """Call OpenAI GPT-4o-mini for classification. Returns parsed JSON + raw response."""
    from config import get_openai_api_key
    from llm_client import call_openai

    raw = call_openai(
        api_key=get_openai_api_key(),
        model=LLM_MODEL_OPENAI,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=60,
    )
    parsed = json.loads(raw)
    return {"parsed": parsed, "raw_response": raw}


def _call_anthropic(prompt: str) -> dict[str, Any]:
    """Call Anthropic Claude for classification. Returns parsed JSON + raw response."""
    from config import get_anthropic_api_key
    from llm_client import call_anthropic

    raw = call_anthropic(
        api_key=get_anthropic_api_key(),
        model=LLM_MODEL_ANTHROPIC,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
        temperature=0,
        timeout=60,
    )

    # Anthropic doesn't have JSON mode — extract JSON from response
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
        else:
            raise

    return {"parsed": parsed, "raw_response": raw}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_song_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and clamp a single song's LLM result.

    Returns cleaned result dict, or None if the result is unusable.
    """
    validated: dict[str, Any] = {}

    # BPM — integer, 30-300
    bpm = result.get("bpm")
    if bpm is not None:
        try:
            bpm = int(round(float(bpm)))
            bpm = max(30, min(300, bpm))
            validated["bpm"] = bpm
        except (ValueError, TypeError):
            validated["bpm"] = None
    else:
        validated["bpm"] = None

    # Felt tempo — integer, 30-300, or None if same as BPM
    felt_tempo = result.get("felt_tempo")
    if felt_tempo is not None:
        try:
            felt_tempo = int(round(float(felt_tempo)))
            felt_tempo = max(30, min(300, felt_tempo))
            validated["felt_tempo"] = felt_tempo
        except (ValueError, TypeError):
            validated["felt_tempo"] = None
    else:
        validated["felt_tempo"] = None

    # Float properties — clamp to 0.0-1.0
    for prop in ("energy", "acousticness", "danceability", "instrumentalness",
                 "valence", "para_score", "symp_score", "grounding_score"):
        val = result.get(prop)
        if val is not None:
            try:
                val = float(val)
                val = max(0.0, min(1.0, val))
                validated[prop] = round(val, 4)
            except (ValueError, TypeError):
                validated[prop] = None
        else:
            validated[prop] = None

    # Tags — clean to list of strings
    for tag_prop in ("mood_tags", "genre_tags"):
        tags = result.get(tag_prop)
        if isinstance(tags, list):
            cleaned = [str(t).strip().lower() for t in tags if t and str(t).strip()]
            validated[tag_prop] = cleaned if cleaned else None
        else:
            validated[tag_prop] = None

    # original_release_year
    orig_year = result.get("original_release_year")
    if orig_year is not None:
        try:
            orig_year = max(1920, min(2030, int(orig_year)))
        except (ValueError, TypeError):
            orig_year = None
    validated["original_release_year"] = orig_year

    # opening_energy
    opening_energy = result.get("opening_energy")
    if opening_energy is not None:
        try:
            opening_energy = max(0.0, min(1.0, float(opening_energy)))
        except (ValueError, TypeError):
            opening_energy = None
    validated["opening_energy"] = opening_energy

    # Must have at least valence or BPM to be useful
    if validated.get("valence") is None and validated.get("bpm") is None:
        return None

    return validated


def _match_result_to_song(
    results: list[dict[str, Any]],
    song: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    """Match an LLM result back to a song by index or title/artist matching."""
    # Try positional match first
    if index < len(results):
        return results[index]

    # Fallback: title/artist match
    name_lower = song.get("name", "").lower().strip()
    artist_lower = song.get("artist", "").lower().strip()
    for r in results:
        r_title = str(r.get("title", "")).lower().strip()
        r_artist = str(r.get("artist", "")).lower().strip()
        if r_title == name_lower and r_artist == artist_lower:
            return r

    return None


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------


def _compute_confidence(
    llm_result: dict[str, Any],
    song: dict[str, Any],
) -> float:
    """Compute confidence score based on cross-validation signals.

    Since LLMs always self-report high confidence, we compute it ourselves:
    - Base confidence: 0.5 (we have a classification)
    - +0.2 if song has Essentia data at all (more data = more reliable merge)
    - +0.3 if Essentia BPM and LLM BPM agree within ±15 (cross-validated,
      after accounting for octave errors — if Essentia is 2x/0.5x of LLM,
      that's an octave error, not agreement)
    - For songs without Essentia: stays at 0.5 (LLM-only, unverified)
    """
    confidence = 0.5

    has_essentia = "essentia" in (song.get("classification_source") or "")
    if has_essentia:
        confidence += 0.2  # Has audio analysis data

        # Cross-validate BPM (using the same octave-aware logic as _pick_best_bpm)
        essentia_bpm = song.get("essentia_bpm")
        llm_bpm = llm_result.get("bpm")
        if essentia_bpm is not None and llm_bpm is not None:
            ratio = essentia_bpm / llm_bpm if llm_bpm > 0 else 0
            # Agreement: within 20% AND not an octave error
            if 0.8 < ratio < 1.2:
                confidence += 0.3  # Genuine BPM agreement = strong signal

    return round(min(1.0, confidence), 2)


def _pick_best_bpm(
    llm_bpm: int | None,
    essentia_bpm: float | None,
) -> int | None:
    """Choose the best BPM from LLM and Essentia sources.

    Strategy: LLM BPM is primary (better recall for known songs, no octave errors).
    Essentia BPM is used for cross-validation and as fallback.

    - If only one source available → use it
    - If both agree (within 20%) → average them (strongest signal)
    - If Essentia is 2x or 0.5x of LLM → octave error, trust LLM
    - If they disagree otherwise → trust LLM (broader knowledge)
    """
    if llm_bpm is None and essentia_bpm is None:
        return None
    if llm_bpm is None:
        return int(round(essentia_bpm))
    if essentia_bpm is None:
        return llm_bpm

    ratio = essentia_bpm / llm_bpm if llm_bpm > 0 else 0

    # Octave error: Essentia is 2x or 0.5x of LLM → trust LLM
    if 1.8 < ratio < 2.2 or 0.45 < ratio < 0.55:
        return llm_bpm

    # They agree (within 20%) → average for best estimate
    if 0.8 < ratio < 1.2:
        return int(round((essentia_bpm + llm_bpm) / 2))

    # Disagree but not by octave → trust LLM
    return llm_bpm


def _merge_energy(
    essentia_energy: float | None,
    llm_energy: float | None,
) -> float | None:
    """Merge Essentia and LLM energy values.

    Essentia onset rate is mostly reliable for energy. Strategy:
    - Agreement (gap <= 0.3): Essentia primary (more precise audio measurement)
    - Disagreement (gap > 0.3): blend 50/50 (neither is clearly right)
    """
    if essentia_energy is None:
        return llm_energy
    if llm_energy is None:
        return essentia_energy

    gap = abs(essentia_energy - llm_energy)
    if gap <= 0.3:
        return essentia_energy
    return round((essentia_energy + llm_energy) / 2, 4)


def _merge_acousticness(
    essentia_acousticness: float | None,
    llm_acousticness: float | None,
) -> float | None:
    """Merge Essentia and LLM acousticness values.

    Essentia spectral flatness is structurally wrong for acousticness — it
    measures tonal vs noise-like, not acoustic vs electronic. 25% of songs
    have acousticness > 0.9, including synthwave ("Blinding Lights" = 0.96).
    Strategy:
    - Agreement (gap <= 0.3): average (both sources plausible)
    - Disagreement (gap > 0.3): LLM wins (cultural knowledge beats spectral proxy)
    """
    if essentia_acousticness is None:
        return llm_acousticness
    if llm_acousticness is None:
        return essentia_acousticness

    gap = abs(essentia_acousticness - llm_acousticness)
    if gap <= 0.3:
        return round((essentia_acousticness + llm_acousticness) / 2, 4)
    return llm_acousticness


def _merge_with_essentia(
    llm_result: dict[str, Any],
    song: dict[str, Any],
) -> dict[str, Any]:
    """Merge LLM classification with existing Essentia data.

    Rules:
    - BPM: LLM primary, Essentia for cross-validation (octave error detection)
    - Key/Mode: Always Essentia when present
    - Energy: Essentia primary on agreement, blend on disagreement
    - Acousticness: Average on agreement, LLM wins on disagreement
    - Danceability/Instrumentalness/Valence/Mood/Genre: Always LLM
    """
    has_essentia = "essentia" in (song.get("classification_source") or "")
    genre_tags = llm_result.get("genre_tags")

    merged: dict[str, Any] = {
        "spotify_uri": song["spotify_uri"],
    }

    # BPM: LLM primary, cross-validated with Essentia
    essentia_bpm = song.get("essentia_bpm") if has_essentia else None
    merged["bpm"] = _pick_best_bpm(llm_result.get("bpm"), essentia_bpm)

    # Key/Mode: Essentia when available
    if has_essentia:
        merged["key"] = song.get("essentia_key")
        merged["mode"] = song.get("essentia_mode")
    else:
        merged["key"] = None
        merged["mode"] = None

    # Energy/Acousticness: smart merge when Essentia available, LLM fallback
    if has_essentia:
        merged["energy"] = _merge_energy(
            song.get("essentia_energy"), llm_result.get("energy"),
        )
        merged["acousticness"] = _merge_acousticness(
            song.get("essentia_acousticness"), llm_result.get("acousticness"),
        )
    else:
        merged["energy"] = llm_result.get("energy")
        merged["acousticness"] = llm_result.get("acousticness")

    # LLM-only properties
    merged["danceability"] = llm_result.get("danceability")
    merged["instrumentalness"] = llm_result.get("instrumentalness")
    merged["valence"] = llm_result.get("valence")
    merged["felt_tempo"] = llm_result.get("felt_tempo")
    merged["original_release_year"] = llm_result.get("original_release_year")
    merged["opening_energy"] = llm_result.get("opening_energy")
    merged["mood_tags"] = llm_result.get("mood_tags")
    merged["genre_tags"] = genre_tags
    merged["confidence"] = _compute_confidence(llm_result, song)

    # LLM direct neuro scores (for blending with formula-computed scores)
    merged["llm_para_score"] = llm_result.get("para_score")
    merged["llm_symp_score"] = llm_result.get("symp_score")
    merged["llm_grounding_score"] = llm_result.get("grounding_score")

    # Classification source
    merged["classification_source"] = "essentia+llm" if has_essentia else "llm"

    # Validate critical fields — don't block the pipeline, but make gaps visible
    missing = [f for f in ("bpm", "energy", "valence") if merged.get(f) is None]
    if missing:
        logger.warning(
            "Merge produced None for critical fields %s: %s",
            missing, merged["spotify_uri"],
        )

    return merged


# ---------------------------------------------------------------------------
# Neurological score ensemble
# ---------------------------------------------------------------------------

# Grounding tempo gaussian bias zone: BPM range where the formula structurally
# over-scores grounding due to the gaussian(bpm, 85, 10) dominating.
_GRND_BIAS_BPM_LOW = 70
_GRND_BIAS_BPM_HIGH = 110

# Energy threshold: songs below this in the GRND bias zone are quiet enough
# that the formula's GRND call is likely wrong (should be PARA/SYMP).
_QUIET_ENERGY_THRESHOLD = 0.40


def _blend_weights(formula_weight: float) -> tuple[float, float]:
    """Return (formula_weight, llm_weight) clamped to [0, 1]."""
    fw = max(0.0, min(1.0, formula_weight))
    return fw, 1.0 - fw


def _weighted_blend(
    formula_scores: dict[str, float],
    llm_scores: dict[str, float],
    formula_weight: float,
) -> dict[str, float]:
    """Blend formula and LLM scores with given formula weight."""
    fw, lw = _blend_weights(formula_weight)
    return {
        key: round(fw * formula_scores[key] + lw * llm_scores[key], 4)
        for key in formula_scores
    }


def _dominant_bucket(scores: dict[str, float]) -> str:
    """Return the key with the highest score."""
    return max(scores, key=scores.get)


def _blend_neuro_scores(
    formula_scores: dict[str, float],
    llm_para: float | None,
    llm_symp: float | None,
    llm_grounding: float | None,
    bpm: float | None = None,
    energy: float | None = None,
) -> dict[str, float]:
    """Confidence-aware ensemble combining formula and LLM direct scores.

    Uses structural knowledge about when each source is likely to fail:

    1. Agreement (both pick same bucket): high confidence, blend 50/50.
    2. Formula says GRND in the 70-110 BPM bias zone AND energy is low (<0.40):
       The formula's grounding gaussian dominates quiet songs at moderate tempo.
       The LLM has cultural context that can distinguish calming from grounding.
       Trust LLM (25% formula / 75% LLM).
    3. Formula says GRND in the bias zone AND energy is moderate/high (>=0.40):
       The song genuinely has moderate properties — grounding is plausible.
       Trust formula (70% formula / 30% LLM).
    4. Other disagreements: slight LLM preference for cultural context
       (40% formula / 60% LLM).

    Returns formula_scores unchanged if any LLM direct score is missing.
    """
    if llm_para is None or llm_symp is None or llm_grounding is None:
        return formula_scores

    llm_scores = {
        "parasympathetic": llm_para,
        "sympathetic": llm_symp,
        "grounding": llm_grounding,
    }

    frm_bucket = _dominant_bucket(formula_scores)
    llm_bucket = _dominant_bucket(llm_scores)

    # Agreement → high confidence
    if frm_bucket == llm_bucket:
        return _weighted_blend(formula_scores, llm_scores, 0.50)

    # Disagreement: use structural knowledge
    _bpm = bpm if bpm is not None else 100
    in_grnd_bias = (
        _GRND_BIAS_BPM_LOW <= _bpm <= _GRND_BIAS_BPM_HIGH
        and frm_bucket == "grounding"
    )

    if in_grnd_bias:
        if energy is not None and energy < _QUIET_ENERGY_THRESHOLD:
            # Quiet song in bias zone → formula biased, trust LLM
            return _weighted_blend(formula_scores, llm_scores, 0.25)
        else:
            # Moderate+ energy → formula's GRND call is plausible
            return _weighted_blend(formula_scores, llm_scores, 0.70)

    # Other disagreements: LLM has cultural context advantage
    return _weighted_blend(formula_scores, llm_scores, 0.40)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def classify_songs(
    conn: sqlite3.Connection,
    provider: str = "openai",
    reclassify: bool = False,
) -> dict[str, int]:
    """Classify all songs needing LLM classification.

    1. Gets work queue from get_songs_needing_llm
    2. Batches by LLM_BATCH_SIZE, calls LLM with retry
    3. Validates, merges with Essentia, computes neurological profile
    4. Upserts each classification
    5. Returns summary stats

    Args:
        conn: Database connection
        provider: "openai" or "anthropic"
        reclassify: If True, re-classify ALL eligible songs (not just unclassified)
    """
    if provider not in ("openai", "anthropic"):
        raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'anthropic'.")
    call_fn = _call_openai if provider == "openai" else _call_anthropic
    stats = {"classified": 0, "failed": 0, "skipped": 0, "batches": 0,
             "low_confidence": 0, "validation_flags": 0}

    songs = get_songs_needing_llm(conn, reclassify=reclassify)
    if not songs:
        logger.info("No songs need LLM classification")
        return stats

    total = len(songs)
    logger.info("LLM classification: %d songs to classify (provider=%s)", total, provider)

    # Process in batches
    for batch_start in range(0, total, LLM_BATCH_SIZE):
        batch = songs[batch_start:batch_start + LLM_BATCH_SIZE]
        batch_num = batch_start // LLM_BATCH_SIZE + 1
        stats["batches"] += 1

        # Retry loop for this batch
        prompt = _build_prompt(batch)
        llm_response = None

        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                llm_response = call_fn(prompt)
                break
            except Exception:
                if attempt == LLM_MAX_RETRIES:
                    logger.error(
                        "Batch %d: all %d retries failed, skipping",
                        batch_num, LLM_MAX_RETRIES, exc_info=True,
                    )
                else:
                    wait = LLM_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "Batch %d: attempt %d failed, retrying in %ds",
                        batch_num, attempt, wait, exc_info=True,
                    )
                    time.sleep(wait)

        if llm_response is None:
            stats["failed"] += len(batch)
            continue

        # Parse results
        parsed = llm_response["parsed"]
        raw_response = llm_response["raw_response"]
        results = parsed.get("songs", [])

        for i, song in enumerate(batch):
            result = _match_result_to_song(results, song, i)
            if result is None:
                logger.warning(
                    "No LLM result for: %s — %s", song["name"], song["artist"]
                )
                stats["skipped"] += 1
                continue

            validated = _validate_song_result(result)
            if validated is None:
                logger.warning(
                    "Validation failed for: %s — %s", song["name"], song["artist"]
                )
                stats["skipped"] += 1
                continue

            merged = _merge_with_essentia(validated, song)

            # Compute neurological profile from merged values.
            # Use felt_tempo for scoring when available (perceived tempo
            # matters more than measured BPM for neurological impact).
            scoring_bpm = merged.get("felt_tempo") or merged.get("bpm")
            neuro = compute_neurological_profile(
                bpm=scoring_bpm,
                energy=merged.get("energy"),
                acousticness=merged.get("acousticness"),
                instrumentalness=merged.get("instrumentalness"),
                valence=merged.get("valence"),
                mode=merged.get("mode"),
                danceability=merged.get("danceability"),
                mood_tags=merged.get("mood_tags"),
            )

            # Ensemble: combine formula + LLM direct scores using
            # structural knowledge about when each source fails
            blended = _blend_neuro_scores(
                neuro,
                merged.get("llm_para_score"),
                merged.get("llm_symp_score"),
                merged.get("llm_grounding_score"),
                bpm=merged.get("bpm"),
                energy=merged.get("energy"),
            )

            merged["parasympathetic"] = blended["parasympathetic"]
            merged["sympathetic"] = blended["sympathetic"]
            merged["grounding"] = blended["grounding"]
            merged["raw_response"] = raw_response
            merged["classified_at"] = datetime.now(timezone.utc).isoformat()

            # Post-classification validation: reduce confidence for suspicious songs
            has_essentia = "essentia" in (song.get("classification_source") or "")
            validation = validate_classification(
                merged,
                essentia_energy=song.get("essentia_energy") if has_essentia else None,
                essentia_acousticness=song.get("essentia_acousticness") if has_essentia else None,
                llm_energy=validated.get("energy"),
                llm_acousticness=validated.get("acousticness"),
            )
            if validation.flags:
                merged["confidence"] = validation.adjusted_confidence
                stats["validation_flags"] += len(validation.flags)

            upsert_song_classification(conn, merged)
            stats["classified"] += 1

            # Flag low-confidence classifications for review
            confidence = merged.get("confidence")
            if confidence is not None and confidence < 0.7:
                stats["low_confidence"] += 1
                logger.warning(
                    "Low confidence (%.2f): %s — %s",
                    confidence, song["name"], song["artist"],
                )

        # Progress logging every 10 batches
        if batch_num % 10 == 0:
            logger.info(
                "Progress: %d/%d songs (%d batches done)",
                stats["classified"] + stats["failed"] + stats["skipped"],
                total, batch_num,
            )

    logger.info(
        "LLM classification complete: %d classified, %d failed, %d skipped, "
        "%d low confidence, %d validation flags",
        stats["classified"], stats["failed"], stats["skipped"],
        stats["low_confidence"], stats["validation_flags"],
    )
    return stats
