"""Experiment: Compare 3 LLM prompting approaches for song classification.

Approach A: Baseline (title + artist + album)
Approach B: Rich context (+ duration + Essentia features where available)
Approach C: Rich context + uncertainty guidance

Runs GPT-4o-mini on 25 test songs with each approach, compares results
against ground truth ratings from Pranav.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH, AUDIO_CLIPS_DIR
from classification.audio import uri_to_filename

# ---------------------------------------------------------------------------
# Test songs with ground truth
# ---------------------------------------------------------------------------

GROUND_TRUTH = [
    # (name_query, artist_query, category, energy_bucket, mood)
    # Category: english, popular_indian, obscure_indian
    # Energy: low, low-mid, mid, mid-high, high
    ("Levitating", "Dua Lipa", "english", "high", "energetic/fun"),
    ("Photograph", "Ed Sheeran", "english", "low", "sad/melancholy"),
    ("Blinding Lights", "The Weeknd", "english", "high", "energetic/fun"),
    ("Locked out of Heaven", "Bruno Mars", "english", "mid", "happy/upbeat"),
    ("Love Yourself", "Justin Bieber", "english", "low", "warm/nostalgic"),
    ("As It Was", "Harry Styles", "english", "mid", "happy/upbeat"),
    ("Die For You", "The Weeknd", "english", "low", "sad/melancholy"),
    ("Night Changes", "One Direction", "english", "mid", "warm/nostalgic"),
    ("Namo Namo", "Amit Trivedi", "popular_indian", "low", "peaceful/devotional"),
    ("Deva Deva", "Pritam", "popular_indian", "mid", "peaceful/devotional"),
    ("Kajra Re", "Shankar-Ehsaan-Loy", "popular_indian", "high", "energetic/fun"),
    ("Chedkhaniyaan", "Shankar-Ehsaan-Loy", "popular_indian", "mid", "happy/upbeat"),
    ("Tere Liye", "Atif Aslam", "popular_indian", "mid", "warm/romantic"),
    ("In Dino", "Pritam", "popular_indian", "low-mid", "warm/nostalgic"),
    ("Softly", "Karan Aujla", "popular_indian", "mid", "happy/upbeat"),
    ("Chunnari Chunnari", "Abhijeet", "popular_indian", "high", "fun/energetic"),
    ("Bernie's Chalisa", "Krishna Das", "obscure_indian", "low", "peaceful/devotional"),
    ("Shiv Kailash", "Rishab Rikhiram Sharma", "obscure_indian", "low", "peaceful/devotional"),
    ("Hanuman Chalisa (Lo-fi)", "Rasraj Ji Maharaj", "obscure_indian", "mid", "peaceful/devotional"),
    ("Dhurandhar", "Shashwat Sachdev", "obscure_indian", "high", "intense/hype"),
    ("Haaye Oye", "QARAN", "obscure_indian", "mid-high", "happy/upbeat"),
    ("Shararat", "Shashwat Sachdev", "obscure_indian", "high", "happy/party"),
    ("Ishq Jalakar", "Shashwat Sachdev", "obscure_indian", "mid", "neutral/slightly-energetic"),
    ("Panwadi", "Khesari Lal Yadav", "obscure_indian", "high", "fun/energetic"),
    ("Shankara", "Rishab Rikhiram Sharma", "obscure_indian", "low", "peaceful/devotional"),
]

# Energy bucket to numeric range for scoring
ENERGY_RANGES = {
    "low": (0.0, 0.3),
    "low-mid": (0.2, 0.5),
    "mid": (0.35, 0.65),
    "mid-high": (0.5, 0.8),
    "high": (0.7, 1.0),
}

# Mood to expected valence range
MOOD_VALENCE = {
    "sad/melancholy": (0.0, 0.35),
    "peaceful/devotional": (0.15, 0.55),
    "warm/nostalgic": (0.3, 0.65),
    "warm/romantic": (0.35, 0.7),
    "neutral/slightly-energetic": (0.35, 0.65),
    "happy/upbeat": (0.5, 0.9),
    "happy/party": (0.6, 1.0),
    "fun/energetic": (0.5, 0.9),
    "energetic/fun": (0.5, 0.9),
    "intense/hype": (0.4, 0.85),
}

# Mood to expected danceability range
MOOD_DANCE = {
    "sad/melancholy": (0.0, 0.4),
    "peaceful/devotional": (0.0, 0.4),
    "warm/nostalgic": (0.2, 0.6),
    "warm/romantic": (0.25, 0.65),
    "neutral/slightly-energetic": (0.3, 0.65),
    "happy/upbeat": (0.5, 0.9),
    "happy/party": (0.6, 1.0),
    "fun/energetic": (0.55, 1.0),
    "energetic/fun": (0.55, 1.0),
    "intense/hype": (0.4, 0.85),
}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_A = """You are a music database. For each song, recall the precise values from music databases (Spotify, MusicBrainz, Discogs). Return factual data, not estimates.

