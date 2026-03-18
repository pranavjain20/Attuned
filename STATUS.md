# Attuned — Current Status

**Last updated:** Mar 18, 2026
**Current phase:** Day 4 pre-work complete. All classification property evaluations done, strategy decided.
**Next action:** Day 4 — LLM song classification (~669 songs).

---

## What's Done (Day 4 Pre-Work: Property Evaluation)

### Property-by-Property Classification Evaluation
Evaluated all 10 classification properties (BPM, key/mode, energy, danceability, acousticness, instrumentalness, valence, mood_tags, genre_tags) against 24 Strategy D audio files with ground truth from Tunebat/SongBPM.

### Per-Property Results and Decisions

**BPM** — Essentia 33% overall (80% English, 23% Indian). TempoCNN identical. GPT-4o-mini 8/25 with complementary failures. ±10 tolerance safe.
- **Decision:** Hybrid — Essentia for English, LLM for Indian

**Key/Mode** — Essentia KeyExtractor: 58% exact+enharmonic, 92% musically usable for sequencing. 3/6 "wrong" results are dominant confusion (known HPCP limitation, musically harmless). Ground truth is Spotify's Essentia-based analysis (same algorithm, different audio source). Three profiles (temperley/edma/bgate) agree 21/24 times.
- **Decision:** Essentia sufficient — 92% musically close is good enough for sequencing

**Energy** — RMS/0.25 broken: 11/24 (46%) clipped at 1.0. Tested alternatives: Loudness, P90 frame energy, sigmoid, percentile, composites (loudness+onset+brightness+BPM). All complex approaches scored worse than simple RMS/0.35 (71% bucket accuracy). Energy is a perceptual property; volume is an imperfect proxy but the simplest thing that works.
- **Decision:** Essentia with fixed normalization (RMS/0.35). 71% bucket accuracy, zero ceiling songs.
- **Code change:** `essentia_analyzer.py` line 117: `rms / 0.25` → `rms / 0.35`

**Danceability** — Essentia DFA: 23/24 values above 1.0, ALL clamped to 1.0. Zero discrimination. Even rescaled raw range [0.995, 1.486] gives 42% bucket accuracy (worse than random). DFA measures rhythmic regularity, not danceability — BSB ballad ranks #4, Levitating ranks #17.
- **Decision:** LLM only — Essentia's algorithm measures the wrong property

**Acousticness** — SpectralCentroidTime: 33% (random). Spectral Flatness: 67%. Rolloff: 33%. Flatness measures tonal vs noise-like spectrum — better proxy for acoustic vs electronic instruments.
- **Decision:** Essentia with switched algorithm (spectral flatness replaces spectral centroid). 67% bucket accuracy.
- **Code change:** `essentia_analyzer.py` — replaced SCT inversion with frame-level spectral flatness computation

**Instrumentalness** — ZCR proxy: 11/24 vocal songs scored >0.5 instrumental. ZCR measures high-frequency content, not vocal presence. Would require ML voice detection models (heavy dependency) to fix.
- **Decision:** LLM only — ZCR is the wrong measurement, all 669 library songs have vocals

**Valence, Mood Tags, Genre Tags** — Not computable from audio signal. These are semantic/perceptual properties.
- **Decision:** LLM only (by design)

### LLM vs Essentia Shootout (Energy + Acousticness)
Tested GPT-4o-mini against Essentia on 25 songs for energy and acousticness. LLM scored worse on both: energy 42% vs Essentia 71%, acousticness 50% vs Essentia 62%. LLM has middle-value bias on continuous 0-1 scales (compresses to 0.4-0.8 range) and weak Indian song knowledge. Confirmed Essentia stays for both.

### Staff Audit (all findings fixed)
- Staff engineer: 3 MUST FIX (unused import, per-frame algorithm instantiation in loop, mock not testing varying flatness). 8 SHOULD FIX (non-idiomatic numpy, missing boundary tests, dead code, test mock gap).
- Staff tester: 4 HIGH gaps (energy boundary, varying flatness, zero-sum spectrum, empty frames). 5 MEDIUM gaps.
- All MUST FIX and HIGH items resolved. 7 new tests added.

### Classification Architecture Summary
- **Essentia handles (4 properties):** BPM (English songs), Key/Mode, Energy (RMS/0.35), Acousticness (spectral flatness)
- **LLM handles (6 properties):** BPM (Indian songs), Danceability, Instrumentalness, Valence, Mood tags, Genre tags
- 421 tests passing, all pushed to main

### BPM Experiment Details (from prior session)
- Tested 6 audio strategies across 25 songs (5 categories)
- Strategy D (duration-verified YouTube) gets correct audio 24/25 times
- Model shootout: GPT-4o-mini > GPT-4o > Claude Sonnet > Claude Opus > GPT-4.1 for BPM recall
- "Database recall" prompting > "estimate" prompting (9/25 vs 8/25, MAE 13.1 vs 18.8)
- TempoCNN dropped (115MB dependency, identical accuracy)
- ±10 BPM tolerance validated safe for state mapper ranges

## What's Done (Day 3)

