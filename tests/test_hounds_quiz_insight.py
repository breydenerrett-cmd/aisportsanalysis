"""The pre-build check (src/hounds/quiz/insight.py + boardstats.py): deterministic, no model, nothing blocks. No FastAPI needed."""

from __future__ import annotations

import copy
import os
import re
import tempfile
import unittest
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds import user_spec
from src.hounds.interact import drill
from src.hounds.quiz import boardstats, compose, insight
from tests._hounds_user_fixtures import DATE, EVENT, result_row, standard_rows, utc

BANNED = (r"\bbeta\b", r"\bnew\b", r"\bedge\b", r"\block\b", r"\bclv\b", r"nothing cleared the bar", r"\bprofit")
NOW = utc("2026-10-22T12:00:00Z")


def composed(answers):
    return compose.compose(answers, taken_names=())


def board(sport="NHL", market="moneyline", games=20, per_day=6, median=6, top=9, home=None, away=None):
    return {f"{sport}|{market}": {"games": games, "max_per_day": per_day, "books_median": median, "books_max": top,
                                  "prices": {"home": home or {-150: 5, 130: 5}, "away": away or {-130: 5, 150: 5}}}}


def windows(rule_bets=None, **kw):
    b = {}
    for part in kw.pop("boards", [board()]):
        b.update(part)
    return {1: {"bets": 0}, 3: {"bets": 1}, 7: {"bets": 3, "wins": 2, "losses": 1, "pushes": 0, "units": 1.0},
            "rule_bets": {0: 3} if rule_bets is None else rule_bets, "board": b}


def codes(out):
    return [f["code"] for f in out["watch_out"]]


