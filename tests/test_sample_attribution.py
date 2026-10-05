"""The public sample page stores an outreach link's first touch, with the one implementation.

Outreach links point at web/sample.html with ?utm_source=<lead id>&utm_medium=<channel>&utm_campaign=...
(the pattern tests/test_public_page_attribution.py pins for the record page and postseason.html, and
tests/test_funnel_attribution.py for the landing page). Without this a lead who read the sample and
signed up later would read as "(direct)" and the batch that found them would look like it had produced
nothing.

The page calls `trackPublicPageView("sample")` from web/js/pageview.js, which stores the first
touch with `captureFirstTouch` (web/js/attribution.js, the same function landing.js calls) and sends
the one public_page_view beacon (tests/test_sample_view_tracking.py pins the beacon). It must not
carry a second copy of the logic. The real sample.js, attribution.js, api.js and
analyst.js are executed under node against a small fake DOM (the harness of tests/test_sample_brief.py).
Skipped when node is missing. `web/js/attribution.js` is unchanged by this work.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_sample_brief import HARNESS, brief

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
SAMPLE_JS = (JS / "sample.js").read_text(encoding="utf-8")
LANDING_JS = (JS / "landing.js").read_text(encoding="utf-8")

OUTREACH = "?utm_source=lead-017&utm_medium=discord_dm&utm_campaign=batch-01"
FIRST_TOUCH_KEY = "linehound.first_touch"


class TheSamplePageUsesTheOneImplementation(unittest.TestCase):
    def test_it_stores_the_touch_through_the_one_shared_call_the_other_public_pages_make(self):
        pageview = (JS / "pageview.js").read_text(encoding="utf-8")
        self.assertIn('import { trackPublicPageView } from "./pageview.js";', SAMPLE_JS)
        self.assertRegex(SAMPLE_JS, r"trackPublicPageView\(SAMPLE_PAGE\);")
        # ... and that call is the landing page's own capture, not a copy of it
        self.assertIn('import { captureFirstTouch } from "./attribution.js";', pageview)
        self.assertIn('import { captureFirstTouch } from "./attribution.js";', LANDING_JS)
        self.assertRegex(pageview, r"captureFirstTouch\(\);")

    def test_it_carries_no_second_implementation(self):
        code = "\n".join(line for line in SAMPLE_JS.splitlines() if not line.strip().startswith(("*", "//", "/*")))
        for needle in ("utm_", "localStorage", "referrer", "URLSearchParams", "first_touch"):
            self.assertNotIn(needle, code)

    def test_the_capture_runs_on_load_before_anything_that_can_fail(self):
        body = SAMPLE_JS[SAMPLE_JS.index("async function main()"):]
        self.assertLess(body.index("trackPublicPageView("), body.index("renderDisclaimerFooter"))
        self.assertLess(body.index("trackPublicPageView("), body.index("fetchSample()"))
        self.assertIn('document.addEventListener("DOMContentLoaded", main)', SAMPLE_JS)

    def test_signup_reads_the_stored_touch_so_a_plain_link_keeps_the_source(self):
        signup = (JS / "signup.js").read_text(encoding="utf-8")
        self.assertIn("attribution: attributionPayload()", signup)
        self.assertRegex(SAMPLE_JS, r'href: "index\.html#/signup"')
        self.assertRegex(SAMPLE_JS, r'href: "landing\.html"')


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheSamplePageStoresTheFirstTouch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def load(self, **scenario):
        scenario.setdefault("brief", brief())
        env = dict(os.environ, SCENARIO=json.dumps(dict(kind="load", **scenario)))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        out = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])
        self.assertFalse(out["crashed"], out["crashed"])
        return out

    def test_an_outreach_link_stores_its_source_medium_and_campaign(self):
        out = self.load(search=OUTREACH)
        self.assertEqual(json.loads(out["stored"][FIRST_TOUCH_KEY]),
                         {"utm_source": "lead-017", "utm_medium": "discord_dm", "utm_campaign": "batch-01"})
        self.assertEqual(out["callCount"], 2)          # and the page still drew the brief

    def test_first_touch_wins_a_later_tagged_visit_does_not_overwrite_it(self):
        earlier = {"utm_source": "reddit", "utm_medium": "post", "utm_campaign": "launch"}
        out = self.load(search=OUTREACH, stored={FIRST_TOUCH_KEY: json.dumps(earlier)})
        self.assertEqual(json.loads(out["stored"][FIRST_TOUCH_KEY]), earlier)

    def test_a_direct_visit_stores_nothing_so_a_later_tagged_one_can_still_count(self):
        out = self.load(search="")
        self.assertNotIn(FIRST_TOUCH_KEY, out["stored"])

    def test_only_the_referring_host_is_kept_never_the_url(self):
        out = self.load(search="", referrer="https://old.reddit.com/r/mlb/comments/abc?x=1")
        self.assertEqual(json.loads(out["stored"][FIRST_TOUCH_KEY]), {"referrer_host": "old.reddit.com"})

    def test_blocked_storage_does_not_break_the_page(self):
        out = self.load(search=OUTREACH, brokenStorage=True)
        self.assertEqual(out["stored"], {})
        self.assertEqual(out["callCount"], 2)
        self.assertEqual(len(out["links"]), 3)

    def test_the_visit_sends_one_funnel_beacon_and_nothing_else(self):
        # (what that beacon says is pinned in tests/test_sample_view_tracking.py)
        out = self.load(search=OUTREACH)
        self.assertEqual(out["posts"], ["/funnel/event"])


if __name__ == "__main__":
    unittest.main()
