"""Essentia-based audio feature extraction.

Analyzes audio clips to extract raw tempo readings, key, mode, energy,
acousticness, instrumentalness, and danceability. Results are stored in
song_classifications with classification_source = "essentia". Tempo readings go
to their own columns; this module never writes bpm or tempo.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from classification.audio import uri_to_filename
from classification.tempo import READING_COLUMNS
from config import TEMPOCNN_MODEL_PATH
from db.queries import (
    get_unclassified_songs,
    update_tempo_readings,
    upsert_song_classification,
)

logger = logging.getLogger(__name__)

# Valid note names for key validation
VALID_KEYS = {"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"}


def _measure_tempo(audio: Any, es: Any) -> dict[str, float | None]:
    """Read tempo with three independent trackers, each kept as reported.

    No folding, averaging or octave correction here: these are raw source
    readings. classification.tempo decides the scored tempo from them (the
    trackers' agreement gives the number, the LLM's bpm picks the octave).
    PercivalBpmEstimator is not used: on 616 real clips it returned only three
    distinct values, so it was noise, not a vote.
    """
    re_bpm, _ticks, re_confidence, _estimates, _intervals = (
        es.RhythmExtractor2013(method="multifeature")(audio)
    )
    degara_bpm = es.RhythmExtractor2013(method="degara")(audio)[0]
    return {
        "essentia_bpm": round(float(re_bpm), 2) if re_bpm > 0 else None,
        "essentia_bpm_confidence": round(float(re_confidence), 3),
        "essentia_degara_bpm": round(float(degara_bpm), 2) if degara_bpm > 0 else None,
        "tempocnn_bpm": _measure_tempocnn(audio, es),
    }


def _measure_tempocnn(audio: Any, es: Any) -> float | None:
    """TempoCNN's global tempo, or None when the model or essentia-tensorflow is missing."""
    if not TEMPOCNN_MODEL_PATH.exists():
        return None
    try:
        audio_11k = es.Resample(inputSampleRate=44100, outputSampleRate=11025)(audio)
        cnn_bpm = es.TempoCNN(graphFilename=str(TEMPOCNN_MODEL_PATH))(audio_11k)[0]
    except Exception as e:  # essentia builds without tensorflow have no TempoCNN
        logger.warning("TempoCNN unavailable: %s", e)
        return None
    return round(float(cnn_bpm), 2) if cnn_bpm > 0 else None


def _load_clip(audio_path: Path) -> tuple[Any, Any] | None:
    """Load a clip as 44.1kHz mono. Returns (audio, essentia.standard) or None."""
    try:
        import essentia.standard as es
    except ImportError:
        logger.error("essentia not installed — run: pip install essentia")
        return None

    if not audio_path.exists():
        logger.warning("Audio file not found: %s", audio_path)
        return None

    try:
        audio = es.MonoLoader(filename=str(audio_path), sampleRate=44100)()
    except Exception:
        logger.warning("Failed to load audio: %s", audio_path)
        return None

    if len(audio) < 44100:  # Less than 1 second of audio
        logger.warning("Audio too short: %s", audio_path)
        return None

    return audio, es


def measure_tempo_readings(audio_path: Path) -> dict[str, float | None] | None:
    """Only the raw tempo readings for one clip, or None if it can't be analyzed."""
    loaded = _load_clip(audio_path)
    if loaded is None:
        return None
    audio, es = loaded
    try:
        return _measure_tempo(audio, es)
    except Exception as e:
        logger.warning("Tempo measurement failed for: %s — %s", audio_path, e)
        return None


