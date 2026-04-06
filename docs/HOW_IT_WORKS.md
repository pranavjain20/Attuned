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

Attuned extracts 12 physiological signals from your morning WHOOP data, computes a continuous neurological profile of how your nervous system actually feels — a 3D representation WHOOP doesn't compute — and builds a Spotify playlist of 15-20 songs from YOUR library that have the right neurological properties. Not generic "chill vibes" — your songs, chosen by science.

It runs locally on your laptop. Supports multiple users via `--profile` flag (separate databases per user). One command: `python main.py generate`.

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

**Brain 1 (WHOOP Intelligence):** Takes your recovery data, sleep architecture, and multi-day trends → computes 12 physiological z-scores → feeds them through a weighted function to produce a continuous neuro profile (parasympathetic/sympathetic/grounding weights). The state classifier still runs for display labels (e.g., "Rest & Repair," "Fuel Up") but does NOT drive song selection.

**Brain 2 (Song Intelligence):** Takes your songs (5,313 classified across 3 users) → classifies each with 3 neurological scores: parasympathetic (calming), sympathetic (energizing), grounding (emotional centering). Uses a combination of LLM classification and Essentia audio analysis.

**The Bridge (Matching Engine):** Given a continuous neuro profile from Brain 1 and scored songs from Brain 2, selects the 20 best songs via cosine similarity scoring + cohesion filtering. For natural language requests via WhatsApp, the LLM picks songs directly by meaning (Claude Sonnet sees the full library) — no neuro-profile middleman.

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

### 4.4 State Classification (Display Labels Only)

The classifier evaluates states in priority order and returns the FIRST match. As of Day 12, the state classifier is used for display labels and logging only — it does NOT drive song selection. The continuous neuro profile (section 6.1) drives scoring.

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

**Why keep the classifier if it doesn't drive selection?** The state label provides human-readable context in playlist names, Spotify descriptions, and database logs. "Rest & Repair" is easier to glance at than "para=0.42, symp=0.26, grnd=0.32." The continuous profile replaced it for scoring because physiological states are continuous — a 44% recovery day and a 15% recovery day both hit "poor_recovery" but need very different music.

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

**Current coverage:** 5,313 songs classified across 2 users. Essentia coverage is 99%+ per user. A handful of songs per library are LLM-only (YouTube unavailable).

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

**Coverage:** 99%+ per user library. A handful of songs per library are genuinely unavailable on YouTube.

---

## 6. The Bridge: Matching Body State to Music

### 6.1 Continuous Neuro Profile

**The old architecture (Days 1-11):** State classifier → one of 7 static profiles → modifier chain (recovery delta, sleep quality). Each state had a fixed target like `para=0.95, symp=0.00, grnd=0.05`. Problem: a 44% recovery and a 15% recovery both mapped to the same static profile. Modifiers tried to patch this but added complexity without solving the fundamental discretization problem.

**The new architecture (Day 12+):** 12 physiological z-scores feed a weighted function that produces a continuous neuro profile. No thresholds, no cliffs, no gates. Every metric contributes proportionally.

**The 12 signals:**

| Signal | What it measures | Direction |
|--------|-----------------|-----------|
| recovery_z | Today's recovery vs 30-day baseline | Negative → more para |
| recovery_delta_z | Day-over-day recovery change vs personal delta baseline | Negative → more para |
| hrv_z | Today's LnRMSSD vs 30-day baseline | Negative → more para |
| hrv_delta_z | Day-over-day HRV change | Negative → more para |
| rhr_z | Today's RHR vs baseline (inverted: high RHR = negative) | Negative → more para |
| rhr_delta_z | Day-over-day RHR change (inverted) | Negative → more para |
| deep_sleep_z | Last night's deep sleep vs baseline | Negative → more para + grounding |
| deep_ratio_z | Deep sleep as fraction of total vs baseline | Negative → more grounding |
| rem_sleep_z | Last night's REM vs baseline | Negative → more grounding |
| sleep_efficiency_z | Sleep efficiency vs baseline | Negative → more para |
| sleep_debt_z | 7-day debt vs baseline (inverted: high debt = negative) | Negative → more para + grounding |
| hrv_trend_z | 7-day HRV slope normalized by baseline SD | Negative → more para |

