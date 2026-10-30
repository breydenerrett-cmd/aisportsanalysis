"""The live game state's plumbing: the cache and its stale guard, the append-only snapshot log, the name matching of
``state_for``, the loop (never under pytest, off by flag, bounded, outlives a bad pass), and the three places that carry it
(the /sports/now board, GET /hounds/live, /health).

No network and no real clock anywhere: fetches are functions over tests/fixtures/live_state/, every time is injected, and
the log writes to a temp directory.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.hounds import live_settle
from src.sports import allsports_view as V
from src.sports import live_state
from src.sports.live_state import loop, names, nhl, store, tennis
from tests import live_state_support as S
from tests.test_allsports_view import mrow

REPO = Path(__file__).resolve().parent.parent


def fresh_pass(now=S.NOW, **kw):
    """One loop pass over the captures with the board's events and the log directory injected."""
    return loop.run_pass(kw.pop("events", lambda: []), now=now, fetch_json=S.fixture_fetch, schedule=kw.pop("schedule", {}), **kw)


class Isolated(unittest.TestCase):
    def setUp(self):
        store.clear()
        tennis.MEMORY.clear()
        loop.reset_schedule()
        self.addCleanup(store.clear)
        self.addCleanup(tennis.MEMORY.clear)
        self.addCleanup(loop.reset_schedule)
        self.log = Path(tempfile.mkdtemp(prefix="livestate_"))


class TheNames(unittest.TestCase):
    def club(self, abbrev, name):
        return {"abbrev": abbrev, "name": name}

    def test_accents_abbreviations_and_the_forms_a_book_uses(self):
        cases = [
            ("Montreal Canadiens", self.club("MTL", "Montréal Canadiens")), ("Montréal Canadiens", self.club("MTL", "Montréal Canadiens")),
            ("St Louis Blues", self.club("STL", "St. Louis Blues")), ("Saint Louis Blues", self.club("STL", "St. Louis Blues")),
            ("St. Louis Blues", self.club("STL", "St. Louis Blues")),
            ("Utah Mammoth", self.club("UTA", "Utah Mammoth")), ("Utah Hockey Club", self.club("UTA", "Utah Mammoth")),
            ("NY Rangers", self.club("NYR", "New York Rangers")), ("New York Rangers", self.club("NYR", "New York Rangers")),
            ("LA Kings", self.club("LAK", "Los Angeles Kings")), ("Los Angeles Kings", self.club("LAK", "Los Angeles Kings")),
            ("Tampa Bay Lightning", self.club("TBL", "Tampa Bay Lightning")), ("WSH", self.club("WSH", "Washington Capitals")),
            ("wsh", self.club("WSH", "Washington Capitals")),
        ]
        for name, team in cases:
            with self.subTest(name=name):
                self.assertTrue(names.nhl_team_matches(name, team))

    def test_all_32_clubs_match_their_own_full_name_and_abbreviation_and_no_other_club(self):
        clubs = {"ANA": "Ducks", "BOS": "Bruins", "BUF": "Sabres", "CGY": "Flames", "CAR": "Hurricanes", "CHI": "Blackhawks",
                 "COL": "Avalanche", "CBJ": "Blue Jackets", "DAL": "Stars", "DET": "Red Wings", "EDM": "Oilers", "FLA": "Panthers",
                 "LAK": "Kings", "MIN": "Wild", "MTL": "Canadiens", "NSH": "Predators", "NJD": "Devils", "NYI": "Islanders",
                 "NYR": "Rangers", "OTT": "Senators", "PHI": "Flyers", "PIT": "Penguins", "SJS": "Sharks", "SEA": "Kraken",
                 "STL": "Blues", "TBL": "Lightning", "TOR": "Maple Leafs", "UTA": "Mammoth", "VAN": "Canucks",
                 "VGK": "Golden Knights", "WSH": "Capitals", "WPG": "Jets"}
        self.assertEqual(set(clubs), set(nhl._PLACES))
        teams = {abbrev: {"abbrev": abbrev, "name": f"{nhl._PLACES[abbrev]} {nick}"} for abbrev, nick in clubs.items()}
        for abbrev, team in teams.items():
            for other_abbrev, other in teams.items():
                self.assertEqual(names.nhl_team_matches(team["name"], other), abbrev == other_abbrev, (team["name"], other["name"]))
                self.assertEqual(names.nhl_team_matches(abbrev, other), abbrev == other_abbrev, (abbrev, other["name"]))

    def test_a_different_club_or_a_bare_nickname_or_nothing_is_not_a_match(self):
        team = self.club("NYR", "New York Rangers")
        for name in ("New York Islanders", "Rangers", "New York", "", None, "Glasgow Rangers", "NYI"):
            with self.subTest(name=name):
                self.assertFalse(names.nhl_team_matches(name, team))
        self.assertFalse(names.nhl_team_matches("New York Rangers", {"abbrev": "NYR", "name": None}))     # an unknown full name never matches by name

    def test_players_match_by_folded_name_only(self):
        self.assertTrue(names.same_player("Alicia Herrero Liñana", "Alicia Herrero Linana"))
        self.assertTrue(names.same_player("Jan-Lennard Struff", "Jan Lennard Struff"))
        self.assertFalse(names.same_player("Alicia Herrero", "Alicia Herrero Linana"))
        self.assertFalse(names.same_player("", ""))
        self.assertFalse(names.same_player(None, "Maya Joint"))

    def test_a_surname_label_drops_only_the_first_name(self):
        self.assertEqual([names.last_word_name(n) for n in ("Maya Joint", "Alicia Herrero Linana", "Cher", "")],
                         ["Joint", "Herrero Linana", "Cher", ""])


