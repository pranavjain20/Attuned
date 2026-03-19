"""Blend experiment v2: Refined strategies based on v1 findings.

Key findings from v1:
- 8 HARD songs (0-5/19 strategies correct): most are structurally impossible
  because BOTH formula and direct get them wrong
- The winner (genre+spread) at 68% works because it trusts formula for Indian
  songs (which formula handles well) and trusts direct for English songs when
  the LLM is confident (high spread)
- Normalization helps because formula scores are compressed (0.1-0.9) while
  direct scores vary widely
- 6 songs are impossible for any strategy (both sources wrong): #4, #6, #10, #16, #23, #7(almost)

This script:
1. Loads saved data from v1 (no new API call needed)
2. Tries more targeted strategies
3. Analyzes the theoretical ceiling
"""

import json
from pathlib import Path

data = json.loads((Path(__file__).parent / 'blend_experiment_results.json').read_text())
all_songs = data['songs']


def dominant(p: float, s: float, g: float) -> str:
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


def spread(p: float, s: float, g: float) -> float:
    return max(p, s, g) - min(p, s, g)


# ─────────────────────────────────────────────────────────────────────────────
# Theoretical ceiling analysis
# ─────────────────────────────────────────────────────────────────────────────
print("="*80)
print("THEORETICAL CEILING: best possible if we had a perfect oracle picking formula vs direct")
print("="*80)

oracle_correct = 0
for sg in all_songs:
    f_dom = dominant(sg['formula']['p'], sg['formula']['s'], sg['formula']['g'])
    d_dom = dominant(sg['direct']['p'], sg['direct']['s'], sg['direct']['g'])
    expected = sg['expected']

    f_ok = f_dom == expected
    d_ok = d_dom == expected
    either = f_ok or d_ok

    if either:
        oracle_correct += 1
    else:
        print(f"  IMPOSSIBLE: {sg['name'][:35]:<35} expected={expected} formula={f_dom} direct={d_dom}")

print(f"\nOracle ceiling: {oracle_correct}/25 = {oracle_correct/25*100:.0f}%")
print(f"Impossible songs: {25 - oracle_correct}")


# ─────────────────────────────────────────────────────────────────────────────
# Refined strategies
# ─────────────────────────────────────────────────────────────────────────────

def strategy_genre_spread_v2(sg: dict) -> str:
    """Refined genre+spread: different thresholds based on v1 analysis.
    For English: spread>0.4 → direct, else genre blend (formula for known-good cases)
    For Indian devotional: 85% formula
    For Indian other: 70% formula, 30% direct"""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']
    sp = spread(dp, ds, dg)

    if sg['is_indian']:
        if sg['is_devotional']:
            fw, dw = 0.85, 0.15
        else:
            fw, dw = 0.70, 0.30
    else:
        # English: use spread to decide
        if sp > 0.4:
            return dominant(dp, ds, dg)
        else:
            fw, dw = 0.4, 0.6  # Slight lean to direct for English

    p = fp * fw + dp * dw
    s = fs * fw + ds * dw
    g = fg * fw + dg * dw
    return dominant(p, s, g)


def strategy_normalized_genre_spread(sg: dict) -> str:
    """Normalize both score sets, then apply genre+spread logic."""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']

    f_total = fp + fs + fg
    d_total = dp + ds + dg
    if f_total > 0:
        fn_p, fn_s, fn_g = fp/f_total, fs/f_total, fg/f_total
    else:
        fn_p, fn_s, fn_g = 1/3, 1/3, 1/3
    if d_total > 0:
        dn_p, dn_s, dn_g = dp/d_total, ds/d_total, dg/d_total
    else:
        dn_p, dn_s, dn_g = 1/3, 1/3, 1/3

    sp = spread(dp, ds, dg)

    if sg['is_indian']:
        if sg['is_devotional']:
            fw, dw = 0.85, 0.15
        else:
            fw, dw = 0.70, 0.30
    else:
        if sp > 0.4:
            return dominant(dn_p, dn_s, dn_g)
        else:
            fw, dw = 0.4, 0.6

    p = fn_p * fw + dn_p * dw
    s = fn_s * fw + dn_s * dw
    g = fn_g * fw + dn_g * dw
    return dominant(p, s, g)


def strategy_adaptive_margin(sg: dict) -> str:
    """Use the margin between top-2 scores as confidence signal for each source.
    Pick the source whose top prediction has a bigger margin."""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']

    f_sorted = sorted([fp, fs, fg], reverse=True)
    d_sorted = sorted([dp, ds, dg], reverse=True)

    f_margin = f_sorted[0] - f_sorted[1]
    d_margin = d_sorted[0] - d_sorted[1]

    if d_margin > f_margin:
        return dominant(dp, ds, dg)
    else:
        return dominant(fp, fs, fg)


