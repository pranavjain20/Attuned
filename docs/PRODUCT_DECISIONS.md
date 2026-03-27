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
**Effect:** Pool shrank 963 → 669 songs, but every scored song has real signal. Top 10 approved by the user.

### Engagement formula weights
**Decision after iterating:**
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

### Unified ranking over pool splitting
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
**What we noticed:** Today classified as accumulated fatigue (recovery below 60%, multi-day pattern). But last night's sleep was genuinely restorative — good deep+REM, high efficiency. The user felt well-rested. The "Slow Down" playlist (95% parasympathetic, devotional) didn't match how they felt.
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

### Continuous baseline profile replaces static compromise
**What we noticed:** Baseline state produced scattered playlists — a mix of slow, inspirational, party songs. The static profile {para:0.15, symp:0.50, grnd:0.35} is a compromise that satisfies no one. "Fuel Up" name implies energy but the playlist was directionless.
**The insight:** Recovery always has direction. On any given day you're trending up or down. True "flat" is rare. The recovery delta (z-score of day-over-day change) already captures this — use it to commit to a direction instead of sitting in a dead zone.
**Decision:** Piecewise linear interpolation on the recovery delta z-score:
- z = -2 → calm anchor: {para:0.45, symp:0.15, grnd:0.40}
- z = 0 → current baseline: {para:0.15, symp:0.50, grnd:0.35}
- z = +2 → energy anchor: {para:0.05, symp:0.75, grnd:0.20}

Replaces the 1.5 SD dead zone threshold. Non-baseline states keep their threshold behavior (the nudge only applies to baseline).
**Effect:** Yesterday's playlist leaned up (z=0.7, +20pp delta) → profile shifted to {0.11, 0.59, 0.30}. More energetic, coherent feel. The playlist committed to a direction instead of averaging everything.

### Recent anchors: guaranteed slots for recently-played songs
**What we noticed:** The "5 recent anchors" design from Day 5 was never implemented. Cohesion picked purely by sonic similarity. Result: 1 of 20 songs had been played in the last 30 days. Chicken Kuk-Doo-Koo (3× this month, score 0.825) was excluded. G Phaad Ke (2 plays, last played 2023) was included.
**Decision:** Added `identify_anchors()` — top-scored songs played within 90 days get guaranteed slots. Cohesion fills the remaining 15 slots. Extended `expand_cluster()` with a `pre_selected` parameter so anchors are part of the cluster from the start.
**Effect:** 5 recently-played songs guaranteed in every playlist. Songs you actually listen to appear. The playlist feels like YOUR music, not a random selection from your library.

### Motivational songs excluded from anchors
**What we noticed:** Chak De India (motivational, recently played at the gym) was getting anchor slots in morning playlists. Gym songs don't belong at breakfast.
**Decision:** Anchors skip songs tagged "motivational" (via `CONTEXT_EXCLUDE_TAGS`). The song can still make the playlist through normal scoring — just not through the guaranteed recent-anchor mechanism.
**Effect:** Chak De India dropped from anchors. Replaced by Daru Badnaam (recently played, not motivational). Morning playlists feel morning-appropriate.

### Weighted mood tag affinity replaces binary sets
**What we noticed:** Mood tags were binary — in a set (1.0) or not (0.0). "Motivational" was identical to "energetic" for sympathetic scoring. 25% of tag instances (449 across 45 tags) were unassigned and defaulted to neutral 0.5. No cross-dimensional contribution.
**Research (12 cited studies):**
- Russell's Circumplex Model (1980): valence × arousal maps to para/symp/grnd dimensions
- Bernardi et al. 2006 (PMC1860846): cardiovascular changes proportional to tempo/complexity
- Chanda & Levitin 2013 (PubMed 23541122): four neurochemical domains — reward/dopamine, stress/cortisol, immunity, social/oxytocin
- Saarikallio & Erkkilä 2007: seven mood regulation strategies (revival, entertainment, solace, mental work, diversion, discharge, strong sensation)
- Taruffi et al. 2017 (Nature srep14396): sad music is the strongest DMN activator for self-referential processing
- Wilkins et al. 2014 (Nature srep6130): preferred music engages DMN for introspective processing
- Barrett et al. 2023 (PMC11907061): nostalgia activates DMN + reward networks
- Keeler et al. 2015 (PMC4585277): group music elevates oxytocin
- Salimpoor et al. 2011 (Nature nn.2726): dopamine release during music anticipation/experience
- Huron 2011 (Sage 1029864911401171): prolactin consolation theory for sad music
- Bretherton et al. 2019: 60 BPM increases vagal modulation
- Thoma et al. 2013 (PMC3734071): music accelerates autonomic recovery

**Decision:** Replaced 3 binary frozensets with a `MOOD_AFFINITY` dict — 64 tags, each with (para, symp, grnd) weights. "Motivational" = (0.00, 0.65, 0.25), not (0, 1.0, 0). "Sad" = (0.60, 0.00, 0.55), not (1.0, 0, 0). "Spiritual" = (0.65, 0.00, 0.55), not neutral 0.5. `compute_mood_score` now returns a weighted average instead of a binary fraction.
**Effect:** Motivational songs properly deprioritized for parasympathetic states. Spiritual/devotional songs now correctly score parasympathetic. Cross-dimensional contributions (sad → grounding) are captured.

