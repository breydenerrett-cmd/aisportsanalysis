"""www.linehound.app sends every request to linehound.app; nothing else moves.

Two addresses for one site split what the browser keys by origin: the stored
first-touch source and the visitor id. A lead who arrived on one host and
signed up on the other would count twice, once unattributed.
"""

import unittest

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:                      # Linux CI runs without api/requirements.txt
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class WwwGoesToTheApex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.client = TestClient(app, follow_redirects=False)

    def _get(self, path, host):
        return self.client.get(path, headers={"host": host})

    def test_www_redirects_permanently_keeping_path_and_query(self):
        response = self._get("/web/index.html?utm_source=l012-unit-circle&utm_campaign=batch_01",
                             "www.linehound.app")
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers["location"],
                         "https://linehound.app/web/index.html?utm_source=l012-unit-circle&utm_campaign=batch_01")

    def test_www_root_and_health_redirect_too(self):
        for path in ("/", "/health", "/card", "/admin/overview"):
            with self.subTest(path):
                response = self._get(path, "www.linehound.app")
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response.headers["location"], f"https://linehound.app{path}")

    def test_a_post_keeps_its_method(self):
        response = self.client.post("/funnel/event", json={"kind": "landing_view"},
                                    headers={"host": "www.linehound.app"})
        self.assertEqual(response.status_code, 308)      # 308, not 301/302: the method survives

    def test_every_other_host_is_served_as_before(self):
        for host in ("linehound.app", "linehound-prod.fly.dev", "linehound-staging.fly.dev",
                     "localhost:8000", "testserver", "172.19.0.2:8000", "www"):
            with self.subTest(host):
                response = self._get("/", host)
                self.assertEqual(response.status_code, 307)
                self.assertEqual(response.headers["location"], "/web/landing.html")

    def test_the_redirect_cannot_be_pointed_at_another_site(self):
        # The target is the request's own host minus "www."; a path cannot
        # change which site it names.
        response = self._get("//evil.example/x", "www.linehound.app")
        self.assertEqual(response.status_code, 308)
        self.assertTrue(response.headers["location"].startswith("https://linehound.app/"))


if __name__ == "__main__":
    unittest.main()
