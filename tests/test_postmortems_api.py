"""api/hounds_postmortems.py: the spreadsheet download and the reviews route (owner ask 2026-10-28).

Who sees what: a house hound's spreadsheet and reviews are public; a member hound's are its owner's. The routes are called directly
(the pattern tests/test_live_settle_api.py uses) with the identity, the book and the engine faked.
"""
from __future__ import annotations

import csv
import io
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:                      # Linux CI runs the no-FastAPI harness
    HAS_FASTAPI = False

from src.ai import postmortem_store as store
from src.ai import postmortems
from tests.postmortem_fixtures import FakeClient, Rig, bet, book_of, hound_data

REPO = Path(__file__).resolve().parent.parent
OWNER, STRANGER = 7, 9


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(unittest.TestCase):
    def setUp(self):
        from fastapi import Response
        from api import hounds_postmortems as api
        from src.hounds.interact import common
        self.api, self.Response, self.common = api, Response, common
        self.rig = Rig()
        self.addCleanup(self.rig.close)
        self.viewer = None
        self.data = {"u-1": hound_data("u-1", [bet(1, result="loss"), bet(2, result="win", price=120)], kind="user"),
                     "h-1": hound_data("h-1", [bet(1, hound_id="h-1", result="loss")], kind="house", category="stats")}
        self.dogs = {"u-1": common.Dog(id="u-1", kind=common.KIND_USER, name="Dee", owner_user_id=OWNER),
                     "h-1": common.Dog(id="h-1", kind=common.KIND_HOUSE, name="Pack hound")}
        patches = [
            mock.patch.object(common, "resolve", lambda hid: self.dogs.get(hid)),
            mock.patch.object(common, "hound_data", lambda dog: self.data.get(dog.id)),
            mock.patch.object(api.auth_mod, "optional_user_id", lambda authorization: self.viewer if authorization else None),
            mock.patch.object(postmortems, "default_engine", lambda: self.rig.engine),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def export(self, hid, fmt="csv", auth=None):
        return self.api.export_bets(hid, self.Response(), format=fmt, authorization=auth, _rl=None)

    def reviews(self, hid, auth=None):
        return self.api.hound_postmortems(hid, self.Response(), authorization=auth, _rl=None)

    def rows(self, response):
        return list(csv.reader(io.StringIO(response.body.decode("utf-8-sig"), newline="")))

    def status_of(self, call, *args, **kw):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            call(*args, **kw)
        return ctx.exception.status_code, ctx.exception.detail

    def review_everything(self, hid="u-1"):
        book = book_of(*self.data.values())
        self.rig.engine.tick(book)
        self.rig.clock.advance(minutes=30)
        self.rig.engine.tick(book)

    # -- the spreadsheet ---------------------------------------------------------------------------------

    def test_a_house_hounds_spreadsheet_is_public(self):
        out = self.export("h-1")
        self.assertEqual(out.media_type, "text/csv; charset=utf-8")
        self.assertIn("attachment", out.headers["content-disposition"])
        self.assertIn("linehound-h-1-bets-", out.headers["content-disposition"])
        self.assertEqual(out.headers["cache-control"], "no-store")
        rows = self.rows(out)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "h-1")
        self.assertTrue(out.body.startswith(b"\xef\xbb\xbf"))

    def test_a_member_hounds_spreadsheet_is_its_owners_only(self):
        self.assertEqual(self.status_of(self.export, "u-1")[0], 401)                     # no sign-in
        self.viewer = STRANGER
        status, detail = self.status_of(self.export, "u-1", auth="Bearer x")
        self.assertEqual((status, detail["error"]), (403, "owner_only"))
        self.viewer = OWNER
        self.assertEqual(len(self.rows(self.export("u-1", auth="Bearer x"))), 3)

    def test_an_unknown_hound_is_a_404(self):
        self.assertEqual(self.status_of(self.export, "nobody")[0], 404)
        self.assertEqual(self.status_of(self.reviews, "nobody")[0], 404)

    def test_a_book_that_is_still_warming_is_a_503_with_a_retry_after(self):
        self.data.pop("h-1")
        response = self.Response()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.api.export_bets("h-1", response, format="csv", authorization=None, _rl=None)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (503, "warming_up"))
        self.assertEqual(response.headers["retry-after"], "5")

    def test_xlsx_is_refused_in_words_when_openpyxl_is_not_installed(self):
        from src.hounds import bet_export
        if "xlsx" in bet_export.available_formats():
            self.skipTest("openpyxl is installed here")
        status, detail = self.status_of(self.export, "h-1", fmt="xlsx")
        self.assertEqual((status, detail["error"], detail["available"]), (422, "format_unavailable", ["csv"]))
        self.assertIn("CSV", detail["message"])

    def test_the_sheet_carries_the_reviews_once_they_exist(self):
        self.review_everything()
        self.viewer = OWNER
        sheet = self.rows(self.export("u-1", auth="Bearer x"))
        head = sheet[0]
        status = {row[head.index("Matchup")]: row[head.index("Hindsight: review status")] for row in sheet[1:]}
        self.assertEqual(set(status.values()), {"reviewed"})
        lesson = sheet[1][head.index("Hindsight: lesson")]
        self.assertTrue(lesson)

    def test_a_broken_ledger_never_stops_the_download(self):
        self.rig.engine.ledger = mock.Mock(rows_for=mock.Mock(side_effect=OSError("disk gone")))
        out = self.export("h-1")
        self.assertEqual(len(self.rows(out)), 2)

    # -- the reviews -----------------------------------------------------------------------------------------------

    def test_house_reviews_are_public_and_labelled_hindsight(self):
        self.review_everything()
        out = self.reviews("h-1")
        self.assertTrue(out["visible"])
        self.assertEqual(out["label"], "Hindsight review")
        self.assertIn("after the result", out["note"])
        self.assertTrue(out["paper_only"])
        key = store.bet_key("h-1", self.data["h-1"].bets[0])
        self.assertEqual(list(out["reviews"]), [key])
        self.assertEqual(out["reviews"][key]["label"], "Hindsight review")
        self.assertTrue(out["reviews"][key]["sources"])

    def test_a_member_hounds_reviews_are_not_shown_to_a_visitor_or_a_stranger(self):
        self.review_everything()
        for viewer, auth in ((None, None), (STRANGER, "Bearer x")):
            self.viewer = viewer
            out = self.reviews("u-1", auth=auth)
            self.assertEqual((out["visible"], out["reviews"]), (False, {}))
        self.viewer = OWNER
        out = self.reviews("u-1", auth="Bearer x")
        self.assertTrue(out["visible"])
        self.assertEqual(len(out["reviews"]), 2)

    def test_no_store_header_because_the_answer_depends_on_who_asks(self):
        response = self.Response()
        self.api.hound_postmortems("h-1", response, authorization=None, _rl=None)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_a_broken_ledger_gives_an_empty_page_not_an_error(self):
        self.rig.engine.ledger = mock.Mock(rows_for=mock.Mock(side_effect=OSError("disk gone")))
        out = self.reviews("h-1")
        self.assertEqual((out["visible"], out["reviews"]), (True, {}))

    def test_pending_counts_the_bets_still_waiting_for_a_review(self):
        self.rig.env.pop("ANTHROPIC_API_KEY")                                         # no key: the queue waits
        self.rig.engine.tick(book_of(*self.data.values()))
        self.viewer = OWNER
        self.assertEqual(self.reviews("u-1", auth="Bearer x")["pending"], 2)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheAllVersionsRoute(unittest.TestCase):
    """GET /hounds/{id}/export?versions=all (every bet of every version, with a Version column) and the lineage's Deep reviews on the
    reviews route (owner ask 2026-10-28)."""

    def setUp(self):
        from fastapi import Response
        from api import hounds_postmortems as api
        from src.hounds import bet_export, version_chain
        from src.hounds.interact import common
        self.api, self.Response, self.common, self.bx, self.vc = api, Response, common, bet_export, version_chain
        self.real_lineage_members = api._lineage_members                                         # the route's own lookup, before it is patched
        self.rig = Rig()
        self.addCleanup(self.rig.close)
        self.viewer = None
        self.data = {
            "u-1": hound_data("u-1", [bet(1, hound_id="u-1", result="loss"), bet(2, hound_id="u-1", result="win")], kind="user"),
            "u-2": hound_data("u-2", [bet(3, hound_id="u-2", result="loss"), bet(4, hound_id="u-2", result="win"), bet(5, hound_id="u-2", result=None)], kind="user"),
            "pk@v1": hound_data("pk@v1", [bet(6, hound_id="pk@v1", result="loss")], kind="house", category="stats"),
            "pk": hound_data("pk", [bet(7, hound_id="pk", result="win")], kind="house", category="stats")}
        self.dogs = {
            "u-1": common.Dog(id="u-1", kind=common.KIND_USER, name="Dee", owner_user_id=OWNER, status="retired", root_id="u-1"),
            "u-2": common.Dog(id="u-2", kind=common.KIND_USER, name="Dee", owner_user_id=OWNER, root_id="u-1"),
            "pk@v1": common.Dog(id="pk@v1", kind=common.KIND_OTHER, name="Pack v1", root_id="pk@v1"),
            "pk": common.Dog(id="pk", kind=common.KIND_HOUSE, name="Pack hound", root_id="pk")}
        member = version_chain.Member
        self.members = {
            "u-1": [member("u-1", 1, "retired", "Dee", replaced=True), member("u-2", 2, "running", "Dee")],
            "pk": [member("pk@v1", 1, "retired", "Pack v1", replaced=True), member("pk", 2, "running", "Pack hound")]}
        self.members["u-2"], self.members["pk@v1"] = self.members["u-1"], self.members["pk"]
        for p in (mock.patch.object(common, "resolve", lambda hid: self.dogs.get(hid)),
                  mock.patch.object(common, "hound_data", lambda dog: self.data.get(dog.id)),
                  mock.patch.object(api.auth_mod, "optional_user_id", lambda authorization: self.viewer if authorization else None),
                  mock.patch.object(postmortems, "default_engine", lambda: self.rig.engine),
                  mock.patch.object(api, "_lineage_members", lambda dog: list(self.members.get(dog.id, [])))):
            p.start()
            self.addCleanup(p.stop)

    def export(self, hid, versions="all", auth=None):
        return self.api.export_bets(hid, self.Response(), format="csv", versions=versions, authorization=auth, _rl=None)

    def sheet(self, response):
        return list(csv.reader(io.StringIO(response.body.decode("utf-8-sig"), newline="")))

    def status_of(self, call, *args, **kw):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            call(*args, **kw)
        return ctx.exception.status_code, ctx.exception.detail

    # -- the sheet ---------------------------------------------------------------------------------------------------

    def test_the_default_sheet_has_no_version_columns_and_only_its_own_bets(self):
        self.viewer = OWNER
        out = self.api.export_bets("u-2", self.Response(), format="csv", authorization="Bearer x", _rl=None)
        rows = self.sheet(out)
        self.assertEqual(rows[0], self.bx.HEADERS)
        self.assertNotIn("Version", rows[0])
        self.assertEqual(len(rows) - 1, 3)

    def test_all_versions_is_one_sheet_with_a_version_column_and_every_bet_of_every_version(self):
        self.viewer = OWNER
        rows = self.sheet(self.export("u-2", auth="Bearer x"))
        head, body = rows[0], rows[1:]
        self.assertEqual(head, [h for _k, h in self.bx.COLUMNS_ALL_VERSIONS])
        self.assertEqual(head[3:5], ["Version", "Version status"])
        self.assertEqual(head[:3], self.bx.HEADERS[:3])
        self.assertEqual(head[5:], self.bx.HEADERS[3:])
        self.assertEqual(len(body), 2 + 3)                                                      # the older version's bets and the current one's
        v, s, h = head.index("Version"), head.index("Version status"), head.index("Hound ID")
        self.assertEqual([r[v] for r in body], ["v1", "v1", "v2", "v2", "v2"])                  # oldest version first
        self.assertEqual([r[s] for r in body], ["replaced by a later version"] * 2 + ["running"] * 3)
        self.assertEqual([r[h] for r in body], ["u-1", "u-1", "u-2", "u-2", "u-2"])
        ids = [r[head.index("Bet ID")] for r in body]
        self.assertEqual(len(set(ids)), len(ids))                                               # an id is made from its own version's hound id

    def test_asking_through_an_older_version_gives_the_same_whole_lineage(self):
        self.viewer = OWNER
        a = self.sheet(self.export("u-1", auth="Bearer x"))
        b = self.sheet(self.export("u-2", auth="Bearer x"))
        self.assertEqual(a, b)

    def test_a_member_lineage_is_its_owners_only_whatever_version_is_asked_for(self):
        for hid in ("u-1", "u-2"):
            self.viewer = None
            self.assertEqual(self.status_of(self.export, hid)[0], 401)
            self.viewer = STRANGER
            status, detail = self.status_of(self.export, hid, auth="Bearer x")
            self.assertEqual((status, detail["error"]), (403, "owner_only"))

    def test_a_house_hounds_earlier_versions_are_public(self):
        rows = self.sheet(self.export("pk"))
        head, body = rows[0], rows[1:]
        self.assertEqual([r[head.index("Version")] for r in body], ["v1", "v2"])
        self.assertEqual([r[head.index("Hound ID")] for r in body], ["pk@v1", "pk"])
        self.assertEqual(self.sheet(self.export("pk@v1")), rows)                                # the archive's own address gives the same sheet

    def test_a_replay_row_keeps_its_label_in_every_version(self):
        self.data["u-1"].bets.append(bet(9, hound_id="u-1", result="loss", segment="replay"))
        self.viewer = OWNER
        rows = self.sheet(self.export("u-2", auth="Bearer x"))
        head = rows[0]
        replay = [r for r in rows[1:] if r[head.index("Segment")].startswith("replay")]
        self.assertEqual(len(replay), 1)
        self.assertEqual((replay[0][head.index("Version")], replay[0][head.index("Counted in record")]), ("v1", "no"))

    def test_the_reviews_of_an_earlier_version_are_on_its_rows(self):
        book = book_of(*self.data.values())
        self.rig.engine.tick(book)
        self.rig.clock.advance(minutes=30)
        self.rig.engine.tick(book)
        self.viewer = OWNER
        rows = self.sheet(self.export("u-2", auth="Bearer x"))
        head = rows[0]
        status = {(r[head.index("Version")], r[head.index("Matchup")]): r[head.index("Hindsight: review status")] for r in rows[1:]}
        self.assertEqual(status[("v1", "Team A1 at Team B1")], "reviewed")

    def test_a_version_nobody_can_read_is_skipped_but_the_asked_for_one_must_be_there(self):
        self.viewer = OWNER
        self.data.pop("u-1")
        rows = self.sheet(self.export("u-2", auth="Bearer x"))
        self.assertEqual({r[rows[0].index("Version")] for r in rows[1:]}, {"v2"})
        self.data["u-1"] = hound_data("u-1", [bet(1, hound_id="u-1")], kind="user")
        self.data.pop("u-2")
        self.assertEqual(self.status_of(self.export, "u-2", auth="Bearer x")[0], 503)

    def test_a_lineage_that_cannot_be_read_still_gives_the_one_version(self):
        self.viewer = OWNER
        self.members.clear()
        rows = self.sheet(self.export("u-2", auth="Bearer x"))
        self.assertEqual({r[rows[0].index("Version")] for r in rows[1:]}, {"v1"})
        self.assertEqual(len(rows) - 1, 3)

    def test_the_file_is_named_for_all_versions(self):
        self.viewer = OWNER
        out = self.export("u-2", auth="Bearer x")
        self.assertIn("linehound-u-2-bets-all-versions-", out.headers["content-disposition"])
        self.assertEqual(out.headers["cache-control"], "no-store")
        plain = self.api.export_bets("u-2", self.Response(), format="csv", authorization="Bearer x", _rl=None)
        self.assertNotIn("all-versions", plain.headers["content-disposition"])

    def test_the_query_param_is_wired_end_to_end_and_only_accepts_all(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(self.api.router)
        client = TestClient(app)
        self.assertEqual(client.get("/hounds/pk/export?versions=bogus").status_code, 422)
        every = client.get("/hounds/pk/export?format=csv&versions=all")
        self.assertEqual(every.status_code, 200)
        self.assertIn("all-versions", every.headers["content-disposition"])
        self.assertIn("Version status", every.content.decode("utf-8-sig").splitlines()[0])
        plain = client.get("/hounds/pk/export")
        self.assertEqual(plain.status_code, 200)
        self.assertNotIn("Version", plain.content.decode("utf-8-sig").splitlines()[0])

    # -- the real lineage lookup -------------------------------------------------------------------------------------

    def test_the_real_lookup_reads_a_member_hounds_versions_from_the_database_rows(self):
        from src.hounds import user_store
        from tests.backfill_fixtures import user_row
        rows = [user_row("u-1", "u-1", 1, status="retired", reason="superseded by u-2: edit"), user_row("u-2", "u-1", 2)]
        with mock.patch.object(user_store, "lineage", lambda hid, db=None: rows):
            members = self.real_lineage_members(self.dogs["u-2"])
        self.assertEqual([(m.label, m.status_text) for m in members], [("v1", "replaced by a later version"), ("v2", "running")])

    def test_the_real_lookup_reads_a_pack_hounds_archives_from_the_book(self):
        from src.hounds import stats
        with mock.patch.object(stats, "peek_book", lambda: book_of(*self.data.values())):
            members = self.real_lineage_members(self.dogs["pk"])
        self.assertEqual([(m.hound_id, m.label) for m in members], [("pk@v1", "v1"), ("pk", "v2")])

    def test_the_real_lookup_never_raises(self):
        from src.hounds import stats

        def boom():
            raise RuntimeError("book")
        with mock.patch.object(stats, "peek_book", boom):
            self.assertEqual(self.real_lineage_members(self.dogs["pk"]), [])

    # -- the Deep reviews on the reviews route ---------------------------------------------------------------------

    def reviews(self, hid, auth=None):
        return self.api.hound_postmortems(hid, self.Response(), authorization=auth, _rl=None)

    def test_the_reviews_route_lists_the_lineages_deep_reviews_newest_first_labelled_hindsight(self):
        from tests.backfill_fixtures import add_deep
        deep = self.rig.engine.deep_ledger
        add_deep(deep, "u-1", settled=12, headline="The first deep look.")
        self.rig.clock.advance(hours=3)
        add_deep(deep, "u-1", settled=24, headline="The second deep look.")
        self.viewer = OWNER
        for hid in ("u-1", "u-2"):                                                              # any version of the lineage shows the lineage's
            out = self.reviews(hid, auth="Bearer x")
            self.assertEqual([d["headline"] for d in out["deep_reviews"]], ["The second deep look.", "The first deep look."])
            self.assertEqual(out["deep_reviews"][0]["label"], "Deep review (hindsight)")
            self.assertIn("after the results", out["deep_note"])
            self.assertEqual(out["deep_label"], "Deep review (hindsight)")
            self.assertNotIn("cost_usd", out["deep_reviews"][0])
            self.assertNotIn("batch_id", out["deep_reviews"][0])

    def test_a_member_hounds_deep_reviews_are_its_owners_only(self):
        from tests.backfill_fixtures import add_deep
        add_deep(self.rig.engine.deep_ledger, "u-1")
        for viewer, auth in ((None, None), (STRANGER, "Bearer x")):
            self.viewer = viewer
            out = self.reviews("u-2", auth=auth)
            self.assertEqual((out["visible"], out["deep_reviews"]), (False, []))

    def test_a_house_hounds_deep_reviews_are_public_through_any_of_its_versions(self):
        from tests.backfill_fixtures import add_deep
        add_deep(self.rig.engine.deep_ledger, "pk", hound_ids=("pk@v1", "pk"))
        self.assertEqual(len(self.reviews("pk")["deep_reviews"]), 1)
        self.assertEqual(len(self.reviews("pk@v1")["deep_reviews"]), 1)

    def test_no_deep_review_is_an_empty_list_and_a_broken_ledger_an_empty_page(self):
        self.assertEqual(self.reviews("pk")["deep_reviews"], [])
        self.rig.engine.deep_ledger = mock.Mock(rows_for=mock.Mock(side_effect=OSError("disk gone")))
        out = self.reviews("pk")
        self.assertEqual((out["visible"], out["deep_reviews"]), (True, []))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheAdminPanel(unittest.TestCase):
    """The backfill's progress is on the admin AI status panel (done / queued / remaining / spent), behind the admin gate."""

    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.close)
        patch = mock.patch.object(postmortems, "default_engine", lambda: self.rig.engine)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_panel_carries_the_postmortem_status_and_the_backfill_progress(self):
        from api import ai as ai_api
        with mock.patch.object(ai_api.ai_runner, "build_status", lambda: {"switch": {"on": True}}):
            out = ai_api.get_ai_status(_admin=None)
        self.assertEqual(out["switch"], {"on": True})
        pm = out["postmortems"]
        self.assertEqual(pm["cap_usd"], 20.0)
        backfill = pm["backfill"]
        self.assertEqual((backfill["on"], backfill["cap_usd"], backfill["spent_usd"]), (False, 25.0, 0.0))
        for part in ("bets", "deep_passes", "lineage_reviews"):
            self.assertIn("done", backfill[part])
            self.assertIn("queued", backfill[part])
        self.assertIn("remaining", backfill["bets"])
        self.assertNotIn("sk-ant", repr(out))
        self.assertIs(pm["key_present"], True)                                                  # whether a key is set, never the key

    def test_a_status_that_cannot_be_read_never_breaks_the_panel(self):
        from api import ai as ai_api
        self.rig.engine.usage = mock.Mock(month_spend=mock.Mock(side_effect=OSError("disk")))
        with mock.patch.object(ai_api.ai_runner, "build_status", lambda: {"switch": {}}):
            out = ai_api.get_ai_status(_admin=None)
        self.assertEqual(out["postmortems"], {"error": "OSError"})


class TheMountOrder(unittest.TestCase):
    def test_the_router_is_mounted_after_the_literal_tips_export_it_would_otherwise_swallow(self):
        src = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertLess(src.index("app.include_router(hounds_tips_router)"), src.index("app.include_router(hounds_postmortems_router)"))

    def test_the_two_routes_exist_with_the_paths_the_page_calls(self):
        text = (REPO / "api" / "hounds_postmortems.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/hounds/{hound_id}/export")', text)
        self.assertIn('@router.get("/hounds/{hound_id}/postmortems")', text)
        js = (REPO / "web" / "js" / "record-postmortems.js").read_text(encoding="utf-8")
        self.assertIn("/export?format=", js)
        self.assertIn("/postmortems", js)


if __name__ == "__main__":
    unittest.main()
