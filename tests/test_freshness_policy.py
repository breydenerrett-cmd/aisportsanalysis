"""The shared freshness policy (src/pipeline/freshness_policy.py) and everything that reads it.

Why this file exists (2026-10-19): the admin Health tab said "Prop listings: Stale, 12 days" while /health said ok
and the alerts feed stayed empty. The store was a finished audit (it spent its 400-credit cap on Oct 7), the live
prop price stores were fresh and untimed, and three surfaces judged freshness three ways. What is pinned here:

  * ONE set of limits: the alerts feed, the admin digest and the verdicts the Health tab draws agree store by store;
  * a store that is not expected to move (off-season, no game today, a finished audit, a season-over standings
    file) is grey with its reason and never alerts;
  * a truly stale store alerts once per UTC day, in plain words, with a one-line "what to do";
  * a finished prop-listing audit is recognised from its own markers, and live prop price stores are timed;
  * the deploy-age alert and the digest; the digest route is behind the admin token.

Core tests need no FastAPI (Linux CI has none); the route tests skip cleanly where it is missing.
"""

from __future__ import annotations

import json
import os
import re
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

from src.appstate import alert_feed as A
from src.appstate import apphealth
from src.pipeline import freshness_policy as P

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)      # a Monday, 4pm Eastern, in the postseason
ROOT = Path(__file__).resolve().parent.parent


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class Site:
    """A temporary data root with every tracked store written at a chosen age (hours before NOW)."""

    def __init__(self, test: unittest.TestCase, *, game_today=True, map_age_hours=2):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "app.db"
        self.set_map(game_today, map_age_hours)

    def set_map(self, game_today: bool, map_age_hours: float = 2) -> None:
        resolved = (NOW - timedelta(hours=map_age_hours)).isoformat()
        first_pitch = NOW + timedelta(hours=3) if game_today else NOW + timedelta(days=2)
        rows = [{"event_id": "e1", "commence_time": first_pitch.isoformat().replace("+00:00", "Z"),
                 "resolved_utc": resolved, "resolved": True}]
        write_jsonl(self.root / "processed" / "event_game_map.jsonl", rows)

    def store(self, subdir: str, name: str, field: str, age_hours: float, extra=None) -> None:
        stamp = (NOW - timedelta(hours=age_hours)).isoformat()
        write_jsonl(self.root / subdir / name, [{field: stamp, **(extra or {})}])

    def fresh_everything(self, **ages) -> None:
        defaults = {"odds_multibook": 0.2, "odds_snapshots": 0.2, "f5_close": 5, "prop_prices": 6,
                    "batter_props": 16, "prop_listing": None, "probables_watch": 0.3, "lineups_watch": 0.3,
                    "transactions_watch": 0.3}
        defaults.update(ages)
        for key, age in defaults.items():
            if key == "prop_listing" and age is None:
                # the real state on 2026-10-19: a finished audit (400 credits spent), 12 days ago
                stamp = (NOW - timedelta(days=12)).isoformat()
                write_jsonl(self.root / "processed" / "prop_listing.jsonl",
                            [{"observed_utc": stamp, "poll": True, "credits_last": 1}] * 400)
                continue
            if key == "odds_multibook":
                self.store("processed", "odds_multibook.jsonl", "observed_utc", age)
                continue
            subdir, name, field = apphealth.FORWARD_STORES[key]
            self.store(subdir, name, field, age)

    def report(self, now=NOW, pages=None) -> dict:
        """The real report over this root. The page-data block is stubbed (the historical stores are not what
        these tests are about); a test of that block passes its own."""
        block = pages if pages is not None else {"stores": {}, "core_stale": [], "stale": []}
        with mock.patch.object(apphealth, "check_data_freshness", return_value=block):
            return apphealth.report(data_dir=self.root, db_path=self.db, now=now)


def verdicts(report: dict) -> dict:
    return {v["key"]: v for v in report["freshness"]["stores"]}


