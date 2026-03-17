# Attuned — Product Document

**Version:** 2.2
**Date:** March 17, 2026
**Author:** Pranav Jain
**Status:** Planning

---

## Why This Exists

I wear a WHOOP every day. Every morning I see a recovery score — green, yellow, red. I know how my body is doing. And every morning I also reach for music. But here's the thing: those two actions are completely disconnected.

When I wake up with a 35% recovery, I don't want the same music as when I wake up at 90%. When my HRV has been dropping for four days and I barely got any deep sleep, I need something different from when I'm fully charged. I know this instinctively — I reach for calmer stuff on bad mornings, more energy on good ones. But I do it manually, scrolling through Spotify, trying to remember which songs fit this feeling. Half the time I settle for some generic playlist that isn't even mine.

Meanwhile, I have years of listening history on Spotify. Thousands of songs I've loved. Somewhere in there is the perfect calm song for a red recovery morning and the perfect banger for a green one. But that library is just a mess — no way to search by "how does this song make me feel" or "what does this song do to my body."

The science is clear that music directly affects the autonomic nervous system — the same system WHOOP measures. Slow tempo music increases HRV. Fast tempo activates your sympathetic response. Specific properties like key, energy, acousticness all have documented effects on heart rate, brainwave activity, and stress levels. This is real, published neuroscience — EEG studies, HRV studies, peer-reviewed research on how specific musical properties change brain activity and autonomic function.

So we have: data about my body (WHOOP), data about my music (Spotify), and science about how specific musical properties affect the body. No product connects all three. That's what Attuned is.

---

## What This Is

A system that reads my WHOOP recovery data every morning, understands my entire Spotify listening history as a classified library of songs with known acoustic and emotional properties, and automatically generates a playlist from songs I already love that match what my body needs today.

**This is NOT:** A generic meditation app. A "relaxation sounds" player. A mood-button playlist generator. A replacement for Spotify. It's an intelligence layer that sits between my body data and my music library.

---

## The Core Insight

Music affects your autonomic nervous system through measurable, specific properties — tempo, key, energy, acousticness, valence. These are quantifiable features that researchers have directly connected to changes in HRV, heart rate, brainwave patterns, and stress hormone levels.

WHOOP measures the exact same system — your autonomic nervous system state, through HRV, resting heart rate, sleep architecture, and recovery scoring.

The insight is that if you can classify every song in someone's personal library by the properties that affect the ANS, and you know the person's ANS state each morning from their wearable, you can make a scientifically grounded match. Not "you seem tired, here's some spa music" but "your HRV is 15% below your 30-day baseline, your deep sleep was 40% below your norm, and you're carrying 2 hours of sleep debt — here are 18 songs from YOUR library that are 60-80 BPM, acoustic, major key, and that you've listened to at least 5 times."

The personal library part matters. Research shows that personal preferred music amplifies the physiological benefits. In one large study, 74.8% of participants ranked their own music as most preferred, and the autonomic benefits of music are stronger when you actually enjoy what you're hearing. Generic "scientifically optimal" playlists don't work as well as YOUR calm songs.

---

## Two Features

### Feature 1: The WHOOP Auto-Playlist (Automatic, Every Morning)

Every morning, the system reads my WHOOP data, figures out my composite physiological state, and generates a Spotify playlist of 15-20 songs. It appears in my Spotify before I wake up. I don't touch anything — it's just there.

Each playlist is a new, dated playlist — not one standing playlist that gets overwritten. The name contains the date and detected state (e.g., "Mar 17 — Accumulated Fatigue"). The description contains a compact summary: state name, key metrics (recovery %, HRV vs baseline), and targeted properties. Spotify playlist descriptions are limited to 300 characters, so the full reasoning (all WHOOP metrics, baseline comparisons, why each song was selected) is stored in the generated_playlists database table. This turns the playlist history into a personal log — weeks later, I can scroll through my playlists and see a timeline of my physiological states and what the system did about each one.

This is the core product. It's quantitative, automatic, and runs on WHOOP data alone.

### Feature 2: The Conversational DJ (On-Demand, Any Time)

I tell it what I need in natural language: "I'm about to shower before a date," "give me something for a walk," "I'm feeling low today." It understands the context, figures out the right song properties, and generates a playlist from my library.

This is the qualitative layer. It uses the same classified music library but the trigger is my words, not my WHOOP data. It can also factor in WHOOP data as context if relevant — like suggesting I don't go too intense if my recovery is red, even if I asked for hype.

Feature 1 is what gets built first. Feature 2 comes later.

---

## The Three Data Sources

Attuned pulls from three places. Each gives us raw data, and each yields deeper intelligence when you analyze the history and cross-reference.

---

### Source 1: WHOOP — What's Going On With My Body

#### What the API Gives Us

**Recovery (calculated once each morning):**
- Recovery score (0-100%) — WHOOP's composite readiness number. Green (67-100%), Yellow (34-66%), Red (0-33%). Correlates moderately with subjective fatigue in healthy adults (r = 0.68), though most of that signal comes from HRV which we already use directly. The exact algorithm is proprietary (~65% HRV, ~20% RHR, ~15% respiratory rate, plus sleep/SpO2/skin temp). Used alongside raw metrics — particularly valuable as a sanity check and for the Peak Readiness state where it confirms raw metric signals.
- HRV (hrv_rmssd_milli) — Root mean square of successive differences between heartbeats, measured during sleep. All HRV computations use LnRMSSD (natural log of RMSSD), per Plews/Buchheit methodology. WHOOP gives raw `hrv_rmssd_milli`; we log-transform on storage. This is the gold standard for autonomic nervous system balance. Higher = parasympathetic dominant (recovered, resilient). Lower = sympathetic dominant (stressed, depleted). This is the single most important metric because it directly reflects the system that music modulates.
- Resting heart rate — Measured during deepest sleep. Lower = better recovered. Upward trends over days signal stress or illness.
- SpO2 — Blood oxygen saturation. Normally 95-100%. Drops below baseline can indicate illness or altitude.
- Skin temperature — Deviations from baseline can indicate illness onset.

