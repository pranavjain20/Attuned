# Attuned — Workflow

Project-specific development process: commands, branching, testing, deployment.

---

## Key Commands

```bash
# Generate today's playlist
python main.py generate

# Run all tests
pytest tests/ -x -v

# Run single test file
pytest tests/test_specific.py -x -v

# Run single test
pytest tests/test_specific.py::test_name -x -v

# Sync Spotify data (liked songs + top tracks + metadata)
python main.py sync-spotify

# Sync for second user
python main.py --profile komal sync-spotify

# Classify songs via LLM
python main.py classify-songs

# Recompute neuro scores (no API calls)
python main.py recompute-scores

# Check today's physiological state
python main.py classify-state

# Dry-run playlist (no Spotify push)
python main.py generate --dry-run
```

## Git Strategy

- **Main branch**: always stable, tests passing
- **Feature branches**: `feat/[component]-[feature]`, `fix/[component]-[description]`, `test/[component]-[what]`
- **Squash merge** to main after review
- **Never merge** without all tests passing

## Testing

- `pytest tests/ -x -v` after every change
- If no tests exist yet: write at least 2 tests first, then make them pass
- Never say "done" without running the full suite and seeing all green
- Currently: 1,044 tests

## Environment

- Python 3.11+ with venv (`.venv/`)
- `.env` for API keys (WHOOP, Spotify, OpenAI, Anthropic)
- SQLite database at `db/attuned.db` (gitignored)
- Audio clips at `audio_clips/` (gitignored)

## API Keys

| Service | Where | Notes |
|---------|-------|-------|
| WHOOP | developer.whoop.com | OAuth 2.0, tokens expire in 1 hour, offline scope for refresh |
| Spotify | developer.spotify.com | Dev mode app, batch endpoint returns 403, single-track with 3s throttle |
| OpenAI | platform.openai.com | GPT-4o-mini for song classification |
| Anthropic | console.anthropic.com | Claude Sonnet fallback |