class TheStaleGuard(Isolated):
    def test_no_state_is_shown_past_180_seconds_and_one_just_inside_is(self):
        fresh_pass()
        self.assertIsNotNone(live_state.state_for("NHL", "San Jose Sharks", "Vancouver Canucks", S.START, now=S.at(179)))
        self.assertIsNone(live_state.state_for("NHL", "San Jose Sharks", "Vancouver Canucks", S.START, now=S.at(181)))

    def test_an_old_detail_layer_hides_only_its_own_keys(self):
        fresh_pass()
        # the score keeps being read; the box score stops (the detail read failed ever since)
        nhl.fetch_and_store(S.at(100), lambda url: S.load("nhl_score_now.json") if url == nhl.SCORE_URL else (_ for _ in ()).throw(OSError("x")),
                            max_requests=1)
        view = live_state.state_for("NHL", "San Jose Sharks", "Vancouver Canucks", S.START, now=S.at(200))
        self.assertIsNotNone(view)
        self.assertEqual((view["strength"], view["goalies"], view["skaters"], view["goals_by_period"]), (None, None, None, None))
        self.assertIsNone(view["detail_as_of"])
        self.assertEqual(view["away"]["sog"], 12)                                  # the score read is still fresh and still shown
        self.assertEqual(view["line"], "2nd · 16:19 · SOG 12-8")

    def test_a_future_stamp_is_not_trusted(self):
        fresh_pass(now=S.at(600))
        self.assertIsNone(live_state.state_for("NHL", "San Jose Sharks", "Vancouver Canucks", S.START, now=S.NOW))

    def test_prune_forgets_old_games(self):
        fresh_pass()
        self.assertEqual(store.prune(S.at(7 * 3600)), 5)
        self.assertEqual(store.fresh_games("NHL", S.at(7 * 3600)), [])


