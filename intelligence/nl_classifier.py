"""Natural language → neuro profile classifier.

Translates a user's natural language request (e.g. "walking to campus, want
something upbeat") into a neuro profile + target valence that the matching
engine can use. Optionally calibrated by today's WHOOP recovery data.
"""

import json
import logging
import math
from typing import Any

from config import (
    LLM_MODEL_OPENAI,
    VALENCE_TARGET_GRND,
    VALENCE_TARGET_PARA,
    VALENCE_TARGET_SYMP,
)

logger = logging.getLogger(__name__)

_NL_SYSTEM_PROMPT = """You're a friend who DJs for someone. You translate their music requests into a
neurological profile — but first, you decide if you understand what they want.

STEP 1: Is the request clear enough to build a playlist?
- Clear: "gym motivational", "walking to campus, upbeat", "romantic dinner" → generate immediately.
- Ambiguous: "I'm sad", "I'm in a mood", "something emotional", "play me something" → ask ONE
  short clarifying question with 2-3 concrete options. Casual and warm, like a friend would ask.

If you need to clarify, return ONLY:
{{
  "needs_clarification": true,
  "clarifying_question": "your friendly question here"
}}

Respond with JSON only.

STEP 2: If you're ready to generate (either the request was clear, or this is after clarification):

The profile has three dimensions (must sum to 1.0):
- para (parasympathetic): calming, slowing down, rest, warmth. High = slow, acoustic, gentle.
- symp (sympathetic): energizing, activating, pushing forward. High = fast, loud, driving.
- grnd (grounding): emotional processing, reflection, connection. High = moderate tempo, warm, lyrical.

target_valence (0.0-1.0):
- 0.3-0.4: melancholy, heavy, reflective
- 0.5-0.6: warm, gentle, serene
- 0.7-0.8: uplifting, joyful, energetic

Filters (restrict the song pool):
- mood_filter: ONE primary mood tag (e.g. "motivational", "romantic", "sad", "energetic", "seductive").
  The system expands to related tags automatically. Set ONLY when user asks for a specific vibe. null otherwise.
  IMPORTANT: "seductive", "freaky", "50 shades" → mood_filter: "seductive", para ~0.30, grnd ~0.40, valence ~0.40.
  Seductive is NOT party. It's dark, slow, sultry. Low energy, not high energy.
- genre_filter: list of genre tags. Set ONLY when user literally mentions a genre. NEVER infer. null otherwise.
- era_filter: decade or year range. Set ONLY when user literally mentions an era. null otherwise.
- artist_filter: list of artist names the user mentioned (e.g. ["The Weeknd", "Drake"]). Set when user
  mentions specific artists. The system will prioritize their songs. null if no artists mentioned.

{whoop_context}

- allow_motivational: true ONLY for physical exertion contexts (gym, workout, running, sports).

Return:
{{
  "needs_clarification": false,
  "dj_message": "A warm, casual one-liner about the playlist you're making. Like a friend, not a robot. One sentence.",
  "para": float,
  "symp": float,
  "grnd": float,
  "target_valence": float,
  "playlist_name_suffix": "short 2-3 word label",
  "reasoning": "one sentence explaining the playlist direction",
  "genre_filter": ["tag1"] or null,
  "era_filter": "1990s" or null,
  "mood_filter": "primary_mood_tag" or null,
  "artist_filter": ["Artist Name"] or null,
  "allow_motivational": boolean
}}"""

_WHOOP_CONTEXT = """IMPORTANT — The user's WHOOP recovery today: {recovery}% (HRV: {hrv}ms, state: {state}).

WHOOP recovery calibrates intensity. The user's words describe DIRECTION, recovery defines RANGE:
- "Upbeat" at 35% recovery → moderate energy (symp ~0.55, not 0.85). Body can't handle full throttle.
- "Upbeat" at 90% recovery → full energy (symp ~0.85). Body is ready.
- "Calm" at 35% recovery → strong calming (para ~0.70). Body needs deep rest.
- "Calm" at 90% recovery → gentle calming (para ~0.45). Body is fine, just wants to chill."""