**How it works:**

1. Start with neutral profile: `para=0.33, symp=0.34, grnd=0.33`
2. For each available signal, add `z_score × weight × WEIGHT_SENSITIVITY` to each dimension
3. Apply interaction bonuses: when HRV AND RHR are both stressed (z < -1.0), add 0.05 to para. Same for deep+REM both deficit.
4. Clamp all dimensions to [0, 1], then normalize to sum to 1.0

**Weight sensitivity (0.20):** Scales all weights globally. At 1.0, a bad day where many signals correlate produces extreme profiles. At 0.20, the profile moves proportionally but stays moderate. Calibrated across scenarios:
- Great day (85% recovery): Para 0.21, Symp 0.46 (energetic)
- Okay day (54%): Para 0.36, Symp 0.32 (balanced, slightly calm)
- Bad day (44%): Para 0.40, Symp 0.26 (noticeably calmer, not rest mode)
- Terrible day (15%): Para 0.59, Symp 0.06 (deep rest)

**Why this is better than the state machine:** Two days at 44% recovery with different sleep architecture, different HRV trends, and different recovery trajectories now produce genuinely different profiles. The old system mapped both to the same "poor_recovery" bucket.

The static state profiles still exist as fallback targets in `state_mapper.py` (used if continuous profile computation fails), and the state classifier still runs for display labels.

### 6.2 Cosine Similarity

For each song, the match score is:

```
neuro_match = dot(song, profile) / (|song| × |profile|)
```

Where:
- `dot = song_para × profile_para + song_symp × profile_symp + song_grnd × profile_grnd`
- `|song| = sqrt(song_para² + song_symp² + song_grnd²)`
- `|profile| = sqrt(profile_para² + profile_symp² + profile_grnd²)`

This is clamped to [0, 1]. Cosine similarity measures directional alignment: a song that points in the same direction as the target scores high regardless of magnitude. A song that's "too much" in one dimension gets penalized — it's pointing slightly off-axis.

**Why cosine instead of one-sided dot product?** The old formula (`dot / |profile|`) only normalized by the profile magnitude, not the song magnitude. This meant songs with large magnitudes (high scores in all dimensions) could score near 1.0 for ANY profile, creating ties at the top. Cosine similarity normalizes both sides, so only songs whose neuro shape genuinely matches the profile score high.

### 6.3 Confidence Multiplier

Songs with Essentia validation (confidence ≥ 0.7) get full weight. LLM-only songs (confidence 0.5-0.7) get multiplied by 0.85 — slightly penalized because their properties are less accurate.

### 6.4 Playlist Rotation

Two layers prevent repetition:

**Hard cap (days-since-last-appearance):** Songs that appeared in a recent playlist are blocked entirely until a minimum gap has passed. The gap scales logarithmically with library size — more songs means a longer gap because there's more depth to rotate through. Formula: `base = max(1, round(log2(library_size / 150)))`. Current bangers (top-quartile engagement + played in last 30 days) get a 1-day discount.

**Freshness nudge (soft tiebreaker):** Songs that appeared 1-4 days ago (if they passed the hard cap) get a small score subtraction: 0.04 for yesterday, 0.03 for 2 days, 0.02 for 3, 0.01 for 4. This only breaks ties among similarly-scored songs — never overrides a genuinely better neurological match.

The old system only had the soft nudge, which wasn't enough — the same 12 "perfect match" songs dominated every playlist. The hard cap forces the engine to explore deeper into the library.

### 6.5 Bollywood Motivational Filter

Bollywood motivational songs (Chak De India, Ziddi Dil, Halla Bol) are tied to specific movie scenes — training montages, sports anthems. Hearing them evokes the scene, not the mood. They're excluded from all playlists except peak_readiness, where the pump-up context fits.

Detection: mood tags include "motivational" AND genre tags include any Bollywood/Punjabi variant. Plus a manual override set for songs the LLM missed tagging. English motivational songs are allowed everywhere — Western pop isn't written for a specific film scene.

