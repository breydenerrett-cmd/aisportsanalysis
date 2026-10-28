"""Go back to an earlier version (src/hounds/interact/revert.py), owner request 2026-10-28: "a way for users to undo an upgraded hound".

The story each group pins, every one failing on the code before ``revert`` existed:

  GOING BACK   makes version n+1 with a COPY of the chosen version's rules; no old row is reopened or edited, every old record stays
               with the version that earned it, the copy starts empty; it is not a training (no event, no five-bet wait)
  THE REFUSALS owner only (someone else's hound reads as not found), a hound the house owns, a buried hound, a version it does not
               have, the version it is already on, a version with the same rules, a version whose rules no longer pass the checks
               (with the checker's reason), a list that was opened on another version than the hound is on now
  THE LIST     v1..vN oldest first with status, when, why and the FORWARD record of each version
  UNDO         the card after a Fine-tune or a Full rebuild carries an Undo that is exactly "go back to the version just retired"

No FastAPI is needed for the first four groups; the route group is skipped where FastAPI is not installed.
"""

from __future__ import annotations

import copy
import json
import unittest

try:
    from fastapi import Response
except ImportError:  # pragma: no cover
    Response = None

from src.hounds import user_spec, user_store
from src.hounds.interact import common, revert, training_plans as plans
from src.hounds.interact.rites import RiteError
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for, write_ledger
from tests._hounds_user_fixtures import spec_dict
from tests.test_training_plans import MIXED, Base as PlanBase


class Lineage(RitesCase):
    """A hound with two versions: v1 (MLB underdogs, +100 to +250) edited into v2 (MLB and NFL, +100 to +300), each with its own tickets."""

    def setUp(self):
        super().setUp()
        self.v1 = self.dog("Rusty Pup", sports=["MLB"], price_min=100, price_max=250)
        self.v2 = user_store.create_version(self.v1["id"], spec_dict(name="Rusty Pup", sports=["MLB", "NFL"], price_min=100, price_max=300),
                                            actor=f"owner:{self.owner.id}", reason="edited by its owner", db=self.db)
        self.rows = (rows_for(self.v1["id"], [(3, dict(result="WIN", side="away", price=150)), (2, dict(result="LOSS", side="away", price=150))])
                     + rows_for(self.v2["id"], [(1, dict(result="WIN", side="away", price=120)), (4, dict(result="LOSS", side="away", price=120))]))
        write_ledger(self.ledger, self.rows)

    def dog_of(self, hound):
        return common.resolve(hound["id"])

    def back(self, to, hound=None, user=None, **kw):
        return revert.go_back(self.dog_of(hound or self.v2), (user or self.owner).id, to, now=NOW, db=self.db, **kw)

    def lineage(self):
        return user_store.lineage(self.v1["id"], db=self.db)


