"""Tests for matching/why_lines.py — the per-song "why it's here" lines."""

import re
from datetime import date, timedelta

import pytest

from matching.why_lines import (
    MAX_WHY_LENGTH,
    _with_article,
    build_context,
    capitalize_first,
    explain_playlist,
    history_is_complete,
)

DATE = "2026-10-21"

# Internal state names and body claims must never reach the page.
STATE_NAMES = re.compile(r"rest day|slower day|grounding|energy day|high-energy day|"
                         r"settled pick|\brest\b|\bstate\b", re.IGNORECASE)
BODY_CLAIMS = re.compile(r"\b(heart rate|hrv|nervous|lowers?|cortisol|stress|recover\w*|heal\w*"
                         r"|relax(es)? you|calms? you|your body|blood)\b", re.IGNORECASE)
EXACT_COUNTS = re.compile(r"\d+ (times|plays)", re.IGNORECASE)


def _song(**overrides):
    song = {
        "spotify_uri": "spotify:track:x",
        "parasympathetic": 0.8, "sympathetic": 0.2, "grounding": 0.4,
        "bpm": 152.0, "felt_tempo": None, "tempo": None, "tempo_confidence": None,
        "energy": 0.5, "valence": 0.5, "acousticness": 0.3,
        "mood_tags": ["romantic", "nostalgic"], "genre_tags": ["bollywood", "hindi"],
        "original_release_year": 2011, "release_year": 2011,
        "play_count": 6, "engagement_score": 0.40,
        "first_played": "2025-01-01T10:00:00Z", "last_played": "2026-03-01T10:00:00Z",
    }
    song.update(overrides)
    return song


def _library(n=100):
    """Play counts 1..n and engagement 0.01..1.0."""
    return [{"play_count": i, "engagement_score": i / n} for i in range(1, n + 1)]


def _every_day(start: str, end: str) -> list[str]:
    d, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


FULL_HISTORY = _every_day("2025-10-01", "2026-10-20")
GAPPY_HISTORY = _every_day("2025-10-01", "2026-04-05") + ["2026-10-20"]  # the real Apr→Oct gap


@pytest.fixture
def ctx():
    return build_context(_library(), DATE, FULL_HISTORY)


@pytest.fixture
def stale_ctx():
    return build_context(_library(), DATE, GAPPY_HISTORY)


def _one(song, state="rest", context=None):
    return explain_playlist([song], state, context or build_context(_library(), DATE, FULL_HISTORY))[0]


class TestBuildContext:
    def test_thresholds_from_library(self, ctx):
        assert ctx["most_played_min"] == 91   # top 10% of 1..100
        assert ctx["history_complete"] is True

    def test_small_library_floors_most_played(self):
        assert build_context([{"play_count": p} for p in (1, 2, 3)], DATE)["most_played_min"] == 10

    def test_empty_library(self):
        ctx = build_context([], DATE)
        assert ctx["most_played_min"] is None
        assert ctx["engaged_min"] is None
        assert ctx["history_complete"] is False


class TestHistoryIsComplete:
    def test_daily_listening_is_complete(self):
        assert history_is_complete(FULL_HISTORY, date.fromisoformat(DATE)) is True

    def test_gap_in_the_middle_is_incomplete(self):
        # Recent plays alone don't help: the months-long gap means "not played since" is unknowable.
        assert history_is_complete(GAPPY_HISTORY, date.fromisoformat(DATE)) is False

    def test_stops_short_of_the_day(self):
        days = _every_day("2025-10-01", "2026-09-30")
        assert history_is_complete(days, date.fromisoformat(DATE)) is False

    def test_starts_too_late(self):
        days = _every_day("2026-06-01", "2026-10-20")
        assert history_is_complete(days, date.fromisoformat(DATE)) is False

    def test_weekly_listening_is_complete(self):
        days = _every_day("2025-10-01", "2026-10-20")[::7]
        assert history_is_complete(days + ["2026-10-20"], date.fromisoformat(DATE)) is True

    def test_ignores_days_on_or_after_ref(self):
        days = _every_day("2025-10-01", "2026-09-01") + ["2026-10-21", "2026-11-01"]
        assert history_is_complete(days, date.fromisoformat(DATE)) is False

    def test_empty(self):
        assert history_is_complete([], date.fromisoformat(DATE)) is False


