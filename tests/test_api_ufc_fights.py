"""api/ufc_fights.py: GET /ufc/fight-night and /ufc/fight-night/{event_id}.

FastAPI is an api/-only dependency and the Linux CI has none, so every test here is
`skipUnless(HAS_FASTAPI)`. Requests go through the ASGI app directly (the helper of
tests/test_datasvc_ufc_api.py) with REAL auth: a user and an invite token are made in a throwaway
sqlite file, so a request either carries a token `require_paid_access` accepts or it does not. The
data is injected (`datasvc.use_data_dir` points the data API's one store holder at a temporary
directory built by the data layer's synthetic world) and the clock is pinned, so no test depends on
the machine, the real files or the time.

What is pinned here:
  * the same sign-in gate as /data/v1, and public demo mode cannot open it;
  * the shape: the event, each bout in card order with both fighters, the price, the data layer's own
    sheet and the read built from that sheet, byte for byte what the two modules produce;
  * fail soft: a bout whose sheet cannot be built still lists, with the reason, and the card still serves;
  * which event is "next", the development show, a finished card, no event at all, an unknown id;
  * the store is loaded once per process and the payload built once per store version.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import FastAPI
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analysis import ufc_read
from src.appstate import users as users_store
from src.datasvc import store as jsonl
from src.datasvc.ufc import matchup
from tests.test_datasvc_ufc_api import request
from tests.test_datasvc_ufc_features import build_store, odds_row

if HAS_FASTAPI:
    from api import datasvc, ufc_fights

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
URL = "/ufc/fight-night"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class FightNightCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "ufc"
        self.store = build_store(self.dir)
        self.db = Path(self._tmp.name) / "app.db"
        for patcher in (mock.patch.object(users_store, "db_path", lambda: self.db),
                        mock.patch.object(datasvc, "_now", lambda: NOW)):
            patcher.start()
            self.addCleanup(patcher.stop)
        datasvc.use_data_dir(self.dir)
        self.addCleanup(datasvc.use_data_dir, None)
        user = users_store.create_user("analyst@example.com", status="active", db=self.db)
        self.token = users_store.issue_invite_token(user.id, db=self.db)
        self.app = FastAPI()
        self.app.include_router(ufc_fights.router)

    def get(self, path=URL, token=True):
        headers = {"Authorization": f"Bearer {self.token}"} if token is True else (
            {"Authorization": f"Bearer {token}"} if token else {})
        return request(self.app, "GET", path, headers)

    def ok(self, path=URL):
        status, body, _ = self.get(path)
        self.assertEqual(status, 200, body)
        return body

    def bout(self, body, bout_id):
        return [b for b in body["bouts"] if b["bout_id"] == bout_id][0]

    def add_event(self, event_id, name, date_utc, bouts, status="scheduled", fetched="2026-10-03T13:00:00Z"):
        """A scheduled event of `bouts` [(bout_id, a, b, number, segment)] using the synthetic fighters."""
        rows = []
        for bout_id, a, b, number, segment in bouts:
            rows.append({"bout_id": bout_id, "event_id": event_id, "date_utc": date_utc, "match_number": number,
                         "card_segment": segment, "card_segment_raw": segment, "weight_class": "Welterweight",
                         "scheduled_rounds": 3, "description": "3 Rnd", "status": status, "fighter_a_id": a,
                         "fighter_b_id": b, "winner_id": None, "result_method": None, "result_method_raw": None,
                         "result_detail": None, "result_target": None, "end_round": None, "end_time_s": None,
                         "fight_time_s": None, "status_url": "x", "source_url": "x", "fetched_utc": fetched})
        self.store.upsert("bouts", rows)
        self.store.upsert("events", [{"event_id": event_id, "name": name, "short_name": name, "date_utc": date_utc,
                                      "season": 2026, "status": status, "venue_id": None,
                                      "bout_ids": [r["bout_id"] for r in rows], "source_url": "x", "fetched_utc": fetched}])


# -- the gate ---------------------------------------------------------------------------------------

class TheGate(FightNightCase):
    def test_both_routes_need_a_token(self):
        for path in (URL, f"{URL}/7013"):
            status, body, _ = self.get(path, token=None)
            self.assertEqual(status, 401, path)
            self.assertEqual(body["detail"]["error"], "unauthorized")

    def test_a_wrong_token_and_a_suspended_account_are_401(self):
        self.assertEqual(self.get(token="not-a-real-token")[0], 401)
        gone = users_store.create_user("gone@example.com", status="suspended", db=self.db)
        token = users_store.issue_invite_token(gone.id, db=self.db)
        self.assertEqual(self.get(token=token)[0], 401)

    def test_a_signed_in_reader_gets_the_card(self):
        self.assertEqual(self.get()[0], 200)

    def test_the_router_carries_its_own_gate_so_mounting_it_anywhere_is_gated(self):
        deps = [d.dependency for d in ufc_fights.router.dependencies]
        from api.auth import require_paid_access
        self.assertIn(require_paid_access, deps)

    def test_app_py_mounts_it_outside_the_public_demo_group(self):
        text = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(ufc_fights_router)\n", text.replace("\r\n", "\n"))
        self.assertNotIn("ufc_fights_router, dependencies", text)

    def test_public_demo_mode_cannot_open_it(self):
        """APP_PUBLIC_DEMO empties app.py's `_authed_paid` group; this route is not in it, so it must still answer 401."""
        code = (
            "import asyncio, os, sys\n"
            "os.environ['APP_PUBLIC_DEMO'] = '1'\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import api.app as app_module\n"
            "assert app_module.PUBLIC_DEMO is True\n"
            "async def call(path):\n"
            "    got = {}\n"
            "    async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}\n"
            "    async def send(m):\n"
            "        if m['type'] == 'http.response.start': got['status'] = m['status']\n"
            "    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'GET', 'path': path,\n"
            "             'raw_path': path.encode(), 'root_path': '', 'scheme': 'http', 'query_string': b'', 'headers': [],\n"
            "             'client': ('127.0.0.1', 1), 'server': ('t', 80)}\n"
            "    await app_module.app(scope, receive, send)\n"
            "    return got['status']\n"
            "print('STATUS', asyncio.run(call('/ufc/fight-night')), asyncio.run(call('/ufc/fight-night/123')),\n"
            "      asyncio.run(call('/health')))\n")
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("STATUS")]
        self.assertTrue(line, proc.stderr[-1500:])
        self.assertEqual(line[0].split()[1:], ["401", "401", "200"], "demo mode opened a gated route, or /health stopped answering")


