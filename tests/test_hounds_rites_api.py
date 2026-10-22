"""POST /hounds/{id}/out-back, POST /hounds/{id}/train, GET /hounds/{id}/headstone and the graveyard payload.

The routes in api/hounds_interact.py are thin wiring over src/hounds/interact/outback.py and training.py (tested without
FastAPI in test_hounds_outback.py and test_hounds_training.py); this file proves the wiring: who may call, which status
and code a refusal carries, that a stray POST without `confirm` changes nothing, and that the real mounted app serves them.
Skipped where FastAPI is not installed (Linux CI has none).
"""

from __future__ import annotations

import unittest

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import user_store
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for, ticket, write_ledger

MIXED = [(7, dict(result="LOSS", side="away", price=180)), (2, dict(result="WIN", side="away", price=180)),
         (6, dict(result="WIN", side="home", price=110, sport="NFL")), (3, dict(result="LOSS", side="home", price=110, sport="NFL"))]


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteCase(RitesCase):
    def setUp(self):
        super().setUp()
        from api import hounds_interact as api
        self.api = api
        self.token = users_store.issue_invite_token(self.owner.id, db=self.db)
        self.other_token = users_store.issue_invite_token(self.other.id, db=self.db)

    def err(self, fn, *a, **k):
        with self.assertRaises(HTTPException) as ctx:
            fn(*a, **k)
        return ctx.exception

    def code(self, exc):
        return exc.detail["error"] if isinstance(exc.detail, dict) else exc.detail

    def hound(self, name="Rusty Pup"):
        return self.dog(name, sports=["MLB", "NFL"])

    def out_back(self, hound_id, user, confirm=True):
        body = self.api.RiteRequest(confirm=confirm) if confirm is not None else None
        return self.api.take_out_back(hound_id, Response(), body=body, current_user=user, _rl=None)

    def train(self, hound_id, user, confirm=True):
        """Send to training as the page does it: the proposal card first, then Apply with the picks it offered. A proposal the
        route refuses (someone else's dog, an open ticket, too soon) leaves no picks, and the Apply then gets that same refusal."""
        picks = basis = None
        try:
            card = self.api.training_proposal(hound_id, Response(), body=None, current_user=user, _rl=None)
            picks, basis = card["picks"], card["basis"]
        except HTTPException:
            pass
        body = self.api.TrainRequest(confirm=confirm, picks=picks, basis=basis) if confirm is not None else None
        return self.api.send_to_training(hound_id, Response(), body=body, current_user=user, _rl=None)


