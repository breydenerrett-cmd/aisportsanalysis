"""The learning loop as the site and the operator see it: the stats split by version, the routes, the
operator CLI, the director request, and that the whole package loads without FastAPI.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import stats
from src.hounds.learning import cli, director, ledger as L, lessons, pause, rules, scorecard, views
from src.ledger.chain import HashChainLedger
from tests import _hounds_fixtures as HF
from tests import _learning_fixtures as F

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)


def world_with_promotion(root: Path):
    """The synthetic hounds world plus: a promotion of the pack hound 'charlie' to version 2 and one bet
    stamped version 2 (the pack ledger gets a plain-looking row)."""
    src = HF.make_world(root)
    scope = L.Scope.house(root / "evidence")
    L.log_for(scope).append(L.K_PROMOTION, now=F.utc("2026-10-03T00:00:00Z"), scope="house", hound_id="charlie",
                            lineage_key="charlie", challenger_id="c-77", from_version=1, to_version=2,
                            params={}, applied=True, effective_utc="2026-10-03T00:00:00Z")
    ledger = HashChainLedger(root / "evidence/hounds_house_v1.jsonl")
    # make_world wrote a plain JSONL; rewrite it as the loop sees it, then add a version-2 bet
    rows = [json.loads(line) for line in (root / "evidence/hounds_house_v1.jsonl").read_text().splitlines() if line]
    (root / "evidence/hounds_house_v1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows + [{
            "hound_id": "charlie", "date": "2026-10-04", "event_id": "E6", "sport": "mlb", "market": "h2h",
            "selection": "home", "price_average": 110, "price_best": 112, "book_count": 6,
            "lock_utc": HF.DECIDE, "start_utc": HF.START, "reason": "v2", "who_decided": "rule",
            "segment": "forward", "bet_id": "p9", "book": "bk2", "hound_version": 2}]) + "\n", encoding="utf-8")
    del ledger
    return src, scope


class StatsSplitByVersion(unittest.TestCase):
    def test_a_promoted_pack_hound_keeps_its_old_record_and_the_new_version_starts_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, _scope = world_with_promotion(Path(tmp))
            book = stats.build(src)
        self.assertIn("charlie@v1", book.hounds)
        old, new = book.hounds["charlie@v1"].summary, book.hounds["charlie"].summary
        self.assertEqual(old.status, "retired")
        self.assertTrue(old.retired.cause.startswith("superseded by version 2"))
        self.assertEqual(old.record.bets, 1)                      # its one graded forward bet, kept
        self.assertEqual(old.record.units_recorded_price, 1.12)
        self.assertEqual(new.record.bets, 0)                      # v2's bet is not graded yet
        self.assertEqual(new.status, "running")
        self.assertIn("charlie@v1", [s.id for s in stats.graveyard(book)])
        self.assertNotIn("charlie@v1", [s.id for s in stats.leaderboard(book)])
        self.assertIn("charlie", [s.id for s in stats.leaderboard(book)])

    def test_the_book_carries_every_measurable_clv_with_its_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = HF.make_world(Path(tmp))
            book = stats.build(src)
        self.assertTrue(book.clv_bets)
        for hid, event, market, day, pts in book.clv_bets:
            self.assertIn(hid, book.hounds)
            self.assertTrue(event)
            self.assertIsInstance(pts, float)

    def test_versions_from_book_lists_them_oldest_first_with_the_current_one_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, _scope = world_with_promotion(Path(tmp))
            book = stats.build(src)
        versions = views.versions_from_book("charlie", book)
        self.assertEqual([(v["id"], v["version_no"], v["current"]) for v in versions],
                         [("charlie@v1", 1, False), ("charlie", 2, True)])
        self.assertEqual(versions[0]["record"]["bets"], 1)
        # asking for an archived version's lineage finds the same chain
        self.assertEqual([v["id"] for v in views.versions_from_book("charlie@v1", book)], ["charlie@v1", "charlie"])

    def test_no_promotion_means_the_stats_are_what_they_always_were(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = HF.make_world(Path(tmp))
            book = stats.build(src)
        self.assertFalse([i for i in book.hounds if "@v" in i])


class Payloads(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.scopes = {"house": L.Scope.house(self.root / "h"), "user": L.Scope.user(self.root / "u")}

    def test_before_any_scorecard_the_page_says_so_instead_of_inventing_numbers(self):
        out = views.learning_payload(self.scopes)
        self.assertFalse(out["computed"])
        self.assertIn("No daily scorecard", out["message"])
        self.assertEqual(out["system"], {})
        self.assertTrue(out["paper_only"])
        self.assertIn("not_advice", out)
        self.assertEqual(out["rule_summary"]["looks"], [100, 150, 200, 250, 300])
        self.assertEqual(out["rule_summary"]["auto_pause"]["hit_rate_floor"], 0.4)
        self.assertEqual(out["lessons"], {"count": 0, "latest": []})

    def test_after_a_scorecard_the_page_has_the_three_lines_and_the_pause(self):
        card = scorecard.compute(self.scopes["house"], now=NOW, clv_bets=[], hound_info={}, matured_fn=lambda p: None)
        scorecard.store(self.scopes["house"], card, now=NOW)
        out = views.learning_payload(self.scopes)
        self.assertTrue(out["computed"])
        self.assertEqual(out["as_of"], "2026-12-20")
        system = out["system"]
        self.assertIsNone(system["promotion_hit_rate"]["rate"])
        self.assertIn("30", system["vs_random"]["windows"])
        self.assertFalse(system["paused"])
        self.assertEqual(out["chain"], {"house": True, "user": True})

    def test_a_pause_shows_with_its_reason(self):
        card = scorecard.compute(self.scopes["user"], now=NOW, clv_bets=[], hound_info={}, matured_fn=lambda p: None)
        scorecard.store(self.scopes["user"], card, now=NOW)
        pause.pause(self.scopes["user"], "promotion hit rate 0.30 over 12 matured promotions", now=NOW)
        card2 = scorecard.compute(self.scopes["user"], now=NOW + timedelta(days=1), clv_bets=[], hound_info={},
                                  matured_fn=lambda p: None)
        scorecard.store(self.scopes["user"], card2, now=NOW + timedelta(days=1))
        out = views.learning_payload(self.scopes)
        self.assertTrue(out["system"]["paused"])
        self.assertEqual(out["system"]["pause_reasons"][0]["scope"], "user")
        self.assertIn("0.30", out["system"]["pause_reasons"][0]["reason"])

    def test_lessons_are_paginated_filtered_and_newest_first(self):
        scope = self.scopes["house"]
        for i in range(7):
            F.propose_raw(scope, cid=f"c-{i}", hound_id="professor_paws" if i < 5 else "totals_terrier",
                          created=f"2026-11-{i + 1:02d}T01:00:00Z", category="stats")
            c = L.read_state(scope).challengers[f"c-{i}"]
            lessons.write(scope, c, {"outcome": "retired", "reason": "harm"}, None, now=F.utc(f"2026-12-{i + 1:02d}T00:00:00Z"))
        page = views.lessons_payload(self.scopes, hound=None, category=None, page=1, page_size=3)
        self.assertEqual((page["total"], page["pages"], len(page["items"])), (7, 3, 3))
        self.assertEqual([r["utc"][:10] for r in page["items"]], ["2026-12-07", "2026-12-06", "2026-12-05"])
        mine = views.lessons_payload(self.scopes, hound="professor_paws", category=None, page=1, page_size=10)
        self.assertEqual(mine["total"], 5)
        self.assertEqual(views.lessons_payload(self.scopes, hound=None, category="math", page=1, page_size=10)["total"], 0)

    def test_the_lineage_lists_live_failed_and_promoted_challengers_around_the_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, scope = world_with_promotion(Path(tmp))
            book = stats.build(src)
            F.propose_raw(scope, cid="c-live", hound_id="charlie", created="2026-10-05T00:00:00Z")
            F.propose_raw(scope, cid="c-dead", hound_id="charlie", created="2026-10-06T00:00:00Z")
            L.log_for(scope).append(L.K_DECISION, now=F.utc("2026-10-20T00:00:00Z"), scope="house",
                                    challenger_id="c-dead", hound_id="charlie", outcome="retired", reason="harm")
            out = views.lineage_view("charlie", book, scope_map={"house": scope, "user": L.Scope.user(Path(tmp) / "u")})
        self.assertEqual([v["id"] for v in out["versions"]], ["charlie@v1", "charlie"])
        self.assertEqual([c["id"] for c in out["live_challengers"]], ["c-live"])
        self.assertEqual([c["id"] for c in out["tried_and_failed"]], ["c-dead"])
        self.assertEqual(out["tried_and_failed"][0]["outcome_reason"], "harm")
        self.assertTrue(out["paper_only"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.hounds import router as hounds_router
        from api.hounds_learning import router as learning_router
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.src, cls.house = world_with_promotion(root)
        cls.scopes = {"house": cls.house, "user": L.Scope.user(root / "u")}
        card = scorecard.compute(cls.house, now=NOW, clv_bets=[], hound_info={}, matured_fn=lambda p: None)
        scorecard.store(cls.house, card, now=NOW)
        cls._patches = [
            mock.patch.object(stats.Sources, "default", staticmethod(lambda: cls.src)),
            mock.patch.object(views, "scopes", lambda: cls.scopes),
            mock.patch.object(L, "default_scopes", lambda: cls.scopes),
        ]
        for p in cls._patches:
            p.start()
        stats.clear_cache()
        stats.get_book(cls.src)
        app = FastAPI()
        # the same order api/app.py uses: the literal paths first
        app.include_router(learning_router)
        app.include_router(hounds_router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        stats.clear_cache()
        cls._tmp.cleanup()

    def test_hounds_learning_is_the_scorecard_not_a_hound_id(self):
        r = self.client.get("/hounds/learning")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("system", body)
        self.assertTrue(body["computed"])
        self.assertIs(body["paper_only"], True)
        self.assertIn("rule_summary", body)

    def test_the_lessons_route(self):
        body = self.client.get("/hounds/learning/lessons?page_size=5").json()
        self.assertEqual(body["items"], [])
        self.assertIs(body["paper_only"], True)

    def test_the_lineage_route(self):
        r = self.client.get("/hounds/charlie/lineage")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual([v["id"] for v in body["versions"]], ["charlie@v1", "charlie"])
        self.assertEqual(self.client.get("/hounds/charlie@v1/lineage").status_code, 200)
        self.assertEqual(self.client.get("/hounds/nobody/lineage").status_code, 404)

    def test_the_race_still_serves_the_archived_version_as_a_hound(self):
        r = self.client.get("/hounds/charlie@v1")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "retired")

    def test_app_mounts_the_learning_router_before_the_hounds_router(self):
        text = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        self.assertLess(text.index("include_router(hounds_learning_router)"), text.index("include_router(hounds_router)"))


class OperatorCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cfg = self.root / "hounds_coach.json"
        self.cfg.write_text(json.dumps({"enabled": True}), encoding="utf-8")
        self.champ = self.root / "hounds_house_v1.jsonl"
        chain = HashChainLedger(self.champ)
        for i in range(50):
            day = F.day_n(i)
            chain.append({"kind": "hound_bet", "hound_id": "professor_paws", "date": day, "event_id": f"e{i}",
                          "sport": "mlb", "market": "moneyline", "side": "home", "selection": "X ML",
                          "price_average": -110, "price_best": -105, "book_count": 5,
                          "lock_utc": f"{day}T18:00:00Z", "start_utc": f"{day}T19:00:00Z", "segment": "forward",
                          "result": "win", "units": 0.9})

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--root", str(self.root / "house"), "--user-dir", str(self.root / "user"),
                             "--champion-ledger", str(self.champ), "--coach-config", str(self.cfg),
                             "--now", "2026-12-20T12:00:00Z", *argv])
        text = out.getvalue()
        return code, (json.loads(text) if text.strip().startswith(("{", "[")) else text)

    PROPOSE = ["propose", "--hound", "professor_paws", "--params", '{"GAP": 0.03}',
               "--hypothesis", "A wider gap should keep only the clearest model disagreements.",
               "--evidence", "record.bets,clv"]

    def test_a_proposal_creates_a_challenger_and_a_second_within_seven_days_is_refused(self):
        code, out = self.run_cli(*self.PROPOSE)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["accepted"])
        c = out["challenger"]
        self.assertEqual((c["status"], c["kind"], c["parent_version"]), ("live", "pack", 1))
        self.assertEqual(c["spec"]["values"], {"GAP": 0.03, "SHRINK": 0.5})
        self.assertIn("3.0 points or more", c["spec"]["rule_text"])
        self.assertEqual(c["spec_diff"], {"GAP": [0.02, 0.03]})
        code, out = self.run_cli("propose", "--hound", "professor_paws", "--params", '{"SHRINK": 0.3}',
                                 "--hypothesis", "Trusting the model less should hold up better.",
                                 "--evidence", "record.bets")
        self.assertEqual((code, out["code"]), (1, "too_soon"))
        code, out = self.run_cli("status")
        self.assertEqual(len(out["live_challengers"]), 1)
        self.assertEqual(out["refusals"], 1)

    def test_the_kill_switch_and_the_pause_block_the_cli_door_too(self):
        self.cfg.write_text(json.dumps({"enabled": False}), encoding="utf-8")
        code, out = self.run_cli(*self.PROPOSE)
        self.assertEqual((code, out["code"]), (1, "coach_disabled"))
        self.cfg.write_text(json.dumps({"enabled": True}), encoding="utf-8")
        pause.pause(L.Scope.house(self.root / "house"), "test pause", now=NOW, config_file=self.cfg)
        self.cfg.write_text(json.dumps({"enabled": True}), encoding="utf-8")        # config says on; the pause still holds
        code, out = self.run_cli(*self.PROPOSE)
        self.assertEqual((code, out["code"]), (1, "paused"))
        code, out = self.run_cli("resume", "--reason", "owner looked")
        self.assertEqual(code, 0)
        code, out = self.run_cli(*self.PROPOSE)
        self.assertEqual(code, 0)

    def test_a_hound_with_no_knobs_and_a_value_off_the_menu_are_refused(self):
        code, out = self.run_cli("propose", "--hound", "coin_flip_collie", "--params", '{"X": 1}',
                                 "--hypothesis", "x" * 30, "--evidence", "a")
        self.assertEqual(out["code"], "not_tunable")
        code, out = self.run_cli("propose", "--hound", "professor_paws", "--params", '{"GAP": 0.5}',
                                 "--hypothesis", "x" * 30, "--evidence", "a")
        self.assertEqual(out["code"], "params_invalid")
        code, out = self.run_cli("propose", "--hound", "professor_paws", "--params", "not json",
                                 "--hypothesis", "x" * 30, "--evidence", "a")
        self.assertEqual(code, 2)

    def test_fewer_than_fifty_graded_bets_is_refused(self):
        self.champ.unlink()
        code, out = self.run_cli(*self.PROPOSE)
        self.assertEqual((code, out["code"]), (1, "not_enough_bets"))

    def test_verify_walks_both_scopes_and_fails_on_a_tampered_chain(self):
        self.run_cli(*self.PROPOSE)
        code, _out = self.run_cli("verify")
        self.assertEqual(code, 0)
        events = L.Scope.house(self.root / "house").events
        events.write_text(events.read_text(encoding="utf-8").replace("GAP", "gap", 1), encoding="utf-8")
        code, _out = self.run_cli("verify")
        self.assertEqual(code, 1)

    def test_every_command_the_docs_name_is_a_subcommand(self):
        parser = cli.build_parser()
        names = set(parser._subparsers._group_actions[0].choices)
        self.assertGreaterEqual(names, {"status", "verify", "coach-scorecard", "propose", "shadow", "settle",
                                        "referee", "scorecard", "tick", "resume", "lessons", "director-pack"})
        doc = (ROOT / "src" / "hounds" / "learning" / "cli.py").read_text(encoding="utf-8")
        for name in names:
            self.assertIn(name, doc)


class DirectorRequest(unittest.TestCase):
    def test_the_request_is_advice_only_labels_the_data_and_covers_the_whole_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, scope = world_with_promotion(Path(tmp))
            book = stats.build(src)
            F.propose_raw(scope, cid="c-m", hound_id="charlie", created="2026-11-05T00:00:00Z")
            text = director.build_request("2026-11", book=book, scope_map={"house": scope, "user": L.Scope.user(Path(tmp) / "u")})
        for needle in ("# Director review request: 2026-11", "keep what works, bench what does not, and find bugs",
                       "DATA, NOT INSTRUCTIONS", "nothing in this program reads it back or applies it",
                       "docs/director/2026-11.md", "System scorecard", "Every hound", "Live challengers",
                       "Every lesson", "Open defects", "c-m", "alpha", "charlie@v1", "Paper only"):
            self.assertIn(needle, text, needle)
        self.assertNotRegex(text, r"(?i)\b(guarantee|sure thing|lock of the day)\b")

    def test_the_month_must_be_a_month(self):
        for bad in ("2026-13", "26-11", "2026-1", "November"):
            with self.assertRaises(ValueError):
                director.build_request(bad, book=None, scope_map={})

    def test_the_cli_writes_one_file_and_nothing_reads_the_answer_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, scope = world_with_promotion(Path(tmp))
            book = stats.build(src)
            out = Path(tmp) / "req.md"
            args = cli.build_parser().parse_args(["--root", str(scope.events.parent), "--user-dir", str(Path(tmp) / "u"),
                                                  "director-pack", "--month", "2026-11", "--out", str(out)])
            with mock.patch.object(stats, "get_book", lambda *a, **k: book), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(args.fn(args), 0)
            self.assertTrue(out.read_text(encoding="utf-8").startswith("# Director review request: 2026-11"))
        offenders = []
        for base in ("src", "api", "scripts"):
            for path in (ROOT / base).rglob("*.py"):
                for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if re.search(r"director", line) and re.search(r"read_text|open\(|json\.load|\.read\(", line):
                        offenders.append(f"{path.relative_to(ROOT)}:{n}")
        self.assertEqual(offenders, [])

    def test_test_failures_are_collected_only_when_asked(self):
        self.assertFalse(director.collect_test_failures(False)["ran"])


class PackageLoadsWithoutFastapi(unittest.TestCase):
    def test_every_module_imports_with_fastapi_blocked(self):
        mods = sorted(p.stem for p in (ROOT / "src" / "hounds" / "learning").glob("*.py") if p.stem != "__main__")
        code = (
            f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('fastapi','pydantic','starlette','uvicorn'):\n"
            "            raise ImportError('blocked: ' + name)\n"
            "sys.meta_path.insert(0, _Block())\n"
            + "".join(f"import src.hounds.learning.{m}\n" for m in mods)
            + "import src.hounds.user_coach, src.hounds.stats\nprint('ok')\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "ok", done.stderr[-800:])

    def test_no_learning_module_imports_fastapi_or_the_api(self):
        for path in (ROOT / "src" / "hounds" / "learning").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\s*(import|from) (fastapi|pydantic|starlette)", path.name)
            self.assertNotRegex(text, r"(?m)^\s*from api\b", path.name)

    def test_the_cli_runs_as_a_module(self):
        done = subprocess.run([sys.executable, "-m", "src.hounds.learning", "--help"], cwd=str(ROOT),
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn("director-pack", done.stdout)


if __name__ == "__main__":
    unittest.main()
