"""Unit tests for scripts/test_parallel.py's serial phase, heartbeat and
overall timeout (fake modules only; never runs the real suite)."""

from __future__ import annotations

import io
import contextlib
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import test_parallel as tp


def _result(modules, *, rc=0, tests=0, failures=0, errors=0, skipped=0,
            timed_out=False):
    return {"modules": modules, "returncode": rc, "tests": tests,
            "failures": failures, "errors": errors, "skipped": skipped,
            "seconds": 0.1, "output": "", "timed_out": timed_out}


class PartitionTests(unittest.TestCase):
    def test_default_serial_pair_is_removed_from_parallel(self):
        mods = ["tests.test_a", "tests.test_daily_bootstrap",
                "tests.test_b", "tests.test_capture_no_set_time"]
        par, ser = tp.partition_serial(mods, tp.DEFAULT_SERIAL_MODULES)
        self.assertEqual(par, ["tests.test_a", "tests.test_b"])
        self.assertEqual(ser, ["tests.test_daily_bootstrap",
                               "tests.test_capture_no_set_time"])

    def test_default_list_names_the_two_flaky_modules(self):
        self.assertEqual(set(tp.DEFAULT_SERIAL_MODULES),
                         {"tests.test_daily_bootstrap",
                          "tests.test_capture_no_set_time"})

    def test_serial_module_not_selected_is_not_invented(self):
        par, ser = tp.partition_serial(["tests.test_a"],
                                       ["tests.test_daily_bootstrap"])
        self.assertEqual((par, ser), (["tests.test_a"], []))

    def test_bare_and_py_names_normalise(self):
        par, ser = tp.partition_serial(
            ["tests.test_a", "tests.test_x"], ["test_x.py", "test_x"])
        self.assertEqual(par, ["tests.test_a"])
        self.assertEqual(ser, ["tests.test_x"])  # de-duplicated

    def test_empty_serial_list_keeps_everything_parallel(self):
        mods = ["tests.test_a", "tests.test_b"]
        self.assertEqual(tp.partition_serial(mods, []), (mods, []))

    def test_partition_loses_and_duplicates_nothing(self):
        mods = [f"tests.test_{i}" for i in range(20)]
        par, ser = tp.partition_serial(mods, ["tests.test_3", "tests.test_7"])
        self.assertEqual(sorted(par + ser), sorted(mods))
        self.assertFalse(set(par) & set(ser))


class AggregateTests(unittest.TestCase):
    def test_totals_count_both_phases(self):
        par = [_result(["a"], tests=10, skipped=1), _result(["b"], tests=5)]
        ser = [_result(["s"], tests=7)]
        agg = tp.aggregate_results(par, ser)
        self.assertEqual(agg["total_tests"], 22)
        self.assertEqual(agg["parallel_tests"], 15)
        self.assertEqual(agg["serial_tests"], 7)
        self.assertEqual(agg["skipped"], 1)
        self.assertEqual(agg["broken"], [])

    def test_serial_failure_makes_the_run_broken(self):
        par = [_result(["a"], tests=10)]
        ser = [_result(["s"], rc=1, tests=7, failures=2, errors=1)]
        agg = tp.aggregate_results(par, ser)
        self.assertEqual(len(agg["broken"]), 1)
        self.assertEqual((agg["failures"], agg["errors"]), (2, 1))
        self.assertEqual(agg["total_tests"], 17)

    def test_timeout_counts_and_is_broken_even_with_zero_failures(self):
        ser = [_result(["s"], rc=tp.TIMEOUT_RETURNCODE, timed_out=True)]
        agg = tp.aggregate_results([], ser)
        self.assertEqual(agg["timeouts"], 1)
        self.assertEqual(len(agg["broken"]), 1)

    def test_parse_unittest_output(self):
        text = ("FAIL: test_x (tests.m.C)\n\nRan 12 tests in 1.5s\n\n"
                "FAILED (failures=2, errors=1, skipped=3)\n")
        self.assertEqual(tp.parse_unittest_output(text),
                         {"tests": 12, "failures": 2, "errors": 1, "skipped": 3})
        self.assertEqual(
            tp.parse_unittest_output("Ran 4 tests in 0.1s\n\nOK\n"),
            {"tests": 4, "failures": 0, "errors": 0, "skipped": 0})


