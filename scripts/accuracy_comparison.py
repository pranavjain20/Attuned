"""Compare OLD vs NEW vs NEW+BLEND neurological scoring accuracy on 25-song test set.

Measures how well each scoring approach assigns the correct dominant neurological
bucket (PARA/GRND/SYMP) based on human-labeled energy levels.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from classification.llm_classifier import _blend_neuro_scores, _is_indian_song
from classification.profiler import (
    NEUTRAL_BPM,
    NEUTRAL_FLOAT,
    compute_neurological_profile,
    gaussian,
    sigmoid_decay,
    sigmoid_rise,
)
from config import DB_PATH

# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

test_songs = [
    ('Levitating', 'Dua Lipa', 'english', 'high'),
    ('Photograph', 'Ed Sheeran', 'english', 'low'),
    ('Blinding Lights', 'The Weeknd', 'english', 'high'),
    ('Locked out of Heaven', 'Bruno Mars', 'english', 'high'),
    ('Love Yourself', 'Justin Bieber', 'english', 'low'),
    ('As It Was', 'Harry Styles', 'english', 'mid'),
    ('Die For You', 'The Weeknd', 'english', 'low'),
    ('Night Changes', 'One Direction', 'english', 'mid'),
    ('Namo Namo', 'Amit Trivedi', 'popular_indian', 'low'),
    ('Deva Deva', 'Pritam', 'popular_indian', 'mid'),
    ('Kajra Re', 'Shankar-Ehsaan-Loy', 'popular_indian', 'high'),
    ('Chedkhaniyaan', 'Shankar-Ehsaan-Loy', 'popular_indian', 'mid'),
    ('Tere Liye', 'Atif Aslam', 'popular_indian', 'mid'),
    ('In Dino', 'Pritam', 'popular_indian', 'low-mid'),
    ('Softly', 'Karan Aujla', 'popular_indian', 'mid'),
    ('Chunnari Chunnari', 'Abhijeet', 'popular_indian', 'high'),
    ("Bernie's Chalisa", 'Krishna Das', 'obscure_indian', 'low'),
    ('Shiv Kailash', 'Rishab Rikhiram Sharma', 'obscure_indian', 'low'),
    ('Hanuman Chalisa (Lo-fi)', 'Rasraj Ji Maharaj', 'obscure_indian', 'mid'),
    ('Dhurandhar', 'Shashwat Sachdev', 'obscure_indian', 'high'),
    ('Haaye Oye', 'QARAN', 'obscure_indian', 'mid-high'),
    ('Shararat', 'Shashwat Sachdev', 'obscure_indian', 'high'),
    ('Ishq Jalakar', 'Shashwat Sachdev', 'obscure_indian', 'mid'),
    ('Panwadi', 'Khesari Lal Yadav', 'obscure_indian', 'high'),
    ('Shankara', 'Rishab Rikhiram Sharma', 'obscure_indian', 'low'),
]

energy_to_expected = {
    'low': 'PARA', 'low-mid': 'PARA', 'mid': 'GRND', 'mid-high': 'SYMP', 'high': 'SYMP',
}

BUCKET_KEYS = {'PARA': 'parasympathetic', 'SYMP': 'sympathetic', 'GRND': 'grounding'}


# ---------------------------------------------------------------------------
# OLD formula (hardcoded old parameters)
# ---------------------------------------------------------------------------

def old_compute_parasympathetic(
    bpm: float, energy: float, acousticness: float,
    instrumentalness: float, valence: float, mode: str | None, danceability: float,
) -> float:
    tempo = sigmoid_decay(bpm, 60, 90) * 0.35
    energy_s = (1.0 - energy) * 0.25
    acoustic_s = acousticness * 0.10
    instrum_s = instrumentalness * 0.10
    valence_s = gaussian(valence, 0.35, 0.2) * 0.10
    mode_s = (1.0 if mode == "major" else 0.5) * 0.05
    dance_s = gaussian(danceability, 0.3, 0.2) * 0.05
    return tempo + energy_s + acoustic_s + instrum_s + valence_s + mode_s + dance_s


def old_compute_sympathetic(
    bpm: float, energy: float, acousticness: float,
    instrumentalness: float, valence: float, mode: str | None, danceability: float,
) -> float:
    tempo = sigmoid_rise(bpm, 100, 130) * 0.35
    energy_s = energy * 0.25
    acoustic_s = (1.0 - acousticness) * 0.10
    instrum_s = (1.0 - instrumentalness) * 0.10
    valence_s = valence * 0.10
    mode_s = (0.8 if mode == "major" else 1.0) * 0.05
    dance_s = danceability * 0.05
    return tempo + energy_s + acoustic_s + instrum_s + valence_s + mode_s + dance_s


def old_compute_grounding(
    bpm: float, energy: float, acousticness: float,
    instrumentalness: float, valence: float, mode: str | None, danceability: float,
) -> float:
    tempo = gaussian(bpm, 75, 15) * 0.30
    energy_s = gaussian(energy, 0.35, 0.15) * 0.20
    acoustic_s = acousticness * 0.15
    valence_s = gaussian(valence, 0.45, 0.2) * 0.15
    instrum_s = gaussian(instrumentalness, 0.3, 0.3) * 0.10
    mode_s = (1.0 if mode == "major" else 0.6) * 0.05
    dance_s = gaussian(danceability, 0.4, 0.2) * 0.05
    return tempo + energy_s + acoustic_s + instrum_s + valence_s + mode_s + dance_s


def old_compute_profile(
    bpm: float | None, energy: float | None, acousticness: float | None,
    instrumentalness: float | None, valence: float | None, mode: str | None,
    danceability: float | None,
) -> dict[str, float]:
    _bpm = float(bpm) if bpm is not None else NEUTRAL_BPM
    _energy = energy if energy is not None else NEUTRAL_FLOAT
    _acousticness = acousticness if acousticness is not None else NEUTRAL_FLOAT
    _instrumentalness = instrumentalness if instrumentalness is not None else NEUTRAL_FLOAT
    _valence = valence if valence is not None else NEUTRAL_FLOAT
    _danceability = danceability if danceability is not None else NEUTRAL_FLOAT

    return {
        "parasympathetic": round(old_compute_parasympathetic(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
        ), 4),
        "sympathetic": round(old_compute_sympathetic(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
        ), 4),
        "grounding": round(old_compute_grounding(
            _bpm, _energy, _acousticness, _instrumentalness, _valence, mode, _danceability,
        ), 4),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dominant_bucket(scores: dict[str, float]) -> str:
    """Return 'PARA', 'SYMP', or 'GRND' based on highest score."""
    p = scores.get("parasympathetic", 0)
    s = scores.get("sympathetic", 0)
    g = scores.get("grounding", 0)
    if p >= s and p >= g:
        return "PARA"
    if s >= p and s >= g:
        return "SYMP"
    return "GRND"


def load_blend_data() -> dict[str, dict]:
    """Load blend experiment results, keyed by (name_lower, artist_lower)."""
    results_path = Path(__file__).parent / "blend_experiment_results.json"
    if not results_path.exists():
        print(f"WARNING: {results_path} not found, NEW+BLEND will be unavailable")
        return {}

    with open(results_path) as f:
        data = json.load(f)

    lookup = {}
    for song in data.get("songs", []):
        key = (song["name"].lower().strip(), song["artist"].lower().strip())
        lookup[key] = song
    return lookup


def find_song_in_db(
    conn: sqlite3.Connection, name: str, artist: str,
) -> dict | None:
    """Find a song's classification by name/artist match (case-insensitive, LIKE for partial)."""
    row = conn.execute(
        """SELECT s.name, s.artist, sc.*
           FROM songs s
           JOIN song_classifications sc ON s.spotify_uri = sc.spotify_uri
           WHERE LOWER(s.name) LIKE ? AND LOWER(s.artist) LIKE ?
           LIMIT 1""",
        (f"%{name.lower()}%", f"%{artist.lower()}%"),
    ).fetchone()
    if row:
        d = dict(row)
        # Deserialize JSON tags
        for tag_key in ("mood_tags", "genre_tags"):
            if d.get(tag_key) and isinstance(d[tag_key], str):
                d[tag_key] = json.loads(d[tag_key])
        return d
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    blend_data = load_blend_data()

    # Collect results
    results = []
    missing = []

    for name, artist, category, energy_label in test_songs:
        expected = energy_to_expected[energy_label]

        db_row = find_song_in_db(conn, name, artist)
        if db_row is None:
            missing.append(f"{name} — {artist}")
            continue

        # Extract properties from DB
        bpm = db_row.get("bpm")
        energy = db_row.get("energy")
        acousticness = db_row.get("acousticness")
        instrumentalness = db_row.get("instrumentalness")
        valence = db_row.get("valence")
        mode = db_row.get("mode")
        danceability = db_row.get("danceability")
        genre_tags = db_row.get("genre_tags")

        # A) OLD formula
        old_scores = old_compute_profile(
            bpm, energy, acousticness, instrumentalness, valence, mode, danceability,
        )
        old_bucket = dominant_bucket(old_scores)

        # B) NEW formula (current profiler.py)
        new_scores = compute_neurological_profile(
            bpm, energy, acousticness, instrumentalness, valence, mode, danceability,
        )
        new_bucket = dominant_bucket(new_scores)

        # C) NEW + BLEND
        blend_bucket = None
        blend_scores = None

        # Try to find direct LLM scores from blend experiment results
        blend_entry = None
        for bkey, bval in blend_data.items():
            if bkey[0] in name.lower() or name.lower() in bkey[0]:
                if bkey[1] in artist.lower() or artist.lower() in bkey[1]:
                    blend_entry = bval
                    break

        if blend_entry and blend_entry.get("direct"):
            direct = blend_entry["direct"]
            llm_para = direct.get("p")
            llm_symp = direct.get("s")
            llm_grounding = direct.get("g")

            blend_scores = _blend_neuro_scores(
                new_scores, llm_para, llm_symp, llm_grounding, genre_tags,
            )
            blend_bucket = dominant_bucket(blend_scores)

        # Determine change status
        old_correct = old_bucket == expected
        new_correct = new_bucket == expected
        blend_correct = blend_bucket == expected if blend_bucket else None

        if old_correct and new_correct:
            status = "same"
        elif not old_correct and new_correct:
            status = "FIX"
        elif old_correct and not new_correct:
            status = "REG"
        else:
            status = "same"  # both wrong

        results.append({
            "name": name,
            "artist": artist,
            "category": category,
            "energy": energy_label,
            "expected": expected,
            "old_bucket": old_bucket,
            "old_correct": old_correct,
            "new_bucket": new_bucket,
            "new_correct": new_correct,
            "blend_bucket": blend_bucket,
            "blend_correct": blend_correct,
            "status": status,
            "old_scores": old_scores,
            "new_scores": new_scores,
            "blend_scores": blend_scores,
        })

    conn.close()

    if missing:
        print(f"\nWARNING: {len(missing)} songs not found in DB:")
        for m in missing:
            print(f"  - {m}")
        print()

    # -----------------------------------------------------------------------
    # Per-song comparison table
    # -----------------------------------------------------------------------
    print("=" * 110)
    print("ACCURACY COMPARISON: OLD vs NEW vs NEW+BLEND")
    print("=" * 110)
    print()
    print(f"{'Song':<32} {'Cat':<10} {'Exp':<5} "
          f"{'OLD':<5} {'OK?':<4} "
          f"{'NEW':<5} {'OK?':<4} "
          f"{'BLEND':<6} {'OK?':<4} "
          f"{'Status':<6}")
    print("-" * 110)

    for r in results:
        song_display = r["name"][:30]
        blend_str = r["blend_bucket"] if r["blend_bucket"] else "N/A"
        blend_ok = "Y" if r["blend_correct"] else ("N" if r["blend_correct"] is False else "-")

        print(f"{song_display:<32} {r['category']:<10} {r['expected']:<5} "
              f"{r['old_bucket']:<5} {'Y' if r['old_correct'] else 'N':<4} "
              f"{r['new_bucket']:<5} {'Y' if r['new_correct'] else 'N':<4} "
              f"{blend_str:<6} {blend_ok:<4} "
              f"{r['status']:<6}")

    # -----------------------------------------------------------------------
    # Summary by category
    # -----------------------------------------------------------------------
    print()
    print("=" * 80)
    print("SUMMARY BY CATEGORY")
    print("=" * 80)

    categories = ["english", "popular_indian", "obscure_indian"]

    print(f"\n{'Category':<18} {'Count':<7} "
          f"{'OLD':<12} {'NEW':<12} {'NEW+BLEND':<12}")
    print("-" * 70)

    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        n = len(cat_results)
        old_acc = sum(1 for r in cat_results if r["old_correct"]) / n if n else 0
        new_acc = sum(1 for r in cat_results if r["new_correct"]) / n if n else 0
        blend_results = [r for r in cat_results if r["blend_correct"] is not None]
        blend_n = len(blend_results)
        blend_acc = sum(1 for r in blend_results if r["blend_correct"]) / blend_n if blend_n else 0

        print(f"{cat:<18} {n:<7} "
              f"{old_acc:>5.0%} ({sum(1 for r in cat_results if r['old_correct'])}/{n})  "
              f"{new_acc:>5.0%} ({sum(1 for r in cat_results if r['new_correct'])}/{n})  "
              f"{blend_acc:>5.0%} ({sum(1 for r in blend_results if r['blend_correct'])}/{blend_n})")

    # Overall
    n = len(results)
    old_total = sum(1 for r in results if r["old_correct"])
    new_total = sum(1 for r in results if r["new_correct"])
    blend_valid = [r for r in results if r["blend_correct"] is not None]
    blend_n = len(blend_valid)
    blend_total = sum(1 for r in blend_valid if r["blend_correct"])

    print("-" * 70)
    print(f"{'OVERALL':<18} {n:<7} "
          f"{old_total/n:>5.0%} ({old_total}/{n})  "
          f"{new_total/n:>5.0%} ({new_total}/{n})  "
          f"{blend_total/blend_n:>5.0%} ({blend_total}/{blend_n})" if blend_n else "")

    # -----------------------------------------------------------------------
    # Fixes and regressions
    # -----------------------------------------------------------------------
    fixes = [r for r in results if r["status"] == "FIX"]
    regressions = [r for r in results if r["status"] == "REG"]

    print()
    print("=" * 80)
    print("FIXES (NEW corrected OLD failures)")
    print("=" * 80)
    if fixes:
        for r in fixes:
            print(f"  {r['name']:<30} expected={r['expected']}, "
                  f"old={r['old_bucket']}, new={r['new_bucket']}")
    else:
        print("  None")

    print()
    print("=" * 80)
    print("REGRESSIONS (NEW broke OLD successes)")
    print("=" * 80)
    if regressions:
        for r in regressions:
            print(f"  {r['name']:<30} expected={r['expected']}, "
                  f"old={r['old_bucket']}, new={r['new_bucket']}")
    else:
        print("  None")

    # Blend-specific changes vs NEW-only
    blend_fixes = [r for r in results
                   if r["blend_correct"] is True and not r["new_correct"]]
    blend_regs = [r for r in results
                  if r["blend_correct"] is False and r["new_correct"]]

    print()
    print("=" * 80)
    print("BLEND FIXES (BLEND corrected NEW-only failures)")
    print("=" * 80)
    if blend_fixes:
        for r in blend_fixes:
            print(f"  {r['name']:<30} expected={r['expected']}, "
                  f"new={r['new_bucket']}, blend={r['blend_bucket']}")
    else:
        print("  None")

    print()
    print("=" * 80)
    print("BLEND REGRESSIONS (BLEND broke NEW-only successes)")
    print("=" * 80)
    if blend_regs:
        for r in blend_regs:
            print(f"  {r['name']:<30} expected={r['expected']}, "
                  f"new={r['new_bucket']}, blend={r['blend_bucket']}")
    else:
        print("  None")

    print()


if __name__ == "__main__":
    main()
