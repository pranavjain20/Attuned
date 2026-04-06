# Attuned — Current Status

## Current Phase

Day 19. 1,090 tests passing. 3 active users. LLM-direct song selection: Claude Sonnet picks songs from the full library by meaning, not neuro-profile math. WhatsApp bot live on Twilio. Conversational DJ with clarifying questions.

## Last Session (Apr 3, 2026)

Fixed Python import system wedged by `pkill -9` (pyc cache corruption from last session). Generated live playlists for all 3 users: Pranav (Settle In, poor sleep), Komal (Fuel Up, baseline), Saumya (Rest & Repair, poor recovery).

Built song availability tracking: `is_available` + `availability_checked_at` on songs table. Generator persists Spotify checks to DB, matching engine excludes unavailable songs. 7-day cache, 5-song buffer. All users get full 20-track playlists.

Built NL mood/genre/era filter pipeline with mood cluster expansion. Iterated through 4 rounds of tuning: "empowering" too broad → "inspirational" too broad → tightened to ["motivational", "triumphant"]. Added title-only dedup, anchor mood filtering, per-filter graceful fallback.

Conversational DJ with clarifying questions. WhatsApp bot live on Twilio (async generation). LLM-direct song selection replaced neuro-profile-cosine pipeline for NL requests — Claude Sonnet sees full 1,188-song library interleaved by artist and picks 20 by semantic understanding. "Dark seductive Weeknd" → Earned It, What You Need, Nothing Compares (not In Dino, Roke Na Ruke Naina). WHOOP daily playlists still use neuro profiles — that path is unchanged.

Iterated through: GPT-4o-mini (too dumb for 1,188 songs) → engagement-sorted library (artist concentration) → shuffled (lost taste signal) → artist-interleaved (right balance). Version dedup in code (Channa Mereya x3 → x1).

## Blockers

- 330 of Saumya's songs can't be downloaded (missing duration_ms or yt-dlp timeouts). Near ceiling.
- Spotify dev mode: 5-user cap per app. Friends register own dev app. Documented in Attuned-Auth repo.

## Next Steps

1. Onboard Saumya on WhatsApp (same process as Komal)
2. More NL prompt testing — have Komal + Saumya try prompts, see what breaks
3. Automated daily generation (cron)
4. Per-user Spotify dev app credentials in code
5. Deploy to cloud for true 24/7 ($5/month VPS) — currently runs on Mac with launchd

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
- **Day 19** — Song availability tracking, NL filters + mood clusters, conversational DJ, WhatsApp bot (Twilio), LLM-direct song selection (Claude Sonnet replaces neuro-profile math for NL)
