"""The critic: nothing the packet does not support is published as analysis.

TWO PASSES, THE CHEAP ONE FIRST
-------------------------------
1. DETERMINISTIC (always on, free, exact). Every evidence path must resolve to
   a value in the packet; every value the analyst claims for it must match;
   every number quoted in prose must be one the packet holds (or a price or
   probability the analyst itself gives in a call); every person named (two or
   more capitalised words) must be a name the packet holds, which is the
   benchmark's original failure, a pitcher nobody had verified; the price and
   book of a TAKE must be a real quote; the verdict must agree with the
   selection; a TAKE at -200 or worse is refused in every market (the owner's
   rulings of 2026-09-20 and 2026-09-22); and a call must
   not contradict itself (a fair estimate below the break-even of the price it
   says to take).
2. MODEL (optional, off by default, costs a second call). A second model reads
   the packet and the published calls and says which reasons overreach their
   evidence. It can only STRIKE; it can never rescue a call the first pass
   struck, and if it cannot be reached the calls stand on the first pass alone
   and the record says the model critic did not run.

STRIKE, NEVER SILENTLY KEEP
---------------------------
A call that fails is published as a PASS whose reason is "could not be
verified", with the problems listed. The struck original goes to the ledger
(the audit trail keeps what the model said) but never to a reader: an
unsupported claim is not shown even to say it was unsupported. A call that is
only overconfident is DOWNGRADED (confidence lowered one step) rather than
struck. The summary is checked the same way and, if it fails, is withheld and
replaced by a plain notice; the calls still publish.

DECLARED DERIVATIONS (prompt v3)
--------------------------------
A number in prose must be in the packet, with ONE exception: an MLB reason, case against or
summary may carry `derived`, a list of {value, unit, op, inputs, note}, and the number it declares
is then allowed in THAT item's prose and nowhere else. The checker does not believe the model's
arithmetic: it reads the values at `inputs` out of the packet, recomputes the op itself
(`verify_derivations`), checks the unit is one the op allows and that the value agrees within the
op's stated tolerance. A derivation whose inputs are absent or not numbers, whose value is off, or
whose op or unit is unknown strikes the call (or withholds the summary) with a plain reason. A
number that is neither in the packet nor a verified derivation is rejected exactly as it always
was. The derivations that held, with the values they were computed from, are kept with the
published call (the row's provenance) and the page shows each as a sentence.

WHAT THIS CANNOT CATCH
----------------------
It checks that quoted facts are true and that the call is coherent. It cannot
tell whether a TRUE fact is a good reason, whether the summary and the calls
agree in spirit, or whether the model's probability is any good. The record
measures that, in public, afterward; this module only stops fabrication. A verified
derivation licenses its NUMBER, not the words round it: "11 days" with a correct 11-day
derivation passes, and so would "11 runs" (the derivation's own unit is on the record, the
prose's is not parsed). The UFC analyst has no derivations: its reasons carry none and the
critic ignores one if it is sent.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from src.analyst import packet as packet_mod
from src.analyst.analyst import (DERIVATION_UNITS, MAX_DERIVATIONS, TAKE_PRICE_FLOOR,
                                 is_mlb_packet)
from src.core import odds as odds_math
from src.data import labels

UNVERIFIED = "could not be verified"

# A fair estimate and the break-even of pass_price may differ by this much in
# probability: the model is converting between odds and probability in its
# head, and a rounding gap is not a contradiction.
PASS_PRICE_TOLERANCE = 0.02

CONFIDENCE_ORDER = ("low", "medium", "high")

# Words that may not appear in anything we publish. Matched on word
# boundaries, case-insensitive. "edge" is allowed only inside a negation.
_BANNED = (
    (r"\block(?:s|ed|ing)?\b", "lock"),
    (r"\bguarantee[sd]?\b", "guaranteed"),
    (r"\bfree\s+money\b", "free money"),
    (r"\bsure\s+thing\b", "sure thing"),
    (r"\bcan'?t\s+lose\b", "can't lose"),
    (r"\bcannot\s+lose\b", "cannot lose"),
    (r"\+\s*EV\b", "+EV"),
    (r"(?i)bet[\s-]*check", "Bet Check"),
)
_EDGE = re.compile(r"\bedges?\b", re.I)
_NEGATOR = re.compile(r"\b(no|not|never|without|nothing|none|isn'?t|aren'?t|don'?t|"
                      r"doesn'?t|can'?t|cannot|lacks?|neither)\b", re.I)

_NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_GAME_ID = re.compile(r"\b[A-Za-z]{2,4}-[A-Za-z]{2,4}-\d{4}-\d{2}-\d{2}-\d+\b")
_LIST_MARK = re.compile(r"(?<![\w.])\d{1,2}\)")


# ---------------------------------------------------------------------------
# numbers and words
# ---------------------------------------------------------------------------

def decimals(literal: Any) -> int:
    """Decimal places a claimed number was written with."""
    text = repr(literal) if isinstance(literal, float) else str(literal)
    return len(text.split(".")[1]) if "." in text else 0


def values_match(claimed: Any, actual: Any) -> bool:
    """Does what the analyst says a value is equal what the packet holds?

    Strings compare case-insensitively. Numbers compare at the precision the
    analyst wrote: 3.4 matches 3.4054, 3 matches only a whole 3. A bool is
    never a number.
    """
    if isinstance(actual, bool) or isinstance(claimed, bool):
        return claimed is actual
    if actual is None or claimed is None:
        return claimed is None and actual is None
    if isinstance(actual, (int, float)):
        if isinstance(claimed, str):
            try:
                claimed = float(claimed.replace("%", "").strip())
            except ValueError:
                return False
        if not isinstance(claimed, (int, float)):
            return False
        d = decimals(claimed)
        if d == 0:
            return abs(float(actual) - round(float(actual))) < 1e-9 \
                and int(round(float(actual))) == int(claimed)
        return round(float(actual), d) == round(float(claimed), d)
    return str(claimed).strip().lower() == str(actual).strip().lower()


def _iso_numbers(packet: Mapping) -> list:
    """Month, day and year of every ISO date string in the packet, so a
    sentence can say "October 3" without the 3 being a number from nowhere."""
    out = []
    for _p, v in packet_mod.iter_leaves(packet):
        if isinstance(v, str) and len(v) >= 10 and _ISO_DATE.match(v[:10]):
            try:
                d = datetime.strptime(v[:10], "%Y-%m-%d")
            except ValueError:
                continue
            out.extend([d.year, d.month, d.day])
    return out


def _expand(vals) -> list:
    """Each number, its absolute value, and both times one hundred (a
    probability is quoted as a percentage)."""
    out = []
    for v in vals:
        f = float(v)
        out.extend([f, abs(f), f * 100.0, abs(f) * 100.0])
    return out


@dataclass
class NumberPool:
    """Every number a sentence may legitimately contain.

    The base is the packet's own numbers (and the parts of its dates). A call
    adds only ITS OWN price, pass price and fair estimate, so one call cannot
    launder a number through another's. Evidence values add nothing: each is
    checked against the packet separately and, when it matches, is already in
    the base. The summary adds the estimates of the calls that were kept.
    """
    values: list

    @classmethod
    def base(cls, packet: Mapping) -> "NumberPool":
        return cls(_expand(list(packet_mod.numbers_in_packet(packet)) + _iso_numbers(packet)))

    def plus(self, calls: Sequence[Mapping]) -> "NumberPool":
        vals = []
        for call in calls:
            for key in ("price", "pass_price", "fair_estimate"):
                v = call.get(key) if isinstance(call, Mapping) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals.append(v)
        return NumberPool(self.values + _expand(vals))

    def with_derived(self, records: Sequence[Mapping]) -> "NumberPool":
        """The pool plus the values of VERIFIED derivations, for the one item that declared them.
        Each adds its value and its absolute value (a gap is said without its sign) and nothing
        else: unlike a packet number it is not also allowed times one hundred, except a probability,
        which is written as a percentage."""
        vals = []
        for rec in records:
            v = float(rec["value"])
            vals.extend([v, abs(v)])
            if rec.get("unit") == "probability":
                vals.extend([v * 100.0, abs(v) * 100.0])
        return NumberPool(self.values + vals)

    def has(self, literal: str) -> bool:
        pct = literal.endswith("%")
        text = literal.rstrip("%").lstrip("+")
        try:
            target = float(text)
        except ValueError:
            return True
        d = decimals(text)
        for v in self.values:
            if d == 0 and not pct:
                # a bare whole number must be a whole number in the packet
                if abs(v - round(v)) < 1e-9 and round(v) == round(target):
                    return True
            elif round(v, d) == round(target, d):
                # decimals, and percentages of any precision, match at the
                # precision the writer used ("55%" for 54.86 is rounding)
                return True
        return False


def numbers_in_prose(text: str) -> list:
    clean = _GAME_ID.sub(" ", text or "")
    clean = _ISO_DATE.sub(" ", clean)
    clean = _LIST_MARK.sub(" ", clean)
    return _NUMBER.findall(clean)


def unsupported_numbers(text: str, pool: NumberPool) -> list:
    return [lit for lit in numbers_in_prose(text) if not pool.has(lit)]


def banned_words(text: str) -> list:
    found = []
    for pattern, label in _BANNED:
        if re.search(pattern, text or "", re.I):
            found.append(label)
    for m in _EDGE.finditer(text or ""):
        window = " ".join((text[:m.start()].split())[-5:])
        if not _NEGATOR.search(window):
            found.append("edge")
            break
    return found


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------
#
# THE BENCHMARK'S ORIGINAL FAILURE was a review that named a pitcher nobody had
# verified. A model with a head full of last season will happily say "Aaron
# Judge has owned him" about a game whose packet never mentions Judge. The
# number check cannot see that sentence; this can: a run of TWO OR MORE
# capitalised words in a claim is treated as a name, and the packet must hold
# it. One capitalised word is not checked ("Cole" after "Gerrit Cole" was
# established, "Rays", sentence-initial words), which keeps the rule from
# striking ordinary prose. A false strike costs a PASS; a missed name costs a
# published claim with no source, so the rule leans strict.

# Words that start a sentence or a clause and so may be capitalised without
# being part of a name. Dropped from the front of a run before it is checked.
_LEADING = frozenset(w.lower() for w in (
    "The This That These Those A An It Its His Her Their He She They We Our I My If When While "
    "With Without Both Each Every Only Even Given Since Because However But And So As At On In "
    "For To Of By From Over Under Home Road Away Tonight Today Yesterday Also Still Overall "
    "Neither Either Nothing Nobody Not No There Here What Which Who Why How Until After Before "
    "Against Between Despite Although Though Unless Whether Maybe Perhaps Likely Another Other "
    "Some Most More Less Any All Both Then Now Once Just Could Would Should Will Can May Might "
    "Take Pass Lean Taking Passing Leaning Total Moneyline").split())

# Capitalised phrases that are ordinary baseball or betting vocabulary.
_PHRASES = frozenset((
    "american league", "national league", "wild card", "division series", "championship series",
    "world series", "major league", "major leagues", "cy young", "all star", "opening day",
    "player props", "run line", "money line", "run total", "game total", "team total",
    "first five", "total bases", "home run", "home runs", "stolen base", "stolen bases",
    "strike out", "strike outs", "plate appearance", "plate appearances", "batting order",
    "starting pitcher", "starting pitching", "last ten", "fixed roof", "open roof",
))

_PUNCT_END = ".,;:!?)"
_NAMEISH = re.compile(r"^[A-Z][A-Za-z'\u2019-]*[a-z][A-Za-z'\u2019-]*$")


def _norm(text: str) -> str:
    """Lower-case, punctuation to spaces (apostrophes unified and kept), spaces
    collapsed: the form both a name and the packet's text are compared in."""
    text = text.lower().replace("\u2019", "'")
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text).split())


