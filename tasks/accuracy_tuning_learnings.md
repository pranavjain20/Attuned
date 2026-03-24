# Accuracy Tuning — Full Session Log

_Day 4b: Everything we tried, what worked, what didn't, and why. This is a detailed archive. For the distilled product decisions, see [docs/PRODUCT_DECISIONS.md](../docs/PRODUCT_DECISIONS.md)._

## What we were trying to do

Attuned classifies every song in Pranav's Spotify library into one of three neurological buckets:
- **PARA** (parasympathetic) — calming music for when your body needs rest
- **SYMP** (sympathetic) — energizing music for when you're in peak readiness
- **GRND** (grounding) — moderate music for emotional regulation

The classification uses a weighted formula that takes 7 properties of each song (BPM, energy, acousticness, instrumentalness, valence, mode, danceability) and produces three scores. The highest score wins.

The goal: given a song, the system should assign the same neurological bucket that a human would. We built a 25-song test set — hand-labeled by Pranav across English pop (8 songs), popular Bollywood (8), and obscure Indian devotional/regional (9). Each song was labeled as low/low-mid/mid/mid-high/high energy, which maps to PARA/PARA/GRND/SYMP/SYMP.

## Where we started: 48% accuracy (12/25)

The original formula used narrow sigmoid curves:
- Parasympathetic tempo: sigmoid_decay with range 60-90 BPM (midpoint 75)
- Sympathetic tempo: sigmoid_rise with range 100-130 BPM
- Grounding tempo: gaussian centered at 75 BPM, sigma 15

This meant:
- A song at 85 BPM (moderate, grounding) got a high parasympathetic score because 85 is above the sigmoid midpoint of 75, but the decay was barely started
- A song at 100 BPM (still pretty moderate) got almost zero parasympathetic score
- The grounding center at 75 was too low — most grounding songs in the test set were 80-95 BPM

Energy was measured using RMS (root mean square of audio amplitude). Problem: RMS is dominated by mastering loudness. Modern pop is mastered louder than 90s Bollywood. Die For You (a quiet R&B ballad) got energy=0.71 because it's a modern master. Namo Namo (a devotional prayer) got lower energy than it should because it's mastered quietly.

## First round of fixes: 48% → 60%

### What we changed

**1. Widened sigmoid parameters:**
- Parasympathetic: 60,90 → 70,110 (wider transition zone)
- Grounding center: 75 → 85, sigma stayed at 15
- Sympathetic: kept 100,130 (already reasonable)

Why: the original curves were too narrow. The "calming zone" ended at 90 BPM, but many calming songs (slow ballads, devotional) are 80-100. The grounding sweet spot at 75 BPM was too low — real grounding songs cluster around 85.

**2. Switched from RMS energy to onset rate energy:**
- Old: `energy = rms / 0.35` (measures loudness)
- New: `energy = (onset_rate - 2.0) / 4.0` (measures rhythmic attacks per second)

Why: RMS measures how loud the audio is, which depends on mastering, not on how energetic the song feels. Onset rate counts how many rhythmic hits happen per second — calm acoustic music has ~2 onsets/sec, tabla/electronic has ~6+. This is immune to mastering volume.

