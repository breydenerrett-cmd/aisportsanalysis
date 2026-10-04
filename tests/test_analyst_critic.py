"""The critic: unsupported calls are struck to PASS, never silently kept."""

from __future__ import annotations

import unittest

from src.analyst import analyst as A
from src.analyst import critic as C
from src.core import odds as odds_math
from tests import analyst_fixtures as F


def verify(packet, mutate=None, **kw):
    out = F.good_output(packet)
    if mutate:
        mutate(out)
    assert A.validate_output(out, packet) == [], A.validate_output(out, packet)
    return C.verify(packet, out, **kw)


def call(verified, slot_id):
    return next(c for c in verified.calls if c["slot_id"] == slot_id)


def struck_ids(verified):
    return [s["slot_id"] for s in verified.struck]


class AGoodAnswerPasses(unittest.TestCase):
    def test_nothing_is_struck_and_the_summary_stands(self):
        packet = F.build()
        v = verify(packet)
        self.assertEqual(v.struck, [])
        self.assertEqual(v.summary_status, "ok")
        self.assertEqual(len(v.calls), len(packet["slots"]))
        self.assertTrue(all(c["verification"]["status"] == "verified" for c in v.calls))

    def test_the_take_is_published_as_the_model_wrote_it(self):
        packet = F.build()
        c = call(verify(packet), "moneyline")
        self.assertEqual(c["verdict"], "TAKE_OTHER_SIDE")
        self.assertEqual(c["selection"], "NYY")
        self.assertIsNotNone(c["fair_estimate"])


class InventedNumbers(unittest.TestCase):
    def test_a_number_that_is_not_in_the_packet_strikes_the_call(self):
        def m(o):
            o["calls"][0]["reasons"][1]["claim"] = "The road starter has a 2.17 ERA over his last starts."
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("2.17" in p for p in v.struck[0]["problems"]))

    def test_a_number_that_is_in_the_packet_is_fine(self):
        def m(o):
            o["calls"][0]["reasons"][1]["claim"] = "The road starter has a 3.4054 ERA and a 3.86 FIP."
        self.assertEqual(verify(F.build(), m).struck, [])

    def test_a_percent_matches_a_packet_fraction_at_the_precision_written(self):
        def m(o):
            o["calls"][0]["reasons"][0]["claim"] = "The books have the home side near 55%."
        self.assertEqual(verify(F.build(), m).struck, [])
        def n(o):
            o["calls"][0]["reasons"][0]["claim"] = "The books have the home side near 71%."
        self.assertEqual(struck_ids(verify(F.build(), n)), ["moneyline"])

    def test_the_analysts_own_estimate_and_prices_may_be_quoted(self):
        packet = F.build()
        out = F.good_output(packet)
        fe = out["calls"][0]["fair_estimate"]
        out["calls"][0]["reasons"][0]["claim"] = f"I make it {round(fe * 100, 1)}% against a price of {out['calls'][0]['price']}."
        self.assertEqual(C.verify(packet, out).struck, [])

    def test_a_date_in_words_is_not_a_number_from_nowhere(self):
        def m(o):
            o["calls"][0]["reasons"][0]["claim"] = "Tonight, October 3, the home side is the lean."
        self.assertEqual(verify(F.build(), m).struck, [])

    def test_an_invented_number_in_the_summary_withholds_the_summary_only(self):
        def m(o):
            o["summary"] = o["summary"] + " I give the home side a 63.2% chance."
        v = verify(F.build(), m)
        self.assertEqual(v.summary_status, "withheld")
        self.assertIsNone(v.summary)
        self.assertEqual(v.struck, [])      # the calls stand
        self.assertTrue(any("63.2" in p for p in v.summary_problems))

    def test_an_invented_number_in_what_would_change_it_strikes_the_call(self):
        def m(o):
            o["calls"][0]["what_would_change_it"] = "The home price shortening past -171."
        self.assertEqual(struck_ids(verify(F.build(), m)), ["moneyline"])


