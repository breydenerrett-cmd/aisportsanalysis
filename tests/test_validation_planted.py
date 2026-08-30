"""Validation gate, checks 1 and 2: a planted edge and planted noise.

WHY THESE TWO CHECKS EXIST TOGETHER
-----------------------------------
The funnel's other tests assert its plumbing; these two assert its JUDGEMENT,
from opposite directions, before it is allowed near a real hypothesis.

Check 1 plants a GENUINE edge -- the backed side wins 62.5% against an implied
of exactly 50%, in both seasons independently, spread across eight clubs, two
books and 160 distinct dates, with doses above and below the threshold and a
larger edge at larger doses (a real dose-response, so the battery must not
kill it) -- and demands promotion: status "candidate", q_pass True. A funnel
that kills everything is as broken as one that blesses everything, and only a
planted positive can tell those failure modes apart.

Check 2 plants TEN hypotheses over pure noise -- backed-side wins pinned
within a few games of exactly half in every block-season -- runs them as one
family, and demands none is promoted, with the FDR denominator equal to the
full spec count on every output row.

WHY THE CONSTRUCTIONS ARE DETERMINISTIC
---------------------------------------
No random module anywhere, seeded or otherwise. Wins are laid down by a
Bresenham spread (_spread) so they land evenly across the rotating clubs, the
alternating books and consecutive dates, and every season aggregate is chosen
BY HAND. In check 2 that choice is the point: each noise block's win count is
pinned at or near half, so a spec that survives is never "an unlucky seed" --
it is a bug in the funnel's arithmetic, reproducible on every run. A
seeded-random construction would leave a chance survivor arguable; a pinned
one makes it damning. The one noise spec built to look best (both seasons
mildly positive) reaches the battery and the correction on purpose, so the
deep gates are exercised too -- its pooled p is around 0.5, hopeless against
a BH threshold of at most q/1 = 0.10 over ten specs, and its exact exit door
(battery or FDR) is a tie-break detail, never the invariant under test.
"""

from __future__ import annotations

import unittest

from src.model import selections
from src.research import funnel
from tests.test_funnel import (CANDIDATE_TEAMS, FEATURES, NOREP_TEAM, OPPONENT,
                               SCREEN_TEAM, World, _spec)

# Eight backed clubs -- enough that the battery's top-5 leave-one-out always
# leaves most of the sample standing, which is what "not a story about one
# club" looks like when the edge is real. The opponent stays Miami on every
# game (never backed, so never a concentration slice), same as the fixture.
BACKED = CANDIDATE_TEAMS + (SCREEN_TEAM, NOREP_TEAM)

EDGE_FEATURE = FEATURES["candidate"]  # which feature is irrelevant; reuse

# The planted dose-response ladder: (dose, wins out of 20 rows) per season.
# Threshold is 0.1 (from _spec), diagnostic half-threshold 0.05, so the 0.07
# rows are graded into the battery's wide sample but never selected -- they
# are the below-threshold band the dose check needs, and their 55% win rate
# continues the gradient downward the way a real effect would. Selected win
# rates rise 60 -> 60 -> 65 -> 65 with dose: monotone, so the M3 spike
# signature (positive spike over a <= 0 neighbour with nothing larger above)
# cannot exist in this table no matter how the bands are cut.
EDGE_LADDER = ((0.07, 11), (0.12, 12), (0.18, 12), (0.24, 13), (0.30, 13))

# Check 2: one block of NOISE_N games per feature per season, dose constant
# and above threshold so every block row is a selection for both of its
# specs. (away wins 2023, away wins 2024) out of 70, half = 35 -- every
# block-season sits within 3 games of implied, and the family's mean effect
# is exactly zero because each feature carries a positive and a negative
# spec whose effects are sign mirrors of each other.
#   The blocks are shaped to die at DIFFERENT gates, so this family
# exercises the screen, the replication gate, the battery and the correction
# rather than ten copies of one trivial death:
#   lineup_platoon_share  (37, 33): pos passes the screen, flips in 2024;
#                                   neg is negative on the screen.
#   starter_platoon_gap   (33, 37): the mirror image of the above.
#   lineup_vs_primary_pitch (35, 35): both effects exactly zero -- wins
#                                   exactly tracking implied, the construction
#                                   where survival can only mean a real bug.
#   primary_pitch_share   (36, 35): pos squeaks past the screen, replication
#                                   effect is exactly 0.0 < the half-floor.
#   top_minus_bottom      (38, 36): pos is mildly positive BOTH seasons, so
#                                   it reaches level 3 and must be refused by
#                                   the battery or the correction, never
#                                   promoted -- pooled p ~0.5 guarantees it.
NOISE_N = 70
NOISE_DOSE = 0.2
NOISE_WINS = (
    ("lineup_platoon_share", 37, 33),
    ("starter_platoon_gap", 33, 37),
    ("lineup_vs_primary_pitch", 35, 35),
    ("primary_pitch_share", 36, 35),
    ("top_minus_bottom", 38, 36),
)

