"""S6a -- settle: `python3 -m src.cli engine settle --date DATE`.

docs/CHECKPOINT_PHASE0_2026-09-03.md S6a: settle that date's paper wagers
(`evidence/paper_wagers_v2.jsonl`, written by `src.engine.slate.run_slate`)
from real results (`data/historical/mlb_results.csv`,
`data/processed/boxscores_*.jsonl`, the F5 results store --
`data/historical/first_five_results.jsonl` for the sealed 2023-24 seasons,
derived from the boxscore linescore's own per-inning rows for anything
newer, since first_five_results.jsonl is a frozen historical store that
does not grow) through `src.board.settle`, write ReviewRecords, update the
accounts, then call `build_fitness` + `promotion_verdict` and append a
Scorecard per system.

REFUSAL, NOT PARTIAL SETTLEMENT
---------------------------------
`run_settle` refuses (`SettleError`, no state written) the moment ANY game
with a wager on `date_str` has no confirmed final result -- never settles
the games it CAN confirm while silently skipping the rest. "Never settle
from a partial game" is read literally: a game absent from
`mlb_results.csv` is not yet final, full stop, regardless of whether some
OTHER game on the same date is.

IDEMPOTENCY
------------
A bet whose `bet_id` already appears in its system's own
`src.accounts.paper.PaperAccount` ledger is skipped -- re-running `engine
settle --date DATE` after it already ran settles nothing a second time.
"""

from __future__ import annotations

import csv
import glob
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from src.accounts.paper import PaperAccount, PaperBet, SettledBet
from src.board.settle import GameResult
from src.core.asof import game_pk_key
from src.factory.fitness import promotion_verdict
from src.factory.scorecard import build_scorecard, decision_key_for
from src.ledger.bridge import V2_LEDGER_PATH
from src.ledger.chain import HashChainLedger
from src.ledger.records import DecisionRecord, ReviewRecord, compute_thesis_outcome
from src.ledger.writer import append_review, append_scorecard
from src.paths import historical_path, processed_path
from src.engine.slate import PAPER_WAGERS_PATH

MLB_RESULTS_CSV = historical_path("mlb_results.csv")
FIRST_FIVE_RESULTS_PATH = historical_path("first_five_results.jsonl")
INFORMATION_EVENTS_PATH = processed_path("information_events.jsonl")
BOXSCORES_GLOB = str(processed_path("boxscores_*.jsonl"))


class SettleError(ValueError):
    """A settle run could not proceed honestly."""


def _read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ---------------------------------------------------------------------------
# Results resolution
# ---------------------------------------------------------------------------

def load_mlb_results(path=MLB_RESULTS_CSV) -> dict:
    """`{str(game_pk): {"home_runs", "away_runs", "date"}}` -- every row in
    the results CSV is a FINISHED game (this store is never written for a
    game that has not completed), so presence here IS the "results are
    available" signal `run_settle` refuses on the absence of."""
    p = Path(path)
    out: dict = {}
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            game_pk = row.get("game_pk")
            if not game_pk:
                continue
            try:
                home_runs = int(row["home_score"])
                away_runs = int(row["away_score"])
            except (KeyError, ValueError, TypeError):
                continue
            out[game_pk_key(game_pk)] = {
                "home_runs": home_runs, "away_runs": away_runs,
                "date": row.get("date"),
            }
    return out


def load_first_five_results(path=FIRST_FIVE_RESULTS_PATH) -> dict:
    """`{str(game_pk): (home_runs_through_5, away_runs_through_5)}` for
    every COMPLETE row of the sealed 2023-24 F5 results store."""
    out: dict = {}
    for row in _read_jsonl(path):
        if not row.get("complete"):
            continue
        game_pk = row.get("game_pk")
        if game_pk is None:
            continue
        home = row.get("home_runs")
        away = row.get("away_runs")
        if home is None or away is None:
            continue
        out[game_pk_key(game_pk)] = (home, away)
    return out


