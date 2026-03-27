# Attuned — Task Tracker

## Pre-Build
- [x] Write PRD
- [x] Scaffold project structure
- [x] Create CLAUDE.md, STATUS.md, tasks/
- [x] Deep research: music-ANS, HRV sports science, sleep architecture, LLM classification, iso principle
- [x] Write docs/RESEARCH.md with findings, formulas, and citations
- [x] Update PRD to v2.0 (6 states, 0.0-1.0 scales, concrete thresholds, research-backed decisions)
- [x] Rephase sprint for extended streaming history (PRD v2.1, CLAUDE.md, STATUS.md updated)
- [ ] Review PRD v2.1 + RESEARCH.md
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
- [x] Iterative formula tuning:
  - recent_play_ratio replaced last-played-date recency
  - clickrow + playbtn + remote as intentional (Alexa fix)
  - MIN_MEANINGFUL_LISTENS 3 → 5
  - Weights: log_play 0.30, completion 0.25, recent 0.20, active 0.15, skip 0.10
- [x] Staff tester round 1: 38 tests added, 1 bug found (timezone)
- [x] Staff auditor round 1: 6 findings, all fixed
- [x] Staff tester round 2: 52 dedup + 6 engagement tests added
- [x] Staff auditor round 2: 8 findings, all fixed
- [x] Real data verified: 669 songs scored, top 10 manually approved

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
- [x] Validated on all 823 real recovery days, last 30 days spot-checked manually
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
- [x] LLM vs Essentia shootout for energy + acousticness: LLM worse (42%/50% vs 71%/62%). Essentia confirmed for both.
- [x] Staff engineer audit: 3 MUST FIX + 8 SHOULD FIX, all resolved
- [x] Staff tester audit: 4 HIGH + 5 MEDIUM gaps, all HIGH resolved, 7 new tests added
- [x] 421 tests passing, 8 commits pushed to main

## Day 4: LLM Song Classification (DONE)
### Implementation
- [x] classification/profiler.py — sigmoid/gaussian math + parasympathetic/sympathetic/grounding scoring (62 tests)
- [x] db/queries.py — get_songs_needing_llm query for hybrid pipeline (10 tests)
- [x] config.py — LLM constants, Indian genre tags, API key getters (8 tests)
- [x] classification/llm_classifier.py — LLM classification pipeline with Essentia merge (78 tests)
- [x] main.py — classify-songs CLI command with --provider flag
- [x] Staff engineer audit + staff tester audit — all findings fixed
- [x] Confidence experiment: 25 songs × 3 approaches → rich context wins for obscure songs
- [x] BPM strategy switch: LLM primary (was Essentia primary) — fixes octave errors
- [x] Full library classified: 1360 songs, 0 failures
- [x] 579 tests passing

### Known Accuracy Gaps (for Day 5 tuning)
- [x] Devotional BPM: fixed — reclassification with updated prompt, Namo Namo now BPM=80
- [x] Energy normalization: fixed — switched from RMS to onset rate energy
- [x] Bucket evaluation too coarse — matching engine will use continuous scores, not buckets

## Day 4b: Accuracy Tuning (DONE)
- [x] Root cause analysis of 10 failing songs → 3 distinct causes identified
- [x] `--reclassify` flag for classify-songs, `--force` for analyze-audio
- [x] `recompute-scores` CLI command (2-second local recompute, no API calls)
- [x] LLM valence calibration in prompt (sad/devotional songs were over-rated)
- [x] `felt_tempo` field added to schema + prompt (LLM mostly ignores, but ready)
- [x] Fixed `has_essentia` exact-match bug (wiped Essentia data during reclassification)
- [x] GRND tempo gaussian narrowed (sigma 15→10) to reduce gravity well
- [x] Replaced weighted-average blend with confidence-aware ensemble
- [x] Added LLM energy/acousticness estimates as fallback when no Essentia
- [x] Validated on fresh 34-song set (56%→65% after energy fix)
- [x] Error severity analysis: 93% correct or adjacent, only 7% catastrophic
- [x] 617 tests passing
- [x] Full reclassification with LLM energy/acousticness — 1360/1360, 100% energy coverage
- [x] Staff tester + staff auditor on Day 4b code changes (2 HIGH + 1 MUST FIX, all fixed)
- [x] Fresh 34-song validation set — cross-validated accuracy
- [x] Product-relevant evaluation: 83% product accuracy, 86% safety, 93% within one bucket
- [x] CPO assessment: classification layer is good enough. Continuous scores serve the matching engine.
- [x] 621 tests passing