**Sleep (calculated after each sleep):**
- Sleep stage breakdown in milliseconds: deep sleep (physical recovery — muscle repair, growth hormone, immune function), REM sleep (cognitive/emotional recovery — memory, emotional regulation), light sleep, awake time
- Disturbance count — How many times sleep was meaningfully disrupted
- Sleep cycle count — Typically 4-6 per night, fewer = disrupted architecture
- Sleep efficiency % — Time asleep / time in bed. Above 90% is healthy.
- Sleep performance % — How much of needed sleep you actually got. This accounts for individual variation in sleep need.
- Sleep consistency % — How regular your sleep/wake timing is
- Respiratory rate
- Sleep needed breakdown: baseline need + additional from sleep debt + additional from recent strain + offset from naps. This tells you not just if sleep was enough, but why and where the deficit comes from.

**Historical access:** The API gives paginated access to everything since I started wearing WHOOP. Months of daily data.

#### What Intelligence We Can Extract

**Personal baselines.** With the full history, we compute what "normal" means for me specifically. Need at least 14 days of data before baselines are reliable (ideally 21+ days):
- 30-day rolling average LnRMSSD — this defines MY normal. A recovery of 50% with LnRMSSD at 3.8 means something completely different if my average is 3.87 versus 4.17.
- HRV coefficient of variation (weekly CV) — Research on athlete monitoring shows the weekly variability of HRV matters as much as the absolute value. A stable week means the autonomic system is well-regulated. A high-CV week with big daily swings means instability, even if the average looks fine. Thresholds: CV >15% = elevated variability, >20% = significant instability (Buchheit 2014). Critical nuance: very low CV + low absolute HRV = bad (system is suppressed, not stable).
- Rolling averages for resting heart rate, deep sleep duration, REM duration, total sleep, sleep efficiency — each gets a personal baseline.

**Trend detection.** Single-day numbers are noisy. Multi-day trends reveal the real picture:
- HRV trend — <0.5 SD below 30-day LnRMSSD mean (Smallest Worthwhile Change) = caution (common during high-strain periods). <1.0 SD below 30-day mean, sustained 3+ days = concern (predicts illness or non-functional overreaching). 7+ consecutive days below baseline = red flag regardless of magnitude. 7-day rolling LnRMSSD averages are superior to single-day measurements (Plews 2012).
- Resting heart rate trend — +5 bpm above 30-day personal average, sustained 3+ days = caution. +7 bpm = concern. The combination of declining HRV + rising RHR is a strong composite indicator of accumulated fatigue.
- Sleep debt trajectory — >5 hours cumulative deficit over 7-day rolling window (~45 min/night shortfall) = moderate concern (cognitive impairment detectable in lab conditions). >10 hours cumulative (~1.5h/night deficit) = significant, equivalent to ~1 night of total sleep deprivation. Subjects were unaware of their impairment (Van Dongen & Dinges, 2003).

**Sleep architecture analysis.** Not just "did I sleep enough" but "what kind of sleep did I get." Normal ranges: deep sleep 15-20% of total sleep time, REM 20-25% of total.
- Deep sleep ratio vs personal norm — When this is significantly low (>1.5 SD below personal mean), physical recovery was inadequate. Body may feel heavy and fatigued regardless of the headline recovery score. 1.0 SD below = "below norm" (caution). 1.5 SD below = "significantly below" (concern). Absolute floor: <10% of total or <1 hour = significant deficit regardless of personal baseline.
- REM ratio vs personal norm — When this is low (>1.5 SD below personal mean), cognitive and emotional processing was disrupted. May feel foggy, emotionally reactive, difficulty concentrating. Absolute floor: <15% of total = significant deficit. This has specific implications for music — REM-deficient states may benefit from emotionally grounding, familiar music.
- Deep-to-REM balance — A night heavy on deep sleep but light on REM: body recovered but mind didn't process. The inverse: mind was active but body didn't restore. Different states, different music needs.

**Composite state classification.** The most useful intelligence layer. Instead of reacting to any single metric, recognize patterns across multiple signals. The classifier evaluates top-to-bottom and returns the first match:

1. **Accumulated Fatigue** — LnRMSSD <1.0 SD below 30-day mean, sustained 3+ days AND RHR rising (+5 bpm above baseline) AND sleep debt >5 hours (7-day rolling). Not just a bad morning — the body is trending downward. Music should be genuinely restorative, prioritizing parasympathetic activation.
2. **Physical Recovery Deficit** — Deep sleep >1.5 SD below personal mean AND REM adequate (within 1.0 SD of personal mean). Body needs physical restoration, mind is relatively clear. Music should be soothing to the body (slow tempo, acoustic) but can be emotionally engaging.
3. **Emotional Processing Deficit** — REM >1.5 SD below personal mean AND deep sleep adequate (within 1.0 SD of personal mean). Body is physically recovered but emotional regulation may be impaired. Music should be emotionally grounding — familiar, warm, comforting.
4. **Single Bad Night** — Today's recovery is low (LnRMSSD <0.5 SD below 30-day mean or recovery <50%) but 7-day LnRMSSD trend is stable or rising. Temporary dip from one poor night. Body's baseline is strong. Music can be moderately calming without being aggressive about it.
5. **Baseline** — Recovery adequate but not exceptional (yellow zone, 34-66%), no strong deficit signal detected by the above states. No significant HRV decline, no sleep architecture deficits exceeding 1.5 SD. Music should be varied and mood-appropriate — widest property ranges.
6. **Peak Readiness** — Green recovery (>=67%), LnRMSSD at or above 30-day average, good sleep architecture (deep and REM within 1.0 SD), low sleep debt (<3 hours). Recovery score is used here as confirmation alongside raw metrics. Autonomic system is balanced. Anything goes — high energy, fast tempo, full intensity.

**Day-of-week patterns (deferred — post-sprint).** With months of data, detect personal rhythms. If Monday recovery is consistently 15% lower than Thursday, the system learns that 50% on Monday is "a normal Monday" and doesn't overreact. Requires months of data + statistical testing.

