"""A hound's identity (src/hounds/interact/identity.py), the evidence bar, "why it lost" (loss_why.py) and the tweak words
"keep the sports" / "focus on hockey" (retune.py).

THE STORY (production 2026-10-29). HOCKEYCHIEF, a hound its owner named for hockey, bet NHL, tennis and MLB. Its training card said
"5 NHL bets went 2-3 (-0.42u at the average price), its weakest part, so the new version no longer takes them" while the coach's own read
said the losing run turns up in 78% of random orders of the same results. The owner typed "THE ONLY TWEAKS YOU HAVE ARE CHANGING THE
SPORTS IT BETTING ON. NO THANKS YOU". Every test here pins one piece of the answer: the core is never proposed for removal, five bets
are not a pattern, the losses are sorted into luck / price / read, and the owner's own words are understood.

No FastAPI, no network, no model: the router is a fake and the ledger is a list of rows.
"""

from __future__ import annotations

import re
import unittest

from src.hounds import user_spec, user_store
from src.hounds.interact import identity, loss_why, retune, rites, training
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for, ticket
from tests._hounds_user_fixtures import spec_dict
from tests.test_hounds_coach import FakeAnswer, FakeRouter

# The owner's tweak, character for character (typos, caps and all).
OWNER_LINE = ("THIS HOUNDS NAME IS hockeychief, WE'RE TRYING TO HAVE IT BE THE best hockey sports BETTER aiu hoUND OUT THERE AND SO FAR "
              "THE ONLY TWEAKS YOU HAVE ARE CHANGING THE SPORTS IT BETTING ON. NO THANKS YOU")
BANNED = re.compile(r"\b(better|improve\w*|stronger|smarter|profit\w*|will win|edge|lock|beta|bet check|dogs?)\b", re.I)
SPORTS = ["MLB", "NHL", "TENNIS"]


def win(sport, n, prices=(130, 150)):
    return [(1, dict(result="WIN", sport=sport, price=prices[i % len(prices)])) for i in range(n)]


def loss(sport, n, price=130):
    return [(n, dict(result="LOSS", sport=sport, price=price))]


# 5 NHL bets that went 2-3 among a hound that is otherwise fine: the production card, in numbers
PRODUCTION = win("NHL", 2, (130,)) + loss("NHL", 3) + win("MLB", 7) + loss("MLB", 3) + win("TENNIS", 3) + loss("TENNIS", 2)
# NHL clearly the worst part over 12 bets (2-10), everything else winning: a real weak spot, in the sport the hound is for
NHL_BAD = win("NHL", 2) + loss("NHL", 10) + win("MLB", 9) + loss("MLB", 2) + win("TENNIS", 8) + loss("TENNIS", 1)
# MLB clearly the worst part over 12 bets, NHL fine: a real weak spot in a sport the hound is NOT for
MLB_BAD = win("NHL", 9) + loss("NHL", 3) + win("MLB", 2) + loss("MLB", 10) + win("TENNIS", 8) + loss("TENNIS", 1)


class Case(RitesCase):
    def hockey(self, name="HOCKEYCHIEF", **spec):
        return self.dog(name, sports=SPORTS, **spec)

    def review(self, hound, plan, **kw):
        kw.setdefault("now", NOW)
        if "rows" not in kw:
            kw["rows"] = rows_for(hound["id"], plan)
        return training.review(self.resolve(hound["id"]), self.owner.id, **kw)

    def assertUntouched(self, hound):
        self.assertEqual(len(user_store.lineage(hound["id"])), 1, "no version was made")
        self.assertEqual(user_store.list_events(root_id=hound["root_id"]), [], "no life event was written")
        self.assertEqual(user_store.trained_count(hound["root_id"]), 0, "it does not count as a training")


# ---------------------------------------------------------------------------------------------------------------
# the core
# ---------------------------------------------------------------------------------------------------------------

