# Matching Engine Rewrite — Full Session Log

_Day 5b: Everything we tried, what worked, what didn't, and why._

## What we were trying to do

Build the matching engine: given a physiological state (from WHOOP), select 20 songs from Pranav's 1,360 classified songs that have the right neurological properties for what his body needs. The engine sits between the state classifier (Day 3) and playlist creation (Day 6).

The starting plan was to replace the v1 range-box engine (Day 5a) with neuro-score dot product matching, since we already computed para/symp/grnd scores for every song in Day 4.

## v1 baseline: range boxes (Day 5a, already built)

The original engine used hand-tuned property ranges per state:
- accumulated_fatigue: BPM 50-70, energy 0.10-0.30, acousticness 0.65-1.0, etc.
- 7 states × 7 property ranges = 49 hand-tuned boundaries

**Problems identified:**
1. **80/1,360 songs reachable** — 94% of library permanently filtered out by range boxes
2. **67% overlap between adjacent states** — fatigue and poor_sleep had nearly identical ranges
3. **Engagement at 30% weight** — pushed favorites to every playlist, killing rediscovery

## v2: neuro-score dot product + staleness + variety

### What we changed

Replaced the entire scoring pipeline:
- **Deleted:** `score_property()` (sigmoid decay against ranges), `score_mode()`, `score_song()` (weighted property matching)
- **Added:** `compute_neuro_match()` — dot product of song's (para, symp, grnd) against state profile, normalized by profile magnitude, clamped to [0,1]
- **Formula:** `neuro_match × confidence × 0.75 + staleness × 0.15 + variety × 0.10`
- Staleness: `min(days_since_last_played / 90, 1.0)` — bonus for rediscovery
- Variety: 0.3x for yesterday's songs, 0.6x for 2-days-ago

State profiles defined as neuro weight vectors:
```
accumulated_fatigue:          para=0.85  symp=0.00  grnd=0.15
peak_readiness:               para=0.00  symp=0.85  grnd=0.15
emotional_processing_deficit: para=0.15  symp=0.00  grnd=0.85
(etc.)
```

### Results

| Metric | v1 (range boxes) | v2 (neuro + staleness) |
|--------|-----------------|----------------------|
| Candidates eligible | 80 | 1,360 |
| Unique songs (7 states) | 80 | 77 |
| Peak↔anything overlap | unknown | 0% |
| Fatigue↔Physical overlap | ~67% | 90% |

**Problem:** Unique songs barely changed (80→77), and fatigue↔physical got WORSE (90%). The dot product worked for extremes (peak vs calming) but couldn't differentiate adjacent calming states.

## Deep diagnosis: why 77 unique songs?

We ran 18 diagnostic analyses to find the root causes. Three compounding issues:

### Root Cause 1: Para ≈ Grnd in the profiler (r = 0.921)

The profiler's grounding formula used the same features as parasympathetic in the same direction:

| Feature | Para formula | Grnd formula | Same direction? |
|---------|-------------|-------------|-----------------|
| BPM (heaviest) | sigmoid_decay(70,110) | gaussian(85,10) | YES — both high at 70-90 |
| Energy (2nd heaviest) | (1 - energy) | gaussian(0.35,0.15) | YES — both high at low energy |
| Acousticness | raw value | raw value | IDENTICAL |
| Instrumentalness | raw value | gaussian(0.3,0.3) | Both reward instrumental |
| Valence | gaussian(0.35) | gaussian(0.45) | Nearly identical centers |

Result: 1,021/1,360 songs (75%) had |para − grnd| ≤ 0.15. The dot product literally could not distinguish fatigue from emotional processing because the song vectors were the same along both dimensions.

### Root Cause 2: Staleness was a flat constant for 77% of songs

1,043/1,360 songs last played >90 days ago → all got staleness = 1.0. The 0.15 staleness weight added a fixed 0.150 to 77% of candidates — zero ranking signal.

### Root Cause 3: Score compression from additive formula

For a typical top-20 candidate: `total = neuro_match × 0.6375 + 0.250`. The 0.250 constant floor (staleness + variety, both maxed) meant only 8% of the total score actually varied. Rankings decided by tiny differences in a compressed band.

