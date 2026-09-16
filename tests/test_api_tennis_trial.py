"""Tests for scripts/api_tennis_trial.py's .env loading, full-day sampling
mode and rescoring. Everything here is driven by an injected fake transport
and an injected clock/sleep -- no real network, no real wall clock, and no
real API_TENNIS_KEY is ever read as a credential."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "api_tennis_trial", REPO_ROOT / "scripts" / "api_tennis_trial.py")
trial = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trial)

from src.providers.api_tennis import ApiTennisError, Client  # noqa: E402

FAKE_KEY = "at-test-do-not-use-1234567890"


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSleep:
    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.calls = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


def _body(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


class ScriptedTransport:
    """Returns queued (status, payload) responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        status, payload = self._responses.pop(0)
        return status, _body(payload)


def _live_match(event_key="1", with_set1=True, set_betting=True):
    scores = [{"score_set": "1", "score_set_1": "6", "score_set_2": "3"}] if with_set1 else []
    return {"event_key": event_key, "scores": scores}


class TestLoadDotenv(unittest.TestCase):
    def test_missing_env_var_error_path_intact(self):
        # No .env, no API_TENNIS_KEY: client_from_env must still raise the
        # named error, proving _load_dotenv() at the top of main() does not
        # swallow or mask the "not set" path when there is nothing to load.
        env = {}
        with self.assertRaises(ApiTennisError) as ctx:
            from src.providers.api_tennis import client_from_env
            client_from_env(env=env)
        self.assertIn("API_TENNIS_KEY", str(ctx.exception))
        self.assertIn("not set", str(ctx.exception))

    def test_load_dotenv_sets_unset_var_but_not_already_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("API_TENNIS_KEY=from-dotenv\nOTHER=1\n", encoding="utf-8")
            saved = dict(os.environ)
            try:
                os.environ.pop("API_TENNIS_KEY", None)
                os.environ["OTHER"] = "already-exported"
                trial._load_dotenv(env_path)
                self.assertEqual(os.environ["API_TENNIS_KEY"], "from-dotenv")
                self.assertEqual(os.environ["OTHER"], "already-exported")  # exported value wins
            finally:
                os.environ.clear()
                os.environ.update(saved)

    def test_dry_run_stays_clean_with_no_key_and_no_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope" / ".env"
            trial._load_dotenv(missing)  # must not raise
            rc = trial.run_dry(print_fn=lambda *a, **k: None)
            self.assertEqual(rc, 0)


class TestSamplingAccumulates(unittest.TestCase):
    def _client(self, responses):
        transport = ScriptedTransport(responses)
        clock = FakeClock()
        return Client(FAKE_KEY, transport=transport, clock=clock, sleep=FakeSleep(clock)), transport

    def test_sample_one_pass_records_check7_and_check9_and_call_count(self):
        # livescore -> one live match with set 1 done
        # check7: get_odds for that match -> Set Betting present
        # check9: two get_live_odds polls, second differs -> one latency
        responses = [
            (200, {"result": [_live_match()]}),                         # get_livescore
            (200, {"result": {"1": {"Set Betting": {"2:0": "1.5"}}}}),   # get_odds (check 7)
            (200, {"result": {"1": {"Match Winner": [{"odd": "1.9", "suspended": "No"}]}}}),  # live_odds poll 1
            (200, {"result": {"1": {"Match Winner": [{"odd": "2.1", "suspended": "No"}]}}}),  # live_odds poll 2
        ]
        client, transport = self._client(responses)
        counting = trial._CountingClient(client)
        records = trial.sample_one_pass(client, counting, "2026-09-16T12:00:00Z")

        kinds = [r["kind"] for r in records]
        self.assertIn("poll_meta", kinds)
        self.assertIn("check7_sample", kinds)
        self.assertIn("check9_latency", kinds)
        self.assertIn("call_count", kinds)
        call_record = next(r for r in records if r["kind"] == "call_count")
        self.assertEqual(call_record["calls"], len(transport.calls))

    def test_sample_one_pass_reports_no_live_match_honestly(self):
        client, _ = self._client([(200, {"result": []})])
        counting = trial._CountingClient(client)
        records = trial.sample_one_pass(client, counting, "2026-09-16T12:00:00Z")
        kinds = [r["kind"] for r in records]
        self.assertIn("no_live_match", kinds)
        self.assertNotIn("check7_sample", kinds)

    def test_run_sample_appends_across_two_passes_without_truncating(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = Path(tmp) / "observations.jsonl"
            responses = [(200, {"result": []})] * 2  # 2 passes, no live match each
            client, _ = self._client(responses)

            times = iter([
                datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 16, 12, 1, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 16, 12, 2, 0, tzinfo=timezone.utc),  # >= deadline, loop exits
            ])
            sample_until = datetime(2026, 9, 16, 12, 2, 0, tzinfo=timezone.utc)

            rc = trial.run_sample(
                sample_until, poll_interval_seconds=0, observations_path=obs_path,
                client=client, print_fn=lambda *a, **k: None,
                now_fn=lambda: next(times), sleep_fn=lambda s: None,
            )
            self.assertEqual(rc, 0)
            records = trial._load_jsonl(obs_path)
            no_live = [r for r in records if r["kind"] == "no_live_match"]
            self.assertEqual(len(no_live), 2)

    def test_run_sample_is_resumable_second_run_keeps_prior_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = Path(tmp) / "observations.jsonl"
            trial._append_jsonl(obs_path, [{"kind": "no_live_match", "ts": "t0"},
                                            {"kind": "call_count", "ts": "t0", "calls": 1}])

            client, _ = self._client([(200, {"result": []})])
            times = iter([
                datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 16, 12, 1, 0, tzinfo=timezone.utc),
            ])
            sample_until = datetime(2026, 9, 16, 12, 1, 0, tzinfo=timezone.utc)
            trial.run_sample(
                sample_until, poll_interval_seconds=0, observations_path=obs_path,
                client=client, print_fn=lambda *a, **k: None,
                now_fn=lambda: next(times), sleep_fn=lambda s: None,
            )
            records = trial._load_jsonl(obs_path)
            # the pre-existing record from "before the restart" must still be there
            self.assertEqual(sum(1 for r in records if r["ts"] == "t0"), 2)
            self.assertGreaterEqual(len(records), 3)

    def test_run_sample_stops_at_daily_call_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = Path(tmp) / "observations.jsonl"
            trial._append_jsonl(obs_path, [{"kind": "call_count", "ts": "t0", "calls": 100}])
            client, _ = self._client([])  # must not be called at all
            printed = []
            rc = trial.run_sample(
                datetime(2026, 9, 17, tzinfo=timezone.utc), poll_interval_seconds=0,
                observations_path=obs_path, daily_call_limit=50, client=client,
                print_fn=printed.append,
                now_fn=lambda: datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc),
                sleep_fn=lambda s: None,
            )
            self.assertEqual(rc, 0)
            self.assertTrue(any("daily call limit" in line for line in printed))


