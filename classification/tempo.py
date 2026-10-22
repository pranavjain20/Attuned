"""Song tempo: turn raw tempo readings into the one tempo the profiler scores with.

Two kinds of source fail in opposite ways:
- Audio beat trackers (Essentia RhythmExtractor2013 multifeature + degara,
  TempoCNN) get the exact number right when they agree, but often land on the
  wrong octave: a ballad you clap at 76 is read as 152 because the tracker
  counts the strummed notes between claps. Soundcharts' tempo (Spotify's old
  audio features) behaves the same way, and stands in when there is no clip.
- The LLM's bpm is the reverse: an imprecise round number, but almost never on
  the wrong octave.

So the rule is:
1. The number comes from the trackers agreeing up to octave (or Soundcharts).
2. The octave is the one (½×, 1×, 2×) nearest the LLM's bpm, inside 55-165 BPM.
3. Hip-hop/rap/trap keep the listed tempo (the level the trackers report), never
   the half-time feel, so they are not scored as slow songs.
4. Energetic songs are never halved: halving is where the rule is least
   reliable (Can't Hold Us, Sooraj Ki Baahon Mein), so they keep the tempo they
   were scored at before (bpm), flagged low confidence for a manual check.
   When that kept tempo is itself half of the level the trackers or Soundcharts
   report (Blinding Lights 88 vs 172), the reported level is used instead, up to
   185 BPM, at medium confidence (low when only one tracker reading backs it).
5. A tempo set by hand (set-tempo) is never overwritten.

`resolve_tempo` is the rule; `update_tempos` is the only code that writes the
tempo columns for the whole library. `bpm` is left untouched as history.
"""

import json
import math
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from classification.llm_response import find_llm_song_result

# Felt tempos outside this window are almost always octave errors.
TEMPO_RANGE_BPM = (55.0, 165.0)
# Listed tempos for hip-hop run higher (Lose Yourself is listed at 171).
LISTED_TEMPO_RANGE_BPM = (55.0, 185.0)
PLAUSIBLE_BPM_RANGE = (30.0, 300.0)

# Two readings agree when they are within ~4% of each other, up to octave.
_AGREEMENT_LOG_TOLERANCE = 0.04
# Readings are folded into one octave [70, 140) before comparing.
_FOLD_LOW_BPM = 70.0

# How much closer (in log distance) the LLM bpm sits to the chosen octave than
# to the next one. log(2) = 0.69 is the most possible. Below 0.12 the LLM sits
# near the midpoint and carries no octave information (Ajab Si: LLM 85 between
# 59 and 118); below 0.20 it leans only weakly.
_AMBIGUOUS_OCTAVE_MARGIN = 0.12
_CLEAR_OCTAVE_MARGIN = 0.20
# Halving into this zone is a judgment call: a listener could defensibly clap
# the double (Is This Love 62 vs 125, Chaandaniya 57 vs 114).
_VERY_SLOW_BPM = 65.0
# A kept tempo counts as half-time when it is within 8% of half the reported
# level (the same ±8% used to call a tempo right).
_HALF_TIME_TOLERANCE = 0.08

LISTED_TEMPO_GENRES = frozenset({"hip-hop", "hip hop", "rap", "trap"})
FAST_MOODS = frozenset({
    "energetic", "party", "celebratory", "upbeat", "festive", "danceable", "fun",
    "dance", "confident", "assertive", "bold", "intense", "motivational",
    "playful", "joyful",
})
SLOW_MOODS = frozenset({
    "romantic", "melancholy", "melancholic", "reflective", "calm", "meditative",
    "introspective", "emotional", "sad", "dreamy", "soothing", "peaceful",
    "sensual", "devotional", "spiritual",
})

READING_COLUMNS = ("essentia_bpm", "essentia_degara_bpm", "tempocnn_bpm")


@dataclass(frozen=True)
class TempoDecision:
    tempo: float | None
    source: str | None
    confidence: str | None  # "high" | "medium" | "low"


