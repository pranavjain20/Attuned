# Attuned — Build Plan

Phased engineering roadmap. What's been built, what's next, and in what order.

---

## Completed Phases

| Phase | What | Key Deliverable |
|-------|------|-----------------|
| Day 1 | Data foundation | Schema, extended history ingestion (33K records), WHOOP + Spotify API clients |
| Day 2 | Engagement scoring | 5-signal scoring, dedup (435 groups), 669 songs scored |
| Day 3 | WHOOP intelligence | Baselines, trends, sleep analysis, 7-state classifier (825 recovery days) |
| Day 4 | Song classification | LLM classification (1,360 songs), Essentia hybrid, 83% product accuracy |
| Day 5 | Matching engine | Neuro-score dot product, seed-and-expand cohesion, unified ranking |
| Day 6 | Playlist creation | End-to-end pipeline: WHOOP state → match → Spotify push → DB log |
| Day 7 | Hardening | Full codebase audit, error handling, near-duplicate dedup |
| Day 8 | Classification fix | Essentia/LLM merge fix, echo chamber removal, essentia_* columns |
| Day 9 | Second user | Komal onboarding, restorative sleep gate, global rate limit handler |
| Day 10 | Refinement | Continuous baseline scaling, sleep dampener, weighted mood affinity, vibe hard cap |
| Day 11 | Rate limit fix | Removed all batch calls, circuit breaker, disabled double-retry, pagination throttle |

## Current Phase

**Blocked on Spotify rate limit** (clears ~Mar 26 afternoon). Then:

1. `sync-spotify` for both profiles — metadata backfill (2,643 songs for second user)
2. Second user audio pipeline: download → analyze → recompute → generate
3. Primary user metadata backfill

## Next Phases

### Second user playlist generation
- Dependencies: rate limit clear, metadata backfill
- Scope: ~2.2 hours metadata + ~2-4 hours audio download + ~1 hour analysis
- Deliverable: first real playlist for second user

### HRV CV modifier
- Dependencies: none (can be built in parallel)
- Scope: ~1 hour — adjusts neuro profile when day-to-day HRV variability is high
- Design: in SYSTEM_LOGIC.md

### Playlist taste import
- Dependencies: `playlist-read-private` scope (re-auth required)
- Scope: ~2 hours — mine user playlists for co-occurrence as cohesion signal
- Research: in reference/playlist_cohesion_research.md

### WHOOP webhook
- Dependencies: playlist generation working for both users
- Scope: ~1 hour — auto-generate playlist when morning recovery is calculated
- Current: manual `generate` command

### User preferences
- Dependencies: multi-user working
- Scope: ~2 hours — genre exclusions, cold-start questions, user_preferences table
