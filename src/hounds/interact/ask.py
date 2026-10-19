"""Ask your dog: a question in, an answer BUILT FROM THE DOG'S OWN DATA out. No model is called.

HOW IT WORKS. ``classify`` reads the question with plain word and phrase rules and names one INTENT (why did you
bet X, what did you bet today, how are you doing, best and worst bet, what would you bet now, why didn't you bet
that game, what are your rules, how do I make you better, what do fans think, what did the coach say). A
builder per intent then writes the answer from facts the page already shows: the dog's tickets and their
reasons, its rule (in plain English when the builder's renderer exists, else the rule text), its record and
form, the fan feedback counts, the graded tips, and, for "right now", the same read-only preview the Fire now
button runs. A question the rules do not recognise gets an honest fallback that lists what the dog CAN answer.

VOICE. First person, short, plain. The dog's name and its one-line catchphrase (a house dog's catchphrase, a
builder's tagline) open the intro and the record answer, nowhere else. No exclamation marks, no claim of an
edge, nothing that sounds like a promise: a record is stated with its sample size, and a small sample is called
small. Every number in an answer is one the page already shows (a test holds that), and every answer can be
rated Good call or Bad call by a signed-in visitor (``store``).

Paper only. Nothing here suggests a real bet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.hounds import stats

INTENTS = ("hello", "record", "today", "why_bet", "best_worst", "bet_now", "why_not", "rules", "improve",
           "fans", "coach")
FALLBACK = "fallback"
ANSWER_KINDS = INTENTS + (FALLBACK,)

SMALL_SAMPLE = 100          # the site's own line: under this many graded bets, say "small sample"
TEAM_MIN_LEN = 4


@dataclass
class AskContext:
    dog_id: str
    name: str
    kind: str = "house"                      # user | house | other
    catchphrase: str = ""
    rule_text: str = ""
    rule_english: str = ""
    trigger: str = ""                        # a house dog's one-line "bets when ..."
    spec: Optional[dict] = None
    summary: Optional[dict] = None           # the contract HoundSummary as JSON
    tickets: list = field(default_factory=list)   # forward tickets, newest first (BetRow JSON)
    manual: list = field(default_factory=list)    # manual ticket views (owner's, kept apart)
    feedback: dict = field(default_factory=dict)  # store.counts(...)
    tips: list = field(default_factory=list)      # graded tips on this dog: [{line, label, kind}]
    is_owner: bool = False
    status: str = "running"
    today: str = ""                          # Eastern date, YYYY-MM-DD
    warming: bool = False
    fire_fn: Optional[Callable[[], dict]] = None


# ---------------------------------------------------------------------------
# reading the question
# ---------------------------------------------------------------------------

_FILLER = re.compile(r"[^a-z0-9+\- ]+")


def norm(question: str) -> str:
    text = str(question or "").lower().replace("’", "").replace("'", "")
    text = _FILLER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has(text: str, *needles: str) -> bool:
    return any(n in text for n in needles)


def _rx(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


BET_WORDS = r"(bet|bets|betting|pick|picks|take|took|back|backed|play|played|choose|chose|ticket|tickets|like)"
PAST_MARKERS = r"\b(did you|have you|had you|placed|made|yesterday|last night|latest|last bet|last pick|most recent|recent|open bets|pending|so far|already|this week|lately)\b"
FUTURE_MARKERS = r"\b(would you|will you|should you|right now|currently|at the moment|fire|any picks|anything|whats your pick|whats your play|what do you like|what are you thinking|thinking|what do you see|what do you want)\b"


def classify(question: str) -> str:
    """The intent a question asks for, or ``fallback``."""
    t = norm(question)
    if not t:
        return FALLBACK
    asks_why = _rx(t, r"(^|\b)why\b") or _rx(t, r"\b(how come|what made you|whats the reason|reason for|explain (?:that|this|your|the) (?:bet|pick|ticket|play))\b")
    negation = _rx(t, r"\b(didnt|dont|wont|wouldnt|havent|cant|not|no bet|skip|skipped|pass|passed|ignore|ignored|avoid|avoided|miss|missed|sit out|sat out|leave out|left out)\b")
    # 1. why did you NOT bet something
    if (asks_why and negation) or _rx(t, r"\bdidnt you (bet|take|pick|back|play)\b") or _rx(t, r"\bwhy no (bet|pick)\b"):
        return "why_not"
    # 2. best / worst
    if _rx(t, r"\b(best|worst|biggest|top|greatest|baddest)\b") and _rx(t, r"\b(bet|bets|pick|picks|win|wins|loss|losses|beat|call|ticket|play|winner|loser)\b"):
        return "best_worst"
    if _rx(t, r"\bworst beat\b"):
        return "best_worst"
    # 3. why did you bet X
    if asks_why and (_rx(t, BET_WORDS) or _rx(t, r"\b(go with|went with|favou?r|side|team|that one|this one)\b")):
        return "why_bet"
    if _rx(t, r"\bexplain (that|this|your|the) (bet|pick|ticket|play)\b"):
        return "why_bet"
    # 4. what would you bet now, against what did you bet
    past = _rx(t, PAST_MARKERS)
    future = _rx(t, FUTURE_MARKERS) or _rx(t, r"\bfire\b")
    if future and not past and (_rx(t, BET_WORDS) or _rx(t, r"\b(now|tonight|today|fire|slate|games|anything|picks)\b")):
        return "bet_now"
    if _rx(t, r"\b(whats|what is) your (pick|play|take|lean)\b") or _rx(t, r"\bwhat do you like (tonight|today)\b"):
        return "bet_now"
    if past and _rx(t, BET_WORDS + r"|\b(wager|wagers|action)\b"):
        return "today"
    if _rx(t, r"\b(bets|picks|tickets|plays)\b") and _rx(t, r"\b(today|tonight|yesterday|open|pending|latest|recent|last)\b"):
        return "today"
    if _rx(t, r"\bwhat (are|r) you (betting|backing|taking|playing)\b") or _rx(t, r"\bwhat did you (bet|pick|take|back|play)\b"):
        return "today"
    # 5. how to make it better
    if _rx(t, r"\b(make you better|improve|get better|train you|teach you|tweak|tune you|change your|suggest|coach you|upgrade|fix you|how do i help)\b"):
        return "improve"
    # 6. the rule
    if _rx(t, r"\b(rule|rules|strategy|system|logic|method|criteria|how do you (pick|choose|decide|work|bet|select)|what do you bet on|explain yourself|how do you do it|your approach)\b"):
        return "rules"
    # 7. fans and the coach
    if _rx(t, r"\b(fans|people think|feedback|reviews?|ratings?|what do people|good call|bad call)\b"):
        return "fans"
    if _rx(t, r"\b(coach|tips|tipped|tip box)\b"):
        return "coach"
    # 8. the record
    if _rx(t, r"\b(how are you|hows it going|how is it going|how you doing|record|units|roi|clv|closing line|winning|losing|perform|performance|streak|how many (bets|wins|losses)|any good|results|form|standing|rank|verdict|status)\b"):
        return "record"
    # 9. who are you
    if _rx(t, r"\b(who are you|hello|hi|hey|your name|who made you|who built you|introduce|about you|about yourself|what are you|yo|sup)\b"):
        return "hello"
    return FALLBACK


# ---------------------------------------------------------------------------
# small formatting helpers
# ---------------------------------------------------------------------------

def _price(p) -> str:
    if p is None or isinstance(p, bool) or not isinstance(p, (int, float)):
        return "n/a"
    p = int(round(p))
    return f"+{p}" if p > 0 else str(p)


def _units(u) -> str:
    if not isinstance(u, (int, float)) or isinstance(u, bool):
        return "n/a"
    return f"{u:+.2f}u"


def _when(stamp) -> str:
    text = str(stamp or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", text)
    if not m:
        return text[:10]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[int(m.group(2)) - 1]} {int(m.group(3))} at {m.group(4)}:{m.group(5)} UTC"


def _day(stamp) -> str:
    text = str(stamp or "")[:10]
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return text
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[int(m.group(2)) - 1]} {int(m.group(3))}"


def _parse(stamp) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def ticket_key(t: dict) -> str:
    """The id feedback uses for a ticket: its slate date and its pick."""
    return f"{str(t.get('date') or '')[:10]}|{t.get('selection') or ''}"


def avg_units(t: dict) -> Optional[float]:
    """Units at the average price (the headline price), from the result and that price."""
    result = t.get("result")
    if result in ("push", "void"):
        return 0.0
    if result in ("win", "loss"):
        value = stats.settle_units(result, t.get("price_average") if t.get("price_average") is not None else t.get("price"))
        return value if value is not None else t.get("units")
    return None


_NOT_ADVICE_TAIL = re.compile(r"\s*Paper only\. These are simulated picks.*$", re.S)


def plain_rule(text: str) -> str:
    """A rule as the dog says it: the boilerplate not-advice tail dropped (the page carries it once) and the word
    the site does not use for a placing time swapped for the plain words."""
    out = _NOT_ADVICE_TAIL.sub("", str(text or "")).strip()
    out = re.sub(r"\blocks\b", "placing times", out, flags=re.I)
    return re.sub(r"\block\b", "placing time", out, flags=re.I)


def _result_phrase(t: dict) -> str:
    result = t.get("result")
    if result == "win":
        return f"it won ({_units(avg_units(t))})"
    if result == "loss":
        return f"it lost ({_units(avg_units(t))})"
    if result == "push":
        return "it pushed (0.00u)"
    if result == "void":
        return "it was voided"
    status = str(t.get("status") or "").upper()
    return "it is ungraded, well past its start" if status == "UNGRADED" else "it is still open"


def _game_of(t: dict) -> str:
    return (t.get("game") or "").strip()


def _ticket_line(t: dict) -> str:
    game = _game_of(t)
    where = f" ({game})" if game else ""
    best = ""
    if t.get("price") is not None and t.get("price") != t.get("price_average") and t.get("book"):
        best = f", best {_price(t.get('price'))} at {t.get('book')}"
    price = t.get("price_average") if t.get("price_average") is not None else t.get("price")
    return f"{t.get('selection') or 'a pick'}{where} at {_price(price)}{best}; {_result_phrase(t)}"


def _ref(t: dict) -> dict:
    return {"key": ticket_key(t), "date": str(t.get("date") or "")[:10], "selection": t.get("selection"),
            "game": _game_of(t), "price": t.get("price_average") if t.get("price_average") is not None else t.get("price"),
            "result": t.get("result"), "status": t.get("status")}


def _sample(n: int) -> str:
    if n <= 0:
        return "no graded bets yet"
    word = "bet" if n == 1 else "bets"
    return f"{n} graded {word}" + (", a small sample" if n < SMALL_SAMPLE else "")


# ---------------------------------------------------------------------------
# team names found in a question
# ---------------------------------------------------------------------------

def _team_names(ctx: AskContext, fire: Optional[dict]) -> list:
    """Every team the dog has a ticket on, or can see on the boards, as (display name, keywords)."""
    names = set()
    for t in ctx.tickets + ctx.manual:
        game = _game_of(t)
        for part in re.split(r"\s+(?:@|at|vs\.?|v)\s+", game):
            if part.strip():
                names.add(part.strip())
        sel = re.sub(r"\s+(to win|ML|moneyline|[+-]\d+(\.\d+)?)(\s+run line)?$", "", str(t.get("selection") or ""), flags=re.I).strip()
        if sel and not re.match(r"^(over|under)\b", sel, flags=re.I):
            names.add(sel)
    if fire:
        for g in fire.get("games", []):
            for part in re.split(r"\s+@\s+", g.get("game") or ""):
                if part.strip():
                    names.add(part.strip())
    out = []
    for name in sorted(names):
        words = [w for w in norm(name).split() if len(w) >= TEAM_MIN_LEN or w in ("sox", "jays", "reds")]
        if words:
            out.append((name, [norm(name)] + words[-1:] + words[:1]))
    return out


def find_team(question: str, ctx: AskContext, fire: Optional[dict] = None) -> Optional[str]:
    t = " " + norm(question) + " "
    best, best_len = None, 0
    for name, keys in _team_names(ctx, fire):
        for key in keys:
            if key and f" {key} " in t and len(key) > best_len:
                best, best_len = name, len(key)
    return best


def _tickets_for(ctx: AskContext, team: str) -> list:
    needle = norm(team)
    return [t for t in ctx.tickets + ctx.manual if needle in norm(_game_of(t)) or needle in norm(str(t.get("selection") or ""))]


# ---------------------------------------------------------------------------
# the answers
# ---------------------------------------------------------------------------

def _timing(t: dict) -> str:
    rec, start = _parse(t.get("recorded_utc")), _parse(t.get("start_utc"))
    if rec is None:
        return ""
    if start is None:
        return f"I recorded it {_when(t.get('recorded_utc'))}."
    minutes = int(round((start - rec).total_seconds() / 60.0))
    if minutes <= 0:
        return f"I recorded it {_when(t.get('recorded_utc'))}."
    span = f"{minutes} minutes" if minutes < 120 else f"{minutes // 60} hours"
    return f"I recorded it {_when(t.get('recorded_utc'))}, {span} before the start."


def explain_ticket(ctx: AskContext, t: dict) -> list:
    """Why a dog took one ticket, as short first-person lines. The reason line is the ticket's own, quoted."""
    lines = []
    game = _game_of(t)
    lines.append(f"I took {t.get('selection') or 'that pick'}" + (f" in {game}" if game else "")
                 + f" at {_price(t.get('price_average') if t.get('price_average') is not None else t.get('price'))}"
                 + (f" ({t.get('book_count')} books were quoting it)" if t.get("book_count") else "") + ".")
    if ctx.kind == "user" and ctx.rule_english:
        lines.append(f"My rule: {plain_rule(ctx.rule_english)}")
    elif ctx.trigger:
        lines.append(f"I bet when {ctx.trigger}.")
    elif ctx.rule_text:
        lines.append(f"My rule: {plain_rule(ctx.rule_text)}")
    if t.get("reason"):
        lines.append(f"The reason on the ticket: {t['reason']}")
    timing = _timing(t)
    if timing:
        lines.append(timing)
    lines.append(f"Result: {_result_phrase(t)}.")
    return lines