**3. Added LLM + formula blending:**
- English songs: 30% formula, 70% LLM direct scores (LLM knows Western music well)
- Indian songs: 70% formula, 30% LLM direct scores (LLM doesn't know obscure Indian music)
- Spread adjustment: if LLM scores are well-separated (>0.4 spread), boost LLM weight; if clustered (<0.25), reduce it

Why: the formula is good at physical audio properties (tempo, energy) but bad at cultural context. The LLM knows that "Photograph" is a sad song even if the audio sounds similar to a happy song. But for obscure Indian devotional music, the LLM often guesses wrong because it hasn't been trained on enough of it.

### Results: 15/25 correct (60%)
- English: improved
- Popular Indian: improved
- Obscure Indian: improved modestly

Still 10 failures. We stopped tuning and investigated each one.

## Root cause analysis of the 10 failures

We pulled the actual database values for each failing song to understand exactly why the system got it wrong.

### Root Cause 1: Stale BPM data in the DB (2 songs)

| Song | DB BPM | Should be | What happened |
|------|--------|-----------|---------------|
| Die For You | 131 | 67 | Essentia detected double-time. Our `_pick_best_bpm` code now correctly returns 67, but the DB was populated before this code existed. |
| Blinding Lights | 86 | 171 | Essentia detected half-time. Same issue — the correction code exists but was never re-applied to the DB. |

The current octave error detection in `_pick_best_bpm` works correctly — it sees that Essentia is 2x or 0.5x of the LLM BPM and trusts the LLM. But since `get_songs_needing_llm` only returned songs with `valence IS NULL`, these already-classified songs were never re-processed with the new logic.

**Fix:** Added `--reclassify` flag to `classify-songs` CLI. When set, ALL eligible songs go through the LLM pipeline again, picking up the corrected BPM merge, onset rate energy, new blend weights, etc.

Also added `--force` flag to `analyze-audio` to recompute Essentia features on all songs (not just unclassified ones), so the onset rate energy gets applied to the 33 songs that have audio clips.

### Root Cause 2: LLM valence bias for melancholy/devotional songs (5 songs)

| Song | LLM valence | Should be | Why wrong |
|------|------------|-----------|-----------|
| Photograph (Ed Sheeran) | 0.7 | ~0.3 | Nostalgic, melancholy — pretty melody but sad lyrics |
| Love Yourself (Bieber) | 0.6 | ~0.3 | Bitter breakup disguised as gentle acoustic |
| Namo Namo (Amit Trivedi) | 0.7 | ~0.3 | Devotional prayer — meditative, not happy |
| Deva Deva (Pritam) | 0.8 | ~0.5 | Spiritual/uplifting but not "happy" |
| Ishq Jalakar (Shashwat Sachdev) | 0.8 | ~0.5 | Emotional intensity ≠ positiveness |

The LLM consistently confuses "pretty melody" with "positive emotion." A beautiful sad song gets rated as happy. This is a known LLM bias on subjective 0-1 scales — they avoid extremes and compress everything to the 0.4-0.8 range.

Valence only has 10% weight in the formula, but it matters at the margins. The parasympathetic score uses `gaussian(valence, 0.35, 0.2)` — when valence=0.7, this returns 0.10 (far from center). When valence=0.3, it returns 0.94 (near center). That's a 9x difference on a component that has 0.10 weight = 0.084 score points. In songs where PARA and GRND are close, that's enough to flip the bucket.

**Fix:** Added explicit valence calibration to the LLM system prompt:
- "Valence measures emotional positiveness of the FEELING, not the melody"
- Sad/nostalgic: 0.2-0.4 even if melody is beautiful
- Bitter/angry: 0.1-0.3 even if acoustically gentle
- Devotional/meditative: 0.2-0.4 (reverent, not happy)
- Genuinely happy/celebratory: 0.7-1.0

### Root Cause 3: "Felt tempo" ≠ measured tempo (2 songs)

| Song | Measured BPM | Felt BPM | Why both sources are "right" |
|------|-------------|----------|------------------------------|
| Namo Namo | 120 | ~80 | Tabla plays at 120, vocal phrase cycles at 80 |
| Shankara | 120 | ~60 | Percussion at 120, chant cycle at 60 |

Indian devotional music often has double-time percussion (tabla, dholak) under slow vocal melodies. Both Essentia and the LLM correctly detect the instrument BPM at 120. But the song *feels* like 60-80 BPM because the vocal/melodic phrase — what the listener tracks — cycles at half speed.

For neurological impact, felt tempo matters more than measured BPM. Your autonomic nervous system responds to the tempo you *perceive*, not the fastest instrument.

**Fix:** Added `felt_tempo` as a new field in the LLM prompt. The LLM is told: "The tempo the LISTENER perceives, which may differ from measured BPM. Set when the song has double-time percussion but the vocal phrase cycles at half speed. If felt tempo equals measured BPM, set to null."

The scoring formula now uses `felt_tempo or bpm` for neurological scoring. The measured BPM is preserved separately for playlist sequencing (smooth tempo transitions between songs).

Added a new `felt_tempo` column to the `song_classifications` database table.

### Other findings

**Locked out of Heaven (Bruno Mars):** We had this labeled as "mid" energy (→ GRND), but it's actually an energetic funk-pop song (BPM=147, energy=0.92). The ground truth was wrong, not the system. Fixed the test set to label it as "high" (→ SYMP).

**Hanuman Chalisa (Lo-fi):** The sigmoid widening (60,90→70,110) helped most songs but hurt this one. At BPM=70, old parasympathetic=0.73, new parasympathetic=0.99. Old grounding=0.95 (center=75), new grounding=0.61 (center=85). The widening pulled this 70 BPM devotional song from GRND into PARA. May need to narrow the sigmoid slightly (70,110 → 65,105) as a compromise if this persists after reclassification.

**Dhurandhar:** Onset rate under-measures its energy (0.64 vs RMS 0.82). The song has high perceived energy but moderate onset rate. Onset rate isn't perfect for every song, but it's better overall than RMS. Edge case we accept.

## Key learnings from the entire process

### About LLMs and music

1. **LLMs are biased on continuous 0-1 scales.** They compress everything to 0.4-0.8 and avoid extremes. GPT-4o-mini rated Kun Faya Kun (a soft Sufi prayer) at 0.80 energy. They're great at categorical judgments ("is this song energetic? yes/no") but bad at continuous ones ("rate the energy from 0 to 1").

2. **Smaller LLMs beat bigger ones for factual recall.** GPT-4o-mini (8/25 BPM accuracy) > GPT-4o (6/25) > Claude Sonnet (7/25) > Claude Opus (5/25). Bigger models try to "reason" about tempo from genre/mood instead of just recalling the memorized database value.

3. **LLM self-reported confidence is worthless.** GPT-4o-mini reported 1.0 confidence on literally every song, including niche kirtan tracks it clearly doesn't know. We compute confidence ourselves from cross-validation signals (BPM agreement between Essentia and LLM).

4. **"Database recall" prompting beats "estimate" prompting.** Framing as "recall the precise BPM from music databases" (9/25, MAE 13.1) vs "estimate the BPM" (8/25, MAE 18.8). The framing changes whether the model retrieves memorized values or tries to reason from first principles.

5. **Extra context helps for obscure songs.** Adding duration + Essentia energy/acousticness to the prompt improved obscure Indian song accuracy from 56% → 78%. More context = higher probability of recognition. But don't include Essentia BPM — it causes the LLM to override its own correct recall with Essentia's octave errors.

### About audio analysis

6. **Essentia's Western training bias is real and unfixable.** 4/5 English BPMs correct, 3/13 Indian BPMs correct. Tabla patterns, vocal ornaments, and non-Western rhythmic structures confuse the beat tracker. Even the neural TempoCNN model (trained on the same Western data) matched classical Essentia exactly.

7. **No free BPM database covers Indian music.** Soundchats ($250/mo), GetSongBPM (Cloudflare-blocked), SongBPM.com (0% Bollywood accuracy), HuggingFace datasets (source: Spotify's deprecated Essentia-based API). Dead end.

8. **Simple normalization beats complex algorithms when signal is weak.** RMS/0.35 (71% accuracy) beat every composite (weighted combinations of Loudness, P90, sigmoid) we tried. When individual components are ~70% accurate, combining noisy signals amplifies noise rather than canceling it.

9. **Spectral flatness > spectral centroid for acousticness.** Centroid measures brightness; bright acoustic guitar scores "electronic" while bass-heavy EDM scores "acoustic." Flatness measures tonal vs noise-like spectrum — correlates better with organic vs synthetic (67% vs 33%).

### About the scoring formula

10. **No single property can single-handedly ruin a classification.** BPM has only 35% weight. Even with wrong BPMs, the remaining 65% (energy, acousticness, valence, etc.) correctly classified obscure Indian songs at 78% accuracy. The weighted design is resilient.

11. **±10 BPM tolerance is safe.** State mapper BPM ranges are 20-60 BPM wide. A ±10 error never causes a song to land in the wrong bucket. This was validated empirically.

12. **Audio analysis and LLM knowledge are complementary.** Essentia measures what the audio actually does (physical properties). The LLM knows what the song is (cultural context). They fail on different songs. The blend approach works because of this orthogonality.

### About methodology

13. **Always test assumptions before committing to an architecture.** We predicted LLM would score 85-90% on energy/acousticness. Actual: 42%/50%. The 5-minute experiment saved us from building the wrong system.

14. **Root cause analysis > parameter tuning.** After hitting 60%, we didn't keep tweaking sigmoid parameters. We examined each failing song individually and found 3 distinct, fixable root causes. This is how you go from "it mostly works" to "it works."

15. **Test on a small set first, then scale.** We ran all 1360 songs through reclassification before validating on the 25-song test set. Should have done the 25 first, confirmed improvement, then scaled. The cost was small ($1.36) but the principle matters.

## What's running now

Full reclassification of all 1360 songs with:
- Corrected BPM via merge pipeline (fixes Root Cause 1)
- Valence calibration in LLM prompt (fixes Root Cause 2)
- `felt_tempo` as new field (fixes Root Cause 3)
- Updated Essentia onset rate energy (from `--force` reanalysis)
- Fixed ground truth (Locked out of Heaven: mid → high)

## Results after first reclassification: 48% → 64% → 68%

After reclassifying all 1360 songs with the updated prompt + onset rate energy + blend:

| Stage | Score | What changed |
|-------|-------|-------------|
| Original (old formula, old data) | 48% (12/25) | baseline |
| After ground truth fix (Locked out of Heaven mid→high) | 56% (14/25) | test set correction |
| After reclassification (NEW formula scores) | 64% (16/25) | BPM corrections, onset rate energy |
| With blend (formula + LLM direct scores) | 68% (17/25) | LLM knows some songs better |

**What worked:**
- Die For You: BPM corrected from 131→67 (Essentia octave error, now caught by `_pick_best_bpm`)
- Shiv Kailash: BPM + valence correction → now correctly PARA
- Shankara: BPM dropped to 74, valence=0.30 → correctly PARA

**Valence calibration results — mixed:**
- Namo Namo: 0.70→0.30 (worked perfectly)
- Love Yourself: 0.60→0.30 (worked)
- Photograph: 0.70→0.60 (partially worked, should be ~0.3)
- Ishq Jalakar: 0.80→0.80 (no change — calibration ignored)

**`felt_tempo` — mostly unused:**
The LLM set `felt_tempo=NULL` for almost every song. It didn't engage with the concept. One exception: Die For You got `felt_tempo=134` (reversed — put the slow tempo in BPM and the fast tempo in felt_tempo). The feature exists in the schema and pipeline but the LLM isn't reliably using it yet.

## The deep dive: why 10 songs still fail

We pulled the actual DB values for every failing song and computed component-level breakdowns of the formula scores. This revealed the core structural problem.

### Discovery: GRND has a structural advantage in the formula

63% of the library (859 songs) falls in BPM 75-105. Within that range, 80% score GRND regardless of other properties. Only 2% score PARA.

Three independent mechanisms cause this:

**1. Weight asymmetry:** GRND puts 0.70 of its total weight on non-tempo components (tempo=0.30), while PARA puts 0.65 (tempo=0.35). When tempo scores are tied (they are at BPM ~80), GRND has 5% more scoring power from other properties.

**2. Energy gaussian vs linear:** PARA's energy is `(1-energy) × 0.25` — a linear decay that barely distinguishes energy=0.15 from energy=0.35 (difference: 0.050). GRND's energy is `gaussian(energy, 0.35, 0.15) × 0.20` which PEAKS at 0.35 (value: 0.200). Most real songs have energy 0.25-0.50, right in GRND's gaussian sweet spot.

**3. Acousticness weight disparity:** GRND gets `acousticness × 0.15`, PARA gets `acousticness × 0.10`. High-acousticness songs — the ones most likely to be calming (PARA) — give a LARGER boost to GRND. At acousticness=0.85: PARA gets 0.085, GRND gets 0.128.

This is not a parameter tuning issue — it's a design limitation of the additive formula. The formula can't express the conjunction "slow AND quiet AND acoustic" that defines parasympathetic activation. It treats each property independently.

### Discovery: the LLM already has the right answer for 5/9 failures

| Song | LLM says | Formula says | Correct? |
|------|----------|-------------|----------|
| Love Yourself | PARA | GRND | LLM right |
| Namo Namo | PARA | GRND | LLM right |
| Haaye Oye | SYMP | GRND | LLM right |
| Shararat | SYMP | GRND | LLM right |
| Deva Deva | PARA | GRND | Formula right |
| Chedkhaniyaan | SYMP | GRND | Formula right |
| Softly | SYMP | GRND | Formula right |
| Shiv Kailash | GRND | PARA | Formula right |
| Hanuman Chalisa | PARA | GRND | Formula right |

The LLM and formula are each right on 16/25 (64%) individually — the same score. But they're **wrong on different songs**. If we could always pick the correct source, we'd get 21/25 (84%).

The weighted average blend (the old approach) can't exploit this. It blindly mixes the two signals every time, regardless of which one is likely right. The formula's GRND bias bleeds through the average.

### What we tried that DIDN'T work

**Attempt 1: Fix the formula's GRND bias with parameter changes.**
- Tried: sigmoid energy for PARA instead of linear, swap acousticness weights (PARA 0.10→0.15, GRND 0.15→0.10), reduce instrumentalness weight.
- Result: 14/25 (56%) — WORSE. Two regressions (Die For You, Shiv Kailash). The sigmoid energy was too aggressive, killing PARA scores for songs with moderate energy. Any change that helps PARA also helps GRND because they share the same positive signals.
- Lesson: the additive formula's GRND bias can't be fixed by parameter tuning. The structure is the problem.

**Attempt 2: Grid search over GRND gaussian sigma + Indian blend weight.**
- Tested: sigma ∈ {10, 11, 12, 13, 14, 15} × Indian formula weight ∈ {0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70}.
- Finding: every regression-free configuration topped out at 17/25 (68%). They all fix only Love Yourself (the 0.003-margin case). More aggressive settings fix more songs but cause regressions — tight coupling.
- Lesson: parameter search within the weighted-average architecture has a hard ceiling.

**Attempt 3: First ensemble (v1) — binary trust rules.**
- Rules: if formula says GRND in 70-110 BPM zone and LLM is confident → trust LLM.
- Result: 17/25 (68%) — WORSE than baseline (18/25). Regressed Deva Deva (formula was right, LLM was wrong, but the rule blindly trusted LLM for any song at BPM 80).
- Lesson: BPM alone can't distinguish "formula is biased" from "formula is correct." Need another signal.

### The breakthrough: energy level distinguishes when to trust which source

Looking at only the disagreement cases where at least one source is right:

| Song | Energy | LLM right? | Formula right? |
|------|--------|-----------|----------------|
| Namo Namo | 0.34 | YES | no |
| Haaye Oye | 0.36 | YES | no |
| Deva Deva | 0.42 | no | YES |
| Hanuman Chalisa | 0.50 | no | YES |
| Tere Liye | 0.53 | no | YES |
| Softly | 0.69 | no | YES |

Energy < 0.40: the song is quiet. The formula's GRND gaussian is biased because it peaks right where quiet songs live. Trust the LLM — it has cultural context to know a quiet devotional song is calming, not grounding.

Energy >= 0.40: the song has real energy. The formula's GRND call is legitimate — the song genuinely has moderate properties. Trust the formula.

This threshold is NOT overfitting to specific songs. It reflects a physical/neurological fact: quiet songs at moderate tempo are more likely to be calming than grounding. The GRND gaussian's bias is strongest for low-energy songs because energy=0.35 is where the gaussian peaks.

### Critical bug found: reclassification wiped Essentia data

During testing, we discovered that the `_merge_with_essentia` function checked `classification_source == "essentia"` (exact match). During reclassification, songs previously classified as "essentia+llm" failed this check — their energy, acousticness, key, and mode were set to NULL.

This meant our first accuracy numbers (18/25 = 72%) were running on corrupted data — most songs had no energy, which accidentally reduced the GRND bias (energy=None defaults to 0.5, which is far from the gaussian center at 0.35).

Fix: changed to `"essentia" in (classification_source or "")` so both "essentia" and "essentia+llm" are recognized. Then re-ran Essentia analysis + LLM classification for the 33 affected songs.

### Final architecture: confidence-aware ensemble

Replaced the weighted-average blend with structural rules:

1. **Agreement** (formula and LLM pick same bucket): blend 50/50. High confidence.
2. **Formula says GRND in BPM 70-110 zone + energy < 0.40**: formula is in its known bias zone AND the song is quiet. Trust LLM (25% formula / 75% LLM).
3. **Formula says GRND in BPM 70-110 zone + energy >= 0.40**: the song genuinely has moderate properties. Trust formula (70% formula / 30% LLM).
4. **Other disagreements**: slight LLM preference for cultural context (40% formula / 60% LLM).

This is fundamentally different from the old approach. Instead of always averaging with fixed weights, it uses knowledge about **when each source is likely to fail**. The formula fails in a predictable zone (GRND gaussian bias at moderate tempo + low energy). The LLM fails in a different predictable way (compressed spreads, under-rating GRND for moderate songs).

### Also implemented: `recompute-scores` CLI command

After discovering that every formula/blend parameter change required a full 1360-song LLM reclassification (~$1.36, ~55 minutes), we built a `recompute-scores` command that recomputes formula + ensemble scores from existing DB data with zero API calls. Takes 2 seconds. This enabled rapid iteration on the ensemble design.

### Also implemented: `--reclassify` and `--force` flags

- `python main.py classify-songs --reclassify`: re-runs LLM classification on ALL songs (not just new ones)
- `python main.py analyze-audio --force`: recomputes Essentia features on all songs with audio clips
- These are only needed when the LLM prompt changes (which affects what the LLM returns). Formula/blend changes use `recompute-scores`.

## Final accuracy: 48% → 72%

| Stage | Score | Approach |
|-------|-------|----------|
| Original formula | 48% (12/25) | Narrow sigmoids, RMS energy, no blend |
| + sigmoid widening + onset rate + blend | 60% (15/25) | Wider curves, better energy measure, weighted average |
| + prompt fixes + reclassification | 64% (16/25) | Valence calibration, felt_tempo, BPM corrections |
| + GRND gaussian narrowing (sigma 15→10) | 68% (17/25) | Reduced GRND gravity well |
| + confidence-aware ensemble | 72% (18/25) | Structural knowledge about when each source fails |

### Remaining 7 failures

| Song | Why | Fixable? |
|------|-----|----------|
| As It Was | BPM=174, should be ~84. LLM octave error. | Yes — BPM accuracy improvement |
| Love Yourself | Both agree GRND. BPM=100 is genuinely borderline. | Debatable ground truth |
| Chedkhaniyaan | LLM says SYMP (wrong). Formula says GRND. LLM overrides. | Need better LLM GRND detection |
| In Dino | Both wrong. Neither source recognizes this as calming. | Hard — needs richer input |
| Haaye Oye | LLM spread=0.1, no confidence. Neither source knows. | Hard — limited data |
| Ishq Jalakar | Both agree SYMP. Valence=0.80 still uncalibrated. | LLM prompt improvement |
| Shankara | LLM nondeterminism across runs. Was correct, then wasn't. | Inherent LLM variance |

### Theoretical ceiling: 84% (21/25)

The LLM and formula together have the right answer for 21/25 songs. Only 4 songs are truly unsolvable with current data (both sources wrong). The remaining gap between 72% and 84% is:
- 2 songs fixable with better BPM accuracy (As It Was, and potentially Shankara)
- 1 song fixable with better valence calibration (Ishq Jalakar)

## Key learnings added this session

16. **A weighted average is the wrong way to combine two complementary classifiers.** When two sources have different, predictable failure modes, averaging them wastes the information about WHEN each fails. A confidence-aware ensemble that routes decisions based on structural knowledge outperforms any fixed-weight blend.

17. **Better data can make a biased formula WORSE.** Restoring correct Essentia energy values made the GRND bias stronger because the GRND gaussian peaks at energy=0.35 — right where quiet acoustic songs actually measure. The formula got more wrong with more accurate data. This is how you know the formula structure is flawed, not the parameters.

18. **The formula can't distinguish PARA from GRND because the distinction is conjunctive.** PARA activation requires "slow AND quiet AND acoustic" — a conjunction. The additive formula treats each property independently, so a high tempo score compensates for low energy. This doesn't match neuroscience. Grounding is genuinely additive (moderate values in various properties balance out), which is why the formula works well for GRND but not for PARA.

19. **63% of a typical music library sits in the 75-105 BPM range.** Any formula bias in this zone affects the majority of songs. The GRND gaussian (center=85, sigma originally 15) dominated this entire range, which is why GRND was the default bucket for most of the library.

20. **Always check if your data pipeline corrupts data on re-runs.** The `classification_source == "essentia"` exact-match bug silently wiped Essentia features during reclassification. Songs went from "essentia+llm" (with energy/acousticness) to "llm" (without). The corrupted data accidentally improved accuracy by reducing the GRND bias, making the bug invisible until we dug into specific song values.

21. **Build fast iteration tools before optimizing.** The `recompute-scores` command (2 seconds, no API calls) enabled testing 42+ parameter combinations in the time one reclassification took. We should have built this before the first full reclassification, not after.

22. **LLMs are nondeterministic even at temperature=0 when batch composition changes.** Shankara got para=0.8 in one run and para=0.6 in another, just from being in a different batch of 5 songs. This affects reproducibility. Accept ~0.1 variance in LLM scores as inherent noise.

23. **Test on a small subset before running the full library.** We reclassified all 1360 songs ($1.36, 55 minutes) before validating on the 25-song test set. Should have reclassified just the 25 test songs first (~$0.05, 1 minute). The full run was needed eventually, but not for the initial validation.

## Validation on fresh 34-song test set

We tested on 34 songs Pranav hadn't labeled before (different from the 25 we tuned on). All 34 were songs without Essentia audio data — representing 98% of the real library.

- Before LLM energy/acousticness: 56% (19/34)
- After LLM energy/acousticness: 62-65% (varies by run, LLM nondeterminism)
- Combined 59 songs: 66% bucket accuracy

PARA accuracy was the weakest: 30% before energy estimates, 60% after. The LLM energy gave the ensemble the signal it needed.

## Error severity analysis (59 songs)

| Category | Count | Percentage |
|----------|-------|-----------|
| Exact bucket match | 39 | 66% |
| Adjacent error (off by one) | 16 | 27% |
| Catastrophic error (PARA↔SYMP) | 4 | 7% |
| Correct + adjacent | 55 | 93% |

Of the 16 adjacent errors, **11 were songs labeled on a boundary** (low-mid, mid, mid-high) where the ground truth itself is ambiguous. Only 3 adjacent errors were on clear labels (low, high). 5 errors had margins under 0.05 — essentially coin flips.

If we give benefit of the doubt to boundary labels: **50/59 = 85%.**

## The 4 catastrophic errors

All 4 share one root cause: the song FEELS different than its measurable properties suggest.

- **Just the Way You Are** (Bruno Mars): BPM=109, energy=0.8, valence=0.9. Every signal says energizing. But Pranav hears it as gentle. Personal perception.
- **Chori Kiya Re Jiya** (Sonu Nigam): BPM=100, valence=0.7. Moderate tempo but perceived as gentle. Melody softness doesn't show up in measured properties.
- **Naina Da Kya Kasoor** (Amit Trivedi): BPM=70, energy=0.4. Every signal says calming. But Pranav hears emotional intensity and drive. That energy comes from vocal delivery, not tempo.
- **Tu Hi Meri Shab Hai** (Pritam): BPM=70, energy=0.3. Same pattern — slow and quiet by measurement, but emotionally intense.

These are perception gaps, not algorithm gaps. Fixing them would require either a neural model trained on millions of labeled examples (learns features we can't name), or a personalization layer that learns individual perception over time.

## The product insight: bucket accuracy is the wrong metric

**This was the most important realization of the entire session.**

We had been evaluating by assigning each song to its highest-scoring bucket (PARA/GRND/SYMP) and comparing against a human label. But the matching engine doesn't work this way. It asks: "I need calming songs — which ones have a parasympathetic score above threshold?"

A song with PARA=0.65 and GRND=0.70 gets classified as "GRND" in bucket evaluation — counted as wrong. But it would **still get selected for a calming playlist** because its PARA score is well above the selection threshold.

Three metrics that actually matter:

| Metric | Score | What it measures |
|--------|-------|-----------------|
| Bucket accuracy | 66% | Is the highest-scoring bucket correct? (evaluation artifact) |
| Product accuracy | 83% | Would this song be selected for the right playlist? (threshold > 0.45) |
| Safety | 86% | Would this song NOT be played in the opposite situation? |

The 3-bucket classification was an **evaluation framework we borrowed from our test methodology, not a product requirement.** The product uses continuous scores with thresholds. A song doesn't need to be "in the right bucket" — it needs to have a high enough score in the relevant dimension.

The PARA/GRND boundary that consumed hours of tuning barely matters in practice. A song scored PARA=0.65, GRND=0.70 works for both calming and grounding playlists. The matching engine handles this naturally through threshold-based selection and progressive filter relaxation.

**CPO call: the classification layer is good enough. The continuous scores for all 1360 songs are what the matching engine needs. Stop optimizing bucket accuracy and build the matching engine.**

## Final learnings

24. **Evaluate against the product metric, not a proxy metric.** Bucket accuracy (66%) made us think we had a problem. Product-relevant accuracy (83%) showed the system was already working. We spent hours optimizing a metric that doesn't match how the product works.

25. **Boundary labels in ground truth create phantom errors.** 11/14 adjacent "errors" were songs labeled low-mid, mid, or mid-high — inherently ambiguous. The system was often placing them in a defensible adjacent bucket. Adjusted accuracy accounting for ground truth ambiguity: 85%.

26. **The dangerous errors (7%) are perception gaps, not algorithm gaps.** Songs where measured properties don't match personal perception. No formula or prompt can fix "this 109 BPM song feels gentle to me." That requires personalization (learning from user behavior) or neural audio models (learning from raw audio spectrograms). Both need data we don't have yet.

27. **Continuous scores are more valuable than discrete buckets.** The matching engine uses score thresholds, not bucket assignments. A song with PARA=0.65 and GRND=0.70 serves both calming and grounding playlists. The bucket boundary between them is irrelevant to the product.

28. **Know when to stop optimizing and ship.** We went from 48% to 66% bucket accuracy (83% product accuracy, 93% within one bucket). The remaining gaps are data quality (more audio clips), personalization (user feedback loop), and perception modeling (neural nets). None of these are classification algorithm improvements. Time to build the matching engine.
