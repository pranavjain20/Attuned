# Attuned

Every WHOOP user sees their recovery score and thinks "I should do something about this." Nobody does. You can't will your nervous system into recovery. But you can press play on a playlist -- and music directly modulates the autonomic nervous system, the same system WHOOP measures.

Attuned reads your morning WHOOP data, figures out what your nervous system needs, and builds a playlist from your own library whose acoustic properties are scientifically matched to your recovery state. Not a calming sounds app. Your songs, chosen by neuroscience.

```
python main.py generate
```

```
State: Accumulated Fatigue  |  Recovery: 25%  |  HRV: 32ms
Playlist: "Mar 20 — Slow Down" (18 tracks)
Calming your nervous system · Bollywood · Melancholy, Reflective
→ open.spotify.com/playlist/...
```

---

## Why This Exists

Wearables have an insight-to-action gap. WHOOP is excellent at diagnosis -- it tells you your HRV is down, your deep sleep was short, your resting heart rate crept up. But then what? You can't will your nervous system into recovery. You can't undo accumulated fatigue by reading a dashboard.

Music directly modulates the autonomic nervous system -- the same system WHOOP measures. Slow tempo increases parasympathetic activity and raises HRV (Bretherton et al., 2019). Fast tempo activates the sympathetic response (Bernardi et al., 2006). Acoustic instruments reduce cortisol (Thoma et al., 2013). Familiar music amplifies the effect -- 74.8% of people respond more strongly to their own music (European Heart Journal, 2024).

And critically: people already listen to music every day. No behavior change required. Attuned doesn't ask you to do anything new. It makes something you already do work harder for you.

---

## How It Works

```
WHOOP Recovery Data
        |
        v
  +-----------+     30-day rolling baselines
  |  WHOOP    |     7-day HRV/RHR trend slopes
  |  Intel    |     Sleep architecture analysis (deep/REM ratios)
  +-----------+     Sleep debt trajectory
        |
        v
  +-----------+
  |  State    |---> 1 of 7 physiological states
  | Classifier|     (priority-ordered, personal-baseline-relative)
  +-----------+
        |
        v
  +-----------+     Neuro-score dot product (para x symp x grnd)
  | Matching  |     Confidence weighting, freshness nudge
  |  Engine   |     Seed-and-expand cohesion for sonic coherence
  +-----------+
        |
        v
  +-----------+
  | Spotify   |---> Dated playlist with state-specific description
  |   Push    |     Logged to DB with full reasoning chain
  +-----------+
```

### The Two Intelligence Layers

**Body intelligence.** Every WHOOP metric is interpreted against personal baselines -- 30-day rolling means, standard deviations, and coefficients of variation using log-transformed RMSSD (following the Plews/Buchheit methodology from sports science). A 50% recovery means something completely different if your 30-day HRV average is 48ms versus 65ms. The system tracks 7-day trend slopes for HRV and resting heart rate, computes rolling sleep debt, and analyzes sleep stage ratios against personal norms. All of this feeds a priority-ordered state classifier.

**Song intelligence.** Every song in your library is classified with two independent sources:

| Source | What it measures | Strength |
|--------|-----------------|----------|
| GPT-4o-mini (LLM) | BPM, valence, danceability, instrumentalness, mood tags, genre tags, direct neuro scores | Cultural context, semantic understanding |
| Essentia (audio analysis) | BPM, key, mode, energy, acousticness from 30-second audio clips | Objective measurement -- 71% energy accuracy vs LLM's 42% |

