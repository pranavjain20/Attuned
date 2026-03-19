"""Experiment: Targeted BPM correction for suspicious songs.

Tests multiple approaches to fix BPM for songs where the LLM defaults to
genre-typical values (e.g., 120 for anything vaguely Indian).

Approaches:
1. Baseline — current DB values, no changes
2. Single-song targeted re-ask — re-query GPT-4o-mini one song at a time
   with specific context about why the BPM looks suspicious
3. Different model (GPT-4o) — same targeted prompt but with a more capable model
4. Comprehensive re-classification — re-ask for BPM + energy + valence together
   (since BPM isn't the only problem)
5. Best-of combined — pick best BPM from approaches 2-4 using agreement logic

For each approach, recomputes neurological scores and measures bucket accuracy
against ground truth.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH, get_openai_api_key
from classification.profiler import compute_neurological_profile
from openai import OpenAI

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

client = OpenAI(api_key=get_openai_api_key())

test_songs = [
    ('Levitating', 'Dua Lipa', 'english', 'high'),
    ('Photograph', 'Ed Sheeran', 'english', 'low'),
    ('Blinding Lights', 'The Weeknd', 'english', 'high'),
    ('Locked out of Heaven', 'Bruno Mars', 'english', 'mid'),
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

DEVOTIONAL_GENRES = {
    "devotional", "kirtan", "sufi", "bhajan", "spiritual", "chant", "mantra", "prayer",
}

# BPM values that are "round number" suspects — LLMs love these defaults
SUSPICIOUS_ROUND_BPMS = {100, 110, 120, 130, 140}


def dominant(p: float, s: float, g: float) -> str:
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Load song data from DB
# ---------------------------------------------------------------------------

songs_data = []
for name, artist, cat, gt_e in test_songs:
    row = conn.execute('''
        SELECT sc.*, s.name, s.artist, s.album, s.duration_ms
        FROM song_classifications sc
        JOIN songs s ON sc.spotify_uri = s.spotify_uri
        WHERE s.name LIKE ? AND s.artist LIKE ?
    ''', (f'%{name}%', f'%{artist}%')).fetchone()
    if row:
        d = dict(row)
        d['cat'] = cat
        d['gt_e'] = gt_e
        songs_data.append(d)
    else:
        print(f"WARNING: not found: {name} — {artist}")

print(f"Loaded {len(songs_data)} songs from DB\n")


# ---------------------------------------------------------------------------
# Identify suspicious songs
# ---------------------------------------------------------------------------

def parse_genre_tags(raw) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (json.JSONDecodeError, TypeError):
        return []


def is_bpm_suspicious(song: dict) -> tuple[bool, str]:
    """Determine if a song's BPM looks like an LLM default.

    Returns (is_suspicious, reason).
    """
    bpm = song.get('bpm')
    if bpm is None:
        return False, ""

    bpm = int(bpm)
    genre_tags = parse_genre_tags(song.get('genre_tags'))
    energy = song.get('energy', 0.5)
    acousticness = song.get('acousticness', 0.5)

    reasons = []

    # Pattern 1: Round BPM (120 is the most suspicious) + Indian genre
    if bpm in SUSPICIOUS_ROUND_BPMS and any(
        g in {"bollywood", "hindi", "indian", "sufi", "devotional", "punjabi", "bhojpuri"}
        for g in genre_tags
    ):
        reasons.append(f"round BPM ({bpm}) + Indian genre")

    # Pattern 2: Devotional/spiritual genre + BPM > 90 (devotionals are usually slow)
    if any(g in DEVOTIONAL_GENRES for g in genre_tags) and bpm > 90:
        reasons.append(f"devotional genre + high BPM ({bpm})")

    # Pattern 3: BPM = exactly 120 (the most common LLM default)
    if bpm == 120:
        reasons.append("BPM = 120 (most common LLM default)")

    # Pattern 4: High acousticness + low energy + high BPM (contradictory signals)
    if acousticness > 0.7 and energy < 0.5 and bpm > 110:
        reasons.append(f"high acousticness ({acousticness:.2f}) + low energy ({energy:.2f}) + high BPM ({bpm})")

    if reasons:
        return True, "; ".join(reasons)
    return False, ""


suspicious = []
for i, s in enumerate(songs_data):
    is_sus, reason = is_bpm_suspicious(s)
    if is_sus:
        suspicious.append((i, s, reason))

print(f"SUSPICIOUS BPM SONGS ({len(suspicious)}):")
print("-" * 80)
for idx, s, reason in suspicious:
    print(f"  {idx+1:>2}. {s['name'][:35]:<35} BPM={int(s['bpm']):>3}  E={s['energy']:.2f}  A={s['acousticness']:.2f}  Reason: {reason}")
print()


# ---------------------------------------------------------------------------
# Approach 2: Single-song targeted BPM re-ask (GPT-4o-mini)
# ---------------------------------------------------------------------------

def targeted_bpm_reask(song: dict, model: str = "gpt-4o-mini") -> dict:
    """Re-ask for BPM with maximum context, one song at a time."""
    genre_tags = parse_genre_tags(song.get('genre_tags'))
    mood_tags = parse_genre_tags(song.get('mood_tags'))

    duration_min = song.get('duration_ms', 0) / 60000 if song.get('duration_ms') else None

    system = """You are a music tempo expert. Your job is to verify or correct a BPM estimate for a specific song.

