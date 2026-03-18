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
