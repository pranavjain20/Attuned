# Attuned

Every WHOOP user sees their recovery score and thinks "I should do something about this." Nobody does. You can't will your nervous system into recovery. But you can press play on a playlist — and music directly modulates the autonomic nervous system, the same system WHOOP measures.

Attuned reads your morning WHOOP data — not just the recovery score, but 12 physiological signals including HRV trends, resting heart rate, sleep architecture, and accumulated debt — computes a continuous neurological profile of what your body needs right now, and builds a playlist from your own Spotify library whose acoustic properties are scientifically matched to that profile.

Not a calming sounds app. Not a mood button. Your songs, chosen by neuroscience.

```
python main.py generate
```

```
State: Baseline (leaning calmer)  |  Recovery: 44%  |  HRV: 39.4ms
Profile: Para 0.40 · Symp 0.26 · Grnd 0.34  (12 signals)
Playlist: "Mar 27 — Rest & Repair" (20 tracks)
Calming your nervous system · Bollywood · Romantic, Melancholy, Reflective
→ open.spotify.com/playlist/...
```

---

## Why This Exists

Talk to anyone who wears a WHOOP, Oura, or Garmin. They see the data, they understand it broadly, but they don't take a specific action because of it on any given day. Recovery is 42% — now what? Sleep better tonight? You were already trying. Reduce stress? Sure, but how, specifically, right now? The insight is real. The actionable step is missing. This is the universal wearable problem.

Music is the only intervention that doesn't have this friction. You were already going to listen — on your commute, at your desk, before a workout. It requires zero behavior change, zero willpower, zero extra time. And it's not a metaphor: the autonomic nervous system that WHOOP reads is the same system that music modulates. Slow tempo measurably increases parasympathetic activity. Fast tempo activates the sympathetic response. These are the same neurons, the same pathways, measured by the same metrics.

A generic calming app feels like medicine — you use it when you "should" and abandon it when you forget. Attuned uses YOUR songs, the ones you've played dozens of times, because the research is clear: familiar music triggers significantly stronger physiological responses than unfamiliar music (European Heart Journal, 2024). You're not doing a health protocol. You're listening to a playlist you genuinely want to hear. The intervention is invisible — and that's why it sticks.

---

## How It Works

### 1. Read the Body

Every morning, WHOOP calculates your recovery. Most apps stop there — one number, one bucket. Attuned reads **12 independent signals** and computes each one as a z-score against your personal 30-day baseline:

| Signal | What it tells us | Example |
|--------|-----------------|---------|
| Recovery score | Overall readiness | 44% today vs your 60% average → z = -0.56 |
| Recovery delta | How you changed from yesterday | Dropped 10pp → z = -0.33 |
| HRV (heart rate variability) | Autonomic nervous system balance | 39ms vs your 45ms baseline → z = -0.97 |
| HRV day-over-day change | Is your nervous system trending better or worse? | Declined from yesterday → z = -0.56 |
| Resting heart rate | Sympathetic stress level | 57 bpm vs your 56 average → slightly elevated |
| RHR day-over-day change | Is stress building or resolving? | Rose 2 bpm → z = -0.70 |
| Deep sleep (absolute) | Physical recovery quality | 1.3h vs your 1.5h average → z = -0.97 |
| Deep sleep (ratio to total) | Did the body prioritize deep sleep? | 1.3h in 5h night ≠ 1.3h in 9h night |
| REM sleep | Emotional processing quality | 1.7h — fine for you |
| Sleep efficiency | How well you slept vs time in bed | 92% — actually good |
| Sleep debt (7-day rolling) | Accumulated deficit | 26h — elevated |
| HRV trend (7-day slope) | Multi-day nervous system trajectory | Declining → z = -0.66 |

**Why 12 signals instead of 1?** Because a 44% recovery day where your HRV is crashing, RHR is rising, and you barely got deep sleep is fundamentally different from a 44% recovery day where your HRV is stable and you just had a short night. Same number, completely different body state, completely different playlist needed.

### 2. Compute What the Body Needs

Each z-score pushes a three-dimensional neurological profile:

- **Parasympathetic** (calming) — your nervous system needs to slow down
- **Sympathetic** (energizing) — your nervous system is ready for stimulation
- **Grounding** (emotional centering) — your mind needs stability and warmth

The push is proportional. A slightly bad day shifts the profile slightly calmer. A terrible day across all metrics shifts it strongly calming. There are no buckets, no cliffs, no thresholds where you suddenly flip from "energetic playlist" to "meditation mode." The profile moves continuously as your body state changes.

Interaction terms capture compound stress: if HRV is crashing AND resting heart rate is spiking simultaneously, that's a stronger signal than either alone — the profile gets an extra parasympathetic boost.

**Example — two consecutive days:**

