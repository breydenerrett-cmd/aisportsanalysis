"""The coach's diagnosis (src/hounds/interact/diagnosis.py): every factor computed on a fixture whose numbers were worked out by hand.

Runs without FastAPI. The fixture is twelve settled bets on twelve consecutive days from Thursday 2026-10-01 (one a day, so the
day of the week of bet ``i`` is easy to read off):

  i   day        side  price  result  start (ET)      books  board move   team on a back-to-back
  0   Thu 10-01  away  +150   LOSS    12:05 early     3      -2.0         no
  1   Fri 10-02  away  +150   LOSS    12:05 early     3      -2.0         yes
  2   Sat 10-03  away  +150   LOSS    19:10 night     3      -2.0         yes
  3   Sun 10-04  away  +150   WIN     16:00 afternoon 3      +1.5         no
  4   Mon 10-05  away  -110   LOSS    16:00           6      -2.0         no
  5   Tue 10-06  home  +120   WIN     16:00           6      +1.5         no
  6   Wed 10-07  home  -120   WIN     16:00           6      +0.2         no
  7   Thu 10-08  home  -120   WIN     16:00           6      (none)       no
  8   Fri 10-09  home  +105   LOSS    19:05 night     9      (none)       no
  9   Sat 10-10  home  -150   WIN     16:00           9      (none)       no
  10  Sun 10-11  away  +200   LOSS    19:05 night     9      -2.0         yes
  11  Mon 10-12  home  -130   PUSH    16:00           9      (none)       no

A WIN at +150 pays 1.5u, +120 pays 1.2u, -120 pays 0.8333u, -150 pays 0.6667u, +105 would pay 1.05u; a LOSS is -1u; a push 0u.
"""

from __future__ import annotations

import json
import re
import unittest

from src.hounds.interact import diagnosis as D, rites, training
from tests._hounds_rites_fixtures import rows_for, ticket
from tests._hounds_user_fixtures import spec_dict

HID = "h-diag"
ROWS_SPEC = [  # (day, side, price, result, start_hour_utc_minute, books)
    (0, "away", 150, "LOSS", "16:05", 3), (1, "away", 150, "LOSS", "16:05", 3), (2, "away", 150, "LOSS", "23:10", 3),
    (3, "away", 150, "WIN", "20:00", 3), (4, "away", -110, "LOSS", "20:00", 6), (5, "home", 120, "WIN", "20:00", 6),
    (6, "home", -120, "WIN", "20:00", 6), (7, "home", -120, "WIN", "20:00", 6), (8, "home", 105, "LOSS", "23:05", 9),
    (9, "home", -150, "WIN", "20:00", 9), (10, "away", 200, "LOSS", "23:05", 9), (11, "home", -130, "PUSH", "20:00", 9)]
B2B_DAYS = {"2026-10-02", "2026-10-03", "2026-10-11"}          # bets 1, 2 and 10
MOVES = {0: -2.0, 1: -2.0, 2: -2.0, 3: 1.5, 4: -2.0, 5: 1.5, 6: 0.2, 10: -2.0}    # by bet index


def build(spec_rows=ROWS_SPEC):
    rows, ids = [], []
    for day, side, price, result, hhmm, books in spec_rows:
        pair = ticket(HID, day=day, result=result, side=side, price=price)
        bet = pair[0]
        stamp = f"{bet['slate_date']}T{hhmm}:00Z"
        bet.update(start_utc=stamp, commence_time=stamp, book_count=books, n_books=books)
        rows.extend(pair)
        ids.append(bet["bet_id"])
    return rows, ids


def context(ids):
    by_id = {ids[i]: pts for i, pts in MOVES.items()}
    return D.Context(rest_days=lambda sport, team, slate, lock: 0 if slate in B2B_DAYS else 2,
                     board_moves=lambda bets: {b.bet_id: by_id[b.bet_id] for b in bets if b.bet_id in by_id})


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.ids = build()
        cls.bets = rites.forward_bets(HID, cls.rows)
        cls.spec = spec_dict(name="Diag Pup", sports=["MLB"])
        cls.table = D.diagnose(cls.bets, cls.spec, rows=cls.rows, context=context(cls.ids))
        cls.by = D.by_id(cls.table)

    def check(self, fid, record, units):
        w, l = record[0], record[1]
        p = record[2] if len(record) > 2 else 0
        f = self.by[fid]
        self.assertEqual((f["wins"], f["losses"], f["pushes"], f["n"]), (w, l, p, w + l + p), fid)
        self.assertAlmostEqual(f["units"], units, places=2, msg=fid)
        return f


