"""The Gematria Hound's "Evidence" fold on web/hound.html: shown for the numerology hound only, behind a tap, both sides' matches for
each pick, every string put on the page as text (never markup), and no sideways scroll at 390 px (tests/test_no_horizontal_overflow.py
carries the phone-width check for the page itself)."""

from __future__ import annotations

import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_hounds_web_pages import q


@unittest.skipUnless(HAS_NODE, "node not installed")
class EvidenceFoldTests(unittest.TestCase):
    def page(self, routes_, hid=F.GEMATRIA_ID, queries=()):
        return run_page("hound", routes=routes_, search=f"?id={hid}", queries=list(queries))

    def test_the_fold_is_shown_for_the_numerology_hound_with_both_sides_of_each_pick(self):
        out = self.page(F.gematria_routes(picks=2), queries=[
            q("hidden", "[data-hook='hound-evidence']", "hidden"), q("copy", "[data-hook='evidence-copy']"),
            q("picks", "[data-hook='evidence-pick']", "count"), q("sides", ".hd-ev__side", "count"),
            q("summary", "[data-hook='evidence-summary']", "texts"), q("heads", ".hd-ev__sidehead", "texts"),
            q("items", ".hd-ev__item", "count"), q("results", "[data-hook='evidence-pick']", "attrs", attr="data-result"),
            q("cat", ".hd-modelhead .hd-typechip")])
        f = out["final"]
        self.assertFalse(f["hidden"])
        self.assertEqual(f["copy"], "Experimental numerology hound. Paper picks, graded in public like every hound.")
        self.assertEqual(f["picks"], 2)
        self.assertEqual(f["sides"], 4)                       # both sides of both picks
        self.assertIn("Margin 4.5 (it needs 3)", f["summary"][0])
        self.assertIn("1311 comparisons tried in all", f["summary"][0])
        self.assertIn("Rules v1", f["summary"][0])
        self.assertTrue(any("(picked)" in h and "Boston Celtics" in h for h in f["heads"]), f["heads"])
        self.assertTrue(any("New York Knicks" in h and "of 611 comparisons" in h for h in f["heads"]), f["heads"])
        self.assertEqual(f["results"], ["open", "win"])
        self.assertGreaterEqual(f["items"], 10)
        self.assertEqual(f["cat"], "Numerology")

    def test_the_evidence_is_closed_until_tapped(self):
        out = self.page(F.gematria_routes(), queries=[q("open", "details[data-hook='hound-evidence']", "attrs", attr="open")])
        self.assertEqual(out["final"]["open"], [None])

    def test_every_string_is_text_not_markup(self):
        out = self.page(F.gematria_routes(hostile=True), queries=[
            q("imgs", "[data-hook='hound-evidence'] img", "count"), q("what", ".hd-ev__what", "texts"),
            q("game", ".hd-ev__game", "texts")])
        f = out["final"]
        self.assertEqual(f["imgs"], 0)
        self.assertTrue(any("<img" in t for t in f["what"] + f["game"]), "the hostile name should appear as literal text")

    def test_before_the_first_pick_the_fold_says_so(self):
        out = self.page(F.gematria_routes(started=False), queries=[
            q("none", "[data-hook='evidence-none']"), q("copy", "[data-hook='evidence-copy']")])
        self.assertIn("No pick yet", out["final"]["none"])
        self.assertIn("Experimental numerology hound", out["final"]["copy"])

    def test_other_hounds_never_see_the_fold(self):
        hid = F.summaries()[0].id
        out = run_page("hound", routes=F.routes(), search=f"?id={hid}",
                       queries=[q("hidden", "[data-hook='hound-evidence']", "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_the_html_has_the_fold_hidden_and_is_inside_the_overview(self):
        html = (WEB / "hound.html").read_text(encoding="utf-8")
        i = html.index('data-hook="hound-evidence"')
        self.assertIn("hidden", html[i:i + 160])
        self.assertLess(html.index('data-tabpanel="overview"'), i)
        self.assertLess(i, html.index('data-tabpanel="tickets"'))


if __name__ == "__main__":
    unittest.main()
