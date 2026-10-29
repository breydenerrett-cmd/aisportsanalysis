import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.research import tennis_comeback as tc


def row(**kw):
    base = {"date": "10/05/2024", "comment": "Completed", "best of": 3, "w1": 6, "l1": 4, "wsets": 2, "lsets": 0,
            "psw": 1.5, "psl": 2.7, "tour": "ATP"}
    base.update(kw)
    return base


class T(unittest.TestCase):
    def test_wilson_and_model(self):
        lo, hi = tc.wilson(5, 10)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        self.assertEqual(tc.wilson(0, 0), (None, None))
        for bo in (3, 5):
            p = tc.solve_set_prob(0.75, bo)
            self.assertAlmostEqual(tc.match_prob(p, bo), 0.75, places=9)
        self.assertAlmostEqual(tc.model_comeback(0.5, 3), 0.25, places=6)
        self.assertAlmostEqual(tc.model_comeback(0.5, 5), 0.5 ** 3 * (4 - 1.5), places=6)

    def test_price(self):
        self.assertEqual(tc.min_live_price(0.5), 106)
        self.assertLess(tc.min_live_price(0.8), 0)
        self.assertIsNone(tc.min_live_price(None))

    def test_clean_drops(self):
        self.assertEqual(tc.clean_match(row(comment="Retired"))[1], "retirement_or_walkover")
        self.assertEqual(tc.clean_match(row(comment="Walkover"))[1], "retirement_or_walkover")
        self.assertEqual(tc.clean_match(row(psw=None, psl=None))[1], "no_odds")
        self.assertEqual(tc.clean_match(row(psw=2.0, psl=2.0))[1], "pick_em_no_favourite")
        self.assertEqual(tc.clean_match(row(date="15/03/2026"))[1], "sealed_dates")
        self.assertEqual(tc.clean_match(row(wsets=1))[1], "set_count_contradicts_best_of")

    def test_fav_and_avg_fallback(self):
        rec, _ = tc.clean_match(row(psw=None, psl=None, avgw=1.5, avgl=2.7))
        self.assertEqual(rec["odds_src"], "Avg")
        self.assertTrue(rec["fav_won_match"])
        self.assertTrue(rec["fav_won_set1"])
        rec, _ = tc.clean_match(row(psw=2.7, psl=1.5))
        self.assertFalse(rec["fav_won_match"])
        self.assertFalse(rec["fav_won_set1"])
        rec, _ = tc.clean_match(row(w1=3, l1=6))
        self.assertTrue(rec["fav_won_match"])
        self.assertFalse(rec["fav_won_set1"])

    def test_table_cells(self):
        rows = [row(w1=3, l1=6)] * 3 + [row(psw=2.7, psl=1.5)] * 2 + [row(comment="Retired")] + [row()] * 4
        t = tc.build_table(rows)
        self.assertEqual(t["drops"], {"retirement_or_walkover": 1})
        c = t["cells"][0]
        self.assertEqual((c["tour"], c["best_of"], c["band"]), ("ATP", 3, "60-65%"))
        self.assertEqual((c["matches"], c["n_lost_set1"], c["won_match"]), (9, 5, 3))
        self.assertIsNone(c["min_live_price_point"])
        self.assertFalse(c["n_floor_met"])

    def test_build_no_input_and_problems(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            raw.mkdir()
            res = tc.build(raw, Path(d) / "o.json", Path(d) / "o.md")
            self.assertEqual(res["status"], "no_input")
            self.assertIn("No table was built", (Path(d) / "o.md").read_text(encoding="utf-8"))
            (raw / "unknown.xlsx").write_bytes(b"x")
            (raw / "atp_2026.xlsx").write_bytes(b"x")
            (raw / "wta_2020.zip").write_bytes(b"not a zip")
            res = tc.build(raw, Path(d) / "o.json", Path(d) / "o.md", write=False)
            self.assertEqual(len(res["data_problems"]), 3)

    def test_xlsx_zip_roundtrip(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Date", "Comment", "Best of", "W1", "L1", "Wsets", "Lsets", "PSW", "PSL"])
        for _ in range(31):
            ws.append(["10/05/2024", "Completed", 3, 3, 6, 2, 1, 1.5, 2.7])
        buf = io.BytesIO()
        wb.save(buf)
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w") as z:
            z.writestr("2024.xlsx", buf.getvalue())
            z.writestr("evil.py", "raise SystemExit")
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw" / "wta"
            raw.mkdir(parents=True)
            (raw / "2024.zip").write_bytes(zbuf.getvalue())
            res = tc.build(Path(d) / "raw", Path(d) / "o.json", Path(d) / "o.md")
            self.assertEqual(res["status"], "ok")
            c = res["cells"][0]
            self.assertEqual((c["tour"], c["n_lost_set1"], c["won_match"]), ("WTA", 31, 31))
            self.assertIsNotNone(c["min_live_price_point"])
            self.assertIn("Headline", (Path(d) / "o.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
