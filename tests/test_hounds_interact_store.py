"""Feedback storage and the locker-room whitelist (src/hounds/interact/store.py, look.py). No FastAPI needed."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds.interact import look, store

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)


class Db(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)

    def vote(self, user=1, verdict="good", kind="ticket", target="2026-10-18|Boston Red Sox to win", note=None,
             dog="u-1", root="u-1", now=NOW):
        return store.record_vote(hound_id=dog, root_id=root, kind=kind, target_id=target, verdict=verdict,
                                 note=note, user_id=user, now=now)


class Feedback(Db):
    def test_a_vote_is_stored_with_dog_target_verdict_note_user_and_time(self):
        self.vote(note="Fair price")
        with store.connect() as conn:
            row = dict(conn.execute("SELECT * FROM hound_feedback").fetchone())
        self.assertEqual((row["hound_id"], row["target_kind"], row["target_id"], row["verdict"], row["note"],
                          row["user_id"], row["created_at"]),
                         ("u-1", "ticket", "2026-10-18|Boston Red Sox to win", "good", "Fair price", 1,
                          "2026-10-19T18:00:00Z"))

    def test_a_second_vote_replaces_the_first_and_does_not_double_count(self):
        self.vote(verdict="good")
        self.vote(verdict="bad", note="changed my mind")
        c = store.counts("u-1")
        self.assertEqual((c["good"], c["bad"]), (0, 1))
        self.vote(user=2, verdict="good")
        c = store.counts("u-1")
        self.assertEqual((c["good"], c["bad"]), (1, 1))
        self.assertEqual(c["by_target"]["ticket:2026-10-18|Boston Red Sox to win"], {"good": 1, "bad": 1})

    def test_counts_split_by_kind_and_a_lineage_shares_its_votes(self):
        self.vote(kind="ticket")
        self.vote(user=2, kind="answer", target="record")
        self.vote(user=3, kind="dog", target="")
        self.vote(user=4, dog="u-2", root="u-1")                       # a newer version of the same dog
        c = store.counts("u-1")
        self.assertEqual(c["good"], 4)
        self.assertEqual(set(c["by_kind"]), {"ticket", "answer", "dog"})
        self.assertEqual(store.counts("someone-else")["good"], 0)

    def test_my_votes_show_a_person_what_they_chose_and_nobody_elses(self):
        self.vote(user=1, verdict="good")
        self.vote(user=2, verdict="bad")
        self.assertEqual(store.my_votes("u-1", 1), {"ticket:2026-10-18|Boston Red Sox to win": "good"})
        self.assertEqual(store.my_votes("u-1", 2), {"ticket:2026-10-18|Boston Red Sox to win": "bad"})

    def test_the_owners_notes_carry_no_user_id(self):
        self.vote(note="Good price", user=11)
        notes = store.notes_for_owner("u-1")
        self.assertEqual(notes[0]["note"], "Good price")
        self.assertEqual(set(notes[0]), {"target_kind", "target_id", "verdict", "note", "created_at"})
        self.assertNotIn(11, notes[0].values())

    def test_a_note_is_trimmed_limited_and_filtered(self):
        self.assertEqual(store.clean_note("  nice   price "), "nice price")
        self.assertIsNone(store.clean_note("   "))
        self.assertIsNone(store.clean_note(None))
        with self.assertRaises(store.FeedbackError) as ctx:
            store.clean_note("x" * 201)
        self.assertEqual(ctx.exception.code, "note_too_long")
        with self.assertRaises(store.FeedbackError) as ctx:
            store.clean_note("this dog is shit")
        self.assertEqual(ctx.exception.code, "note_not_allowed")
        with self.assertRaises(store.FeedbackError):
            store.clean_note(12)

    def test_targets_are_checked(self):
        self.assertEqual(store.clean_target("dog", "ignored"), "")
        self.assertEqual(store.clean_target("answer", " record "), "record")
        for bad in (("ticket", ""), ("ticket", "x" * 121), ("elephant", "x"), ("suggestion", "x")):
            with self.assertRaises(store.FeedbackError):
                store.clean_target(*bad)

    def test_only_good_or_bad_is_a_verdict(self):
        with self.assertRaises(store.FeedbackError):
            self.vote(verdict="great")

    def test_sixty_votes_an_hour_per_person_then_a_429(self):
        for i in range(60):
            self.vote(target=f"t{i}")
        with self.assertRaises(store.FeedbackError) as ctx:
            self.vote(target="one-more")
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("rate_limited", 429))
        self.vote(target="one-more", now=NOW + timedelta(hours=1, minutes=1))      # an hour later it is fine
        self.vote(user=2, target="another-person")

    def test_a_suggestion_is_kept_for_the_owner_and_never_counted_as_a_vote(self):
        store.record_suggestion(hound_id="u-1", root_id="u-1", change={"price_max": 150}, note="too long a band",
                                user_id=5, now=NOW)
        c = store.counts("u-1")
        self.assertEqual((c["good"], c["bad"], c["suggestions"]), (0, 0, 1))
        s = store.suggestions_for_owner("u-1")
        self.assertEqual(s[0]["change"], {"price_max": 150})
        self.assertEqual(s[0]["note"], "too long a band")
        self.assertNotIn("user", json.dumps(s))

    def test_ten_suggestions_a_day_per_person_per_dog(self):
        for i in range(10):
            store.record_suggestion(hound_id="u-1", root_id="u-1", change={"min_books": 2 + i % 5, "lock_minutes": 60},
                                    note=f"idea {i}", user_id=5, now=NOW)
        with self.assertRaises(store.FeedbackError) as ctx:
            store.record_suggestion(hound_id="u-1", root_id="u-1", change={"min_books": 9}, note="one more",
                                    user_id=5, now=NOW)
        self.assertEqual(ctx.exception.status, 429)

    def test_the_tables_are_additive_and_leave_the_existing_ones_alone(self):
        users_store.create_user("a@example.com", status="active", db=self.db)
        with store.connect() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"users", "hound_looks", "hound_feedback"} <= tables)


class TheLocker(Db):
    def test_a_good_look_is_stored_per_lineage_and_read_back(self):
        clean = look.validate_look({"coat": "golden", "eyes": "blue", "bg": "forest", "head": "cap", "face": "sunglasses",
                                    "neck": "chain", "body": "jersey", "number": 23})
        store.set_look("u-root", clean, user_id=1, now=NOW)
        self.assertEqual(store.get_look("u-root"), clean)
        self.assertEqual(store.get_looks(["u-root", "u-none"]), {"u-root": clean})
        again = look.validate_look({"coat": "black"})
        store.set_look("u-root", again, user_id=1, now=NOW)                 # a second save replaces, not duplicates
        self.assertEqual(store.get_look("u-root")["coat"], "black")
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM hound_looks").fetchone()[0], 1)

    def test_missing_fields_take_the_default_look(self):
        out = look.validate_look({})
        self.assertEqual(out, dict(look.DEFAULT_LOOK))
        self.assertEqual(look.validate_look({"coat": "red"})["eyes"], "brown")

    def test_every_choice_in_the_menu_is_accepted(self):
        for key, allowed in look.CHOICES.items():
            for value in allowed:
                self.assertEqual(look.validate_look({key: value})[key], value)

    def test_anything_off_the_whitelist_is_refused_all_at_once(self):
        with self.assertRaises(look.LookError) as ctx:
            look.validate_look({"coat": "#ff0000", "eyes": "<script>", "bg": "url(javascript:1)", "head": "crown",
                                "face": 3, "neck": None, "body": ["hoodie"], "mystery": "x"})
        self.assertEqual(set(ctx.exception.errors), {"coat", "eyes", "bg", "head", "face", "neck", "body", "mystery"})

    def test_the_jersey_number_is_a_small_whole_number_and_only_on_a_jersey(self):
        self.assertEqual(look.validate_look({"body": "jersey", "number": 0})["number"], 0)
        self.assertEqual(look.validate_look({"body": "jersey", "number": 99})["number"], 99)
        self.assertIsNone(look.validate_look({"body": "hoodie"})["number"])
        for bad in (100, -1, 7.5, "7", True, [7]):
            with self.assertRaises(look.LookError) as ctx:
                look.validate_look({"body": "jersey", "number": bad})
            self.assertIn("number", ctx.exception.errors, repr(bad))
        with self.assertRaises(look.LookError) as ctx:
            look.validate_look({"body": "hoodie", "number": 7})
        self.assertIn("jersey", ctx.exception.errors["number"])

    def test_a_look_is_an_object(self):
        for bad in (None, "tan", ["coat"], 5):
            with self.assertRaises(look.LookError):
                look.validate_look(bad)

    def test_the_stored_look_is_only_whitelist_keys(self):
        out = look.validate_look({"coat": "tan", "v": 99})
        self.assertEqual(set(out), set(look.FIELDS) | {"v"})
        self.assertEqual(out["v"], look.LOOK_VERSION)


if __name__ == "__main__":
    unittest.main()