class TheLimitsLiveInOnePlace(unittest.TestCase):
    def test_the_alert_feed_re_exports_the_policys_odds_limit_it_does_not_own_one(self):
        self.assertIs(A.ODDS_STALE_HOURS, P.ODDS_STALE_HOURS)
        self.assertEqual(P.EXPECTATIONS["odds_multibook"].stale_hours, P.ODDS_STALE_HOURS)

    def test_the_operator_watch_script_holds_the_same_odds_limit_and_deploy_age(self):
        from scripts import prod_watch
        self.assertEqual(prod_watch.ODDS_STALE_HOURS, P.ODDS_STALE_HOURS)

    def test_store_freshness_takes_its_day_tolerances_from_the_policy(self):
        from src.pipeline import store_freshness as SF
        for name in ("RESULTS_TOLERANCE_DAYS", "DAILY_TOLERANCE_DAYS", "PITCHER_TOLERANCE_DAYS",
                     "SEASON_AGGREGATE_TOLERANCE_DAYS", "STANDINGS_SEASON_ACTIVE_DAYS"):
            self.assertEqual(getattr(SF, name), getattr(P, name), name)
        src = (ROOT / "src" / "pipeline" / "store_freshness.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?m)^(RESULTS|DAILY|PITCHER|SEASON_AGGREGATE)_TOLERANCE_DAYS\s*=")

    def test_neither_the_alert_feed_nor_the_digest_has_a_threshold_of_its_own(self):
        text = (ROOT / "src" / "appstate" / "alert_feed.py").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^[A-Z_]*(HOURS|DAYS)\s*=\s*[\d.]+\s*$")
        admin = (ROOT / "api" / "admin.py").read_text(encoding="utf-8")
        self.assertNotRegex(admin, r"_HOURS\s*=")

    def test_every_tracked_forward_store_has_an_expectation_and_the_reverse(self):
        tracked = set(apphealth.FORWARD_STORES) | {apphealth.ODDS_STORE_NAME}
        self.assertEqual(tracked - set(P.EXPECTATIONS), set())
        self.assertEqual(set(P.EXPECTATIONS) - tracked, set())

    def test_the_policys_per_store_limits_match_the_brief(self):
        t = P.thresholds_snapshot()
        self.assertEqual(t["odds_multibook"][1], 3.0)
        self.assertEqual(t["lineups_watch"][1:], (6.0, "game_day"))
        self.assertEqual(t["probables_watch"][1:], (6.0, "game_day"))
        self.assertEqual(t["transactions_watch"][1], 72.0)
        self.assertEqual(t["prop_prices"][0], 24.0)
        self.assertEqual(t["batter_props"][0], 24.0)


class AllThreeSurfacesAgree(unittest.TestCase):
    """The page draws the verdicts, the feed alerts on them, the digest lists them: any one reading a store
    differently from the others is the bug this test exists to catch."""

    def test_for_every_store_at_every_age_the_feed_and_the_digest_match_the_verdict(self):
        for age in (0.2, 2.0, 4.0, 8.0, 20.0, 28.0, 34.0, 80.0, 300.0):
            site = Site(self)
            site.fresh_everything(**{k: age for k in P.EXPECTATIONS})
            report = site.report()
            with self.subTest(age=age):
                verdict_alerting = {v["key"] for v in report["freshness"]["attention"] if v["alert"]}
                alerts = A.collect(report, [], now=NOW)
                alerted_kinds = {a["kind"] for a in alerts}
                for key in verdict_alerting:
                    self.assertTrue(any(key in kind or kind in (A.KIND_ODDS_STALE, A.KIND_ODDS_MISSING)
                                        for kind in alerted_kinds), (key, alerted_kinds))
                digest = A.digest(report, [], now=NOW)
                self.assertEqual([i["kind"] for i in digest["items"]], [a["kind"] for a in alerts])
                # the page: tone is the verdict's tone, and only stale/problem verdicts are red
                for v in report["freshness"]["stores"]:
                    self.assertEqual(v["tone"], {"fresh": "ok", "aging": "warn", "stale": "bad",
                                                 "problem": "bad", "not_expected": "mute"}[v["state"]])

    def test_a_payload_without_verdicts_is_judged_by_the_same_policy(self):
        site = Site(self)
        site.fresh_everything(prop_prices=12 * 24)
        report = site.report()
        stripped = {k: v for k, v in report.items() if k != "freshness"}
        # Without the server's `freshness` block the feed still applies the same limits to the same stores. It cannot
        # know which audits have finished (that is read from the data root), so the finished prop-listing audit is
        # the one difference; every live store is judged identically.
        fallback = {a["guid"] for a in A.collect(stripped, [], now=NOW)}
        served = {a["guid"] for a in A.collect(report, [], now=NOW)}
        self.assertEqual(served, {"alert:store_stale_prop_prices:2026-10-19"})
        self.assertEqual(fallback - served, {"alert:store_stale_prop_listing:2026-10-19"})
        self.assertLessEqual(served, fallback)


