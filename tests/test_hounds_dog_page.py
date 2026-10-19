"""The model page's rule, coach panel, follow / share / card, run for real under node against the page's own
HTML: web/hound.html with web/js/hounds-detail.js and its helper modules. Same harness as
tests/test_hounds_web_pages.py (tests/hounds_web_harness.mjs).

(The old "Today's action", proof-of-timing and kennel "My dogs" tests moved to tests/test_hounds_board_pages.py when
the pages became the model leaderboard and the model page, 2026-10-19.)

Skipped when node is not installed. Times are made relative to the real clock (the page asks the browser for
"now"), and the time zone is pinned to UTC so a "7:05 PM" in a test is the same on every machine.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timedelta, timezone

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

HOUND_HTML = (WEB / "hound.html").read_text(encoding="utf-8")
FOLLOW_KEY = "linehound.followed_dogs"
TRIGGER = "the market moves toward one side between the open and bet time"


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def dials_fixture(n=2):
    base = [
        {"name": "MOVE", "label": "Steam needed", "kind": "float", "min": 0.02, "max": 0.05, "step": 0.005,
         "default": 0.03, "current": 0.03, "scale": 100.0, "unit": "points", "text": "3 points"},
        {"name": "GAP", "label": "Gap over the market needed", "kind": "float", "min": 0.015, "max": 0.04,
         "step": 0.005, "default": 0.02, "current": 0.02, "scale": 100.0, "unit": "points", "text": "2 points"},
        {"name": "MIN_BOOKS", "label": "Books quoting before it trusts a price", "kind": "int", "min": 3, "max": 8,
         "step": 1, "default": 5, "current": 5, "scale": 1.0, "unit": "books", "text": "5 books"},
    ]
    return base[:n]


def rulebook(dials=None, last=None, tunable=True):
    return {"hound_id": "closer", "rule_text": "x", "trigger": TRIGGER, "tunable": tunable and bool(dials),
            "dials": dials or [], "champion_version": 2 if last else 1, "last_changed": last,
            "only_the_referee": "Only the referee can change a dog.", "paper_only": True}


def bet(now, *, minutes=60, result=None, hours_ago=None, recorded_before=90, segment="forward", n=1, **extra):
    """A bet row whose game starts `minutes` from now (negative: already started)."""
    start = now + timedelta(minutes=minutes)
    row = {"hound_id": "closer", "date": now.date().isoformat(), "game": f"NYY at BOS #{n}", "market": "moneyline",
           "selection": f"Pick {n}", "price": -110, "price_average": -115, "book": "bookA", "result": result,
           "units": None, "who_decided": "rule", "reason": f"Because of reason {n}.", "segment": segment,
           "start_utc": iso(start), "recorded_utc": iso(start - timedelta(minutes=recorded_before))}
    row.update(extra)
    return row


def bets_page(rows):
    return {"items": rows, "page": 1, "page_size": 25, "total": len(rows), "pages": 1, "paper_only": True,
            "not_advice": "x", "hound_id": "closer", "as_of": F.AS_OF}


@unittest.skipUnless(HAS_NODE, "node not installed")
class DogPageCase(unittest.TestCase):
    def page(self, rows=None, rb=None, hid="closer", stored=None, **kw):
        r = {k: list(v) for k, v in F.routes(True, 45).items()}
        r["/hounds/series"] = [200, F.series([hid], True)]
        detail = F.detail(hid, True, 45)
        if rows is not None:
            detail["bets"] = bets_page(rows)
            r[f"/hounds/{hid}/bets"] = [200, bets_page(rows)]
        r[f"/hounds/{hid}"] = [200, detail]
        r[f"/hounds/{hid}/rulebook"] = [200, rb] if rb is not None else [404, {"detail": "no"}]
        r[f"/hounds/{hid}/tips"] = [200, {"hound_id": hid, "count": 0, "tips": [], "note": "n"}]
        r.update(kw.pop("routes", {}))
        return run_page("hound", routes=r, search=f"?id={hid}", tz="UTC", stored=stored or {}, **kw)

    def now(self):
        return datetime.now(timezone.utc)


class TheRulebook(DogPageCase):
    def test_the_rulebook_is_open_with_the_rule_then_the_dials_in_plain_words(self):
        rb = rulebook(dials_fixture(2))
        out = self.page([], rb, queries=[
            q("title", "#rule-h"), q("rule", "[data-hook='rule-text']"), q("trigger", "[data-hook='rule-trigger']"),
            q("dials", "[data-hook='dials-list'] li", "texts"), q("last", "[data-hook='dials-last-changed']"),
            q("rules", "[data-hook='rule-text']", "count")])
        f = out["final"]
        self.assertEqual(f["title"], "Rule")
        self.assertEqual(f["rules"], 1)
        self.assertEqual(f["trigger"], f"This model bets when {TRIGGER}.")
        self.assertEqual(f["dials"], ["Steam needed: 3 points", "Gap over the market needed: 2 points"])
        self.assertEqual(f["last"], "Last changed: never. It is still on its starting numbers.")

    def test_after_a_promotion_it_names_the_version_the_day_and_the_referee(self):
        rb = rulebook(dials_fixture(1), last={"version": 2, "utc": "2026-10-12T15:00:00Z", "by": "the referee"})
        rb["dials"][0].update(current=0.04, text="4 points")
        out = self.page([], rb, queries=[q("last", "[data-hook='dials-last-changed']"),
                                         q("dial", "[data-hook='dials-list'] li")])
        self.assertEqual(out["final"]["last"], "Last changed: v2 on Oct 12 by the referee.")
        self.assertEqual(out["final"]["dial"], "Steam needed: 4 points")

    def test_a_dog_without_dials_says_its_rule_is_fixed_and_offers_no_coach_panel(self):
        out = self.page([], rulebook(None, tunable=False), queries=[
            q("none", "[data-hook='no-dials']"), q("coach_hidden", "[data-hook='hound-coach-section']", "hidden"),
            q("sliders", "[data-hook='coach-range']", "count")])
        self.assertIn("No dials on this model", out["final"]["none"])
        self.assertTrue(out["final"]["coach_hidden"])
        self.assertEqual(out["final"]["sliders"], 0)

    def test_a_rulebook_that_will_not_load_leaves_the_rule_and_says_so(self):
        out = self.page([], None, queries=[q("rule", "[data-hook='rule-text']"),
                                           q("down", "[data-hook='dials-unavailable']")])
        self.assertTrue(out["final"]["rule"])
        self.assertIn("dials did not load", out["final"]["down"])


class CoachThisDog(DogPageCase):
    def sliders(self, out_kind="attrs", attr="step"):
        return q("sliders", "[data-hook='coach-range']", out_kind, attr=attr)

    def test_one_slider_per_dial_on_the_dials_own_grid_with_the_current_value_marked(self):
        out = self.page([], rulebook(dials_fixture(3)), queries=[
            q("shown", "[data-hook='hound-coach-section']", "hidden"),
            q("steps", "[data-hook='coach-range']", "attrs", attr="step"),
            q("mins", "[data-hook='coach-range']", "attrs", attr="min"),
            q("maxes", "[data-hook='coach-range']", "attrs", attr="max"),
            q("values", "[data-hook='coach-range']", "attrs", attr="value"),
            q("now", "[data-hook='coach-current']", "texts"), q("shown_values", "[data-hook='coach-value']", "texts"),
            q("promise", "[data-hook='coach-promise']"), q("title", "#coach-h"),
            q("tips", "[data-hook='tips-count']")])
        f = out["final"]
        self.assertFalse(f["shown"])
        self.assertEqual(f["title"], "Coach this model")
        self.assertEqual(f["steps"], ["0.005", "0.005", "1"])
        self.assertEqual(f["mins"], ["0.02", "0.015", "3"])
        self.assertEqual(f["maxes"], ["0.05", "0.04", "8"])
        self.assertEqual(f["values"], ["0.03", "0.02", "5"])
        self.assertEqual(f["now"], ["this is where it is now"] * 3)
        self.assertEqual(f["shown_values"], ["3 points", "2 points", "5 books"])
        self.assertEqual(f["promise"], "Tips are graded like the AI coach's. Only the referee can change a model.")
        self.assertEqual(f["tips"], "Fan tips: 0. Grades coming from the coach report card.")

    def test_steppers_walk_the_grid_and_stop_at_the_bounds(self):
        acts = [dict(do="click", sel="[data-hook='coach-inc']", index=0) for _ in range(6)]
        out = self.page([], rulebook(dials_fixture(1)), actions=acts + [
            dict(do="click", sel="[data-hook='coach-dec']", index=0, label="down", capture=[
                q("v", "[data-hook='coach-value']")])],
            queries=[q("value", "[data-hook='coach-value']"), q("send", "[data-hook='coach-send']", "disabled")])
        self.assertEqual(out["final"]["value"], "4.5 points")             # 5 up-steps hit the 0.05 cap, one step down
        self.assertEqual(out["captures"]["down"]["v"], "4.5 points")
        self.assertFalse(out["final"]["send"])

    def test_a_slider_value_off_the_grid_snaps_onto_it(self):
        out = self.page([], rulebook(dials_fixture(1)), actions=[
            dict(do="set", sel="[data-hook='coach-range']", value="0.0437")],
            queries=[q("value", "[data-hook='coach-value']"), q("now", "[data-hook='coach-current']")])
        self.assertEqual(out["final"]["value"], "4.5 points")
        self.assertEqual(out["final"]["now"], "now 3 points")

    def test_at_most_two_dials_can_be_changed(self):
        acts = [dict(do="click", sel="[data-hook='coach-inc']", index=i) for i in range(3)]
        out = self.page([], rulebook(dials_fixture(3)), actions=acts, queries=[
            q("changed", "[data-dial]", "attrs", attr="data-changed"), q("status", "[data-hook='coach-status']"),
            q("count", "[data-hook='coach-count']")])
        changed = [c for c in out["final"]["changed"] if c in ("true", "false")]
        self.assertEqual(changed.count("true"), 2)
        self.assertIn("Two dials at most", out["final"]["status"])
        self.assertEqual(out["final"]["count"], "2 of 2 dials changed.")

    def test_send_posts_only_the_changed_dials_and_a_clean_nickname_then_clears_the_form(self):
        tip_ok = [200, {"tip": {"id": "tip_1"}, "note": "n"}]
        out = self.page([], rulebook(dials_fixture(2)), routes={"POST /hounds/closer/tips": tip_ok}, actions=[
            dict(do="click", sel="[data-hook='coach-inc']", index=0),
            dict(do="set", sel="[data-hook='coach-nick']", value="  Big   Dave 7 "),
            dict(do="click", sel="[data-hook='coach-send']", label="sent", capture=[q("status", "[data-hook='coach-status']")])],
            queries=[q("value", "[data-hook='coach-value']", "texts"), q("send", "[data-hook='coach-send']", "disabled")])
        (post,) = out["posts"]
        self.assertEqual(post["url"], "/hounds/closer/tips")
        self.assertEqual(post["body"], {"values": {"MOVE": 0.035}, "nickname": "Big Dave 7"})
        self.assertIn("Tip sent", out["captures"]["sent"]["status"])
        self.assertIn("stays exactly as it was", out["captures"]["sent"]["status"])
        self.assertEqual(out["final"]["value"][0], "3 points")             # back to where the dog is
        self.assertTrue(out["final"]["send"])

    def test_a_bad_nickname_stops_before_anything_is_sent(self):
        for nick in ("dave!", "x" * 21, "<b>"):
            out = self.page([], rulebook(dials_fixture(1)), actions=[
                dict(do="click", sel="[data-hook='coach-inc']", index=0),
                dict(do="set", sel="[data-hook='coach-nick']", value=nick),
                dict(do="click", sel="[data-hook='coach-send']")],
                queries=[q("status", "[data-hook='coach-status']")])
            self.assertEqual(out["posts"], [], nick)
            self.assertRegex(out["final"]["status"], r"nickname", nick)

    def test_the_servers_refusal_is_shown_in_its_own_words(self):
        refuse = [429, {"detail": {"error": "rate_limited", "message": "that's 3 tips today. Come back tomorrow."}}]
        out = self.page([], rulebook(dials_fixture(1)), routes={"POST /hounds/closer/tips": refuse}, actions=[
            dict(do="click", sel="[data-hook='coach-inc']", index=0), dict(do="click", sel="[data-hook='coach-send']")],
            queries=[q("status", "[data-hook='coach-status']")])
        self.assertEqual(out["final"]["status"], "that's 3 tips today. Come back tomorrow.")

    def test_the_tip_count_and_latest_tips_sit_under_the_panel(self):
        tips = {"hound_id": "closer", "count": 7, "note": "n", "tips": [
            {"id": "tip_9", "values": {"MOVE": 0.04}, "nickname": "Ann", "created_utc": "2026-10-18T10:00:00Z"},
            {"id": "tip_8", "values": {"MOVE": 0.025}, "nickname": None, "created_utc": "2026-10-18T09:00:00Z"}]}
        out = self.page([], rulebook(dials_fixture(1)), routes={"/hounds/closer/tips": [200, tips]}, queries=[
            q("count", "[data-hook='tips-count']"), q("list", "[data-hook='tips-list'] li", "texts")])
        self.assertEqual(out["final"]["count"], "Fan tips: 7. Grades coming from the coach report card.")
        self.assertEqual(out["final"]["list"], ["Ann: Steam needed 4 points", "A fan: Steam needed 2.5 points"])


class FollowShareAndCard(DogPageCase):
    def test_following_saves_to_this_browser_and_the_button_remembers(self):
        out = self.page([], rulebook(), actions=[
            dict(do="click", sel="[data-hook='follow-btn']", label="on", capture=[q("btn", "[data-hook='follow-btn']"),
                                                                                  q("status", "[data-hook='action-status']")])])
        self.assertEqual(json.loads(out["storedAfter"][FOLLOW_KEY]), ["closer"])
        self.assertEqual(out["captures"]["on"]["btn"], "Following")
        self.assertIn("My models", out["captures"]["on"]["status"])
        again = self.page([], rulebook(), stored={FOLLOW_KEY: json.dumps(["closer", "rusty"])},
                          queries=[q("btn", "[data-hook='follow-btn']"),
                                   q("pressed", "[data-hook='follow-btn']", "attr", attr="aria-pressed")],
                          actions=[dict(do="click", sel="[data-hook='follow-btn']", label="off")])
        self.assertEqual(again["final"]["btn"], "Follow")                # the click unfollowed it
        self.assertEqual(json.loads(again["storedAfter"][FOLLOW_KEY]), ["rusty"])

    def test_storage_that_throws_never_breaks_the_page_and_the_star_still_works_for_the_visit(self):
        for mode in ("methods", "accessor"):
            out = self.page([], rulebook(), storageThrows=mode, actions=[
                dict(do="click", sel="[data-hook='follow-btn']", label="on",
                     capture=[q("btn", "[data-hook='follow-btn']"), q("status", "[data-hook='action-status']")])],
                queries=[q("name", "[data-hook='hound-name']")])
            self.assertEqual(out["final"]["name"], "Closer", mode)
            self.assertEqual(out["captures"]["on"]["btn"], "Following", mode)
            self.assertIn("will not remember", out["captures"]["on"]["status"], mode)

    def test_junk_in_storage_is_ignored(self):
        for junk in ("{not json", json.dumps({"a": 1}), json.dumps([1, None, "closer"])):
            out = self.page([], rulebook(), stored={FOLLOW_KEY: junk}, queries=[q("btn", "[data-hook='follow-btn']")])
            self.assertEqual(out["final"]["btn"], "Following" if "closer" in junk else "Follow", junk)

    def test_share_uses_the_native_sheet_with_the_slash_d_link(self):
        out = self.page([], rulebook(), share=True, actions=[dict(do="click", sel="[data-hook='share-btn']")])
        (shared,) = out["shares"]
        self.assertEqual(shared["url"], "https://linehound.test/d/closer")
        self.assertEqual(shared["title"], "Closer | LineHound")
        self.assertIn("Paper bets only, not advice, 21+", shared["text"])
        self.assertEqual(out["clipboard"], [])

    def test_without_a_share_sheet_the_link_is_copied_and_a_toast_says_so(self):
        out = self.page([], rulebook(), actions=[dict(do="click", sel="[data-hook='share-btn']")],
                        queries=[q("toast", "[data-hook='toast']")])
        self.assertEqual(out["clipboard"], ["https://linehound.test/d/closer"])
        self.assertEqual(out["final"]["toast"], "Link copied. Paste it anywhere.")

    def test_a_cancelled_share_sheet_is_not_an_error_and_a_broken_one_falls_back_to_copying(self):
        cancelled = self.page([], rulebook(), share=True, shareFails="AbortError",
                              actions=[dict(do="click", sel="[data-hook='share-btn']")],
                              queries=[q("toast", "[data-hook='toast']", "count")])
        self.assertEqual((cancelled["clipboard"], cancelled["final"]["toast"]), ([], 0))
        broken = self.page([], rulebook(), share=True, shareFails="NotAllowedError",
                           actions=[dict(do="click", sel="[data-hook='share-btn']")])
        self.assertEqual(broken["clipboard"], ["https://linehound.test/d/closer"])

    def test_a_blocked_clipboard_still_shows_the_link(self):
        out = self.page([], rulebook(), clipboardFails=True, actions=[dict(do="click", sel="[data-hook='share-btn']")],
                        queries=[q("toast", "[data-hook='toast']")])
        self.assertIn("Couldn't copy. The link is https://linehound.test/d/closer", out["final"]["toast"])

    def test_download_card_draws_a_1200_by_630_png_with_the_model_and_the_hard_lines(self):
        out = self.page([], rulebook(), actions=[dict(do="click", sel="[data-hook='card-btn']", wait=200)])
        (canvas,) = out["canvases"]
        self.assertEqual((canvas["w"], canvas["h"]), (1200, 630))
        text = " | ".join(canvas["texts"])
        self.assertIn("Closer", canvas["texts"])
        self.assertIn("“I was here first.”", canvas["texts"])
        self.assertIn("Paper bets only · 21+ · linehound.app", canvas["texts"])
        self.assertRegex(text, r"\d+-\d+")                                 # the season W-L
        self.assertRegex(text, r"[+-]\d+\.\d\du paper")                    # paper units
        self.assertRegex(text, r"[WL]\d")                                  # the streak
        self.assertRegex(text, r"(Beating the close|Market|Paying the vig|Not enough bets|Not graded vs close)")   # the status
        self.assertEqual(canvas["images"], 1)                              # the initials badge
        self.assertEqual(out["downloads"], [{"href": "blob:fake", "download": "closer-linehound.png"}])

    def test_the_words_these_modules_put_on_the_page_use_no_claim_words(self):
        for name in ("hounds-board.js", "hounds-tickets.js", "hounds-rulebook.js", "hounds-share.js", "hounds-follow.js"):
            text = (WEB / "js" / name).read_text(encoding="utf-8")
            pairs = re.findall(r'"([^"\n]{3,})"|`([^`\n]{3,})`', text)
            literals = " ".join(x or y for x, y in pairs)
            self.assertGreater(len(pairs), 5, name)
            self.assertIsNone(re.search(r"(?i)\block\b|guarantee|can'?t lose|sure thing|free money|\bedge\b|\bprofit",
                                        literals), name)