def name_runs(text: str) -> list:
    """Runs of two or more name-like words in `text`, as normalised strings,
    after dropping sentence-leading filler and trailing Jr/Sr."""
    runs, current = [], []

    def close():
        words = list(current)
        current.clear()
        while words and words[0] in _LEADING:
            words.pop(0)
        while words and words[-1] in ("jr", "sr", "ii", "iii"):
            words.pop()
        if len(words) >= 2:
            runs.append(" ".join(words))

    for raw in (text or "").split():
        bare = raw.strip("\"([{" + _PUNCT_END + "")
        if bare.endswith(("'s", "\u2019s")):
            bare = bare[:-2]
        ends = raw[-1:] in _PUNCT_END and not bare.lower() in ("jr", "sr")
        if bare in ("Jr", "Sr") and current:
            current.append(bare.lower())
            if raw[-1:] in ",;:!?)":
                close()
            continue
        if _NAMEISH.match(bare):
            current.append(_norm(bare))
            if ends:
                close()
        else:
            close()
    close()
    return runs


@dataclass
class KnownNames:
    """Every name the packet can vouch for: its own text, the printed
    "Last, First" forms turned round, and the clubs.

    `phrases` is the sport's own capitalised vocabulary (defaults to baseball's);
    `clubs=False` leaves the baseball clubs out, for a sport that has none
    (`ufc_analyst.known_names`). The MLB call, `KnownNames.build(packet)`, is
    unchanged."""
    blob: str
    team_words: frozenset
    phrases: frozenset = _PHRASES

    @classmethod
    def build(cls, packet: Mapping, *, extra_phrases: Sequence[str] = (),
              clubs: bool = True) -> "KnownNames":
        pieces, team_words = [], set()
        for _p, v in packet_mod.iter_leaves(packet):
            if not isinstance(v, str):
                continue
            pieces.append(_norm(v))
            if ", " in v and v.count(",") == 1:
                last, first = v.split(", ")
                pieces.append(_norm(f"{first} {last}"))
        if clubs:
            for team in labels.TEAM_NAMES.values():
                for key in ("city", "name", "full"):
                    if team.get(key):
                        pieces.append(_norm(team[key]))
                        team_words.update(_norm(team[key]).split())
        blob = " | ".join(p for p in pieces if p).join(("| ", " |"))
        return cls(blob, frozenset(team_words),
                   _PHRASES | frozenset(_norm(p) for p in extra_phrases))

    def _known(self, segment: str, single: bool) -> bool:
        if single:
            return segment in self.team_words      # "Rays", "Bay", never a bare first name
        # pieces are separated by " | ", so a segment can never span two of them
        return segment in self.phrases or f" {segment} " in self.blob

    def has(self, run: str) -> bool:
        """Can the whole run be tiled by things the packet or the vocabulary
        vouches for? "National League Division Series" is two phrases;
        "Gerrit Rice" is a first name from one player and a surname from
        another, and is not tiled, because single words only count for clubs."""
        words = run.split()
        reach = [True] + [False] * len(words)
        for i in range(len(words)):
            if not reach[i]:
                continue
            for j in range(i + 1, len(words) + 1):
                if self._known(" ".join(words[i:j]), single=(j - i == 1)):
                    reach[j] = True
        return reach[len(words)]