class TheCoreIsReadFromTheNameAndTheWords(unittest.TestCase):
    def test_hockeychief_is_a_hockey_hound(self):
        self.assertEqual(identity.core_of({"name": "HOCKEYCHIEF"}), ["NHL"])

    def test_the_word_map(self):
        cases = {"Puck Daddy": ["NHL"], "Ice": ["NHL"], "Baseball Bob": ["MLB"], "TennisAce": ["TENNIS"], "ATP Hunter": ["TENNIS"],
                 "Gridiron Gus": ["GRIDIRON"], "Football Fred": ["NFL"], "UFC Mike": ["MMA"], "Octagon MMA": ["MMA"],
                 "Hoops Basketball": ["NBA"], "BigNBA": ["NBA"], "NHL and MLB Max": ["MLB", "NHL"]}
        for name, want in cases.items():
            with self.subTest(name=name):
                self.assertEqual(identity.core_of({"name": name}), want)

    def test_a_word_that_only_contains_one_of_the_words_is_not_a_match(self):
        for name in ("Dice Roller", "Iced Out", "Mamma Mia", "Police Dog", "Service Pup", "Rusty Pup"):
            with self.subTest(name=name):
                self.assertEqual(identity.core_of({"name": name}), [])

    def test_the_english_description_counts_too(self):
        hound = {"name": "Rusty Pup", "tagline": "Bets hockey underdogs", "spec": {"sports": ["MLB", "NHL"]}}
        self.assertEqual(identity.identity_of(hound), {"sports": ["NHL"], "markets": [], "source": "description"})

    def test_a_custom_rule_label_counts_as_description(self):
        spec = {"sports": ["MLB", "NHL"], "rules": [{"label": "Puck line dogs", "sports": ["NHL"]}]}
        self.assertEqual(identity.identity_of({"name": "Rusty Pup", "spec": spec})["sports"], ["NHL"])

    def test_the_name_wins_the_source(self):
        hound = {"name": "HOCKEYCHIEF", "tagline": "tennis underdogs", "spec": {"sports": ["NHL", "TENNIS"]}}
        self.assertEqual(identity.identity_of(hound), {"sports": ["NHL", "TENNIS"], "markets": [], "source": "name"})

    def test_a_sport_the_hound_does_not_bet_is_not_core(self):
        """A hound named for hockey that bets MLB only has nothing in the core to protect."""
        self.assertEqual(identity.core_of({"name": "HOCKEYCHIEF", "spec": {"sports": ["MLB"]}}), [])

    def test_an_explicit_core_on_the_spec_is_the_source_and_wins(self):
        spec = user_spec.validate_spec(spec_dict(name="Rusty Pup", sports=["MLB", "NFL"], core=["NFL"]))
        self.assertEqual(spec["core"], ["NFL"])
        self.assertEqual(identity.identity_of({"name": "Rusty Pup", "spec": spec}), {"sports": ["NFL"], "markets": [], "source": "spec"})

    def test_markets_named_in_the_words_are_core_markets(self):
        hound = {"name": "Totals Tom", "tagline": "", "spec": {"sports": ["MLB"], "markets": ["moneyline", "total"]}}
        self.assertEqual(identity.identity_of(hound)["markets"], ["total"])

    def test_the_view_the_card_carries(self):
        core = identity.identity_of({"name": "HOCKEYCHIEF", "spec": {"sports": SPORTS}})
        self.assertEqual(identity.core_view(core), {"sports": ["NHL"], "markets": [], "source": "name", "kept": True, "text": "Core: NHL (kept)"})
        self.assertEqual(identity.core_view(None)["text"], "")


class TheSpecFieldIsOptionalAndNeverMovesAHash(unittest.TestCase):
    def test_a_spec_without_a_core_is_what_it_always_was(self):
        spec = user_spec.validate_spec(spec_dict())
        self.assertNotIn("core", spec)

    def test_the_hash_does_not_depend_on_the_core_for_either_version_of_the_spec(self):
        v1 = user_spec.validate_spec(spec_dict(name="Hash One", sports=["MLB", "NHL"]))
        v1_core = user_spec.validate_spec(spec_dict(name="Hash One", sports=["MLB", "NHL"], core=["NHL"]))
        self.assertEqual(user_spec.spec_hash(v1), user_spec.spec_hash(v1_core))
        raw = {"version": 2, "name": "Hash Two", "rules": [{"sports": ["MLB", "NHL"], "markets": ["moneyline"], "side": "either"}]}
        v2, v2_core = user_spec.validate_spec(raw), user_spec.validate_spec({**raw, "core": ["NHL"]})
        self.assertEqual((v2_core["core"], user_spec.spec_hash(v2)), (["NHL"], user_spec.spec_hash(v2_core)))

    def test_the_core_is_validated_against_the_sport_menu(self):
        for bad in (["QUIDDITCH"], [1], ["NHL", "NHL"], {"NHL": 1}):
            with self.subTest(core=bad):
                with self.assertRaises(user_spec.SpecError) as ctx:
                    user_spec.validate_spec(spec_dict(core=bad))
                self.assertIn("core", ctx.exception.errors)
        self.assertNotIn("core", user_spec.validate_spec(spec_dict(core=[])))
        self.assertEqual(user_spec.validate_spec(spec_dict(sports=["MLB", "NHL"], core="NHL"))["core"], ["NHL"], "a bare word is a list of one, as for sports")

    def test_the_core_survives_a_second_validation(self):
        spec = user_spec.validate_spec(spec_dict(name="Again Pup", sports=["MLB", "NHL"], core=["NHL"]))
        self.assertEqual(user_spec.validate_spec(spec), spec)


