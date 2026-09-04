"""Row construction for the standalone totals evaluation path.

WHY THIS MODULE EXISTS, AND WHY IT IS NOT `scripts/totals_population_audit.py`
-------------------------------------------------------------------------------
`docs/TOTALS_METHODOLOGY.md` "## Revision 2" (R7/A9) and its
"## Methodology re-review" (B6) require a standalone evaluation path mirroring
`src/research/f5_eval.py`: reuse `discovery`/`battery`/`family` verbatim, add
only row construction. `scripts/totals_population_audit.py` already parses the
nested snapshot -> events -> bookmakers -> markets -> outcomes archive and
picks a closing snapshot, but it is deliberately COUNTS-ONLY (B6's own
docstring: "NEVER reads, joins, or reports any outcome/score field") -- it
proves a population exists, it does not grade one. This module reuses its
closing-snapshot/floor/half-point DEFINITIONS (same constants, same tiebreak
rule) but adds the two things a counts-only audit must never do: joining to
`mlb_results.csv` for settlement, and computing a fair probability from book
prices.

WHAT A ROW IS
-------------
One row per gradeable event, at the event's own closing modal line (R5),
provided that line is BOTH floor-met (>=3 books, R2) and half-point (R3) --
exactly the "(4) joint" population `scripts/totals_population_audit.py`
already counts (1,321 in 2023, 1,320 in 2024). Grading a single line per
event does not contradict R2's "no single consensus line chosen for grading":
R2 forbids AVERAGING or interpolating across lines to invent a number, not
grading the one line that is independently established (by the floor and
half-point checks, both feature-side) as the line actually tradeable at
close. A future extension registering additional non-modal floor-met lines
per event as further family members is out of scope for this module, whose
mission defines no hypotheses.

`{game_pk, date, season, line, side, implied, price, book_count, n_books,
won, is_half_point}` -- side is "over", grading the OVER exactly as F5-H1
grades "home": the full-population lens R6 identifies as the natural single
member of a future family, never registered here.

THE INTEGER STRATUM (R3/A5) IS A SEPARATE, NEVER-POOLED BUILD
-----------------------------------------------------------------
`build_integer_stratum_rows` grades the same way at integer closing lines
(estimand P(over | no push), pushes excluded from both numerator and
denominator) and is never merged with the half-point primary population --
pooling both would average two different estimands, which R3 forbids.

CLOSING SNAPSHOT PARAMETERS (R5, B5)
-------------------------------------
`MAX_STALENESS_HOURS` (default 6h) and `ANCHOR_RULE` (default: `commence_time`
read from the SAME snapshot's own event record, never a post-hoc schedule
field -- A7c) are both named constants, not inlined, because a pending W19
audit may revise the default staleness bound: changing it should mean editing
one line here, not hunting through call sites. B5's derivation (measure the
gap distribution first, freeze the bound second) produced 6h for both 2023
and 2024 in `docs/TOTALS_POPULATION_AUDIT.md` section 5 -- this module's
default reproduces that frozen choice, it does not re-derive it.

NO OUTCOME IS READ BY THE UNIVERSE-BUILD PATH UNTIL SETTLEMENT IS JOINED
--------------------------------------------------------------------------
`load_event_snapshots`/`compute_event_closing`/`_modal_line` never open
`mlb_results.csv` -- they are the exact feature-side logic
`totals_population_audit.py` already runs. Only `build_universe` (which joins
for the identity/price-payload manifest) and `build_over_rows`/
`build_integer_stratum_rows` (which attach `won`) touch settlement.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from src.core import odds as odds_math
from src.paths import data_path, historical_path
from src.research import pricepath

ARCHIVE_ROOT = historical_path("odds_history")
RESULTS_CSV = pricepath.RESULTS_CSV
MANIFEST_PATH = data_path("research", "totals", "universe_frozen.json")

# B5: derived from the gap distribution, then frozen -- see module docstring.
# A pending audit (owner note W19) may revise this; it is one constant so a
# revision is a one-line change, never a re-derivation scattered across call
# sites.
MAX_STALENESS_HOURS = 6

# A7c: the anchor for "how stale is this snapshot" is the COMMENCE_TIME
# CARRIED BY THAT SAME SNAPSHOT's own event record -- never a later, post-hoc
# schedule field, which could silently pick up a rescheduled game's revised
# start time. Named so a future second anchor rule (if W19 proposes one)
# has somewhere to be recorded as a real alternative, not an inline literal.
ANCHOR_RULE = "per_snapshot_commence_time"

# R2: a line is admitted into the population only when at least this many
# distinct books quote it (with both an Over and an Under price) at the
# closing snapshot.
BOOK_FLOOR = 3

# The only two seasons this module evaluates. 2025 is TUNING_ONLY (owner
# standing rule, matching src.research.f5_eligibility) and is never read by
# this module; 2026 is SEALED and never read.
SEASONS = ("2023", "2024")

# docs/TOTALS_POPULATION_AUDIT.md section 6: fixed bucket edges for the
# population-shift chi-square, named here (not re-derived) exactly as B6
# published them.
LINE_BUCKET_EDGES = (5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5)

# R2/A4: the three sensitivity conventions, same names `src.research.f5_eval`
# uses for the same reason -- "power" is `src.core.odds`'s spelling of the
# convention the literature calls "multiplicative"/"odds-ratio".
DEVIG_METHODS = {"proportional": "proportional", "multiplicative": "power", "shin": "shin"}
PRIMARY_DEVIG_METHOD = "proportional"

# D1 (docs/PREREG_TOTALS_FAMILIES.md "## Methodology review -- 2026-09-05"):
# the FROZEN classification of every event id `build_universe` has ever
# found not-joined-to-settlement, taken verbatim from
# docs/TOTALS_UNJOINED_AUDIT.md's "Full listing" table (identity/date only --
# NO score field was read to build that audit, and none is read here). This
# table does not get recomputed on every run: the classification (a genuine
# rainout/makeup vs. a Wild Card/Division-Series slot vs. the All-Star
# exhibition) depends on facts -- WHY a game is missing from
# `mlb_results.csv` -- that are not encoded anywhere in the odds archive or
# the results CSV; they were established once, by the audit's manual
# cross-referencing, and are recorded here so the exclusion ledger never has
# to re-derive them from an outcome. `class (b)` (5 doubleheader-nightcap
# join collisions) is DELIBERATELY ABSENT from this table: D1 states plainly
# those 5 are now FIXED (joined, via `_join_doubleheader_same_day`) and
# therefore INCLUDED in the joint denominator -- they must never reappear as
# an exclusion class. `classify_not_joined`'s `unclassified` bucket exists so
# a future archive change that alters the not-joined set is caught as a hard
# failure (`build_universe` raises on it) rather than silently producing a
# ledger that no longer reconciles.
NOT_JOINED_CLASSIFICATION = {
    "postponed": (
        "0bf3309e2b70484d848b9d81c1f7c862", "136295e92bb9e259eaca4748d941a568",
        "16816d9a7807b44dd8cfc0b1cb2a7e17", "2824681ff93df18fa55151dff0bc44d3",
        "2a701e6fae2bd9423013b80ac343f77b", "2fd96e70eb5787df5efbf07b36340c60",
        "32b3944fd9b873891b07d6cb9cf3be82", "408a4f27308668f3393ed128fcda8a09",
        "466f5e785e70b4ab0d3af03ae5295a5a", "59663773d5f2ed65bb700098cb3bd7f8",
        "649ad82dac37a64e347cdbb34c7d73e7", "6acdd27db6bb5c41faa08086a6b8618e",
        "7015048add706580be5a518dd3e2a611", "7bb736b77d1305880a3b99aee8503839",
        "7bda8cc176e4c517746e563979bbd2f9", "7f3b1a8ad87feb0dbb1acc9ff2c38a55",
        "7ff64a7253fb4c3bd2c26af5c1da2603", "813a982760e7b87a94c287bd366c5b09",
        "820d750c16b8dee48995bfac7ac17386", "85c4e285bb00d1e680c737694b109c25",
        "979a1e9d0770ddf4ddc5c115a736c624", "9c8573b0b807fb97e4501e39aacfc9c7",
        "9cbf87bba0ce6052ea37a12f36806423", "9ea64c9ecc7d7364f870d4eb929b844d",
        "c383f4789232ede0272a45c4fdfa68d9", "c963b9af00e516bfb4c02c2a3e71d30b",
        "d7bfc4242d9b4c8eb12bb3b6af4cafb5", "e75516c0e8e178a345913ab089287d7d",
        "e87c5b818f6ebfa9e5a3eabe0412fc63", "f13302c948480e2a0d7e3c0931b93cbd",
    ),
    "all_star": (
        "1e917abee85546968da7eeda899fb65a",
    ),
    "postseason": (
        "1533823cdb69bc81c2874ef58f98be12", "5013b29a336f56c618dc02c05893bc4e",
        "5f02286618321060e43f8e185750c3aa", "8f1a5d9345498b15a8330bca169bd02b",
        "98d592ce811a32f64f0a2f4860544019", "ae60872ca814ec362764c06c880046b8",
        "b86f8004e8cd0e1371e70bc8331dbe57", "bd5db14c1b7b06b3668aa93aa6b4834e",
        "be0b93120d3af3b16fa7b4106a7f72ef", "bef91969a8db09009edc331b7dec5faf",
        "e70aecb7479a5cb8243fe375cc8b491a", "ee785b78fc4a71045f4b849f69e4548f",
        "f2f71df91a9eb0eeb8355d20e89bccdf", "f3e9f2867b5df4befafef6a150d90df0",
    ),
}


def classify_not_joined(not_joined_event_ids: list) -> dict:
    """D1: split `not_joined_event_ids` into the itemised exclusion classes
    `NOT_JOINED_CLASSIFICATION` records (`postponed`, `all_star`,
    `postseason`), plus `unclassified` for anything the frozen table does
    not recognise. `build_universe` raises if `unclassified` is non-empty on
    the real archive -- a ledger that cannot account for every excluded id
    must never be reported as if it reconciled."""
    lookup = {}
    for cls, ids in NOT_JOINED_CLASSIFICATION.items():
        for eid in ids:
            lookup[eid] = cls
    ledger = {cls: [] for cls in NOT_JOINED_CLASSIFICATION}
    ledger["unclassified"] = []
    for eid in not_joined_event_ids:
        ledger.setdefault(lookup.get(eid, "unclassified"), []).append(eid)
    return ledger


class TotalsRowsError(RuntimeError):
    """Raised when totals row construction cannot proceed honestly."""


# ---------------------------------------------------------------------------
# Archive parsing (feature-side only -- mirrors totals_population_audit.py)
# ---------------------------------------------------------------------------

def _iter_jsonl(path: Path):
    target = Path(path)
    if not target.exists():
        return
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def load_event_snapshots(season, *, archive_root=ARCHIVE_ROOT) -> dict:
    """{event_id: [(snapshot_at, commence_time, away_team, home_team, lines), ...]}
    sorted by snapshot_at ascending, one entry per snapshot that carried at
    least one totals outcome for that event.

    `lines` maps point -> {book_key: {"over": price, "under": price}} --
    EITHER side may be absent for a book that only posted one of the two
    (never guessed, never defaulted).
    """
    path = Path(archive_root) / f"mlb_{season}.jsonl"
    events: dict = defaultdict(list)
    for snapshot in _iter_jsonl(path):
        snap_at_raw = snapshot.get("snapshot_at")
        if not snap_at_raw:
            continue
        snap_at = _parse_ts(snap_at_raw)
        for event in snapshot.get("events") or []:
            eid = event.get("id")
            ct_raw = event.get("commence_time")
            if eid is None or not ct_raw:
                continue
            commence_time = _parse_ts(ct_raw)
            lines: dict = defaultdict(dict)
            for book in event.get("bookmakers") or []:
                bk = book.get("key")
                if bk is None:
                    continue
                for market in book.get("markets") or []:
                    if market.get("key") != "totals":
                        continue
                    for outcome in market.get("outcomes") or []:
                        pt = outcome.get("point")
                        name = outcome.get("name")
                        price = outcome.get("price")
                        if pt is None or price is None:
                            continue
                        slot = lines[pt].setdefault(bk, {})
                        if name == "Over":
                            slot["over"] = price
                        elif name == "Under":
                            slot["under"] = price
            if lines:
                events[eid].append(
                    (snap_at, commence_time, event.get("away_team"),
                     event.get("home_team"), {pt: dict(books) for pt, books in lines.items()}))
    for eid in events:
        events[eid].sort(key=lambda r: r[0])
    return dict(events)


def _pick_closing(records: list, max_staleness_hours=MAX_STALENESS_HOURS):
    """Latest record with `snapshot_at` in
    `[commence_time - max_staleness_hours, commence_time)`, per A7a/A7c --
    `commence_time` is read from THAT record's own event, matching
    `ANCHOR_RULE`. Returns None if no record qualifies."""
    for snap_at, commence_time, away, home, lines in reversed(records):
        window_start = commence_time - timedelta(hours=max_staleness_hours)
        if window_start <= snap_at < commence_time:
            return snap_at, commence_time, away, home, lines
    return None


def _modal_line(lines: dict) -> float:
    """Book-count-weighted mode; tie -> toward 8.5, then closest to 8.5, then
    smaller value -- fixed in advance, identical to
    `totals_population_audit._modal_line` (R5, sec 2.2 Decision A)."""
    counts = {pt: len(books) for pt, books in lines.items()}
    max_count = max(counts.values())
    tied = [pt for pt, c in counts.items() if c == max_count]
    if 8.5 in tied:
        return 8.5
    tied.sort(key=lambda pt: (abs(pt - 8.5), pt))
    return tied[0]


def _is_half_point(line: float) -> bool:
    return (line * 2) % 2 == 1


def _n_books_both_sides(book_prices: dict) -> int:
    return sum(1 for p in book_prices.values()
               if p.get("over") is not None and p.get("under") is not None)


def compute_event_closing(records: list, *, max_staleness_hours=MAX_STALENESS_HOURS) -> dict | None:
    """Feature-side closing-snapshot summary for one event. None if excluded
    (no snapshot in the staleness window) -- callers must count this
    exclusion, never silently drop it (R5)."""
    closing = _pick_closing(records, max_staleness_hours)
    if closing is None:
        return None
    snap_at, commence_time, away, home, lines = closing
    modal = _modal_line(lines)
    book_prices = lines.get(modal) or {}
    n_books = _n_books_both_sides(book_prices)
    return {
        "snapshot_at": snap_at,
        "commence_time": commence_time,
        "away_team": away,
        "home_team": home,
        "modal_line": modal,
        "book_prices": book_prices,
        "n_books": n_books,
        "floor_met": n_books >= BOOK_FLOOR,
        "is_half_point": _is_half_point(modal),
        "gap_minutes": (commence_time - snap_at).total_seconds() / 60.0,
    }


# ---------------------------------------------------------------------------
# Per-line fair probability (R2) -- three conventions (A4)
# ---------------------------------------------------------------------------

def consensus_fair_for_line(book_prices: dict, method=PRIMARY_DEVIG_METHOD) -> dict | None:
    """Cross-book mean de-vigged (over_fair, under_fair) for one exact line,
    over only the books quoting BOTH sides -- plus the best (most favourable
    to a bettor) American price per side, same convention as
    `src.research.f5_eval.consensus_fair`. None if no book de-vigs cleanly.
    """
    over_fairs, under_fairs, over_prices, under_prices = [], [], [], []
    for prices in book_prices.values():
        over_p, under_p = prices.get("over"), prices.get("under")
        if over_p is None or under_p is None:
            continue
        try:
            fair_over, fair_under = odds_math.devig_two_way(over_p, under_p, method=method)
        except odds_math.OddsError:
            continue
        over_fairs.append(fair_over)
        under_fairs.append(fair_under)
        over_prices.append(over_p)
        under_prices.append(under_p)
    if not over_fairs:
        return None
    return {
        "over_fair": sum(over_fairs) / len(over_fairs),
        "under_fair": sum(under_fairs) / len(under_fairs),
        "over_price": max(over_prices),
        "under_price": max(under_prices),
        "n_books": len(over_fairs),
    }


def devig_two_way_example() -> dict:
    """A hand-checkable two-way totals example, used by the validation test
    to confirm all three conventions agree on a near-fair line. Not consumed
    by the evaluation path itself."""
    return {"near_fair": {"over": -105, "under": -115}}


# ---------------------------------------------------------------------------
# Settlement join (team/date, reusing pricepath.py's join verbatim)
# ---------------------------------------------------------------------------

def load_settled_games(*, results_path=RESULTS_CSV) -> list:
    """Played, decided games -- `pricepath.read_results`, reused verbatim
    (never re-derived): this module's only settlement source for full-game
    totals."""
    return pricepath.read_results(results_path)


# docs/TOTALS_UNJOINED_AUDIT.md: 5 of the 50 originally-unjoined events are a
# straight doubleheader's SECOND game running long enough (a slow game 1, or a
# delayed turnaround) that its real start drifts past `pricepath`'s shared
# 3-hour MAX_EVENT_GAP_SECONDS -- a cross-day disambiguation bound, not a
# same-day one. Evidence (audit's "same_date" rows): every one of those 5 has
# its nearest candidate SAME CALENDAR DATE at 3.27-5.77h, while every genuine
# cross-day collision (the postponement/makeup pattern the 3h bound exists to
# reject) sits at 15h+. 8h leaves comfortable room above the observed cluster
# and well below the next real population, so this fallback -- SAME DATE
# ONLY, never touching the previous-day fallback below -- cannot reach into a
# different day's game the way widening `pricepath`'s own bound globally
# could.
DOUBLEHEADER_SAME_DAY_GAP_SECONDS = 8 * 3600


def _join_doubleheader_same_day(away, home, commence_time, index):
    """Same-date-only fallback for a straight doubleheader's nightcap running
    past `pricepath.MAX_EVENT_GAP_SECONDS` (see constant docstring above).
    Never consulted for the previous-day case -- that is exactly the
    ambiguous-day territory the tight bound protects."""
    candidates = index.get((away, home, commence_time.date().isoformat())) or []
    best, best_gap = None, None
    for game in candidates:
        gap = abs((game["start_time_utc"] - commence_time).total_seconds())
        if gap <= DOUBLEHEADER_SAME_DAY_GAP_SECONDS and (best_gap is None or gap < best_gap):
            best, best_gap = game, gap
    return best


def _join_settlement(away_team_raw, home_team_raw, commence_time, index):
    """Team/date join to a settled game, reusing `pricepath`'s exact
    two-step resolution (same day, then the UTC-vs-local-date fallback for a
    night game) -- never re-derived here, so a totals join can never quietly
    diverge from the F5/h2h join's behaviour on the same archive shape. Only
    if BOTH of those come back empty does a totals-local, same-day-only
    doubleheader fallback run (see `_join_doubleheader_same_day`) -- it can
    never override or shadow a `pricepath` match."""
    away = pricepath._abbrev(away_team_raw)
    home = pricepath._abbrev(home_team_raw)
    if away is None or home is None:
        return None
    game = pricepath._resolve(index.get((away, home, commence_time.date().isoformat())), commence_time)
    if game is None:
        previous = (commence_time.date() - timedelta(days=1)).isoformat()
        game = pricepath._resolve(index.get((away, home, previous)), commence_time)
    if game is None:
        game = _join_doubleheader_same_day(away, home, commence_time, index)
    return game


def _settle_over_under(total_runs: int, line: float) -> str | None:
    """"over" / "under" / "push"."""
    if total_runs > line:
        return "over"
    if total_runs < line:
        return "under"
    return "push"


# ---------------------------------------------------------------------------
# Universe: identity + price-payload hashes (M1-style manifest, A6)
# ---------------------------------------------------------------------------

def _gradeable_closings(season, *, archive_root=ARCHIVE_ROOT, max_staleness_hours=MAX_STALENESS_HOURS):
    """Per event: (event_id, closing) for events whose closing snapshot is
    both floor-met and half-point -- the exact "(4) joint" population
    `totals_population_audit.py` counts. Excluded/no-closing counts are
    returned alongside so they are never silently dropped (R5)."""
    events = load_event_snapshots(season, archive_root=archive_root)
    out, excluded_no_closing, excluded_not_joint = [], 0, 0
    for eid, records in events.items():
        closing = compute_event_closing(records, max_staleness_hours=max_staleness_hours)
        if closing is None:
            excluded_no_closing += 1
            continue
        if not (closing["floor_met"] and closing["is_half_point"]):
            excluded_not_joint += 1
            continue
        out.append((eid, closing))
    return out, excluded_no_closing, excluded_not_joint


def content_hash(entries: list) -> str:
    """sha256 over the sorted (event_id) identity set -- proves WHICH events
    are in the set, matching `f5_universe.content_hash`'s scope exactly."""
    ids = sorted(str(e["event_id"]) for e in entries)
    payload = json.dumps(ids, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def price_payload_hash(entries: list) -> str:
    """sha256 over each event's closing modal line, snapshot_at, and every
    book's key + over/under prices at that line -- proves WHAT PRICES,
    matching `f5_universe.price_payload_hash`'s scope exactly."""
    out = []
    for e in entries:
        books = []
        for key, prices in (e["book_prices"] or {}).items():
            books.append({"key": key, "over": prices.get("over"), "under": prices.get("under")})
        books.sort(key=lambda b: (b["key"] is None, b["key"]))
        out.append({
            "event_id": str(e["event_id"]),
            "snapshot_at": e["snapshot_at"].isoformat() if e["snapshot_at"] else None,
            "line": e["line"],
            "books": books,
        })
    out.sort(key=lambda e: e["event_id"])
    payload = json.dumps(out, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_universe(*, seasons=SEASONS, archive_root=ARCHIVE_ROOT,
                    results_path=RESULTS_CSV, max_staleness_hours=MAX_STALENESS_HOURS) -> dict:
    """Recompute the frozen totals manifest from source data. Deterministic:
    same inputs always produce the same manifest and the same hashes.

    Denominator is PRE-VOID (A6): a joined, gradeable event is counted here
    regardless of whether its settled total pushes -- void handling belongs
    to row construction, never to the frozen denominator.
    """
    results = load_settled_games(results_path=results_path)
    index = pricepath._index_results(results)

    entries = []
    not_joined = []
    by_season_counts = {}
    excluded_no_closing_total = 0
    excluded_not_joint_total = 0
    for season in seasons:
        closings, excl_no_closing, excl_not_joint = _gradeable_closings(
            season, archive_root=archive_root, max_staleness_hours=max_staleness_hours)
        excluded_no_closing_total += excl_no_closing
        excluded_not_joint_total += excl_not_joint
        n_joined = 0
        for eid, closing in closings:
            game = _join_settlement(closing["away_team"], closing["home_team"],
                                     closing["commence_time"], index)
            if game is None:
                not_joined.append(str(eid))
                continue
            n_joined += 1
            entries.append({
                "event_id": eid,
                "game_pk": game["game_pk"],
                "date": game["date"],
                "season": season,
                "line": closing["modal_line"],
                "n_books": closing["n_books"],
                "book_prices": closing["book_prices"],
                "snapshot_at": closing["snapshot_at"],
                "gap_minutes": closing["gap_minutes"],
            })
        by_season_counts[season] = n_joined

    entries.sort(key=lambda e: str(e["event_id"]))

    # D1: itemise the not-joined-to-settlement events against the frozen
    # audit classification, and refuse to report a ledger that cannot
    # account for every one of them (regular-season-only denominator scope,
    # docs/PREREG_TOTALS_FAMILIES.md "## Methodology review -- 2026-09-05").
    not_joined_ledger = classify_not_joined(not_joined)
    if not_joined_ledger["unclassified"]:
        raise TotalsRowsError(
            "the not-joined-to-settlement set contains "
            f"{len(not_joined_ledger['unclassified'])} event id(s) absent "
            "from the frozen NOT_JOINED_CLASSIFICATION table "
            f"({not_joined_ledger['unclassified'][:5]}...) -- the archive's "
            "not-joined population has moved since docs/TOTALS_UNJOINED_"
            "AUDIT.md was written. Aborting rather than reporting an "
            "exclusion ledger that no longer reconciles; re-audit and "
            "extend the frozen table before proceeding.")

    exclusion_ledger = {
        "postseason": len(not_joined_ledger["postseason"]),
        "all_star": len(not_joined_ledger["all_star"]),
        "postponed": len(not_joined_ledger["postponed"]),
        "no_closing_snapshot": excluded_no_closing_total,
        "not_joint": excluded_not_joint_total,
    }
    # Reconciliation (D1 binding: "the run report must publish the ledger
    # even when nothing surprising is in it"): the itemised classes must sum
    # to the raw exclusion counts they were split from. This can never
    # silently drift -- `classify_not_joined`'s unclassified-raises guard
    # above already forces the not-joined split to reconcile; this second
    # check additionally guards the two independently-counted classes
    # (no-closing-snapshot, not-joint) against a future refactor that moves
    # where they are counted.
    reconciled_not_joined = (exclusion_ledger["postseason"]
                             + exclusion_ledger["all_star"]
                             + exclusion_ledger["postponed"])
    if reconciled_not_joined != len(not_joined):
        raise TotalsRowsError(
            f"exclusion ledger reconciliation failed: itemised classes sum "
            f"to {reconciled_not_joined}, raw not-joined count is "
            f"{len(not_joined)}")

    manifest = {
        "schema_version": 1,
        "seasons": list(seasons),
        "max_staleness_hours": max_staleness_hours,
        "anchor_rule": ANCHOR_RULE,
        "book_floor": BOOK_FLOOR,
        "counts": {
            "joint_by_season": by_season_counts,
            "joint_total": len(entries),
            "excluded_no_closing_snapshot": excluded_no_closing_total,
            "excluded_not_joint": excluded_not_joint_total,
            "not_joined_to_settlement": len(not_joined),
        },
        "exclusion_ledger": exclusion_ledger,
        "not_joined_event_ids": not_joined,
        "events": [
            {"event_id": str(e["event_id"]), "game_pk": e["game_pk"], "date": e["date"],
             "season": e["season"], "line": e["line"]}
            for e in entries
        ],
    }
    manifest["content_hash"] = content_hash(entries)
    manifest["price_payload_hash"] = price_payload_hash(entries)
    return manifest


def write_manifest(manifest: dict, path=MANIFEST_PATH) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(target)


def read_manifest(path=MANIFEST_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Row construction -- H1-analogue (grades "over" of the full joint population)
# ---------------------------------------------------------------------------

def build_over_rows(*, seasons=SEASONS, archive_root=ARCHIVE_ROOT,
                     results_path=RESULTS_CSV, max_staleness_hours=MAX_STALENESS_HOURS,
                     method=PRIMARY_DEVIG_METHOD, dry_run=False) -> list:
    """One row per gradeable (half-point, floor-met) event, grading OVER.

    R6: this IS the shape of the natural full-population Over/Under bias
    hypothesis -- built here as plumbing only; this module registers no
    hypothesis and `dry_run=False` is not authorised against real data by
    the mission that built it.
    """
    results = load_settled_games(results_path=results_path)
    index = pricepath._index_results(results)

    rows = []
    for season in seasons:
        closings, _excl_no_closing, _excl_not_joint = _gradeable_closings(
            season, archive_root=archive_root, max_staleness_hours=max_staleness_hours)
        for eid, closing in closings:
            game = _join_settlement(closing["away_team"], closing["home_team"],
                                     closing["commence_time"], index)
            if game is None:
                continue
            c = consensus_fair_for_line(closing["book_prices"], method=method)
            if c is None:
                raise TotalsRowsError(
                    f"event_id={eid} met the >= {BOOK_FLOOR}-book floor by "
                    f"construction but no book de-vigged cleanly under "
                    f"{method!r} -- investigate before proceeding.")
            won = None
            if not dry_run:
                total_runs = game.get("total_runs")
                if total_runs is None:
                    continue  # no settled total -- excluded, never guessed
                outcome = _settle_over_under(total_runs, closing["modal_line"])
                if outcome == "push":
                    continue  # half-point line: unreachable by construction, guarded anyway
                won = outcome == "over"
            rows.append({
                "game_pk": str(game["game_pk"]),
                "date": game["date"],
                "season": season,
                "line": closing["modal_line"],
                "is_half_point": True,
                "side": "over",
                "implied": c["over_fair"],
                "price": c["over_price"],
                "book_count": c["n_books"],
                "won": won,
            })
    return rows


def build_integer_stratum_rows(*, seasons=SEASONS, archive_root=ARCHIVE_ROOT,
                                results_path=RESULTS_CSV,
                                max_staleness_hours=MAX_STALENESS_HOURS,
                                method=PRIMARY_DEVIG_METHOD, dry_run=False) -> list:
    """R3's named integer stratum: same construction, but at INTEGER closing
    modal lines that are floor-met. Estimand is P(over | no push) -- pushes
    are excluded from both numerator and denominator here, never pooled with
    the half-point primary population (`build_over_rows`)."""
    results = load_settled_games(results_path=results_path)
    index = pricepath._index_results(results)

    rows = []
    for season in seasons:
        events = load_event_snapshots(season, archive_root=archive_root)
        for eid, records in events.items():
            closing = compute_event_closing(records, max_staleness_hours=max_staleness_hours)
            if closing is None or closing["is_half_point"] or not closing["floor_met"]:
                continue
            game = _join_settlement(closing["away_team"], closing["home_team"],
                                     closing["commence_time"], index)
            if game is None:
                continue
            c = consensus_fair_for_line(closing["book_prices"], method=method)
            if c is None:
                raise TotalsRowsError(
                    f"event_id={eid} met the >= {BOOK_FLOOR}-book floor by "
                    f"construction but no book de-vigged cleanly under "
                    f"{method!r} -- investigate before proceeding.")
            won = None
            if not dry_run:
                total_runs = game.get("total_runs")
                if total_runs is None:
                    continue
                outcome = _settle_over_under(total_runs, closing["modal_line"])
                if outcome == "push":
                    continue  # R3: push excluded from numerator and denominator
                won = outcome == "over"
            rows.append({
                "game_pk": str(game["game_pk"]),
                "date": game["date"],
                "season": season,
                "line": closing["modal_line"],
                "is_half_point": False,
                "side": "over",
                "implied": c["over_fair"],
                "price": c["over_price"],
                "book_count": c["n_books"],
                "won": won,
            })
    return rows


# ---------------------------------------------------------------------------
# R1/B1 -- population-shift chi-square on line-bucket occupancy
# ---------------------------------------------------------------------------

def _line_bucket(line: float) -> str:
    for edge in LINE_BUCKET_EDGES:
        if line < edge:
            return f"<{edge}"
    return f">={LINE_BUCKET_EDGES[-1]}"


def _gamma_series(a: float, x: float) -> float:
    """Regularized LOWER incomplete gamma P(a, x), series form (valid for
    x < a + 1) -- the standard Numerical-Recipes `gser`, stdlib-only via
    `math.lgamma`."""
    total = 1.0 / a
    delta = total
    ap = a
    for _ in range(500):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * 1e-14:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_cf(a: float, x: float) -> float:
    """Regularized UPPER incomplete gamma Q(a, x), continued-fraction form
    (valid for x >= a + 1) -- the standard Numerical-Recipes `gcf`."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi_square_survival(chi_square: float, df) -> float:
    """Exact chi-square survival function P(X > chi_square) for ANY
    positive degrees of freedom (need not be even), via the regularized
    incomplete gamma function -- no scipy dependency, `math.lgamma` only.
    `df=2` reduces to exactly `exp(-x/2)`, matching
    `src.research.f5_eval.chi_square_p_df2`'s closed form for that one case
    (tested for agreement in tests/test_totals_rows.py)."""
    if chi_square < 0:
        raise TotalsRowsError(f"chi-square statistic must be >= 0, got {chi_square!r}")
    if df <= 0:
        raise TotalsRowsError(f"degrees of freedom must be > 0, got {df!r}")
    a, x = df / 2.0, chi_square / 2.0
    if x == 0:
        return 1.0
    return (1.0 - _gamma_series(a, x)) if x < a + 1.0 else _gamma_cf(a, x)


def chi_square_p_even_df(chi_square: float, df: int) -> float:
    """Back-compatible name: `chi_square_survival` for an even df, kept so
    call sites written against F5's even-df-only convention need no change.
    """
    if df < 2 or df % 2 != 0:
        raise TotalsRowsError(f"this alias is for an even df >= 2, got {df!r}")
    return chi_square_survival(chi_square, df)


def line_bucket_occupancy(rows: list) -> dict:
    """Bucket counts of `line` per `LINE_BUCKET_EDGES` -- feature-side, never
    reads `won`."""
    counts = defaultdict(int)
    for row in rows:
        counts[_line_bucket(row["line"])] += 1
    return dict(counts)


def population_shift_test(screen_rows: list, replication_rows: list) -> dict:
    """B1: chi-square of the replication leg's line-bucket occupancy against
    the screen leg's own occupancy (fit on the screen leg, applied frozen) --
    feature-side only (`line`, never `won`), decided before any outcome is
    read. Buckets with zero screen-leg expectation are folded into their
    nearest non-empty neighbour so no category contributes a zero-division
    expectation, and the tail is pooled until degrees of freedom is even
    (`chi_square_p_even_df` needs it) -- both folding rules are fixed by the
    SCREEN leg alone, decided before the replication leg's occupancy is read.
    """
    screen_counts = line_bucket_occupancy(screen_rows)
    n_screen = len(screen_rows)
    n_repl = len(replication_rows)
    if not n_screen or not n_repl:
        raise TotalsRowsError("population-shift test needs both a screen and "
                              "a replication sample")

    replication_counts = line_bucket_occupancy(replication_rows)
    all_buckets = sorted(set(screen_counts) | set(replication_counts),
                         key=lambda b: (0, float(b[1:])) if b.startswith("<") else (1, float(b[2:])))
    expected_props = {b: screen_counts.get(b, 0) / n_screen for b in all_buckets}

    kept = [b for b in all_buckets if expected_props[b] > 0]
    if len(kept) < 2:
        raise TotalsRowsError("screen leg's line-bucket occupancy has too "
                              "little spread to test a population shift")

    def _nearest_kept(bucket):
        idx = all_buckets.index(bucket)
        for offset in range(1, len(all_buckets)):
            for cand in (idx - offset, idx + offset):
                if 0 <= cand < len(all_buckets) and all_buckets[cand] in kept:
                    return all_buckets[cand]
        raise TotalsRowsError("no kept bucket to fold into")

    folded_expected = {b: expected_props[b] for b in kept}
    folded_observed = {b: replication_counts.get(b, 0) for b in kept}
    for b in all_buckets:
        if b in kept:
            continue
        target = _nearest_kept(b)
        folded_observed[target] += replication_counts.get(b, 0)

    df = len(kept) - 1
    chi_square = sum(
        ((folded_observed[b] - folded_expected[b] * n_repl) ** 2) / (folded_expected[b] * n_repl)
        for b in kept if folded_expected[b] > 0)

    p = chi_square_survival(chi_square, df) if df >= 1 else None
    fatal = p is not None and p < 0.01
    return {
        "df": df,
        "chi_square": round(chi_square, 5),
        "p": round(p, 6) if p is not None else None,
        "fatal": fatal,
        "screen_buckets": kept,
        "expected_props_screen": {b: round(folded_expected[b], 6) for b in kept},
        "observed_replication": folded_observed,
        "note": ("FATAL when p < 0.01: replication-leg line-bucket occupancy "
                 "differs materially from the screen-leg-fit distribution "
                 "(B1)"),
    }


# ---------------------------------------------------------------------------
# R7/A9 -- market-agnostic threshold-firing, matching funnel.py's semantics
# ---------------------------------------------------------------------------

def threshold_fires(value, threshold) -> bool:
    """Exactly `src.research.funnel._selections_for`'s firing predicate
    (`value is None or abs(value) < threshold` -> not selected), lifted out
    as a standalone, market-agnostic function so a totals hypothesis can use
    the identical selection semantics without importing funnel's h2h-specific
    join machinery. `tests/test_totals_rows.py` carries the A9 equivalence
    check against `funnel._signal` + this predicate on a shared fixture, so
    a future edit to either copy cannot silently diverge unnoticed."""
    if value is None:
        return False
    return abs(value) >= threshold
