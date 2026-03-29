# Attuned — Current Status

## Current Phase

Day 14. 1,048 tests passing. Fixed playlist cohesion for diverse libraries (IDF genre similarity, BPM hard cap, original_release_year from LLM). Both libraries reclassified. Clip re-download running overnight for Essentia opening energy + LLM error correction.

## Last Session (Mar 29, 2026)

Komal's feedback surfaced 4 cohesion issues: genre soup (reggaeton next to Bollywood), house track in pop playlist, 1973 song in modern cluster, calm openings next to upbeat openings. Root cause: "pop" in 60% of library made Jaccard similarity meaningless.

Fixed with IDF-weighted genre similarity (rare tags matter more), BPM hard cap, original_release_year from LLM (Jawani Jan-E-Man correctly identified as 1973). Cohesion improved 0.264 → 0.431.

Also discovered LLM systematic middle-value bias on Bollywood energy (Ishq Di Baajiyaan, Kiya Kiya, Maahi Ve all classified ~0.60 despite being completely different). Essentia cross-validation is the fix — clip re-download running to replace 2,893 Spotify previews with full YouTube downloads.

## Blockers

- Clip re-download running (~24 hrs). After: re-run Essentia, validate on 5 test songs, recompute.

## Next Steps

1. When re-download completes: validate Essentia on 5 problem songs (Ishq Di Baajiyaan, Kiya Kiya, Maahi Ve, Chori Kiya Re, Slow Motion Angreza)
2. If validated: re-run Essentia + recompute for both libraries
3. Listen to playlists, collect feedback, tune weights
4. Automated daily generation (cron)

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
- **Day 14** — Cohesion fix: IDF genre similarity, BPM hard cap, original_release_year, opening energy. Clip re-download for Essentia correction of LLM middle-value bias.
