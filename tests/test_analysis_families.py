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
  * merging without transitivity (A~B, B~C, A and C reported separately),
  * treating "structure unknown" as an empty feature set (two absences
    fabricating a family),
  * counting replayed or unprovenanced rows as forward evidence,
  * counting refusals as decisions,
  * counting one system's repeated decisions as several,
  * reporting `n_families` without `n_systems`.

The last test reads the REAL forward ledger, if it is on disk, and asserts the
invariants that must hold whatever the data says. It never asserts a specific
family count: that number moves every night, and a test that pins it would be
a test of today's data rather than of this module.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.analysis import families as fam
from src.evolab import overlap
from src.ledger.records import (
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
        predates the field and must never read as pre-commitment confirmed.
        818 of the rows on disk are in that state."""
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
        """An empty set compares EQUAL to another empty set under identity,
        so returning one for 'unknown' would merge two systems whose structure
        nobody knows -- a family fabricated out of two absences."""
        self.assertIsNone(fam.feature_set(None))

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

    def test_two_unknown_structures_are_not_a_family(self):
        result = fam.families({"a": frozenset(), "b": frozenset()},
                              genomes={"a": None, "b": None})
        self.assertEqual(result.n_families, 2)
        self.assertEqual(result.basis_of["a"], fam.BASIS_UNCLUSTERABLE)
        kinds = {(x.subject, x.kind) for x in result.absences}
        self.assertIn(("a", fam.ABSENCE_STRUCTURE_UNAVAILABLE), kinds)
        self.assertIn(("b", fam.ABSENCE_STRUCTURE_UNAVAILABLE), kinds)


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

    def test_family_resting_on_absence_is_flagged(self):
        """`b` has never fired and has no known structure: it is a family of
        one by absence of evidence, and the count must say so."""
        clustering = fam.families({"a": frozenset({"w1"}), "b": frozenset()},
                                  genomes={"a": _FakeGenome("f1"), "b": None})
        result = fam.agreement([_rec("a"), _rec("b")], clustering)
        self.assertEqual(result.n_families, 2)
        self.assertEqual(result.families_resting_on_absence, ("fam_b",))
        self.assertEqual(result.basis_by_system["b"], fam.BASIS_UNCLUSTERABLE)
        self.assertTrue(any(x.kind == fam.ABSENCE_FAMILY_UNTESTED
                            for x in result.absences))

    def test_a_fully_tested_family_is_not_flagged(self):
        clustering = _two_family_clustering()
        result = fam.agreement([_rec("a"), _rec("c")], clustering)
        self.assertEqual(result.families_resting_on_absence, ())

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


# ---------------------------------------------------------------------------
# The real ledger
# ---------------------------------------------------------------------------

class LiveLedgerTests(unittest.TestCase):
    """Invariants over the REAL forward ledger. No specific family count is
    asserted -- that number moves every night, and pinning it would test
    today's data instead of this module."""

    @classmethod
    def setUpClass(cls):
        if not LIVE_LEDGER.exists():
            raise unittest.SkipTest(f"{LIVE_LEDGER} not on disk")
        from src.ledger.chain import HashChainLedger
        cls.rows = [r for r in HashChainLedger(LIVE_LEDGER).read()
                    if r.get("kind") != "genesis" and "decision_utc" in r]

    def _clustering(self):
        from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS
        genomes = {s.id: getattr(s, "genome", None) for s in REGISTERED_SYSTEMS}
        selections = fam.forward_selections(
            self.rows, systems=[s.id for s in REGISTERED_SYSTEMS])
        return selections, fam.families(selections.selections, genomes=genomes)

    def test_every_registered_system_is_placed_in_exactly_one_family(self):
        from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS
        _, clustering = self._clustering()
        for system in REGISTERED_SYSTEMS:
            self.assertIn(system.id, clustering.family_id_of)
        placements = [m for members in clustering.families for m in members]
        self.assertEqual(len(placements), len(set(placements)),
                         "a system in two families is not a partition")

    def test_family_count_never_exceeds_system_count(self):
        _, clustering = self._clustering()
        self.assertLessEqual(clustering.n_families, clustering.n_systems)
        self.assertGreaterEqual(clustering.n_families, 1)

    def test_forward_filter_excludes_the_unstamped_and_replayed_rows(self):
        selections, _ = self._clustering()
        forward = [r for r in self.rows
                   if r.get("record_provenance") in fam.FORWARD_RECORD_PROVENANCES
                   and r.get("verdict") == fam.PLAYED_VERDICT]
        self.assertEqual(selections.n_rows_forward, len(forward))
        self.assertLess(selections.n_rows_forward, selections.n_rows_seen,
                        "the ledger holds replayed and unstamped rows; if "
                        "these are equal the forward filter stopped filtering")

    def test_every_live_agreement_count_is_at_most_its_system_count(self):
        _, clustering = self._clustering()
        forward = [r for r in self.rows if fam.is_forward_play(r)]
        counts = fam.agreements_by_selection(forward, clustering)
        self.assertTrue(counts, "no forward plays found in the live ledger")
        for key, result in counts.items():
            self.assertGreaterEqual(result.n_systems, result.n_families, key)
            self.assertGreaterEqual(result.n_families, 1, key)


if __name__ == "__main__":
    unittest.main()
