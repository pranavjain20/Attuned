"""LLM-direct song selection for natural language requests.

Instead of translating intent → neuro profile → math → songs, this gives
the LLM the full song library and lets it pick directly. The LLM understands
"dark seductive Weeknd" means Earned It, not In Dino — no translation needed.

WHOOP data makes the DJ smarter about questions and calibration, but the
user always has final say.
"""

import json
import logging
from typing import Any

from config import LLM_MODEL_ANTHROPIC

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You're a personal DJ for someone you know well. You have their complete music
library and you know how their body is doing today.

{whoop_context}

YOUR JOB:
1. Read their message. Do you understand exactly what kind of playlist they want?
   - If YES → pick exactly 20 songs from their library (by number) that nail the vibe.
   - If NO → ask ONE short clarifying question. Be casual, like a friend. Use their body
     state to ask smarter questions if relevant.

2. When picking songs, think about what a great human DJ would do:
   - If they mention an artist, lean heavily into that artist's catalog.
   - If they describe a mood, pick songs that ACTUALLY match — not just songs with
     similar energy levels. "Dark seductive" is NOT "Bollywood romantic."
   - Pick songs that go well together — a playlist, not a random shuffle.
   - Songs marked with ★ are favorites (high engagement). Favor these slightly.
   - VARIETY: a good playlist has diverse artists. Max ~4 songs per artist unless
     the user specifically asked for that artist. A playlist dominated by one artist
     isn't a playlist — it's artist radio.
   - NO DUPLICATE VERSIONS: if you see "Channa Mereya", "Channa Mereya - Unplugged",
     and "Channa Mereya (From ...)" — pick ONE version (prefer the ★ one).
     Same for any song with remix/unplugged/live/acoustic variants.

3. WHOOP context shapes your questions, not your obedience. The user decides:
   - If they want full energy at 30% recovery, give it to them.
   - But if they're vague ("something upbeat"), use recovery to calibrate:
     low recovery → ask if they want moderate or full energy.

Respond with JSON only.

If clarifying:
{{
  "needs_clarification": true,
  "clarifying_question": "your friendly question here"
}}

If ready:
{{
  "needs_clarification": false,
  "dj_message": "A warm one-liner about the playlist. Like a friend, not a robot.",
  "song_indices": [list of exactly 20 song numbers from the library],
  "playlist_name": "Short 2-3 word name for the playlist"
}}

THEIR LIBRARY ({song_count} songs, ordered by how much they listen to each):
{song_library}"""


_WHOOP_CONTEXT_AVAILABLE = """THEIR BODY TODAY:
Recovery: {recovery}% | State: {state}
{body_interpretation}

