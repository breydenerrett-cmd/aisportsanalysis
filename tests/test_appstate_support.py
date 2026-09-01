"""src/appstate/support.py: support_messages store -- stdlib sqlite only,
no FastAPI involved (tests/test_api_boundary.py's stdlib-only rule)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.appstate import support


class CreateMessageTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_authed_user_message(self):
        msg = support.create_message(user_id=7, subject="Help", body="It broke",
                                     db=self.db)
        self.assertEqual(msg.user_id, 7)
        self.assertIsNone(msg.email)
        self.assertEqual(msg.status, "open")
        self.assertIsNone(msg.answered_at)
        self.assertIsNotNone(msg.id)

    def test_anonymous_email_message(self):
        msg = support.create_message(email="Person@Example.com", subject="Hi",
                                     body="pre-invite question", db=self.db)
        self.assertIsNone(msg.user_id)
        # stored lowercased -- same normalization users.create_user applies
        # to emails, so support and users never disagree on casing.
        self.assertEqual(msg.email, "person@example.com")

    def test_neither_user_id_nor_email_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(subject="x", body="y", db=self.db)

    def test_both_user_id_and_email_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(user_id=1, email="a@b.com", subject="x",
                                   body="y", db=self.db)

    def test_empty_subject_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(user_id=1, subject="   ", body="y", db=self.db)

    def test_empty_body_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(user_id=1, subject="x", body="   ", db=self.db)

    def test_oversized_subject_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(
                user_id=1, subject="x" * (support.MAX_SUBJECT_LENGTH + 1),
                body="y", db=self.db)

    def test_oversized_body_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(
                user_id=1, subject="x", body="y" * (support.MAX_BODY_LENGTH + 1),
                db=self.db)

    def test_unusable_email_rejected(self):
        with self.assertRaises(ValueError):
            support.create_message(email="not-an-email", subject="x", body="y",
                                   db=self.db)

    def test_open_message_cap_per_user(self):
        for i in range(support.MAX_OPEN_MESSAGES_PER_USER):
            support.create_message(user_id=42, subject=f"s{i}", body="b", db=self.db)
        with self.assertRaises(support.TooManyOpenMessagesError):
            support.create_message(user_id=42, subject="one too many", body="b",
                                   db=self.db)

    def test_closing_a_message_frees_the_cap(self):
        ids = []
        for i in range(support.MAX_OPEN_MESSAGES_PER_USER):
            msg = support.create_message(user_id=9, subject=f"s{i}", body="b",
                                         db=self.db)
            ids.append(msg.id)
        support.update_status(ids[0], "closed", db=self.db)
        # one slot freed by closing -- the cap counts open messages only,
        # never lifetime messages (see module docstring).
        support.create_message(user_id=9, subject="fits now", body="b", db=self.db)

    def test_anonymous_senders_are_never_capped(self):
        # No stable identity to key the cap on for an anonymous sender --
        # see create_message's own docstring for why this is a documented
        # trade-off, not an oversight.
        for i in range(support.MAX_OPEN_MESSAGES_PER_USER + 5):
            support.create_message(email="same@example.com", subject=f"s{i}",
                                   body="b", db=self.db)
        messages = support.list_messages(db=self.db)
        self.assertEqual(len(messages), support.MAX_OPEN_MESSAGES_PER_USER + 5)


class ListMessagesTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_newest_first(self):
        first = support.create_message(user_id=1, subject="first", body="b",
                                       db=self.db)
        second = support.create_message(user_id=1, subject="second", body="b",
                                        db=self.db)
        messages = support.list_messages(db=self.db)
        self.assertEqual([m.id for m in messages], [second.id, first.id])

    def test_filter_by_status(self):
        open_msg = support.create_message(user_id=1, subject="a", body="b",
                                          db=self.db)
        answered_msg = support.create_message(user_id=1, subject="c", body="d",
                                              db=self.db)
        support.update_status(answered_msg.id, "answered", db=self.db)
        open_only = support.list_messages(status="open", db=self.db)
        self.assertEqual([m.id for m in open_only], [open_msg.id])

    def test_filter_by_user_id(self):
        support.create_message(user_id=1, subject="a", body="b", db=self.db)
        theirs = support.create_message(user_id=2, subject="c", body="d",
                                        db=self.db)
        mine = support.list_messages(user_id=2, db=self.db)
        self.assertEqual([m.id for m in mine], [theirs.id])

    def test_unknown_status_filter_raises(self):
        with self.assertRaises(ValueError):
            support.list_messages(status="bogus", db=self.db)


class UpdateStatusTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self.msg = support.create_message(user_id=1, subject="x", body="y",
                                          db=self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_answering_sets_answered_at_once(self):
        updated = support.update_status(self.msg.id, "answered", db=self.db)
        self.assertEqual(updated.status, "answered")
        self.assertIsNotNone(updated.answered_at)
        first_answered_at = updated.answered_at

        # closing then answering again must not move the timestamp -- see
        # update_status's own docstring for why answered_at is write-once.
        support.update_status(self.msg.id, "closed", db=self.db)
        reanswered = support.update_status(self.msg.id, "answered", db=self.db)
        self.assertEqual(reanswered.answered_at, first_answered_at)

    def test_closing_without_answering_leaves_answered_at_null(self):
        updated = support.update_status(self.msg.id, "closed", db=self.db)
        self.assertEqual(updated.status, "closed")
        self.assertIsNone(updated.answered_at)

    def test_unknown_id_returns_none(self):
        self.assertIsNone(support.update_status(999999, "closed", db=self.db))

    def test_unknown_status_raises(self):
        with self.assertRaises(ValueError):
            support.update_status(self.msg.id, "bogus", db=self.db)


if __name__ == "__main__":
    unittest.main()
