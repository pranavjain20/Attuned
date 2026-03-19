"""BPM Correction v3: Refined best-of approach.

Builds on findings:
- Mini BPM re-ask is best for Indian songs (cheap, focused)
- 4o comprehensive (BPM + PE) is best for English songs
- Devotional songs with BPM < 85 and high acousticness may need energy scaling
  even after BPM correction

Tests refined strategy:
- Indian non-devotional: mini BPM only
- Indian devotional: mini BPM + energy scale-down when slow/acoustic
- English: 4o comprehensive (BPM + PE replace)
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from classification.profiler import compute_neurological_profile

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

v1_path = Path(__file__).parent / "bpm_correction_results.json"
with open(v1_path) as f:
    v1 = json.load(f)

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

DEVOTIONAL_GENRES = {"devotional", "kirtan", "sufi", "bhajan", "spiritual", "chant", "mantra", "prayer"}


def dominant(p, s, g):
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


def parse_genre_tags(raw):
    if not raw:
        return []
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (json.JSONDecodeError, TypeError):
        return []


# Load songs
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

all_comp = v1.get("all_comprehensive_results", {})
targeted_mini = v1.get("targeted_mini_results", {})

approaches = {}

# ---------------------------------------------------------------------------
# 1. Baseline
# ---------------------------------------------------------------------------
approaches['Baseline'] = []
for s in songs_data:
    approaches['Baseline'].append(dominant(s['parasympathetic'] or 0, s['sympathetic'] or 0, s['grounding'] or 0))

# ---------------------------------------------------------------------------
# 2. Best-of hybrid v1 (from summary script)
# ---------------------------------------------------------------------------
approaches['Hybrid v1'] = []
for i, s in enumerate(songs_data):
    if s['cat'] in ('popular_indian', 'obscure_indian'):
        r = targeted_mini.get(str(i), {})
        bpm = r.get("bpm", s['bpm'])
        neuro = compute_neurological_profile(
            bpm=bpm, energy=s['energy'], acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
    else:
        r = all_comp.get(str(i), {})
        bpm = r.get("bpm", s['bpm'])
        energy = r.get("perceived_energy") or s['energy']
        neuro = compute_neurological_profile(
            bpm=bpm, energy=energy, acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
    approaches['Hybrid v1'].append(dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding']))

# ---------------------------------------------------------------------------
# 3. Hybrid v2: Indian devotional gets energy scaling too
# ---------------------------------------------------------------------------
approaches['Hybrid v2'] = []
for i, s in enumerate(songs_data):
    genre_tags = parse_genre_tags(s.get('genre_tags'))
    is_devotional = any(g in DEVOTIONAL_GENRES for g in genre_tags)

    if s['cat'] in ('popular_indian', 'obscure_indian'):
        r = targeted_mini.get(str(i), {})
        bpm = r.get("bpm", s['bpm']) or 100
        energy = s['energy'] or 0.5

        # For devotional songs with corrected-low BPM: also scale energy down
        if is_devotional and bpm < 85 and (s['acousticness'] or 0) > 0.7:
            # PE from comprehensive if available, otherwise heuristic
            comp_r = v1.get("comprehensive_results", {}).get(str(i), {})
            pe = comp_r.get("perceived_energy")
            if pe is not None:
                energy = pe  # Use perceived energy for devotional songs
            elif energy > 0.3:
                energy = 0.25  # Heuristic: devotional + slow + acoustic = very low energy

        neuro = compute_neurological_profile(
            bpm=bpm, energy=energy, acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
    else:
        r = all_comp.get(str(i), {})
        bpm = r.get("bpm", s['bpm'])
        energy = r.get("perceived_energy") or s['energy']
        neuro = compute_neurological_profile(
            bpm=bpm, energy=energy, acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
    approaches['Hybrid v2'].append(dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding']))

# ---------------------------------------------------------------------------
# 4. Hybrid v3: Everything from v2 + also scale Namo Namo (not tagged devotional
#    but is spiritual/mantra-like)
# Let's be more aggressive: scale energy for ANY Indian song where BPM < 85 and A > 0.7
# ---------------------------------------------------------------------------
approaches['Hybrid v3'] = []
for i, s in enumerate(songs_data):
    if s['cat'] in ('popular_indian', 'obscure_indian'):
        r = targeted_mini.get(str(i), {})
        bpm = r.get("bpm", s['bpm']) or 100
        energy = s['energy'] or 0.5

        # For any Indian song that's slow + acoustic: use PE or scale energy
        if bpm < 85 and (s['acousticness'] or 0) > 0.7:
            comp_r = v1.get("comprehensive_results", {}).get(str(i), {})
            pe = comp_r.get("perceived_energy")
            if pe is not None:
                energy = pe
            elif energy > 0.3:
                energy = 0.25

        neuro = compute_neurological_profile(
            bpm=bpm, energy=energy, acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
    else:
        r = all_comp.get(str(i), {})
        bpm = r.get("bpm", s['bpm'])
        energy = r.get("perceived_energy") or s['energy']
        neuro = compute_neurological_profile(
            bpm=bpm, energy=energy, acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
    approaches['Hybrid v3'].append(dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding']))

# ---------------------------------------------------------------------------
# 5. Hybrid v4: Use 4o comprehensive PE for ALL songs (not just English)
#    For Indian songs: use mini BPM + 4o PE
# ---------------------------------------------------------------------------
approaches['Hybrid v4 (all PE)'] = []
for i, s in enumerate(songs_data):
    r_comp = all_comp.get(str(i), {})
    energy = r_comp.get("perceived_energy") or s['energy']

    if s['cat'] in ('popular_indian', 'obscure_indian'):
        r_mini = targeted_mini.get(str(i), {})
        bpm = r_mini.get("bpm", s['bpm'])
    else:
        bpm = r_comp.get("bpm", s['bpm'])

    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches['Hybrid v4 (all PE)'].append(dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding']))

# ---------------------------------------------------------------------------
# Print results
# ---------------------------------------------------------------------------
print("=" * 100)
print("REFINED APPROACHES COMPARISON")
print("=" * 100)

print(f"\n{'#':>2} {'Song':<35} {'GT':>5} {'Exp':>4}", end="")
for name in approaches:
    print(f" | {name[:10]:>10}", end="")
print()
print("-" * (50 + 13 * len(approaches)))

cat_stats = {name: {} for name in approaches}

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]
    line = f"{i+1:>2} {s['name'][:35]:<35} {s['gt_e']:>5} {expected:>4}"

    for name, doms in approaches.items():
        dom = doms[i]
        ok = dom == expected
        cat = s['cat']
        if cat not in cat_stats[name]:
            cat_stats[name][cat] = {'c': 0, 't': 0}
        cat_stats[name][cat]['t'] += 1
        if ok:
            cat_stats[name][cat]['c'] += 1
        mark = "Y" if ok else " "
        line += f" |   {dom:>4} {mark}  "

    print(line)

print(f"\n\n{'Approach':<22} {'Overall':>10} {'English':>12} {'Pop Indian':>12} {'Obscure':>12}")
print("-" * 72)

for name, doms in approaches.items():
    total = len(doms)
    correct = sum(1 for i, d in enumerate(doms) if d == energy_to_expected[songs_data[i]['gt_e']])
    overall = f"{correct}/{total} ({correct/total*100:.0f}%)"

    parts = []
    for cat in ['english', 'popular_indian', 'obscure_indian']:
        if cat in cat_stats[name]:
            c = cat_stats[name][cat]['c']
            t = cat_stats[name][cat]['t']
            parts.append(f"{c}/{t} ({c/t*100:.0f}%)")
        else:
            parts.append("N/A")

    print(f"  {name:<20} {overall:>10}  {parts[0]:>12} {parts[1]:>12} {parts[2]:>12}")

# What changed between v1 and v2?
print("\n\nChanges from Hybrid v1 -> v2:")
for i, s in enumerate(songs_data):
    if approaches['Hybrid v1'][i] != approaches['Hybrid v2'][i]:
        expected = energy_to_expected[s['gt_e']]
        v1_ok = "Y" if approaches['Hybrid v1'][i] == expected else " "
        v2_ok = "Y" if approaches['Hybrid v2'][i] == expected else " "
        print(f"  {s['name'][:35]:<35} v1={approaches['Hybrid v1'][i]}{v1_ok} -> v2={approaches['Hybrid v2'][i]}{v2_ok} (exp={expected})")

print("\nChanges from Hybrid v1 -> v3:")
for i, s in enumerate(songs_data):
    if approaches['Hybrid v1'][i] != approaches['Hybrid v3'][i]:
        expected = energy_to_expected[s['gt_e']]
        v1_ok = "Y" if approaches['Hybrid v1'][i] == expected else " "
        v3_ok = "Y" if approaches['Hybrid v3'][i] == expected else " "
        print(f"  {s['name'][:35]:<35} v1={approaches['Hybrid v1'][i]}{v1_ok} -> v3={approaches['Hybrid v3'][i]}{v3_ok} (exp={expected})")

print("\nChanges from Hybrid v1 -> v4:")
for i, s in enumerate(songs_data):
    if approaches['Hybrid v1'][i] != approaches['Hybrid v4 (all PE)'][i]:
        expected = energy_to_expected[s['gt_e']]
        v1_ok = "Y" if approaches['Hybrid v1'][i] == expected else " "
        v4_ok = "Y" if approaches['Hybrid v4 (all PE)'][i] == expected else " "
        print(f"  {s['name'][:35]:<35} v1={approaches['Hybrid v1'][i]}{v1_ok} -> v4={approaches['Hybrid v4 (all PE)'][i]}{v4_ok} (exp={expected})")

conn.close()