## Day 5a: Matching Engine v1 (DONE — superseded by 5b)
- [x] config.py — TARGET_RANGES, MATCH_WEIGHTS, selection weights, variety penalties
- [x] matching/state_mapper.py — state → target property ranges (10 tests)
- [x] matching/query_engine.py — scoring + selection pipeline (49 tests)
- [x] db/queries.py — insert_generated_playlist, get_recent_playlist_track_uris
- [x] main.py — match-songs CLI with --state and --date flags
- [x] Real data validation: fatigue/peak/baseline/poor_recovery all produce intuitively correct playlists
- [x] Staff engineer audit: 1 critical bug (fallback breakdown), fixed + tested
- [x] 680 tests passing

## Day 5b: Matching Engine Rewrite (DONE)
- [x] Replaced range-box scoring with neuro-score dot product
- [x] Diagnosed para↔grnd correlation (r=0.921) via 18 diagnostic analyses
- [x] Decorrelated grounding formula: BPM 85→90, energy 0.35→0.40, instrumentalness flipped, acousticness gaussian, valence 0.45→0.55
- [x] Integrated mood tags into profiler as 15% weight (semantic dimension orthogonal to audio)
- [x] Widened state profile gaps: fatigue (0.95/0/0.05), physical (0.60/0/0.40) — gap 0.35 vs old 0.15
- [x] Pool-based selection → unified ranking with recent anchors
- [x] Variety penalty (0.3x multiplier) → freshness nudge (0.02 subtraction tiebreaker)
- [x] Product evaluation: 0/140 weak matches, ~74% optimal, ~45% daily turnover
- [x] Para↔Grnd correlation: 0.921 → 0.776
- [x] Detailed session log: tasks/matching_engine_learnings.md
- [x] Fixed download-audio to use duration-verified Strategy D only (removed unreliable strategies)
- [x] Added --all flag to download audio for all classified songs (skip Spotify preview, yt-dlp only)
- [x] Staff engineer audit: 3 MUST FIX + 4 SHOULD FIX, all resolved
- [x] 697 tests passing

## Essentia Full Library (DONE)
- [x] Audio download: 1,348/1,360 clips (99.1%). Fixed with --ignore-errors, 45s tolerance, title-match fallback.
- [x] Recovered 197 missing duration_ms from listening history (max ms_played)
- [x] Essentia analysis: 1,348 songs analyzed. Fixed transient failures with re-run.
- [x] Fixed --force bug: Essentia now does targeted UPDATE, preserves LLM fields (valence, mood_tags, etc.)
- [x] LLM reclassification: 1360/1360 done, 0 failures. Full Essentia+LLM blend.
- [x] Recompute scores: 1360 songs. Para↔Grnd r=0.638 (was 0.921 at start of day).
- [x] Validation: 0/140 weak matches, 99.1% Essentia-validated.
- [x] Staff audit: 2 MUST FIX + 5 SHOULD FIX, all resolved. 774 tests passing.

### Remaining data gaps
- [ ] **12 songs LLM-only** — 6 no YouTube results, 6 missing duration_ms (Spotify rate-limited). Acceptable — 99.1% coverage.
- [ ] **~869 songs missing release_year** — Spotify rate limit. Run `python main.py backfill-release-years` when limit clears.

## Day 6: Playlist Creation + End-to-End Flow (DONE)
- [x] matching/generator.py — full pipeline: WHOOP state → match → Spotify push → DB log (26 tests)
- [x] spotify/playlist.py — create playlist, description truncation, private by default (13 tests)
- [x] main.py generate — CLI with --date and --dry-run flags
- [x] Dynamic playlist names from neuro profile + recovery (Slow Down, Fuel Up, Full Send, etc.)
- [x] Description: purpose + genre + mood ("Calming your nervous system · Bollywood · Melancholy, Introspective")
- [x] Era cohesion integrated into matching (genre-aware sigma, weight 0.20)
- [x] LLM prompt improved with release_year + Bollywood artist/composer context
- [x] Backfill command with rate-limit handling (auto-retry on 429)
- [x] Dry-run tested: baseline, fatigue, peak — all produce correct playlists
- [x] 794 tests passing

