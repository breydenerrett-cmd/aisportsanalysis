"""Tests for src.accounts.paper: simulated PAPER bankroll accounts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.accounts import paper
from src.board.settle import GameResult
from src.accounts.paper import (
    FLAT_1U,
    PAPER_LABEL,
    PaperAccount,
    PaperAccountBook,
    PaperAccountError,
    PaperBet,
    american_to_profit,
    kelly_stake,
    settle_bet,
)


def _bet(**overrides) -> PaperBet:
    base = dict(bet_id="b1", system_id="sys-1", market_key="h2h",
                selection_id="home", side="home", line=None,
                price_american=-110, settlement_rule="h2h")
    base.update(overrides)
    return PaperBet(**base)


class KellyDisabledTests(unittest.TestCase):
    def test_kelly_always_raises(self):
        with self.assertRaises(PaperAccountError):
            kelly_stake()

    def test_kelly_error_names_the_registered_disabled_sentinel(self):
        with self.assertRaises(PaperAccountError) as ctx:
            kelly_stake(bankroll=1000, edge=0.05)
        self.assertIn(paper.KELLY_REGISTERED_DISABLED, str(ctx.exception))


class Flat1UTests(unittest.TestCase):
    def test_bet_must_be_flat_1u(self):
        with self.assertRaises(PaperAccountError):
            PaperBet(bet_id="b1", system_id="sys-1", market_key="h2h",
                      selection_id="home", side="home", line=None,
                      price_american=-110, settlement_rule="h2h",
                      stake_units=2.0)

    def test_default_stake_is_flat_1u(self):
        bet = _bet()
        self.assertEqual(bet.stake_units, FLAT_1U)


class AmericanToProfitTests(unittest.TestCase):
    def test_positive_price(self):
        self.assertAlmostEqual(american_to_profit(1.0, 150), 1.5)

    def test_negative_price(self):
        self.assertAlmostEqual(american_to_profit(1.0, -110),
                                100 / 110)

    def test_zero_price_refused(self):
        with self.assertRaises(PaperAccountError):
            american_to_profit(1.0, 0)


class SettleBetTests(unittest.TestCase):
    def test_win_h2h_credits_profit(self):
        bet = _bet(price_american=-110)
        result = GameResult(home_runs=5, away_runs=2)
        settled = settle_bet(bet, result)
        self.assertEqual(settled.outcome, "win")
        self.assertAlmostEqual(settled.profit_units, 100 / 110)

    def test_loss_h2h_debits_stake(self):
        bet = _bet(side="away", price_american=-110)
        result = GameResult(home_runs=5, away_runs=2)
        settled = settle_bet(bet, result)
        self.assertEqual(settled.outcome, "loss")
        self.assertAlmostEqual(settled.profit_units, -1.0)

    def test_push_spreads_zero_profit(self):
        bet = _bet(market_key="spreads", selection_id="home", side="home",
                    line="-3", price_american=-110,
                    settlement_rule="spreads")
        result = GameResult(home_runs=5, away_runs=2)
        settled = settle_bet(bet, result)
        self.assertEqual(settled.outcome, "push")
        self.assertEqual(settled.profit_units, 0.0)

    def test_void_h2h_tie_zero_profit(self):
        bet = _bet()
        result = GameResult(home_runs=3, away_runs=3)
        settled = settle_bet(bet, result)
        self.assertEqual(settled.outcome, "void")
        self.assertEqual(settled.profit_units, 0.0)

    def test_dict_labelled_paper(self):
        bet = _bet()
        result = GameResult(home_runs=5, away_runs=2)
        settled = settle_bet(bet, result)
        self.assertEqual(settled.to_dict()["label"], PAPER_LABEL)


class PaperAccountTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._ledger_path = Path(self._tmpdir.name) / "sys-1.jsonl"
        patcher = mock.patch.object(
            paper, "default_ledger_path", return_value=self._ledger_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmpdir.cleanup)

    def test_starting_bankroll_must_be_positive(self):
        with self.assertRaises(PaperAccountError):
            PaperAccount(system_id="sys-1", starting_bankroll=0)

    def test_win_increases_bankroll_and_peak(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        bet = _bet(price_american=100)
        result = GameResult(home_runs=5, away_runs=2)
        account.settle_and_record(bet, result, day="2026-04-01")
        self.assertAlmostEqual(account.bankroll, 1001.0)
        self.assertAlmostEqual(account.peak, 1001.0)
        self.assertEqual(account.drawdown_max, 0.0)

    def test_drawdown_tracks_peak_to_trough(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        win_bet = _bet(bet_id="w1", price_american=100)
        loss_bet = _bet(bet_id="l1", side="away", price_american=100)
        win_result = GameResult(home_runs=5, away_runs=2)  # home wins
        account.settle_and_record(win_bet, win_result, day="2026-04-01")
        self.assertAlmostEqual(account.bankroll, 1001.0)
        # away side now loses against the same result
        account.settle_and_record(loss_bet, win_result, day="2026-04-02")
        self.assertAlmostEqual(account.bankroll, 1000.0)
        self.assertAlmostEqual(account.drawdown_max, 1.0)

    def test_push_and_void_do_not_count_toward_staked_units(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        tie_bet = _bet(bet_id="v1")
        tie_result = GameResult(home_runs=3, away_runs=3)
        account.settle_and_record(tie_bet, tie_result, day="2026-04-01")
        self.assertEqual(account.total_staked_units, 0.0)
        self.assertEqual(account.roi_units, 0.0)

    def test_roi_units_computed_from_staked_and_profit(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        bet = _bet(price_american=100)
        result = GameResult(home_runs=5, away_runs=2)
        account.settle_and_record(bet, result, day="2026-04-01")
        self.assertAlmostEqual(account.roi_units, 1.0)  # +1u profit / 1u staked

    def test_close_day_snapshot_labelled_paper(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        summary = account.close_day("2026-04-01")
        self.assertEqual(summary["label"], PAPER_LABEL)
        self.assertEqual(len(account.daily_summaries), 1)

    def test_report_string_labelled_paper(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        self.assertIn(f"[{PAPER_LABEL}]", account.report())

    def test_ledger_appends_and_verifies(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        bet = _bet(price_american=100)
        result = GameResult(home_runs=5, away_runs=2)
        account.settle_and_record(bet, result, day="2026-04-01")
        verify = account.verify_ledger()
        self.assertTrue(verify.ok)
        self.assertEqual(verify.rows_checked, 1)

    def test_tampered_ledger_fails_verification(self):
        account = PaperAccount(system_id="sys-1", starting_bankroll=1000.0)
        bet = _bet(price_american=100)
        result = GameResult(home_runs=5, away_runs=2)
        account.settle_and_record(bet, result, day="2026-04-01")
        text = self._ledger_path.read_text(encoding="utf-8")
        tampered = text.replace('"bankroll_after": 1001.0',
                                 '"bankroll_after": 5000.0')
        self.assertNotEqual(text, tampered)
        self._ledger_path.write_text(tampered, encoding="utf-8")
        verify = account.verify_ledger()
        self.assertFalse(verify.ok)


class PaperAccountBookTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(
            paper, "default_ledger_path",
            side_effect=lambda system_id: Path(self._tmpdir.name) / f"{system_id}.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmpdir.cleanup)

    def test_many_accounts_run_side_by_side_independently(self):
        book = PaperAccountBook()
        result = GameResult(home_runs=5, away_runs=2)
        bet_a = _bet(system_id="sys-a", bet_id="a1", price_american=100)
        bet_b = _bet(system_id="sys-b", bet_id="b1", side="away",
                      price_american=100)
        book.settle_and_record("sys-a", bet_a, result, day="2026-04-01")
        book.settle_and_record("sys-b", bet_b, result, day="2026-04-01")
        account_a = book.account_for("sys-a")
        account_b = book.account_for("sys-b")
        self.assertAlmostEqual(account_a.bankroll, 1001.0)
        self.assertAlmostEqual(account_b.bankroll, 999.0)

    def test_mismatched_system_id_refused(self):
        book = PaperAccountBook()
        result = GameResult(home_runs=5, away_runs=2)
        bet = _bet(system_id="sys-a")
        with self.assertRaises(PaperAccountError):
            book.settle_and_record("sys-b", bet, result, day="2026-04-01")

    def test_report_lists_every_account_labelled_paper(self):
        book = PaperAccountBook()
        book.account_for("sys-a")
        book.account_for("sys-b")
        report = book.report()
        self.assertIn(PAPER_LABEL, report)
        self.assertIn("sys-a", report)
        self.assertIn("sys-b", report)

    def test_close_day_snapshots_every_account(self):
        book = PaperAccountBook()
        book.account_for("sys-a")
        book.account_for("sys-b")
        summaries = book.close_day("2026-04-01")
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(s["label"] == PAPER_LABEL for s in summaries))


class PropSettlementEndToEndTests(unittest.TestCase):
    """Bug #2 (checkpoint 2026-09-03 review): every prop PaperBet used to
    raise TypeError the moment settle_bet reached src.board.settle.settle.
    This settles a real batter-prop PaperBet end to end through
    PaperAccount.settle_and_record -- the exact path a real caller uses --
    against a REAL row from data/processed/boxscores_2026.jsonl, and shows
    all four outcomes (win/loss/push/void).

    HONESTY NOTE on the selection: data/processed/batter_props.jsonl (the
    real captured batter-prop store) is entirely dated 2026-09-03, while
    data/processed/boxscores_2026.jsonl only covers 2026-08-30..09-01 --
    verified below to have zero overlapping game_date -- so there is no
    single real prop row whose game has a real box score yet. Per the task
    instructions this test therefore builds the PaperBet selections itself
    (a fixture: subject_id/line/side picked by this test) but settles them
    against REAL rows read from the real boxscore store on disk -- the box
    line, the game_pk, the player_id and the stat values are all real MLB
    data, only the (line, side) pairing on top of them is synthesized here
    to exercise all four outcomes deliberately.
    """

    STORE_PATH = "data/processed/boxscores_2026.jsonl"
    BATTER_PROPS_PATH = "data/processed/batter_props.jsonl"

    @classmethod
    def setUpClass(cls):
        from src.pipeline import boxscores

        cls.rows = boxscores.read(cls.STORE_PATH)
        assert cls.rows, (
            f"{cls.STORE_PATH} is empty on disk -- this test needs the real "
            "store checked into the repo, it does not fabricate box lines"
        )
        # staticmethod() wrapping matters here: a plain function assigned as
        # a class attribute is bound as a method on instance access (self
        # gets injected as its first positional argument), which is exactly
        # wrong for a resolver whose contract is keyword-only
        # (game_pk=/subject_id=/subject_kind=) -- staticmethod keeps it a
        # plain callable through `self.resolver`.
        cls.resolver = staticmethod(boxscores.box_row_resolver(cls.rows))

        # The no-overlap claim above, checked against the actual files
        # rather than just asserted in prose.
        import json
        with open(cls.BATTER_PROPS_PATH, encoding="utf-8") as fh:
            prop_dates = {json.loads(line)["game_date"] for line in fh if line.strip()}
        box_dates = {r["date"] for r in cls.rows}
        assert not (prop_dates & box_dates), (
            "batter_props.jsonl now overlaps boxscores_2026.jsonl by date -- "
            "this test's honesty note is stale, rewrite it to use the real "
            "overlapping row instead of a fixture selection"
        )

        # Real rows, real game_pk, real player_id, real stat values --
        # pulled straight out of the 2026-08-30 slate (game_pk 822688).
        cls.game_pk = 822688
        cls.win_row = next(  # Agustín Ramírez, h=2 that night
            r for r in cls.rows
            if r["type"] == "batter" and r["player_id"] == 682663
            and r["game_pk"] == cls.game_pk
        )
        cls.loss_row = next(  # Griffin Conine, h=0 that night
            r for r in cls.rows
            if r["type"] == "batter" and r["player_id"] == 665052
            and r["game_pk"] == cls.game_pk
        )
        cls.push_row = next(  # Esteury Ruiz, h=1 that night
            r for r in cls.rows
            if r["type"] == "batter" and r["player_id"] == 665923
            and r["game_pk"] == cls.game_pk
        )
        assert cls.win_row["h"] == 2 and cls.loss_row["h"] == 0 and cls.push_row["h"] == 1

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(
            paper, "default_ledger_path",
            side_effect=lambda system_id: Path(self._tmpdir.name) / f"{system_id}.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmpdir.cleanup)

    def _prop_bet(self, bet_id, subject_id, line):
        return PaperBet(
            bet_id=bet_id, system_id="sys-props", market_key="batter_hits",
            selection_id=f"batter_hits:{subject_id}:{line}", side="over",
            line=line, price_american=-115, settlement_rule="batter_hits",
            game_pk=self.game_pk, subject_id=subject_id, subject_kind="batter",
        )

    def test_settles_win_loss_push_and_void_through_the_dispatcher(self):
        account = PaperAccount(system_id="sys-props", starting_bankroll=1000.0)

        win_settled = account.settle_and_record(
            self._prop_bet("p-win", 682663, "1.5"),  # h=2 > 1.5
            None, day="2026-08-31", box_row_resolver=self.resolver,
        )
        loss_settled = account.settle_and_record(
            self._prop_bet("p-loss", 665052, "0.5"),  # h=0 < 0.5
            None, day="2026-08-31", box_row_resolver=self.resolver,
        )
        push_settled = account.settle_and_record(
            self._prop_bet("p-push", 665923, "1"),  # h=1 == 1
            None, day="2026-08-31", box_row_resolver=self.resolver,
        )
        void_settled = account.settle_and_record(
            # No box row anywhere for this player/game -- resolver returns
            # None; this must VOID, never raise.
            self._prop_bet("p-void", 999999999, "1.5"),
            None, day="2026-08-31", box_row_resolver=self.resolver,
        )

        self.assertEqual(win_settled.outcome, "win")
        self.assertGreater(win_settled.profit_units, 0.0)
        self.assertEqual(loss_settled.outcome, "loss")
        self.assertEqual(loss_settled.profit_units, -FLAT_1U)
        self.assertEqual(push_settled.outcome, "push")
        self.assertEqual(push_settled.profit_units, 0.0)
        self.assertEqual(void_settled.outcome, "void")
        self.assertEqual(void_settled.profit_units, 0.0)

        # PUSH and VOID never count toward exposure; only win/loss stake.
        self.assertAlmostEqual(account.total_staked_units, 2.0)
        self.assertEqual(account.n_wins, 1)
        self.assertEqual(account.n_losses, 1)
        self.assertEqual(account.n_pushes, 1)
        self.assertEqual(account.n_voids, 1)

        verify = account.verify_ledger()
        self.assertTrue(verify.ok)
        self.assertEqual(verify.rows_checked, 4)


if __name__ == "__main__":
    unittest.main()
