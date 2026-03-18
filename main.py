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
    "dedup-songs": "Consolidate duplicate songs (same name+artist, different URIs)",
    "compute-engagement": "Compute engagement scores for all eligible songs",
    "classify-state": "Classify today's physiological state from WHOOP data",
    "download-audio": "Download 30-second audio clips (Spotify preview + yt-dlp)",
    "analyze-audio": "Run Essentia analysis on audio clips",
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
    elif command == "dedup-songs":
        _cmd_dedup_songs()
    elif command == "compute-engagement":
        _cmd_compute_engagement()
    elif command == "classify-state":
        _cmd_classify_state()
    elif command == "download-audio":
        _cmd_download_audio()
    elif command == "analyze-audio":
        _cmd_analyze_audio()
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
    from spotify.dedup import consolidate_duplicate_songs
    from spotify.engagement import compute_engagement_scores

    conn = get_connection()
    sp = get_spotify_client(conn)
    liked = sync_liked_songs(conn, sp)
    top = sync_top_tracks(conn, sp)
    metadata = fetch_batch_metadata(conn, sp)
    print(f"\nSpotify sync complete:")
    print(f"  Liked songs:   {liked:,}")
    print(f"  Top tracks:    {top:,}")
    print(f"  Metadata fetched: {metadata:,}")

    result = consolidate_duplicate_songs(conn)
    if result["groups"] > 0:
        print(f"  Duplicates consolidated: {result['groups']} groups ({result['songs_merged']} merged)")

    scored = compute_engagement_scores(conn)
    print(f"  Engagement scored: {scored:,}")
    conn.close()


def _cmd_dedup_songs() -> None:
    from spotify.dedup import consolidate_duplicate_songs

    conn = get_connection()
    result = consolidate_duplicate_songs(conn)
    if result["groups"] > 0:
        print(f"\nConsolidated {result['groups']} duplicate groups "
              f"({result['songs_merged']} songs merged)")
    else:
        print("\nNo duplicate songs found")
    conn.close()


def _cmd_compute_engagement() -> None:
    from spotify.engagement import compute_engagement_scores
    from spotify.dedup import consolidate_duplicate_songs

    conn = get_connection()

    # Consolidate duplicates before scoring — dedup changes play counts
    result = consolidate_duplicate_songs(conn)
    if result["groups"] > 0:
        print(f"Consolidated {result['groups']} duplicate groups "
              f"({result['songs_merged']} songs merged)")

    scored = compute_engagement_scores(conn)
    print(f"\nEngagement scoring complete: {scored:,} songs scored")

    # Distribution summary
    rows = conn.execute("""
        SELECT ROUND(engagement_score, 1) as bucket, COUNT(*) as cnt
        FROM songs WHERE engagement_score IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """).fetchall()
    if rows:
        print("\nScore distribution:")
        for row in rows:
            print(f"  {row['bucket']:.1f}: {row['cnt']:,} songs")

    # Top 10
    top = conn.execute("""
        SELECT name, artist, play_count, engagement_score
        FROM songs ORDER BY engagement_score DESC LIMIT 10
    """).fetchall()
    if top:
        print("\nTop 10 by engagement:")
        for i, row in enumerate(top, 1):
            print(f"  {i:2d}. {row['name']} — {row['artist']} "
                  f"(plays: {row['play_count']}, score: {row['engagement_score']:.4f})")

    # Integrity checks
    bad = conn.execute(
        "SELECT COUNT(*) as cnt FROM songs WHERE engagement_score < 0 OR engagement_score > 1"
    ).fetchone()
    print(f"\nScores outside [0,1]: {bad['cnt']}")

    conn.close()


