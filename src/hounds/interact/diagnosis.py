"""The coach's diagnosis: a member hound's own settled bets, cut by every factor the ledger can honestly answer.

THE RULING (Brey, 2026-10-21): "Our training and evolution should be more than just a small change. Haiku should be
assessing multiple factors that could be the reason the hound is losing." ``training.analyse`` already cuts the bets by
sport, market, price band, side, favourite or underdog and rule. This module is the wider table that the coach reads, the
Haiku step reads, and the person watches resolve line by line (web/js/dog-diagnose.js).

EVERY NUMBER IS COMPUTED, FROM THE HOUND'S OWN SETTLED BETS
  * price band, favourite or underdog, home or away (or over or under), sport, market
  * day of the week (the slate day) and slate time (the game's start in Eastern time: early before 1 pm, afternoon 1 to 5
    pm, night from 5 pm)
  * rest: whether the team the hound picked played the day before (a back-to-back), from the schedule the rules engine
    already reads (``user_facts.FactBook.rest_days``); only for a pick on a side, never a total
  * line movement: whether the board's average price for the pick moved against it between the bet and the close
  * how many books quoted the price when the bet was taken
  * the days it bet and the days it did not, and the days it was stopped by its own daily limit
  * streak clustering: its longest losing run, and how often a run that long shows up when the same results are put in
    a random order (a seeded shuffle, so the number never changes between two reads)
  * each rule's contribution, for a hound with its own rules
  * pairs of the above that went wrong together ("away-side underdogs on back-to-backs"), kept only when they went wrong

NOTHING IS GUESSED. A factor the ledger cannot answer is a row that says so ("not checked") with its reason, never a
number. The rest and line-movement factors read stores a request does not own, so they come through a ``Context`` the
caller injects (tests inject fakes; ``diagnosis_live`` builds the real one); with none, they are named as not checked.

SAMPLE SIZE ON EVERY FINDING. Each factor carries its bets, its record, its units, and a level: ``too_few`` (under
``MIN_FACTOR_BETS`` bets: "too few bets to say"), ``low``, ``medium`` or ``high``. The level comes from the size of the
cut and from how far its units per bet sit from the rest of the hound's bets in standard errors (a plain two-sample
z). It is a statement about the past: it never says the hound will do better or worse. Looking at many cuts finds a bad
one by chance alone, so the table also says how many cuts were examined (``meta.cuts_examined``), and a pair cut can
never be rated above ``medium``.

THE RANKING is by size and confidence: for the cuts that lost units, units lost times a weight for the level (too few
0, low 0.35, medium 0.7, high 1), then the larger sample, then the id. Cuts too small to trust come after, marked.

Paper only. Nothing here places or suggests a bet.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from src.hounds import user_spec
from src.hounds.interact import rites, training

MIN_FACTOR_BETS = 5            # a cut under this is "too few bets to say"
MIN_COMBO_BETS = 4             # a pair cut under this is not even listed
COMBO_KEEP = 5                 # how many losing pair cuts are listed
MOVE_EPS = 1.0                 # points of win probability the board must move to count as a move (a smaller one is flat)
SHUFFLES = 2000                # seeded reorderings for the streak check
LONG_RUN = 3                   # a losing run this long is a cluster
EARLY_BEFORE_HOUR, AFTERNOON_BEFORE_HOUR = 13, 17      # Eastern hours that split early / afternoon / night
BOOKS_FEW_MAX, BOOKS_MID_MAX = 4, 7                    # books at bet time: few = 4 or fewer, mid = 5 to 7, many = 8+

LEVEL_WEIGHT = {"too_few": 0.0, "low": 0.35, "medium": 0.7, "high": 1.0}
LEVEL_TEXT = {"too_few": "too few bets to say", "low": "weak signal", "medium": "some signal", "high": "stronger signal"}

GROUPS = (                                         # the order the table and the screen read in
    ("overall", "All settled bets"), ("band", "Price band"), ("role", "Favourite or underdog"), ("venue", "Side"),
    ("sport", "Sport"), ("market", "Market"), ("dow", "Day of the week"), ("slate", "Slate time"), ("rest", "Rest"),
    ("move", "Line movement"), ("books", "Books quoting"), ("activity", "Betting days"), ("cap", "Daily limit"),
    ("rule", "Rules"), ("streak", "Streaks"), ("combo", "Pairs that went wrong together"))
GROUP_NAME = dict(GROUPS)
_GROUP_INDEX = {k: i for i, (k, _n) in enumerate(GROUPS)}

DOW_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SLATE_LABELS = {"early": "Early games (before 1 pm ET)", "afternoon": "Afternoon games (1 to 5 pm ET)",
                "night": "Night games (5 pm ET on)"}
REST_LABELS = {"b2b": "Picked team on a back-to-back", "rested": "Picked team with a day or more off"}
MOVE_LABELS = {"against": "Board moved against the pick before the close", "flat": "Board flat before the close",
               "with": "Board moved toward the pick before the close"}
BOOKS_LABELS = {"few": f"Few books quoting (up to {BOOKS_FEW_MAX})", "mid": f"Some books quoting ({BOOKS_FEW_MAX + 1} to {BOOKS_MID_MAX})",
                "many": f"Many books quoting ({BOOKS_MID_MAX + 1} or more)"}


# ---------------------------------------------------------------------------
# what a caller can inject (the things a request does not own)
# ---------------------------------------------------------------------------

@dataclass
class Context:
    """The stores behind the rest and line-movement factors. Each is optional; without one the factor is a row that says
    it was not checked, with the reason.

    ``rest_days(sport, team_name, slate_date, lock)`` -> days off since the team's last game (0 = played yesterday), or None
    when the schedule does not say. ``board_moves(bets)`` -> ``{bet_id: points}``: how far the board's average win
    probability for the pick moved between the bet and the close, in points (negative = against the pick), for the bets it
    could measure. ``reasons`` carries why a provider that was asked could not answer (``{"rest": "...", "move": "..."}``)."""
    rest_days: Optional[Callable[[str, str, str, Any], Optional[int]]] = None
    board_moves: Optional[Callable[[Sequence], Mapping]] = None
    reasons: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _eastern():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tz database on this machine: the project's own written-out US rules
        from src.data.eastern import EASTERN_FALLBACK
        return EASTERN_FALLBACK


def _moment(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def slate_bucket(start_utc) -> Optional[str]:
    """``early`` (before 1 pm Eastern), ``afternoon`` (1 to 5 pm) or ``night`` (5 pm on) for a game's start, or None."""
    moment = _moment(start_utc)
    if moment is None:
        return None
    hour = moment.astimezone(_eastern()).hour
    return "early" if hour < EARLY_BEFORE_HOUR else "afternoon" if hour < AFTERNOON_BEFORE_HOUR else "night"


