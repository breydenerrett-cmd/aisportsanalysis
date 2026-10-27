"""One-time member announcements: the append-only store, the member API, the CLI and the kennel_fire overlay.

The store and CLI tests need no FastAPI (Linux CI has none); the route tests skip without it; the overlay runs the real
web/js/announcements.js under node in the fake-DOM harness (skipped without node).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import announcements as store
from src.appstate import users as users_store
from src.hounds import announce_cli, user_store
from tests._hounds_user_fixtures import spec_dict
from tests.hounds_web_runner import HAS_NODE, run_page

STEPS = ["one", "two"]
REPO = Path(__file__).resolve().parent.parent


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        p = mock.patch.object(users_store, "db_path", lambda: self.db)
        p.start()
        self.addCleanup(p.stop)
        self.jacob = users_store.create_user("jacob@example.com", status="active", db=self.db)
        self.sam = users_store.create_user("sam@example.com", status="active", db=self.db)


class TheStore(Base):
    def test_unseen_then_seen_and_each_member_only_sees_their_own(self):
        a = store.add(self.jacob.id, "kennel_fire", STEPS, db=self.db)
        self.assertEqual([r["id"] for r in store.unseen(self.jacob.id, db=self.db)], [a["id"]])
        self.assertEqual(store.unseen(self.sam.id, db=self.db), [])
        store.mark_seen(self.jacob.id, a["id"], db=self.db)
        self.assertEqual(store.unseen(self.jacob.id, db=self.db), [])
        store.mark_seen(self.jacob.id, a["id"], db=self.db)            # idempotent
        self.assertEqual(len(store.list_all(db=self.db)), 1)

    def test_someone_elses_id_reads_as_not_found(self):
        a = store.add(self.jacob.id, "kennel_fire", STEPS, db=self.db)
        with self.assertRaises(store.AnnouncementError) as cm:
            store.mark_seen(self.sam.id, a["id"], db=self.db)
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(len(store.unseen(self.jacob.id, db=self.db)), 1)

    def test_the_tables_are_append_only(self):
        a = store.add(self.jacob.id, "kennel_fire", STEPS, db=self.db)
        store.mark_seen(self.jacob.id, a["id"], db=self.db)
        with store.connect(self.db) as conn:
            for sql in ("UPDATE member_announcements SET title = 'x'", "DELETE FROM member_announcements",
                        "UPDATE member_announcement_seen SET seen_utc = 'x'", "DELETE FROM member_announcement_seen"):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                    conn.execute(sql)

    def test_bad_input_is_refused(self):
        for kind, steps, user in (("nope", STEPS, self.jacob.id), ("kennel_fire", [], self.jacob.id),
                                  ("kennel_fire", ["ok", 3], self.jacob.id), ("kennel_fire", STEPS, 9999)):
            with self.assertRaises(store.AnnouncementError):
                store.add(user, kind, steps, db=self.db)

    def test_the_default_steps_file_is_the_five_owner_lines(self):
        steps = json.loads(announce_cli.default_steps_path("kennel_fire").read_text(encoding="utf-8"))
        self.assertEqual(len(steps), 5)
        self.assertTrue(steps[0].startswith("Your data hound now checks every major sport"))
        self.assertTrue(steps[4].startswith("Meet The Learner"))
        self.assertEqual(store.clean_steps(steps), steps)


class TheCli(Base):
    def run_cli(self, **kw):
        base = dict(user=None, kind=None, steps_file=None, list_all=False, find_user=None, db=str(self.db))
        base.update(kw)
        lines: list = []
        code = announce_cli.main(argparse.Namespace(**base), out=lines.append)
        return code, "\n".join(lines)

    def test_announce_writes_one_with_the_default_steps_then_lists_it(self):
        code, text = self.run_cli(user=self.jacob.id, kind="kennel_fire")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(store.unseen(self.jacob.id, db=self.db)[0]["steps"]), 5)
        self.assertIn("UNSEEN", self.run_cli(list_all=True)[1])

    def test_steps_file_overrides_and_a_bad_file_is_an_error_not_a_crash(self):
        f = Path(self._tmp.name) / "s.json"
        f.write_text(json.dumps(["only"]), encoding="utf-8")
        self.assertEqual(self.run_cli(user=self.jacob.id, kind="kennel_fire", steps_file=str(f))[0], 0)
        self.assertEqual(store.unseen(self.jacob.id, db=self.db)[0]["steps"], ["only"])
        f.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_cli(user=self.jacob.id, kind="kennel_fire", steps_file=str(f))[0], 2)
        self.assertEqual(self.run_cli(user=self.jacob.id)[0], 2)

    def test_find_user_prints_the_owner_of_a_hound(self):
        h = user_store.create_hound(self.sam.id, spec_dict(name="Road Rex"), db=self.db)
        code, text = self.run_cli(find_user=h["id"])
        self.assertEqual(code, 0)
        self.assertIn(f"user_id {self.sam.id} ", text)
        self.assertIn(f"v1  {h['id']}  ", text)                        # the lineage, so a retired id points at the current one
        self.assertEqual(self.run_cli(find_user="u-nope")[0], 2)

    def test_the_command_is_wired_into_the_cli(self):
        from src import cli
        args = cli.build_parser().parse_args(["announce", "--find-user", "u-x"])
        self.assertEqual(args.command, "announce")
        self.assertIn("announce", cli.COMMANDS)


@unittest.skipUnless(HAS_FASTAPI, "FastAPI not installed")
class TheRoutes(Base):
    def test_get_returns_only_my_unseen_and_post_marks_one_seen(self):
        from api import announcements as routes
        a = store.add(self.jacob.id, "kennel_fire", STEPS, db=self.db)
        out = routes.my_announcements(Response(), self.jacob, None)
        self.assertEqual([r["id"] for r in out["announcements"]], [a["id"]])
        self.assertNotIn("user_id", out["announcements"][0])
        self.assertEqual(routes.my_announcements(Response(), self.sam, None)["announcements"], [])
        with self.assertRaises(HTTPException) as cm:
            routes.announcement_seen(a["id"], Response(), self.sam, None)
        self.assertEqual(cm.exception.status_code, 404)
        routes.announcement_seen(a["id"], Response(), self.jacob, None)
        self.assertEqual(routes.my_announcements(Response(), self.jacob, None)["announcements"], [])

    def test_the_router_is_mounted_on_the_app(self):
        src = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(announcements_router)", src)


SIGNED = dict(stored={"aisportsanalysis.invite_token": "tok"})
FIRE = {"id": "an-1", "kind": "kennel_fire", "title": "kennel_fire", "steps": ["Step A.", "Step B."],
        "created_utc": "2026-10-26T00:00:00Z"}


def route(items):
    return {"/me/announcements": [200, {"announcements": items}],
            "POST /me/announcements/an-1/seen": [200, {"id": "an-1"}]}


def q(name, sel, mode="text", **extra):
    return {"name": name, "sel": sel, "mode": mode, **extra}


HOOK = "[data-hook='announcement']"
QUERIES = [q("overlay", HOOK, "count"), q("step", HOOK, "attr", attr="data-step"),
           q("title", "[data-hook='announce-title']"), q("steps", "[data-hook='announce-steps'] li", "texts")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheOverlay(unittest.TestCase):
    def run_nav(self, items=(FIRE,), actions=(), **kw):
        return run_page("nav", page_html="hounds.html", routes=route(list(items)), actions=list(actions), queries=QUERIES,
                        **SIGNED, **kw)

    def test_step_one_is_the_alarm_with_a_what_button(self):
        out = self.run_nav()
        f = out["final"]
        self.assertEqual((f["overlay"], f["step"]), (1, "1"))
        self.assertIn("Your entire kennel has been set on fire. No dogs have survived.", f["title"])
        self.assertIn("/me/announcements", out["gets"])

    def test_what_then_step_two_then_go_marks_seen_and_goes_to_my_kennel(self):
        out = self.run_nav(actions=[{"do": "click", "sel": "[data-hook='announce-what']", "capture": QUERIES},
                                    {"do": "click", "sel": "[data-hook='announce-go']"}])
        two = out["captures"]["0"]
        self.assertEqual((two["step"], two["steps"]), ("2", ["Step A.", "Step B."]))
        self.assertIn("Just kidding", two["title"])
        self.assertIn("better trained", two["title"])
        self.assertEqual(out["final"]["overlay"], 0)
        self.assertEqual([p["url"].split("?")[0] for p in out["posts"]], ["/me/announcements/an-1/seen"])
        self.assertEqual(out["navigations"], ["kennel.html"])

    def test_closing_marks_it_seen_without_navigating(self):
        out = self.run_nav(actions=[{"do": "click", "sel": "[data-hook='announce-close']"}])
        self.assertEqual(out["final"]["overlay"], 0)
        self.assertEqual(len(out["posts"]), 1)
        self.assertEqual(out["navigations"], [])

    def test_nothing_unseen_signed_out_and_a_down_server_all_show_nothing(self):
        self.assertEqual(self.run_nav(items=())["final"]["overlay"], 0)
        out = run_page("nav", page_html="hounds.html", routes=route([FIRE]), queries=QUERIES)
        self.assertEqual((out["final"]["overlay"], out["gets"].count("/me/announcements")), (0, 0))
        down = run_page("nav", page_html="hounds.html", routes={}, queries=QUERIES, **SIGNED)
        self.assertEqual(down["final"]["overlay"], 0)


class TheMotionRule(unittest.TestCase):
    def test_the_flicker_only_runs_for_no_preference(self):
        css = (REPO / "web" / "css" / "lhnav.css").read_text(encoding="utf-8")
        block = css[css.index("One-time member announcements"):]
        cut = block.index("@media (prefers-reduced-motion: no-preference)")
        self.assertIn("animation: lh-flicker", block[cut:])
        self.assertNotIn("animation: lh-flicker", block[:cut])


if __name__ == "__main__":
    unittest.main()
