"""The price-improvement library: honest numbers, honest labels."""

import unittest

from src.analysis import prices


def _board(entries):
    return [{"book": book, "away_price": away, "home_price": home}
            for book, away, home in entries]


EVEN_BOARD = _board([(f"book_{i}", -110, -110) for i in range(6)])


class SnapshotTests(unittest.TestCase):
    def test_below_the_book_floor_there_is_no_consensus(self):
        result = prices.snapshot(_board([("a", -110, -110)] * 5))
        self.assertIn("skipped", result)
        self.assertIn("5 books", result["skipped"])

    def test_a_flat_board_shows_zero_range_and_negative_improvement(self):
        """Six identical -110/-110 quotes: consensus 0.5 a side, best price
        implies 0.5238 -- the vig. Improvement is NEGATIVE and reported
        as-is, because on a flat board shopping buys nothing."""
        result = prices.snapshot(EVEN_BOARD)
        home = result["sides"]["home"]
        self.assertAlmostEqual(home["consensus_probability"], 0.5)
        self.assertAlmostEqual(home["improvement_points"], -0.02381, places=5)
        self.assertEqual(result["dispersion"]["home_probability_range"], 0.0)

    def test_an_off_market_book_is_found_and_measured(self):
        board = EVEN_BOARD[:5] + _board([("generous", +105, -125)])
        result = prices.snapshot(board)
        away = result["sides"]["away"]
        self.assertEqual(away["best_book"], "generous")
        self.assertEqual(away["best_price"], 105)
        # +105 implies 0.4878; the consensus away probability sits near 0.497
        # (five even books and one leaning home), so the away side's best
        # price implies LESS than consensus: positive improvement.
        self.assertGreater(away["improvement_points"], 0.0)
        self.assertGreater(away["improvement_return_pct"], 0.0)
        self.assertGreater(result["dispersion"]["home_probability_range"], 0.0)

    def test_the_label_is_always_attached_and_never_speaks_in_edges(self):
        result = prices.snapshot(EVEN_BOARD)
        self.assertIn("not expected value", result["label"])
        self.assertNotIn("edge", result["label"])

    def test_an_unpriceable_quote_costs_one_book_not_the_board(self):
        board = EVEN_BOARD + _board([("broken", 0, -110)])
        result = prices.snapshot(board)
        self.assertEqual(result["dispersion"]["books"], 6)


class LatestInstantTests(unittest.TestCase):
    def test_only_the_newest_capture_instant_survives(self):
        quotes = [
            {"ts": "2026-08-31T20:00:00Z", "book": "a",
             "away_price": -110, "home_price": -110},
            {"ts": "2026-08-31T21:00:00Z", "book": "a",
             "away_price": -105, "home_price": -115},
            {"ts": "2026-08-31T21:00:00Z", "book": "b",
             "away_price": -110, "home_price": -110},
        ]
        board = prices.latest_instant(quotes)
        self.assertEqual(len(board), 2)
        self.assertTrue(all(q["ts"].endswith("21:00:00Z") for q in board))

    def test_a_stale_best_price_never_mixes_into_a_fresh_board(self):
        """The 20:00 quote had the best away price; it must NOT be compared
        against the 21:00 consensus -- that would manufacture improvement
        out of capture latency."""
        quotes = [{"ts": "2026-08-31T20:00:00Z", "book": "old_gold",
                   "away_price": +150, "home_price": -170}]
        quotes += [{"ts": "2026-08-31T21:00:00Z", "book": f"b{i}",
                    "away_price": -110, "home_price": -110}
                   for i in range(6)]
        board = prices.latest_instant(quotes)
        self.assertNotIn("old_gold", [q["book"] for q in board])


class ForGameTests(unittest.TestCase):
    def test_a_game_with_no_observations_says_so(self):
        result = prices.for_game(away_team="Cincinnati Reds",
                                 home_team="New York Mets",
                                 date="2026-08-31", rows=[])
        self.assertIn("skipped", result)

    def test_the_full_path_from_store_rows(self):
        rows = [{"observed_utc": "2026-08-31T21:00:00Z", "event_id": "e1",
                 "commence_time": "2026-08-31T23:10:00Z",
                 "home_team": "New York Mets",
                 "away_team": "Cincinnati Reds", "book": f"b{i}",
                 "book_last_update": "2026-08-31T20:59:00Z",
                 "home_price": -110, "away_price": -110}
                for i in range(6)]
        result = prices.for_game(away_team="Cincinnati Reds",
                                 home_team="New York Mets", rows=rows)
        self.assertIn("sides", result)
        self.assertEqual(result["observed_utc"], "2026-08-31T21:00:00Z")


if __name__ == "__main__":
    unittest.main()


