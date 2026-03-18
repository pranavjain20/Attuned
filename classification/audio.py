"""Audio clip acquisition for song classification.

Downloads 30-second audio clips via Spotify preview URLs (preferred)
or yt-dlp YouTube fallback. Clips are stored in audio_clips/ and named
by URI hash for deterministic dedup.
"""

import hashlib
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from config import AUDIO_CLIP_DURATION_SECONDS

logger = logging.getLogger(__name__)


def uri_to_filename(uri: str) -> str:
    """Convert a Spotify URI to a deterministic filename hash."""
    return hashlib.sha256(uri.encode()).hexdigest()[:16] + ".mp3"


def fetch_preview_urls(
    sp_client: Any,
    uris: list[str],
    batch_size: int = 50,
) -> dict[str, str | None]:
    """Fetch preview URLs from Spotify for a list of URIs.

    Tries batch endpoint first (sp.tracks), falls back to individual
    sp.track() calls if batch returns 403 (known Spotify API restriction).
    Returns {uri: preview_url_or_None}.
    """
    results: dict[str, str | None] = {}

    # Try batch endpoint first
    batch_works = True
    for i in range(0, len(uris), batch_size):
        batch_uris = uris[i : i + batch_size]
        track_ids = [u.split(":")[-1] for u in batch_uris]

        if batch_works:
            try:
                response = sp_client.tracks(track_ids)
                for uri, track in zip(batch_uris, response["tracks"]):
                    results[uri] = track.get("preview_url") if track else None
                continue
            except Exception:
                logger.info("Batch /tracks endpoint unavailable, falling back to individual calls")
                batch_works = False

        # Individual fallback
        for uri in batch_uris:
            track_id = uri.split(":")[-1]
            try:
                track = sp_client.track(track_id)
                results[uri] = track.get("preview_url") if track else None
            except Exception:
                logger.warning("Failed to fetch track %s", uri)
                results[uri] = None

    return results


def download_preview(url: str, output_path: Path) -> bool:
    """Download a Spotify preview MP3. Returns True on success."""
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url)
            response.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        return True
    except Exception:
        logger.warning("Failed to download preview: %s", url)
        return False


def _build_search_query(
    song_name: str,
    artist: str,
    album: str | None = None,
    search_strategy: str = "album",
) -> str:
    """Build a yt-dlp search query string for the given strategy.

    Strategies:
        "album"  — ytsearch1:{song} - {artist} {album}  (more specific)
        "ytmusic" — ytmsearch:{song} - {artist}  (YouTube Music index)
        "basic"  — ytsearch1:{song} - {artist}  (original fallback)
    """
    base = f"{song_name} - {artist}"
    if search_strategy == "album" and album:
        return f"ytsearch1:{base} {album}"
    if search_strategy == "ytmusic":
        return f"ytmsearch:{base}"
    return f"ytsearch1:{base}"


def _find_ytdlp_binary() -> str | None:
    """Locate yt-dlp, preferring the venv copy."""
    ytdlp_bin = shutil.which("yt-dlp", path=str(Path(sys.executable).parent))
    if not ytdlp_bin:
        ytdlp_bin = shutil.which("yt-dlp")
    return ytdlp_bin


