"""The V3 primary test: KM correctness, planted effects, censoring, the floor."""

import unittest
from unittest import mock

from src.research import timingreport, timingtest
from tests.test_timingreport import GAMES, _event, _mb_row


def _measured(game_pk, event_iso, game_start_iso, reaction_50):
    """A synthetic eventstudy.measure() result, shaped exactly as
    timingreport.report() now attaches game_pk/game_start_utc to it."""
    return {"excluded": None, "event_time": event_iso, "game_pk": game_pk,
            "game_start_utc": game_start_iso,
            "ladder_minutes": {"25%": None, "50%": reaction_50,
                               "75%": None, "100%": None}}


def _report_result(name, measured_events, measurable=None):
    measurable = len(measured_events) if measurable is None else measurable
    return {"classes": {name: {"measurable": measurable,
                               "measured": measured_events}}}


# Far outside the dense window (> dense.WINDOW_MINUTES before first pitch),
# so every synthetic event below carries the 60-minute hourly floor.
GAME_START = "2026-09-05T00:00:00+00:00"


def _events(reactions, *, start=0):
    """One event per reaction value, each its own game_pk (its own cluster),
    spaced an hour apart across as many days as needed so timestamps never
    collide -- `_rows_for_class` re-sorts by event_time, and a colliding
    timestamp between a `start=0` batch and a later `start=N` batch would
    interleave them on the tie instead of keeping the caller's two batches
    (e.g. "first half slow, second half fast") in their intended halves."""
    out = []
    for offset, reaction in enumerate(reactions):
        i = start + offset
        day, hour = 1 + i // 20, i % 20
        event_iso = f"2026-09-{day:02d}T{hour:02d}:00:00+00:00"
        out.append(_measured(f"g{i}", event_iso, GAME_START, reaction))
    return out


class KaplanMeierTests(unittest.TestCase):
    """Hand-computable textbook example, traced in the module's own docstring
    reasoning: times 1(event), 2(censored), 3(event), 4(event), 5(censored).
    """

    PAIRS = [(1, False), (2, True), (3, False), (4, False), (5, True)]

    def test_survival_steps_match_hand_calculation(self):
        steps = timingtest.km_survival_steps(self.PAIRS)
        times = [t for t, _ in steps]
        survivals = [round(s, 4) for _, s in steps]
        self.assertEqual(times, [1, 3, 4])
        self.assertEqual(survivals, [0.8, 0.5333, 0.2667])

    def test_survival_at_holds_flat_between_steps(self):
        self.assertEqual(timingtest.km_survival_at(self.PAIRS, 0), 1.0)
        self.assertAlmostEqual(timingtest.km_survival_at(self.PAIRS, 1), 0.8)
        self.assertAlmostEqual(timingtest.km_survival_at(self.PAIRS, 2), 0.8)
        self.assertAlmostEqual(
            timingtest.km_survival_at(self.PAIRS, 3), 0.53333, places=4)

    def test_median_is_the_first_crossing_below_half(self):
        self.assertEqual(timingtest.km_median(self.PAIRS), 4)

    def test_no_crossing_means_not_reached(self):
        # Every subject censored: the curve never drops at all.
        self.assertIsNone(timingtest.km_median([(1, True), (2, True)]))

    def test_empty_pairs_is_not_reached(self):
        self.assertIsNone(timingtest.km_median([]))
        self.assertEqual(timingtest.km_survival_at([], 5), 1.0)


class PlantedEffectTests(unittest.TestCase):
    """The test must find nothing when reaction is genuinely fast, and find
    it when reaction is genuinely slow -- against the SAME 60-minute floor
    (every planted event here sits far outside the dense window)."""

    def test_planted_fast_reaction_is_a_null_result(self):
        # 5 minutes to 50%-moved against a 60-minute floor: diff = -55, every
        # single event, no censoring.
        measured = _events([5.0] * 35)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["status"], "tested")
        self.assertEqual(result["censored"], 0)
        self.assertEqual(result["test"]["point_estimate_s0"], 0.0)
        # No resample can show diff > 0 either -- the bootstrap can only
        # redraw from the same uniformly-fast sample.
        self.assertEqual(result["test"]["p_one_sided"], 1.0)
        self.assertLess(result["descriptive"]["complete_case_median_diff_minutes"], 0)

    def test_planted_slow_reaction_is_a_rejection(self):
        # 300 minutes to 50%-moved against a 60-minute floor: diff = +240.
        measured = _events([300.0] * 35)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["test"]["point_estimate_s0"], 1.0)
        self.assertEqual(result["test"]["p_one_sided"], 0.0)
        self.assertEqual(result["test"]["ci95_s0"], {"low": 1.0, "high": 1.0})
        self.assertGreater(
            result["descriptive"]["complete_case_median_diff_minutes"], 0)

    def test_a_genuinely_mixed_sample_lands_between_the_extremes(self):
        # Half fast (diff -55), half slow (diff +240): S(0) should land near
        # 0.5, not saturate at either boundary, and the CI should not be a
        # single point the way the two pure cases above are.
        measured = _events([5.0] * 18 + [300.0] * 18)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        s0 = result["test"]["point_estimate_s0"]
        self.assertGreater(s0, 0.0)
        self.assertLess(s0, 1.0)
        self.assertNotEqual(result["test"]["ci95_s0"]["low"],
                            result["test"]["ci95_s0"]["high"])


