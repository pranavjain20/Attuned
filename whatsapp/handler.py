"""WhatsApp conversation handler — the conversational DJ over chat.

Receives a phone number + message, manages clarification state,
and returns an immediate reply. Playlist generation happens in a
background thread — the result is sent via Twilio API when ready.
"""

import logging
import sqlite3
import threading
import time
from datetime import date

from config import get_profile_db_path
from db.schema import get_connection
from intelligence.nl_classifier import classify_nl_request
from intelligence.state_classifier import classify_state
from matching.generator import GenerationError, generate_nl_playlist
from spotify.auth import get_spotify_client
from whatsapp.config import (
    CONVERSATION_TTL_SECONDS,
    PHONE_TO_PROFILE,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
)

logger = logging.getLogger(__name__)

# In-memory conversation state. Key: phone number, value: dict with
# original_query and timestamp. Cleared after use or TTL expiry.
_conversations: dict[str, dict] = {}


def _send_whatsapp(to_phone: str, message: str) -> None:
    """Send a WhatsApp message via Twilio API."""
    from twilio.rest import Client

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(
        from_=f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
        to=f"whatsapp:{to_phone}",
        body=message,
    )


def _get_whoop_context(conn: sqlite3.Connection) -> tuple[float | None, float | None, str | None]:
    """Get today's WHOOP recovery context for NL calibration."""
    try:
        classification = classify_state(conn)
        state = classification["state"]
        metrics = classification.get("metrics", {})
        return metrics.get("recovery_score"), metrics.get("hrv_rmssd_milli"), state
    except Exception:
        return None, None, None


def _clear_expired_conversations() -> None:
    """Remove conversations older than TTL."""
    now = time.time()
    expired = [
        phone for phone, conv in _conversations.items()
        if now - conv["timestamp"] > CONVERSATION_TTL_SECONDS
    ]
    for phone in expired:
        del _conversations[phone]


def _generate_and_send(phone: str, profile: str, query: str, nl_result: dict) -> None:
    """Generate playlist in background thread and send result via Twilio API."""
    db_path = get_profile_db_path(None if profile == "default" else profile)
    conn = get_connection(db_path)

    try:
        sp = get_spotify_client(conn)
        result = generate_nl_playlist(
            conn, sp, query, nl_result=nl_result, dry_run=False,
        )

        playlist_url = result.get("playlist_url", "")
        name = result.get("name", "Your Playlist")
        track_count = len(result.get("songs", []))

        reply = f"🎵 {name} ({track_count} tracks)\n{playlist_url}"
        logger.info("WhatsApp [%s]: generated '%s' → %s", profile, name, playlist_url)
        _send_whatsapp(phone, reply)

    except GenerationError as e:
        logger.error("WhatsApp [%s]: generation failed — %s", profile, e)
        _send_whatsapp(phone, f"Couldn't make that playlist — {e}")
    except Exception as e:
        logger.error("WhatsApp [%s]: unexpected error — %s", profile, e, exc_info=True)
        _send_whatsapp(phone, "Something went wrong on my end. Try again in a bit.")
    finally:
        conn.close()


def handle_message(phone: str, message: str) -> str:
    """Process an incoming WhatsApp message and return an immediate reply.

    For clarifying questions and error messages, returns the text directly
    (sent via TwiML response). For playlist generation, returns the DJ
    message immediately and spawns a background thread that sends the
    playlist link via Twilio API when ready.

    Args:
        phone: Phone number in E.164 format (e.g. +919876543210).
        message: The user's message text.

    Returns:
        Immediate reply string (DJ message or clarifying question).
    """
    _clear_expired_conversations()

    # Look up profile
    profile = PHONE_TO_PROFILE.get(phone)
    if not profile:
        logger.warning("Unknown phone number: %s", phone)
        return (
            "Hey! I don't recognize this number. "
            "Ask Pranav to add you to Attuned."
        )

    # Get DB connection and WHOOP context
    db_path = get_profile_db_path(None if profile == "default" else profile)
    conn = get_connection(db_path)

    try:
        recovery_score, hrv, state = _get_whoop_context(conn)

        # Check if this is a reply to a pending clarification
        pending = _conversations.pop(phone, None)

        if pending:
            query = f"{pending['original_query']}. {message}"
            logger.info("WhatsApp [%s]: clarification reply → '%s'", profile, message[:50])
        else:
            query = message
            logger.info("WhatsApp [%s]: new request → '%s'", profile, message[:50])

        # Classify
        nl_result = classify_nl_request(query, recovery_score, hrv, state)

        # If needs clarification and this isn't already a follow-up
        if nl_result.get("needs_clarification") and not pending:
            _conversations[phone] = {
                "original_query": message,
                "timestamp": time.time(),
            }
            question = nl_result.get("clarifying_question", "Could you tell me more?")
            return f"🎵 {question}"

        # If still needs clarification after follow-up, force generation
        if nl_result.get("needs_clarification"):
            nl_result = classify_nl_request(
                f"{query}. IMPORTANT: Do not ask any more questions. "
                f"Set needs_clarification to false and generate the profile now.",
                recovery_score, hrv, state,
            )
            if nl_result.get("needs_clarification"):
                nl_result["needs_clarification"] = False
                nl_result.setdefault("dj_message", "Here's something for you.")
                nl_result.setdefault("profile", {"para": 0.33, "symp": 0.34, "grnd": 0.33})
                nl_result.setdefault("target_valence", 0.50)
                nl_result.setdefault("reasoning", "Forced after clarification loop")
                nl_result.setdefault("playlist_name_suffix", "For You")
                nl_result.setdefault("allow_motivational", False)

        # Return DJ message immediately, generate playlist in background
        dj_msg = nl_result.get("dj_message") or "Working on your playlist..."
        dj_msg += "\n\n⏳ Building your playlist now — link coming in about a minute."
        thread = threading.Thread(
            target=_generate_and_send,
            args=(phone, profile, query, nl_result),
            daemon=True,
        )
        thread.start()
        logger.info("WhatsApp [%s]: spawned background generation", profile)
        return dj_msg

    except Exception as e:
        logger.error("WhatsApp [%s]: unexpected error — %s", profile, e, exc_info=True)
        return "Something went wrong on my end. Try again in a bit."
    finally:
        conn.close()
