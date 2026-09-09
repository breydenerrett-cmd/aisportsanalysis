"""tests for src.engine.slip: the published slip and what may reach it.

The load-bearing test in this file is
`test_two_systems_in_two_families_outrank_three_in_one`. If that one ever
passes for the wrong reason, the product is advertising manufactured
confidence, which is the single failure docs/PRODUCT_DOCTRINE.md amendment 9
exists to prevent.
"""

from __future__ import annotations

import unittest

from src.analysis import families as fam
from src.engine import slip as slip_mod
from src.engine.slip import (
    COHORT_CUTS,
    EVIDENCE_BUILDING,
    EVIDENCE_MINIMAL,
    EVIDENCE_STRONG,
    EVIDENCE_TIER_LABEL,
    EVIDENCE_THIN,
    MIN_MECHANISM_PREDICATES,
    MISS_COMMENCE_TIME_UNKNOWN,
    MISS_GAME_STARTED,
    READ_LIGHT,
    READ_NOTABLE,
    READ_NOTHING_CLEARED,
    SLIP_RULE,
    Slip,
    SlipError,
    build_slip,
    cohorts_for_rank,
    confirmation_strength,
    evidence_tier,
    is_forward_test,
)
from src.ledger.records import COHORT_PUBLISHED, COHORT_TOP_3, COHORT_TOP_5

DATE = "2026-09-08"
SLIP_UTC = "2026-09-08T22:00:00+00:00"


def _row(system_id, event_id, selection_id="sel_a", *, verdict="play",
         price=-110, books=11, signals=1, rung=0, consensus=0.5,
         market="h2h", staleness=0, **extra):
    """One decision row in raw ledger shape (a dict), which is what the slip
    builder reads off `evidence/decisions_v2.jsonl`."""
    preds = [{"threshold_index": rung, "feature": f"feat{i}",
              "predicate_id": f"p{i}@rung{rung}"} for i in range(signals)]
    row = {
        "system_id": system_id, "event_id": event_id,
        "selection_id": selection_id, "market_key": market,
        "verdict": verdict, "price_american": price,
        "books_at_decision": books, "consensus_fair": consensus,
        "friction": {"book_count": books, "staleness_seconds": staleness},
        "mechanism_predicates": preds, "line": None, "book": "somebook",
        "thesis": "because", "counterarguments": [],
        "decision_utc": SLIP_UTC,
    }
    row.update(extra)
    return row


def _clustering(rows, systems=None):
    ids = systems or sorted({r["system_id"] for r in rows})
    return fam.families(fam.forward_selections(rows, systems=ids).selections)


def _forced_clustering(groups):
    """A clustering with EXACTLY the families named in `groups`.

    Built by handing `families()` synthetic decision sets: members of a group
    share an identical set (Jaccard 1.0, above the 0.8 threshold), and
    different groups share nothing. That exercises the real clustering code
    rather than hand-building a FamilyClustering the production path would
    never produce.
    """
    selections = {}
    genomes = {}
    for i, members in enumerate(groups):
        shared = frozenset({f"evt{i}:h2h:s{j}" for j in range(10)})
        for m in members:
            selections[m] = shared
            # A DISTINCT feature set per system, so the structural relation
            # adds no merges of its own and the groups above are exactly what
            # comes out. Passing genomes at all is required: build_slip
            # refuses a structure-blind clustering.
            genomes[m] = frozenset({f"feature_{m}"})
    return fam.families(selections, genomes=genomes)


class CohortNestingTests(unittest.TestCase):
    def test_rank_one_is_in_all_three_cohorts(self):
        self.assertEqual(cohorts_for_rank(1),
                         (COHORT_PUBLISHED, COHORT_TOP_5, COHORT_TOP_3))

    def test_rank_four_is_top5_and_published_only(self):
        self.assertEqual(cohorts_for_rank(4),
                         (COHORT_PUBLISHED, COHORT_TOP_5))

    def test_rank_six_is_published_only(self):
        self.assertEqual(cohorts_for_rank(6), (COHORT_PUBLISHED,))

    def test_every_rank_is_at_least_published(self):
        for rank in range(1, 40):
            self.assertIn(COHORT_PUBLISHED, cohorts_for_rank(rank))

    def test_cohorts_nest_at_every_rank(self):
        """TOP_3 without TOP_5 (or without PUBLISHED) would make two rollups
        of the same night disagree."""
        for rank in range(1, 40):
            tags = cohorts_for_rank(rank)
            if COHORT_TOP_3 in tags:
                self.assertIn(COHORT_TOP_5, tags)
                self.assertIn(COHORT_PUBLISHED, tags)
            if COHORT_TOP_5 in tags:
                self.assertIn(COHORT_PUBLISHED, tags)

    def test_cuts_are_the_frozen_ones(self):
        self.assertEqual(COHORT_CUTS[COHORT_TOP_3], 3)
        self.assertEqual(COHORT_CUTS[COHORT_TOP_5], 5)


