"""Stage answers through the shape check, the code risk manager and the analyst's own checker.

The point of these tests is that the desk REUSES the analyst's checker: an invented number, a name that is not
in the packet and a path that does not resolve are struck by `src/analyst/critic.py`, and a strike by code (the
cap, the price, the market's number) is NOT a checker rejection and so never earns a new answer.
"""

from __future__ import annotations

import copy
import unittest

from src.hounds.desk import checks, roles, schemas
from tests import _desk_hounds_fixtures as H
from tests import analyst_fixtures as F
from tests import nfl_analyst_fixtures as NF

PACKET = F.build()
STATS = roles.ROLES["analyst_stats"]
HEAD = roles.ROLES["head"]
SHARP = roles.ROLES["persona_sharp"]


def finding(claim, path="markets.moneyline.lean", value="TB", derived=None):
    return {"claim": claim, "evidence": [{"path": path, "value": value}], "derived": derived or []}


class ReportChecks(unittest.TestCase):
    def check(self, **kw):
        return checks.check_stage(PACKET, H.report_answer(PACKET, "analyst_stats", **kw), STATS)

    def test_a_clean_report_is_accepted_and_its_material_is_kept(self):
        result = self.check()
        self.assertEqual(result.report.shape_errors, [])
        self.assertEqual(result.report.struck, 0)
        self.assertEqual(result.summary_status, "ok")
        self.assertEqual(len(result.material["findings"]), 1)
        self.assertIsNotNone(result.material["text"])

    def test_the_critic_strikes_an_invented_number_in_a_finding(self):
        result = self.check(findings=[finding("The home side wins 61 percent of the time."),
                                      finding("The market names a favourite in this game.")])
        self.assertEqual(result.report.struck, 1)
        problems = result.report.calls[0].problems
        self.assertTrue(any("61" in p and "not a number in the packet" in p for p in problems), problems)
        # the struck claim is not in the material a later stage may be shown
        self.assertEqual([f["claim"] for f in result.material["findings"]],
                         ["The market names a favourite in this game."])
        self.assertNotIn("61", repr(result.material))

    def test_the_critic_withholds_a_text_with_an_invented_number(self):
        text = H.prose(80) + " The starter has a 99 strikeout rate."
        result = self.check(text=text)
        self.assertEqual(result.summary_status, "withheld")
        self.assertIsNone(result.material["text"])
        self.assertTrue(result.material["text_withheld"])
        self.assertTrue(any("99" in p for p in result.report.summary_problems))

    def test_a_packet_number_in_the_text_is_fine(self):
        result = self.check(text=H.prose(80) + " The home starter has an ERA of 2.8761.")
        self.assertEqual(result.summary_status, "ok")

    def test_a_declared_calculation_licenses_its_number_and_a_wrong_one_does_not(self):
        good = {"value": 0.5287, "unit": "runs", "op": "difference",
                "inputs": ["sections.starters.values.away_sp_era", "sections.starters.values.home_sp_era"],
                "note": "away starter ERA minus home starter ERA"}
        ok = self.check(text=H.prose(80) + " The ERA gap is 0.5293.", text_derived=[
            dict(good, value=0.5293)])
        self.assertEqual(ok.summary_status, "ok", ok.report.summary_problems)
        bad = self.check(text=H.prose(80) + " The ERA gap is 0.9.", text_derived=[dict(good, value=0.9)])
        self.assertEqual(bad.summary_status, "withheld")

    def test_a_name_not_in_the_packet_is_struck(self):
        result = self.check(findings=[finding("Aaron Judge has owned this pitcher.")])
        self.assertEqual(result.report.struck, 1)
        self.assertTrue(any("aaron judge" in p.lower() for p in result.report.calls[0].problems))

    def test_a_wrong_evidence_value_is_struck(self):
        result = self.check(findings=[finding("The market names a favourite.", value="NYY")])
        self.assertEqual(result.report.struck, 1)

    def test_the_word_packet_and_a_banned_word_are_struck(self):
        a = self.check(findings=[finding("The packet makes the home side the favourite.")])
        self.assertEqual(a.report.struck, 1)
        b = self.check(findings=[finding("This is a lock for the home side.")])
        self.assertEqual(b.report.struck, 1)

    def test_a_path_that_does_not_resolve_is_struck(self):
        result = self.check(findings=[finding("A claim.", path="markets.moneyline.nope", value=1)])
        self.assertEqual(result.report.struck, 1)

    def test_shape_errors_reject_the_whole_answer(self):
        short = checks.check_stage(PACKET, H.report_answer(PACKET, "analyst_stats", text="too short"), STATS)
        self.assertTrue(any("words" in e for e in short.report.shape_errors))
        nofind = checks.check_stage(PACKET, H.report_answer(PACKET, "analyst_stats", findings=[]), STATS)
        self.assertTrue(any("findings" in e for e in nofind.report.shape_errors))
        bad_focus = checks.check_stage(PACKET, H.report_answer(
            PACKET, "analyst_stats", focus=[{"slot_id": "moneyline", "selection": "Nobody"}]), STATS)
        self.assertTrue(any("Nobody" in e for e in bad_focus.report.shape_errors))
        self.assertEqual(checks.check_stage(PACKET, ["not", "an", "object"], STATS).report.shape_errors,
                         ["the answer is not a JSON object"])

    def test_a_report_is_rejected_by_the_pilots_own_definition(self):
        from src.analyst import pilot
        clean = self.check()
        struck = self.check(findings=[finding("It is 77 to 1.")])
        self.assertFalse(pilot._is_rejected(clean.report))
        self.assertTrue(pilot._is_rejected(struck.report))


