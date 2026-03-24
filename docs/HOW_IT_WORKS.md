# Attuned: How It Works — Complete Technical Guide

_If I had to rebuild this from scratch, this is everything I'd need to know._

---

## Table of Contents

1. [What This Is](#1-what-this-is)
2. [The Core Idea](#2-the-core-idea)
3. [The Two Brains](#3-the-two-brains)
4. [Brain 1: Understanding Your Body (WHOOP Intelligence)](#4-brain-1-understanding-your-body)
5. [Brain 2: Understanding Your Music (Song Intelligence)](#5-brain-2-understanding-your-music)
6. [The Bridge: Matching Body State to Music](#6-the-bridge-matching-body-state-to-music)
7. [Making It Sound Right: Cohesion](#7-making-it-sound-right-cohesion)
8. [The Full Pipeline: From Wake-Up to Playlist](#8-the-full-pipeline)
9. [Design Decisions & Iteration History](#9-design-decisions--iteration-history)
10. [Current Performance](#10-current-performance)
11. [Remaining Limitations](#11-remaining-limitations)

---

## 1. What This Is

Attuned reads your morning WHOOP data, figures out what your nervous system needs, and builds a Spotify playlist of 15-20 songs from YOUR library that have the right neurological properties. Not generic "chill vibes" — your songs, chosen by science.

It runs locally on your laptop. Single user. One command: `python main.py generate`.

---

## 2. The Core Idea

Your autonomic nervous system (ANS) has two branches:
- **Parasympathetic** — rest, recovery, calm. Measured by high HRV.
- **Sympathetic** — energy, alertness, activation. Measured by low HRV.

Music directly affects the ANS. This is established neuroscience with EEG and HRV studies:
- Slow tempo (60-80 BPM) increases parasympathetic activity — calms you down, raises HRV
- Fast tempo (120+ BPM) activates sympathetic response — increases arousal, heart rate
- Acoustic instruments calm more than electronic sounds
- Familiar music amplifies the effect (74.8% of people respond better to their own music)
- Instrumental music reduces cognitive load more than vocals

WHOOP measures your ANS state. Song properties determine what a song does to your ANS. Attuned connects the two.

---

## 3. The Two Brains

The system has two independent intelligence layers:

**Brain 1 (WHOOP Intelligence):** Takes your recovery data, sleep architecture, and multi-day trends → outputs one of 7 physiological states (e.g., "accumulated fatigue," "peak readiness").

**Brain 2 (Song Intelligence):** Takes your 1,360 songs → classifies each with 3 neurological scores: parasympathetic (calming), sympathetic (energizing), grounding (emotional centering). Uses a combination of LLM classification and Essentia audio analysis.

**The Bridge (Matching Engine):** Given a state from Brain 1 and scored songs from Brain 2, selects the 20 best songs via dot product scoring + cohesion filtering.

---

## 4. Brain 1: Understanding Your Body

### 4.1 Personal Baselines

Every metric is interpreted relative to YOUR normal, not population averages. A 50% recovery means something completely different if your 30-day average is 48% vs 65%.

**How baselines are computed:**
- Take the last 30 days of data (excluding today)
- Need at least 14 days to be reliable
- Compute mean, standard deviation, and coefficient of variation (CV = sd/mean)
- Done for: HRV (using natural log of RMSSD), resting heart rate, deep sleep duration, REM sleep duration, deep/REM ratios

**Why natural log of RMSSD?** Raw HRV in milliseconds is right-skewed — a few high readings dominate the average. The natural log (LnRMSSD) normalizes the distribution so standard deviations are meaningful. This follows the Plews/Buchheit methodology used in sports science.

### 4.2 Trend Detection

Single-day numbers are noisy. Multi-day trends reveal the real picture.

**HRV trend (7-day):**
1. Take HRV readings for the last 7 days
2. Run linear regression → get slope (positive = improving, negative = declining)
3. Check for consecutive days below baseline: if HRV is more than 1.0 standard deviation below the 30-day mean for 3+ consecutive days, flag as "declining"

**RHR trend (7-day):**
- Same regression approach
- If resting heart rate is 5+ BPM above baseline for 3+ consecutive days, flag as "rising" (bad sign)

**Sleep debt (7-day rolling):**
- Each day: debt = max(0, sleep_needed - actual_sleep)
- Sleep needed = baseline need + debt payback + strain payback (conservative — doesn't subtract nap credit)
- Sum the last 7 days of daily debt → total debt in hours

### 4.3 Sleep Architecture Analysis

Not just "did I sleep enough" but "what KIND of sleep."

**Deep sleep deficit:** True if deep sleep is more than 1.5 standard deviations below your personal mean, OR below 10% of total sleep, OR below 1 hour absolute.

**REM sleep deficit:** True if REM is more than 1.5 SDs below mean, OR below 15% of total.

**Adequate:** Within 1.0 SD of mean AND above absolute floors.

The gap between "deficit" (1.5 SD) and "adequate" (1.0 SD) creates a buffer zone — neither deficit nor adequate — which prevents flip-flopping between states.

### 4.4 State Classification

The classifier evaluates states in priority order and returns the FIRST match:

| Priority | State | What it means | When it triggers |
|----------|-------|---------------|-----------------|
| 0 | insufficient_data | Can't compute | Less than 14 days of HRV data |
| 1 | accumulated_fatigue | Multi-day decline | Recovery < 60% AND 3+ of last 5 days also < 60% |
| 2 | poor_sleep | Both sleep types bad | Deep AND REM both deficit |
| 3 | physical_recovery_deficit | Body didn't recover | Deep deficit, REM OK |
| 4 | emotional_processing_deficit | Mind didn't process | REM deficit, deep OK |
| 5 | poor_recovery | Bad day, but isolated | Recovery < 40%, or < 60% with only 0-1 recent bad days |
| 6 | peak_readiness | Everything great | Recovery ≥ 80% + HRV ≥ baseline + no deficits + low debt + trend stable/rising |
| 7 | baseline | Nothing strong either way | Default |

**Why this order matters:** Accumulated fatigue (multi-day pattern) is checked before single-day poor recovery. Sleep deficits are checked before general poor recovery because they're more specific — knowing it's a deep sleep deficit vs REM deficit changes what music you need.

**Why 7 states, not 3 or 20?** Three states (good/ok/bad) can't differentiate "your body needs rest" from "your mind needs emotional processing." Twenty states would have too few songs per state from a 1,360-song library. Seven is the sweet spot where each state has a genuine product difference (different music) and enough songs to fill a playlist.

---

## 5. Brain 2: Understanding Your Music

### 5.1 Song Classification Pipeline

Every song gets classified with two sources:

**LLM (GPT-4o-mini):** Provides BPM, valence, danceability, instrumentalness, mood tags, genre tags, and direct neuro scores. Processes 5 songs per API call. Knows popular songs well, struggles with obscure Indian music. Costs ~$0.005 per batch.

**Essentia (audio analysis):** Measures BPM, key, mode, energy, and acousticness from 30-second audio clips. More accurate than LLM for energy (71% vs 42%) and acousticness (62% vs 50%). Requires downloading audio from YouTube.

**What each source provides:**

| Property | LLM | Essentia | What we use |
|----------|-----|----------|-------------|
| BPM | Yes | Yes | LLM primary, cross-validated with Essentia |
| Key, Mode | Yes | Yes | Essentia (direct measurement) |
| Energy | Yes (42% accurate) | Yes (71% accurate) | Essentia when available |
| Acousticness | Yes (50% accurate) | Yes (62% accurate) | Essentia when available |
| Valence | Yes | No | LLM only |
| Danceability | Yes | Bad (42%) | LLM only |
| Instrumentalness | Yes | Bad (46%) | LLM only |
| Mood tags | Yes | No | LLM only |
| Genre tags | Yes | No | LLM only |

**Current coverage:** 1,348/1,360 songs have Essentia (99.1%). 12 songs are LLM-only.

### 5.2 The Confidence-Aware Ensemble

The LLM also provides direct neuro scores (para_score, symp_score, grounding_score). The profiler formula computes its own. These are blended using structural knowledge about when each source fails:

- **Both agree on dominant dimension:** 50/50 blend (high confidence)
- **Formula says grounding but song is in BPM 70-110 + low energy:** Formula is biased by the gaussian — trust LLM more (25/75)
- **Formula says grounding, BPM 70-110, moderate energy:** Grounding is plausible — trust formula more (70/30)
- **Other disagreements:** LLM has cultural context advantage (40/60)

This matters because the grounding gaussian (centered at BPM 90) creates a "gravity well" — many songs near BPM 90 get pulled toward grounding even if they're actually calming or energizing. The ensemble corrects for this.

### 5.3 The Neurological Profiler

This is the mathematical core. It turns 7 song properties + mood tags into 3 neurological scores.

**The three dimensions:**

**Parasympathetic (calming, rest):** High score = slow, quiet, acoustic, instrumental. Think Krishna Das, lo-fi, ambient. What you need when your body is exhausted.

**Sympathetic (energizing, activating):** High score = fast, loud, electronic, danceable. Think Dua Lipa, Chak De India, party songs. What you need when you're at peak readiness.

**Grounding (emotional centering):** High score = moderate tempo, warm, VOCAL, reflective. Think Bollywood ballads like Kabira, Ranjha. What you need when your REM sleep was poor and emotional processing was disrupted.

**The formulas:**

Each dimension scores 7 audio properties + mood tags. Audio properties get 85% of the weight, mood tags get 15%. This adds a semantic signal orthogonal to audio — "reflective" vs "melancholy" can't be heard in BPM, but they differentiate grounding from parasympathetic.

**Parasympathetic formula:**

| Component | Formula | Weight |
|-----------|---------|--------|
| Tempo | sigmoid_decay(BPM, plateau=70, decay=110) | 0.35 × 0.85 |
| Energy | (1 - energy) | 0.25 × 0.85 |
| Acousticness | acousticness | 0.10 × 0.85 |
| Instrumentalness | instrumentalness | 0.10 × 0.85 |
| Valence | gaussian(valence, center=0.35, sigma=0.2) | 0.10 × 0.85 |
| Mode | 1.0 if major, 0.5 if minor | 0.05 × 0.85 |
| Danceability | gaussian(danceability, center=0.3, sigma=0.2) | 0.05 × 0.85 |
| Mood tags | fraction matching: spiritual, melancholy, calm, meditative... | 0.15 |

The sigmoid_decay means: BPM ≤ 70 gets full score (~1.0), BPM 90 gets ~0.5, BPM ≥ 110 gets ~0. The transition is smooth, not a cliff.

**Sympathetic formula:**

| Component | Formula | Weight |
|-----------|---------|--------|
| Tempo | sigmoid_rise(BPM, decay=100, plateau=130) | 0.35 × 0.85 |
| Energy | energy | 0.25 × 0.85 |
| Acousticness | (1 - acousticness) | 0.10 × 0.85 |
| Instrumentalness | (1 - instrumentalness) | 0.10 × 0.85 |
| Valence | valence | 0.10 × 0.85 |
| Mode | 0.8 if major, 1.0 if minor | 0.05 × 0.85 |
| Danceability | danceability | 0.05 × 0.85 |
| Mood tags | fraction matching: energetic, uplifting, celebratory, party... | 0.15 |

Note: sympathetic is essentially the mirror of parasympathetic — fast, loud, electronic, danceable, vocal.

**Grounding formula (the tricky one):**

| Component | Formula | Weight |
|-----------|---------|--------|
| Tempo | gaussian(BPM, center=90, sigma=10) | 0.30 × 0.85 |
| Energy | gaussian(energy, center=0.40, sigma=0.15) | 0.20 × 0.85 |
| Acousticness | gaussian(acousticness, center=0.5, sigma=0.25) | 0.15 × 0.85 |
| Valence | gaussian(valence, center=0.55, sigma=0.2) | 0.15 × 0.85 |
| Instrumentalness | (1 - instrumentalness) | 0.10 × 0.85 |
| Mode | 1.0 if major, 0.6 if minor | 0.05 × 0.85 |
| Danceability | gaussian(danceability, center=0.4, sigma=0.2) | 0.05 × 0.85 |
| Mood tags | fraction matching: reflective, introspective, nostalgic, romantic... | 0.15 |

Grounding uses gaussians (bell curves) because it has a genuine peak — too slow loses engagement, too fast loses calm. The center is at moderate values (BPM 90, energy 0.40, valence 0.55).

**Critical design choice: why grounding is different from parasympathetic.**

Originally, grounding and parasympathetic were almost identical (correlation r=0.921). Both rewarded slow, quiet, acoustic songs. This meant the system couldn't distinguish "you need deep rest" from "you need emotional processing."

The fix: grounding was redefined as "presence of emotional content" (vocals, warmth, moderate energy) vs parasympathetic as "absence of stimulation" (instrumental, very slow, very quiet). Key changes:
- Grounding BPM center moved from 85 to 90 (moderate, not slow)
- Grounding energy center moved from 0.35 to 0.40 (engaged, not silent)
- Grounding acousticness changed from raw value to gaussian at 0.5 (moderate, not pure quiet)
- Grounding instrumentalness INVERTED: (1 - instrumentalness) means vocals score HIGH (emotional connection through lyrics)
- Grounding valence center moved from 0.45 to 0.55 (warmer emotion)

After these changes: correlation dropped from 0.921 to 0.638. The system now correctly puts Krishna Das mantras in fatigue playlists and Bollywood ballads in emotional processing playlists.

### 5.4 Audio Acquisition

Getting audio clips for Essentia analysis:

**Strategy D (duration-verified YouTube):**
1. Search YouTube for 5 results: `ytsearch5:{song} - {artist} {album}`
2. Use `--ignore-errors` so blocked videos are skipped (this was a key fix — without it, one blocked video kills the entire search)
3. Get duration metadata for each result
4. Pick the result whose duration is closest to the Spotify track duration (within 45 seconds tolerance)
5. Download and trim to 30 seconds (skip first 30 seconds to avoid intros)
6. If no duration match, fall back to title-matching (trust the search result if title matches)

**Coverage:** 1,348/1,360 songs (99.1%). The remaining 12 are genuinely unavailable on YouTube.

---

## 6. The Bridge: Matching Body State to Music

### 6.1 State Neuro Profiles

Each state maps to a 3-dimensional target:

```
accumulated_fatigue:          para=0.95  symp=0.00  grnd=0.05
poor_sleep:                   para=0.55  symp=0.00  grnd=0.45
physical_recovery_deficit:    para=0.60  symp=0.00  grnd=0.40
emotional_processing_deficit: para=0.10  symp=0.00  grnd=0.90
poor_recovery:                para=0.25  symp=0.30  grnd=0.45
baseline:                     para=0.15  symp=0.50  grnd=0.35
peak_readiness:               para=0.00  symp=0.90  grnd=0.10
```

These were deliberately widened so adjacent states produce different playlists. Fatigue (0.95 para) and physical recovery (0.60 para) are 0.35 apart — enough that different songs win even with noisy scores.

### 6.2 The Dot Product

For each song, the match score is:

```
neuro_match = (song_para × state_para + song_symp × state_symp + song_grnd × state_grnd) / |state_vector|
```

Where |state_vector| = sqrt(para² + symp² + grnd²).

This is clamped to [0, 1]. The result means: "how aligned is this song's neurological profile with what the state needs?"

A song with para=0.9, symp=0.1, grnd=0.1 scores high for fatigue (para-dominant) and low for peak readiness (symp-dominant). That's exactly what we want.

### 6.3 Confidence Multiplier

Songs with Essentia validation (confidence ≥ 0.7) get full weight. LLM-only songs (confidence 0.5-0.7) get multiplied by 0.85 — slightly penalized because their properties are less accurate.

### 6.4 Freshness Nudge

If a song was in yesterday's playlist, subtract 0.02 from its score. Two days ago: subtract 0.01. This is tiny — only breaks ties among similarly-scored songs. If a song is genuinely the best match, the nudge doesn't override it.

Result: same state on consecutive days → ~45% of songs change, ~55% stay. The core best songs persist; near-ties rotate for freshness.

### 6.5 The Selection Algorithm

1. Score ALL 1,360 songs by `neuro_match × confidence - freshness_nudge`
2. Rank by score (unified ranking — no pools, no splitting)
3. Take the top 60 candidates
4. Pass to the cohesion engine for sonic coherence filtering
5. Get back 15-20 songs that are neurologically correct AND sound good together

---

## 7. Making It Sound Right: Cohesion

The matching engine finds neurologically correct songs. But 20 random correct songs might not sound good as a playlist — imagine mixing a Bollywood ballad, an EDM track, a devotional song, and a hip-hop track. All might have the right neuro score but the playlist would feel random.

The cohesion engine picks a sonically coherent subset.

### 7.1 Pairwise Similarity

Every pair of songs gets a similarity score (0-1) based on:
- Genre tags overlap: 20% weight (Jaccard similarity — fraction of shared tags)
- Mood tags overlap: 15% weight
- BPM similarity: 20% weight (gaussian with sigma=10 BPM)
- Era similarity: 20% weight (genre-aware — hip-hop has tight era clustering, ghazal is timeless)
- Energy similarity: 10% weight (gaussian with sigma=0.15)
- Acousticness, danceability, valence: 5% each

### 7.2 Seed-and-Expand

1. **Pick a seed:** The song with the best combination of neuro score × average similarity to other candidates. This is the song that's both a great neurological match AND fits well with the pool.
2. **Expand greedily:** Repeatedly add the candidate most similar to the current selection. Stop when 20 songs are selected or similarity drops below 0.15.
3. **Relax if needed:** If fewer than 15 songs pass the similarity threshold, relax it by 0.03 and try again. Up to 3 relaxation steps (0.15 → 0.12 → 0.09 → 0.06).

---

## 8. The Full Pipeline: From Wake-Up to Playlist

```
python main.py generate
```

1. Read WHOOP data for today
2. Compute personal baselines (30-day rolling)
3. Detect trends (7-day HRV/RHR slopes)
4. Analyze sleep architecture (deep/REM deficits)
5. Classify physiological state (priority-ordered)
6. Get state's neuro profile (e.g., fatigue → para=0.95)
7. Score all 1,360 songs by dot product × confidence - freshness
8. Take top 60 → run cohesion seed-and-expand → get 20 coherent songs
9. Create Spotify playlist: "Mar 20 — Accumulated Fatigue"
10. Write description: "Accumulated Fatigue · Recovery 25% · HRV 32ms · Tuned for parasympathetic · 18 tracks"
11. Log everything to database (state, reasoning, metrics, tracks, description)

---

## 9. Design Decisions & Iteration History

See [PRODUCT_DECISIONS.md](PRODUCT_DECISIONS.md) for the full log of what we tried, what worked, what didn't, and why — organized chronologically across all 9 days of development.

---

## 10. Current Performance

**Data quality:**
- 1,360 classified songs
- 1,348 with Essentia-measured energy/acousticness (99.1%)
- All 1,360 have LLM valence, mood tags, genre tags
- Para↔Grnd correlation: 0.638 (started at 0.921 — 31% reduction)

**Accuracy (Q1): Every song fits its state.**
- 0/140 weak matches across all 7 states
- Worst neuro_match in any playlist: 0.816
- Physical recovery and poor sleep: mean neuro_match 1.000

**Optimality (Q2): ~35% of theoretically ideal songs captured.**
- The cohesion layer intentionally trades some neuro match for playlist sonic coherence
- A playlist of 20 individually-best songs that don't sound good together is worse than 20 slightly-less-perfect songs that flow

**Variation (Q3): ~45% daily turnover when same state repeats.**
- Core 55% retained (clearly best, no alternative beats them)
- 9 fresh songs per day from freshness nudge swapping near-ties
- Different states: 0-1 songs shared

**Sample playlists:**
- Fatigue → Tujhe Kitna Chahne Lage, Mast Magan, Aashayein Slow Version (slow, emotional ballads)
- Emotional processing → Saiyaara, Piya O Re Piya, Ajab Si (warm, reflective Bollywood)
- Peak → Oh Ho Ho Ho Remix, Sweety Tera Drama, Afghan Jalebi (high-energy bangers)

---

## 11. Remaining Limitations

**Things only fixable with your feedback:**
- State neuro profiles (is 0.95 para right for fatigue?) — needs listening and adjusting
- Profiler formula parameters — research-informed but not calibrated to YOUR nervous system
- Mood tag weight (15%) — could be 10% or 20%, needs real playlist evaluation

**Things fixable with more data:**
- 12 songs LLM-only (YouTube unavailable) — marginal impact
- 869 songs missing release_year (Spotify rate-limited) — needed for era cohesion
- Para↔Grnd correlation still at 0.638 — structural from shared audio features. Would need lyrical content analysis or personal feedback to go lower.

**Things that are at their ceiling:**
- LLM valence/danceability accuracy (~42-50%) — only fixable with a different measurement approach
- The library's natural clustering — your taste defines the song pool. More ambient/instrumental music would improve calming-state variety.

---

_774 tests passing. 11 commits. Built over 5 days with iterative validation at every step._
