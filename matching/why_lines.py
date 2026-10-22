"""Plain-English "why it's here" lines for each song in a day's playlist.

Rules-based and deterministic, no LLM. A line describes the song in plain
words (mood, feel, genre), then what it does in the mix, then optionally one
personal fact ("One you play a lot.").

The playlist is chosen for what's good for you given how you'll likely feel,
so lines never name our internal states ("rest day", "grounding") and never
claim what a song does to the body ("lowers your heart rate").

No raw BPM unless it's trustworthy: LLM BPM is often double-time for
Bollywood, so only the human-felt tempo (felt_tempo) is ever shown.
"""

from datetime import date as date_cls, timedelta

MAX_WHY_LENGTH = 79  # strictly under 80

# "One you play a lot" = top 10% of the library by plays, never under 10 plays.
MOST_PLAYED_PERCENTILE = 0.90
MOST_PLAYED_MIN_PLAYS = 10
LONG_TIME_MIN_DAYS = 3 * 365   # first heard this long ago → "long-time favourite"
ENGAGED_PERCENTILE = 0.75
DEEP_CUT_MAX_PLAYS = 4
RECENT_WEEK_DAYS = 7
RECENT_MONTH_DAYS = 30
REDISCOVERY_MIN_DAYS = 365
CLASSIC_MAX_YEAR = 1995
# Facts that depend on knowing every play ("not played in a while", "deeper
# cut") need unbroken listening history: over the year before the day, no
# stretch longer than this without a single recorded play.
HISTORY_WINDOW_DAYS = 365
HISTORY_MAX_GAP_DAYS = 14
# A song counts as leaning the day's way if its score on the day's dimension
# is within this margin of its top dimension (neuro scores are noisy at ~0.1).
DIM_TIE_MARGIN = 0.05

SOFT_MAX_ENERGY = 0.30
HIGH_MIN_ENERGY = 0.75
ACOUSTIC_MIN = 0.60

# Mood tags reworded where the raw tag doesn't read as an adjective;
# tags in _SKIP_MOODS don't describe how the song sounds.
_MOOD_WORDS = {"melancholic": "melancholy", "lighthearted": "light-hearted", "party": "party-ready"}
_SKIP_MOODS = frozenset({"modern", "protest"})

# Genre tags that are moods/variants, not genres.
_SKIP_GENRES = frozenset({"romantic", "remix", "classic", "inspirational",
                          "acoustic", "instrumental", "devotional"})
_GENRE_WORDS = {
    "bollywood": "Bollywood", "punjabi": "Punjabi", "hindi": "Hindi",
    "sufi": "Sufi", "latin": "Latin", "r&b": "R&B", "edm": "EDM",
}

# What the song does in the mix, as (noun form, verb form), keyed by the day's
# state and the song's own leaning. The noun form follows a comma ("Soft and
# romantic, an easy one to settle into."); the verb form follows "that".
_STATE_DIM = {"rest": "para", "energy": "symp", "grounding": "grnd"}
_PURPOSES = {
    ("rest", "para"): [("an easy one to settle into", "eases the pace"),
                       ("a gentle one to unwind with", "keeps the mood unhurried"),
                       ("a calm stretch in the mix", "lets the pace drop")],
    ("rest", "grnd"): [("a slow and steady pick", "keeps things slow and steady"),
                       ("an even-tempered one", "holds an easy pace")],
    ("rest", "symp"): [("a little brightness among calmer songs", "adds brightness without rushing")],
    ("energy", "symp"): [("one to get moving to", "keeps the momentum going"),
                         ("a bright lift for the mix", "brings some lift"),
                         ("a lively one to keep things up", "keeps the mix lively")],
    ("energy", "para"): [("a breather between brighter songs", "gives the mix a breather")],
    ("energy", "grnd"): [("a steadier moment among brighter songs", "keeps the lift steady")],
    ("grounding", "grnd"): [("a steady one to stay with", "keeps things even"),
                            ("an even-keeled pick", "holds a steady line"),
                            ("a calm and centred one", "keeps the mood level")],
    ("grounding", "para"): [("a softer moment in the mix", "slows things a touch")],
    ("grounding", "symp"): [("a brighter moment in an even mix", "lifts the mood a little")],
}

_FACTS = {
    "long_time": "A long-time favourite.",
    "most_played": "One you play a lot.",
    "this_week": "Played this week.",
    "this_month": "Played this past month.",
    "classic": "A {year} classic.",
    "new_release": "A recent release.",
    "rediscovery": "Not played in a while.",
    "engaged": "One you keep coming back to.",
    "deep_cut": "A deeper cut from your library.",
}


