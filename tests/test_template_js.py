"""Smoke test of web/template.html's script: render days in node and check what the page shows.

Runs the page script against tests/js/run_page.js's minimal DOM stand-in (no
browser, no npm packages). Skipped when node isn't installed.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from web import site

NODE = shutil.which("node")
RUNNER = Path(__file__).parent / "js" / "run_page.js"
XSS = "<script>alert(1)</script>"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed, so the page script can't be run")


def _day(date, score, recovery, playlist, shortcut, title="WHOOP and Attuned roughly agree today"):
    return {
        "date": date,
        "whoop": {"recovery": recovery, "band": site.band(recovery)},
        "attuned": {"score": score, "band": site.band(score), "state": "rest", "drivers": [],
                    "compare": {"title": title, "line": "A line.", "note": "A note."}},
        "metrics": {},
        "playlist": playlist,
        "shortcut": shortcut,
    }


PLAYLIST = {
    "name": "Oct 22 — Settle In " + XSS, "state": "rest", "total_time": "3 min",
    "open": {"label": "Play on Spotify", "url": "https://open.spotify.com/track/a"},
    "summary": {"lead": "Lead.", "kinds": "Kinds.", "why": "Why.", "cites": [["Bernardi 2006", "https://doi.org/x"]]},
    "tracks": [{"title": '<img src=x onerror="alert(2)">', "artist": "A", "spotify_url": "https://open.spotify.com/track/a",
                "why": "Soft.", "art": None, "duration": "3:00"}],
}

DAYS = [
    _day("2026-10-20", 50, 55, PLAYLIST, shortcut=False),               # no chip
    _day("2026-10-21", None, None, None, shortcut=True, title="No Attuned score today"),
    _day("2026-10-22", 40, 70, PLAYLIST, shortcut=True, title=XSS),
]


@pytest.fixture(scope="module")
def steps(tmp_path_factory):
    html = site.render(site.TEMPLATE_PATH.read_text(), DAYS)
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    script = re.search(r"<script>\n(.*?)</script>", html, re.S).group(1)
    tmp = tmp_path_factory.mktemp("page")
    (tmp / "page.js").write_text(script)
    (tmp / "data.json").write_text(data)
    run = subprocess.run([NODE, str(RUNNER), str(tmp / "page.js"), str(tmp / "data.json")],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr  # the script never throws
    return json.loads(run.stdout)


def _attuned_ring(main):
    return main.split('<div class="ring">')[1]


class TestPageScript:
    def test_opens_on_the_latest_day(self, steps):
        assert steps[0]["date"] == "Oct 22, 2026"
        assert steps[0]["nextDisabled"] is True and steps[0]["prevDisabled"] is False

    def test_page_text_is_escaped(self, steps):
        main = steps[0]["main"]
        assert XSS not in main and "<img src=x" not in main
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in main
        assert "&lt;img src=x onerror=&quot;alert(2)&quot;&gt;" in main

    def test_day_without_a_score_shows_an_empty_grey_ring(self, steps):
        main = steps[1]["main"]
        assert steps[1]["date"] == "Oct 21, 2026"
        ring = _attuned_ring(main)
        assert 'aria-label="Attuned Recovery: no score"' in ring
        assert ">–</text>" in ring
        assert 'class="arc"' not in ring and "var(--red)" not in ring and ">0<" not in ring

    def test_day_without_a_playlist_says_so(self, steps):
        assert "No playlist for this day." in steps[1]["main"]

    def test_scored_ring_shows_the_score_in_its_band(self, steps):
        ring = _attuned_ring(steps[0]["main"])
        assert ">40<tspan" in ring and "var(--yellow)" in ring

    def test_only_shortcut_days_get_chips(self, steps):
        assert [(c["i"], c["label"]) for c in steps[0]["chips"]] == [(1, "Oct 21"), (2, "Latest")]

    def test_current_chip_follows_the_day_shown(self, steps):
        current = [[c["i"] for c in step["chips"] if c["current"] == "true"] for step in steps]
        # latest, then Prev to Oct 21, then a click on the "Latest" chip
        assert current == [[2], [1], [2]]
