"""The three halves of the Hounds feature agree: ledgers, stats, routes, scheduler, pages.

Each class pins one misalignment found when H1 (core + read API), H3 (user hounds) and H2 (pages) were
put together, with the story in its docstring. Nothing reads a live store: boards, results and the
app database are built here.

The scheduler, route-order and page-contract classes live further down this file.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.hounds import contract, ledgers, stats, user_defs, user_engine as eng
from src.hounds import user_settle as st
from src.hounds.ledgers import Sources
from tests._hounds_user_fixtures import (DATE, EVENT, T_LATE, T_LOCK, board_rows, hound,
                                         result_row, standard_rows, utc)

AT_LOCK = utc("2026-10-20T21:10:00Z")
NEXT_DAY = utc("2026-10-21T12:00:00Z")
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}

# Three books disagree: average of +100, +200, +150 (decimals 2, 3, 2.5) is +150, the best is +200.
# Six books, because the closing board needs the consensus floor (src.analysis.prices.MIN_BOOKS) to count.
SPREAD_OUT_LOCK = [("a", -130, 100), ("b", -150, 200), ("c", -140, 150),
                   ("d", -130, 100), ("e", -150, 200), ("f", -140, 150)]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def read_rows(path) -> list:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def user_row(h: dict, **over) -> dict:
    """A user_store-shaped hound row for a fixture hound."""
    row = {"id": h["id"], "owner_user_id": 7, "name": "Dog Days", "tagline": "Dogs bark",
           "spec": h["spec"], "spec_hash": h["spec_hash"], "status": "running",
           "retire_reason": None, "retired_at": None, "retired_by": None,
           "created_at": h["created_at"], "version_of": None, "root_id": h["id"], "version_no": 1,
           "copied_from": None, "coach_opt_in": False}
    row.update(over)
    return row


class World:
    """A temp world: the standard game's boards, a user ledger, and Sources pointing at them."""

    def __init__(self, root: Path, board=None):
        self.root = root
        self.multibook = root / "data" / "processed" / "odds_multibook.jsonl"
        write_jsonl(self.multibook, board if board is not None else standard_rows())
        self.ledger = str(root / "data" / "app" / "hounds_user_v1.jsonl")
        self.hounds = []

    def add_hound(self, hid="u-int1", **spec) -> dict:
        h = hound(hid, **spec)
        self.hounds.append(user_row(h))
        return h

    def bet(self, mode="live"):
        eng.run(DATE, [hound_for(r) for r in self.hounds], eng.load_rows(DATE, ["MLB"],
                multibook_path=str(self.multibook)), ledger=self.ledger, now=AT_LOCK,
                game_pk_index=INDEX, mode=mode)

    def settle(self, away=5, home=3):
        return st.settle(ledger=self.ledger, now=NEXT_DAY, close_fn=lambda b: None,
                         mlb_results={PK: result_row(PK, DATE, "BOS", "SEA", away, home)},
                         game_pk_index=INDEX)

    def sources(self) -> Sources:
        r = self.root
        return Sources(
            decisions=r / "evidence" / "decisions_v2.jsonl", wagers=r / "evidence" / "w.jsonl",
            accounts_dir=r / "data" / "paper_accounts", multibook=self.multibook,
            card_v2=None, house_hounds_cfg=r / "config" / "house_hounds.json",
            house_pack_cfg=r / "config" / "house_pack.json",
            pack_ledgers=(("user", Path(self.ledger)),),
            user_hounds=lambda: [user_defs.definition(h) for h in self.hounds],
            user_stamp=lambda: ("user_hounds", len(self.hounds)))


def hound_for(row: dict) -> dict:
    return {"id": row["id"], "spec": row["spec"], "spec_hash": row["spec_hash"],
            "created_at": row["created_at"]}


