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

## Day 4 Pre-Work (BPM Experiments)

- **Smaller LLMs beat larger ones for BPM recall:** GPT-4o-mini (8/25) > GPT-4o (6/25) > Claude Sonnet (7/25) > Claude Opus (5/25) > GPT-4.1 (2/25). Smaller models recall memorized database values directly. Larger models try to "reason" about tempo from genre/mood and overshoot. For factual recall tasks, don't assume bigger = better.
- **"Database recall" prompting > "estimate" prompting:** Framing BPM as "recall the precise BPM from music databases" (9/25, MAE 13.1) outperformed "estimate the BPM" (8/25, MAE 18.8). The framing changes whether the model retrieves memorized values or tries to reason from first principles. For any task where the model likely has the answer memorized, frame as retrieval, not estimation.
- **Essentia classical BPM fails on Indian music:** 4/5 English songs correct, 3/13 Bollywood songs correct. Not octave errors (2x/0.5x) — fundamental misdetections. Tabla patterns, vocal ornaments, and non-Western rhythmic structures confuse the autocorrelation-based beat tracker. This is a training data bias, not a fixable parameter.
- **TempoCNN = same accuracy as classical Essentia:** Despite being a neural model (115MB, requires essentia-tensorflow), TempoCNN matched classical Essentia's accuracy exactly (8/24). Same Western training data bias. Neural doesn't help when the training distribution doesn't cover your music.
- **No free BPM database covers Bollywood accurately:** Soundcharts has data but audio features are premium ($250+/month). GetSongBPM is Cloudflare-blocked for programmatic access. SongBPM.com has 48% coverage and 0% Bollywood accuracy. HuggingFace's Spotify dataset uses Spotify's old audio features — which ARE Essentia under the hood. Dead end.
- **±10 BPM tolerance is safe for playlist matching:** State mapper BPM ranges are 20-60 BPM wide (e.g., "calming" = 60-80, "energizing" = 100-140). A ±10 BPM error never causes a song to land in the wrong bucket. This isn't overfitting to current data — it's engineering judgment about the matching engine's window width.

## Day 4 Pre-Work (Property Evaluation)

- **Essentia key detection: dominant confusion is the main failure mode.** 3/6 "wrong" key detections were dominant confusion (detecting the 5th instead of root). This is a known HPCP limitation, especially in Indian music where the tanpura emphasizes the 5th. But for sequencing, dominant keys ARE musically compatible — so 92% of detections are usable even if only 58% are exact.
- **RMS normalization matters more than the algorithm.** RMS/0.25 clips 46% of songs at 1.0. RMS/0.35 clips 0%. Every complex alternative (Loudness, P90, composites) scored worse than the simple divisor fix. The lesson: check your normalization constants against real data before reaching for a fancier algorithm.
- **Essentia's danceability (DFA) measures the wrong thing entirely.** It measures rhythmic regularity (how predictable the beat pattern is), not danceability. A metronomic slow ballad scores higher than a syncopated dance track. 42% bucket accuracy — worse than random. No amount of normalization or threshold tuning fixes a wrong measurement.
- **Spectral flatness is a better acousticness proxy than spectral centroid.** SCT measures brightness; bright acoustic guitar scores "electronic" while bass-heavy EDM scores "acoustic." Flatness measures tonal vs noise-like spectrum, which correlates better with organic vs synthetic instrumentation (67% vs 33%).
- **ZCR does not detect vocals.** Zero-crossing rate measures high-frequency spectral content. It has no relationship to whether a song has vocals. 46% of vocal-only songs scored >0.5 instrumentalness. Vocal detection requires ML models (or LLM knowledge).
- **"Perceptual" properties can't be derived from acoustic measurements alone.** Energy, danceability, valence — these are human judgments about how music *feels*, not objective audio properties. Essentia correctly measures acoustic features (RMS, DFA, spectral centroid). The problem is mapping those measurements to human-perceived qualities. Each acoustic feature has confounds (mastering era for loudness, rhythmic regularity vs groove for danceability) that can't be resolved without semantic understanding.
- **Simple approaches beat complex ones when the signal is weak.** Every composite (weighted combinations of multiple features) performed worse than the single best feature with proper normalization. When the underlying signal is noisy (~70% accurate), combining it with other noisy signals amplifies noise rather than canceling it. Save composites for when individual components are >85% accurate.
- **Tunebat/SongBPM ground truth IS Essentia.** These databases source their key/mode data from Spotify's deprecated audio features API, which ran Essentia on official masters. "Ground truth" comparisons are Essentia-on-YouTube vs Essentia-on-Spotify, not Essentia vs human annotation. High match rates confirm audio quality, not algorithm correctness.
