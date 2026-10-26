"""The phone tab bar never covers the end of a page, and a long hound name wraps to two lines (QA pass, 2026-10-25).

Measured for real in a headless Chrome at 390 x 844 (tests/pages_tabbar_390.mjs): the page's bottom padding must be the bar's
height plus 24 px, so the last content scrolls clear of the fixed bar; and the landing card's name may take two lines
(it was cut to "Gematria Ho..." at one). Skipped when node or a Chrome/Chromium binary is not installed.
"""
from __future__ import annotations

import http.server
import json
import subprocess
import threading
import unittest
from pathlib import Path

from tests.test_no_horizontal_overflow import CHROME, HAS_NODE, make_handler

HERE = Path(__file__).resolve().parent
PAGES = ("landing", "hound", "kennels", "learning", "desk")
BAR_GAP = 24            # lhnav.css: the bar's own height plus 24 px of air, plus the phone's home-indicator inset


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class PhoneChromeClearsContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler({}))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/web"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def measure(self, page):
        proc = subprocess.run(["node", str(HERE / "pages_tabbar_390.mjs"), CHROME, f"{self.base}/{page}.html"],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"measure failed for {page} ({proc.returncode}): {proc.stderr[-1500:]}")
        return json.loads(lines[-1])

    def test_each_page_leaves_the_bar_height_plus_24_under_its_last_content(self):
        for page in PAGES:
            with self.subTest(page=page):
                m = self.measure(page)
                bar = m["barH"]
                self.assertGreater(bar, 0, f"{page}: the phone tab bar is drawn")
                self.assertGreaterEqual(m["padBottom"], bar + BAR_GAP, f"{page}: {m}")
                self.assertGreaterEqual(m["scrollH"] - m["maxBottom"], bar + BAR_GAP - 1, f"{page}: {m}")

    def test_a_long_hound_name_takes_two_lines_before_it_is_cut(self):
        self.assertEqual(self.measure("landing")["nameLines"], 2)


if __name__ == "__main__":
    unittest.main()
