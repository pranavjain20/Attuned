# Attuned

Attuned reads your WHOOP data every morning and builds a Spotify playlist from your own library that's matched to how you actually feel. Not your recovery score — how you *feel*.

WHOOP's recovery score measures readiness: "can I train hard today?" That's what it was built for, and HRV dominates the calculation. But most people are asking a different question: "how do I feel?" You can have a 44% recovery and feel fine because your HRV dipped but you slept well. You can have a 75% and feel terrible because your HRV rebounded but you got no deep sleep. Readiness and feeling aren't the same thing.

Attuned builds a neurological profile for the feeling question. It reads 12 independent physiological signals — HRV, resting heart rate, sleep architecture, multi-day trends, accumulated debt — and computes a continuous 3-dimensional profile of your actual state. Recovery is one of 12 inputs (~30% weight), not the whole picture. Then it matches your songs to that profile.

Two modes: a morning playlist that reads your body and selects your songs. A WhatsApp DJ that takes what you want to hear, grounds it in your body's context, and builds you a playlist by conversation.

Not a calming sounds app. Not a mood button. Your songs, chosen by neuroscience.

```
python main.py generate
```

```
Profile: Para 0.40 · Symp 0.26 · Grnd 0.34  (12 signals)
State: Baseline (leaning calmer)  |  Recovery: 44%  |  HRV: 39.4ms
Playlist: "Mar 27 — Rest & Repair" (20 tracks)
Calming your nervous system · Bollywood · Romantic, Melancholy, Reflective
→ open.spotify.com/playlist/...
```

```
WhatsApp: "something dark and moody for a late night drive"
DJ: Your recovery is 62%, HRV is stable — I can go full moody.
→ "Late Night Drive" (20 tracks) — The Weeknd, Dua Lipa, AP Dhillon
→ open.spotify.com/playlist/...
```

---

## Why This Exists

### The representation problem

WHOOP's recovery score is good at what it was designed for — measuring physical readiness, where HRV is the dominant signal. But readiness and feeling are different questions, and the recovery score can't distinguish between:

- Physical recovery deficit (low deep sleep) vs emotional processing deficit (low REM)
- Genuine recovery (HRV + sleep architecture both strong) vs misleading recovery (HRV rebounded but sleep is deteriorating)
- A one-off bad night vs accumulated fatigue across 5 days

To answer "how do I feel today?", sleep architecture matters as much as HRV, multi-day trends matter as much as today's snapshot, and the interaction between signals matters more than any single metric.

Attuned builds a representation for the feeling question: a 12-signal neurological profile where recovery is one input (~30% weight), not the whole picture. The other 70% comes from HRV, resting heart rate, sleep architecture, sleep efficiency, accumulated debt, and multi-day trends — each normalized against your personal baselines.

### The action gap

Even if you understood your body state perfectly, wearable data gives you no specific action. Recovery is 42% — now what? Sleep better tonight? You were already trying. Reduce stress? Sure, but how, specifically, right now? The insight is real. The actionable step is missing. This is the universal wearable problem.

Music is the only intervention that doesn't have this friction. You were already going to listen — on your commute, at your desk, before a workout. It requires zero behavior change, zero willpower, zero extra time. And it's not a metaphor: the autonomic nervous system that WHOOP reads is the same system that music modulates. Slow tempo measurably increases parasympathetic activity. Fast tempo activates the sympathetic response. These are the same neurons, the same pathways, measured by the same metrics.

Attuned uses YOUR songs — the ones you've played dozens of times — because the research is clear: familiar music triggers significantly stronger physiological responses than unfamiliar music (European Heart Journal, 2024). You're not doing a health protocol. You're listening to a playlist you genuinely want to hear. The intervention is invisible — and that's why it sticks.

---

## Two Modes

**Daily Playlist — your body decides.**

Every morning, Attuned reads your WHOOP data, computes your neurological profile from 12 signals, and generates a Spotify playlist from your library. Fully automatic. Songs are scored against the target profile using cosine similarity, then filtered through a cohesion engine (genre, era, mood, BPM). No input needed — your body's state drives the selection.

**WhatsApp DJ — you decide, informed by your body.**

