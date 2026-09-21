"""Manual UFC fight results -- the append-only store `ufc result` writes to.

WHY THIS EXISTS
---------------
There is no legal, free, bulk source of UFC fight results to grade picks
against (docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md S5.2, S5.5):
UFC.com's own Terms of Use ban automated collection AND "any similar or
equivalent manual process ... to access, acquire, copy or monitor any
portion of the Site" -- so this store is filled by a person typing in a
result they read from a news or broadcast source, never by code that reads
UFC.com. `src.cli`'s `ufc result` subcommand is the one writer.

DESIGN: APPEND-ONLY, WHO AND WHEN RECORDED (matches
`src.appstate.card_ledger`'s own append-only convention). A correction is a
NEW row, never an edit of an old one -- `results_for_date` and `result_for_
fight` both return the newest matching row, so a correction supersedes
without erasing the mistake from the record. `entered_by` and `entered_utc`
ride on every row so a disputed grading can be traced to who typed it and
when, not just what it says.

MATCHING A PICK TO A RESULT: by FIGHTER NAMES, not by odds-API event_id --
a manual result is entered from a fight card, which names fighters, not
provider ids. `src.report.ufc_card.settle_for_date` is the one caller that
joins a result row back to a published pick, and does so by an
order-insensitive pair of names -- see `fighters_match` -- so "A vs B" and
"B vs A" (and a differently-capitalized or differently-spaced name) still
match the pick that was actually published.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paths import data_path

LOG = logging.getLogger(__name__)

DEFAULT_PATH = data_path("historical", "ufc_results.jsonl")

OUTCOME_WIN = "win"
OUTCOME_DRAW = "draw"
OUTCOME_NO_CONTEST = "no_contest"
OUTCOME_CANCELLED = "cancelled"
OUTCOMES = (OUTCOME_WIN, OUTCOME_DRAW, OUTCOME_NO_CONTEST, OUTCOME_CANCELLED)

# Every outcome except a clean win grades every pick on the bout VOID
# (src.report.ufc_card.settle_for_date) -- there is no "push" in a
# moneyline market, and a draw/no-contest/cancelled bout settled nobody's
# bet, win or lose.
VOID_OUTCOMES = (OUTCOME_DRAW, OUTCOME_NO_CONTEST, OUTCOME_CANCELLED)


class UfcResultsError(ValueError):
    """A malformed result entry -- refused before it is written, not after."""


def normalize_name(name: str) -> str:
    """Case- and whitespace-insensitive fighter-name key, for matching a
    typed result against a published pick's stored fighter names. Public --
    `src.report.ufc_card.settle_for_date` uses this directly to decide which
    side (home/away) a recorded winner corresponds to."""
    return " ".join(str(name or "").strip().lower().split())


# Back-compat alias for the name used inside this module before it was
# made public for settle_for_date's use.
_norm_name = normalize_name


def split_fight(fight: str) -> Optional[tuple]:
    """("Fighter A", "Fighter B") from a "Fighter A vs Fighter B" string, or
    None if it does not contain " vs " (case-insensitive)."""
    if not fight:
        return None
    lowered = fight.lower()
    idx = lowered.find(" vs ")
    if idx < 0:
        idx = lowered.find(" vs. ")
        seplen = 5
    else:
        seplen = 4
    if idx < 0:
        return None
    a = fight[:idx].strip()
    b = fight[idx + seplen:].strip()
    if not a or not b:
        return None
    return (a, b)


def fighters_match(fight: str, home_team: str, away_team: str) -> bool:
    """Whether `fight` ("A vs B") names the SAME two fighters as a published
    pick's `home_team`/`away_team`, in either order. Order-insensitive
    because a manual result and the odds feed have no reason to agree on
    which fighter is "home"."""
    parsed = split_fight(fight)
    if parsed is None:
        return False
    a, b = _norm_name(parsed[0]), _norm_name(parsed[1])
    home, away = _norm_name(home_team), _norm_name(away_team)
    return {a, b} == {home, away}


def record_result(*, date: str, fight: str, winner: Optional[str] = None,
                  outcome: str = OUTCOME_WIN, entered_by: str,
                  now: Optional[datetime] = None,
                  path: str | Path = DEFAULT_PATH) -> dict:
    """Append one manually-entered fight result. Never overwrites -- a
    correction is a new row; `result_for_fight` reads the newest match.

    Args:
        date: ISO date string the bout was fought on ("2026-09-26").
        fight: "Fighter A vs Fighter B", exactly as it should be matched
               against a published pick's fighter names.
        winner: The winning fighter's name, required when outcome="win".
                Must be one of the two names in `fight` (whitespace/case
                insensitive) -- a winner who is neither fighter almost
                always means the card names changed since the pick locked,
                and is refused here rather than silently mis-graded.
        outcome: One of OUTCOMES. "win" needs `winner`; the other three
                 (draw, no_contest, cancelled) grade every pick on the bout
                 VOID and ignore `winner`.
        entered_by: who is recording this (an email or handle) -- required,
                    never defaulted, so every row is attributable.
    """
    if outcome not in OUTCOMES:
        raise UfcResultsError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if not date:
        raise UfcResultsError("date is required")
    parsed = split_fight(fight or "")
    if parsed is None:
        raise UfcResultsError(
            f'fight must be "Fighter A vs Fighter B", got {fight!r}')
    if not entered_by:
        raise UfcResultsError("entered_by is required -- every result is attributed")

    if outcome == OUTCOME_WIN:
        if not winner:
            raise UfcResultsError('winner is required when outcome="win"')
        a, b = parsed
        if _norm_name(winner) not in (_norm_name(a), _norm_name(b)):
            raise UfcResultsError(
                f"winner {winner!r} is not one of the two fighters in {fight!r}")
    else:
        winner = None

    moment = now if now is not None else datetime.now(timezone.utc)
    row = {
        "date": date,
        "fight": fight,
        "winner": winner,
        "outcome": outcome,
        "entered_by": entered_by,
        "entered_utc": moment.isoformat(),
    }

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        if target.stat().st_size > 0:
            with target.open("rb") as rb:
                rb.seek(-1, 2)
                if rb.read(1) != b"\n":
                    f.write("\n")
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read_all(path: str | Path = DEFAULT_PATH) -> list:
    """Every row, in file order (oldest first). Corrupted lines are skipped,
    never fatal -- matches every other append-only reader in this repo."""
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line_num, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("ufc_results: %s:%s is not valid JSON; skipped", target, line_num)
    return rows


def results_for_date(date: str, path: str | Path = DEFAULT_PATH) -> list:
    """Every result row for `date`, in file order. A fight entered twice
    (a correction) appears twice here on purpose -- `result_for_fight`
    below is the one that resolves to the newest."""
    return [row for row in read_all(path) if row.get("date") == date]


def result_for_fight(date: str, home_team: str, away_team: str,
                     path: str | Path = DEFAULT_PATH) -> Optional[dict]:
    """The NEWEST manually-entered result on `date` whose fighter pair
    matches (home_team, away_team) in either order, or None if nothing was
    entered for this bout yet."""
    newest = None
    for row in results_for_date(date, path):
        if fighters_match(row.get("fight") or "", home_team, away_team):
            newest = row
    return newest
