"""S5 -- the slate runner (`src.engine.slate`): frozen-before-outcome,
idempotency, the first-pitch guard, and the pre-registered selection rule.
Every fixture here is a temp-directory L1/commence store -- no real capture
data is read.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from src.board.ids import selection_id
from src.engine import glue as glue_module
from src.engine import slate
from src.engine.analyze import Proposal
from src.ledger.chain import HashChainLedger

GAME_A = "aaaa1111aaaa1111aaaa1111aaaa1111"
GAME_B = "bbbb2222bbbb2222bbbb2222bbbb2222"

HOME_SEL = selection_id(sport="mlb", market_key="h2h", side="home")
AWAY_SEL = selection_id(sport="mlb", market_key="h2h", side="away")


def _l1_row(event_id, side, price, book, observed_utc):
    market_key = "h2h"
    sel = HOME_SEL if side == "home" else AWAY_SEL
    return {
        "sport": "mlb", "event_id": event_id, "game_pk": None,
        "market_key": market_key, "selection_id": sel, "side": side,
        "subject_kind": None, "subject_id": None, "line": None, "book": book,
        "price_american": price, "observed_utc": observed_utc,
        "book_last_update": None, "known_at": observed_utc,
        "known_at_grade": "A", "capture_id": f"c-{observed_utc}-{book}",
        "source": "odds_api", "region": "us", "provider_market_key": market_key,
        "venue_kind": "sportsbook", "is_close": False, "limit_observed": None,
        "l0_available": False,
    }


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _two_book_rows(event_id, observed_utc, home_price=-150, away_price=130):
    """Two books quoting both sides -- `src.engine.adversaries.ThinBoard`'s
    default `min_books=2` FATAL-vetoes anything thinner, and every test in
    this module runs the REAL `DEFAULT_ADVERSARIES` roster (the default),
    so every fixture needs at least two books to survive ATTACK."""
    return [
        _l1_row(event_id, "home", home_price, "book_a", observed_utc),
        _l1_row(event_id, "away", away_price, "book_a", observed_utc),
        _l1_row(event_id, "home", home_price, "book_b", observed_utc),
        _l1_row(event_id, "away", away_price, "book_b", observed_utc),
    ]


@dataclass(frozen=True, slots=True)
class NullPModelSystem:
    """A minimal `AnalysisSystem` that always proposes home/h2h with NO
    p_model -- the honest-probabilities fixture: it must never come back
    from `analyze()` with a fabricated probability."""

    id: str = "null_p_model_system"
    version: str = "1.0"
    spec_hash: str = "null_p_model_system:1"
    declared_markets: tuple = ("h2h",)
    declared_inputs: tuple = ()
    min_grade: str = "D"
    expected_selection_rate: float = 1.0

    def propose(self, view):
        if "h2h" not in view.available_markets:
            return ()
        return (Proposal(system_id=self.id, system_version=self.version,
                         market_key="h2h", side="home",
                         thesis="always home, no probability"),)


class SlateTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.l1_path = base / "l1_observations.jsonl"
        self.commence_path = base / "odds_snapshots.jsonl"
        self.decisions_path = base / "decisions_v2.jsonl"
        self.wagers_path = base / "paper_wagers_v2.jsonl"

    def _commence_rows(self, event_id, commence_time):
        _write_jsonl(self.commence_path, [
            {"event_id": event_id, "commence_time": commence_time,
             "home_team": "Boston Red Sox", "away_team": "New York Yankees"},
        ])

    def run_slate(self, date_str, **kwargs):
        kwargs.setdefault("l1_path", self.l1_path)
        kwargs.setdefault("commence_path", self.commence_path)
        kwargs.setdefault("decisions_path", self.decisions_path)
        kwargs.setdefault("wagers_path", self.wagers_path)
        kwargs.setdefault("game_pk_map", {})
        return slate.run_slate(date_str, **kwargs)


class TestFrozenBeforeOutcome(SlateTestBase):
    def test_decision_written_before_any_result_and_chain_verifies(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))

        self.assertEqual(report.n_new_decisions, 1)
        self.assertEqual(report.n_new_wagers, 1)

        rows = HashChainLedger(self.decisions_path).read()
        decision_rows = [r for r in rows if r.get("kind") != "genesis"]
        self.assertEqual(len(decision_rows), 1)
        row = decision_rows[0]
        # No result/outcome field exists ANYWHERE on a DecisionRecord --
        # this is a schema fact, asserted here so a future field addition
        # cannot quietly reintroduce one.
        self.assertNotIn("outcome", row)
        self.assertNotIn("result", row)
        self.assertNotIn("settled", row)
        self.assertEqual(row["verdict"], "play")
        self.assertEqual(row["stake_units"], 1.0)

        verify = HashChainLedger(self.decisions_path).verify()
        self.assertTrue(verify.ok, verify.reason)
        wager_verify = HashChainLedger(self.wagers_path).verify()
        self.assertTrue(wager_verify.ok, wager_verify.reason)


class TestIdempotency(SlateTestBase):
    def test_rerun_same_date_writes_no_duplicates(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        systems = (glue_module.TrivialAlwaysHomeSystem(),)

        first = self.run_slate("2026-09-02", systems=systems)
        second = self.run_slate("2026-09-02", systems=systems)

        self.assertEqual(first.n_new_decisions, 1)
        self.assertEqual(second.n_new_decisions, 0)
        self.assertEqual(second.n_duplicate_decisions, 1)
        self.assertEqual(second.n_new_wagers, 0)
        self.assertEqual(second.n_duplicate_wagers, 1)

        decision_rows = [r for r in HashChainLedger(self.decisions_path).read()
                         if r.get("kind") != "genesis"]
        self.assertEqual(len(decision_rows), 1)
        wager_rows = HashChainLedger(self.wagers_path).read()
        self.assertEqual(len(wager_rows), 1)


class TestFirstPitchGuard(SlateTestBase):
    def test_in_play_capture_is_skipped_not_staked(self):
        # Only capture is AT commence_time -- in-play, must be skipped.
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T20:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))

        self.assertEqual(report.n_games_considered, 1)
        self.assertEqual(report.n_games_skipped, 1)
        self.assertEqual(report.n_new_decisions, 0)
        self.assertEqual(report.n_new_wagers, 0)
        game = report.games[0]
        # The only capture is at/after commence_time - margin, so no
        # eligible PRE-GAME capture exists at all -- the first-pitch guard
        # excludes the game rather than staking an in-play board.
        self.assertIn("commence_time", game.skipped_reason)

    def test_unknown_commence_time_is_never_assumed_pregame_for_any_date(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        # No commence_path row at all for GAME_A: `games_for_slate_date`
        # cannot assign it to ANY date's slate (never guesses which date a
        # game with no known first pitch belongs to), so it is simply
        # absent from the slate entirely -- zero decisions, zero wagers,
        # never a silently-assumed pre-game decision on the wrong date.
        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))
        self.assertEqual(report.n_games_considered, 0)
        self.assertEqual(report.n_new_decisions, 0)
        self.assertEqual(report.n_new_wagers, 0)

        # decision_time_for_game, called directly, names why.
        t, commence, reason = slate.decision_time_for_game(
            GAME_A, "2026-09-02", l1_path=self.l1_path,
            commence_path=self.commence_path, game_pk_map={})
        self.assertIsNone(t)
        self.assertIn("commence_time unknown", reason)


class TestSelectionRuleRecorded(SlateTestBase):
    def test_every_written_record_carries_the_named_selection_rule(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))
        game = report.games[0]
        self.assertTrue(game.records)
        for record in game.records:
            self.assertEqual(record.selection_rule, slate.SELECTION_RULE)
        rows = [r for r in HashChainLedger(self.decisions_path).read()
               if r.get("kind") != "genesis"]
        for row in rows:
            self.assertEqual(row["selection_rule"], slate.SELECTION_RULE)

    def test_selection_rule_is_a_named_pre_registered_constant_with_rationale(self):
        self.assertIsInstance(slate.SELECTION_RULE, str)
        self.assertTrue(slate.SELECTION_RULE)
        self.assertIsInstance(slate.SELECTION_RULE_RATIONALE, str)
        self.assertGreater(len(slate.SELECTION_RULE_RATIONALE), 40)


class TestHonestProbabilities(SlateTestBase):
    def test_null_p_model_never_defaulted_by_the_slate_runner(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        report = self.run_slate(
            "2026-09-02", systems=(NullPModelSystem(),))
        game = report.games[0]
        self.assertTrue(game.records)
        record = game.records[0]
        self.assertIsNone(record.p_model)
        self.assertIsNone(record.rating)
        self.assertIsNotNone(record.value_basis)
        # No expected value: edge_bps is None whenever p_model is None,
        # never a computed number standing in for one.
        self.assertIsNone(record.edge_bps)
        # But it still gets staked (FLAT_1U never depends on p_model).
        self.assertEqual(record.stake_units, slate.FLAT_1U)


class TestFlatOneUnit(SlateTestBase):
    def test_every_staked_wager_is_exactly_flat_1u(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        self.run_slate("2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))
        wager_rows = HashChainLedger(self.wagers_path).read()
        self.assertEqual(len(wager_rows), 1)
        self.assertEqual(wager_rows[0]["stake_units"], 1.0)
        self.assertEqual(wager_rows[0]["label"], "PAPER")


class TestScopeMarkets(SlateTestBase):
    def test_only_the_four_scoped_markets_are_ever_written(self):
        for market_key in slate.SCOPE_MARKETS:
            self.assertIn(market_key,
                         ("h2h", "spreads", "totals", "h2h_1st_5_innings"))
        self.assertEqual(
            set(slate.SCOPE_MARKETS),
            {"h2h", "spreads", "totals", "h2h_1st_5_innings"})


class TestDryRun(SlateTestBase):
    def test_dry_run_writes_nothing(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            dry_run=True)
        self.assertEqual(report.n_new_decisions, 1)
        self.assertFalse(self.decisions_path.exists())
        self.assertFalse(self.wagers_path.exists())


if __name__ == "__main__":
    unittest.main()