# ---------------------------------------------------------------------------------------------------------------
# the identity lock and the evidence bar, on the production hound
# ---------------------------------------------------------------------------------------------------------------

class HockeychiefKeepsItsHockey(Case):
    def test_five_nhl_bets_at_2_3_are_not_a_pattern_so_the_card_says_keep_going(self):
        """The production card, as it should have read: nothing is cut, the numbers are said, and nothing is written."""
        hound = self.hockey()
        card = self.review(hound, PRODUCTION)
        self.assertEqual((card["mode"], card["nothing"], card["changes"], card["picks"]), ("keep", True, [], []))
        self.assertEqual(card["message"], "2-3 on 5 NHL bets is too few to tell from luck at these prices. Nothing here is a pattern yet, "
                                          "so HOCKEYCHIEF keeps its rule.")
        self.assertEqual(card["core"], {"sports": ["NHL"], "markets": [], "source": "name", "kept": True, "text": "Core: NHL (kept)"})
        self.assertUntouched(hound)

    def test_the_default_plan_never_drops_nhl_even_when_nhl_is_clearly_the_worst_part(self):
        hound = self.hockey()
        card = self.review(hound, NHL_BAD)
        self.assertEqual((card["mode"], card["changes"]), ("keep", []))
        self.assertIn("2-10 on 12 NHL bets is its weakest part, but NHL is what HOCKEYCHIEF is for, so the coach does not cut it.", card["message"])
        self.assertUntouched(hound)

    def test_the_same_record_on_a_hound_that_is_not_for_hockey_does_drop_it(self):
        """The control: the evidence is real, so a hound that is not for NHL is still coached out of it."""
        hound = self.dog("Rusty Pup", sports=SPORTS)
        card = self.review(hound, NHL_BAD)
        self.assertEqual(card["mode"], "analysed")
        self.assertEqual(card["changes"][0]["id"], "drop_sport")
        self.assertIn("12 NHL bets went 2-10", card["changes"][0]["why"])
        self.assertEqual(card["core"]["sports"], [])
        self.assertEqual(card["core"]["text"], "")

    def test_a_default_training_at_apply_time_refuses_in_words_and_writes_nothing(self):
        hound = self.hockey()
        with self.assertRaises(rites.RiteError) as ctx:
            training.train(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows_for(hound["id"], NHL_BAD),
                           env={}, background=False)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("nothing_to_change", 409))
        self.assertIn("NHL is what HOCKEYCHIEF is for", str(ctx.exception))
        self.assertUntouched(hound)

    def test_a_bad_slice_of_a_sport_the_hound_is_not_for_still_gets_a_change(self):
        """The evidence bar is a bar, not a wall: 12 MLB bets at 2-10 clear it, and MLB is not the core. NHL stays."""
        hound = self.hockey()
        card = self.review(hound, MLB_BAD)
        self.assertEqual(card["mode"], "analysed")
        sports = [c for c in card["changes"] if c["id"] == "drop_sport"]
        self.assertEqual([c["new_text"] for c in sports], ["NHL and tennis"])
        self.assertIn("12 MLB bets went 2-10", sports[0]["why"])
        self.assertEqual(card["core"]["text"], "Core: NHL (kept)")

    def test_the_analysis_holds_the_core_back_instead_of_hiding_it(self):
        hound = self.hockey()
        rows = rows_for(hound["id"], NHL_BAD)
        spec = user_store.get_hound(hound["id"])["spec"]
        core = identity.identity_of(user_store.get_hound(hound["id"]))
        analysis = training.analyse(rites.forward_bets(hound["id"], rows), spec, core=core)
        self.assertNotIn(("sport", "NHL"), [(s["dimension"], s["key"]) for s in analysis["weak"]])
        self.assertEqual([(h["key"], h["reason"]) for h in analysis["held"] if h["dimension"] == "sport"], [("NHL", "core")])
        without = training.analyse(rites.forward_bets(hound["id"], rows), spec)
        self.assertIn(("sport", "NHL"), [(s["dimension"], s["key"]) for s in without["weak"]])

    def test_the_menu_never_offers_a_core_sport_for_removal_unless_the_owner_asks_for_that_one(self):
        hound = self.hockey()
        spec = user_store.get_hound(hound["id"])["spec"]
        core = identity.identity_of(user_store.get_hound(hound["id"]))
        analysis = {"weak": []}

        def cids(lines, enforce=True):
            return {e["cid"] for e in retune.full_menu(spec, analysis, None, core=core, lines=lines, enforce=enforce)}
        self.assertNotIn("drop_sport:NHL", cids([]))
        self.assertIn("drop_sport:TENNIS", cids([]), "only the core is locked")
        self.assertNotIn("drop_sport:NHL", cids(["change the sports"]), "a change to the sports is not an ask to drop hockey")
        self.assertNotIn("drop_sport:NHL", cids(["do not drop hockey"]))
        self.assertNotIn("drop_sport:NHL", cids(["stop dropping the sports"]))
        self.assertNotIn("drop_sport:NHL", cids([OWNER_LINE]))
        for ask in ("drop hockey", "stop betting NHL", "please remove the NHL", "no more hockey"):
            with self.subTest(ask=ask):
                self.assertIn("drop_sport:NHL", cids([ask]))
        self.assertIn("drop_sport:NHL", cids([], enforce=False), "Apply re-checks a card the owner has read")

    def test_an_owner_who_asks_to_drop_hockey_can_apply_that_and_only_that(self):
        hound = self.hockey()
        rows = rows_for(hound["id"], PRODUCTION)
        out = training.train(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows, env={}, background=False,
                             picks=["drop_sport:NHL"])
        self.assertEqual(user_store.get_hound(out["new"]["id"])["spec"]["sports"], ["MLB", "TENNIS"])


