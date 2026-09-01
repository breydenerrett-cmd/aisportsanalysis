"""Adversarial regressions for the authed api/ surface, driven through ASGI.

WHY THIS FILE DRIVES THE APP INSTEAD OF CALLING ROUTE FUNCTIONS
---------------------------------------------------------------
tests/test_api_auth.py and tests/test_api_mybets.py call the route functions
directly, which is the right shape for the logic inside them. It cannot see
the bugs below, because every one of them lives in the layer those tests skip
over: FastAPI's own parameter coercion, and what happens to an exception the
route lets escape. `DELETE /my-bets/<huge>` cannot even be expressed as a
direct call -- the direct call just passes a Python int straight through.

So this file speaks ASGI to the router directly. Starlette's TestClient needs
an HTTP client package this repo does not depend on, so the ~20 lines of
`_request` below stand in for it: build a scope, drive the app, collect the
response. No server, no socket, no new dependency.

The app under test is assembled here from api.auth's and api.mybets' routers
rather than imported from api.app, so these regressions stay about auth and
My Bets and do not go red when something unrelated is mounted next to them.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import FastAPI
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import savedbets as savedbets_store
from src.appstate import users as users_store


def _request(app, method, path, headers=None, body=None):
    """One request through the ASGI app; returns (status, decoded body)."""
    path, _, query = path.partition("?")
    raw_headers = [(k.lower().encode("utf-8"), v.encode("utf-8"))
                   for k, v in (headers or {}).items()]
    payload = b""
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        raw_headers.append((b"content-type", b"application/json"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "path": path, "raw_path": path.encode("utf-8"),
             "root_path": "", "scheme": "http",
             "query_string": query.encode("utf-8"), "headers": raw_headers,
             "client": ("127.0.0.1", 5000), "server": ("testserver", 80)}
    captured, chunks = {}, []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    asyncio.run(app(scope, receive, send))
    raw = b"".join(chunks)
    try:
        return captured.get("status"), json.loads(raw)
    except ValueError:
        return captured.get("status"), raw.decode("utf-8", "replace")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AuthedSurfaceTests(unittest.TestCase):

    def setUp(self):
        import api.mybets as mybets_mod
        from api.auth import router as auth_router
        self._mybets_mod = mybets_mod
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        # Both stores resolve their path lazily, and neither route passes a
        # db= override, so redirecting db_path is what points the whole
        # request path at a throwaway database.
        self._patchers = [
            mock.patch.object(users_store, "db_path", lambda: self.db),
            mock.patch.object(savedbets_store, "db_path", lambda: self.db),
        ]
        for patcher in self._patchers:
            patcher.start()
        self._admin_before = os.environ.get("APP_ADMIN_TOKEN")
        os.environ["APP_ADMIN_TOKEN"] = "admin-secret"
        # The rate limiter is module-level (one process, one counter) and
        # the route's Depends(...) captured this exact object at import
        # time, so a fresh instance would never actually be wired to the
        # route below. Clearing its internal window dict is what actually
        # isolates one test's request count from the next.
        mybets_mod._mybets_limiter._windows.clear()
        self.app = FastAPI()
        self.app.include_router(auth_router)
        self.app.include_router(mybets_mod.router)

    def tearDown(self):
        if self._admin_before is None:
            os.environ.pop("APP_ADMIN_TOKEN", None)
        else:
            os.environ["APP_ADMIN_TOKEN"] = self._admin_before
        for patcher in self._patchers:
            patcher.stop()
        self._mybets_mod._mybets_limiter._windows.clear()
        self._tmp.cleanup()

    # -- helpers ----------------------------------------------------------

    def _invite(self, email):
        status, body = _request(
            self.app, "POST", f"/admin/invites?email={email}",
            headers={"X-Admin-Token": "admin-secret"})
        self.assertEqual(status, 200, body)
        return body["user_id"], body["token"]

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    # -- DELETE /my-bets/{bet_id} -----------------------------------------

    def test_an_out_of_range_bet_id_is_rejected_not_a_500(self):
        """A bet id larger than a 64-bit signed int reached sqlite3's binder
        and raised OverflowError out of the route -- a 500 (and a traceback
        in the server log) for a request whose only honest answer is "no such
        bet". It is client input, so it is refused as client input."""
        _, token = self._invite("overflow@example.com")
        status, _ = _request(self.app, "DELETE", "/my-bets/99999999999999999999",
                             headers=self._auth(token))
        self.assertEqual(status, 422)

    def test_a_plausible_unknown_bet_id_is_still_a_plain_404(self):
        """The bound above must not swallow the ordinary not-found case."""
        _, token = self._invite("notfound@example.com")
        status, body = _request(self.app, "DELETE", "/my-bets/4242",
                                headers=self._auth(token))
        self.assertEqual(status, 404)
        self.assertEqual(body["detail"], "bet not found")

    def test_an_out_of_range_bet_id_is_refused_before_it_is_authenticated(self):
        """And it stays refused with no credentials at all -- the bound is a
        parameter constraint, not something an anonymous caller can reach
        past to hit the store."""
        status, _ = _request(self.app, "DELETE", "/my-bets/99999999999999999999")
        self.assertIn(status, (401, 422))

    # -- POST /admin/invites ----------------------------------------------

    def test_inviting_an_email_that_appeared_mid_request_is_not_a_500(self):
        """Reproduces the two-worker race: another process inserts the same
        email between this request's SELECT and its INSERT. With one uvicorn
        worker it never happens; with two it does, and the endpoint that
        onboards every beta user answered 500. The row the other worker wrote
        is the row this request wanted, so it is re-read, not fatal.

        The interleaving is forced here by creating the user from inside
        create_user itself -- the same state the losing worker finds.
        """
        real_create_user = users_store.create_user

        def create_user_after_someone_else_did(email, **kwargs):
            real_create_user(email, **kwargs)          # the winning worker
            return real_create_user(email, **kwargs)   # this worker, losing

        with mock.patch.object(users_store, "create_user",
                               create_user_after_someone_else_did):
            status, body = _request(
                self.app, "POST", "/admin/invites?email=race@example.com",
                headers={"X-Admin-Token": "admin-secret"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["email"], "race@example.com")
        # And the token it handed back is a real, working credential, not a
        # consolation prize from the error path.
        listed_status, _ = _request(self.app, "GET", "/my-bets",
                                    headers=self._auth(body["token"]))
        self.assertEqual(listed_status, 200)

    def test_an_empty_email_is_a_400_not_a_500(self):
        """`create_user` refuses an empty email with ValueError. Letting that
        escape made an unusable input look like a server fault."""
        status, body = _request(self.app, "POST", "/admin/invites?email=",
                                headers={"X-Admin-Token": "admin-secret"})
        self.assertEqual(status, 400, body)

    def test_admin_token_comparison_survives_a_non_ascii_header(self):
        """The guard compares in constant time (secrets.compare_digest), which
        refuses non-ASCII str outright -- so a header with a high byte in it
        must still come back 401, never a TypeError 500."""
        status, _ = _request(self.app, "POST", "/admin/invites?email=x@e.com",
                             headers={"X-Admin-Token": "admin-secrét"})
        self.assertEqual(status, 401)

    def test_the_right_admin_token_still_works_and_the_wrong_one_does_not(self):
        status, _ = _request(self.app, "POST", "/admin/invites?email=ok@e.com",
                             headers={"X-Admin-Token": "admin-secret"})
        self.assertEqual(status, 200)
        for wrong in ("", "admin-secre", "admin-secret ", "ADMIN-SECRET",
                      "admin-secretx"):
            with self.subTest(wrong=wrong):
                status, _ = _request(
                    self.app, "POST", "/admin/invites?email=no@e.com",
                    headers={"X-Admin-Token": wrong})
                self.assertEqual(status, 401)

    # -- POST /my-bets input bounds -----------------------------------------

    def test_an_oversized_game_field_is_a_422_through_the_wire(self):
        _, token = self._invite("bounds1@example.com")
        status, _ = _request(
            self.app, "POST", "/my-bets",
            headers=self._auth(token), body={"game": "X" * 200, "side": "home"})
        self.assertEqual(status, 422)

    def test_a_non_finite_price_is_a_422_never_a_silent_null(self):
        """The bug this bound exists for: a NaN/Infinity price used to
        reach sqlite and come back out as a silent NULL on the next read.
        json.dumps in `_request` cannot even encode float('nan') as valid
        JSON per the spec, but Python's json module emits the literal
        token `NaN` by default (allow_nan=True) -- exactly the loophole a
        client sends raw bytes through, so the body is built by hand here
        rather than through _request's json.dumps(body)."""
        _, token = self._invite("bounds2@example.com")
        for raw in (b'{"game": "BOS@NYY", "side": "home", "price": NaN}',
                   b'{"game": "BOS@NYY", "side": "home", "price": Infinity}'):
            with self.subTest(raw=raw):
                headers = {**self._auth(token), "content-type": "application/json"}
                raw_headers = [(k.lower().encode(), v.encode())
                              for k, v in headers.items()]
                scope = {"type": "http", "asgi": {"version": "3.0"},
                        "http_version": "1.1", "method": "POST",
                        "path": "/my-bets", "raw_path": b"/my-bets",
                        "root_path": "", "scheme": "http", "query_string": b"",
                        "headers": raw_headers, "client": ("127.0.0.1", 5000),
                        "server": ("testserver", 80)}
                captured, chunks = {}, []

                async def receive():
                    return {"type": "http.request", "body": raw, "more_body": False}

                async def send(message):
                    if message["type"] == "http.response.start":
                        captured["status"] = message["status"]
                    elif message["type"] == "http.response.body":
                        chunks.append(message.get("body", b""))

                asyncio.run(self.app(scope, receive, send))
                self.assertEqual(captured.get("status"), 422)

    def test_a_price_outside_the_plausible_magnitude_is_a_422(self):
        _, token = self._invite("bounds3@example.com")
        status, _ = _request(
            self.app, "POST", "/my-bets",
            headers=self._auth(token),
            body={"game": "BOS@NYY", "side": "home", "price": 7})
        self.assertEqual(status, 422)

    # -- POST /my-bets rate limiting -----------------------------------------

    def test_a_burst_past_the_per_minute_limit_gets_429(self):
        """src/appstate/ratelimit.py, wired to POST /my-bets at 60/min --
        the request count here comes from api.mybets.MYBETS_RATE_LIMIT_PER_MIN
        itself so this test tracks the real configured limit rather than a
        hard-coded copy of it."""
        _, token = self._invite("ratelimited@example.com")
        limit = self._mybets_mod.MYBETS_RATE_LIMIT_PER_MIN
        statuses = []
        for i in range(limit + 1):
            status, _ = _request(
                self.app, "POST", "/my-bets", headers=self._auth(token),
                body={"game": "BOS@NYY", "side": "home"})
            statuses.append(status)
        self.assertEqual(statuses[:limit], [200] * limit)
        self.assertEqual(statuses[limit], 429)

    def test_two_different_users_do_not_share_a_counter(self):
        limit = self._mybets_mod.MYBETS_RATE_LIMIT_PER_MIN
        _, token_a = self._invite("usera@example.com")
        for _ in range(limit):
            status, _ = _request(
                self.app, "POST", "/my-bets", headers=self._auth(token_a),
                body={"game": "BOS@NYY", "side": "home"})
            self.assertEqual(status, 200)
        status, _ = _request(
            self.app, "POST", "/my-bets", headers=self._auth(token_a),
            body={"game": "BOS@NYY", "side": "home"})
        self.assertEqual(status, 429)

        _, token_b = self._invite("userb@example.com")
        status, _ = _request(
            self.app, "POST", "/my-bets", headers=self._auth(token_b),
            body={"game": "BOS@NYY", "side": "home"})
        self.assertEqual(status, 200)

    # -- revocation and expiry, through the wire this time -----------------

    def test_a_revoked_token_stops_working_on_every_authed_route(self):
        """tests/test_api_auth.py proves the dependency rejects it; this
        proves no My Bets route reaches its body regardless of method."""
        _, token = self._invite("revoked@example.com")
        self.assertEqual(_request(self.app, "GET", "/my-bets",
                                  headers=self._auth(token))[0], 200)
        users_store.revoke_token(token, db=self.db)
        for method, path, body in [("GET", "/my-bets", None),
                                   ("POST", "/my-bets",
                                    {"game": "BOS@NYY", "side": "away"}),
                                   ("DELETE", "/my-bets/1", None)]:
            with self.subTest(method=method):
                status, _ = _request(self.app, method, path,
                                     headers=self._auth(token), body=body)
                self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
