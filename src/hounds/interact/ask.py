"""Ask your dog: a question in, an answer BUILT FROM THE DOG'S OWN DATA out. No model is called.

HOW IT WORKS. ``classify`` reads the question with plain word and phrase rules and names one INTENT (why did you
bet X, what did you bet today, how are you doing, best and worst bet, what would you bet now, why didn't you bet
that game, what are your rules, how do I make you better, what do fans think, what did the coach say). A
builder per intent then writes the answer from facts the page already shows: the dog's tickets and their
reasons, its rule (in plain English when the builder's renderer exists, else the rule text), its record and
form, the fan feedback counts, the graded tips, and, for "right now", the same read-only preview the "Unleash"
button runs. A question the rules do not recognise gets an honest fallback that lists what the dog CAN answer.

VOICE. First person, short, plain. The dog's name and its one-line catchphrase (a house dog's catchphrase, a
builder's tagline) open the intro and the record answer, nowhere else. No exclamation marks, no claim of an
edge, nothing that sounds like a promise: a record is stated with its sample size, and a small sample is called
small. Every number in an answer is one the page already shows (a test holds that), and every answer can be
rated Good call or Bad call by a signed-in visitor (``store``).

RETUNE. When the owner tells a member hound its rule is too tight or too loose ("I don't like that you won't take a single bet"),
the intent is ``retune`` (``retune.detect``): the hound answers with what its rule did on today's board, from real counts
(``AskContext.retune_fn``, given to the OWNER of a member hound and to no one else), and the answer carries ``retune`` so the owner's page
can show a "Retune me" button. The button starts the proposal and review in ``training``; this module changes nothing.

Paper only. Nothing here suggests a real bet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from src.hounds import stats
from src.hounds.interact import ask_intents, ask_voice, fire, retune

INTENTS = ("hello", "record", "today", "why_bet", "best_worst", "picks_now", "picks_earlier_today",
           "backtest_window", "why_not", "rules", "improve", "explain_market", "fans", "coach", "help", "retune")
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
    fire_fn: Optional[Callable[[], dict]] = None            # the Fire now payload (the boards as they stand)
    earlier_fn: Optional[Callable[[], dict]] = None         # today's slate, each game at its decision time (hindsight)
    backtest_fn: Optional[Callable[[int], dict]] = None     # the drill for 7, 14 or 30 days
    now: Optional[datetime] = None                          # the clock the answer speaks in (tests inject it)
    sizing: Optional[object] = None                         # the asker's unit_size.Sizing (their dollars); None = the reference account
    retune_fn: Optional[Callable[[str], dict]] = None       # the OWNER's self-diagnosis facts (retune.ask_facts); None for everyone else


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


def _protect(ctx: Optional["AskContext"]) -> set:
    """Words of the dog's own teams, so a team name is never "corrected" into a betting word."""
    if ctx is None:
        return set()
    words: set = set()
    for name, _keys in _team_names(ctx, None):
        words.update(w for w in norm(name).split() if len(w) >= 4)
    return words


def classify(question: str, ctx: Optional["AskContext"] = None) -> str:
    """The intent a question asks for, or ``fallback``. Scored, typo-tolerant: see ``ask_intents``."""
    intent, _score, _all = classify_scored(question, ctx)
    return intent


def classify_scored(question: str, ctx: Optional["AskContext"] = None) -> tuple:
    """(intent or ``fallback``, the winning score, every score). ``scores`` below the bar come back as ``fallback``
    with the closest intent named in the third item so the answer can offer it."""
    if not norm(question):
        return FALLBACK, 0.0, {}
    team = find_team(question, ctx) if ctx is not None else None
    scored = ask_intents.scores(question, _protect(ctx), team_named=team is not None)
    intent, top = ask_intents.best_intent(scored)
    if intent is None or top < ask_intents.MIN_SCORE:
        return FALLBACK, top, scored
    return intent, top, scored


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
    out = re.sub(r"\bit backs\b", "I back", out)
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
    """ONE line: the name and the hound's own catchphrase. The full rules live on the Rules tab, never in the chat
    (owner, 2026-10-22: the bio wall at the top of Ask was the first thing a visitor read)."""
    tag = " ".join(str(ctx.catchphrase or "").split())
    return {"lines": [f"{ctx.name} · {tag}" if tag else str(ctx.name)]}


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
        lines.append("A record needs graded games, so there is nothing to judge yet. My rules can still be replayed: ask "
                     "what I would have done this week, or what I would have taken today.")
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


# ---------------------------------------------------------------------------
# picks: the boards now, today's games at their decision times, and a window of past days
# ---------------------------------------------------------------------------

MAX_CARDS = 5
MAX_MISSES_SAID = 3
PAPER_TAIL = "Paper only. These are simulated picks, not advice."


