"""Send to training (src/hounds/interact/training.py): a dog studies its own settled bets and comes back as a new version.

Owner ruling 2026-10-20: the other path is a dog "coached and transformed into a new updated version that fixes itself
with learned behavior". Every case runs without FastAPI over a temp app database. The sweep at the bottom proves the
trained spec is valid, narrower than the old one and clear of the -200 cap across version-1 and version-2 specs and every
sport on the dog menu.
"""

from __future__ import annotations

import random
import re
import unittest

from src.hounds import user_spec, user_store
from src.hounds.interact import camp, rites, training
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for, ticket
from tests._hounds_user_fixtures import spec_dict

# A dog that loses on the road in MLB and does fine at home in NFL.
MIXED = [(7, dict(result="LOSS", side="away", price=180)), (2, dict(result="WIN", side="away", price=180)),
         (6, dict(result="WIN", side="home", price=110, sport="NFL")), (3, dict(result="LOSS", side="home", price=110, sport="NFL"))]
NO_HOOK = {}                       # an environment with no Zapier hook configured


def refusal(test, fn, *a, **k):
    with test.assertRaises(rites.RiteError) as ctx:
        fn(*a, **k)
    return ctx.exception


class Train(RitesCase):
    def train(self, hound, rows, who=None, **kw):
        kw.setdefault("env", NO_HOOK)
        kw.setdefault("background", False)
        return training.train(self.resolve(hound["id"]), (who or self.owner).id, confirmed=True, now=NOW, rows=rows, **kw)

    def two_sport_dog(self, name="Rusty Pup"):
        return self.dog(name, sports=["MLB", "NFL"])


