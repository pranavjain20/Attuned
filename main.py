"""Attuned — WHOOP-informed Spotify playlist generator.

CLI entry point for all commands.
"""

import logging
import sys
from collections.abc import Callable
from pathlib import Path

from config import STREAMING_HISTORY_DIR, get_profile_db_path
from db.schema import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COMMANDS = {
    "onboard": "Run full onboarding pipeline for a new user",
    "ingest-history": "Parse extended streaming history JSON into the database",
    "sync-whoop": "Pull today's WHOOP recovery + sleep data",
    "sync-spotify": "Sync liked songs, top tracks, and fetch metadata from Spotify",
    "sync-all": "Run sync-whoop and sync-spotify",
    "sync-recently-played": "Pull recently-played tracks from Spotify (last 24h)",
    "dedup-songs": "Consolidate duplicate songs (same name+artist, different URIs)",
    "compute-engagement": "Compute engagement scores for all eligible songs",
    "classify-state": "Classify today's physiological state from WHOOP data",
    "download-audio": "Download audio clips (Spotify preview + yt-dlp)",
    "redownload-short-clips": "Replace short preview clips with full YouTube downloads",
    "analyze-audio": "Run Essentia analysis on audio clips",
    "classify-songs": "Run LLM classification on unclassified songs",
    "validate-classifications": "Validate existing classifications and flag suspicious songs",
    "recompute-scores": "Recompute neuro scores from existing DB data (no API calls)",
    "match-songs": "Match songs to a physiological state (testing/preview)",
    "generate": "Generate today's playlist from WHOOP state + matched songs",
    "request": "Generate a playlist from a natural language request",
    "backfill-release-years": "Backfill release_year from Spotify for songs missing it",
    "sync-whoop-history": "Pull full WHOOP recovery + sleep history",
}


def _extract_profile() -> str | None:
    """Extract --profile <name> from sys.argv early, before command dispatch.

    Removes the flag and its value from sys.argv so downstream flag parsing
    isn't confused. Returns None if not provided.
    """
    if "--profile" not in sys.argv:
        return None
    idx = sys.argv.index("--profile")
    if idx + 1 >= len(sys.argv):
        print("Error: --profile requires a name (e.g. --profile myprofile)")
        sys.exit(1)
    profile = sys.argv[idx + 1]
    # Remove --profile and its value from argv
    del sys.argv[idx:idx + 2]
    return profile


def main() -> None:
    profile = _extract_profile()
    db_path = get_profile_db_path(profile)

    if profile:
        print(f"[profile: {profile}] → {db_path}")

    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "onboard":
        _cmd_onboard(db_path)
    elif command == "ingest-history":
        _cmd_ingest_history(db_path)
    elif command == "sync-whoop":
        _cmd_sync_whoop(db_path)
    elif command == "sync-spotify":
        metadata_only = "--metadata-only" in sys.argv
        _cmd_sync_spotify(db_path, metadata_only=metadata_only)
    elif command == "sync-all":
        _cmd_sync_whoop(db_path)
        _cmd_sync_spotify(db_path)
    elif command == "sync-recently-played":
        _cmd_sync_recently_played(db_path)
    elif command == "dedup-songs":
        _cmd_dedup_songs(db_path)
    elif command == "compute-engagement":
        _cmd_compute_engagement(db_path)
    elif command == "classify-state":
        _cmd_classify_state(db_path)
    elif command == "download-audio":
        _cmd_download_audio(db_path)
    elif command == "redownload-short-clips":
        _cmd_redownload_short_clips(db_path)
    elif command == "analyze-audio":
        _cmd_analyze_audio(db_path)
    elif command == "classify-songs":
        _cmd_classify_songs(db_path)
    elif command == "validate-classifications":
        _cmd_validate_classifications(db_path)
    elif command == "recompute-scores":
        _cmd_recompute_scores(db_path)
    elif command == "sync-whoop-history":
        _cmd_sync_whoop_history(db_path)
    elif command == "backfill-release-years":
        _cmd_backfill_release_years(db_path)
    elif command == "match-songs":
        _cmd_match_songs(db_path)
    elif command == "generate":
        _cmd_generate(db_path)
    elif command == "request":
        _cmd_request(db_path)
    elif command == "auth-whoop":
        _cmd_auth_whoop(db_path)
    elif command == "auth-spotify":
        _cmd_auth_spotify(db_path)
    else:
        print(f"Unknown command: {command}")
        _print_usage()
        sys.exit(1)


def _print_usage() -> None:
    print("Usage: python main.py [--profile <name>] <command>\n")
    print("Options:")
    print(f"  {'--profile <name>':<25} Use a named profile (default: main DB)")
    print()
    print("Commands:")
    for cmd, desc in COMMANDS.items():
        print(f"  {cmd:<25} {desc}")
    print(f"  {'auth-whoop':<25} Run WHOOP OAuth flow")
    print(f"  {'auth-spotify':<25} Run Spotify OAuth flow (opens browser)")


# ---------------------------------------------------------------------------
# Onboarding pipeline
# ---------------------------------------------------------------------------