class WiringTests(unittest.TestCase):
    def test_by_matchup_keys_by_abbreviation_and_date(self):
        rows = [{"observed_utc": "2026-08-31T21:00:00Z", "event_id": "e1",
                 "commence_time": "2026-08-31T23:10:00Z",
                 "home_team": "New York Mets",
                 "away_team": "Cincinnati Reds", "book": f"b{i}",
                 "book_last_update": "x",
                 "home_price": -110, "away_price": -110} for i in range(6)]
        index = prices.by_matchup(rows)
        self.assertIn(("CIN", "NYM", "2026-08-31"), index)
        self.assertIn("sides", index[("CIN", "NYM", "2026-08-31")])

    def test_a_thin_board_lands_as_its_reason_not_a_table(self):
        rows = [{"observed_utc": "2026-08-31T21:00:00Z", "event_id": "e1",
                 "commence_time": "2026-08-31T23:10:00Z",
                 "home_team": "New York Mets",
                 "away_team": "Cincinnati Reds", "book": "only_one",
                 "book_last_update": "x",
                 "home_price": -110, "away_price": -110}]
        index = prices.by_matchup(rows)
        self.assertIn("skipped", index[("CIN", "NYM", "2026-08-31")])

    def test_the_dossier_records_the_section_or_the_honest_gap(self):
        from src.detect import dossier as dossier_mod
        game = {"away_team": "CIN", "home_team": "NYM", "date": "2026-08-31"}
        with_section = dossier_mod.build(
            game, None, price_improvement={"sides": {}, "dispersion": {},
                                           "label": prices.LABEL})
        self.assertIn("price_improvement", with_section.sections)
        without = dossier_mod.build(game, None, price_improvement=None)
        self.assertIn("price_improvement", without.gaps)


class OneBoardTests(unittest.TestCase):
    """One market, one store (docs/OVERNIGHT_RUN.md 2026-08-31, write-up 4)."""

    def rows(self, books=6, commence="2026-08-31T23:10:00Z",
             observed="2026-08-31T21:00:00Z"):
        return [{"observed_utc": observed, "event_id": "e1",
                 "commence_time": commence, "home_team": "New York Mets",
                 "away_team": "Cincinnati Reds", "book": f"b{i}",
                 "book_last_update": "x",
                 "home_price": -110 - i, "away_price": -110 + i}
                for i in range(books)]

    def test_a_board_carries_its_quotes_its_instant_and_its_source(self):
        board = prices.boards_by_matchup(self.rows())[
            ("CIN", "NYM", "2026-08-31")]
        self.assertEqual(len(board["quotes"]), 6)
        self.assertEqual(board["observed_utc"], "2026-08-31T21:00:00Z")
        self.assertEqual(board["source"], prices.SOURCE)

    def test_only_the_newest_instant_is_on_the_board(self):
        rows = self.rows() + self.rows(books=3,
                                       observed="2026-08-31T22:00:00Z")
        board = prices.boards_by_matchup(rows)[("CIN", "NYM", "2026-08-31")]
        self.assertEqual(len(board["quotes"]), 3)
        self.assertEqual(board["observed_utc"], "2026-08-31T22:00:00Z")

    def test_the_summary_describes_exactly_the_board_it_was_given(self):
        boards = prices.boards_by_matchup(self.rows(books=7))
        index = prices.by_matchup(boards=boards)
        key = ("CIN", "NYM", "2026-08-31")
        self.assertEqual(index[key]["dispersion"]["books"],
                         len(boards[key]["quotes"]))
        self.assertEqual(index[key]["observed_utc"],
                         boards[key]["observed_utc"])

    def test_a_west_coast_game_is_keyed_by_its_official_date(self):
        """A 20:41 ET first pitch is 00:41 UTC the next day.

        Slicing the UTC commence time filed those games under tomorrow, where
        the briefing -- which keys by MLB's official date, like everything
        else here -- never looked, so half a slate silently showed no board.
        """
        boards = prices.boards_by_matchup(
            self.rows(commence="2026-09-01T00:41:00Z"))
        self.assertIn(("CIN", "NYM", "2026-08-31"), boards)
        self.assertNotIn(("CIN", "NYM", "2026-09-01"), boards)


