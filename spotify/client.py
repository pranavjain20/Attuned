"""Spotify API data extraction — liked songs, top tracks, metadata."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_liked_songs(sp: Any) -> list[dict[str, Any]]:
    """Fetch all liked (saved) songs from Spotify. Handles pagination."""
    tracks: list[dict[str, Any]] = []
    results = sp.current_user_saved_tracks(limit=50)
    while results:
        for item in results["items"]:
            parsed = _parse_track(item["track"])
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
            parsed = _parse_track(item)
            if parsed:
                tracks.append(parsed)
        results = sp.next(results) if results.get("next") else None
    logger.info("Fetched %d top tracks (%s)", len(tracks), time_range)
    return tracks


def get_tracks_metadata(sp: Any, track_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch track metadata (including duration_ms) for a batch of track IDs.

    track_ids should be Spotify track IDs (not full URIs). Max 50 per call.
    """
    if not track_ids:
        return []
    results = sp.tracks(track_ids)
    parsed = []
    for track in results.get("tracks", []):
        if track:
            p = _parse_track(track)
            if p:
                parsed.append(p)
    return parsed


def _parse_track(track: dict[str, Any]) -> dict[str, Any] | None:
    """Extract {uri, name, artist, album, duration_ms} from a Spotify track object."""
    if not track or not track.get("uri"):
        return None
    artists = track.get("artists", [])
    artist_name = artists[0]["name"] if artists else "Unknown"
    album = track.get("album", {})
    return {
        "uri": track["uri"],
        "name": track.get("name", "Unknown"),
        "artist": artist_name,
        "album": album.get("name") if album else None,
        "duration_ms": track.get("duration_ms"),
    }
