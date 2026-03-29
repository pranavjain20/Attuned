"""Test categorical opening_style approach for opening energy classification.

Instead of asking the LLM for a continuous 0.0-1.0 float (which it compresses
to energy - 0.10), asks a categorical question the LLM can answer from cultural
knowledge, then maps categories to numeric values.

Hypothesis: LLMs are better at categorical classification than continuous
estimation (Day 4 lesson: LLMs compress continuous scales).
"""

import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

# Load .env from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# ---------------------------------------------------------------------------
# Category → numeric mapping
# ---------------------------------------------------------------------------
OPENING_STYLE_MAP = {
    "instant_energy": 0.9,
    "moderate_start": 0.6,
    "slow_build": 0.3,
    "quiet_intro": 0.1,
}

# ---------------------------------------------------------------------------
# Test songs with known current (broken) values
# ---------------------------------------------------------------------------
TEST_SONGS = [
    {"name": "Speak Now (Taylor's Version)", "artist": "Taylor Swift", "album": "Speak Now (Taylor's Version)", "duration_ms": 242473, "current_energy": 0.5, "current_opening_energy": 0.4},
    {"name": "Si Antes Te Hubiera Conocido", "artist": "KAROL G", "album": "Si Antes Te Hubiera Conocido", "duration_ms": 195824, "current_energy": 0.9, "current_opening_energy": 0.8},
    {"name": "Jawani Jan-E-Man", "artist": "Asha Bhosle", "album": "Asha Natkhat Ladi", "duration_ms": 335958, "current_energy": 0.4, "current_opening_energy": 0.3},
    {"name": "Party Rock Anthem", "artist": "LMFAO", "album": "Sorry For Party Rocking", "duration_ms": 262146, "current_energy": 1.0, "current_opening_energy": None},
    {"name": "Impatient", "artist": "Basstian", "album": "Impatient", "duration_ms": 150952, "current_energy": 0.7, "current_opening_energy": 0.6},
    {"name": "Photograph", "artist": "Ed Sheeran", "album": "x", "duration_ms": 258986, "current_energy": 0.25, "current_opening_energy": None},
    {"name": "Kun Faya Kun", "artist": "A.R. Rahman", "album": "Rockstar", "duration_ms": 470500, "current_energy": 0.38, "current_opening_energy": None},
    {"name": "luther (with sza)", "artist": "Kendrick Lamar", "album": "GNX", "duration_ms": 177598, "current_energy": 0.8, "current_opening_energy": 0.7},
    {"name": "Shararat", "artist": "Shashwat Sachdev", "album": "Dhurandhar", "duration_ms": 224083, "current_energy": 0.5, "current_opening_energy": 0.4},
    {"name": "Hurts Me", "artist": "Tory Lanez", "album": "Hurts Me", "duration_ms": 140800, "current_energy": 0.7, "current_opening_energy": 0.6},
]

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a music database. For each song, classify HOW THE SONG OPENS in the first 15 seconds.

Return a JSON object with a "songs" array. Each element must have:
- "title": exact song title (for matching)
- "artist": exact artist name (for matching)
- "opening_style": one of ["instant_energy", "moderate_start", "slow_build", "quiet_intro"]
  - "instant_energy" = beat/drop starts immediately, full energy from second 1 (e.g. Party Rock Anthem, reggaeton drops)
  - "moderate_start" = clear rhythm and beat from the start but not maximal intensity (most pop songs with a verse)
  - "slow_build" = starts noticeably quieter than the chorus, builds energy over 15-30 seconds (intros, builds)
  - "quiet_intro" = opens with silence, whisper, solo instrument, spoken word, or ambient sound before any beat
- "reasoning": one sentence explaining what you hear in the first 15 seconds

Rules:
- Think about the ACTUAL FIRST 15 SECONDS of each specific song/recording, not the genre's typical opening.
- Return ONLY valid JSON. No markdown, no explanations outside the JSON."""


def build_prompt(songs: list[dict]) -> str:
    lines = ["Classify the opening style of these songs:\n"]
    for i, song in enumerate(songs, 1):
        dur_min = song["duration_ms"] / 60000
        lines.append(
            f'{i}. "{song["name"]}" by {song["artist"]} '
            f'(album: {song["album"]}) [duration: {dur_min:.1f}min]'
        )
    return "\n".join(lines)


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    prompt = build_prompt(TEST_SONGS)

    print("=" * 80)
    print("CATEGORICAL OPENING STYLE TEST")
    print("=" * 80)
    print(f"\nSending {len(TEST_SONGS)} songs to GPT-4o-mini...\n")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=60,
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw)
    results = parsed.get("songs", [])

    # Print results
    print(f"{'Song':<42} {'Category':<18} {'Mapped':>7}  {'Old':>7}  {'Energy':>7}  {'Reasoning'}")
    print("-" * 140)

    for i, song in enumerate(TEST_SONGS):
        if i < len(results):
            r = results[i]
            category = r.get("opening_style", "MISSING")
            reasoning = r.get("reasoning", "")
            mapped = OPENING_STYLE_MAP.get(category, "???")
            old = song["current_opening_energy"]
            old_str = f"{old:.1f}" if old is not None else "None"
            energy = song["current_energy"]

            # Flag if the old value was just energy - 0.1
            delta_flag = ""
            if old is not None and abs(old - (energy - 0.1)) < 0.05:
                delta_flag = " [was energy-0.1]"

            print(
                f'{song["name"]:<42} {category:<18} {mapped:>7.1f}  '
                f'{old_str:>7}  {energy:>7.2f}  {reasoning}{delta_flag}'
            )
        else:
            print(f'{song["name"]:<42} NO RESULT')

    # Summary: distribution of categories
    categories = [r.get("opening_style") for r in results]
    print("\n" + "=" * 80)
    print("DISTRIBUTION:")
    for cat in ["instant_energy", "moderate_start", "slow_build", "quiet_intro"]:
        count = categories.count(cat)
        print(f"  {cat:<18} = {count} songs (mapped to {OPENING_STYLE_MAP[cat]})")

    # Check: are the mapped values more spread out than old energy-0.1 pattern?
    old_values = [s["current_opening_energy"] for s in TEST_SONGS if s["current_opening_energy"] is not None]
    new_values = [OPENING_STYLE_MAP.get(r.get("opening_style"), 0.5) for r in results]

    if old_values:
        old_unique = len(set(old_values))
        new_unique = len(set(new_values))
        print(f"\nDIVERSITY: old had {old_unique} unique values from {len(old_values)} songs, "
              f"new has {new_unique} unique values from {len(new_values)} songs")

    # Print raw JSON for inspection
    print("\n" + "=" * 80)
    print("RAW RESPONSE:")
    print(json.dumps(parsed, indent=2))


if __name__ == "__main__":
    main()
