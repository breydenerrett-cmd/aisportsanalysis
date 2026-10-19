"""Tickets as stacked cards on a phone, and the UNGRADED section (2026-10-19).

At 375px the model page's Open/Graded ticket tables scrolled sideways and showed only the date and game; the pick,
the price and the result were cut off. Under 640px every ticket now also renders as a card (line 1 pick + price in
bold and the status chip; line 2 game and market; line 3 date and the recorded-before-the-start time; a graded
ticket adds result, units and CLV) and CSS swaps the card in for the table. The browser's layout is not run here,
so the two halves are pinned separately: the real page script is run under node and the cards' content and
structure are read off the DOM it builds (the harness has no CSS), and the stylesheet is read as text to prove the
swap happens under 640px and ONLY there. The screenshot at 375px is docs/audit/2026-10-19/model-mobile-375-v2.png.
"""

from __future__ import annotations

import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_hounds_board_pages import ticket_routes
from tests.test_hounds_web_pages import q, routes

CSS = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")


def media_block(css: str, header: str) -> str:
    """The text of the first ``@media (...)`` block whose condition equals ``header``."""
    start = css.index(f"@media ({header})")
    depth, i = 0, css.index("{", start)
    begin = i
    while True:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[begin + 1:i]
        i += 1


class TheStylesheetSwapsUnderSixFortyOnly(unittest.TestCase):
    def test_the_table_is_hidden_and_the_cards_shown_under_640px(self):
        block = media_block(CSS, "max-width: 639px")
        self.assertRegex(block, r"\.hd-ticketview > \.hd-tablewrap--tickets\s*\{\s*display:\s*none")
        self.assertRegex(block, r"\.hd-ticketview > \.hd-cards\s*\{\s*display:\s*block")
        self.assertRegex(block, r"\.hd-ticket > :not\(\.hd-card\)\s*\{\s*display:\s*none")
        self.assertRegex(block, r"\.hd-card\s*\{\s*display:\s*block")

    def test_on_a_wider_screen_the_cards_are_never_shown(self):
        outside = CSS.replace(media_block(CSS, "max-width: 639px"), "")
        self.assertRegex(outside, r"\.hd-cards\s*\{\s*display:\s*none")
        self.assertRegex(outside, r"\n\.hd-card\s*\{\s*display:\s*none")
        self.assertNotRegex(outside, r"\.hd-tablewrap--tickets\s*\{[^}]*display:\s*none")

    def test_the_desktop_table_rules_are_untouched(self):
        self.assertIn(".hd-table--tickets { min-width: 900px; }", CSS)

    def test_the_ungraded_chip_has_its_own_style(self):
        self.assertIn(".hd-res--ungraded", CSS)
        self.assertIn(".lbres--ungraded", (WEB / "css" / "kennel.css").read_text(encoding="utf-8"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCardsOnTheModelPage(unittest.TestCase):
    def model_page(self, **over):
        r = routes()
        r.update(ticket_routes("closer"))
        r.update(over)
        return run_page("hound", routes=r, search="?id=closer", queries=[
            q("rows", "[data-hook='bets-table'] tbody tr", "count"),
            q("cards", "[data-hook='bets-table-cards'] [data-hook='ticket-card']", "count"),
            q("picks", "[data-hook='bets-table-cards'] [data-hook='card-pick']", "texts"),
            q("prices", "[data-hook='bets-table-cards'] [data-hook='card-price']", "texts"),
            q("chips", "[data-hook='bets-table-cards'] [data-hook='card-status']", "texts"),
            q("games", "[data-hook='bets-table-cards'] [data-hook='card-game']", "texts"),
            q("when", "[data-hook='bets-table-cards'] [data-hook='card-when']", "texts"),
            q("units", "[data-hook='bets-table-cards'] [data-hook='card-units']", "texts"),
            q("clv", "[data-hook='bets-table-cards'] [data-hook='card-clv']", "texts"),
            q("results", "[data-hook='bets-table-cards'] [data-hook='card-result']", "count"),
            q("open_cards", "[data-hook='open-table-cards'] [data-hook='ticket-card']", "count"),
            q("open_result_lines", "[data-hook='open-table-cards'] [data-hook='card-result']", "count"),
            q("open_chips", "[data-hook='open-table-cards'] [data-hook='card-status']", "texts")])

    def test_every_graded_ticket_is_also_a_card_with_the_same_facts_as_its_table_row(self):
        f = self.model_page()["final"]
        self.assertGreater(f["rows"], 0)
        self.assertEqual(f["cards"], f["rows"])
        self.assertEqual(len(f["picks"]), f["rows"])
        # line 1: the pick and its price, and the status chip
        self.assertIn(f["picks"][0], ("Red Sox to win", "Yankees to win"))
        self.assertTrue(all(re.fullmatch(r"[-+]\d+", p) for p in f["prices"]), f["prices"])
        self.assertTrue(all(c in ("WON", "LOST", "PUSH", "VOID") for c in f["chips"]), f["chips"])
        # line 2: the game and its market
        self.assertTrue(all("NYY at BOS" in g and ("Moneyline" in g) for g in f["games"]), f["games"][:2])
        # line 3: the date and the recorded-before-the-start time (fixture: recorded 50 minutes before the start)
        self.assertTrue(all("Oct" in w and "50m before the start" in w for w in f["when"]), f["when"][:2])
        # a graded ticket carries its result line: units and CLV
        self.assertEqual(f["results"], f["rows"])
        self.assertTrue(all(re.fullmatch(r"[-+]?\d+\.\d\du|n/a", u) for u in f["units"]), f["units"][:3])
        self.assertTrue(all(c.startswith("CLV ") for c in f["clv"]), f["clv"][:3])

    def test_an_open_ticket_card_has_no_result_line(self):
        f = self.model_page()["final"]
        self.assertGreater(f["open_cards"], 0)
        self.assertEqual(f["open_result_lines"], 0)
        self.assertEqual(set(f["open_chips"]), {"PENDING"})

    def test_a_card_never_claims_a_closing_price_the_payload_does_not_carry(self):
        f = self.model_page()["final"]
        self.assertFalse(any("close" in c.lower() and "clv" not in c.lower() for c in f["clv"]))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLatestTicketsFeedHasCardsToo(unittest.TestCase):
    def test_the_leaderboard_feed_has_a_card_per_ticket(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("rows", "[data-hook='stream-list'] .hd-ticket", "count"),
            q("cards", "[data-hook='stream-list'] [data-hook='ticket-card']", "count"),
            q("picks", "[data-hook='stream-list'] [data-hook='card-pick']", "texts"),
            q("prices", "[data-hook='stream-list'] [data-hook='card-price']", "texts"),
            q("models", "[data-hook='stream-list'] .hd-card__model", "texts")])
        f = out["final"]
        self.assertEqual(f["cards"], f["rows"])
        self.assertEqual(f["picks"], ["Yankees to win", "Over 8.5"])
        self.assertEqual(len(f["prices"]), 2)
        self.assertEqual(f["models"], ["Closer", "Coin Flip"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheUngradedSection(unittest.TestCase):
    URL = "/hounds/closer/bets?status=ungraded&segment=forward&page=1&page_size=50"

    def ungraded_payload(self, n):
        rows = F.bet_rows("closer", n)
        items = [dict(__import__("src.hounds.contract", fromlist=["to_json"]).to_json(r),
                      result=None, units=None, clv_pts=None, status="UNGRADED") for r in rows]
        return {"hound_id": "closer", "items": items, "page": 1, "page_size": 50, "total": n, "pages": 1,
                "paper_only": True, "not_advice": "x"}

    def page(self, n):
        r = routes()
        r.update(ticket_routes("closer"))
        r[self.URL] = [200, self.ungraded_payload(n)]
        return run_page("hound", routes=r, search="?id=closer", queries=[
            q("heading", "[data-hook='ungraded-heading']"),
            q("section", "[data-hook='hound-ungraded-section']", "count"),
            q("rows", "[data-hook='ungraded-table'] tbody tr", "count"),
            q("chips", "[data-hook='ungraded-table'] [data-hook='ticket-status']", "texts"),
            q("card_chips", "[data-hook='ungraded-table-cards'] [data-hook='card-status']", "texts"),
            q("open_chips", "[data-hook='open-table'] [data-hook='ticket-status']", "texts"),
            q("note", "[data-hook='ungraded-note']")])

    def test_ungraded_tickets_are_listed_apart_with_a_count_and_say_UNGRADED(self):
        f = self.page(3)["final"]
        self.assertEqual(f["section"], 1)
        self.assertEqual(f["heading"], "Ungraded tickets (3)")
        self.assertEqual(f["rows"], 3)
        self.assertEqual(f["chips"], ["UNGRADED"] * 3)
        self.assertEqual(f["card_chips"], ["UNGRADED"] * 3)
        self.assertIn("not open", f["note"])
        self.assertNotIn("UNGRADED", f["open_chips"])           # and none of them is in the Open tickets table

    def test_a_model_with_none_shows_no_section(self):
        self.assertEqual(self.page(0)["final"]["section"], 0)

    def test_without_an_ungraded_route_there_is_no_section_and_no_error(self):
        r = routes()
        r.update(ticket_routes("closer"))
        out = run_page("hound", routes=r, search="?id=closer",
                       queries=[q("section", "[data-hook='hound-ungraded-section']", "count")])
        self.assertEqual(out["final"]["section"], 0)


if __name__ == "__main__":
    unittest.main()