ONBOARD_STEPS: list[tuple[str, str]] = [
    ("verify-auth", "Verify WHOOP + Spotify tokens"),
    ("ingest-history", "Ingest extended streaming history"),
    ("sync-whoop-history", "Sync full WHOOP recovery + sleep history"),
    ("sync-spotify", "Sync Spotify library + engagement scores"),
    ("download-audio", "Download audio clips for Essentia analysis"),
    ("analyze-audio", "Run Essentia audio analysis"),
    ("classify-songs", "Classify songs via LLM"),
    ("recompute-scores", "Recompute neurological scores"),
    ("generate-preview", "Generate preview playlist (dry run)"),
]


def _onboard_step_verify_auth(db_path: Path) -> None:
    from db.queries import get_token

    conn = get_connection(db_path)
    try:
        whoop = get_token(conn, "whoop")
        spotify = get_token(conn, "spotify")
        missing = []
        if not whoop:
            missing.append("WHOOP (run: python oauth_server.py whoop)")
        if not spotify:
            missing.append("Spotify (run: python oauth_server.py spotify)")
        if missing:
            for m in missing:
                print(f"  Missing: {m}")
            raise RuntimeError("Complete OAuth flows before onboarding")
        print("  WHOOP token: OK")
        print("  Spotify token: OK")
    finally:
        conn.close()


def _onboard_step_ingest_history(db_path: Path) -> None:
    _cmd_ingest_history(db_path)


def _onboard_step_sync_whoop_history(db_path: Path) -> None:
    _cmd_sync_whoop_history(db_path)


def _onboard_step_sync_spotify(db_path: Path) -> None:
    _cmd_sync_spotify(db_path)


def _onboard_step_download_audio(db_path: Path) -> None:
    _cmd_download_audio(db_path)


def _onboard_step_analyze_audio(db_path: Path) -> None:
    _cmd_analyze_audio(db_path)


def _onboard_step_classify_songs(db_path: Path) -> None:
    _cmd_classify_songs(db_path)


def _onboard_step_recompute_scores(db_path: Path) -> None:
    _cmd_recompute_scores(db_path)


def _onboard_step_generate_preview(db_path: Path) -> None:
    from matching.generator import GenerationError, generate_playlist

    conn = get_connection(db_path)
    try:
        try:
            result = generate_playlist(conn, sp=None, dry_run=True)
        except GenerationError as e:
            print(f"  Preview failed: {e}")
            print("  (This is OK — you can run 'generate' later once you have enough data)")
            return

        print(f"  State:  {result['state'].replace('_', ' ').title()}")
        print(f"  Tracks: {len(result['songs'])}")
        print(f"\n  Tracks:")
        for i, song in enumerate(result["songs"], 1):
            name = (song["name"] or "")[:40]
            artist = (song["artist"] or "")[:25]
            print(f"    {i:2d}. {name} — {artist}")
    finally:
        conn.close()


_ONBOARD_STEP_FUNCTIONS: dict[str, Callable[[Path], None]] = {
    "verify-auth": _onboard_step_verify_auth,
    "ingest-history": _onboard_step_ingest_history,
    "sync-whoop-history": _onboard_step_sync_whoop_history,
    "sync-spotify": _onboard_step_sync_spotify,
    "download-audio": _onboard_step_download_audio,
    "analyze-audio": _onboard_step_analyze_audio,
    "classify-songs": _onboard_step_classify_songs,
    "recompute-scores": _onboard_step_recompute_scores,
    "generate-preview": _onboard_step_generate_preview,
}


def _cmd_onboard(db_path: Path) -> None:
    """Run full onboarding pipeline for a new user."""
    # Parse onboard-specific flags
    history_dir = None
    if "--history-dir" in sys.argv:
        idx = sys.argv.index("--history-dir")
        if idx + 1 < len(sys.argv):
            history_dir = sys.argv[idx + 1]

    skip_audio = "--skip-audio" in sys.argv

    resume_from = None
    if "--resume-from" in sys.argv:
        idx = sys.argv.index("--resume-from")
        if idx + 1 < len(sys.argv):
            resume_from = sys.argv[idx + 1]

    # Validate --resume-from step name
    step_names = [name for name, _ in ONBOARD_STEPS]
    if resume_from and resume_from not in step_names:
        print(f"Error: unknown step '{resume_from}'")
        print(f"Valid steps: {', '.join(step_names)}")
        sys.exit(1)

    # Determine which steps to skip
    skipping = resume_from is not None
    steps_to_run: list[tuple[str, str]] = []
    for name, description in ONBOARD_STEPS:
        if skipping:
            if name == resume_from:
                skipping = False
            else:
                continue
        # Skip ingest-history if no --history-dir
        if name == "ingest-history" and not history_dir:
            continue
        # Skip audio steps if --skip-audio
        if name in ("download-audio", "analyze-audio") and skip_audio:
            continue
        steps_to_run.append((name, description))

    total = len(steps_to_run)

    print("=" * 60)
    print("  Attuned Onboarding")
    print("=" * 60)
    print(f"\n  Database: {db_path}")
    print(f"  Steps:    {total}")
    if history_dir:
        print(f"  History:  {history_dir}")
    if skip_audio:
        print(f"  Audio:    skipped (--skip-audio)")
    if resume_from:
        print(f"  Resuming: from {resume_from}")
    print()

    for i, (name, description) in enumerate(steps_to_run, 1):
        print(f"[{i}/{total}] {description} ({name})")
        print("-" * 50)

        step_fn = _ONBOARD_STEP_FUNCTIONS[name]
        try:
            step_fn(db_path)
        except Exception as e:
            print(f"\n{'!' * 50}")
            print(f"  Step failed: {name}")
            print(f"  Error: {e}")
            print(f"\n  To resume:")
            print(f"    python main.py --profile <name> onboard --resume-from {name}")
            if history_dir:
                print(f"    (add --history-dir {history_dir} if needed)")
            if skip_audio:
                print(f"    (add --skip-audio if desired)")
            print(f"{'!' * 50}")
            sys.exit(1)

        print()

    print("=" * 60)
    print("  Onboarding complete!")
    print("=" * 60)
    print(f"\n  Next: python main.py --profile <name> generate")
    print(f"  (Run daily to get your WHOOP-informed playlist)\n")


