"""Validation check 6: the spec compiler against hand-written logic.

WHY THIS CHECK EXISTS
---------------------
funnel._selections_for is a compiler: a spec dict goes in, graded selections
come out. Every funnel level, the battery, and the family correction all
consume its output, so if the compiler's reading of a spec ever drifts from
what the spec SAYS -- a flipped sign, an off-by-one threshold comparison, a
grade against the wrong snapshot -- every downstream number stays perfectly
plausible while quietly measuring a different experiment. The only defence is
an evaluation that shares no code with the compiler: the direct loops below
re-derive the signal, the side, the join, the grade and the effect from the
same raw inputs, and the two paths must agree exactly.

WHAT "INDEPENDENT" MEANS HERE
-----------------------------
The hand path imports nothing from funnel.py. It does reuse the World fixture
(the raw inputs BOTH paths consume) and selections._resolve_pair and
selections._fair -- deliberately, because the price join is selections.py's
property, validated by its own tests; re-implementing it here would test the
re-implementation, not the compiler. Everything the funnel ADDS on top of
that join -- away-minus-home signal, threshold gate, direction resolution,
close-snapshot grading, win labelling, the effect mean -- is re-derived by
hand, one rule per line.

The world is built so every measured quantity is an exact binary fraction
(implied exactly 0.5 from -110/-110, sample sizes powers of two), so "agree
to 10 decimal places" is not asking two float pipelines to coincide by luck
-- any disagreement is a logic difference, never rounding noise.
"""

from __future__ import annotations

import unittest

from src.data import parks
from src.model import selections
from src.research import funnel
from tests.test_funnel import CANDIDATE_TEAMS, FEATURES, OPPONENT, World, _spec

# One feature carries the whole experiment; WHICH one is irrelevant to the
# equivalence question, so the fixture's candidate feature is reused.
FEATURE = FEATURES["candidate"]

# The spec threshold and the diagnostic half-threshold, stated here
# independently of funnel's constants -- the hand path must encode what the
# spec SAYS, not what funnel.py computes, or the comparison proves nothing.
THRESHOLD = 0.1
HALF = THRESHOLD * 0.5


def _equivalence_world():
    """A single-season world exercising every branch the compiler can take.

    16 selected games -- 8 with the signal on the away side and 8 on the home
    side, so BOTH sign branches of side resolution carry real weight -- plus
    three games in the diagnostic band [half-threshold, threshold), two under
    the half-threshold, and one with the feature unreadable. Win counts are
    chosen so the positive-direction effect is exactly +0.125 and the
    negative-direction effect exactly -0.125 (16 = 2**4 keeps the mean an
    exact binary fraction), which lets the test also assert the hand path
    measured the world it was built in -- a shared bug in BOTH paths (say an
    inverted won) would otherwise still "agree".
    """
    world = World()
    pks = {"away_adv": [], "home_adv": [], "band": [], "under": [], "none": []}

    def game(day, away_full, home_full, home_won, away_val, home_val, bucket):
        # World.add_game builds the join-critical parts (price pair, result,
        # canonical spellings) but only knows the fixture's one signal shape:
        # the dose on the away side. The equivalence world needs the signal
        # on EITHER side and at sub-threshold magnitudes, so the two feature
        # columns are overwritten on the freshly appended matrix row --
        # extending the fixture's world, never touching its join machinery.
        world.add_game(2023, day, away_full, home_full, home_won=home_won)
        row = world.matrix[2023][-1]
        row["away_" + FEATURE] = away_val
        row["home_" + FEATURE] = home_val
        pks[bucket].append(row["game_pk"])

    # Signal on the AWAY side (value +0.25): the backed-away side wins 6 of 8.
    for i in range(8):
        game(i, CANDIDATE_TEAMS[i % 6], OPPONENT, home_won=i >= 6,
             away_val=0.25, home_val=0.0, bucket="away_adv")
    # Signal on the HOME side (value -0.25): the backed-home side wins 4 of 8.
    for i in range(8):
        game(10 + i, OPPONENT, CANDIDATE_TEAMS[i % 6], home_won=i < 4,
             away_val=0.0, home_val=0.25, bucket="home_adv")
    # The diagnostic band [0.05, 0.1): graded, never selected. The 0.05 row
    # sits exactly on the half-threshold edge to pin the >= convention.
    game(20, CANDIDATE_TEAMS[0], OPPONENT, True, 0.07, 0.0, "band")
    game(21, OPPONENT, CANDIDATE_TEAMS[1], False, 0.0, 0.06, "band")
    game(22, CANDIDATE_TEAMS[2], OPPONENT, True, 0.05, 0.0, "band")
    # Under the half-threshold: invisible even to the wide sample.
    game(25, CANDIDATE_TEAMS[3], OPPONENT, True, 0.02, 0.0, "under")
    game(26, OPPONENT, CANDIDATE_TEAMS[4], False, 0.0, 0.03, "under")
    # Feature unreadable on one side: no selection -- half a differential is
    # not a differential, and neither path may guess.
    game(28, CANDIDATE_TEAMS[5], OPPONENT, True, None, 0.0, "none")
    return world, pks


