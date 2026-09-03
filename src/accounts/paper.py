"""Simulated daily paper bankroll accounts, one per system, side by side.

docs/ARCHITECTURE_BETTING_ENGINE.md §9.1 decision 9 / adopted amendment S13:
`FLAT_1U` only, Kelly registered but disabled. These accounts are the
"Account Ledger" half of the Two-Ledger Rule described in
docs/planning/design-factory-first.md §1.2 -- purely a REPORTING artifact.
They never feed `objective()` (src/ledger/records.py) and never decide
promotion (src/factory/fitness.py: `promotion_verdict` refuses exactly the
collapse a naive bankroll tournament would invite).

No real money ever moves here. Every stake, settlement and summary string
this module produces is explicitly labelled "PAPER" -- this is a simulated
account, never a live betting instrument (see the project's hard rule
against real-money bet-placement code).

STAKING
-------
`FLAT_1U` is the only enabled staking policy: every settled selection risks
exactly 1.0 unit. `KELLY_REGISTERED_DISABLED` documents that Kelly staking is
a *registered* concept (a name the system knows about) that is *disabled* --
calling `kelly_stake` raises rather than silently falling back to flat,
because a silent fallback would hide the fact that Kelly was ever invoked.

SETTLEMENT
-----------
Every bet settles through `src/board/settle.settle`, never through logic
duplicated here -- this module is a ledger and a P&L calculator, not a
second settlement authority.

LEDGER
-------
Every account keeps its own append-only hash-chained ledger
(`src/ledger/chain.HashChainLedger`), one file per account, so tampering
with one account's history is independently detectable and does not require
trusting a shared file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.board.settle import GameResult, PUSH, VOID, WIN, LOSS, settle
from src.ledger.chain import HashChainLedger
from src.paths import data_path

PAPER_LABEL = "PAPER"

FLAT_1U = 1.0

# Kelly is REGISTERED (named, known to the system) but DISABLED (never
# computed, never used to size a stake) -- S13, verbatim. This sentinel is
# what `kelly_stake` raises against, so the disablement is loud rather than
# silently falling back to FLAT_1U.
KELLY_REGISTERED_DISABLED = "kelly_registered_disabled"


class PaperAccountError(RuntimeError):
    """A paper account operation was attempted with malformed inputs."""


def kelly_stake(*_args, **_kwargs) -> float:
    """Kelly staking: registered by name, never computed. Always raises.

    S13: "FLAT_1U only, Kelly registered disabled." This function exists so
    the concept has a named seam in the codebase -- a future owner decision
    to enable Kelly has somewhere to land -- but it must never silently
    return a flat stake instead: that would hide a Kelly call as though it
    had been honored.
    """
    raise PaperAccountError(
        f"{KELLY_REGISTERED_DISABLED}: Kelly staking is registered but "
        "disabled by ARCHITECTURE_BETTING_ENGINE.md S13 -- FLAT_1U is the "
        "only enabled staking policy"
    )


def american_to_profit(stake_units: float, price_american: int) -> float:
    """Profit (excluding the returned stake) on a WIN at american odds."""
    if price_american == 0:
        raise PaperAccountError("price_american must never be 0")
    if price_american > 0:
        return stake_units * (price_american / 100.0)
    return stake_units * (100.0 / abs(price_american))


@dataclass(frozen=True, slots=True)
class PaperBet:
    """One simulated FLAT_1U selection queued for settlement.

    `stake_units` is always FLAT_1U here -- the field exists (rather than a
    bare constant) so a settled row's ledger entry is self-describing
    without a reader needing to import FLAT_1U to know what was risked.

    `game_pk`, `subject_id` and `subject_kind` are None for every game-level
    bet (h2h/spreads/totals/...) and are the only extra facts a PROP bet
    needs: `settle_bet` uses their presence (`subject_kind is not None`) to
    decide which of `src.board.settle.settle`'s two calling conventions
    applies -- never a second settlement authority, just routing.
    """

    bet_id: str
    system_id: str
    market_key: str
    selection_id: str
    side: str
    line: Optional[str]
    price_american: int
    settlement_rule: str
    stake_units: float = FLAT_1U
    game_pk: Optional[int] = None
    subject_id: object = None
    subject_kind: Optional[str] = None

    def __post_init__(self) -> None:
        if self.stake_units != FLAT_1U:
            raise PaperAccountError(
                f"stake_units={self.stake_units!r} != FLAT_1U={FLAT_1U!r} "
                "-- only FLAT_1U staking is enabled"
            )


@dataclass(frozen=True, slots=True)
class SettledBet:
    """The outcome of settling one PaperBet -- WIN/LOSS/PUSH/VOID plus P&L."""

    bet: PaperBet
    outcome: str
    profit_units: float

    def to_dict(self) -> dict:
        return {
            "label": PAPER_LABEL,
            "bet_id": self.bet.bet_id,
            "system_id": self.bet.system_id,
            "market_key": self.bet.market_key,
            "selection_id": self.bet.selection_id,
            "side": self.bet.side,
            "line": self.bet.line,
            "price_american": self.bet.price_american,
            "settlement_rule": self.bet.settlement_rule,
            "stake_units": self.bet.stake_units,
            "outcome": self.outcome,
            "profit_units": self.profit_units,
        }


def settle_bet(
    bet: PaperBet,
    result: Optional[GameResult] = None,
    *,
    box_row_resolver=None,
) -> SettledBet:
    """Settle one PaperBet via src.board.settle.settle -- never a second
    settlement authority.

    A game-level bet (`bet.subject_kind is None`) settles against `result`
    exactly as before. A PROP bet (`bet.subject_kind` set) has no
    GameResult to settle against at all -- it settles against a per-player
    box row, found by `box_row_resolver` (e.g.
    `src.pipeline.boxscores.box_row_resolver(rows)`) for
    `(bet.game_pk, bet.subject_id, bet.subject_kind)`. A resolver that finds
    no row is not an error: `settle()` passes `row=None` through to the prop
    rule, which grades VOID.
    """
    if bet.subject_kind is not None:
        selection = {"subject_id": bet.subject_id, "line": bet.line, "side": bet.side}
        outcome = settle(
            bet.settlement_rule,
            bet.side,
            selection=selection,
            game_pk=bet.game_pk,
            subject_kind=bet.subject_kind,
            box_row_resolver=box_row_resolver,
        )
    else:
        outcome = settle(bet.settlement_rule, bet.side, result, line=bet.line)
    if outcome == WIN:
        profit = american_to_profit(bet.stake_units, bet.price_american)
    elif outcome == LOSS:
        profit = -bet.stake_units
    elif outcome in (PUSH, VOID):
        profit = 0.0
    else:  # pragma: no cover -- settle() only returns the four above
        raise PaperAccountError(f"unrecognized settlement outcome {outcome!r}")
    return SettledBet(bet=bet, outcome=outcome, profit_units=profit)


@dataclass
class PaperAccount:
    """One simulated daily bankroll account for one system.

    `starting_bankroll` and `bankroll` are PAPER units, never real money.
    `daily_summaries` accumulates one row per `close_day` call; `peak` and
    `drawdown_max` are maintained incrementally so drawdown is always
    reported from the account's own running history, never recomputed by
    guessing at a start point.
    """

    system_id: str
    starting_bankroll: float = 1000.0
    bankroll: float = field(init=False)
    peak: float = field(init=False)
    drawdown_max: float = field(default=0.0, init=False)
    n_settled: int = field(default=0, init=False)
    n_wins: int = field(default=0, init=False)
    n_losses: int = field(default=0, init=False)
    n_pushes: int = field(default=0, init=False)
    n_voids: int = field(default=0, init=False)
    total_staked_units: float = field(default=0.0, init=False)
    total_profit_units: float = field(default=0.0, init=False)
    daily_summaries: list = field(default_factory=list, init=False)
    ledger: Optional[HashChainLedger] = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.starting_bankroll <= 0:
            raise PaperAccountError(
                f"starting_bankroll={self.starting_bankroll!r} must be > 0"
            )
        self.bankroll = self.starting_bankroll
        self.peak = self.starting_bankroll
        self.ledger = HashChainLedger(default_ledger_path(self.system_id))

    def _record_settlement(self, settled: SettledBet, day: str) -> None:
        # Voided/pushed bets never count toward stake exposure (nothing was
        # actually risked-and-lost or risked-and-won), only toward the
        # settled count and outcome tally.
        if settled.outcome not in (PUSH, VOID):
            self.total_staked_units += settled.bet.stake_units
        self.total_profit_units += settled.profit_units
        self.bankroll += settled.profit_units
        self.peak = max(self.peak, self.bankroll)
        current_drawdown = self.peak - self.bankroll
        self.drawdown_max = max(self.drawdown_max, current_drawdown)
        self.n_settled += 1
        if settled.outcome == WIN:
            self.n_wins += 1
        elif settled.outcome == LOSS:
            self.n_losses += 1
        elif settled.outcome == PUSH:
            self.n_pushes += 1
        elif settled.outcome == VOID:
            self.n_voids += 1
        row = settled.to_dict()
        row.update({
            "label": PAPER_LABEL,
            "day": day,
            "bankroll_after": self.bankroll,
            "drawdown_current": current_drawdown,
        })
        self.ledger.append(row)

    def settle_and_record(self, bet: PaperBet, result: Optional[GameResult],
                           day: str, *, box_row_resolver=None) -> SettledBet:
        """Settle one bet and append it to this account's ledger.

        `result` is a GameResult for game-level bets; pass None (with
        `box_row_resolver` set) for a PROP bet -- see `settle_bet`.
        """
        settled = settle_bet(bet, result, box_row_resolver=box_row_resolver)
        self._record_settlement(settled, day)
        return settled

    @property
    def roi_units(self) -> float:
        """Return on units staked -- 0.0 with nothing staked yet, never a
        divide-by-zero surprise."""
        if self.total_staked_units == 0:
            return 0.0
        return self.total_profit_units / self.total_staked_units

    def close_day(self, day: str) -> dict:
        """Snapshot this account's state as of the end of `day` and append
        it to `daily_summaries`. Idempotent to call once per day; calling it
        twice for the same day appends a second row (the reporting layer is
        expected to take the latest per day, matching cadence.py's
        append-only convention)."""
        summary = {
            "label": PAPER_LABEL,
            "system_id": self.system_id,
            "day": day,
            "bankroll": self.bankroll,
            "peak": self.peak,
            "drawdown_current": self.peak - self.bankroll,
            "drawdown_max": self.drawdown_max,
            "roi_units": self.roi_units,
            "n_settled": self.n_settled,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "n_pushes": self.n_pushes,
            "n_voids": self.n_voids,
            "total_staked_units": self.total_staked_units,
            "total_profit_units": self.total_profit_units,
        }
        self.daily_summaries.append(summary)
        return summary

    def report(self) -> str:
        """A human-readable, always-PAPER-labelled one-line summary."""
        return (
            f"[{PAPER_LABEL}] account={self.system_id} "
            f"bankroll={self.bankroll:.2f} roi_units={self.roi_units:.4f} "
            f"drawdown_max={self.drawdown_max:.2f} n_settled={self.n_settled}"
        )

    def verify_ledger(self):
        return self.ledger.verify()


def default_ledger_path(system_id: str):
    """One append-only ledger file per system, under data/paper_accounts/."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in system_id)
    return data_path("paper_accounts", f"{safe}.jsonl")


