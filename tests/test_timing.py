"""Tests for src/core/timing.py -- the stage() harness and its validator.

WHY THIS FILE EXISTS
---------------------
map-compute-scale.md section 1: "compute is never the bottleneck" was an
unmeasured claim shipping in a published artifact. This pins the instrument
itself: stage() measures without fabricating, require_timings() refuses an
artifact with no evidence, and neither ever touches the content being timed.
"""

from __future__ import annotations

import time
import unittest

from src.core import timing


class TestStage(unittest.TestCase):

    def test_records_a_stage_with_all_required_keys(self):
        collector = timing.TimingCollector()
        with timing.stage("load", collector=collector):
            pass
        self.assertEqual(len(collector.records), 1)
        record = collector.to_list()[0]
        for key in ("stage", "wall_s", "cpu_s", "rows", "decisions",
                   "decisions_per_s", "peak_rss_mb"):
            self.assertIn(key, record)
        self.assertEqual(record["stage"], "load")

    def test_wall_s_is_nonnegative_and_reflects_real_elapsed_time(self):
        collector = timing.TimingCollector()
        with timing.stage("sleep", collector=collector):
            time.sleep(0.02)
        record = collector.to_list()[0]
        self.assertGreaterEqual(record["wall_s"], 0.015)

    def test_peak_rss_mb_is_positive(self):
        collector = timing.TimingCollector()
        with timing.stage("noop", collector=collector):
            pass
        self.assertGreater(collector.to_list()[0]["peak_rss_mb"], 0.0)

    def test_decisions_per_s_computed_when_decisions_given(self):
        collector = timing.TimingCollector()
        with timing.stage("evaluate", collector=collector, decisions=1000):
            time.sleep(0.01)
        record = collector.to_list()[0]
        self.assertIsNotNone(record["decisions_per_s"])
        self.assertAlmostEqual(
            record["decisions_per_s"], 1000 / record["wall_s"], places=6)

    def test_decisions_per_s_is_none_without_a_decision_count(self):
        collector = timing.TimingCollector()
        with timing.stage("write", collector=collector):
            pass
        self.assertIsNone(collector.to_list()[0]["decisions_per_s"])

    def test_rows_is_passed_through_verbatim(self):
        collector = timing.TimingCollector()
        with timing.stage("load", collector=collector, rows=4819):
            pass
        self.assertEqual(collector.to_list()[0]["rows"], 4819)

    def test_multiple_stages_append_in_order(self):
        collector = timing.TimingCollector()
        with timing.stage("a", collector=collector):
            pass
        with timing.stage("b", collector=collector):
            pass
        self.assertEqual([r["stage"] for r in collector.to_list()], ["a", "b"])

    def test_no_collector_given_builds_its_own(self):
        # stage() must be usable for a one-off measurement without forcing
        # every caller to pre-build a TimingCollector.
        with timing.stage("solo") as own:
            pass
        self.assertEqual(len(own.records), 1)

    def test_exception_inside_stage_still_propagates(self):
        # Measuring must never swallow an error from the timed code -- a
        # crashed stage still needs its exception to reach the caller.
        collector = timing.TimingCollector()
        with self.assertRaises(ValueError):
            with timing.stage("boom", collector=collector):
                raise ValueError("boom")
        # The record was still appended (partial timing beats none for
        # diagnosing where a crash happened).
        self.assertEqual(len(collector.records), 1)

    def test_stage_never_mutates_a_value_the_caller_computed(self):
        # The core determinism guarantee: stage() must be side-effect-free
        # with respect to anything computed inside it.
        collector = timing.TimingCollector()
        payload = {"x": 1}
        with timing.stage("compute", collector=collector):
            payload["y"] = payload["x"] + 1
        self.assertEqual(payload, {"x": 1, "y": 2})


class TestRequireTimings(unittest.TestCase):

    def _valid_record(self, stage="load"):
        return {"stage": stage, "wall_s": 0.001, "cpu_s": 0.001,
               "rows": None, "decisions": None, "decisions_per_s": None,
               "peak_rss_mb": 12.0}

    def test_passes_with_at_least_one_well_formed_stage(self):
        artifact = {"timings": [self._valid_record()]}
        timing.require_timings(artifact)  # must not raise

    def test_raises_when_timings_key_is_absent(self):
        with self.assertRaises(timing.TimingError):
            timing.require_timings({"schema": "x/1"})

    def test_raises_when_timings_is_empty(self):
        with self.assertRaises(timing.TimingError):
            timing.require_timings({"timings": []})

    def test_raises_when_timings_is_not_a_list(self):
        with self.assertRaises(timing.TimingError):
            timing.require_timings({"timings": "not-a-list"})

    def test_raises_when_a_record_is_missing_a_required_key(self):
        bad = self._valid_record()
        del bad["wall_s"]
        with self.assertRaises(timing.TimingError):
            timing.require_timings({"timings": [bad]})

    def test_raises_when_a_record_has_an_empty_stage_name(self):
        bad = self._valid_record(stage="")
        with self.assertRaises(timing.TimingError):
            timing.require_timings({"timings": [bad]})

    def test_raises_when_a_record_is_not_a_dict(self):
        with self.assertRaises(timing.TimingError):
            timing.require_timings({"timings": ["not-a-dict"]})

    def test_min_stages_enforced(self):
        artifact = {"timings": [self._valid_record()]}
        with self.assertRaises(timing.TimingError):
            timing.require_timings(artifact, min_stages=2)

    def test_real_stage_output_satisfies_require_timings(self):
        # End-to-end: what stage() actually produces must pass its own
        # validator without any manual reshaping.
        collector = timing.TimingCollector()
        with timing.stage("load", collector=collector, rows=10):
            pass
        with timing.stage("evaluate", collector=collector, decisions=500):
            pass
        timing.require_timings({"timings": collector.to_list()})


if __name__ == "__main__":
    unittest.main()
