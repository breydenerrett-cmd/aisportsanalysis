"""EXAMPLE ACCOUNTS: the arithmetic, on hand-built picks (src/appstate/
example_accounts.py). Nothing here reads a ledger; the ledger side is
tests/test_example_accounts_reconcile.py.

Every expected dollar figure below is worked by hand in the comment beside it,
so a reader can check the test against a calculator rather than against the
code under test.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest

from src.appstate import card_ledger
from src.appstate import example_accounts as ea
from src.appstate.example_accounts import make_row

START = "2026-09-22"


def flat(amount, balance=10000, acct_id="f"):
    return {"id": acct_id, "label": "flat", "start_balance": balance,
            "staking": {"kind": "flat", "amount": amount}}


def pct(share, balance=10000, acct_id="p"):
    return {"id": acct_id, "label": "pct", "start_balance": balance,
            "staking": {"kind": "percent_of_balance", "pct": share}}


def series(account, rows, waiting=(), view="mlb", start=START):
    return ea.series_for(account, view, rows, waiting, start)


class FlatStaking(unittest.TestCase):
    def test_a_minus_money_win_a_plus_money_win_and_a_loss_on_one_day(self):
        # -150 win = +0.6667u, +150 win = +1.5u, loss = -1u  ->  +1.1667u
        # $100 flat: +$116.67 -> 10,116.67
        rows = [make_row("2026-09-22", "mlb", "WIN", 0.6667),
                make_row("2026-09-22", "mlb", "WIN", 1.5),
                make_row("2026-09-22", "mlb", "LOSS", -1.0)]
        s = series(flat(100), rows)
        day = s["daily"][0]
        self.assertEqual((day["picks"], day["wins"], day["losses"]), (3, 2, 1))
        self.assertAlmostEqual(day["units"], 1.1667, places=4)
        self.assertAlmostEqual(day["result"], 116.67, places=6)
        self.assertAlmostEqual(day["balance"], 10116.67, places=6)
        self.assertAlmostEqual(s["final_balance"], 10116.67, places=6)

    def test_a_win_at_minus_two_hundred_returns_half_the_stake(self):
        s = series(flat(100), [make_row("2026-09-22", "mlb", "WIN", 0.5)])
        self.assertAlmostEqual(s["final_balance"], 10050.0, places=6)

    def test_a_loss_costs_the_stake_and_is_negative(self):
        s = series(flat(250), [make_row("2026-09-22", "mlb", "LOSS", -1.0)])
        self.assertEqual(s["daily"][0]["result"], -250.0)
        self.assertEqual(s["final_balance"], 9750.0)
        self.assertEqual(s["total_units"], -1.0)

    def test_a_push_and_a_void_return_the_stake_so_move_nothing(self):
        rows = [make_row("2026-09-22", "mlb", "PUSH", 0.0),
                make_row("2026-09-22", "mlb", "VOID", None),
                make_row("2026-09-22", "mlb", "VOID", 0.9)]   # a void's units are never read
        s = series(flat(100), rows)
        day = s["daily"][0]
        self.assertEqual((day["picks"], day["pushes"], day["voids"]), (3, 1, 2))
        self.assertEqual(day["result"], 0.0)
        self.assertEqual(s["final_balance"], 10000.0)
        self.assertEqual(s["graded"], 0)          # pushes and voids are not wins or losses

    def test_the_same_dollar_stake_is_used_whatever_the_balance(self):
        rows = [make_row("2026-09-22", "mlb", "LOSS", -1.0),
                make_row("2026-09-23", "mlb", "LOSS", -1.0)]
        s = series(flat(100, balance=1000), rows)
        self.assertEqual([d["stake"] for d in s["daily"]], [100.0, 100.0])
        self.assertEqual(s["final_balance"], 800.0)

    def test_full_precision_is_carried_and_nothing_is_rounded_to_cents(self):
        # $250 x +0.7463u = $186.575 exactly: a half cent. The balance keeps it.
        s = series(flat(250), [make_row("2026-09-22", "mlb", "WIN", 0.7463)])
        self.assertEqual(s["final_balance"], 10186.575)
        self.assertEqual(s["daily"][0]["result"], 186.575)


class PercentStaking(unittest.TestCase):
    def test_every_pick_on_a_day_uses_the_balance_at_the_start_of_that_day(self):
        # Start 10,000, 1% = $100 on EACH of the day's two picks, even though
        # the first one moves the balance: win +1.5u and loss -1u = +0.5u.
        # Day 1: +$50.00 -> 10,050.00. Day 2 stakes 1% of 10,050 = $100.50.
        rows = [make_row("2026-09-22", "mlb", "WIN", 1.5),
                make_row("2026-09-22", "mlb", "LOSS", -1.0),
                make_row("2026-09-23", "mlb", "LOSS", -1.0)]
        s = series(pct(1), rows)
        first, second = s["daily"]
        self.assertEqual(first["stake"], 100.0)
        self.assertEqual(first["result"], 50.0)
        self.assertEqual(first["balance"], 10050.0)
        self.assertEqual(second["stake"], 100.5)
        self.assertEqual(second["result"], -100.5)
        self.assertEqual(second["balance"], 9949.5)

    def test_two_picks_one_day_are_not_compounded_between_themselves(self):
        # Both lose: 2 x $100 = -$200, never 100 then 99 (compounding inside a day).
        rows = [make_row("2026-09-22", "mlb", "LOSS", -1.0),
                make_row("2026-09-22", "mlb", "LOSS", -1.0)]
        self.assertEqual(series(pct(1), rows)["final_balance"], 9800.0)

    def test_an_account_that_reaches_zero_stakes_nothing_and_never_goes_negative(self):
        rows = [make_row("2026-09-22", "mlb", "LOSS", -1.0),
                make_row("2026-09-23", "mlb", "LOSS", -1.0)]
        s = series(pct(100, balance=100), rows)
        self.assertEqual([d["balance"] for d in s["daily"]], [0.0, 0.0])
        self.assertEqual(s["daily"][1]["stake"], 0.0)

    def test_a_percentage_of_a_balance_below_zero_is_never_a_negative_stake(self):
        """Two concurrent picks at 100% of the balance can lose twice the
        balance (the day's stakes are all sized from the start of the day).
        The balance is then negative, and the next day's stake must be zero:
        a negative stake would turn the next loss into a gain."""
        rows = [make_row("2026-09-22", "mlb", "LOSS", -1.0), make_row("2026-09-22", "mlb", "LOSS", -1.0),
                make_row("2026-09-23", "mlb", "LOSS", -1.0)]
        s = series(pct(100, balance=100), rows)
        self.assertEqual([d["balance"] for d in s["daily"]], [-100.0, -100.0])
        self.assertEqual(s["daily"][1]["stake"], 0.0)
        self.assertEqual(s["lowest_balance"], -100.0)


class TheShapeOfASeries(unittest.TestCase):
    def test_an_empty_sport_is_the_start_balance_and_nothing_else(self):
        s = series(flat(100), [], view="nfl")
        self.assertEqual(s["daily"], [])
        self.assertEqual((s["picks"], s["wins"], s["losses"], s["days"]), (0, 0, 0, 0))
        self.assertEqual(s["final_balance"], 10000.0)
        self.assertEqual(s["lowest_balance"], 10000.0)
        self.assertEqual(s["total_units"], 0.0)
        self.assertIsNone(s["return_pct"])

    def test_one_row_per_date_that_has_settled_picks_oldest_first(self):
        rows = [make_row("2026-09-24", "mlb", "WIN", 1.0), make_row("2026-09-22", "mlb", "LOSS", -1.0),
                make_row("2026-09-24", "mlb", "WIN", 1.0)]
        s = series(flat(100), rows)
        self.assertEqual([d["date"] for d in s["daily"]], ["2026-09-22", "2026-09-24"])
        self.assertEqual(s["daily"][1]["picks"], 2)

    def test_picks_before_the_start_date_are_in_no_account(self):
        rows = [make_row("2026-09-21", "mlb", "LOSS", -1.0), make_row("2026-09-22", "mlb", "WIN", 1.0)]
        s = series(flat(100), rows)
        self.assertEqual([d["date"] for d in s["daily"]], ["2026-09-22"])
        self.assertEqual(s["final_balance"], 10100.0)
        self.assertEqual(s["picks"], 1)

    def test_lowest_balance_and_the_day_it_was_reached(self):
        rows = [make_row("2026-09-22", "mlb", "WIN", 1.0), make_row("2026-09-23", "mlb", "LOSS", -1.0),
                make_row("2026-09-24", "mlb", "LOSS", -1.0), make_row("2026-09-25", "mlb", "WIN", 1.0)]
        s = series(flat(100), rows)
        # 10,100 -> 10,000 -> 9,900 -> 10,000
        self.assertEqual(s["lowest_balance"], 9900.0)
        self.assertEqual(s["lowest_date"], "2026-09-24")

    def test_when_it_never_falls_below_the_start_the_lowest_is_the_start(self):
        s = series(flat(100), [make_row("2026-09-22", "mlb", "WIN", 1.0)])
        self.assertEqual((s["lowest_balance"], s["lowest_date"]), (10000.0, START))

    def test_a_pending_day_moves_no_balance_and_a_partial_day_says_so(self):
        # 09-23 has only a pick still waiting: no settled pick, so no row.
        # 09-22 settled one pick and has another waiting: a row, flagged partial.
        rows = [make_row("2026-09-22", "mlb", "WIN", 1.0)]
        s = series(flat(100), rows, waiting={"2026-09-22", "2026-09-23"})
        self.assertEqual([d["date"] for d in s["daily"]], ["2026-09-22"])
        self.assertTrue(s["daily"][0]["partial"])
        self.assertEqual(s["final_balance"], 10100.0)

    def test_postseason_days_are_flagged_and_counted(self):
        rows = [make_row("2026-09-27", "mlb", "WIN", 1.0),
                make_row("2026-10-01", "mlb", "LOSS", -1.0, postseason=True)]
        s = series(flat(100), rows)
        self.assertEqual([d["postseason"] for d in s["daily"]], [False, True])
        self.assertEqual(s["postseason_picks"], 1)
        self.assertEqual(s["final_balance"], 10000.0)       # the postseason pick was bet

    def test_a_percentage_return_needs_thirty_graded_picks(self):
        under = [make_row(f"2026-09-{22 + i // 5:02d}", "mlb", "WIN" if i % 2 else "LOSS",
                          1.0 if i % 2 else -1.0) for i in range(29)]
        self.assertIsNone(series(flat(100), under)["return_pct"])
        self.assertTrue(series(flat(100), under)["small_sample"])
        enough = under + [make_row("2026-09-28", "mlb", "WIN", 1.0)]
        s = series(flat(100), enough)
        self.assertEqual(s["graded"], 30)
        self.assertFalse(s["small_sample"])
        # 15 wins and 15 losses at 1u each: back to 10,000, 0.00%
        self.assertEqual(s["return_pct"], round((s["final_balance"] - 10000) / 100, 2))

    def test_voids_and_pushes_do_not_count_toward_the_thirty(self):
        rows = [make_row("2026-09-22", "mlb", "WIN", 1.0)] + [
            make_row("2026-09-22", "mlb", "VOID", None) for _ in range(40)]
        s = series(flat(100), rows)
        self.assertEqual((s["picks"], s["graded"]), (41, 1))
        self.assertIsNone(s["return_pct"])


# ---------------------------------------------------------------------------
# the whole payload, from injected sources
# ---------------------------------------------------------------------------

def _ref(rows):
    t = ea.tally(rows)
    return {"counted": t, "postseason": None, "combined": None}


def _sources(mlb=(), nfl=(), ufc=(), waiting=None):
    waiting = waiting or {}
    out = {}
    for sport, rows in (("mlb", list(mlb)), ("nfl", list(nfl)), ("ufc", list(ufc))):
        out[sport] = {"rows": rows, "waiting": set(waiting.get(sport, ())), "reference": _ref(rows)}
    return out


def _config(*accounts):
    return {"start_date": START, "accounts": list(accounts) or [flat(100)]}


class ThePayload(unittest.TestCase):
    def setUp(self):
        self.mlb = [make_row("2026-09-22", "mlb", "WIN", 0.9), make_row("2026-09-22", "mlb", "LOSS", -1.0)]
        self.nfl = [make_row("2026-09-27", "nfl", "WIN", 0.9259)]
        self.ufc = [make_row("2026-09-26", "ufc", "WIN", 0.5864), make_row("2026-09-26", "ufc", "VOID", None)]

    def payload(self, **kwargs):
        return ea.build_payload(_config(flat(100), pct(1, acct_id="p1")),
                                _sources(self.mlb, self.nfl, self.ufc), **kwargs)

    def test_it_has_every_view_for_every_account(self):
        p = self.payload()
        self.assertTrue(p["available"])
        self.assertEqual([a["id"] for a in p["accounts"]], ["f", "p1"])
        for account in p["accounts"]:
            self.assertEqual(set(account["series"]), {"mlb", "nfl", "ufc", "all"})
        self.assertEqual(p["start_date"], START)
        self.assertEqual(p["as_of"], "2026-09-27")
        self.assertEqual(p["min_graded_for_percent"], 30)

    def test_all_sports_is_one_account_that_bets_every_pick_of_the_three(self):
        s = self.payload()["accounts"][0]["series"]
        # one day each: 22nd (MLB), 26th (UFC), 27th (NFL); flat $100
        self.assertEqual([d["date"] for d in s["all"]["daily"]], ["2026-09-22", "2026-09-26", "2026-09-27"])
        self.assertEqual(s["all"]["picks"], s["mlb"]["picks"] + s["nfl"]["picks"] + s["ufc"]["picks"])
        self.assertAlmostEqual(s["all"]["final_balance"], 10000 + 100 * (-0.1 + 0.5864 + 0.9259), places=6)
        # NOT three separate $10,000 accounts added up
        self.assertNotAlmostEqual(
            s["all"]["final_balance"],
            s["mlb"]["final_balance"] + s["nfl"]["final_balance"] + s["ufc"]["final_balance"])

    def test_percent_staking_in_all_sports_uses_the_all_sports_balance(self):
        s = self.payload()["accounts"][1]["series"]["all"]
        balance = 10000.0
        for day in s["daily"]:
            self.assertAlmostEqual(day["stake"], balance * 0.01, places=9)
            balance = day["balance"]

    def test_the_reconciliation_is_published_with_the_numbers_on_both_sides(self):
        rec = self.payload()["reconciled"]
        self.assertEqual(set(rec), {"mlb", "nfl", "ufc", "all"})
        self.assertTrue(all(r["ok"] for r in rec.values()))
        self.assertEqual(rec["ufc"]["account"]["voids"], 1)
        self.assertEqual(rec["ufc"]["counted_record"], rec["ufc"]["account"])
        self.assertEqual(rec["all"]["account"]["picks"], 5)

    def test_it_carries_the_three_notes_and_the_postseason_sentence(self):
        p = self.payload()
        self.assertEqual(len(p["notes"]), 3)
        self.assertEqual(p["notes"], list(ea.NOTES))
        self.assertTrue(p["postseason_note"])

    def test_pending_is_passed_through_unchanged(self):
        pending = [{"sport": "mlb", "picks": 8}]
        self.assertEqual(self.payload(pending=pending)["pending"], pending)
        self.assertEqual(self.payload()["pending"], [])

    def test_an_empty_sport_does_not_make_it_unavailable(self):
        p = ea.build_payload(_config(), _sources(self.mlb, [], self.ufc))
        self.assertTrue(p["available"])
        self.assertEqual(p["accounts"][0]["series"]["nfl"]["daily"], [])

    def test_it_is_json_serialisable_and_has_no_decimal_left_in_it(self):
        json.dumps(self.payload())


class ItShowsNothingThatDoesNotReconcile(unittest.TestCase):
    def setUp(self):
        self.rows = [make_row("2026-09-22", "mlb", "WIN", 0.9), make_row("2026-09-22", "mlb", "LOSS", -1.0)]

    def _with_reference(self, **changes):
        sources = _sources(self.rows, [], [])
        ref = dict(sources["mlb"]["reference"]["counted"])
        ref.update(changes)
        sources["mlb"]["reference"] = {"counted": ref, "postseason": None, "combined": None}
        return ea.build_payload(_config(), sources)

    def test_one_more_win_in_the_record_than_in_the_account(self):
        p = self._with_reference(wins=2, picks=3)
        self.assertFalse(p["available"])
        self.assertIn("MLB", p["reason"])
        self.assertNotIn("accounts", p)

    def test_a_difference_of_one_ten_thousandth_of_a_unit_is_enough(self):
        p = self._with_reference(units=round(-0.1 + 0.0001, 4))
        self.assertFalse(p["available"])

    def test_one_void_missing_from_the_account(self):
        p = self._with_reference(voids=1, picks=3)
        self.assertFalse(p["available"])

    def test_one_push_more_in_the_account(self):
        self.rows.append(make_row("2026-09-23", "mlb", "PUSH", 0.0))
        sources = _sources(self.rows, [], [])
        sources["mlb"]["reference"] = {"counted": {"picks": 2, "wins": 1, "losses": 1, "pushes": 0,
                                                   "voids": 0, "units": -0.1},
                                       "postseason": None, "combined": None}
        self.assertFalse(ea.build_payload(_config(), sources)["available"])

    def test_a_missing_sport_is_unavailable_not_assumed_empty(self):
        sources = _sources(self.rows, [], [])
        del sources["ufc"]
        p = ea.build_payload(_config(), sources)
        self.assertFalse(p["available"])
        self.assertIn("UFC", p["reason"])

    def test_the_same_pick_twice_is_unavailable(self):
        twin = make_row("2026-09-22", "mlb", "WIN", 0.9, pick_id="x")
        rows = [twin, dict(twin)]
        rec = ea.reconcile("mlb", rows, _ref(rows))
        self.assertFalse(rec["ok"])
        self.assertTrue(any("more than once" in p for p in rec["problems"]))

    def test_a_postseason_pick_must_match_the_postseason_cohort_not_just_the_total(self):
        rows = [make_row("2026-10-01", "mlb", "LOSS", -1.0, postseason=True)]
        counted_as_regular = {"counted": ea.tally(rows),
                              "postseason": ea.tally([]), "combined": ea.tally(rows)}
        self.assertFalse(ea.reconcile("mlb", rows, counted_as_regular)["ok"])
        right = {"counted": ea.tally([]), "postseason": ea.tally(rows), "combined": ea.tally(rows)}
        self.assertTrue(ea.reconcile("mlb", rows, right)["ok"])

    def test_the_pooled_figure_the_ledger_publishes_is_a_third_check(self):
        rows = [make_row("2026-09-22", "mlb", "WIN", 1.0)]
        ref = {"counted": ea.tally(rows), "postseason": ea.tally([]),
               "combined": dict(ea.tally(rows), units=0.0)}
        rec = ea.reconcile("mlb", rows, ref)
        self.assertFalse(rec["ok"])
        self.assertTrue(any("pooled" in p for p in rec["problems"]))

    def test_a_graded_pick_with_no_units_is_refused(self):
        with self.assertRaises(ea.AccountsError):
            make_row("2026-09-22", "mlb", "WIN", None)

    def test_a_doctored_series_fails_its_own_addition(self):
        p = ea.build_payload(_config(), _sources(self.rows, [], []))
        s = p["accounts"][0]["series"]
        s["mlb"]["daily"][0]["result"] += 1.0
        with self.assertRaises(ea.AccountsError):
            ea._check_series(s)

    def test_all_sports_that_is_not_the_sum_of_the_three_fails(self):
        p = ea.build_payload(_config(), _sources(self.rows, [], []))
        s = p["accounts"][0]["series"]
        s["all"]["wins"] += 1
        with self.assertRaises(ea.AccountsError):
            ea._check_series(s)


class WhichEntriesArePicks(unittest.TestCase):
    """rows_from_v2_days applies the rule record_v2 and effective_record share."""

    def entry(self, **kw):
        base = {"entry_class": "pick", "withdrawn": False, "kind": "game", "game_pk": 1,
                "team_name": "A", "market": "moneyline", "side": "home", "line": None,
                "result": "WIN", "profit_units": 0.5, "postseason": False}
        base.update(kw)
        return base

    def days(self, *entries, date="2026-09-22"):
        return [{"date": date, "graded": list(entries)}]

    def test_a_withdrawn_entry_is_not_a_pick(self):
        rows, _ = ea.rows_from_v2_days(self.days(self.entry(), self.entry(withdrawn=True, game_pk=2)))
        self.assertEqual(len(rows), 1)

    def test_a_fill_is_never_bet(self):
        rows, _ = ea.rows_from_v2_days(self.days(self.entry(), self.entry(entry_class="fill", game_pk=2)))
        self.assertEqual(len(rows), 1)

    def test_an_unresolved_pick_moves_nothing_and_marks_its_day(self):
        rows, waiting = ea.rows_from_v2_days(self.days(self.entry(), self.entry(
            result="UNRESOLVED", profit_units=None, game_pk=2)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(waiting, {"2026-09-22"})

    def test_a_result_the_page_does_not_know_is_refused_not_skipped(self):
        with self.assertRaises(ea.AccountsError):
            ea.rows_from_v2_days(self.days(self.entry(result="MAYBE")))

    def test_the_postseason_flag_the_history_put_on_the_entry_is_carried(self):
        rows, _ = ea.rows_from_v2_days(self.days(self.entry(postseason=True)))
        self.assertTrue(rows[0]["postseason"])

    def test_two_props_on_one_game_are_two_picks_with_two_identities(self):
        rows, _ = ea.rows_from_v2_days(self.days(
            self.entry(kind="prop", player="A", market="batter_hits", side="Over", line=0.5),
            self.entry(kind="prop", player="B", market="batter_hits", side="Over", line=0.5)))
        self.assertEqual(len({r["pick_id"] for r in rows}), 2)

    def test_a_v1_style_day_must_add_up_to_its_own_totals(self):
        good = {"date": "2026-09-27", "wins": 1, "losses": 0, "pushes": 0, "voids": 0, "unresolved": 0,
                "profit_units": 0.9259, "picks": [
                    {"bet": "b", "market": "moneyline", "result": "WIN", "profit_units": 0.9259}]}
        rows, _ = ea.rows_from_v1_days([good], "nfl")
        self.assertEqual(len(rows), 1)
        for change in ({"wins": 2}, {"profit_units": 0.9}, {"voids": 1}):
            with self.subTest(change=change), self.assertRaises(ea.AccountsError):
                ea.rows_from_v1_days([dict(good, **change)], "nfl")

    def test_a_v1_style_day_with_props_and_totals_is_read_kind_by_kind(self):
        day = {"date": "2026-09-27", "wins": 1, "losses": 0, "pushes": 0, "voids": 0, "unresolved": 0,
               "profit_units": 0.5, "picks": [{"bet": "g", "result": "WIN", "profit_units": 0.5}],
               "prop_wins": 0, "prop_losses": 1, "prop_pushes": 0, "prop_voids": 0,
               "prop_profit_units": -1.0,
               "prop_picks": [{"bet": "p", "result": "LOSS", "profit_units": -1.0}],
               "total_wins": 0, "total_losses": 0, "total_voids": 1, "total_profit_units": 0,
               "total_picks": [{"bet": "t", "result": "VOID", "profit_units": 0}]}
        rows, _ = ea.rows_from_v1_days([day], "nfl")
        self.assertEqual(ea.tally(rows), {"picks": 3, "wins": 1, "losses": 1, "pushes": 0,
                                          "voids": 1, "units": -0.5})


class TheConfig(unittest.TestCase):
    def good(self):
        return {"start_date": START, "accounts": [flat(100)]}

    def test_the_tracked_file_is_the_four_default_accounts(self):
        config = ea.load_config()
        self.assertEqual(config["start_date"], "2026-09-22")
        got = {a["id"]: a for a in config["accounts"]}
        self.assertEqual([a["id"] for a in config["accounts"]], ["flat100", "flat250", "pct1", "starter"])
        self.assertEqual(got["flat100"]["label"], "$10,000 account, $100 on every pick")
        self.assertEqual(got["flat250"]["label"], "$10,000 account, $250 on every pick")
        self.assertEqual(got["pct1"]["label"], "$10,000 account, 1% of the balance on every pick")
        self.assertEqual(got["starter"]["label"], "$1,000 account, $10 on every pick")
        self.assertEqual((got["flat100"]["start_balance"], got["flat100"]["staking"]),
                         (10000, {"kind": "flat", "amount": 100}))
        self.assertEqual(got["pct1"]["staking"], {"kind": "percent_of_balance", "pct": 1})
        self.assertEqual((got["starter"]["start_balance"], got["starter"]["staking"]),
                         (1000, {"kind": "flat", "amount": 10}))

    def test_every_way_to_be_wrong_is_a_config_error_never_a_default(self):
        bad = {
            "not an object": [],
            "no start date": {"accounts": [flat(100)]},
            "start date is not a date": {"start_date": "soon", "accounts": [flat(100)]},
            "no accounts": {"start_date": START, "accounts": []},
            "accounts not a list": {"start_date": START, "accounts": {}},
            "duplicate id": {"start_date": START, "accounts": [flat(100), flat(50)]},
            "bad id": {"start_date": START, "accounts": [dict(flat(100), id="Has Space")]},
            "no label": {"start_date": START, "accounts": [dict(flat(100), label="")]},
            "zero balance": {"start_date": START, "accounts": [flat(100, balance=0)]},
            "text balance": {"start_date": START, "accounts": [dict(flat(100), start_balance="10000")]},
            "boolean balance": {"start_date": START, "accounts": [dict(flat(100), start_balance=True)]},
            "unknown staking": {"start_date": START, "accounts": [dict(flat(100), staking={"kind": "kelly"})]},
            "negative stake": {"start_date": START, "accounts": [flat(-5)]},
            "stake above the balance": {"start_date": START, "accounts": [flat(20000)]},
            "percent over a hundred": {"start_date": START, "accounts": [pct(150)]},
            "percent zero": {"start_date": START, "accounts": [pct(0)]},
            "infinite": {"start_date": START, "accounts": [flat(float("inf"), balance=1e12)]},
            "too many": {"start_date": START,
                         "accounts": [flat(1, acct_id=f"a{i}") for i in range(13)]},
        }
        for name, obj in bad.items():
            with self.subTest(case=name), self.assertRaises(ea.ConfigError):
                ea.validate_config(obj)

    def test_a_missing_file_and_a_file_that_is_not_json_are_config_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ea.ConfigError):
                ea.load_config(os.path.join(tmp, "nope.json"))
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            with self.assertRaises(ea.ConfigError):
                ea.load_config(path)

    def test_a_good_config_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ok.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.good(), fh)
            self.assertEqual(ea.load_config(path)["accounts"][0]["id"], "f")


class TheWordsAndTheLedgersWords(unittest.TestCase):
    def test_result_words_are_the_ledgers_own(self):
        self.assertEqual(
            (ea.RESULT_WIN, ea.RESULT_LOSS, ea.RESULT_PUSH, ea.RESULT_VOID, ea.RESULT_UNRESOLVED),
            (card_ledger.RESULT_WIN, card_ledger.RESULT_LOSS, card_ledger.RESULT_PUSH,
             card_ledger.RESULT_VOID, card_ledger.RESULT_UNRESOLVED))

    def test_the_notes_are_the_owners_sentences_and_use_no_em_dash(self):
        self.assertEqual(ea.NOTES[0], "This is a hypothetical account, not a real one. "
                                      "It puts the same stake on every pick at the price we published.")
        self.assertEqual(ea.NOTES[1], "A real account would differ: prices move, sportsbooks limit bets, "
                                      "and nobody bets every pick.")
        self.assertEqual(ea.NOTES[2], "Past results do not predict future results. This is analysis, not advice.")
        for text in ea.NOTES + (ea.POSTSEASON_NOTE, ea.UNAVAILABLE_SENTENCE):
            self.assertNotIn("—", text)
            self.assertNotIn("–", text)

    def test_no_claim_words_in_anything_the_module_says_to_a_reader(self):
        banned = re.compile(r"\b(profit\w*|edge|winning|beat the market|bet check|guarantee\w*)\b", re.I)
        for text in ea.NOTES + (ea.POSTSEASON_NOTE, ea.UNAVAILABLE_SENTENCE):
            self.assertIsNone(banned.search(text), text)

    def test_the_postseason_sentence_says_why_the_total_differs_from_the_counted_record(self):
        self.assertIn("counted record plus the postseason picks", ea.POSTSEASON_NOTE)
        self.assertEqual(ea.POSTSEASON_NOTE.count(". "), 0)      # one sentence


if __name__ == "__main__":
    unittest.main()
