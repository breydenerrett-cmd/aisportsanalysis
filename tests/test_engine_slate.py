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
from datetime import datetime, timezone
from pathlib import Path

from src.board.ids import selection_id
from src.engine import glue as glue_module
from src.engine import slate
from src.engine.analyze import Proposal
from src.ledger.chain import HashChainLedger
from src.ledger.records import (
    RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
    RECORD_PROVENANCE_REPLAY,
)

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


def _historical_l1_row(event_id, side, price, book, observed_utc):
    """A row shaped exactly like `src.board.l1_historical`'s projector would
    write it (source, capture_id prefix, grade D -- see that module's
    module docstring on why 2023-25 archive rows measure out to D)."""
    row = _l1_row(event_id, side, price, book, observed_utc)
    row["source"] = "odds_api_historical_archive"
    row["known_at_grade"] = "D"
    row["capture_id"] = f"historical_archive:odds_history_archive_2023:{observed_utc}"
    return row


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


def _raw_snapshot_h2h_row(event_id, observed_utc, commence_time, book,
                          home_price, away_price):
    """A raw `odds_snapshots.jsonl`-shaped row (kind='snapshot', l1.py's own
    projector) -- NOT an L1-shaped row. Mirrors `test_board_l1.py`'s
    `SNAPSHOT_H2H_ROW` fixture, which is itself copied verbatim from a real
    captured row's field shape."""
    return {
        "observed_utc": observed_utc, "event_id": event_id,
        "commence_time": commence_time,
        "away_team": "New York Yankees", "home_team": "Boston Red Sox",
        "market": "h2h", "book": book,
        "prices": {"home_price": home_price, "away_price": away_price},
        "book_last_update": observed_utc,
    }