class TheLookup(Isolated):
    def lookup(self, home, away, start=S.START, sport="NHL", now=None):
        return live_state.state_for(sport, home, away, start, now=now or S.at(10))

    def test_the_fixture_game_is_found_by_both_names_in_the_odds_feeds_orientation(self):
        fresh_pass()
        view = self.lookup("San Jose Sharks", "Vancouver Canucks")
        self.assertEqual((view["game_id"], view["state"], view["line"]), (S.GAME, "live", "2nd · 16:19 · SOG 12-8"))
        self.assertEqual(self.lookup("San Jose Sharks", "Vancouver Canucks", sport="icehockey_nhl")["game_id"], S.GAME)
        self.assertEqual(self.lookup("San Jose Sharks", "Vancouver Canucks", start=S.START.isoformat().replace("+00:00", "Z"))["game_id"], S.GAME)

    def test_the_other_orientation_is_no_answer_never_flipped(self):
        fresh_pass()
        self.assertIsNone(self.lookup("Vancouver Canucks", "San Jose Sharks"))

    def test_one_name_alone_or_a_wrong_name_is_no_answer(self):
        fresh_pass()
        self.assertIsNone(self.lookup("San Jose Sharks", "Anaheim Ducks"))
        self.assertIsNone(self.lookup("Sharks", "Canucks"))
        self.assertIsNone(self.lookup("", "Vancouver Canucks"))
        self.assertIsNone(self.lookup("San Jose Sharks", None))

    def test_abbreviations_and_a_book_s_spelling_find_the_game(self):
        fresh_pass()
        self.assertEqual(self.lookup("SJS", "VAN")["game_id"], S.GAME)
        self.assertEqual(self.lookup("Anaheim Ducks", "Buffalo Sabres")["in_intermission"], True)

    def test_a_start_outside_the_window_or_no_start_is_no_answer(self):
        fresh_pass()
        self.assertIsNone(self.lookup("San Jose Sharks", "Vancouver Canucks", start=S.START + timedelta(hours=13)))
        self.assertIsNotNone(self.lookup("San Jose Sharks", "Vancouver Canucks", start=S.START + timedelta(hours=11)))
        self.assertIsNone(self.lookup("San Jose Sharks", "Vancouver Canucks", start=None))
        self.assertIsNone(self.lookup("San Jose Sharks", "Vancouver Canucks", start="not a time"))

    def test_two_games_that_fit_are_no_answer(self):
        fresh_pass()
        twin = dict(store.get("NHL", S.GAME, S.NOW))
        twin["game_id"] = "2026020999"
        store.put_base("NHL", "2026020999", twin, S.at(5))                          # the same two clubs again within the window
        self.assertIsNone(self.lookup("San Jose Sharks", "Vancouver Canucks", now=S.at(10)))

    def test_an_unknown_sport_or_an_empty_cache_is_no_answer(self):
        self.assertIsNone(self.lookup("San Jose Sharks", "Vancouver Canucks"))          # nothing read yet
        fresh_pass()
        self.assertIsNone(self.lookup("A", "B", sport="CRICKET"))
        self.assertIsNone(self.lookup("A", "B", sport=None))

    def test_the_returned_dict_is_a_copy(self):
        fresh_pass()
        view = self.lookup("San Jose Sharks", "Vancouver Canucks")
        view["home"]["score"] = 99
        view["skaters"]["home"].clear()
        view["goals_by_period"].clear()
        again = self.lookup("San Jose Sharks", "Vancouver Canucks")
        self.assertEqual(again["home"]["score"], 0)
        self.assertEqual(len(again["skaters"]["home"]), 18)
        self.assertEqual(len(again["goals_by_period"]), 2)

    def test_tennis_is_found_by_the_two_names_in_either_order_and_laid_out_in_the_callers_order(self):
        for _ in range(2):
            loop.run_pass(lambda: [{"family": "TENNIS", "in_play": True, "_start": S.TENNIS_START}], now=S.TENNIS_NOW,
                          fetch_json=S.fixture_fetch, schedule={"NHL": S.TENNIS_NOW + timedelta(hours=1)}, log_dir=self.log)
        now = S.at(5, S.TENNIS_NOW)
        straight = live_state.state_for("TENNIS", "Kamilla Rakhimova", "Maya Joint", S.TENNIS_START, now=now)
        crossed = live_state.state_for("tennis_wta_toray", "Maya Joint", "Kamilla Rakhimova", S.TENNIS_START, now=now)
        self.assertEqual((straight["orientation"], crossed["orientation"]), ("straight", "crossed"))
        self.assertEqual((straight["home"]["name"], straight["away"]["name"]), ("Kamilla Rakhimova", "Maya Joint"))
        self.assertEqual((crossed["home"]["name"], crossed["away"]["name"]), ("Maya Joint", "Kamilla Rakhimova"))
        self.assertEqual(straight["line"], "Set 2 · 4-3 · Rakhimova serving · on serve · sets 0-1")
        self.assertEqual(crossed["line"], "Set 2 · 3-4 · Rakhimova serving · on serve · sets 1-0")
        self.assertEqual(live_state.state_for("TENNIS", "Maya Joint", "Alicia Herrero Liñana", S.TENNIS_START, now=now), None)
        self.assertIsNotNone(live_state.state_for("TENNIS", "Tamara Zidansek", "Alicia Herrero Liñana", S.TENNIS_START + timedelta(minutes=15), now=now))

    def test_two_tennis_matches_of_the_same_pair_are_no_answer(self):
        games = [{"game_id": "1", "start_utc": "2026-10-30T01:35:00Z", "players": [{"name": "A B"}, {"name": "C D"}]},
                 {"game_id": "2", "start_utc": "2026-10-30T05:00:00Z", "players": [{"name": "C D"}, {"name": "A B"}]}]
        self.assertIsNone(tennis.match("A B", "C D", S.TENNIS_START, games))
        self.assertEqual(tennis.match("A B", "C D", S.TENNIS_START, games[:1])["game_id"], "1")
        self.assertIsNone(tennis.match("A B", "A B", S.TENNIS_START, games[:1]))
        self.assertIsNone(tennis.match("A B", "C D", S.TENNIS_START + timedelta(hours=19), games[:1]))