class DecisionChecks(unittest.TestCase):
    def take(self, slot="moneyline", selection="NYY", prob=None, **kw):
        prob = H.just_above_fair(PACKET, slot, selection) if prob is None else prob
        return H.take(PACKET, slot, selection, prob, **kw)

    def check(self, takes, role=HEAD, **kw):
        return checks.check_stage(PACKET, H.decision_answer(PACKET, role.stage, takes, **kw), role)

    def test_a_clean_take_is_kept(self):
        result = self.check([self.take()])
        self.assertEqual(result.report.struck, 0)
        self.assertEqual([t.slot_id for t in result.risk_kept], ["moneyline"])
        self.assertEqual(result.summary_status, "ok")

    def test_no_takes_passes_the_whole_game_and_is_clean(self):
        result = self.check([])
        self.assertEqual(result.report.shape_errors, [])
        self.assertEqual(result.report.calls, [])
        self.assertEqual(result.summary_status, "ok")
        self.assertEqual(result.risk_kept, [])

    def test_the_critic_strikes_a_take_with_an_invented_number_and_that_is_a_rejection(self):
        bad = self.take(reasons=[{"claim": "The road side has won 83 percent of such games.",
                                  "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}],
                                  "derived": []}])
        result = self.check([bad])
        self.assertEqual(result.report.struck, 1)
        self.assertEqual(len(result.critic_struck), 1)
        self.assertTrue(any("83" in p for p in result.critic_struck[0]["problems"]))
        from src.analyst import pilot
        self.assertTrue(pilot._is_rejected(result.report))

    def test_a_take_at_minus_200_is_struck_by_code_and_is_not_a_rejection(self):
        # prop_02 Over 0.5: best -220
        over = self.take("prop_02", "Over 0.5", prob=0.8)
        result = self.check([over])
        self.assertEqual(result.risk_kept, [])
        self.assertEqual([s.rule for s in result.risk_struck], ["R2"])
        from src.analyst import pilot
        self.assertFalse(pilot._is_rejected(result.report))
        self.assertEqual(result.report.calls, [])

    def test_a_probability_that_does_not_beat_the_market_is_a_strike_not_a_rejection(self):
        result = self.check([self.take(prob=0.40)])
        self.assertEqual([s.rule for s in result.risk_struck], ["R3"])
        from src.analyst import pilot
        self.assertFalse(pilot._is_rejected(result.report))

    def test_the_summary_may_quote_a_probability_code_struck(self):
        # 0.4 is the model's own number; it is not a packet number, but a code strike must not turn into
        # a checker rejection through the summary
        result = self.check([self.take(prob=0.4)], summary=H.prose(110) + " My own number was 0.4 here.")
        self.assertEqual(result.summary_status, "ok", result.report.summary_problems)

    def test_a_take_on_a_second_side_of_the_lean_is_take_other_side(self):
        result = self.check([self.take("moneyline", "NYY")])
        self.assertEqual(result.report.calls[0].verdict, "TAKE_OTHER_SIDE")
        lean = self.check([self.take("total", "Under 7")])
        self.assertEqual(lean.report.calls[0].verdict, "TAKE")

    def test_shape_errors(self):
        for bad, needle in (
                (dict(self.take(), verdict="PASS"), "TAKE"),
                (dict(self.take(), slot_id="nope"), "not a slot"),
                (dict(self.take(), probability=1.5), "probability"),
                (dict(self.take(), price=1.5), "price"),
        ):
            result = self.check([bad])
            self.assertTrue(any(needle in e for e in result.report.shape_errors),
                            (needle, result.report.shape_errors))
        no_case = self.take()
        no_case["case_against"] = None
        self.assertTrue(any("case_against" in e for e in self.check([no_case]).report.shape_errors))
        dup = self.check([self.take(), self.take()])
        self.assertTrue(any("more than one" in e for e in dup.report.shape_errors))

    def test_a_persona_rule_is_applied_from_the_stage(self):
        # the Square never takes the underdog NYY
        result = self.check([self.take("moneyline", "NYY")], role=roles.ROLES["persona_square"])
        self.assertEqual([s.rule for s in result.risk_struck], ["R4"])
        # the Fader does
        result = self.check([self.take("moneyline", "NYY")], role=roles.ROLES["persona_fader"])
        self.assertEqual([t.slot_id for t in result.risk_kept], ["moneyline"])


