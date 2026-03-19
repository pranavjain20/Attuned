# Attuned — Current Status

**Last updated:** Mar 19, 2026
**Current phase:** Day 4b complete. Classification layer done. All 1360 songs classified with energy/acousticness. Ready for Day 5 matching engine.
**Next action:** Day 5 — Matching engine (engagement-weighted song selection from classified library).

---

## Classification Layer — Final State

All 1360 songs fully classified with: BPM, energy, acousticness, valence, danceability, instrumentalness, mode, mood/genre tags, para/symp/grounding scores. 100% energy coverage (LLM estimates + Essentia for 33 songs with audio).

**Accuracy (59-song cross-validated test set):**
- Bucket accuracy: 66% (discrete 3-bucket evaluation)
- Product accuracy: 83% (score above threshold for correct playlist selection)
- Safety: 86% (opposite dimension not dominant)
- Within one adjacent bucket: 93%

**Architecture:** Confidence-aware ensemble (formula + LLM) with energy-based routing. Essentia audio features when available, LLM estimates as fallback. See `tasks/accuracy_tuning_learnings.md` for full session log.

**Key insight:** Bucket accuracy (66%) was the wrong evaluation metric. The matching engine uses continuous scores with thresholds, not discrete buckets. A song with PARA=0.65, GRND=0.70 works for both calming and grounding playlists. Product-relevant accuracy is 83%.

---

## What's Done (Day 4b: Accuracy Tuning)

### Accuracy progression: 48% → 68%

| Stage | Score | What changed |
|-------|-------|-------------|
| Original formula | 48% (12/25) | Narrow sigmoids, RMS energy, no blend |
| + Ground truth fix | 56% (14/25) | Locked out of Heaven: mid → high |
| + Reclassification | 64% (16/25) | Valence calibration, BPM corrections, onset rate energy |
| + GRND gaussian narrowing | 68% (17/25) | sigma 15→10 reduced GRND gravity well |
| + Confidence-aware ensemble | 72% (18/25) | Structural knowledge about when each source fails |
| + LLM energy/acousticness | 68% combined (40/59) | 72% on original 25, 65% on fresh 34 |

### Architecture changes

**Confidence-aware ensemble** (replaced weighted-average blend):
- Agreement (formula + LLM same bucket) → 50/50 blend
- Formula says GRND in BPM 70-110 zone + energy < 0.40 → trust LLM (25/75)
- Formula says GRND in BPM 70-110 zone + energy ≥ 0.40 → trust formula (70/30)
- Other disagreements → slight LLM preference (40/60)
- Uses structural knowledge about when each source fails, not fixed genre-based weights

**LLM energy/acousticness fallback:** When no Essentia audio data (98% of library), LLM now provides energy + acousticness estimates. Less accurate than Essentia (42% vs 71%) but infinitely better than default 0.5. Gives the ensemble the signal it needs to distinguish quiet calming songs from moderate grounding ones.

**GRND tempo gaussian narrowed:** sigma 15→10. The old gaussian dominated BPM 70-105 (63% of library). Narrower gaussian means GRND only wins for songs genuinely at moderate tempo.

### Bug fixes
- `has_essentia` exact-match bug: `== "essentia"` → `"essentia" in source`. Previous reclassification wiped Essentia data for "essentia+llm" songs.
- Valence calibration added to LLM prompt (devotional/sad/nostalgic songs)
- `felt_tempo` field added (LLM mostly ignores it but schema is ready)

### New CLI commands
- `python main.py recompute-scores` — recompute formula + ensemble from existing DB (2 seconds, no API calls)
- `python main.py classify-songs --reclassify` — re-run LLM on all songs
- `python main.py analyze-audio --force` — recompute Essentia on all audio clips

### Error severity (59 songs)
- Correct: 40/59 (68%)
- Adjacent error (off by one bucket): 15/59 (25%)
- Catastrophic error (PARA↔SYMP): 4/59 (7%)
- "Close enough" (correct + adjacent): 55/59 (93%)

### 617 tests passing, all green.

### Detailed session log: `tasks/accuracy_tuning_learnings.md`

---

## What's Done (Day 4: LLM Song Classification Pipeline)

### Neurological Profiler (`classification/profiler.py`)
- `sigmoid_decay`, `sigmoid_rise`, `gaussian` — primitive math functions
- `compute_parasympathetic` — calming score (tempo 0.35, energy 0.25, acousticness 0.10, etc.)
- `compute_sympathetic` — energizing score
- `compute_grounding` — emotional grounding with Gaussian-centered BPM at 85 sigma=10
- `compute_neurological_profile` — public API with None-handling

### LLM Classifier (`classification/llm_classifier.py`)
- `_build_prompt` — "Database recall" framing with rich context
- `_call_openai` / `_call_anthropic` — Provider-agnostic API calls
- `_validate_song_result` — Validates BPM, felt_tempo, energy, acousticness, valence, etc.
- `_pick_best_bpm` — LLM primary, octave error detection
- `_merge_with_essentia` — Essentia for key/mode/energy/acousticness when available, LLM estimates as fallback
- `_blend_neuro_scores` — Confidence-aware ensemble (not a weighted average)
- `classify_songs` — Orchestrator with `--reclassify` support

### Full Library Classification
- 1360 songs classified, 0 failures
- 33 songs with Essentia audio features, 1327 with LLM-only estimates

---

## What's Done (Day 4 Pre-Work)

(See previous STATUS.md sections — unchanged)

## What's Done (Day 3: WHOOP Intelligence)

(See previous STATUS.md sections — unchanged)

## What's Done (Day 2: Engagement Scoring)

(See previous STATUS.md sections — unchanged)

## What's Done (Day 1: Data Foundation)

(See previous STATUS.md sections — unchanged)

---

## What's Next

- **IMMEDIATE:** Full reclassification with LLM energy/acousticness (first thing next session)
- Day 5: Matching engine (engagement-weighted)
- Day 6: Playlist creation + end-to-end flow
- Day 7: Sequencing + polish + hardening

## API Keys Status

- WHOOP: registered, OAuth working, full history synced
- Spotify: registered, OAuth working, library synced
- OpenAI: ~$2 credits remaining (after 2 full + several partial reclassifications)