def _cmd_ingest_history(db_path: Path) -> None:
    from spotify.sync import ingest_extended_history
    from db.queries import count_rows

    # Support --history-dir flag, falls back to env var
    history_dir = STREAMING_HISTORY_DIR
    if "--history-dir" in sys.argv:
        idx = sys.argv.index("--history-dir")
        if idx + 1 < len(sys.argv):
            history_dir = sys.argv[idx + 1]

    conn = get_connection(db_path)
    try:
        result = ingest_extended_history(conn, history_dir)

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
    finally:
        conn.close()


def _cmd_sync_whoop_history(db_path: Path) -> None:
    from whoop.sync import sync_full_history
    from db.queries import count_rows

    conn = get_connection(db_path)
    try:
        result = sync_full_history(conn)
        print(f"\nWHOOP full history sync complete:")
        print(f"  Recovery records: {result['recovery']:,}")
        print(f"  Sleep records:    {result['sleep']:,}")
        print(f"\nDatabase totals:")
        print(f"  whoop_recovery: {count_rows(conn, 'whoop_recovery'):,}")
        print(f"  whoop_sleep:    {count_rows(conn, 'whoop_sleep'):,}")
    finally:
        conn.close()


def _cmd_sync_whoop(db_path: Path) -> None:
    from whoop.sync import sync_today

    conn = get_connection(db_path)
    try:
        result = sync_today(conn)
        if result["recovery"]:
            print("WHOOP recovery synced for today.")
        else:
            print("No WHOOP recovery data found for today.")
        if result["sleep"]:
            print("WHOOP sleep synced for today.")
        else:
            print("No WHOOP sleep data found for today.")
    finally:
        conn.close()


def _cmd_sync_spotify(db_path: Path, metadata_only: bool = False) -> None:
    from spotify.auth import get_spotify_client
    from spotify.sync import sync_liked_songs, sync_top_tracks, fetch_track_metadata
    from spotify.dedup import consolidate_duplicate_songs
    from spotify.engagement import compute_engagement_scores

    conn = get_connection(db_path)
    try:
        sp = get_spotify_client(conn)

        if metadata_only:
            print("Metadata-only mode: skipping liked songs + top tracks pagination")
            metadata = fetch_track_metadata(conn, sp)
            print(f"\nMetadata fetched: {metadata:,}")
        else:
            liked = sync_liked_songs(conn, sp)
            top = sync_top_tracks(conn, sp)
            metadata = fetch_track_metadata(conn, sp)
            print(f"\nSpotify sync complete:")
            print(f"  Liked songs:   {liked:,}")
            print(f"  Top tracks:    {top:,}")
            print(f"  Metadata fetched: {metadata:,}")

            result = consolidate_duplicate_songs(conn)
            if result["groups"] > 0:
                print(f"  Duplicates consolidated: {result['groups']} groups ({result['songs_merged']} merged)")

            scored = compute_engagement_scores(conn)
            print(f"  Engagement scored: {scored:,}")
    finally:
        conn.close()


def _cmd_sync_recently_played(db_path: Path) -> None:
    from spotify.auth import get_spotify_client
    from spotify.sync import sync_recently_played
    from spotify.engagement import compute_engagement_scores

    conn = get_connection(db_path)
    try:
        sp = get_spotify_client(conn)
        recent = sync_recently_played(conn, sp)
        print(f"Recently-played sync: {recent['plays_added']} plays added, {recent['new_songs']} new songs")
        if recent["plays_added"] > 0:
            scored = compute_engagement_scores(conn)
            print(f"Engagement re-scored: {scored:,} songs")
    finally:
        conn.close()


def _cmd_dedup_songs(db_path: Path) -> None:
    from spotify.dedup import consolidate_duplicate_songs

    conn = get_connection(db_path)
    try:
        result = consolidate_duplicate_songs(conn)
        if result["groups"] > 0:
            print(f"\nConsolidated {result['groups']} duplicate groups "
                  f"({result['songs_merged']} songs merged)")
        else:
            print("\nNo duplicate songs found")
    finally:
        conn.close()