def _now(ctx: AskContext) -> datetime:
    return ctx.now or datetime.now(timezone.utc)


def _et_when(ctx: AskContext, stamp) -> str:
    """'Today 8:10 pm ET', 'Thursday 8:15 pm ET': the viewer's day words, Eastern clock, zone named."""
    moment = _parse(stamp)
    if moment is None:
        return ""
    return f"{fire.day_label(fire.day_of(moment), _now(ctx))} {fire.clock_et(moment)}"


def _clock(ctx: AskContext, stamp) -> str:
    moment = _parse(stamp)
    return fire.clock_et(moment) if moment is not None else ""


def _stake_text(ctx: AskContext, units) -> str:
    """What a stake of ``units`` is in the ASKER's terms: "$50", or "2% of bankroll" (their sizing, the reference account's with none)."""
    n = float(units) if isinstance(units, (int, float)) and not isinstance(units, bool) and units > 0 else 1.0
    sizing = _asker(ctx)
    if sizing.mode == "fixed":
        usd = n * sizing.unit_usd
        return f"${usd:,.0f}" if abs(usd - round(usd)) < 0.005 else f"${usd:,.2f}"
    return f"{n * sizing.pct:g}% of bankroll"


def _card(ctx: AskContext, p: dict) -> dict:
    best = ""
    if p.get("price_best") is not None and p.get("price_best") != p.get("price_average") and p.get("best_book"):
        best = f"best {_price(p['price_best'])} at {p['best_book']}"
    return {"selection": p.get("selection"), "price": p.get("price_average"), "price_text": _price(p.get("price_average")),
            "best": best, "game": p.get("game"), "market": p.get("market_label") or p.get("market"),
            "when": _et_when(ctx, p.get("start_utc")), "day": p.get("day_label"), "reason": p.get("reason") or "",
            "state": "started" if p.get("started") else "ahead", "over_limit": bool(p.get("over_daily_limit")),
            "decided": _clock(ctx, p.get("decided_utc")) if p.get("decided_utc") else "",
            "stake": _stake_text(ctx, p.get("stake_units"))}


def _pick_line(c: dict, *, hindsight: bool) -> str:
    bits = f"{c['selection']} at {c['price_text']}" + (f" ({c['best']})" if c["best"] else "")
    line = f"{bits}: {c['game']}, {c['when']}."
    if hindsight and c["state"] == "started":
        line += " That game has started."
    if c["over_limit"]:
        line += " That is past my daily limit, so I would stop before it."
    return line


def _picks_block(ctx: AskContext, picks: list, *, hindsight: bool) -> tuple:
    """(cards, lines): the picks I would stand behind first (within the daily limit), grouped by day when they
    span more than one. Every price is the board average the rule used; none is -200 or worse (the engine's cap)."""
    shown = sorted(picks, key=lambda p: (bool(p.get("over_daily_limit")), p.get("start_utc") or "", p.get("event_id") or ""))
    shown = sorted(shown[:MAX_CARDS], key=lambda p: (p.get("start_utc") or "", p.get("event_id") or ""))
    cards = [_card(ctx, p) for p in shown]
    days = []
    for c in cards:
        if c["day"] not in days:
            days.append(c["day"])
    lines = []
    last = None
    for c in cards:
        if len(days) > 1 and c["day"] != last:
            lines.append(f"{c['day']}:")
            last = c["day"]
        lines.append(_pick_line(c, hindsight=hindsight))
    if len(picks) > len(shown):
        lines.append(f"Plus {len(picks) - len(shown)} more that qualified; ask me again later and I will rank them fresh.")
    return cards, lines


def first_person(text: str) -> str:
    """The Fire now sentences speak to the owner ("your band"); a dog answering says "my"."""
    out = re.sub(r"\b[Yy]our (band|rule|rules|limit)\b", lambda m: "my " + m.group(1), str(text or ""))
    return re.sub(r"\b[Yy]ou are\b", "I am", out)


def _miss_lines(payload: dict, *, limit: int = MAX_MISSES_SAID) -> list:
    out = []
    for m in (payload.get("closest_misses") or [])[:limit]:
        where = f"{m['game']}" + (f" ({m['market_label']})" if m.get("market_label") else "")
        out.append(f"Closest: {where}. {first_person(m['why'])}")
    return out


def _busy_line(busy: dict) -> str:
    n = busy.get("retry_after")
    kind = busy.get("kind")
    if kind == "drill":
        return f"Another replay is running, so I cannot start mine yet. Try again in {n or 30} seconds."
    if kind == "signin":
        return ("Replaying past days is the heaviest thing I do, so it is for signed-in visitors. "
                "Sign in and ask again, or ask me what I would take right now.")
    return f"I am being asked to read the boards a lot right now. Try me again in {n or 30} seconds."


