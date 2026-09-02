"""api/mybets.py: GET/POST/DELETE for the authed user's saved bets.

Skip-if-no-fastapi (see tests/test_api_auth.py's module docstring for why
there is no TestClient/HTTP layer here). Route functions are called
directly with a real User (from src.appstate.users) standing in for what
FastAPI's Depends(get_current_user) would have resolved.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import events
from src.appstate import savedbets as savedbets_store
from src.appstate import users as users_store


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MyBetsRouteTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(savedbets_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("betuser@example.com", db=self.db)

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_list_is_empty_for_a_new_user(self):
        from api.mybets import list_my_bets
        result = list_my_bets(current_user=self.user)
        self.assertEqual(result, {"bets": []})

    def test_post_then_get_roundtrip(self):
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets
        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML", price=120,
                           snapshot_digest="deadbeef"),
            current_user=self.user)
        self.assertEqual(created["game"], "BOS@NYY")
        self.assertIn("id", created)

        listed = list_my_bets(current_user=self.user)
        self.assertEqual(len(listed["bets"]), 1)
        self.assertEqual(listed["bets"][0]["id"], created["id"])
        self.assertEqual(listed["bets"][0]["snapshot_digest"], "deadbeef")

    def test_delete_then_it_no_longer_lists(self):
        from api.mybets import SaveBetRequest, create_my_bet, delete_my_bet, list_my_bets
        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML"), current_user=self.user)
        result = delete_my_bet(created["id"], current_user=self.user)
        self.assertEqual(result, {"deleted": True, "id": created["id"]})
        self.assertEqual(list_my_bets(current_user=self.user)["bets"], [])

    def test_delete_unknown_bet_is_404(self):
        from fastapi import HTTPException
        from api.mybets import delete_my_bet
        with self.assertRaises(HTTPException) as ctx:
            delete_my_bet(999999, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_one_user_cannot_delete_anothers_bet(self):
        from fastapi import HTTPException
        from api.mybets import SaveBetRequest, create_my_bet, delete_my_bet
        other = users_store.create_user("other@example.com", db=self.db)
        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML"), current_user=self.user)
        with self.assertRaises(HTTPException) as ctx:
            delete_my_bet(created["id"], current_user=other)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_one_user_cannot_see_anothers_bets(self):
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets
        other = users_store.create_user("other2@example.com", db=self.db)
        create_my_bet(SaveBetRequest(game="BOS@NYY", side="BOS ML"),
                       current_user=self.user)
        self.assertEqual(list_my_bets(current_user=other)["bets"], [])

    def test_get_rows_carry_settlement_fields_before_and_after_settling(self):
        """GET /my-bets rows must include the three settlement fields even
        before src.appstate.settlement ever runs (null, never omitted --
        a client should not have to special-case a missing key), and must
        reflect a verdict once one is written."""
        from src.appstate import savedbets as savedbets_mod
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets

        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML"), current_user=self.user)
        for field in ("settlement_status", "settlement_reason", "settled_at"):
            self.assertIn(field, created)
            self.assertIsNone(created[field])

        before = list_my_bets(current_user=self.user)["bets"][0]
        self.assertIsNone(before["settlement_status"])

        savedbets_mod.mark_settled(created["id"], "won", db=self.db)
        after = list_my_bets(current_user=self.user)["bets"][0]
        self.assertEqual(after["settlement_status"], "won")
        self.assertIsNotNone(after["settled_at"])

    def test_get_rows_carry_closing_price_fields_before_and_after_recording(self):
        """Same shape guarantee as the settlement fields above, for the
        four closing-price fields: present and null on a fresh save, and
        reflecting whatever src.appstate.savedbets.record_closing wrote
        once the settlement pass computes them."""
        from src.appstate import savedbets as savedbets_mod
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets

        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML", price=110),
            current_user=self.user)
        for field in ("closing_price", "closing_observed_utc",
                     "price_vs_close_cents", "closing_reason"):
            self.assertIn(field, created)
            self.assertIsNone(created[field])

        savedbets_mod.record_closing(
            created["id"], closing_price=116,
            closing_observed_utc="2026-04-01T23:00:00+00:00",
            price_vs_close_cents=6, db=self.db)
        after = list_my_bets(current_user=self.user)["bets"][0]
        self.assertEqual(after["closing_price"], 116)
        self.assertEqual(after["closing_observed_utc"], "2026-04-01T23:00:00+00:00")
        self.assertEqual(after["price_vs_close_cents"], 6)
        self.assertIsNone(after["closing_reason"])

    def test_closing_reason_surfaces_when_no_close_was_found(self):
        from src.appstate import savedbets as savedbets_mod
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets

        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML", price=110),
            current_user=self.user)
        savedbets_mod.record_closing(
            created["id"],
            closing_reason="no odds snapshots captured for this game",
            db=self.db)
        after = list_my_bets(current_user=self.user)["bets"][0]
        self.assertIsNone(after["closing_price"])
        self.assertEqual(after["closing_reason"],
                         "no odds snapshots captured for this game")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SaveBetRequestBoundsTests(unittest.TestCase):
    """Red-team round: input bounds on POST /my-bets. Every case here is a
    pydantic-level 422 (ValidationError), which is what an ASGI request
    would come back as -- the direct-call style just sees the exception
    the framework would otherwise translate."""

    def test_an_oversized_game_is_refused(self):
        from pydantic import ValidationError
        from api.mybets import SaveBetRequest, MAX_GAME_LENGTH
        SaveBetRequest(game="X" * MAX_GAME_LENGTH, side="home")  # at the bound: fine
        with self.assertRaises(ValidationError):
            SaveBetRequest(game="X" * (MAX_GAME_LENGTH + 1), side="home")

    def test_an_oversized_side_is_refused(self):
        from pydantic import ValidationError
        from api.mybets import SaveBetRequest, MAX_SIDE_LENGTH
        SaveBetRequest(game="BOS@NYY", side="X" * MAX_SIDE_LENGTH)  # fine
        with self.assertRaises(ValidationError):
            SaveBetRequest(game="BOS@NYY", side="X" * (MAX_SIDE_LENGTH + 1))

    def test_an_oversized_snapshot_digest_is_refused(self):
        from pydantic import ValidationError
        from api.mybets import SaveBetRequest, MAX_SNAPSHOT_DIGEST_LENGTH
        SaveBetRequest(game="BOS@NYY", side="home",
                       snapshot_digest="a" * MAX_SNAPSHOT_DIGEST_LENGTH)
        with self.assertRaises(ValidationError):
            SaveBetRequest(game="BOS@NYY", side="home",
                           snapshot_digest="a" * (MAX_SNAPSHOT_DIGEST_LENGTH + 1))

    def test_a_price_outside_the_plausible_magnitude_is_refused(self):
        """Same bound POST /betcheck enforces (roughly 100-100000)."""
        from pydantic import ValidationError
        from api.mybets import SaveBetRequest
        SaveBetRequest(game="BOS@NYY", side="home", price=-125)  # fine
        with self.assertRaises(ValidationError):
            SaveBetRequest(game="BOS@NYY", side="home", price=5)
        with self.assertRaises(ValidationError):
            SaveBetRequest(game="BOS@NYY", side="home", price=10_000_000)

    def test_a_non_finite_price_is_a_422_never_a_silent_null(self):
        """The bug this bound exists for: NaN/Infinity is valid IEEE-754
        float input that used to reach sqlite as `price` and come back out
        as a silent NULL on the next read, instead of being refused as the
        unusable input it always was."""
        from pydantic import ValidationError
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    from api.mybets import SaveBetRequest
                    SaveBetRequest(game="BOS@NYY", side="home", price=bad)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MyBetsRateLimitTests(unittest.TestCase):
    """POST /my-bets is rate-limited per user (src/appstate/ratelimit.py).
    This exercises the dependency function directly -- the ASGI-level
    429 (through a real request) is covered in test_api_adversarial.py."""

    def setUp(self):
        import api.mybets as mybets_mod
        from src.appstate import ratelimit
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(savedbets_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("limiter1@example.com", db=self.db)
        self._mybets_mod = mybets_mod
        self._original_limiter = mybets_mod._mybets_limiter
        self._original_dep = mybets_mod._rate_limited
        # A tiny limit so the test does not need 60 real requests.
        mybets_mod._mybets_limiter = ratelimit.FixedWindowLimiter(
            limit=2, window_s=60.0)
        mybets_mod._rate_limited = ratelimit.limiter_dependency(
            mybets_mod._mybets_limiter, user_dependency=mybets_mod.get_current_user)

    def tearDown(self):
        self._mybets_mod._mybets_limiter = self._original_limiter
        self._mybets_mod._rate_limited = self._original_dep
        self._patcher.stop()
        self._tmp.cleanup()

    def test_the_limit_trips_after_the_configured_count(self):
        from fastapi import HTTPException
        dep = self._mybets_mod._rate_limited
        request = mock.Mock(client=None)
        dep(request=request, current_user=self.user)
        dep(request=request, current_user=self.user)
        with self.assertRaises(HTTPException) as ctx:
            dep(request=request, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("retry_after", ctx.exception.detail)

    def test_a_different_user_gets_their_own_counter(self):
        other = users_store.create_user("limiter2@example.com", db=self.db)
        dep = self._mybets_mod._rate_limited
        request = mock.Mock(client=None)
        dep(request=request, current_user=self.user)
        dep(request=request, current_user=self.user)
        dep(request=request, current_user=other)  # a fresh counter, not shared


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class BetSavedEventTests(unittest.TestCase):
    """bet_saved wiring: recorded on a successful save, never on the 400
    validation-error path, and never breaks the response if the events db
    itself is broken."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(savedbets_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("betsaved@example.com", db=self.db)

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_success_records_bet_saved_for_the_authed_user(self):
        from api.mybets import SaveBetRequest, create_my_bet
        with mock.patch.object(events, "record_event_safe") as safe:
            create_my_bet(SaveBetRequest(game="BOS@NYY", side="BOS ML"),
                          current_user=self.user)
        safe.assert_called_once_with(self.user.id, events.BET_SAVED)

    def test_a_rejected_save_records_nothing(self):
        """save_bet's own ValueError (e.g. an unparseable game/side) surfaces
        as this route's 400 -- that is not a bet saved, so it must not
        inflate the count."""
        from fastapi import HTTPException
        from api.mybets import SaveBetRequest, create_my_bet
        with mock.patch("src.appstate.savedbets.save_bet",
                        side_effect=ValueError("bad bet")), \
             mock.patch.object(events, "record_event_safe") as safe:
            with self.assertRaises(HTTPException) as ctx:
                create_my_bet(SaveBetRequest(game="BOS@NYY", side="BOS ML"),
                              current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 400)
        safe.assert_not_called()

    def test_a_broken_events_db_never_breaks_the_save(self):
        from api.mybets import SaveBetRequest, create_my_bet
        with mock.patch.object(events, "record_event",
                               side_effect=RuntimeError("disk full")):
            created = create_my_bet(SaveBetRequest(game="BOS@NYY", side="BOS ML"),
                                    current_user=self.user)
        self.assertEqual(created["game"], "BOS@NYY")

    def test_no_email_in_the_recorded_event_and_the_hash_really_is_there(self):
        """The load-bearing privacy guarantee at this call site: scan the
        events db's raw bytes for the user's email (a raw int id like "1"
        is too short to check this way -- it would coincidentally appear
        inside almost any hex hash; src/appstate/events.py's own test uses a
        large id for exactly that reason)."""
        from api.mybets import SaveBetRequest, create_my_bet
        events_db = Path(self._tmp.name) / "events.db"
        with mock.patch.object(events, "db_path", lambda: events_db):
            create_my_bet(SaveBetRequest(game="BOS@NYY", side="BOS ML"),
                          current_user=self.user)
        blob = events_db.read_bytes()
        self.assertNotIn(self.user.email.encode("utf-8"), blob)
        self.assertIn(events.hash_user_id(self.user.id).encode("utf-8"), blob)


if __name__ == "__main__":
    unittest.main()
