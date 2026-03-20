"""End-to-end playlist generation: WHOOP state → song matching → Spotify playlist."""

import logging
import sqlite3
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


class GenerationError(Exception):
    """Raised when playlist generation fails at any pipeline stage."""


# ---------------------------------------------------------------------------
# Pure formatting functions
# ---------------------------------------------------------------------------

def format_playlist_name(date_str: str, state: str) -> str:
    """Format playlist name: 'Mar 19 — Accumulated Fatigue'."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month_day = dt.strftime("%b %-d")
    state_title = state.replace("_", " ").title()
    return f"{month_day} — {state_title}"


def generate_description(
    state: str,
    metrics: dict,
    neuro_profile: dict[str, float],
    match_stats: dict,
) -> str:
    """Generate a <=300 char playlist description.

    Template-based: state + recovery% + HRV context + neuro emphasis.
    Gracefully omits missing metrics.
    """
    state_label = state.replace("_", " ").title()
    parts = [state_label]

    recovery = metrics.get("recovery_score")
    if recovery is not None:
        parts.append(f"Recovery {recovery:.0f}%")

    hrv = metrics.get("hrv_rmssd_milli")
    if hrv is not None:
        parts.append(f"HRV {hrv:.0f}ms")

    # Neuro emphasis: which dimension dominates
    top_dim = max(neuro_profile, key=neuro_profile.get)
    dim_labels = {"para": "parasympathetic", "symp": "sympathetic", "grnd": "grounding"}
    parts.append(f"Tuned for {dim_labels.get(top_dim, top_dim)}")

    parts.append(f"{match_stats['selected']} tracks")

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

    # 2. Match songs
    match_result = select_songs(conn, state, date_str)
    songs = match_result["songs"]

    if not songs:
        raise GenerationError(
            f"No songs matched for state '{state}'. "
            "Is the library classified? Run: python main.py classify-songs"
        )

    # 3. Format outputs
    name = format_playlist_name(date_str, state)
    description = generate_description(
        state,
        classification.get("metrics", {}),
        match_result["neuro_profile"],
        match_result["match_stats"],
    )
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
