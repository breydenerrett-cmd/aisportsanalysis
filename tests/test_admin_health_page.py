"""The admin Health tab and Overview "Needs your attention", run under node against the REAL server-side verdicts
(src/pipeline/freshness_policy.py via apphealth.report) and the REAL digest (alert_feed.digest).

Owner report, 2026-10-19: the tab showed "Prop listings: Stale, 12 days" (a finished audit), "matchup history 1 day
behind" and "transactions 3 days behind" (both inside their own tolerance) and "standings 2026-09-27" (the season is
over) as warnings, while /health was ok and nothing was emailed. What is pinned: the page draws the server's verdict
for every store (a divergence test over every card), grey cards say why, red cards say what to do, and the attention
list is the digest. Skipped when node is not installed.
"""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import alert_feed as A
from tests import admin_dashboard_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_page
from tests.test_freshness_policy import NOW as REPORT_NOW, Site

PAGE_NOW = datetime(2026, 10, 19, 20, 5, 0, tzinfo=timezone.utc)
STORED = {"aisportsanalysis.admin_token": "tok-admin-123"}

PAGES = {
    "mlb_results": {"through": "2026-10-18", "lag_days": 0, "stale": False, "reason": None, "tolerance_days": 1},
    "matchup_history": {"through": "2026-10-18", "lag_days": 1, "stale": False, "reason": None, "tolerance_days": 1},
    "transactions": {"through": "2026-10-16", "lag_days": 3, "stale": False, "reason": None, "tolerance_days": 3},
    "standings": {"through": "2026-09-27", "lag_days": 0, "stale": False, "reason": None, "tolerance_days": 1,
                  "expected_through": "2026-09-27"},
}


