"""Serving the NFL brief: GET /analyst/nfl/{date}/{away}/{home}, the public sample with a sport, and the page.

The ledger rows come from a real prepare, check and publish into a temp folder, so what is served is
what the pilot froze. The route functions are plain callables (the pattern of tests/test_analyst_api.py);
the gate and the mount are proved by driving the REAL api.app over ASGI (the pattern of
tests/test_api_surface_auth.py), because a router-level dependency is invisible to a direct call. The
page half runs the real analyst.js, sample.js and analyst_nfl.js under node against a small fake DOM.
Everything that needs FastAPI is skipped when it is absent; the rest imports without it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
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

from src.analyst import PILOT_LABEL, ledger, nfl_cli, nfl_pilot
from tests import nfl_analyst_fixtures as F
from tests import test_analyst_web as W
from tests import test_sample_brief as S

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"


def published_rows(root: Path, *, graded: bool = False) -> list:
    """The NFL pilot's ledger rows after a real prepare, check and publish of BUF at KC (and a grade),
    written under `root`. The caller keeps `root` alive: the frozen packet file the rows point at
    lives there, and a page that reads it needs it."""
    store = F.make_store(root / "league")
    out = []
    assert nfl_pilot.prepare(F.DATE, "BUF@KC", cfg=F.CFG, root=root, store=store, rows=F.odds_rows(),
                             now=lambda: F.NOW, out=out.append) == 0, out
    folder = nfl_pilot.game_folder(F.DATE, "BUF", "KC", root)
    packet = json.loads((folder / "packet.json").read_text(encoding="utf-8"))
    response = root / "answer.json"
    response.write_text(json.dumps(F.good_output(packet)), encoding="utf-8")
    assert nfl_pilot.check(str(folder), str(response), out=out.append, now=lambda: F.NOW) == 0, out
    assert nfl_pilot.publish(str(folder), str(response), model="claude-sonnet-5-5", cfg=F.CFG, root=root,
                             now=lambda: F.NOW, out=out.append) == 0, out
    path = nfl_pilot.store_paths(root)["store"]
    if graded:
        store.game_by_id()[F.GAME_ID].update(status="final", away_score=17, home_score=27)
        nfl_cli.execute_grade(F.DATE, store=store, now=lambda: F.NOW + timedelta(hours=9),
                              out=lambda *_: None, store_path=path)
    return ledger.rows(path)


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
class TheRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.rows = published_rows(Path(cls._tmp.name), graded=True)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        from api import analyst_nfl
        self.api = analyst_nfl

    def get(self, date=F.DATE, away="BUF", home="KC", rows=None):
        with mock.patch.object(self.api, "_rows", return_value=self.rows if rows is None else rows):
            return self.api.get_nfl_analysis(date, away, home)

    def test_a_published_game_is_served_with_the_session_label_provenance_calls_and_grade(self):
        body = self.get()
        self.assertTrue(body["available"])
        self.assertEqual(body["label"], PILOT_LABEL)
        self.assertIsNone(body["reason"])
        a = body["analysis"]
        self.assertEqual((a["game_id"], a["date"], a["away"], a["home"]), (F.GAME_ID, F.DATE, "BUF", "KC"))
        self.assertEqual((a["provenance"], a["sport"], a["version"]), ("session_assisted", "nfl", 1))
        self.assertEqual(a["first_pitch_utc"], F.KICKOFF)
        self.assertEqual([c["slot_id"] for c in a["calls"]], ["moneyline", "spread", "total"])
        self.assertEqual(a["summary_status"], "ok")
        self.assertTrue(a["graded"])
        self.assertEqual(a["final"], {"away_score": 17, "home_score": 27})
        ml = a["calls"][0]
        self.assertEqual((ml["verdict"], ml["family"], ml["title"], ml["result"]),
                         ("TAKE_OTHER_SIDE", "moneyline", "Moneyline", "LOSS"))
        self.assertEqual(a["calls"][1]["title"], "Point spread")
        self.assertEqual(ml["case_against"]["claim"].startswith("The home side scored"), True)
        self.assertIn(a["calls"][1]["would_have"]["result"], ("WIN", "LOSS"))

    def test_what_the_brief_could_not_use_is_read_from_the_frozen_packet_file(self):
        missing = self.get()["analysis"]["missing"]
        self.assertIsInstance(missing, list)
        self.assertEqual({"props", "weather"} <= {m["item"] for m in missing}, True)

    def test_the_words_a_reader_sees_carry_no_internal_vocabulary(self):
        text = json.dumps(self.get()["analysis"]["calls"]) + self.get()["analysis"]["summary"]
        for word in ("packet", "repo "):
            self.assertNotIn(word, text.lower())

    def test_club_codes_are_read_any_way_the_nfl_map_reads_them_and_dates_are_checked(self):
        self.assertTrue(self.get(away="buf", home="kc")["available"])
        self.assertTrue(self.get(away="Bills", home="Chiefs")["available"])
        from fastapi import HTTPException
        for date, away, home in (("2025-13-45", "BUF", "KC"), ("tomorrow", "BUF", "KC"), (F.DATE, "XXX", "KC"),
                                 (F.DATE, "BUF", "../etc"), (F.DATE, "BUF", "K" * 30)):
            with self.assertRaises(HTTPException) as ctx:
                self.get(date, away, home)
            self.assertEqual(ctx.exception.status_code, 400, (date, away, home))

    def test_a_game_with_nothing_published_says_so_plainly_and_is_not_an_error(self):
        for body in (self.get(home="NE"), self.get(date="2025-11-02"), self.get(rows=[])):
            self.assertFalse(body["available"])
            self.assertIsNone(body["analysis"])
            self.assertEqual(body["reason"], "No analysis has been published for this game.")
            self.assertEqual(body["label"], PILOT_LABEL)

    def test_the_other_way_round_is_not_the_same_game(self):
        self.assertFalse(self.get(away="KC", home="BUF")["available"])

    def test_a_request_never_calls_the_model_or_the_network(self):
        from src.analyst import analyst as A
        with mock.patch.object(A, "urllib_post", side_effect=AssertionError("network used")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            self.assertTrue(self.get()["available"])

    def test_the_module_reads_only_the_nfl_pilot_ledger_and_imports_no_model_code(self):
        text = (ROOT / "api" / "analyst_nfl.py").read_text(encoding="utf-8")
        for needle in ("analyze(", "urllib", "nfl_analyst", "ANTHROPIC", "http_post", "analyst_v1.jsonl",
                       "analyst_pilot_v1"):
            self.assertNotIn(needle, text)
        self.assertIn("nfl_pilot.STORE", text)

    def test_the_cache_follows_the_file(self):
        self.api.reset_cache_for_tests()
        with mock.patch.object(self.api, "_signature", side_effect=[(1, 1), (1, 1), (2, 2)]), \
                mock.patch.object(self.api.ledger, "rows", return_value=["x"]) as read:
            self.api._rows()
            self.api._rows()
            self.assertEqual(read.call_count, 1)
            self.api._rows()
            self.assertEqual(read.call_count, 2)
        self.api.reset_cache_for_tests()

    def test_a_missing_ledger_is_an_empty_one(self):
        self.api.reset_cache_for_tests()
        with mock.patch.object(self.api, "_signature", return_value=(None, None)):
            self.assertEqual(self.api._rows(), [])
        self.api.reset_cache_for_tests()

    def test_it_is_in_the_app_behind_the_paid_gate_and_nothing_else_moved(self):
        from api import app as app_module
        self.assertIn("/analyst/nfl/{date}/{away}/{home}", app_module.app.openapi()["paths"])
        mount = (ROOT / "api" / "app.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("app.include_router(analyst_nfl_router, dependencies=_authed_paid)\n", mount)
        status, _ = request(app_module.app, "GET", f"/analyst/nfl/{F.DATE}/BUF/KC")
        self.assertEqual(status, 401)
        # the MLB and UFC routes keep their own paths
        paths = app_module.app.openapi()["paths"]
        for kept in ("/analyst/{date}/{away}/{home}", "/analyst/record", "/analyst/ufc/{event_id}"):
            self.assertIn(kept, paths)

    def test_the_mlb_module_still_declares_exactly_its_two_routes(self):
        from api import analyst as mlb
        self.assertEqual(sorted(r.path for r in mlb.router.routes), ["/analyst/{date}/{away}/{home}"])
        self.assertEqual(sorted(r.path for r in mlb.public_router.routes), ["/analyst/record"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheSampleWithASport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.rows = published_rows(cls.root)
        (cls.root / "config").mkdir()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        from api import analyst as api_analyst
        from api import analyst_nfl
        from api import sample
        self.mlb, self.nfl, self.sample = api_analyst, analyst_nfl, sample

    def get(self, config, rows=None):
        path = self.root / "config" / "sample_brief.json"
        path.write_text(config if isinstance(config, str) else json.dumps(config), encoding="utf-8")
        with mock.patch.object(self.sample, "repo_root", return_value=self.root), \
                mock.patch.object(self.nfl, "_rows", return_value=self.rows if rows is None else rows), \
                mock.patch.object(self.mlb, "_pilot_rows", side_effect=AssertionError("the MLB pilot was read")), \
                mock.patch.object(self.mlb, "_rows", side_effect=AssertionError("the main ledger was read")):
            return self.sample.get_sample_brief()

    def test_a_game_with_sport_nfl_is_served_from_the_nfl_pilot_and_never_the_mlb_one(self):
        body = self.get({"date": F.DATE, "away": "BUF", "home": "KC", "sport": "nfl"})
        self.assertTrue(body["available"])
        self.assertEqual((body["sport"], body["label"], body["first_pitch_utc"]), ("nfl", PILOT_LABEL, F.KICKOFF))
        self.assertEqual(body["analysis"]["game_id"], F.GAME_ID)
        self.assertEqual(body["analysis"]["provenance"], "session_assisted")
        self.assertEqual(body["published_utc"], "2025-10-26T17:25:00Z")

    def test_sport_defaults_to_mlb_and_an_unknown_sport_serves_nothing(self):
        self.assertEqual(self.sample.designated.__name__, "designated")
        with mock.patch.object(self.sample, "repo_root", return_value=self.root):
            (self.root / "config" / "sample_brief.json").write_text(
                json.dumps({"date": "2026-10-03", "away": "NYY", "home": "TB"}), encoding="utf-8")
            self.assertEqual(self.sample.designated(),
                             {"date": "2026-10-03", "away": "NYY", "home": "TB", "sport": "mlb"})
        for sport in ("nba", "NFL", 5, None, ""):
            body = self.get({"date": F.DATE, "away": "BUF", "home": "KC", "sport": sport})
            self.assertFalse(body["available"], sport)
            self.assertIsNone(body["analysis"])

    def test_an_nfl_designation_the_pilot_has_not_published_is_not_available(self):
        self.assertFalse(self.get({"date": F.DATE, "away": "NE", "home": "KC", "sport": "nfl"})["available"])
        self.assertFalse(self.get({"date": F.DATE, "away": "BUF", "home": "KC", "sport": "nfl"}, rows=[])["available"])

    def test_an_mlb_designation_is_unchanged_and_carries_its_sport(self):
        with mock.patch.object(self.sample, "repo_root", return_value=self.root), \
                mock.patch.object(self.nfl, "_rows", side_effect=AssertionError("the NFL pilot was read")), \
                mock.patch.object(self.mlb, "_pilot_rows", return_value=[]):
            (self.root / "config" / "sample_brief.json").write_text(
                json.dumps({"date": "2026-10-03", "away": "NYY", "home": "TB"}), encoding="utf-8")
            body = self.sample.get_sample_brief()
        self.assertFalse(body["available"])


class TheShippedConfig(unittest.TestCase):
    def test_the_shipped_sample_is_valid_and_its_sport_if_present_is_known(self):
        shipped = json.loads((ROOT / "config" / "sample_brief.json").read_text(encoding="utf-8"))
        self.assertTrue(shipped is None or {"date", "away", "home"} <= set(shipped))
        self.assertIn((shipped or {}).get("sport", "mlb"), ("mlb", "nfl"))


# ---------------------------------------------------------------------------
# the page, under node
# ---------------------------------------------------------------------------

def nfl_calls():
    return [
        W.call("moneyline", "TAKE_OTHER_SIDE", "moneyline", selection="BUF", price=175, title="Moneyline"),
        W.call("spread", "PASS", "spread", selection="BUF +3.5", price=-110, title="Point spread"),
        W.call("total", "PASS", "total", selection="Under 47.5", price=-110, title="Game total"),
    ]


class StaticChecks(unittest.TestCase):
    def test_the_spread_family_is_shown_between_the_run_line_and_the_total(self):
        src = (JS / "analyst.js").read_text(encoding="utf-8")
        self.assertIn('FAMILY_ORDER = ["moneyline", "run_line", "spread", "total", "team_total", "prop"]', src)
        self.assertIn('spread: "Point spread"', src)

    def test_the_nfl_page_module_reads_one_route_and_calls_no_model(self):
        src = (JS / "analyst_nfl.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"`(/analyst/[^`]*)`", src),
                         ["/analyst/nfl/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}"])
        for needle in ("anthropic", "api.anthropic", "ANTHROPIC", "Authorization"):
            self.assertNotIn(needle, src)
        self.assertIn("renderAnalystSection", src)

    def test_the_router_has_the_nfl_brief_route_and_the_card_routes_are_unchanged(self):
        main = (JS / "main.js").read_text(encoding="utf-8")
        self.assertIn('import { renderNflBrief } from "./analyst_nfl.js";', main)
        self.assertIn('if (route === "brief" && rest.length >= 3) {', main)
        self.assertIn("await renderNflBrief(main, rest[0], rest[1], rest[2]);", main)
        self.assertIn('await renderCardRecord(main, { sport: "nfl", rule: NFL_RETIRED_RULE });', main)
        self.assertIn('await renderCard(main, { sport: "nfl" });', main)

    def test_no_banned_word_is_in_any_string_the_nfl_page_can_show(self):
        src = (JS / "analyst_nfl.js").read_text(encoding="utf-8")
        offenders = [f"{name}: {lit[:60]!r}" for lit in W._string_literals(src)
                     for pattern, name in W.BANNED if re.search(pattern, lit)]
        self.assertEqual(offenders, [])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheSectionUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(W.HARNESS, encoding="utf-8")
        Path(cls._tmp.name, "heading.mjs").write_text(
            'import { gameHeading } from "./analyst_nfl.js";\n'
            'const a = process.argv[2] ? JSON.parse(process.argv[2]) : null;\n'
            'console.log("@@" + JSON.stringify(gameHeading("2025-10-26", "BUF", "KC", a)));\n', encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def render(self, data):
        env = dict(os.environ, SCENARIO=json.dumps({"kind": "section", "data": data}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])

    def nfl_view(self, **over):
        data = W.view(nfl_calls(), date="2025-10-26", away="BUF", home="KC", game_id=F.GAME_ID, sport="nfl")
        data["label"] = PILOT_LABEL
        data["analysis"].update(over)
        return data

    def test_calls_are_grouped_moneyline_then_spread_then_total_with_the_spread_named_plainly(self):
        out = self.render(self.nfl_view())
        self.assertEqual(out["families"], ["moneyline", "spread", "total"])
        self.assertIn("Point spread", out["text"])
        self.assertEqual([c["verdictWord"] for c in out["calls"]], ["Take the other side", "Pass", "Pass"])

    def test_an_nfl_brief_says_kickoff_and_the_mlb_one_still_says_first_pitch(self):
        self.assertIn("Published before kickoff and graded afterward", self.render(self.nfl_view())["text"])
        mlb = W.view([W.call("moneyline", "TAKE", "moneyline")])
        self.assertIn("Published before first pitch and graded afterward", self.render(mlb)["text"])

    def test_the_label_the_server_sent_is_printed_and_a_pass_is_as_plain_as_a_take(self):
        out = self.render(self.nfl_view())
        self.assertEqual(out["firstParagraph"], PILOT_LABEL)
        self.assertEqual(out["labelCount"], 1)
        self.assertEqual(sorted({c["cls"] for c in out["calls"]}),
                         ["an-call an-call--pass", "an-call an-call--take_other_side"])

    def test_the_heading_names_the_game_and_the_kickoff(self):
        def heading(analysis):
            proc = subprocess.run(["node", "heading.mjs", json.dumps(analysis)], cwd=self._tmp.name,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            return json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])
        self.assertTrue(heading(None).startswith("BUF at KC, 2025-10-26"))
        self.assertNotIn("kickoff", heading(None))
        self.assertIn("(kickoff ", heading({"first_pitch_utc": F.KICKOFF}))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheSamplePageUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(S.HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def render(self, data):
        env = dict(os.environ, SCENARIO=json.dumps({"kind": "render", "data": data}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        out = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])
        self.assertFalse(out["crashed"], out["crashed"])
        return out

    def nfl_brief(self):
        data = S.brief()
        data["sport"] = "nfl"
        data["first_pitch_utc"] = F.KICKOFF
        data["analysis"].update(away="BUF", home="KC", date=F.DATE, sport="nfl", first_pitch_utc=F.KICKOFF)
        return data

    def test_an_nfl_sample_says_nfl_and_kickoff_not_mlb_and_first_pitch(self):
        out = self.render(self.nfl_brief())
        self.assertIn("BUF at KC, 2025-10-26 (NFL)", out["text"])
        self.assertNotIn("MLB postseason)", out["text"])
        self.assertTrue(any(re.match(r"Kickoff ", text) for _hook, text in out["facts"]), out["facts"])
        self.assertFalse(any(text.startswith("First pitch") for _hook, text in out["facts"]), out["facts"])
        self.assertIn("Published before kickoff", out["text"])
        self.assertEqual(out["labelParagraphs"], [PILOT_LABEL])

    def test_an_mlb_sample_is_what_it_was(self):
        out = self.render(S.brief())
        self.assertIn("NYY at TB, 2026-10-03 (MLB postseason)", out["text"])
        self.assertTrue(any(text.startswith("First pitch") for _hook, text in out["facts"]))
        self.assertIn("Published before first pitch", out["text"])


if __name__ == "__main__":
    unittest.main()
