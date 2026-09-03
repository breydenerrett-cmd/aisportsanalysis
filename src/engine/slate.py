"""S5 -- the slate runner: `python3 -m src.cli engine slate --date DATE`.

docs/CHECKPOINT_PHASE0_2026-09-03.md S5: resolve one date's slate, and for
every game with captured prices in the four supported markets (h2h,
spreads, totals, h2h_1st_5_innings -- SCOPE_MARKETS below, no other market
family is ever considered here), build board+snapshot at the decision time
(the latest L1 capture strictly before first pitch, honouring the existing
first-pitch guard -- `src.engine.glue.build_board`'s `commence_time` guard),
run `analyze()` with the registered systems
(`src.engine.adapters.evolab_system.REGISTERED_SYSTEMS`) and
`src.engine.adversaries.DEFAULT_ADVERSARIES`, and write FROZEN
DecisionRecords to the hash-chained ledger (`evidence/decisions_v2.jsonl`)
before any outcome exists. Then place FLAT_1U paper wagers into one
`PaperAccount` per system, every output string labelled PAPER.

THE SELECTION RULE
-------------------
`analyze()`'s PROJECT phase may match ONE proposal against MULTIPLE
selections on the board (a totals proposal naming no explicit line matches
every captured total line; ENGINE_CONTRACT.md section 4). RANK already puts
every system's surviving candidates for one game in one deterministic total
order (`(-edge_bps, selection_id, system_id)`), so `SELECTION_RULE` below is
the one additional, PRE-REGISTERED rule this module needs: which of a
system's own ranked `verdict=="play"` records for one game actually becomes
a paper wager. It reads nothing from any account (bankroll, drawdown, prior
P&L) and nothing from any outcome (a result, a close price) -- both would
make "how a bet gets chosen" depend on facts that must never influence a
FROZEN, pre-outcome decision.

IDEMPOTENCY
------------
Re-running the same date writes zero duplicate decisions and zero duplicate
wagers: a decision's identity is `(event_id, system_id, market_key,
selection_id, decision_utc)`, checked against every row already in
`evidence/decisions_v2.jsonl` before appending; a wager's identity is a
`bet_id` derived deterministically from that same tuple (`bet_id_for`),
checked against every row already in `evidence/paper_wagers_v2.jsonl`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from src.accounts.paper import FLAT_1U, PAPER_LABEL, PaperBet
from src.board import gamekey as gamekey_module
from src.board.ids import MARKET_CATALOGUE
from src.engine import glue as glue_module
from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS
from src.engine.adversaries import DEFAULT_ADVERSARIES
from src.engine.analyze import DEFAULT_CONFIG, EngineConfig, analyze
from src.ledger.bridge import V2_LEDGER_PATH
from src.ledger.chain import HashChainLedger
from src.ledger.records import DecisionRecord
from src.ledger.writer import append_decision
from src.paths import evidence_path

# FOUR markets only -- the task's scope boundary, enforced here rather than
# assumed from whatever a system happens to propose or a board happens to
# carry.
SCOPE_MARKETS: tuple = ("h2h", "spreads", "totals", "h2h_1st_5_innings")

PAPER_WAGERS_PATH = evidence_path("paper_wagers_v2.jsonl")

DEFAULT_PRE_GAME_MARGIN_MINUTES = glue_module.DEFAULT_PRE_GAME_MARGIN_MINUTES

# --- The pre-registered selection rule -------------------------------------
SELECTION_RULE = "TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1"
SELECTION_RULE_RATIONALE = (
    "For each (system, game), analyze()'s own RANK phase already orders "
    "every surviving candidate deterministically by (-edge_bps, "
    "selection_id, system_id) -- a total order with no randomness and no "
    "dependency on bankroll or a known outcome. This slate runner stakes "
    "ONLY the single highest-ranked verdict=='play' DecisionRecord for each "
    "(system, game) pair, never every board line a proposal happened to "
    "match (PROJECT may match one proposal against several lines of the "
    "same market/side). Staking every match would risk multiple correlated "
    "tickets on one system's single directional belief; staking the top of "
    "an already-deterministic order stakes exactly one, chosen by a rule "
    "fixed before any board was ever read, not by a per-run judgment call."
)


class SlateError(ValueError):
    """A slate run could not proceed honestly."""


def _parse_utc(value: str) -> datetime:
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def decision_key(record: DecisionRecord) -> tuple:
    """The identity tuple a decision is deduplicated on. Mirrors
    `src.factory.scorecard.decision_key_for`'s own four fields exactly, plus
    `system_id` -- two systems deciding the same (event, market, selection,
    instant) are two distinct decisions, never collapsed into one."""
    return (record.event_id, record.system_id, record.market_key,
            record.selection_id, record.decision_utc)


def bet_id_for(date_str: str, record: DecisionRecord) -> str:
    """A deterministic bet id from the decision's own identity -- re-running
    the same date derives the SAME id for the SAME staked decision, which is
    what makes wager placement idempotent without a separate "already
    placed" flag anywhere."""
    parts = (date_str, record.system_id, record.event_id,
            record.market_key or "", record.selection_id or "",
            record.decision_utc)
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class GameOutcome:
    """What the slate runner did for one game -- surfaced so a caller (the
    CLI) can report a skip honestly instead of a silent shrink."""

    game_key: str
    game_pk: str | None
    t: str | None
    commence_time: str | None
    skipped_reason: str | None
    records: tuple  # tuple[DecisionRecord, ...] -- selection_rule/stake applied
    new_decisions: int
    duplicate_decisions: int
    staked_bet_ids: tuple  # bet_ids newly placed this run
    duplicate_wagers: int


