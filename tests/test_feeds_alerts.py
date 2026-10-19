"""The operator alert feed: GET /feeds/alerts.rss and the alerts behind it (src/appstate/alert_feed.py).

Core tests need no FastAPI (Linux CI has none); the route tests skip cleanly where it is missing.
"""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import alert_feed as A
from src.hounds.learning import ledger as L
from tests import _learning_fixtures as LF

NOW = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)


def healthy(**over) -> dict:
    """What apphealth.report() returns on a healthy site (trimmed to the fields the alerts read)."""
    base = {"status": "ok", "reasons": [],
            "odds": {"odds_multibook": {"present": True, "rows": 10, "status": "ok",
                                        "newest_row_age_seconds": 1800.0,
                                        "newest_row_utc": "2026-10-18T21:30:00+00:00"}},
            "data_freshness": {"core_stale": [], "stale": [], "stores": {}}}
    base.update(over)
    return base


def items_of(xml_text):
    return ET.fromstring(xml_text).findall("./channel/item")


class WhenNothingIsWrong(unittest.TestCase):
    def test_a_healthy_site_has_no_alerts_and_the_feed_is_valid_and_empty(self):
        alerts = A.collect(healthy(), [], now=NOW)
        self.assertEqual(alerts, [])
        xml = A.render_feed(alerts)
        root = ET.fromstring(xml)                       # parses
        self.assertEqual(root.tag, "rss")
        self.assertEqual(root.get("version"), "2.0")
        self.assertEqual(items_of(xml), [])
        self.assertIsNotNone(root.find("./channel/title"))


class Alerts(unittest.TestCase):
    def test_old_odds_say_how_old_in_plain_words_and_date_the_item_when_the_limit_was_crossed(self):
        odds = {"odds_multibook": {"present": True, "rows": 10, "status": "ok",
                                   "newest_row_age_seconds": 4.2 * 3600,
                                   "newest_row_utc": "2026-10-18T17:48:00+00:00"}}
        alerts = A.collect(healthy(odds=odds), [], now=NOW)
        self.assertEqual([a["title"] for a in alerts], ["Odds are 4 hours old"])
        self.assertEqual(alerts[0]["pub"], datetime(2026, 10, 18, 20, 48, tzinfo=timezone.utc))
        self.assertIn("forward-capture", alerts[0]["description"])

    def test_odds_just_inside_the_limit_do_not_alert(self):
        odds = {"odds_multibook": {"present": True, "status": "ok", "newest_row_age_seconds": 3 * 3600.0}}
        self.assertEqual(A.collect(healthy(odds=odds), [], now=NOW), [])

    def test_a_missing_odds_store_is_an_alert_not_a_green_light(self):
        odds = {"odds_multibook": {"present": False, "status": "missing", "newest_row_age_seconds": None}}
        self.assertEqual([a["kind"] for a in A.collect(healthy(odds=odds), [], now=NOW)], ["odds_missing"])

    def test_health_reasons_become_alerts_one_each(self):
        reasons = ["app db unreachable: unable to open database file", "checkout: PUBLIC_BASE_URL is unset"]
        alerts = A.collect(healthy(reasons=reasons), [], now=NOW)
        self.assertEqual(sorted(a["title"] for a in alerts),
                         ["Checkout is broken", "The app database is unreachable"])

    def test_an_unreadable_odds_store_is_one_alert_not_two(self):
        odds = {"odds_multibook": {"present": True, "status": "unreadable", "newest_row_age_seconds": None}}
        alerts = A.collect(healthy(odds=odds, reasons=["odds_multibook: bad json"]), [], now=NOW)
        self.assertEqual([a["kind"] for a in alerts], ["health_odds_multibook"])

    def test_a_stale_store_behind_the_pages_alerts_by_name_one_item_each(self):
        stores = {"mlb_results": {"through": "2026-10-14", "lag_days": 4, "stale": True, "reason": "4 days behind",
                                  "tolerance_days": 1},
                  "bullpen_log": {"through": "2026-10-13", "lag_days": 5, "stale": True, "reason": "5 days behind",
                                  "tolerance_days": 1},
                  "transactions": {"through": "2026-10-15", "lag_days": 3, "stale": False, "reason": None,
                                  "tolerance_days": 3}}
        alerts = A.collect(healthy(data_freshness={"core_stale": ["mlb_results", "bullpen_log"], "stores": stores}),
                           [], now=NOW)
        self.assertEqual(sorted(a["kind"] for a in alerts), ["data_stale_bullpen_log", "data_stale_mlb_results"])
        titles = {a["kind"]: a["title"] for a in alerts}
        self.assertEqual(titles["data_stale_mlb_results"], "Match results are 4 days behind")
        self.assertTrue(all("Fix:" in a["description"] for a in alerts))

    def test_a_learning_loop_that_paused_itself_is_an_alert_dated_when_it_paused(self):
        pauses = [{"scope": "house", "reason": "trailing the random controls for 60 days",
                   "since": "2026-10-17T05:00:00Z"}]
        alerts = A.collect(healthy(), pauses, now=NOW)
        self.assertEqual(alerts[0]["title"], "The learning loop paused itself (house)")
        self.assertEqual(alerts[0]["pub"], datetime(2026, 10, 17, 5, 0, tzinfo=timezone.utc))
        self.assertIn("trailing the random controls", alerts[0]["description"])

    def test_a_health_check_that_itself_failed_is_an_alert(self):
        alerts = A.collect(None, [], now=NOW, health_error="OperationalError")
        self.assertEqual(alerts[0]["title"], "The health check itself failed")