class TestRescore(unittest.TestCase):
    def test_rescore_aggregates_across_accumulated_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = Path(tmp) / "observations.jsonl"
            records = []
            for i in range(25):
                records.append({"kind": "check7_sample", "ts": f"t{i}",
                                 "event_key": str(i), "set_betting_present": i % 5 != 0})
            for i in range(25):
                records.append({"kind": "check9_latency", "ts": f"t{i}", "latency_seconds": 4.0})
            records.append({"kind": "call_count", "ts": "t", "calls": 500})
            trial._append_jsonl(obs_path, records)

            results = trial.rescore_checks_7_9_10(obs_path)
            by_id = {r["id"]: r for r in results}
            self.assertEqual(by_id[7]["measured"]["matches_sampled"], 25)
            self.assertTrue(by_id[7]["pass"])  # 20/25 = 0.8 present, n>=20
            self.assertEqual(by_id[9]["measured"]["triggers_observed"], 25)
            self.assertTrue(by_id[9]["pass"])  # median/worst 4.0 <= thresholds
            self.assertEqual(by_id[10]["measured"]["calls_accumulated"], 500)

    def test_rescore_reports_not_enough_data_below_twenty(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = Path(tmp) / "observations.jsonl"
            trial._append_jsonl(obs_path, [
                {"kind": "check7_sample", "ts": "t0", "event_key": "1", "set_betting_present": True},
            ])
            results = trial.rescore_checks_7_9_10(obs_path)
            by_id = {r["id"]: r for r in results}
            self.assertFalse(by_id[7]["pass"])
            self.assertIn("need >=20", by_id[7]["note"])

    def test_rewrite_results_sections_leaves_check_6_and_8_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_path = Path(tmp) / "results.md"
            original = (
                "# API-Tennis Business trial results\n\n"
                "Generated: 2026-09-16T06:23:00Z\n\n"
                "## Check 6: Point log -- FAIL\n\n"
                "**Measured:** `{\"sets_checked\": 30}`\n\n"
                "## Check 7: Second-set market speed -- FAIL\n\n"
                "**Measured:** `{\"matches_sampled\": 19}`\n\n"
                "## Check 8: Suspension flag -- FAIL\n\n"
                "**Measured:** `{\"moments_checked\": 638}`\n\n"
                "## Check 9: Freshness -- FAIL\n\n"
                "**Measured:** `{\"triggers_observed\": 7}`\n\n"
                "## Check 10: Volume -- NOT ENOUGH DATA\n\n"
                "**Measured:** `{\"calls_this_run\": 77}`\n"
            )
            docs_path.write_text(original, encoding="utf-8")
            saved_results_path = trial.RESULTS_PATH
            trial.RESULTS_PATH = docs_path
            try:
                new_results = [
                    {"id": 7, "name": "Second-set market speed",
                     "measured": {"matches_sampled": 25}, "pass": True, "note": None},
                    {"id": 9, "name": "Freshness",
                     "measured": {"triggers_observed": 22}, "pass": True, "note": None},
                    {"id": 10, "name": "Volume",
                     "measured": {"calls_accumulated": 9000}, "pass": None, "note": "info"},
                ]
                trial.rewrite_results_sections(new_results)
                rewritten = docs_path.read_text(encoding="utf-8")
            finally:
                trial.RESULTS_PATH = saved_results_path

            self.assertIn('"sets_checked": 30', rewritten)  # check 6 untouched
            self.assertIn('"moments_checked": 638', rewritten)  # check 8 untouched
            self.assertIn('"matches_sampled": 25', rewritten)  # check 7 replaced
            self.assertIn('"triggers_observed": 22', rewritten)  # check 9 replaced
            self.assertIn('"calls_accumulated": 9000', rewritten)  # check 10 replaced
            self.assertNotIn('"matches_sampled": 19', rewritten)
            self.assertNotIn('"triggers_observed": 7}', rewritten)
            self.assertNotIn('"calls_this_run": 77', rewritten)


if __name__ == "__main__":
    unittest.main()
