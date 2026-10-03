"""A written read of one UFC fight, built deterministically from one matchup fact sheet.

WHY THIS EXISTS
---------------
The UFC page used to take the betting favourite in every bout and call it a card.
The owner paused that on 2026-10-03: "Which fighter is fighting what fighter? What
are their weaknesses? What are their strengths? Any data or history or historical
matches or momentum? Are we doing actual work here?" The data layer
(`src/datasvc/ufc/matchup.py`) now holds the facts for each booked bout. This module
does the weighing out loud, in plain words, and shows its work.

WHAT IT IS, AND WHAT IT IS NOT
------------------------------
It is a DESCRIPTION of one fight built from the fields of one fact sheet. Nothing is
fetched, nothing is remembered about a fighter from outside the sheet, and no
sentence names a fact that has no path back to a field: every `evidence` entry is
`{path, label, value}`, the path is a dotted path into the sheet, and the value is
read from that path, never typed (`tests/test_ufc_read.py` resolves every one).

It is not a prediction and not advice. It names no pick, makes no profit claim and
no claim that any price is wrong, publishes no win probability of its own (the only
probabilities in it are the market's, labelled as such), and never touches a card,
a ledger or a record. We have not tested whether figures like these beat UFC
prices, and the read says so instead of letting a tidy paragraph suggest it. Where
the facts disagree with the price, or where the data behind them is thin, the read
says the likelier explanation is that the price knows more.

THIN DATA IS THE NORMAL CASE, AND IS SAID OUT LOUD
--------------------------------------------------
UFC fighters fight two or three times a year, so a store that starts in 2024 holds a
handful of fights for most of them (on the first backfill: a median of two). Every
figure carries its own sample (fights and fight minutes, from the sheet). A figure
below the data layer's floor (3 fights and 30 fight minutes for rates, 5 fights for
shares of results, 10 attempts for a takedown defence) is still shown, because a
small sample is information, but it is labelled thin, carries a caveat, and is
down-weighted to 0.3 of a fair one when the read ranks what stands out. A fight
where either fighter is thin says so at the top, and the market view then says the
price is more likely right than the read.

THE RULES AND THEIR THRESHOLDS
------------------------------
Each rule has a size (slight, moderate, large) and a sample level (thin, fair,
solid). Ranking multiplies the size (1, 2, 3) by the sample weight (0.3, 0.6, 1.0),
so a large gap on thin data ranks below a moderate gap on solid data. The
thresholds are design choices fixed in advance, never tuned against results, and
`docs/UFC_FIGHT_NIGHT.md` states each one with its reason. Where the data layer
already had a bar (a style label), the read uses the same number.

Pure. stdlib only, no I/O. The sheet is read, never modified. A rule that fails is
reported in `missing` and the rest of the read is still produced.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.datasvc import names as _names
from src.datasvc.ufc import features as _feat
from src.datasvc.ufc import matchup as _rules
from src.situation import record as _situation

READ_VERSION = 1

# The short "Situation" block (src/situation/): layoff, form, the card slot, the previous meeting
# and weight class, in sentences with their samples. Added only when the route hands a record in.
SITUATION_LABEL = ("Where each fighter stands going into this bout, from fights before it. A description "
                   "of the situation, not a forecast and not a claim that the price is wrong.")
SITUATION_LINES = 6

# ---------------------------------------------------------------------------
# Thresholds. Fixed in advance; each is justified in docs/UFC_FIGHT_NIGHT.md.
# ---------------------------------------------------------------------------

# The data layer's own floors, reused so the two can never drift apart.
MIN_FIGHTS_TIMED = _rules.MIN_FIGHTS_TIMED            # 3 fights ...
MIN_MINUTES_TIMED = _rules.MIN_MINUTES_TIMED          # ... and 30 fight minutes behind a rate
MIN_FIGHTS_RESULTS = _rules.MIN_FIGHTS_RESULTS        # 5 fights behind a share of results
MIN_ATTEMPTS_DEFENCE = _rules.HARD_TO_TAKE_DOWN_MIN_ATTEMPTS   # 10 takedown attempts behind a defence
# "Solid" is twice the floor.
SOLID_FIGHTS_TIMED, SOLID_MINUTES_TIMED = 2 * MIN_FIGHTS_TIMED, 2 * MIN_MINUTES_TIMED
SOLID_FIGHTS_RESULTS = 2 * MIN_FIGHTS_RESULTS
SOLID_ATTEMPTS_DEFENCE = 2 * MIN_ATTEMPTS_DEFENCE
# Fewer takedown attempts than this and a defence figure is not shown at all.
MIN_ATTEMPTS_SHOWN = 5
# Below these a figure is not shown at all, thin or not: one fight is an anecdote, and "finishes fights, 1 of 1"
# reads as a trait when it is a single result. The fighter's record and last fights are still printed as context,
# and the missing list says the figures were held back and why.
MIN_FIGHTS_SHOWN_TIMED = 2
MIN_FIGHTS_SHOWN_RESULTS = 3

# Striking. Net = significant strikes landed minus absorbed, per minute; the rule compares
# the two fighters' nets. The real backfill's middle half of fighters land 2.7 to 4.7 a
# minute and absorb 2.8 to 4.7, so a gap of 1.5 in the nets is a bit over half the spread
# between two ordinary fighters and 5.0 is far outside it.
STRIKING_NET = (1.5, 3.0, 5.0)
# Accuracy and defence: the middle half of fighters on file sit 0.43 to 0.53 and 0.49 to 0.58, so two fighters
# differ by about 0.10 on a typical pair. With a couple of hundred strikes behind each figure the noise in a
# gap between two fighters is itself about 0.05, so the first bar sits above that.
ACCURACY_GAP = (0.06, 0.10, 0.15)         # landed / attempted
DEFENCE_GAP = (0.06, 0.10, 0.14)          # share of thrown strikes that miss

# Grappling.
CONTROL_GAP = (0.10, 0.20, 0.30)          # share of fight time in control; middle half 0.06 to 0.25
TD_RATE_MIN = 1.5                         # takedowns landed per 15 minutes before a route is read
TD_RATE_HIGH = 2.5
TD_DEFENCE_LEAKY = 0.65                   # the bottom third of fighters stop this few or fewer
TD_DEFENCE_VERY_LEAKY = 0.50
TD_DEFENCE_STRONG = _rules.HARD_TO_TAKE_DOWN_DEFENCE       # 0.80, the style label's bar
TD_DEFENCE_ELITE = 0.90
SUBMISSION_ATTEMPTS = (_rules.SUBMISSION_ATTEMPTS_PER_15, 1.75, 2.5)
SUBMITTED_COUNT = (2, 3, 4)               # losses by submission among the fights on file

# Finishing and durability.
KNOCKDOWNS_LANDED = (_rules.KNOCKOUT_KNOCKDOWNS_PER_15, 1.25, 2.0)
KNOCKDOWNS_SUFFERED = (0.75, 1.25, 2.0)
KO_LOSSES_CHIN = 2                        # losses by KO or TKO that read as a chin question on their own
FINISH_RATE = (_rules.FINISHER_FINISH_RATE, 0.75, 0.90)
BEEN_FINISHED_RATE = (_rules.VULNERABLE_BEEN_FINISHED_RATE, 0.45, 0.60)

# Pace.
FIGHT_LENGTH_S = (240.0, 420.0, 600.0)    # gap in average fight time; only read for 5-round bouts
FIVE_ROUND_MIN_ROUNDS = 5
SHORT_AVERAGE_S = 600.0                   # an average under ten minutes: the late rounds are untested
DECISION_WINS_MIN = 2

# Physical, layoff, form, schedule.
LAYOFF_DAYS = (365, 545, 730)
SHORT_TURNAROUND_DAYS = 35
AGE_GAP = (4.0, 7.0, 10.0)
AGE_OLDER_MIN = 34.0                      # the older fighter must be at least this old for age to be read
# Reach and height, inches. Over the 1,667 bouts of the first backfill whose two fighters both list a reach, the
# typical gap is 2.0 inches (the top quarter is 4 or more, the top tenth 5.5 or more); for height the median is 2.0 and
# the top quarter 3 or more. The first bars sit near the 60th and 70th percentiles so a "slight" line is not on every card.
REACH_GAP = (3.0, 4.5, 6.0)
HEIGHT_GAP = (3.0, 4.0, 6.0)
SCHEDULE_GAP = (0.08, 0.15, 0.25)         # gap in the opponents' win rate at the time of each fight
WIN_RATE_GAP = (0.20, 0.35, 0.50)
WIN_STREAK = (3, 5, 7)
LOSS_STREAK = (2, 3, 4)
STREAK_FAIR_LENGTH = 4                    # a shorter streak is always a thin sample

# Ranking.
SIZE_RANK = {"slight": 1, "moderate": 2, "large": 3}
SIZES = ("slight", "moderate", "large")
THIN, FAIR, SOLID = "thin", "fair", "solid"
_LEVEL_RANK = {THIN: 0, FAIR: 1, SOLID: 2}
SAMPLE_WEIGHT = {THIN: 0.3, FAIR: 0.6, SOLID: 1.0}
HEADLINE_MIN_WEIGHT = 0.6                 # slight on fair data, or moderate on thin data
# Records, runs of form and the level of opposition describe where a fighter has been more than how this fight will be
# fought, and are the noisiest figures on a few fights. They headline only when nothing else clears the bar.
HEADLINE_LAST_FAMILIES = ("form", "schedule")
LEAN_MIN = 1.2                            # net weight before the read names a side against the price
MAX_ITEMS = 7                             # strengths or weaknesses kept per fighter
MAX_ROUTES = 3
MAX_SHARED_OPPONENTS = 5

LABEL = ("A written description of this fight built only from the figures on this page. "
         "It is not a prediction, not advice, and not a claim that any price is wrong.")
RESEARCH_NOTE = ("We have not tested whether figures like these beat UFC prices. Treat this as a "
                 "description of the fight, not as advice.")
MOVE_POINTS = 1.0                         # margin-free points before a line move is worth a sentence

METHOD_WORDS = {
    "KO_TKO": "knockout or TKO", "SUB": "submission", "DEC_UNANIMOUS": "unanimous decision",
    "DEC_SPLIT": "split decision", "DEC_MAJORITY": "majority decision", "DECISION": "decision",
    "DQ": "disqualification", "OTHER": "another method", "DRAW": "a draw", "NC": "a no contest",
}

_TOPIC = {
    "striking_net": "in the striking", "striking_accuracy": "in striking accuracy",
    "striking_defence": "in striking defence", "takedown_open": "in the takedown game",
    "takedown_closed": "in the takedown game", "control": "in control on the mat",
    "knockdown_power": "in knockout power", "chin": "in durability", "finisher": "in finishing",
    "finished_often": "in durability", "submission_threat": "in submissions",
    "been_submitted": "in submission defence", "fight_length": "in how deep the fights go",
    "long_layoff": "in time since the last UFC fight", "age": "in age", "reach": "in reach", "height": "in height",
    "schedule": "in the level of opposition", "results": "in results on file",
    "win_streak": "in momentum", "loss_streak": "in momentum",
}

# Plain words for the figures the read can use, for the list of what is missing.
_FIGURE_WORDS = {
    "sig_strikes_landed_per_min": "strikes landed per minute",
    "sig_strikes_absorbed_per_min": "strikes absorbed per minute",
    "sig_strike_accuracy": "striking accuracy", "sig_strike_defence": "striking defence",
    "knockdowns_landed_per_15": "knockdowns scored", "knockdowns_suffered_per_15": "knockdowns suffered",
    "takedowns_landed_per_15": "takedowns landed", "takedown_accuracy": "takedown accuracy",
    "takedown_defence": "takedown defence", "control_time_share": "control time",
    "submission_attempts_per_15": "submission attempts", "finish_rate": "finishing rate",
    "been_finished_rate": "been-finished rate", "distance_rate": "share of fights going the distance",
    "average_fight_time_s": "average fight time", "strength_of_schedule": "strength of schedule",
    "days_since_last_fight": "time since the last fight", "age_years": "age", "height_in": "height",
    "reach_in": "reach", "win_rate": "win rate", "career_record_incl_non_ufc": "overall record",
}
_FIGHT_DERIVED = frozenset(k for k in _FIGURE_WORDS
                           if k not in ("age_years", "height_in", "reach_in", "career_record_incl_non_ufc"))
_PHYSICAL = ("height_in", "reach_in", "age_years")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def resolve_path(payload: Any, path: str) -> Tuple[bool, Any]:
    """`(found, value)` for a dotted path with integer list indexes."""
    node = payload
    for token in str(path).split("."):
        if isinstance(node, dict):
            if token not in node:
                return False, None
            node = node[token]
        elif isinstance(node, (list, tuple)):
            try:
                node = node[int(token)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, node


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _fmt(value: Any, places: int = 1) -> str:
    number = _num(value)
    return "unknown" if number is None else f"{number:.{places}f}"


def _pct(value: Any, places: int = 0) -> str:
    number = _num(value)
    return "unknown" if number is None else f"{number * 100:.{places}f}%"


def _signed(value: Any, places: int = 1) -> str:
    number = _num(value)
    return "unknown" if number is None else f"{number:+.{places}f}"


def _plural(n: Any, word: str, many: Optional[str] = None) -> str:
    n = int(n)
    return f"{n} {word}" if n == 1 else f"{n} {many or word + 's'}"


def _minutes(value: Any) -> str:
    n = _num(value) or 0.0
    return f"{n:.0f} minute" + ("" if round(n) == 1 else "s")


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _join(items: Sequence[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _date(text: Any) -> str:
    return str(text)[:10] if isinstance(text, str) and text else "an unknown date"


def other(side: str) -> str:
    return "b" if side == "a" else "a"


def _size(gap: Optional[float], thresholds: Sequence[float]) -> Optional[str]:
    """The size a gap earns against (slight, moderate, large) thresholds, or None below the first."""
    if gap is None:
        return None
    gap = round(abs(gap), 6)
    out = None
    for label, bar in zip(SIZES, thresholds):
        if gap >= bar:
            out = label
    return out


def _weight(size: str, level: str) -> float:
    return round(SIZE_RANK[size] * SAMPLE_WEIGHT[level], 2)


def _plain(text: Any) -> str:
    """A data-layer reason as a plain sentence: no field names, no `as_of`."""
    out = str(text or "not computed")
    out = out.replace("before as_of", "before this fight").replace("as_of", "the fight date")
    return re.sub(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", lambda m: m.group(0).replace("_", " "), out)


def _poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

def _fights_minutes(fig: dict) -> Tuple[int, float]:
    return int(_num(fig.get("fights")) or 0), float(_num(fig.get("minutes")) or 0.0)


def _weakest(figs: Sequence[dict]) -> Tuple[int, float]:
    """(fights, minutes) of the thinnest figure among `figs`."""
    pairs = [_fights_minutes(f) for f in figs]
    return min(p[0] for p in pairs), min(p[1] for p in pairs)


def _level_timed(figs: Sequence[dict]) -> str:
    fights, minutes = _weakest(figs)
    if fights < MIN_FIGHTS_TIMED or minutes < MIN_MINUTES_TIMED:
        return THIN
    if fights >= SOLID_FIGHTS_TIMED and minutes >= SOLID_MINUTES_TIMED:
        return SOLID
    return FAIR


def _level_results(figs: Sequence[dict]) -> str:
    fights = min(_fights_minutes(f)[0] for f in figs)
    if fights < MIN_FIGHTS_RESULTS:
        return THIN
    return SOLID if fights >= SOLID_FIGHTS_RESULTS else FAIR


def _worst(levels: Sequence[str]) -> str:
    return min(levels, key=lambda lv: _LEVEL_RANK[lv]) if levels else FAIR


# ---------------------------------------------------------------------------
# Context: the sheet, read once
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, sheet: dict, now: Any = None):
        self.sheet = sheet or {}
        self.features = self.sheet.get("features") or {"a": {}, "b": {}}
        self.full = {}
        for side, fallback in (("a", "Fighter A"), ("b", "Fighter B")):
            self.full[side] = str((self.sheet.get(side) or {}).get("name") or fallback)
        # FULL NAMES EVERYWHERE. A last name is not reliable: ESPN lists some fighters family name first (Wang Cong,
        # whom the card calls Wang), some names carry particles (Rafael Dos Anjos) or suffixes, and two fighters can
        # share one (two Silvas). A wrong short name on a fighter's own page is worse than a longer sentence.
        self.short = dict(self.full)
        self.bout = self.sheet.get("bout") or {}
        self.odds = self.sheet.get("odds")
        self.as_of = self.sheet.get("as_of")
        self.now = _feat.parse_instant(now) if now is not None else None
        # With no booked bout the sheet is measured at a date, not at a fight, and the words say which.
        self.before = "before this bout" if self.bout else f"before {_date(self.as_of)}"
        self.on_file = "On file before this fight" if self.bout else f"On file as of {_date(self.as_of)}"

    # -- figures ---------------------------------------------------------

    def fig(self, side: str, name: str) -> dict:
        return ((self.features.get(side) or {}).get("figures") or {}).get(name) or {}

    def val(self, side: str, name: str) -> Optional[float]:
        return _num(self.fig(side, name).get("value"))

    def rec(self, side: str) -> dict:
        return (self.features.get(side) or {}).get("record") or {}

    def sample(self, side: str) -> dict:
        return (self.features.get(side) or {}).get("sample") or {}

    # -- evidence --------------------------------------------------------

    def ev(self, path: str, label: str) -> Optional[dict]:
        """An evidence entry whose value is read from the sheet, never typed, so the path
        and the value cannot disagree."""
        found, value = resolve_path(self.sheet, path)
        if not found or value is None or isinstance(value, (dict, list)):
            return None
        return {"path": path, "label": label, "value": value}

    def derived(self, path: str, label: str, value: Any) -> Optional[dict]:
        """An entry for a number this module worked out from the field at `path`."""
        found, _ = resolve_path(self.sheet, path)
        if not found or value is None:
            return None
        return {"path": path, "label": label, "value": value, "derived": True}

    def fig_ev(self, side: str, names: Sequence[str], labels: Sequence[str]) -> List[Optional[dict]]:
        """The value of each figure, then the fights and minutes of the thinnest one."""
        who = self.short[side]
        out = [self.ev(f"features.{side}.figures.{n}.value", f"{who} {lab}") for n, lab in zip(names, labels)]
        thin = min(names, key=lambda n: (_fights_minutes(self.fig(side, n)), n))
        out.append(self.ev(f"features.{side}.figures.{thin}.fights", f"{who} fights behind this"))
        out.append(self.ev(f"features.{side}.figures.{thin}.minutes", f"{who} fight minutes behind this"))
        return out

    def shown(self, pairs: Sequence[Tuple[str, str]], results: bool = False) -> bool:
        """True when every (side, figure) has at least the fights a figure needs to be shown at all."""
        floor = MIN_FIGHTS_SHOWN_RESULTS if results else MIN_FIGHTS_SHOWN_TIMED
        return all(_fights_minutes(self.fig(side, name))[0] >= floor for side, name in pairs)

    # -- sample text -----------------------------------------------------

    def own_clause(self, side: str, names: Sequence[str]) -> str:
        fights, minutes = _weakest([self.fig(side, n) for n in names])
        return f"(on file: {_plural(fights, 'fight')}, {_minutes(minutes)})"

    def pair_clause(self, names: Sequence[str]) -> str:
        parts = []
        for side in ("a", "b"):
            fights, minutes = _weakest([self.fig(side, n) for n in names])
            parts.append(f"{self.short[side]} {_plural(fights, 'fight')}, {_minutes(minutes)}")
        return "(on file: " + "; ".join(parts) + ")"

    def thin_who(self, names: Sequence[str], sides: Sequence[str] = ("a", "b"),
                 results: bool = False) -> List[str]:
        out = []
        for side in sides:
            fights, minutes = _weakest([self.fig(side, n) for n in names])
            thin = fights < MIN_FIGHTS_RESULTS if results else (
                fights < MIN_FIGHTS_TIMED or minutes < MIN_MINUTES_TIMED)
            if thin:
                out.append(self.short[side])
        return out


def _caveat_thin(who: Sequence[str], results: bool = False, extra: str = "") -> str:
    if not who:
        return extra
    bar = (f"fewer than {MIN_FIGHTS_RESULTS} fights" if results
           else f"fewer than {MIN_FIGHTS_TIMED} fights or {MIN_MINUTES_TIMED:g} fight minutes")
    text = (f"Thin sample: {_join(list(who))} {'has' if len(who) == 1 else 'have'} {bar} behind this, "
            "so one more fight could move it a long way.")
    return (text + " " + extra).strip()


def _dedupe(evidence: Sequence[Optional[dict]]) -> List[dict]:
    """Each entry once. A worked-out number shares its path with the field it came from, so the two are
    told apart by the derived flag and the label, not by the path alone."""
    seen, out = set(), []
    for e in evidence:
        if not e:
            continue
        key = (e["path"], True, e.get("label")) if e.get("derived") else (e["path"], False, None)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _sample(fights: Optional[int], minutes: Optional[float]) -> Optional[dict]:
    """The fights and fight minutes behind an item. None when the item has no sample (a height, an
    age); minutes is None for a count of results, where fight minutes are not what is counted."""
    if fights is None:
        return None
    return {"fights": int(fights), "minutes": None if minutes is None else round(float(minutes), 2)}


def _item(trait: str, family: str, side: str, kind: str, size: str, level: str, sentence: str,
          evidence: Sequence[Optional[dict]], sample: Optional[Tuple[Optional[int], Optional[float]]], *,
          caveat: str = "", pair: Optional[str] = None) -> dict:
    return {
        "trait": trait, "family": family, "kind": kind, "size": size, "sentence": sentence,
        "evidence": _dedupe(evidence),
        "sample": _sample(*sample) if sample else None,
        "sample_level": level, "thin": level == THIN, "down_weighted": level == THIN,
        "caveat": caveat, "weight": _weight(size, level),
        "_side": side, "_pair": pair,
    }


def _compare(ctx: _Ctx, name: str, thresholds: Sequence[float], *, higher_better: bool = True,
             results: bool = False) -> Optional[dict]:
    va, vb = ctx.val("a", name), ctx.val("b", name)
    if va is None or vb is None or not ctx.shown([("a", name), ("b", name)], results):
        return None
    gap = round(va - vb, 6)
    size = _size(gap, thresholds)
    if size is None:
        return None
    w = "a" if (gap > 0) == higher_better else "b"
    loser = other(w)
    return {"w": w, "l": loser, "wv": ctx.val(w, name), "lv": ctx.val(loser, name), "gap": abs(gap), "size": size}


# ---------------------------------------------------------------------------
# Rules. Each takes the context and returns a list of items. A pair rule returns two items
# for one comparison (a strength for the better side, a weakness for the other); an absolute
# rule returns one.
# ---------------------------------------------------------------------------

def _r_striking_net(ctx: _Ctx) -> List[dict]:
    names = ("sig_strikes_landed_per_min", "sig_strikes_absorbed_per_min")
    net = {}
    for side in ("a", "b"):
        landed, absorbed = ctx.val(side, names[0]), ctx.val(side, names[1])
        if landed is None or absorbed is None:
            return []
        net[side] = (landed, absorbed, round(landed - absorbed, 4))
    gap = round(net["a"][2] - net["b"][2], 6)
    size = _size(gap, STRIKING_NET)
    if size is None:
        return []
    w = "a" if gap > 0 else "b"
    lo = other(w)
    if not ctx.shown([(s, n) for s in ("a", "b") for n in names]):
        return []
    figs = [ctx.fig(s, n) for s in ("a", "b") for n in names]
    level = _level_timed(figs)
    W, L = ctx.short[w], ctx.short[lo]
    wl, wa, wn = net[w]
    ll, la, ln = net[lo]
    detail_w = f"landing {_fmt(wl)}, absorbing {_fmt(wa)}"
    detail_l = f"landing {_fmt(ll)}, absorbing {_fmt(la)}"
    clause = ctx.pair_clause(names)
    labels = ("significant strikes landed per minute", "significant strikes absorbed per minute")
    evidence = []
    for side in ("a", "b"):
        evidence += ctx.fig_ev(side, names, labels)
        evidence.append(ctx.derived(f"features.{side}.figures.{names[0]}.value",
                                    f"{ctx.short[side]} net significant strikes per minute (landed minus absorbed)",
                                    net[side][2]))
    caveat = _caveat_thin(ctx.thin_who(names), extra="Strikes are not adjusted for who the opponents were.")
    who = _item("striking_net", "striking", w, "strength", size, level,
                f"{W} out-strikes {L} on the feet, a net of {_signed(wn)} significant strikes a minute "
                f"({detail_w}) against {_signed(ln)} for {L} ({detail_l}) {clause}.",
                evidence, _weakest(figs), caveat=caveat, pair="striking_net")
    lose = _item("striking_net", "striking", lo, "weakness", size, level,
                 f"{L} gets the worse of the striking, a net of {_signed(ln)} significant strikes a minute "
                 f"({detail_l}) against {_signed(wn)} for {W} ({detail_w}) {clause}.",
                 evidence, _weakest(figs), caveat=caveat, pair="striking_net")
    return [who, lose]


def _r_striking_accuracy(ctx: _Ctx) -> List[dict]:
    name = "sig_strike_accuracy"
    cmp = _compare(ctx, name, ACCURACY_GAP)
    if not cmp:
        return []
    w, lo = cmp["w"], cmp["l"]
    W, L = ctx.short[w], ctx.short[lo]
    level = _level_timed([ctx.fig("a", name), ctx.fig("b", name)])
    evidence = ctx.fig_ev("a", (name,), ("significant strike accuracy",)) + \
        ctx.fig_ev("b", (name,), ("significant strike accuracy",))
    clause = ctx.pair_clause((name,))
    caveat = _caveat_thin(ctx.thin_who((name,)))
    sample = _weakest([ctx.fig("a", name), ctx.fig("b", name)])
    return [
        _item("striking_accuracy", "striking", w, "strength", cmp["size"], level,
              f"{W} is the more accurate striker, with {_pct(cmp['wv'])} of significant strikes thrown landing "
              f"against {_pct(cmp['lv'])} for {L} {clause}.", evidence, sample, caveat=caveat, pair="striking_accuracy"),
        _item("striking_accuracy", "striking", lo, "weakness", cmp["size"], level,
              f"{L} is the less accurate striker, with {_pct(cmp['lv'])} of significant strikes thrown landing "
              f"against {_pct(cmp['wv'])} for {W} {clause}.", evidence, sample, caveat=caveat, pair="striking_accuracy"),
    ]


def _r_striking_defence(ctx: _Ctx) -> List[dict]:
    name = "sig_strike_defence"
    cmp = _compare(ctx, name, DEFENCE_GAP)
    if not cmp:
        return []
    w, lo = cmp["w"], cmp["l"]
    W, L = ctx.short[w], ctx.short[lo]
    level = _level_timed([ctx.fig("a", name), ctx.fig("b", name)])
    evidence = ctx.fig_ev("a", (name,), ("share of strikes thrown at the fighter that miss",)) + \
        ctx.fig_ev("b", (name,), ("share of strikes thrown at the fighter that miss",))
    clause = ctx.pair_clause((name,))
    caveat = _caveat_thin(ctx.thin_who((name,)))
    sample = _weakest([ctx.fig("a", name), ctx.fig("b", name)])
    return [
        _item("striking_defence", "striking", w, "strength", cmp["size"], level,
              f"{W} is harder to hit, with {_pct(cmp['wv'])} of the significant strikes thrown at {W} missing "
              f"against {_pct(cmp['lv'])} for {L} {clause}.", evidence, sample, caveat=caveat, pair="striking_defence"),
        _item("striking_defence", "striking", lo, "weakness", cmp["size"], level,
              f"{L} is easier to hit, with only {_pct(cmp['lv'])} of the significant strikes thrown at {L} missing "
              f"against {_pct(cmp['wv'])} for {W} {clause}.", evidence, sample, caveat=caveat, pair="striking_defence"),
    ]


def _r_takedowns(ctx: _Ctx) -> List[dict]:
    out = []
    for att in ("a", "b"):
        dfn = other(att)
        rate_fig, def_fig = ctx.fig(att, "takedowns_landed_per_15"), ctx.fig(dfn, "takedown_defence")
        rate, defence = _num(rate_fig.get("value")), _num(def_fig.get("value"))
        attempts = _num(def_fig.get("den")) or 0.0
        if rate is None or defence is None or rate < TD_RATE_MIN or attempts < MIN_ATTEMPTS_SHOWN:
            continue
        if not ctx.shown([(att, "takedowns_landed_per_15"), (dfn, "takedown_defence")]):
            continue
        level = _level_timed([rate_fig, def_fig])
        if attempts < MIN_ATTEMPTS_DEFENCE:
            level = THIN
        elif level == SOLID and attempts < SOLID_ATTEMPTS_DEFENCE:
            level = FAIR
        X, Y = ctx.short[att], ctx.short[dfn]
        n_att = f"{attempts:.0f}"
        sample = _weakest([rate_fig, def_fig])
        evidence = [
            ctx.ev(f"features.{att}.figures.takedowns_landed_per_15.value", f"{X} takedowns landed per 15 minutes"),
            ctx.ev(f"features.{att}.figures.takedowns_landed_per_15.fights", f"{X} fights behind this"),
            ctx.ev(f"features.{att}.figures.takedowns_landed_per_15.minutes", f"{X} fight minutes behind this"),
            ctx.ev(f"features.{dfn}.figures.takedown_defence.value", f"{Y} takedown defence"),
            ctx.ev(f"features.{dfn}.figures.takedown_defence.den", f"takedowns attempted against {Y}"),
            ctx.ev(f"features.{dfn}.figures.takedown_defence.fights", f"{Y} fights behind this"),
        ]
        x_fights, x_minutes = _fights_minutes(rate_fig)
        clause = (f"(on file: {X} {_plural(x_fights, 'fight')}, {_minutes(x_minutes)}; "
                  f"{Y} {_plural(_fights_minutes(def_fig)[0], 'fight')}, {n_att} takedown attempts against {Y})")
        caveat_extra = ("A takedown defence rests on the attempts made against the fighter, "
                        f"and under {MIN_ATTEMPTS_DEFENCE} attempts is thin.") if attempts < MIN_ATTEMPTS_DEFENCE else ""
        who = ctx.thin_who(("takedowns_landed_per_15",), (att,)) + ctx.thin_who(("takedown_defence",), (dfn,))
        if attempts < MIN_ATTEMPTS_DEFENCE and Y not in who:
            who.append(Y)
        caveat = _caveat_thin(sorted(set(who), key=who.index), extra=caveat_extra)
        stopped = _pct(defence)
        if defence <= TD_DEFENCE_LEAKY:
            points = 1 + int(rate >= TD_RATE_HIGH) + int(defence <= TD_DEFENCE_VERY_LEAKY)
            size = SIZES[points - 1]
            pair = f"takedown_open_{att}"
            out.append(_item(
                "takedown_open", "grappling", att, "strength", size, level,
                f"{X} can take {Y} down, landing {_fmt(rate)} takedowns per 15 minutes while {Y} has stopped "
                f"{stopped} of {n_att} attempts against {Y} {clause}.",
                evidence, sample, caveat=caveat, pair=pair))
            out.append(_item(
                "takedown_open", "grappling", dfn, "weakness", size, level,
                f"{Y} is easy to take down, having stopped {stopped} of {n_att} takedown attempts, "
                f"and {X} lands {_fmt(rate)} takedowns per 15 minutes {clause}.",
                evidence, sample, caveat=caveat, pair=pair))
        elif defence >= TD_DEFENCE_STRONG:
            size = "moderate" if (defence >= TD_DEFENCE_ELITE and rate >= TD_RATE_HIGH) else "slight"
            pair = f"takedown_closed_{att}"
            out.append(_item(
                "takedown_closed", "grappling", dfn, "strength", size, level,
                f"{Y} is hard to take down, having stopped {stopped} of {n_att} takedown attempts, "
                f"against {_poss(X)} {_fmt(rate)} landed per 15 minutes {clause}.",
                evidence, sample, caveat=caveat, pair=pair))
            out.append(_item(
                "takedown_closed", "grappling", att, "weakness", size, level,
                f"{_poss(X)} takedown game meets a strong defence, as {Y} has stopped {stopped} of "
                f"{n_att} takedown attempts {clause}.",
                evidence, sample, caveat=caveat, pair=pair))
    return out


def _r_control(ctx: _Ctx) -> List[dict]:
    name = "control_time_share"
    cmp = _compare(ctx, name, CONTROL_GAP)
    if not cmp:
        return []
    w, lo = cmp["w"], cmp["l"]
    W, L = ctx.short[w], ctx.short[lo]
    level = _level_timed([ctx.fig("a", name), ctx.fig("b", name)])
    evidence = ctx.fig_ev("a", (name,), ("share of fight time in control",)) + \
        ctx.fig_ev("b", (name,), ("share of fight time in control",))
    clause = ctx.pair_clause((name,))
    caveat = _caveat_thin(ctx.thin_who((name,)))
    sample = _weakest([ctx.fig("a", name), ctx.fig("b", name)])
    return [
        _item("control", "grappling", w, "strength", cmp["size"], level,
              f"{W} controls the fight for longer, spending {_pct(cmp['wv'])} of fight time in control "
              f"against {_pct(cmp['lv'])} for {L} {clause}.", evidence, sample, caveat=caveat, pair="control"),
        _item("control", "grappling", lo, "weakness", cmp["size"], level,
              f"{L} spends less of the fight in control, {_pct(cmp['lv'])} of fight time "
              f"against {_pct(cmp['wv'])} for {W} {clause}.", evidence, sample, caveat=caveat, pair="control"),
    ]


def _opponent_of(ctx: _Ctx, side: str, name: str) -> Optional[dict]:
    """The other fighter's figure `name` when it can be printed beside this fighter's (it has a value and enough
    fights to be shown), so a one-sided strength reads as a difference and not as a lone number."""
    foe = other(side)
    fig = ctx.fig(foe, name)
    if _num(fig.get("value")) is None or not ctx.shown([(foe, name)]):
        return None
    return fig


def _r_knockdown_power(ctx: _Ctx) -> List[dict]:
    out = []
    name = "knockdowns_landed_per_15"
    for side in ("a", "b"):
        fig = ctx.fig(side, name)
        value = _num(fig.get("value"))
        size = _size(value, KNOCKDOWNS_LANDED)
        if value is None or size is None or not ctx.shown([(side, name)]):
            continue
        X, Y = ctx.short[side], ctx.short[other(side)]
        ofig = _opponent_of(ctx, side, name)
        figs = [fig] + ([ofig] if ofig else [])
        against = f" against {_fmt(ofig.get('value'))} for {Y}" if ofig else ""
        clause = ctx.pair_clause((name,)) if ofig else ctx.own_clause(side, (name,))
        evidence = ctx.fig_ev(side, (name,), ("knockdowns scored per 15 minutes",))
        if ofig:
            evidence += ctx.fig_ev(other(side), (name,), ("knockdowns scored per 15 minutes",))
        out.append(_item(
            "knockdown_power", "finishing", side, "strength", size, _level_timed(figs),
            f"{X} scores knockdowns, {_fmt(value)} per 15 minutes{against} {clause}.",
            evidence, _weakest(figs),
            caveat=_caveat_thin(ctx.thin_who((name,), ("a", "b") if ofig else (side,)))))
    return out


def _r_chin(ctx: _Ctx) -> List[dict]:
    out = []
    name = "knockdowns_suffered_per_15"
    for side in ("a", "b"):
        fig = ctx.fig(side, name)
        value = _num(fig.get("value"))
        rec = ctx.rec(side)
        ko_losses = int((rec.get("losses_by_method") or {}).get("ko_tko") or 0)
        fights_on_file = int(rec.get("fights") or 0)
        rate_size = _size(value, KNOCKDOWNS_SUFFERED) if ctx.shown([(side, name)]) else None
        count_size = "slight" if (ko_losses >= KO_LOSSES_CHIN and fights_on_file >= MIN_FIGHTS_SHOWN_RESULTS) else None
        size = rate_size or count_size
        if size is None:
            continue
        X, Y = ctx.short[side], ctx.short[other(side)]
        fights = int(rec.get("fights") or 0)
        parts, evidence, level_parts = [], [], []
        ofig = _opponent_of(ctx, side, name) if rate_size else None
        rate_figs = [fig] + ([ofig] if ofig else [])
        if rate_size:
            against = f" against {_fmt(ofig.get('value'))} for {Y}" if ofig else ""
            clause = ctx.pair_clause((name,)) if ofig else ctx.own_clause(side, (name,))
            parts.append(f"{X} has been knocked down {_fmt(value)} times per 15 minutes{against} {clause}")
            evidence += ctx.fig_ev(side, (name,), ("knockdowns suffered per 15 minutes",))
            if ofig:
                evidence += ctx.fig_ev(other(side), (name,), ("knockdowns suffered per 15 minutes",))
            level_parts.append(_level_timed(rate_figs))
        if ko_losses:
            lead = f"{X} has lost by KO or TKO {_times(ko_losses)} in {_plural(fights, 'fight')} on file"
            parts.append(lead if not parts else f"and has lost by KO or TKO {_times(ko_losses)} in {_plural(fights, 'fight')} on file")
            evidence.append(ctx.ev(f"features.{side}.record.losses_by_method.ko_tko", f"{X} losses by KO or TKO"))
            evidence.append(ctx.ev(f"features.{side}.record.fights", f"{X} fights on file"))
            level_parts.append(FAIR if fights >= MIN_FIGHTS_RESULTS else THIN)
        level = _worst(level_parts)
        sentence = parts[0] if len(parts) == 1 else f"{parts[0]}, {parts[1]}"
        results_thin = [X] if (fights < MIN_FIGHTS_RESULTS and ko_losses) else []
        who = ctx.thin_who((name,), ("a", "b") if ofig else (side,)) if rate_size else []
        caveat = _caveat_thin(list(dict.fromkeys(who + results_thin)))
        out.append(_item("chin", "finishing", side, "weakness", size, level, sentence + ".", evidence,
                         _weakest(rate_figs) if rate_size else (fights, None), caveat=caveat))
    return out


def _finish_pair(ctx: _Ctx, name: str, thresholds: Sequence[float], trait: str, kind: str,
                 phrase: str, noun: str) -> List[dict]:
    out = []
    for side in ("a", "b"):
        fig = ctx.fig(side, name)
        value = _num(fig.get("value"))
        size = _size(value, thresholds)
        if value is None or size is None or not ctx.shown([(side, name)], results=True):
            continue
        level = _level_results([fig])
        X = ctx.short[side]
        num, den = int(_num(fig.get("num")) or 0), int(_num(fig.get("den")) or 0)
        evidence = [ctx.ev(f"features.{side}.figures.{name}.value", f"{X} {noun}"),
                    ctx.ev(f"features.{side}.figures.{name}.num", f"{X} {noun}, fights counted"),
                    ctx.ev(f"features.{side}.figures.{name}.den", f"{X} fights with a recorded method"),
                    ctx.ev(f"features.{side}.figures.{name}.fights", f"{X} fights behind this")]
        thin = [X] if level == THIN else []
        out.append(_item(trait, "finishing", side, kind, size, level,
                         f"{X} {phrase.format(num=num, den=den)} (on file: {_plural(den, 'fight')} with a recorded method).",
                         evidence, _fights_minutes(fig), caveat=_caveat_thin(thin, results=True)))
    return out


def _r_finisher(ctx: _Ctx) -> List[dict]:
    return _finish_pair(ctx, "finish_rate", FINISH_RATE, "finisher", "strength",
                        "finishes fights, with {num} of {den} ending in a finishing win by KO, TKO or submission",
                        "finishing rate")


def _r_finished_often(ctx: _Ctx) -> List[dict]:
    return _finish_pair(ctx, "been_finished_rate", BEEN_FINISHED_RATE, "finished_often", "weakness",
                        "gets finished, with {num} of {den} ending in a loss by KO, TKO or submission",
                        "been-finished rate")


def _r_submissions(ctx: _Ctx) -> List[dict]:
    out = []
    name = "submission_attempts_per_15"
    for side in ("a", "b"):
        fig = ctx.fig(side, name)
        value = _num(fig.get("value"))
        size = _size(value, SUBMISSION_ATTEMPTS)
        X, Y = ctx.short[side], ctx.short[other(side)]
        if value is not None and size is not None and ctx.shown([(side, name)]):
            ofig = _opponent_of(ctx, side, name)
            figs = [fig] + ([ofig] if ofig else [])
            against = f" against {_fmt(ofig.get('value'))} for {Y}" if ofig else ""
            clause = ctx.pair_clause((name,)) if ofig else ctx.own_clause(side, (name,))
            evidence = ctx.fig_ev(side, (name,), ("submission attempts per 15 minutes",))
            if ofig:
                evidence += ctx.fig_ev(other(side), (name,), ("submission attempts per 15 minutes",))
            out.append(_item(
                "submission_threat", "grappling", side, "strength", size, _level_timed(figs),
                f"{X} hunts submissions, throwing {_fmt(value)} attempts per 15 minutes{against} {clause}.",
                evidence, _weakest(figs),
                caveat=_caveat_thin(ctx.thin_who((name,), ("a", "b") if ofig else (side,)))))
        rec = ctx.rec(side)
        count = int((rec.get("losses_by_method") or {}).get("submission") or 0)
        fights = int(rec.get("fights") or 0)
        size = _size(count, SUBMITTED_COUNT)
        if size and fights >= MIN_FIGHTS_SHOWN_RESULTS:
            level = FAIR if fights >= MIN_FIGHTS_RESULTS else THIN
            out.append(_item(
                "been_submitted", "grappling", side, "weakness", size, level,
                f"{X} has lost by submission {_times(count)} in {_plural(fights, 'fight')} on file.",
                [ctx.ev(f"features.{side}.record.losses_by_method.submission", f"{X} losses by submission"),
                 ctx.ev(f"features.{side}.record.fights", f"{X} fights on file")],
                (fights, None), caveat=_caveat_thin([X] if level == THIN else [], results=True)))
    return out


def _r_fight_length(ctx: _Ctx) -> List[dict]:
    rounds = _num(ctx.bout.get("scheduled_rounds"))
    if rounds is None or rounds < FIVE_ROUND_MIN_ROUNDS:
        return []
    name = "average_fight_time_s"
    cmp = _compare(ctx, name, FIGHT_LENGTH_S, results=True)
    if not cmp:
        return []
    w, lo = cmp["w"], cmp["l"]
    W, L = ctx.short[w], ctx.short[lo]
    level = _level_results([ctx.fig("a", name), ctx.fig("b", name)])
    wm, lm = cmp["wv"] / 60.0, cmp["lv"] / 60.0
    evidence = [ctx.ev(f"features.{s}.figures.{name}.value", f"{ctx.short[s]} average fight time (seconds)")
                for s in ("a", "b")]
    evidence += [ctx.ev(f"features.{s}.figures.{name}.fights", f"{ctx.short[s]} fights with a fight time") for s in ("a", "b")]
    evidence.append(ctx.ev("bout.scheduled_rounds", "rounds scheduled"))
    sample = _weakest([ctx.fig("a", name), ctx.fig("b", name)])
    thin = ctx.thin_who((name,), results=True)
    caveat = _caveat_thin(thin, results=True,
                          extra="A short average can mean quick finishes as well as a fighter who has not been tested late.")
    clause = ("(on file: " + "; ".join(f"{ctx.short[s]} {_plural(_fights_minutes(ctx.fig(s, name))[0], 'fight')}"
                                       for s in ("a", "b")) + ")")
    items = [_item("fight_length", "pace", w, "strength", cmp["size"], level,
                   f"{W} has been deeper into fights, averaging {_fmt(wm)} minutes on file against {_fmt(lm)} for {L}, "
                   f"in a bout scheduled for {int(rounds)} rounds {clause}.",
                   evidence, sample, caveat=caveat, pair="fight_length")]
    if cmp["lv"] < SHORT_AVERAGE_S:
        items.append(_item("fight_length", "pace", lo, "weakness", cmp["size"], level,
                           f"{_poss(L)} fights on file end earlier, averaging {_fmt(lm)} minutes against {_fmt(wm)} for {W}, "
                           f"with {int(rounds)} rounds scheduled, so the late rounds are less tested {clause}.",
                           evidence, sample, caveat=caveat, pair="fight_length"))
    return items


def _r_layoff(ctx: _Ctx) -> List[dict]:
    out = []
    layoff = ctx.sheet.get("layoff") or {}
    for side in ("a", "b"):
        days = _num(layoff.get(f"{side}_days"))
        size = _size(days, LAYOFF_DAYS)
        if days is None or size is None:
            continue
        X = ctx.short[side]
        last = layoff.get(f"{side}_last_fight_utc")
        out.append(_item(
            "long_layoff", "layoff", side, "weakness", size, FAIR,
            f"{X} has not fought in the UFC for {days / 30.4375:.0f} months, since the last fight on file on {_date(last)}.",
            [ctx.ev(f"layoff.{side}_days", f"{X} days since the last fight"),
             ctx.ev(f"layoff.{side}_last_fight_utc", f"{X} last fight on file")],
            None, caveat="A long gap can mean injury, ring rust or fights outside the UFC; these figures cannot tell which."))
    return out


def _r_age(ctx: _Ctx) -> List[dict]:
    phys = ctx.sheet.get("physical") or {}
    ages = {s: _num((phys.get(s) or {}).get("age_years")) for s in ("a", "b")}
    if ages["a"] is None or ages["b"] is None:
        return []
    older = "a" if ages["a"] > ages["b"] else "b"
    young = other(older)
    gap = round(ages[older] - ages[young], 4)
    size = _size(gap, AGE_GAP)
    if size is None or ages[older] < AGE_OLDER_MIN:
        return []
    O, Y = ctx.short[older], ctx.short[young]
    evidence = [ctx.ev(f"physical.{s}.age_years", f"{ctx.short[s]} age on fight night (years)") for s in ("a", "b")]
    caveat = "Age is shown as a difference in years; these figures do not measure its effect on the fight."
    return [
        _item("age", "physical", young, "strength", size, FAIR,
              f"{Y} is the younger fighter by {_fmt(gap)} years ({_fmt(ages[young])} against {_fmt(ages[older])}).",
              evidence, None, caveat=caveat, pair="age"),
        _item("age", "physical", older, "weakness", size, FAIR,
              f"{O} is the older fighter by {_fmt(gap)} years ({_fmt(ages[older])} against {_fmt(ages[young])}).",
              evidence, None, caveat=caveat, pair="age"),
    ]


def _r_reach(ctx: _Ctx) -> List[dict]:
    return _physical_pair(ctx, "reach_in", "reach", REACH_GAP, "reach",
                          "{W} has the longer reach by {gap} inches ({wv} against {lv}).",
                          "{L} gives away {gap} inches of reach ({lv} against {wv}).")


def _r_height(ctx: _Ctx) -> List[dict]:
    return _physical_pair(ctx, "height_in", "height", HEIGHT_GAP, "height",
                          "{W} is the taller fighter by {gap} inches ({wv} against {lv}).",
                          "{L} is the shorter fighter by {gap} inches ({lv} against {wv}).")


def _physical_pair(ctx: _Ctx, field: str, trait: str, thresholds: Sequence[float], noun: str,
                   strength_text: str, weakness_text: str) -> List[dict]:
    phys = ctx.sheet.get("physical") or {}
    values = {s: _num((phys.get(s) or {}).get(field)) for s in ("a", "b")}
    if values["a"] is None or values["b"] is None:
        return []
    gap = round(values["a"] - values["b"], 4)
    size = _size(gap, thresholds)
    if size is None:
        return []
    w = "a" if gap > 0 else "b"
    lo = other(w)
    fill = {"W": ctx.short[w], "L": ctx.short[lo], "gap": _fmt(abs(gap)),
            "wv": f"{values[w]:.0f}", "lv": f"{values[lo]:.0f}"}
    evidence = [ctx.ev(f"physical.{s}.{field}", f"{ctx.short[s]} {noun} (inches)") for s in ("a", "b")]
    caveat = f"The {noun} is as listed on the fighter record."
    return [
        _item(trait, "physical", w, "strength", size, FAIR, strength_text.format(**fill), evidence, None,
              caveat=caveat, pair=trait),
        _item(trait, "physical", lo, "weakness", size, FAIR, weakness_text.format(**fill), evidence, None,
              caveat=caveat, pair=trait),
    ]


def _r_schedule(ctx: _Ctx) -> List[dict]:
    name = "strength_of_schedule"
    cmp = _compare(ctx, name, SCHEDULE_GAP, results=True)
    if not cmp:
        return []
    w, lo = cmp["w"], cmp["l"]
    W, L = ctx.short[w], ctx.short[lo]
    level = _level_results([ctx.fig("a", name), ctx.fig("b", name)])
    evidence = [ctx.ev(f"features.{s}.figures.{name}.value", f"{ctx.short[s]} opponents' average win rate") for s in ("a", "b")]
    evidence += [ctx.ev(f"features.{s}.figures.{name}.fights", f"{ctx.short[s]} opponents with a record on file")
                 for s in ("a", "b")]
    nw = _fights_minutes(ctx.fig(w, name))[0]
    nl = _fights_minutes(ctx.fig(lo, name))[0]
    clause = f"(opponents with a record on file: {W} {nw}, {L} {nl})"
    caveat = _caveat_thin(ctx.thin_who((name,), results=True), results=True,
                          extra="An opponent with no earlier fight on file is left out of the figure, not counted as average.")
    sample = _weakest([ctx.fig("a", name), ctx.fig("b", name)])
    return [
        _item("schedule", "schedule", w, "strength", cmp["size"], level,
              f"{W} has faced the tougher opposition, with opponents who had won {_pct(cmp['wv'])} of their UFC fights "
              f"going in against {_pct(cmp['lv'])} for {_poss(L)} {clause}.", evidence, sample, caveat=caveat, pair="schedule"),
        _item("schedule", "schedule", lo, "weakness", cmp["size"], level,
              f"{L} has faced the weaker opposition, with opponents who had won {_pct(cmp['lv'])} of their UFC fights "
              f"going in against {_pct(cmp['wv'])} for {_poss(W)} {clause}.", evidence, sample, caveat=caveat, pair="schedule"),
    ]


def _r_results(ctx: _Ctx) -> List[dict]:
    name = "win_rate"
    cmp = _compare(ctx, name, WIN_RATE_GAP, results=True)
    if not cmp:
        return []
    w, lo = cmp["w"], cmp["l"]
    W, L = ctx.short[w], ctx.short[lo]
    level = _level_results([ctx.fig("a", name), ctx.fig("b", name)])

    def line(side: str) -> str:
        rec = ctx.rec(side)
        return f"{_plural(rec.get('wins') or 0, 'win')} in {_plural(rec.get('fights') or 0, 'fight')}"

    evidence = []
    for s in ("a", "b"):
        evidence += [ctx.ev(f"features.{s}.record.wins", f"{ctx.short[s]} wins on file"),
                     ctx.ev(f"features.{s}.record.losses", f"{ctx.short[s]} losses on file"),
                     ctx.ev(f"features.{s}.record.fights", f"{ctx.short[s]} fights on file")]
    caveat = _caveat_thin(ctx.thin_who((name,), results=True), results=True,
                          extra="Records on file say nothing about who the fights were against.")
    sample = _weakest([ctx.fig("a", name), ctx.fig("b", name)])
    return [
        _item("results", "form", w, "strength", cmp["size"], level,
              f"{W} has the better record on file, {line(w)} against {line(lo)} for {L}.",
              evidence, sample, caveat=caveat, pair="results"),
        _item("results", "form", lo, "weakness", cmp["size"], level,
              f"{L} has the weaker record on file, {line(lo)} against {line(w)} for {W}.",
              evidence, sample, caveat=caveat, pair="results"),
    ]


def _r_streak(ctx: _Ctx) -> List[dict]:
    out = []
    for side in ("a", "b"):
        streak = (ctx.features.get(side) or {}).get("streak") or {}
        kind, length = streak.get("type"), int(_num(streak.get("length")) or 0)
        X = ctx.short[side]
        fights = int(ctx.rec(side).get("fights") or 0)
        if kind == "win":
            size = _size(length, WIN_STREAK)
            trait, sentence, label = "win_streak", f"{X} has won {length} fights in a row on file.", "strength"
        elif kind == "loss":
            size = _size(length, LOSS_STREAK)
            trait, sentence, label = "loss_streak", f"{X} has lost {length} fights in a row on file.", "weakness"
        else:
            continue
        if size is None:
            continue
        level = FAIR if length >= STREAK_FAIR_LENGTH else THIN
        out.append(_item(
            trait, "form", side, label, size, level, sentence,
            [ctx.ev(f"features.{side}.streak.type", f"{X} current run"),
             ctx.ev(f"features.{side}.streak.length", f"{X} fights in the run"),
             ctx.ev(f"features.{side}.record.fights", f"{X} fights on file")],
            (fights, None),
            caveat="A run counts results only; it does not say how the fights were won or who they were against."
                   + ("" if level == FAIR else f" A run shorter than {STREAK_FAIR_LENGTH} fights is a thin sample.")))
    return out


_RULES = (
    _r_striking_net, _r_striking_accuracy, _r_striking_defence, _r_takedowns, _r_control,
    _r_knockdown_power, _r_chin, _r_finisher, _r_finished_often, _r_submissions, _r_fight_length,
    _r_layoff, _r_age, _r_reach, _r_height, _r_schedule, _r_results, _r_streak,
)


# ---------------------------------------------------------------------------
# Per-fighter context lines (not scored)
# ---------------------------------------------------------------------------

def _career_fights(ctx: _Ctx, side: str) -> Optional[Tuple[int, str]]:
    """(fights, fetch date) from the fighter record when it was fetched before the fight."""
    block = (ctx.features.get(side) or {}).get("career_record_incl_non_ufc")
    if not isinstance(block, dict):
        return None
    wins, losses, draws = (_num(block.get(k)) for k in ("wins", "losses", "draws"))
    if wins is None or losses is None:
        return None
    try:
        fetched = _feat.parse_instant(block.get("fetched_utc"))
        cutoff = _feat.parse_instant(ctx.as_of)
    except ValueError:
        return None
    if not fetched < cutoff:
        return None
    return int(wins + losses + (draws or 0)), _date(block.get("fetched_utc"))


def _context_for(ctx: _Ctx, side: str) -> List[dict]:
    out = []
    X = ctx.short[side]
    rec = ctx.rec(side)
    fights = int(rec.get("fights") or 0)
    career = _career_fights(ctx, side)
    block = (ctx.features.get(side) or {}).get("career_record_incl_non_ufc") or {}
    if fights == 0:
        text = (f"{X} has no UFC fights on file {ctx.before}, so this is a debut or the file does not "
                "reach earlier fights.")
        evidence = [ctx.ev(f"features.{side}.record.fights", f"{X} fights on file")]
    else:
        nc = int(rec.get("no_contests") or 0)
        record = f"{int(rec.get('wins') or 0)}-{int(rec.get('losses') or 0)}-{int(rec.get('draws') or 0)}"
        text = (f"{X} has {_plural(fights, 'UFC fight')} on file, the first on {_date(rec.get('first_fight_utc'))}, "
                f"for a record of {record}" + (f" with {_plural(nc, 'no contest')}" if nc else "") + ".")
        evidence = [ctx.ev(f"features.{side}.record.fights", f"{X} fights on file"),
                    ctx.ev(f"features.{side}.record.wins", f"{X} wins on file"),
                    ctx.ev(f"features.{side}.record.losses", f"{X} losses on file"),
                    ctx.ev(f"features.{side}.record.first_fight_utc", f"{X} first fight on file")]
    out.append({"key": "coverage", "sentence": text, "evidence": _dedupe(evidence)})
    if career:
        text = (f"The fighter record, fetched {career[1]}, shows {int(block['wins'])}-{int(block['losses'])}-"
                f"{int(block.get('draws') or 0)} overall, {career[0]} professional fights including any outside the UFC.")
        out.append({"key": "overall_record", "sentence": text, "evidence": _dedupe([
            ctx.ev(f"features.{side}.career_record_incl_non_ufc.wins", f"{X} overall wins"),
            ctx.ev(f"features.{side}.career_record_incl_non_ufc.losses", f"{X} overall losses"),
            ctx.ev(f"features.{side}.career_record_incl_non_ufc.fetched_utc", "record fetched")])})
    current = ((ctx.features.get(side) or {}).get("weight_classes") or {}).get("current")
    this = ctx.bout.get("weight_class")
    if current and this and current != this:
        lo = _feat.WEIGHT_LIMIT_LB.get(_names.normalise(current))
        hi = _feat.WEIGHT_LIMIT_LB.get(_names.normalise(this))
        move = "" if lo is None or hi is None or lo == hi else (", a move up" if hi > lo else ", a move down")
        out.append({"key": "weight_class", "sentence": (
            f"{X} last fought at {current} and this bout is at {this}{move}."), "evidence": _dedupe([
                ctx.ev(f"features.{side}.weight_classes.current", f"{X} weight class of the last fight"),
                ctx.ev("bout.weight_class", "weight class of this bout")])})
    last = (ctx.features.get(side) or {}).get("last_three") or []
    if last:
        lines, evidence = [], []
        for j, f in enumerate(last):
            lines.append(_fight_words(None, f.get("opponent_name") or "an opponent with no name on file", f,
                                      with_round=True))
            evidence += [ctx.ev(f"features.{side}.last_three.{j}.result", f"{X} result, fight {j + 1} back"),
                         ctx.ev(f"features.{side}.last_three.{j}.opponent_name", f"{X} opponent, fight {j + 1} back"),
                         ctx.ev(f"features.{side}.last_three.{j}.method", f"{X} method, fight {j + 1} back"),
                         ctx.ev(f"features.{side}.last_three.{j}.date_utc", f"{X} date, fight {j + 1} back")]
        lead = (f"{_poss(X)} last fight on file" if len(last) == 1
                else f"{_poss(X)} last {len(last)} fights on file, newest first")
        out.append({"key": "last_fights", "sentence": f"{lead}: {'; '.join(lines)}.", "evidence": _dedupe(evidence)})
    days = _num((ctx.sheet.get("layoff") or {}).get(f"{side}_days"))
    if ctx.bout and days is not None and 0 <= days <= SHORT_TURNAROUND_DAYS:
        out.append({"key": "short_turnaround", "sentence": (
            f"{X} fought {_plural(int(days), 'day')} before this bout, a short turnaround."),
            "evidence": _dedupe([ctx.ev(f"layoff.{side}_days", f"{X} days since the last fight")])})
    return out


def _shared_context(ctx: _Ctx) -> List[dict]:
    out = []
    phys = ctx.sheet.get("physical") or {}
    if phys.get("stance_matchup"):
        a, b = (phys.get("a") or {}).get("stance"), (phys.get("b") or {}).get("stance")
        if phys.get("same_stance"):
            text = f"Both fighters work from the {str(a).lower()} stance."
        else:
            text = f"{ctx.short['a']} fights {str(a).lower()} and {ctx.short['b']} fights {str(b).lower()}."
        out.append({"key": "stance", "sentence": text + " These figures do not measure what that changes.",
                    "evidence": _dedupe([ctx.ev("physical.stance_matchup", "stances")])})
    # How their fights have ended up: the share that went to the scorecards, a proxy for pace and the late rounds.
    name = "distance_rate"
    va, vb = ctx.val("a", name), ctx.val("b", name)
    if va is not None and vb is not None and ctx.shown([("a", name), ("b", name)], results=True):
        figs = [ctx.fig("a", name), ctx.fig("b", name)]
        na, nb = (_fights_minutes(f)[0] for f in figs)
        entry = {"key": "fight_shape",
                 "sentence": (f"{_poss(ctx.short['a'])} fights on file have gone to the scorecards {_pct(va)} of the time and "
                              f"{_poss(ctx.short['b'])} {_pct(vb)} (fights with a recorded method: {ctx.short['a']} {na}, "
                              f"{ctx.short['b']} {nb})."),
                 "evidence": _dedupe([ctx.ev(f"features.{s}.figures.{name}.value", f"{ctx.short[s]} share of fights that went to "
                                             "the scorecards") for s in ("a", "b")]
                                     + [ctx.ev(f"features.{s}.figures.{name}.fights", f"{ctx.short[s]} fights with a recorded method")
                                        for s in ("a", "b")])}
        thin = ctx.thin_who((name,), results=True)
        if thin:
            entry["caveat"] = _caveat_thin(thin, results=True)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Data depth
# ---------------------------------------------------------------------------

def _data_depth(ctx: _Ctx) -> dict:
    sides, thin, solid = {}, [], True
    evidence = []
    for side in ("a", "b"):
        smp = ctx.sample(side)
        fights, minutes = int(smp.get("fights") or 0), float(smp.get("minutes") or 0.0)
        career = _career_fights(ctx, side)
        sides[side] = {"name": ctx.full[side], "fights": fights, "minutes": round(minutes, 2),
                       "overall_fights": career[0] if career else None}
        if fights < MIN_FIGHTS_TIMED or minutes < MIN_MINUTES_TIMED:
            thin.append(side)
        if not (fights >= SOLID_FIGHTS_TIMED and minutes >= SOLID_MINUTES_TIMED):
            solid = False
        evidence += [ctx.ev(f"features.{side}.sample.fights", f"{ctx.short[side]} UFC fights on file"),
                     ctx.ev(f"features.{side}.sample.minutes", f"{ctx.short[side]} fight minutes on file")]
    level = THIN if thin else (SOLID if solid else FAIR)
    parts = []
    for side in ("a", "b"):
        s = sides[side]
        extra = (f", out of {s['overall_fights']} professional fights in all" if s["overall_fights"] else "")
        parts.append(f"{ctx.short[side]} {_plural(s['fights'], 'UFC fight')} ({_minutes(s['minutes'])}){extra}")
    verdict = {
        THIN: (f"That is thin: under {MIN_FIGHTS_TIMED} fights or {MIN_MINUTES_TIMED:g} fight minutes for "
               f"{_join([ctx.short[s] for s in thin])}, so any figure built on them is an early sign and not a settled fact."),
        FAIR: "That is enough to describe each fighter's recent style and not enough to settle it.",
        SOLID: "That is a reasonable sample of each fighter's recent fights.",
    }[level]
    return {"level": level, "a": sides["a"], "b": sides["b"],
            "sentence": ctx.on_file + ": " + "; ".join(parts) + ". " + verdict,
            "evidence": _dedupe(evidence)}


# ---------------------------------------------------------------------------
# Routes to victory
# ---------------------------------------------------------------------------

def _find(items: Sequence[dict], side: str, trait: str, kind: Optional[str] = None) -> Optional[dict]:
    for it in items:
        if it["_side"] == side and it["trait"] == trait and (kind is None or it["kind"] == kind):
            return it
    return None


def _fact_part(trait: str, size: str, level: str, evidence: Sequence[Optional[dict]], caveat: str = "") -> dict:
    """A count taken straight from the record, shaped like an item so a route can be built from it."""
    return {"trait": trait, "size": size, "sample_level": level, "thin": level == THIN, "caveat": caveat,
            "evidence": [e for e in evidence if e]}


def _route(key: str, title: str, side: str, sentence: str, parts: Sequence[dict], *,
           how: str = "weakest") -> dict:
    sizes = [SIZE_RANK[p["size"]] for p in parts]
    rank = min(sizes) if how == "weakest" else max(sizes)
    level = _worst([p["sample_level"] for p in parts])
    size = SIZES[rank - 1]
    thin_caveat = next((p["caveat"] for p in parts if p["thin"] and p["caveat"]), "")
    evidence = _dedupe([e for p in parts for e in p["evidence"]])
    return {"route": key, "title": title, "sentence": sentence, "size": size, "sample_level": level,
            "thin": level == THIN, "down_weighted": level == THIN, "caveat": thin_caveat,
            "built_from": [p["trait"] for p in parts], "evidence": evidence, "weight": _weight(size, level)}


def _routes(ctx: _Ctx, items: Sequence[dict], side: str) -> List[dict]:
    foe = other(side)
    X, Y = ctx.short[side], ctx.short[foe]
    found = []

    # win the striking
    net = _find(items, side, "striking_net", "strength")
    if net:
        extras, parts = [], [net]
        for trait, text in (("striking_accuracy", "lands more accurately"), ("striking_defence", "is harder to hit")):
            extra = _find(items, side, trait, "strength")
            if extra:
                extras.append(text)
                parts.append(extra)
        x_net = ctx.val(side, "sig_strikes_landed_per_min") - ctx.val(side, "sig_strikes_absorbed_per_min")
        y_net = ctx.val(foe, "sig_strikes_landed_per_min") - ctx.val(foe, "sig_strikes_absorbed_per_min")
        tail = f", and {X} {_join(extras)} as well" if extras else ""
        found.append(_route(
            "striking", "Win the striking", side,
            f"{X} nets {_signed(x_net)} significant strikes a minute on file against {_signed(y_net)} for {Y}{tail}. "
            "This route needs the fight to stay on the feet.", parts, how="strongest"))

    # a knockout
    power = _find(items, side, "knockdown_power", "strength")
    finisher = _find(items, side, "finisher", "strength")
    chin = _find(items, foe, "chin", "weakness")
    foe_rec = ctx.rec(foe)
    ko_losses = int((foe_rec.get("losses_by_method") or {}).get("ko_tko") or 0)
    foe_fights = int(foe_rec.get("fights") or 0)
    lead_item = power or finisher
    if lead_item and (chin or (power and ko_losses >= 1)):
        parts = [lead_item]
        if chin:
            parts.append(chin)
        else:
            parts.append(_fact_part("ko_losses", "slight", FAIR if foe_fights >= MIN_FIGHTS_RESULTS else THIN,
                                    [ctx.ev(f"features.{foe}.record.losses_by_method.ko_tko", f"{Y} losses by KO or TKO"),
                                     ctx.ev(f"features.{foe}.record.fights", f"{Y} fights on file")],
                                    _caveat_thin([Y] if foe_fights < MIN_FIGHTS_RESULTS else [], results=True)))
        if power:
            lead = f"{X} scores {_fmt(ctx.val(side, 'knockdowns_landed_per_15'))} knockdowns per 15 minutes on file"
        else:
            fin = ctx.fig(side, "finish_rate")
            lead = f"{X} has finished {int(_num(fin.get('num')) or 0)} of {int(_num(fin.get('den')) or 0)} fights on file"
        kd = ctx.val(foe, "knockdowns_suffered_per_15")
        if kd is not None and kd >= KNOCKDOWNS_SUFFERED[0]:
            tail = f"{Y} has been knocked down {_fmt(kd)} times per 15 minutes"
            if ko_losses:
                tail += f" and has lost by KO or TKO {_times(ko_losses)}"
        else:
            tail = f"{Y} has lost by KO or TKO {_times(ko_losses)} in {_plural(foe_fights, 'fight')} on file"
        found.append(_route("knockout", "Hurt and finish", side, f"{lead}, and {tail}.", parts))
    elif power:
        found.append(_route(
            "knockout", "Hurt and finish", side,
            f"{X} scores {_fmt(ctx.val(side, 'knockdowns_landed_per_15'))} knockdowns per 15 minutes "
            f"on file, though nothing on file says {Y} is easy to drop.", [power], how="strongest"))

    # the mat
    open_td = _find(items, side, "takedown_open", "strength")
    if open_td:
        control = _find(items, side, "control", "strength")
        parts = [open_td] + ([control] if control else [])
        td_rate = ctx.val(side, "takedowns_landed_per_15")
        stopped = ctx.val(foe, "takedown_defence")
        attempts = int(ctx.fig(foe, "takedown_defence").get("den") or 0)
        tail = (f"; {X} has also spent {_pct(ctx.val(side, 'control_time_share'))} of fight time in control"
                if control else "")
        found.append(_route(
            "mat", "Take it to the mat", side,
            f"{X} lands {_fmt(td_rate)} takedowns per 15 minutes on file, and {Y} has stopped "
            f"only {_pct(stopped)} of {attempts} attempts{tail}.", parts, how="strongest"))

    # a submission
    sub = _find(items, side, "submission_threat", "strength")
    if sub:
        submitted = _find(items, foe, "been_submitted", "weakness")
        reasons = []
        parts = [sub]
        if submitted:
            n = int((ctx.rec(foe).get("losses_by_method") or {}).get("submission") or 0)
            reasons.append(f"has lost by submission {_times(n)} on file")
            parts.append(submitted)
        if open_td:
            reasons.append(f"has stopped only {_pct(ctx.val(foe, 'takedown_defence'))} of takedowns")
            parts.append(open_td)
        if reasons:
            found.append(_route(
                "submission", "Find a submission", side,
                f"{X} throws {_fmt(ctx.val(side, 'submission_attempts_per_15'))} submission attempts per 15 "
                f"minutes on file, and {Y} {_join(reasons)}.", parts))

    # the scorecards
    rec = ctx.rec(side)
    decision_wins = int((rec.get("wins_by_method") or {}).get("decision") or 0)
    wins = int(rec.get("wins") or 0)
    fights = int(rec.get("fights") or 0)
    if decision_wins >= DECISION_WINS_MIN and wins and decision_wins / wins >= 0.5 and fights >= MIN_FIGHTS_SHOWN_RESULTS:
        y_finish = ctx.val(foe, "finish_rate")
        tail = f", and {Y} has finished {_pct(y_finish)} of fights on file" if y_finish is not None and y_finish < 0.5 else ""
        level = FAIR if fights >= MIN_FIGHTS_RESULTS else THIN
        size = "moderate" if decision_wins >= 4 and decision_wins / wins >= 0.75 else "slight"
        part = _fact_part("decision_wins", size, level,
                          [ctx.ev(f"features.{side}.record.wins_by_method.decision", f"{X} wins by decision"),
                           ctx.ev(f"features.{side}.record.wins", f"{X} wins on file"),
                           ctx.ev(f"features.{side}.record.fights", f"{X} fights on file"),
                           ctx.ev(f"features.{foe}.figures.finish_rate.value", f"{Y} finishing rate") if tail else None],
                          _caveat_thin([X] if level == THIN else [], results=True))
        found.append(_route(
            "scorecards", "Win on the scorecards", side,
            f"{decision_wins} of {_poss(X)} {_plural(wins, 'win')} on file came by decision{tail}.",
            [part]))

    # five rounds
    length = _find(items, side, "fight_length", "strength")
    if length:
        found.append(_route(
            "deep", "Make it long", side,
            f"{_poss(X)} fights on file average {_fmt(ctx.val(side, 'average_fight_time_s') / 60.0)} minutes "
            f"against {_fmt(ctx.val(foe, 'average_fight_time_s') / 60.0)} for {Y}, and this one is scheduled for "
            f"{int(_num(ctx.bout.get('scheduled_rounds')) or 0)} rounds.", [length], how="strongest"))

    # keep it standing
    closed = _find(items, side, "takedown_closed", "strength")
    if closed and not _find(items, foe, "striking_net", "strength"):
        found.append(_route(
            "stay_standing", "Keep it standing", side,
            f"{Y} lands {_fmt(ctx.val(foe, 'takedowns_landed_per_15'))} takedowns per 15 minutes on file, "
            f"but {X} has stopped {_pct(ctx.val(side, 'takedown_defence'))} of "
            f"{int(ctx.fig(side, 'takedown_defence').get('den') or 0)} attempts, and nothing on file says "
            f"{Y} wins the striking.", [closed], how="strongest"))

    order = {r["route"]: i for i, r in enumerate(found)}
    found.sort(key=lambda r: (-r["weight"], order[r["route"]]))
    found = found[:MAX_ROUTES]
    if not found:
        n = int(ctx.rec(side).get("fights") or 0)
        why = ("" if n >= MIN_FIGHTS_RESULTS else ", and no fights are on file" if n == 0
               else f", and only {_plural(n, 'fight')} {'is' if n == 1 else 'are'} on file")
        found = [{"route": "none", "title": "No clear route",
                  "sentence": f"Nothing in the figures on file points to a route to a win for {X}{why}.",
                  "size": "slight", "sample_level": THIN, "thin": True, "down_weighted": True,
                  "caveat": "", "built_from": [], "evidence": [
                      e for e in (ctx.ev(f"features.{side}.record.fights", f"{X} fights on file"),) if e],
                  "weight": 0.0}]
    return found


# ---------------------------------------------------------------------------
# Market view
# ---------------------------------------------------------------------------

def _lean(items: Sequence[dict]) -> float:
    """Net weight, positive toward fighter a. Within a family only the heaviest item of each side counts,
    and a weakness counts for the opponent unless it is the twin of a strength already counted."""
    fam: Dict[str, Dict[str, float]] = {}
    for it in items:
        if it["_pair"] and it["kind"] == "weakness":
            continue
        beneficiary = it["_side"] if it["kind"] == "strength" else other(it["_side"])
        slot = fam.setdefault(it["family"], {"a": 0.0, "b": 0.0})
        slot[beneficiary] = max(slot[beneficiary], it["weight"])
    return round(sum(s["a"] - s["b"] for s in fam.values()), 2)


def _market_view(ctx: _Ctx, items: Sequence[dict], depth: dict) -> dict:
    out = {"available": False, "label": "What the price implies, set beside this read.", "sentences": [],
           "evidence": [], "agreement": "no price", "lean": "none", "lean_weight": 0.0}
    odds = ctx.odds
    ml = (odds or {}).get("moneyline") if isinstance(odds, dict) else None
    snap_name = None
    for name in ("current", "close", "open"):
        if isinstance(ml, dict) and isinstance(ml.get(name), dict):
            snap_name = name
            break
    snap = ml[snap_name] if snap_name else None
    fair = (snap or {}).get("without_margin") if isinstance(snap, dict) else None
    if not isinstance(fair, dict) or _num(fair.get("a")) is None or _num(fair.get("b")) is None:
        if isinstance(odds, dict) and odds.get("note"):
            if "in-fight" in str(odds.get("note")):
                out["sentences"].append("Only prices taken during the fight are on file, so there is no pre-fight "
                                        "market to set this read against.")
            else:
                out["sentences"].append("A price is on file for this fight but could not be matched to the two "
                                        "fighters with confidence, so no market view is shown.")
        else:
            out["sentences"].append("No price is on file for this fight, so there is nothing to set this read against.")
        out["sentences"].append(RESEARCH_NOTE)
        return out
    pa, pb = _num(fair["a"]), _num(fair["b"])
    A, B = ctx.short["a"], ctx.short["b"]
    fav = "a" if pa > pb else "b" if pb > pa else None
    out["available"] = True
    out["provider"] = odds.get("provider")
    out["fetched_utc"] = odds.get("fetched_utc")
    out["snapshot"] = snap_name
    out["is_closing"] = bool(odds.get("is_closing"))
    out["implied"] = {s: {"name": ctx.full[s], "american": snap.get(s),
                          "with_margin": (snap.get("implied") or {}).get(s),
                          "without_margin": fair.get(s)} for s in ("a", "b")}
    out["margin"] = snap.get("margin")
    out["favourite"] = fav or "even"
    base = f"odds.moneyline.{snap_name}"
    out["evidence"] = _dedupe([
        ctx.ev(f"{base}.a", f"{A} price"), ctx.ev(f"{base}.b", f"{B} price"),
        ctx.ev(f"{base}.without_margin.a", f"{A} share of the market with the margin removed"),
        ctx.ev(f"{base}.without_margin.b", f"{B} share of the market with the margin removed"),
        ctx.ev(f"{base}.margin", "the bookmaker's margin"),
        ctx.ev("odds.fetched_utc", "prices fetched")])

    provider = odds.get("provider") or "The book"
    when = "closing" if out["is_closing"] else "current"
    if fav:
        f_name, d_name = (A, B) if fav == "a" else (B, A)
        fp, dp = max(pa, pb), min(pa, pb)
        sent = (f"{_poss(provider)} {when} prices make {f_name} the {_pct(fp, 1)} favourite and {d_name} {_pct(dp, 1)}, "
                f"with the bookmaker's margin taken out ({A} {_fmt_american(snap.get('a'))}, "
                f"{B} {_fmt_american(snap.get('b'))}, fetched {_date(odds.get('fetched_utc'))}).")
    else:
        sent = (f"{_poss(provider)} {when} prices have the two fighters level at {_pct(pa, 1)} each with the margin "
                f"taken out, fetched {_date(odds.get('fetched_utc'))}.")
    out["sentences"].append(sent)

    age_h = None
    fetched = _feat.instant(odds.get("fetched_utc"))
    if ctx.now is not None and fetched is not None and not out["is_closing"]:
        age_h = round((ctx.now - fetched).total_seconds() / 3600.0, 1)
        out["age_hours"] = age_h
        if age_h >= 24:
            out["sentences"].append(f"These prices were fetched {age_h:.0f} hours before this page was built, and prices move.")

    open_fair = ((ml.get("open") or {}).get("without_margin") or {}) if isinstance(ml, dict) else {}
    if snap_name == "current" and _num(open_fair.get("a")) is not None:
        move = round((pa - _num(open_fair["a"])) * 100, 1)
        out["movement"] = {"toward": "a" if move > 0 else "b" if move < 0 else None, "points": abs(move)}
        out["evidence"] += _dedupe([ctx.ev("odds.moneyline.open.without_margin.a", f"{A} share when the line opened")])
        if abs(move) >= MOVE_POINTS:
            mover = A if move > 0 else B
            out["sentences"].append(
                f"The line has moved toward {mover} since it opened, by {abs(move):.1f} points of probability with the "
                "margin removed. A move says what the market now thinks and not why.")
        else:
            out["sentences"].append("The line has barely moved since it opened.")

    total = (odds.get("rounds_total") or {}) if isinstance(odds.get("rounds_total"), dict) else {}
    cur = total.get("current") if isinstance(total.get("current"), dict) else None
    if cur and total.get("line") is not None and isinstance(cur.get("without_margin"), dict):
        over, under = _num(cur["without_margin"].get("over")), _num(cur["without_margin"].get("under"))
        if over is not None and under is not None:
            side_word, share = ("past", over) if over >= under else ("short of", under)
            out["sentences"].append(f"The rounds line is {_fmt(total['line'])}, with the fight going {side_word} it the "
                                    f"likelier side at {_pct(share)} with the margin removed.")
            out["evidence"] += _dedupe([ctx.ev("odds.rounds_total.line", "rounds line"),
                                        ctx.ev("odds.rounds_total.current.without_margin.over", "share for the over")])

    method = odds.get("method") if isinstance(odds.get("method"), dict) else None
    mcur = method.get("current") if method and isinstance(method.get("current"), dict) else None
    if mcur and isinstance(mcur.get("without_margin"), dict):
        shares = {}
        for m in ("ko_tko_dq", "submission", "decision"):
            parts = [_num(((mcur["without_margin"].get(s) or {}).get(m))) for s in ("a", "b")]
            if None not in parts:
                shares[m] = sum(parts)
        if len(shares) == 3:
            out["sentences"].append(
                f"Taken together, the method prices put a decision at {_pct(shares['decision'])}, a KO or TKO at "
                f"{_pct(shares['ko_tko_dq'])} and a submission at {_pct(shares['submission'])}, margin removed.")
            out["evidence"] += _dedupe([ctx.ev("odds.method.current.without_margin.a.decision",
                                               f"{A} by decision, margin removed")])

    net = _lean(items)
    side = "a" if net >= LEAN_MIN else "b" if net <= -LEAN_MIN else None
    out["lean_weight"] = abs(net)
    out["lean"] = side or "none"
    thin = depth["level"] == THIN
    if side is None:
        out["agreement"] = "no lean"
        out["sentences"].append("The figures on file do not lean clearly toward either fighter, so this read neither "
                                "agrees nor disagrees with the price. On these inputs the price is the better informed number.")
    elif fav is not None and side == fav:
        out["agreement"] = "agrees"
        out["sentences"].append(
            f"The figures on file lean toward {ctx.short[side]} too, so this read agrees with the market on direction. "
            "That is expected, because what we can see is already in the price. It says nothing about whether the price is right.")
    elif fav is None:
        out["agreement"] = "no lean"
        out["sentences"].append(f"The figures on file lean toward {ctx.short[side]} while the market has the fighters level.")
    else:
        out["agreement"] = "disagrees"
        out["sentences"].append(
            f"The figures on file lean toward {ctx.short[side]}, the side the market has as the underdog, so this read "
            "disagrees with the price.")
        out["sentences"].append(
            "Given how little is on file, the likelier explanation is that the books know something this read cannot "
            "see, such as an injury, a bad weight cut or camp news, and not that the price is wrong." if thin else
            "Even so, a disagreement with a posted price is a question to check and not a finding.")
    if thin:
        out["sentences"].append("With this little on file, the price is more likely right than this read.")
    out["sentences"].append(RESEARCH_NOTE)
    return out


def _fmt_american(price: Any) -> str:
    n = _num(price)
    if n is None:
        return "no price"
    n = int(n)
    return f"+{n}" if n > 0 else str(n)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def method_words(code: Any) -> str:
    return METHOD_WORDS.get(code, "an unrecorded method")


def _fight_words(who: Optional[str], opponent: str, f: dict, *, with_round: bool = False) -> str:
    """One fight as words: "Archer beat Silva by submission on 2026-01-24". With no subject, "beat Silva ..."."""
    result = f.get("result")
    when = _date(f.get("date_utc"))
    lead = f"{who} " if who else ""
    tail = f", round {int(f['round'])}" if with_round and _num(f.get("round")) else ""
    if result == "draw":
        return f"{lead}drew with {opponent} on {when}{tail}"
    if result == "no_contest":
        return f"{lead}had a no contest with {opponent} on {when}{tail}"
    verb = "beat" if result == "win" else "lost to"
    return f"{lead}{verb} {opponent} by {method_words(f.get('method'))} on {when}{tail}"


def _history(ctx: _Ctx) -> dict:
    sheet = ctx.sheet
    A, B = ctx.full["a"], ctx.full["b"]       # full names: two fighters can share a last name with an opponent
    meetings, shared = sheet.get("previous_meetings") or [], sheet.get("shared_opponents") or {}
    out = {"previous_meetings": [], "shared_opponents": [], "summary": "", "caveat": ""}
    for i, m in enumerate(meetings):
        base = f"previous_meetings.{i}"
        if m.get("result") == "draw":
            text = f"{A} and {B} fought to a draw on {_date(m.get('date_utc'))}."
        elif m.get("result") == "no_contest":
            text = f"{A} and {B} had a no contest on {_date(m.get('date_utc'))}."
        else:
            winner = m.get("winner_name") or (A if m.get("result") == "win" else B)
            text = f"{winner} won by {method_words(m.get('method'))} on {_date(m.get('date_utc'))}"
            if m.get("round"):
                text += f", in round {int(m['round'])}"
            if m.get("detail"):
                text += f" ({m['detail']})"
            text += "."
        out["previous_meetings"].append({"sentence": text, "evidence": _dedupe([
            ctx.ev(f"{base}.date_utc", "date of the earlier fight"), ctx.ev(f"{base}.result", f"result for {A}"),
            ctx.ev(f"{base}.method", "method"), ctx.ev(f"{base}.round", "round")])})
    items = shared.get("items") or []
    for i, item in enumerate(items[:MAX_SHARED_OPPONENTS]):
        opp = item.get("opponent_name") or "an opponent with no name on file"
        a_lines = [_fight_words(A, opp, f) for f in item.get("a") or []]
        b_lines = [_fight_words(B, opp, f) for f in item.get("b") or []]
        text = f"Both fought {opp}. {_join(a_lines)}; {_join(b_lines)}."
        evidence = []
        for side in ("a", "b"):
            for j, f in enumerate(item.get(side) or []):
                evidence += [ctx.ev(f"shared_opponents.items.{i}.{side}.{j}.result", f"{ctx.full[side]} result against {opp}"),
                             ctx.ev(f"shared_opponents.items.{i}.{side}.{j}.method", f"{ctx.full[side]} method against {opp}"),
                             ctx.ev(f"shared_opponents.items.{i}.{side}.{j}.date_utc", f"{ctx.full[side]} date against {opp}")]
        out["shared_opponents"].append({"opponent": opp, "sentence": text, "evidence": _dedupe(evidence)})
    n_meet = len(meetings)
    count = int(shared.get("count") or 0)
    na, nb = int(shared.get("a_opponents") or 0), int(shared.get("b_opponents") or 0)
    parts = [f"{A} and {B} have met {_times(n_meet)} in the fights on file." if n_meet
             else f"{A} and {B} have not met in the fights on file."]
    if count:
        parts.append(f"They have {_plural(count, 'opponent')} in common"
                     + (f", and the {MAX_SHARED_OPPONENTS} most recent are shown." if count > MAX_SHARED_OPPONENTS else "."))
    elif na and nb and n_meet:
        parts.append(f"Counting each other, {A} has faced {_plural(na, 'opponent')} on file and {B} has faced {nb}, "
                     "with no one else in common.")
    elif na and nb:
        parts.append(f"{A} has faced {_plural(na, 'opponent')} on file and {B} has faced {nb}, with none in common.")
    else:
        parts.append("At least one of them has no earlier opponents on file, so there is nothing to compare.")
    out["summary"] = " ".join(parts)
    out["evidence"] = _dedupe([ctx.ev("shared_opponents.count", "opponents in common"),
                               ctx.ev("shared_opponents.a_opponents", f"{A} opponents on file"),
                               ctx.ev("shared_opponents.b_opponents", f"{B} opponents on file")])
    if items:
        out["caveat"] = ("Results against a shared opponent are a weak guide: the opponent changes between fights, "
                         "and the fights were months apart.")
    return out


# ---------------------------------------------------------------------------
# What would change it, missing, headline, notices
# ---------------------------------------------------------------------------

def _what_would_change_it(ctx: _Ctx, depth: dict, market: dict) -> List[dict]:
    out = []
    A, B = ctx.short["a"], ctx.short["b"]
    out.append({
        "fact": "A change of opponent, a withdrawal or a cancelled bout.",
        "because": (f"Everything above is built from {A} and {B} as booked for {_date(ctx.bout.get('date_utc') or ctx.as_of)}; "
                    if ctx.bout else f"Everything above is built from {A} and {B} as a possible matchup measured as of "
                                     f"{_date(ctx.as_of)}; ") + "a replacement fighter would void it and start the read again.",
        "evidence": _dedupe([ctx.ev("bout.date_utc", "date of the bout"), ctx.ev("bout.status", "status of the bout")])})
    if depth["level"] == THIN:
        thinnest = min(("a", "b"), key=lambda s: (depth[s]["fights"], depth[s]["minutes"]))
        who = ctx.short[thinnest]
        evidence = _dedupe([ctx.ev(f"features.{thinnest}.sample.fights", f"{who} fights on file"),
                            ctx.ev(f"features.{thinnest}.sample.minutes", f"{who} fight minutes on file")])
        if depth[thinnest]["fights"] == 0:
            out.append({"fact": f"A UFC fight on file for {who}.",
                        "because": f"No UFC fights are on file for {who}, so every fight figure about {who} is missing and a "
                                   "first one would start to fill them in.", "evidence": evidence})
        else:
            out.append({
                "fact": f"More fights on file for {who}.",
                "because": f"{who} has {_plural(depth[thinnest]['fights'], 'fight')} and {_minutes(depth[thinnest]['minutes'])} "
                           "behind the figures, so one more fight would move most of them.",
                "evidence": evidence})
    if market["available"]:
        out.append({"fact": "A move in the price.",
                    "because": "The market takes in injuries, weight cuts and camp news that these figures cannot see; a large "
                               "move after this read was built would mean something we do not see.",
                    "evidence": market["evidence"][:2]})
    else:
        out.append({"fact": "A price being posted.",
                    "because": "With no price on file there is nothing to set this read against; once one is posted the market "
                               "view above fills in.", "evidence": []})
    return out[:3]


def _missing(ctx: _Ctx, depth: dict) -> List[dict]:
    out = []
    sheet = ctx.sheet
    side_missing: Dict[str, list] = {"a": [], "b": []}
    for m in sheet.get("missing") or []:
        side = m.get("side")
        if side in side_missing:
            side_missing[side].append(m)
        elif m.get("figure") == "bout":
            out.append({"input": "The booked bout", "status": "absent",
                        "detail": "no scheduled bout between these two fighters is on file, so the read treats them as a possible matchup"})
        elif m.get("figure") == "odds":
            out.append({"input": "The price", "status": "absent", "detail": _plain(m.get("reason"))})
    for side in ("a", "b"):
        X = ctx.short[side]
        fights = int(ctx.rec(side).get("fights") or 0)
        wanted = [m for m in side_missing[side] if m.get("figure") in _FIGURE_WORDS]
        block = (ctx.features.get(side) or {}).get("career_record_incl_non_ufc")
        if isinstance(block, dict) and _num(block.get("wins")) is not None and _career_fights(ctx, side) is None:
            out.append({"input": f"{X}: overall record", "status": "absent",
                        "detail": f"the fighter record was fetched on {_date(block.get('fetched_utc'))}, not before "
                                  f"{'this bout' if ctx.bout else _date(ctx.as_of)}, so it may already include this fight "
                                  "and is not used"})
        if fights == 0:
            out.append({"input": f"{X}: UFC fights", "status": "absent",
                        "detail": f"no UFC fights on file {ctx.before}, so every figure built from fights is missing"})
            wanted = [m for m in wanted if m["figure"] not in _FIGHT_DERIVED]
        by_reason: Dict[str, List[str]] = {}
        for m in wanted:
            by_reason.setdefault(_plain(m.get("reason")), []).append(_FIGURE_WORDS[m["figure"]])
        for reason, words in by_reason.items():
            out.append({"input": f"{X}: {_join(words)}", "status": "absent", "detail": reason})
        smp = depth[side]
        if fights and (smp["fights"] < MIN_FIGHTS_TIMED or smp["minutes"] < MIN_MINUTES_TIMED):
            out.append({"input": f"{X}: rates and accuracies", "status": "thin",
                        "detail": f"{_plural(smp['fights'], 'fight')} and {_minutes(smp['minutes'])} on file; a rate is shown from "
                                  f"{MIN_FIGHTS_SHOWN_TIMED} fights and counts as more than thin from {MIN_FIGHTS_TIMED} fights "
                                  f"and {MIN_MINUTES_TIMED:g} fight minutes"})
        if fights and smp["fights"] < MIN_FIGHTS_RESULTS:
            out.append({"input": f"{X}: finishing, win and fight-length figures", "status": "thin",
                        "detail": f"{_plural(smp['fights'], 'fight')} on file; a share of results is shown from "
                                  f"{MIN_FIGHTS_SHOWN_RESULTS} fights and counts as more than thin from {MIN_FIGHTS_RESULTS}"})
    return out


def _notices(ctx: _Ctx) -> List[str]:
    notes = []
    A, B = ctx.short["a"], ctx.short["b"]
    if not ctx.bout:
        notes.append(f"No booked bout between {A} and {B} is on file, so this read treats them as a possible matchup "
                     f"measured as of {_date(ctx.as_of)}.")
    elif ctx.bout.get("status") not in (None, "scheduled"):
        notes.append(f"This bout is listed as {str(ctx.bout.get('status')).replace('_', ' ')}. The read describes the fight "
                     "going in and does not use how it turned out.")
    return notes


def _headline(ctx: _Ctx, items: Sequence[dict], depth: dict) -> Tuple[str, Optional[dict]]:
    candidates = [it for it in items if it["kind"] == "strength" or (it["kind"] == "weakness" and not it["_pair"])]
    order = {id(it): i for i, it in enumerate(items)}
    candidates.sort(key=lambda it: (-it["weight"], order[id(it)]))
    top = None
    for pool in ([c for c in candidates if c["family"] not in HEADLINE_LAST_FAMILIES],
                 [c for c in candidates if c["family"] in HEADLINE_LAST_FAMILIES]):
        if pool and pool[0]["weight"] >= HEADLINE_MIN_WEIGHT:
            top = pool[0]
            break
    if top is None:
        tail = ""
        if depth["level"] == THIN:
            none = [ctx.short[s] for s in ("a", "b") if depth[s]["fights"] == 0]
            little = [ctx.short[s] for s in ("a", "b") if depth[s]["fights"] > 0 and (
                depth[s]["fights"] < MIN_FIGHTS_TIMED or depth[s]["minutes"] < MIN_MINUTES_TIMED)]
            if none:
                tail += f" No UFC fights are on file for {_join(none)}."
            if little:
                tail += f" Little is on file for {_join(little)}."
        return (f"No single difference clearly separates {ctx.short['a']} and {ctx.short['b']} in the data on file, "
                f"and that is a valid read.{tail}"), None
    text = f"The biggest difference is {_TOPIC.get(top['trait'], 'in this fight')}. {top['sentence']}"
    if top["thin"]:
        text += " The sample behind it is thin, so treat it as an early sign."
    return text, top


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _rank(items: Sequence[dict], order: Dict[int, int]) -> List[dict]:
    return sorted(items, key=lambda it: (-it["weight"], order[id(it)]))


# ---------------------------------------------------------------------------
# The compact sheet
# ---------------------------------------------------------------------------

# What a page needs from a sheet to draw the fact sheet: the figures side by side (the differentials carry both
# fighters' values and their samples), the physical and layoff blocks, the style labels, each fighter's record,
# streak and last three. Everything else (the leakage statement per fighter, the schedule-strength audit lines, the
# UFC.com block, the shared-opponent and previous-meeting lists the read already summarises) stays out, which takes
# a bout from about 27 KB of sheet to about 9. The read's evidence paths point into the FULL sheet; a client that
# holds the compact one reads each evidence entry's label and value, not its path.
COMPACT_KEEP = ("a", "b", "as_of", "as_of_source", "note", "bout", "differentials", "styles", "physical", "layoff")
COMPACT_FEATURES = ("sample", "record", "streak", "last_three")


def compact_sheet(sheet: Optional[dict]) -> Optional[dict]:
    if not isinstance(sheet, dict):
        return sheet
    out = {k: sheet[k] for k in COMPACT_KEEP if k in sheet}
    feats = sheet.get("features") or {}
    out["features"] = {side: {k: (feats.get(side) or {}).get(k) for k in COMPACT_FEATURES} for side in ("a", "b")}
    out["compact"] = True
    return out


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def build_read(sheet: dict, *, now: Any = None, situation: Optional[dict] = None) -> dict:
    """The written read of one fight. `sheet` is `matchup.matchup(...)`; `now` (optional, an ISO
    string or datetime) lets the market view say how old the prices are. `situation` (optional) is a
    `src.situation.ufc.situation_for_bout` record: it adds the short "Situation" block under its own
    key, and a read built without one has exactly the keys it always had.

    Never raises on a sparse sheet: a rule that fails is reported in `missing` as an error and the
    rest of the read is still produced.
    """
    ctx = _Ctx(sheet, now)
    items: List[dict] = []
    errors = []
    for rule in _RULES:
        try:
            items += rule(ctx)
        except Exception as exc:  # noqa: BLE001 -- one rule never takes the read down
            errors.append({"input": rule.__name__.replace("_r_", "").replace("_", " "), "status": "error",
                           "detail": f"this part could not be worked out from the sheet ({type(exc).__name__})"})
    order = {id(it): i for i, it in enumerate(items)}
    depth = _data_depth(ctx)
    try:
        market = _market_view(ctx, items, depth)
    except Exception as exc:  # noqa: BLE001
        market = {"available": False, "label": "What the price implies, set beside this read.",
                  "sentences": ["The price comparison could not be built from this sheet."], "evidence": [],
                  "agreement": "no price", "lean": "none", "lean_weight": 0.0}
        errors.append({"input": "The price", "status": "error", "detail": type(exc).__name__})
    try:
        history = _history(ctx)
    except Exception as exc:  # noqa: BLE001
        history = {"previous_meetings": [], "shared_opponents": [], "summary": "", "caveat": "", "evidence": []}
        errors.append({"input": "History", "status": "error", "detail": type(exc).__name__})

    headline, top = _headline(ctx, items, depth)
    fighters = {}
    for side in ("a", "b"):
        mine = [it for it in items if it["_side"] == side]
        try:
            routes = _routes(ctx, items, side)
        except Exception as exc:  # noqa: BLE001
            routes = []
            errors.append({"input": f"{ctx.short[side]}: routes to a win", "status": "error", "detail": type(exc).__name__})
        fighters[side] = {
            "fighter_id": (sheet.get(side) or {}).get("fighter_id"),
            "name": ctx.full[side],
            "strengths": [_public(i) for i in _rank([i for i in mine if i["kind"] == "strength"], order)[:MAX_ITEMS]],
            "weaknesses": [_public(i) for i in _rank([i for i in mine if i["kind"] == "weakness"], order)[:MAX_ITEMS]],
            "paths_to_victory": routes,
            "context": _context_for(ctx, side),
        }
    out = {
        "version": READ_VERSION,
        "label": LABEL,
        "as_of": ctx.as_of,
        "headline": headline,
        "headline_trait": top["trait"] if top else None,
        "notices": _notices(ctx),
        "data_depth": depth,
        "a": fighters["a"],
        "b": fighters["b"],
        "context": _shared_context(ctx),
        "history": history,
        "market_view": market,
        "what_would_change_it": _what_would_change_it(ctx, depth, market),
        "missing": _missing(ctx, depth) + errors,
    }
    try:
        block = _situation.page_block(situation, label=SITUATION_LABEL, limit=SITUATION_LINES)
    except Exception:  # noqa: BLE001 -- additive: a record that cannot be shown costs the block, not the read
        block = None
    if block is not None:
        out["situation"] = block
    return out
