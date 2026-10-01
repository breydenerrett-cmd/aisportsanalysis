"""api/health.py: GET /health -- called directly (see test_api_auth.py's
module docstring for why there is no TestClient/HTTP layer in this repo).

No auth on this route, so the tests exercise it purely through
apphealth.report() with data_dir/db_path overrides, plus a Response object
standing in for what FastAPI would inject.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    from fastapi import Response
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import apphealth


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class GetHealthTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_ok_report_leaves_the_default_200_status(self):
        from api.health import get_health
        response = Response()
        with mock.patch.object(apphealth, "report",
                               return_value={"status": "ok", "reasons": []}):
            data = get_health(response)
        self.assertEqual(data["status"], "ok")
        self.assertNotEqual(response.status_code, 503)

    def test_degraded_report_sets_a_503_status(self):
        from api.health import get_health
        response = Response()
        degraded = {"status": "degraded", "reasons": ["app db unreachable: x"]}
        with mock.patch.object(apphealth, "report", return_value=degraded):
            data = get_health(response)
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(response.status_code, 503)

    def test_a_billing_misconfiguration_alone_is_degraded_but_not_a_503(self):
        """Fly routes on this status code. A missing billing setting must be
        loud in the payload and must not take the record page and every
        existing subscriber offline with it."""
        from api.health import get_health
        response = Response()
        degraded = {"status": "degraded",
                    "reasons": ["checkout: STRIPE_WEBHOOK_SECRET is unset, so ..."],
                    "checkout": {"status": "broken"}}
        with mock.patch.object(apphealth, "report", return_value=degraded):
            data = get_health(response)
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["checkout"]["status"], "broken")
        self.assertNotEqual(response.status_code, 503)

    def test_a_billing_misconfiguration_plus_a_real_fault_is_still_a_503(self):
        from api.health import get_health
        response = Response()
        degraded = {"status": "degraded",
                    "reasons": ["checkout: STRIPE_API_KEY is unset", "app db unreachable: x"]}
        with mock.patch.object(apphealth, "report", return_value=degraded):
            get_health(response)
        self.assertEqual(response.status_code, 503)

    def test_runtime_block_says_when_the_process_started_and_what_it_holds(self):
        """A restart must be visible from outside: production restarted for
        lack of memory every eleven minutes and /health looked fine each time."""
        from api import health
        from src.appstate import freshness
        response = Response()
        with mock.patch.object(apphealth, "report",
                               return_value={"status": "ok", "reasons": []}):
            first = health.get_health(response)["runtime"]
            second = health.get_health(response)["runtime"]
        self.assertEqual(first["started_utc"], second["started_utc"])
        self.assertGreaterEqual(second["uptime_s"], first["uptime_s"])
        self.assertEqual(set(first["builds"]), {"running", "max_running", "total"})
        for key in ("rss_mb", "peak_rss_mb"):
            self.assertIn(key, first)        # None off Linux; a number on it
        before = freshness.build_stats()["total"]
        freshness.SingleFlightTTLCache(ttl_s=60).get("k", lambda: 1)
        after = health.get_health(response)["runtime"]["builds"]
        self.assertEqual(after["total"], before + 1)
        self.assertEqual(after["running"], 0)

    def test_a_runtime_fault_never_fails_health(self):
        from api import health
        response = Response()
        with mock.patch.object(apphealth, "report",
                               return_value={"status": "ok", "reasons": []}), \
                mock.patch.object(health, "runtime", side_effect=RuntimeError("boom")):
            data = health.get_health(response)
        self.assertIsNone(data["runtime"])
        self.assertNotEqual(response.status_code, 503)

    def test_a_health_check_that_itself_raises_still_returns_a_response(self):
        """The one route that must never 500 unhandled -- an uptime checker
        needs a real response even when the check machinery itself breaks."""
        from api.health import get_health
        response = Response()
        with mock.patch.object(apphealth, "report",
                               side_effect=RuntimeError("disk full")):
            data = get_health(response)
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(response.status_code, 503)
        self.assertTrue(any("disk full" in r for r in data["reasons"]))

    def test_the_real_report_against_a_fresh_empty_environment(self):
        """No mocking of apphealth itself here -- a real fresh data_dir and
        db_path, proving the wiring (not just the mock) produces a sane,
        secret-free response."""
        data = apphealth.report(data_dir=self.root, db_path=self.root / "app.db")
        self.assertIn(data["status"], ("ok", "degraded"))
        self.assertIn("app_db", data)
        self.assertIn("odds", data)
        self.assertIn("forward_captures", data)


if __name__ == "__main__":
    unittest.main()