@dataclass(frozen=True, slots=True)
class SlateReport:
    date: str
    dry_run: bool
    systems: tuple  # system ids run
    games: tuple  # tuple[GameOutcome, ...]

    @property
    def n_games_considered(self) -> int:
        return len(self.games)

    @property
    def n_games_skipped(self) -> int:
        return sum(1 for g in self.games if g.skipped_reason is not None)

    @property
    def n_new_decisions(self) -> int:
        return sum(g.new_decisions for g in self.games)

    @property
    def n_duplicate_decisions(self) -> int:
        return sum(g.duplicate_decisions for g in self.games)

    @property
    def n_new_wagers(self) -> int:
        return sum(len(g.staked_bet_ids) for g in self.games)

    @property
    def n_duplicate_wagers(self) -> int:
        return sum(g.duplicate_wagers for g in self.games)

    @property
    def n_vetoed(self) -> int:
        """Decisions whose own record carries at least one FATAL-severity
        ancestry is impossible to tell post-ATTACK (a FATAL veto removes the
        candidate before a record ever exists) -- what IS countable here is
        every record with a non-empty `counterarguments` list, i.e. every
        surviving candidate ATTACK had something to say about (MAJOR/MINOR),
        which is what "vetoes" means for a slate report: adversary activity
        against decisions that still played."""
        return sum(1 for g in self.games for r in g.records if r.counterarguments)


def decision_time_for_game(game_key: str, date_str: str, *,
                            margin_minutes: int = DEFAULT_PRE_GAME_MARGIN_MINUTES,
                            l1_path=glue_module.L1_PATH,
                            commence_path=glue_module.ODDS_SNAPSHOTS_PATH,
                            game_pk_map=None,
                            asof: str | None = None,
                            ) -> tuple[str | None, str | None, str | None]:
    """`(t, commence_time, skip_reason)` for one game: `t` is the LATEST L1
    capture strictly before `commence_time - margin_minutes`, searched
    across every capture this game has ever had (never restricted to
    `date_str`'s own capture rows -- the hourly capture cadence routinely
    captures tomorrow's slate hours ahead of first pitch, so a game slated
    for `date_str` may carry its only useful pre-game capture on the
    calendar day before), unless `asof` is given -- an explicit decision
    instant the caller wants used instead, still subject to the SAME
    first-pitch guard (skipped, never silently clamped, when `asof` is at
    or after commence_time). `skip_reason` is non-None, and
    `t`/`commence_time` are both None, exactly when this game should be
    excluded from the slate."""
    commence = glue_module.commence_time_for(
        game_key, path=commence_path, game_pk_map=game_pk_map)
    if commence is None:
        return None, None, ("commence_time unknown -- cannot verify "
                            "pre-game, refusing to assume it")
    commence_dt = _parse_utc(commence)

    if asof is not None:
        t_dt = _parse_utc(asof)
        if t_dt >= commence_dt:
            return None, None, (
                f"--asof {asof} is at/after commence_time {commence} -- "
                "in-play, refusing")
        return _iso(t_dt), commence, None

    margin_cutoff = commence_dt - timedelta(minutes=margin_minutes)
    rows = glue_module.read_l1_observations(game_key, path=l1_path)
    eligible = [_parse_utc(r.observed_utc) for r in rows
               if _parse_utc(r.observed_utc) <= margin_cutoff]
    if not eligible:
        return None, None, (
            f"no L1 capture at/before commence_time - {margin_minutes}min "
            f"({_iso(margin_cutoff)})")
    t_dt = max(eligible)
    if t_dt >= commence_dt:
        return None, None, (
            f"latest eligible capture {_iso(t_dt)} is at/after "
            f"commence_time {commence} -- in-play, refusing")
    return _iso(t_dt), commence, None


