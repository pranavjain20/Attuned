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
from intelligence.playlist_target import STATE_PURPOSE
from intelligence.feeling_score import (
    HEART_SIGNALS,
    SIGNAL_PHRASES,
    band,
    build_page_day,
    compute_composite_history,
)
from matching.day_playlist import build_day_playlists, track_uri
from matching.why_lines import capitalize_first

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
TEMPLATE_PATH = WEB_DIR / "template.html"
ART_CACHE_PATH = WEB_DIR / ".art_cache.json"
PUBLISHED_PATH = WEB_DIR / "published.json"
PLAYLISTS_PATH = WEB_DIR / "playlists.json"   # every day's playlist, decided once
DATA_PLACEHOLDER = "__ATTUNED_DATA__"

SHORTCUT_DAYS = 3             # the most recent days get a shortcut chip above the rings
AGREE_WITHIN_POINTS = 10      # a smaller gap reads as "roughly agree"; this or more, better/worse
BIG_GAP_POINTS = 20           # a gap this big also gets a line on why the two can differ
MAX_MOODS_PER_TRACK = 3
MAX_GENRES_PER_TRACK = 2

OEMBED_URL = "https://open.spotify.com/oembed?url={}"
ART_THROTTLE_S = 0.25
ART_TIMEOUT_S = 15

ArtLookup = Callable[[str], str | None]

MOOD_WORD = {"green": "good", "yellow": "middling", "red": "low"}

