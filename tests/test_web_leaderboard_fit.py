"""The leaderboard table is not clipped on a laptop (round 2, 2026-10-19).

The critic: "table clipped at 1440 ('AVG P')". A 13-column table in a 1048px column cannot fit, so: under 1500px the low-value columns
(7d, 24h, average price, last 10) are hidden; from 1500px the page widens to 1240px and every column shows; a table still too wide
(a phone) scrolls inside its own card with the rank and model columns pinned. This file holds that two ways: a static check of the
CSS (which columns are visible at which width, and that their estimated widths fit the column) and, where Chrome is installed, a
measurement of the real table at 1440 and 1600 against the page's fixtures.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import unittest
import http.server
from pathlib import Path

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js
from tests.test_no_horizontal_overflow import CHROME, make_handler

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
STUDIO = (ROOT / "web" / "css" / "studio.css").read_text(encoding="utf-8")

# estimated minimum width in px of each column's content (rank, then the COLUMNS of web/js/hounds-board.js); a measured table is the real test
EST = {"rank": 44, "model": 300, "type": 90, "record": 80, "bankroll": 80, "return": 70, "d7": 60, "h24": 60, "units": 70, "bets": 48,
       "price": 72, "clv": 128, "last10": 110, "status": 110}
LOW_VALUE = {"d7", "h24", "price", "last10"}
COLUMN_AT_1440 = 1080 - 32          # css/lh.css: .hounds-page .hd-wrap max-width 1080, 16px gutters
COLUMN_AT_1600 = 1360 - 32          # the wide page from 1500px (measured: the 13 columns need 1312px)


def hidden_under_1500() -> set:
    block = re.search(r"@media \(max-width: 1499px\) \{(.*?)\n\}", STUDIO, re.S).group(1)
    return set(re.findall(r"\.hd-col-([a-z0-9]+)", block.split("{")[0]))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheColumnsAreChosenToFit(unittest.TestCase):
    def columns(self):
        keys = run_js('import { COLUMNS } from "./hounds-board.js";\nconsole.log(JSON.stringify(COLUMNS.map((c) => c.key)));')
        return ["rank"] + keys

    def test_the_hidden_set_is_the_four_low_value_columns_and_nothing_a_bettor_needs(self):
        self.assertEqual(hidden_under_1500(), LOW_VALUE)
        for need in ("model", "record", "bankroll", "return", "units", "bets", "status"):
            self.assertNotIn(need, hidden_under_1500())

    def test_every_column_has_a_width_estimate_and_the_visible_ones_fit_at_1440(self):
        cols = self.columns()
        self.assertEqual(sorted(cols), sorted(EST), "a new column needs a width estimate here")
        visible = [c for c in cols if c not in hidden_under_1500()]
        self.assertLessEqual(sum(EST[c] for c in visible), COLUMN_AT_1440, f"visible at 1440: {visible}")
        # and the full 13 would NOT have fit: the reason the columns are hidden at all
        self.assertGreater(sum(EST[c] for c in cols), COLUMN_AT_1440)

    def test_from_1500_the_page_widens_and_all_columns_fit(self):
        cols = self.columns()
        self.assertRegex(STUDIO, r"@media \(min-width: 1500px\) \{\s*\.hounds-page \.hd-wrap:has\(\[data-hook=\"hounds-table\"\]\) \{ max-width: 1360px; \}")
        self.assertLessEqual(sum(EST[c] for c in cols), COLUMN_AT_1600)

    def test_a_long_model_meta_line_wraps_instead_of_holding_the_model_column_wide(self):
        # live data: "MLB, NFL . moneyline, spread, total . by Handler 21E8's kennel" was nowrap and made the model column 434px
        self.assertRegex(STUDIO, r"td\.hd-col-model[^{]*\{ white-space: normal; min-width: 0; max-width: 300px; \}")

    def test_a_narrower_table_scrolls_inside_its_card_with_rank_and_model_pinned(self):
        self.assertRegex(STUDIO, r"\.hd-table--board th\.hd-col-rank[^{]*\{[^}]*position: sticky; left: 0;")
        self.assertRegex(STUDIO, r"\.hd-table--board th\.hd-col-model[^{]*\{[^}]*position: sticky; left: 44px;")
        self.assertRegex(STUDIO, r"@media \(max-width: 1079px\) \{ \.hounds-page \.hd-table--board \{ min-width: 760px; \} \}")
        self.assertNotRegex(STUDIO, r"\.hounds-page \.hd-table--board \{ min-width: (?!0|760)")


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheRealTableFits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        # owner ruling 2026-10-20 kennel-first: the board opens COMPACT (rank, hound, record, bankroll, return); "All stats" shows every column
        def measure(click=None):
            env = dict(os.environ, **({"CLICK": click} if click else {}))
            proc = subprocess.run(["node", str(HERE / "table_fit.mjs"), CHROME, base, "/web/hounds.html", "1440", "1600"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=120, env=env)
            lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
            if proc.returncode != 0 or not lines:
                raise AssertionError(f"table_fit failed ({proc.returncode}): {proc.stderr[-1200:]}")
            return {r["width"]: r for r in json.loads(lines[-1])}
        cls.results = measure()
        cls.full = measure("[data-hook='view-toggle']")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_no_table_scrolls_sideways_at_1440_or_1600(self):
        for width, r in self.results.items():
            self.assertTrue(r["wraps"], f"no table rendered at {width}")
            for wrap in r["wraps"]:
                with self.subTest(width=width, table=wrap["hook"]):
                    self.assertLessEqual(wrap["scroll"], wrap["client"] + 1, f"clipped: {wrap}")
            self.assertLessEqual(r["docScroll"], width + 1)

    def test_the_board_opens_compact_at_every_width(self):
        board = lambda w: next(x for x in self.results[w]["wraps"] if x["heads"])  # noqa: E731
        for width in (1440, 1600):
            self.assertEqual(board(width)["heads"], ["rank", "model", "record", "bankroll", "return"], width)

    def test_all_stats_shows_every_column_at_1600_without_clipping_and_scrolls_inside_its_card_at_1440(self):
        board = lambda w: next(x for x in self.full[w]["wraps"] if x["heads"])  # noqa: E731
        self.assertTrue(LOW_VALUE <= set(board(1600)["heads"]), board(1600)["heads"])
        self.assertLessEqual(board(1600)["scroll"], board(1600)["client"] + 1, board(1600))
        self.assertLessEqual(self.full[1440]["docScroll"], 1441)           # the card scrolls, never the document

if __name__ == "__main__":
    unittest.main()
