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
