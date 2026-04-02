# Attuned — Current Status

## Current Phase

Day 17. 1,048 tests passing. 3 active users (Pranav, Komal, Saumya). Fixed calming ≠ sad (target valence), patriotic exclusion, era cohesion tightening, anchor era filter. Remote OAuth live.

## Last Session (Apr 1-2, 2026)

Onboarded Saumya via remote OAuth. Fixed calming playlists including depressing songs (profiler valence center + target valence in matching). Fixed patriotic songs leaking into recovery playlists. Tightened era cohesion (hard cap 0.30→0.15) and added 15-year anchor era filter so 1958/1999 songs don't appear in 2020s playlists. Fixed Ab To Forever misclassification. Created /generate-playlists skill. Generated playlists for all 3 users.

## Blockers

- 495 of Saumya's songs missing audio clips (YouTube rate limited). Retry when unblocked.
- Spotify dev mode: 5-user cap per app. Friends register own dev app (2 min). Documented in Attuned-Auth repo.

## Next Steps

1. Download remaining 495 audio clips for Saumya
2. Bollywood energy ML model — label 50-100 songs, train on Essentia features
3. Automated daily generation (cron)
4. Natural language playlist requests (v2 direction captured)
5. Weight tuning from daily feedback

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
- **Day 17** — Third user (Saumya), remote OAuth, calming ≠ sad (target valence), patriotic exclusion, era cohesion tightening, anchor era filter, /generate-playlists skill