def load_boxscore_first_five(pattern: str = BOXSCORES_GLOB) -> dict:
    """`{str(game_pk): (home_runs_through_5, away_runs_through_5)}` derived
    by summing innings 1-5 of every `type=="linescore"` row across every
    `data/processed/boxscores_*.jsonl` store -- the forward (2026+) F5
    results source, since `first_five_results.jsonl` is a frozen historical
    store that stops at 2024 (`load_first_five_results`'s own docstring).
    `boxscores.ingest_date` only ever writes a linescore row for a FINAL
    game (its own docstring: "Append box + linescore rows for every FINAL
    game on one date"), so presence of a linescore row here is itself the
    completeness signal for this source.
    """
    out: dict = {}
    for path in sorted(glob.glob(pattern)):
        for row in _read_jsonl(path):
            if row.get("type") != "linescore":
                continue
            game_pk = row.get("game_pk")
            innings = row.get("innings") or []
            if game_pk is None or not innings:
                continue
            home = sum(i.get("home_runs", 0) or 0 for i in innings if i.get("num", 0) <= 5)
            away = sum(i.get("away_runs", 0) or 0 for i in innings if i.get("num", 0) <= 5)
            out[game_pk_key(game_pk)] = (home, away)
    return out


def build_game_result(game_pk: str, results: Mapping, f5_historical: Mapping,
                       f5_boxscore: Mapping) -> GameResult | None:
    """`GameResult` for `game_pk`, or `None` when the full-game result is
    not yet available (the refusal signal `run_settle` acts on). F5 runs
    are best-effort (`first_five_results.jsonl`, then the boxscore
    linescore) and default to `None` (VOID on settlement, per
    `src.board.settle`'s own contract) when neither source has them --
    F5 unavailability never blocks settling the full-game markets."""
    row = results.get(game_pk_key(game_pk))
    if row is None:
        return None
    f5 = (f5_historical.get(game_pk_key(game_pk))
          or f5_boxscore.get(game_pk_key(game_pk)))
    home5, away5 = f5 if f5 is not None else (None, None)
    return GameResult(
        home_runs=row["home_runs"], away_runs=row["away_runs"],
        home_runs_through_5=home5, away_runs_through_5=away5,
    )


# ---------------------------------------------------------------------------
# Wagers / decisions / reviews
# ---------------------------------------------------------------------------

def wagers_for_date(date_str: str, path=PAPER_WAGERS_PATH) -> tuple[dict, ...]:
    return tuple(row for row in HashChainLedger(path).read()
                 if row.get("date") == date_str)


def _record_from_row(cls, row: Mapping):
    import dataclasses
    valid = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in row.items() if k in valid})


def load_decisions(path=None) -> tuple[DecisionRecord, ...]:
    path = str(path or V2_LEDGER_PATH)
    out = []
    for row in HashChainLedger(path).read():
        if row.get("kind") == "genesis" or "decision_utc" not in row:
            continue
        out.append(_record_from_row(DecisionRecord, row))
    return tuple(out)


def load_reviews(path=None) -> tuple[ReviewRecord, ...]:
    from src.ledger.writer import REVIEW_LEDGER_PATH
    path = str(path or REVIEW_LEDGER_PATH)
    out = []
    for row in HashChainLedger(path).read():
        if "decision_key" not in row:
            continue
        out.append(_record_from_row(
            ReviewRecord, dict(row, decision_key=tuple(row["decision_key"]))))
    return tuple(out)


def _account_ledger_path(system_id: str, account_ledger_path_fn=None):
    from src.accounts.paper import default_ledger_path
    fn = account_ledger_path_fn or default_ledger_path
    return fn(system_id)


def already_settled_bet_ids(system_id: str, account_ledger_path_fn=None) -> set:
    out = set()
    path = _account_ledger_path(system_id, account_ledger_path_fn)
    for row in HashChainLedger(path).read():
        bid = row.get("bet_id")
        if bid:
            out.add(bid)
    return out


