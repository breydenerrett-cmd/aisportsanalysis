"""Regression test for the settlement-closing join (see docs handoff, 2026-09-02).

THE BUG: every recent forward-ledger settlement carried closing=null,
closing_reason="no snapshots recorded for this game" even though
data/processed/odds_snapshots.jsonl held thousands of rows for those exact
games. Root cause: `cli._settlement_closing` builds
`snapshots.game_key(rec["away_team"], rec["home_team"], rec["commence_time"])`
from LEDGER rows, whose team fields are this project's abbreviations
('STL', 'LAD'), while `snapshots.group_by_game` keyed the snapshot store's
rows by the odds feed's OWN full club names ('St. Louis Cardinals').
`game_key` did no canonicalization, so the two literal strings never
compared equal and the lookup missed on every single game -- not because a
close was absent, but because the join itself was broken.

These tests exercise the real pipeline (snapshots.group_by_game -- not a
hand-built dict standing in for it -- feeding cli._settlement_closing), the
way `cmd_settle` actually calls it, so a regression here means production
settlement is broken again, not just one function's unit contract.
"""

import unittest

from src import cli
from src.pipeline import snapshots


def snapshot_row(observed, away="St. Louis Cardinals", home="Los Angeles Dodgers",
                 commence="2026-08-27T23:10:00Z", home_price=-150, away_price=130):
    """One h2h snapshot row, shaped exactly like `snapshots.capture` writes it:
    the odds feed's full club names, not this project's abbreviations."""
    return {
        "observed_utc": observed, "commence_time": commence,
        "away_team": away, "home_team": home, "market": "h2h",
        "book": "fanduel", "book_last_update": observed,
        "prices": {"home_price": home_price, "away_price": away_price},
    }


def ledger_rec(away="STL", home="LAD", commence="2026-08-27T23:10:00Z"):
    """One ledger recommendation row, shaped the way `ledger.record_slate`
    actually writes it: this project's team abbreviations, not club names."""
    return {"away_team": away, "home_team": home, "commence_time": commence}


class TestAbbreviationVsFullNameJoin(unittest.TestCase):
    """The exact mismatch that was silently failing every join."""

    def test_ledger_abbreviations_join_a_store_keyed_by_full_names(self):
        rows = [snapshot_row("2026-08-27T22:00:00+00:00")]
        series = snapshots.group_by_game(rows)

        closing, reason = cli._settlement_closing(ledger_rec(), series)

        self.assertIsNone(reason)
        self.assertIsNotNone(closing, "the join must find the series that "
                              "IS there, not report it as absent")
        self.assertEqual(closing["prices"]["home_price"], -150)
        self.assertEqual(closing["book"], "fanduel")

    def test_an_alias_spelling_still_joins(self):
        # Arizona's odds-feed name resolves to ARI; the ledger sometimes
        # carries the older "AZ" spelling. Both must land on the same key.
        rows = [snapshot_row("2026-08-27T22:00:00+00:00",
                             away="Arizona Diamondbacks",
                             home="San Francisco Giants")]
        series = snapshots.group_by_game(rows)

        closing, reason = cli._settlement_closing(
            ledger_rec(away="AZ", home="SF"), series)

        self.assertIsNone(reason)
        self.assertIsNotNone(closing)

    def test_a_different_official_date_stays_unmatched(self):
        # This module's whole promise: a missing close stays missing. A
        # canonicalization fix must not paper over a genuine date mismatch --
        # only the team-name shape mismatch was ever the bug.
        rows = [snapshot_row("2026-08-20T22:00:00+00:00",
                             commence="2026-08-20T23:10:00Z")]
        series = snapshots.group_by_game(rows)

        closing, reason = cli._settlement_closing(
            ledger_rec(commence="2026-08-27T23:10:00Z"), series)

        self.assertIsNone(closing)
        self.assertEqual(reason, "no snapshots recorded for this game")

    def test_an_unresolvable_club_name_stays_unmatched_not_mismatched(self):
        # A name neither resolver recognizes must never silently collide with
        # a different unresolvable name -- see snapshots._canonical_club.
        rows = [snapshot_row("2026-08-27T22:00:00+00:00",
                             away="Some Expansion Team", home="Los Angeles Dodgers")]
        series = snapshots.group_by_game(rows)

        closing, reason = cli._settlement_closing(
            ledger_rec(away="Another Unknown Club"), series)

        self.assertIsNone(closing)
        self.assertEqual(reason, "no snapshots recorded for this game")


class TestGameKeyCanonicalization(unittest.TestCase):
    """Direct unit coverage of the join key itself, isolated from cli."""

    def test_full_name_and_abbreviation_produce_the_same_key(self):
        self.assertEqual(
            snapshots.game_key("St. Louis Cardinals", "Los Angeles Dodgers",
                               "2026-08-27T23:10:00Z"),
            snapshots.game_key("STL", "LAD", "2026-08-27T23:10:00Z"))

    def test_alias_abbreviations_canonicalize_to_the_same_key(self):
        self.assertEqual(
            snapshots.game_key("Arizona Diamondbacks", "San Francisco Giants",
                               "2026-08-27T23:10:00Z"),
            snapshots.game_key("AZ", "SF", "2026-08-27T23:10:00Z"))

    def test_the_official_date_component_is_unaffected(self):
        # Boundary: only the team-name canonicalization changed; the
        # Eastern-date identity logic this module depends on did not.
        key = snapshots.game_key("STL", "LAD", "2026-08-27T23:10:00Z")
        self.assertEqual(key[2], "2026-08-27")

    def test_two_different_unrecognized_names_stay_distinguishable(self):
        # A canonicalizer that folded every unrecognized name onto the same
        # sentinel (e.g. None) would silently merge two unrelated games.
        key_a = snapshots.game_key("Some Expansion Team", "Los Angeles Dodgers",
                                   "2026-08-27T23:10:00Z")
        key_b = snapshots.game_key("A Different Unknown Club", "Los Angeles Dodgers",
                                   "2026-08-27T23:10:00Z")
        self.assertNotEqual(key_a, key_b)


if __name__ == "__main__":
    unittest.main()
