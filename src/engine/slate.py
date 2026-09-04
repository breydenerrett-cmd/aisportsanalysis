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

THE DAY-LEVEL RANKING
-----------------------
`SELECTION_RULE` stops at the game boundary. The owner directive of
2026-09-04 asks for each system's best ten picks ACROSS the slate, so
`DAY_RANKING_RULE`/`rank_day_by_system` below add a second, separately
pre-registered order: top-N per system per day, ranked on price standing
(execution quality), never on a fabricated edge. Its basis is named in
`DAY_RANKING_BASIS` and printed alongside every rendered pick.

IDEMPOTENCY
------------
Re-running the same date writes zero duplicate decisions and zero duplicate
wagers: a decision's identity is `(event_id, system_id, market_key,
selection_id, decision_utc)`, checked against every row already in
`evidence/decisions_v2.jsonl` before appending; a wager's identity is a
`bet_id` derived deterministically from that same tuple (`bet_id_for`),
checked against every row already in `evidence/paper_wagers_v2.jsonl`.

FROZEN MEANS WRITTEN BEFORE FIRST PITCH, NOT JUST DECIDED BEFORE IT
---------------------------------------------------------------------
(B1/B2, slice-review-2026-09-03.) "Before any outcome exists" above is a
claim about the WRITE, not just the decision instant `t` the board was
built at -- `t` being honestly pre-game (the existing first-pitch guard on
`decision_time_for_game`) says nothing about how much wall-clock time has
passed by the time this function actually runs and appends to the ledger.
Two things close that gap, both in `run_slate`:

  * every DecisionRecord written here now carries `recorded_utc` set to
    the REAL write instant (a wall-clock read taken once per call, `now`
    below -- overridable for tests only) instead of a copy of
    `decision_utc`, plus `record_provenance` naming whether this was a
    live pre-commitment write or a deliberate replay/backfill of an
    already-past date (`src.ledger.records.RECORD_PROVENANCE_VALUES`);
  * a LIVE-mode run (`_slate_mode` below) additionally refuses -- skips,
    same as any other named skip reason, never writes a decision at all --
    any game whose `commence_time` is at or before that same write
    instant, even when `t` was honestly pre-game. REPLAY mode (a
    deliberate backfill of an already-past `date_str`) is exempt: every
    game in a real backfill has necessarily already been played.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from src.accounts.paper import FLAT_1U, PAPER_LABEL, PaperBet
from src.board import gamekey as gamekey_module
from src.board.ids import MARKET_CATALOGUE
from src.core.asof import game_pk_key
from src.engine import glue as glue_module
from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS
from src.engine.adversaries import DEFAULT_ADVERSARIES
from src.engine.analyze import DEFAULT_CONFIG, EngineConfig, analyze
from src.ledger.bridge import V2_LEDGER_PATH
from src.ledger.chain import HashChainLedger
from src.ledger.records import (
    RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
    RECORD_PROVENANCE_REPLAY,
    DecisionRecord,
)
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


# --- The day-level ranking rule --------------------------------------------
#
# `SELECTION_RULE` above answers "which of a system's records for ONE GAME
# gets staked". The owner directive of 2026-09-04 asks a different question:
# across the WHOLE SLATE, which are this system's best ten? A day-level
# order is not derivable from the per-game rule -- that rule stops at the
# game boundary -- so it is pre-registered here, in the open, with the basis
# named in every rendered output.
#
# THE BASIS IS PRICE STANDING, AND PRICE STANDING IS NOT AN EDGE.
# `price_standing_bps` below is (the board's own de-vigged consensus for the
# selection) minus (the implied probability of the best price actually
# available), in basis points. It measures ONE thing: how far the best
# quote on the board stands from what the rest of the board, on the same
# quotes, considers fair. It is emphatically NOT an edge: the consensus is
# derived FROM these same prices, so the two are not independent and their
# difference can never be evidence that the market is wrong. That is exactly
# why `DecisionRecord.value_basis` on every record here already reads
# `price_standing_only:no_calibrated_p_model`, and why ranking on it is
# honest while ranking on a fabricated edge would not be: it ranks EXECUTION
# QUALITY (am I taking the best number available for the thing I chose),
# never predictive merit.
#
# A record with no consensus (fewer than `min_books` books quoting both
# sides) or no price has NO basis value at all. It is not defaulted to zero
# -- zero is a real, middling standing -- it is ranked last as a named,
# visible "basis unavailable" group.
DAY_RANKING_RULE = "TOP_N_PER_SYSTEM_PER_DAY_BY_PRICE_STANDING_V1"

# The owner asked for "top 10 best bets for the projected day", with 10-15
# named as the useful band. Ten is the default; the number is a parameter
# because the right N is a product decision, not an engine fact.
DEFAULT_TOP_N_PER_SYSTEM_PER_DAY = 10

DAY_RANKING_BASIS = (
    "price standing in bps (the board's own de-vigged consensus for the "
    "selection minus the implied probability of the best available price), "
    "then more books at the decision, then lower vig, then selection_id and "
    "event_id for determinism. Price standing is execution quality, NOT an "
    "edge: the consensus is computed from these same prices, so their "
    "difference can never be evidence the market is wrong. It is normally "
    "NEGATIVE -- a real quote's implied probability carries the book's "
    "margin, which the de-vigged consensus has had removed -- so ranking "
    "on it ranks how little of that margin the bettor pays, and a positive "
    "value means one book is offering better than the board's own "
    "consensus, not that a profit has been found."
)


@dataclass(frozen=True, slots=True)
class RankedPick:
    """One record in a system's day-level top-N, with the number it was
    ranked on carried alongside it -- a rank whose basis a reader has to
    take on faith is a rank they cannot check."""

    rank: int
    record: DecisionRecord
    game_key: str
    price_standing_bps: int | None
    basis: str = DAY_RANKING_BASIS


def price_standing_bps(record: DecisionRecord) -> int | None:
    """How far this record's price stands from the board's own consensus,
    in basis points -- or None when either input is genuinely absent.

    NOT an edge (see DAY_RANKING_BASIS): consensus and price are the same
    data seen two ways. None over guess: a missing consensus or price is
    reported as absent, never as a standing of zero.
    """
    if record.consensus_fair is None or record.price_american is None:
        return None
    from src.core import odds as odds_math

    implied = odds_math.american_to_probability(record.price_american)
    return int(round((record.consensus_fair - implied) * 10_000))


def _day_rank_key(entry) -> tuple:
    """Deterministic total order; no tie is ever broken by chance or by
    iteration order. Records with no basis value sort after every record
    that has one (the leading 1/0), rather than being given a made-up
    number that would let them outrank real ones."""
    record, game_key = entry
    standing = price_standing_bps(record)
    vig = (record.friction or {}).get("vig")
    return (
        0 if standing is not None else 1,
        -(standing if standing is not None else 0),
        -int(record.books_at_decision or 0),
        (0, vig) if isinstance(vig, (int, float)) else (1, 0.0),
        record.selection_id or "",
        record.event_id or "",
        game_key,
    )


def rank_day_by_system(
    games: Sequence,
    *,
    top_n: int = DEFAULT_TOP_N_PER_SYSTEM_PER_DAY,
) -> dict:
    """`{system_id: (RankedPick, ...)}` -- each system's best `top_n` plays
    across the whole slate, under `DAY_RANKING_RULE`.

    `games` is a sequence of `GameOutcome`. Only `verdict == "play"` records
    are eligible: a refusal is not a pick, and publishing one in a "best
    bets" list would misrepresent the engine standing down as the engine
    choosing. Deterministic: same slate in, same order out, on any machine.
    """
    by_system: dict = {}
    for game in games:
        for record in game.records:
            if record.verdict != "play":
                continue
            by_system.setdefault(record.system_id, []).append(
                (record, game.game_key))
    out: dict = {}
    for system_id, entries in by_system.items():
        entries.sort(key=_day_rank_key)
        out[system_id] = tuple(
            RankedPick(rank=i, record=record, game_key=game_key,
                       price_standing_bps=price_standing_bps(record))
            for i, (record, game_key) in enumerate(entries[:top_n], start=1)
        )
    return out


class SlateError(ValueError):
    """A slate run could not proceed honestly."""


def _parse_utc(value: str) -> datetime:
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _slate_mode(date_str: str, now: datetime) -> str:
    """"LIVE" when `date_str` names `now`'s own UTC calendar date or a
    future one, "REPLAY" when it names a date strictly before it -- the
    same split `src.engine.preflight._mode_and_references` uses, applied
    here for the SAME reason: a deliberate backfill of an already-past date
    necessarily concerns games that have already been played, and must not
    be judged by the live "has first pitch already happened" guard below
    (B2, slice-review-2026-09-03) -- only a slate being decided for today
    (or later) can write a record whose provenance honestly claims
    pre-commitment."""
    return "LIVE" if date.fromisoformat(date_str) >= now.date() else "REPLAY"


def _l1_source_mtimes_newer_than_output(output_path, source_paths) -> bool:
    """`True` when `output_path` (the L1 store) does not exist yet, or any
    path in `source_paths` has a newer mtime than it -- the cheap (`stat()`
    only, no JSONL parsing) signal that `output_path` might now be missing
    rows a source store already has. A source path that does not exist is
    simply not a reason to refresh (nothing to project from it yet)."""
    output = Path(output_path)
    if not output.exists():
        return True
    output_mtime = output.stat().st_mtime
    for source in source_paths:
        source = Path(source)
        if source.exists() and source.stat().st_mtime > output_mtime:
            return True
    return False


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

    def top_picks_by_system(
        self, top_n: int = DEFAULT_TOP_N_PER_SYSTEM_PER_DAY) -> dict:
        """Each system's best `top_n` plays for this whole slate under
        `DAY_RANKING_RULE`. Computed on demand rather than stored: the
        ranking is a pure function of the records already in this report,
        and a stored copy is a second version of the same fact that can
        drift from the first."""
        return rank_day_by_system(self.games, top_n=top_n)

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
    refresh_l1: bool = True,
    l1_sources: Sequence | None = None,
    l1_raw_root=None,
    now: datetime | None = None,
) -> SlateReport:
    """Run the slate for `date_str` and (unless `dry_run`) write frozen
    DecisionRecords + FLAT_1U paper wagers. Idempotent across re-runs (see
    module docstring).

    ALREADY-COMMENCED GUARD + RECORD PROVENANCE (B1/B2,
    slice-review-2026-09-03). `now` (defaults to a real wall-clock read,
    `datetime.now(timezone.utc)`; overridable -- tests only, the same
    convention as `src.engine.preflight.check`) is the actual write
    instant, read ONCE per `run_slate` call and used for two things:

      1. `decision_time_for_game`'s existing guard only ever compares the
         DECISION instant `t` (the latest L1 capture before commence) to
         that game's own `commence_time` -- it says nothing about how much
         wall-clock time has passed between `t` and the moment this
         function actually runs and writes. A slate invoked hours late (a
         missed cron, a manual re-run at end of day) could pick a genuinely
         pre-game `t` for a game whose first pitch has, by the time the
         write happens, already come and gone -- exactly the flagship
         2026-09-03 slate's bug (three of its nine staked games, not the
         two the original review caught: `f857ea67…`, `e956df5f…`, and
         `e3f232af…`, had already started by the observed write instant).
         So in LIVE mode (`_slate_mode` above -- `date_str` is today or a
         future date) this function ALSO refuses any game whose
         `commence_time` is at or before `now`, skipping it with an
         "already commenced" reason exactly like every other skip reason
         here, rather than writing a decision for it at all. REPLAY mode
         (a deliberate backfill of an already-past `date_str`) is exempt on
         purpose: every game in a real backfill has necessarily already
         been played, and that is the honest, intended use of replay -- see
         `_slate_mode`'s own docstring.
      2. Every DecisionRecord this call writes carries `recorded_utc=now`
         (the real write instant, not `decision_utc`/`information_time`,
         which stay the decision instant `t`) and
         `record_provenance="live_pre_commencement"` in LIVE mode or
         `"replay"` in REPLAY mode -- so a reader can always tell a
         genuinely pre-commitment record from a deliberate backfill,
         without having to infer it from git history the way B1 originally
         required. (`"live_post_commencement"` -- the case where a live
         write happened after commence -- is reserved vocabulary for
         labelling records that predate this guard; this function itself
         never produces it going forward, because it refuses the game
         instead.)

    L1 REFRESH (fixes: a slate run seeing hours-stale prices while fresher
    ones already sat captured on disk). `data/processed/l1_observations.jsonl`
    is a PROJECTION `src.board.l1.run()` builds from the real price stores
    (odds_multibook/odds_snapshots/f5_close) -- nothing else re-projects it
    after a capture, so without this a capture landing between two slate
    runs is invisible to `engine slate` until someone remembers to run
    `l1 --backfill` by hand. `run_slate` is the ONE path every real
    invocation of `engine slate` goes through (the CLI, the daily loop,
    replay demonstrations) and it reads L1 through `l1_path` immediately
    below via `games_for_slate_date`/`build_board` -- so refreshing HERE,
    before either is called, is the placement a caller cannot forget by
    omitting a separate step; `refresh_l1=True` is the default for exactly
    that reason.

    The refresh only ever fires when it is safe to: either `l1_path` is the
    real production L1 store (the default -- refreshed from the real
    production source stores), or the caller has explicitly named
    `l1_sources`/`l1_raw_root` to refresh FROM. A test handing `run_slate` a
    synthetic `l1_path` with neither is left untouched -- otherwise every
    existing test using a clean L1 fixture would silently get real
    production price rows projected into it. Idempotent: `src.board.l1.run`
    only ever WRITES rows not already present by `observation_id`, so a
    repeated call writes zero new rows.

    NO FULL RE-WALK WHEN UNNECESSARY: `l1.run()` itself still re-reads every
    source row on each call it makes (needed for its own grading pass), so
    calling it unconditionally on every `engine slate` invocation would pay
    that same walk again even when nothing on disk has changed since the
    last one. `_l1_source_mtimes_newer_than_output` below is the cheap guard
    in front of it: a handful of `stat()` calls, not a JSONL parse, decide
    whether ANY source file `l1_path` would be projected from has changed
    since `l1_path` was last written; `l1.run()` itself is only invoked when
    that is true (or `l1_path` does not exist yet at all). A slate re-run
    between two captures -- the daily loop's actual cadence -- skips the
    walk entirely instead of re-scanning a store that has not moved.
    """
    systems = tuple(systems) if systems is not None else REGISTERED_SYSTEMS
    if not systems:
        raise SlateError("run_slate needs at least one system")

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise SlateError(f"now={now!r} is not timezone-aware")

    mode = _slate_mode(date_str, now)
    recorded_utc = _iso(now)
    record_provenance = (RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT
                         if mode == "LIVE" else RECORD_PROVENANCE_REPLAY)

    decisions_path = str(decisions_path or V2_LEDGER_PATH)
    wagers_path = str(wagers_path or PAPER_WAGERS_PATH)

    if refresh_l1 and (l1_sources is not None or l1_raw_root is not None
                        or Path(l1_path) == Path(glue_module.L1_PATH)):
        from src.board import l1 as l1_module
        source_paths = (
            [s["path"] for s in l1_sources] if l1_sources is not None
            else [s["path"] for s in l1_module.SOURCE_STORES]
                + [s["path"] for s in
                   l1_module._discover_closing_stores(Path(l1_path).parent)])
        if _l1_source_mtimes_newer_than_output(l1_path, source_paths):
            l1_kwargs: dict = {}
            if l1_sources is not None:
                l1_kwargs["sources"] = list(l1_sources)
            if l1_raw_root is not None:
                l1_kwargs["raw_root"] = l1_raw_root
            l1_module.run(since=date_str, output_path=l1_path, **l1_kwargs)

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

        # B2 (slice-review-2026-09-03): `t` being honestly pre-game says
        # nothing about whether THIS RUN, writing right now, is happening
        # before or after that same game's first pitch -- a slate invoked
        # late (a missed cadence, a manual re-run hours after the captures
        # it used) can pick a genuinely pre-game `t` for a game that has,
        # by the time of this actual write, already started. REPLAY mode is
        # exempt on purpose (see `_slate_mode`): every game in a deliberate
        # backfill of an already-past date has necessarily already been
        # played.
        commence_dt = _parse_utc(commence)
        if mode == "LIVE" and now >= commence_dt:
            already_minutes = (now - commence_dt).total_seconds() / 60.0
            game_outcomes.append(GameOutcome(
                game_key=game_key, game_pk=None, t=t, commence_time=commence,
                skipped_reason=(
                    f"already commenced -- first pitch {commence} was "
                    f"{already_minutes:.1f} min before the write instant "
                    f"{recorded_utc}; refusing to stake a game already "
                    "underway"),
                records=(), new_decisions=0, duplicate_decisions=0,
                staked_bet_ids=(), duplicate_wagers=0))
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
                           adversaries=adversaries, config=config,
                           recorded_utc=recorded_utc,
                           record_provenance=record_provenance)

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
                # `record.game_pk` (int|None, src.engine.analyze) and
                # `game_pk_for_event` (the canonical join-key STRING,
                # src.core.asof.game_pk_key) are two different types for
                # the same fact -- `PaperBet.game_pk` is `int | None`
                # (matching boxscores_*.jsonl/mlb_results.csv's own leaf
                # convention), so both branches are canonicalized through
                # the same helper before being cast back to int, rather
                # than an `or` that could hand PaperBet either type
                # depending on which branch happened to answer.
                resolved_game_pk_str = game_pk_key(record.game_pk) or (
                    gamekey_module.game_pk_for_event(
                        record.event_id, resolved_game_pk_map))
                resolved_game_pk = (
                    int(resolved_game_pk_str)
                    if resolved_game_pk_str is not None else None)
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
    from src.board.readable import side_for_selection

    spec = MARKET_CATALOGUE[record.market_key]
    side = side_for_selection(record.market_key, record.selection_id,
                              record.line)
    if side is not None:
        return side
    raise SlateError(
        f"could not recover side for selection_id={record.selection_id!r} "
        f"market_key={record.market_key!r} line={record.line!r} against "
        f"declared sides {spec.sides} -- selection_id/catalogue mismatch")