def late_information_for(game_pk, decision_utc: str, settle_utc: str,
                          path=INFORMATION_EVENTS_PATH) -> tuple:
    """Every real `InformationEvent` for `game_pk` whose `observed_utc`
    falls strictly inside `(decision_utc, settle_utc]` -- information that
    arrived AFTER the decision was frozen, which is exactly what a "second
    verdict" is computed against (ReviewRecord's own `late_information`
    field)."""
    canonical_game_pk = game_pk_key(game_pk)
    if canonical_game_pk is None:
        return ()
    out = []
    for row in _read_jsonl(path):
        if game_pk_key(row.get("game_pk")) != canonical_game_pk:
            continue
        observed = row.get("observed_utc") or row.get("known_at")
        if not observed:
            continue
        if decision_utc < observed <= settle_utc:
            out.append({"kind": row.get("kind"), "observed_utc": observed,
                        "detail": row.get("detail") or row.get("description")})
    return tuple(sorted(out, key=lambda e: e["observed_utc"]))


def build_review_for(decision: DecisionRecord | None, settled: SettledBet,
                      settle_utc: str,
                      information_events_path=INFORMATION_EVENTS_PATH) -> ReviewRecord:
    """One `ReviewRecord` for a settled bet. `mechanism_checks` stays empty
    (this vertical slice records no per-thesis mechanism check yet), which
    `compute_thesis_outcome` reads honestly as UNTESTED rather than a
    fabricated CONFIRMED/REFUTED. `late_information` is the REAL signal for
    "an InformationEvent arrived after the frozen decision" -- when
    non-empty, the review names a distinct verdict path: `system_action`
    becomes "watch" rather than "none", flagging that this settlement's
    thesis was evaluated on a board that later information moved past.
    """
    decision_key = (decision_key_for(decision) if decision is not None
                    else (settled.bet.selection_id, settled.bet.market_key,
                          settled.bet.selection_id, settle_utc))
    late_info = ()
    if decision is not None:
        late_info = late_information_for(
            decision.game_pk, decision.decision_utc, settle_utc,
            path=information_events_path)
    mechanism_checks: tuple = ()
    thesis_outcome = compute_thesis_outcome(mechanism_checks, settled.outcome)
    return ReviewRecord(
        decision_key=decision_key, review_utc=settle_utc,
        settled=settled.outcome, thesis_outcome=thesis_outcome,
        mechanism_checks=mechanism_checks, market_path={},
        late_information=late_info, missed_information=(),
        lineup_delta={}, bullpen_delta={}, counterargument_realized=(),
        variance_flag=False,
        system_action=("watch" if late_info else "none"),
        new_hypothesis=None,
    )


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SystemSettlement:
    system_id: str
    settled: tuple  # tuple[SettledBet, ...] newly settled this run
    duplicate: int
    bankroll: float
    roi_units: float
    drawdown_max: float
    scorecard_verdict: object  # PromotionVerdict
    scorecard_absent: tuple


@dataclass(frozen=True, slots=True)
class SettleReport:
    date: str
    n_wagers_considered: int
    n_games: int
    systems: tuple  # tuple[SystemSettlement, ...]


