import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.research import live_tennis_calibration as cal

A, B = "Alpha", "Beta"


def ev(eid, commence, prices_by_book):
    return {"id": eid, "commence_time": commence, "home_team": A, "away_team": B,
            "bookmakers": [{"key": k, "markets": [{"key": "h2h", "outcomes": [
                {"name": A, "price": pa}, {"name": B, "price": pb}]}]} for k, (pa, pb) in prices_by_book.items()]}


def write_snap(d, ts, events, sport="tennis_atp_x"):
    stamp = ts.replace("-", "").replace(":", "")
    (Path(d) / f"{sport}__{stamp}.json").write_text(json.dumps(
        {"sport": sport, "requested": ts, "usage": {"last": 20, "remaining": 90000},
         "payload": {"timestamp": ts, "data": events}}))


class T(unittest.TestCase):
    def test_plan(self):
        snaps = cal.plan_snapshots()
        self.assertLessEqual(len(snaps), 145)
        self.assertEqual(len(snaps) % 14, 0)
        first = snaps[0]
        self.assertEqual(first["utc"], "2025-07-07T09:00:00Z")  # 10:00 BST
        self.assertTrue(all(s["utc"] < "2026" for s in snaps))

    def test_pull_gated_and_resumable(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            snaps = cal.plan_snapshots()[:3]

            def fetch(ts, sport):
                calls.append(ts)
                return {"timestamp": ts, "data": []}, {"remaining": 90000, "last": 20, "used": 1}
            logged = []
            log = lambda *a, **k: logged.append((a, k))
            self.assertEqual(cal.run_pull(fetch, d, "x", env={}, out=lambda *_: None, snapshots=snaps, log=log), 0)
            self.assertEqual(calls, [])
            env = {"TENNIS_CAL_PULL": "on"}
            cal.run_pull(fetch, d, "x", env=env, out=lambda *_: None, snapshots=snaps, log=log)
            self.assertEqual(len(calls), 3)
            self.assertEqual(logged[0][1]["budget_band"], "live_odds")
            cal.run_pull(fetch, d, "x", env=env, out=lambda *_: None, snapshots=snaps, log=log)
            self.assertEqual(len(calls), 3)

    def test_pull_stops_on_floor_and_cap(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []

            def low(ts, sport):
                calls.append(ts)
                return {"timestamp": ts, "data": []}, {"remaining": 79999, "last": 20, "used": 1}
            cal.run_pull(low, d, "x", env={"TENNIS_CAL_PULL": "on"}, out=lambda *_: None,
                         snapshots=cal.plan_snapshots()[:5], log=lambda *a, **k: True)
            self.assertEqual(len(calls), 1)
        with tempfile.TemporaryDirectory() as d:
            calls = []

            def pricey(ts, sport):
                calls.append(ts)
                return {"timestamp": ts, "data": []}, {"remaining": 90000, "last": 1500, "used": 1}
            cal.run_pull(pricey, d, "x", env={"TENNIS_CAL_PULL": "on"}, out=lambda *_: None,
                         snapshots=cal.plan_snapshots()[:6], log=lambda *a, **k: True)
            self.assertEqual(len(calls), 2)  # 40+1500+1500 is past 3000

    def test_build_settled_favourite_comeback(self):
        c = "2025-07-07T12:00:00Z"
        with tempfile.TemporaryDirectory() as d:
            write_snap(d, "2025-07-07T11:00:00Z", [ev("e1", c, {"pinnacle": (-200, 170), "b2": (-190, 160)})])
            write_snap(d, "2025-07-07T13:00:00Z", [ev("e1", c, {"b1": (120, -140), "b2": (130, -150)})])
            write_snap(d, "2025-07-07T14:00:00Z", [ev("e1", c, {"b1": (-2000, 1000), "b2": (-1800, 900)})])
            recs = cal.build_events(cal.load_snapshots(d))
            self.assertEqual(len(recs), 1)
            r = recs[0]
            self.assertEqual(r["favourite"], A)
            self.assertEqual(r["prematch_source"], "pinnacle")
            self.assertEqual(r["status"], "settled")
            self.assertEqual(r["winner"], A)
            self.assertEqual(r["band"], "+100..+149")
            self.assertEqual(r["first_hit"]["price"], 125)
            self.assertTrue(r["fav_won"])
            row = [b for b in cal.band_table(recs) if b["band"] == "+100..+149"][0]
            self.assertEqual((row["n"], row["wins"]), (1, 1))
            self.assertAlmostEqual(row["flat_1u_roi"], 1.25, places=6)

    def test_unsettled_never_guessed_and_sealed_skipped(self):
        c = "2025-07-07T12:00:00Z"
        with tempfile.TemporaryDirectory() as d:
            write_snap(d, "2025-07-07T11:00:00Z", [ev("e1", c, {"b1": (-200, 170)}),
                                                   ev("e2", "2026-02-01T12:00:00Z", {"b1": (-200, 170)})])
            write_snap(d, "2025-07-07T13:00:00Z", [ev("e1", c, {"b1": (110, -130)})])
            recs = cal.build_events(cal.load_snapshots(d))
            self.assertEqual([r["event_id"] for r in recs], ["e1"])
            self.assertEqual(recs[0]["status"], "unsettled")
            self.assertIsNone(recs[0]["winner"])
            self.assertEqual(sum(b["n"] for b in cal.band_table(recs)), 0)

    def test_build_writes_files_and_doc_language(self):
        with tempfile.TemporaryDirectory() as d:
            write_snap(d, "2025-07-07T11:00:00Z", [ev("e1", "2025-07-07T12:00:00Z", {"b1": (-200, 170)})])
            ej, doc = Path(d) / "e.json", Path(d) / "d.md"
            self.assertEqual(cal.run_build(d, ej, doc, out=lambda *_: None), 0)
            self.assertEqual(json.loads(ej.read_text())["version"], "tennis_live_calibration_v1")
            text = doc.read_text()
            self.assertIn("sample is small", text)
            self.assertIn("No edge is claimed", text)
            self.assertIn("5 minutes", text)

    def test_wilson(self):
        lo, hi = cal.wilson(5, 10)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        self.assertEqual(cal.wilson(0, 0), (None, None))


if __name__ == "__main__":
    unittest.main()
