"""BPM Correction Experiment v2: Deeper analysis of what went wrong.

Builds on v1 findings:
- Targeted BPM re-ask: 52% (from 48%)
- Comprehensive re-ask all songs: 56% (best so far)
- The problem isn't JUST BPM — it's a combination of BPM, energy, and
  the formula weights being misaligned for certain song types.

This script:
1. Analyzes WHY each wrong song is wrong (which input is most off?)
2. Tests a "best corrected inputs" approach where we combine the best
   BPM from LLM re-ask + Essentia energy (weighted differently)
3. Tests using perceived_energy INSTEAD of (not blended with) Essentia energy
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from classification.profiler import (
    compute_neurological_profile,
    compute_parasympathetic,
    compute_sympathetic,
    compute_grounding,
    sigmoid_decay,
    sigmoid_rise,
    gaussian,
    NEUTRAL_BPM,
    NEUTRAL_FLOAT,
)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

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


def dominant(p: float, s: float, g: float) -> str:
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


# Load song data
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

# Load v1 results
v1_results_path = Path(__file__).parent / "bpm_correction_results.json"
with open(v1_results_path) as f:
    v1_results = json.load(f)

print("=" * 100)
print("DEEP ANALYSIS: WHY EACH WRONG SONG IS WRONG")
print("=" * 100)

print(f"\n{'#':>2} {'Song':<32} {'GT':>5} {'Exp':>4} {'Got':>4} | {'BPM':>3} {'E':>4} {'A':>4} {'V':>4} {'D':>4} {'I':>4} | Root cause")
print("-" * 100)

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]
    p = s['parasympathetic'] or 0
    sy = s['sympathetic'] or 0
    g = s['grounding'] or 0
    dom = dominant(p, sy, g)

    if dom == expected:
        continue  # only analyze wrong ones

    bpm = int(s['bpm'] or 100)
    energy = s['energy'] or 0.5
    ac = s['acousticness'] or 0.5
    val = s['valence'] or 0.5
    dance = s['danceability'] or 0.5
    inst = s['instrumentalness'] or 0.5

    # Decompose: what component scores are causing the wrong classification?
    # Tempo contribution to each dimension
    para_tempo = sigmoid_decay(bpm, 60, 90) * 0.35
    symp_tempo = sigmoid_rise(bpm, 100, 130) * 0.35
    grnd_tempo = gaussian(bpm, 75, 15) * 0.30

    # Energy contribution
    para_energy = (1.0 - energy) * 0.25
    symp_energy = energy * 0.25
    grnd_energy = gaussian(energy, 0.35, 0.15) * 0.20

    causes = []
    if expected == 'PARA':
        if symp_tempo > 0.10:
            causes.append(f"BPM={bpm} too high for PARA (symp_tempo={symp_tempo:.2f})")
        if para_energy < 0.10:
            causes.append(f"energy={energy:.2f} too high for PARA")
        if val > 0.6:
            causes.append(f"valence={val:.2f} too positive for PARA")
    elif expected == 'SYMP':
        if symp_tempo < 0.15:
            causes.append(f"BPM={bpm} too low for SYMP (symp_tempo={symp_tempo:.2f})")
        if symp_energy < 0.15:
            causes.append(f"energy={energy:.2f} too low for SYMP")
    elif expected == 'GRND':
        if grnd_tempo < 0.05:
            causes.append(f"BPM={bpm} far from 75 for GRND (grnd_tempo={grnd_tempo:.2f})")
        if symp_tempo > 0.20:
            causes.append(f"BPM={bpm} pushes symp too high")
        if energy > 0.7:
            causes.append(f"energy={energy:.2f} too high for GRND")

    print(f"{i+1:>2} {s['name'][:32]:<32} {s['gt_e']:>5} {expected:>4} {dom:>4} | {bpm:>3} {energy:>4.2f} {ac:>4.2f} {val:>4.2f} {dance:>4.2f} {inst:>4.2f} | {'; '.join(causes)}")


# ---------------------------------------------------------------------------
# Use comprehensive re-ask data to find the best corrected inputs
# ---------------------------------------------------------------------------
print("\n\n" + "=" * 100)
print("EXPERIMENT: BEST CORRECTED INPUTS FROM V1 DATA")
print("=" * 100)

# Build corrected input sets from v1 data
# Key insight from v1: comprehensive_all (approach 5) was best at 56%
# It used: GPT-4o BPM + blended energy + blended valence

# Let's try multiple blending strategies for the comprehensive data

all_comp = v1_results.get("all_comprehensive_results", {})

approaches = {}

# Strategy A: Use GPT-4o BPM only (no energy/valence changes)
approaches["A: 4o BPM only"] = []
for i, s in enumerate(songs_data):
    r = all_comp.get(str(i), {})
    bpm = r.get("bpm", s['bpm'])
    neuro = compute_neurological_profile(
        bpm=bpm, energy=s['energy'], acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["A: 4o BPM only"].append(neuro)

# Strategy B: Use GPT-4o perceived_energy INSTEAD of Essentia (not blended)
approaches["B: 4o BPM + PE replace"] = []
for i, s in enumerate(songs_data):
    r = all_comp.get(str(i), {})
    bpm = r.get("bpm", s['bpm'])
    energy = r.get("perceived_energy", s['energy'])  # replace, not blend
    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["B: 4o BPM + PE replace"].append(neuro)

# Strategy C: 4o BPM + PE blend 50/50 (this is what comprehensive_all did)
approaches["C: 4o BPM + PE blend"] = []
for i, s in enumerate(songs_data):
    r = all_comp.get(str(i), {})
    bpm = r.get("bpm", s['bpm'])
    pe = r.get("perceived_energy")
    energy = (s['energy'] + pe) / 2 if pe is not None and s['energy'] is not None else s['energy']
    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["C: 4o BPM + PE blend"].append(neuro)

# Strategy D: 4o BPM + PE blend + 4o valence blend
approaches["D: BPM + PE + val blend"] = []
for i, s in enumerate(songs_data):
    r = all_comp.get(str(i), {})
    bpm = r.get("bpm", s['bpm'])
    pe = r.get("perceived_energy")
    energy = (s['energy'] + pe) / 2 if pe is not None and s['energy'] is not None else s['energy']
    llm_val = r.get("valence")
    valence = (s['valence'] + llm_val) / 2 if llm_val is not None and s['valence'] is not None else s['valence']
    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=valence,
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["D: BPM + PE + val blend"].append(neuro)

# Strategy E: 4o BPM + PE replace + 4o valence replace + 4o danceability replace
approaches["E: all 4o replace"] = []
for i, s in enumerate(songs_data):
    r = all_comp.get(str(i), {})
    bpm = r.get("bpm", s['bpm'])
    energy = r.get("perceived_energy") or s['energy']
    valence = r.get("valence") or s['valence']
    danceability = r.get("danceability") or s['danceability']
    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=valence,
        mode=s['mode'], danceability=danceability,
    )
    approaches["E: all 4o replace"].append(neuro)

# Strategy F: mini BPM only (from v1 targeted_mini — only suspicious songs)
targeted_mini = v1_results.get("targeted_mini_results", {})
approaches["F: mini BPM only"] = []
for i, s in enumerate(songs_data):
    r = targeted_mini.get(str(i), {})
    bpm = r.get("bpm", s['bpm'])
    neuro = compute_neurological_profile(
        bpm=bpm, energy=s['energy'], acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["F: mini BPM only"].append(neuro)

# Strategy G: Essentia energy scaled — many songs have Essentia energy that
# measures loudness/mastering, not perceived energy. Scale it:
# if BPM < 85 and E_essentia > 0.5, cap at 0.4 (slow songs shouldn't be "high energy")
# if BPM > 130 and E_essentia < 0.5, floor at 0.6 (fast dance songs need energy)
approaches["G: scaled energy"] = []
for i, s in enumerate(songs_data):
    bpm = s['bpm'] or 100
    energy = s['energy'] or 0.5
    # Scale energy based on tempo + acousticness signals
    if bpm < 85 and energy > 0.5 and (s['acousticness'] or 0) > 0.7:
        energy = 0.35
    elif bpm > 130 and energy < 0.5:
        energy = max(energy, 0.6)
    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["G: scaled energy"].append(neuro)

# Strategy H: Combine mini BPM + scaled energy (heuristic corrections only, no extra API calls)
approaches["H: mini BPM + scaled E"] = []
for i, s in enumerate(songs_data):
    r = targeted_mini.get(str(i), {})
    bpm = r.get("bpm", s['bpm']) or 100
    energy = s['energy'] or 0.5
    if bpm < 85 and energy > 0.5 and (s['acousticness'] or 0) > 0.7:
        energy = 0.35
    elif bpm > 130 and energy < 0.5:
        energy = max(energy, 0.6)
    neuro = compute_neurological_profile(
        bpm=bpm, energy=energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    approaches["H: mini BPM + scaled E"].append(neuro)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
print(f"\n{'#':>2} {'Song':<32} {'Exp':>4}", end="")
for name in approaches:
    print(f" | {name[:8]:>8}", end="")
print()
print("-" * (45 + 11 * len(approaches)))

approach_correct = {name: [] for name in approaches}
approach_by_cat = {name: {} for name in approaches}

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]
    line = f"{i+1:>2} {s['name'][:32]:<32} {expected:>4}"

    for name, scores in approaches.items():
        sc = scores[i]
        dom = dominant(sc['parasympathetic'], sc['sympathetic'], sc['grounding'])
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

print(f"\n\n{'Approach':<28} {'Overall':>10} {'English':>12} {'Pop Indian':>12} {'Obscure Indian':>15}")
print("-" * 80)

# Include baseline for reference
baseline_correct = []
for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]
    dom = dominant(s['parasympathetic'] or 0, s['sympathetic'] or 0, s['grounding'] or 0)
    baseline_correct.append(dom == expected)

bc = sum(baseline_correct)
print(f"  {'BASELINE':<26} {bc}/{25} ({bc/25*100:.0f}%)")

for name in approaches:
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

    print(f"  {name:<26} {overall:>10}  {parts[0]:>12} {parts[1]:>12} {parts[2]:>15}")

# ---------------------------------------------------------------------------
# Detailed view of what comprehensive_all (best from v1) vs BPM-only changes
# ---------------------------------------------------------------------------
print("\n\n" + "=" * 100)
print("DETAILED: WHAT CHANGED IN THE BEST APPROACH vs BASELINE")
print("=" * 100)

# Find the best approach
best_name = max(approaches, key=lambda n: sum(approach_correct[n]))
best_correct = sum(approach_correct[best_name])
print(f"\nBest approach: {best_name} ({best_correct}/{len(songs_data)} = {best_correct/len(songs_data)*100:.0f}%)")

print(f"\n{'#':>2} {'Song':<32} {'Base':>4} {'Best':>4} {'Exp':>4} | Changes")
print("-" * 90)

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]
    base_dom = dominant(s['parasympathetic'] or 0, s['sympathetic'] or 0, s['grounding'] or 0)
    best_sc = approaches[best_name][i]
    best_dom = dominant(best_sc['parasympathetic'], best_sc['sympathetic'], best_sc['grounding'])

    if base_dom != best_dom:
        r = all_comp.get(str(i), {})
        changes = []
        if r.get("bpm") and r["bpm"] != int(s['bpm'] or 0):
            changes.append(f"BPM {int(s['bpm'])}→{r['bpm']}")
        if r.get("perceived_energy") is not None:
            orig_e = s['energy'] or 0.5
            new_e = r['perceived_energy']
            if abs(orig_e - new_e) > 0.05:
                changes.append(f"E {orig_e:.2f}→{new_e:.2f}")
        if r.get("valence") is not None:
            orig_v = s['valence'] or 0.5
            new_v = r['valence']
            if abs(orig_v - new_v) > 0.05:
                changes.append(f"V {orig_v:.2f}→{new_v:.2f}")

        b_ok = "Y" if base_dom == expected else " "
        n_ok = "Y" if best_dom == expected else " "
        status = "FIXED" if best_dom == expected and base_dom != expected else "BROKE" if base_dom == expected and best_dom != expected else "CHANGED"
        print(f"{i+1:>2} {s['name'][:32]:<32} {base_dom:>3}{b_ok} {best_dom:>3}{n_ok} {expected:>4} | {status}: {', '.join(changes)}")

# ---------------------------------------------------------------------------
# Summary of songs that no approach gets right
# ---------------------------------------------------------------------------
print("\n\n" + "=" * 100)
print("SONGS THAT NO APPROACH GETS RIGHT")
print("=" * 100)

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]
    any_correct = baseline_correct[i]
    for name in approaches:
        sc = approaches[name][i]
        dom = dominant(sc['parasympathetic'], sc['sympathetic'], sc['grounding'])
        if dom == expected:
            any_correct = True
            break

    if not any_correct:
        bpm = int(s['bpm'] or 100)
        energy = s['energy'] or 0.5
        print(f"  {i+1:>2}. {s['name'][:35]:<35} Exp={expected} BPM={bpm} E={energy:.2f} A={s['acousticness']:.2f} V={s['valence']:.2f}")
        # What would need to change?
        if expected == 'PARA':
            print(f"       -> For PARA: need BPM<75, low energy, high acousticness")
            # Compute what BPM would make it PARA at current energy
            for test_bpm in [50, 55, 60, 65, 70, 75, 80]:
                neuro = compute_neurological_profile(
                    bpm=test_bpm, energy=energy, acousticness=s['acousticness'],
                    instrumentalness=s['instrumentalness'], valence=s['valence'],
                    mode=s['mode'], danceability=s['danceability'],
                )
                dom = dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding'])
                if dom == 'PARA':
                    print(f"       -> Would be PARA at BPM={test_bpm}: P={neuro['parasympathetic']:.4f} S={neuro['sympathetic']:.4f} G={neuro['grounding']:.4f}")
                    break
            else:
                # Even at BPM=50 it's not PARA — energy/valence too high
                for test_e in [0.1, 0.2, 0.3, 0.4]:
                    neuro = compute_neurological_profile(
                        bpm=70, energy=test_e, acousticness=s['acousticness'],
                        instrumentalness=s['instrumentalness'], valence=s['valence'],
                        mode=s['mode'], danceability=s['danceability'],
                    )
                    dom = dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding'])
                    if dom == 'PARA':
                        print(f"       -> Would be PARA at BPM=70 + E={test_e}: P={neuro['parasympathetic']:.4f} S={neuro['sympathetic']:.4f} G={neuro['grounding']:.4f}")
                        break
        elif expected == 'GRND':
            print(f"       -> For GRND: need BPM~75, E~0.35, moderate A/V")
        elif expected == 'SYMP':
            print(f"       -> For SYMP: need BPM>120, E>0.6")

conn.close()