class PhaseTests(unittest.TestCase):
    def test_serial_phase_runs_one_at_a_time_in_order(self):
        live = 0
        peak = 0
        order = []
        lock = threading.Lock()

        def fake(mods, label="x"):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            order.append(mods[0])
            time.sleep(0.02)
            with lock:
                live -= 1
            return _result(mods, tests=1)

        res, rep = tp.run_serial_phase(["m1", "m2", "m3"], None, runner=fake)
        self.assertEqual(order, ["m1", "m2", "m3"])
        self.assertEqual(peak, 1)
        self.assertEqual(len(res), 3)
        self.assertEqual(rep, [])

    def test_serial_phase_not_started_after_deadline(self):
        called = []
        res, rep = tp.run_serial_phase(
            ["m1"], time.perf_counter() - 1, runner=lambda m, label="x": called.append(m))
        self.assertEqual(called, [])
        self.assertTrue(res[0]["timed_out"])
        self.assertNotEqual(res[0]["returncode"], 0)
        self.assertIn("not started", rep[0])

    def test_parallel_phase_returns_results_in_shard_order(self):
        def fake(mods, label="x"):
            time.sleep(0.05 if mods == ["a"] else 0.0)
            return _result(mods, tests=len(mods))

        res, rep = tp.run_parallel_phase([["a"], ["b", "c"]], 2, None, runner=fake)
        self.assertEqual([r["modules"] for r in res], [["a"], ["b", "c"]])
        self.assertEqual(rep, [])

    def test_empty_shards_is_a_noop(self):
        self.assertEqual(tp.run_parallel_phase([], 1, None), ([], []))


class RealSubprocessTests(unittest.TestCase):
    """run_shard against fake on-disk modules (a real `unittest -q` child)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "fk_ok.py").write_text(textwrap.dedent("""
            import unittest
            class T(unittest.TestCase):
                def test_1(self): pass
                def test_2(self): pass
        """))
        (root / "fk_bad.py").write_text(textwrap.dedent("""
            import unittest
            class T(unittest.TestCase):
                def test_1(self): self.fail("boom")
        """))
        (root / "fk_slow.py").write_text(textwrap.dedent("""
            import time, unittest
            class T(unittest.TestCase):
                def test_1(self): time.sleep(60)
        """))
        env = dict(tp._CLEAN_ENV)
        env["PYTHONPATH"] = str(root)
        patcher = mock.patch.object(tp, "_CLEAN_ENV", env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _quiet(self, fn, *a, **k):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            out = fn(*a, **k)
        return out, err.getvalue()

    def test_ok_and_failing_shard_are_parsed(self):
        ok, err = self._quiet(tp.run_shard, ["fk_ok"], label="w")
        self.assertEqual((ok["returncode"], ok["tests"]), (0, 2))
        self.assertIn("w started", err)
        self.assertIn("w finished in", err)
        bad, _ = self._quiet(tp.run_shard, ["fk_bad"], label="w")
        self.assertNotEqual(bad["returncode"], 0)
        self.assertEqual(bad["failures"], 1)
        self.assertIn("FAIL:", bad["output"])

    def test_overall_timeout_names_and_kills_the_slow_shard(self):
        deadline = time.perf_counter() + 3.0
        t0 = time.perf_counter()
        (res, rep), _ = self._quiet(
            tp.run_parallel_phase, [["fk_ok"], ["fk_slow"]], 2, deadline)
        self.assertLess(time.perf_counter() - t0, 30.0)  # did not wait 60 s
        self.assertEqual(res[0]["returncode"], 0)
        self.assertTrue(res[1]["timed_out"])
        self.assertEqual(res[1]["returncode"], tp.TIMEOUT_RETURNCODE)
        self.assertEqual(len(rep), 1)
        self.assertIn("worker 1", rep[0])
        self.assertIn("fk_slow", rep[0])
        agg = tp.aggregate_results(res, [])
        self.assertEqual(agg["timeouts"], 1)
        self.assertEqual(len(agg["broken"]), 1)


if __name__ == "__main__":
    unittest.main()
