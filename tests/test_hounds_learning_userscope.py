"""The user scope end to end, inside the API process's tick: a challenger is shadowed on the same boards,
settled, examined by the referee, promoted into a real new hound version in the app database, and the
champion's old record stays. Plus the tick's isolation from the champions' pass.
"""

from __future__ import annotations

import itertools
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.appstate import users as users_store
from src.hounds import user_coach, user_engine, user_runner, user_store
from src.hounds.learning import ledger as L, scorecard, user_scope
from src.ledger.chain import HashChainLedger
from tests import _hounds_user_fixtures as UF
from tests import _learning_fixtures as F
from tests.test_hounds_user_coach import HYPOTHESIS, EVIDENCE

NOW = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)


def user_bet_row(hound_id, event, day, minute):
    return {"kind": "hound_user_bet", "hound_id": hound_id, "bet_id": f"{hound_id}:{event}", "date": day,
            "slate_date": day, "event_id": event, "sport": "MLB", "market": "moneyline", "side": "home",
            "selection": "Home to win", "price": -110, "price_average": -110, "price_best": -105,
            "best_price": -105, "book": "bk", "book_count": 5, "lock_utc": f"{day}T18:{minute:02d}:00Z",
            "start_utc": f"{day}T19:{minute:02d}:00Z", "segment": "forward", "who_decided": "rule",
            "recorded_utc": f"{day}T18:{minute:02d}:30Z"}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.cfg = tmp / "coach.json"
        self.cfg.write_text('{"enabled": true}', encoding="utf-8")
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        patches = [mock.patch.object(users_store, "db_path", lambda: self.db),
                   mock.patch.dict(os.environ, {user_coach.CONFIG_ENV: str(self.cfg)})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.scope = L.Scope.user(tmp)
        user = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.hound = user_store.create_hound(
            user.id, UF.spec_dict(name="Dog Days", markets=["moneyline", "spread"], max_bets_per_day=3, min_books=2),
            coach_opt_in=True, now=F.utc("2026-10-01T00:00:00Z"))


class TickIsCheapAndIsolated(Case):
    def test_no_challengers_no_files_and_no_work(self):
        out = user_scope.tick(now=NOW, ledger=self.ledger, daily=False)
        self.assertEqual(out["live"], 0)
        self.assertEqual(out["errors"], [])
        self.assertFalse(self.scope.challenger_bets.exists())
        self.assertFalse(self.scope.events.exists())

    def test_a_failing_shadow_step_is_reported_and_never_raised(self):
        F.propose_raw(self.scope, cid="c-1", hound_id=self.hound["id"], kind="user", parent_ref=self.hound["id"],
                      lineage=self.hound["root_id"], spec=dict(self.hound["spec"]), category="mixed")
        with mock.patch("src.hounds.learning.shadow.run_user", side_effect=RuntimeError("odds store missing")):
            out = user_scope.tick(now=NOW, ledger=self.ledger, daily=False)
        self.assertEqual(out["live"], 1)
        self.assertTrue(out["errors"][0].startswith("shadow:"))

    def test_run_pass_reports_the_learning_tick_and_survives_its_failure(self):
        rows = []
        with mock.patch.object(user_scope, "tick", side_effect=RuntimeError("boom")):
            report = user_runner.run_pass(now=UF.utc("2026-10-20T21:20:00Z"), ledger=self.ledger,
                                          hounds=[UF.hound("u-run")], refresh_stats=lambda: None,
                                          settle_kwargs={"mlb_results": {}, "nfl_results": lambda d: {},
                                                         "close_fn": lambda b: None})
        self.assertEqual(report["learning"]["errors"], ["RuntimeError('boom')"])
        self.assertIn("engine", report)


class OneChallengerThroughTheWholeLoop(Case):
    def setUp(self):
        # Fixed hound ids (the store draws them from ``secrets``): the test reads the same on every run.
        counter = itertools.count(1)
        patch = mock.patch.object(user_store, "new_hound_id", lambda: f"u-fixed{next(counter):04d}")
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()

    def test_shadow_settle_referee_promotion_new_version_old_record_kept(self):
        # 1. the coach proposes through the real door's guards (recorded as a live challenger)
        spec = dict(self.hound["spec"], markets=["moneyline"])
        from src.hounds.learning import proposals
        ch = proposals.propose_user(self.scope, self.hound, spec, HYPOTHESIS, EVIDENCE, graded=50,
                                    now=F.utc("2026-11-01T12:00:00Z"))
        # 2. 30 days of 4 games a day: the champion and the challenger each have a bet on every game
        champ, chall = HashChainLedger(self.ledger), HashChainLedger(self.scope.challenger_bets)
        events = []
        for d in range(30):
            day = F.day_n(d)
            for i in range(4):
                eid = f"e{d:03d}-{i}"
                events.append(eid)
                champ.append(user_bet_row(self.hound["id"], eid, day, i * 5))
                chall.append(dict(user_bet_row(ch.id, eid, day, i * 5), role="challenger", challenger_id=ch.id,
                                  parent_hound_id=self.hound["id"], parent_version=1))
        F.cover(self.scope, ch.id, events)

        def attach(bets):
            for b in bets:                                   # the closing-line values the odds scan would give
                b.clv_measurable, b.clv_pts = True, F.scenario_clv(b.hound_id == ch.id, b.event_id)

        card_book = SimpleNamespace(hounds={}, clv_bets=[])
        out = user_scope.tick(now=NOW, ledger=self.ledger, daily=True, attach_fn=attach, book=card_book,
                              rows_for=lambda d, s: [])
        self.assertEqual(out["errors"], [], out)
        self.assertEqual(out["referee"]["promoted"], 1, out)
        look = L.read_state(self.scope).challengers[ch.id].looks[0]
        self.assertGreater(look["se"], 0, "a zero-variance scenario has no p-value and cannot promote")
        # 3. a real new version exists; the old one is retired with its spec and ledger rows untouched
        lineage = user_store.lineage(self.hound["id"])
        self.assertEqual([h["version_no"] for h in lineage], [1, 2])
        old, new = lineage
        self.assertEqual((old["status"], new["status"]), ("retired", "running"))
        self.assertEqual(old["spec"], self.hound["spec"])
        self.assertEqual(new["spec"]["markets"], ["moneyline"])
        self.assertTrue(old["retire_reason"].startswith("superseded by"))
        old_rows = [r for r in HashChainLedger(self.ledger).read() if r["hound_id"] == self.hound["id"]]
        self.assertEqual(len(old_rows), 120)                  # the champion's record is exactly what it was
        state = L.read_state(self.scope)
        self.assertEqual(state.challengers[ch.id].status, "promoted")
        self.assertEqual(state.promotions[0]["new_hound_id"], new["id"])
        # 4. the diary has the referee's row, so the owner's undo works
        diary = user_store.diary_for(new["id"])
        self.assertEqual([(d["decision"], d["decided_by"]) for d in diary], [("applied", "referee")])
        self.assertEqual(user_coach.undo(new["id"], now=NOW)["resumed"]["spec"], self.hound["spec"])
        # 5. the scorecard was stored for the day and a second tick the same day does nothing more
        self.assertEqual(len(L.read_state(self.scope).scorecards), 1)
        again = user_scope.tick(now=NOW + timedelta(hours=2), ledger=self.ledger, daily=True, attach_fn=attach,
                                book=card_book, rows_for=lambda d, s: [])
        self.assertNotIn("referee", again)
        self.assertEqual(len(L.read_state(self.scope).scorecards), 1)

    def test_the_apply_is_idempotent_and_refuses_a_gone_champion(self):
        from src.hounds.learning import proposals
        ch = proposals.propose_user(self.scope, self.hound, dict(self.hound["spec"], markets=["moneyline"]),
                                    HYPOTHESIS, EVIDENCE, graded=50, now=F.utc("2026-11-01T12:00:00Z"))
        c = L.read_state(self.scope).challengers[ch.id]
        a = user_scope.apply_promotion(c, {"p_adj": 0.01})
        b = user_scope.apply_promotion(c, {"p_adj": 0.01})
        self.assertEqual(a, b)
        self.assertFalse(user_scope.champion_current(c, L.State()))        # the parent is retired now
        bad = L.Challenger(id="c-x", scope="user", kind="user", hound_id="u-gone", lineage_key="u-gone",
                           category="mixed", parent_version=1, parent_ref="u-gone", spec={}, spec_hash="h",
                           spec_diff={}, hypothesis="x", evidence=[], created_utc="2026-11-01T00:00:00Z")
        with self.assertRaises(user_store.StoreError):
            user_scope.apply_promotion(bad, {"p_adj": 0.01})


if __name__ == "__main__":
    unittest.main()
