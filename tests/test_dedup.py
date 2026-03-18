"""Tests for spotify/dedup.py — duplicate song consolidation."""

import json
from unittest.mock import patch

import pytest

from db import queries
from spotify.dedup import (
    _delete_duplicate_classifications,
    _delete_duplicate_songs,
    _find_duplicate_groups,
    _merge_song_metadata,
    _pick_canonical_uri,
    _reassign_listening_history,
    consolidate_duplicate_songs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_song(conn, uri, name="Song", artist="Artist", duration_ms=240000,
                 play_count=0, sources=None, first_played=None, last_played=None):
    """Insert a song with given attributes."""
    sources = sources or []
    conn.execute(
        """INSERT INTO songs (spotify_uri, name, artist, duration_ms, play_count,
                              sources, first_played, last_played)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (uri, name, artist, duration_ms, play_count,
         json.dumps(sources), first_played, last_played),
    )
    conn.commit()


def _insert_play(conn, uri, played_at, ms_played=180000,
                 reason_start="clickrow", reason_end="trackdone", skipped=0):
    """Insert a listening history record."""
    conn.execute(
        """INSERT INTO listening_history
               (spotify_uri, played_at, ms_played, reason_start, reason_end, skipped)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uri, played_at, ms_played, reason_start, reason_end, skipped),
    )
    conn.commit()


def _insert_classification(conn, uri, bpm=120.0, energy=0.7):
    """Insert a song classification record."""
    conn.execute(
        """INSERT INTO song_classifications (spotify_uri, bpm, energy)
           VALUES (?, ?, ?)""",
        (uri, bpm, energy),
    )
    conn.commit()


def _count_songs(conn):
    """Count all rows in the songs table."""
    return conn.execute("SELECT COUNT(*) as cnt FROM songs").fetchone()["cnt"]


def _count_history(conn, uri=None):
    """Count listening_history rows, optionally filtered by URI."""
    if uri:
        return conn.execute(
            "SELECT COUNT(*) as cnt FROM listening_history WHERE spotify_uri = ?",
            (uri,),
        ).fetchone()["cnt"]
    return conn.execute("SELECT COUNT(*) as cnt FROM listening_history").fetchone()["cnt"]


def _count_classifications(conn, uri=None):
    """Count song_classifications rows, optionally filtered by URI."""
    if uri:
        return conn.execute(
            "SELECT COUNT(*) as cnt FROM song_classifications WHERE spotify_uri = ?",
            (uri,),
        ).fetchone()["cnt"]
    return conn.execute(
        "SELECT COUNT(*) as cnt FROM song_classifications"
    ).fetchone()["cnt"]


# ---------------------------------------------------------------------------
# _find_duplicate_groups
# ---------------------------------------------------------------------------