class Stability(unittest.TestCase):
    def broken(self):
        odds = {"odds_multibook": {"present": True, "status": "ok", "newest_row_age_seconds": 5 * 3600.0,
                                   "newest_row_utc": "2026-10-18T17:00:00+00:00"}}
        return healthy(odds=odds, reasons=["checkout: broken"])

    def test_the_same_incident_has_the_same_guid_on_every_poll_of_the_day(self):
        early = A.collect(self.broken(), [], now=NOW.replace(hour=1))
        late = A.collect(self.broken(), [], now=NOW.replace(hour=23))
        self.assertEqual([a["guid"] for a in early], [a["guid"] for a in late])
        self.assertEqual(A.render_feed(early), A.render_feed(early))

    def test_the_same_incident_the_next_day_is_a_new_item(self):
        today = {a["guid"] for a in A.collect(self.broken(), [], now=NOW)}
        tomorrow = {a["guid"] for a in A.collect(self.broken(), [], now=NOW + timedelta(days=1))}
        self.assertTrue(today and tomorrow)
        self.assertFalse(today & tomorrow)
        self.assertTrue(all(g.endswith("2026-10-18") for g in today))

    def test_one_item_per_kind_per_date_even_if_two_reasons_share_a_kind(self):
        alerts = A.collect(healthy(reasons=["checkout: a", "checkout: b"]), [], now=NOW)
        self.assertEqual(len(alerts), 1)

    def test_pubdates_are_facts_about_the_incident_never_now(self):
        xml = A.render_feed(A.collect(self.broken(), [], now=NOW))
        stamps = [parsedate_to_datetime(i.findtext("pubDate")) for i in items_of(xml)]
        self.assertEqual(len(stamps), 2)
        self.assertNotIn(NOW, stamps)
        self.assertEqual(stamps, sorted(stamps, reverse=True))


class NothingSecretLeaks(unittest.TestCase):
    def test_paths_emails_and_token_like_runs_are_scrubbed_from_a_public_feed(self):
        secret = "sk_live_" + "A1b2C3d4" * 5
        reasons = [f"app db unreachable: cannot open C:\\Users\\KC\\data\\app.db for owner@example.com",
                   f"checkout: key {secret} rejected at /app/data/app.db"]
        text = A.render_feed(A.collect(healthy(reasons=reasons), [], now=NOW))
        for leak in ("C:\\Users", "owner@example.com", secret, "/app/data", "app.db"):
            self.assertNotIn(leak, text)
        self.assertIn("[path]", text)

    def test_a_long_reason_is_trimmed(self):
        alerts = A.collect(healthy(reasons=["checkout: " + "words " * 200]), [], now=NOW)
        self.assertLessEqual(len(alerts[0]["description"]), 400)


class PauseFacts(unittest.TestCase):
    def test_pause_facts_reads_the_real_pause_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            house = L.Scope.house(Path(tmp) / "h")
            user = L.Scope.user(Path(tmp) / "u")
            L.log_for(house).append(L.K_PAUSE, now=LF.utc("2026-10-17T05:00:00Z"), scope="house",
                                    reason="hit rate under the floor", wrote=[])
            with mock.patch.object(L, "default_scopes", return_value={"house": house, "user": user}), \
                    mock.patch("src.hounds.learning.pause.config_path",
                               return_value=Path(tmp) / "no_such_config.json"):
                facts = A.pause_facts()
        self.assertEqual(facts, [{"scope": "house", "reason": "hit rate under the floor",
                                  "since": "2026-10-17T05:00:00Z"}])

    def test_a_loop_that_is_running_reports_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            scopes = {"house": L.Scope.house(Path(tmp) / "h"), "user": L.Scope.user(Path(tmp) / "u")}
            with mock.patch.object(L, "default_scopes", return_value=scopes), \
                    mock.patch("src.hounds.learning.pause.config_path",
                               return_value=Path(tmp) / "no_such_config.json"):
                self.assertEqual(A.pause_facts(), [])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Route(unittest.TestCase):
    def get(self, report):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.feeds import router
        app = FastAPI()
        app.include_router(router)
        with mock.patch("src.appstate.apphealth.report", return_value=report) as rep, \
                mock.patch.object(A, "pause_facts", return_value=[]):
            return TestClient(app).get("/feeds/alerts.rss"), rep

    def test_healthy_site_serves_an_empty_valid_feed(self):
        r, _ = self.get(healthy())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.headers["content-type"].startswith("application/rss+xml"))
        self.assertEqual(items_of(r.text), [])

    def test_a_broken_site_serves_the_alert_and_a_second_poll_serves_the_same_guid(self):
        report = healthy(reasons=["checkout: broken"])
        r1, _ = self.get(report)
        r2, _ = self.get(report)
        g1 = [i.findtext("guid") for i in items_of(r1.text)]
        g2 = [i.findtext("guid") for i in items_of(r2.text)]
        self.assertEqual(len(g1), 1)
        self.assertEqual(g1, g2)

    def test_if_the_health_check_raises_the_feed_says_so_instead_of_a_500(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.feeds import router
        app = FastAPI()
        app.include_router(router)
        with mock.patch("src.appstate.apphealth.report", side_effect=RuntimeError("boom")), \
                mock.patch.object(A, "pause_facts", return_value=[]):
            r = TestClient(app).get("/feeds/alerts.rss")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([i.findtext("title") for i in items_of(r.text)], ["The health check itself failed"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