def run_settle(date_str: str, *, wagers_path=None, results_path=MLB_RESULTS_CSV,
               f5_historical_path=FIRST_FIVE_RESULTS_PATH,
               boxscores_glob: str = BOXSCORES_GLOB,
               information_events_path=INFORMATION_EVENTS_PATH,
               decisions_path=None, review_path=None, scorecard_path=None,
               account_ledger_path_fn=None,
               now: datetime | None = None) -> SettleReport:
    wagers = wagers_for_date(date_str, path=str(wagers_path or PAPER_WAGERS_PATH))
    if not wagers:
        raise SettleError(
            f"no paper wagers recorded for {date_str} in "
            f"{wagers_path or PAPER_WAGERS_PATH} -- run `engine slate "
            f"--date {date_str}` first")

    results = load_mlb_results(results_path)
    game_pks = sorted({game_pk_key(w.get("game_pk")) for w in wagers
                       if w.get("game_pk") is not None})
    missing = [pk for pk in game_pks if pk not in results]
    unresolved_events = sorted({w.get("event_id") for w in wagers if w.get("game_pk") is None})
    if missing or unresolved_events:
        detail = []
        if missing:
            detail.append(f"game_pk(s) with no result in {results_path}: {missing}")
        if unresolved_events:
            detail.append(f"wager(s) with no resolved game_pk at all: "
                          f"{unresolved_events}")
        raise SettleError(
            f"refusing to settle {date_str}: results are not yet available "
            f"for every wagered game -- {'; '.join(detail)}. Never settling "
            "from a partial slate.")

    f5_historical = load_first_five_results(f5_historical_path)
    f5_boxscore = load_boxscore_first_five(boxscores_glob)

    settle_utc = _iso(now or datetime.now(timezone.utc))
    decisions = load_decisions(decisions_path)
    decisions_by_key = {(d.event_id, d.system_id, d.market_key, d.selection_id,
                        d.decision_utc): d for d in decisions}

    by_system: dict = {}
    for w in wagers:
        by_system.setdefault(w["system_id"], []).append(w)

    system_settlements = []
    for system_id, rows in sorted(by_system.items()):
        already = already_settled_bet_ids(system_id, account_ledger_path_fn)
        # `PaperAccount.__init__` opens THIS system's real ledger file (its
        # own hash chain, `default_ledger_path`) but its in-memory running
        # totals (bankroll/roi/drawdown_max) start fresh at construction --
        # replay every row the ledger already holds (WITHOUT re-appending
        # any of them) before settling anything new, so a second `engine
        # settle` run on a LATER date reports the account's true cumulative
        # state rather than resetting to a fresh $1000 starting bankroll.
        # `account_ledger_path_fn`, when given, REPLACES the account's
        # ledger with one at a caller-chosen path (tests only -- production
        # always uses the real per-system store).
        account = PaperAccount(system_id=system_id)
        if account_ledger_path_fn is not None:
            account.ledger = HashChainLedger(account_ledger_path_fn(system_id))
        _replay_prior_settlements(account)

        newly_settled = []
        n_dupe = 0
        for w in rows:
            if w["bet_id"] in already:
                n_dupe += 1
                continue
            game_pk = w.get("game_pk")
            result = build_game_result(game_pk, results, f5_historical, f5_boxscore)
            if result is None:
                # Should be unreachable given the pre-flight check above,
                # but never fabricate a result rather than trust that.
                raise SettleError(
                    f"internal: no result for game_pk={game_pk!r} on a "
                    f"wager that passed the pre-flight availability check")
            bet = PaperBet(
                bet_id=w["bet_id"], system_id=w["system_id"],
                market_key=w["market_key"], selection_id=w["selection_id"],
                side=w["side"], line=w.get("line"),
                price_american=w["price_american"],
                settlement_rule=w["settlement_rule"],
                stake_units=w.get("stake_units", 1.0), game_pk=game_pk,
            )
            settled = account.settle_and_record(bet, result, date_str)
            newly_settled.append(settled)

            decision_key_5 = (w.get("event_id"), w["system_id"], w["market_key"],
                              w["selection_id"], w.get("decision_utc"))
            decision = decisions_by_key.get(decision_key_5)
            review = build_review_for(decision, settled, settle_utc,
                                      information_events_path=information_events_path)
            if review_path is not None:
                append_review(review, path=review_path)
            else:
                append_review(review)

        # -- Scorecard: real Fitness assembled from THIS system's whole
        # history (bets from its own ledger replayed end to end, decisions
        # from decisions_v2.jsonl, reviews from the review chain), never
        # just today's slice -- a Scorecard reports a system's forward
        # track record, not a single day. Appended only when this run
        # actually settled something new -- idempotency covers the
        # Scorecard chain too, not only decisions/wagers: a re-run that
        # settled nothing new writes no new (system_id, window) row.
        all_bets = _reconstruct_settled_bets(system_id, account_ledger_path_fn)
        system_decisions = tuple(d for d in decisions if d.system_id == system_id)
        all_reviews = load_reviews(review_path)
        scorecard, absent = build_scorecard(
            system_id=system_id, world="real", window=date_str,
            point_class="LATE_BOARD", market_key="h2h",
            bets=all_bets, decisions=system_decisions, reviews=all_reviews,
        )
        fitness = _fitness_for(system_id, all_bets, system_decisions, all_reviews)
        verdict = promotion_verdict(fitness)
        if newly_settled:
            if scorecard_path is not None:
                append_scorecard(scorecard, path=scorecard_path)
            else:
                append_scorecard(scorecard)

        system_settlements.append(SystemSettlement(
            system_id=system_id, settled=tuple(newly_settled),
            duplicate=n_dupe, bankroll=account.bankroll,
            roi_units=account.roi_units, drawdown_max=account.drawdown_max,
            scorecard_verdict=verdict, scorecard_absent=absent,
        ))

    return SettleReport(date=date_str, n_wagers_considered=len(wagers),
                        n_games=len(game_pks), systems=tuple(system_settlements))


