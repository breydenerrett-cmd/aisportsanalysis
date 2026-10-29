"""The hound studio, revamped (owner, 2026-10-29): a header and three tabs, a hound-level Sports row, and a live "Past 14 days" line.

  TABS         exactly Overview, Rules and Coach; every old tab name (look, fire, backtest, ask, record, versions, lessons) still lands on the
               right one, from the address and from the builder's "linehound:studio-tab" event.
  HEADER       the hound's picture opens the Look editor; Unleash, Train and a ... menu (Versions, Take them out back, Remove).
  SPORTS ROW   one chip per sport, on / mixed / off; unticking Tennis removes it from EVERY rule; the last sport cannot be unticked; a rule whose
               markets are not offered in a sport is left alone and the row says so. It is on the public builder page too.
  LIVE TEST    "Past 14 days with these rules: N bets, W-L, +x.xxu" re-runs the builder's 14 day hindsight (POST /hounds/drill with the SPEC) after
               an edit, shows a loading state, an honest "not enough games" line, and says it is a rehearsal and not a forecast.
  HOOKS        the builder keeps one hook set in both of its homes.

The pages run for real under node against the fake DOM of tests/hounds_web_harness.mjs (skipped without node).
"""

from __future__ import annotations

import json
import re
import unittest

from src.hounds import user_spec
from tests import _hounds_rules_fixtures as RF
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_kennel_page import SIGNED, TheStudio, dog, kit, mine, q


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


DRILL = "POST /hounds/drill"
PREVIEW = "POST /hounds/builder/preview"
HIND = {"label": "Backtest (hindsight, not counted in the record)", "counted": False, "days": 14, "paper_only": True,
        "record": {"bets": 23, "graded": 23, "wins": 13, "losses": 10, "pushes": 0, "pending": 0}, "units_average_price": 2.1,
        "sample_note": "23 graded bets: a small sample, so wins and losses this few are mostly luck."}
HIND_AFTER = dict(HIND, record={"bets": 9, "graded": 9, "wins": 3, "losses": 6, "pushes": 0, "pending": 0}, units_average_price=-1.4)
HIND_NONE = dict(HIND, record={"bets": 0, "graded": 0, "wins": 0, "losses": 0, "pushes": 0, "pending": 0}, units_average_price=0)


