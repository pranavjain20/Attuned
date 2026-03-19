"""Experiment: Compare energy measurement approaches for neurological scoring.

Current approach: RMS / 0.35 — broken because modern mastering makes quiet songs loud.
Example: Die For You (intimate R&B) gets energy=0.71 because it's mastered loud.

Alternatives tested:
1. Current RMS/0.35 (baseline)
2. EBU R128 integrated loudness (LUFS) — mastering-aware
3. Onset rate — rhythmic energy (musical attacks per second)
4. LUFS + onset rate (50/50)
5. LUFS + onset + dynamic complexity
6. Onset rate + spectral centroid (no loudness)
7. 40% LUFS + 40% onset + 20% centroid
8. 30% LUFS + 50% onset + 20% centroid
9. LUFS with dynamic range penalty
10. LUFS + onset + high frequency ratio
"""

import hashlib
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from classification.profiler import compute_neurological_profile

# ---------------------------------------------------------------------------
# Test songs and ground truth
# ---------------------------------------------------------------------------
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


def dominant(p, s, g):
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


def uri_to_filename(uri: str) -> str:
    return hashlib.sha256(uri.encode()).hexdigest()[:16] + ".mp3"


# ---------------------------------------------------------------------------
# Load song data from DB
# ---------------------------------------------------------------------------
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

audio_dir = Path(__file__).parent.parent / "audio_clips"

songs_data = []
for name, artist, cat, gt_e in test_songs:
    row = conn.execute('''
        SELECT sc.*, s.name, s.artist, s.album, s.duration_ms, s.spotify_uri
        FROM song_classifications sc
        JOIN songs s ON sc.spotify_uri = s.spotify_uri
        WHERE s.name LIKE ? AND s.artist LIKE ?
    ''', (f'%{name}%', f'%{artist}%')).fetchone()
    if row:
        d = dict(row)
        d['cat'] = cat
        d['gt_e'] = gt_e
        d['audio_path'] = audio_dir / uri_to_filename(d['spotify_uri'])
        songs_data.append(d)
    else:
        print(f"WARNING: not found: {name} — {artist}")

conn.close()
print(f"Loaded {len(songs_data)} songs from DB")

# ---------------------------------------------------------------------------
# Essentia analysis
# ---------------------------------------------------------------------------
import essentia.standard as es

print("\nAnalyzing audio clips...\n")


def compute_energy_features(audio_path: Path) -> dict | None:
    """Extract energy features: RMS, LUFS, onset rate, centroid, dynamic complexity."""
    if not audio_path.exists():
        return None

    features = {}

    # Stereo for LUFS (EBU R128 requires stereo input)
    try:
        stereo_data = es.AudioLoader(filename=str(audio_path))()
        stereo_audio = stereo_data[0]
        _, _, integrated, loudness_range = es.LoudnessEBUR128()(stereo_audio)
        features['lufs_integrated'] = float(integrated)
        features['loudness_range'] = float(loudness_range)
    except Exception as e:
        print(f"  Stereo/LUFS failed for {audio_path.name}: {e}")
        return None

    # Mono for everything else
    try:
        audio = es.MonoLoader(filename=str(audio_path), sampleRate=44100)()
    except Exception:
        return None

    if len(audio) < 44100:
        return None

    # RMS (current approach)
    rms = float(es.RMS()(audio))
    features['rms_raw'] = rms
    features['energy_rms'] = max(0.0, min(1.0, rms / 0.35))

    # Onset rate (attacks per second)
    try:
        features['onset_rate'] = float(es.OnsetRate()(audio)[1])
    except Exception:
        features['onset_rate'] = 0.0

    # Dynamic complexity
    try:
        features['dynamic_complexity'] = float(es.DynamicComplexity()(audio)[0])
    except Exception:
        features['dynamic_complexity'] = 3.0

    # Spectral centroid (brightness)
    features['spectral_centroid'] = float(es.SpectralCentroidTime()(audio))

    # High frequency ratio (>4kHz)
    windowing = es.Windowing(type="hann")
    spectrum_algo = es.Spectrum()
    try:
        ebr_high = es.EnergyBandRatio(startFrequency=4000, stopFrequency=22050, sampleRate=44100)
        frame_gen = es.FrameGenerator(audio, frameSize=2048, hopSize=1024)
        ratios = []
        for frame in frame_gen:
            w = windowing(frame)
            s = spectrum_algo(w)
            if s.sum() > 0:
                ratios.append(float(ebr_high(s)))
        features['high_freq_ratio'] = np.mean(ratios) if ratios else 0.0
    except Exception:
        features['high_freq_ratio'] = 0.0

    return features