# -- the shape ----------------------------------------------------------------------------------------

class TheShape(FightNightCase):
    def test_the_event_and_its_bouts_in_card_order_main_event_first(self):
        body = self.ok()
        self.assertEqual(body["event"], {"event_id": "7013", "name": "Synthetic Championship Night", "short_name": "SCN 13",
                                         "date_utc": "2026-10-10T21:00Z", "status": "scheduled", "bout_count": 2,
                                         "development_show": False})
        self.assertEqual([b["bout_id"] for b in body["bouts"]], ["9101", "9102"])
        self.assertEqual([b["match_number"] for b in body["bouts"]], [1, 5])
        self.assertEqual([b["card_segment"] for b in body["bouts"]], ["main", "prelims"])
        self.assertEqual(body["generated_utc"], "2026-10-03T15:00:00Z")
        self.assertEqual(body["label"], ufc_read.LABEL)
        self.assertEqual(body["missing_bout_ids"], [])

    def test_a_bout_lists_both_fighters_the_card_slot_the_class_and_the_rounds(self):
        main = self.bout(self.ok(), "9101")
        self.assertEqual(main["fighter_a"], {"fighter_id": "101", "name": "Alex Archer", "nickname": None,
                                             "record": {"wins": 12, "losses": 4, "draws": 0}, "stance": "Orthodox",
                                             "weight_class": "Welterweight"})
        self.assertEqual(main["fighter_b"]["name"], "Ben Brawler")
        self.assertEqual((main["weight_class"], main["scheduled_rounds"], main["status"]), ("Welterweight", 5, "scheduled"))
        self.assertEqual(main["date_utc"], "2026-10-10T23:00Z")
        self.assertIsNone(main["result"])
        self.assertIsNone(main["unavailable"])

    def test_the_current_price_summary_is_the_data_layers(self):
        main = self.bout(self.ok(), "9101")
        ml = main["odds"]["moneyline"]
        self.assertEqual((ml["current"]["a"], ml["current"]["b"]), (-170, 145))
        self.assertEqual(ml["current"]["without_margin"], {"a": 0.6067, "b": 0.3933})
        self.assertEqual((ml["open"]["a"], ml["open"]["b"]), (-150, 130))
        self.assertIsNone(main["odds"]["method"])                 # the compact form: no method market
        self.assertIsNone(self.bout(self.ok(), "9102")["odds"])     # no price row for the prelim

    def test_the_sheet_is_the_data_layers_own_and_the_read_is_built_from_it(self):
        main = self.bout(self.ok(), "9101")
        sheet = matchup.matchup(self.store, "101", "102", now=NOW)
        self.assertEqual(main["sheet"], json.loads(json.dumps(sheet)))
        self.assertEqual(main["read"], json.loads(json.dumps(ufc_read.build_read(sheet))))
        self.assertEqual(main["sheet"]["as_of_source"], "scheduled_bout_start")
        self.assertEqual(main["read"]["a"]["name"], "Alex Archer")

    def test_every_evidence_path_in_the_served_read_resolves_in_the_served_sheet(self):
        from tests.test_ufc_read import evidence_entries
        for b in self.ok()["bouts"]:
            for entry in evidence_entries(b["read"]):
                found, value = ufc_read.resolve_path(b["sheet"], entry["path"])
                self.assertTrue(found, (b["bout_id"], entry))
                if not entry.get("derived"):
                    self.assertEqual(value, entry["value"])

    def test_the_data_age_is_the_newest_fetch_among_the_event_its_bouts_and_their_prices(self):
        self.assertEqual(self.ok()["data_updated_utc"], "2026-10-03T12:00:00Z")
        self.store.upsert("odds", [odds_row(fetched_utc="2026-10-03T14:30:00Z")])
        self.assertEqual(self.ok()["data_updated_utc"], "2026-10-03T14:30:00Z")

    def test_the_compact_sheet_is_a_strict_subset_and_the_read_is_unchanged(self):
        full, compact = self.ok(), self.ok(f"{URL}?sheet=compact")
        for f, c in zip(full["bouts"], compact["bouts"]):
            self.assertTrue(c["sheet"]["compact"])
            self.assertEqual(c["read"], f["read"])
            self.assertEqual(c["odds"], f["odds"])
            self.assertLess(len(json.dumps(c["sheet"])), len(json.dumps(f["sheet"])) / 2)
            for key in ("a", "b", "as_of", "bout", "differentials", "styles", "physical", "layoff"):
                self.assertEqual(c["sheet"][key], f["sheet"][key])
            for side in ("a", "b"):
                for key in ("sample", "record", "streak", "last_three"):
                    self.assertEqual(c["sheet"]["features"][side][key], f["sheet"]["features"][side][key])
                self.assertNotIn("figures", c["sheet"]["features"][side])
                self.assertNotIn("ufccom_career", c["sheet"]["features"][side])
        # asking for the compact form does not shrink what the next caller gets
        self.assertIn("figures", self.ok()["bouts"][0]["sheet"]["features"]["a"])

    def test_a_bad_sheet_parameter_is_refused(self):
        self.assertEqual(self.get(f"{URL}?sheet=huge")[0], 422)


