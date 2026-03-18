# Attuned — Current Status

**Last updated:** Mar 17, 2026
**Current phase:** Day 2 complete. Engagement scoring live on real data.
**Next action:** Day 3 — WHOOP personal intelligence (baselines, trends, sleep analysis, state classifier).

---

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

- Day 3: WHOOP personal intelligence (baselines, trends, sleep analysis, state classifier)
- Day 4: LLM song classification (~669 songs)
- Day 5: Matching engine (engagement-weighted)
- Day 6: Playlist creation + end-to-end flow
- Day 7: Sequencing + polish + hardening

## API Keys Status

- WHOOP: registered, OAuth working, full history synced
- Spotify: registered, OAuth working, library synced
- OpenAI: has $5 credits (for song classification, Day 4)