class GoingBack(Lineage):
    def test_it_makes_the_next_version_with_the_chosen_versions_rules(self):
        out = self.back(1)
        new = user_store.get_hound(out["new"]["id"], db=self.db)
        self.assertEqual((new["version_no"], new["status"], new["origin"]), (3, "running", user_store.ORIGIN_REVERT))
        self.assertEqual(user_spec.spec_hash(new["spec"]), user_spec.spec_hash(self.v1["spec"]))
        self.assertEqual(new["spec"]["sports"], ["MLB"])
        self.assertEqual(new["version_of"], self.v2["id"])
        self.assertEqual(len(self.lineage()), 3)
        self.assertEqual((out["mode"], out["restored_from"], out["old"]["version_no"], out["new"]["version_no"]), ("revert", 1, 2, 3))
        self.assertEqual(out["new"]["record"], {"wins": 0, "losses": 0, "pushes": 0, "bets": 0})

    def test_the_version_it_leaves_is_retired_with_the_reason_and_no_old_row_is_touched(self):
        before = {h["id"]: copy.deepcopy(h) for h in self.lineage()}
        self.back(1)
        after = {h["id"]: h for h in self.lineage()}
        v2 = after[self.v2["id"]]
        self.assertEqual(v2["status"], "retired")
        self.assertIn("restored from v1", v2["retire_reason"])
        self.assertEqual(v2["spec"], before[self.v2["id"]]["spec"])
        v1 = after[self.v1["id"]]                                          # version 1 was retired by the edit and is exactly as it was
        self.assertEqual({k: v1[k] for k in v1 if k != "retire_reason"}, {k: before[self.v1["id"]][k] for k in v1 if k != "retire_reason"})
        self.assertEqual(v1["retire_reason"], before[self.v1["id"]]["retire_reason"])
        self.assertEqual(v1["status"], "retired")

    def test_every_old_record_stays_with_the_version_that_earned_it_and_the_copy_starts_empty(self):
        out = self.back(1)
        from src.hounds.interact import rites
        self.assertEqual(len(rites.forward_bets(self.v1["id"], self.rows)), 5)
        self.assertEqual(len(rites.forward_bets(self.v2["id"], self.rows)), 5)
        self.assertEqual(rites.forward_bets(out["new"]["id"], self.rows), [])
        listed = revert.versions(self.dog_of(self.v2), self.owner.id, rows=self.rows, db=self.db)
        by_no = {v["version_no"]: v for v in listed["versions"]}
        self.assertEqual((by_no[1]["record"]["wins"], by_no[1]["record"]["losses"]), (3, 2))
        self.assertEqual((by_no[2]["record"]["wins"], by_no[2]["record"]["losses"]), (1, 4))
        self.assertEqual(by_no[3]["record"]["bets"], 0)

    def test_the_hound_keeps_its_name_and_look_while_the_rules_go_back(self):
        renamed = user_store.create_version(self.v2["id"], spec_dict(name="Rusty Pup", tagline="Fetch", sports=["MLB", "NFL"], price_min=100,
                                                                    price_max=300, max_bets_per_day=3), actor="owner", reason="edit", db=self.db)
        out = self.back(1, hound=renamed)
        new = user_store.get_hound(out["new"]["id"], db=self.db)
        self.assertEqual((new["name"], new["tagline"]), ("Rusty Pup", "Fetch"))
        self.assertEqual(new["spec"]["max_bets_per_day"], self.v1["spec"]["max_bets_per_day"])

    def test_it_is_not_a_training(self):
        trained = user_store.trained_count(self.v1["root_id"], db=self.db)
        self.back(1)
        self.assertEqual(user_store.trained_count(self.v1["root_id"], db=self.db), trained)
        self.assertEqual([e for e in user_store.list_events(root_id=self.v1["root_id"]) if e["kind"] == user_store.EVENT_TRAINED], [])

    def test_it_works_from_the_page_of_an_old_version_too(self):
        self.back(1)                                                       # the hound went back to version 1's rules (as version 3) ...
        out = self.back(2, hound=self.v1)                                  # ... and the owner, on version 1's old page, goes forward to version 2's
        self.assertEqual(out["new"]["version_no"], 4)
        self.assertEqual(user_spec.spec_hash(user_store.get_hound(out["new"]["id"], db=self.db)["spec"]), user_spec.spec_hash(self.v2["spec"]))

    def test_going_back_twice_stacks_versions_and_never_reuses_a_row(self):
        first = self.back(1)
        second = revert.go_back(common.resolve(first["new"]["id"]), self.owner.id, 2, now=NOW, db=self.db)
        self.assertEqual(second["new"]["version_no"], 4)
        self.assertEqual(len({h["id"] for h in self.lineage()}), 4)


