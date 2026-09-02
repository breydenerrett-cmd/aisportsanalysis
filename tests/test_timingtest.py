"""The V3 primary test: KM correctness, planted effects, censoring, the floor."""

import datetime as _dt
import unittest
from unittest import mock

from src.research import timingreport, timingtest
from tests.test_timingreport import GAMES, _event, _mb_row


_UNSET = object()


def _measured(game_pk, event_iso, game_start_iso, reaction_50,
             floor_minutes=60.0, category=_UNSET, matchup=None):
    """A synthetic eventstudy.measure() result, shaped exactly as
    timingreport.report() now attaches game_pk/game_start_utc/event_interval
    to it. `event_interval` is (event_iso - floor_minutes, event_iso) --
    ADDENDUM 2's fix reads the floor as the LITERAL bracket width, never
    inferred from distance to first pitch, so every synthetic event here
    must carry an explicit bracket rather than relying on GAME_START being
    "far enough away" the way the pre-correction tests did.

    `category` is UNSET by default -- the "category" key is omitted
    entirely, exactly like every non-transaction class's real measured
    event, so `timingtest.game_relevant` sees no relevance rule to apply.
    Pass a string (including None, for an unrecorded-category row) to
    attach the key and exercise the relevance filter.
    """
    out = {"excluded": None, "event_time": event_iso, "game_pk": game_pk,
           "game_start_utc": game_start_iso,
           "event_interval": (
               (_dt.datetime.fromisoformat(event_iso)
                - _dt.timedelta(minutes=floor_minutes)).isoformat(),
               event_iso),
           "ladder_minutes": {"25%": None, "50%": reaction_50,
                              "75%": None, "100%": None}}
    if category is not _UNSET:
        out["category"] = category
    if matchup is not None:
        out["matchup"] = matchup
    return out


def _report_result(name, measured_events, measurable=None):
    measurable = len(measured_events) if measurable is None else measurable
    return {"classes": {name: {"measurable": measurable,
                               "measured": measured_events}}}


GAME_START = "2026-09-05T00:00:00+00:00"


def _events(reactions, *, start=0, floor_minutes=60.0):
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
        out.append(_measured(f"g{i}", event_iso, GAME_START, reaction,
                             floor_minutes=floor_minutes))
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
        # single event, no censoring, each its own cluster (35 clusters).
        measured = _events([5.0] * 35)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["status"], "tested")
        self.assertEqual(result["censored"], 0)
        self.assertEqual(result["test"]["km_median_diff_minutes"], -55.0)
        # Every one of the 35 clusters lands on the "-" side: the exact sign
        # test is maximally uninformative for H1 (p=1.0), never a bootstrap
        # artifact -- ADDENDUM 2 replaces "p = 0.000" with exactly this.
        sign = result["test"]["sign_test"]
        self.assertEqual(sign["clusters_plus"], 0)
        self.assertEqual(sign["clusters_minus"], 35)
        self.assertEqual(sign["p_one_sided"], 1.0)
        # Zero clusters favored H1: the sign test alone is uninformative, so
        # the rule-of-three bound is reported alongside it.
        self.assertAlmostEqual(sign["rule_of_three_bound"], 3 / 35, places=4)
        # S(0) is a supporting note now, not the primary statistic, and its
        # own bootstrap is degenerate here (every resample redraws the same
        # uniformly-fast sample) -- the flag says so rather than emitting a
        # fake interval.
        self.assertEqual(result["test"]["supporting_s0"]["point_estimate"], 0.0)
        self.assertTrue(result["test"]["supporting_s0"]["degenerate"])
        self.assertNotIn("bootstrap_ci95", result["test"]["supporting_s0"])
        self.assertLess(result["descriptive"]["complete_case_median_diff_minutes"], 0)

    def test_planted_slow_reaction_is_a_rejection(self):
        # 300 minutes to 50%-moved against a 60-minute floor: diff = +240.
        measured = _events([300.0] * 35)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["test"]["km_median_diff_minutes"], 240.0)
        sign = result["test"]["sign_test"]
        self.assertEqual(sign["clusters_plus"], 35)
        self.assertEqual(sign["clusters_minus"], 0)
        # ~0.5**35 (~2.9e-11) -- small because the evidence really is that
        # one-sided, not because a percentile bootstrap could not
        # extrapolate. The module rounds to 10 places, so check magnitude
        # rather than exact equality against the unrounded value.
        self.assertLess(sign["p_one_sided"], 1e-9)
        self.assertEqual(result["test"]["supporting_s0"]["point_estimate"], 1.0)
        self.assertTrue(result["test"]["supporting_s0"]["degenerate"])
        self.assertNotIn("bootstrap_p_one_sided", result["test"]["supporting_s0"])
        self.assertGreater(
            result["descriptive"]["complete_case_median_diff_minutes"], 0)

    def test_a_genuinely_mixed_sample_lands_between_the_extremes(self):
        # Half fast (diff -55), half slow (diff +240): S(0) should land
        # strictly between the two pure cases' boundary values, and neither
        # bootstrap should degenerate to a single point the way the two pure
        # cases above do.
        measured = _events([5.0] * 18 + [300.0] * 18)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        s0 = result["test"]["supporting_s0"]["point_estimate"]
        self.assertGreater(s0, 0.0)
        self.assertLess(s0, 1.0)
        self.assertFalse(result["test"]["supporting_s0"]["degenerate"])
        ci = result["test"]["km_median_diff_bootstrap_ci95"]
        self.assertNotEqual(ci["low"], ci["high"])


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
        # The primary statistic itself must say "not reached" -- never a
        # fabricated number -- when every event is censored.
        self.assertEqual(result["test"]["km_median_diff_minutes"], "not reached")
        self.assertEqual(result["test"]["km_median_diff_bootstrap_ci95"]["low"],
                         "not reached")
        self.assertEqual(result["test"]["km_median_diff_bootstrap_ci95"]["high"],
                         "not reached")
        # S(0) is still well-defined (no death recorded anywhere, so no
        # evidence AGAINST H1 either) -- reported as 1.0, and degenerate
        # (every resample is also all-censored), never a fake interval.
        self.assertEqual(result["test"]["supporting_s0"]["point_estimate"], 1.0)
        self.assertTrue(result["test"]["supporting_s0"]["degenerate"])


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


