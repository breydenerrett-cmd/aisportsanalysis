"""The code risk manager, rule by rule (src/hounds/desk/risk.py, docs/PREREG_DESK_HOUNDS.md section 3 and 5).

The packets here are hand-built `markets` dicts, so every price and probability the assertions rely on is
visible in the test. Pure and offline.
"""

from __future__ import annotations

import unittest

from src.hounds.desk import risk
from src.core import odds as odds_math

BOOKS = ("alpha", "bravo", "charlie")


def option(selection, side, line, prices, fair, *, best=None):
    quotes = [{"book": b, "price": p, "captured_utc": "2026-10-03T17:00:00Z"} for b, p in zip(BOOKS, prices)]
    top = max(quotes, key=lambda q: odds_math.american_to_decimal(q["price"]))
    return {"selection": selection, "side": side, "line": line, "books": len(quotes), "quotes": quotes,
            "best": best or {"price": top["price"], "book": top["book"]}, "fair_probability": fair}


def market(slot_id, kind, options, label=None):
    return {"slot_id": slot_id, "market": kind, "label": label or slot_id, "lean": options[0]["selection"],
            "options": options}


def packet(**extra_markets):
    markets = {
        "moneyline": market("moneyline", "moneyline", [
            option("HOME", "home", None, [-130, -125, -128], 0.5500),
            option("AWAY", "away", None, [120, 115, 118], 0.4500)]),
        "run_line": market("run_line", "run_line", [
            option("AWAY +1.5", "away", 1.5, [-180, -175, -190], 0.6300),
            option("HOME -1.5", "home", -1.5, [160, 155, 165], 0.3700)]),
        "total": market("total", "total", [
            option("Under 8", "under", 8.0, [-110, -108, -112], 0.5050),
            option("Over 8", "over", 8.0, [-105, -107, -103], 0.4950)]),
        "team_total_home": market("team_total_home", "team_total", [
            option("HOME Over 4", "over", 4.0, [-115, -112, -118], 0.5100),
            option("HOME Under 4", "under", 4.0, [100, 102, 105], 0.4900)]),
        "prop_01": market("prop_01", "prop", [
            option("Under 5.5", "under", 5.5, [-140, -135, -145], 0.5700),
            option("Over 5.5", "over", 5.5, [115, 118, 112], 0.4300)]),
        "prop_02": market("prop_02", "prop", [option("Over 0.5", "over", 0.5, [330, 320, 340], None)]),
    }
    markets.update(extra_markets)
    return {"game": {"game_id": "AWAY-HOME-2026-10-03-1", "first_pitch_utc": "2026-10-03T22:30:00Z"},
            "markets": markets, "slots": [{"slot_id": s, "market": m["market"], "label": m["label"]}
                                          for s, m in markets.items()]}


def decision(pkt, slot_id, selection, probability, *, price=None, book=None, reasons=None):
    opt = next(o for o in pkt["markets"][slot_id]["options"] if o["selection"] == selection)
    return {"slot_id": slot_id, "selection": selection, "verdict": "TAKE",
            "price": opt["best"]["price"] if price is None else price,
            "book": opt["best"]["book"] if book is None else book, "probability": probability,
            "reasons": reasons or [{"claim": "x", "evidence": [{"path": "markets.moneyline.lean", "value": "HOME"}]}],
            "case_against": {"claim": "y", "evidence": []}, "what_would_change_it": "z"}


class Helpers(unittest.TestCase):
    def test_board_average_is_the_american_price_of_the_mean_decimal(self):
        opt = option("A", "away", None, [120, 100, 110], 0.5)
        mean_dec = sum(odds_math.american_to_decimal(p) for p in (120, 100, 110)) / 3
        self.assertEqual(risk.board_average(opt), int(round(odds_math.decimal_to_american(mean_dec))))

    def test_side_kinds(self):
        p = packet()
        m = p["markets"]
        self.assertEqual(risk.side_kind(m["moneyline"], m["moneyline"]["options"][0]), "favourite")
        self.assertEqual(risk.side_kind(m["moneyline"], m["moneyline"]["options"][1]), "underdog")
        self.assertEqual(risk.side_kind(m["run_line"], m["run_line"]["options"][0]), "gets_points")
        self.assertEqual(risk.side_kind(m["run_line"], m["run_line"]["options"][1]), "lays_points")
        self.assertEqual(risk.side_kind(m["total"], m["total"]["options"][0]), "under")
        self.assertEqual(risk.side_kind(m["prop_01"], m["prop_01"]["options"][1]), "over")

    def test_sport_is_read_from_the_game_block(self):
        self.assertEqual(risk.sport_of({"game": {"first_pitch_utc": "x"}}), "mlb")
        self.assertEqual(risk.sport_of({"game": {"kickoff_utc": "x"}}), "nfl")