## v3: pool-based selection (Pranav's insight)

### The product insight

Pranav: "Maybe, if there are 20 songs, you can give 5 songs that are recent so that it doesn't seem extremely random, but not more than 5."

This reframed staleness from a scoring signal to a structural constraint. Instead of weighting staleness in the formula, split selection into pools:
- Score all songs by `neuro_match × confidence × variety` (no staleness)
- Take up to 5 from "recent" pool (played within 90 days)
- Fill remaining 15 from "discovery" pool

This also simplified the formula — no additive constants, pure multiplicative: `neuro_match × confidence × variety`.

### Results

Score discrimination improved (spread doubled) but unique songs dropped to 68 and fatigue↔physical hit 100% overlap. Removing staleness as a tiebreaker meant neuro_match alone decided the discovery pool ranking — and with para≈grnd, the same songs won for all calming states.

## Fix 1: Decorrelate grounding from parasympathetic (profiler change)

### The product distinction

- **Para (fatigue/rest):** absence of stimulation — slow, quiet, instrumental, no emotional demands. Krishna Das mantras, ambient guitar.
- **Grnd (emotional processing):** presence of emotional content — moderate tempo, warm, LYRICAL, reflective. Bollywood ballads, singer-songwriter.

The key differentiators: **vocals/lyrics** (instrumentalness flip) and **emotional warmth** (valence center shift).

### What we changed in the grounding formula

| Feature | Before | After | Rationale |
|---------|--------|-------|-----------|
| BPM center | 85 | **90** | Grounding songs are moderate, not slow |
| Energy center | 0.35 | **0.40** | Emotional engagement needs presence, not silence |
| Acousticness | raw value | **gaussian(0.5, 0.25)** | Moderate acoustic = warmth, not pure quiet |
| Instrumentalness | gaussian(0.3, 0.3) | **(1 - instrumentalness)** | Grounding needs vocals/lyrics for emotional connection |
| Valence center | 0.45 | **0.55** | Warmer emotion, separated from para's 0.35 |

### Simulation results

We tested 6 configurations before committing:

| Config | r(para,grnd) | Para-dom | Balanced | Grnd-dom |
|--------|-------------|----------|----------|----------|
| Current | 0.910 | 26 | 964 | 370 |
| V2: inst flip only | 0.911 | 36 | 1089 | 235 |
| V3: +acous+val | 0.841 | 50 | 738 | 572 |
| V4: +BPM 95 | 0.628 | 119 | 652 | 589 |
| **V5: +energy 0.45** | **0.527** | **131** | **560** | **669** |
| **V6: BPM 90, eng 0.40** | **0.704** | **83** | **640** | **637** |

Chose V6 (BPM=90, energy=0.40) as the less aggressive option. V5 was too extreme — 0% fatigue↔emotional overlap meant the dimensions were over-separated.

V6 validation on actual songs confirmed the product distinction:
- Top para-dominant: Krishna Das flute, instrumental guitar, lo-fi remixes (absence of stimulation)
- Top grnd-dominant: Bollywood ballads at BPM 95-100 with vocals (presence of emotional content)

## Fix 2: Integrate mood tags into the profiler

### The unused signal

All 1,360 songs had mood tags from LLM classification sitting in the DB:
```
romantic: 395    reflective: 195    melancholy: 172
spiritual: 37    energetic: 259     introspective: 118
```

These encode semantic meaning orthogonal to audio properties. Two songs with identical BPM, energy, acousticness can be "reflective" (grounding) vs "melancholy" (parasympathetic). Audio can't distinguish them. Mood tags can.

### Implementation

Added mood tags as a 15% weight in each dimension, scaling existing audio weights to 85%:

```
PARA tags: spiritual, melancholy, calm, meditative, devotional, dreamy, ...
SYMP tags: energetic, uplifting, celebratory, party, confident, intense, ...
GRND tags: reflective, introspective, nostalgic, romantic, emotional, ...
```

Mood score = (count of matching tags) / (total tags). No tags → 0.5 (neutral).

This added a `mood_tags` parameter to all three compute functions and `compute_neurological_profile`. Recompute-scores command updated to pass mood_tags from DB.

