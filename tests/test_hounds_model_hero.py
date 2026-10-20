"""The model page after the round-2 critic (2026-10-19): the bankroll is the one hero tile, the rest is one tidy row, Fire now is a bar.

The critic: "Fire-now card orphaned half-width; KPI grid ragged with 8 equal tiles." Now the Overview opens on one wide hero tile
(the big dollar bankroll, the return beside it with its 24h / 7d / 30d / Season tabs) and a single secondary row of seven compact
tiles; the Fire now panel is a full-width action bar. Same numbers, same hooks, same document order as before.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_page
from tests.test_hounds_board_pages import q, routes

ROOT = Path(__file__).resolve().parent.parent
STUDIO = (ROOT / "web" / "css" / "studio.css").read_text(encoding="utf-8")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBankrollIsTheHero(unittest.TestCase):
    def test_the_hero_holds_exactly_the_bankroll_and_the_return_and_the_row_holds_the_other_seven(self):
        out = run_page("hound", routes=routes(), search="?id=closer", queries=[
            q("hero", "[data-hook='bank-hero'] .hd-kpi", "attrs", attr="data-slot"),
            q("row", "[data-hook='kpi-row'] .hd-kpi", "attrs", attr="data-slot"),
            q("all", "[data-hook='scoreboard-tiles'] .hd-kpi", "attrs", attr="data-slot"),
            q("tabs", "[data-hook='bank-hero'] [data-hook='return-tabs'] button", "attrs", attr="data-window"),
            q("bank", "[data-hook='bank-hero'] .hd-kpi[data-slot='bankroll'] .hd-kpi__big"),
            q("ret", "[data-hook='bank-hero'] [data-hook='return-big']")])
        f = out["final"]
        self.assertEqual(f["hero"], ["bankroll", "return"])
        self.assertEqual(f["row"], ["units", "record", "drawdown", "yield", "bets", "clv", "streak"])
        self.assertEqual(f["all"], ["bankroll", "return", "units", "record", "drawdown", "yield", "bets", "clv", "streak"], "document order is unchanged")
        self.assertEqual(f["tabs"], ["h24", "d7", "d30", "season"])
        b = F.hounds()[0]["bankroll"]
        self.assertIn(f"${b['current']:,.2f}", f["bank"])
        self.assertEqual(f["ret"], f"{b['return_pct']:+.1f}%")

    def test_the_small_sample_sentence_has_one_full_stop_not_two(self):
        out = run_page("hound", routes=routes(), search="?id=closer",
                       queries=[q("bank", ".hd-kpi[data-slot='bankroll'] .hd-kpi__small")])
        self.assertNotIn("..", out["final"]["bank"])


class TheLayoutCss(unittest.TestCase):
    def test_the_hero_is_wide_and_big_the_row_is_seven_compact_tiles_and_wraps_under_1080(self):
        self.assertRegex(STUDIO, r"\.hd-bankhero \{[^}]*grid-template-columns: minmax\(0, 1\.25fr\) minmax\(0, 1fr\)")
        self.assertRegex(STUDIO, r'\.hd-kpi\[data-slot="bankroll"\] \.hd-kpi__big \{ font-size: clamp\(44px, 6vw, 68px\)')
        self.assertRegex(STUDIO, r"\.hd-kpirow \{ display: grid; grid-template-columns: repeat\(7, minmax\(0, 1fr\)\)")
        self.assertRegex(STUDIO, r"@media \(max-width: 1080px\) \{ \.hd-kpirow \{ grid-template-columns: repeat\(4")
        self.assertRegex(STUDIO, r"@media \(max-width: 760px\) \{\s*\.hd-bankhero \{ grid-template-columns: minmax\(0, 1fr\)")

    def test_fire_now_is_a_full_width_action_bar_not_half_a_row(self):
        self.assertRegex(STUDIO, r"\.hounds-page \.dk-top \{ grid-template-columns: minmax\(0, 1fr\); \}")
        bar = re.search(r'\.hounds-page \.dk-top \[data-hook="dog-fire-section"\] \{[^}]*\}', STUDIO).group(0)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr) auto", bar)
        self.assertIn('[data-hook="dog-fire"] { display: contents; }', STUDIO)
        # the dog kit's own two-column rule (dog-kit.css) is overridden here, in the later file
        kit = (ROOT / "web" / "css" / "dog-kit.css").read_text(encoding="utf-8")
        self.assertIn("minmax(0, 1.1fr) minmax(0, 1fr)", kit)


if __name__ == "__main__":
    unittest.main()
