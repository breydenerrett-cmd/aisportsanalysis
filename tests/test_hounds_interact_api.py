"""api/hounds_interact.py: the routes, called directly (this repo's api test style), and the seams that need no FastAPI.

Skipped where FastAPI is not installed (Linux CI has none): src/hounds/interact carries all of the logic and is
tested without it in the sibling modules, and the last class here proves it imports with FastAPI hidden.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import stats, user_engine, user_store, user_view
from src.hounds import user_engine_v2, user_spec
from src.hounds.interact import ask_eval, common, drill, fire, manual
from src.hounds.user_facts import FactBook
from tests._hounds_user_fixtures import DATE, EVENT, spec_dict, standard_rows, utc

REPO = Path(__file__).resolve().parent.parent
NOW = utc("2026-10-20T21:30:00Z")


def upcoming_games(*_a, **_k):
    return {eid: g for eid, g in user_engine.build_games(standard_rows(), near_date=DATE).items()
            if g.commence and g.commence > NOW}


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ApiCase(unittest.TestCase):
    def setUp(self):
        from api import hounds_interact as api
        self.api = api
        fire.clear_cache()
        drill.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                  mock.patch.object(stats, "peek_book", lambda: None),
                  mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming")),
                  mock.patch.object(common, "now_utc", lambda: NOW),
                  mock.patch.object(fire, "cached_games", upcoming_games)):
            p.start()
            self.addCleanup(p.stop)
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.owner_token = users_store.issue_invite_token(self.owner.id, db=self.db)
        self.other = users_store.create_user("other@example.com", status="active", db=self.db)
        self.other_token = users_store.issue_invite_token(self.other.id, db=self.db)
        self.dog = user_store.create_hound(self.owner.id, spec_dict(name="Dog Days"))
        self.id = self.dog["id"]

    def bearer(self, token):
        return f"Bearer {token}"

    def err(self, fn, *a, **k):
        with self.assertRaises(HTTPException) as ctx:
            fn(*a, **k)
        return ctx.exception

    def code(self, exc):
        return exc.detail["error"] if isinstance(exc.detail, dict) else exc.detail

    def put_ticket(self):
        """The rule ticket the live engine would write at the dog's lock, so the dog has one on its record."""
        user_engine.run(DATE, [self.dog], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))


class Kit(ApiCase):
    def test_what_each_visitor_can_do(self):
        anon = self.api.kit(self.id, Response(), authorization=None, _rl=None)
        self.assertFalse(anon["is_owner"])
        self.assertFalse(anon["can_record_manual"] or anon["can_customize"])
        self.assertTrue(anon["can_fire"])
        owner = self.api.kit(self.id, Response(), authorization=self.bearer(self.owner_token), _rl=None)
        self.assertTrue(owner["is_owner"] and owner["can_record_manual"] and owner["can_customize"])
        self.assertEqual(owner["manual"], {"limit_per_day": 5, "remaining_today": 5})
        self.assertEqual(owner["builder_href"], f"build-a-hound.html?from={self.id}")
        other = self.api.kit(self.id, Response(), authorization=self.bearer(self.other_token), _rl=None)
        self.assertFalse(other["is_owner"])
        self.assertTrue(other["can_suggest"])

    def test_a_house_dog_has_the_read_only_parts(self):
        out = self.api.kit("chalk_chihuahua", Response(), authorization=self.bearer(self.owner_token), _rl=None)
        self.assertTrue(out["can_fire"])
        self.assertFalse(out["can_record_manual"] or out["can_customize"] or out["can_suggest"])
        self.assertIsNone(out["builder_href"])

    def test_an_unknown_dog_is_a_404(self):
        self.assertEqual(self.err(self.api.kit, "no-such-dog", Response(), authorization=None, _rl=None).status_code, 404)

    def test_a_bad_token_is_just_anonymous_on_a_public_read(self):
        out = self.api.kit(self.id, Response(), authorization="Bearer nonsense", _rl=None)
        self.assertFalse(out["signed_in"])


