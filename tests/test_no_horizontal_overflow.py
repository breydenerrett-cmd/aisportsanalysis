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
             "build-a-hound.html", "interview.html", "learning.html", "index.html", "admin.html", "postseason.html", "sample.html", "why-we-paused.html"]

    @classmethod
    def setUpClass(cls):
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        api["/sports/now"] = (200, json.loads((HERE / "fixtures" / "sports_now.json").read_text(encoding="utf-8")))
        cls.hid = F.summaries()[0].id
        cls.pages = cls.PAGES + [f"hound.html?id={cls.hid}", f"hound.html?id={cls.hid}&tab=tickets", f"hound.html?id={cls.hid}&tab=locker"]
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


if __name__ == "__main__":
    unittest.main()