LLMs frequently default to 120 BPM for songs they don't know well, especially Indian/Bollywood songs.
The actual tempo of devotional, kirtan, and sufi songs is often 60-85 BPM.
The actual tempo of Bollywood dance numbers is often 130-160 BPM.

Think step by step:
1. What genre/style is this song? (devotional, dance, ballad, etc.)
2. What tempo range is typical for that style?
3. Do you actually know this specific song's tempo, or are you guessing?
4. If you're uncertain, use the audio measurements as clues:
   - Low energy (< 0.4) + high acousticness (> 0.7) → likely slow (60-85 BPM)
   - High energy (> 0.7) + low acousticness (< 0.4) → likely fast (120+ BPM)

Return ONLY a JSON object: {"bpm": <integer>, "confidence": "known"|"estimated"|"uncertain", "reasoning": "<brief explanation>"}"""

    context_parts = [f'Song: "{song["name"]}" by {song["artist"]}']
    if song.get('album'):
        context_parts.append(f'Album: {song["album"]}')
    if genre_tags:
        context_parts.append(f'Genre tags: {", ".join(genre_tags)}')
    if mood_tags:
        context_parts.append(f'Mood tags: {", ".join(mood_tags)}')
    if duration_min:
        context_parts.append(f'Duration: {duration_min:.1f} minutes')
    if song.get('energy') is not None:
        context_parts.append(f'Audio energy: {song["energy"]:.2f} (measured from actual audio, 0=quiet, 1=loud)')
    if song.get('acousticness') is not None:
        context_parts.append(f'Audio acousticness: {song["acousticness"]:.2f} (measured, 0=electronic, 1=acoustic)')

    current_bpm = int(song['bpm'])
    context_parts.append(f'\nA batch classification previously estimated BPM = {current_bpm}.')
    context_parts.append(f'Is {current_bpm} BPM correct for this specific song, or should it be different?')
    context_parts.append('Think carefully about the actual tempo of this specific song, not genre defaults.')

    prompt = "\n".join(context_parts)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"bpm": current_bpm, "confidence": "error", "reasoning": "parse error"}

    return {
        "bpm": result.get("bpm", current_bpm),
        "confidence": result.get("confidence", "unknown"),
        "reasoning": result.get("reasoning", ""),
        "model": model,
        "tokens": response.usage.total_tokens,
    }


# ---------------------------------------------------------------------------
# Approach 4: Comprehensive re-classification (BPM + energy + valence)
# ---------------------------------------------------------------------------

def comprehensive_reask(song: dict, model: str = "gpt-4o-mini") -> dict:
    """Re-ask for BPM, energy perception, and valence — all at once.

    The insight: BPM alone can't fix the scoring. Energy and valence from
    the LLM may also be wrong for obscure songs. Re-asking with focused
    attention on one song gives better results.
    """
    genre_tags = parse_genre_tags(song.get('genre_tags'))
    mood_tags = parse_genre_tags(song.get('mood_tags'))
    duration_min = song.get('duration_ms', 0) / 60000 if song.get('duration_ms') else None

    system = """You are a music analysis expert. Analyze ONE song with careful attention.

