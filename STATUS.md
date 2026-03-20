# Attuned — Current Status

**Last updated:** Mar 19, 2026
**Current phase:** Era cohesion implemented. Playlist generation working (dry-run tested). 774 tests passing.
**Next action:** Finish release_year backfill (rate-limited ~24h), then reclassify songs with improved prompt, then Day 6.

### Background: Essentia analysis running
Audio clips downloaded for 1,069/1,360 songs. Essentia analysis in progress (~100/1,069 done, ~2-3 hours remaining). Once done, run `recompute-scores` to update neuro scores with measured energy/acousticness (71%/62% accuracy vs LLM's 42%/50%). 197 additional songs got duration_ms recovered from listening history.

### Blocked: Spotify rate limit
Backfill of release_year hit Spotify's rate limit after 548/1,623 songs. Fixed batch endpoint (50x fewer calls). Once limit clears (~24h from Mar 19 evening), run:
```
python main.py backfill-release-years     # ~22 API calls with batch fix
python main.py classify-songs --provider openai --reclassify  # With release year in prompt
python main.py recompute-scores           # Recompute neuro scores (~2 sec)
python main.py generate                   # Push real playlist to Spotify
```

---

## What's Done (Era Cohesion + Playlist Generation)

### Era Cohesion
- Genre-aware Gaussian decay on release year: hip-hop σ=2 (tight), ghazal σ=12 (loose), Bollywood σ=6
- Uses larger sigma of two songs (more permissive wins). None year → 0.5 neutral.
- `release_year` column added to songs table with migration
- Spotify client extracts release_year from album.release_date
- `backfill-release-years` CLI command
- Batch endpoint fix: `sp.tracks()` (50/call) instead of `sp.track()` (1/call)
- 491/1,360 classified songs have release_year data

### Cohesion Weight Tuning
- Era weight 0.10 → 0.20 (genre 0.25→0.20, mood 0.20→0.15)
- At 0.10: max era swing was 0.06 — couldn't exclude cross-era songs
- At 0.20: max era swing is 0.12 — correctly filters 1999 songs from 2010s clusters
- Tested: Chunnari Chunnari (1999) excluded from 2009–2018 Bollywood cluster

### LLM Prompt Improvement
- Release year added to classification prompt: `"Jee Le Zaraa" by Vishal Dadlani (album: Talaash) (2012)`
- Helps disambiguate songs with common Hindi phrases as titles
- Both `get_songs_needing_llm` queries updated to include release_year

### Playlist Generation (dry-run tested)
- State: Baseline (Recovery 59%, HRV 43ms)
- 20 tracks selected, mean cohesion 0.612, dominant genre: Bollywood
- Era range with full-data pool: 2009–2018 (tight 2010s cluster)

### Known Issues
- Jee Le Zaraa (Talaash) misclassified as upbeat (energy 0.7, valence 0.8) — actually slow/dark. Release year in prompt should fix on reclassification.
- 64% of classified songs still missing release_year (rate-limited)

### 774 tests passing.

---

## What's Done (Day 5b: Matching Engine Rewrite)

Neuro-score dot product, seed-and-expand cohesion, unified ranking. 0/140 weak matches, ~74% optimal, ~45% daily turnover. Para↔Grnd r: 0.921→0.776.

## What's Done (Day 4b: Accuracy Tuning)

48%→68% accuracy. Confidence-aware ensemble. Product accuracy 83%. See `tasks/accuracy_tuning_learnings.md`.

## What's Done (Day 4: LLM Classification)

1360 songs classified. Profiler + LLM + Essentia hybrid. 0 failures.

## What's Done (Day 3: WHOOP Intelligence)

Baselines, trends, sleep analysis, 8-state classifier. 823 days validated.

## What's Done (Day 2: Engagement Scoring)

5-signal scoring, dedup, 669 songs scored.

## What's Done (Day 1: Data Foundation)

Extended history ingestion, WHOOP/Spotify APIs, schema, 33K records.

---

## What's Next

1. **Immediate (after rate limit clears):** Finish backfill, reclassify with release year, generate real playlist
2. **Day 6:** Playlist sequencing (iso principle) + end-to-end flow
3. **Day 7:** Polish + hardening
4. **Future:** Essentia on more songs, playlist taste import, onboarding

## API Keys Status

- WHOOP: registered, OAuth working, full history synced
- Spotify: registered, OAuth working, library synced — **rate-limited until ~Mar 20 evening**
- OpenAI: ~$2 credits remaining
