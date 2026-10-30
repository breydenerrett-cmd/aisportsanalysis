#!/usr/bin/env python3
"""Where does the time go when a LineHound owner sends a member hound to training?  (stdlib only, no network, no model.)

    python3 scripts/train_timing.py                       # every stage, 3 timed runs + 1 profiled run each
    python3 scripts/train_timing.py --only diagnose,propose --runs 3
    python3 scripts/train_timing.py --list
    python3 scripts/train_timing.py --json out.json       # machine-readable copy of the table

WHAT IT DOES. It builds the fixture the repo's own tests build (a temp app database and ledger, an owner, a member hound like
HOCKEYCHIEF that bets NHL + TENNIS + MLB, about 25 settled bets as ledger rows) and then calls each stage's FUNCTION directly,
the way the API routes in api/hounds_interact.py do:

    diagnose  POST /hounds/{id}/train/diagnose   training.read_step(stage="diagnose")   the live coach (real schedule + captured odds)
    assess    POST /hounds/{id}/train/assess     training.read_step(stage="assess")     coach_ai.assess with a router that answers instantly
    propose   POST /hounds/{id}/train/propose    training.review(...)                   retune.live_board_fn: the whole board replayed per variant
    rebuild   POST /hounds/{id}/train/rebuild    training_plans.full_rebuild(...)       a fake SDK client; the rehearsals are fake, then REAL

THE MODEL IS NEVER CALLED. A fake router / fake SDK client stands in and returns at once; every call it receives is counted. The model
time is therefore NOT in any wall number printed here: add (serial calls x per-call latency) yourself (see --haiku-s, default 3 s).
Nothing reads an API key or the environment: the keys passed are the literal fake strings below.

WHAT IS REAL. The odds, schedule, box-score and results stores under data/ in THIS checkout are read for real (that is the realistic
cost of the board replay and of the rehearsals). The hound, its ledger rows and the app database are temporary and thrown away.
Every file the code opens under data/ is recorded (path, size, number of opens) by an open() wrapper, so the report says which stores
each stage touched.

COLD vs WARM. Each timed run starts with the process caches cleared (the coach's diagnosis cache, ask_eval's 60 s slate cache, the
drill's 30 min cache), because the owner's click that matters is the first one. Stages marked "warm" prime the earlier steps outside
the timed region (the page calls diagnose, then assess, then propose, so propose normally finds both cached). The OS file cache is NOT
cleared, so run 1 can be slower than runs 2 and 3; every run is printed. A fourth, profiled run (cProfile, which inflates wall time)
supplies the top-10 cumulative list and the top-5 self-time list; the wall numbers come from the un-profiled runs.
"""

from __future__ import annotations

import argparse
import builtins
import cProfile
import io
import json
import logging
import os
import pstats
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.appstate import users as users_store                                            # noqa: E402
from src.hounds import stats, user_engine, user_spec, user_store                          # noqa: E402
from src.hounds.interact import (ask_eval, coach as coach_mod, common, diagnosis_live, drill, loss_why, rebuild_ai,   # noqa: E402
                                 rebuild_budget as budget, retune, training, training_plans as plans)
from tests._hounds_rites_fixtures import rows_for                                          # noqa: E402
from tests.test_training_plans import FakeClient, angle_of, stage_of                       # noqa: E402

NOW = datetime(2026, 10, 29, 21, 30, tzinfo=timezone.utc)      # a day the checked-in odds store has games for
FAKE_KEY = "sk-ant-test-FAKE-NOT-A-KEY"                          # a literal; no environment variable is ever read
ENV = {"ANTHROPIC_API_KEY": FAKE_KEY}

# ---------------------------------------------------------------------------------------------------------------
# the fixture: HOCKEYCHIEF, 4 rules over NHL / TENNIS / MLB, 25 settled bets
# ---------------------------------------------------------------------------------------------------------------

