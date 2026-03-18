# Attuned — Lessons Learned

_Patterns, mistakes, and rules discovered during development. Updated as we go._

## Day 1

- **Extended history record filtering:** 116 of 33,427 records had null track_name or artist_name (podcasts, audiobooks, corrupted entries). Filter these out — they can't be songs.
- **Duplicate timestamp+URI pairs:** 582 records in the extended history share the same (uri, played_at) — likely Spotify export duplicates across file boundaries. INSERT OR IGNORE handles this cleanly.
- **SQL injection in utility functions:** Even internal-only functions like `count_rows(table)` should validate table names against an allowlist. f-string SQL is never safe, even with constants — use parameterized queries.
- **Install dependencies before running tests:** The venv may not have project deps. `pip install -r requirements.txt` first.
- **Commit by logical concern, not by session:** Don't dump a full day's work into one commit. Group by concern — data layer, API client, CLI wiring, etc. Each commit should be understandable from its message alone.

## Day 2

- **`.replace(tzinfo=...)` vs `.astimezone(...)`:** When parsing ISO 8601 timestamps with timezone offsets, `.replace(tzinfo=utc)` silently corrupts the time by overwriting the label without converting. Always use `.astimezone(timezone.utc)` to properly convert.
- **Guard `duration_ms = 0` separately from NULL:** `is not None` is true for 0. When branching on "has meaningful duration", check `is not None and > 0`.
- **Clamp intermediate components, not just final scores:** Even when the final score is clamped to [0,1], unclamped intermediate values (like recency > 1.0 from future dates) distort the component's relative weight. Clamp each component individually.
- **Staff tester + staff auditor architecture:** After implementation, always spawn (1) a staff quality tester that creates a testing plan and fills coverage gaps, then (2) a staff engineer auditor that reviews every line for correctness, edge cases, and code quality. Fix all findings before marking done.
- **Spotify re-releases tracks with new URIs:** Same song, same artist, different URI. Must deduplicate by (LOWER(TRIM(name)), LOWER(TRIM(artist))) before computing any aggregate stats. Found 435 groups in a 5,782-song library.
- **Alexa/remote/playbtn are intentional plays:** Only `trackdone` and `fwdbtn` are passive. Using just `clickrow` penalizes multi-device users heavily — 2,300+ Echo Dot plays were being marked as non-intentional.
- **Recency signal needs to be ratio, not last-played date:** A single stray play inflates a date-based recency signal. `plays_last_year / total_plays` is a much stronger signal of current engagement.
- **3 plays is not enough for confident scoring:** Paan Ki Dukaan ranked #20 with only 3 perfect plays. Bumped to 5 minimum — cuts pool from 963 to 669 but every scored song has meaningful data.
- **`not_applicable` platform = unidentified device:** Likely a second Alexa or smart speaker. 2,115 plays from this source — significant portion of listening.

## Day 3

- **Multiple sleep records per date (naps):** WHOOP stores naps and primary sleep as separate records with the same date. `get_sleeps_in_range` returns ALL of them. Any computation that aggregates per-day (sleep debt, stage baselines) must group by date first — otherwise it double-counts "needed" sleep or inflates the baseline count. Found this on real data: 10 dates had 2 records each.
- **Test data overlap with upsert dedup logic:** WHOOP recovery upsert keeps the higher recovery_score when two records share a date. Tests that seed baseline data (high recovery) then insert trend data (low recovery) for overlapping dates will silently keep the baseline values. Use `skip_last_n` or non-overlapping date ranges.
- **Baseline window excludes today, trend window includes it:** Baselines use `[date-N, date-1]` (evaluating today AGAINST the baseline). Trends use `[date-N+1, date]` (slope OF recent days including today). This is intentional and important — don't mix them up.
- **Don't second-guess WHOOP's recovery score:** The original classifier decomposed recovery into independent signals (HRV trend, RHR trend, sleep debt, weighted scoring) and tried to recombine them. But those metrics are correlated (sleep → RHR → HRV → recovery), and WHOOP has 2.5 years of data proving red recovery is never wrong. Trust recovery as the primary signal; use individual metrics to determine HOW to help, not WHETHER it's bad.
- **`mean - SD` vs `mean` for "low" thresholds:** A threshold of `mean - 1*SD` means "abnormally low" — only ~16% of days qualify. For peak readiness debt check, this was too restrictive (required statistically unusual low debt). Changed to `mean` (at or below average). Always think about what the threshold means in practice with real numbers.
- **State names should capture the emotional reality:** `single_bad_night` minimized the experience. Users don't think "oh, just one bad night" — they think "I'm wrecked, get me functional." Renamed to `poor_recovery`. State names affect how the system feels to use.
- **Classification picks strategy, raw metrics pick intensity:** A 19% and 55% day can share the same state (same playlist strategy) but the matching engine uses the raw recovery score to calibrate how aggressive the music is. Don't overload the classifier with intensity logic.