class UserLedgerIsReadByTheSharedStats(unittest.TestCase):
    """MISALIGNMENT 2. H3 computed its own CLV and verdict and named its prices ``price`` and
    ``best_price``; H1's reader looks for ``price_average`` / ``price_best`` and its referee is the
    only one allowed to speak. The user ledger now carries the contract's names and every public
    number about a user hound comes from stats.build."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self._tmp.name), board_rows(T_LOCK, moneyline=SPREAD_OUT_LOCK)
                       + board_rows(T_LATE, moneyline=SPREAD_OUT_LOCK))
        self.h = self.w.add_hound(price_min=100, price_max=300)

    def tearDown(self):
        self._tmp.cleanup()

    def summary(self, hid="u-int1"):
        return stats.build(self.w.sources()).hounds[hid]

    def test_units_average_price_is_the_headline_and_units_recorded_price_is_the_best_quote(self):
        self.w.bet()
        self.w.settle()
        s = self.summary().summary
        self.assertEqual(s.kind, "user")
        self.assertEqual((s.record.bets, s.record.wins), (1, 1))
        self.assertEqual(s.record.units_average_price, 1.5)    # won at the board average, +150
        self.assertEqual(s.record.units_recorded_price, 2.0)   # won at the best quote recorded, +200
        row = self.summary().bets[0]
        self.assertEqual((row.price_average, row.price, row.book), (150, 200, "b"))
        self.assertEqual((row.segment, row.who_decided), ("forward", "rule"))
        self.assertIn("board average", row.reason)

    def test_the_label_is_the_referees_not_the_engines(self):
        self.w.bet()
        self.w.settle()
        d = self.summary()
        # one measurable bet: the pre-registered referee says TOO EARLY whatever the result
        self.assertEqual(d.summary.verdict.label, "TOO EARLY")
        self.assertEqual(d.summary.clv.n, 1)
        self.assertGreater(d.summary.clv.mean_pts, 0)          # +200 recorded vs a +150 close
        self.assertTrue(d.summary.verified)
        self.assertEqual(d.summary.name, "Dog Days")
        self.assertTrue(d.summary.owner_display.startswith("Handler "))

    def test_the_engines_own_clv_column_never_reaches_a_public_number(self):
        self.w.bet()
        self.w.settle()
        rows = read_rows(self.w.ledger)
        for r in rows:
            if r["kind"] == st.KIND_GRADED:
                r["clv_pts"] = 99.0                            # absurd, and ignored
        write_jsonl(Path(self.w.ledger), rows)
        d = self.summary()
        self.assertLess(d.summary.clv.mean_pts, 20)
        self.assertNotEqual(d.bets[0].clv_pts, 99.0)            # H1's own measurement is what shows

    def test_a_replay_run_is_a_separate_block_and_never_a_forward_number(self):
        self.w.bet(mode="replay")
        self.w.settle()
        s = self.summary().summary
        self.assertEqual(s.record.bets, 0)                     # nothing forward
        self.assertEqual((s.replay.bets, s.replay.wins), (1, 1))
        self.assertEqual(s.verdict.label, "TOO EARLY")
        self.assertEqual(s.verdict.sentence.split()[1], "0")   # n = 0
        self.assertEqual(self.summary().bets[0].segment, "replay")

    def test_a_hound_with_no_bet_yet_is_running_not_benched(self):
        s = self.summary().summary
        self.assertEqual((s.status, s.record.bets, s.verdict.label), ("running", 0, "TOO EARLY"))

    def test_a_retired_hound_goes_to_the_graveyard_with_the_contracts_cause(self):
        self.w.hounds[0].update(status="retired", retired_at="2026-10-21T01:00:00Z",
                                retired_by="owner:7", retire_reason="not for me")
        s = self.summary().summary
        self.assertEqual(s.status, "retired")
        self.assertEqual((s.retired.date, s.retired.cause), ("2026-10-21", "retired by the owner"))
        book = stats.build(self.w.sources())
        self.assertEqual([x.id for x in stats.graveyard(book)], ["u-int1"])
        self.assertEqual(stats.leaderboard(book), [])

    def test_rows_written_before_the_contract_names_read_the_same(self):
        """Old rows (``price`` = average, ``best_price``, ``n_books``, ``commence_time``,
        ``provenance``) mean what the new names mean."""
        self.w.bet()
        self.w.settle()
        new = self.summary().summary
        new_names = ("price_average", "price_best", "book", "book_count", "start_utc", "segment",
                     "who_decided", "reason", "date", "units", "units_best_price",
                     "units_average_price")
        rows = read_rows(self.w.ledger)
        for r in rows:
            for k in new_names:
                r.pop(k, None)
        write_jsonl(Path(self.w.ledger), rows)
        old = self.summary().summary
        self.assertEqual(old.record.units_average_price, new.record.units_average_price)
        self.assertEqual(old.record.units_recorded_price, new.record.units_recorded_price)
        self.assertEqual((old.record.bets, old.verdict.label), (new.record.bets, new.verdict.label))

    def test_the_default_ledger_sits_beside_the_app_database_not_in_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app" / "app.db"
            with mock.patch.dict(os.environ, {"APP_DB_PATH": str(db)}, clear=False):
                os.environ.pop(eng.ENV_LEDGER, None)
                self.assertEqual(Path(eng.ledger_path()), db.parent / eng.LEDGER_NAME)
                self.assertEqual(dict(Sources.default().pack_ledgers)["user"],
                                 db.parent / eng.LEDGER_NAME)
            with mock.patch.dict(os.environ, {eng.ENV_LEDGER: str(Path(tmp) / "x.jsonl")}):
                self.assertEqual(eng.ledger_path(), str(Path(tmp) / "x.jsonl"))
            self.assertEqual(eng.ledger_path("explicit.jsonl"), "explicit.jsonl")


class PackLedgerShape(unittest.TestCase):
    """The house pack's real ledger (evidence/hounds_house_v1.jsonl, replay segment) disagreed with
    H1's reader, which had only been run on fixtures. Found 2026-10-18 reading the real file; the
    READER was fixed, the pack files were not touched."""

    def rows(self):
        bet = {"kind": "hound_bet", "hound_id": "totals_terrier", "date": "2026-09-08",
               "event_id": "E1", "sport": "mlb", "market": "total", "line": 8.5,
               "selection": "Over 8.5", "side": "over", "price_average": -108, "price_best": 100,
               "book": "fanatics", "book_count": 10, "lock_utc": "2026-09-08T21:41:00Z",
               "start_utc": "2026-09-08T22:41:00Z", "who_decided": "random", "segment": "replay",
               "reason": "Seeded dart.", "row_hash": "H-BET"}
        graded = {"kind": "hound_graded", "hound_id": "totals_terrier", "date": "2026-09-08",
                  "event_id": "E1", "sport": "mlb", "market": "total", "selection": "Over 8.5",
                  "side": "over", "result": "WIN", "units_best_price": 1.0,
                  "units_average_price": 0.9259, "segment": "replay", "bet_row_hash": "H-BET",
                  "row_hash": "H-GRADED-1"}                    # no ``line``, no ``bet_id``
        return bet, graded

    def test_a_graded_row_finds_its_bet_by_bet_row_hash_when_it_has_no_line(self):
        bet, graded = self.rows()
        bets, _ = ledgers.pack_rows([bet, graded])
        self.assertEqual(len(bets), 1)                         # was 2: one ungraded, one orphan
        b = bets[0]
        self.assertEqual((b.result, b.line, b.units, b.price, b.price_average),
                         ("win", "8.5", 1.0, 100, -108))

    def test_the_last_grading_of_a_bet_wins(self):
        bet, graded = self.rows()
        regraded = dict(graded, result="LOSS", units_best_price=-1.0, row_hash="H-GRADED-2")
        bets, _ = ledgers.pack_rows([bet, graded, regraded])
        self.assertEqual((len(bets), bets[0].result, bets[0].units), (1, "loss", -1.0))

    def test_a_seeded_draw_is_decided_by_code(self):
        bet, _ = self.rows()
        bets, _ = ledgers.pack_rows([bet])
        self.assertEqual(bets[0].who_decided, "code")
        self.assertIn(bets[0].who_decided, contract.WHO_DECIDED)

    def test_units_average_price_is_not_read_as_recorded_units(self):
        bet, graded = self.rows()
        graded.pop("units_best_price")
        graded["profit_units"] = 0.9259                        # the user ledger's AVERAGE-price profit
        bets, _ = ledgers.pack_rows([bet, graded])
        self.assertIsNone(bets[0].units)                       # recomputed from price_best instead
        self.assertEqual(stats.recorded_units(bets[0]), 1.0)
        self.assertEqual(stats.average_units(bets[0]), round(100 / 108, 4))


# ---- routes ---------------------------------------------------------------------------------------

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover -- Linux CI installs none; the core above runs without it
    HAS_FASTAPI = False

if HAS_FASTAPI:
    from fastapi.testclient import TestClient
    from starlette.routing import Match

from tests import _hounds_fixtures as F


def handler_for(app, path: str, method: str = "GET") -> str:
    """The name of the first route in mount order that matches this request path."""
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"",
             "headers": []}
    for route in app.router.routes:
        match, _child = route.matches(scope)
        if match != Match.FULL:
            continue
        # FastAPI wraps an included router in an _IncludedRouter; the mount order of those wrappers
        # is the order requests are matched in, and the first one with a full match owns the path.
        inner = getattr(getattr(route, "original_router", None), "routes", None)
        for sub in inner if inner is not None else [route]:
            if sub.matches(scope)[0] == Match.FULL:
                return sub.endpoint.__name__
    return "<none>"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteOrder(unittest.TestCase):
    """MISALIGNMENT 3. ``GET /hounds/{id}`` (api/hounds.py) swallows any one-segment path under
    /hounds, so ``/hounds/menu`` and ``/hounds/mine`` (api/hounds_create.py) only work because
    api/app.py mounts that router first, and ``stream``, ``series`` and ``graveyard`` only work
    because they are declared before ``{id}``. Pinned against the real app."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_each_literal_path_goes_to_its_own_handler_not_to_the_id_route(self):
        expected = {
            "/hounds/menu": "hounds_menu",
            "/hounds/mine": "my_hounds",
            "/hounds/stream": "stream",
            "/hounds/series": "series",
            "/hounds/graveyard": "graveyard",
            "/hounds": "leaderboard",
            "/hounds/u-abc123": "hound",
            "/hounds/u-abc123/bets": "hound_bets",
            "/hounds/u-abc123/spec": "hound_spec",
            "/hounds/u-abc123/scorecard": "hound_scorecard",
        }
        for path, handler in expected.items():
            with self.subTest(path=path):
                self.assertEqual(handler_for(self.app, path), handler)

    def test_the_hazard_is_real_mounted_the_other_way_round_menu_is_read_as_an_id(self):
        """A negative control: this is what api/app.py's mount order prevents."""
        from fastapi import FastAPI
        from api import hounds, hounds_create
        wrong = FastAPI()
        wrong.include_router(hounds.router)
        wrong.include_router(hounds_create.router)
        self.assertEqual(handler_for(wrong, "/hounds/menu"), "hound")
        self.assertEqual(handler_for(wrong, "/hounds/mine"), "hound")
        self.assertEqual(handler_for(wrong, "/hounds/stream"), "stream")   # declared before {id}

    def test_a_user_hound_id_can_never_equal_a_literal_route(self):
        """The create route's ids are ``u-<hex>``; none can collide with the literal paths."""
        from src.hounds import user_store
        for _ in range(50):
            self.assertTrue(user_store.new_hound_id().startswith("u-"))

    def test_served_over_http_each_literal_path_answers_with_its_own_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            with mock.patch.object(Sources, "default", staticmethod(lambda: src)):
                stats.clear_cache()
                stats.get_book(src)
                client = TestClient(self.app)
                menu = client.get("/hounds/menu")
                self.assertEqual(menu.status_code, 200, menu.text)
                self.assertIn("side_rules", menu.json())             # the create router's menu
                mine = client.get("/hounds/mine")
                self.assertEqual(mine.status_code, 401, mine.text)   # needs a sign-in, not "no such hound"
                self.assertIn("items", client.get("/hounds/stream").json())
                self.assertIn("series", client.get("/hounds/series?ids=alpha").json())
                self.assertIn("hounds", client.get("/hounds/graveyard").json())
                self.assertEqual(client.get("/hounds/alpha").json()["id"], "alpha")
                self.assertEqual(client.get("/hounds/nope").status_code, 404)
                stats.clear_cache()


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class WarmingUp(unittest.TestCase):
    """MISALIGNMENT 5. A cold build streams about a million odds rows (5 to 10 s here). The first
    request must not wait for it and startup must not carry it: it answers ``warming_up`` within a
    second and builds ONCE in the background, under the app's one-build-at-a-time gate."""

    def setUp(self):
        import threading
        from api.app import app
        self._tmp = tempfile.TemporaryDirectory()
        self.src = F.make_world(Path(self._tmp.name))
        self._patch = mock.patch.object(Sources, "default", staticmethod(lambda: self.src))
        self._patch.start()
        stats.clear_cache()
        self.client = TestClient(app)
        self.release = threading.Event()
        self.calls = []
        self.real_build = stats.build

        def slow_build(src):
            self.calls.append(1)
            self.release.wait(10)
            return self.real_build(src)

        self._build = mock.patch.object(stats, "build", slow_build)
        self._build.start()

    def tearDown(self):
        self.release.set()
        thread = stats._BG["thread"]
        if thread is not None:
            thread.join(10)
        self._build.stop()
        self._patch.stop()
        stats.clear_cache()
        self._tmp.cleanup()

    def wait_built(self):
        self.release.set()
        stats._BG["thread"].join(10)

    def test_the_first_request_answers_warming_within_a_second_and_never_waits_for_the_build(self):
        import time
        started = time.time()
        r = self.client.get("/hounds")
        self.assertLess(time.time() - started, 1.0)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIs(body["warming_up"], True)
        self.assertEqual(body["hounds"], [])
        self.assertGreaterEqual(body["retry_after_seconds"], 1)
        self.assertIs(body["paper_only"], True)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_every_route_has_a_warming_shape_of_its_own(self):
        for path, key in (("/hounds", "hounds"), ("/hounds/graveyard", "hounds"),
                          ("/hounds/stream", "items"), ("/hounds/series?ids=alpha", "series"),
                          ("/hounds/alpha", "id"), ("/hounds/alpha/bets", "items")):
            with self.subTest(path=path):
                body = self.client.get(path).json()
                self.assertIs(body["warming_up"], True)
                self.assertIn(key, body)

    def test_many_requests_while_cold_start_one_build_only(self):
        for _ in range(8):
            self.client.get("/hounds")
        self.wait_built()
        self.assertEqual(len(self.calls), 1)

    def test_once_built_the_same_request_returns_the_race(self):
        self.client.get("/hounds")
        self.wait_built()
        body = self.client.get("/hounds").json()
        self.assertNotIn("warming_up", body)
        self.assertIn("alpha", [h["id"] for h in body["hounds"]])
        self.assertIn("max-age", self.client.get("/hounds").headers["cache-control"])

    def test_a_changed_ledger_serves_the_old_book_while_one_rebuild_runs(self):
        self.release.set()
        stats.get_book(self.src)                        # warm, synchronously
        self.release.clear()
        before = self.client.get("/hounds").json()
        with open(self.src.pack_ledgers[0][1], "a", encoding="utf-8") as fh:
            fh.write("\n")                              # an input changed size
        self.calls.clear()
        r = self.client.get("/hounds")
        self.assertNotIn("warming_up", r.json())
        self.assertEqual([h["id"] for h in r.json()["hounds"]],
                         [h["id"] for h in before["hounds"]])
        self.assertEqual(r.headers["cache-control"], "no-store")   # a shared cache must not keep it
        self.client.get("/hounds")
        self.wait_built()
        self.assertEqual(len(self.calls), 1)

    def test_a_failed_first_build_is_a_503_not_an_empty_race(self):
        def broken(src):
            raise RuntimeError("boom")

        with mock.patch.object(stats, "build", broken):
            self.client.get("/hounds")
            stats._BG["thread"].join(10)
            r = self.client.get("/hounds")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("warming_up", r.text)

    def test_the_build_takes_the_apps_build_gate(self):
        from src.appstate import freshness
        before = freshness.build_stats()["total"]
        self.client.get("/hounds")
        self.wait_built()
        self.assertGreater(freshness.build_stats()["total"], before)
        self.assertLessEqual(freshness.build_stats()["max_running"], 1)


