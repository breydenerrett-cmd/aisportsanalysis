"""src/analysis/families.py: family-aware agreement (doctrine amendment 9).

WHAT THESE TESTS ARE FOR
------------------------
Every test here is written to FAIL if the behaviour it guards is broken, and
each one was checked that way -- the bug was introduced, the test was watched
to go red, the bug was removed. The specific failures being guarded against
are the ones that would silently inflate an agreement count:

  * clustering on the behavioural relation ALONE (small-n blindness),
  * clustering on the structural relation with a similarity threshold instead
    of identity (over-merging on two shared features out of three),
  * merging without transitivity, both ACROSS relations (A~B behaviourally,
    B~C structurally) and WITHIN one relation (a group of three linked only
    through its first member),
  * treating "structure unknown" as an empty feature set -- which does not
    merge anything, but does record an absence as a completed comparison and
    un-flags a family nobody has ever been able to test,
  * counting replayed or unprovenanced rows as forward evidence -- BOTH
    halves of `is_forward_play`, separately,
  * widening `_FULLY_TESTED_BASES` so that a family whose distinctness was
    never measured stops being flagged,
  * counting refusals as decisions,
  * counting one system's repeated decisions as several,
  * reporting `n_families` without `n_systems`.

WHY THE LIVE-LEDGER TESTS HARD-CODE A FAMILY STRUCTURE
-------------------------------------------------------
An earlier version of `LiveLedgerTests` asserted only invariants it derived
from the module under test -- `n_families <= n_systems`, every registered
system present in `family_id_of`, the forward-row count recomputed from
`fam.FORWARD_RECORD_PROVENANCES` and `fam.PLAYED_VERDICT`. Those are theorems
about the constructor, not facts about the clustering: an adversarial verifier
replaced the entire merge with `[(s,) for s in universe]` -- clustering
completely disabled, every system its own family -- and all four tests stayed
green. Collapsing every system into ONE family stayed green too, and so did
adding `None` to `FORWARD_RECORD_PROVENANCES`, because the oracle moved with
the code it was supposed to judge.

They are replaced with independently-measured facts, stated over a PREFIX of
`evidence/decisions_v2.jsonl`. That file is tracked in git, append-only and
hash-chained, so its first `LEDGER_MEASURED_ROWS` rows are frozen: an exact
expectation over them is not "a test of today's data", it stays true as
tonight's rows land on the end, and if it ever fails the ledger was rewritten
-- which is itself worth a red test in a project whose product is a record
that cannot be retconned.
"""

from __future__ import annotations

import collections
import itertools
import unittest
from pathlib import Path

from src.analysis import families as fam
from src.evolab import overlap
from src.ledger.records import (
    RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT,
    RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
    RECORD_PROVENANCE_REPLAY,
)

REPO = Path(__file__).resolve().parent.parent
LIVE_LEDGER = REPO / "evidence" / "decisions_v2.jsonl"


def _rec(system_id, event_id="evt1", selection_id="sel_home",
         market_key="h2h", verdict="play",
         record_provenance=RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT):
    """One decision row in the shape `HashChainLedger.read()` returns."""
    return {"system_id": system_id, "event_id": event_id,
            "market_key": market_key, "selection_id": selection_id,
            "verdict": verdict, "record_provenance": record_provenance}


class _FakeSignal:
    def __init__(self, feature):
        self.feature = feature


class _FakeGenome:
    """Duck-types the one attribute `feature_set` reads off a real
    `src.evolab.genome.Genome` (`.signals`, each with `.feature`). Used rather
    than building real genomes so these tests stay independent of the feature
    registry's current contents."""

    def __init__(self, *features):
        self.signals = tuple(_FakeSignal(f) for f in features)


class _FakeRecord:
    """A record OBJECT rather than a dict, so `_field`'s `getattr` branch is
    exercised: `settle_slate.load_decisions` hands this module real
    `DecisionRecord`s, and `HashChainLedger.read()` hands it dicts."""

    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)


# ---------------------------------------------------------------------------
# Wager identity
# ---------------------------------------------------------------------------

class WagerIdTests(unittest.TestCase):

    def test_triple_is_the_identity(self):
        self.assertEqual(fam.wager_id("evt1", "h2h", "sel_home"),
                         "evt1:h2h:sel_home")

    def test_same_selection_id_at_two_events_is_two_wagers(self):
        """`selection_id` carries no event (src/board/ids.py), so every home
        moneyline in the league shares one. Keying on it alone would fuse the
        whole slate into a single wager and make every system look identical."""
        self.assertNotEqual(fam.wager_id("evt1", "h2h", "sel_home"),
                            fam.wager_id("evt2", "h2h", "sel_home"))

    def test_blank_part_is_refused_not_papered_over(self):
        for bad in (None, "", "   ", 17):
            with self.assertRaises(fam.FamilyError):
                fam.wager_id("evt1", "h2h", bad)
            with self.assertRaises(fam.FamilyError):
                fam.wager_id(bad, "h2h", "sel_home")


# ---------------------------------------------------------------------------
# is_forward_play -- BOTH halves, separately
# ---------------------------------------------------------------------------

# The two `record_provenance` values that are forward evidence, written as
# LITERALS rather than read off `fam.FORWARD_RECORD_PROVENANCES`. An oracle
# built from the module under test moves with it: adding `None` to that set --
# which would read every unprovenanced row as pre-commitment confirmed, the one
# thing `src.ledger.records` says must never happen -- left the previous suite
# green precisely because the expectation was recomputed from the mutated set.
FORWARD_PROVENANCE_LITERALS = frozenset({"live_pre_commencement",
                                         "live_post_commencement"})
PLAYED_VERDICT_LITERAL = "play"


class IsForwardPlayTests(unittest.TestCase):
    """`is_forward_play` is an AND of two independent facts, and its own
    docstring says "both halves matter and neither has a safe default". Neither
    half had a test. Reducing the function to `verdict == PLAYED_VERDICT` --
    deleting the provenance half outright -- left all 44 tests green while
    admitting 1,103 ledger rows as forward evidence instead of 909.
    """

    def test_both_halves_are_required(self):
        cases = (
            # (record_provenance, verdict, is forward evidence)
            (RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT, "play", True),
            (RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT, "play", True),
            # provenance half alone
            (RECORD_PROVENANCE_REPLAY, "play", False),
            (None, "play", False),
            ("some_future_provenance", "play", False),
            # verdict half alone
            (RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT, "refused_thin", False),
            (RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT, "refused_stale", False),
            (RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT, "market_unavailable",
             False),
            (RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT, "refused_thin", False),
            (RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT, None, False),
            # neither half
            (RECORD_PROVENANCE_REPLAY, "refused_thin", False),
            (None, None, False),
        )
        for provenance, verdict, expected in cases:
            with self.subTest(provenance=provenance, verdict=verdict):
                row = _rec("a", verdict=verdict, record_provenance=provenance)
                self.assertIs(fam.is_forward_play(row), expected)

    def test_the_forward_provenance_set_is_exactly_the_two_live_values(self):
        """`replay` is history (amendment 8) and `None` is unknown. Neither is
        forward, and 'not marked replay' is not a provenance."""
        self.assertEqual(set(fam.FORWARD_RECORD_PROVENANCES),
                         set(FORWARD_PROVENANCE_LITERALS))
        self.assertNotIn(None, fam.FORWARD_RECORD_PROVENANCES)
        self.assertNotIn("replay", fam.FORWARD_RECORD_PROVENANCES)

    def test_the_played_verdict_is_the_only_one_that_counts(self):
        self.assertEqual(fam.PLAYED_VERDICT, PLAYED_VERDICT_LITERAL)

    def test_reads_a_record_object_as_well_as_a_dict(self):
        forward = _FakeRecord(
            system_id="a", verdict="play",
            record_provenance=RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT)
        replayed = _FakeRecord(system_id="a", verdict="play",
                               record_provenance=RECORD_PROVENANCE_REPLAY)
        self.assertIs(fam.is_forward_play(forward), True)
        self.assertIs(fam.is_forward_play(replayed), False)

    def test_a_record_missing_both_fields_is_not_forward(self):
        """A record that says nothing is unknown, not confirmed."""
        self.assertIs(fam.is_forward_play(_FakeRecord(system_id="a")), False)
        self.assertIs(fam.is_forward_play({}), False)