class FootballChecks(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = NF.make_store(self._tmp.name)
        self.packet = NF.build(self.store)

    def test_the_football_number_line_rule_is_used(self):
        spread = self.packet["markets"]["spread"]
        sel = spread["options"][1]["selection"]
        prob = H.just_above_fair(self.packet, "spread", sel)
        good = H.take(self.packet, "spread", sel, prob)
        self.assertEqual(checks.check_stage(
            self.packet, H.decision_answer(self.packet, "head", [good]), HEAD).report.struck, 0)
        wrong = copy.deepcopy(good)
        wrong["reasons"] = [{"claim": "BUF +9 is a number the books do not quote.",
                             "evidence": [{"path": "markets.spread.lean", "value": spread["lean"]}],
                             "derived": []}]
        result = checks.check_stage(self.packet, H.decision_answer(self.packet, "head", [wrong]), HEAD)
        self.assertEqual(result.report.struck, 1, result.report.calls)

    def test_a_football_report_uses_the_football_name_vocabulary(self):
        ok = checks.check_stage(self.packet, H.report_answer(self.packet, "analyst_stats"), STATS)
        self.assertEqual(ok.report.struck, 0)
        bad = checks.check_stage(self.packet, H.report_answer(
            self.packet, "analyst_stats", findings=[finding("Patrick Mahomes is hurt.", "markets.moneyline.lean",
                                                           self.packet["markets"]["moneyline"]["lean"])]), STATS)
        self.assertEqual(bad.report.struck, 1)

    def test_the_cap_applies_to_the_football_favourite(self):
        # KC is -205 / -210 / -215 in the football fixture: best -205
        favourite = self.packet["markets"]["moneyline"]["lean"]
        take = H.take(self.packet, "moneyline", favourite, 0.9)
        result = checks.check_stage(self.packet, H.decision_answer(self.packet, "head", [take]), HEAD)
        self.assertEqual([s.rule for s in result.risk_struck], ["R2"])


class ShapeOfTheSchemas(unittest.TestCase):
    def test_the_reason_is_the_analysts_reason_with_its_derived_list(self):
        self.assertEqual(schemas.REASON_SCHEMA["required"], ["claim", "evidence", "derived"])

    def test_the_decision_schema_lists_only_takes(self):
        item = schemas.DECISION_SCHEMA["properties"]["decisions"]["items"]
        self.assertEqual(item["properties"]["verdict"]["enum"], ["TAKE"])
        self.assertEqual(set(item["required"]), set(schemas.TAKE_KEYS))


if __name__ == "__main__":
    unittest.main()
