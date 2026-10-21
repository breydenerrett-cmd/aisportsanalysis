"""The signal generator: for each game, every numerological coincidence each side's outcome produces, typed and counted.

THE IDEA, REVERSE-ENGINEERED FROM THE POSTS (research/rabbitszn/METHOD.md). A post builds a world for one result ("Seattle
beats Purdue") and lists the numbers that line up in it: the winner's coach gets his 19th win, the other state is the
19th state, "Seattle" is 19 in Full Reduction, the game is 19 days from a founding date. The number that keeps recurring is
the argument. The other result gets the same treatment (the posts' warning bullets), and the side with the better
case is taken.

THAT IS A SEARCH, and this module makes it a countable one. For each game there are two WORLDS, "home wins" and "away
wins", and a pool of quantities:

  STATIC quantities are the same in both worlds: every name's cipher values (team, city, mascot, state, university,
      abbreviation, head coach, the weekday), the state's order of statehood, the numbers of the game date, spans counted
      from founding/admission dates to the game date, and plain game/meeting numbers.
  MILESTONES exist only in one world: if the home side wins its win total, its venue wins, its streak, the days and
      weeks since it last won, and the AWAY side's losses, loss streak, days since it last lost, the series count, an NFL
      coach's wins and losses with the club (in our store) all take a specific value. They are the outcome-conditional counts.

A MATCH is an equality between a milestone of one world and a static quantity or another milestone of that same world
(or a prime-index / triangular-number link between two of them, or a milestone of 33 or 47), and each match is a typed
``Evidence`` item with the two quantities, their values, the cipher and a weight from the rules file. A side's SCORE is the
sum of the weights of its world's matches. Because the static pool is shared, a side scores only where ITS milestones hit
it. The generator is SYMMETRIC by construction (nothing depends on which team is home except the venue-specific counts,
which swap with the teams) and DETERMINISTIC (fixed field order, no randomness, no clock).

THE SEARCH SPACE IS LOGGED. Every equality tried is counted per world (``comparisons``), because a number that "lines up"
means little without the number of chances it had. With dozens of values in a range of a few hundred, a few matches per
world arrive by chance alone; the evidence panel prints the count beside the score so nobody reads one without the other.

Missing data is silence: a fact or count that is not there makes no quantity, so it can make no match. Pure functions,
stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.hounds.gematria import facts as facts_mod
from src.hounds.gematria import history
from src.hounds.gematria.rules import KINDS, Rules
from src.research import gematria

SIDES = ("home", "away")


def other(side: str) -> str:
    return "away" if side == "home" else "home"


@dataclass(frozen=True)
class Quantity:
    qid: str                         # unique within a game; the dedupe key
    group: str                       # name | state | date | span | count | milestone
    label: str                       # words for the evidence panel
    value: int
    owner: Optional[str] = None      # which side's team this belongs to (None = the game itself)
    cipher: Optional[str] = None

    def brief(self) -> dict:
        out = {"label": self.label, "value": self.value}
        if self.cipher:
            out["cipher"] = self.cipher
        return out


@dataclass(frozen=True)
class Evidence:
    kind: str
    a: Quantity
    b: Optional[Quantity]
    value: int                       # the number the two have in common (for a link, the larger)
    weight: float
    note: str = ""

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "value": self.value, "weight": round(self.weight, 3), "a": self.a.brief()}
        if self.b is not None:
            out["b"] = self.b.brief()
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class SideSignals:
    side: str
    score: float = 0.0
    comparisons: int = 0
    milestones: int = 0
    evidence: List[Evidence] = field(default_factory=list)

    def kind_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.evidence:
            out[e.kind] = out.get(e.kind, 0) + 1
        return out


@dataclass
class Signals:
    home: SideSignals
    away: SideSignals
    static_count: int = 0

    def side(self, which: str) -> SideSignals:
        return self.home if which == "home" else self.away

    @property
    def margin(self) -> float:
        return round(self.home.score - self.away.score, 6)


@dataclass
class TeamInputs:
    """Everything the generator reads about one team. Built by the hound from the facts and the stores; a test builds it by hand."""
    team: facts_mod.Team
    state: Optional[history.TeamState] = None


@dataclass
class GameInputs:
    date: str                        # the game's Eastern calendar date
    home: TeamInputs
    away: TeamInputs
    series: Optional[history.Series] = None     # a = home team, b = away team
    history_available: bool = False
    scope: str = ""                  # where the counts came from, in words (the evidence panel prints it)

    def team(self, side: str) -> TeamInputs:
        return self.home if side == "home" else self.away


# ---------------------------------------------------------------------------
# static quantities
# ---------------------------------------------------------------------------

def _ordinal(n: int) -> str:
    return gematria.ordinal_word(n)


def _poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def static_quantities(g: GameInputs, rules: Rules) -> List[Quantity]:
    out: List[Quantity] = []
    for side in SIDES:
        t = g.team(side).team
        for fname, text in t.name_texts():
            for cipher in rules.ciphers:
                v = gematria.cipher_value(text, cipher)
                out.append(Quantity(f"{side}.name.{fname}.{cipher}", "name", f"{text} ({fname}) = {v} {cipher}", v,
                                    owner=side, cipher=cipher))
        for i, (label, value) in enumerate(t.numbers):
            out.append(Quantity(f"{side}.fact.{i}", "fact", f"{t.name}: {label} = {value}", value, owner=side))
        if t.state_order:
            out.append(Quantity(f"{side}.state_order", "state",
                                f"{t.name}: {t.texts.get('state', 'its state')} is the {_ordinal(t.state_order)} state", t.state_order,
                                owner=side))
        for a in t.anchors:
            for unit in rules.span_units:
                if a.precision == "year" and unit != "year_gap":
                    continue
                for inclusive in (rules.span_inclusive if gematria.span_takes_inclusive(unit) else (False,)):
                    v = gematria.span(a.date if a.precision == "day" else f"{a.date}-01-01", g.date, unit, inclusive=inclusive)
                    if v > 0:
                        out.append(Quantity(f"{side}.span.{a.what}.{unit}.{int(inclusive)}", "span",
                                            f"{v} {gematria.span_label(unit, inclusive)}: {_poss(t.name)} {a.what} ({a.date}) and {g.date}",
                                            v, owner=side))
        st = g.team(side).state
        if st is not None:
            out.append(Quantity(f"{side}.game_number", "count", f"{_poss(t.name)} {_ordinal(st.n + 1)} game of the season",
                                st.n + 1, owner=side))
            if st.coach:
                out.append(Quantity(f"{side}.coach_game_number", "count",
                                    f"{_poss(st.coach)} {_ordinal(st.coach_n + 1)} game with {t.name} (in our store)",
                                    st.coach_n + 1, owner=side))
    if g.series is not None and g.history_available:
        out.append(Quantity("series.meeting_number", "count", f"their {_ordinal(g.series.meetings + 1)} meeting (in our store)",
                            g.series.meetings + 1))
    for name, v in gematria.date_numbers(g.date).items():
        out.append(Quantity(f"date.{name}", "date", f"{g.date}: {name} = {v}", v))
    weekday = gematria.weekday_name(g.date)
    for cipher in rules.ciphers:
        v = gematria.cipher_value(weekday, cipher)
        out.append(Quantity(f"date.weekday.{cipher}", "name", f"{weekday} = {v} {cipher}", v, cipher=cipher))
    return out


# ---------------------------------------------------------------------------
# milestones (one world each)
# ---------------------------------------------------------------------------

def _gap(label: str, last: Optional[str], g_date: str, qid: str, owner: str, out: List[Quantity],
         same_event_as: Optional[str] = None) -> None:
    """Days and whole weeks since ``last``. A venue-specific gap that is the very same event as the overall gap
    (``same_event_as``) is skipped, so one past game is never counted twice."""
    days = history.days_between(last, g_date)
    if days is None or days <= 0 or (same_event_as is not None and last == same_event_as):
        return
    out.append(Quantity(f"{qid}.days", "milestone", f"{days} days {label}", days, owner=owner))
    out.append(Quantity(f"{qid}.weeks", "milestone", f"{days // 7} weeks {label}", days // 7, owner=owner))


def milestones(g: GameInputs, winner: str) -> List[Quantity]:
    """The outcome-conditional counts of the world in which ``winner`` ("home" | "away") wins."""
    out: List[Quantity] = []
    loser = other(winner)
    w_in, l_in = g.team(winner), g.team(loser)
    wn, ln = w_in.team.name, l_in.team.name
    ws, ls = w_in.state, l_in.state
    if ws is not None:
        out.append(Quantity(f"ms.{winner}.wins", "milestone", f"{_poss(wn)} {_ordinal(ws.w + 1)} win of the season", ws.w + 1, owner=winner))
        venue_w = (ws.home_w if winner == "home" else ws.road_w) + 1
        out.append(Quantity(f"ms.{winner}.venue_wins", "milestone",
                            f"{_poss(wn)} {_ordinal(venue_w)} {'home' if winner == 'home' else 'road'} win", venue_w, owner=winner))
        streak = ws.streak_len + 1 if ws.streak_kind == "W" else 1
        out.append(Quantity(f"ms.{winner}.win_streak", "milestone", f"{wn} win streak reaches {streak}", streak, owner=winner))
        _gap(f"since {wn} last won", ws.last_win, g.date, f"ms.{winner}.since_win", winner, out)
        _gap(f"since {wn} last won {'at home' if winner == 'home' else 'on the road'}",
             ws.last_home_win if winner == "home" else ws.last_road_win, g.date, f"ms.{winner}.since_venue_win", winner, out,
             same_event_as=ws.last_win)
        if ws.coach:
            out.append(Quantity(f"ms.{winner}.coach_wins", "milestone",
                                f"{_poss(ws.coach)} {_ordinal(ws.coach_w + 1)} win with {wn} (in our store)", ws.coach_w + 1, owner=winner))
    if ls is not None:
        out.append(Quantity(f"ms.{loser}.losses", "milestone", f"{_poss(ln)} {_ordinal(ls.l + 1)} loss of the season", ls.l + 1, owner=loser))
        venue_l = (ls.home_l if loser == "home" else ls.road_l) + 1
        out.append(Quantity(f"ms.{loser}.venue_losses", "milestone",
                            f"{_poss(ln)} {_ordinal(venue_l)} {'home' if loser == 'home' else 'road'} loss", venue_l, owner=loser))
        lstreak = ls.streak_len + 1 if ls.streak_kind == "L" else 1
        out.append(Quantity(f"ms.{loser}.loss_streak", "milestone", f"{ln} loss streak reaches {lstreak}", lstreak, owner=loser))
        _gap(f"since {ln} last lost", ls.last_loss, g.date, f"ms.{loser}.since_loss", loser, out)
        _gap(f"since {ln} last lost {'at home' if loser == 'home' else 'on the road'}",
             ls.last_home_loss if loser == "home" else ls.last_road_loss, g.date, f"ms.{loser}.since_venue_loss", loser, out,
             same_event_as=ls.last_loss)
        if ls.coach:
            out.append(Quantity(f"ms.{loser}.coach_losses", "milestone",
                                f"{_poss(ls.coach)} {_ordinal(ls.coach_l + 1)} loss with {ln} (in our store)", ls.coach_l + 1, owner=loser))
    s = g.series
    if s is not None and g.history_available and s.meetings:
        wins = (s.a_wins if winner == "home" else s.b_wins) + 1
        out.append(Quantity(f"ms.{winner}.series_wins", "milestone", f"{_poss(wn)} {_ordinal(wins)} win in the series (in our store)", wins, owner=winner))
        _gap(f"since {wn} last beat {ln}", s.last_a_win if winner == "home" else s.last_b_win, g.date,
             f"ms.{winner}.since_series_win", winner, out)
    return out


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

KIND_BY_STATIC_GROUP = {"fact": "milestone_eq_fact_number", "name": "milestone_eq_name", "state": "milestone_eq_state", "date": "milestone_eq_date",
                        "span": "milestone_eq_span", "count": "milestone_eq_count"}


def _weight(rules: Rules, kind: str, value: int, *quantities: Optional[Quantity]) -> float:
    w = rules.kind_weights[kind]
    ciphers = [q.cipher for q in quantities if q is not None and q.cipher]
    if ciphers:
        w *= sum(rules.cipher_weights[c] for c in ciphers) / len(ciphers)
    if value in rules.special_numbers:
        w += rules.special_bonus
    return w


def _world(g: GameInputs, winner: str, static: Sequence[Quantity], rules: Rules) -> SideSignals:
    side = SideSignals(side=winner)
    ms = [q for q in milestones(g, winner) if rules.in_range(q.value)]
    side.milestones = len(ms)
    st = [q for q in static if rules.in_range(q.value)]
    seen = set()

    def add(kind: str, a: Quantity, b: Optional[Quantity], value: int, note: str = "") -> None:
        key = (kind, a.qid, b.qid if b else None)
        if key in seen:
            return
        seen.add(key)
        side.evidence.append(Evidence(kind, a, b, value, _weight(rules, kind, value, a, b), note))

    # a milestone of this world against the static pool
    for m in ms:
        for q in st:
            side.comparisons += 1
            if m.value == q.value:
                add(KIND_BY_STATIC_GROUP[q.group], m, q, m.value)
    # two milestones of the same world (an unordered pair, once)
    for i, m1 in enumerate(ms):
        for m2 in ms[i + 1:]:
            side.comparisons += 1
            if m1.value == m2.value:
                add("milestone_eq_milestone", m1, m2, m1.value)
    # links between any two numbers of the world (at least one a milestone)
    pool = ms + st
    ms_ids = {q.qid for q in ms}
    for x in pool:
        px = gematria.nth_prime(x.value) if x.value <= gematria.MAX_PRIME_INDEX else None
        tx = x.value * (x.value + 1) // 2
        for y in pool:
            if y is x or (x.qid not in ms_ids and y.qid not in ms_ids):
                continue
            side.comparisons += 2
            if px is not None and y.value == px:
                add("prime_link", x, y, y.value, f"{y.value} is the {_ordinal(x.value)} prime")
            if y.value == tx:
                add("triangular_link", x, y, y.value, f"{y.value} is the {_ordinal(x.value)} triangular number")
    # 33 and 47
    for m in ms:
        side.comparisons += 1
        if m.value in rules.special_numbers:
            add("special_33_47", m, None, m.value)
    # this side's own names against the date numbers (no result needed)
    own = [q for q in st if q.group == "name" and q.owner == winner]
    dates = [q for q in st if q.group == "date"]
    for q in own:
        for d in dates:
            side.comparisons += 1
            if q.value == d.value:
                add("own_name_eq_date", q, d, q.value)
    # THE HEADLINE. A post leads with one count ("Gibson's 9th win") and stacks other numbers that equal it. A count of this
    # world that at least ``headline_min_support`` other items equal is flagged once, and outweighs a loose match.
    support: dict = {}
    for e in side.evidence:
        for qty in (e.a, e.b):
            if qty is not None and qty.group == "milestone":
                support[qty.qid] = support.get(qty.qid, 0) + 1
    for m in ms:
        if m.qid.endswith((".days", ".weeks")):
            continue            # a gap since an event supports a headline; it is not itself one
        n = support.get(m.qid, 0)
        if n >= rules.headline_min_support:
            add("headline_milestone", m, None, m.value, f"{n} other numbers equal it")
    side.evidence.sort(key=lambda e: (-e.weight, KINDS.index(e.kind), e.a.qid, e.b.qid if e.b else ""))
    side.score = round(sum(e.weight for e in side.evidence), 6)
    return side


def generate(g: GameInputs, rules: Rules) -> Signals:
    """Both worlds for one game. Pure: same inputs and rules, same evidence, same score."""
    static = static_quantities(g, rules)
    return Signals(home=_world(g, "home", static, rules), away=_world(g, "away", static, rules),
                   static_count=len(static))