@dataclass(frozen=True)
class TrackerConsensus:
    tempo: float              # the agreed number, folded into [70, 140)
    agreeing: int             # how many readings agree with it (up to octave)
    total: int                # how many readings there were
    reported: float           # the octave most agreeing readings reported it at
    reported_unanimous: bool  # every agreeing reading reported that same octave
    reported_by: int          # how many readings reported that octave


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------

def _fold(bpm: float) -> float:
    while bpm >= 2 * _FOLD_LOW_BPM:
        bpm /= 2
    while bpm < _FOLD_LOW_BPM:
        bpm *= 2
    return bpm


def _into_range(bpm: float, low: float, high: float) -> float:
    while bpm > high:
        bpm /= 2
    while bpm < low:
        bpm *= 2
    return bpm


def _octave_steps(bpm: float, reference: float) -> int:
    """Whole octaves between bpm and reference (0 = same level, 1 = double)."""
    return round(math.log2(bpm / reference))


def _same_pulse(a: float, b: float) -> bool:
    """Folded readings agree — including across the fold edge (69.8 vs 140.5)."""
    gap = abs(math.log(a / b))
    return gap < _AGREEMENT_LOG_TOLERANCE or gap > math.log(2) - _AGREEMENT_LOG_TOLERANCE


def _tag_set(tags: Any) -> set[str]:
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            return set()
    if not isinstance(tags, list):
        return set()
    return {str(t).strip().lower() for t in tags}


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def find_tracker_consensus(readings: list[float | None]) -> TrackerConsensus | None:
    """Find the tempo most trackers agree on, up to octave. None if no readings."""
    raw = [float(r) for r in readings if r is not None and r > 0]
    if not raw:
        return None

    folded = [_fold(r) for r in raw]
    best_group: list[int] = []
    for anchor in folded:
        group = [i for i, f in enumerate(folded) if _same_pulse(f, anchor)]
        if len(group) > len(best_group):
            best_group = group

    anchor = folded[best_group[0]]
    # Bring wrapped readings (69.8 next to 140.5) onto the anchor's side.
    aligned = [folded[i] * 2 ** -_octave_steps(folded[i], anchor) for i in best_group]
    tempo = statistics.median(aligned)

    levels = Counter(_octave_steps(raw[i], tempo) for i in best_group)
    top_count = max(levels.values())
    level = max(lv for lv, count in levels.items() if count == top_count)  # tie → faster
    return TrackerConsensus(
        tempo=tempo,
        agreeing=len(best_group),
        total=len(raw),
        reported=tempo * 2 ** level,
        reported_unanimous=len(levels) == 1,
        reported_by=top_count,
    )


def _nearest_octave(number: float, llm_bpm: float) -> tuple[float, float]:
    """The octave of number nearest llm_bpm inside the window, and how clear that is."""
    low, high = TEMPO_RANGE_BPM
    candidates = [number * f for f in (0.25, 0.5, 1, 2, 4) if low <= number * f <= high]
    if not candidates:
        return _into_range(number, low, high), math.inf
    ranked = sorted(candidates, key=lambda c: abs(math.log(c / llm_bpm)))
    if len(ranked) == 1:
        return ranked[0], math.inf
    margin = abs(math.log(ranked[1] / llm_bpm)) - abs(math.log(ranked[0] / llm_bpm))
    return ranked[0], margin


def _is_energetic(moods: set[str]) -> bool:
    return bool(moods & FAST_MOODS) and not (moods & SLOW_MOODS)


def _unhalved(fallback: TempoDecision, listed: TempoDecision) -> TempoDecision:
    """An energetic song's fallback tempo, unless it is half the listed level.

    Then the listed level is used instead, when it is in range.
    """
    low, high = LISTED_TEMPO_RANGE_BPM
    half_time = abs(2 * fallback.tempo / listed.tempo - 1) <= _HALF_TIME_TOLERANCE
    return listed if half_time and low <= listed.tempo <= high else fallback


