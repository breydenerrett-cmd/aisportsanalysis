"""A hound's identity: what it is FOR, so Send to training never cuts it away.

THE BUG (production 2026-10-29). HOCKEYCHIEF, a hound its owner named for hockey, bet NHL, tennis and MLB. Training's card
said "5 NHL bets went 2-3 (-0.42u at the average price), its weakest part, so the new version no longer takes them" and
proposed dropping NHL, while the coach's own read on the same card said the losing run "turns up in 78% of random orders of
the same results". Five bets are a coin flip, and the one sport the owner built the hound for was the one on the cut list. The
owner's reply in the tweak box: "THE ONLY TWEAKS YOU HAVE ARE CHANGING THE SPORTS IT BETTING ON. NO THANKS".

THE LOCK, IN THREE PARTS
  * A hound's CORE is the sports (and markets) it is for. ``core_of`` infers the sports from its NAME and its English
    description (tagline, and the labels on a custom rule) with a small word map: "hockeychief" is hockey is NHL. An explicit
    ``core`` list on the spec (``user_spec.CORE_FIELD``, optional, validated against the sport menu) wins and is added to.
  * The coach never proposes removing a core sport or market: ``training.analyse`` leaves it out of the weak spots,
    ``training.menu`` and ``training.propose`` skip it, and the tweak menu (``retune.full_menu``) does not offer it.
  * Only the owner's own WORDS lift the lock, and only for the thing they name: ``asks_to_drop`` reads a tweak line for a drop
    verb beside the sport ("drop hockey", "stop betting NHL") and says no to a negated one ("don't drop hockey", "stop dropping
    the sports"). "Change the sports" is not an ask to drop hockey.

THE WORD MAP IS CONSERVATIVE ON PURPOSE. A false match costs nothing worse than one fewer cut the coach could have proposed on
a sport it was never going to cut for a reason it could prove; a missed match is the bug above. Words match from the START of a
word ("hockeychief" and "HockeyHank" are hockey; "Dice Roller" is not "ice"), and a camelCase name is split first ("BigNBA").

Deterministic, no model, no network, no clock: the same hound always gives the same core. Paper only.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional, Sequence

from src.hounds import user_spec

# (sport code on the menu, words a name or description starts with, words it must equal). The codes are the spec's own
# (user_spec.SPORTS): the UFC family is "MMA" there.
SPORT_WORDS = (
    ("MLB", ("baseball", "mlb"), ()),
    ("NFL", ("football", "nfl"), ()),
    ("NCAAF", ("ncaaf",), ()),
    ("GRIDIRON", ("gridiron",), ()),
    ("NBA", ("basketball", "nba"), ()),
    ("WNBA", ("wnba",), ()),
    ("NCAAB", ("ncaab",), ()),
    ("NHL", ("hockey", "nhl", "puck"), ("ice",)),
    ("SOCCER", ("soccer",), ()),
    ("TENNIS", ("tennis",), ("atp", "wta")),
    ("CRICKET", ("cricket",), ()),
    ("MMA", ("ufc", "mma"), ()),
    ("RUGBY", ("rugby",), ()),
    ("AFL", (), ("afl",)),
)
MARKET_WORDS = (
    ("moneyline", ("moneyline",), ("ml",)),
    ("spread", ("spread", "runline", "puckline"), ()),
    ("total", ("totals",), ("overunder", "ou")),
)

SOURCES = ("spec", "name", "description")

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN = re.compile(r"[a-z0-9]+")
_NORM_JUNK = re.compile(r"[^a-z0-9+\- ]+")


def _norm(text: Any) -> str:
    out = str(text or "").lower().replace("’", "").replace("'", "")
    return re.sub(r"\s+", " ", _NORM_JUNK.sub(" ", out)).strip()


def _tokens(text: Any) -> list:
    """The lower-case words of a name or description, a camelCase run split first ("BigNBA" is "big" and "nba")."""
    return _TOKEN.findall(_CAMEL.sub(" ", str(text or "")).lower())


def _hits(tokens: Sequence[str], table: Sequence[tuple]) -> list:
    found = []
    for code, starts, exact in table:
        if any(t.startswith(s) for t in tokens for s in starts) or any(t in exact for t in tokens):
            found.append(code)
    return found


def sports_in(text: Any) -> list:
    """The sport codes a piece of free text names, in the menu's order ("hockeychief" gives ["NHL"])."""
    found = set(_hits(_tokens(text), SPORT_WORDS))
    return [s for s in user_spec.SPORTS if s in found]


