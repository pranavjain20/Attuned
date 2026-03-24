# Attuned — Product Decision Log

Every non-obvious product decision made during development. The what, why, how, and effect. Organized chronologically. Research and system design docs remain clean — this is where the "test and learn" lives.

---

## Day 1: Data Foundation

### Extended history filtering: >30s plays only
**What we noticed:** 58% of plays in Spotify extended history are <=30s — skips, previews, accidental taps.
**Decision:** Filter to >30s for engagement scoring. Short plays are noise, not signal.
**Effect:** Cleaner engagement scores. Reduced noise from Alexa auto-plays and skip-throughs.

### Spotify URI as the universal key
**What we noticed:** Extended history already contains `spotify_track_uri` — no search API resolution needed.
**Decision:** Use URI as the song identity key everywhere. No fuzzy matching.
**Effect:** Zero ambiguity in song identity. Dedup handled separately.

---

## Day 2: Engagement Scoring

### Recent play ratio replaced last-played-date recency
**What we noticed:** A song played once yesterday scored higher on "recency" than a song played 50 times last month. One stray play shouldn't inflate a score.
**Decision:** Replace date-based recency with `recent_play_ratio` (plays_last_year / total_plays). Measures sustained recent interest, not a single data point.
**Effect:** Paan Ki Dukaan (3 plays, recent) dropped out of top 20. Songs with consistent recent listening rose.

### Alexa/Echo plays are intentional
**What we noticed:** 2,300+ Echo Dot plays were being marked non-intentional. Alexa voice commands (`remote`, `playbtn`) are deliberate — you asked for the song.
**Decision:** Added `clickrow`, `remote`, `playbtn` to intentional play sources alongside `fwdbtn`.
**Effect:** Active play rate jumped for songs frequently played on Echo. Changed top 10 rankings.

### Minimum meaningful listens: 3 → 5
**What we noticed:** Paan Ki Dukaan had 3 perfect plays and ranked #20. But 3 data points isn't confidence — it's luck.
**Decision:** Bump `MIN_MEANINGFUL_LISTENS` from 3 to 5.
**Effect:** Pool shrank 963 → 669 songs, but every scored song has real signal. Top 10 approved by Pranav.

### Engagement formula weights
**Decision after iterating with Pranav:**
```
log_play: 0.30, completion: 0.25, recent_ratio: 0.20, active_play: 0.15, skip_penalty: 0.10
```
**Why these weights:** Play count (log-scaled) is the strongest signal — you listen to what you like. Completion confirms you didn't skip. Recency prevents decade-old one-offs from scoring. Active play filters ambient/accidental. Skip rate is weakest — some skips are contextual, not dislike.

---

## Day 3: WHOOP Intelligence

### Recovery-first classification (abandoned weighted scoring)
**What we tried:** Decomposed recovery into HRV trend + RHR trend + sleep debt. Recombined with custom weights to produce a composite score.
**What we learned:** WHOOP's recovery score already IS a composite — it combines these signals with their proprietary model. Trying to second-guess their math added complexity and error.
**Decision:** Trust WHOOP's recovery score as the primary gate (which tier are you in?). Use individual metrics (HRV, sleep architecture) to determine HOW to help, not WHETHER.
**Effect:** Simpler classifier, fewer false positives. Recovery tiers directly map to state priority.

### Sleep debt threshold: mean - SD → mean
**What we noticed:** Original "low debt" threshold was `mean - 1*SD` (statistically unusual low debt). This was too restrictive — peak readiness required near-zero debt, which almost never happens.
**Decision:** Changed to `mean` (at or below your personal average).
**Effect:** Peak readiness became achievable on genuinely good days, not just statistical outliers.

### Multi-sleep-per-date bug
**What we noticed:** WHOOP stores naps and primary sleep as separate records. 10 dates had 2 records. Sleep debt and stage baselines were double-counting "needed" sleep.
**Decision:** Aggregate all sleep records per date before any computation.
**Effect:** Fixed inflated sleep debt calculations. Prevented false "poor sleep" classifications on nap days.

### State naming: single_bad_night → poor_recovery
**What we noticed:** "Single bad night" minimizes the experience. When recovery is 38%, you don't think "just one bad night" — you think "I'm wrecked."
**Decision:** Renamed to `poor_recovery` across 8 files. The state name should match how the person FEELS, not how the algorithm categorizes.
**Effect:** Better product language. Playlist names derived from state ("Fuel Up" vs hypothetical "Bad Night Recovery") feel right.

