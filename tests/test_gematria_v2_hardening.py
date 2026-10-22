"""The adversarial check of the Gematria v2 build (2026-10-22, before any v2 pick existed). Each class pins one finding.

  * AN AHEAD READ CUTS ITS HISTORY AT ITS OWN INSTANT. Unleash, the preview and the analysis stream weigh a game before its lock on the
    board standing now; the history was still cut at ``lock - FINISH_LAG``. Live that is harmless (nothing later exists), but a replay
    of a past morning (research/rabbitszn/v2_pick_rate.py, the calibration tool) could count a game that finished after the read.
  * THE -200 CAP AND ONE SIDE PER GAME HOLD ON THE UNLEASH PATH TOO, not only at the lock; and a lock-time pass after an Unleash cannot
    add the other side of a game Unleash already took.
  * THE ORDER THAT CHOSE A BET IS ON THE ROW. Unleash ranks the day by z, the lock-time runner goes earliest first; same rules hash,
    different selection, so a ranked bet says ``day_order: "z"``.
  * THE ANALYSIS IS BOUNDED AND NEVER PROMISES MORE THAN THE HOUND CAN PLACE: today's slate only, at most ``MAX_WEIGHED`` games, the
    hound's own daily limit in its own placing order, and a name with no Latin letter no longer takes the whole payload down.
  * THE COMPACT DAY ADDS UP on every shape of day: none, all started, a huge slate, unicode and markup names, an inconsistent caller.
"""

from __future__ import annotations

import json
import random
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from src.hounds import user_gematria
from src.hounds.gematria import decision as decision_mod
from src.hounds.gematria import history, rules as rules_mod, runtime as rt
from src.hounds.interact import common, fire, gematria_analysis as ga, unleash
from src.hounds.pack import base
from src.research import gematria as g
from tests.test_ai_hounds import allsports_rows, allsports_stores
from tests.test_gematria_hound import NBA_FACTS, StubSource, season_games
from tests.test_gematria_v2 import BIG_DAY, NOW, StubWeigher, bet, weigh_day

UTC = timezone.utc


# ---------------------------------------------------------------------------------------------------
# (b) point in time
# ---------------------------------------------------------------------------------------------------

class AnAheadReadCutsItsHistoryAtItsOwnInstant(unittest.TestCase):
    def setUp(self):
        self.st = allsports_stores(allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=-120, away_ml=100))
        self.ctx = base.build_context(self.st, "nba1")

    def runtime(self, games):
        src = StubSource(games)
        return rt.GematriaRuntime(rules=rules_mod.load("rules_v2.json"), facts=NBA_FACTS, source=src, ledger=None), src

    def test_the_cut_is_the_read_instant_before_the_lock_and_the_lock_after_it(self):
        run, src = self.runtime(season_games())
        board = base.lock_board(self.st, self.ctx)
        early = self.ctx.lock - timedelta(hours=3)
        run.weigh(self.ctx, board, known_at=early)
        run.weigh(self.ctx, board)
        run.weigh(self.ctx, board, known_at=self.ctx.lock + timedelta(minutes=5))
        self.assertEqual(src.calls, [early - history.FINISH_LAG, self.ctx.lock - history.FINISH_LAG, self.ctx.lock - history.FINISH_LAG])

    def test_a_game_that_finished_after_the_read_changes_nothing(self):
        early = self.ctx.lock - timedelta(hours=24)       # a morning-before read
        h, a = g.normalize("Boston Celtics"), g.normalize("New York Knicks")
        # started inside [early - lag, lock - lag): over by the lock, NOT over by the read instant
        when = self.ctx.lock - timedelta(hours=20)
        late = [history.Game(when, when.date().isoformat(), h, a, 120, 90, regular=True)]
        board = base.lock_board(self.st, self.ctx)
        plain, _ = self.runtime(season_games())
        leaky, _ = self.runtime(season_games() + late)
        one = plain.weigh(self.ctx, board, known_at=early)
        two = leaky.weigh(self.ctx, board, known_at=early)
        self.assertEqual(one.block and one.block["inputs_hash"], two.block and two.block["inputs_hash"])
        self.assertEqual((one.verdict.code, one.verdict.side), (two.verdict.code, two.verdict.side))
        # ...while at the lock the same game IS history (so the planted game is a real input, not a dud)
        self.assertEqual(plain.inputs(self.ctx, known_at=early).home.state, leaky.inputs(self.ctx, known_at=early).home.state)
        self.assertNotEqual(plain.inputs(self.ctx).home.state, leaky.inputs(self.ctx).home.state)

    def test_the_weigher_hands_its_read_instant_to_the_runtime(self):
        seen = []

        class Run:
            rules = rules_mod.load("rules_v2.json")

            def weigh(self, ctx, board, known_at=None):
                seen.append(known_at)
                return SimpleNamespace(verdict=None)

        w = user_gematria.Weigher({}, runtime=Run())
        with mock.patch.object(user_gematria.Weigher, "context", lambda self, eid: self_ctx), \
                mock.patch.object(base, "build_board", lambda *a, **k: {}), mock.patch.object(base, "lock_board", lambda *a, **k: {}), \
                mock.patch.object(user_gematria.Weigher, "stores", lambda self: SimpleNamespace(quotes_by_event={})):
            self_ctx = self.ctx
            w.weigh("nba1", as_of=self.ctx.lock - timedelta(hours=2))
            w.weigh("nba1", as_of=self.ctx.lock + timedelta(minutes=1))
            w.weigh("nba1")
        self.assertEqual(seen, [self.ctx.lock - timedelta(hours=2), None, None])