RULES = [
    {"sports": ["NHL"], "markets": ["moneyline"], "side": "either", "price_min": -150, "price_max": 250, "min_books": 3},
    {"sports": ["NHL"], "markets": ["total"], "side": "either", "price_min": -130, "price_max": 120, "min_books": 3},
    {"sports": ["TENNIS"], "markets": ["moneyline"], "side": "either", "price_min": -150, "price_max": 200, "min_books": 3},
    {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": -150, "price_max": 250, "min_books": 3},
]


def _bets(kind: str = "weak") -> list:
    """25 settled bets. ``even``: NHL 9 (the core, a weak 2-7), MLB 8, TENNIS 8, nothing outside the core clears the evidence bar, so the
    proposal is "keep going". ``weak``: NHL 6, MLB 6, TENNIS 13 at 2-11, a real non-core weak spot, so the proposal has changes to count."""
    plan: list = []

    def add(sport, market, rule, rows, line=None):
        for result, side, price in rows:
            plan.append((1, dict(result=result, sport=sport, market=market, side=side, price=price, line=line, rule_index=rule)))
    if kind == "even":
        add("NHL", "moneyline", 0, [("WIN", "away", 140), ("LOSS", "away", 150), ("LOSS", "home", -110), ("LOSS", "away", 160),
                                    ("WIN", "home", 120), ("LOSS", "away", 135)])
        add("NHL", "total", 1, [("LOSS", "over", -110), ("LOSS", "over", -110), ("LOSS", "under", -110)], line=6.0)
        add("MLB", "moneyline", 3, [("WIN", "home", -120), ("WIN", "away", 130), ("LOSS", "away", 150), ("WIN", "home", 105),
                                    ("WIN", "away", 170), ("LOSS", "home", -105), ("WIN", "home", 110), ("LOSS", "away", 140)])
        add("TENNIS", "moneyline", 2, [("WIN", "home", -130), ("WIN", "away", 110), ("LOSS", "away", 140), ("WIN", "home", -115),
                                       ("WIN", "away", 125), ("LOSS", "home", -140), ("WIN", "home", -110), ("LOSS", "away", 160)])
    else:
        add("NHL", "moneyline", 0, [("WIN", "away", 140), ("LOSS", "away", 150), ("LOSS", "home", -110), ("WIN", "home", 120)])
        add("NHL", "total", 1, [("LOSS", "over", -110), ("WIN", "under", -110)], line=6.0)
        add("MLB", "moneyline", 3, [("WIN", "home", -120), ("WIN", "away", 130), ("LOSS", "away", 150), ("WIN", "home", 105),
                                    ("WIN", "away", 170), ("LOSS", "home", -105)])
        add("TENNIS", "moneyline", 2, [("WIN", "home", -130), ("WIN", "away", 110)] +
            [("LOSS", "away", 140), ("LOSS", "home", -115), ("LOSS", "away", 125), ("LOSS", "home", -140), ("LOSS", "away", 160),
             ("LOSS", "home", -110), ("LOSS", "away", 130), ("LOSS", "away", 150), ("LOSS", "home", -120), ("LOSS", "away", 135),
             ("LOSS", "away", 145)])
    return plan


class Fixture:
    """What tests/_hounds_rites_fixtures.RitesCase builds, without unittest: temp app database + ledger, an owner, one hound."""

    def __init__(self, kind: str = "weak"):
        self.kind = kind
        self._tmp = tempfile.TemporaryDirectory(prefix="train_timing_")
        tmp = Path(self._tmp.name)
        self.dir = tmp
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        self._patches = [
            mock.patch.object(users_store, "db_path", lambda: self.db),
            mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
            mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
            mock.patch.object(stats, "peek_book", lambda: None),
            mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming")),
            mock.patch.object(common, "now_utc", lambda: NOW),
            # the rebuild's Caller writes each call's cost to the router's usage store (a real file); a fake call must not
            mock.patch.object(budget, "log_usage_to_router", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)
        spec = user_spec.validate_spec({"version": 2, "name": "HOCKEYCHIEF", "rules": [dict(r) for r in RULES]})
        self.hound_row = user_store.create_hound(self.owner.id, spec)
        self.plan = _bets(kind)
        self.rows = rows_for(self.hound_row["id"], self.plan)
        self.dog = common.resolve(self.hound_row["id"])

    def close(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


# ---------------------------------------------------------------------------------------------------------------
# fakes: nothing here waits, calls out or reads a key; every call is counted
# ---------------------------------------------------------------------------------------------------------------

class FakeAnswer:
    def __init__(self, output, cost=0.0004):
        self.output, self.ok, self.reason, self.cost_usd, self.model, self.latency_ms, self.attempts = output, True, "", cost, "claude-haiku-5-5", 0, []


class FakeRouter:
    """Stands in for ``src.ai.router.Router`` for the coach's one assessment call: it reads the table it is sent and answers with the
    two top-ranked factors (what tests/test_hounds_coach.good_reply does), instantly (or after ``latency_s``)."""

    def __init__(self, latency_s: float = 0.0):
        self.calls: list = []
        self.latency_s = latency_s

    def ask(self, system, user, **kw):
        self.calls.append(time.perf_counter())
        if self.latency_s:
            time.sleep(self.latency_s)
        payload = json.loads(user)
        ranked = payload["ranked"]
        first, second = ranked[0], ranked[1] if len(ranked) > 1 else ranked[0]
        return FakeAnswer({"summary": "The record is short, and the weakest parts are on the road.",
                           "reasons": [{"factors": [first], "text": "This cut lost the most units and is the first place to look.", "confidence": "high"},
                                       {"factors": [second], "text": "This cut also lost units.", "confidence": "medium"}],
                           "try": [c["cid"] for c in payload["candidates"][:2]]})


class CountingClient(FakeClient):
    """tests' FakeClient (the ``anthropic`` SDK stand-in) that records each call's stage, thread and (optionally) waits ``latency_s``."""

    def __init__(self, responder, latency_s: float = 0.0):
        super().__init__(responder)
        self.latency_s = latency_s
        self.log: list = []
        self._lock = threading.Lock()

    def stream(self, **kw):
        if self.latency_s:
            time.sleep(self.latency_s)
        with self._lock:
            self.log.append((stage_of(kw), threading.current_thread().name))
        return super().stream(**kw)


def _candidate(i: int, current_rules: list) -> dict:
    """A rebuilt rule set that keeps the NHL core, differs from the current one by several areas, and differs from its siblings."""
    nhl_ml = dict(current_rules[0], price_min=100 + 10 * i, price_max=260 + 10 * i,
                  when={"op": "all", "items": [{"id": "role", "value": "underdog"}]})
    nhl_total = dict(current_rules[1], side="under", price_min=-125 + i, price_max=105 + i)
    tennis = dict(current_rules[2], price_min=-140 + 4 * i, price_max=190 + 5 * i, min_books=4)
    extra = {"sports": ["MLB"], "markets": ["total"], "side": "under", "price_min": -120, "price_max": 100 + 5 * i, "min_books": 3}
    rules = [nhl_ml, nhl_total, tennis] + ([extra] if i % 2 else [dict(current_rules[3], price_min=100, price_max=200 + 5 * i)])
    return {"version": 2, "rules": rules, "max_bets_per_day": 2 + (i % 3), "stake_units": 1.0, "lock_minutes": (60, 120, 180)[i % 3],
            "rank_by": "earliest_lock"}


def rebuild_responder():
    names = [a[0] for a in rebuild_ai.ANGLES]

    def responder(kw):
        stage = stage_of(kw)
        if stage == "angle":
            i = names.index(angle_of(kw)) if angle_of(kw) in names else 0
            return {"summary": f"{angle_of(kw)} angle rebuild", "spec_json": json.dumps(_candidate(i, RULES))}
        if stage == "analyst":
            return {"chosen": "merge", "spec_json": json.dumps(_candidate(7, RULES)), "reasons": ["More rules cover more of the games"],
                    "cut": ["one rule"], "added": ["four rules"], "weak_spots": ["the sample is small"]}
        return {"lines": ["It now looks at more kinds of games than before.", "The rules it had were losing in the rehearsal.",
                          "In the rehearsal of the last 30 days the updated rules had 30 graded bets."],
                "changed": ["It bets up to 3 a day now"]}
    return responder


def fake_replay(spec, days, now):
    n = len(spec.get("rules") or [1])
    return {"record": {"graded": 30, "wins": 15, "losses": 15, "pushes": 0, "bets": 30}, "units_average_price": 3.0 * n - 2.0, "days": days, "picks": []}


# ---------------------------------------------------------------------------------------------------------------
# I/O trace: which files under data/ did the stage open, and how big are they
# ---------------------------------------------------------------------------------------------------------------

class IoTrace:
    def __init__(self):
        self.seen: dict = {}
        self._lock = threading.Lock()
        self._orig_builtin, self._orig_io = builtins.open, io.open

    def _note(self, file):
        try:
            path = os.fspath(file)
        except TypeError:
            return
        if not isinstance(path, str):
            return
        norm = os.path.abspath(path)
        data = str(ROOT / "data")
        if not norm.startswith(data):
            return
        rel = os.path.relpath(norm, str(ROOT)).replace("\\", "/")
        with self._lock:
            hit = self.seen.get(rel)
            if hit is None:
                try:
                    size = os.path.getsize(norm)
                except OSError:
                    size = None
                hit = self.seen[rel] = {"opens": 0, "bytes": size}
            hit["opens"] += 1

    def __enter__(self):
        trace = self

        def traced_builtin(file, *a, **k):
            trace._note(file)
            return trace._orig_builtin(file, *a, **k)

        def traced_io(file, *a, **k):
            trace._note(file)
            return trace._orig_io(file, *a, **k)
        builtins.open, io.open = traced_builtin, traced_io
        return self

    def __exit__(self, *exc):
        builtins.open, io.open = self._orig_builtin, self._orig_io

    def summary(self) -> list:
        rows = [(rel, v["opens"], v["bytes"]) for rel, v in self.seen.items()]
        rows.sort(key=lambda r: -(r[2] or 0))
        return rows


class BoardProbe:
    """Counts (and times) every uncached board evaluation: ``retune.board_counts`` is one full ``ask_eval.earlier_user`` run."""

    def __init__(self):
        self.seconds: list = []

    def __enter__(self):
        orig, probe = retune.board_counts, self

        def counted(*a, **k):
            t = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                probe.seconds.append(time.perf_counter() - t)
        self._patch = mock.patch.object(retune, "board_counts", counted)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class DownRouter:
    """A router that is 'down': the tweak's mapping falls back to the rules engine, after the one model call it would have made."""

    def __init__(self):
        self.calls: list = []

    def ask(self, system, user, **kw):
        self.calls.append(time.perf_counter())
        answer = FakeAnswer(None)
        answer.ok, answer.reason = False, "fake router: down"
        return answer


# ---------------------------------------------------------------------------------------------------------------
# the stages. Each is  setup(fx) -> state  (untimed)  and  run(fx, state) -> info dict  (timed).
# ``info`` carries the model-call counts the fakes saw.
# ---------------------------------------------------------------------------------------------------------------

def _cold():
    """The first click: no coach cache (a new Coach per run), no slate cache, no drill cache."""
    ask_eval.clear_cache()
    drill.clear_cache()
    try:
        from src.hounds.interact import fire
        fire.clear_cache()
    except Exception:  # noqa: BLE001
        pass


def _live_coach(router=None):
    return coach_mod.Coach(context_factory=diagnosis_live.live_context, router=router)


def _read_step(fx, coach, stage):
    return training.read_step(fx.dog, fx.owner.id, coach, stage=stage, now=NOW, rows=fx.rows, db=fx.db)


def _review(fx, coach, board_fn):
    return training.review(fx.dog, fx.owner.id, coach, board_fn=board_fn, hindsight_fn=loss_why.live_hindsight,
                           now=NOW, rows=fx.rows, db=fx.db)


def stage_diagnose(fx):
    _cold()
    return {"coach": _live_coach(FakeRouter())}


def run_diagnose(fx, st):
    out = _read_step(fx, st["coach"], "diagnose")
    return {"model_calls": 0, "rows": len(out["diagnosis"]["rows"])}


def stage_diagnose_nostores(fx):
    _cold()
    return {"coach": coach_mod.Coach(rules_only=True)}


def run_diagnose_nostores(fx, st):
    out = _read_step(fx, st["coach"], "diagnose")
    return {"model_calls": 0, "rows": len(out["diagnosis"]["rows"])}


def stage_assess_warm(fx):
    _cold()
    router = FakeRouter()
    coach = _live_coach(router)
    _read_step(fx, coach, "diagnose")                                    # what the page does first; its cache is what assess finds
    router.calls.clear()
    return {"coach": coach, "router": router}


def run_assess_warm(fx, st):
    out = _read_step(fx, st["coach"], "assess")
    return {"model_calls": len(st["router"].calls), "source": out["coach"]["source"]}


def stage_assess_cold(fx):
    _cold()
    router = FakeRouter()
    return {"coach": _live_coach(router), "router": router}


def run_assess_cold(fx, st):
    out = _read_step(fx, st["coach"], "assess")
    return {"model_calls": len(st["router"].calls), "source": out["coach"]["source"]}


def stage_propose_warm(fx):
    _cold()
    router = FakeRouter()
    coach = _live_coach(router)
    _read_step(fx, coach, "diagnose")
    _read_step(fx, coach, "assess")                                      # diagnose + assess are cached, as after the page's first two calls
    router.calls.clear()
    ask_eval.clear_cache()                                               # the slate cache is NOT warm on the owner's first propose
    return {"coach": coach, "router": router, "board_fn": retune.live_board_fn(fx.dog)}


def run_propose_warm(fx, st):
    with BoardProbe() as probe:
        out = _review(fx, st["coach"], st["board_fn"])
    return _propose_info(st, out, probe)


def _propose_info(st, out, probe) -> dict:
    today = out.get("today") or {}
    secs = probe.seconds
    return {"model_calls": len(st["router"].calls), "mode": out["mode"], "note": out.get("note"), "changes": len(out["changes"]),
            "board_evals": len(secs), "board_eval_s": round(sum(secs), 2), "first_eval_s": round(secs[0], 2) if secs else None,
            "today": (today.get("games"), today.get("before"), today.get("after"))}


def stage_tweak(fx):
    _cold()
    training._tweaks_clear(fx.hound_row["id"])           # noqa: SLF001 -- the process counts tweak rounds per hound and rule (3 max); every run is round 1
    router = DownRouter()
    coach = _live_coach(router)
    _read_step(fx, coach, "diagnose")
    _read_step(fx, coach, "assess")
    router.calls.clear()
    ask_eval.clear_cache()
    return {"coach": coach, "router": router, "board_fn": retune.live_board_fn(fx.dog)}


def run_tweak(fx, st):
    with BoardProbe() as probe:
        out = training.review(fx.dog, fx.owner.id, st["coach"], tweak="please drop tennis", round_no=0, board_fn=st["board_fn"],
                              hindsight_fn=loss_why.live_hindsight, router=st["router"], env={}, now=NOW, rows=fx.rows, db=fx.db)
    return _propose_info(st, out, probe)


def stage_propose_slate_warm(fx):
    st = stage_propose_warm(fx)
    _review(fx, st["coach"], st["board_fn"])                             # untimed first propose: builds the 60 s slate cache
    st["router"].calls.clear()
    st["board_fn"] = retune.live_board_fn(fx.dog)                        # a new request has a new per-request memo, the slate cache stays
    return st


def stage_propose_cold(fx):
    _cold()
    router = FakeRouter()
    return {"coach": _live_coach(router), "router": router, "board_fn": retune.live_board_fn(fx.dog)}


def _board_evals(board_fn) -> int:
    try:
        return len(board_fn.__closure__[0].cell_contents)             # the memo dict inside live_board_fn
    except Exception:  # noqa: BLE001
        return -1


def stage_rebuild(replay):
    def setup(fx):
        _cold()
        client = CountingClient(rebuild_responder())
        tmp = Path(tempfile.mkdtemp(prefix="rebuild_", dir=fx.dir))
        clock = [datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)]
        return {"client": client, "ledger": budget.RebuildLedger(tmp / "rebuilds.jsonl", clock=lambda: clock[0]),
                "store": plans.PlanStore(tmp / "plans"), "replays": [], "replay": replay}
    return setup


def run_rebuild(fx, st):
    counter, batches = st["replays"], []
    base_replay = st["replay"] or plans.default_replay

    def counting_replay(spec, days, now):
        t = time.perf_counter()
        try:
            return base_replay(spec, days, now)
        finally:
            counter.append(time.perf_counter() - t)

    def counting_many(specs, days, now):
        t = time.perf_counter()
        try:
            return plans.default_replay_many(specs, days, now)
        finally:
            counter.append(time.perf_counter() - t)
            batches.append(len(specs))
    # the REAL stage is production's wiring: the single drill for the rules it has now and for the analyst's merge, and the batch drill for the
    # surviving candidates (``full_rebuild`` falls back to one drill each only when no batch rehearsal is passed, as the fake stage does)
    many = counting_many if st["replay"] is None else None
    card = plans.full_rebuild(fx.dog, fx.owner.id, paid=True, now=NOW, rows=fx.rows, db=fx.db, replay_fn=counting_replay, replay_many_fn=many,
                              env=ENV, client=st["client"], ledger=st["ledger"], store=st["store"], router_spend=lambda: (0.0, 5.0))
    stages = [s for s, _t in st["client"].log]
    return {"model_calls": len(stages), "calls_by_stage": {s: stages.count(s) for s in sorted(set(stages))},
            "rehearsals": len(counter), "batch_sizes": batches, "rehearsal_seconds": [round(x, 2) for x in counter], "found": card.get("found")}


STAGES = {
    # name: (label, route, setup, run)
    "diagnose": ("diagnose", "POST train/diagnose", stage_diagnose, run_diagnose),
    "diagnose_nostores": ("diagnose, stores off (compute only)", "(same, no live context)", stage_diagnose_nostores, run_diagnose_nostores),
    "assess_warm": ("assess, diagnosis cached", "POST train/assess", stage_assess_warm, run_assess_warm),
    "assess_cold": ("assess, cache miss (diagnose + assess)", "POST train/assess", stage_assess_cold, run_assess_cold),
    "propose": ("propose, diagnosis+read cached, slate cold", "POST train/propose", stage_propose_warm, run_propose_warm),
    "propose_slate_warm": ("propose, slate cache warm (2nd click)", "POST train/propose", stage_propose_slate_warm, run_propose_warm),
    "propose_cold": ("propose, everything cold", "POST train/propose", stage_propose_cold, run_propose_warm),
    "tweak": ("propose with a tweak (round 1), slate cold", "POST train/propose {tweak}", stage_tweak, run_tweak),
    "rebuild_fake": ("rebuild, fake rehearsals", "POST train/rebuild", stage_rebuild(fake_replay), run_rebuild),
    "rebuild_real": ("rebuild, REAL drill rehearsals", "POST train/rebuild", stage_rebuild(None), run_rebuild),
}
DEFAULT_ORDER = ["diagnose", "diagnose_nostores", "assess_warm", "assess_cold", "propose", "propose_slate_warm", "propose_cold",
                 "tweak", "rebuild_fake", "rebuild_real"]


# ---------------------------------------------------------------------------------------------------------------
# the runner
# ---------------------------------------------------------------------------------------------------------------

def _top(profile: cProfile.Profile, sort: str, n: int) -> list:
    stats_ = pstats.Stats(profile)
    rows = []
    for (path, line, func), (cc, nc, tt, ct, _callers) in stats_.stats.items():
        try:
            rel = os.path.relpath(path, str(ROOT)).replace("\\", "/") if os.path.isabs(path) else path
        except ValueError:
            rel = path
        if rel.startswith(".."):
            rel = "<stdlib>/" + os.path.basename(path)
        rows.append({"where": f"{rel}:{line}({func})", "calls": nc, "self_s": round(tt, 3), "cum_s": round(ct, 3)})
    rows.sort(key=lambda r: -r["cum_s" if sort == "cum" else "self_s"])
    return rows[:n]


def measure(name: str, fx: Fixture, runs: int, profiled: bool) -> dict:
    label, route, setup, run = STAGES[name]
    walls, info, trace_rows = [], {}, []
    for i in range(runs):
        state = setup(fx)
        t = time.perf_counter()
        with IoTrace() as trace:
            info = run(fx, state)
        walls.append(time.perf_counter() - t)
        if i == 0:
            trace_rows = trace.summary()
        print(f"  {name:20s} run {i + 1}: {walls[-1]:8.2f} s   {info}", flush=True)
    result = {"stage": name, "label": label, "route": route, "walls": [round(w, 3) for w in walls],
              "median_s": round(statistics.median(walls), 3), "info": info, "files": trace_rows}
    if profiled:
        state = setup(fx)
        prof = cProfile.Profile()
        t = time.perf_counter()
        prof.enable()
        try:
            run(fx, state)
        finally:
            prof.disable()
        result["profiled_wall_s"] = round(time.perf_counter() - t, 3)
        result["top_cum"] = _top(prof, "cum", 10)
        result["top_self"] = _top(prof, "self", 5)
        print(f"  {name:20s} profiled: {result['profiled_wall_s']:.2f} s (cProfile overhead included)", flush=True)
    return result


def structure_probe(fx: Fixture, latency_s: float) -> dict:
    """Serial depth of the model calls, measured: give every fake model call ``latency_s`` and see how much wall time that adds.
    ``added / latency_s`` is the number of calls the request waits for one after another (concurrent calls count once)."""
    out = {}
    _cold()
    router = FakeRouter()
    coach = _live_coach(router)
    _read_step(fx, coach, "diagnose")
    t = time.perf_counter()
    _read_step(fx, coach, "assess")
    base = time.perf_counter() - t
    out["assess"] = {"calls": len(router.calls), "wall_no_latency_s": round(base, 3)}
    for label, lat in (("no latency", 0.0), ("with latency", latency_s)):
        _cold()
        st = stage_rebuild(fake_replay)(fx)
        st["client"].latency_s = lat
        t = time.perf_counter()
        run_rebuild(fx, st)
        out[f"rebuild fake rehearsals, {label}"] = round(time.perf_counter() - t, 3)
        out[f"rebuild calls, {label}"] = len(st["client"].log)
    added = out["rebuild fake rehearsals, with latency"] - out["rebuild fake rehearsals, no latency"]
    out["rebuild serial depth (added / latency)"] = round(added / latency_s, 1)
    out["latency_s"] = latency_s
    return out


def sizes() -> list:
    """The stores the stages can read, with sizes (the checked-in copy of data/ in this checkout)."""
    names = ["data/processed/odds_multibook.jsonl", "data/processed/odds_snapshots.jsonl", "data/processed/boxscores_2026.jsonl",
             "data/processed/weather_forecast.jsonl", "data/processed/event_game_map.jsonl", "data/historical/mlb_results.csv"]
    out = []
    for rel in names:
        p = ROOT / rel
        out.append((rel, p.stat().st_size if p.exists() else None))
    arch = ROOT / "data" / "processed" / "archive" / "odds_multibook"
    if arch.exists():
        files = list(arch.glob("*"))
        out.append(("data/processed/archive/odds_multibook/ (%d segments, gz)" % len(files), sum(f.stat().st_size for f in files)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", help="comma list of stages (see --list)")
    ap.add_argument("--runs", type=int, default=3, help="un-profiled timed runs per stage (default 3)")
    ap.add_argument("--no-profile", action="store_true", help="skip the cProfile run")
    ap.add_argument("--fixture", choices=("even", "weak"), default="weak",
                    help="even: nothing outside the core clears the evidence bar (proposal = keep going); weak: TENNIS is a real weak spot")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", help="write the results here")
    ap.add_argument("--haiku-s", type=float, default=3.0, help="assumed seconds per Haiku call, for the estimated-total column")
    ap.add_argument("--probe-latency-s", type=float, default=0.25, help="per-call latency the serial-depth probe injects")
    args = ap.parse_args(argv)
    if args.list:
        for k in DEFAULT_ORDER:
            print(f"{k:20s} {STAGES[k][0]}")
        return 0
    logging.disable(logging.WARNING)           # the diagnosis logs one warning per bet it cannot find a schedule for; keep stdout readable
    chosen = [s.strip() for s in args.only.split(",")] if args.only else DEFAULT_ORDER
    for s in chosen:
        if s not in STAGES:
            ap.error(f"unknown stage {s!r}; --list shows them")
    print(f"fixture: HOCKEYCHIEF, {len(RULES)} rules (NHL x2, TENNIS, MLB), {len(_bets(args.fixture))} settled bets ({args.fixture} fixture), now={NOW.isoformat()}")
    for rel, size in sizes():
        print(f"  store {rel}: {size if size is not None else 'missing'} bytes")
    fx = Fixture(args.fixture)
    results = []
    try:
        for name in chosen:
            print(f"[{name}] {STAGES[name][0]}", flush=True)
            results.append(measure(name, fx, args.runs, not args.no_profile))
        probe = None
        if not args.only or "rebuild_fake" in chosen:
            print("[serial-depth probe]", flush=True)
            probe = structure_probe(fx, args.probe_latency_s)
            print(f"  {probe}")
    finally:
        fx.close()
    print("\n=== summary (median of %d un-profiled runs; model time NOT included) ===" % args.runs)
    print(f"{'stage':45s} {'median s':>9s}  runs")
    for r in results:
        print(f"{r['label']:45s} {r['median_s']:9.2f}  {r['walls']}   {r['info']}")
    for r in results:
        print(f"\n--- {r['stage']}: files opened under data/ (first run) ---")
        for rel, opens, size in r["files"][:12]:
            print(f"  {rel}  opens={opens}  bytes={size}")
        if "top_cum" in r:
            print(f"--- {r['stage']}: top 10 cumulative (profiled run, {r['profiled_wall_s']} s) ---")
            for row in r["top_cum"]:
                print(f"  {row['cum_s']:8.3f} cum {row['self_s']:8.3f} self {row['calls']:>8} calls  {row['where']}")
            print(f"--- {r['stage']}: top 5 self time ---")
            for row in r["top_self"]:
                print(f"  {row['self_s']:8.3f} self {row['cum_s']:8.3f} cum {row['calls']:>8} calls  {row['where']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"fixture": args.fixture, "fixture_now": NOW.isoformat(), "sizes": sizes(), "results": results, "probe": probe,
                                               "haiku_s": args.haiku_s}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
