"""PriceBlindSnapshot and PricedBoard -- the two halves of one instant.

WHY THE SPLIT
--------------
docs/ARCHITECTURE_BETTING_ENGINE.md section 3 and synthesis-judge.md 4.2
both require that a `system`'s PROPOSE phase can physically not see a price.
Filtering a price out of a shared object is a rule that depends on every
future contributor remembering it exists; a TYPE that never carries the
field cannot be defeated by an oversight. `PriceBlindSnapshot` is that type:
it has no `board`, no `quotes`, no `price` attribute at all -- not `None`,
absent -- and `tests/test_engine_snapshot.py` proves this by walking the
dataclass's own field list and by reflection over every attribute name a
running PROPOSE call could think to ask for.

`PricedBoard` is the other half: the `PriceObservation` rows for the same
game at the same instant, built independently and handed only to PROJECT
(src/engine/analyze.py), never to a system's `propose()`.

Both are built from an `as_of` read: `PriceBlindSnapshot.from_asof` takes
the `src.core.asof.Snapshot` (the forward-store read: lineups, probables,
umpires, weather, boxscores) plus a game's point-in-time feature dict, and
`PricedBoard.from_price_observations` takes the `PriceObservation` rows this
project's board layer already produces (src/board/record.py,
src/board/project.py). Neither constructor performs I/O; both are pure
functions of their arguments, matching src.core.asof.as_of's own purity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping

from src.board.record import PriceObservation
from src.core import odds as odds_math
from src.core.asof import Snapshot as AsOfSnapshot

# Names a PROPOSE-side system must never be able to answer to, on either
# type. Kept as a frozenset (not a docstring rule) so a determined caller's
# reflection attempt has something concrete to fail against in the test, and
# so `PriceBlindSnapshot.__getattr__` and the test import the same list.
FORBIDDEN_PRICE_NAMES = frozenset({
    "board", "quotes", "price", "prices", "price_american", "odds",
    "book", "books", "consensus", "consensus_fair", "friction",
    "priced_board", "quote", "best", "line_price",
})


class SnapshotError(RuntimeError):
    """Raised for a malformed snapshot construction request."""


def _parse_iso(value: str) -> datetime:
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class PointMeta:
    """Board-shaped facts a system is allowed to know that are NOT prices:
    which markets exist and how many books quote them. A count of books is
    not a price; a genome's eligibility gate (`min_books`) and its market
    routing already depend on exactly these two facts in the pre-existing
    evolab decision path (src/evolab/decide.py), so they travel here rather
    than being smuggled back in through a price-shaped field.
    """

    observed_utc: str
    simultaneous: bool = False
    staleness_seconds: int = 0


@dataclass(frozen=True, slots=True)
class PriceBlindSnapshot:
    """Everything a PROPOSE-phase system may see. Structurally, never a price.

    No `board`, `quotes` or `price*` field exists on this dataclass -- not a
    filtered one, an absent one. `__getattr__` additionally raises a named
    error for every entry in FORBIDDEN_PRICE_NAMES so a system that tries a
    dynamic lookup (`getattr(snapshot, "board", None)`) gets a loud refusal
    rather than a silent `None` it could branch on.
    """

    game_pk: str
    t: str
    point_class: str
    features: Mapping[str, float]
    available_markets: tuple = ()
    books_by_market: Mapping[str, int] = field(default_factory=dict)
    point_meta: PointMeta | None = None
    lineup_posted: bool = False
    assumption_exposure: Mapping[str, int] = field(default_factory=dict)
    fingerprint: str = ""
    # Whether `from_asof` was ever handed a real `src.core.asof.Snapshot`
    # (True) versus never having a `game_pk` to read one with at all
    # (False). `assumption_exposure` alone cannot distinguish these: an
    # as_of read that found zero degraded fields also leaves
    # `assumption_exposure` empty. `known_at_grade` (src/engine/analyze.py)
    # must not treat "no read happened" as "read happened, nothing
    # degraded" -- the former used to fail open to grade A with zero
    # evidence for it; this field is what lets analyze() tell the two
    # apart and grade the no-read case D instead.
    asof_read: bool = False

    def __getattr__(self, name):
        # Reached only when normal slot lookup fails -- cannot shadow a real
        # field, and touches no attribute of self (no infinite recursion on
        # a half-built instance).
        if name.lower() in FORBIDDEN_PRICE_NAMES:
            raise AttributeError(
                f"PriceBlindSnapshot has no {name!r} and never will. A "
                "PROPOSE-phase system sees the price-blind snapshot only; "
                "prices exist solely on PricedBoard, which PROJECT (never "
                "PROPOSE) is handed (docs/ENGINE_CONTRACT.md)")
        raise AttributeError(f"PriceBlindSnapshot has no attribute {name!r}")

    def differential(self, feature: str):
        """away_<feature> - home_<feature>, or None if either side is absent.

        Mirrors src.evolab.decide.WorldView.differential's convention
        exactly, so an adapter wrapping an evolab genome can reuse this
        method rather than re-deriving the sign.
        """
        away = self.features.get("away_" + feature)
        home = self.features.get("home_" + feature)
        if away is None or home is None:
            return None
        return away - home

    def books_for(self, market: str) -> int:
        return int(self.books_by_market.get(market, 0))

    @staticmethod
    def from_asof(*, game_pk: str, t: str, point_class: str,
                  features: Mapping[str, float],
                  as_of_snapshot: AsOfSnapshot | None = None,
                  available_markets: Iterable[str] = (),
                  books_by_market: Mapping[str, int] | None = None,
                  point_meta: PointMeta | None = None,
                  lineup_posted: bool = False,
                  fingerprint: str = "") -> "PriceBlindSnapshot":
        """Build from a `src.core.asof.Snapshot` plus point-in-time features.

        `as_of_snapshot`'s `fields` mapping (lineups, probables, umpires,
        weather, boxscores) carries no price of any kind by construction
        (src.core.asof never reads a price store), so its per-field
        provenance is folded straight into `assumption_exposure` as a count
        of D-graded (unreconstructable-timing) fields -- the same
        "assumption_exposure" vocabulary synthesis-judge.md 4.2 names on
        `Snapshot`.
        """
        exposure: dict[str, int] = {}
        if as_of_snapshot is not None:
            for name, obs in as_of_snapshot.fields.items():
                key = f"{obs.known_at_grade}:{name}"
                exposure[key] = exposure.get(key, 0) + 1
        return PriceBlindSnapshot(
            game_pk=str(game_pk),
            t=t,
            point_class=point_class,
            features=dict(features),
            available_markets=tuple(available_markets),
            books_by_market=dict(books_by_market or {}),
            point_meta=point_meta,
            lineup_posted=lineup_posted,
            assumption_exposure=exposure,
            fingerprint=fingerprint,
            asof_read=as_of_snapshot is not None,
        )


@dataclass(frozen=True, slots=True)
class Consensus:
    fair_probability: float
    n_books: int


@dataclass(frozen=True, slots=True)
class Friction:
    vig: float
    book_count: int
    staleness_seconds: int
    dispersion: float  # max - min implied probability across quoting books


# A book's latest quote for a selection counts toward `best()`,
# `Friction.book_count` and `Friction.dispersion` only while it is no older
# than this many seconds relative to the board's own `t`. Matches
# `src.engine.adversaries.StaleBook`'s default `max_staleness_seconds`
# deliberately: a book excluded here by staleness is exactly the book that
# adversary would separately veto as no longer a live tradeable price, so
# the two thresholds must agree rather than silently disagree on what
# "stale" means.
STALE_QUOTE_SECONDS = 1800


def _latest_per_book(rows: Iterable[PriceObservation]) -> tuple:
    """One row per book: the row with the latest `observed_utc`. `rows`
    must already be stop-at-T truncated (`PricedBoard`'s own contract), so
    this is genuinely "this book's latest quote at t", never a future
    quote leaking in."""
    latest: dict[str, PriceObservation] = {}
    for r in rows:
        cur = latest.get(r.book)
        if cur is None or _parse_iso(r.observed_utc) > _parse_iso(cur.observed_utc):
            latest[r.book] = r
    return tuple(sorted(latest.values(), key=lambda q: q.book))


def _fresh_latest_per_book(rows: Iterable[PriceObservation], t: str, *,
                            max_staleness_seconds: int = STALE_QUOTE_SECONDS
                            ) -> tuple:
    """Each book's latest quote at t (`_latest_per_book`), minus any book
    whose latest quote has already gone stale by `t` -- a book that quoted
    once, hours before `t`, and never again is not "quoting the selection
    at t" in any sense `best()`/`book_count`/`dispersion` should honor.
    When `t` (or a quote's own `observed_utc`) is not a parseable
    timestamp, that quote is kept rather than guessed away -- best-effort,
    matching `friction()`'s own pre-existing staleness handling."""
    per_book = _latest_per_book(rows)
    try:
        t_dt = _parse_iso(t)
    except Exception:  # pragma: no cover -- defensive, mirrors friction()
        return per_book
    fresh = []
    for r in per_book:
        try:
            age = (t_dt - _parse_iso(r.observed_utc)).total_seconds()
        except Exception:  # pragma: no cover -- defensive, mirrors friction()
            fresh.append(r)
            continue
        if age <= max_staleness_seconds:
            fresh.append(r)
    return tuple(fresh)


@dataclass(frozen=True, slots=True)
class PricedBoard:
    """The PriceObservation rows for one game at one instant. PROJECT-only."""

    game_pk: str
    t: str
    quotes: tuple = ()

    def selections(self) -> tuple:
        return tuple(sorted({q.selection_id for q in self.quotes}))

    def rows_for(self, selection_id: str) -> tuple:
        return tuple(sorted(
            (q for q in self.quotes if q.selection_id == selection_id),
            key=lambda q: q.book))

    def best(self, selection_id: str) -> PriceObservation | None:
        """The most bettor-favorable price among each quoting book's LATEST
        quote at `t` -- the highest American price when positive, the
        least negative when negative -- i.e. the greatest decimal payout,
        ties broken by book name for determinism. A book's own stale or
        superseded quote from earlier in `t`'s history is never a
        candidate: only `_fresh_latest_per_book`'s one-row-per-book,
        staleness-bounded set is considered."""
        rows = self.rows_for(selection_id)
        if not rows:
            return None
        fresh = _fresh_latest_per_book(rows, self.t)
        if not fresh:
            return None
        return max(
            fresh,
            key=lambda q: (odds_math.american_to_decimal(q.price_american),
                           q.book))

    def _opposite_selection_id(self, selection_id: str) -> str | None:
        """The other side of the same two-way market/subject/line, if it is
        on this board. Two-way only (the shapes this project prices today);
        a three-plus-way market has no single opposite and is not devigged
        here."""
        rows = self.rows_for(selection_id)
        if not rows:
            return None
        row = rows[0]
        candidates = {
            q.selection_id for q in self.quotes
            if q.market_key == row.market_key
            and q.line == row.line
            and q.subject_id == row.subject_id
            and q.selection_id != selection_id
        }
        if len(candidates) != 1:
            return None
        return next(iter(candidates))

    def consensus(self, selection_id: str, *, min_books: int = 1,
                  method: str = "proportional") -> Consensus | None:
        """De-vigged fair probability for `selection_id`, averaged across
        every book that quotes BOTH sides of its market at this instant.
        None (consensus-undefined) when fewer than `min_books` books qualify
        -- ARCHITECTURE_BETTING_ENGINE.md guard M7: consensus-undefined is an
        explicit friction state, never silently defaulted to 0.5.
        """
        opp_id = self._opposite_selection_id(selection_id)
        if opp_id is None:
            return None
        mine = {q.book: q.price_american for q in self.rows_for(selection_id)}
        theirs = {q.book: q.price_american for q in self.rows_for(opp_id)}
        books = sorted(set(mine) & set(theirs))
        if len(books) < min_books:
            return None
        fair_probs = []
        for book in books:
            fair_a, _fair_b = odds_math.devig_two_way(
                mine[book], theirs[book], method=method)
            fair_probs.append(fair_a)
        return Consensus(
            fair_probability=sum(fair_probs) / len(fair_probs),
            n_books=len(books),
        )

    def friction(self, selection_id: str, *, as_of_utc: str | None = None
                 ) -> Friction:
        """`book_count`/`dispersion` describe the board at `as_of_utc`
        (falling back to `self.t`): one row per book -- its own latest
        quote -- excluding any book whose latest quote has already gone
        stale by that instant (`_fresh_latest_per_book`, shared with
        `best()` so the two never disagree about which books are
        "quoting"). `vig` still devigs off each book's own latest quote,
        not a mix of every historical row that book ever posted."""
        rows = self.rows_for(selection_id)
        if not rows:
            return Friction(vig=0.0, book_count=0, staleness_seconds=0,
                            dispersion=0.0)
        fresh = _fresh_latest_per_book(rows, as_of_utc or self.t)
        opp_id = self._opposite_selection_id(selection_id)
        vig = 0.0
        if opp_id is not None:
            opp_rows = self.rows_for(opp_id)
            opp_fresh = _fresh_latest_per_book(opp_rows, as_of_utc or self.t)
            mine = {q.book: q.price_american for q in fresh}
            theirs = {q.book: q.price_american for q in opp_fresh}
            common = sorted(set(mine) & set(theirs))
            if common:
                vigs = [odds_math.margin([mine[b], theirs[b]])
                        for b in common]
                vig = sum(vigs) / len(vigs)
        implied = [odds_math.american_to_probability(q.price_american)
                   for q in fresh]
        dispersion = (max(implied) - min(implied)) if implied else 0.0
        staleness = 0
        if as_of_utc is not None:
            try:
                latest = max(_parse_iso(q.observed_utc) for q in rows)
                staleness = int(
                    (_parse_iso(as_of_utc) - latest).total_seconds())
            except Exception:  # pragma: no cover -- best-effort only
                staleness = 0
        return Friction(vig=vig, book_count=len(fresh),
                        staleness_seconds=max(staleness, 0),
                        dispersion=dispersion)

    @staticmethod
    def from_price_observations(game_pk: str, t: str,
                                 rows: Iterable[PriceObservation]
                                 ) -> "PricedBoard":
        return PricedBoard(game_pk=str(game_pk), t=t, quotes=tuple(rows))