class BriefingBoardTests(unittest.TestCase):
    """The board reaches the detector through the dossier, or a gap does."""

    GAME = {"away_team": "CIN", "home_team": "NYM", "date": "2026-08-31",
            "game_pk": 1}

    def board(self):
        return {"quotes": [{"ts": "2026-08-31T21:00:00Z", "book": f"b{i}",
                            "away_price": -110, "home_price": -110}
                           for i in range(6)],
                "observed_utc": "2026-08-31T21:00:00Z",
                "source": prices.SOURCE}

    def test_build_slate_routes_one_board_into_the_dossier(self):
        from src.pipeline import briefing
        key = ("CIN", "NYM", "2026-08-31")
        slate = briefing.build_slate(
            [dict(self.GAME)], None, detectors={},
            price_boards_by_key={key: self.board()},
            price_improvement_by_key={})
        dossier = slate["games"][0]["dossier"]
        self.assertEqual(len(dossier.get("multibook_board")["quotes"]), 6)

    def test_the_schedules_spelling_of_a_club_finds_the_feeds_board(self):
        """ATH/AZ on the schedule, OAK/ARI in the odds feed, one board.

        On 2026-08-31 both those cards said "no multi-book board" while the
        store held eleven books for each.
        """
        from src.pipeline import briefing
        game = {"away_team": "ATH", "home_team": "AZ", "date": "2026-08-31",
                "game_pk": 2}
        slate = briefing.build_slate(
            [game], None, detectors={},
            price_boards_by_key={("OAK", "ARI", "2026-08-31"): self.board()},
            price_improvement_by_key={})
        self.assertIsNotNone(slate["games"][0]["dossier"].get("multibook_board"))

    def test_a_game_with_no_board_gets_a_named_gap_not_a_substitute(self):
        from src.pipeline import briefing
        slate = briefing.build_slate(
            [dict(self.GAME)], None, detectors={},
            price_boards_by_key={}, price_improvement_by_key={})
        dossier = slate["games"][0]["dossier"]
        self.assertIsNone(dossier.get("multibook_board"))
        self.assertIn("multibook_board", dossier.gaps)


class InPlayRowsTests(unittest.TestCase):
    """The multi-book store holds post-first-pitch rows; a board must not.

    A capture is one bulk call and the feed keeps listing a game after it
    starts, so every capture moment past a first pitch appends in-play rows
    (592 of 5,803 on 2026-08-31/09-01, up to 2h50m late, prices to -10000).
    A board is a price to shop, so it is the last PRE-GAME instant.
    """

    KEY = ("CIN", "NYM", "2026-08-31")
    COMMENCE = "2026-08-31T23:10:00Z"

    def rows(self, observed, books=6, home=-110, away=-110):
        return [{"observed_utc": observed, "event_id": "e1",
                 "commence_time": self.COMMENCE,
                 "home_team": "New York Mets", "away_team": "Cincinnati Reds",
                 "book": f"b{i}", "book_last_update": "x",
                 "home_price": home, "away_price": away}
                for i in range(books)]

    def test_the_board_is_the_last_pregame_instant_not_the_newest_row(self):
        rows = (self.rows("2026-08-31T23:00:00Z")
                + self.rows("2026-08-31T23:47:00Z", home=-10000, away=900))
        board = prices.boards_by_matchup(rows)[self.KEY]
        self.assertEqual(board["observed_utc"], "2026-08-31T23:00:00Z")
        self.assertTrue(all(q["home_price"] == -110 for q in board["quotes"]))

    def test_a_started_game_keeps_its_board_rather_than_vanishing(self):
        """Dropping the game entirely would read as 'nothing was captured'."""
        rows = (self.rows("2026-08-31T23:00:00Z")
                + self.rows("2026-09-01T01:00:00Z", home=-10000, away=900))
        self.assertIn(self.KEY, prices.boards_by_matchup(rows))

    def test_a_row_at_first_pitch_is_not_pregame(self):
        board = prices.boards_by_matchup(
            self.rows("2026-08-31T23:00:00Z")
            + self.rows(self.COMMENCE, books=3))[self.KEY]
        self.assertEqual(board["observed_utc"], "2026-08-31T23:00:00Z")
        self.assertEqual(len(board["quotes"]), 6)

    def test_only_in_play_rows_means_no_board_at_all(self):
        self.assertEqual(
            prices.boards_by_matchup(self.rows("2026-09-01T01:00:00Z")), {})

    def test_price_improvement_for_one_game_ignores_in_play_quotes(self):
        rows = (self.rows("2026-08-31T23:00:00Z")
                + self.rows("2026-08-31T23:47:00Z", home=-10000, away=900))
        result = prices.for_game(away_team="Cincinnati Reds",
                                 home_team="New York Mets", rows=rows)
        self.assertEqual(result["observed_utc"], "2026-08-31T23:00:00Z")

    def test_the_summary_index_inherits_the_pregame_board(self):
        rows = (self.rows("2026-08-31T23:00:00Z")
                + self.rows("2026-08-31T23:47:00Z", home=-10000, away=900))
        self.assertEqual(prices.by_matchup(rows)[self.KEY]["observed_utc"],
                         "2026-08-31T23:00:00Z")
