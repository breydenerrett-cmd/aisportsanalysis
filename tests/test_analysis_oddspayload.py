"""src/analysis/oddspayload.py: the Odds-tab payload builders.

stdlib-only, offline, built on fixture board rows shaped exactly like
`prices.latest_instant` output ({ts, book, away_price, home_price}) --
never a live store, never network access.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analysis import oddspayload
from src.analysis import prices as prices_mod
from src.core import odds as odds_math

NOW = datetime(2026, 8, 31, 20, 0, 0, tzinfo=timezone.utc)
TS = "2026-08-31T19:55:00Z"


def _quote(book, away, home, ts=TS):
    return {"ts": ts, "book": book, "away_price": away, "home_price": home}


def _full_board(ts=TS):
    """Seven books -- above prices.MIN_BOOKS (6) -- with a clear best price
    on each side and one deliberate outlier for spread/dispersion checks."""
    return [
        _quote("fanduel", -110, -110, ts),
        _quote("draftkings", -108, -112, ts),
        _quote("betmgm", -105, -115, ts),   # best away price
        _quote("caesars", -112, -108, ts),  # best home price
        _quote("pointsbet", -115, -105, ts),
        _quote("wynn", -120, -100, ts),     # worst away price
        _quote("barstool", -110, -125, ts), # worst home price
    ]


def _thin_board(ts=TS):
    """Three books -- below the MIN_BOOKS floor -- so consensus must refuse
    while raw board/best-price data stays available."""
    return [
        _quote("fanduel", -110, -110, ts),
        _quote("draftkings", -108, -112, ts),
        _quote("betmgm", -105, -115, ts),
    ]


def _game(away="BOS", home="NYY", date_="2026-08-31"):
    return {"away_team": away, "home_team": home, "date": date_,
            "start_time_utc": f"{date_}T23:05:00Z", "venue": "Yankee Stadium"}


class BuildMarketH2hTests(unittest.TestCase):

    def test_no_board_is_an_explicit_unavailable_state(self):
        section = oddspayload.build_market_h2h(None, now=NOW)
        self.assertFalse(section["board_available"])
        self.assertEqual(section["reason"], oddspayload.NO_BOARD_REASON)
        self.assertEqual(section["board"], [])
        self.assertIsNone(section["best"])
        self.assertIsNone(section["consensus"])
        self.assertFalse(section["staleness"]["has_board"])
        self.assertIsNone(section["staleness"]["age_seconds"])

    def test_full_board_reports_board_best_consensus_spread_staleness(self):
        board = {"quotes": _full_board(), "observed_utc": TS}
        section = oddspayload.build_market_h2h(board, now=NOW)

        self.assertTrue(section["board_available"])
        self.assertEqual(len(section["board"]), 7)
        row = section["board"][0]
        self.assertEqual(set(row), {"book", "away_price", "home_price", "captured_at"})

        # Best price highlighting: -105 is the highest away decimal (least
        # negative American price on the favorite side), -100 the highest
        # home decimal.
        self.assertEqual(section["best"]["away"]["price"], -105)
        self.assertIn("betmgm", section["best"]["away"]["books"])
        self.assertEqual(section["best"]["home"]["price"], -100)
        self.assertIn("wynn", section["best"]["home"]["books"])

        # Spread: -105 to -120 away is 15 cents; -100 to -125 home is 25.
        self.assertAlmostEqual(section["spread_cents"]["away"], 15)
        self.assertAlmostEqual(section["spread_cents"]["home"], 25)

        # Staleness.
        self.assertEqual(section["staleness"]["observed_utc"], TS)
        self.assertAlmostEqual(section["staleness"]["age_seconds"], 300.0)
        self.assertTrue(section["staleness"]["has_board"])

    def test_consensus_sums_the_devigged_probabilities_to_one(self):
        board = {"quotes": _full_board(), "observed_utc": TS}
        section = oddspayload.build_market_h2h(board, now=NOW)
        consensus = section["consensus"]
        self.assertIsNotNone(consensus)
        total = (consensus["away"]["implied_probability"]
                 + consensus["home"]["implied_probability"])
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertEqual(consensus["books"], 7)
        # The consensus price is the American price implied by that fair
        # probability -- round-tripping it must reproduce the probability.
        implied = odds_math.american_to_probability(
            consensus["away"]["implied_price"])
        self.assertAlmostEqual(implied, consensus["away"]["implied_probability"],
                               delta=0.01)

    def test_below_book_floor_still_shows_board_and_best_but_no_consensus(self):
        board = {"quotes": _thin_board(), "observed_utc": TS}
        section = oddspayload.build_market_h2h(board, now=NOW)

        self.assertTrue(section["board_available"])
        self.assertEqual(len(section["board"]), 3)
        self.assertIsNotNone(section["best"]["away"])  # best price needs no floor
        self.assertIsNone(section["consensus"])
        self.assertIsNotNone(section["consensus_unavailable_reason"])
        self.assertIn("3 books", section["consensus_unavailable_reason"])

    def test_spread_needs_at_least_two_priced_quotes(self):
        board = {"quotes": [_quote("fanduel", -110, -110)], "observed_utc": TS}
        section = oddspayload.build_market_h2h(board, now=NOW)
        self.assertIsNone(section["spread_cents"]["away"])
        self.assertIsNone(section["spread_cents"]["home"])


class BooksDisagreeOnFavoriteTests(unittest.TestCase):

    def test_unanimous_favorite_is_no_disagreement(self):
        unanimous = [
            _quote("fanduel", -110, +100),
            _quote("draftkings", -108, +102),
            _quote("betmgm", -105, +105),
        ]
        self.assertFalse(oddspayload._books_disagree_on_favorite(unanimous))

    def test_split_favorite_is_flagged(self):
        split = [
            _quote("fanduel", -110, +100),   # away favored
            _quote("draftkings", +100, -110),  # home favored
        ]
        self.assertTrue(oddspayload._books_disagree_on_favorite(split))

    def test_no_priceable_rows_is_none_not_false(self):
        self.assertIsNone(oddspayload._books_disagree_on_favorite([]))


class BuildOddsPayloadTests(unittest.TestCase):

    def test_full_slate_summary_and_per_game_shape(self):
        games = [_game("BOS", "NYY"), _game("SEA", "TEX")]
        boards = {
            prices_mod.matchup_key("BOS", "NYY", "2026-08-31"):
                {"quotes": _full_board(), "observed_utc": TS},
            # SEA/TEX has no board at all.
        }
        payload = oddspayload.build_odds_payload(games, boards, date="2026-08-31",
                                                  now=NOW)
        self.assertEqual(payload["date"], "2026-08-31")
        self.assertEqual(len(payload["games"]), 2)
        self.assertEqual(payload["summary"]["games_count"], 2)

        bos_entry = next(g for g in payload["games"] if g["away_team"] == "BOS")
        self.assertTrue(bos_entry["markets"]["h2h"]["board_available"])
        sea_entry = next(g for g in payload["games"] if g["away_team"] == "SEA")
        self.assertFalse(sea_entry["markets"]["h2h"]["board_available"])

        widest = payload["summary"]["widest_spread_game"]
        self.assertEqual(widest["game_id"], bos_entry["game_id"])
        self.assertEqual(widest["side"], "home")
        self.assertAlmostEqual(widest["spread_cents"], 25)

    def test_empty_slate_is_an_honest_zero_not_an_error(self):
        payload = oddspayload.build_odds_payload([], {}, date="2026-12-25", now=NOW)
        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["summary"]["games_count"], 0)
        self.assertIsNone(payload["summary"]["widest_spread_game"])
        self.assertEqual(payload["summary"]["books_disagree_on_favorite_count"], 0)


class NoBannedVocabularyTests(unittest.TestCase):
    """This module is scanned by tests/test_customer_language.py too; this
    is a narrower, oddspayload-specific pin so a regression here fails next
    to the code that caused it."""

    def test_consensus_field_names_say_implied_not_true(self):
        board = {"quotes": _full_board(), "observed_utc": TS}
        section = oddspayload.build_market_h2h(board, now=NOW)
        consensus = section["consensus"]
        self.assertIn("implied_probability", consensus["away"])
        self.assertIn("implied_price", consensus["away"])
        self.assertNotIn("true_probability", consensus["away"])
        self.assertNotIn("win_probability", consensus["away"])


if __name__ == "__main__":
    unittest.main()
