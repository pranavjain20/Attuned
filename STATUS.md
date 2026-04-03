# Attuned — Current Status

## Current Phase

Day 19. 1,090 tests passing. 3 active users. WhatsApp bot built — conversational DJ over Twilio webhook. Users text a message, DJ clarifies if needed, generates playlist, replies with Spotify link.

## Last Session (Apr 3, 2026)

Fixed Python import system wedged by `pkill -9` (pyc cache corruption from last session). Generated live playlists for all 3 users: Pranav (Settle In, poor sleep), Komal (Fuel Up, baseline), Saumya (Rest & Repair, poor recovery).

Built song availability tracking: `is_available` + `availability_checked_at` on songs table. Generator persists Spotify checks to DB, matching engine excludes unavailable songs. 7-day cache, 5-song buffer. All users get full 20-track playlists.

Built NL mood/genre/era filter pipeline with mood cluster expansion. Iterated through 4 rounds of tuning: "empowering" too broad → "inspirational" too broad → tightened to ["motivational", "triumphant"]. Added title-only dedup, anchor mood filtering, per-filter graceful fallback.

Conversational DJ: ambiguous requests ("I'm feeling sad") get a clarifying question before generating. Clear requests ("gym motivational") generate immediately with a warm DJ message. Same starting prompt + different answer = completely different playlist (heartbreak vs uplifting). LLM decides when to clarify vs generate.

WhatsApp bot: Flask webhook server receives Twilio messages, routes through the same NL pipeline. Phone-to-profile mapping via env vars. In-memory conversation state with 10-min TTL for clarifications. Async generation (DJ message immediate, playlist link follows ~60s later). Tested live on WhatsApp — full flow working: clarify → DJ message → Spotify playlist link with rich preview.

## Blockers

- 330 of Saumya's songs can't be downloaded (missing duration_ms or yt-dlp timeouts). Near ceiling.
- Spotify dev mode: 5-user cap per app. Friends register own dev app. Documented in Attuned-Auth repo.

## Next Steps

1. Onboard Komal + Saumya on WhatsApp (add phone numbers to .env, have them join sandbox)
2. More NL prompt testing (romantic, chill, study, etc.) + tune clusters
3. Recompute Saumya's scores after Essentia finishes
4. Automated daily generation (cron)
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
- **Day 19** — Song availability tracking, NL filters + mood clusters + title dedup, conversational DJ, WhatsApp bot (Twilio webhook)
