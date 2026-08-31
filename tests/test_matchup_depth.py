"""Matchup-depth tests, on the same synthetic pitch store the matrix tests use.

The fixture is imported from tests/test_matrix rather than re-stated, so the
two suites can never quietly test different stores: pitcher 500 (the home
starter, faced by the AWAY lineup) has a hand-checkable 0.300/0.150 platoon
split over 60 BF a side and a 66.7%-usage FF; pitcher 600 (faced by the HOME
lineup) sits below every floor on purpose. See test_matrix's docstring for
the full arithmetic.

What is locked here, in the spirit of tests/test_evidence_honesty.py:
  - every number travels with its sample size;
  - a sample below a stated floor carries an explicit small-sample warning;
  - missing input renders as an honest absence with a reason, never a guess;
  - the section labels itself as observation, not prediction;
  - the wiring: briefing -> dossier -> dashboard, mirroring the news section.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.analysis import matchup
from src.detect import dossier as dossier_mod
from src.pipeline import briefing, rebuilt
from src.report import dashboard
from tests.test_matrix import GAME, HANDEDNESS, POSTED, _slots, _write_store


class SectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.store = _write_store(Path(cls._tmp.name))
        # The public accumulation path, over the synthetic rows -- the same
        # entry the real slate build walks, never a stub of it.
        cls.acc = rebuilt.build_snapshots(["2023-04-01"],
                                          store=cls.store)["2023-04-01"]
        cls.section = matchup.build_section(cls.acc, GAME, POSTED, HANDEDNESS)

    # -- crossing and provenance -------------------------------------------

    def test_sides_cross_over_to_the_opposing_starter(self):
        # The away lineup faces the HOME probable (500), and vice versa.
        self.assertEqual(self.section["away"]["opposing_starter_id"], "500")
        self.assertEqual(self.section["away"]["opposing_starter_throws"], "R")
        self.assertEqual(self.section["home"]["opposing_starter_id"], "600")
        self.assertEqual(self.section["home"]["opposing_starter_throws"], "L")

    def test_cutoff_provenance_and_floors_are_stated(self):
        self.assertEqual(self.section["cutoff"], "2023-04-01")
        floors = self.section["floors"]
        self.assertEqual(floors["platoon_bf_per_side"], rebuilt.MIN_BF_PER_SIDE)
        self.assertEqual(floors["pitch_mix_pitches"],
                         rebuilt.MIN_PITCHES_FOR_MIX)
        self.assertEqual(floors["lineup_vs_pitch_pa"],
                         matchup.MIN_LINEUP_PA_VS_PITCH)

    def test_claims_are_labelled_observations_never_predictions(self):
        self.assertIn("is a prediction", self.section["nature"])
        self.assertIn("Nothing", self.section["nature"])
        for side in ("away", "home"):
            for name in ("handedness", "pitch_mix", "concentration"):
                for sentence in self.section[side][name]["sentences"]:
                    self.assertNotIn(" will ", sentence,
                                     f"{sentence!r} reads as a prediction")

    # -- (a) handedness ----------------------------------------------------

    def test_handedness_picture_with_samples(self):
        picture = self.section["away"]["handedness"]
        # 3 L + 1 S of 9 known hitters are advantaged against the righty 500.
        self.assertEqual(picture["lineup"],
                         {"share": round(4 / 9, 3), "advantaged": 4,
                          "known": 9})
        starter = picture["starter"]
        self.assertEqual(starter["gap"], 0.15)
        self.assertEqual(starter["vs_left_woba"], 0.3)
        self.assertEqual(starter["vs_right_woba"], 0.15)
        # The batters-faced samples ride along with the split.
        self.assertEqual(starter["vs_left_faced"], 60)
        self.assertEqual(starter["vs_right_faced"], 60)
        joined = " ".join(picture["sentences"])
        self.assertIn("60 batters faced", joined)

    def test_starter_split_below_floor_is_absent_with_warning(self):
        picture = self.section["home"]["handedness"]
        self.assertIsNone(picture["starter"])  # 600: 10 BF vs L, 0 vs R
        self.assertTrue(any(str(rebuilt.MIN_BF_PER_SIDE) in reason
                            for reason in picture["absent"]))
        self.assertTrue(any(w.startswith("Small sample")
                            for w in picture["warnings"]))

    # -- (b) pitch mix -----------------------------------------------------

    def test_pitch_mix_picture_with_samples(self):
        picture = self.section["away"]["pitch_mix"]
        self.assertEqual(picture["primary"],
                         {"pitch_type": "FF", "usage_pct": 66.7,
                          "pitches": 80, "total_pitches": 120})
        # PA-weighted FF line: 4 batters at 0.300 over 15 PA plus 5 at 0.450
        # over 4 PA -> (18 + 9) / 80, with the PA sample attached.
        self.assertEqual(picture["lineup_vs_primary"],
                         {"woba": 0.3375, "pa": 80, "batters_measured": 9})
        self.assertEqual(len(picture["batters"]), 9)
        for row in picture["batters"]:
            self.assertGreater(row["pa"], 0)
        # 80 PA is above the floor, so no small-sample warning fires.
        self.assertEqual(picture["warnings"], [])

    def test_starter_below_mix_floor_is_absent_with_warning_not_a_guess(self):
        picture = self.section["home"]["pitch_mix"]
        self.assertIsNone(picture["primary"])
        self.assertIsNone(picture["lineup_vs_primary"])
        self.assertTrue(any(str(rebuilt.MIN_PITCHES_FOR_MIX) in reason
                            for reason in picture["absent"]))
        self.assertTrue(any(w.startswith("Small sample")
                            for w in picture["warnings"]))

    def test_thin_lineup_vs_pitch_shows_the_number_with_a_warning(self):
        # A lineup made of the fixture's bottom hitters has only 20 FF PA:
        # the value renders (no suppression) but carries the floor warning.
        posted = {"away": _slots(9005), "home": POSTED["home"]}
        section = matchup.build_section(self.acc, GAME, posted, HANDEDNESS)
        picture = section["away"]["pitch_mix"]
        self.assertEqual(picture["lineup_vs_primary"]["woba"], 0.45)
        self.assertEqual(picture["lineup_vs_primary"]["pa"], 20)
        self.assertTrue(any(
            f"below the {matchup.MIN_LINEUP_PA_VS_PITCH}-PA floor" in w
            for w in picture["warnings"]))

    # -- (c) concentration -------------------------------------------------

    def test_concentration_with_samples(self):
        picture = self.section["away"]["concentration"]
        # Top (9001-9004): 60 FF PA worth 18 plus 9001's 10 CH PA worth 9.
        self.assertEqual(picture["top"], {"woba": round(27 / 70, 4), "pa": 70})
        self.assertEqual(picture["bottom"], {"woba": 0.15, "pa": 60})
        self.assertEqual(picture["gap"], round(27 / 70 - 9 / 60, 4))
        self.assertEqual(picture["warnings"], [])  # both halves at the floor

    def test_missing_half_is_absent_and_thin_half_is_warned(self):
        picture = self.section["home"]["concentration"]
        # Only 9101 has measured PA: the top half is real but thin, the
        # bottom half does not exist -- and neither is invented.
        self.assertEqual(picture["top"], {"woba": 0.0, "pa": 10})
        self.assertIsNone(picture["bottom"])
        self.assertIsNone(picture["gap"])
        self.assertTrue(any("slots 5-9" in reason
                            for reason in picture["absent"]))
        self.assertTrue(any("10 PA" in w and "Small sample" in w
                            for w in picture["warnings"]))

    # -- absences ----------------------------------------------------------

    def test_missing_lineup_side_is_a_reason_not_a_section(self):
        section = matchup.build_section(
            self.acc, GAME, {"away": POSTED["away"], "home": []}, HANDEDNESS)
        self.assertIn("no posted home lineup", section["home"]["reason"])
        # The away side is unaffected by the other side's hole.
        self.assertEqual(section["away"]["handedness"]["lineup"]["share"],
                         round(4 / 9, 3))

    def test_missing_starter_records_reasons_but_keeps_concentration(self):
        game = dict(GAME, home_probable_id=None)
        section = matchup.build_section(self.acc, game, POSTED, HANDEDNESS)
        side = section["away"]
        self.assertIsNone(side["opposing_starter_id"])
        self.assertIsNone(side["handedness"]["starter"])
        self.assertTrue(any("no probable starter" in r
                            for r in side["handedness"]["absent"]))
        self.assertTrue(any("no probable starter" in r
                            for r in side["pitch_mix"]["absent"]))
        # Concentration is about the lineup alone and survives.
        self.assertEqual(side["concentration"]["top"]["pa"], 70)

    def test_every_absence_carries_a_nonempty_reason(self):
        for side in ("away", "home"):
            for name in ("handedness", "pitch_mix", "concentration"):
                for reason in self.section[side][name]["absent"]:
                    self.assertTrue(reason and reason.strip())


class DepthByPkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = _write_store(self.root)
        self.no_lineup_game = dict(GAME, game_pk="700002", away_team="BOS",
                                   home_team="NYY")

    def test_builds_sections_for_lineup_games_and_reasons_for_the_rest(self):
        out = matchup.depth_by_pk([dict(GAME), self.no_lineup_game],
                                  {"700001": POSTED}, HANDEDNESS,
                                  store=self.store)
        section = out["700001"]
        # Cutoff is the slate's earliest game date -- behind every game.
        self.assertEqual(section["cutoff"], "2023-04-05")
        self.assertEqual(
            section["away"]["handedness"]["starter"]["gap"], 0.15)
        self.assertIn("no posted lineup", out["700002"]["reason"])

    def test_empty_pitch_store_is_a_reason_not_a_crash_or_a_zero(self):
        empty = self.root / "empty_store"
        empty.mkdir()
        out = matchup.depth_by_pk([dict(GAME)], {"700001": POSTED},
                                  HANDEDNESS, store=empty)
        self.assertIn("holds no data", out["700001"]["reason"])

    def test_no_posted_lineups_never_opens_the_store(self):
        # The store path does not even exist; if the walk were attempted the
        # empty-manifest branch would answer instead of the lineup reason.
        out = matchup.depth_by_pk([self.no_lineup_game], {}, HANDEDNESS,
                                  store=self.root / "nonexistent")
        self.assertIn("no posted lineup", out["700002"]["reason"])


class WiringTest(unittest.TestCase):
    """briefing -> dossier -> dashboard, mirroring the news section."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        store = _write_store(Path(self._tmp.name))
        self.acc = rebuilt.build_snapshots(["2023-04-01"],
                                           store=store)["2023-04-01"]
        self.section = matchup.build_section(self.acc, GAME, POSTED,
                                             HANDEDNESS)

    def _slate(self, depth_by_pk):
        return briefing.build_slate([dict(GAME)], store={}, detectors=[],
                                    matchup_depth_by_pk=depth_by_pk)

    def test_briefing_attaches_the_section_to_the_dossier(self):
        slate = self._slate({"700001": self.section})
        dossier = slate["games"][0]["dossier"]
        self.assertIs(dossier.sections["matchup_depth"], self.section)

    def test_an_entry_with_a_reason_becomes_a_named_gap(self):
        slate = self._slate({"700001": {"reason": "no posted lineup for "
                                        "this game"}})
        dossier = slate["games"][0]["dossier"]
        self.assertNotIn("matchup_depth", dossier.sections)
        self.assertIn("no posted lineup", dossier.gaps["matchup_depth"])

    def test_default_path_records_absence_when_no_lineups_exist(self):
        # No lineups on the slate: build_slate derives the depth map itself
        # (without touching any pitch store) and the dossier records why the
        # section is empty rather than omitting it.
        slate = briefing.build_slate([dict(GAME)], store={}, detectors=[])
        dossier = slate["games"][0]["dossier"]
        self.assertIn("no posted lineup", dossier.gaps["matchup_depth"])

    def test_dossier_default_is_an_honest_miss(self):
        dossier = dossier_mod.build(dict(GAME), {})
        self.assertIn("matchup_depth", dossier.gaps)
        self.assertIn("not built", dossier.gaps["matchup_depth"])


class DashboardRenderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        store = _write_store(self.root)
        self.acc = rebuilt.build_snapshots(["2023-04-01"],
                                           store=store)["2023-04-01"]
        self.path = self.root / "b.html"

    def _render(self, dossier):
        payload = {"date": GAME["date"],
                   "games": [{"dossier": dossier, "findings": [],
                              "verdict": "no_play", "summary": ""}],
                   "notes": []}
        dashboard.render(payload, self.path)
        return self.path.read_text(encoding="utf-8")

    def _dossier(self, section):
        dossier = dossier_mod.Dossier(dict(GAME))
        if section is not None:
            dossier.add("matchup_depth", section)
        else:
            dossier.miss("matchup_depth",
                         "matchup depth not built for this slate")
        return dossier

    def test_sentences_samples_and_warnings_reach_the_page(self):
        section = matchup.build_section(self.acc, GAME, POSTED, HANDEDNESS)
        html = self._render(self._dossier(section))
        self.assertIn("Matchup depth", html)
        # The observation label, the samples, and a small-sample warning all
        # survive into the rendered page.
        self.assertIn("Nothing in this section is a prediction.", html)
        self.assertIn("60 batters faced", html)
        self.assertIn("80 of 120 pitches", html)
        self.assertIn("Small sample:", html)
        self.assertIn("vs primary pitch", html)  # per-batter PA table

    def test_a_missing_section_renders_its_reason(self):
        html = self._render(self._dossier(None))
        self.assertIn("matchup depth not built for this slate", html)

    def test_hostile_batter_names_cannot_inject_markup(self):
        posted = {"away": _slots(9001), "home": POSTED["home"]}
        posted["away"][0]["name"] = "<i>injected</i>"
        section = matchup.build_section(self.acc, GAME, posted, HANDEDNESS)
        html = self._render(self._dossier(section))
        self.assertNotIn("<i>injected</i>", html)
        self.assertIn("&lt;i&gt;injected&lt;/i&gt;", html)


if __name__ == "__main__":
    unittest.main()
