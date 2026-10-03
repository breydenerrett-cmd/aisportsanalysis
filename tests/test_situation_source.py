"""`source.mlb_situation_provider`: how arm B and the game page get a game's situation record.

The stores are injected or patched, so no test reads the repo's data. What is pinned here is the one
decision the provider makes that the builder cannot: which days the ingest manifest CONFIRMS. A date
fetched while a game was still pending is in the manifest but is not a confirmed day, because the game
that was pending is not in the results store (`history.unfinished_dates` says why), so it must not
count as covered.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.analyst import source
from src.pipeline import history
from src.situation import postseason_history as ph
from tests import situation_fixtures as SF


def item(game):
    return {"payload": {"advanced": {"game": game}}}


class _Empty:
    games, season_records = [], {}


def record_with(manifest, game=None, **kw):
    """The provider's record for Division Series game 1 (2025-10-04); the world's newest game before it
    is 2025-10-02, so 2025-10-03 is the one day the manifest has to speak for."""
    kw.setdefault("history_loader", lambda: _Empty())
    with mock.patch.object(history, "read_manifest", return_value=manifest):
        provider = source.mlb_situation_provider(results=SF.world(), **kw)
        return provider(item(game or SF.division_game(1)))


class TheManifestDecidesWhichDaysAreConfirmed(unittest.TestCase):
    def test_a_day_the_manifest_confirms_makes_the_store_current(self):
        r = record_with({"2025-10-03": {"final": 0, "pending": 0, "total": 0}})
        self.assertTrue(r["coverage"]["results_current"])
        self.assertTrue(any(f["name"] == "series_state" for f in r["factors"]))

    def test_a_day_fetched_while_a_game_was_pending_is_not_confirmed(self):
        r = record_with({"2025-10-03": {"final": 3, "pending": 2, "total": 5}})
        self.assertFalse(r["coverage"]["results_current"])
        self.assertFalse(any(f["name"] == "series_state" for f in r["factors"]))
        reason = next(g["reason"] for g in r["missing"] if g["name"] == "results_store_current")
        self.assertIn("2025-10-03", reason)

    def test_a_day_the_manifest_never_fetched_is_not_confirmed(self):
        r = record_with({"2025-09-30": {"pending": 0}})
        self.assertFalse(r["coverage"]["results_current"])

    def test_an_empty_manifest_confirms_nothing(self):
        self.assertFalse(record_with({})["coverage"]["results_current"])

    def test_explicit_covered_dates_are_used_without_reading_the_manifest(self):
        provider = source.mlb_situation_provider(results=SF.world(), covered_dates=["2025-10-03"],
                                                 history_loader=lambda: _Empty())
        with mock.patch.object(history, "read_manifest", side_effect=AssertionError("read the manifest")):
            self.assertTrue(provider(item(SF.division_game(1)))["coverage"]["results_current"])


class TheStoresAreReadOnce(unittest.TestCase):
    def test_a_provider_reads_the_results_store_and_the_history_once_for_many_games(self):
        reads, loads = [], []

        def read_results():
            reads.append(1)
            return {r["game_pk"]: r for r in SF.world()}

        def load_history():
            loads.append(1)
            return _Empty()
        with mock.patch.object(history, "read_results", side_effect=read_results), \
                mock.patch.object(history, "read_manifest", return_value={"2025-10-03": {"pending": 0}}):
            provider = source.mlb_situation_provider(history_loader=load_history)
            for n in (1, 2, 3):
                provider(item(SF.division_game(n)))
        self.assertEqual((len(reads), len(loads)), (1, 1))

    def test_the_default_history_is_the_display_only_store_and_a_missing_one_is_empty(self):
        with mock.patch.object(ph, "load", return_value=ph.History()) as load, \
                mock.patch.object(history, "read_manifest", return_value={"2025-10-03": {"pending": 0}}):
            provider = source.mlb_situation_provider(results=SF.world())
            r = provider(item(SF.division_game(1)))
        load.assert_called_once()
        self.assertTrue(r["factors"])

    def test_the_older_postseasons_extend_what_can_be_said_about_a_drought(self):
        older = [SF.g(9001, "2019-10-04", "TB", "HOU", 4, 1, "D"), SF.g(9002, "2019-10-05", "TB", "HOU", 2, 6, "D"),
                 SF.g(9003, "2019-10-07", "HOU", "TB", 3, 1, "D"), SF.g(9004, "2019-10-08", "HOU", "TB", 1, 4, "D"),
                 SF.g(9005, "2019-10-10", "TB", "HOU", 4, 6, "D")]

        class History:
            games, season_records = older, {(2019, "TB"): {"wins": 96, "losses": 66}}
        r = record_with({"2025-10-03": {"pending": 0}}, history_loader=lambda: History())
        wins = next(f for f in r["factors"] if f["name"] == "series_wins_in_data" and f["side"] == "away")
        self.assertEqual(wins["detail"]["first_season_in_data"], 2019)
        self.assertIn("2019 on", wins["sentence"])


class TheGameIsReadFromTheItem(unittest.TestCase):
    def test_a_game_the_item_does_not_carry_is_an_error_the_caller_turns_into_a_skip(self):
        provider = source.mlb_situation_provider(results=SF.world(), covered_dates=[], history_loader=lambda: _Empty())
        with self.assertRaises(ValueError):
            provider({"payload": {"advanced": {}}})          # no game, no date: nothing can be drawn


if __name__ == "__main__":
    unittest.main()