_NO_WHOOP_CONTEXT = """No WHOOP recovery data available. Interpret the request at face value without body-state calibration."""


def classify_nl_request(
    query: str,
    recovery_score: float | None = None,
    hrv: float | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Translate natural language to neuro profile + target valence.

    Args:
        query: User's natural language request.
        recovery_score: Today's WHOOP recovery % (None if unavailable).
        hrv: Today's HRV in ms (None if unavailable).
        state: Today's classified state (None if unavailable).

    Returns:
        Dict with keys: profile, target_valence, reasoning, playlist_name_suffix,
        genre_filter, era_filter, mood_filter, dj_message.
        OR if clarification needed: dict with needs_clarification=True,
        clarifying_question=str.
    """
    if recovery_score is not None:
        whoop_ctx = _WHOOP_CONTEXT.format(
            recovery=f"{recovery_score:.0f}",
            hrv=f"{hrv:.1f}" if hrv else "unknown",
            state=state or "unknown",
        )
    else:
        whoop_ctx = _NO_WHOOP_CONTEXT

    system_prompt = _NL_SYSTEM_PROMPT.format(whoop_context=whoop_ctx)

    from config import get_openai_api_key
    from llm_client import call_openai

    raw = call_openai(
        api_key=get_openai_api_key(),
        model=LLM_MODEL_OPENAI,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=30,
    )
    data = json.loads(raw)

    # Check if clarification is needed
    if data.get("needs_clarification"):
        question = data.get("clarifying_question", "Could you tell me more about what you're in the mood for?")
        logger.info("NL classifier: '%s' → needs clarification", query[:50])
        return {
            "needs_clarification": True,
            "clarifying_question": question,
        }

    # Extract and normalize profile
    para = max(0.0, float(data.get("para", 0.33)))
    symp = max(0.0, float(data.get("symp", 0.34)))
    grnd = max(0.0, float(data.get("grnd", 0.33)))

    # WHOOP calibration clamps
    if recovery_score is not None:
        if recovery_score < 40:
            symp = min(symp, 0.60)
        if recovery_score > 80:
            para = min(para, 0.50)

    # Normalize to sum to 1.0
    total = para + symp + grnd
    if total > 0:
        para, symp, grnd = para / total, symp / total, grnd / total
    else:
        para, symp, grnd = 0.33, 0.34, 0.33

    profile = {"para": round(para, 4), "symp": round(symp, 4), "grnd": round(grnd, 4)}

    # Target valence — use LLM's if provided, else compute from profile
    target_valence = data.get("target_valence")
    if target_valence is not None:
        target_valence = max(0.0, min(1.0, float(target_valence)))
    else:
        target_valence = (
            para * VALENCE_TARGET_PARA
            + symp * VALENCE_TARGET_SYMP
            + grnd * VALENCE_TARGET_GRND
        )

    logger.info(
        "NL classifier: '%s' → para=%.2f symp=%.2f grnd=%.2f valence=%.2f",
        query[:50], para, symp, grnd, target_valence,
    )

    # Normalize mood_filter: LLM may return a string or list — always pass a list downstream
    raw_mood = data.get("mood_filter")
    if isinstance(raw_mood, str):
        mood_filter = [raw_mood]
    elif isinstance(raw_mood, list):
        mood_filter = raw_mood
    else:
        mood_filter = None

    return {
        "needs_clarification": False,
        "dj_message": data.get("dj_message"),
        "profile": profile,
        "target_valence": target_valence,
        "reasoning": data.get("reasoning", ""),
        "playlist_name_suffix": data.get("playlist_name_suffix", "On Demand"),
        "genre_filter": data.get("genre_filter"),
        "era_filter": data.get("era_filter"),
        "mood_filter": mood_filter,
        "artist_filter": data.get("artist_filter"),
        "allow_motivational": bool(data.get("allow_motivational", False)),
    }
