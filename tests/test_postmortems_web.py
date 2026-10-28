"""The record page's spreadsheet link and hindsight reviews (web/js/record-postmortems.js inside web/js/track-record.js), run for real
under node against payloads built by the real Python builder (src/hounds/track_record.py), so a drift between the two fails here.

  LINK     "Download bets (spreadsheet)" shows on a house hound's record, and on a member hound's only for its owner.
  FILE     the owner's click fetches the file with the sign-in header and saves it; a refusal is said in words.
  REVIEWS  a settled ticket opens to its hindsight review (what happened, factors, reason, luck, lesson, analysts, sources), labelled
           as written after the result; a visitor to a member hound sees none; a server without the route changes nothing.
  LINKS    only http(s) sources are links, and they open in a new tab with no referrer.
"""
from __future__ import annotations

import re
import unittest

from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_track_record_web import BANNED, SIGNED, hook, page, payload, q


def review(**over):
    out = {"depth": "fast", "model": "claude-haiku-5-5", "created_utc": "2026-10-28T21:00:00Z", "label": "Hindsight review",
           "what_happened": "Lost 5-2 after the starter left in the fourth with a blister.", "key_factors": ["starter left early", "bullpen gave up three"],
           "factor_tags": ["starter_performance"], "reason_relevance": "partly_valid", "reason_assessment": "Sound angle, hurt starter.",
           "luck_vs_process": "mixed", "info_hound_lacked": ["a blister was reported before the game"], "lesson": "Check the health report first.",
           "grounded": True, "confidence": "high",
           "analyst_takes": [{"outlet": "Example Sports", "take": "A thin lineup against lefties.", "url": "https://example.com/recap"}],
           "sources": [{"url": "https://example.com/recap", "title": "Game recap", "kind": "recap"},
                       {"url": "https://example.org/injuries", "title": "Injury report", "kind": "injury"}]}
    out.update(over)
    return out


def reviews_body(p, n=2, visible=True, **over):
    keys = [t["bet_key"] for t in p["tickets"][:n]]
    return {"visible": visible, "reviews": {k: review(bet_key=k, **over) for k in keys}}