def _unavailable(payload: Optional[dict], fallback: str) -> Optional[dict]:
    """A body when an evaluation could not run (busy, an error sentence, or no answer at all), else None."""
    if payload is None:
        return {"lines": [fallback]}
    if payload.get("busy"):
        return {"lines": [_busy_line(payload["busy"])], "busy": payload["busy"]}
    if payload.get("error"):
        return {"lines": [payload["error"]]}
    return None


def _right_now_view(ctx: AskContext, payload: dict) -> dict:
    """The page's own "what I'd play right now" answer for this payload: ``right_now.view_from_payload``, the SAME function the
    hound page's card calls, so Ask and the card can never disagree about what is fresh. Imported here because right_now
    imports camp, which imports this module."""
    from src.hounds.interact import right_now
    persona = (ctx.summary or {}).get("persona") if isinstance(ctx.summary, dict) else None
    return right_now.view_from_payload(
        payload, dog_id=ctx.dog_id, dog_name=ctx.name, kind=ctx.kind, spec=ctx.spec if ctx.kind == "user" else None,
        persona=persona if isinstance(persona, dict) else None,
        held=right_now.held_positions(payload.get("recorded"), ctx.manual), now=_now(ctx))


def _how_checked(ctx: AskContext, view: dict, payload: dict) -> dict:
    """The collapsed "How I checked it": the rule that fired, the numbers, the closest misses. Never inline in the answer."""
    lines = []
    top = (view.get("candidates") or [None])[0]
    if top is not None:
        if top.get("reason"):
            lines.append(str(top["reason"]))
        if top.get("lead"):
            lines.append(top["lead"])
        if isinstance(top.get("n_books"), int):
            lines.append(f"{top['n_books']} {'book is' if top['n_books'] == 1 else 'books are'} quoting it.")
        if top.get("stale"):
            lines.append(f"The board is {top.get('board_age_minutes')} minutes old, so the price may have moved.")
        if top.get("over_daily_limit"):
            lines.append("That is past my daily limit, so I would stop before it.")
        if payload.get("picks") and any(p.get("before_lock") for p in payload["picks"]):
            lines.append("My real ticket is written at my usual time before the start, on the board then, so it can differ.")
    else:
        lines += _miss_lines(payload)
        n = view.get("games_considered") or 0
        if n:
            lines.append(f"I looked at {n} {'game' if n == 1 else 'games'}.")
    rule = plain_rule(ctx.rule_english or ctx.rule_text)
    if rule:
        lines.append(f"My rule: {rule}")
    return {"title": "How I checked it", "lines": [x for x in lines if x]}


def _picks_now(ctx: AskContext, payload: Optional[dict]) -> dict:
    """"What would you bet right now": a FRESH pick from the current board, in the hound's voice, then the pick card.

    The pick is chosen by ``right_now.fresh_picks`` (the same code the hound page's card runs): never a ticket the hound already
    holds, never the other side of one, never a game that has started. With nothing fresh it says so in its voice and names the
    next game it will check; it does not list started games and does not fall back to a ticket it already placed."""
    from src.hounds.interact import right_now
    stop = _unavailable(payload, "I cannot read the boards just now. Try the Unleash button in a minute.")
    if stop is not None:
        return stop
    view = _right_now_view(ctx, payload)
    voice = view["voice"]
    candidates = view["candidates"]
    if candidates:
        top = candidates[0]
        card = _card(ctx, dict(top, stake_units=top.get("stake_units"), reason=""))   # the rule text is in "How I checked it"
        lines = [ask_voice.pick_line(voice, str(top.get("selection") or ""), _price(top.get("price_average")),
                                     seed=f"{ctx.dog_id}|{top.get('event_id')}|{top.get('market')}")]
        if len(candidates) > 1:
            more = len(candidates) - 1
            lines.append(f"{more} more {'fits' if more == 1 else 'fit'} tonight. Open What I'd play right now on my page to flip through.")
        out = {"lines": lines, "cards": [card], "cards_at": len(lines), "fire": True, "fine": PAPER_FINE}
    else:
        nxt = view.get("next_look") or {}
        when = _et_when(ctx, nxt.get("start_utc")) if nxt.get("start_utc") else ""
        line = ask_voice.nothing_line(voice, nxt.get("game"), when)
        if not nxt.get("game") and view.get("next_game"):
            line = f"{ask_voice.NOTHING.get(voice) or ask_voice.NOTHING['generic']} {view['next_game']}."
        out = {"lines": [line], "cards": [], "cards_at": 1, "fire": True, "fine": PAPER_FINE}
    out["details"] = _how_checked(ctx, view, payload)
    return out


