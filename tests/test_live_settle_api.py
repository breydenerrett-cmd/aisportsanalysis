"""api/hounds_live.py: GET /hounds/live and /hounds/live/status, and how the app mounts and starts the loop (2026-10-22)."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:                      # Linux CI runs the no-FastAPI harness
    HAS_FASTAPI = False

from src.hounds import live_settle as lv

REPO = Path(__file__).resolve().parent.parent


class WithDb(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get(lv.ENV_DB)
        os.environ[lv.ENV_DB] = os.path.join(self._tmp.name, "live.db")
        self.conn = lv.connect()

    def tearDown(self):
        self.conn.close()
        if self._old is None:
            os.environ.pop(lv.ENV_DB, None)
        else:
            os.environ[lv.ENV_DB] = self._old
        self._tmp.cleanup()

    def seed(self, key, state, **kw):
        row = dict(sport="NBA", home_team="Brooklyn Nets", away_team="Charlotte Hornets",
                   start_utc="2026-10-21T23:30:00Z", home_score=None, away_score=None, detail=None,
                   updated_utc="2026-10-22T02:00:00Z", supported=1, final_utc=None, applied_utc=None)
        row.update(kw)
        self.conn.execute(
            "INSERT INTO live_games(game_key, sport, home_team, away_team, start_utc, state, home_score, away_score,"
            " detail, updated_utc, supported, final_utc, applied_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, row["sport"], row["home_team"], row["away_team"], row["start_utc"], state, row["home_score"],
             row["away_score"], row["detail"], row["updated_utc"], row["supported"], row["final_utc"], row["applied_utc"]))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(WithDb):
    def setUp(self):
        super().setUp()
        from fastapi import Response
        from api import hounds_live
        self.api, self.Response = hounds_live, Response

    def test_asked_games_come_back_with_their_state_and_unknown_ids_are_absent(self):
        self.seed("ev1", "final", home_score=112.0, away_score=108.0, final_utc="2026-10-22T02:00:00Z")
        out = self.api.live_games(self.Response(), ids="ev1,nope", _rl=None)
        self.assertEqual(sorted(out["games"]), ["ev1"])
        self.assertEqual((out["games"]["ev1"]["state"], out["games"]["ev1"]["home_score"]), ("final", 112.0))
        self.assertTrue(out["paper_only"])

    def test_the_cache_header_is_shorter_than_the_loop_interval(self):
        response = self.Response()
        self.api.live_games(response, ids="ev1", _rl=None)
        self.assertEqual(response.headers["cache-control"], "public, max-age=15")
        self.assertLess(15, lv.INTERVAL_SECONDS)

    def test_bad_ids_and_too_many_ids_are_a_422_not_a_query(self):
        from fastapi import HTTPException
        for ids in ("a b", "x;drop", "../etc", ",".join(f"id{i}" for i in range(61)), "y" * 65):
            with self.subTest(ids=ids[:20]):
                with self.assertRaises(HTTPException) as ctx:
                    self.api.live_games(self.Response(), ids=ids, _rl=None)
                self.assertEqual(ctx.exception.status_code, 422)

    def test_no_ids_is_an_empty_answer(self):
        self.assertEqual(self.api.live_games(self.Response(), ids=None, _rl=None)["games"], {})

    def test_the_status_counts_games_waiting_for_a_final(self):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.seed("ev-live", "live", start_utc=start)
        self.seed("ev-final", "final", start_utc=start, home_score=1.0, away_score=0.0)
        out = self.api.live_status(self.Response(), _rl=None)
        self.assertEqual((out["awaiting_final"], out["final_ungraded"], out["enabled"]), (1, 1, True))


class TheWiring(unittest.TestCase):
    def test_the_router_is_mounted_before_the_routes_that_read_live_as_a_hound_id(self):
        source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        live_at = source.index("app.include_router(hounds_live_router)")
        for later in ("app.include_router(hounds_router)", "app.include_router(feeds_router)"):
            self.assertLess(live_at, source.index(later), later)

    def test_the_app_starts_the_loop_at_boot_through_the_same_warmup_gate_as_the_others(self):
        source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("live_settle.start_loop(ready=_warm_up_done)", source)

    def test_an_old_stale_live_row_reads_as_unknown_not_as_a_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = lv.connect(os.path.join(tmp, "x.db"))
            conn.execute("INSERT INTO live_games(game_key, sport, state, home_score, away_score, updated_utc, supported)"
                         " VALUES ('k','NBA','live',50,48,'2026-10-22T00:00:00Z',1)")
            got = lv.game_states(["k"], now=datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc), conn=conn)
            conn.close()
        self.assertEqual(got["k"]["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