def owner_routes(p, **extra):
    routes = {"/hounds/u-1/kit": [200, {"is_owner": True}]}
    routes.update(extra)
    return routes


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSpreadsheetLink(unittest.TestCase):
    def probe(self, p, **kw):
        return page(p, queries=[hook("record-export", mode="hidden"), q("link", "[data-hook='export-link']"),
                                q("href", "[data-hook='export-link']", "attr", attr="href")], **kw)

    def test_a_house_hounds_record_offers_the_spreadsheet_to_anyone(self):
        p = payload()
        p["hound"]["is_house"] = True
        f = self.probe(p)["final"]
        self.assertFalse(f["record-export"])
        self.assertEqual(f["link"], "Download bets (spreadsheet)")
        self.assertEqual(f["href"], "/hounds/u-1/export?format=csv")

    def test_a_member_hounds_record_hides_it_from_a_visitor(self):
        p = payload()
        p["hound"]["is_house"] = False
        f = self.probe(p)["final"]
        self.assertTrue(f["record-export"])
        self.assertIsNone(f["link"])

    def test_a_member_hounds_record_shows_it_to_its_owner(self):
        p = payload()
        p["hound"]["is_house"] = False
        f = self.probe(p, routes={"/hounds/u-1/record": [200, p], "/hounds/u-1/kit": [200, {"is_owner": True}]}, **SIGNED)["final"]
        self.assertFalse(f["record-export"])
        self.assertEqual(f["link"], "Download bets (spreadsheet)")

    def test_the_owners_click_fetches_the_file_with_the_sign_in_and_saves_it(self):
        p = payload()
        p["hound"]["is_house"] = False
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/kit": [200, {"is_owner": True}], "/hounds/u-1/export": [200, "Bet ID,Hound ID\n"]}
        out = run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=200, **SIGNED,
                       actions=[dict(do="click", sel="[data-hook='export-link']", wait=150, label="go", capture=[hook("export-note")])])
        self.assertEqual(len(out["downloads"]), 1)
        self.assertEqual(out["downloads"][0]["download"], "linehound-u-1-bets.csv")
        calls = [c for c in out["getCalls"] if "/export" in c["url"]]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], "/hounds/u-1/export?format=csv")
        self.assertEqual(calls[0]["headers"].get("Authorization"), "Bearer tok")
        self.assertIn("Saved", out["captures"]["go"]["export-note"])

    def test_a_refusal_is_said_in_words_and_nothing_is_saved(self):
        p = payload()
        p["hound"]["is_house"] = False
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/kit": [200, {"is_owner": True}],
                  "/hounds/u-1/export": [503, {"detail": {"error": "warming_up", "message": "The record is still being worked out. Try again in a few seconds."}}]}
        out = run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=200, **SIGNED,
                       actions=[dict(do="click", sel="[data-hook='export-link']", wait=150, label="go", capture=[hook("export-note")])])
        self.assertEqual(out["downloads"], [])
        self.assertIn("still being worked out", out["captures"]["go"]["export-note"])

    def test_a_visitor_with_no_sign_in_sends_no_header(self):
        p = payload()
        p["hound"]["is_house"] = True
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/export": [200, "x"]}
        out = run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=200,
                       actions=[dict(do="click", sel="[data-hook='export-link']", wait=150, label="go")])
        calls = [c for c in out["getCalls"] if "/export" in c["url"]]
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0]["headers"])
        self.assertEqual(len(out["downloads"]), 1)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheReviews(unittest.TestCase):
    def go(self, p, body, **kw):
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/postmortems": [200, body]}
        routes.update(kw.pop("routes", {}))
        queries = [q("n", "[data-hook='review']", "count"), q("sum", "[data-hook='review'] summary", "texts"),
                   q("text", "[data-hook='ticket-list']"), q("hrefs", "[data-hook='review-sources'] a", "attrs", attr="href"),
                   q("rels", "[data-hook='review-sources'] a", "attrs", attr="rel"), q("tickets", "[data-hook='ticket']", "count")]
        return run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=250, queries=queries, **kw)["final"]

    def test_a_settled_ticket_opens_to_its_hindsight_review(self):
        p = payload()
        f = self.go(p, reviews_body(p, 2))
        self.assertEqual(f["n"], 2)
        self.assertEqual(f["sum"], ["Hindsight review", "Hindsight review"])
        for needle in ("Written after the result", "What happened: Lost 5-2", "Key factors:", "starter left early",
                       "Was the hound's reason relevant: Partly", "Sound angle, hurt starter", "Luck or process: A mix of process and luck",
                       "What the hound did not know:", "a blister was reported", "Lesson: Check the health report first.",
                       "Other analysts:", "Example Sports: A thin lineup", "Sources:", "Game recap", "Injury report"):
            self.assertIn(needle, f["text"], needle)

    def test_sources_are_links_that_open_in_a_new_tab_without_a_referrer(self):
        p = payload()
        f = self.go(p, reviews_body(p, 1))
        self.assertEqual(f["hrefs"], ["https://example.com/recap", "https://example.org/injuries"])
        self.assertTrue(all("noopener" in r and "noreferrer" in r for r in f["rels"]))

    def test_a_source_that_is_not_http_is_never_a_link(self):
        p = payload()
        bad = [{"url": "javascript:alert(1)", "title": "Click me", "kind": "news"}, {"url": "data:text/html,x", "title": "Data", "kind": "news"},
               {"url": "https://example.com/ok", "title": "Fine", "kind": "recap"}]
        f = self.go(p, reviews_body(p, 1, sources=bad, analyst_takes=[]))
        self.assertEqual(f["hrefs"], ["https://example.com/ok"])

    def test_an_unsourced_review_says_it_is_unchecked(self):
        p = payload()
        f = self.go(p, reviews_body(p, 1, grounded=False, sources=[], analyst_takes=[], confidence="low"))
        self.assertIn("No sources were found for this review", f["text"])
        self.assertNotIn("Sources:", f["text"])

    def test_a_deep_review_is_marked_and_carries_its_deeper_notes(self):
        p = payload()
        f = self.go(p, reviews_body(p, 1, depth="deep", deeper_notes="The closer had thrown 40 pitches the night before."))
        self.assertEqual(f["sum"], ["Hindsight review (deep)"])
        self.assertIn("Deeper notes: The closer had thrown 40 pitches", f["text"])

    def test_a_visitor_to_a_member_hound_sees_no_reviews(self):
        p = payload()
        f = self.go(p, {"visible": False, "reviews": {}})
        self.assertEqual((f["n"], f["tickets"]), (0, 24))

    def test_a_server_without_the_route_changes_nothing(self):
        p = payload()
        out = run_page("record", search="?id=u-1", routes={"/hounds/u-1/record": [200, p]}, tz="UTC", settleMs=250,
                       queries=[q("n", "[data-hook='review']", "count"), q("tickets", "[data-hook='ticket']", "count"),
                                hook("record-state", mode="hidden")])
        self.assertEqual((out["final"]["n"], out["final"]["tickets"]), (0, 24))
        self.assertTrue(out["final"]["record-state"])

    def test_only_settled_tickets_carry_a_review_never_an_open_one(self):
        p = payload()
        body = {"visible": True, "reviews": {t["bet_key"]: review(bet_key=t["bet_key"]) for t in p["open"] + p["waiting"]}}
        f = self.go(p, body)
        self.assertEqual(f["n"], 0)

    def test_a_filter_keeps_the_reviews_on_the_tickets_that_stay(self):
        p = payload()
        keep = [t for t in p["tickets"] if t["sport"] == "nba"][:2]
        body = {"visible": True, "reviews": {t["bet_key"]: review(bet_key=t["bet_key"]) for t in keep}}
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/postmortems": [200, body]}
        out = run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=250,
                       actions=[dict(do="set", sel="[data-hook='filter-sport']", value="NBA", label="nba", wait=80,
                                     capture=[q("n", "[data-hook='review']", "count"), q("t", "[data-hook='ticket']", "count")]),
                                dict(do="set", sel="[data-hook='filter-sport']", value="MLB", label="mlb", wait=80,
                                     capture=[q("n", "[data-hook='review']", "count"), q("t", "[data-hook='ticket']", "count")])])
        self.assertEqual((out["captures"]["nba"]["n"], out["captures"]["nba"]["t"]), (2, 12))
        self.assertEqual((out["captures"]["mlb"]["n"], out["captures"]["mlb"]["t"]), (0, 12))

    def test_every_ticket_in_the_payload_carries_its_bet_key(self):
        p = payload()
        keys = [t["bet_key"] for t in p["tickets"] + p["open"] + p["waiting"]]
        self.assertTrue(all(re.fullmatch(r"pm_[0-9a-f]{16}", k) for k in keys))
        self.assertEqual(len(keys), len(set(keys)))


