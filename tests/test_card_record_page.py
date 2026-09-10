"""THE RECORD page: GET /card/history, card_ledger.history(), and
web/js/cardrecord.js -- the public receipts surface (2026-09-10).

FOUR THINGS THIS FILE GUARDS, MATCHING THE BUILD BRIEF
--------------------------------------------------------------------------
1. Route order does not regress. /card/history shares api/card.py's
   declaration-order hazard with /card/record (tests/test_api_card.py's
   own module docstring): declared after /card/{date}, "history" is
   captured as a date and 400s. test_api_card.py's RouteOrder class is the
   primary suite for the router itself; the check here confirms the same
   invariant from this feature's own test file.
2. An empty record renders the honest empty state. There is no JS
   execution harness anywhere in this repo (tests/ is unittest against
   Python only) -- the same constraint tests/test_no_nothing_clears_the_bar
   .py already works under, which inspects web/'s SOURCE TEXT rather than
   a rendered DOM. This file does the same for cardrecord.js's empty-state
   branch and copy, and separately proves the SERVER data that gates it
   (card_ledger.record()'s `days`) reads 0, never a fabricated non-null
   rate, on an empty ledger. Actually looking at the page is still the
   real check -- see the human verification this task also requires.
3. Losses and voids are present in the output, never dropped. Tested
   against an isolated temporary ledger (same LedgerCase pattern
   tests/test_card_ledger.py uses) so the assertions do not depend on
   whatever this checkout's real evidence/cards_v1.jsonl happens to hold
   today.
4. The jargon ban passes. Reuses tests/test_no_nothing_clears_the_bar.py's
   own banned-phrase/jargon lists and stripper against cardrecord.js
   specifically, rather than redefining a second copy of that list that
   could drift from the one the rest of the suite enforces.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger
from src.analysis import daily_card
from tests.test_no_nothing_clears_the_bar import (
    BANNED_JARGON,
    BANNED_PHRASES,
    _normalise,
    _strip_js_comments,
)

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import card as card_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDRECORD_JS = os.path.join(ROOT, "web", "js", "cardrecord.js")


def _card(date, picks):
    return {
        "date": date,
        "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
        "basis": "basis sentence",
        "disclaimer": "disclaimer sentence",
        "model_id": "run_expectancy_poisson_v1",
        "calibrated": True,
        "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
        "filled": 0,
        "games_on_slate": len(picks),
        "picks": picks,
    }


def _pick(rank, game_pk, side="home", price=-150, market="moneyline", line=None,
          book="draftkings", books=8, label="STRONG"):
    return {
        "rank": rank, "label": label, "bet": f"Take team {rank} at {price}",
        "why": ["because"], "market": market, "line": line, "side": side,
        "team": "AAA", "team_name": f"Team{rank}", "opponent_name": f"Opp{rank}",
        "price": price, "book": book, "books": books,
        "confidence": 0.6, "market_probability": 0.6, "model_probability": 0.58,
        "game_id": f"g{rank}", "game_pk": game_pk, "event_id": f"e{rank}",
        "away_team": "AWY", "home_team": "HME",
        "first_pitch_utc": "2026-09-08T23:05:00Z",
        "observed_utc": "2026-09-08T18:00:00Z", "model": {},
    }


class LedgerCase(unittest.TestCase):
    """Same isolation discipline as tests/test_card_ledger.py: every test
    runs against a temporary ledger path, never the real
    evidence/cards_v1.jsonl -- a test that appends to the real chain would
    be tampering with the evidence it exists to protect."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")


# ---------------------------------------------------------------------------
# 3. Losses and voids are present in the output, never dropped.
# ---------------------------------------------------------------------------