### Era hard cap on cohesion similarity
**What we noticed:** Baadshah O Baadshah (1999) kept appearing in 2010s playlists. Era similarity was 0.0000 (correctly penalized by Gaussian decay), but era weight was only 20% of cohesion. Other dimensions (mood 1.0, BPM 0.98, genre 0.47) compensated, giving total similarity 0.65.
**Research basis:** The era cohesion research doc states "production era changes are more jarring than cultural differences." A 1999 song in a 2013 cluster sounds wrong regardless of mood/tempo match.
**Decision:** When `era_sim < 0.05` (different production eras), cap total pairwise similarity at 0.30. This prevents any dimension from compensating for a fundamental era mismatch.
**Effect:** Baadshah eliminated from 2010s playlists. Tested against all 9 pre-2005 high-sympathetic songs — all correctly excluded from modern clusters.

### System hardening (10 issues)
**What we fixed:**
- Spotify availability check batched to 50 URIs per call (was unbounded)
- Metadata fallback warns user about time estimate before proceeding
- URI validation before any Spotify API call
- LLM 60-second timeout on both OpenAI and Anthropic providers
- Essentia logs actual exceptions instead of swallowing them
- WHOOP pagination validates response structure before processing
- Classification merge warns on missing critical fields (BPM, energy)
- Global Spotify rate limit handler with exponential backoff
- `fetch_track_metadata` fills ALL missing metadata, not just engaged songs
- Spotify API rate limit from unthrottled fallback fixed with 3-second delay between retries

### Onboarding pipeline
**What we built:** `onboard` CLI command — single command for new users. Handles Spotify auth, library sync, extended history import, metadata fetch, LLM classification, Essentia analysis, score computation, and WHOOP sync in sequence.
**Documentation:** Created `docs/ONBOARDING.md` with step-by-step instructions.
**Bug fixed:** `fetch_track_metadata` was only filling metadata for songs with 5+ meaningful listens. New users need ALL songs to have metadata before classification can run.

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
The `--force` flag wiped Essentia data. Ran it twice knowing the bug existed instead of fixing first. Cost real money and hours. Always fix first, run second.

### Test on unseen data before declaring victory
Tuned on 25 songs (72%). Fresh 34-song set: 56%. The tuning set was blind to a fundamental gap (missing Essentia for 98% of library).

### Know when to stop optimizing
83% product accuracy, 93% within one bucket, 86% safety. Remaining gap needs data (more audio clips), personalization (feedback loop), or neural models. None are classification parameter improvements.

---

## WHOOP Insights

