"""The dog page, made watchable, transparent, showable and coachable (owner, 2026-10-18), run for real under
node against the page's own HTML: web/hound.html with web/js/hounds-detail.js and its helper modules, and the
kennel page's "My dogs" filter. Same harness as tests/test_hounds_web_pages.py (tests/hounds_web_harness.mjs).

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


class TodaysAction(DogPageCase):
    def test_every_status_has_its_chip_and_a_pick_a_price_and_a_local_time(self):
        now = self.now()
        rows = [
            bet(now, minutes=180, n=1),                                   # not started
            bet(now, minutes=-60, n=2),                                   # started, not graded
            bet(now, minutes=-400, n=3),                                  # started long ago, still not graded
            bet(now, minutes=-300, result="win", n=4),
            bet(now, minutes=-300, result="loss", n=5),
            bet(now, minutes=-300, result="push", n=6),
            bet(now, minutes=120, refused=True, n=7),
            bet(now, minutes=120, segment="replay", n=8),                 # a rehearsal row never shows
            dict(bet(now, minutes=120, n=9), date=(now - timedelta(days=3)).date().isoformat(),
                 start_utc=iso(now - timedelta(days=3))),                 # an old slate
        ]
        out = self.page(rows, rulebook(dials_fixture(1)), queries=[
            q("chips", "[data-hook='today-chip']", "texts"), q("picks", "[data-hook='today-pick-text']", "texts"),
            q("times", "[data-hook='today-time']", "texts"), q("whys", "[data-hook='today-why']", "texts"),
            q("empty", "[data-hook='today-empty']", "count"), q("title", "#today-h")])
        f = out["final"]
        self.assertEqual(f["title"], "🔴 Today's action")
        # soonest game first: the long-over one, the older start, the started one, then the future ones
        self.assertEqual(sorted(f["chips"]), sorted(["PENDING", "LIVE", "GRADING", "WON", "LOST", "PUSH", "PASSED"]))
        self.assertEqual(len(f["picks"]), 7)
        self.assertNotIn("Pick 8 at -115", f["picks"])
        self.assertNotIn("Pick 9 at -115", f["picks"])
        self.assertIn("Pick 1 at -115", f["picks"])                       # the average price is the headline price
        by = dict(zip(f["picks"], f["chips"]))
        self.assertEqual((by["Pick 1 at -115"], by["Pick 2 at -115"], by["Pick 3 at -115"], by["Pick 7 at -115"]),
                         ("PENDING", "LIVE", "GRADING", "PASSED"))
        self.assertEqual((by["Pick 4 at -115"], by["Pick 5 at -115"], by["Pick 6 at -115"]), ("WON", "LOST", "PUSH"))
        self.assertEqual(f["empty"], 0)
        self.assertIn("Why: Because of reason 1.", f["whys"])
        start = now + timedelta(minutes=180)
        hr = start.hour % 12 or 12
        self.assertIn(f"· {hr}:{start.minute:02d} {'AM' if start.hour < 12 else 'PM'}", f["times"])

    def test_no_start_time_means_pending_never_live(self):
        now = self.now()
        out = self.page([bet(now, minutes=-60, start_utc=None, recorded_utc=None)], rulebook(),
                        queries=[q("chips", "[data-hook='today-chip']", "texts")])
        self.assertEqual(out["final"]["chips"], ["PENDING"])

    def test_the_empty_state_says_when_this_dog_bets(self):
        out = self.page([], rulebook(dials_fixture(1)), queries=[q("empty", "[data-hook='today-empty']")])
        self.assertEqual(out["final"]["empty"],
                         f"No pick yet today. This dog bets when {TRIGGER}; boards refresh through the day.")

    def test_the_empty_state_still_reads_if_the_rulebook_is_down(self):
        out = self.page([], None, queries=[q("empty", "[data-hook='today-empty']")])
        self.assertEqual(out["final"]["empty"],
                         "No pick yet today. This dog bets when its rule fires on a game; boards refresh through the day.")

    def test_a_put_down_dog_has_no_picks_and_no_timer(self):
        dead = dict(F.detail("closer", True, 45), status="retired",
                    retired={"date": "2026-10-20", "cause": "retired: down more than 25 units"})
        out = self.page(None, rulebook(), routes={"/hounds/closer": [200, dead]},
                        queries=[q("empty", "[data-hook='today-empty']")])
        self.assertIn("put down", out["final"]["empty"])
        self.assertEqual(out["intervals"], [])

    def test_it_refreshes_every_sixty_seconds_while_visible_and_picks_up_new_picks(self):
        now = self.now()
        first = [bet(now, minutes=30, n=1)]
        later = [bet(now, minutes=-5, n=1), bet(now, minutes=200, n=2)]
        out = self.page(first, rulebook(), routes={"/hounds/closer/bets": [200, bets_page(later)]}, actions=[
            dict(do="fire_timers", label="tick", capture=[q("chips", "[data-hook='today-chip']", "texts")])],
            captureInitial=[q("chips", "[data-hook='today-chip']", "texts")])
        self.assertEqual(out["intervals"][:1], [60000])
        self.assertEqual(out["captures"]["initial"]["chips"], ["PENDING"])
        self.assertEqual(out["captures"]["tick"]["chips"], ["LIVE", "PENDING"])
        self.assertTrue(any(g.startswith("/hounds/closer/bets?page=1") for g in out["gets"]))

    def test_a_hidden_tab_does_not_poll_and_coming_back_refreshes_once(self):
        now = self.now()
        out = self.page([bet(now, minutes=30)], rulebook(), actions=[
            dict(do="visibility", state="hidden"), dict(do="fire_timers"), dict(do="fire_timers")])
        polls = [g for g in out["gets"] if g.startswith("/hounds/closer/bets")]
        self.assertEqual(polls, [])
        back = self.page([bet(now, minutes=30)], rulebook(), actions=[
            dict(do="visibility", state="hidden"), dict(do="visibility", state="visible")])
        self.assertEqual(len([g for g in back["gets"] if g.startswith("/hounds/closer/bets")]), 1)

    def test_a_failed_refresh_keeps_the_picks_and_says_so(self):
        now = self.now()
        out = self.page([bet(now, minutes=30)], rulebook(), failAfter={"/hounds/closer/bets": 0},
                        actions=[dict(do="fire_timers")],
                        queries=[q("chips", "[data-hook='today-chip']", "texts"), q("note", "[data-hook='today-note']")])
        self.assertEqual(out["final"]["chips"], ["PENDING"])
        self.assertIn("Couldn't refresh just now", out["final"]["note"])


class ProofOfTiming(DogPageCase):
    def test_a_bet_recorded_before_first_pitch_wears_the_on_the_record_stamp(self):
        now = self.now()
        out = self.page([bet(now, minutes=60, recorded_before=90)], rulebook(), queries=[
            q("stamp", "[data-hook='today-stamp']"), q("kind", "[data-hook='today-stamp']", "attr", attr="class"),
            q("table_stamp", "[data-hook='bet-stamp']", "texts"), q("table_why", "[data-hook='bet-why']", "texts")])
        f = out["final"]
        self.assertRegex(f["stamp"], r"^🔒 On the record before the game \(recorded [A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M\)$")
        self.assertIn("hd-pick__stamp--before", f["kind"])
        self.assertEqual(f["table_stamp"][0], f["stamp"])
        self.assertEqual(f["table_why"], ["Because of reason 1."])

    def test_a_bet_written_after_the_start_never_claims_it_was_early(self):
        now = self.now()
        out = self.page([bet(now, minutes=-30, recorded_before=-10)], rulebook(),
                        queries=[q("stamp", "[data-hook='today-stamp']")])
        self.assertNotIn("before the game", out["final"]["stamp"])
        self.assertIn("after the game started", out["final"]["stamp"])

    def test_no_write_stamp_means_no_stamp(self):
        now = self.now()
        out = self.page([bet(now, minutes=60, recorded_utc=None)], rulebook(),
                        queries=[q("stamp", "[data-hook='today-stamp']", "count"), q("cell", "[data-hook='bet-stamp']", "texts")])
        self.assertEqual(out["final"]["stamp"], 0)
        self.assertEqual(out["final"]["cell"], [""])

    def test_a_rehearsal_row_says_it_was_written_after_the_games(self):
        now = self.now()
        out = self.page([bet(now, minutes=60, segment="replay")], rulebook(),
                        queries=[q("cell", "[data-hook='bet-stamp']", "texts")])
        self.assertIn("written after the games were played", out["final"]["cell"][0])

    def test_every_bet_is_open_on_the_page_not_hidden_in_the_receipts(self):
        out = self.page(None, rulebook(), queries=[
            q("inside", "[data-hook='hound-details'] [data-hook='hound-bets']", "count"),
            q("outside", "[data-hook='hound-bets-section'] [data-hook='bets-table']", "count"),
            q("rows", "[data-hook='bets-table'] tbody tr", "count"), q("summary", "[data-hook='hound-details'] summary")])
        self.assertEqual(out["final"]["inside"], 0)
        self.assertEqual(out["final"]["outside"], 1)
        self.assertGreater(out["final"]["rows"], 0)
        self.assertNotIn("every bet", out["final"]["summary"])


class TheRulebook(DogPageCase):
    def test_the_rulebook_is_open_with_the_rule_then_the_dials_in_plain_words(self):
        rb = rulebook(dials_fixture(2))
        out = self.page([], rb, queries=[
            q("title", "#rule-h"), q("rule", "[data-hook='rule-text']"), q("trigger", "[data-hook='rule-trigger']"),
            q("dials", "[data-hook='dials-list'] li", "texts"), q("last", "[data-hook='dials-last-changed']"),
            q("in_details", "[data-hook='hound-details'] [data-hook='rule-text']", "count")])
        f = out["final"]
        self.assertEqual(f["title"], "The rulebook")
        self.assertEqual(f["in_details"], 0)
        self.assertEqual(f["trigger"], f"This dog bets when {TRIGGER}.")
        self.assertEqual(f["dials"], ["Steam needed: 3 points", "Gap over the market needed: 2 points"])
        self.assertEqual(f["last"], "Last changed: never. It's still on its starting numbers.")

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
        self.assertIn("No dials on this one", out["final"]["none"])
        self.assertTrue(out["final"]["coach_hidden"])
        self.assertEqual(out["final"]["sliders"], 0)

    def test_a_rulebook_that_will_not_load_leaves_the_rule_and_says_so(self):
        out = self.page([], None, queries=[q("rule", "[data-hook='rule-text']"),
                                           q("down", "[data-hook='dials-unavailable']")])
        self.assertTrue(out["final"]["rule"])
        self.assertIn("dials didn't load", out["final"]["down"])


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
        self.assertEqual(f["title"], "🧠 Coach this dog")
        self.assertEqual(f["steps"], ["0.005", "0.005", "1"])
        self.assertEqual(f["mins"], ["0.02", "0.015", "3"])
        self.assertEqual(f["maxes"], ["0.05", "0.04", "8"])
        self.assertEqual(f["values"], ["0.03", "0.02", "5"])
        self.assertEqual(f["now"], ["this is where it is now"] * 3)
        self.assertEqual(f["shown_values"], ["3 points", "2 points", "5 books"])
        self.assertEqual(f["promise"], "Tips are graded like the AI coach's. Only the referee can change a dog.")
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
        self.assertEqual(out["captures"]["on"]["btn"], "⭐ Following")
        self.assertIn("My dogs", out["captures"]["on"]["status"])
        again = self.page([], rulebook(), stored={FOLLOW_KEY: json.dumps(["closer", "rusty"])},
                          queries=[q("btn", "[data-hook='follow-btn']"),
                                   q("pressed", "[data-hook='follow-btn']", "attr", attr="aria-pressed")],
                          actions=[dict(do="click", sel="[data-hook='follow-btn']", label="off")])
        self.assertEqual(again["final"]["btn"], "⭐ Follow")                # the click unfollowed it
        self.assertEqual(json.loads(again["storedAfter"][FOLLOW_KEY]), ["rusty"])

    def test_storage_that_throws_never_breaks_the_page_and_the_star_still_works_for_the_visit(self):
        for mode in ("methods", "accessor"):
            out = self.page([], rulebook(), storageThrows=mode, actions=[
                dict(do="click", sel="[data-hook='follow-btn']", label="on",
                     capture=[q("btn", "[data-hook='follow-btn']"), q("status", "[data-hook='action-status']")])],
                queries=[q("name", "[data-hook='hound-name']")])
            self.assertEqual(out["final"]["name"], "Closer", mode)
            self.assertEqual(out["captures"]["on"]["btn"], "⭐ Following", mode)
            self.assertIn("won't remember", out["captures"]["on"]["status"], mode)

    def test_junk_in_storage_is_ignored(self):
        for junk in ("{not json", json.dumps({"a": 1}), json.dumps([1, None, "closer"])):
            out = self.page([], rulebook(), stored={FOLLOW_KEY: junk}, queries=[q("btn", "[data-hook='follow-btn']")])
            self.assertEqual(out["final"]["btn"], "⭐ Following" if "closer" in junk else "⭐ Follow", junk)

    def test_share_uses_the_native_sheet_with_the_slash_d_link(self):
        out = self.page([], rulebook(), share=True, actions=[dict(do="click", sel="[data-hook='share-btn']")])
        (shared,) = out["shares"]
        self.assertEqual(shared["url"], "https://linehound.test/d/closer")
        self.assertEqual(shared["title"], "Closer | LineHound Kennel")
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

    def test_download_card_draws_a_1200_by_630_png_with_the_dog_and_the_hard_lines(self):
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
        self.assertRegex(text, r"(SHARP|COIN FLIP|FEEDING THE BOOK|ROOKIE|UNRATED)")   # the badge
        self.assertEqual(canvas["images"], 1)                              # the avatar
        self.assertEqual(out["downloads"], [{"href": "blob:fake", "download": "closer-linehound.png"}])

    def test_the_words_these_modules_put_on_the_page_use_no_claim_words(self):
        for name in ("hounds-watch.js", "hounds-rulebook.js", "hounds-share.js", "hounds-follow.js"):
            text = (WEB / "js" / name).read_text(encoding="utf-8")
            pairs = re.findall(r'"([^"\n]{3,})"|`([^`\n]{3,})`', text)
            literals = " ".join(x or y for x, y in pairs)
            self.assertGreater(len(pairs), 5, name)
            self.assertIsNone(re.search(r"(?i)\block\b|guarantee|can'?t lose|sure thing|free money|\bedge\b|\bprofit",
                                        literals), name)


class TheKennelPage(unittest.TestCase):
    def kennel(self, stored=None, **kw):
        r = {k: list(v) for k, v in F.routes(True, 45).items()}
        r["/hounds/series"] = [200, F.series([h["id"] for h in F.hounds(True)], True)]
        return run_page("hounds", routes=r, stored=stored or {}, tz="UTC", **kw)

    def test_my_dogs_chip_counts_followed_dogs_and_filters_to_them(self):
        stored = {FOLLOW_KEY: json.dumps(["rusty", "moon-dog", "ghost"])}
        out = self.kennel(stored, actions=[
            dict(do="click", sel="[data-hook='hounds-filter'] [data-filter='mine']", label="mine",
                 capture=[q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound"),
                          q("pressed", "[data-hook='hounds-filter'] [data-filter='mine']", "attr", attr="aria-pressed")])],
            queries=[q("filters", "[data-hook='hounds-filter'] button", "texts")])
        self.assertEqual(out["final"]["filters"][:2], ["All (13)", "My dogs ⭐ (2)"])      # "ghost" is not a dog
        self.assertEqual(sorted(out["captures"]["mine"]["ids"]), ["moon-dog", "rusty"])
        self.assertEqual(out["captures"]["mine"]["pressed"], "true")

    def test_followed_dogs_are_pinned_on_top_and_keep_their_true_rank(self):
        plain = self.kennel(queries=[q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound"),
                                     q("ranks", "[data-hook='hounds-list'] .hd-row [data-hook='rank']", "texts")])
        order = plain["final"]["ids"]
        pick = order[-1]
        out = self.kennel({FOLLOW_KEY: json.dumps([pick])}, queries=[
            q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound"),
            q("ranks", "[data-hook='hounds-list'] .hd-row [data-hook='rank']", "texts"),
            q("star", "[data-hook='hounds-list'] .hd-row [data-hook='row-star']", "count")])
        self.assertEqual(out["final"]["ids"][0], pick)
        self.assertEqual(out["final"]["ids"][1:], order[:-1])
        self.assertEqual(out["final"]["ranks"][0], plain["final"]["ranks"][-1])    # it keeps the rank it earned
        self.assertEqual(out["final"]["star"], 1)

    def test_nobody_followed_says_how_to_follow(self):
        out = self.kennel(actions=[dict(do="click", sel="[data-hook='hounds-filter'] [data-filter='mine']")],
                          queries=[q("empty", "[data-hook='board-empty']")])
        self.assertIn("You aren't following any dogs yet", out["final"]["empty"])

    def test_storage_that_throws_leaves_the_kennel_working(self):
        for mode in ("methods", "accessor"):
            out = self.kennel(storageThrows=mode, queries=[q("n", "[data-hook='hounds-list'] .hd-row", "count")])
            self.assertGreater(out["final"]["n"], 5, mode)


if __name__ == "__main__":
    unittest.main()