class R1PriceInTheData(unittest.TestCase):
    def test_the_best_quote_passes(self):
        p = packet()
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", 0.55)])
        self.assertEqual([t.slot_id for t in result.kept], ["moneyline"])
        self.assertEqual(result.struck, [])

    def test_a_price_not_in_the_data_is_struck(self):
        p = packet()
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", 0.55, price=125)])
        self.assertEqual(result.kept, [])
        self.assertEqual([s.rule for s in result.struck], ["R1"])

    def test_a_real_quote_that_is_not_the_best_is_struck(self):
        p = packet()
        # alpha quotes AWAY at +120, the best; bravo at +115 is a real quote, but not the best
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", 0.55, price=115, book="bravo")])
        self.assertEqual([s.rule for s in result.struck], ["R1"])
        self.assertIn("best", result.struck[0].reason)

    def test_the_wrong_book_for_a_real_price_is_struck(self):
        p = packet()
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", 0.55, book="charlie")])
        self.assertEqual([s.rule for s in result.struck], ["R1"])

    def test_an_unknown_selection_or_slot_is_struck_not_raised(self):
        p = packet()
        bad = decision(p, "moneyline", "AWAY", 0.55)
        bad["selection"] = "NOBODY"
        ghost = dict(bad, slot_id="nope")
        result = risk.assess(p, [bad, ghost])
        self.assertEqual([s.rule for s in result.struck], ["R1", "R1"])


class R2TheCap(unittest.TestCase):
    def test_a_price_of_minus_200_or_worse_is_never_a_take(self):
        p = packet()
        p["markets"]["moneyline"]["options"][0] = option("HOME", "home", None, [-200, -210, -205], 0.66)
        p["markets"]["moneyline"]["lean"] = "HOME"
        result = risk.assess(p, [decision(p, "moneyline", "HOME", 0.80)])
        self.assertEqual([s.rule for s in result.struck], ["R2"])

    def test_minus_199_is_allowed_by_the_cap(self):
        p = packet()
        p["markets"]["moneyline"]["options"][0] = option("HOME", "home", None, [-199, -190, -195], 0.66)
        result = risk.assess(p, [decision(p, "moneyline", "HOME", 0.80)])
        self.assertEqual([t.slot_id for t in result.kept], ["moneyline"])

    def test_the_average_price_at_minus_200_or_worse_strikes_even_when_the_best_does_not(self):
        p = packet()
        p["markets"]["moneyline"]["options"][0] = option("HOME", "home", None, [-195, -215, -230], 0.66)
        self.assertGreater(risk.board_average(p["markets"]["moneyline"]["options"][0]), -200 - 30)
        self.assertLessEqual(risk.board_average(p["markets"]["moneyline"]["options"][0]), -200)
        result = risk.assess(p, [decision(p, "moneyline", "HOME", 0.85)])
        self.assertEqual([s.rule for s in result.struck], ["R2"])
        self.assertIn("board average", result.struck[0].reason)

    def test_the_cap_holds_for_a_prop_and_for_every_hound(self):
        p = packet()
        p["markets"]["prop_01"]["options"][0] = option("Under 5.5", "under", 5.5, [-250, -260, -240], 0.7)
        for persona in (None, "sharp", "grinder", "fader"):
            result = risk.assess(p, [decision(p, "prop_01", "Under 5.5", 0.9)], persona)
            self.assertEqual([t for t in result.kept], [], persona)
            self.assertEqual(result.struck[0].rule, "R2", persona)


class R3BeatTheMarket(unittest.TestCase):
    def test_a_probability_below_the_books_number_is_struck(self):
        p = packet()
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", 0.44)])
        self.assertEqual([s.rule for s in result.struck], ["R3"])

    def test_a_probability_above_fair_but_below_the_average_breakeven_is_struck(self):
        p = packet()
        opt = p["markets"]["moneyline"]["options"][1]
        be_avg = risk.break_even(risk.board_average(opt))
        self.assertGreater(be_avg, opt["fair_probability"])
        stated = round((be_avg + opt["fair_probability"]) / 2, 4)
        self.assertGreater(stated, opt["fair_probability"])
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", stated)])
        self.assertEqual([s.rule for s in result.struck], ["R3"])

    def test_a_probability_above_both_passes_and_the_margin_is_against_the_average(self):
        p = packet()
        opt = p["markets"]["moneyline"]["options"][1]
        be_avg = risk.break_even(risk.board_average(opt))
        result = risk.assess(p, [decision(p, "moneyline", "AWAY", be_avg + 0.03)])
        self.assertEqual(len(result.kept), 1)
        self.assertAlmostEqual(result.kept[0].margin, 0.03, places=6)
        self.assertEqual(result.kept[0].price_best, 120)
        self.assertEqual(result.kept[0].consensus_fair, 0.45)

    def test_a_selection_with_no_consensus_cannot_be_taken(self):
        p = packet()
        result = risk.assess(p, [decision(p, "prop_02", "Over 0.5", 0.9)])
        self.assertEqual([s.rule for s in result.struck], ["R3"])
        self.assertIn("no de-vigged consensus", result.struck[0].reason)


