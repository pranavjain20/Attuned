# Attuned — Current Status

## Current Phase

Day 16. 1,048 tests passing. Audio pipeline complete: 3,421 clips re-downloaded as 60s-from-start, Essentia re-analyzed with opening energy for both libraries. Essentia corrects extreme energy misclassifications but hits 60% ceiling for Bollywood mid-range. Next: ML model on user-labeled data.

## Last Session (Mar 31, 2026)

Validated Essentia on test songs: Slow Motion Angreza correctly 0.77 (was 0.60), Jadoo correctly 0.13 (was 0.70). But Maahi Ve only 0.50 (should be 0.30) — OnsetRate can't distinguish gentle tabla from intense dhol. Generated playlists for both users with corrected energy. Playlist quality improved (energy range 0.14-0.73 vs yesterday's 0.60-0.70 compression).

## Blockers

- None. System is operational.

## Next Steps

1. **Bollywood energy ML model** — label 50-100 songs, train logistic regression on Essentia features. Expected: 70-75% accuracy (vs 60% ceiling with heuristics).
2. Onboard Saumya (history stored, awaiting OAuth)
3. Automated daily generation (cron)
4. Weight tuning from daily feedback

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