class TheChecks(unittest.TestCase):
    def test_a_style_that_reads_data_the_sport_lacks_is_named_with_a_fitting_style_offered(self):
        res = composed({"sports": ["NHL"], "personality": "stats_nerd", "markets": ["moneyline"]})
        out = insight.analyse(res, {"personality": "stats_nerd"})
        f = [x for x in out["watch_out"] if x["code"] == "personality_data"]
        self.assertEqual(len(f), 1)
        self.assertIn("Stats Nerd", f[0]["text"])
        self.assertEqual(f[0]["fix"]["action"], "set_personality")
        self.assertNotEqual(f[0]["fix"]["personality"], "stats_nerd")
        # on MLB the same style has its data: no finding
        mlb = insight.analyse(composed({"sports": ["MLB"], "personality": "stats_nerd", "markets": ["moneyline"]}), {"personality": "stats_nerd"})
        self.assertNotIn("personality_data", codes(mlb))

    def test_a_market_the_sport_does_not_carry_comes_with_a_fix(self):
        res = {"spec": {"name": "X", "sports": ["TENNIS"], "rules": [], "max_bets_per_day": 2, "stake_units": 1.0},
               "warnings": [{"code": "base_narrowed", "level": "note", "message": "Spreads are not posted for tennis, so Chalk covers NBA only."}]}
        res["spec"]["rules"] = [{"label": "Chalk", "sports": ["NBA"], "markets": ["spread"]}]
        out = insight.analyse(res, {})
        self.assertEqual(codes(out), ["market_not_posted"])
        self.assertEqual(out["watch_out"][0]["fix"]["action"], "set_sports")
        self.assertEqual(out["watch_out"][0]["fix"]["sports"], ["NBA"])
        gone = insight.analyse({"spec": res["spec"], "warnings": [{"code": "market_unavailable", "level": "heads_up", "message": "Totals are not posted."}]}, {})
        self.assertEqual(gone["watch_out"][0]["fix"]["action"], "go_back")

    def test_a_rule_that_never_fired_with_games_on_the_board(self):
        res = composed({"sports": ["NHL"], "personality": "underdog_hunter", "markets": ["moneyline"]})
        out = insight.analyse(res, {}, windows(rule_bets={}))
        self.assertIn("rule_never_fired", codes(out))
        self.assertEqual([f for f in out["watch_out"] if f["code"] == "rule_never_fired"][0]["fix"]["action"], "edit_rules")
        self.assertNotIn("rule_never_fired", codes(insight.analyse(res, {}, windows(rule_bets={0: 2}))))

    def test_min_books_above_what_the_sport_typically_has(self):
        res = composed({"sports": ["NHL"], "personality": "underdog_hunter", "markets": ["moneyline"]})
        need = res["spec"]["rules"][0]["min_books"]
        out = insight.analyse(res, {}, windows(boards=[board(median=need - 1, top=need + 2)]))
        f = [x for x in out["watch_out"] if x["code"] == "min_books_high"]
        self.assertEqual(len(f), 1)
        self.assertIn("skips most games", f[0]["text"])
        never = insight.analyse(res, {}, windows(boards=[board(median=need - 1, top=need - 1)]))
        self.assertIn("can never bet", [x for x in never["watch_out"] if x["code"] == "min_books_high"][0]["text"])
        self.assertNotIn("min_books_high", codes(insight.analyse(res, {}, windows(boards=[board(median=need + 1)]))))

    def test_a_price_band_that_excludes_every_quote_the_sport_offered(self):
        res = composed({"sports": ["NHL"], "personality": "underdog_hunter", "markets": ["moneyline"]})
        high = {400: 4, 450: 2}                                              # a board nobody priced inside +100..+300
        out = insight.analyse(res, {}, windows(boards=[board(home=high, away={-400: 3})]))
        f = [x for x in out["watch_out"] if x["code"] == "price_band_empty"]
        self.assertEqual(len(f), 1)
        self.assertIn("can never bet", f[0]["text"])
        ok = insight.analyse(res, {}, windows(boards=[board(home={120: 3}, away={-130: 3})]))
        self.assertNotIn("price_band_empty", codes(ok))

    def test_totals_priced_near_minus_110_against_a_plus_money_band(self):
        res = composed({"sports": ["NBA"], "personality": "underdog_hunter", "markets": ["total"]})
        rule = res["spec"]["rules"][0]
        if not (rule["price_min"] and rule["price_min"] > 0):
            rule["price_min"], rule["price_max"] = 100, 250                  # the composer softens totals; pin the band this check is about
        out = insight.analyse(res, {}, windows(boards=[board("NBA", "total", home=None)], rule_bets={0: 1}) | {
            "board": board("NBA", "total") | {"NBA|total": {**board("NBA", "total")["NBA|total"], "prices": {"over": {-110: 9}, "under": {-110: 9}}}}})
        f = [x for x in out["watch_out"] if x["code"] == "price_band_empty"]
        self.assertEqual(len(f), 1)
        self.assertIn("-110", f[0]["text"])

    def test_a_catchphrase_blanked_by_a_reserved_word_names_the_word_and_offers_the_edit(self):
        res = composed({"sports": ["MLB"], "personality": "chalk_eater", "tagline": "House always wins"})
        out = insight.analyse(res, {"tagline": "House always wins"})
        f = out["watch_out"][0]
        self.assertEqual(f["code"], "tagline_blank")
        self.assertIn('"house"', f["text"])
        self.assertEqual(f["fix"], {"action": "edit_field", "field": "tagline", "label": "Edit the catchphrase"})

    def test_a_blocked_word_is_never_repeated_back(self):
        word = sorted(user_spec._BLOCK_WORDS)[0]
        res = composed({"sports": ["MLB"], "personality": "chalk_eater", "tagline": f"Big {word} energy"})
        out = insight.analyse(res, {"tagline": f"Big {word} energy"})
        self.assertEqual(out["watch_out"][0]["code"], "tagline_blank")
        self.assertNotIn(word, out["watch_out"][0]["text"].lower())

    def test_a_cap_above_the_most_games_a_day_ever_offered(self):
        res = composed({"sports": ["NHL"], "personality": "underdog_hunter", "markets": ["moneyline"], "bets_per_day": 5})
        out = insight.analyse(res, {}, windows(boards=[board(per_day=3)]))
        f = [x for x in out["watch_out"] if x["code"] == "cap_too_high"]
        self.assertEqual(len(f), 1)
        self.assertIn("5 bets a day", f[0]["text"])
        self.assertIn("only 3 games", f[0]["text"])
        self.assertNotIn("cap_too_high", codes(insight.analyse(res, {}, windows(boards=[board(per_day=8)]))))

    def test_a_sport_out_of_season_is_said_once(self):
        res = composed({"sports": ["MLB"], "personality": "chalk_eater", "markets": ["moneyline", "total"]})
        out = insight.analyse(res, {}, windows(boards=[board("NHL")], rule_bets={}))
        self.assertEqual(codes(out).count("no_games"), 1)
        self.assertIn("out of season", [f for f in out["watch_out"] if f["code"] == "no_games"][0]["text"])

    def test_every_finding_has_a_sentence_and_a_fix_and_the_list_is_capped(self):
        res = composed({"sports": ["NHL"], "personality": "stats_nerd", "markets": ["moneyline", "total"], "bets_per_day": 5,
                        "tagline": "NFL house"})
        out = insight.analyse(res, {"personality": "stats_nerd", "tagline": "NFL house"}, windows(boards=[board(per_day=1, median=1, top=1)], rule_bets={}))
        self.assertGreaterEqual(len(out["watch_out"]), 3)
        self.assertLessEqual(len(out["watch_out"]), insight.MAX_FINDINGS)
        for f in out["watch_out"]:
            self.assertTrue(f["text"].strip().endswith("."), f)
            self.assertIsInstance(f["fix"], dict)
            self.assertIn(f["fix"]["action"], ("set_personality", "set_sports", "edit_field", "edit_rules", "go_back"))
            self.assertTrue(f["fix"]["label"])

    def test_what_it_will_do_is_two_or_three_sentences_and_nothing_blocks(self):
        res = composed({"sports": ["NHL"], "personality": "underdog_hunter", "markets": ["moneyline"]})
        out = insight.analyse(res, {}, windows())
        self.assertIn(len(out["will_do"]), (2, 3))
        self.assertIn("last 7 days", out["will_do"][1])
        self.assertIn("on paper", out["will_do"][1])
        self.assertNotIn("blocked", out)
        none = insight.analyse(res, {}, None)
        self.assertIn("could not replay", none["will_do"][1])
        self.assertFalse(none["replay"])

    def test_all_the_copy_follows_the_member_facing_rules(self):
        res = composed({"sports": ["NHL"], "personality": "stats_nerd", "markets": ["moneyline", "total"], "bets_per_day": 5, "tagline": "NFL house"})
        out = insight.analyse(res, {"personality": "stats_nerd", "tagline": "NFL house"}, windows(boards=[board(per_day=1, median=1, top=1)], rule_bets={}))
        text = " ".join(out["will_do"] + [f["text"] + " " + f["fix"]["label"] for f in out["watch_out"]]).lower()
        for pattern in BANNED:
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_it_is_deterministic(self):
        res = composed({"sports": ["NHL"], "personality": "stats_nerd", "markets": ["moneyline"]})
        w = windows()
        self.assertEqual(insight.analyse(res, {"personality": "stats_nerd"}, copy.deepcopy(w)),
                         insight.analyse(res, {"personality": "stats_nerd"}, copy.deepcopy(w)))


