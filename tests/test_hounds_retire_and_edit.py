"""Removing a dog from the kennel, and opening an old (classic) dog for editing.

THE REPORT (a real member, 2026-10-19, on a phone): "I can't delete my two dawgs and/or edit the old strategies."
There was a retire route and a versioning route and no button for either, and an old dog's edit path had never
been walked from a classic spec to a saved new version. These tests walk it:

  * "Remove from my kennel" is a RETIREMENT. The owner can do it with no words; a stranger cannot; the dog
    stops betting, leaves the kennel (every earlier version of it too) and frees its running slot, while its
    ledger rows, its record and its address are exactly as they were, and its page says it was retired by its owner;
  * a classic (version 1) dog opens as the equivalent rule set and saves as version 2 with the old row and every
    bet on it untouched;
  * one dog whose numbers cannot be built never takes the owner's whole list (and its Edit and Remove buttons) down.

The logic needs no FastAPI (Linux CI has none); the route tests are skipped without it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import kennels, stats, user_defs, user_engine, user_rules, user_spec, user_store
from src.hounds.english import render
from tests._hounds_user_fixtures import spec_dict
from tests.test_hounds_user_coach import ledger_rows


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(user_engine, "LEDGER", self.ledger),
                  mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                  mock.patch.object(stats, "peek_book", lambda: None),
                  mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming"))):
            p.start()
            self.addCleanup(p.stop)
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.other = users_store.create_user("other@example.com", status="active", db=self.db)

    def hound(self, name, user=None, **over):
        return user_store.create_hound((user or self.owner).id, spec_dict(name=name, **over))

    def ledger_bytes(self) -> bytes:
        p = Path(self.ledger)
        return p.read_bytes() if p.exists() else b""

    def add_ledger(self, hound_id, n=4):
        from src.ledger.chain import HashChainLedger
        chain = HashChainLedger(self.ledger)
        for row in ledger_rows(hound_id, n):
            chain.append(row)


class WhatCountsAsARemoval(StoreCase):
    def test_a_removal_is_an_owner_retirement_that_is_not_a_supersede(self):
        a = self.hound("Remove Me")
        gone = user_store.retire_hound(a["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        self.assertTrue(user_store.removed_by_owner(gone))
        self.assertFalse(user_store.removed_by_owner(a))                            # still running

    def test_an_edit_retires_the_old_version_but_that_is_not_a_removal(self):
        a = self.hound("Edit Me")
        new = user_store.create_version(a["id"], spec_dict(name="Edit Me", price_max=300), actor=f"owner:{self.owner.id}", reason="edited")
        old = user_store.get_hound(a["id"])
        self.assertEqual(old["status"], "retired")
        self.assertFalse(user_store.removed_by_owner(old))
        self.assertEqual(user_store.removed_roots([old, new]), set())

    def test_a_moderators_retirement_is_not_the_owners_removal(self):
        a = self.hound("Flagged")
        gone = user_store.retire_hound(a["id"], by="admin", reason="name complaint")
        self.assertFalse(user_store.removed_by_owner(gone))

    def test_removing_the_newest_version_removes_the_whole_lineage(self):
        a = self.hound("Many Lives")
        b = user_store.create_version(a["id"], spec_dict(name="Many Lives", price_max=300), actor=f"owner:{self.owner.id}", reason="edit 1")
        c = user_store.create_version(b["id"], spec_dict(name="Many Lives", price_max=350), actor=f"owner:{self.owner.id}", reason="edit 2")
        c = user_store.retire_hound(c["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        rows = user_store.list_for_owner(self.owner.id)
        self.assertEqual(user_store.removed_roots(rows), {a["root_id"]})
        # but a lineage whose newest version is alive is not removed, however old its retired versions are
        d = self.hound("Still Here")
        user_store.create_version(d["id"], spec_dict(name="Still Here", price_max=300), actor=f"owner:{self.owner.id}", reason="edit")
        self.assertNotIn(d["root_id"], user_store.removed_roots(user_store.list_for_owner(self.owner.id)))


class TheKennelAfterARemoval(StoreCase):
    def test_a_removed_dog_and_its_old_versions_leave_my_kennel_and_the_others_stay(self):
        keep = self.hound("Keeper")
        gone = self.hound("Goner")
        gone2 = user_store.create_version(gone["id"], spec_dict(name="Goner", price_max=300), actor=f"owner:{self.owner.id}", reason="edit")
        user_store.retire_hound(gone2["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        out = kennels.my_kennel(self.owner.id)
        self.assertEqual([d["name"] for d in out["dogs"]], ["Keeper"])
        self.assertEqual((out["dog_count"], out["removed_count"]), (1, 1))
        self.assertEqual([d["id"] for d in out["dogs"]], [keep["id"]])

    def test_a_retirement_that_is_not_a_removal_still_shows_in_the_retired_list(self):
        a = self.hound("Superseded")
        user_store.create_version(a["id"], spec_dict(name="Superseded", price_max=300), actor=f"owner:{self.owner.id}", reason="edit")
        out = kennels.my_kennel(self.owner.id)
        self.assertEqual(sorted((d["name"], d["retired"]) for d in out["dogs"]), [("Superseded", False), ("Superseded", True)])
        self.assertEqual(out["removed_count"], 0)

    def test_a_removed_dog_is_not_in_a_public_kennel_either(self):
        a = self.hound("Public Goner")
        self.hound("Public Keeper")
        user_store.retire_hound(a["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        detail = kennels.kennel_detail(kennels.handle_for(self.owner.id))
        self.assertEqual([d["name"] for d in detail["dogs"]], ["Public Keeper"])

    def test_it_stops_betting_and_frees_its_slot(self):
        dogs = [self.hound(f"{w} Pack") for w in ("Alpha", "Bravo", "Cedar", "Delta", "Ember")]
        with self.assertRaises(user_store.StoreError):
            self.hound("Fourth")
        user_store.retire_hound(dogs[0]["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        self.assertNotIn(dogs[0]["id"], [h["id"] for h in user_store.list_running()])
        self.hound("Fourth")                                            # the slot is free again

    def test_its_record_and_ledger_are_exactly_as_they_were(self):
        a = self.hound("Has A Record")
        self.add_ledger(a["id"], 4)
        before = self.ledger_bytes()
        self.assertTrue(before)
        gone = user_store.retire_hound(a["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        self.assertEqual(self.ledger_bytes(), before)                   # append-only: not one byte changed
        self.assertEqual(gone["spec_hash"], a["spec_hash"])             # the rule it bet under is the rule on file
        self.assertEqual(gone["spec"], a["spec"])
        self.assertEqual(user_store.get_hound(a["id"])["id"], a["id"])  # and its address still resolves

    def test_the_dog_page_and_graveyard_say_retired_by_the_owner(self):
        a = self.hound("Page Dog")
        user_store.retire_hound(a["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON)
        definition = user_defs.get_definition(a["id"])
        self.assertEqual(definition["retired"]["cause"], "retired by the owner")
        self.assertIsNotNone(definition["retired"]["date"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(StoreCase):
    def setUp(self):
        super().setUp()
        from api import hounds_create as api
        self.api = api
        self.token = users_store.issue_invite_token(self.owner.id, db=self.db)
        self.other_token = users_store.issue_invite_token(self.other.id, db=self.db)
        p = mock.patch.dict("os.environ", {"APP_ADMIN_TOKEN": "admin-secret"})
        p.start()
        self.addCleanup(p.stop)

    def create(self, **over):
        body = self.api.CreateHoundRequest(spec=spec_dict(**over))
        return self.api.create_hound(body, current_user=self.owner, _rl=None)["hound"]

    def retire(self, hound_id, reason=None, token=None, admin=None):
        return self.api.retire_hound(hound_id, self.api.RetireRequest(reason=reason),
                                     authorization=f"Bearer {token or self.token}" if not admin else None, x_admin_token=admin)

    def test_the_owner_removes_a_dog_with_no_words_and_the_summary_says_so(self):
        h = self.create(name="Remove Me")
        out = self.retire(h["id"])["hound"]
        self.assertEqual((out["status"], out["removed_by_owner"], out["retire_reason"]), ("retired", True, user_store.OWNER_REMOVED_REASON))
        self.assertEqual(user_store.get_hound(h["id"])["retired_by"], f"owner:{self.owner.id}")

    def test_an_owner_may_still_give_their_own_words(self):
        h = self.create(name="Remove Me")
        out = self.retire(h["id"], reason="not for me")["hound"]
        self.assertEqual((out["retire_reason"], out["removed_by_owner"]), ("not for me", True))

    def test_only_the_owner_can_and_a_stranger_reads_as_not_found(self):
        h = self.create(name="Remove Me")
        with self.assertRaises(HTTPException) as ctx:
            self.retire(h["id"], token=self.other_token)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(user_store.get_hound(h["id"])["status"], "running")
        with self.assertRaises(HTTPException) as ctx:
            self.api.retire_hound(h["id"], self.api.RetireRequest(), authorization=None, x_admin_token=None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_an_admin_still_has_to_give_a_reason(self):
        h = self.create(name="Moderated")
        with self.assertRaises(HTTPException) as ctx:
            self.retire(h["id"], admin="admin-secret")
        self.assertEqual(ctx.exception.status_code, 422)
        out = self.retire(h["id"], reason="name complaint", admin="admin-secret")["hound"]
        self.assertEqual((out["status"], out["removed_by_owner"]), ("retired", False))

    def test_removing_twice_is_harmless_and_keeps_the_first_retirement(self):
        h = self.create(name="Remove Me")
        first = self.retire(h["id"])["hound"]
        second = self.retire(h["id"], reason="changed my mind about why")["hound"]
        self.assertEqual(second["retire_reason"], first["retire_reason"])

    def test_the_kennel_route_data_drops_it_and_the_list_keeps_it_flagged(self):
        h = self.create(name="Remove Me")
        keep = self.create(name="Keep Me")
        self.retire(h["id"])
        self.assertEqual([d["id"] for d in kennels.my_kennel(self.owner.id)["dogs"]], [keep["id"]])
        mine = {d["id"]: d for d in self.api.my_hounds(current_user=self.owner, _rl=None)["hounds"]}
        self.assertTrue(mine[h["id"]]["removed_by_owner"])
        self.assertFalse(mine[keep["id"]]["removed_by_owner"])

    # ---- a classic dog is edited as rules and saved as version 2 ---------------------------------------
    def test_a_classic_dog_opens_as_its_equivalent_rule_set_and_saves_as_a_new_version(self):
        h = self.create(name="Old Strategy", side_rule="underdog", markets=["moneyline"], price_min=100, price_max=250)
        self.assertEqual(user_store.get_hound(h["id"])["spec"]["version"], 1)              # a real classic dog
        self.add_ledger(h["id"], 4)
        before = self.ledger_bytes()
        old_hash = user_store.get_hound(h["id"])["spec_hash"]

        mine = self.api.my_hounds(current_user=self.owner, _rl=None)["hounds"][0]
        draft = mine["spec"]
        self.assertEqual(draft["version"], 2)
        self.assertEqual(draft["rules"][0]["when"]["items"], [{"id": "role", "value": "underdog"}])
        self.assertEqual((draft["rules"][0]["price_min"], draft["rules"][0]["price_max"]), (100, 250))
        self.assertTrue(mine["rule_sentences"])

        # the page saves what the cards show: the draft with a head-to-head condition added
        edited = deepcopy(draft)
        edited["rules"][0]["when"]["items"].append(user_rules.default_instance("head_to_head"))
        diff = self.api.hound_diff(h["id"], self.api.PreviewRequest(spec=edited), current_user=self.owner, _rl=None)
        self.assertTrue(diff["changes"])
        out = self.api.hound_new_version(h["id"], self.api.VersionRequest(spec=edited, reason="edited in the builder"),
                                         current_user=self.owner, _rl=None)
        new = user_store.get_hound(out["hound"]["id"])
        self.assertEqual((new["version_no"], new["version_of"], new["root_id"]), (2, h["id"], h["id"]))
        self.assertEqual(new["spec"]["version"], 2)
        self.assertEqual([c["id"] for c in new["spec"]["rules"][0]["when"]["items"]], ["role", "head_to_head"])
        self.assertEqual(new["name"], "Old Strategy")                                       # the lineage keeps its name
        old = user_store.get_hound(h["id"])
        self.assertEqual((old["status"], old["spec"]["version"], old["spec_hash"]), ("retired", 1, old_hash))
        self.assertEqual(self.ledger_bytes(), before)                                       # every bet on it untouched
        self.assertTrue(render.rule_sentences(new["spec"])[0])
        # the old row still carries its 4 bets in the owner's list
        listed = {d["id"]: d for d in self.api.my_hounds(current_user=self.owner, _rl=None)["hounds"]}
        self.assertEqual(listed[h["id"]]["record"]["bets"], 4)

    def test_every_classic_side_rule_opens_and_saves_unchanged_as_a_valid_version(self):
        for i, side_rule in enumerate(("favourite", "underdog", "home", "away", "market_moved_toward", "market_moved_away")):
            h = self.create(name=f"Classic {i}", side_rule=side_rule, price_min=-150 if side_rule == "favourite" else 100)
            draft = next(d for d in self.api.my_hounds(current_user=self.owner, _rl=None)["hounds"] if d["id"] == h["id"])["spec"]
            out = self.api.hound_new_version(h["id"], self.api.VersionRequest(spec=draft), current_user=self.owner, _rl=None)
            self.assertEqual(out["hound"]["version_no"], 2, side_rule)
            self.assertEqual(user_store.get_hound(h["id"])["status"], "retired", side_rule)
            self.retire(out["hound"]["id"])                                                # keep the account under its dog limit

    def test_one_dog_whose_summary_cannot_be_built_does_not_take_the_list_down(self):
        a = self.create(name="Fine Dog")
        b = self.create(name="Broken Dog", side_rule="favourite", price_min=-150)
        real = self.api.owner_summary

        def flaky(hound, **kw):
            if hound["id"] == b["id"]:
                raise RuntimeError("a record that cannot be built")
            return real(hound, **kw)
        with mock.patch.object(self.api, "owner_summary", flaky):
            out = self.api.my_hounds(current_user=self.owner, _rl=None)["hounds"]
        by = {d["id"]: d for d in out}
        self.assertEqual(set(by), {a["id"], b["id"]})
        self.assertNotIn("summary_unavailable", by[a["id"]])
        broken = by[b["id"]]
        self.assertTrue(broken["summary_unavailable"])
        self.assertEqual(broken["spec"]["version"], 2)                       # still editable: its rules came from the store row
        self.assertEqual(broken["spec"]["rules"][0]["when"]["items"], [{"id": "role", "value": "favourite"}])
        self.assertTrue(broken["rule_sentences"])
        self.assertEqual(broken["status"], "running")


if __name__ == "__main__":
    unittest.main()
