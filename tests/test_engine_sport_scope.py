"""The MLB engine's sport scope (2026-09-21).

THE BUG. `src.board.l1.run` projects every odds_multibook/odds_snapshots row
into L1 and stamps each observation `sport="mlb"` whatever sport its source
row was, and the engine read every L1 key. So the 2026-09-20 slate staked 84
paper wagers on 14 NFL games (6 baseline systems x 14 games), and `engine
settle --date 2026-09-20` refused the whole date ("wager(s) with no resolved
game_pk at all"), blocking the 113 genuine MLB wagers behind them.

What is pinned here, every fixture a temp directory (no real store is read):

  * an NFL event -- L1 rows labelled "mlb" exactly as l1.run writes them,
    its SOURCE row tagged "nfl" -- never becomes a slate game, a board, a
    captured game or a wager (and the same for any other non-MLB tag);
  * settle on a date mixing MLB wagers and NFL-leaked wagers settles the MLB
    ones normally and VOIDs the NFL ones with an explicit reason, appended to
    the account ledger like any settlement, never rewriting a wager row;
  * a genuine MLB wager with no resolved game_pk (or no result) still
    refuses the date -- the NFL wagers are not what the refusal names.

Checked against the pre-fix src/engine (HEAD glue/slate/settle_slate in a
temp copy): every test in TestNflRowNeverBecomesACandidate,
TestMixedDateSettlesMlbAndVoidsNfl and the first two of
TestGenuineMlbGapStillRefuses fails there on the behaviour itself (NFL game
staked / whole date refused / refusal names the NFL event). The two guard
tests (MLB tags stay in scope; an untagged unknown event is never voided)
pin the fix's edges.
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.board.ids import selection_id
from src.engine import glue as glue_module
from src.engine import settle_slate
from src.engine import slate
from src.ledger.chain import HashChainLedger

DATE = "2026-09-02"
GAME_MLB = "aaaa1111aaaa1111aaaa1111aaaa1111"
GAME_NFL = "0283a29e1b38ef78b29b904fd56a16dd"  # real id: MIN @ CHI, 2026-09-20
GAME_TENNIS = "ff148419f7d5eb25e56152d03d978141"

HOME_SEL = selection_id(sport="mlb", market_key="h2h", side="home")
AWAY_SEL = selection_id(sport="mlb", market_key="h2h", side="away")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _l1_row(event_id, side, price, book, observed_utc):
    """An L1 PriceObservation row exactly as `src.board.l1.run` writes one
    -- `sport` is "mlb" for EVERY row, an NFL game's included, because the
    projector never carries the source row's own tag through."""
    return {
        "sport": "mlb", "event_id": event_id, "game_pk": None,
        "market_key": "h2h", "selection_id": HOME_SEL if side == "home" else AWAY_SEL,
        "side": side, "subject_kind": None, "subject_id": None, "line": None,
        "book": book, "price_american": price, "observed_utc": observed_utc,
        "book_last_update": None, "known_at": observed_utc,
        "known_at_grade": "A", "capture_id": f"c-{observed_utc}-{book}",
        "source": "odds_api", "region": "us", "provider_market_key": "h2h",
        "venue_kind": "sportsbook", "is_close": False, "limit_observed": None,
        "l0_available": False,
    }


def _two_book_rows(event_id, observed_utc):
    return [
        _l1_row(event_id, "home", -150, "book_a", observed_utc),
        _l1_row(event_id, "away", 130, "book_a", observed_utc),
        _l1_row(event_id, "home", -150, "book_b", observed_utc),
        _l1_row(event_id, "away", 130, "book_b", observed_utc),
    ]