def markets_in(text: Any) -> list:
    """The market names a piece of free text names ("moneyline", "spread", "total"), in the menu's order."""
    found = set(_hits(_tokens(text), MARKET_WORDS))
    return [m for m in ("moneyline", "spread", "total") if m in found]


def _description_of(hound: Mapping, spec: Mapping) -> str:
    """The English the owner wrote about the hound: its tagline and, on a custom-rules hound, each rule's own label."""
    parts = [hound.get("tagline") or spec.get("tagline") or ""]
    for rule in spec.get("rules") or ():
        if isinstance(rule, Mapping):
            parts.append(rule.get("label") or "")
    return " ".join(str(p) for p in parts if p)


def identity_of(hound: Optional[Mapping]) -> dict:
    """``{sports, markets, source}``: the sports and markets this hound is for, and where that was read from (``spec`` for an
    explicit core, else ``name``, else ``description``; None when nothing says). Sports the hound does not bet are left out
    (nothing to protect). ``hound`` is the user store's row (``name``, ``tagline``, ``spec``), or anything shaped like it."""
    hound = hound if isinstance(hound, Mapping) else {}
    spec = hound.get("spec") if isinstance(hound.get("spec"), Mapping) else {}
    name = hound.get("name") or spec.get("name") or ""
    explicit = [s for s in (spec.get(user_spec.CORE_FIELD) or ()) if s in user_spec.SPORTS]
    by_name, by_description = sports_in(name), sports_in(_description_of(hound, spec))
    market_by = markets_in(name) + markets_in(_description_of(hound, spec))
    source = ("spec" if explicit else "name" if by_name else "description" if by_description else None)
    sports = set(explicit) | set(by_name) | set(by_description)
    bet_sports, bet_markets = spec.get("sports"), spec.get("markets")
    out_sports = [s for s in user_spec.SPORTS if s in sports and (not bet_sports or s in bet_sports)]
    out_markets = [m for m in ("moneyline", "spread", "total") if m in set(market_by) and (not bet_markets or m in bet_markets)]
    return {"sports": out_sports, "markets": out_markets, "source": source if (out_sports or out_markets) else None}


def core_of(hound: Optional[Mapping]) -> list:
    """The sport codes this hound is for (HOCKEYCHIEF is ["NHL"]), [] when its name and words say none."""
    return identity_of(hound)["sports"]


def blocks(core: Optional[Mapping], dimension: str, key: Any) -> bool:
    """True when removing ``key`` of ``dimension`` ("sport" or "market") would cut something in the core."""
    if not core:
        return False
    if dimension == "sport":
        return key in (core.get("sports") or ())
    if dimension == "market":
        return key in (core.get("markets") or ())
    return False


def core_view(core: Optional[Mapping]) -> dict:
    """What the review card carries: ``{sports, markets, source, kept, text}``. ``text`` is the one line the card shows
    ("Core: NHL (kept)"), empty when the hound has no core. Written here, drawn by the page as it is."""
    core = core or {}
    sports, markets = list(core.get("sports") or ()), list(core.get("markets") or ())
    names = [user_spec.SPORT_LABELS.get(s, s) for s in sports] + [m for m in markets]
    text = f"Core: {', '.join(names)} (kept)" if names else ""
    return {"sports": sports, "markets": markets, "source": core.get("source"), "kept": True, "text": text}


# ---------------------------------------------------------------------------
# the owner's words
# ---------------------------------------------------------------------------

# A verb that means "stop doing this sport". "stop betting" drops; "stop changing" does not (see _NEGATED).
_DROP = re.compile(r"\b(?:drop\w*|remov\w*|cut(?:ting)?|ditch\w*|exclud\w*|skip\w*|without|no more|no longer|get rid of|"
                   r"take out|leave out|stop (?:bet\w*|look\w*|play\w*|tak\w*)|quit (?:bet\w*|look\w*|play\w*)|"
                   r"(?:dont|do not) (?:bet|play|take|look)\w*)\b")
