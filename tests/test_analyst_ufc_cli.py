"""`analyst run | grade | record --sport ufc`: BLOCKED, dry run, the spend cap, the refusals.

The store, the HTTP caller, the clock and every output path are injected or temporary: no
test here reads the repo's UFC data, calls a model or touches a network. The MLB commands are
pinned by tests/test_analyst_cli.py, which this change leaves green.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.analyst import analyst as A
from src.analyst import cli, ufc_analyst as U, ufc_cli, ufc_ledger as L, ufc_packet
from src.datasvc.ufc import store as ufc_store
from tests import ufc_analyst_fixtures as F

KEY = {"ANTHROPIC_API_KEY": "sk-test"}
SECOND = "9102"


class Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = F.make_store(self.dir / "world", rows=[F.odds(), F.odds(bout_id=SECOND)])
        self.paths = dict(store_path=str(self.dir / "ufc.jsonl"), usage_path=str(self.dir / "usage.jsonl"),
                          packet_dir=str(self.dir / "packets"))
        self.out = []
        self.loader_calls = []

    def items(self, *bout_ids):
        return [F.item(self.store, b) for b in (bout_ids or (SECOND, F.BOUT))]

    def loader(self, *bout_ids):
        def load(date, event=None):
            self.loader_calls.append((date, event))
            return self.items(*bout_ids)
        return load

    def run_cli(self, *, env=KEY, http=None, bouts=(), now=None, **kw):
        return ufc_cli.execute_run(
            F.DATE, env=env, http_post=http, loader=self.loader(*bouts), now=now or (lambda: F.NOW),
            out=self.out.append, cfg=kw.pop("cfg", F.CFG), **self.paths, **kw)

    def answers(self, *bout_ids, usage=None):
        return [(200, F.api_response(F.good_output(F.packet(self.store, b)), usage)) for b in bout_ids]

    def files(self):
        return sorted(str(p.relative_to(self.dir)) for p in self.dir.rglob("*")
                      if p.is_file() and not str(p.relative_to(self.dir)).startswith("world"))

    @property
    def text(self):
        return "\n".join(self.out)


class BlockedWithoutAKey(Env):
    def test_it_prints_blocked_exits_nonzero_and_writes_nothing(self):
        http = F.FakeHttp((200, b"{}"))
        code = self.run_cli(env={}, http=http)
        self.assertEqual(code, ufc_cli.EXIT_BLOCKED)
        self.assertEqual(code, 3)
        self.assertIn("BLOCKED: ANTHROPIC_API_KEY is not set", self.text)
        self.assertEqual(self.files(), [])
        self.assertEqual(http.calls, 0)
        self.assertEqual(self.loader_calls, [])            # not even loaded, let alone built

    def test_a_blank_key_is_blocked_too(self):
        self.assertEqual(self.run_cli(env={"ANTHROPIC_API_KEY": "  "}), 3)

    def test_the_blocked_line_points_at_the_enable_steps_and_it_is_the_same_key_as_mlb(self):
        self.run_cli(env={})
        self.assertIn("docs/decisions/AI_ANALYST_ENABLE.md", self.text)
        self.assertIn("ANTHROPIC_API_KEY", self.text)

    def test_the_real_entry_point_without_a_key_is_blocked_and_writes_nothing(self):
        from src import cli as top
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(top, "_load_dotenv", lambda *a, **k: None), \
                mock.patch.object(ufc_cli, "default_loader", side_effect=AssertionError("loaded")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = top.main(["analyst", "run", "--sport", "ufc", "--date", F.DATE])
        self.assertEqual(code, 3)
        self.assertIn("BLOCKED", buf.getvalue())


class DryRun(Env):
    def test_a_dry_run_needs_no_key_calls_nothing_and_writes_nothing(self):
        http = F.FakeHttp((200, b"{}"))
        code = self.run_cli(env={}, http=http, dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(http.calls, 0)
        self.assertEqual(self.files(), [])
        self.assertIn("nothing sent, nothing written", self.text)

    def test_it_shows_the_packet_size_the_slot_count_and_the_worst_case_cost(self):
        self.run_cli(env={}, dry_run=True, bouts=(F.BOUT,))
        line = next(l for l in self.out if l.startswith("DRY RUN"))
        packet = F.packet(self.store)
        self.assertIn(f"DRY RUN {F.BOUT} Alex Archer vs Ben Brawler: packet {ufc_packet.packet_hash(packet)[:12]}", line)
        self.assertIn(f"({len(A.packet_json(packet))} characters)", line)
        self.assertIn("8 slots", line)
        self.assertIn(f"{len(packet['missing'])} missing items", line)
        self.assertRegex(line, r"request ~\d+ input tokens \(high estimate\), worst case \$0\.\d\d;")
        self.assertIn("  slots: moneyline, rounds_total, method_a_ko", self.text)

    def test_the_worst_case_is_the_input_estimate_plus_the_full_output_cap(self):
        self.run_cli(env={}, dry_run=True, bouts=(F.BOUT,))
        body = U.build_request(F.packet(self.store), F.CFG)
        est = A.estimate_tokens(body["system"], body["messages"][0]["content"])
        worst = (est * 2.0 + 16000 * 10.0) / 1e6
        self.assertIn(f"~{est} input tokens", self.text)
        self.assertIn(f"worst case ${worst:.2f}", self.text)

    def test_the_card_total_is_printed(self):
        self.run_cli(env={}, dry_run=True)
        last = self.out[-1]
        self.assertRegex(last, r"^dry run over 2 bout\(s\) of 2: 16 slots, ~\d+ input tokens, worst case \$\d+\.\d\d "
                               r"\(a run stops at its \$6\.00 cap\); nothing sent, nothing written$")

    def test_print_request_prints_the_exact_body_that_would_be_sent(self):
        self.run_cli(env={}, dry_run=True, print_request=True, bouts=(F.BOUT,))
        start = self.text.index("{\n")
        body = json.loads(self.text[start:self.text.rindex("}") + 1])
        self.assertEqual(body["system"], U.UFC_SYSTEM_PROMPT)
        self.assertEqual(body, json.loads(json.dumps(U.build_request(F.packet(self.store), F.CFG))))
        self.assertIn("PACKET (JSON)", body["messages"][0]["content"])

    def test_a_dry_run_names_the_missing_fighter_names_and_still_shows_the_cost(self):
        self.store.write("fighters", [])
        self.run_cli(env={}, dry_run=True, bouts=(F.BOUT,))
        self.assertIn("DRY RUN 9101 Fighter A vs Fighter B", self.text)
        self.assertIn("NOTE: no name is stored for fighter A and B; a real run skips this bout", self.text)

    def test_a_dry_run_reports_a_frozen_bout_honestly(self):
        self.run_cli(http=F.FakeHttp(*self.answers(F.BOUT)), bouts=(F.BOUT,))
        self.out.clear()
        self.run_cli(env={}, dry_run=True, bouts=(F.BOUT,))
        self.assertIn(f"SKIP {F.BOUT} Alex Archer vs Ben Brawler: already published (v1)", self.text)


class AFullRun(Env):
    def test_it_publishes_logs_cost_and_writes_the_packet(self):
        http = F.FakeHttp(*self.answers(F.BOUT, usage={"input_tokens": 10000, "output_tokens": 5000}))
        code = self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(code, 0)
        self.assertIn(f"PUBLISHED {F.BOUT} Alex Archer vs Ben Brawler v1", self.text)
        rows = L.rows(self.paths["store_path"])
        self.assertEqual([r["kind"] for r in rows], ["analyst_ufc_published"])
        self.assertEqual(rows[0]["run"]["cost_usd"], 0.07)
        usage = L.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertEqual((usage["games"], usage["published"]), (1, 1))
        self.assertAlmostEqual(usage["cost_usd"], 0.07)
        self.assertTrue(L.verify(self.paths["store_path"])["ok"])
        self.assertEqual(http.requests[0]["headers"]["x-api-key"], "sk-test")
        self.assertEqual(http.requests[0]["body"]["system"], U.UFC_SYSTEM_PROMPT)

    def test_the_key_never_appears_in_output_or_files(self):
        self.run_cli(http=F.FakeHttp(*self.answers(F.BOUT)), bouts=(F.BOUT,))
        blob = self.text + "".join(p.read_bytes().decode("latin-1") for p in self.dir.rglob("*")
                                   if p.is_file() and p.suffix != ".gz")
        self.assertNotIn("sk-test", blob)

    def test_a_whole_card_is_published_earliest_start_first(self):
        http = F.FakeHttp(*self.answers(SECOND, F.BOUT))
        self.assertEqual(self.run_cli(http=http), 0)
        self.assertEqual(http.calls, 2)
        rows = L.rows(self.paths["store_path"])
        self.assertEqual([r["bout_id"] for r in rows], [SECOND, F.BOUT])
        self.assertIn("run ", self.out[-1])
        self.assertIn("2 published, 0 skipped, 0 failed", self.out[-1])

    def test_a_published_bout_is_frozen_and_not_paid_for_again(self):
        http = F.FakeHttp(*self.answers(F.BOUT))
        self.run_cli(http=http, bouts=(F.BOUT,))
        self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(http.calls, 1)
        self.assertIn("already published (v1); frozen unless --refresh", self.text)

    def test_refresh_publishes_a_second_version(self):
        http = F.FakeHttp(*self.answers(F.BOUT))
        self.run_cli(http=http, bouts=(F.BOUT,))
        self.run_cli(http=http, bouts=(F.BOUT,), refresh=True)
        self.assertEqual(http.calls, 2)
        self.assertEqual(len(L.rows(self.paths["store_path"])), 2)

    def test_a_struck_call_is_published_as_a_pass_and_counted(self):
        out = F.deep(F.good_output(F.packet(self.store)))
        out["calls"][0]["reasons"][1]["claim"] = "He lands 71.93 strikes a minute."
        self.run_cli(http=F.FakeHttp((200, F.api_response(out))), bouts=(F.BOUT,))
        self.assertIn("1 struck", self.text)
        row = L.rows(self.paths["store_path"])[0]
        self.assertEqual(next(c for c in row["calls"] if c["slot_id"] == "moneyline")["verdict"], "PASS")

    def test_a_missing_model_critic_is_noted_and_the_calls_stand(self):
        http = F.FakeHttp(*self.answers(F.BOUT), (401, b'{"error": {"message": "nope"}}'))
        code = self.run_cli(http=http, bouts=(F.BOUT,), use_model_critic=True)
        self.assertEqual(code, 0)
        self.assertIn("model critic did not run", self.text)
        self.assertEqual(L.rows(self.paths["store_path"])[0]["model_critic"], "did not run")

    def test_a_model_critic_that_runs_can_strike(self):
        verdict = {"checks": [{"slot_id": "moneyline", "supported": False, "problem": "overreach"}],
                   "summary_supported": True, "summary_problem": ""}
        http = F.FakeHttp(*self.answers(F.BOUT),
                          (200, F.api_response(verdict, {"input_tokens": 12000, "output_tokens": 300})))
        self.run_cli(http=http, bouts=(F.BOUT,), use_model_critic=True)
        row = L.rows(self.paths["store_path"])[0]
        self.assertEqual(row["model_critic"], "ran")
        self.assertEqual(next(c for c in row["calls"] if c["slot_id"] == "moneyline")["verdict"], "PASS")


class RefusalsAreFreeBeforeTheCall(Env):
    def test_a_bout_that_has_started_is_skipped_before_the_model_is_called(self):
        http = F.FakeHttp((200, b"{}"))
        late = lambda: datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc)
        code = self.run_cli(http=http, bouts=(F.BOUT,), now=late)
        self.assertEqual(code, 0)
        self.assertEqual(http.calls, 0)
        self.assertIn(f"SKIP {F.BOUT} Alex Archer vs Ben Brawler: the bout's scheduled start", self.text)
        self.assertEqual(self.files(), [])

    def test_only_the_bouts_that_have_not_started_are_paid_for(self):
        """The prelim started at 21:00Z; at 22:00Z only the main event can still be published."""
        http = F.FakeHttp(*self.answers(F.BOUT))
        at = lambda: datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)
        # the packets are built at 22:00Z here, so the answer must be built from that packet too
        packet = F.packet(self.store, F.BOUT, built_at="2026-10-10T22:00:00Z")
        http = F.FakeHttp((200, F.api_response(F.good_output(packet))))
        self.run_cli(http=http, now=at)
        self.assertEqual(http.calls, 1)
        self.assertIn(f"SKIP {SECOND}", self.text)
        self.assertEqual([r["bout_id"] for r in L.rows(self.paths["store_path"])], [F.BOUT])

    def test_a_bout_that_is_not_scheduled_is_skipped(self):
        F.finish_the_bout(self.store)
        http = F.FakeHttp((200, b"{}"))
        self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(http.calls, 0)
        self.assertIn("'final', not scheduled", self.text)

    def test_a_bout_with_no_scheduled_start_is_skipped(self):
        self.store.upsert("bouts", [dict(self.store.bout_by_id()[F.BOUT], date_utc=None)])
        http = F.FakeHttp((200, b"{}"))
        self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(http.calls, 0)
        self.assertIn("scheduled start is unknown", self.text)

    def test_a_bout_with_no_prices_is_skipped_not_sent_empty(self):
        self.store.write("odds", [])
        http = F.FakeHttp((200, b"{}"))
        self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(http.calls, 0)
        self.assertIn("prices no market", self.text)

    def test_a_bout_whose_fighters_the_store_cannot_name_is_skipped(self):
        self.store.write("fighters", [])
        http = F.FakeHttp((200, b"{}"))
        code = self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(code, 0)
        self.assertEqual(http.calls, 0)
        self.assertIn("the store has no name for fighter A and B, so a published analysis could not say "
                      "who is fighting", self.text)
        self.assertEqual(self.files(), [])

    def test_one_unnamed_fighter_is_enough_to_skip(self):
        self.store.upsert("fighters", [f for f in self.store.fighters if f["fighter_id"] != "102"])
        self.store.write("fighters", [f for f in self.store.fighters if f["fighter_id"] != "102"])
        self.run_cli(http=F.FakeHttp((200, b"{}")), bouts=(F.BOUT,))
        self.assertIn("no name for fighter B", self.text)

    def test_a_bout_the_store_does_not_have_is_skipped_with_the_reason(self):
        http = F.FakeHttp((200, b"{}"))
        self.run_cli(http=http, bouts=("nope",))
        self.assertEqual(http.calls, 0)
        self.assertIn("SKIP nope: no bout 'nope' in the store", self.text)


class AnAnalysisThatFinishesAfterTheStartIsRefusedAtPublish(Env):
    def test_the_clock_is_asked_again_at_publish_and_the_ledger_refuses_what_is_late(self):
        """The model call takes time. A bout that was ahead when the call began and has started when
        it returns is refused at publish; the paid call is logged, nothing is published."""
        ticks = iter([F.NOW] + [datetime(2026, 10, 10, 23, 0, 1, tzinfo=timezone.utc)] * 10)
        http = F.FakeHttp(*self.answers(F.BOUT, usage={"input_tokens": 9000, "output_tokens": 4000}))
        code = self.run_cli(http=http, bouts=(F.BOUT,), now=lambda: next(ticks))
        self.assertEqual(code, 0)
        self.assertEqual(http.calls, 1)
        self.assertIn(f"REFUSED {F.BOUT} Alex Archer vs Ben Brawler", self.text)
        self.assertEqual(L.rows(self.paths["store_path"]), [])
        day = L.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertEqual((day["games"], day["published"]), (1, 0))
        self.assertGreater(day["cost_usd"], 0)


class TheConsoleCannotBreakARun(unittest.TestCase):
    def test_a_name_the_console_cannot_encode_is_shown_with_a_question_mark_not_a_traceback(self):
        class Narrow(io.StringIO):
            def write(self, text):
                text.encode("ascii")                        # what a cp1252-or-narrower pipe does
                return super().write(text)
        buf = Narrow()
        with contextlib.redirect_stdout(buf):
            ufc_cli._print("DRY RUN 1 Jan Błachowicz vs Ben Brawler")
        self.assertEqual(buf.getvalue(), "DRY RUN 1 Jan B?achowicz vs Ben Brawler\n")

    def test_plain_ascii_is_untouched(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ufc_cli._print("PUBLISHED 1 Alex Archer vs Ben Brawler v1")
        self.assertEqual(buf.getvalue(), "PUBLISHED 1 Alex Archer vs Ben Brawler v1\n")


class TheSpendCapStopsTheRun(Env):
    def test_the_second_bout_is_not_analysed_and_the_run_says_so(self):
        cfg = dict(F.CFG, spend_cap={"max_usd_per_run": 0.5, "max_tokens_per_run": 10_000_000})
        http = F.FakeHttp(*self.answers(SECOND, usage={"input_tokens": 10000, "output_tokens": 40000}))
        code = self.run_cli(http=http, cfg=cfg)
        self.assertEqual(code, ufc_cli.EXIT_CAP)
        self.assertEqual(code, 4)
        self.assertEqual(http.calls, 1)
        self.assertIn("STOPPED: spend cap reached", self.text)
        self.assertIn("1 published before the stop", self.text)
        self.assertEqual(len(L.rows(self.paths["store_path"])), 1)


class FailuresAreLoggedNotPublished(Env):
    def test_malformed_output_is_logged_with_its_cost_and_nothing_is_published(self):
        bad = F.good_output(F.packet(self.store))
        bad["summary"] = "short"
        http = F.FakeHttp((200, F.api_response(bad, {"input_tokens": 1000, "output_tokens": 1000})))
        code = self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(code, ufc_cli.EXIT_ERROR)
        self.assertIn("rejected after 2 attempts", self.text)
        self.assertEqual(L.rows(self.paths["store_path"]), [])
        day = L.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertEqual((day["games"], day["published"]), (1, 0))
        self.assertAlmostEqual(day["cost_usd"], 0.024)

    def test_a_refusal_is_a_paid_call_and_is_logged_with_its_cost(self):
        http = F.FakeHttp((200, F.api_response("", {"input_tokens": 9000, "output_tokens": 50}, stop_reason="refusal")))
        code = self.run_cli(http=http, bouts=(F.BOUT,))
        self.assertEqual(code, ufc_cli.EXIT_ERROR)
        self.assertIn("declined to answer", self.text)
        day = L.usage_by_day(self.paths["usage_path"])[F.DATE]
        self.assertAlmostEqual(day["cost_usd"], 9000 * 2 / 1e6 + 50 * 10 / 1e6, places=4)

    def test_two_api_failures_in_a_row_stop_the_run(self):
        third = "9103"
        base_bout = dict(self.store.bout_by_id()[SECOND], bout_id=third)
        self.store.upsert("bouts", [base_bout])
        self.store.upsert("odds", [F.odds(bout_id=third)])
        http = F.FakeHttp((401, b'{"error": {"message": "invalid x-api-key"}}'))
        code = self.run_cli(http=http, bouts=(SECOND, F.BOUT, third))
        self.assertEqual(code, ufc_cli.EXIT_ERROR)
        self.assertIn("in a row failed at the API", self.text)
        self.assertEqual(http.calls, 2)

    def test_an_unloadable_store_is_an_error_not_a_traceback(self):
        def broken(date, event=None):
            raise OSError("disk gone")
        code = ufc_cli.execute_run(F.DATE, env=KEY, loader=broken, out=self.out.append, cfg=F.CFG, **self.paths)
        self.assertEqual(code, ufc_cli.EXIT_ERROR)
        self.assertIn("ERROR: could not load the UFC card", self.text)


class TheCardLoader(Env):
    """`default_loader` against a real UfcStore in a temp directory (the store's default
    directory is pointed at it; the repo's data is never read)."""

    def setUp(self):
        super().setUp()
        root = self.dir / "ufcdata"
        F.make_store(root, rows=[F.odds(), F.odds(bout_id=SECOND)])
        patcher = mock.patch.object(ufc_store, "DEFAULT_DIR", root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_dates_events_come_back_earliest_start_first_main_event_first_within_a_start(self):
        items = ufc_cli.default_loader(F.DATE)
        self.assertEqual([i["bout_id"] for i in items], [SECOND, F.BOUT])       # 21:00Z prelim, 23:00Z main
        self.assertEqual({i["event_id"] for i in items}, {F.EVENT})

    def test_a_date_with_no_event_is_empty_and_ok(self):
        self.assertEqual(ufc_cli.default_loader("2026-10-11"), [])
        code = ufc_cli.execute_run("2026-10-11", env=KEY, out=self.out.append, cfg=F.CFG, **self.paths)
        self.assertEqual(code, 0)
        self.assertIn("no UFC bouts found for 2026-10-11", self.text)

    def test_one_event_by_id(self):
        self.assertEqual(len(ufc_cli.default_loader(F.DATE, F.EVENT)), 2)

    def test_an_unknown_event_or_one_dated_otherwise_is_an_error(self):
        with self.assertRaises(LookupError):
            ufc_cli.default_loader(F.DATE, "nope")
        with self.assertRaises(ValueError) as ctx:
            ufc_cli.default_loader("2026-10-11", F.EVENT)
        self.assertIn("is dated 2026-10-10, not 2026-10-11", str(ctx.exception))
        code = ufc_cli.execute_run("2026-10-11", event=F.EVENT, env=KEY, out=self.out.append, cfg=F.CFG,
                                   **self.paths)
        self.assertEqual(code, ufc_cli.EXIT_ERROR)

    def test_the_date_is_the_events_utc_date_even_for_bouts_after_midnight(self):
        store = ufc_cli.default_loader(F.DATE)[0]["store"]
        main = store.bout_by_id()[F.BOUT]
        self.store = store
        store.upsert("bouts", [dict(main, date_utc="2026-10-11T00:30Z")])
        items = ufc_cli.default_loader(F.DATE)
        self.assertEqual([i["bout_id"] for i in items], [SECOND, F.BOUT])


class GradeAndRecord(Env):
    def published(self):
        self.run_cli(http=F.FakeHttp(*self.answers(F.BOUT)), bouts=(F.BOUT,))
        self.out.clear()

    def test_grade_and_record_commands(self):
        self.published()
        F.finish_the_bout(self.store)
        code = ufc_cli.execute_grade(F.DATE, results=lambda d: self.store.bout_by_id(), now=lambda: F.NOW,
                                     out=self.out.append, store_path=self.paths["store_path"])
        self.assertEqual(code, 0)
        self.assertIn("published=1 graded=1 complete=1 unchanged=0", self.text)
        self.out.clear()
        code = ufc_cli.execute_record(out=self.out.append, store_path=self.paths["store_path"],
                                      usage_path=self.paths["usage_path"], cfg=F.CFG)
        self.assertEqual(code, 0)
        self.assertIn("Unproven. Analysis, not advice.", self.text)
        self.assertIn("bouts published 1, settled 1", self.text)
        self.assertIn("ledger: OK", self.text)
        self.assertIn("win rate withheld", self.text)
        for family in ("moneyline", "method", "rounds_total"):
            self.assertIn(family, self.text)
        self.assertIn("cost per day", self.text)

    def test_grade_with_nothing_final_changes_nothing(self):
        self.published()
        ufc_cli.execute_grade(F.DATE, results=lambda d: self.store.bout_by_id(), now=lambda: F.NOW,
                              out=self.out.append, store_path=self.paths["store_path"])
        self.assertIn("graded=0", self.text)
        self.assertEqual(len(L.rows(self.paths["store_path"])), 1)

    def test_record_reports_a_broken_ledger_with_a_nonzero_exit(self):
        self.published()
        path = Path(self.paths["store_path"])
        path.write_text(path.read_text(encoding="utf-8").replace("TAKE_OTHER_SIDE", "TAKE"), encoding="utf-8")
        code = ufc_cli.execute_record(out=self.out.append, store_path=self.paths["store_path"],
                                      usage_path=self.paths["usage_path"], cfg=F.CFG)
        self.assertEqual(code, ufc_cli.EXIT_ERROR)
        self.assertIn("ledger: PROBLEM", self.text)

    def test_the_ufc_record_never_reads_or_writes_the_mlb_files(self):
        from src.analyst import ledger as mlb
        self.assertNotEqual(self.paths["store_path"], mlb.STORE)
        self.published()
        self.assertFalse(any("analyst_v1" in f for f in self.files()))


class TheTopLevelCli(unittest.TestCase):
    def parse(self, *argv):
        from src import cli as top
        return top.build_parser().parse_args(list(argv))

    def test_the_ufc_flags_are_registered(self):
        args = self.parse("analyst", "run", "--sport", "ufc", "--date", "2026-10-10", "--event", "7013",
                          "--dry-run", "--print-request")
        self.assertEqual((args.command, args.analyst_command, args.sport, args.event, args.dry_run, args.print_request),
                         ("analyst", "run", "ufc", "7013", True, True))
        self.assertEqual(self.parse("analyst", "grade", "--sport", "ufc", "--date", "2026-10-10").sport, "ufc")
        self.assertEqual(self.parse("analyst", "record", "--sport", "ufc").sport, "ufc")

    def test_every_mlb_command_parses_as_before_and_defaults_to_mlb(self):
        run = self.parse("analyst", "run", "--date", "2026-10-03", "--dry-run", "--game", "NYY@TB")
        self.assertEqual((run.sport, run.game, run.event, run.dry_run), ("mlb", "NYY@TB", None, True))
        self.assertEqual(self.parse("analyst", "grade", "--date", "2026-10-03").sport, "mlb")
        self.assertEqual(self.parse("analyst", "record").sport, "mlb")

    def test_an_unknown_sport_is_refused_by_the_parser(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse("analyst", "run", "--sport", "nfl", "--date", "2026-10-10")

    def test_game_is_mlb_only_and_event_is_ufc_only(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(ufc_cli.main(self.parse("analyst", "run", "--sport", "ufc", "--date", "2026-10-10",
                                                     "--game", "NYY@TB")), 2)
            self.assertEqual(cli.main(self.parse("analyst", "run", "--date", "2026-10-10", "--event", "7013")), 2)
        self.assertIn("--game is for MLB", buf.getvalue())
        self.assertIn("--event is for --sport ufc", buf.getvalue())

    def test_the_mlb_dispatch_still_reaches_the_mlb_run(self):
        with mock.patch.object(cli, "execute_run", return_value=0) as run, \
                mock.patch.object(ufc_cli, "execute_run", side_effect=AssertionError("ufc")):
            self.assertEqual(cli.main(self.parse("analyst", "run", "--date", "2026-10-03", "--dry-run")), 0)
        self.assertEqual(run.call_args.args, ("2026-10-03",))

    def test_the_ufc_dispatch_reaches_the_ufc_run_and_not_the_mlb_one(self):
        with mock.patch.object(ufc_cli, "execute_run", return_value=0) as run, \
                mock.patch.object(cli, "execute_run", side_effect=AssertionError("mlb")):
            args = self.parse("analyst", "run", "--sport", "ufc", "--date", "2026-10-10", "--event", "7013",
                              "--dry-run", "--refresh", "--model-critic")
            self.assertEqual(cli.main(args), 0)
        self.assertEqual(run.call_args.args, ("2026-10-10",))
        self.assertEqual((run.call_args.kwargs["event"], run.call_args.kwargs["dry_run"],
                          run.call_args.kwargs["refresh"], run.call_args.kwargs["use_model_critic"]),
                         ("7013", True, True, True))


if __name__ == "__main__":
    unittest.main()