class FireRoute(ApiCase):
    def test_anyone_can_fire_and_nothing_is_written(self):
        out = self.api.fire_now(self.id, Response(), authorization=None, _rl=None)
        self.assertEqual(out["picks"][0]["selection"], "Boston Red Sox to win")
        self.assertNotIn("row", out["picks"][0])                         # the internal ledger row is not leaked
        self.assertEqual(out["picks"][0]["manual"], {"can_record": False, "blocked": "only the owner can record a manual pick"})
        self.assertTrue(out["paper_only"])
        self.assertFalse(os.path.exists(self.ledger))
        self.assertFalse(os.path.exists(manual.ledger_path()))

    def test_the_owner_sees_the_record_button_unblocked(self):
        out = self.api.fire_now(self.id, Response(), authorization=self.bearer(self.owner_token), _rl=None)
        self.assertTrue(out["viewer_is_owner"])
        self.assertEqual(out["picks"][0]["manual"], {"can_record": True, "blocked": None})
        self.assertEqual(out["manual_remaining_today"], 5)

    def test_a_house_dog_fires_but_cannot_be_recorded_on(self):
        from src.hounds import pack_run
        from src.hounds.learning import champions
        from tests.test_house_pack_hounds import START, basic_stores
        stores = basic_stores()
        with mock.patch.object(fire, "default_stores", lambda now: stores), \
                mock.patch.object(common, "now_utc", lambda: START - __import__("datetime").timedelta(minutes=90)), \
                mock.patch.object(pack_run, "ledger_path", lambda p=None: p or os.path.join(self._tmp.name, "house.jsonl")), \
                mock.patch.object(champions, "champion_versions", lambda hs, path: tuple(hs)):
            out = self.api.fire_now("chalk_chihuahua", Response(), authorization=None, _rl=None)
        self.assertEqual(out["picks"][0]["selection"], "Boston Red Sox ML")
        self.assertEqual(out["picks"][0]["manual"]["blocked"], "house dogs are read only")

    def test_an_ai_desk_dog_cannot_be_fired(self):
        class Fake:
            pass
        with mock.patch.object(common, "resolve", lambda i: common.Dog(id=i, kind=common.KIND_OTHER, name="Desk")):
            self.assertEqual(self.code(self.err(self.api.fire_now, "desk-x", Response(), authorization=None, _rl=None)),
                             "not_firable")


class ManualRoutes(ApiCase):
    def record(self, **body):
        user = self.owner
        return self.api.record_manual(self.id, self.api.ManualRequest(event_id=body.get("event_id", EVENT),
                                                                      market=body.get("market", "moneyline")),
                                      Response(), current_user=user, _rl=None)

    def test_only_the_owner_and_the_rest_of_the_world_gets_a_404(self):
        exc = self.err(self.api.record_manual, self.id, self.api.ManualRequest(event_id=EVENT, market="moneyline"),
                       Response(), current_user=self.other, _rl=None)
        self.assertEqual(exc.status_code, 404)
        self.assertFalse(os.path.exists(manual.ledger_path()))

    def test_record_then_read_apart_from_the_rule_record(self):
        out = self.record()
        self.assertEqual(out["ticket"]["selection"], "Boston Red Sox to win")
        self.assertEqual(out["remaining_today"], 4)
        self.assertIn("never counted", out["note"])
        public = self.api.manual_tickets(self.id, Response(), _rl=None)
        self.assertEqual(len(public["tickets"]), 1)
        self.assertFalse(public["tickets"][0]["counted_in_record"])
        self.assertEqual(public["record"]["tickets"], 1)
        # the dog's own record has not moved
        data = user_view.hound_data(self.id, kick_build=False)
        self.assertEqual(data.summary.record.bets, 0)
        self.assertEqual(data.bets, [])

    def test_a_second_tap_is_a_409_with_a_code_the_page_can_read(self):
        self.record()
        exc = self.err(self.record)
        self.assertEqual((exc.status_code, self.code(exc)), (409, "already_on_record"))

    def test_a_pick_the_rule_would_not_make_is_a_422(self):
        exc = self.err(self.record, market="spread")                       # underdog away spread is -190: outside the band
        self.assertEqual((exc.status_code, self.code(exc)), (422, "not_a_pick"))

    def test_the_fire_button_then_shows_it_is_already_recorded(self):
        self.record()
        out = self.api.fire_now(self.id, Response(), authorization=self.bearer(self.owner_token), _rl=None)
        self.assertEqual(out["picks"][0]["manual"]["blocked"], "already recorded as a manual pick")

    def test_a_house_dog_has_no_manual_tickets(self):
        self.assertEqual(self.api.manual_tickets("chalk_chihuahua", Response(), _rl=None)["tickets"], [])