WHOOP research and analysis moved to a dedicated repository: [whoop-2.0](https://github.com/pranavjain20/whoop-2.0) (private).

---

## Sleep Quality Dampener — Recovery Delta Is Not Enough

### The observation

Mar 25: Recovery 83% (HRV 55ms, +25pp delta from yesterday). System's continuous baseline scaling leaned hard toward energy (z=0.9). But sleep was 6.9h with only 2.8h deep+REM — both below personal baseline means (deep 1.3h vs mean 1.5h, REM 1.4h vs mean 1.7h). The user didn't feel as energetic as 83% suggests.

Mar 24 (day before): Recovery 58% but sleep was 8.1h with 4.1h deep+REM — well above personal means. User felt fresher on the 58% day than the 83% day.

### The hypothesis

Recovery delta is HRV-driven. HRV is a biomarker of autonomic balance, not a direct cause of how you feel (Laborde 2017, Thayer 2012). HRV can rebound overnight while sleep architecture stays poor (Grimaldi 2019 — HRV rebounded during recovery sleep but SWS did not). When recovery delta says "energy up" but sleep says "you didn't actually rest well," the system was trusting the wrong signal.

### The research

Four parallel research agents investigated:

1. **Sleep-recovery mismatch:** HRV and sleep architecture recover through independent mechanisms. Sleep architecture is a better predictor of subjective state (Vitale 2015: deep sleep % predicted wellness more strongly than HRV; Hynynen 2011: HRV-subjective recovery correlation only r=0.2-0.3).

2. **WHOOP algorithm:** Recovery is ~85% HRV-driven (Marco Altini, Rob ter Horst independent analyses). Sleep stage composition does NOT directly feed into the score — only total duration vs need. Architecture deficits are invisible.

3. **HRV and feeling:** HRV is downstream (good sleep → high HRV, not high HRV → feel good). High HRV + feel terrible: documented in overtraining (Plews 2013), alcohol, illness onset. Low HRV + feel great: post-exercise, excitement, good sleep despite autonomic stress.

4. **What determines how you feel (hierarchy):** Sleep architecture > sleep continuity > circadian alignment > cortisol awakening response > HRV. This hierarchy is consistent across multiple studies.

### What we changed

Added continuous sleep quality z-score as a second input to baseline profile scaling. Sleep quality is computed from actual deep/REM durations relative to personal baselines — not binary deficit/adequate flags.

**The blend:** `z_effective = 0.35 * z_recovery + 0.65 * z_sleep`

Sleep gets 65% weight, recovery delta gets 35%. This ratio comes from the research: sleep architecture correlates with next-morning subjective state at r=0.4-0.6 (Vitale 2015, PMC6456824), while HRV correlates at r=0.2-0.3 (Hynynen 2011). That's roughly a 2:1 ratio in favor of sleep. When both signals agree, the effect is reinforced. When they conflict, sleep dominates — because sleep is what actually determines how you feel.

### The before/after

**Today (recovery 83%, mediocre sleep):**
- Without dampener: z=0.9 → para=0.11, symp=0.59 (strong energy lean — wrong)
- With dampener: z_eff=-0.1 → para=0.17, symp=0.48 (slightly calming — honest, sleep was below average)

**Yesterday (recovery 58%, great sleep):**
- Without dampener: z=0.7 → para=0.11, symp=0.59
- With dampener: z_eff=0.8 → para=0.11, symp=0.60 (reinforced energy — both signals agree)

### Why this matters

This is the most significant insight from building Attuned: **WHOOP's recovery score optimizes for autonomic readiness, but playlists should optimize for subjective state. These overlap most of the time, but when they diverge, sleep architecture is the better predictor of how someone actually feels.** The sleep quality dampener ensures the system respects both signals rather than blindly following HRV.

---

## Anchor Vibe Outlier Detection — When a Song Doesn't Belong Despite Matching on Paper

### The observation

Today's playlist ("Stay Sharp", baseline leaning slightly calm) had 19 warm melodic songs — Mast Magan, Bulleya, Raataan Lambiyan, Humsafar — and then G.O.A.T. by Diljit Dosanjh. Punjabi party banger. It sounded wrong.

The data confirmed the intuition. G.O.A.T.'s properties vs the cluster:

| | G.O.A.T. | Cluster average | Gap |
|---|---|---|---|
| Energy | 0.83 | 0.40 | +2.9 SD |
| Danceability | 0.90 | 0.58 | +2.7 SD |
| Acousticness | 0.10 | 0.47 | -2.0 SD |

G.O.A.T. was the ONLY song in the playlist that was an outlier on 3 dimensions simultaneously. No other song exceeded 2. This is the quantifiable difference: being off on one dimension is variety. Being off on two is unusual. Being off on all three vibe dimensions means the song sounds fundamentally different — it's a different genre of feel, not just variation.

### Why it got through in the first place

G.O.A.T. got in as a recently-played anchor (guaranteed slot). But even through normal cohesion, it survived because:

1. **BPM match was perfect.** G.O.A.T. is BPM=89. Mast Magan is also BPM=89. That perfect match contributed 0.20 to similarity on its own.
2. **Era matched.** Both 2010s-2020s. Another 0.12.
3. **Genre partially overlapped.** Punjabi/hip-hop vs Bollywood/pop share some tags.

Combined: 0.37 total similarity despite zero overlap on how the music FEELS. The cohesion threshold was 0.15. BPM + era alone got it past the gate.

The root cause: cohesion weights gave 75% to category dimensions (genre, mood, BPM, era) and only 25% to vibe dimensions (energy, acousticness, danceability, valence). Energy at 10%, acousticness at 5%, danceability at 5% — even scoring 0.0 on all three, the maximum penalty was only 0.20. Not enough to override BPM.

### The vibe gap is quantifiable

Computed average vibe similarity (energy + acousticness + danceability) for G.O.A.T. vs cluster songs, and cluster songs vs each other:

- **G.O.A.T. → cluster:** avg vibe similarity 0.055 - 0.149 (mean ~0.08)
- **Cluster → cluster:** avg vibe similarity 0.622 - 0.934 (mean ~0.77)

A 10x gap. The songs that belong together have 0.62+ vibe similarity. G.O.A.T. has 0.08.

### What was tried and failed

**Attempt 1: Rebalance cohesion weights.** Shifted weight from BPM/era to energy/dance/acoustic. Didn't work. G.O.A.T. and Mast Magan both BPM=89 — that perfect match contributed 0.15+ on its own. Even with reduced BPM weight, the similarity stayed above 0.28 (well above the 0.15 threshold). The problem wasn't weight balance — a single dimension match was a lifeline that no rebalancing could cut.

**Attempt 2: Ratio-based anchor threshold (75% of cluster mean).** The idea: if an anchor's average similarity to the cluster is below 75% of the cluster's internal mean, drop it. The cluster mean was 0.667, so the threshold was 0.500. Too aggressive — dropped 4 of 5 anchors in baseline, including Uff Teri Adaa (0.370, ratio 0.55) and Waiting For Love (0.365, ratio 0.55) which the user was happy with. Tried 0.55 — still dropped Move, I Ain't Worried, and Bernie's Chalisa (a devotional song that should absolutely be in a fatigue playlist). The ratio approach can't distinguish "slightly different but fine" from "fundamentally doesn't belong."

**Attempt 3: 2-dimension vibe outlier.** Drop anchors that are >1.5 SD from cluster mean on 2+ vibe dimensions. Better concept, but dropped 3 devotional anchors in the fatigue playlist (Bernie's Chalisa, Shiv Kailash, Hanuman Chalisa — outliers on 2 dimensions because they're extremely calm in a cluster that includes some moderate-energy Bollywood). These are exactly the songs that SHOULD be in a fatigue playlist. The 2-dim threshold can't distinguish "extreme in the right direction" from "extreme in the wrong direction."

### What worked

Two complementary mechanisms:

**1. Vibe hard cap (pairwise level).** When the average energy + acousticness + danceability similarity between two songs drops below 0.15, cap total pairwise similarity at 0.30 — regardless of how well BPM, genre, or era match. Same pattern as the era hard cap. This prevents vibe-incompatible songs from building false cohesion through category dimensions.

**2. 3-dimension anchor outlier (cluster level).** An anchor is only dropped when it's an outlier on ALL THREE vibe dimensions (energy AND acousticness AND danceability, each >1.5 SD from cluster mean). G.O.A.T. was the only song at 3 dimensions across all tested states. Devotional songs in fatigue playlists were at 2 dimensions — kept as anchors. And even if an anchor loses guaranteed status, it can still make the playlist through normal neuro scoring if it genuinely fits (Bernie's Chalisa scored 1.000 on fatigue neuro match — it made the playlist without anchor help).

