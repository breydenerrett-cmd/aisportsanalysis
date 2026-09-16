"""Closing-line measurement for DAILY_CARD_BEST_BETS_V2's own picks and
fills (build plan T4; registration 11.3's primary metric, section 4's
market keys).

WHY A NEW FILE, NOT MORE CODE IN `src/report/clv.py`
------------------------------------------------------
`clv.py` measures the live paper ledger's `DecisionRecord`s -- a different
row shape, a different set of absence reasons (its own `ABSENCE_REASONS`
dict, named for that ledger's own failure modes: `SIDE_NOT_RECOVERABLE`,
`DECISION_CONSENSUS_INCONSISTENT`, and so on), and a different publication
cut (provenance and staleness gates that apply to a decision written before
or after first pitch, not to a card pick that is always written before). A
V2 card row has no `consensus_fair`, no `price_american` naming convention,
no `record_provenance` -- reusing `clv.py`'s absence vocabulary here would
either force this module to fabricate fields a card row never carries, or
force `clv.py` to grow a second row shape it was never designed to read.
Registration 11.3's own worked arithmetic (`clv_bps = (p_close - needs) *
10000`, the `price -112 / needs 0.5283 / p_close 0.53` example) is simpler
than `clv.py`'s `consensus_move_bps + price_standing_bps` split, on purpose:
a card pick carries the market's implied probability at the price actually
shown to the reader, not a frozen `consensus_fair` computed at decision
time, so there is only one gap to measure, not two.

What IS reused, because re-deriving it would be exactly the kind of drift
this project keeps writing regression tests to catch: `clv.pregame_index`
(the two-guard pre-game index), `clv.closing_board` (the market's last
pre-game capture, chosen BEFORE the line or the book floor is checked --
see that function's own docstring for why the order matters) and
`clv.closing_consensus` (the de-vig, `src.analysis.prices.snapshot`'s, with
the same `MIN_BOOKS` floor). No de-vig math or closing-instant selection is
re-written here.

PURE, INJECTED, NO CLOCK, NO DISK
------------------------------------
`measure_pick` takes a `pick` (a frozen V2 ledger entry) and an `index`
(a `clv.pregame_index()` result) and returns one measurement or one named
absence. `measure_ledger` takes a `path` and the same `index` and walks a
V2 settled-row ledger built by `src.appstate.card_ledger.settle_v2`. Neither
function opens `data/processed/odds_multibook.jsonl` or any other store
itself -- the index is always the caller's to build (with
`clv.pregame_index`) and hand in, so a test never has to touch a real store
to prove this module's arithmetic.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from src.analysis import best_bets_card
from src.appstate import card_ledger
from src.ledger.chain import HashChainLedger
from src.report import clv

# ---------------------------------------------------------------------------
# Market keys (registration section 4 / build plan T4). Moneyline reads
# clv.py's "h2h" shape; a run line reads "spreads" at the pick's own signed
# line -- MARKET_SHAPES.spreads already matches on the side's own line
# field, so "matched on sign and 1.5 exactly" falls straight out of
# clv.closing_board's own line filter, with nothing extra needed here.
# ---------------------------------------------------------------------------

_MARKET_KEY = {
    "moneyline": "h2h",
    "run_line": "spreads",
}

# ---------------------------------------------------------------------------
# Named absences (build plan T4's own list, distinct from clv.py's).
# ---------------------------------------------------------------------------

NO_EVENT = "NO_EVENT"
NO_MARKET = "NO_MARKET"
CLOSING_BOARD_THIN = "CLOSING_BOARD_THIN"
CLOSE_STALE = "CLOSE_STALE"
CLOSING_BOARD_IS_DECISION_BOARD = "CLOSING_BOARD_IS_DECISION_BOARD"
CLOSE_PRECEDES_DECISION = "CLOSE_PRECEDES_DECISION"
PROP_NOT_MEASURED = "PROP_NOT_MEASURED"

ABSENCE_REASONS = {
    NO_EVENT: (
        "the pre-game index carries no capture for this pick's event, so no "
        "closing board exists to compare against"),
    NO_MARKET: (
        "this pick's market has no declared closing-board shape, or the "
        "market was never captured before first pitch for this event"),
    CLOSING_BOARD_THIN: (
        f"fewer than {clv.MIN_BOOKS} books quoted this pick's exact "
        "selection at the closing instant -- the market most likely closed "
        "on a different line than the one taken"),
    CLOSE_STALE: (
        f"the closing capture is more than {clv.CLOSING_LEAD_STALE_SECONDS} "
        "seconds before first pitch, further out than this measurement "
        "will call unqualified"),
    CLOSING_BOARD_IS_DECISION_BOARD: (
        "the closing capture is the same instant this pick's own quote came "
        "from, so the gap would measure the book's hold, not the close"),
    CLOSE_PRECEDES_DECISION: (
        "the closing capture is older than this pick's own quote, so "
        "calling it the close would measure the market backwards"),
    PROP_NOT_MEASURED: (
        "player props have never reached the six-book closing floor this "
        "project requires; they are never measured against the close"),
}


class CardClvError(ValueError):
    """A programming error in this module's own inputs -- an absence
    reason with no entry above. Never raised for missing market data;
    missing data is always a named absence, not an exception."""


def _absent(reason: str, *, entry_class, price_class, **extra) -> dict:
    if reason not in ABSENCE_REASONS:
        raise CardClvError(f"unnamed absence {reason!r}")
    out = {
        "entry_class": entry_class, "price_class": price_class,
        "absence": reason, "absence_reason": ABSENCE_REASONS[reason],
    }
    out.update(extra)
    return out


def measure_pick(pick: Mapping, index: Mapping) -> dict:
    """One frozen V2 pick (or fill, or withdrawn entry) against the close.

    needs        = breakeven(graded price)          # vig included
    board        = clv.closing_board(entry, market_key, side, line)
    p_close      = clv.closing_consensus(board, market_key, side)  # de-vigged
    clv_bps      = (p_close - needs) * 10,000
    clv_pct      = p_close / needs - 1
    beats_close  = clv_pct > 0

    consensus_drift_pct = p_close / p_lock - 1, with p_lock the pick's own
    frozen `market_probability` (never called CLV -- registration 11.3
    names this S4 and forbids the label).

    Returns an absence with one of `ABSENCE_REASONS` above when any step
    cannot be completed. A prop (`pick["kind"] == "prop"`) always returns
    `PROP_NOT_MEASURED`, unconditionally: no prop book has ever reached the
    six-book floor this measurement requires (registration 11.3), so a prop
    is refused before any board is even looked up.
    """
    entry_class = pick.get("entry_class")
    price_class = pick.get("price_class")

    if pick.get("kind") == "prop":
        return _absent(PROP_NOT_MEASURED, entry_class=entry_class, price_class=price_class)

    market_key = _MARKET_KEY.get(pick.get("market"))
    if market_key is None:
        return _absent(NO_MARKET, entry_class=entry_class, price_class=price_class)

    price = pick.get("price")
    needs = best_bets_card.breakeven(price) if price is not None else None
    if needs is None:
        return _absent(NO_MARKET, entry_class=entry_class, price_class=price_class)

    event_id = pick.get("event_id")
    entry = index.get(event_id) if event_id is not None else None
    if not event_id or entry is None:
        return _absent(NO_EVENT, entry_class=entry_class, price_class=price_class)

    side = pick.get("side")
    line = pick.get("line")
    board = clv.closing_board(entry, market_key, side, line)
    if "absence" in board:
        reason = board["absence"]
        if reason == clv.COMMENCE_TIME_UNKNOWN:
            return _absent(NO_EVENT, entry_class=entry_class, price_class=price_class)
        if reason == clv.CLOSING_BOARD_THIN:
            return _absent(CLOSING_BOARD_THIN, entry_class=entry_class, price_class=price_class)
        # MARKET_NOT_CAPTURED, NO_CAPTURE_BEFORE_COMMENCE: the market has no
        # usable pre-game word on this selection at all.
        return _absent(NO_MARKET, entry_class=entry_class, price_class=price_class)

    if board.get("lead_stale"):
        return _absent(CLOSE_STALE, entry_class=entry_class, price_class=price_class,
                       lead_seconds=board.get("lead_seconds"))

    decision_observed = pick.get("observed_utc")
    board_observed = board.get("observed_utc")
    if decision_observed and board_observed:
        if str(decision_observed) == str(board_observed):
            return _absent(CLOSING_BOARD_IS_DECISION_BOARD,
                           entry_class=entry_class, price_class=price_class)
        d_moment = clv._moment(decision_observed)
        b_moment = clv._moment(board_observed)
        if d_moment is not None and b_moment is not None and b_moment < d_moment:
            return _absent(CLOSE_PRECEDES_DECISION,
                           entry_class=entry_class, price_class=price_class)

    consensus = clv.closing_consensus(board, market_key, side)
    if "absence" in consensus:
        return _absent(CLOSING_BOARD_THIN, entry_class=entry_class, price_class=price_class)

    p_close = consensus["closing_probability"]
    clv_bps = (p_close - needs) * 10_000.0
    clv_pct = p_close / needs - 1.0

    p_lock = pick.get("market_probability")
    consensus_drift_pct = (p_close / p_lock - 1.0) if p_lock else None

    return {
        "entry_class": entry_class, "price_class": price_class,
        "needs": needs,
        "p_close": p_close,
        "clv_bps": round(clv_bps, 4),
        "clv_pct": round(clv_pct, 6),
        "beats_close": clv_pct > 0,
        "consensus_drift_pct": (round(consensus_drift_pct, 6)
                                 if consensus_drift_pct is not None else None),
        "observed_utc": consensus.get("observed_utc"),
        "lead_seconds": consensus.get("lead_seconds"),
        "books_at_close": consensus.get("books"),
    }


def measure_ledger(path: str, index: Mapping) -> list:
    """Every graded V2 pick and fill, and every withdrawn entry, on the
    settled-row ledger at `path`, each measured against `index`
    (registration 11.1: withdrawn entries are counted; a fill is graded but
    never counted -- both are still measured here, apart, because
    `measure_ledger` describes what happened to every SHOWN entry, and the
    read script -- not this function -- decides which populations feed a
    statistic).

    Each measurement carries the entry's own `entry_class` and `price_class`
    (already on the frozen row, never recomputed here) so a caller can split
    by class from one pass, per registration 11.1 and 11.3.
    """
    out: list = []
    for row in HashChainLedger(path).read():
        if row.get("kind") != card_ledger.KIND_SETTLED:
            continue
        date = row.get("date")
        for entry in row.get("graded") or ():
            measurement = measure_pick(entry, index)
            measurement["date"] = date
            measurement["withdrawn"] = bool(entry.get("withdrawn"))
            out.append(measurement)
        for entry in row.get("withdrawn_graded") or ():
            measurement = measure_pick(entry, index)
            measurement["date"] = date
            measurement["withdrawn"] = True
            out.append(measurement)
    return out