def _no_tickets(ctx: AskContext, what: str) -> str:
    return f"I have not recorded a ticket yet, so there is nothing to say about {what}."


def _intro(ctx: AskContext) -> dict:
    s = ctx.summary or {}
    sports = ", ".join(s.get("sports") or []) or "my sports"
    rule = plain_rule(ctx.rule_english or ctx.rule_text)
    lines = [f"I am {ctx.name}." + (f" {ctx.catchphrase}" if ctx.catchphrase else "")]
    if rule:
        lines.append(f"What I do: {rule}")
    lines.append(f"I make paper bets only, in {sports}, and every one is recorded before the game and graded after.")
    lines.append("Ask me about my bets, my record, my rules, or what I would take right now.")
    return {"lines": lines}


def _record(ctx: AskContext) -> dict:
    s = ctx.summary
    if s is None:
        return {"lines": ["My numbers are still loading. Try me again in a minute."]}
    rec = s.get("record") or {}
    n = rec.get("bets") or 0
    lines = []
    if n <= 0:
        open_n = s.get("open_bets") or 0
        lines.append(f"I have no graded bets yet" + (f", and {open_n} open {'ticket' if open_n == 1 else 'tickets'}." if open_n else "."))
        lines.append("A record needs graded games, so there is nothing to judge yet.")
    else:
        w, l, p = rec.get("wins") or 0, rec.get("losses") or 0, rec.get("pushes") or 0
        wl = f"{w}-{l}" + (f"-{p}" if p else "")
        avg = rec.get("units_average_price")
        units = avg if isinstance(avg, (int, float)) else rec.get("units_recorded_price")
        basis = "at the average price" if isinstance(avg, (int, float)) else "at the recorded price"
        lines.append(f"{_sample(n).capitalize()}: {wl}, {_units(units)} {basis}.")
        form = s.get("form") or {}
        streak = form.get("streak")
        if streak and streak.get("length", 0) >= 2:
            lines.append(f"I am on a {streak['length']}-{'win' if streak['kind'] == 'W' else 'loss'} run.")
        last7 = form.get("last7")
        if last7 and last7.get("bets"):
            lines.append(f"Last 7 days: {last7['wins']}-{last7['losses']} over {last7['bets']} bets, {_units(last7.get('units'))}.")
    clv = s.get("clv")
    if clv and clv.get("n"):
        mean = clv.get("mean_pts")
        lines.append(f"Against the closing line I average {mean:+.1f} points over {clv['n']} measurable bets." if isinstance(mean, (int, float))
                     else f"{clv['n']} of my bets have a measurable closing price.")
    verdict = s.get("verdict") or {}
    if verdict.get("sentence"):
        lines.append(f"The referee's read: {verdict['sentence']}")
    elif verdict.get("label"):
        lines.append(f"The referee's label for me is {verdict['label']}.")
    if ctx.catchphrase:
        lines.append(ctx.catchphrase)
    return {"lines": lines}


