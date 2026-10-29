import json
import tempfile
import unittest
from pathlib import Path

from src.research import live_tennis_calibration as cal
from tests.test_live_tennis_calibration import ev, write_snap


class PlanV2(unittest.TestCase):
    def test_plan_shape_and_budget(self):
        snaps = cal.plan_snapshots_v2()
        self.assertEqual(len(snaps), 145)
        self.assertEqual(len(snaps) * cal.CREDITS_PER_SNAPSHOT, 2900)
        self.assertEqual(len({(s["sport"], s["utc"]) for s in snaps}), 145)
        self.assertTrue(all(s["utc"][:4] in ("2024", "2025") for s in snaps))
        self.assertTrue(snaps[0]["local"].endswith("10:45"))
        self.assertEqual(int(snaps[1]["utc"][14:16]) % 15, 0)
        self.assertNotEqual(snaps[0]["utc"], snaps[1]["utc"])

    def test_keys_are_proven_ones_only(self):
        v1 = {s for s, *_ in cal.TOURNAMENT_DAYS}
        for c in _cands():
            self.assertIn(c["sport"], v1)

    def test_choice_is_deterministic_hedged_and_slams(self):
        a, b = cal.choose_v2_blocks(), cal.choose_v2_blocks()
        self.assertEqual([c["sport"] + c["date"] for c in a], [c["sport"] + c["date"] for c in b])
        self.assertEqual(len({c["tournament"] for c in a}), 4)
        self.assertEqual({c["year"] for c in a}, {2024, 2025})
        self.assertTrue(all(c["kind"] == "slam" and c["round"] in ("R1", "R2") for c in a))

    def test_utc_offsets(self):
        snaps = cal.plan_snapshots_v2()
        au = next(s for s in snaps if "aus_open" in s["sport"])
        self.assertEqual(au["utc"], "2024-01-14T23:45:00Z")  # 10:45 AEDT on Jan 15
        us = next(s for s in snaps if s["sport"].endswith("_us_open"))
        self.assertEqual(us["utc"], "2025-08-26T14:45:00Z")  # 10:45 EDT

    def test_expected_funnel_is_monotone(self):
        e = cal.expected_v2()
        for name in ("low", "central", "high"):
            self.assertGreaterEqual(e[name]["listed"], e[name]["settled"])
            self.assertGreaterEqual(e[name]["settled"], e[name]["banded"])
        self.assertLess(e["low"]["banded"], e["central"]["banded"])
        self.assertLess(e["central"]["banded"], e["high"]["banded"])

    def test_cache_dir_separate_from_v1(self):
        self.assertNotEqual(cal.V2_CACHE_DIR, cal.CACHE_DIR)
        self.assertNotIn(cal.CACHE_DIR, cal.V2_CACHE_DIR.parents)

    def test_cli_and_plan_output(self):
        lines = []
        self.assertEqual(cal.main("plan", out=lines.append, plan="v2"), 0)
        self.assertIn("145 snapshots, 2900 credits", lines[0])
        v1 = []
        cal.main("plan", out=v1.append)
        self.assertIn("140 snapshots", v1[0])
        self.assertEqual(cal.main("plan", plan="v3"), 2)


def _cands():
    return [c for c in cal._v2_candidates() if c["tour"] == "atp" or c["kind"] == "slam"]


