"""The Evolution Lab core: frozen signs, capped genomes, pure decisions.

These are the structural guarantees of docs/EVOLAB_DESIGN.md sections 3, 4 and
12 -- the ones that must hold before any world is ever replayed, because every
number the lab later produces is meaningless if a search process can flip a
sign, exceed the complexity cap, or see an outcome.

Nothing here is evidence, and neither is anything the modules under test
produce.
"""

import hashlib
import json
import os
import pathlib
import random
import subprocess
import sys
import unittest

from src.evolab import bitsets
from src.evolab import decide as decide_mod
from src.evolab import genome as genome_mod
from src.evolab import registry as registry_mod
from src.evolab.decide import NO_PLAY, BoardMeta, WorldView, decide
from src.evolab.genome import GenomeError, validate
from src.evolab.registry import MAX_SIGNALS, RegistryError, SignalRegistry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def small_registry() -> SignalRegistry:
    """Two features, three rungs each -- small enough to count by hand."""
    reg = SignalRegistry()
    reg.register(
        feature="lineup_platoon_share",
        mechanism="a one-handed lineup posted against a starter it holds the "
                  "platoon advantage over",
        direction=+1, ladder=(0.1, 0.2, 0.3), scope="FIRST_FIVE",
        provenance="hand-made for tests, not derived from data")
    reg.register(
        feature="top_minus_bottom",
        mechanism="a top-heavy order concentrates its best bats where the "
                  "extra plate appearances go",
        direction=-1, ladder=(0.01, 0.02, 0.03), scope="FIRST_FIVE",
        provenance="hand-made for tests, not derived from data")
    return reg


# One shared instance for the decide tests. Any freshly built small_registry()
# fingerprints identically -- the check is on content, not identity -- so this
# is a convenience, not a coupling.
SMALL = small_registry()


def decide_small(genome, worldview):
    """decide() against the two-feature test registry."""
    return decide(genome, worldview, registry=SMALL)


def reason_small(genome, worldview):
    """(result, reason) against the two-feature test registry."""
    return decide_mod.decide_with_reason(genome, worldview, registry=SMALL)


def a_genome(signals, *, rule="weighted_sum", k=None, min_score=1.0,
             min_confirmations=1, registry=None, markets=("h2h",),
             min_books=1, require_lineup=False,
             execution=genome_mod.DEFAULT_EXECUTION):
    combination = {"rule": rule}
    if k is not None:
        combination["k"] = k
    return validate({
        "eligibility": {"markets": markets, "min_books": min_books,
                        "require_lineup": require_lineup},
        "signals": signals,
        "combination": combination,
        "entry": {"min_score": min_score,
                  "min_confirmations": min_confirmations},
        "routing": {"market_preference": markets, "f5_condition": "never"},
        "execution": execution,
    }, registry or small_registry())


def a_worldview(features, *, books=("dk", "fd"), available=("h2h",),
                lineup_posted=True, simultaneous=True):
    return WorldView(
        game_id="2024-05-01-CIN-NYM", official_date="2024-05-01",
        commence_time="2024-05-01T23:10:00Z", point_class="LINEUP_POSTED",
        game={"away": "CIN", "home": "NYM", "park": "Citi Field",
              "commence_time": "2024-05-01T23:10:00Z"},
        features=features,
        board={"h2h": {b: {"away": -110, "home": -110} for b in books}},
        board_meta=BoardMeta(observed_utc="2024-05-01T22:40:00Z",
                             books=tuple(books), simultaneous=simultaneous,
                             staleness_seconds=30),
        available=tuple(available), lineup_posted=lineup_posted)


# ---------------------------------------------------------------------------
# Registry: the sign is frozen, and a feature needs a mechanism
# ---------------------------------------------------------------------------