def _today(ctx: AskContext, question: str) -> dict:
    t = norm(question)
    if not ctx.tickets:
        return {"lines": [_no_tickets(ctx, "my bets")]}
    day = ctx.today or str(ctx.tickets[0].get("date") or "")[:10]
    if "yesterday" in t or "last night" in t:
        try:
            day = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
        except ValueError:
            pass
        wanted = [x for x in ctx.tickets if str(x.get("date") or "")[:10] == day]
        label = "yesterday"
    elif _rx(t, r"\b(lately|recent|recently|this week|latest|last)\b") or "today" not in t and "tonight" not in t and "open" not in t and "pending" not in t:
        wanted = ctx.tickets[: 3 if _rx(t, r"\b(last|latest|most recent)\b") and not _rx(t, r"\bbets\b") else 5]
        label = "lately"
    elif "open" in t or "pending" in t:
        wanted = [x for x in ctx.tickets if str(x.get("status") or "").upper() == "OPEN" or x.get("result") is None]
        label = "open right now"
    else:
        wanted = [x for x in ctx.tickets if str(x.get("date") or "")[:10] == day]
        label = "today"
    if not wanted:
        last = ctx.tickets[0]
        return {"lines": [f"I have no tickets {label}.", f"My last one was on {_day(last.get('date'))}: {_ticket_line(last)}."],
                "tickets": [_ref(last)]}
    lines = [f"Here {'is my ticket' if len(wanted) == 1 else 'are my tickets'} {label}:"]
    lines += [f"{_ticket_line(x)}." for x in wanted]
    lines.append("Ask me why on any of them.")
    return {"lines": lines, "tickets": [_ref(x) for x in wanted]}


