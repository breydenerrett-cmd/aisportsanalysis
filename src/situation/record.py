"""The situation record: one shape for every sport.

WHAT A SITUATION IS
-------------------
The statistics in a packet say who the two sides ARE. The situation says where
each one is standing the day it plays: how long since it last played, what it
has just done, what is on the line, how it has fared when the stakes were
highest, what happened the last times these two met, who is available, where the
game is. `docs/SITUATION_LAYER_PLAN.md` is the plan; this module is the contract
every sport's builder (`mlb.py`, `ufc.py`) writes to.

ONE SHAPE, FACT BY FACT
-----------------------
A record is a flat list of FACTORS and a flat list of GAPS. A factor is one fact
about one side (or about the game as a whole) with its sample and its source:

    family    the family it belongs to (rest_and_rhythm, form, stakes, ...)
    name      what it is (days_since_last_game, last_10, series_state, ...)
    side      away | home (MLB), a | b (UFC), or "game" for a fact about the matchup
    value     ONE scalar: number, string or bool. Never None, never a list: a path
              the analyst cites must land on a single value the critic can check
    unit      what the value counts ("days", "wins", "miles", "bool", "text")
    sample    how many observations it rests on ({"games": 5}); empty only for a fact
              that is not a count (a park's roof)
    as_of     the newest thing it used: a date or instant strictly BEFORE the
              record's own `as_of`. A factor stamped on or after the cut-off would
              be a leak, and `problems` says so
    source    where it came from, in words a reader can follow
    sentence  the fact in plain words, with its sample size, as the page prints it
    detail    optional companion numbers and names (the other half of "4-1")

A factor that cannot be built is a GAP: `{family, name, side, reason}`. Absence is
stated, never filled with an average or a guess; the analyst's prompt says a claim
that rests on a gap is not made.

THE SENTENCE RULE THAT KEEPS THE CRITIC HAPPY
---------------------------------------------
The analyst's critic strikes any number in a claim that is not a number in the
packet. A situation sentence the model will quote therefore must not carry a number
the record does not also hold as a number: "last played 3 days earlier" needs a 3
somewhere in value, sample or detail. `unsupported_sentence_numbers` finds the ones
that do not, and the tests run it over every factor the builders can write. Dates
in a sentence are ISO ("2026-10-01"); the critic reads those as dates, not numbers.

THE CUT-OFF IS THE RECORD'S, NOT THE FACTOR'S
---------------------------------------------
`as_of` on the record is the moment the situation is drawn at: the game's date (MLB:
games on that date and later never count, even the first half of a doubleheader) or
the bout's start (UFC). The builders read only what precedes it; `problems` re-checks
that no factor claims otherwise.

Pure: no I/O, no clock, no network. Stdlib only.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

VERSION = "situation_v1"

SIDE_GAME = "game"

# The record's own factor keys, in the order they are written.
FACTOR_KEYS = ("family", "name", "side", "value", "unit", "sample", "as_of", "source",
               "sentence")

_SAFE = re.compile(r"^[a-z][a-z0-9_]*$")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# The critic's own number literal (src/analyst/critic.py): a sentence number must
# match this to be found, and must then be a number the packet holds.
_NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?")
_TIME_LIKE = re.compile(r"\b\d{1,2}:\d{2}\b")


class RecordError(ValueError):
    """A factor or a record that cannot be built because it breaks the shape."""


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

def _scalar(value: Any) -> Any:
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecordError("a factor's value must be finite")
        return round(value, 4)
    raise RecordError(f"a factor's value must be a number, string or bool, got {type(value).__name__}")


def _clean(node: Any) -> Any:
    """A copy safe to freeze and hash: floats rounded and finite, keys as strings."""
    if isinstance(node, Mapping):
        return {str(k): _clean(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_clean(v) for v in node]
    if isinstance(node, float):
        return round(node, 4) if math.isfinite(node) else None
    return node


def factor(family: str, name: str, value: Any, unit: str, *, sample: Optional[Mapping] = None,
           as_of: str, source: str, sentence: str, side: str = SIDE_GAME,
           detail: Optional[Mapping] = None) -> dict:
    """One fact. Raises `RecordError` for a value that is not a single scalar, an
    unsafe name, or an empty sentence: a builder bug, caught where it is made."""
    for label, text in (("family", family), ("name", name), ("side", side)):
        if not isinstance(text, str) or not _SAFE.match(text):
            raise RecordError(f"{label} {text!r} is not a lower-case path-safe word")
    if value is None:
        raise RecordError(f"{family}.{name}: a factor has a value; an absent one is a gap")
    if not isinstance(sentence, str) or not sentence.strip():
        raise RecordError(f"{family}.{name}: a factor needs a sentence")
    if not isinstance(source, str) or not source.strip():
        raise RecordError(f"{family}.{name}: a factor needs a source")
    out = {
        "family": family, "name": name, "side": side,
        "value": _scalar(value), "unit": str(unit),
        "sample": _clean(dict(sample or {})),
        "as_of": str(as_of), "source": source.strip(), "sentence": sentence.strip(),
    }
    if detail:
        out["detail"] = _clean(dict(detail))
    return out


def gap(family: str, name: str, reason: str, *, side: str = SIDE_GAME) -> dict:
    """One thing that is not available, and why."""
    for label, text in (("family", family), ("name", name), ("side", side)):
        if not isinstance(text, str) or not _SAFE.match(text):
            raise RecordError(f"{label} {text!r} is not a lower-case path-safe word")
    if not isinstance(reason, str) or not reason.strip():
        raise RecordError(f"{family}.{name}: a gap needs a reason")
    return {"family": family, "name": name, "side": side, "reason": reason.strip()}


def _key(item: Mapping) -> tuple:
    return (item["family"], item["name"], item.get("side") or SIDE_GAME)


# ---------------------------------------------------------------------------
# checking
# ---------------------------------------------------------------------------

def _moment(value: Any) -> Optional[datetime]:
    """A date or instant string as an aware UTC datetime; a bare date is the start
    of that day. None when it cannot be read."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def numeric_leaves(node: Any) -> list:
    """Every real number inside a factor's value, sample and detail (bools are not numbers)."""
    out: list = []
    if isinstance(node, Mapping):
        for v in node.values():
            out.extend(numeric_leaves(v))
    elif isinstance(node, (list, tuple)):
        for v in node:
            out.extend(numeric_leaves(v))
    elif isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node):
        out.append(float(node))
    return out


