"""Tests for src/model/selections.py.

TestTheLabel is the important one. The results store is a CSV, so the home-win
label arrives as the STRING "0" or "1" -- and bool("0") is True. Coercing with
bool() made every selection's outcome read as "did we pick the home side", which
produced a 9.6-point apparent edge on a detector that mostly picks home teams.
Nothing raised, every number was plausible, and the entire first discovery run
was wrong.
"""

import unittest

from src.detect import base, detectors
from src.model import pointintime as pit
from src.model import selections


class TestTheLabel(unittest.TestCase):

    def test_the_string_zero_is_a_loss_not_a_win(self):
        # The whole bug in one line.
        self.assertEqual(selections._label("0"), 0)
        self.assertTrue(bool("0"))

    def test_string_and_integer_labels_agree(self):
        for text, number in (("0", 0), ("1", 1)):
            self.assertEqual(selections._label(text), selections._label(number))

    def test_booleans_are_accepted(self):
        self.assertEqual(selections._label(True), 1)
        self.assertEqual(selections._label(False), 0)

    def test_unrecognisable_values_are_none_rather_than_guessed(self):
        # A game that cannot be scored must be counted unresolved, never
        # silently assigned an outcome.
        for value in (None, "", "x", 2, -1, "maybe"):
            self.assertIsNone(selections._label(value), repr(value))

    def test_a_losing_home_pick_is_a_loss(self):
        # The end-to-end statement the bug violated.
        home_won = selections._label("0")
        self.assertFalse(bool(home_won))
        self.assertTrue(not home_won)


class TestCleanDetectorsOnly(unittest.TestCase):

    def setUp(self):
        self._saved = base.registry()
        base.clear_registry()
        detectors.register_defaults()

    def tearDown(self):
        base.clear_registry()
        for detector in self._saved.values():
            base.register(detector)

    def test_leaky_detectors_are_excluded(self):
        chosen = {d.name for d in selections.clean_detectors(base.registry())}
        for name in ("platoon_mismatch", "pitch_mix_mismatch",
                     "thin_matchup_history", "lineup_vs_starter"):
            self.assertNotIn(name, chosen)

    def test_clean_detectors_are_included(self):
        chosen = {d.name for d in selections.clean_detectors(base.registry())}
        self.assertIn("starter_mismatch", chosen)
        self.assertIn("travel_load", chosen)

    def test_the_whitelist_excludes_leaky_sections_by_construction(self):
        # It is not enough for the detector to be clean if the dossier hands it
        # a leaky section anyway.
        for name in ("splits", "arsenals", "matchup_history"):
            self.assertNotIn(name, selections.HISTORICAL_SECTIONS)
            self.assertEqual(pit.input_status(name)["status"], pit.LEAKY)


class TestConsensusPricing(unittest.TestCase):

    def books(self, *pairs):
        return [{"key": f"b{i}", "markets": [{"key": "h2h", "outcomes": [
            {"name": "AWAY", "price": away}, {"name": "HOME", "price": home}]}]}
            for i, (away, home) in enumerate(pairs)]

    def test_fair_probabilities_are_devigged_and_sum_to_one(self):
        fair = selections._fair(self.books((150, -170)), "HOME", "AWAY")
        self.assertAlmostEqual(fair["away_fair"] + fair["home_fair"], 1.0, places=6)

    def test_the_consensus_averages_across_books(self):
        # One book's number is that book's opinion plus its margin. A base-rate
        # control measured against a single quote moves with whichever book
        # happened to be listed first.
        fair = selections._fair(self.books((150, -170), (160, -180)),
                                "HOME", "AWAY")
        self.assertEqual(fair["books"], 2)

    def test_the_best_price_per_side_is_kept_not_the_average(self):
        # A bet gets the best available number, not the mean of the board.
        fair = selections._fair(self.books((150, -170), (160, -160)),
                                "HOME", "AWAY")
        self.assertEqual(fair["away_price"], 160)
        self.assertEqual(fair["home_price"], -160)

    def test_every_quote_is_kept_for_the_stale_book_detector(self):
        # Handing it a single consensus number silently produced zero
        # selections on the first run.
        fair = selections._fair(self.books((150, -170), (160, -180)),
                                "HOME", "AWAY")
        self.assertEqual(len(fair["quotes"]), 2)

    def test_an_unquotable_market_is_none_rather_than_a_default(self):
        self.assertIsNone(selections._fair([], "HOME", "AWAY"))

    def test_a_book_missing_one_side_is_skipped(self):
        books = [{"key": "b", "markets": [{"key": "h2h", "outcomes": [
            {"name": "AWAY", "price": 150}]}]}]
        self.assertIsNone(selections._fair(books, "HOME", "AWAY"))


def _event(commence, away_price, home_price):
    """One backfill.price_pair entry with a single book quoting both sides."""
    books = [{"key": "bk", "markets": [{"key": "h2h", "outcomes": [
        {"name": "New York Mets", "price": away_price},
        {"name": "Miami Marlins", "price": home_price}]}]}]
    quote = {"snapshot_at": commence, "gap_minutes": 400.0, "bookmakers": books}
    return {"event_id": commence, "commence_time": commence,
            "away_team": "New York Mets", "home_team": "Miami Marlins",
            "open": quote, "close": quote, "distinct": True}


class _AlwaysAway:
    """Stub detector: picks the away side of every game it is shown."""
    name = "always_away"

    def safe_run(self, dossier):
        class Finding:
            detector, side, surprise = "always_away", base.AWAY, 1.0
        return [Finding()]