def _why_bet(ctx: AskContext, question: str) -> dict:
    if not ctx.tickets and not ctx.manual:
        return {"lines": [_no_tickets(ctx, "why I bet")]}
    team = find_team(question, ctx, None)
    found = _tickets_for(ctx, team) if team else []
    if found:
        t = found[0]
        return {"lines": explain_ticket(ctx, t), "tickets": [_ref(t)]}
    pool = ctx.tickets or ctx.manual
    open_first = [x for x in pool if x.get("result") is None]
    t = (open_first or pool)[0]
    lines = ["Taking my most recent ticket:"] + explain_ticket(ctx, t)
    return {"lines": lines, "tickets": [_ref(t)]}


def _best_worst(ctx: AskContext, question: str) -> dict:
    form = (ctx.summary or {}).get("form") or {}
    best, worst = form.get("best_bet"), form.get("worst_beat")
    t = norm(question)
    want_best = not _rx(t, r"\bworst\b|\bloss|\bbeat\b|\bloser\b") or _rx(t, r"\bbest\b")
    want_worst = _rx(t, r"\bworst\b|\bloss|\bbeat\b|\bloser\b") or not _rx(t, r"\bbest\b|\bwin")
    lines, refs = [], []
    if not best and not worst:
        return {"lines": ["I have no graded bets yet, so I have no best or worst to show."]}
    if want_best and best:
        lines.append(f"My best bet: {best['selection']} on {_day(best['date'])} ({best['game']}) at {_price(best['price'])}, {_units(best['units'])}."
                     if best.get("game") else f"My best bet: {best['selection']} on {_day(best['date'])} at {_price(best['price'])}, {_units(best['units'])}.")
    if want_worst and worst:
        lines.append(f"My worst beat is the loss the market thought most likely to win: {worst['selection']} on {_day(worst['date'])} at {_price(worst['price'])}, {_units(worst['units'])}.")
    if want_best and not best:
        lines.append("I have not won a graded bet yet.")
    if want_worst and not worst:
        lines.append("I have not lost a graded bet yet.")
    n = ((ctx.summary or {}).get("record") or {}).get("bets") or 0
    lines.append(f"That is out of {_sample(n)}.")
    return {"lines": lines, "tickets": refs}


