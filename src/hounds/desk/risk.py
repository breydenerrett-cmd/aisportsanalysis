"""The code risk manager: the model proposes, code disposes.

In the TradingAgents idea a risk manager reads the trader's proposal and approves or rejects it. Here the
risk manager is not a model: it is this file, and the model cannot argue with it. It is pre-registered
(docs/PREREG_DESK_HOUNDS.md section 3) and its numbers are named constants.

THE RULES, IN ORDER, FIRST FAILURE WINS
---------------------------------------
    R1  the selection exists, and the price and book named are the selection's best quote in the packet
    R2  no TAKE at -200 or worse, at the price taken OR at the board average price
    R3  the stated probability beats the books' de-vigged consensus AND the break-even of the average price
    R4  the persona's own rule, where the hound has one (`persona_problem`)
    R5  at most `MAX_TAKES` TAKEs: the largest margins are kept, the rest struck

A strike is a PASS with the reason saved; it never earns a new answer (the publication rule's re-answer is
for a checker rejection, not for a decision code disagreed with). Rules R1 to R5 run BEFORE the checker, so
the checker only sees TAKEs code has already allowed, and a TAKE at -210 is a strike here, not a
rejection there.

WHY THE AVERAGE PRICE IN R3
---------------------------
A bet is graded at the best price taken and again at the board's mean price (`price_average`,
src/hounds/stats.py), and the second is the one a bettor who shopped nothing would have got. A model that
cannot show a probability above the break-even of the AVERAGE price is claiming a gap the vig would
swallow for most bettors, so it is not allowed to bet it. The consensus probability is the packet's own
`fair_probability` (the mean over books of each book's proportional de-vig), so it is checkable.

WHY -200 IS CHECKED TWICE
-------------------------
The owner's rulings (2026-09-20, 2026-09-22): no pick at -200 or worse, anywhere. The checker also
strikes it (critic.check_call); this file does it first and independently, on the average price too, so the
cap holds even if the checker is changed.

Pure: no I/O, no clock, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from src.analyst import analyst as analyst_mod
from src.core import odds as odds_math

TAKE_PRICE_FLOOR = analyst_mod.TAKE_PRICE_FLOOR       # -200: this price or worse is never a TAKE
MAX_TAKES = 2                                          # per game, per hound
GRINDER_MAX_GAP = 0.05                                 # probability points above fair_probability
GRINDER_SHORT_FAVOURITE = -150                         # best price this or shorter

HISTORY_PREFIX = {"mlb": "sections.matchup_history",
                  "nfl": "sections.matchup.values.head_to_head"}
HISTORIAN_OK_PREFIXES = ("markets.", "game.")

# Persona -> its rule id in the pre-registration. A hound not listed has no rule R4.
PERSONA_OF_STAGE = {"persona_sharp": "sharp", "persona_square": "square", "persona_fader": "fader",
                    "persona_weather": "weather", "persona_grinder": "grinder",
                    "persona_historian": "historian"}


def sport_of(packet: Mapping) -> str:
    """'nfl' for a football packet (it states a kickoff), else 'mlb'."""
    game = packet.get("game") or {}
    return "nfl" if "kickoff_utc" in game and "first_pitch_utc" not in game else "mlb"


def break_even(price: Any) -> Optional[float]:
    try:
        return odds_math.american_to_probability(price)
    except (odds_math.OddsError, TypeError, ValueError):
        return None


def board_average(option: Mapping) -> Optional[int]:
    """American price of the mean decimal price over the books quoting the option in the packet."""
    prices = [q["price"] for q in option.get("quotes") or []
              if isinstance(q.get("price"), int) and not isinstance(q.get("price"), bool)]
    if not prices:
        return None
    try:
        mean_dec = sum(odds_math.american_to_decimal(p) for p in prices) / len(prices)
    except odds_math.OddsError:
        return None
    if mean_dec <= 1.0:
        return None
    return int(round(odds_math.decimal_to_american(mean_dec)))


def side_kind(market: Mapping, option: Mapping) -> Optional[str]:
    """What kind of side an option is, in the words the persona rules use: favourite, underdog,
    gets_points, lays_points, over, under. None when it is none of those (a pick-em line, an unknown market)."""
    kind = market.get("market")
    if kind == "moneyline":
        return "favourite" if option.get("selection") == market.get("lean") else "underdog"
    if kind in ("run_line", "spread"):
        line = option.get("line")
        if isinstance(line, (int, float)) and not isinstance(line, bool):
            return "gets_points" if line > 0 else "lays_points" if line < 0 else None
        return None
    if kind in ("total", "team_total", "prop"):
        return option.get("side") if option.get("side") in ("over", "under") else None
    return None


@dataclass
class Taken:
    """A TAKE code allowed (before the checker), with every number a row needs."""
    decision: dict
    slot_id: str
    selection: str
    market: str
    side: Optional[str]
    line: Optional[float]
    price_best: int
    book: str
    book_count: int
    price_average: int
    consensus_fair: float
    probability: float
    breakeven_average: float
    margin: float
    kind: Optional[str]


@dataclass
class Struck:
    slot_id: str
    selection: Any
    rule: str
    reason: str

    def line(self) -> str:
        return f"{self.slot_id}: {self.rule} {self.reason}"


@dataclass
class RiskResult:
    kept: list = field(default_factory=list)       # [Taken], largest margin first
    struck: list = field(default_factory=list)     # [Struck]


def _evidence_paths(reasons: Any) -> list:
    out = []
    for reason in reasons or []:
        if isinstance(reason, Mapping):
            for ev in reason.get("evidence") or []:
                if isinstance(ev, Mapping) and isinstance(ev.get("path"), str):
                    out.append(ev["path"])
    return out


def persona_problem(persona: Optional[str], *, packet: Mapping, market: Mapping, option: Taken) -> Optional[str]:
    """Why persona `persona`'s own rule (R4) forbids this TAKE, or None. `option` is the Taken being judged."""
    if persona is None:
        return None
    kind = option.kind
    if persona == "sharp":
        best_be = break_even(option.price_best)
        if best_be is None or not best_be < option.consensus_fair:
            return ("the Sharp takes only a best quote whose break-even probability is below the books' "
                    f"de-vigged number; {option.price_best} implies {best_be if best_be is None else round(best_be, 4)}, "
                    f"the books' number is {option.consensus_fair}")
    elif persona == "square":
        ok = (market.get("market") == "moneyline" and kind == "favourite") or \
             (market.get("market") == "total" and kind == "over")
        if not ok:
            return "the Square takes only the moneyline favourite or the Over on the game total"
    elif persona == "fader":
        if kind not in ("underdog", "gets_points", "under"):
            return "the Fader takes only a moneyline underdog, a side that gets points, or an Under"
    elif persona == "weather":
        if market.get("market") not in ("total", "team_total"):
            return "the Weather Nerd takes only the game total and the team totals"
    elif persona == "grinder":
        short_fav = (market.get("market") == "moneyline" and kind == "favourite"
                     and option.price_best >= GRINDER_SHORT_FAVOURITE)
        if not (kind == "under" or short_fav):
            return (f"the Grinder takes only an Under or a moneyline favourite at {GRINDER_SHORT_FAVOURITE} "
                    "or shorter")
        gap = option.probability - option.consensus_fair
        if gap > GRINDER_MAX_GAP + 1e-9:
            return (f"the Grinder's stated probability may exceed the books' number by at most "
                    f"{GRINDER_MAX_GAP}; this one exceeds it by {round(gap, 4)}")
    elif persona == "historian":
        prefix = HISTORY_PREFIX[sport_of(packet)]
        paths = _evidence_paths(option.decision.get("reasons"))
        stray = [p for p in paths if not (p.startswith(prefix) or p.startswith(HISTORIAN_OK_PREFIXES))]
        if stray:
            return ("the Historian may cite only history, prices (markets.) and the game block; "
                    f"it cited {stray[0]!r}")
        if not any(p.startswith(prefix) for p in paths):
            return f"the Historian needs at least one reason that cites the history section ({prefix})"
    return None


