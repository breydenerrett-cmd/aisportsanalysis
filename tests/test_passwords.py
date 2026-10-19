"""src/appstate/passwords.py and src/appstate/access.py: the storage, hashing,
rules, rate limits and access-end rule behind email + password login.

Stdlib-only on purpose (no FastAPI import anywhere here), so this module runs
under the Linux CI's no-FastAPI harness too. The HTTP shape is
tests/test_api_passwords.py.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import access
from src.appstate import billing
from src.appstate import customers
from src.appstate import passwords
from src.appstate import testers
from src.appstate import users as users_store

GOOD = "correct horse battery"


class _Db(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def user(self, email="member@example.com", status="invited"):
        return users_store.create_user(email, status=status, plan="none")


class HashingTests(_Db):

    def test_the_parameters_are_the_ones_the_owner_asked_for(self):
        self.assertEqual((passwords.SCRYPT_N, passwords.SCRYPT_R, passwords.SCRYPT_P),
                         (2 ** 14, 8, 1))
        self.assertEqual(passwords.SALT_BYTES, 16)
        record = passwords.hash_password(GOOD)
        self.assertEqual(record.params, "scrypt:n=16384,r=8,p=1,dklen=32")
        self.assertEqual(len(bytes.fromhex(record.salt)), 16)
        self.assertEqual(len(bytes.fromhex(record.hash)), 32)

    def test_the_stored_digest_really_is_scrypt_of_the_password_and_salt(self):
        record = passwords.hash_password(GOOD)
        expected = hashlib.scrypt(GOOD.encode(), salt=bytes.fromhex(record.salt),
                                  n=2 ** 14, r=8, p=1, dklen=32)
        self.assertEqual(record.hash, expected.hex())

    def test_the_same_password_never_hashes_the_same_way_twice(self):
        a, b = passwords.hash_password(GOOD), passwords.hash_password(GOOD)
        self.assertNotEqual(a.salt, b.salt)
        self.assertNotEqual(a.hash, b.hash)
        self.assertTrue(passwords.verify_password(GOOD, a))
        self.assertTrue(passwords.verify_password(GOOD, b))

    def test_two_members_with_one_password_get_different_rows(self):
        one, two = self.user("a@example.com"), self.user("b@example.com")
        passwords.set_password(one.id, GOOD)
        passwords.set_password(two.id, GOOD)
        with passwords._connect() as conn:
            rows = conn.execute("SELECT hash, salt FROM user_passwords").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["salt"], rows[1]["salt"])
        self.assertNotEqual(rows[0]["hash"], rows[1]["hash"])

    def test_verification_uses_hmac_compare_digest(self):
        record = passwords.hash_password(GOOD)
        with mock.patch.object(passwords.hmac, "compare_digest",
                               wraps=hmac.compare_digest) as spy:
            self.assertTrue(passwords.verify_password(GOOD, record))
            self.assertFalse(passwords.verify_password("not it at all", record))
        self.assertEqual(spy.call_count, 2)
        source = inspect.getsource(passwords.verify_password)
        self.assertIn("compare_digest", source)
        self.assertNotIn("== expected", source)
        self.assertNotIn("expected ==", source)

    def test_a_row_stored_with_other_parameters_still_verifies(self):
        """The cost can be raised later without locking anyone out: the row's own
        params decide how it is checked."""
        salt = b"\x01" * 16
        digest = hashlib.scrypt(GOOD.encode(), salt=salt, n=2 ** 12, r=8, p=1, dklen=32)
        record = passwords.PasswordRecord(hash=digest.hex(), salt=salt.hex(),
                                          params="scrypt:n=4096,r=8,p=1,dklen=32")
        self.assertTrue(passwords.verify_password(GOOD, record))
        self.assertFalse(passwords.verify_password(GOOD + "x", record))

    def test_a_corrupt_or_unknown_row_is_a_failure_not_an_exception(self):
        good = passwords.hash_password(GOOD)
        for bad in (passwords.PasswordRecord(good.hash, good.salt, "bcrypt:12"),
                    passwords.PasswordRecord("zz", good.salt, good.params),
                    passwords.PasswordRecord(good.hash, "not hex", good.params),
                    passwords.PasswordRecord(good.hash, good.salt,
                                             "scrypt:n=99999999999,r=8,p=1,dklen=32")):
            self.assertFalse(passwords.verify_password(GOOD, bad))

    def test_visually_identical_unicode_is_one_password(self):
        composed, decomposed = "café au lait 2026", "café au lait 2026"
        record = passwords.hash_password(composed)
        self.assertTrue(passwords.verify_password(decomposed, record))

    def test_no_plaintext_password_reaches_the_database_files(self):
        user = self.user()
        secret = "zebra-quartz-lantern-8841"
        passwords.set_password(user.id, secret)
        passwords.authenticate_password(user.email, secret)
        blob = b"".join(p.read_bytes() for p in Path(self._tmp.name).iterdir() if p.is_file())
        self.assertNotIn(secret.encode(), blob)
        self.assertNotIn(secret.encode("utf-16-le"), blob)

    def test_set_replaces_and_reports_whether_it_did(self):
        user = self.user()
        self.assertFalse(passwords.has_password(user.id))
        self.assertFalse(passwords.set_password(user.id, GOOD))
        self.assertTrue(passwords.has_password(user.id))
        self.assertTrue(passwords.set_password(user.id, "a different long passphrase"))
        self.assertTrue(passwords.verify_user_password(user.id, "a different long passphrase"))
        self.assertFalse(passwords.verify_user_password(user.id, GOOD))
        with passwords._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM user_passwords").fetchone()[0], 1)

    def test_clear_runs_the_audit_in_the_same_transaction_and_rolls_back_with_it(self):
        user = self.user()
        passwords.set_password(user.id, GOOD)

        def boom(conn, existed):
            raise RuntimeError("audit down")

        with self.assertRaises(RuntimeError):
            passwords.clear_password(user.id, audit=boom)
        self.assertTrue(passwords.has_password(user.id), "the delete must roll back with the audit")
        seen = []
        self.assertTrue(passwords.clear_password(user.id, audit=lambda c, e: seen.append(e)))
        self.assertEqual(seen, [True])
        self.assertFalse(passwords.has_password(user.id))
        self.assertFalse(passwords.clear_password(user.id))


class RuleTests(unittest.TestCase):

    def reject(self, password, email="member@example.com"):
        with self.assertRaises(passwords.PasswordRejected) as ctx:
            passwords.check_password_rules(password, email)
        message = str(ctx.exception)
        self.assertTrue(message.endswith("."), message)
        if isinstance(password, str) and password:
            self.assertNotIn(password, message)
        return message

    def test_ten_characters_is_the_floor(self):
        self.assertIn("at least 10", self.reject("short-one"))
        self.assertEqual(passwords.check_password_rules("exactly-10", "x@y.co"), "exactly-10")

    def test_empty_and_non_string_values_get_a_plain_sentence(self):
        for value in ("", None, 12345678901, ["a" * 12], {"p": "x" * 12}):
            self.assertEqual(self.reject(value), "Choose a password.")

    def test_it_may_not_be_the_email_or_its_local_part(self):
        email = "thelongestlocalpart@example.com"
        self.assertIn("email", self.reject(email, email))
        self.assertIn("email", self.reject(email.upper(), email))
        self.assertIn("email", self.reject("thelongestlocalpart", email))

    def test_common_passwords_are_refused_in_their_usual_disguises(self):
        for weak in ("password123", "PASSWORD123", "Password1234!", "qwertyuiop", "1234567890",
                     "linehound1", "LineHound2026", "iloveyou123", "letmein!!!!", "welcome123"):
            self.assertIn("too common", self.reject(weak), weak)

    def test_trivially_repetitive_strings_are_refused(self):
        for weak in ("aaaaaaaaaaaa", "abababababab", "            "):
            self.assertIn("too simple", self.reject(weak), repr(weak))

    def test_a_long_passphrase_is_fine_and_there_is_an_upper_bound(self):
        self.assertTrue(passwords.check_password_rules("correct horse battery staple", "a@b.co"))
        self.assertIn("200", self.reject("x1" * 101))


class AuthenticateTests(_Db):

    def test_the_right_password_returns_the_user_case_and_space_insensitively_on_email(self):
        user = self.user("Member@Example.com")
        passwords.set_password(user.id, GOOD)
        got = passwords.authenticate_password("  MEMBER@example.COM ", GOOD)
        self.assertEqual(got.id, user.id)

    def test_every_failure_is_none_and_costs_exactly_one_scrypt(self):
        real = self.user("real@example.com")
        passwords.set_password(real.id, GOOD)
        self.user("nopass@example.com")
        cases = [("real@example.com", "wrong password here"),
                 ("nobody@example.com", GOOD),
                 ("nopass@example.com", GOOD),
                 ("", GOOD), ("real@example.com", ""), (None, None),
                 ({"a": 1}, ["x"]), ("real@example.com", "x" * 5000)]
        calls = []
        original = passwords._scrypt

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        for email, password in cases:
            calls.clear()
            with mock.patch.object(passwords, "_scrypt", counting):
                self.assertIsNone(passwords.authenticate_password(email, password), (email,))
            self.assertEqual(len(calls), 1, (email, len(calls)))

    def test_a_correct_login_also_costs_one_scrypt(self):
        user = self.user()
        passwords.set_password(user.id, GOOD)
        calls = []
        original = passwords._scrypt
        with mock.patch.object(passwords, "_scrypt",
                               lambda *a, **k: (calls.append(1), original(*a, **k))[1]):
            self.assertIsNotNone(passwords.authenticate_password(user.email, GOOD))
        self.assertEqual(len(calls), 1)


class RateLimitTests(_Db):
    T0 = 1_800_000_000.0

    def attempt(self, offset, ip="10.0.0.1", email="member@example.com"):
        return passwords.check_and_record_attempt(
            [(passwords.SCOPE_IP, ip), (passwords.SCOPE_EMAIL, email)],
            now=self.T0 + offset)

    def test_ten_attempts_in_fifteen_minutes_then_blocked_with_a_retry_time(self):
        for i in range(10):
            self.assertIsNone(self.attempt(i * 10), i)
        retry = self.attempt(100)
        self.assertIsNotNone(retry)
        # The first attempt (offset 0) leaves the 15-minute window at 900 s.
        self.assertAlmostEqual(retry, 900 - 100, delta=1)

    def test_a_slot_frees_when_the_oldest_attempt_ages_out(self):
        for i in range(10):
            self.attempt(i * 10)                      # offsets 0, 10, ... 90
        self.assertIsNotNone(self.attempt(500))
        self.assertIsNone(self.attempt(901))          # offset 0 has aged out
        self.assertIsNotNone(self.attempt(905))       # but only one slot freed
        self.assertIsNone(self.attempt(911))          # offset 10 has aged out too

    def test_a_refused_attempt_is_not_recorded_so_it_cannot_extend_its_own_lockout(self):
        for i in range(10):
            self.attempt(i)
        for j in range(30):
            self.assertIsNotNone(self.attempt(100 + j))
        with passwords._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM login_attempts "
                                          "WHERE scope = 'ip'").fetchone()[0], 10)
        self.assertIsNone(self.attempt(901))

    def test_fifty_a_day_even_when_spread_out(self):
        # 10 every 20 minutes stays inside the 15-minute window each time.
        sent = 0
        for batch in range(10):
            for i in range(5):
                if self.attempt(batch * 1200 + i) is None:
                    sent += 1
        self.assertEqual(sent, 50)
        self.assertIsNotNone(self.attempt(10 * 1200 + 5))
        self.assertIsNone(self.attempt(86400 + 5))     # the day has rolled over

    def test_the_email_limit_holds_across_addresses_and_the_ip_limit_across_emails(self):
        for i in range(10):
            self.assertIsNone(self.attempt(i, ip=f"10.0.0.{i}", email="victim@example.com"))
        self.assertIsNotNone(self.attempt(11, ip="10.0.0.99", email="victim@example.com"))
        for i in range(10):
            self.assertIsNone(self.attempt(20 + i, ip="10.9.9.9", email=f"u{i}@example.com"))
        self.assertIsNotNone(self.attempt(31, ip="10.9.9.9", email="fresh@example.com"))
        self.assertIsNone(self.attempt(32, ip="10.7.7.7", email="fresh@example.com"))

    def test_an_address_with_no_account_is_limited_exactly_the_same(self):
        real = self.user("real@example.com")
        passwords.set_password(real.id, GOOD)
        for email in ("real@example.com", "ghost@example.com"):
            results = [self.attempt(i, ip=f"10.1.{hash(email) % 200}.{i}", email=email)
                       for i in range(12)]
            self.assertEqual([r is None for r in results], [True] * 10 + [False] * 2, email)

    def test_the_counts_live_in_the_database_not_the_process(self):
        """A redeploy is a new interpreter on the same file. Prove the state is
        rows: a connection this module never opened sees all ten, and the module
        keeps no counter of its own."""
        import sqlite3
        for i in range(10):
            self.attempt(i)
        raw = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(raw.execute("SELECT COUNT(*) FROM login_attempts "
                                         "WHERE scope = 'ip'").fetchone()[0], 10)
        finally:
            raw.close()
        in_memory = [n for n, v in vars(passwords).items()
                     if isinstance(v, (dict, list, set)) and not n.startswith("__")]
        self.assertEqual(in_memory, [])
        self.assertIsNotNone(self.attempt(20))

    def test_identities_are_hashed_and_old_rows_are_pruned(self):
        self.attempt(0, ip="203.0.113.7", email="private@example.com")
        with passwords._connect() as conn:
            dump = " ".join(f"{r['scope']} {r['key_hash']}"
                            for r in conn.execute("SELECT * FROM login_attempts"))
        self.assertNotIn("203.0.113.7", dump)
        self.assertNotIn("private@example.com", dump)
        self.assertIsNone(self.attempt(2 * 86400, ip="203.0.113.8", email="other@example.com"))
        with passwords._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0], 2)


class AccessEndTests(_Db):
    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def subscriber(self, email="payer@example.com"):
        user = users_store.create_user(email, status="active", plan="beta")
        customers.upsert_customer(user.id, "cus_%d" % user.id)
        customers.upsert_subscription(
            user.id, "sub_%d" % user.id, "active",
            current_period_end=(self.NOW + timedelta(days=20)).isoformat())
        return user

    def tearDown(self):
        access.unregister_access_source("comp")

    def test_a_subscriber_gets_the_usual_subscriber_lifetime(self):
        kind, ends = access.access_token_end(self.subscriber(), now=self.NOW)
        self.assertEqual(kind, "subscriber")
        self.assertEqual(ends, self.NOW + billing.SUBSCRIBER_TOKEN_TTL)

    def test_a_tester_gets_exactly_the_tester_window_end(self):
        user = self.user("tester@example.com")
        grant = testers.grant_tester(user_id=user.id, now=self.NOW)
        kind, ends = access.access_token_end(users_store.get_user(user.id), now=self.NOW)
        self.assertEqual(kind, "tester")
        self.assertEqual(ends, datetime.fromisoformat(grant.expires_at))
        self.assertEqual(ends, self.NOW + testers.TESTER_ACCESS_TTL)

    def test_an_ended_tester_window_is_returned_in_the_past(self):
        user = self.user("old@example.com")
        testers.grant_tester(user_id=user.id, now=self.NOW - timedelta(days=30))
        kind, ends = access.access_token_end(users_store.get_user(user.id), now=self.NOW)
        self.assertEqual(kind, "tester")
        self.assertLess(ends, self.NOW)

    def test_no_access_for_waitlisted_pending_suspended_invited_and_lapsed(self):
        for status in ("waitlisted", "pending_payment", "invited", "active"):
            user = self.user(f"{status}@example.com", status=status)
            self.assertIsNone(access.access_token_end(user, now=self.NOW), status)
        suspended = self.subscriber("susp@example.com")
        users_store.set_user_status(suspended.id, "suspended")
        self.assertIsNone(access.access_token_end(users_store.get_user(suspended.id), now=self.NOW))
        lapsed = users_store.create_user("lapsed@example.com", status="active", plan="beta")
        customers.upsert_customer(lapsed.id, "cus_l")
        customers.upsert_subscription(lapsed.id, "sub_l", "canceled", current_period_end=None)
        self.assertIsNone(access.access_token_end(lapsed, now=self.NOW))
        self.assertIsNone(access.access_token_end(None, now=self.NOW))

    def test_a_registered_source_plugs_in_between_the_paid_check_and_the_tester_rule(self):
        comp_end = self.NOW + timedelta(days=366)
        member = self.user("comp@example.com")
        access.register_access_source(
            "comp", lambda u, now: comp_end if u.email == "comp@example.com" else None)
        self.assertEqual(access.access_token_end(member, now=self.NOW), ("comp", comp_end))
        other = self.user("other@example.com")
        self.assertIsNone(access.access_token_end(other, now=self.NOW))
        # A suspended comp is still refused: suspension is checked first.
        users_store.set_user_status(member.id, "suspended")
        self.assertIsNone(access.access_token_end(users_store.get_user(member.id), now=self.NOW))

    def test_a_source_that_raises_never_grants_access(self):
        def broken(user, now):
            raise RuntimeError("comp table missing")
        access.register_access_source("comp", broken)
        with mock.patch("sys.stderr"):
            self.assertIsNone(access.access_token_end(self.user("x@example.com"), now=self.NOW))


if __name__ == "__main__":
    unittest.main()