def member_dog(did="u-1", name="Hockey Chief", rules=None, version_no=1, **over):
    """A saved hound as GET /hounds/mine lists it, its spec made by the real validator."""
    d = {"id": did, "name": name, "tagline": "", "status": "running", "version_no": version_no, "color": "mint", "badge": "crown",
         "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0}, "rule_sentences": ["Bet NHL moneylines."]}
    d["spec"] = json.loads(json.dumps(user_spec.validate_spec(RF.v2(name=name, rules=rules or [RF.rule(sports=["NHL"], markets=["moneyline"])]))))
    d.update(over)
    return d


class StudioHelpers:
    MENU = TheStudio.MENU
    routes = TheStudio.routes

    def studio(self, dogs=None, mine_dogs=None, extra=None, **kw):
        """The kennel page signed in, with `dogs` on the cards and `mine_dogs` as the builder's own list."""
        routes = self.routes(dogs or [dog("u-1", "Hockey Chief")])
        routes.update({"/hounds/mine": [200, {"hounds": mine_dogs if mine_dogs is not None else [member_dog()], "limit_running": 3}],
                       PREVIEW: [200, {"qualifying": 0, "would_bet": 0, "picks": [], "sentences": ["Bet NHL moneylines."], "max_bets_per_day": 2, "paper_only": True}],
                       DRILL: [200, HIND]})
        routes.update(extra or {})
        kw.setdefault("settleMs", 200)
        return run_page("kennel", routes=routes, **SIGNED, tz="UTC", **kw)

    @staticmethod
    def previews(out):
        return [p["body"]["spec"] for p in out["posts"] if p["url"].endswith("/hounds/builder/preview")]

    @staticmethod
    def drills(out):
        return [p["body"] for p in out["posts"] if p["url"].endswith("/hounds/drill")]


EDIT = dict(do="click", sel="[data-hook='dog-action-edit']", label="edit", wait=500)


# ---------------------------------------------------------------------------------------------------
# the tab names
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class EveryOldTabNameLandsOnANewTab(unittest.TestCase):
    def test_the_mapping(self):
        out = run_js('import { studioTarget, isStudioTab, STUDIO_TABS } from "./studio-tabs.js";\n'
                     'const names = ["overview", "rules", "coach", "record", "lessons", "fire", "look", "backtest", "ask", "versions", "", "nonsense", "constructor", "__proto__"];\n'
                     'console.log(JSON.stringify({ tabs: STUDIO_TABS, got: names.map((n) => [n, studioTarget(n), isStudioTab(n)]) }));')
        self.assertEqual(out["tabs"], ["overview", "rules", "coach"])
        want = {"overview": "overview", "rules": "rules", "coach": "coach", "record": "overview", "lessons": "overview", "fire": "overview", "look": "overview",
                "backtest": "rules", "ask": "coach", "versions": "coach", "": "overview", "nonsense": "overview", "constructor": "overview", "__proto__": "overview"}
        for name, target, known in out["got"]:
            with self.subTest(tab=name):
                self.assertEqual(target["tab"], want[name])
                self.assertEqual(known, name in ("overview", "rules", "coach", "record", "lessons", "fire", "look", "backtest", "ask", "versions"))
        flags = {name: {k for k, v in target.items() if k != "tab" and v} for name, target, _ in out["got"]}
        self.assertEqual({k: v for k, v in flags.items() if v}, {"fire": {"fire"}, "look": {"look"}, "backtest": {"test"}, "versions": {"versions"}})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheAddressStillOpensTheRightTab(StudioHelpers, unittest.TestCase):
    SEL = q("selected", "[role='tab'][aria-selected='true']", "texts")

    def open_at(self, tab, **kw):
        dogs = kw.pop("dogs", None)
        return self.studio(dogs=dogs, search=f"?dog=u-1&tab={tab}", settleMs=700, queries=[
            self.SEL, q("overview", "[data-tabpanel='overview']", "hidden"), q("rules", "[data-tabpanel='rules']", "hidden"), q("coach", "[data-tabpanel='coach']", "hidden"),
            q("look_sheet", "[data-hook='studio-look-sheet']", "hidden"), q("fire_host", "[data-hook='studio-fire']", "hidden"), q("fire_btn", "[data-hook='fire-btn']", "count"),
            q("test_panel", "[data-hook='rules-full-test-panel']", "hidden"), q("versions", "[data-hook='coach-versions-title']", "count"),
            q("locker", "[data-hook='locker-preview']", "count")], **kw)

    def test_each_old_name_selects_the_tab_that_holds_it_now(self):
        cases = {"overview": "Overview", "record": "Overview", "lessons": "Overview", "fire": "Overview", "look": "Overview",
                 "rules": "Rules", "backtest": "Rules", "coach": "Coach", "ask": "Coach", "versions": "Coach"}
        for tab, label in cases.items():
            with self.subTest(tab=tab):
                self.assertEqual(self.open_at(tab)["final"]["selected"], [label])

    def test_with_no_tab_a_hound_opens_on_overview(self):
        out = self.studio(search="?dog=u-1", settleMs=500, queries=[self.SEL])
        self.assertEqual(out["final"]["selected"], ["Overview"])

    def test_look_opens_overview_with_the_look_editor_over_it(self):
        f = self.open_at("look")["final"]
        self.assertFalse(f["look_sheet"])
        self.assertEqual(f["locker"], 1)

    def test_fire_shows_the_unleash_panel_but_an_address_never_places_a_bet(self):
        out = self.open_at("fire")
        f = out["final"]
        self.assertFalse(f["fire_host"])
        self.assertEqual(f["fire_btn"], 1, "the panel is there, with its button")
        self.assertEqual([p for p in out["posts"] if p["url"].endswith("/unleash")], [], "a link must not start a hound betting")

    def test_backtest_opens_rules_with_the_full_test_open(self):
        out = self.studio(mine_dogs=[member_dog()], search="?dog=u-1&tab=backtest", settleMs=1500,
                          queries=[q("test_panel", "[data-hook='rules-full-test-panel']", "hidden"), q("expanded", "[data-hook='rules-full-test-toggle']", "attr", attr="aria-expanded")])
        self.assertFalse(out["final"]["test_panel"])
        self.assertEqual(out["final"]["expanded"], "true")
        self.assertIn({"dog_id": "u-1", "days": 7}, self.drills(out))

    def test_versions_opens_coach_with_the_versions_list_for_a_hound_past_its_first_version(self):
        from tests import test_hound_revert_web as R
        d = dog("u-1", "Hockey Chief", version_no=2)
        out = self.open_at("versions", dogs=[d], extra={"/hounds/u-1/versions": [200, R.payloads()["listed"]]})
        self.assertEqual(out["final"]["selected"], ["Coach"])
        self.assertEqual(out["final"]["versions"], 1)

    def test_the_studio_tab_event_takes_the_old_names_too(self):
        # the builder's "Backtest 30 days" / "Unleash" buttons (hounds-build.js nextStepBlock) ask the studio for a tab by event
        cases = [("backtest", "Rules"), ("ask", "Coach"), ("record", "Overview"), ("versions", "Coach"), ("rules", "Rules"), ("coach", "Coach"), ("look", "Overview")]
        for tab, label in cases:
            with self.subTest(tab=tab):
                out = self.studio(actions=[dict(do="window_event", type="linehound:studio-tab", detail={"id": "u-1", "tab": tab}, label="go", wait=500,
                                                capture=[self.SEL, q("hidden", "[data-hook='studio']", "hidden")])])
                self.assertEqual(out["captures"]["go"]["selected"], [label])
                self.assertFalse(out["captures"]["go"]["hidden"])

    def test_the_event_for_unleash_starts_the_hound_like_the_cards_button_but_an_unknown_name_does_nothing(self):
        out = self.studio(actions=[dict(do="window_event", type="linehound:studio-tab", detail={"id": "u-1", "tab": "fire"}, label="go", wait=500,
                                        capture=[self.SEL])])
        self.assertEqual(out["captures"]["go"]["selected"], ["Overview"])
        self.assertEqual(len([p for p in out["posts"] if p["url"].endswith("/unleash")]), 1)
        none = self.studio(actions=[dict(do="window_event", type="linehound:studio-tab", detail={"id": "u-1", "tab": "nonsense"}, label="go", wait=200,
                                         capture=[q("hidden", "[data-hook='studio']", "hidden")])])
        self.assertTrue(none["captures"]["go"]["hidden"])

    def test_the_cards_buttons_open_overview_and_rules(self):
        out = self.studio(actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="art", wait=300, capture=[self.SEL]),
                                   dict(do="click", sel="[data-hook='studio-close']", wait=100),
                                   dict(do="click", sel="[data-hook='dog-action-edit']", label="edit", wait=500, capture=[self.SEL])])
        self.assertEqual(out["captures"]["art"]["selected"], ["Overview"])
        self.assertEqual(out["captures"]["edit"]["selected"], ["Rules"])


