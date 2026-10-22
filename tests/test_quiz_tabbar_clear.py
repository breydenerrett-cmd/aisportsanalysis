"""The phone tab bar never hides the quiz's controls (checker finding, 2026-10-21).

On the quiz's "Pick its style." (step 2 of the four-step quiz, owner ruling 2026-10-21; there is no Skip button now) step the personality grid is four cards a page, so the "Show me others" pill and the
Back / Next row sit low on the page. The tab bar is fixed to the bottom of a 390 x 844 phone, so a screenshot of the whole page
makes the pill look hidden under it. This test measures it for real in a headless Chrome: the page must leave the bar's height plus 24 px
under its last content, and some scroll position must show the pill and all three buttons with the page (not the bar) under their centres
(`document.elementFromPoint`). The page is reached the way a phone reaches it: pick a sport, Next, "Show me others", pick Gematria.

Skipped when node or a Chrome/Chromium binary is not installed (set LINEHOUND_CHROME to point at one).
"""

from __future__ import annotations

import http.server
import json
import subprocess
import threading
import unittest
from pathlib import Path

from src.hounds.quiz import library as quiz_library
from tests.test_no_horizontal_overflow import CHROME, HAS_NODE, make_handler

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class QuizTabBarClearance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler({"/hounds/quiz/library": (200, json.loads(json.dumps(quiz_library.public_library())))}))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{cls.server.server_address[1]}/web/quiz.html?restart=1"
        proc = subprocess.run(["node", str(HERE / "quiz_tabbar_390.mjs"), CHROME, url], capture_output=True, text=True, encoding="utf-8", timeout=120)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"quiz script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.out = json.loads(lines[-1])
        if "error" in cls.out:
            raise AssertionError(f"the quiz script threw: {cls.out['error']}")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_the_page_is_a_phone_with_the_tab_bar_and_no_sideways_scroll(self):
        self.assertEqual(self.out["iw"], 390, self.out)
        # checker 2026-10-21: the phone tab bar is hidden for the whole quiz (the sticky Back / Next row cannot leave its section, so near the
        # end of the page it sat in the bar's strip); the quiz has its own Back / Next
        self.assertEqual(self.out["bar"], 0, "the shared phone tab bar is hidden on the quiz page")
        self.assertLessEqual(self.out["sw"], 391, self.out)

    def test_the_page_leaves_air_under_its_last_content(self):
        self.assertGreaterEqual(self.out["pad"], 24, self.out)

    def test_some_scroll_position_shows_the_pill_and_back_next_uncovered(self):
        self.assertIsNotNone(self.out["clearAt"], "no scroll position shows the pill and both buttons clear of the tab bar: " + json.dumps(self.out))

    def test_scrolled_to_the_end_nothing_is_under_the_bar(self):
        self.assertEqual(self.out["atEnd"], {"more": True, "back": True, "next": True}, self.out)


if __name__ == "__main__":
    unittest.main()