def _percentile(values: list[float], pct: float) -> float | None:
    """Value at the given percentile (nearest-rank), or None if no values."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(pct * len(vals)))]


def _with_article(phrase: str) -> str:
    return ("an " if phrase[0].lower() in "aeiou" else "a ") + phrase


def _cap(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


def _days_since(timestamp: str | None, ref: date_cls) -> int | None:
    if not timestamp:
        return None
    try:
        return (ref - date_cls.fromisoformat(timestamp[:10])).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Describing the song
# ---------------------------------------------------------------------------

def _moods(song: dict) -> list[str]:
    """Usable mood adjectives in the classifier's order, deduplicated."""
    words: list[str] = []
    for tag in song.get("mood_tags") or []:
        tag = (tag or "").lower().strip()
        if not tag or tag in _SKIP_MOODS:
            continue
        word = _MOOD_WORDS.get(tag, tag)
        if word not in words:
            words.append(word)
    return words


def _genre(song: dict) -> str | None:
    for tag in song.get("genre_tags") or []:
        tag = (tag or "").lower().strip()
        if tag and tag not in _SKIP_GENRES:
            return _GENRE_WORDS.get(tag, tag)
    return None


def _texture(song: dict) -> str | None:
    energy, acoustic = song.get("energy"), song.get("acousticness")
    if energy is not None and energy <= SOFT_MAX_ENERGY:
        return "soft"
    if acoustic is not None and acoustic >= ACOUSTIC_MIN:
        return "acoustic"
    if energy is not None and energy >= HIGH_MIN_ENERGY:
        return "high-energy"
    return None


def _tempo(song: dict) -> str | None:
    """Felt tempo phrase, the only tempo we trust enough to show."""
    felt = song.get("felt_tempo")
    if not felt:
        return None
    word = "slow" if felt <= 85 else "steady" if felt <= 110 else "upbeat"
    return f"{word} ({round(felt)} BPM)"


def _adjective_phrases(song: dict) -> list[str]:
    """Ways to describe the song as adjectives: "soft and romantic"."""
    moods, texture, tempo = _moods(song), _texture(song), _tempo(song)
    phrases = []
    if tempo and moods:
        phrases.append(f"{tempo} and {moods[0]}")
    if texture and moods and texture != moods[0]:
        phrases.append(f"{texture} and {moods[0]}")
    if len(moods) >= 2:
        phrases.append(f"{moods[0]} and {moods[1]}")
    if not phrases and moods:
        phrases.append(moods[0])
    if not phrases and texture:
        phrases.append(texture)
    return phrases


def _noun_phrases(song: dict) -> list[str]:
    """Ways to describe the song as a noun: "a romantic Bollywood song"."""
    moods, genre, texture = _moods(song), _genre(song), _texture(song)
    if not genre:
        return []
    phrases = []
    if moods:
        phrases.append(_with_article(f"{moods[0]} {genre} song"))
    if len(moods) >= 2:
        phrases.append(f"{_with_article(genre)} song with {_with_article(moods[1])} feel")
    if not phrases:
        phrases.append(_with_article(f"{texture} {genre} song" if texture else f"{genre} song"))
    return phrases


def _main_sentences(song: dict, noun: str, verb: str) -> list[tuple[str, str]]:
    """(shape, sentence) options for describing the song and its job in the mix."""
    options = []
    for adj in _adjective_phrases(song):
        options.append(("adj_noun", f"{_cap(adj)}, {noun}."))
        options.append(("noun_adj", f"{_cap(noun)}, {adj}."))
    for np in _noun_phrases(song):
        options.append(("np_verb", f"{_cap(np)} that {verb}."))
    if not options:
        options.append(("bare", f"{_cap(noun)}."))
    return options


# ---------------------------------------------------------------------------
# Picking the song's job in the mix
# ---------------------------------------------------------------------------

def _song_dim(song: dict, state_dim: str) -> str | None:
    """The song's leaning; the day's own dimension wins near-ties."""
    scores = {"para": song.get("parasympathetic"), "symp": song.get("sympathetic"),
              "grnd": song.get("grounding")}
    known = {k: v for k, v in scores.items() if v is not None}
    if not known:
        return None
    top = max(known.values())
    if known.get(state_dim) is not None and known[state_dim] >= top - DIM_TIE_MARGIN:
        return state_dim
    return max(known, key=known.get)


# ---------------------------------------------------------------------------
# Personal facts
# ---------------------------------------------------------------------------