class TestDescription:
    def test_example_shape(self):
        line = _one(_song(energy=0.2, mood_tags=["romantic"], genre_tags=[]))
        assert line == "Soft and romantic, an easy one to settle into."

    def test_noun_shape_uses_that(self):
        line = _one(_song(mood_tags=["romantic"], energy=0.5, acousticness=0.3))
        assert line in {"A romantic Bollywood song that eases the pace.",
                        "Romantic, an easy one to settle into.",
                        "An easy one to settle into, romantic."}

    def test_acoustic_texture(self):
        assert "acoustic and romantic" in _one(_song(acousticness=0.8)).lower()

    @pytest.mark.parametrize("state,words", [
        ("rest", ("settle", "unwind", "pace", "calm")),
        ("energy", ("moving", "lift", "lively", "momentum")),
        ("grounding", ("steady", "even", "centred", "level")),
    ])
    def test_purpose_follows_state_without_naming_it(self, state, words):
        dims = {"rest": (0.9, 0.1, 0.2), "energy": (0.1, 0.9, 0.2), "grounding": (0.1, 0.2, 0.9)}[state]
        line = _one(_song(parasympathetic=dims[0], sympathetic=dims[1], grounding=dims[2]), state=state)
        assert any(w in line for w in words), line
        assert not STATE_NAMES.search(line), line

    def test_off_leaning_song_described_honestly(self):
        # A bright song chosen on a calm day is called a brighter moment, not a calm one.
        line = _one(_song(parasympathetic=0.1, sympathetic=0.9, grounding=0.2), state="rest")
        assert "brightness" in line

    def test_near_tie_counts_as_leaning_the_days_way(self):
        line = _one(_song(parasympathetic=0.66, grounding=0.67), state="rest")
        assert any(w in line for w in ("settle", "unwind", "pace", "calm")), line

    def test_article_before_vowel(self):
        line = explain_playlist([_song(mood_tags=["uplifting", "joyful"], genre_tags=["indie"])] * 3,
                                "rest", build_context(_library(), DATE))
        assert any("An uplifting indie song" in l or "an indie song with a joyful feel" in l.lower()
                   for l in line), line

    @pytest.mark.parametrize("phrase, expected", [
        ("R&B song", "an R&B song"),          # consonant letter, vowel sound
        ("r&b song", "an r&b song"),
        ("EDM song", "an EDM song"),
        ("hour-long song", "an hour-long song"),
        ("upbeat song", "an upbeat song"),
        ("euphoric song", "a euphoric song"),  # vowel letter, consonant sound
        ("unique song", "a unique song"),
        ("one-of-a-kind song", "a one-of-a-kind song"),
        ("romantic song", "a romantic song"),
        ("happy song", "a happy song"),
    ])
    def test_article_follows_the_sound_not_the_letter(self, phrase, expected):
        assert _with_article(phrase) == expected

    def test_r_and_b_genre_line_reads_an(self, ctx):
        line = _one(_song(mood_tags=["romantic"], genre_tags=["r&b"], energy=0.5, acousticness=0.3), context=ctx)
        assert "a R&B" not in line and "A R&B" not in line

    def test_no_em_dash(self, ctx):
        lines = explain_playlist([_song(spotify_uri=str(i)) for i in range(10)], "energy", ctx)
        assert not any("—" in l for l in lines)


