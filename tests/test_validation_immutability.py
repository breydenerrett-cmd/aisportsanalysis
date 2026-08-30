"""Validation check 7: the battery observes; it must never touch.

WHY THIS CHECK EXISTS
---------------------
The battery runs AFTER the funnel has measured a hypothesis, on the same row
objects the funnel measured. If running the diagnostics mutates those rows --
an attached "_diff", a coerced type, a reordered list -- then the act of
checking a candidate changes the candidate, and every number downstream of
the battery call describes a different experiment than the one upstream of
it. Worse and subtler: battery.run accepts a WIDER graded sample (dose_rows,
sub-threshold selections included) purely to arm the dose-response check. If
that wider sample ever bleeds into the baseline or any non-dose check, the
diagnostic sample silently becomes the evidential sample -- more rows, a
different effect, a different p -- which is p-hacking by plumbing rather
than by intent. Neither failure would crash anything; both would corrupt
every verdict. Hence byte-level assertions, not spot checks.

WHAT IS ASSERTED
----------------
(a) battery.run leaves the caller's rows (and dose_rows) byte-identical --
    json.dumps(sort_keys=True) before equals after.
(b) every non-dose check in the report is IDENTICAL whether or not
    dose_rows/dose_bands are supplied, and the comparison is proven
    non-vacuous: the poisoned wider sample demonstrably reached the dose
    checks (they differ across the calls) yet no trace of it appears in any
    non-dose check.
(c) two battery.run calls on the same inputs return byte-identical results
    -- no hidden state, no unseeded randomness (the bootstrap interval is
    seeded inside discovery.py, and this pins that property here).
(d) funnel._measure builds its own "_diff" copies and leaves its input rows
    untouched -- the funnel-side twin of (a).
Plus a scan of battery's module namespace for mutable containers, so the
"no hidden state" claim in (c) is structural, not just observed twice.

The fixture is the shared synthetic World from tests/test_funnel.py -- the
candidate block, whose selections carry every optional battery key (season,
side, team, book, price, dose), so every check actually runs rather than
skipping; a battery that skipped everything could not fail immutability no
matter how badly it mutated.
"""

from __future__ import annotations

import __future__
import json
import types
import unittest

from src.model import selections as selections_mod
from src.research import battery
from src.research import funnel
from tests.test_funnel import CANDIDATE_TEAMS, FEATURES, World, _spec

EFFECT_FLOOR = 0.01

# Band edges for the armed call: [0.05, 0.1) catches the sub-threshold poison
# rows, [0.1, 0.25] the real selections (dose is 0.25 on every fired game in
# the World fixture). 0.1 is the spec threshold, per the battery docstring's
# instruction that the true threshold be one of the edges.
DOSE_BANDS = (0.05, 0.1, 0.25)

# The two report entries that legitimately read the wider dose sample; both
# are fed dose_sample inside battery.run, so both are expected to differ
# between the armed and unarmed calls. EVERYTHING else must not.
DOSE_CHECKS = ("dose_response", "threshold_sensitivity")
NON_DOSE_CHECKS = ("baseline", "season_split", "home_away",
                   "favorite_underdog", "team_concentration",
                   "book_concentration", "price_bands", "extreme_removal")


def _snapshot(obj) -> str:
    """Canonical byte-level fingerprint. sort_keys makes dict ordering
    irrelevant, so equality means equal CONTENT -- and any mutation at all
    (an added key, a coerced float, a reordered list) changes the string."""
    return json.dumps(obj, sort_keys=True)


