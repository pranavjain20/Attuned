# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Attuned — a personal system that connects WHOOP recovery data to Spotify using neuroscience research on how music affects the autonomic nervous system. Reads morning WHOOP data (HRV, sleep architecture, trends), classifies physiological state into one of five categories, then generates a Spotify playlist of 15-20 songs from your own library whose acoustic properties are scientifically matched to what your body needs.

Single-user, runs locally. Not a company — a personal tool.

## Current Status

**See STATUS.md for current task state and what's next.**
- See docs/PRD.md for full product requirements.

## Key Documents

- `docs/PRD.md` — Full product document: features, data sources, intelligence layers, phasing, research citations, technical appendix

## Session Protocol

- On session start: read STATUS.md, tell Pranav what needs review and what's next
- On session end: update STATUS.md with completed work, blockers, next steps
- Track tasks in tasks/todo.md
- Log lessons learned in tasks/lessons.md

## Tech Stack

- **Language:** Python 3.11+
- **Database:** SQLite (single-user, local — zero setup, one file)
- **WHOOP:** Custom thin client (registered app, OAuth 2.0, direct API calls with httpx)
- **Spotify:** Spotipy (OAuth, library access, playlist creation)
- **Computations:** pandas + numpy (rolling averages, trend slopes, ratios)
- **Song Classification:** OpenAI GPT-4o-mini first ($5 credits), then Anthropic Claude Sonnet. Provider-agnostic wrapper.
- **Audio Analysis:** Essentia (later, when library exceeds 500 songs)
- **Trigger:** Manual CLI first, WHOOP webhook later

## Project Structure

```
attuned/
├── main.py                    # CLI entry point
├── CLAUDE.md
├── STATUS.md
├── .env / .env.example
├── requirements.txt
├── docs/
│   └── PRD.md
├── tasks/
│   ├── todo.md
│   └── lessons.md
├── db/
│   ├── schema.py              # SQLite table definitions
│   └── queries.py             # Database access functions
├── whoop/
│   ├── auth.py                # OAuth 2.0 token management
│   ├── client.py              # API client (recovery, sleep, cycles)
│   └── sync.py                # Full history sync + incremental updates
├── spotify/
│   ├── auth.py                # OAuth 2.0 via Spotipy
│   ├── client.py              # Library access (liked songs, top tracks, recently played)
│   ├── playlist.py            # Playlist creation + description generation
│   └── sync.py                # Song pool sync + deduplication
├── intelligence/
│   ├── baselines.py           # Personal rolling averages, standard deviations, CVs
│   ├── trends.py              # 7-day HRV/RHR slopes, sleep debt trajectory
│   ├── sleep_analysis.py      # Deep/REM/light ratios vs personal norms
│   └── state_classifier.py    # Composite state detection (5 states)
├── classification/
│   ├── llm_classifier.py      # LLM song classification (BPM, key, energy, valence, etc.)
│   └── profiler.py            # Neurological impact scoring per song
├── matching/
│   ├── state_mapper.py        # State → target song property ranges
│   ├── query_engine.py        # Find matching songs from classified library
│   ├── sequencer.py           # Playlist ordering (iso principle, tempo transitions)
│   └── generator.py           # End-to-end pipeline: WHOOP → state → match → playlist
└── tests/
```

## Database Tables

- **songs** — Every unique song. Key: spotify_uri. Track name, artist, album, duration, source.
- **whoop_recovery** — One row per day. Recovery score, HRV, RHR, SpO2, skin temp.
- **whoop_sleep** — One row per sleep session. Stage durations (deep/REM/light/awake), quality metrics, sleep_needed breakdown.
- **listening_history** — Every play event. spotify_uri, played_at, duration_played. Unique on (spotify_uri, played_at).
- **song_classifications** — One row per song. LLM properties (BPM, key, mode, energy, valence, acousticness, danceability, mood_tags) + neurological scores. Classification source + raw response.
- **generated_playlists** — Log of every playlist created. Date, detected state, reasoning, WHOOP metrics, track URIs, Spotify description.

## Five Composite States