class GameRelevantTests(unittest.TestCase):
    """docs/RESEARCH_V3_TIMING.md ADDENDUM 2's class-mismatch fix: the
    frozen il_roster_move definition is narrower than "every transaction id
    first seen", and this is the function that restates it.
    """

    def test_a_class_with_no_category_field_is_always_relevant(self):
        # Every non-transaction class's real measured events carry no
        # "category" key at all -- this is what tells game_relevant "no
        # relevance rule applies here" rather than "this event failed it".
        self.assertTrue(timingtest.game_relevant({"class": "lineup_posted"}))

    def test_each_relevant_category_passes(self):
        for category in timingtest.GAME_RELEVANT_TRANSACTION_CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue(
                    timingtest.game_relevant({"category": category}))

    def test_each_non_relevant_category_is_filtered(self):
        for category in timingtest.NON_RELEVANT_TRANSACTION_CATEGORIES:
            with self.subTest(category=category):
                self.assertFalse(
                    timingtest.game_relevant({"category": category}))

    def test_a_missing_or_unrecorded_category_is_conservatively_excluded(self):
        # Rows written before `category` was captured (or a feed row the
        # classifier could not place) carry `category: None` -- excluded,
        # never guessed into "relevant".
        self.assertFalse(timingtest.game_relevant({"category": None}))
        self.assertFalse(timingtest.game_relevant({"category": "other"}))
        self.assertFalse(timingtest.game_relevant(
            {"category": "some raw type this repo has never named"}))


class RelevanceFilteredClassTests(unittest.TestCase):
    """test_class's relevance-aware wrapping: a class whose events carry a
    "category" field gets BOTH a primary_relevant_subset (gated) and a
    secondary_all_transactions_exploratory (unfiltered) reading; a class
    without one (every other class) is untouched -- same flat shape as
    before ADDENDUM 2.
    """

    def _tx_events(self, relevant_n, non_relevant_n, *, reaction=300.0):
        relevant = _events([reaction] * relevant_n,
                           start=0)
        for m in relevant:
            m["category"] = "recalled"
        non_relevant = _events([reaction] * non_relevant_n, start=relevant_n)
        for m in non_relevant:
            m["category"] = "optioned"
        return relevant + non_relevant

    def test_a_class_without_category_is_the_old_flat_shape(self):
        measured = _events([300.0] * 35)
        result = timingtest.test_class(
            "cls", report_result=_report_result("cls", measured))
        self.assertEqual(result["status"], "tested")
        self.assertNotIn("relevance", result)
        self.assertNotIn("primary_relevant_subset", result)
        self.assertIn("test", result)  # flat, not nested under a reading

    def test_relevant_subset_below_its_own_floor_reports_that_and_nothing_else(self):
        # 42 all-transactions events (clears the 30 floor), only 19 of them
        # category "recalled" (relevant) -- the actual shape ADDENDUM 2's
        # correction produced on the real store.
        measured = self._tx_events(19, 23)
        result = timingtest.test_class(
            "transaction_first_seen",
            report_result=_report_result("transaction_first_seen", measured))
        self.assertEqual(result["relevance"]["n_relevant"], 19)
        self.assertEqual(result["relevance"]["n_all_transactions"], 42)
        primary = result["primary_relevant_subset"]
        self.assertEqual(primary["status"], "below floor after relevance filter")
        self.assertNotIn("test", primary)  # no result read below the floor
        # The secondary/exploratory reading is unfiltered and DOES clear the
        # floor -- reported, but never as a promotable result.
        secondary = result["secondary_all_transactions_exploratory"]
        self.assertEqual(secondary["status"], "tested")
        self.assertEqual(secondary["measurable_events"], 42)

    def test_relevant_subset_at_floor_produces_its_own_primary_reading(self):
        measured = self._tx_events(30, 10)
        result = timingtest.test_class(
            "transaction_first_seen",
            report_result=_report_result("transaction_first_seen", measured))
        primary = result["primary_relevant_subset"]
        self.assertEqual(primary["status"], "tested")
        self.assertEqual(primary["measurable_events"], 30)
        self.assertEqual(result["secondary_all_transactions_exploratory"]
                         ["measurable_events"], 40)


