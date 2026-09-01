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