### State Classifier Redesign (recovery-first, 5-tier system)
- Rewrote `intelligence/state_classifier.py` — recovery-first flow, 8 states (insufficient_data, accumulated_fatigue, poor_sleep, physical_recovery_deficit, emotional_processing_deficit, poor_recovery, peak_readiness, baseline)
- Recovery tiers: <40 (definitively bad), <60 (struggling), <80 (functional), ≥80 (great)
- Accumulated fatigue: recovery < 60 AND ≥3 of last 5 days also < 60 (replaces weighted scoring)
- Sleep deficits checked at any recovery level (P2-P4)
- Renamed `single_bad_night` → `poor_recovery` across entire codebase (8 files)
- Fixed `_is_debt_low` threshold: changed from `mean - 1*SD` to `mean` (debt at or below average for peak). Increased peak_readiness from 25 → 47 days on real data.

### Real Data Validation
- Ran classifier on all 823 recovery days
- Distribution: baseline 51%, fatigue 20%, poor_recovery 12%, peak 6%, phys/emo deficit 4% each, poor_sleep 1%
- Last 30 days spot-checked with Pranav — all classifications match felt experience
- Key dates verified: 2025-03-12 (96%) → peak, 2026-03-13 (19%) → fatigue, 2026-03-05 (29%) → fatigue

### WHOOP Personal Intelligence Layer
- `intelligence/baselines.py` — HRV, RHR, sleep stage baselines + sleep debt (30-day windows, personal norms)
- `intelligence/trends.py` — 7-day HRV/RHR slopes + consecutive day detection
- `intelligence/sleep_analysis.py` — Deep/REM deficit and adequacy analysis vs personal norms + absolute floors
- `config.py` — Recovery tier thresholds, fatigue window constants, sleep/baseline thresholds
- `db/queries.py` — get_recoveries_in_range, get_sleeps_in_range
- `main.py` — `classify-state` CLI command with `--date` flag

### Data Integrity Fixes
- Fixed multi-sleep-per-date bug: naps + primary sleep on same date were double-counting "needed" sleep in debt calculation and inflating baseline stage counts. Now correctly groups by date.

### Tests
- **354 tests, all passing** across 15 test files
- `test_state_classifier.py`: 45 tests (rewritten for recovery-first logic + audit gap fills)

### Audit Findings (all fixed)
- Staff auditor: 1 MUST FIX (_is_debt_low threshold too restrictive), 5 SHOULD FIX (unused constants, gray zone reasoning, stale docs, test rename, asymmetry comment)
- Staff tester: 6 HIGH gaps (declining trend, None HRV, gray zone assertion, metrics values, debt path, trend unavailable), 9 MEDIUM gaps (boundaries, confidence levels, null handling)
- All findings resolved

## What's Done (Day 2)

### Duplicate Song Consolidation
- `spotify/dedup.py` — detects same (name, artist) with different Spotify URIs, merges into canonical
- 435 duplicate groups found and consolidated (499 songs merged)
- Explicit transaction with rollback, conflict logging, idempotent

### Engagement Scoring
- `spotify/engagement.py` — 5-signal engagement scoring, tuned through iterative review with real data
- Final weights: log_play 0.30, completion 0.25, recent_ratio 0.20, active 0.15, (1-skip) 0.10
- `recent_play_ratio` = fraction of >30s plays from last 365 days (replaced weak last-played-date signal)
- Active play rate counts clickrow + playbtn + remote (fixes Alexa/voice penalty)
- MIN_MEANINGFUL_LISTENS = 5 (was 3)
- `db/schema.py` — added `recent_play_ratio` column with idempotent migration
- `main.py` — `compute-engagement` and `dedup-songs` CLI commands
- Dedup + scoring auto-runs at end of `sync-spotify`

### Real Data Results
- 669 songs scored (5+ meaningful plays, after dedup)
- Top 5: Bernie's Chalisa, Namo Namo (96 plays combined from 2 URIs), Boyfriend, Aayi Nai, Shiv Kailash
- 0 scores outside [0,1]
- Devices in data: iPhone (27k), Echo Dot (2.3k), unknown/2nd Alexa (2.1k), Mac (739), Fire TV (25)

### Tests
- **232 tests, all passing** across 10 test files
- New: `test_dedup.py` (52 tests), expanded `test_engagement.py` (62 tests)

### Audit Findings (all fixed)
- Day 2 round 1: timezone conversion bug, duration_ms=0 routing, unclamped recency, weak assertions
- Day 2 round 2: explicit transaction for dedup, conflict logging, misleading comment, sync-spotify dedup ordering

## What's Done (Day 1)

### Tier 1 — Offline, fully tested
- `config.py` — constants, thresholds, lazy env var loaders
- `db/schema.py` — 7 tables + indexes, WAL mode, foreign keys
- `db/queries.py` — all CRUD functions
- `spotify/sync.py` — extended history ingestion: 32,729 history rows, 5,782 songs
- `main.py` — CLI entry point

### Tier 2 — API clients, tested with mocks
- `whoop/auth.py`, `whoop/client.py`, `whoop/sync.py` — full WHOOP integration
- `spotify/auth.py`, `spotify/client.py` — Spotify OAuth + library access

### Tier 3 — Integration (done)
- WHOOP: 823 recovery days, 907 sleep records (Nov 2023 — Mar 2026)
- Spotify: liked songs, top tracks, metadata synced

## What's Next

- Day 4: LLM song classification (~669 songs)
- Day 5: Matching engine (engagement-weighted)
- Day 6: Playlist creation + end-to-end flow
- Day 7: Sequencing + polish + hardening

## API Keys Status

- WHOOP: registered, OAuth working, full history synced
- Spotify: registered, OAuth working, library synced
- OpenAI: has $5 credits (for song classification, Day 4)