1. **Accumulated Fatigue** — HRV declining 3+ days AND RHR rising AND sleep debt accumulating
2. **Single Bad Night** — Low recovery today but 7-day HRV trend stable/rising
3. **Physical Recovery Deficit** — Deep sleep significantly below norm, REM adequate
4. **Emotional Processing Deficit** — REM below norm, deep sleep adequate
5. **Peak Readiness** — Green recovery, HRV at/above 30-day average, good sleep, low debt

## Key Constraints

- **Small library:** ~113 liked songs, ~300-400 after expansion. Matching engine must progressively relax filters when too few songs match. Log when relaxation happens.
- **Spotify audio features API is deprecated** — classification is entirely LLM-based (then Essentia later)
- **Spotify playlist descriptions:** 300 character limit
- **WHOOP tokens:** Expire after 1 hour — must use offline scope for refresh tokens
- **WHOOP pagination:** 25 records per page using nextToken
- **WHOOP timestamps:** ISO 8601 with timezone offsets — careful date derivation
- **LLM classification:** Batch 30-50 songs per call, request ONLY valid JSON (no markdown). Provider-agnostic wrapper so switching OpenAI → Anthropic is a config change.
- **Each playlist is a new dated playlist** — not overwriting a standing one. Name includes date + detected state. Description includes reasoning.

## Key Concepts

- **WHOOP = body state, Spotify = song pool, Song Properties = the bridge.** WHOOP tells us what the ANS needs. Song properties tell us what each song does to the ANS. The matching engine connects the two.
- **Personal baselines over absolute numbers.** A 50% recovery with HRV at 45ms means something completely different if the 30-day average is 48ms vs 65ms. Every metric is interpreted relative to the user's personal norms.
- **Multi-day trends over single-day snapshots.** Single-day numbers are noisy. 7-day HRV slope, RHR trend, sleep debt trajectory — these reveal the real picture. The composite state classifier uses trends, not just today's data.
- **Progressive filter relaxation.** With a small library, strict matching criteria might return 3 songs. The engine widens BPM range, lowers acousticness threshold, etc. until 15-20 songs qualify. Always log what was relaxed and why.
- **The iso principle.** From music therapy: start the playlist near the listener's current state and gradually transition toward the desired state. Don't jump from 60 BPM to 140 BPM.

## Commands

- `python main.py generate` — Generate today's playlist (manual trigger)
- `pytest tests/ -x -v` — Run all tests
- `pytest tests/test_specific.py -x -v` — Run a single test file
- `pytest tests/test_specific.py::test_name -x -v` — Run a single test

## Git Strategy

- Main branch: always stable, tests passing
- Feature branches: `feat/[component]-[feature]`, `fix/[component]-[description]`, `test/[component]-[what]`
- Squash merge to main after review
- Never merge without all tests passing

## API Keys Needed

- **WHOOP:** developer.whoop.com — registered app (client_id + client_secret)
- **Spotify:** developer.spotify.com — registered app
- **OpenAI:** platform.openai.com — $5 existing credits (song classification)
- **Anthropic:** console.anthropic.com — fallback when OpenAI credits run out

## Code Quality Philosophy

The goal is code that a great engineer would enjoy reading. Not clever code, not over-abstracted code — clean code where every piece is obvious, intentional, and earns its place.

- **Readability is the measure.** If someone has to re-read a function to understand it, it's too complex — whether that's because it's too long, too nested, too clever, or poorly named. Use judgment, not line counts.
- **Each function does one thing you can name.** If you need "and" to describe it, consider splitting. But don't split just to be short — two tangled halves are worse than one clear whole.
- **Flat over nested.** Early returns, guard clauses, extract-and-name. If logic is three levels deep, there's almost always a cleaner way.
- **Names are documentation.** `get_recovery_by_date`, not `get_rec`. `is_declining_trend`, not `trend_flag`. `compute_hrv_baseline`, not `calc_base`. Consistent verbs across the codebase — if one module uses `compute_`, they all do.
- **No dead weight.** No commented-out code, no unused imports, no placeholder functions, no `Any` types without genuine need. If it's not pulling its weight, delete it.
- **Files stay cohesive.** One domain per file. When a file starts covering too many concerns, split by responsibility — not by arbitrary size.
- **Type hints on all function signatures.** Including return types. This is a typed codebase.
- **Tests read like specs.** Name describes the behavior (`test_state_classifier_detects_accumulated_fatigue_over_three_days`), one logical assertion per test, arrange-act-assert flow.
- **Minimum code that solves the problem.** No unrequested features. No abstractions for single-use code. If 200 lines could be 50, rewrite it.
- **Surgical changes.** Touch only what you must. Don't improve adjacent code, comments, formatting. Match existing style, even if you'd do it differently. Note unrelated issues — don't fix them without asking.