# ---------------------------------------------------------------------------------------------------------------
# the evidence bar
# ---------------------------------------------------------------------------------------------------------------

class TheEvidenceBar(unittest.TestCase):
    def analyse(self, plan, sports=("MLB", "NFL")):
        spec = user_spec.validate_spec(spec_dict(sports=list(sports)))
        return training.analyse(rites.forward_bets("u-x", rows_for("u-x", plan)), spec)

    def test_the_floor_is_ten_bets_and_a_signal(self):
        self.assertEqual((training.MIN_SEGMENT_BETS, training.MIN_SEGMENT_LEVEL), (10, "medium"))

    def test_nine_bad_bets_are_thin_and_ten_bad_bets_against_a_good_rest_are_weak(self):
        thin = self.analyse(loss("MLB", 9) + win("NFL", 12))
        self.assertEqual([(h["key"], h["reason"]) for h in thin["held"] if h["dimension"] == "sport"], [("MLB", "thin")])
        ten = self.analyse(loss("MLB", 10) + win("NFL", 12))
        self.assertIn(("sport", "MLB"), [(s["dimension"], s["key"]) for s in ten["weak"]])

    def test_a_slice_the_coach_table_rates_below_some_signal_is_not_weak(self):
        from src.hounds.interact import diagnosis
        plan = loss("MLB", 6, 120) + win("MLB", 6, (120,)) + loss("NFL", 4, 120) + win("NFL", 5, (120,)) + win("NFL", 1, (140,))
        a = self.analyse(plan)
        mlb = next(s for s in a["segments"]["sport"] if s["key"] == "MLB")
        self.assertGreaterEqual(mlb["n"], training.MIN_SEGMENT_BETS)
        self.assertEqual(a["weak"], [])
        self.assertEqual(diagnosis.level_of(mlb["n"], 0.0), "low")


# ---------------------------------------------------------------------------------------------------------------
# keeping the sports, in the owner's words
# ---------------------------------------------------------------------------------------------------------------