### Peak readiness minimum data: 25 → 47 days
**What we noticed:** With only 25 days of data, baselines were unstable. Peak readiness was triggering on noise.
**Decision:** Require 47+ days (full WHOOP month with buffer) before peak can trigger.
**Effect:** No false peak classifications early in a user's history.

---

## Day 4 Pre-Work: BPM & Property Experiments

### LLM BPM > Essentia BPM for Indian music
**What we tried:** Essentia classical BPM, TempoCNN neural BPM, multiple LLMs.
**Results:**
- Essentia: 4/5 English, 3/13 Indian (tabla patterns confuse beat tracking)
- TempoCNN: identical to Essentia (same Western training bias)
- GPT-4o-mini: 8/25 overall, complementary failures to Essentia
**Decision:** LLM primary for BPM. Essentia as cross-validation (when they agree, high confidence).
**Effect:** Combined accuracy 14/25 within ±5 BPM. Octave errors (2x/0.5x) caught by cross-validation.

### Smaller LLMs beat larger for BPM recall
**What we tested:** GPT-4o-mini (8/25), GPT-4o (6/25), GPT-4.1 (2/25), Claude Sonnet (7/25), Claude Opus (5/25).
**Why:** Smaller models recall memorized database values. Larger models "reason" about tempo from genre/mood and overshoot. For factual recall, don't assume bigger = better.
**Decision:** Stick with GPT-4o-mini for classification.

### "Database recall" prompting beats "estimate" prompting
**What we tested:** "Recall the BPM from music databases" (9/25, MAE 13.1) vs "Estimate the BPM" (8/25, MAE 18.8).
**Why:** Framing as retrieval triggers different model behavior than framing as reasoning.
**Decision:** All classification prompts use recall framing.

### Essentia energy: RMS/0.25 → RMS/0.35
**What we noticed:** RMS with 0.25 divisor clipped 46% of songs at energy=1.0. Modern mastered-loud pop floored the scale.
**What we tried:** Loudness normalization, P90, sigmoid, percentile mapping, composites. All worse.
**Decision:** Simple fix: RMS/0.35 → 71% accuracy. No complex algorithm beat simple normalization.
**Lesson:** When individual components are ~70% accurate, composites amplify noise. Save composites for >85% components.

### Essentia danceability: abandoned entirely
**What we noticed:** Essentia DFA (detrended fluctuation analysis) measures rhythmic regularity, not danceability. A metronomic slow ballad scores higher than a syncopated dance track. 42% accuracy (worse than random).
**Decision:** LLM only for danceability.

### Acousticness: spectral centroid → spectral flatness
**What we tested:** Centroid 33% vs flatness 67%.
**Why:** Flatness measures tonal vs noise-like (matches acoustic vs electronic). Centroid measures brightness (bright guitar = "electronic" — wrong).
**Decision:** Switched to flatness-based acousticness.

---

## Day 4: LLM Classification

### Don't include Essentia BPM in LLM prompt
**What happened:** LLM trusted Essentia's octave errors over its own correct recall. Blinding Lights: LLM correctly knew 171 → Essentia said 86 → LLM adopted 86.
**Decision:** Never feed Essentia BPM to the LLM. Handle BPM merge in code separately.
**Effect:** LLM maintains independent BPM recall. Cross-validation catches disagreements.

### LLM self-reported confidence is worthless
**What we noticed:** GPT-4o-mini reported 1.0 confidence on every song, including niche devotional tracks it clearly didn't know.
**Decision:** Build computed confidence from cross-validation (BPM agreement, Essentia availability), not LLM self-report.

### Valence bias on melancholy/devotional songs
**What we noticed:** LLM confused "pretty melody" with "positive emotion." Examples:
- Photograph (Ed Sheeran): nostalgic/sad → LLM said 0.7, should be 0.3
- Namo Namo (devotional prayer): reverent → LLM said 0.7, should be 0.3
**Decision:** Added explicit calibration: "Valence measures emotional positiveness of the FEELING, not melody beauty. Sad/nostalgic = 0.2-0.4 even if melody is beautiful."
**Effect:** Improved valence separation between genuinely happy and beautifully sad songs.

