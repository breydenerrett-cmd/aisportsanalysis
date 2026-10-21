"""The watchdog (src/ops/watchdog.py): stuck deploys, red CI, production behind, stalled capture, degraded health,
AI spend, the incident lifecycle that turns them into one email each, the GitHub budget, and the kill switch.

Every test uses an injected GitHub (``FakeGitHub``), an injected clock and a temp state file: nothing touches the
network, the wall clock or the real disk (tests/test_ops_watchdog.py is also part of the CI step that blocks
sockets). Core tests need no FastAPI (Linux CI has none); the route tests skip cleanly where it is missing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import alert_feed as A
from src.ops import watchdog as W

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
HEAD = "f" * 40
REPO_URL = "https://github.com/breydenerrett-cmd/aisportsanalysis"
SECRET = "ghp_SECRETTOKENVALUE0123456789abcdefABCD"


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def run(rid, status="completed", conclusion="success", *, created=None, started=None, updated=None, sha=None,
        msg="Forward capture slot"):
    created = created or ago(minutes=30)
    started = started or created
    updated = updated or started + timedelta(minutes=6)
    return {"id": rid, "status": status, "conclusion": conclusion if status == "completed" else None,
            "html_url": f"{REPO_URL}/actions/runs/{rid}", "created_at": iso(created), "run_started_at": iso(started),
            "updated_at": iso(updated), "head_sha": sha or f"{rid:040x}", "head_commit": {"message": msg}}


def commit(sha, when):
    return {"sha": sha, "commit": {"committer": {"date": iso(when)}, "message": "x"}}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeGitHub:
    """api.github.com as far as the watchdog reads it, with every request recorded."""

    def __init__(self):
        self.deploy_runs, self.tests_runs, self.slate_runs = [], [], []
        self.capture_success, self.capture_newest = [], []
        self.commits, self.jobs, self.logs = [], {}, {}
        self.requests, self.replies = [], []
        self.down = False
        self.status = None
        self.extra_headers = {}

    def api_requests(self):
        return [(u, h) for u, h in self.requests if u.startswith("https://api.github.com")]

    def paths(self):
        return [urllib.parse.urlparse(u).path for u, _ in self.api_requests()]

    def __call__(self, url, headers):
        reply = self.answer(url, headers)
        self.replies.append(reply)
        return reply

    def answer(self, url, headers):
        self.requests.append((url, dict(headers)))
        if self.down:
            raise OSError("network is down")
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != "api.github.com":
            return W.Reply(200, {}, self.logs.get("blob", ""))
        if self.status:
            return W.Reply(self.status, dict(self.extra_headers), "{}")
        path, q = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
        if path.endswith("/actions/workflows/deploy-prod.yml/runs"):
            body = {"workflow_runs": self.deploy_runs}
        elif path.endswith("/actions/workflows/tests.yml/runs"):
            body = {"workflow_runs": self.tests_runs}
        elif path.endswith("/actions/workflows/afternoon-slate.yml/runs"):
            body = {"workflow_runs": self.slate_runs}
        elif path.endswith("/actions/workflows/forward-capture.yml/runs"):
            body = {"workflow_runs": self.capture_success if q.get("status") == "success" else self.capture_newest}
        elif path.endswith("/commits"):
            body = self.commits
        elif "/actions/runs/" in path and path.endswith("/jobs"):
            body = {"jobs": self.jobs.get(int(path.split("/")[-2]), [])}
        elif "/actions/jobs/" in path and path.endswith("/logs"):
            return W.Reply(302, {"location": "https://logs.example.test/blob"}, "")
        else:
            return W.Reply(404, {}, "{}")
        text = json.dumps(body)
        etag = 'W/"%s"' % hashlib.md5(text.encode()).hexdigest()
        if headers.get("If-None-Match") == etag:
            return W.Reply(304, {"etag": etag}, "")
        return W.Reply(200, dict(self.extra_headers, etag=etag), text)


class Rig:
    """A watchdog wired to fakes, starting from a healthy world: production is on the branch's newest commit, the
    tests are green, a deploy finished an hour ago in 6 minutes and capture succeeded 20 minutes ago."""

    def __init__(self, case, env=None, version="head"):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.clock = Clock(NOW)
        self.gh = FakeGitHub()
        self.store = W.StateStore(self.tmp / "state.json")
        self.env = {"WATCHDOG": "on"}
        self.env.update(env or {})
        self.health, self.ai = [], None
        self.version = {"sha": HEAD, "source": "test"} if version == "head" else version
        self.started = iso(ago(minutes=50))
        self.gh.deploy_runs = [run(900 - i, started=ago(minutes=70 + 60 * i), updated=ago(minutes=64 + 60 * i))
                               for i in range(3)]
        self.gh.tests_runs = [run(800, sha=HEAD)]
        self.gh.capture_success = [run(700, updated=ago(minutes=20))]
        self.gh.commits = [commit(HEAD, ago(minutes=30))]
        self.dog = self.make()

    def make(self):
        return W.Watchdog(env=self.env, http=self.gh, now=self.clock, store=self.store,
                          version=lambda: self.version, started_utc=lambda: self.started,
                          health=lambda now: list(self.health), ai_spend=lambda now: self.ai)

    def restart(self):
        self.dog = self.make()

    def tick(self, **advance):
        if advance:
            self.clock.advance(**advance)
        return self.dog.run_once()

    def incidents(self, status="open"):
        return [i for i in self.store.load()["incidents"] if i["status"] == status]

    def feed(self, **kw):
        return W.feed_alerts(self.clock.now, env=self.env, store=self.store, **kw)

    def status(self):
        return W.status(env=self.env, store=self.store, now=self.clock.now)

    def check(self, name):
        return self.store.load()["checks"][name]["state"]


# ---------------------------------------------------------------------------
# 1. a deploy stuck, queued or running too long
# ---------------------------------------------------------------------------

class StuckDeploy(unittest.TestCase):
    def stuck(self, rig, minutes=34, rid=101):
        rig.gh.deploy_runs.insert(0, run(rid, "in_progress", created=ago(minutes=minutes), started=ago(minutes=minutes)))

    def test_a_running_deploy_past_the_limit_says_how_long_what_is_normal_and_what_to_click(self):
        rig = Rig(self)
        self.stuck(rig)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "deploy_stuck")
        self.assertIn("Deploy to production has been running 34 min (normal is 6)", inc["what"])
        self.assertIn(f"open {REPO_URL}/actions/runs/101 and click Cancel workflow; Claude will redeploy", inc["fix"])
        self.assertEqual(inc["url"], f"{REPO_URL}/actions/runs/101")
        (item,) = rig.feed()
        self.assertEqual(item["description"].count("Fix:"), 1)
        self.assertIn("(normal is 6). ", item["description"])

    def test_normal_is_the_median_of_recent_finished_deploys_not_a_constant(self):
        rig = Rig(self)
        rig.gh.deploy_runs = [run(900 + i, started=ago(minutes=100 + 60 * i), updated=ago(minutes=100 + 60 * i) + timedelta(minutes=m))
                              for i, m in enumerate((10, 12, 14))]
        self.stuck(rig, 40)
        rig.tick()
        self.assertIn("(normal is 12)", rig.incidents()[0]["what"])

    def test_the_limit_is_strictly_more_than_twenty_five_minutes(self):
        rig = Rig(self)
        self.stuck(rig, 25)
        rig.tick()
        self.assertEqual(rig.check("deploy_stuck"), "ok")
        self.assertEqual(rig.incidents(), [])
        rig.gh.deploy_runs[0] = run(101, "in_progress", created=ago(minutes=26), started=ago(minutes=26))
        rig.tick(minutes=10)
        self.assertEqual(rig.check("deploy_stuck"), "alert")

    def test_a_normal_slow_deploy_of_twelve_minutes_is_not_stuck(self):
        rig = Rig(self)
        self.stuck(rig, 12)
        rig.tick()
        self.assertEqual(rig.check("deploy_stuck"), "ok")

    def test_runs_queued_behind_the_stuck_one_are_counted_and_the_stuck_one_is_the_cause(self):
        rig = Rig(self)
        rig.gh.deploy_runs = [run(103, "queued", created=ago(minutes=25)), run(102, "queued", created=ago(minutes=85)),
                              run(101, "in_progress", created=ago(minutes=130), started=ago(minutes=130))] + rig.gh.deploy_runs
        rig.tick()
        (inc,) = rig.incidents()
        self.assertIn("running 2 h 10 min", inc["what"])
        self.assertIn("2 more runs are queued behind it", inc["what"])
        self.assertTrue(inc["url"].endswith("/runs/101"))

    def test_a_deploy_that_never_starts_is_stuck_too(self):
        rig = Rig(self)
        rig.gh.deploy_runs.insert(0, run(104, "pending", created=ago(minutes=45)))
        rig.tick()
        (inc,) = rig.incidents()
        self.assertIn("waiting to start for 45 min", inc["what"])
        self.assertIn("click Cancel workflow", inc["fix"])

    def test_a_healthy_world_opens_nothing_and_the_feed_stays_empty(self):
        rig = Rig(self)
        rig.tick()
        self.assertEqual(rig.incidents(), [])
        self.assertEqual(rig.feed(), [])
        self.assertEqual({c["state"] for n, c in rig.store.load()["checks"].items() if n != "ai_spend"}, {"ok"})
        self.assertEqual(rig.check("ai_spend"), "skipped")


class OtherWorkflowsStuck(unittest.TestCase):
    """Limits the orchestrator measured on 2026-10-20: tests 45, forward-capture 130 (runs take 65 to 75 and two can
    overlap while one waits in the concurrency queue), afternoon-slate 60."""

    def rig_with(self, attr, status, minutes, rid=300):
        rig = Rig(self)
        extra = run(rid, status, created=ago(minutes=minutes), started=ago(minutes=minutes))
        setattr(rig.gh, attr, [extra] + getattr(rig.gh, attr))
        return rig

    def test_the_limits_are_the_measured_ones(self):
        self.assertEqual(W.STUCK_MINUTES_BY_WORKFLOW,
                         {"deploy-prod.yml": 25, "tests.yml": 45, "forward-capture.yml": 130, "afternoon-slate.yml": 60})

    def test_tests_running_44_minutes_are_fine_46_are_stuck(self):
        rig = self.rig_with("tests_runs", "in_progress", 44)
        rig.tick()
        self.assertEqual(rig.check("tests_stuck"), "ok")
        rig = self.rig_with("tests_runs", "in_progress", 46)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "tests_stuck")
        self.assertIn("The test run has been running 46 min (normal is 6)", inc["what"], "median of the finished runs seen")
        rig = self.rig_with("tests_runs", "in_progress", 46)
        rig.gh.tests_runs = rig.gh.tests_runs[:1]              # nothing finished to take a median of: the measured default
        rig.tick()
        self.assertIn("(normal is 20)", rig.incidents()[0]["what"])
        self.assertIn("click Cancel workflow; Claude will re-run it", inc["fix"])

    def test_a_forward_capture_run_of_seventy_minutes_is_normal_and_131_is_stuck(self):
        rig = self.rig_with("capture_newest", "in_progress", 75)
        rig.tick()
        self.assertEqual(rig.check("capture_run"), "ok", "the false alarm of 2026-10-20 was a 60 minute limit")
        rig = self.rig_with("capture_newest", "in_progress", 131)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "capture_run_stuck")
        self.assertIn("The data-capture run has been running 2 h 11 min (normal is 70)", inc["what"])

    def test_a_queued_forward_capture_run_waits_a_full_130_minutes_before_it_is_alarming(self):
        rig = self.rig_with("capture_newest", "queued", 129)
        rig.gh.capture_newest.append(run(301, "in_progress", created=ago(minutes=60), started=ago(minutes=60)))   # the overlap
        rig.tick()
        self.assertEqual(rig.check("capture_run"), "ok")
        rig = self.rig_with("capture_newest", "queued", 131)
        rig.tick()
        self.assertEqual(rig.check("capture_run"), "alert")

    def test_an_afternoon_slate_run_is_stuck_after_an_hour(self):
        rig = self.rig_with("slate_runs", "in_progress", 59)
        rig.tick()
        self.assertEqual(rig.check("slate_stuck"), "ok")
        rig = self.rig_with("slate_runs", "in_progress", 61)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "slate_stuck")
        self.assertIn("The afternoon slate run has been running 61 min", inc["what"])
        self.assertNotIn("normal is", inc["what"], "no measured normal, so none is claimed")

    def test_each_workflow_is_its_own_incident_and_clears_on_its_own(self):
        rig = self.rig_with("tests_runs", "in_progress", 50)
        rig.gh.deploy_runs.insert(0, run(101, "in_progress", created=ago(minutes=30), started=ago(minutes=30)))
        rig.tick()
        self.assertEqual(sorted(i["kind"] for i in rig.incidents()), ["deploy_stuck", "tests_stuck"])
        rig.gh.tests_runs[0] = run(300, "completed", "success", created=ago(minutes=50), updated=ago(minutes=1))
        rig.tick(minutes=10)
        self.assertEqual([i["kind"] for i in rig.incidents()], ["deploy_stuck"])
        self.assertTrue(any(i["title"].startswith("Resolved: The test run is stuck") for i in rig.feed()))


# ---------------------------------------------------------------------------
# the incident lifecycle: one alert per incident, one all-clear
# ---------------------------------------------------------------------------

class Lifecycle(unittest.TestCase):
    def open_stuck(self, rig, minutes=34):
        rig.gh.deploy_runs.insert(0, run(101, "in_progress", created=ago(minutes=minutes), started=ago(minutes=minutes)))
        rig.tick()

    def test_ten_polls_and_a_restart_are_one_incident_with_one_guid_and_a_frozen_text(self):
        rig = Rig(self)
        self.open_stuck(rig)
        first = rig.feed()[0]
        for _ in range(5):
            rig.tick(minutes=10)
        rig.restart()
        rig.tick(minutes=10)
        (inc,) = rig.incidents()
        (again,) = rig.feed()
        self.assertEqual(again["guid"], first["guid"])
        self.assertEqual(again["description"], first["description"], "the feed text is the opened-time snapshot")
        self.assertEqual(again["pub"], first["pub"])
        self.assertIn("running 34 min", again["description"])
        self.assertIn("running 94 min", inc["current_what"])
        live = rig.status()["open_incidents"][0]["what"]
        self.assertIn("running 94 min", live, "GET /admin/watchdog shows the live text")

    def test_it_clears_with_exactly_one_all_clear_that_says_what_it_was(self):
        rig = Rig(self)
        self.open_stuck(rig)
        opened_guid = rig.feed()[0]["guid"]
        rig.gh.deploy_runs[0] = run(101, "completed", "cancelled", created=ago(minutes=40), started=ago(minutes=40),
                                    updated=ago(minutes=2))
        rig.tick(minutes=10)
        self.assertEqual(rig.incidents(), [])
        (clear,) = rig.feed()
        self.assertEqual(clear["guid"], opened_guid + ":resolved")
        self.assertTrue(clear["title"].startswith("Resolved: Deploy to production is stuck"))
        self.assertIn("All clear: no deploy has been running or waiting longer than 25 min", clear["description"])
        self.assertIn("This was the alert", clear["description"])
        rig.tick(minutes=10)
        rig.restart()
        rig.tick(minutes=10)
        self.assertEqual([i["guid"] for i in rig.feed()], [opened_guid + ":resolved"], "no second all-clear")
        self.assertEqual(rig.status()["recently_resolved"][0]["kind"], "deploy_stuck")

    def test_the_all_clear_leaves_the_feed_after_its_window_and_the_state_after_a_week(self):
        rig = Rig(self)
        self.open_stuck(rig)
        rig.gh.deploy_runs.pop(0)
        rig.tick(minutes=10)
        self.assertEqual(len(rig.feed()), 1)
        rig.clock.advance(hours=W.RESOLVED_FEED_HOURS, minutes=1)
        self.assertEqual(rig.feed(), [])
        rig.clock.advance(days=W.RESOLVED_KEEP_DAYS + 1)
        rig.gh.capture_success[0]["updated_at"] = iso(rig.clock.now - timedelta(minutes=20))   # the world stayed healthy
        rig.tick()
        self.assertEqual(rig.store.load()["incidents"], [])

    def test_a_second_incident_of_the_same_kind_is_a_new_guid(self):
        rig = Rig(self)
        self.open_stuck(rig)
        first = rig.feed()[0]["guid"]
        rig.gh.deploy_runs.pop(0)
        rig.tick(minutes=10)
        rig.gh.deploy_runs.insert(0, run(102, "in_progress", created=ago(minutes=-60), started=ago(minutes=-60)))
        rig.tick(hours=2)
        guids = {i["guid"] for i in rig.feed()}
        self.assertEqual(len(guids), 2)
        self.assertIn(first + ":resolved", guids)
        self.assertNotIn(first, guids)

    def test_not_knowing_is_not_all_clear_an_open_incident_survives_a_github_outage(self):
        rig = Rig(self)
        self.open_stuck(rig)
        rig.gh.down = True
        rig.tick(minutes=10)
        self.assertEqual(rig.check("deploy_stuck"), "alert", "a short blip is covered by the last answer")
        rig.tick(minutes=70)                       # now the last answer is older than an hour: no longer a fact
        self.assertEqual(rig.check("deploy_stuck"), "unknown")
        self.assertEqual(len(rig.incidents()), 1, "an outage must not resolve what it cannot see")
        self.assertEqual(len(rig.feed()), 1)
        self.assertEqual(rig.feed()[0]["description"].count("Cancel workflow"), 1)

    def test_two_different_problems_are_two_incidents(self):
        rig = Rig(self)
        self.open_stuck(rig)
        rig.gh.capture_success = [run(700, updated=ago(hours=5))]
        rig.tick(minutes=10)
        self.assertEqual(sorted(i["kind"] for i in rig.incidents()), ["capture_stalled", "deploy_stuck"])


# ---------------------------------------------------------------------------
# 2. CI red
# ---------------------------------------------------------------------------

LOG = """2026-10-20T14:00:01.1234567Z test_alpha (tests.test_a.A.test_alpha) ... ok
2026-10-20T14:09:12.0000000Z ======================================================================
2026-10-20T14:09:12.0000001Z FAIL: test_picks_sorted (tests.test_card.CardTests.test_picks_sorted)
2026-10-20T14:09:12.0000002Z ERROR: test_feed_guid (tests.test_feeds.FeedTests.test_feed_guid)
2026-10-20T14:09:12.0000003Z FAIL: test_picks_sorted (tests.test_card.CardTests.test_picks_sorted)
2026-10-20T14:09:13.0000000Z Ran 4200 tests in 190.0s
"""


class CiRed(unittest.TestCase):
    def red(self, rig, rid=811, **kw):
        return run(rid, "completed", "failure", created=ago(minutes=kw.get("minutes", 30)), sha="c" * 40,
                   msg="Add the thing\n\nlong body")

    def jobs(self, rig, rid=811):
        rig.gh.jobs[rid] = [{"id": 5001, "name": "unittest (3.10)", "conclusion": "failure",
                             "steps": [{"name": "Set up Python", "conclusion": "success"},
                                       {"name": "Run the test suite", "conclusion": "failure"}]},
                            {"id": 5002, "name": "unittest (3.12)", "conclusion": "success", "steps": []}]

    def test_a_failed_latest_run_names_the_job_the_step_and_the_run_url(self):
        rig = Rig(self)
        rig.gh.tests_runs = [self.red(rig), run(800)]
        self.jobs(rig)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "ci_red")
        self.assertIn('the latest run (ccccccc, "Add the thing") failed', inc["what"])
        self.assertIn('in the job "unittest (3.10)" at the step "Run the test suite"', inc["what"])
        self.assertIn("Production only redeploys when the tests are green", inc["what"])
        self.assertIn(f"open {REPO_URL}/actions/runs/811", inc["fix"])
        self.assertNotIn("unittest (3.12)", inc["what"], "only the failing job is named")

    def test_failing_twice_in_a_row_is_one_incident_that_says_so(self):
        rig = Rig(self)
        rig.gh.tests_runs = [self.red(rig, 812), self.red(rig, 811), run(800)]
        self.jobs(rig, 812)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertIn("failed, 2 runs in a row", inc["what"])
        rig.gh.tests_runs.insert(0, self.red(rig, 813))
        rig.tick(minutes=10)
        self.assertEqual(len(rig.incidents()), 1, "a third red run extends the incident, it does not open another")
        self.assertIn("3 runs in a row", rig.incidents()[0]["current_what"])

    def test_with_a_token_the_failing_test_is_named_and_the_token_never_leaves_api_github_com(self):
        rig = Rig(self, env={"GITHUB_TOKEN": SECRET})
        rig.gh.tests_runs = [self.red(rig)]
        self.jobs(rig)
        rig.gh.logs["blob"] = LOG
        rig.restart()
        rig.tick()
        (inc,) = rig.incidents()
        self.assertIn("Failing: test_picks_sorted (tests.test_card.CardTests.test_picks_sorted); "
                      "test_feed_guid (tests.test_feeds.FeedTests.test_feed_guid)", inc["what"])
        self.assertIn("ask Claude to fix test_picks_sorted", inc["fix"])
        for url, headers in rig.gh.requests:
            if url.startswith("https://api.github.com"):
                self.assertEqual(headers.get("Authorization"), f"Bearer {SECRET}")
            else:
                self.assertNotIn("Authorization", headers, "the log download must not receive the token")
        self.assertEqual([u for u, _ in rig.gh.requests if "logs.example.test" in u], ["https://logs.example.test/blob"])

    def test_without_a_token_the_logs_are_not_even_requested(self):
        rig = Rig(self)
        rig.gh.tests_runs = [self.red(rig)]
        self.jobs(rig)
        rig.tick()
        self.assertFalse([p for p in rig.gh.paths() if p.endswith("/logs")])
        self.assertNotIn("Failing:", rig.incidents()[0]["what"])

    def test_cancelled_and_skipped_runs_are_not_a_verdict(self):
        rig = Rig(self)
        rig.gh.tests_runs = [run(814, "completed", "cancelled"), run(813, "completed", "skipped"), run(800)]
        rig.tick()
        self.assertEqual(rig.check("ci_tests"), "ok")

    def test_green_again_resolves_it_and_no_finished_run_is_unknown_not_green(self):
        rig = Rig(self)
        rig.gh.tests_runs = [self.red(rig)]
        rig.tick()
        self.assertEqual(len(rig.incidents()), 1)
        rig.gh.tests_runs = [run(815, sha="d" * 40), self.red(rig)]
        rig.tick(minutes=10)
        self.assertEqual(rig.incidents(), [])
        self.assertIn("The latest tests run on the working branch passed".lower(), rig.feed()[0]["description"].lower())
        rig.gh.tests_runs = []
        rig.tick(minutes=10)
        self.assertEqual(rig.check("ci_tests"), "unknown")

    def test_it_asks_github_for_finished_runs_on_the_working_branch_only(self):
        rig = Rig(self)
        rig.tick()
        queries = [dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query)) for u, _ in rig.gh.api_requests()
                   if "tests.yml" in u]
        self.assertEqual(queries, [{"branch": W.BRANCH, "per_page": "20"}], "one request serves the CI and stuck checks")

    def test_log_parser_reads_unittest_and_pytest_lines_once_each(self):
        self.assertEqual(W.failing_tests_from_log(LOG),
                         ["test_picks_sorted (tests.test_card.CardTests.test_picks_sorted)",
                          "test_feed_guid (tests.test_feeds.FeedTests.test_feed_guid)"])
        self.assertEqual(W.failing_tests_from_log("2026-10-20T1:2:3Z FAILED tests/test_x.py::T::test_y - boom\n"),
                         ["tests/test_x.py::T::test_y"])
        self.assertEqual(W.failing_tests_from_log("all fine\n"), [])


# ---------------------------------------------------------------------------
# 3. production behind the branch
# ---------------------------------------------------------------------------

def history(missing_minutes, deployed="a" * 40, newer=3):
    """Commits newest first: ``newer`` commits production lacks, the oldest of them ``missing_minutes`` old, then
    the deployed commit."""
    out = [commit(str(i + 1) * 40, ago(minutes=missing_minutes * (newer - i) / newer if newer > 1 else missing_minutes))
           for i in range(newer)]
    out[-1] = commit(out[-1]["sha"], ago(minutes=missing_minutes))
    out.append(commit(deployed, ago(minutes=missing_minutes + 40)))
    out.append(commit("9" * 40, ago(minutes=missing_minutes + 80)))
    return out


class ProdBehind(unittest.TestCase):
    def rig(self, missing, **kw):
        rig = Rig(self, version={"sha": "a" * 40, "source": "test"})
        rig.gh.commits = history(missing, **kw)
        return rig

    def test_behind_more_than_ninety_minutes_with_green_tests_says_what_to_click(self):
        rig = self.rig(130)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "prod_behind")
        self.assertIn("Production is 2 h 10 min behind the code: it runs aaaaaaa while the working branch is at 1111111, "
                      "3 commits newer, and the tests are green, so it should have redeployed", inc["what"])
        self.assertIn("click Run workflow", inc["fix"])
        self.assertIn("deploy-prod.yml", inc["fix"])

    def test_normal_hourly_lag_is_not_an_alert_and_the_limit_is_ninety(self):
        rig = self.rig(90)
        rig.tick()
        self.assertEqual(rig.check("prod_behind"), "ok")
        self.assertIn("normal lag", rig.store.load()["checks"]["prod_behind"]["summary"])
        rig.gh.commits = history(91)
        rig.tick(minutes=10)
        self.assertEqual(rig.check("prod_behind"), "alert")

    def test_at_the_branch_head_is_ok(self):
        rig = Rig(self)
        rig.tick()
        self.assertEqual(rig.check("prod_behind"), "ok")
        self.assertIn("newest commit", rig.store.load()["checks"]["prod_behind"]["summary"])

    def test_red_tests_explain_the_lag_so_no_second_alert_is_raised(self):
        rig = self.rig(200)
        rig.gh.tests_runs = [run(811, "completed", "failure")]
        rig.tick()
        self.assertEqual(rig.check("prod_behind"), "suppressed")
        self.assertIn("the tests are red, so it is expected to be", rig.store.load()["checks"]["prod_behind"]["summary"])
        self.assertEqual([i["kind"] for i in rig.incidents()], ["ci_red"])
        rig.gh.tests_runs = []                      # tests state unknown: still no alert, but a different reason
        rig.tick(minutes=10)
        self.assertEqual(rig.check("prod_behind"), "suppressed")
        self.assertIn("state is unknown", rig.store.load()["checks"]["prod_behind"]["summary"])

    def test_an_open_behind_incident_is_not_closed_by_the_tests_going_red(self):
        rig = self.rig(130)
        rig.tick()
        rig.gh.tests_runs = [run(811, "completed", "failure")]
        rig.tick(minutes=10)
        self.assertEqual(sorted(i["kind"] for i in rig.incidents()), ["ci_red", "prod_behind"])

    def test_when_production_does_not_know_its_commit_the_check_is_unknown_and_says_why(self):
        rig = Rig(self, version=None)
        rig.started = iso(ago(days=3))
        rig.tick()
        self.assertEqual(rig.check("prod_behind"), "unknown")
        self.assertEqual(rig.incidents(), [])
        self.assertIn("not known", rig.store.load()["checks"]["prod_behind"]["summary"])

    def test_without_a_version_file_the_commit_is_inferred_from_the_deploy_run_that_built_this_process(self):
        rig = Rig(self, version=None)
        built = "b" * 40
        rig.gh.deploy_runs = [run(901, started=ago(minutes=200), updated=ago(minutes=194), sha="c" * 40),
                              run(902, started=ago(minutes=300), updated=ago(minutes=294), sha=built)]
        rig.started = iso(ago(minutes=296))          # during run 902's deploy step
        rig.gh.commits = history(130, deployed=built)
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "prod_behind")
        self.assertEqual(rig.store.load()["checks"]["prod_behind"]["detail"]["deployed_source"],
                         "inferred from deploy-prod run 902 (the image has no VERSION file)")

    def test_a_commit_older_than_the_fetched_history_is_reported_as_at_least(self):
        rig = Rig(self, version={"sha": "e" * 40, "source": "test"})
        rig.gh.commits = [commit(f"{i + 1:040x}", ago(minutes=500 - i)) for i in range(50)]
        rig.tick()
        (inc,) = rig.incidents()
        self.assertIn("50+ commits newer", inc["what"])

    def test_a_short_sha_from_a_setting_matches_the_full_one(self):
        rig = Rig(self, version={"sha": "aaaaaaa", "source": "GIT_SHA setting"})
        rig.gh.commits = history(130)
        rig.tick()
        self.assertEqual(rig.check("prod_behind"), "alert")

    def test_the_last_failed_deploy_is_named_in_the_alert(self):
        rig = self.rig(130)
        rig.gh.deploy_runs.insert(0, run(930, "completed", "failure", created=ago(minutes=20), updated=ago(minutes=15)))
        rig.tick()
        self.assertIn(f"The last deploy-prod run ended failure: {REPO_URL}/actions/runs/930", rig.incidents()[0]["what"])

    def test_it_clears_when_production_redeploys(self):
        rig = self.rig(130)
        rig.tick()
        rig.version = {"sha": HEAD, "source": "test"}
        rig.gh.commits = [commit(HEAD, ago(minutes=5))] + rig.gh.commits
        rig.tick(minutes=10)
        self.assertEqual(rig.incidents(), [])
        self.assertIn("Resolved: Production is", rig.feed()[0]["title"])


# ---------------------------------------------------------------------------
# 4. capture stalled
# ---------------------------------------------------------------------------

class CaptureStalled(unittest.TestCase):
    def test_three_hours_without_a_success_alerts_and_explains_the_cost(self):
        rig = Rig(self)
        rig.gh.capture_success = [run(700, updated=ago(hours=4))]
        rig.gh.capture_newest = [run(710, "completed", "failure")]
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "capture_stalled")
        self.assertIn("No forward-capture run has succeeded in 4 h 00 min", inc["what"])
        self.assertIn("the newest run is failure", inc["what"])
        self.assertIn("the hourly production redeploy stops too", inc["what"])
        self.assertIn("forward-capture.yml", inc["fix"])
        self.assertIn("click Run workflow", inc["fix"])

    def test_just_inside_three_hours_is_fine(self):
        rig = Rig(self)
        rig.gh.capture_success = [run(700, updated=ago(hours=2, minutes=59))]
        rig.tick()
        self.assertEqual(rig.check("capture"), "ok")

    def test_no_success_on_record_at_all_is_an_alert_not_a_pass(self):
        rig = Rig(self)
        rig.gh.capture_success = []
        rig.tick()
        (inc,) = rig.incidents()
        self.assertIn("no successful forward-capture run at all", inc["what"])

    def test_it_asks_only_for_the_newest_success(self):
        rig = Rig(self)
        rig.tick()
        queries = [dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query)) for u, _ in rig.gh.api_requests()
                   if "forward-capture.yml" in u]
        self.assertEqual(sorted(queries, key=str), [{"per_page": "1", "status": "success"}, {"per_page": "10"}])

    def test_a_new_success_resolves_it(self):
        rig = Rig(self)
        rig.gh.capture_success = [run(700, updated=ago(hours=4))]
        rig.tick()
        rig.gh.capture_success = [run(701, updated=ago(minutes=1))]
        rig.tick(minutes=10)
        self.assertEqual(rig.incidents(), [])
        self.assertIn("All clear", rig.feed()[0]["description"])


# ---------------------------------------------------------------------------
# 5 and 6. health (reused) and AI spend
# ---------------------------------------------------------------------------

def health_alert(kind="odds_stale"):
    return {"kind": kind, "title": "Odds are 4 hours old", "what": "The newest odds row is 4 hours old",
            "fix": "open the Health tab", "pub": ago(hours=1)}


class Health(unittest.TestCase):
    def test_a_degraded_health_check_is_an_incident_but_not_a_second_feed_item(self):
        rig = Rig(self)
        rig.health = [health_alert()]
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "health:odds_stale")
        self.assertFalse(inc["feed"])
        self.assertEqual(rig.feed(), [], "the alerts feed already carries it, once per UTC day")
        self.assertEqual(rig.status()["open_incidents"][0]["in_alerts_feed"], False)
        self.assertEqual(rig.check("health"), "alert")

    def test_when_the_health_clears_the_owner_gets_the_all_clear(self):
        rig = Rig(self)
        rig.health = [health_alert()]
        rig.tick()
        rig.health = []
        rig.tick(minutes=10)
        (clear,) = rig.feed()
        self.assertTrue(clear["title"].startswith("Resolved: Odds are 4 hours old"))
        self.assertIn("All clear: GET /health shows nothing that needs doing", clear["description"])

    def test_a_health_check_that_raises_is_an_error_and_the_other_checks_still_run(self):
        rig = Rig(self)

        def boom(now):
            raise RuntimeError("apphealth blew up")
        rig.dog._health = boom
        rig.gh.capture_success = [run(700, updated=ago(hours=5))]
        with self.assertLogs("linehound.ops.watchdog", "ERROR"):
            rig.tick()
        self.assertEqual(rig.check("health"), "error")
        self.assertEqual([i["kind"] for i in rig.incidents()], ["capture_stalled"])

    def test_the_real_source_runs_the_apps_own_checks_without_the_watchdogs_items(self):
        healthy = {"status": "ok", "reasons": [], "odds": {}, "forward_captures": {},
                   "data_freshness": {"stores": {}}}
        with mock.patch("src.appstate.apphealth.report", return_value=healthy), \
                mock.patch.object(A, "pause_facts", return_value=[]):
            self.assertEqual(W.health_alerts_source(lambda: iso(ago(hours=9)))(NOW)[0]["kind"], "deploy_stale")
            self.assertEqual(W.health_alerts_source(lambda: iso(ago(minutes=5)))(NOW), [])


class AiSpend(unittest.TestCase):
    def test_no_usage_store_means_skipped_not_alerted_not_ok(self):
        rig = Rig(self)
        rig.ai = None
        rig.tick()
        self.assertEqual(rig.check("ai_spend"), "skipped")
        self.assertEqual(rig.incidents(), [])

    def test_eighty_percent_of_the_cap_alerts_and_says_nothing_is_overspent(self):
        rig = Rig(self)
        rig.ai = {"fraction": 0.85, "spent_usd": 5.1, "cap_usd": 6.0, "key": "k", "label": "the analyst's run for 2026-10-20"}
        rig.tick()
        (inc,) = rig.incidents()
        self.assertEqual(inc["title"], "AI spend is at 85% of its cap")
        self.assertIn("$5.10 of $6.00", inc["what"])
        self.assertIn("the analyst stops itself at 100%", inc["fix"])

    def test_below_eighty_is_fine_and_still_reported(self):
        rig = Rig(self)
        rig.ai = {"fraction": 0.79, "spent_usd": 4.74, "cap_usd": 6.0, "key": "k", "label": "run"}
        rig.tick()
        self.assertEqual(rig.check("ai_spend"), "ok")

    def usage_root(self, rows, store="evidence/analyst_usage_v1.jsonl", config=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "evidence").mkdir()
        (root / store).write_text("\n".join(json.dumps(r) if isinstance(r, dict) else r for r in rows), encoding="utf-8")
        if config is not None:
            (root / "config").mkdir()
            (root / "config" / "analyst.json").write_text(json.dumps(config), encoding="utf-8")
        return root

    def row(self, usd, run_id="r1", date="2026-10-20", at=None, **extra):
        return dict({"kind": "analyst_usage", "date": date, "run_id": run_id, "cost_usd": usd,
                     "logged_utc": iso(at or ago(hours=1)), "input_tokens": 1000, "output_tokens": 1000}, **extra)

    def test_the_status_reads_the_paid_store_and_groups_by_run(self):
        root = self.usage_root([self.row(2.5), self.row(2.6), self.row(1.0, run_id="r0", at=ago(hours=30)), "{not json"])
        out = W.ai_spend_status(env={}, now=NOW, root=root, router_usage_path=NO_METER)
        self.assertAlmostEqual(out["spent_usd"], 5.1)
        self.assertEqual(out["cap_usd"], 6.0)
        self.assertAlmostEqual(out["fraction"], 0.85)

    def test_the_cap_comes_from_config_and_tokens_count_when_closer(self):
        root = self.usage_root([self.row(1.0, input_tokens=500000, output_tokens=0)],
                               config={"spend_cap": {"max_usd_per_run": 10.0, "max_tokens_per_run": 600000}})
        out = W.ai_spend_status(env={}, now=NOW, root=root, router_usage_path=NO_METER)
        self.assertEqual(out["cap_usd"], 10.0)
        self.assertAlmostEqual(out["fraction"], 500000 / 600000)

    def test_pilot_usage_is_a_claude_session_estimate_not_paid_spend_and_is_ignored(self):
        root = self.usage_root([self.row(50.0)], store="evidence/analyst_pilot_usage_v1.jsonl")
        self.assertIsNone(W.ai_spend_status(env={}, now=NOW, root=root, router_usage_path=NO_METER))

    def test_no_store_at_all_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(W.ai_spend_status(env={}, now=NOW, root=Path(tmp), router_usage_path=NO_METER))

    def test_an_optional_monthly_cap_is_judged_over_the_month(self):
        root = self.usage_root([self.row(30.0, run_id=f"r{i}", date="2026-10-%02d" % (i + 1), at=ago(days=i + 3))
                                for i in range(2)])
        out = W.ai_spend_status(env={"AI_MONTHLY_CAP_USD": "60"}, now=NOW, root=root, router_usage_path=NO_METER)
        self.assertAlmostEqual(out["fraction"], 1.0)
        self.assertIn("AI_MONTHLY_CAP_USD", out["label"])
        self.assertAlmostEqual(W.ai_spend_status(env={"AI_MONTHLY_CAP_USD": "junk"}, now=NOW, root=root, router_usage_path=NO_METER)["fraction"], 0.0)


NO_METER = Path(tempfile.gettempdir()) / "linehound-watchdog-no-such-meter" / "ai_usage_v1.jsonl"


class RouterSpendTests(unittest.TestCase):
    """The AI hounds' paid spend lives in the router's meter beside the app database, not in evidence/."""

    def meter(self, rows):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ai_usage_v1.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def call(self, usd, month=None, provider="anthropic"):
        month = month or NOW.strftime("%Y-%m")
        return {"kind": "call", "provider": provider, "status": "ok", "cost_usd": usd,
                "day": month + "-01", "month": month, "ts": month + "-01T00:00:00Z"}

    def empty_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_the_router_meter_is_judged_against_the_paid_cap(self):
        path = self.meter([self.call(2.0), self.call(2.25), self.call(9.0, month="2020-01")])
        out = W.ai_spend_status(env={"AI_PAID_CAP_USD": "5"}, now=NOW, root=self.empty_root(), router_usage_path=path)
        self.assertAlmostEqual(out["spent_usd"], 4.25)
        self.assertEqual(out["cap_usd"], 5.0)
        self.assertAlmostEqual(out["fraction"], 0.85)
        self.assertIn("AI_PAID_CAP_USD", out["label"])

    def test_the_check_alerts_from_the_router_meter_alone(self):
        path = self.meter([self.call(4.5)])
        out = W.ai_spend_status(env={}, now=NOW, root=self.empty_root(), router_usage_path=path)
        self.assertGreaterEqual(out["fraction"], W.AI_SPEND_WARN)

    def test_no_meter_and_no_analyst_store_is_none(self):
        self.assertIsNone(W.ai_spend_status(env={}, now=NOW, root=self.empty_root(), router_usage_path=NO_METER))

    def test_a_broken_meter_does_not_take_the_check_down(self):
        with mock.patch.object(W, "router_spend_status", side_effect=RuntimeError("boom")):
            self.assertIsNone(W.ai_spend_status(env={}, now=NOW, root=self.empty_root(), router_usage_path=NO_METER))


# ---------------------------------------------------------------------------
# the GitHub budget and cache
# ---------------------------------------------------------------------------

class Budget(unittest.TestCase):
    def test_a_healthy_tick_costs_six_requests_and_six_ticks_an_hour_stay_under_sixty(self):
        rig = Rig(self)
        rig.tick()
        self.assertEqual(len(rig.gh.api_requests()), 6)
        for _ in range(5):
            rig.tick(minutes=10)
        self.assertEqual(len(rig.gh.api_requests()), 36)
        self.assertLessEqual(len(rig.gh.api_requests()) + 6, W.GITHUB_BUDGET_PER_HOUR,
                             "room for one restart's refetch inside the same hour")

    def test_a_repeat_inside_the_ttl_is_served_from_cache_and_after_it_an_etag_makes_it_a_304(self):
        rig = Rig(self)
        client = rig.dog.client
        client.get("/repos/x/y/commits", {"per_page": 1})
        client.get("/repos/x/y/commits", {"per_page": 1})
        self.assertEqual(len(rig.gh.api_requests()), 1)
        rig.gh.commits = [commit(HEAD, ago(minutes=1))]
        first = client.get("/repos/x/y/commits", {"per_page": 2})
        etag = rig.gh.replies[-1].headers["etag"]
        rig.clock.advance(seconds=W.RUNS_TTL_S + 1)
        again = client.get("/repos/x/y/commits", {"per_page": 2})
        self.assertEqual(len(rig.gh.api_requests()), 3)
        self.assertEqual(rig.gh.api_requests()[-1][1].get("If-None-Match"), etag)
        self.assertEqual(rig.gh.replies[-1].status, 304, "unchanged: GitHub answers 304, which costs it nothing")
        self.assertEqual(again, first)
        self.assertEqual(again[0]["sha"], HEAD, "a 304 returns the cached body")

    def test_the_budget_is_a_hard_stop_and_a_check_that_hits_it_is_unknown_not_ok(self):
        rig = Rig(self, env={"WATCHDOG_GITHUB_BUDGET": "3"})
        rig.restart()
        rig.tick()
        self.assertEqual(len(rig.gh.api_requests()), 3)
        states = [c["state"] for c in rig.store.load()["checks"].values()]
        self.assertIn("unknown", states)
        self.assertNotIn("alert", states, "running out of budget must never read as a problem OR as all clear")
        rig.tick(minutes=10)
        self.assertEqual(len(rig.gh.api_requests()), 3, "no request once the hour's budget is spent")
        rig.tick(minutes=55)
        self.assertGreater(len(rig.gh.api_requests()), 3, "the window slides")

    def test_the_count_survives_a_restart(self):
        rig = Rig(self, env={"WATCHDOG_GITHUB_BUDGET": "8"})
        rig.restart()
        rig.tick()
        self.assertEqual(len(rig.gh.api_requests()), 6)
        rig.restart()
        rig.tick(minutes=10)
        self.assertEqual(len(rig.gh.api_requests()), 8, "only 2 requests were left in the hour, whatever restarted")

    def test_github_saying_few_requests_remain_pauses_us_until_its_reset(self):
        rig = Rig(self)
        reset = (NOW + timedelta(minutes=30)).timestamp()
        rig.gh.extra_headers = {"x-ratelimit-remaining": "3", "x-ratelimit-reset": str(int(reset))}
        rig.tick()
        first = len(rig.gh.api_requests())
        self.assertLess(first, 6)
        rig.gh.extra_headers = {}
        rig.tick(minutes=10)
        self.assertEqual(len(rig.gh.api_requests()), first)
        self.assertIsNotNone(rig.status()["github"]["blocked_until"])
        rig.tick(minutes=25)
        self.assertGreater(len(rig.gh.api_requests()), first)

    def test_a_403_is_a_pause_not_a_crash(self):
        rig = Rig(self)
        rig.gh.status = 403
        rig.tick()
        self.assertEqual(len(rig.gh.api_requests()), 1, "after one refusal the rest wait")
        self.assertEqual(rig.check("deploy_stuck"), "unknown")
        self.assertIn("rate-limiting", rig.store.load()["checks"]["deploy_stuck"]["summary"])
        self.assertIn("no GITHUB_TOKEN", rig.store.load()["checks"]["deploy_stuck"]["summary"])

    def test_old_cache_covers_a_blip_for_an_hour_and_not_longer(self):
        rig = Rig(self)
        rig.tick()
        rig.gh.down = True
        rig.tick(minutes=10)
        self.assertEqual(rig.check("deploy_stuck"), "ok", "a 10 minute blip is covered by the last answer")
        rig.tick(minutes=55)
        self.assertEqual(rig.check("deploy_stuck"), "unknown", "an hour-old answer is no longer a fact")

    def test_the_token_is_sent_to_github_and_appears_nowhere_we_write(self):
        rig = Rig(self, env={"GITHUB_TOKEN": SECRET})
        rig.restart()
        rig.gh.deploy_runs.insert(0, run(101, "in_progress", created=ago(minutes=34), started=ago(minutes=34)))
        rig.gh.tests_runs = [run(811, "completed", "failure")]
        rig.tick()
        for _url, headers in rig.gh.api_requests():
            self.assertEqual(headers["Authorization"], f"Bearer {SECRET}")
        written = rig.store.path.read_text(encoding="utf-8")
        blob = json.dumps([written, rig.status(), rig.feed(), A.render_feed(A.collect(None, [], now=NOW, extra=rig.feed()))],
                          default=str)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("SECRETTOKEN", blob)
        self.assertTrue(rig.status()["github"]["token_present"])

    def test_requests_name_the_repo_branch_and_ask_for_json(self):
        rig = Rig(self)
        rig.tick()
        for url, headers in rig.gh.api_requests():
            self.assertTrue(url.startswith(f"https://api.github.com/repos/{W.REPO}/"), url)
            self.assertEqual(headers["Accept"], "application/vnd.github+json")
            self.assertTrue(headers["User-Agent"])
            self.assertNotIn("Authorization", headers)


# ---------------------------------------------------------------------------
# the watchdog watching itself, and surviving
# ---------------------------------------------------------------------------

class Resilience(unittest.TestCase):
    def test_a_watchdog_that_cannot_see_github_for_ninety_minutes_says_so_and_clears_when_it_can(self):
        rig = Rig(self)
        rig.gh.down = True
        for _ in range(8):                          # 0, 10, ... 70 min: still inside the tolerance
            rig.tick(minutes=10)
        self.assertEqual(rig.incidents(), [])
        self.assertEqual(rig.check("github_reach"), "unknown")
        for _ in range(3):
            rig.tick(minutes=10)                    # 100 min since the first blind tick
        (inc,) = rig.incidents()
        self.assertEqual(inc["kind"], "watchdog_blind")
        self.assertIn("An empty alert feed does not mean all is well", inc["what"])
        self.assertIn("GITHUB_TOKEN", inc["fix"])
        rig.gh.down = False
        rig.tick(minutes=10)
        self.assertEqual(rig.incidents(), [])
        self.assertIn("All clear: GitHub is answering", rig.feed()[0]["description"])

    def test_one_check_crashing_does_not_stop_the_others_or_the_tick(self):
        rig = Rig(self)
        rig.dog.check_ci = lambda now: 1 / 0
        rig.gh.capture_success = [run(700, updated=ago(hours=5))]
        with self.assertLogs("linehound.ops.watchdog", "ERROR"):
            state = rig.tick()
        self.assertEqual(state["checks"]["ci_tests"]["state"], "error")
        self.assertIn("ZeroDivisionError", state["checks"]["ci_tests"]["summary"])
        self.assertEqual([i["kind"] for i in rig.incidents()], ["capture_stalled"])

    def test_a_corrupt_state_file_starts_over_instead_of_crashing(self):
        rig = Rig(self)
        rig.store.path.write_text("{ not json", encoding="utf-8")
        rig.restart()
        rig.tick()
        self.assertEqual(rig.store.load()["checks"]["capture"]["state"], "ok")
        self.assertEqual(W.feed_alerts(NOW, env=rig.env, store=W.StateStore(rig.tmp / "missing.json")), [])

    def test_the_state_is_written_atomically_and_only_where_told(self):
        rig = Rig(self)
        rig.tick()
        self.assertEqual(sorted(p.name for p in rig.tmp.iterdir()), ["state.json"])

    def test_the_default_state_path_sits_beside_the_app_database(self):
        with mock.patch.dict(os.environ, {"APP_DB_PATH": "/tmp/vol/app.db"}, clear=False):
            self.assertEqual(W.default_state_path({}).name, "watchdog_state.json")
            self.assertEqual(W.default_state_path({}).parent.name, "vol")
        self.assertEqual(W.default_state_path({"WATCHDOG_STATE_PATH": "/x/y.json"}), Path("/x/y.json"))


# ---------------------------------------------------------------------------
# the kill switch
# ---------------------------------------------------------------------------

class KillSwitch(unittest.TestCase):
    def test_only_the_word_on_turns_it_on(self):
        self.assertTrue(W.enabled({"WATCHDOG": "on"}))
        self.assertTrue(W.enabled({"WATCHDOG": " ON "}))
        for value in ("off", "", "true", "1", "yes", "0", "On!"):
            self.assertFalse(W.enabled({"WATCHDOG": value}), value)
        self.assertFalse(W.enabled({}))

    def test_off_or_unset_starts_no_thread(self):
        for env in ({"WATCHDOG": "off"}, {}):
            ticks = []
            self.assertIsNone(W.start_loop(env=env, do_tick=lambda: ticks.append(1)))
            self.assertEqual(ticks, [])

    def test_on_starts_one_daemon_thread_that_ticks_until_stopped(self):
        stop, seen = threading.Event(), []
        hit = threading.Event()

        def tick():
            seen.append(1)
            hit.set()
        thread = W.start_loop(env={"WATCHDOG": "on"}, stop_event=stop, tick_s=0.01, do_tick=tick, ready=lambda: True)
        self.assertTrue(thread.daemon)
        self.assertEqual(thread.name, "watchdog")
        self.assertTrue(hit.wait(5))
        stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_the_loop_waits_for_the_first_warm_up_pass(self):
        stop, seen = threading.Event(), []
        gate = {"ready": False}
        thread = W.start_loop(env={"WATCHDOG": "on"}, stop_event=stop, tick_s=0.01, do_tick=lambda: seen.append(1),
                              ready=lambda: gate["ready"])
        stop.wait(0.3)
        self.assertEqual(seen, [], "no tick before the warm-up finishes")
        stop.set()
        thread.join(10)

    def test_a_tick_that_raises_cannot_kill_the_loop(self):
        rig = Rig(self)
        rig.dog.run_once = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertLogs("linehound.ops.watchdog", "ERROR"):
            W.tick_safely(rig.dog)                  # must not raise
        rig.dog.run_once.assert_called_once()

    def test_off_removes_the_watchdogs_items_from_the_feed_even_with_incidents_on_disk(self):
        rig = Rig(self)
        rig.gh.deploy_runs.insert(0, run(101, "in_progress", created=ago(minutes=34), started=ago(minutes=34)))
        rig.tick()
        self.assertEqual(len(rig.feed()), 1)
        off = dict(rig.env, WATCHDOG="off")
        self.assertEqual(W.feed_alerts(rig.clock.now, env=off, store=rig.store), [])
        status = W.status(env=off, store=rig.store, now=rig.clock.now)
        self.assertFalse(status["enabled"])
        self.assertEqual(status["switch"], "off")
        self.assertIn("WATCHDOG=on", status["note"])


# ---------------------------------------------------------------------------
# which commit production runs
# ---------------------------------------------------------------------------

def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Version(unittest.TestCase):
    def meta(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        return root

    def test_a_real_git_layout_a_flattened_copy_packed_refs_a_detached_head_and_fetch_head_all_resolve(self):
        sha, other = "1" * 40, "2" * 40
        branch = "ref: refs/heads/claude/work\n"
        cases = {
            "real .git loose ref": {"HEAD": branch, "refs/heads/claude/work": sha + "\n"},
            "flattened copy (what the Dockerfile makes)": {"HEAD": branch, "heads/claude/work": sha + "\n"},
            "remote-tracking ref only": {"HEAD": branch, "remotes/origin/claude/work": sha + "\n"},
            "packed refs": {"HEAD": branch, "packed-refs": f"# pack-refs\n{other} refs/heads/other\n{sha} refs/heads/claude/work\n"},
            "detached head": {"HEAD": sha + "\n"},
            "fetch head": {"HEAD": branch, "FETCH_HEAD": f"{other}\tnot-for-merge\tbranch 'x' of github\n{sha}\t\tbranch 'claude/work' of github\n"},
        }
        for name, files in cases.items():
            with self.subTest(name):
                self.assertEqual(W.sha_from_gitmeta(self.meta(files)), sha)

    def test_nothing_that_is_not_a_full_commit_id_is_believed(self):
        for files in ({}, {"HEAD": "ref: refs/heads/x\n"}, {"HEAD": "ref: refs/heads/x\n", "refs/heads/x": "abc123\n"},
                      {"HEAD": "not a ref\n"}, {"HEAD": "ref: refs/heads/x\n", "FETCH_HEAD": "zzzz\t\tbranch\n"}):
            with self.subTest(files):
                self.assertIsNone(W.sha_from_gitmeta(self.meta(files)))
        self.assertIsNone(W.sha_from_gitmeta(Path("/definitely/not/here")))

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_it_reads_what_a_real_checkout_leaves_behind_as_the_dockerfile_copies_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            git("init", "-q", "-b", "claude/work", cwd=repo)
            git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "one", cwd=repo)
            want = git("rev-parse", "HEAD", cwd=repo)
            copy = Path(tmp) / "gitmeta"
            copy.mkdir()
            shutil.copy(repo / ".git" / "HEAD", copy / "HEAD")
            shutil.copytree(repo / ".git" / "refs", copy, dirs_exist_ok=True)       # COPY of a dir copies its CONTENTS
            self.assertEqual(W.sha_from_gitmeta(copy), want)
            out = Path(tmp) / "VERSION"
            self.assertEqual(W.write_version(copy, out), want)
            self.assertEqual(out.read_text(encoding="utf-8"), want + "\n")

    def test_write_version_writes_nothing_when_unknown_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "VERSION"
            self.assertIsNone(W.write_version(Path(tmp) / "missing", out))
            self.assertFalse(out.exists(), "an unknown commit is no file, not a made-up one")
            good = self.meta({"HEAD": "3" * 40 + "\n"})
            self.assertIsNone(W.write_version(good, Path(tmp) / "no" / "such" / "dir" / "VERSION"))

    def test_the_cli_always_exits_zero_so_it_can_never_fail_the_image_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(W.main(["write-version", "--gitmeta", str(Path(tmp) / "nope"), "--out", str(Path(tmp) / "V")]), 0)
            good = self.meta({"HEAD": "4" * 40 + "\n"})
            self.assertEqual(W.main(["write-version", "--gitmeta", str(good), "--out", str(Path(tmp) / "V")]), 0)
            self.assertEqual((Path(tmp) / "V").read_text(encoding="utf-8").strip(), "4" * 40)

    def test_the_running_commit_comes_from_the_setting_then_the_file_then_nowhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(W.deployed_version({}, root))
            (root / "VERSION").write_text("5" * 40 + "\n", encoding="utf-8")
            got = W.deployed_version({}, root)
            self.assertEqual(got["sha"], "5" * 40)
            self.assertIn("VERSION file", got["source"])
            self.assertEqual(W.deployed_version({"GIT_SHA": "ABCDEF1234567"}, root)["sha"], "abcdef1234567")
            self.assertEqual(W.deployed_version({"GIT_SHA": "not-a-sha"}, root)["sha"], "5" * 40)
            (root / "VERSION").write_text("garbage", encoding="utf-8")
            self.assertIsNone(W.deployed_version({}, root))


class ImageBuild(unittest.TestCase):
    """The build recipe is text no test can run (no Docker in CI), so pin the properties that keep it safe."""
    ROOT = Path(__file__).resolve().parent.parent

    def test_dockerignore_admits_only_the_four_commit_naming_git_entries_and_never_the_config(self):
        lines = [ln.strip() for ln in (self.ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]
        git_rules = [ln for ln in lines if ln.lstrip("!").startswith(".git")]
        self.assertEqual(git_rules, [".git/*", "!.git/HEAD", "!.git/FETCH_HEAD", "!.git/packed-refs", "!.git/refs/"])
        self.assertFalse([ln for ln in git_rules if "config" in ln or "hooks" in ln or "index" in ln])

    def test_the_dockerfile_copies_with_wildcards_only_and_cannot_fail_the_build(self):
        text = (self.ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        copy = next(ln for ln in text.splitlines() if ln.startswith("COPY deploy/fly.production.toml"))
        sources = copy.split()[1:-1]
        self.assertEqual(sources[0], "deploy/fly.production.toml", "a source that always exists comes first")
        self.assertTrue(all("*" in s for s in sources[1:]), "every .git source is a wildcard: absent means nothing copied")
        self.assertTrue((self.ROOT / sources[0]).is_file())
        i = text.index("RUN python -m src.ops.watchdog write-version")
        recipe = text[i:text.index("\n\n", i)]
        self.assertIn("|| echo", recipe)
        self.assertIn("rm -rf /app/.gitmeta", recipe)
        self.assertLess(text.index("display_refresh --max-seconds"), i, "after the slow refresh layer, so it never invalidates it")
        self.assertLess(i, text.index("useradd"), "before the chown that hands /app to the app user")

    def test_the_module_the_build_runs_imports_with_only_the_standard_library(self):
        result = subprocess.run(
            [sys.executable, "-S", "-c", f"import sys; sys.path.insert(0, {str(self.ROOT)!r}); "
             "import src.ops.watchdog; print('OK')"], capture_output=True, text=True, cwd=self.ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_turns_it_on_and_staging_does_not(self):
        prod = (self.ROOT / "deploy" / "fly.production.toml").read_text(encoding="utf-8")
        staging = (self.ROOT / "deploy" / "fly.staging.toml").read_text(encoding="utf-8")
        self.assertIn('WATCHDOG = "on"', prod)
        self.assertNotIn("WATCHDOG", staging)


# ---------------------------------------------------------------------------
# into the alerts feed
# ---------------------------------------------------------------------------

class IntoTheFeed(unittest.TestCase):
    def stuck_rig(self):
        rig = Rig(self)
        rig.gh.deploy_runs.insert(0, run(101, "in_progress", created=ago(minutes=34), started=ago(minutes=34)))
        rig.tick()
        return rig

    def test_the_items_are_valid_rss_with_a_stable_guid_the_run_as_link_and_the_raised_time_as_date(self):
        rig = self.stuck_rig()
        healthy = {"status": "ok", "reasons": [], "odds": {}, "data_freshness": {"stores": {}}}
        alerts = A.collect(healthy, [], now=NOW, extra=rig.feed())
        xml = A.render_feed(alerts)
        (item,) = ET.fromstring(xml).findall("./channel/item")
        guid = item.find("guid")
        self.assertEqual(guid.get("isPermaLink"), "false")
        self.assertTrue(guid.text.startswith("watchdog:deploy_stuck:101:"))
        self.assertEqual(item.find("link").text, f"{REPO_URL}/actions/runs/101")
        self.assertIn("click Cancel workflow; Claude will redeploy", item.find("description").text)
        self.assertEqual(A.render_feed(A.collect(healthy, [], now=NOW, extra=rig.feed())), xml, "two polls are byte-identical")

    def test_watchdog_items_sit_beside_the_daily_health_items_without_touching_them(self):
        rig = self.stuck_rig()
        odds = {"odds_multibook": {"present": True, "rows": 10, "status": "ok", "newest_row_age_seconds": 4.2 * 3600,
                                   "newest_row_utc": "2026-10-20T10:48:00+00:00"}}
        health = {"status": "ok", "reasons": [], "odds": odds, "data_freshness": {"core_stale": [], "stale": [], "stores": {}}}
        alerts = A.collect(health, [], now=NOW, extra=rig.feed())
        guids = [a["guid"] for a in alerts]
        self.assertTrue(any(g.startswith("alert:odds_stale:2026-10-20") for g in guids))
        self.assertTrue(any(g.startswith("watchdog:deploy_stuck:") for g in guids))
        self.assertEqual(len(guids), len(set(guids)))

    def test_the_digest_lists_open_watchdog_incidents_and_never_an_all_clear(self):
        rig = self.stuck_rig()
        healthy = {"status": "ok", "reasons": [], "odds": {}, "data_freshness": {"stores": {}}}
        d = A.digest(healthy, [], now=NOW, extra=W.feed_alerts(NOW, env=rig.env, store=rig.store, include_resolved=False))
        self.assertFalse(d["all_clear"])
        self.assertIn("Deploy to production is stuck", d["items"][0]["title"])
        rig.gh.deploy_runs.pop(0)
        rig.tick(minutes=10)
        d = A.digest(healthy, [], now=NOW, extra=W.feed_alerts(NOW, env=rig.env, store=rig.store, include_resolved=False))
        self.assertTrue(d["all_clear"], "a resolved incident is a feed message, not something left to do")
        self.assertTrue(any("CI" in line for line in d["not_checked"]))

    def test_with_no_extra_the_feed_is_exactly_what_it_was(self):
        healthy = {"status": "ok", "reasons": [], "odds": {}, "data_freshness": {"stores": {}}}
        self.assertEqual(A.collect(healthy, [], now=NOW), A.collect(healthy, [], now=NOW, extra=None))
        self.assertEqual(A.collect(healthy, [], now=NOW, extra=[]), [])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Routes(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for name in ("WATCHDOG", "WATCHDOG_STATE_PATH", "APP_ADMIN_TOKEN", "GITHUB_TOKEN"):
            os.environ.pop(name, None)

    def rig_with_incident(self):
        rig = Rig(self)
        rig.gh.deploy_runs.insert(0, run(101, "in_progress", created=ago(minutes=34), started=ago(minutes=34)))
        rig.tick()
        os.environ["WATCHDOG"] = "on"
        os.environ["WATCHDOG_STATE_PATH"] = str(rig.store.path)
        return rig

    def client(self, *routers):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        for r in routers:
            app.include_router(r)
        return TestClient(app)

    def feed(self, client):
        healthy = {"status": "ok", "reasons": [], "odds": {}, "forward_captures": {}, "data_freshness": {"stores": {}}}
        from api import health as api_health
        with mock.patch("src.appstate.apphealth.report", return_value=healthy), \
                mock.patch.object(A, "pause_facts", return_value=[]), \
                mock.patch.object(api_health, "process_started_utc",
                                  return_value=iso(datetime.now(timezone.utc) - timedelta(minutes=5))):
            return client.get("/feeds/alerts.rss")

    def test_the_alerts_feed_route_carries_the_open_incident_when_on_and_nothing_when_off(self):
        from api.feeds import router
        rig = self.rig_with_incident()
        r = self.feed(self.client(router))
        self.assertEqual(r.status_code, 200)
        items = ET.fromstring(r.text).findall("./channel/item")
        self.assertEqual(len(items), 1)
        self.assertIn("Deploy to production is stuck", items[0].find("title").text)
        os.environ["WATCHDOG"] = "off"
        self.assertEqual(ET.fromstring(self.feed(self.client(router)).text).findall("./channel/item"), [])
        del rig

    def test_the_admin_view_is_gated_like_the_rest_of_admin(self):
        from api.admin import router
        c = self.client(router)
        self.assertEqual(c.get("/admin/watchdog").status_code, 404, "no APP_ADMIN_TOKEN: the route does not exist")
        os.environ["APP_ADMIN_TOKEN"] = "right-token"
        self.assertEqual(c.get("/admin/watchdog").status_code, 401)
        self.assertEqual(c.get("/admin/watchdog", headers={"X-Admin-Token": "nope"}).status_code, 401)

    def test_the_admin_view_shows_the_last_check_each_check_and_the_open_incidents_and_no_secret(self):
        from api.admin import router
        rig = self.rig_with_incident()
        os.environ["APP_ADMIN_TOKEN"] = "right-token"
        os.environ["GITHUB_TOKEN"] = SECRET
        r = self.client(router).get("/admin/watchdog", headers={"X-Admin-Token": "right-token"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["last_check_utc"], iso(NOW))
        self.assertEqual(set(body["checks"]), {"deploy_stuck", "tests_stuck", "capture_run", "slate_stuck", "ci_tests",
                                               "prod_behind", "capture", "health", "ai_spend", "github_reach"})
        self.assertEqual(body["checks"]["deploy_stuck"]["state"], "alert")
        self.assertEqual(body["open_incidents"][0]["kind"], "deploy_stuck")
        self.assertIn("click Cancel workflow", body["open_incidents"][0]["fix"])
        self.assertTrue(body["github"]["token_present"])
        self.assertNotIn("SECRETTOKEN", r.text)
        for key in ("production_commit", "recently_resolved", "limits", "interval_seconds"):
            self.assertIn(key, body)
        del rig

    def test_the_health_digest_route_includes_the_open_incident(self):
        from api.admin import router
        self.rig_with_incident()
        os.environ["APP_ADMIN_TOKEN"] = "right-token"
        healthy = {"status": "ok", "reasons": [], "odds": {}, "forward_captures": {}, "data_freshness": {"stores": {}}}
        with mock.patch("src.appstate.apphealth.report", return_value=healthy), \
                mock.patch.object(A, "pause_facts", return_value=[]):
            body = self.client(router).get("/admin/health-digest", headers={"X-Admin-Token": "right-token"}).json()
        self.assertFalse(body["all_clear"])
        self.assertTrue(any(i["kind"] == "watchdog_deploy_stuck" for i in body["items"]))

    def test_the_real_app_starts_the_loop_at_boot_with_the_process_start_time(self):
        """Something has to CALL it: the app's startup hook hands start_loop the warm-up gate and the start time."""
        import api.app as app_module
        hooks = [h for h in app_module.app.router.on_startup if h.__name__ == "_start_watchdog"]
        self.assertEqual(len(hooks), 1)
        with mock.patch.object(W, "start_loop") as start:
            hooks[0]()
        kwargs = start.call_args.kwargs
        from api import health as api_health
        self.assertEqual(kwargs["started_utc"], api_health.process_started_utc)
        self.assertTrue(callable(kwargs["ready"]))

    def test_without_the_switch_the_real_hook_starts_nothing(self):
        import api.app as app_module
        hook = next(h for h in app_module.app.router.on_startup if h.__name__ == "_start_watchdog")
        with mock.patch.object(threading.Thread, "start") as start:
            hook()
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
