# Key Decisions

The decisions that shaped Attuned, including the ones I got wrong first. Each has the situation, what I tried, what went wrong, and what I changed. Numbers are from my own WHOOP and Spotify data at the time of the change. The full detail is in the commit messages, which record the before and after of each.

A few terms used throughout:

- **Usual:** my own average over the last 30 days.
- **z-score:** how far today sits from my usual, measured in my typical day-to-day wobble. +1 means "one typical wobble better than usual".
- **Position:** where today's score ranks among all my earlier days, from 0 (below every earlier day) to 1 (above every one).

---

## 1. Answer "how will I feel?", not "how ready am I?", and leave WHOOP's recovery out

**Situation.** On April 7, 2026 WHOOP said 81% and I felt drained. On April 8 it said 59% and I felt great. WHOOP describes its recovery as how prepared your body is to perform, and says it relies mostly on HRV. My HRV had bounced back on the 7th while my REM and sleep quality hadn't.

**What I tried first.** A 12-signal profile in which WHOOP's recovery score and its change since yesterday were two of the twelve inputs.

**What went wrong.** WHOOP's recovery is itself built from HRV, resting heart rate and sleep. Including it counted those signals twice. It also meant my score was partly a copy of the WHOOP number I wanted to compare it with. On the page, the two rings would agree partly because one contained the other.

**What I changed.** The Attuned score uses 11 "compared with my usual" signals and never WHOOP's recovery. I added last night's total sleep, because without it a very short night only counted through its deep and REM hours. WHOOP's number appears on the page only as the thing being compared against.

**Evidence.** April 7: WHOOP 81, Attuned 57. The page explains it: higher HRV than usual, but broken sleep and less REM.

---

## 2. Weight sleep about twice the heart signals, and call it a design choice

**Situation.** What I read pointed one way: sleep is more closely tied to next-day mood than HRV is. I wanted the score to reflect that.

**What went wrong, twice.**

- **The weights drifted.** When I rebuilt the profile as a continuous weighted sum, the heart and recovery signals ended up outweighing sleep about 2.5 to 1, the reverse of what I intended. On April 7 that profile chose an energy playlist, the opposite of how I felt.
- **The justification was wrong.** I had backed the roughly 2:1 ratio with correlation figures credited to "Vitale 2015" and "Hynynen 2011". When I checked, there is no such Vitale paper, and Hynynen 2011 reports no such figure. Another source was credited to the wrong authors.

**What I changed.** Sleep signals together carry about twice the weight of the heart signals together. When I removed WHOOP's recovery (decision 1), I scaled the heart weights up so the ratio stayed near 2:1 instead of quietly growing. In the code and every doc, the ratio is labelled as my design choice, informed by research on sleep and mood. No study gives it.

**Still open.** Whether 2:1 is right is exactly what daily feeling check-ins would test.

---

## 3. Put the score on WHOOP's curve

**Situation.** A weighted average of z-scores is a number like −0.4 or +1.1. It's meaningless next to WHOOP's 0–100 ring.

**Options.** A fixed formula (for example, 50 + 20 × the average) would put the two rings on different curves. Then any difference could just mean "Attuned runs high", not "Attuned disagrees about this day".

**What I chose.** Percentile matching. Today's result is ranked among all my earlier days, and the score is my WHOOP recovery at that same rank. Over my history, Attuned has the same share of red, yellow and green days as WHOOP, so the rings only differ in which days they call good or bad. Only earlier days are used, so a past day's score never changes as new data arrives. It needs 60 earlier scored days before it will give a number.

**The trade-off, stated plainly.** This borrows WHOOP's idea of how often days are bad. If WHOOP calls too many days red, so does Attuned. Real feeling check-ins should replace this calibration.

**Evidence.** On my history the two scores share a colour on roughly seven days in ten, and are never two colours apart. Where they disagree there's a consistent pattern: Attuned is lower after a high-HRV morning that followed broken or short sleep, and higher after a long, deep night with low HRV.

---

## 4. Cite research only for the problem