class TheSnapshotLog(Isolated):
    def lines(self):
        files = sorted(self.log.glob("*.jsonl"))
        return [(f.name, [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]) for f in files]

    def test_the_first_pass_writes_one_line_per_live_game_to_a_file_named_for_the_utc_day(self):
        fresh_pass(log_dir=self.log)
        [(name, rows)] = self.lines()
        self.assertEqual(name, "2026-10-30.jsonl")
        self.assertEqual(sorted(r["id"] for r in rows), ["2026020211", "2026020212", S.GAME])
        self.assertTrue(all(r["sp"] == "NHL" and r["st"] == "live" for r in rows))

    def test_an_unchanged_game_appends_nothing_even_though_the_clock_ran(self):
        fresh_pass(log_dir=self.log)
        before = (self.log / "2026-10-30.jsonl").read_bytes()
        later = S.load("nhl_score_now.json")
        for g in later["games"]:
            if g.get("clock"):
                g["clock"] = dict(g["clock"], secondsRemaining=g["clock"]["secondsRemaining"] - 40, timeRemaining="15:39")
        calls = lambda url: later if url == nhl.SCORE_URL else S.fixture_fetch(url)
        loop.run_pass(lambda: [], now=S.at(40), fetch_json=calls, schedule={}, log_dir=self.log)
        self.assertEqual((self.log / "2026-10-30.jsonl").read_bytes(), before)

    def test_a_shot_appends_exactly_one_line_and_leaves_every_earlier_byte_alone(self):
        fresh_pass(log_dir=self.log)
        path = self.log / "2026-10-30.jsonl"
        before = path.read_bytes()
        moved = S.load("nhl_score_now.json")
        for g in moved["games"]:
            if str(g["id"]) == S.GAME:
                g["awayTeam"]["sog"] = 13
        loop.run_pass(lambda: [], now=S.at(40), fetch_json=lambda url: moved if url == nhl.SCORE_URL else S.fixture_fetch(url),
                      schedule={}, log_dir=self.log)
        after = path.read_bytes()
        self.assertTrue(after.startswith(before))                                   # append-only: the old lines are untouched
        added = [json.loads(x) for x in after[len(before):].decode("utf-8").splitlines()]
        self.assertEqual(len(added), 1)
        self.assertEqual((added[0]["id"], added[0]["a"][2], added[0]["t"]), (S.GAME, 13, "2026-10-30T02:40:40Z"))

    def test_a_new_utc_day_goes_to_a_new_file(self):
        fresh_pass(log_dir=self.log)
        moved = S.load("nhl_score_now.json")
        for g in moved["games"]:
            if str(g["id"]) == S.GAME:
                g["homeTeam"]["score"] = 1
        midnight = datetime(2026, 10, 31, 0, 5, tzinfo=timezone.utc)
        loop.run_pass(lambda: [], now=midnight, fetch_json=lambda url: moved if url == nhl.SCORE_URL else S.fixture_fetch(url),
                      schedule={}, log_dir=self.log)
        self.assertEqual([n for n, _ in self.lines()], ["2026-10-30.jsonl", "2026-10-31.jsonl"])

    def test_a_game_first_met_already_final_is_not_logged_but_one_that_finishes_after_being_live_is(self):
        fresh_pass(log_dir=self.log)
        ids = [r["id"] for _n, rows in self.lines() for r in rows]
        self.assertNotIn("2026020208", ids)                                          # final on the very first read
        done = S.load("nhl_score_now.json")
        for g in done["games"]:
            if str(g["id"]) == S.GAME:
                g["gameState"], g["homeTeam"]["score"] = "FINAL", 1
        loop.run_pass(lambda: [], now=S.at(40), fetch_json=lambda url: done if url == nhl.SCORE_URL else S.fixture_fetch(url),
                      schedule={}, log_dir=self.log)
        rows = [r for _n, rs in self.lines() for r in rs if r["id"] == S.GAME]
        self.assertEqual([r["st"] for r in rows], ["live", "final"])

    def test_a_failing_disk_is_counted_and_never_raises(self):
        blocker = self.log / "file_not_dir"
        blocker.write_text("x", encoding="utf-8")
        before = store.STATUS["log_errors"]
        with self.assertLogs("linehound.sports.live_state", level="WARNING"):
            fresh_pass(log_dir=blocker)                                              # a file where the directory should be
        self.assertGreater(store.STATUS["log_errors"], before)

    def test_the_default_directory_sits_beside_the_hounds_ledger(self):
        with mock.patch("src.hounds.user_engine.ledger_path", return_value=str(self.log / "user_ledger.jsonl")):
            self.assertEqual(store.default_log_dir(), self.log / "live_state")