# ---------------------------------------------------------------------------------------------------
# the header
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHeaderButtons(StudioHelpers, unittest.TestCase):
    OPEN = dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=250)

    def test_unleash_train_and_the_menu_are_in_the_header_and_the_pictures_a_button(self):
        out = self.studio(actions=[dict(self.OPEN, capture=[
            q("unleash", "[data-hook='studio-unleash']"), q("train", "[data-hook='studio-train']"), q("more", "[data-hook='studio-more']", "attr", attr="aria-label"),
            q("actions_hidden", "[data-hook='studio-actions']", "hidden"), q("avatar_tag", "[data-hook='studio-avatar']", "attr", attr="aria-label"),
            q("unleash_class", "[data-hook='studio-unleash']", "attr", attr="class"), q("version", "[data-hook='studio-version']"),
            q("menu_hidden", "[data-hook='studio-menu']", "hidden"), q("status", "[data-hook='studio-status']")])])
        c = out["captures"]["open"]
        self.assertEqual((c["unleash"], c["train"]), ("Unleash", "Train"))
        self.assertEqual(c["more"], "More for this hound")
        self.assertFalse(c["actions_hidden"])
        self.assertEqual(c["avatar_tag"], "Change how this hound looks")
        self.assertIn("lh-btn--solid", c["unleash_class"], "Unleash is the one primary button")
        self.assertEqual(c["version"], "v1")
        self.assertTrue(c["menu_hidden"])
        self.assertRegex(c["status"], r"^Running")

    def test_the_menu_holds_take_them_out_back_and_remove_and_versions_only_past_the_first_version(self):
        caps = [q("menu_hidden", "[data-hook='studio-menu']", "hidden"), q("versions_hidden", "[data-hook='studio-versions-open']", "hidden"),
                q("outback_hidden", "[data-hook='studio-outback']", "hidden"), q("remove_hidden", "[data-hook='studio-remove']", "hidden"),
                q("outback", "[data-hook='studio-outback']"), q("expanded", "[data-hook='studio-more']", "attr", attr="aria-expanded")]
        first = self.studio(actions=[self.OPEN, dict(do="click", sel="[data-hook='studio-more']", label="menu", wait=80, capture=caps)])
        c = first["captures"]["menu"]
        self.assertEqual((c["menu_hidden"], c["expanded"]), (False, "true"))
        self.assertEqual((c["versions_hidden"], c["outback_hidden"], c["remove_hidden"]), (True, False, False))
        self.assertEqual(c["outback"], "Take them out back")
        later = self.studio(dogs=[dog("u-1", "Hockey Chief", version_no=2)], actions=[self.OPEN, dict(do="click", sel="[data-hook='studio-more']", label="menu", wait=80, capture=caps)])
        self.assertFalse(later["captures"]["menu"]["versions_hidden"])

    def test_train_opens_the_same_training_sheet_as_the_cards_button(self):
        from tests import test_hounds_rites_web as rites
        routes = rites.kennel_routes([dog("u-1", "Hockey Chief")])
        out = run_page("kennel", routes=routes, **SIGNED, reducedMotion=True, actions=[
            self.OPEN, dict(do="click", sel="[data-hook='studio-train']", label="train", wait=200, capture=rites.sheet_caps())])
        c = out["captures"]["train"]
        self.assertEqual(c["kind"], "training-confirm")
        self.assertEqual(c["title"], "Send Hockey Chief to training?")
        self.assertEqual(out["posts"], [], "the sheet asks first: nothing is sent by the tap")

    def test_the_coach_tab_has_its_own_train_button_that_opens_the_same_sheet(self):
        from tests import test_hounds_rites_web as rites
        routes = rites.kennel_routes([dog("u-1", "Hockey Chief")])
        out = run_page("kennel", routes=routes, **SIGNED, reducedMotion=True, actions=[
            self.OPEN, dict(do="click", sel="[role='tab'][data-tab='coach']", wait=300),
            dict(do="click", sel="[data-hook='coach-train']", label="train", wait=200, capture=rites.sheet_caps())])
        self.assertEqual(out["captures"]["train"]["kind"], "training-confirm")

    def test_take_them_out_back_from_the_menu_opens_the_first_of_the_two_confirmations(self):
        from tests import test_hounds_rites_web as rites
        routes = rites.kennel_routes([dog("u-1", "Hockey Chief")])
        out = run_page("kennel", routes=routes, **SIGNED, reducedMotion=True, actions=[
            self.OPEN, dict(do="click", sel="[data-hook='studio-more']", wait=60),
            dict(do="click", sel="[data-hook='studio-outback']", label="out", wait=200, capture=rites.sheet_caps())])
        self.assertEqual(out["captures"]["out"]["kind"], "outback-confirm-1")
        self.assertEqual(out["posts"], [])

    def test_the_header_unleash_starts_the_hound_and_shows_the_day_on_overview(self):
        out = self.studio(actions=[self.OPEN, dict(do="click", sel="[data-hook='studio-unleash']", label="fire", wait=400, capture=[
            q("selected", "[role='tab'][aria-selected='true']", "texts"), q("headline", "[data-hook='unleash-headline']"), q("panel", "[data-hook='studio-fire']", "hidden")])])
        c = out["captures"]["fire"]
        self.assertEqual(c["selected"], ["Overview"])
        self.assertIn("Nothing on today's board fits its rule yet", c["headline"])
        self.assertFalse(c["panel"])
        self.assertEqual([p["url"].split("/")[-2:] for p in out["posts"]], [["u-1", "unleash"]])

    def test_the_header_unleash_works_from_the_rules_tab_too(self):
        out = self.studio(actions=[dict(do="click", sel="[data-hook='dog-action-edit']", wait=500),
                                   dict(do="click", sel="[data-hook='studio-unleash']", label="fire", wait=500, capture=[
                                       q("selected", "[role='tab'][aria-selected='true']", "texts"), q("headline", "[data-hook='unleash-headline']")])])
        self.assertEqual(out["captures"]["fire"]["selected"], ["Overview"])
        self.assertIn("is unleashed", out["captures"]["fire"]["headline"])

    def test_a_retired_hound_has_no_buttons_in_the_header(self):
        out = self.studio(dogs=[dog("u-1", "Live Wire"), dog("u-2", "Old Timer", status="retired", retired=True)], actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", index=1, wait=300, label="open", capture=[
                q("actions_hidden", "[data-hook='studio-actions']", "hidden"), q("title", "[data-hook='studio-title']"), q("remove_hidden", "[data-hook='studio-remove']", "hidden")])])
        c = out["captures"]["open"]
        self.assertEqual(c["title"], "Old Timer")
        self.assertTrue(c["actions_hidden"])

    def test_the_picture_opens_the_look_editor_over_the_drawer_and_done_puts_it_away(self):
        out = self.studio(actions=[
            self.OPEN,
            dict(do="click", sel="[data-hook='studio-avatar']", label="look", wait=300, capture=[
                q("sheet_hidden", "[data-hook='studio-look-sheet']", "hidden"), q("preview", "[data-hook='locker-preview'] svg.dk-badge", "count"),
                q("title", "[data-hook='studio-look-sheet'] .kn-look__title")]),
            dict(do="click", sel="[data-hook='studio-look-done']", label="done", wait=100, capture=[
                q("sheet_hidden", "[data-hook='studio-look-sheet']", "hidden"), q("preview", "[data-hook='locker-preview']", "count")])])
        look, done = out["captures"]["look"], out["captures"]["done"]
        self.assertEqual((look["sheet_hidden"], look["preview"], look["title"]), (False, 1, "Look"))
        self.assertEqual((done["sheet_hidden"], done["preview"]), (True, 0))


