"""The Analyze report, wired into My Kennel (web/js/kennel.js; the report itself is tests/test_analyze_report_web.py).

  MOUNT    the studio's Overview reads GET /hounds/{id}/report ONCE per open (not once per tab switch; a reopen reads it again) and
           draws it in the studio-analyze slot; a house hound's kit is not "user", so its slot stays hidden and the route is never asked.
  BUTTONS  an "Analyze" button on each hound card and an "Analyze" entry in the header's ... menu open the studio on Overview and bring the
           report into view; the card keeps its four other buttons.
  EXPAND   the report's "Review this change" announces "linehound:analyze-expand"; the page starts the existing retune review with the idea's
           words (POST .../train/propose, origin "chat"). It never applies anything: no POST to /train happens without the owner's Apply.
           An idea with no text in the event is looked up in the report that was mounted; "Start a copy" is a link to the builder, not a retune.

The pages run for real under node against the fake DOM of tests/hounds_web_harness.mjs (skipped without node). The report is a real one built
by src/hounds/analyze_report.py (tests/test_analyze_report_web.py).
"""

from __future__ import annotations

import re
import unittest

from tests import test_hounds_rites_web as rites_web
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_analyze_report_web import report
from tests.test_kennel_page import SIGNED, dog, kit, q

REPORT_URL = "/hounds/u-1/report"
OPEN = dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=400)
CLOSE = dict(do="click", sel="[data-hook='studio-close']", wait=100)
SELECTED = q("selected", "[role='tab'][aria-selected='true']", "texts")
EXPAND_EVENT = "linehound:analyze-expand"
FOUR = ["Unleash", "Send to training", "Edit", "Take them out back"]


def reports(gets):
    return [u for u in gets if u.split("?")[0] == REPORT_URL]


def proposals(out):
    return [p for p in out["posts"] if p["url"] == "/hounds/u-1/train/propose"]