def sentence_numbers(text: str) -> list:
    """The number literals a reader (or the critic) would find in a sentence: ISO
    dates and clock times are removed first, as the critic does."""
    clean = _ISO_DATE.sub(" ", text or "")
    clean = _TIME_LIKE.sub(" ", clean)
    return _NUMBER.findall(clean)


def _pool_has(pool: Sequence[float], literal: str) -> bool:
    pct = literal.endswith("%")
    text = literal.rstrip("%").lstrip("+")
    try:
        target = float(text)
    except ValueError:
        return True
    places = len(text.split(".")[1]) if "." in text else 0
    for v in pool:
        for candidate in (v, abs(v), v * 100.0, abs(v) * 100.0):
            if places == 0 and not pct:
                if abs(candidate - round(candidate)) < 1e-9 and round(candidate) == round(target):
                    return True
            elif round(candidate, places) == round(target, places):
                return True
    return False


def unsupported_sentence_numbers(item: Mapping) -> list:
    """Numbers in a factor's sentence that the factor does not also hold as numbers."""
    pool = (numeric_leaves(item.get("value")) + numeric_leaves(item.get("sample"))
            + numeric_leaves(item.get("detail")))
    return [lit for lit in sentence_numbers(item.get("sentence", "")) if not _pool_has(pool, lit)]


