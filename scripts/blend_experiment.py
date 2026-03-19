"""Experiment: Find optimal blending strategy for formula vs direct LLM neurological scores.

Tests multiple strategies for combining:
- Formula-based scoring (profiler.py): good for obscure Indian, bad for English
- Direct LLM scoring (GPT-4o-mini para/symp/grnd): good for English, bad for popular Indian

Ground truth: 25 songs with known energy buckets mapped to expected dominant score.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH, get_openai_api_key
from classification.profiler import compute_neurological_profile
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Ground truth
# ─────────────────────────────────────────────────────────────────────────────
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
INDIAN_GENRE_LOWER = {
    "bollywood", "hindi", "punjabi", "indian", "desi", "bhangra",
    "sufi", "ghazal", "qawwali", "devotional", "filmi", "indi-pop",
    "indian pop", "indian classical", "hindustani", "carnatic",
    "world", "spiritual",
}


def dominant(p: float, s: float, g: float) -> str:
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


def parse_genre_tags(raw) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (json.JSONDecodeError, TypeError):
        return []


def is_indian_song(genre_tags: list[str]) -> bool:
    return any(g.lower() in INDIAN_GENRE_LOWER for g in genre_tags)


def is_devotional(genre_tags: list[str]) -> bool:
    return any(g.lower() in DEVOTIONAL_GENRES for g in genre_tags)


def spread(p: float, s: float, g: float) -> float:
    """Max minus min of the three scores. High spread = LLM is confident."""
    return max(p, s, g) - min(p, s, g)


def max_score(p: float, s: float, g: float) -> float:
    """The highest of the three scores."""
    return max(p, s, g)


# ─────────────────────────────────────────────────────────────────────────────
# Load data from DB
# ─────────────────────────────────────────────────────────────────────────────
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

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

# ─────────────────────────────────────────────────────────────────────────────
# Get direct LLM neurological scores
# ─────────────────────────────────────────────────────────────────────────────
system_prompt = """You are a music neuroscience expert. For each song, score its effect on the autonomic nervous system based on the research:

- Parasympathetic activation (vagal tone, calming): driven by slow tempo (<80 BPM), low energy, acoustic instruments, moderate-low valence, instrumental/minimal vocals
- Sympathetic activation (arousal, energizing): driven by fast tempo (>120 BPM), high energy, electronic production, high valence, strong rhythm
- Emotional grounding (centered, present): driven by moderate tempo (~70-80 BPM), warm acoustic tone, moderate energy, familiar/comforting feel, gentle rhythm

Some songs include duration and audio measurements. Use all available context.

Return a JSON object with a "songs" array. Each element must have:
- "title": exact song title
- "artist": exact artist name
- "parasympathetic": float 0.0-1.0 (how strongly this song activates the parasympathetic/calming response)
- "sympathetic": float 0.0-1.0 (how strongly this song activates the sympathetic/energizing response)
- "grounding": float 0.0-1.0 (how strongly this song provides emotional grounding)

