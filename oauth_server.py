"""Temporary local OAuth callback server. Captures the authorization code automatically."""

import secrets
import ssl
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse

captured_code = None
expected_state = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global captured_code
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        captured_code = query.get("code", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if captured_code:
            self.wfile.write(b"<h1>Authorization successful!</h1><p>You can close this tab.</p>")
        else:
            error = query.get("error", ["unknown"])[0]
            self.wfile.write(f"<h1>Authorization failed: {error}</h1>".encode())

    def log_message(self, format, *args):
        pass


def _parse_profile() -> str | None:
    """Extract --profile from argv, return profile name or None."""
    if "--profile" not in sys.argv:
        return None
    idx = sys.argv.index("--profile")
    if idx + 1 >= len(sys.argv):
        print("Error: --profile requires a name")
        sys.exit(1)
    return sys.argv[idx + 1]


def run_whoop():
    """WHOOP OAuth flow with state parameter."""
    global captured_code, expected_state
    captured_code = None

    from config import get_profile_db_path
    from db.schema import get_connection
    from urllib.parse import urlencode
    from config import (
        WHOOP_AUTH_URL, WHOOP_SCOPES,
        get_whoop_client_id, get_whoop_redirect_uri,
    )
    from whoop.auth import exchange_code_for_tokens

    profile = _parse_profile()
    db_path = get_profile_db_path(profile)
    if profile:
        print(f"[profile: {profile}] → {db_path}")

    expected_state = secrets.token_urlsafe(32)
    params = {
        "client_id": get_whoop_client_id(),
        "redirect_uri": get_whoop_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(WHOOP_SCOPES),
        "state": expected_state,
    }
    auth_url = f"{WHOOP_AUTH_URL}?{urlencode(params)}"

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    server.timeout = 300

    print(f"\nOpen this URL in your browser:\n")
    print(auth_url)
    print(f"\nWaiting for authorization...\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server.handle_request()

    if captured_code:
        print("Got authorization code. Exchanging for tokens...")
        conn = get_connection(db_path)
        exchange_code_for_tokens(captured_code, conn)
        print("\nWHOOP authorization complete! Tokens stored.")
        conn.close()
    else:
        print("No authorization code received.")
        sys.exit(1)


def run_spotify():
    """Spotify OAuth flow — local server on 127.0.0.1:8080."""
    global captured_code
    captured_code = None

    from config import get_profile_db_path
    from db.schema import get_connection
    from config import (
        SPOTIFY_SCOPES,
        get_spotify_client_id, get_spotify_redirect_uri,
    )
    from db.queries import save_token

    profile = _parse_profile()
    db_path = get_profile_db_path(profile)
    if profile:
        print(f"[profile: {profile}] → {db_path}")

    client_id = get_spotify_client_id()
    redirect_uri = get_spotify_redirect_uri()
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SPOTIFY_SCOPES),
        "state": state,
    }
    auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"

    server = HTTPServer(("127.0.0.1", 8080), CallbackHandler)
    server.timeout = 300

    print(f"\nOpen this URL in your browser:\n")
    print(auth_url)
    print(f"\nWaiting for authorization...\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server.handle_request()

    if not captured_code:
        print("No authorization code received.")
        sys.exit(1)

    # Exchange code for tokens
    import httpx
    from config import get_spotify_client_secret
    print("Got authorization code. Exchanging for tokens...")

    response = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": captured_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": get_spotify_client_secret(),
        },
    )
    response.raise_for_status()
    data = response.json()

    import time
    conn = get_connection(db_path)
    save_token(
        conn,
        provider="spotify",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=time.time() + data.get("expires_in", 3600),
    )
    print(f"\nSpotify authorization complete! Tokens stored.")

    # Verify it works
    from spotify.auth import get_spotify_client
    sp = get_spotify_client(conn)
    user = sp.current_user()
    print(f"Authenticated as: {user['display_name']} ({user['id']})")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python oauth_server.py [--profile <name>] <whoop|spotify>")
        sys.exit(1)

    # Find the provider arg (not --profile or its value)
    provider = None
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--profile":
            i += 2  # skip flag + value
            continue
        if sys.argv[i] in ("whoop", "spotify"):
            provider = sys.argv[i]
            break
        i += 1

    if provider is None:
        print("Usage: python oauth_server.py [--profile <name>] <whoop|spotify>")
        sys.exit(1)

    if provider == "whoop":
        run_whoop()
    elif provider == "spotify":
        run_spotify()