# ---------------------------------------------------------------------------
# Forward decision sets
# ---------------------------------------------------------------------------

class ForwardSelectionTests(unittest.TestCase):

    def test_replay_rows_are_not_forward_evidence(self):
        """Amendment 8: a replayed decision is a statement about history."""
        result = fam.forward_selections([
            _rec("a", event_id="e1"),
            _rec("a", event_id="e2", record_provenance=RECORD_PROVENANCE_REPLAY),
        ])
        self.assertEqual(result.selections["a"],
                         frozenset({"e1:h2h:sel_home"}))
        self.assertEqual(result.n_rows_forward, 1)
        self.assertEqual(
            result.excluded_by_reason[f"record_provenance={RECORD_PROVENANCE_REPLAY!r}"],
            1)

    def test_unstamped_provenance_is_unknown_not_forward(self):
        """`src.ledger.records`: a row with `record_provenance is None`
        carries no evidence either way and must never read as pre-commitment
        confirmed. 818 of the rows on disk are in that state -- and, contrary
        to what this module's docstring used to say, only 69 of those predate
        the field; the other 749 are refusals written by a path that still
        does not stamp one."""
        result = fam.forward_selections([
            _rec("a", event_id="e1", record_provenance=None)])
        self.assertEqual(result.selections["a"], frozenset())
        self.assertEqual(result.n_rows_forward, 0)
        self.assertEqual(result.excluded_by_reason["record_provenance=None"], 1)

    def test_a_refusal_is_not_a_decision(self):
        result = fam.forward_selections([
            _rec("a", event_id="e1", verdict="refused_thin"),
            _rec("a", event_id="e2", verdict="refused_stale"),
            _rec("a", event_id="e3"),
        ])
        self.assertEqual(result.selections["a"],
                         frozenset({"e3:h2h:sel_home"}))
        self.assertEqual(result.excluded_by_reason["verdict='refused_thin'"], 1)

    def test_roster_systems_with_no_forward_play_are_kept_and_named(self):
        """Dropping a never-fired system would quietly shrink the population
        every downstream statement is about."""
        result = fam.forward_selections([_rec("a")], systems=["a", "b"])
        self.assertEqual(result.selections["b"], frozenset())
        kinds = {(x.subject, x.kind) for x in result.absences}
        self.assertIn(("b", fam.ABSENCE_NO_FORWARD_DECISIONS), kinds)
        self.assertNotIn(("a", fam.ABSENCE_NO_FORWARD_DECISIONS), kinds)

    def test_row_without_a_system_id_is_refused(self):
        with self.assertRaises(fam.FamilyError):
            fam.forward_selections([_rec(None)])


# ---------------------------------------------------------------------------
# Feature sets (the structural relation's input)
# ---------------------------------------------------------------------------

class FeatureSetTests(unittest.TestCase):

    def test_missing_structure_returns_none_never_an_empty_set(self):
        self.assertIsNone(fam.feature_set(None))

    def test_two_empty_feature_sets_would_not_merge_but_that_is_not_the_point(self):
        """The rationale, pinned, because the docstring used to state it
        backwards. `jaccard(set(), set())` is 0.0 by explicit design, so
        returning an empty set for "unknown" would NOT fabricate a family.
        What it would do is record an absence as a completed comparison --
        see `test_an_unknown_structure_is_never_reported_as_measured`."""
        self.assertEqual(overlap.jaccard(frozenset(), frozenset()), 0.0)
        self.assertLess(overlap.jaccard(frozenset(), frozenset()),
                        fam.STRUCTURAL_IDENTITY_THRESHOLD)

    def test_an_unknown_structure_is_never_reported_as_measured(self):
        """The real cost of returning `frozenset()` for "structure unknown":
        the family stops being flagged as untested, so a family nobody could
        compare to anything is published as one that was compared and found
        distinct."""
        clustering = fam.families({"a": frozenset(), "b": frozenset()},
                                  genomes={"a": None, "b": None})
        self.assertEqual(clustering.basis_of["a"], fam.BASIS_UNCLUSTERABLE)
        self.assertEqual(clustering.basis_of["b"], fam.BASIS_UNCLUSTERABLE)
        kinds = {(x.subject, x.kind) for x in clustering.absences}
        self.assertIn(("a", fam.ABSENCE_STRUCTURE_UNAVAILABLE), kinds)
        result = fam.agreement([_rec("a"), _rec("b")], clustering)
        self.assertEqual(result.families_resting_on_absence,
                         ("fam_a", "fam_b"))

    def test_reads_a_genome_signal_features(self):
        self.assertEqual(fam.feature_set(_FakeGenome("x", "y")),
                         frozenset({"x", "y"}))

    def test_bare_string_is_refused_not_iterated(self):
        with self.assertRaises(fam.FamilyError):
            fam.feature_set("velocity_gap")

    def test_unreadable_type_is_refused(self):
        with self.assertRaises(fam.FamilyError):
            fam.feature_set(17)


# ---------------------------------------------------------------------------
# The clustering
# ---------------------------------------------------------------------------

class BehaviouralRelationTests(unittest.TestCase):

    def test_reuses_overlaps_threshold_object(self):
        """Not a re-declaration of 0.8: the same object `lifecycle.admit()`
        already refuses a retired family's near-duplicate on."""
        self.assertIs(fam.FAMILY_THRESHOLD, overlap.FAMILY_THRESHOLD)

    def test_merges_at_exactly_the_threshold(self):
        a = frozenset(f"w{i}" for i in range(8)) | {"only_a"}
        b = frozenset(f"w{i}" for i in range(8)) | {"only_b"}
        self.assertEqual(overlap.jaccard(a, b), 0.8)   # the fixture is the bar
        result = fam.families({"a": a, "b": b})
        self.assertEqual(result.n_families, 1)

    def test_does_not_merge_below_the_threshold(self):
        a = frozenset({"w1", "w2", "w3", "w4"})
        b = frozenset({"w1", "w2", "w3", "w9"})
        self.assertLess(overlap.jaccard(a, b), fam.FAMILY_THRESHOLD)
        result = fam.families({"a": a, "b": b})
        self.assertEqual(result.n_families, 2)


# The largest feature-set size the near-identity ladder below runs to. A pair
# of feature sets differing by exactly one member out of n has Jaccard
# n/(n+1), which rises towards 1.0 but never reaches it -- so a behavioural
# fixture can push the pinned lower bound arbitrarily close to identity and
# never quite close it. 200 puts the highest tested NON-identical pair at
# 200/201 = 0.995, which kills every threshold at or below that (the verifier's
# surviving mutation set it to 0.8); the remaining sliver above 0.995 is closed
# by asserting the constant itself, which is the only way to close it at all.
NEAR_IDENTITY_MAX_SET_SIZE = 200


