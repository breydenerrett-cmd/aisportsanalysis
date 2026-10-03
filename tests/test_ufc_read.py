"""src/analysis/ufc_read.py: the written read of one UFC fight.

Three kinds of test, none of which touches the network or the real data:

  * RULE tests on small hand-built sheets (tests/_ufc_read_fixtures.py). The BASELINE is two
    identical, solidly sampled fighters, so no rule fires; each test changes one figure and checks
    the one rule that should answer, with the thresholds written out so a change of a number in
    the module shows up here as a failing line and not as a silent change in what readers see;
  * THIN-SAMPLE tests: the data layer's floors (3 fights and 30 fight minutes, 5 fights for shares
    of results, 10 takedown attempts) are the read's floors, a thin figure is labelled and
    down-weighted, and a large gap on thin data ranks below a moderate gap on fair data;
  * SWEEPS over every read this file produces: every evidence path resolves against the sheet and
    its value matches, nothing reads as a pick, a lock, a profit claim or a probability of ours,
    no dash, no field name, no gendered pronoun reaches a reader.

The last class runs the read over every pair of the synthetic world the data layer's own tests use,
so a hand-built sheet cannot drift from a real one without something failing.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.analysis import ufc_read as ur
from src.datasvc.ufc import matchup
from tests._ufc_read_fixtures import BASE_VALUES, figure, make_sheet, odds_block

NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)


def read_of(sheet=None, **kw):
    return ur.build_read(sheet if sheet is not None else make_sheet(**kw))


def traits(side_read, kind):
    return [i["trait"] for i in side_read[kind]]


def item(read, side, kind, trait):
    found = [i for i in read[side][kind] if i["trait"] == trait]
    assert found, f"no {trait} {kind} for {side}: {traits(read[side], kind)}"
    return found[0]


def route_keys(read, side):
    return [r["route"] for r in read[side]["paths_to_victory"]]


def walk(node, path=()):
    """(path, value) for every leaf of a nested read."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (i,))
    else:
        yield path, node


def evidence_entries(read):
    out = []

    def rec(node):
        if isinstance(node, dict):
            if {"path", "label", "value"} <= set(node):
                out.append(node)
            for v in node.values():
                rec(v)
        elif isinstance(node, list):
            for v in node:
                rec(v)

    rec(read)
    return out


def prose(read):
    """Every string that can reach a reader: anything with a space in it, except an evidence path."""
    out = []
    for path, value in walk(read):
        if isinstance(value, str) and " " in value and "path" not in [p for p in path if isinstance(p, str)][-1:]:
            out.append(value)
    return out


# -- the baseline says nothing --------------------------------------------------------------------

class TheBaselineIsQuiet(unittest.TestCase):
    def test_two_identical_solid_fighters_produce_no_strength_or_weakness(self):
        r = read_of()
        for side in ("a", "b"):
            # the only thing that can fire on identical fighters is a one-sided fact; the baseline has none
            self.assertEqual(r[side]["strengths"], [])
            self.assertEqual(r[side]["weaknesses"], [])
            self.assertEqual(route_keys(r, side), ["none"])

    def test_the_headline_says_nothing_separates_them_and_calls_that_a_valid_read(self):
        r = read_of()
        self.assertIn("No single difference clearly separates Alex Archer and Ben Brawler", r["headline"])
        self.assertIn("valid read", r["headline"])
        self.assertIsNone(r["headline_trait"])

    def test_the_shape(self):
        r = read_of()
        self.assertEqual(set(r), {"version", "label", "as_of", "headline", "headline_trait", "notices", "data_depth",
                                  "a", "b", "context", "history", "market_view", "what_would_change_it", "missing"})
        for side in ("a", "b"):
            self.assertEqual(set(r[side]), {"fighter_id", "name", "strengths", "weaknesses", "paths_to_victory", "context"})
        self.assertEqual(r["version"], ur.READ_VERSION)
        self.assertEqual(r["label"], ur.LABEL)

    def test_it_is_plain_json_deterministic_and_never_edits_the_sheet(self):
        sheet = make_sheet(a={"figures": {"sig_strikes_landed_per_min": figure(6.0), "sig_strikes_absorbed_per_min": figure(3.0)}})
        before = json.dumps(sheet, sort_keys=True)
        r1, r2 = ur.build_read(sheet), ur.build_read(sheet)
        self.assertEqual(json.dumps(sheet, sort_keys=True), before)
        self.assertEqual(r1, r2)
        self.assertEqual(json.loads(json.dumps(r1)), r1)

    def test_a_bare_sheet_does_not_raise(self):
        for sparse in ({}, {"a": {"name": "A"}, "b": {"name": "B"}}, {"features": {}},
                       {"a": {"name": "X"}, "b": {"name": "Y"}, "features": {"a": {}, "b": {}}, "odds": {}}):
            with self.subTest(sparse=sparse):
                r = ur.build_read(sparse)
                self.assertIn("headline", r)
                self.assertIn("missing", r)

    def test_the_market_view_is_not_asked_to_agree_with_nothing(self):
        r = read_of()
        self.assertEqual(r["market_view"]["agreement"], "no lean")
        self.assertEqual(r["market_view"]["lean"], "none")


# -- rule by rule ---------------------------------------------------------------------------------

def F(**names):
    return {k: figure(v) if not isinstance(v, dict) else v for k, v in names.items()}


class StrikingRules(unittest.TestCase):
    def test_net_strikes_gap_sizes(self):
        # net = landed - absorbed; a's net minus b's net must reach 1.5 / 3.0 / 5.0
        for landed, absorbed, size in ((4.8, 4.0, None), (5.5, 4.0, "slight"), (6.5, 3.5, "moderate"), (7.0, 2.0, "large")):
            with self.subTest(net=landed - absorbed):
                r = read_of(a={"figures": F(sig_strikes_landed_per_min=landed, sig_strikes_absorbed_per_min=absorbed)})
                if size is None:
                    self.assertNotIn("striking_net", traits(r["a"], "strengths"))
                else:
                    self.assertEqual(item(r, "a", "strengths", "striking_net")["size"], size)

    def test_the_strength_and_the_weakness_are_the_two_sides_of_one_comparison(self):
        r = read_of(a={"figures": F(sig_strikes_landed_per_min=6.0, sig_strikes_absorbed_per_min=3.0)},
                    b={"figures": F(sig_strikes_landed_per_min=3.0, sig_strikes_absorbed_per_min=5.0)})
        win, lose = item(r, "a", "strengths", "striking_net"), item(r, "b", "weaknesses", "striking_net")
        self.assertEqual((win["size"], lose["size"]), ("large", "large"))      # nets +3.0 and -2.0: a gap of 5.0
        self.assertIn("Alex Archer out-strikes Ben Brawler", win["sentence"])
        self.assertIn("a net of +3.0 significant strikes a minute (landing 6.0, absorbing 3.0)", win["sentence"])
        self.assertIn("against -2.0 for Ben Brawler (landing 3.0, absorbing 5.0)", win["sentence"])
        self.assertIn("Ben Brawler gets the worse of the striking", lose["sentence"])
        self.assertEqual(r["headline_trait"], "striking_net")
        self.assertTrue(r["headline"].startswith("The biggest difference is in the striking."))

    def test_accuracy_and_defence_gaps(self):
        r = read_of(a={"figures": F(sig_strike_accuracy=0.60, sig_strike_defence=0.69)},
                    b={"figures": F(sig_strike_accuracy=0.50, sig_strike_defence=0.55)})
        self.assertEqual(item(r, "a", "strengths", "striking_accuracy")["size"], "moderate")      # 0.10 >= 0.10
        self.assertEqual(item(r, "a", "strengths", "striking_defence")["size"], "large")          # 0.14 >= 0.14
        self.assertIn("60% of significant strikes thrown landing against 50% for Ben Brawler",
                      item(r, "a", "strengths", "striking_accuracy")["sentence"])
        self.assertIn("69% of the significant strikes thrown at Alex Archer missing against 55% for Ben Brawler",
                      item(r, "a", "strengths", "striking_defence")["sentence"])
        slight = read_of(a={"figures": F(sig_strike_accuracy=0.54, sig_strike_defence=0.61)})
        self.assertEqual(item(slight, "a", "strengths", "striking_accuracy")["size"], "slight")   # 0.06
        self.assertEqual(item(slight, "a", "strengths", "striking_defence")["size"], "slight")    # 0.06
        self.assertIn("striking_accuracy", traits(r["b"], "weaknesses"))
        self.assertIn("striking_defence", traits(r["b"], "weaknesses"))

    def test_below_the_first_threshold_nothing_is_said(self):
        r = read_of(a={"figures": F(sig_strike_accuracy=0.53, sig_strike_defence=0.60)})
        self.assertEqual(traits(r["a"], "strengths"), [])

    def test_a_missing_figure_skips_the_rule(self):
        r = read_of(a={"figures": F(sig_strikes_landed_per_min={"value": None, "unit": "u", "fights": 0, "minutes": 0.0})})
        self.assertNotIn("striking_net", traits(r["a"], "strengths") + traits(r["b"], "weaknesses"))