# Where each noise spec must die, straight from the table above. The one
# level-3 spec is asserted separately: its exit is a refusal either way.
EXPECTED_EXITS = {
    "lineup_platoon_share_pos": "no_replication",
    "lineup_platoon_share_neg": "screen_dead",
    "starter_platoon_gap_pos": "screen_dead",
    "starter_platoon_gap_neg": "no_replication",
    "lineup_vs_primary_pitch_pos": "screen_dead",
    "lineup_vs_primary_pitch_neg": "screen_dead",
    "primary_pitch_share_pos": "no_replication",
    "primary_pitch_share_neg": "screen_dead",
    "top_minus_bottom_neg": "screen_dead",
}


def _spread(i, n, wins):
    """True for exactly `wins` of the indices 0..n-1, spread evenly.

    Bresenham's line, used as a win scheduler: the i-th row wins iff it
    advances the running count of wins owed by position i. Even spacing is
    what keeps the wins balanced across the rotating clubs (i mod 8), the
    alternating books (day parity) and the date order, without a random draw
    -- the construction stays fully deterministic AND non-degenerate.
    """
    return (i + 1) * wins // n > i * wins // n


class PlantedWorld(World):
    """The fixture's World, with a per-game dose instead of the fixed 0.25.

    The base fixture pins every fired dose at one value because its tests are
    about exit doors, not gradients. A planted dose-response needs the dose to
    VARY, so this subclass builds the game through the parent (keeping the
    price pair, the result and the join exactly as the fixture earns them)
    and then rewrites the matrix row's feature columns: the named feature gets
    `dose` on the away side, every other feature reads 0.0 on both sides --
    covered but sub-threshold, so specs on other features never fire here.
    """

    def fire_dosed(self, season, day, backed_full, want_win, feature, dose):
        # Backed club plays AWAY against the fixed opponent, mirroring
        # World.fire: "the backed side won" is home_won inverted, so the
        # outcome is set per game without touching side resolution.
        self.add_game(season, day, backed_full, OPPONENT,
                      home_won=not want_win, fired_feature=None)
        row = self.matrix[season][-1]
        for name in funnel.NUMERIC_FEATURES:
            row["away_" + name] = dose if name == feature else 0.0
            row["home_" + name] = 0.0


def _edge_world():
    """Check 1's world: 100 games per season, 80 selected, 62.5% winners.

    Each ladder level runs 20 games with clubs rotating through all eight
    backed teams (offset by level so no club is welded to one dose) and wins
    Bresenham-spread across the level. Every game gets its own date, and the
    fixture's day-parity book assignment splits each level 10-10 across the
    two books. Per season the selected rows go 50-30 -- effect +0.125 against
    an implied of exactly 0.5 -- in BOTH seasons, because a real edge is the
    one thing that should replicate here.
    """
    world = PlantedWorld()
    for season in (2023, 2024):
        day = 0
        for level, (dose, wins) in enumerate(EDGE_LADDER):
            for i in range(20):
                world.fire_dosed(season, day, BACKED[(i + level) % 8],
                                 _spread(i, 20, wins), EDGE_FEATURE, dose)
                day += 1
    return world