class TheTweakMapperUnderstandsKeepAndFocus(Case):
    def setUp(self):
        super().setUp()
        self.hound = self.hockey()
        stored = user_store.get_hound(self.hound["id"])
        self.spec = stored["spec"]
        self.core = identity.identity_of(stored)
        self.entries = training._menu_for(self.spec, {"weak": []}, None, None, core=self.core)      # noqa: SLF001

    def map(self, *lines, router=None):
        return retune.map_chat(list(lines), self.entries, {"base": None, "by_cid": {}}, router=router, env={})

    def test_the_two_items_are_on_the_closed_menu(self):
        by = {e["cid"]: e for e in self.entries}
        self.assertEqual(by[retune.KEEP_CID]["text"], "Sports: keep them as they are")
        self.assertEqual(by[retune.FOCUS_CID]["text"], "Sports: MLB, NHL and tennis to NHL")
        self.assertEqual(by[retune.FOCUS_CID]["direction"], "narrow")

    def test_the_owners_exact_line_maps_to_keep_the_sports(self):
        out = self.map(OWNER_LINE)
        self.assertEqual(out["source"], "rules")
        self.assertEqual([(i["cid"], i["line"], i["text"]) for i in out["items"]], [(retune.KEEP_CID, 0, OWNER_LINE)])

    def test_common_phrasings(self):
        cases = {"stop changing sports": retune.KEEP_CID, "Stop changing the sports!": retune.KEEP_CID,
                 "dont change the sports": retune.KEEP_CID, "keep the sports as they are": retune.KEEP_CID,
                 "keep NHL": retune.KEEP_CID, "leave the sports alone": retune.KEEP_CID,
                 "only hockey": retune.FOCUS_CID, "focus on hockey": retune.FOCUS_CID, "Only NHL please": retune.FOCUS_CID,
                 "stick to hockey": retune.FOCUS_CID}
        for line, cid in cases.items():
            with self.subTest(line=line):
                self.assertEqual([i["cid"] for i in self.map(line)["items"]], [cid])

    def test_a_request_for_more_sports_or_another_sport_is_not_a_keep_or_a_focus(self):
        for line in ("please add more sports", "only tennis", "change the sports to add NFL", "look at other leagues"):
            with self.subTest(line=line):
                self.assertNotIn(self.map(line)["items"][0]["cid"] if self.map(line)["items"] else None, (retune.KEEP_CID, retune.FOCUS_CID))

    def test_a_model_may_pick_them_too_and_the_pick_is_vetted_like_any_other(self):
        router = FakeRouter(FakeAnswer(output={"items": [{"cid": "keep_sports", "line": 0, "quote": "THE ONLY TWEAKS YOU HAVE"}]}))
        out = retune.map_chat([OWNER_LINE], self.entries, {"base": None, "by_cid": {}}, router=router)
        self.assertEqual((out["source"], [i["cid"] for i in out["items"]]), ("ai", [retune.KEEP_CID]))
        system, user, _kw = router.calls[0]
        self.assertIn("keep_sports", system)
        self.assertNotIn("HOCKEYCHIEF", system, "the owner's words never reach the instructions")


