"""Spotify API data extraction — liked songs, top tracks, metadata."""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def get_liked_songs(sp: Any) -> list[dict[str, Any]]:
    """Fetch all liked (saved) songs from Spotify. Handles pagination."""
    tracks: list[dict[str, Any]] = []
    results = sp.current_user_saved_tracks(limit=50)
    while results:
        for item in results["items"]:
            parsed = parse_track(item["track"])
            if parsed:
                tracks.append(parsed)
        results = sp.next(results) if results.get("next") else None
    logger.info("Fetched %d liked songs", len(tracks))
    return tracks


def get_top_tracks(sp: Any, time_range: str = "medium_term") -> list[dict[str, Any]]:
    """Fetch top tracks for a given time range.

    time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (years).
    """
    tracks: list[dict[str, Any]] = []
    results = sp.current_user_top_tracks(limit=50, time_range=time_range)
    while results:
        for item in results["items"]:
            parsed = parse_track(item)
            if parsed:
                tracks.append(parsed)
        results = sp.next(results) if results.get("next") else None
    logger.info("Fetched %d top tracks (%s)", len(tracks), time_range)
    return tracks


def get_tracks_metadata(sp: Any, track_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch track metadata (including duration_ms) for a list of track IDs.

    Uses batch endpoint (up to 50 per call). Falls back to one-at-a-time
    if batch returns 403 (seen on very new Spotify apps).
    """
    if not track_ids:
        return []

    parsed = []
    # Try batch first (50x fewer API calls)
    try:
        batch = track_ids[:50]
        result = sp.tracks(batch)
        # Batch works — use it for everything
        for track in (result.get("tracks") or []):
            if track:
                p = parse_track(track)
                if p:
                    parsed.append(p)
        # Process remaining batches
        for i in range(50, len(track_ids), 50):
            batch = track_ids[i : i + 50]
            result = sp.tracks(batch)
            for track in (result.get("tracks") or []):
                if track:
                    p = parse_track(track)
                    if p:
                        parsed.append(p)
        return parsed
    except Exception as e:
        if "403" in str(e):
            logger.warning("Batch endpoint returned 403, falling back to single-track fetch")
        else:
            logger.warning("Batch fetch failed (%s), falling back to single-track fetch", e)

    # Fallback: one at a time with 3-second delay to avoid rate limits.
    # The batch endpoint returns 403 on Spotify apps in development mode.
    # Without throttling, rapid-fire individual calls trigger 429 lockout.
    parsed = []
    for i, track_id in enumerate(track_ids):
        try:
            track = sp.track(track_id)
            if track:
                p = parse_track(track)
                if p:
                    parsed.append(p)
        except Exception:
            logger.warning("Failed to fetch metadata for track %s", track_id)
        if i < len(track_ids) - 1:
            time.sleep(3)
        if (i + 1) % 50 == 0:
            logger.info("Metadata fallback: %d/%d tracks fetched", i + 1, len(track_ids))
    return parsed


def parse_track(track: dict[str, Any]) -> dict[str, Any] | None:
    """Extract {uri, name, artist, album, duration_ms} from a Spotify track object."""
    if not track or not track.get("uri"):
        return None
    artists = track.get("artists", [])
    artist_name = artists[0]["name"] if artists else "Unknown"
    album = track.get("album") or {}
    release_date = album.get("release_date", "")
    try:
        raw_year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None
    except ValueError:
        raw_year = None
    release_year = raw_year if raw_year and raw_year > 1900 else None
    return {
        "uri": track["uri"],
        "name": track.get("name", "Unknown"),
        "artist": artist_name,
        "album": album.get("name") if album else None,
        "duration_ms": track.get("duration_ms"),
        "release_year": release_year,
    }