def unsupported_names(text: str, known: KnownNames) -> list:
    return [run for run in name_runs(text) if not known.has(run)]


# ---------------------------------------------------------------------------
# declared derivations
# ---------------------------------------------------------------------------
#
# WHY THE CHECKER DOES THE ARITHMETIC. The packet check rejects "11 days" because no 11 is in the
# packet, and it was right to: the model had computed it itself, and a model's mental arithmetic is
# exactly what the packet rule exists to keep out of prose. But some calculated facts are legitimate
# (the days a starter has rested, the gap between two ERAs, the chance a price implies), and the
# owner's ruling of 2026-10-04 is that they are allowed "when deterministic code verifies their
# source inputs, calculation, units and time convention", with the provenance kept beside the report.
# So the model DECLARES the calculation and this code REDOES it from packet values; the model's
# number is never trusted, only compared.
#
# THE CLOSED SET OF OPS, their conventions and tolerances. A value agrees with the recomputed one
# when it is within the half unit of the last place it was written to (3.5 for 3.4876 is rounding),
# and never by more than the op's cap, so a whole number cannot stand in for 0.6. A cap of 0 means
# exact. `scale` turns the raw result into the unit's own number (a probability's raw result is a
# fraction; the unit "percent" is 100 times it).
#
#   difference           inputs[0] minus inputs[1], signed. Cap 0.05 (0.5 in percentage points).
#   sum                  of two to twelve numbers. Cap 0.05 (0.5 in percent or percentage points).
#   mean                 the arithmetic mean of two to twelve numbers. Same caps as sum.
#   ratio                inputs[0] over inputs[1]; a zero denominator is refused. Cap 0.05 (0.5 percent).
#   percent_change       from inputs[0] to inputs[1], as a percent of the absolute value of inputs[0];
#                        a zero start is refused. Cap 0.5 percent.
#   days_between         CALENDAR days between the UTC dates of two ISO dates or datetimes in the
#                        packet, later minus earlier (never negative). A date alone is that day in
#                        UTC; a datetime is first converted to UTC (no offset is read as UTC). The
#                        time of day is dropped, so 22:30Z on the 3rd and 00:10Z on the 4th are 1 day
#                        apart. Exact.
#   implied_probability  the break-even probability of one American price in the packet, vig left in
#                        (src/core/odds). Unit percent (cap 0.5) or probability (cap 0.005).
#   count                the length of one packet list. Exact.
#
# The units each op may be written in are `analyst.DERIVATION_UNITS` (the schema's enum): the same
# tuple names, with the arithmetic here.
_PLAIN_UNITS = ("runs", "points", "games", "wins", "innings", "hits", "strikeouts", "degrees",
                "mph", "units")
