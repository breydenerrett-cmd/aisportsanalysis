"""tests for src.report.stand_downs: turning "no pick" into a reason."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ledger.chain import HashChainLedger
from src.report import stand_downs as sd

DATE = "2026-09-09"


class _Store:
    def __init__(self, rows):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "stand_downs.jsonl")
        ledger = HashChainLedger(self.path)
        for r in rows:
            ledger.append(r)

    def close(self):
        self.tmp.cleanup()


def _row(game_key, system_id, reason, date=DATE):
    return {"date": date, "game_key": game_key, "system_id": system_id,
            "reason": reason, "game_pk": "1", "first_seen_utc": None}


class SummarizeTests(unittest.TestCase):
    def _summary(self, rows, game_key="AZ@KC"):
        store = _Store(rows)
        self.addCleanup(store.close)
        return sd.summarize_game(DATE, game_key, store.path)

    def test_an_unrecorded_game_is_none_not_an_empty_summary(self):
        """None means the slate may not have reached this game. A summary
        listing zero systems cannot occur -- a row exists only because a
        system actually declined -- so the two must not be conflated."""
        store = _Store([_row("AZ@KC", "g1", "NO_LINEUP")])
        self.addCleanup(store.close)
        self.assertIsNone(sd.summarize_game(DATE, "CLE@BAL", store.path))

    def test_a_missing_ledger_reads_as_not_recorded(self):
        self.assertIsNone(sd.summarize_game(DATE, "AZ@KC", "no/such/file"))

    def test_it_counts_systems_per_reason(self):
        s = self._summary([_row("AZ@KC", f"g{i}", "NO_LINEUP")
                           for i in range(14)]
                          + [_row("AZ@KC", "g14", "NO_SIGNAL")])
        self.assertEqual(s["n_systems"], 15)
        by = {r["reason"]: r["n_systems"] for r in s["reasons"]}
        self.assertEqual(by, {"NO_LINEUP": 14, "NO_SIGNAL": 1})

    def test_no_lineup_is_reported_as_able_to_change(self):
        """A clock, not a verdict. The lineup may post and the systems may
        then decide -- telling a reader to come back is the useful answer."""
        s = self._summary([_row("AZ@KC", "g1", "NO_LINEUP")])
        self.assertTrue(s["may_change_tonight"])
        self.assertIn("can change", s["headline"])

    def test_no_signal_is_reported_as_a_settled_verdict(self):
        """The systems saw the lineup and passed. Telling a reader to come
        back would be false."""
        s = self._summary([_row("AZ@KC", "g1", "NO_SIGNAL")])
        self.assertFalse(s["may_change_tonight"])
        self.assertNotIn("can change", s["headline"])

    def test_the_headline_leads_with_the_reason_covering_most_systems(self):
        s = self._summary([_row("AZ@KC", f"g{i}", "NO_SIGNAL")
                           for i in range(12)]
                          + [_row("AZ@KC", "gx", "NO_LINEUP")])
        self.assertIn("found nothing", s["headline"])
        self.assertFalse(s["may_change_tonight"])

    def test_an_unknown_reason_is_kept_not_dropped(self):
        """A reason this module has not been taught is still a real answer.
        Dropping it would under-report how many systems declined."""
        s = self._summary([_row("AZ@KC", "g1", "SOMETHING_NEW")])
        self.assertEqual(s["n_systems"], 1)
        self.assertEqual(s["reasons"][0]["reason"], "SOMETHING_NEW")
        self.assertIn("not been taught", s["reasons"][0]["sentence"])

    def test_reasons_render_without_jargon(self):
        """These strings reach a customer. No enum names, no snake_case."""
        s = self._summary([_row("AZ@KC", "g1", "NO_LINEUP"),
                           _row("AZ@KC", "g2", "NO_SIGNAL")])
        for r in s["reasons"]:
            self.assertNotIn("_", r["sentence"])
            self.assertNotIn(r["reason"], r["sentence"])
        self.assertNotIn("_", s["headline"])

    def test_another_date_does_not_leak_in(self):
        s = self._summary([_row("AZ@KC", "g1", "NO_LINEUP"),
                           _row("AZ@KC", "g2", "NO_SIGNAL",
                                date="2026-09-08")])
        self.assertEqual(s["n_systems"], 1)

    def test_systems_are_listed_so_the_count_is_checkable(self):
        s = self._summary([_row("AZ@KC", "gb", "NO_LINEUP"),
                           _row("AZ@KC", "ga", "NO_LINEUP")])
        self.assertEqual(s["reasons"][0]["systems"], ["ga", "gb"])


class ByGameTests(unittest.TestCase):
    def test_it_groups_every_game_on_the_date(self):
        store = _Store([_row("AZ@KC", "g1", "NO_LINEUP"),
                        _row("CLE@BAL", "g1", "NO_SIGNAL")])
        self.addCleanup(store.close)
        out = sd.by_game(DATE, store.path)
        self.assertEqual(set(out), {"AZ@KC", "CLE@BAL"})


if __name__ == "__main__":
    unittest.main()
