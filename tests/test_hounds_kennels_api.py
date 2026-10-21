"""Kennels: every member's public dogs (src/hounds/kennels.py, api/hounds_kennels.py).

The rules this file holds the feature to:
  * a dog with NO bet (a member made it a minute ago) is listed, with a zero record and "new": true. The
    2026-10-19 bug was two members' dogs that nobody could find because every list hid a dog with nothing yet;
  * only PUBLIC dogs: a retired dog is not in a kennel (it is in the graveyard with its record);
  * nothing about the account ever leaves: no email, no account id, no token, no owner key;
  * the handle is the anonymous owner label as a slug, and either spelling resolves;
  * the router is mounted before api.hounds, or /hounds/kennels would be read as a hound id.

The logic tests need no FastAPI (Linux CI has none); the route tests are skipped without it.
"""

from __future__ import annotations

import json
import re
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
from src.hounds import kennels, seasons, stats, user_defs, user_engine, user_store
from tests._hounds_user_fixtures import spec_dict

REPO = Path(__file__).resolve().parent.parent


class KennelCase(unittest.TestCase):
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
        self.jacob = users_store.create_user("jacob.private@example.com", status="active", db=self.db)
        self.sam = users_store.create_user("sam.private@example.com", status="active", db=self.db)
        self.gus = user_store.create_hound(self.jacob.id, spec_dict(name="Underdog Gus"))
        self.tina = user_store.create_hound(self.jacob.id, spec_dict(name="Totals Tina"))
        self.rex = user_store.create_hound(self.sam.id, spec_dict(name="Road Rex"))

    @property
    def jacob_handle(self):
        return kennels.handle_for(self.jacob.id)


class TheHandle(KennelCase):
    def test_the_handle_is_the_anonymous_owner_label_as_a_slug(self):
        label = user_defs.owner_display(self.jacob.id)
        self.assertRegex(label, r"^Handler [0-9A-F]{4}$")
        self.assertEqual(self.jacob_handle, label.lower().replace(" ", "-"))
        self.assertEqual(kennels.slug("Handler 21E8"), "handler-21e8")

    def test_either_spelling_finds_the_kennel_and_a_stranger_finds_nothing(self):
        label = user_defs.owner_display(self.jacob.id)
        for spelling in (self.jacob_handle, label, label.upper(), f"  {self.jacob_handle}  "):
            self.assertEqual(kennels.kennel_detail(spelling)["dog_count"], 2, spelling)
        self.assertIsNone(kennels.kennel_detail("handler-0000"))
        self.assertIsNone(kennels.kennel_detail("someone-else"))
        self.assertIsNone(kennels.kennel_detail(""))


class TheListedDogs(KennelCase):
    def test_a_dog_with_no_bet_is_listed_with_a_zero_record_in_season_two(self):
        self.assertEqual(seasons.default_id(), "s2")
        out = kennels.kennel_detail(self.jacob_handle)
        self.assertEqual({d["name"] for d in out["dogs"]}, {"Underdog Gus", "Totals Tina"})
        for dog in out["dogs"]:
            self.assertTrue(dog["new"], dog)
            self.assertEqual((dog["settled"], dog["open_bets"]), (0, 0))
            self.assertEqual(dog["record"]["bets"], 0)
            self.assertIsNone(dog["last_pick"])
            self.assertEqual(dog["page_href"], f"hound.html?id={dog['id']}")
        self.assertEqual(out["season"]["id"], "s2")
        self.assertIsNone(out["best"])                      # nobody has a settled bet: there is no "best", never a guess

    def test_the_index_counts_every_dog_even_when_none_has_a_bet(self):
        out = kennels.kennel_list()
        by_handle = {k["handle"]: k for k in out["kennels"]}
        self.assertEqual(out["count"], 2)
        self.assertEqual(by_handle[self.jacob_handle]["dog_count"], 2)
        self.assertEqual(by_handle[self.jacob_handle]["new_dogs"], 2)
        self.assertEqual(by_handle[kennels.handle_for(self.sam.id)]["dog_count"], 1)
        self.assertEqual(out["kennels"][0]["handle"], self.jacob_handle)         # most dogs first
        self.assertEqual(by_handle[self.jacob_handle]["href"], f"kennel.html?u={self.jacob_handle}")

    def test_a_retired_dog_is_not_public(self):
        user_store.retire_hound(self.tina["id"], by="owner", reason="done with it")
        out = kennels.kennel_detail(self.jacob_handle)
        self.assertEqual([d["name"] for d in out["dogs"]], ["Underdog Gus"])
        self.assertEqual(kennels.kennel_list()["kennels"][0]["dog_count"], 1)
        user_store.retire_hound(self.gus["id"], by="owner", reason="done with it")
        self.assertIsNone(kennels.kennel_detail(self.jacob_handle))                # no public dog, no kennel
        self.assertNotIn(self.jacob_handle, [k["handle"] for k in kennels.kennel_list()["kennels"]])

    def test_a_saved_look_travels_with_the_dog(self):
        from src.hounds.interact import look, store
        saved = look.validate_look({"coat": "black", "eyes": "amber", "bg": "teal", "head": "cap"})
        store.set_look(self.gus["root_id"], saved, self.jacob.id)
        dogs = {d["name"]: d for d in kennels.kennel_detail(self.jacob_handle)["dogs"]}
        self.assertEqual(dogs["Underdog Gus"]["look"]["coat"], "black")
        self.assertIsNone(dogs["Totals Tina"]["look"])

    def test_no_member_dogs_at_all_is_an_empty_index_not_an_error(self):
        with mock.patch.object(user_defs, "db_exists", lambda: False):
            self.assertEqual(kennels.kennel_list()["kennels"], [])
            self.assertIsNone(kennels.kennel_detail(self.jacob_handle))