def download_from_youtube(
    song_name: str,
    artist: str,
    output_path: Path,
    album: str | None = None,
    search_strategy: str = "album",
) -> bool:
    """Search YouTube and download full audio via yt-dlp.

    Args:
        song_name: Track name.
        artist: Artist name.
        output_path: Where to save the MP3.
        album: Album name (used by "album" strategy for more specific queries).
        search_strategy: "album" (default), "ytmusic", or "basic".

    Returns True on success.
    """
    query = _build_search_query(song_name, artist, album, search_strategy)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = output_path.with_suffix(".ytdl.mp3")

    ytdlp_bin = _find_ytdlp_binary()
    if not ytdlp_bin:
        logger.error("yt-dlp not installed — cannot download from YouTube")
        return False

    try:
        result = subprocess.run(
            [
                ytdlp_bin,
                query,
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "5",
                "--output", str(temp_path),
                "--no-playlist",
                "--quiet",
                "--no-warnings",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.warning("yt-dlp failed for '%s': %s", query, result.stderr[:200])
            return False

        # yt-dlp may append extra suffixes — find the actual output file
        actual_file = _find_ytdlp_output(temp_path)
        if actual_file and actual_file.exists():
            actual_file.rename(output_path)
            return True

        logger.warning("yt-dlp output file not found for '%s'", query)
        return False

    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp timed out for '%s'", query)
        return False
    except FileNotFoundError:
        logger.error("yt-dlp not installed — cannot download from YouTube")
        return False


def download_from_youtube_verified(
    song_name: str,
    artist: str,
    output_path: Path,
    expected_duration_s: float,
    album: str | None = None,
    num_results: int = 5,
    tolerance_s: float = 15.0,
) -> bool:
    """Search YouTube for multiple results and download the best duration match.

    Instead of blindly taking the first result, fetches metadata for N results
    and picks the one whose duration is closest to expected_duration_s.
    Only downloads if the best match is within tolerance_s.

    Returns True on success.
    """
    ytdlp_bin = _find_ytdlp_binary()
    if not ytdlp_bin:
        logger.error("yt-dlp not installed — cannot download from YouTube")
        return False

    base_query = f"{song_name} - {artist}"
    if album:
        base_query += f" {album}"
    search_query = f"ytsearch{num_results}:{base_query}"

    # Step 1: Get metadata for N search results
    try:
        result = subprocess.run(
            [
                ytdlp_bin,
                search_query,
                "--dump-json",
                "--no-playlist",
                "--quiet",
                "--no-warnings",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("yt-dlp metadata search failed: %s", result.stderr[:200])
            return False
    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp metadata search timed out for '%s'", base_query)
        return False

    # Parse JSON lines (one per result)
    import json as _json

    candidates: list[dict] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            info = _json.loads(line)
            duration = info.get("duration")
            if duration is not None:
                candidates.append({
                    "url": info.get("webpage_url") or info.get("url"),
                    "id": info.get("id"),
                    "title": info.get("title", ""),
                    "duration": float(duration),
                    "delta": abs(float(duration) - expected_duration_s),
                })
        except _json.JSONDecodeError:
            continue

    if not candidates:
        logger.warning("No YouTube results for '%s'", base_query)
        return False

    # Step 2: Pick the candidate with smallest duration delta
    candidates.sort(key=lambda c: c["delta"])
    best = candidates[0]

    if best["delta"] > tolerance_s:
        logger.info(
            "Best YouTube match for '%s' is %.1fs off (%.1fs vs %.1fs) — skipping",
            base_query, best["delta"], best["duration"], expected_duration_s,
        )
        return False

    logger.info(
        "Best match: '%s' (%.1fs, delta=%.1fs)",
        best["title"], best["duration"], best["delta"],
    )

    # Step 3: Download the best match by URL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".ytdl.mp3")

    try:
        dl_result = subprocess.run(
            [
                ytdlp_bin,
                best["url"] or f"https://www.youtube.com/watch?v={best['id']}",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "5",
                "--output", str(temp_path),
                "--no-playlist",
                "--quiet",
                "--no-warnings",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if dl_result.returncode != 0:
            logger.warning("yt-dlp download failed: %s", dl_result.stderr[:200])
            return False

        actual_file = _find_ytdlp_output(temp_path)
        if actual_file and actual_file.exists():
            actual_file.rename(output_path)
            return True

        logger.warning("yt-dlp output file not found after download")
        return False

    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp download timed out for '%s'", best["title"])
        return False


def _find_ytdlp_output(expected_path: Path) -> Path | None:
    """Find the actual yt-dlp output file, accounting for suffix variations."""
    # yt-dlp sometimes produces .ytdl.mp3, sometimes .ytdl.mp3.mp3, etc.
    parent = expected_path.parent
    stem = expected_path.stem.replace(".ytdl", "")  # base stem
    for candidate in parent.iterdir():
        if candidate.name.startswith(expected_path.stem) and candidate.suffix == ".mp3":
            return candidate
    # Fall back to exact match
    if expected_path.exists():
        return expected_path
    return None


def acquire_audio_clips(
    sp_client: Any,
    songs: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, int]:
    """Orchestrate audio clip acquisition for a list of songs.

    Tries Spotify preview first, falls back to yt-dlp.
    Skips already-cached clips (idempotent re-runs).

    Args:
        sp_client: Authenticated Spotipy client.
        songs: List of song dicts with spotify_uri, name, artist.
        output_dir: Directory to store audio clips.

    Returns:
        Summary stats: {downloaded, failed, already_cached, preview_count, ytdlp_count}
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "downloaded": 0,
        "failed": 0,
        "already_cached": 0,
        "preview_count": 0,
        "ytdlp_count": 0,
    }

    # Check which songs already have cached clips
    uris_needing_download: list[dict[str, Any]] = []
    for song in songs:
        clip_path = output_dir / uri_to_filename(song["spotify_uri"])
        if clip_path.exists() and clip_path.stat().st_size > 0:
            stats["already_cached"] += 1
        else:
            uris_needing_download.append(song)

    if not uris_needing_download:
        return stats

    # Batch-fetch preview URLs for songs needing download
    uris = [s["spotify_uri"] for s in uris_needing_download]
    preview_urls = fetch_preview_urls(sp_client, uris)

    for song in uris_needing_download:
        uri = song["spotify_uri"]
        clip_path = output_dir / uri_to_filename(uri)

        # Try Spotify preview first
        preview_url = preview_urls.get(uri)
        if preview_url and download_preview(preview_url, clip_path):
            stats["downloaded"] += 1
            stats["preview_count"] += 1
            logger.info("Downloaded preview: %s — %s", song["name"], song["artist"])
            continue

        # Fallback to yt-dlp
        if download_from_youtube(song["name"], song["artist"], clip_path, album=song.get("album")):
            stats["downloaded"] += 1
            stats["ytdlp_count"] += 1
            logger.info("Downloaded via yt-dlp: %s — %s", song["name"], song["artist"])
            continue

        stats["failed"] += 1
        logger.warning("Failed both sources: %s — %s", song["name"], song["artist"])

    return stats