class TestL1RefreshBeforeSlate(SlateTestBase):
    """Defect #2: `data/processed/l1_observations.jsonl` is a PROJECTION of
    the real price stores, and nothing re-projected it after a capture, so
    `engine slate` could see prices hours older than what was already
    captured on disk until someone ran `l1 --backfill` by hand. Proves
    `run_slate` closes that gap itself: a "fresh capture" landing only in
    the RAW source store (never touching `l1_path` directly) is picked up
    and projected into L1 by `run_slate`'s own refresh step, with zero
    manual step between the capture and the slate run."""

    def test_fresh_capture_is_seen_with_no_manual_l1_backfill_step(self):
        # The "capture": two books' worth of a real raw odds_snapshots-shaped
        # row, written straight to the raw source path -- `self.l1_path`
        # (the L1 store `run_slate` actually reads to build boards) is never
        # touched here at all; it does not even exist yet.
        self.assertFalse(self.l1_path.exists())
        _write_jsonl(self.commence_path, [
            _raw_snapshot_h2h_row(GAME_A, "2026-09-02T22:00:00Z",
                                  "2026-09-02T23:00:00Z", "book_a", -150, 130),
            _raw_snapshot_h2h_row(GAME_A, "2026-09-02T22:00:00Z",
                                  "2026-09-02T23:00:00Z", "book_b", -150, 130),
        ])

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            l1_sources=[{"name": "odds_snapshots", "path": self.commence_path,
                        "kind": "snapshot", "is_close": False}])

        # The refresh actually wrote L1 rows for the fresh capture...
        self.assertTrue(self.l1_path.exists())
        l1_rows = [json.loads(line) for line in
                  self.l1_path.read_text().splitlines() if line.strip()]
        self.assertTrue(any(r["event_id"] == GAME_A for r in l1_rows))

        # ...and the SAME run priced the game off of it -- no second,
        # separate `l1 --backfill` invocation was needed in between.
        self.assertEqual(report.n_games_considered, 1)
        self.assertEqual(report.n_games_skipped, 0)
        game = report.games[0]
        self.assertIsNone(game.skipped_reason)
        self.assertTrue(any(r.price_american == -150 for r in game.records))

    def test_refresh_is_idempotent_and_incremental(self):
        """A second run over the same, unchanged raw source writes zero new
        L1 rows -- refreshing is safe to run on every slate invocation."""
        _write_jsonl(self.commence_path, [
            _raw_snapshot_h2h_row(GAME_A, "2026-09-02T22:00:00Z",
                                  "2026-09-02T23:00:00Z", "book_a", -150, 130),
            _raw_snapshot_h2h_row(GAME_A, "2026-09-02T22:00:00Z",
                                  "2026-09-02T23:00:00Z", "book_b", -150, 130),
        ])
        kwargs = dict(
            systems=(glue_module.TrivialAlwaysHomeSystem(),),
            l1_sources=[{"name": "odds_snapshots", "path": self.commence_path,
                        "kind": "snapshot", "is_close": False}])
        self.run_slate("2026-09-02", **kwargs)
        rows_after_first = self.l1_path.read_text().splitlines()
        self.run_slate("2026-09-02", **kwargs)
        rows_after_second = self.l1_path.read_text().splitlines()
        self.assertEqual(rows_after_first, rows_after_second)

    def test_refresh_is_skipped_for_an_isolated_l1_path_with_no_sources_named(self):
        """The safety rail: a caller handing `run_slate` a synthetic
        `l1_path` (every OTHER test in this module) without naming
        `l1_sources`/`l1_raw_root` must never have real production price
        stores silently projected into its fixture -- refresh only fires
        when it is told exactly what to refresh from, or when `l1_path` is
        the real production store."""
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        before = self.l1_path.read_text()
        self.run_slate("2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))
        after = self.l1_path.read_text()
        self.assertEqual(before, after)


class TestRecordedUtcIsWriteInstant(SlateTestBase):
    """B1 (slice-review-2026-09-03): `recorded_utc` must be the real
    wall-clock write instant, not a copy of `decision_utc`/
    `information_time` -- this pins the PRODUCTION value `run_slate`
    actually writes, not just a hand-built fixture's assumption."""

    def test_live_mode_recorded_utc_is_now_not_the_decision_instant(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        now = datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc)

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            now=now)

        game = report.games[0]
        self.assertTrue(game.records)
        record = game.records[0]
        self.assertEqual(record.decision_utc, slate._iso(slate._parse_utc("2026-09-02T18:00:00Z")))
        self.assertEqual(record.information_time, slate._iso(slate._parse_utc("2026-09-02T18:00:00Z")))
        # The write instant, NOT the decision instant -- the whole point of
        # B1: a record must carry independent evidence of when it was
        # written.
        self.assertEqual(record.recorded_utc, slate._iso(now))
        self.assertNotEqual(record.recorded_utc, record.decision_utc)
        self.assertEqual(record.record_provenance,
                         RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT)

        # And the ledger row on disk carries the same, not just the
        # in-memory dataclass.
        rows = [r for r in HashChainLedger(self.decisions_path).read()
               if r.get("kind") != "genesis"]
        self.assertEqual(rows[0]["recorded_utc"], slate._iso(now))
        self.assertEqual(rows[0]["record_provenance"],
                         RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT)

    def test_replay_mode_recorded_utc_is_still_the_write_instant(self):
        # A deliberate backfill of an already-past date: the decision
        # instant and commence_time are both in the past relative to `now`,
        # which is expected and honest for REPLAY -- but recorded_utc must
        # still be the actual write instant, labelled `replay`, never
        # silently reusing decision_utc either.
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-08-31T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-08-31T20:00:00Z")
        now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

        report = self.run_slate(
            "2026-08-31", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            now=now)

        game = report.games[0]
        self.assertTrue(game.records)
        record = game.records[0]
        self.assertEqual(record.decision_utc, slate._iso(slate._parse_utc("2026-08-31T18:00:00Z")))
        self.assertEqual(record.recorded_utc, slate._iso(now))
        self.assertNotEqual(record.recorded_utc, record.decision_utc)
        self.assertEqual(record.record_provenance, RECORD_PROVENANCE_REPLAY)

    def test_default_now_reads_the_real_wall_clock(self):
        # No `now=` override: run_slate must read a REAL clock, not fall
        # back to the decision instant the way analyze() alone would.
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")

        before = datetime.now(timezone.utc)
        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),))
        after = datetime.now(timezone.utc)

        record = report.games[0].records[0]
        self.assertNotEqual(record.recorded_utc, record.decision_utc)
        recorded_dt = slate._parse_utc(record.recorded_utc)
        self.assertGreaterEqual(recorded_dt, before)
        self.assertLessEqual(recorded_dt, after)


