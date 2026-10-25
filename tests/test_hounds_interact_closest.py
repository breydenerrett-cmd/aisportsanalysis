"""The closest game when nothing fully fits, the research answer, and times the browser formats (owner, 2026-10-25).

WHY THESE TESTS. "If you had to take a bet no matter what" got "The signs are quiet" with 131 games on the board: the rule
had nothing that fully fit, and nothing else was offered. The fix is a SUGGESTION of the closest game (most conditions
passed), never placed, never -200 or worse, never a started or held game. These tests pin each of those guards with a
hand-made payload, so no board or store is read.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import unittest
from datetime import datetime, timezone

from src.hounds import user_engine
from src.hounds.interact import ask, fire, right_now

NOW = datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc)      # 9:00 am PT, Sunday: today's games are still ahead

SPEC = {"sports": ["MLB"], "stake_units": 1.0, "rank_by": "earliest_lock", "markets": ["moneyline"]}


def near(event_id, *, price=120, start="2026-10-25T23:10:00Z", score=4, misses=None, market="moneyline",
         selection="Boston Red Sox to win"):
    """A closest-candidate row in the shape fire.fire's payload carries."""
    return {
        "event_id": event_id, "game": f"Game {event_id}", "sport": "MLB", "market": market,
        "market_label": "Moneyline", "side": "away", "selection": selection, "line": None,
        "price_average": price, "price_best": price, "best_book": "BookA", "n_books": 3,
        "start_utc": start, "minutes_to_start": 300, "day_label": "Today", "stale": False,
        "board_age_minutes": 5.0, "score": score, "of": 5, "reason": "", "over_daily_limit": False,
        "misses": misses if misses is not None else ["the price +120 is outside my band of +200 to +250"],
        "manual": {"can_record": False, "blocked": None},
    }


def payload(closest, picks=None, miss_counts=None, games_considered=4):
    return {"picks": picks or [], "recorded": [], "closest_candidates": closest, "closest_misses": [],
            "miss_counts": miss_counts or {"outside_price_band": 3, "rule_not_met": 1},
            "games_considered": games_considered, "games": [], "next_game": None, "live_elsewhere": None}


def view(pay, held=None):
    return right_now.view_from_payload(pay, dog_id="d1", dog_name="Rex", kind="user", spec=SPEC, persona=None,
                                       held=held or [], now=NOW)


class TheCloseness(unittest.TestCase):
    """user_engine.closeness: the conditions counted, and the cap never bent."""

    def setUp(self):
        from tests._hounds_user_fixtures import AWAY, EVENT, HOME, board_rows, hound, utc
        self.utc = utc
        self.hound = hound
        self.board_rows = board_rows
        self.AWAY, self.HOME, self.EVENT = AWAY, HOME, EVENT

    def test_a_price_outside_the_band_scores_four_of_five_and_names_the_band(self):
        from tests._hounds_user_fixtures import standard_rows
        from src.hounds.user_engine import build_event_game
        game = build_event_game(standard_rows(), self.EVENT)
        spec = dict(self.hound()["spec"], price_min=200, price_max=250, side_rule="favourite")
        lock = game.commence
        out = user_engine.closeness(spec, game, "moneyline", lock, game.commence)
        self.assertIsNotNone(out)
        self.assertEqual(out["of"], 5)
        self.assertIn("outside my band", " ".join(out["misses"]))
        self.assertGreaterEqual(out["score"], 3)

    def test_minus_200_or_worse_is_never_a_closest_candidate(self):
        from src.hounds.user_engine import build_event_game
        from tests._hounds_user_fixtures import standard_rows
        game = build_event_game(standard_rows(), self.EVENT)
        spec = dict(self.hound()["spec"], side_rule="favourite", price_min=-1000, price_max=-150)
        from unittest import mock
        with mock.patch.object(user_engine, "average_price", return_value=-250):      # the board's average is -250
            self.assertIsNone(user_engine.closeness(spec, game, "moneyline", game.commence, game.commence))


class TheClosestView(unittest.TestCase):
    """right_now.view_from_payload: nothing fresh -> the closest, under the same guards as a full pick."""

    def test_nothing_fully_fits_still_offers_the_closest_game(self):
        out = view(payload([near("e1")]))
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["closest"][0]["selection"], "Boston Red Sox to win")
        self.assertEqual(out["closest"][0]["misses"], ["the price +120 is outside my band of +200 to +250"])

    def test_a_started_game_is_never_the_closest(self):
        out = view(payload([near("e1", start="2026-10-25T14:00:00Z")]))
        self.assertEqual(out["closest"], [])

    def test_minus_200_is_never_the_closest(self):
        out = view(payload([near("e1", price=-250)]))
        self.assertEqual(out["closest"], [])

    def test_a_held_game_is_never_the_closest(self):
        held = [{"event_id": "e1", "market": "moneyline", "side": "away"}]
        out = view(payload([near("e1")]), held=held)
        self.assertEqual(out["closest"], [])

    def test_one_closest_per_game_and_the_most_conditions_first(self):
        rows = [near("e1", score=3), near("e1", score=4, selection="Other side"), near("e2", score=4), near("e3", score=5)]
        out = view(payload(rows))
        self.assertEqual([c["event_id"] for c in out["closest"]], ["e3", "e2", "e1"])
        self.assertEqual(len({c["event_id"] for c in out["closest"]}), len(out["closest"]))

    def test_a_full_fit_leaves_the_closest_list_empty(self):
        pick = dict(near("e9", price=150, score=5), misses=[], reason="rule")
        out = view(payload([near("e1")], picks=[pick]))
        self.assertEqual(len(out["candidates"]), 1)
        self.assertEqual(out["closest"], [])


