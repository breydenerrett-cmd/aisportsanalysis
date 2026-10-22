"""Unleash finds plays (2026-10-22): the 2026-10-21 report and the in-play opt-in.

THE REPORT. DRAKEO (0 settled, 5 open tickets, 5 a day) was unleashed: "Checked 60 games - Nothing to lock yet", then
"already running", and no picks. Three faults, each pinned here:

  1. "running" meant "has any bet ever" and a running hound was only SHOWN. Unleash never evaluated its new games.
  2. A hound created after a game's lock skipped that game for good ("hound_created_after_lock"), so every game starting
     within the lock window (120/180 minutes: the games "about to be in play") was passed over by a new hound.
  3. The day view listed only rows whose slate date was today, so a hound with open tickets showed none, and
     "Nothing to lock yet" never said why. It now lists every open ticket and counts the reason per game.

THE FEATURE. ``bet_in_play`` (default off) lets Unleash and the runner bet a game already started, at the price on
the live board AT the evaluation instant (never a later capture), refusing a live board older than
``LIVE_MAX_AGE_MINUTES``. The -200 cap, the daily limit and one side per game hold.

Fixtures: the game starts 23:10Z (unless a test says otherwise); a 120-minute lock is 21:10Z.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from src.hounds import user_engine, user_spec
from src.hounds.english import render
from src.hounds.interact import common, unleash
from tests import _hounds_rules_fixtures as RF
from tests._hounds_user_fixtures import BOOKS, board_rows, utc
from tests.hounds_web_runner import HAS_NODE, run_page
from tests.test_kennel_page import SIGNED, TheStudio, dog as kennel_dog, q
from tests.test_unleash_web import HOOK, OPEN, routes

OWNER = 7
START = "2026-10-20T23:10:00Z"


TEAMS = {"g2": ("Texas Rangers", "Detroit Tigers"), "g3": ("Houston Astros", "Oakland Athletics")}


def game(event, observed, away, home, start, books=BOOKS):
    """Distinct teams per event: the same teams on one day are one game to the one-side guard."""
    kw = {"home": TEAMS[event][0], "away": TEAMS[event][1]} if event in TEAMS else {}
    return board_rows(observed, event_id=event, start=start, moneyline=[(b, home, away) for b in books], **kw)


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "l.jsonl")
        players = RF.patch_players()
        players.start()
        self.addCleanup(players.stop)

    def dog(self, created="2026-10-20T06:00:00Z", rules=None, **over):
        h = RF.hound("u-find", created_at=created, max_bets_per_day=over.pop("max_bets_per_day", 5),
                     rules=rules or [RF.rule(side="away", price_min=100, price_max=250)], **over)
        return common.Dog(id=h["id"], kind=common.KIND_USER, name="Finder", hound=h, owner_user_id=OWNER,
                          status="running", root_id=h["id"])

    def go(self, rows, now, dog=None):
        return unleash.unleash(dog or self.dog(), OWNER, now=utc(now), rows=rows, ledger=self.ledger,
                               game_pk_index=RF.PK_INDEX, facts=RF.facts(), prop_rows=[], mlb_results={},
                               nfl_results=lambda _d: {}, allsports_results={}, refresh_stats=lambda: None,
                               manual_ledger=os.path.join(self._tmp.name, "m.jsonl"))

    def bets(self):
        return [r for r in user_engine.read_ledger(self.ledger) if r.get("kind") == user_engine.KIND_BET]


class RunningHoundStillEvaluates(_Case):
    def test_a_hound_with_a_bet_places_a_new_game_on_the_board(self):
        """Regression (a): the old code skipped the engine for any hound with a bet on its record."""
        first = game("g1", "2026-10-20T17:00:00Z", 120, -140, "2026-10-20T23:10:00Z")
        self.assertEqual(self.go(first, "2026-10-20T18:00:00Z")["placed_now"], 1)
        both = first + game("g2", "2026-10-20T18:20:00Z", 130, -150, "2026-10-20T23:40:00Z")
        out = self.go(both, "2026-10-20T18:30:00Z")
        self.assertTrue(out["already_running"])
        self.assertEqual(out["placed_now"], 1)
        self.assertEqual(sorted(r["event_id"] for r in self.bets()), ["g1", "g2"])
        again = self.go(both, "2026-10-20T18:31:00Z")
        self.assertEqual(again["placed_now"], 0)                      # idempotent: the bet id, not a flag, stops a repeat
        self.assertEqual(len(self.bets()), 2)

    def test_the_daily_limit_still_holds_for_a_running_hound(self):
        rows = []
        for i in range(3):
            rows += game(f"g{i}", "2026-10-20T17:00:00Z", 120, -140, f"2026-10-20T23:{10 + i}:00Z")
        out = self.go(rows, "2026-10-20T18:00:00Z", dog=self.dog(max_bets_per_day=1))
        self.assertEqual(out["placed_now"], 1)
        counts = {c["code"]: c["count"] for c in out["why"]["counts"]}
        self.assertEqual(counts, {"on_record": 1, "over_limit": 2})


class GamesAboutToStart(_Case):
    def test_a_hound_born_after_the_lock_still_bets_a_game_that_has_not_started(self):
        """Regression (b): lock 21:10Z passed at 22:00Z, the game starts 23:10Z, the hound was made at 21:30Z."""
        rows = game("g1", "2026-10-20T21:05:00Z", 120, -140, START) + game("g1", "2026-10-20T22:20:00Z", 300, -400, START)
        out = self.go(rows, "2026-10-20T22:00:00Z", dog=self.dog(created="2026-10-20T21:30:00Z"))
        self.assertEqual(out["placed_now"], 1)
        row = self.bets()[0]
        self.assertEqual(row["board_observed_utc"], "2026-10-20T21:05:00Z")      # the board standing at 22:00, not the 22:20 one
        self.assertEqual(row["price"], 120)

    def test_a_game_that_has_started_is_never_bet_without_the_opt_in(self):
        rows = game("g1", "2026-10-20T21:05:00Z", 120, -140, START) + game("g1", "2026-10-20T23:25:00Z", 125, -145, START)
        out = self.go(rows, "2026-10-20T23:30:00Z")
        self.assertEqual(self.bets(), [])
        self.assertEqual({c["code"]: c["count"] for c in out["why"]["counts"]}, {"started": 1})


class PerReasonCounts(_Case):
    def test_every_game_lands_in_exactly_one_bucket_and_the_next_check_is_named(self):
        rows = []
        rows += game("fit", "2026-10-20T19:00:00Z", 120, -140, "2026-10-20T23:10:00Z")
        rows += game("band", "2026-10-20T19:00:00Z", 400, -600, "2026-10-20T23:40:00Z")
        rows += game("books", "2026-10-20T19:00:00Z", 120, -140, "2026-10-20T23:30:00Z", books=BOOKS[:2])
        rows += game("started", "2026-10-20T17:00:00Z", 120, -140, "2026-10-20T19:00:00Z")
        rows += game("late", "2026-10-20T21:00:00Z", 120, -140, "2026-10-20T23:50:00Z")      # first capture is after now
        out = self.go(rows, "2026-10-20T20:00:00Z")
        counts = {c["code"]: c["count"] for c in out["why"]["counts"]}
        self.assertEqual(counts, {"on_record": 1, "started": 1, "no_board": 1, "too_few_books": 1, "price_band": 1})
        self.assertEqual(sum(counts.values()), out["why"]["checked"], out["why"]["counts"])
        self.assertEqual(out["why"]["placed"], 1)
        self.assertIn("Checked 5 games: ", out["why"]["text"])
        self.assertIn("1 price outside +100 to +250", out["why"]["text"])
        self.assertTrue(out["why"]["text"].endswith("→ placed 1"))
        nxt = out["next_check"]
        self.assertEqual((nxt["event_id"], nxt["when_utc"]), ("books", "2026-10-20T21:30:00Z"))   # 23:30 start, 120-minute lock

    def test_nothing_left_to_check_says_so(self):
        out = self.go(game("done", "2026-10-20T17:00:00Z", 120, -140, "2026-10-20T19:00:00Z"), "2026-10-20T20:00:00Z")
        self.assertIsNone(out["next_check"])


class TheDayListsOpenTickets(_Case):
    """Regression (c): five open tickets, an empty day view."""

    def test_open_tickets_are_listed_with_a_status_on_the_same_day_and_the_next(self):
        rows = game("g1", "2026-10-20T17:00:00Z", 120, -140, START)
        self.go(rows, "2026-10-20T18:00:00Z")
        for now in ("2026-10-20T22:00:00Z", "2026-10-21T05:00:00Z"):     # same Eastern day; after midnight Eastern
            with self.subTest(now=now):
                out = self.go(rows, now)
                self.assertEqual([t["event_id"] for t in out["open_tickets"]], ["g1"])
                self.assertEqual(out["open_tickets"][0]["status"], "not_started" if now < START else "in_play")
                self.assertIn("1 open ticket", out["headline"])
                self.assertNotIn("Nothing to lock yet", json.dumps(out))

    def test_the_wording_never_blames_the_hound_for_a_tap_that_placed_nothing(self):
        out = self.go(game("g1", "2026-10-20T17:00:00Z", 400, -600, START), "2026-10-20T18:00:00Z")
        self.assertIn("reasons are below", out["headline"])
        self.assertEqual(out["why"]["counts"][0]["code"], "price_band")


class InPlayBets(_Case):
    def live_dog(self, **kw):
        return self.dog(bet_in_play=True, **kw)

    def rows(self, live_at="2026-10-20T23:27:00Z", live_away=130):
        rows = game("g1", "2026-10-20T21:05:00Z", 120, -140, START)
        rows += game("g1", live_at, live_away, -150, START)                   # the in-play capture
        rows += game("g1", "2026-10-20T23:45:00Z", 140, -160, START)          # planted LATER price: must be ignored
        return rows

    def test_the_setting_defaults_to_off_and_is_validated(self):
        self.assertFalse(user_spec.bets_in_play(RF.hound()["spec"]))
        self.assertNotIn("bet_in_play", RF.hound()["spec"])
        self.assertIs(user_spec.builder_menu()["bet_in_play"]["default"], False)
        on = user_spec.validate_spec(RF.v2(bet_in_play=True))
        self.assertTrue(user_spec.bets_in_play(on))
        self.assertNotEqual(user_spec.spec_hash(on), user_spec.spec_hash(user_spec.validate_spec(RF.v2())))
        with self.assertRaises(user_spec.SpecError):
            user_spec.validate_spec(RF.v2(bet_in_play="yes"))
        self.assertIn("already in play", " ".join(render.global_sentences(on)))

    def test_off_means_a_started_game_is_not_bet(self):
        self.go(self.rows(), "2026-10-20T23:30:00Z")
        self.assertEqual(self.bets(), [])

    def test_an_in_play_bet_uses_only_the_price_standing_at_evaluation(self):
        out = self.go(self.rows(), "2026-10-20T23:30:00Z", dog=self.live_dog())
        row = self.bets()[0]
        self.assertEqual((row["price"], row["board_observed_utc"]), (130, "2026-10-20T23:27:00Z"))   # not the 23:45 +140
        self.assertTrue(row["live"])
        self.assertEqual(row["live_price_observed_utc"], "2026-10-20T23:27:00Z")
        self.assertEqual(row["recorded_utc"], "2026-10-20T23:30:00Z")
        self.assertIn("A live bet", row["reason"])
        pick = out["picks"][0]
        self.assertTrue(pick["live"])
        self.assertEqual(pick["live_price_at_utc"], "2026-10-20T23:27:00Z")

    def test_a_stale_live_board_is_skipped_with_its_reason(self):
        out = self.go(self.rows(live_at="2026-10-20T23:20:00Z"), "2026-10-20T23:30:00Z", dog=self.live_dog())
        self.assertEqual(self.bets(), [])
        self.assertEqual({c["code"] for c in out["why"]["counts"]}, {"live_price_too_old"})
        self.assertIn("live price too old", out["why"]["text"])

    def test_a_pre_game_board_is_never_passed_off_as_a_live_one(self):
        rows = game("g1", "2026-10-20T21:05:00Z", 120, -140, START)
        out = self.go(rows, "2026-10-20T23:30:00Z", dog=self.live_dog())
        self.assertEqual(self.bets(), [])
        self.assertEqual({c["code"] for c in out["why"]["counts"]}, {"no_live_board"})

    def test_the_minus_200_cap_holds_in_play(self):
        rows = game("g1", "2026-10-20T21:05:00Z", -250, -140, START) + game("g1", "2026-10-20T23:27:00Z", -250, 200, START)
        dog = self.live_dog(rules=[RF.rule(side="away", price_min=-199, price_max=1000)])
        self.go(rows, "2026-10-20T23:30:00Z", dog=dog)
        self.assertEqual(self.bets(), [])

    def test_one_side_per_game_holds_in_play(self):
        """A pre-game away moneyline is held; the live spread rule would back the home side: refused."""
        rules = [RF.rule(side="away", price_min=100, price_max=250),
                 RF.rule(markets=["spread"], side="home", price_min=-199, price_max=1000)]
        pre = game("g1", "2026-10-20T21:05:00Z", 120, -140, START)
        self.go(pre, "2026-10-20T22:00:00Z", dog=self.live_dog(rules=rules))
        self.assertEqual(len(self.bets()), 1)
        live = pre + board_rows("2026-10-20T23:27:00Z", event_id="g1", start=START,
                                spread=(-1.5, [(b, -110, -110) for b in BOOKS]))
        self.go(live, "2026-10-20T23:30:00Z", dog=self.live_dog(rules=rules))
        self.assertEqual([(r["market"], r["side"]) for r in self.bets()], [("moneyline", "away")])

    def test_a_game_already_bet_pre_game_is_not_bet_again_live(self):
        self.go(game("g1", "2026-10-20T21:05:00Z", 120, -140, START), "2026-10-20T22:00:00Z", dog=self.live_dog())
        self.go(self.rows(), "2026-10-20T23:30:00Z", dog=self.live_dog())
        self.assertEqual(len(self.bets()), 1)
        self.assertNotIn("live", self.bets()[0])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheUi(unittest.TestCase):
    def data(self, **over):
        case = _Case("setUp")
        case.setUp()
        try:
            out = case.go(game("g1", "2026-10-20T17:00:00Z", 400, -600, START), "2026-10-20T18:00:00Z")
        finally:
            case._tmp.cleanup()
        out = json.loads(json.dumps(out))
        out.update(over)
        return out

    def test_the_page_shows_the_reasons_the_next_game_and_the_open_tickets(self):
        ticket = {"event_id": "g1", "market": "moneyline", "market_label": "Moneyline", "selection": "Boston Red Sox to win",
                  "game": "A @ B", "price_average": 120, "stake_units": 1.0, "status": "not_started",
                  "status_text": "Not started yet", "live": True, "live_price_at_utc": "2026-10-20T23:27:00Z"}
        data = self.data(open_tickets=[ticket])
        out = run_page("kennel", routes=routes(data), **SIGNED, actions=[dict(OPEN, capture=[
            q("why", HOOK("unleash-why")), q("next", HOOK("unleash-next")), q("steps", HOOK("unleash-steps") + " li", "texts"),
            q("open", HOOK("unleash-open-ticket"), "count"), q("live", HOOK("unleash-live-chip"), "texts"),
            q("status", HOOK("unleash-ticket-status"), "texts")])])
        c = out["captures"]["open"]
        self.assertIn("Checked 1 game: 1 price outside +100 to +250", c["why"])
        self.assertTrue(c["why"].endswith("placed 0"))
        self.assertEqual(c["steps"][-1], "1 open ticket, none new")
        self.assertEqual((c["open"], c["status"]), (1, ["Not started yet"]))
        self.assertRegex(c["live"][0], r"^Live bet · price at \d\d:\d\d$")

    def test_the_card_never_says_bets_0_beside_open_tickets(self):
        d = kennel_dog("u-1", bets=0, open_bets=5)
        out = run_page("kennel", routes=TheStudio().routes([d]), **SIGNED, actions=[dict(do="wait", label="card", wait=200, capture=[
            q("bets", "[data-hook='dog-bets']", "texts")])])
        self.assertEqual(out["captures"]["card"]["bets"], ["5 (5 open)"])

    def test_the_studio_record_tab_agrees(self):
        d = kennel_dog("u-1", bets=0, open_bets=5)
        out = run_page("kennel", routes=TheStudio().routes([d]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=120),
            dict(do="click", sel="[role='tab'][data-tab='record']", label="record", wait=300, capture=[
                q("stats", "[data-hook='studio-record-stats'] dd", "texts")])])
        self.assertEqual(out["captures"]["record"]["stats"][3:], ["5 (5 open)", "5"])


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