Return a JSON object with a "songs" array. Each element must have:
- "title": exact song title (for matching)
- "artist": exact artist name (for matching)
- "bpm": integer tempo in beats per minute (30-300)
- "danceability": float 0.0-1.0 (how suitable for dancing)
- "instrumentalness": float 0.0-1.0 (1.0 = no vocals, 0.0 = full vocals)
- "valence": float 0.0-1.0 (musical positiveness, 1.0 = happy/cheerful, 0.0 = sad/angry)
- "mood_tags": list of 2-4 mood descriptors
- "genre_tags": list of 2-4 genre tags
- "confidence": float 0.0-1.0 (how confident you are recalling actual data vs guessing. 1.0 = exact database match, 0.0 = never seen this song)

Rules:
- Use the FULL 0.0-1.0 range. Quiet acoustic ballads should be near 0.1, not 0.5.
- BPM must be an integer. Look up the actual BPM, don't guess from genre.
- Be honest with confidence — it's better to say 0.3 than to pretend you know a song.
- Return ONLY valid JSON. No markdown, no explanations."""

SYSTEM_B = """You are a music database. For each song, recall the precise values from music databases (Spotify, MusicBrainz, Discogs). Return factual data, not estimates.

Some songs include audio analysis data (energy, acousticness, BPM from Essentia) and duration. Use these as additional signals when available — they are measured from the actual audio.

Return a JSON object with a "songs" array. Each element must have:
- "title": exact song title (for matching)
- "artist": exact artist name (for matching)
- "bpm": integer tempo in beats per minute (30-300)
- "danceability": float 0.0-1.0 (how suitable for dancing)
- "instrumentalness": float 0.0-1.0 (1.0 = no vocals, 0.0 = full vocals)
- "valence": float 0.0-1.0 (musical positiveness, 1.0 = happy/cheerful, 0.0 = sad/angry)
- "mood_tags": list of 2-4 mood descriptors
- "genre_tags": list of 2-4 genre tags
- "confidence": float 0.0-1.0 (how confident you are recalling actual data vs guessing. 1.0 = exact database match, 0.0 = never seen this song)

Rules:
- Use the FULL 0.0-1.0 range. Quiet acoustic ballads should be near 0.1, not 0.5.
- BPM must be an integer. Look up the actual BPM, don't guess from genre.
- When audio features are provided, use them to inform your classification — e.g. if energy=0.15, the song is quiet.
- Be honest with confidence — it's better to say 0.3 than to pretend you know a song.
- Return ONLY valid JSON. No markdown, no explanations."""

SYSTEM_C = """You are a music database. For each song, recall the precise values from music databases (Spotify, MusicBrainz, Discogs). Return factual data, not estimates.

Some songs include audio analysis data (energy, acousticness, BPM from Essentia) and duration. Use these as additional signals when available — they are measured from the actual audio.

Return a JSON object with a "songs" array. Each element must have:
- "title": exact song title (for matching)
- "artist": exact artist name (for matching)
- "bpm": integer tempo in beats per minute (30-300)
- "danceability": float 0.0-1.0 (how suitable for dancing)
- "instrumentalness": float 0.0-1.0 (1.0 = no vocals, 0.0 = full vocals)
- "valence": float 0.0-1.0 (musical positiveness, 1.0 = happy/cheerful, 0.0 = sad/angry)
- "mood_tags": list of 2-4 mood descriptors
- "genre_tags": list of 2-4 genre tags
- "confidence": float 0.0-1.0 (how confident you are recalling actual data vs guessing. 1.0 = exact database match, 0.0 = never seen this song)