class Feedback(ApiCase):
    def vote(self, user=None, **body):
        body.setdefault("target_kind", "dog")
        body.setdefault("verdict", "good")
        return self.api.feedback_write(self.id, self.api.FeedbackRequest(**body), Response(),
                                       current_user=user or self.other, _rl=None)

    def test_it_needs_a_sign_in_on_every_write(self):
        deps = {(r.path, tuple(sorted(r.methods))): [(getattr(d, "call", None) or d.dependency).__name__
                                                      for d in r.dependant.dependencies]
                for r in self.api.router.routes if hasattr(r, "dependant")}
        for key in (("/hounds/{hound_id}/feedback", ("POST",)), ("/hounds/{hound_id}/suggest", ("POST",)),
                    ("/hounds/{hound_id}/look", ("PUT",)), ("/hounds/{hound_id}/manual", ("POST",)),
                    ("/hounds/drill", ("POST",)), ("/hounds/camp/mine", ("GET",))):
            self.assertIn("get_current_user", deps[key], key)
        for key in (("/hounds/{hound_id}/fire", ("POST",)), ("/hounds/{hound_id}/ask", ("POST",)),
                    ("/hounds/{hound_id}/feedback", ("GET",))):
            self.assertNotIn("get_current_user", deps[key], key)
        from api.auth import get_current_user
        self.assertEqual(self.err(get_current_user, authorization=None).status_code, 401)

    def test_a_dog_level_vote_and_the_public_counts(self):
        out = self.vote(verdict="bad", note="Too many unders")
        self.assertEqual(out["counts"]["bad"], 1)
        public = self.api.feedback_read(self.id, Response(), authorization=None, _rl=None)
        self.assertEqual((public["counts"]["good"], public["counts"]["bad"]), (0, 1))
        self.assertNotIn("notes", public)                                   # a stranger reads counts only
        self.assertNotIn("my_votes", public)

    def test_my_votes_come_back_only_to_me_and_the_owner_reads_the_notes(self):
        self.vote(verdict="good", note="Fair price")
        mine = self.api.feedback_read(self.id, Response(), authorization=self.bearer(self.other_token), _rl=None)
        self.assertEqual(mine["my_votes"], {"dog:": "good"})
        self.assertNotIn("notes", mine)
        owner = self.api.feedback_read(self.id, Response(), authorization=self.bearer(self.owner_token), _rl=None)
        self.assertEqual(owner["notes"][0]["note"], "Fair price")
        self.assertEqual(owner["suggestions"], [])
        self.assertNotIn("user_id", str(owner))

    def test_a_ticket_vote_lands_only_on_a_ticket_the_dog_really_has(self):
        exc = self.err(self.vote, target_kind="ticket", target_id="2026-10-20|Boston Red Sox to win")
        self.assertEqual((exc.status_code, self.code(exc)), (404, "target_not_found"))
        self.put_ticket()
        out = self.vote(target_kind="ticket", target_id="2026-10-20|Boston Red Sox to win", verdict="good")
        self.assertEqual(out["counts"]["by_target"]["ticket:2026-10-20|Boston Red Sox to win"], {"good": 1, "bad": 0})
        self.assertEqual(self.vote(target_kind="ticket", target_id="2026-10-20|Boston Red Sox to win", verdict="bad")
                         ["counts"]["by_target"]["ticket:2026-10-20|Boston Red Sox to win"], {"good": 0, "bad": 1})

    def test_an_answer_vote_names_a_real_kind_of_answer(self):
        self.assertEqual(self.vote(target_kind="answer", target_id="record")["counts"]["good"], 1)
        exc = self.err(self.vote, target_kind="answer", target_id="made-up")
        self.assertEqual(exc.status_code, 422)

    def test_a_bad_verdict_a_bad_kind_and_a_bad_note_are_422s(self):
        self.assertEqual(self.err(self.vote, verdict="great").status_code, 422)
        self.assertEqual(self.err(self.vote, target_kind="suggestion").status_code, 422)
        exc = self.err(self.vote, note="this dog is shit")
        self.assertEqual((exc.status_code, self.code(exc)), (422, "note_not_allowed"))

    def test_the_owner_can_rate_their_own_manual_ticket(self):
        ticket = manual.record(common.resolve(self.id), self.owner.id, EVENT, "moneyline", now=NOW,
                               games=upcoming_games(), rule_ledger=self.ledger)
        out = self.vote(user=self.owner, target_kind="manual", target_id=ticket["bet_id"])
        self.assertEqual(out["counts"]["by_kind"]["manual"]["good"], 1)
        self.assertEqual(self.err(self.vote, target_kind="manual", target_id="m-nope").status_code, 404)


