"""Ground truth assertions for classification quality.

Catches regressions when classification or merge logic changes.
Each assertion encodes a known fact about a song that should hold
regardless of LLM provider, prompt changes, or merge parameters.
"""

import sqlite3

import pytest

from config import get_profile_db_path
from db.schema import get_connection


@pytest.fixture(scope="module")
def conn():
    """Connect to the real (non-test) database."""
    db_path = get_profile_db_path(None)
    if not db_path.exists():
        pytest.skip("No production DB found")
    c = get_connection(db_path)
    # Verify we have classifications
    count = c.execute(
        "SELECT COUNT(*) as cnt FROM song_classifications WHERE valence IS NOT NULL"
    ).fetchone()["cnt"]
    if count == 0:
        c.close()
        pytest.skip("No classifications in DB")
    yield c
    c.close()


def _get_song(conn: sqlite3.Connection, name_pattern: str) -> dict | None:
    row = conn.execute(
        """SELECT s.name, s.artist, sc.*
           FROM song_classifications sc
           JOIN songs s ON sc.spotify_uri = s.spotify_uri
           WHERE s.name LIKE ?
           LIMIT 1""",
        (f"%{name_pattern}%",),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Acousticness: the original problem — electronic songs must not score high
# ---------------------------------------------------------------------------

class TestAcousticnessNotBroken:
    def test_blinding_lights_not_acoustic(self, conn):
        """Synthwave track — acousticness should be low."""
        song = _get_song(conn, "Blinding Lights")
        assert song is not None
        assert song["acousticness"] < 0.4

    def test_single_ladies_not_acoustic(self, conn):
        """Heavily produced pop — acousticness should be low."""
        song = _get_song(conn, "Single Ladies")
        assert song is not None
        assert song["acousticness"] < 0.4

    def test_brown_rang_not_acoustic(self, conn):
        """Electronic Punjabi pop — acousticness should be low."""
        song = _get_song(conn, "Brown Rang")
        assert song is not None
        assert song["acousticness"] < 0.3

    def test_photograph_is_acoustic(self, conn):
        """Solo acoustic guitar + vocals — acousticness should be high."""
        song = _get_song(conn, "Photograph")
        assert song is not None
        assert song["acousticness"] > 0.6


# ---------------------------------------------------------------------------
# Energy: high-energy songs should score high, calm songs low
# ---------------------------------------------------------------------------

class TestEnergyDirectionality:
    def test_sheila_ki_jawani_high_energy(self, conn):
        """Club banger — energy should be high."""
        song = _get_song(conn, "Sheila Ki Jawani")
        assert song is not None
        assert song["energy"] > 0.5

    def test_kun_faya_kun_low_energy(self, conn):
        """Soft Sufi prayer — energy should be low-moderate."""
        song = _get_song(conn, "Kun Faya Kun")
        assert song is not None
        assert song["energy"] < 0.5

    def test_bernies_chalisa_low_energy(self, conn):
        """Slow devotional chant — energy should be very low."""
        song = _get_song(conn, "Bernie")
        assert song is not None
        assert song["energy"] < 0.3


# ---------------------------------------------------------------------------
# Neuro scores: songs should land in the right bucket
# ---------------------------------------------------------------------------

class TestNeuroScoreDirection:
    def test_devotional_is_parasympathetic(self, conn):
        """Hanuman Chalisa Lo-fi — should be strongly parasympathetic."""
        song = _get_song(conn, "Hanuman Chalisa")
        assert song is not None
        assert song["parasympathetic"] > song["sympathetic"]
        assert song["parasympathetic"] > 0.6

    def test_banger_is_sympathetic(self, conn):
        """Brown Rang — should be strongly sympathetic."""
        song = _get_song(conn, "Brown Rang")
        assert song is not None
        assert song["sympathetic"] > song["parasympathetic"]
        assert song["sympathetic"] > 0.7

    def test_acoustic_ballad_not_sympathetic(self, conn):
        """Photograph — should not be sympathetic-dominant."""
        song = _get_song(conn, "Photograph")
        assert song is not None
        assert song["parasympathetic"] > song["sympathetic"]
