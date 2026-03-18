# Attuned

Spotify playlist generator using WHOOP recovery data and music neuroscience.

## What it does

Reads your WHOOP data every morning — HRV, resting heart rate, sleep architecture, sleep debt — classifies your physiological state into one of six categories, then generates a Spotify playlist of 15-20 songs from your own library whose acoustic properties are scientifically matched to what your body needs.

## How it works

1. **WHOOP → physiological state.** Pulls recovery and sleep data, computes personal baselines (30-day rolling averages), detects multi-day trends, and classifies into one of six states: Accumulated Fatigue, Physical Recovery Deficit, Emotional Processing Deficit, Poor Recovery, Baseline, or Peak Readiness.

2. **Spotify library → classified song pool.** Every song in your library gets classified by properties that affect the autonomic nervous system — tempo, energy, acousticness, instrumentalness, valence, mode, danceability. Classification is LLM-based (GPT-4o-mini), scored using research-backed neurological impact weights.

3. **State + songs → playlist.** Maps the detected state to target song property ranges grounded in neuroscience research. Selects matching songs, orders them using the iso principle (start near current state, gradually transition toward target), and creates a dated Spotify playlist with a description explaining the reasoning.

## The science

Music modulates the autonomic nervous system — the same system WHOOP measures. Slow tempo (60-80 BPM) increases parasympathetic activity and HRV. Fast tempo activates the sympathetic response. Acoustic instruments, instrumental music, and major keys each have documented calming effects. Personal preferred music amplifies these benefits.

Every threshold, weight, and property range in the system traces back to published research. See [docs/RESEARCH.md](docs/RESEARCH.md) for the full analysis with citations.

## Tech stack

- Python 3.11+
- SQLite
- Spotipy (Spotify), httpx (WHOOP), pandas + numpy (computations), Pydantic (validation)
- OpenAI GPT-4o-mini for song classification

## Status

Pre-build. PRD and research complete, ready to start implementation. See [STATUS.md](STATUS.md) for current state.
