# Attuned

Attuned turns my WHOOP data into a daily score for how I'm likely to feel, and builds a playlist from my own Spotify library for that day.

## The problem

WHOOP's recovery score answers one question: how prepared is my body to perform today? It leans mostly on HRV (heart rate variability, a sign of whether the nervous system bounced back overnight). That's the right question for an athlete deciding how hard to train. But most people who check their recovery every morning are really asking something else: how am I going to feel today?

Those two questions often have different answers. HRV can bounce back after a single night even when the sleep itself was short or broken, and how you slept is closely tied to how you feel the next day. So there are mornings when WHOOP says green and you feel drained, and mornings when it says yellow and you feel great. And even a better number wouldn't change much on its own, because people don't change their day over a score. Music is different: almost everyone already listens every day, so that's where Attuned acts.

## How it works

Every morning, Attuned compares last night with my own usual over the past 30 days, signal by signal: how long I slept, how broken the sleep was, deep sleep, REM, sleep debt over the week, HRV and resting heart rate. Sleep counts for about twice as much as the heart signals, because how you slept matters more for how you feel than whether your body is ready to train. WHOOP's own recovery number is deliberately not an input.

That comparison becomes a 0–100 score on the same scale as WHOOP's, with the same share of red, yellow and green days across my history. The two scores therefore only disagree about which days were good or bad, and those disagreements are the point: they're the days where how ready my body is and how I'll feel come apart.

The score then decides the music. On a low day the playlist is built to help me settle, with slower, softer songs. On a middling day it's built to keep me level. On a high day it's built to give me a lift, with brighter, faster songs. Every song comes from my own library, each one classified from its audio and metadata (tempo, energy, mood, genre), and the playlist is picked to sound coherent and to rotate rather than repeat the same favourites.

Each day lives on one page: the Attuned score next to WHOOP's, a sentence on why they differ, the signals that moved the score, and the day's playlist with a one-line reason under every song. There's also a WhatsApp DJ: I text what I want ("something for a late-night drive") and get a playlist back, with the day's score quietly shaping the picks.

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

`python main.py` with no command lists the rest (syncing, classification, tempo tools). `--profile <name>` runs any command against another person's database.

More detail: [PRD](docs/PRD.md) · [Key decisions](docs/DECISIONS.md) · [How it works, technically](docs/HOW_IT_WORKS.md) · [Research](docs/RESEARCH.md)

## License

MIT. See [LICENSE](LICENSE).