class TestAlreadyCommencedGuard(SlateTestBase):
    """B2 (slice-review-2026-09-03): a live slate must refuse to stake a
    game whose first pitch has already passed at the ACTUAL write instant,
    even when the decision instant `t` it picked was honestly pre-game --
    exactly the flagship 2026-09-03 slate's bug (a run hours after the
    captures it used, for games that had since started)."""

    def test_live_mode_refuses_a_game_already_commenced_at_write_time(self):
        # The decision instant itself is honestly pre-game (18:00 < 18:30
        # commence) -- decision_time_for_game's own guard has nothing to
        # object to. But the run doesn't actually happen until 20:00, well
        # after that same 18:30 first pitch.
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T18:30:00Z")
        now = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            now=now)

        self.assertEqual(report.n_games_considered, 1)
        self.assertEqual(report.n_games_skipped, 1)
        self.assertEqual(report.n_new_decisions, 0)
        self.assertEqual(report.n_new_wagers, 0)
        game = report.games[0]
        self.assertIsNotNone(game.t)  # decision_time_for_game found a t
        self.assertIn("already commenced", game.skipped_reason)
        self.assertEqual(game.records, ())

    def test_exactly_at_commence_time_is_refused_too(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T18:30:00Z")
        now = datetime(2026, 9, 2, 18, 30, tzinfo=timezone.utc)

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            now=now)

        self.assertEqual(report.n_games_skipped, 1)
        self.assertIn("already commenced", report.games[0].skipped_reason)

    def test_live_mode_still_stakes_a_game_not_yet_commenced(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        now = datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc)

        report = self.run_slate(
            "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            now=now)

        self.assertEqual(report.n_games_skipped, 0)
        self.assertEqual(report.n_new_wagers, 1)
        self.assertEqual(report.games[0].records[0].record_provenance,
                         RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT)

    def test_replay_mode_is_exempt_from_the_already_commenced_guard(self):
        # A deliberate backfill of an already-past date: the game is long
        # over relative to `now` -- that is expected for replay, not a
        # reason to refuse.
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-08-31T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-08-31T18:30:00Z")
        now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

        report = self.run_slate(
            "2026-08-31", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            now=now)

        self.assertEqual(report.n_games_skipped, 0)
        self.assertEqual(report.n_new_decisions, 1)
        self.assertEqual(report.n_new_wagers, 1)
        self.assertEqual(report.games[0].records[0].record_provenance,
                         RECORD_PROVENANCE_REPLAY)

    def test_naive_now_is_rejected(self):
        _write_jsonl(self.l1_path, [
            *_two_book_rows(GAME_A, "2026-09-02T18:00:00Z"),
        ])
        self._commence_rows(GAME_A, "2026-09-02T20:00:00Z")
        with self.assertRaises(slate.SlateError):
            self.run_slate(
                "2026-09-02", systems=(glue_module.TrivialAlwaysHomeSystem(),),
                now=datetime(2026, 9, 2, 19, 0))
class TestHistoricalSlateResolvesBoard(SlateTestBase):
    """A 2023 archive-shaped slate: L1 rows carry
    `source="odds_api_historical_archive"` / grade D (the shape
    `src.board.l1_historical` actually writes), NOTHING is written to
    `self.commence_path` (the live `odds_snapshots.jsonl` stand-in --
    proving commence-time resolution does NOT depend on it here), and
    `game_pk_map` is populated the way `l1_historical.
    ensure_historical_event_map` populates the real `event_game_map.jsonl`
    (`schedule_commence_time` from `mlb_results.csv`, not a live schedule
    call). This is the exact mechanism that makes `engine slate --date
    DATE` resolvable for a historical date at all: without a
    `schedule_commence_time` entry, `commence_time_for` returns `None` for
    every archive event and `games_for_slate_date` would silently exclude
    every historical game from every slate, forever."""

    def _historical_game_pk_map(self, event_id, game_pk, schedule_commence_time):
        return {event_id: {
            "event_id": event_id, "game_pk": game_pk, "resolved": True,
            "ambiguous": False, "source": "mlb_results_csv",
            "schedule_commence_time": schedule_commence_time,
        }}

    def test_2023_archive_slate_builds_a_board_and_writes_a_decision(self):
        _write_jsonl(self.l1_path, [
            _historical_l1_row(GAME_A, "home", -150, "book_a", "2023-04-05T16:00:00Z"),
            _historical_l1_row(GAME_A, "away", 130, "book_a", "2023-04-05T16:00:00Z"),
            _historical_l1_row(GAME_A, "home", -150, "book_b", "2023-04-05T16:00:00Z"),
            _historical_l1_row(GAME_A, "away", 130, "book_b", "2023-04-05T16:00:00Z"),
        ])
        # self.commence_path is left untouched -- no live odds_snapshots.jsonl
        # entry exists for this event at all.
        self.assertFalse(self.commence_path.exists())
        game_pk_map = self._historical_game_pk_map(
            GAME_A, "660123", "2023-04-05T23:05:00Z")

        report = self.run_slate(
            "2023-04-05", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            game_pk_map=game_pk_map)

        self.assertEqual(report.n_games_considered, 1)
        self.assertEqual(report.n_games_skipped, 0)
        game = report.games[0]
        self.assertIsNone(game.skipped_reason)
        self.assertEqual(game.commence_time, "2023-04-05T23:05:00Z")
        self.assertEqual(report.n_new_decisions, 1)
        self.assertEqual(report.n_new_wagers, 1)
        self.assertTrue(any(r.price_american == -150 for r in game.records))

    def test_without_a_map_entry_the_historical_game_is_skipped_not_guessed(self):
        """The negative case, proving the map entry above is load-bearing:
        the exact same L1 rows, with NO game_pk_map entry at all, must be
        skipped (commence_time unknown) rather than silently priced off an
        assumed time."""
        _write_jsonl(self.l1_path, [
            _historical_l1_row(GAME_A, "home", -150, "book_a", "2023-04-05T16:00:00Z"),
            _historical_l1_row(GAME_A, "away", 130, "book_a", "2023-04-05T16:00:00Z"),
        ])
        report = self.run_slate(
            "2023-04-05", systems=(glue_module.TrivialAlwaysHomeSystem(),),
            game_pk_map={})
        self.assertEqual(report.n_games_considered, 0)
        self.assertEqual(report.n_new_decisions, 0)


if __name__ == "__main__":
    unittest.main()