class GrapplingRules(unittest.TestCase):
    def td_sheet(self, rate, defence, den=20, **kw):
        return read_of(a={"figures": F(takedowns_landed_per_15=rate)},
                       b={"figures": {"takedown_defence": figure(defence, num=round(den * (1 - defence)), den=den)}}, **kw)

    def test_an_open_door_is_a_strength_for_the_attacker_and_a_weakness_for_the_defender(self):
        r = self.td_sheet(2.9, 0.52, den=31)
        win, lose = item(r, "a", "strengths", "takedown_open"), item(r, "b", "weaknesses", "takedown_open")
        self.assertEqual(win["size"], "moderate")     # rate 2.9 >= 2.5 and defence 0.52 <= 0.65 (not <= 0.50)
        self.assertIn("Alex Archer can take Ben Brawler down, landing 2.9 takedowns per 15 minutes while Ben Brawler has stopped 52% "
                      "of 31 attempts against Ben Brawler", win["sentence"])
        self.assertIn("Ben Brawler is easy to take down, having stopped 52% of 31 takedown attempts", lose["sentence"])

    def test_the_size_adds_a_point_for_each_extra_reason(self):
        self.assertEqual(item(self.td_sheet(1.6, 0.60), "a", "strengths", "takedown_open")["size"], "slight")
        self.assertEqual(item(self.td_sheet(2.6, 0.60), "a", "strengths", "takedown_open")["size"], "moderate")
        self.assertEqual(item(self.td_sheet(1.6, 0.45), "a", "strengths", "takedown_open")["size"], "moderate")
        self.assertEqual(item(self.td_sheet(2.6, 0.45), "a", "strengths", "takedown_open")["size"], "large")

    def test_a_defence_that_holds_is_the_defenders_strength(self):
        r = self.td_sheet(3.0, 0.90, den=24)
        win, lose = item(r, "b", "strengths", "takedown_closed"), item(r, "a", "weaknesses", "takedown_closed")
        self.assertEqual(win["size"], "moderate")
        self.assertIn("Ben Brawler is hard to take down, having stopped 90% of 24 takedown attempts, against Alex Archer's 3.0 landed",
                      win["sentence"])
        self.assertIn("Alex Archer's takedown game meets a strong defence", lose["sentence"])
        self.assertEqual(item(self.td_sheet(1.6, 0.82), "b", "strengths", "takedown_closed")["size"], "slight")

    def test_no_route_is_read_without_real_takedown_offence_or_enough_attempts(self):
        self.assertNotIn("takedown_open", traits(self.td_sheet(1.2, 0.40)["a"], "strengths"))         # rate under 1.5
        self.assertNotIn("takedown_open", traits(self.td_sheet(3.0, 0.40, den=4)["a"], "strengths"))  # under 5 attempts
        self.assertNotIn("takedown_open", traits(self.td_sheet(3.0, 0.70)["a"], "strengths"))         # between the bars

    def test_a_takedown_defence_on_fewer_than_ten_attempts_is_thin(self):
        thin = item(self.td_sheet(3.0, 0.40, den=9), "a", "strengths", "takedown_open")
        fair = item(self.td_sheet(3.0, 0.40, den=10), "a", "strengths", "takedown_open")
        self.assertTrue(thin["thin"])
        self.assertEqual(fair["sample_level"], ur.FAIR)
        self.assertIn("under 10 attempts is thin", thin["caveat"])

    def test_control_gap(self):
        for a_share, size in ((0.22, None), (0.26, "slight"), (0.36, "moderate"), (0.50, "large")):
            r = read_of(a={"figures": F(control_time_share=a_share)})
            if size is None:
                self.assertNotIn("control", traits(r["a"], "strengths"))
            else:
                self.assertEqual(item(r, "a", "strengths", "control")["size"], size)
        r = read_of(a={"figures": F(control_time_share=0.40)})
        self.assertIn("Alex Archer controls the fight for longer, spending 40% of fight time in control against 15% for Ben Brawler",
                      item(r, "a", "strengths", "control")["sentence"])

    def test_submission_threat_and_being_submitted(self):
        r = read_of(a={"figures": F(submission_attempts_per_15=1.9)}, b={"record_update": {"losses_by_method": {
            "ko_tko": 0, "submission": 3, "decision": 0, "dq": 0, "other": 0, "unknown": 0}}})
        self.assertEqual(item(r, "a", "strengths", "submission_threat")["size"], "moderate")
        self.assertIn("Alex Archer hunts submissions, throwing 1.9 attempts per 15 minutes", item(r, "a", "strengths", "submission_threat")["sentence"])
        weak = item(r, "b", "weaknesses", "been_submitted")
        self.assertEqual(weak["size"], "moderate")
        self.assertIn("Ben Brawler has lost by submission 3 times in 8 fights on file", weak["sentence"])
        self.assertNotIn("been_submitted", traits(read_of(b={"record_update": {"losses_by_method": {
            "ko_tko": 0, "submission": 1, "decision": 0, "dq": 0, "other": 0, "unknown": 0}}})["b"], "weaknesses"))


class FinishingRules(unittest.TestCase):
    def test_knockdown_power_and_chin(self):
        r = read_of(a={"figures": F(knockdowns_landed_per_15=1.5)}, b={"figures": F(knockdowns_suffered_per_15=1.4)})
        self.assertEqual(item(r, "a", "strengths", "knockdown_power")["size"], "moderate")
        self.assertIn("Alex Archer scores knockdowns, 1.5 per 15 minutes", item(r, "a", "strengths", "knockdown_power")["sentence"])
        chin = item(r, "b", "weaknesses", "chin")
        self.assertEqual(chin["size"], "moderate")
        self.assertIn("Ben Brawler has been knocked down 1.4 times per 15 minutes", chin["sentence"])
        self.assertEqual(item(read_of(a={"figures": F(knockdowns_landed_per_15=0.8)}), "a", "strengths", "knockdown_power")["size"], "slight")
        self.assertEqual(item(read_of(a={"figures": F(knockdowns_landed_per_15=2.2)}), "a", "strengths", "knockdown_power")["size"], "large")
        self.assertNotIn("knockdown_power", traits(read_of(a={"figures": F(knockdowns_landed_per_15=0.7)})["a"], "strengths"))

    def test_losses_by_ko_alone_raise_a_chin_question_only_from_two(self):
        two = {"losses_by_method": {"ko_tko": 2, "submission": 0, "decision": 1, "dq": 0, "other": 0, "unknown": 0}}
        one = {"losses_by_method": {"ko_tko": 1, "submission": 0, "decision": 2, "dq": 0, "other": 0, "unknown": 0}}
        r = read_of(b={"record_update": two})
        chin = item(r, "b", "weaknesses", "chin")
        self.assertEqual(chin["size"], "slight")
        self.assertIn("Ben Brawler has lost by KO or TKO twice in 8 fights on file", chin["sentence"])
        self.assertNotIn("chin", traits(read_of(b={"record_update": one})["b"], "weaknesses"))

    def test_finishing_and_being_finished_use_the_data_layers_bars(self):
        self.assertEqual(ur.FINISH_RATE[0], 0.60)
        self.assertEqual(ur.BEEN_FINISHED_RATE[0], 0.30)
        r = read_of(a={"figures": {"finish_rate": figure(0.75, num=6, den=8)}},
                    b={"figures": {"been_finished_rate": figure(0.5, num=4, den=8)}})
        fin = item(r, "a", "strengths", "finisher")
        self.assertEqual(fin["size"], "moderate")
        self.assertIn("Alex Archer finishes fights, with 6 of 8 ending in a finishing win by KO, TKO or submission", fin["sentence"])
        weak = item(r, "b", "weaknesses", "finished_often")
        self.assertEqual(weak["size"], "moderate")
        self.assertIn("Ben Brawler gets finished, with 4 of 8 ending in a loss by KO, TKO or submission", weak["sentence"])
        self.assertNotIn("finisher", traits(read_of(a={"figures": {"finish_rate": figure(0.55, num=5, den=9)}})["a"], "strengths"))