def _cmd_classify_state() -> None:
    from datetime import date

    from intelligence.state_classifier import classify_state

    # Support --date flag, default to today
    target_date = date.today().isoformat()
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            target_date = sys.argv[idx + 1]

    conn = get_connection()
    result = classify_state(conn, target_date)

    state = result["state"].replace("_", " ").title()
    print(f"\n{'='*50}")
    print(f"  State: {state}")
    print(f"  Confidence: {result['confidence']}")
    print(f"  Date: {target_date}")
    print(f"{'='*50}")

    if result["reasoning"]:
        print("\nReasoning:")
        for r in result["reasoning"]:
            print(f"  - {r}")

    metrics = result["metrics"]
    if metrics:
        print("\nToday's Metrics:")
        if "recovery_score" in metrics and metrics["recovery_score"] is not None:
            print(f"  Recovery:  {metrics['recovery_score']:.0f}%")
        if "hrv_rmssd_milli" in metrics and metrics["hrv_rmssd_milli"] is not None:
            print(f"  HRV:       {metrics['hrv_rmssd_milli']:.1f} ms")
        if "resting_heart_rate" in metrics and metrics["resting_heart_rate"] is not None:
            print(f"  RHR:       {metrics['resting_heart_rate']:.0f} bpm")
        if "deep_sleep_ms" in metrics and metrics["deep_sleep_ms"] is not None:
            deep_h = metrics["deep_sleep_ms"] / 3_600_000
            print(f"  Deep:      {deep_h:.1f}h")
        if "rem_sleep_ms" in metrics and metrics["rem_sleep_ms"] is not None:
            rem_h = metrics["rem_sleep_ms"] / 3_600_000
            print(f"  REM:       {rem_h:.1f}h")
        if "sleep_debt_hours" in metrics and metrics["sleep_debt_hours"] is not None:
            print(f"  Debt:      {metrics['sleep_debt_hours']:.1f}h")

    baselines = result.get("baselines", {})
    if baselines.get("hrv"):
        hrv = baselines["hrv"]
        print(f"\nBaselines (30-day):")
        print(f"  HRV mean:  {hrv['mean']:.3f} (ln), CV: {hrv['cv']:.3f}")
    if baselines.get("rhr"):
        rhr = baselines["rhr"]
        print(f"  RHR mean:  {rhr['mean']:.1f} bpm")

    conn.close()


def _cmd_download_audio() -> None:
    from config import AUDIO_CLIPS_DIR
    from db.queries import get_unclassified_songs
    from spotify.auth import get_spotify_client
    from classification.audio import acquire_audio_clips

    conn = get_connection()
    sp = get_spotify_client(conn)
    songs = get_unclassified_songs(conn)

    if not songs:
        print("No unclassified songs to download audio for.")
        conn.close()
        return

    print(f"Downloading audio clips for {len(songs)} songs...")
    stats = acquire_audio_clips(sp, songs, AUDIO_CLIPS_DIR)

    print(f"\nAudio download complete:")
    print(f"  Downloaded:      {stats['downloaded']:,}")
    print(f"  Already cached:  {stats['already_cached']:,}")
    print(f"  Failed:          {stats['failed']:,}")
    print(f"  Spotify preview: {stats['preview_count']:,}")
    print(f"  yt-dlp fallback: {stats['ytdlp_count']:,}")
    conn.close()


def _cmd_analyze_audio() -> None:
    from config import AUDIO_CLIPS_DIR
    from db.queries import count_rows
    from classification.essentia_analyzer import analyze_all_songs

    conn = get_connection()

    if not AUDIO_CLIPS_DIR.exists():
        print("No audio_clips/ directory found. Run download-audio first.")
        conn.close()
        return

    print("Running Essentia analysis on audio clips...")
    stats = analyze_all_songs(conn, AUDIO_CLIPS_DIR)

    print(f"\nEssentia analysis complete:")
    print(f"  Analyzed:  {stats['analyzed']:,}")
    print(f"  Failed:    {stats['failed']:,}")
    print(f"  Skipped:   {stats['skipped']:,} (no audio clip)")
    print(f"\nTotal classifications: {count_rows(conn, 'song_classifications'):,}")
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