---

### Source 2: Spotify — My Music Library

#### What the API Gives Us

- **Saved/liked songs** — Every track I've explicitly saved. Track name, artist, album, Spotify URI.
- **Recently played** (deferred for v1 — extended history provides 6 years of data, making 50-track recent polling unnecessary).
- **Extended streaming history** — Arrived Mar 16, 2026 (requested Mar 15). Contains 33,427 records spanning Feb 2020 – Mar 2026, with 5,701 unique tracks. Spotify URIs already included in the data — no search API resolution needed. Rich behavioral fields: ms_played, reason_start (clickrow, fwdbtn, trackdone, etc.), reason_end, skipped, shuffle, platform. 58% of plays are <=30s (skips/noise) — filter to >30s for meaningful engagement. 679 tracks have 5+ meaningful listens (>30s), 366 have 10+.
- **Top items** — Most-played tracks and artists across short-term (~4 weeks), medium-term (~6 months), and long-term (years).
- **Playlists** — Every playlist I've created or follow, including track listings.
- **Playlist creation/modification** — Can create playlists, add/remove/replace tracks, set descriptions. This is how the system delivers the output.

**v1 song sources:** Extended streaming history (primary — 679+ tracks with 5+ meaningful listens) + liked songs + top tracks (3 time windows: short/medium/long term, supplementary engagement signals). Top artist tracks are deferred because they add globally popular songs the user may never have heard, violating the personal library principle.

#### What Intelligence We Can Extract

**The repository.** At the most basic level, Spotify provides every song I can recommend from. The fundamental rule: every recommendation comes from music I've already listened to and presumably liked.

**Genuine preference signals (v1: engagement scoring from extended history).** Not all songs in the history are equal:
- Play count — Songs played dozens of times over years have deep personal significance. Played once = exploratory or incidental. Filtered to meaningful listens (>30s) to exclude skips and noise.
- Completion rate (ms played / track duration) — Songs listened to in full = genuine preference. Songs skipped at 5 seconds = noise.
- Active vs. passive — Songs I actively chose (reason_start = clickrow) carry stronger signal than autoplay (reason_start = fwdbtn, trackdone).
- Skip rate — Tracks where reason_end = fwdbtn or skipped = true indicate weaker preference.
- Recency — First and last played dates, with more weight toward songs still in rotation.
- Composite engagement score — Weighted combination of all signals above, computed per song:

```
engagement_score = (
    log_normalized_play_count  * 0.35 +
    completion_rate            * 0.25 +
    active_play_rate           * 0.20 +
    (1.0 - skip_rate)          * 0.10 +
    recency_score              * 0.10
)
```

Where:
- **play_count:** Log-normalized — `log(play_count + 1) / log(max_play_count + 1)`. Prevents a song with 200 plays from dominating.
- **completion_rate:** Average ms_played / track_duration (0.0-1.0).
- **active_play_rate:** Proportion of plays where reason_start = clickrow.
- **skip_rate:** Proportion of plays where reason_end = fwdbtn or skipped = true. Inverted: lower skip = higher score.
- **recency_score:** Days since last played, normalized with decay — more recent = higher.

The system uses these signals to weight recommendations toward genuinely loved music. This replaces the originally planned source-based scoring (liked +3, top track +2) with real behavioral data.

**Temporal listening patterns (deferred — data available, not quality-blocking for v1).** When I listen to a song matters:
- Time-of-day patterns — A song consistently played between 6-8 AM has a different role than one played at midnight. The system can learn "morning songs" and "night songs" for me specifically.
- Sequential patterns — Songs I often play back-to-back have an implicit relationship that informs playlist sequencing.

**Historical correlation with WHOOP data (deferred — data available, not quality-blocking for v1).** For the overlap period where both datasets exist, the system can discover things neither reveals alone:
- Did certain music before bed correlate with better sleep metrics?
- On low-recovery mornings, what did I naturally gravitate toward? My unconscious choices may reveal what my body instinctively seeks.
- Did morning music on good recovery days differ systematically from bad recovery days?

This is retrospective analysis that runs once on the full history to find patterns I don't consciously know about.

**Taste profiling (deferred — data available, not quality-blocking for v1).** Over time, build a picture of my musical identity — genres, artists, language preferences, tempo preferences, emotional range. This ensures recommendations never feel alien even when they're scientifically optimal.

---

### Source 3: Song Properties — What Music Does to the Body

#### What Properties Matter and Why

Every song has measurable acoustic properties that determine how it interacts with the autonomic nervous system. This is grounded in published neuroscience research.

**Tempo (BPM)** — The single most powerful property. Research using EEG shows emotional valence increases with tempo, and Beta/Gamma brainwave power rises with faster tempos (more neural activation). Slow tempo (60-80 BPM) promotes parasympathetic response — calms the nervous system, increases HRV. Fast tempo (120+ BPM) activates sympathetic response — increases arousal, heart rate, alertness. Slow tempo promotes synchronization between occipital and parietal brain regions (emotional stability). Fast tempo enhances frontal-parietal synchronization (alertness, engagement).

**Key and Mode (Major vs. Minor)** — Major keys = bright, happy, positive. Minor keys = sad, reflective, introspective. One of the most robust findings in music psychology, replicated across cultures and training levels.

**Energy (0.0-1.0)** — Composite of loudness, dynamic range, spectral density, onset rate. High energy = fast, loud, intense. Low energy = quiet, sparse, gentle. Correlates with sympathetic activation.

**Valence (0.0-1.0)** — Emotional positiveness. Independent of energy. A song can be high energy + low valence (angry metal) or low energy + high valence (peaceful contentment). Valence directly influences the ANS — positive music activates reward circuits, negative music activates stress circuits.

**Acousticness (0.0-1.0)** — Acoustic instruments (piano, guitar, strings) tend to activate parasympathetic response more than electronic/synthesized sounds. Probably related to the brain's evolved response to natural vs. artificial sounds.