def factor_problems(item: Mapping, as_of: Any) -> list:
    """Everything wrong with one factor against the record's cut-off. Empty when it is sound."""
    out = []
    where = f"{item.get('family')}.{item.get('name')}.{item.get('side')}"
    missing = [k for k in FACTOR_KEYS if k not in item]
    if missing:
        return [f"{where}: missing {missing}"]
    if item["value"] is None or isinstance(item["value"], (list, dict)):
        out.append(f"{where}: value must be one scalar")
    elif isinstance(item["value"], float) and not math.isfinite(item["value"]):
        out.append(f"{where}: value is not finite")
    if not str(item["sentence"]).strip():
        out.append(f"{where}: empty sentence")
    cutoff, stamped = _moment(as_of), _moment(item["as_of"])
    if stamped is None:
        out.append(f"{where}: as_of {item['as_of']!r} is not a date")
    elif cutoff is not None and not stamped < cutoff:
        out.append(f"{where}: as_of {item['as_of']} is not before the record's cut-off {as_of}")
    return out


def problems(record: Mapping) -> list:
    """Every way a record breaks its own contract: the shape, the cut-off, duplicates.
    The sentence-number rule is separate (`unsupported_sentence_numbers`)."""
    out = []
    if record.get("version") != VERSION:
        out.append(f"version is {record.get('version')!r}, not {VERSION!r}")
    families = list(record.get("families") or [])
    seen: set = set()
    for item in record.get("factors") or []:
        out.extend(factor_problems(item, record.get("as_of")))
        if item.get("family") not in families:
            out.append(f"{item.get('family')}: not one of this sport's families")
        if _key(item) in seen:
            out.append(f"{_key(item)}: written twice")
        seen.add(_key(item))
    for item in record.get("missing") or []:
        if not item.get("reason"):
            out.append(f"{_key(item)}: a gap with no reason")
        if _key(item) in seen:
            out.append(f"{_key(item)}: both a factor and a gap")
    return out


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------

def build(*, sport: str, subject: Mapping, as_of: str, as_of_basis: str,
          families: Sequence[str], sides: Sequence[str], factors: Iterable[Mapping],
          missing: Iterable[Mapping], coverage: Optional[Mapping] = None,
          display: Optional[Sequence[tuple]] = None) -> dict:
    """Assemble and check a record.

    A factor that fails its own check (a stamp on or after the cut-off, a value that
    is not a scalar) is not published: it moves to `missing` with the reason, so a
    builder bug can cost a fact and can never put a leak in front of the analyst.
    `display` is the builder's pick of what a short page block should say, as
    (family, name, side) triples in order; it is stored as indexes into `factors`.
    """
    order = {f: i for i, f in enumerate(families)}
    kept: list = []
    gaps = [dict(g) for g in missing]
    for item in factors:
        bad = factor_problems(item, as_of)
        if item.get("family") not in order:
            bad.append(f"{item.get('family')} is not a family of this sport")
        if bad:
            gaps.append(gap(item.get("family") if item.get("family") in order else families[0],
                            str(item.get("name") or "unknown"),
                            "the fact failed its own consistency check and was left out: " + bad[0],
                            side=item.get("side") or SIDE_GAME))
            continue
        kept.append(dict(item))
    side_rank = {s: i for i, s in enumerate(list(sides) + [SIDE_GAME])}
    kept.sort(key=lambda f: (order[f["family"]], f["name"], side_rank.get(f["side"], 99)))
    gaps.sort(key=lambda g: (order.get(g["family"], 99), g["name"], side_rank.get(g["side"], 99),
                             g["reason"]))
    unique_gaps, seen = [], set()
    for g in gaps:
        k = (g["family"], g["name"], g["side"], g["reason"])
        if k not in seen:
            seen.add(k)
            unique_gaps.append(g)
    index = {_key(f): i for i, f in enumerate(kept)}
    shown = []
    for triple in display or ():
        i = index.get(tuple(triple))
        if i is not None and i not in shown:
            shown.append(i)
    out = {
        "version": VERSION, "sport": sport, "subject": _clean(dict(subject)),
        "as_of": as_of, "as_of_basis": as_of_basis,
        "families": list(families), "sides": list(sides) + [SIDE_GAME],
        "factors": kept, "missing": unique_gaps,
        "coverage": _clean(dict(coverage or {})), "display": shown,
    }
    return out


# ---------------------------------------------------------------------------
# what the analyst and the pages read
# ---------------------------------------------------------------------------