def analyze_audio(audio_path: Path) -> dict[str, Any] | None:
    """Analyze a single audio file with Essentia algorithms.

    Returns a dict of extracted features, or None if analysis fails.
    """
    loaded = _load_clip(audio_path)
    if loaded is None:
        return None
    audio, es = loaded

    try:
        # Tempo — raw readings from three trackers (see _measure_tempo)
        tempo_readings = _measure_tempo(audio, es)

        # Key + mode
        key_extractor = es.KeyExtractor()
        key, scale, _strength = key_extractor(audio)
        mode = "major" if scale == "major" else "minor"
        if key not in VALID_KEYS:
            key = None
            mode = None

        # Energy — onset rate (rhythmic attacks per second)
        # Onset rate is immune to mastering loudness (unlike RMS which was broken
        # by loud mastering — e.g. Die For You quiet R&B got energy=0.71).
        # Range: ~2 onsets/sec (calm acoustic) to ~6+ (tabla, dhol, electronic).
        # Previous RMS approach: rms = float(es.RMS()(audio)); energy = rms / 0.35
        onset_rate = float(es.OnsetRate()(audio)[1])
        energy = max(0.0, min(1.0, (onset_rate - 2.0) / 4.0))

        # Opening energy — RMS of intro relative to overall RMS.
        # Intro = first 7% of song duration (design choice: roughly the length of
        # a typical pop intro; not taken from a study). This adapts to
        # song length: ~17s for a 4-min Bollywood song, ~13s for a 3-min pop track.
        # RMS measures actual loudness. Ratio is immune to mastering differences.
        # Low ratio = song builds slowly (quiet intro). High ratio = instant energy.
        sample_rate = 44100
        intro_fraction = 0.07
        intro_samples = int(len(audio) * intro_fraction)
        intro_samples = max(intro_samples, sample_rate)  # at least 1 second
        opening_audio = audio[:intro_samples]
        import numpy as np
        rms_overall = float(np.sqrt(np.mean(audio ** 2))) if len(audio) > 0 else 0
        rms_opening = float(np.sqrt(np.mean(opening_audio ** 2))) if len(opening_audio) >= sample_rate else 0
        opening_energy_ratio = rms_opening / rms_overall if rms_overall > 0 else 1.0
        # Clamp to [0, 1] — ratio > 1 means opening is louder than average (front-loaded)
        opening_energy = max(0.0, min(1.0, opening_energy_ratio))

        # Acousticness — spectral flatness (tonal vs noise-like)
        # Low flatness = clear harmonics (acoustic instruments)
        # High flatness = noise-like spectrum (electronic production)
        # Computed as mean flatness across all frames
        windowing = es.Windowing(type="hann")
        spectrum = es.Spectrum()
        flatness = es.Flatness()
        frame_gen = es.FrameGenerator(audio, frameSize=2048, hopSize=1024)
        flatness_values = []
        for frame in frame_gen:
            windowed = windowing(frame)
            spec = spectrum(windowed)
            if spec.sum() > 0:
                flatness_values.append(float(flatness(spec)))
        avg_flatness = (
            sum(flatness_values) / len(flatness_values)
            if flatness_values else 0.0
        )
        # Map: low flatness (tonal/acoustic) → high acousticness
        # Observed range: ~0.002 (pure acoustic) to ~0.046 (electronic pop)
        # Scale factor 20 maps this range to roughly [0.08, 0.96]
        acousticness = max(0.0, min(1.0, 1.0 - avg_flatness * 20))

        # Instrumentalness — zero-crossing rate as voice proxy
        # Vocal tracks tend to have lower ZCR; instrumental/percussion higher
        # Observed range: ~0.02-0.06 for pop/Bollywood vocals
        zcr = float(es.ZeroCrossingRate()(audio))
        instrumentalness = max(0.0, min(1.0, (zcr - 0.02) / 0.08))

        # Danceability
        danceability_extractor = es.Danceability()
        danceability = float(danceability_extractor(audio)[0])
        danceability = max(0.0, min(1.0, danceability))

        return {
            **tempo_readings,
            "key": key,
            "mode": mode,
            "energy": round(energy, 4),
            "opening_energy": round(opening_energy, 4),
            "acousticness": round(acousticness, 4),
            "instrumentalness": round(instrumentalness, 4),
            "danceability": round(danceability, 4),
        }

    except Exception as e:
        logger.warning("Analysis failed for: %s — %s", audio_path, e)
        return None


