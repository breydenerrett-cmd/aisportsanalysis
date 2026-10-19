"""The breeding program's public, read-only route (docs/PREREG_BREEDING.md).

    GET /hounds/breeding     the family tree: generations, parents, babies with status and record, culls,
                             refusals, the recent cycles, the next cycle time, and the eligibility table
                             (each member's settled forward bets against the 25 it needs)

No auth, like the rest of the race. Nothing here writes. The payload is built from small hash-chained
files (the breeding ledger, the learning ledger, the pack and challenger ledgers) and kept in memory until
one of them changes size or time stamp, so a request never re-reads an unchanged ledger.

MOUNT ORDER. ``/hounds/breeding`` is a literal path under ``/hounds/{id}``: this router is mounted BEFORE
``api.hounds`` (api/app.py does; tests/test_hounds_breeding.py pins it), or "breeding" would be read as a
hound id.
"""

from __future__ import annotations

import os
import threading

from fastapi import APIRouter, HTTPException, Response

router = APIRouter()

_CACHE = "public, max-age=60"
_LOCK = threading.Lock()
_MEMO: dict = {}


def _stamp(world) -> tuple:
    out = []
    for p in (world.breed_ledger, world.scope.events, world.scope.challenger_bets, world.champion_ledger,
              world.config):
        try:
            st = os.stat(p)
            out.append((str(p), st.st_size, st.st_mtime_ns))
        except (OSError, TypeError):
            out.append((str(p), None, None))
    return tuple(out)


def payload() -> dict:
    """The family tree, memoised on the input files' size and time stamp (the countdown is computed by
    the page from ``next_cycle_utc``, so a cached payload never shows a stale clock)."""
    from src.hounds.breeding import cycle
    world = cycle.World.default()
    key = _stamp(world)
    with _LOCK:
        hit = _MEMO.get("tree")
        if hit is not None and hit[0] == key:
            return hit[1]
    tree = cycle.family_tree(world)
    with _LOCK:
        _MEMO["tree"] = (key, tree)
    return tree


@router.get("/hounds/breeding")
def breeding(response: Response):
    try:
        tree = payload()
    except Exception:  # noqa: BLE001 -- an unreadable ledger is a calm 503, never a stack trace
        raise HTTPException(status_code=503, detail="the breeding program could not be read right now")
    response.headers["Cache-Control"] = _CACHE
    return tree
