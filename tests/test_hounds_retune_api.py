"""The retune and review routes (api/hounds_interact.py): POST /hounds/{id}/train/propose, /train/veto and /train with the picks.

The routes are thin wiring over src/hounds/interact/training.py and retune.py (tested without FastAPI in test_hounds_retune.py);
this file proves the wiring: only the owner may propose, veto or apply; a propose and a veto write nothing; Apply needs the confirm
and refuses a pick that is not on the menu with a 422; Ask hands the Retune facts to the OWNER of a member hound and to nobody else.
Skipped where FastAPI is not installed (Linux CI has none).
"""

from __future__ import annotations

import unittest
from unittest import mock

try:
    from fastapi import Response
except ImportError:  # pragma: no cover
    Response = None

from src.hounds import user_store
from src.hounds.interact import ask, retune
from tests._hounds_rites_fixtures import NOW, ticket, write_ledger
from tests.test_hounds_rites_api import RouteCase
from tests.test_hounds_retune import OWNER_LINE, board


class Routes(RouteCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(retune, "board_counts", lambda dog, spec, **kw: board(spec))
        patch.start()
        self.addCleanup(patch.stop)
        self.hound_row = self.dog("Idle Pup", price_min=100, price_max=110)

    def propose(self, user=None, **body):
        return self.api.training_proposal(self.hound_row["id"], Response(), body=self.api.ProposeRequest(**body),
                                          current_user=user or self.owner, _rl=None)

    def apply(self, user=None, confirm=True, **body):
        return self.api.send_to_training(self.hound_row["id"], Response(), body=self.api.TrainRequest(confirm=confirm, **body),
                                         current_user=user or self.owner, _rl=None)

    def untouched(self):
        self.assertEqual(len(user_store.lineage(self.hound_row["id"])), 1)
        self.assertEqual(user_store.list_events(root_id=self.hound_row["root_id"]), [])


class ProposeAndVeto(Routes):
    def test_the_owner_gets_the_proposal_card_and_nothing_is_written(self):
        out = self.propose()
        self.assertEqual((out["mode"], out["paper_only"], out["nothing"]), ("loosen", True, False))
        self.assertTrue(all(c["direction"] == "loosen" for c in out["changes"]))
        self.assertIn("makes no promise about results", out["honesty"])
        self.untouched()

    def test_a_retune_proposal_from_the_chat_cites_the_owners_line(self):
        with mock.patch.object(retune, "_router_for", lambda router, env: None):
            out = self.propose(origin="chat", chat=[OWNER_LINE])
        self.assertEqual(out["origin"], "owner_retune_chat")
        self.assertTrue(out["changes"])
        self.assertTrue(all(c["cite"]["text"] == OWNER_LINE for c in out["changes"]))
        self.untouched()

    def test_somebody_elses_hound_is_a_404_for_propose_veto_and_apply(self):
        for call in (lambda: self.propose(user=self.other), lambda: self.apply(user=self.other, picks=["lower_books"]),
                     lambda: self.api.training_veto(self.hound_row["id"], Response(), current_user=self.other, _rl=None)):
            exc = self.err(call)
            self.assertEqual((exc.status_code, self.code(exc)), (404, "not_found"))
        self.untouched()

    def test_a_house_hound_is_a_422(self):
        exc = self.err(self.api.training_proposal, "chalk_chihuahua", Response(), body=None, current_user=self.owner, _rl=None)
        self.assertEqual((exc.status_code, self.code(exc)), (422, "not_a_member_dog"))

    def test_too_many_chat_lines_is_a_422_and_a_fourth_tweak_a_409(self):
        exc = self.err(self.propose, origin="chat", chat=["x"] * 21)
        self.assertEqual((exc.status_code, self.code(exc)), (422, "too_many_lines"))
        with mock.patch.object(retune, "_router_for", lambda router, env: None):
            for _ in range(3):
                self.propose(tweak="look at more sports")
            exc = self.err(self.propose, tweak="and more")
        self.assertEqual((exc.status_code, self.code(exc)), (409, "tweak_limit"))

    def test_a_veto_changes_nothing_and_says_so(self):
        out = self.api.training_veto(self.hound_row["id"], Response(), current_user=self.owner, _rl=None)
        self.assertEqual((out["vetoed"], out["changed"], out["counts_toward_limit"]), (True, False, False))
        self.untouched()


class Apply(Routes):
    def test_apply_with_the_ticked_picks_makes_the_version(self):
        out = self.apply(picks=["lower_books"])
        self.assertEqual([c["cid"] for c in out["changes"]], ["lower_books"])
        self.assertEqual(out["new"]["version_no"], 2)

    def test_a_retune_apply_carries_the_lineage_marker(self):
        out = self.apply(picks=["widen_band:up"], origin="chat")
        self.assertEqual((out["mode"], out["lineage"]), ("retune", "owner retune (from chat)"))
        self.assertEqual(user_store.get_hound(out["new"]["id"])["origin"], "owner_retune_chat")

    def test_without_the_confirm_nothing_changes_and_an_off_menu_pick_is_a_422(self):
        exc = self.err(self.apply, confirm=False, picks=["lower_books"])
        self.assertEqual((exc.status_code, self.code(exc)), (400, "confirm_required"))
        exc = self.err(self.apply, picks=["price_max:900"])
        self.assertEqual((exc.status_code, self.code(exc)), (422, "unknown_change"))
        exc = self.err(self.apply, picks=[])
        self.assertEqual((exc.status_code, self.code(exc)), (400, "no_changes_selected"))
        self.untouched()

    def test_the_old_one_shot_post_is_refused_and_writes_nothing(self):
        # a page cached from before the review (or any stray POST) sends only {"confirm": true}: never applied unseen
        for body in (self.api.RiteRequest(confirm=True), self.api.TrainRequest(confirm=True), self.api.TrainRequest(confirm=True, origin="chat")):
            exc = self.err(self.api.send_to_training, self.hound_row["id"], Response(), body=body, current_user=self.owner, _rl=None)
            self.assertEqual((exc.status_code, self.code(exc)), (409, "review_required"))
            self.assertIn("Nothing was changed", exc.detail["message"])
        self.untouched()
        card = self.propose()
        out = self.apply(picks=card["picks"], basis=card["basis"])
        self.assertEqual(out["new"]["version_no"], 2)
        self.assertEqual(out["mode"], "loosen", "a hound with no settled bet is widened, never narrowed")

    def test_too_soon_after_a_training_is_a_409_for_a_retune_too(self):
        self.apply(picks=["lower_books"], origin="chat")
        newest = user_store.lineage(self.hound_row["id"])[-1]
        exc = self.err(self.api.send_to_training, newest["id"], Response(), body=self.api.TrainRequest(confirm=True, picks=["widen_band:up"], origin="chat"),
                       current_user=self.owner, _rl=None)
        self.assertEqual((exc.status_code, self.code(exc)), (409, "training_too_soon"))


class Hardening(Routes):
    def test_a_stale_card_is_a_409_that_says_so(self):
        card = self.propose()
        self.apply(picks=card["picks"][:1], basis=card["basis"])
        exc = self.err(self.apply, picks=card["picks"][:1], basis=card["basis"])
        self.assertEqual((exc.status_code, self.code(exc)), (409, "proposal_stale"))
        self.assertIn("out of date", exc.detail["message"])
        self.assertEqual(len(user_store.lineage(self.hound_row["id"])), 2)

    def test_a_pasted_megabyte_is_refused_before_it_is_read(self):
        big = "x" * (self.api.TEXT_MAX + 1)
        for body in ({"tweak": big}, {"origin": "chat", "chat": [big]}):
            exc = self.err(self.propose, **body)
            self.assertEqual((exc.status_code, self.code(exc)), (422, "text_too_long"))
        exc = self.err(self.propose, origin="chat", chat=["a"] * 21)
        self.assertEqual(self.code(exc), "too_many_lines")
        self.untouched()

    def test_a_flood_of_picks_or_a_giant_id_is_refused_before_the_menu_is_built(self):
        for body in ({"picks": ["lower_books"] * 11}, {"picks": ["x" * 500]}, {"picks": ["lower_books"], "basis": "b" * 500}):
            exc = self.err(self.apply, **body)
            self.assertEqual((exc.status_code, self.code(exc)), (422, "too_many_changes"), body)
        self.untouched()


class OnlyTheOwnerIsOfferedRetune(Routes):
    def ask_as(self, user_id):
        dog = self.api._dog(self.hound_row["id"])
        ctx = self.api._context(dog, user_id)
        return ctx, ask.answer(OWNER_LINE, ctx)

    def test_the_owner_of_a_member_hound_is_given_the_button(self):
        ctx, out = self.ask_as(self.owner.id)
        self.assertIsNotNone(ctx.retune_fn)
        self.assertEqual(out["intent"], "retune")
        self.assertTrue(out["retune"]["offer"] and out["retune"]["enabled"])
        self.assertIn("Today I checked 60 games", out["answer"])

    def test_another_signed_in_account_and_a_signed_out_visitor_are_not(self):
        for viewer in (self.other.id, None):
            ctx, out = self.ask_as(viewer)
            self.assertIsNone(ctx.retune_fn)
            self.assertIsNone(out["retune"])
            self.assertEqual(out["intent"], "retune")
            self.assertIn("Only my owner can change my rules", out["answer"])

    def test_a_hound_that_cannot_train_now_has_the_button_off_and_says_why(self):
        write_ledger(self.ledger, ticket(self.hound_row["id"], result=None, start_hours_ago=-3, now=NOW))
        _ctx, out = self.ask_as(self.owner.id)
        self.assertFalse(out["retune"]["enabled"])
        self.assertIn("open ticket", out["retune"]["note"])


if __name__ == "__main__":
    unittest.main()