def _snapshot_row(event_id, observed_utc, commence_time, book, *, sport=None,
                  home="Boston Red Sox", away="New York Yankees"):
    """A raw `odds_snapshots.jsonl` row in the capture path's real shape: an
    MLB row carries NO `sport` key; any other sport carries its tag."""
    row = {
        "observed_utc": observed_utc, "event_id": event_id,
        "commence_time": commence_time, "away_team": away, "home_team": home,
        "market": "h2h", "book": book,
        "prices": {"home_price": -150, "away_price": 130},
        "book_last_update": observed_utc,
    }
    if sport is not None:
        row["sport"] = sport
    return row


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.l1_path = self.base / "l1_observations.jsonl"
        # The commence store IS the real L1 source store's name, sitting next
        # to L1 -- the same layout as data/processed/.
        self.commence_path = self.base / "odds_snapshots.jsonl"
        self.multibook_path = self.base / "odds_multibook.jsonl"
        self.decisions_path = self.base / "decisions_v2.jsonl"
        self.wagers_path = self.base / "paper_wagers_v2.jsonl"

    def _write_mlb_and_nfl_board(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_MLB, f"{DATE}T18:00:00Z"),
            *_two_book_rows(GAME_NFL, f"{DATE}T18:00:00Z"),
        ])
        _write_jsonl(self.commence_path, [
            _snapshot_row(GAME_MLB, f"{DATE}T18:00:00Z", f"{DATE}T23:05:00Z",
                          "book_a"),
            _snapshot_row(GAME_NFL, f"{DATE}T18:00:00Z", f"{DATE}T22:00:00Z",
                          "book_a", sport="nfl", home="Chicago Bears",
                          away="Minnesota Vikings"),
        ])

    def _run_slate(self, **kwargs):
        kwargs.setdefault("systems", (glue_module.TrivialAlwaysHomeSystem(),))
        kwargs.setdefault("l1_path", self.l1_path)
        kwargs.setdefault("commence_path", self.commence_path)
        kwargs.setdefault("decisions_path", self.decisions_path)
        kwargs.setdefault("wagers_path", self.wagers_path)
        kwargs.setdefault("game_pk_map", {})
        return slate.run_slate(DATE, **kwargs)

    def _staked_events(self):
        return {r.get("event_id") for r in HashChainLedger(self.wagers_path).read()
                if r.get("bet_id")}

    def _decided_events(self):
        return {r.get("event_id") for r in HashChainLedger(self.decisions_path).read()
                if "decision_utc" in r}


# ---------------------------------------------------------------------------
# 1. An NFL row never becomes an engine candidate
# ---------------------------------------------------------------------------

class TestNflRowNeverBecomesACandidate(_TempDirCase):
    def test_slate_stakes_the_mlb_game_and_never_the_nfl_game(self):
        self._write_mlb_and_nfl_board()

        report = self._run_slate()

        # Behaviour first: what was actually frozen and staked.
        self.assertNotIn(GAME_NFL, self._staked_events(),
                         "an NFL game was staked by the MLB engine")
        self.assertNotIn(GAME_NFL, self._decided_events(),
                         "an NFL game got a frozen MLB DecisionRecord")
        self.assertEqual(self._staked_events(), {GAME_MLB})
        self.assertEqual([g.game_key for g in report.games], [GAME_MLB])
        # ...and the exclusion is counted, not silent.
        self.assertEqual(report.excluded_non_mlb, ((GAME_NFL, "nfl"),))

    def test_nfl_capture_projected_by_the_real_l1_refresh_is_never_staked(self):
        """End to end through the real projector: raw source rows (one MLB,
        one NFL tagged "nfl") -> `run_slate`'s own L1 refresh -> L1 (where
        the NFL rows come out labelled "mlb", the actual bug) -> slate."""
        self.assertFalse(self.l1_path.exists())
        _write_jsonl(self.commence_path, [
            _snapshot_row(GAME_MLB, f"{DATE}T18:00:00Z", f"{DATE}T23:05:00Z", "book_a"),
            _snapshot_row(GAME_MLB, f"{DATE}T18:00:00Z", f"{DATE}T23:05:00Z", "book_b"),
            _snapshot_row(GAME_NFL, f"{DATE}T18:00:00Z", f"{DATE}T22:00:00Z", "book_a",
                          sport="nfl", home="Chicago Bears", away="Minnesota Vikings"),
            _snapshot_row(GAME_NFL, f"{DATE}T18:00:00Z", f"{DATE}T22:00:00Z", "book_b",
                          sport="nfl", home="Chicago Bears", away="Minnesota Vikings"),
        ])

        report = self._run_slate(l1_sources=[{
            "name": "odds_snapshots", "path": self.commence_path,
            "kind": "snapshot", "is_close": False}])

        l1_rows = [json.loads(line) for line in
                   self.l1_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        nfl_l1 = [r for r in l1_rows if r["event_id"] == GAME_NFL]
        # Precondition: the projector really did write the NFL game into L1
        # labelled as MLB -- the input shape the engine must defend against.
        self.assertTrue(nfl_l1)
        self.assertEqual({r["sport"] for r in nfl_l1}, {"mlb"})

        self.assertEqual(self._staked_events(), {GAME_MLB})
        self.assertNotIn(GAME_NFL, self._decided_events())
        self.assertEqual(report.excluded_non_mlb, ((GAME_NFL, "nfl"),))

    def test_nfl_event_is_not_a_captured_game_and_has_no_board_rows(self):
        self._write_mlb_and_nfl_board()
        # games_captured_on feeds the preflight freshness guard and the
        # too-early guard: an NFL capture must not count as an MLB capture.
        self.assertEqual(glue_module.games_captured_on(DATE, path=self.l1_path),
                         (GAME_MLB,))
        self.assertEqual(glue_module.read_l1_observations(GAME_NFL, path=self.l1_path),
                         ())
        self.assertEqual(len(glue_module.read_l1_observations(
            GAME_MLB, path=self.l1_path)), 4)

    def test_any_non_mlb_tag_in_any_sibling_source_store_is_excluded(self):
        """A tennis event tagged only in odds_multibook.jsonl (not in the
        commence store) is still out: every L1 source store is consulted."""
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_MLB, f"{DATE}T18:00:00Z"),
            *_two_book_rows(GAME_TENNIS, f"{DATE}T18:00:00Z"),
        ])
        _write_jsonl(self.commence_path, [
            {"event_id": GAME_MLB, "commence_time": f"{DATE}T23:05:00Z"},
            {"event_id": GAME_TENNIS, "commence_time": f"{DATE}T22:30:00Z"},
        ])
        _write_jsonl(self.multibook_path, [{
            "observed_utc": f"{DATE}T18:00:00Z", "event_id": GAME_TENNIS,
            "commence_time": f"{DATE}T22:30:00Z", "home_team": "Kyoka Okamura",
            "away_team": "Leylah Fernandez", "book": "fanduel",
            "home_price": 1500, "away_price": -3500,
            "sport": "tennis_wta_singapore_open",
        }])

        report = self._run_slate()

        self.assertEqual(self._staked_events(), {GAME_MLB})
        self.assertEqual(report.excluded_non_mlb,
                         ((GAME_TENNIS, "tennis_wta_singapore_open"),))