Send a message: "walking to campus, want energy." "Dark and moody for a late night drive." "Hype me up for the gym." The LLM sees your entire classified library — every song's name, artist, genre, mood tags, energy, era — and picks 20 tracks by semantic understanding. Your WHOOP data calibrates the response: "hype me up" at 50% recovery produces a different playlist than at 85%. The DJ asks clarifying questions when the request is ambiguous. A Spotify playlist appears in your library within 30 seconds.

The distinction: daily playlists use the neuro-profile math pipeline (12 z-score signals → cosine similarity → cohesion engine). Conversational playlists use LLM-direct selection (Claude Sonnet sees the full library and picks by meaning). Both paths are live.

---

## How It Works

### 1. Read the Body

Every morning, WHOOP measures your body while you sleep — heart rate variability, resting heart rate, sleep stages (deep, REM, light, awake), respiratory rate, skin temperature. Then it compresses all of that into one number: your recovery score. Attuned starts from the raw signals.

**12 independent signals**, each computed as a z-score against your personal 30-day baseline:

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

### 2. Compute How You Actually Feel

Each z-score pushes a three-dimensional neurological profile:

- **Parasympathetic** (calming) — your nervous system needs to slow down
- **Sympathetic** (energizing) — your nervous system is ready for stimulation
- **Grounding** (emotional centering) — your mind needs stability and warmth

The push is proportional. A slightly bad day shifts the profile slightly calmer. A terrible day across all metrics shifts it strongly calming. There are no buckets, no cliffs, no thresholds where you suddenly flip from "energetic playlist" to "meditation mode." The profile moves continuously as your body state changes.

Interaction terms capture compound stress: if HRV is crashing AND resting heart rate is spiking simultaneously, that's a stronger signal than either alone — the profile gets an extra parasympathetic boost.

This is Attuned's core output — a continuous 3D representation of your neurological state that WHOOP doesn't compute. Recovery is one of 12 inputs, weighted at roughly 30%. HRV, sleep architecture, resting heart rate, and multi-day trends contribute the other 70%.

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

**Audio analysis (Essentia):** Listens to the actual audio. Essentia is the leading open-source audio analysis library, developed by the Music Technology Group at Universitat Pompeu Fabra (Barcelona) — built on the same academic foundations (spectral analysis, onset detection, MFCCs, beat tracking) as Spotify's now-deprecated audio features API. Measures key, mode, energy (onset rate), acousticness (spectral flatness), and opening energy (RMS ratio of first 15 seconds vs overall) from 60-second clips starting from the song's opening. Excels at objective measurement — can't be fooled by song titles or genres.

Spotify deprecated their audio features API in late 2024, removing the only free source of per-track audio properties. Attuned replaces it with a dual-source approach that's actually stronger: Essentia for objective audio measurement, LLM for cultural context that audio alone can't capture (mood, genre nuance, valence). Where Spotify had one proprietary source, we have two independent sources that cross-validate each other.

A confidence-aware ensemble blends both sources, weighting each based on where they're known to fail. The LLM compresses energy to the middle for non-Western music it hasn't heard (a slow Bollywood romantic and an intense anthem both get ~0.60); Essentia measures the actual audio and corrects this. Essentia can't measure valence or mood; the LLM fills that gap. Where they agree, confidence is high. Where they disagree, the more reliable source for that specific property wins.

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

A dated playlist appears in your Spotify: "Mar 27 — Rest & Repair" with a description explaining what the music is doing and why. Daily playlists replace the previous version automatically. WhatsApp playlists create fresh entries alongside the daily ones.

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

**A neurological profile, not a recovery score.** Other approaches map recovery to music: low = calm, high = energetic. Three buckets, three playlists. Attuned extracts 12 signals that WHOOP doesn't combine, computes them into a continuous 3-dimensional profile, and matches music to that profile. Recovery is one of 12 inputs, weighted at roughly 30%. It's not the driver.

**Two interfaces, one intelligence.** A daily automatic playlist when you want your body to decide. A WhatsApp DJ when you want to decide, informed by your body. Same song library, same WHOOP context, different selection engines.