def _noise_world():
    """Check 2's world: five 70-game blocks per season, one per feature.

    Days run 0..349 per season on a single counter, so every game has its own
    date and (club, opponent, date) join keys never collide -- 2023's late
    dates spill into early calendar 2024 but stop before 2024's block begins,
    so no date string is shared across seasons either.

    WHICH rows win is varied per block and per season through a bijective
    index permutation (gcd(3, 70) = 1), so the win pattern differs across
    blocks -- different clubs, dates and books carry the wins -- while the
    block-season win COUNT stays exactly the pinned aggregate. Varied noise,
    pinned totals: the non-degeneracy and the determinism at once.
    """
    world = PlantedWorld()
    for season in (2023, 2024):
        day = 0
        for block, (feature, wins_2023, wins_2024) in enumerate(NOISE_WINS):
            wins = wins_2023 if season == 2023 else wins_2024
            for i in range(NOISE_N):
                perm = (3 * i + 11 * block
                        + (17 if season == 2024 else 0)) % NOISE_N
                world.fire_dosed(season, day, BACKED[(i + block) % 8],
                                 _spread(perm, NOISE_N, wins), feature,
                                 NOISE_DOSE)
                day += 1
    specs = []
    for feature, _, _ in NOISE_WINS:
        # Two hypotheses per feature -- the market underrates it and the
        # market overrates it -- which is how ten distinct specs come out of
        # five matrix features without inventing columns the funnel lacks.
        specs.append(_spec(feature + "_pos", feature))
        specs.append(_spec(feature + "_neg", feature, direction="negative"))
    return specs, world


class PlantedPositiveTests(unittest.TestCase):
    """Check 1: the machine can still FIND something."""

    @classmethod
    def setUpClass(cls):
        cls.world = _edge_world()
        cls.spec = _spec("planted_edge", EDGE_FEATURE)
        cls.rows = cls.world.run([cls.spec])
        cls.row = cls.rows[0]

    def test_the_planted_edge_is_promoted(self):
        # THE assertion of check 1. If this fails, the funnel cannot detect a
        # 12.5-point edge replicated across two seasons, eight clubs and two
        # books -- it kills everything, which is exactly as disqualifying as
        # blessing everything.
        self.assertEqual(self.row["status"], "candidate")
        self.assertTrue(self.row["q_pass"])
        self.assertEqual(self.row["level_reached"], 3)
        # Not one fatal check fired: a genuine spread-out dose-responsive
        # edge is the shape the battery is pre-registered to leave alone.
        self.assertEqual(self.row["battery_fatal"], [])

    def test_the_measured_numbers_are_the_planted_numbers(self):
        # 80 selected per season, 50-30 each: the funnel must measure what
        # was planted, exactly -- implied is 0.5 by construction (-110/-110),
        # so every effect is a hand-checkable fraction.
        self.assertEqual(self.row["n_2023"], 80)
        self.assertEqual(self.row["n_2024"], 80)
        self.assertEqual(self.row["n_pooled"], 160)
        self.assertAlmostEqual(self.row["effect_2023"], 0.125)
        self.assertAlmostEqual(self.row["effect_2024"], 0.125)
        self.assertAlmostEqual(self.row["effect_pooled"], 0.125)
        # Clustered p on 160 one-selection dates at +0.125 is far under any
        # reasonable bar; 0.05 is asserted, not tuned to the construction.
        self.assertLess(self.row["p_pooled"], 0.05)

    def test_family_of_one_bookkeeping(self):
        # A single-spec family divides by one: BH threshold q * 1 / 1.
        self.assertEqual(self.row["fdr_family_size"], 1)
        self.assertAlmostEqual(self.row["fdr_threshold"], 0.10)

    def test_the_dose_response_is_real_in_the_rows(self):
        # Audit the CONSTRUCTION through the funnel's own selection builder,
        # so a fixture refactor can never silently flatten the gradient this
        # check's promotion claim rests on.
        spec = funnel.validate_spec(self.spec)
        index = selections.index_price_pairs(self.world.pairs[2023])
        wide = funnel._selections_for(spec, self.world.matrix[2023], index,
                                      self.world.results, 2023,
                                      fraction=funnel.DIAGNOSTIC_FRACTION)
        self.assertEqual(len(wide), 100)
        sub = [r for r in wide if not r["selected"]]
        self.assertEqual(len(sub), 20)  # the below-threshold band exists
        self.assertTrue(all(r["dose"] == 0.07 for r in sub))
        wins_by_dose = {}
        for r in wide:
            wins_by_dose.setdefault(r["dose"], []).append(r["won"])
        self.assertEqual({d: sum(w) for d, w in wins_by_dose.items()},
                         {dose: wins for dose, wins in EDGE_LADDER})
        # Larger dose, larger edge -- monotone by dose, and genuinely larger
        # at the top than at the bottom.
        rates = [sum(wins_by_dose[d]) / len(wins_by_dose[d])
                 for d in sorted(wins_by_dose)]
        self.assertEqual(rates, sorted(rates))
        self.assertGreater(rates[-1], rates[0])
        # The spread the concentration checks lean on: eight clubs, two books.
        self.assertEqual(len({r["team"] for r in wide}), 8)
        self.assertEqual({r["book"] for r in wide}, {"bookA", "bookB"})


