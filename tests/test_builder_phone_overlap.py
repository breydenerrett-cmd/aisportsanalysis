"""The builder on a phone (rebuild QA 2026-10-21, 390px with the site tab bar).

* The floating "would have bet today" pill (fixed, z-index 20, bottom 12px) sat under the tab bar (fixed, z-index 70,
  60px tall): only its top border showed. On the tab-bar widths it now rides above the bar.
* The 60px badge in the sidebar cards is absolutely placed top-right; the heading kept clear of it but the line under the
  heading wrapped beneath it ("Your hound passes today. Nothin|g"). The heading now holds the badge's height.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def css(name):
    return (ROOT / "web" / "css" / name).read_text(encoding="utf-8")


class TheBuilderOnAPhone(unittest.TestCase):
    def test_the_pill_rides_above_the_tab_bar(self):
        tabbar = re.search(r"@media \(max-width: (\d+)px\)\s*\{\s*\.lh-nav__bar", css("lhnav.css"))
        self.assertIsNotNone(tabbar)
        rule = re.search(r"@media \(max-width: (\d+)px\) \{ body:has\(> \.lh-tabbar\) \.bd-pill \{ bottom: calc\(var\(--lh-tabbar-h[^)]*\) \+ 12px",
                         css("builder.css"))
        self.assertIsNotNone(rule, "the pill has no tab-bar offset")
        self.assertEqual(rule.group(1), tabbar.group(1), "the offset must apply at exactly the widths the tab bar shows")

    def test_the_sidebar_heading_holds_the_badge_height(self):
        studio = css("studio.css")
        badge = int(re.search(r"\.bd-side__dog svg \{ width: (\d+)px; height: (\d+)px; \}", studio).group(2))
        top = re.search(r"\.bd-side__dog \{ position: absolute; top: var\(--lh-s4\)", studio)
        self.assertIsNotNone(top)
        h2 = re.search(r"\.hounds-page \.bd-side \.hd-panel h2 \{ padding-right: 72px; min-height: (\d+)px; \}", studio)
        self.assertIsNotNone(h2, "the heading does not reserve the badge's height")
        # the badge starts 16px from the card top, the heading 24px (the card's padding): it must reach the badge's bottom
        self.assertGreaterEqual(int(h2.group(1)) + 24, badge + 16)


if __name__ == "__main__":
    unittest.main()
