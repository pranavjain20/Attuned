"""Attuned — WHOOP-informed Spotify playlist generator.

CLI entry point for all commands.
"""

import logging
import sys

from config import DB_PATH, STREAMING_HISTORY_DIR
from db.schema import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COMMANDS = {
    "ingest-history": "Parse extended streaming history JSON into the database",
    "sync-whoop": "Pull today's WHOOP recovery + sleep data",
    "sync-spotify": "Sync liked songs, top tracks, and fetch metadata from Spotify",
    "sync-all": "Run sync-whoop and sync-spotify",
    "generate": "Generate today's playlist (not yet implemented)",
}


def main() -> None:
    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "ingest-history":
        _cmd_ingest_history()
    elif command == "sync-whoop":
        _cmd_sync_whoop()
    elif command == "sync-spotify":
        _cmd_sync_spotify()
    elif command == "sync-all":
        _cmd_sync_whoop()
        _cmd_sync_spotify()
    elif command == "sync-whoop-history":
        _cmd_sync_whoop_history()
    elif command == "generate":
        print("Not yet implemented — playlist generation comes Day 5-6.")
    elif command == "auth-whoop":
        _cmd_auth_whoop()
    elif command == "auth-spotify":
        _cmd_auth_spotify()
    else:
        print(f"Unknown command: {command}")
        _print_usage()
        sys.exit(1)


def _print_usage() -> None:
    print("Usage: python main.py <command>\n")
    print("Commands:")
    for cmd, desc in COMMANDS.items():
        print(f"  {cmd:<20} {desc}")
    print(f"  {'auth-whoop':<20} Run WHOOP OAuth flow")
    print(f"  {'auth-spotify':<20} Run Spotify OAuth flow (opens browser)")


def _cmd_ingest_history() -> None:
    from spotify.sync import ingest_extended_history
    from db.queries import count_rows

    conn = get_connection()
    result = ingest_extended_history(conn, STREAMING_HISTORY_DIR)

    print(f"\nIngestion complete:")
    print(f"  Records parsed:     {result['total_records']:,}")
    print(f"  History rows added: {result['inserted_history']:,}")
    print(f"  Unique songs:       {result['total_songs']:,}")
    print(f"\nDatabase totals:")
    print(f"  listening_history:  {count_rows(conn, 'listening_history'):,}")
    print(f"  songs:              {count_rows(conn, 'songs'):,}")

    # Show play count distribution
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM songs WHERE play_count >= 5"
    ).fetchone()
    print(f"  songs (5+ plays):   {row['cnt']:,}")
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM songs WHERE play_count >= 10"
    ).fetchone()
    print(f"  songs (10+ plays):  {row['cnt']:,}")
    conn.close()


def _cmd_sync_whoop_history() -> None:
    from whoop.sync import sync_full_history
    from db.queries import count_rows

    conn = get_connection()
    result = sync_full_history(conn)
    print(f"\nWHOOP full history sync complete:")
    print(f"  Recovery records: {result['recovery']:,}")
    print(f"  Sleep records:    {result['sleep']:,}")
    print(f"\nDatabase totals:")
    print(f"  whoop_recovery: {count_rows(conn, 'whoop_recovery'):,}")
    print(f"  whoop_sleep:    {count_rows(conn, 'whoop_sleep'):,}")
    conn.close()


def _cmd_sync_whoop() -> None:
    from whoop.sync import sync_today

    conn = get_connection()
    result = sync_today(conn)
    if result["recovery"]:
        print("WHOOP recovery synced for today.")
    else:
        print("No WHOOP recovery data found for today.")
    if result["sleep"]:
        print("WHOOP sleep synced for today.")
    else:
        print("No WHOOP sleep data found for today.")
    conn.close()


def _cmd_sync_spotify() -> None:
    from spotify.auth import get_spotify_client
    from spotify.sync import sync_liked_songs, sync_top_tracks, fetch_batch_metadata

    conn = get_connection()
    sp = get_spotify_client(conn)
    liked = sync_liked_songs(conn, sp)
    top = sync_top_tracks(conn, sp)
    metadata = fetch_batch_metadata(conn, sp)
    print(f"\nSpotify sync complete:")
    print(f"  Liked songs:   {liked:,}")
    print(f"  Top tracks:    {top:,}")
    print(f"  Metadata fetched: {metadata:,}")
    conn.close()


def _cmd_auth_whoop() -> None:
    from whoop.auth import get_authorization_url, exchange_code_for_tokens

    conn = get_connection()
    url = get_authorization_url()
    print(f"\nOpen this URL in your browser:\n{url}\n")
    code = input("Paste the authorization code: ").strip()
    exchange_code_for_tokens(code, conn)
    print("WHOOP tokens stored successfully.")
    conn.close()


def _cmd_auth_spotify() -> None:
    from spotify.auth import get_spotify_client

    conn = get_connection()
    sp = get_spotify_client(conn)
    user = sp.current_user()
    print(f"Authenticated as: {user['display_name']} ({user['id']})")
    conn.close()


if __name__ == "__main__":
    main()