def _cmd_compute_engagement(db_path: Path) -> None:
    from spotify.engagement import compute_engagement_scores
    from spotify.dedup import consolidate_duplicate_songs

    conn = get_connection(db_path)
    try:
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
    finally:
        conn.close()


def _cmd_classify_state(db_path: Path) -> None:
    from datetime import date

    from intelligence.state_classifier import classify_state

    # Support --date flag, default to today
    target_date = date.today().isoformat()
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            target_date = sys.argv[idx + 1]

    conn = get_connection(db_path)
    try:
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
            if "recovery_delta" in metrics:
                delta = metrics["recovery_delta"]
                yesterday = metrics.get("yesterday_recovery_score")
                if yesterday is not None:
                    print(f"  Delta:     {delta:+.0f}pp (yesterday: {yesterday:.0f}%)")
                else:
                    print(f"  Delta:     {delta:+.0f}pp")

        baselines = result.get("baselines", {})
        if baselines.get("hrv"):
            hrv = baselines["hrv"]
            print(f"\nBaselines (30-day):")
            print(f"  HRV mean:  {hrv['mean']:.3f} (ln), CV: {hrv['cv']:.3f}")
        if baselines.get("rhr"):
            rhr = baselines["rhr"]
            print(f"  RHR mean:  {rhr['mean']:.1f} bpm")
    finally:
        conn.close()


def _cmd_backfill_release_years(db_path: Path) -> None:
    import time

    from spotify.auth import get_spotify_client
    from spotify.client import parse_track

    conn = get_connection(db_path)
    try:
        sp = get_spotify_client(conn)

        # Phase 1: Free release_years from liked songs + top tracks (paginated, ~5 API calls)
        print("Phase 1: Syncing liked songs + top tracks for free release_years...")
        phase1_updated = 0
        try:
            from spotify.client import get_liked_songs, get_top_tracks
            for label, tracks in [
                ("liked", get_liked_songs(sp)),
                ("top_short", get_top_tracks(sp, "short_term")),
                ("top_medium", get_top_tracks(sp, "medium_term")),
                ("top_long", get_top_tracks(sp, "long_term")),
            ]:
                for t in tracks:
                    if t.get("release_year") is not None:
                        result = conn.execute(
                            "UPDATE songs SET release_year = ? WHERE spotify_uri = ? AND release_year IS NULL",
                            (t["release_year"], t["uri"]),
                        )
                        phase1_updated += result.rowcount
            conn.commit()
            print(f"  Phase 1: {phase1_updated} songs got release_year for free")
        except Exception as e:
            print(f"  Phase 1 failed ({e}), continuing to phase 2...")

        # Phase 2: Individual track calls with 3s delay for the rest
        rows = conn.execute(
            "SELECT spotify_uri FROM songs WHERE release_year IS NULL AND duration_ms IS NOT NULL"
        ).fetchall()
        missing = [r["spotify_uri"] for r in rows]

        if not missing:
            print("All songs already have release_year.")
            return

        print(f"Phase 2: Fetching {len(missing)} songs individually (3s delay, ~{len(missing) * 3 // 60}min)...")
        updated = 0
        failed = 0

        for i, uri in enumerate(missing):
            track_id = uri.split(":")[-1]
            try:
                # 429 retry handled globally by _RateLimitedSpotify wrapper
                track = sp.track(track_id)
                if track:
                    parsed = parse_track(track)
                    if parsed and parsed.get("release_year") is not None:
                        conn.execute(
                            "UPDATE songs SET release_year = ? WHERE spotify_uri = ?",
                            (parsed["release_year"], uri),
                        )
                        updated += 1
            except Exception:
                failed += 1

            # Commit every 25 songs
            if (i + 1) % 25 == 0:
                conn.commit()
                print(f"  {i + 1}/{len(missing)} ({updated} updated, {failed} failed)")

            # 3-second delay between calls to avoid hitting rate limits
            if i < len(missing) - 1:
                time.sleep(3)

        conn.commit()
        print(f"\nBackfill complete: {phase1_updated} (phase 1) + {updated} (phase 2) updated, {failed} failed")

        row = conn.execute("SELECT COUNT(*) as cnt FROM songs WHERE release_year IS NOT NULL").fetchone()
        total = conn.execute("SELECT COUNT(*) as cnt FROM songs").fetchone()
        print(f"  Songs with release_year: {row['cnt']}/{total['cnt']}")
    finally:
        conn.close()


