"""GET /props and src/report/props.py -- the prop board's transport layer.

Every store is injected. A test that reads the real disk passes or fails by
which machine it runs on and by what the capture bot committed that hour,
which is how a green suite stops meaning anything.
"""

from __future__ import annotations

import unittest

try:
    from fastapi import HTTPException
    _HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAVE_FASTAPI = False

from src.report import props as report_props


LEAGUE_HISTORY = [
    {"date": f"2026-08-{day:02d}", "type": "batter", "player_name": "Batter A",
     "h": 1, "ab": 4, "pa": 4, "doubles": 0, "triples": 0, "hr": 0,
     "r": 0, "rbi": 0, "total_bases": 1}
    for day in range(1, 31)
]


def _quotes(line=0.5, over=-150, under=125, books=("draftkings", "fanduel"),
            player="Batter A", date="2026-09-11"):
    rows = []
    for book in books:
        for side, price in (("Over", over), ("Under", under)):
            rows.append({
                "game_date": date, "event_id": "e1", "player": player,
                "market": "batter_hits", "line": line, "side": side,
                "price": price, "book": book,
                "observed_utc": f"{date}T20:00:00Z",
            })
    return rows


class BoardAssembly(unittest.TestCase):
    def test_a_real_shaped_board_comes_back_ranked_and_priced(self):
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(),
            batter_rows=LEAGUE_HISTORY, slots={})
        self.assertEqual(board["date"], "2026-09-11")
        self.assertIsNone(board["reason"])
        self.assertTrue(board["contracts"])
        first = board["contracts"][0]
        for field in ("player", "market", "line", "side", "probability",
                      "breakeven", "gap_vs_breakeven", "price", "book"):
            self.assertIn(field, first)

    def test_contracts_are_ordered_by_likelihood_not_by_the_price_gap(self):
        """The ordering the whole surface rests on.

        Selecting on the gap against the price was measured at -13.4%
        against a -9.1% control, so the board must never present that
        ranking. Checked here as well as in the analysis tests because this
        layer could re-sort and nothing downstream would notice.
        """
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(),
            batter_rows=LEAGUE_HISTORY, slots={})
        probabilities = [c["probability"] for c in board["contracts"]]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))

    def test_nothing_below_a_coin_flip_reaches_the_board(self):
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(),
            batter_rows=LEAGUE_HISTORY, slots={})
        for contract in board["contracts"]:
            self.assertGreater(contract["probability"], 0.5)

    def test_an_empty_board_says_why_rather_than_rendering_blank(self):
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=[], batter_rows=LEAGUE_HISTORY, slots={})
        self.assertEqual(board["contracts"], [])
        self.assertIn("no prop prices posted", board["reason"])

    def test_no_batter_history_is_a_reason_not_a_crash(self):
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(), batter_rows=[], slots={})
        self.assertEqual(board["contracts"], [])
        self.assertIn("no batter history", board["reason"])

    def test_the_limit_is_honoured_and_capped(self):
        rows = []
        for i in range(12):
            rows.extend(_quotes(player=f"Batter {i}"))
        history = []
        for i in range(12):
            for row in LEAGUE_HISTORY:
                history.append({**row, "player_name": f"Batter {i}"})
        board = report_props.board_for_date(
            "2026-09-11", limit=3, prop_rows=rows,
            batter_rows=history, slots={})
        self.assertLessEqual(len(board["contracts"]), 3)

    def test_the_counts_report_what_was_refused(self):
        """A board that silently drops most of its input looks like a thin
        slate, and a reader cannot tell those apart without this."""
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(books=("draftkings",)),
            batter_rows=LEAGUE_HISTORY, slots={})
        self.assertIn("refused", board["counts"])
        self.assertTrue(board["counts"]["refused"])