class AgreementOutranksSystemCountTests(unittest.TestCase):
    """Doctrine amendment 9, pinned."""

    def test_two_systems_in_two_families_outrank_three_in_one(self):
        """THE test. Three near-duplicate genomes agreeing is one opinion
        wearing three hats; two independent families agreeing is two
        opinions. If raw system count ever wins here, the product is
        manufacturing confidence out of near-copies.

        Everything else is held equal, and the three-system selection is
        given the BETTER price standing, so the only way it can lose is if
        family agreement genuinely dominates."""
        rows = [
            # one family, three members, better price standing
            _row("dup1", "evtA", consensus=0.60, price=-110),
            _row("dup2", "evtA", consensus=0.60, price=-110),
            _row("dup3", "evtA", consensus=0.60, price=-110),
            # two families, two members, worse price standing
            _row("indep1", "evtB", consensus=0.40, price=-110),
            _row("indep2", "evtB", consensus=0.40, price=-110),
        ]
        clustering = _forced_clustering(
            [("dup1", "dup2", "dup3"), ("indep1",), ("indep2",)])
        slip = build_slip(rows, clustering, date=DATE, slip_utc=SLIP_UTC)

        self.assertEqual(len(slip.picks), 2)
        top, second = slip.picks
        self.assertEqual(top.event_id, "evtB",
                         "two independent families must outrank three "
                         "near-duplicates")
        self.assertEqual((top.n_families, top.n_systems), (2, 2))
        self.assertEqual((second.n_families, second.n_systems), (1, 3))

    def test_the_discount_is_reported_not_just_applied(self):
        rows = [_row("dup1", "evtA"), _row("dup2", "evtA"),
                _row("dup3", "evtA")]
        clustering = _forced_clustering([("dup1", "dup2", "dup3")])
        pick = build_slip(rows, clustering, date=DATE,
                          slip_utc=SLIP_UTC).picks[0]
        self.assertEqual(pick.n_families, 1)
        self.assertEqual(pick.n_systems, 3)
        self.assertEqual(pick.agreement["n_systems_discounted"], 2)

    def test_one_system_deciding_the_same_wager_twice_is_not_agreement(self):
        """A system that re-decided at two capture instants agreed with
        itself."""
        rows = [_row("solo", "evtA", decision_utc="2026-09-08T15:00:00+00:00"),
                _row("solo", "evtA", decision_utc="2026-09-08T21:00:00+00:00")]
        clustering = _forced_clustering([("solo",)])
        pick = build_slip(rows, clustering, date=DATE,
                          slip_utc=SLIP_UTC).picks[0]
        self.assertEqual(pick.n_systems, 1)
        self.assertEqual(pick.n_families, 1)


