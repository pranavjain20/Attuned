"""Tests for classification/tempo.py — turning raw tempo readings into the scored tempo."""

import json

import pytest

from classification.tempo import (
    TempoDecision,
    find_tracker_consensus,
    parse_llm_bpm,
    resolve_tempo,
    set_manual_tempo,
    update_tempos,
)
from db import queries


def _song(
    *,
    essentia: float | None = None,
    degara: float | None = None,
    cnn: float | None = None,
    soundcharts: float | None = None,
    genres: list[str] | None = None,
    moods: list[str] | None = None,
    bpm: float | None = None,
    tempo: float | None = None,
    tempo_source: str | None = None,
    tempo_confidence: str | None = None,
) -> dict:
    return {
        "essentia_bpm": essentia,
        "essentia_degara_bpm": degara,
        "tempocnn_bpm": cnn,
        "soundcharts_tempo": soundcharts,
        "genre_tags": genres or ["bollywood"],
        "mood_tags": moods or [],
        "bpm": bpm,
        "tempo": tempo,
        "tempo_source": tempo_source,
        "tempo_confidence": tempo_confidence,
    }


# ---------------------------------------------------------------------------
# Tracker consensus
# ---------------------------------------------------------------------------

class TestFindTrackerConsensus:
    def test_three_agreeing_trackers_give_their_median(self):
        consensus = find_tracker_consensus([107.9, 107.8, 108.0])
        assert consensus.tempo == pytest.approx(107.9)
        assert consensus.agreeing == 3

    def test_octave_disagreement_still_counts_as_agreement(self):
        """Khuda Jaane: RE 79, CNN 160 — same pulse, different octave."""
        consensus = find_tracker_consensus([79.0, 79.5, 160.0])
        assert consensus.agreeing == 3
        assert consensus.tempo == pytest.approx(79.5, abs=0.6)

    def test_reported_level_is_where_most_trackers_read_it(self):
        """POPSTAR: RE/Degara read 163, CNN reads 81 — trackers report 163."""
        consensus = find_tracker_consensus([163.1, 163.1, 81.0])
        assert consensus.reported == pytest.approx(163.1, abs=0.5)
        assert consensus.reported_unanimous is False
        assert consensus.reported_by == 2

    def test_reported_level_unanimous_when_all_trackers_match(self):
        consensus = find_tracker_consensus([150.2, 150.2, 150.0])
        assert consensus.reported == pytest.approx(150.2, abs=0.2)
        assert consensus.reported_unanimous is True

    def test_non_octave_disagreement_leaves_the_odd_one_out(self):
        """Life Is Good: RE/CNN 82, Degara 109 (a 4:3 confusion)."""
        consensus = find_tracker_consensus([81.7, 109.1, 82.0])
        assert consensus.agreeing == 2
        assert consensus.tempo == pytest.approx(81.85, abs=0.2)

    def test_agreement_across_the_fold_boundary(self):
        """69.8 and 140.5 are one octave apart even though they fold to opposite edges."""
        consensus = find_tracker_consensus([69.8, 140.5])
        assert consensus.agreeing == 2

    def test_ignores_missing_and_zero_readings(self):
        consensus = find_tracker_consensus([None, 0.0, 120.0])
        assert consensus.agreeing == 1
        assert consensus.total == 1
        assert consensus.tempo == pytest.approx(120.0)

    def test_no_readings_returns_none(self):
        assert find_tracker_consensus([None, None, 0.0]) is None


# ---------------------------------------------------------------------------
# resolve_tempo: audio + LLM octave (the main rule)
# ---------------------------------------------------------------------------

