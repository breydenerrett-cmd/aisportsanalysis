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