class RegistryTests(unittest.TestCase):
    def test_a_feature_without_a_mechanism_is_refused(self):
        reg = SignalRegistry()
        with self.assertRaises(RegistryError) as caught:
            reg.register(feature="top_minus_bottom", mechanism="",
                         direction=+1, ladder=(1.0, 2.0, 3.0),
                         scope="FIRST_FIVE", provenance="test")
        self.assertIn("mechanism", str(caught.exception))
        self.assertEqual(len(reg), 0)

    def test_a_one_word_mechanism_is_not_a_mechanism(self):
        reg = SignalRegistry()
        with self.assertRaises(RegistryError):
            reg.register(feature="top_minus_bottom", mechanism="momentum",
                         direction=+1, ladder=(1.0, 2.0, 3.0),
                         scope="FIRST_FIVE", provenance="test")

    def test_a_feature_the_matrix_does_not_compute_is_refused(self):
        reg = SignalRegistry()
        with self.assertRaises(RegistryError) as caught:
            reg.register(feature="vibes", mechanism="the boys are locked in "
                         "tonight and you can feel it", direction=+1,
                         ladder=(1.0, 2.0, 3.0), scope="FIRST_FIVE",
                         provenance="test")
        self.assertIn("numeric matrix column", str(caught.exception))

    def test_a_feature_cannot_be_registered_twice(self):
        """The second registration is where a sign gets flipped."""
        reg = small_registry()
        with self.assertRaises(RegistryError) as caught:
            reg.register(feature="top_minus_bottom",
                         mechanism="on reflection the other way round makes "
                                   "more sense",
                         direction=+1, ladder=(0.01, 0.02, 0.03),
                         scope="FIRST_FIVE", provenance="test")
        self.assertIn("frozen", str(caught.exception))
        self.assertEqual(reg.get("top_minus_bottom").direction, -1)

    def test_a_spec_cannot_be_mutated_after_registration(self):
        spec = small_registry().get("top_minus_bottom")
        with self.assertRaises(Exception):
            spec.direction = +1

    def test_direction_must_be_minus_one_or_plus_one(self):
        reg = SignalRegistry()
        for bad in (0, 2, -2, "positive", True, None):
            with self.subTest(direction=bad):
                with self.assertRaises(RegistryError):
                    reg.register(feature="top_minus_bottom",
                                 mechanism="a top-heavy order concentrates "
                                           "its best bats",
                                 direction=bad, ladder=(0.01, 0.02, 0.03),
                                 scope="FIRST_FIVE", provenance="test")

    def test_the_ladder_must_be_three_strictly_increasing_positive_rungs(self):
        reg = SignalRegistry()
        mechanism = "a top-heavy order concentrates its best bats where the "\
                    "plate appearances go"
        for bad in ((0.1, 0.2), (0.1, 0.2, 0.3, 0.4), (0.2, 0.1, 0.3),
                    (0.1, 0.1, 0.3), (0.0, 0.1, 0.2), (-0.1, 0.1, 0.2)):
            with self.subTest(ladder=bad):
                with self.assertRaises(RegistryError):
                    reg.register(feature="top_minus_bottom",
                                 mechanism=mechanism, direction=+1,
                                 ladder=bad, scope="FIRST_FIVE",
                                 provenance="test")

    def test_features_are_sorted_not_insertion_ordered(self):
        """Enumeration order rides on this; insertion order would make the
        enumeration spec hash depend on the order of register() calls."""
        reg = small_registry()
        self.assertEqual(reg.features(),
                         ("lineup_platoon_share", "top_minus_bottom"))
        self.assertEqual(list(reg.features()), sorted(reg.features()))

    def test_the_pair_alphabet_is_every_feature_times_every_rung(self):
        self.assertEqual(len(small_registry().pairs()), 2 * 3)

    def test_side_for_applies_the_frozen_sign(self):
        reg = small_registry()
        positive = reg.get("lineup_platoon_share")   # direction +1
        negative = reg.get("top_minus_bottom")       # direction -1
        self.assertEqual(positive.side_for(0.5), "away")
        self.assertEqual(positive.side_for(-0.5), "home")
        self.assertEqual(negative.side_for(0.5), "home")
        self.assertEqual(negative.side_for(-0.5), "away")

    def test_a_zero_or_absent_differential_points_nowhere(self):
        spec = small_registry().get("lineup_platoon_share")
        self.assertIsNone(spec.side_for(0))
        self.assertIsNone(spec.side_for(None))
        self.assertFalse(spec.fires(None, 0))

    def test_a_threshold_index_outside_the_ladder_is_refused(self):
        spec = small_registry().get("lineup_platoon_share")
        for bad in (-1, 3, 99, "0", True):
            with self.subTest(index=bad):
                with self.assertRaises(RegistryError):
                    spec.threshold(bad)

    def test_the_default_registry_only_names_real_matrix_columns(self):
        from src.research import funnel
        for spec in registry_mod.DEFAULT_REGISTRY.specs():
            self.assertIn(spec.feature, funnel.NUMERIC_FEATURES)
            self.assertIn(spec.direction, (-1, 1))
            self.assertEqual(len(spec.ladder), registry_mod.LADDER_LENGTH)

    def test_starter_platoon_gap_is_deliberately_unregistered(self):
        """Its sign is only meaningful crossed with the lineup's handedness,
        so no standalone direction is true of it. Absence is the honest
        answer, and this test is the record of that decision."""
        self.assertNotIn("starter_platoon_gap",
                         registry_mod.DEFAULT_REGISTRY.features())

    def test_derive_ladder_is_nearest_rank_and_outcome_blind(self):
        values = list(range(1, 11))
        self.assertEqual(registry_mod.derive_ladder(values), (5.0, 8.0, 9.0))
        self.assertEqual(registry_mod.derive_ladder([-v for v in values]),
                         (5.0, 8.0, 9.0))   # magnitudes only
        self.assertIsNone(registry_mod.derive_ladder([]))
        self.assertIsNone(registry_mod.derive_ladder([1.0] * 50))