class TestResolveTempoAudio:
    def test_double_time_ballad_is_halved_to_the_llm_octave(self):
        """Tere Mast Mast Do Nain: trackers 152, LLM 80 → 76."""
        decision = resolve_tempo(
            _song(essentia=152.0, degara=152.2, cnn=152.0, moods=["romantic", "nostalgic"]), 80,
        )
        assert decision.tempo == pytest.approx(76.0, abs=0.2)
        assert decision.source == "audio+llm_octave"
        assert decision.confidence == "high"

    def test_precise_audio_number_beats_round_llm_guess(self):
        """Bhool Bhulaiyaa: trackers 108, LLM 128 → 108 (number from audio)."""
        decision = resolve_tempo(_song(essentia=107.9, degara=107.8, cnn=108.0), 128)
        assert decision.tempo == pytest.approx(107.9, abs=0.1)

    def test_llm_octave_doubles_a_half_time_reading(self):
        """Rangisari: trackers 70, LLM 120 → 140."""
        decision = resolve_tempo(
            _song(essentia=70.0, degara=70.0, cnn=70.0, moods=["joyful", "celebratory"]), 120,
        )
        assert decision.tempo == pytest.approx(140.0, abs=0.2)

    def test_octave_window_stops_llm_pushing_past_165(self):
        """What You Know Bout Love (no hip-hop tag here): LLM 140 would pick 168, window keeps 84."""
        decision = resolve_tempo(_song(essentia=84.0, degara=84.0, cnn=168.0, genres=["r&b"]), 140)
        assert decision.tempo == pytest.approx(84.0, abs=0.1)

    def test_octave_window_floor_is_55(self):
        decision = resolve_tempo(_song(essentia=104.0, degara=104.0, cnn=104.0), 40)
        assert decision.tempo == pytest.approx(104.0, abs=0.1)

    def test_llm_near_the_midpoint_is_low_confidence(self):
        """Ajab Si: trackers 118, LLM 85 sits between 59 and 118 — no octave information."""
        decision = resolve_tempo(
            _song(essentia=117.7, degara=117.9, cnn=118.0, moods=["romantic", "nostalgic"]), 85,
        )
        assert decision.confidence == "low"

    def test_halving_into_very_slow_tempo_is_low_confidence(self):
        """Is This Love: halved to 62 — a listener could defensibly clap 125."""
        decision = resolve_tempo(
            _song(essentia=125.0, degara=125.0, cnn=125.0, moods=["romantic", "reflective"]), 75,
        )
        assert decision.tempo == pytest.approx(62.5, abs=0.2)
        assert decision.confidence == "low"

    def test_halving_that_stays_above_very_slow_keeps_high_confidence(self):
        """Tere Bina: 144 → 72 is a clear double-time error, not ambiguous."""
        decision = resolve_tempo(
            _song(essentia=144.0, degara=144.0, cnn=72.0, moods=["romantic", "nostalgic"]), 90,
        )
        assert decision.tempo == pytest.approx(72.0, abs=0.2)
        assert decision.confidence == "high"

    def test_two_of_three_trackers_is_medium_confidence(self):
        decision = resolve_tempo(_song(essentia=94.0, degara=94.0, cnn=126.0), 95)
        assert decision.tempo == pytest.approx(94.0, abs=0.1)
        assert decision.confidence == "medium"

    def test_single_tracker_is_low_confidence(self):
        decision = resolve_tempo(_song(essentia=111.0, degara=None, cnn=None), 110)
        assert decision.confidence == "low"

    def test_all_trackers_disagree_is_low_confidence(self):
        """Bheegi Si Bhaagi Si: RE 111, CNN 69, Degara 89 — no two agree."""
        decision = resolve_tempo(_song(essentia=111.0, degara=89.0, cnn=69.0), 85)
        assert decision.confidence == "low"

    def test_without_llm_bpm_keeps_the_reported_level(self):
        decision = resolve_tempo(_song(essentia=152.0, degara=152.0, cnn=152.0), None)
        assert decision.tempo == pytest.approx(152.0, abs=0.1)
        assert decision.source == "audio"
        assert decision.confidence == "low"

    def test_without_llm_bpm_folds_into_the_window(self):
        decision = resolve_tempo(_song(essentia=180.0, degara=180.0, cnn=180.0), None)
        assert decision.tempo == pytest.approx(90.0, abs=0.1)

    def test_tags_may_be_json_strings(self):
        song = _song(essentia=152.0, degara=152.0, cnn=152.0)
        song["genre_tags"] = json.dumps(["bollywood"])
        song["mood_tags"] = json.dumps(["romantic"])
        assert resolve_tempo(song, 80).tempo == pytest.approx(76.0, abs=0.2)