Rules:
- Use the FULL 0.0-1.0 range. Quiet acoustic ballads should be near 0.1, not 0.5.
- BPM must be an integer. Look up the actual BPM, don't guess from genre.
- When audio features are provided, use them to inform your classification — e.g. if energy=0.15, the song is quiet.
- IMPORTANT: If you don't recognize a song, DO NOT guess wildly from genre stereotypes. Instead:
  - Use any provided audio features (energy, acousticness, BPM) as your primary signal.
  - Use the duration as a hint (very short = likely energetic/pop, very long = likely devotional/ambient).
  - Infer from the artist's other known work if you recognize the artist but not the song.
  - Set confidence low (0.1-0.3) and keep values conservative (closer to 0.5) for properties you're truly unsure about.
- Be honest with confidence — it's better to say 0.3 than to pretend you know a song.
- Return ONLY valid JSON. No markdown, no explanations."""


def get_songs_from_db():
    """Fetch the 25 test songs with all available metadata."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    songs = []
    for name_q, artist_q, category, energy, mood in GROUND_TRUTH:
        row = conn.execute(
            "SELECT s.spotify_uri, s.name, s.artist, s.album, s.duration_ms "
            "FROM songs s WHERE s.name LIKE ? AND s.artist LIKE ?",
            (f"%{name_q}%", f"%{artist_q}%"),
        ).fetchone()
        if not row:
            print(f"WARNING: Song not found: {name_q} — {artist_q}")
            continue

        # Check for Essentia data
        ess = conn.execute(
            "SELECT bpm, energy, acousticness, key, mode FROM song_classifications WHERE spotify_uri = ?",
            (row["spotify_uri"],),
        ).fetchone()

        songs.append({
            "spotify_uri": row["spotify_uri"],
            "name": row["name"],
            "artist": row["artist"],
            "album": row["album"],
            "duration_ms": row["duration_ms"],
            "essentia_bpm": dict(ess)["bpm"] if ess else None,
            "essentia_energy": dict(ess)["energy"] if ess else None,
            "essentia_acousticness": dict(ess)["acousticness"] if ess else None,
            "essentia_key": dict(ess)["key"] if ess else None,
            "essentia_mode": dict(ess)["mode"] if ess else None,
            "category": category,
            "gt_energy": energy,
            "gt_mood": mood,
        })

    conn.close()
    return songs


def build_prompt_a(songs):
    """Approach A: title + artist + album only."""
    lines = ["Classify these songs:\n"]
    for i, s in enumerate(songs, 1):
        album_str = f" (album: {s['album']})" if s["album"] else ""
        lines.append(f'{i}. "{s["name"]}" by {s["artist"]}{album_str}')
    return "\n".join(lines)


def build_prompt_bc(songs):
    """Approach B/C: title + artist + album + duration + Essentia features."""
    lines = ["Classify these songs:\n"]
    for i, s in enumerate(songs, 1):
        parts = [f'{i}. "{s["name"]}" by {s["artist"]}']
        if s["album"]:
            parts.append(f"(album: {s['album']})")

        # Duration
        if s["duration_ms"]:
            dur_min = s["duration_ms"] / 60000
            parts.append(f"[duration: {dur_min:.1f}min]")

        # Essentia features
        ess_parts = []
        if s["essentia_energy"] is not None:
            ess_parts.append(f"energy={s['essentia_energy']:.2f}")
        if s["essentia_acousticness"] is not None:
            ess_parts.append(f"acousticness={s['essentia_acousticness']:.2f}")
        if s["essentia_bpm"] is not None:
            ess_parts.append(f"measured_bpm={s['essentia_bpm']}")
        if s["essentia_key"] is not None:
            ess_parts.append(f"key={s['essentia_key']} {s['essentia_mode'] or ''}")
        if ess_parts:
            parts.append(f"[audio: {', '.join(ess_parts)}]")

        lines.append(" ".join(parts))
    return "\n".join(lines)