# ---------------------------------------------------------------------------
# Genome: the three structural refusals
# ---------------------------------------------------------------------------

class GenomeRefusalTests(unittest.TestCase):
    def base(self, **over):
        spec = {
            "eligibility": {"markets": ("h2h",), "min_books": 1,
                            "require_lineup": False},
            "signals": [{"feature": "lineup_platoon_share",
                         "threshold_index": 0, "weight": 1.0}],
            "combination": {"rule": "weighted_sum"},
            "entry": {"min_score": 1.0, "min_confirmations": 1},
            "routing": {"market_preference": ("h2h",),
                        "f5_condition": "never"},
            "execution": "CONSENSUS_EXECUTION",
        }
        spec.update(over)
        return spec

    def test_a_genome_carrying_a_direction_is_refused(self):
        spec = self.base()
        spec["signals"][0]["direction"] = 1
        with self.assertRaises(GenomeError) as caught:
            validate(spec, small_registry())
        self.assertIn("may not carry a direction", str(caught.exception))

    def test_every_direction_shaped_key_is_refused_at_any_depth(self):
        for key in ("sign", "direction", "polarity", "flip", "invert",
                    "negate", "reverse", "side_rule"):
            with self.subTest(key=key):
                spec = self.base()
                spec["routing"][key] = "harmless"
                with self.assertRaises(GenomeError):
                    validate(spec, small_registry())

    def test_a_direction_key_is_refused_even_when_its_value_is_none(self):
        """The refusal is on the KEY: a slot built for a sign is a slot
        something will eventually put a sign in."""
        spec = self.base()
        spec["direction"] = None
        with self.assertRaises(GenomeError):
            validate(spec, small_registry())

    def test_a_negative_weight_is_a_sign_flip_wearing_a_costume(self):
        spec = self.base()
        spec["signals"][0]["weight"] = -1.0
        with self.assertRaises(GenomeError) as caught:
            validate(spec, small_registry())
        self.assertIn("sign flip", str(caught.exception))

    def test_a_zero_weight_is_refused(self):
        spec = self.base()
        spec["signals"][0]["weight"] = 0.0
        with self.assertRaises(GenomeError):
            validate(spec, small_registry())

    def test_an_unregistered_feature_is_refused(self):
        spec = self.base()
        spec["signals"][0]["feature"] = "starter_platoon_gap"
        with self.assertRaises(GenomeError) as caught:
            validate(spec, small_registry())
        self.assertIn("registry", str(caught.exception))

    def test_more_than_max_signals_is_refused(self):
        reg = registry_mod.DEFAULT_REGISTRY
        features = reg.features()[:MAX_SIGNALS + 1]
        spec = self.base(signals=[
            {"feature": f, "threshold_index": 0, "weight": 1.0}
            for f in features])
        with self.assertRaises(GenomeError) as caught:
            validate(spec, reg)
        self.assertIn(f"MAX_SIGNALS={MAX_SIGNALS}", str(caught.exception))

    def test_exactly_max_signals_is_accepted(self):
        reg = registry_mod.DEFAULT_REGISTRY
        spec = self.base(signals=[
            {"feature": f, "threshold_index": 0, "weight": 1.0}
            for f in reg.features()[:MAX_SIGNALS]])
        self.assertEqual(len(validate(spec, reg).signals), MAX_SIGNALS)

    def test_a_duplicate_feature_is_refused_even_at_different_rungs(self):
        spec = self.base(signals=[
            {"feature": "lineup_platoon_share", "threshold_index": 0,
             "weight": 1.0},
            {"feature": "lineup_platoon_share", "threshold_index": 2,
             "weight": 1.0}])
        with self.assertRaises(GenomeError) as caught:
            validate(spec, small_registry())
        self.assertIn("counted twice", str(caught.exception))

    def test_a_signal_with_no_signals_at_all_is_refused(self):
        with self.assertRaises(GenomeError):
            validate(self.base(signals=[]), small_registry())

    def test_an_unknown_signal_field_is_refused(self):
        spec = self.base()
        spec["signals"][0]["lookback_days"] = 30
        with self.assertRaises(GenomeError):
            validate(spec, small_registry())

    def test_an_unreachable_entry_gate_is_refused(self):
        spec = self.base(entry={"min_score": 99.0, "min_confirmations": 1})
        with self.assertRaises(GenomeError) as caught:
            validate(spec, small_registry())
        self.assertIn("never fire", str(caught.exception))

    def test_k_must_fit_the_signals_present(self):
        for k in (0, 2):
            with self.subTest(k=k):
                spec = self.base(combination={"rule": "k_of_n", "k": k},
                                 entry={"min_score": 1.0,
                                        "min_confirmations": 1})
                with self.assertRaises(GenomeError):
                    validate(spec, small_registry())

    def test_signals_are_canonically_ordered_by_feature(self):
        """Two genomes differing only in the order their signals were written
        are the same genome, hash included -- otherwise float accumulation
        order becomes a searchable parameter."""
        written = [{"feature": "top_minus_bottom", "threshold_index": 1,
                    "weight": 2.0},
                   {"feature": "lineup_platoon_share", "threshold_index": 0,
                    "weight": 1.0}]
        forward = validate(self.base(signals=written), small_registry())
        backward = validate(self.base(signals=list(reversed(written))),
                            small_registry())
        self.assertEqual([s.feature for s in forward.signals],
                         ["lineup_platoon_share", "top_minus_bottom"])
        self.assertEqual(forward, backward)
        self.assertEqual(forward.strategy_id, backward.strategy_id)

    def test_a_full_game_mechanism_cannot_be_routed_to_the_first_five(self):
        reg = SignalRegistry()
        reg.register(feature="top_minus_bottom",
                     mechanism="the bullpen gap only resolves over nine full "
                               "innings of play",
                     direction=+1, ladder=(0.01, 0.02, 0.03),
                     scope="FULL_GAME", provenance="test")
        spec = self.base(
            eligibility={"markets": ("h2h", "h2h_1st_5_innings"),
                         "min_books": 1, "require_lineup": False},
            signals=[{"feature": "top_minus_bottom", "threshold_index": 0,
                      "weight": 1.0}],
            routing={"market_preference": ("h2h_1st_5_innings", "h2h"),
                     "f5_condition": "if_all_signals_first_five"})
        with self.assertRaises(GenomeError) as caught:
            validate(spec, reg)
        self.assertIn("nine innings", str(caught.exception))

    def test_preferring_an_ineligible_market_is_refused(self):
        spec = self.base(routing={
            "market_preference": ("h2h_1st_5_innings",),
            "f5_condition": "if_all_signals_first_five"})
        with self.assertRaises(GenomeError):
            validate(spec, small_registry())


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

