"""The one place that decides whether the public MLB value picks are still public.

WHY THIS EXISTS
---------------
On 2026-10-16 the owner paused the public MLB value picks (the MAIN and PLUS
props, the moneyline picks and the fills of the V2 value card). The loss
diagnosis (docs/research/loss_diagnosis/00_SYNTHESIS.md) found that every bet
was priced worse than the market's own number (a mean premium of +2.36
probability points), that the model's disagreement with the market carries no
information (a blend weight of zero or below, on 6,818 priced prop contracts
and on 2024 moneylines), and that the card ranks by exactly that disagreement.
Picks stay paused until a forward test registered in advance clears a
closing-line-value bar (docs/handoff/WEEK_2026-10-16_PLAN.md).
docs/decisions/MLB_VALUE_PICKS_PAUSED.md has the decision, what stops, what
continues and how to reverse it. This module is the MLB twin of
src/appstate/ufc_public_card.py and has the same contract.

THE ONE VALUE
-------------
`value_picks_last_public_date` in config/mlb_public_card.json is the last slate
date the MLB value picks are public. Three things act on it, and all read it
through this module so none can disagree with another:

  * src/cli.py `card publish` for sport mlb -- for a date AFTER it, the V1 and
    V2 publishes are not made and `  no card: value picks paused since ...`
    is printed (scripts/capture_slot.sh and scripts/afternoon_slate.sh treat a
    `  no card:` line as a fact about the slate, never an error). The three
    registered V2 shadows (A, C, E) keep publishing under `--rule all`: they
    are forward tests, not public.
  * api/card.py -- for sport=mlb and a date after it, GET /card/{date} answers
    `paused: true`, no picks, the reason and the links to use instead.
  * web/js/card.js -- renders that reason where the card would be.

Nothing else changes: the ledgers, the settle path, the record routes, the
brief, the board, `mlb_value_shadow` and odds capture do not read this file.

WHEN THE FILE CANNOT BE READ: THE PAUSE HOLDS, ONLY THE PAST STAYS PUBLIC
------------------------------------------------------------------------
A missing, unreadable, malformed or nonsensical config falls back to
DEFAULT_LAST_PUBLIC_DATE, the date the owner chose, not to "no pause". The
deployed image has not always copied config/, so a missing file is a real
state of the running app, and treating it as "publish picks again" would have
quietly undone the decision in production. One warning per distinct problem is
logged so the gap is visible instead of silent.

The config path is anchored at the repository root through src.paths, never
the process's working directory. Stdlib only, like the rest of src/.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date as date_cls
from pathlib import Path
from typing import Optional, Sequence, Union

from src.paths import repo_root

CONFIG_KEY = "value_picks_last_public_date"

# The date the owner chose. Used only when the config cannot be read (see the
# module docstring); the config file is what normally decides.
DEFAULT_LAST_PUBLIC_DATE = "2026-10-16"

# What a reader is told. Plain words, no claim about results or returns.
PAUSED_REASON = (
    "MLB picks are paused. Our picks paid a premium over the market's own "
    "price, and our forecasts carried nothing the market did not already "
    "know. Picks come back only if a test we register in advance shows we "
    "beat the closing price. The daily brief and the price board continue, "
    "and every pick made so far stays on the record page."
)

# Where a reader goes instead: the record page and the price board are routes
# of the app (web/js/main.js), the sample brief is its own page (web/sample.html).
PAUSED_LINKS = (
    {"label": "VIEW THE RECORD", "href": "#/record-card"},
    {"label": "SEE A SAMPLE BRIEF", "href": "sample.html"},
    {"label": "OPEN THE PRICE BOARD", "href": "#/odds"},
)

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_log = logging.getLogger(__name__)
_WARNED: set = set()


def config_path() -> Path:
    """config/mlb_public_card.json under the repository root, found from
    src/paths.py's own location and not from the working directory."""
    return repo_root() / "config" / "mlb_public_card.json"


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
    _log.warning("MLB pause config: %s; using the built-in last public date %s",
                 problem, DEFAULT_LAST_PUBLIC_DATE)


def configured_last_public_date(path: Union[str, Path, None] = None) -> Optional[str]:
    """The config file's own value, or None when the file is missing,
    unreadable, not a JSON object, or holds no real YYYY-MM-DD date under
    `value_picks_last_public_date`. Never raises: whatever stops the file
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
    """The last slate date the value picks is public: the config's value,
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
    """The payload GET /card/{date} (sport mlb) answers with when `date_str` is
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
        "sport": "mlb",
        "picks": [],
        "count": 0,
        "paused": True,
        "paused_after": last,
        "reason": PAUSED_REASON,
        "links": [dict(link) for link in PAUSED_LINKS],
        "frozen": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python3 -m src.appstate.mlb_public_card`: print the last public date,
    one line and nothing else on stdout, and exit 0. This is what
    scripts/capture_slot.sh reads; a problem with the config goes to stderr as
    a warning and the printed date is the built-in one."""
    print(last_public_date())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