class Suggestions(ApiCase):
    def suggest(self, user=None, **body):
        body.setdefault("change", {"price_max": 200})
        return self.api.suggest_change(self.id, self.api.SuggestRequest(**body), Response(),
                                       current_user=user or self.other, _rl=None)

    def test_a_stranger_suggests_and_the_owner_reads_it(self):
        out = self.suggest(note="a shorter band")
        self.assertIn("changes nothing", out["note"])
        owner = self.api.feedback_read(self.id, Response(), authorization=self.bearer(self.owner_token), _rl=None)
        self.assertEqual(owner["suggestions"][0]["change"], {"price_max": 200})
        self.assertEqual(owner["suggestions"][0]["note"], "a shorter band")
        # and it did not touch the dog
        self.assertEqual(user_store.get_hound(self.id)["spec"]["price_max"], 250)

    def test_the_owner_uses_the_builder_instead(self):
        self.assertEqual(self.code(self.err(self.suggest, user=self.owner)), "own_dog")

    def test_only_rule_fields_and_only_rules_the_menu_allows(self):
        for change in ({}, {"name": "Renamed"}, {"price_min": 1, "price_max": 2, "min_books": 3},
                       {"price_min": -250}, {"side_rule": "teleport"}):
            exc = self.err(self.suggest, change=change)
            self.assertEqual(exc.status_code, 422, change)
        self.assertEqual(self.code(self.err(self.suggest, change={"price_min": -250})), "change_invalid")

    def test_not_for_a_house_dog(self):
        exc = self.err(self.api.suggest_change, "chalk_chihuahua", self.api.SuggestRequest(change={"price_max": 200}),
                       Response(), current_user=self.other, _rl=None)
        self.assertEqual(self.code(exc), "not_a_builder_dog")


class Locker(ApiCase):
    def put(self, user=None, **look):
        return self.api.look_write(self.id, self.api.LookRequest(look=look), Response(),
                                   current_user=user or self.owner, _rl=None)

    def test_the_owner_dresses_the_dog_and_everyone_sees_it(self):
        out = self.put(coat="golden", head="cap", body="jersey", number=7)
        self.assertEqual(out["look"]["number"], 7)
        shown = self.api.look_read(self.id, Response(), _rl=None)
        self.assertEqual(shown["look"], out["look"])
        self.assertIn("coat", shown["menu"])
        batch = self.api.looks(Response(), ids=f"{self.id},chalk_chihuahua,nope", _rl=None)
        self.assertEqual(list(batch["looks"]), [self.id])

    def test_nobody_else_can_and_junk_is_a_422_with_the_fields(self):
        self.assertEqual(self.err(self.put, user=self.other, coat="red").status_code, 404)
        exc = self.err(self.put, coat="#ff0000", head="crown")
        self.assertEqual((exc.status_code, self.code(exc)), (422, "look_invalid"))
        self.assertEqual(set(exc.detail["fields"]), {"coat", "head"})
        self.assertIsNone(self.api.look_read(self.id, Response(), _rl=None)["look"])      # nothing was saved

    def test_a_new_version_keeps_the_look(self):
        self.put(coat="red")
        newer = user_store.create_version(self.id, dict(spec_dict(name="Dog Days"), price_max=200), actor="owner",
                                          reason="tweak")
        new_id = newer["id"] if "id" in newer else newer["new"]["id"]
        self.assertEqual(self.api.look_read(new_id, Response(), _rl=None)["look"]["coat"], "red")

    def test_a_house_dog_has_no_look_to_edit(self):
        self.assertIsNone(self.api.look_read("chalk_chihuahua", Response(), _rl=None)["look"])
        exc = self.err(self.api.look_write, "chalk_chihuahua", self.api.LookRequest(look={"coat": "red"}), Response(),
                       current_user=self.owner, _rl=None)
        self.assertEqual(exc.status_code, 404)