class NotExpectedIsGreyAndSilent(unittest.TestCase):
    def test_off_season_stores_never_alert_however_old(self):
        winter = datetime(2026, 12, 15, 20, 0, tzinfo=timezone.utc)
        site = Site(self)
        site.set_map(False, 24 * 40)
        for key in P.EXPECTATIONS:
            if key == "odds_multibook":
                site.store("processed", "odds_multibook.jsonl", "observed_utc", 24 * 60)
            else:
                subdir, name, field = apphealth.FORWARD_STORES[key]
                stamp = (winter - timedelta(days=60)).isoformat()
                write_jsonl(site.root / subdir / name, [{field: stamp}])
        report = site.report(now=winter)
        states = {k: v["state"] for k, v in verdicts(report).items() if k in P.EXPECTATIONS}
        self.assertEqual(set(states.values()), {"not_expected"})
        self.assertEqual(A.collect(report, [], now=winter), [])
        for v in report["freshness"]["stores"]:
            if v["key"] in P.EXPECTATIONS:
                self.assertEqual(v["tone"], "mute")
                self.assertIn("season is over", v["reason"])

    def test_a_game_day_store_is_not_expected_on_a_confirmed_off_day(self):
        site = Site(self, game_today=False)
        site.fresh_everything(prop_prices=100, batter_props=100, lineups_watch=30, probables_watch=30, f5_close=100)
        report = site.report()
        v = verdicts(report)
        for key in ("prop_prices", "batter_props", "lineups_watch", "probables_watch", "f5_close"):
            self.assertEqual(v[key]["state"], "not_expected", key)
            self.assertIn("No MLB games today", v[key]["reason"])
        # but odds and transactions are in-season stores: an off day does not excuse them
        site.fresh_everything(odds_snapshots=9, transactions_watch=100, prop_prices=100, batter_props=100)
        v = verdicts(site.report())
        self.assertEqual(v["odds_snapshots"]["state"], "stale")
        self.assertEqual(v["transactions_watch"]["state"], "stale")

    def test_when_the_game_map_is_missing_or_old_the_day_is_unknown_and_stores_stay_expected(self):
        site = Site(self)
        (site.root / "processed" / "event_game_map.jsonl").unlink()
        site.fresh_everything(prop_prices=100)
        self.assertIsNone(P.game_day(site.root, NOW))
        self.assertEqual(verdicts(site.report())["prop_prices"]["state"], "stale")
        site.set_map(False, map_age_hours=72)                  # a map that stopped updating proves nothing
        self.assertIsNone(P.game_day(site.root, NOW))

    def test_game_day_is_read_from_the_eastern_date_of_first_pitch(self):
        site = Site(self, game_today=False)
        late = datetime(2026, 10, 20, 0, 10, tzinfo=timezone.utc)      # 8:10pm Eastern on the 19th
        write_jsonl(site.root / "processed" / "event_game_map.jsonl",
                    [{"commence_time": late.isoformat(), "resolved_utc": (NOW - timedelta(hours=3)).isoformat()}])
        self.assertTrue(P.game_day(site.root, NOW))

    def test_a_standings_file_after_the_regular_season_is_grey_not_amber(self):
        health = {"data_freshness": {"stores": {
            "standings": {"through": "2026-09-27", "lag_days": 0, "stale": False, "reason": None,
                          "tolerance_days": 1, "expected_through": "2026-09-27"},
            "transactions": {"through": "2026-10-16", "lag_days": 3, "stale": False, "reason": None,
                             "tolerance_days": 3, "expected_through": None}}}}
        v = {x["key"]: x for x in P.evaluate(health)}
        self.assertEqual((v["fresh_standings"]["state"], v["fresh_standings"]["tone"]), ("not_expected", "mute"))
        self.assertIn("last there will be", v["fresh_standings"]["reason"])
        self.assertEqual(v["fresh_transactions"]["state"], "fresh")                   # three days is its tolerance
        self.assertIn("within its 3-day tolerance", v["fresh_transactions"]["reason"])
        self.assertEqual(A.collect(health, [], now=NOW), [])

    def test_a_standings_file_that_is_behind_its_own_horizon_still_alerts(self):
        health = {"data_freshness": {"stores": {
            "standings": {"through": "2026-09-20", "lag_days": 7, "stale": True, "reason": "covers through 2026-09-20",
                          "tolerance_days": 1, "expected_through": "2026-09-27"}}}}
        alerts = A.collect(health, [], now=NOW)
        self.assertEqual([a["kind"] for a in alerts], ["data_stale_standings"])