def _hand_rows(world, direction):
    """The spec evaluated by hand: direct loops, nothing from funnel.py.

    Every rule the spec states is applied literally, in order: value =
    away - home; |value| >= HALF fires into the wide graded sample and
    |value| >= THRESHOLD marks it selected; a positive value advantages away,
    negative home; direction "positive" backs the advantaged side, "negative"
    the other; the price joins through selections._resolve_pair; the grade is
    the consensus fair from the CLOSE snapshot; won inverts home_won for an
    away pick. That is the entire experiment -- anything the compiler does
    beyond this list is the drift this check exists to catch.
    """
    index = selections.index_price_pairs(world.pairs[2023])
    out = []
    for row in world.matrix[2023]:
        away, home = row["away_" + FEATURE], row["home_" + FEATURE]
        if away is None or home is None:  # the world holds floats or None
            continue
        value = away - home
        if abs(value) < HALF:
            continue
        advantaged = "away" if value > 0 else "home"
        if direction == "positive":
            side = advantaged
        else:
            side = "home" if advantaged == "away" else "away"
        key = (parks.canonical_team(row["away_team"]),
               parks.canonical_team(row["home_team"]), row["date"])
        pair = selections._resolve_pair(index.get(key), row)
        if not pair or not pair.get("distinct"):
            continue
        grading = selections._fair(pair["close"]["bookmakers"],
                                   pair["home_team"], pair["away_team"])
        if not grading:
            continue
        home_won = world.results[row["game_pk"]]["home_won"] == "1"
        out.append({
            "game_pk": row["game_pk"],
            "side": side,
            # The selection contract publishes implied at 5 decimals; in this
            # world the fair is exactly 0.5, so the rounding is inert and the
            # comparison below is exact either way.
            "implied": round(grading["home_fair"] if side == "home"
                             else grading["away_fair"], 5),
            "won": home_won if side == "home" else not home_won,
            "selected": abs(value) >= THRESHOLD,
        })
    return out


def _hand_effect(rows):
    """mean(won - implied) over SELECTED rows only -- the band rows are dose
    diagnostics for the battery and must never enter the measurement."""
    graded = [(1.0 if r["won"] else 0.0) - r["implied"]
              for r in rows if r["selected"]]
    return sum(graded) / len(graded)


