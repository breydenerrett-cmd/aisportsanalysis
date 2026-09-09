"""tests for stand-down telemetry: why a game has no pick.

On 2026-09-09 the product produced no picks all day and the only way to learn
why was to pull a scheduled CI run's log and grep it. The answer -- 224
NO_LINEUP, 12 NO_SIGNAL, 4 MARKET_UNAVAILABLE across 16 systems and 15 games --
was a fact the product should have been able to state about itself.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.engine import slate as slate_mod
from src.engine.analyze import Analysis, StandDown


class _Outcome:
    def __init__(self, game_key, stand_downs):
        self.game_key = game_key
        self.stand_downs = stand_downs


def _sd(system_id, reason, game_pk="1", t="2026-09-09T15:00:00+00:00"):
    return StandDown(system_id=system_id, reason=reason, game_pk=game_pk, t=t)


class StandDownLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "stand_downs.jsonl")
        patcher = mock.patch.object(slate_mod, "STAND_DOWNS_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _rows(self):
        p = Path(self.path)
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
                if l.strip()]

    def test_a_stand_down_is_recorded_with_its_reason(self):
        n = slate_mod.record_stand_downs(
            "2026-09-09", [_Outcome("AZ@KC", (_sd("g1", "NO_LINEUP"),))])
        self.assertEqual(n, 1)
        row = self._rows()[0]
        self.assertEqual(row["reason"], "NO_LINEUP")
        self.assertEqual(row["system_id"], "g1")
        self.assertEqual(row["game_key"], "AZ@KC")

    def test_the_same_refusal_at_a_later_pass_is_not_written_twice(self):
        """A genome refusing NO_LINEUP at every pass has said one thing, not
        sixteen. Writing a row per pass would put thousands of rows a day here
        and bury the only interesting event: a reason CHANGING."""
        out = [_Outcome("AZ@KC", (_sd("g1", "NO_LINEUP"),))]
        self.assertEqual(slate_mod.record_stand_downs("2026-09-09", out), 1)
        self.assertEqual(slate_mod.record_stand_downs("2026-09-09", out), 0)
        self.assertEqual(len(self._rows()), 1)

    def test_a_changed_reason_is_a_new_row(self):
        """NO_LINEUP -> NO_SIGNAL means the lineup posted and the genome then
        had nothing to say. That transition is the point of this ledger."""
        slate_mod.record_stand_downs(
            "2026-09-09", [_Outcome("AZ@KC", (_sd("g1", "NO_LINEUP"),))])
        n = slate_mod.record_stand_downs(
            "2026-09-09", [_Outcome("AZ@KC", (_sd("g1", "NO_SIGNAL"),))])
        self.assertEqual(n, 1)
        self.assertEqual([r["reason"] for r in self._rows()],
                         ["NO_LINEUP", "NO_SIGNAL"])

    def test_the_same_reason_on_another_game_is_its_own_row(self):
        n = slate_mod.record_stand_downs("2026-09-09", [
            _Outcome("AZ@KC", (_sd("g1", "NO_LINEUP"),)),
            _Outcome("CLE@BAL", (_sd("g1", "NO_LINEUP"),)),
        ])
        self.assertEqual(n, 2)

    def test_a_new_date_is_a_new_row(self):
        out = [_Outcome("AZ@KC", (_sd("g1", "NO_LINEUP"),))]
        slate_mod.record_stand_downs("2026-09-09", out)
        self.assertEqual(slate_mod.record_stand_downs("2026-09-10", out), 1)

    def test_nothing_to_record_writes_no_file(self):
        self.assertEqual(slate_mod.record_stand_downs("2026-09-09", []), 0)
        self.assertEqual(self._rows(), [])

    def test_a_broken_ledger_never_costs_a_decision(self):
        """Telemetry must never take the run down. A frozen decision and a
        staked wager are what this run exists to produce."""
        with mock.patch.object(slate_mod, "HashChainLedger",
                               side_effect=OSError("disk full")):
            n = slate_mod.record_stand_downs(
                "2026-09-09", [_Outcome("AZ@KC", (_sd("g1", "NO_LINEUP"),))])
        self.assertEqual(n, 0)

    def test_the_key_excludes_the_instant(self):
        a = slate_mod.stand_down_key("2026-09-09", "AZ@KC", "g1", "NO_LINEUP")
        b = slate_mod.stand_down_key("2026-09-09", "AZ@KC", "g1", "NO_LINEUP")
        self.assertEqual(a, b)
        self.assertNotEqual(
            a, slate_mod.stand_down_key("2026-09-09", "AZ@KC", "g1",
                                        "NO_SIGNAL"))


class AnalysisCarriesStandDownsTests(unittest.TestCase):
    def test_analysis_defaults_to_no_stand_downs(self):
        a = Analysis(game_pk="1", t="2026-09-09T15:00:00+00:00")
        self.assertEqual(a.stand_downs, ())

    def test_a_stand_down_is_not_a_decision_record(self):
        """It has no market, no selection and no price. Folding it into the
        decisions ledger would inflate every count computed off that file."""
        sd = _sd("g1", "NO_LINEUP")
        self.assertFalse(hasattr(sd, "market_key"))
        self.assertFalse(hasattr(sd, "selection_id"))
        self.assertFalse(hasattr(sd, "price_american"))

    def test_it_serialises_for_the_ledger(self):
        json.dumps(_sd("g1", "NO_LINEUP").to_dict())


if __name__ == "__main__":
    unittest.main()