class NumbersAreNotLaunderedBetweenCalls(unittest.TestCase):
    def test_one_calls_estimate_cannot_be_quoted_by_another(self):
        packet = F.build()
        out = F.good_output(packet)
        fe = out["calls"][0]["fair_estimate"]
        out["calls"][1]["reasons"][0]["claim"] = f"The books are near {round(fe * 100, 2)}% here."
        self.assertEqual(struck_ids(C.verify(packet, out)), ["run_line"])

    def test_a_wrong_evidence_value_does_not_make_its_number_quotable(self):
        packet = F.build()
        out = F.good_output(packet)
        out["calls"][0]["reasons"][1]["evidence"][0]["value"] = 4.321    # wrong, and struck
        out["calls"][1]["reasons"][0]["claim"] = "A road ERA near 4.321."
        self.assertEqual(sorted(struck_ids(C.verify(packet, out))), ["moneyline", "run_line"])

    def test_the_summary_may_quote_a_kept_calls_estimate_but_not_a_struck_ones(self):
        packet = F.build()
        out = F.good_output(packet)
        fe = out["calls"][0]["fair_estimate"]
        out["summary"] = out["summary"] + f" I make the road side {round(fe * 100, 2)}%."
        self.assertEqual(C.verify(packet, out).summary_status, "ok")
        out["calls"][0]["reasons"][1]["claim"] = "He has a 2.17 ERA."      # strikes the call
        self.assertEqual(C.verify(packet, out).summary_status, "withheld")

    def test_a_price_threshold_in_what_would_change_it_is_the_calls_own_pass_price(self):
        packet = F.build()
        out = F.good_output(packet)
        pp = out["calls"][0]["pass_price"]
        out["calls"][0]["what_would_change_it"] = f"The road price falling to {pp:+d} or worse."
        self.assertEqual(C.verify(packet, out).struck, [])


class NamesMustBeInThePacket(unittest.TestCase):
    """The benchmark's original failure: a pitcher nobody had verified."""

    def claim(self, text, where="reason", mutate=None):
        packet = F.build()
        out = F.good_output(packet)
        if where == "reason":
            out["calls"][0]["reasons"][0]["claim"] = text
        elif where == "change":
            out["calls"][0]["what_would_change_it"] = text
        else:
            out["summary"] = out["summary"] + " " + text
        return C.verify(packet, out)

    def test_a_player_the_packet_never_mentions_strikes_the_call(self):
        v = self.claim("Aaron Judge has owned this starter.")
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("names 'aaron judge'" in p for p in v.struck[0]["problems"]))

    def test_a_starter_the_packet_names_is_fine_with_or_without_a_possessive(self):
        self.assertEqual(self.claim("Gerrit Cole has the longer leash.").struck, [])
        self.assertEqual(self.claim("Gerrit Cole's ERA is in the data.").struck, [])
        self.assertEqual(self.claim("Drew Rasmussen is the home starter.").struck, [])

    def test_a_batter_from_a_prop_in_the_packet_is_fine(self):
        self.assertEqual(self.claim("Junior Caminero is priced at a short number.").struck, [])
        self.assertEqual(self.claim("Jazz Chisholm Jr. has a one-sided price.").struck, [])

    def test_club_names_and_cities_are_fine_though_the_packet_only_has_abbreviations(self):
        self.assertEqual(self.claim("The Tampa Bay Rays are the home side.").struck, [])
        self.assertEqual(self.claim("New York comes in as the road club.").struck, [])

    def test_one_capitalised_word_is_not_checked(self):
        self.assertEqual(self.claim("Rasmussen has been sharper. Judge is not mentioned again.").struck, [])
        self.assertEqual(self.claim("Cole is the road starter.").struck, [])

    def test_sentence_leading_filler_is_not_part_of_a_name(self):
        self.assertEqual(self.claim("The Rays have the better price. This Yankees side is longer.").struck, [])
        self.assertEqual(self.claim("Without Gerrit Cole this changes.").struck, [])

    def test_a_name_in_what_would_change_it_or_the_summary_is_checked_too(self):
        v = self.claim("A scratch of Giancarlo Stanton would flip it.", where="change")
        self.assertEqual(struck_ids(v), ["moneyline"])
        v = self.claim("Giancarlo Stanton is the key.", where="summary")
        self.assertEqual(v.summary_status, "withheld")
        self.assertTrue(any("giancarlo stanton" in p for p in v.summary_problems))

    def test_a_printed_last_comma_first_name_counts_as_first_last(self):
        payload = F.payload()
        payload["advanced"]["sections"]["arsenals"] = {
            "away": [{"name": "Cole, Gerrit", "pitch_name": "Slider", "pitch_usage": 19.9,
                      "whiff_percent": 27.9}], "home": []}
        from src.analyst import packet as P
        packet = P.build_packet(payload, built_at=F.BUILT_AT, multibook_rows=F.multibook_rows(), cfg=F.CFG)
        known = C.KnownNames.build(packet)
        self.assertEqual(C.unsupported_names("Gerrit Cole throws a slider.", known), [])
        self.assertEqual(C.unsupported_names("Ben Rice throws a slider.", known), ["ben rice"])

    def test_ordinary_capitalised_baseball_phrases_are_fine(self):
        self.assertEqual(self.claim("In the National League Division Series the Run Line matters.").struck, [])

    def test_a_name_invented_from_two_real_players_pieces_is_not_tiled(self):
        known = C.KnownNames.build(F.build())
        # "Gerrit" is Cole's first name and "Rice" is Ben Rice's surname; the pair is nobody
        self.assertEqual(C.unsupported_names("Gerrit Rice is the starter.", known), ["gerrit rice"])
        # two clubs side by side are two clubs
        self.assertEqual(C.unsupported_names("Yankees Rays is a long way round.", known), [])

    def test_a_possessive_and_a_sentence_boundary_do_not_glue_names_together(self):
        known = C.KnownNames.build(F.build())
        self.assertEqual(C.name_runs("He faced Gerrit Cole. Drew Rasmussen followed."),
                         ["gerrit cole", "drew rasmussen"])
        self.assertEqual(C.unsupported_names("Gerrit Cole. Drew Rasmussen.", known), [])

    def test_a_number_hidden_after_a_colon_is_still_a_number(self):
        """The benchmark's `word:number` hole: ERA:9.99 hid 9.99 from its checker."""
        self.assertEqual(struck_ids(self.claim("ERA:9.99 for the road starter.")), ["moneyline"])


