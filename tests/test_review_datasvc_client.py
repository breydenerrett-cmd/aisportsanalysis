"""Adversarial review of the internal data service merged 2026-10-04 (red team, same day):
`src/datasvc/client.py`, `src/datasvc/mlb/service.py`, `api/datasvc.py` (docs/datasvc/CLIENT.md).

Each class tells the story of one defect the review reproduced. A test marked `expectedFailure` FAILS today for
the reason in its docstring; when the fix lands the decorator comes off and the test guards it. Tests with no
marker pin behaviour the review confirmed is already right (so a later change cannot quietly lose it).

The service-level tests need no FastAPI (the Linux CI has none); the HTTP ones are `skipUnless(HAS_FASTAPI)`.
No network: the schedule and the loader are counting fakes, the clock is pinned.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.datasvc.mlb import service as svc
from src.pipeline import store_freshness
from tests import analyst_fixtures as F
from tests.test_datasvc_mlb_api import MlbApiCase, request
from tests.test_datasvc_mlb_service import schedule_game
from tests.test_datasvc_ufc_api import HAS_FASTAPI

if HAS_FASTAPI:
    from fastapi import FastAPI
    from api import datasvc
    from src.appstate import users as users_store

MLB = "/data/v1/mlb"


def items_for(games):
    out = []
    for g in games:
        payload = F.payload(g["state"])
        payload["advanced"]["game"].update(game_pk=g["game_pk"], away_team=g["away_team"], home_team=g["home_team"])
        out.append({"payload": payload, "multibook_rows": F.multibook_rows(), "team_total_rows": F.team_total_rows(),
                    "batter_prop_rows": F.batter_prop_rows(), "pitcher_prop_rows": F.pitcher_prop_rows(),
                    "prop_board": F.prop_board(), "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
                    "section_as_of": {"teams": "2026-10-02", "starters": "2026-10-02"}})
    return out


class Counting:
    """A service over counting fakes: every schedule request and every whole-slate build is recorded."""

    def __init__(self, *, games=None, clock=None, gate=None, **kw):
        self.games = games if games is not None else [schedule_game()]
        self.fetches, self.loads = [], []
        self.fetch_error = None
        self.now = F.NOW
        self.gate = gate or {}

        def fetch(date):
            self.fetches.append(date)
            if self.fetch_error:
                raise RuntimeError(self.fetch_error)
            return [dict(g) for g in self.games]

        def load(date, games, now):
            self.loads.append(date)
            if date in self.gate:                       # a build that blocks until the test lets it go
                started, release = self.gate[date]
                started.set()
                release.wait(10)
            return items_for(games)

        self.service = svc.MlbService(fetch_games=fetch, loader=load, stores=(), clock=clock or (lambda: self.now),
                                      config_loader=lambda: dict(F.CFG), results_reader=lambda: {},
                                      pitcher_reader=lambda: {},
                                      data_root=Path(tempfile.gettempdir()) / "linehound_review_no_such_root", **kw)


class ASlateIsBuiltOnlyForAGameThatIsOnIt(unittest.TestCase):

    def test_a_club_pair_the_schedule_does_not_list_builds_nothing(self):
        """`MlbService.packet` takes the date's snapshot (the whole slate: 8.6 s for 16 games, docs/datasvc/
        CLIENT.md) BEFORE it looks for the game, so an authenticated caller asking for ZZZ@YYY on any date pays for
        and evicts a real build. The schedule it already holds says there is no such game."""
        c = Counting()
        c.service.packet(F.DATE, "ZZZ", "YYY")
        self.assertEqual(c.loads, [], "a whole-slate build ran for a game that is not on the schedule")

    def test_junk_requests_cannot_evict_the_slate_a_real_reader_is_using(self):
        """MAX_DATES_HELD is 4 and the oldest date goes first, so five junk requests on five other dates push
        today's slate out, and the next real read rebuilds it."""
        c = Counting()
        c.service.packet(F.DATE, "NYY", "TB")
        for day in range(1, 6):
            c.service.packet(f"2026-09-{day:02d}", "ZZZ", "YYY")
        before = len(c.loads)
        c.service.packet(F.DATE, "NYY", "TB")
        self.assertEqual(len(c.loads), before, "today's slate was evicted by requests for games that do not exist")

    def test_a_club_code_in_lowercase_is_the_same_game_and_the_same_cache_entry(self):
        c = Counting()
        a = c.service.packet(F.DATE, "NYY", "TB")
        b = c.service.packet(F.DATE, "nyy", "tb")
        self.assertTrue(a["available"] and b["available"])
        self.assertEqual(c.service.counters["packet_builds"], 1)
        self.assertEqual(a, b)

    def test_a_doubleheader_is_refused_never_served_as_one_half(self):
        c = Counting(games=[schedule_game(pk=1), schedule_game(pk=2, game_number=2)])
        out = c.service.packet(F.DATE, "NYY", "TB")
        self.assertFalse(out["available"])
        self.assertEqual(out["missing"][0]["code"], "ambiguous")

    def test_odd_inputs_are_refused_or_not_found_never_a_traceback(self):
        c = Counting()
        for away, home in (("../../etc", "passwd"), ("N" * 5000, "T" * 5000), ("\u0131\u0131", "\u017f"),
                           ("NYY\x00", "TB"), ("", "TB"), (None, "TB")):
            try:
                out = c.service.packet(F.DATE, away, home)
            except Exception as exc:  # noqa: BLE001
                self.assertEqual(type(exc).__name__, "DataError", (away, home))
                self.assertEqual(exc.status, 422)
            else:
                self.assertFalse(out["available"], (away, home))