class ClusterSignTestTests(unittest.TestCase):
    """ADDENDUM 2's replacement for "p = 0.000": one vote per cluster, exact
    binomial tail, plus a rule-of-three bound when the count on one side is
    zero.
    """

    def test_all_clusters_agreeing_gives_the_exact_binomial_tail(self):
        rows = [{"cluster": f"g{i}", "censored": False, "diff_minutes": 10.0}
               for i in range(6)]
        result = timingtest.cluster_sign_test(rows)
        self.assertEqual(result["clusters_plus"], 6)
        self.assertEqual(result["clusters_minus"], 0)
        self.assertEqual(result["n"], 6)
        self.assertAlmostEqual(result["p_one_sided"], 0.5 ** 6, places=8)

    def test_a_mixed_sign_cluster_is_a_dropped_tie(self):
        rows = [
            {"cluster": "g1", "censored": False, "diff_minutes": 10.0},
            {"cluster": "g1", "censored": False, "diff_minutes": -10.0},
            {"cluster": "g2", "censored": False, "diff_minutes": 5.0},
            {"cluster": "g3", "censored": False, "diff_minutes": -5.0},
        ]
        result = timingtest.cluster_sign_test(rows)
        self.assertEqual(result["clusters_mixed_sign_dropped"], 1)
        self.assertEqual(result["n"], 2)  # g1 dropped, g2 and g3 remain

    def test_zero_favoring_clusters_reports_a_rule_of_three_bound(self):
        rows = [{"cluster": f"g{i}", "censored": False, "diff_minutes": -10.0}
               for i in range(10)]
        result = timingtest.cluster_sign_test(rows)
        self.assertEqual(result["p_one_sided"], 1.0)
        self.assertAlmostEqual(result["rule_of_three_bound"], 0.3, places=4)

    def test_no_classifiable_cluster_is_undefined_not_a_fabricated_p(self):
        rows = [
            {"cluster": "g1", "censored": False, "diff_minutes": 10.0},
            {"cluster": "g1", "censored": False, "diff_minutes": -10.0},
        ]
        result = timingtest.cluster_sign_test(rows)
        self.assertEqual(result["n"], 0)
        self.assertIsNone(result["p_one_sided"])


class ConcentrationCheckTests(unittest.TestCase):
    """RESEARCH_V3_TIMING.md lines 120-121's required, never-run-before
    concentration check."""

    def test_a_single_dominant_cluster_and_matchup_are_named(self):
        rows, _ = timingtest._rows_for_class([
            _measured("g1", "2026-09-01T00:00:00+00:00", GAME_START, 100.0,
                     matchup="DET@MIN"),
            _measured("g1", "2026-09-01T01:00:00+00:00", GAME_START, 90.0,
                     matchup="DET@MIN"),
            _measured("g2", "2026-09-02T00:00:00+00:00", GAME_START, None,
                     matchup="NYY@BOS"),
        ])
        result = timingtest._concentration(rows)
        self.assertEqual(result["n_clusters"], 2)
        self.assertEqual(result["n_calendar_dates"], 2)
        self.assertEqual(result["top_matchup"], {"matchup": "DET@MIN",
                                                 "events": 2})
        self.assertEqual(result["n_observed_total"], 2)
        self.assertEqual(result["clusters_with_any_observed_reaction"], 1)
        self.assertEqual(result["share_of_observed_in_top3_clusters"], 1.0)


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