class EvidencePaths(unittest.TestCase):
    def test_an_unresolved_path_strikes_the_call(self):
        def m(o):
            o["calls"][0]["reasons"][0]["evidence"][0]["path"] = "sections.starters.values.away_sp_whip"
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("no key 'away_sp_whip'" in p for p in v.struck[0]["problems"]))

    def test_the_benchmarks_data_prefix_mistake_is_named(self):
        def m(o):
            o["calls"][0]["reasons"][0]["evidence"][0]["path"] = "data.best_price"
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("start at the packet's own top-level key" in p for p in v.struck[0]["problems"]))

    def test_a_value_that_does_not_match_the_packet_strikes_the_call(self):
        def m(o):
            o["calls"][0]["reasons"][1]["evidence"][0]["value"] = 2.5
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("holds 3.8602, not 2.5" in p for p in v.struck[0]["problems"]))

    def test_a_rounded_value_matches_at_the_precision_written(self):
        def m(o):
            o["calls"][0]["reasons"][1]["evidence"][0]["value"] = 3.86
        self.assertEqual(verify(F.build(), m).struck, [])

    def test_a_whole_number_does_not_match_a_fraction(self):
        def m(o):
            o["calls"][0]["reasons"][1]["evidence"][0]["value"] = 4
        self.assertEqual(struck_ids(verify(F.build(), m)), ["moneyline"])

    def test_a_path_to_a_group_is_not_a_value(self):
        def m(o):
            o["calls"][0]["reasons"][0]["evidence"][0] = {"path": "markets.moneyline.options[0]", "value": "x"}
        self.assertEqual(struck_ids(verify(F.build(), m)), ["moneyline"])

    def test_a_reason_with_no_evidence_strikes_the_call(self):
        def m(o):
            o["calls"][1]["reasons"][0]["evidence"] = []
        self.assertEqual(struck_ids(verify(F.build(), m)), ["run_line"])

    def test_string_values_match_case_insensitively(self):
        self.assertTrue(C.values_match("tb", "TB"))
        self.assertFalse(C.values_match("NYY", "TB"))
        self.assertTrue(C.values_match(True, True))
        self.assertFalse(C.values_match(1, True))
        self.assertTrue(C.values_match(None, None))


