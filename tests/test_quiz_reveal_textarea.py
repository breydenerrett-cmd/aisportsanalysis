"""The reveal's "Add anything in your own words" heading never covers the textarea (QA walk 2026-10-26).

The textarea sits inside a closed <details>, so a closed-page measurement cannot see it. This test drives the quiz to the reveal at 390 x 844
in a headless Chrome, OPENS the details, and checks that the summary's bottom is at or above the textarea's top and that nothing else is on
top of the textarea's top edge (`document.elementFromPoint` on several points of the edge).

Skipped when node or a Chrome/Chromium binary is not installed (set LINEHOUND_CHROME to point at one).
"""

from __future__ import annotations

import http.server
import json
import subprocess
import threading
import unittest
from pathlib import Path

from tests import hounds_web_fixtures as F
from tests.test_no_horizontal_overflow import CHROME, HAS_NODE, make_post_handler

HERE = Path(__file__).resolve().parent
CSS = (HERE.parent / "web" / "css" / "quiz.css").read_text(encoding="utf-8")


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class RevealTextareaIsClearOfItsHeading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.hounds.quiz import library as quiz_library
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        api["/hounds/quiz/library"] = (200, json.loads(json.dumps(quiz_library.public_library())))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_post_handler(api))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        proc = subprocess.run(["node", str(HERE / "quiz_reveal_390.mjs"), CHROME, base], capture_output=True, text=True, encoding="utf-8", timeout=120)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"reveal script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.out = json.loads(lines[-1])
        if "error" in cls.out:
            raise AssertionError(f"the reveal script threw: {cls.out['error']}")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_measured_on_a_390_phone_with_the_details_open(self):
        self.assertEqual(self.out["iw"], 390, self.out)
        self.assertFalse(self.out["closed"]["open"], "the details start closed")
        self.assertTrue(self.out["open"], "the details were opened before measuring")
        self.assertGreater(self.out["ta"]["h"], 40, self.out)
        self.assertLessEqual(self.out["sw"], 391, self.out)

    def test_the_heading_bottom_is_at_or_above_the_textarea_top(self):
        self.assertLessEqual(self.out["sum"]["bottom"], self.out["ta"]["top"], self.out)
        for head in self.out["heads"]:
            self.assertLessEqual(head["r"]["bottom"], self.out["ta"]["top"], head)

    def test_nothing_sits_on_the_textarea_top_edge(self):
        self.assertEqual(self.out["topEdgeHit"], [], self.out)

    def test_the_textarea_is_a_block_with_no_overlapping_position_in_the_css(self):
        self.assertIn(".qz-own > .qz-textarea { display: block;", CSS)
        self.assertIn("::-webkit-details-marker", CSS)


if __name__ == "__main__":
    unittest.main()
