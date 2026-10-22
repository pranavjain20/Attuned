# How Attuned Works

A technical walk-through of the code as it is now, from a WHOOP sync to the page. For why things are the way they are, see [DECISIONS.md](DECISIONS.md). For the research, see [RESEARCH.md](RESEARCH.md). Every weight, threshold and range below is my design choice unless a source is named.

## The flow at a glance

```
WHOOP sync ──> last night + this morning, dated in local time
            ──> z-scores against my own usual            (intelligence/signals.py)
            ──> Attuned score 0–100 + explanation        (intelligence/feeling_score.py)
            ──> position among earlier days ──> playlist target (calm / steady / energy)
                                                  │
Spotify library ──> classified songs ─────────────┴──> matched, rotated, cohesive playlist
                    (tempo, energy, mood, genre)        (matching/)
                                                  │
                         Spotify push · day page (web/site.py) · WhatsApp DJ (intelligence/dj_context.py)
```

## 1. Getting the data right

**WHOOP sync** (`whoop/`). Each morning `sync-whoop` pulls the recovery and sleep records for today; `sync-whoop-history` pulls everything.

- **Local dates.** WHOOP sends times in UTC plus the wearer's time-zone offset in a separate field. `local_date(timestamp, offset)` in `whoop/client.py` is the only place a timestamp becomes a date. A sleep is dated by its local end time, and a recovery takes the date of the sleep it scores. The daily sync asks for a three-day UTC window and keeps records whose local date matches today, because one local day spans parts of three UTC days.
- **Naps are never "last night".** WHOOP's nap flag is stored. `intelligence/main_sleep.py` defines last night as the longest non-nap sleep on that date, never a sum. Sleep debt is the one place naps count, because a nap really is sleep you got.
- **Short nights.** `is_short_night` marks a main sleep under 6 hours asleep (deep + REM + light). Exactly 6 hours is not short. If stage data is missing, the length is unknown and the night is not called short.

**Spotify sync** (`spotify/`). The library is built from extended streaming history plus liked songs, top tracks and recently played. Only songs with real listening history are classified and eligible.

## 2. Comparing each signal with my usual

`compute_z_scores` (`intelligence/signals.py`) turns today into z-scores. A z-score is how far today sits from my usual (the previous 30 days, not including today), measured in my typical day-to-day wobble (one standard deviation). Every z-score is signed so positive means better, and clamped to ±2.5 so one extreme night can't dominate. A personal usual needs at least 14 days of data.

The signals the score uses (`FEELING_WEIGHTS` in `intelligence/feeling_score.py`):

- **Sleep group:**
  - sleep efficiency (share of time in bed actually asleep);
  - deep sleep hours;
  - REM hours;
  - total sleep;
  - sleep debt over the last 7 nights including last night;
  - deep-sleep share of the night.
- **Heart group:**
  - HRV, using the natural log of WHOOP's RMSSD, a common way to make HRV comparable from day to day;
  - resting heart rate (higher is worse, so its sign is flipped);
  - the 7-day HRV trend (slope of a fitted line);
  - HRV change since yesterday;
  - resting heart rate change since yesterday.

Caps on what can count as good news:

- **Short nights.** After a night under 6 hours, sleep efficiency and deep-sleep share are capped at 0. A short night is naturally unbroken and front-loaded with deep sleep, so a high reading there isn't a good sign.
- **Sleep debt.** More than 7 hours of debt over 7 nights is capped at 0, even if it's less debt than my usual.

WHOOP's recovery score is not a signal. It's built from HRV, resting heart rate and sleep, so including it would count those twice.

## 3. The Attuned score

`compute_feeling_score` in `intelligence/feeling_score.py`.