def _cmd_match_songs(db_path: Path) -> None:
    from datetime import date

    from intelligence.state_classifier import classify_state
    from matching.query_engine import select_songs

    # Support --date flag, default to today
    target_date = date.today().isoformat()
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            target_date = sys.argv[idx + 1]

    # Support --state flag to override classifier
    override_state = None
    if "--state" in sys.argv:
        idx = sys.argv.index("--state")
        if idx + 1 < len(sys.argv):
            override_state = sys.argv[idx + 1]

    conn = get_connection(db_path)
    try:
        if override_state:
            state = override_state
            print(f"\nUsing override state: {state}")
        else:
            result = classify_state(conn, target_date)
            state = result["state"]
            print(f"\nDetected state: {state} (confidence: {result['confidence']})")
            if result["reasoning"]:
                for r in result["reasoning"]:
                    print(f"  - {r}")

        if state == "insufficient_data":
            print("\nCannot match songs — insufficient WHOOP data (need 14+ days)")
            return

        print(f"\nMatching songs for state: {state} (date: {target_date})")
        match_result = select_songs(conn, state, target_date)

        stats = match_result["match_stats"]
        print(f"\nMatch stats:")
        print(f"  Candidates:  {stats['total_candidates']:,}")
        print(f"  Selected:    {stats['selected']}")
        cohesion = stats.get("cohesion_stats", {})
        if cohesion:
            print(f"  Cohesion pool:     {cohesion.get('pool_size', 0)}")
            print(f"  Mean similarity:   {cohesion.get('mean_similarity', 0):.4f}")
            print(f"  Dominant genre:    {cohesion.get('dominant_genre', 'N/A')}")
            if cohesion.get("seed_song"):
                print(f"  Seed song:         {cohesion['seed_song']}")
            if cohesion.get("relaxations", 0) > 0:
                print(f"  Relaxations:       {cohesion['relaxations']}")

        songs = match_result["songs"]
        if not songs:
            print("\nNo songs matched. Is the library classified?")
            return

        # Show neuro profile
        profile = match_result["neuro_profile"]
        print(f"\nNeuro profile:")
        print(f"  Para: {profile['para']:.2f}  Symp: {profile['symp']:.2f}  Grnd: {profile['grnd']:.2f}")

        print(f"\n{'#':<4} {'Song':<35} {'Artist':<22} {'Genre':<15} {'BPM':>5} {'Sel':>6}")
        print("-" * 95)
        for i, song in enumerate(songs, 1):
            name = (song["name"] or "")[:33]
            artist = (song["artist"] or "")[:20]
            genres = song.get("genre_tags") or []
            genre_str = (genres[0] if genres else "—")[:13]
            bpm_str = f"{song['bpm']:.0f}" if song.get("bpm") is not None else "?"
            print(f"{i:<4} {name:<35} {artist:<22} {genre_str:<15} {bpm_str:>5} {song['selection_score']:>6.3f}")
    finally:
        conn.close()


def _cmd_generate(db_path: Path) -> None:
    from datetime import date

    from matching.generator import GenerationError, generate_playlist

    # Support --date flag, default to today
    target_date = date.today().isoformat()
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            target_date = sys.argv[idx + 1]

    dry_run = "--dry-run" in sys.argv

    conn = get_connection(db_path)
    try:
        sp = None

        if not dry_run:
            from spotify.auth import get_spotify_client
            sp = get_spotify_client(conn)

            # Auto-sync recently-played before generation
            from spotify.sync import sync_recently_played
            from spotify.dedup import consolidate_duplicate_songs
            from spotify.engagement import compute_engagement_scores
            recent = sync_recently_played(conn, sp)
            if recent["plays_added"] > 0 or recent["new_songs"] > 0:
                consolidate_duplicate_songs(conn)
                compute_engagement_scores(conn)
                print(f"  Synced {recent['plays_added']} recent plays, {recent['new_songs']} new songs")

            # Auto-classify songs that crossed 2+ listens but aren't classified
            from db.queries import get_songs_needing_llm
            needs_llm = get_songs_needing_llm(conn)
            if needs_llm:
                from classification.llm_classifier import classify_songs
                print(f"  Classifying {len(needs_llm)} new song(s)...")
                stats = classify_songs(conn, provider="openai")
                if stats["classified"] > 0:
                    print(f"  Classified {stats['classified']} new songs")

        try:
            result = generate_playlist(conn, sp, date_str=target_date, dry_run=dry_run)
        except GenerationError as e:
            print(f"\nGeneration failed: {e}")
            sys.exit(1)

        # Print results
        mode = "DRY RUN" if dry_run else "LIVE"
        print(f"\n{'='*50}")
        print(f"  [{mode}] Playlist Generated")
        print(f"{'='*50}")
        print(f"  Name:   {result['name']}")
        print(f"  State:  {result['state'].replace('_', ' ').title()}")
        print(f"  Tracks: {len(result['songs'])}")

        if result["playlist_url"]:
            print(f"  URL:    {result['playlist_url']}")

        print(f"\nDescription:")
        print(f"  {result['description']}")

        profile = result["neuro_profile"]
        print(f"\nNeuro profile:")
        print(f"  Para: {profile.get('para', 0):.2f}  "
              f"Symp: {profile.get('symp', 0):.2f}  "
              f"Grnd: {profile.get('grnd', 0):.2f}")

        stats = result["match_stats"]
        print(f"\nMatch stats:")
        print(f"  Candidates: {stats['total_candidates']:,}")
        print(f"  Selected:   {stats['selected']}")
        cohesion = stats.get("cohesion_stats", {})
        if cohesion:
            print(f"  Cohesion:   mean_sim={cohesion.get('mean_similarity', 0):.4f}, "
                  f"genre={cohesion.get('dominant_genre', 'N/A')}")

        print(f"\nTracks:")
        for i, song in enumerate(result["songs"], 1):
            name = (song["name"] or "")[:40]
            artist = (song["artist"] or "")[:25]
            print(f"  {i:2d}. {name} — {artist} ({song['selection_score']:.3f})")
    finally:
        conn.close()