class TheLoop(Isolated):
    def test_it_does_not_start_when_switched_off_or_under_pytest(self):
        self.assertIsNone(loop.start_loop(lambda: [], env={"LIVE_STATE": "off"}))
        for value in ("OFF", "0", "false", "no"):
            self.assertIsNone(loop.start_loop(lambda: [], env={"LIVE_STATE": value}))
        with mock.patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "x"}):
            self.assertIsNone(loop.start_loop(lambda: []))
            self.assertIsNone(live_state.start_loop(lambda: []))

    def test_pytest_itself_never_starts_it_even_though_the_app_module_declares_the_hook(self):
        with mock.patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "tests/x.py::t (call)"}):
            self.assertIsNone(live_state.start_loop(lambda: [], ready=lambda: True))
        self.assertFalse(store.STATUS["enabled"])

    def test_it_is_on_by_default_and_a_pass_that_raises_does_not_kill_it(self):
        self.assertTrue(loop.enabled({}))
        stop, ran = threading.Event(), []

        def flaky(*_a, **_k):
            ran.append(1)
            if len(ran) == 1:
                raise RuntimeError("boom")
            if len(ran) >= 3:
                stop.set()
            return {}
        self.addCleanup(lambda: store.STATUS.update(enabled=False, last_error=None))
        with mock.patch.object(loop, "run_pass", side_effect=flaky), self.assertLogs("linehound.sports.live_state", level="ERROR"):
            thread = loop.start_loop(lambda: [], interval_s=0.01, stop_event=stop, env={}, log_dir=self.log)
            thread.join(10)
        self.assertGreaterEqual(len(ran), 3)
        self.assertIn("boom", store.STATUS["last_error"])
        self.assertEqual(thread.name, "live-state")
        self.assertTrue(thread.daemon)

    def test_a_board_provider_that_raises_does_not_stop_the_nhl_read(self):
        def boom():
            raise RuntimeError("no board")
        report = loop.run_pass(boom, now=S.NOW, fetch_json=S.fixture_fetch, schedule={}, log_dir=self.log)
        self.assertEqual(report["nhl"]["games"], 5)

    def test_a_pass_calls_nothing_but_the_injected_fetch(self):
        urls = []
        loop.run_pass(lambda: [{"family": "TENNIS", "in_play": True, "_start": S.TENNIS_START}], now=S.TENNIS_NOW,
                      fetch_json=lambda u: urls.append(u) or S.fixture_fetch(u), schedule={}, log_dir=self.log)
        self.assertTrue(urls)
        for url in urls:
            self.assertRegex(url, r"^https://(api-web\.nhle\.com|site\.api\.espn\.com)/")
            self.assertNotIn("the-odds-api", url)

    def test_the_cadence_is_thirty_seconds_with_a_five_minute_idle_and_a_pass_budget(self):
        self.assertEqual(loop.INTERVAL_SECONDS, 30.0)
        self.assertEqual(nhl.SCORE_EVERY_SECONDS, 30.0)
        self.assertEqual(nhl.DETAIL_EVERY_SECONDS, 60.0)
        self.assertEqual(store.STALE_AFTER_SECONDS, 180.0)
        self.assertLessEqual(loop.PASS_BUDGET_SECONDS, loop.INTERVAL_SECONDS)

    def test_a_quiet_day_waits_five_minutes_between_score_reads_and_a_busy_one_thirty_seconds(self):
        quiet = S.load("nhl_score_now.json")
        quiet["games"] = [g for g in quiet["games"] if g["gameState"] in ("OFF", "FINAL")]
        calls = []
        sched = {}
        loop.run_pass(lambda: [], now=S.NOW, fetch_json=lambda u: calls.append(u) or quiet, schedule=sched, log_dir=self.log)
        self.assertEqual(sched["NHL"], S.NOW + timedelta(seconds=300))
        loop.run_pass(lambda: [], now=S.at(30), fetch_json=lambda u: calls.append(u) or quiet, schedule=sched, log_dir=self.log)
        self.assertEqual(len(calls), 1)                                              # inside the idle wait: no request at all
        busy_sched = {}
        loop.run_pass(lambda: [], now=S.NOW, fetch_json=S.fixture_fetch, schedule=busy_sched, log_dir=self.log)
        self.assertEqual(busy_sched["NHL"], S.NOW + timedelta(seconds=30))

    def test_a_failed_score_read_is_retried_in_thirty_seconds_not_five_minutes(self):
        sched = {}
        loop.run_pass(lambda: [], now=S.NOW, fetch_json=lambda u: (_ for _ in ()).throw(OSError("down")), schedule=sched, log_dir=self.log)
        self.assertEqual(sched["NHL"], S.NOW + timedelta(seconds=30))
        self.assertIn("nhl", store.STATUS["last_error"])

    def test_a_board_that_cannot_be_read_skips_tennis_and_nothing_else(self):
        def boom():
            raise RuntimeError("no board")
        report = loop.run_pass(boom, now=S.NOW, fetch_json=S.fixture_fetch, schedule={}, log_dir=self.log)
        self.assertIn("nhl", report)
        self.assertNotIn("tennis", report)

    def test_app_wires_the_loop_and_health_reports_it(self):
        app = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("live_state.start_loop(allsports_view.current_events", app)
        health = (REPO / "api" / "health.py").read_text(encoding="utf-8")
        self.assertIn('data["live_state"] = live_state.status()', health)

    def test_status_reports_games_and_the_log(self):
        fresh_pass(log_dir=self.log)
        status = live_state.status(S.at(5))
        self.assertEqual(status["games"]["nhl"], {"fresh": 5, "live": 3})
        self.assertEqual(status["stale_after_seconds"], 180)
        self.assertGreaterEqual(status["log_rows"], 3)
        self.assertEqual(status["nhl_last_read_utc"], "2026-10-30T02:40:00Z")
        json.dumps(status)

    def test_the_package_reads_no_file_the_image_would_have_to_ship(self):
        # a new reader of the disk must be in the image (Dockerfile COPY + .dockerignore): this package reads only the volume log it writes
        src = "".join((REPO / "src" / "sports" / "live_state" / n).read_text(encoding="utf-8") for n in os.listdir(REPO / "src" / "sports" / "live_state") if n.endswith(".py"))
        self.assertNotIn("open(\"config", src)
        self.assertNotIn("repo_root", src)
        self.assertIn("COPY src/ src/", (REPO / "deploy" / "Dockerfile").read_text(encoding="utf-8"))