**Situation.** The early docs and code comments justified weights, tempo ranges, thresholds and a mood table with research citations. It read as rigorous.

**What I did.** I listed every source cited anywhere in the repo and my site, 73 in all, and checked each one against the actual paper.

**What went wrong.** Many didn't hold up. Some didn't exist as cited, some were credited to the wrong authors, and some said something different from my claim. One study I cited for "your own music has stronger physiological effects" found the opposite. Another was cited with its direction reversed.

**What I changed.** [RESEARCH.md](RESEARCH.md) now rests on 11 sources, each checked against the paper, plus WHOOP's own public statements. Research is cited for one thing only: that the problem is real (sleep is tied to how you feel, readiness and feeling can come apart, music changes your state). Every design choice (signals, weights, thresholds, song scoring, tempo ranges) is labelled as mine. The page cites a study only next to the claim it supports, for example slower music tending to lower heart rate.

---

## 5. "Last night" means the main night's sleep, never a nap

**Situation.** WHOOP records naps as separate sleeps. I never stored WHOOP's nap flag.

**What went wrong.** For a date with a nap and a night, the code took the first record, which was the afternoon nap on 62 of 83 such dates, and summed deep, REM and light sleep across both. On one date a 1.3-hour nap at 99% efficiency replaced a 3.9-hour night at 82%. The daily sync could also keep the nap and drop the night entirely.

**What I changed.** The nap flag is stored. "Last night" is the longest non-nap sleep, never a sum. Sleep debt still counts naps, because a nap really is sleep you got.

**Related fix: short nights.** A 2.5-hour night is naturally unbroken and front-loaded with deep sleep, so it was scoring as good sleep. On one such day Attuned said 60 against WHOOP's 22, with the headline "your sleep held up". Now, after a night under 6 hours, efficiency and deep-sleep share can't count as good news, and the headline never credits sleep. That day dropped from 60 to 43.

**Evidence.** The backfill flagged 84 naps. The playlist's state changed on 54 days, all of them days where a nap had leaked in.

---

## 6. Date every record in local time

**Situation.** WHOOP sends times in UTC (one global reference clock) plus the wearer's time-zone offset in a separate field. I ignored the offset.

**What went wrong.** In India, a night ending before 5:30 a.m. local time ends "yesterday" in UTC. Those nights landed on the previous date, so 11 dates held two nights and the next date held none. Recoveries are stored one per date, so when two collided, one was silently dropped: 16 days of data gone, with no error.

**What I changed.** One helper turns a timestamp plus offset into a local date, and both the sleep and recovery parsers use it. A recovery takes the date of the night it scores. The daily sync reads a three-day UTC window and keeps the records whose local date matches. The history re-dating runs in one transaction, so a half-finished run can't lose rows.

**Evidence.** Recovery days went from 16 short of WHOOP's count to an exact match. Dates holding two nights went from 11 to 0. No stored value changed.

---

## 7. Drive the playlist from the Attuned score

**Situation.** Even after I built the Attuned score, the daily playlist still came from the older 12-signal weighted profile.

**What went wrong.**

- **It was nearly flat.** Signals pushing in opposite directions cancelled out. On a typical day the leading dimension (calm, energy or grounding) was ahead of the next by about 0.06 on a 0-to-1 scale, and on 30% of days by under 0.03. Labels were close to coin flips, and the same balanced songs won every day.
- **It quietly followed WHOOP.** Recovery was still an input to the target. The playlist names came straight from WHOOP's recovery ("Rest & Repair" whenever recovery was under 50), and motivational songs were unlocked by the old WHOOP-based classifier.

**What I changed.**

- **One source.** The target now comes only from the Attuned score's position, blended in a straight line between three fixed points: calm at the bottom, steady in the middle, energy at the top. A lower score always means a calmer target, with no jumps.
- **Names and unlocks follow too.** Playlist names and the motivational-song unlock follow the same position. WHOOP plays no part in any of them.
- **The old code is gone.** The weighted profile, the WHOOP-based state mapper and its constants were deleted so they can't come back by accident.

**Evidence.**