class Ask(ApiCase):
    def say(self, text, token=None):
        return self.api.ask_dog(self.id, self.api.AskRequest(question=text), Response(),
                                authorization=self.bearer(token or self.owner_token), _rl=None)

    def test_a_question_gets_an_answer_built_from_the_dog(self):
        self.put_ticket()
        out = self.say("What did you bet today?")
        self.assertEqual(out["intent"], "today")
        self.assertIn("Boston Red Sox to win", out["answer"])
        self.assertIn("+120", out["answer"])
        self.assertEqual(out["dog_name"], "Dog Days")
        why = self.say("why did you bet Boston")
        self.assertIn("5 books were quoting it", why["answer"])

    def test_right_now_reads_the_same_preview_as_the_button(self):
        out = self.say("what would you bet right now?")
        self.assertIn("Boston Red Sox to win", out["answer"])


    def fixture_slate(self):
        return lambda date, with_props: user_engine_v2.build_slate(
            date, ["MLB", "NFL"], with_props=with_props, rows=standard_rows(), prop_rows=[], facts=FactBook(),
            game_pk_index={})

    def test_the_owners_question_with_no_tickets_runs_the_rules_over_todays_boards(self):
        """2026-10-19: this exact question got 'I have not recorded a ticket yet' from a dog with a rule."""
        ask_eval.clear_cache()
        with mock.patch.object(ask_eval, "default_slate", self.fixture_slate()):
            out = self.say("What bets would yopu have taken today pre market")
        self.assertEqual(out["intent"], "picks_earlier_today")
        self.assertNotIn("I have not recorded a ticket yet, so there is nothing to say about my bets", out["answer"])
        self.assertIn("Boston Red Sox to win at +120", out["answer"])
        self.assertIn("Hindsight", out["answer"])
        self.assertEqual(out["cards"][0]["game"], "Boston Red Sox @ Seattle Mariners")

    def test_a_dog_built_from_english_rules_can_be_fired_by_the_button_and_asked(self):
        spec = user_spec.validate_spec({**user_spec.upgrade_v1(spec_dict(name="Rule Dog")), "name": "Rule Dog"})
        made = user_store.create_hound(self.owner.id, spec)
        ask_eval.clear_cache()
        with mock.patch.object(ask_eval, "default_slate", self.fixture_slate()):
            fired = self.api.fire_now(made["id"], Response(), authorization=None, _rl=None)
            asked = self.api.ask_dog(made["id"], self.api.AskRequest(question="any plays rn"), Response(),
                                     authorization=self.bearer(self.owner_token), _rl=None)
        self.assertEqual([p["selection"] for p in fired["picks"]], ["Boston Red Sox to win"])
        self.assertIn("slate", fired)
        self.assertEqual(asked["intent"], "picks_now")
        self.assertIn("Boston Red Sox to win at +120", asked["answer"])

    def test_asking_in_chat_is_not_a_way_around_the_fire_allowance(self):
        from fastapi import HTTPException as Http
        refuse = Http(status_code=429, detail={"error": "rate_limited", "retry_after": 7})
        with mock.patch.object(self.api, "_rl_fire_route", side_effect=refuse):
            out = self.api.ask_dog(self.id, self.api.AskRequest(question="what would you bet right now"), Response(),
                                   authorization=self.bearer(self.owner_token), _rl=None, request=object())
        self.assertIn("Try me again in 7 seconds.", out["answer"])
        self.assertEqual(out["busy"], {"kind": "rate", "retry_after": 7})

    def test_a_replay_in_chat_spends_the_drill_allowance_and_a_signed_out_visitor_is_asked_to_sign_in(self):
        from fastapi import HTTPException as Http
        # a house dog's Ask stays open to a signed-out visitor; a member dog's Ask is a paid tool (api/entitlements.py)
        out = self.api.ask_dog("chalk_chihuahua", self.api.AskRequest(question="what would you have done this week"),
                               Response(), authorization=None, _rl=None, request=object())
        self.assertIn("for signed-in visitors", out["answer"])
        refuse = Http(status_code=429, detail={"error": "rate_limited", "retry_after": 41})
        with mock.patch.object(self.api, "_rl_drill", side_effect=refuse):
            out = self.api.ask_dog(self.id, self.api.AskRequest(question="what would you have done this week"),
                                   Response(), authorization=self.bearer(self.owner_token), _rl=None, request=object())
        self.assertIn("Try me again in 41 seconds.", out["answer"])

    def test_the_greeting_has_the_dogs_name_and_questions_to_try(self):
        out = self.api.ask_open(self.id, Response(), authorization=None, _rl=None)
        self.assertIn("I am Dog Days.", out["greeting"][0])
        self.assertGreaterEqual(len(out["suggestions"]), 5)

    def test_empty_and_overlong_questions_are_refused(self):
        self.assertEqual(self.err(self.say, "   ").status_code, 422)
        self.assertEqual(self.err(self.say, "x" * 301).status_code, 422)

    def test_a_house_dog_can_be_asked(self):
        out = self.api.ask_dog("chalk_chihuahua", self.api.AskRequest(question="what are your rules"), Response(),
                               authorization=None, _rl=None)
        self.assertIn("My rule:", out["answer"])