class OneBuildDoesNotStopEveryOtherRead(unittest.TestCase):

    def test_a_cached_packet_is_served_while_another_date_is_being_built(self):
        """`_snapshot` holds the service's one RLock for the whole slate build (and `_schedule_for` for the whole
        upstream request), and a cache hit needs that lock, so one slow date stalls every reader of every date.
        Single-flight per date is right; a global lock is an outage lever for any signed-in caller."""
        started, release = threading.Event(), threading.Event()
        c = Counting(gate={"2026-10-04": (started, release)})
        self.assertTrue(c.service.packet(F.DATE, "NYY", "TB")["available"])          # warm: today is cached
        other = threading.Thread(target=lambda: c.service.packet("2026-10-04", "NYY", "TB"), daemon=True)
        other.start()
        self.assertTrue(started.wait(5))
        served = []
        reader = threading.Thread(target=lambda: served.append(c.service.packet(F.DATE, "NYY", "TB")), daemon=True)
        reader.start()
        reader.join(2.0)
        served_while_building = bool(served)
        release.set()
        other.join(5)
        reader.join(5)
        self.assertTrue(served_while_building, "a cache hit for today waited behind the build of another date")


class AnUpstreamBurstIsBounded(unittest.TestCase):

    def test_a_burst_of_distinct_dates_does_not_become_a_burst_of_upstream_requests(self):
        """Any date from 0001-01-01 to 9999-12-31 passes `validate_date`, each distinct date is one request to the
        schedule provider, and the cache keeps eight of them. A signed-in caller looping over dates sends the
        provider (shared with the live pages) as many requests as they like in a second."""
        c = Counting()
        for n in range(100):
            c.service.games((datetime(1990, 1, 1) + timedelta(days=n)).strftime("%Y-%m-%d"))
        self.assertLess(len(c.fetches), 100, f"{len(c.fetches)} upstream requests for 100 dates in one instant")


