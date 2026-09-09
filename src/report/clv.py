"""Closing-line value: the number we took, against the number the market closed at.

WHY THIS MODULE EXISTS
-----------------------
`docs/PRODUCT_DOCTRINE.md` §8.5 lists "CLV has never been measured" as a known
misalignment, and §6 names CLV the LEADING indicator of the public record with
realized return as the lagging one. That ordering is the whole reason this file
exists: a forward record of 72 settled bets cannot separate a real selection
from a lucky one, but the closing line can say -- far sooner, and on every
decision rather than only the settled ones -- whether the number we took was
better than where the market ended up. Nothing in this repository computed that
before. `src.pipeline.snapshots.closing_line_value` compares two RAW American
prices and is used by the single-book snapshot surface; it has no notion of a
de-vigged multi-book consensus, of a book floor, or of a decision ledger, and
it silently answers for any two prices handed to it. This module is the ledger-
wide measurement, and it refuses far more often than it answers.

WHAT CLV IS HERE, PRECISELY
----------------------------
For a frozen decision that TOOK price P on selection S at instant T, the close
is the DE-VIGGED CONSENSUS for S from the last multi-book capture strictly
before that game's first pitch. CLV is

    clv_bps = (closing_consensus_probability - implied_probability(P)) * 10000

Positive means we took a number the closing market says was better than the
price implies. That is evidence the selection carried information; it is NOT a
profit, NOT an expected value, NOT a win probability, and NOT an edge. No
independent model probability exists anywhere in this project (`edge_bps` is
structurally null on every live row), so nothing here may be read as predictive
merit beyond the one narrow claim above.

THE VIG ASYMMETRY, AND WHY THE HEADLINE NUMBER IS BIASED NEGATIVE
------------------------------------------------------------------
`implied_probability(P)` carries the book's margin; the closing consensus has
had the margin removed. Subtracting one from the other therefore starts life
NEGATIVE by roughly half the hold, on every bet, before any line has moved --
exactly the arithmetic `src.analysis.prices.NO_IMPROVEMENT_NOTE` already warns
about for price improvement. A column of negative `clv_bps` is the normal case
and is not by itself a verdict on the systems.

So every measurement carries the decomposition, and it is an exact identity:

    clv_bps = consensus_move_bps + price_standing_bps

  * `consensus_move_bps` -- the de-vigged consensus at the close minus the
    de-vigged consensus FROZEN ON THE DECISION (`DecisionRecord.consensus_fair`).
    Both sides of that subtraction have had the vig removed, so the hold
    cancels: this is how far the fair market moved toward the side we took,
    and it is the vig-neutral reading of "did this selection have information
    value". Read this one when comparing systems.
  * `price_standing_bps` -- the frozen consensus minus what our taken price
    implied. This is EXECUTION QUALITY and nothing else. It is the same
    quantity `src.engine.slate` calls "emphatically NOT an edge", recomputed
    here from the record's own frozen fields so the identity above can be
    checked rather than asserted.

Reporting the mandated `clv_bps` without that split would let a structural
hold term be read as a verdict on the ranker, which is precisely the class of
mistake this project keeps writing modules to prevent.

WHAT IS REFUSED, AND WHY REFUSAL IS THE POINT
-----------------------------------------------
Every decision that cannot be measured gets a NAMED absence and a sentence
saying why (`ABSENCE_REASONS`). Nothing is zero-filled, interpolated, or
matched to a "close enough" board. The refusals that matter most:

  * `CLOSING_BOARD_IS_DECISION_BOARD` -- the last pre-game capture IS the board
    the decision read. The subtraction then reduces exactly to
    `price_standing_bps` with `consensus_move_bps == 0` by construction: a
    board compared against itself measures the hold, not the close. Counting
    those in a CLV mean would be calling price improvement CLV, which doctrine
    forbids by name. Every live decision is `point_class == LATE_BOARD`, so
    this is a large and structural bucket, not an edge case.
  * `CLOSE_PRECEDES_DECISION` -- the last pre-game capture is OLDER than the
    decision. Calling an earlier board "the close" would invert the
    measurement's direction.
  * `CLOSING_BOARD_THIN` -- fewer than `MIN_BOOKS` books quoted that exact
    selection at the closing instant. For a spread or a total this usually
    means the market moved OFF the line we took: Over 8.0 and Over 8.5 are
    different bets, and translating between them needs a run-distribution
    model this project does not have and will not fake.
  * `DECISION_CONSENSUS_INCONSISTENT` -- the row's OWN frozen fields
    contradict each other, so only the vig-neutral split is withheld while
    `clv_bps` (which never reads them) stands. See
    `standing_exceeds_frozen_board` for the arithmetic and for the three
    ledger rows it catches.

WHAT MAY REACH A PUBLISHED ROLLUP, AND WHY THAT IS NOT THE SAME QUESTION
-------------------------------------------------------------------------
A row can be perfectly measurable and still be barred from a published
record. `docs/PRODUCT_DOCTRINE.md` §6 -- the section that names CLV the
leading indicator -- admits "only settled, published, FORWARD_TEST rows. No
backtests, replays, unpublished positions or controls." Two facts decide that
for a CLV row and NEITHER of them is visible in `clv_bps`:

  * `record_provenance` (`src.ledger.records`) says WHEN the decision was
    written relative to its own game. `replay` rows are backfills of an
    already-played date; `live_post_commencement` rows were written after
    first pitch; a row with no stamp at all predates the field and, in that
    module's own words, "must never be read as pre-commitment confirmed".
    Only `live_pre_commencement` is evidence that we said so first, which is
    the entire claim CLV is being asked to support. This module was published
    once without carrying that field onto the measurement row at all, so a
    caller could not filter it even in principle, and replay rows written up
    to 33 hours after the game were pooled into a headline that then had to
    be retracted. Every measurement row now carries `record_provenance`
    verbatim, and every rollup segments on it.
  * `closing_lead_stale` says the board being called "the close" is further
    than `CLOSING_LEAD_STALE_SECONDS` from first pitch. That flag was being
    computed per row and then discarded by the rollups, and it is not noise:
    on this ledger the stale rows mean materially worse CLV than the fresh
    ones, so pooling them moves the headline in a direction that has nothing
    to do with selection quality.

`is_publishable` is the conjunction of those two, `publishable()` is the cut,
and `report()["published"]` is that cut summarised. The contaminated pools are
still reported beside it -- deleting them would replace one silent number with
another -- but every `summarise()` that contains a row the cut would drop says
so in `publication_caveat` and carries the clean sub-summary in
`segments["publishable"]`. A caller that quotes a mean without reading either
has to ignore a field that names the problem.

COHORTS LIVE ON THE SLIP LEDGER, NOT ON THE DECISION
------------------------------------------------------
Doctrine §6 requires CLV per cohort. `DecisionRecord` deliberately carries no
`cohorts` field -- `src.ledger.records` refuses rank, cohort and agreement in
so many words, and a test pins the refusal -- because a day-level rank is not
knowable when a decision is written and, once persisted, the published slip is
the sole authority on it. An earlier version of this module read
`record.cohorts` anyway; that cut could never activate and was dead code
dressed as a measurement. `by_cohort` now joins against
`evidence/slips_v1.jsonl` through `src.engine.slip`, on the same
`(event_id, market_key, selection_id)` wager id the slip itself is keyed by.

ONE DE-VIG, REUSED
-------------------
The de-vig and the book floor come from `src.analysis.prices.snapshot`, which
is the project's only de-vig for a multi-book board. That function speaks
`away_price`/`home_price` because it was written for moneylines, while the
two-way arithmetic underneath is side-agnostic; `MARKET_SHAPES` below is the
one declared mapping from each market's own side vocabulary onto those two
slots, so a totals board can be de-vigged by the same code without a second
copy of the arithmetic existing anywhere.

READ-ONLY, NO CLOCK, NO NETWORK
---------------------------------
Every function reads the decision ledger (`src.engine.settle_slate.
load_decisions`, itself a `HashChainLedger` reader) and the multi-book store,
and nothing else. Nothing appends, settles, re-ranks or re-prices. Nothing
calls `datetime.now()`: "before first pitch" is decided against the commence
time the FEED reported, never against wall clock. Both stores may be absent --
the result is then an honestly empty report, never an exception.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

from src.analysis import families as families_mod
from src.analysis import prices
from src.board.readable import side_for_selection
from src.core import odds as odds_math
from src.engine import slip as slip_mod
from src.engine.settle_slate import load_decisions
from src.ledger import records as record_contract
from src.pipeline import snapshots
from src.report import engine_bridge

CONTROL = engine_bridge.CONTROL
MARKET_REFERENCE = engine_bridge.MARKET_REFERENCE
FORWARD_TEST = engine_bridge.FORWARD_TEST

LABEL = ("closing-line value -- the number taken versus the de-vigged "
         "consensus at the last pre-game capture. Evidence of information "
         "value, never a profit, an edge, or a win probability.")

# IMPORTED, NEVER REDECLARED. A CLV number computed over a board this project
# would refuse to call a consensus anywhere else would be a number that exists
# only because this module invented a looser floor for itself.
MIN_BOOKS = prices.MIN_BOOKS

# Probability points -> basis points. Named because `* 10000` appearing inline
# three times is three chances to write `* 1000` once.
BPS_PER_PROBABILITY_UNIT = 10_000

# How close to first pitch the closing capture has to be before the phrase
# "closing line" is unqualified.
#
# WHY NINETY MINUTES: the capture cadence in this store puts most games'
# last pre-game board inside half an hour of first pitch, but a market the
# feed stops quoting early (a suspended board, a market the provider drops
# once lineups post) can leave its last capture hours out. Such a board is
# still that market's last pre-game word and is still the honest close -- the
# definition does not move, exactly as `snapshots.CLOSING_STALE_SECONDS` does
# not move which observation is the close. Ninety minutes is roughly three
# capture cycles: below it a gap is ordinary cadence, above it the board is
# meaningfully older than the market that actually closed, and a reader
# weighting these numbers deserves to know which they are looking at. This
# flag NEVER excludes a measurement; it is recorded on it, and the publication
# cut below is the only place it decides anything.
#
# PINNED BY TEST, deliberately. This number is the difference between "a
# quarter of the rows call a six-hour-old board the close" and "none of them
# do": widening it to eight hours takes `close_stale` on the live ledger from
# 265 rows to zero without changing one measurement. A threshold nobody's test
# pins is a threshold that can be tuned until the answer is friendly, so
# tests/test_report_clv.py pins both this constant and the behaviour at 85 and
# 95 minutes against hardcoded stamps rather than against this name.
CLOSING_LEAD_STALE_SECONDS = 90 * 60

SOURCE = prices.SOURCE

# ---------------------------------------------------------------------------
# Publication eligibility (doctrine section 6)
# ---------------------------------------------------------------------------

# IMPORTED, NEVER REDECLARED -- `src.ledger.records` mints these values and
# validates them on construction. Re-typing the strings here would let this
# module and the record contract drift apart silently, and the one that would
# then be wrong is the filter standing between a replay row and a headline.
PROVENANCE_PRE_COMMITMENT = record_contract.RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT
PROVENANCE_POST_COMMENCEMENT = record_contract.RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT
PROVENANCE_REPLAY = record_contract.RECORD_PROVENANCE_REPLAY

# The None case, given a NAME so it can be counted rather than silently
# grouped with a real value. `records.py`: a record with no provenance stamp
# predates the field and "carries no evidence either way -- it must never be
# read as pre-commitment confirmed". Keeping that bucket separate from
# `replay` is the difference between saying a row was backfilled and saying
# nobody knows, and only one of those is true of it.
PROVENANCE_UNSTAMPED = "unstamped"

# The one provenance doctrine section 6 admits to a published record. Stated
# as an allowlist rather than a blocklist on purpose: a provenance value added
# to `records.py` tomorrow must be argued INTO a published rollup rather than
# accidentally inherited by one.
PUBLISHABLE_PROVENANCE = frozenset({PROVENANCE_PRE_COMMITMENT})

# Segment names. Two independent PARTITIONS of a group -- every row falls in
# exactly one provenance segment and exactly one close segment -- plus the
# publication cut, which is the intersection of the two admissible ones.
# Partitions rather than a loose bag of flags because a partition can be
# CHECKED: the segment counts must add back to `n_decisions`, and a test pins
# that they do, so no row can fall out of the accounting unnoticed.
SEG_PROVENANCE_PRE_COMMITMENT = "provenance_pre_commitment"
SEG_PROVENANCE_POST_COMMENCEMENT = "provenance_post_commencement"
SEG_PROVENANCE_REPLAY = "provenance_replay"
SEG_PROVENANCE_UNSTAMPED = "provenance_unstamped"
SEG_CLOSE_FRESH = "close_fresh"
SEG_CLOSE_STALE = "close_stale"
SEG_CLOSE_NOT_ESTABLISHED = "close_not_established"
SEG_PUBLISHABLE = "publishable"

PROVENANCE_SEGMENTS = {
    PROVENANCE_PRE_COMMITMENT: SEG_PROVENANCE_PRE_COMMITMENT,
    PROVENANCE_POST_COMMENCEMENT: SEG_PROVENANCE_POST_COMMENCEMENT,
    PROVENANCE_REPLAY: SEG_PROVENANCE_REPLAY,
    PROVENANCE_UNSTAMPED: SEG_PROVENANCE_UNSTAMPED,
}

SEGMENT_NOTES = {
    SEG_PROVENANCE_PRE_COMMITMENT: (
        "written by a live slate before this game's own first pitch -- the "
        "only provenance that is evidence the number was taken before the "
        "market closed, and the only one doctrine section 6 admits"),
    SEG_PROVENANCE_POST_COMMENCEMENT: (
        "written by a live slate AFTER first pitch had already passed. Not a "
        "pre-commitment, so not publishable; reported rather than dropped so "
        "the count is visible"),
    SEG_PROVENANCE_REPLAY: (
        "a deliberate replay/backfill of an already-played date. Honest as a "
        "replay and worthless as a leading indicator: doctrine section 6 "
        "admits no replays to a published record"),
    SEG_PROVENANCE_UNSTAMPED: (
        "the record carries no record_provenance at all. It predates the "
        "field and carries no evidence either way; src.ledger.records says it "
        "must never be read as pre-commitment confirmed, so it is not "
        "publishable -- and it is NOT counted as a replay either, because "
        "that would be asserting something nobody knows"),
    SEG_CLOSE_FRESH: (
        f"the closing board is within {CLOSING_LEAD_STALE_SECONDS // 60} "
        "minutes of first pitch, so calling it 'the close' is unqualified"),
    SEG_CLOSE_STALE: (
        f"the closing board is more than {CLOSING_LEAD_STALE_SECONDS // 60} "
        "minutes before first pitch. It is still that market's last pre-game "
        "word and still the honest close, but it is measurably not the board "
        "the market ended on, and on this ledger the stale rows do not carry "
        "the same mean as the fresh ones"),
    SEG_CLOSE_NOT_ESTABLISHED: (
        "no closing board was established for this row at all, so its "
        "freshness is not a fact anyone has"),
    SEG_PUBLISHABLE: (
        "pre-commitment provenance AND a fresh close: the rows doctrine "
        "section 6 permits in a published CLV record. This is the cut; every "
        "other segment here is diagnostic"),
}

PUBLICATION_RULE = (
    "A published CLV rollup admits only rows whose record_provenance is "
    f"{PROVENANCE_PRE_COMMITMENT!r} and whose closing board is within "
    f"{CLOSING_LEAD_STALE_SECONDS // 60} minutes of first pitch "
    "(docs/PRODUCT_DOCTRINE.md section 6: no backtests, replays, unpublished "
    "positions or controls). Replay, post-commencement and unstamped rows, "
    "and stale closes, are reported in `segments` and never pooled into "
    "`published`.")

# ---------------------------------------------------------------------------
# Named absences. Every gap says WHY.
# ---------------------------------------------------------------------------

NOT_A_BET = "NOT_A_BET"
NO_PRICE_TAKEN = "NO_PRICE_TAKEN"
SIDE_NOT_RECOVERABLE = "SIDE_NOT_RECOVERABLE"
MARKET_NOT_CAPTURED = "MARKET_NOT_CAPTURED"
EVENT_NOT_IN_STORE = "EVENT_NOT_IN_STORE"
COMMENCE_TIME_UNKNOWN = "COMMENCE_TIME_UNKNOWN"
DECISION_TIME_UNPARSEABLE = "DECISION_TIME_UNPARSEABLE"
NO_CAPTURE_BEFORE_COMMENCE = "NO_CAPTURE_BEFORE_COMMENCE"
CLOSING_BOARD_THIN = "CLOSING_BOARD_THIN"
CLOSING_SIDE_UNPRICEABLE = "CLOSING_SIDE_UNPRICEABLE"
CLOSING_BOARD_IS_DECISION_BOARD = "CLOSING_BOARD_IS_DECISION_BOARD"
CLOSE_PRECEDES_DECISION = "CLOSE_PRECEDES_DECISION"
PRICE_NOT_CONVERTIBLE = "PRICE_NOT_CONVERTIBLE"

# Absences that apply only to the vig-neutral companion measure, which needs
# the decision's own frozen consensus as well as the closing one.
DECISION_CONSENSUS_MISSING = "DECISION_CONSENSUS_MISSING"
DECISION_BOARD_THIN = "DECISION_BOARD_THIN"
DECISION_BOOK_COUNT_UNKNOWN = "DECISION_BOOK_COUNT_UNKNOWN"
DECISION_CONSENSUS_INCONSISTENT = "DECISION_CONSENSUS_INCONSISTENT"

# Absences of a whole cut, not of one row.
NO_SLIP_LEDGER = "NO_SLIP_LEDGER"
NO_SLIP_PICK_MEASURED = "NO_SLIP_PICK_MEASURED"

ABSENCE_REASONS = {
    NOT_A_BET: (
        "the engine refused this candidate rather than taking a price, so "
        "there is no number to compare against the close"),
    NO_PRICE_TAKEN: (
        "the record carries no price_american, so nothing was taken at any "
        "number and CLV is undefined rather than zero"),
    SIDE_NOT_RECOVERABLE: (
        "the selection_id does not re-derive to any side declared for this "
        "market in src.board.ids.MARKET_CATALOGUE, so which side of the "
        "closing board to read cannot be established"),
    MARKET_NOT_CAPTURED: (
        "the multi-book store has never captured this market, so no closing "
        "board for this selection exists to compare against"),
    EVENT_NOT_IN_STORE: (
        "no pre-game multi-book row carries this decision's event_id, so the "
        "closing board for this game was never captured"),
    COMMENCE_TIME_UNKNOWN: (
        "the store reports no commence_time for this event, so 'strictly "
        "before first pitch' cannot be evaluated and no capture may be "
        "called a close"),
    DECISION_TIME_UNPARSEABLE: (
        "the decision's own timestamp cannot be parsed, so whether the "
        "closing capture came after it cannot be established"),
    NO_CAPTURE_BEFORE_COMMENCE: (
        "every capture of this selection is at or after first pitch; an "
        "in-play board is a different product and is never a closing price"),
    CLOSING_BOARD_THIN: (
        f"fewer than {MIN_BOOKS} books quoted this exact selection at the "
        "closing instant -- for a spread or total this usually means the "
        "market closed on a DIFFERENT line than the one taken, and "
        "translating a price across lines needs a run-distribution model "
        "this project does not have"),
    CLOSING_SIDE_UNPRICEABLE: (
        "the closing board carries no usable price on the side taken, so it "
        "has no consensus for that side"),
    CLOSING_BOARD_IS_DECISION_BOARD: (
        "the last pre-game capture is the same instant the decision read, so "
        "the difference is the book's hold -- price standing -- and not "
        "closing-line value; counting it would be calling price improvement "
        "CLV"),
    CLOSE_PRECEDES_DECISION: (
        "the last pre-game capture is older than the decision itself, so "
        "calling it 'the close' would measure the market backwards"),
    PRICE_NOT_CONVERTIBLE: (
        "the taken price is not a valid American price, so no implied "
        "probability can be derived from it"),
    DECISION_CONSENSUS_MISSING: (
        "the decision froze no consensus_fair, so the vig-neutral move "
        "cannot be measured against the board the decision actually saw"),
    DECISION_BOARD_THIN: (
        f"the decision was frozen against fewer than {MIN_BOOKS} books, so "
        "its consensus_fair is that handful's opinion and not a market's"),
    DECISION_BOOK_COUNT_UNKNOWN: (
        "the record carries no books_at_decision, so how many books stood "
        "behind its consensus_fair is unknown. Saying the board was THIN "
        "would be a claim about data nobody has -- the honest statement is "
        "ignorance, and it withholds the vig-neutral split for the same "
        "reason a thin board does without borrowing that board's story"),
    DECISION_CONSENSUS_INCONSISTENT: (
        "the frozen consensus_fair exceeds the taken price's implied "
        "probability by more than the frozen board's own dispersion, which "
        "no single board can produce -- consensus_fair and price_american on "
        "this row are not describing the same market, so the vig-neutral "
        "split would be arithmetic on two unrelated numbers"),
    NO_SLIP_LEDGER: (
        "the published-slip ledger (src.engine.slip) holds no slip, so no "
        "pick has ever been assigned a cohort and a per-cohort CLV cut would "
        "be a cut over an empty field rather than a result"),
    NO_SLIP_PICK_MEASURED: (
        "slips exist, but no published pick carrying a cohort tag appears "
        "among these measurements, so every cohort bucket would be empty. An "
        "empty bucket reads as 'measured and found nothing'; this says "
        "instead that the join found nothing to measure"),
}

# Reported alongside every mean, because the rows are not independent draws.
INDEPENDENCE_NOTE = (
    "These rows are NOT independent observations. Many systems decide the "
    "same game off the same board, and near-duplicate genomes decide alike by "
    "construction (docs/PRODUCT_DOCTRINE.md amendment 9), so the naive "
    "standard error below is a LOWER BOUND on the true uncertainty. Read "
    "n_games beside n_decisions before reading any mean.")

VIG_NOTE = (
    "clv_bps subtracts a de-vigged closing consensus from a taken price that "
    "still carries the book's margin, so it is biased NEGATIVE by roughly "
    "half the hold before any line has moved. consensus_move_bps has the vig "
    "removed on both sides of the subtraction and is the number to compare "
    "systems on; price_standing_bps is the execution-quality remainder and is "
    "emphatically not an edge. The three satisfy "
    "clv_bps = consensus_move_bps + price_standing_bps exactly.")


# ---------------------------------------------------------------------------
# The one declared mapping from a market's sides onto the de-vig's two slots
# ---------------------------------------------------------------------------

class SideShape(NamedTuple):
    """How one side of one market is read out of a multi-book store row.

    `slot` is the key `src.analysis.prices.snapshot` files this side under.
    That function's vocabulary is away/home because it was written for
    moneylines; the two-way de-vig underneath does not care what the sides
    are called. Declaring the mapping here, once, is what lets a totals board
    reuse the project's single de-vig instead of growing a second one.
    """

    price_field: str
    line_field: str | None  # the store field carrying THIS side's line
    slot: str


class MarketShape(NamedTuple):
    """How one market's rows are recognised and read in the multi-book store.

    `store_market` is the value of a row's `market` key -- None for h2h,
    whose rows deliberately keep the legacy shape with no such key
    (`snapshots.multibook_rows`). Matching on it is what stops a book's
    totals row from being read as its moneyline, the bug that made every
    board on /odds report "9 books, no consensus" on 2026-09-07.
    """

    store_market: str | None
    sides: dict


MARKET_SHAPES = {
    "h2h": MarketShape(
        store_market=None,
        sides={
            "away": SideShape("away_price", None, "away"),
            "home": SideShape("home_price", None, "home"),
        }),
    "spreads": MarketShape(
        store_market="spreads",
        sides={
            # A spread's line is part of its identity (src.board.ids), and the
            # two sides carry OPPOSITE lines on the same row, so each side
            # matches on its own line field. A decision on the home -1.5 and a
            # decision on the away +1.5 are different selections that happen
            # to be quoted by the same row.
            "away": SideShape("away_price", "away_line", "away"),
            "home": SideShape("home_price", "home_line", "home"),
        }),
    "totals": MarketShape(
        store_market="totals",
        sides={
            # Both sides share one line field: a totals row is Over/Under the
            # same number. The over/under -> away/home slot assignment is
            # arbitrary and declared ONLY here, so no caller can pick a
            # different one.
            "over": SideShape("over_price", "total", "away"),
            "under": SideShape("under_price", "total", "home"),
        }),
}


class ClvError(ValueError):
    """Raised for a programming error in this module's own inputs -- an
    unknown market shape reached past the guard, a side that is not in the
    shape table. Never raised for missing data: missing data is an absence."""


def _moment(value):
    """A UTC datetime for an ISO-8601 stamp, or None when it will not parse.

    Both stores mix suffix styles ('...Z' on commence times, '+00:00' on
    observation stamps), so these strings cannot be ordered lexicographically
    across the two -- the comparison has to run on real datetimes. This repo's
    two existing parsers (`snapshots._parse`, `asof._parse_utc`) are private to
    their modules; reaching across a module boundary for a private name to save
    six lines would couple this file to something its owner is free to rename.

    Returns None rather than raising: an unparseable stamp is missing data,
    and missing data in this module is always an absence with a reason.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _field(obj, name, default=None):
    """`obj.name` or `obj[name]` -- so every function here accepts a real
    `DecisionRecord` (what `load_decisions` returns) or a plain dict (what a
    test fixture builds), the same tolerance `engine_bridge._field` grants."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _absent(reason, **extra) -> dict:
    """An absence, always carrying its own explanation.

    The reason token and the sentence travel together on purpose: a caller
    that renders only the token still has the sentence available, and a
    reason that has no entry in `ABSENCE_REASONS` is a bug here rather than
    an unexplained gap in the data, so it raises.
    """
    if reason not in ABSENCE_REASONS:
        raise ClvError(f"unnamed absence {reason!r} -- every gap must say why")
    out = {"absence": reason, "absence_reason": ABSENCE_REASONS[reason]}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# The pre-game index: what a closing board may be drawn from
# ---------------------------------------------------------------------------

def pregame_index(rows=None) -> dict:
    """`{event_id: {"rows": [...], "commence_time": str|None}}` for the store.

    TWO INDEPENDENT PRE-GAME GUARDS, ON PURPOSE.

    First, `snapshots.pregame_rows` -- this project's single definition of
    "observed before first pitch", which checks each row against the
    commence_time THAT ROW carried. That is the point-in-time-correct test:
    it asks what the feed said first pitch was at the moment we looked.

    Second, an event-level cutoff at the commence_time from the event's most
    recently observed row -- the feed's final word on first pitch. The feed
    revises commence times by a minute or two as a game firms up (30 of 133
    events in this store carry more than one). When a revision moves first
    pitch EARLIER, a row that passed the first guard against a stale, later
    commence time is in fact a post-commencement capture. Only the second
    guard catches that, and a post-commencement board presented as a close is
    exactly the corruption this module exists to refuse.

    Rows with no event_id are dropped: an unattributable row can only ever be
    filed against the wrong game.

    Tolerates a missing store -- `snapshots.read_multibook` returns [] for a
    missing file, and any other read failure yields an empty index rather than
    an exception, since a container that has never captured must still be able
    to report "nothing measurable" instead of crashing.
    """
    try:
        source = snapshots.read_multibook() if rows is None else list(rows)
    except Exception:
        return {}

    # The feed's LAST word on first pitch, taken from the newest observation of
    # each event -- read from the RAW rows, not the pre-game ones, because the
    # newest observation of a started game is in-play and is precisely the row
    # most likely to carry the corrected time.
    final_commence: dict = {}
    for row in source:
        event_id = row.get("event_id")
        stamp = row.get("observed_utc")
        if not event_id or not stamp:
            continue
        seen = final_commence.get(event_id)
        if seen is None or stamp > seen[0]:
            final_commence[event_id] = (stamp, row.get("commence_time"))

    index: dict = {}
    for row in snapshots.pregame_rows(source):
        event_id = row.get("event_id")
        if not event_id:
            continue
        entry = index.get(event_id)
        if entry is None:
            entry = {"rows": [],
                     "commence_time": final_commence.get(event_id, (None, None))[1]}
            index[event_id] = entry
        entry["rows"].append(row)

    for event_id, entry in index.items():
        cutoff = _moment(entry["commence_time"])
        if cutoff is None:
            # No usable final commence time: the second guard cannot run, and
            # a board that cannot be shown to be pre-game is not served as one.
            entry["rows"] = []
            continue
        entry["rows"] = [r for r in entry["rows"]
                         if (m := _moment(r.get("observed_utc"))) is not None
                         and m < cutoff]
    return index


# ---------------------------------------------------------------------------
# The closing board for ONE selection
# ---------------------------------------------------------------------------

def closing_board(entry, market_key, side, line) -> dict:
    """This market's last pre-game board, cut to this selection, or an absence.

    `entry` is one `pregame_index` value. The returned board is
    `{"quotes": [{ts, book, away_price, home_price}], "observed_utc",
    "commence_time", "lead_seconds", "lead_stale", "source"}` -- the same
    `{book, away_price, home_price}` shape `src.analysis.prices.snapshot`
    consumes, with this market's sides mapped onto its two slots by
    `MARKET_SHAPES`.

    THE CLOSING INSTANT IS CHOSEN BEFORE THE LINE IS CHECKED, AND THAT ORDER
    IS THE WHOLE DESIGN. The instant is this MARKET's last pre-game capture
    for this game; the line filter is then applied WITHIN that instant. Doing
    it the other way round -- filtering to the taken line first and then
    taking the newest surviving instant -- silently answers a totals bet taken
    at 8.0 with a board from three hours earlier when the market closed at
    8.5, and calls that board "the close". Doctrine forbids exactly that
    sentence: a late board is not the closing price unless it genuinely is
    the closing price. Under this order a market that moved off the taken
    line comes back `CLOSING_BOARD_THIN` instead, which is the true statement
    -- the market closed on a different bet.

    The instant is chosen per MARKET rather than per game because a market
    the feed stops quoting early still has a last pre-game word of its own,
    and refusing it because some other market on the same game was captured
    later would throw away real evidence. How much older it is is recorded as
    `lead_seconds`/`lead_stale`, never hidden.

    Within the instant, `prices.latest_instant` applies the same
    newest-row-per-book rule every other board in this project is built with.
    """
    shape = MARKET_SHAPES.get(market_key)
    if shape is None:
        return _absent(MARKET_NOT_CAPTURED, market_key=market_key)
    if side not in shape.sides:
        raise ClvError(
            f"side {side!r} is not declared for market {market_key!r} in "
            "MARKET_SHAPES -- the catalogue and this table disagree")

    commence = (entry or {}).get("commence_time")
    if _moment(commence) is None:
        return _absent(COMMENCE_TIME_UNKNOWN)

    taken = shape.sides[side]
    other_side = next(s for s in shape.sides if s != side)
    other = shape.sides[other_side]

    in_market = [row for row in (entry or {}).get("rows") or ()
                 if row.get("market") == shape.store_market]
    if not in_market:
        return _absent(NO_CAPTURE_BEFORE_COMMENCE, market_key=market_key)

    # Ordered on parsed instants, never on the strings. The two stores this
    # project reads write '...Z' and '...+00:00' for the same moment, and a
    # lexicographic max over a mixture of the two picks the wrong capture.
    stamped = [(m, row.get("observed_utc")) for row in in_market
               if (m := _moment(row.get("observed_utc"))) is not None]
    if not stamped:
        return _absent(NO_CAPTURE_BEFORE_COMMENCE, market_key=market_key)
    observed = max(stamped)[1]

    quotes = []
    for row in in_market:
        if (row.get("observed_utc") or "") != observed:
            continue
        if taken.line_field is not None and row.get(taken.line_field) != line:
            continue
        quote = {"ts": row.get("observed_utc"), "book": row.get("book")}
        quote[f"{taken.slot}_price"] = row.get(taken.price_field)
        quote[f"{other.slot}_price"] = row.get(other.price_field)
        quotes.append(quote)

    board = prices.latest_instant(quotes)
    if not board:
        # The market WAS captured before first pitch; no book at its closing
        # instant quoted the line taken. That is a thin closing board of size
        # zero, not a missing capture, and saying so is the difference between
        # "we never saw the close" and "the market closed on a different bet".
        return _absent(CLOSING_BOARD_THIN, market_key=market_key, line=line,
                       detail=("0 books quoted this line at the closing "
                               "instant; the market closed on another number"))
    lead = (_moment(commence) - _moment(observed)).total_seconds()
    return {"quotes": board, "observed_utc": observed,
            "commence_time": commence, "lead_seconds": lead,
            "lead_stale": lead > CLOSING_LEAD_STALE_SECONDS,
            "source": SOURCE}


def closing_consensus(board, market_key, side) -> dict:
    """The de-vigged closing probability for `side`, or an absence.

    The de-vig and the book floor are `src.analysis.prices.snapshot`'s, not
    this module's. `snapshot` returns `{"skipped": ...}` below `MIN_BOOKS`,
    which becomes `CLOSING_BOARD_THIN` here -- a thin board produces a story,
    never a number.
    """
    shape = MARKET_SHAPES.get(market_key)
    if shape is None:
        return _absent(MARKET_NOT_CAPTURED, market_key=market_key)
    if side not in shape.sides:
        raise ClvError(
            f"side {side!r} is not declared for market {market_key!r}")

    section = prices.snapshot((board or {}).get("quotes") or [])
    if "skipped" in section:
        return _absent(CLOSING_BOARD_THIN, detail=section["skipped"])
    detail = section["sides"].get(shape.sides[side].slot) or {}
    if "skipped" in detail or detail.get("consensus_probability") is None:
        return _absent(CLOSING_SIDE_UNPRICEABLE,
                       detail=detail.get("skipped"))
    return {"closing_probability": detail["consensus_probability"],
            "books": section["dispersion"]["books"],
            "observed_utc": board.get("observed_utc"),
            "lead_seconds": board.get("lead_seconds"),
            "lead_stale": board.get("lead_stale")}


def standing_exceeds_frozen_board(price_standing_bps, friction) -> bool:
    """True when a row's own frozen fields cannot both describe one board.

    THE ARITHMETIC. `DecisionRecord.consensus_fair` is the MEAN of the
    per-book DE-VIGGED probabilities for the taken selection
    (`src.engine.snapshot.PricedBoard.consensus`); `price_american` is the
    BEST price on that same board, so its implied probability is the SMALLEST
    raw implied probability any book quoted; `friction["dispersion"]` is the
    RANGE of those raw implied probabilities (`PricedBoard.friction` -- raw,
    not de-vigged, which is what makes this bound hold without assuming a
    de-vig method). De-vigging only ever lowers a probability, so every
    per-book fair value is at most that book's raw value, and therefore

        consensus_fair <= max_book(raw) = min_book(raw) + dispersion
        =>  price_standing_bps = (consensus_fair - implied) <= dispersion

    A row that breaks that inequality is not an unusual board; it is two
    numbers that came from different boards -- a consensus for one line and a
    price for another, or a book set that changed underneath. Three rows on
    this ledger break it, two of them by more than 1,000bps on a run line
    whose real de-vigged home probability was 0.379 while the row froze
    0.508.

    ONE-SIDED, DELIBERATELY, AND PINNED BY TEST. The mirror-image bound needs
    the LARGEST per-book margin and the record freezes only the MEAN one
    (`friction["vig"]`), so a lower bound built from it would flag honest rows
    whose best price happened to come from the most-vigged book. Refusing to
    invent that threshold means a symmetrically-corrupt row on the other side
    survives this check; it is named in this module's report rather than
    filtered by a number nobody can justify.

    Because the asymmetry is a judgement rather than arithmetic, it is the
    line most likely to be "tidied" into `abs(price_standing_bps) >
    dispersion * ...` by someone who reads it as a symmetry bug. That edit
    would start withholding the vig-neutral split from every row whose taken
    price merely beat its own frozen consensus by a wide margin -- a large,
    ordinary population -- on the strength of a bound this record cannot
    support. tests/test_report_clv.py pins a large NEGATIVE standing as NOT a
    contradiction for exactly that reason.

    The comparison is strict (`>`): a standing exactly equal to the board's
    own dispersion is the boundary the inequality above permits, not a
    violation of it.

    Returns False (i.e. "no contradiction shown") when there is no dispersion
    to check against -- an unrunnable check is not a failed one.
    """
    dispersion = (friction or {}).get("dispersion")
    if dispersion is None or price_standing_bps is None:
        return False
    return price_standing_bps > dispersion * BPS_PER_PROBABILITY_UNIT


# ---------------------------------------------------------------------------
# One decision
# ---------------------------------------------------------------------------

def measure_decision(record, index) -> dict:
    """CLV for one frozen decision, or a named absence saying why there is none.

    Pure: everything it needs is `record` plus one `pregame_index`. It never
    re-derives a decision's own numbers -- the taken price, the frozen
    consensus, the book count and the side all come off the record, and the
    ONLY thing computed from the store is the closing board.

    Returns a dict that always carries the joining identity (system, class,
    event, market, side, price) so a rejected row is still reportable.
    `clv_bps` and a row-level `absence` NEVER both appear -- that is the
    invariant every rollup here relies on. Two things deliberately do coexist
    with an absence, because both are observations rather than the metric:
    the closing board's own facts (`closing_probability`, `closing_books`,
    `seconds_from_decision_to_close`), which are what let a reader see WHY a
    row was refused instead of taking the token on trust; and `move_absence`,
    which withholds only the vig-neutral split while a real `clv_bps` stands.
    """
    system_id = _field(record, "system_id")
    market_key = _field(record, "market_key")
    line = _field(record, "line")
    price = _field(record, "price_american")
    verdict = _field(record, "verdict")

    base = {
        "system_id": system_id,
        "system_class": engine_bridge.system_class(system_id),
        "event_id": _field(record, "event_id"),
        "market_key": market_key,
        # Carried so a caller can join this row to the published slip, which
        # is the sole authority on cohort and rank. `selection_id` alone is
        # not a wager id (every home moneyline in the league shares one); the
        # triple with event_id and market_key is -- see `_wager_id`.
        "selection_id": _field(record, "selection_id"),
        "line": line,
        "side": None,
        "verdict": verdict,
        "decision_utc": _field(record, "decision_utc"),
        "price_american": price,
        "book": _field(record, "book"),
        # WHEN this record was written relative to its own game, verbatim off
        # the record and never inferred. Carried on EVERY row including the
        # absences: a caller filtering a published rollup needs it on rows
        # this module refused as much as on the ones it measured, and the
        # version of this module that omitted it is why 33-hour-late replay
        # rows reached a headline that had to be retracted.
        "record_provenance": _field(record, "record_provenance"),
        "clv_bps": None,
        "consensus_move_bps": None,
        "price_standing_bps": None,
        "closing_probability": None,
        "closing_observed_utc": None,
        "closing_books": None,
        "closing_lead_seconds": None,
        "closing_lead_stale": None,
        "seconds_from_decision_to_close": None,
        "move_absence": None,
        "move_absence_reason": None,
    }

    # A refusal is not a bet. It is a real, deliberate ledger row and it is
    # counted -- as an absence with its own reason, never as a CLV of zero.
    if verdict != "play":
        return {**base, **_absent(NOT_A_BET, verdict=verdict)}
    if price is None:
        return {**base, **_absent(NO_PRICE_TAKEN)}

    side = side_for_selection(market_key, _field(record, "selection_id"), line)
    if side is None:
        return {**base, **_absent(SIDE_NOT_RECOVERABLE)}
    base["side"] = side

    if market_key not in MARKET_SHAPES:
        return {**base, **_absent(MARKET_NOT_CAPTURED, market_key=market_key)}

    decided_at = _moment(_field(record, "decision_utc"))
    if decided_at is None:
        return {**base, **_absent(DECISION_TIME_UNPARSEABLE)}

    entry = (index or {}).get(_field(record, "event_id"))
    if not entry:
        return {**base, **_absent(EVENT_NOT_IN_STORE)}

    board = closing_board(entry, market_key, side, line)
    if "absence" in board:
        return {**base, **board}

    consensus = closing_consensus(board, market_key, side)
    if "absence" in consensus:
        return {**base, **consensus}

    closed_at = _moment(consensus["observed_utc"])
    gap = (closed_at - decided_at).total_seconds()
    base.update({
        "closing_probability": consensus["closing_probability"],
        "closing_observed_utc": consensus["observed_utc"],
        "closing_books": consensus["books"],
        "closing_lead_seconds": consensus["lead_seconds"],
        "closing_lead_stale": consensus["lead_stale"],
        "seconds_from_decision_to_close": gap,
    })

    # The two degenerate orderings. Both are refusals, not small numbers: one
    # measures the hold and calls it CLV, the other measures the market
    # backwards. See the module docstring.
    if gap < 0:
        return {**base, **_absent(CLOSE_PRECEDES_DECISION)}
    if gap == 0:
        return {**base, **_absent(CLOSING_BOARD_IS_DECISION_BOARD)}

    try:
        implied = odds_math.american_to_probability(price)
    except odds_math.OddsError:
        return {**base, **_absent(PRICE_NOT_CONVERTIBLE, price_american=price)}

    base["clv_bps"] = round(
        (consensus["closing_probability"] - implied)
        * BPS_PER_PROBABILITY_UNIT, 4)

    # The vig-neutral companion, which needs the board the decision itself
    # saw. Its absence is recorded SEPARATELY: a row can have a real clv_bps
    # and no consensus_move_bps, and collapsing the two absences would hide
    # which of the two numbers is missing.
    frozen = _field(record, "consensus_fair")
    books_at_decision = _field(record, "books_at_decision")
    standing = (None if frozen is None
                else (frozen - implied) * BPS_PER_PROBABILITY_UNIT)
    if frozen is None:
        move_absence = DECISION_CONSENSUS_MISSING
    elif books_at_decision is None:
        # NOT folded in with the thin-board case. Both withhold the same
        # number, but DECISION_BOARD_THIN's sentence asserts the board was
        # frozen against fewer than MIN_BOOKS books, and on a row carrying no
        # count at all that sentence is a claim about data nobody has. A
        # named ignorance and a named finding are different statements and
        # this module does not get to substitute one for the other.
        move_absence = DECISION_BOOK_COUNT_UNKNOWN
    elif books_at_decision < MIN_BOOKS:
        move_absence = DECISION_BOARD_THIN
    elif standing_exceeds_frozen_board(standing, _field(record, "friction")):
        move_absence = DECISION_CONSENSUS_INCONSISTENT
    else:
        move_absence = None

    if move_absence is not None:
        base["move_absence"] = move_absence
        base["move_absence_reason"] = ABSENCE_REASONS[move_absence]
    else:
        base["consensus_move_bps"] = round(
            (consensus["closing_probability"] - frozen)
            * BPS_PER_PROBABILITY_UNIT, 4)
        base["price_standing_bps"] = round(standing, 4)
    return base


def measure(decisions=None, rows=None, index=None) -> list:
    """`measure_decision` over a whole ledger, in ledger order.

    `decisions` defaults to `src.engine.settle_slate.load_decisions()`, which
    is the same `HashChainLedger` read every other report surface uses (it
    already skips the genesis row and the correction rows, neither of which is
    a decision). `rows`/`index` let a caller supply the store, so a report that
    reads the 31MB multi-book file once can hand the index to several cuts.

    Tolerates an unreadable decision ledger the same way `pregame_index`
    tolerates a missing store: an empty list, never an exception.
    """
    if decisions is None:
        try:
            decisions = load_decisions()
        except Exception:
            return []
    if index is None:
        index = pregame_index(rows)
    return [measure_decision(record, index) for record in decisions or ()]


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------

def _mean(values):
    return sum(values) / len(values) if values else None


def _median(values):
    """The middle value, or the mean of the two middle values on an even list.

    Reported BESIDE the mean, not instead of it, because the two disagreeing
    is itself the finding: CLV rows here are heavily skewed by the vig term
    and a handful of large moves, and a mean that has drifted away from the
    median is a mean carried by its tail. Sorting a copy rather than the
    caller's list matters -- `summarise` hands in a list it built from the
    measurement rows, and a rollup that reordered its own input would make
    every downstream cut depend on which rollup ran first.
    """
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _stderr_naive(values):
    """Standard error of the mean, ASSUMING independent draws -- which these
    are not (see INDEPENDENCE_NOTE). The name carries the caveat so a caller
    cannot quote the number without quoting the qualifier.

    THE SAMPLE variance (n-1), then divided by n again for the error OF THE
    MEAN. Both halves are load-bearing and both are easy to get quietly
    wrong: dividing by n instead of n-1 understates the spread of a small
    sample, which is every sample this project currently has, and returning
    the standard deviation instead of the SEM overstates the uncertainty of
    the mean by a factor of sqrt(n). Neither mistake changes a sign or throws,
    so neither is visible in a rendered table -- the whole published
    conclusion ("7 of 11 positive, no signal") rests on this number, so
    tests/test_report_clv.py pins it against hand-computed values rather than
    against a re-derivation.

    None below n=2: the standard error of a single observation is not zero,
    it is undefined, and zero is a real value that would read as certainty.
    """
    if len(values) < 2:
        return None
    mean = _mean(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return (variance / len(values)) ** 0.5


# ---------------------------------------------------------------------------
# Publication segments
# ---------------------------------------------------------------------------

def provenance_segment(row) -> str:
    """Which provenance partition one measurement row falls in.

    An unrecognised value maps to the unstamped bucket rather than raising:
    `records.py` validates provenance on construction, so a value this table
    does not know can only reach here from a hand-built row, and the
    conservative answer for an unknown stamp is the same as for no stamp --
    not publishable, and not asserted to be a replay.
    """
    value = (row or {}).get("record_provenance")
    return PROVENANCE_SEGMENTS.get(value, SEG_PROVENANCE_UNSTAMPED)


def close_segment(row) -> str:
    """Which close-freshness partition one measurement row falls in.

    Three buckets, not two. `closing_lead_stale` is None on every row that
    never got a closing board at all, and calling those "fresh" would count a
    row with no close as a well-timed one.
    """
    stale = (row or {}).get("closing_lead_stale")
    if stale is None:
        return SEG_CLOSE_NOT_ESTABLISHED
    return SEG_CLOSE_STALE if stale else SEG_CLOSE_FRESH


def is_publishable(row) -> bool:
    """True when doctrine section 6 permits this row in a published rollup.

    THREE conditions, never fewer: a fresh close on a replay row is still a
    replay, a pre-commitment decision measured against a six-hour-old board
    is still not measured against the close, and a CONTROL or
    MARKET_REFERENCE row is still an instrument, no matter how fresh its
    provenance or close. See PUBLICATION_RULE, whose own text ("no
    backtests, replays, unpublished positions or controls") named this third
    condition before any code enforced it -- measured on the real ledger,
    the gap let 938 MARKET_REFERENCE and 469 CONTROL rows outnumber 196
    genuine FORWARD_TEST rows 7-to-1 in what the docstring called "the cut."
    A control's price-standing is the board agreeing with itself
    (src/report/engine_bridge.py says exactly this about "engine interest");
    pooling it into a CLV number meant to demonstrate genome-level edge
    would publish the market's own calibration as if it were evidence for
    the product.

    This says nothing about whether the row was measurable -- an unmeasurable
    pre-commitment row with a fresh close is publishable and contributes its
    absence to the published rollup, which is the honest accounting.
    """
    return (provenance_segment(row) in
            (PROVENANCE_SEGMENTS[p] for p in PUBLISHABLE_PROVENANCE)
            and close_segment(row) == SEG_CLOSE_FRESH
            and (row.get("system_class") or FORWARD_TEST) == FORWARD_TEST)


def publishable(measurements) -> list:
    """The rows a published CLV rollup may contain, in input order."""
    return [row for row in measurements or () if is_publishable(row)]


def segments(measurements) -> dict:
    """`{segment_name: [rows]}` -- both partitions plus the publication cut.

    Every segment name in SEGMENT_NOTES is present even when empty, so a
    reader can tell "this ledger holds no replays" apart from "this rollup
    forgot to look". The two partitions each sum to the whole; `publishable`
    deliberately overlaps them both, being their intersection.
    """
    out: dict = {name: [] for name in SEGMENT_NOTES}
    for row in measurements or ():
        out[provenance_segment(row)].append(row)
        out[close_segment(row)].append(row)
        if is_publishable(row):
            out[SEG_PUBLISHABLE].append(row)
    return out


def summarise(measurements, *, segment=True) -> dict:
    """CLV statistics for one group of measurement rows.

    Only rows carrying a real `clv_bps` contribute to the CLV statistics;
    everything else is counted by its absence token. `n_games` sits beside
    `n_decisions` because the rows are clustered by game, and a mean over 400
    decisions on 40 games is a mean over roughly 40 things.

    Returns `clv_bps_mean: None` with `n_measured: 0` when nothing in the
    group could be measured -- an honest empty, never a zero.

    EVERY FILTER HERE TESTS `is not None`, NEVER TRUTHINESS, AND NOTHING IS
    ZERO-FILLED. Both halves of that are load-bearing and both were live
    defects waiting to happen. `r.get(k) or 0.0` turns a withheld
    `price_standing_bps` into a middling real value -- on the live ledger it
    moved the mean from -107.79 to -91.97 by inventing 86 numbers -- and
    `if r.get(k)` silently drops a GENUINE zero, which is a real, measured,
    middling standing and not an absence. The two errors point opposite ways
    and both corrupt; the only safe test is against None.

    THE PARTITIONS ARE COMPUTED HERE, NOT BY THE CALLER. Provenance and close
    freshness reach every rollup because `summarise` is the one function every
    cut in this module goes through, so a cut cannot be added later that
    quietly forgets them. `segment=False` computes one level down without
    recursing.
    """
    rows = list(measurements or ())
    measured = [r for r in rows if r.get("clv_bps") is not None]
    clv = [r["clv_bps"] for r in measured]
    move = [r["consensus_move_bps"] for r in measured
            if r.get("consensus_move_bps") is not None]
    standing = [r["price_standing_bps"] for r in measured
                if r.get("price_standing_bps") is not None]

    absences: dict = {}
    for row in rows:
        token = row.get("absence")
        if token:
            absences.setdefault(
                token, {"n": 0, "reason": ABSENCE_REASONS[token]})
            absences[token]["n"] += 1

    # Counted separately from `absences` on purpose: these rows DO carry a
    # real clv_bps and are missing only the vig-neutral split. Folding the two
    # tallies together would make `n_measured` unreconcilable with either.
    move_absences: dict = {}
    for row in measured:
        token = row.get("move_absence")
        if token:
            move_absences.setdefault(
                token, {"n": 0, "reason": ABSENCE_REASONS[token]})
            move_absences[token]["n"] += 1

    # ZERO IS COUNTED IN ITS OWN COLUMN, never folded into either sign.
    # positive + zero + negative == n, and a test pins that identity, so
    # `>= 0` cannot be substituted for `> 0` without the accounting breaking.
    # A CLV of exactly zero means the close landed on the number taken: real,
    # measured, and emphatically not evidence the selection carried anything.
    n_publishable = sum(1 for r in rows if is_publishable(r))
    out = {
        "n_decisions": len(rows),
        "n_measured": len(measured),
        "n_games": len({r.get("event_id") for r in measured
                        if r.get("event_id")}),
        "n_systems": len({r.get("system_id") for r in measured
                          if r.get("system_id")}),
        "clv_bps_mean": _mean(clv),
        "clv_bps_median": _median(clv),
        "clv_bps_stderr_naive": _stderr_naive(clv),
        "clv_bps_positive": sum(1 for v in clv if v > 0),
        "clv_bps_zero": sum(1 for v in clv if v == 0),
        "clv_bps_negative": sum(1 for v in clv if v < 0),
        "consensus_move_bps_n": len(move),
        "consensus_move_bps_mean": _mean(move),
        "consensus_move_bps_median": _median(move),
        "consensus_move_bps_stderr_naive": _stderr_naive(move),
        "consensus_move_bps_positive": sum(1 for v in move if v > 0),
        "consensus_move_bps_zero": sum(1 for v in move if v == 0),
        "consensus_move_bps_negative": sum(1 for v in move if v < 0),
        "price_standing_bps_n": len(standing),
        "price_standing_bps_mean": _mean(standing),
        "n_publishable": n_publishable,
        "publication_caveat": None,
        "absences": absences,
        "move_absences": move_absences,
    }
    if n_publishable < len(rows):
        # Stated on the rollup itself rather than left to a reader to derive
        # from the segment counts. The retraction this module exists to
        # prevent happened because a mean was quoted from a group nobody had
        # checked for contamination; a caveat that has to be looked up is a
        # caveat that gets skipped.
        out["publication_caveat"] = (
            f"{len(rows) - n_publishable} of {len(rows)} rows in this group "
            "are NOT publishable under doctrine section 6. Quote "
            "segments['publishable'] for a published record, or say which "
            "pool this number came from. " + PUBLICATION_RULE)
    if segment:
        out["segments"] = {
            name: dict(summarise(group, segment=False),
                       segment_note=SEGMENT_NOTES[name])
            for name, group in segments(rows).items()
        }
    return out


def _group(measurements, key_fn) -> dict:
    grouped: dict = {}
    for row in measurements or ():
        for key in key_fn(row):
            grouped.setdefault(key, []).append(row)
    return {key: summarise(rows) for key, rows in sorted(grouped.items())}


def by_system_class(measurements) -> dict:
    """CONTROL / MARKET_REFERENCE / FORWARD_TEST, never conflated.

    The classification is `engine_bridge.system_class`'s and is never
    re-derived here -- the same rule `paper_performance` and `daily_record`
    already report under, so three surfaces cannot disagree about what a
    system is.
    """
    return _group(measurements, lambda r: (r.get("system_class") or FORWARD_TEST,))


def by_system(measurements) -> dict:
    return _group(measurements, lambda r: (r.get("system_id") or "(unset)",))


def by_market(measurements) -> dict:
    return _group(measurements, lambda r: (r.get("market_key") or "(unset)",))


def _wager_id(row):
    """The `(event_id, market_key, selection_id)` identity, or None.

    `families.wager_id` REFUSES a partly-blank identity rather than minting
    one with a hole in it, which is right for the clustering that owns it and
    wrong for a rollup: a decision that never recovered a selection simply
    has no slip to join to, and that is an unmatched row, not an error that
    should take the report down.
    """
    try:
        return families_mod.wager_id(row.get("event_id"),
                                     row.get("market_key"),
                                     row.get("selection_id"))
    except families_mod.FamilyError:
        return None


def latest_slip_per_date(slips=None) -> dict:
    """`{date: slip}` keeping the LAST slip written for each date.

    This is `src.engine.slip.latest_slip_for`'s rule -- last in append-order
    for that date, never by comparing `slip_utc` strings, because the chain's
    order is the order things actually happened and a clock disagreement must
    not be able to reorder history -- applied to every date in one pass so the
    ledger is read once. A test pins that this and `latest_slip_for` agree on
    the same ledger, so the two cannot drift.

    Several slips per date is the design, not a bug (`slip.py`): a later slate
    pass saw lineups the earlier one could not, and the last one written is
    the authority on what was actually published for that date.
    """
    rows = slip_mod.read_slips() if slips is None else list(slips or ())
    latest: dict = {}
    for row in rows:
        date = row.get("date")
        # `rule` is the same guard `latest_slip_for` applies: it is what
        # distinguishes a slip payload from any other row on the chain.
        if not date or not row.get("rule"):
            continue
        latest[date] = row
    return latest


def cohort_tags_by_wager(slips=None) -> dict:
    """`{wager_id: (cohort tags,)}` from the authoritative slip for each date.

    The published slip is the SOLE authority on cohort -- `src.ledger.records`
    refuses `cohorts` on `DecisionRecord` outright, and a duplicate field
    there would be a second authority on the same fact. So the tags are read
    off `SlipPick.cohorts`, which was frozen when the slip was written and is
    never recomputed here: re-deriving a cohort from today's ranker is the
    re-ranking of graded history doctrine amendment 8 forbids.
    """
    tags: dict = {}
    for row in latest_slip_per_date(slips).values():
        for pick in row.get("picks") or ():
            wid = pick.get("wager_id")
            if wid:
                tags[wid] = tuple(pick.get("cohorts") or ())
    return tags


def by_cohort(measurements, slips=None) -> dict:
    """Per-cohort CLV -- doctrine section 6's required cut -- or a named absence.

    Joined to `evidence/slips_v1.jsonl` on the wager id, NOT read off the
    decision. An earlier version of this function read `record.cohorts`; that
    field does not exist and was refused on purpose (see the comment in
    `src.ledger.records` and the test that pins it), so the cut could never
    activate and its "no cohort tags yet" absence was reporting the wrong
    reason for the right emptiness. The two absences it can return now say
    which of the two real situations holds: no slip has ever been published,
    or slips exist and none of their picks is in this measurement set.

    A pick reports under EVERY tag it carries, not under the tuple of them:
    the cohorts nest (a TOP_3 pick is also TOP_5 and PUBLISHED -- see
    `src.ledger.records`'s own nesting invariant), so each cut is a filter
    over one frozen set. Filing a pick under the combination instead would
    let the Top 3 record and the published record disagree about a bet they
    both contain.
    """
    tags = cohort_tags_by_wager(slips)
    if not tags:
        return _absent(NO_SLIP_LEDGER)
    # A pick must carry at least one tag to be groupable, and every rank does
    # (`slip.cohorts_for_rank` always includes PUBLISHED). Requiring it anyway
    # is what stops a slip written under some other rule from producing an
    # EMPTY dict here -- an empty cut with no absence beside it reads as
    # "measured and found nothing", which is the one thing this module is not
    # allowed to say by accident.
    joined = [row for row in measurements or ()
              if tags.get(_wager_id(row))]
    if not joined:
        return _absent(NO_SLIP_PICK_MEASURED, n_slip_picks=len(tags),
                       n_slip_picks_tagged=sum(1 for t in tags.values() if t))
    return _group(joined, lambda r: tags.get(_wager_id(r), ()))


def report(decisions=None, rows=None, index=None, slips=None) -> dict:
    """The whole CLV surface: totals, absences, and every required cut.

    This is the function a caller renders. It carries its own label, the vig
    decomposition note and the independence note, so a table built from it
    cannot be published without the two sentences that say how to read it.

    `overall` and `eligible` are the WHOLE ledger, contamination included, and
    `published` is the doctrine section 6 cut. All three are reported because
    dropping the contaminated pools would replace one silently-wrong number
    with another: the contaminated pools are how a reader sees how much was
    dropped and how differently it behaved. `published` is the one to quote,
    and every summary here carries `publication_caveat` and
    `segments['publishable']` so the distinction survives being copied out of
    context.

    The per-class, per-system and per-market cuts run over EVERY row rather
    than over the published cut, because a control system's replay rows are a
    legitimate research question and refusing to compute them would answer it
    with silence. Each of those summaries carries its own publishable segment.
    """
    measurements = measure(decisions=decisions, rows=rows, index=index)
    overall = summarise(measurements)
    eligible = [r for r in measurements
                if r.get("absence") not in (NOT_A_BET, NO_PRICE_TAKEN)]
    published = publishable(eligible)
    return {
        "label": LABEL,
        "source": SOURCE,
        "min_books": MIN_BOOKS,
        "vig_note": VIG_NOTE,
        "independence_note": INDEPENDENCE_NOTE,
        "publication_rule": PUBLICATION_RULE,
        "n_ledger_rows": len(measurements),
        "n_eligible": len(eligible),
        "n_published": len(published),
        "overall": overall,
        "eligible": summarise(eligible),
        "published": summarise(published),
        "by_system_class": by_system_class(measurements),
        "by_system": by_system(measurements),
        "by_market": by_market(measurements),
        "by_cohort": by_cohort(measurements, slips=slips),
        "published_by_system_class": by_system_class(published),
        "measurements": measurements,
    }
