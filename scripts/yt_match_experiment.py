#!/usr/bin/env python3
"""Audio source experiment: compare strategies for getting correct audio for BPM analysis.

Downloads 25 songs with four strategies, compares duration against Spotify's
duration_ms, and runs Essentia BPM analysis on each. Prints a comparison report.

Strategies:
    A — Album-enriched YouTube search (baseline, from prior experiment)
    B — YouTube Music search (prior experiment, ytmsearch unsupported — all missing)
    C — Spotify 30s preview URLs (guaranteed correct audio)
    D — Duration-verified YouTube (search 5 results, pick best duration match)
    F — LLM BPM via GPT-4o-mini (no audio, song metadata only)

Usage:
    python scripts/yt_match_experiment.py [--download] [--analyze] [--report]
    python scripts/yt_match_experiment.py --strategy c --download   # only Strategy C
    python scripts/yt_match_experiment.py --strategy d --download   # only Strategy D
    python scripts/yt_match_experiment.py --strategy f --analyze    # LLM only
    python scripts/yt_match_experiment.py --report                  # report from saved results

    No flags = run all steps for strategies C and D (A/B already done).
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from classification.audio import (
    download_from_youtube,
    download_from_youtube_verified,
    download_preview,
    fetch_preview_urls,
    _find_ytdlp_binary,
)
from classification.essentia_analyzer import _estimate_bpm

DB_PATH = PROJECT_ROOT / "attuned.db"
DIR_A = PROJECT_ROOT / "audio_clips_test_a"  # Strategy A: album-enriched YouTube
DIR_B = PROJECT_ROOT / "audio_clips_test_b"  # Strategy B: ytmusic (dead)
DIR_C = PROJECT_ROOT / "audio_clips_test_c"  # Strategy C: Spotify previews
DIR_D = PROJECT_ROOT / "audio_clips_test_d"  # Strategy D: duration-verified YouTube
RESULTS_PATH = PROJECT_ROOT / "scripts" / "yt_match_results.json"

# 25 songs covering the risk spectrum.
# Known BPM values from Tunebat/Musicstax (looked up manually).
TEST_SONGS = [
    # --- Old Bollywood classics (highest risk: covers, remixes, long intros) ---
    {"name": "Pal Pal Dil Ke Paas", "artist": "Kishore Kumar", "known_bpm": 117,
     "category": "old_bollywood", "note": "known failure +36 BPM"},
    {"name": "Chaand Taare", "artist": "Abhijeet", "known_bpm": 130,
     "category": "old_bollywood"},
    {"name": "Chand Sifarish", "artist": "Jatin-Lalit", "known_bpm": 82,
     "category": "old_bollywood"},
    {"name": "Yun Hi Chala Chal", "artist": "Udit Narayan", "known_bpm": 86,
     "category": "old_bollywood"},
    {"name": "Dil Kya Kare", "artist": "Adnan Sami", "known_bpm": 78,
     "category": "old_bollywood"},

    # --- Modern Bollywood (medium risk) ---
    {"name": "Namo Namo", "artist": "Amit Trivedi", "known_bpm": 95,
     "category": "modern_bollywood"},
    {"name": "Deva Deva", "artist": "Pritam", "known_bpm": 110,
     "category": "modern_bollywood"},
    {"name": "Apna Bana Le", "artist": "Sachin-Jigar", "known_bpm": 79,
     "category": "modern_bollywood"},
    {"name": "Kun Faya Kun", "artist": "A.R. Rahman", "known_bpm": 86,
     "category": "modern_bollywood"},
    {"name": "Raataan Lambiyan", "artist": "Tanishk Bagchi", "known_bpm": 79,
     "category": "modern_bollywood"},
    {"name": "Jashn-E-Bahaaraa", "artist": "A.R. Rahman", "known_bpm": 80,
     "category": "modern_bollywood"},
    {"name": "Tum Se Hi", "artist": "Pritam", "known_bpm": 77,
     "category": "modern_bollywood"},
    {"name": "Naina Da Kya Kasoor", "artist": "Amit Trivedi", "known_bpm": 144,
     "category": "modern_bollywood"},

    # --- English pop (lower risk) ---
    {"name": "One Love", "artist": "Blue", "known_bpm": 104,
     "category": "english", "note": "known failure -10 BPM"},
    {"name": "Levitating", "artist": "Dua Lipa", "known_bpm": 103,
     "category": "english"},
    {"name": "Watermelon Sugar", "artist": "Harry Styles", "known_bpm": 95,
     "category": "english"},
    {"name": "Maps", "artist": "Maroon 5", "known_bpm": 120,
     "category": "english"},
    {"name": "Quit Playing Games (With My Heart)", "artist": "Backstreet Boys", "known_bpm": 101,
     "category": "english"},

    # --- Punjabi (medium risk) ---
    {"name": "Excuses", "artist": "AP Dhillon", "known_bpm": 128,
     "category": "punjabi"},
    {"name": "Softly", "artist": "Karan Aujla", "known_bpm": 100,
     "category": "punjabi"},
    {"name": "Cheques", "artist": "Shubh", "known_bpm": 88,
     "category": "punjabi"},
    {"name": "Amplifier", "artist": "Imran Khan", "known_bpm": 95,
     "category": "punjabi"},

    # --- High risk: common names / remixes ---
    {"name": "One Love", "artist": "Shubh", "known_bpm": 80,
     "category": "common_name", "note": "same name as Blue's One Love"},
    {"name": "Ride It", "artist": "Jay Sean", "known_bpm": 102,
     "category": "common_name", "note": "Hindi version, many remixes exist"},
    {"name": "Maan Meri Jaan", "artist": "King", "known_bpm": 104,
     "category": "common_name"},
]

# Audio-based strategies (have duration + BPM from audio files)
STRATEGIES = [
    ("A_album", DIR_A, "a", "A (album-enriched YT)"),
    ("B_ytmusic", DIR_B, "b", "B (YouTube Music)"),
    ("C_preview", DIR_C, "c", "C (Spotify preview)"),
    ("D_verified", DIR_D, "d", "D (duration-verified YT)"),
]

# All strategies including non-audio ones (F = LLM)
ALL_STRATEGIES = STRATEGIES + [
    ("F_llm", None, "f", "F (LLM GPT-4o-mini)"),
]


def _get_song_from_db(name: str, artist: str) -> dict | None:
    """Look up a song in the DB to get album, duration_ms, and spotify_uri."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM songs WHERE name LIKE ? AND artist LIKE ? LIMIT 1",
        (f"%{name}%", f"%{artist}%"),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _get_audio_duration_seconds(path: Path) -> float | None:
    """Get audio duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else None
    except Exception:
        return None


def _safe_filename(name: str, artist: str) -> str:
    """Create a filesystem-safe filename from song name and artist."""
    safe = f"{artist} - {name}".replace("/", "_").replace("\\", "_")
    return safe[:80] + ".mp3"


def _get_spotify_client():
    """Get authenticated Spotify client for preview URL fetching."""
    from spotify.auth import get_spotify_client
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        return get_spotify_client(conn), conn
    except Exception as e:
        conn.close()
        print(f"ERROR: Could not get Spotify client: {e}")
        return None, None


def download_ab(songs: list[dict]) -> None:
    """Download test songs with strategies A and B (original YouTube strategies)."""
    DIR_A.mkdir(exist_ok=True)
    DIR_B.mkdir(exist_ok=True)

    ytdlp = _find_ytdlp_binary()
    if not ytdlp:
        print("ERROR: yt-dlp not found")
        sys.exit(1)

    for i, song in enumerate(songs, 1):
        db_song = _get_song_from_db(song["name"], song["artist"])
        album = db_song["album"] if db_song else None
        filename = _safe_filename(song["name"], song["artist"])

        print(f"\n[{i}/{len(songs)}] {song['artist']} — {song['name']}")
        if album:
            print(f"  Album: {album}")

        # Strategy A: album-enriched search
        path_a = DIR_A / filename
        if path_a.exists():
            print(f"  Strategy A: already downloaded")
        else:
            ok = download_from_youtube(
                song["name"], song["artist"], path_a,
                album=album, search_strategy="album",
            )
            print(f"  Strategy A (album): {'OK' if ok else 'FAILED'}")

        # Strategy B: YouTube Music search
        path_b = DIR_B / filename
        if path_b.exists():
            print(f"  Strategy B: already downloaded")
        else:
            ok = download_from_youtube(
                song["name"], song["artist"], path_b,
                search_strategy="ytmusic",
            )
            print(f"  Strategy B (ytmusic): {'OK' if ok else 'FAILED'}")


def download_previews(songs: list[dict]) -> None:
    """Strategy C: Download Spotify 30s preview clips."""
    DIR_C.mkdir(exist_ok=True)

    sp, conn = _get_spotify_client()
    if not sp:
        print("ERROR: Spotify auth failed — skipping Strategy C")
        return

    # Collect URIs for songs that need downloading
    uri_map: dict[str, tuple[str, str]] = {}  # uri -> (filename, song label)
    songs_needing_preview: list[str] = []

    for song in songs:
        db_song = _get_song_from_db(song["name"], song["artist"])
        if not db_song or not db_song.get("spotify_uri"):
            print(f"  {song['artist']} — {song['name']}: NOT IN DB, skipping")
            continue

        filename = _safe_filename(song["name"], song["artist"])
        path = DIR_C / filename
        if path.exists():
            continue

        uri = db_song["spotify_uri"]
        uri_map[uri] = (filename, f"{song['artist']} — {song['name']}")
        songs_needing_preview.append(uri)

    if not songs_needing_preview:
        print("  All previews already downloaded or no URIs to fetch")
        conn.close()
        return

    # Batch fetch preview URLs
    print(f"  Fetching preview URLs for {len(songs_needing_preview)} songs...")
    preview_urls = fetch_preview_urls(sp, songs_needing_preview)
    conn.close()

    has_preview = sum(1 for u in preview_urls.values() if u)
    no_preview = len(preview_urls) - has_preview
    print(f"  Preview URL coverage: {has_preview}/{len(preview_urls)} have previews, {no_preview} missing")

    # Download each preview
    for uri, url in preview_urls.items():
        filename, label = uri_map[uri]
        path = DIR_C / filename

        if not url:
            print(f"  {label}: NO PREVIEW URL")
            continue

        ok = download_preview(url, path)
        print(f"  {label}: {'OK' if ok else 'FAILED'}")


def download_verified_youtube(songs: list[dict]) -> None:
    """Strategy D: Duration-verified YouTube downloads."""
    DIR_D.mkdir(exist_ok=True)

    ytdlp = _find_ytdlp_binary()
    if not ytdlp:
        print("ERROR: yt-dlp not found — skipping Strategy D")
        return

    for i, song in enumerate(songs, 1):
        db_song = _get_song_from_db(song["name"], song["artist"])
        album = db_song["album"] if db_song else None
        duration_ms = db_song["duration_ms"] if db_song else None
        filename = _safe_filename(song["name"], song["artist"])
        path = DIR_D / filename

        print(f"\n[{i}/{len(songs)}] {song['artist']} — {song['name']}")

        if path.exists():
            print(f"  Strategy D: already downloaded")
            continue

        if not duration_ms:
            print(f"  Strategy D: NO duration_ms in DB, skipping")
            continue

        expected_s = duration_ms / 1000.0
        ok = download_from_youtube_verified(
            song["name"], song["artist"], path,
            expected_duration_s=expected_s,
            album=album,
        )
        status = "OK" if ok else "FAILED (no match within ±15s)"
        print(f"  Strategy D (verified, expect {expected_s:.0f}s): {status}")


def estimate_llm_bpm(songs: list[dict]) -> list[dict]:
    """Experiment F: Estimate BPM for all songs via GPT-4o-mini.

    Sends all 25 songs in one API call with structured output.
    Returns updated results with f_bpm, f_bpm_delta, f_status fields.
    """
    import os
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        # Try loading from .env
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in environment or .env")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # Build song list for the prompt
    song_lines = []
    for i, song in enumerate(songs):
        db_song = _get_song_from_db(song["name"], song["artist"])
        album = db_song["album"] if db_song else "Unknown"
        song_lines.append(f"{i+1}. \"{song['name']}\" by {song['artist']} (album: {album})")

    prompt = (
        "For each song below, estimate the BPM (beats per minute) as an integer. "
        "Use your knowledge of these songs. Return a JSON array of objects with "
        "\"index\" (1-based) and \"bpm\" (integer) fields, one per song.\n\n"
        + "\n".join(song_lines)
    )

    print(f"  Sending {len(songs)} songs to GPT-4o-mini...")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "bpm_estimates",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "songs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer"},
                                    "bpm": {"type": "integer"},
                                },
                                "required": ["index", "bpm"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["songs"],
                    "additionalProperties": False,
                },
            },
        },
    )

    result_json = json.loads(response.choices[0].message.content)
    bpm_by_index = {item["index"]: item["bpm"] for item in result_json["songs"]}

    print(f"  Got {len(bpm_by_index)} BPM estimates")

    # Load existing results
    existing: dict[str, dict] = {}
    if RESULTS_PATH.exists():
        for r in json.loads(RESULTS_PATH.read_text()):
            key = f"{r['artist']}:{r['name']}"
            existing[key] = r

    results = []
    for i, song in enumerate(songs):
        key = f"{song['artist']}:{song['name']}"
        entry = existing.get(key, {
            "name": song["name"],
            "artist": song["artist"],
            "category": song["category"],
            "known_bpm": song.get("known_bpm"),
            "note": song.get("note", ""),
        })

        llm_bpm = bpm_by_index.get(i + 1)
        entry["f_bpm"] = llm_bpm
        if llm_bpm and song.get("known_bpm"):
            delta = llm_bpm - song["known_bpm"]
            entry["f_bpm_delta"] = delta
            entry["f_status"] = "OK" if abs(delta) <= 5 else "BPM_OFF"
        else:
            entry["f_bpm_delta"] = None
            entry["f_status"] = "missing"

        print(f"  {song['artist']} — {song['name']}: "
              f"LLM={llm_bpm} known={song.get('known_bpm')} "
              f"delta={entry['f_bpm_delta']} → {entry['f_status']}")

        results.append(entry)

    # Save
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {RESULTS_PATH}")
    return results


def analyze_all(songs: list[dict], strategies: list[str] | None = None) -> list[dict]:
    """Run duration + BPM analysis on all downloaded files.

    Args:
        songs: Test song list.
        strategies: Which strategy prefixes to analyze (e.g. ["c", "d"]).
                    None = all strategies.
    """
    try:
        import essentia.standard as es
    except ImportError:
        print("ERROR: essentia not installed")
        sys.exit(1)

    # Load existing results to preserve prior strategy data
    existing: dict[str, dict] = {}
    if RESULTS_PATH.exists():
        for r in json.loads(RESULTS_PATH.read_text()):
            key = f"{r['artist']}:{r['name']}"
            existing[key] = r

    # Determine which strategies to process
    active_strategies = [
        s for s in STRATEGIES
        if strategies is None or s[2] in strategies
    ]

    results = []

    for i, song in enumerate(songs, 1):
        db_song = _get_song_from_db(song["name"], song["artist"])
        spotify_duration_s = db_song["duration_ms"] / 1000 if db_song and db_song["duration_ms"] else None
        filename = _safe_filename(song["name"], song["artist"])

        print(f"\n[{i}/{len(songs)}] {song['artist']} — {song['name']}")

        # Start from existing data if available, else fresh entry
        key = f"{song['artist']}:{song['name']}"
        entry = existing.get(key, {})
        entry.update({
            "name": song["name"],
            "artist": song["artist"],
            "category": song["category"],
            "known_bpm": song.get("known_bpm"),
            "spotify_duration_s": round(spotify_duration_s, 1) if spotify_duration_s else None,
            "note": song.get("note", ""),
        })

        for strategy_name, dir_path, prefix, _label in active_strategies:
            path = dir_path / filename
            if not path.exists():
                entry[f"{prefix}_duration_s"] = None
                entry[f"{prefix}_duration_delta_s"] = None
                entry[f"{prefix}_bpm"] = None
                entry[f"{prefix}_bpm_delta"] = None
                entry[f"{prefix}_status"] = "missing"
                continue

            # Duration check
            duration = _get_audio_duration_seconds(path)
            entry[f"{prefix}_duration_s"] = round(duration, 1) if duration else None

            if duration and spotify_duration_s:
                delta = round(duration - spotify_duration_s, 1)
                entry[f"{prefix}_duration_delta_s"] = delta
            else:
                entry[f"{prefix}_duration_delta_s"] = None

            # BPM check
            try:
                audio = es.MonoLoader(filename=str(path), sampleRate=44100)()
                bpm, confidence = _estimate_bpm(audio, es)
                entry[f"{prefix}_bpm"] = bpm
                entry[f"{prefix}_bpm_confidence"] = round(confidence, 3)
                if bpm and song.get("known_bpm"):
                    entry[f"{prefix}_bpm_delta"] = bpm - song["known_bpm"]
                else:
                    entry[f"{prefix}_bpm_delta"] = None
            except Exception as e:
                entry[f"{prefix}_bpm"] = None
                entry[f"{prefix}_bpm_delta"] = None
                entry[f"{prefix}_bpm_confidence"] = None
                print(f"  {strategy_name} BPM failed: {e}")

            # Status: duration delta > 20s = likely wrong version
            dur_delta = abs(entry[f"{prefix}_duration_delta_s"] or 0)
            bpm_delta = abs(entry[f"{prefix}_bpm_delta"] or 0)
            if dur_delta > 20:
                entry[f"{prefix}_status"] = "WRONG_VERSION"
            elif bpm_delta > 5:
                entry[f"{prefix}_status"] = "BPM_OFF"
            else:
                entry[f"{prefix}_status"] = "OK"

            print(f"  {strategy_name}: dur={entry[f'{prefix}_duration_s']}s "
                  f"(delta={entry[f'{prefix}_duration_delta_s']}s) "
                  f"BPM={entry[f'{prefix}_bpm']} "
                  f"(delta={entry[f'{prefix}_bpm_delta']}) "
                  f"→ {entry[f'{prefix}_status']}")

        results.append(entry)

    # Save results
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {RESULTS_PATH}")
    return results


def print_report(results: list[dict] | None = None) -> None:
    """Print a formatted comparison report across all strategies."""
    if results is None:
        if not RESULTS_PATH.exists():
            print("No results found. Run --analyze first.")
            return
        results = json.loads(RESULTS_PATH.read_text())

    # Only show strategies that have at least one non-missing result
    active_prefixes = []
    for _name, _dir, prefix, label in ALL_STRATEGIES:
        has_data = any(r.get(f"{prefix}_status") and r[f"{prefix}_status"] != "missing"
                       for r in results)
        if has_data:
            active_prefixes.append((prefix, label))

    print("\n" + "=" * 140)
    print("AUDIO SOURCE EXPERIMENT — COMPARISON REPORT")
    print("=" * 140)

    # Per-song table
    # Build header dynamically based on active strategies
    header = f"{'Song':<40} {'Known':>5}"
    for prefix, label in active_prefixes:
        header += f" | {prefix.upper()} bpmΔ {prefix.upper()} status  "
    print(f"\n{header}")
    print("-" * 140)

    # Tallies per strategy
    tallies: dict[str, dict[str, int]] = {
        p: {"OK": 0, "BPM_OFF": 0, "WRONG_VERSION": 0, "missing": 0}
        for p, _ in active_prefixes
    }

    for r in results:
        label = f"{r['artist'][:18]} — {r['name'][:18]}"
        line = f"{label:<40} {r.get('known_bpm', ''):>5}"

        for prefix, _plabel in active_prefixes:
            bpm_delta = r.get(f"{prefix}_bpm_delta")
            status = r.get(f"{prefix}_status", "missing")

            bpm_str = f"{bpm_delta:+d}" if bpm_delta is not None else "—"
            line += f" | {bpm_str:>7} {status:<14}"

            tallies[prefix][status] = tallies[prefix].get(status, 0) + 1

        print(line)

    print("-" * 140)

    # Summary
    print(f"\n{'SUMMARY':^140}")
    print(f"{'Strategy':<30} {'OK':>5} {'BPM_OFF':>8} {'WRONG_VER':>10} {'Missing':>8} {'Accuracy':>10}")
    print("-" * 75)

    best_ok = 0
    best_label = ""
    for prefix, label in active_prefixes:
        t = tallies[prefix]
        ok = t["OK"]
        off = t["BPM_OFF"]
        wrong = t["WRONG_VERSION"]
        miss = t["missing"]
        attempted = 25 - miss
        accuracy = f"{ok}/{attempted}" if attempted > 0 else "—"
        print(f"{label:<30} {ok:>5} {off:>8} {wrong:>10} {miss:>8} {accuracy:>10}")

        if ok > best_ok:
            best_ok = ok
            best_label = label

    # Combined coverage analysis: best source per song
    print(f"\n{'COMBINED COVERAGE (best source per song)':^140}")
    print("-" * 75)

    combined_ok = 0
    combined_source: dict[str, int] = {}
    uncovered = 0

    for r in results:
        best_for_song = None
        for prefix, label in active_prefixes:
            status = r.get(f"{prefix}_status", "missing")
            if status == "OK":
                best_for_song = label
                break  # Take first OK strategy in priority order

        if best_for_song:
            combined_ok += 1
            combined_source[best_for_song] = combined_source.get(best_for_song, 0) + 1
        else:
            uncovered += 1

    print(f"  Songs with ≤±5 BPM from at least one source: {combined_ok}/25")
    for src, count in sorted(combined_source.items(), key=lambda x: -x[1]):
        print(f"    {src}: {count} songs")
    if uncovered:
        print(f"  Uncovered (no source within ±5 BPM): {uncovered}")

    # Per-category breakdown (compact)
    categories = sorted(set(r["category"] for r in results))
    print(f"\n{'PER-CATEGORY BREAKDOWN':^140}")
    cat_header = f"{'Category':<20}"
    for prefix, label in active_prefixes:
        cat_header += f" {prefix.upper()}_OK"
    print(cat_header)

    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        line = f"{cat:<20}"
        for prefix, _ in active_prefixes:
            ok_count = sum(1 for r in cat_results if r.get(f"{prefix}_status") == "OK")
            total = len(cat_results)
            line += f" {ok_count}/{total}  "
        print(line)

    print(f"\n→ Best single strategy: {best_label} ({best_ok}/25 OK)")
    print(f"→ Combined coverage: {combined_ok}/25 OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audio source experiment")
    parser.add_argument("--download", action="store_true", help="Download audio files")
    parser.add_argument("--analyze", action="store_true", help="Run BPM + duration analysis")
    parser.add_argument("--report", action="store_true", help="Print comparison report")
    parser.add_argument(
        "--strategy", type=str, default=None,
        help="Run only specific strategy: a, b, c, d, f or comma-separated (e.g. c,d)",
    )
    args = parser.parse_args()

    run_all = not (args.download or args.analyze or args.report)
    requested = set(args.strategy.lower().split(",")) if args.strategy else None

    if run_all or args.download:
        print("=== DOWNLOADING ===")
        if requested is None or requested & {"a", "b"}:
            download_ab(TEST_SONGS)
        if requested is None or "c" in requested:
            print("\n--- Strategy C: Spotify Previews ---")
            download_previews(TEST_SONGS)
        if requested is None or "d" in requested:
            print("\n--- Strategy D: Duration-verified YouTube ---")
            download_verified_youtube(TEST_SONGS)

    if run_all or args.analyze:
        print("\n=== ANALYZING ===")
        # Route F to its dedicated function
        if requested and "f" in requested:
            print("\n--- Experiment F: LLM BPM (GPT-4o-mini) ---")
            results = estimate_llm_bpm(TEST_SONGS)
        else:
            strategy_filter = list(requested) if requested else None
            results = analyze_all(TEST_SONGS, strategies=strategy_filter)
    else:
        results = None

    if run_all or args.report:
        print_report(results)


if __name__ == "__main__":
    main()
