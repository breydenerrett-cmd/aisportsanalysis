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

MLB has no season counts: its stored games begin mid-season (the seal), so ``GameInputs.season_counts`` is False and the win/loss,
home/road, game-number and head-to-head totals are not generated at all (a total since the floor is not the season's). Days since an
event, complete streaks, spans, ciphers and statehood are exact in any window and stay.

Missing data is silence: a fact or count that is not there makes no quantity, so it can make no match. Pure functions,
stdlib only.

RULES V2 AND THE STATIC BASIS. Under ``rules.static_fallback`` (rules_v2.json) a game whose outcome-conditional counts are thin
(a season a few days old, or a sport we hold no results for) is not passed as ``thin_data``/``no_history``. Each side is scored on
STATIC evidence instead: coincidences among the numbers that belong to that side's own team (its name, city, mascot, state,
founding spans, any stored number) and the numbers of the game date. Nothing in it depends on a result, so it exists for every
game with two names; it is the same arithmetic as the posts' cipher, statehood and date bullets, minus the counts we cannot make.
A game scored this way says so (``Signals.basis == "static"``) and the margin is judged against the game's own noise
(``Signals.noise_sd``), not a fixed number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.hounds.gematria import facts as facts_mod
from src.hounds.gematria import history
from src.hounds.gematria.rules import ALL_KINDS as KINDS, Rules
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
    basis: str = "season"            # "season" (outcome-conditional counts, rules v1 and v2) | "static" (rules v2's fallback)

    @property
    def noise_sd(self) -> float:
        """The chance scale of the margin: each match is a rare coincidence, so a side's score is a sum of independent small
        weights and the variance of the difference is the sum of the squared weights of ALL matches on both sides. A game with a
        big search and many matches has a wide noise band; a quiet game a narrow one."""
        return round(sum(e.weight ** 2 for side in (self.home, self.away) for e in side.evidence) ** 0.5, 6)

    @property
    def z(self) -> float:
        """The margin in units of its own noise (0 when nothing matched on either side)."""
        sd = self.noise_sd
        return round(abs(self.margin) / sd, 6) if sd > 0 else 0.0

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
    season_counts: bool = True       # False (MLB): the stored games start mid-season, so no season-to-date count is a true count

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
        if st is not None and g.season_counts:
            out.append(Quantity(f"{side}.game_number", "count", f"{_poss(t.name)} {_ordinal(st.n + 1)} game of the season",
                                st.n + 1, owner=side))
            if st.coach:
                out.append(Quantity(f"{side}.coach_game_number", "count",
                                    f"{_poss(st.coach)} {_ordinal(st.coach_n + 1)} game with {t.name} (in our store)",
                                    st.coach_n + 1, owner=side))
    if g.series is not None and g.history_available and g.season_counts:
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
    full = g.season_counts           # False: the window starts mid-season, so a total over it is not "the season's"

    def streak_is_whole(s) -> bool:
        """A streak is exact when it ends inside the window (an opposite result sits before it); one that runs back to the
        first stored game may have started earlier."""
        return full or s.streak_len < s.n

    if ws is not None:
        if full:
            out.append(Quantity(f"ms.{winner}.wins", "milestone", f"{_poss(wn)} {_ordinal(ws.w + 1)} win of the season", ws.w + 1, owner=winner))
            venue_w = (ws.home_w if winner == "home" else ws.road_w) + 1
            out.append(Quantity(f"ms.{winner}.venue_wins", "milestone",
                                f"{_poss(wn)} {_ordinal(venue_w)} {'home' if winner == 'home' else 'road'} win", venue_w, owner=winner))
        if ws.streak_kind != "W" or streak_is_whole(ws):
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
        if full:
            out.append(Quantity(f"ms.{loser}.losses", "milestone", f"{_poss(ln)} {_ordinal(ls.l + 1)} loss of the season", ls.l + 1, owner=loser))
            venue_l = (ls.home_l if loser == "home" else ls.road_l) + 1
            out.append(Quantity(f"ms.{loser}.venue_losses", "milestone",
                                f"{_poss(ln)} {_ordinal(venue_l)} {'home' if loser == 'home' else 'road'} loss", venue_l, owner=loser))
        if ls.streak_kind != "L" or streak_is_whole(ls):
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
        if full:
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