class WhoMayTrainWhat(Train):
    def test_the_owner_of_a_member_dog_can(self):
        hound = self.two_sport_dog()
        self.assertEqual(self.train(hound, rows_for(hound["id"], MIXED))["new"]["version_no"], 2)

    def test_someone_elses_dog_reads_as_not_there(self):
        hound = self.two_sport_dog()
        exc = refusal(self, self.train, hound, rows_for(hound["id"], MIXED), who=self.other)
        self.assertEqual((exc.code, exc.status), ("not_found", 404))
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")

    def test_a_house_dog_is_refused(self):
        exc = refusal(self, training.train, self.resolve("chalk_chihuahua"), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual((exc.code, exc.status), ("not_a_member_dog", 422))

    def test_without_the_confirm_nothing_changes(self):
        hound = self.two_sport_dog()
        exc = refusal(self, training.train, self.resolve(hound["id"]), self.owner.id, confirmed=False, now=NOW, rows=[])
        self.assertEqual((exc.code, exc.status), ("confirm_required", 400))
        self.assertEqual(len(user_store.lineage(hound["id"])), 1)

    def test_a_buried_or_retired_dog_cannot_train(self):
        hound = self.dog()
        user_store.bury_hound(hound["id"], owner_user_id=self.owner.id, payload={"name": "x"})
        self.assertEqual(refusal(self, self.train, hound, []).code, "already_buried")
        other = self.dog("Old Timer")
        user_store.retire_hound(other["id"], by="admin", reason="moderation")
        self.assertEqual(refusal(self, self.train, other, []).code, "not_active")


class OpenTicketsBlockTraining(Train):
    def test_an_open_ticket_blocks_it(self):
        hound = self.two_sport_dog()
        rows = rows_for(hound["id"], MIXED) + ticket(hound["id"], result=None, start_hours_ago=-3, now=NOW)
        exc = refusal(self, self.train, hound, rows)
        self.assertEqual((exc.code, exc.status), ("open_tickets", 409))
        self.assertIn("Wait until its open tickets settle", str(exc))
        self.assertEqual(len(user_store.lineage(hound["id"])), 1)

    def test_a_ticket_waiting_for_a_grade_blocks_it(self):
        hound = self.two_sport_dog()
        exc = refusal(self, self.train, hound, ticket(hound["id"], result=None, start_hours_ago=70, now=NOW))
        self.assertEqual(exc.code, "open_tickets")


class TheLimits(Train):
    def test_a_first_training_under_five_settled_bets_is_a_labelled_light_adjustment(self):
        hound = self.two_sport_dog()
        for settled in (1, 4):
            with self.subTest(settled=settled):
                dog = self.dog(f"Young Dog {settled}", sports=["MLB", "NFL"])
                out = self.train(dog, rows_for(dog["id"], [(settled, dict(result="LOSS"))]))
                self.assertEqual((out["mode"], out["light_adjustment"], out["label"]), ("light", True, "Light adjustment"))
                self.assertIn("light adjustment", out["light_note"])
                self.assertEqual(len(out["changes"]), 1)
                self.assertIsNone(out["changes"][0]["segment"])

    def test_a_hound_with_no_settled_bet_is_never_narrowed_it_is_offered_loosening(self):
        """Production 2026-10-22: a Gematria hound with 0 settled bets was sent to training and came back with 'Most bets a day
        3 -> 2'. It places nothing, so narrowing it was pointless. A hound that is not betting is offered ways to look at more."""
        dog = self.dog("Idle Dog", sports=["MLB", "NFL"], max_bets_per_day=3)
        out = self.train(dog, [])
        self.assertEqual((out["mode"], out["light_adjustment"], out["label"]), ("loosen", True, "Light adjustment"))
        self.assertTrue(out["changes"])
        self.assertTrue(all(c["direction"] == "loosen" for c in out["changes"]), out["changes"])
        self.assertNotIn("fewer_bets", {c["id"] for c in out["changes"]})
        self.assertNotIn("more_bets", {c["id"] for c in out["changes"]}, "a hound that places nothing is not held back by its daily limit")
        new = user_store.get_hound(out["new"]["id"])["spec"]
        self.assertEqual(new["max_bets_per_day"], 3)

    def test_a_hound_with_settled_bets_and_no_candidate_today_is_never_narrowed(self):
        """Owner report: a hound with 2 settled bets and nothing on today's board was offered "Most bets a day" cut. A rule that
        finds nothing today is not held back by its daily limit, so the proposal may only loosen (or say nothing sensible)."""
        dog = self.dog("Quiet Pup", sports=["MLB", "NFL"], max_bets_per_day=3)
        rows = rows_for(dog["id"], [(2, dict(result="LOSS"))])
        empty_board = lambda spec: {"games": 4, "candidates": 0, "with_candidate": 0, "failed": {}, "failed_total": 0}
        # Nothing loosening adds a game to an empty board, so the honest answer is "nothing sensible" (a refusal, nothing changes).
        err = refusal(self, self.train, dog, rows, board_fn=empty_board)
        self.assertEqual(err.code, "nothing_to_change")
        self.assertEqual(user_store.get_hound(dog["id"])["spec"]["max_bets_per_day"], 3)

    def test_five_settled_bets_is_enough_for_an_analysis(self):
        hound = self.two_sport_dog()
        out = self.train(hound, rows_for(hound["id"], [(5, dict(result="LOSS", side="away"))]))
        self.assertFalse(out["light_adjustment"] and out["analysis"]["settled"] >= 5 and out["mode"] == "analysed")
        self.assertEqual(out["analysis"]["settled"], 5)

    def test_once_per_version_it_needs_five_new_settled_bets_before_it_can_train_again(self):
        hound = self.two_sport_dog()
        first = self.train(hound, rows_for(hound["id"], MIXED))
        v2 = user_store.get_hound(first["new"]["id"])
        now = refusal(self, self.train, v2, [])
        self.assertEqual((now.code, now.status), ("training_too_soon", 409))
        self.assertIn("needs 5 new settled bets on version 2", str(now))
        self.assertEqual(now.extra["needs"], 5)
        # four new settled bets on version 2 are still not enough; the old version's bets never count for it
        rows = rows_for(hound["id"], MIXED) + rows_for(v2["id"], [(4, dict(result="LOSS"))])
        self.assertEqual(refusal(self, self.train, v2, rows).extra["needs"], 1)
        rows += rows_for(v2["id"], [(1, dict(result="LOSS", side="away"))])
        again = self.train(v2, rows)
        self.assertEqual(again["new"]["version_no"], 3)
        self.assertEqual(again["new"]["trained_times"], 2)

    def test_a_push_counts_as_settled_and_a_void_does_not(self):
        hound = self.two_sport_dog()
        first = self.train(hound, [])
        v2 = user_store.get_hound(first["new"]["id"])
        rows = rows_for(v2["id"], [(3, dict(result="LOSS")), (1, dict(result="PUSH")), (3, dict(result="VOID"))])
        self.assertEqual(refusal(self, self.train, v2, rows).extra["needs"], 1)

    def test_an_owners_edit_does_not_reset_the_wait_for_a_lineage_that_has_trained(self):
        hound = self.two_sport_dog()
        first = self.train(hound, [])
        v3 = user_store.create_version(first["new"]["id"], {**user_store.get_hound(first["new"]["id"])["spec"], "max_bets_per_day": 1},
                                       actor="owner", reason="edit")
        self.assertEqual(refusal(self, self.train, v3, []).code, "training_too_soon")

    def test_a_dog_with_nothing_left_to_tighten_is_told_so(self):
        hound = self.dog("Tight Dog", min_books=10, max_bets_per_day=1)
        exc = refusal(self, self.train, hound, rows_for(hound["id"], [(2, dict(result="LOSS"))]))
        self.assertEqual((exc.code, exc.status), ("nothing_to_change", 409))
        self.assertEqual(len(user_store.lineage(hound["id"])), 1)


class TheNewVersion(Train):
    def test_it_has_lineage_a_fresh_record_and_the_old_record_is_frozen(self):
        hound = self.two_sport_dog()
        rows = rows_for(hound["id"], MIXED)
        out = self.train(hound, rows)
        new = user_store.get_hound(out["new"]["id"])
        old = user_store.get_hound(hound["id"])
        self.assertEqual((new["version_no"], new["version_of"], new["coached_from"], new["root_id"]), (2, hound["id"], hound["id"], hound["root_id"]))
        self.assertEqual((new["status"], new["name"], new["tagline"], new["owner_user_id"]), ("running", old["name"], old["tagline"], self.owner.id))
        self.assertEqual(old["status"], "retired")
        self.assertTrue(old["retire_reason"].startswith("superseded by"))
        self.assertEqual(old["spec"], hound["spec"])                                   # the old rule is untouched
        # the new version starts with no ticket at all; the old one keeps all 18
        self.assertEqual(rites.forward_bets(new["id"], rows), [])
        self.assertEqual(len(rites.forward_bets(hound["id"], rows)), 18)
        self.assertEqual(out["old"]["record"]["wins"] + out["old"]["record"]["losses"], 18)
        self.assertEqual(out["new"]["record"], {"wins": 0, "losses": 0, "pushes": 0, "bets": 0})

    def test_the_badge_counts_trainings_and_the_kit_and_kennel_show_it(self):
        hound = self.two_sport_dog()
        self.assertEqual(user_store.trained_count(hound["root_id"]), 0)
        out = self.train(hound, rows_for(hound["id"], MIXED))
        self.assertEqual(out["new"]["trained_times"], 1)
        kit = camp.kit(self.resolve(out["new"]["id"]), self.owner.id)
        self.assertEqual((kit["trained_times"], kit["coached_from"]), (1, hound["id"]))
        from src.hounds import kennels
        dog = kennels.my_kennel(self.owner.id)["dogs"][0]
        self.assertEqual((dog["id"], dog["trained_times"], dog["version_no"]), (out["new"]["id"], 1, 2))

    def test_it_keeps_the_dogs_look_because_the_look_belongs_to_the_lineage(self):
        hound = self.two_sport_dog()
        out = self.train(hound, rows_for(hound["id"], MIXED))
        self.assertEqual(self.resolve(out["new"]["id"]).root_id, hound["root_id"])

    def test_the_training_is_one_event_row_written_with_the_version(self):
        hound = self.two_sport_dog()
        out = self.train(hound, rows_for(hound["id"], MIXED))
        events = user_store.list_events(user_store.EVENT_TRAINED)
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual((payload["from_hound_id"], payload["new_hound_id"], payload["to_version"]), (hound["id"], out["new"]["id"], 2))
        self.assertEqual(payload["record"], {"wins": 8, "losses": 10, "pushes": 0})
        self.assertEqual(payload["changes"][0]["id"], out["changes"][0]["id"])

    def test_a_failed_training_leaves_no_event_behind(self):
        hound = self.dog("Tight Dog", min_books=10, max_bets_per_day=1)
        refusal(self, self.train, hound, rows_for(hound["id"], [(2, dict(result="LOSS"))]))
        self.assertEqual(user_store.list_events(), [])

    def test_a_free_accounts_slot_count_does_not_move(self):
        hound = user_store.create_hound(self.owner.id, spec_dict(name="Only Dog", sports=["MLB", "NFL"]), free_tier=True)
        self.train(hound, [])
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_hound(self.owner.id, spec_dict(name="Second Dog"), free_tier=True)
        self.assertEqual(ctx.exception.code, "upgrade_required")


class TheAnalysis(unittest.TestCase):
    def analyse(self, spec_over=None, plan=MIXED):
        spec = user_spec.validate_spec(spec_dict(sports=["MLB", "NFL"], **(spec_over or {})))
        rows = rows_for("u-x", plan)
        return spec, training.analyse(rites.forward_bets("u-x", rows), spec)

    def test_the_bets_are_cut_every_way(self):
        _spec, a = self.analyse()
        self.assertEqual(a["overall"], {"n": 18, "wins": 8, "losses": 10, "pushes": 0, "units": a["overall"]["units"]})
        dims = a["segments"]
        self.assertEqual({s["key"]: (s["wins"], s["losses"]) for s in dims["sport"]}, {"MLB": (2, 7), "NFL": (6, 3)})
        self.assertEqual({s["key"]: (s["wins"], s["losses"]) for s in dims["venue"]}, {"away": (2, 7), "home": (6, 3)})
        self.assertEqual({s["key"] for s in dims["market"]}, {"moneyline"})
        self.assertEqual({s["key"] for s in dims["role"]}, {"underdog"})       # +180 and +110 are both underdog prices
        self.assertEqual({s["key"] for s in dims["band"]}, {"underdogs"})

    def test_the_worst_segments_come_first_and_a_one_value_dimension_is_never_weak(self):
        _spec, a = self.analyse()
        self.assertEqual([(s["dimension"], s["key"]) for s in a["weak"]], [("sport", "MLB"), ("venue", "away")])
        self.assertTrue(all(s["units"] < 0 and s["n"] >= training.MIN_SEGMENT_BETS for s in a["weak"]))
        self.assertNotIn("market", {s["dimension"] for s in a["weak"]})

    def test_a_segment_under_three_bets_is_noise_not_a_weak_spot(self):
        _spec, a = self.analyse(plan=[(2, dict(result="LOSS", sport="NFL")), (8, dict(result="WIN"))])
        self.assertEqual(a["weak"], [])

    def test_the_price_bands_cover_every_price_once(self):
        keys = {training.band_of(p): p for p in (-199, -151, -150, -111, -110, -101, 100, 109, 110, 199, 200, 1000)}
        self.assertEqual(list(keys), ["short_favourites", "favourites", "near_even", "underdogs", "long_shots"])
        self.assertEqual([training.band_of(p) for p in (-250, 5000)], ["short_favourites", "long_shots"])
        self.assertIsNone(training.band_of(None))

    def test_favourite_and_underdog_follow_the_price_or_the_spread_line(self):
        from src.hounds import ledgers
        def bet(**kw):
            rows = ticket("u-x", result="WIN", **kw)
            return ledgers.pack_rows(rows)[0][0]
        self.assertEqual(training.role_of(bet(price=-140)), "favourite")
        self.assertEqual(training.role_of(bet(price=130)), "underdog")
        self.assertEqual(training.role_of(bet(market="spread", line=-1.5, price=-110)), "favourite")
        self.assertEqual(training.role_of(bet(market="spread", line=1.5, price=-110)), "underdog")
        self.assertIsNone(training.role_of(bet(market="total", side="over", price=-110)))

    def test_a_custom_rules_dog_is_cut_by_the_rule_that_made_each_bet(self):
        spec = user_spec.validate_spec({"version": 2, "name": "Two Rules", "rules": [
            {"sports": ["MLB"], "markets": ["moneyline"], "side": "either"},
            {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 300}]})
        rows = (rows_for("u-x", [(5, dict(result="LOSS", rule_index=0))]) + rows_for("u-x", [(5, dict(result="WIN", rule_index=1))]))
        a = training.analyse(rites.forward_bets("u-x", rows), spec, training.rule_index_of(rows, "u-x"))
        self.assertEqual([(s["key"], s["wins"], s["losses"]) for s in a["segments"]["rule"]], [(0, 0, 5), (1, 5, 0)])
        self.assertEqual(a["weak"][0]["label"], "rule 1")


class TheChanges(unittest.TestCase):
    def propose(self, spec, plan, light=False):
        rows = rows_for("u-x", plan)
        analysis = training.analyse(rites.forward_bets("u-x", rows), spec, training.rule_index_of(rows, "u-x"))
        return training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=light), analysis

    def test_the_weakest_sport_is_dropped(self):
        spec = user_spec.validate_spec(spec_dict(sports=["MLB", "NFL"]))
        (new, changes, mode, _note), _a = self.propose(spec, MIXED)
        self.assertEqual((mode, new["sports"], [c["id"] for c in changes]), ("analysed", ["NFL"], ["drop_sport"]))
        self.assertEqual((changes[0]["old_text"], changes[0]["new_text"]), ("MLB and NFL", "NFL"))
        self.assertEqual(changes[0]["hindsight"], {"n": 9, "wins": 2, "losses": 7, "pushes": 0, "units": changes[0]["hindsight"]["units"]})
        self.assertIn("9 MLB bets went 2-7", changes[0]["why"])

    def test_the_worst_market_is_dropped(self):
        spec = user_spec.validate_spec(spec_dict(markets=["moneyline", "total"], side_rule="market_moved_toward"))
        plan = [(5, dict(result="LOSS", market="total", side="over", price=-105)), (6, dict(result="WIN", market="moneyline", price=130))]
        (new, changes, _mode, _n), _a = self.propose(spec, plan)
        self.assertEqual((new["markets"], changes[0]["id"]), (["moneyline"], "drop_market"))

    def test_a_price_band_on_the_edge_of_the_range_is_cut_off(self):
        spec = user_spec.validate_spec(spec_dict(price_min=100, price_max=400))
        plan = [(5, dict(result="LOSS", price=300)), (6, dict(result="WIN", price=130))]
        (new, changes, _mode, _n), _a = self.propose(spec, plan)
        self.assertEqual((new["price_min"], new["price_max"], changes[0]["id"]), (100, 199, "tighten_band"))
        self.assertEqual(changes[0]["new_text"], "+100 to +199")

    def test_a_band_in_the_middle_of_a_range_cannot_be_cut_out(self):
        spec = user_spec.validate_spec(spec_dict(price_min=100, price_max=400))
        plan = [(5, dict(result="LOSS", price=150)), (3, dict(result="WIN", price=300)), (3, dict(result="WIN", price=105))]
        (new, changes, mode, note), _a = self.propose(spec, plan)
        self.assertEqual(mode, "light")                      # nothing it could cut, so it fell back to a nudge
        self.assertEqual(note, "no_weak_spot")
        self.assertEqual(changes[0]["id"] in ("more_books", "fewer_bets"), True)

    def test_a_custom_rule_that_takes_either_side_learns_the_other_one(self):
        spec = user_spec.validate_spec({"version": 2, "name": "Either Dog", "rules": [{"sports": ["MLB"], "markets": ["moneyline"], "side": "either"}]})
        plan = [(6, dict(result="LOSS", side="away", price=-120, rule_index=0)), (6, dict(result="WIN", side="home", price=-120, rule_index=0))]
        (new, changes, _mode, _n), _a = self.propose(spec, plan)
        self.assertEqual((new["rules"][0]["side"], changes[0]["id"]), ("home", "drop_venue"))

    def test_a_classic_dog_never_has_its_side_rule_rewritten(self):
        spec = user_spec.validate_spec(spec_dict(side_rule="away"))
        plan = [(6, dict(result="LOSS", side="away", price=130)), (6, dict(result="WIN", side="home", price=130))]
        (new, changes, mode, _n), _a = self.propose(spec, plan)
        self.assertEqual(new["side_rule"], "away")
        self.assertEqual(mode, "light")

    def test_a_favourites_leak_adds_the_underdog_condition_to_a_custom_rule(self):
        spec = user_spec.validate_spec({"version": 2, "name": "Chalk Dog", "rules": [{"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": -190, "price_max": 150}]})
        plan = [(6, dict(result="LOSS", price=-140, rule_index=0)), (6, dict(result="WIN", price=130, rule_index=0))]
        (new, changes, _mode, _n), _a = self.propose(spec, plan)
        ids = [c["id"] for c in changes]
        self.assertIn("require_role", ids)
        self.assertEqual(new["rules"][0]["when"], {"op": "all", "items": [{"id": "role", "value": "underdog"}]})

    def test_at_most_three_changes_and_each_one_changes_the_spec(self):
        spec = user_spec.validate_spec({"version": 2, "name": "Big Dog", "rules": [
            {"sports": ["MLB", "NFL"], "markets": ["moneyline"], "side": "either", "price_min": -190, "price_max": 400},
            {"sports": ["MLB", "NFL"], "markets": ["total"], "side": "either", "price_min": -190, "price_max": 400}]})
        plan = ([(5, dict(result="LOSS", sport="MLB", side="away", price=300, market="moneyline", rule_index=0))]
                + [(5, dict(result="LOSS", sport="NFL", side="home", price=-150, market="moneyline", rule_index=0))]
                + [(5, dict(result="LOSS", sport="MLB", side="over", price=-105, market="total", rule_index=1))]
                + [(8, dict(result="WIN", sport="NFL", side="away", price=120, market="moneyline", rule_index=0))])
        (new, changes, _mode, _n), _a = self.propose(spec, plan)
        self.assertTrue(1 <= len(changes) <= training.MAX_CHANGES)
        self.assertNotEqual(user_spec.spec_hash(new), user_spec.spec_hash(spec))
        self.assertEqual(new, user_spec.validate_spec(new))

    def test_a_change_the_menu_refuses_is_dropped_not_repaired(self):
        spec = user_spec.validate_spec(spec_dict(sports=["MLB", "NFL"]))
        refused = {"n": 0}
        real = user_spec.validate_spec

        def picky(raw, **kw):
            if sorted(raw.get("sports") or []) == ["NFL"]:
                refused["n"] += 1
                raise user_spec.SpecError({"sports": "no"})
            return real(raw, **kw)
        original = training.user_spec.validate_spec
        training.user_spec.validate_spec = picky
        try:
            (new, changes, mode, _n), _a = self.propose(spec, MIXED)
        finally:
            training.user_spec.validate_spec = original
        self.assertGreaterEqual(refused["n"], 1)
        self.assertNotEqual(new["sports"], ["NFL"])                    # the refused change is not in the result
        self.assertEqual(mode, "light")

    def test_the_same_bets_and_rule_always_give_the_same_changes(self):
        spec = user_spec.validate_spec(spec_dict(sports=["MLB", "NFL"]))
        first, _ = self.propose(spec, MIXED)
        second, _ = self.propose(spec, MIXED)
        self.assertEqual(first, second)
        light_a, _ = self.propose(spec, [], light=True)
        light_b, _ = self.propose(spec, [], light=True)
        self.assertEqual(light_a, light_b)