Return a JSON object with:
- "bpm": integer tempo (30-300). Do NOT default to 120. Think about the specific song.
- "perceived_energy": float 0.0-1.0. How energizing does this song FEEL to a listener?
  This is about the overall listening experience, not just volume.
  - Slow devotional chant with harmonium = 0.1-0.2
  - Gentle acoustic ballad = 0.2-0.3
  - Mid-tempo pop song = 0.4-0.6
  - Upbeat dance track = 0.7-0.8
  - Intense club banger = 0.8-1.0
- "valence": float 0.0-1.0. Musical positiveness/mood.
- "danceability": float 0.0-1.0.
- "reasoning": brief explanation of your analysis

Think step by step about what this song actually sounds like."""

    context_parts = [f'Analyze: "{song["name"]}" by {song["artist"]}']
    if song.get('album'):
        context_parts.append(f'Album: {song["album"]}')
    if genre_tags:
        context_parts.append(f'Genre: {", ".join(genre_tags)}')
    if mood_tags:
        context_parts.append(f'Mood: {", ".join(mood_tags)}')
    if duration_min:
        context_parts.append(f'Duration: {duration_min:.1f} min')
    if song.get('energy') is not None:
        context_parts.append(f'Measured audio energy: {song["energy"]:.2f}')
    if song.get('acousticness') is not None:
        context_parts.append(f'Measured acousticness: {song["acousticness"]:.2f}')

    prompt = "\n".join(context_parts)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"bpm": int(song['bpm']), "perceived_energy": None, "valence": None,
                "danceability": None, "reasoning": "parse error", "tokens": 0}

    return {
        "bpm": result.get("bpm", int(song['bpm'])),
        "perceived_energy": result.get("perceived_energy"),
        "valence": result.get("valence"),
        "danceability": result.get("danceability"),
        "reasoning": result.get("reasoning", ""),
        "tokens": response.usage.total_tokens,
    }


# ---------------------------------------------------------------------------
# Run all approaches
# ---------------------------------------------------------------------------

print("=" * 90)
print("RUNNING TARGETED BPM CORRECTION EXPERIMENTS")
print("=" * 90)

# Storage for results per approach
# approach_name -> list of (para, symp, grnd) for each song
approach_scores = {}

# ---------------------------------------------------------------------------
# Approach 1: Baseline (current DB values)
# ---------------------------------------------------------------------------
print("\n--- Approach 1: BASELINE (current DB) ---")
baseline_scores = []
for s in songs_data:
    baseline_scores.append({
        'p': s['parasympathetic'] or 0,
        's': s['sympathetic'] or 0,
        'g': s['grounding'] or 0,
    })
approach_scores['baseline'] = baseline_scores

# ---------------------------------------------------------------------------
# Approach 2: Targeted BPM re-ask (GPT-4o-mini), only for suspicious songs
# ---------------------------------------------------------------------------
print("\n--- Approach 2: TARGETED BPM RE-ASK (gpt-4o-mini) ---")
targeted_mini_results = {}
total_tokens_mini = 0

for idx, s, reason in suspicious:
    result = targeted_bpm_reask(s, model="gpt-4o-mini")
    targeted_mini_results[idx] = result
    total_tokens_mini += result['tokens']
    old_bpm = int(s['bpm'])
    new_bpm = result['bpm']
    changed = " CHANGED" if abs(new_bpm - old_bpm) > 5 else ""
    print(f"  {s['name'][:35]:<35} {old_bpm:>3} -> {new_bpm:>3} ({result['confidence']}) {result['reasoning'][:60]}{changed}")
    time.sleep(0.3)  # rate limit politeness

print(f"  Total tokens: {total_tokens_mini}")

# Compute scores with corrected BPM
approach2_scores = []
for i, s in enumerate(songs_data):
    if i in targeted_mini_results:
        new_bpm = targeted_mini_results[i]['bpm']
    else:
        new_bpm = s['bpm']

    neuro = compute_neurological_profile(
        bpm=new_bpm, energy=s['energy'], acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approach2_scores.append(neuro)
approach_scores['targeted_mini'] = approach2_scores

# ---------------------------------------------------------------------------
# Approach 3: Targeted BPM re-ask (GPT-4o — more capable model)
# ---------------------------------------------------------------------------
print("\n--- Approach 3: TARGETED BPM RE-ASK (gpt-4o) ---")
targeted_4o_results = {}
total_tokens_4o = 0

for idx, s, reason in suspicious:
    result = targeted_bpm_reask(s, model="gpt-4o")
    targeted_4o_results[idx] = result
    total_tokens_4o += result['tokens']
    old_bpm = int(s['bpm'])
    new_bpm = result['bpm']
    changed = " CHANGED" if abs(new_bpm - old_bpm) > 5 else ""
    print(f"  {s['name'][:35]:<35} {old_bpm:>3} -> {new_bpm:>3} ({result['confidence']}) {result['reasoning'][:60]}{changed}")
    time.sleep(0.3)

print(f"  Total tokens: {total_tokens_4o}")

# Compute scores with corrected BPM
approach3_scores = []
for i, s in enumerate(songs_data):
    if i in targeted_4o_results:
        new_bpm = targeted_4o_results[i]['bpm']
    else:
        new_bpm = s['bpm']

    neuro = compute_neurological_profile(
        bpm=new_bpm, energy=s['energy'], acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approach3_scores.append(neuro)
approach_scores['targeted_4o'] = approach3_scores

# ---------------------------------------------------------------------------
# Approach 4: Comprehensive re-ask (BPM + perceived energy + valence)
# Only for suspicious songs, using GPT-4o for best quality
# ---------------------------------------------------------------------------
print("\n--- Approach 4: COMPREHENSIVE RE-ASK (gpt-4o, BPM+energy+valence) ---")
comprehensive_results = {}
total_tokens_comp = 0

for idx, s, reason in suspicious:
    result = comprehensive_reask(s, model="gpt-4o")
    comprehensive_results[idx] = result
    total_tokens_comp += result['tokens']
    old_bpm = int(s['bpm'])
    new_bpm = result['bpm']
    pe = result.get('perceived_energy')
    pe_str = f"PE={pe:.2f}" if pe is not None else "PE=None"
    print(f"  {s['name'][:35]:<35} BPM {old_bpm:>3}->{new_bpm:>3}  {pe_str}  {result['reasoning'][:50]}")
    time.sleep(0.3)

print(f"  Total tokens: {total_tokens_comp}")

# Compute scores using corrected BPM and BLENDED energy
# Use perceived_energy as a corrective signal: average with Essentia energy
approach4_scores = []
for i, s in enumerate(songs_data):
    bpm = s['bpm']
    energy = s['energy']
    valence = s['valence']
    danceability = s['danceability']

    if i in comprehensive_results:
        r = comprehensive_results[i]
        bpm = r['bpm']
        # Blend perceived energy with Essentia energy (Essentia measures loudness,
        # perceived energy captures musical intensity — average is better than either alone)
        if r.get('perceived_energy') is not None and energy is not None:
            energy = (energy + r['perceived_energy']) / 2
        elif r.get('perceived_energy') is not None:
            energy = r['perceived_energy']
        # Use LLM valence if provided (but don't override — average with existing)
        if r.get('valence') is not None and valence is not None:
            valence = (valence + r['valence']) / 2
        elif r.get('valence') is not None:
            valence = r['valence']
        # Danceability
        if r.get('danceability') is not None and danceability is not None:
            danceability = (danceability + r['danceability']) / 2
        elif r.get('danceability') is not None:
            danceability = r['danceability']

    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=valence,
        mode=s['mode'], danceability=danceability,
    )
    approach4_scores.append(neuro)
approach_scores['comprehensive_4o'] = approach4_scores

# ---------------------------------------------------------------------------
# Approach 5: Comprehensive re-ask for ALL 25 songs (not just suspicious)
# Some English songs also have wrong BPMs / properties
# ---------------------------------------------------------------------------
print("\n--- Approach 5: COMPREHENSIVE RE-ASK ALL 25 SONGS (gpt-4o) ---")
all_comprehensive_results = {}
total_tokens_all = 0

for i, s in enumerate(songs_data):
    # For suspicious songs, reuse results from approach 4
    if i in comprehensive_results:
        all_comprehensive_results[i] = comprehensive_results[i]
        continue

    result = comprehensive_reask(s, model="gpt-4o")
    all_comprehensive_results[i] = result
    total_tokens_all += result['tokens']
    old_bpm = int(s['bpm'])
    new_bpm = result['bpm']
    pe = result.get('perceived_energy')
    pe_str = f"PE={pe:.2f}" if pe is not None else "PE=None"
    print(f"  {s['name'][:35]:<35} BPM {old_bpm:>3}->{new_bpm:>3}  {pe_str}  {result['reasoning'][:50]}")
    time.sleep(0.3)

print(f"  Total additional tokens: {total_tokens_all}")

# Compute scores for all songs with comprehensive corrections
approach5_scores = []
for i, s in enumerate(songs_data):
    bpm = s['bpm']
    energy = s['energy']
    valence = s['valence']
    danceability = s['danceability']

    if i in all_comprehensive_results:
        r = all_comprehensive_results[i]
        bpm = r['bpm']
        if r.get('perceived_energy') is not None and energy is not None:
            energy = (energy + r['perceived_energy']) / 2
        elif r.get('perceived_energy') is not None:
            energy = r['perceived_energy']
        if r.get('valence') is not None and valence is not None:
            valence = (valence + r['valence']) / 2
        elif r.get('valence') is not None:
            valence = r['valence']
        if r.get('danceability') is not None and danceability is not None:
            danceability = (danceability + r['danceability']) / 2
        elif r.get('danceability') is not None:
            danceability = r['danceability']

    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=valence,
        mode=s['mode'], danceability=danceability,
    )
    approach5_scores.append(neuro)
approach_scores['comprehensive_all'] = approach5_scores

# ---------------------------------------------------------------------------
# Approach 6: BPM agreement (best of approaches 2+3, trust when they agree)
# ---------------------------------------------------------------------------
print("\n--- Approach 6: BPM AGREEMENT (mini + 4o agree → use it, else keep original) ---")
agreement_bpms = {}
for idx, s, reason in suspicious:
    mini_bpm = targeted_mini_results[idx]['bpm']
    four_o_bpm = targeted_4o_results[idx]['bpm']
    orig_bpm = int(s['bpm'])

    # If both models agree within 10 BPM, use their average
    if abs(mini_bpm - four_o_bpm) <= 10:
        agreed_bpm = int(round((mini_bpm + four_o_bpm) / 2))
        agreement_bpms[idx] = agreed_bpm
        status = "AGREE"
    else:
        # Disagree — keep original (too uncertain to change)
        agreement_bpms[idx] = orig_bpm
        status = "DISAGREE (keep original)"

    print(f"  {s['name'][:35]:<35} mini={mini_bpm:>3} 4o={four_o_bpm:>3} -> {agreement_bpms[idx]:>3} [{status}]")

approach6_scores = []
for i, s in enumerate(songs_data):
    bpm = agreement_bpms.get(i, s['bpm'])
    neuro = compute_neurological_profile(
        bpm=bpm, energy=s['energy'], acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approach6_scores.append(neuro)
approach_scores['bpm_agreement'] = approach6_scores


# ---------------------------------------------------------------------------
# Results comparison
# ---------------------------------------------------------------------------
print("\n")
print("=" * 120)
print("DETAILED RESULTS")
print("=" * 120)

header = f"{'#':>2} {'Song':<32} {'GT':>4} {'Exp':>4}"
for name in ['baseline', 'targeted_mini', 'targeted_4o', 'comprehensive_4o', 'comprehensive_all', 'bpm_agreement']:
    short = name[:8]
    header += f" | {short:>8}"
print(header)
print("-" * 120)

approach_correct = {name: [] for name in approach_scores}
approach_by_cat = {name: {} for name in approach_scores}

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]

    line = f"{i+1:>2} {s['name'][:32]:<32} {s['gt_e']:>4} {expected:>4}"

    for name, scores in approach_scores.items():
        sc = scores[i]
        if 'parasympathetic' in sc:
            p, sy, g = sc['parasympathetic'], sc['sympathetic'], sc['grounding']
        else:
            p, sy, g = sc['p'], sc['s'], sc['g']

        dom = dominant(p, sy, g)
        ok = dom == expected
        approach_correct[name].append(ok)

        cat = s['cat']
        if cat not in approach_by_cat[name]:
            approach_by_cat[name][cat] = {'correct': 0, 'total': 0}
        approach_by_cat[name][cat]['total'] += 1
        if ok:
            approach_by_cat[name][cat]['correct'] += 1

        mark = "Y" if ok else " "
        line += f" | {dom:>6} {mark}"

    print(line)

print("\n")
print("=" * 120)
print("ACCURACY SUMMARY")
print("=" * 120)

print(f"\n{'Approach':<25} {'Overall':>8} {'English':>10} {'Pop Indian':>12} {'Obscure Indian':>15}")
print("-" * 75)

for name in approach_scores:
    total = len(approach_correct[name])
    correct = sum(approach_correct[name])
    overall = f"{correct}/{total} ({correct/total*100:.0f}%)"

    parts = []
    for cat in ['english', 'popular_indian', 'obscure_indian']:
        if cat in approach_by_cat[name]:
            c = approach_by_cat[name][cat]['correct']
            t = approach_by_cat[name][cat]['total']
            parts.append(f"{c}/{t} ({c/t*100:.0f}%)")
        else:
            parts.append("N/A")

    print(f"  {name:<23} {overall:>8}  {parts[0]:>10} {parts[1]:>12} {parts[2]:>15}")

# ---------------------------------------------------------------------------
# BPM changes detail
# ---------------------------------------------------------------------------
print("\n")
print("=" * 120)
print("BPM CHANGES DETAIL (suspicious songs only)")
print("=" * 120)

print(f"\n{'Song':<35} {'Orig':>4} {'Mini':>5} {'4o':>4} {'Comp':>5} {'Agree':>5} {'GT energy':>10}")
print("-" * 80)
for idx, s, reason in suspicious:
    orig = int(s['bpm'])
    mini = targeted_mini_results[idx]['bpm']
    four_o = targeted_4o_results[idx]['bpm']
    comp = comprehensive_results[idx]['bpm']
    agree = agreement_bpms[idx]

    print(f"  {s['name'][:33]:<33} {orig:>4} {mini:>5} {four_o:>4} {comp:>5} {agree:>5}   {s['gt_e']:>10}")

# ---------------------------------------------------------------------------
# Token cost summary
# ---------------------------------------------------------------------------
print("\n")
print("=" * 60)
print("COST SUMMARY")
print("=" * 60)
# GPT-4o-mini: ~$0.15 per 1M input, ~$0.60 per 1M output
# GPT-4o: ~$2.50 per 1M input, ~$10.00 per 1M output
print(f"  Approach 2 (targeted mini): {total_tokens_mini:>6} tokens")
print(f"  Approach 3 (targeted 4o):   {total_tokens_4o:>6} tokens")
print(f"  Approach 4 (comp 4o susp):  {total_tokens_comp:>6} tokens")
print(f"  Approach 5 (comp 4o all):   {total_tokens_all:>6} tokens (additional)")
print(f"  Total:                      {total_tokens_mini + total_tokens_4o + total_tokens_comp + total_tokens_all:>6} tokens")

# ---------------------------------------------------------------------------
# Save full results to JSON
# ---------------------------------------------------------------------------
results_data = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "suspicious_songs": [
        {"index": idx, "name": s['name'], "artist": s['artist'], "reason": reason,
         "original_bpm": int(s['bpm'])}
        for idx, s, reason in suspicious
    ],
    "targeted_mini_results": {str(k): v for k, v in targeted_mini_results.items()},
    "targeted_4o_results": {str(k): v for k, v in targeted_4o_results.items()},
    "comprehensive_results": {str(k): v for k, v in comprehensive_results.items()},
    "all_comprehensive_results": {str(k): v for k, v in all_comprehensive_results.items()},
    "accuracy": {
        name: {
            "overall": sum(approach_correct[name]) / len(approach_correct[name]),
            "correct": sum(approach_correct[name]),
            "total": len(approach_correct[name]),
            "by_category": {
                cat: {"correct": v["correct"], "total": v["total"]}
                for cat, v in approach_by_cat[name].items()
            }
        }
        for name in approach_scores
    },
}

results_path = Path(__file__).parent / "bpm_correction_results.json"
with open(results_path, 'w') as f:
    json.dump(results_data, f, indent=2)
print(f"\nFull results saved to {results_path}")

conn.close()
