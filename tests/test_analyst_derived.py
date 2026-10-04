"""Declared derivations (prompt v3): a calculated number in prose is allowed only when the item declares
the calculation and the checker recomputes it from packet values.

THE STORY (2026-10-03, the first real brief): the checker struck a call that said "11 days" because the
model had computed the 11 itself. That was right and stays right. The owner's ruling of 2026-10-04 lets a
calculated fact through "when deterministic code verifies their source inputs, calculation, units and
time convention", with the provenance kept beside the report, and without weakening the checker. These
tests pin both halves: every op is right when right and strikes when wrong, and every rejection that
existed before still rejects.

The synthetic game has no starter rest date, so the tests add one to the frozen packet dict
(`away_sp_last_start`, 2026-09-22, 11 calendar days before the 2026-10-03 game). The shared fixture itself
is untouched: its packet hash is pinned elsewhere.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import critic as C
from src.analyst import ledger
from src.analyst import ufc_analyst as U
from tests import analyst_fixtures as F
from tests import ufc_analyst_fixtures as UF

LAST_START = "sections.starters.values.away_sp_last_start"
ERA_AWAY = "sections.starters.values.away_sp_era"
ERA_HOME = "sections.starters.values.home_sp_era"
FIP_AWAY = "sections.starters.values.away_sp_fip"
FIP_HOME = "sections.starters.values.home_sp_fip"
ML_PRICE = "markets.moneyline.options[0].best.price"
ML_QUOTES = "markets.moneyline.options[0].quotes"

# The UFC side of the world, unchanged by this work: pinned so a drift in either is a test failure.
UFC_SCHEMA_SHA256 = "c7e2e9c7e02652a7a5bbb848f33d7d8302396e1ce1b7ca270dd47493491ab211"
UFC_PROMPT_HASH = "0c924190a80f5c579941ce46d8fee834056b9ec82b7ba207e51ca923c3d28c4a"


def packet(**extra) -> dict:
    p = F.build()
    values = p["sections"]["starters"]["values"]
    values["away_sp_last_start"] = "2026-09-22"
    values["away_sp_zero"] = 0
    values["away_sp_label"] = "Gerrit Cole"
    values.update(extra)
    return p


def d(op, value, unit, inputs, note="worked out from the data"):
    return {"op": op, "value": value, "unit": unit, "inputs": list(inputs), "note": note}


DAYS = d("days_between", 11, "days", [LAST_START, "game.date"], "days since the road starter's last start")
ERA_GAP = d("difference", 0.53, "points", [ERA_AWAY, ERA_HOME], "road ERA minus home ERA")

REST_CLAIM = "The road starter pitched 11 days before this game, so rest is not the question."


def run(derived=None, claim=REST_CLAIM, *, where="reasons", p=None, extra_reason_claim=None):
    """Verify the shared good answer with the moneyline's second reason (or its case against) replaced
    by `claim` carrying `derived`."""
    p = p or packet()
    out = F.good_output(p)
    call = out["calls"][0]
    target = call["reasons"][1] if where == "reasons" else call["case_against"]
    target["claim"] = claim
    if derived is not None:
        target["derived"] = derived
    errors = A.validate_output(out, p)
    assert errors == [], errors
    return C.verify(p, out), out


def problems(v) -> str:
    return " | ".join(pr for s in v.struck for pr in s["problems"])


def ml(v) -> dict:
    return next(c for c in v.calls if c["slot_id"] == "moneyline")


def struck(v) -> bool:
    return [s["slot_id"] for s in v.struck] == ["moneyline"]


def refused(v) -> bool:
    """Struck AND the reason given is about a declared derivation, not merely an unlicensed number."""
    return struck(v) and ".derived" in problems(v)


class TheStoryStillHolds(unittest.TestCase):
    """Nothing about a number with no derivation changed."""

    def test_the_fixture_has_no_eleven_so_the_number_is_genuinely_new(self):
        pool = C.NumberPool.base(packet())
        self.assertFalse(pool.has("11"))

    def test_eleven_days_with_no_derivation_is_still_struck(self):
        v, _ = run()
        self.assertTrue(struck(v))
        self.assertIn("quotes 11, which is not a number in the packet", problems(v))

    def test_eleven_days_with_an_empty_derived_list_is_still_struck(self):
        v, _ = run([])
        self.assertTrue(struck(v))

    def test_a_correct_derivation_for_a_different_number_does_not_license_eleven(self):
        v, _ = run([ERA_GAP])
        self.assertTrue(struck(v))
        self.assertIn("quotes 11", problems(v))

    def test_a_derivation_is_never_a_way_around_a_name_or_a_banned_word(self):
        v, _ = run([DAYS], "The road starter pitched 11 days ago, so Aaron Judge is a lock.")
        text = problems(v)
        self.assertTrue(struck(v))
        self.assertIn("names 'aaron judge'", text)
        self.assertIn("banned word 'lock'", text)

    def test_an_unused_but_correct_derivation_changes_nothing_and_is_not_kept(self):
        v, _ = run([DAYS], "The road starter looks rested.")
        self.assertEqual(v.struck, [])
        self.assertNotIn("derived", ml(v)["reasons"][1])


class DaysBetween(unittest.TestCase):
    def test_correct_over_real_packet_dates_is_kept(self):
        v, _ = run([DAYS])
        self.assertEqual(v.struck, [])
        self.assertEqual(v.calls[0]["verification"]["status"], "verified")

    def test_either_order_of_the_dates_gives_the_same_non_negative_count(self):
        v, _ = run([d("days_between", 11, "days", ["game.date", LAST_START])])
        self.assertEqual(v.struck, [])

    def test_off_by_one_day_strikes_either_way(self):
        for wrong in (10, 12):
            v, _ = run([d("days_between", wrong, "days", [LAST_START, "game.date"])],
                       REST_CLAIM.replace("11", str(wrong)))
            self.assertTrue(refused(v), wrong)
            self.assertIn("days_between of those inputs is 11 days", problems(v))

    def test_a_negative_value_is_the_wrong_sign(self):
        v, _ = run([d("days_between", -11, "days", [LAST_START, "game.date"])])
        self.assertTrue(refused(v))
        self.assertIn("is 11 days, not -11", problems(v))

    def test_the_wrong_unit_strikes(self):
        for unit in ("runs", "percent", "hours"):
            v, _ = run([d("days_between", 11, unit, [LAST_START, "game.date"])])
            self.assertTrue(refused(v), unit)
            self.assertIn("is not a unit days_between can be written in", problems(v))

    def test_a_missing_input_strikes_with_the_reason(self):
        v, _ = run([d("days_between", 11, "days", ["sections.starters.values.no_such_date", "game.date"])])
        self.assertTrue(refused(v))
        self.assertIn("no key 'no_such_date'", problems(v))

    def test_one_input_or_three_strikes(self):
        for inputs in ([LAST_START], [LAST_START, "game.date", "game.first_pitch_utc"]):
            v, _ = run([d("days_between", 11, "days", inputs)])
            self.assertTrue(refused(v), inputs)
            self.assertIn("needs 2 inputs", problems(v))

    def test_an_input_that_is_not_a_date_strikes(self):
        for path in ("game.venue", ERA_AWAY, "sections.starters.values.away_sp_known"):
            v, _ = run([d("days_between", 11, "days", [path, "game.date"])])
            self.assertTrue(refused(v), path)
            self.assertIn("does not hold an ISO date or datetime", problems(v))

    def test_a_string_that_only_looks_like_a_date_strikes(self):
        p = packet(away_sp_last_start="Sept 22")
        v, _ = run([DAYS], p=p)
        self.assertTrue(refused(v))

    def test_the_time_convention_is_calendar_days_in_utc(self):
        # 23:59 on the 22nd at UTC-5 is 04:59 UTC on the 23rd: ten calendar days, not eleven
        p = packet(away_sp_last_start="2026-09-22T23:59:00-05:00")
        ten, _ = run([d("days_between", 10, "days", [LAST_START, "game.date"])],
                     REST_CLAIM.replace("11", "10"), p=p)
        self.assertEqual(ten.struck, [])
        eleven, _ = run([DAYS], p=p)
        self.assertTrue(refused(eleven))

    def test_the_time_of_day_is_dropped_not_rounded(self):
        # 23:50 UTC on the 2nd to 22:30 UTC on the 3rd is 22 hours apart and one calendar day
        p = packet(away_sp_last_start="2026-10-02T23:50:00Z")
        v, _ = run([d("days_between", 1, "days", [LAST_START, "game.first_pitch_utc"])],
                   "The road starter pitched 1 day before this game.", p=p)
        self.assertEqual(v.struck, [])

    def test_a_datetime_and_a_date_work_together_and_naive_is_utc(self):
        p = packet(away_sp_last_start="2026-09-22T20:00:00")
        v, _ = run([d("days_between", 11, "days", [LAST_START, "game.first_pitch_utc"])], p=p)
        self.assertEqual(v.struck, [])

    def test_the_value_must_be_exact_not_close(self):
        v, _ = run([d("days_between", 11.4, "days", [LAST_START, "game.date"])],
                   REST_CLAIM.replace("11", "11.4"))
        self.assertTrue(refused(v))


class Difference(unittest.TestCase):
    CLAIM = "The road starter's ERA is 0.53 higher than the home starter's."

    def test_correct_is_kept_and_signed(self):
        v, _ = run([ERA_GAP], self.CLAIM)
        self.assertEqual(v.struck, [])

    def test_the_prose_may_say_it_without_the_sign(self):
        v, _ = run([d("difference", -0.53, "points", [ERA_HOME, ERA_AWAY])],
                   "The home starter's ERA is 0.53 lower than the road starter's.")
        self.assertEqual(v.struck, [])

    def test_wrong_sign_strikes(self):
        v, _ = run([d("difference", -0.53, "points", [ERA_AWAY, ERA_HOME])], self.CLAIM)
        self.assertTrue(refused(v))
        self.assertIn("is 0.5293 points, not -0.53", problems(v))

    def test_rounding_to_the_precision_written_is_fine(self):
        for value in (0.5, 0.53, 0.529):
            v, _ = run([d("difference", value, "points", [ERA_AWAY, ERA_HOME])],
                       self.CLAIM.replace("0.53", str(value)))
            self.assertEqual(v.struck, [], value)

    def test_a_value_that_is_off_strikes(self):
        for value in (0.6, 0.45, 0.54):
            v, _ = run([d("difference", value, "points", [ERA_AWAY, ERA_HOME])],
                       self.CLAIM.replace("0.53", str(value)))
            self.assertTrue(refused(v), value)

    def test_a_whole_number_cannot_stand_in_for_a_fraction(self):
        v, _ = run([d("difference", 1, "points", [ERA_AWAY, ERA_HOME])], "The gap is 1 point.")
        self.assertTrue(refused(v))

    def test_the_wrong_unit_strikes(self):
        for unit in ("days", "percent", "ratio"):
            v, _ = run([d("difference", 0.53, unit, [ERA_AWAY, ERA_HOME])], self.CLAIM)
            self.assertTrue(refused(v), unit)

    def test_percentage_points_scale_a_probability_difference(self):
        a, b = "markets.moneyline.options[0].fair_probability", "markets.moneyline.options[1].fair_probability"
        p = packet()
        pa, pb = p["markets"]["moneyline"]["options"][0]["fair_probability"], \
            p["markets"]["moneyline"]["options"][1]["fair_probability"]
        gap = round((pa - pb) * 100, 1)
        v, _ = run([d("difference", gap, "percentage points", [a, b])],
                   f"The books put the home side {gap} percentage points clear.", p=p)
        self.assertEqual(v.struck, [])

    def test_missing_or_non_numeric_inputs_strike(self):
        for inputs, text in (([ERA_AWAY, "sections.starters.values.nope"], "no key 'nope'"),
                             ([ERA_AWAY, "game.venue"], "does not hold a number"),
                             ([ERA_AWAY, "sections.starters.values.away_sp_known"], "does not hold a number"),
                             ([ERA_AWAY, "sections.starters"], "is a group"),
                             ([ERA_AWAY], "needs 2 inputs")):
            v, _ = run([d("difference", 0.53, "points", inputs)], self.CLAIM)
            self.assertTrue(refused(v), inputs)
            self.assertIn(text, problems(v))


class SumMeanRatioPercentChange(unittest.TestCase):
    def test_sum_right_and_wrong(self):
        ok, _ = run([d("sum", 6.28, "points", [ERA_AWAY, ERA_HOME])], "The two ERAs sum to 6.28.")
        self.assertEqual(ok.struck, [])
        bad, _ = run([d("sum", 6.3, "points", [ERA_AWAY, ERA_HOME])], "The two ERAs sum to 6.3.")
        self.assertEqual(bad.struck, [])      # 6.2815 to one decimal is 6.3
        worse, _ = run([d("sum", 6.4, "points", [ERA_AWAY, ERA_HOME])], "The two ERAs sum to 6.4.")
        self.assertTrue(refused(worse))

    def test_sum_takes_up_to_twelve_inputs_and_not_one(self):
        v, _ = run([d("sum", 3.41, "points", [ERA_AWAY])], "That is 3.41.")
        self.assertTrue(refused(v))
        self.assertIn("needs 2 to 12 inputs", problems(v))

    def test_mean_right_and_wrong(self):
        ok, _ = run([d("mean", 3.14, "points", [ERA_AWAY, ERA_HOME])], "The two ERAs average 3.14.")
        self.assertEqual(ok.struck, [])
        bad, _ = run([d("mean", 3.3, "points", [ERA_AWAY, ERA_HOME])], "The two ERAs average 3.3.")
        self.assertTrue(refused(bad))

    def test_ratio_right_and_wrong(self):
        ok, _ = run([d("ratio", 1.18, "times", [ERA_AWAY, ERA_HOME])], "The road ERA is 1.18 times the home ERA.")
        self.assertEqual(ok.struck, [])
        bad, _ = run([d("ratio", 0.84, "times", [ERA_AWAY, ERA_HOME])], "The road ERA is 0.84 times the home ERA.")
        self.assertTrue(refused(bad))                  # the ratio the wrong way round
        pct, _ = run([d("ratio", 118.4, "percent", [ERA_AWAY, ERA_HOME])], "The road ERA is 118.4% of the home ERA.")
        self.assertEqual(pct.struck, [])

    def test_ratio_by_zero_is_refused(self):
        v, _ = run([d("ratio", 1.0, "ratio", [ERA_AWAY, "sections.starters.values.away_sp_zero"])],
                   "The ratio is 1.0.")
        self.assertTrue(refused(v))
        self.assertIn("divides by zero", problems(v))

    def test_percent_change_right_and_wrong(self):
        # from the home ERA to the road ERA: (3.4054 - 2.8761) / 2.8761 = 18.4%
        ok, _ = run([d("percent_change", 18.4, "percent", [ERA_HOME, ERA_AWAY])],
                    "From the home ERA to the road ERA is up 18.4%.")
        self.assertEqual(ok.struck, [])
        sign, _ = run([d("percent_change", -18.4, "percent", [ERA_HOME, ERA_AWAY])],
                      "From the home ERA to the road ERA is down 18.4%.")
        self.assertTrue(refused(sign))
        base, _ = run([d("percent_change", 15.5, "percent", [ERA_AWAY, ERA_HOME])],
                      "That is up 15.5%.")
        self.assertTrue(refused(base))                 # measured from the wrong end
        unit, _ = run([d("percent_change", 18.4, "points", [ERA_HOME, ERA_AWAY])], "Up 18.4.")
        self.assertTrue(refused(unit))

    def test_percent_change_from_zero_is_refused(self):
        v, _ = run([d("percent_change", 5.0, "percent", ["sections.starters.values.away_sp_zero", ERA_AWAY])],
                   "That is up 5.0%.")
        self.assertTrue(refused(v))
        self.assertIn("starts from zero", problems(v))


class ImpliedProbabilityAndCount(unittest.TestCase):
    def test_implied_probability_right_in_percent_and_as_a_probability(self):
        # TB's best price is -127: 127 / 227 = 0.5595
        ok, _ = run([d("implied_probability", 55.9, "percent", [ML_PRICE])],
                    "The best home price implies 55.9% for the home side.")
        self.assertEqual(ok.struck, [])
        prob, _ = run([d("implied_probability", 0.56, "probability", [ML_PRICE])],
                      "The best home price implies 0.56 for the home side.")
        self.assertEqual(prob.struck, [])
        pct, _ = run([d("implied_probability", 0.56, "probability", [ML_PRICE])],
                     "The best home price implies 56% for the home side.")
        self.assertEqual(pct.struck, [])                      # a probability may be said as a percentage

    def test_implied_probability_wrong_value_unit_or_input(self):
        wrong, _ = run([d("implied_probability", 59.0, "percent", [ML_PRICE])], "That implies 59.0%.")
        self.assertTrue(refused(wrong))
        flipped, _ = run([d("implied_probability", 0.44, "probability", [ML_PRICE])], "That implies 0.44.")
        self.assertTrue(refused(flipped))                      # the other side's number
        unit, _ = run([d("implied_probability", 55.9, "days", [ML_PRICE])], "That implies 55.9.")
        self.assertTrue(refused(unit))
        for path, text in ((ERA_AWAY, "does not hold an American price"),
                           ("game.venue", "does not hold an American price"),
                           ("markets.moneyline.options[9].best.price", "no list item [9]")):
            v, _ = run([d("implied_probability", 55.9, "percent", [path])], "That implies 55.9%.")
            self.assertTrue(refused(v), path)
            self.assertIn(text, problems(v))

    def test_count_right_and_wrong(self):
        ok, _ = run([d("count", 3, "books", [ML_QUOTES])], "Three books quote the home side, 3 of them.")
        self.assertEqual(ok.struck, [])
        wrong, _ = run([d("count", 2, "books", [ML_QUOTES])], "Only 2 books quote the home side.")
        self.assertTrue(refused(wrong))
        unit, _ = run([d("count", 3, "days", [ML_QUOTES])], "That is 3.")
        self.assertTrue(refused(unit))

    def test_count_needs_a_list(self):
        for path, text in ((ERA_AWAY, "is not a list"), ("markets.moneyline.options[0]", "is a group")):
            v, _ = run([d("count", 3, "books", [path])], "There are 3 of them.")
            self.assertTrue(refused(v), path)
            self.assertIn(text, problems(v))

    def test_a_group_is_refused_as_a_numeric_input_but_a_list_is_countable(self):
        v, _ = run([d("sum", 3.0, "points", [ML_QUOTES, ERA_AWAY])], "That is 3.0.")
        self.assertTrue(refused(v))
        self.assertIn("is a group", problems(v))


class UnknownOpsAndShape(unittest.TestCase):
    def test_an_unknown_op_strikes_with_the_ops_it_does_know(self):
        v, _ = run([d("median", 3.14, "points", [ERA_AWAY, ERA_HOME])], "The median is 3.14.")
        self.assertTrue(refused(v))
        self.assertIn("'median' is not a calculation the checker knows", problems(v))
        self.assertIn("days_between", problems(v))

    def test_an_unknown_unit_strikes(self):
        v, _ = run([d("difference", 0.53, "parsecs", [ERA_AWAY, ERA_HOME])], "The gap is 0.53.")
        self.assertTrue(refused(v))

    def test_more_than_six_derivations_in_one_item_strikes(self):
        v, _ = run([DAYS] * 7)
        self.assertTrue(refused(v))
        self.assertIn("at most 6", problems(v))

    def test_a_value_that_is_not_a_number_strikes_in_the_critic_and_fails_the_shape_first(self):
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1]["derived"] = [d("days_between", "11", "days", [LAST_START, "game.date"])]
        self.assertTrue(any("value must be a number" in e for e in A.validate_output(out, p)))
        v = C.verify(p, out)                       # the critic is never the one that raises
        self.assertEqual([s["slot_id"] for s in v.struck], ["moneyline"])

    def test_the_shape_check_names_each_malformed_derivation(self):
        p = packet()
        for bad, text in (("not a list", "derived must be a list"),
                          ([["x"]], "is not an object"),
                          ([{"op": "sum"}], "is missing"),
                          ([dict(DAYS, extra=1)], "unexpected keys"),
                          ([dict(DAYS, inputs="game.date")], "inputs must be a list"),
                          ([dict(DAYS, op=3)], "op, unit and note as strings")):
            out = F.good_output(p)
            out["calls"][0]["reasons"][0]["derived"] = bad
            errors = A.validate_output(out, p)
            self.assertTrue(any(text in e for e in errors), (bad, errors))

    def test_an_absent_derived_is_an_empty_one(self):
        p = packet()
        self.assertEqual(A.validate_output(F.good_output(p), p), [])

    def test_an_unknown_top_level_key_is_still_refused(self):
        p = packet()
        out = F.good_output(p)
        out["extra"] = 1
        self.assertTrue(any("unexpected top-level keys" in e for e in A.validate_output(out, p)))


class WhatADerivationLicenses(unittest.TestCase):
    def test_it_does_not_license_a_different_number_in_the_same_sentence(self):
        v, _ = run([DAYS], "The road starter pitched 11 days ago and 12 days before that.")
        self.assertTrue(struck(v))
        self.assertIn("quotes 12", problems(v))
        self.assertNotIn("quotes 11", problems(v))

    def test_it_does_not_license_the_number_in_another_reason(self):
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1]["claim"] = REST_CLAIM
        out["calls"][0]["reasons"][1]["derived"] = [DAYS]
        out["calls"][0]["reasons"][0]["claim"] = "That is 11 days of rest."
        v = C.verify(p, out)
        self.assertTrue(struck(v))
        self.assertIn("reasons[0] quotes 11", problems(v))

    def test_it_does_not_license_the_number_in_what_would_change_it(self):
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1].update(claim=REST_CLAIM, derived=[DAYS])
        out["calls"][0]["what_would_change_it"] = "Another 11 days of rest."
        v = C.verify(p, out)
        self.assertTrue(struck(v))
        self.assertIn("what_would_change_it quotes 11", problems(v))

    def test_it_does_not_license_another_call(self):
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1].update(claim=REST_CLAIM, derived=[DAYS])
        out["calls"][1]["reasons"][0]["claim"] = "The road starter had 11 days of rest."
        v = C.verify(p, out)
        self.assertEqual([s["slot_id"] for s in v.struck], [out["calls"][1]["slot_id"]])

    def test_a_case_against_declares_and_is_licensed_on_its_own(self):
        claim = "The road starter pitched 11 days ago, which is plenty of rest, and that works against this bet."
        v, _ = run([DAYS], claim, where="case_against")
        self.assertEqual(v.struck, [])
        self.assertEqual(ml(v)["case_against"]["derived"][0]["value"], 11)
        # and the reasons beside it are not licensed by it
        self.assertNotIn("derived", ml(v)["reasons"][0])
        none, _ = run(None, claim, where="case_against")
        self.assertTrue(struck(none))
        self.assertIn("case_against quotes 11", problems(none))

    def test_a_wrong_derivation_in_the_case_against_strikes_the_call(self):
        bad = d("days_between", 12, "days", [LAST_START, "game.date"])
        v, _ = run([bad], "The road starter pitched 12 days ago, which is plenty of rest.", where="case_against")
        self.assertTrue(struck(v))

    def test_the_wrong_derivation_strikes_even_when_the_prose_number_is_in_the_packet(self):
        v, _ = run([d("days_between", 12, "days", [LAST_START, "game.date"])],
                   "The road ERA is 3.4054.")
        self.assertTrue(struck(v))


class TheSummary(unittest.TestCase):
    def out(self, derived=None, sentence=" The road starter pitched 11 days before the game."):
        p = packet()
        out = F.good_output(p)
        out["summary"] = out["summary"] + sentence
        if derived is not None:
            out["summary_derived"] = derived
        self.assertEqual(A.validate_output(out, p), [])
        return p, out

    def test_a_calculated_number_in_the_summary_needs_its_derivation(self):
        p, out = self.out()
        v = C.verify(p, out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertIn("the summary quotes 11", " ".join(v.summary_problems))

    def test_a_verified_derivation_licenses_the_summary_and_is_kept(self):
        p, out = self.out([DAYS])
        v = C.verify(p, out)
        self.assertEqual(v.summary_status, "ok")
        self.assertEqual(v.summary_derived[0]["value"], 11)
        self.assertEqual(v.struck, [])

    def test_a_wrong_summary_derivation_withholds_the_summary_and_the_calls_still_publish(self):
        p, out = self.out([d("days_between", 12, "days", [LAST_START, "game.date"])],
                          " The road starter pitched 12 days before the game.")
        v = C.verify(p, out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertIsNone(v.summary)
        self.assertEqual(v.summary_derived, [])
        self.assertEqual(v.struck, [])
        self.assertIn("the summary's derived[0]", " ".join(v.summary_problems))

    def test_a_calls_derivation_does_not_license_the_summary(self):
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1].update(claim=REST_CLAIM, derived=[DAYS])
        out["summary"] += " The road starter pitched 11 days before the game."
        v = C.verify(p, out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertEqual(v.struck, [])


class UfcIsUntouched(unittest.TestCase):
    def test_the_ufc_schema_and_hash_are_what_they_were(self):
        self.assertEqual(hashlib.sha256(json.dumps(A.RESPONSE_SCHEMA, sort_keys=True).encode()).hexdigest(),
                         UFC_SCHEMA_SHA256)
        self.assertEqual(U.prompt_hash(), UFC_PROMPT_HASH)
        self.assertNotIn("derived", json.dumps(A.RESPONSE_SCHEMA))
        self.assertNotIn("derived", U.UFC_SYSTEM_PROMPT)
        self.assertIsNot(A.MLB_RESPONSE_SCHEMA, A.RESPONSE_SCHEMA)

    def test_the_ufc_request_carries_the_shared_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkt = UF.packet(UF.make_store(Path(tmp)))
            body = U.build_request(pkt, UF.CFG)
        self.assertIs(A.schema_for(pkt), A.RESPONSE_SCHEMA)
        self.assertEqual(body["output_config"]["format"]["schema"], A.RESPONSE_SCHEMA)
        self.assertNotIn("summary_derived", json.dumps(body))

    def test_a_ufc_reason_that_declares_a_derivation_is_not_licensed_by_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkt = UF.packet(UF.make_store(Path(tmp)))
        out = UF.good_output(pkt)
        slots = len(pkt["slots"])
        reason = out["calls"][0]["reasons"][0]
        reason["claim"] = f"There are {slots} things to call here."
        before = U.verify(pkt, copy.deepcopy(out))
        reason["derived"] = [d("count", slots, "items", ["slots"])]
        after = U.verify(pkt, out)
        self.assertEqual([s["problems"] for s in after.struck], [s["problems"] for s in before.struck])
        self.assertEqual(after.summary_derived, [])
        for call in after.calls:
            for r in call["reasons"]:
                self.assertNotIn("derived", r)


class TheSchemaAndThePrompt(unittest.TestCase):
    def test_the_schema_asks_for_derived_on_reasons_the_case_against_and_the_summary(self):
        s = A.MLB_RESPONSE_SCHEMA
        self.assertIn("summary_derived", s["required"])
        item = s["properties"]["calls"]["items"]
        reason = item["properties"]["reasons"]["items"]
        self.assertIn("derived", reason["required"])
        self.assertIn("derived", reason["properties"])
        self.assertEqual(item["properties"]["case_against"]["anyOf"][0], reason)
        entry = reason["properties"]["derived"]["items"]
        self.assertEqual(entry["required"], ["value", "unit", "op", "inputs", "note"])
        self.assertFalse(entry["additionalProperties"])
        self.assertEqual(entry["properties"]["op"]["enum"], list(A.DERIVATION_OPS))

    def test_the_prompt_says_what_to_do_and_leaves_every_rule_number_where_it_was(self):
        text = A.SYSTEM_PROMPT
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v3")
        self.assertIn("3a. The one exception to doing arithmetic is a calculation you declare.", text)
        self.assertIn("Do no arithmetic of your own on packet numbers in prose", text)
        self.assertIn("the checker recomputes every derived value", text.replace("The checker recomputes", "the checker recomputes"))
        for op in A.DERIVATION_OPS:
            self.assertIn(op, text)
        rules = [int(n) for n in re.findall(r"^(\d+)\. ", text, re.M)]
        self.assertEqual(rules, list(range(1, 17)))
        self.assertEqual(C.banned_words(text.split("THE WORDS")[0]), [])

    def test_the_checker_and_the_schema_name_the_same_ops_and_units(self):
        self.assertEqual({op: tuple(rules) for op, rules in C.UNIT_RULES.items()},
                         {op: tuple(units) for op, units in A.DERIVATION_UNITS.items()})
        self.assertEqual(set(C.UNIT_RULES), set(C._ARITY))

    def test_the_prompt_hash_moved_and_covers_the_schema(self):
        self.assertEqual(ledger.prompt_hash(),
                         hashlib.sha256((A.SYSTEM_PROMPT + "\n" + json.dumps(
                             A.MLB_RESPONSE_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest())
        self.assertNotEqual(ledger.prompt_hash(), U.prompt_hash())


class ProvenanceKeptWithTheReport(unittest.TestCase):
    def test_the_published_reason_carries_what_was_verified_and_what_it_came_from(self):
        v, _ = run([DAYS])
        reason = ml(v)["reasons"][1]
        rec = reason["derived"][0]
        self.assertEqual((rec["op"], rec["unit"], rec["value"]), ("days_between", "days", 11))
        self.assertEqual([i["path"] for i in rec["inputs"]], [LAST_START, "game.date"])
        self.assertEqual([i["value"] for i in rec["inputs"]], ["2026-09-22", "2026-10-03"])
        self.assertEqual(rec["note"], "days since the road starter's last start")
        self.assertEqual(reason["claim"], REST_CLAIM)

    def test_a_reason_with_no_derivation_is_what_it_always_was(self):
        p = packet()
        v = C.verify(p, F.good_output(p))
        for c in v.calls:
            for r in c["reasons"]:
                self.assertEqual(set(r), {"claim", "evidence"})
        self.assertEqual(v.summary_derived, [])

    def test_the_models_own_derived_list_is_never_what_is_published(self):
        # the shape check refuses an unknown key, so go straight at the critic, which must not echo it
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1].update(claim=REST_CLAIM, derived=[dict(DAYS, sneaky="x")])
        v = C.verify(p, out)
        self.assertEqual(v.struck, [])
        self.assertNotIn("sneaky", json.dumps(ml(v)))

    def test_a_struck_call_publishes_nothing_it_said(self):
        v, _ = run([d("days_between", 12, "days", [LAST_START, "game.date"])], REST_CLAIM.replace("11", "12"))
        published = json.dumps(ml(v))
        self.assertNotIn("derived", published)
        self.assertNotIn("12", ml(v)["reasons"][0]["claim"])
        self.assertIn("derived", json.dumps(v.struck[0]["original"]))      # the audit trail keeps it

    def test_the_sentences_are_plain_and_carry_no_path(self):
        v, _ = run([DAYS])
        sentence = C.derivation_sentence(ml(v)["reasons"][1]["derived"][0])
        self.assertEqual(sentence, "11 days: calendar days (UTC) from away starter last start to the game date.")
        self.assertNotIn("sections.", sentence)
        self.assertNotIn("_", sentence)

    def test_every_op_has_a_plain_sentence(self):
        cases = [
            ([ERA_GAP], "The road starter's ERA is 0.53 higher.", "0.53 points: away starter ERA minus home starter ERA."),
            ([d("sum", 6.28, "points", [ERA_AWAY, ERA_HOME])], "They sum to 6.28.",
             "6.28 points: away starter ERA plus home starter ERA."),
            ([d("mean", 3.14, "points", [ERA_AWAY, ERA_HOME])], "They average 3.14.",
             "3.14 points: the average of away starter ERA, home starter ERA."),
            ([d("ratio", 1.18, "times", [ERA_AWAY, ERA_HOME])], "That is 1.18 times.",
             "1.18 times: away starter ERA divided by home starter ERA."),
            ([d("percent_change", 18.4, "percent", [ERA_HOME, ERA_AWAY])], "That is up 18.4%.",
             "18.4 percent: the change from home starter ERA to away starter ERA, as a percent of home starter ERA."),
            ([d("implied_probability", 55.9, "percent", [ML_PRICE])], "That implies 55.9%.",
             "55.9 percent: the chance the price implies for TB moneyline price at -127."),
            ([d("count", 3, "books", [ML_QUOTES])], "There are 3 of them.",
             "3 books: how many entries TB moneyline quotes lists."),
        ]
        for derived, claim, expected in cases:
            v, _ = run(derived, claim)
            self.assertEqual(v.struck, [], claim)
            self.assertEqual(C.derivation_sentences(ml(v)["reasons"][1]["derived"]), [expected])


class StoredAndServed(unittest.TestCase):
    """`ledger.publish` stores the verified records; `game_view` serves one plain sentence each."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = str(self.root / "analyst.jsonl")

    def publish(self, p, out):
        verified = C.verify(p, out)
        row, created = ledger.publish(p, verified, model="claude-sonnet-5-5", now=F.NOW, path=self.store,
                                      packet_dir=self.root / "packets")
        self.assertTrue(created)
        return row, verified

    def test_the_row_stores_the_records_and_the_view_serves_sentences_only(self):
        p = packet()
        out = F.good_output(p)
        out["calls"][0]["reasons"][1].update(claim=REST_CLAIM, derived=[DAYS])
        out["calls"][0]["case_against"].update(
            claim="The road starter pitched 11 days ago, which is plenty of rest.", derived=[DAYS])
        out["summary"] += " The road starter pitched 11 days before the game."
        out["summary_derived"] = [DAYS]
        row, verified = self.publish(p, out)
        self.assertEqual(row["prompt_version"], "analyst_prompt_v3")
        self.assertEqual(row["calls"][0]["reasons"][1]["derived"][0]["inputs"][0]["path"], LAST_START)
        self.assertEqual(row["summary_derived"][0]["value"], 11)

        view = ledger.game_view(F.DATE, "NYY", "TB", path=self.store, root=self.root / "packets")
        sentence = "11 days: calendar days (UTC) from away starter last start to the game date."
        call = view["calls"][0]
        self.assertEqual(call["reasons"][1]["derivations"], [sentence])
        self.assertEqual(call["case_against"]["derivations"], [sentence])
        self.assertEqual(view["summary_derivations"], [sentence])
        served = json.dumps(view)
        self.assertNotIn("sections.starters", served.replace(
            "sections.starters.values.away_sp_fip", "").replace("sections.starters.values.home_sp_fip", "")
            .replace("sections.starters.values.away_sp_era", "").replace("sections.starters.values.home_sp_era", ""))
        self.assertNotIn('"derived"', served)
        self.assertNotIn("sneaky", served)

    def test_a_row_with_no_derivation_serves_no_new_key_on_its_reasons(self):
        p = packet()
        self.publish(p, F.good_output(p))
        view = ledger.game_view(F.DATE, "NYY", "TB", path=self.store, root=self.root / "packets")
        for call in view["calls"]:
            for r in call["reasons"]:
                self.assertEqual(set(r), {"claim", "evidence"})
        self.assertEqual(view["summary_derivations"], [])
        row = ledger.rows(self.store)[0]
        self.assertNotIn("summary_derived", row)

    def test_a_row_written_before_v3_still_serves(self):
        # a stored reason with no `derived` and a row with no `summary_derived` (all of v2's rows)
        rows = [{"kind": ledger.KIND_PUBLISHED, "game_id": "g", "date": F.DATE, "away": "NYY", "home": "TB",
                 "first_pitch_utc": F.FIRST_PITCH, "published_utc": "x", "model": "m", "version": 1,
                 "row_hash": "h", "summary": "s", "summary_status": "ok",
                 "calls": [{"slot_id": "moneyline", "market": "moneyline", "selection": "TB",
                            "verdict": "PASS", "reasons": [{"claim": "c", "evidence": []}],
                            "case_against": None, "grading": {}}]}]
        view = ledger.game_view(F.DATE, "NYY", "TB", all_rows=rows)
        self.assertEqual(view["calls"][0]["reasons"], [{"claim": "c", "evidence": []}])
        self.assertEqual(view["summary_derivations"], [])


if __name__ == "__main__":
    unittest.main()