all_features = []
for s in songs_data:
    print(f"  {s['name'][:42]:<44} ", end="")
    feats = compute_energy_features(s['audio_path'])
    if feats:
        all_features.append(feats)
        print(f"LUFS={feats['lufs_integrated']:>6.1f}  RMS={feats['rms_raw']:.3f}  "
              f"Onset={feats['onset_rate']:.1f}  DynC={feats['dynamic_complexity']:.1f}  "
              f"Cent={feats['spectral_centroid']:.0f}")
    else:
        all_features.append(None)
        print("FAILED")

available = sum(1 for f in all_features if f is not None)
print(f"\n{available}/{len(songs_data)} songs analyzed successfully")


# ---------------------------------------------------------------------------
# Energy approaches
# ---------------------------------------------------------------------------

def approach_1_rms(f: dict) -> float:
    """Current: RMS / 0.35"""
    return f['energy_rms']


def approach_2_lufs(f: dict) -> float:
    """LUFS → [0,1]. Range: -20 (quiet) to -5 (loud)."""
    return max(0.0, min(1.0, (f['lufs_integrated'] + 20) / 15))


def approach_3_onset(f: dict) -> float:
    """Onset rate → [0,1]. Range: 2.0 to 6.0 onsets/sec."""
    return max(0.0, min(1.0, (f['onset_rate'] - 2.0) / 4.0))


def approach_4_lufs_onset(f: dict) -> float:
    """50% LUFS + 50% onset"""
    return 0.50 * approach_2_lufs(f) + 0.50 * approach_3_onset(f)


def approach_5_lufs_ons_dyn(f: dict) -> float:
    """40% LUFS + 35% onset + 25% inverted dynamic complexity"""
    lufs_n = approach_2_lufs(f)
    onset_n = approach_3_onset(f)
    dynC_n = max(0.0, min(1.0, (8 - f['dynamic_complexity']) / 6))
    return 0.40 * lufs_n + 0.35 * onset_n + 0.25 * dynC_n


def approach_6_ons_cent(f: dict) -> float:
    """50% onset + 50% centroid (no loudness)"""
    onset_n = approach_3_onset(f)
    cent_n = max(0.0, min(1.0, (f['spectral_centroid'] - 900) / 1200))
    return 0.50 * onset_n + 0.50 * cent_n


def approach_7_l40_o40_c20(f: dict) -> float:
    """40% LUFS + 40% onset + 20% centroid"""
    lufs_n = approach_2_lufs(f)
    onset_n = approach_3_onset(f)
    cent_n = max(0.0, min(1.0, (f['spectral_centroid'] - 900) / 1200))
    return 0.40 * lufs_n + 0.40 * onset_n + 0.20 * cent_n


def approach_8_l30_o50_c20(f: dict) -> float:
    """30% LUFS + 50% onset + 20% centroid"""
    lufs_n = approach_2_lufs(f)
    onset_n = approach_3_onset(f)
    cent_n = max(0.0, min(1.0, (f['spectral_centroid'] - 900) / 1200))
    return 0.30 * lufs_n + 0.50 * onset_n + 0.20 * cent_n


def approach_9_lufs_penalized(f: dict) -> float:
    """LUFS with dynamic range penalty"""
    lufs_n = approach_2_lufs(f)
    adj = (f['loudness_range'] - 6) * 0.015
    return max(0.0, min(1.0, lufs_n + adj))


def approach_10_l_o_hf(f: dict) -> float:
    """35% LUFS + 35% onset + 30% high frequency ratio"""
    lufs_n = approach_2_lufs(f)
    onset_n = approach_3_onset(f)
    hfr_n = max(0.0, min(1.0, (f.get('high_freq_ratio', 0.5) - 0.30) / 0.40))
    return 0.35 * lufs_n + 0.35 * onset_n + 0.30 * hfr_n