# ---------------------------------------------------------------------------
# resolve_tempo: hip-hop keeps the listed tempo (Pranav's decision)
# ---------------------------------------------------------------------------

class TestResolveTempoListedGenres:
    @pytest.mark.parametrize("readings, llm, expected, genres", [
        ((163.1, 163.1, 81.0), 90, 163.1, ["hip-hop", "rap"]),        # POPSTAR
        ((172.3, 172.3, 130.0), 87, 172.3, ["hip-hop", "rap"]),       # Lose Yourself
        ((150.2, 150.2, 150.0), 90, 150.2, ["hip-hop", "pop"]),       # INDUSTRY BABY
        ((77.4, 154.8, 155.0), 140, 154.9, ["hip-hop", "rap"]),       # Some Way
        ((146.1, 146.0, 146.0), 95, 146.0, ["hip-hop", "rap"]),       # Can't Hold Us
        ((84.0, 84.0, 168.0), 140, 84.0, ["hip-hop", "rap"]),         # What You Know Bout Love
        ((135.2, 133.0, 67.0), 80, 134.0, ["trap"]),                  # Laugh Now Cry Later
    ])
    def test_listed_tempo_not_half_time(self, readings, llm, expected, genres):
        essentia, degara, cnn = readings
        decision = resolve_tempo(
            _song(essentia=essentia, degara=degara, cnn=cnn, genres=genres, moods=["confident"]), llm,
        )
        assert decision.tempo == pytest.approx(expected, rel=0.01)
        assert decision.source == "audio_listed"

    def test_listed_level_split_between_trackers_is_medium(self):
        """Amplifier: RE/CNN 82, Degara 164 — the number is sure, the level is not."""
        decision = resolve_tempo(
            _song(essentia=81.9, degara=163.9, cnn=82.0, genres=["punjabi", "hip-hop"]), 130,
        )
        assert decision.confidence == "medium"

    def test_unanimous_listed_level_is_high(self):
        decision = resolve_tempo(
            _song(essentia=150.2, degara=150.2, cnn=150.0, genres=["hip-hop"]), 90,
        )
        assert decision.confidence == "high"

    def test_listed_tempo_from_soundcharts_without_audio(self):
        decision = resolve_tempo(_song(soundcharts=155.0, genres=["hip-hop", "trap"]), 77)
        assert decision.tempo == pytest.approx(155.0)
        assert decision.source == "soundcharts"


# ---------------------------------------------------------------------------
# resolve_tempo: energetic songs are never halved (risk guard)
# ---------------------------------------------------------------------------

