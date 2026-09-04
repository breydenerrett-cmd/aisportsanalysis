"""The canonical wager: stored ONCE, referenced by every strategy that bets it.

WHY THIS MODULE EXISTS
-----------------------
`src/evolab/sweep.py` runs thousands of genomes over the same handful of
games. Most "strategies" that fire on a given game fire on the SAME side of
the SAME market at the SAME game -- the genome differs, the bet does not.
Counting "total strategy decisions" as if each were independent evidence is
exactly the six-figures-of-trivial-perturbation failure this program's owner
has explicitly ruled out (see docs/FACTORY_SCALE_DESIGN.md section 0). This
module gives every distinct real-world bet ONE canonical id, so a wager is
stored once and a strategy that selects it stores only a reference.

WHAT IS IN THE KEY, AND WHY (full justification: FACTORY_SCALE_DESIGN.md 1.1)
-------------------------------------------------------------------------------
`game_pk`, `market`, `side`, `line` -- and nothing else. In particular NOT
price: price moves continuously and keying on it would silently fragment one
real bet into many near-duplicate wager ids, which defeats the entire point
of this table. Price is stored as a field ON the wager, never part of its
identity. Not a price bucket either -- any bucket width is a tunable knob on
the dedup statistic itself, which a gate must never be tunable through.

APPEND-ONLY, NOT UPSERT
------------------------
A wager, once it happened, does not change. `WagerStore.add` raises on any
attempt to re-write an existing id with different content (`price`, `line`,
etc.) rather than silently picking a winner -- the same "no silent overwrite"
discipline `sweep.py`'s content-addressed `write()` already applies to sweep
reports. A second strategy claiming the same wager calls `add` again with
identical content, which is a no-op confirmation, not a second row.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Mapping


class WagerError(RuntimeError):
    """Raised when a wager cannot be recorded honestly."""


# The fields that make two wagers the SAME wager. Order fixed here (not just
# in canonical_wager_id's sorted-json call) so the docstring and the code can
# never drift about what identity means.
_KEY_FIELDS = ("game_pk", "market", "side", "line")


def canonical_wager_id(game_pk: int, market: str, side: str,
                        line: float | None = None) -> str:
    """The one true id for a (game, market, side, line) real-world bet.

    `line` defaults to `None` for moneyline markets, where there is no line
    to key on. Two calls with the same four values -- from any two strategies,
    any two worlds -- produce the same id; that is the whole mechanism.
    """
    if game_pk is None:
        raise WagerError("wager needs a game_pk; None is not a game")
    if not market:
        raise WagerError("wager needs a non-empty market")
    if side not in ("home", "away", "over", "under"):
        raise WagerError(f"unknown wager side {side!r}; expected one of "
                         "'home', 'away', 'over', 'under'")
    payload = {
        "game_pk": game_pk,
        "market": market,
        "side": side,
        "line": line,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Wager:
    """One canonical wager row. See module docstring for what `wager_id` keys on."""

    wager_id: str
    game_pk: int
    market: str
    side: str
    line: float | None
    price: float | None
    world_id: str | None
    source: str
    first_seen_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "wager_id": self.wager_id,
            "game_pk": self.game_pk,
            "market": self.market,
            "side": self.side,
            "line": self.line,
            "price": self.price,
            "world_id": self.world_id,
            "source": self.source,
            "first_seen_at": self.first_seen_at,
        }


class WagerStore:
    """In-memory append-only wager table with optional JSON-file persistence.

    Deliberately the smallest thing that satisfies "canonical wager stored
    once, strategies reference it": a dict keyed by `wager_id`. The identity
    fields (`_KEY_FIELDS`) of an existing row can never change once written;
    `price`/`world_id`/`source` on a re-`add` of the same id must match the
    first observation too, because a store that let those drift silently
    would defeat the audit trail this table exists to provide (design
    section 1.2's "written once, never mutated"). A conflicting re-write of
    ANY field on an existing id raises `WagerError` rather than choosing a
    winner.
    """

    def __init__(self):
        self._rows: dict[str, Wager] = {}

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, wager_id: str) -> bool:
        return wager_id in self._rows

    def get(self, wager_id: str) -> Wager | None:
        return self._rows.get(wager_id)

    def add(self, game_pk: int, market: str, side: str,
            line: float | None = None, price: float | None = None,
            world_id: str | None = None, source: str = "",
            first_seen_at: str | None = None) -> str:
        """Record a wager; return its `wager_id`. Idempotent for identical content.

        Raises `WagerError` if `wager_id` already exists with DIFFERENT
        content -- see class docstring. Returns the same id either way on
        success, so callers never need to branch on "was this new".
        """
        wager_id = canonical_wager_id(game_pk, market, side, line)
        candidate = Wager(
            wager_id=wager_id, game_pk=game_pk, market=market, side=side,
            line=line, price=price, world_id=world_id, source=source,
            first_seen_at=first_seen_at)
        existing = self._rows.get(wager_id)
        if existing is not None:
            # first_seen_at is provenance of WHEN it was first recorded, not
            # part of what a re-write must match -- two different first
            # observations still describe the identical wager.
            if existing.to_dict() | {"first_seen_at": None} != \
               candidate.to_dict() | {"first_seen_at": None}:
                raise WagerError(
                    f"wager {wager_id} already recorded with different "
                    f"content: existing={existing.to_dict()!r} "
                    f"incoming={candidate.to_dict()!r}")
            return wager_id
        self._rows[wager_id] = candidate
        return wager_id

    def all(self) -> tuple[Wager, ...]:
        """All rows, sorted by id -- deterministic iteration, per this
        codebase's general rule that reports are built from sorted iteration
        (see genome.py's enumeration-order contract)."""
        return tuple(self._rows[k] for k in sorted(self._rows))

    def to_dict(self) -> dict:
        return {"schema": "evolab.wagers/1",
                "wagers": [w.to_dict() for w in self.all()]}

    def write(self, path: str) -> str:
        """Write this store as deterministic, indented JSON to `path`."""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                    exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, sort_keys=True, indent=2)
            fh.write("\n")
        return path

    @classmethod
    def read(cls, path: str) -> "WagerStore":
        """Load a store previously written by `write`. Missing file -> empty store."""
        store = cls()
        if not os.path.exists(path):
            return store
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        for row in payload.get("wagers", []):
            store.add(game_pk=row["game_pk"], market=row["market"],
                      side=row["side"], line=row.get("line"),
                      price=row.get("price"), world_id=row.get("world_id"),
                      source=row.get("source", ""),
                      first_seen_at=row.get("first_seen_at"))
        return store