class OutBackRoute(RouteCase):
    def test_the_owner_buries_a_dog_and_gets_its_headstone(self):
        hound = self.hound()
        write_ledger(self.ledger, rows_for(hound["id"], MIXED))
        out = self.out_back(hound["id"], self.owner)
        self.assertIs(out["paper_only"], True)
        self.assertEqual((out["headstone"]["name"], out["headstone"]["record"]["losses"], out["freed_slot"]), ("Rusty Pup", 10, True))
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "buried")

    def test_someone_elses_dog_is_a_404_and_a_house_dog_a_422(self):
        hound = self.hound()
        exc = self.err(self.out_back, hound["id"], self.other)
        self.assertEqual((exc.status_code, self.code(exc)), (404, "not_found"))
        exc = self.err(self.out_back, "chalk_chihuahua", self.owner)
        self.assertEqual((exc.status_code, self.code(exc)), (422, "not_a_member_dog"))
        exc = self.err(self.out_back, "no-such-dog", self.owner)
        self.assertEqual(exc.status_code, 404)
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")

    def test_an_open_ticket_is_a_409_that_says_to_wait(self):
        hound = self.hound()
        write_ledger(self.ledger, ticket(hound["id"], result=None, start_hours_ago=-3, now=NOW))
        exc = self.err(self.out_back, hound["id"], self.owner)
        self.assertEqual((exc.status_code, self.code(exc), exc.detail["open_tickets"]), (409, "open_tickets", 1))
        self.assertIn("Wait until its open tickets settle", exc.detail["message"])

    def test_a_dog_already_buried_is_a_409(self):
        hound = self.hound()
        self.out_back(hound["id"], self.owner)
        exc = self.err(self.out_back, hound["id"], self.owner)
        self.assertEqual((exc.status_code, self.code(exc)), (409, "already_buried"))

    def test_a_post_without_confirm_buries_nothing(self):
        hound = self.hound()
        for confirm in (False, None):
            exc = self.err(self.out_back, hound["id"], self.owner, confirm=confirm)
            self.assertEqual((exc.status_code, self.code(exc)), (400, "confirm_required"))
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")

    def test_the_headstone_route_is_public_and_only_for_the_buried(self):
        hound = self.hound()
        exc = self.err(self.api.headstone, hound["id"], Response(), _rl=None)
        self.assertEqual(exc.status_code, 404)
        self.out_back(hound["id"], self.owner)
        out = self.api.headstone(hound["id"], Response(), _rl=None)
        self.assertEqual(out["headstone"]["hound_id"], hound["id"])
        self.assertNotIn("owner_user_id", out["headstone"])
        self.assertEqual(self.err(self.api.headstone, "../etc", Response(), _rl=None).status_code, 404)

    def test_the_kit_reports_the_rites_to_the_owner_only(self):
        hound = self.hound()
        owner = self.api.kit(hound["id"], Response(), authorization=f"Bearer {self.token}", _rl=None)
        other = self.api.kit(hound["id"], Response(), authorization=f"Bearer {self.other_token}", _rl=None)
        anon = self.api.kit(hound["id"], Response(), authorization=None, _rl=None)
        self.assertEqual((owner["can_train"], owner["can_out_back"]), (True, True))
        self.assertEqual([(k["can_train"], k["can_out_back"]) for k in (other, anon)], [(False, False)] * 2)
        house = self.api.kit("chalk_chihuahua", Response(), authorization=f"Bearer {self.token}", _rl=None)
        self.assertEqual((house["can_train"], house["can_out_back"], house["trained_times"]), (False, False, 0))


class TrainRoute(RouteCase):
    def test_the_owner_trains_a_dog_and_gets_the_card(self):
        hound = self.hound()
        write_ledger(self.ledger, rows_for(hound["id"], MIXED))
        out = self.train(hound["id"], self.owner)
        self.assertEqual((out["new"]["version_no"], out["mode"], out["changes"][0]["id"]), (2, "analysed", "drop_sport"))
        self.assertIn("starts now", out["headline"])
        self.assertIs(out["paper_only"], True)

    def test_someone_elses_dog_a_house_dog_and_an_open_ticket_are_refused(self):
        hound = self.hound()
        self.assertEqual(self.err(self.train, hound["id"], self.other).status_code, 404)
        exc = self.err(self.train, "chalk_chihuahua", self.owner)
        self.assertEqual((exc.status_code, self.code(exc)), (422, "not_a_member_dog"))
        write_ledger(self.ledger, ticket(hound["id"], result=None, start_hours_ago=-3, now=NOW))
        exc = self.err(self.train, hound["id"], self.owner)
        self.assertEqual((exc.status_code, self.code(exc)), (409, "open_tickets"))
        self.assertEqual(len(user_store.lineage(hound["id"])), 1)

    def test_the_second_training_waits_for_five_new_settled_bets(self):
        hound = self.hound()
        first = self.train(hound["id"], self.owner)
        exc = self.err(self.train, first["new"]["id"], self.owner)
        self.assertEqual((exc.status_code, self.code(exc), exc.detail["needs"]), (409, "training_too_soon", 5))

    def test_a_post_without_confirm_trains_nothing(self):
        hound = self.hound()
        exc = self.err(self.train, hound["id"], self.owner, confirm=False)
        self.assertEqual((exc.status_code, self.code(exc)), (400, "confirm_required"))
        self.assertEqual(len(user_store.lineage(hound["id"])), 1)

    def test_a_buried_dog_cannot_be_trained(self):
        hound = self.hound()
        self.out_back(hound["id"], self.owner)
        self.assertEqual(self.code(self.err(self.train, hound["id"], self.owner)), "already_buried")


