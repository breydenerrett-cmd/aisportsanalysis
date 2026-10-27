"""The step-by-step rules editor (owner ask 2026-10-26, docs/HOUND_LOOP_PLAN.md phase 2), in both of its homes.

Sports chips that say what is in season and how many games are on this week, markets, plain-English condition blocks with sliders,
one price range with the -200 floor drawn and enforced, limits, a live preview with a 14 day HINDSIGHT line, "Say it in words" as a
shortcut that fills the steps, and "Saving makes version N+1" beside the button. The page runs for real under node against the fake DOM
of tests/hounds_web_harness.mjs (skipped without node); the season read and the menu's quick blocks need neither node nor FastAPI.
"""
from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timezone

from src.hounds import user_spec
from src.sports import season_view
from tests import test_hounds_builder_web as B
from tests.hounds_web_runner import HAS_NODE, WEB

import tests.test_kennel_page as K

q = B.q
NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
JS = (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8")
HTML = (WEB / "build-a-hound.html").read_text(encoding="utf-8")
SKELETON = (WEB / "js" / "builder-skeleton.js").read_text(encoding="utf-8")

# what the program has stored for the week of 2026-10-26: NBA busy, MLB in its postseason, MMA out of season, tennis between events
SEASON = json.loads(json.dumps(season_view.season_overview(
    NOW, espn={"NBA": {"games": 58, "phase": None, "as_of": "2026-10-26T17:00:00Z"}, "NHL": {"games": 31, "phase": None, "as_of": None}},
    board={"MLB": 3, "NFL": 14}, active={"NBA", "NHL", "TENNIS"}, active_as_of="2026-10-26T17:47:34Z")))

HIND = {"label": "Backtest (hindsight, not counted in the record)", "counted": False, "days": 14, "paper_only": True,
        "record": {"bets": 23, "graded": 23, "wins": 13, "losses": 10, "pushes": 0, "pending": 0}, "units_average_price": 2.1,
        "sample_note": "23 graded bets is a small sample."}
DRILL = "POST /hounds/drill"
SIGNED = B.SIGNED


def routes(**over):
    r = B.base_routes(**{"/sports/season": [200, SEASON]})
    r.update(over)
    return r


def chips_of(out):
    return out["final"]["chips"]


# ---------------------------------------------------------------------------------------------------
# the season read: stored rows only, a chip's words, a reason for every dimmed sport
# ---------------------------------------------------------------------------------------------------

class TheSeasonRead(unittest.TestCase):
    def sport(self, code):
        return next(s for s in SEASON["sports"] if s["code"] == code)

    def test_a_chip_says_the_count_and_the_phase_in_the_owners_words(self):
        self.assertEqual(self.sport("NBA")["chip"], "NBA · 58 games coming up")
        self.assertEqual(self.sport("MLB")["chip"], "MLB · postseason · 3 games")
        self.assertEqual(season_view.chip_text("WNBA", 1, "postseason"), "WNBA · postseason · 1 game")
        self.assertEqual(season_view.chip_text("Tennis", 0, None), "Tennis · no games this week")

    def test_zero_games_is_dimmed_with_a_reason_and_out_of_season_is_told_apart(self):
        mma = self.sport("MMA")
        self.assertEqual((mma["games_7d"], mma["in_season"], mma["reason"]), (0, False, "Out of season."))
        tennis = self.sport("TENNIS")
        self.assertEqual((tennis["games_7d"], tennis["in_season"]), (0, True))
        self.assertIn("No games scheduled", tennis["reason"])
        self.assertEqual(self.sport("NBA")["reason"], "")

    def test_the_larger_of_the_two_sources_wins_they_are_never_added(self):
        got = season_view.season_overview(NOW, espn={"NBA": {"games": 10}}, board={"NBA": 12}, active=set())
        self.assertEqual(next(s for s in got["sports"] if s["code"] == "NBA")["games_7d"], 12)

    def test_only_sports_a_hound_may_bet_are_listed_and_the_note_is_honest(self):
        from src.sports import catalog
        self.assertEqual({s["code"] for s in SEASON["sports"]}, {c for c in catalog.family_codes() if (catalog.family(c) or {}).get("dog_menu")})
        self.assertIn("not a full league schedule", SEASON["note"])
        self.assertTrue(SEASON["paper_only"])

    def test_it_reads_stores_only_and_the_route_is_public_and_cached(self):
        src = (WEB.parent / "src" / "sports" / "season_view.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"requests|urllib|httpx|fetch_")
        api = (WEB.parent / "api" / "sports.py").read_text(encoding="utf-8")
        self.assertRegex(api, r'public_router\.get\("/sports/season"\)')
        self.assertIn("cached_season_overview", api)

    def test_a_missing_store_lowers_a_count_it_never_raises(self):
        got = season_view.season_overview(NOW, espn={}, board={}, active=set())
        self.assertTrue(all(s["games_7d"] == 0 for s in got["sports"]))
        self.assertEqual(season_view.espn_counts(NOW, store=object()), {})


class TheMenuNamesTheQuickBlocks(unittest.TestCase):
    def test_every_quick_block_is_a_condition_the_engine_has(self):
        menu = user_spec.builder_menu()
        ids = {c["id"] for c in menu["conditions"]}
        self.assertEqual({b["id"] for b in menu["quick_blocks"]}, {"last_n_wins", "rest_days", "steam", "venue_record", "player_form"})
        for block in menu["quick_blocks"]:
            self.assertIn(block["id"], ids)
            cond = next(c for c in menu["conditions"] if c["id"] == block["id"])
            names = {p["name"] for p in cond["params"]}
            self.assertLessEqual(set(block["set"]), names, block["id"])

    def test_a_block_started_at_its_values_validates_as_a_spec(self):
        from tests import _hounds_rules_fixtures as F
        for block in user_spec.builder_menu()["quick_blocks"]:
            cond = next(c for c in user_spec.builder_menu()["conditions"] if c["id"] == block["id"])
            item = {"id": block["id"], **{p["name"]: p["default"] for p in cond["params"]}, **block["set"]}
            kind = "prop" if block["id"] == "player_form" else "ml_spread"
            rule = F.rule(markets=["batter_hits"], side="over") if kind == "prop" else F.rule()
            rule["when"] = {"op": "all", "items": [item]}
            user_spec.validate_spec(F.v2(rules=[rule]))


# ---------------------------------------------------------------------------------------------------
# the page, run for real
# ---------------------------------------------------------------------------------------------------

BLANK = B.CLICK_BLANK
CHIPS = q("chips", "[data-hook='rule-sports'] button", "texts")
PRESSED = q("pressed", "[data-hook='rule-sports'] button[aria-pressed='true']", "attrs", attr="data-sport")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class SportsStep(unittest.TestCase):
    def test_chips_show_the_counts_and_the_phase(self):
        out = B.build(routes(), actions=[BLANK], queries=[CHIPS])
        chips = chips_of(out)
        self.assertTrue(any(c.startswith("NBA · 58 games coming up") for c in chips), chips)
        self.assertTrue(any(c.startswith("MLB · postseason · 3 games") for c in chips), chips)

    def test_out_of_season_and_zero_game_sports_are_dimmed_with_a_reason_and_still_selectable(self):
        out = B.build(routes(), actions=[BLANK, dict(do="click", sel="[data-hook='rule-sports'] button[data-sport='MMA']", wait=60)], queries=[
            q("dim", "[data-hook='rule-sports'] button[data-dim]", "attrs", attr="data-dim"),
            q("dim_sports", "[data-hook='rule-sports'] button[data-dim]", "attrs", attr="data-sport"),
            q("why", "[data-hook='rule-sports'] button[data-sport='MMA'] .bd-chip__why"), PRESSED,
            q("mma_disabled", "[data-hook='rule-sports'] button[data-sport='MMA']", "disabled")])
        f = out["final"]
        self.assertIn("MMA", f["dim_sports"])
        self.assertEqual(f["dim"][f["dim_sports"].index("MMA")], "out_of_season")
        self.assertIn("no_games", f["dim"])
        self.assertEqual(f["why"], "Out of season.")
        self.assertFalse(f["mma_disabled"])
        self.assertIn("MMA", f["pressed"], "a dimmed sport can still be picked")

    def test_the_in_season_ones_come_first(self):
        out = B.build(routes(), actions=[BLANK], queries=[q("games", "[data-hook='rule-sports'] button", "attrs", attr="data-games")])
        games = [int(g) for g in out["final"]["games"] if g is not None]
        self.assertEqual(games, sorted(games, key=lambda g: (g == 0, -g)), "sports with games lead, most games first")

    def test_pick_for_me_chooses_exactly_what_is_in_season(self):
        out = B.build(routes(), actions=[BLANK, dict(do="click", sel="[data-hook='pick-in-season']", wait=80)], queries=[
            PRESSED, q("dimmed_pressed", "[data-hook='rule-sports'] button[data-dim][aria-pressed='true']", "count")])
        pressed = out["final"]["pressed"]
        live = {s["code"] for s in SEASON["sports"] if s["games_7d"] > 0}
        self.assertTrue(pressed and set(pressed) <= live, pressed)
        self.assertEqual(out["final"]["dimmed_pressed"], 0)
        self.assertIn("MLB", pressed)

    def test_without_the_season_the_chips_are_plain_and_nothing_is_dimmed(self):
        out = B.build(B.base_routes(), actions=[BLANK], queries=[CHIPS, q("dim", "[data-hook='rule-sports'] button[data-dim]", "count"),
                                                                 q("pick", "[data-hook='pick-in-season']", "count")])
        self.assertEqual(out["final"]["dim"], 0)
        self.assertEqual(out["final"]["pick"], 0)
        self.assertNotIn("games", " ".join(chips_of(out)))


@unittest.skipUnless(HAS_NODE, "node is not installed")
class StepsMakeTheSameSpecTheOldPathMade(unittest.TestCase):
    def last_spec(self, actions):
        out = B.build(routes(), actions=[BLANK, *actions], settleMs=80)
        return B.preview_posts(out)[-1]

    def test_sliders_and_typed_boxes_are_two_ways_to_the_same_numbers(self):
        old = self.last_spec([dict(do="set", sel="[data-hook='price-min']", value="100", wait=20), dict(do="set", sel="[data-hook='price-max']", value="200", wait=20),
                              dict(do="set", sel="[data-hook='g-bets']", value="3", wait=400)])
        new = self.last_spec([dict(do="set", sel="[data-slider='price-min']", value="100", wait=20), dict(do="set", sel="[data-slider='price-max']", value="120", wait=20),
                              dict(do="set", sel="[data-slider='g-bets']", value="3", wait=400)])
        self.assertEqual(old, new)
        self.assertEqual((new["rules"][0]["price_min"], new["rules"][0]["price_max"], new["max_bets_per_day"]), (100, 200, 3))

    def test_a_quick_block_adds_the_same_condition_the_add_menu_adds(self):
        old = self.last_spec([dict(do="set", sel="[data-hook='add-condition']", value="rest_days", wait=400)])
        new = self.last_spec([dict(do="click", sel="[data-quick='rest_days']", wait=400)])
        self.assertEqual(old["rules"][0]["when"], new["rules"][0]["when"])
        self.assertEqual(new["rules"][0]["when"]["items"][0]["id"], "rest_days")

    def test_a_condition_slider_sets_the_same_value_the_box_does(self):
        spec = self.last_spec([dict(do="click", sel="[data-quick='rest_days']", wait=100), dict(do="set", sel="[data-hook='condition'] [data-slider='value']", value="4", wait=400)])
        self.assertEqual(spec["rules"][0]["when"]["items"][0]["value"], 4)
        box = self.last_spec([dict(do="click", sel="[data-quick='rest_days']", wait=100), dict(do="set", sel="[data-hook='condition'] [data-param='value']", value="4", wait=400)])
        self.assertEqual(box["rules"][0]["when"], spec["rules"][0]["when"])

    def test_a_block_for_a_sport_the_engine_cannot_run_is_disabled_with_a_reason(self):
        out = B.build(routes(), actions=[BLANK, dict(do="click", sel="[data-hook='rule-sports'] button[data-sport='MLB']", wait=40),
                                         dict(do="click", sel="[data-hook='rule-sports'] button[data-sport='NBA']", wait=80)],
                      queries=[q("disabled", "[data-quick]", "attrs", attr="disabled"), q("ids", "[data-quick]", "attrs", attr="data-quick"),
                               q("reason", "[data-quick='rest_days']", "attr", attr="title")])
        f = out["final"]
        self.assertTrue(f["ids"])
        self.assertIsNotNone(f["disabled"][f["ids"].index("rest_days")])
        self.assertIn("only", f["reason"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheMinusTwoHundredFloor(unittest.TestCase):
    def specs(self, actions):
        out = B.build(routes(), actions=[BLANK, *actions])
        return out, [p["rules"][0] for p in B.preview_posts(out)]

    def test_the_floor_is_drawn(self):
        out = B.build(routes(), actions=[BLANK], queries=[q("floor", "[data-hook='price-floor']"), q("n", "[data-hook='price-floor']", "count"),
                                                          q("read", "[data-hook='price-readout']")])
        self.assertEqual(out["final"]["n"], 1)
        self.assertIn("-200", out["final"]["floor"])
        self.assertIn("never", out["final"]["floor"])
        self.assertIn("-199", out["final"]["read"])

    def test_a_typed_price_past_the_floor_is_clamped_and_said(self):
        out, rules = self.specs([dict(do="set", sel="[data-hook='price-min']", value="-250", wait=400)])
        self.assertEqual(rules[-1]["price_min"], -199)
        self.assertTrue(all(r["price_min"] >= -199 for r in rules))
        note = B.build(routes(), actions=[BLANK, dict(do="set", sel="[data-hook='price-min']", value="-250", wait=60)],
                       queries=[q("note", "[data-hook='price-floor-note']"), q("hidden", "[data-hook='price-floor-note']", "hidden"),
                                q("box", "[data-hook='price-min']", "value")])["final"]
        self.assertFalse(note["hidden"])
        self.assertIn("-200 or worse", note["note"])
        self.assertEqual(note["box"], "-199")

    def test_the_slider_cannot_go_past_it_and_the_far_thumb_cannot_cross_the_near_one(self):
        _, rules = self.specs([dict(do="set", sel="[data-slider='price-min']", value="0", wait=400)])
        self.assertEqual(rules[-1]["price_min"], -199)
        _, rules = self.specs([dict(do="set", sel="[data-slider='price-min']", value="140", wait=20), dict(do="set", sel="[data-slider='price-max']", value="120", wait=400)])
        self.assertEqual((rules[-1]["price_min"], rules[-1]["price_max"]), (300, 300))

    def test_the_axis_spends_its_room_where_underdog_prices_are(self):
        # position 120 is +200 and 140 is +300 (steps of 5), so a +120 to +200 rule is a visible stretch of the slider, not a sliver
        out = B.build(routes(), actions=[BLANK, dict(do="set", sel="[data-slider='price-min']", value="104", wait=20),
                                         dict(do="set", sel="[data-slider='price-max']", value="120", wait=400)],
                      queries=[q("read", "[data-hook='price-readout']")])
        self.assertEqual(out["final"]["read"], "Average price from +120 to +200")

    def test_the_axis_has_no_prices_between_minus_100_and_plus_100(self):
        out = B.build(routes(), actions=[BLANK, dict(do="set", sel="[data-slider='price-max']", value="99", wait=400)])
        self.assertEqual(B.preview_posts(out)[-1]["rules"][0]["price_max"], -100)
        out = B.build(routes(), actions=[BLANK, dict(do="set", sel="[data-slider='price-max']", value="100", wait=400)])
        self.assertEqual(B.preview_posts(out)[-1]["rules"][0]["price_max"], 100)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheLiveHindsightPreview(unittest.TestCase):
    LINE = q("line", "[data-hook='hind-line']")
    STATE = q("state", "[data-hook='hind-box']", "attr", attr="data-state")
    REFRESH = q("refresh", "[data-hook='hind-refresh']", "count")

    def run_it(self, actions, drill=None, **kw):
        r = routes(**{DRILL: drill or [200, HIND]})
        return B.build(r, **SIGNED, actions=[BLANK, *actions], queries=[self.LINE, self.STATE, self.REFRESH, q("label", "[data-hook='hind-label']")], **kw)

    def drills(self, out):
        return [p["body"] for p in out["posts"] if p["url"].endswith("/hounds/drill")]

    def test_it_says_what_the_rule_would_have_done_and_labels_it_hindsight(self):
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)])
        f = out["final"]
        self.assertEqual(f["line"], "Over the last 14 days this rule would have bet 23 times: 13-10, +2.10u (hindsight, not counted).")
        self.assertIn("Hindsight", f["label"])
        posts = self.drills(out)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["days"], 14)
        self.assertEqual(posts[0]["spec"]["max_bets_per_day"], 3)
        self.assertNotIn("dog", f["line"].lower())

    def test_a_burst_of_edits_is_one_request(self):
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value="3", wait=20), dict(do="set", sel="[data-hook='g-bets']", value="4", wait=20),
                           dict(do="set", sel="[data-hook='g-bets']", value="5", wait=1900)])
        posts = self.drills(out)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["spec"]["max_bets_per_day"], 5)

    def test_the_same_rule_twice_asks_once(self):
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900), dict(do="set", sel="[data-hook='g-bets']", value="4", wait=1900),
                           dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)])
        self.assertEqual(len(self.drills(out)), 2, "3 then 4 are two rules; going back to 3 is the one already answered")

    def test_it_runs_on_its_own_only_twice_an_hour_then_waits_for_a_tap(self):
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value=str(v), wait=1900) for v in (3, 4, 5)])
        f = out["final"]
        self.assertEqual(len(self.drills(out)), 2, "the third edit does not spend the member's backtest allowance")
        self.assertEqual(f["state"], "paused")
        self.assertIn("Preview paused, tap to refresh.", f["line"])
        self.assertEqual(f["refresh"], 1)
        self.assertIn("Out of date", out["text"], "the last result stays, marked out of date")
        tap = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value=str(v), wait=1900) for v in (3, 4, 5)]
                          + [dict(do="click", sel="[data-hook='hind-refresh']", wait=300)])
        self.assertEqual(len(self.drills(tap)), 3, "a tap always asks")
        self.assertEqual(tap["final"]["state"], "result")

    def test_the_servers_limit_reads_as_paused_with_a_button(self):
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)],
                          drill=[429, {"detail": {"error": "rate_limited", "message": "5 an hour", "retry_after": 1800}}])
        f = out["final"]
        self.assertEqual(f["state"], "paused")
        self.assertIn("Preview paused, tap to refresh.", f["line"])
        self.assertEqual(f["refresh"], 1)

    def test_a_signed_out_visitor_is_asked_to_sign_in_and_nothing_is_sent(self):
        out = B.build(routes(), actions=[BLANK, dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)], queries=[self.LINE])
        self.assertIn("Sign in", out["final"]["line"])
        self.assertEqual(self.drills(out), [])

    def test_a_free_account_sees_the_plan_prompt_not_a_broken_preview(self):
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)],
                          drill=[402, {"detail": {"error": "upgrade_required", "feature": "backtest", "message": "Backtest is a member tool."}}])
        self.assertIn("upgrade-prompt", out["hooks"])

    def test_a_rule_the_server_refuses_shows_no_hindsight(self):
        bad = {"detail": {"error": "invalid_spec", "message": "no", "fields": {"rules[0].price_min": "too short"}}}
        out = B.build(routes(**{"POST /hounds/builder/preview": [422, bad], DRILL: [200, HIND]}), **SIGNED,
                      actions=[BLANK, dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)], queries=[self.LINE, self.STATE])
        self.assertEqual(out["final"]["state"], "blocked")
        self.assertEqual(self.drills(out), [])

    def test_no_zero_bet_window_reads_as_a_win(self):
        zero = dict(HIND, record={"bets": 0, "graded": 0, "wins": 0, "losses": 0, "pushes": 0, "pending": 0}, units_average_price=0)
        out = self.run_it([dict(do="set", sel="[data-hook='g-bets']", value="3", wait=1900)], drill=[200, zero])
        self.assertEqual(out["final"]["line"], "Over the last 14 days this rule would not have placed a bet (hindsight, not counted).")

    def test_the_rule_sentence_sits_in_the_preview_beside_the_numbers(self):
        out = B.build(routes(), actions=[dict(BLANK, wait=500)], queries=[q("rule", "[data-hook='preview-rule-text']")])
        self.assertIn("MLB moneylines", out["final"]["rule"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class SayItInWordsFillsTheSteps(unittest.TestCase):
    TEXT = "Bet home underdogs between +120 and +200 when they're on 2+ days rest. Max 2 bets a day."
    Q = [PRESSED, q("price_min", "[data-hook='price-min']", "value"), q("price_max", "[data-hook='price-max']", "value"),
         q("bets", "[data-hook='g-bets']", "value"), q("cards", "[data-hook='rule-card']", "count"),
         q("conds", "[data-hook='condition']", "attrs", attr="data-cond"), q("status", "[data-hook='english-status']"),
         q("unread", "[data-hook='not-understood']", "count"), q("side", "[data-hook='rule-side']", "value")]

    def read(self, text):
        r = routes(**{"POST /hounds/english": [200, B.english_answer(text)]})
        return B.build(r, actions=[dict(do="set", sel="[data-hook='english-input']", value=text, wait=20),
                                   dict(do="click", sel="[data-hook='english-go']", wait=200)], queries=self.Q)["final"]

    def test_the_parsed_words_land_in_the_steps_for_review(self):
        f = self.read(self.TEXT)
        self.assertEqual((f["price_min"], f["price_max"], f["bets"]), ("120", "200", "2"))
        self.assertIn("rest_days", f["conds"])
        self.assertEqual(f["cards"], 1)
        self.assertIn("MLB", f["pressed"])
        self.assertIn("filled in the steps", f["status"])
        self.assertEqual(f["unread"], 0)

    def test_what_was_not_understood_is_said_and_the_steps_stay_editable(self):
        text = "Bet underdogs when the moon is in a good mood and zorp the quux"
        r = routes(**{"POST /hounds/english": [200, B.english_answer(text)]})
        out = B.build(r, actions=[dict(do="set", sel="[data-hook='english-input']", value=text, wait=20),
                                  dict(do="click", sel="[data-hook='english-go']", wait=200),
                                  dict(do="set", sel="[data-slider='g-bets']", value="4", wait=400)], queries=self.Q)
        f = out["final"]
        self.assertGreaterEqual(f["unread"], 1)
        self.assertGreaterEqual(f["cards"], 1)
        self.assertEqual(f["bets"], "4", "the steps took an edit after a partial read")
        self.assertEqual(B.preview_posts(out)[-1]["max_bets_per_day"], 4)

    def test_nothing_read_leaves_blank_steps_to_fill_in(self):
        text = "zzz qqq"
        r = routes(**{"POST /hounds/english": [200, B.english_answer(text)]})
        f = B.build(r, actions=[dict(do="set", sel="[data-hook='english-input']", value=text, wait=20),
                                dict(do="click", sel="[data-hook='english-go']", wait=200)], queries=self.Q)["final"]
        self.assertEqual(f["cards"], 1)
        self.assertIn("steps below are blank", f["status"])


def dog_row(version_no=3):
    return B.dog("u-1", "Dog One", version_no=version_no)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class SavingMakesTheNextVersion(unittest.TestCase):
    EXPECT = "Saving makes version 4; the old version keeps its record."

    def test_the_page_says_it_beside_the_button(self):
        r = routes(**{"/hounds/mine": [200, {"hounds": [dog_row(3)], "limit_running": 3}]})
        out = B.build(r, **SIGNED, actions=[dict(do="click", sel="[data-hook='edit-dog']", index=0, wait=200)], queries=[q("note", "[data-hook='version-note']")])
        self.assertEqual(out["final"]["note"], self.EXPECT)
        self.assertLess(HTML.index('data-hook="build-submit"'), HTML.index('data-hook="version-note"'))
        blank = B.build(routes(), actions=[BLANK], queries=[q("note", "[data-hook='version-note']")])
        self.assertEqual(blank["final"]["note"], "")

    def test_the_studio_says_it_too_and_runs_the_same_steps(self):
        mine_dog = dog_row(3)
        mine_dog["rule_sentences"] = ["MLB moneylines: it backs the underdog."]
        r = K.TheStudio.routes(K.TheStudio, [K.dog("u-1")], **{
            "/hounds/mine": [200, {"hounds": [mine_dog], "limit_running": 3}], "/sports/season": [200, SEASON], DRILL: [200, HIND],
            "POST /hounds/builder/preview": [200, B.preview_answer()]})
        out = K.run_page("kennel", routes=r, **K.SIGNED, settleMs=500, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", label="edit", wait=3500)], queries=[
            q("note", "[data-hook='version-note']"), CHIPS, q("price", "[data-hook='price-range']", "count"), q("quick", "[data-quick]", "count"),
            q("sliders", "[data-slider]", "count"), q("line", "[data-hook='hind-line']"), q("dock", "[data-dock]", "count")])
        f = out["final"]
        self.assertEqual(f["note"], self.EXPECT)
        self.assertTrue(any(c.startswith("NBA · 58 games coming up") for c in f["chips"]), f["chips"])
        self.assertEqual(f["price"], 1)
        self.assertGreaterEqual(f["quick"], 4)
        self.assertGreaterEqual(f["sliders"], 3)
        self.assertEqual(f["dock"], 1)
        self.assertIn("hindsight, not counted", f["line"])


class TheWordsStayHonest(unittest.TestCase):
    FILES = {"page": HTML, "script": JS, "skeleton": SKELETON}

    def user_text(self):
        for name, text in self.FILES.items():
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            text = re.sub(r"(?m)^\s*//.*$", "", text)
            yield name, text

    def test_no_dog_beta_new_or_profit_words_in_what_a_member_reads(self):
        for name, text in self.user_text():
            for m in re.finditer(r'(?:text|placeholder|title|aria-label|label|note): ?[`"]([^`"]+)[`"]|>([^<>{}\n]{3,})<', text):
                words = (m.group(1) or m.group(2) or "")
                self.assertNotRegex(words.lower(), r"\bdogs?\b|\bbeta\b|\bnew\b(?! version)|guarantee|profit|\bedge\b", f"{name}: {words}")

    def test_the_hindsight_line_always_carries_its_label(self):
        self.assertIn("(hindsight, not counted)", JS)
        self.assertIn("Hindsight, not counted in the record", JS)

    def test_the_page_uses_no_script_tag_of_its_own_beyond_the_module(self):
        self.assertEqual(len(re.findall(r"<script\b", HTML)), len(re.findall(r"<script\b[^>]*src=", HTML)))


if __name__ == "__main__":
    unittest.main()