**Personal baselines, not population averages.** A 50% recovery with HRV at 45ms means something completely different if your 30-day average is 48ms versus 65ms. Every metric is interpreted relative to YOUR norms, computed from YOUR history.

**Continuous intelligence, not brackets.** 12 physiological signals feed a weighted function that produces a continuous profile. There are no thresholds that flip a switch. A slightly worse day produces a slightly calmer playlist. A much worse day produces a much calmer playlist. The system responds proportionally.

**Two independent classification sources.** The LLM knows cultural context (Kun Faya Kun is a Sufi prayer, not just a slow song). Essentia measures the actual audio (energy from RMS, not the LLM's guess). They cross-validate each other and a confidence-aware ensemble resolves disagreements.

**Cohesion, not just scoring.** Picking the 20 highest-scoring songs individually doesn't make a good playlist. Songs must belong in the same sonic space — same era, similar genre, compatible BPM, aligned mood. The cohesion engine ensures playlists sound intentional.

**Real rotation.** Songs can't repeat within a library-size-scaled gap. Freshness uses only the latest playlist per day (not test iterations). Recently-played anchors get guaranteed slots for familiarity; the rest rotate.

**Context awareness.** Bollywood motivational songs are excluded from non-peak playlists — they're tied to movie training scenes and evoke the wrong context for a recovery morning. This distinction is genre-aware: English motivational passes through because Western pop isn't written for specific film scenes.

**Multi-user.** Each user gets their own database, own baselines, own library, own playlists. Same algorithm, personalized to their body and their music.

---

## What's Next

**Beyond your library.** Today, every playlist draws from your own Spotify library — songs you've listened to and we've classified. The next step: using the LLM's knowledge of all music to recommend songs you haven't heard yet but would love, taste-anchored by your library. Your familiar songs as the foundation, new discoveries woven in. Verified on Spotify before they hit the playlist.

**Automated daily generation.** Cron-scheduled playlists that appear in your Spotify every morning without running a command.

**Feedback loop.** Learning from which songs you play, skip, and seek out on your own to calibrate classifications over time.

---

## Current Numbers

- **5,313** classified songs across 3 users (2+ meaningful listens each)
- **4,871** with Essentia audio analysis (92% coverage)
- **1,319** days of WHOOP recovery data (combined)
- **138,569** listening history records (combined)
- **15,345** unique songs ingested from extended Spotify history
- **12** physiological z-score signals driving continuous profiles
- **64** mood tags with research-backed neurological weights
- **22** cited research papers
- **1,090** tests across 30 test files
- **3** active users with live daily playlists
- **WhatsApp conversational DJ** live on Twilio
- **19** days of iterative development and refinement

---

## Running Attuned

Runs locally. Requires your own WHOOP and Spotify accounts. Each user authenticates with their own credentials through OAuth — no data is shared.

```bash
python main.py generate            # Generate today's playlist
python main.py generate --dry-run  # Preview without pushing to Spotify
python main.py classify-state      # See today's physiological classification
python -m whatsapp.server          # Start WhatsApp DJ (requires Twilio + ngrok)
```

**[Get onboarded →](https://github.com/pranavjain20/Attuned-Auth)**

---

## The Framework

The representation problem Attuned solves — that a single recovery score is a lossy compression of multidimensional physiological state — is analyzed in depth in the companion research repo. Attuned proves the framework works by acting on it: if a single number can't capture how you feel, build a better representation and connect it to an intervention.

**[WHOOP 2.0 — Continuous Neurological Profile →](https://github.com/pranavjain20/whoop-2.0)**

---

## Architecture

```
attuned/
├── intelligence/
│   ├── continuous_profile.py    # 12-signal weighted function → neuro profile
│   ├── nl_song_selector.py      # LLM-direct song selection for conversational DJ
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
├── whatsapp/
│   ├── server.py                # Flask webhook for Twilio
│   └── handler.py               # Conversation state, clarification, generation
├── whoop/                       # OAuth, API client, sync
├── spotify/                     # OAuth, library sync, playlist creation
├── db/                          # SQLite schema + queries
├── tests/                       # 1,090 tests
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