class TestTempoWords:
    """Tempo is shown only as a plain word, and only when the corrected tempo is trusted."""

    @staticmethod
    def _lines(**overrides):
        return explain_playlist([_song(**overrides)] * 4, "rest", build_context(_library(), DATE))

    def test_llm_bpm_never_shown(self, ctx):
        lines = explain_playlist([_song(bpm=b) for b in (60.0, 90.0, 152.0, None)], "rest", ctx)
        assert not any("BPM" in line or "152" in line for line in lines)

    @pytest.mark.parametrize("tempo, word", [(60.0, "slow"), (85.0, "slow"), (86.0, "mid-tempo"),
                                             (110.0, "mid-tempo"), (111.0, "up-tempo"),
                                             (172.0, "up-tempo")])
    @pytest.mark.parametrize("confidence", ["high", "medium"])
    def test_trusted_tempo_shown_as_word(self, tempo, word, confidence):
        lines = self._lines(tempo=tempo, tempo_confidence=confidence)
        assert any(f"{word} and romantic" in l.lower() for l in lines), lines

    @pytest.mark.parametrize("confidence", ["high", "medium", "low", None])
    def test_never_a_number(self, confidence):
        lines = self._lines(tempo=72.0, tempo_confidence=confidence, felt_tempo=70.0, bpm=144.0)
        assert not any(re.search(r"\d|bpm", l, re.IGNORECASE) for l in lines), lines

    @pytest.mark.parametrize("confidence", ["low", None, "unknown"])
    def test_untrusted_tempo_not_shown(self, confidence):
        lines = self._lines(tempo=72.0, tempo_confidence=confidence)
        assert not any(w in l.lower() for l in lines for w in ("slow", "mid-tempo", "up-tempo")), lines

    def test_felt_tempo_alone_not_shown(self):
        """felt_tempo is the old LLM guess; only the corrected tempo is trusted now."""
        lines = self._lines(felt_tempo=72.0)
        assert not any("slow" in l.lower() for l in lines), lines


class TestMissingData:
    def test_no_tags_no_engagement(self):
        line = _one(_song(mood_tags=None, genre_tags=None, play_count=None, engagement_score=None,
                          last_played=None, first_played=None, original_release_year=None,
                          release_year=None, energy=None, acousticness=None))
        assert line == "An easy one to settle into."

    def test_genre_only(self):
        line = _one(_song(mood_tags=[], genre_tags=["sufi"], energy=None, acousticness=None,
                          play_count=None, engagement_score=None))
        assert line.startswith("A Sufi song that")

    def test_skip_moods_and_genres(self):
        line = _one(_song(mood_tags=["protest", "modern"], genre_tags=["romantic", "remix"],
                          energy=None, acousticness=None))
        assert "protest" not in line and "remix" not in line

    def test_missing_neuro_scores_uses_days_purpose(self):
        line = _one(_song(parasympathetic=None, sympathetic=None, grounding=None))
        assert any(w in line for w in ("settle", "unwind", "pace", "calm")), line

    def test_bad_dates_ignored(self):
        assert _one(_song(last_played="not-a-date", first_played="??"))

    def test_unknown_engagement_claims_nothing_about_it(self):
        line = _one(_song(play_count=None, engagement_score=None))
        assert not re.search(r"favourite|play a lot|coming back|deeper cut", line), line