### Testing across states

| State | Anchors | Dropped | Correct? |
|---|---|---|---|
| Baseline (today) | 5 | G.O.A.T. (3-dim outlier) | Yes — party banger in calm cluster |
| Baseline (yesterday) | 5 | None | Yes — all fit the energetic cluster |
| Fatigue (Mar 21) | 5 | Bernie's Chalisa (3-dim, but still makes playlist via score) | Yes — lost anchor status but earned its spot |
| Peak (Mar 22) | 5 | None | Yes — all high-energy, fits peak cluster |

### The deeper insight

The cohesion system has two layers that serve different purposes:
- **Category dimensions** (genre, mood, BPM, era) define what the music IS — Bollywood vs Western, fast vs slow, old vs new
- **Vibe dimensions** (energy, acousticness, danceability) define how the music FEELS — quiet acoustic vs loud electronic, danceable vs still, intimate vs produced

Both matter for coherence, but either can be a dealbreaker. A 1999 Bollywood song in a 2015 cluster is jarring (era gap — handled by era hard cap). A party banger in an acoustic ballad cluster is jarring (vibe gap — now handled by vibe hard cap + outlier detection). The system needs hard floors on both, not just weights that can be overridden by strong matches on other dimensions.

---

## Day 11: Playlist Freshness Uses Latest-Per-Day Only

### The observation

After iterating on playlists 4 times on Mar 25 (generate, evaluate, tweak, regenerate), the freshness/repeat mechanism was treating all 4 iterations as separate playlists. Songs from iteration 1 (later dropped in iteration 4) still counted as "recently played," polluting the rotation. Result: the "recently used" set was 4x larger than it should be, reducing effective song rotation.

### The decision

`get_recent_playlist_track_uris()` and `get_consecutive_playlist_days()` now query only the latest playlist per date (`ORDER BY id DESC LIMIT 1`). Earlier iterations are ignored for freshness/repeat purposes.

### Why this is correct

When iterating during a session, intermediate playlists are drafts. The user hears and evaluates the final one. The freshness mechanism should model what the user actually experienced, not every draft the system produced. A song dropped from iteration 1 shouldn't block it from appearing tomorrow — the user never heard it in that context.

### Effect

With a 1,188-song library, the hard cap is 3 days (bangers: 2). Previously, the inflated "recently used" set meant songs were effectively blocked for longer because they appeared in draft playlists they were later removed from. Now the rotation reflects actual listening.

---

## Day 11: Days-Since-Last-Appearance Replaces Consecutive-Day Streak

### The observation

I'll Do The Talking Tonight appeared on Mar 24, skipped Mar 25, and returned Mar 26. With the old consecutive-streak counter, the gap on Mar 25 reset the streak to 0 — the song looked "fresh" even though it was just 2 days old. The hard cap only blocked songs with unbroken streaks, so a song could appear every other day indefinitely.

### The decision

Replaced `get_consecutive_playlist_days()` with `get_days_since_last_appearance()`. The hard cap now checks when a song last appeared, not whether it appeared on consecutive days. A song that appeared 2 days ago is blocked regardless of whether it was in yesterday's playlist.

### Why this is correct

The listener's experience is "I heard this recently" — whether it was yesterday or 2 days ago. A 1-day gap doesn't make a song feel fresh. The rotation should be a function of library depth (log2-scaled), not streak length.

### Effect

39 songs blocked per playlist (was ~5 with consecutive-streak). 15 new songs per playlist vs previous day. Score floor remained high (0.900). Library depth of 1,188 songs gives a 3-day minimum gap — enough rotation without sacrificing quality.

---

## Day 11: Bollywood Motivational Songs Excluded (Scene-Tied Context)

