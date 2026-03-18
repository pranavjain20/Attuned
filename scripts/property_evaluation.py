#!/usr/bin/env python3
"""Property-by-property evaluation of Essentia classification properties.

Runs Essentia analysis on Strategy D audio files for:
- Key/Mode (KeyExtractor with multiple profiles)
- Energy (RMS vs Loudness vs OnsetRate)
- Danceability (raw range analysis)
- Acousticness (SpectralCentroid vs SpectralFlatness vs SpectralRolloff)
- Instrumentalness (ZCR analysis — expected low for vocal tracks)

Compares against ground truth where available and prints evaluation report.

Usage:
    python scripts/property_evaluation.py                    # full report
    python scripts/property_evaluation.py --property key     # key/mode only
    python scripts/property_evaluation.py --property energy  # energy only
    python scripts/property_evaluation.py --json             # save raw data
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DIR_D = PROJECT_ROOT / "audio_clips_test_d"
RESULTS_PATH = PROJECT_ROOT / "scripts" / "property_eval_results.json"

# Same test songs as yt_match_experiment.py, extended with known key/mode ground truth.
# Ground truth from Tunebat / music databases. None = not yet looked up.
# Ground truth: Spotify audio features via Tunebat/SongBPM/SongData.
# CAVEAT: These are Spotify's algorithmic key detection (Essentia-based),
# not human annotation. We're comparing our Essentia-on-YouTube against
# Spotify's Essentia-on-official-audio. Differences show audio quality
# or parameter divergence, not necessarily "wrong" keys.
TEST_SONGS = [
    # --- Old Bollywood ---
    {"name": "Pal Pal Dil Ke Paas", "artist": "Kishore Kumar",
     "category": "old_bollywood", "known_key": "Bb", "known_mode": "minor"},
    {"name": "Chaand Taare", "artist": "Abhijeet",
     "category": "old_bollywood", "known_key": "G", "known_mode": "major"},
    {"name": "Chand Sifarish", "artist": "Jatin-Lalit",
     "category": "old_bollywood", "known_key": "D", "known_mode": "major"},
    {"name": "Yun Hi Chala Chal", "artist": "Udit Narayan",
     "category": "old_bollywood", "known_key": "A", "known_mode": "major"},
    {"name": "Dil Kya Kare", "artist": "Adnan Sami",
     "category": "old_bollywood", "known_key": "G", "known_mode": "major"},

    # --- Modern Bollywood ---
    {"name": "Namo Namo", "artist": "Amit Trivedi",
     "category": "modern_bollywood", "known_key": "E", "known_mode": "major"},
    {"name": "Deva Deva", "artist": "Pritam",
     "category": "modern_bollywood", "known_key": "C", "known_mode": "major"},
    {"name": "Apna Bana Le", "artist": "Sachin-Jigar",
     "category": "modern_bollywood", "known_key": "A", "known_mode": "major"},
    {"name": "Kun Faya Kun", "artist": "A.R. Rahman",
     "category": "modern_bollywood", "known_key": "Db", "known_mode": "major"},
    {"name": "Raataan Lambiyan", "artist": "Tanishk Bagchi",
     "category": "modern_bollywood", "known_key": "Bb", "known_mode": "major"},
    {"name": "Jashn-E-Bahaaraa", "artist": "A.R. Rahman",
     "category": "modern_bollywood", "known_key": "D", "known_mode": "major"},
    {"name": "Tum Se Hi", "artist": "Pritam",
     "category": "modern_bollywood", "known_key": "F#", "known_mode": "major"},
    {"name": "Naina Da Kya Kasoor", "artist": "Amit Trivedi",
     "category": "modern_bollywood", "known_key": "A", "known_mode": "major"},

    # --- English ---
    {"name": "One Love", "artist": "Blue",
     "category": "english", "known_key": "Ab", "known_mode": "minor"},
    {"name": "Levitating", "artist": "Dua Lipa",
     "category": "english", "known_key": "F#", "known_mode": "minor"},
    {"name": "Watermelon Sugar", "artist": "Harry Styles",
     "category": "english", "known_key": "C", "known_mode": "major"},
    {"name": "Maps", "artist": "Maroon 5",
     "category": "english", "known_key": "Db", "known_mode": "minor"},
    {"name": "Quit Playing Games (With My Heart)", "artist": "Backstreet Boys",
     "category": "english", "known_key": "B", "known_mode": "minor"},

    # --- Punjabi ---
    {"name": "Excuses", "artist": "AP Dhillon",
     "category": "punjabi", "known_key": "F", "known_mode": "minor"},
    {"name": "Softly", "artist": "Karan Aujla",
     "category": "punjabi", "known_key": "Ab", "known_mode": "major"},
    {"name": "Cheques", "artist": "Shubh",
     "category": "punjabi", "known_key": "E", "known_mode": "minor"},
    {"name": "Amplifier", "artist": "Imran Khan",
     "category": "punjabi", "known_key": "D", "known_mode": "major"},

    # --- Common names ---
    {"name": "One Love", "artist": "Shubh",
     "category": "common_name", "known_key": "G", "known_mode": "major"},
    {"name": "Ride It", "artist": "Jay Sean",
     "category": "common_name", "known_key": "B", "known_mode": "minor"},
    {"name": "Maan Meri Jaan", "artist": "King",
     "category": "common_name", "known_key": "F#", "known_mode": "minor"},
]


def _safe_filename(name: str, artist: str) -> str:
    """Create a filesystem-safe filename from song name and artist."""
    safe = f"{artist} - {name}".replace("/", "_").replace("\\", "_")
    return safe[:80] + ".mp3"


def analyze_all_properties(songs: list[dict]) -> list[dict]:
    """Run comprehensive Essentia analysis on all audio files."""
    try:
        import essentia.standard as es
    except ImportError:
        print("ERROR: essentia not installed")
        sys.exit(1)

    results = []

    for i, song in enumerate(songs, 1):
        filename = _safe_filename(song["name"], song["artist"])
        path = DIR_D / filename
        label = f"{song['artist'][:20]} — {song['name'][:25]}"

        entry = {
            "name": song["name"],
            "artist": song["artist"],
            "category": song["category"],
            "known_key": song.get("known_key"),
            "known_mode": song.get("known_mode"),
        }

        if not path.exists():
            print(f"[{i}/{len(songs)}] {label}: NO AUDIO FILE")
            entry["status"] = "missing"
            results.append(entry)
            continue

        print(f"[{i}/{len(songs)}] {label}")

        try:
            audio = es.MonoLoader(filename=str(path), sampleRate=44100)()
        except Exception as e:
            print(f"  LOAD FAILED: {e}")
            entry["status"] = "load_failed"
            results.append(entry)
            continue

        # ── Key/Mode ──────────────────────────────────────────────
        # Default profile (temperley)
        key_ext = es.KeyExtractor()
        key, scale, strength = key_ext(audio)
        entry["key"] = key
        entry["mode"] = "major" if scale == "major" else "minor"
        entry["key_strength"] = round(float(strength), 4)

        # EDMA profile (Electronic Dance Music Analysis — tuned for non-classical)
        key_ext_edma = es.KeyExtractor(profileType="edma")
        key_e, scale_e, strength_e = key_ext_edma(audio)
        entry["key_edma"] = key_e
        entry["mode_edma"] = "major" if scale_e == "major" else "minor"
        entry["key_strength_edma"] = round(float(strength_e), 4)

        # Bgate profile (uses different weighting)
        key_ext_bg = es.KeyExtractor(profileType="bgate")
        key_b, scale_b, strength_b = key_ext_bg(audio)
        entry["key_bgate"] = key_b
        entry["mode_bgate"] = "major" if scale_b == "major" else "minor"
        entry["key_strength_bgate"] = round(float(strength_b), 4)

        # ── Energy ────────────────────────────────────────────────
        # Current method: RMS / 0.25
        rms = float(es.RMS()(audio))
        entry["rms_raw"] = round(rms, 5)
        entry["energy_rms"] = round(max(0.0, min(1.0, rms / 0.25)), 4)

        # Alternative 1: Loudness (EBU R128 integrated loudness in LUFS)
        loudness = float(es.Loudness()(audio))
        entry["loudness_raw"] = round(loudness, 4)

        # Alternative 2: Dynamic Complexity
        dc, dc_loudness = es.DynamicComplexity()(audio)
        entry["dynamic_complexity"] = round(float(dc), 4)
        entry["dynamic_complexity_loudness"] = round(float(dc_loudness), 4)

        # Alternative 3: Onset Rate (onsets per second — rhythmic density)
        onset_rate = float(es.OnsetRate()(audio)[1])
        entry["onset_rate"] = round(onset_rate, 4)

        # Alternative 4: Spectral Energy (sum of magnitudes)
        spectrum = es.Spectrum(size=2048)(es.Windowing(type="hann")(audio[:2048]))
        spec_energy = float(es.Energy()(spectrum))
        entry["spectral_energy"] = round(spec_energy, 6)

        # ── Danceability ──────────────────────────────────────────
        # Current method: Essentia Danceability (DFA)
        dance_raw = float(es.Danceability()(audio)[0])
        entry["danceability_raw"] = round(dance_raw, 4)
        entry["danceability_clamped"] = round(max(0.0, min(1.0, dance_raw)), 4)

        # Danceability returns (danceability, dfa_array)
        # dfa_array is the full DFA output — just record the raw danceability
        entry["dfa_alpha"] = round(dance_raw, 4)  # same as raw, kept for schema

        # ── Acousticness ──────────────────────────────────────────
        # Current method: inverted SpectralCentroidTime
        sct = float(es.SpectralCentroidTime()(audio))
        entry["spectral_centroid_hz"] = round(sct, 2)
        entry["acousticness_sct"] = round(
            max(0.0, min(1.0, 1.0 - (sct - 500.0) / 1500.0)), 4
        )

        # Alternative 1: Spectral Flatness (closer to 1 = noise-like/bright)
        # Need to compute on frames
        frame_gen = es.FrameGenerator(audio, frameSize=2048, hopSize=1024)
        flatness_values = []
        for frame in frame_gen:
            windowed = es.Windowing(type="hann")(frame)
            spec = es.Spectrum()(windowed)
            if sum(spec) > 0:
                flatness_values.append(float(es.Flatness()(spec)))
        avg_flatness = sum(flatness_values) / len(flatness_values) if flatness_values else 0
        entry["spectral_flatness"] = round(avg_flatness, 6)
        # Invert: low flatness = more tonal/acoustic
        entry["acousticness_flatness"] = round(1.0 - min(1.0, avg_flatness * 10), 4)

        # Alternative 2: Spectral Rolloff (frequency below which 85% of energy)
        rolloff_values = []
        frame_gen2 = es.FrameGenerator(audio, frameSize=2048, hopSize=1024)
        for frame in frame_gen2:
            windowed = es.Windowing(type="hann")(frame)
            spec = es.Spectrum()(windowed)
            if sum(spec) > 0:
                rolloff_values.append(float(es.RollOff()(spec)))
        avg_rolloff = sum(rolloff_values) / len(rolloff_values) if rolloff_values else 0
        entry["spectral_rolloff_hz"] = round(avg_rolloff, 2)
        # Map: lower rolloff = more acoustic. Range roughly 1000-8000 Hz
        entry["acousticness_rolloff"] = round(
            max(0.0, min(1.0, 1.0 - (avg_rolloff - 1000) / 7000)), 4
        )

        # ── Instrumentalness ─────────────────────────────────────
        # Current method: ZCR
        zcr = float(es.ZeroCrossingRate()(audio))
        entry["zcr_raw"] = round(zcr, 6)
        entry["instrumentalness_zcr"] = round(
            max(0.0, min(1.0, (zcr - 0.02) / 0.08)), 4
        )

        # For comparison: also compute spectral flux (voice has more variation)
        flux_values = []
        prev_spec = None
        frame_gen3 = es.FrameGenerator(audio, frameSize=2048, hopSize=1024)
        for frame in frame_gen3:
            windowed = es.Windowing(type="hann")(frame)
            spec = es.Spectrum()(windowed)
            if prev_spec is not None:
                flux_values.append(float(es.Flux()(spec)))
            prev_spec = spec
        avg_flux = sum(flux_values) / len(flux_values) if flux_values else 0
        entry["spectral_flux"] = round(avg_flux, 6)

        entry["status"] = "ok"
        results.append(entry)

    return results


# ── Enharmonic equivalents for key comparison ─────────────────────
ENHARMONIC = {
    "C#": "Db", "Db": "C#",
    "D#": "Eb", "Eb": "D#",
    "F#": "Gb", "Gb": "F#",
    "G#": "Ab", "Ab": "G#",
    "A#": "Bb", "Bb": "A#",
}

# Relative major/minor pairs (parallel keys share same root)
# Relative keys: C major ↔ A minor, etc.
RELATIVE_MINOR = {
    "C": "A", "C#": "Bb", "Db": "Bb", "D": "B", "Eb": "C",
    "E": "C#", "F": "D", "F#": "Eb", "Gb": "Eb", "G": "E",
    "Ab": "F", "A": "F#", "Bb": "G", "B": "Ab",
}


def _keys_match(k1: str, m1: str, k2: str, m2: str) -> str:
    """Compare two key/mode pairs. Returns match type."""
    if k1 is None or k2 is None:
        return "no_ground_truth"

    # Exact match
    if k1 == k2 and m1 == m2:
        return "exact"

    # Enharmonic match (C# = Db, etc.)
    if ENHARMONIC.get(k1) == k2 and m1 == m2:
        return "enharmonic"

    # Same root, different mode (parallel key: C major vs C minor)
    if k1 == k2 and m1 != m2:
        return "parallel"
    if ENHARMONIC.get(k1) == k2 and m1 != m2:
        return "parallel"

    # Relative key (C major ↔ A minor — same notes, different root)
    if m1 == "major" and m2 == "minor":
        rel = RELATIVE_MINOR.get(k1)
        if rel == k2 or ENHARMONIC.get(rel, "") == k2:
            return "relative"
    elif m1 == "minor" and m2 == "major":
        rel = RELATIVE_MINOR.get(k2)
        if rel == k1 or ENHARMONIC.get(rel, "") == k1:
            return "relative"

    return "wrong"


def print_key_mode_report(results: list[dict]) -> None:
    """Evaluate key/mode accuracy."""
    print("\n" + "=" * 120)
    print("KEY/MODE EVALUATION")
    print("=" * 120)

    print(f"\n{'Song':<45} {'Known':>8} {'Default':>10} {'Str':>5} "
          f"{'EDMA':>10} {'Str':>5} {'Bgate':>10} {'Str':>5} {'Match':>10}")
    print("-" * 120)

    match_counts = {"exact": 0, "enharmonic": 0, "parallel": 0,
                    "relative": 0, "wrong": 0, "no_ground_truth": 0}
    by_category: dict[str, dict[str, int]] = {}

    for r in results:
        if r.get("status") != "ok":
            continue

        label = f"{r['artist'][:18]} — {r['name'][:22]}"
        def _mode_abbr(m: str) -> str:
            return "M" if m == "major" else "m"

        known_m = _mode_abbr(r['known_mode']) if r.get('known_mode') else '?'
        known = f"{r.get('known_key', '?')}{known_m}"
        default = f"{r['key']}{_mode_abbr(r['mode'])}"
        edma = f"{r['key_edma']}{_mode_abbr(r['mode_edma'])}"
        bgate = f"{r['key_bgate']}{_mode_abbr(r['mode_bgate'])}"

        match = _keys_match(
            r.get("known_key"), r.get("known_mode"),
            r["key"], r["mode"],
        )
        match_counts[match] += 1

        cat = r["category"]
        if cat not in by_category:
            by_category[cat] = {"exact": 0, "enharmonic": 0, "parallel": 0,
                                "relative": 0, "wrong": 0, "no_ground_truth": 0}
        by_category[cat][match] += 1

        print(f"{label:<45} {known:>8} {default:>10} {r['key_strength']:>5.3f} "
              f"{edma:>10} {r['key_strength_edma']:>5.3f} "
              f"{bgate:>10} {r['key_strength_bgate']:>5.3f} {match:>10}")

    print("-" * 120)
    total_with_gt = sum(v for k, v in match_counts.items() if k != "no_ground_truth")
    print(f"\nKey/Mode Match Summary (songs with ground truth: {total_with_gt}):")
    print(f"  Exact:      {match_counts['exact']}")
    print(f"  Enharmonic: {match_counts['enharmonic']}")
    print(f"  Parallel:   {match_counts['parallel']} (same root, wrong major/minor)")
    print(f"  Relative:   {match_counts['relative']} (relative key — musically close)")
    print(f"  Wrong:      {match_counts['wrong']}")
    print(f"  No GT:      {match_counts['no_ground_truth']}")

    if by_category:
        print(f"\nPer-Category Breakdown:")
        for cat, counts in sorted(by_category.items()):
            total = sum(v for k, v in counts.items() if k != "no_ground_truth")
            correct = counts["exact"] + counts["enharmonic"]
            close = counts["parallel"] + counts["relative"]
            print(f"  {cat:<20} exact+enhar: {correct}/{total}  "
                  f"close: {close}/{total}  wrong: {counts['wrong']}/{total}  "
                  f"no_gt: {counts['no_ground_truth']}")

    # Profile comparison
    print(f"\nProfile Agreement (default vs EDMA vs Bgate):")
    agree_all = 0
    agree_none = 0
    for r in results:
        if r.get("status") != "ok":
            continue
        keys = [(r["key"], r["mode"]), (r["key_edma"], r["mode_edma"]),
                (r["key_bgate"], r["mode_bgate"])]
        if keys[0] == keys[1] == keys[2]:
            agree_all += 1
        elif keys[0] != keys[1] and keys[0] != keys[2] and keys[1] != keys[2]:
            agree_none += 1
    total = sum(1 for r in results if r.get("status") == "ok")
    print(f"  All 3 agree: {agree_all}/{total}")
    print(f"  All 3 disagree: {agree_none}/{total}")


def print_energy_report(results: list[dict]) -> None:
    """Evaluate energy measures."""
    print("\n" + "=" * 120)
    print("ENERGY EVALUATION")
    print("=" * 120)

    print(f"\n{'Song':<40} {'Cat':<12} {'RMS':>6} {'Energy':>7} "
          f"{'Loud':>7} {'DynCx':>6} {'Onset':>6}")
    print("-" * 90)

    rms_vals = []
    loud_vals = []
    onset_vals = []

    for r in results:
        if r.get("status") != "ok":
            continue

        label = f"{r['artist'][:16]} — {r['name'][:20]}"
        print(f"{label:<40} {r['category']:<12} "
              f"{r['rms_raw']:>6.4f} {r['energy_rms']:>7.4f} "
              f"{r['loudness_raw']:>7.2f} {r['dynamic_complexity']:>6.2f} "
              f"{r['onset_rate']:>6.2f}")

        rms_vals.append(r["energy_rms"])
        loud_vals.append(r["loudness_raw"])
        onset_vals.append(r["onset_rate"])

    print("-" * 90)

    # Distribution stats
    def _stats(vals: list[float]) -> str:
        if not vals:
            return "no data"
        mn, mx = min(vals), max(vals)
        avg = sum(vals) / len(vals)
        return f"min={mn:.3f} max={mx:.3f} avg={avg:.3f} range={mx-mn:.3f}"

    print(f"\nDistribution:")
    print(f"  Energy (RMS/0.25): {_stats(rms_vals)}")
    print(f"  Loudness (raw):    {_stats(loud_vals)}")
    print(f"  Onset Rate:        {_stats(onset_vals)}")

    # Sanity check: rank by energy and see if it makes sense
    ranked = sorted(
        [r for r in results if r.get("status") == "ok"],
        key=lambda r: r["energy_rms"],
        reverse=True,
    )
    print(f"\nTop 5 by Energy (RMS):")
    for r in ranked[:5]:
        print(f"  {r['energy_rms']:.4f} — {r['artist']} — {r['name']} [{r['category']}]")
    print(f"Bottom 5 by Energy (RMS):")
    for r in ranked[-5:]:
        print(f"  {r['energy_rms']:.4f} — {r['artist']} — {r['name']} [{r['category']}]")

    # Same for loudness
    ranked_loud = sorted(
        [r for r in results if r.get("status") == "ok"],
        key=lambda r: r["loudness_raw"],
        reverse=True,
    )
    print(f"\nTop 5 by Loudness:")
    for r in ranked_loud[:5]:
        print(f"  {r['loudness_raw']:.2f} — {r['artist']} — {r['name']} [{r['category']}]")
    print(f"Bottom 5 by Loudness:")
    for r in ranked_loud[-5:]:
        print(f"  {r['loudness_raw']:.2f} — {r['artist']} — {r['name']} [{r['category']}]")

    # Correlation between RMS energy and loudness
    if rms_vals and loud_vals:
        n = len(rms_vals)
        mean_r = sum(rms_vals) / n
        mean_l = sum(loud_vals) / n
        cov = sum((r - mean_r) * (l - mean_l) for r, l in zip(rms_vals, loud_vals)) / n
        std_r = (sum((r - mean_r) ** 2 for r in rms_vals) / n) ** 0.5
        std_l = (sum((l - mean_l) ** 2 for l in loud_vals) / n) ** 0.5
        corr = cov / (std_r * std_l) if std_r > 0 and std_l > 0 else 0
        print(f"\nCorrelation (RMS Energy vs Loudness): {corr:.3f}")


def print_danceability_report(results: list[dict]) -> None:
    """Evaluate danceability measure."""
    print("\n" + "=" * 120)
    print("DANCEABILITY EVALUATION")
    print("=" * 120)

    print(f"\n{'Song':<40} {'Cat':<12} {'Raw':>7} {'Clamped':>8} {'DFA_α':>7}")
    print("-" * 80)

    raw_vals = []
    for r in results:
        if r.get("status") != "ok":
            continue

        label = f"{r['artist'][:16]} — {r['name'][:20]}"
        print(f"{label:<40} {r['category']:<12} "
              f"{r['danceability_raw']:>7.4f} {r['danceability_clamped']:>8.4f} "
              f"{r['dfa_alpha']:>7.4f}")
        raw_vals.append(r["danceability_raw"])

    print("-" * 80)

    if raw_vals:
        mn, mx = min(raw_vals), max(raw_vals)
        avg = sum(raw_vals) / len(raw_vals)
        above_1 = sum(1 for v in raw_vals if v > 1.0)
        print(f"\nRaw Distribution: min={mn:.4f} max={mx:.4f} avg={avg:.4f}")
        print(f"  Values > 1.0 (clamped): {above_1}/{len(raw_vals)}")
        print(f"  Values < 0.0 (clamped): {sum(1 for v in raw_vals if v < 0.0)}/{len(raw_vals)}")
        print(f"  Effective range used: [{mn:.4f}, {min(mx, 1.0):.4f}]")

    # Rank by danceability
    ranked = sorted(
        [r for r in results if r.get("status") == "ok"],
        key=lambda r: r["danceability_raw"],
        reverse=True,
    )
    print(f"\nTop 5 Most Danceable:")
    for r in ranked[:5]:
        print(f"  {r['danceability_raw']:.4f} — {r['artist']} — {r['name']} [{r['category']}]")
    print(f"Bottom 5 Least Danceable:")
    for r in ranked[-5:]:
        print(f"  {r['danceability_raw']:.4f} — {r['artist']} — {r['name']} [{r['category']}]")


def print_acousticness_report(results: list[dict]) -> None:
    """Evaluate acousticness measures."""
    print("\n" + "=" * 120)
    print("ACOUSTICNESS EVALUATION")
    print("=" * 120)

    print(f"\n{'Song':<40} {'Cat':<12} {'SCT_Hz':>7} {'Ac_SCT':>7} "
          f"{'Flat':>8} {'Ac_Flat':>7} {'Roll_Hz':>8} {'Ac_Roll':>7}")
    print("-" * 100)

    sct_vals = []
    flat_vals = []
    roll_vals = []

    for r in results:
        if r.get("status") != "ok":
            continue

        label = f"{r['artist'][:16]} — {r['name'][:20]}"
        print(f"{label:<40} {r['category']:<12} "
              f"{r['spectral_centroid_hz']:>7.1f} {r['acousticness_sct']:>7.4f} "
              f"{r['spectral_flatness']:>8.6f} {r['acousticness_flatness']:>7.4f} "
              f"{r['spectral_rolloff_hz']:>8.1f} {r['acousticness_rolloff']:>7.4f}")

        sct_vals.append(r["acousticness_sct"])
        flat_vals.append(r["acousticness_flatness"])
        roll_vals.append(r["acousticness_rolloff"])

    print("-" * 100)

    def _stats(name: str, vals: list[float]) -> None:
        mn, mx = min(vals), max(vals)
        avg = sum(vals) / len(vals)
        print(f"  {name}: min={mn:.4f} max={mx:.4f} avg={avg:.4f} range={mx-mn:.4f}")

    print(f"\nDistribution:")
    _stats("Acousticness (SCT)", sct_vals)
    _stats("Acousticness (Flat)", flat_vals)
    _stats("Acousticness (Roll)", roll_vals)

    # Rank by each method
    for method, key_name in [("SCT", "acousticness_sct"),
                              ("Flatness", "acousticness_flatness"),
                              ("Rolloff", "acousticness_rolloff")]:
        ranked = sorted(
            [r for r in results if r.get("status") == "ok"],
            key=lambda r, k=key_name: r[k],
            reverse=True,
        )
        print(f"\nTop 3 Most Acoustic ({method}):")
        for r in ranked[:3]:
            print(f"  {r[key_name]:.4f} — {r['artist']} — {r['name']} [{r['category']}]")
        print(f"Top 3 Least Acoustic ({method}):")
        for r in ranked[-3:]:
            print(f"  {r[key_name]:.4f} — {r['artist']} — {r['name']} [{r['category']}]")

    # Correlation between the three methods
    if sct_vals and flat_vals:
        n = len(sct_vals)
        for name_a, vals_a, name_b, vals_b in [
            ("SCT", sct_vals, "Flatness", flat_vals),
            ("SCT", sct_vals, "Rolloff", roll_vals),
            ("Flatness", flat_vals, "Rolloff", roll_vals),
        ]:
            mean_a = sum(vals_a) / n
            mean_b = sum(vals_b) / n
            cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(vals_a, vals_b)) / n
            std_a = (sum((a - mean_a) ** 2 for a in vals_a) / n) ** 0.5
            std_b = (sum((b - mean_b) ** 2 for b in vals_b) / n) ** 0.5
            corr = cov / (std_a * std_b) if std_a > 0 and std_b > 0 else 0
            print(f"\nCorrelation ({name_a} vs {name_b}): {corr:.3f}")


def print_instrumentalness_report(results: list[dict]) -> None:
    """Evaluate instrumentalness measures."""
    print("\n" + "=" * 120)
    print("INSTRUMENTALNESS EVALUATION")
    print("=" * 120)
    print("NOTE: All 24 test songs are vocal tracks. Instrumentalness should be LOW for all.")

    print(f"\n{'Song':<40} {'Cat':<12} {'ZCR':>8} {'Inst_ZCR':>9} {'Flux':>9}")
    print("-" * 85)

    zcr_vals = []
    inst_vals = []

    for r in results:
        if r.get("status") != "ok":
            continue

        label = f"{r['artist'][:16]} — {r['name'][:20]}"
        print(f"{label:<40} {r['category']:<12} "
              f"{r['zcr_raw']:>8.5f} {r['instrumentalness_zcr']:>9.4f} "
              f"{r['spectral_flux']:>9.6f}")

        zcr_vals.append(r["zcr_raw"])
        inst_vals.append(r["instrumentalness_zcr"])

    print("-" * 85)

    if zcr_vals:
        mn, mx = min(zcr_vals), max(zcr_vals)
        avg = sum(zcr_vals) / len(zcr_vals)
        print(f"\nZCR Distribution: min={mn:.5f} max={mx:.5f} avg={avg:.5f}")

        mn_i, mx_i = min(inst_vals), max(inst_vals)
        avg_i = sum(inst_vals) / len(inst_vals)
        print(f"Instrumentalness (ZCR) Distribution: min={mn_i:.4f} max={mx_i:.4f} avg={avg_i:.4f}")

        high_inst = sum(1 for v in inst_vals if v > 0.5)
        print(f"\nSongs with instrumentalness > 0.5: {high_inst}/{len(inst_vals)} "
              f"(should be 0 — all songs are vocal)")

        # The ZCR-based proxy should ideally give LOW values for all vocal tracks
        # If there's high variance, the proxy isn't distinguishing vocal vs instrumental
        variance = sum((v - avg_i) ** 2 for v in inst_vals) / len(inst_vals)
        print(f"Variance: {variance:.6f} (low variance = proxy isn't discriminating)")


def print_summary(results: list[dict]) -> None:
    """Print final summary with decisions."""
    print("\n" + "=" * 120)
    print("PROPERTY EVALUATION SUMMARY")
    print("=" * 120)

    ok_results = [r for r in results if r.get("status") == "ok"]
    n = len(ok_results)
    print(f"\nAnalyzed {n} songs across {len(set(r['category'] for r in ok_results))} categories")

    print(f"\nPer-Property Overview:")
    print(f"{'Property':<20} {'Algorithm':<25} {'Key Observation'}")
    print("-" * 90)

    # Key strength stats
    strengths = [r["key_strength"] for r in ok_results]
    avg_str = sum(strengths) / len(strengths) if strengths else 0
    print(f"{'Key/Mode':<20} {'KeyExtractor (HPCP)':<25} "
          f"avg strength={avg_str:.3f}, see match report above")

    # Energy range
    energies = [r["energy_rms"] for r in ok_results]
    print(f"{'Energy':<20} {'RMS / 0.25':<25} "
          f"range=[{min(energies):.3f}, {max(energies):.3f}]")

    # Danceability range
    dances = [r["danceability_raw"] for r in ok_results]
    above1 = sum(1 for d in dances if d > 1.0)
    print(f"{'Danceability':<20} {'DFA algorithm':<25} "
          f"raw range=[{min(dances):.3f}, {max(dances):.3f}], {above1} above 1.0")

    # Acousticness
    acous = [r["acousticness_sct"] for r in ok_results]
    print(f"{'Acousticness':<20} {'Inv. SpectralCentroid':<25} "
          f"range=[{min(acous):.3f}, {max(acous):.3f}]")

    # Instrumentalness
    insts = [r["instrumentalness_zcr"] for r in ok_results]
    high = sum(1 for v in insts if v > 0.5)
    print(f"{'Instrumentalness':<20} {'ZCR proxy':<25} "
          f"range=[{min(insts):.3f}, {max(insts):.3f}], {high} vocal songs scored >0.5")


def main() -> None:
    parser = argparse.ArgumentParser(description="Property-by-property Essentia evaluation")
    parser.add_argument("--property", type=str, default=None,
                        help="Evaluate specific property: key, energy, dance, acoustic, instrumental")
    parser.add_argument("--json", action="store_true", help="Save raw results to JSON")
    args = parser.parse_args()

    print("=== RUNNING ESSENTIA ANALYSIS ON STRATEGY D AUDIO FILES ===\n")
    results = analyze_all_properties(TEST_SONGS)

    if args.json:
        RESULTS_PATH.write_text(json.dumps(results, indent=2))
        print(f"\nRaw results saved to {RESULTS_PATH}")

    # Print reports
    prop = args.property
    if prop is None or prop == "key":
        print_key_mode_report(results)
    if prop is None or prop == "energy":
        print_energy_report(results)
    if prop is None or prop in ("dance", "danceability"):
        print_danceability_report(results)
    if prop is None or prop in ("acoustic", "acousticness"):
        print_acousticness_report(results)
    if prop is None or prop in ("instrumental", "instrumentalness"):
        print_instrumentalness_report(results)
    if prop is None:
        print_summary(results)


if __name__ == "__main__":
    main()