def _selection_rows() -> list:
    """120 pooled candidate selections built through the module's own path.

    The rows come from funnel._selections_for over the shared World fixture
    -- the same compiler that feeds the real battery -- rather than from
    hand-built dicts, so the immutability claim is tested on rows shaped
    exactly like production rows (books_at_best lists, "selected" flags and
    all). Win pattern copied from the fixture's candidate block: 40W/20L per
    season across six clubs and two books, so every fatal check judges a
    real, spread-out sample and none skips.
    """
    world = World()
    for season in (2023, 2024):
        for i in range(60):
            wins_for_team = 7 if i % 6 < 4 else 6
            world.fire(season, i, CANDIDATE_TEAMS[i % 6],
                       i // 6 < wins_for_team, FEATURES["candidate"])
    spec = funnel.validate_spec(_spec("immutability", FEATURES["candidate"]))
    rows = []
    for season in (2023, 2024):
        index = selections_mod.index_price_pairs(world.pairs[season])
        rows.extend(funnel._selections_for(spec, world.matrix[season], index,
                                           world.results, season))
    return rows


def _poison_rows() -> list:
    """40 sub-threshold rows engineered so any bleed is unmissable.

    All losses at implied 0.5 (a bleed drags the baseline effect down hard),
    a team and book that exist nowhere in the selections (a bleed puts the
    string "POISON" into a concentration table), and July dates disjoint
    from the selections' April/May dates (a bleed changes the extreme-removal
    date pool). If any non-dose check ingests these rows, it cannot match the
    unarmed call AND it cannot avoid naming the poison.
    """
    rows = []
    for i in range(40):
        rows.append({"date": f"2023-07-{(i % 28) + 1:02d}", "season": 2023,
                     "side": "away", "team": "POISON", "book": "bookPOISON",
                     "books_at_best": ["bookPOISON"], "price": -110,
                     "implied": 0.5, "won": False, "dose": 0.06,
                     "selected": False})
    return rows


class BatteryImmutabilityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = _selection_rows()
        # The wider diagnostic sample the battery docstring asks for:
        # selections plus graded sub-threshold rows.
        cls.dose_rows = cls.rows + _poison_rows()

    # -- (a) ---------------------------------------------------------------
    def test_run_leaves_caller_rows_byte_identical(self):
        before_rows = _snapshot(self.rows)
        before_dose = _snapshot(self.dose_rows)
        result = battery.run(self.rows, effect_floor=EFFECT_FLOOR,
                             dose_key="dose", dose_bands=list(DOSE_BANDS),
                             dose_rows=self.dose_rows)
        # ran=True first: a battery that skipped everything never touched
        # the rows either, and this test would pass while proving nothing.
        self.assertTrue(result["ran"])
        self.assertEqual(_snapshot(self.rows), before_rows)
        self.assertEqual(_snapshot(self.dose_rows), before_dose)

    # -- (b) ---------------------------------------------------------------
    def test_wider_dose_sample_never_reaches_a_non_dose_check(self):
        unarmed = battery.run(self.rows, effect_floor=EFFECT_FLOOR,
                              dose_key="dose")
        armed = battery.run(self.rows, effect_floor=EFFECT_FLOOR,
                            dose_key="dose", dose_bands=list(DOSE_BANDS),
                            dose_rows=self.dose_rows)
        # The report must contain exactly the checks this test partitions
        # into dose and non-dose. If the battery ever grows a new check,
        # this fails loudly and the partition gets re-decided on purpose,
        # instead of a new check silently escaping the bleed comparison.
        expected = set(NON_DOSE_CHECKS) | set(DOSE_CHECKS)
        self.assertEqual(set(unarmed["report"]), expected)
        self.assertEqual(set(armed["report"]), expected)

        # The heart of the check: baseline effect/n/p -- and every other
        # non-dose check, in full -- identical with and without the wider
        # sample. Dict equality first (readable diff on failure), then the
        # byte fingerprint (nothing assertEqual might forgive).
        for name in NON_DOSE_CHECKS:
            self.assertEqual(armed["report"][name], unarmed["report"][name],
                             name)
            self.assertEqual(_snapshot(armed["report"][name]),
                             _snapshot(unarmed["report"][name]), name)

        # Prove the comparison had teeth: the poison really did reach the
        # dose path. Unarmed, every dose is 0.25 so quartile banding finds
        # no spread and dose_response skips; armed, the bands are measured.
        # If these were EQUAL, the assertions above would be vacuous.
        self.assertIn("skipped", unarmed["report"]["dose_response"])
        self.assertNotIn("skipped", armed["report"]["dose_response"])
        self.assertNotEqual(armed["report"]["threshold_sensitivity"],
                            unarmed["report"]["threshold_sensitivity"])

        # And the direct bleed detector: the poison's unmistakable markers
        # appear nowhere outside the dose checks.
        non_dose_text = _snapshot({name: armed["report"][name]
                                   for name in NON_DOSE_CHECKS})
        self.assertNotIn("POISON", non_dose_text)
        self.assertNotIn("2023-07-", non_dose_text)
        # Verdict bookkeeping must agree too -- the wider sample may inform
        # the dose checks but never the survival verdict's other inputs.
        self.assertEqual(armed["survives"], unarmed["survives"])
        self.assertEqual(
            [f for f in armed["fatal"] if f not in DOSE_CHECKS],
            [f for f in unarmed["fatal"] if f not in DOSE_CHECKS])

    # -- (c) ---------------------------------------------------------------
    def test_repeat_runs_are_byte_identical(self):
        first = battery.run(self.rows, effect_floor=EFFECT_FLOOR,
                            dose_key="dose", dose_bands=list(DOSE_BANDS),
                            dose_rows=self.dose_rows)
        second = battery.run(self.rows, effect_floor=EFFECT_FLOOR,
                             dose_key="dose", dose_bands=list(DOSE_BANDS),
                             dose_rows=self.dose_rows)
        # The whole return value, not just the report: survives/ran/fatal
        # are what a caller acts on. Byte-identical output on identical
        # input is the observable face of "no hidden state" -- it also pins
        # the bootstrap interval to its fixed seed; an unseeded resample
        # would fail here on the baseline's ci alone.
        self.assertEqual(_snapshot(first), _snapshot(second))

    # -- (d) ---------------------------------------------------------------
    def test_funnel_measure_does_not_mutate_rows(self):
        before = _snapshot(self.rows)
        n, effect, p = funnel._measure(self.rows)
        # Sanity that _measure actually did work on this sample (a no-op
        # cannot mutate, and would prove nothing).
        self.assertEqual(n, len(self.rows))
        self.assertIsNotNone(effect)
        self.assertIsNotNone(p)
        # The "_diff" working key must live on _measure's own copies, never
        # on the caller's rows -- byte-identical means no key appeared.
        self.assertEqual(_snapshot(self.rows), before)
        self.assertFalse(any("_diff" in row for row in self.rows))

    # -- structural: no module-level mutable state --------------------------
    def test_battery_module_holds_no_mutable_state(self):
        """(c) observed determinism twice; this makes it structural.

        Every module-level binding in battery must be a module, function,
        class, or immutable value (int, float, str, bool, tuple). A single
        module-level list or dict is a place for one run to leave residue
        for the next -- exactly the hidden state (c) exists to rule out --
        so its mere existence fails, whether or not anything writes to it
        today. (Tuples of tuples/strings, like PRICE_BANDS and FATAL_CHECKS,
        are immutable all the way down and pass.)
        """
        def deeply_immutable(value):
            if isinstance(value, (int, float, str, bool, bytes,
                                  frozenset, type(None))):
                return True
            if isinstance(value, tuple):
                return all(deeply_immutable(item) for item in value)
            return False

        offenders = {}
        for name, value in vars(battery).items():
            if name.startswith("__"):
                continue
            if isinstance(value, (types.ModuleType, types.FunctionType,
                                  type)):
                continue
            # `from __future__ import annotations` binds a _Feature marker;
            # code, not state -- excluded so the scan reports real residue.
            if isinstance(value, __future__._Feature):
                continue
            if not deeply_immutable(value):
                offenders[name] = type(value).__name__
        self.assertEqual(offenders, {})


if __name__ == "__main__":
    unittest.main()
