# Attuned — Current Status

## Current Phase

Day 11-12. 1,048 tests passing. Playlist rotation and quality significantly improved. Spotify rate limit architecture rebuilt. Komal's pipeline partially complete — blocked on Spotify rate limit for metadata backfill (837 songs).

## Last Session (Mar 26, 2026)

Fixed circuit breaker bug (Spotipy strips Retry-After header through MaxRetryError path — missing header now triggers immediate abort). Komal's sync-spotify ran: liked songs (752) + top tracks (3,823) succeeded, but pagination burned the rate limit before metadata fetch started. Audio download completed (7 new clips, rest already cached from shared library).

Playlist rotation overhauled: replaced consecutive-streak counter with days-since-last-appearance (39 songs blocked per playlist, much better rotation). Fixed freshness to use only latest playlist per date (iteration drafts no longer pollute history). Added Bollywood motivational filter (16 songs excluded from non-peak playlists — scene-tied context doesn't fit morning recovery). Manual override for songs the LLM missed tagging.

Generated today's playlist: "Mar 26 — Fuel Up" pushed to Spotify. Cleaned 6 stale playlists from Spotify.

## Blockers

- **Spotify rate limit** — Komal's pagination burned the quota. 837 songs need metadata (2+ listens, playlist candidates). Rate limit clears ~10 PM tonight.

## Next Steps

1. When rate limit clears: targeted metadata fetch for Komal's 837 songs (need `--metadata-only` flag or direct call to avoid re-running pagination)
2. Komal: `analyze-audio` → `recompute-scores` → `generate`
3. Primary user: `sync-spotify` for remaining metadata gaps
4. Automated daily playlist generation (cron or scheduled agent)
5. Motivational song detection improvement (LLM prompt context for Bollywood sports anthems)

## Project Timeline

- **Day 1** — Data foundation: schema, extended history ingestion (33K records), WHOOP + Spotify API clients
- **Day 2** — Engagement scoring: 5-signal formula, dedup (435 groups), 669 songs scored
- **Day 3** — WHOOP intelligence: baselines, trends, sleep analysis, 7-state classifier (825 days)
- **Day 4** — Song classification: LLM + Essentia hybrid, 1,360 songs, 83% product accuracy
- **Day 5** — Matching engine: neuro-score dot product, cohesion, unified ranking, Essentia full library
- **Day 6** — Playlist creation: end-to-end WHOOP → match → Spotify push, era cohesion, dynamic names
- **Day 7** — Hardening: full audit, error handling, near-duplicate dedup, 807 tests
- **Day 8** — Classification fix: Essentia/LLM merge, echo chamber removal, essentia_* columns
- **Day 9** — Second user: Komal onboarding, restorative sleep gate, global rate limit handler
- **Day 10** — Refinement: continuous baseline scaling, sleep dampener, mood affinity, vibe hard cap
- **Day 11** — Rate limit fix: batch removal, circuit breaker, double-retry disabled, pagination throttle
- **Day 12** — Rotation overhaul: days-since-last-appearance, latest-per-day freshness, Bollywood motivational filter, project restructure to playbook spec