**Composite.** A weighted average of the z-scores present that day. The sleep group's weights add up to about twice the heart group's (1.55 to 0.78). If the signals present carry less than 70% of the total weight (for example, no night's sleep recorded), there's no score, and the page says why in plain words.

**Mapping to 0–100 (percentile matching).**

1. Rank today's composite among the composites of every earlier day. That rank is the day's **position**, from 0 (below every earlier day) to 1 (above every one).
2. The score is my WHOOP recovery at that same rank among those days' WHOOP recoveries.

This means:

- **Same share of colours.** Over my history, Attuned has the same share of red (0–33), yellow (34–66) and green (67–100) days as WHOOP. The rings disagree only about which days are which.
- **Stable past scores.** Only earlier days are used, so a day's score never changes as new data arrives.
- **A minimum history.** It needs at least 60 earlier scored days.
- **A known limit.** It assumes WHOOP has the right proportion of bad days.

**Explanation.** `pick_drivers` chooses up to three signals that explain the day:

- **Which side to explain.** If Attuned and WHOOP land in different colours, it explains the gap. Otherwise it explains how the day compares with a typical one.
- **Order.** Signals pushing that way come first, biggest effect first. One strong signal pushing the other way can take the last slot, introduced with "On the other side".
- **Noise filter.** Anything within half a wobble of usual is never named.

Each driver becomes one fixed sentence with real numbers ("You got 1.2 h of REM sleep, less than your usual 1.7 h."). The headline compares with WHOOP when the colours differ ("WHOOP says ready, but your sleep says go easy"). After a short night, it never credits sleep for a better-than-WHOOP day.

## 4. From score to playlist target

`compute_continuous_profile` in `intelligence/continuous_profile.py`; the target itself, the state and `STATE_PURPOSE` are in `intelligence/playlist_target.py`.

**Three numbers.** A playlist target is three numbers that add up to 1: how calming (para, short for parasympathetic, the body's "rest and digest" side), how energising (symp, sympathetic, "fight or flight") and how grounding (grnd, emotionally steady) the music should be.

**Three fixed points.** The day's position picks a point on a line between three fixed targets in `config.py`:

- **Position 0, calm:** para 0.65, symp 0.05, grnd 0.30. Built to help you settle.
- **Position 0.5, steady:** 0.25 / 0.25 / 0.50. Built to keep you level.
- **Position 1, energy:** 0.05 / 0.65 / 0.30. Built to give you a lift.

**Straight-line blending.** Between those points the target blends in a straight line. A lower score always gives a calmer target, with no thresholds or jumps. A day with no score gets the steady target.

**State and name.** The day's **state** is the target's largest number: Rest below position ~0.29, Energy above ~0.71, Grounding in between. Playlist names follow the state and how far the day is from usual:

- **Rest:** "Rest & Repair" for my lowest 15% of days, otherwise "Settle In".
- **Energy:** "Stay Sharp" for my top 15%, otherwise "Fuel Up".
- **Grounding:** "Ease Into It" at or above the middle, otherwise "Ground Yourself".

`STATE_PURPOSE` holds the one wording ("help you settle", "keep you level", "give you a lift") used by the playlist description, the explanation, the page and the DJ.

**Emotional tone.** The target also sets a desired emotional tone (valence). Calm doesn't mean sad: a rest day aims for warm, not melancholy.

## 5. Understanding the songs

**Classification** (`classification/llm_classifier.py`, `classification/essentia_analyzer.py`). Each song gets two independent readings:

- **A language model** (GPT-4o-mini) gives tempo, energy, valence, danceability, instrumentalness, mood tags and genre tags from the song's name, artist and context. It knows songs culturally, for example that a song is a Sufi devotional, but compresses energy toward the middle for music it doesn't know well.
- **Audio analysis** (Essentia, an open-source audio library) runs on a 60-second clip from the start of the song. It measures key, mode, energy and acousticness, and gives three independent tempo readings.

Where the sources disagree, the one that's more reliable for that property wins: audio for energy and acousticness, the model for mood, genre and valence.

**Tempo** (`classification/tempo.py`). This is the only code that writes a song's tempo. The two kinds of source fail in opposite ways:

- **Beat trackers** get the exact number right when they agree, but often report double the felt tempo. They count the notes between beats, so a ballad you'd clap at 76 is read as 152.
- **The model** gives imprecise round numbers but almost never doubles.

So the rule is:

1. The number comes from where the three trackers (two Essentia beat trackers and TempoCNN, a neural tempo model) agree, allowing for doubling. With no clip, it comes from Soundcharts (a music data service).
2. Half, same or double is chosen as whichever is nearest the model's guess, within 55–165 beats per minute.
3. Hip-hop, rap and trap keep their listed fast tempo.
4. Energetic songs are never halved, because that's where the rule is least reliable. They keep their earlier tempo, marked low confidence. One exception: when that kept tempo is itself half the level the trackers or Soundcharts report (Blinding Lights kept at 88, reported at 172), the reported level is used instead, up to 185 beats per minute, at medium confidence (low when only one reading backs it).
5. A tempo set by hand (`set-tempo`) is never overwritten.

Raw readings live in their own columns, and each decision stores its source and confidence. To refresh a library: `analyze-audio --tempo-only`, `fetch-soundcharts-tempos`, `update-tempos`, then `recompute-scores`.

**Song scores** (`classification/profiler.py`). Each song gets three scores matching the playlist target: calming, energising and grounding.

- **Inputs.** They're smooth curves over tempo (the largest weight), energy, acousticness, instrumentalness, valence, mode and danceability, plus 15% from mood tags.
- **Shapes.** Calming rises as tempo and energy fall. Energising is roughly the mirror. Grounding peaks at moderate tempo and energy, and favours vocals and warmth.
- **Blending.** The model also gives its own three scores. The two are blended, leaning on whichever is more reliable in that situation.

## 6. Picking the playlist

`select_songs` in `matching/query_engine.py`.

1. **Exclude songs:**
   - songs already known to be unavailable on Spotify (an earlier availability check marked them in the database);
   - songs played in a recent playlist, with a minimum gap that grows with library size;
   - scene-tied motivational Bollywood songs (film training anthems), except on an energy day in my top 15%. Those songs evoke the film scene rather than a mood.
2. **Score every remaining song.** The core is how closely the song's three scores point in the same direction as the target (cosine similarity), blended with how well its valence fits. That is multiplied down for songs with less reliable classifications, with a small nudge against songs from the last few days.
3. **Shortlist.** Take the top 60, keeping up to 5 recently played songs as familiar anchors.
4. **Make it sound coherent** (`matching/cohesion.py`). Start from the song that's both a strong match and similar to the rest. Then add, one at a time, the candidate most similar to what's already chosen. Similarity covers genre, mood, tempo, production era, energy, acousticness and danceability. Hard caps stop clashes such as a 1999 song in a 2010s cluster, or a party track next to a quiet acoustic one. Era matters more for some genres (hip-hop dates fast; ghazal barely dates). If fewer than 15 songs pass, the similarity bar is lowered in small steps.
5. **Finish.** Put a few favourites at the front and drop near-duplicate versions of the same song. The result is 25 songs: the 20-song playlist plus 5 spares.
6. **Check availability before anything reaches Spotify.** Both `generate` and `publish-playlists` ask Spotify about each song, one call every 3 seconds, skipping songs confirmed playable in the last 7 days. A song Spotify no longer plays is dropped and marked in the database, the next spare moves up, and the list is cut to 20. An exhausted daily quota stops the run instead of waving every song through. The page's replay makes no Spotify calls, so it only leaves out songs already marked unavailable.

**Why-lines** (`matching/why_lines.py`). One rules-based line per song, under 80 characters:

- **The song first.** It describes the song in plain words, then what it does in the mix.
- **At most one personal fact.** "A long-time favourite", "Played this week", only when true.
- **Never internal labels or health claims.** No state names, no claims about effects on the body, no raw tempo numbers.
- **Only trustworthy history.** Facts that depend on knowing every play ("Not played in a while") are skipped when the listening history has a gap of more than 14 days.

## 7. Where it shows up

**Daily push** (`main.py generate`, run by `scripts/daily.sh` each morning). It syncs WHOOP, scores the day, selects the songs, checks they're playable on Spotify, and creates a dated playlist with a description. Each run is logged to the database.

**Replay without side effects** (`matching/day_playlist.py`, `main.py playlist-json`). It runs the same selection for any past day, with the library rewound to that morning: only plays before midnight UTC count (plays are stored in UTC, so a few plays near local midnight can land on the wrong day), and play counts are recomputed. Nothing is written. Each day keeps its 20 songs plus the 5 spares. Over a date range, each day's 20 songs count toward the next day's rotation, as if they had been pushed.

**Publishing the latest days** (`web/publish.py`, `main.py publish-playlists`). It turns the page's 3 most recent days into real public Spotify playlists (more only with `--allow-more`), and replays the same window as the page so the songs match. Before any write it runs the availability check above, so a spare stands in for each song Spotify no longer plays. `web/published.json` records each day's playlist URL, tracks, name and description. Running it again never makes a second playlist for a recorded day. It replaces the tracks, or renames the playlist, only when they changed, and makes a new playlist if the recorded one is gone from Spotify (404). Every Spotify write is followed by a 2-second pause, and the file is saved after each one. `--dry-run` prints the plan without logging in.

**The page** (`web/site.py`, `main.py build-site`). It writes `web/dist/index.html`, one static page that steps through recent days.

- **Copy is worked out in Python.** All the wording is produced by tested Python functions. The page's JavaScript only renders and handles clicks.
- **What each day shows:**
  - the Attuned ring, then WHOOP's;
  - a title and one sentence on why they differ, for example "You had a higher HRV, which WHOOP leans on. But you also had more broken sleep and less REM, which Attuned weighs more for how you'll feel.";
  - the drivers with values against usual;
  - the health metrics;
  - the playlist, with album art, a summary of what's in it, why that kind of music should help (with linked sources from RESEARCH.md), and the why-line under each song.
- **Published days.** A published day lists the songs on its Spotify playlist, in that order, and its green button opens the playlist. If the replay no longer has every published song (the playlist is out of date), the page lists the replay's songs and the button plays the first song instead, so the button never opens different songs from the page.
- **Supporting data.** Album art comes from Spotify's public embed endpoint and is cached locally. Only real answers are cached: a picture, or "not found". A server error is asked again next build, and a rate limit stops art fetching for the rest of the build. The score history is built once per run and shared by scoring, playlists and the page.

**The WhatsApp DJ** (`whatsapp/`, `intelligence/nl_song_selector.py`, `main.py request`).

- **Picking songs.** The whole classified library goes to a language model (Claude Sonnet), listed round-robin by artist with favourites marked. The model either asks one clarifying question or picks 20 songs by meaning. Code then removes duplicate versions and unavailable tracks.
- **Body context.** `intelligence/dj_context.attuned_context` is the only builder of the body context, for every path. It includes:
  - the Attuned score and colour;
  - the state and what the music is for;
  - the same reasons the page shows;
  - one calibration line, for example "today leans calm: prefer settling choices within what they asked for, unless they explicitly ask for energy".
- **Request first.** The prompt tells the model the request comes first and not to lecture.
- **No WHOOP.** WHOOP's recovery never reaches the prompt.
- **The request still gets an answer.** If building the context fails, the error is logged with its full traceback and the DJ is told there's no body data today, so it goes by the request alone. Over WhatsApp, a day's context is built once and reused for 10 minutes (it replays the score history, about 3 seconds), so a clarifying question and its answer don't build it twice, while WHOOP data synced later in the morning still gets through.

**Several people.** `--profile <name>` points any command at that person's own SQLite database, with their own tokens, usual and library.

## 8. Stack

- **Python and SQLite.** One local database file per person; no server.
- **WHOOP API** through a small custom client, and **Spotify** through Spotipy, both with OAuth (each person authorises their own accounts).
- **Essentia and TempoCNN** for audio analysis; **yt-dlp** to fetch clips where Spotify has no preview.
- **OpenAI GPT-4o-mini** to classify songs; **Anthropic Claude Sonnet** for the DJ.
- **Soundcharts** for tempo when a song has no clip.
- **Twilio** for WhatsApp.
- **macOS launchd** runs `scripts/daily.sh` each morning.

## 9. Where things live

- `intelligence/feeling_score.py`: the score, its mapping, drivers, headline and page data.
- `intelligence/signals.py`: each day's signals as z-scores against my usual.
- `intelligence/playlist_target.py`: the playlist target for a score position, the state and its wording.
- `intelligence/continuous_profile.py`: the day's target from its score, and the name and top-energy-day cut-offs.
- `intelligence/dates.py`: shifting "YYYY-MM-DD" dates.
- `intelligence/main_sleep.py`, `baselines.py`, `trends.py`, `sleep_analysis.py`: what counts as last night, personal usuals, HRV trend.
- `intelligence/dj_context.py`, `nl_song_selector.py`: the DJ's body context and song picking.
- `classification/`: song classification, audio analysis, tempo, song scores.
- `matching/`: selection, cohesion, why-lines, day replay, Spotify generation.
- `web/`: the page builder, its template, and publishing the latest days to Spotify.
- `whoop/`, `spotify/`, `db/`, `whatsapp/`: API clients, storage, the DJ server.
- `tests/`: unit and integration tests for all of the above.

## 10. Known limits

- **One person's validation.** The score has been checked against one person's memory of specific days, not against recorded feelings.
- **WHOOP's proportions.** The 0–100 mapping takes WHOOP's share of red, yellow and green days as given.
- **The ~2:1 weighting is unproven.** It's a design choice, not a measured result.
- **Some tempos are low confidence.** Songs with no clip rely on one outside source, and energetic songs that might be double are kept and flagged rather than corrected.
- **The DJ depends on an outside model.** Its picks can vary between runs, and it needs an API key and network access.
