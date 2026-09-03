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
        """The most bettor-favorable price observed for this selection --
        the highest American price when positive, the least negative when
        negative -- i.e. the greatest decimal payout, ties broken by book
        name for determinism."""
        rows = self.rows_for(selection_id)
        if not rows:
            return None
        return max(
            rows,
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
        rows = self.rows_for(selection_id)
        if not rows:
            return Friction(vig=0.0, book_count=0, staleness_seconds=0,
                            dispersion=0.0)
        opp_id = self._opposite_selection_id(selection_id)
        vig = 0.0
        if opp_id is not None:
            mine = {q.book: q.price_american for q in rows}
            theirs = {q.book: q.price_american
                      for q in self.rows_for(opp_id)}
            common = sorted(set(mine) & set(theirs))
            if common:
                vigs = [odds_math.margin([mine[b], theirs[b]])
                        for b in common]
                vig = sum(vigs) / len(vigs)
        implied = [odds_math.american_to_probability(q.price_american)
                   for q in rows]
        dispersion = (max(implied) - min(implied)) if implied else 0.0
        staleness = 0
        if as_of_utc is not None:
            try:
                latest = max(_parse_iso(q.observed_utc) for q in rows)
                staleness = int(
                    (_parse_iso(as_of_utc) - latest).total_seconds())
            except Exception:  # pragma: no cover -- best-effort only
                staleness = 0
        return Friction(vig=vig, book_count=len(rows),
                        staleness_seconds=max(staleness, 0),
                        dispersion=dispersion)

    @staticmethod
    def from_price_observations(game_pk: str, t: str,
                                 rows: Iterable[PriceObservation]
                                 ) -> "PricedBoard":
        return PricedBoard(game_pk=str(game_pk), t=t, quotes=tuple(rows))