class TestFindDuplicateGroups:
    def test_no_duplicates(self, db_conn):
        """No duplicates found when all songs have unique name+artist."""
        _insert_song(db_conn, "uri:1", name="Song A", artist="Artist X")
        _insert_song(db_conn, "uri:2", name="Song B", artist="Artist Y")

        groups = _find_duplicate_groups(db_conn)

        assert groups == []

    def test_finds_exact_name_match(self, db_conn):
        """Two songs with same name and artist are grouped."""
        _insert_song(db_conn, "uri:1", name="Blinding Lights", artist="The Weeknd")
        _insert_song(db_conn, "uri:2", name="Blinding Lights", artist="The Weeknd")

        groups = _find_duplicate_groups(db_conn)

        assert len(groups) == 1
        name, artist, uris = groups[0]
        assert name == "blinding lights"
        assert artist == "the weeknd"
        assert set(uris) == {"uri:1", "uri:2"}

    def test_case_insensitive_matching(self, db_conn):
        """Name/artist matching is case-insensitive."""
        _insert_song(db_conn, "uri:1", name="Blinding Lights", artist="The Weeknd")
        _insert_song(db_conn, "uri:2", name="BLINDING LIGHTS", artist="THE WEEKND")

        groups = _find_duplicate_groups(db_conn)

        assert len(groups) == 1
        assert len(groups[0][2]) == 2

    def test_trims_whitespace(self, db_conn):
        """Leading/trailing whitespace is trimmed before matching."""
        _insert_song(db_conn, "uri:1", name="  Song A  ", artist="  Artist X  ")
        _insert_song(db_conn, "uri:2", name="Song A", artist="Artist X")

        groups = _find_duplicate_groups(db_conn)

        assert len(groups) == 1

    def test_different_artist_not_grouped(self, db_conn):
        """Songs with same name but different artist are NOT grouped."""
        _insert_song(db_conn, "uri:1", name="Stay", artist="The Kid LAROI")
        _insert_song(db_conn, "uri:2", name="Stay", artist="Rihanna")

        groups = _find_duplicate_groups(db_conn)

        assert groups == []

    def test_three_plus_uris_same_song(self, db_conn):
        """Three URIs for the same song form one group with all three URIs."""
        _insert_song(db_conn, "uri:1", name="Heat Waves", artist="Glass Animals")
        _insert_song(db_conn, "uri:2", name="Heat Waves", artist="Glass Animals")
        _insert_song(db_conn, "uri:3", name="Heat Waves", artist="Glass Animals")

        groups = _find_duplicate_groups(db_conn)

        assert len(groups) == 1
        assert len(groups[0][2]) == 3

    def test_multiple_duplicate_groups(self, db_conn):
        """Multiple distinct duplicate groups are found independently."""
        _insert_song(db_conn, "uri:a1", name="Song A", artist="Artist 1")
        _insert_song(db_conn, "uri:a2", name="Song A", artist="Artist 1")
        _insert_song(db_conn, "uri:b1", name="Song B", artist="Artist 2")
        _insert_song(db_conn, "uri:b2", name="Song B", artist="Artist 2")
        _insert_song(db_conn, "uri:c1", name="Song C", artist="Artist 3")  # no dup

        groups = _find_duplicate_groups(db_conn)

        assert len(groups) == 2

    def test_empty_database(self, db_conn):
        """No songs in DB returns empty list."""
        groups = _find_duplicate_groups(db_conn)
        assert groups == []


# ---------------------------------------------------------------------------
# _pick_canonical_uri
# ---------------------------------------------------------------------------