**Danceability (0.0-1.0)** — Rhythm regularity, beat strength, tempo stability. Regular predictable rhythms give the brain a sense of control.

**Instrumentalness (0.0-1.0)** — Likelihood of no vocals. Instrumental music is more effective for parasympathetic activation because lyrics add cognitive load. Especially important for recovery states where the goal is to reduce mental processing demands.

**Loudness and Dynamic Range** — Compressed loud music (modern pop, EDM) maintains arousal. Dynamic music (classical, jazz) engages attention differently.

**Vocal Presence** — Instrumental music has a more positive effect on cognitive tasks than music with lyrics, because lyrics add cognitive load. For recovery states, instrumental or foreign-language vocals may be more effective.

#### How to Extract These Properties

**Essentia (open-source audio analysis):** An open-source C++ library with Python bindings from the Music Technology Group at Universitat Pompeu Fabra. Can extract BPM, key, mode, energy, loudness, danceability, spectral characteristics, and through TensorFlow models — mood classification (happy/sad/aggressive/relaxed), genre, voice/instrumental detection. Requires actual audio files as input. Even 30-second clips give accurate results.

**LLM classification (GPT-4o-mini):** Large language models classify songs from memorized training data, not audio analysis. Accuracy varies significantly by property and song popularity:
- BPM: 85-90% within +/-5 BPM for popular songs, 30-40% for obscure
- Key/Mode: 80-85% for popular, 20-30% for obscure
- Energy/Danceability: 70-80% for popular, genre-correlated
- Valence: Hardest — 60-70% for popular, 40-50% for obscure (models cluster around 0.5 when uncertain)
- Genre/Mood tags: 85-90% for popular (LLM's strongest suit)

Batch size: 5 songs per request (quality drops significantly above 10). All properties use 0.0-1.0 scale, BPM as exact integer. Each song gets a `confidence` field ("high"/"medium"/"low") — the prompt explicitly tells the model it can say "I don't know" to prevent fabrication. Uses Structured Outputs with `strict: true` for guaranteed valid JSON, plus Pydantic validation for 0.0-1.0 range clamping. Reference anchors in the prompt calibrate the scale (e.g., "Energy 1.0 = 'Killing in the Name' by RATM. Energy 0.1 = 'Clair de Lune'").

Known biases: popularity bias (well-known songs get accurate data, obscure get fabrications), genre stereotyping (metal/rock more accurate than rap, world music), Western music bias (English-language pop/rock better than other traditions), mid-range valence clustering (defaults to ~0.5 when uncertain).

**Recommended approach — phased by library size:**

LLM classification comes first. With under 500 songs, the accuracy is good enough — the matching engine doesn't have a large enough pool to benefit from fine-grained precision anyway. LLM classification is immediate, costs under $1, and requires no audio files. This is what we use from day one.

Essentia comes later, when the extended streaming history arrives and the library grows past 500+ songs. At that point, the matching engine has enough songs to make fine-grained distinctions, and the difference between "the LLM says around 80 BPM" and "Essentia measured 82 BPM" starts affecting playlist quality at the boundaries. Essentia runs on 30-second audio clips sourced via yt-dlp, analyzing the top songs by play count first.

Calibration happens after both exist: compare LLM estimates against Essentia ground truth, identify systematic biases (e.g., LLM overestimates BPM for Bollywood songs), and apply corrections across the library. New songs get LLM classification immediately and Essentia analysis in batches.

#### What Intelligence We Can Extract

**Neurological impact profile for every song.** Based on the research, score what each song does to the ANS using weighted properties:

| Property | Weight | Rationale |
|---|---|---|
| Tempo (BPM) | 0.35 | Strongest single ANS predictor (Bretherton 2019, Bernardi 2006, Kim 2024) |
| Energy | 0.25 | Strong arousal predictor, highly correlated with sympathetic activation |
| Acousticness | 0.10 | Moderate relaxation context predictor (Thoma 2013, Scarratt 2023) |
| Instrumentalness | 0.10 | Reduces cognitive load, supports relaxation (BMC Psych 2023) |
| Valence | 0.10 | Weaker than arousal for physiology, but important for subjective experience |
| Mode (major/minor) | 0.05 | Detectable but small physiological effect (Khalfa 2002, Zhang 2024) |
| Danceability | 0.05 | Rhythm regularity, sense of control |

Three computed scores per song:
- Parasympathetic activation potential — slow tempo, acoustic, major key, moderate energy, positive valence. These increase HRV and promote recovery.
- Sympathetic activation potential — fast tempo, high energy, strong beat. These increase arousal and alertness.
- Emotional grounding potential — high familiarity, moderate tempo, warm timbre. These support emotional regulation.

**Scoring approach:** Parasympathetic and sympathetic scores use sigmoid functions for tempo and energy (modeling monotonic relationships — slower is calmer, faster is more activating). The grounding score uses Gaussian (true peak at ~75 BPM). See docs/RESEARCH.md Section 7 for full formulas.

**Matching specificity.** Not "calm song for bad recovery" but "60-80 BPM, major key, acousticness > 0.7, valence > 0.6, from liked songs or frequent top tracks." Precise multi-dimensional matching.

**Playlist sequencing — the iso principle.** From music therapy: start close to the listener's current state and gradually transition toward the desired state. Research-backed algorithm:
- First 1-2 songs: match current state within +/- 5 BPM and +/- 0.1 energy
- Each subsequent song: shift 10-15 BPM and 0.1-0.15 energy toward target
- Minimum 3 transition songs (Saarikallio 2021: 2 is too abrupt)
- 8-10 songs for a full mood journey (clinical practice guideline)
- Total playlist duration: 15-30 minutes

**Starting profiles by state** (where the listener probably is upon waking):

| State | Starting BPM | Starting Energy | Rationale |
|---|---|---|---|
| Accumulated Fatigue | 80 | 0.35 | Fatigued but awake, normal morning arousal |
| Physical Recovery Deficit | 80 | 0.35 | Body tired, mind normal |
| Emotional Processing Deficit | 80 | 0.40 | Body fine, mind foggy |
| Single Bad Night | 85 | 0.40 | Slightly off but baseline is strong |
| Baseline | 85 | 0.45 | Normal morning |
| Peak Readiness | 80 | 0.40 | Just woke up — start moderate, build up |

**Behavioral calibration.** Once the system is running, play/skip behavior on generated playlists feeds back. If a song classified as "calm" keeps getting skipped on low-recovery mornings, it's not calm for me. The system learns from usage.

---

## Technical Decisions

- **Language:** Python. Every tool in this project has a Python library — Spotipy for Spotify, httpx for WHOOP, Essentia for audio analysis, pandas/numpy for computations, OpenAI SDK for classification. Claude Code is excellent at Python.
- **Spotify integration:** Spotipy. Standard Python library for the Spotify Web API. Handles OAuth token refresh, pagination, rate limiting out of the box.
- **WHOOP integration:** Custom thin client with httpx. Registered app, OAuth 2.0, direct API calls. ~100-150 lines. Full control, no dependency on unofficial library.
- **Database:** SQLite. Single-user system on a laptop — zero setup, one file, Python has it built in. More than fast enough for the data volume here (tens of thousands of rows max). Migrate to Postgres later if this ever needs to support multiple users.
- **Intelligence computations:** Plain Python + pandas + numpy. Rolling averages, trend slopes, ratio calculations — this is tabular math, and pandas is built for it. No pipeline frameworks, no workflow tools, just functions that take DataFrames and return results.
- **Song classification:** OpenAI GPT-4o-mini first (have $5 in existing credits). Batch size of 5 songs per call, 0.0-1.0 scale for all properties, confidence field per song. Structured Outputs with `strict: true` for guaranteed valid JSON, Pydantic validation for range clamping. Switch to Anthropic API (Claude Sonnet) when credits run out — provider-agnostic wrapper makes switching a config change, not a rewrite.
- **Playlist trigger:** Manual trigger first (run a command, get a playlist). WHOOP webhooks later for automatic morning generation.
- **Audio analysis:** LLM classification only while library is under 500 songs. Essentia for precision after extended streaming history arrives and library grows.

---

## What Needs to Be Built — Full Superset

Everything the complete system needs. Not all built at once — phasing comes next. But this is the comprehensive list.

### Data Layer
- WHOOP API integration (OAuth 2.0, token management, data retrieval)
- Spotify API integration (OAuth 2.0, token management, library access, playlist creation)
- Extended streaming history ingestion (parse exported JSON — arrived Mar 16, 33K records, URIs included)
- Song metadata database (every unique song with features, classifications, and engagement scores)
- WHOOP history database (every recovery, sleep, cycle, workout)
- Listening history database (every play event with timestamp and engagement data)
- Personal baseline store (rolling averages, trends, norms)

### Intelligence Layer
- Personal baseline computation (rolling averages, standard deviations, CVs)
- Trend detection (7-day slopes for HRV, RHR, sleep metrics)
- Sleep architecture analyzer (deep/REM/light ratios vs personal norms)
- Sleep debt trajectory tracker (multi-day accumulation/resolution)
- Composite state classifier (combining multiple signals into six state assessments)
- Day-of-week pattern detector (deferred — post-sprint)
- Song classification pipeline — LLM (broad coverage)
- Song audio analysis pipeline — Essentia (precision)
- Neurological impact profiler (song properties → expected ANS effects)
- Engagement score calculator (v1: play count, completion rate, active/passive, skip rate from extended history)
- Temporal listening pattern analyzer (deferred — data available, not quality-blocking for v1)
- Historical WHOOP-Spotify correlation engine (deferred — data available, not quality-blocking for v1)
- Taste profiler (deferred — data available, not quality-blocking for v1)

### Matching Layer
- State-to-properties mapper (composite state → target song property ranges)
- Library query engine (find matching songs from classified library)
- Preference-weighted selection (prioritize high-engagement songs)
- Variety and freshness logic (don't repeat the same 15 songs daily)
- Playlist sequencing engine (order songs for optimal transitions)
- Feedback integration (learn from play/skip on generated playlists)

### Output Layer
- Spotify playlist creator/updater
- Playlist description generator (compact 300-char summary for Spotify, full reasoning in database)
- Manual trigger (v1) — run a command or hit a button, playlist generates immediately. This is what we build first. No infrastructure needed, no timing issues, just works when you trigger it.
- WHOOP webhook trigger (v2) — WHOOP fires a webhook when recovery is calculated (i.e., when you wake up). The system receives it, pulls data, runs matching, creates playlist. By the time you open Spotify, it's there. Requires a publicly accessible URL (ngrok for local dev, or a small cloud server for production). Added after the core system works.
- Conversational interface (natural language → playlist, Feature 2)
- Web UI (simple interface for mood input and playlist viewing)

---

## Phasing

Seven building days. Each phase ends with something testable — you can verify it works before moving on. No building on debt.

### Day 1: Project Setup + Extended History Ingestion + First API Pulls

This is the root of everything. If the data is wrong, every layer on top is broken.

Create config.py with all constants and thresholds. Design and create the SQLite schema (8 tables including tokens table for OAuth storage — songs table includes engagement columns, listening_history includes extended history fields). Parse extended streaming history JSON (33K records). Filter to records with spotify_track_uri only. URIs are already in the data — no Spotify search API resolution needed. Register apps on both developer dashboards. Get WHOOP OAuth working — authenticate, pull today's recovery and sleep data, confirm real numbers come back. Get Spotify OAuth working — authenticate, pull liked songs, pull top tracks across all three time windows (short/medium/long term). These are now supplementary engagement signals, not the primary song pool. Fetch track metadata from Spotify API batch endpoint (up to 50 tracks per request) for duration_ms — needed for completion rate calculation in engagement scoring. Deduplicate: merge all sources into songs table. Each unique song appears once with sources JSON list.

**Testable:** DB populated with listening history, songs table with ~5,700 tracks, WHOOP today's data, integrity checks pass.

### Day 2: Engagement Scoring + Full WHOOP History + Data Integrity

Compute per-song engagement scores from listening_history: play_count (meaningful listens >30s), completion_rate, active_play_rate (clickrow vs fwdbtn), skip_rate, first/last played, recency. Composite engagement_score (weighted combination). Paginate through entire WHOOP recovery and sleep history — every record since I started wearing it. Store with LnRMSSD computed on ingestion. Run data integrity verification: row counts, date ranges, gap detection, engagement score distribution, spot-check known songs.

**Testable:** Every song has engagement score, full WHOOP history in DB, "top 20 songs by engagement" looks right.

**What Days 1-2 deliver:** All data sitting in a local database — every recovery score, every sleep session, every song with real engagement scores from 6 years of listening data. No intelligence yet, just clean verified data with behavioral signals.

**Constraint driving these days:** Nothing else can be built without data access. Classification needs songs. Baselines need WHOOP history. Engagement scoring needs listening history. Playlists need all three.

### Day 3: WHOOP Personal Intelligence

Compute personal baselines: 30-day rolling LnRMSSD average, RHR average, typical deep sleep and REM durations with standard deviations. Compute 7-day LnRMSSD rolling average and HRV CV. Compute RHR trend. Compute sleep debt trajectory (7-day rolling cumulative deficit). Compute deep sleep and REM ratios per night plus personal averages. Build the composite state classifier — takes today's data + baselines + trends, outputs one of six states with a human-readable explanation. Uses concrete research-backed thresholds: LnRMSSD <1.0 SD below 30-day mean for fatigue, >1.5 SD for sleep stage deficits, >5 hours for sleep debt.

**Testable:** Classify state for any historical date, verify against known good/bad days.

### Day 4: LLM Song Classification (679 songs)

Build the LLM classification pipeline. Design the prompt for batches of 5 songs, returning structured JSON with BPM (exact integer), key, mode, energy, valence, acousticness, danceability, instrumentalness (all 0.0-1.0), plus mood_tags, genre_tags, and confidence ("high"/"medium"/"low"). Use Structured Outputs with `strict: true` for guaranteed valid JSON, Pydantic validation for 0.0-1.0 range clamping. Classify tier 1: 366 songs with 10+ meaningful listens (~74 calls). Classify tier 2: 313 songs with 5-9 meaningful listens (~63 calls). Total: ~136 calls, ~$0.68, well within budget. Build the neurological impact profiler — scores each song's parasympathetic activation potential, sympathetic activation potential, and emotional grounding potential based on its classified properties using the research-backed weight table.

**Testable:** 679 songs classified, top parasympathetic songs are slow/acoustic/calm, cost <$1.

**What Days 3-4 deliver:** The WHOOP side knows my six states with personal context. The music side has 679 songs classified with properties that map to neuroscience research. Both halves of the brain exist independently.

**Constraint driving these days:** The matching engine (Day 5) needs both a detected state and classified songs to work.

### Day 5: Matching Engine (engagement-weighted)

Build the state-to-properties mapper — for each of the six states, define target song property ranges grounded in the research (e.g., Accumulated Fatigue → 50-70 BPM, energy ≤ 0.3, acousticness ≥ 0.7). Build the library query that finds matching songs. Add engagement-weighted selection: selection_weight = property_match_score (0.60) + engagement_score (0.30) + variety_factor (0.10). This replaces the old source-based scoring (liked +3, top track +2) with real behavioral data. Add recency penalty for variety: -50% weight if played in yesterday's playlist, -25% if 2 days ago.

**Property match score:** For each of the seven properties, compute how well the song fits the state's target range:
- Inside range: score based on proximity to range center (1.0 at center, 0.7 at edges)
- Outside range: score decays with distance from nearest edge (sigmoid decay)

Weight each property (tempo 0.35, energy 0.25, acousticness 0.10, instrumentalness 0.10, valence 0.10, mode 0.05, danceability 0.05). Sum to get property_match_score (0.0-1.0).

Note: The neurological scores (parasympathetic/sympathetic/grounding) are used for playlist description and logging, NOT for selection. Selection uses per-property range matching.

**Confidence multiplier in matching:** The LLM confidence field feeds into the property match score — high: 1.0x, medium: 0.8x, low: 0.5x. Songs classified with low confidence have their property match score halved, making them less likely to be selected when strict matching matters.

Progressive filter relaxation when too few songs match:
- Step 1: Widen BPM range
- Step 2: Lower acousticness threshold
- Step 3: Widen energy range
- Step 4: Relax instrumentalness and valence constraints
- Step 5 (terminal fallback): Drop all property constraints, select purely by engagement score. Log warning: "Insufficient library coverage for [state] — playlist selected by engagement only"

**Testable:** For each of 6 states, selected songs make intuitive sense and high-engagement songs appear more.

### Day 6: Playlist Creation + End-to-End Flow

Build the Spotify playlist creator — creates a playlist with selected songs. Build the description generator — compact 300-char summary for Spotify (state name, key metrics, target properties), full reasoning stored in database. Wire the full pipeline: manual trigger → pull WHOOP → classify state → match songs → create playlist. Run it end to end and see a real playlist appear in Spotify.

**Testable:** Real Spotify playlist appears with correct name, description, and songs.

**What Days 5-6 deliver:** The MVP. Trigger the system, it reads WHOOP, classifies my state, selects engagement-weighted songs, and a real Spotify playlist appears with a description explaining why those songs were chosen.

### Day 7: Sequencing + Polish + Hardening

Build playlist sequencing — order songs using the iso principle: first 1-2 songs match detected state (+/- 5 BPM, +/- 0.1 energy), each subsequent song shifts 10-15 BPM and 0.1-0.15 energy toward target, minimum 3 transition songs, 8-10 songs for full mood journey. Test across all six states, verify playlists feel subjectively right. Fix rough edges. Run the full pipeline multiple times across different historical dates to verify consistency. Edge cases, polish, full test suite green.

**Testable:** Sequenced playlists for all 6 states sound right when played.

**What this delivers:** A polished, reliable system that generates well-sequenced playlists consistently across all six states. Ready for daily use.

### Beyond Sprint

- **Temporal listening patterns:** Data available from extended history (time-of-day, sequential patterns). Interesting but matching engine already uses acoustic properties — not quality-blocking for v1.
- **WHOOP-Spotify correlation:** Retrospective analysis across the overlap period. Not needed for core pipeline.
- **Taste profiling:** Data available but all recs already come from user's own library — deferred.
- **Recently played polling:** Unnecessary with 6 years of extended history.
- **Top artist track expansion:** Unnecessary with actual listening behavior data — 679 tracks is a healthy pool.
- **Day-of-week pattern detection:** Requires months of WHOOP data + statistical testing to detect significant personal rhythms.
- **Essentia audio analysis:** With 679+ songs in the pool, Essentia precision becomes valuable. Run on top tracks for precise BPM, key, energy. Calibrate LLM estimates.
- **WHOOP webhook automation:** System generates playlist automatically when recovery is calculated each morning.
- **Conversational DJ (Feature 2):** Natural language interface for on-demand playlists.
- **Behavioral feedback loop:** Learn from play/skip behavior on generated playlists to calibrate classifications over time.
- **Multi-user note:** The current design relies on Spotify's extended streaming history export (requested via privacy settings, delivered in ~days). A multi-user version would need to work with Spotify's API-only data (liked songs, top tracks, recently played — no extended history). This represents a significantly smaller and less rich song pool. The engagement scoring formula would need to be adapted for API-only signals (no ms_played, no reason_start/reason_end, no skip data). This is out of scope for v1 but worth noting as an architectural constraint.

---

## Research That Backs This Up

Full research analysis with design implications: see docs/RESEARCH.md

1. **Music and HRV:** Music induces physiological responses that increase HRV. Classical music showed significantly higher HRV response than electronic music. Personal preferred music ranked most preferred by 74.8% of participants. (European Heart Journal, 2024)

2. **Music and ANS:** Music acts on the cardiac autonomic nervous system, increasing parasympathetic activity and HRV. Slow-tempo music activates parasympathetic response. (Complementary Therapies in Clinical Practice, 2020)

3. **Tempo and Brain Activity:** Emotional valence increases with tempo. Fast tempo increases Beta/Gamma brainwave power. Slow tempo promotes occipital-parietal synchronization → emotional stability and relaxation. (Scientific Reports, 2025)

4. **Music and Autonomic Nervous System:** Music valence influences the ANS. Music activates nearly all brain regions including hippocampus, amygdala, limbic system. (Harvard Medicine Magazine, 2025)

5. **Musical Cues and Emotion:** Most potent cues: mode, tempo, dynamics, articulation, timbre, phrasing. (Frontiers in Computational Neuroscience, 2016)

6. **Lyrics and Cognitive Load:** Instrumental music more beneficial for cognitive tasks than music with lyrics due to cognitive load. (Journal of Cultural Cognitive Science, 2024)

7. **Sleep Deprivation and HRV:** Sleep deprivation significantly decreases RMSSD and increases LF/HF ratio — sympathetic dominance. (Frontiers in Neurology, 2025)

8. **HRV and Wellbeing:** Higher morning RMSSD associated with better sleep quality, lower fatigue, reduced stress. (MDPI Sensors, 2025)

9. **HRV Monitoring Best Practices:** Near-daily HRV with weekly averages and CV superior to isolated measurements for detecting adaptation and recovery. (MDPI Sensors, 2025)

10. **Pre-sleep HRV and Sleep Quality:** Higher parasympathetic activity associated with sleep onset and deeper sleep. Music-based relaxation modulating HRV improves sleep quality. (Frontiers in Physiology, 2025)

11. **Baroreflex Sensitivity and Tempo:** BRS significantly greater at 60 BPM than at 120 or 180 BPM, driven entirely by parasympathetic activity. (Bretherton et al., 2019 — Music Perception)

12. **Cardiovascular Response to Tempo:** Blood pressure, heart rate, and LF:HF ratio increased proportional to tempo. Pauses afterward decreased all measures. (Bernardi et al., 2006 — Heart)

13. **Neurochemistry of Music:** Familiar music triggers stronger dopamine release via the reward circuit. Music activates the same endorphin pathways as food and social bonding. (Chanda & Levitin, 2013 — Trends in Cognitive Sciences)

14. **Oxytocin/Cortisol and Tempo:** Slow-tempo music increased oxytocin and parasympathetic markers. Fast-tempo decreased cortisol and increased sympathetic markers. (Ooishi et al., 2017 — PLOS ONE)

15. **Music Tempo and Sympathetic Inhibition:** 60-80 BPM music inhibited sympathetic activity, decreasing LFR and increasing HFR. (Kim et al., 2024 — J Exerc Rehabil)

16. **HRV Monitoring in Athletes:** 7-day rolling LnRMSSD averages superior to single-day measurements. CV of LnRMSSD detects non-functional overreaching. (Plews et al., 2012 — Eur J Appl Physiol)

17. **HRV CV Thresholds:** Day-to-day variations in training load entail CV = 10-20% for LnRMSSD. CV >15% = elevated, >20% = unstable. (Buchheit, 2014 — Frontiers in Physiology)

18. **Cumulative Sleep Debt:** >5 hours over 7 days causes detectable cognitive impairment. >10 hours equivalent to total sleep deprivation. Subjects unaware of impairment. (Van Dongen & Dinges, 2003 — SLEEP)

19. **Iso Principle — Clinical Definition:** Match music to current state, then gradually shift toward desired state. Clinically validated in music therapy. (Heiderscheit & Madson, 2015 — Augsburg University)

20. **Transition Requires 3+ Songs:** Using only 2 songs created too-abrupt shifts. 3-5+ songs required for effective gradual transition. (Saarikallio et al., 2021 — IJERPH)

21. **LLM Music Annotation:** LLMs can annotate musical properties from memorized training data. Accuracy varies by property and song popularity. (Yang et al., 2025 — arXiv)

22. **WHOOP Accuracy:** Recovery correlated with subjective fatigue at r = 0.68 in healthy adults, weaker in clinical populations. Raw metrics more reliable than composite scores. (medRxiv, 2024 — Systematic Review)

---

## Technical Appendix

### Stack

- Python 3.11+
- SQLite
- Spotipy (Spotify), httpx (WHOOP custom client), pandas + numpy (computations), Pydantic (validation)
- OpenAI GPT-4o-mini for song classification (switch to Anthropic Claude Sonnet when credits run out)
- Essentia for audio analysis (later, when library exceeds 500 songs)

### Project Structure

```
attuned/
├── main.py
├── config.py
├── .env
├── requirements.txt
├── db/
│   ├── schema.py
│   └── queries.py
├── whoop/
│   ├── auth.py
│   ├── client.py
│   └── sync.py
├── spotify/
│   ├── auth.py
│   ├── client.py
│   ├── playlist.py
│   └── sync.py
├── intelligence/
│   ├── baselines.py
│   ├── trends.py
│   ├── sleep_analysis.py
│   └── state_classifier.py
├── classification/
│   ├── llm_classifier.py
│   └── profiler.py
├── matching/
│   ├── state_mapper.py
│   ├── query_engine.py
│   ├── sequencer.py
│   └── generator.py
└── tests/
```

### Database Tables

- **songs** — Every unique song. Key: spotify_uri. Contains track name, artist, album, duration_ms (from Spotify track metadata API — batch endpoint, up to 50 tracks per request), sources (JSON list, e.g. `["liked", "top_track", "extended_history"]`), and engagement columns: play_count (meaningful listens >30s), completion_rate, active_play_rate, skip_rate, engagement_score (composite), first_played, last_played.
- **whoop_recovery** — One row per day. Key: cycle_id. Contains date (DATE — derived from cycle end time in user's local timezone), recovery_score, hrv_rmssd_milli, ln_rmssd (REAL — natural log of hrv_rmssd_milli, computed on storage), resting_heart_rate, spo2, skin_temp.
- **whoop_sleep** — One row per sleep session. Contains date (DATE — derived from sleep end time in user's local timezone), recovery_cycle_id (FK to whoop_recovery.cycle_id — links sleep to its recovery day), plus all stage durations in ms (deep, REM, light, awake), sleep quality metrics (efficiency, performance, consistency, respiratory rate, disturbance count, cycle count), and sleep_needed breakdown (baseline, debt, strain, nap offset).
- **listening_history** — Every play event. Contains spotify_uri, played_at timestamp, ms_played, reason_start, reason_end, skipped, shuffle, platform. Unique on (spotify_uri, played_at).
- **song_classifications** — One row per song. Contains LLM-derived properties (bpm, key, mode, energy, valence, acousticness, danceability, instrumentalness — all 0.0-1.0 — plus mood_tags, genre_tags, confidence) and computed neurological scores (parasympathetic, sympathetic, grounding). Also stores classification source and raw response.
- **generated_playlists** — Log of every playlist created. Contains spotify_playlist_id, date, detected state, reasoning, all WHOOP metrics at time of generation, track_uris (JSON array of spotify URIs), and the description written to Spotify.
- **tokens** — OAuth token storage. Contains provider (whoop/spotify), access_token, refresh_token, expires_at.

### Indexes

- `songs.engagement_score` — for engagement-weighted selection
- `song_classifications.bpm` — for BPM range queries in matching
- `song_classifications.energy` — for energy range queries in matching

### Key Constraints Claude Code Should Know

- **Library size:** 679 tracks with 5+ meaningful listens (>30s), 366 with 10+. Total unique tracks from extended history: ~5,700. The matching engine classifies and selects from the 679-track engaged pool. If fewer than 15 songs match a state's criteria, progressively relax filters (widen BPM range, lower acousticness threshold, etc.) until enough songs qualify. Log when relaxation happens.
- **Classification pool boundary:** All 679 songs with 5+ meaningful listens are classified and eligible for playlist selection. Liked songs or top tracks that fall outside this pool (fewer than 5 meaningful listens) are included in the songs table for tracking but are NOT classified and NOT eligible for playlist selection in v1.
- **Extended streaming history:** Already contains spotify_track_uri — no search API resolution needed. 58% of plays are <=30s (skips/noise) — filter to >30s for meaningful engagement scoring.
- **WHOOP recovery score complements raw metrics** — the state classifier primarily uses raw HRV, RHR, and sleep stages (which allow distinguishing between specific deficit types), with recovery score as a confirmatory signal and sanity check.
- **Need 14+ days of WHOOP data** before personal baselines are reliable. Use rolling 30-day window for computation.
- **WHOOP OAuth scopes needed:** read:recovery, read:cycles, read:sleep, read:profile, read:body_measurement, offline
- **Spotify OAuth scopes needed:** user-library-read, user-read-recently-played, user-top-read, playlist-modify-private, user-read-private
- WHOOP API paginates at 25 records per page using nextToken
- WHOOP timestamps are ISO 8601 with timezone offsets — need careful date derivation
- **Cycle-to-date mapping:** Each calendar day's data uses the primary sleep cycle (longest duration). Date is derived from the cycle end time in the user's local timezone. If multiple sleep cycles exist for one day (e.g., a nap), the primary (longest) cycle is used for baselines and state classification.
- WHOOP access tokens expire after 1 hour — must request the `offline` scope to get a refresh token
- Spotify playlist descriptions have a 300 character limit
- Spotify audio features and recommendations endpoints are deprecated for new apps — do not attempt to use them
- **LLM classification:** Batch 5 songs per call for optimal accuracy. 679 songs = ~136 calls, ~$0.68. Use Structured Outputs with `response_format: { type: "json_schema" }` and `strict: true` for guaranteed valid JSON. Pydantic validation for 0.0-1.0 range enforcement. Have $5 in OpenAI credits. Provider-agnostic wrapper so switching to Anthropic is a config change.