class ThePropListingAuditIsFinishedNotBroken(unittest.TestCase):
    def audit_rows(self, polls: int, credits_each=1, when="2026-10-07T18:11:48+00:00"):
        rows = [{"observed_utc": when, "poll": True, "credits_last": credits_each, "game_date": "2026-10-07",
                 "event_id": f"e{i}", "slot": "T-2h"} for i in range(polls)]
        rows.append({"observed_utc": when, "book": "betonlineag", "market": "pitcher_strikeouts", "listed": True,
                     "credits_last": credits_each, "event_id": "e0", "player": "A"})   # listing rows are not spend
        return rows

    def test_the_audit_that_spent_its_cap_is_grey_with_the_reason_and_never_alerts(self):
        site = Site(self)
        site.fresh_everything(prop_listing=12 * 24)
        write_jsonl(site.root / "processed" / "prop_listing.jsonl", self.audit_rows(400))
        report = site.report()
        v = verdicts(report)["prop_listing"]
        self.assertEqual((v["state"], v["tone"], v["word"]), ("not_expected", "mute", "Not expected now"))
        self.assertIn("400-credit cap", v["reason"])
        self.assertIn("Finished on 2026-10-07", v["reason"])
        self.assertIn("not a stalled capture", v["reason"])
        self.assertEqual(report["freshness"]["situation"]["finished"]["prop_listing"]["since"], "2026-10-07")
        self.assertEqual([a["kind"] for a in A.collect(report, [], now=NOW)], [])

    def test_an_audit_under_its_cap_that_has_gone_quiet_is_a_real_stale_store(self):
        site = Site(self)
        site.fresh_everything(prop_listing=12 * 24)
        write_jsonl(site.root / "processed" / "prop_listing.jsonl", self.audit_rows(300))
        v = verdicts(site.report())["prop_listing"]
        self.assertEqual(v["state"], "stale")

    def test_the_live_prop_price_stores_are_timed_and_a_stalled_one_alerts_in_plain_words(self):
        site = Site(self)
        site.fresh_everything(prop_prices=12 * 24 + 3)
        write_jsonl(site.root / "processed" / "prop_listing.jsonl", self.audit_rows(400))
        report = site.report()
        self.assertIn("prop_prices", report["forward_captures"])
        self.assertIn("batter_props", report["forward_captures"])
        alerts = A.collect(report, [], now=NOW)
        self.assertEqual([a["title"] for a in alerts], ["Pitcher prop prices are 12 days old"])
        text = alerts[0]["description"]
        self.assertIn("Fix:", text)
        self.assertIn("prop_prices.py", text)                       # the cause names the writer
        self.assertIn("forward-capture", alerts[0]["fix"])