## Fix 3: Widen state profile gaps

Fatigue (0.85, 0, 0.15) and physical recovery (0.70, 0, 0.30) were separated by only 0.15. Widened to:

```
accumulated_fatigue:          para=0.95  symp=0.00  grnd=0.05  (was 0.85/0.15)
physical_recovery_deficit:    para=0.60  symp=0.00  grnd=0.40  (was 0.70/0.30)
emotional_processing_deficit: para=0.10  symp=0.00  grnd=0.90  (was 0.15/0.85)
peak_readiness:               para=0.00  symp=0.90  grnd=0.10  (was 0.00/0.85/0.15)
```

Gap between fatigue and physical recovery: 0.35 (was 0.15).

## Reframing: the right evaluation questions (Pranav's insight)

After implementing all three fixes, we were evaluating with the wrong metrics (overlap %, unique song count). Pranav reframed to the three questions that actually matter:

1. **Accuracy:** Given a state, do the selected songs have the right neurological properties?
2. **Optimality:** Are these the BEST songs from the entire 1,360 for that state?
3. **Variation:** Across a week with different/repeated states, do playlists feel fresh?

This shifted focus from inter-state overlap (an internal metric) to per-state quality (the user experience).

## v4: unified ranking (Pranav's algorithm)

### The problem with pool-based selection