class NeverClaimsItIsBetter(Train):
    BANNED = re.compile(r"\b(better|improve|improved|improves|fix|fixed|fixes|stronger|smarter|profit|profitable|edge|winning|will win|beat the)\b", re.I)

    def texts(self, out):
        yield out["headline"]
        yield out["guidance"]["text"]
        yield out["next_training"]
        yield out["change_sentence"]
        if out["light_note"]:
            yield out["light_note"]
        for c in out["changes"]:
            yield c["why"]
            yield c["label"]

    def test_no_sentence_says_the_new_version_is_better(self):
        for plan in (MIXED, []):
            hound = self.dog(f"Dog {len(plan)}", sports=["MLB", "NFL"])
            out = self.train(hound, rows_for(hound["id"], plan))
            for text in self.texts(out):
                self.assertIsNone(self.BANNED.search(text), text)
            self.assertIn("new record starts now", out["headline"].lower())
            self.assertIn("starts now", out["guidance"]["text"])

    def test_it_says_the_old_record_is_kept_and_the_new_one_starts_now(self):
        hound = self.two_sport_dog()
        out = self.train(hound, rows_for(hound["id"], MIXED))
        self.assertEqual(out["headline"], "Rusty Pup is back as version 2. Its new record starts now.")
        self.assertIn("Version 1 keeps its record as it stands.", out["guidance"]["text"])
        self.assertTrue(out["old"]["frozen"])