def call_openai(system_prompt, user_prompt):
    """Call GPT-4o-mini and return parsed results."""
    from openai import OpenAI
    from config import get_openai_api_key

    client = OpenAI(api_key=get_openai_api_key())
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    parsed = json.loads(raw)
    usage = response.usage
    return parsed, usage


def score_results(results, songs):
    """Score LLM results against ground truth. Returns per-song and aggregate scores."""
    scored = []
    for i, song in enumerate(songs):
        if i >= len(results.get("songs", [])):
            scored.append({"song": song["name"], "error": "missing from response"})
            continue

        r = results["songs"][i]
        gt_energy = song["gt_energy"]
        gt_mood = song["gt_mood"]

        # Extract LLM values
        llm_valence = r.get("valence", 0.5)
        llm_dance = r.get("danceability", 0.5)
        llm_bpm = r.get("bpm", 100)
        llm_confidence = r.get("confidence", 0.5)

        # Score energy bucket: map BPM + danceability to energy estimate
        # BPM < 80 = low, 80-110 = mid, > 110 = high (rough)
        if llm_bpm < 80:
            llm_energy_bucket = "low"
        elif llm_bpm < 100:
            llm_energy_bucket = "low-mid"
        elif llm_bpm < 120:
            llm_energy_bucket = "mid"
        elif llm_bpm < 135:
            llm_energy_bucket = "mid-high"
        else:
            llm_energy_bucket = "high"

        # Check if energy bucket is close enough
        energy_order = ["low", "low-mid", "mid", "mid-high", "high"]
        gt_idx = energy_order.index(gt_energy)
        llm_idx = energy_order.index(llm_energy_bucket)
        energy_distance = abs(gt_idx - llm_idx)
        energy_correct = energy_distance <= 1  # Within 1 bucket = pass

        # Check valence against mood range
        val_range = MOOD_VALENCE.get(gt_mood, (0.3, 0.7))
        valence_in_range = val_range[0] <= llm_valence <= val_range[1]
        # Also count "close" — within 0.15 of range
        valence_close = (val_range[0] - 0.15) <= llm_valence <= (val_range[1] + 0.15)

        # Check danceability against mood range
        dance_range = MOOD_DANCE.get(gt_mood, (0.3, 0.7))
        dance_in_range = dance_range[0] <= llm_dance <= dance_range[1]

        scored.append({
            "song": song["name"],
            "artist": song["artist"],
            "category": song["category"],
            "gt_energy": gt_energy,
            "gt_mood": gt_mood,
            "llm_bpm": llm_bpm,
            "llm_valence": llm_valence,
            "llm_dance": llm_dance,
            "llm_confidence": llm_confidence,
            "llm_energy_bucket": llm_energy_bucket,
            "energy_correct": energy_correct,
            "energy_distance": energy_distance,
            "valence_in_range": valence_in_range,
            "valence_close": valence_close,
            "dance_in_range": dance_in_range,
        })

    return scored


