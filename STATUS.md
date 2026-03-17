# Attuned — Current Status

**Last updated:** Mar 17, 2026
**Current phase:** Day 1 complete (Tier 1 + Tier 2). Extended history ingested. API clients built and tested with mocks.
**Next action:** Register WHOOP + Spotify developer apps, add credentials to `.env`, run Tier 3 integration.

---

## What's Done (Day 1)

### Tier 1 — Offline, fully tested
- `config.py` — all constants, thresholds, lazy env var loaders
- `db/schema.py` — 7 tables + indexes, WAL mode, foreign keys
- `db/queries.py` — all CRUD functions (listening_history, songs, whoop_recovery, whoop_sleep, tokens)
- `spotify/sync.py` — extended history ingestion: parses 33,311 valid audio records → 32,729 unique history rows, 5,701 songs, 676 with 5+ meaningful plays
- `main.py` — CLI with `ingest-history`, `sync-whoop`, `sync-spotify`, `sync-all`, `auth-whoop`, `auth-spotify`, `generate` (stub)

### Tier 2 — API clients, tested with mocks
- `whoop/auth.py` — OAuth flow, token storage/refresh with 5-min expiry buffer
- `whoop/client.py` — recovery/sleep API calls, pagination, response parsing, timezone-aware date derivation
- `whoop/sync.py` — orchestration: get token → call client → store in DB
- `spotify/auth.py` — custom Spotipy CacheHandler backed by SQLite tokens table
- `spotify/client.py` — liked songs, top tracks, batch metadata extraction

### Tests
- **120 tests, all passing** across 8 test files
- Coverage: config (15), schema (8), queries (25), spotify_sync (20), whoop_auth (10), whoop_client (22), whoop_sync (3), spotify_auth (4), spotify_client (13)

### Audit findings fixed
- SQL injection in `count_rows()` — added allowlist validation
- SQL injection in `_compute_basic_song_stats()` — switched to parameterized query
- DRY violation in song source/date merging — extracted `_merge_sources`, `_earlier_date`, `_later_date` helpers

## What's Left (Tier 3 — needs API keys)

1. Register WHOOP + Spotify apps, add credentials to `.env`
2. Run OAuth flows (`python main.py auth-whoop`, `python main.py auth-spotify`)
3. Pull today's WHOOP data (`python main.py sync-whoop`)
4. Sync liked songs + top tracks + batch metadata (`python main.py sync-spotify`)
5. Verify full DB populated with real data

## Blockers

- WHOOP developer app: needs to be registered at developer.whoop.com
- Spotify developer app: needs to be registered at developer.spotify.com

## API Keys Status

- WHOOP: not yet (need to register app)
- Spotify: not yet (need to register app)
- OpenAI: has $5 credits (for song classification, Day 4 — 676 songs ~$0.68)