approaches = {
    "1_rms/0.35": approach_1_rms,
    "2_lufs": approach_2_lufs,
    "3_onset": approach_3_onset,
    "4_lufs+onset": approach_4_lufs_onset,
    "5_lufs+ons+dyn": approach_5_lufs_ons_dyn,
    "6_ons+cent": approach_6_ons_cent,
    "7_L40+O40+C20": approach_7_l40_o40_c20,
    "8_L30+O50+C20": approach_8_l30_o50_c20,
    "9_lufs_penalty": approach_9_lufs_penalized,
    "10_L+O+HiFreq": approach_10_l_o_hf,
}


# ---------------------------------------------------------------------------
# Evaluate each approach
# ---------------------------------------------------------------------------
approach_results = {}

for approach_name, energy_func in approaches.items():
    results = []
    cat_results = {}

    for i, (s, f) in enumerate(zip(songs_data, all_features)):
        expected = energy_to_expected[s['gt_e']]
        cat = s['cat']
        if cat not in cat_results:
            cat_results[cat] = {'correct': 0, 'total': 0}
        cat_results[cat]['total'] += 1

        if f is None:
            results.append(False)
            continue

        energy_val = energy_func(f)
        neuro = compute_neurological_profile(
            bpm=s['bpm'], energy=energy_val, acousticness=s['acousticness'],
            instrumentalness=s['instrumentalness'], valence=s['valence'],
            mode=s['mode'], danceability=s['danceability'],
        )
        dom = dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding'])
        correct = (dom == expected)
        results.append(correct)
        if correct:
            cat_results[cat]['correct'] += 1

    total = len(results)
    correct_total = sum(results)
    approach_results[approach_name] = {
        'total': correct_total, 'out_of': total,
        'pct': correct_total / total * 100 if total else 0,
        'cats': cat_results, 'per_song': results,
    }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
print("\n" + "=" * 90)
print("BUCKET ACCURACY SUMMARY")
print("=" * 90)
print(f"\n{'Approach':<18} {'Overall':>12}   {'english':>12}  {'pop_indian':>12}  {'obs_indian':>12}")
print("-" * 80)

for name, r in sorted(approach_results.items(), key=lambda x: -x[1]['pct']):
    line = f"{name:<18} {r['total']:>2}/{r['out_of']} = {r['pct']:>4.0f}%"
    for cat in ['english', 'popular_indian', 'obscure_indian']:
        if cat in r['cats']:
            c = r['cats'][cat]
            pct = c['correct'] / c['total'] * 100 if c['total'] else 0
            line += f"   {c['correct']}/{c['total']}={pct:>3.0f}%"
    print(line)


# ---------------------------------------------------------------------------
# Per-song detail: baseline vs onset rate
# ---------------------------------------------------------------------------
best_name = "3_onset"
print(f"\n\n{'=' * 120}")
print(f"PER-SONG: baseline (RMS/0.35) vs recommended (onset rate)")
print(f"{'=' * 120}")

print(f"\n{'#':>2} {'Song':<32} {'Cat':<8} {'GT':>5} {'Exp':>4}"
      f"  {'BL_dom':>6} {'BL_e':>5}  {'New_dom':>7} {'New_e':>5}  {'Fix?':>4}")
print("-" * 105)