class R5AtMostTwo(unittest.TestCase):
    def test_the_two_largest_margins_are_kept_and_the_rest_struck(self):
        p = packet()
        be = {s: risk.break_even(risk.board_average(p["markets"][s]["options"][i]))
              for s, i in (("moneyline", 1), ("total", 0), ("team_total_home", 1))}
        takes = [decision(p, "moneyline", "AWAY", be["moneyline"] + 0.02),
                 decision(p, "total", "Under 8", be["total"] + 0.06),
                 decision(p, "team_total_home", "HOME Under 4", be["team_total_home"] + 0.04)]
        result = risk.assess(p, takes)
        self.assertEqual([t.slot_id for t in result.kept], ["total", "team_total_home"])
        self.assertEqual([(s.slot_id, s.rule) for s in result.struck], [("moneyline", "R5")])

    def test_two_takes_are_both_kept(self):
        p = packet()
        be_t = risk.break_even(risk.board_average(p["markets"]["total"]["options"][0]))
        be_m = risk.break_even(risk.board_average(p["markets"]["moneyline"]["options"][1]))
        result = risk.assess(p, [decision(p, "total", "Under 8", be_t + 0.03),
                                 decision(p, "moneyline", "AWAY", be_m + 0.03)])
        self.assertEqual(len(result.kept), 2)
        self.assertEqual(result.struck, [])

    def test_a_tie_goes_to_slot_order(self):
        p = packet()
        be_t = risk.break_even(risk.board_average(p["markets"]["total"]["options"][0]))
        # moneyline first in slot order; give all three exactly the same margin
        be_m = risk.break_even(risk.board_average(p["markets"]["moneyline"]["options"][1]))
        be_h = risk.break_even(risk.board_average(p["markets"]["team_total_home"]["options"][1]))
        result = risk.assess(p, [decision(p, "team_total_home", "HOME Under 4", be_h + 0.05),
                                 decision(p, "total", "Under 8", be_t + 0.05),
                                 decision(p, "moneyline", "AWAY", be_m + 0.05)])
        self.assertEqual([t.slot_id for t in result.kept], ["moneyline", "total"])