class EnumerationTests(unittest.TestCase):
    def test_a_two_feature_registry_enumerates_the_hand_counted_space(self):
        """2 features x 3 rungs.

        n=1: 6 (feature, rung) pairs x 1 body (weighted_sum, weight 1.0,
             min_score 1.0; k_of_n at n=1 is the same genome and is skipped)
        n=2: 1 feature pair x 9 rung pairs = 9 signal sets, x 10 bodies
             (weighted_sum: (1,1)->2 min_scores, (2,1)->3, (1,2)->3 = 8;
              k_of_n: k=1,2 = 2) = 90
        """
        space = genome_mod.enumerate_genomes(small_registry())
        self.assertEqual(len(space), 96)
        self.assertEqual(
            len(genome_mod.enumerate_genomes(small_registry(),
                                             max_signals=1)), 6)

    def test_the_default_space_is_the_designs_order_of_magnitude(self):
        space = genome_mod.enumerate_genomes()
        self.assertEqual(len(space), 11088)
        self.assertTrue(1000 <= len(space) <= 100000)

    def test_no_enumerated_genome_exceeds_the_complexity_cap(self):
        for g in genome_mod.enumerate_genomes(small_registry()):
            self.assertLessEqual(len(g.signals), MAX_SIGNALS)
            self.assertTrue(all(s.weight > 0 for s in g.signals))

    def test_enumeration_order_is_identical_on_repeat_calls(self):
        first = genome_mod.enumerate_genomes(small_registry())
        second = genome_mod.enumerate_genomes(small_registry())
        self.assertEqual([g.strategy_id for g in first],
                         [g.strategy_id for g in second])

    def test_enumeration_order_survives_a_different_hash_seed(self):
        """The real determinism risk is set and dict iteration order, which
        PYTHONHASHSEED perturbs between PROCESSES, not between calls. So this
        one runs in subprocesses."""
        program = (
            "import hashlib;"
            "from src.evolab import genome, registry;"
            "import tests.test_evolab_core as t;"
            "ids=''.join(g.strategy_id for g in "
            "genome.enumerate_genomes(t.small_registry()));"
            "print(hashlib.sha256(ids.encode()).hexdigest())")
        digests = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run([sys.executable, "-c", program],
                                 cwd=REPO_ROOT, env=env, capture_output=True,
                                 text=True, check=True)
            digests.add(out.stdout.strip())
        self.assertEqual(len(digests), 1, f"order drifted: {digests}")

    def test_signal_order_within_a_genome_is_sorted(self):
        for g in genome_mod.enumerate_genomes(small_registry()):
            features = [s.feature for s in g.signals]
            self.assertEqual(features, sorted(features))

    def test_no_enumerated_gate_is_unreachable(self):
        for g in genome_mod.enumerate_genomes(small_registry()):
            reachable = (sum(s.weight for s in g.signals)
                         if g.combination.rule == "weighted_sum"
                         else float(len(g.signals)))
            self.assertLessEqual(g.entry.min_score, reachable)

    def test_the_spec_hash_is_stable_and_moves_when_the_space_moves(self):
        reg = small_registry()
        base = genome_mod.spec_hash(genome_mod.enumeration_spec(reg))
        self.assertEqual(
            base, genome_mod.spec_hash(genome_mod.enumeration_spec(reg)))
        narrower = genome_mod.spec_hash(
            genome_mod.enumeration_spec(reg, max_signals=1))
        self.assertNotEqual(base, narrower)

    def test_the_spec_hash_moves_when_a_ladder_moves(self):
        """A run whose ladders changed enumerated a different space and must
        not be compared with an earlier one as though it had not."""
        moved = SignalRegistry()
        moved.register(feature="lineup_platoon_share",
                       mechanism="a one-handed lineup posted against a "
                                 "starter it holds the advantage over",
                       direction=+1, ladder=(0.1, 0.2, 0.35),
                       scope="FIRST_FIVE", provenance="test")
        moved.register(feature="top_minus_bottom",
                       mechanism="a top-heavy order concentrates its best "
                                 "bats where the appearances go",
                       direction=-1, ladder=(0.01, 0.02, 0.03),
                       scope="FIRST_FIVE", provenance="test")
        self.assertNotEqual(
            genome_mod.spec_hash(
                genome_mod.enumeration_spec(small_registry())),
            genome_mod.spec_hash(genome_mod.enumeration_spec(moved)))

    def test_the_spec_hash_records_the_frozen_directions(self):
        spec = genome_mod.enumeration_spec(small_registry())
        directions = {e["feature"]: e["direction"] for e in spec["registry"]}
        self.assertEqual(directions,
                         {"lineup_platoon_share": 1, "top_minus_bottom": -1})