class TheBoardCarriesTheLine(Isolated):
    START = S.START

    def rows(self, home="San Jose Sharks", away="Vancouver Canucks", family="nhl", league="icehockey_nhl"):
        return mrow("nhl_1", family, self.START, S.NOW - timedelta(minutes=1), home=home, away=away, prices=((-150, 130),), league=league)

    def board(self, now=None, rows=None, **kw):
        return V.sports_now(now or S.at(10), rows=rows if rows is not None else self.rows(), scores_index={}, feed_answers={}, **kw)

    def live_events(self, body, code="NHL"):
        fam = next((f for f in body["families"] if f["code"] == code), None)
        return fam["live"] if fam else []

    def test_a_game_in_play_gets_its_line_from_the_cache(self):
        fresh_pass()
        [game] = self.live_events(self.board())
        self.assertEqual(game["live_state"], {"line": "2nd · 16:19 · SOG 12-8", "sport": "NHL", "as_of": "2026-10-30T02:40:00Z"})

    def test_a_game_it_cannot_place_gets_no_key_and_the_board_is_unchanged(self):
        fresh_pass()
        [game] = self.live_events(self.board(rows=self.rows(home="Vancouver Canucks", away="San Jose Sharks")))
        self.assertNotIn("live_state", game)

    def test_a_stale_cache_gives_no_line(self):
        fresh_pass()
        [game] = self.live_events(self.board(now=S.at(400), rows=mrow("nhl_1", "nhl", self.START, S.at(399), home="San Jose Sharks",
                                                                         away="Vancouver Canucks", prices=((-150, 130),), league="icehockey_nhl")))
        self.assertNotIn("live_state", game)

    def test_an_empty_cache_leaves_the_board_exactly_as_before(self):
        [game] = self.live_events(self.board())
        self.assertNotIn("live_state", game)

    def test_the_injection_point_and_a_failing_lookup_cannot_break_the_board(self):
        [game] = self.live_events(self.board(live_states={"nhl_1": {"state": "live", "sport": "NHL", "line": "injected", "as_of": "x"}}))
        self.assertEqual(game["live_state"]["line"], "injected")
        with mock.patch.object(live_state, "state_for", side_effect=RuntimeError("boom")):
            [game] = self.live_events(self.board())
        self.assertNotIn("live_state", game)

    def test_a_family_with_no_live_state_is_untouched(self):
        rows = mrow("nba_1", "nba", self.START, S.NOW - timedelta(minutes=1), home="Lakers", away="Suns", prices=((-150, 130),), league="basketball_nba")
        fresh_pass()
        [game] = self.live_events(self.board(rows=rows), "NBA")
        self.assertNotIn("live_state", game)