PAPER_FINE = "Paper pick, not advice. 21+."


MAX_TICKETS = 3


def _picks_earlier(ctx: AskContext, payload: Optional[dict], *, intro: bool = True) -> dict:
    """"What would you have taken today, pre market": every game on today's slate at its own decision time."""
    stop = _unavailable(payload, "I cannot read today's boards just now. Try me again in a minute.")
    if stop is not None:
        return stop
    head = ["Hindsight, not counted: here is what my rules would have taken on today's games, each game judged "
            "on the board as it stood at its own decision time."] if intro else []
    picks = payload.get("picks") or []
    tail = []
    cards: list = []
    pick_lines: list = []
    in_limit = [p for p in picks if not p.get("over_daily_limit")]
    n_games = payload.get("games_considered") or 0
    if in_limit:
        cards, pick_lines = _picks_block(ctx, in_limit, hindsight=True)
        if any(not p.get("started") and p.get("before_lock") for p in in_limit):
            tail.append("A game whose placing time has not come yet is judged on the newest board, so it can still change.")
        cut = len(picks) - len(in_limit)
        if cut:
            tail.append(f"{cut} more would have qualified, but my daily limit stops me before {'it' if cut == 1 else 'them'}.")
    else:
        if n_games == 0 and not (payload.get("closest_misses") or payload.get("passes")):
            if payload.get("trigger") is not None:
                tail.append("None of today's games have started yet, and I can replay a game only once its placing time "
                            "has passed. Ask me what I would bet right now to run my rule on the boards as they stand.")
            else:
                tail.append("There are no games on today's board for my rule to look at. Ask me what I would bet right "
                            "now to see the next slate.")
        else:
            tail.append("Nothing would have qualified.")
            tail += _miss_lines(payload)
            if payload.get("trigger") and payload.get("passes"):
                tail.append(f"I bet when {payload['trigger']}; none of the {payload['passes']} games I looked at fit.")
            if n_games:
                tail.append(f"I looked at {n_games} {'game' if n_games == 1 else 'games'}.")
    tail.append(PAPER_TAIL)
    return {"lines": head + pick_lines + tail, "ui_lines": head + tail, "cards": cards, "cards_at": len(head),
            "hindsight": True}


# -- the replay over past days ---------------------------------------------------------------------------------

def _money(units: Optional[float], unit_usd: float) -> str:
    if units is None:
        return "n/a"
    return _usd_words(round(units * unit_usd, 2))


def _usd_words(usd: Optional[float]) -> str:
    if usd is None:
        return "n/a"
    if usd == 0:
        return "even, $0.00"
    return f"{'up' if usd > 0 else 'down'} ${abs(usd):,.2f}"


def _asker(ctx: AskContext):
    """The sizing this answer speaks in: the asker's own (``unit_size``) or, with none, the reference account."""
    from src.hounds import bankroll, unit_size
    if ctx.sizing is not None:
        return ctx.sizing
    p = bankroll.params()
    return unit_size.Sizing("fixed", p.unit_usd, None, p.start)


def _unit_phrase(sizing) -> str:
    if sizing.mode == "fixed":
        return f"one unit is ${sizing.unit_usd:,.0f} a bet, flat"
    return f"one unit is {sizing.pct:g}% of the balance when the bet is placed, so it compounds"


def _window_dates(kind: str, today: str) -> Optional[tuple]:
    """(first, last) dates a named window covers inside the drill's span, or None for the whole span."""
    try:
        d = datetime.fromisoformat(today)
    except ValueError:
        return None
    if kind == "yesterday":
        y = (d - timedelta(days=1)).date().isoformat()
        return y, y
    if kind == "weekend":
        sunday = d - timedelta(days=1)
        while sunday.weekday() != 6:
            sunday -= timedelta(days=1)
        return (sunday - timedelta(days=1)).date().isoformat(), sunday.date().isoformat()
    if kind == "thisweek":
        monday = d - timedelta(days=d.weekday())
        if monday >= d:
            return None
        return monday.date().isoformat(), (d - timedelta(days=1)).date().isoformat()
    return None