- The typical lead went from 0.06 to 0.16.
- Once the Attuned score is accounted for, the playlist's remaining link to WHOOP went from 0.21 to 0.03, which is essentially none.
- In a 30-day replay, energy and rest days went from sharing some songs to sharing none, and calm-day songs got slower and softer.

**What I didn't do.** I tried pulling "mixed" days (where sleep and heart signals disagree) toward the middle. It moved few days, had no ground truth to justify it, and would break "same score, same playlist". I left it out.

---

## 8. Fix song tempo at the root

**Situation.** Tempo is the biggest single factor in whether a song scores as calming or energising. For slow Bollywood songs it was often wrong: a ballad you'd clap at 76 beats per minute stored as 152.

**What I found.** Audio beat trackers often count the strummed notes between beats and report double the real tempo. The language model I use to classify songs has the opposite weakness: it guesses round numbers, but it almost never gets the tempo doubled. My pipeline let the audio analysis overwrite the classified tempo after the fact, so the check that should have caught doubling never ran. One of the four audio "votes" was also broken, returning only 3 distinct values across hundreds of songs.

**How I measured it.** I built a hand-checked sample of 113 songs. Only 67% of stored tempos were right, and only 53% for slow romantic Bollywood, with almost a quarter of those doubled. Twelve of the 20 songs on my April 8 calming playlist had the wrong tempo.

**What I changed.** One module is now the only code that writes a song's tempo. It takes the exact number from where the three audio trackers agree, and lets the classifier's guess choose between half, same or double. Raw readings are kept in their own columns. Rap keeps its listed fast tempo. Energetic songs are never halved, because that's where the rule is least reliable. A tempo I set by hand is never overwritten. Songs with no audio clip get their tempo from a music data service.

**Evidence.** Accuracy on the sample went from 67% to 92%. On the songs where the right answer was certain, it went from 84% to 100%, and on slow Bollywood from 53% to 88%. No energetic song in the library was halved.

---

## 9. For spoken requests, let the model pick the songs

**Situation.** For the WhatsApp DJ, I first turned the request into the same three numbers the daily playlist uses (how calming, energising and grounding), then picked songs by maths.

**What went wrong.** Three numbers can't hold what a request means. "Dark, seductive, Weeknd" and "soft romantic Bollywood" came out as similar numbers. Someone asking for the first got the second.

**What I changed.** The DJ gives a language model the whole classified library (name, artist, genre, mood, energy, with favourites marked) and lets it pick 20 songs by meaning. Getting this right took several rounds:

- **A smaller model** skimmed and picked unrelated songs.
- **A library sorted by play count** made it pile onto one artist (13 of 20 songs).
- **A shuffled library** lost the sense of what I actually like.
- **What worked:** listing the library round-robin by artist, with favourites marked, plus code that removes duplicate versions of the same song.

**Evidence.** "Dark seductive Weeknd" now returns songs like Earned It and Starboy instead of Bollywood love songs. The daily playlist still uses the numeric path, because there the input really is a number (the score), not words.

---

## 10. The DJ that ran blind

**Situation.** The DJ is meant to know how my body is doing, so a vague request leans the right way.

**What went wrong.** The WhatsApp handler and the `request` command called the body-state function without the date it required. The error was caught by a catch-all and replaced with "No body data available". So the DJ had been running without any body context since I built it, and nothing looked broken. The one path that did get body data used WHOOP recovery buckets ("full energy is fair game" above 80%), not the Attuned score.

**What I changed.** One function builds the DJ's body context for every path (WhatsApp, the command line, and the shared generator). It contains:

- the Attuned score and colour;
- the day's state and what the music is for;
- the same plain reasons the page shows;
- one calibration line, for example "today leans calm: prefer settling choices within what they asked for".

The request still comes first. WHOOP's recovery never reaches the prompt. Errors now surface instead of turning silently into "no data". An unused module that still built prompts from WHOOP buckets was deleted.

**The lesson I took.** A fallback that swallows errors can hide a feature that never worked. Unit tests passed the whole time. Only reading what the model was actually sent showed the problem.