class StructuralRelationTests(unittest.TestCase):

    def test_identical_feature_sets_merge_even_when_decisions_diverge(self):
        """The small-n case the structural relation exists for: two genomes
        reading the same measurements, whose decision sets have not had room
        to coincide yet, are ONE source, not two."""
        result = fam.families(
            {"a": frozenset({"w1"}), "b": frozenset({"w2"})},
            genomes={"a": _FakeGenome("f1", "f2"), "b": _FakeGenome("f2", "f1")})
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.families[0], ("a", "b"))

    def test_structural_relation_is_identity_not_similarity(self):
        """Two of three shared features is Jaccard 0.5 -- over the 0.8 bar it
        would be 'not similar', but the point is that NO similarity threshold
        applies here at all. Sharing two features out of three is not being
        the same strategy."""
        a, b = _FakeGenome("f1", "f2", "f3"), _FakeGenome("f1", "f2", "f4")
        self.assertEqual(overlap.jaccard(fam.feature_set(a), fam.feature_set(b)),
                         0.5)
        result = fam.families({"a": frozenset({"w1"}), "b": frozenset({"w2"})},
                              genomes={"a": a, "b": b})
        self.assertEqual(result.n_families, 2)

    def test_the_structural_threshold_is_exact_identity(self):
        """Pinned as a constant as well as behaviourally, because no fixture
        can: see `NEAR_IDENTITY_MAX_SET_SIZE`. Also pinned as strictly ABOVE
        the behavioural bar, since collapsing the two relations onto one
        number is the specific over-merge the module docstring rejects."""
        self.assertEqual(fam.STRUCTURAL_IDENTITY_THRESHOLD, 1.0)
        self.assertGreater(fam.STRUCTURAL_IDENTITY_THRESHOLD,
                           fam.FAMILY_THRESHOLD)

    def test_near_identical_feature_sets_never_merge(self):
        """The range the two live structural fixtures left completely
        unpinned. They sat at Jaccard 0.5 and 1.0, so ANY threshold in
        (0.5, 1.0] passed and setting it to 0.8 survived the whole suite.
        One feature different out of n is one feature different, at every n."""
        for n in range(1, NEAR_IDENTITY_MAX_SET_SIZE + 1):
            base = tuple(f"f{i}" for i in range(n))
            a, b = _FakeGenome(*base), _FakeGenome(*base, "one_more")
            j = overlap.jaccard(fam.feature_set(a), fam.feature_set(b))
            with self.subTest(n_features=n, jaccard=j):
                self.assertEqual(j, n / (n + 1))
                result = fam.families({"a": frozenset(), "b": frozenset()},
                                      genomes={"a": a, "b": b})
                self.assertEqual(
                    result.n_families, 2,
                    f"merged two different feature sets at Jaccard {j}; the "
                    "structural relation is identity, not similarity")

    def test_identical_feature_sets_merge_at_every_size(self):
        """The other end of the same pin: identity must merge whatever the
        set size, so the threshold cannot have been pushed above 1.0 either
        (which would disable the structural relation entirely and un-merge
        the four F5/h2h twins in the live population)."""
        for n in (1, 2, 3, 17, NEAR_IDENTITY_MAX_SET_SIZE):
            base = tuple(f"f{i}" for i in range(n))
            with self.subTest(n_features=n):
                result = fam.families(
                    {"a": frozenset(), "b": frozenset()},
                    genomes={"a": _FakeGenome(*base),
                             "b": _FakeGenome(*reversed(base))})
                self.assertEqual(result.n_families, 1)

    def test_two_unknown_structures_are_not_a_family(self):
        result = fam.families({"a": frozenset(), "b": frozenset()},
                              genomes={"a": None, "b": None})
        self.assertEqual(result.n_families, 2)
        self.assertEqual(result.basis_of["a"], fam.BASIS_UNCLUSTERABLE)
        kinds = {(x.subject, x.kind) for x in result.absences}
        self.assertIn(("a", fam.ABSENCE_STRUCTURE_UNAVAILABLE), kinds)
        self.assertIn(("b", fam.ABSENCE_STRUCTURE_UNAVAILABLE), kinds)


# ---------------------------------------------------------------------------
# Transitivity of the merge
# ---------------------------------------------------------------------------

class UnionOfRelationsTests(unittest.TestCase):

    def test_union_is_transitive_across_the_two_relations(self):
        """A and B are behavioural near-duplicates; B and C are structural
        twins; A and C are related by neither. One family of three."""
        shared = frozenset(f"w{i}" for i in range(9))
        result = fam.families(
            {"a": shared, "b": shared | {"extra"}, "c": frozenset({"z1"})},
            genomes={"a": _FakeGenome("f1"), "b": _FakeGenome("f2"),
                     "c": _FakeGenome("f2")})
        self.assertGreaterEqual(overlap.jaccard(shared, shared | {"extra"}),
                                fam.FAMILY_THRESHOLD)
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.families[0], ("a", "b", "c"))

    def test_both_relations_are_reported_separately(self):
        """The discount has to be explainable: a reader must be able to see
        WHICH relation folded two systems together."""
        shared = frozenset(f"w{i}" for i in range(9))
        result = fam.families(
            {"a": shared, "b": shared | {"extra"}, "c": frozenset({"z1"})},
            genomes={"a": _FakeGenome("f1"), "b": _FakeGenome("f2"),
                     "c": _FakeGenome("f2")})
        self.assertIn(("a", "b"), result.behavioural)
        self.assertIn(("b", "c"), result.structural)


class MergeWithinOneRelationTests(unittest.TestCase):
    """Transitivity WITHIN a single relation's group, which nothing tested.

    Every fixture in the old suite -- and every group in the live population --
    had exactly two members, so `for other in group[1:]` and `group[1:2]` are
    indistinguishable: both union the first member with the second. Narrowing
    it to `group[1:2]` survived all 44 tests while dropping every member from
    the third onwards out of its own family, which INFLATES `n_families` on
    exactly the largest, most duplicated groups -- the ones amendment 9 was
    written for. The 8,811-genome sweep's largest family held 4,019 members;
    under that mutation it would have reported 4,018 families instead of one.
    """

    def test_a_group_of_three_in_one_partition_is_one_family(self):
        merged = fam._merge_partitions([("a", "b", "c")],
                                       [("a",), ("b",), ("c",)])
        self.assertEqual(merged, [("a", "b", "c")])

    def test_every_member_after_the_second_is_merged_too(self):
        members = ("a", "b", "c", "d", "e", "f", "g")
        merged = fam._merge_partitions([members], [(m,) for m in members])
        self.assertEqual(merged, [members])

    def test_two_groups_of_three_merge_fully_and_do_not_cross(self):
        """Both halves of the same property at once: every member of a group
        reaches every other, and no member reaches a member of the other
        group. A merge that stops after `group[1]` fails the first half; a
        merge that unions everything it is handed fails the second."""
        merged = fam._merge_partitions(
            [("a", "b", "c"), ("x", "y", "z")],
            [(m,) for m in ("a", "b", "c", "x", "y", "z")])
        self.assertEqual(merged, [("a", "b", "c"), ("x", "y", "z")])

    def test_three_behavioural_twins_are_one_family_end_to_end(self):
        shared = frozenset(f"w{i}" for i in range(9))
        result = fam.families(
            {"a": shared, "b": shared, "c": shared},
            genomes={"a": _FakeGenome("f1"), "b": _FakeGenome("f2"),
                     "c": _FakeGenome("f3")})
        self.assertEqual(result.behavioural[0], ("a", "b", "c"))
        self.assertEqual(result.families, (("a", "b", "c"),))
        self.assertEqual(result.n_families, 1)

    def test_three_structural_twins_are_one_family_end_to_end(self):
        result = fam.families(
            {"a": frozenset({"w1"}), "b": frozenset({"w2"}),
             "c": frozenset({"w3"})},
            genomes={"a": _FakeGenome("f1", "f2"), "b": _FakeGenome("f2", "f1"),
                     "c": _FakeGenome("f1", "f2")})
        self.assertEqual(result.structural[0], ("a", "b", "c"))
        self.assertEqual(result.families, (("a", "b", "c"),))

    def test_a_four_member_group_agrees_as_one_source(self):
        """The discount, at a group size the old fixtures never reached."""
        shared = frozenset(f"w{i}" for i in range(9))
        clustering = fam.families(
            {s: shared for s in ("a", "b", "c", "d")},
            genomes={s: _FakeGenome(f"f{i}") for i, s in
                     enumerate(("a", "b", "c", "d"))})
        result = fam.agreement(
            [_rec("a"), _rec("b"), _rec("c"), _rec("d")], clustering)
        self.assertEqual(result.n_systems, 4)
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.n_systems_discounted, 3)