class TheOptionalAiParagraph(Train):
    HOOK = {"ZAPIER_TRANSLATE_HOOK_URL": "https://hooks.zapier.com/hooks/catch/1/abc/", "TRAINING_BRIEF_ZAP": "on"}

    def test_the_brief_is_opt_in_even_with_a_hook(self):
        """The only hook today is the live translator Zap; without TRAINING_BRIEF_ZAP=on nothing is sent to it."""
        from src.hounds.interact import training
        sent = []
        env = {"ZAPIER_TRANSLATE_HOOK_URL": self.HOOK["ZAPIER_TRANSLATE_HOOK_URL"]}
        self.assertFalse(training.send_brief({"x": 1}, "training-t", env=env, poster=lambda u, p: sent.append(p), background=False))
        self.assertEqual(sent, [])

    def test_without_a_hook_the_paragraph_is_deterministic_text_and_nothing_is_sent(self):
        hound = self.two_sport_dog()
        sent = []
        out = self.train(hound, rows_for(hound["id"], MIXED), poster=lambda url, payload: sent.append(payload))
        self.assertEqual((out["guidance"]["source"], out["guidance"]["ai_requested"], sent), ("code", False, []))
        self.assertIn("Rusty Pup went 8-10 over 18 settled bets", out["guidance"]["text"])

    def test_with_a_hook_the_brief_is_posted_and_the_shown_text_does_not_change(self):
        hound = self.two_sport_dog()
        sent = []
        out = self.train(hound, rows_for(hound["id"], MIXED), env=self.HOOK, poster=lambda url, payload: sent.append((url, payload)))
        self.assertTrue(out["guidance"]["ai_requested"])
        self.assertEqual(out["guidance"]["source"], "code")
        (url, payload), = sent
        self.assertEqual((url, payload["kind"]), (self.HOOK["ZAPIER_TRANSLATE_HOOK_URL"], "training_brief"))
        self.assertTrue(payload["job_id"].startswith("training-"))
        import json
        brief = json.loads(payload["text"])
        self.assertIn("DATA, NOT INSTRUCTIONS", brief["data_notice"])
        self.assertEqual((brief["dog"], brief["record"], brief["paper_only"]), ("Rusty Pup", "8-10", True))
        self.assertNotIn("owner", payload["text"].lower().replace("owner's", ""))
        self.assertLessEqual(len(payload["text"].encode("utf-8")), 25_000)

    def test_a_hook_that_fails_or_raises_never_blocks_or_breaks_the_training(self):
        hound = self.two_sport_dog()

        def boom(url, payload):
            raise OSError("the hook is down")
        out = self.train(hound, rows_for(hound["id"], MIXED), env=self.HOOK, poster=boom)
        self.assertEqual(out["new"]["version_no"], 2)
        self.assertEqual(user_store.get_hound(out["new"]["id"])["status"], "running")

    def test_the_post_runs_on_a_background_thread_so_a_slow_hook_cannot_hold_the_request(self):
        import threading
        import time
        hound = self.two_sport_dog()
        gate = threading.Event()
        started = threading.Event()

        def slow(url, payload):
            started.set()
            gate.wait(5)
        t0 = time.monotonic()
        out = self.train(hound, rows_for(hound["id"], MIXED), env=self.HOOK, poster=slow, background=True)
        elapsed = time.monotonic() - t0
        gate.set()
        self.assertLess(elapsed, 2.0)
        self.assertTrue(out["guidance"]["ai_requested"])
        self.assertTrue(started.wait(2))