class TestResolveTempoEnergeticGuard:
    def test_energetic_song_keeps_its_reported_tempo_instead_of_halving(self):
        """Sooraj Ki Baahon Mein: 125 everywhere, LLM 85 would halve it to 62."""
        decision = resolve_tempo(
            _song(essentia=125.0, degara=125.0, cnn=125.0, moods=["uplifting", "joyful"]), 85,
        )
        assert decision.tempo == pytest.approx(125.0, abs=0.1)
        assert decision.source == "audio"
        assert decision.confidence == "low"  # 125 is not a halving of anything: unchanged

    def test_energetic_guard_keeps_the_current_tempo(self):
        """Sakhiyaan: stored 164, trackers 165/165/83, LLM 120 would halve to 83 — keep 164."""
        decision = resolve_tempo(
            _song(essentia=165.3, degara=165.0, cnn=83.0, bpm=164,
                  moods=["uplifting", "celebratory"], genres=["punjabi", "pop"]), 120,
        )
        assert decision == TempoDecision(164.0, "kept_bpm", "low")

    def test_kept_half_time_tempo_is_replaced_by_the_listed_level(self):
        """Kar Har Maidaan Fateh: stored 88 is half of the 172 trackers report → 172."""
        decision = resolve_tempo(
            _song(essentia=172.3, degara=172.3, cnn=84.0, bpm=88,
                  moods=["motivational", "inspirational"]), 120,
        )
        assert decision == TempoDecision(172.3, "audio_listed", "medium")

    def test_listed_level_above_the_felt_window(self):
        """Blinding Lights: LLM 171, trackers 85.6/172.3/171 — 171 is above the 165
        window so the octave rule picks 86; the stored 88 is the same half-time."""
        decision = resolve_tempo(
            _song(essentia=85.55, degara=172.27, cnn=171.0, bpm=88,
                  moods=["energetic", "uplifting"], genres=["pop", "synthwave"]), 171,
        )
        assert decision.tempo == pytest.approx(171.6, abs=0.7)
        assert decision.source == "audio_listed"
        assert decision.confidence == "medium"

    def test_two_agreeing_trackers_are_enough_for_medium(self):
        """Bulleya: 178.2/178.2/123, stored 89 → 178.2."""
        decision = resolve_tempo(
            _song(essentia=178.21, degara=178.21, cnn=123.0, bpm=89,
                  moods=["energetic", "powerful"]), 120,
        )
        assert decision == TempoDecision(178.2, "audio_listed", "medium")

    def test_one_tracker_alone_is_low_confidence(self):
        """No two readings agree: the listed level is still preferred, but flagged."""
        decision = resolve_tempo(
            _song(essentia=171.0, degara=123.0, cnn=101.0, bpm=88, moods=["energetic"]), 88,
        )
        assert decision == TempoDecision(171.0, "audio_listed", "low")

    def test_listed_level_from_a_one_one_tracker_split_is_low_confidence(self):
        """Tera Yaar Hoon Main: 164.8 and 84 agree up to octave but split on the level,
        so only one reading backs the fast level."""
        decision = resolve_tempo(
            _song(essentia=164.79, degara=111.38, cnn=84.0, bpm=88,
                  moods=["friendly", "celebratory"]), 85,
        )
        assert decision.source == "audio_listed"
        assert decision.tempo == pytest.approx(166.4, abs=1.0)
        assert decision.confidence == "low"

    def test_soundcharts_listed_level_replaces_half_time(self):
        """Bye Bye Bye: Soundcharts 172.6, stored 91 → 172.6."""
        decision = resolve_tempo(
            _song(soundcharts=172.64, bpm=91, moods=["energetic", "fun"], genres=["pop"]), 92,
        )
        assert decision == TempoDecision(172.6, "soundcharts", "medium")

    def test_listed_level_above_185_keeps_the_current_tempo(self):
        """Chunky: Soundcharts 202 is out of range, so the stored 100 stays."""
        decision = resolve_tempo(
            _song(soundcharts=202.1, bpm=100, moods=["fun", "party"], genres=["pop"]), 100,
        )
        assert decision == TempoDecision(100.0, "kept_bpm", "low")

    def test_listed_level_at_185_is_in_range(self):
        decision = resolve_tempo(_song(soundcharts=185.0, bpm=92, moods=["energetic"]), 92)
        assert decision == TempoDecision(185.0, "soundcharts", "medium")

    def test_current_tempo_not_an_octave_of_the_listed_level_is_kept(self):
        """Attention: Soundcharts 148 vs stored 99 (a 3:2 gap, not half-time) → keep 99."""
        decision = resolve_tempo(
            _song(soundcharts=148.0, bpm=99, moods=["confident", "seductive"], genres=["pop"]), 100,
        )
        assert decision == TempoDecision(99.0, "kept_bpm", "low")

    @pytest.mark.parametrize("bpm, listed", [(80.0, True), (92.0, True), (93.5, False), (78.0, False)])
    def test_half_time_means_within_8_percent_of_half(self, bpm, listed):
        """172/2 = 86; 80 and 92 are within 8% of it, 78 and 93.5 are not."""
        decision = resolve_tempo(_song(soundcharts=172.0, bpm=bpm, moods=["energetic"]), 92)
        assert decision.source == ("soundcharts" if listed else "kept_bpm")

    def test_energetic_guard_without_current_bpm_uses_the_listed_level(self):
        """No stored tempo: halving 172 to 86 is still halving, so 172 is used."""
        decision = resolve_tempo(
            _song(essentia=172.3, degara=172.3, cnn=84.0, moods=["motivational"]), 88,
        )
        assert decision == TempoDecision(172.3, "audio_listed", "medium")

    def test_energetic_without_current_bpm_above_185_falls_back_to_the_reading(self):
        decision = resolve_tempo(_song(essentia=190.0, degara=190.0, cnn=95.0, moods=["party"]), 95)
        assert decision.tempo == pytest.approx(95.0, abs=0.1)
        assert decision.source == "audio"
        assert decision.confidence == "low"

    def test_energetic_song_without_llm_is_not_halved(self):
        decision = resolve_tempo(_song(essentia=172.0, degara=172.0, cnn=172.0, moods=["energetic"]), None)
        assert decision == TempoDecision(172.0, "audio_listed", "medium")

    def test_calm_song_without_llm_is_still_folded_into_the_window(self):
        decision = resolve_tempo(_song(essentia=172.0, degara=172.0, cnn=172.0, moods=["calm"]), None)
        assert decision == TempoDecision(86.0, "audio", "low")

    def test_listed_level_is_stable_when_rerun(self):
        """The decision reads bpm (history), never tempo, so a rerun gives the same answer."""
        song = _song(essentia=172.3, degara=172.3, cnn=84.0, bpm=88, moods=["motivational"])
        first = resolve_tempo(song, 120)
        rerun = resolve_tempo({**song, "tempo": first.tempo, "tempo_source": first.source,
                               "tempo_confidence": first.confidence}, 120)
        assert rerun == first

    def test_energetic_song_that_matches_llm_octave_is_untouched(self):
        decision = resolve_tempo(
            _song(essentia=128.0, degara=128.0, cnn=128.0, moods=["energetic", "party"]), 128,
        )
        assert decision.tempo == pytest.approx(128.0, abs=0.1)
        assert decision.confidence == "high"

    def test_energetic_song_may_be_doubled_but_is_low_confidence(self):
        """Nagada Sang Dhol: trackers 75.5, LLM 120 → 151, flagged."""
        decision = resolve_tempo(
            _song(essentia=75.5, degara=75.5, cnn=151.0, moods=["festive", "energetic"]), 120,
        )
        assert decision.tempo == pytest.approx(151.0, abs=0.3)
        assert decision.confidence == "low"

    def test_mixed_mood_song_is_not_guarded(self):
        """Tere Naina: romantic + celebratory — slow mood wins, halving allowed."""
        decision = resolve_tempo(
            _song(essentia=140.0, degara=140.0, cnn=140.0, moods=["romantic", "celebratory"]), 85,
        )
        assert decision.tempo == pytest.approx(70.0, abs=0.1)

    def test_soundcharts_energetic_song_is_not_halved(self):
        decision = resolve_tempo(_song(soundcharts=130.0, moods=["energetic", "party"]), 80)
        assert decision.tempo == pytest.approx(130.0)
        assert decision.confidence == "low"