class ClusteringEdgeCaseTests(unittest.TestCase):

    def test_zero_forward_decisions_falls_back_to_structural_and_says_so(self):
        result = fam.families(
            {"a": frozenset({"w1"}), "b": frozenset()},
            genomes={"a": _FakeGenome("f1"), "b": _FakeGenome("f1")})
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.basis_of["b"], fam.BASIS_STRUCTURAL_ONLY)
        self.assertEqual(result.basis_of["a"],
                         fam.BASIS_BEHAVIOURAL_AND_STRUCTURAL)
        reasons = [x.reason for x in result.absences
                   if x.subject == "b"
                   and x.kind == fam.ABSENCE_NO_FORWARD_DECISIONS]
        self.assertTrue(reasons, "the fallback must be stated, not implied")
        self.assertIn("behavioural", reasons[0])

    def test_structure_missing_leaves_a_behavioural_only_basis(self):
        result = fam.families({"a": frozenset({"w1"})}, genomes={"a": None})
        self.assertEqual(result.basis_of["a"], fam.BASIS_BEHAVIOURAL_ONLY)
        self.assertEqual(result.n_families, 1)

    def test_a_single_system_is_one_family_not_an_error(self):
        result = fam.families({"a": frozenset({"w1"})},
                              genomes={"a": _FakeGenome("f1")})
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.n_systems, 1)

    def test_a_system_named_only_in_genomes_is_still_in_the_population(self):
        result = fam.families({"a": frozenset({"w1"})},
                              genomes={"a": _FakeGenome("f1"),
                                       "b": _FakeGenome("f9")})
        self.assertEqual(sorted(result.family_id_of), ["a", "b"])

    def test_none_selections_is_refused(self):
        with self.assertRaises(fam.FamilyError):
            fam.families(None)

    def test_unknown_system_has_no_family_and_says_so(self):
        result = fam.families({"a": frozenset({"w1"})})
        with self.assertRaises(fam.FamilyError):
            result.family_id("never_seen")

    def test_families_are_ordered_largest_first(self):
        shared = frozenset(f"w{i}" for i in range(9))
        result = fam.families({"a": shared, "b": shared, "c": frozenset({"z"})})
        self.assertEqual(result.families[0], ("a", "b"))
        self.assertEqual(result.families[1], ("c",))


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

def _two_family_clustering():
    """`a` and `b` are behavioural twins; `c` stands alone. Three systems,
    two families -- the smallest fixture that can show a real discount."""
    shared = frozenset(f"w{i}" for i in range(9))
    return fam.families(
        {"a": shared, "b": shared, "c": frozenset({"z1"})},
        genomes={"a": _FakeGenome("f1"), "b": _FakeGenome("f2"),
                 "c": _FakeGenome("f3")})


class AgreementTests(unittest.TestCase):

    def test_records_both_counts_and_the_membership(self):
        """Doctrine: ranking reads n_families, but BOTH are recorded so the
        discount is auditable rather than an unexplained number."""
        clustering = _two_family_clustering()
        result = fam.agreement(
            [_rec("a"), _rec("b"), _rec("c")], clustering)
        self.assertEqual(result.n_systems, 3)
        self.assertEqual(result.n_families, 2)
        self.assertEqual(result.n_systems_discounted, 1)
        self.assertEqual(result.family_ids, ("fam_a", "fam_c"))
        self.assertEqual(result.families_by_id["fam_a"], ("a", "b"))
        self.assertEqual(result.systems, ("a", "b", "c"))

    def test_near_duplicates_do_not_manufacture_agreement(self):
        """The whole amendment, in one assertion: two near-copies landing on
        the same bet are ONE distinct source."""
        clustering = _two_family_clustering()
        result = fam.agreement([_rec("a"), _rec("b")], clustering)
        self.assertEqual(result.n_systems, 2)
        self.assertEqual(result.n_families, 1)

    def test_one_system_deciding_repeatedly_is_not_agreement(self):
        clustering = _two_family_clustering()
        result = fam.agreement([_rec("a"), _rec("a"), _rec("a")], clustering)
        self.assertEqual(result.n_systems, 1)
        self.assertEqual(result.n_families, 1)

    def test_refusals_do_not_count_toward_agreement(self):
        clustering = _two_family_clustering()
        result = fam.agreement(
            [_rec("a"), _rec("c", verdict="refused_thin")], clustering)
        self.assertEqual(result.systems, ("a",))
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.n_records_not_played, 1)

    def test_records_spanning_two_selections_are_refused(self):
        clustering = _two_family_clustering()
        with self.assertRaises(fam.FamilyError):
            fam.agreement([_rec("a", event_id="e1"),
                           _rec("b", event_id="e2")], clustering)

    def test_a_system_outside_the_clustering_is_refused_not_counted(self):
        """Counting it as its own family is the raw system count amendment 9
        abolishes; dropping it would understate n_systems.

        The message is asserted, not just the exception type: an earlier
        revision of this test passed against a version that DID mint
        `fam_stranger` silently, because a later lookup happened to raise the
        same exception class for an unrelated reason. A test that goes green
        on the bug it exists to catch is worse than no test."""
        clustering = _two_family_clustering()
        with self.assertRaisesRegex(
                fam.FamilyError, "must not be counted as a family of its own"):
            fam.agreement([_rec("a"), _rec("stranger")], clustering)

    def test_no_clustering_means_no_family_aware_number(self):
        with self.assertRaises(fam.FamilyError):
            fam.agreement([_rec("a")], None)

    def test_no_records_is_not_an_agreement_of_zero(self):
        with self.assertRaises(fam.FamilyError):
            fam.agreement([], _two_family_clustering())

    def test_provenance_is_reported_not_silently_filtered(self):
        """agreement() runs on tonight's fresh candidates too, whose
        provenance the writing caller stamps later. Zeroing the count over an
        unstamped field would be worse than showing what went in."""
        clustering = _two_family_clustering()
        result = fam.agreement(
            [_rec("a"), _rec("c", record_provenance=None)], clustering)
        self.assertEqual(result.n_systems, 2)
        self.assertIn("__unset__", result.record_provenances)
        self.assertIn(RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
                      result.record_provenances)

    def test_to_dict_carries_both_counts(self):
        clustering = _two_family_clustering()
        payload = fam.agreement([_rec("a"), _rec("b"), _rec("c")],
                                clustering).to_dict()
        self.assertEqual(payload["n_families"], 2)
        self.assertEqual(payload["n_systems"], 3)
        self.assertEqual(payload["n_systems_discounted"], 1)
        self.assertEqual(payload["wager_id"], "evt1:h2h:sel_home")

    def test_agreements_by_selection_groups_by_wager(self):
        clustering = _two_family_clustering()
        out = fam.agreements_by_selection(
            [_rec("a", event_id="e1"), _rec("b", event_id="e1"),
             _rec("c", event_id="e2")], clustering)
        self.assertEqual(sorted(out), ["e1:h2h:sel_home", "e2:h2h:sel_home"])
        self.assertEqual(out["e1:h2h:sel_home"].n_families, 1)
        self.assertEqual(out["e1:h2h:sel_home"].n_systems, 2)
        self.assertEqual(out["e2:h2h:sel_home"].n_families, 1)