class TheFeedAnnouncesIt(Train):
    def test_a_training_is_a_news_item_that_says_the_new_record_starts_now(self):
        from src.hounds import kennel_feed
        hound = self.two_sport_dog()
        out = self.train(hound, rows_for(hound["id"], MIXED))
        (item,) = kennel_feed.rite_events(user_store.list_events())
        self.assertEqual((item["kind"], item["guid"]), ("trained", f"kennel:trained:{out['new']['id']}"))
        self.assertIn("went to training and came back as version 2", item["title"])
        self.assertIn("Sports from MLB and NFL to NFL", item["why"])
        self.assertIn("the new version's record starts now", item["why"])
        self.assertEqual(item["hound_id"], out["new"]["id"])
        self.assertIsNone(re.search(r"better|improv", item["why"] + item["title"], re.I))

    def test_a_light_adjustment_says_so_in_the_title(self):
        from src.hounds import kennel_feed
        hound = self.two_sport_dog()
        self.train(hound, [])
        (item,) = kennel_feed.rite_events(user_store.list_events())
        self.assertIn("(a light adjustment)", item["title"])


# ---------------------------------------------------------------------------------------------------------------
# the sweep: every shape of dog, every sport
# ---------------------------------------------------------------------------------------------------------------

V1_SIDE_RULES = {"favourite": ["moneyline", "spread"], "underdog": ["moneyline", "spread"], "home": ["moneyline", "spread"],
                 "away": ["moneyline"], "over": ["total"], "under": ["total"], "market_moved_toward": ["moneyline", "spread", "total"],
                 "market_moved_away": ["moneyline", "spread", "total"]}