class TestMlbTagsStayInScope(_TempDirCase):
    """Guard against over-filtering: absent, "mlb" and "baseball_mlb" are
    all MLB. (Not a regression test for the bug -- it pins the fix's edge.)"""

    def test_explicit_mlb_tags_are_not_excluded(self):
        for tag in (None, "", "mlb", "MLB", "baseball_mlb"):
            self.assertTrue(glue_module.is_mlb_sport_tag(tag), tag)
        for tag in ("nfl", "americanfootball_nfl", "tennis_wta_singapore_open"):
            self.assertFalse(glue_module.is_mlb_sport_tag(tag), tag)

        _write_jsonl(self.l1_path, _two_book_rows(GAME_MLB, f"{DATE}T18:00:00Z"))
        _write_jsonl(self.commence_path, [
            _snapshot_row(GAME_MLB, f"{DATE}T18:00:00Z", f"{DATE}T23:05:00Z",
                          "book_a", sport="baseball_mlb"),
        ])
        report = self._run_slate()
        self.assertEqual(self._staked_events(), {GAME_MLB})
        self.assertEqual(report.excluded_non_mlb, ())


# ---------------------------------------------------------------------------
# Settle fixtures
# ---------------------------------------------------------------------------

MLB_PK_1 = 900001   # home wins 5-2
MLB_PK_2 = 900002   # home loses 2-5
SYS_A = "trivial_always_home"
SYS_B = "market_derived_consensus_h2h_home"