def _day_of_week(date_text) -> Optional[int]:
    try:
        return date_cls.fromisoformat(str(date_text)[:10]).weekday()
    except ValueError:
        return None


def _books_bucket(count) -> Optional[str]:
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return None
    return "few" if count <= BOOKS_FEW_MAX else "mid" if count <= BOOKS_MID_MAX else "many"


def _record(w: int, l: int, p: int) -> str:
    return f"{w}-{l}" + (f"-{p}" if p else "")


def _fmt_units(u: float) -> str:
    return f"{u:+.1f}u"


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _var(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _z(seg: Sequence[float], rest: Sequence[float]) -> Optional[float]:
    """How many standard errors the segment's units per bet sit from the rest of the bets' (or from zero when the segment is
    every bet)."""
    if not seg:
        return None
    if len(rest) >= 2:
        se = math.sqrt(_var(seg) / len(seg) + _var(rest) / len(rest))
        diff = _mean(seg) - _mean(rest)
    else:
        se = math.sqrt(_var(seg) / len(seg))
        diff = _mean(seg)
    return None if se <= 1e-12 else diff / se


def level_of(n: int, z: Optional[float], *, cap: str = "high") -> str:
    """The sample-size level: too_few under MIN_FACTOR_BETS; else high / medium / low from the bets and the z."""
    if n < MIN_FACTOR_BETS:
        return "too_few"
    level = "low"
    if z is not None:
        if n >= 20 and abs(z) >= 1.96:
            level = "high"
        elif n >= 10 and abs(z) >= 1.0:
            level = "medium"
    order = ("low", "medium", "high")
    return order[min(order.index(level), order.index(cap))]


def _tone(direction: str, level: str) -> str:
    if level == "too_few":
        return "thin"
    if direction == "against":
        return "weak" if level in ("medium", "high") else "soft"
    return "ok"


# ---------------------------------------------------------------------------
# one factor
# ---------------------------------------------------------------------------

def _factor(fid: str, group: str, label: str, rows: Sequence[Mapping], rest: Sequence[Mapping], *, kind: str = "segment",
            level_cap: str = "high", note: str = "", min_n: int = 1) -> Optional[dict]:
    n = len(rows)
    if n < min_n or n == 0:
        return None
    if not rest and kind == "segment":
        kind = "whole"          # a cut that holds every bet is the whole record again: shown, never ranked, never a reason
    wins = sum(1 for r in rows if r["result"] == "win")
    losses = sum(1 for r in rows if r["result"] == "loss")
    pushes = n - wins - losses
    units = round(sum(r["units"] for r in rows), 2)
    seg_u, rest_u = [r["units"] for r in rows], [r["units"] for r in rest]
    z = _z(seg_u, rest_u)
    level = level_of(n, z, cap=level_cap)
    direction = "against" if units < 0 else "for" if units > 0 else "even"
    if kind == "whole":
        direction = "even"
    upb = round(units / n, 3)
    rest_upb = round(_mean(rest_u), 3) if rest_u else None
    line = f"{label}: {_record(wins, losses, pushes)}, {_fmt_units(units)}"
    if note:
        line += f" ({note})"
    return {"id": fid, "group": group, "kind": kind, "label": label, "n": n, "wins": wins, "losses": losses, "pushes": pushes,
            "units": units, "units_per_bet": upb, "rest_units_per_bet": rest_upb,
            "win_pct": round(100.0 * wins / (wins + losses), 1) if wins + losses else None,
            "z": None if z is None else round(z, 2), "level": level, "level_text": LEVEL_TEXT[level], "direction": direction,
            "tone": "ok" if kind == "whole" else _tone(direction, level), "note": note, "line": line}


def _score(f: Mapping) -> float:
    return max(0.0, -f["units"]) * LEVEL_WEIGHT[f["level"]]


# ---------------------------------------------------------------------------
# the facts behind every cut
# ---------------------------------------------------------------------------

def _raw_index(rows: Optional[Sequence]) -> dict:
    out: dict = {}
    for r in rows or ():
        if isinstance(r, Mapping) and r.get("bet_id") and (r.get("away_team") or r.get("home_team")):
            out.setdefault(r["bet_id"], r)
    return out


def _bet_facts(bets: Sequence, spec: Mapping, rule_index: Optional[Mapping], raw: Mapping, ctx: Context,
               moves: Mapping) -> list:
    out = []
    for b in bets:
        if b.result not in rites.SETTLED_RESULTS:
            continue
        price = b.price_average if b.price_average is not None else b.price
        side = b.side if b.side in training.VENUE_LABELS else None
        row = raw.get(b.bet_id) or {}
        sport = str(b.sport or "").upper() or None
        rest = None
        if ctx.rest_days is not None and side in ("home", "away") and sport:
            team = row.get("home_team" if side == "home" else "away_team")
            slate = str(row.get("slate_date") or row.get("date") or b.date or "")[:10]
            if team and slate:
                try:
                    rest = ctx.rest_days(sport, team, slate, row.get("lock_utc") or b.decision_utc)
                except Exception:  # noqa: BLE001 -- a schedule that cannot answer is "not known", never a crash
                    rest = None
        move = moves.get(b.bet_id)
        out.append({
            "bet_id": b.bet_id, "result": b.result, "units": training._units_of(b), "sport": sport,   # noqa: SLF001
            "market": training.market_of(b), "band": training.band_of(price), "venue": side, "role": training.role_of(b),
            "rule": (rule_index or {}).get(b.bet_id) if user_spec.is_v2(spec) else None,
            "dow": _day_of_week(b.date), "slate": slate_bucket(b.start_utc or row.get("commence_time")),
            "rest": (None if rest is None else "b2b" if rest == 0 else "rested"),
            "move": (None if not isinstance(move, (int, float)) or isinstance(move, bool) else
                     "against" if move <= -MOVE_EPS else "with" if move >= MOVE_EPS else "flat"),
            "books": _books_bucket(b.book_count), "date": b.date,
            "order": str(b.start_utc or b.decision_utc or b.date or "") + "|" + str(b.bet_id)})
    out.sort(key=lambda r: r["order"])
    return out


_LABELERS = {
    "band": lambda spec, k: _band_label(k),
    "role": lambda spec, k: training.ROLE_LABELS[k].capitalize() + "s",
    "venue": lambda spec, k: training.VENUE_LABELS[k].capitalize() + " bets",
    "sport": lambda spec, k: training._label(spec, "sport", k)[0] + " bets",       # noqa: SLF001
    "market": lambda spec, k: training._label(spec, "market", k)[0].capitalize() + " bets",   # noqa: SLF001
    "dow": lambda spec, k: DOW_NAMES[k] + " slates",
    "slate": lambda spec, k: SLATE_LABELS[k], "rest": lambda spec, k: REST_LABELS[k],
    "move": lambda spec, k: MOVE_LABELS[k], "books": lambda spec, k: BOOKS_LABELS[k],
}


def _band_label(key: str) -> str:
    _k, _name, rng, _lo, _hi = training.PRICE_BANDS[training._BAND_BY_KEY[key]]    # noqa: SLF001
    return f"Price {rng}"


def _plain_rule_label(spec: Mapping, key) -> str:
    """"Rule 2" -- the position only. A rule's own label is the owner's free text and never goes on a screen or to a model."""
    return f"Rule {key + 1}" if isinstance(key, int) else f"Rule {key}"


def _label(spec: Mapping, group: str, key) -> str:
    if group == "rule":
        return _plain_rule_label(spec, key)
    return _LABELERS[group](spec, key)


def _segments(rows: Sequence[Mapping], group: str, spec: Mapping, *, order=None, min_distinct: int = 1) -> list:
    """The factors of one grouping (``band``, ``sport``...): one per value present, each against the rest of the bets."""
    groups: dict = {}
    for r in rows:
        v = r.get(group)
        if v is not None:
            groups.setdefault(v, []).append(r)
    if len(groups) < min_distinct:
        return []
    keys = sorted(groups, key=order or (lambda k: (str(type(k)), k)))
    out = []
    for k in keys:
        mine = groups[k]
        ids = {id(x) for x in mine}
        rest = [r for r in rows if id(r) not in ids]
        f = _factor(f"{group}:{k}", group, _label(spec, group, k), mine, rest)
        if f:
            out.append(f)
    return out


def _others(rows: Sequence[Mapping], mine: Sequence[Mapping]) -> list:
    """The rows that are not in ``mine`` (by identity: a bet is in a cut or it is not)."""
    ids = {id(x) for x in mine}
    return [r for r in rows if id(r) not in ids]


def _coverage_note(rows: Sequence[Mapping], key: str, what: str) -> str:
    known = sum(1 for r in rows if r.get(key) is not None)
    return "" if known == len(rows) else f"{what} for {known} of {len(rows)}"


# ---------------------------------------------------------------------------
# the pairs that went wrong together
# ---------------------------------------------------------------------------

_PAIRS = (("venue", "role"), ("role", "rest"), ("venue", "rest"), ("band", "venue"), ("sport", "venue"), ("slate", "venue"),
          ("role", "move"))


def _combo_label(parts: Sequence[tuple], spec: Mapping) -> str:
    d = dict(parts)
    sport = d.get("sport")
    venue = training.VENUE_LABELS[d["venue"]] if "venue" in d else None
    noun = (training.ROLE_LABELS[d["role"]] + "s") if "role" in d else "bets"
    pieces = [x for x in (sport, venue) if x]
    pieces.append(noun)
    if "rest" in d:
        pieces.append("on back-to-backs" if d["rest"] == "b2b" else "with a day or more off")
    if "band" in d:
        pieces.append("priced " + training.PRICE_BANDS[training._BAND_BY_KEY[d["band"]]][2])   # noqa: SLF001
    if "slate" in d:
        pieces.append({"early": "in early games", "afternoon": "in afternoon games", "night": "in night games"}[d["slate"]])
    if "move" in d:
        pieces.append({"against": "when the board moved against them", "with": "when the board moved toward them",
                       "flat": "when the board stayed flat"}[d["move"]])
    text = " ".join(pieces)
    return text[:1].upper() + text[1:]


def _combos(rows: Sequence[Mapping], spec: Mapping) -> tuple:
    examined = 0
    found: list = []
    # a pair that holds exactly the bets of one of its parts (or of an earlier pair) says nothing new, so it is not listed
    seen: set = set()
    for dim in {d for pair in _PAIRS for d in pair}:
        parts: dict = {}
        for r in rows:
            if r.get(dim) is not None:
                parts.setdefault(r[dim], set()).add(r["bet_id"])
        seen.update(frozenset(v) for v in parts.values())
    for a, b in _PAIRS:
        cells: dict = {}
        for r in rows:
            if r.get(a) is not None and r.get(b) is not None:
                cells.setdefault((r[a], r[b]), []).append(r)
        for (ka, kb), mine in sorted(cells.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            examined += 1
            if len(mine) < MIN_COMBO_BETS:
                continue
            sig = frozenset(r["bet_id"] for r in mine)
            if sig in seen:
                continue
            seen.add(sig)
            ids = {id(x) for x in mine}
            rest = [r for r in rows if id(r) not in ids]
            f = _factor(f"combo:{a}:{ka}+{b}:{kb}", "combo", _combo_label(((a, ka), (b, kb)), spec), mine, rest,
                        kind="combo", level_cap="medium")
            if f and f["units"] < 0:
                found.append(f)
    found.sort(key=lambda f: (f["units"], -f["n"], f["id"]))
    return found[:COMBO_KEEP], examined


# ---------------------------------------------------------------------------
# streaks
# ---------------------------------------------------------------------------

def _runs(seq: Sequence[str]) -> list:
    """Lengths of the consecutive-loss runs in a sequence of "W" / "L" (a push is skipped before this is called)."""
    runs, cur = [], 0
    for s in seq:
        if s == "L":
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


def streak_check(rows: Sequence[Mapping]) -> dict:
    """The losing-run facts for bets already in time order: the longest run, the runs of ``LONG_RUN`` or more, and the share of
    seeded random orderings of the same wins and losses whose longest losing run is at least as long (``chance``)."""
    seq = ["L" if r["result"] == "loss" else "W" for r in rows if r["result"] in ("win", "loss")]
    runs = _runs(seq)
    longest = max(runs) if runs else 0
    seed = hashlib.sha1("|".join(r["bet_id"] for r in rows).encode("utf-8")).hexdigest()
    rng = random.Random(seed)
    hits = 0
    pool = list(seq)
    for _ in range(SHUFFLES):
        rng.shuffle(pool)
        runs_s = _runs(pool)
        if (max(runs_s) if runs_s else 0) >= longest:
            hits += 1
    return {"longest": longest, "long_runs": sum(1 for r in runs if r >= LONG_RUN), "chance": round(hits / SHUFFLES, 3),
            "n": len(seq)}


def _streak_factor(rows: Sequence[Mapping]) -> Optional[dict]:
    decided = [r for r in rows if r["result"] in ("win", "loss")]
    if len(decided) < MIN_FACTOR_BETS:
        return None
    info = streak_check(rows)
    if info["longest"] < LONG_RUN:
        return {"id": "streak:losing_runs", "group": "streak", "kind": "streak", "label": "Losing runs", "n": len(decided),
                "wins": None, "losses": None, "pushes": None, "units": 0.0, "units_per_bet": None, "rest_units_per_bet": None,
                "win_pct": None, "z": None, "level": "low", "level_text": LEVEL_TEXT["low"], "direction": "even", "tone": "ok",
                "note": "", "streak": info, "line": f"Losing runs: longest {info['longest']}, no cluster of {LONG_RUN} or more"}
    # the bets inside the runs of LONG_RUN or more form the segment
    inside, cur = [], []
    for r in rows:
        if r["result"] == "loss":
            cur.append(r)
        elif r["result"] == "win":
            if len(cur) >= LONG_RUN:
                inside.extend(cur)
            cur = []
    if len(cur) >= LONG_RUN:
        inside.extend(cur)
    units = round(sum(r["units"] for r in inside), 2)
    p = info["chance"]
    level = "too_few" if len(decided) < 10 else "high" if p <= 0.05 else "medium" if p <= 0.2 else "low"
    pct = round(p * 100)
    return {"id": "streak:losing_runs", "group": "streak", "kind": "streak", "label": "Losing runs", "n": len(inside),
            "wins": 0, "losses": len(inside), "pushes": 0, "units": units, "units_per_bet": round(units / len(inside), 3),
            "rest_units_per_bet": None, "win_pct": 0.0, "z": None, "level": level, "level_text": LEVEL_TEXT[level],
            "direction": "against", "tone": _tone("against", level), "note": f"{pct}% chance", "streak": info,
            "line": (f"Losing runs: longest {info['longest']} in a row, {len(inside)} losses in runs of {LONG_RUN}+ "
                     f"({_fmt_units(units)}); a run that long turns up in {pct}% of random orders of the same results")}


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------

def _activity(rows: Sequence[Mapping], spec: Mapping) -> tuple:
    """``(activity factor, cap factor)``: how many days it bet, and the bets placed on days it hit its daily limit."""
    days = sorted({r["date"] for r in rows if r.get("date")})
    if not days:
        return None, None
    first, last = date_cls.fromisoformat(days[0]), date_cls.fromisoformat(days[-1])
    span = (last - first).days + 1
    per_day: dict = {}
    for r in rows:
        if r.get("date"):
            per_day.setdefault(r["date"], []).append(r)
    cap = spec.get("max_bets_per_day")
    at_cap = sorted(d for d, v in per_day.items() if isinstance(cap, int) and len(v) >= cap)
    idle = span - len(days)
    text = f"Bet on {len(days)} of {span} days"
    if span == len(days):
        text = f"Bet on every one of {span} days"
    if isinstance(cap, int) and at_cap:
        text += f", stopped by its limit of {cap} a day on {len(at_cap)}"
    activity = {"id": "activity:days", "group": "activity", "kind": "context", "label": "Betting days", "n": len(rows),
                "wins": None, "losses": None, "pushes": None, "units": None, "units_per_bet": None, "rest_units_per_bet": None,
                "win_pct": None, "z": None, "level": "low", "level_text": "", "direction": "even", "tone": "ok", "note": "",
                "days_bet": len(days), "days_span": span, "days_idle": idle, "days_at_limit": len(at_cap),
                "bets_per_bet_day": round(len(rows) / len(days), 2), "passes_recorded": False,
                "line": text + (f"; {idle} {'day' if idle == 1 else 'days'} with no ticket" if idle else "")}
    capped = None
    if at_cap:
        mine = [r for d in at_cap for r in per_day[d]]
        if 0 < len(mine) < len(rows):
            ids = {id(x) for x in mine}
            rest = [r for r in rows if id(r) not in ids]
            capped = _factor("cap:at_limit", "cap", f"Days it hit its limit of {cap} a day", mine, rest)
    return activity, capped


def _unavailable(fid: str, group: str, label: str, reason: str) -> dict:
    return {"id": fid, "group": group, "kind": "unavailable", "label": label, "n": 0, "wins": None, "losses": None, "pushes": None,
            "units": None, "units_per_bet": None, "rest_units_per_bet": None, "win_pct": None, "z": None, "level": "too_few",
            "level_text": "", "direction": "even", "tone": "none", "note": reason, "line": f"{label}: not checked ({reason})"}


def diagnose(bets: Sequence, spec: Mapping, *, rows: Optional[Sequence] = None, rule_index: Optional[Mapping] = None,
             context: Optional[Context] = None) -> dict:
    """The diagnosis table for a hound's bets.

    ``{"version", "settled", "overall", "rows": [factor...], "ranked": [factor id...], "holding": [factor id...],
    "meta": {...}}`` where ``rows`` is every cut that was checked, in screen order (``GROUPS``), each with its own
    ``line`` of text; ``ranked`` is the ids of the cuts that lost units, best case first (``rank_key``); ``holding`` the
    cuts above zero. Deterministic: the same bets give the same table, byte for byte."""
    ctx = context or Context()
    raw = _raw_index(rows)
    settled_bets = [b for b in bets if b.result in rites.SETTLED_RESULTS]
    moves: Mapping = {}
    if ctx.board_moves is not None and settled_bets:
        try:
            moves = ctx.board_moves(settled_bets) or {}
        except Exception:  # noqa: BLE001 -- the closing odds could not be read: the factor is "not checked"
            moves = {}
            ctx.reasons.setdefault("move", "the closing odds could not be read just now")
    facts = _bet_facts(settled_bets, spec, rule_index, raw, ctx, moves)
    n = len(facts)
    out: list = []
    unavailable: list = []

    overall = _factor("overall", "overall", "All settled bets", facts, [], kind="context") if facts else None
    if overall:
        overall["level"] = level_of(n, None)
        overall["level_text"] = LEVEL_TEXT[overall["level"]]
        overall["tone"] = "ok"
        out.append(overall)

    band_order = lambda k: training._BAND_BY_KEY[k]    # noqa: E731, SLF001
    out += _segments(facts, "band", spec, order=band_order)
    out += _segments(facts, "role", spec)
    out += _segments(facts, "venue", spec, order=lambda k: ("home", "away", "over", "under").index(k))
    out += _segments(facts, "sport", spec)
    out += _segments(facts, "market", spec)
    out += _segments(facts, "dow", spec)
    out += _segments(facts, "slate", spec, order=lambda k: ("early", "afternoon", "night").index(k))

    # rest: only the side bets, and only if a schedule answered for them
    side_bets = [r for r in facts if r["venue"] in ("home", "away")]
    rest_known = [r for r in facts if r["rest"] is not None]
    if rest_known:
        note = _coverage_note(side_bets, "rest", "schedule on file") if side_bets else ""
        rest_pool = rest_known
        for k in ("b2b", "rested"):
            mine = [r for r in rest_pool if r["rest"] == k]
            rest = _others(facts, mine)
            f = _factor(f"rest:{k}", "rest", REST_LABELS[k], mine, rest, note=note)
            if f:
                out.append(f)
    else:
        reason = ctx.reasons.get("rest") or ("no schedule was loaded for this read" if ctx.rest_days is None else
                                            "the schedule did not cover these bets" if side_bets else "no side bets (only totals or props)")
        unavailable.append(_unavailable("rest:none", "rest", "Rest days", reason))

    # line movement
    moved = [r for r in facts if r["move"] is not None]
    if moved:
        against_n = sum(1 for r in moved if r["move"] == "against")
        pct = int(100.0 * against_n / len(moved) + 0.5)
        out.append({"id": "move:share", "group": "move", "kind": "context", "label": "Line movement", "n": len(moved), "wins": None,
                    "losses": None, "pushes": None, "units": None, "units_per_bet": None, "rest_units_per_bet": None, "win_pct": None,
                    "z": None, "level": "too_few" if len(moved) < MIN_FACTOR_BETS else "low", "level_text": "", "direction": "even",
                    "tone": "thin" if len(moved) < MIN_FACTOR_BETS else "soft" if pct > 50 else "ok", "note": "",
                    "against": against_n, "measured": len(moved),
                    "line": (f"Board moved against {against_n} of {len(moved)} measured picks ({pct}%)"
                             + (" - too few to say" if len(moved) < MIN_FACTOR_BETS else ""))})
        note = _coverage_note(facts, "move", "closing odds")
        for k in ("against", "flat", "with"):
            mine = [r for r in moved if r["move"] == k]
            rest = _others(facts, mine)
            f = _factor(f"move:{k}", "move", MOVE_LABELS[k], mine, rest, note=note)
            if f:
                out.append(f)
    else:
        reason = ctx.reasons.get("move") or ("closing odds were not loaded for this read" if ctx.board_moves is None else
                                            "no closing odds were on file for these bets")
        unavailable.append(_unavailable("move:none", "move", "Line movement", reason))

    # books at bet time
    books_known = [r for r in facts if r["books"] is not None]
    if books_known:
        note = _coverage_note(facts, "books", "book count")
        for k in ("few", "mid", "many"):
            mine = [r for r in books_known if r["books"] == k]
            f = _factor(f"books:{k}", "books", BOOKS_LABELS[k], mine, _others(facts, mine), note=note)
            if f:
                out.append(f)
    else:
        unavailable.append(_unavailable("books:none", "books", "Books quoting", "the tickets do not record how many books quoted"))
    unavailable.append(_unavailable("consensus:none", "books", "Consensus price at bet time",
                                    "a member hound's ticket does not store a consensus value"))

    activity, capped = _activity(facts, spec)
    if activity:
        out.append(activity)
    if capped:
        out.append(capped)

    if user_spec.is_v2(spec):
        rule_cuts = _segments(facts, "rule", spec, order=lambda k: k)
        total = training._tally(facts)["units"]          # noqa: SLF001
        for f in rule_cuts:                              # each rule's contribution: its units against the whole record's
            f["note"] = f"of {_fmt_units(total)} in all"
            f["line"] += f" ({f['note']})"
        out += rule_cuts

    streak = _streak_factor(facts)
    if streak:
        out.append(streak)

    combos, combo_examined = _combos(facts, spec)
    out += combos

    out += unavailable
    out.sort(key=lambda f: _GROUP_INDEX[f["group"]])           # stable: within a group the order built above stays
    cuts = sum(1 for f in out if f["kind"] in ("segment", "combo", "streak")) + (combo_examined - len(combos))
    ranked = rank(out)
    holding = [f["id"] for f in sorted((f for f in out if f["kind"] in ("segment", "combo") and f["direction"] == "for"
                                         and f["level"] != "too_few"), key=lambda f: (-f["units"], -f["n"], f["id"]))][:3]
    meta = {"cuts_examined": cuts, "min_factor_bets": MIN_FACTOR_BETS, "rest_known": len(rest_known), "move_known": len(moved),
            "books_known": len(books_known),
            "note": ("Many cuts were examined, so one of them looks bad by chance alone. These are facts about the past, not a "
                     "forecast.")}
    return {"version": 1, "settled": n, "overall": _overall(facts), "rows": out, "ranked": ranked, "holding": holding, "meta": meta,
            "paper_only": True}


def _overall(facts: Sequence[Mapping]) -> dict:
    return training._tally(facts)       # noqa: SLF001 -- {n, wins, losses, pushes, units}


def rank_key(f: Mapping) -> tuple:
    """Sort key for the cuts that lost units: the trusted ones by size and confidence first, the too-small ones after."""
    return (f["level"] == "too_few", -_score(f), f["units"], -f["n"], f["id"])


def rank(rows: Sequence[Mapping]) -> list:
    """Ids of the cuts that lost units (segment, pair and streak cuts), ranked by size and confidence. Too-small cuts last."""
    lost = [f for f in rows if f["kind"] in ("segment", "combo", "streak") and f["direction"] == "against"]
    return [f["id"] for f in sorted(lost, key=rank_key)]


def by_id(diagnosis: Mapping) -> dict:
    return {f["id"]: f for f in diagnosis.get("rows", ())}


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def sentence(f: Mapping) -> str:
    """One plain sentence about a cut, from its own numbers. A fact about the past; no forecast."""
    if f["kind"] == "streak":
        return f["line"]
    rec = _record(f["wins"], f["losses"], f["pushes"])
    tail = f" ({LEVEL_TEXT[f['level']]})" if f["level"] == "too_few" else ""
    return f"{f['label']}: {rec} over {f['n']} {'bet' if f['n'] == 1 else 'bets'}, {_fmt_units(f['units'])}{tail}."


def rules_reasons(diagnosis: Mapping, limit: int = 3) -> list:
    """The deterministic read: the top ranked cuts as reasons, in the engine's own words (no model involved)."""
    table = by_id(diagnosis)
    out = []
    for fid in diagnosis.get("ranked", ()):
        f = table[fid]
        if f["level"] == "too_few" and out:
            continue                       # a too-small cut leads only when nothing else lost
        out.append({"factors": [fid], "text": sentence(f), "confidence": f["level"] if f["level"] != "too_few" else "low",
                    "level": f["level"]})
        if len(out) >= limit:
            break
    return out


def numbers_in(f: Mapping) -> set:
    """Every number a sentence about this cut could honestly contain, as the strings a reader would see."""
    vals: set = set()

    def add(x):
        if x is None or isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            for fmt in ("{:g}", "{:.1f}", "{:.2f}", "{:+.1f}", "{:+.2f}"):
                vals.add(fmt.format(x))
                vals.add(fmt.format(abs(x)))
            if float(x).is_integer():
                vals.add(str(int(abs(x))))
        elif isinstance(x, str):
            vals.update(re.findall(r"\d+(?:\.\d+)?", x))

    for key in ("n", "wins", "losses", "pushes", "units", "units_per_bet", "win_pct", "z"):
        add(f.get(key))
    add(f.get("label"))
    add(f.get("note"))
    info = f.get("streak") or {}
    for key in ("longest", "long_runs", "n"):
        add(info.get(key))
    if info.get("chance") is not None:
        add(round(info["chance"] * 100))
    return vals


def compact(diagnosis: Mapping) -> dict:
    """The table cut down to what travels to the model and into the stored event: ids, labels, counts and units. No bet id,
    no team, no name, no rule label (a rule is only "Rule 2")."""
    rows = []
    for f in diagnosis["rows"]:
        if f["kind"] == "unavailable":
            rows.append({"id": f["id"], "state": "not_checked", "why": f["note"]})
            continue
        row = {"id": f["id"], "label": f["label"], "n": f["n"], "level": f["level"]}
        if f["kind"] == "context":
            row["line"] = f["line"]
        elif f["kind"] == "streak":
            row["line"] = f["line"]
            row.update(longest=f["streak"]["longest"], chance=f["streak"]["chance"])
        else:
            row.update(w=f["wins"], l=f["losses"], p=f["pushes"], units=f["units"], upb=f["units_per_bet"],
                       rest_upb=f["rest_units_per_bet"], z=f["z"])
        rows.append(row)
    return {"settled": diagnosis["settled"], "overall": diagnosis["overall"], "rows": rows, "ranked": diagnosis["ranked"],
            "cuts_examined": diagnosis["meta"]["cuts_examined"], "min_bets": MIN_FACTOR_BETS}