class R4Personas(unittest.TestCase):
    def kept(self, persona, slot, selection, p_extra=0.03, pkt=None, **kw):
        pkt = pkt or packet()
        opt = next(o for o in pkt["markets"][slot]["options"] if o["selection"] == selection)
        be = risk.break_even(risk.board_average(opt))
        prob = max(be, opt["fair_probability"] or 0) + p_extra
        result = risk.assess(pkt, [decision(pkt, slot, selection, prob, **kw)], persona)
        return result

    def test_the_sharp_needs_the_best_quote_to_beat_the_books_number(self):
        # best AWAY quote +120 has break-even 0.4545, above the books' 0.45: not a better price than fair
        result = self.kept("sharp", "moneyline", "AWAY")
        self.assertEqual([s.rule for s in result.struck], ["R4"])
        pkt = packet()
        pkt["markets"]["moneyline"]["options"][1] = option("AWAY", "away", None, [140, 115, 118], 0.4500)
        result = self.kept("sharp", "moneyline", "AWAY", pkt=pkt)
        self.assertEqual(len(result.kept), 1, result.struck)

    def test_the_square_takes_only_the_favourite_and_the_over(self):
        self.assertEqual(len(self.kept("square", "moneyline", "HOME").kept), 1)
        self.assertEqual(len(self.kept("square", "total", "Over 8").kept), 1)
        for slot, sel in (("moneyline", "AWAY"), ("total", "Under 8"), ("run_line", "AWAY +1.5"),
                          ("team_total_home", "HOME Over 4"), ("prop_01", "Over 5.5")):
            result = self.kept("square", slot, sel)
            self.assertEqual([s.rule for s in result.struck], ["R4"], (slot, sel))

    def test_the_fader_takes_the_underdog_the_points_and_the_under(self):
        for slot, sel in (("moneyline", "AWAY"), ("run_line", "AWAY +1.5"), ("total", "Under 8"),
                          ("prop_01", "Under 5.5"), ("team_total_home", "HOME Under 4")):
            self.assertEqual(len(self.kept("fader", slot, sel).kept), 1, (slot, sel))
        for slot, sel in (("moneyline", "HOME"), ("run_line", "HOME -1.5"), ("total", "Over 8")):
            self.assertEqual([s.rule for s in self.kept("fader", slot, sel).struck], ["R4"], (slot, sel))

    def test_the_weather_nerd_takes_only_totals(self):
        for slot, sel in (("total", "Under 8"), ("team_total_home", "HOME Under 4")):
            self.assertEqual(len(self.kept("weather", slot, sel).kept), 1, (slot, sel))
        for slot, sel in (("moneyline", "AWAY"), ("run_line", "AWAY +1.5"), ("prop_01", "Under 5.5")):
            self.assertEqual([s.rule for s in self.kept("weather", slot, sel).struck], ["R4"], (slot, sel))

    def test_the_grinder_takes_unders_and_short_favourites_with_a_small_gap(self):
        self.assertEqual(len(self.kept("grinder", "total", "Under 8", 0.02).kept), 1)
        # HOME -130 best -125 is a short favourite (-150 or shorter)
        self.assertEqual(len(self.kept("grinder", "moneyline", "HOME", 0.02).kept), 1)
        # an underdog and an over are not his
        self.assertEqual([s.rule for s in self.kept("grinder", "moneyline", "AWAY", 0.02).struck], ["R4"])
        self.assertEqual([s.rule for s in self.kept("grinder", "total", "Over 8", 0.02).struck], ["R4"])

    def test_the_grinder_rejects_a_favourite_longer_than_minus_150(self):
        pkt = packet()
        pkt["markets"]["moneyline"]["options"][0] = option("HOME", "home", None, [-165, -170, -160], 0.62)
        result = self.kept("grinder", "moneyline", "HOME", 0.02, pkt=pkt)
        self.assertEqual([s.rule for s in result.struck], ["R4"])

    def test_the_grinder_rejects_a_big_claimed_gap(self):
        opt = packet()["markets"]["total"]["options"][0]
        result = risk.assess(packet(), [decision(packet(), "total", "Under 8", opt["fair_probability"] + 0.06)],
                             "grinder")
        self.assertEqual([s.rule for s in result.struck], ["R4"])
        self.assertIn("at most", result.struck[0].reason)

    def history_reasons(self, *paths):
        return [{"claim": "c", "evidence": [{"path": p, "value": 1} for p in paths]}]

    def test_the_historian_needs_a_history_path_and_cites_nothing_else(self):
        hist = "sections.matchup_history.values.games"
        ok = self.kept("historian", "total", "Under 8", reasons=self.history_reasons(
            hist, "markets.total.options[0].best.price", "game.date"))
        self.assertEqual(len(ok.kept), 1, ok.struck)
        none = self.kept("historian", "total", "Under 8", reasons=self.history_reasons(
            "markets.total.options[0].best.price"))
        self.assertEqual([s.rule for s in none.struck], ["R4"])
        stray = self.kept("historian", "total", "Under 8", reasons=self.history_reasons(
            hist, "sections.starters.values.home_sp_era"))
        self.assertEqual([s.rule for s in stray.struck], ["R4"])
        self.assertIn("starters", stray.struck[0].reason)

    def test_the_historian_uses_the_football_section_for_a_football_packet(self):
        pkt = packet()
        pkt["game"] = {"game_id": "g", "kickoff_utc": "2026-10-03T22:30:00Z"}
        nfl_hist = "sections.matchup.values.head_to_head.games"
        ok = self.kept("historian", "total", "Under 8", pkt=pkt,
                       reasons=self.history_reasons(nfl_hist))
        self.assertEqual(len(ok.kept), 1, ok.struck)
        wrong = self.kept("historian", "total", "Under 8", pkt=pkt,
                          reasons=self.history_reasons("sections.matchup_history.values.games"))
        self.assertEqual([s.rule for s in wrong.struck], ["R4"])

    def test_the_desk_has_no_persona_rule(self):
        for slot, sel in (("moneyline", "HOME"), ("moneyline", "AWAY"), ("total", "Over 8")):
            self.assertEqual(len(self.kept(None, slot, sel).kept), 1, (slot, sel))


if __name__ == "__main__":
    unittest.main()
