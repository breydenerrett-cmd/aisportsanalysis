"""The Analyze report (src/hounds/analyze_report.py): numbers worked out by hand, the honesty rules, and the Coach's read.

Runs without FastAPI (the Linux CI has none). The fixture is a DRAKEO-like hound at 16-7 over 23 settled bets, one a day from
2026-10-01, in a deterministic shuffle:

    9 favourites  taken at -115 at home  (implied win probability 115/215), 6 won, 3 lost
   14 underdogs   taken at +130 away     (implied win probability 100/230), 10 won, 4 lost

so the prices expected 9 * 115/215 + 14 * 100/230 = 10.90 wins, and the chance of 16 or more is a sum of two binomials worked out here
with ``math.comb`` and not with the module's own dynamic programme.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

from src.ai.postmortem_store import bet_key
from src.hounds import analyze_report as A, digest, pick_grades, stats, user_spec, user_store, user_view, verdict as vd
from src.hounds.interact import common, retune, rites
from tests._hounds_rites_fixtures import NOW as RITES_NOW, RitesCase, ticket, write_ledger
from tests._hounds_user_fixtures import spec_dict
from tests.test_hounds_coach import FakeAdapter, FakeAnswer, FakeRouter, real_router

HID = "u-drakeo"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
P_FAV, P_DOG = 115 / 215, 100 / 230
PLAN = [("home", -115, "WIN")] * 6 + [("home", -115, "LOSS")] * 3 + [("away", 130, "WIN")] * 10 + [("away", 130, "LOSS")] * 4
random.Random(7).shuffle(PLAN)
SPEC = user_spec.validate_spec(spec_dict(name="DRAKEO", sports=["MLB"], markets=["moneyline"], side_rule="underdog",
                                         price_min=-120, price_max=150, min_books=3, max_bets_per_day=2))


def dog(spec=SPEC, hid=HID, version_no=1):
    return common.Dog(id=hid, kind=common.KIND_USER, name="DRAKEO", hound={"spec": spec, "version_no": version_no}, owner_user_id=1,
                      root_id=hid)


def rows_of(plan, hid=HID):
    rows = []
    for day, (side, price, res) in enumerate(plan):
        rows.extend(ticket(hid, day=day, result=res.upper() if res else None, side=side, price=price))
    return rows


ROWS = rows_of(PLAN)


def clv_book(pairs):
    """A stand-in for the cached ``stats.HoundData``: only what the report reads (the measurable closing-line points, the BetRows)."""
    return types.SimpleNamespace(clv_points=pairs, bets=[])


def clv_pairs(n, beat, start="2026-09-01"):
    """``n`` (day, points) pairs, ``beat`` of them positive, on distinct days."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), 0.5 if i < beat else -0.5) for i in range(n)]


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from strings_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from strings_in(v)


def p_at_least_16():
    """P(wins >= 16): 9 bets at P_FAV plus 14 bets at P_DOG, by the product of two binomials."""
    def pmf(n, p, k):
        return math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    return sum(pmf(9, P_FAV, a) * pmf(14, P_DOG, b) for a in range(10) for b in range(15) if a + b >= 16)


class TailMath(unittest.TestCase):
    def test_the_exact_tail_matches_brute_force_on_four_unequal_bets(self):
        import itertools
        probs = [0.2, 0.5, 0.65, 0.9]
        for k in range(0, 6):
            want = 0.0
            for outcome in itertools.product([0, 1], repeat=4):
                if sum(outcome) >= k:
                    mass = 1.0
                    for o, p in zip(outcome, probs):
                        mass *= p if o else 1 - p
                    want += mass
            self.assertAlmostEqual(A.tail_at_least(probs, k), want, places=12, msg=k)
        self.assertAlmostEqual(A.tail_at_most(probs, 2), 1 - A.tail_at_least(probs, 3), places=12)

    def test_equal_bets_are_a_plain_binomial(self):
        p = 110 / 210
        want = sum(math.comb(23, k) * p ** k * (1 - p) ** (23 - k) for k in range(16, 24))
        self.assertAlmostEqual(A.tail_at_least([p] * 23, 16), want, places=12)

    def test_the_normal_approximation_beyond_the_exact_range_is_close(self):
        probs = [0.45 + 0.1 * ((i * 7) % 5) / 4 for i in range(450)]
        k = int(sum(probs) + 8)
        with mock.patch.object(A, "EXACT_TAIL_MAX_BETS", 10_000):
            exact = A.tail_at_least(probs, k)
        self.assertLess(A.EXACT_TAIL_MAX_BETS, 450)
        self.assertAlmostEqual(A.tail_at_least(probs, k), exact, delta=0.01)

    def test_edges(self):
        self.assertEqual(A.tail_at_least([0.5, 0.5], 0), 1.0)
        self.assertEqual(A.tail_at_least([0.5, 0.5], 3), 0.0)
        self.assertEqual(A.tail_at_most([0.5, 0.5], 5), 1.0)
        self.assertEqual(A.tail_at_most([0.5, 0.5], -1), 0.0)
        self.assertIsNone(A.implied_probability(None))
        self.assertIsNone(A.implied_probability(50))
        self.assertAlmostEqual(A.implied_probability(-115), P_FAV, places=9)
        self.assertAlmostEqual(A.implied_probability(130), P_DOG, places=9)


