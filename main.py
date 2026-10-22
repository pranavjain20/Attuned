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
    "download-audio": "Download audio clips (Spotify preview + yt-dlp)",
    "redownload-short-clips": "Replace short preview clips with full YouTube downloads",
    "analyze-audio": "Run Essentia analysis on audio clips (--tempo-only: just backfill tempo readings)",
    "classify-songs": "Run LLM classification on unclassified songs",
    "validate-classifications": "Validate existing classifications and flag suspicious songs",
    "fetch-soundcharts-tempos": "Fetch Soundcharts tempo for engaged songs with no audio clip (--limit N, default 50; --force re-asks songs answered with no tempo)",
    "update-tempos": "Decide every song's scored tempo from its stored readings (no API calls)",
    "set-tempo": "Pin a song's tempo by hand: set-tempo <spotify_uri|title> <bpm>",
    "recompute-scores": "Recompute neuro scores from existing DB data (no API calls)",
    "match-songs": "Preview the day's playlist songs, no Spotify (testing/preview)",
    "generate": "Generate today's playlist from WHOOP state + matched songs",
    "request": "Generate a playlist from a natural language request",
    "backfill-release-years": "Backfill release_year from Spotify for songs missing it",
    "sync-whoop-history": "Pull full WHOOP recovery + sleep history",
    "feeling-score": "Attuned 0-100 feeling score for a day (--date YYYY-MM-DD, --json)",
    "playlist-json": "Playlist + why-lines as JSON, read-only (--date D, or --from A --to B --out DIR)",
    "build-site": "Write the showcase page, read-only (--days 30, --end YYYY-MM-DD, --out web/dist)",
    "publish-playlists": "Make public Spotify playlists for the page's latest days (--recent 3, max 3; --dry-run)",
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
    elif command == "fetch-soundcharts-tempos":
        _cmd_fetch_soundcharts_tempos(db_path)
    elif command == "update-tempos":
        _cmd_update_tempos(db_path)
    elif command == "set-tempo":
        _cmd_set_tempo(db_path)
    elif command == "recompute-scores":
        _cmd_recompute_scores(db_path)
    elif command == "sync-whoop-history":
        _cmd_sync_whoop_history(db_path)
    elif command == "feeling-score":
        _cmd_feeling_score(db_path)
    elif command == "playlist-json":
        _cmd_playlist_json(db_path)
    elif command == "build-site":
        _cmd_build_site(db_path)
    elif command == "publish-playlists":
        _cmd_publish_playlists(db_path)
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


def _flag_value(flag: str) -> str | None:
    """Value after `flag` in argv, None if the flag is absent; exits if the value is missing."""
    if flag not in sys.argv:
        return None
    idx = sys.argv.index(flag)
    if idx + 1 >= len(sys.argv):
        print(f"Error: {flag} requires a value")
        sys.exit(1)
    return sys.argv[idx + 1]


def _parse_date_flag(flag: str = "--date", default_today: bool = True) -> str | None:
    """`flag` YYYY-MM-DD from argv (default today, or None); exits with a message if malformed."""
    from datetime import date

    target_date = _flag_value(flag)
    if target_date is None:
        return date.today().isoformat() if default_today else None
    try:
        date.fromisoformat(target_date)
    except ValueError:
        print(f"Error: {flag} must be YYYY-MM-DD, got {target_date!r}")
        sys.exit(1)
    return target_date