def _personal_facts(song: dict, ctx: dict) -> list[str]:
    """True personal facts as _FACTS keys, most distinctive first."""
    ref = ctx["date"]
    facts: list[str] = []
    plays = song.get("play_count")
    if plays is not None and ctx["most_played_min"] is not None and plays >= ctx["most_played_min"]:
        first_days = _days_since(song.get("first_played"), ref)
        long_time = first_days is not None and first_days >= LONG_TIME_MIN_DAYS
        facts.append("long_time" if long_time else "most_played")

    last_days = _days_since(song.get("last_played"), ref)
    if last_days is not None and 0 <= last_days <= RECENT_WEEK_DAYS:
        facts.append("this_week")
    elif last_days is not None and 0 <= last_days <= RECENT_MONTH_DAYS:
        facts.append("this_month")
    elif last_days is not None and last_days >= REDISCOVERY_MIN_DAYS and ctx["history_complete"]:
        facts.append("rediscovery")

    year = song.get("original_release_year") or song.get("release_year")
    if year and year <= CLASSIC_MAX_YEAR:
        facts.append("classic")
    elif year and year >= ref.year - 1:
        facts.append("new_release")

    engagement = song.get("engagement_score")
    if (not facts and engagement is not None and ctx["engaged_min"] is not None
            and engagement >= ctx["engaged_min"]):
        facts.append("engaged")
    if not facts and plays is not None and plays <= DEEP_CUT_MAX_PLAYS and ctx["history_complete"]:
        facts.append("deep_cut")
    return facts


def history_is_complete(play_dates: list[str], ref: date_cls) -> bool:
    """True if listening history covers the year before ref with no long gap.

    play_dates: YYYY-MM-DD days with at least one recorded play. A gap longer
    than HISTORY_MAX_GAP_DAYS anywhere in [ref - HISTORY_WINDOW_DAYS, ref)
    (including at either end) means plays went unrecorded.
    """
    window_start = ref - timedelta(days=HISTORY_WINDOW_DAYS)
    days = sorted({date_cls.fromisoformat(d[:10]) for d in play_dates})
    days = [d for d in days if window_start <= d < ref]
    if not days:
        return False
    points = [window_start, *days, ref]
    return all((b - a).days <= HISTORY_MAX_GAP_DAYS for a, b in zip(points, points[1:]))


def build_context(library: list[dict], date: str, play_dates: list[str] | None = None) -> dict:
    """Library-wide thresholds the lines are judged against.

    play_dates: days with recorded plays before `date` (see history_is_complete);
    None means unknown, so history-dependent facts are never claimed.
    """
    ref = date_cls.fromisoformat(date)
    p90 = _percentile([s.get("play_count") for s in library], MOST_PLAYED_PERCENTILE)
    return {
        "date": ref,
        "history_complete": history_is_complete(play_dates or [], ref),
        "most_played_min": max(p90, MOST_PLAYED_MIN_PLAYS) if p90 is not None else None,
        "engaged_min": _percentile([s.get("engagement_score") for s in library], ENGAGED_PERCENTILE),
    }


# ---------------------------------------------------------------------------
# Assembling lines
# ---------------------------------------------------------------------------

def explain_playlist(songs: list[dict], state: str, context: dict) -> list[str]:
    """One "why it's here" line per song, phrased so the list doesn't repeat itself.

    Variety: purposes rotate down the list; each song gets the sentence shape
    and personal fact used least so far; a line already used is never reused
    while another true phrasing exists.
    """
    uses: dict[str, int] = {}
    seen: set[str] = set()
    lines = []
    for song in songs:
        line = _explain(song, state, context, uses, seen)
        seen.add(line)
        lines.append(line)
    return lines


def _rotated(key: str, options: list, uses: dict[str, int]) -> list:
    """options starting from the next unused one for this key."""
    n = uses.get(key, 0) % len(options)
    return options[n:] + options[:n]


def _explain(song: dict, state: str, ctx: dict, uses: dict[str, int], seen: set[str]) -> str:
    """The preferred line for this song that hasn't already been used in the playlist."""
    state_dim = _STATE_DIM[state]
    purpose_key = (state, _song_dim(song, state_dim) or state_dim)
    purposes = _PURPOSES[purpose_key]

    facts = sorted(_personal_facts(song, ctx), key=lambda f: uses.get(f, 0))
    fact = facts[0] if facts else None
    second = _FACTS[fact].format(year=song.get("original_release_year") or song.get("release_year")) if fact else ""

    mains = []  # (main sentence, purpose_index, shape), preferred first
    for noun, verb in _rotated(str(purpose_key), purposes, uses):
        idx = purposes.index((noun, verb))
        for shape, main in sorted(_main_sentences(song, noun, verb), key=lambda m: uses.get(m[0], 0)):
            mains.append((main, idx, shape))
    # Keeping the personal fact beats keeping the preferred phrasing.
    candidates = [(f"{main} {second}", idx, shape, True) for main, idx, shape in mains
                  if second and len(f"{main} {second}") <= MAX_WHY_LENGTH]
    candidates += [(main, idx, shape, False) for main, idx, shape in mains
                   if len(main) <= MAX_WHY_LENGTH]
    candidates.append((f"{_cap(purposes[0][0])}.", 0, "bare", False))  # always fits
    line, idx, shape, used_fact = next((c for c in candidates if c[0] not in seen), candidates[0])

    uses[str(purpose_key)] = idx + 1
    uses[shape] = uses.get(shape, 0) + 1
    if used_fact:
        uses[fact] = uses.get(fact, 0) + 1
    return line