# "dont drop hockey", "stop dropping the sports", "never cut it": the owner is asking for the opposite
_NEGATED = re.compile(r"\b(?:dont|do not|never|stop|quit|no need to|please dont)\s+(?:\w+\s+){0,2}"
                      r"(?:drop\w*|remov\w*|cut\w*|ditch\w*|chang\w*|touch\w*|exclud\w*|skip\w*)\b")


def _sentences(line: Any) -> list:
    return [s for s in re.split(r"[.;!?\n]+", str(line or "")) if s.strip()]


def asks_to_drop(lines: Iterable[Any], thing: str) -> bool:
    """True when one of the owner's lines explicitly asks to drop ``thing`` (a sport code or a market name): a drop verb and
    the sport (or market) named in the same sentence, and not negated. Anything less is not an ask."""
    for line in lines or ():
        for sentence in _sentences(line):
            t = _norm(sentence)
            named = set(sports_in(sentence)) | set(markets_in(sentence))
            if thing in named and _DROP.search(t) and not _NEGATED.search(t):
                return True
    return False


_SPORT_ALT = "(?:" + "|".join(sorted({w for _c, starts, exact in SPORT_WORDS for w in (*starts, *exact) if len(w) > 3} | {"nhl", "nfl", "nba", "mlb", "ufc", "mma"},
                                      key=len, reverse=True)) + ")"
_CHANGE = r"(?:chang\w*|switch\w*|swap\w*|alter\w*|cutt?\w*|drop\w*|remov\w*|narrow\w*|touch\w*|tweak\w*|mess\w*)"
_KEEP_PATTERNS = tuple(re.compile(p) for p in (
    r"\b(?:stop|quit|dont|do not|never|no more|enough|please dont)\b.{0,20}\b" + _CHANGE + r"\b.{0,15}\b(?:sports?|leagues?)\b",
    r"\bkeep\b.{0,12}\b(?:the |my |its |our )?(?:sports?|leagues?)\b",
    r"\bkeep\b.{0,10}\b" + _SPORT_ALT + r"\b",
    r"\b(?:same|current|existing|original) (?:sports?|leagues?)\b",
    r"\bleave\b.{0,12}\b(?:sports?|leagues?)\b",
))
# "the only tweaks you have are changing the sports ... no thanks": a change to the sports named in a complaint
_COMPLAINT_CHANGE = re.compile(r"\b" + _CHANGE + r"\b.{0,20}\b(?:sports?|leagues?)\b")
_COMPLAINT_MARK = re.compile(r"\b(?:no thanks?|no thank you|not interested|nope|only (?:tweaks?|changes?|options?|things?|ideas?|"
                             r"suggestions?|proposals?)|keeps? (?:changing|cutting|dropping|removing))\b")
_ASKS_FOR_MORE = re.compile(r"\b(?:more|add|other|another|different|additional|extra)\b.{0,12}\b(?:sports?|leagues?)\b")
_FOCUS_PATTERNS = tuple(re.compile(p) for p in (
    r"\bonly\b.{0,14}\b" + _SPORT_ALT + r"\b",
    r"\bfocus\w*\b.{0,20}\b" + _SPORT_ALT + r"\b",
    r"\bstick\w*\b.{0,10}\bto\b.{0,10}\b" + _SPORT_ALT + r"\b",
    r"\bjust\b.{0,8}\b" + _SPORT_ALT + r"\b",
    r"\bspecial\w*\b.{0,15}\b" + _SPORT_ALT + r"\b",
))


def intents_in(line: Any) -> dict:
    """What the owner's words say about the hound's sports: ``{"keep": bool, "focus": [codes] | None}``. ``focus`` is the
    sports the line asks the hound to narrow to ("only hockey", "focus on NHL"); ``keep`` is "stop changing the sports",
    "keep the sports", "keep NHL", or the complaint that the only tweaks on offer change them. Plain word rules over the
    normalised line, the same stance as ``retune.kinds_in``; a model is never asked."""
    t = _norm(line)
    if not t:
        return {"keep": False, "focus": None}
    focus = None
    if any(p.search(t) for p in _FOCUS_PATTERNS):
        named = sports_in(line)
        focus = named or None
    keep = any(p.search(t) for p in _KEEP_PATTERNS)
    if not keep and _COMPLAINT_CHANGE.search(t) and _COMPLAINT_MARK.search(t) and not _ASKS_FOR_MORE.search(t):
        keep = True
    return {"keep": keep, "focus": focus}