class TheSixteenAndSevenHound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = A.build_report(dog(), ROWS, now=NOW)
        cls.hot = cls.report["hot_hand"]

    def test_the_headline_is_one_sentence_from_the_numbers(self):
        units = 6 * (100 / 115) + 10 * 1.3 - 3 - 4
        roi = round(100 * units / 23, 1)
        self.assertEqual(self.report["headline"], f"DRAKEO is 16-7, {roi:+.1f}% on paper over 23 settled bets.")
        self.assertEqual(self.report["record"]["wins"], 16)
        self.assertAlmostEqual(self.report["record"]["units"], units, places=1)

    def test_expected_wins_and_the_luck_check_are_the_prices_arithmetic(self):
        want = 9 * P_FAV + 14 * P_DOG
        self.assertEqual((self.hot["actual_w"], self.hot["expected_w"]), (16, round(want, 2)))
        p = p_at_least_16()
        self.assertAlmostEqual(self.hot["luck_check"]["p"], p, places=4)
        self.assertEqual(self.hot["luck_check"]["one_in"], int(round(1 / p)))
        self.assertEqual((self.hot["luck_check"]["tail"], self.hot["luck_check"]["method"]), ("at_least", "exact"))
        self.assertEqual(self.hot["temperature"], "hot")

    def test_23_bets_can_only_be_too_early_and_the_referee_says_so(self):
        self.assertEqual(self.hot["verdict"], "too_early")
        self.assertEqual(self.hot["referee"]["label"], vd.TOO_EARLY)
        self.assertEqual(self.hot["referee"]["needs"], 150)
        self.assertEqual(self.hot["meter_label"], "Hot dice, so far")
        self.assertLessEqual(self.hot["meter"], 49)
        self.assertTrue(self.hot["text"].startswith("Hot, but too early to call: it won 16 where the prices expected about 10.9."))
        self.assertIn(f"about 1 time in {self.hot['luck_check']['one_in']}", self.hot["text"])

    def test_the_closing_line_is_counted_from_the_referees_own_points(self):
        out = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(21, 14)))["hot_hand"]
        self.assertEqual((out["clv"]["measured"], out["clv"]["beat"]), (21, 14))
        self.assertAlmostEqual(out["clv"]["avg_pts"], round((14 * 0.5 - 7 * 0.5) / 21, 2), places=2)
        self.assertIn("It beat the closing line on 14 of 21 measured bets, which is the better sign to watch.", out["text"])
        self.assertEqual((out["verdict"], out["referee"]["n"]), ("too_early", 21))
        self.assertIn("Only 21 of its bets have a measurable closing price", out["referee"]["sentence"])

    def test_the_meter_scales_how_unusual_the_record_is_by_how_much_of_the_referees_sample_exists(self):
        p = p_at_least_16()
        for measured, want in ((0, 0), (21, round(100 * (1 - p) * 21 / 150)), (60, round(100 * (1 - p) * 60 / 150))):
            out = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(measured, measured // 2)) if measured else None)["hot_hand"]
            self.assertEqual(out["meter"], min(want, 49), measured)

    def test_the_run_and_the_pace(self):
        self.assertEqual(self.hot["streak"]["longest_win"] >= 1, True)
        seq = [r for _s, _p, r in PLAN]
        cur = 0
        for r in reversed(seq):
            if r == seq[-1]:
                cur += 1
            else:
                break
        self.assertEqual((self.hot["streak"]["current"], self.hot["streak"]["current_length"]), (seq[-1].lower(), cur))
        keep = self.report["keep_it_up"]
        self.assertEqual(keep["pace_per_day"], 1.0)
        self.assertEqual(keep["need_measured"], 150)

    def test_an_empty_hound_says_so(self):
        out = A.build_report(dog(), [], now=NOW)
        self.assertEqual(out["headline"], "DRAKEO has no settled bets yet.")
        self.assertEqual((out["hot_hand"]["actual_w"], out["hot_hand"]["verdict"]), (0, "too_early"))
        self.assertIn("nothing to call", out["hot_hand"]["text"])
        self.assertEqual(out["picks"], [])

    def test_a_cold_hound_is_called_cold_and_never_hot(self):
        cold = [("away", 130, "LOSS")] * 12 + [("away", 130, "WIN")] * 2
        out = A.build_report(dog(), rows_of(cold), now=NOW)["hot_hand"]
        self.assertEqual((out["temperature"], out["meter"], out["meter_label"]), ("cold", 0, "Running cold"))
        self.assertEqual(out["luck_check"]["tail"], "at_most")
        self.assertIn("too early to read anything into it", out["text"])


class TheReferee150Path(unittest.TestCase):
    def test_with_150_measurable_bets_the_referees_verdict_decides(self):
        with mock.patch.object(A.vd, "verdict_for", wraps=vd.verdict_for) as spy:
            out = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(160, 160)))["hot_hand"]
        spy.assert_called_once()
        self.assertEqual(len(spy.call_args.args[0]), 160)
        self.assertEqual((out["verdict"], out["referee"]["label"]), ("real_signal", vd.BEATING_THE_CLOSE))
        self.assertGreaterEqual(out["meter"], 50)
        self.assertEqual(out["meter_label"], "Hot hand")
        self.assertIn(out["referee"]["sentence"], out["text"])
        self.assertIn("says nothing about the next bet", out["text"])

    def test_prices_worse_than_the_close_make_a_hot_record_look_like_luck(self):
        out = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(160, 0)))["hot_hand"]
        self.assertEqual((out["verdict"], out["referee"]["label"]), ("looks_like_luck", vd.PAYING_THE_VIG))
        self.assertLess(out["meter"], 50)
        self.assertIn("the prices do not explain it", out["text"])

    def test_149_is_still_too_early(self):
        out = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(149, 149)))["hot_hand"]
        self.assertEqual(out["verdict"], "too_early")
        self.assertLessEqual(out["meter"], 49)


