"""Ticket rows and copy as a bettor reads them on hounds.html and hound.html (QA pass, 2026-10-25).

Three live defects, one test each:
  * a ticket's "recorded" and "price at" times were UTC ("Oct 26 00:20 UTC"); a person reads the zone on their clock, so every
    time on a ticket row now goes through web/js/local-time.js (the viewer's zone), and the rendered row carries no "UTC";
  * a member hound's ticket showed the raw feed key ("williamhill_us", "betonlineag"); the label map names it instead;
  * the "New: no bets yet" badge broke the no-"new" copy rule; it reads "No bets yet".

The row is rendered by the real ``ticketItem`` in node with a small DOM shim (the page's own module, not a copy of it).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js

WEB_JS = Path(__file__).resolve().parent.parent / "web" / "js"

# a fake document: enough for h() to build a tree that the test can read back as text
DOM_SHIM = """
globalThis.document = {
  createElement(tag) {
    return { tag, textContent: "", kids: [], attrs: {}, style: {}, setAttribute(k, v) { this.attrs[k] = v; },
      appendChild(c) { this.kids.push(c); return c; }, addEventListener() {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } } };
  },
  createTextNode(t) { return { tag: "#text", textContent: String(t), kids: [], attrs: {}, appendChild() {}, setAttribute() {} }; },
};
function visibleText(n) {
  if (!n) return "";
  if (typeof n === "string") return n;
  return [n.textContent || "", ...(n.kids || []).map(visibleText)].join(" ");
}
"""

TICKET = {
    "hound_id": "u-1", "hound_name": "Rex", "date": "2026-10-25", "game": "Brewers at Cubs", "market": "moneyline",
    "selection": "Cubs ML", "price": 120, "book": "williamhill_us", "book_count": 3,
    "recorded_utc": "2026-10-26T00:20:00Z", "start_utc": "2026-10-26T01:00:00Z",
    "live_price_at_utc": "2026-10-26T00:10:00Z", "result": "pending", "status": "OPEN",
}


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheTicketRowRendersInTheViewersZone(unittest.TestCase):
    def setUp(self):
        import json
        src = ('import { ticketItem, liveTag } from "./hounds-tickets.js";\n'
               'import * as B from "./hounds-board.js";\n' + DOM_SHIM +
               f'const t = {json.dumps(TICKET)};\n'
               'console.log(JSON.stringify({ row: visibleText(ticketItem(t, { showModel: true })), '
               'live: visibleText(liveTag(t)), recorded: B.recordedText(t).text, books: B.booksText(t) }));')
        self.out = run_js(src, viewer=None)

    def test_no_utc_text_in_the_rendered_row(self):
        self.assertNotIn("UTC", self.out["row"])
        self.assertNotIn("UTC", self.out["live"])
        self.assertNotIn("UTC", self.out["recorded"])

    def test_the_recorded_time_is_a_clock_in_the_viewers_zone(self):
        # the zone name depends on the machine running the test; the clock and the gap before the start do not
        self.assertRegex(self.out["recorded"], r"\d{1,2}:\d{2} (AM|PM)")
        self.assertIn("40m before the start", self.out["recorded"])

    def test_the_live_price_time_is_a_clock_too(self):
        self.assertRegex(self.out["live"], r"^Live bet · price at \d{1,2}:\d{2} (AM|PM)")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheBookNamesAreLabelled(unittest.TestCase):
    def test_a_raw_feed_key_is_shown_as_its_label(self):
        import json
        out = run_js('import * as B from "./hounds-board.js";'
                     f'console.log(JSON.stringify([B.booksText({json.dumps(TICKET)}), '
                     'B.booksText({ book: "betonlineag", book_count: 1 }), B.booksText({ book: "lowvig" }), '
                     'B.booksText({ book: "betus", book_count: 2 })]));', viewer=None)
        self.assertEqual(out[0], "Caesars, 3 books")
        self.assertEqual(out[1], "BetOnline, 1 book")
        self.assertEqual(out[2], "LowVig")
        self.assertEqual(out[3], "BetUS, 2 books")

    def test_no_raw_key_reaches_the_row(self):
        import json
        out = run_js('import { ticketItem } from "./hounds-tickets.js";' + DOM_SHIM +
                     f'console.log(JSON.stringify(visibleText(ticketItem({json.dumps(TICKET)}, {{ showModel: true }}))));',
                     viewer=None)
        self.assertNotIn("williamhill_us", out)


class TheNoNewCopyRule(unittest.TestCase):
    def test_no_web_js_string_says_new_colon(self):
        # the owner's copy rule: no "New:" badge (2026-10-25). "New token", "New York" and "Newer" are not badges.
        pattern = re.compile(r"""["'`]New:""")
        hits = []
        for path in sorted(WEB_JS.glob("*.js")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith(("//", "*", "/*")):
                    hits.append(f"{path.name}:{n}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