class PaceFormAndPhysicalRules(unittest.TestCase):
    def five_round(self, **kw):
        bout = make_sheet()["bout"]
        bout["scheduled_rounds"] = 5
        return read_of(bout=bout, **kw)

    def test_fight_length_is_read_only_for_five_round_bouts(self):
        a = {"figures": F(average_fight_time_s=1300.0)}
        b = {"figures": F(average_fight_time_s=420.0)}
        self.assertNotIn("fight_length", traits(read_of(a=a, b=b)["a"], "strengths"))
        r = self.five_round(a=a, b=b)
        win, lose = item(r, "a", "strengths", "fight_length"), item(r, "b", "weaknesses", "fight_length")
        self.assertEqual(win["size"], "large")        # gap 880 s >= 600
        self.assertIn("Alex Archer has been deeper into fights, averaging 21.7 minutes on file against 7.0 for Ben Brawler, "
                      "in a bout scheduled for 5 rounds", win["sentence"])
        self.assertIn("late rounds are less tested", lose["sentence"])
        self.assertIn("deep", route_keys(r, "a"))

    def test_a_long_average_on_both_sides_makes_no_weakness_for_the_shorter(self):
        r = self.five_round(a={"figures": F(average_fight_time_s=1400.0)}, b={"figures": F(average_fight_time_s=900.0)})
        self.assertIn("fight_length", traits(r["a"], "strengths"))
        self.assertNotIn("fight_length", traits(r["b"], "weaknesses"))

    def test_layoff(self):
        for days, size in ((300, None), (400, "slight"), (600, "moderate"), (800, "large")):
            r = read_of(layoff={"a_days": days, "a_last_fight_utc": "2025-01-01T22:00:00Z"})
            if size is None:
                self.assertNotIn("long_layoff", traits(r["a"], "weaknesses"))
            else:
                self.assertEqual(item(r, "a", "weaknesses", "long_layoff")["size"], size)
        r = read_of(layoff={"a_days": 640, "a_last_fight_utc": "2025-01-01T22:00:00Z"})
        self.assertIn("Alex Archer has not fought in the UFC for 21 months, since the last fight on file on 2025-01-01",
                      item(r, "a", "weaknesses", "long_layoff")["sentence"])
        self.assertIsNone(item(r, "a", "weaknesses", "long_layoff")["sample"])

    def test_a_short_turnaround_is_context_not_a_weakness(self):
        r = read_of(layoff={"a_days": 28})
        self.assertEqual(r["a"]["weaknesses"], [])
        self.assertIn("short_turnaround", [c["key"] for c in r["a"]["context"]])

    def test_age_is_read_only_when_the_older_fighter_is_34_or_more(self):
        old = read_of(physical={"a": {"age_years": 38.0}, "b": {"age_years": 29.0}})
        self.assertEqual(item(old, "b", "strengths", "age")["size"], "moderate")      # gap 9 >= 7
        self.assertIn("Ben Brawler is the younger fighter by 9.0 years (29.0 against 38.0)", item(old, "b", "strengths", "age")["sentence"])
        self.assertIn("Alex Archer is the older fighter by 9.0 years", item(old, "a", "weaknesses", "age")["sentence"])
        young = read_of(physical={"a": {"age_years": 33.5}, "b": {"age_years": 24.0}})
        self.assertNotIn("age", traits(young["b"], "strengths"))
        self.assertEqual(item(read_of(physical={"a": {"age_years": 38.0}, "b": {"age_years": 33.0}}), "b", "strengths", "age")["size"], "slight")

    def test_reach_and_height(self):
        r = read_of(physical={"a": {"reach_in": 78.0, "height_in": 73.0}, "b": {"reach_in": 72.0, "height_in": 70.0}})
        self.assertEqual(item(r, "a", "strengths", "reach")["size"], "large")          # 6 in
        self.assertEqual(item(r, "a", "strengths", "height")["size"], "slight")        # 3 in
        self.assertIn("Alex Archer has the longer reach by 6.0 inches (78 against 72)", item(r, "a", "strengths", "reach")["sentence"])
        self.assertIn("Ben Brawler gives away 6.0 inches of reach (72 against 78)", item(r, "b", "weaknesses", "reach")["sentence"])
        self.assertNotIn("reach", traits(read_of(physical={"a": {"reach_in": 76.5}})["a"], "strengths"))      # 2.5 in: under the bar
        self.assertEqual(item(read_of(physical={"a": {"reach_in": 77.0}}), "a", "strengths", "reach")["size"], "slight")       # 3.0
        self.assertEqual(item(read_of(physical={"a": {"reach_in": 78.5}}), "a", "strengths", "reach")["size"], "moderate")     # 4.5
        self.assertEqual(item(read_of(physical={"a": {"height_in": 76.0}}), "a", "strengths", "height")["size"], "moderate")   # 4
        self.assertEqual(item(read_of(physical={"a": {"height_in": 78.0}}), "a", "strengths", "height")["size"], "large")      # 6
        self.assertEqual(item(r, "a", "strengths", "reach")["sample_level"], ur.FAIR)

    def test_schedule_and_results(self):
        r = read_of(a={"figures": {"strength_of_schedule": figure(0.66, fights=6), "win_rate": figure(0.85, fights=7)},
                       "record_update": {"fights": 7, "wins": 6, "losses": 1}},
                    b={"figures": {"strength_of_schedule": figure(0.45, fights=6), "win_rate": figure(0.5, fights=6)}})
        self.assertEqual(item(r, "a", "strengths", "schedule")["size"], "moderate")    # 0.21 >= 0.15
        self.assertEqual(item(r, "a", "strengths", "results")["size"], "moderate")     # 0.35 >= 0.35
        self.assertIn("opponents who had won 66% of their UFC fights going in against 45% for Ben Brawler's",
                      item(r, "a", "strengths", "schedule")["sentence"])
        self.assertIn("6 wins in 7 fights against 5 wins in 8 fights for Ben Brawler", item(r, "a", "strengths", "results")["sentence"])

    def test_streaks(self):
        r = read_of(a={"streak": {"type": "win", "length": 5}}, b={"streak": {"type": "loss", "length": 3}})
        self.assertEqual(item(r, "a", "strengths", "win_streak")["size"], "moderate")
        self.assertEqual(item(r, "b", "weaknesses", "loss_streak")["size"], "moderate")
        self.assertIn("Alex Archer has won 5 fights in a row on file", item(r, "a", "strengths", "win_streak")["sentence"])
        self.assertEqual(item(r, "a", "strengths", "win_streak")["sample_level"], ur.FAIR)
        short = read_of(a={"streak": {"type": "win", "length": 3}}, b={"streak": {"type": "loss", "length": 2}})
        self.assertTrue(item(short, "a", "strengths", "win_streak")["thin"])
        self.assertTrue(item(short, "b", "weaknesses", "loss_streak")["thin"])
        self.assertNotIn("win_streak", traits(read_of(a={"streak": {"type": "win", "length": 2}})["a"], "strengths"))
        self.assertNotIn("loss_streak", traits(read_of(b={"streak": {"type": "loss", "length": 1}})["b"], "weaknesses"))
        self.assertNotIn("win_streak", traits(read_of(a={"streak": {"type": "draw", "length": 4}})["a"], "strengths"))


# -- routes ---------------------------------------------------------------------------------------

class RoutesToVictory(unittest.TestCase):
    def test_a_knockout_route_needs_power_and_something_on_the_chin(self):
        r = read_of(a={"figures": F(knockdowns_landed_per_15=1.5)}, b={"figures": F(knockdowns_suffered_per_15=1.4)})
        ko = [x for x in r["a"]["paths_to_victory"] if x["route"] == "knockout"][0]
        self.assertEqual(ko["title"], "Hurt and finish")
        self.assertTrue(ko["sentence"].startswith("Alex Archer scores 1.5 knockdowns per 15 minutes on file, and Ben Brawler has been "
                                                  "knocked down 1.4 times per 15 minutes"), ko["sentence"])
        self.assertEqual(ko["built_from"], ["knockdown_power", "chin"])
        # power with nothing on the other chin is a weaker, differently worded route
        no_ko = {"record_update": {"losses_by_method": {"ko_tko": 0, "submission": 0, "decision": 3, "dq": 0, "other": 0, "unknown": 0}}}
        alone = [x for x in read_of(a={"figures": F(knockdowns_landed_per_15=1.5)}, b=no_ko)["a"]["paths_to_victory"]
                 if x["route"] == "knockout"][0]
        self.assertTrue(alone["sentence"].startswith("Alex Archer scores 1.5 knockdowns per 15 minutes on file, though"))
        self.assertIn("nothing on file says Ben Brawler is easy to drop", alone["sentence"])

    def test_one_ko_loss_on_the_opponent_is_enough_to_pair_with_power(self):
        r = read_of(a={"figures": F(knockdowns_landed_per_15=1.5)})
        ko = [x for x in r["a"]["paths_to_victory"] if x["route"] == "knockout"][0]
        self.assertIn("Ben Brawler has lost by KO or TKO once in 8 fights on file", ko["sentence"])
        self.assertEqual(ko["built_from"], ["knockdown_power", "ko_losses"])

    def test_the_mat_route(self):
        r = read_of(a={"figures": F(takedowns_landed_per_15=3.0, control_time_share=0.40)},
                    b={"figures": {"takedown_defence": figure(0.45, num=11, den=20)}})
        mat = [x for x in r["a"]["paths_to_victory"] if x["route"] == "mat"][0]
        self.assertEqual(mat["title"], "Take it to the mat")
        self.assertEqual(mat["sentence"], "Alex Archer lands 3.0 takedowns per 15 minutes on file, and Ben Brawler has stopped only "
                                          "45% of 20 attempts; Alex Archer has also spent 40% of fight time in control.")
        self.assertIn("control", mat["built_from"])

    def test_a_submission_route_needs_the_threat_and_a_reason_to_think_it_gets_there(self):
        threat = {"figures": F(submission_attempts_per_15=2.0)}
        self.assertNotIn("submission", route_keys(read_of(a=threat), "a"))
        submitted = {"record_update": {"losses_by_method": {"ko_tko": 0, "submission": 2, "decision": 1, "dq": 0, "other": 0, "unknown": 0}}}
        r = read_of(a=threat, b=submitted)
        sub = [x for x in r["a"]["paths_to_victory"] if x["route"] == "submission"][0]
        self.assertEqual(sub["title"], "Find a submission")
        self.assertEqual(sub["sentence"], "Alex Archer throws 2.0 submission attempts per 15 minutes on file, and Ben Brawler has "
                                          "lost by submission twice on file.")

    def test_the_striking_route_and_the_keep_it_standing_route(self):
        r = read_of(a={"figures": F(sig_strikes_landed_per_min=6.0, sig_strikes_absorbed_per_min=3.0, sig_strike_accuracy=0.60)})
        strike = [x for x in r["a"]["paths_to_victory"] if x["route"] == "striking"][0]
        self.assertEqual(strike["title"], "Win the striking")
        self.assertEqual(strike["sentence"], "Alex Archer nets +3.0 significant strikes a minute on file against +0.0 for Ben Brawler, "
                                             "and Alex Archer lands more accurately as well. This route needs the fight to stay on the feet.")
        stand = read_of(a={"figures": {"takedown_defence": figure(0.9, num=22, den=24)}}, b={"figures": F(takedowns_landed_per_15=3.0)})
        route = [x for x in stand["a"]["paths_to_victory"] if x["route"] == "stay_standing"][0]
        self.assertIn("Ben Brawler lands 3.0 takedowns per 15 minutes on file, but Alex Archer has stopped 90% of 24 attempts", route["sentence"])
        # not offered when the other fighter wins the striking: staying on the feet is no route then
        worse = read_of(a={"figures": {"takedown_defence": figure(0.9, num=22, den=24)}},
                        b={"figures": F(takedowns_landed_per_15=3.0, sig_strikes_landed_per_min=6.5, sig_strikes_absorbed_per_min=3.0)})
        self.assertNotIn("stay_standing", route_keys(worse, "a"))

    def test_the_scorecards_route(self):
        a = {"record_update": {"fights": 8, "wins": 4, "losses": 4, "wins_by_method": {
            "ko_tko": 0, "submission": 1, "decision": 3, "dq": 0, "other": 0, "unknown": 0}}}
        r = read_of(a=a, b={"figures": {"finish_rate": figure(0.25, num=2, den=8)}})
        sc = [x for x in r["a"]["paths_to_victory"] if x["route"] == "scorecards"][0]
        self.assertEqual(sc["title"], "Win on the scorecards")
        self.assertEqual(sc["sentence"], "3 of Alex Archer's 4 wins on file came by decision, and Ben Brawler has finished 25% of "
                                         "fights on file.")
        self.assertIn("features.b.figures.finish_rate.value", [e["path"] for e in sc["evidence"]])

    def test_routes_are_ranked_and_capped(self):
        a = {"figures": F(sig_strikes_landed_per_min=7.0, sig_strikes_absorbed_per_min=2.0, takedowns_landed_per_15=3.0,
                          control_time_share=0.4, knockdowns_landed_per_15=1.6, submission_attempts_per_15=2.0)}
        b = {"figures": {"takedown_defence": figure(0.4, num=12, den=20), "knockdowns_suffered_per_15": figure(1.5)}}
        r = read_of(a=a, b=b)
        weights = [x["weight"] for x in r["a"]["paths_to_victory"]]
        self.assertEqual(len(weights), ur.MAX_ROUTES)
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_with_nothing_to_go_on_the_route_says_so_and_why(self):
        r = read_of(a={"record_update": {"fights": 2}, "sample": {"fights": 2, "minutes": 20.0}})
        route = r["a"]["paths_to_victory"][0]
        self.assertEqual(route["route"], "none")
        self.assertEqual(route["sentence"], "Nothing in the figures on file points to a route to a win for Alex Archer, "
                                            "and only 2 fights are on file.")


