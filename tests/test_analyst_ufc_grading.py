"""Grading UFC analyst calls from the data layer's bout results: every result kind.

Pure functions over a call and a bout record, so every case here is a dict. The moneyline is
graded by the winner, a method by the winner AND how he won, a rounds total by the elapsed
fight time against the line, with a bout that ends exactly on the half-round line a PUSH.
A draw, a no contest and a canceled bout are VOID; a bout that is not final is UNRESOLVED.
"""

from __future__ import annotations

import tempfile
import unittest

from src.analyst import ufc_grading as G
from tests import ufc_analyst_fixtures as F

A_ID, B_ID = "101", "102"


def bout(**kw) -> dict:
    base = {"bout_id": "9101", "status": "final", "fighter_a_id": A_ID, "fighter_b_id": B_ID,
            "winner_id": A_ID, "result_method": "KO_TKO", "result_method_raw": "kotko",
            "end_round": 2, "end_time_s": 77.0, "fight_time_s": 377.0, "scheduled_rounds": 3}
    base.update(kw)
    return base


def moneyline(fighter=A_ID, price=-170, verdict="TAKE"):
    return {"slot_id": "moneyline", "selection": "x", "verdict": verdict, "price": price, "book": "DraftKings",
            "grading": {"family": "moneyline", "side": "a", "line": None, "fighter_id": fighter,
                        "fighter_side": "a", "method": None, "reference_price": price}}


def method(fighter, which, price=300, verdict="TAKE"):
    return {"slot_id": f"method_{which}", "selection": "x", "verdict": verdict, "price": price,
            "book": "DraftKings",
            "grading": {"family": "method", "side": "a", "line": None, "fighter_id": fighter,
                        "fighter_side": "a", "method": which, "reference_price": price}}


def total(side, line, price=-110, verdict="TAKE"):
    return {"slot_id": "rounds_total", "selection": "x", "verdict": verdict, "price": price,
            "book": "DraftKings",
            "grading": {"family": "rounds_total", "side": side, "line": line, "fighter_id": None,
                        "fighter_side": None, "method": None, "reference_price": price}}


def result(call, **bout_kw):
    return G.grade_call(call, bout(**bout_kw))


class TheMoneyline(unittest.TestCase):
    def test_the_backed_fighter_winning_is_a_win_at_the_published_price(self):
        r = result(moneyline(A_ID, 145))
        self.assertEqual((r["result"], r["profit_units"]), ("WIN", 1.45))
        r = result(moneyline(A_ID, -170))
        self.assertEqual((r["result"], r["profit_units"]), ("WIN", 0.5882))

    def test_the_other_fighter_winning_is_a_loss_of_one_unit(self):
        r = result(moneyline(B_ID, 145))
        self.assertEqual((r["result"], r["profit_units"]), ("LOSS", -1.0))

    def test_every_way_of_winning_wins_the_moneyline(self):
        for method_name in ("KO_TKO", "SUB", "DEC_UNANIMOUS", "DEC_SPLIT", "DEC_MAJORITY", "DECISION",
                            "DQ", "OTHER"):
            self.assertEqual(result(moneyline(A_ID), result_method=method_name)["result"], "WIN", method_name)

    def test_a_draw_is_void_not_a_loss(self):
        r = result(moneyline(A_ID), winner_id=None, result_method="DRAW")
        self.assertEqual((r["result"], r["profit_units"], r["reason"]), ("VOID", 0.0, "the bout was a draw"))

    def test_a_no_contest_is_void(self):
        r = result(moneyline(A_ID), winner_id=None, result_method="NC")
        self.assertEqual((r["result"], r["reason"]), ("VOID", "the bout was a no contest"))

    def test_a_no_contest_with_a_winner_field_is_still_void(self):
        """The data layer records winners on no contests in some bouts (2026-02-21): not a result."""
        self.assertEqual(result(moneyline(A_ID), winner_id=A_ID, result_method="NC")["result"], "VOID")

    def test_a_canceled_bout_is_void(self):
        r = G.grade_call(moneyline(A_ID), bout(status="canceled", winner_id=None, result_method=None))
        self.assertEqual((r["result"], r["reason"]), ("VOID", "the bout was canceled"))

    def test_a_bout_not_final_is_unresolved_never_a_loss(self):
        for status in ("scheduled", "in_progress", "postponed", "unknown"):
            r = G.grade_call(moneyline(A_ID), bout(status=status, winner_id=None, result_method=None))
            self.assertEqual((r["result"], r["profit_units"]), ("UNRESOLVED", 0.0), status)
            self.assertIn("not final", r["reason"])

    def test_a_bout_missing_from_the_store_is_unresolved(self):
        self.assertEqual(G.grade_call(moneyline(A_ID), None)["result"], "UNRESOLVED")

    def test_a_final_bout_with_no_winner_is_unresolved(self):
        r = result(moneyline(A_ID), winner_id=None, result_method="KO_TKO")
        self.assertEqual((r["result"], r["reason"]), ("UNRESOLVED", "the bout is final but no winner is recorded"))

    def test_a_winner_who_is_not_in_the_bout_is_unresolved_not_graded(self):
        r = result(moneyline(A_ID), winner_id="999")
        self.assertEqual(r["result"], "UNRESOLVED")
        self.assertIn("neither", r["reason"])

    def test_a_call_with_no_fighter_is_void(self):
        self.assertEqual(result(moneyline(fighter=None))["result"], "VOID")

    def test_an_unusable_price_is_void_not_a_crash(self):
        self.assertEqual(result(moneyline(A_ID, 50))["result"], "VOID")