The pool approach split songs into "recent" and "discovery" pools, ranked each independently, then merged. This meant a mediocre recent song (overall rank #200) could beat an excellent discovery song (rank #21) just because it was in the recent pool.

Optimality: only 40-65% of theoretically ideal songs captured.

### Pranav's algorithm

"You pick the top n songs that are objectively the best. In that list, you pick the ones that are the five most recent but also the highest up. Rank number nine might be a recent song."

1. Rank ALL 1,360 songs by `neuro_match × confidence` — one unified ranking
2. Walk the ranking. The first 5 songs that happen to be recently played become anchors
3. Fill remaining 15 slots from the rest of the ranking, in order

Key difference: recent songs only make the cut if they're already highly ranked. No song gets in just because it's recent.

### Results

- Emotional processing: 20/20 ideal captured (100%, was 60%)
- Peak readiness: 20/20 (100%, unchanged)
- Overall optimality: ~74% (was ~60%)
- Emotional processing got 3R+17D (only 3 recent songs were good enough) instead of forced 5R+15D

## v5: freshness nudge (replacing variety penalty)

### Why the old variety penalty was wrong

The old penalty (0.3x for yesterday's songs) was a sledgehammer. A great song scoring 0.9 became 0.27, losing to mediocre songs at 0.35. Pranav questioned the premise: if these are the best songs for baseline, why give worse songs just because you heard them yesterday?

### The right framing

Pranav: "For two songs that are almost the same and you've already played one yesterday, I'd rather want the other one. But it shouldn't hit into wrong songs."

Variation should be a **tiebreaker**, not a penalty. Among equally-good songs, prefer the one not in yesterday's playlist.

### Implementation: subtractive nudge

```python
FRESHNESS_NUDGE = {1: 0.02, 2: 0.01}  # days_ago → subtraction
score = neuro_match × confidence - nudge
```

Typical adjacent-song gap: 0.005-0.012. A 0.02 nudge swaps a song with its 2-3 nearest neighbors. Enough to feel fresh, never enough to put a wrong song in.

### Results

Same state 3 days in a row (baseline): 9 fresh songs each day, 11 retained. The nudge swaps ~45% daily — songs near the boundary get replaced by equally-good alternatives. The core 11 (clearly best) stay regardless.

Different states: 0-1 shared songs (natural differentiation from different neuro profiles).

## Final system state

### Architecture
```
State → neuro profile (para/symp/grnd weights)
Song → neuro scores (from profiler: audio properties + mood tags + LLM ensemble)
Score = dot_product(song_scores, state_weights) / |state_weights| × confidence
Selection = unified ranking, up to 5 recent anchors, freshness nudge for tiebreaking
```

### What we changed (files)
- `config.py` — STATE_NEURO_PROFILES (widened gaps), MOOD_TAG mappings, removed TARGET_RANGES/MATCH_WEIGHTS/SELECTION_*_WEIGHTs/VARIETY_PENALTY
- `classification/profiler.py` — grounding formula decorrelation (BPM 90, energy 0.40, acousticness gaussian, instrumentalness flip, valence 0.55), mood tags as 15% weight in all three dimensions
- `matching/state_mapper.py` — `get_state_neuro_profile()` replacing `get_target_ranges()`
- `matching/query_engine.py` — complete rewrite: `compute_neuro_match()`, unified ranking, freshness nudge
- `db/queries.py` — added `last_played` to classified songs query
- `main.py` — CLI output: neuro profile + pool labels instead of target ranges
- All corresponding test files rewritten

### Product evaluation (3 questions)

**Q1 Accuracy:** 0/140 weak matches. Every song fits its state. Worst neuro_match across all states: 0.679 (still solidly aligned).

**Q2 Optimality:** 50-100% of ideal songs captured (avg ~74%). Remaining gap is from the 5-recent constraint — worth the tradeoff for familiarity.

**Q3 Variation:** 9 fresh songs per day when same state repeats. ~45% daily turnover from freshness nudge. Core 55% retained (clearly best songs for the state).

### Remaining limitations (data, not algorithm)
1. **LLM property accuracy** — 98% of songs LLM-only (energy accuracy ~42%). Essentia on more songs would sharpen scores.
2. **Library clustering** — only ~22 para-dominant and ~20 symp-dominant songs. More ambient/instrumental music would reduce calming-state overlap.
3. **Para↔Grnd correlation** — down from 0.921 to 0.776 but still coupled. The audio features (BPM, energy) naturally drive both. Mood tags help but at 15% weight can only do so much.

### Key learnings

29. **The right evaluation metric matters more than the algorithm.** We spent hours optimizing overlap % and unique song count. Pranav reframed to accuracy/optimality/variation — metrics that map to user experience — and the picture changed completely.

30. **Staleness is a structural constraint, not a scoring signal.** Weighting staleness in the formula (additive) compressed dynamic range. Separating it into a pool constraint (up to 5 recent) preserved score discrimination.

31. **Pool-based selection is worse than unified ranking with filtering.** Splitting into pools and ranking each independently lets mediocre songs from the smaller pool displace better songs from the larger pool. Unified ranking with a filter ("first 5 recent songs encountered") is strictly better.

32. **Variety should be a tiebreaker, not a penalty.** The old 0.3x multiplier destroyed good songs. A 0.02 subtractive nudge breaks ties among similarly-scored songs without overriding genuine quality differences.

33. **Unused data in the DB is a missed opportunity.** Mood tags sat in the DB for the entire project. Adding them as a 15% profiler weight created the orthogonal signal we needed to decorrelate para from grnd — no API calls required.

34. **Profiler correlation is a feature engineering problem, not a matching problem.** The matching engine (dot product) was correct all along. The issue was that the profiler compressed a 7D feature space into a 2D effective space (calm↔energetic + slight grounding). Fixing the profiler formulas and adding mood tags expanded it back toward 3D.

35. **Simulate before committing.** We tested 6 grounding formula configurations (V1-V6) with full correlation and overlap analysis before changing the profiler. V5 (most aggressive) would have over-separated the dimensions. V6 (moderate) was the right choice.

### 693 tests passing, all green.

---

## Day 5c: Essentia Full Library + Audio Pipeline Hardening

### What we were trying to do

Improve input accuracy for all 1,360 songs. Before: only 33 had Essentia-measured energy/acousticness (71%/62% accurate). The other 1,327 relied on LLM guesses (42%/50% accurate). Energy is the second-heaviest weight in the profiler — bad energy → bad neuro scores → wrong playlists.

### Audio download progression

| Stage | Clips | What changed |
|-------|-------|-------------|
| Start | 34 | 33 from Day 4 experiments |
| First download (yt-dlp basic) | 1,069 | Duration-verified Strategy D, skip Spotify previews |
| Duration recovery | +176 | Derived duration_ms from max(ms_played) in listening history |
| Relaxed tolerance (15s→30s) | +43 | Caught Bollywood songs with padded intros |
| --ignore-errors fix | +29 | yt-dlp was failing on blocked videos instead of skipping them |
| Title-match fallback (no duration check) | +33 | For songs where YouTube only has music videos (different length) |
| **Final** | **1,348** | **99.1% of library** |

### The --force bug (cost $1.40 and 2 hours)

`analyze-audio --force` used `upsert_song_classification()` which does a full row replacement. This wiped LLM data (valence, mood_tags, genre_tags, raw_response) for every song Essentia touched. Required a full LLM reclassification ($0.70, ~1 hour) to restore.

**Made this mistake TWICE** — ran --force knowing the bug existed the second time instead of fixing it first. The fix was 10 lines (targeted UPDATE instead of full upsert). Should have fixed the code first, then re-run.

**The fix:**
- Essentia now does `UPDATE ... SET bpm=?, key=?, mode=?, energy=?, acousticness=?` (only its reliable fields)
- Does NOT touch: valence, mood_tags, genre_tags, instrumentalness, danceability, raw_response
- Reads existing `classification_source` from DB to correctly append `+essentia`
- For new songs (no existing row): falls back to full `upsert_song_classification`

### Key decisions

**Duration tolerance: 15s → 30s → 45s.** Initially strict (15s) to avoid wrong audio. But Bollywood songs on YouTube have padded intros/outros (music video vs audio track). 45s catches these while still rejecting genuinely wrong songs. The trim-to-30s function means we only analyze 30 seconds anyway.

**--ignore-errors was the biggest unlock.** yt-dlp fails the entire search if ONE video in the results is unavailable/blocked. Adding `--ignore-errors` makes it skip those and return the rest. Recovered Safarnama, The Scientist, Channa Mereya, and dozens of other popular songs that were incorrectly marked as "unfindable."

**Title-match fallback for the last 37.** For songs where duration verification fails (music video is a different length), we search YouTube, pick the result with the best title match, and download regardless of duration. We trim to 30 seconds anyway, so a 4-minute music video and a 3-minute audio track produce the same 30-second analysis clip. Recovered 33 of 37.

**Bollywood artist = composer OR singer.** Spotify lists either the composer (Pritam) or singer (Arijit Singh) inconsistently. YouTube search fails when Spotify says "Pritam" but every YouTube video says "Arijit Singh." Added context to LLM prompt so future classifications consider both roles.

**Essentia UPDATE should only write what it's reliable for.** Essentia is good at: BPM, key, mode, energy, acousticness. It's bad at: danceability (42%), instrumentalness (46%). The UPDATE path only sets the good fields. The INSERT path (new songs) sets everything since there's nothing to preserve.

### Final intelligence state

| Metric | Start of day | End of day |
|--------|-------------|-----------|
| Essentia-validated | 33/1,360 (2%) | 1,348/1,360 (99.1%) |
| Confidence ≥ 0.7 | 33 | 1,339 |
| Para↔Grnd correlation | 0.921 | 0.638 |
| LLM-only songs | 1,327 | 12 |
| Audio clips | 34 | 1,348 |

### Key learnings

36. **Fix the bug BEFORE re-running the broken code.** Ran --force with a known data-wiping bug, twice. Cost $1.40 and 2 hours. The fix was 10 lines that should have come first.

37. **--ignore-errors is essential for yt-dlp search.** One blocked video kills the entire search without it. This was the biggest unlock for the 74 "unfindable" songs — they were findable all along, just behind a blocked video in the search results.

38. **Duration verification tolerance should match the use case.** 15s was too strict for Bollywood (music videos have padding). 45s is right — catches the right song even with intro/outro differences. Trim-to-30s means the actual analysis clip is consistent regardless.

39. **Derive data from what you already have.** 197 songs were missing duration_ms (Spotify rate-limited). But we had their play events in listening_history — max(ms_played) approximates the song's duration. Zero API calls needed.

40. **Spotify's artist field is unreliable for Bollywood.** Could be composer or singer, inconsistently. This affects both YouTube search (wrong search terms) and LLM classification (wrong context). Added to LLM prompt for future runs.

### 774 tests passing, all green.
