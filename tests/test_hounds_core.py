"""The referee and the contract: boundaries, not just happy paths.

Every threshold asserted here is quoted from docs/PREREG_HOUND_VERDICT.md; a
change to one is a change to that document first.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import unittest
from pathlib import Path

from src.hounds import NOT_ADVICE, contract, verdict as vd

ROOT = Path(__file__).resolve().parent.parent


def points(n_dates, per_date, value_fn):
    """``[(date, pts)]`` over ``n_dates`` dates with ``per_date`` bets each."""
    out = []
    for d in range(n_dates):
        day = f"2026-09-{1 + d:02d}" if d < 28 else f"2026-10-{d - 27:02d}"
        for k in range(per_date):
            out.append((day, value_fn(d, k)))
    return out


class VerdictBoundaries(unittest.TestCase):
    def test_zero_bets_is_too_early(self):
        v = vd.verdict_for([])
        self.assertEqual((v.label, v.n), (vd.TOO_EARLY, 0))
        self.assertIsNone(v.ci_low)

    def test_149_is_too_early_and_150_speaks(self):
        # 149 bets on 30 dates, all +1: not enough, whatever the mean says.
        pts = points(30, 5, lambda d, k: 1.0)[:149]
        v = vd.verdict_for(pts)
        self.assertEqual((v.label, v.n), (vd.TOO_EARLY, 149))
        self.assertAlmostEqual(v.mean_pts, 1.0)
        self.assertIn("149", v.sentence)
        self.assertIn("150", v.sentence)
        v150 = vd.verdict_for(points(30, 5, lambda d, k: 1.0))
        self.assertEqual((v150.label, v150.n), (vd.BEATING_THE_CLOSE, 150))

    def test_paying_the_vig_when_interval_entirely_below_zero(self):
        v = vd.verdict_for(points(30, 5, lambda d, k: -1.0))
        self.assertEqual(v.label, vd.PAYING_THE_VIG)
        self.assertLess(v.ci_high, 0)
        self.assertIn("worse than the closing market", v.sentence)

    def test_interval_spanning_zero_is_no_different(self):
        v = vd.verdict_for(points(30, 5, lambda d, k: 1.0 if (d + k) % 2 else -1.0))
        self.assertEqual(v.label, vd.NO_DIFFERENT)
        self.assertIn("cannot be told apart from zero", v.sentence)

    def test_low_bound_exactly_zero_is_not_beating(self):
        # CI [0, 0] (mean exactly 0): neither "entirely above" nor "below".
        v = vd.verdict_for(points(25, 6, lambda d, k: 1.0 if k % 2 else -1.0))
        self.assertEqual(v.label, vd.NO_DIFFERENT)

    def test_one_date_cannot_have_an_interval(self):
        v = vd.verdict_for([("2026-09-01", 1.0)] * 400)
        self.assertEqual(v.label, vd.TOO_EARLY)
        self.assertIsNone(v.ci_low)

    def test_label_never_reads_units(self):
        # The verdict API has no units parameter at all: pin that.
        import inspect
        self.assertEqual(list(inspect.signature(vd.verdict_for).parameters), ["points"])

    def test_not_measured_label_exists_and_labels_are_closed(self):
        self.assertEqual(set(vd.LABELS), {
            "TOO EARLY", "BEATING THE CLOSE", "PAYING THE VIG",
            "NO DIFFERENT FROM THE MARKET", "NOT MEASURED"})
        self.assertEqual(vd.not_measured_verdict("why").label, vd.NOT_MEASURED)


class BootstrapParity(unittest.TestCase):
    def test_matches_the_project_clustered_bootstrap(self):
        """Same RNG, sorted dates, percentile indices: same interval."""
        from src.model import discovery
        rng = random.Random(7)
        pts = [(f"2026-09-{1 + (i % 25):02d}", rng.gauss(0.3, 3.0)) for i in range(260)]
        mine = vd.clustered_ci(vd.per_date_sums(pts))
        rows = [{"date": d, "v": v} for d, v in pts]
        theirs = discovery.clustered_bootstrap(
            rows, lambda s: sum(r["v"] for r in s) / len(s))
        self.assertAlmostEqual(mine[0], theirs["low"], places=4)
        self.assertAlmostEqual(mine[1], theirs["high"], places=4)

    def test_constants_are_the_projects(self):
        from src.model import discovery
        self.assertEqual(vd.BOOTSTRAP_RESAMPLES, discovery.BOOTSTRAP_RESAMPLES)
        self.assertEqual(vd.BOOTSTRAP_SEED, discovery.BOOTSTRAP_SEED)


class UnitsLine(unittest.TestCase):
    def test_threshold_is_1000(self):
        self.assertIn("say nothing", vd.units_note(0))
        self.assertIn("say nothing", vd.units_note(999))
        self.assertNotIn("say nothing", vd.units_note(1000))
        self.assertIn("never change the label", vd.units_note(1000))


class StatusRules(unittest.TestCase):
    def test_benched_after_seven_days_not_before(self):
        self.assertEqual(vd.status_for("2026-10-10", "2026-10-17"), vd.STATUS_RUNNING)
        self.assertEqual(vd.status_for("2026-10-09", "2026-10-17"), vd.STATUS_BENCHED)

    def test_retired_wins_over_benched_and_no_bets_is_benched(self):
        self.assertEqual(vd.status_for("2026-01-01", "2026-10-17", retired=True),
                         vd.STATUS_RETIRED)
        self.assertEqual(vd.status_for(None, "2026-10-17"), vd.STATUS_BENCHED)


class RetirementMechanics(unittest.TestCase):
    def test_units_threshold_is_strict(self):
        at = [("2026-09-01", -25.0), ("2026-09-02", -24.0)]
        self.assertIsNone(vd.find_retirement(at, []))
        below = [("2026-09-01", -10.0), ("2026-09-02", -25.01), ("2026-09-03", -30.0)]
        self.assertEqual(vd.find_retirement(below, []),
                         ("2026-09-02", vd.CAUSE_UNITS))

    def test_retirement_is_the_first_day_and_sticky(self):
        # Dips below, recovers: still retired, dated to the dip.
        days = [("2026-09-01", -26.0), ("2026-09-02", 5.0), ("2026-09-03", 40.0)]
        self.assertEqual(vd.find_retirement(days, [])[0], "2026-09-01")

    def test_clv_rule_needs_300_measurable_bets(self):
        days = [(f"2026-09-{d:02d}", 0.0) for d in range(1, 21)]
        pts299 = [(f"2026-09-{1 + i % 20:02d}", -1.0) for i in range(299)]
        self.assertIsNone(vd.find_retirement(days, pts299))
        pts300 = [(f"2026-09-{1 + i % 20:02d}", -1.0) for i in range(300)]
        found = vd.find_retirement(days, pts300)
        self.assertEqual(found[1], vd.CAUSE_CLV)
        self.assertTrue(found[0].startswith("2026-09-"))

    def test_clv_rule_ignores_a_hound_that_is_not_paying_the_vig(self):
        days = [(f"2026-09-{d:02d}", 0.0) for d in range(1, 21)]
        pts = [(f"2026-09-{1 + i % 20:02d}", 1.0 if i % 2 else -1.0) for i in range(400)]
        self.assertIsNone(vd.find_retirement(days, pts))

    def test_units_rule_checked_before_clv_rule_on_the_same_day(self):
        days = [(f"2026-09-{d:02d}", -30.0) for d in range(1, 21)]
        pts = [(f"2026-09-{1 + i % 20:02d}", -1.0) for i in range(400)]
        self.assertEqual(vd.find_retirement(days, pts)[1], vd.CAUSE_UNITS)

    def test_data_after_a_day_cannot_move_that_days_retirement(self):
        days = [("2026-09-01", -26.0)]
        more = days + [("2026-09-02", 100.0)]
        self.assertEqual(vd.find_retirement(days, []), vd.find_retirement(more, []))


class ContractShapes(unittest.TestCase):
    SUMMARY_KEYS = {
        "id", "name", "tagline", "kind", "category", "style", "owner_display",
        "sports", "markets", "rule_text", "status", "retired", "record", "clv",
        "verdict", "first_bet_utc", "last_bet_utc", "verified", "verified_share",
        "checkable_share", "replay", "spark", "spark_basis", "source", "persona", "form", "open_bets",
        "settled", "ranked"}

    def test_summary_keys_and_nested_record(self):
        s = contract.to_json(contract.HoundSummary(id="x", name="X"))
        self.assertEqual(set(s), self.SUMMARY_KEYS)
        self.assertEqual(set(s["record"]), {
            "bets", "wins", "losses", "pushes", "voids",
            "units_recorded_price", "units_average_price"})
        self.assertIsNone(s["record"]["units_average_price"])
        self.assertEqual(set(s["verdict"]), {"label", "sentence", "units_note", "n"})
        json.dumps(s)

    def test_series_point_and_bet_row_keys(self):
        p = contract.to_json(contract.SeriesPoint("2026-10-01", None, 0.0, 0, None))
        self.assertEqual(set(p), {"date", "cum_units_average_price",
                                  "cum_units_recorded_price", "bets_settled",
                                  "cum_clv_mean_pts"})
        row = contract.to_json(contract.BetRow(hound_id="x", date="2026-10-01"))
        self.assertTrue({"date", "game", "market", "selection", "price", "book",
                         "consensus_fair", "result", "units", "clv_pts",
                         "who_decided", "reason", "segment"} <= set(row))
        stream = contract.to_json(contract.StreamItem(hound_id="x", date="d"))
        self.assertTrue({"refused", "verdict", "hound_name"} <= set(stream))

    def test_every_payload_is_stamped_paper_only_and_not_advice(self):
        s = contract.HoundSummary(id="x", name="X")
        page = contract.paginate([], 1)
        payloads = [
            contract.leaderboard_payload([s], "2026-10-17"),
            contract.graveyard_payload([s], "2026-10-17"),
            contract.hound_payload(s, [], page, "2026-10-17"),
            contract.bets_payload("x", page, "2026-10-17"),
            contract.stream_payload(page, "2026-10-17"),
            contract.series_payload({"x": []}, "2026-10-17"),
        ]
        for p in payloads:
            self.assertIs(p["paper_only"], True)
            self.assertEqual(p["not_advice"], NOT_ADVICE)
            self.assertIn("as_of", p)
            json.dumps(p)
        self.assertIn("Paper only", payloads[0]["basis"])
        self.assertIn("not advice", payloads[0]["basis"])

    def test_pagination_clamps(self):
        items = list(range(10))
        p = contract.paginate(items, 0, 3)
        self.assertEqual((p["page"], p["page_size"], p["pages"]), (1, 3, 4))
        self.assertEqual(p["items"], [0, 1, 2])
        self.assertEqual(contract.paginate(items, 4, 3)["items"], [9])
        self.assertEqual(contract.paginate(items, 9, 3)["items"], [])
        self.assertEqual(contract.paginate(items, "x", 10_000)["page_size"],
                         contract.MAX_PAGE_SIZE)


class NoFastApiNeeded(unittest.TestCase):
    """Linux CI has no FastAPI: the whole src/hounds package must import
    and run without it (only api/hounds.py needs it)."""

    def test_core_modules_import_with_fastapi_blocked(self):
        code = (
            "import sys\n"
            "sys.modules['fastapi'] = None\n"
            "sys.modules['starlette'] = None\n"
            "import src.hounds.contract, src.hounds.verdict, src.hounds.ledgers,"
            " src.hounds.boards, src.hounds.stats, src.hounds.house\n"
            "print('ok')\n")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ok", out.stdout)


if __name__ == "__main__":
    unittest.main()
