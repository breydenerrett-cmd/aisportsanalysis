"""Credit-balance log: one row every time the odds provider's quota is read.

WHY THIS COSTS NOTHING AND WHY IT MATTERS ANYWAY
-------------------------------------------------
dense.run() and prop_listing.run() already read `odds_provider.quota()` before
spending a single credit -- the free sports-list endpoint, and the only
ordering under which a credit floor can actually hold (see dense.py's own
comment on this). That call already returns the account's current balance and
what the LAST billed request cost; the only thing missing was writing it down.

A history of the balance over time turns "credits ran out" from a surprise
into a graph: burn rate per day, whether the approved layers add up to the
~132/day envelope docs/COLLECTION_POLICY.md allows, and how many days of
runway remain -- none of which was answerable before, because nobody was
recording the number.

WHY THIS MODULE NEVER RAISES
-----------------------------
Every call site this hooks into (dense.py's two quota checks, prop_listing's
one, prop_prices' own) is on the critical path of a paid capture. A log write
failing -- a full disk, a permissions error, a test's forward-store guard
catching an unredirected default path -- must never take the capture down
with it. Every public function here therefore fails silently and returns a
sentinel rather than raising, matching the `poll_hook` convention dense.py
already uses for exactly this reason.

APPEND-ONLY, LIKE EVERY OTHER FORWARD STORE
--------------------------------------------
One row per quota read, appended to data/processed/credit_log.jsonl. Never
rewritten, never deduplicated in place.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.paths import processed_path

LOG = logging.getLogger(__name__)

DEFAULT_STORE = processed_path("credit_log.jsonl")


def log(remaining, used_last, caller, store=DEFAULT_STORE, now=None) -> bool:
    """Append one {utc, credits_remaining, credits_used_last, caller} row.

    `remaining`/`used_last` are passed straight through from the provider's
    quota response -- already ints or None; nothing is invented here. Returns
    True on a successful write, False on ANY failure. Never raises: a caller
    on a paid-capture critical path must not go down because a log line
    could not be written.
    """
    try:
        moment = _now(now)
        row = {
            "utc": _utc_iso(moment),
            "credits_remaining": remaining,
            "credits_used_last": used_last,
            "caller": caller,
        }
        target = Path(store)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            if _ends_ragged(target):
                handle.write("\n")
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001 -- a log write must never break its caller
        # DEBUG, not WARNING: the most common cause of this path firing is a
        # test's forward-store guard catching an unredirected default path
        # (tests/__init__.py), which is the guard working as intended, not an
        # operational fault. A real disk/permissions failure in production is
        # still discoverable here with logging turned up, without drowning
        # every dense/prop_listing/prop_prices test run in a traceback for a
        # side-effect write nothing in those tests asserts on.
        LOG.debug("creditlog: failed to append a row (%s: %s)",
                  type(exc).__name__, exc)
        return False


def read(store=DEFAULT_STORE) -> list:
    """Every row in the store. A corrupt line is logged and skipped."""
    target = Path(store)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("creditlog: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


def latest(store=DEFAULT_STORE):
    """The most recently written row, or None if the store is empty/missing.

    Rows are appended in observation order, so the last line IS the latest
    reading -- no timestamp parsing needed to find it.
    """
    rows = read(store)
    return rows[-1] if rows else None


def _ends_ragged(target) -> bool:
    """True when the file ends mid-line -- the signature of an interrupted append."""
    target = Path(target)
    if not target.exists() or not target.stat().st_size:
        return False
    with target.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1) != b"\n"


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(
            "creditlog now() must return a timezone-aware datetime; a naive "
            "observation time cannot honestly timestamp a credit reading")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv=None, store=None) -> int:
    """`python3 -m src.cli credits` wires here; also runnable standalone."""
    row = latest(store if store is not None else DEFAULT_STORE)
    if row is None:
        print("credit log: no rows yet")
        return 0
    print(f"credit log: {row.get('utc')}  "
          f"remaining={row.get('credits_remaining')}  "
          f"used_last={row.get('credits_used_last')}  "
          f"caller={row.get('caller')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