class TestPersonalFacts:
    def test_most_played(self, ctx):
        assert "One you play a lot." in _one(_song(play_count=95), context=ctx)

    def test_long_time_favourite_needs_old_first_play(self, ctx):
        assert "A long-time favourite." in _one(
            _song(play_count=95, first_played="2020-02-05T00:00:00Z"), context=ctx)
        assert "long-time" not in _one(_song(play_count=95, first_played="2025-06-01"), context=ctx)

    def test_never_exact_counts(self, ctx):
        for plays in (12, 50, 95):
            assert not EXACT_COUNTS.search(_one(_song(play_count=plays), context=ctx))

    def test_played_this_week(self, ctx):
        assert "this week" in _one(_song(last_played="2026-10-18T08:00:00Z"), context=ctx)

    def test_played_this_month(self, ctx):
        assert "past month" in _one(_song(last_played="2026-10-01T08:00:00Z"), context=ctx)

    def test_rediscovery_only_with_fresh_history(self, ctx, stale_ctx):
        old = _song(last_played="2023-05-01T08:00:00Z")
        assert "Not played in a while." in _one(old, context=ctx)
        assert "while" not in _one(old, context=stale_ctx)

    def test_deep_cut_only_with_fresh_history(self, ctx, stale_ctx):
        assert "deeper cut" in _one(_song(play_count=2), context=ctx)
        assert "deeper cut" not in _one(_song(play_count=2), context=stale_ctx)

    def test_classic(self, ctx):
        assert "A 1973 classic." in _one(_song(original_release_year=1973), context=ctx)

    def test_new_release(self, ctx):
        assert "A recent release." in _one(_song(original_release_year=2026), context=ctx)

    def test_engaged_when_nothing_else(self, ctx):
        assert "keep coming back" in _one(_song(play_count=20, engagement_score=0.99), context=ctx)


class TestPlaylistLevel:
    def _playlist(self, n=20):
        moods = [["romantic", "nostalgic"], ["uplifting", "romantic"], ["reflective", "melancholic"]]
        return [_song(spotify_uri=f"spotify:track:{i}", mood_tags=moods[i % 3],
                      play_count=(i * 7) % 100, energy=0.2 + (i % 5) * 0.15,
                      parasympathetic=0.8 if i % 4 else 0.2, sympathetic=0.2 if i % 4 else 0.9,
                      last_played=f"2026-{(i % 9) + 1:02d}-15T10:00:00Z") for i in range(n)]

    def test_all_lines_distinct(self, ctx):
        lines = explain_playlist(self._playlist(), "rest", ctx)
        assert len(set(lines)) == len(lines)

    def test_identical_songs_get_distinct_lines(self, ctx):
        lines = explain_playlist([_song() for _ in range(6)], "rest", ctx)
        assert len(set(lines)) == 6

    def test_sentence_shapes_vary(self, ctx):
        lines = explain_playlist(self._playlist(), "rest", ctx)
        starts_with_purpose = sum(l.startswith(("An easy", "A gentle", "A calm", "A little")) for l in lines)
        uses_that = sum(" that " in l for l in lines)
        assert starts_with_purpose >= 3 and uses_that >= 3

    def test_deterministic(self, ctx):
        songs = self._playlist()
        assert explain_playlist(songs, "rest", ctx) == explain_playlist(songs, "rest", ctx)

    @pytest.mark.parametrize("state", ["rest", "energy", "grounding"])
    def test_guardrails(self, ctx, state):
        songs = self._playlist() + [_song(mood_tags=["light-hearted", "celebratory", "x"],
                                          genre_tags=["hip-hop"], tempo=128.0,
                                          tempo_confidence="high",
                                          play_count=99, original_release_year=1970)]
        for line in explain_playlist(songs, state, ctx):
            assert len(line) < 80, line
            assert len(line) <= MAX_WHY_LENGTH
            assert not BODY_CLAIMS.search(line), line
            assert not STATE_NAMES.search(line), line
            assert not EXACT_COUNTS.search(line), line
            assert "—" not in line
            assert line.count(",") <= 1, line  # no comma pile-ups
            assert line.endswith(".")

    def test_empty_playlist(self, ctx):
        assert explain_playlist([], "rest", ctx) == []


class TestCapitalizeFirst:
    @pytest.mark.parametrize("text, expected", [("", ""), ("a", "A"), ("less REM", "Less REM"),
                                                ("R&B", "R&B")])
    def test_only_the_first_letter_changes(self, text, expected):
        assert capitalize_first(text) == expected