class LossesAndVoidsSurface(LedgerCase):
    def setUp(self):
        super().setUp()
        picks = [
            _pick(1, 111, side="home", price=-150, book="draftkings", books=9),   # will WIN
            _pick(2, 222, side="home", price=-120, book="fanduel", books=7),      # will LOSE
            _pick(3, 333, side="away", price=+110, book="betmgm", books=6),       # will LOSE
            _pick(4, 444, side="home", price=-105, book="caesars", books=5),      # no result -> VOID
        ]
        card_ledger.publish(_card("2026-09-08", picks), path=self.path)
        results = {
            111: {"away_score": "2", "home_score": "5"},  # home wins
            222: {"away_score": "6", "home_score": "1"},  # home loses
            333: {"away_score": "1", "home_score": "4"},  # away side loses
            # 444 deliberately has no entry -> grade_pick sees no score -> VOID
        }
        self.settled = card_ledger.settle("2026-09-08", results, path=self.path)

    def test_settle_itself_keeps_every_pick_including_the_loss_and_the_void(self):
        results = [p["result"] for p in self.settled["picks"]]
        self.assertEqual(4, len(results), "a pick went missing during settlement")
        self.assertEqual(["WIN", "LOSS", "LOSS", "VOID"], results)

    def test_record_counts_losses_and_voids_rather_than_hiding_them(self):
        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["wins"])
        self.assertEqual(2, rec["losses"])
        self.assertEqual(1, rec["voids"], "the postponed/unscored pick must still be counted")
        self.assertEqual(3, rec["n_staked"], "voids must not be counted as staked bets")

    def test_history_carries_the_loss_and_void_picks_with_their_reasons(self):
        hist = card_ledger.history(path=self.path)
        self.assertEqual(1, len(hist["days"]))
        day = hist["days"][0]
        self.assertEqual(2, day["losses"])
        self.assertEqual(1, day["voids"])
        picks_by_result = {}
        for p in day["picks"]:
            picks_by_result.setdefault(p["result"], []).append(p)
        self.assertEqual(1, len(picks_by_result.get("WIN", [])))
        self.assertEqual(2, len(picks_by_result.get("LOSS", [])))
        void_picks = picks_by_result.get("VOID", [])
        self.assertEqual(1, len(void_picks))
        self.assertTrue(void_picks[0]["reason"], "a VOID pick must explain itself, not read blank")

    def test_history_joins_book_and_team_names_from_the_published_row(self):
        """The settled row alone does not carry book/team names (see
        card_ledger.history's own docstring on why the join exists) -- a
        regression here would silently blank out BOOK on the record page
        while every number kept looking fine."""
        hist = card_ledger.history(path=self.path)
        by_rank = {p["rank"]: p for p in hist["days"][0]["picks"]}
        self.assertEqual("draftkings", by_rank[1]["book"])
        self.assertEqual(9, by_rank[1]["books"])
        self.assertEqual("Team2", by_rank[2]["team_name"])

    def test_win_rate_is_none_not_zero_when_nothing_is_staked(self):
        """Absent != zero. A day where every pick voids must not report a
        fabricated 0% win rate."""
        empty_path = os.path.join(self._tmp.name, "all_void.jsonl")
        card_ledger.publish(_card("2026-09-09", [_pick(1, 999)]), path=empty_path)
        card_ledger.settle("2026-09-09", {}, path=empty_path)  # no results at all -> VOID
        rec = card_ledger.record(path=empty_path)
        self.assertEqual(0, rec["n_staked"])
        self.assertIsNone(rec["win_rate"], "an all-void day must not read as a 0% win rate")
        self.assertIsNone(rec["roi_pct"])


class HistoryPagination(LedgerCase):
    def test_limit_caps_and_reports_truncation_honestly(self):
        for i, date in enumerate(["2026-09-01", "2026-09-02", "2026-09-03"]):
            card_ledger.publish(_card(date, [_pick(1, 1000 + i)]), path=self.path)
            card_ledger.settle(date, {1000 + i: {"away_score": "1", "home_score": "9"}},
                               path=self.path)

        capped = card_ledger.history(path=self.path, limit=2)
        self.assertEqual(2, len(capped["days"]))
        self.assertEqual(3, capped["total_days"])
        self.assertTrue(capped["truncated"])
        # Newest first.
        self.assertEqual(["2026-09-03", "2026-09-02"], [d["date"] for d in capped["days"]])

        uncapped = card_ledger.history(path=self.path, limit=10)
        self.assertEqual(3, len(uncapped["days"]))
        self.assertFalse(uncapped["truncated"])

    def test_an_empty_ledger_reports_zero_not_a_missing_key(self):
        hist = card_ledger.history(path=self.path)
        self.assertEqual([], hist["days"])
        self.assertEqual(0, hist["total_days"])
        self.assertFalse(hist["truncated"])


