# Attuned — Task Tracker

## Pre-Build
- [x] Write PRD
- [x] Scaffold project structure
- [x] Create CLAUDE.md, STATUS.md, tasks/
- [x] Deep research: music-ANS, HRV sports science, sleep architecture, LLM classification, iso principle
- [x] Write docs/RESEARCH.md with findings, formulas, and citations
- [x] Update PRD to v2.0 (6 states, 0.0-1.0 scales, concrete thresholds, research-backed decisions)
- [x] Rephase sprint for extended streaming history (PRD v2.1, CLAUDE.md, STATUS.md updated)
- [ ] Pranav reads PRD v2.1 + RESEARCH.md
- [x] Register WHOOP developer app
- [x] Register Spotify developer app
- [x] Set up .env with credentials

## Day 1: Project Setup + Extended History Ingestion + First API Pulls
### Tier 1 — Offline (DONE)
- [x] config.py — constants, thresholds, env var loaders (15 tests)
- [x] db/schema.py — 7 tables + indexes (8 tests)
- [x] db/queries.py — all CRUD functions (25 tests)
- [x] tests/conftest.py + tests/fixtures/ — shared fixtures
- [x] spotify/sync.py — extended history ingestion (20 tests)
- [x] main.py — CLI with ingest-history command
- [x] Run ingest-history on real data: 33,311 records → 32,729 history rows, 5,701 songs
- [x] Verify idempotent re-run (0 new rows)
- [x] Code audit: fixed SQL injection, DRY violations

### Tier 2 — API Clients with Mocks (DONE)
- [x] whoop/auth.py — OAuth flow + token refresh (10 tests)
- [x] whoop/client.py — API calls + pagination + parsing (22 tests)
- [x] whoop/sync.py — orchestration (3 tests)
- [x] spotify/auth.py — SQLite CacheHandler (4 tests)
- [x] spotify/client.py — liked songs + top tracks + metadata (13 tests)

### Tier 3 — Integration (DONE)
- [x] Register WHOOP + Spotify apps, add credentials to .env
- [x] Run OAuth flows (auth-whoop, auth-spotify)
- [x] Pull full WHOOP history (823 recovery, 907 sleep)
- [x] Sync liked songs + top tracks + batch metadata (sync-spotify)
- [x] Verified full DB populated with real data

## Day 2: Engagement Scoring + Data Integrity (DONE)
### Dedup
- [x] spotify/dedup.py — duplicate song consolidation (52 tests)
- [x] 435 groups consolidated, 499 songs merged
- [x] Staff tester: 52 tests, 0 bugs found
- [x] Staff auditor: explicit transaction, conflict logging, comment fix, sync-spotify ordering

### Engagement Scoring
- [x] spotify/engagement.py — 5-signal scoring with tuned weights (62 tests)
- [x] db/schema.py — recent_play_ratio column + migration
- [x] main.py — compute-engagement, dedup-songs CLI commands
- [x] Iterative formula tuning with Pranav:
  - recent_play_ratio replaced last-played-date recency
  - clickrow + playbtn + remote as intentional (Alexa fix)
  - MIN_MEANINGFUL_LISTENS 3 → 5
  - Weights: log_play 0.30, completion 0.25, recent 0.20, active 0.15, skip 0.10
- [x] Staff tester round 1: 38 tests added, 1 bug found (timezone)
- [x] Staff auditor round 1: 6 findings, all fixed
- [x] Staff tester round 2: 52 dedup + 6 engagement tests added
- [x] Staff auditor round 2: 8 findings, all fixed
- [x] Real data verified: 669 songs scored, top 10 approved by Pranav