class TestSeriesCollision(unittest.TestCase):
    """Consecutive games between the same clubs share an (away, home, date) key.

    Each event is indexed under its UTC date and the day before, so in any
    normal series the game on date D and the game on D+1 both claim key D. A
    plain assignment let the second overwrite the first, and 55% of matched
    2023 games were then priced from -- and graded against -- the NEXT game's
    odds. The key cannot break the tie; the game's own start time can.
    """

    def pairs(self):
        return selections.index_price_pairs({
            "e1": _event("2023-03-30T20:10:00Z", 130, -150),
            "e2": _event("2023-03-31T22:40:00Z", 200, -240)})

    def game(self, pk, date, start):
        return {"game_pk": pk, "date": date, "start_time_utc": start,
                "away_team": "NYM", "home_team": "MIA", "home_won": "1"}

    def test_each_game_is_priced_from_its_own_event(self):
        result = selections.build(
            [self.game("1", "2023-03-30", "2023-03-30T20:10:00Z"),
             self.game("2", "2023-03-31", "2023-03-31T22:40:00Z")],
            {}, None, self.pairs(), detectors=[_AlwaysAway()])
        prices = {s["game_pk"]: s["price"] for s in result["selections"]}
        # Before the fix the first game silently took the second game's odds.
        self.assertEqual(prices, {"1": 130, "2": 200})

    def test_a_late_start_still_resolves_across_the_date_line(self):
        # The reason both dates are indexed at all: a west-coast night game's
        # UTC first pitch lands on the day after its official date.
        pairs = selections.index_price_pairs(
            {"e1": _event("2023-06-10T02:10:00Z", 120, -140)})
        pair = selections._resolve_pair(
            pairs[("NYM", "MIA", "2023-06-09")],
            self.game("1", "2023-06-09", "2023-06-10T02:10:00Z"))
        self.assertEqual(pair["commence_time"], "2023-06-10T02:10:00Z")

    def test_a_lone_neighbouring_event_is_not_a_match(self):
        # When a game's own event is missing from the odds archive, the only
        # candidate on its key is another game's market. Unpriced is correct;
        # priced from a different game is corruption.
        pair = selections._resolve_pair(
            [_event("2023-03-31T22:40:00Z", 200, -240)],
            self.game("1", "2023-03-30", "2023-03-30T20:10:00Z"))
        self.assertIsNone(pair)

    def test_no_start_time_and_two_candidates_stays_unpriced(self):
        # The tie cannot be broken honestly without a start time; a guess would
        # be right half the time and invisible all the time.
        game = self.game("1", "2023-03-30", None)
        candidates = self.pairs()[("NYM", "MIA", "2023-03-30")]
        self.assertEqual(len(candidates), 2)
        self.assertIsNone(selections._resolve_pair(candidates, game))


class TestAbbreviationJoin(unittest.TestCase):
    """The results store and the odds feed spell two franchises differently.

    The store keeps the MLB Stats API abbreviations -- AZ for Arizona, and ATH
    for the Athletics from 2025 -- while index_price_pairs keys are resolved
    from odds-feed club names, which land on ARI/OAK. Joined raw, the .get()
    in build() returns None and every game those clubs play is skipped as
    "unpriced" with nothing raised: 324 of 324 Diamondbacks games across
    2023-24 evaluated to zero matches. Both sides of the join must pass
    through parks.canonical_team, exactly as the live slate.match_events does.
    """

    def _event(self, away_name, home_name):
        books = [{"key": "bk", "markets": [{"key": "h2h", "outcomes": [
            {"name": away_name, "price": 130},
            {"name": home_name, "price": -150}]}]}]
        quote = {"snapshot_at": "2023-05-12T20:10:00Z", "gap_minutes": 400.0,
                 "bookmakers": books}
        return {"event_id": "e1", "commence_time": "2023-05-12T20:10:00Z",
                "away_team": away_name, "home_team": home_name,
                "open": quote, "close": quote, "distinct": True}

    def _build(self, away_abbrev, home_abbrev, away_name, home_name):
        pairs = selections.index_price_pairs(
            {"e1": self._event(away_name, home_name)})
        game = {"game_pk": "1", "date": "2023-05-12",
                "start_time_utc": "2023-05-12T20:10:00Z",
                "away_team": away_abbrev, "home_team": home_abbrev,
                "home_won": "1"}
        return selections.build([game], {}, None, pairs,
                                detectors=[_AlwaysAway()])

    def test_a_store_az_game_matches_odds_keyed_ari(self):
        result = self._build("AZ", "SF", "Arizona Diamondbacks",
                             "San Francisco Giants")
        self.assertEqual(result["counts"]["games_priced"], 1)
        self.assertEqual(len(result["selections"]), 1)

    def test_a_store_ath_game_matches_odds_keyed_oak(self):
        # The 2025+ store spelling for the Athletics.
        result = self._build("ATH", "SEA", "Athletics", "Seattle Mariners")
        self.assertEqual(result["counts"]["games_priced"], 1)

    def test_matching_spellings_still_match(self):
        result = self._build("NYM", "MIA", "New York Mets", "Miami Marlins")
        self.assertEqual(result["counts"]["games_priced"], 1)


class TestDateIndexing(unittest.TestCase):

    def test_both_candidate_dates_are_indexed_for_a_late_start(self):
        # A west-coast night game's UTC date is the day after its official date,
        # and guessing one would drop those games from every evaluation.
        dates = selections._candidate_dates("2026-08-29T02:10:00Z")
        self.assertIn("2026-08-29", dates)
        self.assertIn("2026-08-28", dates)

    def test_an_unparseable_time_yields_no_dates(self):
        self.assertEqual(selections._candidate_dates("not a time"), [])


if __name__ == "__main__":
    unittest.main()
