"""End-to-end playlist generation: WHOOP state → song matching → Spotify playlist."""

import logging
import sqlite3
import time
from datetime import date, datetime, timedelta as _timedelta

import spotipy

from db.queries import insert_generated_playlist
from intelligence.continuous_profile import NAME_DEEP_SHARE, STATE_PURPOSE, is_top_energy_day, pick_state
from intelligence.dj_context import attuned_context
from intelligence.state_classifier import classify_state
from matching.query_engine import select_songs
from spotify.playlist import (
    SPOTIFY_DESCRIPTION_MAX_LENGTH,
    SpotifyPlaylistError,
    create_playlist,
)

logger = logging.getLogger(__name__)


def _filter_unavailable_tracks(
    sp: spotipy.Spotify,
    songs: list[dict],
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Remove songs that are no longer playable on Spotify.

    Checks each track individually via sp.track() with throttling (batch
    endpoint returns 403 in dev mode). Drops tracks where is_playable is False.
    On per-track errors, treats the track as available (graceful degradation).

    Persists results to the DB so future runs skip known-unavailable songs
    at query time. Songs checked within AVAILABILITY_CACHE_DAYS skip the API call.
    """
    from config import AVAILABILITY_CACHE_DAYS
    from db.queries import update_song_availability_batch
    from spotify.client import SPOTIFY_TRACK_THROTTLE_SECONDS

    if not songs:
        return songs

    # Determine which songs need a fresh check vs cached
    now = datetime.now().astimezone()
    cache_cutoff = now - _timedelta(days=AVAILABILITY_CACHE_DAYS)
    needs_check: list[dict] = []
    cached_available: list[dict] = []

    for song in songs:
        checked_at = song.get("availability_checked_at")
        is_avail = song.get("is_available")
        if checked_at and is_avail == 1:
            try:
                checked_dt = datetime.fromisoformat(checked_at)
                if checked_dt > cache_cutoff:
                    cached_available.append(song)
                    continue
            except (ValueError, TypeError):
                pass
        needs_check.append(song)

    if cached_available:
        logger.info(
            "Availability cache: %d song(s) verified within %d days, skipping API check",
            len(cached_available), AVAILABILITY_CACHE_DAYS,
        )

    unavailable_uris: set[str] = set()
    availability_results: list[tuple[str, bool]] = []

    for i, song in enumerate(needs_check):
        uri = song["spotify_uri"]
        track_id = uri.split(":")[-1]
        try:
            track = sp.track(track_id)
            playable = track.get("is_playable", True) if track else True
            availability_results.append((uri, playable))
            if not playable:
                unavailable_uris.add(uri)
                logger.info(
                    "Dropping unavailable track: '%s' — %s (uri=%s)",
                    track.get("name", "?"),
                    track.get("artists", [{}])[0].get("name", "?"),
                    uri,
                )
        except Exception:
            logger.warning("Failed to check availability for %s — treating as available", uri)
        if i < len(needs_check) - 1:
            time.sleep(SPOTIFY_TRACK_THROTTLE_SECONDS)

    # Persist availability results to DB
    if conn is not None and availability_results:
        update_song_availability_batch(conn, availability_results)

    if unavailable_uris:
        logger.info("Filtered %d unavailable track(s)", len(unavailable_uris))

    return [s for s in songs if s["spotify_uri"] not in unavailable_uris]


class GenerationError(Exception):
    """Raised when playlist generation fails at any pipeline stage."""


# ---------------------------------------------------------------------------
# Pure formatting functions
# ---------------------------------------------------------------------------

def format_playlist_name(
    date_str: str,
    neuro_profile: dict[str, float],
    position: float | None = None,
) -> str:
    """Dynamic playlist name: "Mar 19 — Rest & Repair".

    Names reflect what the music is doing for you, not clinical state names.
    position is the Attuned score's position (see _pick_name_label).
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month_day = dt.strftime("%b %-d")

    label = _pick_name_label(neuro_profile, position)
    return f"{month_day} — {label}"


def _pick_name_label(
    neuro_profile: dict[str, float],
    position: float | None = None,
) -> str:
    """Pick a human-readable label from the day's state and the Attuned score's position.

    The state is the profile's lead (as on the page and for the songs). position is
    where the Attuned score sits among your own earlier days (0 = your lowest, 1 =
    your best; None when the day has no score), so each state's name gets stronger
    the further the day is from your usual. WHOOP recovery plays no part.
    """
    state, _label = pick_state(neuro_profile)

    if state == "rest":
        if position is not None and position < NAME_DEEP_SHARE:
            return "Rest & Repair"
        return "Settle In"

    if state == "energy":
        if is_top_energy_day(state, position):
            return "Stay Sharp"
        return "Fuel Up"

    # grounding: a usual day, leaning toward a gentle lift when at or above your middle
    if position is not None and position >= 0.5:
        return "Ease Into It"
    return "Ground Yourself"


def _get_neuro_purpose(neuro_profile: dict[str, float]) -> str:
    """Human-readable phrase for what the music is doing."""
    state, _label = pick_state(neuro_profile)
    return f"Built to {STATE_PURPOSE[state]}"


def _get_dominant_moods(songs: list[dict], top_n: int = 3) -> list[str]:
    """Extract the most common mood tags from selected songs."""
    mood_counts: dict[str, int] = {}
    for song in songs:
        for tag in (song.get("mood_tags") or []):
            t = tag.lower().strip()
            if t:
                mood_counts[t] = mood_counts.get(t, 0) + 1
    if not mood_counts:
        return []
    sorted_moods = sorted(mood_counts, key=mood_counts.get, reverse=True)
    return sorted_moods[:top_n]


def generate_description(
    neuro_profile: dict[str, float],
    songs: list[dict],
    cohesion_stats: dict,
) -> str:
    """Generate a <=300 char playlist description.

    Format: what the music does · genre · mood tags.
    """
    parts = [_get_neuro_purpose(neuro_profile)]

    genre = cohesion_stats.get("dominant_genre")
    if genre:
        parts.append(genre.title())

    moods = _get_dominant_moods(songs)
    if moods:
        parts.append(", ".join(m.title() for m in moods))

    desc = " · ".join(parts)
    if len(desc) > SPOTIFY_DESCRIPTION_MAX_LENGTH:
        desc = desc[:SPOTIFY_DESCRIPTION_MAX_LENGTH - 1] + "\u2026"
    return desc


def format_reasoning(
    classification_result: dict,
    match_result: dict,
) -> str:
    """Format full reasoning for DB storage (no size limit).

    The Attuned state and score position that picked the songs, WHOOP's raw
    metrics for the record, then match stats.
    """
    lines = []

    lines.append(f"State: {match_result['state']}")
    position = match_result.get("position")
    lines.append(f"Attuned position: {'none (no score)' if position is None else f'{position:.2f}'}")

    metrics = classification_result.get("metrics", {})
    if metrics:
        lines.append("")
        lines.append("Metrics:")
        for key, val in metrics.items():
            if val is not None:
                lines.append(f"  {key}: {val}")

    stats = match_result.get("match_stats", {})
    if stats:
        lines.append("")
        lines.append("Match stats:")
        lines.append(f"  Candidates: {stats.get('total_candidates', 0)}")
        lines.append(f"  Selected: {stats.get('selected', 0)}")
        cohesion = stats.get("cohesion_stats", {})
        if cohesion:
            lines.append(f"  Cohesion pool: {cohesion.get('pool_size', 0)}")
            lines.append(f"  Mean similarity: {cohesion.get('mean_similarity', 0):.4f}")
            lines.append(f"  Dominant genre: {cohesion.get('dominant_genre', 'N/A')}")
            if cohesion.get("relaxations", 0) > 0:
                lines.append(f"  Relaxations: {cohesion['relaxations']}")

    profile = match_result.get("neuro_profile", {})
    if profile:
        lines.append("")
        lines.append("Neuro profile:")
        lines.append(f"  Para: {profile.get('para', 0):.2f}  "
                     f"Symp: {profile.get('symp', 0):.2f}  "
                     f"Grnd: {profile.get('grnd', 0):.2f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def select_day_songs(
    conn: sqlite3.Connection,
    date_str: str,
    point_in_time: bool = False,
    prior_playlists: dict[str, list[str]] | None = None,
    history: dict[str, dict] | None = None,
) -> tuple[dict, dict]:
    """Match songs to the day's Attuned state — no Spotify, no DB writes.

    Over-selects by AVAILABILITY_BUFFER_SIZE so callers can drop unavailable
    tracks and still fill MAX_PLAYLIST_SIZE. point_in_time replays a past day
    using only the library as it stood that morning; prior_playlists counts
    earlier replayed days for rotation (see select_songs). history (from
    feeling_score.compute_composite_history) saves rescoring every earlier day
    (~3 s) when building many days; the result is the same without it.

    Returns (classification, match_result). classification is the old WHOOP
    classifier's output, kept only for its raw metrics; it plays no part in the
    songs. match_result["state"] and ["position"] are the Attuned state and
    score position (0-1, None when the day has no score).
    Raises GenerationError on insufficient WHOOP data or no matching songs.
    """
    # 1. Data check: "insufficient_data" means fewer than 14 days of HRV (no baseline yet)
    classification = classify_state(conn, date_str)
    if classification["state"] == "insufficient_data":
        raise GenerationError(
            "Cannot generate playlist — insufficient WHOOP data (need 14+ days of HRV)"
        )

    # 1b. Playlist target, set by the Attuned score's position
    from intelligence.continuous_profile import compute_continuous_profile
    continuous = compute_continuous_profile(conn, date_str, history)
    state = continuous["state"]

    z_summary = {k: round(v, 2) for k, v in continuous["z_scores"].items() if v is not None}
    logger.info(
        "Continuous profile: %d signals, z-scores: %s",
        continuous["signals_used"], z_summary,
    )

    # 2. Match songs (over-select by buffer to absorb unavailable drops)
    from config import AVAILABILITY_BUFFER_SIZE, MAX_PLAYLIST_SIZE
    buffer_size = MAX_PLAYLIST_SIZE + AVAILABILITY_BUFFER_SIZE
    match_result = select_songs(
        conn, state, date_str,
        neuro_profile=continuous["profile"],
        target_valence=continuous["target_valence"],
        position=continuous["position"],
        target_size=buffer_size,
        point_in_time=point_in_time,
        prior_playlists=prior_playlists,
    )

    if not match_result["songs"]:
        raise GenerationError(
            f"No songs matched for state '{state}'. "
            "Is the library classified? Run: python main.py classify-songs"
        )
    match_result["state"] = state
    match_result["position"] = continuous["position"]
    return classification, match_result


def generate_playlist(
    conn: sqlite3.Connection,
    sp: spotipy.Spotify | None,
    date_str: str | None = None,
    dry_run: bool = False,
    public: bool = False,
) -> dict:
    """End-to-end playlist generation pipeline.

    1. Attuned state + target from the day's score position
    2. Match songs to the target
    3. Create Spotify playlist (unless dry_run)
    4. Log to DB

    Args:
        conn: Database connection.
        sp: Authenticated Spotipy client (None allowed only if dry_run).
        date_str: Date to generate for (YYYY-MM-DD). Defaults to today.
        dry_run: Preview without creating Spotify playlist.
        public: Create the Spotify playlist as public (needs the
            playlist-modify-public scope). Default private.

    Returns:
        Dict with: name, state, description, reasoning, songs, match_stats,
                   neuro_profile, playlist_id, playlist_url, dry_run.

    Raises:
        GenerationError: On insufficient data, no songs, or Spotify failure.
    """
    from config import MAX_PLAYLIST_SIZE

    if date_str is None:
        date_str = date.today().isoformat()

    # 1-2. Attuned state and target, match songs
    classification, match_result = select_day_songs(conn, date_str)
    state = match_result["state"]
    songs = match_result["songs"]

    # 2b. Filter unavailable tracks (Spotify may have removed them), then trim to target
    if sp is not None:
        songs = _filter_unavailable_tracks(sp, songs, conn=conn)
        if not songs:
            raise GenerationError(
                f"All matched songs for state '{state}' are unavailable on Spotify"
            )
    songs = songs[:MAX_PLAYLIST_SIZE]

    # 3. Format outputs
    neuro_profile = match_result["neuro_profile"]
    cohesion_stats = match_result["match_stats"].get("cohesion_stats", {})

    name = format_playlist_name(date_str, neuro_profile, match_result["position"])
    description = generate_description(neuro_profile, songs, cohesion_stats)
    reasoning = format_reasoning(classification, match_result)
    track_uris = [s["spotify_uri"] for s in songs]

    # 4. Create Spotify playlist (unless dry_run)
    playlist_id = None
    playlist_url = None

    if not dry_run:
        if sp is None:
            raise GenerationError("Spotify client required for live playlist creation")
        try:
            result = create_playlist(sp, name, description, track_uris, public=public)
            playlist_id = result["playlist_id"]
            playlist_url = result["playlist_url"]
        except SpotifyPlaylistError as e:
            # Log the attempt before re-raising
            insert_generated_playlist(
                conn,
                date=date_str,
                detected_state=state,
                track_uris=track_uris,
                reasoning=f"FAILED: {e}\n\n{reasoning}",
                whoop_metrics=classification.get("metrics"),
                description=description,
                spotify_playlist_id=None,
            )
            raise GenerationError(f"Spotify API failed: {e}") from e

    # 5. Log to DB
    insert_generated_playlist(
        conn,
        date=date_str,
        detected_state=state,
        track_uris=track_uris,
        reasoning=reasoning,
        whoop_metrics=classification.get("metrics"),
        description=description,
        spotify_playlist_id=playlist_id,
    )

    logger.info(
        "Generated playlist '%s': %d tracks, state=%s, dry_run=%s",
        name, len(songs), state, dry_run,
    )

    return {
        "name": name,
        "state": state,
        "description": description,
        "reasoning": reasoning,
        "songs": songs,
        "match_stats": match_result["match_stats"],
        "neuro_profile": match_result["neuro_profile"],
        "playlist_id": playlist_id,
        "playlist_url": playlist_url,
        "dry_run": dry_run,
    }


def generate_nl_playlist(
    conn: sqlite3.Connection,
    sp: spotipy.Spotify | None,
    query: str,
    date_str: str | None = None,
    dry_run: bool = False,
    nl_result: dict | None = None,
) -> dict:
    """Generate a playlist from a natural language request.

    The LLM sees the full song library and picks songs directly by meaning.
    No neuro profile middleman — "dark seductive Weeknd" goes straight to
    Earned It, not through cosine similarity.

    The day's Attuned score (dj_context.attuned_context) calibrates the DJ;
    the request still drives the picks.

    Args:
        conn: Database connection.
        sp: Authenticated Spotipy client (None allowed only if dry_run).
        query: Natural language request (e.g. "walking to campus, want energy").
        date_str: Date string (YYYY-MM-DD). Defaults to today.
        dry_run: Preview without creating Spotify playlist.
        nl_result: Pre-selected NL result (skips LLM if provided — used by
                   WhatsApp handler after clarification).

    Returns:
        Dict with: name, description, songs, playlist_id, playlist_url,
                   dry_run, dj_message, nl_query.
    """
    from config import MAX_PLAYLIST_SIZE
    from db.queries import get_all_classified_songs
    from intelligence.nl_song_selector import select_songs_nl

    if date_str is None:
        date_str = date.today().isoformat()

    # 1. LLM picks songs directly, told the day's Attuned body context (unless pre-selected)
    if nl_result is None:
        all_songs = get_all_classified_songs(conn)
        if not all_songs:
            raise GenerationError(
                "No classified songs in database. "
                "Run: python main.py classify-songs"
            )
        nl_result = select_songs_nl(query, all_songs, attuned_context(conn, date_str))

    # If clarification needed, return it (caller handles the interaction)
    if nl_result.get("needs_clarification"):
        return {
            "needs_clarification": True,
            "clarifying_question": nl_result["clarifying_question"],
        }

    songs = nl_result["songs"]
    dj_message = nl_result.get("dj_message", "Here's your playlist.")
    playlist_name = nl_result.get("playlist_name", "On Demand")

    if not songs:
        raise GenerationError(
            f"No songs selected for request '{query}'."
        )

    # 2. Filter unavailable tracks
    if sp is not None:
        songs = _filter_unavailable_tracks(sp, songs, conn=conn)
        if not songs:
            raise GenerationError("All selected songs are unavailable on Spotify")
    songs = songs[:MAX_PLAYLIST_SIZE]

    # 3. Format outputs
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    name = f"{dt.strftime('%b %-d')} — {playlist_name}"
    track_uris = [s["spotify_uri"] for s in songs]

    # Simple description from the songs
    artists = list(dict.fromkeys(s.get("artist", "?") for s in songs[:5]))
    description = f"{dj_message[:200]} · {', '.join(artists[:3])}"
    if len(description) > 300:
        description = description[:297] + "..."

    # What the DJ was asked, and the body context it was given
    reasoning = f"NL request: \"{query}\""
    if nl_result.get("body_context"):
        reasoning += f"\n{nl_result['body_context']}"

    # 4. Create Spotify playlist
    playlist_id = None
    playlist_url = None

    if not dry_run:
        if sp is None:
            raise GenerationError("Spotify client required for live playlist creation")
        result = create_playlist(sp, name, description, track_uris)
        playlist_id = result["playlist_id"]
        playlist_url = result["playlist_url"]

    # 5. Log to DB
    insert_generated_playlist(
        conn,
        date=date_str,
        detected_state="nl_request",
        track_uris=track_uris,
        reasoning=reasoning,
        whoop_metrics={"nl_query": query},
        description=description,
        spotify_playlist_id=playlist_id,
    )

    logger.info(
        "Generated NL playlist '%s': %d tracks, query='%s', dry_run=%s",
        name, len(songs), query[:50], dry_run,
    )

    return {
        "name": name,
        "description": description,
        "reasoning": reasoning,
        "songs": songs,
        "playlist_id": playlist_id,
        "playlist_url": playlist_url,
        "dry_run": dry_run,
        "nl_query": query,
        "dj_message": dj_message,
    }
