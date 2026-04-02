"""End-to-end playlist generation: WHOOP state → song matching → Spotify playlist."""

import logging
import sqlite3
import time
from datetime import date, datetime

import spotipy

from db.queries import insert_generated_playlist
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
) -> list[dict]:
    """Remove songs that are no longer playable on Spotify.

    Checks each track individually via sp.track() with throttling (batch
    endpoint returns 403 in dev mode). Drops tracks where is_playable is False.
    On per-track errors, treats the track as available (graceful degradation).
    """
    from spotify.client import SPOTIFY_TRACK_THROTTLE_SECONDS

    if not songs:
        return songs

    unavailable_uris: set[str] = set()

    for i, song in enumerate(songs):
        uri = song["spotify_uri"]
        track_id = uri.split(":")[-1]
        try:
            track = sp.track(track_id)
            if track and not track.get("is_playable", True):
                unavailable_uris.add(uri)
                logger.info(
                    "Dropping unavailable track: '%s' — %s (uri=%s)",
                    track.get("name", "?"),
                    track.get("artists", [{}])[0].get("name", "?"),
                    uri,
                )
        except Exception:
            logger.warning("Failed to check availability for %s — treating as available", uri)
        if i < len(songs) - 1:
            time.sleep(SPOTIFY_TRACK_THROTTLE_SECONDS)

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
    recovery_score: float | None = None,
) -> str:
    """Dynamic playlist name based on neuro profile + recovery intensity.

    Names reflect what the music is doing for the body, not clinical state names.
    Recovery score adds intensity variation so no two days feel the same.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month_day = dt.strftime("%b %-d")

    label = _pick_name_label(neuro_profile, recovery_score)
    return f"{month_day} — {label}"


def _pick_name_label(
    neuro_profile: dict[str, float],
    recovery_score: float | None = None,
) -> str:
    """Pick a human-readable label from neuro profile + recovery."""
    para = neuro_profile.get("para", 0)
    symp = neuro_profile.get("symp", 0)
    grnd = neuro_profile.get("grnd", 0)
    recovery = recovery_score if recovery_score is not None else 50.0

    top_dim = max(neuro_profile, key=neuro_profile.get)

    if top_dim == "para":
        if para > 0.80:
            return "Slow Down"
        if recovery < 50:
            return "Rest & Repair"
        return "Settle In"

    if top_dim == "symp":
        if symp > 0.80:
            return "Full Send"
        if recovery > 70:
            return "Stay Sharp"
        return "Fuel Up"

    # grnd dominant
    if grnd > 0.80:
        return "Sit With It"
    if symp > 0.20:
        return "Ease Into It"  # mixed grnd+symp = gentle lift
    return "Ground Yourself"


def _get_neuro_purpose(neuro_profile: dict[str, float]) -> str:
    """Human-readable phrase for what the music is doing."""
    top_dim = max(neuro_profile, key=neuro_profile.get)
    purposes = {
        "para": "Calming your nervous system",
        "symp": "Matching your energy",
        "grnd": "Grounding your emotions",
    }
    return purposes.get(top_dim, "Tuned for you")


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

    Includes state classifier reasoning + match stats.
    """
    lines = []

    lines.append(f"State: {classification_result['state']}")
    lines.append(f"Confidence: {classification_result['confidence']}")

    if classification_result.get("reasoning"):
        lines.append("")
        lines.append("Classifier reasoning:")
        for r in classification_result["reasoning"]:
            lines.append(f"  - {r}")

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

def generate_playlist(
    conn: sqlite3.Connection,
    sp: spotipy.Spotify | None,
    date_str: str | None = None,
    dry_run: bool = False,
) -> dict:
    """End-to-end playlist generation pipeline.

    1. Classify physiological state
    2. Match songs to state
    3. Create Spotify playlist (unless dry_run)
    4. Log to DB

    Args:
        conn: Database connection.
        sp: Authenticated Spotipy client (None allowed only if dry_run).
        date_str: Date to generate for (YYYY-MM-DD). Defaults to today.
        dry_run: Preview without creating Spotify playlist.

    Returns:
        Dict with: name, state, description, reasoning, songs, match_stats,
                   neuro_profile, playlist_id, playlist_url, dry_run.

    Raises:
        GenerationError: On insufficient data, no songs, or Spotify failure.
    """
    if date_str is None:
        date_str = date.today().isoformat()

    # 1. Classify state
    classification = classify_state(conn, date_str)
    state = classification["state"]

    if state == "insufficient_data":
        raise GenerationError(
            "Cannot generate playlist — insufficient WHOOP data (need 14+ days of HRV)"
        )

    # 1b. Continuous profile — weighted function of all physiological signals
    from intelligence.continuous_profile import compute_continuous_profile
    continuous = compute_continuous_profile(conn, date_str)
    neuro_profile_override = continuous["profile"]
    target_valence = continuous.get("target_valence")

    z_summary = {k: round(v, 2) for k, v in continuous["z_scores"].items() if v is not None}
    logger.info(
        "Continuous profile: %d signals, z-scores: %s",
        continuous["signals_used"], z_summary,
    )
    if continuous["interactions"]:
        for interaction in continuous["interactions"]:
            logger.info("Interaction: %s", interaction)

    # 2. Match songs
    match_result = select_songs(conn, state, date_str, neuro_profile_override=neuro_profile_override, target_valence=target_valence)
    songs = match_result["songs"]

    if not songs:
        raise GenerationError(
            f"No songs matched for state '{state}'. "
            "Is the library classified? Run: python main.py classify-songs"
        )

    # 2b. Filter unavailable tracks (Spotify may have removed them)
    if sp is not None:
        songs = _filter_unavailable_tracks(sp, songs)
        if not songs:
            raise GenerationError(
                f"All matched songs for state '{state}' are unavailable on Spotify"
            )

    # 3. Format outputs
    metrics = classification.get("metrics", {})
    neuro_profile = match_result["neuro_profile"]
    cohesion_stats = match_result["match_stats"].get("cohesion_stats", {})

    name = format_playlist_name(date_str, neuro_profile, metrics.get("recovery_score"))
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
            result = create_playlist(sp, name, description, track_uris)
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