class CompilerEquivalenceTests(unittest.TestCase):
    """funnel._selections_for + _measure against the hand evaluation."""

    @classmethod
    def setUpClass(cls):
        cls.world, cls.pks = _equivalence_world()
        cls.index = selections.index_price_pairs(cls.world.pairs[2023])

    def _funnel_rows(self, direction):
        spec = funnel.validate_spec(_spec(direction, FEATURE,
                                          direction=direction))
        # fraction=0.5 is the compiler's own diagnostic pass -- the one whose
        # output feeds both the levels (selected rows) and the battery's dose
        # bands (all rows), so it is the one worth proving equivalent.
        return funnel._selections_for(spec, self.world.matrix[2023],
                                      self.index, self.world.results, 2023,
                                      fraction=0.5)

    def _assert_equivalent(self, direction, expected_effect):
        hand = _hand_rows(self.world, direction)
        compiled = self._funnel_rows(direction)

        # Identical populations, wide and selected: a compiler that fires on
        # different games is a different experiment before any grading runs.
        self.assertEqual({r["game_pk"] for r in compiled},
                         {r["game_pk"] for r in hand})
        self.assertEqual({r["game_pk"] for r in compiled if r["selected"]},
                         {r["game_pk"] for r in hand if r["selected"]})

        # Row for row: same side, same implied, same grade, same selected
        # flag. The set equality above guarantees no compiled extras.
        by_pk = {r["game_pk"]: r for r in compiled}
        for r in hand:
            got = by_pk[r["game_pk"]]
            self.assertEqual(got["side"], r["side"], r["game_pk"])
            self.assertEqual(got["implied"], r["implied"], r["game_pk"])
            self.assertEqual(got["won"], r["won"], r["game_pk"])
            self.assertEqual(got["selected"], r["selected"], r["game_pk"])

        n, effect, _ = funnel._measure([r for r in compiled if r["selected"]])
        self.assertEqual(n, sum(1 for r in hand if r["selected"]))
        self.assertAlmostEqual(effect, _hand_effect(hand), places=10)
        # And the hand path measured the world it was built in -- without
        # this anchor, a bug shared by both paths would still "agree".
        self.assertAlmostEqual(_hand_effect(hand), expected_effect, places=10)

    def test_positive_direction_matches_the_hand_evaluation(self):
        self._assert_equivalent("positive", 0.125)

    def test_negative_direction_matches_the_hand_evaluation(self):
        # Same world, same selections, mirrored sides: the flip must happen
        # at construction, and the effect must be the exact complement.
        self._assert_equivalent("negative", -0.125)

    def test_band_rows_are_graded_unselected_in_both_paths(self):
        # [half-threshold, threshold): present in the wide sample -- the dose
        # check is disarmed without them -- but selected=False in BOTH paths,
        # boundary row at exactly 0.05 included.
        for direction in ("positive", "negative"):
            hand = {r["game_pk"]: r for r in _hand_rows(self.world, direction)}
            compiled = {r["game_pk"]: r
                        for r in self._funnel_rows(direction)}
            for pk in self.pks["band"]:
                self.assertIn(pk, compiled, (direction, pk))
                self.assertIn(pk, hand, (direction, pk))
                self.assertFalse(compiled[pk]["selected"], (direction, pk))
                self.assertFalse(hand[pk]["selected"], (direction, pk))

    def test_band_rows_do_not_move_the_hand_effect(self):
        # Dropping the band games entirely must not change the measurement:
        # proof they were excluded from the effect, not merely down-weighted.
        hand = _hand_rows(self.world, "positive")
        band = set(self.pks["band"])
        self.assertEqual(
            _hand_effect(hand),
            _hand_effect([r for r in hand if r["game_pk"] not in band]))

    def test_sub_band_and_unreadable_rows_never_appear(self):
        # Under the half-threshold, or a None feature side: not even a
        # diagnostic row. If these leaked into the wide sample, the dose
        # bands would be padded with a population the spec never named.
        for direction in ("positive", "negative"):
            seen = {r["game_pk"] for r in self._funnel_rows(direction)}
            seen |= {r["game_pk"] for r in _hand_rows(self.world, direction)}
            for pk in self.pks["under"] + self.pks["none"]:
                self.assertNotIn(pk, seen, (direction, pk))


if __name__ == "__main__":
    unittest.main()