class TheMethod(unittest.TestCase):
    def grade(self, fighter, which, **bout_kw):
        return result(method(fighter, which), **bout_kw)["result"]

    def test_the_priced_fighter_winning_the_priced_way_is_a_win(self):
        self.assertEqual(self.grade(A_ID, "ko_tko_dq", result_method="KO_TKO"), "WIN")
        self.assertEqual(self.grade(A_ID, "submission", result_method="SUB"), "WIN")
        for decision in ("DEC_UNANIMOUS", "DEC_SPLIT", "DEC_MAJORITY", "DECISION"):
            self.assertEqual(self.grade(A_ID, "decision", result_method=decision), "WIN", decision)

    def test_a_disqualification_win_is_a_ko_tko_dq_win(self):
        self.assertEqual(self.grade(A_ID, "ko_tko_dq", result_method="DQ"), "WIN")
        self.assertEqual(self.grade(A_ID, "decision", result_method="DQ"), "LOSS")

    def test_the_right_fighter_the_wrong_way_is_a_loss(self):
        self.assertEqual(self.grade(A_ID, "submission", result_method="KO_TKO"), "LOSS")
        self.assertEqual(self.grade(A_ID, "ko_tko_dq", result_method="DEC_UNANIMOUS"), "LOSS")
        self.assertEqual(self.grade(A_ID, "decision", result_method="SUB"), "LOSS")

    def test_the_wrong_fighter_the_right_way_is_a_loss(self):
        self.assertEqual(self.grade(B_ID, "ko_tko_dq", result_method="KO_TKO"), "LOSS")
        self.assertEqual(self.grade(A_ID, "ko_tko_dq", winner_id=B_ID, result_method="KO_TKO"), "LOSS")

    def test_a_win_pays_the_published_price(self):
        r = result(method(A_ID, "ko_tko_dq", price=280), result_method="KO_TKO")
        self.assertEqual((r["result"], r["profit_units"]), ("WIN", 2.8))

    def test_a_doctors_stoppage_is_a_tko_and_any_other_unmapped_result_is_void(self):
        doctor = dict(result_method="OTHER", result_method_raw="tko---doctors-stoppage")
        self.assertEqual(self.grade(A_ID, "ko_tko_dq", **doctor), "WIN")
        self.assertEqual(self.grade(A_ID, "decision", **doctor), "LOSS")
        mystery = dict(result_method="OTHER", result_method_raw="technical-decision---unanimous")
        r = result(method(A_ID, "decision"), **mystery)
        self.assertEqual(r["result"], "VOID")
        self.assertIn("cannot be matched", r["reason"])

    def test_a_final_bout_with_a_winner_and_no_method_is_unresolved(self):
        r = result(method(A_ID, "ko_tko_dq"), result_method=None)
        self.assertEqual((r["result"], r["reason"]), ("UNRESOLVED", "no result method is recorded"))

    def test_a_draw_or_no_contest_is_void(self):
        self.assertEqual(self.grade(A_ID, "decision", winner_id=None, result_method="DRAW"), "VOID")
        self.assertEqual(self.grade(A_ID, "ko_tko_dq", winner_id=None, result_method="NC"), "VOID")

    def test_a_not_final_bout_is_unresolved(self):
        self.assertEqual(self.grade(A_ID, "decision", status="in_progress", winner_id=None,
                                    result_method=None), "UNRESOLVED")

    def test_a_call_with_no_method_is_void(self):
        self.assertEqual(self.grade(A_ID, None), "VOID")