# ---------------------------------------------------------------------------
# WorldView: the future is absent, not filtered
# ---------------------------------------------------------------------------

class WorldViewTests(unittest.TestCase):
    def test_the_worldview_exposes_no_outcome_and_no_closing_price(self):
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.2})
        for name in ("outcome", "result", "winner", "home_won", "final_score",
                     "closing_price", "closing_line", "close", "clv"):
            with self.subTest(attribute=name):
                with self.assertRaises(AttributeError) as caught:
                    getattr(wv, name)
                self.assertIn("construction", str(caught.exception))

    def test_an_outcome_cannot_be_attached_after_construction(self):
        wv = a_worldview({})
        with self.assertRaises(Exception):
            wv.outcome = 1
        with self.assertRaises(Exception):
            wv.anything_at_all = 1

    def test_a_feature_named_like_an_outcome_is_refused_at_construction(self):
        with self.assertRaises(decide_mod.WorldViewError):
            a_worldview({"outcome": 1})
        with self.assertRaises(decide_mod.WorldViewError):
            a_worldview({"closing_price": -120})

    def test_an_ordinary_missing_attribute_still_reads_as_missing(self):
        wv = a_worldview({})
        with self.assertRaises(AttributeError):
            wv.park_factor

    def test_the_differential_is_away_minus_home_and_none_over_guess(self):
        wv = a_worldview({"away_top_minus_bottom": 0.05,
                          "home_top_minus_bottom": 0.02,
                          "away_lineup_platoon_share": 0.6})
        self.assertAlmostEqual(wv.differential("top_minus_bottom"), 0.03)
        self.assertIsNone(wv.differential("lineup_platoon_share"))
        self.assertIsNone(wv.differential("primary_pitch_share"))


# ---------------------------------------------------------------------------
# decide(): pure, deterministic, and explicit about ties
# ---------------------------------------------------------------------------

