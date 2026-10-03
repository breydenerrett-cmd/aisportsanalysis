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