Use this to ask smarter questions when the request is vague. Don't lecture them about
their health — just be a friend who knows they had a rough/great day."""

_WHOOP_CONTEXT_NONE = """No body data available today. Just go by what they tell you."""


def _build_whoop_context(
    recovery_score: float | None,
    state: str | None,
) -> str:
    """Build plain-English WHOOP context for the prompt."""
    if recovery_score is None:
        return _WHOOP_CONTEXT_NONE

    if recovery_score < 40:
        interpretation = "Rough day — body is stressed and tired. Gentle is the default unless they push."
    elif recovery_score < 60:
        interpretation = "Moderate day — not great, not terrible. Middle-of-the-road energy is safe."
    elif recovery_score < 80:
        interpretation = "Decent day — body is doing fine. Can handle most things."
    else:
        interpretation = "Great day — body is fully charged. Full energy is fair game."

    return _WHOOP_CONTEXT_AVAILABLE.format(
        recovery=f"{recovery_score:.0f}",
        state=state or "unknown",
        body_interpretation=interpretation,
    )


def _build_song_library(songs: list[dict]) -> str:
    """Format the song library as a numbered list for the LLM.

    Interleaved by artist to prevent position bias. Songs arrive sorted by
    engagement (favorites first), but if one artist dominates the top 50,
    the LLM over-indexes. Interleaving ensures diverse artists appear early
    while preserving engagement order within each artist.
    """
    # Round-robin interleave: take top song from each artist, then second, etc.
    from collections import defaultdict
    by_artist: dict[str, list[dict]] = defaultdict(list)
    for song in songs:
        by_artist[(song.get("artist") or "").lower()].append(song)

    interleaved = []
    max_depth = max((len(v) for v in by_artist.values()), default=0)
    for depth in range(max_depth):
        for artist_songs in by_artist.values():
            if depth < len(artist_songs):
                interleaved.append(artist_songs[depth])

    # Build index mapping: interleaved position → original song
    # (so LLM indices map back correctly)
    lines = []
    indexed_songs = []
    for i, song in enumerate(interleaved, 1):
        name = song.get("name", "?")
        artist = song.get("artist", "?")
        moods = song.get("mood_tags") or []
        if isinstance(moods, str):
            moods = json.loads(moods)
        mood_str = " ".join(moods) if moods else ""
        energy = song.get("energy", 0)
        valence = song.get("valence", 0)
        engagement = song.get("engagement_score") or 0
        fav = " ★" if engagement > 0.5 else ""
        lines.append(f"[{i}] {name} — {artist} | {mood_str} | e={energy:.1f} v={valence:.1f}{fav}")
        indexed_songs.append(song)
    return "\n".join(lines), indexed_songs


def select_songs_nl(
    query: str,
    songs: list[dict],
    recovery_score: float | None = None,
    hrv: float | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Let the LLM pick songs directly from the library.

    Args:
        query: User's natural language request.
        songs: Full classified song library (from get_all_classified_songs).
        recovery_score: Today's WHOOP recovery % (None if unavailable).
        hrv: Today's HRV in ms (None if unavailable).
        state: Today's classified state (None if unavailable).

    Returns:
        If clarification needed:
            {"needs_clarification": True, "clarifying_question": str}
        If ready:
            {"needs_clarification": False, "songs": list[dict], "dj_message": str,
             "playlist_name": str}
    """
    from config import get_anthropic_api_key
    from llm_client import call_anthropic

    whoop_ctx = _build_whoop_context(recovery_score, state)
    song_library_text, indexed_songs = _build_song_library(songs)

    system_prompt = _SYSTEM_PROMPT.format(
        whoop_context=whoop_ctx,
        song_count=len(indexed_songs),
        song_library=song_library_text,
    )

    logger.info("NL song selector: query='%s', %d songs, recovery=%s",
                query[:50], len(songs), recovery_score)

    raw = call_anthropic(
        api_key=get_anthropic_api_key(),
        model=LLM_MODEL_ANTHROPIC,
        system=system_prompt,
        messages=[
            {"role": "user", "content": query},
        ],
        temperature=0.3,
        timeout=90,  # Larger context needs more time
    )
    # Claude doesn't have json_object mode — extract JSON from response
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    data = json.loads(raw)

    # Check for clarification
    if data.get("needs_clarification"):
        question = data.get("clarifying_question", "Could you tell me more about what you're in the mood for?")
        logger.info("NL song selector: needs clarification → '%s'", question[:60])
        return {
            "needs_clarification": True,
            "clarifying_question": question,
        }

    # Parse song selections
    indices = data.get("song_indices", [])
    dj_message = data.get("dj_message", "Here's your playlist.")
    playlist_name = data.get("playlist_name", "On Demand")

    # Validate indices and map to song dicts
    selected = []
    seen_indices: set[int] = set()
    for idx in indices:
        if not isinstance(idx, int):
            continue
        if idx < 1 or idx > len(indexed_songs):
            logger.warning("NL song selector: invalid index %d (library size %d)", idx, len(indexed_songs))
            continue
        if idx in seen_indices:
            continue
        seen_indices.add(idx)
        song = indexed_songs[idx - 1]  # 1-indexed in prompt
        selected.append(song)

    # Deduplicate song versions (the LLM can't tell that "Channa Mereya" and
    # "Channa Mereya (From "Ae Dil Hai Mushkil")" are the same song with different URIs)
    import re
    seen_titles: set[str] = set()
    deduped: list[dict] = []
    for song in selected:
        title = (song.get("name") or "").strip()
        normalized = re.sub(r'\s*[\(\-].*$', '', title).strip().lower()
        if normalized in seen_titles:
            logger.info("Version dedup: skipping '%s' (duplicate of '%s')", song.get("name"), normalized)
            continue
        seen_titles.add(normalized)
        deduped.append(song)
    selected = deduped

    if len(selected) < 15:
        logger.warning("NL song selector: only %d valid songs after dedup (expected 20)", len(selected))

    logger.info(
        "NL song selector: selected %d songs, playlist='%s'",
        len(selected), playlist_name,
    )

    return {
        "needs_clarification": False,
        "songs": selected,
        "dj_message": dj_message,
        "playlist_name": playlist_name,
    }