## Day 3: WHOOP Personal Intelligence
### Implementation (DONE)
- [x] config.py — threshold constants (tiers, fatigue window, sleep/baseline)
- [x] db/queries.py — get_recoveries_in_range, get_sleeps_in_range (8 tests)
- [x] intelligence/baselines.py — HRV/RHR/sleep stage baselines + sleep debt (26 tests)
- [x] intelligence/trends.py — 7-day slopes + consecutive day detection (21 tests)
- [x] intelligence/sleep_analysis.py — deficit/adequacy vs personal norms (13 tests)
- [x] intelligence/state_classifier.py — 8-state recovery-first classifier (45 tests)
- [x] main.py — classify-state CLI command with --date flag
- [x] Fixed multi-sleep-per-date bug in debt + stage baseline calculations
- [x] Redesigned classifier: recovery-first 5-tier system (replaced weighted scoring)
- [x] Renamed single_bad_night → poor_recovery across 8 files
- [x] Fixed _is_debt_low threshold (mean - SD → mean), peak_readiness 25 → 47 days
- [x] Validated on all 823 real recovery days, last 30 days spot-checked with Pranav
- [x] Staff tester audit: 6 HIGH + 9 MEDIUM gaps found, all fixed
- [x] Staff auditor review: 1 MUST FIX + 5 SHOULD FIX found, all fixed

## Day 4 Pre-Work: BPM Experiments (DONE)
- [x] Audio source experiments: Strategies A-D (YouTube variants, Spotify previews, duration-verified YouTube)
- [x] Strategy D (duration-verified YouTube) confirmed best: 24/25 correct audio files
- [x] Essentia classical BPM: 8/24 within ±5 BPM. Works for English (4/5), fails on Indian music (3/13)
- [x] TempoCNN neural BPM: identical accuracy to classical Essentia (8/24). Same Western training bias. Dropped.
- [x] GPT-4o-mini LLM BPM: 8/25 within ±5. Complementary to Essentia — fails on different songs. Combined = 14/25.
- [x] Model shootout: GPT-4o (6/25), GPT-4.1 (2/25), Claude Sonnet (7/25), Claude Opus (5/25). Smaller > larger for BPM recall.
- [x] Prompt engineering: "Database recall" framing best (9/25, MAE 13.1 vs 18.8 baseline)
- [x] External API hunt: Soundcharts (premium), GetSongBPM (blocked), SongBPM.com (poor), HuggingFace (same Essentia data). No free DB covers Indian music.
- [x] ±10 BPM tolerance validated: zero state-bucket misrouting
- [x] Decision: GPT-4o-mini + database-recall prompt + Essentia hybrid (Essentia for English, LLM for Indian)
- [x] Cleanup: deleted experiment scripts, TempoCNN model/code, fixed .gitignore, cleaned worktrees

## Day 4 Pre-Work: Property Evaluation (DONE)
- [x] Built `scripts/property_evaluation.py` — comprehensive Essentia analysis on 24 Strategy D files
- [x] Looked up Tunebat/SongBPM ground truth for key/mode (all 25 songs)
- [x] Key/Mode: 58% exact, 92% musically usable. Dominant confusion (3/6 wrong) is harmless for sequencing. Decision: Essentia sufficient.
- [x] Energy: RMS/0.25 broken (46% ceiling). Tested Loudness, P90, sigmoid, percentile, composites — all worse than RMS/0.35 (71%). Decision: Fix normalization to 0.35.
- [x] Danceability: DFA gives 42% (worse than random). Measures rhythmic regularity, not danceability. Decision: LLM only.
- [x] Acousticness: SCT 33% (random). Spectral Flatness 67%. Decision: Switch to flatness-based.
- [x] Instrumentalness: ZCR 46% wrong on vocal songs. Decision: LLM only.
- [x] Applied code fixes: `essentia_analyzer.py` (energy divisor, acousticness algorithm), updated tests
- [x] 414 tests passing

## Day 4: LLM Song Classification (~669 songs)
_Next up — informed by property evaluation decisions above_

## Day 5: Matching Engine (engagement-weighted)
_Not started_

## Day 6: Playlist Creation + End-to-End Flow
_Not started_

## Day 7: Sequencing + Polish + Hardening
_Not started_
