"""The recorded state that lets the daily loop stop escalating for the right
reason: scripts/tier_ladder_read.py and scripts/readiness_battery_read.py.

What these pin, and why each one matters:

- A recorded read silences an ESCALATE only while it still verifies. Edit the
  registration's rule text, change the registered script's constants, lose the
  registry row, or alter the artifact after it was registered, and the
  verifier says no -- otherwise "recorded" would be a switch anyone could flip
  by writing a file.
- A recorded ADOPT is never an all-clear.
- The checked-in record verifies against the checked-in registration and
  registry (something real reads the state it was written for).
- The registry row is an AUDIT, so the product's count of pre-registered
  hypotheses does not move.
- Settlement's battery run judges exactly one of the five fatal rules on the
  rows it hands over; a "PASS" there is mostly vacuous and the reader must
  never mistake it.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import tier_ladder_read as tlr  # noqa: E402
import readiness_battery_read as rbr  # noqa: E402
from src.research import alpha_registry, battery  # noqa: E402

PREREG_TEXT = (
    "# Pre-registration\n\n## The rule\n\nSTRONG is the 95th percentile.\n\n"
    "## Status\n\nRUN. Appended log lines live below this heading.\n")


def _constants():
    return {name: i for i, name in enumerate(tlr.REGISTERED_CONSTANTS)}


def _ladder_stub(constants=None):
    return types.SimpleNamespace(**(constants or _constants()))


def _result(rule_sha, constants=None, verdict="NOT_ADOPT"):
    return {
        "rule_id": tlr.RULE_ID,
        "registry_id": tlr.REGISTRY_ID,
        "registration": {"rule_sha256": rule_sha},
        "instrument": {"constants": constants or _constants()},
        "read": {"through_date": "2026-10-16", "n_usable_dates": 22,
                 "n_wagers_measured": 347,
                 "usable_dates": ["2026-08-31", "2026-10-15"]},
        "registered_report": {"real_mean_families": 5.032,
                              "null_mean_families": 7.132},
        "failed_checks": ["real_agreement_exceeds_the_null"],
        "verdict": verdict,
        "consequence": {"EVIDENCE_STRONG_MIN_FAMILIES": 3,
                        "decision_note": tlr.DECISION_NOTE},
    }


class _Workspace:
    """A temp prereg, artifact and registry wired together the way the real
    ones are, so each test can break exactly one link."""

    def __init__(self, test):
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.prereg = os.path.join(self.dir.name, "PREREG.md")
        self.artifact = os.path.join(self.dir.name, "result.json")
        self.registry = os.path.join(self.dir.name, "registry.jsonl")
        self.write_prereg(PREREG_TEXT)

    def write_prereg(self, text):
        with open(self.prereg, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def write_artifact(self, result):
        with open(self.artifact, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")

    def register(self, note_extra=""):
        reg = alpha_registry.AlphaRegistry(self.registry)
        reg.register({
            "kind": "audit", "id": tlr.REGISTRY_ID, "family": "TIER_LADDER",
            "market": "forward_slip", "sport": "mlb",
            "registered_utc": tlr.PREREG_COMMIT_UTC,
            "data_window": {"discovery": "2026-forward", "replication": None,
                            "sealed_untouched": True},
            "alpha_declared": None, "source_doc": "docs/PREREG_TIER_LADDER.md",
        })
        reg.record_verdict({
            "kind": "verdict", "id": tlr.REGISTRY_ID,
            "read_utc": "2026-10-17T00:00:00+00:00", "result": "audit",
            "note": "artifact sha256 " + tlr.file_sha256(self.artifact)
                    + note_extra,
        })

    def good(self, test, **overrides):
        result = _result(tlr.prereg_rule_sha256(self.prereg), **overrides)
        self.write_artifact(result)
        self.register()
        return result

    def verify(self):
        return tlr.verify_recorded(
            artifact_path=self.artifact, registry_path=self.registry,
            prereg_path=self.prereg, ladder_module=_ladder_stub())


class RuleFreezeTest(unittest.TestCase):
    def test_status_section_may_grow_without_voiding_the_read(self):
        ws = _Workspace(self)
        before = tlr.prereg_rule_sha256(ws.prereg)
        ws.write_prereg(PREREG_TEXT + "\nMore log lines appended later.\n")
        self.assertEqual(before, tlr.prereg_rule_sha256(ws.prereg))

    def test_an_edit_to_the_rule_changes_the_hash(self):
        ws = _Workspace(self)
        before = tlr.prereg_rule_sha256(ws.prereg)
        ws.write_prereg(PREREG_TEXT.replace("95th", "90th"))
        self.assertNotEqual(before, tlr.prereg_rule_sha256(ws.prereg))

    def test_crlf_checkout_hashes_the_same_as_lf(self):
        ws = _Workspace(self)
        lf = tlr.prereg_rule_sha256(ws.prereg)
        ws.write_prereg(PREREG_TEXT.replace("\n", "\r\n"))
        self.assertEqual(lf, tlr.prereg_rule_sha256(ws.prereg))

    def test_a_document_with_no_status_heading_cannot_be_frozen(self):
        ws = _Workspace(self)
        ws.write_prereg("# only a rule\n")
        with self.assertRaises(ValueError):
            tlr.prereg_rule_sha256(ws.prereg)


class VerifyRecordedTest(unittest.TestCase):
    def test_an_intact_record_verifies(self):
        ws = _Workspace(self)
        ws.good(self)
        ok, message, result = ws.verify()
        self.assertTrue(ok, message)
        self.assertEqual(result["verdict"], "NOT_ADOPT")

    def test_no_artifact_means_no_record(self):
        ws = _Workspace(self)
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("does not exist", message)

    def test_unreadable_artifact_means_no_record(self):
        ws = _Workspace(self)
        with open(ws.artifact, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("unreadable", message)

    def test_editing_the_rule_after_the_read_voids_it(self):
        ws = _Workspace(self)
        ws.good(self)
        ws.write_prereg(PREREG_TEXT.replace("95th", "90th"))
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("edited after it was read", message)

    def test_changing_the_registered_constants_voids_it(self):
        ws = _Workspace(self)
        ws.good(self)
        changed = dict(_constants(), STRONG_PERCENTILE=90)
        ok, message, _ = tlr.verify_recorded(
            artifact_path=ws.artifact, registry_path=ws.registry,
            prereg_path=ws.prereg, ladder_module=_ladder_stub(changed))
        self.assertFalse(ok)
        self.assertIn("constants differ", message)

    def test_a_missing_registry_row_voids_it(self):
        ws = _Workspace(self)
        result = _result(tlr.prereg_rule_sha256(ws.prereg))
        ws.write_artifact(result)  # artifact exists, registry never told
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("no verdict row", message)

    def test_altering_the_artifact_after_registering_it_voids_it(self):
        ws = _Workspace(self)
        result = ws.good(self)
        tampered = copy.deepcopy(result)
        tampered["failed_checks"] = []
        ws.write_artifact(tampered)
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("no verdict row", message)

    def test_a_recorded_adopt_is_never_an_all_clear(self):
        ws = _Workspace(self)
        ws.good(self, verdict="ADOPT")
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("ADOPTS", message)

    def test_a_not_answerable_read_is_a_wait_not_a_record(self):
        ws = _Workspace(self)
        ws.good(self, verdict="NOT_ANSWERABLE")
        ok, message, _ = ws.verify()
        self.assertFalse(ok)
        self.assertIn("not a recordable", message)

    def test_a_record_for_another_rule_does_not_count(self):
        ws = _Workspace(self)
        result = _result(tlr.prereg_rule_sha256(ws.prereg))
        result["rule_id"] = "SOMETHING_ELSE"
        ws.write_artifact(result)
        ws.register()
        ok, _message, _ = ws.verify()
        self.assertFalse(ok)

    def test_the_recorded_line_says_the_threshold_is_unchanged(self):
        line = tlr.recorded_line(_result("x"))
        self.assertTrue(line.startswith("RECORDED:"))
        self.assertIn("NOT_ADOPT", line)
        self.assertIn("unchanged at 3 families", line)
        self.assertIn(tlr.DECISION_NOTE, line)
        self.assertNotIn("ESCALATE", line)


class WriteOnceTest(unittest.TestCase):
    def test_a_read_is_never_overwritten(self):
        ws = _Workspace(self)
        tlr.write_artifact({"a": 1}, path=ws.artifact)
        with self.assertRaises(FileExistsError):
            tlr.write_artifact({"a": 2}, path=ws.artifact)
        with open(ws.artifact, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"a": 1})


class RegistryRowTest(unittest.TestCase):
    def test_registering_adds_an_audit_and_no_hypothesis(self):
        ws = _Workspace(self)
        result = _result(tlr.prereg_rule_sha256(ws.prereg))
        result["read"].update({"usable_dates": ["2026-08-31", "2026-10-15"]})
        result["registered_report"].update({"split_half_disagreement": 2})
        result["ladder_the_null_produces"] = {"STRONG": 16, "BUILDING": 11,
                                              "THIN": 6}
        result["registration"].update(
            {"commit": tlr.PREREG_COMMIT, "committed_utc": tlr.PREREG_COMMIT_UTC})
        tlr.write_artifact(result, path=ws.artifact)
        tlr.register_read(result, artifact_path=ws.artifact,
                          registry_path=ws.registry,
                          read_utc="2026-10-17T00:00:00+00:00")
        rows = alpha_registry.read_all(path=ws.registry)
        self.assertEqual([r["kind"] for r in rows], ["audit", "verdict"])
        counts = alpha_registry.public_research_counts(path=ws.registry)
        self.assertEqual(counts["hypotheses"], 0)
        searched = alpha_registry.total_searched(path=ws.registry)
        self.assertEqual(searched["audits"], 1)
        self.assertEqual(searched["read"], 1)
        # and the verdict row names the artifact, so the verifier can find it
        self.assertIn(tlr.file_sha256(ws.artifact), rows[1]["note"])
        # a second registration of the same read is refused
        with self.assertRaises(alpha_registry.AppendOnlyError):
            tlr.register_read(result, artifact_path=ws.artifact,
                              registry_path=ws.registry)


class CheckedInRecordTest(unittest.TestCase):
    """The state the daily loop will actually read, as committed."""

    def test_the_checked_in_read_verifies_against_the_checked_in_rule(self):
        ok, message, result = tlr.verify_recorded()
        self.assertTrue(ok, message)
        self.assertEqual(result["verdict"], "NOT_ADOPT")
        self.assertFalse(result["consequence"].get("live_threshold_changed"))

    def test_the_read_did_not_move_the_live_threshold(self):
        from src.engine import slip
        self.assertEqual(slip.EVIDENCE_STRONG_MIN_FAMILIES, 3)

    def test_the_read_touched_no_outcome(self):
        _ok, _message, result = tlr.verify_recorded()
        self.assertIs(result["read"]["outcomes_read"], False)
        self.assertGreaterEqual(result["read"]["usable_dates"][0], "2026-08-28")

    def test_the_read_was_answerable_not_a_wait(self):
        _ok, _message, result = tlr.verify_recorded()
        self.assertGreaterEqual(result["read"]["n_usable_dates"],
                                result["instrument"]["constants"]["MIN_DATES"])

    def test_the_decision_note_the_record_points_at_exists(self):
        _ok, _message, result = tlr.verify_recorded()
        path = os.path.join(REPO, result["consequence"]["decision_note"])
        self.assertTrue(os.path.isfile(path), path)


class BatteryReadJudgeabilityTest(unittest.TestCase):
    """Settlement hands the battery {date, won, implied} and nothing else."""

    @staticmethod
    def _rows(n):
        return [{"date": f"2026-09-{1 + i % 25:02d}", "won": i % 2 == 0,
                 "implied": 0.5} for i in range(n)]

    def test_only_extreme_removal_can_be_judged_on_date_won_implied(self):
        result = battery.run(self._rows(60))
        judged, unjudged = rbr.judged_fatal_rules(result)
        self.assertEqual(judged, ["extreme_removal"])
        self.assertEqual(set(unjudged), {"season_split", "team_concentration",
                                         "book_concentration",
                                         "dose_response"})

    def test_a_pass_that_judged_nothing_is_called_vacuous(self):
        # 31 rows: dropping the most influential date leaves < 30, so even
        # extreme_removal cannot read an effect.
        result = battery.run(self._rows(31))
        judged, unjudged = rbr.judged_fatal_rules(result)
        self.assertEqual(judged, [])
        self.assertIn("extreme_removal", unjudged)
        self.assertTrue(result["survives"] and result["ran"])

    def test_a_battery_that_did_not_run_judges_nothing(self):
        result = battery.run(self._rows(10))
        self.assertFalse(result["ran"])
        judged, _ = rbr.judged_fatal_rules(result)
        self.assertEqual(judged, [])


if __name__ == "__main__":
    unittest.main()