class TheRoundsTotal(unittest.TestCase):
    def grade(self, side, line, **bout_kw):
        return result(total(side, line), **bout_kw)

    def test_a_fight_that_went_the_distance_is_over_every_line_below_its_rounds(self):
        full = dict(end_round=3, end_time_s=300.0, result_method="DEC_UNANIMOUS", scheduled_rounds=3)
        self.assertEqual(self.grade("over", 2.5, **full)["result"], "WIN")
        self.assertEqual(self.grade("under", 2.5, **full)["result"], "LOSS")
        self.assertEqual(self.grade("over", 1.5, **full)["result"], "WIN")
        five = dict(end_round=5, end_time_s=300.0, result_method="DEC_UNANIMOUS", scheduled_rounds=5)
        self.assertEqual(self.grade("over", 4.5, **five)["result"], "WIN")
        self.assertEqual(self.grade("under", 4.5, **five)["result"], "LOSS")

    def test_a_first_round_finish_is_under(self):
        quick = dict(end_round=1, end_time_s=120.0, result_method="KO_TKO")
        self.assertEqual(self.grade("under", 1.5, **quick)["result"], "WIN")
        self.assertEqual(self.grade("over", 1.5, **quick)["result"], "LOSS")

    def test_a_winning_total_pays_the_published_price(self):
        r = result(total("under", 1.5, price=130), end_round=1, end_time_s=120.0)
        self.assertEqual((r["result"], r["profit_units"]), ("WIN", 1.3))
        r = result(total("over", 1.5, price=-150), end_round=1, end_time_s=120.0)
        self.assertEqual((r["result"], r["profit_units"]), ("LOSS", -1.0))

    def test_a_finish_before_and_after_the_middle_of_the_round_picks_a_side(self):
        before = dict(end_round=3, end_time_s=149.9, result_method="KO_TKO")
        after = dict(end_round=3, end_time_s=150.1, result_method="KO_TKO")
        self.assertEqual(self.grade("under", 2.5, **before)["result"], "WIN")
        self.assertEqual(self.grade("over", 2.5, **before)["result"], "LOSS")
        self.assertEqual(self.grade("over", 2.5, **after)["result"], "WIN")
        self.assertEqual(self.grade("under", 2.5, **after)["result"], "LOSS")

    def test_a_fight_ending_exactly_on_the_half_round_line_is_a_push_for_either_side(self):
        """2:30 of round 3 against 2.5. The usual rule, stated in src/analyst/ufc_grading.py."""
        exact = dict(end_round=3, end_time_s=150.0, result_method="KO_TKO")
        for side in ("over", "under"):
            r = self.grade(side, 2.5, **exact)
            self.assertEqual((r["result"], r["profit_units"]), ("PUSH", 0.0), side)
            self.assertIn("exactly on the line", r["reason"])

    def test_the_boundary_holds_for_every_round_of_a_five_round_fight(self):
        for rnd in range(1, 6):
            line = rnd - 0.5
            exact = dict(end_round=rnd, end_time_s=150.0, result_method="KO_TKO", scheduled_rounds=5)
            self.assertEqual(self.grade("over", line, **exact)["result"], "PUSH", line)
            # the same clock against the NEXT half-round line is not a push
            other = self.grade("under", line + 1, **exact)
            self.assertEqual(other["result"], "WIN", line + 1)

    def test_a_stoppage_between_rounds_is_the_whole_rounds_fought(self):
        for end in (dict(end_round=2, end_time_s=300.0), dict(end_round=3, end_time_s=0.0)):
            r = self.grade("under", 2.5, result_method="OTHER", **end)
            self.assertEqual(r["result"], "WIN", end)

    def test_a_disqualification_is_graded_on_the_time_it_happened(self):
        r = self.grade("under", 1.5, result_method="DQ", end_round=1, end_time_s=139.0)
        self.assertEqual(r["result"], "WIN")

    def test_a_draw_or_no_contest_is_void_even_though_it_has_a_time(self):
        self.assertEqual(self.grade("over", 2.5, winner_id=None, result_method="DRAW",
                                    end_round=3, end_time_s=300.0)["result"], "VOID")
        self.assertEqual(self.grade("under", 1.5, winner_id=None, result_method="NC",
                                    end_round=1, end_time_s=299.0)["result"], "VOID")

    def test_a_missing_or_impossible_time_is_unresolved_not_graded(self):
        for edit in (dict(end_round=None), dict(end_time_s=None), dict(end_round=0), dict(end_round=1.5),
                     dict(end_time_s=301.0), dict(end_time_s=-1.0), dict(end_round=True),
                     dict(end_time_s=float("nan"))):
            r = self.grade("over", 1.5, **edit)
            self.assertEqual(r["result"], "UNRESOLVED", edit)

    def test_a_call_with_no_line_or_side_is_void(self):
        self.assertEqual(self.grade("over", None)["result"], "VOID")
        self.assertEqual(self.grade("sideways", 2.5)["result"], "VOID")

    def test_seconds_are_compared_not_floats_of_rounds(self):
        # 4.5 x 300 = 1350 exactly; (5 - 1) x 300 + 150 = 1350 exactly
        self.assertEqual(G.elapsed_seconds(bout(end_round=5, end_time_s=150.0)), 1350.0)
        r = self.grade("over", 4.5, end_round=5, end_time_s=150.0)
        self.assertEqual(r["result"], "PUSH")