class DrillRoute(ApiCase):
    def test_a_drill_wraps_the_result_and_maps_its_refusals(self):
        canned = {"label": "Backtest (hindsight, not counted in the record)", "counted": False}
        with mock.patch.object(drill, "drill", lambda **kw: dict(canned, kw=sorted(kw))):
            out = self.api.run_drill(self.api.DrillRequest(dog_id=self.id, days=14), Response(),
                                     current_user=self.other, _rl=None)
        self.assertEqual(out["label"], "Backtest (hindsight, not counted in the record)")
        self.assertTrue(out["paper_only"])
        with mock.patch.object(drill, "drill", side_effect=drill.DrillError("days_invalid", "choose 7", 422)):
            exc = self.err(self.api.run_drill, self.api.DrillRequest(dog_id=self.id, days=3), Response(),
                           current_user=self.other, _rl=None)
        self.assertEqual((exc.status_code, self.code(exc)), (422, "days_invalid"))
        self.assertEqual(self.err(self.api.run_drill, self.api.DrillRequest(dog_id="nope", days=7), Response(),
                                  current_user=self.other, _rl=None).status_code, 404)


    def test_the_backtest_tab_sends_a_season_and_it_reaches_the_drill(self):
        seen = {}
        with mock.patch.object(drill, "drill", lambda **kw: seen.update(kw) or {"label": "x"}):
            self.api.run_drill(self.api.DrillRequest(dog_id=self.id, season="s2"), Response(),
                               current_user=self.other, _rl=None)
        self.assertEqual((seen["season"], seen["dog"].id), ("s2", self.id))
        with mock.patch.object(drill, "drill", lambda **kw: seen.update(kw) or {"label": "x"}):
            self.api.run_drill(self.api.DrillRequest(dog_id=self.id, days=30), Response(), current_user=self.other, _rl=None)
        self.assertIsNone(seen["season"])

    def test_any_signed_in_member_may_backtest_any_dog_house_or_member(self):
        for dog_id in (self.id, "chalk_chihuahua"):
            with mock.patch.object(drill, "drill", lambda **kw: {"label": "x"}):
                out = self.api.run_drill(self.api.DrillRequest(dog_id=dog_id, days=7), Response(),
                                         current_user=self.other, _rl=None)
            self.assertEqual(out["label"], "x")

    def test_the_route_needs_a_sign_in_and_is_rate_limited_to_five_an_hour(self):
        names = [(getattr(d, "call", None) or d.dependency).__name__
                 for r in self.api.router.routes if getattr(r, "path", "") == "/hounds/drill"
                 for d in r.dependant.dependencies]
        self.assertIn("get_current_user", names)
        self.assertEqual(self.api.DRILL_PER_USER_PER_HOUR, 5)

    def test_a_busy_replay_is_a_429_with_the_seconds_to_wait_in_the_body_and_header(self):
        busy = drill.DrillError("drill_busy", "another drill is running", 429, retry_after=30)
        with mock.patch.object(drill, "drill", side_effect=busy):
            exc = self.err(self.api.run_drill, self.api.DrillRequest(dog_id=self.id, days=7), Response(),
                           current_user=self.other, _rl=None)
        self.assertEqual((exc.status_code, exc.detail["error"], exc.detail["retry_after"]), (429, "drill_busy", 30))
        self.assertEqual(exc.headers["Retry-After"], "30")