class TheBoardCounts(unittest.TestCase):
    def test_games_a_day_books_and_prices_are_counted_and_in_play_rows_skipped(self):
        stats = boardstats.BoardStats("2026-10-20", "2026-10-20")
        pre = utc("2026-10-20T20:00:00Z")
        rows = [{"market": None, "event_id": "e1", "sport": "nhl", "book": b, "home_price": -120, "away_price": 100,
                 "observed_utc": utc("2026-10-20T18:00:00Z"), "commence_time": pre} for b in ("a", "b", "c")]
        rows.append({"market": None, "event_id": "e1", "sport": "nhl", "book": "late", "home_price": -500, "away_price": 400,
                     "observed_utc": utc("2026-10-20T21:00:00Z"), "commence_time": pre})                   # in play: skipped
        rows.append({"market": "totals", "event_id": "e2", "sport": "nhl", "book": "a", "over_price": -110, "under_price": -110,
                     "observed_utc": utc("2026-10-20T18:00:00Z"), "commence_time": pre})
        stats({"2026-10-20": rows, "2026-10-01": [dict(rows[0], event_id="old")]})                       # outside the window: skipped
        out = stats.summary()
        ml = out["NHL|moneyline"]
        self.assertEqual((ml["games"], ml["max_per_day"], ml["books_median"], ml["books_max"]), (1, 1, 3, 3))
        self.assertEqual(ml["prices"]["home"], {-120: 3})
        self.assertNotIn(-500, ml["prices"]["home"])
        self.assertEqual(out["NHL|total"]["prices"]["over"], {-110: 1})
        self.assertEqual(boardstats.in_band({-110: 4, 130: 2}, 100, 250), 2)
        self.assertEqual(boardstats.in_band({-110: 4}, None, -120), 0)
        self.assertEqual(boardstats.median_price({-110: 3, -105: 1}), -110)


class TheWholeCheck(unittest.TestCase):
    def setUp(self):
        drill.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def inject(self):
        pk = "900001"
        return dict(rows_by_date={DATE: standard_rows()}, mlb_results={pk: result_row(pk, DATE, "BOS", "SEA", 5, 3)},
                    nfl_results=lambda d: {}, game_pk_index={EVENT: {"game_pk": pk}})

    def test_check_replays_once_counts_the_boards_and_reports(self):
        out = insight.check({"sports": ["MLB"], "personality": "underdog_hunter", "markets": ["moneyline"], "price_comfort": "plus"},
                            now=NOW, **self.inject())
        self.assertTrue(out["replay"])
        self.assertTrue(out["paper_only"])
        self.assertIn("1 bet, 1-0", out["will_do"][1])

    def test_a_busy_slot_still_answers_without_the_replay(self):
        self.assertTrue(drill._drill_slot.acquire(blocking=False))
        try:
            out = insight.check({"sports": ["MLB"], "personality": "chalk_eater"}, now=NOW, **self.inject())
        finally:
            drill._drill_slot.release()
        self.assertFalse(out["replay"])
        self.assertIn("could not replay", out["will_do"][1])

    def test_a_gematria_hound_is_checked_without_a_replay(self):
        out = insight.check({"sports": ["MLB"], "personality": "gematria"}, now=NOW, **self.inject())
        self.assertFalse(out["replay"])


if __name__ == "__main__":
    unittest.main()
