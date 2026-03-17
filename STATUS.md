# Attuned — Current Status

**Last updated:** Mar 17, 2026
**Current phase:** Day 2 complete. Engagement scoring implemented, tested, audited.
**Next action:** Run `python main.py sync-spotify` to fetch remaining `duration_ms` for ~137 songs, then `python main.py compute-engagement` on real data + spot-check top 10.

---

## What's Done (Day 2)

### Engagement Scoring
- `spotify/engagement.py` — 5-signal engagement scoring (completion_rate, active_play_rate, skip_rate, log-normalized play count, recency decay)
- Weighted formula: `log_play*0.35 + completion*0.25 + active*0.20 + (1-skip)*0.10 + recency*0.10`
- Songs missing `duration_ms` scored with redistributed weights (no completion_rate component)
- Songs below `MIN_MEANINGFUL_LISTENS` (3) excluded
- `main.py` — `compute-engagement` CLI command with distribution summary + top 10 display
- Engagement scoring auto-runs at end of `sync-spotify`

### Tests
- **177 tests, all passing** across 9 test files
- New: `test_engagement.py` — 57 tests covering all signals, edge cases, boundaries, idempotency, weight redistribution, timezone handling, orphan data, NULL fallbacks

### Staff audit findings (all fixed)
- `_parse_date` timezone bug — `.replace(tzinfo=utc)` → `.astimezone(utc)` for non-UTC offsets
- `duration_ms = 0` wrong branch — now routes to redistributed-weight path
- Recency component unclamped for future dates — added `min(1.0, ...)` clamp
- Docstring contradicted code on eligibility criteria — corrected
- Weak test assertion on completion_rate cap — strengthened to `pytest.approx(1.0)`
- Unused import removed

## What's Done (Day 1)

### Tier 1 — Offline, fully tested
- `config.py` — all constants, thresholds, lazy env var loaders
- `db/schema.py` — 7 tables + indexes, WAL mode, foreign keys
- `db/queries.py` — all CRUD functions (listening_history, songs, whoop_recovery, whoop_sleep, tokens)
- `spotify/sync.py` — extended history ingestion: parses 33,311 valid audio records → 32,729 unique history rows, 5,701 songs, 676 with 5+ meaningful plays
- `main.py` — CLI with `ingest-history`, `sync-whoop`, `sync-spotify`, `sync-all`, `auth-whoop`, `auth-spotify`, `compute-engagement`, `generate` (stub)

### Tier 2 — API clients, tested with mocks
- `whoop/auth.py` — OAuth flow, token storage/refresh with 5-min expiry buffer
- `whoop/client.py` — recovery/sleep API calls, pagination, response parsing, timezone-aware date derivation
- `whoop/sync.py` — orchestration: get token → call client → store in DB
- `spotify/auth.py` — custom Spotipy CacheHandler backed by SQLite tokens table
- `spotify/client.py` — liked songs, top tracks, batch metadata extraction

## What's Left

### Day 2 remaining
1. Run `python main.py sync-spotify` to fetch `duration_ms` for ~137 songs still missing it
2. Run `python main.py compute-engagement` on real data
3. Spot-check top 10 songs — verify they're recognizable favorites
4. Run integrity SQL queries (distribution, out-of-range check, WHOOP gap check)

### Day 3+
- Day 3: WHOOP personal intelligence (baselines, trends, sleep analysis, state classifier)
- Day 4: LLM song classification (~1,006 songs)
- Day 5: Matching engine (engagement-weighted)
- Day 6: Playlist creation + end-to-end flow
- Day 7: Sequencing + polish + hardening

## API Keys Status

- WHOOP: registered, OAuth working, full history synced (823 recovery, 907 sleep)
- Spotify: registered, OAuth working, liked songs + top tracks synced
- OpenAI: has $5 credits (for song classification, Day 4)
