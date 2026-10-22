"""The static showcase site: one page that steps through recent days.

Each day shows the Attuned feeling score next to WHOOP's recovery, why they
differ, and the playlist built for that morning. Everything the page says is
worked out here; the page's JavaScript only renders and handles clicks.
"""

import json
import logging
import math
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import date as date_cls, timedelta
from pathlib import Path

from db.queries import get_recoveries_in_range, get_song, get_song_classifications
from intelligence.feeling_score import HEART_SIGNALS, band, build_page_day, compute_composite_history
from matching.day_playlist import build_day_playlist, build_day_playlists
from matching.generator import GenerationError

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
TEMPLATE_PATH = WEB_DIR / "template.html"
ART_CACHE_PATH = WEB_DIR / ".art_cache.json"
PUBLISHED_PATH = WEB_DIR / "published.json"
DATA_PLACEHOLDER = "__ATTUNED_DATA__"

NOTABLE_DATES = ("2026-04-07", "2026-04-08")
AGREE_WITHIN_POINTS = 10      # a smaller gap reads as "roughly agree"
BIG_GAP_POINTS = 20           # a gap this big gets called out under the rings
MAX_MOODS_PER_TRACK = 3
MAX_GENRES_PER_TRACK = 2

OEMBED_URL = "https://open.spotify.com/oembed?url={}"
ART_THROTTLE_S = 0.25
ART_TIMEOUT_S = 15

ArtLookup = Callable[[str], str | None]

# How each signal reads in a sentence: (when it helped, when it hurt).
PHRASE = {
    "deep_sleep_z": ("more deep sleep", "less deep sleep"),
    "deep_ratio_z": ("a bigger share of deep sleep", "a smaller share of deep sleep"),
    "rem_sleep_z": ("more REM", "less REM"),
    "total_sleep_z": ("a longer night", "a shorter night"),
    "sleep_efficiency_z": ("less broken sleep", "more broken sleep"),
    "sleep_debt_z": ("less sleep debt", "built-up sleep debt"),
    "hrv_z": ("a higher HRV", "a lower HRV"),
    "hrv_delta_z": ("HRV up since yesterday", "HRV down since yesterday"),
    "hrv_trend_z": ("HRV trending up this week", "HRV drifting down this week"),
    "rhr_z": ("a lower resting heart rate", "a higher resting heart rate"),
    "rhr_delta_z": ("resting heart rate down since yesterday", "resting heart rate up since yesterday"),
}

MOOD_WORD = {"green": "good", "yellow": "middling", "red": "low"}

BERNARDI_2006 = ["Bernardi 2006", "https://doi.org/10.1136/hrt.2005.064600"]
PLAN = {
    "rest": {
        "does": "built to help you settle", "kinds": "Slower, softer",
        "why": "Studies find slower music tends to bring heart rate down and calm the body.",
        "cites": [BERNARDI_2006, ["Ooishi 2017", "https://doi.org/10.1371/journal.pone.0189075"]],
    },
    "energy": {
        "does": "built to give you a lift", "kinds": "Brighter, faster",
        "why": "Studies find faster music tends to raise heart rate and breathing, in step with the tempo.",
        "cites": [BERNARDI_2006],
    },
    "grounding": {
        "does": "built to keep you level", "kinds": "Steady, familiar",
        "why": "Studies find music you love triggers the brain's reward system, "
               "so familiar songs land harder emotionally.",
        "cites": [["Salimpoor 2011", "https://doi.org/10.1038/nn.2726"],
                  ["Hennessy 2025", "https://doi.org/10.1002/hbm.70181"]],
    },
}


# ---------------------------------------------------------------------------
# Copy: why Attuned and WHOOP differ
# ---------------------------------------------------------------------------

def _round_half_up(x: float) -> int:
    """Round like JavaScript's Math.round (Python's round() sends 0.5 to the even neighbour)."""
    return math.floor(x + 0.5)