### Blocked on Spotify rate limit
- [ ] Finish release_year backfill: `python main.py backfill-release-years`
- [ ] Push first real playlist to Spotify: `python main.py generate`

## Day 7: Polish + Hardening (DONE)
- [x] Full codebase audit, 25 files touched, 807 tests passing
- [x] Near-duplicate dedup, no-data transparency, confidence clamped, error handling hardened

## Day 8: Essentia/LLM Merge Fix + Validator Cleanup
### Done (code changes)
- [x] Remove Essentia energy/acousticness hints from LLM prompt (echo chamber fix)
- [x] Add `_merge_energy()` / `_merge_acousticness()` smart merge helpers
- [x] Fix `_merge_with_essentia()` to use smart merge instead of blind Essentia trust
- [x] Guard Essentia re-analysis: don't overwrite energy/acousticness when LLM data exists
- [x] Remove genre outlier validation (182/300 false positives)
- [x] Update `_check_essentia_llm_disagreement()` to compare original values
- [x] Extend `recompute-scores` to re-merge energy/acousticness
- [x] Create docs/CLASSIFICATION_VALIDATION.md
- [x] 941 tests passing (134 new/updated)
- [x] HRV CV research — confirmed gap between spec and implementation
- [x] Add `essentia_energy`/`essentia_acousticness` columns for idempotent recompute
- [x] Schema migration (`_migrate_add_essentia_columns`)
- [x] Essentia analyzer always writes raw values to `essentia_*` columns
- [x] `get_songs_needing_llm` reads from `essentia_*` columns (not merged `energy`/`acousticness`)
- [x] `recompute-scores` reads from `essentia_*` columns (idempotent)
- [x] `validate_all_classifications` passes `essentia_*` values to disagreement check
- [x] Guard: when `essentia_*` NULL, keep existing merged values (don't regress to LLM-only)
- [x] 957 tests passing (16 new/updated)

---

## What's Done (Day 9)

### Primary user backfill (steps 1-6)
- [x] 1. `analyze-audio --force` — 1,350 songs analyzed, 0 failures
- [x] 2. `recompute-scores` — 1,346 re-merged from essentia_* columns
- [x] 3. `validate-classifications` — 983 flagged (72%, mostly acousticness gaps)
- [x] 4. `classify-songs --reclassify` — 1,360 reclassified, 0 failures
- [x] 5. `recompute-scores` — 1,360 recomputed
- [x] 6. `validate-classifications` — **zero flags** (reclassification fixed everything)
- [x] 7. No code to commit (DB is gitignored)

### Second user onboarding (steps 10-12)
- [x] 10. `sync-spotify --profile <name>` — liked + top tracks synced, engagement-scored
- [x] 12. `classify-songs --profile <name>` — classified, 0 failures
- [x] 13. `generate --profile <name> --dry-run` — "Fuel Up", 20 tracks (baseline, no WHOOP sync)

### System improvements
- [x] Restorative sleep gate on accumulated fatigue classifier (committed, pushed)
- [x] Global Spotify rate limit handler — all API calls auto-retry on 429 (committed, pushed)
- [x] PRODUCT_DECISIONS.md — chronological log of all product decisions (committed, pushed)
- [x] Doc cleanup — each doc has one job (committed, pushed)
- [x] Today's playlist regenerated — "Fuel Up" (baseline, not fatigue)
- [x] `fetch_batch_metadata` fix — fills ALL missing metadata in one pass (974 tests passing)
- [x] `onboard` CLI command — single command for new user setup (committed, pushed)
- [x] `docs/ONBOARDING.md` — step-by-step onboarding guide (committed, pushed)
- [x] 3-second throttle on single-track metadata fallback (committed, pushed)
- [x] Full codebase audit — 10 issues found across all API layers, all fixed (committed, pushed)
  - Spotify availability check batched to 50, URI validation, fallback time estimate warning
  - LLM 60-second timeout on OpenAI + Anthropic calls
  - Essentia logs actual exceptions, warns on zero analyzed
  - WHOOP pagination validates response structure
  - Classification merge warns on missing critical fields
- [x] 974 tests passing, 7 commits pushed

### Second user onboarding — additional
- [x] `sync-whoop-history --profile <name>` — full recovery history synced

### Day 10 improvements
- [x] Continuous baseline scaling — recovery delta picks calm-to-energy position (replaces static profile)
- [x] Sleep quality dampener — sleep architecture (65% weight) blended with recovery delta (35%) for baseline
- [x] Weighted mood affinity table — 64 tags with research-backed weights replacing binary sets (12 studies)
- [x] Recent anchors — 5 recently-played songs guaranteed in every playlist
- [x] Motivational songs excluded from anchors — gym context songs don't get guaranteed morning slots
- [x] Era hard cap — production era gaps (era_sim < 0.05) cap total similarity at 0.30
- [x] Vibe hard cap — energy+acoustic+dance similarity < 0.15 caps total similarity at 0.30
- [x] Anchor vibe outlier — anchors outlier on all 3 vibe dimensions (>1.5 SD) dropped from guaranteed status
- [x] WHOOP Insights doc — 10,313 words, 18 research citations, athlete-vs-human thesis
- [x] All old Spotify playlists cleaned — only latest exists
- [x] Docs scrubbed for public release — personal names, dollar amounts, biometric data removed
- [x] README rewritten for public GitHub
- [x] 1,030 tests passing

---

## Day 11: Spotify Rate Limit Architecture Fix (DONE)
- [x] Remove all `sp.tracks()` batch calls from 6 production files (never worked in dev mode)
- [x] All fetching uses `sp.track()` with 3-second throttle
- [x] Disable Spotipy's hidden urllib3 retry layer (`retries=0, status_retries=0`)
- [x] Circuit breaker: Retry-After > 60s → `SpotifyRateLimitError` (abort, don't sleep for hours)
- [x] Server error retry: 500/502/503/504 retry 3 times with 5s delay
- [x] Pagination throttle: 1-second delay between `sp.next()` calls
- [x] Renamed `fetch_batch_metadata` → `fetch_track_metadata`
- [x] 14 new tests, 1,044 total passing
- [x] 2 commits pushed

## Blocked (Spotify API — daily rate limit, clears ~Mar 26 afternoon)

### When rate limit clears — run these:
- [ ] `python main.py sync-spotify` — fill missing release_years/duration_ms
- [ ] `python main.py --profile komal sync-spotify` — fill second user's missing metadata (~2,643 songs, ~2.2 hours)

---

## What's Left

### Second user — full pipeline (sequential, after rate limit clears)
- [ ] Re-run `sync-spotify --profile <name>` to fill missing metadata
- [ ] `download-audio --profile <name>` (~2-4 hours, yt-dlp)
- [ ] `analyze-audio --profile <name>`
- [ ] `recompute-scores --profile <name>` (NO reclassification needed — prompt is already correct)
- [ ] `generate --profile <name>` — first real playlist (only after full pipeline complete)

### Primary user — after rate limit
- [ ] Re-run `sync-spotify` to fill missing metadata
- [ ] 12 songs still LLM-only (no YouTube audio) — low priority, marginal impact

### Code changes — not yet built
- [ ] `/onboard` skill — bulletproof end-to-end onboarding. Build ONLY after Komal's playlist ships and is approved. Encodes every rate limit lesson, correct step ordering, idempotent resume, filtered metadata fetch, dry-run table at end. The skill is the proof we got it right.
- [ ] HRV CV modifier in `state_mapper.py` — adjusts neuro profile when day-to-day HRV variability is high. Same pattern as recovery delta modifier. Research done, design in SYSTEM_LOGIC.md. ~1 hour.
- [ ] Quality testing framework — automated before/after comparison for classifier changes. ~2 hours.
- [ ] Era cohesion sigma tuning — tune Gaussian decay values based on real playlist output

### Future features — designed but deferred
- [ ] **Playlist taste import** — mine user playlists for co-occurrence, add as cohesion signal. Needs `playlist-read-private` scope, re-auth. Research done in docs/playlist_cohesion_research.md.
- [ ] **WHOOP webhook** — auto-generate playlist when recovery is calculated each morning. Currently manual `generate` command.
- [ ] **User preferences** — genre exclusions, iso principle preference, cold-start questions. user_preferences table (key-value).
- [ ] **Conversational DJ** — natural language interface ("give me something for a walk"). Separate feature entirely.