### The observation

Chak De India and Toofan kept appearing in baseline "Fuel Up" playlists. Musically they match (high energy, uplifting) but they're Bollywood sports anthems — hearing them evokes the movie scene (hockey team training, boxing montage), not a general morning energy boost.

### The decision

Bollywood motivational songs are excluded from all playlists except peak_readiness. English motivational songs (Hall of Fame, Lose Yourself) are allowed through — Western pop isn't written for specific film scenes, so they don't carry the same contextual baggage.

Detection has two layers:
1. **Tag-based**: mood includes "motivational" AND genre is Bollywood/Punjabi/soundtrack → auto-excluded (catches 15 songs)
2. **Manual override**: `_MOTIVATIONAL_OVERRIDES` set for songs the LLM missed tagging (Halla Bol, Chak Lein De — tagged "uplifting, energetic" but are clearly sports anthems)

### Why Bollywood specifically

Bollywood music is written for a movie scene. A motivational Bollywood song = someone is training, fighting, overcoming odds. That's a specific physical context (gym, workout) that doesn't match a morning recovery playlist. English motivational is more abstract — "you can do anything" rather than "the hockey team is winning." The scene-specificity is the key distinction, not the language.

### Effect

16 Bollywood motivational songs excluded from non-peak playlists. English motivational songs still available. Manual override catches the LLM's blind spots without needing reclassification.

---

## Day 12: From State Machine to Continuous Intelligence

### The observation that triggered this

Mar 27: Recovery 44% (down from 54%), HRV 39.4ms (down from 42.5ms), RHR 57 (up from 55), deep sleep 1.3h (down from 2.3h). Every single metric is worse than yesterday. The system classified both days as "baseline" and produced similar playlists — romantic reflective Bollywood.

The recovery delta modifier caught the -10pp drop and shifted the profile slightly calmer (Para 0.22 vs 0.15). But the HRV decline, RHR increase, and sleep quality drop were invisible to the playlist. Only recovery delta was used continuously. Everything else was a binary gate.

### The deeper problem: brackets vs intelligence

The current architecture is a state machine:
1. Classify into 7 discrete states via if/elif thresholds
2. Look up the state's static neuro profile
3. Apply recovery delta modifier (continuous, but only for baseline state)
4. Apply sleep dampener (continuous, but only for baseline state)

This means:
- A recovery of 39% triggers poor_recovery; 41% does not. Cliff.
- Deep sleep at mean-1.01*SD is "adequate"; at mean-0.99*SD is not. Cliff.
- HRV decline and RHR increase are computed but only used as boolean gates for peak readiness. They don't move the playlist dial at all for any other state.

Two days with identical state classification get nearly identical playlists:

| Day A | Day B | Same state? |
|-------|-------|-------------|
| Recovery 44%, HRV declining, RHR rising, deep 1.3h/5h total | Recovery 44%, HRV stable, RHR stable, deep 1.3h/9h total | Yes → similar playlists |

These need different playlists. Day A is a body under stress (everything declining). Day B is a relaxed body that didn't recover well (stable vitals, just low deep ratio).

The key insight: **1.5h deep sleep in a 5h night ≠ 1.5h deep sleep in a 9h night.** The body prioritized deep sleep in the short night (high deep ratio = sleep pressure response). Same absolute deep, completely different physiological context. Both the absolute amount AND the ratio AND the total sleep duration matter.

### What the research says about signal strength

**Correlation with subjective state (strongest → weakest):**

| Signal | Strength | Source |
|--------|----------|--------|
| Sleep architecture quality (efficiency + deep/REM ratios) | r = 0.4-0.6 | PMC6456824, Nature Sci Rep 2024 |
| HRV (ln_rmssd) | r = 0.68 with fatigue, r = 0.46 with stress | JSSM 2023, Lundstrom 2024 |
| RHR | Meaningful only combined with HRV (multiplicative) | System Logic research |
| WHOOP Recovery composite | r = -0.05 to -0.18 with validated stress scales | Loses raw signal fidelity |
| Sleep debt | Cognitive impairment >5h cumulative | Van Dongen & Dinges 2003 |

**Key research insights:**
- Multi-day trends (7-day rolling averages) are more predictive than single-day readings (Plews et al., 2012)
- Day-over-day deltas predict subjective experience better than absolute position
- HRV decline + RHR rise together is multiplicative — stronger signal than either alone
- Deep sleep deficit + REM deficit indicate different problems requiring different music
- Subjective state recovers after 1 good night; objective impairment takes 9+ days (Dinges/Belenky)
- Sleep efficiency is the single strongest objective correlate of subjective sleep quality
- Sleep quality/architecture matters more than quantity for subjective state — shifting 30min from light to deep improves positive affect by +0.38 regardless of total duration (PMC12208346)

### The new architecture: continuous weighted function

**Current flow:**
```
metrics → state classification (7 buckets) → static profile → modifiers → playlist
```

**New flow:**
```
metrics → continuous scoring function → neuro profile → playlist
         ↘ state label (for display/description only)
```

