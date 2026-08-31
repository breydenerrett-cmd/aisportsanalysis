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
