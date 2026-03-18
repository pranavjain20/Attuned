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
_Not started_

## Day 4: LLM Song Classification (~669 songs)
_Not started_

## Day 5: Matching Engine (engagement-weighted)
_Not started_

## Day 6: Playlist Creation + End-to-End Flow
_Not started_

## Day 7: Sequencing + Polish + Hardening
_Not started_