# ---------------------------------------------------------------------------
# 1. Route order does not regress (see test_api_card.py for the fuller
#    router-level suite; this confirms the same invariant here).
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class RouteOrderFromThisFeature(unittest.TestCase):
    def test_history_is_declared_before_the_date_route(self):
        paths = [getattr(r, "path", None) for r in card_api.router.routes]
        self.assertIn("/card/history", paths)
        self.assertIn("/card/{date}", paths)
        self.assertLess(paths.index("/card/history"), paths.index("/card/{date}"))


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class ApiShape(unittest.TestCase):
    """Direct-call tests against whatever real (possibly empty) on-disk
    ledger this checkout has -- same offline pattern as
    tests/test_api_daily.py. No auth dependency is visible at this level
    (router-level `dependencies=` is invisible to a direct function call);
    tests/test_api_card.py's CardRequiresAuth drives the real ASGI app to
    prove the gate itself. Because the real store's CONTENT is unknown
    here, these only assert shape/keys/limits, never specific win/loss
    figures -- that is LossesAndVoidsSurface's job, against an isolated
    ledger it controls completely."""

    def test_record_disclaimer_is_the_one_true_constant_not_a_second_copy(self):
        payload = card_api.get_card_record()
        self.assertEqual(daily_card.CARD_DISCLAIMER, payload["disclaimer"])
        self.assertEqual(daily_card.CARD_BASIS, payload["basis"])
        self.assertIn("chain_ok", payload)
        self.assertIn("rows_checked", payload)

    def test_history_returns_the_documented_shape(self):
        payload = card_api.get_card_history(limit=5)
        for key in ("days", "limit", "total_days", "truncated"):
            self.assertIn(key, payload)
        self.assertLessEqual(len(payload["days"]), 5)
        for day in payload["days"]:
            for key in ("date", "wins", "losses", "pushes", "voids", "n_staked",
                       "profit_units", "roi_pct", "row_hash", "published_row_hash", "picks"):
                self.assertIn(key, day)

    def test_limit_out_of_range_is_a_400_not_a_500_or_a_silent_clamp(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            card_api.get_card_history(limit=0)
        self.assertEqual(400, ctx.exception.status_code)
        with self.assertRaises(fastapi.HTTPException) as ctx:
            card_api.get_card_history(limit=card_api.MAX_HISTORY_LIMIT + 1)
        self.assertEqual(400, ctx.exception.status_code)

    def test_limit_at_bounds_is_accepted(self):
        card_api.get_card_history(limit=1)
        card_api.get_card_history(limit=card_api.MAX_HISTORY_LIMIT)


# ---------------------------------------------------------------------------
# 2. An empty record renders the honest empty state (source-text checks --
#    see this module's own docstring on why; the real check is looking at
#    the rendered page, done separately).
# ---------------------------------------------------------------------------

class EmptyStateCopyExists(unittest.TestCase):
    def setUp(self):
        with open(CARDRECORD_JS, encoding="utf-8") as fh:
            self.src = fh.read()

    def test_the_page_gates_on_record_days_not_on_history_length(self):
        """record.days is the pooled, authoritative count; the empty-state
        branch must key off it so a day-by-day fetch hiccup can never masquerade
        as 'nothing has ever settled'."""
        self.assertIn("record.days", self.src)

    def test_the_empty_state_says_nothing_is_graded_yet_in_plain_words(self):
        self.assertIn("Nothing has been graded yet", self.src)
        self.assertIn("including the days it loses", self.src)

    def test_the_empty_state_is_not_hidden_behind_a_generic_loading_state(self):
        """NOTHING SETTLED YET has to be its own labelled panel, not folded
        into the generic renderLoading()/notYetAvailable() treatment, so it
        reads as a fact about the product rather than a stalled fetch."""
        self.assertIn("NOTHING SETTLED YET", self.src)

    def test_voids_note_renders_unconditionally_win_or_zero(self):
        """voidsNote must not be gated behind `if (record.voids)` -- a
        record with zero voids has to say so, not go silent. Checked by the
        presence of the explicit zero-voids sentence, which only exists on
        the branch that runs when there ISN'T a truthy void count."""
        self.assertIn("No pick has gone ungraded so far", self.src)


class JargonBanOnCardRecordPage(unittest.TestCase):
    """Same lists tests/test_no_nothing_clears_the_bar.py enforces across
    the rest of web/ -- reused, not re-typed, so this can never drift from
    what the rest of the suite considers banned."""

    def setUp(self):
        with open(CARDRECORD_JS, encoding="utf-8") as fh:
            raw = fh.read()
        self.text = _normalise(_strip_js_comments(raw))

    def test_no_banned_verdict_phrase(self):
        offenders = [p for p in BANNED_PHRASES if p in self.text]
        self.assertEqual([], offenders)

    def test_no_unexplained_jargon(self):
        offenders = [p for p in BANNED_JARGON if p in self.text]
        self.assertEqual([], offenders)

    def test_never_claims_an_edge_or_positive_expected_value(self):
        for phrase in ("positive expected value", "guaranteed", "beats the market"):
            self.assertNotIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