def _backtest(ctx: AskContext, question: str, result: Optional[dict], win: dict) -> dict:
    from src.hounds import bankroll
    from src.hounds.interact import drill
    stop = _unavailable(result, "I cannot replay my rules just now. Try me again in a minute.")
    if stop is not None:
        return stop
    params = bankroll.params()
    span = _window_dates(win["kind"], ctx.today)
    label = win["label"]
    notes = []
    body = result
    if span is not None:
        picks = result.get("picks") or []
        if result.get("picks_total", len(picks)) > len(picks):
            notes.append(f"That window held more bets than I can list, so here is the last {result.get('days', 7)} days instead.")
            label = f"the last {result.get('days', 7)} days"
        else:
            kept = [p for p in picks if span[0] <= str(p.get("date")) <= span[1]]
            body = dict(drill._summary(list(kept)))
    if win.get("clipped"):
        notes.append("I can look back at most 30 days, so that is the window I used.")
    if win["kind"] == "thisweek" and span is None:
        notes.append("This week has no finished day yet, so I used the last 7 days.")
        label = "the last 7 days"
    rec = body.get("record") or {}
    graded, bets = rec.get("graded", 0), rec.get("bets", 0)
    lines = [f"Replaying my rules over {label}, in hindsight (not counted, a rehearsal on boards already captured):"]
    if not bets:
        lines.append("My rules would not have placed a bet in that window.")
    else:
        wl = f"{rec.get('wins', 0)}-{rec.get('losses', 0)}" + (f"-{rec['pushes']}" if rec.get("pushes") else "")
        units = body.get("units_average_price")
        sizing = _asker(ctx)
        picks_usd = {}
        if sizing.mode == "fixed":
            money_text = _money(units, sizing.unit_usd)
            pct = None if units is None else units * sizing.unit_usd / sizing.start_usd * 100.0
        else:
            # percent of bankroll compounds: the replay's own bet list (stake-weighted), priced bet by bet
            from src.hounds import unit_size
            evts = unit_size.from_wire((body.get("bankroll") or {}).get("events"))
            dollars = [d[0] for d in unit_size.priced(evts, sizing)] if evts else []
            picks_usd = dict(enumerate(dollars))
            total = round(sum(dollars), 2) if dollars else None
            money_text = _usd_words(total)
            pct = None if total is None else total / sizing.start_usd * 100.0
        lines.append(f"{graded} graded {'bet' if graded == 1 else 'bets'}: {wl}, {money_text} "
                     f"on a ${sizing.start_usd:,.0f} paper bankroll"
                     + (f", a {pct:+.1f}% return" if pct is not None else "")
                     + (" at your sizing" if sizing.mode == "percent" and pct is not None else "")
                     + f" ({_unit_phrase(sizing)}).")
        unsettled = bets - graded
        if unsettled:
            lines.append(f"{unsettled} more {'bet is' if unsettled == 1 else 'bets are'} not graded yet.")
        for tag, items in (("Best", body.get("best") or []), ("Worst", body.get("worst") or [])):
            if items:
                p = items[0]
                worth = (_money(p.get("units_average_price"), sizing.unit_usd) if sizing.mode == "fixed"
                         else _usd_words(round(picks_usd[p["ev"]], 2) if p.get("ev") in picks_usd else None))
                lines.append(f"{tag} pick: {p['selection']} ({p['game']}, {_day(p['date'])}) at {_price(p['price_average'])}, "
                             f"{worth}.")
        lines.append("That is a small sample, so wins and losses this few are mostly luck." if body.get("small_sample", True)
                     else "Even so, a rehearsal is not a forward result.")
    lines += notes
    lines.append(PAPER_TAIL)
    return {"lines": [x for x in lines if x], "hindsight": True, "window": {"label": label, "days": result.get("days")}}


def _why_not(ctx: AskContext, question: str, fire: Optional[dict]) -> dict:
    team = find_team(question, ctx, fire)
    early = None
    if team is None and ctx.earlier_fn is not None:
        early = _get_earlier(ctx)                       # today's started games are teams a person can name too
        team = find_team(question, ctx, early) if not early.get("error") and not early.get("busy") else None
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
                        lines.append(f"On {label} I pass. {first_person(m['why'])}")
                return {"lines": lines}
    if ctx.earlier_fn is not None:
        early = early if early is not None else _get_earlier(ctx)
        if not early.get("error") and not early.get("busy"):
            for g in early.get("games", []):
                if needle in norm(g.get("game") or ""):
                    lines = [f"{g['game']} is on today's slate, so I judged it on the board at its own decision time "
                             "(hindsight, not counted)."]
                    for m in g["markets"]:
                        label = m["market"] if m.get("market") else "the game"
                        if m["status"] == "pick":
                            lines.append(f"On {label} my rule would have taken {m['selection']} at {_price(m['price_average'])}.")
                        else:
                            lines.append(f"On {label} I would have passed. {first_person(m['why'])}")
                    return {"lines": lines, "hindsight": True}
    return {"lines": [f"I cannot see {team} on today's slate or among the games still ahead of me, and I have no ticket on it.",
                      "To see what my rule does over past days, ask me what I would have done this week. It replays my "
                      "rule on old boards and is never counted."]}


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
    lines.append("I do not change my own rule. A new version is a new hound with its own record.")
    return {"lines": lines}