### Felt tempo for devotional music
**What we noticed:** Indian devotional music has tabla at 120 BPM but vocal phrase cycles at 60-80. For neurological impact, felt tempo matters more than measured tempo.
**Decision:** Added `felt_tempo` field to schema and prompt.
**Effect:** Minimal — LLM mostly ignores it (<5% of songs). Exists as a hook for future improvement.

---

## Day 4b: Accuracy Tuning

### Confidence-aware ensemble replaced weighted averaging
**What we tried:** 50/50 weighted average of LLM + formula scores. Both at 64% individually → average at 68%.
**What we learned:** Weighted averaging can't fix structural biases. When formula systematically overpredicts grounding in the 75-105 BPM zone and LLM systematically underpredicts it, averaging gives you 50% of each problem.
**Decision:** Conditional routing based on WHEN each source fails:
1. Both agree → 50/50 blend
2. Formula says GRND in 70-110 BPM + low energy → Trust LLM 75% (formula biased by quiet songs)
3. Formula says GRND in 70-110 BPM + decent energy → Trust formula 70% (legitimate call)
4. Other disagreements → LLM preference 60%
**Effect:** 68% → 72% accuracy. Structural routing outperforms blind averaging.

### Product accuracy vs bucket accuracy (the CPO insight)
**What we noticed:** Bucket accuracy (66%) made us think the system was broken. But the product doesn't use buckets.
**The realization:**
- Bucket accuracy: Is the highest-scoring bucket correct? (66%)
- Product accuracy: Would this song be selected for the right playlist? (83%)
- Safety: Would it NOT be selected for opposite situation? (86%)
A song with para=0.65, grnd=0.70 gets labeled "GRND" (counted wrong). But it STILL gets selected for a calming playlist because para=0.65 is well above threshold.
**Decision:** Stop optimizing bucket accuracy. Continuous scores serve the matching engine. Ship it.
**Effect:** Unblocked Day 5. Hours saved from chasing the wrong metric.

### The wall at 72% — parameters can't fix structure
**What we tried:** Grid search on grounding sigma (10-15), Indian blend weight (40-70%). Every non-regressing config topped at 68%.
**Why:** The 10 failing songs had root causes unrelated to parameters: stale BPM, LLM valence bias, felt tempo concept not engaged. Parameters can't fix structural issues.
**Decision:** Fix root causes (reclassify with updated prompts, add Essentia data) instead of tuning parameters.

### Test on unseen data before declaring victory
**What happened:** Tuned on 25 songs, achieved 72%. Tested on fresh 34-song set: 56%.
**Why so low:** 98% of the library had no Essentia energy/acousticness. Default value 0.5 breaks the grounding gaussian (peaks at 0.35-0.40).
**Fix:** Added LLM energy/acousticness estimates as fallback. Fresh set improved 56% → 65%.
**Lesson:** Always validate on unseen data. The tuning set was blind to a fundamental gap.

---

## Day 5: Matching Engine

### Dot product replaced range boxes
**What we tried (v1):** Hand-tuned property ranges per state (BPM 50-70, energy 0.1-0.3, etc.). 49 range boundaries.
**What happened:** 94% of library filtered out, only 80 songs eligible, 67% overlap between adjacent states.
**Decision (v2):** Neuro-score dot product: `song_para × state_para + song_symp × state_symp + song_grnd × state_grnd`
**Effect:** Full library eligible, songs ranked by alignment. Zero hard cutoffs. Different states produce different top-20s.

### Grounding decorrelation: the instrumentalness flip
**What we noticed:** Para and grounding had r=0.921 correlation. Same songs won for all calming states. Root cause: both formulas rewarded the same properties (slow, quiet, acoustic, instrumental).
**Key insight:** Parasympathetic = absence of stimulation. Grounding = presence of emotional content. Grounding needs VOCALS for emotional connection.
**Changes:**
- BPM center: 75 → 90 (moderate, not slow)
- Energy center: 0.35 → 0.40 (engagement needs presence)
- Acousticness: raw → gaussian at 0.5 (moderate, not pure quiet)
- **Instrumentalness: raw → (1-instrumentalness)** — the key flip
- Valence center: 0.35 → 0.55 (warmer emotion)
- Added mood tags as 15% weight (semantic dimension orthogonal to audio)
**Effect:** r=0.921 → 0.638. Krishna Das mantras correctly in fatigue playlists, Bollywood ballads in emotional processing playlists.

