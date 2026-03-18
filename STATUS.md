# Attuned — Current Status

**Last updated:** Mar 17, 2026
**Current phase:** Day 3 complete. State classifier redesigned, validated on real data.
**Next action:** Day 4 — LLM song classification (~669 songs).

---

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