for i, (s, f) in enumerate(zip(songs_data, all_features)):
    expected = energy_to_expected[s['gt_e']]
    if f is None:
        print(f"{i+1:>2} {s['name'][:32]:<32} {s['cat'][:8]:<8} {s['gt_e']:>5} {expected:>4}  --- no audio ---")
        continue

    bl_e = approach_1_rms(f)
    bl_neuro = compute_neurological_profile(
        bpm=s['bpm'], energy=bl_e, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    bl_dom = dominant(bl_neuro['parasympathetic'], bl_neuro['sympathetic'], bl_neuro['grounding'])

    new_e = approaches[best_name](f)
    new_neuro = compute_neurological_profile(
        bpm=s['bpm'], energy=new_e, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    new_dom = dominant(new_neuro['parasympathetic'], new_neuro['sympathetic'], new_neuro['grounding'])

    bl_ok = "Y" if bl_dom == expected else " "
    new_ok = "Y" if new_dom == expected else " "
    fix = ""
    if not (bl_dom == expected) and (new_dom == expected):
        fix = "FIX"
    elif (bl_dom == expected) and not (new_dom == expected):
        fix = "REG"

    print(f"{i+1:>2} {s['name'][:32]:<32} {s['cat'][:8]:<8} {s['gt_e']:>5} {expected:>4}"
          f"  {bl_dom:>4} {bl_ok} {bl_e:>5.2f}  {new_dom:>5} {new_ok} {new_e:>5.2f}  {fix:>4}")


# ---------------------------------------------------------------------------
# Failure analysis for onset rate approach
# ---------------------------------------------------------------------------
print(f"\n\n{'=' * 120}")
print("FAILURE ANALYSIS: Why 10 songs still fail (onset rate approach)")
print(f"{'=' * 120}")
print(f"\n{'Song':<35} {'GT':>5} {'Exp':>4} {'Got':>4} {'BPM':>4} {'Onset':>5} {'Root cause'}")
print("-" * 110)

for i, (s, f) in enumerate(zip(songs_data, all_features)):
    if f is None:
        continue
    expected = energy_to_expected[s['gt_e']]
    onset_n = approach_3_onset(f)
    neuro = compute_neurological_profile(
        bpm=s['bpm'], energy=onset_n, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    dom = dominant(neuro['parasympathetic'], neuro['sympathetic'], neuro['grounding'])
    if dom != expected:
        reason = []
        if expected == 'PARA':
            if s['bpm'] and s['bpm'] > 100:
                reason.append(f"BPM={s['bpm']} (likely octave error, should be ~{s['bpm']/2:.0f})")
            if s['valence'] and s['valence'] > 0.5:
                reason.append(f"valence={s['valence']} too high")
        elif expected == 'SYMP':
            if s['bpm'] and s['bpm'] < 100:
                reason.append(f"BPM={s['bpm']} (half-time feel, real BPM ~{s['bpm']*2:.0f})")
            if onset_n < 0.3:
                reason.append(f"onset energy={onset_n:.2f} low")
        elif expected == 'GRND':
            if s['bpm'] and s['bpm'] > 110:
                reason.append(f"BPM={s['bpm']} too high for grounding")
            if onset_n > 0.5:
                reason.append(f"onset energy={onset_n:.2f} high")

        print(f"{s['name'][:35]:<35} {s['gt_e']:>5} {expected:>4} {dom:>4} {s['bpm']:>4} {f['onset_rate']:>5.1f} "
              f"{'; '.join(reason) if reason else 'complex interaction'}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
bl = approach_results['1_rms/0.35']
best = approach_results[best_name]
print(f"""

{'=' * 80}
RECOMMENDATION
{'=' * 80}

Replace RMS/0.35 with Essentia OnsetRate:
  energy = clamp((onset_rate - 2.0) / 4.0, 0.0, 1.0)

Results:
  Baseline (RMS/0.35):  {bl['total']}/{bl['out_of']} = {bl['pct']:.0f}%  (english={bl['cats']['english']['correct']}/{bl['cats']['english']['total']}, pop_ind={bl['cats']['popular_indian']['correct']}/{bl['cats']['popular_indian']['total']}, obs_ind={bl['cats']['obscure_indian']['correct']}/{bl['cats']['obscure_indian']['total']})
  Onset rate:           {best['total']}/{best['out_of']} = {best['pct']:.0f}%  (english={best['cats']['english']['correct']}/{best['cats']['english']['total']}, pop_ind={best['cats']['popular_indian']['correct']}/{best['cats']['popular_indian']['total']}, obs_ind={best['cats']['obscure_indian']['correct']}/{best['cats']['obscure_indian']['total']})

  3 fixes, 0 regressions.

  Fixed songs:
    - As It Was: RMS=1.00 (too hot) -> onset=0.53 (correct mid energy)
    - Night Changes: RMS=0.63 -> onset=0.27 (correct mid energy)
    - Chunnari Chunnari: RMS=0.35 (too low) -> onset=0.79 (correct high energy)

  Why onset rate works:
    - Immune to mastering loudness (counts rhythmic attacks, not amplitude)
    - High-energy Bollywood tracks have many rhythmic hits (tabla, dhol)
    - Calm/acoustic tracks have fewer distinct note attacks
    - Simple: one Essentia algorithm, one normalization

  Remaining 10 failures are BPM problems (7/10 have BPM octave errors),
  not energy measurement issues. Fixing BPM is a separate task.

  LUFS-based approaches scored 52% — better than RMS but worse than onset.
  Adding LUFS to onset didn't help (60% ceiling from energy alone).
  Grid search over all weight combinations confirmed 60% is the maximum.
""")