# ---------------------------------------------------------------------------------------------------
# the hound-level Sports row
# ---------------------------------------------------------------------------------------------------

def two_rules(sports_a, sports_b, markets_b=("spread",)):
    return [RF.rule(sports=list(sports_a), markets=["moneyline"]), RF.rule(sports=list(sports_b), markets=list(markets_b))]


def state_of(sport):
    return q(sport, f"[data-hound-sport='{sport}']", "attr", attr="aria-checked")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSportsRow(StudioHelpers, unittest.TestCase):
    CHECKED = q("on", "[data-hook='hound-sports'] [aria-checked='true']", "attrs", attr="data-hound-sport")
    MIXED = q("mixed", "[data-hook='hound-sports'] [aria-checked='mixed']", "attrs", attr="data-hound-sport")
    NOTE = q("note", "[data-hook='hound-sports-note']")

    def hound(self, rules, **kw):
        return self.studio(mine_dogs=[member_dog(rules=rules)], **kw)

    def test_it_is_the_first_thing_on_the_rules_tab_one_chip_per_sport_without_any_sport(self):
        out = self.hound(two_rules(["NHL", "TENNIS"], ["NHL", "TENNIS"]), actions=[EDIT], queries=[
            q("chips", "[data-hook='hound-sports'] [data-hound-sport]", "attrs", attr="data-hound-sport"), self.CHECKED, self.MIXED,
            q("roles", "[data-hook='hound-sports'] [data-hound-sport]", "attrs", attr="role"), q("hidden", "[data-hook='hound-sports']", "hidden"),
            q("first", "[data-hook='studio-rules'] [data-hook]", "attrs", attr="data-hook")])
        f = out["final"]
        menu_sports = [s["value"] for s in TheStudio.MENU["sports"] if not s.get("any")]
        self.assertCountEqual(f["chips"], menu_sports)
        self.assertNotIn("ANY", f["chips"])
        self.assertCountEqual(f["on"], ["NHL", "TENNIS"])
        self.assertEqual(f["mixed"], [])
        self.assertEqual(set(f["roles"]), {"checkbox"})
        self.assertFalse(f["hidden"])
        hooks = [h for h in f["first"] if h in ("hound-sports", "rules-quick", "rule-sentences", "rules-live-test", "rules-fold", "rule-cards")]
        self.assertEqual(hooks[:5], ["hound-sports", "rules-quick", "rule-sentences", "rules-live-test", "rules-fold"])

    def test_unticking_tennis_removes_it_from_every_rule(self):
        out = self.hound(two_rules(["NHL", "TENNIS"], ["NHL", "TENNIS"]), actions=[
            EDIT, dict(do="click", sel="[data-hound-sport='TENNIS']", label="off", wait=500, capture=[self.CHECKED, self.MIXED, state_of("TENNIS"), self.NOTE])])
        c = out["captures"]["off"]
        self.assertEqual(c["on"], ["NHL"])
        self.assertEqual(c["TENNIS"], "false")
        self.assertIn("Tennis", c["note"])
        last = self.previews(out)[-1]
        self.assertEqual([r["sports"] for r in last["rules"]], [["NHL"], ["NHL"]])

    def test_an_any_sport_rule_is_expanded_so_one_sport_can_come_off(self):
        # the owner's HOCKEYCHIEF "keeps betting tennis": a rule on "Any sport" shows every chip on, and one tap takes tennis out
        out = self.hound([RF.rule(sports=["ANY"], markets=["moneyline"])], actions=[
            EDIT, dict(do="click", sel="[data-hound-sport='TENNIS']", label="off", wait=500, capture=[state_of("TENNIS"), state_of("NHL")])])
        self.assertEqual(out["captures"]["off"], {"TENNIS": "false", "NHL": "true"})
        sports = self.previews(out)[-1]["rules"][0]["sports"]
        self.assertNotIn("TENNIS", sports)
        self.assertNotIn("ANY", sports)
        self.assertIn("NHL", sports)
        self.assertGreater(len(sports), 10)

    def test_a_sport_only_some_rules_bet_is_mixed_and_a_tap_adds_it_to_all_of_them(self):
        out = self.hound(two_rules(["NHL", "TENNIS"], ["NHL"]), actions=[
            EDIT, dict(do="wait", label="seen", wait=100, capture=[self.CHECKED, self.MIXED, state_of("TENNIS"), state_of("NHL")]),
            dict(do="click", sel="[data-hound-sport='TENNIS']", label="all", wait=500, capture=[self.CHECKED, self.MIXED, state_of("TENNIS")])])
        seen, after = out["captures"]["seen"], out["captures"]["all"]
        self.assertEqual((seen["TENNIS"], seen["NHL"]), ("mixed", "true"))
        self.assertEqual(seen["mixed"], ["TENNIS"])
        self.assertEqual((after["TENNIS"], after["mixed"]), ("true", []))
        self.assertEqual([r["sports"] for r in self.previews(out)[-1]["rules"]], [["NHL", "TENNIS"], ["NHL", "TENNIS"]])

    def test_the_last_sport_cannot_be_unticked(self):
        out = self.hound([RF.rule(sports=["NHL"], markets=["moneyline"])], actions=[
            EDIT, dict(do="click", sel="[data-hound-sport='NHL']", label="tap", wait=500, capture=[state_of("NHL"), self.CHECKED,
                                                                                           q("disabled", "[data-hound-sport='NHL']", "disabled"),
                                                                                           q("title", "[data-hound-sport='NHL']", "attr", attr="title")])])
        c = out["captures"]["tap"]
        self.assertTrue(c["disabled"])
        self.assertEqual((c["NHL"], c["on"]), ("true", ["NHL"]))
        self.assertIn("At least one sport", c["title"])
        for spec in self.previews(out):
            self.assertEqual([r["sports"] for r in spec["rules"]], [["NHL"]], "no preview ever went out with an empty sport list")

    def test_a_rule_that_would_be_left_with_no_sport_keeps_the_chip_disabled_even_when_other_rules_have_more(self):
        out = self.hound(two_rules(["NHL", "TENNIS"], ["NHL"]), actions=[
            EDIT, dict(do="wait", label="seen", wait=100, capture=[q("disabled", "[data-hound-sport='NHL']", "disabled"), q("tennis_disabled", "[data-hound-sport='TENNIS']", "disabled")])])
        self.assertTrue(out["captures"]["seen"]["disabled"], "rule 2 has only NHL")
        self.assertFalse(out["captures"]["seen"]["tennis_disabled"])

    def test_a_rule_whose_markets_are_not_offered_in_the_sport_is_left_alone_and_the_row_says_so(self):
        rules = [RF.rule(sports=["MLB"], markets=["moneyline"]), RF.rule(sports=["MLB"], markets=["batter_hits"])]
        out = self.hound(rules, actions=[EDIT, dict(do="click", sel="[data-hound-sport='TENNIS']", label="on", wait=500, capture=[
            state_of("TENNIS"), self.NOTE, q("mlb", "[data-hound-sport='MLB']", "attr", attr="aria-checked")])])
        c = out["captures"]["on"]
        self.assertEqual(c["TENNIS"], "mixed")
        self.assertIn("Rule 2", c["note"])
        self.assertIn("not offered", c["note"])
        self.assertEqual([r["sports"] for r in self.previews(out)[-1]["rules"]], [["MLB", "TENNIS"], ["MLB"]])

    def test_a_sport_none_of_the_rules_can_bet_is_disabled(self):
        out = self.hound([RF.rule(sports=["MLB"], markets=["batter_hits"])], actions=[EDIT], queries=[
            q("tennis_disabled", "[data-hound-sport='TENNIS']", "disabled"), q("mlb_disabled", "[data-hound-sport='MLB']", "disabled")])
        self.assertTrue(out["final"]["tennis_disabled"])
        self.assertTrue(out["final"]["mlb_disabled"], "the last sport")

    def test_a_stat_condition_the_new_sports_cannot_run_leaves_with_the_change_and_the_row_says_how_many(self):
        # the temperature condition is MLB-only: adding hockey to the rule takes it out, as the rule card's own sport grid does
        rule = RF.rule(sports=["MLB"], markets=["moneyline"], when={"op": "all", "items": [{"id": "temperature", "cmp": "gte", "value": 80}]})
        out = self.hound([rule], actions=[EDIT, dict(do="click", sel="[data-hound-sport='NHL']", label="on", wait=500, capture=[state_of("NHL"), self.NOTE])])
        self.assertEqual(out["captures"]["on"]["NHL"], "true")
        self.assertIn("1 stat condition was removed", out["captures"]["on"]["note"])
        self.assertIsNone(self.previews(out)[-1]["rules"][0].get("when"))

    def test_it_follows_a_change_made_in_a_rule_card(self):
        out = self.hound([RF.rule(sports=["NHL"], markets=["moneyline"])], actions=[
            EDIT, dict(do="click", sel="[data-hook='rule-sports'] [data-sport='TENNIS']", label="card", wait=400, capture=[self.CHECKED])])
        self.assertCountEqual(out["captures"]["card"]["on"], ["NHL", "TENNIS"])

    def test_it_is_on_the_public_builder_page_too_and_drives_the_rule_there(self):
        # build-a-hound.html: a blank rule, then the row appears at the top of "Build the rule"
        from tests import test_hounds_builder_web as B
        out = B.build(actions=[dict(do="click", sel="[data-hook='blank-rule']", wait=100),
                               dict(do="click", sel="[data-hound-sport='NBA']", wait=300, label="nba", capture=[self.CHECKED, state_of("NBA")])],
                      queries=[q("hidden", "[data-hook='hound-sports']", "hidden"), q("chips", "[data-hook='hound-sports'] [data-hound-sport]", "count"),
                               q("quick", "[data-hook='rules-quick']", "hidden"), q("quick_children", "[data-hook='rules-quick'] [data-hook]", "count")])
        self.assertFalse(out["final"]["hidden"])
        self.assertGreater(out["final"]["chips"], 10)
        self.assertEqual(out["captures"]["nba"]["NBA"], "true")
        self.assertIn("NBA", out["captures"]["nba"]["on"])
        self.assertTrue(out["final"]["quick"], "the quick row is the studio's; the page shows its rule cards open")
        self.assertEqual(out["final"]["quick_children"], 0)


