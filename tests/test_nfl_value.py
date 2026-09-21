"""NFL_CARD_V2 (src/analysis/nfl_value.py): value lines, not favourites.

Built 2026-09-20 after NFL_CARD_V1 published San Francisco -950. Each test
pins one rule from the pre-registration (docs/PREREG_NFL_CARD_V2.md), plus
the grading and record plumbing V2 needs.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.analysis import nfl_value
from src.appstate import card_ledger
from src.core import odds as odds_math
from src.report import nfl_card as nfl_report

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
KICKOFF = (NOW + timedelta(hours=8)).isoformat().replace("+00:00", "Z")
HOME, AWAY = "Kansas City Chiefs", "Indianapolis Colts"


def _stamp(minutes_ago=0):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _row(book, market, *, minutes_ago=0, kickoff=KICKOFF, **prices):
    row = {"event_id": "ev1", "commence_time": kickoff, "home_team": HOME,
           "away_team": AWAY, "book": book, "market": market,
           "observed_utc": _stamp(minutes_ago), "book_last_update": _stamp(minutes_ago),
           "sport": "nfl"}
    row.update(prices)
    return row


def _totals(book, over, under, total="44.5", **kw):
    return _row(book, "totals", total=total, over_price=over, under_price=under, **kw)


def _spread(book, home_line, home_price, away_price, **kw):
    return _row(book, "spreads", home_line=str(home_line), home_price=home_price,
                away_line=str(-float(home_line)), away_price=away_price, **kw)


def _h2h(book, home, away, **kw):
    return _row(book, None, home_price=home, away_price=away, **kw)


def _market(n, make):
    return [make(f"book{i}") for i in range(n)]


class ValueRules(unittest.TestCase):
    def test_a_price_better_than_the_other_books_is_a_candidate(self):
        rows = _market(6, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)]
        cands = nfl_value.value_candidates(rows, now=NOW)
        over = [c for c in cands if c["book"] == "outlier" and c["side"] == "over"]
        self.assertEqual(len(over), 1)
        self.assertAlmostEqual(over[0]["ev"], 0.5 * 2.10 - 1.0, places=6)

    def test_the_judged_book_is_never_part_of_its_own_consensus(self):
        rows = _market(6, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)]
        over = [c for c in nfl_value.value_candidates(rows, now=NOW)
                if c["book"] == "outlier" and c["side"] == "over"][0]
        # Six symmetric -110/-110 books de-vig to exactly 50%; had the
        # outlier's own +110 been averaged in, the fair price would drift.
        self.assertAlmostEqual(over["fair_probability"], 0.5, places=9)
        self.assertEqual(over["n_other_books"], 6)

    def test_no_price_at_minus_200_or_worse_is_ever_a_candidate(self):
        # Every other book says home is a 75% shot (-300/+300 de-vigs to it);
        # -200 there would be +12.5% "value" -- and is still refused.
        rows = _market(6, lambda b: _h2h(b, -300, 300)) + [_h2h("soft", -200, 180)]
        cands = nfl_value.value_candidates(rows, now=NOW)
        self.assertFalse([c for c in cands if c["side"] == "home"])

    def test_minus_199_is_allowed_through_the_price_rule(self):
        rows = _market(6, lambda b: _h2h(b, -300, 300)) + [_h2h("soft", -199, 180)]
        cands = nfl_value.value_candidates(rows, now=NOW)
        self.assertTrue([c for c in cands if c["side"] == "home" and c["book"] == "soft"])

    def test_a_stale_quote_is_never_judged(self):
        rows = (_market(6, lambda b: _totals(b, -110, -110))
                + [_totals("asleep", 120, -140, minutes_ago=120)])
        cands = nfl_value.value_candidates(rows, now=NOW)
        self.assertFalse([c for c in cands if c["book"] == "asleep"])

    def test_a_line_only_one_book_hangs_is_not_judged_against_other_numbers(self):
        rows = (_market(6, lambda b: _spread(b, -3.0, -110, -110))
                + [_spread("lonely", -3.5, 120, -140)])
        cands = nfl_value.value_candidates(rows, now=NOW)
        self.assertFalse([c for c in cands if c["book"] == "lonely"])

    def test_too_few_other_books_on_the_line_is_not_judged(self):
        rows = _market(4, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)]
        self.assertEqual(nfl_value.value_candidates(rows, now=NOW), [])

    def test_a_started_game_is_never_a_candidate(self):
        past = (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        rows = (_market(6, lambda b: _totals(b, -110, -110, kickoff=past))
                + [_totals("outlier", 110, -130, kickoff=past)])
        self.assertEqual(nfl_value.value_candidates(rows, now=NOW), [])

    def test_only_each_books_latest_quote_counts(self):
        rows = (_market(6, lambda b: _totals(b, -110, -110))
                + [_totals("outlier", 110, -130, minutes_ago=10),
                   _totals("outlier", -110, -110, minutes_ago=1)])
        self.assertEqual(nfl_value.value_candidates(rows, now=NOW), [])


def _by_method(fav, dog, price, side):
    """Independent of nfl_value: (EV, fair) of `price` on `side` ("fav" or
    "dog") against books all quoting fav/dog, under each de-vig method."""
    out = {}
    for method in ("proportional", "shin", "power"):
        fair_fav, fair_dog = odds_math.devig_two_way(fav, dog, method=method)
        fair = fair_dog if side == "dog" else fair_fav
        out[method] = (fair * odds_math.american_to_decimal(price) - 1.0, fair)
    return out


class DevigRobustness(unittest.TestCase):
    """Review finding, 2026-09-21: proportional de-vig leaves too much
    probability on the long shot, so any book a few cents longer on a big
    underdog "cleared" 2% -- replayed over the store, 16 of V2's 17
    candidates were plus-money moneyline dogs, none of which reached 2%
    under power (the best, GB@NYJ +170, was +0.34%). A candidate now has to
    clear under all three methods, and the card shows the most cautious
    one."""

    def test_a_long_shot_dog_that_clears_only_under_proportional_is_not_a_candidate(self):
        ev = _by_method(-320, 260, 290, "dog")
        # The fixture is the case it claims: 4.2% proportional, not 2% elsewhere.
        self.assertGreaterEqual(ev["proportional"][0], nfl_value.MIN_EV)
        self.assertLess(ev["shin"][0], nfl_value.MIN_EV)
        self.assertLess(ev["power"][0], nfl_value.MIN_EV)
        rows = _market(6, lambda b: _h2h(b, -320, 260)) + [_h2h("soft", -400, 290)]
        cands = nfl_value.value_candidates(rows, now=NOW)
        self.assertFalse([c for c in cands if c["book"] == "soft"])
        self.assertEqual(nfl_value.select(rows, now=NOW,
                                          game_ids={(HOME, AWAY): "g"}), [])

    def test_a_near_even_total_that_clears_under_all_three_is_a_candidate(self):
        ev = _by_method(-115, -105, 110, "dog")      # over is the -105 side
        self.assertTrue(all(e >= nfl_value.MIN_EV for e, _ in ev.values()))
        rows = _market(6, lambda b: _totals(b, -105, -115)) + [_totals("outlier", 110, -130)]
        over = [c for c in nfl_value.value_candidates(rows, now=NOW)
                if c["book"] == "outlier" and c["side"] == "over"]
        self.assertEqual(len(over), 1)
        low_ev, low_fair = min(ev.values())
        self.assertAlmostEqual(over[0]["ev"], low_ev, places=9)
        self.assertAlmostEqual(over[0]["fair_probability"], low_fair, places=9)

    def test_the_card_publishes_the_most_cautious_method_not_proportional(self):
        # A dog long enough to clear under all three: 9.5% proportional,
        # 5.8% Shin, 3.7% power. The card must say 3.7%.
        ev = _by_method(-320, 260, 310, "dog")
        low_ev, low_fair = min(ev.values())
        self.assertGreaterEqual(low_ev, nfl_value.MIN_EV)
        self.assertLess(low_ev, ev["proportional"][0] - 0.05)
        rows = _market(6, lambda b: _h2h(b, -320, 260)) + [_h2h("soft", -400, 310)]
        picks = nfl_value.select(rows, now=NOW, game_ids={(HOME, AWAY): "g"})
        self.assertEqual(len(picks), 1)
        pick = picks[0]
        self.assertEqual((pick["market"], pick["side"], pick["book"]),
                         ("moneyline", "away", "soft"))
        self.assertEqual(pick["value_pct"], round(low_ev * 100.0, 2))
        self.assertEqual(pick["market_probability"], round(low_fair, 4))
        why = " ".join(pick["why"])
        self.assertIn(f"{low_fair * 100.0:.1f}%", why)
        self.assertIn(f"about {low_ev * 100.0:.1f}% more", why)
        self.assertNotIn(f"{ev['proportional'][0] * 100.0:.1f}%", why)


class BoardAge(unittest.TestCase):
    """Review finding, 2026-09-21: freshness was only measured book against
    book, so a board every book had stopped updating together looked fresh.
    On 2026-09-20 NFL capture stopped at 04:01Z and the card still ran at
    14:37Z-20:29Z; V2 would have published and locked IND@KC Over 46.5 +110
    from a 16-hour-old board, a price no book was offering by then."""

    def test_a_board_older_than_an_hour_is_never_judged(self):
        rows = (_market(6, lambda b: _totals(b, -110, -110, minutes_ago=16 * 60))
                + [_totals("outlier", 110, -130, minutes_ago=16 * 60)])
        self.assertEqual(nfl_value.value_candidates(rows, now=NOW), [])
        self.assertEqual(nfl_value.select(rows, now=NOW,
                                          game_ids={(HOME, AWAY): "g"}), [])
        self.assertEqual(nfl_value.FRESH_BOARD_SECONDS, 60 * 60)

    def test_a_board_inside_the_hour_is_still_judged(self):
        rows = (_market(6, lambda b: _totals(b, -110, -110, minutes_ago=59))
                + [_totals("outlier", 110, -130, minutes_ago=59)])
        cands = nfl_value.value_candidates(rows, now=NOW)
        self.assertTrue([c for c in cands if c["book"] == "outlier"])

    def test_the_age_gate_is_per_game_and_market(self):
        # Fresh totals, a spreads board that stopped 90 minutes ago: only
        # the totals are judged.
        rows = (_market(6, lambda b: _totals(b, -110, -110))
                + [_totals("outlier", 110, -130)]
                + _market(6, lambda b: _spread(b, -3.0, -110, -110, minutes_ago=90))
                + [_spread("sharp", -3.0, 115, -135, minutes_ago=90)])
        markets = {c["market"] for c in nfl_value.value_candidates(rows, now=NOW)}
        self.assertEqual(markets, {"totals"})

    def test_has_fresh_board_tells_a_stale_board_from_a_declined_one(self):
        fresh = _market(7, lambda b: _totals(b, -110, -110))
        stale = _market(7, lambda b: _totals(b, -110, -110, minutes_ago=61))
        self.assertTrue(nfl_value.has_fresh_board(fresh, now=NOW))
        self.assertFalse(nfl_value.has_fresh_board(stale, now=NOW))
        self.assertFalse(nfl_value.has_fresh_board([], now=NOW))


class Selection(unittest.TestCase):
    def test_one_pick_per_game_the_best_value_ranked_and_labelled(self):
        rows = (_market(6, lambda b: _totals(b, -110, -110))
                + _market(6, lambda b: _spread(b, -3.0, -110, -110))
                + [_totals("outlier", 105, -125), _spread("sharp", -3.0, 115, -135)])
        picks = nfl_value.select(rows, now=NOW, game_ids={(HOME, AWAY): "2026_03_IND_KC"})
        self.assertEqual(len(picks), 1)
        pick = picks[0]
        self.assertEqual(pick["market"], "spread")        # +115 beats +105
        self.assertEqual(pick["side"], "home")
        self.assertEqual(pick["line"], -3.0)
        self.assertEqual(pick["game_id"], "2026_03_IND_KC")
        self.assertEqual(pick["rank"], 1)
        self.assertIn("Kansas City Chiefs -3", pick["bet"])
        self.assertIn(pick["label"], (nfl_value.LABEL_STRONG, nfl_value.LABEL_LEAN))

    def test_a_game_with_no_schedule_id_is_not_published(self):
        rows = _market(6, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)]
        self.assertEqual(nfl_value.select(rows, now=NOW, game_ids={}), [])

    def test_the_card_payload_carries_v2_provenance_and_notice(self):
        rows = _market(6, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)]
        entries = [{"game_id": "2026_03_IND_KC", "week": 3, "home_team": HOME,
                    "away_team": AWAY, "kickoff_utc": KICKOFF}]
        card = nfl_report.card_for_date("2026-09-24", now=NOW, entries=entries,
                                        rows=rows, prefer_frozen=False)
        self.assertEqual(card["rule"], nfl_value.RULE_ID)
        self.assertEqual(card["model_id"], nfl_value.MODEL_ID)
        self.assertIn("bet at your own risk", card["notice"])
        self.assertEqual(card["picks"][0]["market"], "total")

    def test_an_empty_v2_card_says_which_nothing_it_is(self):
        entries = [{"game_id": "g", "week": 3, "home_team": HOME, "away_team": AWAY,
                    "kickoff_utc": KICKOFF}]
        no_board = nfl_report.card_for_date("2026-09-24", now=NOW, entries=entries,
                                            rows=[], prefer_frozen=False)
        self.assertIn("No priced board", no_board["reason"])
        flat = _market(7, lambda b: _totals(b, -110, -110))
        declined = nfl_report.card_for_date("2026-09-24", now=NOW, entries=entries,
                                            rows=flat, prefer_frozen=False)
        self.assertIn("priced better than the rest of the market", declined["reason"])


class GradingAndRecord(unittest.TestCase):
    def test_spread_and_total_picks_grade_on_the_main_card(self):
        result = {"away_score": 24, "home_score": 21}          # home lost by 3
        spread = card_ledger.grade_pick(
            {"market": "spread", "side": "home", "line": 3.5, "price": -110}, result)
        self.assertEqual(spread["result"], card_ledger.RESULT_WIN)
        pushed = card_ledger.grade_pick(
            {"market": "spread", "side": "home", "line": 3.0, "price": -110}, result)
        self.assertEqual(pushed["result"], card_ledger.RESULT_PUSH)
        over = card_ledger.grade_pick(
            {"market": "total", "side": "over", "line": 44.5, "price": -110}, result)
        self.assertEqual(over["result"], card_ledger.RESULT_WIN)
        under = card_ledger.grade_pick(
            {"market": "total", "side": "under", "line": 45.0, "price": -110}, result)
        self.assertEqual(under["result"], card_ledger.RESULT_PUSH)

    def _ledger_with_both_rules(self, folder):
        path = str(Path(folder) / "cards_nfl.jsonl")
        base = {"sport": "nfl", "experimental": True, "basis": "b", "disclaimer": "d",
                "model_id": "m", "calibrated": False, "calibration": None}
        v1_pick = {"game_id": "g1", "rank": 1, "sport": "nfl", "side": "home",
                   "market": "moneyline", "price": -225, "bet": "Take Bills",
                   "label": "STRONG", "kickoff_utc": "2026-09-17T17:00:00Z"}
        v2_pick = {"game_id": "g2", "rank": 1, "sport": "nfl", "side": "away",
                   "market": "spread", "line": 6.5, "price": 105, "bet": "Take Colts +6.5",
                   "label": "LEAN", "kickoff_utc": "2026-09-24T17:00:00Z"}
        card_ledger.publish({**base, "date": "2026-09-17", "rule": "NFL_CARD_V1",
                             "picks": [v1_pick]},
                            now="2026-09-17T12:00:00+00:00", path=path, sport="nfl")
        card_ledger.publish({**base, "date": "2026-09-24", "rule": nfl_value.RULE_ID,
                             "picks": [v2_pick]},
                            now="2026-09-24T12:00:00+00:00", path=path, sport="nfl")
        card_ledger.settle("2026-09-17", {"g1": {"away_score": 10, "home_score": 20}},
                           path=path, sport="nfl")
        card_ledger.settle("2026-09-24", {"g2": {"away_score": 17, "home_score": 23}},
                           path=path, sport="nfl")
        return path

    def test_the_record_never_pools_two_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._ledger_with_both_rules(folder)
            pooled = card_ledger.record(path=path)
            v2_only = card_ledger.record(path=path, rule=nfl_value.RULE_ID)
            v1_only = card_ledger.record(path=path, rule="NFL_CARD_V1")
            self.assertEqual((pooled["days"], pooled["wins"]), (2, 2))
            self.assertEqual((v2_only["days"], v2_only["wins"]), (1, 1))  # 6 < 6.5
            self.assertEqual((v1_only["days"], v1_only["wins"]), (1, 1))
            hist = card_ledger.history(path=path, rule=nfl_value.RULE_ID)
            self.assertEqual([d.get("date") for d in hist["days"]], ["2026-09-24"])

    def test_v2_never_publishes_over_a_date_that_already_has_a_v1_card(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "cards_nfl.jsonl")
            card_ledger.publish({"date": "2026-09-24", "sport": "nfl", "rule": "NFL_CARD_V1",
                                 "picks": [{"game_id": "g1", "rank": 1, "sport": "nfl",
                                            "side": "home", "market": "moneyline",
                                            "price": -300, "bet": "Take fav",
                                            "kickoff_utc": KICKOFF}]},
                                now="2026-09-24T10:00:00+00:00", path=path, sport="nfl")
            rows = _market(6, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)]
            entries = [{"game_id": "g1", "week": 3, "home_team": HOME,
                        "away_team": AWAY, "kickoff_utc": KICKOFF}]
            out = nfl_report.publish_for_date("2026-09-24", now=NOW, entries=entries,
                                              rows=rows, path=path)
            self.assertFalse(out.get("published"))
            self.assertIn("NFL_CARD_V1", out["reason"])


if __name__ == "__main__":
    unittest.main()