def _cmd_playlist_json(db_path: Path) -> None:
    """A day's playlist + why-lines as JSON. Read-only: no Spotify, no DB writes.

    --date D prints one day. --from A --to B --out DIR replays the range oldest
    first, chaining rotation between days, and writes DIR/<date>.json per day.
    """
    import json

    from matching.day_playlist import build_day_playlist, build_day_playlists
    from matching.generator import GenerationError

    start = _parse_date_flag("--from", default_today=False)
    end = _parse_date_flag("--to", default_today=False)
    if start is None and end is None:
        target_date = _parse_date_flag()
        # Keep stdout pure JSON: the pipeline's INFO logs would bury it.
        logging.getLogger().setLevel(logging.WARNING)
        conn = get_connection(db_path)
        try:
            playlist = build_day_playlist(conn, target_date)
        except GenerationError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            conn.close()
        print(json.dumps(playlist, indent=2, ensure_ascii=False))
        return

    out = _flag_value("--out")
    if start is None or end is None or out is None or "--date" in sys.argv:
        print("Error: a range needs --from YYYY-MM-DD --to YYYY-MM-DD --out DIR (and no --date)")
        sys.exit(1)
    if start > end:
        print(f"Error: --from {start} must be on or before --to {end}")
        sys.exit(1)

    logging.getLogger().setLevel(logging.WARNING)
    conn = get_connection(db_path)
    try:
        results = build_day_playlists(conn, start, end)
    finally:
        conn.close()

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    for result in results:
        if result["error"]:
            failed = True
            print(f"Error: {result['date']}: {result['error']}", file=sys.stderr)
            continue
        path = out_dir / f"{result['date']}.json"
        path.write_text(json.dumps(result["playlist"], indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote {path}")
    if failed:
        sys.exit(1)


def _site_window_flags() -> tuple[int, str]:
    """(--days, default 30; --end, default today): the page's window, shared so publishing sees the same days."""
    raw_days = _flag_value("--days") or "30"
    if not raw_days.isdigit() or int(raw_days) < 1:
        print(f"Error: --days must be a whole number of at least 1, got {raw_days!r}")
        sys.exit(1)
    return int(raw_days), _parse_date_flag("--end")


def _cmd_build_site(db_path: Path) -> None:
    """Write OUT/index.html: the showcase page for every WHOOP day in the last --days up to --end.

    Read-only: no Spotify API calls and no DB writes. Album art comes from
    Spotify's public oEmbed endpoint, cached in web/.art_cache.json.
    """
    import time

    from web import site

    n_days, end_date = _site_window_flags()
    out_dir = Path(_flag_value("--out") or site.WEB_DIR / "dist")

    started = time.monotonic()
    logging.getLogger().setLevel(logging.WARNING)
    art = site.OembedArtCache()
    conn = get_connection(db_path)
    try:
        frozen = site.load_frozen(site.PLAYLISTS_PATH)
        days = site.build_site_days(conn, end_date, n_days, art_lookup=art,
                                    published=site.load_published(), frozen=frozen)
        site.save_frozen(frozen, site.PLAYLISTS_PATH)
    finally:
        conn.close()
        art.save()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(site.render(site.TEMPLATE_PATH.read_text(), days))
    with_playlist = sum(1 for day in days if day["playlist"])
    print(f"Wrote {out_path}: {len(days)} days, {with_playlist} with playlists "
          f"({time.monotonic() - started:.0f}s)")


def _cmd_publish_playlists(db_path: Path) -> None:
    """Create public Spotify playlists for the page's --recent latest days (default and max 3).

    Replays the same --days/--end window as build-site, so each playlist is
    exactly what the page shows; songs Spotify no longer plays are swapped for
    the day's spares first. Records them in web/published.json; re-running never
    makes a second playlist for a recorded day, it only updates changed tracks,
    name or description. --dry-run prints the plan without logging in to
    Spotify (so without the availability check) or writing anything.
    """
    from spotify.auth import SpotifyRateLimitError, get_spotify_client
    from spotify.playlist import SpotifyPlaylistError
    from web import publish, site

    raw_recent = _flag_value("--recent") or str(publish.MAX_RECENT)
    if not raw_recent.isdigit():
        print(f"Error: --recent must be a whole number, got {raw_recent!r}")
        sys.exit(1)
    n_recent, allow_more = int(raw_recent), "--allow-more" in sys.argv
    try:
        publish.check_recent(n_recent, allow_more)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    n_days, end_date = _site_window_flags()
    dry_run = "--dry-run" in sys.argv

    logging.getLogger().setLevel(logging.WARNING)
    conn = get_connection(db_path)
    try:
        dates = site.window_dates(conn, end_date, n_days)
        frozen = site.load_frozen(site.PLAYLISTS_PATH)
        playlists = site.replay_playlists(conn, dates, frozen=frozen)
        site.save_frozen(frozen, site.PLAYLISTS_PATH)
        days = [{"date": date, "playlist": playlists.get(date)} for date in dates]
        published = site.load_published(site.PUBLISHED_PATH)
        sp, unavailable = None, set()
        if not dry_run:
            sp = get_spotify_client(conn)
            unavailable = publish.find_unavailable(conn, sp, publish.recent_days(days, n_recent, allow_more))
        steps = publish.plan_publish(days, published, n_recent, allow_more, unavailable)
        for step in steps:
            changes = f" ({', '.join(step['changes'])})" if step["changes"] else ""
            print(f"  {step['date']}  {step['action'] + changes:<25}  {step['name']} "
                  f"({len(step['track_uris'])} songs)")
        if dry_run:
            print("Dry run: nothing written, Spotify not contacted (song availability not checked).")
            return
        if all(step["action"] == "unchanged" for step in steps):
            print("Nothing to publish.")
            return
        published = publish.publish_steps(sp, steps, published, site.PUBLISHED_PATH)
    except (SpotifyRateLimitError, SpotifyPlaylistError) as e:
        print(f"Error: {e}\nStopped; {site.PUBLISHED_PATH} lists what was published. Re-run to finish.")
        sys.exit(1)
    finally:
        conn.close()
    for step in steps:
        print(f"  {step['date']}  {published[step['date']]['url']}")


def _cmd_feeling_score(db_path: Path) -> None:
    """Print the feeling score for --date (default today); --json prints the page data contract."""
    import json

    from intelligence.feeling_score import build_page_day

    target_date = _parse_date_flag()

    # Scoring replays every earlier day; their per-day INFO logs would bury the output.
    logging.getLogger("intelligence").setLevel(logging.WARNING)
    conn = get_connection(db_path)
    try:
        day = build_page_day(conn, target_date)
    finally:
        conn.close()

    if "--json" in sys.argv:
        print(json.dumps(day, indent=2, ensure_ascii=False))
        return

    attuned, whoop = day["attuned"], day["whoop"]
    print(f"\n{target_date}  WHOOP {whoop['recovery']} ({whoop['band']})")
    if attuned["score"] is None:
        print(f"Attuned: no score — {attuned['reason']}")
        return
    print(f"Attuned {attuned['score']} ({attuned['band']}) · {attuned['state_label']}")
    print(f"\n{attuned['headline']}")
    for line in attuned["explanation"]:
        print(f"  - {line}")


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
    from config import MAX_PLAYLIST_SIZE
    from matching.generator import GenerationError, select_day_songs

    target_date = _parse_date_flag()

    conn = get_connection(db_path)
    try:
        # Same path as the daily playlist (before Spotify's availability check)
        try:
            match_result = select_day_songs(conn, target_date)
        except GenerationError as e:
            print(f"\nCannot match songs — {e}")
            return
        position = match_result["position"]
        print(f"\nAttuned state: {match_result['state']} "
              f"(position: {'no score' if position is None else f'{position:.2f}'}, date: {target_date})")

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

        songs = match_result["songs"][:MAX_PLAYLIST_SIZE]

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
            tempo_str = f"{song['tempo']:.0f}" if song.get("tempo") is not None else "?"
            print(f"{i:<4} {name:<35} {artist:<22} {genre_str:<15} {tempo_str:>5} {song['selection_score']:>6.3f}")
    finally:
        conn.close()


def _cmd_generate(db_path: Path) -> None:
    from matching.generator import GenerationError, generate_playlist

    target_date = _parse_date_flag()

    dry_run = "--dry-run" in sys.argv

    conn = get_connection(db_path)
    try:
        # Auto-sync WHOOP before generation (so today's recovery is always fresh)
        from whoop.sync import sync_today
        try:
            sync_today(conn)
        except Exception as e:
            logger.warning("WHOOP sync failed (continuing with cached data): %s", e)

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
    from datetime import date

    from db.queries import get_all_classified_songs
    from intelligence.dj_context import attuned_context
    from intelligence.nl_song_selector import select_songs_nl
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

        # Today's Attuned body context calibrates the DJ
        body_context = attuned_context(conn, date.today().isoformat())

        # Load song library for LLM-direct selection
        all_songs = get_all_classified_songs(conn)

        # Phase 1: LLM picks songs or asks a clarifying question
        nl_result = select_songs_nl(query, all_songs, body_context)

        # If the DJ needs clarification, ask and re-select
        if nl_result.get("needs_clarification"):
            print(f"\n  {nl_result['clarifying_question']}")
            answer = input("\n  > ").strip()
            if answer:
                refined_query = f"{query}. {answer}"
                nl_result = select_songs_nl(refined_query, all_songs, body_context)
                query = refined_query

        # If still needs clarification after one round, force selection
        if nl_result.get("needs_clarification"):
            nl_result = select_songs_nl(
                f"{query}. IMPORTANT: Do not ask questions. Pick 20 songs now.",
                all_songs, body_context,
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

        if "--tempo-only" in sys.argv:
            from classification.essentia_analyzer import measure_missing_tempo_readings

            print("Measuring tempo readings for classified songs that have none...")
            stats = measure_missing_tempo_readings(conn, AUDIO_CLIPS_DIR)
            print(f"\nTempo readings: {stats['measured']:,} measured, "
                  f"{stats['failed']:,} failed, {stats['skipped']:,} without a clip")
            print("Next: python main.py update-tempos && python main.py recompute-scores")
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


def _cmd_fetch_soundcharts_tempos(db_path: Path) -> None:
    from classification.soundcharts import backfill_soundcharts_tempos, fetch_soundcharts_song
    from config import get_soundcharts_api_key, get_soundcharts_app_id

    limit_value = _flag_value("--limit") or "50"
    if not limit_value.isdigit() or int(limit_value) < 1:
        print(f"Error: --limit must be a positive whole number, got {limit_value!r}")
        sys.exit(1)

    app_id, api_key = get_soundcharts_app_id(), get_soundcharts_api_key()
    conn = get_connection(db_path)
    try:
        stats = backfill_soundcharts_tempos(
            conn, lambda uri: fetch_soundcharts_song(uri, app_id, api_key), int(limit_value),
            force="--force" in sys.argv,
        )
        print(f"Soundcharts: {stats['calls']:,} calls, {stats['stored']:,} tempos stored, "
              f"{stats['no_tempo']:,} without a tempo")
        print(f"  Quota remaining: {stats['quota_remaining']}")
        if stats["stopped"]:
            print(f"  Stopped early: {stats['stopped']}")
        print("Next: python main.py update-tempos && python main.py recompute-scores")
    finally:
        conn.close()


def _cmd_update_tempos(db_path: Path) -> None:
    from classification.tempo import update_tempos

    conn = get_connection(db_path)
    try:
        stats = update_tempos(conn)
        print(f"Decided tempo for {stats['updated']:,} songs")
        for label, counts in (("source", stats["by_source"]), ("confidence", stats["by_confidence"])):
            print(f"  By {label}: " + ", ".join(f"{k} {v:,}" for k, v in sorted(counts.items())))
        print("Next: python main.py recompute-scores")
    finally:
        conn.close()


def _cmd_set_tempo(db_path: Path) -> None:
    from classification.tempo import set_manual_tempo

    if len(sys.argv) != 4:
        print('Usage: python main.py set-tempo <spotify_uri|"exact title"> <bpm>')
        sys.exit(1)
    song, bpm_text = sys.argv[2], sys.argv[3]
    try:
        bpm = float(bpm_text)
    except ValueError:
        print(f"Error: bpm must be a number, got {bpm_text!r}")
        sys.exit(1)

    conn = get_connection(db_path)
    try:
        try:
            match = set_manual_tempo(conn, song, bpm)[0]
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        print(f"{match['name']} — {match['artist']}: tempo {match['old_tempo']} → {bpm:g} (manual)")
        print("Next: python main.py recompute-scores")
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
    from classification.llm_response import find_llm_song_result
    from classification.profiler import compute_neurological_profile, scoring_tempo

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT sc.spotify_uri, s.name, s.artist,
                      sc.tempo, sc.bpm, sc.felt_tempo, sc.energy, sc.acousticness,
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
            llm_result = find_llm_song_result(d.get("raw_response"), d.get("name"), d.get("artist")) or {}
            llm_para = llm_result.get("para_score")
            llm_symp = llm_result.get("symp_score")
            llm_grounding = llm_result.get("grounding_score")
            llm_energy = llm_result.get("energy")
            llm_acousticness = llm_result.get("acousticness")

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

            # Score at the corrected tempo (written by update-tempos, never here)
            tempo = scoring_tempo(d)

            # Recompute formula scores
            neuro = compute_neurological_profile(
                bpm=tempo,
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
                bpm=tempo, energy=energy,
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