# ---------------------------------------------------------------------------
# resolve_tempo: no audio clip
# ---------------------------------------------------------------------------

class TestResolveTempoWithoutAudio:
    def test_soundcharts_number_with_llm_octave(self):
        """Zara Sa style: Soundcharts 164, LLM 90 → 82."""
        decision = resolve_tempo(_song(soundcharts=164.0, moods=["romantic"]), 90)
        assert decision.tempo == pytest.approx(82.0)
        assert decision.source == "soundcharts+llm_octave"
        assert decision.confidence == "medium"

    def test_soundcharts_is_never_high_confidence(self):
        decision = resolve_tempo(_song(soundcharts=100.0), 100)
        assert decision.confidence == "medium"

    def test_soundcharts_without_llm_is_low(self):
        decision = resolve_tempo(_song(soundcharts=100.0), None)
        assert decision.tempo == pytest.approx(100.0)
        assert decision.confidence == "low"

    def test_llm_only(self):
        decision = resolve_tempo(_song(), 92)
        assert decision == TempoDecision(92.0, "llm", "low")

    def test_falls_back_to_stored_bpm(self):
        decision = resolve_tempo(_song(bpm=101.0), None)
        assert decision == TempoDecision(101.0, "bpm", "low")

    def test_nothing_known_gives_no_tempo(self):
        assert resolve_tempo(_song(), None) == TempoDecision(None, None, None)