def _cmd_request(db_path: Path) -> None:
    """Generate a playlist from a natural language request (interactive)."""
    from db.queries import get_all_classified_songs
    from intelligence.nl_song_selector import select_songs_nl
    from intelligence.state_classifier import classify_state
    from matching.generator import GenerationError, generate_nl_playlist

    # Extract the query from argv (everything after "request" that's not a flag)
    query_parts = []
    i = sys.argv.index("request") + 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.startswith("--"):
            i += 2 if arg in ("--profile", "--date") else 1
            continue
        query_parts.append(arg)
        i += 1
    query = " ".join(query_parts)

    if not query:
        print("Usage: python main.py [--profile <name>] request \"your request here\"")
        print("Example: python main.py request \"walking to campus, want something upbeat\"")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv

    conn = get_connection(db_path)
    try:
        sp = None
        if not dry_run:
            from spotify.auth import get_spotify_client
            sp = get_spotify_client(conn)

        # Get WHOOP context for NL calibration
        recovery_score = None
        hrv = None
        state = None
        try:
            classification = classify_state(conn)
            state = classification["state"]
            metrics = classification.get("metrics", {})
            recovery_score = metrics.get("recovery_score")
            hrv = metrics.get("hrv_rmssd_milli")
        except Exception:
            pass

        # Load song library for LLM-direct selection
        all_songs = get_all_classified_songs(conn)

        # Phase 1: LLM picks songs or asks a clarifying question
        nl_result = select_songs_nl(query, all_songs, recovery_score, hrv, state)

        # If the DJ needs clarification, ask and re-select
        if nl_result.get("needs_clarification"):
            print(f"\n  {nl_result['clarifying_question']}")
            answer = input("\n  > ").strip()
            if answer:
                refined_query = f"{query}. {answer}"
                nl_result = select_songs_nl(refined_query, all_songs, recovery_score, hrv, state)
                query = refined_query

        # If still needs clarification after one round, force selection
        if nl_result.get("needs_clarification"):
            nl_result = select_songs_nl(
                f"{query}. IMPORTANT: Do not ask questions. Pick 20 songs now.",
                all_songs, recovery_score, hrv, state,
            )

        # Print DJ message
        if nl_result.get("dj_message"):
            print(f"\n  {nl_result['dj_message']}")

        try:
            result = generate_nl_playlist(conn, sp, query, dry_run=dry_run, nl_result=nl_result)
        except GenerationError as e:
            print(f"\nGeneration failed: {e}")
            sys.exit(1)

        mode = "DRY RUN" if dry_run else "LIVE"
        print(f"\n{'='*50}")
        print(f"  [{mode}] NL Playlist Generated")
        print(f"{'='*50}")
        print(f"  Name:    {result['name']}")
        print(f"  Query:   \"{query}\"")
        print(f"  Tracks:  {len(result['songs'])}")

        if result.get("playlist_url"):
            print(f"  URL:     {result['playlist_url']}")

        print(f"\nDescription:")
        print(f"  {result['description']}")

        print(f"\nTracks:")
        for i, song in enumerate(result["songs"], 1):
            name = (song.get("name") or "")[:40]
            artist = (song.get("artist") or "")[:25]
            print(f"  {i:2d}. {name} — {artist}")
    finally:
        conn.close()


def _cmd_redownload_short_clips(db_path: Path) -> None:
    from config import AUDIO_CLIPS_DIR
    from classification.audio import redownload_short_clips
    from db.queries import get_all_classified_songs

    conn = get_connection(db_path)
    try:
        songs = get_all_classified_songs(conn)
        if not songs:
            print("No classified songs.")
            return

        print(f"Checking {len(songs)} songs for short clips to replace...")
        stats = redownload_short_clips(songs, AUDIO_CLIPS_DIR)

        print(f"\nRe-download complete:")
        print(f"  Replaced:           {stats['replaced']:,}")
        print(f"  Failed:             {stats['failed']:,}")
        print(f"  Already full:       {stats['already_full']:,}")
        print(f"  Skipped (no dur):   {stats['skipped_no_duration']:,}")
    finally:
        conn.close()


def _cmd_download_audio(db_path: Path) -> None:
    from config import AUDIO_CLIPS_DIR
    from classification.audio import acquire_audio_clips

    conn = get_connection(db_path)
    try:
        if "--all" in sys.argv:
            # Download audio for ALL classified songs (for Essentia re-analysis)
            # Skip Spotify client — previews are deprecated, we use yt-dlp only
            from db.queries import get_all_classified_songs
            songs = get_all_classified_songs(conn)
        else:
            from db.queries import get_unclassified_songs
            songs = get_unclassified_songs(conn)

        if not songs:
            print("No songs to download audio for.")
            return

        print(f"Downloading audio clips for {len(songs)} songs...")
        stats = acquire_audio_clips(None, songs, AUDIO_CLIPS_DIR, skip_preview=True)

        print(f"\nAudio download complete:")
        print(f"  Downloaded:      {stats['downloaded']:,}")
        print(f"  Already cached:  {stats['already_cached']:,}")
        print(f"  Failed:          {stats['failed']:,}")
        print(f"  Spotify preview: {stats['preview_count']:,}")
        print(f"  yt-dlp fallback: {stats['ytdlp_count']:,}")
    finally:
        conn.close()