def _fire_lines(ctx: AskContext, fire: dict) -> list:
    picks = fire.get("picks") or []
    lines = []
    if picks:
        lines.append("On the boards stored right now I would take:")
        for p in picks[:3]:
            best = f", best {_price(p['price_best'])} at {p['best_book']}" if p.get("price_best") is not None and p["price_best"] != p["price_average"] else ""
            lines.append(f"{p['selection']} ({p['game']}) at {_price(p['price_average'])}{best}. {p['reason']}")
        if len(picks) > 3:
            lines.append(f"Plus {len(picks) - 3} more on the Fire now panel.")
        if any(p.get("before_lock") for p in picks):
            lines.append("My real ticket is written at my usual time before the start, on the board then, so it can differ.")
    else:
        lines.append("Nothing qualifies right now.")
        misses = fire.get("closest_misses") or []
        for m in misses[:2]:
            lines.append(f"Closest: {m['game']}. {m['why']}")
        if not misses and fire.get("headline"):
            lines.append(fire["headline"])
    return lines


def _bet_now(ctx: AskContext, fire: Optional[dict]) -> dict:
    if fire is None:
        return {"lines": ["I cannot read the boards just now. Try the Fire now button in a minute."]}
    if fire.get("error"):
        return {"lines": [fire["error"]]}
    return {"lines": _fire_lines(ctx, fire), "fire": True}


