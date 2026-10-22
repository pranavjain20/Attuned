"""Reading one song's values back out of a stored LLM batch response.

Each song_classifications.raw_response holds the whole batch (~5 songs) the
LLM answered in one call, so a song's own values are found by title + artist.
"""

import json
from typing import Any


def find_llm_song_result(
    raw_response: str | None,
    name: str | None,
    artist: str | None,
) -> dict[str, Any] | None:
    """Return this song's entry from a raw LLM batch response, or None.

    Matches title and artist exactly (case and surrounding spaces ignored).
    Returns None for a missing or malformed response, or when no entry matches.
    """
    if not raw_response:
        return None
    try:
        results = json.loads(raw_response).get("songs", [])
    except (json.JSONDecodeError, AttributeError):
        return None

    song_name = (name or "").lower().strip()
    song_artist = (artist or "").lower().strip()
    for result in results:
        if not isinstance(result, dict):
            continue
        r_title = str(result.get("title", "")).lower().strip()
        r_artist = str(result.get("artist", "")).lower().strip()
        if r_title == song_name and r_artist == song_artist:
            return result
    return None