# ---- the in-process scheduler -----------------------------------------------------------------------

import threading
import time
import tracemalloc

from src.appstate import freshness
from src.hounds import user_runner, user_store


class SchedulerSwitch(unittest.TestCase):
    """MISALIGNMENT 4. The capture slot runs in GitHub Actions with no app database, while user
    hounds live in the production app database. The engine therefore runs inside the API process,
    OFF unless HOUNDS_ENGINE=on."""

    def test_off_by_default_and_for_anything_but_on(self):
        self.assertFalse(user_runner.enabled({}))
        for value in ("", "off", "0", "no", "false", "maybe"):
            self.assertFalse(user_runner.enabled({"HOUNDS_ENGINE": value}), value)
        for value in ("on", "ON", " on ", "1", "true"):
            self.assertTrue(user_runner.enabled({"HOUNDS_ENGINE": value}), value)

    def test_off_starts_no_thread_at_all(self):
        before = threading.active_count()
        self.assertIsNone(user_runner.start_loop(env={}, do_pass=lambda: self.fail("ran")))
        self.assertIsNone(user_runner.start_loop(env={"HOUNDS_ENGINE": "off"}))
        self.assertEqual(threading.active_count(), before)

    def test_the_interval_is_15_minutes_and_a_typo_is_not_a_hot_loop(self):
        self.assertEqual(user_runner.interval_seconds({}), 900.0)
        self.assertEqual(user_runner.interval_seconds({"HOUNDS_ENGINE_INTERVAL_SECONDS": "60"}), 60.0)
        self.assertEqual(user_runner.interval_seconds({"HOUNDS_ENGINE_INTERVAL_SECONDS": "0.01"}),
                         user_runner.MIN_INTERVAL_SECONDS)
        self.assertEqual(user_runner.interval_seconds({"HOUNDS_ENGINE_INTERVAL_SECONDS": "soon"}), 900.0)

    def test_on_runs_passes_on_a_cadence_one_at_a_time_and_stops_when_told(self):
        stop = threading.Event()
        ran = []
        gate = threading.Event()

        def do_pass():
            ran.append(time.time())
            gate.set()

        thread = user_runner.start_loop(env={"HOUNDS_ENGINE": "on"}, interval_s=0.05,
                                        stop_event=stop, do_pass=do_pass)
        try:
            self.assertTrue(gate.wait(5))
            time.sleep(0.3)
        finally:
            stop.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(len(ran), 2)
        self.assertEqual(sum(1 for t in threading.enumerate() if t.name == "hounds-engine"), 0)

    def test_it_waits_for_the_first_cache_warm_up_before_its_first_pass(self):
        stop = threading.Event()
        ready = {"yes": False}
        ran = threading.Event()
        thread = user_runner.start_loop(env={"HOUNDS_ENGINE": "on"}, interval_s=60, stop_event=stop,
                                        ready=lambda: ready["yes"], do_pass=ran.set)
        try:
            self.assertFalse(ran.wait(0.3))
            ready["yes"] = True
            self.assertTrue(ran.wait(10))
        finally:
            stop.set()
            thread.join(10)

    def test_the_app_starts_no_engine_thread_without_the_flag(self):
        if not HAS_FASTAPI:
            self.skipTest("fastapi not installed")
        from api import app as app_mod
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOUNDS_ENGINE", None)
            app_mod._start_hounds_engine()
        self.assertEqual(sum(1 for t in threading.enumerate() if t.name == "hounds-engine"), 0)