def _replay_prior_settlements(account: PaperAccount) -> None:
    """Fold every row already on `account`'s own hash-chained ledger into
    its in-memory running totals, WITHOUT appending any of them again --
    `PaperAccount._record_settlement` both updates the totals AND appends
    to the ledger in one call, so this reimplements only the totals half
    (mirrors `src.report.eod.account_day_from_ledger_rows`'s own replay,
    applied to the live account object here instead of a read-only
    snapshot)."""
    from src.board.settle import PUSH, VOID, WIN, LOSS

    for row in HashChainLedger(account.ledger.path).read():
        outcome = row["outcome"]
        stake = row.get("stake_units", 1.0)
        profit = row["profit_units"]
        if outcome not in (PUSH, VOID):
            account.total_staked_units += stake
        account.total_profit_units += profit
        account.bankroll += profit
        account.peak = max(account.peak, account.bankroll)
        account.drawdown_max = max(account.drawdown_max,
                                   account.peak - account.bankroll)
        account.n_settled += 1
        if outcome == WIN:
            account.n_wins += 1
        elif outcome == LOSS:
            account.n_losses += 1
        elif outcome == PUSH:
            account.n_pushes += 1
        elif outcome == VOID:
            account.n_voids += 1


def _fitness_for(system_id, bets, decisions, reviews):
    from src.factory.scorecard import build_fitness
    return build_fitness(system_id, bets, decisions, reviews).fitness


def _reconstruct_settled_bets(system_id: str, account_ledger_path_fn=None) -> tuple:
    """Every `SettledBet` this system's OWN hash-chained ledger has ever
    recorded, in append order -- the source of truth `build_fitness`/
    `build_scorecard` replay, independent of what this particular
    `run_settle` call newly settled."""
    out = []
    path = _account_ledger_path(system_id, account_ledger_path_fn)
    for row in HashChainLedger(path).read():
        bet = PaperBet(
            bet_id=row["bet_id"], system_id=row["system_id"],
            market_key=row["market_key"], selection_id=row["selection_id"],
            side=row["side"], line=row.get("line"),
            price_american=row["price_american"],
            settlement_rule=row["settlement_rule"],
            stake_units=row.get("stake_units", 1.0),
        )
        out.append(SettledBet(bet=bet, outcome=row["outcome"],
                              profit_units=row["profit_units"]))
    return tuple(out)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