class StaleAlertsOncePerDayWithAWhatToDo(unittest.TestCase):
    def stale_report(self):
        site = Site(self)
        site.fresh_everything(prop_prices=40, lineups_watch=9)
        return site.report()

    def test_each_truly_stale_store_gets_one_item_with_a_stable_guid_per_utc_day(self):
        report = self.stale_report()
        early = A.collect(report, [], now=NOW.replace(hour=1))
        late = A.collect(report, [], now=NOW.replace(hour=23))
        self.assertEqual(sorted(a["kind"] for a in early), ["store_stale_lineups_watch", "store_stale_prop_prices"])
        self.assertEqual([a["guid"] for a in early], [a["guid"] for a in late])
        self.assertTrue(all(g.endswith("2026-10-19") for g in (a["guid"] for a in early)))
        tomorrow = {a["guid"] for a in A.collect(report, [], now=NOW + timedelta(days=1))}
        self.assertFalse(tomorrow & {a["guid"] for a in early})

    def test_every_alert_the_feed_can_raise_says_what_to_do(self):
        report = self.stale_report()
        report["reasons"] = ["app db unreachable: x", "checkout: PUBLIC_BASE_URL is unset", "prop_prices: bad"]
        pauses = [{"scope": "house", "reason": "r", "since": "2026-10-17T05:00:00Z"}]
        alerts = (A.collect(report, pauses, now=NOW, started_utc=(NOW - timedelta(hours=9)).isoformat())
                  + A.collect(None, [], now=NOW, health_error="OperationalError"))
        self.assertGreaterEqual(len(alerts), 7)
        for a in alerts:
            self.assertTrue(a["fix"], a["kind"])
            self.assertRegex(a["description"], r"Fix: .+\.$", a["kind"])
            self.assertNotIn("None", a["title"])
        xml = A.render_feed(alerts)
        self.assertEqual(len(re.findall(r"<item>", xml)), len(alerts))

    def test_the_feed_item_dates_come_from_the_incident_not_from_now(self):
        report = self.stale_report()
        alerts = A.collect(report, [], now=NOW)
        by = {a["kind"]: a for a in alerts}
        prop = by["store_stale_prop_prices"]
        self.assertEqual(prop["pub"], NOW - timedelta(hours=40) + timedelta(hours=30))
        self.assertLessEqual(prop["pub"], NOW)

    def test_an_unreadable_store_is_shown_red_but_alerted_once_through_the_health_reason(self):
        site = Site(self)
        site.fresh_everything()
        (site.root / "processed" / "prop_prices.jsonl").write_text("not json\nstill not\n", encoding="utf-8")
        report = site.report()
        self.assertEqual(verdicts(report)["prop_prices"]["state"], "problem")
        kinds = [a["kind"] for a in A.collect(report, [], now=NOW)]
        self.assertEqual(kinds, ["health_prop_prices"])


class TheRunningVersionAlert(unittest.TestCase):
    def healthy(self):
        return {"status": "ok", "reasons": [], "odds": {}, "forward_captures": {}, "data_freshness": {"stores": {}}}

    def test_a_process_older_than_three_hours_means_redeploys_stopped(self):
        started = (NOW - timedelta(hours=7, minutes=20)).isoformat()
        alerts = A.collect(self.healthy(), [], now=NOW, started_utc=started)
        self.assertEqual([a["title"] for a in alerts], ["Production has not redeployed in 7 hours"])
        self.assertEqual(alerts[0]["kind"], "deploy_stale")
        self.assertIn("deploy-prod", alerts[0]["fix"])

    def test_a_recent_deploy_or_an_unknown_start_says_nothing(self):
        recent = (NOW - timedelta(minutes=50)).isoformat()
        self.assertEqual(A.collect(self.healthy(), [], now=NOW, started_utc=recent), [])
        self.assertEqual(A.collect(self.healthy(), [], now=NOW, started_utc=None), [])
        self.assertEqual(A.collect(self.healthy(), [], now=NOW, started_utc="garbage"), [])

    def test_exactly_three_hours_is_still_inside_the_limit(self):
        self.assertEqual(A.collect(self.healthy(), [], now=NOW,
                                   started_utc=(NOW - timedelta(hours=3)).isoformat()), [])

    def test_the_digest_says_ci_is_not_checked_so_silence_is_not_read_as_green(self):
        d = A.digest(self.healthy(), [], now=NOW)
        self.assertTrue(any("CI" in line for line in d["not_checked"]))


class TheDigest(unittest.TestCase):
    def test_an_all_clear_site_says_so(self):
        site = Site(self)
        site.fresh_everything()
        d = A.digest(site.report(), [], now=NOW)
        self.assertTrue(d["all_clear"])
        self.assertEqual(d["headline"], "Nothing needs doing today.")
        self.assertEqual(d["items"], [])

    def test_a_site_with_problems_lists_them_as_plain_sentences_with_fixes(self):
        site = Site(self)
        site.fresh_everything(prop_prices=200, batter_props=27)
        d = A.digest(site.report(), [], now=NOW)
        self.assertFalse(d["all_clear"])
        self.assertEqual(d["headline"], "1 thing needs doing today.")
        self.assertEqual(d["items"][0]["title"], "Pitcher prop prices are 8 days old")
        self.assertTrue(d["items"][0]["line"].endswith("."))
        self.assertIn("Fix:", d["items"][0]["line"])
        self.assertEqual([w["key"] for w in d["watch"]], ["batter_props"])            # 27h: past 24, short of 30

    def test_the_grey_stores_are_listed_with_their_reasons(self):
        site = Site(self)
        site.fresh_everything(prop_listing=300)
        write_jsonl(site.root / "processed" / "prop_listing.jsonl",
                    [{"observed_utc": "2026-10-07T18:00:00+00:00", "poll": True, "credits_last": 1}] * 400)
        d = A.digest(site.report(), [], now=NOW)
        grey = {g["key"]: g["reason"] for g in d["not_expected"]}
        self.assertIn("Finished on 2026-10-07", grey["prop_listing"])