def _get_songs_for_analysis(
    conn: sqlite3.Connection,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Get songs eligible for Essentia analysis.

    Default: unclassified songs only (not in song_classifications).
    Force: ALL eligible songs (play_count >= threshold), regardless of
    existing classification. Used to recompute Essentia features (e.g.,
    after switching from RMS to onset rate energy).
    """
    if force:
        from config import MIN_CLASSIFICATION_LISTENS

        rows = conn.execute(
            """SELECT s.spotify_uri, s.name, s.artist, s.album, s.duration_ms,
                      s.play_count, s.engagement_score
               FROM songs s
               WHERE s.play_count >= ?
               ORDER BY s.play_count DESC""",
            (MIN_CLASSIFICATION_LISTENS,),
        ).fetchall()
        return [dict(r) for r in rows]
    return get_unclassified_songs(conn)


def analyze_all_songs(
    conn: sqlite3.Connection,
    audio_dir: Path,
    force: bool = False,
) -> dict[str, int]:
    """Analyze songs that have audio clips.

    Default: only unclassified songs.
    Force: ALL eligible songs, recomputing Essentia features even if
    previously classified.

    Returns summary: {analyzed, failed, skipped}
    """
    stats = {"analyzed": 0, "failed": 0, "skipped": 0}

    unclassified = _get_songs_for_analysis(conn, force=force)
    if not unclassified:
        logger.info("No unclassified songs to analyze")
        return stats

    for song in unclassified:
        uri = song["spotify_uri"]
        clip_path = audio_dir / uri_to_filename(uri)

        if not clip_path.exists():
            stats["skipped"] += 1
            continue

        features = analyze_audio(clip_path)
        if features is None:
            stats["failed"] += 1
            logger.warning(
                "Analysis failed: %s — %s", song["name"], song["artist"]
            )
            continue

        # Merge Essentia features with existing data — never overwrite LLM fields
        # (valence, mood_tags, genre_tags, raw_response, etc.)
        existing = conn.execute(
            "SELECT classification_source FROM song_classifications WHERE spotify_uri = ?", (uri,)
        ).fetchone()

        existing_source = existing["classification_source"] if existing else ""
        existing_source = existing_source or ""
        new_source = existing_source if "essentia" in existing_source else (
            existing_source + "+essentia" if existing_source else "essentia"
        )
        now = datetime.now(timezone.utc).isoformat()
        # RhythmExtractor2013 confidence runs 0-5.32; the confidence column is 0-1.
        tracker_confidence = min(features["essentia_bpm_confidence"], 1.0)

        if existing:
            # UPDATE: always write raw Essentia values to essentia_* columns.
            # When LLM has already classified, only update key/mode —
            # energy/acousticness are handled by the merge logic in llm_classifier
            # (Essentia spectral flatness is structurally wrong for acousticness).
            if "llm" in existing_source:
                conn.execute(
                    """UPDATE song_classifications
                       SET key = ?, mode = ?,
                           essentia_energy = ?, essentia_acousticness = ?,
                           opening_energy = ?,
                           confidence = MAX(COALESCE(confidence, 0), ?),
                           classification_source = ?,
                           classified_at = ?
                       WHERE spotify_uri = ?""",
                    (
                        features["key"], features["mode"],
                        features["energy"], features["acousticness"],
                        features["opening_energy"],
                        tracker_confidence,
                        new_source, now, uri,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE song_classifications
                       SET key = ?, mode = ?, energy = ?, acousticness = ?,
                           essentia_energy = ?, essentia_acousticness = ?,
                           opening_energy = ?,
                           confidence = MAX(COALESCE(confidence, 0), ?),
                           classification_source = ?,
                           classified_at = ?
                       WHERE spotify_uri = ?""",
                    (
                        features["key"], features["mode"],
                        features["energy"], features["acousticness"],
                        features["energy"], features["acousticness"],
                        features["opening_energy"],
                        tracker_confidence,
                        new_source, now, uri,
                    ),
                )
        else:
            # INSERT: new song with Essentia-only data
            upsert_song_classification(conn, {
                "spotify_uri": uri,
                "key": features["key"],
                "mode": features["mode"],
                "energy": features["energy"],
                "acousticness": features["acousticness"],
                "essentia_energy": features["energy"],
                "essentia_acousticness": features["acousticness"],
                "opening_energy": features["opening_energy"],
                "instrumentalness": features["instrumentalness"],
                "danceability": features["danceability"],
                "confidence": tracker_confidence,
                "classification_source": "essentia",
                "classified_at": now,
            })
        update_tempo_readings(conn, uri, features)
        conn.commit()
        stats["analyzed"] += 1
        logger.info(
            "Analyzed: %s — %s (essentia BPM=%s, key=%s %s)",
            song["name"], song["artist"],
            features["essentia_bpm"], features["key"], features["mode"],
        )

    total = len(unclassified)
    if total > 0 and stats["analyzed"] == 0:
        logger.warning(
            "ALL %d songs failed Essentia analysis (skipped=%d, failed=%d) "
            "— check audio directory exists and contains valid clips",
            total, stats["skipped"], stats["failed"],
        )

    return stats


def measure_missing_tempo_readings(
    conn: sqlite3.Connection,
    audio_dir: Path,
) -> dict[str, int]:
    """Backfill raw tempo readings for classified songs that have none yet.

    Writes only the tracker columns — nothing else about the song changes —
    so it is safe on a fully classified library. Run update-tempos afterwards
    to turn the readings into tempo.

    Returns summary: {measured, failed, skipped}
    """
    stats = {"measured": 0, "failed": 0, "skipped": 0}
    no_readings = " AND ".join(f"{c} IS NULL" for c in READING_COLUMNS)
    rows = conn.execute(
        f"SELECT spotify_uri FROM song_classifications WHERE {no_readings}"  # noqa: S608
    ).fetchall()

    for row in rows:
        uri = row["spotify_uri"]
        clip_path = audio_dir / uri_to_filename(uri)
        if not clip_path.exists():
            stats["skipped"] += 1
            continue
        readings = measure_tempo_readings(clip_path)
        if readings is None:
            stats["failed"] += 1
            continue
        update_tempo_readings(conn, uri, readings)
        conn.commit()
        stats["measured"] += 1
        if stats["measured"] % 50 == 0:
            logger.info("Tempo readings: %d measured", stats["measured"])

    return stats