class DecideTests(unittest.TestCase):
    def test_the_same_genome_and_worldview_decide_identically_twice(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0}])
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.2})
        first, second = decide_small(g, wv), decide_small(g, wv)
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first.__dict__, sort_keys=True,
                                    default=list),
                         json.dumps(second.__dict__, sort_keys=True,
                                    default=list))

    def test_the_frozen_sign_decides_the_side(self):
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.2,
                          "away_top_minus_bottom": 0.05,
                          "home_top_minus_bottom": 0.0})
        positive = a_genome([{"feature": "lineup_platoon_share",
                              "threshold_index": 0, "weight": 1.0}])
        negative = a_genome([{"feature": "top_minus_bottom",
                              "threshold_index": 0, "weight": 1.0}])
        # Both differentials favour AWAY numerically; the -1 feature's frozen
        # mechanism says the side holding more of it is the harmed one.
        self.assertEqual(decide_small(positive, wv).side, "away")
        self.assertEqual(decide_small(negative, wv).side, "home")

    def test_a_differential_below_the_rung_does_not_fire(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 2, "weight": 1.0}])
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.45})  # d = 0.15 < 0.3
        result, reason = reason_small(g, wv)
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.NO_SIGNAL)

    def test_an_unmeasured_feature_is_no_play_not_a_zero(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0}])
        result, reason = reason_small(
            g, a_worldview({"away_lineup_platoon_share": 0.6}))
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.NO_SIGNAL)

    def test_equal_and_opposite_signals_refuse_rather_than_pick_a_side(self):
        """Rule 4 of the tie-break: a coin flip would manufacture selections
        the strategy never made, and half of them would win."""
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0},
                      {"feature": "top_minus_bottom", "threshold_index": 0,
                       "weight": 1.0}],
                     rule="k_of_n", k=1, min_score=1.0, min_confirmations=1)
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.2,
                          "away_top_minus_bottom": 0.05,
                          "home_top_minus_bottom": 0.0})
        result, reason = reason_small(g, wv)
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.CONFLICTING_SIGNALS)

    def test_the_heavier_side_wins_a_conflict(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 2.0},
                      {"feature": "top_minus_bottom", "threshold_index": 0,
                       "weight": 1.0}], min_score=1.0)
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.2,
                          "away_top_minus_bottom": 0.05,
                          "home_top_minus_bottom": 0.0})
        decision = decide_small(g, wv)
        self.assertEqual(decision.side, "away")
        self.assertEqual(decision.score, 2.0)
        self.assertEqual(decision.signals_fired,
                         (("lineup_platoon_share", 0),))

    def test_k_of_n_counts_confirmations_and_ignores_magnitudes(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0},
                      {"feature": "top_minus_bottom", "threshold_index": 0,
                       "weight": 1.0}],
                     rule="k_of_n", k=2, min_score=2.0, min_confirmations=2)
        both_away = a_worldview({"away_lineup_platoon_share": 0.6,
                                 "home_lineup_platoon_share": 0.2,
                                 "away_top_minus_bottom": 0.0,
                                 "home_top_minus_bottom": 0.05})
        self.assertEqual(decide_small(g, both_away).side, "away")
        self.assertEqual(decide_small(g, both_away).score, 2.0)

        only_one = a_worldview({"away_lineup_platoon_share": 0.6,
                                "home_lineup_platoon_share": 0.2,
                                "away_top_minus_bottom": 0.0,
                                "home_top_minus_bottom": 0.0})
        result, reason = reason_small(g, only_one)
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.BELOW_ENTRY)

    def test_a_thin_board_is_no_play(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0}], min_books=5)
        result, reason = reason_small(
            g, a_worldview({"away_lineup_platoon_share": 0.6,
                            "home_lineup_platoon_share": 0.2}))
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.INSUFFICIENT_BOOKS)

    def test_an_unavailable_market_is_no_play(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0}])
        result, reason = reason_small(
            g, a_worldview({"away_lineup_platoon_share": 0.6,
                            "home_lineup_platoon_share": 0.2},
                           available=()))
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.MARKET_UNAVAILABLE)

    def test_require_lineup_stands_down_before_the_lineup_is_posted(self):
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0}],
                     require_lineup=True)
        result, reason = reason_small(
            g, a_worldview({"away_lineup_platoon_share": 0.6,
                            "home_lineup_platoon_share": 0.2},
                           lineup_posted=False))
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.NO_LINEUP)

    def test_best_observed_execution_refuses_a_stitched_board(self):
        """Design section 5: a best price across quotes taken at different
        instants is not a price anybody could have taken."""
        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 0, "weight": 1.0}],
                     execution="BEST_OBSERVED_EXECUTION")
        features = {"away_lineup_platoon_share": 0.6,
                    "home_lineup_platoon_share": 0.2}
        result, reason = reason_small(
            g, a_worldview(features, simultaneous=False))
        self.assertIs(result, NO_PLAY)
        self.assertEqual(reason, decide_mod.NOT_SIMULTANEOUS)
        self.assertIsNot(
            decide_small(g, a_worldview(features, simultaneous=True)),
            NO_PLAY)

    def test_decide_refuses_a_registry_the_genome_was_not_built_on(self):
        """The regression this test pins was a real bug in this file's first
        draft: a genome validated against the two-feature test registry was
        being decided against the default one, where top_minus_bottom carries
        the opposite frozen sign. It picked the other side and looked fine."""
        g = a_genome([{"feature": "top_minus_bottom", "threshold_index": 0,
                       "weight": 1.0}], registry=SMALL)
        wv = a_worldview({"away_top_minus_bottom": 0.05,
                          "home_top_minus_bottom": 0.0})
        self.assertEqual(decide_small(g, wv).side, "home")
        with self.assertRaises(ValueError) as caught:
            decide(g, wv, registry=registry_mod.DEFAULT_REGISTRY)
        self.assertIn("validated against registry", str(caught.exception))

    def test_a_genome_carrying_a_foreign_registry_fingerprint_is_refused(self):
        spec = a_genome([{"feature": "top_minus_bottom",
                          "threshold_index": 0, "weight": 1.0}],
                        registry=SMALL).to_dict()
        spec["registry_fingerprint"] = "0000000000000000"
        with self.assertRaises(GenomeError) as caught:
            validate(spec, SMALL)
        self.assertIn("different strategy", str(caught.exception))

    def test_two_registries_with_identical_contents_are_interchangeable(self):
        self.assertEqual(small_registry().fingerprint(),
                         small_registry().fingerprint())
        self.assertNotEqual(small_registry().fingerprint(),
                            registry_mod.DEFAULT_REGISTRY.fingerprint())

    def test_decide_refuses_an_unvalidated_genome(self):
        with self.assertRaises(TypeError):
            decide({"signals": []}, a_worldview({}), registry=SMALL)

    def test_decide_reads_no_clock_and_no_randomness(self):
        """Purity by inspection: the module imports nothing that could make
        two identical calls differ."""
        source = pathlib.Path(decide_mod.__file__).read_text(encoding="utf-8")
        for banned in ("import random", "import time", "import datetime",
                       "open(", "requests"):
            self.assertNotIn(banned, source)

    def test_the_whole_space_decides_identically_on_a_repeat_sweep(self):
        wv = a_worldview({"away_lineup_platoon_share": 0.6,
                          "home_lineup_platoon_share": 0.2,
                          "away_top_minus_bottom": 0.05,
                          "home_top_minus_bottom": 0.0})
        reg = small_registry()
        space = genome_mod.enumerate_genomes(reg)

        def sweep():
            out = []
            for g in space:
                d = decide(g, wv, registry=reg)
                out.append("NO_PLAY" if d is NO_PLAY else
                           f"{d.market}|{d.side}|{d.score!r}"
                           f"|{d.signals_fired}")
            return hashlib.sha256("\n".join(out).encode()).hexdigest()

        self.assertEqual(sweep(), sweep())