class AStaleScheduleIsSaidToBeStale(unittest.TestCase):

    def test_a_packet_built_on_a_schedule_read_days_ago_says_so_in_its_missing_list(self):
        """When the provider fails, the held schedule is served with its ORIGINAL observation time (right) and
        `games()` adds a `stale` entry to `missing`. `packet()` only sets `schedule_refresh_error`: the packet's
        `meta.missing` is the packet's own list, so a consumer that checks `missing` (as CLIENT.md tells it to)
        reads a three-day-old schedule as current, with no age limit at all."""
        c = Counting()
        self.assertTrue(c.service.packet(F.DATE, "NYY", "TB")["available"])
        c.fetch_error = "provider down"
        c.now = F.NOW + timedelta(days=3)
        out = c.service.packet(F.DATE, "NYY", "TB")
        self.assertTrue(out["available"])
        self.assertTrue(out["meta"]["schedule_refresh_error"])
        items = [m["item"] for m in out["meta"]["missing"]]
        self.assertIn("schedule", items, f"missing says {items}; the schedule is three days old")

    def test_games_says_so(self):
        c = Counting()
        c.service.games(F.DATE)
        c.fetch_error = "provider down"
        c.now = F.NOW + timedelta(days=3)
        out = c.service.games(F.DATE)
        self.assertEqual(out["meta"]["missing"][0]["kind"], "stale")
        self.assertEqual(out["meta"]["observed_utc"], "2026-10-03T18:00:00Z")      # the original read, not a fresh one