def strategy_genre_spread_strict(sg: dict) -> str:
    """Like genre+spread but with stricter thresholds:
    English: only trust direct with spread > 0.5
    Indian: 80/20 formula/direct"""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']
    sp = spread(dp, ds, dg)

    if sg['is_indian']:
        fw, dw = 0.80, 0.20
    else:
        if sp > 0.5:
            return dominant(dp, ds, dg)
        else:
            fw, dw = 0.45, 0.55

    p = fp * fw + dp * dw
    s = fs * fw + ds * dw
    g = fg * fw + dg * dw
    return dominant(p, s, g)


def strategy_softmax_blend(sg: dict) -> str:
    """Apply softmax-like sharpening to both score sets before blending.
    This amplifies the differences, making the dominant score more dominant."""
    import math

    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']

    # Sharpen with temperature=0.3 (lower = sharper)
    temp = 0.3

    def sharpen(p, s, g, t):
        exps = [math.exp(x/t) for x in [p, s, g]]
        total = sum(exps)
        return [e/total for e in exps]

    fn = sharpen(fp, fs, fg, temp)
    dn = sharpen(dp, ds, dg, temp)

    if sg['is_indian']:
        fw, dw = 0.7, 0.3
    else:
        fw, dw = 0.3, 0.7

    sp = spread(dp, ds, dg)
    if sp > 0.4 and not sg['is_indian']:
        return dominant(dn[0], dn[1], dn[2])

    p = fn[0] * fw + dn[0] * dw
    s = fn[1] * fw + dn[1] * dw
    g = fn[2] * fw + dn[2] * dw
    return dominant(p, s, g)


def strategy_genre_spread_tuned(sg: dict) -> str:
    """The v1 winner with slightly tuned parameters.
    Key change: for Indian non-devotional, try 65/35 instead of 70/30.
    For English low-spread, try 35/65 instead of 50/50."""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']
    sp = spread(dp, ds, dg)

    if sg['is_indian']:
        if sg['is_devotional']:
            fw, dw = 0.85, 0.15
        else:
            fw, dw = 0.65, 0.35
    else:
        if sp > 0.4:
            spread_boost = 0.15
        elif sp > 0.25:
            spread_boost = 0.05
        else:
            spread_boost = -0.1
        dw = min(0.9, max(0.1, 0.65 + spread_boost))
        fw = 1.0 - dw

    p = fp * fw + dp * dw
    s = fs * fw + ds * dw
    g = fg * fw + dg * dw
    return dominant(p, s, g)


def strategy_two_stage(sg: dict) -> str:
    """Two-stage decision: first decide PARA vs non-PARA using direct (which
    is better at detecting calming songs), then decide SYMP vs GRND using formula
    (which is better at detecting grounding properties)."""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']

    # Stage 1: Is this a calming/PARA song?
    # Direct LLM is better at recognizing calming songs (especially for English)
    if sg['is_indian']:
        para_score = fp * 0.6 + dp * 0.4
    else:
        para_score = fp * 0.3 + dp * 0.7

    # If para score is highest, call it PARA
    # Need to compare against a threshold relative to other scores
    if sg['is_indian']:
        non_para_s = fs * 0.7 + ds * 0.3
        non_para_g = fg * 0.7 + dg * 0.3
    else:
        non_para_s = fs * 0.4 + ds * 0.6
        non_para_g = fg * 0.4 + dg * 0.6

    if para_score > max(non_para_s, non_para_g):
        return 'PARA'

    # Stage 2: SYMP vs GRND — use formula-weighted blend
    if non_para_s > non_para_g:
        return 'SYMP'
    else:
        return 'GRND'


def strategy_genre_spread_v3(sg: dict) -> str:
    """v1 winner logic but with finer per-category tuning:
    English: spread>0.3 (instead of >0.4) + 0.15 boost → direct
    Indian (devotional): 90/10 formula
    Indian (other): 75/25 formula with spread adjustment"""
    fp, fs, fg = sg['formula']['p'], sg['formula']['s'], sg['formula']['g']
    dp, ds, dg = sg['direct']['p'], sg['direct']['s'], sg['direct']['g']
    sp = spread(dp, ds, dg)

    if sg['is_indian']:
        if sg['is_devotional']:
            fw, dw = 0.90, 0.10
        else:
            # For Indian non-devotional, slight spread adjustment
            base_fw = 0.75
            if sp > 0.4:
                base_fw -= 0.10
            elif sp < 0.15:
                base_fw += 0.05
            fw = base_fw
            dw = 1.0 - fw
    else:
        if sp > 0.3:
            # High LLM confidence for English → go direct
            spread_boost = min(0.2, (sp - 0.3) * 0.5)
            dw = 0.7 + spread_boost
            fw = 1.0 - dw
        else:
            fw, dw = 0.45, 0.55

    p = fp * fw + dp * dw
    s = fs * fw + ds * dw
    g = fg * fw + dg * dw
    return dominant(p, s, g)