Rules:
- Use the FULL 0.0-1.0 range. A quiet acoustic prayer should be 0.8+ parasympathetic. A loud dance track should be 0.8+ sympathetic.
- These are physiological effects based on music properties, not subjective feelings.
- A song CAN score moderately on multiple dimensions.
- Return ONLY valid JSON."""

lines = ["Score these songs:\n"]
for s in songs_data:
    parts = [f'"{s["name"]}" by {s["artist"]}']
    if s.get("album"):
        parts.append(f'(album: {s["album"]})')
    if s.get("duration_ms"):
        parts.append(f'[duration: {s["duration_ms"]/60000:.1f}min]')
    if s.get("energy") is not None:
        parts.append(f'[audio: energy={s["energy"]:.2f}, acousticness={s["acousticness"]:.2f}]')
    lines.append(" ".join(parts))

print("Calling LLM for direct neurological scores...")
client = OpenAI(api_key=get_openai_api_key())
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(lines)},
    ],
    response_format={"type": "json_object"},
    temperature=0,
)
llm_direct = json.loads(response.choices[0].message.content)
print(f"Tokens: {response.usage.total_tokens}\n")

# ─────────────────────────────────────────────────────────────────────────────
# Build score arrays for each song
# ─────────────────────────────────────────────────────────────────────────────
all_songs = []
for i, s in enumerate(songs_data):
    genre_tags = parse_genre_tags(s.get('genre_tags'))
    expected = energy_to_expected[s['gt_e']]

    # Formula scores (from DB)
    f_p = s['parasympathetic'] or 0
    f_s = s['sympathetic'] or 0
    f_g = s['grounding'] or 0

    # Direct LLM scores
    llm_song = llm_direct['songs'][i] if i < len(llm_direct.get('songs', [])) else {}
    d_p = llm_song.get('parasympathetic', 0.5)
    d_s = llm_song.get('sympathetic', 0.5)
    d_g = llm_song.get('grounding', 0.5)

    # DB confidence (from LLM classification confidence)
    db_confidence = s.get('confidence') or 0.8

    all_songs.append({
        'name': s['name'],
        'artist': s['artist'],
        'cat': s['cat'],
        'gt_e': s['gt_e'],
        'expected': expected,
        'genre_tags': genre_tags,
        'db_confidence': db_confidence,
        # Formula scores
        'f_p': f_p, 'f_s': f_s, 'f_g': f_g,
        # Direct LLM scores
        'd_p': d_p, 'd_s': d_s, 'd_g': d_g,
        # LLM spread (confidence signal)
        'd_spread': spread(d_p, d_s, d_g),
        'd_max': max_score(d_p, d_s, d_g),
        # Is this an Indian song?
        'is_indian': is_indian_song(genre_tags),
        'is_devotional': is_devotional(genre_tags),
        # Raw DB properties for recomputation
        'bpm': s.get('bpm'),
        'energy': s.get('energy'),
        'acousticness': s.get('acousticness'),
        'instrumentalness': s.get('instrumentalness'),
        'valence': s.get('valence'),
        'mode': s.get('mode'),
        'danceability': s.get('danceability'),
    })

conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# Print raw scores for inspection
# ─────────────────────────────────────────────────────────────────────────────
print(f"{'#':>2} {'Song':<30} {'Cat':<8} {'F_P':>5} {'F_S':>5} {'F_G':>5} | {'D_P':>5} {'D_S':>5} {'D_G':>5} {'Sprd':>5} | {'Exp':>4}")
print(f"{'--':>2} {'-'*30} {'-'*8} {'-'*5} {'-'*5} {'-'*5} | {'-'*5} {'-'*5} {'-'*5} {'-'*5} | {'-'*4}")

for i, sg in enumerate(all_songs):
    print(f"{i+1:>2} {sg['name'][:30]:<30} {sg['cat']:<8} "
          f"{sg['f_p']:.3f} {sg['f_s']:.3f} {sg['f_g']:.3f} | "
          f"{sg['d_p']:.3f} {sg['d_s']:.3f} {sg['d_g']:.3f} {sg['d_spread']:.3f} | "
          f"{sg['expected']:>4}")


# ─────────────────────────────────────────────────────────────────────────────
# Define blending strategies
# ─────────────────────────────────────────────────────────────────────────────
def strategy_formula_only(sg: dict) -> str:
    """Baseline: formula scores only."""
    return dominant(sg['f_p'], sg['f_s'], sg['f_g'])


def strategy_direct_only(sg: dict) -> str:
    """Baseline: direct LLM scores only."""
    return dominant(sg['d_p'], sg['d_s'], sg['d_g'])


def strategy_simple_average(sg: dict) -> str:
    """50/50 average of formula and direct."""
    p = (sg['f_p'] + sg['d_p']) / 2
    s = (sg['f_s'] + sg['d_s']) / 2
    g = (sg['f_g'] + sg['d_g']) / 2
    return dominant(p, s, g)


def strategy_confidence_weighted(sg: dict) -> str:
    """Weight direct LLM by DB confidence (higher confidence = trust direct more).
    Confidence ranges 0.5-1.0. Normalize to 0.0-1.0 as direct weight."""
    conf = sg['db_confidence']
    # Higher confidence = LLM was more sure of its classification = trust formula more
    # (since formula uses those classified properties)
    # Lower confidence = LLM guessed = trust direct scoring more
    # Actually, confidence is about the LLM classification (BPM/energy/etc) quality.
    # High confidence → formula inputs are reliable → weight formula higher
    formula_weight = conf  # 0.5-1.0
    direct_weight = 1.0 - formula_weight
    total = formula_weight + direct_weight
    p = (sg['f_p'] * formula_weight + sg['d_p'] * direct_weight) / total
    s = (sg['f_s'] * formula_weight + sg['d_s'] * direct_weight) / total
    g = (sg['f_g'] * formula_weight + sg['d_g'] * direct_weight) / total
    return dominant(p, s, g)


def strategy_confidence_weighted_inverse(sg: dict) -> str:
    """Inverse: low confidence → trust direct more, high confidence → trust formula more.
    But remap so the range is meaningful."""
    conf = sg['db_confidence']
    # conf=1.0 → formula_w=0.7, direct_w=0.3
    # conf=0.5 → formula_w=0.3, direct_w=0.7
    formula_weight = 0.3 + 0.4 * conf
    direct_weight = 1.0 - formula_weight
    p = sg['f_p'] * formula_weight + sg['d_p'] * direct_weight
    s = sg['f_s'] * formula_weight + sg['d_s'] * direct_weight
    g = sg['f_g'] * formula_weight + sg['d_g'] * direct_weight
    return dominant(p, s, g)


def strategy_genre_heuristic(sg: dict) -> str:
    """If Indian → lean formula (70/30), if English → lean direct (30/70)."""
    if sg['is_indian']:
        fw, dw = 0.7, 0.3
    else:
        fw, dw = 0.3, 0.7
    p = sg['f_p'] * fw + sg['d_p'] * dw
    s = sg['f_s'] * fw + sg['d_s'] * dw
    g = sg['f_g'] * fw + sg['d_g'] * dw
    return dominant(p, s, g)


def strategy_genre_heuristic_extreme(sg: dict) -> str:
    """If Indian → lean formula (80/20), if English → lean direct (20/80)."""
    if sg['is_indian']:
        fw, dw = 0.8, 0.2
    else:
        fw, dw = 0.2, 0.8
    p = sg['f_p'] * fw + sg['d_p'] * dw
    s = sg['f_s'] * fw + sg['d_s'] * dw
    g = sg['f_g'] * fw + sg['d_g'] * dw
    return dominant(p, s, g)


def strategy_spread_weighted(sg: dict) -> str:
    """Use LLM score spread as confidence signal.
    High spread (>0.3) → LLM is confident → weight direct more.
    Low spread (<0.15) → LLM is guessing → weight formula more."""
    sp = sg['d_spread']
    # Map spread to direct weight: spread 0→0.2, spread 0.5→0.8
    direct_weight = min(0.8, max(0.2, 0.2 + 1.2 * sp))
    formula_weight = 1.0 - direct_weight
    p = sg['f_p'] * formula_weight + sg['d_p'] * direct_weight
    s = sg['f_s'] * formula_weight + sg['d_s'] * direct_weight
    g = sg['f_g'] * formula_weight + sg['d_g'] * direct_weight
    return dominant(p, s, g)


def strategy_pick_by_spread(sg: dict) -> str:
    """Pick-the-best: if LLM spread > 0.3, use direct. Otherwise, use formula."""
    if sg['d_spread'] > 0.3:
        return dominant(sg['d_p'], sg['d_s'], sg['d_g'])
    else:
        return dominant(sg['f_p'], sg['f_s'], sg['f_g'])


def strategy_pick_by_spread_025(sg: dict) -> str:
    """Pick: if LLM spread > 0.25, use direct. Otherwise, use formula."""
    if sg['d_spread'] > 0.25:
        return dominant(sg['d_p'], sg['d_s'], sg['d_g'])
    else:
        return dominant(sg['f_p'], sg['f_s'], sg['f_g'])


def strategy_genre_plus_spread(sg: dict) -> str:
    """Combine genre heuristic with spread signal.
    Base weights from genre, then adjust by spread."""
    if sg['is_indian']:
        base_fw, base_dw = 0.7, 0.3
    else:
        base_fw, base_dw = 0.3, 0.7

    # If LLM has high spread (confident), boost direct weight
    sp = sg['d_spread']
    if sp > 0.4:
        spread_boost = 0.15
    elif sp > 0.25:
        spread_boost = 0.05
    else:
        spread_boost = -0.1  # Low spread = less confidence in direct

    dw = min(0.9, max(0.1, base_dw + spread_boost))
    fw = 1.0 - dw
    p = sg['f_p'] * fw + sg['d_p'] * dw
    s = sg['f_s'] * fw + sg['d_s'] * dw
    g = sg['f_g'] * fw + sg['d_g'] * dw
    return dominant(p, s, g)


def strategy_devotional_aware(sg: dict) -> str:
    """Like genre heuristic, but devotional songs go 90% formula.
    Devotional = the category LLM struggles with most."""
    if sg['is_devotional']:
        fw, dw = 0.9, 0.1
    elif sg['is_indian']:
        fw, dw = 0.6, 0.4
    else:
        fw, dw = 0.3, 0.7
    p = sg['f_p'] * fw + sg['d_p'] * dw
    s = sg['f_s'] * fw + sg['d_s'] * dw
    g = sg['f_g'] * fw + sg['d_g'] * dw
    return dominant(p, s, g)


def strategy_max_confidence(sg: dict) -> str:
    """Pick whichever source has higher max score (more decisive)."""
    f_max = max(sg['f_p'], sg['f_s'], sg['f_g'])
    d_max = max(sg['d_p'], sg['d_s'], sg['d_g'])
    if d_max > f_max:
        return dominant(sg['d_p'], sg['d_s'], sg['d_g'])
    else:
        return dominant(sg['f_p'], sg['f_s'], sg['f_g'])


def strategy_weighted_60_40_direct(sg: dict) -> str:
    """60% direct, 40% formula (since direct is better overall 52 vs 48)."""
    fw, dw = 0.4, 0.6
    p = sg['f_p'] * fw + sg['d_p'] * dw
    s = sg['f_s'] * fw + sg['d_s'] * dw
    g = sg['f_g'] * fw + sg['d_g'] * dw
    return dominant(p, s, g)


def strategy_agreement_boost(sg: dict) -> str:
    """When formula and direct agree on dominant bucket, use that.
    When they disagree, use genre heuristic to break the tie."""
    f_dom = dominant(sg['f_p'], sg['f_s'], sg['f_g'])
    d_dom = dominant(sg['d_p'], sg['d_s'], sg['d_g'])

    if f_dom == d_dom:
        return f_dom
    else:
        # Disagree → use genre-weighted blend
        if sg['is_indian']:
            fw, dw = 0.7, 0.3
        else:
            fw, dw = 0.3, 0.7
        p = sg['f_p'] * fw + sg['d_p'] * dw
        s = sg['f_s'] * fw + sg['d_s'] * dw
        g = sg['f_g'] * fw + sg['d_g'] * dw
        return dominant(p, s, g)


def strategy_spread_genre_combo(sg: dict) -> str:
    """Best of both worlds: use spread for English, genre+formula for Indian.
    English: if spread > 0.3 use direct, else 50/50
    Indian: always 75/25 formula/direct"""
    if sg['is_indian']:
        fw, dw = 0.75, 0.25
    else:
        if sg['d_spread'] > 0.3:
            return dominant(sg['d_p'], sg['d_s'], sg['d_g'])
        else:
            fw, dw = 0.5, 0.5
    p = sg['f_p'] * fw + sg['d_p'] * dw
    s = sg['f_s'] * fw + sg['d_s'] * dw
    g = sg['f_g'] * fw + sg['d_g'] * dw
    return dominant(p, s, g)


def strategy_normalized_blend(sg: dict) -> str:
    """Normalize both score sets to sum to 1.0, then average.
    This handles the different scales of formula (0.2-0.5) vs direct (0.1-0.9)."""
    f_total = sg['f_p'] + sg['f_s'] + sg['f_g']
    d_total = sg['d_p'] + sg['d_s'] + sg['d_g']

    if f_total > 0:
        fn_p, fn_s, fn_g = sg['f_p']/f_total, sg['f_s']/f_total, sg['f_g']/f_total
    else:
        fn_p, fn_s, fn_g = 1/3, 1/3, 1/3

    if d_total > 0:
        dn_p, dn_s, dn_g = sg['d_p']/d_total, sg['d_s']/d_total, sg['d_g']/d_total
    else:
        dn_p, dn_s, dn_g = 1/3, 1/3, 1/3

    p = (fn_p + dn_p) / 2
    s = (fn_s + dn_s) / 2
    g = (fn_g + dn_g) / 2
    return dominant(p, s, g)


def strategy_normalized_genre(sg: dict) -> str:
    """Normalize both to sum=1.0, then use genre-weighted blend."""
    f_total = sg['f_p'] + sg['f_s'] + sg['f_g']
    d_total = sg['d_p'] + sg['d_s'] + sg['d_g']

    if f_total > 0:
        fn_p, fn_s, fn_g = sg['f_p']/f_total, sg['f_s']/f_total, sg['f_g']/f_total
    else:
        fn_p, fn_s, fn_g = 1/3, 1/3, 1/3

    if d_total > 0:
        dn_p, dn_s, dn_g = sg['d_p']/d_total, sg['d_s']/d_total, sg['d_g']/d_total
    else:
        dn_p, dn_s, dn_g = 1/3, 1/3, 1/3

    if sg['is_indian']:
        fw, dw = 0.7, 0.3
    else:
        fw, dw = 0.3, 0.7

    p = fn_p * fw + dn_p * dw
    s = fn_s * fw + dn_s * dw
    g = fn_g * fw + dn_g * dw
    return dominant(p, s, g)


def strategy_rank_fusion(sg: dict) -> str:
    """Rank fusion: rank each bucket 1st/2nd/3rd in each source, sum ranks.
    Lowest total rank wins."""
    f_scores = [('PARA', sg['f_p']), ('SYMP', sg['f_s']), ('GRND', sg['f_g'])]
    d_scores = [('PARA', sg['d_p']), ('SYMP', sg['d_s']), ('GRND', sg['d_g'])]

    f_ranked = sorted(f_scores, key=lambda x: -x[1])
    d_ranked = sorted(d_scores, key=lambda x: -x[1])

    rank_sums = {}
    for rank, (bucket, _) in enumerate(f_ranked):
        rank_sums[bucket] = rank
    for rank, (bucket, _) in enumerate(d_ranked):
        rank_sums[bucket] = rank_sums.get(bucket, 0) + rank

    return min(rank_sums, key=rank_sums.get)


# ─────────────────────────────────────────────────────────────────────────────
# Run all strategies
# ─────────────────────────────────────────────────────────────────────────────
strategies = {
    'formula_only': strategy_formula_only,
    'direct_only': strategy_direct_only,
    'simple_avg': strategy_simple_average,
    'conf_weighted': strategy_confidence_weighted,
    'conf_inv': strategy_confidence_weighted_inverse,
    'genre_70_30': strategy_genre_heuristic,
    'genre_80_20': strategy_genre_heuristic_extreme,
    'spread_weighted': strategy_spread_weighted,
    'pick_spread_030': strategy_pick_by_spread,
    'pick_spread_025': strategy_pick_by_spread_025,
    'genre+spread': strategy_genre_plus_spread,
    'devotional_aware': strategy_devotional_aware,
    'max_confidence': strategy_max_confidence,
    'weighted_60_40_d': strategy_weighted_60_40_direct,
    'agreement_boost': strategy_agreement_boost,
    'spread_genre_cmb': strategy_spread_genre_combo,
    'normalized_avg': strategy_normalized_blend,
    'normalized_genre': strategy_normalized_genre,
    'rank_fusion': strategy_rank_fusion,
}

results = {}
for strat_name, strat_fn in strategies.items():
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
# Print detailed results
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"BLENDING STRATEGY COMPARISON — Per-Song Results")
print(f"{'='*110}")

# Header
header = f"{'#':>2} {'Song':<30} {'Cat':<8} {'Exp':>4}"
for strat_name in strategies:
    header += f" {strat_name[:6]:>6}"
print(header)
print(f"{'--':>2} {'-'*30} {'-'*8} {'-'*4}" + (" " + "-"*6) * len(strategies))

for i, sg in enumerate(all_songs):
    row = f"{i+1:>2} {sg['name'][:30]:<30} {sg['cat']:<8} {sg['expected']:>4}"
    for strat_name in strategies:
        r = results[strat_name][i]
        mark = "Y" if r['correct'] else " "
        row += f" {r['predicted'][:4]:>4}{mark:>2}"
    print(row)


# ─────────────────────────────────────────────────────────────────────────────
# Summary table
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"ACCURACY SUMMARY")
print(f"{'='*110}")
print(f"{'Strategy':<20} {'Overall':>8} | {'English':>8} {'Pop Indian':>10} {'Obs Indian':>10}")
print(f"{'-'*20} {'-'*8} | {'-'*8} {'-'*10} {'-'*10}")

# Sort by overall accuracy descending
sorted_strats = sorted(strategies.keys(), key=lambda s: -sum(1 for r in results[s] if r['correct']))

for strat_name in sorted_strats:
    per_song = results[strat_name]
    total = len(per_song)
    correct = sum(1 for r in per_song if r['correct'])

    cats = {}
    for r in per_song:
        cat = r['cat']
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
# Per-song analysis: which songs are NEVER correct across all strategies?
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"PER-SONG DIFFICULTY (how many strategies got it right)")
print(f"{'='*110}")

for i, sg in enumerate(all_songs):
    n_correct = sum(1 for strat_name in strategies if results[strat_name][i]['correct'])
    n_total = len(strategies)
    difficulty = "EASY" if n_correct > n_total * 0.7 else "HARD" if n_correct < n_total * 0.3 else "MIXED"

    # Show what formula and direct predict for hard songs
    f_pred = dominant(sg['f_p'], sg['f_s'], sg['f_g'])
    d_pred = dominant(sg['d_p'], sg['d_s'], sg['d_g'])

    extra = ""
    if difficulty == "HARD":
        extra = f"  formula={f_pred} direct={d_pred} f_scores=({sg['f_p']:.2f},{sg['f_s']:.2f},{sg['f_g']:.2f}) d_scores=({sg['d_p']:.2f},{sg['d_s']:.2f},{sg['d_g']:.2f})"

    print(f"{i+1:>2} {sg['name'][:30]:<30} {sg['cat']:<8} {sg['expected']:>4} → {n_correct:>2}/{n_total} [{difficulty}]{extra}")


# ─────────────────────────────────────────────────────────────────────────────
# Winner
# ─────────────────────────────────────────────────────────────────────────────
best_name = sorted_strats[0]
best_correct = sum(1 for r in results[best_name] if r['correct'])
best_pct = best_correct / len(all_songs) * 100

print(f"\n{'='*110}")
print(f"BEST STRATEGY: {best_name} at {best_correct}/{len(all_songs)} = {best_pct:.0f}%")
print(f"{'='*110}")

# Save all raw data for further analysis
output_data = {
    'songs': [],
    'strategy_results': {},
}
for sg in all_songs:
    output_data['songs'].append({
        'name': sg['name'],
        'artist': sg['artist'],
        'cat': sg['cat'],
        'gt_e': sg['gt_e'],
        'expected': sg['expected'],
        'formula': {'p': sg['f_p'], 's': sg['f_s'], 'g': sg['f_g']},
        'direct': {'p': sg['d_p'], 's': sg['d_s'], 'g': sg['d_g']},
        'spread': sg['d_spread'],
        'db_confidence': sg['db_confidence'],
        'genre_tags': sg['genre_tags'],
        'is_indian': sg['is_indian'],
        'is_devotional': sg['is_devotional'],
    })

for strat_name in sorted_strats:
    per_song = results[strat_name]
    correct = sum(1 for r in per_song if r['correct'])
    output_data['strategy_results'][strat_name] = {
        'accuracy': correct / len(per_song),
        'correct': correct,
        'total': len(per_song),
        'predictions': [{'name': r['name'], 'predicted': r['predicted'], 'expected': r['expected'], 'correct': r['correct']} for r in per_song],
    }

output_path = Path(__file__).parent / 'blend_experiment_results.json'
with open(output_path, 'w') as f:
    json.dump(output_data, f, indent=2)
print(f"\nRaw data saved to {output_path}")