class Drivers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = A.build_report(dog(), ROWS, now=NOW)

    def test_winning_slices_are_the_diagnosis_cuts_with_their_levels(self):
        win = {d["id"]: d for d in self.report["drivers"]["winning"]}
        self.assertEqual(win["band:underdogs"]["record"], "10-4")
        self.assertAlmostEqual(win["band:underdogs"]["units"], 13.0 - 4.0, places=2)
        self.assertEqual(win["band:underdogs"]["n"], 14)
        self.assertIn(win["band:underdogs"]["level"], ("low", "medium", "high"))
        self.assertEqual(win["band:favourites"]["record"], "6-3")
        self.assertEqual(self.report["drivers"]["losing"], [])
        self.assertLessEqual(len(self.report["drivers"]["winning"]), 3)

    def test_two_cuts_that_hold_the_same_bets_are_one_finding(self):
        ids = [d["id"] for d in self.report["drivers"]["winning"]]
        # the underdogs are also the away-side bets and the 'role' cut of a moneyline price: one finding, not three
        self.assertEqual(len([i for i in ids if i in ("band:underdogs", "venue:away", "role:underdog")]), 1)

    def test_the_note_says_many_cuts_were_examined(self):
        self.assertIn("ways of slicing the bets were examined", self.report["drivers"]["note"])
        self.assertIn("not a forecast", self.report["drivers"]["note"])

    def test_losing_slices_and_the_too_few_rule(self):
        plan = ([("home", -115, "LOSS")] * 6 + [("home", -115, "WIN")] * 1 + [("away", 130, "WIN")] * 8 + [("away", 130, "LOSS")] * 2
                + [("away", 250, "LOSS")] * 3)
        out = A.build_report(dog(), rows_of(plan), now=NOW)["drivers"]
        lose = {d["id"]: d for d in out["losing"]}
        self.assertEqual(lose["band:favourites"]["record"], "1-6")
        self.assertNotIn("band:long_shots", lose)           # 3 bets: too few to say, so not a driver
        self.assertTrue(all(d["level"] != "too_few" for d in out["winning"] + out["losing"]))


class KeepItUp(unittest.TestCase):
    def test_the_case_for_changing_nothing_is_from_the_numbers(self):
        keep = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(21, 14)))["keep_it_up"]
        self.assertEqual(keep["text"], "Its rule has not changed in 23 bets; changing it now restarts the record. "
                                       "The fastest way to learn if this is real is more bets on the same rule.")
        self.assertEqual(keep["need_measured"], 129)
        self.assertIn("The referee needs 150 bets with a measurable closing price", keep["points"][0])
        self.assertIn("21 have one", keep["points"][0])
        self.assertIn("about 129 more days", keep["points"][1])

    def test_a_later_version_says_so(self):
        keep = A.build_report(dog(version_no=3), ROWS, now=NOW)["keep_it_up"]
        self.assertIn("This is version 3; earlier versions keep their own records.", keep["points"])

    def test_with_the_referees_sample_in_hand_it_says_the_referee_has_spoken(self):
        keep = A.build_report(dog(), ROWS, now=NOW, book=clv_book(clv_pairs(160, 160)))["keep_it_up"]
        self.assertEqual(keep["need_measured"], 0)
        self.assertIn("has spoken: beating the close", keep["points"][0])


