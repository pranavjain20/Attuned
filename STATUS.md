# Attuned — Current Status

**Last updated:** Mar 25, 2026
**Current phase:** Day 11. 1,044 tests passing. Spotify API rate limit architecture completely rebuilt: removed all batch sp.tracks() calls (never worked in dev mode), disabled Spotipy's hidden double-retry layer, added circuit breaker for daily quota exhaustion, throttled all pagination. Three consecutive 24-hour lockouts traced to root cause and fixed.
**Next action:** When rate limit clears (~Mar 26 afternoon), run `python main.py --profile komal sync-spotify` to complete second user's metadata backfill (2,643 songs, ~2.2 hours). Then audio pipeline.

---

## What's Done (Day 11: Spotify Rate Limit Fix)

### Batch endpoint removal
- Removed all `sp.tracks()` (batch) calls from 6 production files — batch returned 403 from Day 1 on dev-mode app
- All metadata, availability, and preview URL fetching now uses `sp.track()` with 3-second throttle
- Renamed `fetch_batch_metadata` → `fetch_track_metadata`, `SPOTIFY_BATCH_SIZE` → `SPOTIFY_PROGRESS_LOG_INTERVAL`
- Updated 7 test files, 3 docs, 1 lesson

### Rate limit architecture rewrite
- Disabled Spotipy's built-in urllib3 retry (`retries=0, status_retries=0`) — was silently retrying 429s up to 3 times, sleeping up to 6 hours each
- `_RateLimitedSpotify` wrapper is now the single retry layer
- Circuit breaker: Retry-After > 60s → `SpotifyRateLimitError` immediately (daily quota, not burst)
- Server error retry: 500/502/503/504 retry 3 times with 5s delay
- Pagination throttle: 1-second delay between `sp.next()` calls in liked songs + top tracks

### Root cause of three-day lockout
1. Batch sp.tracks() → 403 → fallback to individual calls (initially unthrottled)
2. Spotipy's hidden urllib3 retry + our wrapper = double retry = up to 19 HTTP requests per 429
3. No circuit breaker — Retry-After: 84580s caused code to sleep for 23 hours
4. Running sync-spotify with broken code as diagnostic test burned quota on day 3

### 1,044 tests passing, 2 commits pushed.

---

## What's Done (Era Cohesion + Playlist Generation)

### Era Cohesion
- Genre-aware Gaussian decay on release year: hip-hop σ=2 (tight), ghazal σ=12 (loose), Bollywood σ=6
- Uses larger sigma of two songs (more permissive wins). None year → 0.5 neutral.
- `release_year` column added to songs table with migration
- Spotify client extracts release_year from album.release_date
- `backfill-release-years` CLI command
- Batch endpoint fix: `sp.tracks()` (50/call) instead of `sp.track()` (1/call)
- 491/1,360 classified songs have release_year data

### Cohesion Weight Tuning
- Era weight 0.10 → 0.20 (genre 0.25→0.20, mood 0.20→0.15)
- At 0.10: max era swing was 0.06 — couldn't exclude cross-era songs
- At 0.20: max era swing is 0.12 — correctly filters 1999 songs from 2010s clusters
- Tested: Chunnari Chunnari (1999) excluded from 2009–2018 Bollywood cluster

### LLM Prompt Improvement
- Release year added to classification prompt: `"Jee Le Zaraa" by Vishal Dadlani (album: Talaash) (2012)`
- Helps disambiguate songs with common Hindi phrases as titles
- Both `get_songs_needing_llm` queries updated to include release_year

### Playlist Generation (dry-run tested)
- State: Baseline
- 20 tracks selected, mean cohesion 0.612, dominant genre: Bollywood
- Era range with full-data pool: 2009–2018 (tight 2010s cluster)

### Known Issues
- Jee Le Zaraa (Talaash) misclassified as upbeat (energy 0.7, valence 0.8) — actually slow/dark. Release year in prompt should fix on reclassification.
- 64% of classified songs still missing release_year (rate-limited)

### 957 tests passing.

---

## What's Done (Day 7: Audit + Hardening)

Full codebase audit (6 parallel reviewers), 25 files touched. Near-duplicate playlist dedup (69 pairs in library), no-data transparency warning, confidence clamped to [0,1], release_year=0 cleaned. Error handling hardened: conn.close() try/finally on all 16 CLI handlers, httpx timeouts, token refresh guards. Dead code removed (6 items). 807 tests passing.

## What's Done (Day 6: Playlist Creation + End-to-End)

Full pipeline: WHOOP state → match → Spotify push → DB log. Dynamic playlist names from neuro profile + recovery. Era cohesion with genre-aware sigma. release_year 97.7% coverage. Real playlists pushing to Spotify.

## What's Done (Day 5: Matching Engine + Essentia Full Library)

Neuro-score dot product, seed-and-expand cohesion, unified ranking, freshness nudge. Profiler decorrelated (r=0.638). Essentia on 99.1% of library. 0/140 weak matches.

## What's Done (Day 4: LLM Classification + Accuracy)

1360 songs classified. Profiler + LLM + Essentia hybrid. 83% product accuracy.

## What's Done (Day 3: WHOOP Intelligence)

Baselines, trends, sleep analysis, 7-state classifier. 825 recovery days.

## What's Done (Day 2: Engagement Scoring)

5-signal scoring, dedup, 669 songs scored.

## What's Done (Day 1: Data Foundation)

Extended history ingestion, WHOOP/Spotify APIs, schema, 33K records.

---

## What's Next

1. **Playlist taste import** — co-occurrence from user playlists as cohesion signal
2. **Onboarding** — preferences, genre exclusions, cold-start flow
3. **12 songs** still LLM-only (no YouTube audio available)

## API Keys Status

- WHOOP: registered, OAuth working, full history synced
- Spotify: registered, OAuth working, library synced
- OpenAI: credits available