class EveryFactorOnHandCheckedNumbers(Fixture):
    def test_the_whole_record(self):
        self.assertEqual(self.table["settled"], 12)
        o = self.table["overall"]
        self.assertEqual((o["wins"], o["losses"], o["pushes"]), (5, 6, 1))
        self.assertAlmostEqual(o["units"], -0.97, places=2)        # -3.5 away + 2.5333 home

    def test_price_bands(self):
        self.check("band:underdogs", (2, 3), -0.30)                # +150 x4 (L L L W) and +120 (W): -3 + 1.5 + 1.2
        self.check("band:long_shots", (0, 1), -1.00)               # +200
        self.check("band:near_even", (0, 2), -2.00)                # -110 and +105, both lost
        self.check("band:favourites", (3, 0, 1), 2.33)             # -120 -120 -150 and the -130 push: 0.8333 * 2 + 0.6667
        self.assertNotIn("band:short_favourites", self.by)         # no bet at -151 or longer: no row, never an empty one

    def test_favourite_or_underdog(self):
        self.check("role:favourite", (3, 1, 1), 1.33)              # every price below zero: -110 L, -120 W, -120 W, -150 W, -130 P
        self.check("role:underdog", (2, 5), -2.30)                 # 7 bets: +150 x4, +120, +105, +200

    def test_home_and_away(self):
        self.check("venue:away", (1, 5), -3.50)
        self.check("venue:home", (4, 1, 1), 2.53)

    def test_sport_and_market(self):
        self.check("sport:MLB", (5, 6, 1), -0.97)
        self.check("market:moneyline", (5, 6, 1), -0.97)

    def test_a_cut_that_holds_every_bet_is_the_whole_record_again_and_is_never_a_reason(self):
        for fid in ("sport:MLB", "market:moneyline", "books:mid" if False else "sport:MLB"):
            f = self.by[fid]
            self.assertEqual((f["kind"], f["direction"], f["tone"]), ("whole", "even", "ok"), fid)
            self.assertNotIn(fid, self.table["ranked"])
        self.assertIn("MLB bets: 5-6-1", self.by["sport:MLB"]["line"], "it is still shown, as a real check")

    def test_day_of_the_week_from_the_slate_day(self):
        self.check("dow:6", (1, 1), 0.50)                          # Sunday: bet 3 won +1.5, bet 10 lost
        self.check("dow:5", (1, 1), -0.33)                         # Saturday: bet 2 lost, bet 9 won +0.6667
        self.check("dow:3", (1, 1), -0.17)                         # Thursday: bet 0 lost, bet 7 won +0.8333
        self.assertEqual(sum(self.by[f"dow:{d}"]["n"] for d in range(7) if f"dow:{d}" in self.by), 12)

    def test_slate_time_in_eastern(self):
        self.check("slate:early", (0, 2), -2.00)                   # 16:05Z is 12:05 pm EDT
        self.check("slate:night", (0, 3), -3.00)                   # 23:10Z and 23:05Z are 7 pm EDT
        self.check("slate:afternoon", (5, 1, 1), 4.03)             # 20:00Z is 4 pm EDT

    def test_rest_and_back_to_backs(self):
        self.check("rest:b2b", (0, 3), -3.00)                      # bets 1, 2, 10
        self.check("rest:rested", (5, 3, 1), 2.03)
        self.assertEqual(self.table["meta"]["rest_known"], 12)

    def test_line_movement_against_the_pick(self):
        self.check("move:against", (0, 5), -5.00)                  # bets 0, 1, 2, 4, 10 (-2.0 points each)
        self.check("move:with", (2, 0), 2.70)                      # bets 3 and 5 (+1.5 points)
        f = self.check("move:flat", (1, 0), 0.83)                  # bet 6 moved 0.2 points: under the 1-point line, so flat
        self.assertEqual(f["level"], "too_few")
        self.assertEqual(self.table["meta"]["move_known"], 8)
        self.assertEqual(f["note"], "closing odds for 8 of 12")

    def test_how_often_the_board_moved_against_the_pick(self):
        f = self.by["move:share"]
        self.assertEqual((f["kind"], f["against"], f["measured"]), ("context", 5, 8))
        self.assertEqual(f["line"], "Board moved against 5 of 8 measured picks (63%)")        # 5 of 8 is 62.5%, rounded half up
        self.assertEqual(f["tone"], "soft")
        self.assertNotIn("move:share", self.table["ranked"])

    def test_each_rule_of_a_custom_rules_hound_is_a_cut_that_says_how_much_of_the_record_it_is(self):
        from src.hounds import user_spec
        spec = user_spec.validate_spec({"version": 2, "name": "Two Rules", "rules": [
            {"sports": ["MLB"], "markets": ["moneyline"], "side": "either"},
            {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 300}]})
        rows = (rows_for("h-r", [(6, dict(result="LOSS", rule_index=0, side="away", price=130))])
                + rows_for("h-r", [(4, dict(result="WIN", rule_index=1, side="home", price=130))]))
        bets = rites.forward_bets("h-r", rows)
        table = D.diagnose(bets, spec, rows=rows, rule_index=training.rule_index_of(rows, "h-r"))
        by = D.by_id(table)
        self.assertEqual((by["rule:0"]["wins"], by["rule:0"]["losses"]), (0, 6))
        self.assertAlmostEqual(by["rule:0"]["units"], -6.0, places=2)
        self.assertAlmostEqual(by["rule:1"]["units"], 5.2, places=2)
        self.assertEqual(by["rule:0"]["label"], "Rule 1")
        self.assertEqual(by["rule:0"]["line"], "Rule 1: 0-6, -6.0u (of -0.8u in all)")
        self.assertIn("rule:0", table["ranked"])

    def test_books_quoting_at_bet_time(self):
        self.check("books:few", (1, 3), -1.50)
        self.check("books:mid", (3, 1), 1.87)
        self.check("books:many", (1, 2, 1), -1.33)

    def test_betting_days(self):
        a = self.by["activity:days"]
        self.assertEqual((a["days_bet"], a["days_span"], a["days_idle"], a["days_at_limit"]), (12, 12, 0, 0))
        self.assertFalse(a["passes_recorded"])
        self.assertEqual(a["line"], "Bet on every one of 12 days")

    def test_the_daily_limit_cut_only_exists_when_the_limit_was_hit(self):
        # two bets on one day with a limit of 2: the day it stopped itself
        spec = spec_dict(name="Cap Pup", sports=["MLB"], max_bets_per_day=2)
        rows = []
        for day, res in ((0, "LOSS"), (0, "LOSS"), (1, "WIN"), (2, "WIN"), (3, "LOSS")):
            rows += ticket("h-cap", day=day, result=res, side="home", price=110)
        table = D.diagnose(rites.forward_bets("h-cap", rows), spec, rows=rows)
        cap = D.by_id(table)["cap:at_limit"]
        self.assertEqual((cap["wins"], cap["losses"], cap["n"]), (0, 2, 2))
        self.assertEqual(D.by_id(table)["activity:days"]["days_at_limit"], 1)

    def test_losing_runs(self):
        s = self.by["streak:losing_runs"]
        self.assertEqual((s["streak"]["longest"], s["streak"]["long_runs"], s["streak"]["n"]), (3, 1, 11))   # L L L W L W W W L W L (the push is not a result)
        self.assertEqual((s["wins"], s["losses"], s["n"]), (0, 3, 3))
        self.assertAlmostEqual(s["units"], -3.00, places=2)
        self.assertGreater(s["streak"]["chance"], 0.0)
        self.assertLessEqual(s["streak"]["chance"], 1.0)

    def test_the_streak_chance_is_the_same_every_read(self):
        again = D.diagnose(self.bets, self.spec, rows=self.rows, context=context(self.ids))
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.table, sort_keys=True))

    def test_a_pair_that_went_wrong_together_is_listed_and_one_that_adds_nothing_is_not(self):
        away_dog = self.by["combo:venue:away+role:underdog"]
        self.assertEqual((away_dog["wins"], away_dog["losses"], away_dog["n"]), (1, 4, 5))       # bets 0, 1, 2, 3, 10
        self.assertAlmostEqual(away_dog["units"], -2.50, places=2)
        self.assertEqual(away_dog["level"], "low")                                                 # a pair is never rated above medium
        # sport:MLB + venue:away holds exactly the bets of venue:away, so it says nothing new
        self.assertNotIn("combo:sport:MLB+venue:away", self.by)
        self.assertTrue(all(f["units"] < 0 for f in self.table["rows"] if f["kind"] == "combo"))

    def test_the_labels_say_what_the_cut_is_in_plain_words(self):
        self.assertEqual(self.by["combo:venue:away+role:underdog"]["label"], "Away-side underdogs")
        self.assertEqual(self.by["band:underdogs"]["label"], "Price +110 to +199")
        self.assertEqual(self.by["rest:b2b"]["label"], "Picked team on a back-to-back")
        self.assertEqual(self.by["dow:6"]["label"], "Sunday slates")
        self.assertEqual(self.by["books:few"]["label"], "Few books quoting (up to 4)")