def _load_existing_decision_keys(path) -> set:
    out = set()
    for row in HashChainLedger(path).read():
        if row.get("kind") == "genesis" or "decision_utc" not in row:
            continue
        out.add((row.get("event_id"), row.get("system_id"),
                 row.get("market_key"), row.get("selection_id"),
                 row.get("decision_utc")))
    return out


def _load_existing_bet_ids(path) -> set:
    out = set()
    for row in HashChainLedger(path).read():
        bid = row.get("bet_id")
        if bid:
            out.add(bid)
    return out


def games_for_slate_date(date_str: str, *, l1_path=glue_module.L1_PATH,
                          commence_path=glue_module.ODDS_SNAPSHOTS_PATH,
                          game_pk_map: Mapping[str, dict] | None = None,
                          ) -> tuple:
    """Every L1 `board_key` whose game's own OFFICIAL (Eastern) calendar
    date is `date_str` -- NOT `glue.games_captured_on`'s "captured on this
    date" (a game slated for tomorrow is routinely captured today, hours
    ahead of first pitch, by the hourly capture cadence; keying the slate on
    capture date would silently pull tomorrow's games into today's slate
    and miss today's games captured yesterday evening). Scans every
    `board_key` the L1 store has ever seen (not just one day's rows) and
    keeps the ones whose resolved `commence_time` files under `date_str`.
    """
    from pathlib import Path as _Path

    from src.pipeline.snapshots import official_date as _official_date

    all_keys: set = set()
    for raw in glue_module._iter_l1_raw(_Path(l1_path)):
        key = glue_module._row_key(raw)
        if key:
            all_keys.add(key)

    matches = []
    for key in sorted(all_keys):
        commence = glue_module.commence_time_for(
            key, path=commence_path, game_pk_map=game_pk_map)
        if commence is None:
            continue
        if _official_date(commence) == date_str:
            matches.append(key)
    return tuple(matches)


def _decision_payload(record: DecisionRecord) -> dict:
    payload = record.to_dict()
    payload.pop("prev_hash", None)
    payload.pop("row_hash", None)
    return payload


