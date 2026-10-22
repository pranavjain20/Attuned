# Attuned

Attuned reads the same WHOOP data as WHOOP's recovery score but answers a different question. WHOOP's recovery asks "how prepared is my body to perform?". Attuned asks "how am I likely to feel today?". It shows that answer as a 0–100 score next to WHOOP's, explains why the two differ, and builds a playlist from my own Spotify library that suits the day.

See a live day: LIVE_LINK

## The problem

I've worn a WHOOP for over three years and checked my recovery score every morning. Over time I noticed days where I felt like a green but WHOOP showed red, and days where WHOOP showed green but I felt like a red. A lot of my friends said the same.

WHOOP says its recovery score is "a daily measure of how prepared your body is to perform" and that it relies mostly on HRV (heart rate variability, how much the gap between heartbeats varies; a sign of whether your nervous system has bounced back overnight). That makes sense for the question WHOOP was built to answer: how hard should an athlete train today? But most people wearing it aren't asking that. They're asking how they'll feel.

Two days made this concrete for me:

- **April 7, 2026.** WHOOP said 81%, green. I felt tired, worked up and low on energy. My HRV was well above my usual, but my REM sleep was 1.2 hours, well below my normal, and my sleep was broken. My nervous system had recovered. My sleep hadn't.
- **April 8, 2026.** WHOOP said 59%, yellow, down 22 points. I woke up happier and more energetic than I'd felt all week. My REM had nearly doubled to 2.1 hours, but my HRV had dipped.

Research supports the direction: how you slept is closely tied to how you feel the next day, and HRV-led readiness scores can come apart from how people feel. The sources, and what they do and don't show, are in [docs/RESEARCH.md](docs/RESEARCH.md). The longer story is in my essay, [Why WHOOP's Recovery Score Is Wrong (For Most of Us)](https://pranavjain20.vercel.app/writing/why-whoops-recovery-score-is-wrong).

A better number on its own didn't change anything for anyone, though. People don't change habits because of a score. But almost everyone already listens to music every day, so that's where Attuned acts.

## How it works

**1. A score for how you'll likely feel.** Each morning Attuned compares last night and this morning with my own usual (my last 30 days), signal by signal: sleep efficiency (share of time in bed actually asleep), deep sleep, REM, total sleep, 7-night sleep debt, deep-sleep share, HRV, resting heart rate, and their recent changes. Sleep counts for about twice as much as the heart signals. That ratio is my design choice, informed by the research, not a number any study gives. WHOOP's recovery score is not an input, so the Attuned score can't quietly become a copy of WHOOP's.

**2. Put on WHOOP's scale.** The result is mapped onto 0–100 so that, over my history, Attuned has the same share of red, yellow and green days as WHOOP. The two rings only disagree about *which* days are good or bad, which makes the disagreement the interesting part. Only earlier days are used, so a day's score never changes later.

**3. A playlist for what's good for you today.** The playlist isn't chosen to mirror my mood. It's chosen for what should help, given how I'll likely feel:

- a low score: music built to help me settle (slower, softer);
- a middle score: music built to keep me level (steady, familiar);
- a high score: music built to give me a lift (brighter, faster).

Songs come only from my own Spotify library. Each one has been classified from its audio and its metadata (tempo, energy, mood, genre), and the playlist is picked to sound coherent together and to rotate through the library instead of repeating favourites.

**4. The page.** For each day, the page shows the Attuned ring first and WHOOP's second, a plain sentence on why they differ, the signals that moved the score (with real numbers against my usual), the day's health metrics, and the playlist: what's in it, why that kind of music should help (with the sources), and one plain reason under every song.

**5. The WhatsApp DJ.** I can text what I want ("something for a late-night drive", "hype me up for the gym") and get a Spotify playlist back. The request always comes first. The Attuned score only tunes it: on a low day, a vague request leans gentler; on a high day, it can lean brighter. If the request is unclear, the DJ asks one question.

## What I don't claim

- **It's checked against one person.** I've compared the score with my own memory of how I felt on specific days, using my own data. That is not a study, and it may not hold for anyone else. The next step is a daily "how do you feel?" check-in so the score can be tested and calibrated against real answers instead of memory.
- **It doesn't fix every day.** April 7 moves from WHOOP's 81 to 57 on Attuned. April 8, the day I felt best, stays at 59 on both: my deep sleep was below my usual and offsets the REM.
- **It borrows WHOOP's idea of how often days are bad.** Matching WHOOP's share of red, yellow and green days keeps the two rings comparable, but it means Attuned assumes WHOOP has the right *proportion* of bad days.
- **The design is mine, not the literature's.** Research is cited only for the problem (sleep is tied to feeling; readiness and feeling can diverge; music changes your state). The signals, weights, thresholds and song-scoring rules are my own choices, labelled that way.
- **The music effects are modest and general.** Studies show slower music tends to calm the body and faster music to raise heart rate. I don't claim a given playlist will change how you feel by a measurable amount.

## Running it

Attuned runs locally on Python 3.11+, with SQLite. You need your own WHOOP and Spotify developer apps, plus API keys for the song classifier and the DJ. Copy `.env.example` to `.env` and fill it in. To onboard a friend with their own accounts, see [Attuned-Auth](https://github.com/pranavjain20/Attuned-Auth).

```bash
pip install -r requirements.txt
python oauth_server.py whoop          # connect WHOOP
python oauth_server.py spotify        # connect Spotify
python main.py onboard                # history, library sync, audio analysis, classification
```

The main commands:

```bash
python main.py generate                          # today's playlist, pushed to Spotify
python main.py generate --dry-run                # same, without touching Spotify
python main.py feeling-score --date 2026-04-07   # the day's score and explanation (--json for page data)
python main.py playlist-json --date 2026-04-07   # any day's playlist and per-song reasons, read-only
python main.py build-site --days 30              # write the day-by-day page to web/dist/index.html
python main.py request "late night drive, dark and moody"   # the DJ from the command line
python -m whatsapp.server                        # the DJ on WhatsApp (needs Twilio)
```

`python main.py` with no command lists the rest (syncing, classification, tempo tools). `--profile <name>` runs any command against another person's database. `scripts/daily.sh` is the morning job: sync WHOOP, then generate.

## Docs

- [docs/PRD.md](docs/PRD.md): the problem, who it's for, goals and non-goals, and how I'd know it works.
- [docs/DECISIONS.md](docs/DECISIONS.md): the key decisions, including what went wrong and what changed, with before and after evidence.
- [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md): the technical walk-through, from WHOOP sync to the page.
- [docs/RESEARCH.md](docs/RESEARCH.md): the studies Attuned rests on, what they do and don't show, and which choices are mine.

## License

MIT. See [LICENSE](LICENSE).