# -- thin samples ---------------------------------------------------------------------------------

class ThinSamples(unittest.TestCase):
    def test_the_floors_are_the_data_layers_own(self):
        self.assertEqual((ur.MIN_FIGHTS_TIMED, ur.MIN_MINUTES_TIMED, ur.MIN_FIGHTS_RESULTS),
                         (matchup.MIN_FIGHTS_TIMED, matchup.MIN_MINUTES_TIMED, matchup.MIN_FIGHTS_RESULTS))
        self.assertEqual(ur.MIN_ATTEMPTS_DEFENCE, matchup.HARD_TO_TAKE_DOWN_MIN_ATTEMPTS)
        self.assertEqual((ur.SOLID_FIGHTS_TIMED, ur.SOLID_MINUTES_TIMED, ur.SOLID_FIGHTS_RESULTS), (6, 60.0, 10))

    def test_the_levels_at_each_boundary(self):
        def level(fights, minutes):
            return ur._level_timed([figure(1.0, fights=fights, minutes=minutes)])
        self.assertEqual(level(2, 100.0), ur.THIN)
        self.assertEqual(level(8, 29.9), ur.THIN)
        self.assertEqual(level(3, 30.0), ur.FAIR)
        self.assertEqual(level(5, 59.9), ur.FAIR)
        self.assertEqual(level(6, 60.0), ur.SOLID)
        self.assertEqual(ur._level_results([figure(0.5, fights=4)]), ur.THIN)
        self.assertEqual(ur._level_results([figure(0.5, fights=5)]), ur.FAIR)
        self.assertEqual(ur._level_results([figure(0.5, fights=10)]), ur.SOLID)
        self.assertEqual(ur._level_timed([figure(1.0, fights=9, minutes=90.0), figure(1.0, fights=2, minutes=90.0)]), ur.THIN)

    def thin_net(self, fights=2, minutes=20.0):
        landed, absorbed = figure(6.5, fights=fights, minutes=minutes), figure(3.0, fights=fights, minutes=minutes)
        return read_of(a={"figures": {"sig_strikes_landed_per_min": landed, "sig_strikes_absorbed_per_min": absorbed}})

    def test_a_thin_item_is_labelled_down_weighted_and_says_how_little_is_behind_it(self):
        r = self.thin_net()
        it = item(r, "a", "strengths", "striking_net")
        self.assertTrue(it["thin"])
        self.assertTrue(it["down_weighted"])
        self.assertEqual(it["sample_level"], "thin")
        self.assertEqual(it["sample"], {"fights": 2, "minutes": 20.0})
        self.assertEqual(it["weight"], round(ur.SIZE_RANK[it["size"]] * 0.3, 2))
        self.assertTrue(it["caveat"].startswith("Thin sample: Alex Archer has fewer than 3 fights or 30 fight minutes"))
        self.assertIn("(on file: Alex Archer 2 fights, 20 minutes; Ben Brawler 8 fights, 100 minutes)", it["sentence"])
        # the opponent's side of the same comparison carries the same flag
        self.assertTrue(item(r, "b", "weaknesses", "striking_net")["thin"])

    def test_the_headline_says_when_the_biggest_difference_rests_on_thin_data(self):
        r = self.thin_net()
        self.assertEqual(r["headline_trait"], "striking_net")
        self.assertIn("The sample behind it is thin, so treat it as an early sign.", r["headline"])
        self.assertNotIn("thin", read_of(a={"figures": F(sig_strikes_landed_per_min=6.5, sig_strikes_absorbed_per_min=3.0)})["headline"])

    def test_a_large_gap_on_thin_data_ranks_below_a_moderate_gap_on_fair_data(self):
        r = read_of(a={"figures": {"sig_strikes_landed_per_min": figure(7.0, fights=2, minutes=20.0),
                                   "sig_strikes_absorbed_per_min": figure(2.0, fights=2, minutes=20.0)}},
                    physical={"a": {"reach_in": 78.0}, "b": {"reach_in": 73.0}})
        strengths = r["a"]["strengths"]
        self.assertEqual([s["trait"] for s in strengths], ["reach", "striking_net"])
        self.assertEqual([(s["size"], s["weight"]) for s in strengths], [("moderate", 1.2), ("large", 0.9)])
        self.assertEqual(r["headline_trait"], "reach")

    def test_nothing_clears_the_headline_bar_when_everything_is_slight_and_thin(self):
        r = read_of(a={"figures": {"sig_strike_accuracy": figure(0.54, fights=2, minutes=20.0)}})
        self.assertEqual(r["a"]["strengths"][0]["weight"], 0.3)
        self.assertIsNone(r["headline_trait"])
        self.assertIn("No single difference clearly separates", r["headline"])

    def test_results_shares_need_five_fights(self):
        for fights, thin in ((4, True), (5, False)):
            r = read_of(a={"figures": {"finish_rate": figure(0.8, fights=fights, num=4, den=fights)}})
            self.assertEqual(item(r, "a", "strengths", "finisher")["thin"], thin)
        self.assertIn("fewer than 5 fights", item(read_of(a={"figures": {"finish_rate": figure(0.8, fights=4, num=3, den=4)}}),
                                                  "a", "strengths", "finisher")["caveat"])

    def test_depth_levels_and_what_they_say(self):
        solid = read_of()["data_depth"]
        self.assertEqual(solid["level"], "solid")
        thin = read_of(a={"sample": {"fights": 2, "minutes": 25.0}})["data_depth"]
        self.assertEqual(thin["level"], "thin")
        self.assertIn("under 3 fights or 30 fight minutes for Alex Archer", thin["sentence"])
        fair = read_of(b={"sample": {"fights": 4, "minutes": 50.0}})["data_depth"]
        self.assertEqual(fair["level"], "fair")
        self.assertIn("Alex Archer 8 UFC fights (100 minutes), out of 16 professional fights in all", solid["sentence"])

    def test_every_thin_item_in_a_read_names_who_is_thin(self):
        r = read_of(a={"sample": {"fights": 2, "minutes": 25.0},
                       "figures": {"sig_strike_accuracy": figure(0.60, fights=2, minutes=25.0),
                                   "control_time_share": figure(0.45, fights=2, minutes=25.0)}})
        for side in ("a", "b"):
            for kind in ("strengths", "weaknesses"):
                for it in r[side][kind]:
                    if it["thin"]:
                        self.assertTrue(it["caveat"].startswith("Thin sample"), it)


class DisplayFloors(unittest.TestCase):
    """One fight is an anecdote. Below 2 fights a rate is not shown at all, below 3 a share of results is not,
    and the missing list says they were held back."""

    def test_the_floors(self):
        self.assertEqual((ur.MIN_FIGHTS_SHOWN_TIMED, ur.MIN_FIGHTS_SHOWN_RESULTS), (2, 3))

    def one_fight(self, **extra):
        figs = {k: figure(v, fights=1, minutes=22.0) for k, v in BASE_VALUES.items()}
        figs.update(extra)
        return {"figures": figs, "sample": {"fights": 1, "minutes": 22.0}, "record_update": {"fights": 1, "wins": 1, "losses": 0}}

    def test_a_rate_from_one_fight_is_not_a_strength_or_a_weakness(self):
        loud = self.one_fight(sig_strikes_landed_per_min=figure(8.0, fights=1, minutes=22.0),
                              sig_strikes_absorbed_per_min=figure(2.0, fights=1, minutes=22.0),
                              sig_strike_accuracy=figure(0.7, fights=1, minutes=22.0),
                              knockdowns_landed_per_15=figure(3.0, fights=1, minutes=22.0),
                              submission_attempts_per_15=figure(4.0, fights=1, minutes=22.0),
                              takedowns_landed_per_15=figure(5.0, fights=1, minutes=22.0))
        r = read_of(a=loud)
        self.assertEqual(r["a"]["strengths"], [])
        self.assertEqual(r["b"]["weaknesses"], [])

    def test_two_fights_are_enough_to_show_a_rate_flagged_thin(self):
        landed = figure(8.0, fights=2, minutes=25.0)
        absorbed = figure(2.0, fights=2, minutes=25.0)
        r = read_of(a={"figures": {"sig_strikes_landed_per_min": landed, "sig_strikes_absorbed_per_min": absorbed}})
        self.assertTrue(item(r, "a", "strengths", "striking_net")["thin"])

    def test_a_share_of_results_needs_three_fights(self):
        for fights, shown in ((2, False), (3, True)):
            r = read_of(a={"figures": {"finish_rate": figure(1.0, fights=fights, num=fights, den=fights),
                                       "win_rate": figure(1.0, fights=fights)},
                           "record_update": {"fights": fights, "wins": fights, "losses": 0}},
                        b={"figures": {"win_rate": figure(0.0, fights=3)}})
            self.assertEqual("finisher" in traits(r["a"], "strengths"), shown, fights)
            self.assertEqual("results" in traits(r["a"], "strengths"), shown, fights)

    def test_losses_by_ko_alone_need_three_fights_on_file_to_raise_a_chin_question(self):
        two = {"record_update": {"fights": 2, "losses_by_method": {"ko_tko": 2, "submission": 0, "decision": 0, "dq": 0, "other": 0, "unknown": 0}}}
        self.assertNotIn("chin", traits(read_of(b=two)["b"], "weaknesses"))
        three = {"record_update": {"fights": 3, "losses_by_method": {"ko_tko": 2, "submission": 0, "decision": 0, "dq": 0, "other": 0, "unknown": 0}}}
        self.assertIn("chin", traits(read_of(b=three)["b"], "weaknesses"))

    def test_the_missing_list_says_what_was_held_back_and_from_how_many_fights(self):
        r = read_of(a=self.one_fight())
        details = {m["input"]: m["detail"] for m in r["missing"]}
        self.assertEqual(details["Alex Archer: rates and accuracies"],
                         "1 fight and 22 minutes on file; a rate is shown from 2 fights and counts as more than thin from "
                         "3 fights and 30 fight minutes")
        self.assertEqual(details["Alex Archer: finishing, win and fight-length figures"],
                         "1 fight on file; a share of results is shown from 3 fights and counts as more than thin from 5")

    def test_the_headline_for_a_fighter_with_nothing_names_who_and_does_not_call_it_a_small_sample(self):
        r = read_of(a=no_fights(), b=no_fights())
        self.assertIn("No UFC fights are on file for Alex Archer and Ben Brawler.", r["headline"])
        r = read_of(a=self.one_fight())
        self.assertIn("Little is on file for Alex Archer.", r["headline"])


