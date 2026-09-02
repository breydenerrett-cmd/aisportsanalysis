"""Tests for src/research/alpha_registry.py and scripts/alpha_registry_migrate.py.

See docs/ALPHA_REGISTRY_DESIGN.md for the design this implements and
docs/ALPHA_REGISTRY_MIGRATION_REPORT.md for the reconciliation of every
number the migration script transcribes.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.research import alpha_registry as reg  # noqa: E402


def _load_migrate_module():
    """scripts/ is not a package -- import the migration script by path."""
    spec = importlib.util.spec_from_file_location(
        "alpha_registry_migrate", REPO_ROOT / "scripts" / "alpha_registry_migrate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TempRegistryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "alpha_registry.jsonl"

    def tearDown(self):
        self._tmpdir.cleanup()

    def make_hypothesis(self, id_="H1", market="h2h", family="TEST", **overrides):
        row = {
            "kind": "hypothesis", "id": id_, "family": family, "spec_id": "spec1",
            "market": market, "sport": "mlb", "registered_utc": "2026-01-01",
            "data_window": {"discovery": "2023", "replication": "2024",
                             "sealed_untouched": True},
            "direction": "positive", "feature_expr_hash": "deadbeef",
            "alpha_declared": 0.10, "status": "registered",
            "source_doc": "docs/TEST.md", "code_hash": "abc123",
        }
        row.update(overrides)
        return row


class TestRoundTrip(TempRegistryTestCase):
    """register -> verdict -> total_searched."""

    def test_round_trip(self):
        hyp = self.make_hypothesis()
        reg.register(hyp, path=self.path)

        verdict = {
            "kind": "verdict", "id": "H1", "read_utc": "2026-02-01",
            "result": "null", "p": 0.5, "effect": 0.01, "ci": [-0.02, 0.04],
            "battery_version": "2.0.0",
            "forward_window": {"start": None, "n": None, "pending": False},
        }
        reg.record_verdict(verdict, path=self.path)

        totals = reg.total_searched(path=self.path)
        self.assertEqual(totals["hypotheses"], 1)
        self.assertEqual(totals["sweeps"], 0)
        self.assertEqual(totals["audits"], 0)
        self.assertEqual(totals["by_family"]["TEST"]["hypotheses"], 1)

        rows = reg.read_all(path=self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["kind"], "hypothesis")
        self.assertEqual(rows[1]["kind"], "verdict")
        self.assertEqual(rows[1]["result"], "null")

    def test_total_searched_filters_by_market_and_data_window(self):
        reg.register(self.make_hypothesis(id_="A", market="h2h"), path=self.path)
        reg.register(self.make_hypothesis(id_="B", market="totals"), path=self.path)
        reg.register(self.make_hypothesis(
            id_="C", market="h2h",
            data_window={"discovery": "2019", "replication": None, "sealed_untouched": True},
        ), path=self.path)

        self.assertEqual(reg.total_searched(path=self.path, market="h2h")["hypotheses"], 2)
        self.assertEqual(reg.total_searched(path=self.path, market="totals")["hypotheses"], 1)
        self.assertEqual(
            reg.total_searched(path=self.path, data_window="2023")["hypotheses"], 2
        )
        self.assertEqual(
            reg.total_searched(path=self.path, data_window="2019")["hypotheses"], 1
        )
        self.assertEqual(
            reg.total_searched(path=self.path, market="h2h", data_window="2019")["hypotheses"], 1
        )

    def test_sweep_candidates_do_not_leak_into_hypothesis_count(self):
        sweep = self.make_hypothesis(id_="SWEEP1", kind="sweep", family="EVOLAB")
        sweep["candidates_evaluated"] = 8811
        reg.register(sweep, path=self.path)

        totals = reg.total_searched(path=self.path)
        self.assertEqual(totals["hypotheses"], 0)
        self.assertEqual(totals["sweeps"], 1)
        self.assertEqual(totals["sweep_candidates"], 8811)


class TestAppendOnly(TempRegistryTestCase):
    def test_duplicate_register_is_refused(self):
        hyp = self.make_hypothesis(id_="DUP1")
        reg.register(hyp, path=self.path)
        with self.assertRaises(reg.AppendOnlyError):
            reg.register(hyp, path=self.path)
        # exactly one row on disk -- the refused call appended nothing
        rows = reg.read_all(path=self.path)
        self.assertEqual(len(rows), 1)

    def test_duplicate_verdict_is_refused(self):
        reg.register(self.make_hypothesis(id_="DUP2"), path=self.path)
        verdict = {"kind": "verdict", "id": "DUP2", "read_utc": "2026-02-01",
                   "result": "null"}
        reg.record_verdict(verdict, path=self.path)
        with self.assertRaises(reg.AppendOnlyError):
            reg.record_verdict(verdict, path=self.path)
        rows = [r for r in reg.read_all(path=self.path) if r["kind"] == "verdict"]
        self.assertEqual(len(rows), 1)

    def test_verdict_without_registration_is_refused(self):
        verdict = {"kind": "verdict", "id": "NEVER_REGISTERED",
                   "read_utc": "2026-02-01", "result": "null"}
        with self.assertRaises(ValueError):
            reg.record_verdict(verdict, path=self.path)

    def test_register_rejects_wrong_kind(self):
        with self.assertRaises(ValueError):
            reg.register({"kind": "verdict", "id": "X"}, path=self.path)

    def test_no_function_exposes_a_delete_or_update(self):
        # Structural check that append-only isn't just convention: the
        # public surface has no rewrite/delete entry point at all.
        public = {name for name in dir(reg) if not name.startswith("_")}
        for forbidden in ("delete", "update", "rewrite", "remove", "edit"):
            self.assertFalse(
                any(forbidden in name.lower() for name in public),
                f"found a {forbidden!r}-like public name: "
                f"{[n for n in public if forbidden in n.lower()]}",
            )


class TestSemanticHashV0(unittest.TestCase):
    def test_order_invariance(self):
        atoms_a = [
            ("bullpen_exposure", "flag_present", "h2h", None),
            ("travel_load", "flag_present", "totals", None),
        ]
        atoms_b = list(reversed(atoms_a))
        self.assertEqual(reg.semantic_hash_v0(atoms_a), reg.semantic_hash_v0(atoms_b))

    def test_duplicate_atoms_do_not_change_the_hash(self):
        atoms = [("f", "op", "h2h", "positive")]
        doubled = atoms + atoms
        self.assertEqual(reg.semantic_hash_v0(atoms), reg.semantic_hash_v0(doubled))

    def test_different_atom_sets_hash_differently(self):
        a = reg.semantic_hash_v0([("f1", "op", "h2h", "positive")])
        b = reg.semantic_hash_v0([("f2", "op", "h2h", "positive")])
        self.assertNotEqual(a, b)

    def test_threshold_outside_grid_changes_the_hash(self):
        grid = [0.05, 0.10, 0.15]
        in_grid = reg.semantic_hash_v0(
            [("feat", "gte", "h2h", "positive", 0.10)], grid=grid
        )
        # 0.85 is far outside the declared grid -- buckets to the nearest
        # point (0.15) but is still a materially different threshold than
        # a value that was actually declared at 0.10.
        outside_grid = reg.semantic_hash_v0(
            [("feat", "gte", "h2h", "positive", 0.85)], grid=grid
        )
        self.assertNotEqual(in_grid, outside_grid)

    def test_thresholds_bucketing_to_the_same_grid_point_hash_identically(self):
        grid = [0.05, 0.10, 0.15]
        a = reg.semantic_hash_v0([("feat", "gte", "h2h", "positive", 0.101)], grid=grid)
        b = reg.semantic_hash_v0([("feat", "gte", "h2h", "positive", 0.099)], grid=grid)
        self.assertEqual(a, b)  # both nearest to 0.10

    def test_no_grid_uses_raw_threshold(self):
        a = reg.semantic_hash_v0([("feat", "gte", "h2h", "positive", 0.10)])
        b = reg.semantic_hash_v0([("feat", "gte", "h2h", "positive", 0.11)])
        self.assertNotEqual(a, b)

    def test_rejects_malformed_atom(self):
        with self.assertRaises(ValueError):
            reg.semantic_hash_v0([("too", "few")])


class TestMigration(TempRegistryTestCase):
    def setUp(self):
        super().setUp()
        self.migrate_mod = _load_migrate_module()

    def test_migration_produces_expected_counts(self):
        result = self.migrate_mod.migrate(path=self.path)
        self.assertEqual(result["appended_hypotheses_sweeps_audits"], 42)  # 40 + sweep + audit
        self.assertEqual(result["skipped_hypotheses_sweeps_audits"], 0)

        totals = reg.total_searched(path=self.path)
        self.assertEqual(totals["hypotheses"], 40)
        self.assertEqual(totals["sweeps"], 1)
        self.assertEqual(totals["audits"], 1)
        self.assertEqual(totals["sweep_candidates"], 8811)

        by_family = totals["by_family"]
        self.assertEqual(by_family["V1"]["hypotheses"], 21)
        self.assertEqual(by_family["V2"]["hypotheses"], 5)
        self.assertEqual(by_family["V4"]["hypotheses"], 6)
        self.assertEqual(by_family["V5"]["hypotheses"], 3)
        self.assertEqual(by_family["V3"]["hypotheses"], 5)

    def test_migration_is_idempotent(self):
        first = self.migrate_mod.migrate(path=self.path)
        rows_after_first = len(reg.read_all(path=self.path))

        second = self.migrate_mod.migrate(path=self.path)
        rows_after_second = len(reg.read_all(path=self.path))

        self.assertEqual(second["appended_hypotheses_sweeps_audits"], 0)
        self.assertEqual(second["appended_verdicts"], 0)
        self.assertEqual(
            second["skipped_hypotheses_sweeps_audits"],
            first["appended_hypotheses_sweeps_audits"],
        )
        self.assertEqual(rows_after_first, rows_after_second)

    def test_v3_five_admitted_classes_one_verdict(self):
        self.migrate_mod.migrate(path=self.path)
        rows = reg.read_all(path=self.path)
        v3_hyps = [r for r in rows if r.get("family") == "V3" and r["kind"] == "hypothesis"]
        v3_verdicts = [r for r in rows if r["kind"] == "verdict" and r["id"].startswith("V3:")]
        self.assertEqual(len(v3_hyps), 5)
        self.assertEqual(len(v3_verdicts), 1)
        self.assertEqual(v3_verdicts[0]["id"], "V3:transaction_first_seen")
        umpire_row = next(r for r in v3_hyps if r["spec_id"] == "umpire_crew_revealed")
        self.assertEqual(
            umpire_row["registered_via_amendment"],
            "docs/RESEARCH_V3_UMPIRE_CLASS.md",
        )

    def test_report_runs_and_totals_all_forty(self):
        self.migrate_mod.migrate(path=self.path)
        text = self.migrate_mod.report(path=self.path)
        self.assertIn("40 hypotheses", text)
        self.assertIn("1 sweeps", text)
        self.assertIn("1 audits", text)


if __name__ == "__main__":
    unittest.main()
