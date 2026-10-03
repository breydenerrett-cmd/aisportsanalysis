"""GET /analyst/ufc/{event_id} and GET /analyst/ufc/record.

The route functions are plain callables (the pattern of tests/test_analyst_api.py), so no
server and no TestClient is needed for them; the gate and the mount order are proved by
driving the REAL api.app over ASGI (the pattern of tests/test_api_surface_auth.py), because a
router-level dependency is invisible to a direct call. The ledger rows are injected: nothing
here reads evidence/analyst_ufc_v1.jsonl, and a test proves a request never calls the model.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analyst import ufc_analyst as U
from src.analyst import ufc_ledger as L
from tests import ufc_analyst_fixtures as F

ROOT = Path(__file__).resolve().parent.parent
LABEL = "Written by an AI model from the data on this page. Unproven. Analysis, not advice."
SECOND = "9102"


def rows_with_a_graded_event():
    """Two bouts of one event published, the main event struck on one call and graded."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        store = F.make_store(tmp / "world", rows=[F.odds(), F.odds(bout_id=SECOND)])
        path, packets = str(tmp / "ufc.jsonl"), str(tmp / "packets")
        for bout_id in (SECOND, F.BOUT):
            packet = F.packet(store, bout_id=bout_id)
            out = F.deep(F.good_output(packet))
            if bout_id == F.BOUT:
                out["calls"][1]["reasons"][0]["claim"] = "A 71.93 thing."          # struck
            L.publish(packet, U.verify(packet, out), now=F.NOW, model="m", path=path, packet_dir=packets)
        F.finish_the_bout(store)
        L.grade_date(F.DATE, store.bout_by_id(), now=F.NOW + timedelta(hours=9), path=path)
        return L.rows(path)


