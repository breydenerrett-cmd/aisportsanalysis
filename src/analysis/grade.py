"""How much do we actually KNOW about this game? A letter, and why.

WHAT THE OWNER ASKED FOR, 2026-09-12
------------------------------------
    "tomorrow's bets have been pre-analyzed and screened thoroughly and
     have starter ideas for what's looking A+ Grade setups, B Grade and
     everything below a C+"

WHAT A LETTER CAN HONESTLY MEAN HERE
------------------------------------
Not "how much we expect to win". Five measurements in
docs/DOES_THE_MODEL_BEAT_THE_MARKET.md say our own number does not beat
the price, and scripts/probe_prop_value.py measured that selecting on our
disagreement with the price returned -13.4% against a -9.1% control. A
grade computed from "how far our number clears the price" would put an A+
on the signal we have measured to mislead.

So this is a KNOWLEDGE grade: how complete our read of the game is, from
facts that exist before any price is looked at. A bet made on a game where
the lineup has posted, both starters are named, and nine books have priced
it in the last hour is a different thing from a bet made at breakfast on a
game with none of that -- whatever the number says. That difference is what
the letter measures, and the page says so in one line.

The "+" is the one place a price enters, and only on the top grade: an A
becomes A+ when the pick's own model number clears the break-even the price
demands. It is a note, not a reason -- the same caveat as above applies to
that number -- and the legend says so.

THE BANDS, FIXED HERE BEFORE ANY SLATE WAS SCORED
--------------------------------------------------
Four CORE facts. Each is a yes/no about the game, not a judgement:

    lineups    both clubs have posted a batting order
    starters   both probable starters are named
    board      a priced board at or above the consensus floor
               (src.analysis.prices.MIN_BOOKS books)
    fresh      that board was captured within FRESH_SECONDS

Supporting facts are the dossier sections that inform the model but are
not decisive on their own: team form, starter logs, bullpen workload,
weather, park. Each one the dossier could not fill is a supporting gap.

    A   all four core facts, at most one supporting gap
    B   all four core facts with two or more supporting gaps,
        OR three core facts where the one missing is `fresh` or `board`
        (a thin or stale board is a thin read, not a blind one)
    C   a board exists but lineups OR starters are missing
    D   no board at all, or neither lineups nor starters

Everything below C is "not enough to call it a setup", which is the line
the owner drew. The bands are not tuned after the fact to make a slate look
busier; a test pins them.

Pure. No I/O, no clock of its own, no api/ import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional, Sequence

from src.analysis import prices as prices_mod

# A board older than this is a different board: the capture runs every
# fifteen minutes, so this is four cycles missed, and a moneyline can move
# a full point in that time on a lineup or a scratch.
FRESH_SECONDS = 60 * 60

# The dossier sections that inform a read without deciding it. Named here
# so the grade cannot quietly start counting a section nobody agreed
# mattered.
SUPPORTING_SECTIONS = ("teams", "starters", "bullpen", "weather", "park")

# A lineup is a batting order, not a partial one.
LINEUP_LENGTH = 9

LETTERS = ("A", "B", "C", "D")


def _sides_posted(lineups: Optional[Mapping]) -> int:
    """How many of the two clubs have a full batting order in the section.

    Tolerant of the two shapes the pipeline has used -- a bare list of nine
    batters per side, or a dict carrying that list -- and strict about the
    count: eight names is not a lineup.
    """
    if not isinstance(lineups, Mapping):
        return 0
    posted = 0
    for side in ("away", "home"):
        value = lineups.get(side)
        if isinstance(value, Mapping):
            value = (value.get("batters") or value.get("lineup")
                     or value.get("order") or value.get("players"))
        if isinstance(value, (list, tuple)) and len(value) >= LINEUP_LENGTH:
            posted += 1
    return posted


def knowledge_grade(*, game: Mapping, data_quality: Mapping,
                    board_summary: Mapping, lineups: Optional[Mapping] = None,
                    gaps: Optional[Mapping] = None) -> dict:
    """The letter, the four core facts, the supporting gaps, and one sentence.

    `game` is the schedule row (probable ids live there). `data_quality` and
    `board_summary` are the slate row's own census, built by
    src/analysis/gamepayload.py; `lineups` is the dossier section when it
    exists; `gaps` is the dossier's own record of what it could not fill.
    """
    gaps = dict(gaps or (data_quality or {}).get("gaps") or {})

    sides = _sides_posted(lineups)
    core = {
        "lineups": sides >= 2,
        "starters": bool(game.get("away_probable_id")) and bool(game.get("home_probable_id")),
        "board": bool((board_summary or {}).get("has_board"))
                 and (board_summary or {}).get("books") is not None
                 and int(board_summary["books"]) >= prices_mod.MIN_BOOKS,
        "fresh": (board_summary or {}).get("age_seconds") is not None
                 and float(board_summary["age_seconds"]) <= FRESH_SECONDS,
    }
    supporting_gaps = [name for name in SUPPORTING_SECTIONS if name in gaps]

    has_board = bool((board_summary or {}).get("has_board"))
    core_count = sum(1 for v in core.values() if v)
    missing_core = [k for k, v in core.items() if not v]

    if not has_board or (not core["lineups"] and not core["starters"]):
        letter = "D"
    elif not core["lineups"] or not core["starters"]:
        letter = "C"
    elif core_count == 4:
        letter = "A" if len(supporting_gaps) <= 1 else "B"
    elif core_count == 3 and missing_core[0] in ("fresh", "board") \
            and len(supporting_gaps) <= 1:
        letter = "B"
    else:
        letter = "C"

    return {
        "letter": letter,
        "plus": False,
        "grade": letter,
        "core": core,
        "sides_posted": sides,
        "supporting_gaps": supporting_gaps,
        "why": _why(letter, core, sides, board_summary or {}, supporting_gaps),
    }


def with_plus(grade: Mapping, *, model_probability: Optional[float],
              breakeven: Optional[float]) -> dict:
    """An A becomes A+ when the pick's own number clears the break-even.

    Only on an A. A B+ would say "we know less but the price is nice",
    which is the reverse of the order the owner set: likely first, then
    price. Only when both numbers exist; a missing number is not a pass.
    """
    out = dict(grade)
    out["plus"] = False
    out["grade"] = out.get("letter")
    if (out.get("letter") == "A" and model_probability is not None
            and breakeven is not None
            and float(model_probability) > float(breakeven)):
        out["plus"] = True
        out["grade"] = "A+"
    return out


def _why(letter, core, sides, board_summary, supporting_gaps) -> str:
    """One sentence a reader can check against the page."""
    parts = []
    if core["lineups"]:
        parts.append("lineups posted")
    elif sides == 1:
        parts.append("one lineup posted")
    else:
        parts.append("no lineup yet")
    parts.append("both starters named" if core["starters"] else "a starter unnamed")

    books = board_summary.get("books")
    age = board_summary.get("age_seconds")
    if not board_summary.get("has_board"):
        parts.append("no prices yet")
    else:
        depth = f"{int(books)} books" if books is not None else "a board"
        if age is None:
            parts.append(f"{depth} quoting")
        elif core["fresh"]:
            parts.append(f"{depth} quoting {int(age // 60)} minutes ago")
        else:
            hours = age / 3600
            parts.append(f"{depth} quoting {hours:.1f} hours ago")
    if supporting_gaps:
        parts.append(f"missing {', '.join(supporting_gaps)}")
    return f"{letter}: " + ", ".join(parts) + "."


def legend() -> Sequence[str]:
    """The lines a page prints once beside the first grade it shows."""
    return (
        "The grade is how much we know about the game, not how much we "
        "expect to win.",
        "A: lineups posted, both starters named, a fresh board of at least "
        f"{prices_mod.MIN_BOOKS} books. B: one of those thin or stale. "
        "C: a lineup or a starter still missing. D: no prices yet.",
        "A+ means the price is on your side by our own number. That number "
        "has been measured unreliable when it disagrees with the market, so "
        "treat the plus as a note, not a reason.",
    )