# Which basis actually TESTED a system's separation from the rest of the
# population, and which merely records a comparison that could not be run.
# Only `behavioural_and_structural` did: `structural_only` means the
# behavioural relation had no decisions to work with, `behavioural_only` means
# the genome's structure is unknown, and `unclusterable` means neither ran.
# This table is the acceptance criterion for `families._FULLY_TESTED_BASES`,
# which was unguarded: widening it to include `structural_only` and
# `behavioural_only` left all 44 tests green and would have cleared
# `families_resting_on_absence` on every one of the 338 live agreement counts
# measured 2026-09-08 -- 11 of the 16 registered genomes are `structural_only`
# and every market-reference system is `behavioural_only`.
BASIS_IS_A_COMPLETED_TEST = {
    fam.BASIS_BEHAVIOURAL_AND_STRUCTURAL: True,
    fam.BASIS_STRUCTURAL_ONLY: False,
    fam.BASIS_BEHAVIOURAL_ONLY: False,
    fam.BASIS_UNCLUSTERABLE: False,
}


def _one_system_with_basis(basis):
    """A one-system clustering whose only member has exactly `basis`."""
    decided = frozenset({"w1"})
    if basis == fam.BASIS_BEHAVIOURAL_AND_STRUCTURAL:
        return fam.families({"a": decided}, genomes={"a": _FakeGenome("f1")})
    if basis == fam.BASIS_STRUCTURAL_ONLY:
        return fam.families({"a": frozenset()},
                            genomes={"a": _FakeGenome("f1")})
    if basis == fam.BASIS_BEHAVIOURAL_ONLY:
        return fam.families({"a": decided}, genomes={"a": None})
    if basis == fam.BASIS_UNCLUSTERABLE:
        return fam.families({"a": frozenset()}, genomes={"a": None})
    raise AssertionError(f"unhandled basis {basis!r}")


class FamilyRestingOnAbsenceTests(unittest.TestCase):
    """`families_resting_on_absence` is the flag that keeps a family of one by
    absence of evidence from reading as a family of one by evidence of
    distinctness. It is doctrine-critical -- it is the difference between "four
    independent sources agree" and "four things nobody could compare agree" --
    and only the `unclusterable` case had a test.
    """

    def test_a_family_counts_as_tested_only_under_both_relations(self):
        for basis, tested in sorted(BASIS_IS_A_COMPLETED_TEST.items()):
            with self.subTest(basis=basis):
                clustering = _one_system_with_basis(basis)
                self.assertEqual(clustering.basis_of["a"], basis)
                result = fam.agreement([_rec("a")], clustering)
                self.assertEqual(result.basis_by_system["a"], basis)
                self.assertEqual(
                    result.families_resting_on_absence,
                    () if tested else ("fam_a",),
                    f"basis {basis!r} is not a completed comparison; a family "
                    "resting on it must say so")
                self.assertEqual(
                    any(x.kind == fam.ABSENCE_FAMILY_UNTESTED
                        for x in result.absences), not tested)

    def test_one_fully_tested_member_settles_the_family(self):
        """The flag is about the FAMILY, not the member: `b` was never
        compared behaviourally, but it is in `a`'s family because `a` and `b`
        are structural twins and `a` WAS compared under both. Narrowing
        `_FULLY_TESTED_BASES`, or changing `any` to `all`, flags a family whose
        separation is in fact measured."""
        clustering = fam.families(
            {"a": frozenset({"w1"}), "b": frozenset()},
            genomes={"a": _FakeGenome("f1"), "b": _FakeGenome("f1")})
        self.assertEqual(clustering.families, (("a", "b"),))
        self.assertEqual(clustering.basis_of["a"],
                         fam.BASIS_BEHAVIOURAL_AND_STRUCTURAL)
        self.assertEqual(clustering.basis_of["b"], fam.BASIS_STRUCTURAL_ONLY)
        result = fam.agreement([_rec("a"), _rec("b")], clustering)
        self.assertEqual(result.n_families, 1)
        self.assertEqual(result.families_resting_on_absence, ())

    def test_a_flagged_family_and_a_tested_one_are_told_apart(self):
        """Both families count 1 towards `n_families`; only one of them
        earned it."""
        clustering = fam.families(
            {"a": frozenset({"w1"}), "b": frozenset()},
            genomes={"a": _FakeGenome("f1"), "b": None})
        result = fam.agreement([_rec("a"), _rec("b")], clustering)
        self.assertEqual(result.n_families, 2)
        self.assertEqual(result.families_resting_on_absence, ("fam_b",))

    def test_a_fully_tested_family_is_not_flagged(self):
        clustering = _two_family_clustering()
        result = fam.agreement([_rec("a"), _rec("c")], clustering)
        self.assertEqual(result.families_resting_on_absence, ())


# ---------------------------------------------------------------------------
# The real ledger -- measured facts, over a frozen prefix
# ---------------------------------------------------------------------------
#
# Every number below was MEASURED on 2026-09-08 against
# `evidence/decisions_v2.jsonl` at HEAD 495ff08, not recalled, and every one is
# stated over the file's first LEDGER_MEASURED_ROWS decision rows. The ledger
# is tracked in git, append-only and hash-chained, so that prefix does not
# change when tonight's slate appends to the end. If one of these fails, either
# the clustering changed or the ledger was rewritten; both deserve a red test.

LEDGER_MEASURED_ROWS = 1852

# `record_provenance` x `verdict` over the whole prefix. Spelled out as a table
# rather than as three totals because the shape is the point: there is not one
# unprovenanced population but two (69 legacy plays and 749 refusals), and
# there is not a single stamped refusal anywhere in the file. See the module
# docstring of `src/analysis/families.py`.
LEDGER_MEASURED_PROVENANCE_BY_VERDICT = {
    (None, "play"): 69,
    (None, "refused_thin"): 495,
    (None, "refused_stale"): 254,
    ("live_pre_commencement", "play"): 909,
    ("replay", "play"): 125,
}
LEDGER_MEASURED_FORWARD_ROWS = 909      # forward provenance AND verdict 'play'
LEDGER_MEASURED_PLAY_ROWS = 1103        # verdict 'play', ANY provenance
LEDGER_MEASURED_UNSTAMPED_ROWS = 818
LEDGER_MEASURED_REPLAY_ROWS = 125

