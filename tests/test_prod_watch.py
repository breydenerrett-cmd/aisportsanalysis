"""The production watch says OK or names the breach, from observations alone."""
import unittest
from datetime import datetime, timezone

from scripts import prod_watch as pw

NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
STARTED = "2026-10-02T00:06:01+00:00"


def health(**over):
    base = {"status": "ok",
            "runtime": {"started_utc": STARTED, "uptime_s": 10000, "rss_mb": 390.0,
                        "peak_rss_mb": 588.9, "builds": {"max_running": 1}},
            "odds": {"odds_multibook": {"newest_row_age_seconds": 1800.0}},
            "checkout": {"status": "off"}}
    base.update(over)
    return base


def runs(**over):
    base = {"tests.yml": [{"status": "completed", "conclusion": "success"}],
            "forward-capture.yml": [{"conclusion": "success", "updatedAt": "2026-10-02T02:32:03Z"}],
            "daily-loop.yml": [{"status": "completed", "conclusion": "success"}],
            "deploy-prod.yml": [{"conclusion": "success", "updatedAt": "2026-10-02T00:08:06Z"}]}
    base.update(over)
    return base


class Evaluate(unittest.TestCase):
    def _breaches(self, **kwargs):
        args = {"health_status": 200, "health": health(), "card_status": 401, "runs": runs(),
                "previous": {"started_utc": STARTED, "restarts_seen": 0}, "now": NOW}
        args.update(kwargs)
        _, breaches, state = pw.evaluate(**args)
        return breaches, state

    def test_a_healthy_site_has_no_breach(self):
        breaches, state = self._breaches()
        self.assertEqual(breaches, [])
        self.assertEqual(state["restarts_seen"], 0)

    def test_a_restart_with_no_deploy_near_it_is_a_breach_and_is_counted(self):
        breaches, state = self._breaches(previous={"started_utc": "2026-10-01T21:41:05+00:00",
                                                   "restarts_seen": 0},
                                         runs=runs(**{"deploy-prod.yml": []}))
        self.assertTrue(any("restarted" in b for b in breaches), breaches)
        self.assertEqual(state["restarts_seen"], 1)

    def test_a_restart_caused_by_a_deploy_is_not(self):
        breaches, state = self._breaches(previous={"started_utc": "2026-10-01T21:41:05+00:00",
                                                   "restarts_seen": 0})
        self.assertEqual(breaches, [])
        self.assertEqual(state["restarts_seen"], 0)

    def test_each_threshold_names_its_own_breach(self):
        cases = {
            "memory": dict(health=health(runtime={"started_utc": STARTED, "peak_rss_mb": 900.0,
                                                  "builds": {"max_running": 1}})),
            "builds at once": dict(health=health(runtime={"started_utc": STARTED, "peak_rss_mb": 500.0,
                                                          "builds": {"max_running": 3}})),
            "odds": dict(health=health(odds={"odds_multibook": {"newest_row_age_seconds": 4 * 3600}})),
            "/card": dict(card_status=200),
            "billing": dict(health=health(checkout={"status": "ok"})),
            "CI": dict(runs=runs(**{"tests.yml": [{"status": "completed", "conclusion": "failure"}]})),
            "capture": dict(runs=runs(**{"forward-capture.yml": [
                {"conclusion": "success", "updatedAt": "2026-10-01T23:00:00Z"}]})),
            "daily loop": dict(runs=runs(**{"daily-loop.yml": [
                {"status": "completed", "conclusion": "failure"}]})),
            "/health": dict(health_status=None, health=None),
        }
        for word, change in cases.items():
            with self.subTest(word):
                breaches, _ = self._breaches(**change)
                self.assertTrue(any(word in b for b in breaches), (word, breaches))

    def test_a_run_still_in_progress_is_not_read_as_the_ci_result(self):
        breaches, _ = self._breaches(runs=runs(**{"tests.yml": [
            {"status": "in_progress", "conclusion": None},
            {"status": "completed", "conclusion": "success"}]}))
        self.assertEqual(breaches, [])

    def test_the_first_look_has_nothing_to_compare_and_is_not_a_restart(self):
        breaches, state = self._breaches(previous=None)
        self.assertEqual(breaches, [])
        self.assertEqual(state["restarts_seen"], 0)


if __name__ == "__main__":
    unittest.main()