class TestPickCanonicalUri:
    def test_picks_uri_with_most_meaningful_plays(self, db_conn):
        """URI with more >30s plays wins."""
        _insert_song(db_conn, "uri:few", name="Song", artist="Art", sources=["extended_history"])
        _insert_song(db_conn, "uri:many", name="Song", artist="Art", sources=["extended_history"])
        # uri:few has 1 meaningful play
        _insert_play(db_conn, "uri:few", "2026-01-01T10:00:00Z", ms_played=60000)
        # uri:many has 3 meaningful plays
        _insert_play(db_conn, "uri:many", "2026-01-01T10:00:00Z", ms_played=60000)
        _insert_play(db_conn, "uri:many", "2026-01-02T10:00:00Z", ms_played=60000)
        _insert_play(db_conn, "uri:many", "2026-01-03T10:00:00Z", ms_played=60000)

        result = _pick_canonical_uri(db_conn, ["uri:few", "uri:many"])

        assert result == "uri:many"

    def test_tiebreaker_prefers_liked_source(self, db_conn):
        """When play counts tie, URI with 'liked' in sources wins."""
        _insert_song(db_conn, "uri:liked", name="Song", artist="Art",
                     sources=["liked", "extended_history"])
        _insert_song(db_conn, "uri:plain", name="Song", artist="Art",
                     sources=["extended_history"])
        # Equal meaningful plays
        _insert_play(db_conn, "uri:liked", "2026-01-01T10:00:00Z", ms_played=60000)
        _insert_play(db_conn, "uri:plain", "2026-01-01T10:00:00Z", ms_played=60000)

        result = _pick_canonical_uri(db_conn, ["uri:liked", "uri:plain"])

        assert result == "uri:liked"

    def test_tiebreaker_prefers_top_track_source(self, db_conn):
        """When play counts tie, URI with 'top_track' in sources wins."""
        _insert_song(db_conn, "uri:top", name="Song", artist="Art",
                     sources=["top_track"])
        _insert_song(db_conn, "uri:plain", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_play(db_conn, "uri:top", "2026-01-01T10:00:00Z", ms_played=60000)
        _insert_play(db_conn, "uri:plain", "2026-01-01T10:00:00Z", ms_played=60000)

        result = _pick_canonical_uri(db_conn, ["uri:top", "uri:plain"])

        assert result == "uri:top"

    def test_lexicographic_final_tiebreaker(self, db_conn):
        """When play counts and sources are identical, max URI wins (lexicographic)."""
        _insert_song(db_conn, "uri:aaa", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_song(db_conn, "uri:zzz", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_play(db_conn, "uri:aaa", "2026-01-01T10:00:00Z", ms_played=60000)
        _insert_play(db_conn, "uri:zzz", "2026-01-01T10:00:00Z", ms_played=60000)

        result = _pick_canonical_uri(db_conn, ["uri:aaa", "uri:zzz"])

        # max() with the sort key: same count (1), same preferred (False), then max URI
        assert result == "uri:zzz"

    def test_no_plays_for_any_uri(self, db_conn):
        """When no URI has plays, falls back to sources then lexicographic."""
        _insert_song(db_conn, "uri:aaa", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_song(db_conn, "uri:zzz", name="Song", artist="Art",
                     sources=["extended_history"])

        result = _pick_canonical_uri(db_conn, ["uri:aaa", "uri:zzz"])

        # Both have 0 plays, neither preferred, max by URI
        assert result == "uri:zzz"

    def test_short_plays_not_counted(self, db_conn):
        """Plays under 30s are not counted toward canonical selection."""
        _insert_song(db_conn, "uri:short", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_song(db_conn, "uri:long", name="Song", artist="Art",
                     sources=["extended_history"])
        # uri:short has many short plays
        for i in range(10):
            _insert_play(db_conn, "uri:short", f"2026-01-{i+1:02d}T10:00:00Z",
                         ms_played=5000)
        # uri:long has one meaningful play
        _insert_play(db_conn, "uri:long", "2026-01-01T10:00:00Z", ms_played=60000)

        result = _pick_canonical_uri(db_conn, ["uri:short", "uri:long"])

        assert result == "uri:long"

    def test_play_count_overrides_source_preference(self, db_conn):
        """More plays beats 'liked' source when counts differ."""
        _insert_song(db_conn, "uri:liked", name="Song", artist="Art",
                     sources=["liked"])
        _insert_song(db_conn, "uri:many", name="Song", artist="Art",
                     sources=["extended_history"])
        # uri:liked has 1 play, uri:many has 5
        _insert_play(db_conn, "uri:liked", "2026-01-01T10:00:00Z", ms_played=60000)
        for i in range(5):
            _insert_play(db_conn, "uri:many", f"2026-01-{i+1:02d}T10:00:00Z",
                         ms_played=60000)

        result = _pick_canonical_uri(db_conn, ["uri:liked", "uri:many"])

        assert result == "uri:many"


# ---------------------------------------------------------------------------
# _reassign_listening_history
# ---------------------------------------------------------------------------

class TestReassignListeningHistory:
    def test_moves_plays_to_canonical(self, db_conn):
        """Plays from other URIs are reassigned to canonical URI."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")
        _insert_play(db_conn, "uri:other", "2026-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:other", "2026-01-02T10:00:00Z")

        _reassign_listening_history(db_conn, "uri:canonical", ["uri:other"])

        assert _count_history(db_conn, "uri:canonical") == 2
        assert _count_history(db_conn, "uri:other") == 0

    def test_handles_timestamp_conflict_silently(self, db_conn):
        """When canonical already has a play at same timestamp, duplicate is dropped."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")
        # Both have a play at the same timestamp
        _insert_play(db_conn, "uri:canonical", "2026-01-01T10:00:00Z", ms_played=200000)
        _insert_play(db_conn, "uri:other", "2026-01-01T10:00:00Z", ms_played=180000)
        # uri:other has a unique play too
        _insert_play(db_conn, "uri:other", "2026-01-02T10:00:00Z", ms_played=180000)

        _reassign_listening_history(db_conn, "uri:canonical", ["uri:other"])

        # Canonical keeps its original + the non-conflicting one = 2
        assert _count_history(db_conn, "uri:canonical") == 2
        assert _count_history(db_conn, "uri:other") == 0
        # Total should be 2 (1 conflicting was dropped)
        assert _count_history(db_conn) == 2

    def test_multiple_others(self, db_conn):
        """Plays from multiple duplicate URIs all move to canonical."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:dup1", name="Song", artist="Art")
        _insert_song(db_conn, "uri:dup2", name="Song", artist="Art")
        _insert_play(db_conn, "uri:dup1", "2026-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:dup2", "2026-01-02T10:00:00Z")

        _reassign_listening_history(db_conn, "uri:canonical", ["uri:dup1", "uri:dup2"])

        assert _count_history(db_conn, "uri:canonical") == 2
        assert _count_history(db_conn, "uri:dup1") == 0
        assert _count_history(db_conn, "uri:dup2") == 0

    def test_no_plays_to_reassign(self, db_conn):
        """When other URIs have no plays, nothing happens (no errors)."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")
        _insert_play(db_conn, "uri:canonical", "2026-01-01T10:00:00Z")

        _reassign_listening_history(db_conn, "uri:canonical", ["uri:other"])

        assert _count_history(db_conn, "uri:canonical") == 1

    def test_preserves_play_metadata(self, db_conn):
        """Reassigned plays keep their ms_played, reason_start, etc."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")
        _insert_play(db_conn, "uri:other", "2026-01-01T10:00:00Z",
                     ms_played=99999, reason_start="fwdbtn", reason_end="trackdone",
                     skipped=1)

        _reassign_listening_history(db_conn, "uri:canonical", ["uri:other"])

        row = db_conn.execute(
            "SELECT * FROM listening_history WHERE spotify_uri = ?",
            ("uri:canonical",),
        ).fetchone()
        assert row["ms_played"] == 99999
        assert row["reason_start"] == "fwdbtn"
        assert row["reason_end"] == "trackdone"
        assert row["skipped"] == 1


# ---------------------------------------------------------------------------
# _merge_song_metadata
# ---------------------------------------------------------------------------

class TestMergeSongMetadata:
    def test_merges_sources(self, db_conn):
        """Sources from all duplicates are merged into canonical."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     sources=["liked"])
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     sources=["extended_history", "top_track"])

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        sources = json.loads(song["sources"])
        assert set(sources) == {"liked", "extended_history", "top_track"}

    def test_takes_earliest_first_played(self, db_conn):
        """Earliest first_played across all duplicates is used."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     first_played="2025-06-01T00:00:00Z")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     first_played="2024-01-01T00:00:00Z")

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        assert song["first_played"] == "2024-01-01T00:00:00Z"

    def test_takes_latest_last_played(self, db_conn):
        """Latest last_played across all duplicates is used."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     last_played="2025-01-01T00:00:00Z")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     last_played="2026-03-01T00:00:00Z")

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        assert song["last_played"] == "2026-03-01T00:00:00Z"

    def test_keeps_canonical_duration(self, db_conn):
        """Canonical song's duration_ms is preferred."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     duration_ms=240000)
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     duration_ms=245000)

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        assert song["duration_ms"] == 240000

    def test_falls_back_to_duplicate_duration_when_canonical_missing(self, db_conn):
        """When canonical has no duration, grabs from a duplicate."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     duration_ms=None)
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     duration_ms=200000)

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        assert song["duration_ms"] == 200000

    def test_handles_null_dates(self, db_conn):
        """Null first_played/last_played on some duplicates are handled gracefully."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     first_played=None, last_played="2026-01-01T00:00:00Z")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     first_played="2024-06-01T00:00:00Z", last_played=None)

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        assert song["first_played"] == "2024-06-01T00:00:00Z"
        assert song["last_played"] == "2026-01-01T00:00:00Z"

    def test_deduplicates_sources(self, db_conn):
        """Overlapping sources are deduplicated."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     sources=["liked", "extended_history"])
        _insert_song(db_conn, "uri:other", name="Song", artist="Art",
                     sources=["liked", "top_track"])

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:other"])

        song = queries.get_song(db_conn, "uri:canonical")
        sources = json.loads(song["sources"])
        assert sorted(sources) == ["extended_history", "liked", "top_track"]

    def test_three_duplicates_merged(self, db_conn):
        """Metadata from 3+ duplicates all merges correctly."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art",
                     sources=["liked"], first_played="2025-06-01T00:00:00Z",
                     last_played="2025-12-01T00:00:00Z", duration_ms=240000)
        _insert_song(db_conn, "uri:dup1", name="Song", artist="Art",
                     sources=["extended_history"], first_played="2024-01-01T00:00:00Z",
                     last_played="2025-06-01T00:00:00Z", duration_ms=None)
        _insert_song(db_conn, "uri:dup2", name="Song", artist="Art",
                     sources=["top_track"], first_played="2025-03-01T00:00:00Z",
                     last_played="2026-03-01T00:00:00Z", duration_ms=245000)

        _merge_song_metadata(db_conn, "uri:canonical", ["uri:dup1", "uri:dup2"])

        song = queries.get_song(db_conn, "uri:canonical")
        sources = json.loads(song["sources"])
        assert set(sources) == {"liked", "extended_history", "top_track"}
        assert song["first_played"] == "2024-01-01T00:00:00Z"
        assert song["last_played"] == "2026-03-01T00:00:00Z"
        assert song["duration_ms"] == 240000  # canonical's value


# ---------------------------------------------------------------------------
# _delete_duplicate_classifications
# ---------------------------------------------------------------------------

class TestDeleteDuplicateClassifications:
    def test_removes_classifications_for_others(self, db_conn):
        """Classifications for non-canonical URIs are deleted."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")
        _insert_classification(db_conn, "uri:canonical", bpm=120)
        _insert_classification(db_conn, "uri:other", bpm=125)

        _delete_duplicate_classifications(db_conn, ["uri:other"])

        assert _count_classifications(db_conn, "uri:canonical") == 1
        assert _count_classifications(db_conn, "uri:other") == 0

    def test_no_classifications_is_harmless(self, db_conn):
        """No crash when others have no classifications."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")

        _delete_duplicate_classifications(db_conn, ["uri:other"])

        assert _count_classifications(db_conn) == 0


# ---------------------------------------------------------------------------
# _delete_duplicate_songs
# ---------------------------------------------------------------------------

class TestDeleteDuplicateSongs:
    def test_removes_non_canonical_songs(self, db_conn):
        """Non-canonical song rows are deleted."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:other", name="Song", artist="Art")

        _delete_duplicate_songs(db_conn, ["uri:other"])

        assert _count_songs(db_conn) == 1
        assert queries.get_song(db_conn, "uri:canonical") is not None
        assert queries.get_song(db_conn, "uri:other") is None

    def test_canonical_untouched(self, db_conn):
        """Canonical URI song row is never deleted."""
        _insert_song(db_conn, "uri:canonical", name="Song", artist="Art")
        _insert_song(db_conn, "uri:dup1", name="Song", artist="Art")
        _insert_song(db_conn, "uri:dup2", name="Song", artist="Art")

        _delete_duplicate_songs(db_conn, ["uri:dup1", "uri:dup2"])

        assert _count_songs(db_conn) == 1
        assert queries.get_song(db_conn, "uri:canonical") is not None


