"""`analyst compare`: arm A against arm B, by sport and market family.

The ledgers here are written with the real hash-chain primitive and hand-made rows, so every
figure in the report can be checked on paper. The rule the owner set: rates are withheld under 30
graded calls per family.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.analyst import compare, grading, ledger, ufc_ledger
from src.ledger.chain import HashChainLedger

MLB = compare.SPORTS["mlb"]
UFC = compare.SPORTS["ufc"]


class World:
    """Two ledgers (arm A's and arm B's) in a temporary directory, filled by hand."""

    def __init__(self, root: Path, mod=ledger, id_key="game_id"):
        self.mod, self.id_key = mod, id_key
        self.a = HashChainLedger(str(root / "a.jsonl"))
        self.b = HashChainLedger(str(root / "b.jsonl"))
        self.published = {}

    def call(self, slot, verdict="TAKE", selection="X", price=150, estimate=0.5, family="moneyline"):
        return {"slot_id": slot, "market": family, "selection": selection, "verdict": verdict, "price": price,
                "book": "dk", "fair_estimate": estimate, "grading": {"family": family}}

    def publish(self, arm, gid, calls, *, date="2026-10-03", version=1, marked=True):
        chain = self.a if arm == "A" else self.b
        payload = {"kind": self.mod.KIND_PUBLISHED, self.id_key: gid, "date": date, "calls": calls,
                   "version": version, "away": "NYY", "home": "TB",
                   "fighters": {"a": {"name": "A"}, "b": {"name": "B"}}}
        if arm == "B" and marked:
            payload["arm"] = "B"
        row = chain.append(payload)
        self.published[(arm, gid)] = row
        return row

    def grade(self, arm, gid, results):
        """results: {slot: (result, profit_units)} or {slot: (result, profit, would_have_result)}."""
        chain = self.a if arm == "A" else self.b
        calls = []
        for slot, spec in results.items():
            c = {"slot_id": slot, "result": spec[0], "profit_units": spec[1]}
            if len(spec) > 2:
                c["would_have"] = {"result": spec[2]}
            calls.append(c)
        pub = self.published[(arm, gid)]
        return chain.append({"kind": self.mod.KIND_GRADED, self.id_key: gid, "date": pub["date"],
                             "published_row_hash": pub["row_hash"], "complete": True, "calls": calls})

    def rows(self):
        return self.mod.rows(self.a.path), self.mod.rows(self.b.path)

    def compare(self, sport=MLB, min_graded=30, **kw):
        a, b = self.rows()
        return compare.compare_sport(sport, a, b, min_graded=min_graded, **kw)


def fam(report, name="moneyline"):
    return report["families"][name]


class WithTemp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class OnlyGamesBothArmsFroze(WithTemp):
    def test_the_comparison_is_over_paired_games_and_counts_the_rest(self):
        w = World(self.root)
        for gid in ("g1", "g2", "g3"):
            w.publish("A", gid, [w.call("moneyline")])
        for gid in ("g2", "g3", "g4"):
            w.publish("B", gid, [w.call("moneyline")])
        r = w.compare()
        self.assertEqual(r["games"], {"published_a": 3, "published_b": 3, "paired": 2, "only_a": 1, "only_b": 1})
        self.assertEqual(fam(r)["A"]["taken"], 2)           # g1 is not counted: B never froze it
        self.assertEqual(fam(r)["B"]["taken"], 2)           # and g4 is not counted: A never did

    def test_only_the_newest_version_of_a_game_counts(self):
        w = World(self.root)
        w.publish("A", "g1", [w.call("moneyline", verdict="PASS")], version=1)
        w.publish("A", "g1", [w.call("moneyline", verdict="TAKE")], version=2)
        w.publish("B", "g1", [w.call("moneyline")])
        r = w.compare()
        self.assertEqual((fam(r)["A"]["taken"], fam(r)["A"]["passes"]), (1, 0))

    def test_empty_ledgers_give_zeros_not_an_error(self):
        r = World(self.root).compare()
        self.assertEqual(r["games"]["paired"], 0)
        self.assertEqual(fam(r)["A"]["taken"], 0)
        self.assertEqual(fam(r)["A"]["win_rate"], None)


class TheSmallSampleRule(WithTemp):
    def fill(self, n, arm_b_n=None):
        w = World(self.root)
        for i in range(n):
            gid = f"g{i}"
            w.publish("A", gid, [w.call("moneyline")])
            w.publish("B", gid, [w.call("moneyline")])
            w.grade("A", gid, {"moneyline": ("WIN" if i % 2 == 0 else "LOSS", 1.5 if i % 2 == 0 else -1.0)})
            if arm_b_n is None or i < arm_b_n:
                w.grade("B", gid, {"moneyline": ("WIN" if i % 3 == 0 else "LOSS", 1.5 if i % 3 == 0 else -1.0)})
        return w

    def test_under_thirty_graded_calls_every_rate_is_withheld_and_the_count_is_not(self):
        r = self.fill(29).compare()
        a = fam(r)["A"]
        self.assertEqual((a["graded"], a["win_rate"], a["units"], a["units_per_call"]), (29, None, None, None))
        self.assertIn("fewer than 30 graded calls (29 so far)", a["withheld_reason"])
        self.assertIsNone(a["calibration"]["brier"])
        self.assertIn("fewer than 30", a["calibration"]["withheld_reason"])
        self.assertEqual((a["wins"], a["losses"]), (15, 14))                    # the counts are always shown
        self.assertIsNone(fam(r)["difference_b_minus_a"])

    def test_at_thirty_the_rates_appear(self):
        r = self.fill(30).compare()
        a, b = fam(r)["A"], fam(r)["B"]
        self.assertEqual(a["graded"], 30)
        self.assertEqual(a["win_rate"], 0.5)                                    # 15 of 30
        self.assertEqual(b["win_rate"], 0.3333)                                 # 10 of 30
        self.assertEqual(a["units"], round(15 * 1.5 - 15 * 1.0, 2))
        self.assertEqual(a["withheld_reason"], None)

    def test_the_difference_needs_both_arms_over_the_bar(self):
        r = self.fill(30, arm_b_n=20).compare()                                 # B has graded only 20
        self.assertEqual(fam(r)["A"]["graded"], 30)
        self.assertEqual(fam(r)["B"]["graded"], 20)
        self.assertIsNotNone(fam(r)["A"]["win_rate"])
        self.assertIsNone(fam(r)["B"]["win_rate"])
        self.assertIsNone(fam(r)["difference_b_minus_a"])
        full = self.fill(30)                                                    # (same root: more files; fresh dir)
        self.assertIsNotNone(full.compare()["families"]["moneyline"]["difference_b_minus_a"])

    def test_the_bar_is_per_family_not_per_sport(self):
        w = World(self.root)
        for i in range(30):
            gid = f"g{i}"
            calls = [w.call("moneyline")] + ([w.call("total", family="total")] if i < 5 else [])
            w.publish("A", gid, calls)
            w.publish("B", gid, calls)
            res = {"moneyline": ("WIN", 1.5)}
            if i < 5:
                res["total"] = ("WIN", 1.0)
            w.grade("A", gid, res)
            w.grade("B", gid, res)
        r = w.compare()
        self.assertIsNotNone(fam(r)["A"]["win_rate"])
        self.assertIsNone(fam(r, "total")["A"]["win_rate"])
        self.assertEqual(fam(r, "total")["A"]["graded"], 5)

    def test_the_minimum_is_the_configs(self):
        from src.analyst import config as config_mod
        self.assertEqual(config_mod.DEFAULTS["min_graded_for_rates"], 30)
        out = []
        compare.execute_compare(out=out.append, loaders={"mlb": lambda: ([], [], [], []), "ufc": lambda: ([], [], [], [])})
        self.assertIn("rates withheld under 30 graded calls per family", "\n".join(out))


class TheArithmetic(WithTemp):
    """Four calls a side at a bar of four, so every number is a short hand sum."""

    def setUp(self):
        super().setUp()
        w = World(self.root)
        # arm A: win, loss, win, win at +150 (1.5 units a win, -1 a loss), always 0.5
        a_res = [("WIN", 1.5), ("LOSS", -1.0), ("WIN", 1.5), ("WIN", 1.5)]
        # arm B: loss at 0.6, loss at 0.4, win at 0.7, win at 0.3
        b_res = [("LOSS", -1.0), ("LOSS", -1.0), ("WIN", 1.5), ("WIN", 1.5)]
        b_est = [0.6, 0.4, 0.7, 0.3]
        for i in range(4):
            gid = f"g{i}"
            w.publish("A", gid, [w.call("moneyline", estimate=0.5)])
            w.publish("B", gid, [w.call("moneyline", estimate=b_est[i])])
            w.grade("A", gid, {"moneyline": a_res[i]})
            w.grade("B", gid, {"moneyline": b_res[i]})
        self.r = w.compare(min_graded=4)

    def test_results_and_units(self):
        a, b = fam(self.r)["A"], fam(self.r)["B"]
        self.assertEqual((a["wins"], a["losses"], a["win_rate"], a["units"], a["units_per_call"]),
                         (3, 1, 0.75, 3.5, 0.875))
        self.assertEqual((b["wins"], b["losses"], b["win_rate"], b["units"], b["units_per_call"]),
                         (2, 2, 0.5, 1.0, 0.25))

    def test_calibration(self):
        a, b = fam(self.r)["A"]["calibration"], fam(self.r)["B"]["calibration"]
        # A: every call said 0.5; Brier is 0.25 whatever happens; it won 0.75 of them
        self.assertEqual((a["calls"], a["brier"], a["mean_estimate"], a["actual_rate"], a["gap"]),
                         (4, 0.25, 0.5, 0.75, -0.25))
        # B: (0.6-0)^2 + (0.4-0)^2 + (0.7-1)^2 + (0.3-1)^2 = 0.36 + 0.16 + 0.09 + 0.49 = 1.10, over four
        self.assertEqual((b["brier"], b["mean_estimate"], b["actual_rate"], b["gap"]), (0.275, 0.5, 0.5, 0.0))

    def test_the_difference_is_b_minus_a(self):
        d = fam(self.r)["difference_b_minus_a"]
        self.assertEqual((d["win_rate"], d["units"], d["units_per_call"], d["brier"]), (-0.25, -2.5, -0.625, 0.025))


class WhatIsCounted(WithTemp):
    def test_passes_and_their_would_have_results_are_not_bets(self):
        w = World(self.root)
        w.publish("A", "g1", [w.call("moneyline", verdict="PASS", estimate=None)])
        w.publish("B", "g1", [w.call("moneyline", verdict="TAKE_OTHER_SIDE")])
        w.grade("A", "g1", {"moneyline": ("PASS", 0.0, "WIN")})
        w.grade("B", "g1", {"moneyline": ("LOSS", -1.0)})
        r = w.compare(min_graded=1)
        a, b = fam(r)["A"], fam(r)["B"]
        self.assertEqual((a["taken"], a["passes"], a["graded"], a["passes_would_have_won"]), (0, 1, 0, 1))
        self.assertEqual((b["taken"], b["taken_other_side"], b["graded"], b["losses"]), (1, 1, 1, 1))

    def test_pushes_and_voids_and_unresolved_are_counted_apart(self):
        w = World(self.root)
        for i, res in enumerate(("PUSH", "VOID", "UNRESOLVED", "WIN")):
            gid = f"g{i}"
            w.publish("A", gid, [w.call("moneyline")])
            w.publish("B", gid, [w.call("moneyline")])
            if res != "UNRESOLVED":
                w.grade("A", gid, {"moneyline": (res, 0.0 if res != "WIN" else 1.5)})
        a = fam(w.compare(min_graded=1))["A"]
        self.assertEqual((a["pushes"], a["voids"], a["unresolved"], a["wins"], a["graded"]), (1, 1, 1, 1, 2))
        self.assertEqual(a["units"], 1.5)

    def test_a_correction_changes_the_result_the_report_shows(self):
        w = World(self.root)
        w.publish("A", "g1", [w.call("moneyline")])
        w.publish("B", "g1", [w.call("moneyline")])
        graded = w.grade("A", "g1", {"moneyline": ("LOSS", -1.0)})
        w.a.append({"kind": ledger.KIND_CORRECTION, "game_id": "g1", "slot_id": "moneyline",
                    "graded_row_hash": graded["row_hash"], "fields": {"result": "WIN", "profit_units": 1.5},
                    "reason": "the book's rule"})
        a = fam(w.compare(min_graded=1))["A"]
        self.assertEqual((a["wins"], a["losses"], a["units"]), (1, 0, 1.5))

    def test_a_call_with_no_estimate_is_not_in_the_calibration(self):
        w = World(self.root)
        for i in range(3):
            w.publish("A", f"g{i}", [w.call("moneyline", estimate=None if i == 0 else 0.6)])
            w.publish("B", f"g{i}", [w.call("moneyline")])
            w.grade("A", f"g{i}", {"moneyline": ("WIN", 1.5)})
            w.grade("B", f"g{i}", {"moneyline": ("WIN", 1.5)})
        a = fam(w.compare(min_graded=1))["A"]["calibration"]
        self.assertEqual(a["calls"], 2)

    def test_it_agrees_with_the_record_when_every_game_is_paired(self):
        w = World(self.root)
        for i in range(6):
            gid = f"g{i}"
            calls = [w.call("moneyline", verdict="TAKE" if i % 2 == 0 else "PASS"),
                     w.call("total", family="total", verdict="TAKE_OTHER_SIDE")]
            w.publish("A", gid, calls)
            w.publish("B", gid, calls)
            w.grade("A", gid, {"moneyline": ("WIN" if i % 4 == 0 else "LOSS", 1.5), "total": ("PUSH", 0.0)})
            w.grade("B", gid, {"moneyline": ("LOSS", -1.0), "total": ("WIN", 0.9)})
        rows_a, _rows_b = w.rows()
        record = ledger.record(all_rows=rows_a, min_graded=1)
        report = w.compare(min_graded=1)
        for name in ("moneyline", "total"):
            for key in ("taken", "taken_other_side", "passes", "graded", "wins", "losses", "pushes", "voids",
                        "unresolved", "units"):
                self.assertEqual(fam(report, name)["A"][key], record["families"][name][key], f"{name}.{key}")

    def test_the_agreement_counts(self):
        w = World(self.root)
        w.publish("A", "g1", [w.call("moneyline", verdict="TAKE"), w.call("total", family="total", verdict="PASS"),
                              w.call("run_line", family="run_line", verdict="TAKE", selection="Y"),
                              w.call("team_total_home", family="team_total", verdict="TAKE"),
                              w.call("prop_01", family="prop", verdict="PASS")])
        w.publish("B", "g1", [w.call("moneyline", verdict="PASS"), w.call("total", family="total", verdict="TAKE"),
                              w.call("run_line", family="run_line", verdict="TAKE", selection="Y"),
                              w.call("team_total_home", family="team_total", verdict="TAKE_OTHER_SIDE"),
                              w.call("prop_02", family="prop", verdict="PASS")])
        r = w.compare()
        self.assertEqual(fam(r)["agreement"], {"slots_in_both": 1, "same_verdict": 0, "a_take_b_pass": 1,
                                               "a_pass_b_take": 0, "both_take_different_calls": 0,
                                               "slot_only_in_a": 0, "slot_only_in_b": 0})
        self.assertEqual(fam(r, "total")["agreement"]["a_pass_b_take"], 1)
        self.assertEqual(fam(r, "run_line")["agreement"]["same_verdict"], 1)
        self.assertEqual(fam(r, "team_total")["agreement"]["both_take_different_calls"], 1)
        self.assertEqual((fam(r, "prop")["agreement"]["slot_only_in_a"], fam(r, "prop")["agreement"]["slot_only_in_b"]),
                         (1, 1))


class TheLedgersAreTheRightOnes(WithTemp):
    def test_a_file_whose_rows_are_not_marked_arm_b_is_refused(self):
        w = World(self.root)
        w.publish("A", "g1", [w.call("moneyline")])
        w.publish("B", "g1", [w.call("moneyline")], marked=False)
        r = w.compare()
        self.assertTrue(r["problems"])
        self.assertIn("not marked arm B", r["problems"][0])
        out = []
        code = compare.execute_compare(out=out.append, loaders={"mlb": lambda: w.rows() + ([], []),
                                                                 "ufc": lambda: ([], [], [], [])})
        self.assertEqual(code, compare.EXIT_PROBLEM)
        self.assertIn("PROBLEM:", "\n".join(out))

    def test_an_arm_a_file_holding_arm_b_rows_is_refused(self):
        w = World(self.root)
        w.a.append({"kind": ledger.KIND_PUBLISHED, "game_id": "g1", "date": "2026-10-03", "calls": [],
                    "version": 1, "arm": "B"})
        w.publish("B", "g1", [w.call("moneyline")])
        self.assertTrue(w.compare()["problems"])

    def test_two_good_ledgers_have_no_problem_and_exit_zero(self):
        w = World(self.root)
        w.publish("A", "g1", [w.call("moneyline")])
        w.publish("B", "g1", [w.call("moneyline")])
        self.assertEqual(w.compare()["problems"], [])
        code = compare.execute_compare(out=lambda s: None, loaders={"mlb": lambda: w.rows() + ([], []),
                                                                     "ufc": lambda: ([], [], [], [])})
        self.assertEqual(code, compare.EXIT_OK)


class TheCost(WithTemp):
    def test_cost_is_summed_over_the_paired_games_only(self):
        w = World(self.root)
        for gid in ("g1", "g2"):
            w.publish("A", gid, [w.call("moneyline")])
        w.publish("B", "g1", [w.call("moneyline")])
        usage_a = [{"game_id": "g1", "cost_usd": 0.08}, {"game_id": "g2", "cost_usd": 0.09}]
        usage_b = [{"game_id": "g1", "cost_usd": 0.12}, {"game_id": "g9", "cost_usd": 0.50}]
        c = w.compare(usage_a=usage_a, usage_b=usage_b)["cost"]
        self.assertEqual((c["arm_a_usd"], c["arm_b_usd"], c["ratio"]), (0.08, 0.12, 1.5))

    def test_no_cost_logged_is_no_ratio_not_a_divide_by_zero(self):
        self.assertIsNone(World(self.root).compare()["cost"]["ratio"])


class UfcAndTheWords(WithTemp):
    def test_the_ufc_families_and_ids(self):
        w = World(self.root, mod=ufc_ledger, id_key="bout_id")
        calls = [w.call("moneyline"), w.call("method_a_ko", family="method"), w.call("rounds_total", family="rounds_total")]
        w.publish("A", "9101", calls)
        w.publish("B", "9101", calls)
        r = w.compare(sport=UFC)
        self.assertEqual(r["sport"], "ufc")
        self.assertEqual(set(r["families"]), {"moneyline", "method", "rounds_total"})
        self.assertEqual(r["games"]["paired"], 1)
        self.assertEqual(fam(r, "method")["A"]["taken"], 1)

    def test_the_text_report_says_what_it_compares_and_withholds(self):
        w = World(self.root)
        for i in range(3):
            w.publish("A", f"g{i}", [w.call("moneyline")])
            w.publish("B", f"g{i}", [w.call("moneyline", verdict="PASS")])
            w.grade("A", f"g{i}", {"moneyline": ("WIN", 1.5)})
        out = []
        compare.execute_compare(sport="mlb", out=out.append, loaders={"mlb": lambda: w.rows() + ([], [])})
        text = "\n".join(out)
        self.assertIn("Unproven. Analysis, not advice.", text)
        self.assertIn("Arm A reads the matchup statistics. Arm B reads the same plus the situation layer.", text)
        self.assertIn("3 paired", text)
        self.assertIn("win rate withheld", text)
        self.assertIn("B minus A: withheld until both arms have 30 graded calls", text)
        self.assertIn("A bet and B passed on 3", text)

    def test_the_json_report_is_machine_readable(self):
        out = []
        compare.execute_compare(sport="mlb", as_json=True, out=out.append,
                                loaders={"mlb": lambda: ([], [], [], [])})
        data = json.loads(out[0])
        self.assertEqual(data["version"], "analyst_compare_v1")
        self.assertEqual(data["min_graded"], 30)
        self.assertEqual(list(data["sports"]), ["mlb"])

    def test_it_reads_nothing_it_was_not_given_a_missing_ledger_is_empty(self):
        rows = ledger.rows(str(self.root / "no_such.jsonl"))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