def scenario(test, **ages):
    site = Site(test)
    site.fresh_everything(**ages)
    report = site.report(pages={"stores": PAGES, "core_stale": [], "stale": [], "baseball_date": "2026-10-19"})
    table = {path: [200, body] for path, body in F.build(PAGE_NOW).items()}
    overview = copy.deepcopy(F.build(PAGE_NOW)["/admin/overview"])
    overview["store_health"] = report
    table["/admin/overview"] = [200, overview]
    digest = A.digest(report, [], now=REPORT_NOW)
    table["/admin/health-digest"] = [200, digest]
    # nothing else should need the owner in this scenario
    users = copy.deepcopy(F.build(PAGE_NOW)["/admin/users"])
    users["users"] = [u for u in users["users"] if u["status"] != "waitlisted" and not u["tester"]]
    table["/admin/users"] = [200, users]
    table["/admin/testers"] = [200, dict(copy.deepcopy(F.build(PAGE_NOW)["/admin/testers"]), testers=[])]
    table["/admin/support"] = [200, {"messages": []}]
    return report, digest, table


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheHealthTabDrawsTheServersVerdicts(unittest.TestCase):
    def run_health(self, table):
        return run_page("admin", now=PAGE_NOW.isoformat(), routes=table, stored=dict(STORED),
                        actions=[dict(do="click", sel="[data-hook='admin-nav-item'][data-route='health']")],
                        queries=[
                            q("stores", "[data-hook='admin-health-card']", "attrs", attr="data-store"),
                            q("tones", "[data-hook='admin-health-card']", "attrs", attr="data-tone"),
                            q("words", "[data-hook='admin-health-word']", "texts"),
                            q("reasons", "[data-hook='admin-health-reason']", "texts"),
                            q("fixes", "[data-hook='admin-health-fix']", "texts"),
                            q("legend", "[data-hook='admin-health-legend']"),
                        ])["final"]

    def test_every_card_has_the_tone_and_word_the_server_gave_that_store(self):
        report, _digest, table = scenario(self, prop_prices=40, f5_close=26, lineups_watch=9)
        f = self.run_health(table)
        tone = dict(zip(f["stores"], f["tones"]))
        word = dict(zip(f["stores"], f["words"]))
        for v in report["freshness"]["stores"]:
            self.assertIn(v["key"], tone, v["key"])
            self.assertEqual(tone[v["key"]], v["tone"], v["key"])
            self.assertEqual(word[v["key"]], v["word"], v["key"])
        self.assertTrue(f["legend"])

    def test_the_owners_four_complaints_are_no_longer_warnings(self):
        _report, _digest, table = scenario(self)
        f = self.run_health(table)
        tone = dict(zip(f["stores"], f["tones"]))
        word = dict(zip(f["stores"], f["words"]))
        self.assertEqual((tone["prop_listing"], word["prop_listing"]), ("mute", "Not expected now"))
        self.assertEqual((tone["fresh_matchup_history"], tone["fresh_transactions"]), ("ok", "ok"))
        self.assertEqual((tone["fresh_standings"], word["fresh_standings"]), ("mute", "Not expected now"))
        store_tones = {k: t for k, t in tone.items() if k not in ("app_db", "checkout", "version")}
        self.assertEqual(set(store_tones.values()), {"ok", "mute"})        # no amber, no red anywhere in the stores
        self.assertTrue(any("Finished on 2026-10-07" in r for r in f["reasons"]))
        self.assertTrue(any("last there will be" in r for r in f["reasons"]))

    def test_a_stalled_store_is_red_and_the_card_says_what_to_do(self):
        _report, _digest, table = scenario(self, prop_prices=12 * 24)
        f = self.run_health(table)
        tone = dict(zip(f["stores"], f["tones"]))
        self.assertEqual(tone["prop_prices"], "bad")
        self.assertEqual(len(f["fixes"]), 1)
        self.assertTrue(f["fixes"][0].startswith("What to do:"))
        self.assertIn("forward-capture", f["fixes"][0])

    def test_an_older_server_without_verdicts_still_draws_the_cards(self):
        _report, _digest, table = scenario(self)
        overview = table["/admin/overview"][1]
        del overview["store_health"]["freshness"]
        f = self.run_health(table)
        self.assertIn("odds_multibook", f["stores"])
        self.assertFalse(f["legend"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class NeedsYourAttentionIsTheDigest(unittest.TestCase):
    def attention(self, table):
        return run_page("admin", now=PAGE_NOW.isoformat(), routes=table, stored=dict(STORED), queries=[
            q("keys", "[data-hook='admin-attention-item']", "attrs", attr="data-key"),
            q("texts", "[data-hook='admin-attention-item']", "texts"),
            q("empty", "[data-hook='admin-attention-empty']"),
        ])["final"]

    def test_a_site_with_nothing_to_do_says_so(self):
        _report, digest, table = scenario(self)
        self.assertTrue(digest["all_clear"])
        f = self.attention(table)
        self.assertEqual(f["keys"], [])
        self.assertIn("Nothing needs you", f["empty"])

    def test_the_digests_items_are_the_lists_health_rows_with_their_fix(self):
        _report, digest, table = scenario(self, prop_prices=12 * 24, batter_props=27)
        f = self.attention(table)
        self.assertEqual(f["keys"], [f"health-{i['kind']}" for i in digest["items"]] + ["health-aging"])
        joined = " ".join(f["texts"])
        self.assertIn("Pitcher prop prices are 12 days old", joined)
        self.assertIn("Fix:", joined)
        self.assertIn("1 data store is getting old", joined)

    def test_if_the_digest_cannot_be_loaded_the_old_card_based_list_still_shows_red_cards(self):
        _report, _digest, table = scenario(self, prop_prices=12 * 24)
        table["/admin/health-digest"] = [500, {"detail": "boom"}]
        f = self.attention(table)
        self.assertIn("health-prop_prices", f["keys"])


class TheDigestAndPageCannotDiverge(unittest.TestCase):
    """Python-only: runs without node. The digest's items are exactly the red verdicts the page paints red."""

    def test_digest_items_are_the_red_verdicts_that_want_an_alert(self):
        for kw in ({}, {"prop_prices": 300}, {"prop_prices": 300, "lineups_watch": 12, "odds_snapshots": 5}):
            site = Site(self)
            site.fresh_everything(**kw)
            report = site.report()
            digest = A.digest(report, [], now=REPORT_NOW)
            red = {v["title"] for v in report["freshness"]["stores"] if v["tone"] == "bad" and v["alert"]}
            self.assertEqual(len(digest["items"]), len(red), kw)
            self.assertEqual(digest["all_clear"], not red)


if __name__ == "__main__":
    unittest.main()
