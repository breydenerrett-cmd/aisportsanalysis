"""src/datasvc/ufc/matchup.py: the fact sheet.

Uses the synthetic world of tests/test_datasvc_ufc_features.py (see its docstring for
the bouts). The sheet for 101 v 102 is the scheduled main event 9101, whose odds are
-170/+145 current and -150/+130 open, so every probability below is arithmetic on
those prices done by hand.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.datasvc.ufc import features, matchup
from tests.test_datasvc_ufc_features import FETCHED, MAIN_EVENT_START, UFCCOM_101, build_store, odds_row

NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
DOC = Path(__file__).resolve().parent.parent / "docs" / "datasvc" / "UFC_FEATURES.md"


class MatchupCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = build_store(Path(cls._tmp.name))
        cls.m = matchup.matchup(cls.store, "101", "102", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def sheet(self, a, b, as_of=None):
        return matchup.matchup(self.store, a, b, as_of, now=NOW)


class AsOfAndTheScheduledBout(MatchupCase):
    def test_as_of_defaults_to_the_scheduled_bouts_start(self):
        self.assertEqual(self.m["as_of"], "2026-10-10T23:00:00Z")
        self.assertEqual(self.m["as_of_source"], "scheduled_bout_start")
        self.assertEqual(self.m["bout"], {
            "bout_id": "9101", "event_id": "7013", "event_name": "Synthetic Championship Night",
            "date_utc": MAIN_EVENT_START, "weight_class": "Welterweight", "scheduled_rounds": 5,
            "card_segment": "main", "match_number": 1, "description": "5 Rnd", "status": "scheduled",
            "other_scheduled_bout_ids": []})

    def test_an_explicit_as_of_wins_but_the_bout_and_odds_are_still_attached(self):
        m = self.sheet("101", "102", "2026-03-14")
        self.assertEqual((m["as_of"], m["as_of_source"]), ("2026-03-14T00:00:00Z", "argument"))
        self.assertEqual(m["bout"]["bout_id"], "9101")
        self.assertIsNotNone(m["odds"])

    def test_without_a_scheduled_bout_as_of_is_now_and_the_sheet_says_what_is_absent(self):
        m = self.sheet("101", "103")           # 9013 between them was cancelled, not scheduled
        self.assertEqual((m["as_of"], m["as_of_source"]), ("2026-10-03T15:00:00Z", "now"))
        self.assertIsNone(m["bout"])
        self.assertIsNone(m["odds"])
        self.assertIn({"side": None, "figure": "bout",
                       "reason": "no scheduled bout between these fighters in the store"}, m["missing"])

    def test_asking_in_the_other_order_swaps_the_sides_and_keeps_the_bout(self):
        m = self.sheet("102", "101")
        self.assertEqual((m["a"]["fighter_id"], m["b"]["fighter_id"]), ("102", "101"))
        self.assertEqual(m["bout"]["bout_id"], "9101")
        self.assertEqual(m["as_of"], self.m["as_of"])
        self.assertEqual(m["features"]["a"]["fighter_id"], "102")

    def test_both_fighters_features_are_measured_at_that_moment(self):
        self.assertEqual(self.m["features"]["a"]["as_of"], self.m["as_of"])
        self.assertEqual(self.m["features"]["b"]["as_of"], self.m["as_of"])
        self.assertEqual(self.m["features"]["a"]["record"]["fights"], 5)
        self.assertEqual(self.m["features"]["b"]["record"]["fights"], 5)

    def test_the_whole_sheet_is_leakage_free_at_an_earlier_as_of(self):
        """At 2026-03-14 (the day of 9009) that fight and everything after it is invisible."""
        m = self.sheet("101", "102", "2026-03-14")
        self.assertEqual(m["previous_meetings"], [])
        self.assertEqual(m["features"]["a"]["record"]["fights"], 3)
        self.assertEqual(m["features"]["b"]["record"]["fights"], 3)       # 9002, 9004, 9008
        shared = {i["opponent_id"]: i for i in m["shared_opponents"]["items"]}
        self.assertEqual([x["bout_id"] for x in shared["103"]["b"]], ["9002"])    # 9012 is later
        self.assertEqual([x["bout_id"] for x in shared["104"]["a"]], ["9003"])    # 9011 is later

    def test_the_sheet_equals_the_sheet_from_a_world_that_ends_there(self):
        for cut in ("2025-07-01", "2026-03-14", "2026-07-01"):
            with tempfile.TemporaryDirectory() as tmp:
                past = build_store(Path(tmp), before=cut)
                for a, b in (("101", "102"), ("103", "104"), ("102", "105")):
                    full = matchup.matchup(self.store, a, b, cut, now=NOW)
                    cut_world = matchup.matchup(past, a, b, cut, now=NOW)
                    for key in ("features", "differentials", "styles", "shared_opponents",
                                "previous_meetings", "physical", "layoff"):
                        self.assertEqual(full[key], cut_world[key], f"{a} v {b} as of {cut}: {key} saw the future")

    def test_several_scheduled_bouts_prefer_the_next_one_and_list_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp))
            base = dict(store.bout_by_id()["9101"])
            store.upsert("bouts", [
                dict(base, bout_id="9200", date_utc="2026-09-01T22:00Z"),      # stale: never refreshed
                dict(base, bout_id="9201", date_utc="2026-12-12T22:00Z")])
            m = matchup.matchup(store, "101", "102", now=NOW)
            self.assertEqual(m["bout"]["bout_id"], "9101")
            self.assertEqual(m["bout"]["other_scheduled_bout_ids"], ["9201", "9200"])
            later = matchup.matchup(store, "101", "102", now=datetime(2027, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(later["bout"]["bout_id"], "9201")                # nothing ahead: the latest
            self.assertEqual(later["as_of"], "2026-12-12T22:00:00Z")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            self.sheet("101", "101")
        with self.assertRaises(features.UnknownFighter):
            self.sheet("101", "999")
        with self.assertRaises(ValueError):
            self.sheet("101", "102", "someday")

    def test_the_sheet_is_plain_json_and_deterministic(self):
        self.assertEqual(json.loads(json.dumps(self.m)), self.m)
        self.assertEqual(matchup.matchup(self.store, "101", "102", now=NOW), self.m)

    def test_no_prediction_pick_or_edge_appears_anywhere(self):
        forbidden = re.compile(r"predict|pick|recommend|edge|value_bet|confidence|win_probability", re.I)
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    keys.add(k)
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(self.m)
        self.assertEqual([k for k in keys if forbidden.search(k)], [])
        self.assertIn("No prediction, no pick", self.m["note"])


class OddsBlock(MatchupCase):
    def test_moneyline_probabilities_with_and_without_the_margin(self):
        ml = self.m["odds"]["moneyline"]
        # current: -170 -> 170/270 = 0.62963, +145 -> 100/245 = 0.40816, total 1.03779
        cur = ml["current"]
        self.assertEqual((cur["a"], cur["b"]), (-170, 145))
        self.assertEqual(cur["implied"], {"a": 0.6296, "b": 0.4082})
        self.assertEqual(cur["margin"], 0.0378)
        self.assertEqual(cur["without_margin"], {"a": 0.6067, "b": 0.3933})     # 0.62963/1.03779, 0.40816/1.03779
        self.assertAlmostEqual(sum(cur["without_margin"].values()), 1.0, places=3)
        # open: -150 -> 0.6, +130 -> 100/230 = 0.43478, total 1.03478
        opening = ml["open"]
        self.assertEqual(opening["implied"], {"a": 0.6, "b": 0.4348})
        self.assertEqual(opening["margin"], 0.0348)
        self.assertEqual(opening["without_margin"], {"a": 0.5798, "b": 0.4202})
        self.assertIsNone(ml["close"])                                          # not posted yet

    def test_rounds_total_probabilities(self):
        rt = self.m["odds"]["rounds_total"]
        self.assertEqual(rt["line"], 4.5)
        self.assertEqual(rt["current"]["without_margin"], {"over": 0.5, "under": 0.5})   # -110 / -110
        self.assertEqual(rt["current"]["margin"], 0.0476)                                # 2 * 0.52381 - 1
        self.assertEqual(rt["open"]["implied"], {"over": 0.5455, "under": 0.5})          # -120, +100
        self.assertEqual(rt["open"]["without_margin"], {"over": 0.5217, "under": 0.4783})

    def test_method_prices_have_one_margin_over_all_six_outcomes(self):
        method = self.m["odds"]["method"]["open"]
        self.assertEqual(method["a"], {"ko_tko_dq": 300, "submission": 800, "decision": 350})
        self.assertEqual(method["b"], {"ko_tko_dq": 450, "submission": 900, "decision": 400})
        # 0.25 + 0.11111 + 0.22222 + 0.18182 + 0.1 + 0.2 = 1.06515
        self.assertEqual(method["margin"], 0.0652)
        self.assertEqual(method["without_margin"]["a"]["ko_tko_dq"], 0.2347)             # 0.25 / 1.06515
        six = [p for side in method["without_margin"].values() for p in side.values()]
        self.assertAlmostEqual(sum(six), 1.0, places=3)
        self.assertIsNone(self.m["odds"]["method"]["close"])

    def test_odds_are_mapped_by_fighter_not_by_position(self):
        """The bout is 101 (a) v 102 (b). Ask for 102 first and every price follows its fighter."""
        swapped = self.sheet("102", "101")["odds"]
        cur = swapped["moneyline"]["current"]
        self.assertEqual((cur["a"], cur["b"]), (145, -170))
        self.assertEqual(cur["without_margin"], {"a": 0.3933, "b": 0.6067})
        self.assertEqual(swapped["method"]["open"]["a"], {"ko_tko_dq": 450, "submission": 900, "decision": 400})
        # over/under has no sides, so it is the same
        self.assertEqual(swapped["rounds_total"], self.m["odds"]["rounds_total"])

    def test_provider_facts_ride_along(self):
        odds = self.m["odds"]
        self.assertEqual((odds["provider"], odds["provider_id"], odds["orientation"]), ("DraftKings", "100", "verified"))
        self.assertEqual(odds["fetched_utc"], FETCHED)
        self.assertFalse(odds["is_closing"])
        self.assertFalse(odds["as_of_safe"])             # prices as fetched, not as of the sheet's as_of
        self.assertEqual(odds["other_providers"], [])

    def test_draftkings_is_preferred_and_other_providers_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp), odds=[
                odds_row(provider_id="200", provider="Other Book", a_ml_current=-300, b_ml_current=250),
                odds_row()])
            odds = matchup.matchup(store, "101", "102", now=NOW)["odds"]
        self.assertEqual(odds["provider"], "DraftKings")
        self.assertEqual(odds["moneyline"]["current"]["a"], -170)
        self.assertEqual(odds["other_providers"], [{"provider_id": "200", "provider": "Other Book"}])

    def test_unverified_orientation_withholds_the_prices_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp), odds=[odds_row(
                orientation="unknown", a_ml_open=None, a_ml_current=None, b_ml_open=None, b_ml_current=None,
                over_open=None, over_current=None, under_open=None, under_current=None, method_odds=None)])
            m = matchup.matchup(store, "101", "102", now=NOW)
        odds = m["odds"]
        self.assertEqual(odds["orientation"], "unknown")
        self.assertIsNone(odds["moneyline"])
        self.assertIn("prices withheld", odds["note"])
        self.assertIn({"side": None, "figure": "odds", "reason": odds["note"]}, m["missing"])

    def test_a_fighter_pair_that_is_not_the_bouts_pair_gets_no_prices(self):
        """Odds rows belong to a bout (101 v 102); asking for them against anyone else must not map a price."""
        bout = self.store.bout_by_id()["9101"]
        block = matchup.bout_odds(self.store, bout, "101", "104")
        self.assertIsNone(block["moneyline"])
        self.assertIn("withheld", block["note"])

    def test_one_missing_price_keeps_the_others_but_does_not_divide_out_a_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp), odds=[odds_row(b_ml_current=None)])
            cur = matchup.matchup(store, "101", "102", now=NOW)["odds"]["moneyline"]["current"]
        self.assertEqual(cur["a"], -170)
        self.assertIsNone(cur["b"])
        self.assertEqual(cur["implied"], {"a": 0.6296, "b": None})
        self.assertIsNone(cur["margin"])
        self.assertIsNone(cur["without_margin"])

    def test_a_bout_with_no_odds_row_says_so(self):
        m = matchup.matchup(self.store, "104", "105", now=NOW)           # 9102 has no odds
        self.assertEqual(m["bout"]["bout_id"], "9102")
        self.assertEqual(m["bout"]["card_segment"], "prelims")
        self.assertIsNone(m["odds"])
        self.assertIn({"side": None, "figure": "odds", "reason": "no odds row for the scheduled bout"}, m["missing"])

    def test_the_compact_form_has_open_and_current_moneyline_and_no_method_market(self):
        bout = self.store.bout_by_id()["9101"]
        compact = matchup.bout_odds(self.store, bout, "101", "102", detail="current")
        self.assertEqual(set(compact["moneyline"]), {"open", "current"})
        self.assertEqual(set(compact["rounds_total"]), {"line", "current"})
        self.assertIsNone(compact["method"])


class OddsMath(unittest.TestCase):
    def test_american_prices_to_probabilities(self):
        p = matchup.american_to_probability
        self.assertEqual(p(100), 0.5)
        self.assertEqual(p(-100), 0.5)
        self.assertEqual(p(150), 0.4)
        self.assertEqual(p(-150), 0.6)
        self.assertAlmostEqual(p(-200), 2 / 3)
        self.assertAlmostEqual(p(1400), 100 / 1500)
        self.assertEqual(p(120.0), 100 / 220)

    def test_prices_that_cannot_be_american_are_refused(self):
        for bad in (0, 50, -50, 99.9, -99.9, None, True, "−110", "-110", float("nan"), float("inf"), [], {}):
            self.assertIsNone(matchup.american_to_probability(bad), repr(bad))

    def test_remove_margin(self):
        r = matchup.remove_margin({"a": -110, "b": -110})
        self.assertEqual(r["implied"], {"a": 0.5238, "b": 0.5238})
        self.assertEqual(r["margin"], 0.0476)
        self.assertEqual(r["without_margin"], {"a": 0.5, "b": 0.5})
        even = matchup.remove_margin({"a": 100, "b": 100})
        self.assertEqual((even["margin"], even["without_margin"]), (0.0, {"a": 0.5, "b": 0.5}))

    def test_remove_margin_needs_every_price(self):
        r = matchup.remove_margin({"a": -110, "b": None})
        self.assertEqual(r["implied"], {"a": 0.5238, "b": None})
        self.assertIsNone(r["margin"])
        self.assertIsNone(r["without_margin"])
        self.assertEqual(matchup.remove_margin({}), {"implied": {}, "margin": None, "without_margin": None})

    def test_method_odds_nesting_is_read_whichever_way_it_was_written(self):
        price = matchup._method_price
        by_snapshot = {"open": {"a": {"submission": 800}, "b": {"submission": 900}}, "close": None}
        by_side = {"a": {"open": {"submission": 800}, "close": {"submission": 700}}, "b": {"open": {"submission": 900}}}
        by_method = {"a": {"submission": {"open": 800, "close": 700}}, "b": {"submission": {"open": 900}}}
        for shape in (by_snapshot, by_side, by_method):
            self.assertEqual(price(shape, "a", "open", "submission"), 800, shape)
            self.assertEqual(price(shape, "b", "open", "submission"), 900, shape)
            self.assertIsNone(price(shape, "a", "open", "decision"), shape)
            self.assertIsNone(price(shape, "a", "current", "submission"), shape)
        self.assertEqual(price(by_side, "a", "close", "submission"), 700)
        self.assertEqual(price(by_method, "a", "close", "submission"), 700)
        self.assertIsNone(price(by_snapshot, "a", "close", "submission"))

    def test_a_method_price_that_does_not_say_which_snapshot_it_is_refused(self):
        unlabelled = {"a": {"submission": 800}, "b": {"submission": 900}}
        for snapshot in matchup.SNAPSHOTS:
            self.assertIsNone(matchup._method_price(unlabelled, "a", snapshot, "submission"))
        self.assertIsNone(matchup._method_price(None, "a", "open", "submission"))
        self.assertIsNone(matchup._method_price({"open": {"a": {"submission": 30}}}, "a", "open", "submission"))


class Differentials(MatchupCase):
    def test_a_minus_b_on_hand_checked_figures(self):
        d = self.m["differentials"]
        # 101: 200 landed in 50 min = 4.0; 102: 205 landed in 61.333 min = 3.3424
        self.assertEqual((d["sig_strikes_landed_per_min"]["a"], d["sig_strikes_landed_per_min"]["b"]), (4, 3.3424))
        self.assertEqual(d["sig_strikes_landed_per_min"]["diff"], 0.6576)
        # 101: 6 takedowns in 50 min -> 1.8 per 15; 102: 12 in 61.333 min -> 2.9348
        self.assertEqual(d["takedowns_landed_per_15"]["diff"], round(1.8 - 2.9348, 4))
        self.assertEqual(d["win_rate"]["diff"], -0.2)                  # 0.6 - 0.8
        self.assertEqual(d["distance_rate"]["diff"], 0.2)              # 0.6 - 0.4
        self.assertEqual(d["ufc_fights"]["diff"], 0)

    def test_every_difference_is_a_minus_b_of_the_two_sides_values(self):
        for name, entry in self.m["differentials"].items():
            fa = self.m["features"]["a"]["figures"][name]
            fb = self.m["features"]["b"]["figures"][name]
            self.assertEqual((entry["a"], entry["b"]), (fa["value"], fb["value"]), name)
            expected = None if fa["value"] is None or fb["value"] is None else round(fa["value"] - fb["value"], 4)
            self.assertEqual(entry["diff"], expected, name)
            self.assertEqual(entry["a_sample"], {"fights": fa["fights"], "minutes": fa["minutes"]}, name)

    def test_only_figures_where_a_difference_means_something_are_differenced(self):
        names = set(self.m["differentials"])
        self.assertEqual(names, set(matchup.DIFFERENTIAL_FIGURES))
        for excluded in ("height_in", "reach_in", "age_years", "days_since_last_fight"):
            self.assertNotIn(excluded, names)             # they have the physical and layoff blocks
        for name in names:
            self.assertIn(name, self.m["features"]["a"]["figures"])

    def test_a_missing_side_gives_no_difference_and_a_thin_sample_flag(self):
        m = self.sheet("105", "102", "2025-07-01")        # 105 has one fight and no statistics of its own
        entry = m["differentials"]["sig_strikes_landed_per_min"]
        self.assertIsNone(entry["a"])
        self.assertIsNone(entry["diff"])
        self.assertTrue(entry["thin_sample"])
        self.assertEqual(entry["a_sample"], {"fights": 0, "minutes": 0.0})

    def test_a_small_sample_is_flagged_and_a_real_one_is_not(self):
        d = self.m["differentials"]
        self.assertFalse(d["sig_strikes_landed_per_min"]["thin_sample"])       # 4 and 5 fights, 50 and 61 minutes
        self.assertTrue(d["strength_of_schedule"]["thin_sample"])               # only 3 rated opponents for 101
        early = self.sheet("101", "102", "2025-05-01")["differentials"]
        self.assertTrue(early["sig_strikes_landed_per_min"]["thin_sample"])    # 101 has 2 fights, 10 minutes


class StyleLabels(MatchupCase):
    def test_a_wrestler_lands_takedowns_often_and_controls(self):
        b = self.m["styles"]["b"]
        names = [s["name"] for s in b["applies"]]
        self.assertIn("wrestler", names)
        wrestler = [s for s in b["applies"] if s["name"] == "wrestler"][0]
        self.assertEqual(wrestler["evidence"], {"takedowns_landed_per_15": 2.9348, "control_time_share": 0.288})
        self.assertEqual(wrestler["sample"], {"fights": 5, "minutes": 61.33})
        self.assertEqual(wrestler["rule"], "takedowns_landed_per_15 >= 2 and control_time_share >= 0.2")

    def test_takedowns_without_enough_of_them_are_not_a_wrestler_even_with_the_control_time(self):
        """101 controls exactly the threshold (0.2) but lands 1.8 takedowns per 15, under 2.0."""
        a = self.m["styles"]["a"]
        self.assertIn("wrestler", a["does_not_apply"])
        self.assertEqual(self.m["features"]["a"]["figures"]["control_time_share"]["value"], 0.2)

    def test_labels_that_apply_and_the_ones_checked(self):
        a = self.m["styles"]["a"]
        self.assertEqual([s["name"] for s in a["applies"]], ["submission_threat", "goes_the_distance"])
        self.assertEqual(a["checked"], [r.name for r in matchup.STYLE_RULES])
        everything = ([s["name"] for s in a["applies"]] + a["does_not_apply"] + [n["name"] for n in a["not_assessed"]])
        self.assertEqual(sorted(everything), sorted(a["checked"]))      # every label lands in exactly one place

    def test_a_label_the_sample_cannot_support_is_not_assessed_with_the_reason(self):
        """104 has 4 fights with statistics but only 27.83 minutes, under the 30 needed."""
        feats = features.features_as_of(self.store, "104", "2026-10-10")
        styles = matchup.style_descriptors(feats)
        unjudged = {n["name"]: n["reason"] for n in styles["not_assessed"]}
        self.assertIn("volume_striker", unjudged)
        self.assertIn("needs 30 fight minutes, has 27.83", unjudged["volume_striker"])
        self.assertIn("needs 5 fights, has 4", unjudged["finisher"])         # 4 decided fights; the NC is excluded
        self.assertEqual(styles["applies"], [])

    def test_a_failed_condition_settles_the_label_even_if_another_could_not_be_judged(self):
        feats = {"figures": {
            "sig_strike_share_distance": {"value": 0.5, "fights": 5, "minutes": 60.0},
            "takedowns_landed_per_15": {"value": None, "fights": 0, "minutes": 0.0, "reason": "no statistics"}}}
        styles = matchup.style_descriptors(feats)
        # striker needs distance share >= 0.75 AND few takedowns: 0.5 fails, so the missing takedowns cannot save it
        self.assertIn("striker", styles["does_not_apply"])
        # wrestler needs takedowns and control, and neither could be judged
        unjudged = {n["name"]: n["reason"] for n in styles["not_assessed"]}
        self.assertIn("wrestler", unjudged)
        self.assertIn("no statistics", unjudged["wrestler"])

    @staticmethod
    def _passing(cond):
        """A value comfortably on the passing side of a condition."""
        return cond.threshold + 1.0 if cond.op == ">=" else cond.threshold - 0.5

    def test_each_threshold_is_inclusive_at_the_line_and_exclusive_just_under(self):
        """Every condition of every rule, one at a time: on the line, just over, just under.

        `>=` holds on the line; `<` does not (strictly under holds). All other conditions of
        the rule are held on their passing side so only the one under test decides.
        """
        for rule in matchup.STYLE_RULES:
            for cond in rule.conditions:
                for delta in (0.0, +0.001, -0.001):
                    expect = (delta >= 0) if cond.op == ">=" else (delta < 0)
                    figures = {c.figure: {"value": self._passing(c), "fights": 10, "minutes": 100.0, "den": 100}
                               for c in rule.conditions}
                    figures[cond.figure]["value"] = round(cond.threshold + delta, 6)
                    styles = matchup.style_descriptors({"figures": figures})
                    applied = rule.name in [s["name"] for s in styles["applies"]]
                    self.assertEqual(applied, expect, f"{rule.name}: {cond.text()} at {delta:+}")

    def _single(self, figure, value, **sample):
        fig = {"value": value, "fights": 10, "minutes": 100.0, "den": 100}
        fig.update(sample)
        return matchup.style_descriptors({"figures": {figure: fig}})

    def test_minimum_samples_are_enforced(self):
        def names(styles, key):
            return [(s if isinstance(s, str) else s["name"]) for s in styles[key]]

        self.assertIn("volume_striker", names(self._single("sig_strikes_landed_per_min", 9.0), "applies"))
        for override in ({"fights": 2}, {"minutes": 29.99}):
            styles = self._single("sig_strikes_landed_per_min", 9.0, **override)
            self.assertIn("volume_striker", names(styles, "not_assessed"), override)
            self.assertNotIn("volume_striker", names(styles, "applies"), override)
        # shares of results need five fights and no minutes at all
        self.assertIn("finisher", names(self._single("finish_rate", 1.0, minutes=0.0), "applies"))
        self.assertIn("finisher", names(self._single("finish_rate", 1.0, fights=4), "not_assessed"))
        # a takedown defence needs ten opponent attempts behind it
        self.assertIn("hard_to_take_down", names(self._single("takedown_defence", 0.9, den=10), "applies"))
        styles = self._single("takedown_defence", 0.9, den=9)
        reason = [n["reason"] for n in styles["not_assessed"] if n["name"] == "hard_to_take_down"][0]
        self.assertIn("needs 10 opponent takedown attempts, has 9", reason)

    def test_the_documented_thresholds_are_the_ones_in_the_code(self):
        """docs/datasvc/UFC_FEATURES.md must list every rule and every threshold the code uses."""
        text = DOC.read_text(encoding="utf-8")
        for rule in matchup.STYLE_RULES:
            self.assertIn(f"`{rule.name}`", text, rule.name)
            for cond in rule.conditions:
                self.assertIn(cond.text(), text, f"{rule.name}: {cond.text()}")
        for const in ("MIN_FIGHTS_TIMED", "MIN_MINUTES_TIMED", "MIN_FIGHTS_RESULTS"):
            self.assertIn(f"{const} = {getattr(matchup, const):g}", text, const)

    def test_ufccom_career_numbers_never_move_a_label_or_a_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp))
            store.upsert("ufccom_profiles", [dict(UFCCOM_101, sig_strikes_landed_per_min=0.01,
                                                  takedown_avg_per_15=99.0, sig_strike_accuracy=0.01)])
            other = matchup.matchup(store, "101", "102", now=NOW)
        self.assertEqual(other["differentials"], self.m["differentials"])
        self.assertEqual(other["styles"], self.m["styles"])
        self.assertEqual(other["features"]["a"]["figures"], self.m["features"]["a"]["figures"])
        self.assertFalse(other["features"]["a"]["ufccom_career"]["as_of_safe"])


class SharedOpponentsAndMeetings(MatchupCase):
    def test_shared_opponents_with_each_fighters_result_against_them(self):
        shared = self.m["shared_opponents"]
        self.assertEqual((shared["a_opponents"], shared["b_opponents"], shared["count"]), (4, 4, 3))
        items = {i["opponent_id"]: i for i in shared["items"]}
        self.assertEqual(list(items), ["103", "104", "105"])                    # by opponent name
        clinch = items["103"]
        self.assertEqual([(x["bout_id"], x["result"], x["method"]) for x in clinch["a"]], [("9001", "win", "KO_TKO")])
        self.assertEqual([(x["bout_id"], x["result"], x["method"]) for x in clinch["b"]],
                         [("9002", "win", "DEC_UNANIMOUS"), ("9012", "loss", "SUB")])      # a rematch lists both
        dan = items["104"]
        self.assertEqual([(x["bout_id"], x["result"]) for x in dan["a"]], [("9003", "loss"), ("9011", "win")])
        self.assertEqual([(x["bout_id"], x["result"]) for x in dan["b"]], [("9008", "win")])
        self.assertEqual(clinch["opponent_name"], "Cal Clinch")

    def test_the_two_fighters_themselves_are_never_shared_opponents(self):
        ids = {i["opponent_id"] for i in self.m["shared_opponents"]["items"]}
        self.assertNotIn("101", ids)
        self.assertNotIn("102", ids)

    def test_an_empty_overlap_can_be_told_from_an_empty_history(self):
        m = self.sheet("103", "105", "2025-03-01")    # 103 has fought once (9001), 105 not at all
        shared = m["shared_opponents"]
        self.assertEqual((shared["a_opponents"], shared["b_opponents"], shared["count"], shared["items"]),
                         (1, 0, 0, []))

    def test_previous_meetings_are_results_from_as_sides_view(self):
        meetings = self.m["previous_meetings"]
        self.assertEqual(len(meetings), 1)
        meeting = meetings[0]
        self.assertEqual((meeting["bout_id"], meeting["result"], meeting["method"]), ("9009", "loss", "DEC_UNANIMOUS"))
        self.assertEqual((meeting["winner_id"], meeting["winner_name"]), ("102", "Ben Brawler"))
        flipped = self.sheet("102", "101")["previous_meetings"][0]
        self.assertEqual((flipped["result"], flipped["winner_id"]), ("win", "102"))

    def test_a_no_contest_is_a_meeting_and_later_fights_between_them_are_not(self):
        self.assertEqual(self.sheet("104", "105")["previous_meetings"][0]["result"], "no_contest")   # 9007
        self.assertEqual(self.sheet("102", "104", "2025-05-01")["previous_meetings"], [])           # 9008 is later


class PhysicalAndLayoff(MatchupCase):
    def test_physical_comparison(self):
        p = self.m["physical"]
        self.assertEqual(p["a"], {"height_in": 72.0, "reach_in": 74.0, "reach_minus_height_in": 2.0,
                                  "age_years": 34.5, "stance": "Orthodox"})
        self.assertEqual(p["b"]["stance"], "Southpaw")
        self.assertEqual(p["differences"], {"height_in": 2.0, "reach_in": 3.0, "reach_minus_height_in": 1.0,
                                            "age_years": round(34.5 - 36.94, 2)})
        self.assertEqual(p["stance_matchup"], "Orthodox vs Southpaw")
        self.assertFalse(p["same_stance"])
        self.assertTrue(self.sheet("101", "103")["physical"]["same_stance"])

    def test_age_is_measured_at_the_as_of(self):
        # 101: 1992-04-10 to 2026-10-10 is 12,418 days to 2026-04-10 plus 183 = 12,601 -> 34.50 years
        # 102: 1989-11-02 to 2026-10-10 is 13,149 days to 2025-11-02 plus 342 = 13,491 -> 36.94 years
        self.assertEqual(self.m["physical"]["a"]["age_years"], 34.5)
        self.assertEqual(self.m["physical"]["b"]["age_years"], 36.94)
        earlier = self.sheet("101", "102", "2026-04-10")["physical"]
        self.assertEqual(earlier["a"]["age_years"], 34.0)          # 12,418 days / 365.2425 = 34.0

    def test_layoff_comparison(self):
        layoff = self.m["layoff"]
        # 101 last fought 2026-06-13T22:00, 102 on 2026-08-08T22:00; measured to 2026-10-10T23:00
        self.assertEqual((layoff["a_days"], layoff["b_days"]), (119, 63))
        self.assertEqual(layoff["difference_days"], 56)
        self.assertEqual(layoff["longer_layoff"], "a")
        self.assertEqual(layoff["measured_to"], "2026-10-10T23:00:00Z")
        self.assertEqual(layoff["a_last_fight_utc"], "2026-06-13T22:00:00Z")

    def test_a_fighter_with_no_fight_yet_has_no_layoff_to_compare(self):
        layoff = self.sheet("101", "105", "2025-01-01")["layoff"]
        self.assertEqual((layoff["a_days"], layoff["b_days"], layoff["difference_days"], layoff["longer_layoff"]),
                         (None, None, None, None))


class CombinedMissingList(MatchupCase):
    def test_both_sides_missing_entries_are_combined_and_tagged(self):
        missing = self.m["missing"]
        sides = {m["side"] for m in missing}
        self.assertEqual(sides, {"b"})                # 101 has everything; 102 lacks a breakdown and a profile
        figures = {(m["side"], m["figure"]) for m in missing}
        self.assertIn(("b", "ufccom_career"), figures)
        self.assertIn(("b", "sig_strike_share_distance"), figures)
        for entry in missing:
            self.assertEqual(entry["fighter_id"], "102")
            self.assertTrue(entry["reason"])

    def test_it_contains_exactly_each_sides_own_missing_list_plus_the_bout_level_gaps(self):
        m = self.sheet("105", "103", "2025-02-01")    # 105 has no fights, 103 has one
        expected = ([("a", x["figure"]) for x in m["features"]["a"]["missing"]]
                    + [("b", x["figure"]) for x in m["features"]["b"]["missing"]]
                    + [(None, "bout")])
        self.assertEqual([(x["side"], x["figure"]) for x in m["missing"]], expected)


if __name__ == "__main__":
    unittest.main()