#: static quantity groups that belong to a team (a game-level date number belongs to neither side)
_OWNED_GROUPS = ("name", "fact", "state", "span")


def _source_key(q: Quantity) -> str:
    """Which fact a quantity was read from: all four ciphers of one text are ONE source ("home.name.city"), and every unit and
    both inclusive conventions of one dated anchor are ONE source ("home.span.state admitted"), so a fact never matches itself."""
    parts = q.qid.split(".")
    return ".".join(parts[:3]) if q.group in ("name", "span") else q.qid


def static_world(g: GameInputs, side: str, static: Sequence[Quantity], rules: Rules) -> SideSignals:
    """``side``'s STATIC evidence (rules v2): matches among the numbers of this side's own team and the game date. Needs no
    result. ``milestones`` is the count of the side's own static numbers (what the side brings to the search), so the
    "enough to compare" gate of v1 still means something."""
    out = SideSignals(side=side)
    st = [q for q in static if rules.in_range(q.value)]
    owned = [q for q in st if q.owner == side and q.group in _OWNED_GROUPS]
    dates = [q for q in st if q.group == "date"]
    out.milestones = len(owned)
    seen = set()

    def add(kind: str, a: Quantity, b: Optional[Quantity], value: int, note: str = "") -> None:
        key = (kind, a.qid, b.qid if b else None)
        if key in seen:
            return
        seen.add(key)
        out.evidence.append(Evidence(kind, a, b, value, _weight(rules, kind, value, a, b), note))

    for q in owned:
        for d in dates:                                  # a team's own number against the number of the date
            out.comparisons += 1
            if q.value == d.value:
                add("own_name_eq_date" if q.group == "name" else "static_eq_date", q, d, q.value)
    for i, q1 in enumerate(owned):                      # two different facts of the same team that agree
        for q2 in owned[i + 1:]:
            if _source_key(q1) == _source_key(q2):
                continue
            out.comparisons += 1
            if q1.value == q2.value:
                add("static_eq_static", q1, q2, q1.value)
    pool = owned + dates                                # prime / triangular links, at least one end the team's own
    owned_ids = {q.qid for q in owned}
    for x in pool:
        px = gematria.nth_prime(x.value) if x.value <= gematria.MAX_PRIME_INDEX else None
        tx = x.value * (x.value + 1) // 2
        for y in pool:
            if y is x or (x.qid not in owned_ids and y.qid not in owned_ids):
                continue
            out.comparisons += 2
            if px is not None and y.value == px:
                add("prime_link", x, y, y.value, f"{y.value} is the {_ordinal(x.value)} prime")
            if y.value == tx:
                add("triangular_link", x, y, y.value, f"{y.value} is the {_ordinal(x.value)} triangular number")
    for q in owned:
        out.comparisons += 1
        if q.value in rules.special_numbers:
            add("static_special_33_47", q, None, q.value)
    out.evidence.sort(key=lambda e: (-e.weight, KINDS.index(e.kind), e.a.qid, e.b.qid if e.b else ""))
    out.score = round(sum(e.weight for e in out.evidence), 6)
    return out


def generate(g: GameInputs, rules: Rules) -> Signals:
    """Both worlds for one game. Pure: same inputs and rules, same evidence, same score.

    Under ``rules.static_fallback`` a game with thin counts (either side under ``min_milestones_per_side``, or no stored
    results at all) is scored on its static evidence instead (``basis == "static"``); otherwise exactly rules v1."""
    static = static_quantities(g, rules)
    home, away = _world(g, "home", static, rules), _world(g, "away", static, rules)
    basis = "season"
    if rules.static_fallback and (not g.history_available
                                  or min(home.milestones, away.milestones) < rules.decision.min_milestones_per_side):
        home, away = static_world(g, "home", static, rules), static_world(g, "away", static, rules)
        basis = "static"
    return Signals(home=home, away=away, static_count=len(static), basis=basis)
