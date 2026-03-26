# Attuned — Tech Stack

Technology choices with rationale. Each choice: what, why, alternatives considered.

---

| Technology | Choice | Why | Alternatives Considered |
|-----------|--------|-----|------------------------|
| **Language** | Python 3.11+ | Data science ecosystem (pandas, numpy), LLM SDKs, Essentia bindings. Single-user tool — performance isn't the bottleneck. | Node.js (weaker data science), Go (no Essentia bindings) |
| **Database** | SQLite | Single-user, local, zero setup, one file. No server, no Docker, no connection strings. Portable. | PostgreSQL (overkill for single-user), JSON files (no queries) |
| **WHOOP API** | Custom thin client (httpx) | No official SDK. OAuth 2.0 with offline refresh tokens, paginated endpoints (25/page), timezone-aware timestamps. | Requests (httpx is async-ready, better timeout handling) |
| **Spotify API** | Spotipy | Mature Python SDK, handles OAuth, token refresh, pagination. Batch endpoint returns 403 on dev-mode apps — we use single-track calls with 3-second throttle. | Raw httpx (more control but reinventing OAuth) |
| **Computations** | pandas + numpy | Rolling averages, trend slopes (linregress), standard deviations, CVs. All personal baseline math. | Pure Python (slower, verbose), polars (overkill for <1K rows) |
| **Song Classification** | OpenAI GPT-4o-mini (primary), Anthropic Claude Sonnet (fallback) | LLM classifies BPM, energy, valence, mood, genre from song name + artist. Provider-agnostic wrapper — switch with a config flag. GPT-4o-mini best for factual recall (BPM). ~$0.01 per 5 songs. | Spotify audio features API (deprecated), manual tagging (doesn't scale) |
| **Audio Analysis** | Essentia | Open-source, runs locally. Key/mode detection (92% usable), energy (RMS/0.35), acousticness (spectral flatness). Cross-validates LLM estimates. | librosa (slower, less accurate on our tests), TempoCNN (same accuracy, larger model) |
| **CLI** | argparse (stdlib) | Simple, no dependencies. Single entry point (`main.py`). | Click (heavier), Typer (dependency for no gain) |
| **Audio Download** | yt-dlp | Duration-verified YouTube download (Strategy D). 99.1% coverage. Fallback when Spotify previews unavailable. | Spotify previews (30s only, many songs have none) |