def v1_specs():
    for side, markets in V1_SIDE_RULES.items():
        for sports in (["MLB"], ["MLB", "NFL"], list(user_spec.SPORTS)):
            for band in ((100, 250), (-190, 150), (-150, -110)):
                if side in ("underdog",) and band[1] < 100:
                    continue
                yield user_spec.validate_spec(spec_dict(name=f"Sweep {side[:4]} {len(sports)} {abs(band[0])}", sports=sports, markets=markets,
                                                        side_rule=side, price_min=band[0], price_max=band[1], min_books=3, max_bets_per_day=3))


def v2_specs():
    one = {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": -190, "price_max": 400}
    yield user_spec.validate_spec({"version": 2, "name": "Sweep One Rule", "rules": [one]})
    yield user_spec.validate_spec({"version": 2, "name": "Sweep Any Sport", "rules": [{**one, "sports": list(user_spec.SPORTS), "markets": ["moneyline", "spread"]}]})
    yield user_spec.validate_spec({"version": 2, "name": "Sweep Two Rules", "rules": [one, {**one, "markets": ["total"], "side": "either", "price_min": -190, "price_max": 300}]})
    yield user_spec.validate_spec({"version": 2, "name": "Sweep When", "rules": [{**one, "when": {"op": "all", "items": [{"id": "steam", "direction": "toward"}]}}]})
    yield user_spec.validate_spec({"version": 2, "name": "Sweep Three Rules", "max_bets_per_day": 4, "stake_units": 2.0, "rules": [
        one, {**one, "sports": ["NFL"], "price_min": 100}, {**one, "markets": ["total"], "price_min": -140, "price_max": 200}]})


def synthetic_plan(spec, rng):
    """Bets across every sport, market, side and price the spec could make, with a random mix of results, so most
    dimensions have a weak spot somewhere."""
    sports = sorted({s for rl in (spec["rules"] if user_spec.is_v2(spec) else [spec]) for s in rl["sports"]})
    plan = []
    for i, sport in enumerate(sports):
        for market in ("moneyline", "spread", "total"):
            side = {"moneyline": rng.choice(["home", "away"]), "spread": rng.choice(["home", "away"]), "total": rng.choice(["over", "under"])}[market]
            for result in ("LOSS",) * 4 + ("WIN",) * 3:
                price = rng.choice([-190, -150, -120, -105, 105, 130, 180, 250, 320])
                if price < spec_pmin(spec):
                    price = spec_pmin(spec)
                plan.append((1, dict(result=result, sport=sport, market=market, side=side, price=price,
                                     line=(-1.5 if market == "spread" and price < 0 else 1.5 if market == "spread" else None),
                                     rule_index=0 if user_spec.is_v2(spec) else None)))
    rng.shuffle(plan)
    return plan


def spec_pmin(spec):
    rls = spec["rules"] if user_spec.is_v2(spec) else [spec]
    return min(rl["price_min"] for rl in rls)


def decimal(p):
    return user_spec.price_decimal(p)


def assert_narrower(test, old, new):
    """The invariants of a training: valid, same name, never wider, never past the -200 cap."""
    test.assertEqual(new, user_spec.validate_spec(new), "the trained spec is already normalised and valid")
    test.assertEqual((new["name"], new["tagline"], user_spec.is_v2(new)), (old["name"], old["tagline"], user_spec.is_v2(old)))
    test.assertLessEqual(set(new["sports"]), set(old["sports"]))
    test.assertLessEqual(set(new["markets"]), set(old["markets"]))
    test.assertLessEqual(new["max_bets_per_day"], old["max_bets_per_day"])
    olds, news = (old["rules"], new["rules"]) if user_spec.is_v2(old) else ([old], [new])
    test.assertLessEqual(len(news), len(olds))
    for rl in news:
        test.assertFalse(user_spec.beyond_cap(rl["price_min"]) or user_spec.beyond_cap(rl["price_max"]), "the -200 cap")
        test.assertGreaterEqual(rl["price_min"], -199)
    if len(news) == len(olds):
        for o, n in zip(olds, news):
            test.assertLessEqual(set(n["sports"]), set(o["sports"]))
            test.assertLessEqual(set(n["markets"]), set(o["markets"]))
            test.assertGreaterEqual(decimal(n["price_min"]), decimal(o["price_min"]) - 1e-9)
            test.assertLessEqual(decimal(n["price_max"]), decimal(o["price_max"]) + 1e-9)
            test.assertGreaterEqual(n["min_books"], o["min_books"])


class TheSweep(unittest.TestCase):
    def run_spec(self, spec, seed):
        rng = random.Random(seed)
        plan = synthetic_plan(spec, rng)
        rows = rows_for("u-x", plan)
        bets = rites.forward_bets("u-x", rows)
        analysis = training.analyse(bets, spec, training.rule_index_of(rows, "u-x"))
        for light in (False, True):
            new, changes, mode, _note = training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=light)
            if new is None:
                self.assertEqual((changes, mode), ([], "light"))
                continue
            self.assertTrue(1 <= len(changes) <= training.MAX_CHANGES)
            self.assertNotEqual(user_spec.spec_hash(new), user_spec.spec_hash(spec))
            assert_narrower(self, spec, new)
            again = training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=light)
            self.assertEqual((new, changes), (again[0], again[1]), "deterministic")

    def test_every_version_one_shape(self):
        count = 0
        for i, spec in enumerate(v1_specs()):
            with self.subTest(name=spec["name"]):
                self.run_spec(spec, i)
            count += 1
        self.assertGreater(count, 60)

    def test_every_version_two_shape(self):
        for i, spec in enumerate(v2_specs()):
            with self.subTest(name=spec["name"]):
                self.run_spec(spec, 100 + i)

    def test_every_sport_on_the_menu_can_be_the_one_that_is_dropped(self):
        """An any-sport dog that loses in ONE sport and wins in the rest drops exactly that sport, for each of them."""
        for sport in user_spec.SPORTS:
            with self.subTest(sport=sport):
                spec = user_spec.validate_spec(spec_dict(name="Any Sport Dog", sports=list(user_spec.SPORTS)))
                others = [s for s in user_spec.SPORTS if s != sport]
                plan = [(5, dict(result="LOSS", sport=sport, price=150))] + [(3, dict(result="WIN", sport=s, price=150)) for s in others]
                rows = rows_for("u-x", plan)
                analysis = training.analyse(rites.forward_bets("u-x", rows), spec)
                new, changes, mode, _n = training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=False)
                self.assertEqual((mode, changes[0]["id"], sport in new["sports"]), ("analysed", "drop_sport", False))
                self.assertEqual(set(new["sports"]), set(others))
                assert_narrower(self, spec, new)

    def test_the_light_adjustment_is_valid_for_every_shape_even_with_no_bets(self):
        for spec in list(v1_specs()) + list(v2_specs()):
            analysis = training.analyse([], spec)
            new, changes, mode, note = training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=True)
            with self.subTest(name=spec["name"]):
                if new is None:
                    self.assertEqual(note, "nothing_to_change")
                    continue
                self.assertEqual((mode, len(changes), note), ("light", 1, "not_enough_bets"))
                assert_narrower(self, spec, new)

    def test_a_dog_priced_at_the_edge_of_the_cap_stays_inside_it(self):
        spec = user_spec.validate_spec(spec_dict(side_rule="favourite", markets=["moneyline"], price_min=-199, price_max=-110))
        plan = [(5, dict(result="LOSS", price=-190)), (5, dict(result="WIN", price=-120))]
        rows = rows_for("u-x", plan)
        analysis = training.analyse(rites.forward_bets("u-x", rows), spec)
        new, _changes, _mode, _n = training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=False)
        self.assertGreaterEqual(new["price_min"], -199)
        self.assertEqual(new["price_min"], -150)                 # the short-favourite band (-199 to -151) is cut off the front
        assert_narrower(self, spec, new)


