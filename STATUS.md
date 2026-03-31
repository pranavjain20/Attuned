# Attuned — Current Status

## Current Phase

Day 15. 1,048 tests passing. Audio pipeline rebuild: all clips being re-downloaded as 60s-from-start with YouTube auth. 5 parallel processes running, ~7 hours to completion. IDF genre similarity, BPM hard cap, original_release_year all shipped. Essentia energy correction pending clip re-download.

## Last Session (Mar 30, 2026)

Generated playlists for both users (Pranav 81% Stay Sharp, Komal 64% Fuel Up). Confirmed LLM middle-value bias still affects Bollywood energy (Chori Kiya Re = Do Dhaari Talwaar in LLM's eyes). Validated Essentia corrects this — Slow Motion Angreza measured 0.77 energy vs LLM's 0.60. Jadoo measured 0.13 vs LLM's 0.70.

Rebuilt audio clip pipeline: 60s from start (was 30s from middle — literally threw away the opening). Opening energy uses 7% of song duration (industry standard for intro length). YouTube auth (cookies + JS challenge solver) + 15s pacing + 5 parallel processes for bulk downloads.

Stored Saumya's extended Spotify history for future onboarding. Documented dual-source classification as Spotify audio features replacement.

## Blockers

- Audio clip re-download: 879/3,717 done, 5 parallel processes running. ~7 hours to completion.

## Next Steps

1. When re-download completes: validate Essentia on 5 test songs (Ishq Di Baajiyaan, Kiya Kiya, Maahi Ve, Chori Kiya Re, Slow Motion Angreza)
2. If validated: re-run Essentia + recompute for both libraries
3. Regenerate playlists and compare before/after
4. Onboard Saumya
5. Listen to playlists, collect feedback, tune weights

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