class PlantedNullTests(unittest.TestCase):
    """Check 2: ten noise specs in one family, and none may come out alive."""

    @classmethod
    def setUpClass(cls):
        cls.specs, cls.world = _noise_world()
        cls.rows = cls.world.run(cls.specs)
        cls.by_name = {row["name"]: row for row in cls.rows}

    def test_no_noise_spec_is_promoted(self):
        # THE assertion of check 2. The construction pins every block-season
        # within three games of implied, so "candidate" here cannot be bad
        # luck -- it would be the funnel promoting nothing at all. If this
        # ever fails, the fix is in the funnel, never in this assertion.
        for row in self.rows:
            self.assertNotEqual(row["status"], "candidate", row["name"])
            self.assertFalse(row["q_pass"], row["name"])

    def test_the_family_denominator_is_the_full_count_on_every_row(self):
        # Ten specs entered, ten is the denominator on EVERY row -- including
        # the six that died at the screen with no pooled p (they enter the
        # correction at p = 1.0). A shrinking denominator is p-hacking with
        # extra steps; this is the invariant the funnel exists to protect.
        self.assertEqual(len(self.specs), 10)
        for row in self.rows:
            self.assertEqual(row["fdr_family_size"], 10, row["name"])
        for row in self.rows:
            if row["p_pooled"] is None:
                self.assertEqual(row["p_fdr"], 1.0, row["name"])

    def test_each_designed_exit_is_taken(self):
        # Nine specs die exactly where the win table says they must: the
        # sign-mirror pairs split screen_dead / no_replication, and the
        # exactly-half block dies twice at the screen with effect 0.0.
        for name, status in EXPECTED_EXITS.items():
            self.assertEqual(self.by_name[name]["status"], status, name)
        # The best-looking noise spec earns level 3 -- mildly positive both
        # seasons -- and is then refused by the battery or the correction.
        # WHICH door is a tie-break detail of leave-one-out slices; both are
        # correct refusals, and its pooled p (~0.5 at +4 wins over 140) can
        # never beat a BH threshold of at most 0.10 anyway. "candidate" is
        # the only wrong answer, and it is excluded above.
        deep = self.by_name["top_minus_bottom_pos"]
        self.assertEqual(deep["level_reached"], 3)
        self.assertIn(deep["status"], ("killed_by_battery", "failed_fdr"))
        self.assertGreater(deep["p_fdr"], 0.10)

    def test_every_null_died_on_merit_not_data_poverty(self):
        # Every spec graded its full 70-selection screen: the nulls were
        # measured and refused, not starved. A funnel that "kills" noise by
        # failing to build its selections would pass check 2 while broken.
        for row in self.rows:
            self.assertGreaterEqual(row["level_reached"], 1, row["name"])
            self.assertEqual(row["n_2023"], NOISE_N, row["name"])

    def test_the_noise_averages_to_implied(self):
        # The construction's own honesty check: across the family the screen
        # effects cancel exactly (each feature carries a +x and a -x spec),
        # and no single block strays past four games from half -- this is
        # noise around implied, not a hidden edge planted by accident.
        effects = [row["effect_2023"] for row in self.rows]
        self.assertAlmostEqual(sum(effects), 0.0)
        for row in self.rows:
            # + 5e-6, not 1e-9: funnel._measure rounds effects to 5 decimal
            # places, so an exact-fraction bound can lose to rounding by up to
            # half of the last kept digit. The tolerance covers the rounding,
            # never a real excess.
            self.assertLessEqual(abs(row["effect_2023"]), 3 / NOISE_N + 5e-6,
                                 row["name"])


if __name__ == "__main__":
    unittest.main()
