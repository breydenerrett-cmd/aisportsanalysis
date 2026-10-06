"""Five defects a review found in the support re-issue (2026-10-05), each pinned.

THE STORY. POST /admin/users/reissue replaces a buyer's lost token. The review
found that the replacement did not close every door the old credential had been
handed out through, and that the audit trail around it could lie:

  1. GET /signup/complete?session_id=... kept returning the raw ACTIVATION token
     after a re-issue (the raw value stays in signup_activation_tokens for 72 h
     unread and 10 min after the first read, and the route never asked whether it
     still authenticates). The page then stored that dead token over the buyer's
     good one. Fixed on both sides: the store wipes the raw token in the same
     transaction as any revoke, the route refuses one that no longer
     authenticates, and the page asks the server about an exchanged token before
     it stores it (the page half is in tests/test_return_recovery.py, the part
     that runs under node).
  3. user_id=2**70 was a 500 (sqlite OverflowError); every id that is not a real
     account is the one 409.
  4. The audit row and the revoke/issue were two transactions: a failed token
     change left a "reissued" row for a re-issue that never happened.
  5. `reason` is free text that lands in a log: a token must not get in.

(Defect 2, the procedure treating a typed email as proof, is a document and a
page wording: tests/test_return_recovery.py TheDocumentsSayWhatWasDecided and
SupportPageTellsALockedOutBuyerWhatToSend.)
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import unittest
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

if HAS_FASTAPI:
    from fastapi import HTTPException
    from tests.test_billing_acceptance_path import SESSION, _Case
    from tests.test_tester_journey_e2e import _Journey
    from src.appstate import customers, events, users as users_store
else:  # Linux CI has no FastAPI: the classes below are skipped, but must still load
    SESSION = None
    _Case = _Journey = unittest.TestCase

REASON = "lost the token; verified by reply from the account mailbox, ticket 41"


def _activation_row(db, user_id):
    with contextlib.closing(sqlite3.connect(str(db))) as conn:
        return conn.execute("SELECT raw_token, retrieved_at FROM signup_activation_tokens "
                            "WHERE user_id = ?", (user_id,)).fetchone()


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheActivationBridgeStopsHandingOutARevokedToken(_Case):
    """Defect 1, the server half."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"APP_DB_PATH": str(self.db)})
        env.start()
        self.addCleanup(env.stop)
        patcher = mock.patch.object(events, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def webhook_only_buyer(self, email="webhook-only@example.com"):
        user_id = self.signup(email)["user_id"]
        self.webhook(self.completed_event(user_id))
        self.webhook(self.subscription_event("created", "trialing"))
        return user_id

    def reissue(self, user_id):
        from api.admin import ReissueAccessRequest, reissue_access_token
        return reissue_access_token(ReissueAccessRequest(user_id=user_id, reason=REASON),
                                    _admin=None)

    def assert_refused_like_a_session_that_never_happened(self):
        with self.assertRaises(HTTPException) as refused:
            self.collect_token()
        self.assertEqual(refused.exception.status_code, 404)
        with self.assertRaises(HTTPException) as never:
            self.collect_token("cs_never_happened")
        self.assertEqual(refused.exception.detail, never.exception.detail)

    def test_an_unread_activation_token_is_not_handed_out_after_a_reissue(self):
        user_id = self.webhook_only_buyer()
        self.reissue(user_id)
        self.assert_refused_like_a_session_that_never_happened()
        raw, _retrieved = _activation_row(self.db, user_id)
        self.assertIsNone(raw, "the replaced credential is still stored in the clear")

    def test_a_token_read_once_is_not_handed_out_again_in_the_window_after_a_reissue(self):
        user_id = self.webhook_only_buyer()
        first = self.collect_token()["token"]
        self.assertIsNotNone(users_store.authenticate(first))
        fresh = self.reissue(user_id)
        self.assert_refused_like_a_session_that_never_happened()
        self.assertIsNone(users_store.authenticate(first))
        self.assertEqual(self.open_paid_page(fresh["token"]).id, user_id)

    def test_every_way_of_revoking_wipes_the_activation_token_too(self):
        for name in ("revoke_all_tokens", "revoke_token"):
            with self.subTest(revoke=name):
                user = users_store.create_user(f"{name}@example.com", status="active", plan="beta")
                raw = users_store.issue_invite_token(user.id)
                customers.record_activation_token(f"cs_wipe_{name}", user.id, raw)
                if name == "revoke_all_tokens":
                    users_store.revoke_all_tokens(user.id)
                else:
                    users_store.revoke_token(raw)
                self.assertIsNone(customers.take_activation_token(
                    f"cs_wipe_{name}", reread_window=customers.ACTIVATION_REREAD_WINDOW))
                self.assertIsNone(_activation_row(self.db, user.id)[0])

    def test_the_read_path_itself_refuses_a_token_that_no_longer_authenticates(self):
        # belt and braces: whatever left the raw value behind (a path that revokes
        # in SQL, a future one), the route asks authenticate() before it answers.
        user_id = self.webhook_only_buyer()
        raw, _ = _activation_row(self.db, user_id)
        with contextlib.closing(sqlite3.connect(str(self.db))) as conn, conn:
            conn.execute("UPDATE tokens SET revoked_at = '2026-01-01T00:00:00+00:00'")
        self.assertEqual(_activation_row(self.db, user_id)[0], raw)
        self.assert_refused_like_a_session_that_never_happened()

    def test_a_buyer_nobody_touched_still_collects_the_token(self):
        user_id = self.webhook_only_buyer()
        result = self.collect_token()
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(users_store.authenticate(result["token"]).id, user_id)
        self.assertEqual(self.collect_token()["token"], result["token"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _ReissueJourney(_Journey):
    def reissue(self, **body):
        body.setdefault("reason", REASON)
        return self.call("POST", "/admin/users/reissue", admin=True, body=body)

    def reissued_rows(self):
        return [e for e in events.list_events() if e.kind == events.SUPPORT_TOKEN_REISSUED]


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AnIdThatIsNotAnAccountIsTheSameRefusal(_ReissueJourney):
    """Defect 3."""

    def test_out_of_range_and_non_integer_ids_are_the_unknown_account_409(self):
        grant = self.grant("a@example.test")
        reference = self.reissue(user_id=grant["user_id"] + 1000)
        self.assertEqual(reference[0], 409)
        for bad in (2 ** 70, 2 ** 63, 2 ** 64, -2 ** 70, -1, 0, "abc", "1", 1.5, True, False,
                    [1], {"id": 1}):
            with self.subTest(user_id=bad):
                self.assertEqual(self.reissue(user_id=bad), reference)
        # and nothing was touched
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)
        self.assertEqual(self.reissued_rows(), [])

    def test_a_real_integer_id_still_works(self):
        grant = self.grant("a@example.test")
        status, body = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 200, body)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheAuditRowAndTheTokenChangeAreOneThing(_ReissueJourney):
    """Defect 4."""

    def actions(self):
        return [e.properties["action"] for e in self.reissued_rows()]

    def token_count(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]

    def test_a_failed_token_change_leaves_no_reissued_row_but_is_on_record(self):
        grant = self.grant("a@example.test")
        with mock.patch.object(users_store, "insert_token", side_effect=sqlite3.OperationalError("disk full")):
            status, answer = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 503, answer)
        # no "reissued" row survives, and the old token was neither revoked nor replaced
        self.assertNotIn("reissue", self.actions())
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)
        self.assertEqual(self.token_count(), 1)
        # the attempt that failed is still auditable, with the reason and no secret
        self.assertEqual(self.actions(), ["reissue_failed"])
        row = self.reissued_rows()[0]
        self.assertEqual(row.user_hash, events.hash_user_id(grant["user_id"]))
        self.assertEqual(row.properties["reason"], REASON)
        self.assertNotIn(grant["token"], str(row))

    def test_a_failed_audit_write_changes_nothing_and_says_so(self):
        grant = self.grant("a@example.test")
        with mock.patch("api.admin._write_reissue_audit", side_effect=sqlite3.OperationalError("disk full")):
            status, answer = self.reissue(user_id=grant["user_id"])
        self.assertEqual((status, answer["detail"]["error"]), (503, "audit_log_unavailable"))
        self.assertNotIn("reissue", self.actions())
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)
        self.assertEqual(self.token_count(), 1)

    def test_a_good_reissue_is_one_row_written_with_the_change(self):
        grant = self.grant("a@example.test")
        status, fresh = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 200, fresh)
        self.assertEqual(self.actions(), ["reissue"])
        self.assertEqual(self.reissued_rows()[0].properties["revoked_tokens"], 1)
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=fresh["token"])[0], 200)

    def test_the_audit_row_commits_with_the_tokens_not_before(self):
        # the row exists only if the new token does: fail between them and neither stays
        grant = self.grant("a@example.test")
        real_insert = users_store.insert_token
        seen = {}

        def insert_then_fail(conn, *args, **kwargs):
            seen["rows_before_insert"] = conn.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE kind = ?",
                (events.SUPPORT_TOKEN_REISSUED,)).fetchone()[0]
            real_insert(conn, *args, **kwargs)
            raise sqlite3.OperationalError("crash after the insert")

        with mock.patch.object(users_store, "insert_token", insert_then_fail):
            status, _ = self.reissue(user_id=grant["user_id"])
        self.assertEqual(status, 503)
        self.assertEqual(self.token_count(), 1)
        self.assertEqual(self.actions(), ["reissue_failed"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheReasonNeverCarriesAToken(_ReissueJourney):
    """Defect 5 (the reason half)."""

    def test_a_token_anywhere_in_the_reason_is_refused_and_nothing_is_logged(self):
        grant = self.grant("a@example.test")
        import secrets
        pasted = secrets.token_urlsafe(32)
        for reason in (pasted, f"lost it, it was {pasted}, ticket 41",
                       f"verified. Authorization: Bearer {pasted}",
                       "Bearer short-but-real", "old token=abc123XYZ",
                       "see https://x.test/#/signup/complete?session_id=cs_live_a1b2c3d4e5f6"):
            with self.subTest(reason=reason[:30]):
                status, answer = self.reissue(user_id=grant["user_id"], reason=reason)
                self.assertEqual((status, answer["detail"]["error"]), (400, "reason_looks_like_a_secret"))
        self.assertEqual(self.reissued_rows(), [])
        self.assertEqual(self.call("GET", f"/games/{self.date}", token=grant["token"])[0], 200)

    def test_an_ordinary_note_is_accepted(self):
        grant = self.grant("a@example.test")
        status, body = self.reissue(user_id=grant["user_id"], reason="reply from the mailbox 2026-10-05, ticket 41")
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
