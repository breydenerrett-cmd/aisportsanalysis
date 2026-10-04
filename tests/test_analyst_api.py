"""GET /analyst/{date}/{away}/{home} and GET /analyst/record.

The route functions are plain callables (the pattern of tests/test_api_games.py),
so no server and no TestClient is needed. The ledger rows are injected: nothing
here reads evidence/analyst_v1.jsonl, and a test proves a request never calls
the model.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analyst import critic, ledger
from tests import analyst_fixtures as F

ROOT = Path(__file__).resolve().parent.parent


def rows_with_a_graded_game():
    tmp = tempfile.TemporaryDirectory()
    path = str(Path(tmp.name) / "a.jsonl")
    packet = F.build()
    out = F.good_output(packet)
    out["calls"][1]["reasons"][0]["claim"] = "A 9.99 thing."          # struck
    ledger.publish(packet, critic.verify(packet, out), now=F.NOW, model="m", path=path,
                   packet_dir=str(Path(tmp.name) / "p"))
    ledger.grade_date(F.DATE, {849835: {"away_score": "5", "home_score": "3"}}, [], now=F.NOW, path=path)
    rows = ledger.rows(path)
    tmp.cleanup()
    return rows


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheGameRoute(unittest.TestCase):
    def setUp(self):
        from api import analyst as api_analyst
        self.api = api_analyst
        self.rows = rows_with_a_graded_game()

    def get(self, date=F.DATE, away="NYY", home="TB", rows=None):
        with mock.patch.object(self.api, "_rows", return_value=self.rows if rows is None else rows):
            return self.api.get_analysis(date, away, home)

    def test_a_published_game_returns_its_analysis_label_and_grades(self):
        body = self.get()
        self.assertTrue(body["available"])
        self.assertEqual(body["label"], "Written by an AI model from the data on this page. Unproven. Analysis, not advice.")
        a = body["analysis"]
        self.assertEqual(a["game_id"], "NYY-TB-2026-10-03-1")
        self.assertEqual(a["summary_status"], "ok")
        ml = next(c for c in a["calls"] if c["slot_id"] == "moneyline")
        self.assertEqual((ml["verdict"], ml["selection"], ml["result"]), ("TAKE_OTHER_SIDE", "NYY", "WIN"))
        self.assertTrue(a["graded"])

    def test_pass_calls_are_returned_alongside_takes(self):
        verdicts = {c["verdict"] for c in self.get()["analysis"]["calls"]}
        self.assertEqual(verdicts, {"TAKE_OTHER_SIDE", "PASS"})

    def test_a_struck_call_arrives_as_a_pass_with_no_unsupported_claim(self):
        a = self.get()["analysis"]
        rl = next(c for c in a["calls"] if c["slot_id"] == "run_line")
        self.assertEqual(rl["verification"]["status"], "could not be verified")
        self.assertNotIn("9.99", json.dumps(a))

    def test_a_game_with_nothing_published_says_so_plainly_and_is_not_an_error(self):
        body = self.get(away="BOS", home="NYM")
        self.assertEqual(body["available"], False)
        self.assertEqual(body["reason"], "No analysis has been published for this game.")
        self.assertIsNone(body["analysis"])
        self.assertIn("Unproven", body["label"])

    def test_a_bad_date_is_a_400(self):
        from fastapi import HTTPException
        for bad in ("2026-13-45", "yesterday", "2026-1-1"):
            with self.assertRaises(HTTPException) as ctx:
                self.get(date=bad)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_a_request_never_calls_the_model_or_the_network(self):
        from src.analyst import analyst as A
        with mock.patch.object(A, "urllib_post", side_effect=AssertionError("network used")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            self.assertTrue(self.get()["available"])
            self.assertFalse(self.get(away="X", home="Y")["available"])

    def test_the_route_module_imports_no_model_code(self):
        text = (ROOT / "api" / "analyst.py").read_text(encoding="utf-8")
        self.assertNotIn("analyze(", text)
        self.assertNotIn("urllib", text)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRecordRoute(unittest.TestCase):
    def setUp(self):
        from api import analyst as api_analyst
        self.api = api_analyst
        self.rows = rows_with_a_graded_game()

    def test_it_returns_counts_by_family_with_the_small_sample_rule(self):
        with mock.patch.object(self.api, "_rows", return_value=self.rows):
            rec = self.api.get_record()
        self.assertEqual(rec["games_published"], 1)
        ml = rec["families"]["moneyline"]
        self.assertEqual((ml["taken"], ml["wins"], ml["graded"]), (1, 1, 1))
        self.assertIsNone(ml["win_rate"])
        self.assertIsNone(ml["units"])
        self.assertIn("fewer than 30", ml["withheld_reason"])
        self.assertIn("Unproven", rec["label"])

    def test_it_never_serves_an_unsettled_games_calls(self):
        unsettled = [r for r in self.rows if r["kind"] == ledger.KIND_PUBLISHED]
        with mock.patch.object(self.api, "_rows", return_value=unsettled):
            rec = self.api.get_record()
        self.assertEqual(rec["recent"], [])
        self.assertNotIn("Caminero", json.dumps(rec))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheCacheFollowsTheFile(unittest.TestCase):
    def test_rows_are_reread_when_the_file_changes_and_not_before(self):
        from api import analyst as api_analyst
        api_analyst.reset_cache_for_tests()
        none = (None, None)
        with mock.patch.object(api_analyst, "_signature",
                               side_effect=[((1, 1), none), ((1, 1), none), ((2, 2), none)]), \
                mock.patch.object(api_analyst.ledger, "rows", return_value=["x"]) as read:
            api_analyst._rows()
            api_analyst._rows()
            self.assertEqual(read.call_count, 1)
            api_analyst._rows()
            self.assertEqual(read.call_count, 2)
        api_analyst.reset_cache_for_tests()

    def test_a_missing_ledger_is_an_empty_one(self):
        from api import analyst as api_analyst
        api_analyst.reset_cache_for_tests()
        with mock.patch.object(api_analyst, "_signature", return_value=(None, None)):
            self.assertEqual(api_analyst._rows(), [])
        api_analyst.reset_cache_for_tests()


class MountedWithTheRightGates(unittest.TestCase):
    """api/app.py is read as text: this repo's test environment has no ASGI
    client, and the property is positional (public before paid, paid gate on
    the game route)."""

    def setUp(self):
        self.app = (ROOT / "api" / "app.py").read_text(encoding="utf-8")

    def test_the_game_route_has_the_same_gate_as_the_game_surface(self):
        self.assertIn("app.include_router(analyst_router, dependencies=_authed_paid)", self.app)
        self.assertIn("app.include_router(games_router, dependencies=_authed_paid)", self.app)

    def test_the_public_record_is_mounted_before_the_paid_route_and_ungated(self):
        public = self.app.index("app.include_router(analyst_public_router)")
        paid = self.app.index("app.include_router(analyst_router,")
        self.assertLess(public, paid)
        self.assertNotRegex(self.app, r"analyst_public_router[^\n]*dependencies")

    def test_the_route_module_declares_exactly_those_two_paths(self):
        text = (ROOT / "api" / "analyst.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r'@(?:public_)?router\.get\("([^"]+)"', text)),
                         ["/analyst/record", "/analyst/{date}/{away}/{home}"])


if __name__ == "__main__":
    unittest.main()