def counts_by_ceiling(spec):
    """A fake of today's board: more candidates as the price ceiling and the daily limit rise."""
    top = spec["price_max"]
    return {"games": 12, "candidates": 2 + max(0, (top - 150) // 25) + (spec["max_bets_per_day"] - 2), "with_candidate": 2,
            "failed": {}, "failed_total": 10}


class Expand(unittest.TestCase):
    def report(self, **kw):
        return A.build_report(dog(), ROWS, now=NOW, **kw)

    def test_only_moves_that_widen_what_has_worked_are_offered(self):
        ids = [i["id"] for i in self.report()["expand"]["items"]]
        self.assertEqual(ids, ["widen_band:up", "widen_band:down", "more_bets", "spin_off"])
        self.assertFalse([i for i in ids if i.startswith(("add_sport", "add_market"))])

    def test_each_idea_says_which_slice_backs_it_and_that_a_change_restarts_the_record(self):
        out = self.report()["expand"]
        first = out["items"][0]
        self.assertEqual((first["supports"], first["text"]), (["band:underdogs"], "Price range: -120 to +150 becomes -120 to +200."))
        self.assertIn("10-4", first["because"])
        self.assertEqual(first["how"], A.HOW)
        self.assertIn("record from zero", out["note"])
        self.assertTrue(out["items"][0]["how"].endswith("nothing changes until you press Apply."))

    def test_today_counts_come_from_the_board_and_order_the_ideas(self):
        out = self.report(board_fn=counts_by_ceiling)["expand"]["items"]
        by = {i["id"]: i for i in out}
        self.assertEqual(by["widen_band:up"]["today"], {"before": 2, "after": 4})
        self.assertEqual(by["more_bets"]["today"], {"before": 2, "after": 3})
        self.assertEqual(by["widen_band:down"]["today"], {"before": 2, "after": 2})
        self.assertEqual(by["widen_band:up"]["today_text"], "On today's board it would have 4 candidates instead of 2.")
        self.assertEqual([i["id"] for i in out][:3], ["widen_band:up", "more_bets", "widen_band:down"])      # most added first
        self.assertIsNone(by["spin_off"]["today"])

    def test_without_a_board_the_counts_are_absent_not_guessed(self):
        self.assertTrue(all(i["today"] is None for i in self.report()["expand"]["items"]))
        self.assertTrue(all(i["today"] is None for i in self.report(board_fn=lambda spec: None)["expand"]["items"]))

    def test_the_spin_off_is_the_existing_copy_flow(self):
        spin = self.report()["expand"]["items"][-1]
        self.assertEqual((spin["id"], spin["href"]), ("spin_off", f"build-a-hound.html?from={HID}"))
        self.assertIn("left as they are", spin["how"])

    def test_a_losing_hound_gets_no_ideas_and_no_spin_off(self):
        plan = [("away", 130, "LOSS")] * 8 + [("away", 130, "WIN")] * 2
        out = A.build_report(dog(), rows_of(plan), now=NOW)["expand"]
        self.assertEqual(out["items"], [])

    def test_a_move_at_minus_200_is_never_offered_even_if_the_validator_waved_it_through(self):
        spec = dict(SPEC)

        def make(s):
            s = dict(s)
            s["price_min"] = -200
            return {"spec": s, "label": "Price range", "old_text": "x", "new_text": "y", "id": "widen_band"}
        bad = {"cid": "widen_band:down", "id": "widen_band", "family": "band", "build": make, "text": "x", "why": "x"}
        with mock.patch.object(retune, "loosening_menu", lambda s: [bad]), \
                mock.patch.object(A.user_spec, "validate_spec", lambda raw, **kw: raw):
            self.assertIsNone(A._entry_is_safe(spec, bad))
            out = A.build_report(dog(), ROWS, now=NOW)["expand"]["items"]
        self.assertEqual(out, [])

    def test_a_move_the_validator_refuses_is_never_offered(self):
        def make(s):
            s = dict(s)
            s["price_min"] = -200
            return {"spec": s, "label": "Price range", "old_text": "x", "new_text": "y", "id": "widen_band"}
        bad = {"cid": "widen_band:down", "id": "widen_band", "family": "band", "build": make, "text": "x", "why": "x"}
        self.assertIsNone(A._entry_is_safe(SPEC, bad))                      # the real validate_spec raises on -200
        self.assertFalse(A._prices_ok(dict(SPEC, price_min=-200)))
        self.assertTrue(A._prices_ok(dict(SPEC, price_min=-199)))

    def test_every_offered_move_applies_to_a_spec_that_validates_inside_the_cap(self):
        menu = {e["cid"]: e for e in retune.loosening_menu(SPEC)}
        for item in self.report()["expand"]["items"]:
            if item["id"] == "spin_off":
                continue
            change = menu[item["id"]]["build"](dict(SPEC))
            valid = user_spec.validate_spec(change["spec"], taken_names=())
            self.assertGreater(valid["price_min"], user_spec.MAX_FAVOURITE_PRICE)
            self.assertLessEqual(valid["price_max"], retune.BAND_LONG_CAP)


class Picks(unittest.TestCase):
    def rows_with_open(self):
        rows = rows_of(PLAN[:5])
        rows += ticket(HID, day=40, result=None, side="home", price=-115, start_hours_ago=2, now=NOW)
        rows += ticket(HID, day=41, result=None, side="away", price=130, start_hours_ago=-3, now=NOW)
        return rows

    def test_open_tickets_come_first_then_settled_newest_first(self):
        out = A.build_report(dog(), self.rows_with_open(), now=NOW)
        picks = out["picks"]
        self.assertEqual([p["result"] for p in picks[:2]], ["open", "open"])
        self.assertEqual([p["status"] for p in picks[:2]], ["OPEN", "OPEN"])
        settled_days = [p["date"] for p in picks[2:]]
        self.assertEqual(settled_days, sorted(settled_days, reverse=True))
        self.assertEqual(len(picks), 7)
        self.assertEqual((out["hound"]["settled"], out["hound"]["open"]), (5, 2))
        first = picks[2]
        for key in ("bet_id", "date", "game", "market", "selection", "price", "price_average", "book", "units", "reason", "clv", "grades",
                    "hindsight", "start_utc", "status"):
            self.assertIn(key, first)
        self.assertEqual(first["market"], "moneyline")

    def test_grades_are_attached_by_ticket_key_or_ledger_id_and_absent_means_none(self):
        bets = rites.forward_bets(HID, ROWS)
        last = sorted(bets, key=A._order_key)[-1]
        grade = {"value": {"score": 71, "label": "Fair", "reason": "r"}, "confidence": {"score": 60}, "clv": {"score": None}}
        out = A.build_report(dog(), ROWS, now=NOW, grades={last.bet_id: grade})
        self.assertEqual(out["picks"][0]["grades"], grade)
        self.assertTrue(all(p["grades"] is None for p in out["picks"][1:]))
        key = out["picks"][0]["bet_id"]
        again = A.build_report(dog(), ROWS, now=NOW, grades={key: grade})
        self.assertEqual(again["picks"][0]["grades"], grade)
        self.assertTrue(all(p["grades"] is None for p in A.build_report(dog(), ROWS, now=NOW)["picks"]))

    def test_hindsight_is_short_labelled_and_never_banned(self):
        base = A.build_report(dog(), ROWS, now=NOW)
        keys = [p["bet_id"] for p in base["picks"]]
        reviews = {keys[0]: {"lesson": "The bullpen decided it late. " * 20, "luck_vs_process": "mixed", "grounded": True},
                   keys[1]: {"lesson": "The pitcher had the edge all night."},
                   keys[2]: {"what_happened": "Won on a late run.", "luck_vs_process": "mostly_luck"}}
        out = A.build_report(dog(), ROWS, now=NOW, postmortems=reviews)
        h0 = out["picks"][0]["hindsight"]
        self.assertEqual(h0["label"], "Hindsight review")
        self.assertLessEqual(len(h0["text"]), A.HINDSIGHT_MAX_CHARS + 3)
        self.assertEqual(h0["luck"], "A mix of process and luck")
        self.assertIsNone(out["picks"][1]["hindsight"])                      # 'edge' is in the review: left off
        self.assertEqual(out["picks"][2]["hindsight"]["text"], "Won on a late run.")
        self.assertIn("not what the hound", out["hindsight_note"])

    def test_the_teaser_carries_no_hindsight_and_no_paid_section(self):
        base = A.build_report(dog(), ROWS, now=NOW)
        reviews = {base["picks"][0]["bet_id"]: {"lesson": "A lesson."}}
        asked = []
        out = A.build_report(dog(), ROWS, now=NOW, postmortems=reviews, full=False, coach_fn=lambda *a: asked.append(a) or {})
        self.assertEqual(out["tier"], "teaser")
        self.assertIsNone(out["picks"][0]["hindsight"])
        self.assertEqual(out["locked"], ["drivers", "keep_it_up", "expand", "coach_read"])
        for key in out["locked"]:
            self.assertNotIn(key, out)
        self.assertNotIn("hindsight_note", out)
        self.assertEqual(asked, [])
        self.assertEqual(out["upgrade"]["feature"], "analyze")

    def test_a_long_record_is_cut_and_counted(self):
        with mock.patch.object(A, "MAX_PICKS", 5):
            out = A.build_report(dog(), ROWS, now=NOW)
        self.assertEqual((len(out["picks"]), out["picks_more"]), (5, 18))

    def test_the_closing_line_of_a_ticket_comes_from_the_cached_book(self):
        bets = rites.forward_bets(HID, ROWS)
        teams = A._teams_by_bet(ROWS)
        target = sorted(bets, key=A._order_key)[-1]
        row = stats.bet_row(target, teams.get(target.bet_id))
        row.clv_pts = 1.25
        book = types.SimpleNamespace(clv_points=[], bets=[row])
        out = A.build_report(dog(), ROWS, now=NOW, book=book)
        self.assertEqual(out["picks"][0]["clv"], {"pts": 1.25, "beat": True})
        self.assertIsNone(out["picks"][1]["clv"])


def good_text(facts):
    h = facts["hot_hand"]
    return (f"HOUND is {facts['record']['wins']}-{facts['record']['losses']} on paper and the prices expected about {h['expected_w']} wins, "
            f"so the run is real in the record. It is too early to call, because a record this good turns up about 1 time in {h['one_in']} "
            f"by luck alone. The closing line is the better sign to watch, and {h['clv_measured']} measured bets is not enough yet. "
            "Changing the rule starts a fresh record, so more bets on the same rule teach the most.")


def adapter_replying(make):
    return FakeAdapter(lambda facts: {"text": make(facts)})


class TheCoachsRead(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = A._CoachCache()
        self.facts = A.coach_facts(*self._parts())

    def _parts(self):
        rep = A.build_report(dog(), ROWS, now=NOW)
        return rep["record"], rep["hot_hand"], rep["drivers"], rep["expand"], rep["keep_it_up"]

    def ask(self, adapter, **kw):
        router = real_router(self._tmp.name, adapter, **kw)
        return A.coach_read(self.facts, ("u", 1, 23), router=router, cache=self.cache)

    def test_a_vetted_reply_is_used_and_the_hound_is_named_by_the_code(self):
        adapter = adapter_replying(good_text)
        out = self.ask(adapter)
        self.assertEqual((out["source"], out["status"]), ("ai", "ok"))
        self.assertEqual(len(adapter.calls), 1)
        sent = json.loads(adapter.calls[0]["user"])
        self.assertNotIn("DRAKEO", adapter.calls[0]["user"])                  # no name, no owner, no bet id goes to the model
        self.assertEqual(sent["record"]["wins"], 16)
        rep = A.build_report(dog(), ROWS, now=NOW, coach_fn=lambda facts, key: out)
        self.assertTrue(rep["coach_read"]["text"].startswith("DRAKEO is 16-7 on paper"))
        self.assertNotIn(A.PLACEHOLDER, rep["coach_read"]["text"])
        self.assertEqual(rep["coach_read"]["source"], "ai")

    def test_a_reply_with_an_invented_number_is_dropped_for_the_code_written_read(self):
        adapter = adapter_replying(lambda f: good_text(f).replace("1 time in", "1 time in 777 or"))
        out = self.ask(adapter)
        self.assertEqual((out["source"], out["status"]), ("rules", "dropped"))
        self.assertEqual(len(adapter.calls), 1)                              # asked once, answer refused, fallback used
        self.assertEqual(out["text"], A.code_coach_read(self.facts))

    def test_promises_banned_words_number_words_and_a_missing_caution_are_each_dropped(self):
        base = good_text(self.facts)
        bad = {
            "will win": base + " HOUND will keep winning.",
            "edge": base.replace("run is real", "run is an edge"),
            "profit": base + " That is profit on paper.",
            "number in words": base + " It has won sixteen.",
            "dollar": base + " That is $5.",
            "link": base + " See https://example.com now.",
            "advice": base + " Bet on the underdogs.",
            "no caution": ("HOUND is 16-7 on paper and the prices expected about 10.9 wins. It had a great run. The best slice is the "
                           "underdogs. The prices look fine. Changing the rule starts a fresh record."),
            "too short": "HOUND is 16-7 on paper. It is too early to call.",
        }
        for name, text in bad.items():
            got, problem = A.vet_coach_text(text, self.facts)
            self.assertIsNone(got, name)
            self.assertTrue(problem, name)
        got, problem = A.vet_coach_text(base, self.facts)
        self.assertEqual((got is not None, problem), (True, None))

    def test_dog_becomes_hound(self):
        got, _ = A.vet_coach_text(good_text(self.facts).replace("HOUND is", "That dog is", 1), self.facts)
        self.assertIn("That hound is", got)

    def test_a_capped_month_falls_back_without_a_call(self):
        adapter = adapter_replying(good_text)
        out = self.ask(adapter, cap=0)
        self.assertEqual((out["source"], out["status"]), ("rules", "capped"))
        self.assertEqual(adapter.calls, [])

    def test_a_router_that_says_it_is_over_the_cap_is_never_asked(self):
        class Capped(FakeRouter):
            specs = [types.SimpleNamespace(id="anthropic")]

            def skip_reason(self, spec, est=0.0):
                return "monthly paid cap of $5.00 reached"

            def ask(self, *a, **k):
                raise AssertionError("a capped router must not be asked")
        out = A.coach_read(self.facts, ("u", 1, 23), router=Capped(), cache=self.cache)
        self.assertEqual((out["source"], out["status"]), ("rules", "capped"))

    def test_a_router_that_fails_or_answers_badly_falls_back(self):
        for router in (FakeRouter(raises=RuntimeError("boom sk-ant-secret")), FakeRouter(FakeAnswer(ok=False, output=None, reason="down")),
                       FakeRouter(FakeAnswer(output={"nope": 1}))):
            cache = A._CoachCache()
            out = A.coach_read(self.facts, ("u", 1, 23), router=router, cache=cache)
            self.assertEqual(out["source"], "rules")
            self.assertNotIn("sk-ant", json.dumps(out))

    def test_no_key_no_call(self):
        out = A.coach_read(self.facts, ("u", 9, 9), env={}, cache=self.cache)
        self.assertEqual((out["source"], out["status"]), ("rules", "off"))

    def test_a_second_open_costs_nothing(self):
        adapter = adapter_replying(good_text)
        first = self.ask(adapter)
        second = self.ask(adapter)
        self.assertEqual((first["source"], second["source"]), ("ai", "ai"))
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(self.ask(adapter)["text"], first["text"])
        # a new settled bet is a new key and asks again
        router = real_router(self._tmp.name, adapter)
        A.coach_read(self.facts, ("u", 1, 24), router=router, cache=self.cache)
        self.assertEqual(len(adapter.calls), 2)

    def test_a_fallback_is_remembered_only_for_a_while(self):
        clock = [0.0]
        cache = A._CoachCache(clock=lambda: clock[0], fallback_ttl_s=100)
        adapter = adapter_replying(lambda f: "x")
        router = real_router(self._tmp.name, adapter)
        A.coach_read(self.facts, ("u", 1, 1), router=router, cache=cache)
        A.coach_read(self.facts, ("u", 1, 1), router=router, cache=cache)
        self.assertEqual(len(adapter.calls), 1)                              # the dropped reply is not paid for twice in a window
        clock[0] = 101.0
        A.coach_read(self.facts, ("u", 1, 1), router=router, cache=cache)
        self.assertEqual(len(adapter.calls), 2)

    def test_the_code_written_read_passes_its_own_vet_in_every_state(self):
        for plan, book in ((PLAN, None), (PLAN, clv_book(clv_pairs(21, 14))), (PLAN, clv_book(clv_pairs(160, 160))),
                           (PLAN, clv_book(clv_pairs(160, 0))), ([("away", 130, "LOSS")] * 10 + [("away", 130, "WIN")] * 2, None),
                           ([("away", 130, "WIN"), ("home", -115, "LOSS")], None)):
            rep = A.build_report(dog(), rows_of(plan), now=NOW, book=book)
            facts = A.coach_facts(rep["record"], rep["hot_hand"], rep["drivers"], rep["expand"], rep["keep_it_up"])
            text = A.code_coach_read(facts)
            got, problem = A.vet_coach_text(text, facts)
            self.assertIsNone(problem, text)
        empty = A.build_report(dog(), [], now=NOW)
        facts = A.coach_facts(empty["record"], empty["hot_hand"], empty["drivers"], empty["expand"], empty["keep_it_up"])
        self.assertEqual(A.vet_coach_text(A.code_coach_read(facts), facts)[1], None)

    def test_the_facts_carry_no_name_and_no_free_text(self):
        blob = json.dumps(self.facts)
        self.assertNotIn("DRAKEO", blob)
        self.assertNotIn("u-drakeo", blob)
        self.assertNotIn("Boston", blob)


class TheLoader(RitesCase):
    """``load_report``: the I/O around the pure core, against a temp app database and a temp ledger."""

    def setUp(self):
        super().setUp()
        A.clear_caches()
        self.addCleanup(A.clear_caches)
        self.row = self.dog("Drakeo Pup", sports=["MLB"], markets=["moneyline"], side_rule="underdog", price_min=-120, price_max=150,
                            min_books=3, max_bets_per_day=2)
        write_ledger(self.ledger, rows_of(PLAN, hid=self.row["id"]))
        self.dog_ = common.resolve(self.row["id"])
        self.clock = [0.0]
        self.router = FakeRouter(FakeAnswer(output={"text": good_text_for_fixture()}))
        self.boards = []
        patch = mock.patch.object(retune, "live_board_fn", lambda dog, **kw: (lambda spec: self.boards.append(spec["price_max"]) or counts_by_ceiling(spec)))
        patch.start()
        self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def load(self, **kw):
        kw.setdefault("now", RITES_NOW)
        kw.setdefault("clock", lambda: self.clock[0])
        return A.load_report(self.dog_, **kw)

    def test_a_teaser_needs_no_paid_work(self):
        asked = FakeRouter(raises=AssertionError("a teaser must not ask the model"))
        out = self.load(full=False, router=asked)
        self.assertEqual((out["tier"], out["hound"]["name"], out["record"]["wins"]), ("teaser", "Drakeo Pup", 16))
        self.assertEqual(out["locked"], A.LOCKED)
        self.assertEqual(asked.calls, [])
        self.assertEqual(self.boards, [])
        self.assertTrue(all(set(p["grades"]) == {"value", "confidence", "clv"} for p in out["picks"]), "the teaser carries the meters too")

    def test_a_full_report_asks_the_board_and_the_coach_once(self):
        out = self.load(full=True, owner=True, router=self.router)
        self.assertEqual((out["tier"], out["coach_read"]["source"]), ("full", "ai"))
        self.assertTrue(out["coach_read"]["text"].startswith("Drakeo Pup is 16-7"))
        self.assertTrue(self.boards)
        self.assertTrue(any(i["today"] for i in out["expand"]["items"]))
        self.assertEqual(len(self.router.calls), 1)

    def test_a_repeat_open_reads_nothing_again(self):
        reads = []
        real = A.rites.read_rows
        with mock.patch.object(A.rites, "read_rows", lambda *a, **k: reads.append(1) or real(*a, **k)):
            self.load(full=True, owner=True, router=self.router)
            self.load(full=True, owner=True, router=self.router)
            self.load(full=False)
            self.load(full=False)
            self.assertEqual(len(reads), 2)                                 # once per tier, not once per open
            self.clock[0] += A.REPORT_TTL_S + 1                             # the report is rebuilt, the coach's read is not re-asked
            self.load(full=True, owner=True, router=self.router)
        self.assertEqual(len(reads), 3)
        self.assertEqual(len(self.router.calls), 1)

    def test_today_counts_are_kept_for_a_while(self):
        self.load(full=True, owner=True, router=self.router)
        first = len(self.boards)
        self.clock[0] += A.REPORT_TTL_S + 1
        self.load(full=True, owner=True, router=self.router)
        self.assertEqual(len(self.boards), first)
        self.clock[0] += A.BOARD_TTL_S + 1
        self.load(full=True, owner=True, router=self.router)
        self.assertGreater(len(self.boards), first)

    def test_a_teaser_is_not_served_as_the_full_report_and_back(self):
        full = self.load(full=True, owner=True, router=self.router)
        teaser = self.load(full=False, owner=True)
        self.assertEqual((full["tier"], teaser["tier"]), ("full", "teaser"))
        self.assertNotIn("drivers", teaser)
        self.assertIn("member plan", teaser["upgrade"]["line"])
        visitor = self.load(full=False, owner=False)
        self.assertIn("owner", visitor["upgrade"]["line"])
        self.assertNotIn("member plan", visitor["upgrade"]["line"])

    def test_a_capped_coach_leaves_the_code_written_read(self):
        out = self.load(full=True, owner=True, router=FakeRouter(FakeAnswer(ok=False, output=None, reason="monthly paid cap of $5.00 reached")))
        self.assertEqual((out["coach_read"]["source"], out["coach_read"]["status"]), ("rules", "down"))
        self.assertIn("Drakeo Pup is 16-7", out["coach_read"]["text"])

    def test_the_tickets_carry_the_graders_blocks_built_from_the_books_own_rows(self):
        out = self.load(full=False)
        by_first = sorted(out["picks"], key=lambda p: p["date"])
        self.assertEqual(by_first[0]["grades"]["value"]["label"], "Not yet available")      # nothing had settled before the first bet
        last = by_first[-1]["grades"]
        self.assertGreaterEqual(last["value"]["slice"]["n"], pick_grades.MIN_SLICE_BETS)       # the kind of spot it is in had a record by then
        self.assertIsNotNone(last["confidence"]["score"])

    def test_a_grader_that_breaks_costs_the_report_nothing(self):
        def boom(*args, **kwargs):
            raise RuntimeError("grader down")
        with mock.patch("src.hounds.pick_grades.grades_for_page", boom):
            out = self.load(full=False)
        self.assertEqual(len(out["picks"]), 23)
        self.assertTrue(all(p["grades"] is None for p in out["picks"]))

    def test_a_record_still_being_worked_out_is_none_not_a_guess(self):
        with mock.patch.object(common, "hound_data", lambda dog: None):
            self.assertIsNone(self.load(full=False))


class TheReportGradesAreTheTicketsGrades(RitesCase):
    """Owner ask 2026-10-29, "same grades everywhere": a pick reads the same Confidence and Value on its ticket card (GET /hounds/{id}/bets,
    ``user_view.bets_for``) and in the Analyze report. Version 2 of a hound is graded on its WHOLE lineage's record, so its first picks are
    graded against version 1's twelve settled bets; the report used to grade only the rows it was given."""

    def setUp(self):
        super().setUp()
        A.clear_caches()
        self.addCleanup(A.clear_caches)
        spec = dict(sports=["MLB"], markets=["moneyline"], side_rule="underdog", price_min=-120, price_max=150, min_books=3, max_bets_per_day=2)
        self.v1 = self.dog("Drakeo Pup", **spec)
        self.v2 = user_store.create_version(self.v1["id"], spec_dict(name="Drakeo Pup", **dict(spec, price_max=200)), actor="owner:1", reason="widen")
        # version 1: twelve settled bets (8-4 at +130), one a day. Version 2: six settled (3-3), then two still open.
        old = [("away", 130, "WIN" if i % 3 else "LOSS") for i in range(12)]
        new = [("away", 130, "WIN" if i % 2 else "LOSS") for i in range(6)] + [("away", 130, None)] * 2
        rows = []
        for day, (side, price, res) in enumerate(old):
            rows.extend(ticket(self.v1["id"], day=day, result=res, side=side, price=price))
        for day, (side, price, res) in enumerate(new, start=12):
            rows.extend(ticket(self.v2["id"], day=day, result=res, side=side, price=price))
        write_ledger(self.ledger, rows)
        self.dog_ = common.resolve(self.v2["id"])

    def report_grades(self):
        out = A.load_report(self.dog_, full=False, now=RITES_NOW)
        return {p["bet_id"]: p["grades"] for p in out["picks"]}

    def ticket_grades(self):
        body = user_view.bets_for(self.v2["id"], page_size=100)
        return {bet_key(self.v2["id"], types.SimpleNamespace(**item)): item["grades"] for item in body["items"]}

    def test_every_pick_has_the_same_grades_on_its_card_and_in_the_report(self):
        report, tickets = self.report_grades(), self.ticket_grades()
        self.assertEqual(len(tickets), 8)
        self.assertEqual(set(report), set(tickets), "the report lists the same tickets the card list does")
        for key, grades in tickets.items():
            with self.subTest(ticket=key):
                self.assertIsNotNone(report[key])
                self.assertEqual(report[key], grades)

    def test_the_first_picks_of_version_2_are_graded_on_version_1s_record(self):
        report = self.report_grades()
        first = min(self.ticket_pairs(), key=lambda pair: pair[1]["recorded_utc"])
        grades = report[first[0]]
        self.assertEqual(grades["value"]["slice"]["n"], 12, "the twelve settled bets of version 1 are this pick's history")
        self.assertEqual((grades["value"]["slice"]["w"], grades["value"]["slice"]["l"]), (8, 4))
        self.assertNotEqual(grades["value"]["label"], "Not yet available")

    def ticket_pairs(self):
        body = user_view.bets_for(self.v2["id"], page_size=100)
        return [(bet_key(self.v2["id"], types.SimpleNamespace(**item)), item) for item in body["items"]]

    def test_the_open_picks_are_graded_from_everything_that_had_settled_before_them(self):
        report = self.report_grades()
        latest = max(self.ticket_pairs(), key=lambda pair: pair[1]["recorded_utc"])
        self.assertEqual(report[latest[0]]["value"]["slice"]["n"], 18)           # version 1's twelve and version 2's six
        self.assertIsNone(report[latest[0]]["clv"], "an open pick has no closing line yet")


def good_text_for_fixture():
    return ("HOUND is 16-7 on paper and the prices expected about 10.9 wins, so the run is real in the record. It is too early to call, "
            "because a record this good turns up about 1 time in 38 by luck alone. The closing line is the better sign to watch, and 0 measured "
            "bets is not enough yet. Changing the rule starts a fresh record, so more bets on the same rule teach the most.")


class HonestyScan(unittest.TestCase):
    """Every sentence the report writes passes the digest's banned list, the owner's 'beta', and never promises."""

    REPORTS = {}

    @classmethod
    def setUpClass(cls):
        for label, plan, book in (("hot", PLAN, None), ("hot_clv", PLAN, clv_book(clv_pairs(21, 14))), ("real", PLAN, clv_book(clv_pairs(160, 160))),
                                  ("luck", PLAN, clv_book(clv_pairs(160, 0))), ("cold", [("away", 130, "LOSS")] * 10 + [("away", 130, "WIN")] * 2, None),
                                  ("empty", [], None)):
            rep = A.build_report(dog(), rows_of(plan), now=NOW, book=book, board_fn=counts_by_ceiling)
            cls.REPORTS[label] = rep
        teaser = A.build_report(dog(), ROWS, now=NOW, full=False)
        cls.REPORTS["teaser"] = A.teaser_variant(teaser, owner=False)
        cls.REPORTS["teaser_owner"] = A.teaser_variant(teaser, owner=True)

    def test_no_banned_word_anywhere_in_any_state(self):
        for label, rep in self.REPORTS.items():
            for text in strings_in(rep):
                self.assertFalse(A.banned(text), (label, text))
                # "moneyline" is a market's name; the digest's list is aimed at the word "money"
                self.assertIsNone(digest.BANNED.search(re.sub(r"money\s?line", " ", text, flags=re.I)), (label, text))
                self.assertIsNone(re.search(r"\bbeta\b", text, re.I), (label, text))

    def test_no_promise_and_no_dog(self):
        promise = re.compile(r"\b(will win|will keep|keep winning|keeps winning|guaranteed|due for|can't lose|sure thing)\b", re.I)
        dogword = re.compile(r"\bdogs?\b", re.I)
        for label, rep in self.REPORTS.items():
            for text in strings_in(rep):
                self.assertIsNone(promise.search(text), (label, text))
                self.assertIsNone(dogword.search(text), (label, text))

    def test_every_number_in_the_hot_hand_text_is_in_the_numbers_beside_it(self):
        for label, rep in self.REPORTS.items():
            hot = rep["hot_hand"]
            allowed = set(re.findall(r"\d+(?:\.\d+)?", json.dumps({k: v for k, v in hot.items() if k != "text"})))
            allowed |= {f"{hot['expected_w']:.1f}", "1"}
            for n in re.findall(r"\d+(?:\.\d+)?", hot["text"]):
                self.assertIn(n, allowed, (label, n, hot["text"]))

    def test_the_teaser_upgrade_line_differs_for_the_owner_and_a_visitor(self):
        self.assertIn("member plan", self.REPORTS["teaser_owner"]["upgrade"]["line"])
        self.assertIn("is for the hound's owner", self.REPORTS["teaser"]["upgrade"]["line"])

    def test_the_report_never_calls_a_hound_with_23_bets_a_hot_hand(self):
        self.assertNotEqual(self.REPORTS["hot"]["hot_hand"]["meter_label"], "Hot hand")
        self.assertNotEqual(self.REPORTS["hot"]["hot_hand"]["verdict"], "real_signal")


if __name__ == "__main__":
    unittest.main()