class TheTrainingRunsOnARealStore(Train):
    def test_the_trained_spec_is_what_create_version_stored_and_it_validates(self):
        hound = self.two_sport_dog()
        out = self.train(hound, rows_for(hound["id"], MIXED))
        stored = user_store.get_hound(out["new"]["id"])["spec"]
        self.assertEqual(stored, user_spec.validate_spec(stored))
        self.assertEqual(stored["sports"], ["NFL"])
        self.assertEqual(out["diff"][0]["what"], "Rule 1 changed")

    def test_the_sweep_through_the_real_store_for_a_dog_of_each_shape(self):
        shapes = [spec_dict(name="Shape A", sports=["MLB", "NFL"]),
                  {"version": 2, "name": "Shape B", "rules": [{"sports": ["MLB", "NFL"], "markets": ["moneyline"], "side": "either"}]}]
        for raw in shapes:
            with self.subTest(name=raw["name"]):
                hound = user_store.create_hound(self.owner.id, raw)
                plan = [(6, dict(result="LOSS", side="away", price=150, rule_index=0 if user_spec.is_v2(hound["spec"]) else None)),
                        (6, dict(result="WIN", side="home", price=150, sport="NFL", rule_index=0 if user_spec.is_v2(hound["spec"]) else None))]
                out = self.train(hound, rows_for(hound["id"], plan))
                assert_narrower(self, hound["spec"], user_store.get_hound(out["new"]["id"])["spec"])


if __name__ == "__main__":
    unittest.main()