class TestResolveTempoManual:
    def test_manual_tempo_is_never_overwritten(self):
        song = _song(essentia=152.0, degara=152.0, cnn=152.0,
                     tempo=150.0, tempo_source="manual", tempo_confidence="high")
        assert resolve_tempo(song, 80) == TempoDecision(150.0, "manual", "high")


# ---------------------------------------------------------------------------
# update_tempos — the single writer of tempo
# ---------------------------------------------------------------------------

def _seed(db_conn, uri, name, *, llm_bpm=None, **columns):
    queries.upsert_song(db_conn, uri, name, "Artist")
    raw = json.dumps({"songs": [{"title": name, "artist": "Artist", "bpm": llm_bpm}]}) \
        if llm_bpm is not None else None
    queries.upsert_song_classification(db_conn, {
        "spotify_uri": uri, "bpm": columns.pop("bpm", None), "valence": 0.5,
        "genre_tags": columns.pop("genre_tags", ["bollywood"]),
        "mood_tags": columns.pop("mood_tags", ["romantic"]),
        "classification_source": "essentia+llm", "raw_response": raw,
    })
    if columns:
        sets = ", ".join(f"{k} = ?" for k in columns)
        db_conn.execute(f"UPDATE song_classifications SET {sets} WHERE spotify_uri = ?",
                        (*columns.values(), uri))
        db_conn.commit()


def _tempo_row(db_conn, uri):
    return dict(db_conn.execute(
        "SELECT bpm, tempo, tempo_source, tempo_confidence FROM song_classifications "
        "WHERE spotify_uri = ?", (uri,),
    ).fetchone())


class TestUpdateTempos:
    def test_writes_tempo_from_readings_and_llm_bpm(self, db_conn):
        _seed(db_conn, "uri:1", "Tere Mast", llm_bpm=80, bpm=154,
              essentia_bpm=152.0, essentia_degara_bpm=152.2, tempocnn_bpm=152.0)
        update_tempos(db_conn)
        row = _tempo_row(db_conn, "uri:1")
        assert row["tempo"] == pytest.approx(76.0, abs=0.2)
        assert row["tempo_source"] == "audio+llm_octave"
        assert row["tempo_confidence"] == "high"

    def test_never_touches_bpm(self, db_conn):
        _seed(db_conn, "uri:1", "Tere Mast", llm_bpm=80, bpm=154,
              essentia_bpm=152.0, essentia_degara_bpm=152.2, tempocnn_bpm=152.0)
        update_tempos(db_conn)
        assert _tempo_row(db_conn, "uri:1")["bpm"] == 154

    def test_keeps_manual_tempo(self, db_conn):
        _seed(db_conn, "uri:1", "Kyon", llm_bpm=80, essentia_bpm=122.0,
              tempo=122.0, tempo_source="manual", tempo_confidence="high")
        update_tempos(db_conn)
        assert _tempo_row(db_conn, "uri:1")["tempo"] == 122.0
        assert _tempo_row(db_conn, "uri:1")["tempo_source"] == "manual"

    def test_is_idempotent(self, db_conn):
        _seed(db_conn, "uri:1", "A", llm_bpm=80, essentia_bpm=152.0, tempocnn_bpm=76.0)
        _seed(db_conn, "uri:2", "B", llm_bpm=95, soundcharts_tempo=190.0)
        _seed(db_conn, "uri:3", "C", llm_bpm=None, bpm=99)
        update_tempos(db_conn)
        first = [_tempo_row(db_conn, u) for u in ("uri:1", "uri:2", "uri:3")]
        update_tempos(db_conn)
        assert [_tempo_row(db_conn, u) for u in ("uri:1", "uri:2", "uri:3")] == first

    def test_returns_counts_by_source_and_confidence(self, db_conn):
        _seed(db_conn, "uri:1", "A", llm_bpm=80, essentia_bpm=152.0,
              essentia_degara_bpm=152.0, tempocnn_bpm=152.0)
        _seed(db_conn, "uri:2", "B", llm_bpm=95)
        stats = update_tempos(db_conn)
        assert stats["updated"] == 2
        assert stats["by_source"] == {"audio+llm_octave": 1, "llm": 1}
        assert stats["by_confidence"] == {"high": 1, "low": 1}

    def test_unmatched_raw_response_falls_back_to_stored_bpm(self, db_conn):
        _seed(db_conn, "uri:1", "Title", bpm=88)
        db_conn.execute("UPDATE song_classifications SET raw_response = ? WHERE spotify_uri = 'uri:1'",
                        (json.dumps({"songs": [{"title": "Other", "artist": "X", "bpm": 120}]}),))
        update_tempos(db_conn)
        assert _tempo_row(db_conn, "uri:1")["tempo"] == 88