class PullV2(unittest.TestCase):
    def test_gate_off_requests_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            rc = cal.run_pull_v2(fetch=lambda *a: calls.append(a), cache_dir=d, env={}, out=lambda m: None,
                                 log=lambda *a, **k: None)
            self.assertEqual((rc, calls, list(Path(d).iterdir())), (0, [], []))

    def test_floor_75000_and_caller(self):
        with tempfile.TemporaryDirectory() as d:
            logged, calls, out = [], [], []
            usage = [{"last": 20, "remaining": 80000}, {"last": 20, "remaining": 74990}, {"last": 20, "remaining": 74970}]

            def fetch(ts, sport):
                calls.append(ts)
                return {"timestamp": ts, "data": [ev("e1", "2024-01-15T12:00:00Z", {"pinnacle": (-200, 170)})]}, usage[len(calls) - 1]

            cal.run_pull_v2(fetch=fetch, cache_dir=d, env={cal.ENV_SWITCH: "on"}, out=out.append,
                            log=lambda *a, **k: logged.append((a, k)))
            self.assertEqual(len(calls), 2)  # 74990 < 75000 stops before a third
            self.assertTrue(any("below 75000" in m for m in out))
            self.assertTrue(all(a[2] == cal.V2_CALLER for a, _ in logged))

    def test_run_cap_3000(self):
        with tempfile.TemporaryDirectory() as d:
            n = []

            def fetch(ts, sport):
                n.append(ts)
                return {"timestamp": ts, "data": [ev("e", "2024-01-15T12:00:00Z", {"pinnacle": (-200, 170)})]}, {"last": 1000, "remaining": 99999}

            cal.run_pull_v2(fetch=fetch, cache_dir=d, env={cal.ENV_SWITCH: "on"}, out=lambda m: None,
                            log=lambda *a, **k: None)
            self.assertEqual(len(n), 3)  # 3 x 1000 = 3000, a 4th would pass the cap

    def test_empty_block_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            calls, out = [], []

            def fetch(ts, sport):
                calls.append(ts)
                return {"timestamp": ts, "data": []}, {"last": 20, "remaining": 99999}

            cal.run_pull_v2(fetch=fetch, cache_dir=d, env={cal.ENV_SWITCH: "on"}, out=out.append,
                            log=lambda *a, **k: None)
            self.assertEqual(len(calls), 4 * cal.V2_BLOCKS)  # 4 empty snapshots per block, then moved on
            self.assertTrue(any("skip rest of block" in m for m in out))


class BuildV2(unittest.TestCase):
    def test_combine_dedupes_by_event_id(self):
        v1 = [{"event_id": "x", "commence": "2025-01-01T00:00:00Z", "status": "unsettled", "inplay_snapshots": 1},
              {"event_id": "y", "commence": "2025-01-02T00:00:00Z", "status": "settled", "inplay_snapshots": 2}]
        v2 = [{"event_id": "x", "commence": "2025-01-01T00:00:00Z", "status": "settled", "inplay_snapshots": 6},
              {"event_id": "y", "commence": "2025-01-02T00:00:00Z", "status": "settled", "inplay_snapshots": 2},
              {"event_id": "z", "commence": "2025-01-03T00:00:00Z", "status": "no_inplay"}]
        out = cal.combine_records(v1, v2)
        self.assertEqual([r["event_id"] for r in out], ["x", "y", "z"])
        self.assertEqual(out[0]["status"], "settled")

    def test_build_v2_writes_only_v2_files_and_prints_combined(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for sub in ("v1", "v2", "evid"):
                (d / sub).mkdir()
            for cache in ("v1", "v2"):
                write_snap(d / cache, "2025-01-01T11:00:00Z", [ev("same", "2025-01-01T12:00:00Z", {"pinnacle": (-200, 170)})])
                write_snap(d / cache, "2025-01-01T12:30:00Z", [ev("same", "2025-01-01T12:00:00Z", {"pinnacle": (150, -180)})])
                write_snap(d / cache, "2025-01-01T13:30:00Z", [ev("same", "2025-01-01T12:00:00Z", {"pinnacle": (3000, -9000)})])
            v1_before = sorted(p.read_bytes() for p in (d / "v1").glob("*"))
            out = []
            rc = cal.run_build_v2(cache_dir=d / "v2", v1_cache_dir=d / "v1", evidence_path=d / "evid" / "v2.json",
                                  doc_path=d / "evid" / "v2.md", out=out.append)
            self.assertEqual(rc, 0)
            res = json.loads((d / "evid" / "v2.json").read_text())
            self.assertEqual(res["version"], "tennis_live_calibration_v2")
            self.assertEqual(res["events"], 1)
            self.assertEqual(res["combined"]["events"], 1)  # same id counted once
            self.assertTrue(any(line.startswith("-150..-101") for line in out))
            self.assertIn("Combined with v1", (d / "evid" / "v2.md").read_text())
            self.assertEqual(sorted(p.read_bytes() for p in (d / "v1").glob("*")), v1_before)

    def test_build_v2_no_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cal.run_build_v2(cache_dir=Path(d) / "none", out=lambda m: None), 2)

    def test_output_paths(self):
        self.assertEqual(cal.EVIDENCE_PATH.name, "tennis_live_calibration_v1.json")
        self.assertEqual(cal.V2_EVIDENCE_PATH.name, "tennis_live_calibration_v2.json")
        self.assertEqual(cal.V2_DOC_PATH.name, "TENNIS_LIVE_CALIBRATION_V2.md")


if __name__ == "__main__":
    unittest.main()