# ---------------------------------------------------------------------------------------------------
# (c) the cap, one side, and the order on the row, on the Unleash path
# ---------------------------------------------------------------------------------------------------

class TheCapAndOneSideOnTheUnleashPath(unittest.TestCase):
    def setUp(self):
        from tests.test_gematria_member_style import EngineCase
        self.case = EngineCase("run_engine")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def engine(self, now, decide=None, rows=None, **kw):
        from tests import test_gematria_member_style as M
        from src.hounds import user_engine
        factory = M.runtime_factory(rules=rules_mod.load("rules_v2.json"))
        patches = [mock.patch.object(user_gematria, "make_runtime", factory)]
        if decide is not None:
            patches.append(mock.patch.object(decision_mod, "decide", decide))
        for p in patches:
            p.start()
        try:
            return user_engine.run(M.DATE, [M.member()], rows if rows is not None else M.nba_rows(), ledger=self.case.ledger, now=now,
                                   mode="live", **kw)
        finally:
            for p in patches:
                p.stop()

    @staticmethod
    def forced(side, price=110):
        def decide(sig, board, rules, *, history_available, teams_known):
            v = decision_mod.Verdict("bet", "bet", "forced", side=side, price=price, margin=4.0, scores={"home": 1.0, "away": 5.0}, z=2.0)
            v.confidence = 2
            return v
        return decide

    def early(self):
        return datetime(2026, 10, 20, 21, 30, tzinfo=UTC)          # before the 22:15Z lock of the fixture game

    def test_a_minus_250_side_is_refused_when_unleashed_ahead(self):
        rows = allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=210, away_ml=-250,
                              spread=(-1.5, -110, -110), total=(221.5, -110, -110))
        out = self.engine(self.early(), decide=self.forced("away", price=-250), rows=rows, place_ahead=True)
        self.assertEqual(out["bets_written"], 0)
        self.assertEqual(out["skipped"].get("price_cap"), 1)
        self.assertEqual(self.case.bets(), [])

    def test_the_lock_pass_after_an_unleash_never_adds_the_other_side(self):
        first = self.engine(self.early(), decide=self.forced("away"), place_ahead=True)
        self.assertEqual(first["bets_written"], 1)
        lock_time = datetime(2026, 10, 20, 22, 20, tzinfo=UTC)
        again = self.engine(lock_time, decide=self.forced("home"))       # the numbers "flip" at the lock
        self.assertEqual(again["bets_written"], 0)
        rows = self.case.bets()
        self.assertEqual([(r["event_id"], r["side"]) for r in rows], [(rows[0]["event_id"], "away")])

    def test_a_ranked_bet_says_which_order_chose_it(self):
        self.engine(self.early(), decide=self.forced("away"), place_ahead=True)
        (row,) = self.case.bets()
        self.assertEqual(row["day_order"], "z")