_COUNT_UNITS = ("items", "games", "players", "books", "quotes", "entries")
_PLAIN = {u: (1.0, 0.05) for u in _PLAIN_UNITS}
_SCALED = dict(_PLAIN, **{"percentage points": (100.0, 0.5), "percent": (100.0, 0.5)})

# op -> {unit: (scale, cap)}
UNIT_RULES: dict = {
    "difference": dict(_PLAIN, **{"percentage points": (100.0, 0.5)}),
    "sum": dict(_SCALED),
    "mean": dict(_SCALED),
    "ratio": {"ratio": (1.0, 0.05), "times": (1.0, 0.05), "percent": (100.0, 0.5)},
    "percent_change": {"percent": (1.0, 0.5)},
    "days_between": {"days": (1.0, 0.0)},
    "implied_probability": {"percent": (100.0, 0.5), "probability": (1.0, 0.005)},
    "count": {u: (1.0, 0.0) for u in _COUNT_UNITS},
}
# op -> (fewest, most) inputs
_ARITY = {"difference": (2, 2), "sum": (2, 12), "mean": (2, 12), "ratio": (2, 2),
          "percent_change": (2, 2), "days_between": (2, 2), "implied_probability": (1, 1),
          "count": (1, 1)}
NOTE_MAX = 240

_ISO_DAY_START = re.compile(r"^\d{4}-\d{2}-\d{2}")
_STRUCTURAL_KEYS = frozenset(("sections", "values", "markets", "options", "best"))
_GENERIC_KEYS = frozenset(("price", "line", "value", "date", "name", "avg", "wins", "losses",
                           "pct", "count", "total", "rate", "era", "fip", "observed_utc",
                           "captured_utc"))
_ABBREVIATIONS = {"sp": "starter", "era": "ERA", "fip": "FIP", "whip": "WHIP", "ops": "OPS",
                  "utc": "", "pct": "percentage", "ml": "moneyline", "avg": "average",
                  "diff": "gap", "rbi": "RBI", "hr": "home run", "k": "strikeout", "bb": "walk"}