### 6.6 The Selection Algorithm

1. Compute continuous neuro profile from 12 physiological z-scores
2. Exclude blocked songs: user blocklist, Bollywood motivational (if not peak_readiness), hard-cap rotation
3. Score ALL remaining songs by `cosine_similarity × confidence × familiarity - freshness_nudge`
4. Rank by score (unified ranking — no pools, no splitting)
5. Take the top 60 candidates
6. Pass to the cohesion engine for sonic coherence filtering
7. Get back 15-20 songs that are neurologically correct AND sound good together

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
python main.py [--profile <name>] generate
```

1. Read WHOOP data for today
2. Compute personal baselines (30-day rolling)
3. Detect trends (7-day HRV/RHR slopes)
4. Analyze sleep architecture (deep/REM deficits)
5. Classify physiological state (priority-ordered) — used for display label only
6. Compute 12 physiological z-scores (recovery, HRV, RHR, sleep stages, debt, trends, deltas)
7. Feed z-scores through weighted function → continuous neuro profile (para/symp/grnd)
8. Apply rotation hard cap: exclude songs that appeared within minimum gap
9. Score all songs by cosine similarity × confidence × familiarity - freshness nudge
10. Take top 60 → run cohesion seed-and-expand → get 20 coherent songs
11. Create Spotify playlist: "Mar 20 — Rest & Repair"
12. Write description: "Calming your nervous system · Bollywood · Melancholy, Reflective, Romantic"
13. Log everything to database (state, z-scores, neuro profile, reasoning, metrics, tracks, description)

Multi-user: the `--profile <name>` flag routes to a separate database (`attuned_<name>.db`), allowing each user to have their own WHOOP data, song library, baselines, and playlists.

---

## 9. Design Decisions & Iteration History

See [PRODUCT_DECISIONS.md](PRODUCT_DECISIONS.md) for the full log of what we tried, what worked, what didn't, and why — organized chronologically across all 12 days of development.

---

## 10. Current Performance

**Data quality:**
- 5,313 classified songs across 2 users
- Essentia coverage 99%+ per user
- All songs have LLM valence, mood tags, genre tags
- Para↔Grnd correlation: 0.638 (started at 0.921 — 31% reduction)

**Scoring quality (cosine similarity):**
- Cosine similarity eliminated the 1.000-score ties that plagued the old one-sided dot product
- Songs now differentiate properly — a calm song scores high for a calming profile and low for an energizing one, without magnitude inflation

**Variation:**
- Hard cap rotation forces library exploration: songs can't reappear until minimum gap passes
- Current bangers get a 1-day discount (they've earned repeat access)
- Different continuous profiles on consecutive days (even if same state label) produce genuinely different playlists

**Sample playlists:**
- Terrible day (para=0.59) → Tujhe Kitna Chahne Lage, Mast Magan, Aashayein Slow Version (slow, emotional ballads)
- Emotional processing (grnd-dominant) → Saiyaara, Piya O Re Piya, Ajab Si (warm, reflective Bollywood)
- Great day (symp=0.46) → Oh Ho Ho Ho Remix, Sweety Tera Drama, Afghan Jalebi (high-energy bangers)

---

## 11. Remaining Limitations

**Things only fixable with user feedback:**
- Signal weights and weight sensitivity (0.20) — research-informed starting points, not calibrated to individual nervous systems
- Profiler formula parameters — research-informed but personal preference matters
- Mood tag weight (15%) — could be 10% or 20%, needs real playlist evaluation

**Things fixable with more data:**
- Para↔Grnd correlation still at 0.638 — structural from shared audio features. Would need lyrical content analysis or personal feedback to go lower.
- Some songs missing release_year (Spotify rate-limited) — needed for era cohesion

**Things that are at their ceiling:**
- LLM valence/danceability accuracy (~42-50%) — only fixable with a different measurement approach
- The library's natural clustering — your taste defines the song pool. More ambient/instrumental music would improve calming-state variety.

---

_1,048 tests passing. Built over 12 days with iterative validation at every step._