@dataclass
class PaperAccountBook:
    """Many PaperAccounts, one per system, running side by side.

    This is the "many accounts run side by side" requirement made concrete:
    a caller settles a bet against a named system's account without ever
    needing to reach into another system's state, and every summary printed
    from this book carries the PAPER label via each account's own methods.
    """

    accounts: dict = field(default_factory=dict)

    def account_for(self, system_id: str,
                     starting_bankroll: float = 1000.0) -> PaperAccount:
        if system_id not in self.accounts:
            self.accounts[system_id] = PaperAccount(
                system_id=system_id, starting_bankroll=starting_bankroll)
        return self.accounts[system_id]

    def settle_and_record(self, system_id: str, bet: PaperBet,
                           result: Optional[GameResult], day: str,
                           *, box_row_resolver=None) -> SettledBet:
        if bet.system_id != system_id:
            raise PaperAccountError(
                f"bet.system_id={bet.system_id!r} does not match the "
                f"account it was routed to ({system_id!r})"
            )
        account = self.account_for(system_id)
        return account.settle_and_record(
            bet, result, day, box_row_resolver=box_row_resolver)

    def close_day(self, day: str) -> list:
        return [account.close_day(day) for account in self.accounts.values()]

    def report(self) -> str:
        lines = [f"[{PAPER_LABEL}] {len(self.accounts)} account(s):"]
        for system_id in sorted(self.accounts):
            lines.append("  " + self.accounts[system_id].report())
        return "\n".join(lines)