def print_results(name, scored, usage):
    """Print detailed results for one approach."""
    print(f"\n{'='*80}")
    print(f"  APPROACH {name}")
    print(f"{'='*80}")
    print(f"  Tokens: {usage.prompt_tokens} prompt + {usage.completion_tokens} completion = {usage.total_tokens} total")
    print()

    # Per-song results
    print(f"  {'Song':<35} {'Cat':<8} {'BPM':>4} {'Val':>5} {'Dnc':>5} {'Conf':>5} {'E?':>3} {'V?':>3} {'D?':>3}")
    print(f"  {'-'*35} {'-'*8} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*3} {'-'*3} {'-'*3}")

    for s in scored:
        if "error" in s:
            print(f"  {s['song']:<35} ERROR: {s['error']}")
            continue
        e_mark = "Y" if s["energy_correct"] else "N"
        v_mark = "Y" if s["valence_in_range"] else ("~" if s["valence_close"] else "N")
        d_mark = "Y" if s["dance_in_range"] else "N"
        print(f"  {s['song']:<35} {s['category']:<8} {s['llm_bpm']:>4} {s['llm_valence']:>5.2f} {s['llm_dance']:>5.2f} {s['llm_confidence']:>5.2f} {e_mark:>3} {v_mark:>3} {d_mark:>3}")

    # Aggregate scores
    valid = [s for s in scored if "error" not in s]
    if valid:
        print(f"\n  AGGREGATE SCORES:")
        for cat in ["english", "popular_indian", "obscure_indian", "ALL"]:
            subset = valid if cat == "ALL" else [s for s in valid if s["category"] == cat]
            if not subset:
                continue
            n = len(subset)
            e_acc = sum(1 for s in subset if s["energy_correct"]) / n * 100
            v_acc = sum(1 for s in subset if s["valence_in_range"]) / n * 100
            v_close = sum(1 for s in subset if s["valence_close"]) / n * 100
            d_acc = sum(1 for s in subset if s["dance_in_range"]) / n * 100
            avg_conf = sum(s["llm_confidence"] for s in subset) / n
            avg_e_dist = sum(s["energy_distance"] for s in subset) / n
            label = f"{cat} ({n})"
            print(f"    {label:<25} Energy: {e_acc:5.1f}%  Valence: {v_acc:5.1f}% (close: {v_close:5.1f}%)  Dance: {d_acc:5.1f}%  AvgConf: {avg_conf:.2f}  AvgEnergyDist: {avg_e_dist:.1f}")


def main():
    print("Loading test songs from database...")
    songs = get_songs_from_db()
    print(f"Found {len(songs)} songs")

    # Count Essentia data
    ess_count = sum(1 for s in songs if s["essentia_energy"] is not None)
    print(f"Songs with Essentia data: {ess_count}")

    prompt_a = build_prompt_a(songs)
    prompt_bc = build_prompt_bc(songs)

    print(f"\nPrompt A length: {len(prompt_a)} chars")
    print(f"Prompt B/C length: {len(prompt_bc)} chars")

    # Run all 3 approaches
    print("\n--- Running Approach A (baseline) ---")
    results_a, usage_a = call_openai(SYSTEM_A, prompt_a)
    scored_a = score_results(results_a, songs)
    print_results("A — Baseline", scored_a, usage_a)

    print("\n--- Running Approach B (rich context) ---")
    results_b, usage_b = call_openai(SYSTEM_B, prompt_bc)
    scored_b = score_results(results_b, songs)
    print_results("B — Rich Context", scored_b, usage_b)

    print("\n--- Running Approach C (rich context + uncertainty guidance) ---")
    results_c, usage_c = call_openai(SYSTEM_C, prompt_bc)
    scored_c = score_results(results_c, songs)
    print_results("C — Rich Context + Uncertainty Guidance", scored_c, usage_c)

    # Summary comparison
    print(f"\n{'='*80}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*80}")

    for name, scored in [("A", scored_a), ("B", scored_b), ("C", scored_c)]:
        valid = [s for s in scored if "error" not in s]
        obscure = [s for s in valid if s["category"] == "obscure_indian"]
        all_e = sum(1 for s in valid if s["energy_correct"]) / len(valid) * 100
        all_v = sum(1 for s in valid if s["valence_in_range"]) / len(valid) * 100
        obs_e = sum(1 for s in obscure if s["energy_correct"]) / len(obscure) * 100 if obscure else 0
        obs_v = sum(1 for s in obscure if s["valence_in_range"]) / len(obscure) * 100 if obscure else 0
        obs_conf = sum(s["llm_confidence"] for s in obscure) / len(obscure) if obscure else 0
        print(f"  {name}: Overall energy={all_e:.0f}% valence={all_v:.0f}% | Obscure energy={obs_e:.0f}% valence={obs_v:.0f}% conf={obs_conf:.2f}")

    # Save raw results
    output = {
        "approach_a": results_a,
        "approach_b": results_b,
        "approach_c": results_c,
    }
    output_path = Path(__file__).parent / "confidence_experiment_results.json"
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nRaw results saved to {output_path}")


if __name__ == "__main__":
    main()