class RankingOrderTests(unittest.TestCase):
    def test_price_standing_is_the_last_term_not_the_first(self):
        """Between two selections whose cases are identical, the better
        number wins -- but a better number must never beat a stronger case.
        The stronger case here is more fired signals."""
        rows = [
            _row("a", "evtA", signals=2, consensus=0.40),   # stronger case
            _row("b", "evtB", signals=1, consensus=0.90),   # better standing
        ]
        clustering = _forced_clustering([("a",), ("b",)])
        picks = build_slip(rows, clustering, date=DATE,
                           slip_utc=SLIP_UTC).picks
        self.assertEqual(picks[0].event_id, "evtA")

    def test_identical_cases_separate_on_price_standing(self):
        rows = [_row("a", "evtA", consensus=0.40),
                _row("b", "evtB", consensus=0.90)]
        clustering = _forced_clustering([("a",), ("b",)])
        picks = build_slip(rows, clustering, date=DATE,
                           slip_utc=SLIP_UTC).picks
        self.assertEqual(picks[0].event_id, "evtB")
        self.assertGreater(picks[0].price_standing_bps,
                           picks[1].price_standing_bps)

    def test_a_deeper_threshold_rung_outranks_a_shallower_one(self):
        rows = [_row("a", "evtA", rung=0, consensus=0.90),
                _row("b", "evtB", rung=2, consensus=0.40)]
        clustering = _forced_clustering([("a",), ("b",)])
        picks = build_slip(rows, clustering, date=DATE,
                           slip_utc=SLIP_UTC).picks
        self.assertEqual(picks[0].event_id, "evtB")
        self.assertEqual(picks[0].deepest_rung, 2)

    def test_the_slip_is_deterministic(self):
        rows = [_row(f"s{i}", f"evt{i}") for i in range(6)]
        clustering = _forced_clustering([(f"s{i}",) for i in range(6)])
        a = build_slip(rows, clustering, date=DATE, slip_utc=SLIP_UTC)
        b = build_slip(list(reversed(rows)), clustering, date=DATE,
                       slip_utc=SLIP_UTC)
        self.assertEqual([p.wager_id for p in a.picks],
                         [p.wager_id for p in b.picks])