The state classifier still runs for the human-readable label ("Rest & Repair" vs "Fuel Up"). But the playlist profile is computed directly from the weighted metrics, not derived from the state label.

### Input signals

Every metric becomes a z-score against the user's personal 30-day baseline:

| Signal | What it measures | z = -2 means | z = +2 means |
|--------|-----------------|--------------|--------------|
| recovery_z | Today's recovery vs personal mean | Very bad day | Great day |
| recovery_delta_z | Today - yesterday recovery, vs personal delta SD | Big drop from yesterday | Big jump |
| hrv_z | Today's ln_rmssd vs 30-day mean | HRV crashed | HRV elevated |
| hrv_delta_z | Today - yesterday HRV, vs personal delta SD | HRV declining | HRV rising |
| rhr_z | Today's RHR vs 30-day mean (inverted: high RHR = negative) | RHR very elevated (bad) | RHR low (good) |
| rhr_delta_z | Today - yesterday RHR (inverted) | RHR rising (bad) | RHR dropping (good) |
| deep_sleep_z | Deep sleep ms vs personal mean | Very low deep | Excellent deep |
| deep_ratio_z | Deep/total vs personal ratio mean | Low ratio (long sleep, little deep) | High ratio (body prioritized deep) |
| rem_sleep_z | REM ms vs personal mean | Very low REM | Excellent REM |
| sleep_efficiency_z | Last night's efficiency vs personal mean | Poor efficiency | Excellent efficiency |
| sleep_debt_z | 7-day debt vs personal debt mean (inverted) | Debt very high | Low debt |
| hrv_trend_z | 7-day HRV slope, normalized | Declining trend | Rising trend |

### The weighting table

Each z-score pushes the neuro profile toward parasympathetic (calming), sympathetic (energy), or grounding (stability). The weight determines how much push per unit of z.

| Signal | Para weight | Symp weight | Grnd weight | Rationale |
|--------|-------------|-------------|-------------|-----------|
| recovery_z | -0.15 | +0.15 | 0 | Low recovery → more calming; high → more energy. Largest weight because it's the most integrated signal. |
| recovery_delta_z | -0.10 | +0.10 | 0 | Yesterday-to-today change. A 10pp drop should move the dial more than a steady 44%. |
| hrv_z | -0.12 | +0.12 | 0 | Second strongest predictor (r=0.68). Low HRV = autonomic nervous system needs support. |
| hrv_delta_z | -0.05 | +0.05 | 0 | Direction of HRV change. Smaller than absolute because trends > single-day (Plews 2012). |
| rhr_z (inverted) | -0.08 | +0.08 | 0 | Elevated RHR = sympathetic overdrive. Calm it down. Only meaningful combined with HRV. |
| deep_sleep_z | -0.08 | +0.05 | -0.03 | Low deep → physical recovery need (parasympathetic + grounding). |
| deep_ratio_z | 0 | 0 | ±0.05 | High ratio with short total = sleep pressure (grounding). High ratio with long total = great night (neutral). |
| rem_sleep_z | -0.03 | 0 | -0.07 | Low REM → emotional processing need → grounding, not parasympathetic. This is why grounding weight is higher. |
| sleep_efficiency_z | -0.08 | +0.08 | 0 | Strongest single subjective correlate. Poor efficiency = body didn't rest despite time in bed. |
| sleep_debt_z (inverted) | -0.05 | +0.03 | -0.02 | High accumulated debt → calming + grounding. Accumulated, so grounding is part of the response. |
| hrv_trend_z | -0.05 | +0.05 | 0 | Multi-day HRV direction. Declining for days is worse than one bad reading. |

**Negative weight for para/grnd = bad z-score increases that component.** E.g., recovery_z = -1.0 (bad day) × para weight -0.15 = +0.15 added to parasympathetic. The double negative produces the intuitive result: bad metrics push toward calming.

### How the function works

1. Compute all 12 z-scores from today's metrics + 30-day baselines
2. Start from neutral: `{para: 0.33, symp: 0.34, grnd: 0.33}`
3. For each signal: add `z * weight` to each component
4. Check interaction terms:
   - If `hrv_z` AND `rhr_z` both < -1.0 → additional +0.05 to para (both metrics bad = multiplicative stress signal)
   - If `deep_sleep_z` AND `rem_sleep_z` both < -1.0 → additional +0.05 to para (complete sleep failure)
5. Clamp each component to [0.0, 1.0]
6. Normalize so para + symp + grnd = 1.0

### Worked example: today (Mar 27) vs yesterday (Mar 26)

**Yesterday (Mar 26):** Recovery 54%, HRV 42.5ms, RHR 55, deep 2.3h, REM 1.9h
- recovery_z ≈ -0.3, hrv_z ≈ -0.1, rhr_z ≈ 0.0, deep_z ≈ +0.8, rem_z ≈ +0.1
- recovery_delta_z ≈ -1.2 (dropped from 83% two days ago)
- Result: ~{para: 0.22, symp: 0.42, grnd: 0.36} — baseline, leaning slightly calmer
- Playlist: Hawayein, Pani Da Rang — gentle romantic Bollywood

