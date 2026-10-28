"""The append-only ledger and the credit cap guard of LIVE_TENNIS_V1.

Ledger: a second row of a kind for the same id is refused, a bet has one reference OR one no_reference, an edit or a
deletion breaks the hash chain, the constants fingerprint is checked against the genesis row, and the snapshot store
reads only the tail of a long file.

Guard: every refusal in the order the guard checks them (switch, stop date, unreadable quota, floor, daily cap,
pre-match sub-cap, monthly cap, the owner's shared live-odds cap), each with its boundary, plus the billing rule
(a call's own x-requests-last, one when the vendor sent none, never zero).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.capture import budget
from src.pipeline import creditlog
from src.research.live_tennis import config, guard
from src.research.live_tennis.ledger import LedgerError, PaperLedger, SnapshotStore

from tests.live_tennis_fixtures import utc

ON = {config.ENV_SWITCH: "on"}
NOON = utc("2026-11-02T12:00:00Z")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.jsonl"
        self.ledger = PaperLedger(self.path)

    def test_genesis_is_written_once_and_carries_the_freeze(self):
        first = self.ledger.ensure_genesis(now=NOON, prereg_sha256="ab" * 32)
        again = self.ledger.ensure_genesis(now=utc("2026-11-03T00:00:00Z"), prereg_sha256="cd" * 32)
        self.assertEqual(first["row_hash"], again["row_hash"])
        self.assertEqual(len(self.ledger.rows()), 1)
        self.assertEqual(first["fingerprint"], config.fingerprint())
        self.assertEqual(first["stop_date"], config.STOP_DATE)
        self.assertEqual(first["first_capture_utc"], "2026-11-02T12:00:00Z")
        self.assertEqual(first["constants"], config.constants())

    def test_a_second_decision_for_the_same_dp_is_refused(self):
        self.ledger.append("decision", {"dp_id": "e:S2", "status": "NO_BET"}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("decision", {"dp_id": "e:S2", "status": "BET"}, now=NOON)
        self.ledger.append("decision", {"dp_id": "e:S3", "status": "BET"}, now=NOON)
        self.assertEqual(len(self.ledger.of_kind("decision")), 2)

    def test_armed_outcome_and_attempt_uniqueness(self):
        self.ledger.append("armed", {"dp_id": "e:S2"}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("armed", {"dp_id": "e:S2"}, now=NOON)
        self.ledger.append("attempt", {"dp_id": "e:S2", "attempt_no": 1}, now=NOON)
        self.ledger.append("attempt", {"dp_id": "e:S2", "attempt_no": 2}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("attempt", {"dp_id": "e:S2", "attempt_no": 2}, now=NOON)
        self.ledger.append("outcome", {"dp_id": "e:S2"}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("outcome", {"dp_id": "e:S2"}, now=NOON)

    def test_a_bet_has_a_reference_or_a_no_reference_never_both(self):
        self.ledger.append("reference", {"dp_id": "e:S2"}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("reference", {"dp_id": "e:S2"}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("no_reference", {"dp_id": "e:S2", "cause": "X"}, now=NOON)
        self.ledger.append("no_reference", {"dp_id": "e:S3", "cause": "X"}, now=NOON)
        with self.assertRaises(LedgerError):
            self.ledger.append("reference", {"dp_id": "e:S3"}, now=NOON)

    def test_unknown_kinds_reserved_fields_and_missing_ids_are_refused(self):
        for kind, payload in (("fill", {"dp_id": "x"}), ("decision", {"dp_id": "x", "kind": "armed"}),
                              ("decision", {"dp_id": "x", "recorded_utc": "2020"}), ("decision", {}),
                              ("attempt", {"dp_id": "x"}), ("reference", {})):
            with self.assertRaises(LedgerError, msg=f"{kind} {payload}"):
                self.ledger.append(kind, payload, now=NOON)
        self.assertFalse(self.path.exists())

    def test_the_chain_detects_an_edit_and_a_deletion(self):
        for i in range(4):
            self.ledger.append("decision", {"dp_id": f"e:S{i}", "status": "NO_BET"}, now=NOON)
        self.assertTrue(self.ledger.verify().ok)
        original = self.path.read_text(encoding="utf-8")
        self.path.write_text(original.replace('"NO_BET"', '"BET"', 1), encoding="utf-8")
        broken = PaperLedger(self.path).verify()
        self.assertFalse(broken.ok)
        self.assertEqual(broken.broken_at_line, 1)
        lines = original.splitlines()
        self.path.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")
        self.assertFalse(PaperLedger(self.path).verify().ok)

    def test_fingerprint_mismatch_is_reported_only_when_a_constant_moved(self):
        self.assertIsNone(self.ledger.fingerprint_problem())                 # no genesis yet
        self.ledger.ensure_genesis(now=NOON)
        self.assertIsNone(self.ledger.fingerprint_problem())
        with mock.patch.object(config, "GAP_THRESHOLD_PP", 1.0):
            self.assertIn("fingerprint", self.ledger.fingerprint_problem())

    def test_the_cache_follows_appends_and_outside_edits(self):
        self.ledger.append("armed", {"dp_id": "a"}, now=NOON)
        self.assertEqual(len(self.ledger.rows()), 1)
        self.ledger.append("armed", {"dp_id": "b"}, now=NOON)
        self.assertEqual([r["dp_id"] for r in self.ledger.rows()], ["a", "b"])
        other = PaperLedger(self.path)
        other.append("armed", {"dp_id": "c"}, now=NOON)
        self.assertEqual([r["dp_id"] for r in self.ledger.rows()], ["a", "b", "c"])


class TailChainTests(unittest.TestCase):
    """The ledgers read only the END of the file to find the last hash; the bytes they write must stay the stock format."""

    def test_the_tail_hash_equals_the_stock_full_scan_and_the_chain_verifies(self):
        from src.ledger.chain import HashChainLedger

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chain.jsonl"
            store = SnapshotStore(path)
            self.assertEqual(store._chain.last_hash(), HashChainLedger(path).last_hash())      # no file: genesis
            for i in range(25):
                size = 40 if i % 5 else 40000                                                  # rows smaller and larger than the window
                store.append({"snapshot_id": f"s{i}", "t_resp": f"2026-11-02T00:{i:02d}:00Z", "pad": "x" * size})
                self.assertEqual(store._chain.last_hash(), HashChainLedger(path).last_hash(), i)
            self.assertTrue(HashChainLedger(path).verify().ok)
            self.assertEqual(len(HashChainLedger(path).read()), 25)

    def test_an_empty_file_falls_back_to_the_stock_behaviour(self):
        from src.ledger.chain import GENESIS_HASH

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            self.assertEqual(SnapshotStore(path)._chain.last_hash(), GENESIS_HASH)


class SnapshotStoreTests(unittest.TestCase):
    def test_recent_reads_the_tail_and_returns_only_rows_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp) / "snaps.jsonl")
            for hour in range(10):
                store.append({"snapshot_id": f"s{hour}", "t_resp": f"2026-11-02T{hour:02d}:00:00Z", "key": "k",
                              "events": {"e": {"pad": "x" * 400}}})
            got = store.recent(utc("2026-11-02T07:00:00Z"), chunk_bytes=900)
            self.assertEqual([r["snapshot_id"] for r in got], ["s7", "s8", "s9"])
            self.assertEqual(len(store.recent(utc("2026-11-01T00:00:00Z"), chunk_bytes=900)), 10)
            self.assertEqual(store.recent(utc("2026-11-03T00:00:00Z")), [])
            self.assertTrue(store.verify().ok)
            with self.assertRaises(LedgerError):
                store.append({"snapshot_id": "", "t_resp": "x"})

    def test_missing_file_is_empty(self):
        self.assertEqual(SnapshotStore(Path(tempfile.gettempdir()) / "no_such_live_tennis_store.jsonl").recent(NOON), [])


def row(day, caller, used, band="live_odds", hour="12"):
    return {"utc": f"{day}T{hour}:00:00Z", "caller": caller, "credits_used_last": used, "budget_band": band,
            "credits_remaining": None}


class GuardTests(unittest.TestCase):
    def ok(self, est=1, purpose="decision", **kw):
        kw.setdefault("env", ON)
        kw.setdefault("remaining", 50000)
        kw.setdefault("now", NOON)
        kw.setdefault("rows", [])
        return guard.can_spend(est, purpose=purpose, **kw)

    def test_off_is_the_default_and_refuses_everything(self):
        verdict = guard.can_spend(1, now=NOON, remaining=50000, rows=[], env={})
        self.assertFalse(verdict.allowed)
        self.assertIn("OFF", verdict.reason)
        self.assertFalse(guard.can_spend(0, now=NOON, remaining=50000, rows=[], env={}).allowed)

    def test_free_calls_and_unknown_purposes(self):
        self.assertTrue(self.ok(est=0).allowed)
        self.assertFalse(self.ok(purpose="speculation").allowed)

    def test_unreadable_balance_fails_closed(self):
        verdict = self.ok(remaining=None)
        self.assertFalse(verdict.allowed)
        self.assertIn("unreadable", verdict.reason)

    def test_credit_floor_boundary(self):
        floor = budget.CREDIT_FLOOR
        self.assertTrue(self.ok(remaining=floor + 2).allowed)
        refused = self.ok(remaining=floor + 1)
        self.assertFalse(refused.allowed)
        self.assertIn("floor", refused.reason)

    def test_stop_date(self):
        self.assertTrue(self.ok(now=utc("2027-01-31T23:59:59Z")).allowed)
        late = self.ok(now=utc("2027-02-01T00:00:01Z"))
        self.assertFalse(late.allowed)
        self.assertIn("stop date", late.reason)

    def test_daily_cap_boundary_counts_only_this_tests_own_rows_today(self):
        today = "2026-11-02"
        at_cap = [row(today, config.CREDIT_CALLER, config.DAILY_CREDIT_CAP - 1)]
        self.assertTrue(self.ok(rows=at_cap).allowed)
        self.assertFalse(self.ok(est=2, rows=at_cap).allowed)
        self.assertIn("daily cap", self.ok(est=2, rows=at_cap).reason)
        other_callers = [row(today, "allsports_capture.inplay", 5000, band="allsports_capture")]
        self.assertTrue(self.ok(rows=other_callers).allowed)
        yesterday = [row("2026-11-01", config.CREDIT_CALLER, 199)]
        self.assertTrue(self.ok(rows=yesterday).allowed)

    def test_prematch_subcap_only_binds_a_prematch_purpose(self):
        today = "2026-11-02"
        rows = [row(today, config.CREDIT_CALLER_PREMATCH, config.PREMATCH_DAILY_SUBCAP)]
        refused = self.ok(purpose="prematch", rows=rows)
        self.assertFalse(refused.allowed)
        self.assertIn("pre-match", refused.reason)
        self.assertTrue(self.ok(purpose="decision", rows=rows).allowed)
        self.assertTrue(self.ok(purpose="prematch", rows=[row(today, config.CREDIT_CALLER_PREMATCH,
                                                              config.PREMATCH_DAILY_SUBCAP - 1)]).allowed)

    def test_monthly_cap(self):
        spread = [row(f"2026-11-{d:02d}", config.CREDIT_CALLER, 100) for d in range(1, 2)]
        many = [row(f"2026-11-{d:02d}", config.CREDIT_CALLER, 100) for d in range(3, 28)]       # 2,500 on other days
        many += [row(f"2026-10-{d:02d}", config.CREDIT_CALLER, 200) for d in range(1, 31)]      # last month does not count
        self.assertTrue(self.ok(rows=many + spread).allowed)
        heavy = [row(f"2026-11-{d:02d}", config.CREDIT_CALLER, 200) for d in range(3, 24)]       # 4,200 on other days
        refused = self.ok(rows=heavy)
        self.assertFalse(refused.allowed)
        self.assertIn("monthly cap", refused.reason)
        edge = [row(f"2026-11-{d:02d}", config.CREDIT_CALLER, 200) for d in range(3, 22)]          # 19 x 200 = 3,800
        edge.append(row("2026-11-22", config.CREDIT_CALLER, config.MONTHLY_CREDIT_CAP - 3800 - 1))   # 3,999 in all
        self.assertTrue(self.ok(rows=edge).allowed)                  # the 4,000th credit is the last one allowed
        self.assertFalse(self.ok(est=2, rows=edge).allowed)

    def test_the_owners_shared_live_odds_cap_is_respected(self):
        today = "2026-11-02"
        shared = [row(today, "live_odds.capture_inplay", budget.LIVE_ODDS_DAILY_CAP)]
        refused = self.ok(rows=shared)
        self.assertFalse(refused.allowed)
        self.assertIn("shared", refused.reason)
        self.assertTrue(self.ok(rows=[row(today, "live_odds.capture_inplay", budget.LIVE_ODDS_DAILY_CAP - 1)]).allowed)

    def test_log_call_bills_the_vendors_own_cost_and_never_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "live_credit.jsonl"
            self.assertEqual(guard.log_call(purpose="decision", usage={"remaining": 49990, "last": 1}, now=NOON, store=store), 1)
            self.assertEqual(guard.log_call(purpose="prematch", usage={"remaining": 49980, "last": 3}, now=NOON, store=store), 3)
            self.assertEqual(guard.log_call(purpose="reference", usage={"remaining": None, "last": None}, now=NOON, store=store), 1)
            self.assertEqual(guard.log_call(purpose="decision", usage=None, now=NOON, store=store), 1)
            rows = creditlog.read(store)
            self.assertEqual([r["credits_used_last"] for r in rows], [1, 3, 1, 1])
            self.assertEqual({r["budget_band"] for r in rows}, {"live_odds"})
            self.assertEqual([r["caller"] for r in rows], [config.CREDIT_CALLER, config.CREDIT_CALLER_PREMATCH,
                                                          config.CREDIT_CALLER, config.CREDIT_CALLER])
            # these rows are exactly what the guard counts back
            self.assertEqual(guard.spent(rows, day="2026-11-02", caller_prefix=config.CREDIT_CALLER), 6)
            self.assertEqual(guard.spent(rows, day="2026-11-02", caller_prefix=config.CREDIT_CALLER_PREMATCH), 3)
            self.assertEqual(guard.spent(rows, day="2026-11-02", band=budget.LIVE_ODDS), 6)


if __name__ == "__main__":
    unittest.main()