class Camp(ApiCase):
    def test_a_signed_in_owner_sees_their_dogs_with_record_feedback_and_suggestions(self):
        self.put_ticket()
        self.api.feedback_write(self.id, self.api.FeedbackRequest(target_kind="dog", verdict="good"), Response(),
                                current_user=self.other, _rl=None)
        self.api.suggest_change(self.id, self.api.SuggestRequest(change={"min_books": 4}, note="more books"),
                                Response(), current_user=self.other, _rl=None)
        self.api.look_write(self.id, self.api.LookRequest(look={"coat": "red"}), Response(), current_user=self.owner, _rl=None)
        out = self.api.camp_mine(Response(), current_user=self.owner, _rl=None)
        self.assertEqual(out["count"], 1)
        d = out["dogs"][0]
        self.assertEqual((d["id"], d["name"], d["status"]), (self.id, "Dog Days", "running"))
        self.assertEqual(d["look"]["coat"], "red")
        self.assertEqual(d["feedback"]["good"], 1)
        self.assertEqual(d["feedback"]["suggestions"], 1)
        self.assertEqual(d["suggestions"][0]["change"], {"min_books": 4})
        self.assertEqual(d["last_tickets"][0]["selection"], "Boston Red Sox to win")
        self.assertEqual(d["manual"]["remaining_today"], 5)
        self.assertEqual(d["builder_href"], f"build-a-hound.html?from={self.id}")
        self.assertEqual(self.api.camp_mine(Response(), current_user=self.other, _rl=None)["count"], 0)


class TheSeams(unittest.TestCase):
    def test_the_router_is_mounted_before_the_race_and_after_the_tip_box(self):
        src = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        tips = src.index("app.include_router(hounds_tips_router)")
        mine = src.index("app.include_router(hounds_interact_router)")
        race = src.index("app.include_router(hounds_router)")
        self.assertLess(tips, mine)
        self.assertLess(mine, race)

    def test_the_whole_package_imports_with_fastapi_hidden(self):
        code = ("import sys\n"
                "for n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
                "import src.hounds.interact.common, src.hounds.interact.store, src.hounds.interact.look\n"
                "import src.hounds.interact.fire, src.hounds.interact.manual, src.hounds.interact.ask\n"
                "import src.hounds.interact.drill, src.hounds.interact.camp\n"
                "import src.hounds.interact.ask_eval, src.hounds.interact.ask_intents\n"
                "print('ok')\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "ok", done.stderr)

    def test_no_interact_file_imports_fastapi_or_api(self):
        for path in (REPO / "src" / "hounds" / "interact").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in ("import fastapi", "from fastapi", "from api", "import api"):
                self.assertNotIn(banned, text, path.name)


if __name__ == "__main__":
    unittest.main()