def request(app, method, path, headers=None):
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 11111), "server": ("testserver", 80),
    }
    got, parts = {}, []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            got["status"] = message["status"]
        elif message["type"] == "http.response.body":
            parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    raw = b"".join(parts)
    try:
        return got.get("status"), json.loads(raw)
    except ValueError:
        return got.get("status"), raw.decode("utf-8", "replace")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheEventRoute(unittest.TestCase):
    def setUp(self):
        from api import analyst_ufc
        self.api = analyst_ufc
        self.rows = rows_with_a_graded_event()

    def get(self, event_id=F.EVENT, rows=None):
        with mock.patch.object(self.api, "_rows", return_value=self.rows if rows is None else rows):
            return self.api.get_event_analysis(event_id)

    def test_a_published_event_returns_every_bout_in_card_order_with_label_and_grades(self):
        body = self.get()
        self.assertTrue(body["available"])
        self.assertEqual(body["label"], LABEL)
        self.assertIsNone(body["reason"])
        analysis = body["analysis"]
        self.assertEqual((analysis["event_id"], analysis["event_name"], analysis["date"]),
                         (F.EVENT, "Synthetic Championship Night", F.DATE))
        self.assertEqual([b["bout_id"] for b in analysis["bouts"]], [F.BOUT, SECOND])
        main = analysis["bouts"][0]
        self.assertEqual((main["fighter_a"], main["fighter_b"], main["summary_status"], main["graded"]),
                         (F.A, F.B, "ok", True))
        self.assertEqual(main["result_text"], "Ben Brawler won by KO/TKO in round 2.")
        ml = next(c for c in main["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual((ml["verdict"], ml["selection"], ml["result"]), ("TAKE_OTHER_SIDE", F.B, "WIN"))
        self.assertFalse(analysis["bouts"][1]["graded"])                    # the prelim has no result yet

    def test_pass_calls_are_returned_alongside_takes(self):
        verdicts = {c["verdict"] for c in self.get()["analysis"]["bouts"][1]["calls"]}
        self.assertEqual(verdicts, {"TAKE_OTHER_SIDE", "PASS"})

    def test_a_struck_call_arrives_as_a_pass_with_no_unsupported_claim(self):
        main = self.get()["analysis"]["bouts"][0]
        rt = next(c for c in main["calls"] if c["slot_id"] == "rounds_total")
        self.assertEqual(rt["verification"]["status"], "could not be verified")
        self.assertEqual(rt["verdict"], "PASS")
        self.assertNotIn("71.93", json.dumps(self.get()))

    def test_an_event_with_nothing_published_says_so_plainly_and_is_not_an_error(self):
        body = self.get("999")
        self.assertEqual(body["available"], False)
        self.assertEqual(body["reason"], "No analysis has been published for this event.")
        self.assertIsNone(body["analysis"])
        self.assertIn("Unproven", body["label"])
        self.assertFalse(self.get(rows=[])["available"])

    def test_a_malformed_event_id_is_a_400(self):
        from fastapi import HTTPException
        for bad in ("../etc", "a b", "", "x" * 41, "7013/9101", "7013;drop"):
            with self.assertRaises(HTTPException) as ctx:
                self.get(bad)
            self.assertEqual(ctx.exception.status_code, 400, bad)

    def test_a_request_never_calls_the_model_or_the_network(self):
        from src.analyst import analyst as A
        with mock.patch.object(A, "urllib_post", side_effect=AssertionError("network used")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            self.assertTrue(self.get()["available"])
            self.assertFalse(self.get("999")["available"])

    def test_the_route_module_imports_no_model_code(self):
        text = (ROOT / "api" / "analyst_ufc.py").read_text(encoding="utf-8")
        for needle in ("analyze(", "urllib", "ufc_analyst", "ANTHROPIC", "http_post"):
            self.assertNotIn(needle, text)

    def test_it_reads_only_the_ufc_ledger(self):
        text = (ROOT / "api" / "analyst_ufc.py").read_text(encoding="utf-8")
        self.assertIn("ufc_ledger.STORE", text)
        self.assertNotIn("analyst_v1", text)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRecordRoute(unittest.TestCase):
    def setUp(self):
        from api import analyst_ufc
        self.api = analyst_ufc
        self.rows = rows_with_a_graded_event()

    def test_it_returns_counts_by_family_with_the_small_sample_rule(self):
        with mock.patch.object(self.api, "_rows", return_value=self.rows):
            rec = self.api.get_record()
        self.assertEqual((rec["bouts_published"], rec["bouts_settled"]), (2, 1))
        self.assertEqual(list(rec["families"]), ["moneyline", "method", "rounds_total"])
        ml = rec["families"]["moneyline"]
        self.assertEqual((ml["taken"], ml["wins"], ml["graded"]), (2, 1, 1))
        self.assertIsNone(ml["win_rate"])
        self.assertIsNone(ml["units"])
        self.assertIn("fewer than 30", ml["withheld_reason"])
        self.assertIn("Unproven", rec["label"])

    def test_it_never_serves_an_unsettled_bouts_calls(self):
        unsettled = [r for r in self.rows if r["kind"] == L.KIND_PUBLISHED]
        with mock.patch.object(self.api, "_rows", return_value=unsettled):
            rec = self.api.get_record()
        self.assertEqual(rec["recent"], [])
        self.assertNotIn("Brawler", json.dumps(rec))

    def test_the_recent_list_has_only_what_was_settled(self):
        with mock.patch.object(self.api, "_rows", return_value=self.rows):
            rec = self.api.get_record()
        self.assertEqual({r["fighter_a"] for r in rec["recent"]}, {F.A})
        self.assertTrue(all(r["result"] in ("WIN", "LOSS", "PUSH", "VOID") for r in rec["recent"]))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheCacheFollowsTheFile(unittest.TestCase):
    def test_rows_are_reread_when_the_file_changes_and_not_before(self):
        from api import analyst_ufc
        analyst_ufc.reset_cache_for_tests()
        with mock.patch.object(analyst_ufc, "_signature", side_effect=[(1, 1), (1, 1), (2, 2)]), \
                mock.patch.object(analyst_ufc.ufc_ledger, "rows", return_value=["x"]) as read:
            analyst_ufc._rows()
            analyst_ufc._rows()
            self.assertEqual(read.call_count, 1)
            analyst_ufc._rows()
            self.assertEqual(read.call_count, 2)
        analyst_ufc.reset_cache_for_tests()

    def test_a_missing_ledger_is_an_empty_one(self):
        from api import analyst_ufc
        analyst_ufc.reset_cache_for_tests()
        with mock.patch.object(analyst_ufc, "_signature", return_value=(None, None)):
            self.assertEqual(analyst_ufc._rows(), [])
        analyst_ufc.reset_cache_for_tests()


class MountedWithTheRightGates(unittest.TestCase):
    """api/app.py read as text: public before paid, the paid gate on the event route."""

    def setUp(self):
        self.app = (ROOT / "api" / "app.py").read_text(encoding="utf-8")

    def test_the_event_route_has_the_same_gate_as_the_game_surface(self):
        self.assertIn("app.include_router(analyst_ufc_router, dependencies=_authed_paid)", self.app)
        self.assertIn("app.include_router(analyst_router, dependencies=_authed_paid)", self.app)

    def test_the_public_record_is_mounted_before_the_paid_route_and_ungated(self):
        public = self.app.index("app.include_router(analyst_ufc_public_router)")
        paid = self.app.index("app.include_router(analyst_ufc_router,")
        self.assertLess(public, paid)
        self.assertNotRegex(self.app, r"analyst_ufc_public_router[^\n]*dependencies")

    def test_the_route_module_declares_exactly_those_two_paths(self):
        text = (ROOT / "api" / "analyst_ufc.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r'@(?:public_)?router\.get\("([^"]+)"', text)),
                         ["/analyst/ufc/record", "/analyst/ufc/{event_id}"])

    def test_the_mlb_route_module_is_untouched_in_what_it_declares(self):
        text = (ROOT / "api" / "analyst.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r'@(?:public_)?router\.get\("([^"]+)"', text)),
                         ["/analyst/record", "/analyst/{date}/{away}/{home}"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRealAppEnforcesThem(unittest.TestCase):
    """Router-level dependencies are invisible to a direct call, so this drives api.app itself."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_the_event_route_needs_a_token(self):
        status, _ = request(self.app, "GET", f"/analyst/ufc/{F.EVENT}")
        self.assertEqual(status, 401)

    def test_a_bad_token_is_refused_too(self):
        status, _ = request(self.app, "GET", f"/analyst/ufc/{F.EVENT}", {"Authorization": "Bearer nope"})
        self.assertEqual(status, 401)

    def test_the_record_is_public_and_is_not_swallowed_by_the_event_route(self):
        with mock.patch("api.analyst_ufc._rows", return_value=[]):
            status, body = request(self.app, "GET", "/analyst/ufc/record")
        self.assertEqual(status, 200)
        self.assertEqual(list(body["families"]), ["moneyline", "method", "rounds_total"])
        self.assertEqual((body["bouts_published"], body["bouts_settled"]), (0, 0))
        self.assertIn("Unproven", body["label"])

    def test_the_mlb_analyst_routes_still_answer_as_they_did(self):
        status, _ = request(self.app, "GET", "/analyst/2026-10-03/NYY/TB")
        self.assertEqual(status, 401)
        with mock.patch("api.analyst._rows", return_value=[]):
            status, body = request(self.app, "GET", "/analyst/record")
        self.assertEqual(status, 200)
        self.assertEqual(list(body["families"]), ["moneyline", "run_line", "total", "team_total", "prop"])


if __name__ == "__main__":
    unittest.main()