def deep(**over):
    out = {"review_key": "dr_aaaaaaaaaaaaaaaa", "label": "Deep review (hindsight)", "created_utc": "2026-10-28T21:00:00Z", "model": "claude-sonnet-5-5",
           "settled": 24, "versions": 2, "record": {"wins": 11, "losses": 12, "pushes": 1}, "units": -1.5, "units_basis": "board-average price",
           "by_version": [{"version": "v1", "status": "replaced by a later version", "bets": 12, "wins": 5, "losses": 7, "pushes": 0, "units": -3.0},
                          {"version": "v2", "status": "running", "bets": 12, "wins": 6, "losses": 5, "pushes": 1, "units": 1.5}],
           "headline": "It lost slightly more than it won, and the later version did better.",
           "working": ["Underdog picks held up better than favourites.", "The later version cut its losing sport."],
           "failing": ["Spread bets lost more units than any other market."],
           "changes": ["Try dropping the spread rule first.", "Try a narrower price band on underdogs."],
           "sample_note": "This rests on 24 settled bets, so treat it as a rough look."}
    out.update(over)
    return out


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheAllVersionsLink(unittest.TestCase):
    def probe(self, p, **kw):
        return page(p, queries=[hook("record-export", mode="hidden"), q("link", "[data-hook='export-link']"), q("all", "[data-hook='export-all-link']"),
                                q("href", "[data-hook='export-link']", "attr", attr="href"),
                                q("allhref", "[data-hook='export-all-link']", "attr", attr="href"), q("hint", ".rc-export__hint")], **kw)

    def test_all_versions_sits_beside_the_ordinary_link_and_the_ordinary_link_is_unchanged(self):
        p = payload()
        p["hound"]["is_house"] = True
        f = self.probe(p)["final"]
        self.assertFalse(f["record-export"])
        self.assertEqual((f["link"], f["href"]), ("Download bets (spreadsheet)", "/hounds/u-1/export?format=csv"))
        self.assertEqual((f["all"], f["allhref"]), ("All versions", "/hounds/u-1/export?format=csv&versions=all"))

    def test_a_visitor_to_a_member_hound_gets_neither_link_and_its_owner_gets_both(self):
        p = payload()
        p["hound"]["is_house"] = False
        gone = self.probe(p)["final"]
        self.assertTrue(gone["record-export"])
        self.assertIsNone(gone["all"])
        both = self.probe(p, routes={"/hounds/u-1/record": [200, p], "/hounds/u-1/kit": [200, {"is_owner": True}]}, **SIGNED)["final"]
        self.assertEqual((both["link"], both["all"]), ("Download bets (spreadsheet)", "All versions"))

    def test_the_owners_click_fetches_every_version_with_the_sign_in_and_saves_it_under_its_own_name(self):
        p = payload()
        p["hound"]["is_house"] = False
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/kit": [200, {"is_owner": True}], "/hounds/u-1/export": [200, "Bet ID,Version\n"]}
        out = run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=200, **SIGNED,
                       actions=[dict(do="click", sel="[data-hook='export-all-link']", wait=150, label="go", capture=[hook("export-note")])])
        self.assertEqual(len(out["downloads"]), 1)
        self.assertEqual(out["downloads"][0]["download"], "linehound-u-1-bets-all-versions.csv")
        calls = [c for c in out["getCalls"] if "/export" in c["url"]]
        self.assertEqual([c["url"] for c in calls], ["/hounds/u-1/export?format=csv&versions=all"])
        self.assertEqual(calls[0]["headers"].get("Authorization"), "Bearer tok")
        self.assertIn("Every version is in the one sheet", out["captures"]["go"]["export-note"])

    def test_a_refusal_for_all_versions_is_said_in_words_and_nothing_is_saved(self):
        p = payload()
        p["hound"]["is_house"] = False
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/kit": [200, {"is_owner": True}],
                  "/hounds/u-1/export": [403, {"detail": {"error": "owner_only", "message": "Only a hound's owner can download its spreadsheet."}}]}
        out = run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=200, **SIGNED,
                       actions=[dict(do="click", sel="[data-hook='export-all-link']", wait=150, label="go", capture=[hook("export-note")])])
        self.assertEqual(out["downloads"], [])
        self.assertIn("Only a hound's owner", out["captures"]["go"]["export-note"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDeepReview(unittest.TestCase):
    def go(self, p, body, **kw):
        routes = {"/hounds/u-1/record": [200, p], "/hounds/u-1/postmortems": [200, body]}
        queries = [hook("record-deep-section", mode="hidden"), q("n", "[data-hook='deep-review']", "count"),
                   q("sum", "[data-hook='deep-review'] summary", "texts"), q("open", "[data-hook='deep-review']", "attrs", attr="open"),
                   q("text", "[data-hook='record-deep']"), q("head", "#rc-deep-h"), q("basis", "[data-hook='deep-basis']", "texts"),
                   q("reviews", "[data-hook='review']", "count")]
        return run_page("record", search="?id=u-1", routes=routes, tz="UTC", settleMs=250, queries=queries, **kw)["final"]

    def test_the_deep_review_shows_under_the_tickets_labelled_hindsight_with_its_date(self):
        p = payload()
        f = self.go(p, dict(reviews_body(p, 2), deep_reviews=[deep()]))
        self.assertFalse(f["record-deep-section"])
        self.assertEqual(f["head"], "Deep review")
        self.assertEqual(f["n"], 1)
        self.assertRegex(f["sum"][0], r"^Deep review \(hindsight\), Oct 28 at 9:00 PM")
        for needle in ("Written after the results", "not what the hound knew before a game", "It lost slightly more than it won",
                       "What is working:", "Underdog picks held up better", "What is failing:", "Spread bets lost more units",
                       "Biggest changes worth trying:", "Try a narrower price band", "About the sample: This rests on 24 settled bets",
                       "By version:", "v1 (replaced by a later version): 12 bets, 5-7-0", "v2 (running): 12 bets, 6-5-1"):
            self.assertIn(needle, f["text"], needle)
        self.assertEqual(f["basis"], ["Rests on 24 settled bets across 2 versions: 11-12-1."])
        self.assertEqual(f["reviews"], 2)                                                       # the bet reviews are still under their tickets

    def test_the_section_sits_after_the_tickets_and_before_the_comparison(self):
        html = (WEB / "record.html").read_text(encoding="utf-8")
        self.assertLess(html.index('data-hook="record-tickets-section"'), html.index('data-hook="record-deep-section"'))
        self.assertLess(html.index('data-hook="record-deep-section"'), html.index('data-hook="record-compare-section"'))
        self.assertRegex(html, r'data-hook="record-deep-section"[^>]*\bhidden\b')

    def test_the_newest_opens_and_the_earlier_ones_stay_listed_closed(self):
        p = payload()
        older = deep(created_utc="2026-10-21T21:00:00Z", headline="The first look at both versions.", settled=12)
        f = self.go(p, dict(reviews_body(p, 1), deep_reviews=[deep(), older]))
        self.assertEqual(f["n"], 2)
        self.assertEqual(f["open"], ["", None])
        self.assertIn("Oct 21", f["sum"][1])
        self.assertIn("The first look at both versions.", f["text"])

    def test_with_none_the_section_stays_hidden(self):
        p = payload()
        f = self.go(p, dict(reviews_body(p, 1), deep_reviews=[]))
        self.assertTrue(f["record-deep-section"])
        self.assertEqual(f["n"], 0)
        f = self.go(p, reviews_body(p, 1))                                                      # a server from before the Deep review
        self.assertTrue(f["record-deep-section"])

    def test_a_visitor_to_a_member_hound_sees_none(self):
        p = payload()
        f = self.go(p, {"visible": False, "reviews": {}, "deep_reviews": []})
        self.assertTrue(f["record-deep-section"])
        self.assertEqual(f["n"], 0)

    def test_a_deep_review_with_no_bet_reviews_still_shows(self):
        p = payload()
        f = self.go(p, {"visible": True, "reviews": {}, "deep_reviews": [deep()]})
        self.assertFalse(f["record-deep-section"])
        self.assertEqual((f["n"], f["reviews"]), (1, 0))

    def test_a_single_version_hound_says_nothing_about_versions(self):
        p = payload()
        f = self.go(p, {"visible": True, "reviews": {}, "deep_reviews": [deep(versions=1, by_version=[deep()["by_version"][1]])]})
        self.assertEqual(f["basis"], ["Rests on 24 settled bets: 11-12-1."])
        self.assertNotIn("By version:", f["text"])

    def test_the_words_are_drawn_as_text_never_as_markup(self):
        p = payload()
        f = self.go(p, {"visible": True, "reviews": {}, "deep_reviews": [deep(headline="<img src=x onerror=alert(1)> It lost more than it won.")]})
        self.assertIn("<img src=x onerror=alert(1)>", f["text"])
        self.assertEqual(f["n"], 1)

    def test_a_server_that_fails_changes_nothing(self):
        p = payload()
        out = run_page("record", search="?id=u-1", routes={"/hounds/u-1/record": [200, p], "/hounds/u-1/postmortems": [500, {}]}, tz="UTC",
                       settleMs=250, queries=[hook("record-deep-section", mode="hidden"), q("n", "[data-hook='deep-review']", "count")])
        self.assertEqual((out["final"]["record-deep-section"], out["final"]["n"]), (True, 0))


class TheCopy(unittest.TestCase):
    def test_no_banned_word_in_the_new_script_or_the_records_new_markup(self):
        js = (WEB / "js" / "record-postmortems.js").read_text(encoding="utf-8")
        strings = " ".join(re.findall(r'"([^"\n]{4,})"', js) + re.findall(r"`([^`\n]{4,})`", js))
        self.assertIsNone(BANNED.search(strings), BANNED.search(strings))
        html = (WEB / "record.html").read_text(encoding="utf-8")
        self.assertIn('data-hook="record-export"', html)

    def test_the_review_is_always_labelled_as_hindsight(self):
        js = (WEB / "js" / "record-postmortems.js").read_text(encoding="utf-8")
        self.assertIn('REVIEW_LABEL = "Hindsight review"', js)
        self.assertIn("Written after the result", js)
        self.assertIn('EXPORT_TEXT = "Download bets (spreadsheet)"', js)

    def test_the_stylesheet_additions_stay_scoped_to_the_record_page(self):
        css = (WEB / "css" / "record.css").read_text(encoding="utf-8")
        for line in re.findall(r"^[^/\n{}]*\{", css, flags=re.M):
            sel = line.strip().rstrip("{").strip()
            if sel and not sel.startswith("@") and not sel.startswith("*"):
                self.assertRegex(sel, r"\.rc-|\.hounds-page \.rc-wrap", sel)
        self.assertIn(".rc-review", css)
        self.assertIn(".rc-export", css)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def test_safe_url_and_the_who_sees_it_rule(self):
        out = run_js("""
import { safeUrl, canExport, exportHref, fileNameOf } from "./record-postmortems.js";
console.log(JSON.stringify({
  ok: safeUrl("https://example.com/a?b=1"), http: safeUrl("http://example.com"), js: safeUrl("javascript:alert(1)"),
  data: safeUrl("data:text/html,x"), space: safeUrl("https://exa mple.com"), empty: safeUrl(""),
  house: canExport({ is_house: true }, false), owner: canExport({ is_house: false }, true), visitor: canExport({ is_house: false }, false),
  none: canExport(null, true), href: exportHref("u 1/x"), name: fileNameOf("../a b", "csv")
}));
""")
        self.assertEqual(out["ok"], "https://example.com/a?b=1")
        self.assertEqual(out["http"], "http://example.com")
        self.assertEqual((out["js"], out["data"], out["space"], out["empty"]), ("", "", "", ""))
        self.assertEqual((out["house"], out["owner"], out["visitor"], out["none"]), (True, True, False, False))
        self.assertEqual(out["href"], "/hounds/u%201%2Fx/export?format=csv")
        self.assertNotIn("/", out["name"])
        self.assertNotIn(" ", out["name"])


if __name__ == "__main__":
    unittest.main()