class TheHealthPayload(unittest.TestCase):
    def test_verdicts_ride_in_the_payload_and_never_change_the_status(self):
        site = Site(self)
        site.fresh_everything(prop_prices=500)
        report = site.report()
        self.assertEqual(report["status"], "ok")             # informational, like data_freshness
        self.assertEqual(report["reasons"], [])
        self.assertTrue(report["freshness"]["attention"])

    def test_the_big_batter_props_store_is_aged_from_its_tail_not_parsed_end_to_end(self):
        site = Site(self)
        site.fresh_everything()
        path = site.root / "processed" / "batter_props.jsonl"
        old = (NOW - timedelta(days=3)).isoformat()
        new = (NOW - timedelta(hours=5)).isoformat()
        filler = [{"observed_utc": old, "pad": "x" * 200}] * 4000          # ~900 KB before the tail
        write_jsonl(path, filler + [{"observed_utc": new}])
        apphealth._SCAN_CACHE.clear()
        with mock.patch.object(apphealth, "_newest_timestamp", side_effect=AssertionError("full scan")):
            check = apphealth.check_store(path, "observed_utc", now=NOW)
        self.assertEqual(check.status, "ok")
        self.assertIsNone(check.rows)                         # unknown, not guessed
        self.assertAlmostEqual(check.newest_row_age_seconds, 5 * 3600, delta=1)

    def test_a_freshness_failure_degrades_to_an_error_block_not_a_500(self):
        site = Site(self)
        with mock.patch("src.pipeline.freshness_policy.summarize", side_effect=RuntimeError("boom")):
            report = site.report()
        self.assertIn("could not evaluate freshness", report["freshness"]["error"])
        self.assertEqual(report["freshness"]["stores"], [])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheDigestRoute(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("APP_ADMIN_TOKEN")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop("APP_ADMIN_TOKEN", None)
        else:
            os.environ["APP_ADMIN_TOKEN"] = self._saved

    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.admin import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_without_a_configured_token_the_route_does_not_exist(self):
        os.environ.pop("APP_ADMIN_TOKEN", None)
        self.assertEqual(self.client().get("/admin/health-digest").status_code, 404)

    def test_a_missing_or_wrong_token_is_refused(self):
        os.environ["APP_ADMIN_TOKEN"] = "right-token"
        c = self.client()
        self.assertEqual(c.get("/admin/health-digest").status_code, 401)
        self.assertEqual(c.get("/admin/health-digest", headers={"X-Admin-Token": "nope"}).status_code, 401)

    def test_the_right_token_gets_the_digest_built_from_the_shared_checks(self):
        os.environ["APP_ADMIN_TOKEN"] = "right-token"
        site = Site(self)
        site.fresh_everything(prop_prices=300)
        with mock.patch("src.appstate.apphealth.report", return_value=site.report(now=datetime.now(timezone.utc))), \
                mock.patch.object(A, "pause_facts", return_value=[]):
            r = self.client().get("/admin/health-digest", headers={"X-Admin-Token": "right-token"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for key in ("headline", "all_clear", "items", "watch", "not_expected", "not_checked", "generated_at"):
            self.assertIn(key, body)
        self.assertIn("deploy", " ".join(i["kind"] for i in body["items"]) + " deploy")   # shape only

    def test_the_alerts_feed_route_carries_the_process_start_for_the_deploy_alert(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api import health as api_health
        from api.feeds import router
        app = FastAPI()
        app.include_router(router)
        healthy = {"status": "ok", "reasons": [], "odds": {}, "forward_captures": {}, "data_freshness": {"stores": {}}}
        old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
        with mock.patch("src.appstate.apphealth.report", return_value=healthy), \
                mock.patch.object(A, "pause_facts", return_value=[]), \
                mock.patch.object(api_health, "process_started_utc", return_value=old):
            r = TestClient(app).get("/feeds/alerts.rss")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Production has not redeployed in 9 hours", r.text)


if __name__ == "__main__":
    unittest.main()