def assess(packet: Mapping, decisions: Sequence[Mapping], persona: Optional[str] = None,
           max_takes: int = MAX_TAKES) -> RiskResult:
    """Run R1 to R5 over a hound's proposed TAKEs. Never raises on bad content: bad content is what it
    exists to strike. `persona` is a key of `PERSONA_OF_STAGE.values()` or None (the Desk has no R4)."""
    result = RiskResult()
    survivors: list = []
    markets = packet.get("markets") or {}
    for d in decisions:
        sid, sel = d.get("slot_id"), d.get("selection")
        market = markets.get(sid)
        option = next((o for o in (market or {}).get("options", []) if o.get("selection") == sel), None)
        if market is None or option is None:
            result.struck.append(Struck(str(sid), sel, "R1", f"{sel!r} is not a listed selection of {sid!r}"))
            continue
        price, book = d.get("price"), d.get("book")
        best = option.get("best") or {}
        quoted = any(q.get("book") == book and q.get("price") == price for q in option.get("quotes") or [])
        if not quoted or price != best.get("price"):
            result.struck.append(Struck(
                sid, sel, "R1", f"{book!r} at {price!r} is not the best quote in the data for {sel!r} "
                                f"(the best is {best.get('price')!r})"))
            continue
        average = board_average(option)
        if price <= TAKE_PRICE_FLOOR or (average is not None and average <= TAKE_PRICE_FLOOR):
            result.struck.append(Struck(
                sid, sel, "R2", f"a price of {price} (board average {average}) is {TAKE_PRICE_FLOOR} or worse "
                                "and cannot be a TAKE"))
            continue
        fair = option.get("fair_probability")
        p = d.get("probability")
        be_avg = break_even(average) if average is not None else None
        if not isinstance(fair, (int, float)) or isinstance(fair, bool) or be_avg is None:
            result.struck.append(Struck(sid, sel, "R3", "there is no de-vigged consensus or average price "
                                                        "to beat for this selection"))
            continue
        if not isinstance(p, (int, float)) or isinstance(p, bool) or not p > fair or not p > be_avg:
            result.struck.append(Struck(
                sid, sel, "R3", f"the stated probability {p!r} does not beat both the books' de-vigged number "
                                f"{fair} and the break-even {round(be_avg, 4)} of the average price {average}"))
            continue
        taken = Taken(decision=dict(d), slot_id=sid, selection=sel, market=market["market"],
                      side=option.get("side"), line=option.get("line"), price_best=price, book=book,
                      book_count=int(option.get("books") or len(option.get("quotes") or [])),
                      price_average=average, consensus_fair=float(fair), probability=float(p),
                      breakeven_average=be_avg, margin=float(p) - be_avg,
                      kind=side_kind(market, option))
        why = persona_problem(persona, packet=packet, market=market, option=taken)
        if why:
            result.struck.append(Struck(sid, sel, "R4", why))
            continue
        survivors.append(taken)
    order = {sid: i for i, sid in enumerate(markets)}
    survivors.sort(key=lambda t: (-t.margin, order.get(t.slot_id, 10 ** 6)))
    result.kept = survivors[:max_takes]
    for extra in survivors[max_takes:]:
        result.struck.append(Struck(
            extra.slot_id, extra.selection, "R5",
            f"more than {max_takes} TAKEs; the {max_takes} with the largest margin are kept and this one's "
            f"margin {round(extra.margin, 4)} was smaller"))
    return result