# ---------------------------------------------------------------------------
# set_manual_tempo
# ---------------------------------------------------------------------------

class TestSetManualTempo:
    def test_sets_by_uri(self, db_conn):
        _seed(db_conn, "spotify:track:abc", "Kyon", llm_bpm=80)
        matched = set_manual_tempo(db_conn, "spotify:track:abc", 122)
        assert [m["spotify_uri"] for m in matched] == ["spotify:track:abc"]
        row = _tempo_row(db_conn, "spotify:track:abc")
        assert (row["tempo"], row["tempo_source"], row["tempo_confidence"]) == (122.0, "manual", "high")

    def test_sets_by_title_case_insensitive(self, db_conn):
        _seed(db_conn, "uri:1", "Ajab Si", llm_bpm=85)
        set_manual_tempo(db_conn, "ajab si", 59)
        assert _tempo_row(db_conn, "uri:1")["tempo"] == 59.0

    def test_ambiguous_title_raises_and_changes_nothing(self, db_conn):
        _seed(db_conn, "uri:1", "Lemonade", llm_bpm=140)
        _seed(db_conn, "uri:2", "Lemonade", llm_bpm=90)
        with pytest.raises(ValueError, match="2 songs"):
            set_manual_tempo(db_conn, "Lemonade", 140)
        assert _tempo_row(db_conn, "uri:1")["tempo"] is None

    def test_unknown_song_raises(self, db_conn):
        with pytest.raises(ValueError, match="No classified song"):
            set_manual_tempo(db_conn, "Nope", 100)

    @pytest.mark.parametrize("bpm", [0, 29.9, 300.1, -5])
    def test_rejects_implausible_bpm(self, db_conn, bpm):
        _seed(db_conn, "uri:1", "Song", llm_bpm=100)
        with pytest.raises(ValueError, match="between 30 and 300"):
            set_manual_tempo(db_conn, "uri:1", bpm)

    def test_manual_tempo_survives_update_tempos(self, db_conn):
        _seed(db_conn, "uri:1", "Kyon", llm_bpm=80, essentia_bpm=122.0)
        set_manual_tempo(db_conn, "uri:1", 122)
        update_tempos(db_conn)
        assert _tempo_row(db_conn, "uri:1")["tempo_source"] == "manual"


class TestParseLlmBpm:
    @pytest.mark.parametrize("bpm", ["abc", 0, 29, 29.9, 301, 300.1, None, float("nan"), float("inf"), [120]])
    def test_missing_or_implausible_is_none(self, bpm):
        assert parse_llm_bpm({"bpm": bpm}) is None

    @pytest.mark.parametrize("bpm, expected", [(30, 30.0), (300, 300.0), (120, 120.0), ("96", 96.0), (76.5, 76.5)])
    def test_plausible_bpm_is_a_float(self, bpm, expected):
        result = parse_llm_bpm({"bpm": bpm})
        assert result == expected and isinstance(result, float)

    @pytest.mark.parametrize("llm_result", [None, {}, {"title": "no bpm"}])
    def test_no_result_or_no_bpm_is_none(self, llm_result):
        assert parse_llm_bpm(llm_result) is None
