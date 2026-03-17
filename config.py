"""Configuration constants, thresholds, and environment variable loaders."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "attuned.db"
STREAMING_HISTORY_DIR = os.getenv(
    "STREAMING_HISTORY_DIR",
    str(Path.home() / "Desktop" / "Spotify Extended Streaming History"),
)

# ---------------------------------------------------------------------------
# WHOOP
# ---------------------------------------------------------------------------
WHOOP_BASE_URL = "https://api.prod.whoop.com/developer"
WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_SCOPES = [
    "read:recovery",
    "read:cycles",
    "read:sleep",
    "read:profile",
    "read:body_measurement",
    "offline",
]
WHOOP_PAGE_SIZE = 25

# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------
SPOTIFY_SCOPES = [
    "user-library-read",
    "user-read-recently-played",
    "user-top-read",
    "playlist-modify-private",
    "user-read-private",
]
SPOTIFY_BATCH_SIZE = 50

# ---------------------------------------------------------------------------
# Engagement scoring
# ---------------------------------------------------------------------------
MIN_PLAY_DURATION_MS = 30_000
MIN_MEANINGFUL_LISTENS = 5

# ---------------------------------------------------------------------------
# Intelligence thresholds (used in later days)
# ---------------------------------------------------------------------------
BASELINE_WINDOW_DAYS = 30
ROLLING_WINDOW_DAYS = 7
MIN_BASELINE_DAYS = 14
HRV_DECLINE_DAYS = 3
HRV_DECLINE_SD = 1.0
SLEEP_DEFICIT_SD = 1.5
CV_ELEVATED = 0.15
CV_SIGNIFICANT = 0.20
TOKEN_EXPIRY_BUFFER_SECONDS = 300  # 5-minute buffer before refresh


# ---------------------------------------------------------------------------
# Environment variable getters — fail loudly when missing
# ---------------------------------------------------------------------------
def get_whoop_client_id() -> str:
    val = os.getenv("WHOOP_CLIENT_ID")
    if not val:
        raise RuntimeError("WHOOP_CLIENT_ID not set in environment / .env")
    return val


def get_whoop_client_secret() -> str:
    val = os.getenv("WHOOP_CLIENT_SECRET")
    if not val:
        raise RuntimeError("WHOOP_CLIENT_SECRET not set in environment / .env")
    return val


def get_whoop_redirect_uri() -> str:
    return os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8080/callback")


def get_spotify_client_id() -> str:
    val = os.getenv("SPOTIFY_CLIENT_ID")
    if not val:
        raise RuntimeError("SPOTIFY_CLIENT_ID not set in environment / .env")
    return val


def get_spotify_client_secret() -> str:
    val = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not val:
        raise RuntimeError("SPOTIFY_CLIENT_SECRET not set in environment / .env")
    return val


def get_spotify_redirect_uri() -> str:
    return os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/spotify/callback")