class Wire:
    """The kennel page with a report route (the real report as the server sends it to the owner of a paid plan)."""

    REPORT = report(full=True, owner=True)
    ITEMS = REPORT["expand"]["items"]

    def page(self, kit_over=None, extra=None, **kw):
        routes = rites_web.kennel_routes(kw.pop("dogs", None) or [dog("u-1", "Hockey Chief")])
        routes[REPORT_URL] = [200, self.REPORT]
        routes["/hounds/u-1/kit"] = [200, kit("u-1", **(kit_over or {}))]
        routes.update(extra or {})
        kw.setdefault("settleMs", 200)
        return run_page("kennel", routes=routes, **SIGNED, reducedMotion=True, tz="UTC", **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class OverviewMountsTheReportOncePerOpen(Wire, unittest.TestCase):
    def test_opening_the_studio_reads_the_report_once_and_draws_it_in_the_slot(self):
        out = self.page(actions=[dict(OPEN, capture=[
            q("hidden", "[data-hook='studio-analyze']", "hidden"), q("drawn", "[data-hook='studio-analyze'] [data-hook='analyze-report']", "count"),
            q("tier", "[data-hook='studio-analyze'] [data-hook='analyze-report']", "attr", attr="data-tier"),
            q("dog", "[data-hook='analyze-report']", "attr", attr="data-dog"), q("buttons", "[data-hook='analyze-expand-go']", "count")])])
        c = out["captures"]["open"]
        self.assertEqual((c["hidden"], c["drawn"], c["tier"], c["dog"]), (False, 1, "full", "u-1"))
        self.assertEqual(c["buttons"], len(self.ITEMS))
        self.assertEqual(len(reports(out["gets"])), 1)

    def test_switching_tabs_does_not_read_it_again_but_closing_and_reopening_does(self):
        def tab(name, **kw):
            return dict(do="click", sel=f"[role='tab'][data-tab='{name}']", wait=300, **kw)
        out = self.page(actions=[OPEN, tab("rules"), tab("coach"), tab("overview", label="back", capture=[
            SELECTED, q("drawn", "[data-hook='analyze-report']", "count")])])
        self.assertEqual(out["captures"]["back"]["selected"], ["Overview"])
        self.assertEqual(out["captures"]["back"]["drawn"], 1)
        self.assertEqual(len(reports(out["gets"])), 1, "three tab switches, one read")
        again = self.page(actions=[OPEN, CLOSE, dict(OPEN, label="second", capture=[q("drawn", "[data-hook='analyze-report']", "count")])])
        self.assertEqual(len(reports(again["gets"])), 2, "a reopen is a new open")
        self.assertEqual(again["captures"]["second"]["drawn"], 1)

    def test_a_house_hounds_slot_stays_hidden_and_the_route_is_never_asked(self):
        out = self.page(kit_over={"kind": "house", "is_owner": False}, actions=[dict(OPEN, capture=[
            q("hidden", "[data-hook='studio-analyze']", "hidden"), q("drawn", "[data-hook='analyze-report']", "count")])])
        self.assertEqual((out["captures"]["open"]["hidden"], out["captures"]["open"]["drawn"]), (True, 0))
        self.assertEqual(reports(out["gets"]), [])

    def test_a_failed_read_shows_the_reports_own_error_and_retry_not_a_blank(self):
        refusal = [503, {"detail": {"error": "warming_up", "message": "The record is still being worked out. Try again in a few seconds."}}]
        out = self.page(extra={REPORT_URL: refusal}, actions=[dict(OPEN, capture=[
            q("error", "[data-hook='analyze-error']"), q("retry", "[data-hook='analyze-retry']", "count"), q("hidden", "[data-hook='studio-analyze']", "hidden")])])
        c = out["captures"]["open"]
        self.assertFalse(c["hidden"])
        self.assertIn("still being worked out", c["error"])
        self.assertEqual(c["retry"], 1)

    def test_a_report_for_a_hound_the_studio_has_moved_on_from_is_not_drawn(self):
        dogs = [dog("u-1", "Hockey Chief"), dog("u-2", "Second Dog")]
        out = self.page(dogs=dogs, extra={"/hounds/u-2/kit": [200, kit("u-2")], "/hounds/u-2/report": [200, report(full=False, owner=True)]},
                        delay={REPORT_URL: 600}, actions=[
                            dict(OPEN, wait=50), CLOSE,
                            dict(do="click", sel="[data-hook='dog-avatar']", index=1, label="second", wait=1000, capture=[
                                q("dog", "[data-hook='analyze-report']", "attr", attr="data-dog"), q("drawn", "[data-hook='analyze-report']", "count")])])
        self.assertEqual((out["captures"]["second"]["drawn"], out["captures"]["second"]["dog"]), (1, "u-2"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class AnalyzeButtons(Wire, unittest.TestCase):
    def test_each_card_has_an_analyze_button_after_its_four_others(self):
        out = self.page(dogs=[dog("u-1", "Hockey Chief"), dog("u-2", "Second Dog")], queries=[
            q("actions", "[data-hook='kennel-dog'] .kn-act", "texts"), q("analyze", "[data-hook='dog-action-analyze']", "count"),
            q("aria", "[data-hook='dog-action-analyze']", "attrs", attr="aria-label"), q("wide", ".kn-act--wide", "count")])
        f = out["final"]
        self.assertEqual(f["actions"], (FOUR + ["Analyze"]) * 2)
        self.assertEqual((f["analyze"], f["wide"]), (2, 2))
        self.assertEqual(f["aria"], ["Analyze Hockey Chief", "Analyze Second Dog"])

    def test_the_cards_analyze_opens_overview_and_brings_the_report_into_view(self):
        out = self.page(actions=[dict(do="click", sel="[data-hook='dog-action-analyze']", label="go", wait=700, capture=[
            SELECTED, q("hidden", "[data-hook='studio']", "hidden"), q("drawn", "[data-hook='analyze-report']", "count")])])
        c = out["captures"]["go"]
        self.assertEqual((c["selected"], c["hidden"], c["drawn"]), (["Overview"], False, 1))
        self.assertIn("studio-analyze", out["scrolls"])
        self.assertEqual(len(reports(out["gets"])), 1)

    def test_opening_the_studio_by_the_picture_does_not_scroll_to_the_report(self):
        out = self.page(actions=[dict(OPEN, wait=700)])
        self.assertNotIn("studio-analyze", out["scrolls"])

    def test_the_header_menu_has_analyze_and_it_switches_to_overview_without_reading_the_report_again(self):
        coach = dict(do="click", sel="[role='tab'][data-tab='coach']", wait=300)
        menu = dict(do="click", sel="[data-hook='studio-more']", wait=80, label="menu", capture=[
            q("item", "[data-hook='studio-analyze-open']"), q("hidden", "[data-hook='studio-menu']", "hidden")])
        go = dict(do="click", sel="[data-hook='studio-analyze-open']", label="go", wait=500, capture=[SELECTED, q("menu", "[data-hook='studio-menu']", "hidden")])
        out = self.page(actions=[OPEN, coach, menu, go])
        self.assertEqual(out["captures"]["menu"]["item"], "Analyze")
        self.assertFalse(out["captures"]["menu"]["hidden"])
        self.assertEqual(out["captures"]["go"]["selected"], ["Overview"])
        self.assertTrue(out["captures"]["go"]["menu"], "the menu closes")
        self.assertIn("studio-analyze", out["scrolls"])
        self.assertEqual(len(reports(out["gets"])), 1)

    def test_a_house_hounds_analyze_has_nothing_to_show_and_scrolls_nowhere(self):
        out = self.page(kit_over={"kind": "house", "is_owner": False}, actions=[dict(do="click", sel="[data-hook='dog-action-analyze']", wait=500)])
        self.assertNotIn("studio-analyze", out["scrolls"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class ExpandStartsTheReview(Wire, unittest.TestCase):
    def fire(self, detail, **kw):
        return self.page(actions=[OPEN, dict(do="window_event", type=EXPAND_EVENT, detail=detail, label="expand", wait=500, capture=[
            q("sheet", ".rt-sheet", "attr", attr="data-hook"), q("title", "[data-hook='rites-title']")])], **kw)

    def test_the_ideas_own_text_is_the_owners_words_in_the_proposal_request(self):
        item = self.ITEMS[0]
        out = self.fire({"dogId": "u-1", "id": item["id"], "text": item["text"]})
        self.assertEqual([p["body"] for p in proposals(out)], [{"origin": "chat", "chat": [item["text"]]}])
        self.assertEqual(out["captures"]["expand"]["title"], "Retune Hockey Chief?")
        self.assertEqual([p for p in out["posts"] if p["url"] == "/hounds/u-1/train"], [], "nothing is applied without the owner's Apply")

    def test_an_event_without_text_is_answered_from_the_report_that_was_mounted(self):
        item = self.ITEMS[0]
        out = self.fire({"dogId": "u-1", "id": item["id"]})
        self.assertEqual([p["body"] for p in proposals(out)], [{"origin": "chat", "chat": [item["text"]]}])

    def test_every_real_idea_resolves_to_its_own_words(self):
        ideas = [i for i in self.ITEMS if i["id"] != "spin_off"]
        self.assertTrue(ideas)
        for item in ideas:
            with self.subTest(idea=item["id"]):
                out = self.fire({"dogId": "u-1", "id": item["id"]})
                self.assertEqual([p["body"]["chat"] for p in proposals(out)], [[item["text"]]])

    def test_an_idea_nobody_can_find_starts_nothing(self):
        out = self.fire({"dogId": "u-1", "id": "no_such_idea"})
        self.assertEqual(proposals(out), [])
        self.assertIsNone(out["captures"]["expand"]["sheet"])

    def test_an_event_for_another_hound_is_ignored(self):
        out = self.fire({"dogId": "u-9", "id": self.ITEMS[0]["id"], "text": "Loosen it."})
        self.assertEqual(proposals(out), [])

    def test_with_the_studio_closed_nothing_starts(self):
        out = self.page(actions=[dict(do="window_event", type=EXPAND_EVENT, detail={"dogId": "u-1", "id": "x", "text": "Loosen it."}, wait=300)])
        self.assertEqual(proposals(out), [])

    def test_the_spin_off_is_followed_as_a_link_and_never_retunes_this_hound(self):
        href = "build-a-hound.html?from=u-1"
        out = self.fire({"dogId": "u-1", "id": "spin_off", "href": href, "text": "Spin off a copy and loosen the copy instead."})
        self.assertEqual(proposals(out), [])
        self.assertEqual(out["navigations"], [href])

    def test_a_link_that_leaves_the_site_is_not_followed(self):
        out = self.fire({"dogId": "u-1", "id": "spin_off", "href": "https://elsewhere.example/steal"})
        self.assertEqual((proposals(out), out["navigations"]), ([], []))


class TheMarkupAndTheCss(unittest.TestCase):
    HTML = (WEB / "kennel.html").read_text(encoding="utf-8")
    CSS = (WEB / "css" / "studio.css").read_text(encoding="utf-8")

    def test_the_header_menu_lists_analyze_first(self):
        menu = self.HTML.split('data-hook="studio-menu"')[1].split("</div>")[0]
        self.assertEqual(re.findall(r'data-hook="(studio-[a-z-]+)"', menu), ["studio-analyze-open", "studio-versions-open", "studio-outback", "studio-remove"])

    def test_analyze_takes_the_whole_row_under_the_two_by_two_grid(self):
        self.assertRegex(self.CSS, r"\.kn-act--wide \{ grid-column: 1 / -1; \}")


if __name__ == "__main__":
    unittest.main()