def _decide_octave(
    number: float,
    llm_bpm: float | None,
    moods: set[str],
    agreeing: int,
    source: str,
    plain_source: str,
    listed: TempoDecision,
    current_bpm: float | None,
) -> TempoDecision:
    """Apply the LLM-octave rule to a precise number, with the energetic guard.

    current_bpm is the tempo the song was scored at before this rule existed
    (the bpm column, history); the guard keeps it rather than halving, unless
    it is itself half the listed level. listed is the level the readings
    report, as a decision.
    """
    reported = listed.tempo
    energetic = _is_energetic(moods)
    plain = TempoDecision(_into_range(reported, *TEMPO_RANGE_BPM), plain_source, "low")
    if llm_bpm is None:
        return _unhalved(plain, listed) if energetic else plain

    tempo, margin = _nearest_octave(number, llm_bpm)
    steps = _octave_steps(tempo, reported)
    if energetic and steps != 0:
        if steps < 0:  # never halve an energetic song: keep its current tempo
            kept = plain if current_bpm is None else TempoDecision(float(current_bpm), "kept_bpm", "low")
            return _unhalved(kept, listed)
        return TempoDecision(tempo, source, "low")

    if (agreeing < 2 or margin < _AMBIGUOUS_OCTAVE_MARGIN
            or (steps < 0 and tempo < _VERY_SLOW_BPM)):
        confidence = "low"
    elif agreeing == 2 or margin < _CLEAR_OCTAVE_MARGIN:
        confidence = "medium"
    else:
        confidence = "high"
    return TempoDecision(tempo, source, confidence)


def _listed_confidence(consensus: TrackerConsensus) -> str:
    if consensus.agreeing < 2:
        return "low"
    if consensus.agreeing == 2 or not consensus.reported_unanimous:
        return "medium"
    return "high"


def resolve_tempo(song: dict[str, Any], llm_bpm: float | None) -> TempoDecision:
    """Decide a song's scored tempo from its stored readings and the LLM's bpm.

    song needs: essentia_bpm, essentia_degara_bpm, tempocnn_bpm,
    soundcharts_tempo, genre_tags, mood_tags, bpm, tempo, tempo_source,
    tempo_confidence (missing keys count as unknown). Tempo is rounded to 0.1 BPM.
    """
    decision = _resolve_tempo(song, llm_bpm)
    if decision.tempo is None:
        return decision
    return TempoDecision(round(decision.tempo, 1), decision.source, decision.confidence)


def _resolve_tempo(song: dict[str, Any], llm_bpm: float | None) -> TempoDecision:
    if song.get("tempo_source") == "manual":
        return TempoDecision(song.get("tempo"), "manual", song.get("tempo_confidence"))
    if llm_bpm is not None and llm_bpm <= 0:
        llm_bpm = None

    listed_genre = bool(_tag_set(song.get("genre_tags")) & LISTED_TEMPO_GENRES)
    moods = _tag_set(song.get("mood_tags"))

    consensus = find_tracker_consensus([song.get(c) for c in READING_COLUMNS])
    if consensus is not None:
        if listed_genre:
            tempo = _into_range(consensus.reported, *LISTED_TEMPO_RANGE_BPM)
            return TempoDecision(tempo, "audio_listed", _listed_confidence(consensus))
        # The level the trackers report; trusted to medium only when 2+ readings back it.
        listed = TempoDecision(
            consensus.reported, "audio_listed", "medium" if consensus.reported_by >= 2 else "low",
        )
        return _decide_octave(
            consensus.tempo, llm_bpm, moods,
            consensus.agreeing, "audio+llm_octave", "audio", listed, song.get("bpm"),
        )

    soundcharts = song.get("soundcharts_tempo")
    if soundcharts:
        if listed_genre:
            tempo = _into_range(float(soundcharts), *LISTED_TEMPO_RANGE_BPM)
            return TempoDecision(tempo, "soundcharts", "medium")
        decision = _decide_octave(
            float(soundcharts), llm_bpm, moods,
            2, "soundcharts+llm_octave", "soundcharts",
            TempoDecision(float(soundcharts), "soundcharts", "medium"), song.get("bpm"),
        )
        # One outside source is never "high", however clear the octave.
        if decision.confidence == "high":
            return TempoDecision(decision.tempo, decision.source, "medium")
        return decision

    if llm_bpm is not None:
        return TempoDecision(float(llm_bpm), "llm", "low")
    if song.get("bpm") is not None:
        return TempoDecision(float(song["bpm"]), "bpm", "low")
    return TempoDecision(None, None, None)


