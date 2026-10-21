"""Phrases the hound language cannot run yet, found by rule and listed, never dropped.

WHY A TABLE AND NOT THE MODEL
-----------------------------
"Can't automate yet" is a promise that nothing the person asked for vanishes. If only a model decided what is
unsupported, a model that missed one would drop it silently. So every free-text slot is also scanned here, in
every mode, and each hit becomes an entry with a plain reason. The model's own `unsupported` list is merged in
afterwards; this table is the floor.

TWO FAMILIES
------------
  * after-the-start ideas (live bets, in-game triggers, innings, halves): a hound locks 60 to 180 minutes
    before the start and may only use what was known by then (src/hounds/user_rules.py, "POINT IN TIME").
    This is the "only pre-lock conditions" rule, enforced at the language level.
  * facts and moves the rules do not have (injuries, lineups, public splits, parlays, a named book ...).

A phrase that follows a negation within a few words ("I never bet live") is not a request for it. Facts are the
exception: "avoid injured starters" still DEPENDS on injury data, so a negation does not clear a NO_DATA phrase.
"""

from __future__ import annotations

import re
from typing import List

AFTER_START = "after_start"
NO_DATA = "no_data"
NO_MARKET = "no_market"
NO_MOVE = "no_move"

# (code, kind, regex, plain reason)
_TABLE = (
    ("live", AFTER_START,
     r"\b(?:live|in[- ]play|in[- ]game|during the game|mid[- ]game|half[- ]?time|late in the game|"
     r"after (?:the )?(?:first|second|third|fourth|fifth|sixth|seventh|\d+(?:st|nd|rd|th)) "
     r"(?:inning|quarter|period|half)|(?:top|bottom) of the \d+(?:st|nd|rd|th)|"
     r"(?:\d+(?:st|nd|rd|th)) (?:inning|quarter|period))\b",
     "Live and in-game bets are not available. A hound locks 60 to 180 minutes before the start and uses only "
     "what was known by then."),
    ("after_start_fact", AFTER_START,
     r"\b(?:final score|box score|after (?:the )?(?:game|first pitch|kickoff|tip[- ]?off) (?:starts|started|begins)|"
     r"once the game starts|when the game starts|team (?:is )?(?:down|up|trailing|leading) by)\b",
     "That is only known after the game starts. Hounds use only what was known at their lock."),
    ("first_five", NO_MARKET, r"\b(?:f5|first (?:5|five) innings?|first half|1st half|first quarter|1st quarter)\b",
     "First-five-innings, half and quarter markets are not on the menu. Hounds bet full-game moneylines, spreads, "
     "totals and MLB player props."),
    ("parlay", NO_MARKET, r"\b(?:parlays?|teasers?|round[- ]robins?|sgp|same[- ]game|futures?|alt(?:ernate)? lines?)\b",
     "Parlays, teasers, futures and alternate lines are not on the menu. A hound makes single paper bets."),
    ("opening_line", NO_MOVE,
     r"\b(?:opening (?:line|price|odds)|open(?:er)? (?:line|price)|bet(?:ting|s)? (?:at |into |on )?the clos(?:e|ing))\b",
     "A hound is priced at its lock time, as the average across books. It cannot take the opening or the closing line."),
    ("named_book", NO_MOVE,
     r"\b(?:draftkings|fanduel|betmgm|caesars|bet365|pinnacle|espn bet|bovada|betrivers|fanatics|hard rock|prizepicks)\b",
     "A hound is priced at the average across all the books quoting it. It cannot be tied to one book."),
    ("line_shop", NO_MOVE, r"\b(?:line[- ]?shop\w*|best (?:available )?(?:line|price|odds)|shop(?:ping)? (?:for )?(?:the )?(?:best|lines?))\b",
     "Hounds are graded at the average price, not the best price anywhere."),
    ("injuries", NO_DATA, r"\b(?:injur(?:y|ies|ed)|questionable|doubtful|game[- ]time decision|inactives?|scratched|day[- ]to[- ]day)\b",
     "Injuries are not available to the rules yet."),
    ("starters", NO_DATA,
     r"\b(?:lineups?|starting (?:pitcher|lineup|goalie|quarterback|qb|five)s?|starters?|probable pitchers?|bullpens?|"
     r"goalies?|pitching matchups?|era|whip|fip)\b",
     "Starting pitchers, goalies, quarterbacks, lineups and bullpens are not available to the rules yet."),
    ("public_money", NO_DATA,
     r"\b(?:public (?:betting|money|bets|percent\w*|splits?|side)|ticket (?:count|percent\w*|counts)|bets? ?%|money ?%|"
     r"money splits?|fade the public|contrarian|reverse line movement|sharp(?:s| money| action| side)?)\b",
     "Public betting percentages, money splits and sharp-money signals are not available to the rules."),
    ("milestones", NO_DATA, r"\b(?:milestones?|career (?:high|first|game)|retirement|anniversar\w+|rivalry week|revenge)\b",
     "Milestones, anniversaries and storylines are not facts the rules can read."),
    ("stake_methods", NO_MOVE,
     r"\b(?:kelly|martingale|chas(?:e|ing) (?:losses|the loss)|double (?:up|down)|doubling|drawdown|stop[- ]loss|"
     r"max(?:imum)? exposure|exposure limit|bankroll (?:percent|%)|% of (?:my )?bankroll|unit sizing|daily (?:loss|limit)|"
     r"loss limit|\d+(?:\.\d+)? units? (?:a|per) (?:day|week))\b",
     "Stake sizing beyond one flat paper stake (Kelly, doubling, drawdown stops, exposure limits) is not on the menu."),
    ("edge_value", NO_MOVE, r"\b(?:min(?:imum)? edge|expected value|\+ev|value bets?|positive ev)\b",
     "A hound has no value or expected-return calculation. Describe the bet with a price range and conditions."),
    ("hedge_cancel", NO_MOVE, r"\b(?:hedg\w+|cash[- ]?out|cancel\w*|middle[sd]?|void\w*)\b",
     "Hedging, cashing out and cancelling are not available. A locked paper bet stays as it was locked."),
)

_NEGATION = re.compile(r"\b(?:never|not|don'?t|doesn'?t|won'?t|without|avoid\w*|skip\w*|ignore|no(?!\s+(?:more|less|fewer)))"
                       r"\s+(?:[\w'-]+\s+){0,2}$", re.I)
_COMPILED = [(code, kind, re.compile(rx, re.I), reason) for code, kind, rx, reason in _TABLE]


def find_unsupported(text: str, *, topic: str = "") -> List[dict]:
    """[{code, kind, text, reason, topic}], one entry per idea; `text` joins every phrase that named it. A phrase the
    person has just ruled out ("never live") is not an entry."""
    out: List[dict] = []
    body = str(text or "")
    for code, kind, rx, reason in _COMPILED:
        phrases: List[str] = []
        for m in rx.finditer(body):
            before = re.split(r"[.;,\n]", body[max(0, m.start() - 40):m.start()])[-1]
            if kind != NO_DATA and _NEGATION.search(before):
                continue
            phrase = m.group(0).strip()
            if phrase.lower() not in [p.lower() for p in phrases]:
                phrases.append(phrase)
        if phrases:
            out.append({"code": code, "kind": kind, "text": "; ".join(phrases[:3]), "reason": reason, "topic": topic})
    return out