BERNARDI_2006 = ["Bernardi 2006", "https://doi.org/10.1136/hrt.2005.064600"]
PLAN = {
    "rest": {
        "does": f"built to {STATE_PURPOSE['rest']}", "kinds": "Slower, softer",
        "why": "Studies find slower music tends to bring heart rate down and calm the body.",
        "cites": [BERNARDI_2006, ["Ooishi 2017", "https://doi.org/10.1371/journal.pone.0189075"]],
    },
    "energy": {
        "does": f"built to {STATE_PURPOSE['energy']}", "kinds": "Brighter, faster",
        "why": "Studies find faster music tends to raise heart rate and breathing, in step with the tempo.",
        "cites": [BERNARDI_2006],
    },
    "grounding": {
        "does": f"built to {STATE_PURPOSE['grounding']}", "kinds": "Steady, familiar",
        "why": "Studies find music you love triggers the brain's reward system, "
               "so personally meaningful songs land harder emotionally.",
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


def _leads_with_bad(attuned: dict, whoop: dict) -> bool:
    """Lead with what pulled the score down? At or below WHOOP, yes. With no WHOOP number,
    follow the drivers: they come explaining-side first (feeling_score.pick_drivers)."""
    if whoop.get("recovery") is not None:
        return attuned["score"] <= whoop["recovery"]
    drivers = attuned.get("drivers") or []
    return bool(drivers) and drivers[0]["effect"] != "up"


def reason_line(attuned: dict, whoop: dict) -> str:
    """One sentence naming what moved the score, leading with the side that explains it."""
    if attuned.get("score") is None:
        return attuned.get("reason") or "No feeling score for this day."
    good, bad = [], []
    for driver in attuned.get("drivers") or []:
        phrase = SIGNAL_PHRASES.get(driver["signal"])
        if phrase is None:
            continue
        if driver["effect"] == "up":
            good.append(phrase[0])
        else:
            bad.append(phrase[1])
    lead, other = (bad, good) if _leads_with_bad(attuned, whoop) else (good, bad)
    if not lead:
        lead, other = other, []
    if not lead:
        return "A night close to your usual."
    line = join_and(lead) + (f", despite {join_and(other)}" if other else " than usual")
    return capitalize_first(line) + "."


def _gap_article(size: int) -> str:
    """'An' before numbers said with a vowel sound (8, 11, 18, 80-89), else 'A'."""
    return "An" if str(size).startswith("8") or size in (11, 18) else "A"


def _gap_note(gap: int) -> str:
    """The small line under the two rings, for a signed gap (Attuned minus WHOOP).

    Uses the title's cut-off, so the note never contradicts the title above it.
    """
    size = abs(gap)
    if size == 0:
        return "Same score as WHOOP today."
    if size < AGREE_WITHIN_POINTS:
        return f"Within {size} point{'' if size == 1 else 's'}: today the two scores roughly agree."
    if size >= BIG_GAP_POINTS:
        return f"{_gap_article(size)} {size}-point gap: body readiness and mood can point different ways."
    return f"{_gap_article(size)} {size}-point gap."


def compare_copy(attuned: dict, whoop: dict) -> dict:
    """{"title", "line", "note"}: why Attuned differs from WHOOP today, in a title + one sentence.

    The note under the rings is blank when either score is missing.
    """
    if attuned.get("score") is None:
        return {"title": "No Attuned score today", "line": attuned.get("reason") or "", "note": ""}
    if whoop.get("recovery") is None:
        return {"title": "No WHOOP recovery to compare today", "line": reason_line(attuned, whoop), "note": ""}

    gap = _round_half_up(attuned["score"] - whoop["recovery"])
    note = _gap_note(gap)
    heart_good, heart_bad, sleep_good, sleep_bad = [], [], [], []
    for driver in attuned.get("drivers") or []:
        phrase = SIGNAL_PHRASES.get(driver["signal"])
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
    elif attuned.get("drivers") == [] and band(attuned["score"]) == "yellow":
        # An ordinary night that lands Attuned in the middle: the gap is WHOOP's, so don't invent a cause.
        line = ("Your sleep and heart signals were all close to your usual, so Attuned puts today "
                f"in the middle. WHOOP rated it {'higher' if worse else 'lower'}.")
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
    """{"lead", "kinds", "why", "cites": [[label, url]]} for the playlist card.

    The plan follows the day's state, or the playlist's own when the day has none.
    """
    plan = PLAN.get(attuned.get("state") or playlist.get("state"), PLAN["grounding"])
    if attuned.get("score") is None:
        lead = f"There's no Attuned score for today yet, so this playlist is {plan['does']}."
    else:
        mood = MOOD_WORD[attuned.get("band") or band(attuned["score"])]
        lead = f"You'll likely feel {mood} today, so this playlist is {plan['does']}."
    return {
        "lead": lead,
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
    uri = track_uri(track)
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

    Only real answers are cached: a reply, or "not found" (404). A server error
    (5xx) is skipped and asked again next build. A rate limit (429) or a network
    failure is not cached either, and stops further fetches for the rest of this
    run, so a throttled or offline build doesn't keep asking or wait out a
    timeout per track.
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
            if e.code != 404:
                logger.warning("Album art for %s failed (HTTP %s); not cached", track_url, e.code)
                if e.code == 429:
                    logger.warning("Spotify is rate limiting oEmbed; skipping art for the rest of this build")
                    self.offline = True
                return None
            logger.warning("No album art for %s (HTTP 404)", track_url)
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


def _is_published_record(record) -> bool:
    return (isinstance(record, dict) and isinstance(record.get("url"), str)
            and isinstance(record.get("track_uris"), list)
            and all(isinstance(uri, str) for uri in record["track_uris"])
            and all(isinstance(record[key], str) for key in ("name", "description") if key in record))


def load_published(path: Path = PUBLISHED_PATH) -> dict[str, dict]:
    """{date: {"url", "track_uris", "name"?, "description"?}} for days really pushed to Spotify.

    {} when the file is absent. name and description are what the Spotify
    playlist was last given (records written before they were kept lack them).
    """
    if not path.exists():
        return {}
    published = json.loads(path.read_text())
    if not isinstance(published, dict) or not all(
            isinstance(k, str) and _is_published_record(v) for k, v in published.items()):
        raise ValueError(f'{path} must map date strings to '
                         f'{{"url": str, "track_uris": [str], "name"?: str, "description"?: str}}')
    return published


def _write_json_atomically(data: dict, path: Path) -> None:
    """Write via a temp file, so an interrupted run never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def save_published(published: dict[str, dict], path: Path = PUBLISHED_PATH) -> None:
    """Write the published mapping atomically."""
    _write_json_atomically(published, path)


def load_frozen(path: Path = PLAYLISTS_PATH) -> dict[str, dict]:
    """{date: playlist} for every day already decided; {} when the file is absent."""
    if not path.exists():
        return {}
    frozen = json.loads(path.read_text())
    if not isinstance(frozen, dict) or not all(
            isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("tracks"), list)
            for k, v in frozen.items()):
        raise ValueError(f"{path} must map date strings to playlists with a tracks list")
    return frozen


def save_frozen(frozen: dict[str, dict], path: Path = PLAYLISTS_PATH) -> None:
    """Write the decided playlists atomically."""
    _write_json_atomically(frozen, path)


def open_link(record: dict | None, tracks: list[dict]) -> dict | None:
    """The playlist header's green button.

    The published playlist (load_published's record) only when it holds exactly
    these tracks in this order, so the button never opens different songs from
    the page; otherwise the first song.
    """
    if record and tracks and record["track_uris"] == [track_uri(t) for t in tracks]:
        return {"label": "Open in Spotify", "url": record["url"]}
    if tracks:
        return {"label": "Play on Spotify", "url": tracks[0]["spotify_url"]}
    return None


def shown_tracks(playlist: dict, record: dict | None) -> list[dict]:
    """The songs the page lists for a day: the published ones when the replay still has them all.

    Publishing swaps songs Spotify no longer plays for spares, so a published
    playlist can differ from the replay's first 20. When every published song is
    among the replay's tracks and spares, the page shows them (with their
    why-lines) in the published order, matching Spotify. Otherwise the replay
    has moved on (or nothing was published) and the page shows its own tracks.
    """
    candidates = {track_uri(t): t for t in playlist["tracks"] + playlist.get("spares", [])}
    uris = record["track_uris"] if record else []
    if uris and all(uri in candidates for uri in uris):
        return [candidates[uri] for uri in uris]
    return playlist["tracks"]


# ---------------------------------------------------------------------------
# Assembling the days
# ---------------------------------------------------------------------------

def _site_playlist(conn: sqlite3.Connection, playlist: dict, attuned: dict,
                   art_lookup: ArtLookup, record: dict | None) -> dict:
    tracks = [enrich_track(conn, track, art_lookup) for track in shown_tracks(playlist, record)]
    enriched = {"name": playlist["name"], "state": playlist["state"], "open": open_link(record, tracks),
                "tracks": tracks, "total_time": format_total_time(tracks)}
    enriched["summary"] = playlist_summary(enriched, attuned)
    return enriched


def window_dates(conn: sqlite3.Connection, end_date: str, n_days: int) -> list[str]:
    """The page's days, oldest first: every WHOOP day in the n_days ending end_date."""
    if n_days < 1:
        raise ValueError(f"n_days must be at least 1, got {n_days}")
    start = (date_cls.fromisoformat(end_date) - timedelta(days=n_days - 1)).isoformat()
    return sorted(row["date"] for row in get_recoveries_in_range(conn, start, end_date))


def replay_playlists(conn: sqlite3.Connection, dates: list[str],
                     history: dict[str, dict] | None = None,
                     frozen: dict[str, dict] | None = None) -> dict[str, dict | None]:
    """The days' playlists (build_day_playlist's dict, or None).

    A day's playlist is decided once, like a real morning: days already in
    `frozen` are reused, and only new days are built, chained after every frozen
    day so rotation carries over. Newly built days are added to `frozen` (the
    caller saves it); a day that couldn't be built isn't, so it's retried.
    Without this, the window sliding forward a day would change past days.
    """
    frozen = {} if frozen is None else frozen
    missing = [d for d in dates if d not in frozen]
    if missing:
        fixed = {d: [track_uri(t) for t in pl["tracks"]] for d, pl in frozen.items() if d <= dates[-1]}
        for result in build_day_playlists(conn, missing[0], dates[-1], history=history, fixed=fixed):
            if result["error"]:
                logger.warning("No playlist for %s: %s", result["date"], result["error"])
            elif result["playlist"]:
                frozen[result["date"]] = result["playlist"]
    return {d: frozen.get(d) for d in dates}


def build_site_days(
    conn: sqlite3.Connection,
    end_date: str,
    n_days: int,
    art_lookup: ArtLookup,
    published: dict[str, dict] | None = None,
    frozen: dict[str, dict] | None = None,
) -> list[dict]:
    """Page days, oldest first: every WHOOP day in the n_days ending end_date.

    frozen: load_frozen's playlists (see replay_playlists); new days are added to it.

    Each day is build_page_day's contract plus attuned.compare, a playlist
    (None when one can't be built) with name/state/summary/total_time, enriched
    tracks (shown_tracks) and open (the header button: {label, url}), and
    shortcut: True on the SHORTCUT_DAYS most recent days.
    published is load_published's mapping. art_lookup maps a track URL to album art
    (main.py passes an OembedArtCache and saves it afterwards).
    """
    dates = window_dates(conn, end_date, n_days)
    published = published or {}
    shortcuts = set(dates[-SHORTCUT_DAYS:])
    # Scoring a day replays every earlier day; compute that history once and share it
    # between the scores and the playlists.
    next_day = (date_cls.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    history = compute_composite_history(conn, next_day)
    playlists = replay_playlists(conn, dates, history, frozen)

    days = []
    for date in dates:
        day = build_page_day(conn, date, history)
        day["attuned"]["compare"] = compare_copy(day["attuned"], day["whoop"])
        playlist = playlists.get(date)
        if playlist is not None:
            playlist = _site_playlist(conn, playlist, day["attuned"], art_lookup, published.get(date))
        day["playlist"] = playlist
        day["shortcut"] = date in shortcuts
        days.append(day)
    return days


def render(template: str, days: list[dict]) -> str:
    """The template with the day data embedded; `</` is escaped so no value can close the script tag."""
    if template.count(DATA_PLACEHOLDER) != 1:
        raise ValueError(f"template must contain {DATA_PLACEHOLDER} exactly once")
    data = json.dumps(days, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(DATA_PLACEHOLDER, data)
