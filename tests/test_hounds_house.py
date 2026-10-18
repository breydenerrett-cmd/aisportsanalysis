"""The house pack's copy must be TRUE and every hound must be real.

Reads config/house_hounds.json (the editable copy) and checks it against the
code that actually decides: the engine's baseline classes, the evolab genomes
the signal hounds are, and the paused-card memo. Read-only against the repo's
ledgers (the account files are git-tracked evidence).
"""

from __future__ import annotations

import json
import types
import unittest
from pathlib import Path

from src.hounds import house
from src.hounds.contract import CATEGORIES, KINDS

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "house_hounds.json"


def defs():
    return house.definitions(CFG, ROOT / "config" / "house_pack.json")


class HouseConfig(unittest.TestCase):
    def test_config_exists_and_ids_are_unique(self):
        d = defs()
        self.assertGreaterEqual(len(d), 6)
        self.assertEqual(len({x["id"] for x in d}), len(d))

    def test_every_hound_has_copy_and_valid_vocabulary(self):
        for x in defs():
            with self.subTest(x["id"]):
                for key in ("name", "tagline", "rule_text", "style"):
                    self.assertTrue(x[key].strip(), key)
                self.assertIn(x["kind"], KINDS)
                self.assertIn(x["category"], CATEGORIES)
                self.assertGreater(len(x["rule_text"]), 60)

    def test_baselines_are_marked_baseline(self):
        base = {x["system_id"] for x in defs() if x["kind"] == "baseline"}
        self.assertEqual(base, {"trivial_always_home", "trivial_under_total",
                                "market_derived_consensus_totals_over"})
        for x in defs():
            if x["kind"] == "baseline":
                self.assertEqual(x["category"], "baseline")

    def test_each_engine_hound_maps_to_a_system_with_a_ledger_of_graded_bets(self):
        for x in defs():
            if not x.get("system_id"):
                continue
            with self.subTest(x["system_id"]):
                path = ROOT / "data" / "paper_accounts" / f"{x['system_id']}.jsonl"
                self.assertTrue(path.exists(), path)
                rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertGreaterEqual(len(rows), 50)
                self.assertTrue(all(r["system_id"] == x["system_id"] for r in rows))


class RuleTextIsTrue(unittest.TestCase):
    def setUp(self):
        self.by_id = {x["id"]: x for x in defs()}

    def test_signal_hounds_text_is_regenerated_from_the_genome(self):
        from src.evolab.genome import enumerate_genomes
        genomes = {g.strategy_id: g for g in enumerate_genomes()}
        signal = [x for x in self.by_id.values()
                  if x.get("system_id") and x["kind"] == "house"]
        self.assertGreaterEqual(len(signal), 4)
        for x in signal:
            with self.subTest(x["id"]):
                genome = genomes[x["system_id"]]       # a real, enumerable genome
                self.assertEqual(x["rule_text"], house.genome_rule_text(genome))
                for s in genome.signals:               # every signal is named
                    self.assertIn(house.SIGNAL_WORDS[s.feature].split(" (")[0], x["rule_text"])

    def test_genome_text_reflects_weights_gate_and_lineup_requirement(self):
        from src.evolab.genome import enumerate_genomes
        g = next(g for g in enumerate_genomes()
                 if g.strategy_id == "e5ff00d4b3899ccc")
        text = house.genome_rule_text(g)
        self.assertIn("counted double", text)             # primary_pitch_share weight 2.0
        self.assertIn("only once the lineups are posted", text)
        self.assertIn("at least 3 books", text)
        self.assertIn("a tie is no bet", text)
        self.assertIn("3 pre-registered signals", text)

    def test_baseline_sides_match_the_code(self):
        from src.engine.adapters.evolab_system import (
            MarketDerivedConsensusSystem, TrivialUnderTotalSystem)
        from src.engine.glue import TrivialAlwaysHomeSystem
        view = types.SimpleNamespace(available_markets=("h2h", "totals", "spreads"))
        home = TrivialAlwaysHomeSystem().propose(view)
        under = TrivialUnderTotalSystem().propose(view)
        over = MarketDerivedConsensusSystem(market_key="totals", side="over").propose(view)
        self.assertEqual((home[0].market_key, home[0].side), ("h2h", "home"))
        self.assertEqual((under[0].market_key, under[0].side), ("totals", "under"))
        self.assertEqual((over[0].market_key, over[0].side), ("totals", "over"))
        self.assertEqual(over[0].p_model_provenance, "market_derived")
        t = {x["system_id"]: x["rule_text"].lower() for x in defs() if x["kind"] == "baseline"}
        self.assertIn("home team on the moneyline", t["trivial_always_home"])
        self.assertIn("under", t["trivial_under_total"])
        self.assertIn("over", t["market_derived_consensus_totals_over"])
        self.assertIn("no opinion and no edge", t["market_derived_consensus_totals_over"])

    def test_old_dog_cites_the_pause_memo_and_is_retired(self):
        dog = self.by_id["old-dog"]
        self.assertTrue(dog["card"])
        self.assertEqual(dog["retired"]["date"], "2026-10-16")
        self.assertIn("paused 2026-10-16", dog["retired"]["cause"])
        self.assertIn("premium over the market", dog["retired"]["cause"])
        self.assertIn("docs/decisions/MLB_VALUE_PICKS_PAUSED.md", dog["rule_text"])
        self.assertTrue((ROOT / "docs/decisions/MLB_VALUE_PICKS_PAUSED.md").exists())
        self.assertIn("MLB_VALUE_PICKS_PAUSED", dog["verdict_sentence"])

    def test_no_edge_or_profit_language_in_the_copy(self):
        banned = ("guarantee", "sure thing", "lock of", "free money", "can't lose",
                  "profit", "will win", "beat the book", "edge on")
        for x in defs():
            blob = " ".join([x["name"], x["tagline"], x["rule_text"], x["style"]]).lower()
            for word in banned:
                with self.subTest(x["id"], word=word):
                    self.assertNotIn(word, blob)


if __name__ == "__main__":
    unittest.main()
