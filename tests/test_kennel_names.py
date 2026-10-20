"""Kennel names and public profiles (src/hounds/member_profile.py, src/hounds/kennels.py, api/hounds_kennels.py).

Owner ask 2026-10-19. The rules this file holds the feature to:
  * a member can name their kennel: 2 to 30 characters of letters, digits, spaces, hyphens and apostrophes, run through
    the dog-name text filter (profanity, protected brand and league names, reserved words) and a short claims list;
  * a name is UNIQUE case-insensitively (its slug is the identity: "Bob's Dogs" and "bobs dogs" are one kennel), and a
    name may not pass as an anonymous handle ("Handler 21E8");
  * until a member sets one, the kennel is the anonymous handle and a one-time prompt is due; "Not now" ends it;
  * the name shows wherever the owner label shows (kennels index, kennel page title, leaderboard "by <name>", the
    dog page's "Built by <name>"), and the old anonymous link still lands on the renamed kennel;
  * an admin can set or clear any member's kennel name (a reason is required and never public);
  * the public profile carries kennel name, member since (month and year), dog count, the combined paper record and
    dollars, the best dog and the recent tickets, and NEVER an email, an account id or a token.

The logic tests need no FastAPI (Linux CI has none); the route tests are skipped without it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import kennels, member_profile, stats, user_defs, user_engine, user_settle, user_store
from tests._hounds_user_fixtures import DATE, EVENT, result_row, spec_dict, standard_rows, utc

REPO = Path(__file__).resolve().parent.parent
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}
RESULTS = {PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}            # Boston (away, +120) wins


class NameCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                  mock.patch.object(stats, "peek_book", lambda: None),
                  mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming"))):
            p.start()
            self.addCleanup(p.stop)
        member_profile.clear_cache()
        self.addCleanup(member_profile.clear_cache)
        self.jacob = users_store.create_user("jacob.private@example.com", status="active", db=self.db)
        self.sam = users_store.create_user("sam.private@example.com", status="active", db=self.db)
        self.gus = user_store.create_hound(self.jacob.id, spec_dict(name="Underdog Gus"))
        self.tina = user_store.create_hound(self.jacob.id, spec_dict(name="Totals Tina"))
        self.rex = user_store.create_hound(self.sam.id, spec_dict(name="Road Rex"))

    def refuses(self, name, code, user=None):
        with self.assertRaises(member_profile.ProfileError) as ctx:
            member_profile.set_kennel_name((user or self.jacob).id, name)
        self.assertEqual(ctx.exception.code, code, name)
        return ctx.exception


class TheName(NameCase):
    def test_a_good_name_is_saved_and_shown_as_the_owner_label(self):
        member_profile.set_kennel_name(self.jacob.id, "  Jacob's   Pound-1 ")
        self.assertEqual(member_profile.kennel_name_of(self.jacob.id), "Jacob's Pound-1")
        self.assertEqual(user_defs.owner_display(self.jacob.id), "Jacob's Pound-1")
        self.assertEqual(user_defs.owner_display(self.sam.id), user_defs.anonymous_handle(self.sam.id))

    def test_until_it_is_set_the_label_is_the_anonymous_handle(self):
        self.assertRegex(user_defs.owner_display(self.jacob.id), r"^Handler [0-9A-F]{4}$")

    def test_length_is_two_to_thirty(self):
        self.refuses("A", "kennel_name_length")
        self.refuses("   ", "kennel_name_length")
        self.refuses("x" * 31, "kennel_name_length")
        member_profile.set_kennel_name(self.jacob.id, "Ab")
        member_profile.set_kennel_name(self.jacob.id, "a" * 30)

    def test_only_letters_digits_spaces_hyphens_and_apostrophes(self):
        for bad in ("Dogs <b>", "Dogs & Co", "Dogs.", "Dogs_1", "-Dogs", "Dogs-", "'Dogs", "1234", "Dogsé"):
            with self.subTest(bad=bad):
                with self.assertRaises(member_profile.ProfileError) as ctx:
                    member_profile.set_kennel_name(self.jacob.id, bad)
                self.assertIn(ctx.exception.code, ("kennel_name_characters", "kennel_name_length"))

    def test_profanity_protected_names_and_reserved_words_are_refused_like_a_dogs_name(self):
        self.refuses("Fuck Pound", "kennel_name_not_allowed")
        self.refuses("F u c k Pound", "kennel_name_not_allowed")
        self.refuses("DraftKings Dogs", "kennel_name_not_allowed")
        self.refuses("Official Kennel", "kennel_name_not_allowed")
        self.refuses("Linehound HQ", "kennel_name_not_allowed")

    def test_a_kennel_cannot_promise_a_result(self):
        self.refuses("Guaranteed Winners", "kennel_name_claim")
        self.refuses("Can't Lose Crew", "kennel_name_claim")
        self.refuses("Free Money Kennel", "kennel_name_claim")

    def test_a_name_cannot_pass_as_an_anonymous_handle(self):
        self.refuses("Handler 21E8", "kennel_name_reserved")
        self.refuses("handler-0000", "kennel_name_reserved")
        self.refuses("Mine", "kennel_name_reserved")

    def test_a_name_is_unique_case_insensitively_and_by_its_slug(self):
        member_profile.set_kennel_name(self.jacob.id, "Bob's Dogs")
        for twin in ("bob's dogs", "BOBS DOGS", "bobs-dogs", "Bob's  Dogs"):
            with self.subTest(twin=twin):
                exc = self.refuses(twin, "kennel_name_taken", user=self.sam)
                self.assertEqual(exc.status, 409)
        member_profile.set_kennel_name(self.sam.id, "Bob's Cats")

    def test_a_member_can_keep_or_recase_their_own_name(self):
        member_profile.set_kennel_name(self.jacob.id, "Bob's Dogs")
        member_profile.set_kennel_name(self.jacob.id, "BOB'S DOGS")
        self.assertEqual(member_profile.kennel_name_of(self.jacob.id), "BOB'S DOGS")

    def test_two_writes_at_once_cannot_both_take_a_name(self):
        """The unique index is the backstop even when the check and the write race."""
        member_profile.set_kennel_name(self.jacob.id, "Racers")
        import sqlite3
        with member_profile._connect() as conn:
            conn.execute("INSERT INTO member_profiles (user_id, kennel_name, kennel_key) VALUES (?, ?, ?)",
                         (self.sam.id, "Other", "other"))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE member_profiles SET kennel_key = 'racers' WHERE user_id = ?", (self.sam.id,))

    def test_a_member_cannot_clear_their_name_but_an_admin_can(self):
        member_profile.set_kennel_name(self.jacob.id, "Bob's Dogs")
        self.refuses("", "kennel_name_length")
        member_profile.set_kennel_name(self.jacob.id, "", actor="admin", reason="asked support")
        self.assertIsNone(member_profile.kennel_name_of(self.jacob.id))
        self.assertEqual(user_defs.owner_display(self.jacob.id), user_defs.anonymous_handle(self.jacob.id))
        member_profile.set_kennel_name(self.sam.id, "Bob's Dogs")                # the freed name can be taken

    def test_an_unknown_member_is_a_404(self):
        with self.assertRaises(member_profile.ProfileError) as ctx:
            member_profile.set_kennel_name(9999, "Nobody Here")
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_found", 404))


class TheOneTimePrompt(NameCase):
    def test_the_prompt_is_due_until_a_name_is_set_or_it_is_dismissed(self):
        self.assertTrue(member_profile.get(self.jacob.id)["needs_name_prompt"])
        member_profile.dismiss_prompt(self.jacob.id)
        self.assertFalse(member_profile.get(self.jacob.id)["needs_name_prompt"])
        self.assertIsNone(member_profile.get(self.jacob.id)["kennel_name"])
        member_profile.set_kennel_name(self.sam.id, "Sam's Pound")
        self.assertFalse(member_profile.get(self.sam.id)["needs_name_prompt"])

    def test_my_kennel_says_whether_to_prompt_and_what_the_limits_are(self):
        out = kennels.my_kennel(self.jacob.id)
        self.assertTrue(out["needs_name_prompt"])
        self.assertIsNone(out["kennel_name"])
        self.assertEqual((out["name_limits"]["min"], out["name_limits"]["max"]), (2, 30))
        member_profile.set_kennel_name(self.jacob.id, "Jacob's Pound")
        out = kennels.my_kennel(self.jacob.id)
        self.assertFalse(out["needs_name_prompt"])
        self.assertEqual((out["kennel_name"], out["display"], out["handle"]), ("Jacob's Pound", "Jacob's Pound", "jacobs-pound"))


class WhereTheNameShows(NameCase):
    def setUp(self):
        super().setUp()
        self.old_handle = kennels.handle_for(self.jacob.id)
        member_profile.set_kennel_name(self.jacob.id, "Jacob's Pound")

    def test_the_index_the_page_title_and_the_handle(self):
        index = {k["handle"]: k for k in kennels.kennel_list()["kennels"]}
        self.assertEqual(index["jacobs-pound"]["display"], "Jacob's Pound")
        self.assertTrue(index["jacobs-pound"]["named"])
        self.assertEqual(index["jacobs-pound"]["href"], "kennel.html?u=jacobs-pound")
        self.assertFalse(index[kennels.handle_for(self.sam.id)]["named"])
        page = kennels.kennel_detail("jacobs-pound")
        self.assertEqual((page["title"], page["display"], page["named"]), ("Jacob's Pound", "Jacob's Pound", True))

    def test_the_leaderboard_stats_and_the_dog_page_carry_the_name(self):
        self.assertEqual(user_defs.definition(self.gus)["owner_display"], "Jacob's Pound")
        from src.hounds import user_view
        data = user_view.hound_data(self.gus["id"], kick_build=False)
        self.assertEqual(data.summary.owner_display, "Jacob's Pound")

    def test_a_rename_changes_the_stats_cache_key(self):
        before = user_defs.stamp()
        member_profile.set_kennel_name(self.jacob.id, "Jacob's Yard")
        self.assertNotEqual(before, user_defs.stamp())

    def test_the_old_anonymous_link_still_lands_on_the_renamed_kennel(self):
        self.assertEqual(kennels.kennel_detail(self.old_handle)["display"], "Jacob's Pound")
        self.assertEqual(kennels.kennel_detail(self.old_handle.upper())["dog_count"], 2)
        self.assertIsNone(kennels.kennel_detail("handler-0000"))

    def test_a_clear_goes_back_to_the_anonymous_handle_everywhere(self):
        member_profile.set_kennel_name(self.jacob.id, "", actor="admin", reason="support")
        self.assertEqual(kennels.kennel_detail(self.old_handle)["display"], user_defs.anonymous_handle(self.jacob.id))
        self.assertIsNone(kennels.kennel_detail("jacobs-pound"))

    def test_no_member_dogs_database_leaves_the_handle(self):
        with mock.patch.object(users_store, "db_path", lambda: self.db.parent / "nope.db"):
            member_profile.clear_cache()
            self.assertEqual(member_profile.kennel_names(), {})
            self.assertFalse((self.db.parent / "nope.db").exists())


class TheProfile(NameCase):
    def put_and_settle_a_win(self):
        """One ticket for Underdog Gus, graded a win at +120 (+1.2u = +$12 on the $1,000 paper bankroll)."""
        user_engine.run(DATE, [self.gus], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))
        user_settle.settle(ledger=self.ledger, now=utc("2026-10-21T12:00:00Z"), mlb_results=RESULTS,
                           game_pk_index=INDEX, close_fn=lambda b: None, nfl_results=lambda d: {})

    def test_a_new_member_profile(self):
        member_profile.set_kennel_name(self.jacob.id, "Jacob's Pound")
        page = kennels.kennel_detail("jacobs-pound")
        self.assertEqual(page["dog_count"], 2)
        self.assertRegex(page["member_since"], r"^[A-Z][a-z]+ \d{4}$")
        self.assertEqual(page["combined"]["record"], {"bets": 0, "wins": 0, "losses": 0, "pushes": 0})
        self.assertEqual((page["combined"]["pnl_usd"], page["combined"]["start_usd"]), (0.0, 2000.0))
        self.assertIsNone(page["best"])
        self.assertEqual(page["recent_tickets"], [])

    def test_the_combined_record_dollars_best_dog_and_recent_tickets(self):
        self.put_and_settle_a_win()
        page = kennels.kennel_detail(kennels.handle_for(self.jacob.id))
        self.assertEqual(page["combined"]["record"]["wins"], 1)
        self.assertEqual(page["combined"]["settled"], 1)
        self.assertEqual(page["combined"]["pnl_usd"], 12.0)
        self.assertEqual(page["combined"]["return_pct"], 0.6)            # +$12 over two dogs' $2,000
        self.assertEqual(page["best"]["name"], "Underdog Gus")
        self.assertEqual(len(page["recent_tickets"]), 1)
        ticket = page["recent_tickets"][0]
        self.assertEqual((ticket["result"], ticket["dog"]["name"]), ("won", "Underdog Gus"))
        self.assertEqual(ticket["dog"]["href"], f"hound.html?id={self.gus['id']}")
        self.assertEqual(page["bankroll"]["unit_usd"], 10.0)

    def test_the_profile_is_not_a_second_kennel_index_row(self):
        self.put_and_settle_a_win()
        rows = kennels.kennel_list()["kennels"]
        self.assertEqual(sorted(k["dog_count"] for k in rows), [1, 2])


class NothingAboutTheAccountLeaves(NameCase):
    def test_no_email_id_or_token_in_any_payload_named_or_not(self):
        member_profile.set_kennel_name(self.jacob.id, "Jacob's Pound")
        user_engine.run(DATE, [self.gus], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))
        text = json.dumps([kennels.kennel_list(), kennels.kennel_detail("jacobs-pound"),
                           kennels.kennel_detail(kennels.handle_for(self.sam.id)), kennels.my_kennel(self.jacob.id),
                           member_profile.get(self.jacob.id)])
        self.assertNotIn("example.com", text)
        self.assertNotIn("private", text)
        for key in ("owner_user_id", "email", "user_id", "token", "owner_id", "created_at", "kennel_key", "kennel_set"):
            self.assertNotIn(f'"{key}"', text, key)

    def test_member_since_is_a_month_and_a_year_and_nothing_finer(self):
        text = member_profile.member_since(self.jacob.id)
        self.assertRegex(text, r"^[A-Z][a-z]+ \d{4}$")
        self.assertIsNone(member_profile.member_since(9999))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(NameCase):
    def setUp(self):
        super().setUp()
        from api import hounds_kennels as api
        self.api = api

    def put(self, user, **body):
        return self.api.put_my_kennel_name(self.api.KennelNameRequest(**body), Response(), current_user=user, _rl=None)

    def status(self, fn, *a, **k):
        with self.assertRaises(HTTPException) as ctx:
            fn(*a, **k)
        return ctx.exception

    def test_put_names_the_kennel_and_returns_the_handle(self):
        out = self.put(self.jacob, kennel_name="Jacob's Pound")
        self.assertEqual((out["kennel_name"], out["display"], out["handle"]), ("Jacob's Pound", "Jacob's Pound", "jacobs-pound"))
        self.assertFalse(out["needs_name_prompt"])
        self.assertTrue(out["paper_only"])
        self.assertEqual(self.api.my_kennel_name(Response(), current_user=self.jacob, _rl=None)["kennel_name"], "Jacob's Pound")
        page = self.api.kennel_page("jacobs-pound", Response(), season=None, _rl=None)
        self.assertEqual(page["title"], "Jacob's Pound")

    def test_put_refusals_carry_a_code_the_page_can_read(self):
        self.put(self.jacob, kennel_name="Taken Name")
        exc = self.status(self.put, self.sam, kennel_name="taken name")
        self.assertEqual((exc.status_code, exc.detail["error"]), (409, "kennel_name_taken"))
        exc = self.status(self.put, self.sam, kennel_name="Fuck Pound")
        self.assertEqual((exc.status_code, exc.detail["error"]), (422, "kennel_name_not_allowed"))
        exc = self.status(self.put, self.sam, kennel_name="x")
        self.assertEqual((exc.status_code, exc.detail["error"]), (422, "kennel_name_length"))
        exc = self.status(self.put, self.sam)
        self.assertEqual(exc.status_code, 422)

    def test_dismissing_the_prompt(self):
        out = self.put(self.sam, dismiss_prompt=True)
        self.assertFalse(out["needs_name_prompt"])
        self.assertIsNone(out["kennel_name"])

    def test_the_routes_need_a_signed_in_member_and_the_admin_one_needs_the_admin_token(self):
        deps = {}
        for route in self.api.router.routes:
            path = getattr(route, "path", "")
            if path in ("/me/kennel", "/admin/users/kennel-name"):
                names = [(getattr(d, "call", None) or d.dependency).__name__ for d in route.dependant.dependencies]
                deps[(path, tuple(sorted(route.methods)))] = names
        self.assertIn("get_current_user", deps[("/me/kennel", ("PUT",))])
        self.assertIn("get_current_user", deps[("/me/kennel", ("GET",))])
        self.assertIn("_require_admin", deps[("/admin/users/kennel-name", ("POST",))])

    def admin(self, **body):
        return self.api.admin_set_kennel_name(self.api.AdminKennelNameRequest(**body), _admin=None)

    def test_the_admin_sets_a_name_for_any_member_and_never_sees_an_email_back(self):
        out = self.admin(user_id=self.sam.id, kennel_name="Sam's Pound", reason="asked in ticket 12")
        self.assertEqual((out["ok"], out["kennel_name"], out["handle"]), (True, "Sam's Pound", "sams-pound"))
        self.assertNotIn("example.com", json.dumps(out))
        self.assertEqual(user_defs.owner_display(self.sam.id), "Sam's Pound")

    def test_the_admin_name_goes_through_the_same_filter_and_uniqueness(self):
        self.admin(user_id=self.sam.id, kennel_name="Sam's Pound", reason="ok")
        exc = self.status(self.admin, user_id=self.jacob.id, kennel_name="SAMS POUND", reason="ok")
        self.assertEqual((exc.status_code, exc.detail["error"]), (409, "kennel_name_taken"))
        exc = self.status(self.admin, user_id=self.jacob.id, kennel_name="Fuck Pound", reason="ok")
        self.assertEqual(exc.detail["error"], "kennel_name_not_allowed")

    def test_the_admin_needs_a_reason_a_real_member_and_a_name(self):
        self.assertEqual(self.status(self.admin, user_id=self.sam.id, kennel_name="Fine Name").detail["error"], "reason_required")
        self.assertEqual(self.status(self.admin, user_id=999, kennel_name="Fine Name", reason="r").status_code, 409)
        self.assertEqual(self.status(self.admin, user_id="1; drop", kennel_name="Fine Name", reason="r").status_code, 409)
        self.assertEqual(self.status(self.admin, user_id=self.sam.id, reason="r").detail["error"], "kennel_name_required")

    def test_the_admin_can_clear_a_name(self):
        self.put(self.sam, kennel_name="Sam's Pound")
        out = self.admin(user_id=self.sam.id, kennel_name="", reason="owner asked")
        self.assertIsNone(out["kennel_name"])
        self.assertEqual(user_defs.owner_display(self.sam.id), user_defs.anonymous_handle(self.sam.id))


class WithoutFastApi(unittest.TestCase):
    def test_the_logic_modules_import_with_fastapi_hidden(self):
        import subprocess
        import sys
        code = ("import sys\nfor n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
                "import src.hounds.member_profile as m, src.hounds.kennels\nprint(m.slug(\"Bob's Dogs\"))")
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertEqual(out.stdout.strip(), "bobs-dogs")


if __name__ == "__main__":
    unittest.main()
