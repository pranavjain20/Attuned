# Attuned — Current Status

## Current Phase

Day 18. 1,048 tests passing. 3 active users. Natural language playlist engine built (v2 Phase 1) — users describe what they want, LLM translates to neuro profile calibrated by WHOOP recovery. Saumya audio coverage at 85%.

## Last Session (Apr 3, 2026)

Built NL playlist engine: LLM translates natural language ("going to gym, hype me up") to neuro profile + target valence, calibrated by WHOOP recovery. Same word "upbeat" produces different playlists at 35% vs 90% recovery. LLM decides context-specific decisions (gym hype → allow motivational songs, date hype → don't). Tested 9 queries successfully. Downloaded Saumya's remaining clips to 85% (1,959/2,289). Essentia running on new clips.

## Blockers

- 330 of Saumya's songs can't be downloaded (missing duration_ms or yt-dlp timeouts). Near ceiling.
- Spotify dev mode: 5-user cap per app. Friends register own dev app. Documented in Attuned-Auth repo.

## Next Steps

1. Test more NL prompts live + tune
2. Recompute Saumya's scores after Essentia finishes
3. Automated daily generation (cron)
4. WhatsApp integration for NL requests (Phase 2)
5. Per-user Spotify dev app credentials in code

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
- **Day 12** — Continuous intelligence: 12-signal weighted profile, cosine similarity, playlist rotation overhaul, Bollywood motivational filter, Komal's first live playlist
- **Day 13** — Polish: auto-classify new songs, dynamic library sync, `/onboard` skill, public-ready audit, MIT license
- **Day 14** — Cohesion fix: IDF genre similarity, BPM hard cap, original_release_year, opening energy
- **Day 15** — Audio pipeline rebuild: 60s-from-start clips, YouTube auth, parallel downloads, 7% intro measurement, dual-source classification documented
- **Day 16** — Essentia validation: 60% ceiling confirmed for Bollywood, ML model identified as next step, playlists generated with corrected energy
- **Day 17** — Third user (Saumya), remote OAuth, calming ≠ sad (target valence), patriotic exclusion, era cohesion tightening, /generate-playlists skill
- **Day 18** — Natural language playlist engine (v2 Phase 1), LLM-based context decisions (gym vs date hype), Saumya audio 78%→85%