class LastFightsAndNoBout(unittest.TestCase):
    def fights(self):
        return [{"bout_id": "1", "date_utc": "2026-09-27T00:00Z", "opponent_id": "9", "opponent_name": "Raoni Barcelos",
                 "result": "win", "method": "KO_TKO", "detail": None, "round": 5, "time_s": 98.0, "weight_class": "Bantamweight"},
                {"bout_id": "2", "date_utc": "2026-03-01T00:00Z", "opponent_id": "8", "opponent_name": "Dan Silva",
                 "result": "loss", "method": "SUB", "detail": "Guillotine Choke", "round": 2, "time_s": 100.0, "weight_class": "Bantamweight"},
                {"bout_id": "3", "date_utc": "2025-12-01T00:00Z", "opponent_id": "7", "opponent_name": "Eli Silva",
                 "result": "draw", "method": "DRAW", "detail": None, "round": 3, "time_s": 300.0, "weight_class": "Bantamweight"}]

    def test_the_last_three_fights_are_a_plain_line_with_their_evidence(self):
        r = read_of(a={"last_three": self.fights()})
        line = [c for c in r["a"]["context"] if c["key"] == "last_fights"][0]
        self.assertEqual(line["sentence"],
                         "Alex Archer's last 3 fights on file, newest first: beat Raoni Barcelos by knockout or TKO on 2026-09-27, round 5; "
                         "lost to Dan Silva by submission on 2026-03-01, round 2; drew with Eli Silva on 2025-12-01, round 3.")
        self.assertIn("features.a.last_three.0.result", [e["path"] for e in line["evidence"]])
        one = read_of(a={"last_three": self.fights()[:1]})
        self.assertTrue([c for c in one["a"]["context"] if c["key"] == "last_fights"][0]["sentence"].startswith("Alex Archer's last fight on file:"))
        self.assertFalse([c for c in read_of()["a"]["context"] if c["key"] == "last_fights"])

    def test_with_no_booked_bout_the_words_say_a_date_and_not_a_fight(self):
        r = read_of(bout=None, a=no_fights())
        self.assertTrue(r["data_depth"]["sentence"].startswith("On file as of 2026-10-10:"))
        self.assertIn("no UFC fights on file before 2026-10-10", r["a"]["context"][0]["sentence"])
        inputs = {m["input"]: m["detail"] for m in r["missing"]}
        self.assertIn("no UFC fights on file before 2026-10-10", inputs["Alex Archer: UFC fights"])
        self.assertIn("as a possible matchup measured as of 2026-10-10", r["what_would_change_it"][0]["because"])
        short = read_of(bout=None, layoff={"a_days": 6})
        self.assertNotIn("short_turnaround", [c["key"] for c in short["a"]["context"]])

    def test_with_a_booked_bout_the_words_say_the_bout(self):
        r = read_of(a=no_fights())
        self.assertTrue(r["data_depth"]["sentence"].startswith("On file before this fight:"))
        self.assertIn("no UFC fights on file before this bout", r["a"]["context"][0]["sentence"])

    def test_two_fighters_who_have_only_met_each_other_are_not_said_to_share_opponents(self):
        h = read_of(previous_meetings=[meeting()], shared={"a_opponents": 1, "b_opponents": 1, "count": 0, "items": []})["history"]
        self.assertIn("Counting each other, Alex Archer has faced 1 opponent on file and Ben Brawler has faced 1, "
                      "with no one else in common.", h["summary"])


# -- missing data ---------------------------------------------------------------------------------

def no_fights(name="Alex Archer"):
    gone = {"value": None, "unit": "unit", "fights": 0, "minutes": 0.0,
            "reason": "no UFC fights in the store before as_of"}
    return {"figures": {k: dict(gone) for k in BASE_VALUES}, "sample": {"fights": 0, "minutes": 0.0},
            "record": {"fights": 0, "wins": 0, "losses": 0, "draws": 0, "no_contests": 0,
                       "wins_by_method": {"ko_tko": 0, "submission": 0, "decision": 0, "dq": 0, "other": 0, "unknown": 0},
                       "losses_by_method": {"ko_tko": 0, "submission": 0, "decision": 0, "dq": 0, "other": 0, "unknown": 0},
                       "first_fight_utc": None, "last_fight_utc": None},
            "streak": {"type": None, "length": 0}, "weight_classes": {"current": None}}


class MissingData(unittest.TestCase):
    def debut_read(self):
        missing = [{"side": "a", "fighter_id": "101", "figure": k, "reason": "no UFC fights in the store before as_of"}
                   for k in ("sig_strikes_landed_per_min", "control_time_share", "age_years")]
        return read_of(a=no_fights(), layoff={"a_days": None, "a_last_fight_utc": None}, missing=missing)

    def test_a_fighter_with_no_fights_yields_no_fight_items_and_says_why(self):
        r = self.debut_read()
        self.assertEqual(r["a"]["strengths"], [])
        self.assertEqual(r["a"]["weaknesses"], [])
        inputs = {m["input"]: m for m in r["missing"]}
        self.assertEqual(inputs["Alex Archer: UFC fights"]["status"], "absent")
        self.assertIn("every figure built from fights is missing", inputs["Alex Archer: UFC fights"]["detail"])
        self.assertEqual(r["data_depth"]["level"], "thin")
        self.assertIn("no UFC fights on file before this bout", r["a"]["context"][0]["sentence"])

    def test_physical_facts_still_read_without_fights(self):
        r = read_of(a=no_fights(), physical={"a": {"reach_in": 79.0}, "b": {"reach_in": 72.0}})
        self.assertIn("reach", traits(r["a"], "strengths"))

    def test_the_opponent_is_still_read_and_the_route_says_only_the_fighter_without_fights_is_thin(self):
        r = self.debut_read()
        self.assertEqual(route_keys(r, "a"), ["none"])
        self.assertIn("only 0 fights are on file", r["a"]["paths_to_victory"][0]["sentence"])

    def test_missing_reasons_are_plain_words_not_field_names(self):
        r = self.debut_read()
        for m in r["missing"]:
            self.assertNotIn("as_of", m["detail"])
            self.assertIsNone(re.search(r"\b[a-z]+_[a-z]+\b", m["input"] + " " + m["detail"]), m)

    def test_a_missing_bout_and_missing_price_are_named(self):
        r = read_of(bout=None, odds=None, missing=[
            {"side": None, "figure": "bout", "reason": "no scheduled bout between these fighters in the store"},
            {"side": None, "figure": "odds", "reason": "no odds row for the scheduled bout"}])
        inputs = [m["input"] for m in r["missing"]]
        self.assertIn("The booked bout", inputs)
        self.assertIn("The price", inputs)
        self.assertIn("No booked bout between Alex Archer and Ben Brawler is on file", r["notices"][0])

    def test_a_bout_that_is_not_scheduled_is_noted(self):
        bout = make_sheet()["bout"]
        bout["status"] = "final"
        r = read_of(bout=bout)
        self.assertIn("This bout is listed as final. The read describes the fight going in and does not use how it turned out.",
                      r["notices"])

    def test_missing_figures_are_grouped_by_reason_per_fighter(self):
        missing = [{"side": "b", "fighter_id": "102", "figure": "control_time_share", "reason": "none of the 3 fight(s) before as_of has its own control time and a fight time"},
                   {"side": "b", "fighter_id": "102", "figure": "submission_attempts_per_15", "reason": "none of the 3 fight(s) before as_of has its own control time and a fight time"},
                   {"side": "b", "fighter_id": "102", "figure": "height_in", "reason": "no height on the fighter record"},
                   {"side": "b", "fighter_id": "102", "figure": "sig_strike_share_head", "reason": "not used by the read"}]
        r = read_of(missing=missing)
        details = {m["input"]: m["detail"] for m in r["missing"]}
        self.assertIn("Ben Brawler: control time and submission attempts", details)
        self.assertEqual(details["Ben Brawler: height"], "no height on the fighter record")
        self.assertFalse([k for k in details if "share" in k], "a figure the read never uses is not listed")


# -- the market view ------------------------------------------------------------------------------