# ---------------------------------------------------------------------------------------------------
# the quick row
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheQuickRow(StudioHelpers, unittest.TestCase):
    def test_a_one_rule_hound_gets_markets_side_price_and_bets_a_day_above_the_cards(self):
        out = self.studio(actions=[EDIT], queries=[
            q("markets", "[data-hook='quick-markets'] button", "count"), q("side", "[data-hook='quick-side']", "count"), q("price", "[data-hook='quick-price-range']", "count"),
            q("read", "[data-hook='quick-price-readout']"), q("bets", "[data-hook='quick-bets']", "value"), q("hidden", "[data-hook='rules-quick']", "hidden"),
            q("card_price", "[data-hook='price-range']", "count")])
        f = out["final"]
        self.assertGreater(f["markets"], 3)
        self.assertEqual((f["side"], f["price"], f["card_price"]), (1, 1, 1))
        self.assertFalse(f["hidden"])
        self.assertEqual(f["bets"], "2")
        self.assertRegex(f["read"], r"^Average price from")

    def test_bets_a_day_in_the_quick_row_writes_the_spec_and_the_cards_limits_box_follows(self):
        out = self.studio(actions=[EDIT, dict(do="set", sel="[data-hook='quick-bets']", value="4", label="set", wait=600, capture=[
            q("limits", "[data-hook='globals-grid'] [data-hook='g-bets']", "value"), q("quick", "[data-hook='quick-bets']", "value")])])
        self.assertEqual(out["captures"]["set"], {"limits": "4", "quick": "4"})
        self.assertEqual(self.previews(out)[-1]["max_bets_per_day"], 4)

    def test_a_change_in_the_rule_card_moves_the_quick_row(self):
        out = self.studio(actions=[EDIT, dict(do="set", sel="[data-hook='globals-grid'] [data-hook='g-bets']", value="5", label="set", wait=400,
                                              capture=[q("quick", "[data-hook='quick-bets']", "value")])])
        self.assertEqual(out["captures"]["set"]["quick"], "5")

    def test_a_market_chip_in_the_quick_row_switches_the_rules_market(self):
        out = self.studio(actions=[EDIT, dict(do="click", sel="[data-hook='quick-markets'] [data-market='total']", label="total", wait=500)])
        self.assertEqual(self.previews(out)[-1]["rules"][0]["markets"], ["total"])

    def test_a_hound_with_several_rules_gets_bets_a_day_and_a_pointer_to_the_cards(self):
        out = self.studio(mine_dogs=[member_dog(rules=two_rules(["NHL"], ["NHL"]))], actions=[EDIT], queries=[
            q("markets", "[data-hook='quick-markets']", "count"), q("many", "[data-hook='quick-many']"), q("bets", "[data-hook='quick-bets']", "count")])
        f = out["final"]
        self.assertEqual((f["markets"], f["bets"]), (0, 1))
        self.assertIn("2 rules", f["many"])
        self.assertIn("Advanced: edit each rule", f["many"])