# `REGISTERED_SYSTEMS` when the structure below was measured. Asserted first
# and on its own, so a roster change (a genome promoted, a control retired)
# fails with "the population changed" rather than an unreadable 38-family
# diff.
#
# RE-MEASURED 2026-09-09: REGISTERED_GENOME_COUNT 12->40 and
# REGISTERED_F5_GENOME_COUNT 4->12 (owner directive -- too few nights were
# clearing any published pick at all; see the constants' own comments in
# src/engine/adapters/evolab_system.py). This is a roster-size change only.
# The evidence floors in src/engine/slip.py, MIN_BOOKS and
# MIN_MECHANISM_PREDICATES are untouched, and every new genome earns its
# place under the identical pre-registered rules the original 16 used.
LEDGER_MEASURED_ROSTER = (
    "11da2d044a08ac38", "192eda5ca8760fce", "1c41c299676854d1",
    "1f5b79a0578568b7", "2bff17328ce70639", "375833d79e4bfef1",
    "42f0801e3e427201", "44faa9639a3a54e8", "4703ed67882a9d2b",
    "487b77c84551b046", "4a7700d36b3855ab", "4d21e4380e2ef716",
    "55b224b73474abec", "5f6d68dec562b5b3", "606be696ff199952",
    "6093c1cf8a6d6c08", "63ca06e1f2178a6c", "6435b1c945d78929",
    "6672fa80e22d2863", "66fd4a5e38e890fd", "67dd8b42c8a8be00",
    "6e9a91ab8b7c0b55", "7f7b7086400aea0b", "812f69c21540b56d",
    "8974e1cb85d58bcb", "8b2bb45d42021846", "8f24d63763454ce2",
    "8f27edc938ea2a56", "97a1156fdf4ba7cd", "999a7baa84ce385c",
    "9f653877f196fef4", "a3fd07c4387af7f0", "aabf4ae1da4d438a",
    "ab993b80cf517276", "aee91192d90b3be2", "b0f7d329342ebce1",
    "b6c0d42d22ff73a4", "b8135c76981b90be", "cbd1c70811efbf71",
    "cf08b6622ea2abda", "d8990c3e820ca117", "da1aab8fe3b869ce",
    "dd96d24159d3c866", "e5b0edc481775057", "e5ff00d4b3899ccc",
    "e64c85130b4664cc", "e7f41ed66082c279", "e8c58d079df7ecdd",
    "ec712e93b6b9d771", "f2f0a57586755527", "f301c228a7092d20",
    "f7685be895a987f9",
    "market_derived_consensus_h2h_1st_5_innings_away",
    "market_derived_consensus_h2h_1st_5_innings_home",
    "market_derived_consensus_h2h_away", "market_derived_consensus_h2h_home",
    "market_derived_consensus_spreads_away",
    "market_derived_consensus_spreads_home",
    "market_derived_consensus_totals_over",
    "market_derived_consensus_totals_under",
    "trivial_always_home", "trivial_always_home_spread", "trivial_under_total",
)

# 63 systems, 38 families. Hard-coded, not derived: a structure recomputed
# from the module under test is not an expectation, it is an echo.
LEDGER_MEASURED_FAMILIES = (
    ("56ba4bb647b80640", "999a7baa84ce385c", "b0f7d329342ebce1",
     "f2f0a57586755527"),
    ("11da2d044a08ac38", "dd96d24159d3c866", "e64c85130b4664cc"),
    ("1c41c299676854d1", "b8135c76981b90be", "e7f41ed66082c279"),
    ("1f5b79a0578568b7", "375833d79e4bfef1", "97a1156fdf4ba7cd"),
    ("2bff17328ce70639", "55b224b73474abec", "812f69c21540b56d"),
    ("42f0801e3e427201", "4d21e4380e2ef716", "e5ff00d4b3899ccc"),
    ("4703ed67882a9d2b", "487b77c84551b046", "cf08b6622ea2abda"),
    ("5f6d68dec562b5b3", "63ca06e1f2178a6c", "da1aab8fe3b869ce"),
    ("606be696ff199952", "6435b1c945d78929", "9f653877f196fef4"),
    ("8974e1cb85d58bcb", "e8c58d079df7ecdd", "f7685be895a987f9"),
    ("192eda5ca8760fce", "4a7700d36b3855ab"),
    ("6093c1cf8a6d6c08", "66fd4a5e38e890fd"),
    ("67dd8b42c8a8be00", "6e9a91ab8b7c0b55"),
    ("7f7b7086400aea0b", "aee91192d90b3be2"),
    ("8f24d63763454ce2", "d8990c3e820ca117"),
    ("8f27edc938ea2a56", "f301c228a7092d20"),
    ("market_derived_consensus_h2h_home", "trivial_always_home"),
    ("market_derived_consensus_spreads_home", "trivial_always_home_spread"),
    ("market_derived_consensus_totals_under", "trivial_under_total"),
    ("410024de8934544a",),
    ("44faa9639a3a54e8",),
    ("6672fa80e22d2863",),
    ("7be45f28a9c9312a",),
    ("8b2bb45d42021846",),
    ("a3fd07c4387af7f0",),
    ("aabf4ae1da4d438a",),
    ("ab993b80cf517276",),
    ("b6c0d42d22ff73a4",),
    ("cbd1c70811efbf71",),
    ("dcedc80dd159bf62",),
    ("e5b0edc481775057",),
    ("ec712e93b6b9d771",),
    ("ed2b9ec19d3b9b9a",),
    ("market_derived_consensus_h2h_1st_5_innings_away",),
    ("market_derived_consensus_h2h_1st_5_innings_home",),
    ("market_derived_consensus_h2h_away",),
    ("market_derived_consensus_spreads_away",),
    ("market_derived_consensus_totals_over",),
)

# The ONE behavioural merge between two evolab genomes on the live ledger:
# five forward wagers each, and the SAME five, so Jaccard is exactly 1.000.
# Unchanged by the roster expansion -- the new genomes have no forward
# history on the frozen ledger prefix this fixture is measured over, so they
# cannot join this pair behaviourally. Their feature sets differ, so nothing
# but the behavioural relation can have put THIS pair together -- which is
# what makes it, and not the structural twins below, the fixture that dies if
# the behavioural relation is disabled. (It sits inside a larger 4-member
# family above because two of its members separately have a structural F5
# twin; that chaining is exactly what LEDGER_STRUCTURAL_TWINS documents.)
LEDGER_BEHAVIOURAL_MERGE = ("56ba4bb647b80640", "999a7baa84ce385c")
LEDGER_BEHAVIOURAL_MERGE_WAGERS_EACH = 5

# Every structural-only component with more than one member: same feature
# set, different `routing.market_preference` (`h2h` vs `h2h_1st_5_innings`).
# Routing deliberately does not split a structural family -- two genomes
# reading the same measurements and disagreeing only about which market to
# express the answer in are one reading published twice. Ten are 3-member
# triads (an h2h genome, its F5 twin, and a second F5 genome the enumeration
# happened to place at the same feature set); six are plain 2-member pairs.
# Their behavioural Jaccard is 0.0 in every case on this frozen prefix (at
# least one member of each group has no forward decisions at all), so nothing
# but the structural relation can have put them together.
LEDGER_STRUCTURAL_TWINS = (
    ("11da2d044a08ac38", "dd96d24159d3c866", "e64c85130b4664cc"),
    ("1c41c299676854d1", "b8135c76981b90be", "e7f41ed66082c279"),
    ("1f5b79a0578568b7", "375833d79e4bfef1", "97a1156fdf4ba7cd"),
    ("2bff17328ce70639", "55b224b73474abec", "812f69c21540b56d"),
    ("42f0801e3e427201", "4d21e4380e2ef716", "e5ff00d4b3899ccc"),
    ("4703ed67882a9d2b", "487b77c84551b046", "cf08b6622ea2abda"),
    ("5f6d68dec562b5b3", "63ca06e1f2178a6c", "da1aab8fe3b869ce"),
    ("606be696ff199952", "6435b1c945d78929", "9f653877f196fef4"),
    ("8974e1cb85d58bcb", "e8c58d079df7ecdd", "f7685be895a987f9"),
    ("999a7baa84ce385c", "b0f7d329342ebce1", "f2f0a57586755527"),
    ("192eda5ca8760fce", "4a7700d36b3855ab"),
    ("6093c1cf8a6d6c08", "66fd4a5e38e890fd"),
    ("67dd8b42c8a8be00", "6e9a91ab8b7c0b55"),
    ("7f7b7086400aea0b", "aee91192d90b3be2"),
    ("8f24d63763454ce2", "d8990c3e820ca117"),
    ("8f27edc938ea2a56", "f301c228a7092d20"),
)

LEDGER_MEASURED_BASIS_COUNTS = {
    "behavioural_and_structural": 3,
    "structural_only": 49,
    "behavioural_only": 11,
    "unclusterable": 5,
}