def _real(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _num_text(x: Any) -> str:
    f = float(x)
    return str(int(round(f))) if abs(f - round(f)) < 1e-9 else repr(round(f, 6))


def _humanize(key: str) -> str:
    return " ".join(w for w in (_ABBREVIATIONS.get(p, p) for p in key.split("_")) if w)


def _label(packet: Mapping, path: str) -> str:
    """A plain name for what a path holds, for the sentence the page shows: never the path itself.
    "markets.moneyline.options[0].best.price" is "NYY moneyline best price"; a section field is its
    last key in words, with the key before it when the last is too bare to say what it is."""
    if path == "game.first_pitch_utc":
        return "first pitch"
    if path == "game.date":
        return "the game date"
    m = re.match(r"^markets\.(\w+)\.options\[(\d+)\]\.(.+)$", path)
    if m:
        market = (packet.get("markets") or {}).get(m.group(1)) or {}
        opts = market.get("options") or []
        sel = opts[int(m.group(2))].get("selection") if int(m.group(2)) < len(opts) else None
        rest = " ".join(_humanize(k) for k in m.group(3).split(".") if k not in ("best",))
        return " ".join(x for x in (str(sel or ""), str(market.get("market") or m.group(1)), rest) if x)
    keys = [k for k in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", path) if k not in _STRUCTURAL_KEYS]
    if not keys:
        return "a figure in the data"
    last = keys[-1]
    if last == "as_of" and len(keys) > 1:
        return f"the {_humanize(keys[-2])} as-of date"
    if last in _GENERIC_KEYS and len(keys) > 1:
        return f"{_humanize(keys[-2])} {_humanize(last)}"
    return _humanize(last)


def _calendar_day(value: Any):
    """The UTC calendar date of an ISO date or datetime string, or None."""
    if not isinstance(value, str) or not _ISO_DAY_START.match(value):
        return None
    moment = packet_mod._parse_utc(value)
    return moment.date() if moment else None


def _agrees(value: Any, expected: float, cap: float) -> bool:
    """Is the declared value the recomputed one, to the precision it was written at and within `cap`?"""
    gap = abs(float(value) - expected)
    if cap == 0:
        return gap < 1e-9
    return gap <= min(0.5 * 10 ** -decimals(value), cap) + 1e-9


def _recompute(op: str, got: Sequence, at: str, problems: list) -> Optional[float]:
    """The raw result of `op` over `got` = [(path, packet value)], or None with the reason appended."""
    if op == "count":
        path, found = got[0]
        if not isinstance(found, list):
            problems.append(f"{at}: {path!r} is not a list, so there is nothing to count")
            return None
        return float(len(found))
    if op == "days_between":
        days = []
        for path, found in got:
            day = _calendar_day(found)
            if day is None:
                problems.append(f"{at}: {path!r} does not hold an ISO date or datetime")
                return None
            days.append(day)
        return float(abs((days[0] - days[1]).days))
    if op == "implied_probability":
        path, found = got[0]
        if not _real(found) or float(found) != int(found):
            problems.append(f"{at}: {path!r} does not hold an American price")
            return None
        prob = _implied(int(found))
        if prob is None:
            problems.append(f"{at}: {path!r} holds {found!r}, which is not a usable American price")
        return prob
    nums = []
    for path, found in got:
        if not _real(found):
            problems.append(f"{at}: {path!r} does not hold a number")
            return None
        nums.append(float(found))
    if op == "difference":
        return nums[0] - nums[1]
    if op == "sum":
        return math.fsum(nums)
    if op == "mean":
        return math.fsum(nums) / len(nums)
    if op == "ratio":
        if nums[1] == 0:
            problems.append(f"{at}: the ratio divides by zero")
            return None
        return nums[0] / nums[1]
    if nums[0] == 0:                      # percent_change
        problems.append(f"{at}: the percent change starts from zero")
        return None
    return (nums[1] - nums[0]) / abs(nums[0]) * 100.0


def _verify_one(packet: Mapping, d: Any, at: str, problems: list) -> Optional[dict]:
    if not isinstance(d, Mapping):
        problems.append(f"{at} is not a calculation")
        return None
    op, unit, value, inputs = d.get("op"), d.get("unit"), d.get("value"), d.get("inputs")
    if not isinstance(op, str) or op not in UNIT_RULES:
        problems.append(f"{at}: {op!r} is not a calculation the checker knows "
                        f"(it knows {', '.join(UNIT_RULES)})")
        return None
    rules = UNIT_RULES[op]
    if not isinstance(unit, str) or unit not in rules:
        problems.append(f"{at}: {unit!r} is not a unit {op} can be written in ({', '.join(rules)})")
        return None
    if not _real(value):
        problems.append(f"{at}: the value {value!r} is not a number")
        return None
    if not isinstance(inputs, list) or not all(isinstance(i, str) for i in inputs):
        problems.append(f"{at}: inputs must be a list of packet paths")
        return None
    lo, hi = _ARITY[op]
    if not lo <= len(inputs) <= hi:
        need = str(lo) if lo == hi else f"{lo} to {hi}"
        problems.append(f"{at}: {op} needs {need} input{'s' if hi > 1 else ''}, not {len(inputs)}")
        return None
    got, failed = [], False
    for path in inputs:
        ok, found = packet_mod.resolve_path(packet, path)
        if not ok:
            problems.append(f"{at}: input {path!r}: {found}")
            failed = True
        elif isinstance(found, dict) or (isinstance(found, list) and op != "count"):
            problems.append(f"{at}: input {path!r} is a group, not a single value")
            failed = True
        else:
            got.append((path, found))
    if failed:
        return None
    raw = _recompute(op, got, at, problems)
    if raw is None:
        return None
    scale, cap = rules[unit]
    expected = raw * scale
    if not _agrees(value, expected, cap):
        problems.append(f"{at}: {op} of those inputs is {_num_text(round(expected, 4))} {unit}, "
                        f"not {value!r}")
        return None
    return {"op": op, "unit": unit, "value": value,
            "inputs": [{"path": p, "label": _label(packet, p),
                        "value": len(v) if isinstance(v, list) else v} for p, v in got],
            "note": str(d.get("note") or "")[:NOTE_MAX]}


def verify_derivations(packet: Mapping, derived: Any, where: str = "derived") -> tuple:
    """`(verified, problems)` for one item's `derived` list.

    `verified` holds a record per derivation that recomputed exactly as declared: its op, unit and
    value, the packet paths it was computed from with a plain label and the value read at each, and
    the model's note. `problems` is plain text, one per derivation that did not hold (inputs absent
    or not numbers, a value that differs, an unknown op or unit); any problem strikes the item.
    None or an empty list is no derivation."""
    if derived is None:
        return [], []
    if not isinstance(derived, list):
        return [], [f"{where} is not a list"]
    if len(derived) > MAX_DERIVATIONS:
        return [], [f"{where} declares {len(derived)} calculations; at most {MAX_DERIVATIONS} are allowed"]
    problems: list = []
    verified = []
    for k, d in enumerate(derived):
        rec = _verify_one(packet, d, f"{where}[{k}]", problems)
        if rec is not None:
            verified.append(rec)
    return verified, problems


def _used(records: Sequence[Mapping], text: str) -> list:
    """The verified derivations whose number the prose actually says: a derivation the sentence does
    not use is not provenance for anything the reader sees, so it is not kept."""
    lits = numbers_in_prose(text)
    return [r for r in records if any(NumberPool([]).with_derived([r]).has(lit) for lit in lits)]


def derivation_sentence(rec: Mapping) -> str:
    """The short plain sentence that says where a calculated number came from, from a stored record:
    "11 days: calendar days (UTC) from the starter last start date to first pitch." No path, no code
    word; the labels were written when the record was verified."""
    op, unit = rec.get("op"), rec.get("unit")
    ins = list(rec.get("inputs") or [])
    names = [str(i.get("label") or "a figure in the data") for i in ins]
    head = f"{_num_text(rec.get('value'))} {unit}"
    if op == "days_between" and len(ins) == 2:
        days = [_calendar_day(i.get("value")) for i in ins]
        if None not in days and days[0] > days[1]:
            names.reverse()
        body = f"calendar days (UTC) from {names[0]} to {names[1]}"
    elif op == "difference" and len(names) == 2:
        body = f"{names[0]} minus {names[1]}"
    elif op == "sum":
        body = " plus ".join(names)
    elif op == "mean":
        body = "the average of " + ", ".join(names)
    elif op == "ratio" and len(names) == 2:
        body = f"{names[0]} divided by {names[1]}"
    elif op == "percent_change" and len(names) == 2:
        body = f"the change from {names[0]} to {names[1]}, as a percent of {names[0]}"
    elif op == "implied_probability" and ins:
        price = ins[0].get("value")
        shown = f" at {int(price):+d}" if _real(price) else ""
        body = f"the chance the price implies for {names[0]}{shown}"
    elif op == "count" and ins:
        body = f"how many entries {names[0]} lists"
    else:
        body = "worked out from the data"
    return f"{head}: {body}."


def derivation_sentences(records: Any) -> list:
    return [derivation_sentence(r) for r in records or [] if isinstance(r, Mapping)]


# ---------------------------------------------------------------------------
# one call
# ---------------------------------------------------------------------------

@dataclass
class CallCheck:
    problems: list = field(default_factory=list)
    downgrades: list = field(default_factory=list)
    # verified derivations the prose used: {"reasons": {index: [record]}, "case_against": [record]}
    derived: dict = field(default_factory=dict)


def _implied(price: Any) -> Optional[float]:
    try:
        return odds_math.american_to_probability(price)
    except (odds_math.OddsError, TypeError, ValueError):
        return None


def _check_reason(packet: Mapping, where: str, reason: Any, pool: NumberPool,
                  known: KnownNames, problems: list, *, required: bool,
                  used: Optional[list] = None) -> int:
    """Every problem with one {claim, evidence} (a reason, or a case against), appended to
    `problems`. `required` also demands a non-empty claim (a case against; a reason has never
    been held to that, and the UFC critic shares this routine). Returns how many evidence items it cited. The one routine both are checked by,
    so a case against is held to exactly the standard a reason is.

    `used` is passed only for an MLB packet (prompt v3): the item's `derived` list is verified,
    its failures are problems, and the numbers it verifies are allowed in THIS claim's prose and no
    other; the verified derivations the prose used are appended to `used`. Left None (UFC), a
    `derived` key is ignored and the number rule is exactly what it was."""
    if not isinstance(reason, Mapping):
        problems.append(f"{where} is not a claim with evidence")
        return 0
    claim = reason.get("claim")
    claim = claim if isinstance(claim, str) else ""
    evidence = reason.get("evidence") or []
    if required and not claim.strip():
        problems.append(f"{where} has no claim")
    if not evidence:
        problems.append(f"{where} cites no packet path")
    for k, ev in enumerate(evidence):
        ok, found = packet_mod.resolve_path(packet, ev.get("path"))
        if not ok:
            problems.append(f"{where}.evidence[{k}]: {ev.get('path')!r}: {found}")
            continue
        if isinstance(found, (dict, list)):
            problems.append(f"{where}.evidence[{k}]: {ev.get('path')!r} is a group, "
                            "not a single value")
            continue
        if not values_match(ev.get("value"), found):
            problems.append(f"{where}.evidence[{k}]: {ev.get('path')!r} holds {found!r}, "
                            f"not {ev.get('value')!r}")
    if used is not None:
        verified, d_problems = verify_derivations(packet, reason.get("derived"), f"{where}.derived")
        problems.extend(d_problems)
        pool = pool.with_derived(verified)
        used.extend(_used(verified, claim))
    for lit in unsupported_numbers(claim, pool):
        problems.append(f"{where} quotes {lit}, which is not a number in the packet")
    for word in banned_words(claim):
        problems.append(f"{where} uses the banned word {word!r}")
    for run in unsupported_names(claim, known):
        problems.append(f"{where} names {run!r}, which is not a name in the packet")
    return len(evidence)


def check_call(packet: Mapping, call: Mapping, pool: NumberPool,
               known: Optional[KnownNames] = None) -> CallCheck:
    """Every deterministic problem with one call. Empty `problems` = verified."""
    known = known or KnownNames.build(packet)
    out = CallCheck()
    p = out.problems
    sid = call.get("slot_id")
    market = packet_mod.slot(packet, sid)
    if market is None:
        return CallCheck(problems=[f"slot {sid!r} is not in the packet"])
    selection, verdict = call.get("selection"), call.get("verdict")
    opts = [o["selection"] for o in market["options"]]
    opt = packet_mod.option(packet, sid, selection)
    if opt is None:
        p.append(f"selection {selection!r} is not one of {opts}")
    else:
        lean = market["lean"]
        if verdict == "TAKE" and selection != lean:
            p.append(f"TAKE must name the lean {lean!r}, not {selection!r}")
        if verdict == "TAKE_OTHER_SIDE":
            if len(opts) < 2:
                p.append("this market has no other side to take")
            elif selection == lean:
                p.append(f"TAKE_OTHER_SIDE must name the side other than the lean {lean!r}")

    price, book = call.get("price"), call.get("book")
    takes = verdict in ("TAKE", "TAKE_OTHER_SIDE")
    if opt is not None:
        if price is not None or book is not None:
            if not packet_mod.has_quote(packet, sid, selection, book, price):
                p.append(f"{book!r} at {price!r} is not a quote for {selection!r} in the packet")
        elif takes:
            p.append("a TAKE must name the price and book it would be taken at")

    if takes and isinstance(price, int) and price <= TAKE_PRICE_FLOOR:
        p.append(f"a {market['market']} at {price} is {TAKE_PRICE_FLOOR} or worse and cannot be a TAKE")

    fe, pp = call.get("fair_estimate"), call.get("pass_price")
    if takes:
        if fe is None:
            p.append("a TAKE needs a fair_estimate")
        if pp is None:
            p.append("a TAKE needs a pass_price")
        implied = _implied(price) if price is not None else None
        if fe is not None and implied is not None and fe <= implied:
            p.append(f"the call contradicts itself: fair_estimate {fe} is not above the "
                     f"break-even {round(implied, 4)} of {price}")
        if fe is not None and pp is not None:
            pp_imp = _implied(pp)
            if pp_imp is None or abs(pp_imp - fe) > PASS_PRICE_TOLERANCE:
                p.append(f"pass_price {pp} is not the break-even price of fair_estimate {fe}")
        if price is not None and pp is not None:
            try:
                if odds_math.american_to_decimal(pp) > odds_math.american_to_decimal(price) + 1e-9:
                    p.append("pass_price is a better price than the price taken, so the "
                             "call would already be a pass")
            except odds_math.OddsError:
                p.append("pass_price is not a usable price")

    reasons = call.get("reasons") or []
    n_evidence = 0
    mlb = is_mlb_packet(packet)
    for j, reason in enumerate(reasons):
        used = [] if mlb else None
        n_evidence += _check_reason(packet, f"reasons[{j}]", reason, pool, known, p, required=False,
                                    used=used)
        if used:
            out.derived.setdefault("reasons", {})[j] = used
    if mlb:
        # Prompt v2: a bet is published with the strongest reason it loses, checked exactly as a
        # reason is. A PASS carries none (and publishes none, see `verify`).
        if takes:
            against = call.get("case_against")
            if against is None:
                p.append("a TAKE needs a case_against: the strongest reason from the packet that "
                         "this bet loses")
            else:
                used = []
                _check_reason(packet, "case_against", against, pool, known, p, required=True,
                              used=used)
                if used:
                    out.derived["case_against"] = used
    for text_key in ("what_would_change_it",):
        text = call.get(text_key) or ""
        for lit in unsupported_numbers(text, pool):
            p.append(f"{text_key} quotes {lit}, which is not a number in the packet")
        for word in banned_words(text):
            p.append(f"{text_key} uses the banned word {word!r}")
        for run in unsupported_names(text, known):
            p.append(f"{text_key} names {run!r}, which is not a name in the packet")

    # not struck, only lowered
    if call.get("confidence") == "high":
        stale = [m for m in packet.get("missing", [])
                 if m["kind"] == "stale" and m["item"] in (sid, "prop_prices")
                 and (sid.startswith("prop_") or m["item"] == sid)]
        if stale:
            out.downgrades.append("confidence lowered: the price it rests on is stale")
        elif n_evidence < 2:
            out.downgrades.append("confidence lowered: fewer than two packet facts cited")
    return out


# ---------------------------------------------------------------------------
# the whole analysis
# ---------------------------------------------------------------------------

@dataclass
class Verified:
    summary: Optional[str]
    summary_status: str            # "ok" | "withheld"
    summary_problems: list
    calls: list                    # published calls, in slot order
    struck: list                   # [{slot_id, original, problems}]
    model_critic: str              # "off" | "ran" | "did not run"
    # verified derivations the published summary used (prompt v3); empty when none, and always for UFC
    summary_derived: list = field(default_factory=list)


def _lower(confidence: str) -> str:
    i = CONFIDENCE_ORDER.index(confidence) if confidence in CONFIDENCE_ORDER else 0
    return CONFIDENCE_ORDER[max(0, i - 1)]


def _struck_call(packet: Mapping, call: Mapping, problems: Sequence[str]) -> dict:
    """The published replacement for a call that failed: a PASS that says so.

    Keeps the selection and the quote only when they are real; everything the
    model asserted (estimate, reasons) is dropped from the published call.
    """
    sid = call.get("slot_id")
    market = packet_mod.slot(packet, sid) or {"market": call.get("market"), "options": [], "lean": None}
    selection = call.get("selection")
    if packet_mod.option(packet, sid, selection) is None:
        selection = market.get("lean")
    price, book = call.get("price"), call.get("book")
    if not packet_mod.has_quote(packet, sid, selection, book, price):
        price = book = None
    out = {
        "slot_id": sid, "market": market["market"], "selection": selection,
        "verdict": "PASS", "price": price, "book": book, "fair_estimate": None,
        "confidence": "low",
        "reasons": [{"claim": UNVERIFIED.capitalize() + ".", "evidence": []}],
        "pass_price": None,
        "what_would_change_it": "A call that can be checked against the data.",
        # The published call carries the status and NOTHING the model said: the
        # problems quote its claims (an invented number, a wrong value), and a
        # reader must not meet an unsupported claim even in a list of reasons it
        # was struck. The detail is in the ledger row's `struck` audit trail.
        "verification": {"status": UNVERIFIED, "problems": []},
    }
    if is_mlb_packet(packet):
        out["case_against"] = None
    return out


def _published_reason(reason: Any, derived: Optional[Sequence[Mapping]]) -> Any:
    """A kept reason (or case against) without the model's `derived`, plus the verified records the
    prose used. A reason with none is what it has always been: {claim, evidence} and nothing more."""
    if not isinstance(reason, Mapping):
        return reason
    out = {k: v for k, v in reason.items() if k != "derived"}
    if derived:
        out["derived"] = [dict(r) for r in derived]
    return out


def verify(packet: Mapping, output: Mapping, *,
           model_critic: Optional[Mapping] = None,
           model_critic_status: str = "off",
           known: Optional[KnownNames] = None,
           extra_numbers: Sequence[float] = ()) -> Verified:
    """Run the deterministic pass (and fold in a model critic's verdict, when
    one ran) over a shape-valid analysis. Never raises on bad content: bad
    content is what it exists to strike.

    `model_critic` is the parsed critic JSON ({"checks": [...],
    "summary_supported", "summary_problem"}); it can only strike. `known` is
    the name vocabulary to check against; the default is the MLB one, and
    another sport passes its own (`ufc_analyst.known_names`). `extra_numbers`
    are numbers the packet states inside a string and a claim may repeat (the
    number in an event's name); the default adds nothing.
    """
    base_pool = NumberPool.base(packet)
    if extra_numbers:
        base_pool = NumberPool(base_pool.values + _expand(extra_numbers))
    known = known or KnownNames.build(packet)
    flagged: dict = {}
    if model_critic:
        for c in model_critic.get("checks") or []:
            if isinstance(c, Mapping) and c.get("supported") is False:
                flagged[c.get("slot_id")] = str(c.get("problem") or "the model critic "
                                                "found the reasons overreach the evidence")[:300]
    calls, struck = [], []
    for call in output.get("calls") or []:
        check = check_call(packet, call, base_pool.plus([call]), known)
        problems = list(check.problems)
        if call.get("slot_id") in flagged:
            problems.append("model critic: " + flagged[call["slot_id"]])
        if problems:
            struck.append({"slot_id": call.get("slot_id"), "original": call,
                           "problems": problems})
            calls.append(_struck_call(packet, call, problems))
            continue
        kept = {k: call[k] for k in ("slot_id", "market", "selection", "verdict", "price",
                                     "book", "fair_estimate", "confidence", "reasons",
                                     "pass_price", "what_would_change_it")}
        # The published reasons carry the VERIFIED derivations (with what they were computed from),
        # never the model's own list: nothing the checker did not recompute is kept. A UFC reason
        # has none to verify, so a `derived` key a session sent is dropped, not published.
        kept["reasons"] = [_published_reason(r, check.derived.get("reasons", {}).get(j))
                           for j, r in enumerate(call["reasons"])]
        if is_mlb_packet(packet):
            # a PASS publishes no case against whatever the model sent: nothing unchecked is shown
            kept["case_against"] = (_published_reason(call.get("case_against"),
                                                      check.derived.get("case_against"))
                                    if call["verdict"] != "PASS" else None)
        kept["verification"] = {"status": "verified", "problems": []}
        if check.downgrades:
            kept["confidence"] = _lower(kept["confidence"])
            kept["verification"]["downgrades"] = check.downgrades
        calls.append(kept)

    summary = output.get("summary")
    s_problems = []
    s_derived: list = []
    pool = base_pool.plus([c for c in calls if c["verification"]["status"] == "verified"])
    if isinstance(summary, str):
        if is_mlb_packet(packet):
            s_verified, d_problems = verify_derivations(packet, output.get("summary_derived"),
                                                        "the summary's derived")
            s_problems.extend(d_problems)
            pool = pool.with_derived(s_verified)
            s_derived = _used(s_verified, summary)
        for lit in unsupported_numbers(summary, pool):
            s_problems.append(f"the summary quotes {lit}, which is not a number in the packet")
        for word in banned_words(summary):
            s_problems.append(f"the summary uses the banned word {word!r}")
        for run in unsupported_names(summary, known):
            s_problems.append(f"the summary names {run!r}, which is not a name in the packet")
    else:
        s_problems.append("the summary is missing")
    if model_critic and model_critic.get("summary_supported") is False:
        s_problems.append("model critic: " + str(model_critic.get("summary_problem") or
                                                "the summary overreaches the evidence")[:300])
    return Verified(
        summary=None if s_problems else summary,
        summary_status="withheld" if s_problems else "ok",
        summary_problems=s_problems,
        calls=calls, struck=struck, model_critic=model_critic_status,
        summary_derived=[] if s_problems else s_derived)