| | Yesterday (54% recovery) | Today (44% recovery) |
|--|--------------------------|----------------------|
| **Profile** | Para 0.36 · Symp 0.32 · Grnd 0.33 | Para 0.40 · Symp 0.26 · Grnd 0.34 |
| **Playlist character** | Gentle romantic Bollywood | Calmer, more reflective — same genre, lower energy |
| **Why different** | HRV was stable, deep sleep was good | HRV crashed, RHR rose, deep sleep dropped |

The 10-point recovery drop produced a visible but proportional shift — not a genre flip.

### 3. Know Your Music

Every song in your Spotify library (2+ meaningful listens) is classified using two independent sources:

**LLM classification (GPT-4o-mini):** Knows what a song sounds like from its training data. Classifies BPM, energy, valence, mood tags (64-tag weighted affinity table), genre tags. Excels at cultural context — knows that Kun Faya Kun is a Sufi devotional prayer, not just a slow song.

**Audio analysis (Essentia):** Listens to the actual audio. Measures key, mode, energy (RMS), acousticness (spectral flatness) from 30-second clips. Excels at objective measurement — can't be fooled by song titles or genres.

A confidence-aware ensemble blends both sources, weighting each based on where they're known to fail. The LLM stereotypes obscure Indian music; Essentia can't measure valence or mood. Where they agree, confidence is high. Where they disagree, the more reliable source for that specific property wins.

Each song gets three neurological scores — parasympathetic, sympathetic, grounding — computed from a weighted profiler formula backed by published research (tempo 35%, energy 25%, acousticness 10%, instrumentalness 10%, valence 10%, mode 5%, danceability 5%).

### 4. Match Song to Body

Songs are scored against the target profile using **cosine similarity** — measuring directional alignment, not just magnitude. A song that points in exactly the same direction as the target (same proportional balance of calming, energizing, grounding) scores highest, regardless of how extreme its individual scores are.

The top candidates pass through a **cohesion engine** that ensures the playlist sounds coherent:
- **Genre clustering** — a playlist of all indie rock but spanning 80-130 BPM feels right; mixing K-pop, country, and metal feels broken
- **Era cohesion** — songs from different decades sound different even in the same genre. Genre-aware Gaussian decay: hip-hop clusters tight by year (σ=2), ghazal is timeless (σ=12)
- **Mood alignment** — "reflective" songs stay with "reflective," not mixed with "party"
- **BPM corridors** — no jumping from 60 BPM to 140 BPM

**Rotation:** Songs can't repeat within a minimum gap that scales with library size (log2-based). With 1,200 songs, minimum 3 days between appearances. Recently-played songs get 5 guaranteed "anchor" slots for familiarity — the rest rotate.

**Context filters:** Bollywood motivational songs (Chak De India, Dangal — tied to movie training scenes) are excluded from all playlists except peak readiness, where the pump-up context fits. English motivational (Hall of Fame, Lose Yourself) passes through — no scene-specific baggage.

### 5. Push to Spotify

A dated playlist appears in your Spotify: "Mar 27 — Rest & Repair" with a description explaining what the music is doing and why. Only one playlist per day — iterations during testing replace the previous version automatically.

---

## The Science

This isn't vibes. Every threshold, weight, and property range traces back to published research:

**Music and the autonomic nervous system:**
- 60 BPM = maximum baroreflex sensitivity, driven entirely by parasympathetic activity (Bretherton et al., 2019 — Music Perception)
- Blood pressure, heart rate, and LF:HF ratio increase proportional to tempo (Bernardi et al., 2006 — Heart)
- 60-80 BPM music inhibited sympathetic activity; 120-140 BPM increased it (Kim et al., 2024 — J Exerc Rehabil)
- Classical/acoustic music reduced cortisol, HR, and BP in controlled stress paradigm (Thoma et al., 2013 — PLOS ONE)
- Familiar music triggers significantly stronger physiological responses via the dopamine reward circuit (Chanda & Levitin, 2013 — Trends in Cognitive Sciences)

**HRV monitoring:**
- 7-day rolling LnRMSSD averages superior to single-day measurements for detecting overreaching (Plews et al., 2012 — Eur J Appl Physiol)
- CV of LnRMSSD detects non-functional overreaching before traditional markers (Buchheit, 2014 — Frontiers in Physiology)

**Sleep architecture:**
- Shifting 30 minutes from light to deep sleep improves positive affect by +0.38, independent of total duration (PMC12208346)
- Sleep quality predicts next-day positive affect with a coefficient 2.6x larger than the reverse (PMC6456824)
- 5+ hours cumulative sleep debt over 7 days produces detectable cognitive impairment; subjects are unaware (Van Dongen & Dinges, 2003 — SLEEP)

Full research analysis with methodology notes and evidence quality caveats: [docs/RESEARCH.md](docs/RESEARCH.md)

---