class TheTicketPayloadCarriesTheLine(Isolated):
    def setUp(self):
        super().setUp()
        self.db = Path(self.log) / "live_settle.db"
        self.conn = live_settle.connect(self.db)
        self.addCleanup(self.conn.close)

    def insert(self, key, sport, home, away, start, state="upcoming"):
        self.conn.execute("INSERT INTO live_games(game_key, sport, home_team, away_team, start_utc, supported, state, updated_utc) "
                          "VALUES (?,?,?,?,?,?,?,?)", (key, sport, home, away, start, 1, state, "2026-10-30T02:39:00Z"))

    def test_an_open_nhl_ticket_in_play_carries_the_line(self):
        fresh_pass()
        self.insert("e1", "NHL", "San Jose Sharks", "Vancouver Canucks", "2026-10-30T02:00:00Z", "live")
        got = live_settle.game_states(["e1"], now=S.at(10), conn=self.conn)["e1"]
        self.assertEqual(got["live_state"]["line"], "2nd · 16:19 · SOG 12-8")
        self.assertEqual(got["state"], "live")

    def test_a_tennis_ticket_carries_it_even_though_the_grader_cache_still_says_upcoming(self):
        for _ in range(2):
            loop.run_pass(lambda: [{"family": "TENNIS", "in_play": True, "_start": S.TENNIS_START}], now=S.TENNIS_NOW,
                          fetch_json=S.fixture_fetch, schedule={"NHL": S.TENNIS_NOW + timedelta(hours=1)}, log_dir=self.log)
        self.insert("t1", "TENNIS", "Kamilla Rakhimova", "Maya Joint", "2026-10-30T01:35:00Z", "upcoming")
        got = live_settle.game_states(["t1"], now=S.at(5, S.TENNIS_NOW), conn=self.conn)["t1"]
        self.assertTrue(got["live_state"]["line"].startswith("Set 2 · 4-3 · Rakhimova serving"))

    def test_a_final_game_or_another_sport_or_a_miss_gets_no_key(self):
        fresh_pass()
        self.insert("e1", "NHL", "San Jose Sharks", "Vancouver Canucks", "2026-10-30T02:00:00Z", "final")
        self.insert("e2", "NBA", "San Jose Sharks", "Vancouver Canucks", "2026-10-30T02:00:00Z", "live")
        self.insert("e3", "NHL", "Vancouver Canucks", "San Jose Sharks", "2026-10-30T02:00:00Z", "live")
        got = live_settle.game_states(["e1", "e2", "e3"], now=S.at(10), conn=self.conn)
        for key in ("e1", "e2", "e3"):
            self.assertNotIn("live_state", got[key], key)

    def test_with_nothing_cached_the_answer_is_byte_for_byte_what_it_was(self):
        self.insert("e1", "NHL", "San Jose Sharks", "Vancouver Canucks", "2026-10-30T02:00:00Z", "live")
        got = live_settle.game_states(["e1"], now=S.at(10), conn=self.conn)["e1"]
        self.assertEqual(set(got), {"state", "start_utc", "home_score", "away_score", "detail", "final_utc", "updated_utc", "supported"})


if __name__ == "__main__":
    unittest.main()
