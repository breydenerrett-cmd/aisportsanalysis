"""The quiz's "Describe it first" door: a sentence in, a draft spec out, and only the questions the draft left open.

The person types a strategy ("NHL underdog moneylines, four bets a day at most"). The English reader (src/hounds/english/parser.py)
reads what it can and says plainly what it cannot check. This module adds two things on top of that reader and nothing else:

  1. THE SPORT WORDS. The reader's rule vocabulary knows MLB and NFL only, so a hockey sentence came back as "covers MLB and NFL".
     When the reader had to assume its default sports and the words name a sport, the draft takes the sport the words named, and
     the sport word is taken off the can't-check list (it was understood, just not by the rule reader).
  2. THE FOLLOW-UP QUESTIONS. `questions()` asks only what the draft leaves open, by plain rules (see its docstring). The page
     answers them, and the answers are applied ONLY where the draft is silent: the person's own words always win.

Nothing here saves, places or grades anything. The draft still goes through the real validator (`user_spec.validate_spec`) and the
composer before it can become a hound; this module only decides what to ask next.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping

from src.hounds import user_spec
from src.hounds.english import parser as english_parser
from src.hounds.english import render

# The prop stats the menu supports. Player props are MLB only (quiz library, the "props" market), so the stat question offers these
# and only for MLB. The labels are the menu's plain names for them.
PROP_STATS = (
    ("batter_hits", "Hits"),
    ("batter_total_bases", "Total bases"),
    ("batter_home_runs", "Home runs"),
    ("pitcher_strikeouts", "Pitcher strikeouts"),
)
PROP_SPORT = "MLB"
# The words that say a prop was meant, even when no stat was named ("MLB player props").
_PROP_WORDS = re.compile(r"\bprops?\b|\bplayer\b", re.IGNORECASE)
# The reader's own note when it had to assume its default sports (english/parser.py), matched here by its words.
_ASSUMED_SPORTS_NOTE = "no sport was named"
# Sport words the reader does not check by rule, so they must not stay on the can't-check list once the sport was read.
_SPORT_WORDS = re.compile(r"\b(?:hockey|basketball|nhl|nba|wnba|ncaab|ncaaf|soccer|tennis|mma|ufc|nfl|mlb|cricket|rugby)\b",
                          re.IGNORECASE)

_SPORT_QUESTION = {"id": "sports", "title": "Which sports should it bet?", "kind": "sports",
                   "sub": "Pick as many as you like, or all of them."}
_NAME_LOOK_QUESTION = {"id": "finish", "title": "Name it and dress it.", "kind": "finish",
                       "sub": "Both are optional. A name is suggested if you skip it."}


def _has_price_band(draft: Mapping) -> bool:
    return any(r.get("price_min") is not None or r.get("price_max") is not None for r in draft.get("rules") or [])


def _has_stat_rule(draft: Mapping) -> bool:
    stats = {sid for sid, _ in PROP_STATS}
    return any(m in stats for r in draft.get("rules") or [] for m in r.get("markets") or [])


def questions(draft: Mapping, named_sports: Iterable[str] = (), text: str = "", levels: Iterable[Mapping] = ()) -> list:
    """The follow-up questions the draft leaves open, in the order the page asks them. Plain rules, no model:

      sports      no sport named in the words                     -> ask which sports (the sport grid)
      risk        no price band in any rule                        -> ask how bold (three choices; sets the price band)
      stats       props named in the words with no stat            -> ask which stats (MLB's menu only)
      aggression  no bets-a-day cap, or no stake                    -> ask how aggressive (three levels; cap and stake only)
      finish      always last                                       -> name and look

    ``levels`` is the library's risk_levels table (the three choices). ``text`` is the person's words, for the props check."""
    named = list(named_sports or [])
    level_rows = [dict(lv) for lv in levels]
    out: list = []
    if not named:
        out.append(dict(_SPORT_QUESTION))
    if not _has_price_band(draft):
        out.append({"id": "risk", "title": "How bold should it be?", "kind": "choice",
                    "sub": "One choice sets its prices, its stake and its bets a day.", "choices": level_rows})
    if _PROP_WORDS.search(text or "") and not _has_stat_rule(draft) and (not named or PROP_SPORT in named):
        out.append({"id": "stats", "title": "Which stats?", "kind": "choice", "multi": True,
                    "sub": "Player props are MLB only.",
                    "choices": [{"id": sid, "name": label} for sid, label in PROP_STATS]})
    if "max_bets_per_day" not in draft or "stake_units" not in draft:
        out.append({"id": "aggression", "title": "How aggressive?", "kind": "choice",
                    "sub": "How many bets a day, and how big each one is.", "choices": level_rows})
    out.append(dict(_NAME_LOOK_QUESTION))
    return out


def _sport_phrase(codes: list) -> str:
    labels = [user_spec.SPORT_LABELS.get(c, c) for c in codes]
    if len(labels) <= 2:
        return " and ".join(labels)
    return ", ".join(labels[:-1]) + ", and " + labels[-1]


def read(text: Any, levels: Iterable[Mapping] = ()) -> dict:
    """The describe door's answer for one sentence: the draft, what was understood, what cannot be checked yet, the English of
    the draft (once it validates) and the follow-up questions. Saves nothing."""
    parsed = english_parser.parse(text)
    draft = copy.deepcopy(parsed.get("draft") or {})
    assumed = list(parsed.get("assumed") or [])
    not_understood = list(parsed.get("not_understood") or [])
    named = english_parser.named_sports(text)
    if named and any(_ASSUMED_SPORTS_NOTE in a for a in assumed):
        for rule in draft.get("rules") or []:
            rule["sports"] = list(named)
        assumed = [a for a in assumed if _ASSUMED_SPORTS_NOTE not in a]
        assumed.append(f"{_sport_phrase(named)} named, so the rule covers {_sport_phrase(named)}")
        not_understood = [n for n in not_understood if not _SPORT_WORDS.search(str(n.get("text") or ""))]
    spec, problems = None, []
    if draft.get("rules"):
        try:
            spec = user_spec.validate_spec({**draft, "name": "Draft Dog"})
            spec["name"] = ""
        except user_spec.SpecError as exc:
            problems = [f"{field}: {msg}" for field, msg in exc.errors.items() if field != "name"]
    sentences = render.rule_sentences(spec) + render.global_sentences(spec) if spec else []
    return {
        "draft": draft,
        "understood": list(parsed.get("understood") or []),
        "not_understood": not_understood,
        "assumed": list(dict.fromkeys(assumed)),
        "problems": problems,
        "sentences": sentences,
        "named_sports": named,
        "questions": questions(draft, named, text=text or "", levels=levels),
    }
