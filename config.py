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
AUDIO_CLIPS_DIR = PROJECT_ROOT / "audio_clips"


def get_profile_db_path(profile: str | None) -> Path:
    """Return DB path for a named profile.

    No --profile flag → existing attuned.db (backward compatible).
    --profile <name> → db/<name>.db
    """
    if profile is None:
        return DB_PATH
    return PROJECT_ROOT / "db" / f"{profile}.db"
AUDIO_CLIP_DURATION_SECONDS = 30
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
MIN_CLASSIFICATION_LISTENS = 2

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
RHR_ELEVATED_BPM = 5           # RHR above baseline → caution (used in trend detection)
RHR_PEAK_MAX_BPM = 2           # Max RHR above baseline for Peak Readiness
SLEEP_DEBT_PEAK_HOURS = 3      # Absolute fallback: max debt for peak (used when debt baseline insufficient)
DEEP_SLEEP_MIN_RATIO = 0.10    # Absolute floor: <10% = deficit
DEEP_SLEEP_MIN_MS = 3_600_000  # Absolute floor: <1 hour = deficit
REM_SLEEP_MIN_RATIO = 0.15     # Absolute floor: <15% = deficit
SLEEP_ADEQUATE_SD = 1.0        # Within this many SDs of mean = "adequate"

# Recovery tiers (from real experience, not WHOOP's red/yellow/green)
RECOVERY_TIER_2_MAX = 40       # Definitively bad
RECOVERY_TIER_3_MAX = 60       # Struggling / stressed
RECOVERY_TIER_4_MAX = 80       # Functional / okay (above = great)

# Accumulated fatigue detection
FATIGUE_RECENT_DAYS = 5        # Look back window for multi-day pattern
FATIGUE_BAD_DAYS_MIN = 3       # Min bad days in window → fatigue
TOKEN_EXPIRY_BUFFER_SECONDS = 300  # 5-minute buffer before refresh

# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------
LLM_BATCH_SIZE = 5
LLM_MODEL_OPENAI = "gpt-4o-mini"
LLM_MODEL_ANTHROPIC = "claude-sonnet-4-20250514"
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_SECONDS = 2

# ---------------------------------------------------------------------------
# Matching engine
# ---------------------------------------------------------------------------
MIN_PLAYLIST_SIZE = 15
MAX_PLAYLIST_SIZE = 20
MIN_MATCH_FLOOR = 0.25  # Below this, log warning about insufficient coverage

# Cohesion: seed-and-expand selection
COHESION_POOL_SIZE = 60
COHESION_MIN_SIMILARITY = 0.15
COHESION_RELAXATION_STEP = 0.03
COHESION_RELAXATION_MAX = 3
COHESION_WEIGHTS = {
    "genre_tags": 0.20, "mood_tags": 0.15, "bpm": 0.20,
    "release_year": 0.20,
    "energy": 0.10, "acousticness": 0.05, "danceability": 0.05, "valence": 0.05,
}
COHESION_BPM_SIGMA = 10.0
COHESION_PROPERTY_SIGMA = 0.15

# Era cohesion: genre-aware production era similarity
# Sigma = standard deviation in years for Gaussian decay.
# Tight = production-driven genres that change fast.
# Wide = melody/performance matters more than production.
ERA_SIGMA_BY_GENRE = {
    # Tight — production-driven, changes fast
    "hip-hop": 2, "rap": 2, "edm": 2, "electronic": 2, "dance": 2,
    "punjabi": 2, "bhangra": 3,
    # Medium — production matters but not everything
    "pop": 3, "r&b": 3, "desi": 4,
    "indie": 4, "alternative": 4,
    "rock": 5, "bollywood": 6, "hindi": 6, "filmi": 6, "indi-pop": 5,
    "soul": 5, "funk": 5, "singer-songwriter": 6,
    # Wide — melody/performance > production
    "romantic": 6, "folk": 8, "acoustic": 8,
    "sufi": 10,
    # Era-agnostic — timeless forms
    "ghazal": 12, "qawwali": 12,
    "devotional": 20, "spiritual": 20,
    "classical": 20, "hindustani": 20, "carnatic": 20, "jazz": 20,
}
ERA_SIGMA_DEFAULT = 5

# State → neuro profile weights for dot-product scoring.
# Each state defines the ideal blend of parasympathetic, sympathetic, and grounding.
# Fatigue and physical recovery pushed further apart (gap 0.35 vs old 0.15).
STATE_NEURO_PROFILES: dict[str, dict[str, float]] = {
    "accumulated_fatigue":  {"para": 0.95, "symp": 0.00, "grnd": 0.05},
    "poor_sleep":           {"para": 0.50, "symp": 0.05, "grnd": 0.45},
    "poor_recovery":        {"para": 0.50, "symp": 0.10, "grnd": 0.40},
    "baseline":             {"para": 0.15, "symp": 0.50, "grnd": 0.35},
    "peak_readiness":       {"para": 0.00, "symp": 0.90, "grnd": 0.10},
}

# ---------------------------------------------------------------------------
# Mood tag → neuro dimension mappings (used in profiler)
# ---------------------------------------------------------------------------
# Weight given to mood tags in the profiler (existing audio weights scale to 1 - this)
MOOD_TAG_WEIGHT = 0.15

# Parasympathetic: absence of stimulation, rest, surrender
PARA_MOOD_TAGS = frozenset({
    "melancholy", "melancholic", "calm", "dreamy",
    "soothing", "serene", "relaxed", "chill", "laid-back", "peaceful",
    "sad",
})

# Sympathetic: energy, activation, arousal
SYMP_MOOD_TAGS = frozenset({
    "energetic", "uplifting", "upbeat", "celebratory", "joyful", "party",
    "fun", "confident", "festive", "motivational", "intense", "empowering",
    "danceable", "dynamic", "aggressive", "rebellious", "powerful",
    "triumphant", "vibrant", "lively", "adventurous",
})

# Grounding: emotional processing, connection, warmth, reflection
GRND_MOOD_TAGS = frozenset({
    "reflective", "introspective", "nostalgic", "romantic", "emotional",
    "bittersweet", "hopeful", "heartfelt", "sentimental", "thoughtful",
    "contemplative", "warm", "passionate", "moody",
    "spiritual", "meditative", "devotional",
})

# Genre tags that indicate Indian music (BPM from LLM, not Essentia)
INDIAN_GENRE_TAGS = frozenset({
    "bollywood", "hindi", "punjabi", "indian", "desi", "bhangra",
    "sufi", "ghazal", "qawwali", "devotional", "filmi", "indi-pop",
    "indian pop", "indian classical", "hindustani", "carnatic",
    "rajasthani", "tamil", "telugu", "bengali", "marathi", "gujarati",
    "kannada", "malayalam",
})


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


def get_openai_api_key() -> str:
    val = os.getenv("OPENAI_API_KEY")
    if not val:
        raise RuntimeError("OPENAI_API_KEY not set in environment / .env")
    return val


def get_anthropic_api_key() -> str:
    val = os.getenv("ANTHROPIC_API_KEY")
    if not val:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment / .env")
    return val
