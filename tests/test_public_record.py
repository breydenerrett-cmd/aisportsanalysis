"""The graded record is PUBLIC; tonight's picks are not.

The landing page promises "one public page you can open yourself". Behind the
paid gate a stranger who followed that promise met "SIGN IN REQUIRED". The
record routes (GET /card/record, GET /card/history) are now open, which makes
one thing load-bearing: they may only ever expose SETTLED days. history() and
history_v2() return published-but-unsettled days too (`pending_days` is
tonight's card with its books and prices, and a partially settled day lists the
bets whose games have not been played), so every test below is about what
must NOT come out of an unauthenticated request.

Isolation: every ledger here is a temp file; nothing touches
evidence/cards_*.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

from src.appstate import card_ledger
from tests.test_card_record_page import _card, _pick

try:
    from api.app import app
    from api import card as card_api
    _HAVE_FASTAPI = True
except Exception:  # noqa: BLE001
    _HAVE_FASTAPI = False

TONIGHT_BET = "Take team 7 at -111"       # a pick that must never be public
SETTLED_DATE = "2026-09-07"
PARTIAL_DATE = "2026-09-08"
TONIGHT_DATE = "2026-09-09"


def _asgi_get(path: str, headers=None):
    """(status, parsed json body) for a real GET through the whole app."""
    path, _, query = path.partition("?")
    captured = {"body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "root_path": "",
        "headers": [(b"host", b"test")] + list(headers or []),
        "client": ("test", 1), "server": ("test", 80),
    }
    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    try:
        body = json.loads(captured["body"])
    except ValueError:
        body = None
    return captured.get("status"), body


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class PublicHistoryShowsSettledDaysOnly(unittest.TestCase):
    """One ledger, three dates: a fully settled day, a partially settled day
    (one pick still UNRESOLVED), and a card published tonight and never
    settled."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

        card_ledger.publish(_card(SETTLED_DATE, [
            _pick(1, 101, price=-150), _pick(2, 102, price=-120)]), path=self.path)
        card_ledger.settle(SETTLED_DATE, {
            101: {"away_score": "2", "home_score": "5"},
            102: {"away_score": "6", "home_score": "1"},
        }, path=self.path)

        card_ledger.publish(_card(PARTIAL_DATE, [
            _pick(1, 201), _pick(2, 202, price=-111),
        ]), path=self.path)
        # 202 has no result yet: the settled row exists, with one pick
        # UNRESOLVED -- the bet text for 202 is a pick still to be played.
        card_ledger.settle(PARTIAL_DATE, {
            201: {"away_score": "2", "home_score": "5"},
        }, path=self.path)

        tonight = _pick(7, 701, price=-111)
        card_ledger.publish(_card(TONIGHT_DATE, [tonight]), path=self.path)

        patches = [
            mock.patch.object(card_ledger, "store_path", lambda sport=None: self.path),
            mock.patch.object(card_ledger, "CARD_STORE", self.path),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_raw_ledger_really_does_hold_the_unsettled_picks(self):
        """The control: without the public filter the leak is real, so the
        assertions below are not vacuous."""
        raw = card_ledger.history(path=self.path)
        self.assertEqual([d["date"] for d in raw["pending_days"]], [TONIGHT_DATE])
        self.assertIn(PARTIAL_DATE, [d["date"] for d in raw["days"]])
        self.assertIn(TONIGHT_BET, json.dumps(raw))

    def test_history_returns_only_fully_settled_days(self):
        payload = card_api.get_card_history(limit=60, sport="mlb", rule="v1")
        self.assertEqual([d["date"] for d in payload["days"]], [SETTLED_DATE])

    def test_pending_days_is_always_empty(self):
        payload = card_api.get_card_history(limit=60, sport="mlb", rule="v1")
        self.assertEqual(payload["pending_days"], [])

    def test_tonights_pick_text_appears_nowhere_in_the_public_payload(self):
        payload = card_api.get_card_history(limit=60, sport="mlb", rule="v1")
        blob = json.dumps(payload)
        self.assertNotIn(TONIGHT_BET, blob)
        self.assertNotIn(TONIGHT_DATE, blob)
        self.assertNotIn(PARTIAL_DATE, blob)

    def test_totals_never_count_days_the_response_hides(self):
        payload = card_api.get_card_history(limit=60, sport="mlb", rule="v1")
        self.assertEqual(payload["total_days"], len(payload["days"]))
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["withheld_days"], 1)

    def test_the_day_returns_when_its_last_pick_resolves(self):
        card_ledger.settle(PARTIAL_DATE, {
            201: {"away_score": "2", "home_score": "5"},
            202: {"away_score": "6", "home_score": "1"},
        }, path=self.path)
        payload = card_api.get_card_history(limit=60, sport="mlb", rule="v1")
        self.assertEqual({d["date"] for d in payload["days"]},
                         {SETTLED_DATE, PARTIAL_DATE})

    def test_no_token_needed_through_the_real_app(self):
        status, body = _asgi_get("/card/history?rule=v1")
        self.assertEqual(status, 200)
        self.assertEqual([d["date"] for d in body["days"]], [SETTLED_DATE])
        self.assertEqual(body["pending_days"], [])
        self.assertNotIn(TONIGHT_BET, json.dumps(body))

    def test_record_needs_no_token_and_carries_no_pick_text(self):
        status, body = _asgi_get("/card/record?rule=v1")
        self.assertEqual(status, 200)
        self.assertNotIn(TONIGHT_BET, json.dumps(body))
        self.assertIn("wins", body)

    def test_tonights_card_by_date_still_needs_a_token(self):
        status, _ = _asgi_get(f"/card/{TONIGHT_DATE}")
        self.assertEqual(status, 401)
        status, _ = _asgi_get(f"/card/{TONIGHT_DATE}?rule=v1")
        self.assertEqual(status, 401)

    def test_a_bad_token_on_the_public_route_is_ignored_not_a_401(self):
        """A stale token in a visitor's browser must not turn the public
        record into a sign-in wall: the route has no auth dependency at all."""
        status, _ = _asgi_get("/card/history?rule=v1",
                              headers=[(b"authorization", b"Bearer not-a-real-token")])
        self.assertEqual(status, 200)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class PublicHistoryFilterUnit(unittest.TestCase):
    """`_public_history` on hand-built payloads, including V2's `graded` shape
    and the partial-settlement counters."""

    def test_v2_day_with_an_unresolved_entry_is_withheld(self):
        payload = {"days": [
            {"date": "2026-09-27", "graded": [{"result": "WIN"}, {"result": "LOSS"}]},
            {"date": "2026-09-28", "graded": [{"result": "WIN"}, {"result": "UNRESOLVED"}]},
        ], "total_days": 2, "truncated": False}
        out = card_api._public_history(payload)
        self.assertEqual([d["date"] for d in out["days"]], ["2026-09-27"])
        self.assertEqual(out["total_days"], 1)
        self.assertEqual(out["pending_days"], [])

    def test_counter_only_unresolved_also_withholds(self):
        out = card_api._public_history({"days": [
            {"date": "d1", "unresolved": 0, "picks": []},
            {"date": "d2", "unresolved": 2, "picks": []},
            {"date": "d3", "prop_unresolved": 1, "picks": []},
            {"date": "d4", "total_unresolved": 1, "picks": []},
        ], "total_days": 4})
        self.assertEqual([d["date"] for d in out["days"]], ["d1"])

    def test_pending_days_are_dropped_whatever_the_payload_held(self):
        out = card_api._public_history({"days": [], "pending_days": [
            {"date": "2026-10-01", "picks": [{"bet": "secret"}]}]})
        self.assertEqual(out["pending_days"], [])
        self.assertNotIn("secret", json.dumps(out))

    def test_truncated_is_recomputed_from_what_remains(self):
        out = card_api._public_history({
            "days": [{"date": "a", "unresolved": 1}, {"date": "b"}],
            "total_days": 2, "truncated": False})
        self.assertFalse(out["truncated"])
        out = card_api._public_history({
            "days": [{"date": "a"}], "total_days": 90, "truncated": True})
        self.assertTrue(out["truncated"])

    def test_every_history_branch_goes_through_the_filter(self):
        """A new branch added to get_card_history must not skip it: the
        source of the route returns `_public_history(...)` on each path."""
        import inspect
        source = inspect.getsource(card_api.get_card_history)
        self.assertGreaterEqual(source.count("_public_history("), 2)
        self.assertNotIn("payload = card_ledger.history_v2(limit=limit)\n", source)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class PublicRoutesAreRateLimited(unittest.TestCase):
    def test_both_public_routes_carry_a_per_ip_limiter(self):
        for route in card_api.public_router.routes:
            with self.subTest(path=route.path):
                self.assertTrue(route.dependencies,
                                "an open route with no limiter is a free way "
                                "to burn the box's CPU on chain verification")

    def test_the_paid_router_holds_only_the_paid_routes(self):
        paths = {getattr(r, "path", None) for r in card_api.router.routes}
        self.assertEqual(paths, {"/card", "/card/{date}"})


if __name__ == "__main__":
    unittest.main()