# ---------------------------------------------------------------------------
# consolidate_duplicate_songs (integration)
# ---------------------------------------------------------------------------

class TestConsolidateDuplicateSongs:
    def test_no_duplicates_returns_zero(self, db_conn):
        """No duplicates → returns zeros, no changes."""
        _insert_song(db_conn, "uri:1", name="Song A", artist="Artist X")
        _insert_song(db_conn, "uri:2", name="Song B", artist="Artist Y")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 0, "songs_merged": 0}
        assert _count_songs(db_conn) == 2

    def test_single_duplicate_group(self, db_conn):
        """Two URIs for same song → merged into one, stats recomputed."""
        _insert_song(db_conn, "uri:keep", name="Song A", artist="Artist X",
                     sources=["liked"], first_played="2025-01-01T00:00:00Z",
                     last_played="2025-06-01T00:00:00Z")
        _insert_song(db_conn, "uri:dup", name="Song A", artist="Artist X",
                     sources=["extended_history"], first_played="2024-06-01T00:00:00Z",
                     last_played="2026-01-01T00:00:00Z")
        # uri:keep has more plays → becomes canonical
        for i in range(5):
            _insert_play(db_conn, "uri:keep", f"2025-0{i+1}-01T10:00:00Z")
        _insert_play(db_conn, "uri:dup", "2024-06-01T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 1, "songs_merged": 1}
        assert _count_songs(db_conn) == 1
        assert queries.get_song(db_conn, "uri:keep") is not None
        assert queries.get_song(db_conn, "uri:dup") is None
        # All history should be under canonical
        assert _count_history(db_conn, "uri:keep") == 6
        assert _count_history(db_conn, "uri:dup") == 0

    def test_three_uris_merged_into_one(self, db_conn):
        """Three URIs for the same song → two merged away."""
        for uri in ("uri:a", "uri:b", "uri:c"):
            _insert_song(db_conn, uri, name="Same Song", artist="Same Artist",
                         sources=["extended_history"])
        # uri:b has most plays
        for i in range(5):
            _insert_play(db_conn, "uri:b", f"2026-01-{i+1:02d}T10:00:00Z")
        _insert_play(db_conn, "uri:a", "2026-02-01T10:00:00Z")
        _insert_play(db_conn, "uri:c", "2026-02-02T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 1, "songs_merged": 2}
        assert _count_songs(db_conn) == 1
        assert queries.get_song(db_conn, "uri:b") is not None

    def test_classifications_cleaned_up(self, db_conn):
        """Classifications for non-canonical URIs are removed."""
        _insert_song(db_conn, "uri:keep", name="Song", artist="Art",
                     sources=["liked"])
        _insert_song(db_conn, "uri:dup", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_play(db_conn, "uri:keep", "2026-01-01T10:00:00Z")
        _insert_classification(db_conn, "uri:keep", bpm=120)
        _insert_classification(db_conn, "uri:dup", bpm=125)

        with patch("spotify.sync._compute_basic_song_stats"):
            consolidate_duplicate_songs(db_conn)

        assert _count_classifications(db_conn, "uri:keep") == 1
        assert _count_classifications(db_conn, "uri:dup") == 0

    def test_idempotent(self, db_conn):
        """Running consolidation twice produces the same result (no errors on second run)."""
        _insert_song(db_conn, "uri:keep", name="Song A", artist="Artist X",
                     sources=["liked"])
        _insert_song(db_conn, "uri:dup", name="Song A", artist="Artist X",
                     sources=["extended_history"])
        _insert_play(db_conn, "uri:keep", "2026-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:dup", "2026-01-02T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            result1 = consolidate_duplicate_songs(db_conn)
            result2 = consolidate_duplicate_songs(db_conn)

        assert result1 == {"groups": 1, "songs_merged": 1}
        assert result2 == {"groups": 0, "songs_merged": 0}
        assert _count_songs(db_conn) == 1

    def test_empty_database(self, db_conn):
        """No songs at all → no-op, returns zeros."""
        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 0, "songs_merged": 0}

    def test_timestamp_conflicts_handled_during_merge(self, db_conn):
        """When both URIs have a play at the same timestamp, no UNIQUE violation."""
        _insert_song(db_conn, "uri:keep", name="Song", artist="Art",
                     sources=["liked"])
        _insert_song(db_conn, "uri:dup", name="Song", artist="Art",
                     sources=["extended_history"])
        # Both have plays at same timestamp
        _insert_play(db_conn, "uri:keep", "2026-01-01T10:00:00Z", ms_played=200000)
        _insert_play(db_conn, "uri:dup", "2026-01-01T10:00:00Z", ms_played=180000)
        # Additional unique plays
        _insert_play(db_conn, "uri:keep", "2026-01-02T10:00:00Z")
        _insert_play(db_conn, "uri:dup", "2026-01-03T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result["groups"] == 1
        assert result["songs_merged"] == 1
        # 2 from canonical + 1 non-conflicting from dup = 3 (the conflicting one is dropped)
        assert _count_history(db_conn, "uri:keep") == 3
        assert _count_history(db_conn) == 3

    def test_sources_merged_after_consolidation(self, db_conn):
        """Canonical song has merged sources after consolidation."""
        _insert_song(db_conn, "uri:keep", name="Song", artist="Art",
                     sources=["liked"])
        _insert_song(db_conn, "uri:dup", name="Song", artist="Art",
                     sources=["extended_history", "top_track"])
        _insert_play(db_conn, "uri:keep", "2026-01-01T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            consolidate_duplicate_songs(db_conn)

        song = queries.get_song(db_conn, "uri:keep")
        sources = json.loads(song["sources"])
        assert set(sources) == {"liked", "extended_history", "top_track"}

    def test_multiple_groups_independent(self, db_conn):
        """Multiple duplicate groups are each consolidated independently."""
        # Group 1: Song A
        _insert_song(db_conn, "uri:a1", name="Song A", artist="Artist 1",
                     sources=["liked"])
        _insert_song(db_conn, "uri:a2", name="Song A", artist="Artist 1",
                     sources=["extended_history"])
        _insert_play(db_conn, "uri:a1", "2026-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:a2", "2026-01-02T10:00:00Z")

        # Group 2: Song B
        _insert_song(db_conn, "uri:b1", name="Song B", artist="Artist 2",
                     sources=["top_track"])
        _insert_song(db_conn, "uri:b2", name="Song B", artist="Artist 2",
                     sources=["extended_history"])
        for i in range(3):
            _insert_play(db_conn, "uri:b1", f"2026-01-{i+1:02d}T10:00:00Z")

        # Non-duplicate song
        _insert_song(db_conn, "uri:c", name="Unique Song", artist="Artist 3")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 2, "songs_merged": 2}
        assert _count_songs(db_conn) == 3  # 1 from each group + unique


# ---------------------------------------------------------------------------
# Edge case: same name, different artist (should NOT merge)
# ---------------------------------------------------------------------------

class TestSameNameDifferentArtist:
    def test_not_merged(self, db_conn):
        """Songs with same name but different artists remain separate."""
        _insert_song(db_conn, "uri:1", name="Stay", artist="The Kid LAROI")
        _insert_song(db_conn, "uri:2", name="Stay", artist="Rihanna")
        _insert_play(db_conn, "uri:1", "2026-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:2", "2026-01-02T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 0, "songs_merged": 0}
        assert _count_songs(db_conn) == 2
        assert _count_history(db_conn, "uri:1") == 1
        assert _count_history(db_conn, "uri:2") == 1


# ---------------------------------------------------------------------------
# Edge case: song with listening history but no song_classifications
# ---------------------------------------------------------------------------

class TestNoClassifications:
    def test_consolidation_works_without_any_classifications(self, db_conn):
        """Dedup works fine when song_classifications table is empty."""
        _insert_song(db_conn, "uri:keep", name="Song", artist="Art",
                     sources=["liked"])
        _insert_song(db_conn, "uri:dup", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_play(db_conn, "uri:keep", "2026-01-01T10:00:00Z")
        _insert_play(db_conn, "uri:dup", "2026-01-02T10:00:00Z")

        with patch("spotify.sync._compute_basic_song_stats"):
            result = consolidate_duplicate_songs(db_conn)

        assert result == {"groups": 1, "songs_merged": 1}
        assert _count_songs(db_conn) == 1


# ---------------------------------------------------------------------------
# Edge case: all URIs in a group have zero meaningful plays
# ---------------------------------------------------------------------------

class TestAllZeroPlays:
    def test_canonical_selected_by_source_then_lexicographic(self, db_conn):
        """When all URIs have zero plays, source preference and lex order decide."""
        _insert_song(db_conn, "uri:aaa", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_song(db_conn, "uri:zzz", name="Song", artist="Art",
                     sources=["liked"])

        with patch("spotify.sync._compute_basic_song_stats"):
            consolidate_duplicate_songs(db_conn)

        assert _count_songs(db_conn) == 1
        # uri:zzz should win: 0 plays for both, but "liked" is a preferred source,
        # so preferred_sources=True (1) for zzz vs False (0) for aaa
        assert queries.get_song(db_conn, "uri:zzz") is not None

    def test_all_extended_history_uses_lexicographic(self, db_conn):
        """When all URIs have zero plays and same sources, lexicographic max wins."""
        _insert_song(db_conn, "uri:aaa", name="Song", artist="Art",
                     sources=["extended_history"])
        _insert_song(db_conn, "uri:mmm", name="Song", artist="Art",
                     sources=["extended_history"])

        with patch("spotify.sync._compute_basic_song_stats"):
            consolidate_duplicate_songs(db_conn)

        assert _count_songs(db_conn) == 1
        assert queries.get_song(db_conn, "uri:mmm") is not None
