"""Name normalisation and matching for people (fighters now, players later).

`normalise` folds accents, case and punctuation and drops a quoted nickname, so
"José Aldo", "Jose Aldo" and 'José "Junior" Aldo' are the same string. `match`
finds a person from a typed query and refuses to guess: when two people fit equally
well it says so and lists them, because silently picking one is how a matchup gets
built for the wrong fighter.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

_QUOTED = re.compile(r"[\"“”][^\"“”]*[\"“”]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Letters that Unicode does not decompose into a base letter plus an accent, so NFKD
# alone would drop them ("Błachowicz" would become "b achowicz").
_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                       "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i", "þ": "th"})


def normalise(name: Optional[str]) -> str:
    if not name:
        return ""
    text = _QUOTED.sub(" ", str(name)).translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("'", "").replace("’", "")
    return _NON_ALNUM.sub(" ", text).strip()


def tokens(name: Optional[str]) -> List[str]:
    return [t for t in normalise(name).split(" ") if t]


@dataclass
class MatchResult:
    best: Optional[str]                       # the id, or None when no single best match
    ambiguous: bool
    candidates: List[Tuple[str, str, float]] = field(default_factory=list)  # (id, name, score)


def _score(query_tokens: List[str], name: str) -> float:
    cand = tokens(name)
    if not cand or not query_tokens:
        return 0.0
    if cand == query_tokens:
        return 1.0
    qs, cs = set(query_tokens), set(cand)
    if qs <= cs:
        # every typed word is in the name ("naurdiev" in "ismail naurdiev")
        return 0.9 if len(qs) > 1 or len(cs) <= 3 else 0.85
    overlap = len(qs & cs) / len(qs | cs)
    return round(0.8 * overlap, 4)


def match(query: str, people: Dict[str, Iterable[str]], *, limit: int = 5,
          threshold: float = 0.6) -> MatchResult:
    """`people` maps an id to every name it may be called by (name, full name, aliases)."""
    q = tokens(query)
    scored = []
    for pid, names in people.items():
        best_name, best = "", 0.0
        for n in names:
            s = _score(q, n)
            if s > best:
                best_name, best = n, s
        if best >= threshold:
            scored.append((pid, best_name, best))
    scored.sort(key=lambda t: (-t[2], t[1], t[0]))
    top = scored[:limit]
    if not top:
        return MatchResult(best=None, ambiguous=False, candidates=[])
    if len(top) > 1 and top[1][2] == top[0][2]:
        return MatchResult(best=None, ambiguous=True, candidates=top)
    return MatchResult(best=top[0][0], ambiguous=False, candidates=top)


# ---------------------------------------------------------------------------
# Two spellings of ONE person (tennis players, any sport with named competitors)
# ---------------------------------------------------------------------------
#
# `match` above finds a person from a typed query among many; `person_score` answers a narrower question that
# result-matching needs: "are these two strings the same human?". It is deliberately strict -- a wrong "yes"
# grades a bet on the wrong player, a wrong "no" only leaves the bet to void after 72 hours.

PERSON_EXACT = 1.0          # same words in the same order (after accents, case, punctuation are folded)
PERSON_REVERSED = 0.97      # same words, other order: "Sinner Jannik"
PERSON_INITIALS = 0.90      # "J. Sinner" for "Jannik Sinner": initials only where the first names should be
PERSON_DROPPED = 0.88       # a middle name or particle dropped: "Alex Minaur" for "Alex de Minaur"
PERSON_MIN = PERSON_DROPPED  # the lowest score a caller may treat as "the same person"


def person_score(a: Optional[str], b: Optional[str]) -> float:
    """How surely two names are one person: PERSON_EXACT, PERSON_REVERSED, PERSON_INITIALS, PERSON_DROPPED or 0.0.

    Never fuzzy: a nickname ("Alex" for "Alexander"), a different first name or a different surname scores 0.
    A lone token (a surname by itself) scores 0 unless both names are that same single token."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return PERSON_EXACT if len(ta) > 1 else PERSON_REVERSED
    if len(ta) < 2 or len(tb) < 2:
        return 0.0
    if sorted(ta) == sorted(tb):
        return PERSON_REVERSED
    # reversed-order forms with initials ("Sinner J.") are read in the usual order first
    for first, second in ((ta, tb), (tb, ta)):
        if _initials_of(first, second):
            return PERSON_INITIALS
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if (len(short) < len(long_) and set(short) <= set(long_) and short[0] == long_[0]
            and short[-1] == long_[-1] and len(short[0]) > 1):
        return PERSON_DROPPED
    return 0.0


def _initials_of(initialled: List[str], full: List[str]) -> bool:
    """True when `initialled` is `full` with some given names cut to one letter ("j sinner" / "jannik sinner").

    Every word of `initialled` must be a word of `full`; each one-letter token must be the first letter of a
    DIFFERENT remaining word of `full`; and `full`'s last word (the surname) must be among the words given, so
    a name is never decided by initials alone."""
    letters = [t for t in initialled if len(t) == 1]
    words = [t for t in initialled if len(t) > 1]
    if not letters or not words or full[-1] not in words:
        return False
    remaining = list(full)
    for word in words:
        if word not in remaining:
            return False
        remaining.remove(word)
    for letter in letters:
        pick = next((t for t in remaining if len(t) > 1 and t[0] == letter), None)
        if pick is None:
            return False
        remaining.remove(pick)
    return True