class TheOwnersTweakOnTheCard(Case):
    def test_keep_the_sports_takes_every_sport_change_out_and_says_so(self):
        """The owner's exact line, on a hound whose only evidence is a bad MLB slice: no sport is dropped, and the card says why."""
        hound = self.hockey()
        card = self.review(hound, MLB_BAD, tweak=OWNER_LINE, router=None, env={})
        self.assertTrue(card["kept_sports"])
        self.assertEqual(card["kept_note"], "Sports kept as they are, as you asked.")
        self.assertFalse([c for c in card["changes"] if c["id"] in retune.SPORT_CHANGE_IDS])
        self.assertEqual((card["mode"], card["nothing"]), ("keep", True))
        self.assertIn("You asked to keep the sports as they are, so no sport change is proposed.", card["message"])
        self.assertEqual((card["mapper"]["source"], card["tweak"]["used"]), ("rules", 1))
        self.assertUntouched(hound)

    def test_keep_the_sports_still_lets_the_rest_of_the_default_plan_through(self):
        """With a bad price band and a bad sport at once, 'keep the sports' drops only the sport."""
        hound = self.dog("Rusty Pup", sports=["MLB", "NFL"], price_min=100, price_max=400)
        plan = loss("MLB", 12, 300) + win("NFL", 6, (130,)) + win("NFL", 6, (150,))
        plain = self.review(hound, plan)
        self.assertIn("drop_sport", [c["id"] for c in plain["changes"]])
        kept = self.review(hound, plan, tweak="stop changing sports", router=None, env={})
        self.assertTrue(kept["kept_sports"])
        self.assertTrue(kept["changes"], "the band is not a sport")
        self.assertFalse([c for c in kept["changes"] if c["id"] in retune.SPORT_CHANGE_IDS])

    def test_focus_on_hockey_narrows_to_the_core_and_applies_through_the_normal_gate(self):
        hound = self.hockey()
        rows = rows_for(hound["id"], PRODUCTION)
        card = self.review(hound, PRODUCTION, tweak="focus on hockey", router=None, env={})
        self.assertEqual([(c["id"], c["old_text"], c["new_text"], c["direction"]) for c in card["changes"]],
                         [("focus_sports", "MLB, NHL and tennis", "NHL", "narrow")])
        self.assertEqual(card["changes"][0]["cite"]["text"], "focus on hockey")
        self.assertUntouched(hound)
        out = training.train(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows, env={}, background=False,
                             picks=card["picks"], basis=card["basis"])
        new = user_store.get_hound(out["new"]["id"])["spec"]
        self.assertEqual((new["sports"], new, user_spec.validate_spec(new)), (["NHL"], new, new))
        self.assertLessEqual(new["price_min"], new["price_max"])
        self.assertFalse(user_spec.beyond_cap(new["price_min"]), "the -200 cap is untouched")

    def test_focus_on_another_sport_is_not_offered_on_a_hockey_hound(self):
        hound = self.hockey()
        card = self.review(hound, PRODUCTION, tweak="only tennis", router=None, env={})
        self.assertEqual((card["nothing"], card["changes"]), (True, []))
        self.assertFalse(card["kept_sports"])

    def test_the_whole_card_promises_nothing_and_says_none_of_the_banned_words(self):
        hound = self.hockey()
        for card in (self.review(hound, PRODUCTION), self.review(hound, NHL_BAD), self.review(hound, MLB_BAD)):
            text = " ".join([card["message"], card["core"]["text"], *card["losses"]["lines"], *[c["why"] for c in card["changes"]]])
            self.assertIsNone(BANNED.search(text), text)


# ---------------------------------------------------------------------------------------------------------------
# why it lost
# ---------------------------------------------------------------------------------------------------------------

def lost(kind="NHL", *, bet_id="b1", market="h2h", side="home", line=None, away=None, home=None, clv=None, selection="", date="2026-10-01"):
    return {"bet_id": bet_id, "result": "loss", "sport": kind, "market": market, "side": side, "line": line, "selection": selection, "date": date,
            "away_score": away, "home_score": home, "clv_pts": clv}


