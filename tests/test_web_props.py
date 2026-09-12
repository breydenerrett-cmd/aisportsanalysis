"""Structural checks for the PLAYER PROPS screen (web/js/props.js).

A plain-text scan, like tests/test_web_structure.py -- never starts a server,
never imports a JS engine.

The one that matters most is `test_the_route_has_an_entry_point`. Wiring a
route and forgetting to link it is the defect this repo has now found ten
times, and it found it again this morning on #/performance, where a comment
beside the change asserted the route "stays reachable" while nothing in the
app pointed at it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

# The scanner itself, not a re-implementation of it. Re-declaring the word
# lists is how tests/test_web_structure.py once ended up with a WEAKER copy
# that dropped several phrases -- which is how "TOP PLAY" shipped without a
# red test. Importing `_violations_in` means this file cannot drift.
from tests.test_customer_language import _violations_in

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
WEB_JS = WEB / "js"

PROPS_JS = WEB_JS / "props.js"
PROPS_CSS = WEB / "css" / "props.css"
MAIN_JS = WEB_JS / "main.js"
INDEX = WEB / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TheScreenExists(unittest.TestCase):
    def test_the_module_and_its_stylesheet_are_present(self):
        for path in (PROPS_JS, PROPS_CSS):
            self.assertTrue(path.is_file(), f"{path.name} missing")
            self.assertTrue(_read(path).strip(), f"{path.name} is empty")

    def test_the_stylesheet_is_actually_loaded(self):
        """A stylesheet nothing links is the same as no stylesheet."""
        self.assertIn("css/props.css", _read(INDEX))


class TheRouteIsWired(unittest.TestCase):
    def setUp(self):
        self.main = _read(MAIN_JS)

    def test_main_imports_and_dispatches_it(self):
        self.assertIn('from "./props.js"', self.main)
        self.assertIn("renderProps", self.main)
        self.assertIn('route === "props"', self.main)

    def test_the_section_label_is_registered(self):
        self.assertIn('props: "PLAYER PROPS"', self.main)

    def test_the_route_has_an_entry_point(self):
        """Something a visitor can click must lead here.

        Deliberately ignores main.js and props.js itself: a route that only
        answers to a typed URL is an orphan, and a "back to props" link on
        the props screen is not an entry point. This is the check that was
        missing when #/performance was orphaned for a day.
        """
        entry_points = []
        for path in sorted(WEB_JS.glob("*.js")):
            if path.name in ("main.js", "props.js"):
                continue
            for line in _read(path).splitlines():
                stripped = line.strip()
                if stripped.startswith("*") or stripped.startswith("//"):
                    continue
                if 'href: "#/props"' in line or "'#/props'" in line:
                    entry_points.append(f"{path.name}: {stripped[:60]}")
        self.assertTrue(
            entry_points,
            "#/props has no entry point outside itself -- the route "
            "dispatches but nothing in the app links to it")

    def test_it_is_reachable_from_today_not_only_the_footer(self):
        """The footer is where a link goes to be permanent, not to be found.

        The owner's complaint was that every bet on #/today is a moneyline.
        The answer has to be reachable from that screen.
        """
        self.assertIn('href: "#/props"', _read(WEB_JS / "today.js"))


class ItIsABoardAndNotAPickList(unittest.TestCase):
    """The ordering rule, asserted in the client too.

    Selecting on the gap between our number and the price was measured
    returning -13.4% against -9.1% for taking everything. The server sends
    rows ordered by likelihood; the client must not re-sort them, and must
    not label any of them a pick.
    """

    def setUp(self):
        self.text = _read(PROPS_JS)

    def test_the_client_never_re_sorts_the_rows(self):
        self.assertNotIn(".sort(", self.text,
                         "the client re-orders rows the server ranked")

    def test_no_row_is_labelled_a_pick(self):
        lowered = self.text.lower()
        for word in ("top play", "best bet", "lock", "our pick",
                     "recommended"):
            self.assertNotIn(word, lowered, f"{word!r} on a board")

    def test_both_numbers_are_rendered(self):
        """Either number alone is misleading: a bet can win three nights in
        four and still be poor value, which is most of this board."""
        self.assertIn("prop-probability", self.text)
        self.assertIn("prop-breakeven", self.text)

    def test_the_plate_appearance_source_is_shown_not_hidden(self):
        """Before a lineup posts the model is using a season average, and
        the row says so rather than implying it knows tonight's slot."""
        self.assertIn("lineup not posted yet", self.text)


class ItSpeaksTheProductsLanguage(unittest.TestCase):
    def test_no_banned_customer_language(self):
        """The JS only.

        props.css is deliberately NOT scanned: the design system's token
        `var(--edge-1)` is a border colour used by every stylesheet in the
        repo, and flagging it would be the tripwire reading a variable name
        as customer prose. No other stylesheet is scanned either.
        """
        violations = []
        for lineno, line in enumerate(_read(PROPS_JS).splitlines(), start=1):
            violations.extend(_violations_in(line, f"props.js:{lineno}"))
        self.assertEqual(violations, [],
                         "banned customer language:\n" + "\n".join(violations))

    def test_no_probability_identifiers_leak_into_the_client(self):
        text = _read(PROPS_JS)
        for token in ("win_probability", "winProbability", "true_probability"):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