class MarketView(unittest.TestCase):
    def test_it_prints_the_markets_margin_free_numbers_and_the_prices_as_fetched(self):
        r = read_of()
        mv = r["market_view"]
        self.assertTrue(mv["available"])
        self.assertEqual(mv["implied"]["a"]["without_margin"], 0.6067)
        self.assertEqual(mv["implied"]["b"]["without_margin"], 0.3933)
        first = mv["sentences"][0]
        self.assertIn("DraftKings' current prices make Alex Archer the 60.7% favourite and Ben Brawler 39.3%", first)
        self.assertIn("with the bookmaker's margin taken out (Alex Archer -170, Ben Brawler +145, fetched 2026-10-03)", first)
        self.assertEqual(mv["favourite"], "a")

    def test_movement_is_a_fact_not_a_signal(self):
        mv = read_of()["market_view"]
        move = [s for s in mv["sentences"] if "moved toward" in s]
        self.assertEqual(len(move), 1)
        self.assertIn("The line has moved toward Alex Archer since it opened", move[0])
        self.assertIn("A move says what the market now thinks and not why.", move[0])
        flat = odds_block(-170, 145)
        flat["moneyline"]["open"] = dict(flat["moneyline"]["current"])
        self.assertIn("The line has barely moved since it opened.", read_of(odds=flat)["market_view"]["sentences"])

    def test_the_rounds_line_and_the_method_split(self):
        method_side = {"ko_tko_dq": 0.1, "submission": 0.05, "decision": 0.35}
        odds = odds_block(method={"open": None, "close": None, "current": {
            "a": {}, "b": {}, "implied": {}, "margin": 0.08, "without_margin": {"a": method_side, "b": dict(method_side)}}})
        sentences = read_of(odds=odds)["market_view"]["sentences"]
        self.assertTrue([s for s in sentences if s.startswith("The rounds line is 4.5")])
        self.assertTrue([s for s in sentences if "put a decision at 70%, a KO or TKO at 20% and a submission at 10%" in s])

    def test_agreement_follows_the_lean_against_the_favourite(self):
        strong_a = {"figures": F(sig_strikes_landed_per_min=7.0, sig_strikes_absorbed_per_min=2.0)}
        agrees = read_of(a=strong_a)["market_view"]                    # a is the -170 favourite
        self.assertEqual((agrees["lean"], agrees["agreement"]), ("a", "agrees"))
        self.assertIn("lean toward Alex Archer too, so this read agrees with the market on direction", " ".join(agrees["sentences"]))
        self.assertIn("It says nothing about whether the price is right.", " ".join(agrees["sentences"]))
        strong_b = {"figures": F(sig_strikes_landed_per_min=7.0, sig_strikes_absorbed_per_min=2.0)}
        against = read_of(b=strong_b)["market_view"]
        self.assertEqual((against["lean"], against["agreement"]), ("b", "disagrees"))
        text = " ".join(against["sentences"])
        self.assertIn("lean toward Ben Brawler, the side the market has as the underdog, so this read disagrees with the price", text)
        self.assertIn("a question to check and not a finding", text)

    def test_when_inputs_are_thin_the_read_says_the_market_is_more_likely_right(self):
        thin = {"sample": {"fights": 2, "minutes": 20.0}}
        for kw in ({}, {"b": {"figures": F(sig_strikes_landed_per_min=7.0, sig_strikes_absorbed_per_min=2.0)}}):
            mv = read_of(a=dict(thin, **kw.get("a", {})), **{k: v for k, v in kw.items() if k != "a"})["market_view"]
            self.assertIn("With this little on file, the price is more likely right than this read.", mv["sentences"])
        both = read_of(a=thin, b={"figures": F(sig_strikes_landed_per_min=7.0, sig_strikes_absorbed_per_min=2.0)})["market_view"]
        self.assertEqual(both["agreement"], "disagrees")
        self.assertIn("the books know something this read cannot see", " ".join(both["sentences"]))
        solid = read_of()["market_view"]
        self.assertNotIn("more likely right", " ".join(solid["sentences"]))

    def test_no_lean_says_the_price_is_the_better_informed_number(self):
        text = " ".join(read_of()["market_view"]["sentences"])
        self.assertIn("do not lean clearly toward either fighter", text)
        self.assertIn("the price is the better informed number", text)

    def test_one_slight_thin_item_is_not_a_lean(self):
        r = read_of(a={"figures": {"sig_strike_accuracy": figure(0.60, fights=2, minutes=20.0)}})
        self.assertEqual(r["market_view"]["lean"], "none")

    def test_the_lean_counts_the_heaviest_item_of_each_family_once(self):
        # three striking items for a are one family: heaviest only. 1.2 (moderate, fair) is exactly the bar.
        a = {"figures": F(sig_strike_accuracy=0.57, sig_strike_defence=0.64, sig_strikes_landed_per_min=5.8, sig_strikes_absorbed_per_min=3.6)}
        items = [i for i in read_of(a=a)["a"]["strengths"] if i["family"] == "striking"]
        self.assertGreaterEqual(len(items), 2)
        mv = read_of(a=a)["market_view"]
        self.assertLess(mv["lean_weight"], sum(i["weight"] for i in items))

    def test_no_price_and_withheld_prices_say_so(self):
        none = read_of(odds=None)["market_view"]
        self.assertFalse(none["available"])
        self.assertIn("No price is on file for this fight, so there is nothing to set this read against.", none["sentences"])
        withheld = read_of(odds={"provider": "DraftKings", "moneyline": None, "rounds_total": None, "method": None,
                                 "note": "prices withheld: the odds row's sides could not be matched to these fighters"})["market_view"]
        self.assertFalse(withheld["available"])
        self.assertIn("could not be matched to the two fighters with confidence", withheld["sentences"][0])
        live = read_of(odds={"provider": None, "moneyline": None, "note": "only in-fight prices exist for this bout; no pre-fight market is shown"})["market_view"]
        self.assertIn("Only prices taken during the fight are on file", live["sentences"][0])
        for mv in (none, withheld, live):
            self.assertEqual(mv["agreement"], "no price")

    def test_a_finished_bouts_close_is_called_the_closing_price(self):
        odds = odds_block()
        odds["is_closing"] = True
        mv = read_of(odds=odds)["market_view"]
        self.assertIn("closing prices", mv["sentences"][0])
        self.assertTrue(mv["is_closing"])
        # a closed market has no age to speak of, whatever the clock says
        later = ur.build_read(make_sheet(odds=odds), now=datetime(2026, 12, 1, tzinfo=timezone.utc))["market_view"]
        self.assertFalse([s for s in later["sentences"] if "hours before this page" in s])

    def test_the_age_of_the_prices_is_said_only_when_the_clock_is_given(self):
        sheet = make_sheet()
        self.assertFalse([s for s in ur.build_read(sheet)["market_view"]["sentences"] if "hours before this page" in s])
        late = ur.build_read(sheet, now=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc))["market_view"]
        self.assertTrue([s for s in late["sentences"] if "fetched 48 hours before this page was built, and prices move" in s])
        recent = ur.build_read(sheet, now=datetime(2026, 10, 3, 13, 0, tzinfo=timezone.utc))["market_view"]
        self.assertFalse([s for s in recent["sentences"] if "hours before this page" in s])

    def test_it_never_claims_the_read_beats_the_price(self):
        for odds in ("default", None):
            text = " ".join(read_of(odds=odds)["market_view"]["sentences"])
            self.assertIn("We have not tested whether figures like these beat UFC prices.", text)
            self.assertIn("not as advice", text)

    def test_the_sides_are_mapped_by_name_not_position(self):
        flipped = make_sheet(a_name="Ben Brawler", b_name="Alex Archer", odds=odds_block(145, -170))
        mv = ur.build_read(flipped)["market_view"]
        self.assertEqual(mv["favourite"], "b")
        self.assertIn("make Alex Archer the 60.7% favourite", mv["sentences"][0])


# -- history --------------------------------------------------------------------------------------

def meeting(result="loss", method="DEC_UNANIMOUS", winner="Ben Brawler", rnd=5, detail=None, date="2026-03-14T22:00Z"):
    return {"bout_id": "9009", "date_utc": date, "opponent_id": "102", "opponent_name": "Ben Brawler",
            "result": result, "method": method, "detail": detail, "round": rnd, "time_s": 300.0,
            "weight_class": "Welterweight", "winner_id": "102" if winner else None, "winner_name": winner}


def line(result, method, date, opponent="Dan Silva"):
    return {"bout_id": "x", "date_utc": date, "opponent_id": "104", "opponent_name": opponent, "result": result,
            "method": method, "detail": None, "round": 2, "time_s": 100.0, "weight_class": "Welterweight"}


class History(unittest.TestCase):
    def test_a_previous_meeting_is_stated_with_winner_method_round_and_date(self):
        h = read_of(previous_meetings=[meeting()])["history"]
        self.assertEqual(h["previous_meetings"][0]["sentence"], "Ben Brawler won by unanimous decision on 2026-03-14, in round 5.")
        self.assertIn("Alex Archer and Ben Brawler have met once in the fights on file.", h["summary"])
        sub = read_of(previous_meetings=[meeting(method="SUB", rnd=2, detail="Guillotine Choke", result="win", winner="Alex Archer")])["history"]
        self.assertEqual(sub["previous_meetings"][0]["sentence"], "Alex Archer won by submission on 2026-03-14, in round 2 (Guillotine Choke).")

    def test_a_draw_and_a_no_contest_are_not_called_wins(self):
        draw = read_of(previous_meetings=[meeting(result="draw", method="DRAW", winner=None)])["history"]
        self.assertEqual(draw["previous_meetings"][0]["sentence"], "Alex Archer and Ben Brawler fought to a draw on 2026-03-14.")
        nc = read_of(previous_meetings=[meeting(result="no_contest", method="NC", winner=None)])["history"]
        self.assertEqual(nc["previous_meetings"][0]["sentence"], "Alex Archer and Ben Brawler had a no contest on 2026-03-14.")

    def test_no_earlier_meeting_is_said_plainly(self):
        h = read_of()["history"]
        self.assertEqual(h["previous_meetings"], [])
        self.assertIn("have not met in the fights on file", h["summary"])

    def test_shared_opponents_list_each_fighters_results_against_them(self):
        shared = {"a_opponents": 4, "b_opponents": 5, "count": 1, "items": [{
            "opponent_id": "104", "opponent_name": "Dan Silva",
            "a": [line("loss", "SUB", "2025-04-26T22:00Z"), line("win", "DEC_UNANIMOUS", "2026-06-13T22:00Z")],
            "b": [line("win", "SUB", "2026-01-24T22:00Z")]}]}
        h = read_of(shared=shared)["history"]
        self.assertEqual(h["shared_opponents"][0]["sentence"],
                         "Both fought Dan Silva. Alex Archer lost to Dan Silva by submission on 2025-04-26 and Alex Archer beat "
                         "Dan Silva by unanimous decision on 2026-06-13; Ben Brawler beat Dan Silva by submission on 2026-01-24.")
        self.assertIn("They have 1 opponent in common.", h["summary"])
        self.assertIn("weak guide", h["caveat"])

    def test_no_overlap_between_two_real_histories_differs_from_no_history(self):
        none_common = read_of(shared={"a_opponents": 4, "b_opponents": 5, "count": 0, "items": []})["history"]
        self.assertIn("Alex Archer has faced 4 opponents on file and Ben Brawler has faced 5, with none in common",
                      none_common["summary"])
        no_history = read_of(shared={"a_opponents": 0, "b_opponents": 5, "count": 0, "items": []})["history"]
        self.assertIn("has no earlier opponents on file, so there is nothing to compare", no_history["summary"])

    def test_only_the_first_five_shared_opponents_are_written_out(self):
        items = [{"opponent_id": str(i), "opponent_name": f"Opp {i}", "a": [line("win", "KO_TKO", "2025-01-01T00:00Z", f"Opp {i}")],
                  "b": [line("loss", "SUB", "2025-02-01T00:00Z", f"Opp {i}")]} for i in range(7)]
        h = read_of(shared={"a_opponents": 7, "b_opponents": 7, "count": 7, "items": items})["history"]
        self.assertEqual(len(h["shared_opponents"]), ur.MAX_SHARED_OPPONENTS)
        self.assertIn("the 5 most recent are shown", h["summary"])