def _write_results_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["game_pk", "date", "home_score",
                                                "away_score"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _wager(bet_id, game_pk, event_id, system_id, price=150):
    return {
        "label": "PAPER", "date": DATE, "bet_id": bet_id,
        "system_id": system_id, "market_key": "h2h", "selection_id": HOME_SEL,
        "side": "home", "line": None, "price_american": price,
        "settlement_rule": "h2h", "stake_units": 1.0, "game_pk": game_pk,
        "event_id": event_id, "decision_utc": f"{DATE}T18:00:00+00:00",
        "selection_rule": "TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1",
    }


class _SettleCase(_TempDirCase):
    """`run_settle` is called WITHOUT `sport_source_paths`, exactly as the
    CLI calls it; `glue.L1_PATH` is pointed at this temp dir so the
    production default ("the stores next to the real L1") resolves to the
    fixture stores here and never to data/processed/."""

    def setUp(self):
        super().setUp()
        self.results_path = self.base / "mlb_results.csv"
        self.accounts_dir = self.base / "paper_accounts"
        self.review_path = self.base / "reviews_v2.jsonl"
        self.scorecard_path = self.base / "scorecards_v2.jsonl"
        patcher = mock.patch.object(glue_module, "L1_PATH", self.l1_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The price-source store that tags each event's sport.
        _write_jsonl(self.commence_path, [
            _snapshot_row("evt-mlb-1", f"{DATE}T15:00:00Z", f"{DATE}T23:05:00Z", "fd"),
            _snapshot_row("evt-mlb-2", f"{DATE}T15:00:00Z", f"{DATE}T23:10:00Z", "fd"),
            _snapshot_row("evt-mlb-unmapped", f"{DATE}T15:00:00Z",
                          f"{DATE}T23:20:00Z", "fd"),
            _snapshot_row(GAME_NFL, f"{DATE}T15:00:00Z", f"{DATE}T17:00:00Z", "dk",
                          sport="nfl", home="Chicago Bears", away="Minnesota Vikings"),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": MLB_PK_1, "date": DATE, "home_score": 5, "away_score": 2},
            {"game_pk": MLB_PK_2, "date": DATE, "home_score": 2, "away_score": 5},
        ])

    def account_ledger_path_fn(self, system_id):
        return self.accounts_dir / f"{system_id}.jsonl"

    def run_settle(self, **kwargs):
        kwargs.setdefault("wagers_path", self.wagers_path)
        kwargs.setdefault("results_path", self.results_path)
        kwargs.setdefault("f5_historical_path", self.base / "f5.jsonl")
        kwargs.setdefault("boxscores_glob", str(self.base / "boxscores_*.jsonl"))
        kwargs.setdefault("information_events_path", self.base / "info.jsonl")
        kwargs.setdefault("decisions_path", self.decisions_path)
        kwargs.setdefault("review_path", self.review_path)
        kwargs.setdefault("scorecard_path", self.scorecard_path)
        kwargs.setdefault("account_ledger_path_fn", self.account_ledger_path_fn)
        kwargs.setdefault("game_pk_map_path", self.base / "event_game_map.jsonl")
        return settle_slate.run_settle(DATE, **kwargs)

    def _write_wagers(self, rows):
        ledger = HashChainLedger(self.wagers_path)
        for row in rows:
            ledger.append(row)
        return self.wagers_path.read_bytes()


# ---------------------------------------------------------------------------
# 2. A mixed date settles the MLB wagers and VOIDs the NFL-leaked ones
# ---------------------------------------------------------------------------

class TestMixedDateSettlesMlbAndVoidsNfl(_SettleCase):
    def setUp(self):
        super().setUp()
        self.wagers_bytes = self._write_wagers([
            _wager("mlb-a-1", MLB_PK_1, "evt-mlb-1", SYS_A),        # win +1.5
            _wager("mlb-a-2", MLB_PK_2, "evt-mlb-2", SYS_A),        # loss -1
            _wager("nfl-a", None, GAME_NFL, SYS_A),                 # VOID
            _wager("mlb-b-1", MLB_PK_1, "evt-mlb-1", SYS_B, -120),  # win
            _wager("nfl-b", None, GAME_NFL, SYS_B, 110),            # VOID
        ])

    def test_mlb_settles_nfl_voids_with_the_reason(self):
        report = self.run_settle()   # pre-fix: SettleError for the whole date

        outcomes = {s.bet.bet_id: s for sys in report.systems for s in sys.settled}
        self.assertEqual(outcomes["mlb-a-1"].outcome, "win")
        self.assertAlmostEqual(outcomes["mlb-a-1"].profit_units, 1.5)
        self.assertEqual(outcomes["mlb-a-2"].outcome, "loss")
        self.assertEqual(outcomes["mlb-b-1"].outcome, "win")
        self.assertEqual(outcomes["nfl-a"].outcome, "void")
        self.assertEqual(outcomes["nfl-b"].outcome, "void")
        self.assertEqual(outcomes["nfl-a"].profit_units, 0.0)

        # Counted and reported, with the reason.
        self.assertEqual(report.n_not_mlb_wagers, 2)
        self.assertEqual(report.n_games, 2)  # MLB games only
        self.assertEqual(sorted(v["bet_id"] for v in report.voided_not_mlb),
                         ["nfl-a", "nfl-b"])
        for v in report.voided_not_mlb:
            self.assertEqual(v["event_id"], GAME_NFL)
            self.assertEqual(v["sport"], "nfl")
            self.assertIn("not an MLB event", v["reason"])

        # The bankroll moved by the MLB results only.
        sys_a = next(s for s in report.systems if s.system_id == SYS_A)
        self.assertAlmostEqual(sys_a.bankroll, 1000.0 + 1.5 - 1.0)

    def test_void_is_appended_to_the_account_ledger_with_the_reason(self):
        self.run_settle()
        rows = HashChainLedger(self.account_ledger_path_fn(SYS_A)).read()
        by_id = {r["bet_id"]: r for r in rows}
        self.assertEqual(set(by_id), {"mlb-a-1", "mlb-a-2", "nfl-a"})
        void = by_id["nfl-a"]
        self.assertEqual(void["outcome"], "void")
        self.assertEqual(void["profit_units"], 0.0)
        self.assertEqual(void["day"], DATE)
        self.assertIn("not an MLB event", void["void_reason"])
        self.assertIn("nfl", void["void_reason"])
        self.assertEqual(void["sport"], "nfl")
        self.assertNotIn("void_reason", by_id["mlb-a-1"])
        for system_id in (SYS_A, SYS_B):
            verify = HashChainLedger(self.account_ledger_path_fn(system_id)).verify()
            self.assertTrue(verify.ok, verify.reason)
        # A review is appended for every settled bet, the voids included.
        reviews = HashChainLedger(self.review_path).read()
        self.assertEqual(len(reviews), 5)
        self.assertEqual(sum(1 for r in reviews if r["settled"] == "void"), 2)
        self.assertTrue(HashChainLedger(self.review_path).verify().ok)

    def test_wager_ledger_is_never_rewritten_and_a_rerun_settles_nothing(self):
        self.run_settle()
        second = self.run_settle()
        self.assertEqual(self.wagers_path.read_bytes(), self.wagers_bytes)
        self.assertEqual(sum(len(s.settled) for s in second.systems), 0)
        self.assertEqual(sum(s.duplicate for s in second.systems), 5)
        self.assertEqual(second.n_not_mlb_wagers, 2)
        self.assertEqual(second.voided_not_mlb, ())
        rows = HashChainLedger(self.account_ledger_path_fn(SYS_A)).read()
        self.assertEqual(len(rows), 3)


# ---------------------------------------------------------------------------
# 3. A genuine unresolved MLB wager still refuses -- and it, not the NFL
#    wagers, is what the refusal names
# ---------------------------------------------------------------------------

class TestGenuineMlbGapStillRefuses(_SettleCase):
    def test_unresolved_mlb_wager_refuses_and_names_only_the_mlb_event(self):
        self._write_wagers([
            _wager("mlb-ok", MLB_PK_1, "evt-mlb-1", SYS_A),
            _wager("mlb-unmapped", None, "evt-mlb-unmapped", SYS_A),
            _wager("nfl-a", None, GAME_NFL, SYS_A),
        ])
        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle()
        message = str(ctx.exception)
        self.assertIn("evt-mlb-unmapped", message)
        self.assertNotIn(GAME_NFL, message,
                         "the refusal still blames the NFL wager, so a date "
                         "with NFL-leaked wagers could never settle")
        # Refusal means NOTHING written -- not the MLB win, not the void.
        self.assertFalse(self.account_ledger_path_fn(SYS_A).exists())
        self.assertFalse(self.review_path.exists())

    def test_missing_mlb_result_refuses_and_names_only_the_mlb_game(self):
        self._write_wagers([
            _wager("mlb-ok", MLB_PK_1, "evt-mlb-1", SYS_A),
            _wager("mlb-no-result", 900099, "evt-mlb-2", SYS_A),
            _wager("nfl-a", None, GAME_NFL, SYS_A),
        ])
        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle()
        message = str(ctx.exception)
        self.assertIn("900099", message)
        self.assertNotIn(GAME_NFL, message)
        self.assertFalse(self.account_ledger_path_fn(SYS_A).exists())

    def test_event_no_store_tags_is_never_voided_on_a_guess(self):
        """Unknown to every price store -> not positively another sport ->
        still an unresolved wager that refuses. (Passes pre-fix too.)"""
        self._write_wagers([
            _wager("mystery", None, "evt-not-in-any-store", SYS_A),
        ])
        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle()
        self.assertIn("evt-not-in-any-store", str(ctx.exception))
        self.assertFalse(self.account_ledger_path_fn(SYS_A).exists())


if __name__ == "__main__":
    unittest.main()
