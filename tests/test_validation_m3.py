"""Machinery-validation check 4: the battery re-falsifies the real M3 candidate.

M3 -- cross-book dispersion, docs/RESULTS_V2.md -- is the one false positive
this project has actually produced and then destroyed: +8.49pp, p = 0.006,
killed by hand-written dose-response, book-concentration and season-split
tests. The automated battery exists so those kill-tests never depend on being
remembered, which makes M3 the canonical regression case: a battery that
passes M3 is worse than no battery, because it stamps "survives" on the exact
shape of noise the machinery was built to destroy.

The original battery DID pass M3 (gate failure, 2026-08-30). The rules were
then amended -- a shrinkage leg on the concentration checks, and a dose rule
that no longer lets an unjudgeable upper tail rescue a spike sitting on a
judgeable contradiction. This module pins the amended verdict so it can never
silently regress.

M3 is a REGRESSION CASE here, not the definition of correctness. The rules
themselves are validated as general skeptical rules against controlled
synthetic cases in tests/test_battery_generality.py; this file only proves
that the general rules, applied to the one real false positive on record,
reach the verdict the hand-written analysis reached.

The reproduction needs the historical odds store, which is large and not part
of a source checkout everywhere; without it the whole module skips rather
than pretending to have checked anything.
"""

import unittest

from pathlib import Path

from src.pipeline import backfill

_STORE = Path(backfill.DEFAULT_STORE)

# The frozen M3 definition, from docs/RESEARCH_V2.md / RESULTS_V2.md: grade
# every leave-one-out deviation of at least one point, select at the 2pp
# headline threshold. These are M3's registered parameters, not the battery's.
GRADED_FLOOR = 0.01
SELECTION_THRESHOLD = 0.02

# The reproduction target, straight from docs/RESULTS_V2.md's headline table.
EXPECTED_SELECTED = 249
EXPECTED_EFFECT = 0.08492


def _m3_rows():
    """The graded M3 sample, rebuilt from the raw price paths."""
    from src.research import m3_dispersion, pricepath

    paths = pricepath.build(2023) + pricepath.build(2024)
    rows = []
    for row in m3_dispersion.deviations(paths):
        dose = abs(row["deviation"])
        if dose < GRADED_FLOOR:
            continue
        side = "away" if row["deviation"] > 0 else "home"
        won = (not row["home_won"]) if side == "away" else bool(row["home_won"])
        implied = (1.0 - row["consensus_home_probability"] if side == "away"
                   else row["consensus_home_probability"])
        rows.append({
            "date": row["date"], "won": won, "implied": implied,
            "book": row["book"], "season": int(str(row["date"])[:4]),
            "side": side, "dose": dose,
        })
    return rows


@unittest.skipUnless(_STORE.exists(),
                     "historical odds store absent; M3 cannot be rebuilt")
class M3RefalsificationTests(unittest.TestCase):
    """One expensive build, shared; every assertion reads from it."""

    @classmethod
    def setUpClass(cls):
        from src.research import battery, funnel

        cls.graded = _m3_rows()
        cls.selected = [r for r in cls.graded
                        if r["dose"] >= SELECTION_THRESHOLD]
        # Both band constructions that matter: the bands the original V2
        # analysis read, and the bands the funnel would build on its own.
        # A battery that kills M3 only under hand-picked bands has not
        # closed the gap.
        cls.registered = battery.run(
            cls.selected, effect_floor=0.01, dose_key="dose",
            dose_bands=[0.01, 0.02, 0.03, 0.10], dose_rows=cls.graded)
        cls.funnel_style = battery.run(
            cls.selected, effect_floor=0.01, dose_key="dose",
            dose_bands=funnel._dose_edges(cls.selected, SELECTION_THRESHOLD),
            dose_rows=cls.graded)

    def test_the_reproduction_is_the_documented_candidate(self):
        """Killing a different sample would prove nothing about M3."""
        self.assertEqual(len(self.selected), EXPECTED_SELECTED)
        effect = sum((1.0 if r["won"] else 0.0) - r["implied"]
                     for r in self.selected) / len(self.selected)
        self.assertAlmostEqual(effect, EXPECTED_EFFECT, places=4)

    def test_m3_does_not_survive_the_battery(self):
        self.assertTrue(self.registered["ran"])
        self.assertFalse(self.registered["survives"])

    def test_m3_does_not_survive_under_the_funnels_own_bands(self):
        self.assertTrue(self.funnel_style["ran"])
        self.assertFalse(self.funnel_style["survives"])

    def test_the_kill_matches_the_hand_written_analysis(self):
        """RESULTS_V2 killed M3 on book concentration above all: the effect
        was carried by one book. The battery must find the same story."""
        self.assertIn("book_concentration", self.registered["fatal"])
        self.assertIn("book_concentration", self.funnel_style["fatal"])

    def test_the_verdict_names_the_rules_that_judged_it(self):
        """A verdict without a rule fingerprint cannot be compared honestly
        against verdicts produced by other rule versions."""
        from src.research import battery

        for verdict in (self.registered, self.funnel_style):
            self.assertEqual(verdict["rules"]["version"],
                             battery.RULES_VERSION)
            self.assertEqual(verdict["rules"]["fingerprint"],
                             battery.rules_fingerprint())


if __name__ == "__main__":
    unittest.main()