class BattingSlotJoin(unittest.TestCase):
    """Slot is the input this board is most sensitive to.

    SLOT_PLATE_APPEARANCES runs 4.467 leading off to 3.461 batting ninth --
    about 29% more chances -- which is why a lineup posting moves a player
    total far more than it moves a moneyline.
    """

    def test_a_posted_slot_raises_the_over(self):
        leadoff = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(), batter_rows=LEAGUE_HISTORY,
            slots={"Batter A": 1})
        ninth = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(), batter_rows=LEAGUE_HISTORY,
            slots={"Batter A": 9})
        over_first = [c for c in leadoff["contracts"]
                      if c["side"] == "Over"][0]
        over_ninth = [c for c in ninth["contracts"] if c["side"] == "Over"][0]
        self.assertGreater(over_first["probability"],
                           over_ninth["probability"])
        self.assertEqual(over_first["batting_slot"], 1)

    def test_no_lineup_yet_still_prices_and_says_which_estimate_it_used(self):
        board = report_props.board_for_date(
            "2026-09-11", prop_rows=_quotes(),
            batter_rows=LEAGUE_HISTORY, slots={})
        self.assertTrue(board["contracts"])
        self.assertEqual(board["contracts"][0]["expected_pa_source"],
                         "season_average")

    def test_the_stores_explicit_order_beats_list_position(self):
        """The store carries `order`; position is only the fallback.

        A card that ever arrived out of order would otherwise hand every
        batter the wrong slot, silently, on the one input that matters most.
        """
        stored = {"1": {"date": "2026-09-11", "game_pk": 1,
                        "away": [{"name": "Nine Hitter", "order": 9},
                                 {"name": "Leadoff", "order": 1}],
                        "home": []}}
        import src.pipeline.lineup_store as lineup_store
        original = lineup_store.read
        lineup_store.read = lambda *a, **k: stored
        try:
            slots = report_props._slots_for("2026-09-11")
        finally:
            lineup_store.read = original
        self.assertEqual(slots["Nine Hitter"], 9)
        self.assertEqual(slots["Leadoff"], 1)

    def test_another_dates_lineup_is_not_used_for_tonight(self):
        stored = {"1": {"date": "2026-09-10", "game_pk": 1,
                        "away": [{"name": "Leadoff", "order": 1}],
                        "home": []}}
        import src.pipeline.lineup_store as lineup_store
        original = lineup_store.read
        lineup_store.read = lambda *a, **k: stored
        try:
            self.assertEqual(report_props._slots_for("2026-09-11"), {})
        finally:
            lineup_store.read = original

    def test_an_unreadable_lineup_store_is_empty_not_fatal(self):
        import src.pipeline.lineup_store as lineup_store
        original = lineup_store.read

        def boom(*_a, **_k):
            raise OSError("store unreadable")

        lineup_store.read = boom
        try:
            self.assertEqual(report_props._slots_for("2026-09-11"), {})
        finally:
            lineup_store.read = original


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class Endpoint(unittest.TestCase):
    def test_a_malformed_date_is_a_400_not_a_502(self):
        from api import props as api_props
        with self.assertRaises(HTTPException) as ctx:
            api_props._validate("11-09-2026")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_a_well_formed_date_passes_through(self):
        from api import props as api_props
        self.assertEqual(api_props._validate("2026-09-11"), "2026-09-11")

    def test_an_unreadable_store_is_a_502_not_a_blank_board(self):
        """An empty board and a broken one are different facts.

        A client that cannot tell them apart shows "nothing tonight" when
        the truth is "we could not look".
        """
        from api import props as api_props
        original = api_props.props_mod.board_for_date

        def boom(*_a, **_k):
            raise OSError("store unreadable")

        api_props.props_mod.board_for_date = boom
        try:
            with self.assertRaises(HTTPException) as ctx:
                api_props._board("2026-09-11", 10)
        finally:
            api_props.props_mod.board_for_date = original
        self.assertEqual(ctx.exception.status_code, 502)

    def test_the_route_is_actually_served(self):
        """Green tests prove the module works, never that anything runs it.

        Asserted against the OpenAPI schema rather than `app.routes`. This
        FastAPI version wraps every `include_router` call in an opaque
        `_IncludedRouter` with no `.path`, so walking `app.routes` finds
        only the handful of routes declared directly on the app and would
        report every mounted router as missing -- including /games and
        /card, which plainly work. The schema is what is actually exposed.
        """
        from api.app import app
        paths = set(app.openapi().get("paths") or {})
        self.assertIn("/props", paths)
        self.assertIn("/props/{date}", paths)
        # The sanity check that would have caught the first version of this
        # test: a surface known to be mounted must also be found.
        self.assertIn("/card", paths)


if __name__ == "__main__":
    unittest.main()