class SelectionPriceAndVerdict(unittest.TestCase):
    def test_a_selection_not_in_the_slot_strikes_the_call(self):
        def m(o):
            o["calls"][1]["selection"] = "NYY -1.5"
        self.assertEqual(struck_ids(verify(F.build(), m)), ["run_line"])

    def test_a_price_no_book_quoted_strikes_the_call(self):
        def m(o):
            o["calls"][0]["price"] = 125
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("is not a quote" in p for p in v.struck[0]["problems"]))

    def test_a_book_that_did_not_quote_that_price_strikes_the_call(self):
        def m(o):
            o["calls"][0]["book"] = "draftkings"
        self.assertEqual(struck_ids(verify(F.build(), m)), ["moneyline"])

    def test_take_must_name_the_lean_and_other_side_must_not(self):
        packet = F.build()
        def m(o):
            o["calls"][0]["verdict"] = "TAKE"          # NYY is not the lean
        self.assertTrue(any("TAKE must name the lean" in p
                            for p in verify(packet, m).struck[0]["problems"]))
        def n(o):
            o["calls"][1].update(verdict="TAKE_OTHER_SIDE")   # run_line PASS call names the lean
        self.assertEqual(struck_ids(verify(packet, n)), ["run_line"])

    def test_other_side_on_a_one_sided_market_is_impossible(self):
        packet = F.build()
        slot = next(s for s, m in packet["markets"].items() if len(m["options"]) == 1)
        out = F.good_output(packet)
        c = next(c for c in out["calls"] if c["slot_id"] == slot)
        c["verdict"] = "TAKE_OTHER_SIDE"
        self.assertIn(slot, struck_ids(C.verify(packet, out)))

    def test_a_take_without_a_price_is_struck(self):
        def m(o):
            o["calls"][0].update(price=None, book=None)
        self.assertEqual(struck_ids(verify(F.build(), m)), ["moneyline"])


