"""scripts/probe_slot_prop.py -- the V7 reader, on synthetic rows.

Each test names the mutation it exists to catch. The reader is the
instrument; the instrument is the suspect.
"""

from __future__ import annotations

import unittest

from scripts import probe_slot_prop as probe

POST = "2026-09-12T21:00:00Z"
FIRST_PITCH = "2026-09-12T23:10:00Z"


def _quote(observed, book="fanduel", side="Over", price=-110, player="A B",
           event_id="e1", market="batter_hits", line="0.5", date="2026-09-12",
           commence=FIRST_PITCH):
    return {"game_date": date, "event_id": event_id, "player": player,
            "market": market, "line": line, "side": side, "book": book,
            "price": price, "observed_utc": observed, "commence_time": commence}


def _both_sides(observed, over=-110, under=-110, **kw):
    return [_quote(observed, "fanduel", "Over", over, **kw),
            _quote(observed, "fanduel", "Under", under, **kw),
            _quote(observed, "draftkings", "Over", over, **kw),
            _quote(observed, "draftkings", "Under", under, **kw)]


class TheWindowIsPostLineupOnly(unittest.TestCase):
    POSTED = {"e1": probe.parse_iso(POST)}

    def test_before_the_posting_is_dropped(self):
        rows = [_quote("2026-09-12T20:59:59Z")]
        self.assertEqual(probe.post_lineup_rows(rows, self.POSTED), [])

    def test_at_or_after_the_posting_inside_two_hours_is_kept(self):
        """Posted 21:00, first pitch 23:10: a 21:15 quote is post-lineup and
        115 minutes out; 22:30 is 40 minutes out. Both are in the window."""
        rows = [_quote("2026-09-12T21:15:00Z"), _quote("2026-09-12T22:30:00Z")]
        self.assertEqual(len(probe.post_lineup_rows(rows, self.POSTED)), 2)

    def test_post_lineup_but_still_more_than_two_hours_out_waits(self):
        """Posted 21:00 and quoted at 21:00 -- after the posting, but 130
        minutes before first pitch: the gate has not opened for it yet."""
        rows = [_quote("2026-09-12T21:00:00Z")]
        self.assertEqual(probe.post_lineup_rows(rows, self.POSTED), [])

    def test_more_than_two_hours_out_is_dropped(self):
        """Posted early but observed 2h01m before first pitch: outside."""
        posted = {"e1": probe.parse_iso("2026-09-12T20:00:00Z")}
        rows = [_quote("2026-09-12T21:09:00Z")]
        self.assertEqual(probe.post_lineup_rows(rows, posted), [])

    def test_after_first_pitch_is_dropped(self):
        rows = [_quote("2026-09-12T23:10:01Z")]
        self.assertEqual(probe.post_lineup_rows(rows, self.POSTED), [])

    def test_a_game_with_no_posting_time_anchors_nothing(self):
        rows = [_quote("2026-09-12T22:00:00Z")]
        self.assertEqual(probe.post_lineup_rows(rows, {}), [])


class SlotsAndGroups(unittest.TestCase):

    def test_norm_needs_ten_priors_and_is_the_median_of_the_last_ten(self):
        self.assertIsNone(probe.norm_slot([7] * 9))
        self.assertEqual(probe.norm_slot([1, 1, 1] + [7] * 10), 7)

    def test_moving_up_is_positive(self):
        self.assertEqual(probe.delta_slot(7, 3), 4)
        self.assertEqual(probe.delta_slot(3, 7), -4)

    def test_groups_are_the_registered_bands(self):
        self.assertEqual(probe.group_of(2), "UP")
        self.assertEqual(probe.group_of(5), "UP")
        self.assertEqual(probe.group_of(0), "FLAT")
        self.assertEqual(probe.group_of(-2), "DOWN")
        self.assertIsNone(probe.group_of(1))
        self.assertIsNone(probe.group_of(-1))

    def test_lineups_by_date_reads_order_and_posting_time(self):
        stored = {"101": {"date": "2026-09-12", "game_pk": 101,
                          "observed_utc": POST,
                          "away": [{"name": "A B", "order": 3}],
                          "home": [{"name": "C D"}]}}
        slots, posted = probe.lineups_by_date(stored)
        self.assertEqual(slots["2026-09-12"], {"A B": 3, "C D": 1})
        self.assertEqual(posted[("2026-09-12", "101")], probe.parse_iso(POST))


class FairAndBaseline(unittest.TestCase):

    def test_two_books_both_sides_gives_a_devigged_over(self):
        fair = probe.fair_over_by_key(_both_sides("2026-09-12T22:00:00Z"))
        self.assertEqual(len(fair), 1)
        self.assertAlmostEqual(list(fair.values())[0], 0.5, places=6)

    def test_one_book_is_not_a_fair_price(self):
        rows = [_quote("2026-09-12T22:00:00Z", "fanduel", "Over", -110),
                _quote("2026-09-12T22:00:00Z", "fanduel", "Under", -110)]
        self.assertEqual(probe.fair_over_by_key(rows), {})

    def test_baseline_needs_three_prior_nights_strictly_before(self):
        hist = [("2026-09-09", 0.50), ("2026-09-10", 0.52), ("2026-09-11", 0.54),
                ("2026-09-12", 0.90)]
        self.assertAlmostEqual(probe.baseline_fair(hist, "2026-09-12"), 0.52)
        self.assertIsNone(probe.baseline_fair(hist[:2] + hist[3:], "2026-09-12"))


def _fair_key(date, player, line="0.5", event="e"):
    return (date, f"{event}{date}", player, "batter_hits", line)