**Today (Mar 27):** Recovery 44%, HRV 39.4ms, RHR 57, deep 1.3h, REM 1.7h
- recovery_z ≈ -0.7, hrv_z ≈ -1.0, rhr_z ≈ -0.4, deep_z ≈ -0.5, rem_z ≈ 0.0
- recovery_delta_z ≈ -0.5 (dropped 10pp from yesterday)
- Interaction: hrv_z (-1.0) × rhr_z (-0.4) — HRV bad but RHR not quite at -1.0, so interaction doesn't trigger
- Result: ~{para: 0.38, symp: 0.30, grnd: 0.32} — noticeably calmer, more grounded
- Expected playlist: slower, more acoustic, more grounding than yesterday. Not as extreme as accumulated fatigue (para 0.95) but a clear shift.

**The difference is visible:** yesterday para=0.22, today para=0.38. That's a 73% increase in parasympathetic weight driven by HRV decline (-1.0 z), RHR increase, and worse deep sleep. Every metric that got worse moved the dial.

### What this means for the product

The playlist becomes a continuous response to the body's state, not a bucketed reaction. Small changes in metrics produce small changes in playlist character. Large changes produce large shifts. No cliffs, no gates, no "you're either baseline or fatigue with nothing in between."

The state label still exists for the user ("Rest & Repair" vs "Fuel Up") but the actual music selection is driven by the continuous profile. Two "baseline" days can have meaningfully different playlists if the underlying metrics differ.

### Status

Architecture designed and implemented. `intelligence/continuous_profile.py` created, wired into `matching/generator.py`. The state classifier still runs for display labels but the neuro profile is now driven entirely by the continuous function. 1,048 tests passing.

### Before/After: Mar 27 Playlist Comparison

**Today's metrics:** Recovery 44% (↓10pp), HRV 39.4ms (↓3.1ms), RHR 57 (↑2), deep 1.3h (↓1.0h), REM 1.7h (↓0.2h), sleep efficiency 92% (good), sleep debt 26.2h (high).

**Z-scores computed by the continuous function:**

| Signal | z-score | Interpretation |
|--------|---------|----------------|
| recovery_z | -0.56 | Below average, not extreme |
| recovery_delta_z | -0.33 | Moderate drop from yesterday |
| hrv_z | **-0.97** | Almost 1 SD below — significant |
| hrv_delta_z | -0.56 | HRV declining day-over-day |
| rhr_z | -0.36 | RHR slightly elevated |
| rhr_delta_z | **-0.70** | RHR rose notably |
| deep_sleep_z | **-0.97** | Deep sleep almost 1 SD below |
| deep_ratio_z | **-0.97** | Low ratio (short sleep + low deep) |
| rem_sleep_z | -0.04 | REM was fine |
| sleep_efficiency_z | **+0.58** | Actually good — body slept efficiently |
| sleep_debt_z | **-0.86** | Accumulated debt is high |
| hrv_trend_z | -0.66 | Multi-day HRV declining |

9 of 12 signals are negative. Only sleep efficiency is positive. The body is clearly stressed across multiple dimensions — this isn't just "a bad recovery score," it's declining HRV, rising RHR, poor deep sleep, and accumulated debt all at once.

**Profile comparison:**

| | Previous (state machine) | New (continuous) |
|--|--------------------------|------------------|
| **Para** | 0.22 | **0.64** |
| **Symp** | 0.42 | **0.00** |
| **Grnd** | 0.36 | **0.36** |
| **Name** | Fuel Up | Rest & Repair |
| **Character** | Romantic, reflective Bollywood | Devotional, deeply calming |

**Previous playlist (state machine — Para 0.22/Symp 0.42/Grnd 0.36):**

| # | Song | Artist |
|---|------|--------|
| 1 | Saudebazi (Encore) | Pritam |
| 2 | Khuda Jaane | Vishal-Shekhar |
| 3 | Piya O Re Piya | Atif Aslam |
| 4 | Bheegi Si Bhaagi Si | Pritam |
| 5 | Hawayein | Pritam |
| 6 | Pani Da Rang | Ayushmann Khurrana |
| 7 | Main Agar Kahoon | Sonu Nigam |
| 8 | Saiyaara | Sohail Sen |
| 9 | Main Rang Sharbaton Ka | Atif Aslam |
| 10 | Lehra Do (83) | Pritam |
| 11 | Kun Faya Kun | A.R. Rahman |
| 12 | Rabba | Mohit Chauhan |
| 13 | Mann Mera | Gajendra Verma |
| 14 | Tu Chahiye | Pritam |
| 15 | Aashiyan | Pritam |
| 16 | Mere Bina | Pritam |
| 17 | Teri Jhuki Nazar | Pritam |
| 18 | Hosanna | A.R. Rahman |
| 19 | Te Amo (Duet) | Pritam |
| 20 | Jab Mila Tu | Vishal-Shekhar |

Romantic Bollywood — gentle but with energy. Hawayein, Pani Da Rang, Saiyaara are sweet, moderately upbeat. This is "I'm fine, just a bit tired" music. The system saw baseline + slight recovery drop and produced a mildly calmer baseline playlist.