class TheMinus200Rule(unittest.TestCase):
    """No TAKE at -200 or worse. The build brief named the moneyline; the owner's
    2026-09-22 ruling ("no public pick at -200 or worse, on any sport") is
    broader, so every market is held to it."""

    def packet(self):
        return F.build(multibook_rows=F.multibook_rows(home_ml=(-250, -240, -260),
                                                       away_ml=(205, 210, 200)))

    def take_home(self, packet, price):
        market = packet["markets"]["moneyline"]
        book = next(q["book"] for q in market["options"][0]["quotes"] if q["price"] == price)
        fair = round(odds_math.american_to_probability(price) + 0.03, 4)
        return {"slot_id": "moneyline", "market": "moneyline", "selection": "TB", "verdict": "TAKE",
                "price": price, "book": book, "fair_estimate": fair, "confidence": "medium",
                "reasons": [{"claim": "The home side is the clear favourite.",
                             "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}]}],
                "pass_price": int(round(odds_math.probability_to_american(fair))),
                "what_would_change_it": "A scratch of the home starter.",
                "case_against": {"claim": "The home side is the books' favourite.",
                  "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}]}}

    def test_a_take_on_a_moneyline_at_minus_200_or_worse_is_struck_to_pass(self):
        packet = self.packet()
        out = F.good_output(packet)
        out["calls"][0] = self.take_home(packet, -240)
        v = C.verify(packet, out)
        self.assertIn("moneyline", struck_ids(v))
        pub = call(v, "moneyline")
        self.assertEqual(pub["verdict"], "PASS")
        self.assertTrue(any("-200 or worse" in p for p in v.struck[0]["problems"]))

    def test_exactly_minus_200_is_also_refused(self):
        rows = F.multibook_rows(home_ml=(-200, -200, -200), away_ml=(170, 170, 170))
        packet = F.build(multibook_rows=rows)
        out = F.good_output(packet)
        out["calls"][0] = self.take_home(packet, -200)
        self.assertIn("moneyline", struck_ids(C.verify(packet, out)))

    def test_minus_199_is_allowed(self):
        rows = F.multibook_rows(home_ml=(-199, -199, -199), away_ml=(170, 170, 170))
        packet = F.build(multibook_rows=rows)
        out = F.good_output(packet)
        out["calls"][0] = self.take_home(packet, -199)
        self.assertNotIn("moneyline", struck_ids(C.verify(packet, out)))

    def test_every_market_is_held_to_the_floor_not_only_the_moneyline(self):
        """A prop under at -263 is "not an advertising pick" just as a -240 favourite is."""
        packet = F.build()
        prop = next(s for s, m in packet["markets"].items()
                    if m["market"] == "prop" and m["options"][0]["best"]["price"] <= -150)
        market = packet["markets"][prop]
        opt = market["options"][0]
        # build a market whose lean is priced at -263 by editing the frozen packet in memory
        packet["markets"][prop]["options"][0]["quotes"] = [
            {"book": "betonlineag", "price": -263, "captured_utc": F.CAPTURED}]
        packet["markets"][prop]["options"][0]["best"] = {"price": -263, "book": "betonlineag"}
        fair = round(odds_math.american_to_probability(-263) + 0.03, 4)
        out = F.good_output(packet)
        call = F.pass_call(packet, prop)
        call.update(verdict="TAKE", selection=opt["selection"], price=-263, book="betonlineag",
                    fair_estimate=fair, confidence="medium",
                    pass_price=int(round(odds_math.probability_to_american(fair))),
                    case_against=F.case_against_for(packet, prop))
        out["calls"] = [call if c["slot_id"] == prop else c for c in out["calls"]]
        v = C.verify(packet, out)
        self.assertIn(prop, struck_ids(v))
        self.assertTrue(any("-200 or worse" in p for p in v.struck[0]["problems"]))
        # the other side of the same market, at a plus price, is not caught by it
        other = market["options"][1]
        take_other = F.pass_call(packet, prop)
        take_other.update(verdict="TAKE_OTHER_SIDE", selection=other["selection"],
                          price=other["best"]["price"], book=other["best"]["book"])
        fe = round(odds_math.american_to_probability(other["best"]["price"]) + 0.03, 4)
        take_other.update(fair_estimate=fe, confidence="medium",
                          pass_price=int(round(odds_math.probability_to_american(fe))),
                          case_against=F.case_against_for(packet, prop))
        out["calls"] = [take_other if c["slot_id"] == prop else c for c in out["calls"]]
        self.assertNotIn(prop, struck_ids(C.verify(packet, out)))

    def test_a_pass_on_a_heavy_favourite_is_fine(self):
        packet = self.packet()
        out = F.good_output(packet)
        out["calls"][0] = F.pass_call(packet, "moneyline")
        self.assertEqual(C.verify(packet, out).struck, [])


class CoherenceOfATake(unittest.TestCase):
    def test_a_fair_estimate_below_the_price_breakeven_contradicts_itself(self):
        def m(o):
            c = o["calls"][0]
            c["fair_estimate"] = 0.30
            c["pass_price"] = int(round(odds_math.probability_to_american(0.30)))
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertTrue(any("contradicts itself" in p for p in v.struck[0]["problems"]))

    def test_a_pass_price_that_is_not_the_breakeven_of_the_estimate_is_struck(self):
        def m(o):
            o["calls"][0]["pass_price"] = 400
        v = verify(F.build(), m)
        self.assertTrue(any("not the break-even price" in p for p in v.struck[0]["problems"]))

    def test_a_pass_price_better_than_the_price_taken_is_struck(self):
        packet = F.build()
        out = F.good_output(packet)
        c = out["calls"][0]
        c["fair_estimate"] = round(odds_math.american_to_probability(c["price"]) - 0.001 + 0.0, 4) + 0.001
        c["pass_price"] = c["price"] + 40   # a better price for the bettor than the one taken
        self.assertIn("moneyline", struck_ids(C.verify(packet, out)))

    def test_a_take_needs_an_estimate_and_a_pass_price(self):
        def m(o):
            o["calls"][0].update(fair_estimate=None, pass_price=None)
        problems = " | ".join(verify(F.build(), m).struck[0]["problems"])
        self.assertIn("needs a fair_estimate", problems)
        self.assertIn("needs a pass_price", problems)


class BannedWords(unittest.TestCase):
    def test_banned_words_in_a_claim_strike_the_call(self):
        for word in ("a lock", "guaranteed", "free money", "a sure thing", "can't lose", "+EV"):
            def m(o, word=word):
                o["calls"][1]["reasons"][0]["claim"] = f"This is {word} on the books' own number."
            self.assertEqual(struck_ids(verify(F.build(), m)), ["run_line"], word)

    def test_edge_is_banned_unless_it_is_denied(self):
        self.assertEqual(C.banned_words("There is no edge here."), [])
        self.assertEqual(C.banned_words("I do not have an edge on this."), [])
        self.assertEqual(C.banned_words("I have an edge on this."), ["edge"])

    def test_the_other_banned_words_are_matched_on_word_boundaries(self):
        self.assertEqual(C.banned_words("The lineup is not locked."), ["lock"])
        self.assertEqual(C.banned_words("A clockwork bullpen."), [])
        self.assertEqual(C.banned_words("Bet Check says so"), ["Bet Check"])

    def test_a_banned_word_in_the_summary_withholds_it(self):
        v = verify(F.build(), lambda o: o.update(summary=o["summary"] + " This one is a lock."))
        self.assertEqual(v.summary_status, "withheld")


class StrikeNeverSilentlyKeep(unittest.TestCase):
    def test_a_struck_call_is_published_as_a_pass_that_says_it_could_not_be_verified(self):
        def m(o):
            o["calls"][0]["reasons"][1]["claim"] = "He has a 2.17 ERA."
        v = verify(F.build(), m)
        pub = call(v, "moneyline")
        self.assertEqual(pub["verdict"], "PASS")
        self.assertEqual(pub["verification"]["status"], "could not be verified")
        self.assertIn("Could not be verified", pub["reasons"][0]["claim"])
        self.assertIsNone(pub["fair_estimate"])
        self.assertIsNone(pub["pass_price"])
        self.assertEqual(pub["confidence"], "low")

    def test_what_the_model_asserted_is_not_in_the_published_call_but_is_in_the_audit(self):
        def m(o):
            o["calls"][0]["reasons"][1]["claim"] = "He has a 2.17 ERA."
        v = verify(F.build(), m)
        pub = call(v, "moneyline")
        self.assertNotIn("2.17", str(pub))
        self.assertIn("2.17", str(v.struck[0]["original"]))
        self.assertEqual(v.struck[0]["original"]["verdict"], "TAKE_OTHER_SIDE")

    def test_the_struck_pass_keeps_only_a_real_selection_and_quote(self):
        def m(o):
            c = o["calls"][0]
            c.update(selection="NYY", price=125, book="draftkings")    # not a real quote
        pub = call(verify(F.build(), m), "moneyline")
        self.assertEqual(pub["selection"], "NYY")
        self.assertIsNone(pub["price"])
        self.assertIsNone(pub["book"])
        def n(o):
            o["calls"][0]["selection"] = "BOS"
        self.assertEqual(call(verify(F.build(), n), "moneyline")["selection"], "TB")   # the lean

    def test_one_bad_call_does_not_strike_the_good_ones(self):
        def m(o):
            o["calls"][1]["reasons"][0]["claim"] = "A 9.99 thing."
        v = verify(F.build(), m)
        self.assertEqual(struck_ids(v), ["run_line"])
        self.assertEqual(call(v, "moneyline")["verdict"], "TAKE_OTHER_SIDE")

    def test_every_published_call_is_one_of_the_three_verdicts(self):
        for c in verify(F.build()).calls:
            self.assertIn(c["verdict"], A.VERDICTS)


class Downgrades(unittest.TestCase):
    def test_high_confidence_on_a_single_fact_is_lowered_not_struck(self):
        def m(o):
            o["calls"][0]["confidence"] = "high"
            o["calls"][0]["reasons"] = o["calls"][0]["reasons"][:1]
            o["calls"][0]["reasons"][0]["evidence"] = o["calls"][0]["reasons"][0]["evidence"][:1]
        v = verify(F.build(), m)
        self.assertEqual(v.struck, [])
        c = call(v, "moneyline")
        self.assertEqual(c["confidence"], "medium")
        self.assertIn("fewer than two packet facts", c["verification"]["downgrades"][0])

    def test_high_confidence_on_a_stale_price_is_lowered(self):
        packet = F.build(built_at="2026-10-03T21:00:00Z")
        out = F.good_output(packet)
        out["calls"][0]["confidence"] = "high"
        v = C.verify(packet, out)
        self.assertEqual(call(v, "moneyline")["confidence"], "medium")


class TheModelCritic(unittest.TestCase):
    def test_it_can_strike_a_call_the_deterministic_pass_kept(self):
        packet = F.build()
        out = F.good_output(packet)
        verdict = {"checks": [{"slot_id": "moneyline", "supported": False,
                               "problem": "the FIP gap does not support the lean"}],
                   "summary_supported": True, "summary_problem": ""}
        v = C.verify(packet, out, model_critic=verdict, model_critic_status="ran")
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertIn("model critic: the FIP gap", v.struck[0]["problems"][0])
        self.assertEqual(v.model_critic, "ran")
        self.assertEqual(call(v, "moneyline")["verdict"], "PASS")

    def test_it_can_withhold_a_summary(self):
        packet = F.build()
        v = C.verify(packet, F.good_output(packet),
                     model_critic={"checks": [], "summary_supported": False,
                                   "summary_problem": "overreaches"}, model_critic_status="ran")
        self.assertEqual(v.summary_status, "withheld")

    def test_it_cannot_rescue_a_call_the_deterministic_pass_struck(self):
        packet = F.build()
        out = F.good_output(packet)
        out["calls"][0]["reasons"][1]["claim"] = "A 2.17 ERA."
        verdict = {"checks": [{"slot_id": "moneyline", "supported": True, "problem": ""}],
                   "summary_supported": True, "summary_problem": ""}
        self.assertEqual(struck_ids(C.verify(packet, out, model_critic=verdict)), ["moneyline"])

    def test_the_critic_request_carries_the_packet_and_the_analysis(self):
        packet = F.build()
        out = F.good_output(packet)
        body = A.build_critic_request(packet, out, F.CFG)
        text = body["messages"][0]["content"]
        self.assertIn(A.packet_json(packet), text)
        self.assertIn("TAKE_OTHER_SIDE", text)
        self.assertEqual(body["output_config"]["format"]["schema"], A.CRITIC_SCHEMA)

    def test_running_it_reports_usage_and_cost(self):
        packet = F.build()
        out = F.good_output(packet)
        verdict = {"checks": [{"slot_id": "moneyline", "supported": True, "problem": ""}],
                   "summary_supported": True, "summary_problem": ""}
        http = F.FakeHttp((200, F.api_response(verdict, {"input_tokens": 12000, "output_tokens": 500})))
        got, usage, cost = A.run_model_critic(packet, out, F.CFG, api_key="k", http_post=http)
        self.assertEqual(got["checks"][0]["slot_id"], "moneyline")
        self.assertAlmostEqual(cost, 12000 * 2 / 1e6 + 500 * 10 / 1e6)

    def test_a_critic_failure_is_an_error_never_an_all_clear(self):
        http = F.FakeHttp((200, F.api_response("not json")))
        with self.assertRaises(A.MalformedOutput):
            A.run_model_critic(F.build(), F.good_output(F.build()), F.CFG, api_key="k", http_post=http)
        with self.assertRaises(A.Blocked):
            A.run_model_critic(F.build(), F.good_output(F.build()), F.CFG, api_key=None, http_post=http)


if __name__ == "__main__":
    unittest.main()