class SampleSizeOnEveryClaim(Fixture):
    def test_every_cut_carries_its_bets_and_a_level_and_small_ones_say_too_few(self):
        for f in self.table["rows"]:
            if f["kind"] in ("segment", "combo", "streak"):
                self.assertIn(f["level"], ("too_few", "low", "medium", "high"), f["id"])
                self.assertIsInstance(f["n"], int, f["id"])
                if f["n"] < D.MIN_FACTOR_BETS and f["kind"] != "streak":
                    self.assertEqual(f["level"], "too_few", f["id"])
                    self.assertEqual(f["tone"], "thin", f["id"])
                    self.assertEqual(f["level_text"], "too few bets to say", f["id"])
        self.assertEqual(self.by["role:favourite"]["level"], "low")
        self.assertEqual(self.by["venue:away"]["level"], "low")      # 6 bets: big enough to list, too short to be firm

    def test_a_cut_of_five_or_more_is_not_called_too_few_and_four_is(self):
        self.assertEqual(D.level_of(4, 3.0), "too_few")
        self.assertEqual(D.level_of(5, 3.0), "low")
        self.assertEqual(D.level_of(10, 1.2), "medium")
        self.assertEqual(D.level_of(20, 2.1), "high")
        self.assertEqual(D.level_of(20, 2.1, cap="medium"), "medium")
        self.assertEqual(D.level_of(40, None), "low")

    def test_the_table_says_how_many_cuts_were_examined_and_that_it_is_the_past(self):
        meta = self.table["meta"]
        self.assertGreater(meta["cuts_examined"], len([f for f in self.table["rows"] if f["kind"] in ("segment", "combo")]) - 1)
        self.assertIn("by chance", meta["note"])
        self.assertIn("not a forecast", meta["note"])

    def test_no_row_promises_or_forecasts(self):
        words = re.compile(r"\b(will|improve\w*|better|edge|profit\w*|guarantee\w*|expect\w*|should)\b", re.I)
        for f in self.table["rows"]:
            self.assertIsNone(words.search(f["line"]), f["line"])
            self.assertIsNone(words.search(f["label"]), f["label"])

    def test_the_cuts_that_lost_are_ranked_by_size_and_confidence_and_too_small_ones_come_last(self):
        ranked = self.table["ranked"]
        self.assertTrue(ranked)
        table = D.by_id(self.table)
        for fid in ranked:
            self.assertEqual(table[fid]["direction"], "against", fid)
        # the trusted cuts (not too_few) come first, in descending score; then the too-small ones
        levels = [table[f]["level"] == "too_few" for f in ranked]
        self.assertEqual(levels, sorted(levels), "a too-small cut never ranks above a trusted one")
        trusted = [f for f in ranked if table[f]["level"] != "too_few"]
        scores = [D._score(table[f]) for f in trusted]            # noqa: SLF001
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(ranked, D.rank(self.table["rows"]))