# -- context lines --------------------------------------------------------------------------------

class Context(unittest.TestCase):
    def test_coverage_and_overall_record_lines(self):
        r = read_of()
        keys = [c["key"] for c in r["a"]["context"]]
        self.assertEqual(keys[:2], ["coverage", "overall_record"])
        self.assertIn("Alex Archer has 8 UFC fights on file, the first on 2024-02-03, for a record of 5-3-0.", r["a"]["context"][0]["sentence"])
        self.assertIn("The fighter record, fetched 2026-10-03, shows 12-4-0 overall, 16 professional fights including any outside the UFC.",
                      r["a"]["context"][1]["sentence"])

    def test_an_overall_record_fetched_after_the_fight_is_not_used_and_is_listed_as_not_used(self):
        late = {"career_record_incl_non_ufc": {"wins": 12, "losses": 4, "draws": 0, "fetched_utc": "2026-10-20T12:00:00Z"}}
        r = read_of(a=late)
        self.assertNotIn("overall_record", [c["key"] for c in r["a"]["context"]])
        self.assertIsNone(r["data_depth"]["a"]["overall_fights"])
        entry = [m for m in r["missing"] if m["input"] == "Alex Archer: overall record"][0]
        self.assertEqual(entry["status"], "absent")
        self.assertEqual(entry["detail"], "the fighter record was fetched on 2026-10-20, not before this bout, so it may already "
                                          "include this fight and is not used")
        self.assertFalse([m for m in read_of()["missing"] if "overall record" in m["input"]])

    def test_a_weight_class_move_is_a_fact_with_a_direction(self):
        r = read_of(a={"weight_classes": {"current": "Lightweight"}})
        move = [c for c in r["a"]["context"] if c["key"] == "weight_class"][0]
        self.assertEqual(move["sentence"], "Alex Archer last fought at Lightweight and this bout is at Welterweight, a move up.")
        down = read_of(a={"weight_classes": {"current": "Middleweight"}})
        self.assertIn("a move down", [c for c in down["a"]["context"] if c["key"] == "weight_class"][0]["sentence"])
        unknown = read_of(a={"weight_classes": {"current": "Catchweight"}})
        self.assertEqual([c for c in unknown["a"]["context"] if c["key"] == "weight_class"][0]["sentence"],
                         "Alex Archer last fought at Catchweight and this bout is at Welterweight.")

    def test_the_fight_shape_line_states_how_often_each_fighters_fights_went_to_the_scorecards(self):
        r = read_of(a={"figures": {"distance_rate": figure(0.75, fights=8)}}, b={"figures": {"distance_rate": figure(0.25, fights=8)}})
        line = [c for c in r["context"] if c["key"] == "fight_shape"][0]
        self.assertEqual(line["sentence"],
                         "Alex Archer's fights on file have gone to the scorecards 75% of the time and Ben Brawler's 25% "
                         "(fights with a recorded method: Alex Archer 8, Ben Brawler 8).")
        self.assertNotIn("caveat", line)
        self.assertEqual([e["path"] for e in line["evidence"]],
                         ["features.a.figures.distance_rate.value", "features.b.figures.distance_rate.value",
                          "features.a.figures.distance_rate.fights", "features.b.figures.distance_rate.fights"])
        thin = read_of(a={"figures": {"distance_rate": figure(0.75, fights=4)}}, b={"figures": {"distance_rate": figure(0.25, fights=8)}})
        thin_line = [c for c in thin["context"] if c["key"] == "fight_shape"][0]
        self.assertTrue(thin_line["caveat"].startswith("Thin sample: Alex Archer has fewer than 5 fights"))
        # one fight or two on either side: held back, like every other result share
        held = read_of(a={"figures": {"distance_rate": figure(1.0, fights=2)}})
        self.assertFalse([c for c in held["context"] if c["key"] == "fight_shape"])

    def test_stance_is_named_without_claiming_what_it_changes(self):
        c = read_of()["context"][0]["sentence"]
        self.assertEqual(c, "Alex Archer fights orthodox and Ben Brawler fights southpaw. These figures do not measure what that changes.")
        same = read_of(physical={"b": {"stance": "Orthodox"}, "same_stance": True})["context"][0]["sentence"]
        self.assertIn("Both fighters work from the orthodox stance.", same)


# -- what would change it -------------------------------------------------------------------------

class WhatWouldChangeIt(unittest.TestCase):
    def test_it_always_names_the_booking_and_the_price(self):
        items = read_of()["what_would_change_it"]
        self.assertEqual(items[0]["fact"], "A change of opponent, a withdrawal or a cancelled bout.")
        self.assertEqual(items[-1]["fact"], "A move in the price.")
        self.assertLessEqual(len(items), 3)

    def test_thin_data_adds_the_fighter_with_the_least_on_file(self):
        items = read_of(a={"sample": {"fights": 2, "minutes": 25.0}})["what_would_change_it"]
        facts = [i["fact"] for i in items]
        self.assertIn("More fights on file for Alex Archer.", facts)
        self.assertEqual(len(items), 3)

    def test_no_price_says_a_price_being_posted_would_change_it(self):
        self.assertEqual(read_of(odds=None)["what_would_change_it"][-1]["fact"], "A price being posted.")


# -- sweeps over everything ------------------------------------------------------------------------

BANNED = (
    (r"\bedge(s)?\b", "edge"), (r"\block(s|ed)?\b", "lock"), (r"guarantee", "guarantee"), (r"profit", "profit"),
    (r"\bpicks?\b", "pick"), (r"recommend", "recommend"), (r"win[- ]probabilit", "win probability"),
    (r"\broi\b", "roi"), (r"value bet", "value bet"), (r"\+\s*ev\b", "+EV"), (r"sure thing", "sure thing"),
    (r"free money", "free money"), (r"\bbet(s|ting)?\b", "bet"), (r"\bclv\b", "clv"),
    (r"closing line", "closing line"), (r"\bunits?\b", "units"), (r"\bstake", "stake"), (r"you should", "you should"),
    (r"\b(he|his|him|himself|she|her|hers|herself)\b", "gendered pronoun"),
    (r"\bundefined\b|\bnan\b|\bnull\b|\[object", "a programming value"),
    (r"nothing clears the bar|nothing cleared the bar|no demonstrated edge|we checked the slate", "a retired sentence"),
)
SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def sweep_sheets():
    """A spread of reads: quiet, loud, thin, empty, priced, unpriced, five rounds."""
    five = make_sheet()["bout"]
    five["scheduled_rounds"] = 5
    loud_a = {"figures": F(sig_strikes_landed_per_min=7.0, sig_strikes_absorbed_per_min=2.0, sig_strike_accuracy=0.6,
                           sig_strike_defence=0.66, takedowns_landed_per_15=3.0, control_time_share=0.45,
                           knockdowns_landed_per_15=1.6, submission_attempts_per_15=2.0, average_fight_time_s=1300.0,
                           strength_of_schedule=0.7, win_rate=0.9),
              "streak": {"type": "win", "length": 6}}
    loud_b = {"figures": {"takedown_defence": figure(0.4, num=12, den=20), "knockdowns_suffered_per_15": figure(1.5),
                          "finish_rate": figure(0.1, num=1, den=8), "been_finished_rate": figure(0.6, num=5, den=8),
                          "average_fight_time_s": figure(400.0), "strength_of_schedule": figure(0.4, fights=6),
                          "win_rate": figure(0.4)},
              "streak": {"type": "loss", "length": 4},
              "record_update": {"losses_by_method": {"ko_tko": 3, "submission": 3, "decision": 0, "dq": 0, "other": 0, "unknown": 0}}}
    thin = {"sample": {"fights": 2, "minutes": 20.0}, "figures": {
        "sig_strike_accuracy": figure(0.62, fights=2, minutes=20.0), "control_time_share": figure(0.5, fights=2, minutes=20.0)}}
    return [make_sheet(), make_sheet(loud_a, loud_b, bout=five, physical={"a": {"reach_in": 78.0, "height_in": 74.0, "age_years": 27.0},
                                                                          "b": {"reach_in": 72.0, "height_in": 69.0, "age_years": 38.0}},
                                     layoff={"b_days": 700, "b_last_fight_utc": "2024-11-01T22:00:00Z"},
                                     previous_meetings=[meeting()],
                                     shared={"a_opponents": 4, "b_opponents": 5, "count": 1, "items": [{
                                         "opponent_id": "104", "opponent_name": "Dan Silva", "a": [line("win", "KO_TKO", "2025-04-26T22:00Z")],
                                         "b": [line("loss", "SUB", "2026-01-24T22:00Z")]}]}),
            make_sheet(thin, loud_b, odds=None), make_sheet(no_fights(), thin, bout=None, odds=None)]


