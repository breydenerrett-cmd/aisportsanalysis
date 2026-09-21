"""The shared footer must be styled, and reachable, on every page that mounts it.

WHY THIS FILE EXISTS
---------------------
web/js/meta.js's renderDisclaimerFooter is mounted by BOTH the app shell and
the marketing page. It carries the beta disclaimer, the 21+ notice, the
support link and the responsible-gambling helpline -- the four pieces of copy
on this product with the least room for being hard to read.

Its styles (`.sitefoot__*`) live in web/css/app.css, which web/landing.html
did not load. So on the one page every stranger sees first, the entire footer
rendered as unstyled browser defaults: `.sitefoot__row` computed
`display: block`, the flex spacer collapsed to zero width, and the legal
notice, the helpline and the support link ran together as a single unbroken
string.

Nothing errored. No test failed. The component was correct; it was simply
never given its stylesheet on one of the two pages that mount it.

Found by reading the computed style of a rendered element, not the source --
which is the only way this kind of defect is ever found.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"

# Every page that mounts the shared footer, by its disclaimer host hook.
FOOTER_HOST_HOOK = 'data-hook="disclaimer-host"'
# The stylesheet the footer's own rules live in.
FOOTER_STYLESHEET = "css/app.css"


def _pages_mounting_the_footer():
    out = []
    for path in sorted(WEB.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if FOOTER_HOST_HOOK in text:
            out.append(path)
    return out


class TheFooterIsStyledEverywhereItMounts(unittest.TestCase):

    def test_at_least_two_pages_mount_it(self):
        """If this drops to one, the shared-component premise is gone and
        this whole file should be re-thought rather than quietly passing."""
        pages = _pages_mounting_the_footer()
        self.assertGreaterEqual(
            len(pages), 2,
            f"expected the footer on both the app shell and the landing "
            f"page; found {[p.name for p in pages]}")

    def test_every_page_that_mounts_it_loads_its_stylesheet(self):
        offenders = []
        for path in _pages_mounting_the_footer():
            text = path.read_text(encoding="utf-8")
            links = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"',
                               text)
            if FOOTER_STYLESHEET not in links:
                offenders.append(path.name)
        self.assertEqual(
            [], offenders,
            f"{offenders} mount the shared footer without loading "
            f"{FOOTER_STYLESHEET}, where its .sitefoot__* rules live -- it "
            f"will render as unstyled browser defaults")

    def test_the_footer_rules_actually_live_there(self):
        """Guards the assumption above: if .sitefoot__* moves to another
        stylesheet, the test on this page becomes a check of nothing."""
        css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".sitefoot__row", css,
                      "the footer's rules are no longer in app.css; update "
                      "FOOTER_STYLESHEET to wherever they moved")

    def test_landing_css_loads_after_the_app_shell_stylesheet(self):
        """The landing page's own rules must still win any conflict."""
        text = (WEB / "landing.html").read_text(encoding="utf-8")
        app_at = text.find(FOOTER_STYLESHEET)
        landing_at = text.find("css/landing.css")
        self.assertGreaterEqual(app_at, 0)
        self.assertGreaterEqual(landing_at, 0)
        self.assertLess(app_at, landing_at,
                        "app.css is loaded after landing.css and can now "
                        "override the marketing page's own styling")


class FooterMatchesTheRedesign(unittest.TestCase):
    """CHR-7 (DESIGN_SYSTEM.md section 3, "Footer"): the summary sentence,
    the link set/order, and the linkPrefix parameter that lets landing.js
    reuse this same footer with working hrefs. Static text checks, same
    style as the rest of this file."""

    def setUp(self):
        self.code = (WEB / "js" / "meta.js").read_text(encoding="utf-8")

    def test_summary_matches_the_design_system_wording(self):
        # DESIGN_SYSTEM.md section 5's replacement table, shell-07: the old
        # "Three to five bets a day, frozen before first pitch and graded
        # after" overclaimed a fixed price a later publish can still
        # replace (section 5's record wording) -- this exact sentence
        # replaces it. Extended 2026-09-20 (NFL and tennis live): every pick
        # is part of a test, analysis not advice, bet at your own risk.
        self.assertIn(
            "Beta. Every pick here is part of an ongoing test — published "
            "before each game and graded as it stood at its lock, win or "
            "lose. This is analysis, not advice. Nothing here is a "
            "guarantee; bet at your own risk.",
            self.code,
        )

    def test_renderDisclaimerFooter_takes_an_optional_linkPrefix(self):
        # Matches sport.js's renderSportLevel(host, activeSport,
        # {placement, linkPrefix}) contract -- landing.js calls this with
        # linkPrefix: "index.html" so #/betcheck etc. resolve from
        # landing.html rather than dead-ending as a bare fragment there.
        self.assertIn(
            "export async function renderDisclaimerFooter(container, "
            '{ linkPrefix = "" } = {})',
            self.code,
        )

    def test_footer_betcheck_link_exists(self):
        # D7: CHECK leaves the primary navigation and the fixed "Check a
        # bet" band goes with it, but Bet Check's route stays reachable
        # from the footer.
        self.assertIn('"data-hook": "footer-betcheck"', self.code)
        self.assertIn('route("#/betcheck")', self.code)

    def test_every_existing_footer_hook_is_kept(self):
        for hook in ("footer-support", "footer-record", "footer-performance", "footer-props"):
            self.assertIn(f'"data-hook": "{hook}"', self.code,
                          f"{hook} must stay -- another file may link to it by name")

    def test_footer_links_appear_in_the_design_systems_stated_order(self):
        # Section 3: "links to Results, Research, Player props, Bet Check
        # and Support."
        hooks_in_order = ["footer-record", "footer-performance", "footer-props",
                          "footer-betcheck", "footer-support"]
        positions = [self.code.index(f'"data-hook": "{h}"') for h in hooks_in_order]
        self.assertEqual(positions, sorted(positions),
                         "footer links are not in Results/Research/Player props/"
                         "Bet Check/Support order")

    def test_viewer_zone_is_stated_exactly_once(self):
        # Section 3, row 4: "Times shown in PDT, your time zone." -- and
        # explicitly NOT duplicated with the legal row's old "ALL TIMES
        # {zone} ·" prefix, which is removed.
        self.assertIn("your time zone", self.code)
        self.assertIn("localZoneAbbr()", self.code)
        self.assertNotIn("ALL TIMES", self.code)


class ResponsibleGamblingIsActionable(unittest.TestCase):
    """1-800-GAMBLER existed only in the design mockups and never shipped
    into web/. The product told people to play responsibly and gave them
    nowhere to go -- the one piece of copy here whose entire value is being
    actionable at the moment somebody needs it."""

    def setUp(self):
        self.code = (WEB / "js" / "meta.js").read_text(encoding="utf-8")

    def test_the_helpline_is_rendered(self):
        self.assertIn("1-800-GAMBLER", self.code)

    def test_it_is_a_dialable_link_not_just_text(self):
        self.assertTrue(
            re.search(r'href:\s*"tel:1-800-426-2537"', self.code),
            "the helpline is plain text; on the device most people read "
            "this on, a tel: link is one tap")

    def test_the_play_responsibly_notice_is_still_there(self):
        self.assertIn("PLAY RESPONSIBLY", self.code)
        self.assertIn("21+", self.code)


if __name__ == "__main__":
    unittest.main()