# Five ids `forward_selections` finds mentioned on this frozen ledger prefix
# that are NOT in the current REGISTERED_SYSTEMS: the remnant of the old
# 16-system roster the 2026-09-09 stride change did not re-select. This is
# the module working exactly as documented ("every id the records mention on
# an excluded row" -- families.py's own forward_selections docstring): a
# genome's historical forward decisions do not vanish when it rotates out of
# the live population, so the clustering still has to account for them. It is
# why `clustering.n_systems` (68) exceeds `len(REGISTERED_SYSTEMS)` (63).
LEDGER_MEASURED_RETIRED_IN_LEDGER = (
    "410024de8934544a", "56ba4bb647b80640", "7be45f28a9c9312a",
    "dcedc80dd159bf62", "ed2b9ec19d3b9b9a",
)

# Live agreement over the 909 forward rows: 338 distinct wagers, and the
# (n_systems, n_families) shape of the discount on them. With clustering
# disabled every entry would be (n, n); with everything collapsed into one
# family every entry would be (n, 1). Neither is this. Unchanged by the
# roster expansion, for the same reason LEDGER_BEHAVIOURAL_MERGE is: the new
# genomes carry no forward decisions on this frozen prefix, so they can never
# appear in any wager's agreement group here.
LEDGER_MEASURED_FORWARD_WAGERS = 338
LEDGER_MEASURED_AGREEMENT_SHAPE = {
    (1, 1): 163, (2, 1): 164, (2, 2): 3, (3, 2): 4, (3, 3): 1,
    (4, 2): 2, (5, 3): 1,
}

# The largest real discount on the ledger: five systems, three families.
LEDGER_LARGEST_DISCOUNT_WAGER = (
    "10492fa54f9765a1ae3c65266b20ca1a:h2h:9e8d61f45a38abf0")
LEDGER_LARGEST_DISCOUNT_FAMILIES = {
    "fam_56ba4bb647b80640": ("56ba4bb647b80640", "999a7baa84ce385c"),
    "fam_ed2b9ec19d3b9b9a": ("ed2b9ec19d3b9b9a",),
    "fam_market_derived_consensus_h2h_home": (
        "market_derived_consensus_h2h_home", "trivial_always_home"),
}


