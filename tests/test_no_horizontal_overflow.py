"""No page of the hub scrolls sideways on a 390 px phone (design system v2, 2026-10-19).

A real headless Chrome loads each page from a local static server that also answers the public GETs the pages make with the
test fixtures (tests/hounds_web_fixtures.py), so the tables, boards, the landing race and the dog faces are all on the page when
the width is measured. `scrollWidth` may not exceed the viewport. A page that is meant to scroll a table sideways does it inside
its own wrapper (the leaderboard's `.hd-tablewrap`), never on the document.

Skipped when node or a Chrome/Chromium binary is not installed (set LINEHOUND_CHROME to point at one).
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import threading
import unittest
from pathlib import Path

from tests import hounds_web_fixtures as F

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


def find_chrome():
    env = os.environ.get("LINEHOUND_CHROME")
    if env and Path(env).exists():
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(p).exists():
            return p
    return None


CHROME = find_chrome()
HAS_NODE = shutil.which("node") is not None


def make_handler(api):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/web/"):
                return super().do_GET()
            hit = api.get(path)
            if hit is None and path.startswith("/hounds/series"):
                hit = (200, {"series": {}})
            if hit is None and path.startswith("/hounds/kennels"):
                hit = (200, {"kennels": [], "count": 0})
            if hit is None:
                hit = (404, {"detail": "not in the fixture"})
            body = json.dumps(hit[1], default=str).encode()
            self.send_response(hit[0])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class EveryPageFitsAPhone(unittest.TestCase):
    # owner ruling 2026-10-20 kennel-first: the leaderboard has no Kennels tab any more; its house-kennel filter and the graveyard are measured too
    PAGES = ["landing.html", "desk.html", "hounds.html", "hounds.html?scope=house", "kennels.html", "graveyard.html", "live.html", "kennel.html", "kennel.html?u=handler-21e8",
             "build-a-hound.html", "interview.html", "learning.html", "index.html", "admin.html", "postseason.html", "sample.html", "why-we-paused.html", "room.html"]

    @classmethod
    def setUpClass(cls):
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        api["/sports/now"] = (200, json.loads((HERE / "fixtures" / "sports_now.json").read_text(encoding="utf-8")))
        cls.hid = F.summaries()[0].id
        # the Gematria Hound's page with its Evidence fold OPEN: long labels, two picks, both sides (web/js/hounds-gematria.js)
        api.update({k: v for k, v in F.gematria_routes(picks=2).items()})
        cls.pages = cls.PAGES + [f"hound.html?id={cls.hid}", f"hound.html?id={cls.hid}&tab=tickets", f"hound.html?id={cls.hid}&tab=locker",
                                 f"hound.html?id={F.GEMATRIA_ID}", f"hound.html?id={F.GEMATRIA_ID}&open=evidence"]
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        proc = subprocess.run(["node", str(HERE / "overflow_390.mjs"), CHROME, base] + [f"/web/{p}" for p in cls.pages],
                              capture_output=True, text=True, encoding="utf-8", timeout=240)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"overflow script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_every_page_was_measured_at_390(self):
        self.assertEqual(len(self.results), len(self.pages))
        for r in self.results:
            self.assertEqual(r["iw"], 390, r)
            self.assertGreater(r["h"], 300, f"{r['path']} rendered almost nothing")

    def test_no_page_scrolls_sideways(self):
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1]
        self.assertEqual(bad, [], "pages wider than the phone: " + json.dumps(bad, indent=1))

    def test_every_page_with_the_tab_bar_ends_above_it_with_air_to_spare(self):
        """Round 2 (2026-10-19): the phone tab bar is 60px and fixed to the bottom; the page must leave the bar's height plus 24px below its
        last element, on every page that draws the bar (the member app, index.html, pads its own main column in css/app.css)."""
        barred = [r for r in self.results if r["bar"] > 0]
        self.assertGreaterEqual(len(barred), 10, "the shared tab bar is on the hub's pages")
        short = [(r["path"], r["bar"], r["pad"], r["clear"]) for r in barred if r["path"] != "/web/index.html" and (r["pad"] < r["bar"] + 24 or r["clear"] < r["bar"])]
        self.assertEqual(short, [], "pages whose last content sits under the tab bar: (path, bar, body padding, clearance) " + json.dumps(short))


def make_post_handler(api):
    """The same static server, plus the quiz's POSTs answered by the REAL composer (so the reveal is on the page when it is measured)."""
    base = make_handler(api)

    class Handler(base):
        def do_POST(self):
            from src.hounds.quiz import compose as C
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            path = self.path.split("?")[0]
            if path == "/hounds/quiz/compose":
                status, payload = 200, C.compose(body.get("answers") or {})
            elif path == "/hounds/builder/preview":
                picks = [{"event_id": f"e{i}", "selection": "Boston Red Sox to win", "away_team": "Boston Red Sox", "home_team": "New York Yankees",
                          "price": 120, "would_bet": i < 2} for i in range(3)]
                status, payload = 200, {"qualifying": 3, "would_bet": 2, "max_bets_per_day": 2, "picks": picks, "games_fit": 3, "board_size": 9,
                                        "games_on_board": 9, "read_only": True, "paper_only": True, "not_advice": "Paper bets only. Not advice."}
            else:
                status, payload = 404, {"detail": "not in the fixture"}
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheKennelFrontFitsEveryWidth(unittest.TestCase):
    """OWNER RULING 2026-10-21 (kennel front): the landing, the four quiz steps and the reveal, My Kennel and the nav (signed in and out) have no
    horizontal overflow at 375 and 390 (phones) and 1440 (desktop)."""
    WIDTHS = (375, 390, 1440)
    PAGES = ["/web/landing.html", "/web/hounds.html", "/web/quiz.html?restart=1#quiz", "/web/kennel.html#signed", "/web/hounds.html#signed",
             "/web/landing.html?stay=1#signed"]

    @classmethod
    def setUpClass(cls):
        from src.hounds.quiz import library as quiz_library
        from tests import test_kennel_page as K
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        api["/sports/now"] = (200, json.loads((HERE / "fixtures" / "sports_now.json").read_text(encoding="utf-8")))
        api["/hounds/quiz/library"] = (200, json.loads(json.dumps(quiz_library.public_library())))
        status, body = K.mine([K.dog("u-1", "Underdog Gus", wins=14, losses=9, bets=23, units=6.4), K.dog("u-2", "Totals Tina")])
        body["kennel_name"] = "Gus and Company Kennel"
        api["/hounds/kennels/mine"] = (status, body)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_post_handler(api))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        proc = subprocess.run(["node", str(HERE / "overflow_widths.mjs"), CHROME, base, ",".join(str(w) for w in cls.WIDTHS)] + cls.PAGES,
                              capture_output=True, text=True, encoding="utf-8", timeout=420)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"overflow script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_every_page_and_quiz_step_was_measured_at_every_width(self):
        quiz_steps = ["sports", "personality", "risk", "finish", "reveal"]
        self.assertEqual(len(self.results), len(self.WIDTHS) * (len(self.PAGES) - 1 + len(quiz_steps)))
        self.assertEqual({r["iw"] for r in self.results}, set(self.WIDTHS))
        self.assertEqual([r["step"] for r in self.results if r["step"] and r["width"] == 375], quiz_steps)     # the quiz has four steps and the reveal
        for r in self.results:
            self.assertGreater(r["h"], 300, f"{r['path']} {r['step']} rendered almost nothing")

    def test_nothing_scrolls_sideways_at_375_390_or_1440(self):
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1]
        self.assertEqual(bad, [], "wider than the screen: " + json.dumps(bad, indent=1))


if __name__ == "__main__":
    unittest.main()