class NothingAboutTheAccountLeaves(KennelCase):
    def blob(self):
        return json.dumps([kennels.kennel_list(), kennels.kennel_detail(self.jacob_handle),
                           kennels.kennel_detail(kennels.handle_for(self.sam.id))])

    def test_no_email_account_id_or_owner_key_is_in_any_payload(self):
        text = self.blob()
        self.assertNotIn("example.com", text)
        self.assertNotIn("private", text)
        for key in ("owner_user_id", "email", "user_id", "token", "owner_id", "spec_json", "spec_hash", "created_at"):
            self.assertNotIn(f'"{key}"', text, key)
        # the only owner identity is the anonymous label
        self.assertEqual(sorted(set(re.findall(r"handler-[0-9a-f]{4}", text))),
                         sorted({self.jacob_handle, kennels.handle_for(self.sam.id)}))

    def test_a_dog_entry_has_only_the_public_fields(self):
        dog = kennels.kennel_detail(self.jacob_handle)["dogs"][0]
        self.assertEqual(set(dog), {"id", "name", "tagline", "status", "version_no", "look", "sports", "record", "settled",
                                    "open_bets", "new", "last_pick", "page_href", "bankroll", "trained_times", "coached_from", "root_id"})

    def test_every_dog_carries_its_paper_account_even_a_dog_with_no_bet(self):
        for dog in kennels.kennel_detail(self.jacob_handle)["dogs"]:
            b = dog["bankroll"]
            self.assertIsNotNone(b, dog["id"])
            self.assertEqual((b["start"], b["unit_usd"]), (1000.0, 10.0))
            if dog["new"]:
                self.assertEqual((b["current"], b["return_pct"], b["bets"]), (1000.0, 0.0, 0))
            self.assertEqual(b["current"], round(1000.0 + b["pnl_usd"], 2))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(KennelCase):
    def setUp(self):
        super().setUp()
        from api import hounds_kennels as api
        self.api = api

    def test_the_index_and_a_kennel_are_public_reads_with_the_paper_line(self):
        index = self.api.kennel_index(Response(), season=None, _rl=None)
        self.assertTrue(index["paper_only"])
        self.assertEqual(index["count"], 2)
        page = self.api.kennel_page(self.jacob_handle, Response(), season=None, _rl=None)
        self.assertEqual(page["dog_count"], 2)
        self.assertTrue(page["paper_only"] and page["not_advice"])

    def test_an_unknown_kennel_is_a_404_and_a_bad_season_is_a_422(self):
        with self.assertRaises(HTTPException) as ctx:
            self.api.kennel_page("handler-0000", Response(), season=None, _rl=None)
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            self.api.kennel_index(Response(), season="s99", _rl=None)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_the_router_is_mounted_before_the_routes_that_read_a_kennel_as_a_hound_id(self):
        source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        kennel_at = source.index("app.include_router(hounds_kennels_router)")
        for later in ("app.include_router(hounds_router)", "app.include_router(hounds_learning_router)"):
            self.assertLess(kennel_at, source.index(later), later)


class MyKennel(KennelCase):
    def test_my_kennel_is_only_my_dogs_with_retired_ones_last_and_flagged(self):
        user_store.retire_hound(self.gus["id"], by="owner", reason="done with it")
        out = kennels.my_kennel(self.jacob.id)
        self.assertEqual([d["name"] for d in out["dogs"]], ["Totals Tina", "Underdog Gus"])
        self.assertEqual([d["retired"] for d in out["dogs"]], [False, True])
        self.assertEqual(out["dog_count"], 1)
        self.assertEqual(out["handle"], self.jacob_handle)
        self.assertTrue(all(d["builder_href"].startswith("build-a-hound.html?from=u-") for d in out["dogs"]))
        self.assertNotIn("Road Rex", json.dumps(out))
        self.assertNotIn("example.com", json.dumps(out))

    def test_a_member_with_no_dog_gets_an_empty_kennel_not_an_error(self):
        nobody = users_store.create_user("nobody@example.com", status="active", db=self.db)
        out = kennels.my_kennel(nobody.id)
        self.assertEqual((out["dogs"], out["dog_count"]), ([], 0))


class WithoutFastApi(unittest.TestCase):
    def test_the_logic_module_imports_with_fastapi_hidden(self):
        import subprocess
        import sys
        code = ("import sys\nfor n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
                "import src.hounds.kennels as k\nprint(k.slug('Handler 3F2A'))")
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertEqual(out.stdout.strip(), "handler-3f2a")


if __name__ == "__main__":
    unittest.main()