def _improve(ctx: AskContext) -> dict:
    lines = []
    if ctx.kind == "user" and ctx.is_owner:
        lines += ["You are my owner, so you can change my rule: open the builder from my page, change one thing, and it becomes a new version with its own record.",
                  "Before you do, run a backtest in the Training camp. It replays my rule over the last 7, 14 or 30 days so you can see what a change would have done. It is never counted.",
                  "Rate my tickets Good call or Bad call. I keep the notes where you can read them."]
    elif ctx.kind == "user":
        lines += ["Rate my tickets Good call or Bad call, and use Suggest a change to send my owner an idea. It reaches them as a suggestion and changes nothing on its own."]
    else:
        lines += ["Rate my tickets Good call or Bad call.",
                  "If I have dials, the Coach this model panel on my page lets you send a tip. Every tip is graded by code against the same games, and only the referee can change me."]
    lines.append("Nothing anyone sends changes me by itself. A change has to earn its place on the numbers.")
    return {"lines": lines}


RETUNE_LABEL = "Retune me"
NOT_YOURS = ("Only my owner can change my rules. Use Suggest a change to send my owner an idea: it reaches them as a "
             "suggestion and changes nothing on its own.")


def _retune(ctx: AskContext, question: str) -> dict:
    """The owner said the rule is too tight, too loose, or asked what to change (owner request 2026-10-22). The hound answers with
    what its own rule did on today's board, in the counts ``retune.self_diagnosis`` computed, and the owner (only) gets a Retune
    button. The button starts a proposal the owner can veto or tweak; nothing is changed by this answer. A visitor, or an owner
    asking a house hound, gets no button."""
    if ctx.kind != "user":
        return _improve(ctx)
    if not ctx.is_owner or ctx.retune_fn is None:
        return {"lines": [NOT_YOURS]}
    facts = _guarded(ctx.retune_fn, question, missing=NOT_YOURS)
    if facts.get("busy"):
        return {"lines": [_busy_line(facts["busy"])]}
    if facts.get("error"):
        return {"lines": [facts["error"]]}
    return {"lines": retune.compose_lines(facts),
            "retune": {"offer": True, "label": RETUNE_LABEL, "enabled": bool(facts.get("eligible")),
                       "note": "" if facts.get("eligible") else str(facts.get("gate") or "")}}


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
        return {"lines": ["No graded tip has been sent about me yet. Tips on a hound with dials show up here once code has graded them."]}
    lines = [f"{len(tips)} graded {'tip' if len(tips) == 1 else 'tips'} about me:"]
    for tip in tips[:3]:
        lines.append(f"{tip.get('label') or 'Not graded'}: {tip.get('line')}")
    lines.append("Tips never change me. Only the referee does.")
    return {"lines": lines}


# ---------------------------------------------------------------------------
# a betting term, the menu, and a question nobody recognised
# ---------------------------------------------------------------------------

def _glossary(sizing=None) -> dict:
    from src.hounds import bankroll
    p = bankroll.params()
    share = sizing is not None and sizing.mode == "percent"
    if sizing is None:
        start, unit = f"${p.start:,.0f}", f"${p.unit_usd:,.0f}"
    elif share:
        start, unit = f"${sizing.start_usd:,.0f}", f"{sizing.pct:g}% of the balance"
    else:
        start, unit = f"${sizing.start_usd:,.0f}", f"${sizing.unit_usd:,.0f}"
    unit_line = (f"A unit is one standard stake. At your sizing one unit is {unit} when the bet is placed, so it grows and "
                 f"shrinks with the balance, on a {start} start." if share else
                 f"A unit is one standard stake. On my paper bankroll one unit is {unit}, 1% of the {start} start, "
                 "and it never grows or shrinks with the balance.")
    bank_line = (f"My paper bankroll starts at {start}, and every bet is {unit} per unit. Nothing real is "
                 "ever staked: it is how the site keeps score." if share else
                 f"My paper bankroll starts at {start}, and every bet is a flat unit of {unit}. Nothing real is "
                 "ever staked: it is how the site keeps score.")
    return {
        "spread": ["A spread bet is on the margin of a game, not just who wins. A team at -1.5 has to win by two or more; "
                   "a team at +1.5 can lose by one and still count as a win. In baseball the spread is the run line."],
        "runline": ["The run line is baseball's spread, almost always 1.5 runs. The favourite at -1.5 has to win by two or "
                    "more; the underdog at +1.5 wins the bet if it wins or loses by one."],
        "moneyline": ["A moneyline is a bet on who wins, with no margin. A price of -150 means staking 150 to win 100; "
                      "+130 means a stake of 100 wins 130."],
        "total": ["A total (the over/under) is a bet on the combined score of both teams against a number, say 8.5 runs. "
                  "The over wins on 9 or more; the under wins on 8 or fewer. A whole-number total can push."],
        "prop": ["A prop is a bet on one player's line rather than the game's result, such as a pitcher's strikeouts or "
                 "a batter's hits. Props are MLB only here, and dogs built with rules can use them."],
        "unit": [unit_line],
        "bankroll": [bank_line],
        "vig": ["The vig (or juice) is the book's cut built into the price. Both sides of a -110 market pay less than even "
                "money, which is why a coin-flip bet loses a little every time."],
        "parlay": ["A parlay ties several bets into one that pays only if every leg wins. I do not bet parlays; every pick "
                   "of mine is a single bet."],
        "push": ["A push is a tie with the line: the stake comes back and the bet counts as neither a win nor a loss."],
        "odds": ["American odds: a minus price (-150) is what you stake to win 100; a plus price (+130) is what a stake of "
                 "100 wins. A plus price is an underdog and a minus price a favourite."],
        "impliedprob": ["Implied probability is the win chance a price states: -150 says 60%, +150 says 40%. Add both sides "
                        "of a market and you get over 100%; the extra is the vig."],
        "favourite": ["The favourite is the side the market thinks more likely to win (the minus price); the underdog is "
                      "the plus price. I never take a price of -200 or worse."],
        "clv": ["Closing line value compares the price a bet got with the price when the game started. It measures the "
                "price only; it says nothing about whether any one bet wins."],
        "steam": ["Steam, or line movement, is the price or number shifting as bets come in. Some of my rules follow a move "
                  "and some fade it."],
        "roi": [f"Return here is how much a bankroll moved as a share of its start: on {start}, a gain of $50 is a 5% return. "
                "Yield is the gain per dollar actually staked, a different denominator."],
    }


