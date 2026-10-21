"""Dated history a person says they kept: parsed, labelled "claimed, unverified", and kept apart.

THE RULE THIS FILE EXISTS TO KEEP
---------------------------------
A hound's record is what it bet, forward, on paper, recorded before the game (src/hounds/ledgers.py and the
referee). Nothing a person types can be that. So history is stored in its own table (store.py) under a label the
database itself enforces, it is never joined to a hound's ledger, stats or leaderboard row, and the only numbers
this module will produce from it are a count and a win-loss-push tally of what was CLAIMED. No units, no ROI,
no "profit": a described win is not evidence of one, and the product never says otherwise.

Rows that cannot be read (no date, a date in the future, a price that is not American odds, a result that is not
win, loss or push) are returned as `rejected` with the line number and the reason. Nothing is guessed to make a
row fit.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional, Tuple

from src.hounds.interview import privacy

LABEL = "claimed, unverified"
LABEL_CODE = "claimed_unverified"
MAX_ROWS = 500
MAX_PICK = 80
EARLIEST = date(1990, 1, 1)

_RESULTS = {"w": "W", "win": "W", "won": "W", "l": "L", "loss": "L", "lost": "L", "lose": "L", "p": "P", "push": "P",
            "pushed": "P", "tie": "P", "void": "P", "d": "P", "draw": "P"}
_SPLIT = re.compile(r"\t|\||,(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)")


def _parse_date(token: str) -> Optional[date]:
    token = token.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _parse_price(token: str) -> Optional[int]:
    m = re.fullmatch(r"\s*([+-]?)(\d{3,4})\s*", token)
    if not m:
        return None
    value = int(m.group(2))
    if value < 100:
        return None
    return -value if m.group(1) == "-" else value


def parse(text: str, *, today: date) -> Tuple[List[dict], List[dict]]:
    """(rows, rejected). `today` is injected so the 'not in the future' check is testable."""
    rows: List[dict] = []
    rejected: List[dict] = []
    lines = [ln for ln in str(text or "").replace("\r", "").split("\n")]
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        cells = [c.strip().strip('"') for c in _SPLIT.split(line)]
        if number == 1 and cells and cells[0].lower() in ("date", "day", "when"):
            continue                                            # a header row
        if len(rows) >= MAX_ROWS:
            rejected.append({"line": number, "text": line[:80], "reason": f"only the first {MAX_ROWS} rows are kept"})
            break
        if len(cells) < 4:
            rejected.append({"line": number, "text": line[:80], "reason": "needs four parts: date, pick, price, result"})
            continue
        day = _parse_date(cells[0])
        price = _parse_price(cells[-2])
        result = _RESULTS.get(cells[-1].strip().lower())
        pick = " ".join(", ".join(cells[1:-2]).split())
        if day is None:
            reason = "the date could not be read (use 2026-09-03)"
        elif day > today:
            reason = "that date is in the future"
        elif day < EARLIEST:
            reason = "that date is too old to be a betting record"
        elif price is None:
            reason = "the price must be American odds such as -110 or +120"
        elif result is None:
            reason = "the result must be W, L or P"
        elif not pick:
            reason = "no pick was named"
        else:
            reason = ""
        if reason:
            rejected.append({"line": number, "text": line[:80], "reason": reason})
            continue
        rows.append({"date": day.isoformat(), "pick": privacy.clean_text(pick, limit=MAX_PICK).replace("\n", " "),
                     "price": price, "result": result})
    rows.sort(key=lambda r: (r["date"], r["pick"], r["price"], r["result"]))
    return rows, rejected


def summary(rows: List[dict], rejected: Optional[List[dict]] = None) -> dict:
    """What the person CLAIMED, as counts. Never units, never a rate of return."""
    tally = {"W": 0, "L": 0, "P": 0}
    for r in rows:
        tally[r["result"]] += 1
    return {"label": LABEL, "rows": len(rows), "rejected": len(rejected or []), "claimed_wins": tally["W"],
            "claimed_losses": tally["L"], "claimed_pushes": tally["P"],
            "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
            "note": "Claimed by the member and not verified. It is not part of the hound's record."}