class TheRefusals(Lineage):
    def refused(self, code, status, *args, **kw):
        before = len(self.lineage())
        with self.assertRaises(RiteError) as ctx:
            self.back(*args, **kw)
        self.assertEqual((ctx.exception.code, ctx.exception.status), (code, status))
        self.assertEqual(len(self.lineage()), before)                        # nothing was written
        return ctx.exception

    def test_someone_elses_hound_reads_as_not_found(self):
        self.refused("not_found", 404, 1, user=self.other)

    def test_no_such_hound(self):
        with self.assertRaises(RiteError) as ctx:
            revert.go_back(None, self.owner.id, 1, db=self.db)
        self.assertEqual(ctx.exception.status, 404)

    def test_a_house_hound_has_no_versions_to_go_back_to(self):
        house = common.Dog(id="pack-1", kind=common.KIND_HOUSE, name="Chalk Chihuahua")
        with self.assertRaises(RiteError) as ctx:
            revert.go_back(house, self.owner.id, 1, db=self.db)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_a_member_dog", 422))

    def test_the_version_it_is_already_on_is_refused(self):
        self.refused("already_current", 409, 2)

    def test_a_version_with_the_same_rules_as_the_current_one_is_refused(self):
        same = user_store.create_version(self.v2["id"], spec_dict(name="Rusty Pup", tagline="Fetch", sports=["MLB", "NFL"], price_min=100,
                                                                 price_max=300), actor="owner", reason="catchphrase", db=self.db)
        exc = self.refused("same_rules", 409, 2, hound=same)
        self.assertIn("same rules", str(exc))

    def test_a_version_the_hound_never_had_is_refused(self):
        self.refused("no_such_version", 404, 9)

    def test_a_version_number_must_be_a_whole_number(self):
        self.refused("bad_version", 422, "1")
        self.refused("bad_version", 422, True)

    def test_a_version_whose_rules_no_longer_pass_the_checks_is_refused_with_the_reason(self):
        spec = copy.deepcopy(self.v1["spec"])
        spec["price_min"] = -250                                               # a price the menu has since refused
        with user_store._connect(self.db) as conn:                             # noqa: SLF001 -- how an old row that no longer validates is made
            conn.execute("UPDATE hounds SET spec_json = ? WHERE id = ?", (json.dumps(spec), self.v1["id"]))
        exc = self.refused("spec_invalid", 422, 1)
        self.assertIn("no longer pass", str(exc))
        self.assertIn("price_min", str(exc))

    def test_a_list_opened_on_another_version_is_refused_in_words(self):
        exc = self.refused("version_stale", 409, 1, current_id=self.v1["id"])
        self.assertIn("moved to another version", str(exc))

    def test_a_buried_hound_cannot_go_back(self):
        user_store.bury_hound(self.v2["id"], owner_user_id=self.owner.id, payload={"name": "Rusty Pup"}, db=self.db)
        self.refused("already_buried", 409, 1)

    def test_a_hound_its_owner_removed_cannot_go_back(self):
        user_store.retire_hound(self.v2["id"], by=f"owner:{self.owner.id}", reason=user_store.OWNER_REMOVED_REASON, db=self.db)
        self.refused("not_active", 409, 1)


class TheList(Lineage):
    def test_every_version_oldest_first_with_status_when_why_and_the_forward_record(self):
        out = revert.versions(self.dog_of(self.v2), self.owner.id, rows=self.rows, db=self.db)
        self.assertEqual([v["version_no"] for v in out["versions"]], [1, 2])
        v1, v2 = out["versions"]
        self.assertEqual((v1["status"], v2["status"], out["current"]["version_no"]), ("earlier", "current", 2))
        self.assertEqual(v1["why"], "The first version")
        self.assertEqual(v2["why"], "Edited by its owner")
        self.assertTrue(v1["created_at"] and v1["retired_at"])
        self.assertEqual((v1["can_go_back"], v2["can_go_back"]), (True, False))
        self.assertEqual(v2["cannot_reason"], "This is the version it is on now.")
        self.assertEqual({k: v1["record"][k] for k in ("wins", "losses", "graded", "open")}, {"wins": 3, "losses": 2, "graded": 5, "open": 0})
        self.assertTrue(v1["rule_text"])
        self.assertIs(out["paper_only"], True)

    def test_a_reverted_version_says_where_it_went_back_to(self):
        self.back(1)
        out = revert.versions(self.dog_of(self.v2), self.owner.id, rows=self.rows, db=self.db)
        last = out["versions"][-1]
        self.assertEqual((last["version_no"], last["why"]), (3, "Went back to version 1"))
        self.assertEqual({v["version_no"]: v["can_go_back"] for v in out["versions"]}, {1: False, 2: True, 3: False})   # v1 now equals the current rules

    def test_it_is_the_owners_alone(self):
        with self.assertRaises(RiteError) as ctx:
            revert.versions(self.dog_of(self.v2), self.other.id, rows=self.rows, db=self.db)
        self.assertEqual(ctx.exception.status, 404)

    def test_open_tickets_are_counted_apart_from_the_graded_ones(self):
        rows = self.rows + rows_for(self.v2["id"], [(2, dict(result=None, side="away", price=120, start_hours_ago=1, now=NOW))])
        out = revert.versions(self.dog_of(self.v2), self.owner.id, rows=rows, db=self.db)
        self.assertEqual((out["versions"][1]["record"]["graded"], out["versions"][1]["record"]["open"]), (5, 2))