class SchedulerPass(unittest.TestCase):
    """One pass of user_runner.run_pass against a small world (the engine, the ledger beside the
    database, settlement), one at a time under the app's build gate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.w = World(root)
        self.h = self.w.add_hound(price_min=100, price_max=300)
        self.ledger = self.w.ledger
        self.kw = dict(ledger=self.ledger, multibook_path=str(self.w.multibook),
                       hounds=[hound_for(self.w.hounds[0])],
                       refresh_stats=lambda: self.refreshed.append(1))
        self.refreshed = []
        self.index_patch = mock.patch.object(eng, "_load_game_pk_index", lambda: INDEX)
        self.index_patch.start()

    def tearDown(self):
        self.index_patch.stop()
        self._tmp.cleanup()

    def settle_kwargs(self):
        return dict(close_fn=lambda b: None, game_pk_index=INDEX,
                    mlb_results={PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)})

    def test_a_pass_writes_the_bet_then_grades_it_and_a_second_pass_adds_nothing(self):
        first = user_runner.run_pass(now=AT_LOCK, settle_kwargs=self.settle_kwargs(), **self.kw)
        self.assertEqual(first["engine"][0]["bets_written"], 1)
        self.assertEqual(first["settle"]["graded"], 0)         # the game has not started at the lock
        self.assertEqual(self.refreshed, [1])                   # new rows: one stats rebuild asked for
        later = user_runner.run_pass(now=NEXT_DAY, settle_kwargs=self.settle_kwargs(), **self.kw)
        self.assertEqual(later["settle"]["graded"], 1)
        again = user_runner.run_pass(now=NEXT_DAY, settle_kwargs=self.settle_kwargs(), **self.kw)
        self.assertEqual((again["wrote"], again["engine"][0]["bets_written"]), (0, 0))
        self.assertEqual(self.refreshed, [1, 1])                # nothing new, nothing asked for
        rows = read_rows(self.ledger)
        self.assertEqual([r["kind"] for r in rows], [eng.KIND_BET, st.KIND_GRADED])
        self.assertTrue(eng.verify_ledger(self.ledger).ok)

    def test_no_running_hounds_means_the_odds_store_is_never_opened(self):
        with mock.patch.object(eng, "iter_rows", side_effect=AssertionError("read the store")):
            report = user_runner.run_pass(now=AT_LOCK, ledger=self.ledger, hounds=[],
                                          refresh_stats=lambda: self.fail("rebuilt"))
        self.assertEqual(report["skipped"], "no running hounds")
        self.assertFalse(os.path.exists(self.ledger))

    def test_the_pass_streams_the_store_instead_of_listing_it(self):
        seen = {}
        real = eng.iter_rows

        def spy(*a, **k):
            gen = real(*a, **k)
            seen["is_generator"] = hasattr(gen, "__next__") and not isinstance(gen, list)
            return gen

        with mock.patch.object(eng, "iter_rows", spy):
            user_runner.run_pass(now=AT_LOCK, settle_kwargs=self.settle_kwargs(), **self.kw)
        self.assertTrue(seen["is_generator"])

    def test_tomorrows_slate_is_included_only_late_in_the_eastern_evening(self):
        noon = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)       # 12:00 Eastern
        late = datetime(2026, 10, 21, 1, 30, tzinfo=timezone.utc)       # 21:30 Eastern on the 20th
        self.assertEqual(user_runner.pass_dates(noon), ["2026-10-20"])
        self.assertEqual(user_runner.pass_dates(late), ["2026-10-20", "2026-10-21"])

    def test_the_pass_takes_the_build_gate_and_never_runs_beside_another_build(self):
        held = threading.Event()
        release = threading.Event()

        def other_build():
            with freshness._gated_build():
                held.set()
                release.wait(10)

        t = threading.Thread(target=other_build)
        t.start()
        self.assertTrue(held.wait(5))
        done = threading.Event()
        result = {}

        def run():
            result["r"] = user_runner.run_pass(now=AT_LOCK, settle_kwargs=self.settle_kwargs(), **self.kw)
            done.set()

        runner = threading.Thread(target=run)
        runner.start()
        self.assertFalse(done.wait(0.5), "the pass ran while another build held the gate")
        release.set()
        self.assertTrue(done.wait(10))
        t.join(5)
        runner.join(5)
        self.assertEqual(result["r"]["engine"][0]["bets_written"], 1)
        self.assertLessEqual(freshness.build_stats()["max_running"], 1)

    def test_a_crashing_pass_is_logged_and_the_loop_survives(self):
        before = user_runner.status()["passes"]
        with mock.patch.object(user_runner, "run_pass", side_effect=RuntimeError("boom")):
            out = user_runner.pass_safely()
        self.assertIn("boom", out["error"])
        self.assertEqual(user_runner.status()["passes"], before + 1)
        self.assertIn("boom", user_runner.status()["last_error"])


REAL_MULTIBOOK = Path(__file__).resolve().parent.parent / "data" / "processed" / "odds_multibook.jsonl"
PEAK_BUDGET_BYTES = 150 * 1024 * 1024         # the task's budget for one pass on the 1 GB machine


@unittest.skipUnless(REAL_MULTIBOOK.exists(), "no local odds store")
class SchedulerMemoryOnTheRealStore(unittest.TestCase):
    """Peak Python memory of one engine pass against the REAL odds store (read-only), measured with
    tracemalloc. A slate of 15 games at the busiest part of the regular season; the budget is 150 MB.
    Whole-store reads were the 2026-10-01 incident; this pass keeps one slate and trimmed rows."""

    def test_one_pass_over_a_full_regular_season_slate_stays_under_150_mb(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app" / "app.db"
            ledger = str(Path(tmp) / "app" / "hounds_user_v1.jsonl")
            with mock.patch.dict(os.environ, {"APP_DB_PATH": str(db)}):
                from src.appstate import users as users_store
                user = users_store.create_user("mem@example.com", status="active")
                base = dict(tagline="", sports=["MLB"], side_rule="underdog", price_min=-199,
                            price_max=1000, min_books=1, max_bets_per_day=5, lock_minutes=120)
                long_ago = datetime(2026, 9, 1, tzinfo=timezone.utc)
                user_store.create_hound(user.id, dict(base, name="Mem Dog", markets=["moneyline", "spread"]),
                                        now=long_ago)
                user_store.create_hound(user.id, dict(base, name="Mem Over", markets=["total"],
                                                      side_rule="over"), now=long_ago)
                tracemalloc.start()
                try:
                    report = user_runner.run_pass(now=datetime(2026, 9, 20, 17, 0, tzinfo=timezone.utc),
                                                  ledger=ledger, refresh_stats=lambda: None)
                    _cur, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
        self.assertGreaterEqual(report["engine"][0]["games_seen"], 10, report)
        self.assertLess(peak, PEAK_BUDGET_BYTES, f"one pass peaked at {peak / 1e6:.0f} MB")


# ---- the pages against the real API --------------------------------------------------------------------

from tests.hounds_web_runner import HAS_NODE, run_page


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


@unittest.skipUnless(HAS_FASTAPI and HAS_NODE, "needs FastAPI and node")
class PagesReadTheRealApi(unittest.TestCase):
    """MISALIGNMENT 1, end to end. The pages' payloads are fetched from the REAL app (TestClient over
    ``api.app``, the real routers, the real stats over the H1 synthetic world) and handed to the pages'
    own scripts under node. Nothing in between is a hand-written fixture."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls._tmp = tempfile.TemporaryDirectory()
        cls.src = F.make_world(Path(cls._tmp.name))
        cls._patch = mock.patch.object(Sources, "default", staticmethod(lambda: cls.src))
        cls._patch.start()
        stats.clear_cache()
        stats.get_book(cls.src)
        client = TestClient(app)
        cls.routes = {}
        for path in ("/hounds", "/hounds/stream", "/hounds/graveyard", "/hounds/menu", "/hounds/alpha",
                     "/hounds/charlie", "/hounds/delta", "/hounds/alpha/bets?page=2&page_size=2"):
            r = client.get(path)
            assert r.status_code == 200, (path, r.text)
            cls.routes[path.split("?")[0] if "?" not in path else path] = [200, r.json()]
        ids = ",".join(h["id"] for h in cls.routes["/hounds"][1]["hounds"])
        cls.routes["/hounds/series"] = [200, client.get(f"/hounds/series?ids={ids}").json()]
        cls.routes["/hounds/mine"] = [200, {"hounds": [], "limit_running": 3}]
        cls.routes["/hounds/alpha/spec"] = [200, {"spec": dict(
            name="Alpha II", tagline="", sports=["MLB"], markets=["moneyline"], side_rule="underdog",
            price_min=100, price_max=250, min_books=3, max_bets_per_day=2, lock_minutes=120),
            "copied_from": "alpha", "rule_text": "x"}]

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        stats.clear_cache()
        cls._tmp.cleanup()

    def test_the_race_page_lists_every_hound_with_its_real_numbers_and_the_replay_apart(self):
        out = run_page("hounds", routes=self.routes, queries=[
            q("ids", ".hd-row", "attrs", attr="data-hound"),
            q("alpha", ".hd-row[data-hound='alpha']"),
            q("alpha_replay", ".hd-row[data-hound='alpha'] [data-hook='replay-line']"),
            q("charlie", ".hd-row[data-hound='charlie']"),
            q("units", ".hd-row[data-hound='alpha'] [data-hook='row-units']"),
            q("lines", "[data-hook='hounds-chart-panel'] .hd-line", "count"),
            q("user", ".hd-row[data-hound='u-1']"),
            q("stream", "[data-hook='stream-list'] .hd-stream__text", "texts"),
            q("refused", "[data-hook='stream-list'] li", "attrs", attr="data-refused"),
            q("basis", "[data-hook='hounds-basis']")])
        final = out["final"]
        self.assertEqual(set(final["ids"]), {"alpha", "bravo", "charlie", "delta", "u-1"})
        # alpha: 3 forward bets, its replay bet in a separate line (never in the forward record)
        self.assertIn("3 bets", final["alpha"])
        self.assertIn("replay", final["alpha_replay"].lower())
        self.assertIn("average price", final["units"])
        self.assertIn("best price", final["units"])
        self.assertGreater(final["lines"], 0)
        self.assertIn("Paper only", final["basis"])
        self.assertTrue(any(t.startswith("Passed") for t in final["stream"]), final["stream"])
        self.assertIn("true", final["refused"])
        self.assertNotIn("warming", out["text"].lower())

    def test_the_hound_page_shows_the_bets_the_server_sent_and_pages_with_the_servers_numbers(self):
        out = run_page("hound", routes=self.routes, search="?id=alpha", queries=[
            q("rows", "[data-hook='bets-table'] tbody tr", "count"), q("page", "[data-hook='bets-page']"),
            q("name", "[data-hook='hound-name']"), q("rule", "[data-hook='rule-text']"),
            q("verdict", "[data-hook='verdict-chip']"),
            q("heads", "[data-hook='bets-table'] thead th", "texts"),
            q("next_off", "[data-hook='bets-next']", "disabled")])
        self.assertEqual(out["final"]["name"], "Alpha")
        self.assertEqual(out["final"]["rule"], "Alpha rule.")
        self.assertIn("TOO EARLY", out["final"]["verdict"])
        total = self.routes["/hounds/alpha"][1]["bets"]["total"]
        self.assertGreater(total, 0)
        self.assertGreater(out["final"]["rows"], 0)
        self.assertIn("Average price", out["final"]["heads"])
        self.assertIn(f"({total} bets)", out["final"]["page"])
        self.assertTrue(out["final"]["next_off"])               # one page of 5 bets: nothing older to fetch

    def test_a_replay_only_pack_hound_has_no_forward_numbers_and_its_replay_result_is_shown_apart(self):
        out = run_page("hound", routes=self.routes, search="?id=charlie", queries=[
            q("fwd", "[data-hook='forward-facts']"), q("rep", "[data-hook='replay-line']"),
            q("chart", "[data-hook='hound-chart-title']")])
        charlie = self.routes["/hounds/charlie"][1]
        self.assertEqual(charlie["record"]["bets"], 1)         # the fixture's one forward bet
        self.assertEqual(charlie["replay"]["bets"], 1)

    def test_the_build_form_posts_what_the_real_create_route_accepts(self):
        """The page's own script posts the JSON; the real request model and the real menu validation take it."""
        from api.hounds_create import CreateHoundRequest
        from src.hounds import user_spec
        r = dict(self.routes)
        r["/hounds/menu"] = [200, user_spec.menu()]
        r["POST /hounds"] = [200, {"hound": {"id": "u-x"}}]
        out = run_page("build", routes=r, stored={"aisportsanalysis.invite_token": "tok"}, actions=[
            dict(do="set", sel="[data-hook='f-name']", value="Pup Test"),
            dict(do="set", sel="[data-hook='f-tagline']", value="Fetches"),
            dict(do="check", sel="[data-field='sport'] input", index=0),
            dict(do="check", sel="[data-field='market'] input", index=0),
            dict(do="check", sel="[data-field='side'] input", index=1),
            dict(do="set", sel="[data-hook='f-price-min']", value="-150"),
            dict(do="set", sel="[data-hook='f-price-max']", value="250"),
            dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)])
        self.assertEqual(len(out["posts"]), 1)
        body = out["posts"][0]["body"]
        model = CreateHoundRequest(**body)                      # the request model accepts it as it stands
        spec = user_spec.validate_spec(model.spec)              # and so does the menu's own validation
        self.assertEqual((spec["name"], spec["side_rule"], spec["price_min"], spec["price_max"]),
                         ("Pup Test", "underdog", -150, 250))
        self.assertEqual(out["navigations"], ["hound.html?id=u-x"])

    def test_the_copy_flow_posts_the_spec_endpoints_answer_back_with_copied_from(self):
        from api.hounds_create import CreateHoundRequest
        from src.hounds import user_spec
        r = dict(self.routes)
        r["/hounds/menu"] = [200, user_spec.menu()]
        r["POST /hounds"] = [200, {"hound": {"id": "u-y"}}]
        out = run_page("build", routes=r, search="?from=alpha", stored={"aisportsanalysis.invite_token": "tok"},
                       actions=[dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)])
        body = out["posts"][0]["body"]
        model = CreateHoundRequest(**body)
        self.assertEqual(model.copied_from, "alpha")
        user_spec.validate_spec(model.spec)


