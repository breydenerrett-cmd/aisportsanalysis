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

WHAT THIS CANNOT CATCH
----------------------
It checks that quoted facts are true and that the call is coherent. It cannot
tell whether a TRUE fact is a good reason, whether the summary and the calls
agree in spirit, or whether the model's probability is any good. The record
measures that, in public, afterward; this module only stops fabrication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from src.analyst import packet as packet_mod
from src.analyst.analyst import TAKE_PRICE_FLOOR
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
    "Last, First" forms turned round, and the clubs."""
    blob: str
    team_words: frozenset

    @classmethod
    def build(cls, packet: Mapping) -> "KnownNames":
        pieces, team_words = [], set()
        for _p, v in packet_mod.iter_leaves(packet):
            if not isinstance(v, str):
                continue
            pieces.append(_norm(v))
            if ", " in v and v.count(",") == 1:
                last, first = v.split(", ")
                pieces.append(_norm(f"{first} {last}"))
        for team in labels.TEAM_NAMES.values():
            for key in ("city", "name", "full"):
                if team.get(key):
                    pieces.append(_norm(team[key]))
                    team_words.update(_norm(team[key]).split())
        blob = " | ".join(p for p in pieces if p).join(("| ", " |"))
        return cls(blob, frozenset(team_words))

    def _known(self, segment: str, single: bool) -> bool:
        if single:
            return segment in self.team_words      # "Rays", "Bay", never a bare first name
        # pieces are separated by " | ", so a segment can never span two of them
        return segment in _PHRASES or f" {segment} " in self.blob

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
# one call
# ---------------------------------------------------------------------------

@dataclass
class CallCheck:
    problems: list = field(default_factory=list)
    downgrades: list = field(default_factory=list)


def _implied(price: Any) -> Optional[float]:
    try:
        return odds_math.american_to_probability(price)
    except (odds_math.OddsError, TypeError, ValueError):
        return None


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
    for j, reason in enumerate(reasons):
        claim = reason.get("claim", "")
        evidence = reason.get("evidence") or []
        if not evidence:
            p.append(f"reasons[{j}] cites no packet path")
        n_evidence += len(evidence)
        for k, ev in enumerate(evidence):
            ok, found = packet_mod.resolve_path(packet, ev.get("path"))
            if not ok:
                p.append(f"reasons[{j}].evidence[{k}]: {ev.get('path')!r}: {found}")
                continue
            if isinstance(found, (dict, list)):
                p.append(f"reasons[{j}].evidence[{k}]: {ev.get('path')!r} is a group, "
                         "not a single value")
                continue
            if not values_match(ev.get("value"), found):
                p.append(f"reasons[{j}].evidence[{k}]: {ev.get('path')!r} holds {found!r}, "
                         f"not {ev.get('value')!r}")
        for lit in unsupported_numbers(claim, pool):
            p.append(f"reasons[{j}] quotes {lit}, which is not a number in the packet")
        for word in banned_words(claim):
            p.append(f"reasons[{j}] uses the banned word {word!r}")
        for run in unsupported_names(claim, known):
            p.append(f"reasons[{j}] names {run!r}, which is not a name in the packet")
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
    return {
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


def verify(packet: Mapping, output: Mapping, *,
           model_critic: Optional[Mapping] = None,
           model_critic_status: str = "off") -> Verified:
    """Run the deterministic pass (and fold in a model critic's verdict, when
    one ran) over a shape-valid analysis. Never raises on bad content: bad
    content is what it exists to strike.

    `model_critic` is the parsed critic JSON ({"checks": [...],
    "summary_supported", "summary_problem"}); it can only strike.
    """
    base_pool = NumberPool.base(packet)
    known = KnownNames.build(packet)
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
        kept["verification"] = {"status": "verified", "problems": []}
        if check.downgrades:
            kept["confidence"] = _lower(kept["confidence"])
            kept["verification"]["downgrades"] = check.downgrades
        calls.append(kept)

    summary = output.get("summary")
    s_problems = []
    pool = base_pool.plus([c for c in calls if c["verification"]["status"] == "verified"])
    if isinstance(summary, str):
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
        calls=calls, struck=struck, model_critic=model_critic_status)