def join_and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(items) < 2:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def reason_line(attuned: dict, whoop: dict) -> str:
    """One sentence naming what moved the score, leading with the side that explains it."""
    if attuned.get("score") is None:
        return attuned.get("reason") or "No feeling score for this day."
    good, bad = [], []
    for driver in attuned.get("drivers") or []:
        phrase = PHRASE.get(driver["signal"])
        if phrase is None:
            continue
        if driver["effect"] == "up":
            good.append(phrase[0])
        else:
            bad.append(phrase[1])
    lead, other = (bad, good) if attuned["score"] <= (whoop.get("recovery") or 0) else (good, bad)
    if not lead:
        lead, other = other, []
    if not lead:
        return "A night close to your usual."
    line = join_and(lead) + (f", despite {join_and(other)}" if other else " than usual")
    return _capitalize_first(line) + "."


def _gap_note(attuned: dict, whoop: dict) -> str:
    """The small line under the two rings; blank when either score is missing."""
    if attuned.get("score") is None or whoop.get("recovery") is None:
        return ""
    gap = abs(whoop["recovery"] - attuned["score"])
    if gap >= BIG_GAP_POINTS:
        return f"A {gap}-point gap: body readiness and mood can point different ways."
    return f"Within {gap} points: today the two scores roughly agree."


def compare_copy(attuned: dict, whoop: dict) -> dict:
    """{"title", "line", "note"}: why Attuned differs from WHOOP today, in a title + one sentence."""
    note = _gap_note(attuned, whoop)
    if attuned.get("score") is None:
        return {"title": "No Attuned score today", "line": attuned.get("reason") or "", "note": note}

    gap = _round_half_up(attuned["score"] - (whoop.get("recovery") or 0))
    heart_good, heart_bad, sleep_good, sleep_bad = [], [], [], []
    for driver in attuned.get("drivers") or []:
        phrase = PHRASE.get(driver["signal"])
        if phrase is None:
            continue
        up, heart = driver["effect"] == "up", driver["signal"] in HEART_SIGNALS
        if heart:
            (heart_good if up else heart_bad).append(phrase[0] if up else phrase[1])
        else:
            (sleep_good if up else sleep_bad).append(phrase[0] if up else phrase[1])

    if abs(gap) < AGREE_WITHIN_POINTS:
        return {"title": "WHOOP and Attuned roughly agree today", "line": reason_line(attuned, whoop),
                "note": note}
    worse = gap < 0
    title = f"Why you'll likely feel {'worse' if worse else 'better'} than WHOOP says"
    if worse and heart_good and sleep_bad:
        line = (f"You had {join_and(heart_good)}, which WHOOP leans on. But you also had "
                f"{join_and(sleep_bad)}, which Attuned weighs more for how you'll feel.")
    elif not worse and heart_bad and sleep_good:
        line = (f"You had {join_and(heart_bad)}, which pulls WHOOP down. But you also had "
                f"{join_and(sleep_good)}, which Attuned weighs more for how you'll feel.")
    else:
        line = reason_line(attuned, whoop)
    return {"title": title, "line": line, "note": note}


# ---------------------------------------------------------------------------
# Copy: what the playlist is and why
# ---------------------------------------------------------------------------

def _ranked(tag_lists: list[list[str]]) -> list[tuple[str, int]]:
    """Tags by how many lists they appear in, most first; ties keep first-seen order."""
    return Counter(tag for tags in tag_lists for tag in tags).most_common()


def kinds_line(tracks: list[dict]) -> str:
    """e.g. 'calm, romantic Bollywood songs from your library'."""
    moods = [tag for tag, _ in _ranked([t.get("moods") or [] for t in tracks])[:2]]
    genres = _ranked([(t.get("genres") or [])[:1] for t in tracks])
    if not genres:
        genre = ""
    elif genres[0][1] >= len(tracks) / 2:
        genre = genres[0][0]
    else:
        genre = " and ".join(tag for tag, _ in genres[:2])
    genre = re.sub(r"\bbollywood\b", "Bollywood", genre)
    return (", ".join(moods) + " " if moods else "") + (genre + " " if genre else "") + "songs from your library"


