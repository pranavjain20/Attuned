"""Download audio clips for a specific batch of songs (for parallel execution)."""

import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from classification.audio import download_from_youtube_verified, uri_to_filename
from db.schema import get_connection
from db.queries import get_all_classified_songs


def main():
    batch_file = sys.argv[1]  # /tmp/batch1_uris.json or /tmp/batch2_uris.json
    batch_name = Path(batch_file).stem

    with open(batch_file) as f:
        target_uris = set(json.load(f))

    conn = get_connection("db/komal.db")
    all_songs = get_all_classified_songs(conn)
    songs = [s for s in all_songs if s["spotify_uri"] in target_uris]
    conn.close()

    clip_dir = Path("audio_clips")
    clip_dir.mkdir(exist_ok=True)

    downloaded = 0
    failed = 0
    skipped = 0

    for idx, song in enumerate(songs):
        clip_path = clip_dir / uri_to_filename(song["spotify_uri"])

        if clip_path.exists() and clip_path.stat().st_size > 500:
            skipped += 1
            continue

        if not song.get("duration_ms"):
            failed += 1
            continue

        if idx > 0:
            time.sleep(15)

        expected_s = song["duration_ms"] / 1000.0
        if download_from_youtube_verified(
            song["name"], song["artist"], clip_path,
            expected_duration_s=expected_s, album=song.get("album"),
        ):
            downloaded += 1
        else:
            failed += 1

        if (idx + 1) % 50 == 0:
            print(f"[{batch_name}] {idx+1}/{len(songs)}: {downloaded} downloaded, {failed} failed, {skipped} skipped", flush=True)

    print(f"[{batch_name}] DONE: {downloaded} downloaded, {failed} failed, {skipped} skipped", flush=True)


if __name__ == "__main__":
    main()