def _explain_market(ctx: AskContext, question: str) -> dict:
    term = ask_intents.glossary_term(ask_intents.normalize(question, _protect(ctx)))
    lines = list(_glossary(ctx.sizing).get(term or "", []))
    if not lines:
        return _help(ctx)
    lines.append("Ask about another term, or what I would take right now.")
    return {"lines": lines}


MENU = ("Why I made a bet, what I bet today, how I am doing, my best and worst bet, what I would bet right now, "
        "what I would have taken earlier today, what I would have done over the last 7, 14 or 30 days, "
        "why I skipped a game, my rules, a betting term like a spread, and how to make me better.")


def _help(ctx: AskContext) -> dict:
    return {"lines": ["Here is what I can answer:", MENU,
                      "Try: what would you bet right now, what would you have taken today pre market, "
                      "or what would you have done this week."]}


def _unknown(ctx: AskContext, scored: dict) -> dict:
    """A question nobody recognised is never a dead end: the closest thing I know, then the menu."""
    best, top = ask_intents.best_intent(scored or {})
    lines = ["I did not quite catch that, so here is the closest thing I have."]
    heavy = {"picks_now": "what would you bet right now", "picks_earlier_today": "what would you have taken today pre market",
             "backtest_window": "what would you have done this week", "why_bet": "why did you bet the (team)",
             "why_not": "why did you not bet the (team)"}
    if best in heavy and top >= 1.0:
        lines.append(f"It sounds like you want me to run my rules. Ask it like this: \"{heavy[best]}\" and I will.")
        lines += _record(ctx)["lines"][:2]
    elif best in ("rules", "improve", "fans", "coach", "explain_market", "best_worst", "hello", "help") and top >= 1.0:
        builder = {"rules": lambda: _rules(ctx), "improve": lambda: _improve(ctx), "fans": lambda: _fans(ctx),
                   "coach": lambda: _coach(ctx), "best_worst": lambda: _best_worst(ctx, ""),
                   "explain_market": lambda: _help(ctx), "hello": lambda: _intro(ctx), "help": lambda: _help(ctx)}[best]
        lines += builder()["lines"][:3]
    else:
        lines += _record(ctx)["lines"][:2]
    lines += ["Here is what I can answer:", MENU]
    return {"lines": lines}


def suggestions(ctx: AskContext) -> list:
    """Questions worth asking this dog right now, in the order a person reads them."""
    out = ["What would you bet right now?", "What would you have taken earlier today?"]
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
        out.append("What did you bet today?")
    out += ["What would you have done this week?", "How are you doing?", "What are your rules?",
            "What is your best and worst bet?", "How do I make you better?"]
    return out[:7]


# ---------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------