# ---------------------------------------------------------------------------------------------------
# the live test
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLiveTestLine(StudioHelpers, unittest.TestCase):
    LINE = q("line", "[data-hook='rules-live-test'] [data-hook='hind-line']")
    STATE = q("state", "[data-hook='rules-live-test']", "attr", attr="data-state")

    def test_it_says_what_the_rules_would_have_done_over_the_past_14_days(self):
        out = self.studio(actions=[dict(EDIT, wait=2000, capture=[self.LINE, self.STATE, q("outcome", "[data-hook='rules-live-test']", "attr", attr="data-outcome"),
                                                                    q("label", "[data-hook='rules-live-test'] [data-hook='hind-label']")])])
        c = out["captures"]["edit"]
        self.assertEqual(c["line"], "Past 14 days with these rules: 23 bets, 13-10, +2.10u.")
        self.assertEqual((c["state"], c["outcome"]), ("result", "settled"))
        self.assertIn("rehearsal on past games, not a forecast", c["label"])
        self.assertEqual(self.drills(out)[0]["days"], 14)
        self.assertEqual(self.drills(out)[0]["spec"]["name"], "Hockey Chief", "the call carries the SPEC, so unsaved edits are what is tested")

    def test_a_change_re_runs_the_same_call_after_a_pause_and_the_new_numbers_replace_the_old(self):
        out = self.studio(extra={}, switchAfter={"/hounds/drill": [1, [200, HIND_AFTER]]}, actions=[
            dict(EDIT, wait=2000, capture=[self.LINE]),
            dict(do="click", sel="[data-hound-sport='TENNIS']", label="change", wait=300, capture=[self.LINE, self.STATE]),
            dict(do="wait", label="after", wait=1800, capture=[self.LINE, self.STATE])],
            mine_dogs=[member_dog(rules=[RF.rule(sports=["NHL", "TENNIS"], markets=["moneyline"])])])
        first, soon, after = out["captures"]["edit"], out["captures"]["change"], out["captures"]["after"]
        self.assertEqual(first["line"], "Past 14 days with these rules: 23 bets, 13-10, +2.10u.")
        self.assertEqual(len(self.drills(out)), 2)
        self.assertEqual(self.drills(out)[1]["spec"]["rules"][0]["sports"], ["NHL"], "the second call is the edited rule")
        self.assertEqual(self.drills(out)[1]["days"], 14)
        self.assertEqual(after["line"], "Past 14 days with these rules: 9 bets, 3-6, -1.40u.")
        self.assertEqual(after["state"], "result")
        self.assertNotEqual(soon["line"], after["line"])

    def test_a_burst_of_chip_taps_is_one_request(self):
        out = self.studio(mine_dogs=[member_dog(rules=[RF.rule(sports=["NHL"], markets=["moneyline"])])], actions=[
            dict(EDIT, wait=2000),
            dict(do="click", sel="[data-hound-sport='TENNIS']", wait=30), dict(do="click", sel="[data-hound-sport='SOCCER']", wait=30),
            dict(do="click", sel="[data-hound-sport='MMA']", wait=1800, label="end", capture=[self.LINE])])
        drills = self.drills(out)
        self.assertEqual(len(drills), 2, "the opening one and one for the burst")
        self.assertEqual(set(drills[1]["spec"]["rules"][0]["sports"]), {"NHL", "TENNIS", "SOCCER", "MMA"})

    def test_while_it_runs_the_line_says_it_is_checking(self):
        out = self.studio(delay={"POST /hounds/drill": 2500}, actions=[dict(EDIT, wait=1700, capture=[
            self.LINE, self.STATE, q("busy", "[data-hook='rules-live-test']", "attr", attr="aria-busy")])])
        c = out["captures"]["edit"]
        self.assertEqual(c["line"], "Past 14 days with these rules: checking...")
        self.assertEqual((c["state"], c["busy"]), ("pending", "true"))

    def test_no_bets_in_the_window_says_not_enough_games_not_a_win(self):
        out = self.studio(extra={DRILL: [200, HIND_NONE]}, actions=[dict(EDIT, wait=2000, capture=[
            self.LINE, q("outcome", "[data-hook='rules-live-test']", "attr", attr="data-outcome")])])
        c = out["captures"]["edit"]
        self.assertEqual(c["line"], "Past 14 days with these rules: no bets. Not enough games fit these rules in that window to judge them.")
        self.assertEqual(c["outcome"], "empty")
        self.assertNotIn("+", c["line"])

    def test_bets_that_have_not_settled_are_not_given_a_record(self):
        pending = dict(HIND, record={"bets": 3, "graded": 0, "wins": 0, "losses": 0, "pushes": 0, "pending": 3}, units_average_price=None)
        out = self.studio(extra={DRILL: [200, pending]}, actions=[dict(EDIT, wait=2000, capture=[self.LINE])])
        self.assertEqual(out["captures"]["edit"]["line"], "Past 14 days with these rules: 3 bets, none settled yet.")

    def test_it_is_labelled_a_rehearsal_not_a_forecast_and_carries_the_servers_small_sample_note(self):
        out = self.studio(actions=[dict(EDIT, wait=2000)], queries=[q("text", "[data-hook='rules-live-test']")])
        text = out["final"]["text"]
        self.assertIn("a rehearsal on past games, not a forecast", text)
        self.assertIn("not a forecast", text)
        self.assertIn("Not counted in the record", text)
        self.assertIn("a small sample", text)

    def test_the_servers_limit_reads_as_paused_with_a_refresh_button(self):
        out = self.studio(extra={DRILL: [429, {"detail": {"error": "rate_limited", "message": "5 an hour", "retry_after": 1800}}]}, actions=[dict(EDIT, wait=2000, capture=[
            self.LINE, self.STATE, q("refresh", "[data-hook='hind-refresh']", "count")])])
        c = out["captures"]["edit"]
        self.assertEqual((c["state"], c["refresh"]), ("paused", 1))
        self.assertIn("Preview paused", c["line"])

    def test_the_full_test_waits_behind_a_button_and_runs_the_saved_rules_when_opened(self):
        out = self.studio(actions=[
            dict(EDIT, wait=2000, capture=[q("panel", "[data-hook='rules-full-test-panel']", "hidden"), q("toggle", "[data-hook='rules-full-test-toggle']"),
                                           q("expanded", "[data-hook='rules-full-test-toggle']", "attr", attr="aria-expanded")]),
            dict(do="click", sel="[data-hook='rules-full-test-toggle']", label="open", wait=400, capture=[
                q("panel", "[data-hook='rules-full-test-panel']", "hidden"), q("note", ".kn-fulltest__note"), q("windows", "[data-hook='backtest-window']", "texts"),
                q("expanded", "[data-hook='rules-full-test-toggle']", "attr", attr="aria-expanded")])])
        closed, opened = out["captures"]["edit"], out["captures"]["open"]
        self.assertEqual((closed["panel"], closed["toggle"], closed["expanded"]), (True, "See the full test", "false"))
        self.assertEqual((opened["panel"], opened["expanded"]), (False, "true"))
        self.assertIn("saved as v1", opened["note"])
        self.assertTrue(opened["windows"])
        self.assertEqual([b for b in self.drills(out) if "dog_id" in b], [{"dog_id": "u-1", "days": 7}])
        self.assertEqual(len([b for b in self.drills(out) if "dog_id" in b]), 1, "the full test only ran because it was opened")