class TheAskAnswers(unittest.TestCase):
    """The owner's two questions, end to end through ask.answer with a payload injected."""

    def ctx(self, pay):
        return ask.AskContext(dog_id="d1", name="Rex", kind="user", spec=SPEC, now=NOW, fire_fn=lambda: pay)

    def test_forced_bet_gets_the_closest_pick_labelled_with_what_it_misses(self):
        out = ask.answer("If you had to take a bet no matter what, what would it be?", self.ctx(payload([near("e1")])))
        self.assertEqual(out["intent"], "picks_now")
        self.assertIn("Nothing fully fits my rule. Closest: Boston Red Sox to win +120", out["answer"])
        self.assertIn("it misses: the price +120 is outside my band of +200 to +250.", out["answer"])
        self.assertTrue(out["cards"][0]["closest"])

    def test_research_says_what_was_checked_today(self):
        out = ask.answer("Show me the research and results", self.ctx(payload([near("e1")])))
        self.assertEqual(out["intent"], "research")
        text = out["answer"]
        self.assertIn("Today I checked 4 games and 0 passed my rule.", text)
        self.assertIn("3 priced outside the band", text)
        self.assertIn("Closest: Boston Red Sox to win +120. It misses:", text)
        self.assertNotIn("graded bets", text)

    def test_no_closest_and_no_fire_is_said_plainly(self):
        out = ask.answer("Show me the research and results", ask.AskContext(dog_id="d1", name="Rex", kind="house"))
        self.assertEqual(out["intent"], "research")
        self.assertIn("cannot run a rule on demand", out["answer"])


class TheTimeTokens(unittest.TestCase):
    """The server writes tokens; the plain reader gets Eastern. The browser's own zone is tested in TheBrowserZone."""

    def test_stamp_writes_a_token_with_utc_inside(self):
        moment = datetime(2026, 10, 25, 19, 45, tzinfo=timezone.utc)
        self.assertEqual(fire.stamp("t", moment), "[[t:2026-10-25T19:45:00Z]]")
        self.assertEqual(fire.stamp("t", None), "")

    def test_resolve_plain_writes_eastern_day_words_and_clock(self):
        moment = datetime(2026, 10, 25, 19, 45, tzinfo=timezone.utc)                  # 3:45 pm EDT
        text = f"Next: {fire.stamp('t', moment)} | {fire.stamp('d', moment)} | {fire.stamp('w', moment)}"
        self.assertEqual(fire.resolve_plain(text, NOW), "Next: Today 3:45 pm ET | Oct 25 at 3:45 pm ET | Sun 3:45 pm ET")

    def test_the_next_game_line_carries_a_token_not_a_clock(self):
        moment = datetime(2026, 10, 26, 22, 15, tzinfo=timezone.utc)
        line = fire.next_game_line(NOW, [("A @ B", moment, moment)])
        self.assertIn("[[w:2026-10-26T22:15:00Z]]", line)
        self.assertNotIn("PM", line)

    def test_no_user_facing_text_still_says_utc(self):
        moment = datetime(2026, 10, 25, 19, 25, tzinfo=timezone.utc)
        self.assertNotIn("UTC", ask._when(fire.stamp("d", moment)))


class TheBrowserZone(unittest.TestCase):
    """web/js/local-time.js in node, with the zone pinned, so the viewer's clock is what the test checks."""

    def run_node(self, zone, expr):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        module = pathlib.Path(__file__).resolve().parent.parent / "web" / "js" / "local-time.js"
        script = (f"import({json.dumps(module.as_uri())}).then((m) => {{ const now = new Date('2026-10-25T16:00:00Z');"
                  f" process.stdout.write(JSON.stringify({expr})); }});")
        env = dict(os.environ, TZ=zone)
        out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_today_in_pacific_time(self):
        got = self.run_node("America/Los_Angeles", "m.localizeTimes('Next: [[t:2026-10-25T19:45:00Z]]', now)")
        self.assertEqual(got, "Next: Today 12:45 PM PT")

    def test_the_same_moment_in_eastern_time(self):
        got = self.run_node("America/New_York", "m.localizeTimes('[[t:2026-10-25T19:45:00Z]]', now)")
        self.assertEqual(got, "Today 3:45 PM ET")

    def test_a_recorded_time_names_the_date(self):
        got = self.run_node("America/Los_Angeles", "m.localizeTimes('[[d:2026-10-25T19:25:00Z]]', now)")
        self.assertEqual(got, "Oct 25 at 12:25 PM PT")

    def test_a_bad_token_is_left_out_not_shown_raw(self):
        got = self.run_node("America/Los_Angeles", "m.localizeTimes('x [[t:not-a-time]] y', now)")
        self.assertEqual(got, "x  y")


class TheCopy(unittest.TestCase):
    """Owner rules that are plain text in the page code: no "new" wording, market keys in words."""

    def read(self, rel):
        with open(os.path.join(os.path.dirname(__file__), "..", rel), encoding="utf-8") as fh:
            return fh.read()

    def test_no_new_wording_in_the_fresh_hound_lines(self):
        self.assertNotIn("New here", self.read("web/js/hound-lines.js"))
        self.assertIn("Waiting for its first game.", self.read("web/js/hound-lines.js"))

    def test_market_keys_have_plain_words_on_the_hero(self):
        board = self.read("web/js/hounds-board.js")
        self.assertIn("batter_hits: \"hits\"", board)
        self.assertIn("batter_total_bases: \"total bases\"", board)


if __name__ == "__main__":
    unittest.main()