class TheOrderStamp(unittest.TestCase):
    def test_only_a_ranked_candidate_carries_it(self):
        spec = {"sports": ["NBA"], "lock_minutes": 60}
        hound = {"id": "h-1", "created_at": "2026-10-22T10:00:00Z"}
        games = {eid: SimpleNamespace(sport="NBA", commence=NOW + timedelta(hours=6), away_team="A", home_team="H") for eid in ("a", "b")}
        with mock.patch.object(user_gematria, "_candidate", lambda game, ctx, board, weighed, runtime: {"row_extra": {}, "side": weighed.verdict.side}):
            for rules_file, ahead, want in (("rules_v2.json", True, "z"), ("rules_v2.json", False, None), ("rules_v1.json", True, None)):
                w = StubWeigher({"a": bet(1.5), "b": bet(2.5)}, rules_mod.load(rules_file))
                clock = (lambda: NOW) if ahead else (lambda: NOW + timedelta(hours=5, minutes=10))
                out = user_gematria.hound_candidates(hound, spec, games, "2026-10-22", mode="live", clock=clock, seen_ids=set(),
                                                     skipped=Counter(), considered={}, weigher=w, ahead=ahead)
                self.assertTrue(out, (rules_file, ahead))
                self.assertEqual({c[6]["row_extra"].get("day_order") for c in out}, {want}, (rules_file, ahead))


# ---------------------------------------------------------------------------------------------------
# (d) the analysis payload
# ---------------------------------------------------------------------------------------------------

class TheAnalysisIsBounded(unittest.TestCase):
    def setUp(self):
        self.rules = rules_mod.load("rules_v2.json")
        self.weighed = weigh_day(self.rules, matches=BIG_DAY)
        by_event = {c.event_id: (c, {}, w) for c, w, _r in self.weighed}

        class Stub:
            def __init__(self, games, runtime=None):
                self.games = games

            def weigh(self, event_id, as_of=None):
                return by_event[event_id]

        p = mock.patch.object(user_gematria, "Weigher", Stub)
        p.start()
        self.addCleanup(p.stop)
        self.now = min(c.lock for c, _w, _r in self.weighed) - timedelta(hours=2)
        self.games = {c.event_id: SimpleNamespace(sport="SOCCER", commence=c.start) for c, _w, _r in self.weighed}
        self.house = common.Dog(id="gematria", kind=common.KIND_OTHER, name="Gematria Hound", status="running", root_id="gematria")

    def member(self, per_day):
        from tests.test_gematria_member_style import gem_spec
        return common.Dog(id="u-gem", kind=common.KIND_USER, name="Numbers Pup",
                          hound={"id": "u-gem", "spec": gem_spec(sports=["SOCCER"], max_bets_per_day=per_day)})

    def build(self, dog, games=None, **kw):
        return ga.build(dog, now=self.now, games=games or self.games, runtime=SimpleNamespace(rules=self.rules), use_cache=False, **kw)

    def candidates(self):
        return [w for _c, w, _r in self.weighed if w.verdict.is_bet]

    def test_a_member_is_never_shown_more_picks_than_its_limit_and_in_unleashs_order(self):
        self.assertGreater(len(self.candidates()), 2, "the fixture must have more candidates than the limit")
        out = self.build(self.member(2))
        picks = [e for e in out["games"] if e["status"] == "bet"]
        self.assertEqual((out["limit_per_day"], out["ranked_by"], len(picks), out["picks_total"]), (2, "z", 2, 2))
        best = sorted((w.verdict.z for w in self.candidates()), reverse=True)[:2]
        self.assertEqual(sorted((e["z"] for e in picks), reverse=True), best)
        over = [e for e in out["games"] if e.get("over_limit")]
        self.assertTrue(over)
        for e in over:
            self.assertEqual(e["lines"][-1]["status"], "pass")
            self.assertIn("over its limit of 2 a day", e["lines"][-1]["text"])
            self.assertNotIn("Pick:", e["lines"][-1]["text"])
        self.assertEqual(out["candidates_total"], len(self.candidates()))

    def test_the_house_hound_follows_its_runner_earliest_first(self):
        out = self.build(self.house)
        self.assertEqual(out["ranked_by"], "start")
        self.assertEqual(out["picks_total"], min(len(self.candidates()), self.rules.decision.max_picks_per_day))
        earliest = sorted((c.start, c.event_id) for c, w, _r in self.weighed if w.verdict.is_bet)[:out["picks_total"]]
        self.assertEqual(sorted(e["event_id"] for e in out["games"] if e["status"] == "bet"), sorted(eid for _s, eid in earliest))

    def test_only_todays_slate_is_weighed(self):
        tomorrow = {f"t{i}": SimpleNamespace(sport="SOCCER", commence=self.now + timedelta(days=1, hours=i)) for i in range(5)}
        out = self.build(self.house, games={**self.games, **tomorrow})
        self.assertEqual(out["weighed"], len(self.weighed))
        self.assertFalse(any(e["event_id"].startswith("t") for e in out["games"]))

    def test_a_huge_slate_is_weighed_only_up_to_the_cap_earliest_first(self):
        with mock.patch.object(ga, "MAX_WEIGHED", 5):
            out = self.build(self.house)
        self.assertEqual((out["weighed"], out["unweighed"]), (5, len(self.weighed) - 5))
        first5 = {c.event_id for c in sorted((c for c, _w, _r in self.weighed), key=lambda c: (c.start, c.event_id))[:5]}
        self.assertTrue({e["event_id"] for e in out["games"]} <= first5)

    def test_no_games_today_is_an_empty_payload_not_an_error(self):
        out = self.build(self.house, games={"x": SimpleNamespace(sport="SOCCER", commence=self.now - timedelta(hours=1))})
        self.assertEqual((out["weighed"], out["shown"], out["games"], out["picks_total"]), (0, 0, [], 0))


