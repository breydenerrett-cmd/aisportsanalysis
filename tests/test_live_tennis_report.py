"""The report of LIVE_TENNIS_V1: counts always, effect statistics only past the pre-registered floors.

The ledger is built synthetically (small rows, so a few hundred bets stay fast). What is pinned:

  * the five states are never run together: NO_DATA (no input) is not COLLECTING (a floor unmet) is not INCONCLUSIVE
    (the stop date passed, or the freeze or the chain is broken) is not PASS or FAIL;
  * below any floor NOTHING resembling a result is in the report (no M1, M2, units, Brier), in the dict or the text;
  * PASS needs M2's interval entirely above zero AND M1 above zero; either alone is FAIL;
  * a shadow reference never counts toward a floor or the decisive statistic;
  * the verdict is appended to the alpha registry once, for a final state only.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ledger.chain import PREV_HASH_FIELD, ROW_HASH_FIELD, row_hash
from src.research import alpha_registry
from src.research.live_tennis import config, decision, report
from src.research.live_tennis.ledger import PaperLedger

from tests.live_tennis_fixtures import utc

NOW = utc("2026-12-01T12:00:00Z")
AFTER_STOP = utc("2027-02-02T12:00:00Z")


class Synth:
    """Builds a ledger of `n` bets spread over `matches` matches with controllable M1/M2."""

    def __init__(self, tmp: Path):
        self.ledger = PaperLedger(tmp / "ledger.jsonl")
        self.hb = tmp / "heartbeat.jsonl"
        self.ledger.ensure_genesis(now=utc("2026-11-02T09:00:00Z"), prereg_sha256="aa" * 32)
        self.n = 0
        self.pending = []

    def _add(self, kind: str, payload: dict) -> None:
        """Queue a row; `flush` writes the whole batch as one valid hash chain (opening a file a thousand times is the
        slow part of a synthetic ledger on this machine, so the tests write once)."""
        self.pending.append({"kind": kind, "recorded_utc": "2026-12-01T12:00:00Z", "rule_id": config.RULE_ID,
                             "schema": config.SCHEMA_VERSION, **payload})

    def flush(self) -> None:
        if not self.pending:
            return
        prev = self.ledger._chain.last_hash()
        lines = []
        for payload in self.pending:
            row = dict(payload)
            row[PREV_HASH_FIELD] = prev
            row[ROW_HASH_FIELD] = row_hash(payload, prev)
            prev = row[ROW_HASH_FIELD]
            lines.append(json.dumps(row, sort_keys=True))
        with self.ledger.path.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line)
                fh.write(chr(10))
        self.pending = []

    def bet(self, match: int, m1: float, m2: float, *, reference: str = "yes", shadow: bool = False, won: bool = None,
            set_no: int = 2):
        self.n += 1
        dp = f"m{match}:S{set_no}:{self.n}"
        board = {"consensus_home": 0.6}
        self._add("armed", {"dp_id": dp, "espn_tour": "atp", "espn_match_id": str(match), "orientation": "straight",
                            "set_number": set_no, "t_c": "2026-11-03T11:00:00Z"})
        self._add("decision", {
            "dp_id": dp, "event_id": f"m{match}", "sport_key": "tennis_atp_x", "tour": "atp",
            "status": decision.NO_BET if shadow else decision.BET, "shadow_bet": bool(shadow),
            "reason": "BELOW_THRESHOLD" if shadow else None, "side": "home", "sets_won_home": 1, "sets_won_away": 0, "board": board,
            "model": {"p_match_home": 0.8, "p_set_home": 0.55}, "entry": {"side": "home", "best_price": 105.0,
                                                                        "avg_implied": 0.5, "best_implied": 0.49,
                                                                        "consensus": 0.52},
            "fresh_quotes": [], "t_decision": "2026-11-03T11:00:05Z"})
        if reference == "yes":
            self._add("reference", {"dp_id": dp, "event_id": f"m{match}", "m1": m1, "m2": m2, "m2_best": m2 + 0.5,
                                    "other_m1": -m1, "other_m2": -m1 - 2.8, "shadow": shadow})
        elif reference == "no":
            self._add("no_reference", {"dp_id": dp, "event_id": f"m{match}", "cause": "NO_SNAPSHOT_IN_WINDOW",
                                       "shadow": shadow})
        if won is not None:
            self._add("outcome", {"dp_id": dp, "status": decision.BET, "bet_side": "home",
                                  "bet_result": "WIN" if won else "LOSS", "profit_avg": 1.0 if won else -1.0,
                                  "profit_best": 1.05 if won else -1.0, "match_winner_home": won,
                                  "set_winner_home": won, "model_p_match_home": 0.8,
                                  "model_p_set_home": 0.55, "consensus_home_at_decision": 0.6})

    def fill(self, n_bets: int, n_matches: int, mean_m1: float, mean_m2: float, sd: float = 3.0, seed: int = 7, **kw):
        rng = random.Random(seed)
        for i in range(n_bets):
            self.bet(i % n_matches, rng.gauss(mean_m1, sd), rng.gauss(mean_m2, sd), **kw)

    def build(self, now=NOW, **kw):
        self.flush()
        return report.build(self.ledger, now=now, heartbeat_path=self.hb, credit_rows=kw.get("credit_rows", []))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.s = Synth(self.dir)


class StateTests(Base):
    def test_no_ledger_and_a_genesis_only_ledger_are_no_data_not_a_verdict(self):
        empty = report.build(PaperLedger(self.dir / "absent.jsonl"), now=NOW, heartbeat_path=self.dir / "hb",
                             credit_rows=[])
        self.assertEqual(empty["state"], report.NO_DATA)
        self.assertIsNone(empty["registry_result"])
        self.assertFalse(empty["integrity"]["ledger_exists"])
        genesis_only = self.s.build()
        self.assertEqual(genesis_only["state"], report.NO_DATA)
        self.assertIn("absence of input", genesis_only["note"])

    def test_below_the_floors_it_is_collecting_and_no_effect_statistic_exists_anywhere(self):
        self.s.fill(40, 25, 0.0, 5.0, won=True)                    # an enticing positive mean that must stay hidden
        built = self.s.build()
        self.assertEqual(built["state"], report.COLLECTING)
        self.assertNotIn("effect", built)
        self.assertNotIn("descriptive", built)
        self.assertIsNone(built["registry_result"])
        text = report.render(built)
        for needle in ("M2", "M1", "units", "Brier", "profit"):
            self.assertNotIn(needle, text.replace("floors:", ""), needle)
        self.assertEqual(built["floors"]["bets_with_reference"], 40)
        self.assertFalse(built["floors"]["met"])
        self.assertEqual(built["counts"]["bets"], 40)
        self.assertEqual(built["counts"]["outcomes"], 40)

    def test_each_floor_is_a_floor(self):
        for name in ("a", "b", "c"):
            (self.dir / name).mkdir()
        # 300 bets from only 100 matches: the match floor fails
        a = Synth(self.dir / "a")
        a.fill(300, 100, 1.0, 1.0)
        self.assertEqual(a.build()["state"], report.COLLECTING)
        self.assertEqual(a.build()["floors"]["matches"], 100)
        # 299 bets from 299 matches: the bet floor fails by one
        b = Synth(self.dir / "b")
        b.fill(299, 299, 1.0, 1.0)
        self.assertEqual(b.build()["state"], report.COLLECTING)
        # 300 bets with a reference but 200 more without: coverage 0.6 < 0.7
        c = Synth(self.dir / "c")
        c.fill(300, 300, 1.0, 1.0)
        c.fill(200, 200, 1.0, 1.0, reference="no")
        built = c.build()
        self.assertEqual(built["state"], report.COLLECTING)
        self.assertAlmostEqual(built["floors"]["coverage"], 0.6, places=6)
        self.assertEqual(built["counts"]["no_reference_causes"], {"NO_SNAPSHOT_IN_WINDOW": 200})

    def test_the_stop_date_with_a_floor_unmet_is_inconclusive_and_maps_to_below_floor(self):
        self.s.fill(20, 10, 0.0, 0.0)
        built = self.s.build(now=AFTER_STOP)
        self.assertEqual(built["state"], report.INCONCLUSIVE)
        self.assertEqual(built["registry_result"], "below_floor")
        self.assertIn("stop date", built["note"])
        self.assertNotIn("effect", built)

    def test_a_changed_constant_or_a_tampered_chain_is_inconclusive(self):
        self.s.fill(10, 10, 0.0, 0.0)
        with mock.patch.object(config, "GAP_THRESHOLD_PP", 9.9):
            built = self.s.build()
        self.assertEqual(built["state"], report.INCONCLUSIVE)
        self.assertIsNotNone(built["integrity"]["fingerprint_problem"])
        path = self.s.ledger.path
        path.write_text(path.read_text(encoding="utf-8").replace('"BET"', '"NO_BET"', 1), encoding="utf-8")
        tampered = report.build(PaperLedger(path), now=NOW, heartbeat_path=self.dir / "hb", credit_rows=[])
        self.assertEqual(tampered["state"], report.INCONCLUSIVE)
        self.assertFalse(tampered["integrity"]["chain_ok"])


class VerdictTests(Base):
    def test_pass_needs_the_interval_above_zero_and_m1_above_zero(self):
        self.s.fill(330, 165, 1.5, 2.5, sd=2.0)
        built = self.s.build()
        self.assertEqual(built["state"], report.PASS)
        self.assertEqual(built["registry_result"], "candidate")
        self.assertGreater(built["effect"]["m2_interval"]["low"], 0)
        self.assertGreater(built["effect"]["m1_mean"], 0)
        self.assertEqual(built["effect"]["resamples"], config.BOOTSTRAP_RESAMPLES)
        self.assertEqual(built["effect"]["seed"], config.BOOTSTRAP_SEED)
        self.assertIn("descriptive", built)
        self.assertEqual(built["descriptive"]["units"]["bets_settled"], 0)

    def test_the_expected_outcome_a_negative_m2_is_a_fail_and_says_which_way(self):
        self.s.fill(330, 165, -0.3, -3.1, sd=3.0)
        built = self.s.build()
        self.assertEqual(built["state"], report.FAIL)
        self.assertEqual(built["registry_result"], "null")
        self.assertIn("below", built["note"])
        self.assertLess(built["effect"]["m2_mean"], 0)

    def test_a_positive_m2_whose_interval_includes_zero_is_a_fail(self):
        self.s.fill(330, 165, 0.1, 0.2, sd=6.0)
        built = self.s.build()
        self.assertEqual(built["state"], report.FAIL)
        self.assertLessEqual(built["effect"]["m2_interval"]["low"], 0)

    def test_m2_above_zero_with_m1_not_above_zero_is_still_a_fail(self):
        self.s.fill(330, 165, -1.0, 2.5, sd=2.0)
        built = self.s.build()
        self.assertGreater(built["effect"]["m2_interval"]["low"], 0)
        self.assertLess(built["effect"]["m1_mean"], 0)
        self.assertEqual(built["state"], report.FAIL)

    def test_the_interval_is_a_function_of_the_data_alone(self):
        self.s.fill(320, 160, 0.0, -2.0)
        self.assertEqual(self.s.build()["effect"], self.s.build()["effect"])

    def test_shadow_references_never_count_toward_a_floor_or_the_statistic(self):
        self.s.fill(300, 150, 1.5, 2.5, sd=2.0)
        self.s.fill(400, 200, -5.0, -9.0, sd=1.0, shadow=True)     # a flood of terrible shadow references
        built = self.s.build()
        self.assertEqual(built["floors"]["bets"], 300)
        self.assertEqual(built["floors"]["bets_with_reference"], 300)
        self.assertEqual(built["counts"]["shadow_bets"], 400)
        self.assertEqual(built["counts"]["references"], 300)
        self.assertEqual(built["effect"]["n"], 300)
        self.assertGreater(built["effect"]["m2_mean"], 0)

    def test_descriptive_extras_appear_only_past_the_floors_and_are_labelled(self):
        self.s.fill(330, 165, 1.5, 2.5, sd=2.0, won=True)
        d = self.s.build()["descriptive"]
        self.assertIn("line shopping", d["m2_best"]["label"])
        self.assertEqual(d["units"]["bets_settled"], 330)
        self.assertEqual(d["units"]["label"], "descriptive, flat 1 unit, not a result")
        self.assertAlmostEqual(d["units"]["profit_at_best_price"], 330 * 1.05, places=6)
        self.assertIsNotNone(d["brier"]["model_match"])
        self.assertEqual(d["selection_effect"]["mean"] is not None, True)


class RegistryTests(Base):
    def setUp(self):
        super().setUp()
        self.registry = self.dir / "alpha_registry.jsonl"
        alpha_registry.register({
            "kind": "hypothesis", "id": config.REGISTRY_ID, "family": "LIVE_TENNIS", "market": "h2h", "sport": "tennis",
            "registered_utc": "2026-10-28T17:05:14+00:00",
            "data_window": {"discovery": "x", "replication": None, "sealed_untouched": True}, "alpha_declared": 0.05,
            "source_doc": config.PREREG_DOC}, self.registry)

    def test_a_final_state_is_recorded_once_and_a_second_time_is_refused(self):
        self.s.fill(330, 165, -0.3, -3.1, sd=3.0)
        built = self.s.build()
        row = report.record_verdict(built, registry_path=self.registry, now=NOW)
        self.assertEqual(row["result"], "null")
        self.assertEqual(row["forward_window"]["n"], 330)
        with self.assertRaises(alpha_registry.AppendOnlyError):
            report.record_verdict(built, registry_path=self.registry, now=NOW)
        verdicts = [r for r in alpha_registry.read_all(self.registry) if r["kind"] == "verdict"]
        self.assertEqual(len(verdicts), 1)

    def test_a_non_final_state_is_not_recorded(self):
        self.s.fill(10, 10, 0.0, 0.0)
        for built in (self.s.build(), report.build(PaperLedger(self.dir / "none.jsonl"), now=NOW,
                                                   heartbeat_path=self.dir / "hb", credit_rows=[])):
            with self.assertRaises(ValueError):
                report.record_verdict(built, registry_path=self.registry)
        self.assertEqual([r for r in alpha_registry.read_all(self.registry) if r["kind"] == "verdict"], [])

    def test_inconclusive_after_the_stop_date_maps_to_below_floor(self):
        self.s.fill(10, 10, 0.0, 0.0)
        row = report.record_verdict(self.s.build(now=AFTER_STOP), registry_path=self.registry, now=AFTER_STOP)
        self.assertEqual(row["result"], "below_floor")


class CountsTests(Base):
    def test_credits_heartbeats_refusals_and_unmatched_are_counted_from_their_own_sources(self):
        self.s.fill(5, 5, 0.0, 0.0)
        self.s.hb.write_text("\n".join(json.dumps(b) for b in (
            {"utc": "2026-11-03T11:00:00Z", "espn_ok": True, "errors": ["odds x: boom"], "unmatched_live": ["e1", "e2"],
             "refused": [{"key": "k", "reason": "refused: daily cap (200 of 200 spent today, +1 would exceed it)"}]},
            {"utc": "2026-11-03T11:01:00Z", "espn_ok": False, "errors": ["espn atp: OSError"], "unmatched_live": ["e2"],
             "refused": []})) + "\n", encoding="utf-8")
        credit = [{"utc": "2026-11-03T11:00:00Z", "caller": config.CREDIT_CALLER, "credits_used_last": 1},
                  {"utc": "2026-11-03T11:30:00Z", "caller": config.CREDIT_CALLER_PREMATCH, "credits_used_last": 1},
                  {"utc": "2026-11-04T11:00:00Z", "caller": config.CREDIT_CALLER, "credits_used_last": 1},
                  {"utc": "2026-11-04T11:00:00Z", "caller": "allsports_capture.inplay", "credits_used_last": 50}]
        counts = self.s.build(credit_rows=credit)["counts"]
        self.assertEqual(counts["credits_total"], 3)
        self.assertEqual(counts["credits_by_day"], {"2026-11-03": 2, "2026-11-04": 1})
        self.assertEqual(counts["credits_per_active_day"], 1.5)
        self.assertEqual((counts["ticks"], counts["ticks_with_espn"], counts["tick_errors"]), (2, 1, 2))
        self.assertEqual(counts["unmatched_live_events"], 2)                    # distinct events across ticks
        self.assertEqual(counts["guard_refusals"], {"refused: daily cap": 1})
        self.assertEqual(counts["bets_pending_reference"], 0)


if __name__ == "__main__":
    unittest.main()
