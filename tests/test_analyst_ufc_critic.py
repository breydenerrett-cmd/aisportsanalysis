"""The critic on UFC packets: the same checks, a fight's vocabulary, and the -200 rule.

The deterministic critic is the MLB one (`src/analyst/critic.py`); these tests prove it
reads a UFC packet correctly (paths, one-option method slots, names that are fighters) and
that the only thing a sport changed, the name vocabulary, does what it should: a UFC claim
may say "Unanimous Decision" or "Women's Flyweight", and a stranger is still struck.
"""

from __future__ import annotations

import tempfile
import unittest

from src.analyst import critic
from src.analyst import ufc_analyst as U
from src.core import odds as odds_math
from tests import ufc_analyst_fixtures as F


class World(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = F.make_store(cls._tmp.name)
        cls.packet = F.packet(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def output(self):
        return F.deep(F.good_output(self.packet))

    def verify(self, output, packet=None):
        return U.verify(packet or self.packet, output)

    def call(self, out, slot_id):
        return next(c for c in out["calls"] if c["slot_id"] == slot_id)

    def published(self, verified, slot_id):
        return next(c for c in verified.calls if c["slot_id"] == slot_id)

    def struck_ids(self, verified):
        return [s["slot_id"] for s in verified.struck]


class AGoodAnalysisPasses(World):
    def test_nothing_is_struck_and_the_summary_stands(self):
        v = self.verify(self.output())
        self.assertEqual((v.struck, v.summary_status, v.summary_problems), ([], "ok", []))
        self.assertEqual([c["slot_id"] for c in v.calls], [s["slot_id"] for s in self.packet["slots"]])
        self.assertTrue(all(c["verification"]["status"] == "verified" for c in v.calls))

    def test_a_pass_and_a_take_other_side_both_survive(self):
        v = self.verify(self.output())
        self.assertEqual(self.published(v, "moneyline")["verdict"], "TAKE_OTHER_SIDE")
        self.assertEqual(self.published(v, "method_a_ko")["verdict"], "PASS")


class AStruckCallIsPublishedAsAPass(World):
    def test_a_wrong_evidence_value_strikes_the_call_and_keeps_the_audit_trail(self):
        out = self.output()
        out["calls"][0]["reasons"][0]["evidence"][0]["value"] = 999
        v = self.verify(out)
        self.assertEqual(self.struck_ids(v), ["moneyline"])
        pub = self.published(v, "moneyline")
        self.assertEqual(pub["verdict"], "PASS")
        self.assertEqual(pub["reasons"], [{"claim": "Could not be verified.", "evidence": []}])
        self.assertEqual(pub["verification"], {"status": "could not be verified", "problems": []})
        self.assertIsNone(pub["fair_estimate"])
        self.assertTrue(any("holds" in p for p in v.struck[0]["problems"]))
        self.assertEqual(v.struck[0]["original"]["verdict"], "TAKE_OTHER_SIDE")      # kept for the audit

    def test_the_struck_call_keeps_only_a_real_quote(self):
        out = self.output()
        out["calls"][0]["price"] = 999
        pub = self.published(self.verify(out), "moneyline")
        self.assertEqual((pub["price"], pub["book"]), (None, None))
        out = self.output()
        out["calls"][0]["reasons"][0]["claim"] = "He has a 2.17 rating."
        pub = self.published(self.verify(out), "moneyline")
        self.assertEqual((pub["price"], pub["book"]), (145, "DraftKings"))

    def test_an_unresolvable_path_is_struck_with_the_data_mistake_named(self):
        out = self.output()
        out["calls"][0]["reasons"][0]["evidence"][0]["path"] = "data.markets.moneyline.lean"
        v = self.verify(out)
        self.assertTrue(any("not with 'data'" in p for p in v.struck[0]["problems"]))

    def test_a_group_is_not_a_value(self):
        out = self.output()
        out["calls"][0]["reasons"][0]["evidence"][0] = {"path": "markets.moneyline.options[0].best", "value": "x"}
        self.assertTrue(any("group" in p for p in self.verify(out).struck[0]["problems"]))

    def test_an_invented_number_in_a_claim_is_struck(self):
        out = self.output()
        out["calls"][0]["reasons"][1]["claim"] = "He lands 8.31 significant strikes a minute."
        v = self.verify(out)
        self.assertTrue(any("8.31" in p for p in v.struck[0]["problems"]))

    def test_a_number_the_packet_holds_is_fine_and_so_is_a_percentage_of_one(self):
        out = self.output()
        value = self.packet["markets"]["moneyline"]["options"][1]["fair_probability"]
        out["calls"][0]["reasons"][1]["claim"] = f"The books have him at {round(value * 100)}% once the margin is out."
        self.assertEqual(self.verify(out).struck, [])

    def test_a_fighter_who_is_not_in_the_packet_is_struck(self):
        out = self.output()
        out["calls"][0]["reasons"][1]["claim"] = "Islam Makhachev has owned this kind of fighter."
        v = self.verify(out)
        self.assertTrue(any("islam makhachev" in p for p in v.struck[0]["problems"]))

    def test_the_two_fighters_and_their_opponents_are_names_the_packet_vouches_for(self):
        out = self.output()
        out["calls"][0]["reasons"][1]["claim"] = ("Alex Archer beat Dan Silva and lost to Ben Brawler, and "
                                                  "Ben Brawler's wrestling decided that fight.")
        self.assertEqual(self.verify(out).struck, [])

    def test_a_name_stitched_from_two_real_ones_is_struck(self):
        out = self.output()
        out["calls"][0]["reasons"][1]["claim"] = "Alex Brawler has the better wrestling."
        self.assertTrue(any("alex brawler" in p for p in self.verify(out).struck[0]["problems"]))

    def test_banned_words_are_struck_and_a_denied_edge_is_not(self):
        for text in ("This is a lock.", "A +EV spot.", "Guaranteed to cover.", "That is free money.",
                     "He has an edge here."):
            out = self.output()
            out["calls"][0]["reasons"][1]["claim"] = text
            self.assertEqual(self.struck_ids(self.verify(out)), ["moneyline"], text)
        out = self.output()
        out["calls"][0]["reasons"][1]["claim"] = "There is no edge here beyond the price."
        self.assertEqual(self.verify(out).struck, [])

    def test_a_price_that_is_not_a_quote_is_struck(self):
        out = self.output()
        out["calls"][0].update(price=150, book="DraftKings")
        self.assertTrue(any("is not a quote" in p for p in self.verify(out).struck[0]["problems"]))
        out = self.output()
        out["calls"][0].update(book="FanDuel")
        self.assertEqual(self.struck_ids(self.verify(out)), ["moneyline"])

    def test_a_call_that_contradicts_itself_is_struck(self):
        out = self.output()
        out["calls"][0]["fair_estimate"] = 0.20            # below the break-even of +145
        self.assertTrue(any("contradicts itself" in p for p in self.verify(out).struck[0]["problems"]))

    def test_a_take_with_no_estimate_or_pass_price_is_struck(self):
        out = self.output()
        out["calls"][0].update(fair_estimate=None, pass_price=None)
        problems = self.verify(out).struck[0]["problems"]
        self.assertTrue(any("needs a fair_estimate" in p for p in problems))
        self.assertTrue(any("needs a pass_price" in p for p in problems))


class OneOptionSlotsAreATakeOrAPass(World):
    def take(self, slot_id, verdict="TAKE", price_edit=None):
        out = self.output()
        market = self.packet["markets"][slot_id]
        opt = market["options"][0]
        fair = round(opt["implied_probability"] + 0.04, 4)
        call = {
            "slot_id": slot_id, "market": "method", "selection": opt["selection"], "verdict": verdict,
            "price": opt["best"]["price"], "book": "DraftKings", "fair_estimate": fair,
            "confidence": "low",
            "reasons": [{"claim": "The price is longer than the fighter's record of finishing suggests.",
                         "evidence": [{"path": f"markets.{slot_id}.options[0].best.price",
                                       "value": opt["best"]["price"]}]}],
            "pass_price": int(round(odds_math.probability_to_american(fair))),
            "what_would_change_it": "A late price move.",
        }
        out["calls"] = [call if c["slot_id"] == slot_id else c for c in out["calls"]]
        return out

    def test_a_take_on_a_method_slot_can_stand(self):
        v = self.verify(self.take("method_b_ko"))
        self.assertEqual(self.published(v, "method_b_ko")["verdict"], "TAKE")
        self.assertEqual(v.struck, [])

    def test_take_other_side_on_a_method_slot_is_struck_because_there_is_no_other_side(self):
        v = self.verify(self.take("method_b_ko", verdict="TAKE_OTHER_SIDE"))
        self.assertEqual(self.struck_ids(v), ["method_b_ko"])
        self.assertTrue(any("no other side" in p for p in v.struck[0]["problems"]))

    def test_take_must_name_the_lean_of_a_two_option_slot(self):
        out = self.output()
        under = self.packet["markets"]["rounds_total"]["options"][1]
        out["calls"][1].update(verdict="TAKE", selection=under["selection"], price=under["best"]["price"],
                               fair_estimate=0.6, pass_price=-150)
        v = self.verify(out)
        self.assertTrue(any("TAKE must name the lean" in p for p in v.struck[0]["problems"]))


class NoTakeAtMinus200OrWorse(World):
    """The owner's rulings of 2026-09-20 and 2026-09-22, in every UFC market."""

    def packet_with(self, **odds_edits):
        with tempfile.TemporaryDirectory() as tmp:
            store = F.make_store(tmp, rows=[F.odds(**odds_edits)])
            return F.packet(store)

    def take_lean(self, packet, slot_id, price):
        out = F.deep(F.good_output(packet))
        market = packet["markets"][slot_id]
        opt = market["options"][0]
        fair = round(min(0.97, odds_math.american_to_probability(price) + 0.05), 4)
        call = {
            "slot_id": slot_id, "market": market["market"], "selection": opt["selection"], "verdict": "TAKE",
            "price": price, "book": "DraftKings", "fair_estimate": fair, "confidence": "low",
            "reasons": [{"claim": "The price is better than the fight deserves.",
                         "evidence": [{"path": f"markets.{slot_id}.options[0].best.price", "value": price}]}],
            "pass_price": int(round(odds_math.probability_to_american(fair))),
            "what_would_change_it": "A late price move.",
        }
        out["calls"] = [call if c["slot_id"] == slot_id else c for c in out["calls"]]
        return out

    def test_a_moneyline_take_at_minus_250_is_struck(self):
        packet = self.packet_with(a_ml_current=-250, b_ml_current=210)
        v = U.verify(packet, self.take_lean(packet, "moneyline", -250))
        self.assertEqual([s["slot_id"] for s in v.struck], ["moneyline"])
        self.assertTrue(any("-200 or worse" in p for p in v.struck[0]["problems"]))

    def test_exactly_minus_200_is_struck_and_minus_199_is_not(self):
        packet = self.packet_with(a_ml_current=-200, b_ml_current=170)
        self.assertEqual(len(U.verify(packet, self.take_lean(packet, "moneyline", -200)).struck), 1)
        packet = self.packet_with(a_ml_current=-199, b_ml_current=170)
        self.assertEqual(U.verify(packet, self.take_lean(packet, "moneyline", -199)).struck, [])

    def test_a_method_take_at_minus_300_is_struck_too(self):
        mo = F.method_odds()
        mo["a"]["decision"]["current"] = -300
        packet = self.packet_with(method_odds=mo)
        v = U.verify(packet, self.take_lean(packet, "method_a_dec", -300))
        self.assertEqual([s["slot_id"] for s in v.struck], ["method_a_dec"])
        self.assertTrue(any("-200 or worse" in p for p in v.struck[0]["problems"]))

    def test_a_rounds_total_take_at_minus_220_is_struck(self):
        packet = self.packet_with(over_current=-220, under_current=180)
        v = U.verify(packet, self.take_lean(packet, "rounds_total", -220))
        self.assertTrue(any("-200 or worse" in p for p in v.struck[0]["problems"]))

    def test_the_other_side_of_the_same_market_is_not_caught_by_it(self):
        packet = self.packet_with(a_ml_current=-250, b_ml_current=210)
        out = F.deep(F.good_output(packet))          # TAKE_OTHER_SIDE on the +210 fighter
        self.assertEqual(out["calls"][0]["price"], 210)
        self.assertEqual(U.verify(packet, out).struck, [])

    def test_a_pass_at_minus_250_is_fine(self):
        packet = self.packet_with(a_ml_current=-250, b_ml_current=210)
        out = F.deep(F.good_output(packet))
        out["calls"][0] = F.pass_call(packet, "moneyline")
        self.assertEqual(out["calls"][0]["price"], -250)
        self.assertEqual(U.verify(packet, out).struck, [])


class TheSummary(World):
    def test_an_unsupported_number_withholds_it_and_the_calls_still_publish(self):
        out = self.output()
        out["summary"] = out["summary"] + " He is 71.93 percent better."
        v = self.verify(out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertIsNone(v.summary)
        self.assertEqual(len(v.calls), len(self.packet["slots"]))
        self.assertEqual(v.struck, [])

    def test_a_stranger_in_the_summary_withholds_it(self):
        out = self.output()
        out["summary"] = out["summary"].replace("Archer is the favourite", "Georges St-Pierre would like this one, and Archer is the favourite")
        out["summary"] += " Henry Cejudo agrees."
        v = self.verify(out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertTrue(any("henry cejudo" in p for p in v.summary_problems))

    def test_a_banned_word_withholds_it(self):
        out = self.output()
        out["summary"] += " It is a lock."
        self.assertEqual(self.verify(out).summary_status, "withheld")


class TheFightVocabulary(World):
    def packet_in_class(self, weight_class):
        packet = F.deep(self.packet)
        packet["bout"]["weight_class"] = weight_class
        return packet

    def claim(self, packet, text):
        out = F.deep(F.good_output(packet))
        out["calls"][0]["reasons"][1]["claim"] = text
        return U.verify(packet, out)

    def test_the_fighting_words_are_not_strangers(self):
        for text in ("A Unanimous Decision is the likeliest ending.", "Neither wins by Split Decision here.",
                     "This is a Title Fight in all but name.", "He has not been a Main Event fighter.",
                     "He fought on an Early Prelims slot."):
            self.assertEqual(self.claim(self.packet, text).struck, [], text)

    def test_a_womens_division_the_packet_names_is_not_a_stranger(self):
        """The critic strips a possessive before it looks a name up, so this was a false strike."""
        for division in ("Women's Flyweight", "Women's Strawweight", "Women's Bantamweight"):
            packet = self.packet_in_class(division)
            self.assertEqual(self.claim(packet, f"She has fought in the {division} division.").struck, [], division)

    def test_a_weight_class_the_packet_does_not_name_is_still_ordinary_vocabulary_only_if_listed(self):
        self.assertEqual(self.claim(self.packet, "He once fought at Light Heavyweight.").struck, [])
        self.assertEqual(len(self.claim(self.packet, "He once fought at Super Mega Weight.").struck), 1)

    def test_the_number_in_the_events_name_is_a_number_the_packet_holds(self):
        """"UFC 332" is in the packet as part of a string; a summary that says it is not quoting a
        number from nowhere. A different event number still is."""
        packet = F.deep(self.packet)
        packet["bout"]["event_name"] = "UFC 332: Silva vs. Wang"
        self.assertEqual(U.event_numbers(packet), [332.0])
        self.assertEqual(self.claim(packet, "This is the main event of UFC 332.").struck, [])
        out = F.deep(F.good_output(packet))
        out["summary"] += " Nothing about UFC 332 changes that."
        self.assertEqual(U.verify(packet, out).summary_status, "ok")
        bad = self.claim(packet, "This is the main event of UFC 333.")
        self.assertTrue(any("333" in p for p in bad.struck[0]["problems"]))

    def test_an_event_name_with_no_number_adds_no_number(self):
        self.assertEqual(U.event_numbers(self.packet), [])
        self.assertEqual(len(self.claim(self.packet, "This is the main event of UFC 332.").struck), 1)

    def test_no_baseball_club_is_vouched_for_in_a_ufc_claim(self):
        self.assertTrue(critic.KnownNames.build(self.packet).has("tampa bay rays"))        # the MLB default
        self.assertFalse(U.known_names(self.packet).has("tampa bay rays"))
        self.assertEqual(len(self.claim(self.packet, "He fights like the Tampa Bay Rays bullpen.").struck), 1)

    def test_the_mlb_critic_is_unchanged_for_mlb_packets(self):
        from tests import analyst_fixtures as M
        packet = M.build()
        out = M.good_output(packet)
        out["calls"][0]["reasons"][0]["claim"] = "The Tampa Bay Rays are the home side."
        self.assertEqual(critic.verify(packet, out).struck, [])
        self.assertEqual(critic.KnownNames.build(packet).phrases, critic._PHRASES)


class TheStalePriceDowngrade(World):
    def test_high_confidence_on_a_stale_price_is_lowered_not_struck(self):
        stale = F.packet(self.store, built_at="2026-10-10T20:00:00Z")
        out = F.deep(F.good_output(stale))
        out["calls"][0]["confidence"] = "high"
        v = U.verify(stale, out)
        self.assertEqual(v.struck, [])
        ml = self.published(v, "moneyline")
        self.assertEqual(ml["confidence"], "medium")
        self.assertIn("stale", ml["verification"]["downgrades"][0])

    def test_high_confidence_on_one_cited_fact_is_lowered(self):
        out = self.output()
        out["calls"][0]["confidence"] = "high"
        out["calls"][0]["reasons"] = out["calls"][0]["reasons"][:1]
        out["calls"][0]["reasons"][0]["evidence"] = out["calls"][0]["reasons"][0]["evidence"][:1]
        ml = self.published(self.verify(out), "moneyline")
        self.assertEqual(ml["confidence"], "medium")


if __name__ == "__main__":
    unittest.main()