def run_slate(
    date_str: str,
    *,
    systems: Sequence | None = None,
    adversaries: tuple = DEFAULT_ADVERSARIES,
    config: EngineConfig = DEFAULT_CONFIG,
    asof: str | None = None,
    dry_run: bool = False,
    l1_path=glue_module.L1_PATH,
    commence_path=glue_module.ODDS_SNAPSHOTS_PATH,
    decisions_path=None,
    wagers_path=None,
    game_pk_map: Mapping[str, dict] | None = None,
) -> SlateReport:
    """Run the slate for `date_str` and (unless `dry_run`) write frozen
    DecisionRecords + FLAT_1U paper wagers. Idempotent across re-runs (see
    module docstring)."""
    systems = tuple(systems) if systems is not None else REGISTERED_SYSTEMS
    if not systems:
        raise SlateError("run_slate needs at least one system")

    decisions_path = str(decisions_path or V2_LEDGER_PATH)
    wagers_path = str(wagers_path or PAPER_WAGERS_PATH)

    existing_decisions = _load_existing_decision_keys(decisions_path)
    existing_bet_ids = _load_existing_bet_ids(wagers_path)
    # `DecisionRecord.game_pk` is only ever the numeric MLB id when
    # `snapshot.game_pk` (== `PricedBoard.game_pk`, `GameRef.board_key`)
    # itself is numeric -- for every L1-sourced game it is the odds
    # provider's own `event_id` (an opaque hash; `GameRef.board_key` prefers
    # `event_id`), so `record.game_pk` is `None` on every live decision.
    # `settle_slate.py` needs a REAL game_pk to key results lookups on; the
    # S1 map (`src.board.gamekey`) already resolves exactly this, so the
    # wager row (not the frozen DecisionRecord itself, which is left
    # untouched) carries the resolved id.
    resolved_game_pk_map = (game_pk_map if game_pk_map is not None
                            else gamekey_module.load_map())

    games = games_for_slate_date(date_str, l1_path=l1_path,
                                 commence_path=commence_path,
                                 game_pk_map=resolved_game_pk_map)
    game_outcomes: list[GameOutcome] = []

    for game_key in games:
        t, commence, reason = decision_time_for_game(
            game_key, date_str, l1_path=l1_path, commence_path=commence_path,
            game_pk_map=game_pk_map, asof=asof)
        if t is None:
            game_outcomes.append(GameOutcome(
                game_key=game_key, game_pk=None, t=None, commence_time=None,
                skipped_reason=reason, records=(), new_decisions=0,
                duplicate_decisions=0, staked_bet_ids=(), duplicate_wagers=0))
            continue

        board = glue_module.build_board(
            game_key, t, path=l1_path, commence_time=commence,
            game_pk_map=game_pk_map)
        markets_present = {q.market_key for q in board.quotes}
        if not (markets_present & set(SCOPE_MARKETS)):
            game_outcomes.append(GameOutcome(
                game_key=game_key, game_pk=board.game_pk, t=t,
                commence_time=commence,
                skipped_reason="no captured price in a supported market "
                              f"({SCOPE_MARKETS})",
                records=(), new_decisions=0, duplicate_decisions=0,
                staked_bet_ids=(), duplicate_wagers=0))
            continue

        snapshot = glue_module.build_snapshot(
            game_key, t, board=board, game_pk_map=game_pk_map)
        analysis = analyze(snapshot, board, systems=systems,
                           adversaries=adversaries, config=config)

        # Scope: four markets only, and only the games/records this board
        # actually priced -- a record naming a market outside SCOPE_MARKETS
        # (no registered system does today, but the guard is explicit
        # rather than assumed) is dropped before it is ever considered for
        # staking or the ledger.
        scoped = tuple(r for r in analysis.records if r.market_key in SCOPE_MARKETS)

        staked_system_ids: set = set()
        final_records: list[DecisionRecord] = []
        for record in scoped:
            record = replace(record, selection_rule=SELECTION_RULE)
            if record.verdict == "play" and record.system_id not in staked_system_ids:
                staked_system_ids.add(record.system_id)
                record = replace(record, stake_units=FLAT_1U)
            final_records.append(record)

        new_decisions = duplicate_decisions = 0
        new_bet_ids: list[str] = []
        duplicate_wagers = 0
        for record in final_records:
            key = decision_key(record)
            if key in existing_decisions:
                duplicate_decisions += 1
            else:
                if not dry_run:
                    append_decision(record, path=decisions_path)
                existing_decisions.add(key)
                new_decisions += 1

            if record.verdict == "play" and record.stake_units == FLAT_1U:
                bet_id = bet_id_for(date_str, record)
                if bet_id in existing_bet_ids:
                    duplicate_wagers += 1
                    continue
                settlement_rule = (MARKET_CATALOGUE[record.market_key]
                                  .settlement_rule)
                resolved_game_pk = record.game_pk or gamekey_module.game_pk_for_event(
                    record.event_id, resolved_game_pk_map)
                bet = PaperBet(
                    bet_id=bet_id, system_id=record.system_id,
                    market_key=record.market_key,
                    selection_id=record.selection_id,
                    side=_side_for_record(record),
                    line=record.line, price_american=record.price_american,
                    settlement_rule=settlement_rule,
                    game_pk=resolved_game_pk,
                )
                if not dry_run:
                    HashChainLedger(wagers_path).append({
                        "label": PAPER_LABEL, "date": date_str,
                        "bet_id": bet.bet_id, "system_id": bet.system_id,
                        "market_key": bet.market_key,
                        "selection_id": bet.selection_id, "side": bet.side,
                        "line": bet.line, "price_american": bet.price_american,
                        "settlement_rule": bet.settlement_rule,
                        "stake_units": bet.stake_units,
                        "game_pk": bet.game_pk, "event_id": record.event_id,
                        "decision_utc": record.decision_utc,
                        "selection_rule": SELECTION_RULE,
                    })
                existing_bet_ids.add(bet_id)
                new_bet_ids.append(bet_id)

        game_outcomes.append(GameOutcome(
            game_key=game_key, game_pk=board.game_pk, t=t,
            commence_time=commence, skipped_reason=None,
            records=tuple(final_records), new_decisions=new_decisions,
            duplicate_decisions=duplicate_decisions,
            staked_bet_ids=tuple(new_bet_ids),
            duplicate_wagers=duplicate_wagers))

    return SlateReport(date=date_str, dry_run=dry_run,
                       systems=tuple(s.id for s in systems),
                       games=tuple(game_outcomes))


def _side_for_record(record: DecisionRecord) -> str:
    """The side a PaperBet stakes, recovered from `record.selection_id`'s
    own identity via the market's declared side vocabulary -- DecisionRecord
    does not itself carry a bare `side` field (only the hashed
    `selection_id`), so this checks each declared side of the record's own
    market against the board's own selection_id hash until one matches.
    Never guesses: raises if none does, which would mean either the
    catalogue or `src.board.ids.selection_id` disagrees with itself."""
    from src.board.ids import selection_id as _sel_id

    spec = MARKET_CATALOGUE[record.market_key]
    for side in spec.sides:
        if _sel_id(sport="mlb", market_key=record.market_key, side=side,
                   line=record.line) == record.selection_id:
            return side
    raise SlateError(
        f"could not recover side for selection_id={record.selection_id!r} "
        f"market_key={record.market_key!r} line={record.line!r} against "
        f"declared sides {spec.sides} -- selection_id/catalogue mismatch")