def _why_not(ctx: AskContext, question: str, fire: Optional[dict]) -> dict:
    team = find_team(question, ctx, fire)
    if team is None:
        return {"lines": ["Tell me which game or team and I will tell you what my rule saw. For example: why did you not bet the Mariners."]}
    had = _tickets_for(ctx, team)
    if had:
        t = had[0]
        return {"lines": ["I did bet that game, so there was nothing to skip."] + explain_ticket(ctx, t), "tickets": [_ref(t)]}
    needle = norm(team)
    if fire and not fire.get("error"):
        for g in fire.get("games", []):
            if needle in norm(g.get("game") or ""):
                lines = [f"{g['game']} is still ahead of me."]
                for m in g["markets"]:
                    label = m["market"].replace("moneyline", "moneyline").replace("spread", "spread").replace("total", "total") if m.get("market") else "the game"
                    if m["status"] == "pick":
                        lines.append(f"On {label} my rule does take {m['selection']} at {_price(m['price_average'])}, so a ticket is coming at my usual time.")
                    elif m["status"] == "recorded":
                        lines.append(f"On {label} I already have a ticket: {m['selection']} at {_price(m['price_average'])}.")
                    else:
                        lines.append(f"On {label} I pass. {m['why']}")
                return {"lines": lines}
    return {"lines": [f"I cannot see {team} among the games still ahead of me on the stored boards, and I have no ticket on it.",
                      "I only keep the reason for games that have not started. To see what my rule does over past days, run a drill in the Training camp. It replays my rule on old boards and is never counted."]}


def _rules(ctx: AskContext) -> dict:
    lines = []
    rule = plain_rule(ctx.rule_english or ctx.rule_text)
    if rule:
        lines.append(f"My rule: {rule}")
    if ctx.kind == "house" and ctx.trigger:
        lines.append(f"In short, I bet when {ctx.trigger}.")
    if ctx.spec:
        lines.append(f"I place a pick {ctx.spec['lock_minutes']} minutes before the start, take at most {ctx.spec['max_bets_per_day']} a day, "
                     f"and need at least {ctx.spec['min_books']} books quoting.")
    lines.append("The cap is always on: I never take a price of -200 or worse.")
    lines.append("I do not change my own rule. A new version is a new dog with its own record.")
    return {"lines": lines}


def _improve(ctx: AskContext) -> dict:
    lines = []
    if ctx.kind == "user" and ctx.is_owner:
        lines += ["You are my owner, so you can change my rule: open the builder from my page, change one thing, and it becomes a new version with its own record.",
                  "Before you do, run a drill in the Training camp. It replays my rule over the last 7, 14 or 30 days so you can see what a change would have done. It is never counted.",
                  "Rate my tickets Good call or Bad call. I keep the notes where you can read them."]
    elif ctx.kind == "user":
        lines += ["Rate my tickets Good call or Bad call, and use Suggest a change to send my owner an idea. It reaches them as a suggestion and changes nothing on its own."]
    else:
        lines += ["Rate my tickets Good call or Bad call.",
                  "If I have dials, the Coach this model panel on my page lets you send a tip. Every tip is graded by code against the same games, and only the referee can change me."]
    lines.append("Nothing anyone sends changes me by itself. A change has to earn its place on the numbers.")
    return {"lines": lines}


