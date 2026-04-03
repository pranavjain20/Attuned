"""WhatsApp bot configuration — Twilio credentials and phone-to-profile mapping."""

import os

from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "+14155238886")

# Phone number → Attuned profile mapping.
# Numbers must be in E.164 format (e.g. +919876543210).
# Loaded from env: WHATSAPP_PRANAV=+91..., WHATSAPP_KOMAL=+91..., etc.
PHONE_TO_PROFILE: dict[str, str] = {}
for env_key, profile_name in [
    ("WHATSAPP_PRANAV", "default"),
    ("WHATSAPP_KOMAL", "komal"),
    ("WHATSAPP_SAUMYA", "saumya"),
]:
    number = os.getenv(env_key)
    if number:
        PHONE_TO_PROFILE[number] = profile_name

# Conversation TTL: pending clarifications expire after this many seconds.
CONVERSATION_TTL_SECONDS = 600  # 10 minutes