# ---- the real house pack ---------------------------------------------------------------------------------

import dataclasses


def _pack_paths():
    """config/house_pack.json and evidence/hounds_house_v1.jsonl, or the paths in HOUNDS_PACK_CFG and
    HOUNDS_PACK_LEDGER (a way to run this against another checkout's copy of the pack)."""
    default = Sources.default()
    cfg = Path(os.environ.get("HOUNDS_PACK_CFG") or default.house_pack_cfg)
    ledger = Path(os.environ.get("HOUNDS_PACK_LEDGER") or dict(default.pack_ledgers)["house"])
    return cfg, ledger


_PACK_CFG, _PACK_LEDGER = _pack_paths()


@unittest.skipUnless(_PACK_CFG.exists() and _PACK_LEDGER.exists(), "the house pack files are not in this checkout")
class TheRealHousePack(unittest.TestCase):
    """The pack worker's real ledger (replay segment only) read by H1's reader. The first run of the
    reader on the real file found three disagreements, all fixed on the READER side: a graded row carries
    ``bet_row_hash`` and no ``line`` (spread and total bets were counted twice), ``who_decided`` is
    ``random`` for the seeded hounds, and the units fields are ``units_best_price`` / ``units_average_price``."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads(_PACK_CFG.read_text(encoding="utf-8"))["hounds"]
        with tempfile.TemporaryDirectory() as tmp:
            # the engine hounds' ledgers are not under test here: an empty world beside the real pack files
            world = World(Path(tmp))
            src = dataclasses.replace(world.sources(), house_pack_cfg=_PACK_CFG,
                                      pack_ledgers=(("house", _PACK_LEDGER),),
                                      user_hounds=None, user_stamp=None)
            cls.book = stats.build(src)
        cls.rows = read_rows(_PACK_LEDGER)

    def test_every_pack_hound_in_the_config_is_listed_with_its_category_style_and_rule(self):
        self.assertEqual(len(self.cfg), 21)
        for entry in self.cfg:
            with self.subTest(hound=entry["id"]):
                s = self.book.hounds[entry["id"]].summary
                self.assertEqual((s.name, s.category, s.style, s.rule_text),
                                 (entry["name"], entry["category"], entry["style"], entry["rule_text"]))
                self.assertEqual(s.kind, "house")

    def test_the_replay_ledger_shows_as_a_replay_block_and_never_as_a_forward_number(self):
        graded = {}
        for r in self.rows:
            if r.get("kind") == "hound_graded":
                graded[r["bet_row_hash"]] = r                    # the last grading of a bet wins
        by_hound = {}
        for r in graded.values():
            by_hound.setdefault(r["hound_id"], []).append(r)
        for entry in self.cfg:
            hid = entry["id"]
            with self.subTest(hound=hid):
                d = self.book.hounds[hid]
                expected = len(by_hound.get(hid, []))
                self.assertEqual(d.summary.record.bets, 0)       # every row of the pack ledger is replay
                self.assertEqual(d.summary.verdict.label, "TOO EARLY")
                self.assertEqual(d.series, [])
                self.assertEqual(d.summary.replay.bets if d.summary.replay else 0, expected)
                self.assertTrue(all(b.segment == "replay" for b in d.bets))

    def test_a_bet_is_one_row_however_many_times_it_was_graded(self):
        bet_rows = [r for r in self.rows if r.get("kind") == "hound_bet"]
        for entry in self.cfg:
            hid = entry["id"]
            with self.subTest(hound=hid):
                self.assertEqual(len(self.book.hounds[hid].bets),
                                 sum(1 for r in bet_rows if r["hound_id"] == hid))

    def test_every_decider_is_in_the_contracts_closed_set(self):
        for d in self.book.hounds.values():
            for b in d.bets:
                self.assertIn(b.who_decided, contract.WHO_DECIDED)
        coin = self.book.hounds["coin_flip_collie"]
        self.assertEqual({b.who_decided for b in coin.bets}, {"code"})

    def test_prices_are_the_recorded_best_quote_and_the_board_average(self):
        sample = next(b for d in self.book.hounds.values() for b in d.bets if b.price_average is not None)
        row = next(r for r in self.rows if r.get("kind") == "hound_bet" and r["hound_id"] == sample.hound_id
                   and r["date"] == sample.date and r["selection"] == sample.selection)
        self.assertEqual((sample.price, sample.price_average), (row["price_best"], row["price_average"]))


if __name__ == "__main__":
    unittest.main()