class BuildRowsEndToEnd(unittest.TestCase):

    def test_an_up_row_is_scored_against_the_batters_own_history(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 13)]
        # Eleven prior lineups at slot 7, tonight at slot 3; three prior
        # nights of fair Over 0.50 and tonight 0.58.
        slots = {d: {"A B": 7} for d in dates[:-1]}
        slots[dates[-1]] = {"A B": 3}
        fair = {_fair_key(d, "A B"): 0.50 for d in dates[-4:-1]}
        fair[_fair_key(dates[-1], "A B")] = 0.58
        rows, control = probe.build_rows(fair, slots, probe.slot_history(slots))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["group"], "UP")
        self.assertEqual(row["delta"], 4)
        self.assertAlmostEqual(row["dfair"], 0.08)
        self.assertEqual(len(control), 4)

    def test_too_few_priors_or_baseline_nights_scores_nothing(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 6)]
        slots = {d: {"A B": 7} for d in dates}
        fair = {_fair_key(d, "A B"): 0.5 for d in dates}
        rows, _control = probe.build_rows(fair, slots, probe.slot_history(slots))
        self.assertEqual(rows, [])


class TheBootstrapAndTheVerdict(unittest.TestCase):

    def _rows(self, values_by_date):
        return [{"date": d, "dfair": v, "fair": v} for d, vs in values_by_date.items() for v in vs]

    def test_a_clear_separation_confirms_and_its_mirror_does_not(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 21)]
        up = self._rows({d: [0.05, 0.06, 0.04] for d in dates})
        flat = self._rows({d: [0.0, 0.01, -0.01] for d in dates})
        interval = probe.cluster_bootstrap_difference(up, flat, "dfair", 0.01)
        self.assertEqual(probe.verdict_from(interval), "CONFIRMED")
        self.assertGreater(interval[2], 0.04)
        # THE MUTATION THAT MATTERS: the sign. Swapped groups must not confirm.
        swapped = probe.cluster_bootstrap_difference(flat, up, "dfair", 0.01)
        self.assertEqual(probe.verdict_from(swapped), "NOT SUPPORTED")

    def test_no_difference_is_not_supported(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 21)]
        a = self._rows({d: [0.01, -0.01, 0.0] for d in dates})
        b = self._rows({d: [0.0, 0.01, -0.01] for d in dates})
        self.assertEqual(probe.verdict_from(
            probe.cluster_bootstrap_difference(a, b, "dfair", 0.01)), "NOT SUPPORTED")

    def test_empty_groups_are_undetermined_never_a_number(self):
        self.assertIsNone(probe.cluster_bootstrap_difference([], [{"date": "x", "dfair": 1}], "dfair", 0.05))
        self.assertEqual(probe.verdict_from(None), "UNDETERMINED")

    def test_the_seed_makes_the_read_reproducible(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 11)]
        a = self._rows({d: [0.03, 0.02] for d in dates})
        b = self._rows({d: [0.0, 0.01] for d in dates})
        one = probe.cluster_bootstrap_difference(a, b, "dfair", 0.05)
        two = probe.cluster_bootstrap_difference(a, b, "dfair", 0.05)
        self.assertEqual(one, two)


class TheFloorsHold(unittest.TestCase):

    def test_pending_until_every_floor(self):
        self.assertEqual(probe.read_state(149, 150, 100, 100), "PENDING")
        self.assertEqual(probe.read_state(150, 149, 100, 100), "PENDING")
        self.assertEqual(probe.read_state(150, 150, 99, 100), "PENDING")
        self.assertEqual(probe.read_state(150, 150, 100, 100), "READ")

    def test_a_pending_report_carries_counts_and_no_interval(self):
        rows = [{"date": "d", "group": "UP", "dfair": 0.1}] * 3
        out = probe.report(rows, [], 0.01, 42)
        self.assertEqual(out["state"], "PENDING")
        self.assertEqual(out["n_up"], 3)
        self.assertNotIn("primary", out)
        self.assertNotIn("control", out)

    def test_a_failed_control_makes_every_verdict_undetermined(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 31)]
        rows = []
        for d in dates:
            rows += [{"date": d, "group": "UP", "dfair": 0.05}] * 5
            rows += [{"date": d, "group": "FLAT", "dfair": 0.0}] * 5
            rows += [{"date": d, "group": "DOWN", "dfair": -0.05}] * 2
        # Control: top and bottom priced identically -- the instrument sees nothing.
        control = []
        for d in dates:
            control += [{"date": d, "slot": 1, "fair": 0.5, "line": "0.5"}] * 4
            control += [{"date": d, "slot": 9, "fair": 0.5, "line": "0.5"}] * 4
        out = probe.report(rows, control, 0.01, 42)
        self.assertEqual(out["state"], "READ")
        self.assertEqual(out["control"]["verdict"], "NOT SUPPORTED")
        self.assertEqual(out["primary"]["verdict"], "UNDETERMINED")
        self.assertIn("evidence of absence", out["note"])

    def test_a_passing_control_lets_the_primary_speak(self):
        dates = [f"2026-09-{d:02d}" for d in range(1, 31)]
        rows, control = [], []
        for d in dates:
            rows += [{"date": d, "group": "UP", "dfair": 0.05}] * 5
            rows += [{"date": d, "group": "FLAT", "dfair": 0.0}] * 5
            rows += [{"date": d, "group": "DOWN", "dfair": -0.05}] * 2
            control += [{"date": d, "slot": 1, "fair": 0.60, "line": "0.5"}] * 4
            control += [{"date": d, "slot": 9, "fair": 0.45, "line": "0.5"}] * 4
        out = probe.report(rows, control, 0.01, 42)
        self.assertEqual(out["control"]["verdict"], "CONFIRMED")
        self.assertEqual(out["primary"]["verdict"], "CONFIRMED")
        self.assertEqual(out["mirror"]["verdict"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