def _cmd_analyze_audio(db_path: Path) -> None:
    from config import AUDIO_CLIPS_DIR
    from db.queries import count_rows
    from classification.essentia_analyzer import analyze_all_songs

    force = "--force" in sys.argv

    conn = get_connection(db_path)
    try:
        if not AUDIO_CLIPS_DIR.exists():
            print("No audio_clips/ directory found. Run download-audio first.")
            return

        if force:
            print("Running Essentia analysis on ALL eligible songs (--force)...")
        else:
            print("Running Essentia analysis on audio clips...")
        stats = analyze_all_songs(conn, AUDIO_CLIPS_DIR, force=force)

        print(f"\nEssentia analysis complete:")
        print(f"  Analyzed:  {stats['analyzed']:,}")
        print(f"  Failed:    {stats['failed']:,}")
        print(f"  Skipped:   {stats['skipped']:,} (no audio clip)")
        print(f"\nTotal classifications: {count_rows(conn, 'song_classifications'):,}")
    finally:
        conn.close()


def _cmd_recompute_scores(db_path: Path) -> None:
    """Recompute neurological scores + re-merge energy/acousticness. No API calls.

    For essentia+llm songs: extracts original LLM energy/acousticness from
    raw_response, re-runs the merge logic with current Essentia values from DB.
    For all songs: re-runs formula + blend with current parameters.
    """
    import json

    from classification.llm_classifier import (
        _blend_neuro_scores,
        _merge_acousticness,
        _merge_energy,
    )
    from classification.profiler import compute_neurological_profile

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT sc.spotify_uri, s.name, s.artist,
                      sc.bpm, sc.felt_tempo, sc.energy, sc.acousticness,
                      sc.essentia_energy, sc.essentia_acousticness,
                      sc.instrumentalness, sc.valence, sc.mode, sc.danceability,
                      sc.genre_tags, sc.mood_tags, sc.raw_response,
                      sc.classification_source
               FROM song_classifications sc
               JOIN songs s ON sc.spotify_uri = s.spotify_uri
               WHERE sc.valence IS NOT NULL"""
        ).fetchall()

        updated = 0
        remerged = 0
        def _clamp01(v: float | None) -> float | None:
            return max(0.0, min(1.0, float(v))) if v is not None else None

        for row in rows:
            d = dict(row)
            mood_tags = json.loads(d["mood_tags"]) if d.get("mood_tags") else None
            source = d.get("classification_source") or ""

            # Extract LLM values from raw_response by matching title/artist.
            # Each raw_response contains a batch of ~5 songs — must match the right one.
            llm_para, llm_symp, llm_grounding = None, None, None
            llm_energy, llm_acousticness = None, None
            song_name = (d.get("name") or "").lower().strip()
            song_artist = (d.get("artist") or "").lower().strip()
            if d.get("raw_response"):
                try:
                    raw = json.loads(d["raw_response"])
                    for song_result in raw.get("songs", []):
                        r_title = str(song_result.get("title", "")).lower().strip()
                        r_artist = str(song_result.get("artist", "")).lower().strip()
                        if r_title == song_name and r_artist == song_artist:
                            llm_para = song_result.get("para_score")
                            llm_symp = song_result.get("symp_score")
                            llm_grounding = song_result.get("grounding_score")
                            llm_energy = song_result.get("energy")
                            llm_acousticness = song_result.get("acousticness")
                            break
                except (json.JSONDecodeError, KeyError):
                    pass

            # Re-merge energy/acousticness for essentia+llm songs.
            # Use essentia_* columns (original Essentia values) as source,
            # not energy/acousticness (which may already be merged values).
            # This makes recompute-scores idempotent.
            # If essentia_* columns are NULL (not yet backfilled via analyze-audio
            # --force), keep the existing merged values in energy/acousticness.
            energy = d.get("energy")
            acousticness = d.get("acousticness")
            if source == "essentia+llm" and llm_energy is not None:
                essentia_e = d.get("essentia_energy")
                if essentia_e is not None:
                    energy = _merge_energy(essentia_e, _clamp01(llm_energy))
                    remerged += 1
            if source == "essentia+llm" and llm_acousticness is not None:
                essentia_a = d.get("essentia_acousticness")
                if essentia_a is not None:
                    acousticness = _merge_acousticness(essentia_a, _clamp01(llm_acousticness))

            # Use felt_tempo for scoring when available
            scoring_bpm = d.get("felt_tempo") or d.get("bpm")

            # Recompute formula scores
            neuro = compute_neurological_profile(
                bpm=scoring_bpm,
                energy=energy,
                acousticness=acousticness,
                instrumentalness=d.get("instrumentalness"),
                valence=d.get("valence"),
                mode=d.get("mode"),
                danceability=d.get("danceability"),
                mood_tags=mood_tags,
            )

            llm_para = _clamp01(llm_para)
            llm_symp = _clamp01(llm_symp)
            llm_grounding = _clamp01(llm_grounding)

            # Ensemble: combine formula + LLM using structural knowledge
            blended = _blend_neuro_scores(
                neuro, llm_para, llm_symp, llm_grounding,
                bpm=d.get("bpm"), energy=energy,
            )

            conn.execute(
                """UPDATE song_classifications
                   SET energy = ?, acousticness = ?,
                       parasympathetic = ?, sympathetic = ?, grounding = ?
                   WHERE spotify_uri = ?""",
                (energy, acousticness,
                 blended["parasympathetic"], blended["sympathetic"],
                 blended["grounding"], d["spotify_uri"]),
            )
            updated += 1

        conn.commit()
        print(f"Recomputed scores for {updated:,} songs ({remerged:,} re-merged energy/acousticness)")
    finally:
        conn.close()


def _cmd_classify_songs(db_path: Path) -> None:
    from db.queries import count_rows
    from classification.llm_classifier import classify_songs

    # Support --provider flag, default to openai
    provider = "openai"
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        if idx + 1 < len(sys.argv):
            provider = sys.argv[idx + 1]
    if provider not in ("openai", "anthropic"):
        print(f"Invalid provider: {provider}. Use 'openai' or 'anthropic'.")
        sys.exit(1)

    reclassify = "--reclassify" in sys.argv

    conn = get_connection(db_path)
    try:
        if reclassify:
            print(f"Re-classifying ALL songs (provider={provider}, --reclassify)...")
        else:
            print(f"Running LLM classification (provider={provider})...")
        stats = classify_songs(conn, provider=provider, reclassify=reclassify)

        print(f"\nLLM classification complete:")
        print(f"  Classified:        {stats['classified']:,}")
        print(f"  Failed:            {stats['failed']:,}")
        print(f"  Skipped:           {stats['skipped']:,}")
        print(f"  Low confidence:    {stats['low_confidence']:,}")
        print(f"  Validation flags:  {stats['validation_flags']:,}")
        print(f"  Batches:           {stats['batches']:,}")
        print(f"\nTotal classifications: {count_rows(conn, 'song_classifications'):,}")
    finally:
        conn.close()


def _cmd_validate_classifications(db_path: Path) -> None:
    from classification.validator import validate_all_classifications

    apply = "--apply" in sys.argv

    conn = get_connection(db_path)
    try:
        flagged = validate_all_classifications(conn)

        if not flagged:
            print("No validation flags found — all classifications look clean.")
            return

        total_songs = conn.execute(
            "SELECT COUNT(*) as cnt FROM song_classifications WHERE valence IS NOT NULL"
        ).fetchone()["cnt"]
        print(f"\nValidation summary:")
        print(f"  Total classified:  {total_songs:,}")
        print(f"  Songs flagged:     {len(flagged):,} ({len(flagged) / total_songs * 100:.1f}%)")

        total_flags = sum(len(s["flags"]) for s in flagged)
        print(f"  Total flags:       {total_flags:,}")

        # Rule distribution
        rule_counts: dict[str, int] = {}
        for song in flagged:
            for f in song["flags"]:
                rule_counts[f["rule"]] = rule_counts.get(f["rule"], 0) + 1
        print(f"\nFlags by rule:")
        for rule, count in sorted(rule_counts.items(), key=lambda x: -x[1]):
            print(f"  {rule:<35} {count:,}")

        # Top 15 flagged songs
        print(f"\nTop 15 flagged songs:")
        print(f"  {'#':<4} {'Song':<30} {'Artist':<20} {'Conf':>6} {'Adj':>6} {'Flags'}")
        print(f"  {'-'*100}")
        for i, song in enumerate(flagged[:15], 1):
            name = (song["name"] or "")[:28]
            artist = (song["artist"] or "")[:18]
            flag_rules = ", ".join(f["rule"] for f in song["flags"])
            print(f"  {i:<4} {name:<30} {artist:<20} "
                  f"{song['original_confidence']:>5.2f} {song['adjusted_confidence']:>6.2f}  "
                  f"{flag_rules}")

        if apply:
            updated = 0
            for song in flagged:
                conn.execute(
                    "UPDATE song_classifications SET confidence = ? WHERE spotify_uri = ?",
                    (song["adjusted_confidence"], song["spotify_uri"]),
                )
                updated += 1
            conn.commit()
            print(f"\nApplied: updated confidence for {updated:,} songs")
        else:
            print(f"\nDry run — no changes made. Use --apply to update confidence in DB.")
    finally:
        conn.close()


def _cmd_auth_whoop(db_path: Path) -> None:
    from whoop.auth import get_authorization_url, exchange_code_for_tokens

    conn = get_connection(db_path)
    try:
        url = get_authorization_url()
        print(f"\nOpen this URL in your browser:\n{url}\n")
        code = input("Paste the authorization code: ").strip()
        exchange_code_for_tokens(code, conn)
        print("WHOOP tokens stored successfully.")
    finally:
        conn.close()


def _cmd_auth_spotify(db_path: Path) -> None:
    from spotify.auth import get_spotify_client

    conn = get_connection(db_path)
    try:
        sp = get_spotify_client(conn)
        user = sp.current_user()
        print(f"Authenticated as: {user['display_name']} ({user['id']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