## Build Discipline

IMPORTANT: The data pipeline is the foundation. If WHOOP data is parsed wrong, baselines are off, or song classifications are inaccurate, the playlists will be meaningless. No hacks. No shortcuts. No "good enough for now." Every layer must be correct before building on top of it.

YOU MUST do the end-of-day audit automatically. Pranav should never have to ask "did you check everything?" — that check is your job, every time.

### Write a Little, Test a Little

- Build incrementally: implement one small piece, write its tests, verify it passes, then move on.
- Never batch up a ton of untested code. If you wrote more than ~30 lines without running tests, stop and test what you have.
- Every new function gets at least one happy-path test and one edge-case test before moving to the next function.

### End-of-Day Audit (MANDATORY — do this automatically, not when asked)

After finishing each day's work, before saying "done":
1. **Re-read every file you touched.** Look for:
   - Hacks, workarounds, or "temporary" solutions that should be done properly
   - Copy-pasted code that should be extracted
   - Missing error handling or edge cases
   - Inconsistencies with existing patterns
   - Data integrity gaps (API responses not validated, computation inputs not checked)
   - Silent failures that should be explicit errors or logged warnings
2. **If you find a hack, fix it now.** Don't defer. Don't leave TODOs. Do it the right way or don't do it at all. Keep iterating until it's right.
3. **Run the full test suite**, not just the new tests. Confirm nothing regressed.
4. **Audit test coverage ruthlessly.** For every function, ask:
   - Happy path tested?
   - Every error/validation path tested? (missing data, bad input, API failures, malformed responses)
   - Edge cases tested? (empty lists, 0 values, None, exactly-at-threshold, 1 day of data vs 30 days)
   - Computation boundary conditions tested? (first day with no baseline, partial week of data, all metrics missing)
   - Data pipeline integrity tested? (WHOOP → DB → baselines → state classifier chain)
5. **Report findings honestly** — list what you found and fixed, not just "all good."

### Be Your Own Harshest Reviewer

After writing code, switch to reviewer mindset. Ask: "If a staff engineer reviewed this, what would they flag?"
- Can bad input cause an unhandled exception instead of a clean error or logged warning?
- Are API responses validated before use? (WHOOP could return unexpected fields, LLM could return malformed JSON)
- Are computations correct at boundary conditions? (0 days of data, 1 day, exactly 7 days, exactly 30 days)
- Is the data pipeline end-to-end sound? (Does garbage in at one layer propagate silently, or get caught?)
- Are there magic numbers that should be named constants?
- Is there duplicated logic across modules that should be extracted?
- If you wouldn't ship it to production, don't call it done.

### No Hacking Through Blockers

- If something doesn't work, find the root cause. Don't add workarounds.
- If a test fails, understand WHY before fixing it. Don't just tweak until it passes.
- If you're stuck, stop and re-plan rather than forcing a brittle solution.
- Ask Pranav if genuinely unsure — a 30-second question beats an hour of wrong-direction work.

### Verification

- Run `pytest tests/ -x -v` after every change
- If no tests exist yet: write at least 2 tests first, then make them pass
- Never say "done" without running the full suite and seeing all green

### Definition of Done

- All tests pass
- Changes committed (nothing hanging)
- STATUS.md updated
- tasks/todo.md updated
- tasks/lessons.md updated if new patterns discovered
- `git status` clean