## What Makes This Different from a Weekend Project

A weekend project picks calming songs when recovery is low and upbeat songs when it's high. Three states, three playlists, done.

Attuned does something fundamentally different:

**Personal baselines, not population averages.** A 50% recovery with HRV at 45ms means something completely different if your 30-day average is 48ms versus 65ms. Every metric is interpreted relative to YOUR norms, computed from YOUR history.

**Continuous intelligence, not brackets.** 12 physiological signals feed a weighted function that produces a continuous profile. There are no thresholds that flip a switch. A slightly worse day produces a slightly calmer playlist. A much worse day produces a much calmer playlist. The system responds proportionally.

**Two independent classification sources.** The LLM knows cultural context (Kun Faya Kun is a Sufi prayer, not just a slow song). Essentia measures the actual audio (energy from RMS, not the LLM's guess). They cross-validate each other and a confidence-aware ensemble resolves disagreements.

**Cohesion, not just scoring.** Picking the 20 highest-scoring songs individually doesn't make a good playlist. Songs must belong in the same sonic space — same era, similar genre, compatible BPM, aligned mood. The cohesion engine ensures playlists sound intentional.

**Real rotation.** Songs can't repeat within a library-size-scaled gap. Freshness uses only the latest playlist per day (not test iterations). Recently-played anchors get guaranteed slots for familiarity; the rest rotate.

**Context awareness.** Bollywood motivational songs are excluded from non-peak playlists — they're tied to movie training scenes and evoke the wrong context for a recovery morning. This distinction is genre-aware: English motivational passes through because Western pop isn't written for specific film scenes.

**Multi-user.** Each user gets their own database, own baselines, own library, own playlists. Same algorithm, personalized to their body and their music.

---

## Current Numbers

- **5,313** classified songs across 2 users (2+ meaningful listens each)
- **4,871** with Essentia audio analysis (92% coverage)
- **1,319** days of WHOOP recovery data (combined)
- **138,569** listening history records (combined)
- **15,345** unique songs ingested from extended Spotify history
- **12** physiological z-score signals driving continuous profiles
- **64** mood tags with research-backed neurological weights
- **22** cited research papers
- **1,048** tests across 25 test files
- **2** active users with live daily playlists
- **12** days of iterative development and refinement

---

## Running Attuned

Runs locally. Requires your own WHOOP and Spotify accounts. Each user authenticates with their own credentials through OAuth — no data is shared.

```bash
python main.py generate            # Generate today's playlist
python main.py generate --dry-run  # Preview without pushing to Spotify
python main.py classify-state      # See today's physiological classification
```

New user setup: [docs/ONBOARDING.md](docs/ONBOARDING.md)

---

## Architecture

```
attuned/
├── intelligence/
│   ├── continuous_profile.py    # 12-signal weighted function → neuro profile
│   ├── baselines.py             # 30-day rolling means, SDs, CVs (LnRMSSD)
│   ├── trends.py                # 7-day HRV/RHR slopes, trajectory
│   ├── sleep_analysis.py        # Deep/REM ratios vs personal norms
│   └── state_classifier.py      # Display labels (demoted from profile driver)
├── classification/
│   ├── llm_classifier.py        # GPT-4o-mini batch classification
│   ├── essentia_analyzer.py     # Audio feature extraction from clips
│   ├── profiler.py              # Neurological impact scoring (3 dimensions)
│   └── validator.py             # Post-classification quality checks
├── matching/
│   ├── query_engine.py          # Cosine similarity scoring + rotation
│   ├── cohesion.py              # Genre-aware era decay, mood/BPM clustering
│   └── generator.py             # End-to-end pipeline orchestration
├── whoop/                       # OAuth, API client, sync
├── spotify/                     # OAuth, library sync, playlist creation
├── db/                          # SQLite schema + queries
├── tests/                       # 1,048 tests
└── docs/
    ├── RESEARCH.md              # Full research analysis with citations
    ├── SYSTEM_LOGIC.md          # How the system thinks (bridge between research and code)
    ├── PRODUCT_DECISIONS.md     # Every non-obvious decision with reasoning
    └── HOW_IT_WORKS.md          # Complete technical guide
```

## Documentation

| Document | What it covers |
|----------|---------------|
| [RESEARCH.md](docs/RESEARCH.md) | 22 studies cited, methodology notes, evidence quality caveats |
| [SYSTEM_LOGIC.md](docs/SYSTEM_LOGIC.md) | Plain-language explanation of the full chain from wake-up to playlist |
| [PRODUCT_DECISIONS.md](docs/PRODUCT_DECISIONS.md) | Every decision — what was tried, what worked, what didn't, why |
| [HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Technical guide — enough to rebuild from scratch |
| [TECH_STACK.md](docs/TECH_STACK.md) | Every technology choice with rationale and alternatives considered |
