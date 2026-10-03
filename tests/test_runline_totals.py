"""Run line and totals: the reader, the payload sections, the RUNLINE_TOTALS
switch, and the two odds routes with the switch on and off.

Offline throughout: fixture multibook rows shaped exactly like
snapshots.multibook_rows writes them (spreads/totals lines as decimal STRINGS,
moneyline rows with no `market` key), no store on disk, no network.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.analysis import oddspayload, runline_totals
from src.analysis import prices as prices_mod

NOW = datetime(2026, 10, 3, 17, 0, 0, tzinfo=timezone.utc)
NEWEST = "2026-10-03T16:50:00+00:00"
OLDER = "2026-10-03T16:20:00+00:00"
START = "2026-10-03T22:10:00Z"           # 6:10 pm ET -> official date 2026-10-03
BOOKS = ("fanduel", "draftkings", "betmgm", "caesars", "betrivers", "lowvig", "bovada")


def _base(observed, book, away="Boston Red Sox", home="New York Yankees", commence=START):
    return {"observed_utc": observed, "event_id": "evt1", "commence_time": commence,
            "home_team": home, "away_team": away, "book": book,
            "book_last_update": observed}


def _spread(book, home_line, home_price, away_price, observed=NEWEST, **kw):
    row = _base(observed, book, **kw)
    row.update(market="spreads", home_line=str(home_line), home_price=home_price,
               away_line=str(-home_line), away_price=away_price)
    return row


def _total(book, total, over, under, observed=NEWEST, **kw):
    row = _base(observed, book, **kw)
    row.update(market="totals", total=str(total), over_price=over, under_price=under)
    return row


def _moneyline(book, observed=NEWEST):
    row = _base(observed, book)
    row.update(home_price=-150, away_price=130)
    return row


def _full_rows():
    rows = []
    for i, book in enumerate(BOOKS):
        rows.append(_spread(book, -1.5, 140 + i, -160 - i))
        rows.append(_total(book, 8.5, -110 + i, -110 - i))
    rows.append(_moneyline("fanduel"))
    return rows


KEY = ("BOS", "NYY", "2026-10-03")
_REAL_LINE_BOARDS = runline_totals.line_boards_by_matchup


def _staleness(observed, has_board):
    return oddspayload._staleness(observed, now=NOW, has_board=has_board)


class SwitchTests(unittest.TestCase):

    def test_default_is_off(self):
        self.assertFalse(runline_totals.enabled({}))
        self.assertFalse(runline_totals.enabled({"RUNLINE_TOTALS": ""}))

    def test_only_an_explicit_on_turns_it_on(self):
        for value in ("on", "1", "true", "YES", " On "):
            self.assertTrue(runline_totals.enabled({"RUNLINE_TOTALS": value}), value)
        for value in ("off", "0", "false", "no", "enabled", "2"):
            self.assertFalse(runline_totals.enabled({"RUNLINE_TOTALS": value}), value)


class ReaderTests(unittest.TestCase):

    def test_boards_are_keyed_like_the_moneyline_boards(self):
        boards = runline_totals.line_boards_by_matchup(rows=_full_rows())
        self.assertEqual(list(boards), [KEY])
        self.assertEqual(set(boards[KEY]), {"spreads", "totals"})
        self.assertEqual(len(boards[KEY]["spreads"]["quotes"]), len(BOOKS))
        self.assertEqual(boards[KEY]["spreads"]["observed_utc"], NEWEST)

    def test_moneyline_rows_are_not_line_rows(self):
        boards = runline_totals.line_boards_by_matchup(rows=[_moneyline("fanduel")])
        self.assertEqual(boards, {})

    def test_only_the_newest_pregame_instant_is_kept(self):
        rows = [_spread("fanduel", -1.5, 150, -170, observed=OLDER),
                _spread("draftkings", -1.5, 155, -175, observed=NEWEST)]
        board = runline_totals.line_boards_by_matchup(rows=rows)[KEY]["spreads"]
        self.assertEqual([q["book"] for q in board["quotes"]], ["draftkings"])

    def test_in_play_rows_are_excluded(self):
        after_first_pitch = "2026-10-03T22:40:00+00:00"
        rows = [_total("fanduel", 8.5, -110, -110, observed=OLDER),
                _total("fanduel", 4.5, -300, 240, observed=after_first_pitch)]
        board = runline_totals.line_boards_by_matchup(rows=rows)[KEY]["totals"]
        self.assertEqual(board["quotes"][0]["total"], 8.5)
        self.assertEqual(board["observed_utc"], OLDER)

    def test_incomplete_rows_are_skipped_not_half_recorded(self):
        bad = _spread("fanduel", -1.5, None, -170)
        bad2 = _total("draftkings", "n/a", -110, -110)
        self.assertEqual(runline_totals.line_boards_by_matchup(rows=[bad, bad2]), {})

    def test_unknown_club_is_dropped(self):
        row = _total("fanduel", 8.5, -110, -110, home="Springfield Isotopes")
        self.assertEqual(runline_totals.line_boards_by_matchup(rows=[row]), {})


class SectionTests(unittest.TestCase):

    def _sections(self, rows):
        boards = runline_totals.line_boards_by_matchup(rows=rows)
        return runline_totals.build_game_line_markets(boards.get(KEY), staleness=_staleness)

    def test_run_line_main_line_best_price_and_consensus(self):
        spreads = self._sections(_full_rows())["spreads"]
        self.assertTrue(spreads["board_available"])
        self.assertEqual(spreads["main_line"], {"home": -1.5, "away": 1.5})
        self.assertEqual(spreads["books_at_main_line"], 7)
        # best home price is the highest payout: +146 (lowvig i=5); best away -160 (fanduel)
        self.assertEqual(spreads["best"]["home"], {"price": 146, "books": ["bovada"], "line": -1.5})
        self.assertEqual(spreads["best"]["away"], {"price": -160, "books": ["fanduel"], "line": 1.5})
        self.assertEqual(spreads["consensus"]["books"], 7)
        self.assertIn("implied_price", spreads["consensus"]["home"])
        self.assertIsNone(spreads["consensus_unavailable_reason"])
        self.assertEqual(spreads["basis"], "last pre-game capture")
        self.assertEqual(spreads["staleness"]["observed_utc"], NEWEST)

    def test_totals_main_line_over_under(self):
        totals = self._sections(_full_rows())["totals"]
        self.assertEqual(totals["main_line"], {"total": 8.5})
        self.assertEqual(totals["best"]["over"]["total"], 8.5)
        self.assertEqual(totals["best"]["over"]["price"], -104)   # -110 + 6
        self.assertEqual(totals["best"]["under"]["price"], -110)  # i=0 is best under
        self.assertEqual(totals["best"]["under"]["books"], ["fanduel"])

    def test_probabilities_are_devigged_and_sum_to_one(self):
        totals = self._sections(_full_rows())["totals"]
        over = totals["consensus"]["over"]["implied_probability"]
        under = totals["consensus"]["under"]["implied_probability"]
        self.assertAlmostEqual(over + under, 1.0, places=3)

    def test_a_book_on_another_line_never_sets_the_best_price(self):
        rows = _full_rows()
        # one book hangs 7.5 with a juicy over price; it must not become "best over"
        rows.append(_total("wynn", 7.5, +150, -180))
        totals = self._sections(rows)["totals"]
        self.assertEqual(totals["main_line"], {"total": 8.5})
        self.assertEqual(totals["books_at_main_line"], 7)
        self.assertNotEqual(totals["best"]["over"]["price"], 150)
        self.assertEqual(totals["other_lines"], [{"total": 7.5, "books": 1}])
        off_line = [r for r in totals["board"] if not r["at_main_line"]]
        self.assertEqual([r["book"] for r in off_line], ["wynn"])

    def test_below_the_book_floor_there_is_no_consensus_but_prices_remain(self):
        rows = [_total(b, 8.5, -110, -110) for b in BOOKS[:3]]
        totals = self._sections(rows)["totals"]
        self.assertTrue(totals["board_available"])
        self.assertIsNone(totals["consensus"])
        self.assertIn("6-book floor", totals["consensus_unavailable_reason"])
        self.assertIsNotNone(totals["best"]["over"])

    def test_ties_for_best_price_name_every_book(self):
        rows = [_total(b, 8.5, -105, -115) for b in BOOKS]
        totals = self._sections(rows)["totals"]
        self.assertEqual(totals["best"]["over"]["books"], sorted(BOOKS))

    def test_modal_line_tie_is_deterministic(self):
        rows = ([_total(b, 8.5, -110, -110) for b in BOOKS[:3]]
                + [_total(b, 9.0, -110, -110) for b in BOOKS[3:6]])
        first = self._sections(rows)["totals"]["main_line"]
        second = self._sections(list(reversed(rows)))["totals"]["main_line"]
        self.assertEqual(first, second)

    def test_a_home_underdog_run_line_is_not_assumed_negative(self):
        rows = [_spread(b, 1.5, -170, 150) for b in BOOKS]
        spreads = self._sections(rows)["spreads"]
        self.assertEqual(spreads["main_line"], {"home": 1.5, "away": -1.5})

    def test_no_board_is_an_explicit_unavailable_section(self):
        sections = runline_totals.build_game_line_markets({}, staleness=_staleness)
        for name in ("spreads", "totals"):
            self.assertFalse(sections[name]["board_available"])
            self.assertEqual(sections[name]["reason"], runline_totals.NO_BOARD_REASON)
            self.assertEqual(sections[name]["board"], [])
            self.assertIsNone(sections[name]["best"])
            self.assertIsNone(sections[name]["consensus"])


class PayloadSwitchTests(unittest.TestCase):

    GAME = {"away_team": "BOS", "home_team": "NYY", "date": "2026-10-03",
            "start_time_utc": START, "venue": "Yankee Stadium", "game_pk": 1}

    def _h2h_board(self):
        quotes = [{"ts": NEWEST, "book": b, "away_price": 130, "home_price": -150} for b in BOOKS]
        return {"quotes": quotes, "observed_utc": NEWEST, "source": "test"}

    def test_off_the_payload_is_exactly_what_it_was(self):
        entry = oddspayload.build_game_odds(self.GAME, self._h2h_board(), now=NOW)
        self.assertEqual(set(entry["markets"]), {"h2h"})
        slate = oddspayload.build_odds_payload([self.GAME], {KEY: self._h2h_board()},
                                               date="2026-10-03", now=NOW)
        self.assertEqual(set(slate["games"][0]["markets"]), {"h2h"})

    def test_on_the_game_carries_spreads_and_totals_beside_h2h(self):
        line_boards = runline_totals.line_boards_by_matchup(rows=_full_rows())[KEY]
        entry = oddspayload.build_game_odds(self.GAME, self._h2h_board(), now=NOW,
                                            line_boards=line_boards)
        self.assertEqual(set(entry["markets"]), {"h2h", "spreads", "totals"})
        self.assertTrue(entry["markets"]["totals"]["board_available"])
        json.dumps(entry)  # serialisable end to end

    def test_on_a_slate_game_without_line_rows_is_unavailable_not_absent(self):
        slate = oddspayload.build_odds_payload([self.GAME], {KEY: self._h2h_board()},
                                               date="2026-10-03", now=NOW, line_boards={})
        markets = slate["games"][0]["markets"]
        self.assertFalse(markets["spreads"]["board_available"])
        self.assertTrue(markets["h2h"]["board_available"])

    def test_h2h_is_unchanged_by_turning_it_on(self):
        off = oddspayload.build_game_odds(self.GAME, self._h2h_board(), now=NOW)
        on = oddspayload.build_game_odds(self.GAME, self._h2h_board(), now=NOW, line_boards={})
        self.assertEqual(off["markets"]["h2h"], on["markets"]["h2h"])

    def test_the_moneyline_reader_still_ignores_line_rows(self):
        # The store holds all three markets; the moneyline board must not change.
        boards = prices_mod.boards_by_matchup(rows=_full_rows())
        self.assertEqual(len(boards[KEY]["quotes"]), 1)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteTests(unittest.TestCase):

    def setUp(self):
        from api import odds as odds_mod
        from src.appstate import freshness
        self.odds_mod = odds_mod
        odds_mod._odds_cache = freshness.SingleFlightTTLCache(ttl_s=odds_mod.ODDS_CACHE_TTL_S)
        self.schedule = [{"game_pk": 1, "date": "2026-10-03", "away_team": "BOS",
                          "home_team": "NYY", "start_time_utc": START, "venue": "Yankee Stadium"}]
        quotes = [{"ts": NEWEST, "book": b, "away_price": 130, "home_price": -150} for b in BOOKS]
        self.h2h = {KEY: {"quotes": quotes, "observed_utc": NEWEST, "source": "test"}}

    def _run(self, env, fn, *args):
        from src.providers import mlb
        calls = []

        def fake_line_boards(**kw):
            calls.append(kw)
            return _REAL_LINE_BOARDS(rows=_full_rows())

        with patch.dict("os.environ", env, clear=False), \
                patch.object(mlb, "fetch_games", return_value=self.schedule), \
                patch.object(prices_mod, "boards_by_matchup", return_value=self.h2h), \
                patch.object(runline_totals, "line_boards_by_matchup", side_effect=fake_line_boards):
            payload = fn(*args)
        return payload, calls

    def test_slate_route_default_off_reads_nothing_extra(self):
        payload, calls = self._run({"RUNLINE_TOTALS": ""}, self.odds_mod.get_odds, "2026-10-03")
        self.assertEqual(calls, [])
        self.assertEqual(set(payload["games"][0]["markets"]), {"h2h"})

    def test_slate_route_on_serves_both_markets(self):
        payload, calls = self._run({"RUNLINE_TOTALS": "on"}, self.odds_mod.get_odds, "2026-10-03")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], {"date": "2026-10-03"})
        markets = payload["games"][0]["markets"]
        self.assertEqual(markets["spreads"]["main_line"], {"home": -1.5, "away": 1.5})
        self.assertEqual(markets["totals"]["main_line"], {"total": 8.5})

    def test_game_route_on_serves_both_markets(self):
        payload, _ = self._run({"RUNLINE_TOTALS": "on"}, self.odds_mod.get_odds_game,
                               "2026-10-03", "BOS", "NYY")
        self.assertEqual(set(payload["markets"]), {"h2h", "spreads", "totals"})

    def test_game_route_off_is_h2h_only(self):
        payload, _ = self._run({"RUNLINE_TOTALS": "off"}, self.odds_mod.get_odds_game,
                               "2026-10-03", "BOS", "NYY")
        self.assertEqual(set(payload["markets"]), {"h2h"})

    def test_a_failing_line_read_never_takes_the_moneyline_down(self):
        from src.providers import mlb
        with patch.dict("os.environ", {"RUNLINE_TOTALS": "on"}), \
                patch.object(mlb, "fetch_games", return_value=self.schedule), \
                patch.object(prices_mod, "boards_by_matchup", return_value=self.h2h), \
                patch.object(runline_totals, "line_boards_by_matchup",
                             side_effect=OSError("store unreadable")):
            payload = self.odds_mod.get_odds("2026-10-03")
        markets = payload["games"][0]["markets"]
        self.assertTrue(markets["h2h"]["board_available"])
        self.assertFalse(markets["spreads"]["board_available"])

    def test_line_boards_are_read_once_per_cache_window(self):
        from src.providers import mlb
        calls = []

        def fake(**kw):
            calls.append(kw)
            return {}

        with patch.dict("os.environ", {"RUNLINE_TOTALS": "on"}), \
                patch.object(mlb, "fetch_games", return_value=self.schedule), \
                patch.object(prices_mod, "boards_by_matchup", return_value=self.h2h), \
                patch.object(runline_totals, "line_boards_by_matchup", side_effect=fake):
            for _ in range(5):
                self.odds_mod.get_odds("2026-10-03")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
