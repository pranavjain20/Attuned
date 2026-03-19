"""Experiment: Compare 4 neurological scoring approaches.

1. Current formula (baseline)
2. Direct LLM scoring (para/symp/grounding directly)
3. Fixed inputs (genre-based BPM correction + energy mastering fix)
4. Hybrid (average of fixed formula + direct LLM)
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH, get_openai_api_key
from classification.profiler import compute_neurological_profile
from openai import OpenAI

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

DEVOTIONAL_GENRES = {"devotional", "kirtan", "sufi", "bhajan", "spiritual", "chant", "mantra", "prayer"}


def dominant(p, s, g):
    scores = {'PARA': p, 'SYMP': s, 'GRND': g}
    return max(scores, key=scores.get)


# Load song data from DB
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

# Call LLM for direct scoring
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

# Compute all four approaches
print(f"{'#':>2} {'Song':<30} {'Cat':<8} {'Curr':>4}  {'Direct':>6}  {'Fixed':>5}  {'Hybrid':>6}  {'Exp':>4}")
print(f"{'--':>2} {'-'*30} {'-'*8} {'-'*5} {'-'*7} {'-'*6} {'-'*7} {'-'*5}")

results = {"current": [], "direct": [], "fixed": [], "hybrid": []}

for i, s in enumerate(songs_data):
    expected = energy_to_expected[s['gt_e']]

    # Current
    curr_dom = dominant(s['parasympathetic'] or 0, s['sympathetic'] or 0, s['grounding'] or 0)

    # Direct LLM
    llm_song = llm_direct['songs'][i] if i < len(llm_direct.get('songs', [])) else {}
    direct_p = llm_song.get('parasympathetic', 0.5)
    direct_s = llm_song.get('sympathetic', 0.5)
    direct_g = llm_song.get('grounding', 0.5)
    direct_dom = dominant(direct_p, direct_s, direct_g)

    # Fixed inputs
    genre_tags = []
    if s.get('genre_tags'):
        try:
            genre_tags = json.loads(s['genre_tags']) if isinstance(s['genre_tags'], str) else (s['genre_tags'] or [])
        except (json.JSONDecodeError, TypeError):
            genre_tags = []

    fixed_bpm = s['bpm']
    if genre_tags and any(g in DEVOTIONAL_GENRES for g in genre_tags):
        if fixed_bpm and fixed_bpm > 100:
            fixed_bpm = 75

    fixed_energy = s['energy']
    if fixed_bpm and fixed_energy:
        if fixed_bpm < 80 and fixed_energy > 0.6:
            fixed_energy = 0.35

    fixed_neuro = compute_neurological_profile(
        bpm=fixed_bpm, energy=fixed_energy, acousticness=s['acousticness'],
        instrumentalness=s['instrumentalness'], valence=s['valence'],
        mode=s['mode'], danceability=s['danceability'],
    )
    fixed_dom = dominant(fixed_neuro['parasympathetic'], fixed_neuro['sympathetic'], fixed_neuro['grounding'])

    # Hybrid
    hybrid_p = (fixed_neuro['parasympathetic'] + direct_p) / 2
    hybrid_s = (fixed_neuro['sympathetic'] + direct_s) / 2
    hybrid_g = (fixed_neuro['grounding'] + direct_g) / 2
    hybrid_dom = dominant(hybrid_p, hybrid_s, hybrid_g)

    for approach, dom in [("current", curr_dom), ("direct", direct_dom), ("fixed", fixed_dom), ("hybrid", hybrid_dom)]:
        results[approach].append(dom == expected)

    c_ok = "Y" if curr_dom == expected else " "
    d_ok = "Y" if direct_dom == expected else " "
    f_ok = "Y" if fixed_dom == expected else " "
    h_ok = "Y" if hybrid_dom == expected else " "

    print(f"{i+1:>2} {s['name'][:30]:<30} {s['cat']:<8} {curr_dom:>3} {c_ok} {direct_dom:>5} {d_ok} {fixed_dom:>4} {f_ok} {hybrid_dom:>5} {h_ok}  {expected:>4}")

# Summary
print(f"\n{'='*70}")
print(f"BUCKET ACCURACY")
print(f"{'='*70}")

for approach in ["current", "direct", "fixed", "hybrid"]:
    total = len(results[approach])
    correct = sum(results[approach])
    cats = {}
    for i, s in enumerate(songs_data):
        cat = s['cat']
        if cat not in cats:
            cats[cat] = {'c': 0, 't': 0}
        cats[cat]['t'] += 1
        if results[approach][i]:
            cats[cat]['c'] += 1

    parts = []
    for cat in ['english', 'popular_indian', 'obscure_indian']:
        if cat in cats:
            pct = cats[cat]['c'] / cats[cat]['t'] * 100
            parts.append(f"{cat}={pct:.0f}%")

    print(f"  {approach:<10} {correct}/{total} = {correct/total*100:.0f}%  ({', '.join(parts)})")

conn.close()