class CensoringTests(unittest.TestCase):
    def test_censored_events_are_counted_and_never_silently_dropped(self):
        measured = (_events([300.0] * 20, start=0)
                   + _events([None] * 15, start=20))
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["used_for_test"], 35)
        self.assertEqual(result["observed"], 20)
        self.assertEqual(result["censored"], 15)
        self.assertAlmostEqual(result["censored_fraction"], 15 / 35, places=4)

    def test_km_reaction_median_is_never_below_the_complete_case_one(self):
        """Dropping the slow (censored) tail can only bias the complete-case
        median DOWN; the KM estimate that folds it back in must be at least
        as large."""
        measured = (_events([100.0] * 20, start=0)
                   + _events([None] * 15, start=20))
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        cc = result["descriptive"]["complete_case_median_reaction_minutes"]
        km = result["descriptive"]["km_median_reaction_minutes"]
        self.assertIsNotNone(cc)
        if km is not None:
            self.assertGreaterEqual(km, cc)

    def test_all_censored_reads_not_reached_rather_than_a_fabricated_number(self):
        measured = _events([None] * 35)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["observed"], 0)
        self.assertIsNone(result["descriptive"]["km_median_reaction_minutes"])
        self.assertIsNone(result["descriptive"]["complete_case_median_reaction_minutes"])
        # S(0) is still well-defined (no death recorded anywhere, so no
        # evidence AGAINST H1 either) -- reported as 1.0, not skipped.
        self.assertEqual(result["test"]["point_estimate_s0"], 1.0)


class FloorTests(unittest.TestCase):
    def test_below_floor_refuses_to_read_the_measured_list(self):
        # `measured` is deliberately a sentinel that would raise if iterated
        # or indexed -- the refusal must happen before any such access.
        class _PoisonList:
            def __iter__(self):
                raise AssertionError("below-floor path touched the events")

        report_result = {"classes": {"lineup_posted": {
            "measurable": 29, "measured": _PoisonList()}}}
        result = timingtest.test_class(
            "lineup_posted", report_result=report_result)
        self.assertEqual(result["status"], "below floor")
        self.assertEqual(result["measurable_events"], 29)
        self.assertEqual(result["floor"], 30)
        self.assertNotIn("test", result)
        self.assertNotIn("descriptive", result)

    def test_unknown_class_is_named_rather_than_raising(self):
        result = timingtest.test_class(
            "nonexistent", report_result={"classes": {}})
        self.assertIn("unknown class", result["status"])

    def test_test_all_leaves_every_below_floor_class_unread(self):
        report_result = {"classes": {
            "starter_scratch": {"measurable": 2, "measured": None},
            "hitter_scratch": {"measurable": 29, "measured": None}}}
        results = timingtest.test_all(report_result=report_result)
        self.assertEqual(results["starter_scratch"]["status"], "below floor")
        self.assertEqual(results["hitter_scratch"]["status"], "below floor")

    def test_too_few_events_survive_join_exclusions_also_refuses(self):
        # 30 measurable events clear the outer floor, but every one of them
        # is missing a mapped game start -- the inner gate must catch this
        # too, since the outer count alone does not guarantee testable rows.
        measured = [dict(_measured(f"g{i}", "2026-09-01T00:00:00+00:00",
                                   GAME_START, 100.0), game_start_utc=None)
                   for i in range(30)]
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["status"],
                         "below floor after join exclusions")
        self.assertEqual(
            result["excluded_before_test"][timingtest.NO_GAME_START], 30)


class ReplicationTests(unittest.TestCase):
    def test_a_consistent_slow_effect_replicates(self):
        measured = _events([300.0] * 40)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["replication"]["verdict"], "replicated")

    def test_a_direction_flip_does_not_replicate(self):
        # First half slow (diff > 0), second half fast (diff < 0): opposite
        # signs must fail replication even though both halves clear the
        # half-floor on their own.
        measured = _events([300.0] * 20) + _events([5.0] * 20, start=20)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertFalse(result["replication"].get("direction_holds", True))
        self.assertEqual(result["replication"]["verdict"], "not replicated")


class BHFDRTests(unittest.TestCase):
    def test_standard_bh_example(self):
        # Textbook check: with q=0.10 and m=4, only p-values at or below
        # their own (rank/m)*q survive, and everything ranked below the
        # largest surviving rank survives with it.
        pvalues = {"a": 0.01, "b": 0.20, "c": 0.03, "d": 0.50}
        result = timingtest.bh_fdr(pvalues, q=0.10)
        self.assertEqual(result["m"], 4)
        self.assertEqual(set(result["significant"]), {"a", "c"})

    def test_no_pvalues_is_the_vacuous_case(self):
        result = timingtest.bh_fdr({})
        self.assertEqual(result, {"q": timingtest.FDR_Q, "m": 0,
                                  "significant": [], "ranked": []})


class IntegrationWithTimingReportTests(unittest.TestCase):
    """End-to-end through the real join (timingreport.report), confirming
    the game_pk / game_start_utc fields it now attaches actually reach here."""

    def test_a_real_join_produces_a_testable_class(self):
        rows = [_mb_row(f"b{i}") for i in range(8)]
        events = [_event() for _ in range(30)]
        with mock.patch.object(timingreport.rosterwatch, "events",
                               return_value=events):
            report_result = timingreport.report(
                multibook_rows=rows, games=GAMES, transactions=[])
        result = timingtest.test_class(
            "starter_scratch", report_result=report_result)
        self.assertEqual(result["status"], "tested")
        self.assertIn("s0", "".join(result["test"]))  # point_estimate_s0 key present
        self.assertGreaterEqual(result["measurable_events"], 30)


if __name__ == "__main__":
    unittest.main()