class EvidenceThresholdTests(unittest.TestCase):
    def test_a_refusal_never_reaches_the_slip(self):
        rows = [_row("a", "evtA", verdict="no_play"),
                _row("b", "evtB", verdict="refused_thin")]
        slip = build_slip(rows, _forced_clustering([("a",), ("b",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(slip.picks, ())

    def test_control_and_market_reference_never_reach_the_slip(self):
        rows = [_row("trivial_always_home", "evtA"),
                _row("market_derived_consensus_h2h_home", "evtB"),
                _row("genome1", "evtC")]
        slip = build_slip(rows, _forced_clustering([("genome1",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual([p.event_id for p in slip.picks], ["evtC"])

    def test_instrument_plays_are_counted_not_listed(self):
        """`misses` answers "what would it have taken tonight?". Burying two
        genuine near-misses under hundreds of rows that were never eligible
        would make it useless for that."""
        rows = [_row("trivial_always_home", f"evt{i}") for i in range(50)]
        rows.append(_row("genome1", "evtX", books=2))
        slip = build_slip(rows, _forced_clustering([("genome1",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(slip.n_instrument_plays, 50)
        self.assertEqual(len(slip.misses), 1)
        self.assertEqual(slip.misses[0].reason, slip_mod.MISS_THIN_BOARD)

    def test_a_thin_board_is_a_named_miss_carrying_the_count(self):
        rows = [_row("genome1", "evtA", books=3)]
        slip = build_slip(rows, _forced_clustering([("genome1",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(slip.picks, ())
        self.assertIn("3 book", slip.misses[0].detail)

    def test_a_pick_with_no_falsifiable_mechanism_is_refused(self):
        """Without a predicate frozen with the pick, no game can ever refute
        it, so the learning loop can never grade it."""
        rows = [_row("genome1", "evtA", signals=0)]
        slip = build_slip(rows, _forced_clustering([("genome1",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(slip.picks, ())
        self.assertEqual(slip.misses[0].reason,
                         slip_mod.MISS_NO_FALSIFIABLE_MECHANISM)

    def test_no_price_is_a_named_miss(self):
        rows = [_row("genome1", "evtA", price=None)]
        slip = build_slip(rows, _forced_clustering([("genome1",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(slip.picks, ())
        self.assertEqual(slip.misses[0].reason, slip_mod.MISS_NO_PRICE)

    def test_an_empty_night_is_a_measurement_not_an_error(self):
        slip = build_slip([], _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC)
        self.assertEqual(slip.picks, ())
        self.assertEqual(slip.rule, SLIP_RULE)

    def test_the_floor_is_at_least_one_predicate(self):
        self.assertEqual(MIN_MECHANISM_PREDICATES, 1)


class ClusteringIsRequiredTests(unittest.TestCase):
    def test_build_slip_refuses_without_a_clustering(self):
        """Without one the agreement count silently degrades to a raw system
        count -- the exact number amendment 9 replaces."""
        with self.assertRaises(SlipError):
            build_slip([_row("a", "evtA")], None, date=DATE,
                       slip_utc=SLIP_UTC)

    def test_build_slip_refuses_a_structure_blind_clustering(self):
        """A clustering built without genomes runs only the behavioural
        relation. That is not a smaller version of the right answer -- it is
        biased toward finding MORE families, so it overstates agreement.

        This shipped once: the CLI omitted genomes= and the slip reported 15
        families where both relations find 11, on a night when no structural
        twins both fired, so nothing looked wrong."""
        blind = fam.families({"a": frozenset({"w1"}), "b": frozenset({"w2"})})
        with self.assertRaises(SlipError) as ctx:
            build_slip([_row("a", "evtA")], blind, date=DATE,
                       slip_utc=SLIP_UTC)
        self.assertIn("genomes", str(ctx.exception))

    def test_structural_twins_do_not_manufacture_agreement(self):
        """Two genomes with identical feature sets are one family even if
        their decision sets have not yet had room to diverge. All four F5
        genomes in the live registry are feature-set twins of an h2h genome,
        so this is the real case, not a hypothetical."""
        clustering = fam.families(
            {"twin_a": frozenset({"w1"}), "twin_b": frozenset({"w2"})},
            genomes={"twin_a": frozenset({"velocity_gap"}),
                     "twin_b": frozenset({"velocity_gap"})})
        slip = build_slip([_row("twin_a", "evtA"), _row("twin_b", "evtA")],
                          clustering, date=DATE, slip_utc=SLIP_UTC)
        pick = slip.picks[0]
        self.assertEqual(pick.n_systems, 2)
        self.assertEqual(pick.n_families, 1,
                         "identical feature sets are one source of evidence, "
                         "not two")


class HelperTests(unittest.TestCase):
    def test_forward_test_prefix_rule(self):
        self.assertFalse(is_forward_test("trivial_always_home"))
        self.assertFalse(is_forward_test("market_derived_consensus_h2h_home"))
        self.assertTrue(is_forward_test("56ba4bb647b80640"))

    def test_an_unset_system_id_is_never_treated_as_a_baseline(self):
        self.assertTrue(is_forward_test(None))
        self.assertTrue(is_forward_test(""))

    def test_confirmation_strength_reads_predicates_not_evidence_strings(self):
        row = _row("a", "evtA", signals=3, rung=2)
        row["evidence"] = ["score=99.0"]
        self.assertEqual(confirmation_strength(row), (3, 2))

    def test_no_predicates_sorts_below_rung_zero(self):
        self.assertEqual(confirmation_strength(_row("a", "e", signals=0)),
                         (0, -1))

    def test_absent_price_standing_never_beats_a_real_one(self):
        """Zero is a real, middling standing and must never stand in for
        'unknown'."""
        self.assertFalse(slip_mod._better_standing(None, -500))
        self.assertTrue(slip_mod._better_standing(-500, None))
        self.assertFalse(slip_mod._better_standing(None, None))


class SerialisationTests(unittest.TestCase):
    def test_slip_round_trips_to_a_json_safe_dict(self):
        import json
        rows = [_row("a", "evtA"), _row("b", "evtB")]
        slip = build_slip(rows, _forced_clustering([("a",), ("b",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        payload = slip.to_dict()
        json.dumps(payload)  # raises if anything is not serialisable
        self.assertEqual(payload["rule"], SLIP_RULE)
        self.assertEqual(payload["n_picks"], 2)
        self.assertEqual(payload["cohort_cuts"], {"TOP_3": 3, "TOP_5": 5})

    def test_every_pick_carries_both_agreement_counts(self):
        rows = [_row("a", "evtA")]
        slip = build_slip(rows, _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC)
        ag = slip.to_dict()["picks"][0]["agreement"]
        self.assertIn("n_families", ag)
        self.assertIn("n_systems", ag)


class CohortFilterTests(unittest.TestCase):
    def test_cohort_is_a_filter_over_one_frozen_list(self):
        rows = [_row(f"s{i}", f"evt{i}") for i in range(6)]
        slip = build_slip(rows, _forced_clustering([(f"s{i}",)
                                                    for i in range(6)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(len(slip.cohort(COHORT_TOP_3)), 3)
        self.assertEqual(len(slip.cohort(COHORT_TOP_5)), 5)
        self.assertEqual(len(slip.cohort(COHORT_PUBLISHED)), 6)
        # Nested: every Top 3 pick is also in the wider cohorts.
        top3 = {p.wager_id for p in slip.cohort(COHORT_TOP_3)}
        top5 = {p.wager_id for p in slip.cohort(COHORT_TOP_5)}
        self.assertTrue(top3 <= top5)

    def test_a_short_night_yields_short_cohorts_without_padding(self):
        rows = [_row("a", "evtA"), _row("b", "evtB")]
        slip = build_slip(rows, _forced_clustering([("a",), ("b",)]),
                          date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(len(slip.cohort(COHORT_TOP_3)), 2)
        self.assertEqual(len(slip.cohort(COHORT_TOP_5)), 2)


class EvidenceTierTests(unittest.TestCase):
    """docs/PRODUCT_DOCTRINE.md section 4's confidence axis, gated: this is a
    tier over CASE STRENGTH (family agreement + signal-ladder depth), never a
    win probability. Every boundary below is checked from both sides -- one
    input over the line, everything else held constant -- so the tier
    actually discriminates rather than reading the same value everywhere."""

    def test_three_families_is_strong_regardless_of_rung(self):
        self.assertEqual(evidence_tier(3, 0), EVIDENCE_STRONG)
        self.assertEqual(evidence_tier(3, 2), EVIDENCE_STRONG)

    def test_two_families_is_building(self):
        self.assertEqual(evidence_tier(2, 0), EVIDENCE_BUILDING)

    def test_one_family_at_the_hardest_rung_is_also_building(self):
        """A single system that cleared p90 alone is treated the same as two
        systems agreeing at a weaker rung -- both are real, checkable
        evidence, neither is a guess at which matters more."""
        self.assertEqual(evidence_tier(1, 2), EVIDENCE_BUILDING)

    def test_one_family_at_the_middle_rung_is_thin(self):
        self.assertEqual(evidence_tier(1, 1), EVIDENCE_THIN)

    def test_one_family_at_the_weakest_rung_is_minimal(self):
        self.assertEqual(evidence_tier(1, 0), EVIDENCE_MINIMAL)

    def test_every_boundary_is_a_real_boundary(self):
        """The four tiers are actually distinct outcomes, not the same label
        wearing four names -- this is the test a constant-function mutation
        would fail."""
        seen = {evidence_tier(3, 0), evidence_tier(2, 0), evidence_tier(1, 2),
                evidence_tier(1, 1), evidence_tier(1, 0)}
        self.assertEqual(len(seen), 4)

    def test_raising_n_families_alone_never_lowers_the_tier(self):
        order = {EVIDENCE_MINIMAL: 0, EVIDENCE_THIN: 1, EVIDENCE_BUILDING: 2,
                 EVIDENCE_STRONG: 3}
        for rung in (0, 1, 2):
            prev = -1
            for n in (1, 2, 3, 5):
                rank = order[evidence_tier(n, rung)]
                self.assertGreaterEqual(rank, prev)
                prev = rank

    def test_raising_rung_alone_never_lowers_the_tier(self):
        order = {EVIDENCE_MINIMAL: 0, EVIDENCE_THIN: 1, EVIDENCE_BUILDING: 2,
                 EVIDENCE_STRONG: 3}
        for n in (1, 2):
            prev = -1
            for rung in (0, 1, 2):
                rank = order[evidence_tier(n, rung)]
                self.assertGreaterEqual(rank, prev)
                prev = rank

    def test_every_tier_has_a_plain_english_label(self):
        for tier in (EVIDENCE_STRONG, EVIDENCE_BUILDING, EVIDENCE_THIN,
                    EVIDENCE_MINIMAL):
            label = EVIDENCE_TIER_LABEL[tier]
            self.assertNotIn("_", label)
            self.assertGreater(len(label), 10)

    def test_a_slip_picks_tier_matches_the_pure_function(self):
        """The property on SlipPick must never drift from the function every
        test above pins -- two implementations of the same rule is exactly
        the failure mode this project designs against."""
        rows = [_row("a", "evtA", signals=1, rung=0)]
        pick = build_slip(rows, _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC).picks[0]
        self.assertEqual(pick.evidence_tier,
                         evidence_tier(pick.n_families, pick.deepest_rung))

    def test_the_tier_reaches_the_serialised_dict(self):
        rows = [_row("a", "evtA", signals=1, rung=0)]
        payload = build_slip(rows, _forced_clustering([("a",)]), date=DATE,
                             slip_utc=SLIP_UTC).picks[0].to_dict()
        self.assertEqual(payload["evidence_tier"], EVIDENCE_MINIMAL)
        self.assertIn("evidence_tier_label", payload)

    def test_no_tier_ever_names_a_probability_or_a_percent(self):
        """Doctrine: no independent model probability exists, so nothing here
        may look like one."""
        for label in EVIDENCE_TIER_LABEL.values():
            lowered = label.lower()
            for banned in ("%", "probability", "chance of winning",
                          "confidence that", "will win", "guaranteed"):
                self.assertNotIn(banned, lowered)


class SlipReadAsTests(unittest.TestCase):
    """The honest framing a page reads off tonight's slip -- computed only
    from PUBLISHED, floor-cleared picks. Never from a miss."""

    def test_no_picks_reads_as_nothing_cleared(self):
        slip = build_slip([], _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC)
        self.assertEqual(slip.read_as, READ_NOTHING_CLEARED)

    def test_only_thin_or_minimal_picks_read_as_light(self):
        """One real, floor-cleared, honestly-labelled-thin pick is the 'skip
        tonight unless you're betting anyway, here is our lean' case -- a
        real pick, never a fabricated one."""
        rows = [_row("a", "evtA", signals=1, rung=0)]
        slip = build_slip(rows, _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC)
        self.assertEqual(slip.read_as, READ_LIGHT)
        self.assertEqual(slip.tier_counts[EVIDENCE_MINIMAL], 1)

    def test_a_strong_pick_reads_as_notable(self):
        rows = [_row("a", "evtA", signals=1, rung=0),
                _row("b", "evtB", signals=1, rung=2)]
        clustering = _forced_clustering([("a",), ("b",)])
        slip = build_slip(rows, clustering, date=DATE, slip_utc=SLIP_UTC)
        self.assertEqual(slip.read_as, READ_NOTABLE)

    def test_tier_counts_always_report_all_four_keys(self):
        """A caller must never have to guess whether a missing key means zero
        or means unmeasured."""
        slip = build_slip([], _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC)
        self.assertEqual(set(slip.tier_counts),
                         {EVIDENCE_MINIMAL, EVIDENCE_THIN, EVIDENCE_BUILDING,
                          EVIDENCE_STRONG})
        self.assertEqual(sum(slip.tier_counts.values()), 0)

    def test_read_as_reaches_the_serialised_dict(self):
        payload = build_slip([], _forced_clustering([("a",)]), date=DATE,
                             slip_utc=SLIP_UTC).to_dict()
        self.assertEqual(payload["read_as"], READ_NOTHING_CLEARED)
        self.assertIn("tier_counts", payload)


class GameAlreadyStartedTests(unittest.TestCase):
    """Found live 2026-09-09: 21 of 23 published picks on a real slip were
    for games already in progress or final. The frozen decision underneath
    each one was genuinely pregame; nothing stopped the SLIP from
    continuing to present them as live recommendations. This is the guard."""

    PRE = "2026-09-09T23:05:00+00:00"  # first pitch, per the real incident
    NOW_BEFORE = "2026-09-09T22:00:00+00:00"   # 65 min before first pitch
    NOW_AT = "2026-09-09T23:05:00+00:00"       # exactly first pitch
    NOW_AFTER = "2026-09-09T23:45:00+00:00"    # the actual incident's clock

    def test_with_no_schedule_data_behaves_exactly_as_before(self):
        """The opt-in default: omitting commence_time_by_event/now must
        reproduce the pre-fix behaviour for every existing caller and test
        that has no schedule handy."""
        rows = [_row("a", "evtA")]
        slip = build_slip(rows, _forced_clustering([("a",)]), date=DATE,
                          slip_utc=SLIP_UTC)
        self.assertEqual(len(slip.picks), 1)

    def test_a_game_still_pregame_is_published(self):
        rows = [_row("a", "evtA")]
        slip = build_slip(
            rows, _forced_clustering([("a",)]), date=DATE, slip_utc=SLIP_UTC,
            commence_time_by_event={"evtA": self.PRE}, now=self.NOW_BEFORE)
        self.assertEqual(len(slip.picks), 1)

    def test_a_game_already_started_is_refused_not_published(self):
        rows = [_row("a", "evtA")]
        slip = build_slip(
            rows, _forced_clustering([("a",)]), date=DATE, slip_utc=SLIP_UTC,
            commence_time_by_event={"evtA": self.PRE}, now=self.NOW_AFTER)
        self.assertEqual(slip.picks, ())
        self.assertEqual(slip.misses[0].reason, MISS_GAME_STARTED)

    def test_exactly_at_first_pitch_is_already_started(self):
        """At-or-before, not strictly-before: the instant of first pitch is
        no longer a pregame call."""
        rows = [_row("a", "evtA")]
        slip = build_slip(
            rows, _forced_clustering([("a",)]), date=DATE, slip_utc=SLIP_UTC,
            commence_time_by_event={"evtA": self.PRE}, now=self.NOW_AT)
        self.assertEqual(slip.picks, ())
        self.assertEqual(slip.misses[0].reason, MISS_GAME_STARTED)

    def test_an_event_missing_from_the_schedule_map_fails_closed(self):
        """A partial schedule fetch must not silently trust whatever it
        happened to have -- an unverifiable game is refused, not published."""
        rows = [_row("a", "evtA")]
        slip = build_slip(
            rows, _forced_clustering([("a",)]), date=DATE, slip_utc=SLIP_UTC,
            commence_time_by_event={}, now=self.NOW_BEFORE)
        self.assertEqual(slip.picks, ())
        self.assertEqual(slip.misses[0].reason, MISS_COMMENCE_TIME_UNKNOWN)

    def test_the_two_real_timestamp_shapes_compare_correctly(self):
        """mlb.fetch_games uses a trailing 'Z'; datetime.isoformat() uses
        '+00:00'. A raw string compare of the two does not sort the same way
        and would silently mis-rank some fraction of games -- this is the
        exact live incident's timestamp shapes, byte for byte."""
        rows = [_row("a", "evtA")]
        slip = build_slip(
            rows, _forced_clustering([("a",)]), date=DATE, slip_utc=SLIP_UTC,
            commence_time_by_event={"evtA": "2026-09-09T23:05:00Z"},
            now="2026-09-09T23:45:51.448314+00:00")
        self.assertEqual(slip.picks, (),
                         "a 'Z'-suffixed commence time after a "
                         "microsecond-precision '+00:00' now must still "
                         "correctly compare as already started")

    def test_only_the_started_game_is_refused_others_unaffected(self):
        rows = [_row("a", "evtA"), _row("b", "evtB")]
        slip = build_slip(
            rows, _forced_clustering([("a",), ("b",)]), date=DATE,
            slip_utc=SLIP_UTC,
            commence_time_by_event={
                "evtA": "2026-09-09T20:00:00+00:00",   # already started
                "evtB": "2026-09-10T02:00:00+00:00",   # still hours away
            },
            now=self.NOW_AFTER)
        self.assertEqual(len(slip.picks), 1)
        self.assertEqual(slip.picks[0].event_id, "evtB")
        self.assertEqual(slip.misses[0].reason, MISS_GAME_STARTED)

    def test_the_miss_names_the_actual_first_pitch_time(self):
        """The reason string carries the real timestamp, not just the
        category -- a reader (or a future debugger) can see exactly how
        late the pass ran without cross-referencing anything else."""
        rows = [_row("a", "evtA")]
        slip = build_slip(
            rows, _forced_clustering([("a",)]), date=DATE, slip_utc=SLIP_UTC,
            commence_time_by_event={"evtA": self.PRE}, now=self.NOW_AFTER)
        self.assertIn(self.PRE, slip.misses[0].detail)


if __name__ == "__main__":
    unittest.main()
