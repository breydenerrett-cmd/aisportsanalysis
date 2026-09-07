"""Tests for src.report.engine_bridge (Task B2).

Covers: `system_class` prefix rules, `event_index` built from a small
multi-book fixture, `decisions_for_date`'s join (event_id -> game key,
wager side override, thesis shown only for FORWARD_TEST), `summarize_game`'s
rollup, and missing-file tolerance for every public function.

Decision fixtures are plain dicts rather than real `DecisionRecord`
instances -- `engine_bridge._field` reads either a dict or an attribute-
bearing object, and a dict fixture only needs to carry the handful of keys
`decisions_for_date` actually reads, not every required `DecisionRecord`
field.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.report import engine_bridge as eb


def _mb_row(event_id, away_team, home_team, commence_time):
    return {
        "event_id": event_id, "away_team": away_team, "home_team": home_team,
        "commence_time": commence_time, "book": "fanduel",
        "home_price": -120, "away_price": 110,
        "observed_utc": "2026-09-07T10:00:00Z",
    }


class SystemClassTests(unittest.TestCase):
    def test_trivial_prefix_is_control(self):
        self.assertEqual(eb.system_class("trivial_always_home_spread"), eb.CONTROL)

    def test_market_derived_prefix_is_market_reference(self):
        self.assertEqual(
            eb.system_class("market_derived_consensus_h2h_home"),
            eb.MARKET_REFERENCE)

    def test_hex_id_is_forward_test(self):
        self.assertEqual(eb.system_class("a1b2c3d4e5f60718"), eb.FORWARD_TEST)

    def test_missing_id_is_forward_test(self):
        self.assertEqual(eb.system_class(None), eb.FORWARD_TEST)
        self.assertEqual(eb.system_class(""), eb.FORWARD_TEST)


class EventIndexTests(unittest.TestCase):
    def test_builds_abbrev_and_date_from_multibook_rows(self):
        rows = [
            _mb_row("ev1", "Boston Red Sox", "New York Yankees",
                   "2026-09-07T23:05:00Z"),
            _mb_row("ev2", "Los Angeles Dodgers", "San Francisco Giants",
                   "2026-09-08T02:10:00Z"),
            # Duplicate event_id (a second book's row for ev1) must not
            # overwrite the first-seen entry.
            _mb_row("ev1", "Boston Red Sox", "New York Yankees",
                   "2026-09-07T23:05:00Z"),
        ]
        idx = eb.event_index(rows=rows)
        self.assertEqual(len(idx), 2)
        self.assertEqual(idx["ev1"]["away_abbrev"], "BOS")
        self.assertEqual(idx["ev1"]["home_abbrev"], "NYY")
        self.assertEqual(idx["ev1"]["date"], "2026-09-07")
        self.assertEqual(idx["ev1"]["away_name"], "Boston Red Sox")

    def test_empty_rows_is_empty_index(self):
        self.assertEqual(eb.event_index(rows=[]), {})

    def test_tolerates_a_broken_reader(self):
        with patch("src.pipeline.snapshots.read_multibook",
                  side_effect=OSError("no such file")):
            self.assertEqual(eb.event_index(), {})


class DecisionsForDateTests(unittest.TestCase):
    FIXTURE_INDEX = {
        "ev1": {"away_abbrev": "BOS", "home_abbrev": "NYY",
                "away_name": "Boston Red Sox", "home_name": "New York Yankees",
                "commence_time": "2026-09-07T23:05:00Z", "date": "2026-09-07"},
        "ev2": {"away_abbrev": "LAD", "home_abbrev": "SF",
                "away_name": "Los Angeles Dodgers", "home_name": "San Francisco Giants",
                "commence_time": "2026-09-08T02:10:00Z", "date": "2026-09-08"},
    }

    def _decisions(self):
        return [
            {  # CONTROL, no wager -> not staked, thesis withheld
                "system_id": "trivial_always_home_spread", "event_id": "ev1",
                "verdict": "play", "market_key": "spreads",
                "selection_id": "home", "line": "-1.5",
                "price_american": -110, "consensus_fair": 0.5,
                "books_at_decision": 9, "p_model_provenance": "placeholder",
                "known_at_grade": "A", "counterarguments": [],
                "thesis": "should never surface", "decision_utc": "2026-09-07T09:00:00Z",
            },
            {  # FORWARD_TEST, staked via a matching wager row, thesis shown
                "system_id": "a1b2c3d4e5f60718", "event_id": "ev1",
                "verdict": "play", "market_key": "h2h",
                "selection_id": "sel-away", "line": None,
                "price_american": 130, "consensus_fair": 0.44,
                "books_at_decision": 9, "p_model_provenance": "none",
                "known_at_grade": "B", "counterarguments": [
                    {"adversary_id": "x", "cause": "y", "severity": "FATAL",
                     "detail": "z"},
                ],
                "thesis": "a forward-test thesis", "decision_utc": "2026-09-07T09:05:00Z",
            },
            {  # a decision on a different date's event -- must not join here
                "system_id": "market_derived_consensus_h2h_away", "event_id": "ev2",
                "verdict": "play", "market_key": "h2h",
                "selection_id": "away", "line": None,
                "price_american": 150, "consensus_fair": 0.4,
                "books_at_decision": 8, "p_model_provenance": "market_derived",
                "known_at_grade": "A", "counterarguments": [],
                "thesis": None, "decision_utc": "2026-09-08T09:00:00Z",
            },
        ]

    def _wagers(self):
        return [
            {"event_id": "ev1", "system_id": "a1b2c3d4e5f60718",
            "side": "away", "date": "2026-09-07"},
        ]

    def test_joins_by_event_and_filters_to_the_requested_date(self):
        with patch.object(eb, "event_index", return_value=self.FIXTURE_INDEX):
            result = eb.decisions_for_date(
                "2026-09-07", decisions=self._decisions(), wagers=self._wagers())
        self.assertEqual(list(result.keys()), [("BOS", "NYY", "2026-09-07")])
        summaries = result[("BOS", "NYY", "2026-09-07")]
        self.assertEqual(len(summaries), 2)

    def test_schedule_spelling_finds_the_feeds_spelling_of_a_club(self):
        """Regression, 2026-09-07: the odds feed's 'Athletics' resolves to
        OAK, the MLB schedule says ATH, and TOR@ATH came back with no engine
        decisions while every other game joined. Both sides of the join go
        through engine_bridge.game_key, which canonicalises."""
        index = {"ev9": {"away_abbrev": "TOR", "home_abbrev": "OAK",
                         "away_name": "Toronto Blue Jays", "home_name": "Athletics",
                         "commence_time": "2026-09-08T02:05:00Z", "date": "2026-09-07"}}
        decision = dict(self._decisions()[0], event_id="ev9")
        with patch.object(eb, "event_index", return_value=index):
            result = eb.decisions_for_date("2026-09-07", decisions=[decision], wagers=[])
        self.assertEqual(list(result.keys()), [eb.game_key("TOR", "ATH", "2026-09-07")])
        self.assertEqual(list(result.keys()), [("TOR", "OAK", "2026-09-07")])
        self.assertEqual(eb.game_key("TOR", "ATH", "2026-09-07"),
                         eb.game_key("tor", "OAK", "2026-09-07"))
        self.assertEqual(eb.game_key("AZ", "KC", "2026-09-07"), ("ARI", "KC", "2026-09-07"))
        self.assertEqual(eb.game_key("ZZZ", None, "2026-09-07"), ("ZZZ", "", "2026-09-07"))

    def test_control_never_carries_a_thesis_and_is_not_staked(self):
        with patch.object(eb, "event_index", return_value=self.FIXTURE_INDEX):
            result = eb.decisions_for_date(
                "2026-09-07", decisions=self._decisions(), wagers=self._wagers())
        control = next(s for s in result[("BOS", "NYY", "2026-09-07")]
                       if s["system_class"] == eb.CONTROL)
        self.assertIsNone(control["thesis"])
        self.assertFalse(control["staked"])
        self.assertEqual(control["side_or_selection"], "home")

    def test_forward_test_carries_thesis_and_wager_side_wins_over_selection(self):
        with patch.object(eb, "event_index", return_value=self.FIXTURE_INDEX):
            result = eb.decisions_for_date(
                "2026-09-07", decisions=self._decisions(), wagers=self._wagers())
        ft = next(s for s in result[("BOS", "NYY", "2026-09-07")]
                 if s["system_class"] == eb.FORWARD_TEST)
        self.assertEqual(ft["thesis"], "a forward-test thesis")
        self.assertTrue(ft["staked"])
        # the wager row's side ("away") overrides the raw selection_id
        self.assertEqual(ft["side_or_selection"], "away")
        self.assertEqual(ft["counterarguments"],
                         [{"severity": "FATAL", "cause": "y", "detail": "z"}])

    def test_missing_stores_return_empty_without_raising(self):
        with patch.object(eb, "load_decisions", side_effect=OSError("no ledger")), \
             patch.object(eb, "wagers_for_date", side_effect=OSError("no ledger")), \
             patch.object(eb, "event_index", side_effect=OSError("no store")):
            result = eb.decisions_for_date("2026-09-07")
        self.assertEqual(result, {})

    def test_no_decisions_and_no_wagers_is_an_empty_dict(self):
        with patch.object(eb, "event_index", return_value=self.FIXTURE_INDEX):
            result = eb.decisions_for_date("2026-09-07", decisions=(), wagers=())
        self.assertEqual(result, {})


class SummarizeGameTests(unittest.TestCase):
    def test_rollup_counts_and_forward_test_isolation(self):
        summaries = [
            {"system_class": eb.CONTROL, "verdict": "play", "staked": False,
            "p_model_provenance": "placeholder", "counterarguments": []},
            {"system_class": eb.MARKET_REFERENCE, "verdict": "play", "staked": False,
            "p_model_provenance": "market_derived", "counterarguments": []},
            {"system_class": eb.FORWARD_TEST, "verdict": "play", "staked": True,
            "p_model_provenance": "none",
            "counterarguments": [{"severity": "FATAL", "cause": "c", "detail": "d"}]},
            {"system_class": eb.FORWARD_TEST, "verdict": "no_play", "staked": False,
            "p_model_provenance": "none", "counterarguments": []},
        ]
        out = eb.summarize_game(summaries)
        self.assertEqual(out["n_decisions"], 4)
        self.assertEqual(out["n_play"], 3)
        self.assertEqual(out["n_staked"], 1)
        self.assertEqual(len(out["forward_test_plays"]), 1)
        self.assertTrue(out["market_reference_present"])
        self.assertEqual(len(out["fatal_counterarguments"]), 1)
        self.assertEqual(out["provenance_counts"],
                         {"placeholder": 1, "market_derived": 1, "none": 2})

    def test_empty_summaries_is_a_zeroed_rollup_not_a_crash(self):
        out = eb.summarize_game([])
        self.assertEqual(out["n_decisions"], 0)
        self.assertEqual(out["forward_test_plays"], [])
        self.assertFalse(out["market_reference_present"])


if __name__ == "__main__":
    unittest.main()