def _fans(ctx: AskContext) -> dict:
    fb = ctx.feedback or {}
    good, bad = fb.get("good", 0), fb.get("bad", 0)
    if not good and not bad:
        return {"lines": ["Nobody has rated my tickets yet. A Good call or Bad call under any ticket counts."]}
    total = good + bad
    lines = [f"{total} {'rating' if total == 1 else 'ratings'} so far: {good} Good call, {bad} Bad call."]
    if total < 10:
        lines.append("That is a small sample, so read it lightly.")
    if fb.get("notes"):
        lines.append(f"{fb['notes']} {'note was' if fb['notes'] == 1 else 'notes were'} left with them.")
    return {"lines": lines}


def _coach(ctx: AskContext) -> dict:
    tips = ctx.tips or []
    if not tips:
        return {"lines": ["No graded tip has been sent about me yet. Tips on a dog with dials show up here once code has graded them."]}
    lines = [f"{len(tips)} graded {'tip' if len(tips) == 1 else 'tips'} about me:"]
    for tip in tips[:3]:
        lines.append(f"{tip.get('label') or 'Not graded'}: {tip.get('line')}")
    lines.append("Tips never change me. Only the referee does.")
    return {"lines": lines}


def _fallback(ctx: AskContext) -> dict:
    return {"lines": ["I did not catch that. Here is what I can answer:",
                      "Why I made a bet, what I bet today, how I am doing, my best and worst bet, what I would bet right now, "
                      "why I skipped a game, my rules, and how to make me better."]}


def suggestions(ctx: AskContext) -> list:
    """Questions worth asking this dog right now, in the order a person reads them."""
    out = ["What did you bet today?"]
    if ctx.tickets:
        t = ctx.tickets[0]
        team = None
        game = _game_of(t)
        sel = str(t.get("selection") or "")
        if sel and not re.match(r"^(over|under)\b", sel, flags=re.I):
            team = re.sub(r"\s+(to win|ML|moneyline).*$", "", re.sub(r"\s+[+-]\d.*$", "", sel), flags=re.I).strip()
        if team:
            out.append(f"Why did you bet the {team.split()[-1]}?")
        elif game:
            out.append("Why did you make your last bet?")
    out += ["How are you doing?", "What is your best and worst bet?", "What would you bet right now?",
            "What are your rules?", "How do I make you better?"]
    return out[:7]


# ---------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------

def _get_fire(ctx: AskContext) -> dict:
    """The read-only preview, or an ``{"error": sentence}`` the answer can say out loud."""
    if ctx.fire_fn is None:
        return {"error": "I cannot fire from here: only the house dogs and the dogs people built run a rule on demand."}
    try:
        return ctx.fire_fn()
    except Exception as exc:  # noqa: BLE001 -- a board that cannot be read is said, not hidden
        return {"error": str(exc) if getattr(exc, "public", False) else "I cannot read the boards just now."}


def answer(question: str, ctx: AskContext) -> dict:
    """``{intent, answer, lines, tickets, followups, matched, question}``. Never raises on an odd question."""
    q = str(question or "").strip()[:300]
    intent = classify(q)
    if intent == "why_bet":
        team = find_team(q, ctx, None)
        if team and not _tickets_for(ctx, team):
            intent = "why_not"                     # a team the dog never bet: that is a question about a skip
    fire = _get_fire(ctx) if intent in ("bet_now", "why_not") else None
    if intent == "hello":
        body = _intro(ctx)
    elif intent == "record":
        body = _record(ctx)
    elif intent == "today":
        body = _today(ctx, q)
    elif intent == "why_bet":
        body = _why_bet(ctx, q)
    elif intent == "best_worst":
        body = _best_worst(ctx, q)
    elif intent == "bet_now":
        body = _bet_now(ctx, fire)
    elif intent == "why_not":
        body = _why_not(ctx, q, fire)
    elif intent == "rules":
        body = _rules(ctx)
    elif intent == "improve":
        body = _improve(ctx)
    elif intent == "fans":
        body = _fans(ctx)
    elif intent == "coach":
        body = _coach(ctx)
    else:
        intent = FALLBACK
        body = _fallback(ctx)
    lines = body["lines"]
    followups = [s for s in suggestions(ctx) if norm(s) != norm(q)][:4]
    return {"intent": intent, "question": q, "answer": " ".join(lines), "lines": lines,
            "tickets": body.get("tickets", []), "followups": followups, "matched": intent != FALLBACK,
            "dog_id": ctx.dog_id, "dog_name": ctx.name, "paper_only": True}
