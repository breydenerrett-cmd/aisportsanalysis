"""The one place that decides whether the UFC favourites card is still public.

WHY THIS EXISTS
---------------
On 2026-10-03 the owner paused the public UFC card. The rule behind it,
UFC_CARD_V1 (src/analysis/ufc_card.py), takes the market favourite in each
bout under -200, and in his words "UFC is one of the most volatile examples...
Do you understand that there needs to be actual analysis". New public UFC
favourites picks stop after 2026-10-03 and stay stopped until a real fight
analysis product replaces the rule. docs/decisions/UFC_FAVOURITES_PAUSED.md
has the decision, what stays, what stops and how to reverse it.

THE ONE VALUE
-------------
`favourites_rule_last_public_date` in config/ufc_public_card.json is the last
slate date the favourites rule is public. Two things act on it, and both read
it through this module so neither can disagree with the other:

  * scripts/capture_slot.sh -- the `card publish --sport mma` step runs only
    for a SLATE_DATE on or before it. The script runs
    `python3 -m src.appstate.ufc_public_card`, which prints the date.
  * api/card.py -- for sport=mma and a date AFTER it, GET /card/{date} answers
    with no picks, `paused: true` and PAUSED_REASON, and never builds a live
    favourites card (`paused_card` below). A date on or before it is served
    exactly as before, frozen rows untouched.

Nothing else changes. The rule file, the ledger rows already published, the
settle path, the record routes and `ufc capture` (odds capture) do not read
this file, so no published pick, row or record is altered by the pause.

WHEN THE FILE CANNOT BE READ: THE PAUSE HOLDS, ONLY THE PAST STAYS PUBLIC
------------------------------------------------------------------------
A missing, unreadable, malformed or nonsensical config falls back to
DEFAULT_LAST_PUBLIC_DATE, the date the owner chose, not to "no pause". The
deployed image did not copy config/ at the time this was written (the same
gap leaves config/example_accounts.json missing there), so a missing file is
a real state of the running app, and treating it as "publish favourites again"
would have quietly undone the decision in production. The effect of the
fallback is exactly the owner's decision: a date on or before 2026-10-03 is
still served and published as before, a later one is paused. It logs one
warning per distinct problem so the gap is visible instead of silent.

The config path is anchored at the repository root through src.paths (found
from that file's own location), never the process's working directory.

Stdlib only, like the rest of src/ (tests/test_api_boundary.py).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date as date_cls
from pathlib import Path
from typing import Optional, Sequence, Union

from src.paths import repo_root

CONFIG_KEY = "favourites_rule_last_public_date"

# The date the owner chose. Used only when the config cannot be read (see the
# module docstring); the config file is what normally decides.
DEFAULT_LAST_PUBLIC_DATE = "2026-10-03"

# What a reader is told. Plain words, no claim about results or returns.
PAUSED_REASON = (
    "UFC picks are paused. The old rule took the betting favourite in every "
    "fight, which is not analysis. Picks come back when each fight has a real "
    "breakdown behind it. Every UFC pick made so far stays on the record page."
)

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_log = logging.getLogger(__name__)
_WARNED: set = set()


def config_path() -> Path:
    """config/ufc_public_card.json under the repository root, found from
    src/paths.py's own location and not from the working directory."""
    return repo_root() / "config" / "ufc_public_card.json"


def parse_iso_date(value) -> Optional[date_cls]:
    """A real calendar date written YYYY-MM-DD, or None. Nothing looser is
    accepted: a different spelling of a date is not guessed at."""
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _warn_once(problem: str) -> None:
    if problem in _WARNED:
        return
    _WARNED.add(problem)
    _log.warning("UFC pause config: %s; using the built-in last public date %s",
                 problem, DEFAULT_LAST_PUBLIC_DATE)


def configured_last_public_date(path: Union[str, Path, None] = None) -> Optional[str]:
    """The config file's own value, or None when the file is missing,
    unreadable, not a JSON object, or holds no real YYYY-MM-DD date under
    `favourites_rule_last_public_date`. Never raises: whatever stops the file
    being read (a missing file, a bad path, a failure finding the path at all)
    reads as "unreadable", which falls back to the owner's own date, and the
    warning names the kind of failure."""
    target = None
    try:
        target = Path(path) if path is not None else config_path()
        # utf-8-sig: a file saved with a byte order mark (PowerShell does it)
        # must not read as "malformed" and silently fall back.
        with open(target, "r", encoding="utf-8-sig") as fh:
            parsed = json.load(fh)
    except Exception as exc:  # noqa: BLE001 -- this guards a public route; see above
        _warn_once(f"{getattr(target, 'name', 'the config')} could not be read "
                   f"({type(exc).__name__})")
        return None
    if not isinstance(parsed, dict):
        _warn_once(f"{target.name} is not a JSON object")
        return None
    value = parsed.get(CONFIG_KEY)
    if parse_iso_date(value) is None:
        _warn_once(f"{target.name} has no valid {CONFIG_KEY}")
        return None
    return value


def last_public_date(path: Union[str, Path, None] = None) -> str:
    """The last slate date the favourites rule is public: the config's value,
    or DEFAULT_LAST_PUBLIC_DATE when the config cannot be used. Always a
    valid YYYY-MM-DD string."""
    return configured_last_public_date(path) or DEFAULT_LAST_PUBLIC_DATE


def is_paused_for(date_str, path: Union[str, Path, None] = None) -> bool:
    """True when `date_str` is a real date AFTER the last public date. A
    string that is not a YYYY-MM-DD date is never "after" anything, so it is
    left to whatever handled it before this pause existed."""
    day = parse_iso_date(date_str)
    if day is None:
        return False
    return day > parse_iso_date(last_public_date(path))


def paused_card(date_str, path: Union[str, Path, None] = None) -> Optional[dict]:
    """The payload GET /card/{date}?sport=mma answers with when `date_str` is
    after the last public date, or None when that date is still public.

    No picks, `paused: true`, and the reason a reader sees. It carries no
    rule, no prices and no fighter: nothing here was built from the market.
    `paused_after` names the last public date, so the date in force can be read
    off a live response."""
    last = last_public_date(path)
    day = parse_iso_date(date_str)
    if day is None or day <= parse_iso_date(last):
        return None
    return {
        "date": date_str,
        "sport": "mma",
        "picks": [],
        "count": 0,
        "paused": True,
        "paused_after": last,
        "reason": PAUSED_REASON,
        "frozen": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python3 -m src.appstate.ufc_public_card`: print the last public date,
    one line and nothing else on stdout, and exit 0. This is what
    scripts/capture_slot.sh reads; a problem with the config goes to stderr as
    a warning and the printed date is the built-in one."""
    print(last_public_date())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