class TheGraveyardRoute(RouteCase):
    def test_the_payload_carries_the_headstones_newest_first_beside_the_old_retired_list(self):
        from api import hounds as hounds_api
        from src.hounds import stats
        a, b = self.hound("Dog A"), self.hound("Dog B")
        from datetime import timedelta
        from src.hounds.interact import outback
        outback.bury(self.resolve(a["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        outback.bury(self.resolve(b["id"]), self.owner.id, confirmed=True, now=NOW + timedelta(hours=1), rows=[])
        out = hounds_api.graveyard(Response())                      # the stats book is still warming: the headstones come from their own rows
        self.assertEqual([s["name"] for s in out["headstones"]], ["Dog B", "Dog A"])
        self.assertIn("hounds", out)
        self.assertEqual(stats.peek_book(), None)

    def test_an_empty_graveyard_is_an_empty_list_not_an_error(self):
        from api import hounds as hounds_api
        self.assertEqual(hounds_api.graveyard(Response())["headstones"], [])


class OnTheRealApp(RouteCase):
    """The mounted app, over HTTP: the token is required, the body is read, and a literal path never shadows a dog id."""

    def test_the_routes_need_a_signed_in_owner_and_work_end_to_end(self):
        from fastapi.testclient import TestClient
        from api.app import app
        hound = self.hound()
        client = TestClient(app)
        self.assertEqual(client.post(f"/hounds/{hound['id']}/out-back", json={"confirm": True}).status_code, 401)
        self.assertEqual(client.post(f"/hounds/{hound['id']}/train", json={"confirm": True}).status_code, 401)
        mine = {"Authorization": f"Bearer {self.token}"}
        stranger = {"Authorization": f"Bearer {self.other_token}"}
        self.assertEqual(client.post(f"/hounds/{hound['id']}/train", json={"confirm": True}, headers=stranger).status_code, 404)
        self.assertEqual(client.post(f"/hounds/{hound['id']}/out-back", json={}, headers=mine).status_code, 400)
        one_tap = client.post(f"/hounds/{hound['id']}/train", json={"confirm": True}, headers=mine)
        self.assertEqual((one_tap.status_code, one_tap.json()["detail"]["error"]), (409, "review_required"), one_tap.text)
        self.assertEqual(len(user_store.lineage(hound["id"])), 1)
        card = client.post(f"/hounds/{hound['id']}/train/propose", json={}, headers=mine)
        self.assertEqual(card.status_code, 200, card.text)
        trained = client.post(f"/hounds/{hound['id']}/train", json={"confirm": True, "picks": card.json()["picks"],
                                                                    "basis": card.json()["basis"]}, headers=mine)
        self.assertEqual(trained.status_code, 200, trained.text)
        v2 = trained.json()["new"]["id"]
        buried = client.post(f"/hounds/{v2}/out-back", json={"confirm": True}, headers=mine)
        self.assertEqual(buried.status_code, 200, buried.text)
        self.assertEqual(buried.json()["headstone"]["trained_times"], 1)
        stone = client.get(f"/hounds/{v2}/headstone")
        self.assertEqual(stone.status_code, 200)
        yard = client.get("/hounds/graveyard")
        self.assertEqual(yard.status_code, 200)
        self.assertEqual([s["hound_id"] for s in yard.json()["headstones"]], [v2])
        kennel = client.get(f"/hounds/kennels/mine", headers=mine).json()
        self.assertEqual((kennel["dogs"], [s["hound_id"] for s in kennel["graveyard"]]), ([], [v2]))


if __name__ == "__main__":
    unittest.main()
