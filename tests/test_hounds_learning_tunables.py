"""The knobs a pack hound declares: every declaration is held to the code, a challenger's values are
validated against the declared menu, its published rule text is generated, and patching a hound's
constants is scoped to its own call.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.hounds import pack as pack_mod
from src.hounds.learning import champions, ledger as L, rules, tunables
from src.hounds.pack import base

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "house_pack.json").read_text(encoding="utf-8"))
TUN = tunables.load()


class DeclarationsAreHeldToTheCode(unittest.TestCase):
    def test_eleven_pack_hounds_declare_knobs_and_the_controls_do_not(self):
        self.assertEqual(len(TUN), 11)
        for hid in ("coin_flip_collie", "dartboard_dalmatian", "lunar_lab", "numerology_newfie"):
            self.assertNotIn(hid, TUN)                 # controls and for-fun hounds are not tuned
        for hid in TUN:
            self.assertIn(hid, pack_mod.BY_ID)

    def test_each_default_is_the_live_value_on_the_grid_and_inside_the_bounds(self):
        for hid, t in TUN.items():
            mod = importlib.import_module(t.module)
            for name, knob in t.knobs.items():
                with self.subTest(hound=hid, knob=name):
                    self.assertTrue(hasattr(mod, name), f"{t.module}.{name} does not exist")
                    self.assertAlmostEqual(float(getattr(mod, name)), float(knob.default), places=9)
                    self.assertLessEqual(knob.lo, knob.default)
                    self.assertLessEqual(knob.default, knob.hi)
                    self.assertTrue(knob.on_grid(knob.default))
                    self.assertGreater(knob.step, 0)
                    self.assertIn(knob.kind, ("int", "float"))
                    if knob.kind == "int":
                        self.assertEqual(int(knob.default), knob.default)

    def test_each_render_of_the_default_is_the_literal_and_the_literal_is_in_the_rule_text(self):
        for hid, t in TUN.items():
            self.assertEqual(t.rule_text, pack_mod.BY_ID[hid].RULE, hid)
            for name, knob in t.knobs.items():
                self.assertTrue(knob.renders, f"{hid}.{name} has no render")
                for lit, new in tunables.render(knob, knob.default):
                    with self.subTest(hound=hid, knob=name, literal=lit):
                        self.assertEqual(new, lit)
                        self.assertIn(lit, t.rule_text)

    def test_rule_text_at_the_defaults_is_the_declared_text(self):
        for hid, t in TUN.items():
            self.assertEqual(tunables.rule_text(t, t.defaults()), t.rule_text, hid)

    def test_every_value_on_every_grid_changes_the_text_and_states_the_value(self):
        for hid, t in TUN.items():
            for name, knob in t.knobs.items():
                v = knob.lo
                while v <= knob.hi + 1e-9:
                    value = tunables._typed(knob, v)
                    values = dict(t.defaults(), **{name: value})
                    text = tunables.rule_text(t, values)
                    with self.subTest(hound=hid, knob=name, value=value):
                        for lit, new in tunables.render(knob, value):
                            self.assertIn(new, text)
                        if abs(value - knob.default) > 1e-9:
                            self.assertNotEqual(text, t.rule_text)
                    v += knob.step

    def test_a_hound_that_is_a_voter_for_an_ensemble_is_not_patched_while_the_ensemble_runs(self):
        # pack_leader / scrappy_schnauzer ask other hounds' own pick(); only VersionedHound patches,
        # and only for its own call, so a Professor Paws challenger changes nothing for them.
        self.assertIn("professor_paws", TUN)
        mod = importlib.import_module("src.hounds.pack.professor_paws")
        before = mod.GAP
        t = TUN["professor_paws"]
        seen = {}

        class Spy:
            id = "professor_paws"
            band = (base.PRICE_MIN, base.PRICE_MAX)

            def applies_to(self, sport):
                return True

            def pick(self, board, ctx):
                seen["during"] = mod.GAP
                return []

        vh = tunables.VersionedHound(Spy(), t, dict(t.defaults(), GAP=0.04), hound_id="c-test")
        self.assertEqual(vh.id, "c-test")
        vh.pick({}, None)
        self.assertEqual(seen["during"], 0.04)
        self.assertEqual(mod.GAP, before)            # put back exactly


class ValidatingAProposedKnobSet(unittest.TestCase):
    def setUp(self):
        self.t = TUN["professor_paws"]
        self.champ = self.t.defaults()

    def test_a_valid_change_returns_the_full_values(self):
        values = tunables.validate(self.t, self.champ, {"GAP": 0.03})
        self.assertEqual(values, {"GAP": 0.03, "SHRINK": 0.5})

    def refused(self, proposed, **kw):
        with self.assertRaises(tunables.TunableError) as ctx:
            tunables.validate(self.t, kw.get("champ", self.champ), proposed)
        return ctx.exception.errors

    def test_unknown_knob_out_of_bounds_off_grid_and_wrong_type(self):
        self.assertIn("NOPE", self.refused({"NOPE": 1}))
        self.assertIn("GAP", self.refused({"GAP": 0.5}))              # above max 0.04
        self.assertIn("GAP", self.refused({"GAP": 0.01}))             # below min 0.015
        self.assertIn("GAP", self.refused({"GAP": 0.0225}))           # off the 0.005 grid
        self.assertIn("GAP", self.refused({"GAP": True}))             # a bool is not a number
        self.assertIn("GAP", self.refused({"GAP": "0.03"}))
        self.assertIn("params", self.refused({}))
        self.assertIn("params", self.refused("GAP=0.03"))

    def test_an_int_knob_must_be_whole(self):
        t = TUN["relief_retriever"]
        with self.assertRaises(tunables.TunableError):
            tunables.validate(t, t.defaults(), {"GAP": 100.5})
        self.assertEqual(tunables.validate(t, t.defaults(), {"GAP": 100})["GAP"], 100)

    def test_at_most_two_knobs_and_at_least_one_must_differ(self):
        t = TUN["grudge_bulldog"]
        ok = tunables.validate(t, t.defaults(), {"NFL_MARGIN": 8, "MLB_MARGIN": 4})
        self.assertEqual(ok, {"NFL_MARGIN": 8, "MLB_MARGIN": 4})
        self.assertIn("params", self.refused({"GAP": 0.02}))           # equals the champion: no change
        self.assertEqual(rules.MAX_KNOBS_CHANGED, 2)

    def test_three_changed_knobs_are_refused(self):
        fake = tunables.TunableHound(
            "x", "X", "stats", "m", "t", (), (),
            {n: tunables.Knob(n, n, "int", 5, 1, 9, 1, ()) for n in "ABC"})
        with self.assertRaises(tunables.TunableError):
            tunables.validate(fake, fake.defaults(), {"A": 6, "B": 6, "C": 6})

    def test_near_duplicate_is_within_one_step_on_every_knob(self):
        a = {"GAP": 0.03, "SHRINK": 0.5}
        self.assertTrue(tunables.near_duplicate(self.t, a, {"GAP": 0.035, "SHRINK": 0.5}))
        self.assertFalse(tunables.near_duplicate(self.t, a, {"GAP": 0.04, "SHRINK": 0.5}))
        self.assertFalse(tunables.near_duplicate(self.t, a, {"GAP": 0.03, "SHRINK": 0.7}))


class PatchingIsScopedAndRestored(unittest.TestCase):
    def setUp(self):
        self.mod = types.ModuleType("fake_pack_mod")
        self.mod.GAP = 1.0
        sys.modules["fake_pack_mod"] = self.mod
        self.addCleanup(sys.modules.pop, "fake_pack_mod", None)

    def test_restored_after_an_exception(self):
        with self.assertRaises(RuntimeError):
            with tunables.patched("fake_pack_mod", {"GAP": 9.0}, {"GAP": 1.0}):
                self.assertEqual(self.mod.GAP, 9.0)
                raise RuntimeError("boom")
        self.assertEqual(self.mod.GAP, 1.0)

    def test_versioned_hound_forwards_everything_else_and_stamps_rows(self):
        class H:
            id = "h"
            band = (-150, 300)
            who_decided = "rule"
            name = "H"

            def applies_to(self, sport):
                return sport == "mlb"

            def pick(self, board, ctx):
                return [mod.GAP]

        mod = self.mod
        t = tunables.TunableHound("h", "H", "stats", "fake_pack_mod", "x", ("mlb",), ("moneyline",),
                                  {"GAP": tunables.Knob("GAP", "g", "float", 1.0, 0.5, 2.0, 0.5, ())})
        vh = tunables.VersionedHound(H(), t, {"GAP": 2.0}, hound_id="c-1", row_extra={"role": "challenger"})
        self.assertEqual(vh.band, (-150, 300))
        self.assertTrue(vh.applies_to("mlb"))
        self.assertFalse(vh.applies_to("nfl"))
        self.assertEqual(vh.who_decided, "rule")
        self.assertEqual(vh.pick(None, None), [2.0])
        self.assertEqual(mod.GAP, 1.0)
        self.assertEqual(vh.row_extra, {"role": "challenger"})

    def test_accepts_gates_games_by_lock(self):
        class Ctx:
            lock = datetime(2026, 11, 1, 20, tzinfo=timezone.utc)

        t = TUN["professor_paws"]
        floor = datetime(2026, 11, 1, 21, tzinfo=timezone.utc)
        vh = tunables.VersionedHound(pack_mod.BY_ID["professor_paws"], t, t.defaults(), min_lock=floor)
        self.assertFalse(vh.accepts(Ctx()))
        self.assertTrue(tunables.VersionedHound(pack_mod.BY_ID["professor_paws"], t, t.defaults()).accepts(Ctx()))


class ChampionVersionsForThePackRunner(unittest.TestCase):
    def test_no_registry_means_the_pack_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = champions.champion_versions(pack_mod.PACK, Path(tmp) / "nope.jsonl")
        self.assertEqual(len(out), len(pack_mod.PACK))
        for a, b in zip(out, pack_mod.PACK):
            self.assertIs(a, b)

    def test_a_promotion_wraps_only_that_hound_with_its_version_and_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = L.Scope.house(Path(tmp))
            L.log_for(scope).append(
                L.K_PROMOTION, scope="house", hound_id="professor_paws", challenger_id="c-1",
                from_version=1, to_version=2, params={"GAP": 0.03, "SHRINK": 0.5}, applied=True,
                effective_utc="2026-11-02T00:00:00Z")
            out = champions.champion_versions(pack_mod.PACK, scope.events)
        by = {h.id: h for h in out}
        self.assertIsInstance(by["professor_paws"], tunables.VersionedHound)
        self.assertEqual(by["professor_paws"].row_extra["hound_version"], 2)
        self.assertEqual(by["professor_paws"].row_extra["params"], {"GAP": 0.03, "SHRINK": 0.5})
        self.assertIs(by["totals_terrier"], pack_mod.BY_ID["totals_terrier"])

    def test_an_unreadable_registry_never_stops_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / L.HOUSE_EVENTS
            path.write_text("{ this is not json\n", encoding="utf-8")
            out = champions.champion_versions(pack_mod.PACK, path)
        self.assertEqual([h.id for h in out], [h.id for h in pack_mod.PACK])


if __name__ == "__main__":
    unittest.main()