class OneVersionPerPacket(unittest.TestCase):

    def test_a_store_that_changes_during_every_build_is_unavailable_never_a_mix(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Path(tmp.name) / "results.csv"
        store.write_text("a\n", encoding="utf-8")

        def load(date, games, now):
            with store.open("a", encoding="utf-8") as handle:
                handle.write("x\n")
            return items_for(games)

        service = svc.MlbService(fetch_games=lambda d: [schedule_game()], loader=load,
                                 stores=(svc.StoreFile("mlb_results", lambda d: store),), clock=lambda: F.NOW,
                                 config_loader=lambda: dict(F.CFG), results_reader=lambda: {},
                                 pitcher_reader=lambda: {})
        out = service.packet(F.DATE, "NYY", "TB")
        self.assertFalse(out["available"])
        self.assertEqual(out["missing"][0]["code"], "unavailable")

    def test_a_repeat_read_of_an_unchanged_snapshot_builds_and_asks_for_nothing(self):
        c = Counting()
        first = c.service.packet(F.DATE, "NYY", "TB")
        loads, fetches = len(c.loads), len(c.fetches)
        for _ in range(20):
            again = c.service.packet(F.DATE, "NYY", "TB")
        self.assertEqual(again, first)
        self.assertEqual((len(c.loads), len(c.fetches)), (loads, fetches))

    def test_a_clock_stepped_back_an_hour_does_not_refetch_on_every_read(self):
        c = Counting()
        c.service.games(F.DATE)
        c.now = F.NOW - timedelta(hours=1)
        for _ in range(20):
            c.service.games(F.DATE)
        self.assertLessEqual(len(c.fetches), 2)


# -- /status ----------------------------------------------------------------------------------------------

class StatusDoesNotRescanOrLeak(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "unique_status_root_7f3a"
        hist = self.root / "historical"
        hist.mkdir(parents=True)
        (hist / "handedness.json").write_text('{"a": 1', encoding="utf-8")          # truncated
        (hist / "pitcher_splits.json").mkdir()                                       # unreadable: not a file
        store_freshness.reset_cache_for_tests()
        self.addCleanup(store_freshness.reset_cache_for_tests)
        self.now = datetime(2026, 10, 4, 15, tzinfo=timezone.utc)

    def test_a_corrupt_store_is_scanned_once_per_file_version_not_once_per_status_request(self):
        """`store_freshness._scan_cached` says 'errors are never cached', so a corrupt or torn store file is parsed
        again on EVERY /data/v1/status request; the UFC and NFL halves of the same route remember a failure per
        file version for exactly this reason (client._LockedMixin, dataset_status)."""
        scans = []
        real = store_freshness._scan_handedness

        def counting(path):
            scans.append(1)
            return real(path)

        with mock.patch.object(store_freshness, "_scan_handedness", counting):
            service = svc.MlbService(data_root=self.root)
            for _ in range(5):
                service.status(self.now)
        self.assertEqual(len(scans), 1, f"the same unchanged corrupt file was parsed {len(scans)} times")

    def test_status_does_not_print_the_servers_file_path(self):
        """The unreadable-store reason is `f"{type(exc).__name__}: {exc}"`, and an OSError's text carries the
        absolute path (`[Errno 13] Permission denied: 'C:\\\\...\\\\pitcher_splits.json'`), which `/status` returns
        to any signed-in caller."""
        out = svc.MlbService(data_root=self.root).status(self.now)
        text = json.dumps(out)
        self.assertNotIn(self.root.name, text, "the status body names a server path")
        self.assertNotIn("Errno", text)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class OverHttp(MlbApiCase):

    def setUp(self):
        super().setUp()
        self.fuzz_app = FastAPI()
        self.fuzz_app.include_router(datasvc.router)

    def test_every_route_and_method_refuses_a_caller_with_no_token_a_bad_token_or_the_wrong_scheme(self):
        import re
        paths = {re.sub(r"\{[^}]+\}", "x", r.path).replace(":path", "") for r in datasvc.router.routes}
        paths |= {"/data/v1/", "/data/v1/status/", "/data/v1//status", f"{MLB}/games/2026-10-03/NYY/TB/packet/"}
        for path in sorted(paths):
            for method in ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"):
                for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic YTpi"},
                                {"Authorization": "bearer"}):
                    status, _, _ = request(self.app, method, path, headers)
                    self.assertEqual(status, 401, (method, path, headers))
        self.assertEqual(self.fetches, [])

    def test_a_suspended_user_and_an_expired_token_are_refused(self):
        suspended = users_store.create_user("s@example.com", status="suspended", db=self.db)
        tok = users_store.issue_invite_token(suspended.id, db=self.db)
        active = users_store.create_user("e@example.com", status="active", db=self.db)
        expired = users_store.issue_invite_token(active.id, ttl=timedelta(seconds=-5), db=self.db)
        for token in (tok, expired):
            status, body, _ = self.get(f"{MLB}/games?date=2026-10-03", token=token)
            self.assertEqual((status, body["error"]["code"]), (401, "unauthorized"))
        self.assertEqual(self.fetches, [])

    def test_hostile_path_segments_get_the_one_error_shape_and_no_server_path(self):
        for away in ("..", "%2e%2e", "%00", "N" * 3000, "%C4%B1%C4%B1", "nyy%20", "%E2%80%AE"):
            status, body, _ = self.get(f"{MLB}/games/2026-10-03/{away}/TB/packet")
            self.assertIn(status, (404, 422), away)
            self.assertEqual(set(body), {"error"}, away)
            self.assertNotIn(Path(self._tmp.name).name, json.dumps(body), away)
        for date in ("2026-10-03%00", "%EF%BC%92%EF%BC%90%EF%BC%92%EF%BC%96-10-03", "2026-10-3", "20261003",
                     "2026-02-30", "x" * 400):
            status, body, _ = self.get(f"{MLB}/games/{date}/NYY/TB/packet")
            self.assertEqual(status, 422, date)
            self.assertEqual(body["error"]["code"], "invalid_parameter", date)

    def test_a_corrupt_ufc_store_is_a_503_with_no_server_path(self):
        (self.dir / "events.jsonl").write_text("{not json\n", encoding="utf-8")
        status, body, _ = self.get("/data/v1/ufc/events")
        self.assertEqual(status, 503, body)
        self.assertNotIn(Path(self._tmp.name).name, json.dumps(body))
        self.assertEqual(body["error"]["code"], "data_unavailable")

    def test_http_status_does_not_print_the_servers_file_path_of_an_unreadable_mlb_store(self):
        root = Path(self._tmp.name) / "mlb_status_root"
        (root / "historical" / "pitcher_splits.json").mkdir(parents=True)
        store_freshness.reset_cache_for_tests()
        self.addCleanup(store_freshness.reset_cache_for_tests)
        datasvc.use_mlb_service(svc.MlbService(data_root=root, clock=lambda: F.NOW))
        status, body, _ = self.get("/data/v1/status")
        self.assertEqual(status, 200, body)
        self.assertNotIn(Path(self._tmp.name).name, json.dumps(body["data"]["mlb"]), "/status names a server path")


if __name__ == "__main__":
    unittest.main()