### Unified ranking over pool splitting (Pranav's algorithm)
**What we tried:** Split "recent" (played <90 days) and "discovery" pools, rank each, merge.
**Problem:** Mediocre recent song (rank #200 overall) beat excellent discovery song (rank #21).
**Decision:** One ranked list. Walk it. First 5 recently-played songs become anchors. Fill remaining 15 from rest in order.
**Effect:** Emotional processing optimality 60% → 100%. Overall ~74%. Recent songs only make the cut if genuinely good.

### Freshness nudge over variety penalty
**What we tried:** 0.3x multiplier for yesterday's songs. A great song scoring 0.9 became 0.27.
**Decision:** Subtractive nudge: `score - 0.02` for yesterday's songs, `- 0.01` for day before.
**Why:** Typical adjacent-song gap is 0.005-0.012. A 0.02 nudge swaps with nearest neighbors. Never overrides quality.
**Effect:** Same state 3 days → 9 fresh songs each day, 11 retained. ~45% daily turnover. Core 55% stays.

### State profile gaps widened
**What we noticed:** Fatigue (para=0.80) and physical recovery (para=0.65) were only 0.15 apart. With formula noise, same songs won for both.
**Decision:** Widened: fatigue para=0.95, physical=0.60. Gap of 0.35.
**Effect:** Different songs win even with noisy scores. Each state produces a distinct playlist.

---

## Day 6: Playlist Creation

### Dynamic playlist names from neuro profile
**Decision:** Names reflect what the music does, not clinical state names.
- Fatigue → "Slow Down" or "Rest & Repair"
- Peak → "Full Send" or "Stay Sharp"
- Baseline → "Settle In" or "Fuel Up"
- Emotional → "Sit With It" or "Ground Yourself"
**Why:** "Accumulated Fatigue Playlist" is clinical. "Slow Down" is what the music actually tells you to do.

### Era cohesion: genre-aware Gaussian decay
**What we researched:** Hindi/Bollywood has discrete production eras (pre/post A.R. Rahman 1992, Honey Singh 2011, Tanishk 2016). English music evolves continuously.
**Decision:** Gaussian decay on release year with genre-specific sigma:
- Hip-hop σ=2 (tight — production IS the genre)
- Bollywood σ=6 (moderate — melody > production)
- Ghazal σ=12 (loose — timeless form)
**Tuning:** Weight 0.10 (max swing 0.06, couldn't exclude cross-era songs) → 0.20 (max swing 0.12, correctly filtered 1999 songs from 2010s cluster).
**Test case:** Chunnari Chunnari (1999) excluded from 2009-2018 Bollywood cluster.

### Iso principle: decided NOT to implement
**What we researched:** Music therapy principle — start playlist near listener's current state, gradually transition toward target. Heiderscheit & Madson 2015, Saarikallio 2021.
**Decision:** Don't implement sequencing. Reasons:
1. High complexity for 20-song ordering
2. Spotify usage is mostly shuffle/skip
3. Core value (neurologically correct songs) doesn't require sequence
**Playlists ordered by score instead.**

---

## Day 7: Audit & Hardening

### Near-duplicate playlist dedup
**What we found:** 69 pairs of near-duplicate songs in library (re-releases, remastered versions).
**Decision:** Dedup by `(LOWER(TRIM(name)), LOWER(TRIM(artist)))`, consolidate URIs, merge listening history.
**Effect:** Prevented same song appearing twice in a playlist under different URIs.

---

## Day 8: Echo Chamber Fix

### Essentia hints in LLM prompt created echo chamber
**What we noticed:** LLM prompt included Essentia energy/acousticness as "hints." The LLM learned to parrot these values back. When we re-ran classification, merged values converged to Essentia-only (LLM "independent" estimate was actually Essentia's number).
**Decision:** Remove Essentia hints from prompt. LLM classifies blind. Merge happens in code after both produce independent estimates.
**Effect:** LLM energy/acousticness estimates are now genuinely independent. Merge is meaningful.

### Separate source columns for idempotent recompute
**What we noticed:** `recompute-scores` read from `energy`/`acousticness` columns — the same columns it wrote merged values to. Second run merged already-merged values. Not idempotent.
**Decision:** Added `essentia_energy`/`essentia_acousticness` columns. Essentia writes to source columns. Merge reads from source columns, writes to merged columns.
**Effect:** `recompute-scores` is fully idempotent. Can run unlimited times, same result.

### Removed genre outlier validation (182/300 false positives)
**What we noticed:** Genre validation flagged 182 of 300 songs as "outliers." Too aggressive — Indian music genres don't follow Western taxonomies cleanly.
**Decision:** Removed the check entirely. Better to trust the classification than over-filter.

---

## Day 9: Restorative Sleep Gate

### Restorative sleep overrides accumulated fatigue
**What we noticed:** Today classified as accumulated fatigue (recovery 58%, 3 of last 5 days <60%). But last night's sleep was excellent: 4.1h deep+REM, 7.5h total, 92% efficiency. Pranav felt well-rested. The "Slow Down" playlist (95% parasympathetic, devotional, Hanuman Chalisa) didn't match how he felt.
**Research we did:**
- Sleep quality is the single strongest predictor of next-morning subjective state — coefficient 2.6x larger than reverse direction (PMC6456824)
- Sleep efficiency is the strongest objective correlate of subjective sleep quality (Nature Scientific Reports 2024)
- Reallocating 30 min light → deep sleep improves positive affect by +0.38 independent of total duration (PMC12208346)
- One good night does NOT fully reverse accumulated fatigue objectively. But subjective experience is disproportionately driven by last night.
**The product insight:** Playlists target how you FEEL, not your lab-measured cognitive performance. A person who slept great doesn't want "slow down" even if the week has been rough.
**Decision:** Added restorative sleep gate to accumulated fatigue. If last night meets ALL four conditions, skip fatigue:
1. No deep sleep deficit
2. No REM sleep deficit
3. Sleep efficiency >= 85%
4. Total sleep >= 6 hours
**Effect on today:** Accumulated fatigue → baseline. Playlist changed from devotional/gentle (Hanuman Chalisa, Channa Mereya) to energizing Bollywood (Sarphira, Sher Khul Gaye). Zero track overlap.
**Backtest:** 830 recovery days. 150 → 88 fatigue days (62 flipped). All 62 had genuinely restorative sleep when inspected. All landed on baseline. 966 tests passing.

### Poor recovery means "get me functional," not "slow down"
**What we decided (Day 3, validated Day 9):** Poor recovery (today is terrible, acute bad day) needs a playlist that brings you UP — gentle energy, not parasympathetic shutdown. Unlike accumulated fatigue which eases into rest.
**Why this matters:** The matching profiles reflect this: poor_recovery has symp=0.30 (some energy), while fatigue has symp=0.00 (zero stimulation).

### Recovery delta: jump should boost energy
**What we noticed:** Recovery jumping 24→80 should feel different than steady 80. The body is bouncing back — playlist should match that energy.
**Decision (Day 8):** Added recovery delta modifier. Large day-over-day recovery swings (>1.5 SD) nudge the neuro profile toward sympathetic (coming up) or parasympathetic (crashing down).
**Effect:** Same recovery score, different playlist energy based on trajectory.

---

## Crosscutting Lessons

### Measure the product metric, not a proxy
Bucket accuracy (66%) looked broken. Product accuracy (83%) showed the system worked. Hours wasted optimizing the wrong metric. Always ask: what does the user experience?

### Parameters can't fix structure
When parameter tuning hits a ceiling, it's a structure problem. The wall at 72% broke when we fixed formulas (instrumentalness flip, BPM centers), not when we tuned sigmas.

### Better data can make a biased formula worse
Restoring correct Essentia energy made the grounding bias stronger (gaussian peaks where quiet songs measure). More accurate data revealed the formula was structurally wrong. Data quality and formula structure must improve together.

### Build fast iteration tools before optimizing
`recompute-scores` (2 seconds, no API calls) enabled testing 40+ parameter combos in the time one reclassification took. Always build the feedback loop first.

### Fix bugs before re-running pipelines
The `--force` flag wiped Essentia data. Ran it twice knowing the bug existed instead of fixing first. Cost $1.40 and 2 hours. Always fix first, run second.

### Test on unseen data before declaring victory
Tuned on 25 songs (72%). Fresh 34-song set: 56%. The tuning set was blind to a fundamental gap (missing Essentia for 98% of library).

### Know when to stop optimizing
83% product accuracy, 93% within one bucket, 86% safety. Remaining gap needs data (more audio clips), personalization (feedback loop), or neural models. None are classification parameter improvements.