HOW_TO_READ = (
    "Each entry under factors is one fact about the situation around this game, as of the date "
    "in as_of and strictly before it: a value, its unit, the sample it rests on, where it came "
    "from and a sentence in plain words. Quote the numbers as written and do no arithmetic on them.",
    "The side a fact is about is its last key: {sides}. game is a fact about the matchup itself.",
    "A fact listed under missing was not available. Do not guess it, and do not make a claim that "
    "rests on it.",
    "These facts describe what happened before the game. They are not forecasts, and the price "
    "may already include whatever story they tell.",
)


def packet_section(record: Mapping) -> dict:
    """The record as an analyst packet section: `{as_of, as_of_basis, values}`.

    Factors are nested `factors[family][name][side]` so a path reads like a sentence
    (`sections.situation.values.factors.form.last_10.home.value`). Family, name and
    side are implied by the path and left out of each leaf to save tokens; the
    display list and the subject are not carried (the packet has its own game block).
    """
    nested: dict = {}
    for item in record.get("factors") or []:
        leaf = {k: item[k] for k in ("value", "unit", "sample", "as_of", "source", "sentence")}
        if item.get("detail"):
            leaf["detail"] = item["detail"]
        nested.setdefault(item["family"], {}).setdefault(item["name"], {})[item["side"]] = leaf
    sides = ", ".join(s for s in record.get("sides") or [])
    return {
        "as_of": record["as_of"],
        "as_of_basis": record["as_of_basis"],
        "values": {
            "version": record["version"],
            "factors": nested,
            "missing": [{k: g[k] for k in ("family", "name", "side", "reason")}
                        for g in record.get("missing") or []],
            "coverage": dict(record.get("coverage") or {}),
            "how_to_read": [line.format(sides=sides) for line in HOW_TO_READ],
        },
    }


def display_lines(record: Optional[Mapping], *, limit: int = 6) -> list:
    """The record's short page block: up to `limit` entries `{sentence, family, side,
    sample, evidence}`. `evidence` is a path into the record as the page holds it
    (`situation.factors.<i>.value`, the written reads' dotted-path grammar with integer list
    indexes) so each sentence can be walked back to its value."""
    out = []
    if not isinstance(record, Mapping):
        return out
    factors = record.get("factors") or []
    for i in (record.get("display") or [])[:limit]:
        if not isinstance(i, int) or not 0 <= i < len(factors):
            continue
        item = factors[i]
        out.append({
            "sentence": item["sentence"], "family": item["family"], "side": item["side"],
            "sample": dict(item.get("sample") or {}),
            "evidence": {"path": f"situation.factors.{i}.value", "label": item["name"].replace("_", " "),
                         "value": item["value"]},
        })
    return out


PAGE_MISSING_SHOWN = 8


def page_block(record: Optional[Mapping], *, label: str, limit: int = 6) -> Optional[dict]:
    """The "Situation" block of a written read: `{label, as_of, lines, missing}`, or None when the
    record has nothing to say (a page with no record shows no block, never an empty one).

    `lines` are `display_lines` (a sentence, its sample and an evidence path that resolves in the
    record the page holds). `missing` is what the situation could not say, in the shape the
    read's own "what we could not use" list uses (`input`, `status`, `detail`): a store that is not
    current is `stale`, everything else `absent`. The reads add this block only when a record is
    handed to them, so a read built without one is exactly the read it always was."""
    if not isinstance(record, Mapping):
        return None
    lines = display_lines(record, limit=limit)
    notes = [{"input": f"{g['family'].replace('_', ' ')}: {g['name'].replace('_', ' ')}"
                       + ("" if g.get("side") == SIDE_GAME else f" ({g['side']})"),
              "status": "stale" if g["name"] == "results_store_current" else "absent",
              "detail": g["reason"]} for g in (record.get("missing") or [])][:PAGE_MISSING_SHOWN]
    if not lines and not notes:
        return None
    return {"label": label, "as_of": record.get("as_of"), "lines": lines, "missing": notes}


def numbers_in_record(record: Mapping) -> list:
    """Every number a packet built from this record would hold."""
    return [n for item in record.get("factors") or []
            for n in (numeric_leaves(item.get("value")) + numeric_leaves(item.get("sample"))
                      + numeric_leaves(item.get("detail")))]