class WhyItLost(unittest.TestCase):
    def kind(self, row, review=None):
        return loss_why.classify(row, review)[0]

    def test_beating_the_close_and_still_losing_is_bad_luck(self):
        self.assertEqual(self.kind(lost(clv=1.4)), "bad_luck")

    def test_the_price_moving_against_the_pick_is_a_bad_price(self):
        self.assertEqual(self.kind(lost(clv=-2.2)), "bad_price")

    def test_a_hindsight_process_verdict_is_a_bad_read(self):
        self.assertEqual(self.kind(lost(), "mostly_process"), "bad_read")
        self.assertEqual(self.kind(lost(), {"luck_vs_process": "mostly_process", "grounded": True}), "bad_read")

    def test_precedence_hindsight_process_beats_the_closing_price_and_the_margin(self):
        row = lost(clv=3.0, home=2, away=3)
        self.assertEqual(self.kind(row), "bad_luck")
        self.assertEqual(self.kind(row, "mostly_process"), "bad_read")

    def test_a_hindsight_luck_verdict_is_bad_luck_even_against_a_bad_price(self):
        self.assertEqual(self.kind(lost(clv=-2.0), "mostly_luck"), "bad_luck")

    def test_a_mixed_unclear_or_ungrounded_review_falls_through_to_the_numbers(self):
        for review in ("mixed", "unclear", {"luck_vs_process": "mostly_process", "grounded": False}, {"luck_vs_process": None}, 7):
            with self.subTest(review=review):
                self.assertEqual(self.kind(lost(clv=-1.0), review), "bad_price")

    def test_the_closing_price_beats_the_margin_and_the_margin_speaks_when_it_is_missing_or_flat(self):
        close = dict(home=2, away=3)
        self.assertEqual(self.kind(lost(clv=-1.0, **close)), "bad_price", "lost by one, but the market also disagreed")
        self.assertEqual(self.kind(lost(clv=0.0, **close)), "bad_luck")
        self.assertEqual(self.kind(lost(**close)), "bad_luck")

    def test_close_means_one_in_nhl_mlb_and_soccer_and_three_in_football_and_basketball(self):
        self.assertEqual(self.kind(lost("NHL", home=2, away=3)), "bad_luck")
        self.assertEqual(self.kind(lost("NHL", home=1, away=3)), "unclear")
        self.assertEqual(self.kind(lost("MLB", home=4, away=5)), "bad_luck")
        self.assertEqual(self.kind(lost("SOCCER", home=0, away=1)), "bad_luck")
        self.assertEqual(self.kind(lost("NFL", home=20, away=23)), "bad_luck")
        self.assertEqual(self.kind(lost("NFL", home=20, away=24)), "unclear")
        self.assertEqual(self.kind(lost("NBA", home=100, away=103)), "bad_luck")
        self.assertEqual(self.kind(lost("NBA", home=100, away=104)), "unclear")

    def test_the_margin_reads_a_spread_from_the_pick_and_a_total_from_the_line(self):
        self.assertEqual(self.kind(lost("NHL", market="spreads", side="home", line="-1.5", home=3, away=2)), "bad_luck")     # won by 1, needed 2
        self.assertEqual(self.kind(lost("NFL", market="spreads", side="away", line="3.5", home=30, away=20)), "unclear")     # lost by 10, +3.5
        self.assertEqual(self.kind(lost("MLB", market="totals", side="over", line="8.5", home=4, away=4)), "bad_luck")       # 8 against 8.5
        self.assertEqual(self.kind(lost("MLB", market="totals", side="under", line="8.5", home=1, away=1)), "unclear")

    def test_sports_without_a_margin_rule_and_rows_without_data_are_unclear_not_guessed(self):
        self.assertEqual(self.kind(lost("TENNIS", home=2, away=3)), "unclear", "tennis has CLV only")
        self.assertEqual(self.kind(lost("MMA", home=1, away=0)), "unclear")
        self.assertEqual(self.kind(lost("NHL")), "unclear", "no score and no closing price")
        self.assertEqual(self.kind(lost("NHL", market="player_points", side="over", line="20.5", home=2, away=3)), "unclear", "a prop is not graded by the score")
        self.assertEqual(self.kind(lost("NHL", home=None, away=3)), "unclear")

    def test_the_breakdown_counts_every_loss_once_and_ignores_wins_and_pushes(self):
        rows = [lost(bet_id="a", clv=2.0), lost(bet_id="b", clv=-1.0), lost(bet_id="c"), lost(bet_id="d"), lost(bet_id="e", home=1, away=2),
                {**lost(bet_id="w"), "result": "win"}, {**lost(bet_id="p"), "result": "push"}]
        out = loss_why.loss_breakdown(rows, {"d": "mostly_process"})
        self.assertEqual(out["counts"], {"bad_luck": 2, "bad_price": 1, "bad_read": 1, "unclear": 1})
        self.assertEqual((out["n_losses"], out["n_settled"], sum(out["counts"].values())), (5, 7, 5))
        self.assertEqual(out["hindsight"], {"read": True, "reviewed": 1})
        self.assertEqual(len(out["examples"]), 3)
        self.assertTrue(out["examples"][0].endswith("the hindsight review blames the process."), "a bad read is quoted first")

    def test_without_reviews_there_is_no_bad_read_and_it_says_it_did_not_look(self):
        out = loss_why.loss_breakdown([lost(bet_id=str(i), clv=-1.0) for i in range(6)])
        self.assertEqual((out["counts"]["bad_read"], out["hindsight"]), (0, {"read": False, "reviewed": 0}))

    def test_the_verdict_by_the_numbers(self):
        def verdict(clvs):
            return loss_why.loss_breakdown([lost(bet_id=str(i), clv=c) for i, c in enumerate(clvs)])["verdict"]
        self.assertEqual(verdict([]), "none")
        self.assertEqual(verdict([1.0, 1.0, 1.0]), "too_few")
        self.assertEqual(verdict([1.0] * 4 + [-1.0]), "variance")
        self.assertEqual(verdict([-1.0] * 4 + [1.0]), "process")
        self.assertEqual(verdict([1.0, 1.0, -1.0, -1.0, None]), "mixed")

    def test_the_lines_are_three_to_five_and_never_promise(self):
        rows = [lost(bet_id=str(i), clv=1.0 if i % 2 else -1.0, selection=f"Team {i} to win") for i in range(8)]
        rows += [{**lost(bet_id=f"w{i}"), "result": "win"} for i in range(4)]
        out = loss_why.loss_breakdown(rows)
        self.assertTrue(3 <= len(out["lines"]) <= 5, out["lines"])
        self.assertIn("Longest losing run", " ".join(out["lines"]))
        self.assertIsNone(BANNED.search(" ".join(out["lines"])), out["lines"])
        self.assertEqual(out["summary"], out["lines"][0])

    def test_the_streak_line_quotes_the_same_check_the_coach_uses(self):
        from src.hounds.interact import diagnosis
        rows = [{**lost(bet_id=f"{i:02d}", clv=1.0), "result": "win" if i in (3, 9) else "loss"} for i in range(10)]
        out = loss_why.loss_breakdown(rows)
        self.assertEqual(out["streak"], diagnosis.streak_check(rows))

    def test_no_losses_no_lines(self):
        out = loss_why.loss_breakdown([{**lost(), "result": "win"}])
        self.assertEqual((out["n_losses"], out["lines"], out["summary"]), (0, [], "No settled losses to explain."))

    def test_the_hindsight_reader_never_raises(self):
        self.assertIsNone(loss_why.live_hindsight("u-x", [object()]))