class ANameWithNoLatinLetter(unittest.TestCase):
    def test_it_is_analysed_not_a_500(self):
        rules = rules_mod.load("rules_v2.json")
        ((ctx, w, run),) = weigh_day(rules, matches=[("张之臻", "Zhang Zhizhen")])
        entry = ga.game_entry(ctx, w, run)
        ciphers = [l for l in entry["lines"] if l["kind"] == "cipher"]
        self.assertIn({"kind": "cipher", "side": "away", "field": "name", "text": "张之臻: no letters the ciphers can count",
                       "values": {}}, ciphers)
        self.assertEqual(entry["lines"][-1]["kind"], "decision")
        json.dumps(entry)

    def test_markup_in_a_name_is_carried_as_plain_text(self):
        rules = rules_mod.load("rules_v2.json")
        ((ctx, w, run),) = weigh_day(rules, matches=[("<img src=x onerror=alert(1)>", "Chelsea & Co")])
        entry = ga.game_entry(ctx, w, run)
        self.assertEqual(entry["game"], "<img src=x onerror=alert(1)> @ Chelsea & Co")     # the page sets it as textContent


# ---------------------------------------------------------------------------------------------------
# (e) the compact day adds up
# ---------------------------------------------------------------------------------------------------

T0 = datetime(2026, 10, 22, 23, 0, tzinfo=UTC)          # 7 pm Eastern


def check_view(test, view, names):
    c = view["counts"]
    test.assertEqual(c["started"] + c["later"] + c["checked_now"], c["total"], c)
    listed = sum(len(g["games"]) + g["more"] for g in view["groups"])
    test.assertEqual(listed, c["total"], "the fold lists (or counts) every game of today exactly once")
    for name in names:
        test.assertNotIn(name, view.get("line", ""))
        test.assertNotIn(name, view["counts_line"])
    for g in view["groups"]:
        test.assertLessEqual(len(g["games"]), fire.MAX_LISTED)