def playlist_summary(playlist: dict, attuned: dict) -> dict:
    """{"lead", "kinds", "why", "cites": [[label, url]]} for the playlist card."""
    plan = PLAN.get(attuned.get("state"), PLAN["grounding"])
    mood = MOOD_WORD.get(attuned.get("band") or band(attuned.get("score")), "okay")
    return {
        "lead": f"You'll likely feel {mood} today, so this playlist is {plan['does']}.",
        "kinds": f"{plan['kinds']}, mostly {kinds_line(playlist['tracks'])}.",
        "why": plan["why"],
        "cites": [list(cite) for cite in plan["cites"]],
    }


def format_duration(ms: int | None) -> str:
    """'3:05'; blank when unknown."""
    if not ms:
        return ""
    seconds = _round_half_up(ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_total_time(tracks: list[dict]) -> str:
    """'48 min' or '1 hr 5 min'; tracks with no known length count as zero."""
    minutes = _round_half_up(sum(t.get("duration_ms") or 0 for t in tracks) / 60_000)
    return f"{minutes // 60} hr {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


# ---------------------------------------------------------------------------
# Track enrichment: album art, length, mood/genre tags
# ---------------------------------------------------------------------------

def enrich_track(conn: sqlite3.Connection, track: dict, art_lookup: ArtLookup) -> dict:
    """A copy of track with art, duration_ms, duration ("m:ss"), moods and genres added."""
    uri = "spotify:track:" + track["spotify_url"].rsplit("/", 1)[-1]
    song = get_song(conn, uri) or {}
    classifications = get_song_classifications(conn, [uri])
    tags = classifications[0] if classifications else {}
    duration_ms = song.get("duration_ms")
    return {
        **track,
        "art": art_lookup(track["spotify_url"]),
        "duration_ms": duration_ms,
        "duration": format_duration(duration_ms),
        "moods": (tags.get("mood_tags") or [])[:MAX_MOODS_PER_TRACK],
        "genres": (tags.get("genre_tags") or [])[:MAX_GENRES_PER_TRACK],
    }


class OembedArtCache:
    """Album art URLs from Spotify's public oEmbed endpoint (no login), cached on disk.

    A track Spotify answers for (even with "not found") is cached. A network
    failure is not cached, and stops further fetches for the rest of this run so
    an offline build doesn't wait out a timeout per track.
    """

    def __init__(self, path: Path = ART_CACHE_PATH, fetch: Callable = urllib.request.urlopen,
                 throttle_s: float = ART_THROTTLE_S) -> None:
        self.path = path
        self.fetch = fetch
        self.throttle_s = throttle_s
        self.offline = False
        self.cache = self._load()

    def _load(self) -> dict[str, str | None]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except ValueError:
            logger.warning("Art cache %s is unreadable; starting empty", self.path)
            return {}

    def __call__(self, track_url: str) -> str | None:
        if track_url in self.cache:
            return self.cache[track_url]
        if self.offline:
            return None
        url = OEMBED_URL.format(urllib.parse.quote(track_url, safe=""))
        try:
            with self.fetch(url, timeout=ART_TIMEOUT_S) as response:
                art = json.loads(response.read()).get("thumbnail_url")
        except urllib.error.HTTPError as e:
            logger.warning("No album art for %s (HTTP %s)", track_url, e.code)
            art = None
        except (urllib.error.URLError, OSError) as e:
            logger.warning("Album art unreachable (%s); skipping art for the rest of this build", e)
            self.offline = True
            return None
        except (ValueError, AttributeError) as e:
            logger.warning("Unreadable oEmbed reply for %s: %s", track_url, e)
            return None
        finally:
            time.sleep(self.throttle_s)
        self.cache[track_url] = art
        return art

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, indent=0, sort_keys=True))
        tmp.replace(self.path)