# ─────────────────────────────────────────────────────────────────────────────
# Run all strategies
# ─────────────────────────────────────────────────────────────────────────────
strategies = {
    'genre+spread_v1': None,  # Will copy from v1 data
    'genre_spread_v2': strategy_genre_spread_v2,
    'norm_genre_sprd': strategy_normalized_genre_spread,
    'adaptive_margin': strategy_adaptive_margin,
    'genre_sprd_strct': strategy_genre_spread_strict,
    'softmax_blend': strategy_softmax_blend,
    'genre_sprd_tuned': strategy_genre_spread_tuned,
    'two_stage': strategy_two_stage,
    'genre_spread_v3': strategy_genre_spread_v3,
}

results = {}
for strat_name, strat_fn in strategies.items():
    if strat_name == 'genre+spread_v1':
        # Copy from v1 saved data
        v1_data = data['strategy_results'].get('genre+spread', {})
        results[strat_name] = [
            {'name': p['name'], 'expected': p['expected'], 'predicted': p['predicted'], 'correct': p['correct']}
            for p in v1_data.get('predictions', [])
        ]
        continue

    per_song = []
    for sg in all_songs:
        predicted = strat_fn(sg)
        correct = predicted == sg['expected']
        per_song.append({
            'name': sg['name'],
            'cat': sg['cat'],
            'expected': sg['expected'],
            'predicted': predicted,
            'correct': correct,
        })
    results[strat_name] = per_song


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"ACCURACY SUMMARY (v2 refined strategies)")
print(f"{'='*90}")
print(f"{'Strategy':<20} {'Overall':>8} | {'English':>8} {'Pop Indian':>10} {'Obs Indian':>10}")
print(f"{'-'*20} {'-'*8} | {'-'*8} {'-'*10} {'-'*10}")

sorted_strats = sorted(strategies.keys(), key=lambda s: -sum(1 for r in results[s] if r['correct']))

for strat_name in sorted_strats:
    per_song = results[strat_name]
    total = len(per_song)
    correct = sum(1 for r in per_song if r['correct'])

    cats = {}
    for i, r in enumerate(per_song):
        cat = all_songs[i]['cat'] if 'cat' not in r else r.get('cat', all_songs[i]['cat'])
        if cat not in cats:
            cats[cat] = {'c': 0, 't': 0}
        cats[cat]['t'] += 1
        if r['correct']:
            cats[cat]['c'] += 1

    eng = cats.get('english', {'c': 0, 't': 1})
    pop = cats.get('popular_indian', {'c': 0, 't': 1})
    obs = cats.get('obscure_indian', {'c': 0, 't': 1})

    print(f"{strat_name:<20} {correct:>2}/{total:<2} {correct/total*100:>4.0f}% | "
          f"{eng['c']}/{eng['t']} {eng['c']/eng['t']*100:>4.0f}% "
          f"  {pop['c']}/{pop['t']} {pop['c']/pop['t']*100:>5.0f}% "
          f"  {obs['c']}/{obs['t']} {obs['c']/obs['t']*100:>5.0f}%")


# ─────────────────────────────────────────────────────────────────────────────
# Detailed comparison of top strategies
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"PER-SONG COMPARISON (top strategies)")
print(f"{'='*90}")

top_strats = sorted_strats[:5]
header = f"{'#':>2} {'Song':<35} {'Cat':<10} {'Exp':>4}"
for s in top_strats:
    header += f" {s[:8]:>8}"
print(header)

for i, sg in enumerate(all_songs):
    row = f"{i+1:>2} {sg['name'][:35]:<35} {sg['cat']:<10} {sg['expected']:>4}"
    for strat_name in top_strats:
        r = results[strat_name][i]
        mark = "Y" if r['correct'] else " "
        row += f" {r['predicted'][:4]:>5}{mark:>3}"
    print(row)


# ─────────────────────────────────────────────────────────────────────────────
# Category-level analysis of the best strategy
# ─────────────────────────────────────────────────────────────────────────────
best = sorted_strats[0]
print(f"\n{'='*90}")
print(f"BEST STRATEGY: {best}")
print(f"{'='*90}")

best_results = results[best]
best_correct = sum(1 for r in best_results if r['correct'])
print(f"Overall: {best_correct}/25 = {best_correct/25*100:.0f}%")

print(f"\nIncorrect predictions:")
for i, r in enumerate(best_results):
    if not r['correct']:
        sg = all_songs[i]
        f_dom = dominant(sg['formula']['p'], sg['formula']['s'], sg['formula']['g'])
        d_dom = dominant(sg['direct']['p'], sg['direct']['s'], sg['direct']['g'])
        sp = spread(sg['direct']['p'], sg['direct']['s'], sg['direct']['g'])
        print(f"  {sg['name'][:35]:<35} {sg['cat']:<10} expected={r['expected']} got={r['predicted']} "
              f"(formula={f_dom} direct={d_dom} spread={sp:.2f})")
