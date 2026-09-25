"""KEYBOARD ACCESS on the per-sport record tiles (task B1 follow-up).

VERIFIED LIVE during this task: with the app served at
http://localhost:8000/web/landing.html, every "See every ___ pick,
graded ->" control under [data-hook="sport-record-tiles"] came back
`tabIndex: 0` / a real non-empty `href` (checked via
`document.querySelectorAll('[data-hook="sport-record-tiles"] a')` in the
live page) -- a real, native, keyboard-reachable link, not a div/span
with a click handler bolted on. This file pins that structurally so a
future redesign of the tiles can't quietly swap the link for a
JS-only-clickable element and lose keyboard access without any test
noticing.

Native `<a href="...">` is deliberately the whole keyboard-access
strategy here: it is Tab-focusable and Enter-activatable by the browser
itself, no `tabindex`/`role`/keydown handler required or wanted. A
`tabindex="-1"`, a `role="button"` on a non-`<a>`/`<button>`, or an
`onclick` with no underlying href would all break that for a keyboard
user silently -- this test fails on any of them.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HTML = (REPO / "web" / "landing.html").read_text(encoding="utf-8")

TILE_PREFIXES = ("sport-tile-mlb", "sport-tile-nfl", "sport-tile-ufc")


class SportTileLinksAreKeyboardReachable(unittest.TestCase):
    def _tile_html(self, prefix: str) -> str:
        marker = f'data-hook="{prefix}"'
        start = HTML.index(marker)
        div_start = HTML.rindex("<div", 0, start)
        depth, i = 0, div_start
        while True:
            open_tag = HTML.find("<div", i)
            close_tag = HTML.find("</div>", i)
            if close_tag == -1:
                raise AssertionError(f"unterminated tile markup for {prefix}")
            if open_tag != -1 and open_tag < close_tag:
                depth += 1
                i = open_tag + 4
            else:
                depth -= 1
                i = close_tag + 6
                if depth == 0:
                    return HTML[div_start:i]

    def test_every_tile_carries_exactly_one_real_anchor_link(self):
        for prefix in TILE_PREFIXES:
            html = self._tile_html(prefix)
            anchors = re.findall(r"<a\b[^>]*>", html)
            self.assertEqual(len(anchors), 1, f"{prefix}: expected one <a>, found {len(anchors)}")
            tag = anchors[0]
            href = re.search(r'href="([^"]+)"', tag)
            self.assertIsNotNone(href, f"{prefix}: link has no href")
            self.assertTrue(href.group(1).strip(), f"{prefix}: href is empty")

    def test_no_tile_link_is_pulled_out_of_tab_order(self):
        for prefix in TILE_PREFIXES:
            html = self._tile_html(prefix)
            self.assertNotIn('tabindex="-1"', html, f"{prefix}: a negative tabindex breaks Tab reachability")

    def test_no_clickable_lookalike_replaces_the_anchor(self):
        """A div/span carrying `onclick`/`role="button"` in place of a
        real link would be mouse-only unless it also wires its own
        keydown handler -- neither exists here today, so this asserts
        neither appears inside a tile."""
        for prefix in TILE_PREFIXES:
            html = self._tile_html(prefix)
            self.assertNotIn("onclick=", html, prefix)
            self.assertNotRegex(html, r'role="button"', prefix)

    def test_the_three_destinations_are_distinct_and_sport_specific(self):
        """Confirms the links actually route somewhere real and sport-
        specific -- not three copies of the same href, which would make
        Tab-reaching all three pointless."""
        hrefs = []
        for prefix in TILE_PREFIXES:
            html = self._tile_html(prefix)
            href = re.search(r'<a\b[^>]*href="([^"]+)"', html)
            hrefs.append(href.group(1))
        self.assertEqual(len(set(hrefs)), len(hrefs), hrefs)


if __name__ == "__main__":
    unittest.main()