# -- fail soft ------------------------------------------------------------------------------------------

class FailSoft(FightNightCase):
    def test_a_bout_whose_sheet_cannot_be_built_is_listed_with_the_reason_and_the_rest_of_the_card_serves(self):
        real = matchup.matchup

        def flaky(store, a, b, *args, **kw):
            if {a, b} == {"104", "105"}:
                raise RuntimeError("boom with /secret/path in it")
            return real(store, a, b, *args, **kw)

        errors = io.StringIO()
        with mock.patch.object(matchup, "matchup", flaky), contextlib.redirect_stderr(errors):
            body = self.ok()
        broken, fine = self.bout(body, "9102"), self.bout(body, "9101")
        self.assertIsNone(broken["sheet"])
        self.assertIsNone(broken["read"])
        self.assertEqual(broken["unavailable"], "The fact sheet for this bout could not be built.")
        self.assertEqual(broken["fighter_a"]["name"], "Dan Silva")          # still listed, with its fighters
        self.assertIsNotNone(fine["read"])
        self.assertNotIn("secret", json.dumps(body), "an exception's text must never reach the client")
        self.assertIn("error_id=", errors.getvalue())                        # it is logged for us

    def test_a_bout_with_no_second_fighter_says_so(self):
        self.store.upsert("bouts", [dict(self.store.bout_by_id()["9102"], fighter_b_id=None)])
        with contextlib.redirect_stderr(io.StringIO()):
            broken = self.bout(self.ok(), "9102")
        self.assertEqual(broken["unavailable"], "A fighter is not named for this bout yet.")
        self.assertIsNone(broken["fighter_b"]["fighter_id"])

    def test_a_failure_in_the_read_keeps_the_facts(self):
        with mock.patch.object(ufc_read, "build_read", side_effect=RuntimeError("no")), contextlib.redirect_stderr(io.StringIO()):
            body = self.ok()
        for b in body["bouts"]:
            self.assertIsNotNone(b["sheet"])
            self.assertIsNone(b["read"])
            self.assertEqual(b["unavailable"], "The written read for this bout could not be built, so only the facts are shown.")

    def test_a_cancelled_or_postponed_bout_is_listed_and_not_read(self):
        for status, word in (("canceled", "cancelled"), ("postponed", "postponed")):
            self.store.upsert("bouts", [dict(self.store.bout_by_id()["9102"], status=status)])
            b = self.bout(self.ok(), "9102")
            self.assertEqual(b["unavailable"], f"This bout is listed as {word}.")
            self.assertIsNone(b["sheet"])

    def test_a_bout_with_no_start_time_that_is_not_scheduled_says_so(self):
        self.store.upsert("bouts", [dict(self.store.bout_by_id()["9102"], status="final", date_utc=None)])
        with contextlib.redirect_stderr(io.StringIO()):
            b = self.bout(self.ok(), "9102")
        self.assertEqual(b["unavailable"], "This bout has no start time on file.")

    def test_a_dataset_that_only_the_sheets_need_is_a_503_too_and_not_fourteen_broken_bouts(self):
        for name in ("fight_stats", "odds"):
            with self.subTest(dataset=name):
                (self.dir / f"{name}.jsonl").write_text('{"bout_id": "x"}\nnot json\n', encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    status, body, _ = self.get()
                self.assertEqual((status, body["detail"]), (503, "UFC data is not readable right now"))
                self.dir.joinpath(f"{name}.jsonl").unlink()
                build_store(self.dir)                                   # put the world back for the next dataset

    def test_a_corrupt_dataset_is_a_503_with_a_plain_message_and_no_path(self):
        (self.dir / "bouts.jsonl").write_text('{"bout_id": "x"}\nnot json\n', encoding="utf-8")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, body, _ = self.get()
        self.assertEqual(status, 503)
        self.assertEqual(body["detail"], "UFC data is not readable right now")
        self.assertNotIn(str(self.dir), json.dumps(body))
        self.assertIn("could not be read", errors.getvalue())


# -- which event ----------------------------------------------------------------------------------------

class WhichEvent(FightNightCase):
    def test_the_next_card_is_the_soonest_scheduled_one_and_the_others_are_listed(self):
        self.add_event("7020", "Synthetic Fight Night 20", "2026-10-17T21:00Z", [("9201", "103", "104", 1, "main")])
        body = self.ok()
        self.assertEqual(body["event"]["event_id"], "7013")
        self.assertEqual([e["event_id"] for e in body["other_events"]], ["7013", "7020"])
        self.assertEqual(self.ok(f"{URL}/7020")["event"]["event_id"], "7020")

    def test_the_development_show_is_never_the_default_but_can_be_opened_by_id(self):
        self.add_event("7030", "Dana White's Contender Series: Season 10, Week 9", "2026-10-05T23:00Z",
                       [("9301", "103", "105", 1, "main")])
        body = self.ok()
        self.assertEqual(body["event"]["event_id"], "7013", "a development show came first in time but is not the next UFC card")
        flags = {e["event_id"]: e["development_show"] for e in body["other_events"]}
        self.assertEqual(flags, {"7030": True, "7013": False})
        dwcs = self.ok(f"{URL}/7030")
        self.assertTrue(dwcs["event"]["development_show"])
        self.assertEqual([b["bout_id"] for b in dwcs["bouts"]], ["9301"])

    def test_with_only_a_development_show_upcoming_it_is_the_fallback(self):
        self.store.upsert("events", [dict(self.store.event_by_id()["7013"], status="final")])
        self.add_event("7030", "Dana White's Contender Series: Season 10, Week 9", "2026-10-05T23:00Z",
                       [("9301", "103", "105", 1, "main")])
        self.assertEqual(self.ok()["event"]["event_id"], "7030")

    def test_a_stale_scheduled_event_and_a_finished_one_are_not_upcoming(self):
        self.add_event("7040", "Stale", "2026-09-28T21:00Z", [("9401", "103", "104", 1, "main")])
        self.add_event("7041", "Done", "2026-10-04T21:00Z", [("9402", "103", "104", 1, "main")], status="final")
        ids = [e["event_id"] for e in self.ok()["other_events"]]
        self.assertEqual(ids, ["7013"])

    def test_a_card_that_started_a_few_hours_ago_is_still_tonights_card(self):
        self.add_event("7050", "Under way", "2026-10-03T08:00Z", [("9501", "103", "104", 1, "main")], status="in_progress")
        self.assertEqual(self.ok()["event"]["event_id"], "7050")

    def test_an_unknown_event_is_404_and_says_so_plainly(self):
        status, body, _ = self.get(f"{URL}/nope")
        self.assertEqual((status, body["detail"]), (404, "no UFC event with that id is on file"))

    def test_no_event_at_all_is_a_200_that_says_so_and_when_the_data_was_last_updated(self):
        with tempfile.TemporaryDirectory() as empty:
            datasvc.use_data_dir(Path(empty))
            body = self.ok()
        self.assertIsNone(body["event"])
        self.assertEqual(body["bouts"], [])
        self.assertEqual(body["reason"], "No UFC event is scheduled in our data right now.")
        self.assertIsNone(body["data_updated_utc"])
        self.assertEqual(body["other_events"], [])

    def test_only_finished_events_is_no_event_with_the_newest_fetch_as_the_data_date(self):
        only_final = self.dir.parent / "final_only"
        build_store(only_final, before="2026-10-01")          # every bout in the synthetic world is before the future card
        datasvc.use_data_dir(only_final)
        body = self.ok()
        self.assertIsNone(body["event"])
        self.assertEqual(body["data_updated_utc"], "2026-10-03T12:00:00Z")


# -- a card that is under way or over ---------------------------------------------------------------------

class AFinishedBout(FightNightCase):
    def test_a_finished_bout_is_read_as_it_was_going_in_and_its_result_is_shown_beside_it(self):
        body = self.ok(f"{URL}/7009")
        self.assertEqual(body["event"]["status"], "final")
        b = body["bouts"][0]
        self.assertEqual(b["bout_id"], "9009")
        self.assertEqual(b["result"]["outcome"], "decided")
        self.assertEqual(b["result"]["winner_name"], "Ben Brawler")
        self.assertEqual(b["result"]["method_words"], "unanimous decision")
        sheet = b["sheet"]
        self.assertEqual(sheet["as_of"], "2026-03-14T22:00:00Z")
        self.assertEqual(sheet["as_of_source"], "argument")
        self.assertEqual(sheet["bout"]["bout_id"], "9009")
        self.assertEqual(sheet["previous_meetings"], [], "the fight itself must never be one of the previous meetings")
        self.assertEqual(sheet["features"]["a"]["record"]["fights"], 3)          # 9001, 9003, 9006; not 9009 or later
        self.assertIn("This bout is listed as final. The read describes the fight going in and does not use how it turned out.",
                      b["read"]["notices"])
        self.assertFalse([s for s in b["read"]["history"]["previous_meetings"]])

    def test_the_prices_of_a_finished_bout_are_attached_when_there_are_some(self):
        self.store.upsert("odds", [odds_row(bout_id="9009", event_id="7009", is_closing=True,
                                            a_ml_current=130, b_ml_current=-150, a_ml_open=120, b_ml_open=-140)])
        b = self.ok(f"{URL}/7009")["bouts"][0]
        self.assertEqual(b["sheet"]["odds"]["moneyline"]["current"]["a"], 130)
        self.assertIn("closing prices", b["read"]["market_view"]["sentences"][0])
        self.assertFalse([m for m in b["sheet"]["missing"] if m["figure"] == "odds"])

    def test_without_prices_the_finished_bout_says_so(self):
        b = self.ok(f"{URL}/7009")["bouts"][0]
        self.assertIsNone(b["sheet"]["odds"])
        self.assertTrue([m for m in b["sheet"]["missing"] if m["figure"] == "odds"])
        self.assertFalse(b["read"]["market_view"]["available"])

    def test_a_drawn_bout_has_no_winner(self):
        row = dict(self.store.bout_by_id()["9009"], winner_id=None, result_method="DRAW")
        self.store.upsert("bouts", [row])
        r = self.ok(f"{URL}/7009")["bouts"][0]["result"]
        self.assertEqual((r["outcome"], r["winner_name"]), ("draw", None))


# -- loaded once --------------------------------------------------------------------------------------------

class LoadedOnce(FightNightCase):
    def count_reads(self):
        counts = {}
        real = jsonl.read_jsonl

        def counting(path):
            counts[Path(path).name] = counts.get(Path(path).name, 0) + 1
            return real(path)

        return counts, mock.patch.object(jsonl, "read_jsonl", counting)

    def test_each_dataset_is_read_once_however_many_requests_come(self):
        counts, patch = self.count_reads()
        with patch:
            for _ in range(4):
                self.ok()
            self.ok(f"{URL}?sheet=compact")
            self.ok(f"{URL}/7013")
        self.assertTrue(counts)
        self.assertEqual({k: v for k, v in counts.items() if v != 1}, {}, counts)

    def test_the_payload_is_built_once_per_store_version_and_again_after_a_file_changes(self):
        built = []
        real = ufc_read.build_read

        def counting(sheet, **kw):
            built.append(1)
            return real(sheet, **kw)

        with mock.patch.object(ufc_read, "build_read", counting):
            self.ok()
            first = len(built)
            self.ok()
            self.ok(f"{URL}?sheet=compact")
            self.assertEqual(len(built), first, "a repeat request rebuilt the card")
            self.assertEqual(first, 2)
            self.store.upsert("odds", [odds_row(a_ml_current=-200, b_ml_current=170)])
            body = self.ok()
            self.assertEqual(len(built), first * 2, "a changed file must be picked up on the next request")
        self.assertEqual(self.bout(body, "9101")["odds"]["moneyline"]["current"]["a"], -200)

    def test_concurrent_first_requests_read_each_file_once_and_agree(self):
        counts, patch = self.count_reads()
        results, errors = [], []
        barrier = threading.Barrier(6)

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(self.ok())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with patch:
            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 6)
        self.assertEqual({k: v for k, v in counts.items() if v != 1}, {}, counts)
        self.assertTrue(all(r["bouts"] == results[0]["bouts"] for r in results))

    def test_nothing_that_varies_with_the_clock_is_baked_into_the_cached_read(self):
        a = self.ok()
        later = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
        with mock.patch.object(datasvc, "_now", lambda: later):
            b = self.ok()
        self.assertEqual(a["generated_utc"], "2026-10-03T15:00:00Z")
        self.assertEqual(b["generated_utc"], "2026-10-09T09:00:00Z")
        for x, y in zip(a["bouts"], b["bouts"]):
            self.assertEqual(x["read"], y["read"])
            self.assertFalse([s for s in x["read"]["market_view"]["sentences"] if "hours before this page" in s])


# -- words on the way out ------------------------------------------------------------------------------------

class WhatTheRouteSays(FightNightCase):
    def test_no_reason_or_label_the_route_writes_reads_as_a_pick_or_a_dash(self):
        strings = [ufc_fights.NO_EVENT_REASON, ufc_read.LABEL]
        self.store.upsert("bouts", [dict(self.store.bout_by_id()["9102"], status="canceled")])
        strings.append(self.bout(self.ok(), "9102")["unavailable"])
        for text in strings:
            self.assertNotIn("—", text)
            self.assertNotRegex(text.lower(), r"\bpick|\block\b|profit|guarantee")


if __name__ == "__main__":
    unittest.main()
