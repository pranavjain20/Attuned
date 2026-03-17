# Attuned — Lessons Learned

_Patterns, mistakes, and rules discovered during development. Updated as we go._

## Day 1

- **Extended history record filtering:** 116 of 33,427 records had null track_name or artist_name (podcasts, audiobooks, corrupted entries). Filter these out — they can't be songs.
- **Duplicate timestamp+URI pairs:** 582 records in the extended history share the same (uri, played_at) — likely Spotify export duplicates across file boundaries. INSERT OR IGNORE handles this cleanly.
- **SQL injection in utility functions:** Even internal-only functions like `count_rows(table)` should validate table names against an allowlist. f-string SQL is never safe, even with constants — use parameterized queries.
- **Install dependencies before running tests:** The venv may not have project deps. `pip install -r requirements.txt` first.