A confidence-aware ensemble blends the two sources, weighting each based on structural knowledge of where they fail (e.g., the LLM stereotypes obscure Indian music; Essentia can't measure valence).

Each song receives three neurological scores via a weighted profiler formula:
- **Parasympathetic** (calming) -- slow tempo, low energy, acoustic, instrumental
- **Sympathetic** (energizing) -- fast tempo, high energy, electronic, danceable
- **Grounding** (emotional centering) -- moderate tempo, vocal, warm, reflective

These three dimensions were deliberately decorrelated (r=0.638, down from 0.921) so the system can distinguish "your body needs deep rest" from "your mind needs emotional processing."

### The Seven States

| Priority | State | Trigger | What the playlist does |
|----------|-------|---------|----------------------|
| 1 | Accumulated Fatigue | Recovery < 60% for 3+ of last 5 days | Parasympathetic restoration -- slow, acoustic, instrumental |
| 2 | Poor Sleep | Both deep AND REM deficit | Mixed calming + grounding |
| 3 | Physical Recovery Deficit | Deep sleep deficit, REM adequate | Gentle music -- body rests, mind stays present |
| 4 | Emotional Processing Deficit | REM deficit, deep sleep adequate | Warm, vocal, familiar -- emotional grounding through lyrics |
| 5 | Poor Recovery | Recovery < 40% (acute) or < 60% (isolated) | Light support without overreacting |
| 6 | Peak Readiness | Recovery >= 80%, HRV >= baseline, no deficits | High-energy, positive, full intensity |
| 7 | Baseline | No strong signals | Good varied playlist, no intervention needed |

Priority order matters. Multi-day fatigue is checked before single-day poor recovery. Sleep deficits are checked before general poor recovery because they're more specific -- knowing it's deep sleep versus REM changes the music.

### The Matching Engine

Songs are scored against the detected state using a dot product across the three neurological dimensions:

```
neuro_match = (song.para * state.para + song.symp * state.symp + song.grnd * state.grnd) / |state_vector|
```

The top 60 candidates pass through a seed-and-expand cohesion engine that ensures sonic coherence -- genre overlap, mood alignment, BPM similarity, era clustering (with genre-aware decay: hip-hop clusters tightly by year, ghazal is timeless), energy similarity. The result is 15-20 songs that are both neurologically correct and sound like they belong together.

Additional modifiers: confidence weighting penalizes LLM-only songs, freshness nudge rotates near-ties across consecutive days (~45% turnover), a restorative sleep gate overrides accumulated fatigue when last night's sleep was genuinely restorative (research: last night's sleep is the strongest predictor of next-morning subjective state), and recovery delta modifiers boost playlist energy when recovery jumps sharply (24% to 80% gets a different playlist than steady 80%).

---

## The Science

Every threshold, weight, and property range traces back to published research. Key studies:

- **Bretherton et al., 2019** -- Baroreflex sensitivity significantly greater at 60 BPM vs 120 BPM (p < 0.001), driven entirely by parasympathetic activity
- **Bernardi et al., 2006** -- Blood pressure, heart rate, LF:HF ratio all increase proportional to tempo
- **Plews et al., 2012 / Buchheit, 2014** -- LnRMSSD rolling averages as the standard for detecting overreaching and recovery status
- **Thoma et al., 2013** -- Classical/acoustic music reduced cortisol, HR, and BP in controlled stress paradigm
- **Chanda & Levitin, 2013** -- Familiar music triggers stronger dopamine release via reward circuit
- **Kim et al., 2024** -- 60-80 BPM music inhibited sympathetic activity; 120-140 BPM increased it
- **Khalfa et al., 2002** -- Major mode produced larger skin conductance responses and faster HR than minor mode
- **Zhang et al., 2024** -- Major mode decreased salivary cortisol more than minor; minor elicited higher arousal
- **Karageorghis & Priest, 2012** -- Comprehensive review confirming tempo as primary driver, energy/rhythm as secondary
- **European Heart Journal, 2024** -- 74.8% of participants responded more strongly to personal preferred music
- **Van Dongen & Dinges, 2003** -- 5+ hours cumulative sleep debt over 7 days produces detectable cognitive impairment

The profiler uses a 69-tag weighted mood affinity table mapping mood descriptors to neurological dimensions (e.g., "reflective" scores 0.85 grounding, 0.30 parasympathetic, 0.05 sympathetic). Audio properties carry 85% of the scoring weight; mood tags add a 15% semantic signal orthogonal to audio -- "reflective" versus "melancholy" can't be distinguished by BPM alone.

Full research analysis with methodology notes and evidence quality caveats: [docs/RESEARCH.md](docs/RESEARCH.md)

---

## Quick Start

### Prerequisites