**New playlist (continuous — Para 0.64/Symp 0.00/Grnd 0.36):**

| # | Song | Artist |
|---|------|--------|
| 1 | Bernie's Chalisa | Krishna Das |
| 2 | Shiv Kailash (Live) | Rishab Rikhiram Sharma |
| 3 | Hanuman Chalisa (Lo-fi) | Rasraj Ji Maharaj |
| 4 | Kun Faya Kun | A.R. Rahman |
| 5 | Ganpati Aarti | Rohan Vinayak |
| 6 | Khwaja Mere Khwaja | A.R. Rahman |
| 7 | Bheegi Si Bhaagi Si | Pritam |
| 8 | Kabira | Pritam |
| 9 | Saathiyaa | Shreya Ghoshal |
| 10 | Piya O Re Piya | Atif Aslam |
| 11 | Maula Mere Maula | Roop Kumar Rathod |
| 12 | Main Agar Kahoon | Sonu Nigam |
| 13 | Tu Chahiye | Pritam |
| 14 | Surili Akhiyon Wale | Rahat Fateh Ali Khan |
| 15 | Baatein Kuch Ankahee | Pritam |
| 16 | Dildaara (Stand By Me) | Shafqat Amanat Ali |
| 17 | Kahin To | Rashid Ali |
| 18 | Phir Le Aya Dil (Reprise) | Pritam |
| 19 | Channa Mereya | Pritam |
| 20 | Saibo | Sachin-Jigar |

Deeply calming. Opens with devotional (Krishna Das, Hanuman Chalisa, Kun Faya Kun, Khwaja Mere Khwaja) then transitions to slow romantic Bollywood (Kabira, Channa Mereya, Saibo). Zero sympathetic energy. The system read 9 negative signals and said "your body needs deep rest, not romantic energy."

### Why the new playlist is better

1. **The old system was blind to 10 of 12 signals.** It only used recovery delta (-10pp → slight calmer nudge). The HRV crash (-0.97 z), RHR spike (-0.70 z), deep sleep deficit (-0.97 z), and accumulated debt (-0.86 z) were completely invisible. These are strong stress signals the old playlist ignored.

2. **The genre shift is data-driven.** Devotional music (Krishna Das, Khwaja Mere Khwaja) isn't random — it's the highest-scoring parasympathetic + grounding music in the library. The old system never reached these songs because Symp 0.42 kept pulling toward upbeat romantic tracks.

3. **8 shared songs between old and new** — Piya O Re Piya, Bheegi Si Bhaagi Si, Main Agar Kahoon, Tu Chahiye, Kun Faya Kun, Kabira, Saibo (via anchors/high scores). The new system didn't discard the old playlist entirely — it shifted it calmer while keeping the strongest matches.

### Open question: is Para 0.64 too extreme?

The user described today as "baseline but worse than yesterday" — not "I need to lie down." Para 0.64 / Symp 0.00 is closer to accumulated fatigue (Para 0.95) than baseline (Para 0.15). The previous Para 0.22 was arguably too energetic (ignoring 10 signals). The truth might be Para 0.35-0.45.

### Weight sensitivity calibration

Initial run produced Para 0.64 — accumulated-fatigue territory for a 44% day. Too extreme. Root cause: the weights were designed per-signal ("recovery pushes para by 0.15 per z-unit") but with 12 correlated signals, the maximum combined para push is `sum(all para weights) × max_z = 0.83 × 2.5 = 2.075` — 6x the entire profile range. Weights were calibrated for a 1-2 signal system, not 12.

The fix separates two independent concepts:
1. **Relative importance** (the weight table): recovery matters more than RHR delta. Research-backed, unchanged.
2. **Absolute magnitude** (`WEIGHT_SENSITIVITY`): how much should the worst day differ from the best? Depends on signal count and correlation.

Working backwards: worst day (all z = -2.0) should produce Para ~0.65. Math: `sensitivity = 0.35 / (0.83 × 2.0) ≈ 0.21`. Set to 0.20.

**Tuned profile range:**

| Day | Recovery | Para | Symp | Grnd |
|-----|----------|------|------|------|
| Great | 85% | 0.21 | 0.46 | 0.32 |
| Okay (yesterday) | 54% | 0.36 | 0.32 | 0.33 |
| Bad (today) | 44% | 0.40 | 0.26 | 0.34 |
| Terrible | 15% | 0.59 | 0.06 | 0.35 |

The sensitivity knob keeps the weight table readable (relative importance visible) while calibrating the output range to the system's dimensionality. 12 correlated signals need ~5x smaller individual impact than 2-3 independent signals.

### Final playlist (tuned — Para 0.40 / Symp 0.26 / Grnd 0.34)

Mix of devotional anchors (recently listened: Shiv Kailash, Hanuman Chalisa), gentle English (Let Her Go), and romantic Bollywood (Hawayein, Bheegi Si Bhaagi Si, Channa Mereya). 13 songs overlap with the old state-machine playlist, but the overall character is calmer — proportional to the metric decline, not a genre flip.