# ---------------------------------------------------------------------------------------------------
# saving
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSaveButton(StudioHelpers, unittest.TestCase):
    def test_it_says_save_as_the_next_version_and_a_second_tap_confirms(self):
        diff = {"changes": [{"what": "Sports", "before": "NHL and tennis", "after": "NHL"}], "paper_only": True}
        saved = {"hound": {"id": "u-1b", "name": "Hockey Chief", "version_no": 3}, "previous_id": "u-1", "changes": diff["changes"], "paper_only": True}
        out = self.studio(mine_dogs=[member_dog(version_no=2, rules=[RF.rule(sports=["NHL", "TENNIS"], markets=["moneyline"])])],
                          extra={"POST /hounds/u-1/diff": [200, diff], "POST /hounds/u-1/version": [200, saved]}, actions=[
            dict(EDIT, wait=500, capture=[q("btn", "[data-hook='build-submit']"), q("note", "[data-hook='version-note']")]),
            dict(do="click", sel="[data-hound-sport='TENNIS']", wait=400),
            dict(do="click", sel="[data-hook='build-submit']", label="review", wait=300, capture=[q("btn", "[data-hook='build-submit']"), q("diff", "[data-hook='diff']", "hidden")]),
            dict(do="click", sel="[data-hook='build-submit']", label="save", wait=500, capture=[q("msg", "[data-hook='build-message']")])])
        self.assertEqual(out["captures"]["edit"]["btn"], "Save as v3")
        self.assertIn("version 3", out["captures"]["edit"]["note"])
        self.assertEqual(out["captures"]["review"]["btn"], "Confirm and save as v3")
        self.assertFalse(out["captures"]["review"]["diff"])
        self.assertIn("Saved as version 3", out["captures"]["save"]["msg"])
        versions = [p for p in out["posts"] if p["url"].endswith("/version")]
        self.assertEqual(len(versions), 1, "saving still makes a new version")
        self.assertEqual(versions[0]["body"]["spec"]["rules"][0]["sports"], ["NHL"])

    def test_the_save_row_sits_in_a_bar_at_the_foot_of_the_page(self):
        out = self.studio(actions=[EDIT], queries=[q("bar", "[data-hook='build-savebar'] [data-hook='build-submit']", "count"),
                                                   q("in_identity", "[data-hook='step-identity'] [data-hook='build-submit']", "count")])
        self.assertEqual(out["final"], {"bar": 1, "in_identity": 0})
        css = read("css/studio.css")
        self.assertRegex(css, r"\.bd-savebar \{ position: sticky; bottom: 0;")


