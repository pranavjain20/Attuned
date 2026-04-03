"""WhatsApp webhook server — receives Twilio messages, replies with playlists.

Run: python -m whatsapp.server
Expose: ngrok http 5000
Configure: Twilio console → WhatsApp sandbox → webhook URL → https://xxx.ngrok.io/webhook
"""

import logging
import os
import sys

from flask import Flask, request as flask_request

# Add project root to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER
from whatsapp.handler import handle_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages from Twilio."""
    from twilio.twiml.messaging_response import MessagingResponse

    # Parse incoming message
    from_number = flask_request.form.get("From", "")  # "whatsapp:+919876543210"
    body = flask_request.form.get("Body", "").strip()

    # Strip "whatsapp:" prefix to get clean phone number.
    # Twilio sends "whatsapp:+16507989300" but form decoding turns + into space.
    phone = from_number.replace("whatsapp:", "").strip()
    if phone and not phone.startswith("+"):
        phone = "+" + phone

    logger.info("Incoming from %s: '%s'", phone, body[:80])

    if not body:
        resp = MessagingResponse()
        resp.message("Send me a message and I'll make you a playlist! 🎵")
        return str(resp), 200, {"Content-Type": "text/xml"}

    # Handle the message
    reply_text = handle_message(phone, body)

    # Reply via TwiML (Twilio's inline response format)
    resp = MessagingResponse()
    resp.message(reply_text)
    return str(resp), 200, {"Content-Type": "text/xml"}


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return "ok", 200


def main():
    """Start the webhook server."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.warning(
            "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN not set in .env — "
            "bot will run but Twilio signature verification is disabled"
        )

    port = int(os.getenv("WHATSAPP_PORT", "5000"))
    logger.info("Starting WhatsApp bot on port %d", port)
    logger.info("Webhook URL: http://localhost:%d/webhook", port)
    logger.info("Expose with: ngrok http %d", port)
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