class WhatCannotBeAnsweredIsSaidNotGuessed(unittest.TestCase):
    def setUp(self):
        self.rows, self.ids = build()
        self.bets = rites.forward_bets(HID, self.rows)
        self.spec = spec_dict(name="Diag Pup", sports=["MLB"])

    def test_with_no_context_rest_and_movement_are_named_as_not_checked(self):
        table = D.diagnose(self.bets, self.spec, rows=self.rows)
        by = D.by_id(table)
        self.assertEqual(by["rest:none"]["kind"], "unavailable")
        self.assertIn("not checked", by["rest:none"]["line"])
        self.assertEqual(by["move:none"]["kind"], "unavailable")
        self.assertNotIn("rest:b2b", by)
        self.assertNotIn("move:against", by)
        self.assertNotIn("rest:none", table["ranked"])

    def test_a_provider_that_fails_is_a_named_reason_not_a_crash(self):
        def boom(bets):
            raise RuntimeError("store on fire")
        ctx = D.Context(board_moves=boom, rest_days=lambda *a: (_ for _ in ()).throw(ValueError("no schedule")))
        table = D.diagnose(self.bets, self.spec, rows=self.rows, context=ctx)
        by = D.by_id(table)
        self.assertEqual(by["move:none"]["kind"], "unavailable")
        self.assertEqual(by["rest:none"]["kind"], "unavailable")
        self.assertNotIn("store on fire", json.dumps(table), "an exception message never reaches the table")

    def test_a_reason_given_by_the_provider_is_the_one_shown(self):
        ctx = D.Context(reasons={"move": "the closing odds took too long to read"})
        table = D.diagnose(self.bets, self.spec, rows=self.rows, context=ctx)
        self.assertIn("took too long", D.by_id(table)["move:none"]["line"])

    def test_the_consensus_price_is_always_named_as_not_stored_for_a_member_hound(self):
        self.assertEqual(D.by_id(D.diagnose(self.bets, self.spec))["consensus:none"]["kind"], "unavailable")

    def test_no_bets_is_an_empty_table_not_an_error(self):
        table = D.diagnose([], self.spec)
        self.assertEqual((table["settled"], table["ranked"]), (0, []))
        self.assertEqual([f for f in table["rows"] if f["kind"] != "unavailable"], [])

    def test_an_open_ticket_and_a_void_are_not_in_the_table(self):
        rows = list(self.rows) + ticket(HID, day=20, result=None, side="home", price=110) + ticket(HID, day=21, result="VOID", side="home", price=110)
        table = D.diagnose(rites.forward_bets(HID, rows), self.spec, rows=rows)
        self.assertEqual(table["settled"], 12)

    def test_a_rule_is_only_ever_its_position_never_the_owners_label(self):
        spec = spec_dict(name="Rules Pup", sports=["MLB"])
        spec["rules"] = [{"label": "alice@example.com secret system"}]
        self.assertEqual(D._label(spec, "rule", 0), "Rule 1")       # noqa: SLF001
        self.assertEqual(D._label(spec, "rule", 3), "Rule 4")       # noqa: SLF001
        self.assertNotIn("alice", json.dumps(D.compact(D.diagnose(self.bets, self.spec))))


class CompactIsWhatTravelsToTheModel(Fixture):
    def test_it_is_ids_counts_and_units_with_no_bet_id_team_or_name(self):
        text = json.dumps(D.compact(self.table))
        for bet_id in self.ids:
            self.assertNotIn(bet_id, text)
        for forbidden in ("Seattle", "Boston", "Diag Pup", HID, "@"):
            self.assertNotIn(forbidden, text)
        c = D.compact(self.table)
        self.assertEqual(c["settled"], 12)
        self.assertEqual(c["min_bets"], D.MIN_FACTOR_BETS)
        unchecked = [r for r in c["rows"] if r.get("state") == "not_checked"]
        self.assertTrue(unchecked and all("why" in r for r in unchecked))

    def test_the_rules_engine_read_is_the_top_of_the_ranking_in_the_tables_own_words(self):
        reasons = D.rules_reasons(self.table)
        self.assertTrue(1 <= len(reasons) <= 3)
        self.assertEqual(reasons[0]["factors"], [self.table["ranked"][0]])
        for r in reasons:
            f = self.by[r["factors"][0]]
            if f["kind"] != "streak":
                self.assertIn(f["label"], r["text"])


if __name__ == "__main__":
    unittest.main()
