"""Spotify API data extraction — liked songs, top tracks, metadata."""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

SPOTIFY_TRACK_THROTTLE_SECONDS = 3
SPOTIFY_PAGINATION_THROTTLE_SECONDS = 1


def get_liked_songs(sp: Any) -> list[dict[str, Any]]:
    """Fetch all liked (saved) songs from Spotify. Handles pagination."""
    tracks: list[dict[str, Any]] = []
    results = sp.current_user_saved_tracks(limit=50)
    while results:
        for item in results["items"]:
            parsed = parse_track(item["track"])
            if parsed:
                tracks.append(parsed)
        if results.get("next"):
            time.sleep(SPOTIFY_PAGINATION_THROTTLE_SECONDS)
            results = sp.next(results)
        else:
            results = None
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
        if results.get("next"):
            time.sleep(SPOTIFY_PAGINATION_THROTTLE_SECONDS)
            results = sp.next(results)
        else:
            results = None
    logger.info("Fetched %d top tracks (%s)", len(tracks), time_range)
    return tracks


def get_tracks_metadata(sp: Any, track_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch track metadata (including duration_ms) for a list of track IDs.

    Uses individual sp.track() calls with throttling. The batch /v1/tracks
    endpoint returns 403 on Spotify apps in dev mode.
    """
    if not track_ids:
        return []

    from config import SPOTIFY_PROGRESS_LOG_INTERVAL

    logger.info(
        "Fetching metadata for %d tracks (~%d minutes)",
        len(track_ids),
        len(track_ids) * SPOTIFY_TRACK_THROTTLE_SECONDS // 60 + 1,
    )

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
            time.sleep(SPOTIFY_TRACK_THROTTLE_SECONDS)
        if (i + 1) % SPOTIFY_PROGRESS_LOG_INTERVAL == 0:
            logger.info("Metadata: %d/%d tracks fetched", i + 1, len(track_ids))
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