# ---------------------------------------------------------------------------
# Database: the single writer of tempo
# ---------------------------------------------------------------------------

def parse_llm_bpm(llm_result: dict[str, Any] | None) -> float | None:
    """The LLM's bpm from one song's result, or None if missing/implausible."""
    if not llm_result:
        return None
    try:
        bpm = float(llm_result.get("bpm"))
    except (TypeError, ValueError):
        return None
    low, high = PLAUSIBLE_BPM_RANGE
    return bpm if low <= bpm <= high else None


def update_tempos(conn: sqlite3.Connection) -> dict[str, Any]:
    """Re-decide tempo for every classified song from its stored source columns.

    Reads only source columns (tracker readings, soundcharts_tempo, the LLM's
    bpm inside raw_response, tags) — never the tempo it writes — so running it
    twice gives the same result. Manual tempos are kept.
    """
    rows = conn.execute(
        f"""SELECT sc.spotify_uri, s.name, s.artist, sc.raw_response,
                   {", ".join("sc." + c for c in READING_COLUMNS)},
                   sc.soundcharts_tempo, sc.genre_tags, sc.mood_tags, sc.bpm,
                   sc.tempo, sc.tempo_source, sc.tempo_confidence
            FROM song_classifications sc
            JOIN songs s ON sc.spotify_uri = s.spotify_uri"""
    ).fetchall()

    by_source: Counter[str] = Counter()
    by_confidence: Counter[str] = Counter()
    for row in rows:
        song = dict(row)
        llm_bpm = parse_llm_bpm(
            find_llm_song_result(song["raw_response"], song["name"], song["artist"])
        )
        decision = resolve_tempo(song, llm_bpm)
        conn.execute(
            """UPDATE song_classifications
               SET tempo = ?, tempo_source = ?, tempo_confidence = ?
               WHERE spotify_uri = ?""",
            (decision.tempo, decision.source, decision.confidence, song["spotify_uri"]),
        )
        by_source[decision.source or "none"] += 1
        by_confidence[decision.confidence or "none"] += 1
    conn.commit()

    return {
        "updated": len(rows),
        "by_source": dict(by_source),
        "by_confidence": dict(by_confidence),
    }


def set_manual_tempo(conn: sqlite3.Connection, song: str, bpm: float) -> list[dict[str, Any]]:
    """Pin a song's tempo by hand (e.g. after tapping along). Never overwritten.

    song is a spotify_uri or an exact title (case-insensitive). A title that
    matches several classified songs raises instead of guessing.
    Returns the matched row(s) as {spotify_uri, name, artist, old_tempo}.
    """
    low, high = PLAUSIBLE_BPM_RANGE
    if not low <= bpm <= high:
        raise ValueError(f"Tempo must be between {low:.0f} and {high:.0f} BPM, got {bpm}")

    matches = conn.execute(
        """SELECT sc.spotify_uri, s.name, s.artist, sc.tempo AS old_tempo
           FROM song_classifications sc
           JOIN songs s ON sc.spotify_uri = s.spotify_uri
           WHERE sc.spotify_uri = ? OR LOWER(TRIM(s.name)) = LOWER(TRIM(?))""",
        (song, song),
    ).fetchall()
    matches = [dict(m) for m in matches]
    if not matches:
        raise ValueError(f"No classified song matches {song!r}")
    if len(matches) > 1:
        listed = "; ".join(f"{m['name']} — {m['artist']} ({m['spotify_uri']})" for m in matches)
        raise ValueError(f"{song!r} matches {len(matches)} songs, use the spotify_uri: {listed}")

    conn.execute(
        """UPDATE song_classifications
           SET tempo = ?, tempo_source = 'manual', tempo_confidence = 'high'
           WHERE spotify_uri = ?""",
        (float(bpm), matches[0]["spotify_uri"]),
    )
    conn.commit()
    return matches