class WhyItLostOnTheCard(Case):
    def test_the_card_carries_the_breakdown_from_what_the_grader_stored(self):
        hound = self.hockey()
        rows = []
        for i in range(6):
            rows += ticket(hound["id"], day=i, result="LOSS", sport="NHL", price=130, away_score=3, home_score=2, clv_pts=1.5 if i < 3 else -1.0)
        rows += ticket(hound["id"], day=7, result="LOSS", sport="NHL", price=130)
        for i in range(8):
            rows += ticket(hound["id"], day=10 + i, result="WIN", sport="MLB", price=130 + 5 * i)
        card = self.review(hound, None, rows=rows)
        losses = card["losses"]
        self.assertEqual((losses["n_losses"], losses["counts"]), (7, {"bad_luck": 3, "bad_price": 3, "bad_read": 0, "unclear": 1}))
        self.assertEqual(losses["hindsight"]["read"], False)
        self.assertTrue(3 <= len(losses["lines"]) <= 5)

    def test_a_hindsight_reader_the_caller_hands_in_is_used_by_bet_id(self):
        hound = self.hockey()
        rows = rows_for(hound["id"], PRODUCTION)
        bets = rites.forward_bets(hound["id"], rows)
        first_loss = next(b for b in bets if b.result == "loss")
        card = self.review(hound, None, rows=rows, hindsight_fn=lambda hid, bs: {first_loss.bet_id: {"luck_vs_process": "mostly_process", "grounded": True}})
        self.assertEqual(card["losses"]["counts"]["bad_read"], 1)
        self.assertEqual(card["losses"]["hindsight"], {"read": True, "reviewed": 1})

    def test_a_breakdown_that_cannot_be_built_leaves_the_card_whole(self):
        hound = self.hockey()

        def boom(hid, bs):
            raise RuntimeError("the ledger is down")
        card = self.review(hound, PRODUCTION, hindsight_fn=boom)
        self.assertIsNone(card["losses"])
        self.assertEqual(card["mode"], "keep")


class TheInteractPackageStillCallsNoModel(unittest.TestCase):
    def test_the_new_modules_import_no_model_client_and_make_no_network_call(self):
        from pathlib import Path
        forbidden = re.compile(r"(?m)^\s*(?:import|from)\s+(anthropic|openai|requests|httpx|urllib\.request|http\.client|socket|aiohttp|websockets)\b")
        package = Path(__file__).resolve().parent.parent / "src" / "hounds" / "interact"
        for name in ("identity.py", "loss_why.py", "training.py", "retune.py"):
            self.assertIsNone(forbidden.search((package / name).read_text(encoding="utf-8")), name)


if __name__ == "__main__":
    unittest.main()
