"""Essentia-based audio feature extraction.

Analyzes audio clips to extract BPM, key, mode, energy, acousticness,
instrumentalness, and danceability. Results are stored in song_classifications
with classification_source = "essentia".
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from classification.audio import uri_to_filename
from db.queries import get_unclassified_songs, upsert_song_classification

logger = logging.getLogger(__name__)

# Valid note names for key validation
VALID_KEYS = {"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"}


def _estimate_bpm(audio: Any, es: Any) -> tuple[int | None, float]:
    """Multi-algorithm BPM estimation with octave-aware consensus.

    Runs RhythmExtractor2013 + PercivalBpmEstimator + BpmHistogramDescriptors,
    normalizes candidates to the 60-170 BPM range, and picks the consensus.
    Returns (bpm, confidence).
    """
    # Algorithm 1: RhythmExtractor2013 (5 outputs)
    rhythm_ext = es.RhythmExtractor2013(method="multifeature")
    re_bpm, _ticks, re_confidence, _estimates, bpm_intervals = rhythm_ext(audio)

    # Algorithm 2: PercivalBpmEstimator (independent second opinion)
    percival_bpm = float(es.PercivalBpmEstimator()(audio))

    # Algorithm 3: BpmHistogramDescriptors peaks (from RhythmExtractor's intervals)
    peak1_bpm, peak2_bpm = 0.0, 0.0
    if len(bpm_intervals) >= 2:
        peak1_bpm, _, _, peak2_bpm, _, _, _ = es.BpmHistogramDescriptors()(bpm_intervals)

    # Collect all non-zero candidates
    raw_candidates = [c for c in [re_bpm, percival_bpm, peak1_bpm, peak2_bpm] if c > 0]
    if not raw_candidates:
        return None, 0.0

    # Normalize all candidates to the 60-170 BPM range
    def normalize(bpm: float) -> float:
        while bpm > 170:
            bpm /= 2
        while bpm < 60:
            bpm *= 2
        return bpm

    normalized = [normalize(c) for c in raw_candidates]

    # Find consensus: group candidates within 10 BPM of each other
    best_group: list[float] = []
    for anchor in normalized:
        group = [n for n in normalized if abs(n - anchor) <= 10]
        if len(group) > len(best_group):
            best_group = group

    if best_group:
        best_bpm = sum(best_group) / len(best_group)
    else:
        best_bpm = normalize(re_bpm)

    # Confidence: RhythmExtractor confidence (0-5.32) scaled by agreement level
    agreement = len(best_group) / len(normalized) if normalized else 0
    confidence = min(float(re_confidence) * agreement, 1.0)

    return int(round(best_bpm)), confidence


def analyze_audio(audio_path: Path) -> dict[str, Any] | None:
    """Analyze a single audio file with Essentia algorithms.

    Returns a dict of extracted features, or None if analysis fails.
    """
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

    try:
        # BPM — multi-algorithm consensus with octave correction
        bpm, bpm_confidence = _estimate_bpm(audio, es)

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
            "bpm": bpm,
            "bpm_confidence": round(bpm_confidence, 3),
            "key": key,
            "mode": mode,
            "energy": round(energy, 4),
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

        if existing:
            # UPDATE: always write raw Essentia values to essentia_* columns.
            # When LLM has already classified, only update BPM/key/mode —
            # energy/acousticness are handled by the merge logic in llm_classifier
            # (Essentia spectral flatness is structurally wrong for acousticness).
            if "llm" in existing_source:
                conn.execute(
                    """UPDATE song_classifications
                       SET bpm = ?, key = ?, mode = ?,
                           essentia_energy = ?, essentia_acousticness = ?,
                           confidence = MAX(COALESCE(confidence, 0), ?),
                           classification_source = ?,
                           classified_at = ?
                       WHERE spotify_uri = ?""",
                    (
                        features["bpm"], features["key"], features["mode"],
                        features["energy"], features["acousticness"],
                        features["bpm_confidence"],
                        new_source, now, uri,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE song_classifications
                       SET bpm = ?, key = ?, mode = ?, energy = ?, acousticness = ?,
                           essentia_energy = ?, essentia_acousticness = ?,
                           confidence = MAX(COALESCE(confidence, 0), ?),
                           classification_source = ?,
                           classified_at = ?
                       WHERE spotify_uri = ?""",
                    (
                        features["bpm"], features["key"], features["mode"],
                        features["energy"], features["acousticness"],
                        features["energy"], features["acousticness"],
                        features["bpm_confidence"],
                        new_source, now, uri,
                    ),
                )
        else:
            # INSERT: new song with Essentia-only data
            upsert_song_classification(conn, {
                "spotify_uri": uri,
                "bpm": features["bpm"],
                "key": features["key"],
                "mode": features["mode"],
                "energy": features["energy"],
                "acousticness": features["acousticness"],
                "essentia_energy": features["energy"],
                "essentia_acousticness": features["acousticness"],
                "instrumentalness": features["instrumentalness"],
                "danceability": features["danceability"],
                "confidence": features["bpm_confidence"],
                "classification_source": "essentia",
                "classified_at": now,
            })
        conn.commit()
        stats["analyzed"] += 1
        logger.info(
            "Analyzed: %s — %s (BPM=%s, key=%s %s)",
            song["name"], song["artist"],
            features["bpm"], features["key"], features["mode"],
        )

    total = len(unclassified)
    if total > 0 and stats["analyzed"] == 0:
        logger.warning(
            "ALL %d songs failed Essentia analysis (skipped=%d, failed=%d) "
            "— check audio directory exists and contains valid clips",
            total, stats["skipped"], stats["failed"],
        )

    return stats