class LiveLedgerTests(unittest.TestCase):
    """The clustering, checked against measured facts about the real ledger.

    Deliberately NOT the invariants this class used to assert.
    `n_families <= n_systems` is a theorem about `FamilyClustering.__init__`
    (`n_families` counts `families`, `n_systems` counts `family_id_of`, and
    `family_id_of` is built by iterating `families`), so it cannot fail for any
    input and it stayed green with the clustering entirely removed. Everything
    below fails if the merge stops merging, if it merges everything, if either
    relation is switched off, or if the forward filter stops filtering.
    """

    @classmethod
    def setUpClass(cls):
        if not LIVE_LEDGER.exists():
            raise unittest.SkipTest(f"{LIVE_LEDGER} not on disk")
        from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS
        from src.ledger.chain import HashChainLedger
        rows = [r for r in HashChainLedger(LIVE_LEDGER).read()
                if r.get("kind") != "genesis" and "decision_utc" in r]
        cls.n_rows_on_disk = len(rows)
        cls.rows = rows[:LEDGER_MEASURED_ROWS]
        cls.roster = tuple(sorted(s.id for s in REGISTERED_SYSTEMS))
        # REGISTERED_SYSTEMS ONLY -- exactly what production builds
        # (src/cli.py's `engine slip` command). An id that has rotated out of
        # the roster (LEDGER_MEASURED_RETIRED_IN_LEDGER) is simply ABSENT as a
        # key here, matching production exactly; `.get()` reads below turn
        # that absence into families.families's own documented "structure
        # unavailable" handling (`genomes=None` for a system -> an Absence,
        # never a fabricated feature set) rather than a KeyError.
        cls.genomes = {s.id: getattr(s, "genome", None)
                       for s in REGISTERED_SYSTEMS}
        cls.selections = fam.forward_selections(cls.rows, systems=cls.roster)
        cls.clustering = fam.families(cls.selections.selections,
                                      genomes=cls.genomes)

    # -- the fixture itself -------------------------------------------------

    def test_the_measured_prefix_is_still_on_disk_and_unchanged(self):
        """Append-only: the file may have grown, but its first 1,852 decision
        rows are frozen and every expectation below is stated over them."""
        self.assertGreaterEqual(self.n_rows_on_disk, LEDGER_MEASURED_ROWS)
        self.assertEqual(len(self.rows), LEDGER_MEASURED_ROWS)
        shape = collections.Counter(
            (r.get("record_provenance"), r.get("verdict")) for r in self.rows)
        self.assertEqual(dict(shape), LEDGER_MEASURED_PROVENANCE_BY_VERDICT)

    # -- the forward filter -------------------------------------------------

    def test_the_forward_filter_matches_an_independent_parse(self):
        """The expectation is recomputed from string LITERALS, not from
        `fam.FORWARD_RECORD_PROVENANCES` and `fam.PLAYED_VERDICT`. The version
        this replaces used the module's own constants, so adding `None` to that
        set moved the expectation with the code and stayed green."""
        expected_rows = [
            r for r in self.rows
            if r.get("record_provenance") in FORWARD_PROVENANCE_LITERALS
            and r.get("verdict") == PLAYED_VERDICT_LITERAL]
        self.assertEqual(len(expected_rows), LEDGER_MEASURED_FORWARD_ROWS)
        self.assertEqual(self.selections.n_rows_seen, LEDGER_MEASURED_ROWS)
        self.assertEqual(self.selections.n_rows_forward,
                         LEDGER_MEASURED_FORWARD_ROWS)
        self.assertEqual(dict(self.selections.excluded_by_reason), {
            "record_provenance=None": LEDGER_MEASURED_UNSTAMPED_ROWS,
            "record_provenance='replay'": LEDGER_MEASURED_REPLAY_ROWS,
        })

    def test_every_forward_wager_set_matches_the_independent_parse(self):
        """Not just the count: the actual wager ids, per system, rebuilt from
        the raw rows without calling `wager_id`."""
        rebuilt: dict = {}
        for row in self.rows:
            if (row.get("record_provenance") in FORWARD_PROVENANCE_LITERALS
                    and row.get("verdict") == PLAYED_VERDICT_LITERAL):
                rebuilt.setdefault(row["system_id"], set()).add(
                    ":".join((row["event_id"], row["market_key"],
                              row["selection_id"])))
        for system_id, wagers in sorted(rebuilt.items()):
            self.assertEqual(set(self.selections.selections[system_id]),
                             wagers, system_id)
        empty = {s for s, w in self.selections.selections.items() if not w}
        self.assertEqual(set(self.selections.selections) - set(rebuilt), empty)

    def test_the_provenance_half_refuses_194_real_rows(self):
        """The named mutation, priced against the real ledger: dropping the
        provenance check from `is_forward_play` admits 1,103 rows instead of
        909 -- 125 replayed plays (history, amendment 8) and 69 unstamped ones
        (no evidence either way)."""
        both_halves = sum(1 for r in self.rows if fam.is_forward_play(r))
        verdict_half_only = sum(1 for r in self.rows
                                if r.get("verdict") == PLAYED_VERDICT_LITERAL)
        self.assertEqual(both_halves, LEDGER_MEASURED_FORWARD_ROWS)
        self.assertEqual(verdict_half_only, LEDGER_MEASURED_PLAY_ROWS)
        self.assertEqual(verdict_half_only - both_halves, 194)

    # -- the family structure -----------------------------------------------

    def test_the_registered_population_is_the_one_measured(self):
        self.assertEqual(self.roster, LEDGER_MEASURED_ROSTER,
                         "REGISTERED_SYSTEMS changed; re-measure the family "
                         "structure below rather than loosening it")

    def test_the_measured_family_structure_is_reproduced_exactly(self):
        """One assertion that fails under every clustering mutation the
        verifier found: disabling the merge (68 singleton families), collapsing
        it (one family of 68), switching off either relation, and losing
        transitivity all change this tuple."""
        self.assertEqual(self.clustering.families, LEDGER_MEASURED_FAMILIES)
        self.assertEqual(self.clustering.n_families, 38)
        self.assertEqual(self.clustering.n_systems, 68)

    def test_the_measured_basis_of_every_system(self):
        """Why `_FULLY_TESTED_BASES` matters in production: only 3 of the 68
        systems this clustering covers have been compared under BOTH
        relations. The rest are placed on structural identity alone, on
        behavioural agreement alone, or (5 of them) on neither -- a family of
        one by absence of evidence, not by evidence of distinctness."""
        counts = collections.Counter(self.clustering.basis_of.values())
        self.assertEqual(dict(counts), LEDGER_MEASURED_BASIS_COUNTS)

    def test_the_one_behavioural_merge_is_behavioural_and_only_behavioural(self):
        a, b = LEDGER_BEHAVIOURAL_MERGE
        wagers_a = self.selections.selections[a]
        wagers_b = self.selections.selections[b]
        self.assertEqual(len(wagers_a), LEDGER_BEHAVIOURAL_MERGE_WAGERS_EACH)
        self.assertEqual(len(wagers_b), LEDGER_BEHAVIOURAL_MERGE_WAGERS_EACH)
        self.assertEqual(overlap.jaccard(wagers_a, wagers_b), 1.0)
        # .get(), not [a]/[b]: `a` (56ba...) has rotated out of
        # REGISTERED_SYSTEMS (LEDGER_MEASURED_RETIRED_IN_LEDGER), so it is not
        # a key in `self.genomes` at all -- exactly production's shape.
        # `feature_set(None)` is `None` by the module's own contract, and
        # `None != a real frozenset` still proves the point below.
        self.assertNotEqual(fam.feature_set(self.genomes.get(a)),
                            fam.feature_set(self.genomes.get(b)),
                            "if their feature sets were equal this pair would "
                            "prove nothing about the behavioural relation")
        self.assertIn((a, b), self.clustering.behavioural)
        self.assertEqual(self.clustering.family_id(a),
                         self.clustering.family_id(b))

    def test_the_structural_twins_merge_on_structure_alone(self):
        """Each group here is one structural component: same feature set,
        different `routing.market_preference`. Ten are 3-member triads (an
        h2h genome, its F5 twin, and a second F5 genome the enumeration
        happened to place at the same feature set); six are plain pairs.
        Checked pairwise within each group, plus the group as a whole against
        the clustering's own structural components -- not just `assertIn`,
        which silently stops proving anything once a component has more than
        two members (a 2-tuple can never equal a 3-tuple)."""
        structural_components = {tuple(sorted(c))
                                 for c in self.clustering.structural
                                 if len(c) > 1}
        for group in LEDGER_STRUCTURAL_TWINS:
            with self.subTest(group=group):
                for a, b in itertools.combinations(group, 2):
                    self.assertEqual(fam.feature_set(self.genomes.get(a)),
                                     fam.feature_set(self.genomes.get(b)))
                    behavioural_j = overlap.jaccard(
                        self.selections.selections[a],
                        self.selections.selections[b])
                    self.assertLess(
                        behavioural_j, fam.FAMILY_THRESHOLD,
                        "this pair would merge behaviourally too, so it "
                        "cannot pin the structural relation")
                self.assertIn(tuple(sorted(group)), structural_components)
                fids = {self.clustering.family_id(m) for m in group}
                self.assertEqual(len(fids), 1)

    def test_the_cross_relation_family_of_four_is_actually_built(self):
        """`56ba` and `999a` are behavioural twins (five forward wagers each,
        Jaccard exactly 1.0). `999a`, `b0f7` and `f2f0` are a structural
        triad (identical feature set). `56ba` shares neither relation with
        `b0f7` or `f2f0` directly. The live population contains the union
        case chained through `999a`, and it must be one family of four --
        not two families that happen to share a member."""
        self.assertEqual(self.clustering.families[0],
                         ("56ba4bb647b80640", "999a7baa84ce385c",
                          "b0f7d329342ebce1", "f2f0a57586755527"))
        self.assertIn(("56ba4bb647b80640", "999a7baa84ce385c"),
                      self.clustering.behavioural)
        self.assertIn(
            ("999a7baa84ce385c", "b0f7d329342ebce1", "f2f0a57586755527"),
            self.clustering.structural)
        self.assertNotIn(("56ba4bb647b80640", "b0f7d329342ebce1"),
                         self.clustering.behavioural)
        self.assertNotIn(("56ba4bb647b80640", "f2f0a57586755527"),
                         self.clustering.behavioural)
        for c in self.clustering.structural:
            if len(c) > 1:
                self.assertNotIn(
                    "56ba4bb647b80640", c,
                    "56ba's feature set differs from the triad's; it must "
                    "not appear in any MULTI-member structural component "
                    "(its own singleton component is expected and fine)")

    def test_systems_sharing_neither_relation_are_not_one_family(self):
        """The other direction: collapsing the population into a single family
        would satisfy any 'near-duplicates must merge' test on its own."""
        distinct = (("56ba4bb647b80640", "market_derived_consensus_totals_over"),
                    ("ed2b9ec19d3b9b9a", "8974e1cb85d58bcb"),
                    ("trivial_always_home", "trivial_under_total"),
                    ("market_derived_consensus_h2h_away",
                     "market_derived_consensus_h2h_home"))
        for a, b in distinct:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(self.clustering.family_id(a),
                                    self.clustering.family_id(b))

    # -- agreement over the live forward rows -------------------------------

    def test_the_live_discount_has_the_measured_shape(self):
        forward = [r for r in self.rows if fam.is_forward_play(r)]
        counts = fam.agreements_by_selection(forward, self.clustering)
        self.assertEqual(len(counts), LEDGER_MEASURED_FORWARD_WAGERS)
        shape = collections.Counter(
            (a.n_systems, a.n_families) for a in counts.values())
        self.assertEqual(dict(shape), LEDGER_MEASURED_AGREEMENT_SHAPE)

    def test_the_largest_live_discount_is_five_systems_three_families(self):
        forward = [r for r in self.rows if fam.is_forward_play(r)]
        counts = fam.agreements_by_selection(forward, self.clustering)
        result = counts[LEDGER_LARGEST_DISCOUNT_WAGER]
        self.assertEqual(result.n_systems, 5)
        self.assertEqual(result.n_families, 3)
        self.assertEqual(result.n_systems_discounted, 2)
        self.assertEqual(dict(result.families_by_id),
                         LEDGER_LARGEST_DISCOUNT_FAMILIES)

    def test_every_live_agreement_names_a_family_resting_on_absence(self):
        """The live stake of `_FULLY_TESTED_BASES`, measured: all 338 forward
        wagers carry at least one family whose distinctness has never been
        tested, because every market-reference and control system is
        `behavioural_only`. Widening that set would clear the flag on all 338
        at once and nothing on the page would say the evidence changed."""
        forward = [r for r in self.rows if fam.is_forward_play(r)]
        counts = fam.agreements_by_selection(forward, self.clustering)
        flagged = [k for k, a in counts.items()
                   if a.families_resting_on_absence]
        self.assertEqual(len(flagged), LEDGER_MEASURED_FORWARD_WAGERS)


if __name__ == "__main__":
    unittest.main()