def load_published(path: Path = PUBLISHED_PATH) -> dict[str, str]:
    """{date: Spotify playlist URL} for days really pushed to Spotify; {} when the file is absent."""
    if not path.exists():
        return {}
    published = json.loads(path.read_text())
    if not isinstance(published, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in published.items()):
        raise ValueError(f"{path} must map date strings to playlist URL strings")
    return published


# ---------------------------------------------------------------------------
# Assembling the days
# ---------------------------------------------------------------------------

def _site_playlist(conn: sqlite3.Connection, playlist: dict, attuned: dict,
                   art_lookup: ArtLookup, spotify_url: str | None) -> dict:
    tracks = [enrich_track(conn, track, art_lookup) for track in playlist["tracks"]]
    enriched = {**playlist, "spotify_url": spotify_url, "tracks": tracks,
                "total_time": format_total_time(tracks)}
    enriched["summary"] = playlist_summary(enriched, attuned)
    return enriched


def _playlists_by_date(conn: sqlite3.Connection, recent: list[str], others: list[str]) -> dict[str, dict | None]:
    """Recent days replayed as one chain (rotation carries over); other days on their own."""
    playlists: dict[str, dict | None] = {}
    if recent:
        for result in build_day_playlists(conn, recent[0], recent[-1]):
            if result["error"]:
                logger.warning("No playlist for %s: %s", result["date"], result["error"])
            playlists[result["date"]] = result["playlist"]
    for date in others:
        try:
            playlists[date] = build_day_playlist(conn, date)
        except GenerationError as e:
            logger.warning("No playlist for %s: %s", date, e)
            playlists[date] = None
    return playlists


def build_site_days(
    conn: sqlite3.Connection,
    end_date: str,
    n_days: int,
    art_lookup: ArtLookup,
    notable_dates: tuple[str, ...] = NOTABLE_DATES,
    published: dict[str, str] | None = None,
) -> list[dict]:
    """Page days, oldest first: every WHOOP day in the n_days ending end_date, plus notable_dates.

    Each day is build_page_day's contract plus attuned.compare, a playlist
    (None when one can't be built) with summary/total_time and enriched tracks,
    and notable: True on notable dates. art_lookup maps a track URL to album art
    (main.py passes an OembedArtCache and saves it afterwards).
    """
    if n_days < 1:
        raise ValueError(f"n_days must be at least 1, got {n_days}")
    published = published or {}

    end = date_cls.fromisoformat(end_date)
    start = (end - timedelta(days=n_days - 1)).isoformat()
    recent = [row["date"] for row in get_recoveries_in_range(conn, start, end_date)]
    others = sorted(set(notable_dates) - set(recent))

    # Scoring a day replays every earlier day; compute that history once for all of them.
    history = compute_composite_history(conn, (end + timedelta(days=1)).isoformat())
    playlists = _playlists_by_date(conn, recent, others)

    days = []
    for date in sorted(recent + others):
        day = build_page_day(conn, date, history)
        day["attuned"]["compare"] = compare_copy(day["attuned"], day["whoop"])
        playlist = playlists.get(date)
        day["playlist"] = None if playlist is None else _site_playlist(
            conn, playlist, day["attuned"], art_lookup, published.get(date, playlist.get("spotify_url")))
        day["notable"] = date in notable_dates
        days.append(day)
    return days


def render(template: str, days: list[dict]) -> str:
    """The template with the day data embedded; `</` is escaped so no value can close the script tag."""
    if template.count(DATA_PLACEHOLDER) != 1:
        raise ValueError(f"template must contain {DATA_PLACEHOLDER} exactly once")
    data = json.dumps(days, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(DATA_PLACEHOLDER, data)