class APassIsNotABet(unittest.TestCase):
    def test_a_pass_reports_what_the_passed_side_would_have_done(self):
        r = result(moneyline(A_ID, -170, verdict="PASS"))
        self.assertEqual((r["result"], r["profit_units"]), ("PASS", None))
        self.assertEqual(r["would_have"], {"result": "WIN", "price": -170})
        r = result(moneyline(B_ID, 145, verdict="PASS"))
        self.assertEqual(r["would_have"], {"result": "LOSS", "price": 145})

    def test_a_pass_on_an_unfought_bout_has_no_would_have(self):
        r = G.grade_call(moneyline(A_ID, verdict="PASS"), bout(status="scheduled", winner_id=None,
                                                               result_method=None))
        self.assertIsNone(r["would_have"])

    def test_a_pass_without_a_price_falls_back_to_the_reference_price(self):
        call = moneyline(A_ID, price=None, verdict="PASS")
        call["grading"]["reference_price"] = -150
        self.assertEqual(G.grade_call(call, bout())["would_have"], {"result": "WIN", "price": -150})

    def test_a_pass_on_a_push_would_have_pushed(self):
        r = result(total("over", 2.5, verdict="PASS"), end_round=3, end_time_s=150.0)
        self.assertEqual(r["would_have"]["result"], "PUSH")


class TheBout(unittest.TestCase):
    def published(self, *calls):
        return {"calls": list(calls)}

    def test_a_bout_is_complete_when_every_bet_has_a_settled_result(self):
        pub = self.published(moneyline(A_ID), total("over", 1.5), method(A_ID, "ko_tko_dq", verdict="PASS"))
        body = G.grade_bout(pub, bout())
        self.assertTrue(body["complete"])
        self.assertEqual([c["result"] for c in body["calls"]], ["WIN", "LOSS", "PASS"])
        self.assertEqual(body["final"]["outcome"], "decided")
        self.assertEqual((body["final"]["winner_id"], body["final"]["method"], body["final"]["end_round"]),
                         (A_ID, "KO_TKO", 2))

    def test_a_bout_with_an_unresolved_bet_is_not_complete(self):
        body = G.grade_bout(self.published(moneyline(A_ID), total("over", 1.5)), bout(end_time_s=None))
        self.assertFalse(body["complete"])

    def test_an_all_pass_bout_is_complete_once_it_has_a_result(self):
        pub = self.published(moneyline(A_ID, verdict="PASS"))
        self.assertTrue(G.grade_bout(pub, bout())["complete"])
        self.assertFalse(G.grade_bout(pub, bout(status="scheduled", winner_id=None, result_method=None))["complete"])

    def test_a_canceled_bout_is_complete_with_every_bet_void(self):
        body = G.grade_bout(self.published(moneyline(A_ID)), bout(status="canceled", winner_id=None,
                                                                  result_method=None))
        self.assertTrue(body["complete"])
        self.assertEqual((body["calls"][0]["result"], body["final"]), ("VOID", {"outcome": "canceled"}))

    def test_final_blocks_for_a_draw_and_a_no_contest(self):
        self.assertEqual(G.final_block(bout(winner_id=None, result_method="DRAW"))["outcome"], "draw")
        self.assertEqual(G.final_block(bout(winner_id=None, result_method="NC"))["outcome"], "no_contest")
        self.assertIsNone(G.final_block(bout(status="scheduled")))
        self.assertIsNone(G.final_block(None))


class TheSpecFrozenAtPublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.packet = F.packet(F.make_store(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def spec(self, slot_id, selection=None):
        market = self.packet["markets"][slot_id]
        return G.spec_for(market, selection or market["options"][0]["selection"], self.packet["bout"])

    def test_a_moneyline_spec_names_the_fighter_it_backs(self):
        lean = self.spec("moneyline")
        self.assertEqual((lean["family"], lean["fighter_id"], lean["fighter_name"], lean["fighter_side"]),
                         ("moneyline", "101", F.A, "a"))
        other = self.spec("moneyline", F.B)
        self.assertEqual((other["fighter_id"], other["fighter_name"], other["reference_price"]),
                         ("102", F.B, 145))

    def test_a_method_spec_names_the_fighter_and_the_method(self):
        s = self.spec("method_b_sub")
        self.assertEqual((s["family"], s["fighter_id"], s["method"], s["reference_price"]),
                         ("method", "102", "submission", 850))

    def test_a_rounds_total_spec_has_its_side_and_line(self):
        s = self.spec("rounds_total", "Under 4.5")
        self.assertEqual((s["family"], s["side"], s["line"], s["fighter_id"]), ("rounds_total", "under", 4.5, None))

    def test_a_spec_grades_without_the_packet(self):
        s = self.spec("method_a_ko")
        call = {"slot_id": "method_a_ko", "selection": "x", "verdict": "TAKE", "price": 280, "book": "DraftKings",
                "grading": s}
        self.assertEqual(G.grade_call(call, bout())["result"], "WIN")


class TheResultInWords(unittest.TestCase):
    fighters = {"a": {"id": A_ID, "name": F.A}, "b": {"id": B_ID, "name": F.B}}

    def text(self, **kw):
        return G.result_text(G.final_block(bout(**kw)), self.fighters)

    def test_a_finish_names_the_winner_the_method_and_the_round(self):
        self.assertEqual(self.text(), "Alex Archer won by KO/TKO in round 2.")
        self.assertEqual(self.text(winner_id=B_ID, result_method="SUB", end_round=1),
                         "Ben Brawler won by submission in round 1.")

    def test_a_decision_has_no_round(self):
        self.assertEqual(self.text(result_method="DEC_SPLIT", end_round=3),
                         "Alex Archer won by split decision.")

    def test_a_doctors_stoppage_and_a_disqualification(self):
        self.assertEqual(self.text(result_method="OTHER", result_method_raw="tko---doctors-stoppage", end_round=3),
                         "Alex Archer won by doctor's stoppage in round 3.")
        self.assertEqual(self.text(result_method="DQ", end_round=1),
                         "Alex Archer won by disqualification in round 1.")

    def test_a_draw_a_no_contest_and_a_canceled_bout(self):
        self.assertEqual(self.text(winner_id=None, result_method="DRAW"), "The bout was a draw.")
        self.assertEqual(self.text(winner_id=None, result_method="NC"), "The bout was a no contest.")
        self.assertEqual(G.result_text({"outcome": "canceled"}, self.fighters), "The bout was canceled.")

    def test_nothing_until_there_is_a_result(self):
        self.assertIsNone(G.result_text(None, self.fighters))


if __name__ == "__main__":
    unittest.main()