class TheSlateViewAddsUp(unittest.TestCase):
    def test_no_games(self):
        v = fire.slate_view(T0, [], [])
        self.assertEqual((v["counts"]["total"], v["counts_line"], v["groups"], v["today_state"]), (0, "", [], "none"))

    def test_all_started(self):
        started = [(f"Away {i} @ Home {i}", T0 - timedelta(minutes=10 * i + 5)) for i in range(6)]
        v = fire.slate_view(T0, started, [])
        self.assertEqual(v["today_state"], "started")
        self.assertEqual(v["counts"], {"total": 6, "started": 6, "later": 0, "checked_now": 0})
        check_view(self, v, [g for g, _s in started])

    def test_a_huge_slate_with_unicode_names(self):
        upcoming = [(f"Atlético {i} @ 张之臻 {i}", T0 + timedelta(minutes=5 + i), T0 + timedelta(minutes=5 + i) - timedelta(minutes=60))
                    for i in range(150)]
        started = [(f"Mönchengladbach {i} @ <b>{i}</b>", T0 - timedelta(minutes=1 + i)) for i in range(120)]
        v = fire.slate_view(T0, started, upcoming)
        check_view(self, v, [g for g, _s in started] + [g for g, _s, _k in upcoming])
        self.assertEqual(v["counts"]["total"], 270)
        self.assertTrue(all(g["more"] > 0 for g in v["groups"]))

    def test_an_upcoming_game_that_already_started_is_counted_as_started(self):
        v = fire.slate_view(T0, [], [("A @ B", T0 - timedelta(minutes=30), T0 - timedelta(minutes=90)), ("C @ D", T0 + timedelta(hours=1), None)])
        self.assertEqual(v["counts"], {"total": 2, "started": 1, "later": 1, "checked_now": 0})

    def test_random_days_always_add_up(self):
        rnd = random.Random(20261022)
        for _ in range(400):
            now = T0 - timedelta(hours=rnd.randint(0, 20))
            started = [(f"S{i} @ X", now - timedelta(minutes=rnd.randint(1, 900))) for i in range(rnd.randint(0, 6))]
            upcoming = []
            for i in range(rnd.randint(0, 60)):
                s = now + timedelta(minutes=rnd.randint(-90, 2500))
                upcoming.append((f"U{i} @ Y", s, rnd.choice([None, s - timedelta(minutes=60)])))
            check_view(self, fire.slate_view(now, started, upcoming), [])


class TheUnleashDayBlockAddsUp(unittest.TestCase):
    def games(self, n_started, n_ahead, name=lambda i: (f"Away {i}", f"Home {i}")):
        out = {}
        for i in range(n_started + n_ahead):
            away, home = name(i)
            start = T0 - timedelta(minutes=i + 1) if i < n_started else T0 + timedelta(minutes=i)
            out[f"e{i}"] = SimpleNamespace(away_team=away, home_team=home, commence=start)
        return out

    def test_no_games(self):
        b = unleash.day_block({}, {}, T0)
        self.assertEqual((b["counts"]["total"], b["counts_line"], b["groups"]), (0, "", []))

    def test_all_started(self):
        b = unleash.day_block(self.games(5, 0), {}, T0)
        self.assertEqual(b["counts"], {"total": 5, "started": 5, "later": 0, "checked_now": 0})
        self.assertEqual(b["counts_line"], "5 games today · 5 started")
        check_view(self, b, [])

    def test_a_huge_slate_with_unicode_and_markup_names(self):
        b = unleash.day_block(self.games(90, 210, name=lambda i: (f"张之臻 {i}", f"<script>{i}</script>")), {}, T0)
        self.assertEqual(b["counts"]["total"], 300)
        check_view(self, b, ["张", "<script>"])
        self.assertEqual([g["more"] for g in b["groups"]], [90 - fire.MAX_LISTED, 210 - fire.MAX_LISTED])

    def test_a_game_with_no_start_is_left_out_of_every_part(self):
        g = self.games(1, 1)
        g["x"] = SimpleNamespace(away_team="N", home_team="M", commence=None)
        b = unleash.day_block(g, {}, T0)
        self.assertEqual(b["counts"]["total"], 2)
        check_view(self, b, [])


if __name__ == "__main__":
    unittest.main()
