"""src.analysis.prices.legacy_quotes_from_board and its wiring through
src.pipeline.briefing.build_slate / src.analysis.gamepayload.slate_game_summary.

THE DEFECT THESE TESTS NAME (2026-09-12, observed on staging)
---------------------------------------------------------------
api/games._build_entries calls build_slate with NO `prices_by_matchup` --
only the CLI's live odds fetch ever supplies that mapping. Before this fix,
src.detect.dossier.build(..., prices=None) therefore recorded the gap "no
prices on the board for this game" for EVERY game on EVERY API-built slate,
even a game whose multibook board (price_boards_by_key -- the SAME store
the price-improvement table beside it reads) held eleven priced books. On
linehound-staging.fly.dev/web/index.html#/today the KC@BOS card's #1 pick
read "Take Red Sox to win at -212 ... best of 11 books" directly above a
Today hero for the identical game reading "MARKET UNAVAILABLE ... NO PRICE
BOARD RECORDED FOR THIS GAME" -- a contradiction on one screen, caused by
the market screen (mismatch.apply_market_screen, fed by
briefing._routed_price(dossier, ...)) reading an always-empty
dossier["market"] while the price table two lines away read the board
directly.

Each test class's docstring says exactly which pre-fix code path it fails
against, reasoned from the source rather than run against a checked-out
pre-fix commit (none exists in this working tree to check out).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from src.analysis import gamepayload
from src.analysis import prices as prices_mod
from src.detect import dossier as dossier_mod
from src.pipeline import briefing, history
from src.pipeline import mismatch as mismatch_mod


def _game(game_pk=990101, away="BOS", home="NYY", date="2026-08-31"):
    return {"game_pk": game_pk, "date": date, "away_team": away,
            "home_team": home, "venue": "Fenway Park",
            "start_time_utc": f"{date}T23:05:00Z"}


def _board(books, *, observed=None):
    """A board shaped like src.analysis.prices.boards_by_matchup's output:
    {"quotes": [...], "observed_utc": ts, "source": ...}. `books` is
    [(book, away_price, home_price), ...]."""
    observed = observed or datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
    ts = observed.isoformat()
    return {
        "quotes": [{"ts": ts, "book": book, "away_price": away,
                    "home_price": home} for book, away, home in books],
        "observed_utc": ts,
        "source": "test",
    }


# Six books, identical price on every side -- their two-way hold is
# therefore identical too, so legacy_quotes_from_board's tie-break (book
# name) is the only thing that decides which one is "the" h2h quote, and
# the choice is exactly predictable: "book_a", alphabetically first.
_UNIFORM_BOOKS = [("book_f", -150, 130), ("book_b", -150, 130),
                  ("book_a", -150, 130), ("book_d", -150, 130),
                  ("book_e", -150, 130), ("book_c", -150, 130)]


def _build(game=None, **kwargs):
    game = game or _game()
    store = history.read_results()
    kwargs.setdefault("roster_events_by_pk", {})
    slate = briefing.build_slate([game], store, **kwargs)
    return slate["games"][0], game


class BoardSuppliesTheMarketSectionTests(unittest.TestCase):
    """(a) With no prices_by_matchup at all, an injected board must still
    reach dossier["market"] and clear data_quality.has_market/gaps.market.

    PRE-FIX FAILURE: build_slate's dossier_mod.build call always passed
    `prices=(prices_by_matchup or {}).get(key)`, which is None whenever the
    caller (api/games._build_entries, exactly this test's call shape) never
    supplies prices_by_matchup -- regardless of what price_boards_by_key
    holds. dossier.build then took the `else` branch at
    src/detect/dossier.py:216-217 and called
    `dossier.miss("market", "no prices on the board for this game")` for
    every game, so sections["market"] never existed and data_quality.
    has_market was always False, exactly the contradiction this mission
    describes on the live Today page.
    """

    def test_board_becomes_the_market_section(self):
        game = _game()
        price_key = prices_mod.matchup_key(
            game["away_team"], game["home_team"], game["date"])
        board = _board(_UNIFORM_BOOKS)
        entry, game = _build(game, price_boards_by_key={price_key: board})
        dossier = entry["dossier"]

        market = dossier.get("market")
        self.assertIsNotNone(market, "the board must populate dossier market")
        h2h = market["markets"]["h2h"]
        self.assertIn("away_fair", h2h)
        self.assertIn("home_fair", h2h)
        self.assertNotIn("market", dossier.gaps)

        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        self.assertTrue(row["data_quality"]["has_market"])
        self.assertNotIn("market", row["data_quality"]["gaps"])


class ExplicitPricesWinOverTheBoardTests(unittest.TestCase):
    """(b) An explicit prices_by_matchup entry for a game's key must win
    over an injected board for that same key -- the board is a fallback,
    never a silent override of a caller who did supply a live quote.

    This exercises the new `if prices is None:` branch added to
    build_slate: it must never fire when prices_by_matchup already has the
    key, so this test would fail if that ordering were reversed (board
    checked first) or if the fallback ran unconditionally.
    """

    def test_explicit_price_beats_board_derived_price(self):
        game = _game()
        price_key = prices_mod.matchup_key(
            game["away_team"], game["home_team"], game["date"])
        prices_by_matchup = {
            (game["away_team"], game["home_team"]): {
                "h2h": {"away_price": 999, "home_price": -999,
                        "away_fair": 0.11, "home_fair": 0.89},
            }
        }
        board = _board(_UNIFORM_BOOKS)  # would pick -150/130 if consulted
        entry, _ = _build(
            game, prices_by_matchup=prices_by_matchup,
            price_boards_by_key={price_key: board})
        h2h = entry["dossier"].get("market")["markets"]["h2h"]
        self.assertEqual(h2h["away_price"], 999)
        self.assertEqual(h2h["home_price"], -999)


class NoBoardLeavesTheOriginalGapTests(unittest.TestCase):
    """(c) No board and no explicit prices: the gap keeps its exact
    original wording -- the fallback must not invent a market section (or a
    different gap sentence) out of nothing.
    """

    def test_gap_wording_unchanged_with_nothing_to_fall_back_to(self):
        entry, _ = _build(price_boards_by_key={})
        self.assertIsNone(entry["dossier"].get("market"))
        self.assertEqual(entry["dossier"].gaps.get("market"),
                         "no prices on the board for this game")


class LegacyQuotesFromBoardUnitTests(unittest.TestCase):
    """(d) legacy_quotes_from_board in isolation, no build_slate involved.

    PRE-FIX FAILURE: this function did not exist at all -- every assertion
    below fails with AttributeError against the pre-fix module.
    """

    def test_preferred_book_wins_when_both_priced(self):
        board = _board(_UNIFORM_BOOKS + [("preferred", -105, -105)])
        result = prices_mod.legacy_quotes_from_board(board, preferred_book="preferred")
        self.assertEqual(result["h2h"]["book"], "preferred")
        self.assertEqual(result["h2h"]["away_price"], -105)
        self.assertEqual(result["h2h"]["home_price"], -105)

    def test_preferred_book_ignored_when_not_on_board(self):
        board = _board(_UNIFORM_BOOKS)
        result = prices_mod.legacy_quotes_from_board(board, preferred_book="nobody_here")
        # Falls through to the lowest-hold/tie-by-name rule below.
        self.assertEqual(result["h2h"]["book"], "book_a")

    def test_lowest_hold_book_chosen_tie_broken_by_name(self):
        # Every book here quotes the SAME two prices, so hold is identical
        # across the board and the tie-break (book name) is the only thing
        # that can be asserted deterministically.
        board = _board(_UNIFORM_BOOKS)
        result = prices_mod.legacy_quotes_from_board(board)
        self.assertEqual(result["h2h"]["book"], "book_a")
        self.assertEqual(result["h2h"]["away_price"], -150)
        self.assertEqual(result["h2h"]["home_price"], 130)

    def test_lowest_hold_wins_over_a_worse_priced_book(self):
        # a_juiced: -130/-110 -> implied probs 0.5652 + 0.5238, hold ~8.18%.
        # z_tight:  -105/-105 -> implied probs 0.5122 + 0.5122, hold ~2.38%.
        # z_tight has the lower hold but sorts AFTER a_juiced alphabetically,
        # so this only passes if hold is compared before name.
        board = _board([("a_juiced", -130, -110), ("z_tight", -105, -105)])
        result = prices_mod.legacy_quotes_from_board(board)
        self.assertEqual(result["h2h"]["book"], "z_tight")

    def test_every_priceable_book_in_all_books(self):
        board = _board(_UNIFORM_BOOKS)
        result = prices_mod.legacy_quotes_from_board(board)
        books = {row["book"] for row in result["all_books"]["h2h"]}
        self.assertEqual(books, {b for b, _, _ in _UNIFORM_BOOKS})
        self.assertEqual(len(result["all_books"]["h2h"]), len(_UNIFORM_BOOKS))

    def test_rows_missing_a_price_are_skipped(self):
        board = _board([("has_both", -150, 130)])
        board["quotes"].append({"ts": board["observed_utc"], "book": "half",
                                "away_price": None, "home_price": 130})
        result = prices_mod.legacy_quotes_from_board(board)
        books = {row["book"] for row in result["all_books"]["h2h"]}
        self.assertEqual(books, {"has_both"})

    def test_none_on_empty_board(self):
        self.assertIsNone(prices_mod.legacy_quotes_from_board(None))
        self.assertIsNone(prices_mod.legacy_quotes_from_board({"quotes": []}))

    def test_none_when_nothing_priceable(self):
        board = _board([])
        board["quotes"] = [{"ts": board["observed_utc"], "book": "half",
                            "away_price": 110, "home_price": None}]
        self.assertIsNone(prices_mod.legacy_quotes_from_board(board))


class CandidateScreenedAgainstTheBoardTests(unittest.TestCase):
    """(e) A candidate routed to the full game must be screened with the
    board's own price, via the exact same apply_market_screen call the CLI
    path uses -- mismatch.scan_game is mocked so this test does not have to
    fabricate real starter/roster feature gaps to reach CANDIDATE.

    PRE-FIX FAILURE: `_routed_price(dossier, "full_game")` reads
    `dossier.get("market")["markets"]["h2h"]`, and dossier["market"] was
    always None on this call path (see class (a) above), so `quote` was
    always `{}` and apply_market_screen always received
    (None, None) -- every full-game candidate on the API path landed on
    market_unavailable regardless of what the board actually held.
    """

    def _candidate(self, game, market):
        return {
            "game_pk": game["game_pk"], "date": game["date"],
            "away_team": game["away_team"], "home_team": game["home_team"],
            "verdict": mismatch_mod.CANDIDATE, "side": "home", "market": market,
            "signals": {"starters": {"fires": True}, "roster": {"fires": True}},
            "reasons": ["synthetic candidate for this test"],
        }

    def test_full_game_candidate_is_priced_from_the_board(self):
        game = _game()
        price_key = prices_mod.matchup_key(
            game["away_team"], game["home_team"], game["date"])
        board = _board(_UNIFORM_BOOKS)  # -> book_a, away -150 / home 130
        candidate = self._candidate(game, mismatch_mod.MARKET_FULL)

        real_screen = mismatch_mod.apply_market_screen
        with mock.patch.object(mismatch_mod, "scan_game", return_value=candidate), \
             mock.patch.object(mismatch_mod, "apply_market_screen",
                              wraps=real_screen) as screen_spy:
            entry, _ = _build(game, price_boards_by_key={price_key: board})

        screen_spy.assert_called_once()
        called_scan, called_away, called_home = screen_spy.call_args[0]
        self.assertEqual(called_away, -150)
        self.assertEqual(called_home, 130)
        self.assertNotEqual(entry["verdict"], mismatch_mod.MARKET_UNAVAILABLE)


class F5RoutedCandidateHasNoBoardTests(unittest.TestCase):
    """(f) A candidate routed to the first five, with only an h2h (full
    game) board on file, must land on market_unavailable -- the multibook
    store never carries a first-five price at all (boards_by_matchup's own
    "FULL-GAME MONEYLINE ROWS ONLY" rule) -- AND the slate row's
    verdict_reason must name the first five and the full-game book count,
    not repeat the generic "no board" sentence.

    PRE-FIX FAILURE: gamepayload.slate_game_summary's row had no
    `verdict_reason` key at all, so `row["verdict_reason"]` raises KeyError
    against the pre-fix module regardless of routing.
    """

    def _candidate(self, game):
        return {
            "game_pk": game["game_pk"], "date": game["date"],
            "away_team": game["away_team"], "home_team": game["home_team"],
            "verdict": mismatch_mod.CANDIDATE, "side": "away",
            "market": mismatch_mod.MARKET_F5,
            "signals": {"starters": {"fires": True}, "roster": {"fires": False}},
            "reasons": ["synthetic F5 candidate for this test"],
        }

    def test_market_unavailable_with_a_reason_naming_f5_and_book_count(self):
        game = _game()
        price_key = prices_mod.matchup_key(
            game["away_team"], game["home_team"], game["date"])
        board = _board(_UNIFORM_BOOKS)  # six books, h2h only -- no F5 price
        candidate = self._candidate(game)

        with mock.patch.object(mismatch_mod, "scan_game", return_value=candidate):
            entry, _ = _build(game, price_boards_by_key={price_key: board})

        self.assertEqual(entry["verdict"], mismatch_mod.MARKET_UNAVAILABLE)
        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        reason = row["verdict_reason"]
        self.assertIsNotNone(reason)
        self.assertIn("first five", reason)
        self.assertIn(f"{len(_UNIFORM_BOOKS)}", reason)
        self.assertIn("book", reason)


class BelowFloorBoardDoesNotFabricateConsensusTests(unittest.TestCase):
    """(checker finding #3, 2026-09-12) legacy_quotes_from_board applies no
    minimum-book floor -- correctly, a single quoted book is still a real
    quote worth screening a candidate against -- but nothing downstream
    compensated: a board under prices.MIN_BOOKS (6) produced a REAL board-
    derived market section while price_improvement stayed skipped below
    the floor, and market_implied_consensus (sourced, pre-checker-fix,
    from that board-derived section) printed a "fair price across the
    books" number on a row the SAME payload's board_summary called unpriced
    (has_board: False). Same contradiction this whole mission exists to
    remove, on a row no fixture in this file exercised (every board here
    was 6+ books until now).

    PRE-FIX FAILURE (of the checker's follow-up, not the original
    mission): market_implied_consensus was non-null on a 1-book board
    because _market_implied_consensus read dossier["market"]["markets"]
    ["h2h"] whenever it existed, with no way to tell a single-book quote
    apart from a real board average.
    """

    def test_one_book_board_leaves_consensus_null(self):
        game = _game()
        price_key = prices_mod.matchup_key(
            game["away_team"], game["home_team"], game["date"])
        board = _board([("book_a", -150, 130)])
        entry, _ = _build(game, price_boards_by_key={price_key: board})
        dossier = entry["dossier"]

        self.assertIsNotNone(
            dossier.get("market"),
            "a real single-book quote is still a real quote for screening")
        self.assertIsNone(
            dossier.get("price_improvement"),
            "one book is below the 6-book floor -- no consensus exists")

        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        self.assertIsNone(
            row["market_implied_consensus"],
            "no averaged consensus exists below the floor -- must not "
            "fabricate one from the single book on the board")
        self.assertFalse(row["board_summary"]["has_board"])


class VerdictReasonBookCountGuardTests(unittest.TestCase):
    """(checker finding #4, 2026-09-12) `_board_book_count` returns 0 when
    a dossier's market section did not come with a price_improvement or a
    multibook_board attached -- an explicit caller supplied a market with
    no accompanying board. Naming "0 books" (or "the board is real: 0
    books") in either verdict_reason branch below is the identical
    contradiction-on-one-screen this fix exists to remove, just spelled
    with a number instead of a missing hero. Not reachable through any
    api/ caller today (api/games.py, api/today.py, api/digest.py,
    api/betcheck.py never pass prices_by_matchup to build_slate), so this
    drives dossier_mod.build and briefing.make_entry directly rather than
    through build_slate, to reach the call shape the checker flagged as
    "one caller away".

    PRE-FIX FAILURE: before the checker's follow-up, the F5 branch always
    printed "The full-game board is real: 0 books." when book count was
    zero, with no guard; the full-game sibling branch always printed the
    generic sentence regardless of whether the board was actually
    populated, which the third test below distinguishes.
    """

    def _game(self):
        return {"game_pk": 990199, "date": "2026-08-31",
                "away_team": "SEA", "home_team": "TEX",
                "venue": "T-Mobile Park",
                "start_time_utc": "2026-08-31T23:05:00Z"}

    def test_f5_branch_falls_back_when_book_count_is_zero(self):
        game = self._game()
        store = history.read_results()
        dossier = dossier_mod.build(
            game, store, prices={"h2h": {"away_price": -110, "home_price": -110}})
        entry = briefing.make_entry(
            dossier, verdict=mismatch_mod.MARKET_UNAVAILABLE,
            scan={"market": mismatch_mod.MARKET_F5})
        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        self.assertEqual(row["verdict_reason"],
                         "No book on our board quoted this game.")

    def test_full_game_sibling_falls_back_when_book_count_is_zero(self):
        game = self._game()
        store = history.read_results()
        dossier = dossier_mod.build(
            game, store,
            prices={"h2h_1st_5_innings": {"away_price": -110, "home_price": -110}})
        entry = briefing.make_entry(
            dossier, verdict=mismatch_mod.MARKET_UNAVAILABLE,
            scan={"market": mismatch_mod.MARKET_FULL})
        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        self.assertEqual(row["verdict_reason"],
                         "No book on our board quoted this game.")

    def test_full_game_sibling_names_the_board_when_it_is_populated(self):
        game = self._game()
        store = history.read_results()
        board = _board(_UNIFORM_BOOKS)
        dossier = dossier_mod.build(
            game, store,
            prices={"h2h_1st_5_innings": {"away_price": -110, "home_price": -110}},
            price_board=board)
        entry = briefing.make_entry(
            dossier, verdict=mismatch_mod.MARKET_UNAVAILABLE,
            scan={"market": mismatch_mod.MARKET_FULL})
        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        reason = row["verdict_reason"]
        self.assertIsNotNone(reason)
        self.assertIn(f"{len(_UNIFORM_BOOKS)}", reason)
        self.assertIn("book", reason)
        self.assertNotEqual(reason, "No book on our board quoted this game.")


class NoPlayCarriesNoVerdictReasonTests(unittest.TestCase):
    """(g) A no_play row's verdict_reason is None -- the field exists only
    to explain a market_unavailable verdict, and must not print a
    market-shaped sentence next to an entirely different verdict."""

    def test_no_play_reason_is_none(self):
        # No pitcher_logs, no team-features store content for these two
        # clubs on this date -- both signals stay unfired and scan_game
        # (run for real, unmocked) returns NO_PLAY.
        entry, _ = _build()
        self.assertEqual(entry["verdict"], mismatch_mod.NO_PLAY)
        row = gamepayload.slate_game_summary(entry, now=datetime.now(timezone.utc))
        self.assertIsNone(row["verdict_reason"])


class TheServerSentenceSpeaksPlainly(unittest.TestCase):
    """today.js renders verdict_reason verbatim as the hero body, so the
    browser-side jargon test cannot see it (its scanner reads only quoted
    `text:` literals). Caught by the second check on 2026-09-12: the server
    sentence said "cleared the talent bar and was routed to". Fails on that."""

    def test_no_engine_jargon_in_verdict_reason(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / "src" / "analysis"
               / "gamepayload.py").read_text(encoding="utf-8")
        body = src.split("def _verdict_reason(")[1].split("\ndef ")[0]
        # Skip the docstring and comments: they quote the old wording as
        # the record of what was fixed.
        after_docstring = body.split('"""', 2)[2]
        code = "\n".join(line for line in after_docstring.splitlines()
                         if not line.strip().startswith("#")).lower()
        for phrase in ("talent bar", "routed to"):
            self.assertNotIn(phrase, code, phrase)


if __name__ == "__main__":
    unittest.main()