class SweepsOverEveryRead(unittest.TestCase):
    def test_every_evidence_path_resolves_and_its_value_is_the_sheets(self):
        checked = 0
        for sheet in sweep_sheets():
            read = ur.build_read(sheet)
            for entry in evidence_entries(read):
                found, value = ur.resolve_path(sheet, entry["path"])
                self.assertTrue(found, f"{entry['path']} does not resolve: {entry}")
                if not entry.get("derived"):
                    self.assertEqual(value, entry["value"], entry["path"])
                checked += 1
        self.assertGreater(checked, 150, "the sweep saw almost no evidence; the walker has probably stopped matching")

    def test_a_derived_entry_is_flagged_and_its_path_resolves(self):
        read = ur.build_read(sweep_sheets()[1])
        derived = [e for e in evidence_entries(read) if e.get("derived")]
        self.assertTrue(derived)
        self.assertTrue(any("net significant strikes per minute" in e["label"] for e in derived))

    def test_no_sentence_names_a_pick_a_lock_a_profit_or_a_probability_of_ours(self):
        seen = 0
        for sheet in sweep_sheets():
            for text in prose(ur.build_read(sheet)):
                seen += 1
                for pattern, label in BANNED:
                    self.assertIsNone(re.search(pattern, text, re.I), f"{label!r} in {text!r}")
                # Python's own spellings, case sensitive: "none in common" is English, None is a leak
                self.assertIsNone(re.search(r"\bNone\b|\bTrue\b|\bFalse\b", text), text)
        self.assertGreater(seen, 200)

    def test_no_dash_no_field_name_no_double_space_and_every_sentence_ends_cleanly(self):
        for sheet in sweep_sheets():
            read = ur.build_read(sheet)
            for text in prose(read):
                self.assertNotIn("—", text)
                self.assertNotIn("–", text)
                self.assertEqual(SNAKE.findall(text), [], text)
                self.assertNotIn("  ", text)
                self.assertNotIn(" ,", text)
                self.assertNotIn("..", text)
            for side in ("a", "b"):
                for kind in ("strengths", "weaknesses", "paths_to_victory"):
                    for it in read[side][kind]:
                        self.assertRegex(it["sentence"], r"[.)]$", it["sentence"])
                        self.assertTrue(it["sentence"][0].isupper(), it["sentence"])

    def test_every_item_carries_what_the_page_prints(self):
        for sheet in sweep_sheets():
            read = ur.build_read(sheet)
            for side in ("a", "b"):
                for kind in ("strengths", "weaknesses"):
                    for it in read[side][kind]:
                        self.assertIn(it["size"], ur.SIZES)
                        self.assertIn(it["sample_level"], ("thin", "fair", "solid"))
                        self.assertEqual(it["thin"], it["sample_level"] == "thin")
                        self.assertEqual(it["down_weighted"], it["thin"])
                        self.assertEqual(it["weight"], round(ur.SIZE_RANK[it["size"]] * ur.SAMPLE_WEIGHT[it["sample_level"]], 2))
                        self.assertTrue(it["evidence"], it["trait"])
                        if it["thin"]:
                            self.assertTrue(it["caveat"], it["trait"])
                        self.assertLessEqual(len(read[side][kind]), ur.MAX_ITEMS)

    def test_lists_are_ordered_by_weight(self):
        for sheet in sweep_sheets():
            read = ur.build_read(sheet)
            for side in ("a", "b"):
                for kind in ("strengths", "weaknesses"):
                    weights = [i["weight"] for i in read[side][kind]]
                    self.assertEqual(weights, sorted(weights, reverse=True))

    def test_the_headline_is_the_heaviest_difference_in_how_the_fight_will_be_fought(self):
        read = ur.build_read(sweep_sheets()[1])
        pool = [i for s in ("a", "b") for i in read[s]["strengths"]] + \
               [i for s in ("a", "b") for i in read[s]["weaknesses"] if i["trait"] in
                ("chin", "finished_often", "been_submitted", "long_layoff", "loss_streak")]
        fought = [i for i in pool if i["family"] not in ur.HEADLINE_LAST_FAMILIES]
        top = max(i["weight"] for i in fought)
        self.assertIn(read["headline_trait"], [i["trait"] for i in fought if i["weight"] == top])
        self.assertIn(read["headline"].split(". ", 1)[1].split(" The sample")[0], [i["sentence"] for i in pool])

    def test_a_record_or_a_run_or_the_opposition_headlines_only_when_nothing_else_clears_the_bar(self):
        # a large gap in results (thin, 0.9) and a slight but fair striking gap (0.6): the striking one headlines
        a = {"figures": {"win_rate": figure(1.0, fights=3), "sig_strikes_landed_per_min": figure(5.6, fights=4, minutes=40.0),
                         "sig_strikes_absorbed_per_min": figure(3.9, fights=4, minutes=40.0)}, "record_update": {"fights": 3, "wins": 3, "losses": 0}}
        b = {"figures": {"win_rate": figure(0.0, fights=3)}, "record_update": {"fights": 3, "wins": 0, "losses": 3}}
        r = read_of(a=a, b=b)
        self.assertEqual(item(r, "a", "strengths", "results")["weight"], 0.9)
        self.assertEqual(item(r, "a", "strengths", "striking_net")["weight"], 0.6)
        self.assertEqual(r["headline_trait"], "striking_net")
        # with nothing else to say, the record does headline
        only = read_of(a={"figures": {"win_rate": figure(1.0, fights=6)}, "record_update": {"fights": 6, "wins": 6, "losses": 0}},
                       b={"figures": {"win_rate": figure(0.0, fights=6)}, "record_update": {"fights": 6, "wins": 0, "losses": 6}})
        self.assertEqual(only["headline_trait"], "results")
        self.assertTrue(only["headline"].startswith("The biggest difference is in results on file."))

    def test_the_word_prediction_appears_only_in_the_labels_own_denial(self):
        for sheet in sweep_sheets():
            for text in prose(ur.build_read(sheet)):
                if re.search(r"predict", text, re.I):
                    self.assertEqual(text, ur.LABEL)

    def test_the_label_is_the_same_everywhere_and_says_what_this_is_not(self):
        for sheet in sweep_sheets():
            read = ur.build_read(sheet)
            self.assertEqual(read["label"], ur.LABEL)
        self.assertIn("not a prediction, not advice", ur.LABEL)

    def test_the_module_never_prints_a_win_probability_of_its_own(self):
        read = ur.build_read(make_sheet())
        keys = {str(p[-1]) for p, _ in walk(read) if p and isinstance(p[-1], str)}
        self.assertFalse([k for k in keys if re.search(r"win_prob|p_win|probability_of|expected_value|edge|pick", k)])


# -- the synthetic world ---------------------------------------------------------------------------

class OverTheSyntheticWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_datasvc_ufc_features import build_store
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = build_store(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def pairs(self):
        ids = ("101", "102", "103", "104", "105")
        return [(a, b) for a in ids for b in ids if a < b]

    def test_every_pair_reads_without_error_and_every_path_resolves(self):
        for a, b in self.pairs():
            sheet = matchup.matchup(self.store, a, b, now=NOW)
            read = ur.build_read(sheet, now=NOW)
            self.assertFalse([m for m in read["missing"] if m["status"] == "error"], (a, b, read["missing"]))
            for entry in evidence_entries(read):
                found, value = ur.resolve_path(sheet, entry["path"])
                self.assertTrue(found, (a, b, entry))
                if not entry.get("derived"):
                    self.assertEqual(value, entry["value"], (a, b, entry["path"]))

    def test_every_pair_passes_the_wording_sweep(self):
        for a, b in self.pairs():
            read = ur.build_read(matchup.matchup(self.store, a, b, now=NOW), now=NOW)
            for text in prose(read):
                self.assertNotIn("—", text)
                self.assertEqual(SNAKE.findall(text), [], text)
                for pattern, label in BANNED:
                    self.assertIsNone(re.search(pattern, text, re.I), f"{a} v {b}: {label!r} in {text!r}")

    def test_the_read_flags_the_same_thin_pairs_the_sheets_differentials_do(self):
        """For a rule built on one figure, the item is thin exactly when the sheet says the pair's sample is."""
        single = {"striking_accuracy": "sig_strike_accuracy", "striking_defence": "sig_strike_defence",
                  "control": "control_time_share"}
        compared = 0
        for a, b in self.pairs():
            sheet = matchup.matchup(self.store, a, b, now=NOW)
            read = ur.build_read(sheet)
            for trait, fig in single.items():
                for it in read["a"]["strengths"] + read["b"]["strengths"]:
                    if it["trait"] == trait:
                        self.assertEqual(it["thin"], sheet["differentials"][fig]["thin_sample"], (a, b, trait))
                        compared += 1
        self.assertGreater(compared, 0)

    def test_the_main_event_reads_from_the_real_sheet(self):
        sheet = matchup.matchup(self.store, "101", "102", now=NOW)
        read = ur.build_read(sheet, now=NOW)
        self.assertEqual(read["a"]["name"], "Alex Archer")
        self.assertEqual(read["history"]["previous_meetings"][0]["sentence"],
                         "Ben Brawler won by unanimous decision on 2026-03-14, in round 5.")
        self.assertEqual(read["market_view"]["implied"]["a"]["without_margin"], 0.6067)
        self.assertIn("takedown_open", traits(read["b"], "strengths"))
        self.assertIn("takedown_open", traits(read["a"], "weaknesses"))
        self.assertIn("deep", [r["route"] for r in read["b"]["paths_to_victory"]] + ["deep"])

    def test_a_fighter_with_no_prior_ufc_fights_does_not_break_a_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tests.test_datasvc_ufc_features import build_store
            store = build_store(Path(tmp), before="2025-02-01")        # 101 and 103 fought once; 102, 104, 105 not at all
            for a, b in (("102", "104"), ("101", "103"), ("104", "105")):
                try:
                    sheet = matchup.matchup(store, a, b, now=NOW)
                except Exception:   # a fighter not in the world: not this test's subject
                    continue
                read = ur.build_read(sheet)
                self.assertTrue(read["headline"])


if __name__ == "__main__":
    unittest.main()