# ---------------------------------------------------------------------------------------------------
# one hook set, two homes
# ---------------------------------------------------------------------------------------------------

class BothSkeletonsCarryTheNewHooks(unittest.TestCase):
    NEW = ("hound-sports", "rules-quick", "rules-live-test", "hind-box")

    def test_the_static_page_and_the_studio_skeleton_have_every_new_hook(self):
        page, skeleton = read("build-a-hound.html"), read("js/builder-skeleton.js")
        for hook in self.NEW:
            with self.subTest(hook=hook):
                self.assertIn(f'data-hook="{hook}"', page)
                self.assertTrue(f'hook("{hook}"' in skeleton or f'"data-hook": "{hook}"' in skeleton)

    def test_the_builder_reads_them(self):
        js = read("js/hounds-build.js")
        for hook in self.NEW:
            self.assertIn(f'q("{hook}")', js, hook)

    def test_the_hound_sports_row_leads_the_rule_step_on_both(self):
        page, skeleton = read("build-a-hound.html"), read("js/builder-skeleton.js")
        self.assertLess(page.index('data-hook="hound-sports"'), page.index('data-hook="rules-empty"'))
        self.assertLess(skeleton.index('hook("hound-sports"'), skeleton.index('hook("rules-empty"'))

    def test_the_last_14_days_lives_in_the_rule_step_not_the_rail(self):
        page, skeleton = read("build-a-hound.html"), read("js/builder-skeleton.js")
        self.assertGreater(page.index('data-hook="hind-box"'), page.index('data-hook="step-rules"'))
        self.assertLess(page.index('data-hook="hind-box"'), page.index('data-hook="step-identity"'))
        self.assertGreater(skeleton.index('hook("hind-box"'), skeleton.index('hook("rules-live-test"'))
        self.assertNotIn("Last 14 days", page + skeleton)

    def test_the_studio_folds_the_cards_under_advanced_and_the_page_keeps_them_open(self):
        skeleton, page = read("js/builder-skeleton.js"), read("build-a-hound.html")
        self.assertIn('h("details", hook("rules-fold"', skeleton)
        self.assertIn("Advanced: edit each rule", skeleton)
        self.assertNotIn("<details", page[page.index('data-hook="rules-advanced"'):page.index('data-hook="step-identity"')])


class TheStudioMarkup(unittest.TestCase):
    HTML = read("kennel.html")

    def test_three_tabs_and_none_of_the_old_ones(self):
        tabs = re.findall(r'role="tab" data-tab="([a-z]+)"', self.HTML)
        self.assertEqual(tabs, ["overview", "rules", "coach"])
        self.assertNotIn("data-scrollactive", self.HTML)
        self.assertEqual(re.findall(r'data-tabpanel="([a-z]+)"', self.HTML), ["overview", "rules", "coach"])

    def test_the_header_buttons_and_the_analyze_slot_and_the_look_sheet_are_in_the_markup(self):
        for hook in ("studio-unleash", "studio-train", "studio-more", "studio-menu", "studio-versions-open", "studio-outback", "studio-remove",
                     "studio-analyze", "studio-look-sheet", "studio-look", "studio-look-done", "studio-training", "studio-fire", "studio-record"):
            self.assertIn(f'data-hook="{hook}"', self.HTML, hook)
        self.assertRegex(self.HTML, r'<section class="kn-analyze" data-hook="studio-analyze" hidden></section>')
        analyze = self.HTML.index('data-hook="studio-analyze"')
        self.assertLess(analyze, self.HTML.index('data-hook="studio-record"'))
        self.assertLess(self.HTML.index('data-hook="studio-overview"'), analyze)

    def test_the_old_tab_words_are_gone_from_the_copy(self):
        studio = self.HTML[self.HTML.index('data-hook="studio"'):self.HTML.index("</aside>")]
        for word in (">Look<", ">Unleash<", ">Backtest<", ">Ask<", ">Record<", ">Lessons<"):
            if word == ">Unleash<":                       # the header's primary button is still called Unleash
                continue
            self.assertNotIn(word, studio.replace('<h3 class="kn-look__title">Look</h3>', ""), word)

    def test_a_phone_gets_no_sideways_tab_strip_and_44px_targets(self):
        css = read("css/studio.css").split("THE STUDIO, REVAMPED", 1)[1]
        self.assertIn(".lh-tabs--studio { overflow: visible;", css)
        self.assertRegex(css, r"\.lh-tabs--studio \[role=\"tab\"\] \{ flex: 1 1 0; min-width: 0; height: 44px;")
        self.assertIn(".kn-studio__act { flex: 1 1 120px; min-height: 44px;", css)
        self.assertIn("width: 44px; height: 44px", css)
        self.assertIn("min-height: 44px", css.split(".bd-houndsports", 1)[1])

    def test_every_animation_added_is_inside_the_no_preference_block(self):
        css = read("css/studio.css").split("THE STUDIO, REVAMPED", 1)[1]
        outside = re.sub(r"@media \(prefers-reduced-motion: no-preference\) \{.*?\n\}\n", "", css, flags=re.S)
        outside = re.sub(r"@keyframes [\w-]+ \{.*?\n", "", outside)
        self.assertNotRegex(outside, r"animation\s*:")

    def test_no_banned_word_in_what_the_new_markup_and_script_say(self):
        text = self.HTML + read("js/studio-tabs.js") + read("js/builder-skeleton.js")
        shown = re.findall(r'>([^<>{}\n]{3,})<|text: ?"([^"]+)"', text)
        for a, b in shown:
            words = (a or b).lower()
            self.assertNotRegex(words, r"\bbeta\b|\bedge\b|\block\b|guarantee|profit", words)


if __name__ == "__main__":
    unittest.main()
