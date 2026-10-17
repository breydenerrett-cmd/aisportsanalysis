"""The sentence about which sports are live today exists in ONE place.

Owner brief 2026-10-17: the landing page said "The daily MLB brief" and the sample
page "MLB postseason briefs are posted before first pitch" while the MLB season
ends in about two weeks. Both now say "a brief for every game we cover, posted
before it starts", and the one sentence about what is live today is the constant
`SPORTS_LIVE_TODAY` in web/js/dom.js. The pages read it; the landing markup carries
the same sentence as a no-script fallback, and this file fails if the two differ.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "js"


def _constant() -> str:
    source = (JS / "dom.js").read_text(encoding="utf-8")
    return re.search(r'export const SPORTS_LIVE_TODAY = "([^"]+)";', source).group(1)


class TheLiveSportsSentenceHasOneSource(unittest.TestCase):
    def test_the_constant_names_what_is_live_today(self):
        text = _constant()
        self.assertIn("MLB postseason", text)
        self.assertIn("NFL", text)

    def test_the_landing_markup_fallback_equals_the_constant(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        nodes = re.findall(r'data-hook="sports-live-today">([^<]*)<', html)
        self.assertEqual(nodes, [_constant()])

    def test_the_landing_script_fills_it_from_the_constant_and_types_no_second_copy(self):
        landing = (JS / "landing.js").read_text(encoding="utf-8")
        self.assertIn("SPORTS_LIVE_TODAY", landing)
        self.assertIn("fillLiveSports();", landing)
        sample = (JS / "sample.js").read_text(encoding="utf-8")
        self.assertIn("SPORTS_LIVE_TODAY", sample)
        for name in ("landing.js", "sample.js"):
            self.assertNotIn("MLB postseason", (JS / name).read_text(encoding="utf-8"), name)

    def test_no_page_still_says_the_daily_brief_or_names_the_postseason_in_a_promise(self):
        for path in (WEB / "landing.html", WEB / "sample.html", JS / "sample.js", JS / "landing.js"):
            text = path.read_text(encoding="utf-8").replace(_constant(), "")
            self.assertNotRegex(text, r"(?i)daily MLB brief", path.name)
            self.assertNotIn("MLB postseason briefs", text, path.name)


if __name__ == "__main__":
    unittest.main()
