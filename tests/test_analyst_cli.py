"""`analyst run | grade | record`: BLOCKED, dry run, the spend cap, the refusals."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import cli, ledger
from tests import analyst_fixtures as F

KEY = {"ANTHROPIC_API_KEY": "sk-test"}


def item(state="pending", away="NYY", home="TB"):
    payload = F.payload(state)
    return {
        "payload": payload, "multibook_rows": F.multibook_rows(), "team_total_rows": F.team_total_rows(),
        "batter_prop_rows": F.batter_prop_rows(), "pitcher_prop_rows": F.pitcher_prop_rows(),
        "prop_board": F.prop_board(),
        "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
        "section_as_of": {"teams": "2026-10-02"},
    }


def second_game():
    other = item()
    adv = other["payload"]["advanced"]
    adv["game_id"] = "BOS-NYM-2026-10-03-1"
    adv["game"].update(away_team="BOS", home_team="NYM", game_pk=2)
    return other


class Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.paths = dict(store_path=str(self.dir / "analyst.jsonl"),
                          usage_path=str(self.dir / "usage.jsonl"),
                          packet_dir=str(self.dir / "packets"))
        self.out = []
        self.loader_calls = 0

    def loader(self, *items):
        def load(date):
            self.loader_calls += 1
            return list(items) or [item()]
        return load

    def run_cli(self, *, env=KEY, http=None, items=None, **kw):
        return cli.execute_run(
            F.DATE, env=env, http_post=http, loader=self.loader(*(items or [item()])),
            now=lambda: F.NOW, out=self.out.append, cfg=kw.pop("cfg", F.CFG), **self.paths, **kw)

    def files(self):
        return sorted(str(p.relative_to(self.dir)) for p in self.dir.rglob("*") if p.is_file())

    @property
    def text(self):
        return "\n".join(self.out)


class BlockedWithoutAKey(Env):
    def test_it_prints_blocked_exits_nonzero_and_writes_nothing(self):
        http = F.FakeHttp((200, b"{}"))
        code = self.run_cli(env={}, http=http)
        self.assertEqual(code, cli.EXIT_BLOCKED)
        self.assertNotEqual(code, 0)
        self.assertIn("BLOCKED: ANTHROPIC_API_KEY is not set", self.text)
        self.assertEqual(self.files(), [])
        self.assertEqual(http.calls, 0)
        self.assertEqual(self.loader_calls, 0)     # not even built

    def test_a_blank_key_is_blocked_too(self):
        self.assertEqual(self.run_cli(env={"ANTHROPIC_API_KEY": "  "}), cli.EXIT_BLOCKED)

    def test_the_blocked_line_points_at_the_enable_steps(self):
        self.run_cli(env={})
        self.assertIn("docs/decisions/AI_ANALYST_ENABLE.md", self.text)


class DryRun(Env):
    def test_a_dry_run_needs_no_key_calls_nothing_and_writes_nothing(self):
        http = F.FakeHttp((200, b"{}"))
        code = self.run_cli(env={}, http=http, dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(http.calls, 0)
        self.assertEqual(self.files(), [])
        self.assertIn("DRY RUN NYY-TB-2026-10-03-1", self.text)
        self.assertIn("nothing sent, nothing written", self.text)

    def test_print_request_prints_the_exact_body_that_would_be_sent(self):
        self.run_cli(env={}, dry_run=True, print_request=True)
        start = self.text.index("{\n")
        body = json.loads(self.text[start:self.text.rindex("}") + 1])
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["system"], A.SYSTEM_PROMPT)
        self.assertIn("PACKET (JSON)", body["messages"][0]["content"])

    def test_a_dry_run_does_not_spend_the_meter_or_skip_a_published_game_silently(self):
        # publish first, then a dry run reports the freeze honestly
        http = F.FakeHttp((200, F.api_response(F.good_output(F.build(built_at="2026-10-03T18:00:00Z")))))
        self.assertEqual(self.run_cli(http=http), 0)
        self.out.clear()
        self.run_cli(env={}, dry_run=True)
        self.assertIn("SKIP NYY-TB-2026-10-03-1: already published", self.text)


class AFullRun(Env):
    def answer(self, usage=None):
        return (200, F.api_response(F.good_output(F.build()), usage))

    def test_it_publishes_logs_cost_and_writes_the_packet(self):
        http = F.FakeHttp(self.answer({"input_tokens": 10000, "output_tokens": 5000}))
        code = self.run_cli(http=http)
        self.assertEqual(code, 0)
        self.assertIn("PUBLISHED NYY-TB-2026-10-03-1 v1", self.text)
        rows = ledger.rows(self.paths["store_path"])
        self.assertEqual([r["kind"] for r in rows], ["analyst_published"])
        self.assertEqual(rows[0]["run"]["cost_usd"], 0.07)
        usage = ledger.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertEqual((usage["games"], usage["published"]), (1, 1))
        self.assertAlmostEqual(usage["cost_usd"], 0.07)
        self.assertTrue(ledger.verify(self.paths["store_path"])["ok"])
        self.assertEqual(http.requests[0]["headers"]["x-api-key"], "sk-test")

    def test_the_key_never_appears_in_output_or_files(self):
        self.run_cli(http=F.FakeHttp(self.answer()))
        blob = self.text + "".join(p.read_bytes().decode("latin-1") for p in self.dir.rglob("*")
                                   if p.is_file() and p.suffix != ".gz")
        self.assertNotIn("sk-test", blob)

    def test_a_published_game_is_frozen_and_not_paid_for_again(self):
        http = F.FakeHttp(self.answer())
        self.run_cli(http=http)
        self.run_cli(http=http)
        self.assertEqual(http.calls, 1)
        self.assertIn("already published (v1); frozen unless --refresh", self.text)

    def test_refresh_publishes_a_second_version(self):
        http = F.FakeHttp(self.answer())
        self.run_cli(http=http)
        self.run_cli(http=http, refresh=True)
        self.assertEqual(http.calls, 2)
        self.assertEqual(len(ledger.rows(self.paths["store_path"])), 2)

    def test_game_filter_runs_only_that_game(self):
        http = F.FakeHttp(self.answer())
        self.run_cli(http=http, items=[item(), second_game()], game="NYY@TB")
        self.assertEqual(http.calls, 1)
        self.out.clear()
        self.assertEqual(self.run_cli(env=KEY, http=http, game="XXX@YYY"), cli.EXIT_ERROR)
        self.assertIn("no games found", self.text)

    def test_a_struck_call_is_published_as_a_pass_and_counted(self):
        packet = F.build()
        out = F.good_output(packet)
        out["calls"][0]["reasons"][1]["claim"] = "He has a 2.17 ERA."
        self.run_cli(http=F.FakeHttp((200, F.api_response(out))))
        self.assertIn("1 struck", self.text)
        row = ledger.rows(self.paths["store_path"])[0]
        self.assertEqual(next(c for c in row["calls"] if c["slot_id"] == "moneyline")["verdict"], "PASS")


class RefusalsAreFreeBeforeTheCall(Env):
    def test_a_game_that_has_started_is_skipped_before_the_model_is_called(self):
        http = F.FakeHttp((200, b"{}"))
        late = lambda: datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc)
        code = cli.execute_run(F.DATE, env=KEY, http_post=http, loader=self.loader(item()),
                               now=late, out=self.out.append, cfg=F.CFG, **self.paths)
        self.assertEqual(code, 0)
        self.assertEqual(http.calls, 0)
        self.assertIn("SKIP NYY-TB-2026-10-03-1", self.text)
        self.assertEqual(self.files(), [])

    def test_a_live_or_final_game_is_skipped(self):
        http = F.FakeHttp((200, b"{}"))
        self.run_cli(http=http, items=[item(state="live")])
        self.assertEqual(http.calls, 0)
        self.assertIn("not pending", self.text)

    def test_a_game_with_no_prices_is_skipped_not_sent_empty(self):
        empty = item()
        empty.update(multibook_rows=[], team_total_rows=[], batter_prop_rows=[],
                     pitcher_prop_rows=[], prop_board=[])
        http = F.FakeHttp((200, b"{}"))
        self.run_cli(http=http, items=[empty])
        self.assertEqual(http.calls, 0)
        self.assertIn("prices no market", self.text)


class TheSpendCapStopsTheRun(Env):
    def test_the_second_game_is_not_analysed_and_the_run_says_so(self):
        cfg = dict(F.CFG, spend_cap={"max_usd_per_run": 0.5, "max_tokens_per_run": 10_000_000})
        http = F.FakeHttp((200, F.api_response(F.good_output(F.build()),
                                               {"input_tokens": 10000, "output_tokens": 40000})))
        code = self.run_cli(http=http, items=[item(), second_game()], cfg=cfg)
        self.assertEqual(code, cli.EXIT_CAP)
        self.assertEqual(http.calls, 1)
        self.assertIn("STOPPED: spend cap reached", self.text)
        self.assertIn("1 published before the stop", self.text)
        self.assertEqual(len(ledger.rows(self.paths["store_path"])), 1)


class FailuresAreLoggedNotPublished(Env):
    def test_malformed_output_is_logged_with_its_cost_and_nothing_is_published(self):
        bad = F.good_output(F.build())
        bad["summary"] = "short"
        http = F.FakeHttp((200, F.api_response(bad, {"input_tokens": 1000, "output_tokens": 1000})))
        code = self.run_cli(http=http)
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("rejected after 2 attempts", self.text)
        self.assertEqual(ledger.rows(self.paths["store_path"]), [])
        day = ledger.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertEqual((day["games"], day["published"]), (1, 0))
        self.assertAlmostEqual(day["cost_usd"], 0.024)

    def test_a_refusal_is_a_paid_call_and_is_logged_with_its_cost(self):
        http = F.FakeHttp((200, F.api_response("", {"input_tokens": 11000, "output_tokens": 50},
                                               stop_reason="refusal")))
        code = self.run_cli(http=http)
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("declined to answer", self.text)
        self.assertEqual(ledger.rows(self.paths["store_path"]), [])
        day = ledger.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertEqual((day["games"], day["published"]), (1, 0))
        self.assertAlmostEqual(day["cost_usd"], 11000 * 2 / 1e6 + 50 * 10 / 1e6, places=4)

    def test_a_refusal_does_not_count_toward_the_api_outage_stop(self):
        http = F.FakeHttp((200, F.api_response("", stop_reason="refusal")))
        self.run_cli(http=http, items=[item(), second_game(), second_game()])
        self.assertEqual(http.calls, 3)
        self.assertNotIn("in a row failed at the API", self.text)

    def test_two_api_failures_in_a_row_stop_the_run(self):
        http = F.FakeHttp((401, b'{"error": {"message": "invalid x-api-key"}}'))
        code = self.run_cli(http=http, items=[item(), second_game(), second_game()])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("in a row failed at the API", self.text)
        self.assertEqual(http.calls, 2)

    def test_a_missing_model_critic_is_noted_and_the_calls_stand_on_the_first_pass(self):
        packet = F.build()
        http = F.FakeHttp((200, F.api_response(F.good_output(packet))),
                          (401, b'{"error": {"message": "nope"}}'))
        code = self.run_cli(http=http, use_model_critic=True)
        self.assertEqual(code, 0)
        self.assertIn("model critic did not run", self.text)
        self.assertEqual(ledger.rows(self.paths["store_path"])[0]["model_critic"], "did not run")

    def test_a_model_critic_that_runs_can_strike(self):
        packet = F.build()
        verdict = {"checks": [{"slot_id": "moneyline", "supported": False, "problem": "overreach"}],
                   "summary_supported": True, "summary_problem": ""}
        http = F.FakeHttp((200, F.api_response(F.good_output(packet))),
                          (200, F.api_response(verdict, {"input_tokens": 12000, "output_tokens": 300})))
        self.run_cli(http=http, use_model_critic=True)
        row = ledger.rows(self.paths["store_path"])[0]
        self.assertEqual(row["model_critic"], "ran")
        self.assertEqual(next(c for c in row["calls"] if c["slot_id"] == "moneyline")["verdict"], "PASS")
        self.assertGreater(row["run"]["cost_usd"], 0.07)


class GradeAndRecord(Env):
    def test_grade_and_record_commands(self):
        self.run_cli(http=F.FakeHttp((200, F.api_response(F.good_output(F.build())))))
        code = cli.execute_grade(
            F.DATE, results=lambda d: ({849835: {"away_score": "5", "home_score": "3"}}, []),
            now=lambda: F.NOW, out=self.out.append, store_path=self.paths["store_path"])
        self.assertEqual(code, 0)
        self.assertIn("graded=1", self.text)
        self.out.clear()
        code = cli.execute_record(out=self.out.append, store_path=self.paths["store_path"],
                                  usage_path=self.paths["usage_path"], cfg=F.CFG)
        self.assertEqual(code, 0)
        self.assertIn("Unproven. Analysis, not advice.", self.text)
        self.assertIn("ledger: OK", self.text)
        self.assertIn("win rate withheld", self.text)
        self.assertIn("$0.07", self.text)

    def test_record_reports_a_broken_ledger_with_a_nonzero_exit(self):
        self.run_cli(http=F.FakeHttp((200, F.api_response(F.good_output(F.build())))))
        text = Path(self.paths["store_path"]).read_text(encoding="utf-8").replace("TAKE_OTHER_SIDE", "TAKE")
        Path(self.paths["store_path"]).write_text(text, encoding="utf-8")
        code = cli.execute_record(out=self.out.append, store_path=self.paths["store_path"],
                                  usage_path=self.paths["usage_path"], cfg=F.CFG)
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ledger: PROBLEM", self.text)


class TheDailyStep(unittest.TestCase):
    """scripts/analyst_step.sh is read as text: the properties that matter are
    positional (guarded by the key, cannot fail the loop), not behavioural."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.step = (self.ROOT / "scripts" / "analyst_step.sh").read_text(encoding="utf-8")
        self.loop = (self.ROOT / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")

    def test_the_run_is_guarded_by_the_key_and_the_grade_is_not(self):
        guard = self.step.index('if [ -z "${ANTHROPIC_API_KEY:-}" ]')
        self.assertLess(self.step.index("analyst grade"), guard)
        self.assertGreater(self.step.index("analyst run"), guard)

    def test_it_can_never_fail_the_loop_or_escalate(self):
        body = "\n".join(l for l in self.step.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("ESCALATE", body)
        self.assertTrue(body.rstrip().endswith("exit 0"))
        cli_lines = [l for l in body.splitlines() if "python3 -m src.cli" in l]
        self.assertEqual(len(cli_lines), 2)
        self.assertTrue(all(l.rstrip().endswith("|| true") for l in cli_lines))

    def test_the_daily_loop_calls_it_once_before_eod_and_after_settlement(self):
        self.assertEqual(self.loop.count("scripts/analyst_step.sh"), 1)
        at = self.loop.index('bash scripts/analyst_step.sh "$TODAY" "$YESTERDAY"')
        self.assertGreater(at, self.loop.index("nfl card settle"))
        self.assertLess(at, self.loop.index('echo "== eod (yesterday'))

    def test_the_key_is_never_echoed_by_the_script(self):
        self.assertNotRegex(self.step, r"echo[^\n]*\$\{?ANTHROPIC_API_KEY[^:]")


class TheTopLevelCli(unittest.TestCase):
    def test_the_analyst_subcommand_is_registered(self):
        from src import cli as top
        args = top.build_parser().parse_args(["analyst", "run", "--date", "2026-10-03", "--dry-run",
                                              "--game", "NYY@TB"])
        self.assertEqual((args.command, args.analyst_command, args.dry_run, args.game),
                         ("analyst", "run", True, "NYY@TB"))
        self.assertIn("analyst", top.COMMANDS)
        top.build_parser().parse_args(["analyst", "grade", "--date", "2026-10-03"])
        top.build_parser().parse_args(["analyst", "record"])

    def test_end_to_end_without_a_key_the_real_entry_point_is_blocked(self):
        from unittest import mock
        from src import cli as top
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(top, "_load_dotenv", lambda *a, **k: None):
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = top.main(["analyst", "run", "--date", "2026-10-03"])
        self.assertEqual(code, 3)
        self.assertIn("BLOCKED", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
