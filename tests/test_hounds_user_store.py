"""src/hounds/user_store.py: limits, accounts, versions, retirement, copies."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import user_spec, user_store
from tests._hounds_user_fixtures import spec_dict


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._patch.start()
        self.user = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.other = users_store.create_user("other@example.com", status="invited", db=self.db)

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def make(self, user=None, **over):
        over.setdefault("name", f"Hound {len(user_store.list_all()) + 1}")
        return user_store.create_hound((user or self.user).id, spec_dict(**over))


class Creation(StoreCase):
    def test_create_returns_a_running_version_one(self):
        h = self.make(name="Dog Days")
        self.assertEqual((h["status"], h["version_no"], h["version_of"], h["root_id"]),
                         ("running", 1, None, h["id"]))
        self.assertEqual(h["spec"]["name"], "Dog Days")
        self.assertFalse(h["coach_opt_in"])

    def test_the_sixth_running_hound_is_refused(self):
        for i in range(5):
            self.make(name=f"Pack {i}")
        with self.assertRaises(user_store.StoreError) as ctx:
            self.make(name="Pack 6")
        self.assertEqual(ctx.exception.code, "limit")

    def test_the_limit_is_per_account_and_a_retirement_frees_a_slot(self):
        words = ("Alpha", "Bravo", "Cedar", "Delta", "Ember")
        hounds = [self.make(name=f"{w} Pack") for w in words]
        self.make(self.other, name="Other One")                    # a different account is unaffected
        user_store.retire_hound(hounds[0]["id"], by="owner", reason="done")
        self.make(name="Fargo Pack")                              # the freed slot
        self.assertEqual(len([h for h in user_store.list_for_owner(self.user.id)
                              if h["status"] == "running"]), 5)

    def test_only_an_existing_unsuspended_account_may_create(self):
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_hound(9999, spec_dict())
        self.assertEqual(ctx.exception.code, "no_account")
        users_store.set_user_status(self.other.id, "suspended", db=self.db)
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_hound(self.other.id, spec_dict())
        self.assertEqual(ctx.exception.code, "account_suspended")

    def test_names_are_unique_across_accounts(self):
        self.make(name="Dog Days")
        with self.assertRaises(user_spec.SpecError):
            self.make(self.other, name="dog days")

    def test_an_invalid_spec_creates_nothing(self):
        with self.assertRaises(user_spec.SpecError):
            user_store.create_hound(self.user.id, spec_dict(price_min=-250))
        self.assertEqual(user_store.list_all(), [])


class VersionsAndRetirement(StoreCase):
    def test_a_changed_rule_is_a_new_hound_and_the_old_row_is_untouched(self):
        old = self.make(name="Dog Days")
        new = user_store.create_version(old["id"], spec_dict(name="Dog Days", side_rule="favourite",
                                                              price_min=-150, price_max=100),
                                        actor="owner", reason="try favourites")
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual((new["version_of"], new["version_no"], new["root_id"], new["status"]),
                         (old["id"], 2, old["root_id"], "running"))
        after = user_store.get_hound(old["id"])
        self.assertEqual(after["spec"], old["spec"])             # the rule was never rewritten
        self.assertEqual(after["status"], "retired")
        self.assertIn(new["id"], after["retire_reason"])
        self.assertEqual([h["id"] for h in user_store.lineage(new["id"])], [old["id"], new["id"]])

    def test_a_new_version_does_not_count_against_the_limit(self):
        hs = [self.make(name=f"Pack {i}") for i in range(3)]
        user_store.create_version(hs[0]["id"], spec_dict(name="Pack 0", min_books=5),
                                  actor="owner", reason="x")
        self.assertEqual(len([h for h in user_store.list_for_owner(self.user.id)
                              if h["status"] == "running"]), 3)

    def test_a_retired_hound_cannot_be_versioned(self):
        h = self.make(name="Dog Days")
        user_store.retire_hound(h["id"], by="owner", reason="done")
        with self.assertRaises(user_store.StoreError):
            user_store.create_version(h["id"], spec_dict(name="Dog Days"), actor="owner", reason="x")

    def test_retire_needs_a_reason_and_keeps_the_first_retirement(self):
        h = self.make(name="Dog Days")
        with self.assertRaises(user_store.StoreError):
            user_store.retire_hound(h["id"], by="admin", reason="  ")
        first = user_store.retire_hound(h["id"], by="admin", reason="moderation")
        again = user_store.retire_hound(h["id"], by="owner", reason="later")
        self.assertEqual(first["retire_reason"], again["retire_reason"])
        self.assertEqual(again["retired_by"], "admin")

    def test_copies_carry_copied_from_and_need_their_own_name(self):
        src = self.make(name="Dog Days")
        with self.assertRaises(user_spec.SpecError):
            user_store.create_hound(self.other.id, spec_dict(name="Dog Days"), copied_from=src["id"])
        suggested = user_store.suggest_copy_name("Dog Days")
        copy = user_store.create_hound(self.other.id, spec_dict(name=suggested), copied_from=src["id"])
        self.assertEqual(copy["copied_from"], src["id"])
        self.assertEqual(copy["root_id"], copy["id"])            # a copy is its own lineage
        self.assertEqual(copy["spec_hash"], src["spec_hash"])    # same rule, recognisably

    def test_copying_an_unknown_hound_is_refused(self):
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_hound(self.user.id, spec_dict(), copied_from="u-nope")
        self.assertEqual(ctx.exception.code, "unknown_source")

    def test_suggested_names_fit_the_name_rules(self):
        long = "A" * 24
        self.make(name=long)
        name = user_store.suggest_copy_name(long)
        self.assertLessEqual(len(name), user_spec.NAME_MAX)
        user_spec.validate_spec(spec_dict(name=name), taken_names=user_store.taken_names())


if __name__ == "__main__":
    unittest.main()