- Python 3.11+
- WHOOP account with developer API access ([developer.whoop.com](https://developer.whoop.com))
- Spotify account with developer API access ([developer.spotify.com](https://developer.spotify.com))
- OpenAI API key (song classification, ~$0.70 for a full library)

### Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in API credentials in .env
```

### First Run (New User)

```bash
python main.py onboard
```

Onboarding syncs your WHOOP history, imports your Spotify library, classifies your songs, and computes your personal baselines. Takes about 30 minutes depending on library size.

### Daily Use

```bash
python main.py generate
```

Reads today's WHOOP data, classifies your state, builds and pushes a playlist to Spotify.

### Other Commands

```bash
python main.py sync-whoop          # Incremental WHOOP data sync
python main.py sync-spotify        # Refresh Spotify library
python main.py classify-songs      # Classify unclassified songs
python main.py analyze-audio       # Run Essentia on unanalyzed songs
python main.py generate --dry-run  # Preview without pushing to Spotify
```

---

## Architecture

```
attuned/
├── main.py                          # CLI entry point
├── config.py                        # Constants, mood affinity table, thresholds
├── db/
│   ├── schema.py                    # SQLite table definitions + migrations
│   └── queries.py                   # Database access layer
├── whoop/
│   ├── auth.py                      # OAuth 2.0 with offline refresh tokens
│   ├── client.py                    # Recovery, sleep, cycle API calls (httpx)
│   └── sync.py                      # Full history sync + incremental updates
├── spotify/
│   ├── auth.py                      # OAuth 2.0 via Spotipy
│   ├── client.py                    # Library access (liked songs, top tracks, history)
│   ├── playlist.py                  # Playlist creation + description generation
│   ├── engagement.py                # 5-signal engagement scoring
│   ├── dedup.py                     # Near-duplicate detection
│   └── sync.py                      # Song pool sync + deduplication
├── intelligence/
│   ├── baselines.py                 # 30-day rolling means, SDs, CVs (LnRMSSD)
│   ├── trends.py                    # 7-day HRV/RHR slopes, sleep debt trajectory
│   ├── sleep_analysis.py            # Deep/REM ratios vs personal norms
│   └── state_classifier.py          # Priority-ordered composite state detection
├── classification/
│   ├── llm_classifier.py            # GPT-4o-mini batch classification (5 songs/call)
│   ├── essentia_analyzer.py         # Audio feature extraction from clips
│   ├── profiler.py                  # Neurological impact scoring (3 dimensions)
│   └── validator.py                 # Post-classification quality checks
├── matching/
│   ├── state_mapper.py              # State -> neuro profile targets
│   ├── query_engine.py              # Dot product scoring + candidate selection
│   ├── cohesion.py                  # Seed-and-expand with genre-aware era decay
│   └── generator.py                 # End-to-end pipeline orchestration
├── tests/                           # 1,016 tests across 25 test files
└── docs/
    ├── RESEARCH.md                  # Full research analysis with citations
    ├── HOW_IT_WORKS.md              # Complete technical guide
    ├── SYSTEM_LOGIC.md              # Plain-language system explanation
    └── PRODUCT_DECISIONS.md         # Chronological decision log
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Type hints, pattern matching, asyncio |
| Database | SQLite | Single-user, local, zero setup, one file |
| WHOOP | httpx + custom OAuth client | Direct API, offline refresh tokens, pagination handling |
| Spotify | Spotipy | OAuth, library access, playlist creation |
| Computations | pandas + numpy | Rolling averages, trend slopes, sleep ratios |
| Song classification | OpenAI GPT-4o-mini | Batch classification with structured outputs |
| Audio analysis | Essentia | BPM, key, mode, energy, acousticness from audio |
| Validation | Pydantic | Schema enforcement on API responses and classifications |

---

## Documentation

| Document | What it covers |
|----------|---------------|
| [RESEARCH.md](docs/RESEARCH.md) | Every study cited, methodology notes, evidence quality caveats |
| [HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Complete technical guide -- enough to rebuild from scratch |
| [SYSTEM_LOGIC.md](docs/SYSTEM_LOGIC.md) | Plain-language explanation of the full chain from wake-up to playlist |
| [PRODUCT_DECISIONS.md](docs/PRODUCT_DECISIONS.md) | What was tried, what worked, what didn't, and why |

---

## Current Numbers

- 1,360 classified songs across Bollywood, hip-hop, pop, devotional, ghazal, EDM
- 1,348 with Essentia audio analysis (99.1% coverage)
- 825 days of WHOOP recovery data
- 33,427 listening history records
- 69-tag mood affinity table informed by 12 neuroscience studies
- 0/140 weak matches across all 7 states in validation (worst neuro_match: 0.816)
- ~45% daily song turnover when the same state repeats on consecutive days
- 1,016 tests across 25 test files