# ---------------------------------------------------------------------------
# Bitsets: fast path must equal the slow path
# ---------------------------------------------------------------------------

def naive_signal_masks(differentials, threshold, direction):
    """The obvious implementation: the thing the fast one must match."""
    away, home = set(), set()
    for i, d in enumerate(differentials):
        if d is None or abs(d) < threshold or d == 0:
            continue
        (away if d * direction > 0 else home).add(i)
    return away, home


def as_set(mask):
    return {i for i in range(mask.bit_length()) if mask >> i & 1}


class BitsetTests(unittest.TestCase):
    def test_masks_match_the_naive_reference_on_random_worlds(self):
        rng = random.Random(20260831)
        for trial in range(200):
            n = rng.randrange(1, 60)
            diffs = [None if rng.random() < 0.2
                     else round(rng.uniform(-1.0, 1.0), 4) for _ in range(n)]
            threshold = round(rng.uniform(0.05, 0.9), 4)
            direction = rng.choice((-1, 1))
            with self.subTest(trial=trial):
                away, home = bitsets.signal_masks(diffs, threshold, direction)
                exp_away, exp_home = naive_signal_masks(diffs, threshold,
                                                        direction)
                self.assertEqual(as_set(away), exp_away)
                self.assertEqual(as_set(home), exp_home)
                self.assertEqual(away & home, 0)   # disjoint by construction

    def test_combination_matches_the_naive_reference_on_random_cases(self):
        rng = random.Random(7)
        for trial in range(400):
            n_games = rng.randrange(1, 80)
            n_masks = rng.randrange(1, 4)
            sets = [{i for i in range(n_games) if rng.random() < 0.4}
                    for _ in range(n_masks)]
            masks = [bitsets.mask_from_indices(s) for s in sets]
            with self.subTest(trial=trial):
                self.assertEqual(as_set(bitsets.combine_and(masks)),
                                 set.intersection(*sets))
                self.assertEqual(as_set(bitsets.combine_or(masks)),
                                 set.union(*sets))
                k = rng.randrange(1, n_masks + 1)
                expected = {i for i in range(n_games)
                            if sum(i in s for s in sets) >= k}
                self.assertEqual(as_set(bitsets.combine_k_of_n(masks, k)),
                                 expected)

    def test_an_empty_intersection_is_empty_not_the_universe(self):
        self.assertEqual(bitsets.combine_and([]), 0)
        self.assertEqual(bitsets.combine_or([]), 0)

    def test_set_bits_come_out_ascending_and_complete(self):
        rng = random.Random(99)
        for _ in range(50):
            indices = sorted({rng.randrange(0, 200) for _ in range(20)})
            mask = bitsets.mask_from_indices(indices)
            self.assertEqual(list(bitsets.iter_set_bits(mask)), indices)
            self.assertEqual(bitsets.count_bits(mask), len(indices))

    def test_sum_over_mask_matches_an_ordered_reference(self):
        rng = random.Random(4242)
        for _ in range(100):
            n = rng.randrange(1, 120)
            values = [round(rng.uniform(-3, 3), 6) for _ in range(n)]
            chosen = sorted({rng.randrange(0, n) for _ in range(n // 3 + 1)})
            mask = bitsets.mask_from_indices(chosen)
            expected = 0.0
            for i in chosen:
                expected += values[i]
            self.assertEqual(bitsets.sum_over_mask(mask, values), expected)

    def test_a_mask_reaching_past_the_value_vector_is_refused(self):
        with self.assertRaises(bitsets.BitsetError):
            bitsets.sum_over_mask(bitsets.mask_from_indices([9]), [1.0, 2.0])

    def test_a_none_value_under_the_mask_is_refused_not_read_as_zero(self):
        with self.assertRaises(bitsets.BitsetError):
            bitsets.sum_over_mask(bitsets.mask_from_indices([1]),
                                  [1.0, None, 3.0])

    def test_a_negative_game_index_is_refused(self):
        with self.assertRaises(bitsets.BitsetError):
            bitsets.mask_from_indices([-1])

    def test_the_table_skips_features_the_world_could_not_compute(self):
        reg = small_registry()
        table = bitsets.build_signal_mask_table(
            reg, {"lineup_platoon_share": [0.5, -0.5, None, 0.05]})
        self.assertEqual(sorted(table), [("lineup_platoon_share", i)
                                         for i in range(3)])
        away, home = table[("lineup_platoon_share", 0)]   # rung 0.1, sign +1
        self.assertEqual(as_set(away), {0})
        self.assertEqual(as_set(home), {1})

    def test_the_bitset_path_agrees_with_decide_over_a_whole_world(self):
        """The engine and the readable implementation must select the same
        games; a fast path that quietly disagrees is worse than none."""
        rng = random.Random(1234)
        reg = small_registry()
        n = 300
        diffs = {f: [None if rng.random() < 0.15
                     else round(rng.uniform(-0.6, 0.6), 4) for _ in range(n)]
                 for f in reg.features()}
        table = bitsets.build_signal_mask_table(reg, diffs)

        g = a_genome([{"feature": "lineup_platoon_share",
                       "threshold_index": 1, "weight": 1.0},
                      {"feature": "top_minus_bottom", "threshold_index": 0,
                       "weight": 1.0}],
                     rule="k_of_n", k=2, min_score=2.0, min_confirmations=2,
                     registry=reg)

        by_bitset = {}
        for side_index, side in enumerate(("away", "home")):
            masks = [table[(s.feature, s.threshold_index)][side_index]
                     for s in g.signals]
            for i in bitsets.iter_set_bits(bitsets.combine_and(masks)):
                by_bitset[i] = side

        by_decide = {}
        for i in range(n):
            features = {}
            for f in reg.features():
                if diffs[f][i] is not None:
                    features["away_" + f] = diffs[f][i]
                    features["home_" + f] = 0.0
            d = decide(g, a_worldview(features), registry=reg)
            if d is not NO_PLAY:
                by_decide[i] = d.side

        self.assertEqual(by_bitset, by_decide)
        self.assertTrue(by_decide, "the fixture selected nothing to compare")


if __name__ == "__main__":
    unittest.main()