class UndoAfterApply(PlanBase):
    """The card a Fine-tune or a Full rebuild leaves carries an Undo that goes back to the version it just retired."""

    def apply_fine(self):
        card = self.fine()
        self.assertTrue(card["found"])
        return plans.apply_plan(self.dog_obj(), self.owner.id, card["plan_id"], now=NOW, rows=self.rows, db=self.db, store=self.store)

    def test_the_applied_card_offers_an_undo_to_the_version_it_retired(self):
        out = self.apply_fine()
        self.assertEqual(out["undo"], {"available": True, "to_version": 1, "from_version": 2, "retired_id": self.hound_row["id"],
                                       "label": "Undo (go back to version 1)"})

    def test_undo_makes_version_three_with_version_ones_rules(self):
        out = self.apply_fine()
        undone = revert.go_back(common.resolve(out["new"]["id"]), self.owner.id, out["undo"]["to_version"], current_id=out["new"]["id"],
                                now=NOW, db=self.db)
        new = user_store.get_hound(undone["new"]["id"], db=self.db)
        self.assertEqual(new["version_no"], 3)
        self.assertEqual(user_spec.spec_hash(new["spec"]), user_spec.spec_hash(self.hound_row["spec"]))
        self.assertEqual(user_store.get_hound(out["new"]["id"], db=self.db)["status"], "retired")
        self.assertEqual(undone["undo"]["to_version"], 2)                       # and the undo of an undo goes forward again

    def test_a_rebuild_card_offers_it_too(self):
        card, _client = self.rebuild()
        out = plans.apply_plan(self.dog_obj(), self.owner.id, card["plan_id"], now=NOW, rows=self.rows, db=self.db, store=self.store)
        self.assertEqual(out["undo"]["to_version"], 1)


@unittest.skipIf(Response is None, "FastAPI is not installed")
class Routes(Lineage):
    def setUp(self):
        super().setUp()
        from api import hounds_interact as api
        self.api = api

    def call_err(self, fn, *a, **k):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            fn(*a, **k)
        exc = ctx.exception
        return exc.status_code, (exc.detail["error"] if isinstance(exc.detail, dict) else exc.detail)

    def test_the_owner_reads_the_list_and_goes_back_with_a_confirm(self):
        out = self.api.hound_versions(self.v2["id"], Response(), current_user=self.owner, _rl=None)
        self.assertEqual([v["version_no"] for v in out["versions"]], [1, 2])
        body = self.api.RevertRequest(version_no=1, current_id=self.v2["id"], confirm=False)
        self.assertEqual(self.call_err(self.api.hound_revert, self.v2["id"], body, Response(), current_user=self.owner, _rl=None),
                         (400, "confirm_required"))
        body = self.api.RevertRequest(version_no=1, current_id=self.v2["id"], confirm=True)
        done = self.api.hound_revert(self.v2["id"], body, Response(), current_user=self.owner, _rl=None)
        self.assertEqual((done["mode"], done["new"]["version_no"], done["undo"]["to_version"]), ("revert", 3, 2))

    def test_someone_else_gets_a_404_for_the_list_and_for_the_revert(self):
        self.assertEqual(self.call_err(self.api.hound_versions, self.v2["id"], Response(), current_user=self.other, _rl=None)[0], 404)
        body = self.api.RevertRequest(version_no=1, confirm=True)
        self.assertEqual(self.call_err(self.api.hound_revert, self.v2["id"], body, Response(), current_user=self.other, _rl=None)[0], 404)
        self.assertEqual(len(self.lineage()), 2)

    def test_the_routes_are_registered(self):
        paths = {(r.path, tuple(sorted(r.methods))) for r in self.api.router.routes}
        self.assertIn(("/hounds/{hound_id}/versions", ("GET",)), paths)
        self.assertIn(("/hounds/{hound_id}/revert", ("POST",)), paths)


if __name__ == "__main__":
    unittest.main()
