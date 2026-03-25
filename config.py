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

# Restorative sleep gate — if last night was genuinely restorative, skip accumulated_fatigue
# Research: last night's sleep is the strongest predictor of next-morning subjective state (PMC6456824)
RESTORATIVE_SLEEP_EFFICIENCY_MIN = 85.0    # Sleep efficiency % floor
RESTORATIVE_SLEEP_TOTAL_MIN_MS = 6 * 3_600_000  # 6h minimum total sleep

# Recovery delta modifier — adjusts neuro profile when day-over-day recovery change is extreme
RECOVERY_DELTA_THRESHOLD_SD = 1.5   # z-score must exceed this (not equal) to trigger (non-baseline states)
RECOVERY_DELTA_NUDGE = 0.10         # Fixed weight added to target dimension (non-baseline states)
RECOVERY_DELTA_EXEMPT_STATES = frozenset({"accumulated_fatigue", "peak_readiness"})

# Continuous baseline scaling — baseline uses recovery delta direction to pick a point on the spectrum
# z = -2 → calm/devotional, z = 0 → current baseline, z = +2 → high energy
BASELINE_CALM_ANCHOR = {"para": 0.45, "symp": 0.15, "grnd": 0.40}
BASELINE_ENERGY_ANCHOR = {"para": 0.05, "symp": 0.75, "grnd": 0.20}
BASELINE_Z_CLAMP = 2.0
BASELINE_SLEEP_WEIGHT = 0.65  # Sleep architecture vs recovery delta weight for baseline scaling
# Research basis: sleep-subjective correlation r=0.4-0.6 (Vitale 2015, PMC6456824)
# vs HRV-subjective correlation r=0.2-0.3 (Hynynen 2011). Roughly 2:1 ratio.
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

# Recent anchors — guarantee recently-played songs in every playlist
ANCHOR_RECENCY_DAYS = 90       # "recently played" = last_played within this many days
ANCHOR_MAX_COUNT = 5           # max guaranteed anchor slots
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

# When era similarity drops below this floor, cap total pairwise similarity.
# A 1999 song matching perfectly on mood/BPM/genre shouldn't survive in a 2010s cluster.
# Research: production era changes are "more jarring than cultural differences."
ERA_SIM_FLOOR = 0.05          # Below this = effectively different eras
ERA_HARD_CAP_SIMILARITY = 0.30  # Max total similarity when era_sim < floor

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
# Mood tag affinity (used in profiler)
# ---------------------------------------------------------------------------
# Weight given to mood tags in the profiler (existing audio weights scale to 1 - this)
MOOD_TAG_WEIGHT = 0.15

# Mood tag affinity table — research-backed weights for each dimension.
# Each tag has (para, symp, grnd) weights from 0.0-1.0.
# Based on Russell's circumplex, Bernardi 2006, Chanda & Levitin 2013,
# Saarikallio 2007, Taruffi et al. 2017, Bretherton 2019.
MOOD_AFFINITY: dict[str, tuple[float, float, float]] = {
    # (para, symp, grnd)
    # --- High sympathetic ---
    "energetic":      (0.00, 0.95, 0.05),
    "intense":        (0.00, 0.90, 0.15),
    "aggressive":     (0.00, 0.95, 0.10),
    "powerful":       (0.05, 0.85, 0.20),
    "upbeat":         (0.00, 0.85, 0.10),
    "party":          (0.00, 0.85, 0.15),
    "danceable":      (0.00, 0.80, 0.10),
    "dynamic":        (0.00, 0.80, 0.10),
    "confident":      (0.00, 0.80, 0.25),
    "rebellious":     (0.00, 0.80, 0.25),
    "vibrant":        (0.00, 0.80, 0.15),
    "lively":         (0.00, 0.80, 0.15),
    "triumphant":     (0.05, 0.80, 0.30),
    "uplifting":      (0.05, 0.75, 0.30),
    "fun":            (0.00, 0.75, 0.20),
    "empowering":     (0.00, 0.75, 0.30),
    "celebratory":    (0.00, 0.70, 0.35),
    "joyful":         (0.05, 0.70, 0.30),
    "festive":        (0.00, 0.70, 0.30),
    "adventurous":    (0.00, 0.70, 0.30),
    "edgy":           (0.00, 0.70, 0.20),
    "cheerful":       (0.05, 0.70, 0.20),
    "groovy":         (0.05, 0.65, 0.25),
    "playful":        (0.05, 0.65, 0.25),
    "motivational":   (0.00, 0.65, 0.25),
    "inspirational":  (0.05, 0.60, 0.40),
    "inspiring":      (0.05, 0.60, 0.40),
    "dramatic":       (0.10, 0.65, 0.45),
    "passionate":     (0.05, 0.55, 0.60),
    # --- High parasympathetic ---
    "calm":           (0.90, 0.00, 0.15),
    "soothing":       (0.90, 0.00, 0.10),
    "peaceful":       (0.90, 0.00, 0.20),
    "serene":         (0.85, 0.00, 0.15),
    "relaxed":        (0.85, 0.00, 0.10),
    "meditative":     (0.80, 0.00, 0.40),
    "dreamy":         (0.75, 0.00, 0.30),
    "chill":          (0.75, 0.00, 0.15),
    "gentle":         (0.70, 0.00, 0.30),
    "ethereal":       (0.70, 0.00, 0.35),
    "melancholy":     (0.70, 0.00, 0.50),
    "melancholic":    (0.70, 0.00, 0.50),
    "laid-back":      (0.70, 0.05, 0.20),
    "spiritual":      (0.65, 0.00, 0.55),
    "devotional":     (0.70, 0.00, 0.55),
    "sad":            (0.60, 0.00, 0.55),
    "smooth":         (0.45, 0.15, 0.40),
    # --- High grounding ---
    "introspective":  (0.30, 0.05, 0.90),
    "reflective":     (0.30, 0.05, 0.85),
    "contemplative":  (0.35, 0.05, 0.85),
    "bittersweet":    (0.35, 0.05, 0.85),
    "nostalgic":      (0.25, 0.10, 0.85),
    "heartfelt":      (0.20, 0.15, 0.85),
    "romantic":       (0.15, 0.25, 0.80),
    "emotional":      (0.20, 0.20, 0.80),
    "sentimental":    (0.30, 0.05, 0.80),
    "thoughtful":     (0.25, 0.10, 0.80),
    "wistful":        (0.35, 0.05, 0.75),
    "tender":         (0.35, 0.05, 0.75),
    "warm":           (0.25, 0.15, 0.75),
    "hopeful":        (0.15, 0.35, 0.65),
    "moody":          (0.35, 0.15, 0.70),
    "haunting":       (0.45, 0.15, 0.60),
    "raw":            (0.05, 0.50, 0.65),
    "sultry":         (0.20, 0.40, 0.55),
    # --- Mixed ---
    "dark":           (0.30, 0.45, 0.40),
    "anthemic":       (0.00, 0.70, 0.35),
    "happy":          (0.05, 0.65, 0.25),
    # --- Structural ---
    "melodic":        (0.20, 0.10, 0.30),
    "catchy":         (0.05, 0.40, 0.15),
}

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
