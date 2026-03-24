# Onboarding a New User

Step-by-step guide to set up Attuned for a new person. One command runs the full pipeline once the prerequisites are in place.

---

## Prerequisites

- A **WHOOP** account with an active membership (any tier)
- A **Spotify** account (free or premium)
- Python 3.11+ installed
- The Attuned repo cloned and dependencies installed (`pip install -r requirements.txt`)

---

## 1. Set Up API Credentials

You need developer apps registered with both WHOOP and Spotify. These are shared across all users — you only do this once.

### WHOOP

1. Go to [developer.whoop.com](https://developer.whoop.com)
2. Create an application
3. Set the redirect URI to `http://localhost:8080/callback`
4. Copy the **Client ID** and **Client Secret**

### Spotify

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create an application
3. In Settings, add the redirect URI: `https://localhost:8080/spotify/callback`
4. Copy the **Client ID** and **Client Secret**

### Add to `.env`

Copy `.env.example` to `.env` and fill in the values:

```
WHOOP_CLIENT_ID=your_whoop_client_id
WHOOP_CLIENT_SECRET=your_whoop_client_secret
WHOOP_REDIRECT_URI=http://localhost:8080/callback

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=https://localhost:8080/spotify/callback

OPENAI_API_KEY=your_openai_key
```

---

## 2. Run OAuth Flows

Each user needs to authorize their own WHOOP and Spotify accounts. Replace `<name>` with a short profile name (e.g., `komal`, `pranav`).

```bash
# Authorize WHOOP — opens browser, log in with the user's WHOOP account
python oauth_server.py --profile <name> whoop

# Authorize Spotify — opens browser, log in with the user's Spotify account
python oauth_server.py --profile <name> spotify
```

Each command opens a browser window. The user logs in, grants permissions, and the tokens are stored in their profile database (`db/<name>.db`).

---

## 3. Optional: Export Spotify Extended Streaming History

This gives Attuned your full listening history (years of data), which dramatically improves engagement scoring and song selection.

1. Open Spotify → **Settings** → **Privacy** → **Request your data**
2. Check **Extended streaming history**
3. Wait for the email (takes 5-30 days)
4. Download and unzip the files to a folder (e.g., `~/Desktop/spotify-export`)

If you skip this, Attuned still works — it uses your liked songs and top tracks. But engagement scores will be less accurate with fewer data points.

---

## 4. Run Onboarding

One command runs the full pipeline:

```bash
python main.py --profile <name> onboard --history-dir /path/to/spotify-export
```

### Flags

| Flag | Required | Description |
|------|----------|-------------|
| `--profile <name>` | Yes | User profile name |
| `--history-dir /path` | No | Path to Spotify extended history export folder |
| `--skip-audio` | No | Skip audio download + Essentia analysis (faster, less accurate) |
| `--resume-from <step>` | No | Resume from a specific step after a failure |

### Examples

```bash
# Full onboarding with extended history
python main.py --profile komal onboard --history-dir ~/Desktop/spotify-export

# Without extended history
python main.py --profile komal onboard

# Skip audio analysis (faster, use LLM-only classification)
python main.py --profile komal onboard --skip-audio

# Resume after a failure
python main.py --profile komal onboard --resume-from classify-songs
```

---

## 5. What Happens

The onboard command runs these steps in order:

| # | Step | What it does |
|---|------|-------------|
| 1 | **verify-auth** | Checks WHOOP + Spotify tokens exist. Fails early if OAuth isn't done. |
| 2 | **ingest-history** | Parses extended streaming history JSON files into the database. Only runs if `--history-dir` is provided. |
| 3 | **sync-whoop-history** | Pulls full WHOOP recovery and sleep history via the API. |
| 4 | **sync-spotify** | Syncs liked songs, top tracks, fetches metadata, deduplicates, and computes engagement scores. |
| 5 | **download-audio** | Downloads 30-second audio clips via yt-dlp for Essentia analysis. Skipped with `--skip-audio`. |
| 6 | **analyze-audio** | Runs Essentia audio feature extraction on downloaded clips. Skipped with `--skip-audio`. |
| 7 | **classify-songs** | Sends songs to OpenAI for LLM classification (BPM, energy, valence, mood, genre, neuro scores). |
| 8 | **recompute-scores** | Recomputes neurological impact scores from all classification data. |
| 9 | **generate-preview** | Generates a dry-run playlist to verify everything works end-to-end. |

If any step fails, the command prints the exact resume command to pick up where it left off.

---

## 6. Expected Time and Cost

### With `--skip-audio` (recommended for first run)

- **Time:** ~5 minutes
- **Cost:** LLM classification only

### With audio analysis (full pipeline)

- **Time:** 2-4 hours (yt-dlp download is the bottleneck)
- **Cost:** LLM classification + negligible compute

### LLM classification cost (OpenAI gpt-4o-mini)

Songs are classified in batches of 5. Each batch costs ~$0.01.

| Library size | Batches | Estimated cost |
|-------------|---------|----------------|
| ~750 songs | ~150 | ~$1.50 |
| ~2,000 songs | ~400 | ~$4.00 |
| ~4,000 songs | ~800 | ~$8.00 |

Formula: `(song_count / 5) x $0.01`

---

## 7. After Onboarding

Daily usage — run this each morning after your WHOOP recovery data is in:

```bash
python main.py --profile <name> generate
```

This reads today's WHOOP data, classifies your physiological state, matches songs from your library, and creates a new Spotify playlist.

For a dry run (no Spotify playlist created):

```bash
python main.py --profile <name> generate --dry-run
```

---

## 8. Troubleshooting

### "Missing: WHOOP" or "Missing: Spotify"

OAuth tokens aren't stored. Re-run the OAuth flow:

```bash
python oauth_server.py --profile <name> whoop
python oauth_server.py --profile <name> spotify
```

### Step failed mid-onboarding

The error message includes the resume command. Example:

```
  To resume:
    python main.py --profile komal onboard --resume-from classify-songs
```

### WHOOP token expired

WHOOP tokens expire after 1 hour. If sync-whoop-history fails with an auth error, re-run the WHOOP OAuth flow, then resume.

### OpenAI rate limit or credit exhaustion

Switch to Anthropic by setting `ANTHROPIC_API_KEY` in `.env`. The classify-songs step uses OpenAI by default. To use Anthropic, run classification manually:

```bash
python main.py --profile <name> classify-songs --provider anthropic
```

Then resume onboarding from the next step:

```bash
python main.py --profile <name> onboard --resume-from recompute-scores
```

### yt-dlp download is slow

Audio downloads can take hours for large libraries. Use `--skip-audio` for the initial onboarding, then run audio steps separately later:

```bash
python main.py --profile <name> download-audio
python main.py --profile <name> analyze-audio
python main.py --profile <name> recompute-scores
```
