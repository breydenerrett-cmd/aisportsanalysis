"""Test-split seal: an auditable count of how often a holdout has been looked at.

WHY THIS EXISTS
---------------
A held-out test split is only evidence while it is unseen. Every evaluation against
it spends some of its ability to tell the truth, because whatever you learn feeds
back into the next decision -- which features to add, which hyperparameters to keep,
whether to try again.

The discipline is "touch it once, at the very end". The discipline fails silently:
nothing in a normal codebase counts the touches, so a split gets evaluated four
times over an afternoon and still gets reported as held-out.

That is not hypothetical. It is exactly what happened here. The 2025 test split was
evaluated four separate times during development -- once for the locked model, twice
comparing team-only against team-plus-pitcher features, and once checking the
prediction distribution. Each was individually reasonable. Together they mean every
number reported from that split is optimistically biased by an unknown amount.

So the count is now recorded on disk, and any evaluation past the first is reported
as such rather than being quietly indistinguishable from the first.

THE ONLY GENUINELY SEALED SPLIT IS THE FUTURE
---------------------------------------------
A split carved out of data you already hold can always be peeked at, and the seal
depends on discipline. Games that have not been played yet cannot be peeked at by
anyone, including by accident. Forward evaluation on unplayed games is therefore
strictly stronger evidence than any historical holdout, and it is what the
validation plan ultimately rests on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.paths import repo_root

# Committed to version control, unlike everything under data/. This is a
# research-integrity RECORD, not generated data -- it belongs next to
# docs/VALIDATION_CRITERIA.md, and a holdout count that vanishes on a fresh
# checkout enforces nothing.
DEFAULT_SEAL = repo_root() / "docs" / "test_split_seal.json"

# Past this many evaluations a split is not a holdout in any meaningful sense.
BURN_THRESHOLD = 1


class SealError(RuntimeError):
    """Raised when the seal record cannot be read or written."""


def read_seal(path=DEFAULT_SEAL) -> dict:
    target = Path(path)
    if not target.exists():
        return {"splits": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SealError(f"seal at {target} is not valid JSON") from exc
    if not isinstance(data, dict) or "splits" not in data:
        raise SealError(f"seal at {target} is malformed")
    return data


def write_seal(seal: dict, path=DEFAULT_SEAL) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(seal, indent=1, sort_keys=True), encoding="utf-8")
    return str(target)


def split_id(first_date, last_date, n) -> str:
    """Identity for a split. Re-cutting the same boundaries is the same split.

    Deliberately keyed on the boundaries rather than on a name, so renaming a split
    or rebuilding the table cannot reset its count.
    """
    return f"{first_date}..{last_date}:n={n}"


def record_evaluation(first_date, last_date, n, reason=None,
                      path=DEFAULT_SEAL, now=None) -> dict:
    """Record one evaluation against a split and report its status.

    Returns the running count and whether the split is now burned. Callers are
    expected to surface that rather than swallow it -- the point is that a second
    look is visibly different from a first.
    """
    seal = read_seal(path)
    key = split_id(first_date, last_date, n)
    entry = seal["splits"].setdefault(
        key, {"evaluations": 0, "first_evaluated": None, "reasons": []})

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    entry["evaluations"] += 1
    entry["last_evaluated"] = stamp
    if entry["first_evaluated"] is None:
        entry["first_evaluated"] = stamp
    if reason:
        entry["reasons"].append({"at": stamp, "reason": reason})

    write_seal(seal, path)
    return status(first_date, last_date, n, path=path)


def status(first_date, last_date, n, path=DEFAULT_SEAL) -> dict:
    """How many times this split has been evaluated, and whether it is burned."""
    seal = read_seal(path)
    key = split_id(first_date, last_date, n)
    entry = seal["splits"].get(key)
    count = entry["evaluations"] if entry else 0
    burned = count > BURN_THRESHOLD
    return {
        "split": key,
        "evaluations": count,
        "burned": burned,
        "first_evaluated": entry.get("first_evaluated") if entry else None,
        "last_evaluated": entry.get("last_evaluated") if entry else None,
        "reasons": entry.get("reasons", []) if entry else [],
        "warning": (
            f"This split has been evaluated {count} times. A holdout is evidence "
            "only while unseen; every look feeds back into the next decision. "
            "Numbers from it are optimistically biased by an unknown amount and "
            "must not be reported as out-of-sample."
        ) if burned else None,
    }


def declare_burned(first_date, last_date, n, reason,
                   evaluations, path=DEFAULT_SEAL, now=None) -> dict:
    """Record a split as already-burned from evaluations made before sealing existed.

    Backdating a count is normally the sort of thing that should be impossible. It
    is allowed here precisely once, for the honest declaration of history that
    predates this module -- and it is a named, explicit function rather than a
    quiet increment, so it shows up in a diff.
    """
    seal = read_seal(path)
    key = split_id(first_date, last_date, n)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    seal["splits"][key] = {
        "evaluations": int(evaluations),
        "first_evaluated": stamp,
        "last_evaluated": stamp,
        "declared_burned": True,
        "reasons": [{"at": stamp, "reason": reason}],
    }
    write_seal(seal, path)
    return status(first_date, last_date, n, path=path)