def _guarded(fn: Optional[Callable], *args, missing: str = "") -> dict:
    """An evaluation's payload, or ``{"busy": ...}`` / ``{"error": sentence}`` the answer can say out loud."""
    if fn is None:
        return {"error": missing}
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 -- a board that cannot be read is said, not hidden
        kind = getattr(exc, "kind", None)
        if kind in ("rate", "drill", "signin"):
            return {"busy": {"kind": kind, "retry_after": getattr(exc, "retry_after", None)}}
        return {"error": str(exc) if getattr(exc, "public", False) else "I cannot read the boards just now."}


NOT_FIRABLE = "I cannot run a rule on demand: only the house hounds and the hounds people built can do that."


def _get_fire(ctx: AskContext) -> dict:
    """The read-only preview, or an ``{"error": sentence}`` the answer can say out loud."""
    return _guarded(ctx.fire_fn, missing=NOT_FIRABLE)


def _get_earlier(ctx: AskContext) -> dict:
    return _guarded(ctx.earlier_fn, missing=NOT_FIRABLE)


def _answer_body(intent: str, q: str, ctx: AskContext, scored: dict) -> dict:
    if intent == "hello":
        return _intro(ctx)
    if intent == "help":
        return _help(ctx)
    if intent == "record":
        return _record(ctx)
    if intent == "today":
        body = _today(ctx, q)
        if not ctx.tickets and ctx.earlier_fn is not None:
            # A dog with no ticket still has a rule: say so, then run it over today's games (owner, 2026-10-19).
            more = _picks_earlier(ctx, _get_earlier(ctx), intro=False)
            lead = ["I have not recorded a ticket yet, so there is nothing on my record to list. My rules can still "
                    "answer that: here is what they would have taken today, in hindsight."]
            body = dict(more, lines=lead + more["lines"], ui_lines=lead + more.get("ui_lines", more["lines"]),
                        cards_at=(more.get("cards_at") or 0) + 1)
        return body
    if intent == "why_bet":
        return _why_bet(ctx, q)
    if intent == "best_worst":
        return _best_worst(ctx, q)
    if intent == "picks_now":
        if ctx.fire_fn is None:
            # a hound with no rule to run (a desk model, a baseline) has no "right now" pick; it never answers with a ticket it already placed
            return {"lines": [ask_voice.CANNOT_RUN], "fine": PAPER_FINE}
        return _picks_now(ctx, _get_fire(ctx))
    if intent == "picks_earlier_today":
        if ctx.earlier_fn is None:
            return {"lines": [NOT_FIRABLE + " Ask me about my record instead."]}
        return _picks_earlier(ctx, _get_earlier(ctx))
    if intent == "backtest_window":
        win = ask_intents.parse_window(q, _protect(ctx))
        if ctx.backtest_fn is None:
            return {"lines": [NOT_FIRABLE + " Ask me about my record instead."]}
        return _backtest(ctx, q, _guarded(ctx.backtest_fn, win["days"], missing=NOT_FIRABLE), win)
    if intent == "why_not":
        return _why_not(ctx, q, _get_fire(ctx))
    if intent == "rules":
        return _rules(ctx)
    if intent == "improve":
        return _improve(ctx)
    if intent == "retune":
        return _retune(ctx, q)
    if intent == "explain_market":
        return _explain_market(ctx, q)
    if intent == "fans":
        return _fans(ctx)
    if intent == "coach":
        return _coach(ctx)
    return _unknown(ctx, scored)


def answer(question: str, ctx: AskContext) -> dict:
    """``{intent, answer, lines, cards, tickets, followups, matched, question}``. Never raises on an odd question."""
    q = str(question or "").strip()[:300]
    intent, _top, scored = classify_scored(q, ctx)
    if intent == "why_bet":
        team = find_team(q, ctx, None)
        if team and not _tickets_for(ctx, team):
            intent = "why_not"                     # a team the dog never bet: that is a question about a skip
    asks_for_picks = intent in ("picks_now", "picks_earlier_today", "backtest_window")
    if retune.detect(q, strong=asks_for_picks) and find_team(q, ctx, None) is None:
        intent = "retune"                          # "I don't like that you won't take a single bet": a request to tune the rule
    body = _answer_body(intent, q, ctx, scored)
    if intent == FALLBACK:
        intent = FALLBACK
    lines = body["lines"]
    followups = [s for s in suggestions(ctx) if norm(s) != norm(q)][:4]
    return {"intent": intent, "question": q, "answer": " ".join(lines), "lines": lines,
            "ui_lines": body.get("ui_lines") or lines, "cards": body.get("cards", []), "cards_at": body.get("cards_at"),
            "hindsight": bool(body.get("hindsight")), "busy": body.get("busy"),
            "details": body.get("details"), "fine": body.get("fine"), "retune": body.get("retune"),
            "tickets": body.get("tickets", []), "followups": followups, "matched": intent != FALLBACK,
            "dog_id": ctx.dog_id, "dog_name": ctx.name, "paper_only": True}
