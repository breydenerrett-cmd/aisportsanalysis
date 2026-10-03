"""A written read of one game, generated deterministically from the game page's
own data.

WHY THIS EXISTS
---------------
The game page showed tables and no reasoning. The owner's verdict was that
the matchup analysis was "barely analytical, just a couple of numbers", and he
was right: a reader had to do the weighing in their head. This module does the
weighing, out loud, in plain words, and shows its work.

WHAT IT IS, AND WHAT IT IS NOT
------------------------------
It is a DESCRIPTION. Every sentence is built from fields already in the game
payload (plus a small `read_inputs` block that says how old each store behind
the payload is, see `src.pipeline.read_context`). Nothing is fetched, nothing
is remembered about a player from outside the payload, and no sentence names a
fact that has no path back to a field. Every `evidence` entry carries that
path, and `tests/test_matchup_read.py` resolves each one against the payload.

It is not a prediction and not advice. It makes no profit claim and no edge
claim, it publishes no win probability, and it never touches a pick, a gate or
a record. Our own research record found no betting advantage in features like
these, and the read says so rather than letting a tidy paragraph suggest
otherwise. Where it disagrees with the market price, the read says the likelier
explanation is that our inputs are thin, not that the price is wrong.

THE FACTORS, AND HOW EACH ONE IS DOWN-WEIGHTED
-----------------------------------------------
Each factor carries a size (slight, moderate, large) and a confidence (low,
medium, high). Ranking multiplies the two, so a large gap on thin or stale
data ranks below a moderate gap on solid data. The thresholds are design
choices, set in advance, never tuned against results, and `docs/MATCHUP_READ.md`
states each one with its reason.

Stale or thin data is never used silently. Two rules do the work:

  * Every store has an age against the game date (`read_inputs`). A store that
    ends days before first pitch is named in `missing`, and any factor built
    on it has its confidence capped and says so in its caveat.
  * A rate carries its sample. Below the stated floor the factor is still
    shown when that is informative, at low confidence, with the sample in the
    sentence.

THE RUN ENVIRONMENT REUSES THE CARD MODEL'S PUBLISHED ARITHMETIC
-----------------------------------------------------------------
`run_environment` calls `src.analysis.strength.run_means`, the same unfitted
run arithmetic the rest of the product uses, rather than carrying a second
formula that could drift from it. What this module adds is the sentence form
of each step and a range built from the sampling error of the season rates.
It is an estimate with no track record, and says that.

Pure. stdlib only, no I/O. The payload is read, never modified.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from src.analysis import strength
from src.data import labels
from src.situation import record as situation_record

# ---------------------------------------------------------------------------
# Thresholds. Fixed in advance; each is justified in docs/MATCHUP_READ.md.
# ---------------------------------------------------------------------------

# Starting pitching: FIP gap in runs per nine. 1.00 over a six inning start is
# two thirds of a run; 0.25 is about a sixth of a run.
FIP_SLIGHT, FIP_MODERATE, FIP_LARGE = 0.25, 0.50, 1.00
# Innings behind a starter's line: below the first a rate is mostly noise,
# below the second it is still loose.
INNINGS_LOW, INNINGS_MEDIUM = 60.0, 120.0
# ERA versus FIP: a gap this wide is results running ahead of (or behind) the
# strikeouts, walks and homers underneath them.
REGRESSION_GAP = 0.50
REGRESSION_MIN_INNINGS = 50.0
# Last three starts versus the season, in earned runs per nine.
FORM_DELTA = 1.50
FORM_IP_DROP = 0.75
# Home runs per nine, gap between the two starters.
HR9_SLIGHT, HR9_MODERATE = 0.40, 0.80
PARK_HIGH, PARK_LOW = 1.05, 0.95
ALTITUDE_HIGH_M = 1000
# Platoon advantage share of a lineup (one hitter of nine is 0.111).
PLATOON_SLIGHT, PLATOON_MODERATE, PLATOON_LARGE = 0.20, 0.30, 0.40
# wOBA gaps, pooled across a lineup or an arsenal. Design choices: three steps
# of roughly doubling size, set before any result was looked at.
DEPTH_SLIGHT, DEPTH_MODERATE, DEPTH_LARGE = 0.010, 0.020, 0.035
MIX_SLIGHT, MIX_MODERATE, MIX_LARGE = 0.015, 0.030, 0.050
ARSENAL_SLIGHT, ARSENAL_MODERATE, ARSENAL_LARGE = 0.015, 0.030, 0.050
ARSENAL_PA_FLOOR, ARSENAL_PA_MEDIUM = 60, 200
MIX_PA_LOW = 150
HALF_PA_FLOOR = 60
# Season run margin per game; 1.00 is the same bar the talent scan uses.
MARGIN_SLIGHT, MARGIN_MODERATE, MARGIN_LARGE = 0.25, 0.50, 1.00
# Recent run margin, relative to the club's own season margin. Ten games is
# so noisy that the factor is capped at slight whatever the gap.
RECENT_SLIGHT = 0.75
# Batter against pitcher, aggregate average gap, capped at slight.
BVP_AVG_GAP = 0.040
BVP_MIN_AB = 40
# Weather and park.
TEMP_WARM_F, TEMP_COLD_F = 85.0, 55.0
PRECIP_FLAG_PCT = 40
WIND_FLAG_MPH = 12.0
# Bullpen, availability points: likely unavailable counts two, questionable one.
PEN_SLIGHT, PEN_MODERATE = 2, 4
# Travel flags.
TRAVEL_MILES, TRAVEL_ZONES = 1500, 2
# How far apart two expected run totals must be to name a leader.
RUN_LEAD_MIN = 0.25
# Net lean of the whole read below which it declines to name a side.
LEAN_MIN = 1.2

# Staleness, in days between the newest record in a store and the game date.
RESULTS_STALE_DAYS = 2
PITCHER_STALE_DAYS = 7
BULLPEN_STALE_DAYS = 3
FORECAST_HOURS = 3.0

_SIZE_RANK = {"slight": 1, "moderate": 2, "large": 3}
_SIZE_BY_RANK = {1: "slight", 2: "moderate", 3: "large"}
_CONF_RANK = {"low": 0, "medium": 1, "high": 2}
_CONF_MULT = {"low": 0.3, "medium": 0.6, "high": 1.0}

LABEL = ("A written description of this game built only from the data on this "
         "page. It is not a prediction, not advice, and not a claim that any "
         "price is wrong.")
RUN_LABEL = ("An estimate built from season averages. It has no track record "
             "and is not a prediction of the score.")
RESEARCH_NOTE = ("In our own pre-registered tests of features like these "
                 "against the market, none held up as a betting advantage. "
                 "Treat everything above as a description of the game.")

# The short "Situation" block (src/situation/): where each club stands going into the game, in
# sentences with their samples. Added to the read only when the page hands one in.
SITUATION_LABEL = ("Where each club stands going into this game, from games before it. A description of "
                   "the situation, not a forecast and not a claim that the price is wrong.")
SITUATION_LINES = 6

_GAME_TYPES = {"R": "regular season", "F": "wild card series", "D": "division series",
               "L": "league championship series", "W": "world series",
               "S": "spring training", "E": "exhibition"}
_STARTED_STATES = {"in progress", "final", "game over", "completed early",
                   "manager challenge", "delayed", "suspended"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def resolve_path(payload: Any, path: str):
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


def _num(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _fmt(value, places=2) -> str:
    number = _num(value)
    return "unknown" if number is None else f"{number:.{places}f}"


def _pct(value, places=1) -> str:
    number = _num(value)
    return "unknown" if number is None else f"{number * 100:.{places}f}%"


def _size(gap: Optional[float], slight: float, moderate: float,
          large: float) -> Optional[str]:
    if gap is None:
        return None
    gap = abs(gap)
    if gap >= large:
        return "large"
    if gap >= moderate:
        return "moderate"
    if gap >= slight:
        return "slight"
    return None


def _shift(size: Optional[str], steps: int) -> Optional[str]:
    """Move a size up or down; below slight it disappears (None)."""
    if size is None:
        return None
    rank = _SIZE_RANK[size] + steps
    if rank < 1:
        return None
    return _SIZE_BY_RANK[min(rank, 3)]


def _cap(conf: str, ceiling: str) -> str:
    return conf if _CONF_RANK[conf] <= _CONF_RANK[ceiling] else ceiling


def _days_between(earlier: Optional[str], later: Optional[str]) -> Optional[int]:
    from datetime import date
    try:
        a = date.fromisoformat(str(earlier)[:10])
        b = date.fromisoformat(str(later)[:10])
    except (TypeError, ValueError):
        return None
    return (b - a).days


def _cap1(text: str) -> str:
    """Capitalise the first letter only, leaving club names as they are."""
    return text[:1].upper() + text[1:]


def _plural(n, word, many=None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {many or word + 's'}"


def _join(items) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------------------
# Context: the payload, read once, with every staleness fact computed once
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, payload: dict):
        self.payload = payload or {}
        self.advanced = self.payload.get("advanced") or {}
        self.sections = self.advanced.get("sections") or {}
        self.gaps = self.advanced.get("gaps") or {}
        self.game = self.advanced.get("game") or {}
        self.inputs = self.payload.get("read_inputs") or {}
        self.away = self.game.get("away_team") or "away"
        self.home = self.game.get("home_team") or "home"
        self.date = self.game.get("date")
        self.as_of = self.advanced.get("information_time")
        self.missing: list = []
        self._missing_keys: set = set()

        results = (self.inputs.get("results") or {}).get("through")
        pitcher = (self.inputs.get("pitcher_logs") or {}).get("through")
        pen = (self.inputs.get("bullpen_log") or {}).get("through")
        self.results_through = results
        self.pitcher_through = pitcher
        self.bullpen_through = pen
        self.results_days = _days_between(results, self.date)
        self.pitcher_days = _days_between(pitcher, self.date)
        self.bullpen_days = _days_between(pen, self.date)
        self.results_stale = (self.results_days is None
                              or self.results_days > RESULTS_STALE_DAYS)
        self.pitcher_stale = (self.pitcher_days is None
                              or self.pitcher_days > PITCHER_STALE_DAYS)
        self.bullpen_stale = (self.bullpen_days is None
                              or self.bullpen_days > BULLPEN_STALE_DAYS)

    # -- naming -----------------------------------------------------------

    def club(self, side_or_abbr: str) -> str:
        abbr = self.abbr(side_or_abbr)
        return labels.team_name(abbr, "name") or abbr

    def abbr(self, side_or_abbr: str) -> str:
        if side_or_abbr == "away":
            return self.away
        if side_or_abbr == "home":
            return self.home
        return side_or_abbr

    def pitcher(self, side: str) -> str:
        return self.game.get(f"{side}_probable") or f"the {self.club(side)} starter"

    @staticmethod
    def other(side: str) -> str:
        return "home" if side == "away" else "away"

    def sec(self, name: str):
        value = self.sections.get(name)
        return value if value else None

    # -- evidence ---------------------------------------------------------

    def ev(self, path: str, label: str) -> Optional[dict]:
        """An evidence entry whose value is read from the payload, never
        typed, so the path and the value cannot disagree."""
        found, value = resolve_path(self.payload, path)
        if not found or value is None or isinstance(value, (dict, list)):
            return None
        return {"path": path, "label": label, "value": value}

    def derived(self, path: str, label: str, value) -> Optional[dict]:
        """An evidence entry for a number this module computed from the
        section at `path`. The path must resolve; the value is flagged."""
        found, _ = resolve_path(self.payload, path)
        if not found or value is None:
            return None
        return {"path": path, "label": label, "value": value, "derived": True}

    def miss(self, name: str, status: str, detail: str) -> None:
        key = (name, status)
        if key in self._missing_keys:
            return
        self._missing_keys.add(key)
        self.missing.append({"input": name, "status": status, "detail": detail})

    # -- shared phrases ---------------------------------------------------

    def results_phrase(self) -> str:
        if self.results_through is None:
            return "our results store has no stated end date"
        days = self.results_days
        gap = "" if days is None else f", {_plural(days, 'day')} before this game"
        return f"our results end {self.results_through}{gap}"

    def pitcher_phrase(self) -> str:
        if self.pitcher_through is None:
            return "our pitcher logs have no stated end date"
        days = self.pitcher_days
        gap = "" if days is None else f", {_plural(days, 'day')} before this game"
        return f"our pitcher logs end {self.pitcher_through}{gap}"


def _factor(ctx: _Ctx, key: str, title: str, favours: str, size: str,
            short: str, sentence: str, evidence: list, confidence: str,
            caveat: str, down_weighted: bool = False) -> dict:
    return {
        "factor": key,
        "title": title,
        "favours": favours,
        "size": size,
        "short": short,
        "sentence": sentence,
        "evidence": [e for e in evidence if e],
        "confidence": confidence,
        "caveat": caveat,
        "down_weighted": bool(down_weighted),
    }


# ---------------------------------------------------------------------------
# Starting pitching
# ---------------------------------------------------------------------------

_SP_FIELDS = ("era", "fip", "whip", "k9", "bb9", "hr9", "k_bb_pct", "innings",
              "ip_per_start", "recent_starts", "recent_era",
              "recent_ip_per_start", "days_rest", "thin", "starts")


def _sp(ctx: _Ctx, side: str) -> Optional[dict]:
    starters = ctx.sec("starters")
    if not starters or not starters.get(f"{side}_sp_known"):
        return None
    out = {name: starters.get(f"{side}_sp_{name}") for name in _SP_FIELDS}
    if _num(out["fip"]) is None or _num(out["innings"]) is None:
        return None
    out["name"] = ctx.pitcher(side)
    return out


def _arsenal_rows(ctx: _Ctx, side: str) -> list:
    section = ctx.sec("arsenals") or {}
    rows = section.get(side)
    return rows if isinstance(rows, list) else []


def _log_gap_reason(ctx: _Ctx, side: str) -> str:
    """Why a starter has no line, with the pitch-file cross-check."""
    name = ctx.game.get(f"{side}_probable")
    if not name:
        return f"no probable starter is listed for {ctx.club(side)}"
    rows = _arsenal_rows(ctx, side)
    pitches = sum(_num(r.get("pitches")) or 0 for r in rows)
    pa = sum(_num(r.get("pa")) or 0 for r in rows)
    if pitches >= 100:
        return (f"{name} has no game log in our records, yet our pitch file "
                f"shows {pitches:.0f} pitches and {pa:.0f} plate appearances "
                "from him this season, so the gap is in our log, not a "
                "sign he is new")
    return (f"{name} has no game log in our records and no pitch data "
            "either, so nothing can be said about him from this page")


def _pitching_confidence(ctx: _Ctx, starters: list) -> tuple:
    """(confidence, reasons) for a comparison resting on these starters."""
    innings = min(_num(s["innings"]) or 0 for s in starters)
    if innings < INNINGS_LOW:
        conf = "low"
    elif innings < INNINGS_MEDIUM:
        conf = "medium"
    else:
        conf = "high"
    reasons = []
    if any(s.get("thin") for s in starters):
        conf = "low"
        reasons.append("at least one starter has a thin sample")
    if ctx.pitcher_stale:
        conf = _cap(conf, "medium")
        reasons.append(ctx.pitcher_phrase() + ", so recent starts are missing")
    return conf, reasons


def _sp_line(s: dict) -> str:
    return (f"{s['name']} ({_fmt(s['fip'])} FIP, {_fmt(s['whip'])} WHIP, "
            f"{_pct(s['k_bb_pct'])} strikeouts minus walks, "
            f"{_fmt(s['innings'], 0)} innings)")


def _f_starting_pitching(ctx: _Ctx) -> Optional[dict]:
    away, home = _sp(ctx, "away"), _sp(ctx, "home")
    if not ctx.sec("starters"):
        ctx.miss("Starting pitchers", "absent",
                 ctx.gaps.get("starters") or "no starter data on this page")
        return None
    for side, line in (("away", away), ("home", home)):
        if line is None:
            ctx.miss(f"{ctx.pitcher(side)} (starter line)", "absent",
                     _log_gap_reason(ctx, side))
    if away is None and home is None:
        return None

    st = "advanced.sections.starters."
    if away is None or home is None:
        known, side = (home, "home") if home else (away, "away")
        gone = ctx.other(side)
        conf, why = _pitching_confidence(ctx, [known])
        conf = _cap(conf, "low")
        sentence = (f"Only {_sp_line(known)} has a line on file. "
                    f"{ctx.pitcher(gone)} has none, so the two starters cannot "
                    "be compared and this factor carries no direction.")
        evidence = [ctx.ev(f"{st}{side}_sp_fip", f"{known['name']} FIP"),
                    ctx.ev(f"{st}{side}_sp_innings", f"{known['name']} innings")]
        return _factor(ctx, "starting_pitching", "Starting pitching", "even",
                       "slight",
                       f"Only {known['name']} has a pitching line on file, so "
                       "the starters cannot be compared.",
                       sentence, evidence, conf,
                       "One starter has no line, so there is nothing to weigh "
                       "him against. " + _log_gap_reason(ctx, gone) + ".",
                       down_weighted=True)

    gap = _num(away["fip"]) - _num(home["fip"])      # positive: home better
    size = _size(gap, FIP_SLIGHT, FIP_MODERATE, FIP_LARGE)
    better = "home" if gap > 0 else "away"
    worse = ctx.other(better)

    # Do WHIP and strikeouts minus walks point the same way as FIP?
    agree = 0
    checks = []
    for key, lower_is_better in (("whip", True), ("k_bb_pct", False)):
        a, h = _num(away[key]), _num(home[key])
        if a is None or h is None or a == h:
            continue
        home_better = (h < a) if lower_is_better else (h > a)
        checks.append(home_better == (better == "home"))
    agree = sum(1 for c in checks if c)
    if size and checks and agree == 0:
        size = _shift(size, -1)
        agreement = ("WHIP and strikeouts minus walks point the other way, "
                     "so the gap is discounted a step.")
    elif checks and agree == len(checks):
        agreement = "WHIP and strikeouts minus walks point the same way."
    elif checks:
        agreement = "WHIP and strikeouts minus walks split on direction."
    else:
        agreement = ""

    conf, reasons = _pitching_confidence(ctx, [away, home])
    evidence = []
    for side, s in (("away", away), ("home", home)):
        for field, label in (("fip", "FIP"), ("whip", "WHIP"),
                             ("k_bb_pct", "strikeouts minus walks"),
                             ("innings", "innings")):
            evidence.append(ctx.ev(f"{st}{side}_sp_{field}",
                                   f"{s['name']} {label}"))
    caveat = ("Season lines only; park and opponent are not adjusted. "
              + (_cap1("; ".join(reasons)) + "." if reasons else ""))
    down = bool(reasons)
    if size is None:
        sentence = (f"{_sp_line(away)} against {_sp_line(home)}: the starters "
                    f"are within {FIP_SLIGHT:.2f} runs per nine of each other "
                    "on FIP, so pitching does not separate the clubs. "
                    + agreement).strip()
        return _factor(ctx, "starting_pitching", "Starting pitching", "even",
                       "slight", "The two starters are close on FIP, so pitching "
                       "does not separate the clubs.", sentence,
                       evidence, conf, caveat.strip(), down)
    sentence = (f"{_sp_line(away)} against {_sp_line(home)}. "
                f"{ctx.pitcher(better)} is better by {abs(gap):.2f} runs per "
                f"nine on FIP, which favours the {ctx.club(better)}. "
                + agreement).strip()
    short = (f"{ctx.pitcher(better)} ({_fmt(_sp(ctx, better)['fip'])} FIP) is "
             f"the better starter than {ctx.pitcher(worse)} "
             f"({_fmt(_sp(ctx, worse)['fip'])} FIP), which favours the "
             f"{ctx.club(better)}.")
    return _factor(ctx, "starting_pitching", "Starting pitching",
                   ctx.abbr(better), size, short, sentence, evidence, conf,
                   caveat.strip(), down)


def _f_pitcher_regression(ctx: _Ctx) -> Optional[dict]:
    st = "advanced.sections.starters."
    items = {}
    for side in ("away", "home"):
        s = _sp(ctx, side)
        if not s or _num(s["era"]) is None:
            continue
        if _num(s["innings"]) < REGRESSION_MIN_INNINGS:
            continue
        gap = _num(s["fip"]) - _num(s["era"])         # positive: ERA flatters
        if abs(gap) >= REGRESSION_GAP:
            items[side] = (s, gap)
    if not items:
        return None
    parts, evidence = [], []
    net = 0.0                                          # positive: favours away
    for side in ("away", "home"):
        if side not in items:
            continue
        s, gap = items[side]
        if gap > 0:
            parts.append(f"{s['name']}'s ERA of {_fmt(s['era'])} sits {gap:.2f} "
                         f"below his FIP of {_fmt(s['fip'])} over "
                         f"{_fmt(s['innings'], 0)} innings, so his results have "
                         "run ahead of the strikeouts, walks and homers behind "
                         "them")
        else:
            parts.append(f"{s['name']}'s ERA of {_fmt(s['era'])} sits "
                         f"{abs(gap):.2f} above his FIP of {_fmt(s['fip'])} over "
                         f"{_fmt(s['innings'], 0)} innings, so his results have "
                         "lagged the strikeouts, walks and homers behind them")
        net += (gap if side == "home" else -gap)
        evidence += [ctx.ev(f"{st}{side}_sp_era", f"{s['name']} ERA"),
                     ctx.ev(f"{st}{side}_sp_fip", f"{s['name']} FIP"),
                     ctx.ev(f"{st}{side}_sp_innings", f"{s['name']} innings")]
    size = _size(net, REGRESSION_GAP, 1.0, 99)
    favours = "even"
    if size:
        favours = ctx.abbr("away" if net > 0 else "home")
    else:
        size = "slight"
    sentence = ("; ".join(parts) + ". That gap is a sign part of the ERA is "
                "sequencing luck, and results of that kind tend to drift back "
                "toward the FIP.")
    conf = "medium" if min(_num(i[0]["innings"]) for i in items.values()) >= 100 else "low"
    if ctx.pitcher_stale:
        conf = _cap(conf, "medium")
    caveat = ("A pointer toward which results are more likely to cool, not a "
              "forecast of any one game.")
    if ctx.pitcher_stale:
        caveat += " " + _cap1(ctx.pitcher_phrase()) + "."
    lead = []
    for side in ("away", "home"):
        if side not in items:
            continue
        one, one_gap = items[side]
        lead.append(f"{one['name']}'s ERA ({_fmt(one['era'])}) is "
                    f"{abs(one_gap):.2f} {'below' if one_gap > 0 else 'above'} "
                    f"his FIP ({_fmt(one['fip'])})")
    signs = {gap > 0 for _, gap in items.values()}
    outlook = ("a sign results may cool" if signs == {True}
               else "a sign results may improve" if signs == {False}
               else "pointing in opposite directions")
    short = (_join(lead) + f", {outlook}"
             + (f", which leans toward the {ctx.club(favours)}"
                if favours != "even" else "") + ".")
    return _factor(ctx, "pitcher_regression", "ERA against FIP", favours, size,
                   short, sentence, evidence, conf, caveat)


def _f_pitcher_form(ctx: _Ctx) -> Optional[dict]:
    st = "advanced.sections.starters."
    flagged, deltas = {}, {}
    for side in ("away", "home"):
        s = _sp(ctx, side)
        if not s:
            continue
        starts = _num(s["recent_starts"])
        recent, season = _num(s["recent_era"]), _num(s["era"])
        if not starts or starts < 3 or recent is None or season is None:
            continue
        delta = recent - season                    # positive: recently worse
        deltas[side] = delta
        recent_ip, season_ip = _num(s["recent_ip_per_start"]), _num(s["ip_per_start"])
        short_outings = (recent_ip is not None and season_ip is not None
                         and season_ip - recent_ip >= FORM_IP_DROP)
        if abs(delta) >= FORM_DELTA or short_outings:
            flagged[side] = (s, delta, short_outings)
    if not flagged:
        return None
    parts, evidence = [], []
    # Direction comes from BOTH starters' recent-minus-season gaps, not just the
    # flagged ones; positive favours the away club.
    net = deltas.get("home", 0.0) - deltas.get("away", 0.0)
    for side in ("away", "home"):
        if side not in flagged:
            continue
        s, delta, short_outings = flagged[side]
        starts = int(_num(s["recent_starts"]))
        ip = _num(s["recent_ip_per_start"])
        total_ip = starts * ip if ip is not None else None
        sample = (f"{starts} starts, about {total_ip:.0f} innings"
                  if total_ip is not None else f"{starts} starts")
        direction = "worse" if delta > 0 else "better"
        text = (f"{s['name']} has a {_fmt(s['recent_era'])} ERA over his last "
                f"three on file ({sample}) against {_fmt(s['era'])} on the "
                f"season, {direction} by {abs(delta):.2f}")
        if short_outings:
            text += (f", with shorter outings ({_fmt(s['recent_ip_per_start'], 1)} "
                     f"innings a start against {_fmt(s['ip_per_start'], 1)}), "
                     "which hands more innings to the bullpen")
        parts.append(text)
        evidence += [ctx.ev(f"{st}{side}_sp_recent_era", f"{s['name']} last three ERA"),
                     ctx.ev(f"{st}{side}_sp_era", f"{s['name']} season ERA"),
                     ctx.ev(f"{st}{side}_sp_recent_starts", f"{s['name']} recent starts"),
                     ctx.ev(f"{st}{side}_sp_recent_ip_per_start",
                            f"{s['name']} innings per start, last three"),
                     ctx.ev(f"{st}{side}_sp_ip_per_start",
                            f"{s['name']} innings per start, season")]
    favours = "even"
    if abs(net) >= FORM_DELTA:
        favours = ctx.abbr("away" if net > 0 else "home")
    sentence = ". ".join(parts) + ". Three starts is a small sample."
    caveat = "Three starts is roughly eighteen innings, which is noise-level."
    down = True
    if ctx.pitcher_stale:
        caveat += (" These are the three newest on file and "
                   + ctx.pitcher_phrase() + ", so they are not the latest "
                   "three he has thrown.")
    names = _join([flagged[side][0]["name"] for side in ("away", "home")
                   if side in flagged])
    short = (f"{names} {'has' if len(flagged) == 1 else 'have'} pitched "
             "differently over the last three starts than over the season"
             + (f", which leans toward the {ctx.club(favours)}"
                if favours != "even" else ", over a small sample") + ".")
    return _factor(ctx, "pitcher_form", "Last three starts", favours, "slight",
                   short, sentence, evidence, "low", caveat, down)


def _f_hr_park(ctx: _Ctx) -> Optional[dict]:
    st = "advanced.sections.starters."
    away, home = _sp(ctx, "away"), _sp(ctx, "home")
    if not away or not home:
        return None
    a, h = _num(away["hr9"]), _num(home["hr9"])
    if a is None or h is None:
        return None
    gap = a - h                                    # positive: home starter better
    size = _size(gap, HR9_SLIGHT, HR9_MODERATE, 99)
    if size is None:
        return None
    better = "home" if gap > 0 else "away"
    worse = ctx.other(better)
    park = ctx.sec("park") or {}
    pf = (ctx.inputs.get("park_factor") or {})
    factor = _num(pf.get("factor"))
    altitude = _num(park.get("altitude_m"))
    notes, evidence = [], []
    shift = 0
    if factor is not None and not pf.get("thin"):
        if factor >= PARK_HIGH:
            shift += 1
            notes.append(f"the park factor of {factor:.3f} says runs come easier here")
        elif factor <= PARK_LOW:
            shift -= 1
            notes.append(f"the park factor of {factor:.3f} says runs come harder here")
        else:
            notes.append(f"the park factor of {factor:.3f} is close to neutral")
        evidence.append(ctx.ev("read_inputs.park_factor.factor", "park run factor"))
        evidence.append(ctx.ev("read_inputs.park_factor.home_games",
                               "home games behind the park factor"))
    elif factor is not None:
        notes.append(f"the park factor of {factor:.3f} rests on thin games and is "
                     "not used to move the size")
        evidence.append(ctx.ev("read_inputs.park_factor.factor", "park run factor"))
    else:
        notes.append("no park factor is available")
    if altitude is not None and altitude >= ALTITUDE_HIGH_M:
        shift += 1
        notes.append(f"the park sits {altitude:.0f} metres above sea level, where "
                     "the ball carries")
        evidence.append(ctx.ev("advanced.sections.park.altitude_m", "park altitude (metres)"))
    size = _shift(size, shift) or "slight"
    innings = min(_num(away["innings"]), _num(home["innings"]))
    conf = "low" if innings < 100 else "medium"
    if ctx.pitcher_stale:
        conf = _cap(conf, "medium")
    sentence = (f"{away['name']} has allowed {_fmt(away['hr9'])} home runs per "
                f"nine and {home['name']} {_fmt(home['hr9'])} "
                f"({_fmt(away['innings'], 0)} and {_fmt(home['innings'], 0)} "
                f"innings), a gap that favours the {ctx.club(better)}; "
                f"{_join(notes)}.")
    for side, s in (("away", away), ("home", home)):
        evidence += [ctx.ev(f"{st}{side}_sp_hr9", f"{s['name']} home runs per nine"),
                     ctx.ev(f"{st}{side}_sp_innings", f"{s['name']} innings")]
    caveat = ("Home run rates settle slowly; with a few hundred batters behind "
              "each, a gap this size can move a lot.")
    return _factor(ctx, "hr_park", "Home runs against the park", ctx.abbr(better),
                   size, f"{ctx.pitcher(worse)} gives up more home runs than "
                   f"{ctx.pitcher(better)}, which favours the {ctx.club(better)}.",
                   sentence, evidence, conf, caveat, down_weighted=conf == "low")


# ---------------------------------------------------------------------------
# Arsenals: results by pitch, and pitch mix against the lineup
# ---------------------------------------------------------------------------

def _arsenal_summary(rows: list) -> Optional[dict]:
    pa = woba_sum = pitches = whiff_sum = whiff_w = 0.0
    for r in rows:
        r_pa, r_woba = _num(r.get("pa")), _num(r.get("woba"))
        if r_pa and r_woba is not None:
            pa += r_pa
            woba_sum += r_pa * r_woba
        r_p, r_w = _num(r.get("pitches")), _num(r.get("whiff_percent"))
        if r_p:
            pitches += r_p
        if r_p and r_w is not None:
            whiff_sum += r_p * r_w
            whiff_w += r_p
    if not pa:
        return None
    primary = max(rows, key=lambda r: _num(r.get("pitch_usage")) or 0)
    return {"pa": pa, "woba": woba_sum / pa, "pitches": pitches,
            "whiff": (whiff_sum / whiff_w) if whiff_w else None,
            "primary": primary}


def _f_arsenal_results(ctx: _Ctx) -> Optional[dict]:
    if not ctx.sec("arsenals"):
        ctx.miss("Pitch arsenals", "absent",
                 ctx.gaps.get("arsenals") or "no pitch arsenal data for either starter")
        return None
    summary = {}
    for side in ("away", "home"):
        s = _arsenal_summary(_arsenal_rows(ctx, side))
        if s is None:
            ctx.miss(f"{ctx.pitcher(side)} (pitch arsenal)", "absent",
                     f"our pitch file has no rows for {ctx.pitcher(side)}")
        elif s["pa"] < ARSENAL_PA_FLOOR:
            ctx.miss(f"{ctx.pitcher(side)} (pitch arsenal)", "thin",
                     f"only {s['pa']:.0f} plate appearances behind "
                     f"{ctx.pitcher(side)}'s pitch results, under the "
                     f"{ARSENAL_PA_FLOOR} we need to compare")
        else:
            summary[side] = s
    if len(summary) < 2:
        return None
    a, h = summary["away"], summary["home"]
    gap = a["woba"] - h["woba"]                    # positive: home starter better
    size = _size(gap, ARSENAL_SLIGHT, ARSENAL_MODERATE, ARSENAL_LARGE)
    min_pa = min(a["pa"], h["pa"])
    conf = "medium" if min_pa >= ARSENAL_PA_MEDIUM else "low"
    conf = _cap(conf, "medium")

    def line(side, s):
        prim = s["primary"]
        whiff = f", {s['whiff']:.1f}% whiffs" if s["whiff"] is not None else ""
        return (f"{ctx.pitcher(side)} has held hitters to a {s['woba']:.3f} wOBA "
                f"over {s['pa']:.0f} plate appearances{whiff}, leaning on the "
                f"{str(prim.get('pitch_name')).lower()} "
                f"({_fmt(prim.get('pitch_usage'), 1)}% of his pitches)")

    evidence = []
    for side in ("away", "home"):
        for i, row in enumerate(_arsenal_rows(ctx, side)):
            base = f"advanced.sections.arsenals.{side}.{i}"
            tag = f"{ctx.pitcher(side)} {row.get('pitch_name')}"
            evidence += [ctx.ev(f"{base}.woba", f"{tag} wOBA allowed"),
                         ctx.ev(f"{base}.pa", f"{tag} plate appearances")]
    caveat = ("Plate appearances that ended on each pitch type, season to "
              "date, as of a pitch-file date this page does not state. Not "
              "adjusted for opponent or park.")
    if size is None:
        return _factor(ctx, "arsenal_results", "Results by pitch", "even",
                       "slight", "The two starters' pitches have been about "
                       "equally hard to hit.",
                       f"{line('away', a)}. {line('home', h)}. The two are "
                       f"within {ARSENAL_SLIGHT:.3f} wOBA of each other.",
                       evidence, conf, caveat, conf == "low")
    better = "home" if gap > 0 else "away"
    sentence = (f"{line('away', a)}. {line('home', h)}. By results on each "
                f"pitch, {ctx.pitcher(better)} has been harder to hit by "
                f"{abs(gap):.3f} wOBA, which favours the {ctx.club(better)}.")
    return _factor(ctx, "arsenal_results", "Results by pitch", ctx.abbr(better),
                   size, f"{ctx.pitcher(better)} has been harder to hit on "
                   f"the pitches he throws, which favours the {ctx.club(better)}.",
                   sentence, evidence, conf, caveat,
                   conf == "low")


def _vs_pitch(ctx: _Ctx, side: str) -> dict:
    lineup = (ctx.sec("lineups") or {}).get(side) or {}
    grouped = lineup.get("vs_pitch")
    return grouped if isinstance(grouped, dict) else {}


def _batter_totals(ctx: _Ctx, side: str) -> dict:
    """person_id (str) -> {woba, pa} pooled over pitch types, from the lineup's
    per-pitch lines."""
    totals: dict = {}
    for rows in _vs_pitch(ctx, side).values():
        for r in rows:
            pa, woba = _num(r.get("pa")), _num(r.get("woba"))
            if not pa or woba is None:
                continue
            t = totals.setdefault(str(r.get("player_id")), [0.0, 0.0])
            t[0] += woba * pa
            t[1] += pa
    return {pid: {"woba": v[0] / v[1], "pa": v[1]} for pid, v in totals.items() if v[1]}


def _pool(totals: dict, ids: list) -> Optional[dict]:
    value = pa = 0.0
    n = 0
    for pid in ids:
        t = totals.get(str(pid))
        if t:
            value += t["woba"] * t["pa"]
            pa += t["pa"]
            n += 1
    return {"woba": value / pa, "pa": pa, "hitters": n} if pa else None


def _f_pitch_mix(ctx: _Ctx) -> Optional[dict]:
    if not ctx.sec("lineups") or not ctx.sec("arsenals"):
        return None
    results = {}
    for side in ("away", "home"):
        opp = ctx.other(side)                      # the starter this lineup faces
        arsenal = _arsenal_rows(ctx, opp)
        grouped = _vs_pitch(ctx, side)
        if not arsenal or not grouped:
            continue
        # Lineup's pooled wOBA over every pitch type it has a line against.
        all_value = all_pa = 0.0
        per_type = {}
        for ptype, rows in grouped.items():
            v = p = 0.0
            for r in rows:
                pa, woba = _num(r.get("pa")), _num(r.get("woba"))
                if pa and woba is not None:
                    v += woba * pa
                    p += pa
            if p:
                per_type[ptype] = (v / p, p)
                all_value += v
                all_pa += p
        if not all_pa:
            continue
        baseline = all_value / all_pa
        usage_total = used_usage = mix_value = mix_pa = 0.0
        for row in arsenal:
            usage = _num(row.get("pitch_usage")) or 0.0
            usage_total += usage
            hit = per_type.get(row.get("pitch_type"))
            if hit:
                used_usage += usage
                mix_value += usage * hit[0]
                mix_pa += hit[1]
        if not used_usage:
            continue
        mix = mix_value / used_usage
        primary = max(arsenal, key=lambda r: _num(r.get("pitch_usage")) or 0)
        results[side] = {"mix": mix, "baseline": baseline, "delta": mix - baseline,
                         "pa": mix_pa, "coverage": used_usage / usage_total
                         if usage_total else 0.0, "primary": primary}
    if not results:
        return None
    parts, evidence, deltas = [], [], {}
    for side in ("away", "home"):
        r = results.get(side)
        if r is None:
            continue
        opp = ctx.other(side)
        prim = r["primary"]
        direction = "better" if r["delta"] >= 0 else "worse"
        parts.append(
            f"The {ctx.club(side)} lineup has run {r['mix']:.3f} wOBA against "
            f"the pitch types {ctx.pitcher(opp)} throws, weighted by how often "
            f"he throws them, {abs(r['delta']):.3f} {direction} than its "
            f"{r['baseline']:.3f} across every pitch type it has a line against "
            f"({r['pa']:.0f} plate appearances; his main pitch is the "
            f"{str(prim.get('pitch_name')).lower()} at "
            f"{_fmt(prim.get('pitch_usage'), 1)}%)")
        deltas[side] = r
        evidence.append(ctx.derived(f"advanced.sections.lineups.{side}.vs_pitch",
                                    f"{ctx.club(side)} lineup wOBA against {ctx.pitcher(opp)}'s mix",
                                    round(r["mix"], 4)))
        evidence.append(ctx.ev(f"advanced.sections.arsenals.{opp}.0.pitch_usage",
                               f"{ctx.pitcher(opp)} top pitch usage"))
    favours, size = "even", None
    if len(deltas) == 2:
        gap = deltas["away"]["delta"] - deltas["home"]["delta"]
        size = _size(gap, MIX_SLIGHT, MIX_MODERATE, MIX_LARGE)
        if size:
            favours = ctx.abbr("away" if gap > 0 else "home")
    else:
        (side, r), = deltas.items()
        size = _size(r["delta"], MIX_SLIGHT, MIX_MODERATE, MIX_LARGE)
        if size:
            favours = ctx.abbr(side if r["delta"] > 0 else ctx.other(side))
        other = ctx.other(side)          # the lineup we could not read
        ctx.miss(f"{ctx.club(other)} lineup against {ctx.pitcher(side)} (pitch mix)",
                 "absent",
                 f"{ctx.pitcher(side)}'s pitch mix or the {ctx.club(other)} "
                 "lineup's per-pitch lines are not on file")
    weak = min(r["pa"] for r in deltas.values())
    conf = "low" if weak < MIX_PA_LOW or any(r["coverage"] < 0.7 for r in deltas.values()) else "medium"
    sentence = ". ".join(parts) + "."
    if size is None:
        size = "slight"
        sentence += (" Neither lineup is far from its usual line against these pitches."
                     if len(deltas) == 2 else
                     " That lineup is close to its usual line against these pitches, "
                     "and the other lineup cannot be read.")
    caveat = ("Plate appearances that ended on each pitch type, pooled across "
              "the hitters named. Individual hitters carry small samples, and "
              "the pitch file's date is not stated.")
    return _factor(ctx, "pitch_mix", "Pitch mix against the lineup", favours, size,
                   (f"The {ctx.club(favours)} lineup has handled the pitch mix it "
                    "faces better." if favours != "even" else
                    "Neither lineup stands out against the pitch mix it faces."),
                   sentence, evidence, conf, caveat, conf == "low")


# ---------------------------------------------------------------------------
# Lineups: platoon and depth
# ---------------------------------------------------------------------------

def _f_platoon(ctx: _Ctx) -> Optional[dict]:
    lineups = ctx.sec("lineups")
    if not lineups:
        ctx.miss("Lineups", "absent", ctx.gaps.get("lineups")
                 or "no lineup is posted for either club yet")
        return None
    shares, parts, evidence = {}, [], []
    for side in ("away", "home"):
        lineup = lineups.get(side)
        if not lineup:
            ctx.miss(f"{ctx.club(side)} lineup", "absent",
                     f"the {ctx.club(side)} lineup is not posted yet")
            continue
        adv = lineup.get("platoon_advantage") or {}
        share, known = _num(adv.get("share")), adv.get("known")
        throws = lineup.get("faces_starter_throwing")
        opp = ctx.other(side)
        if share is None:
            ctx.miss(f"{ctx.club(side)} platoon share", "absent",
                     adv.get("reason") or "bat sides are unknown")
            continue
        hand = "left-handed" if throws == "L" else "right-handed"
        parts.append(f"{adv.get('advantaged')} of {known} {ctx.club(side)} "
                     f"hitters have the platoon advantage against "
                     f"{ctx.pitcher(opp)}, who throws {hand}")
        shares[side] = (share, known)
        base = f"advanced.sections.lineups.{side}.platoon_advantage"
        evidence += [ctx.ev(f"{base}.advantaged", f"{ctx.club(side)} hitters with the advantage"),
                     ctx.ev(f"{base}.known", f"{ctx.club(side)} hitters with a known bat side"),
                     ctx.ev(f"advanced.sections.lineups.{side}.faces_starter_throwing",
                            f"{ctx.pitcher(opp)} throws")]
    if not shares:
        return None
    # The starter's own split, when we have it.
    splits = ctx.sec("splits") or {}
    split_note = []
    for side in ("away", "home"):
        platoon = ((splits.get(side) or {}).get("platoon")) or {}
        if platoon.get("usable"):
            weaker = "left-handed" if platoon.get("weaker_against") == "L" else "right-handed"
            split_note.append(
                f"{ctx.pitcher(side)} has allowed a {_fmt(platoon.get('vs_left_ops'), 3)} "
                f"OPS to left-handed hitters ({platoon.get('vs_left_faced')} batters "
                f"faced) and {_fmt(platoon.get('vs_right_ops'), 3)} to right-handed "
                f"({platoon.get('vs_right_faced')}), weaker against {weaker} bats")
            evidence += [ctx.ev(f"advanced.sections.splits.{side}.platoon.vs_left_ops",
                                f"{ctx.pitcher(side)} OPS allowed to lefties"),
                         ctx.ev(f"advanced.sections.splits.{side}.platoon.vs_right_ops",
                                f"{ctx.pitcher(side)} OPS allowed to righties")]
    favours, size = "even", None
    if len(shares) == 2:
        gap = shares["away"][0] - shares["home"][0]
        size = _size(gap, PLATOON_SLIGHT, PLATOON_MODERATE, PLATOON_LARGE)
        if size:
            favours = ctx.abbr("away" if gap > 0 else "home")
    known_min = min(k for _, k in shares.values())
    conf = "medium" if known_min >= 8 and len(shares) == 2 else "low"
    sentence = "; ".join(parts) + "."
    if split_note:
        sentence += " " + "; ".join(split_note) + "."
    if size is None:
        size = "slight"
        sentence += (" The two lineups present a similar platoon picture."
                     if len(shares) == 2 else
                     " Only one lineup is posted, so there is no comparison.")
    caveat = ("A count of bat sides against the starter's throwing hand. A "
              "switch hitter always counts as having the advantage. A lineup "
              "can still change before first pitch.")
    return _factor(ctx, "platoon", "Lineup handedness", favours, size,
                   (f"The {ctx.club(favours)} lineup holds more platoon "
                    "advantages against the opposing starter."
                    if favours != "even" else
                    "The lineups' platoon picture is similar, or only one is posted."),
                   sentence, evidence, conf, caveat, conf == "low")


def _depth_from_section(ctx: _Ctx, side: str) -> Optional[dict]:
    """The matchup depth section's own top-four/bottom-five picture, when the
    pitch store built it."""
    depth = ctx.sec("matchup_depth")
    conc = ((depth or {}).get(side) or {}).get("concentration")
    if not conc or not conc.get("top") or not conc.get("bottom"):
        return None
    return {"top": conc["top"], "bottom": conc["bottom"],
            "source": f"advanced.sections.matchup_depth.{side}.concentration"}


def _f_lineup_depth(ctx: _Ctx) -> Optional[dict]:
    lineups = ctx.sec("lineups")
    if not lineups:
        return None
    pics = {}
    for side in ("away", "home"):
        lineup = lineups.get(side)
        if not lineup:
            continue
        pic = _depth_from_section(ctx, side)
        if pic is None:
            totals = _batter_totals(ctx, side)
            order = {str(b.get("person_id")): b.get("order")
                     for b in lineup.get("batters") or []}
            top_ids = [pid for pid, o in order.items() if o is not None and 1 <= o <= 4]
            bot_ids = [pid for pid, o in order.items() if o is not None and o >= 5]
            top, bot = _pool(totals, top_ids), _pool(totals, bot_ids)
            if top and bot:
                pic = {"top": top, "bottom": bot,
                       "source": f"advanced.sections.lineups.{side}.vs_pitch"}
        if pic is None:
            ctx.miss(f"{ctx.club(side)} lineup depth", "absent",
                     f"no per-hitter results are on file for the {ctx.club(side)} "
                     "lineup, so top four against bottom five cannot be read")
            continue
        top, bot = pic["top"], pic["bottom"]
        total_pa = top["pa"] + bot["pa"]
        pic["overall"] = (top["woba"] * top["pa"] + bot["woba"] * bot["pa"]) / total_pa
        pic["thin"] = top["pa"] < HALF_PA_FLOOR or bot["pa"] < HALF_PA_FLOOR
        pics[side] = pic
    if not pics:
        return None
    parts, evidence = [], []
    for side in ("away", "home"):
        p = pics.get(side)
        if not p:
            continue
        shape = ("top-heavy" if p["top"]["woba"] - p["bottom"]["woba"] >= 0.04
                 else "fairly even from top to bottom")
        parts.append(f"The {ctx.club(side)} lineup has run {p['top']['woba']:.3f} "
                     f"wOBA from slots one to four ({p['top']['pa']:.0f} plate "
                     f"appearances) and {p['bottom']['woba']:.3f} from slots five "
                     f"to nine ({p['bottom']['pa']:.0f}), {shape}")
        evidence.append(ctx.derived(p["source"],
                                    f"{ctx.club(side)} slots 1 to 4 wOBA",
                                    round(p["top"]["woba"], 4)))
        evidence.append(ctx.derived(p["source"],
                                    f"{ctx.club(side)} slots 5 to 9 wOBA",
                                    round(p["bottom"]["woba"], 4)))
    favours, size = "even", None
    if len(pics) == 2:
        gap = pics["away"]["overall"] - pics["home"]["overall"]
        size = _size(gap, DEPTH_SLIGHT, DEPTH_MODERATE, DEPTH_LARGE)
        if size:
            favours = ctx.abbr("away" if gap > 0 else "home")
    thin = any(p["thin"] for p in pics.values())
    conf = "low" if thin or len(pics) < 2 else "medium"
    sentence = ". ".join(parts) + "."
    if size is None:
        size = "slight"
        sentence += (" Taken as a whole the two lineups are close."
                     if len(pics) == 2 else
                     " Only one lineup can be read, so there is no comparison.")
    else:
        sentence += (f" Pooled across all nine, that favours the {ctx.club(favours)}.")
    caveat = ("Built from each hitter's results on plate appearances that ended "
              "on a pitch of each type, pooled by plate appearances. Hitters with "
              "no measured line are left out, so a lineup can look better or "
              "worse than it is.")
    return _factor(ctx, "lineup_depth", "Lineup depth", favours, size,
                   (f"The {ctx.club(favours)} lineup is deeper, top four and "
                    "bottom five pooled."
                    if favours != "even" else
                    "The lineups are close on depth, or only one can be read."),
                   sentence, evidence, conf, caveat, conf == "low")


def _f_batter_vs_pitcher(ctx: _Ctx) -> Optional[dict]:
    history = ctx.sec("matchup_history")
    if not history:
        ctx.miss("Batter against pitcher history", "absent",
                 ctx.gaps.get("matchup_history")
                 or "no head-to-head history is on file")
        return None
    sides = {}
    for side in ("away", "home"):
        row = history.get(side)
        opp = ctx.other(side)
        if not row or not row.get("usable") or not row.get("total_at_bats"):
            ctx.miss(f"{ctx.club(side)} hitters against {ctx.pitcher(opp)}", "absent",
                     (row or {}).get("reason")
                     or f"no head-to-head history for the {ctx.club(side)} lineup "
                        f"against {ctx.pitcher(opp)} is on file")
            continue
        sides[side] = row
    if not sides:
        return None
    parts, evidence = [], []
    for side in ("away", "home"):
        row = sides.get(side)
        if not row:
            continue
        opp = ctx.other(side)
        batters = row.get("batters") or []
        biggest = max((b.get("at_bats") or 0 for b in batters), default=0)
        parts.append(
            f"{ctx.club(side)} hitters are {row.get('total_hits')} for "
            f"{row.get('total_at_bats')} ({_fmt(row.get('aggregate_avg'), 3)}) with "
            f"{row.get('total_home_runs')} home runs against {ctx.pitcher(opp)}, "
            f"spread over {len(batters)} hitters, the most at-bats for any one "
            f"being {biggest}")
        base = f"advanced.sections.matchup_history.{side}"
        evidence += [ctx.ev(f"{base}.total_at_bats", f"{ctx.club(side)} at-bats against {ctx.pitcher(opp)}"),
                     ctx.ev(f"{base}.total_hits", f"{ctx.club(side)} hits against {ctx.pitcher(opp)}"),
                     ctx.ev(f"{base}.aggregate_avg", f"{ctx.club(side)} average against {ctx.pitcher(opp)}")]
    favours, size = "even", "slight"
    if len(sides) == 2:
        a, h = sides["away"], sides["home"]
        gap = (_num(a.get("aggregate_avg")) or 0) - (_num(h.get("aggregate_avg")) or 0)
        if (min(a["total_at_bats"], h["total_at_bats"]) >= BVP_MIN_AB
                and abs(gap) >= BVP_AVG_GAP):
            favours = ctx.abbr("away" if gap > 0 else "home")
    sentence = ". ".join(parts) + "."
    sentence += (" These are career head-to-head totals; at this many at-bats "
                 "they are background, not a measured tendency.")
    if len(sides) == 1:
        sentence += " The other lineup's history is not on file, so there is no comparison."
    caveat = ("Small samples by nature: nine hitters each with a handful of "
              "at-bats. Career totals with no date cutoff, so they are as old "
              "as the hitters' careers.")
    return _factor(ctx, "batter_vs_pitcher", "Hitters against this pitcher",
                   favours, size, "Head-to-head history is shown for background; "
                   "the at-bat counts are small.",
                   sentence, evidence, "low", caveat, True)


# ---------------------------------------------------------------------------
# Teams: season strength, recent form, rest and travel
# ---------------------------------------------------------------------------

def _team_conf(ctx: _Ctx, games: Optional[float]) -> tuple:
    games = games or 0
    conf = "high" if games >= 100 else "medium" if games >= 40 else "low"
    reasons = []
    if ctx.results_stale and ctx.results_days is not None and ctx.results_days > 7:
        conf = _cap(conf, "medium")
        reasons.append(ctx.results_phrase())
    elif ctx.results_stale and not ctx.inputs:
        conf = _cap(conf, "medium")
        reasons.append("we cannot tell how current our results are")
    return conf, reasons


def _f_season_strength(ctx: _Ctx) -> Optional[dict]:
    t = ctx.sec("teams")
    if not t:
        ctx.miss("Team records", "absent", ctx.gaps.get("teams")
                 or "no team run rates are on this page")
        return None
    a, h = _num(t.get("away_run_diff_pg")), _num(t.get("home_run_diff_pg"))
    if a is None or h is None:
        return None
    gap = a - h
    size = _size(gap, MARGIN_SLIGHT, MARGIN_MODERATE, MARGIN_LARGE)
    games = min(_num(t.get("away_games_played")) or 0, _num(t.get("home_games_played")) or 0)
    conf, reasons = _team_conf(ctx, games)
    if t.get("either_sample_thin"):
        conf = "low"
        reasons.append("at least one club has a thin sample")
    base = "advanced.sections.teams."
    evidence = [ctx.ev(f"{base}away_run_diff_pg", f"{ctx.club('away')} run margin per game"),
                ctx.ev(f"{base}home_run_diff_pg", f"{ctx.club('home')} run margin per game"),
                ctx.ev(f"{base}away_games_played", f"{ctx.club('away')} games played"),
                ctx.ev(f"{base}home_games_played", f"{ctx.club('home')} games played"),
                ctx.ev(f"{base}away_win_pct", f"{ctx.club('away')} win share"),
                ctx.ev(f"{base}home_win_pct", f"{ctx.club('home')} win share")]
    gt = ctx.game.get("game_type")
    caveat = f"Season rates; the smaller sample is {games:.0f} games."
    if gt and gt != "R":
        caveat = (f"This is a {_GAME_TYPES.get(gt, 'postseason')} game and these are "
                  f"regular season rates; the smaller sample is {games:.0f} games.")
    if reasons:
        caveat += " " + _cap1("; ".join(reasons)) + "."
    text = (f"The {ctx.club('away')} have outscored opponents by "
            f"{_fmt(a)} runs a game ({_fmt(t.get('away_runs_scored_pg'))} scored, "
            f"{_fmt(t.get('away_runs_allowed_pg'))} allowed) and the "
            f"{ctx.club('home')} by {_fmt(h)} "
            f"({_fmt(t.get('home_runs_scored_pg'))} scored, "
            f"{_fmt(t.get('home_runs_allowed_pg'))} allowed).")
    if size is None:
        return _factor(ctx, "season_strength", "Season run margin", "even", "slight",
                       "The two clubs have a similar season run margin, so "
                       "the season does not separate them.",
                       text + f" The gap of {abs(gap):.2f} runs a game is under "
                       f"the {MARGIN_SLIGHT:.2f} we call a difference.",
                       evidence, conf, caveat, bool(reasons))
    better = "away" if gap > 0 else "home"
    return _factor(ctx, "season_strength", "Season run margin", ctx.abbr(better),
                   size, f"The {ctx.club(better)} have the better season run margin "
                   f"({_fmt(t.get(f'{better}_run_diff_pg'))} against "
                   f"{_fmt(t.get(f'{ctx.other(better)}_run_diff_pg'))} a game).",
                   text + f" The {abs(gap):.2f} run gap favours the {ctx.club(better)}.",
                   evidence, conf, caveat, bool(reasons))


def _f_recent_form(ctx: _Ctx) -> Optional[dict]:
    t = ctx.sec("teams")
    if not t:
        return None
    forms = {}
    for side in ("away", "home"):
        l10 = _num(t.get(f"{side}_last10_run_diff_pg"))
        season = _num(t.get(f"{side}_run_diff_pg"))
        n = _num(t.get(f"{side}_last10_games"))
        if l10 is None or season is None or not n:
            continue
        forms[side] = (l10, season, n, l10 - season)
    if len(forms) < 2:
        if forms:
            ctx.miss("Recent form", "thin", "only one club has a ten-game line")
        return None
    gap = forms["away"][3] - forms["home"][3]
    base = "advanced.sections.teams."
    parts = []
    for side in ("away", "home"):
        l10, season, n, delta = forms[side]
        parts.append(f"the {ctx.club(side)} outscored opponents by {l10:.2f} a game "
                     f"over their last {int(n)}, against {season:.2f} on the season")
    evidence = []
    for side in ("away", "home"):
        evidence += [ctx.ev(f"{base}{side}_last10_run_diff_pg",
                            f"{ctx.club(side)} run margin, last ten"),
                     ctx.ev(f"{base}{side}_last10_games", f"{ctx.club(side)} games in the window"),
                     ctx.ev(f"{base}{side}_last5_run_diff_pg",
                            f"{ctx.club(side)} run margin, last five")]
    stale = ctx.results_stale
    caveat = ("Ten games swings by more than a run a game on luck alone, so this "
              "factor is capped at slight.")
    if stale:
        caveat += (" " + _cap1(ctx.results_phrase()) + ", so these ten "
                   "games are the newest in our records, not the newest played.")
    favours = "even"
    if abs(gap) >= RECENT_SLIGHT:
        favours = ctx.abbr("away" if gap > 0 else "home")
    sentence = _cap1("; ".join(parts)) + "."
    if favours != "even":
        sentence += (f" The {ctx.club(favours)} are running further above their "
                     "season line.")
    else:
        sentence += " Neither club is far from its season line."
    return _factor(ctx, "recent_form", "Recent run scoring and prevention",
                   favours, "slight",
                   (f"The {ctx.club(favours)} are running further above their season "
                    "line over the last ten games, a small sample."
                    if favours != "even" else
                    "Neither club is far from its season line over the last ten games."),
                   sentence, evidence, "low", caveat, True)


def _f_rest_travel(ctx: _Ctx) -> Optional[dict]:
    travel = ctx.sec("travel")
    if not travel:
        ctx.miss("Travel", "absent", ctx.gaps.get("travel") or "travel load was not computed")
        return None
    loads = {}
    for side in ("away", "home"):
        row = travel.get(ctx.abbr(side)) or {}
        if row.get("reason") or row.get("games_last_7") in (None, 0):
            ctx.miss(f"{ctx.club(side)} travel", "absent",
                     (row.get("reason") or "no games in the window")
                     + f"; {ctx.results_phrase()}")
            continue
        flags = []
        if row.get("dense_stretch"):
            flags.append("a dense stretch of games")
        if row.get("eastward") and (row.get("zones") or 0) >= TRAVEL_ZONES:
            flags.append(f"{row.get('zones')} time zones east")
        if (row.get("miles") or 0) >= TRAVEL_MILES:
            flags.append(f"{row.get('miles'):.0f} miles flown")
        loads[side] = (row, flags)
    t = ctx.sec("teams") or {}
    rest_a, rest_h = _num(t.get("away_rest_days")), _num(t.get("home_rest_days"))
    rest_ok = (not ctx.results_stale and rest_a is not None and rest_h is not None)
    if (rest_a is not None or rest_h is not None) and not rest_ok:
        ctx.miss("Days of rest", "stale",
                 f"the rest days on the page ({_fmt(rest_a, 0)} and {_fmt(rest_h, 0)}) "
                 "are the gap since the newest game in our results, and "
                 f"{ctx.results_phrase()}, so they are not a measured break")
    if not loads and not rest_ok:
        return None
    parts, evidence = [], []
    for side, (row, flags) in loads.items():
        parts.append(f"the {ctx.club(side)} carry " + (_join(flags) if flags
                     else "no travel flag") + f" over {row.get('games_last_7')} games in seven days")
        evidence += [ctx.ev(f"advanced.sections.travel.{ctx.abbr(side)}.miles",
                            f"{ctx.club(side)} miles flown"),
                     ctx.ev(f"advanced.sections.travel.{ctx.abbr(side)}.games_last_7",
                            f"{ctx.club(side)} games in seven days")]
    favours, size = "even", "slight"
    if len(loads) == 2:
        la, lh = len(loads["away"][1]), len(loads["home"][1])
        if la != lh:
            favours = ctx.abbr("home" if la > lh else "away")
            size = "moderate" if abs(la - lh) >= 2 else "slight"
    if rest_ok:
        parts.append(f"rest is {_fmt(rest_a, 0)} days for the {ctx.club('away')} and "
                     f"{_fmt(rest_h, 0)} for the {ctx.club('home')}")
        evidence += [ctx.ev("advanced.sections.teams.away_rest_days",
                            f"{ctx.club('away')} days of rest"),
                     ctx.ev("advanced.sections.teams.home_rest_days",
                            f"{ctx.club('home')} days of rest")]
    sentence = _cap1("; ".join(parts)) + "."
    caveat = ("Whether travel costs runs is a hypothesis this project has not "
              "tested, so the factor is shown at low confidence.")
    return _factor(ctx, "rest_travel", "Rest and travel", favours, size,
                   (f"The {ctx.club(favours)} carry the lighter travel load into "
                    "this game." if favours != "even" else
                    "Travel and rest do not separate the clubs."),
                   sentence, evidence, "low", caveat, True)


def _f_bullpen(ctx: _Ctx) -> Optional[dict]:
    pens = ctx.sec("bullpen")
    if not pens:
        ctx.miss("Bullpen workload", "absent", ctx.gaps.get("bullpen") or "bullpen workload was not built")
        return None
    usable, current = {}, not ctx.bullpen_stale and ctx.bullpen_through is not None
    for side in ("away", "home"):
        row = pens.get(ctx.abbr(side)) or {}
        usable[side] = row
    counts = {s: (r.get("reliever_count") or 0) for s, r in usable.items()}
    if not current or not all(counts.values()):
        if ctx.bullpen_through is None:
            why = "our bullpen log has no stated end date"
        else:
            why = (f"our bullpen log ends {ctx.bullpen_through}, "
                   f"{_plural(ctx.bullpen_days, 'day')} before this game")
        ctx.miss("Bullpen workload", "stale",
                 f"{why}, so the seven day workload window holds "
                 f"{_plural(counts['away'], 'relief outing')} for the "
                 f"{ctx.club('away')} and {counts['home']} for the "
                 f"{ctx.club('home')}; it is not used")
        return None
    pts, parts, evidence = {}, [], []
    for side, row in usable.items():
        rel = row.get("relievers") or []
        un = sum(1 for r in rel if r.get("availability") == "likely_unavailable")
        q = sum(1 for r in rel if r.get("availability") == "questionable")
        pts[side] = un * 2 + q
        parts.append(f"the {ctx.club(side)} have thrown {_fmt(row.get('total_innings'), 1)} "
                     f"relief innings in seven days across {row.get('reliever_count')} "
                     f"pitchers, with {un} likely unavailable and {q} questionable")
        base = f"advanced.sections.bullpen.{ctx.abbr(side)}"
        evidence += [ctx.ev(f"{base}.total_innings", f"{ctx.club(side)} relief innings, seven days"),
                     ctx.ev(f"{base}.reliever_count", f"{ctx.club(side)} relievers used")]
    gap = pts["away"] - pts["home"]
    size = _size(gap, PEN_SLIGHT, PEN_MODERATE, 99)
    favours = "even"
    if size:
        favours = ctx.abbr("home" if gap > 0 else "away")
    sentence = _cap1("; ".join(parts)) + "."
    sentence += (f" That leaves the {ctx.club(favours)} better rested in relief."
                 if size else " The two bullpens are about equally taxed.")
    return _factor(ctx, "bullpen", "Bullpen workload", favours, size or "slight",
                   (f"The {ctx.club(favours)} bullpen is better rested over the "
                    "last seven days." if favours != "even" else
                    "The two bullpens are about equally taxed over the last seven days."),
                   sentence, evidence, "medium",
                   "Availability tags come from recent pitch counts and days "
                   "off; they are not injury reports.")


# ---------------------------------------------------------------------------
# Park and weather
# ---------------------------------------------------------------------------

def _f_park_weather(ctx: _Ctx) -> Optional[dict]:
    park = ctx.sec("park")
    weather = ctx.sec("weather")
    if not park and not weather:
        ctx.miss("Park and weather", "absent", "no park or weather on this page")
        return None
    notes, evidence, points = [], [], 0
    roof = (park or {}).get("roof")
    name = (park or {}).get("name") or "the park"
    if park:
        evidence.append(ctx.ev("advanced.sections.park.roof", "roof type"))
    pf = ctx.inputs.get("park_factor") or {}
    factor = _num(pf.get("factor"))
    if factor is not None:
        evidence += [ctx.ev("read_inputs.park_factor.factor", "park run factor"),
                     ctx.ev("read_inputs.park_factor.home_games", "home games behind the park factor")]
        if pf.get("thin"):
            notes.append(f"the park factor of {factor:.3f} rests on thin games")
        elif factor >= PARK_HIGH:
            points += 1
            notes.append(f"the park factor of {factor:.3f} makes it a higher scoring park")
        elif factor <= PARK_LOW:
            points -= 1
            notes.append(f"the park factor of {factor:.3f} makes it a lower scoring park")
        else:
            notes.append(f"the park factor of {factor:.3f} is close to neutral")
    else:
        ctx.miss("Park run factor", "absent", "no park factor could be measured from our results")
    altitude = _num((park or {}).get("altitude_m"))
    if altitude is not None and altitude >= ALTITUDE_HIGH_M:
        points += 2
        notes.append(f"the park sits {altitude:.0f} metres up, where the ball carries")
        evidence.append(ctx.ev("advanced.sections.park.altitude_m", "park altitude (metres)"))

    weather_used = False
    caveat_bits = ["Park orientation is not on file for any ballpark, so wind "
                   "direction cannot be read as blowing in or out."]
    if roof == "fixed":
        notes.append("the roof is fixed, so the weather outside does not apply")
    elif roof == "retractable":
        notes.append("the roof can close and its state for this game is not on file, "
                     "so the weather is not used")
        ctx.miss("Roof state", "absent",
                 f"{name} has a retractable roof and the page does not say whether it is closed")
    elif weather:
        hours = _num(weather.get("hours_from_first_pitch"))
        forecast_far = hours is not None and abs(hours) > FORECAST_HOURS
        temp, wind = _num(weather.get("temp_f")), _num(weather.get("wind_mph"))
        rain = _num(weather.get("precip_probability_pct"))
        bits = []
        if temp is not None:
            if temp >= TEMP_WARM_F:
                points += 1
                bits.append(f"{temp:.0f} F, warm air that carries the ball")
            elif temp <= TEMP_COLD_F:
                points -= 1
                bits.append(f"{temp:.0f} F, cold air that holds the ball down")
            else:
                bits.append(f"{temp:.0f} F, a mild reading")
            evidence.append(ctx.ev("advanced.sections.weather.temp_f", "forecast temperature (F)"))
        if wind is not None:
            if wind >= WIND_FLAG_MPH:
                bits.append(f"wind of {wind:.0f} mph whose direction we cannot read against this park")
            else:
                bits.append(f"light wind of {wind:.0f} mph")
            evidence.append(ctx.ev("advanced.sections.weather.wind_mph", "forecast wind (mph)"))
        if rain is not None:
            bits.append(f"a {rain:.0f}% chance of rain")
            evidence.append(ctx.ev("advanced.sections.weather.precip_probability_pct",
                                   "chance of rain (%)"))
        if bits:
            notes.append("the forecast around first pitch is " + _join(bits))
            weather_used = True
        if forecast_far:
            caveat_bits.append(f"The forecast hour is {abs(hours):.1f} hours from first pitch.")
        evidence.append(ctx.ev("advanced.sections.weather.hours_from_first_pitch",
                               "hours between the forecast hour and first pitch"))
    else:
        ctx.miss("Weather", "absent", ctx.gaps.get("weather") or "no forecast is on this page")
    if not notes:
        return None
    size = ("slight" if abs(points) <= 1 else "moderate" if abs(points) == 2
            else "large")
    leaning = ("tilted toward runs" if points > 0 else "tilted toward pitchers"
               if points < 0 else "not tilted either way")
    sentence = (f"At {name}, " + "; ".join(notes)
                + f". Taken together the setting is {leaning}, for both clubs equally.")
    if weather and roof == "open":
        temp_now = _num(weather.get("temp_f"))
        if temp_now is not None and (temp_now >= 100 or temp_now <= 20):
            caveat_bits.append(f"A forecast of {temp_now:.0f} F is extreme enough "
                               "to be worth checking against a live forecast.")
    conf = "medium" if weather_used or roof in ("fixed",) or factor is not None else "low"
    conf = "low" if (weather_used and weather and abs(_num(weather.get("hours_from_first_pitch")) or 0) > FORECAST_HOURS) else conf
    return _factor(ctx, "park_weather", "Park and weather", "even", size,
                   f"The setting at {name} is {leaning}, for both clubs equally.",
                   sentence,
                   evidence, conf, " ".join(caveat_bits), conf == "low")


# ---------------------------------------------------------------------------
# Run environment
# ---------------------------------------------------------------------------

def _se_rate(rate: float, n: float) -> Optional[float]:
    if rate is None or rate <= 0 or not n or n <= 0:
        return None
    return math.sqrt(strength.DISPERSION * rate / n)


def _run_environment(ctx: _Ctx) -> dict:
    out = {"label": RUN_LABEL, "available": False, "arithmetic": [], "caveats": [],
           "evidence": []}
    teams = ctx.sec("teams")
    league = _num((ctx.inputs.get("league_runs_per_game") or {}).get("value"))
    if not teams:
        out["reason"] = ctx.gaps.get("teams") or "no team run rates are on this page"
        ctx.miss("Run estimate", "absent", out["reason"])
        return out
    if league is None:
        out["reason"] = ("no league run rate could be measured from our results, so "
                         "offence cannot be scaled against defence")
        ctx.miss("Run estimate", "absent", out["reason"])
        return out
    features = dict(teams)
    features.update(ctx.sec("starters") or {})
    pf = ctx.inputs.get("park_factor") or {}
    park_factor = _num(pf.get("factor"))
    if park_factor:
        features["park_factor"] = park_factor
    try:
        rm = strength.run_means(features, league_rpg=league)
    except strength.StrengthError as exc:
        out["reason"] = str(exc)
        ctx.miss("Run estimate", "absent", out["reason"])
        return out

    out["available"] = True
    lines = []
    games_league = (ctx.inputs.get("league_runs_per_game") or {}).get("games")
    lines.append(f"League scoring: {league:.2f} runs per team per game over "
                 f"{games_league} games in our results.")
    se_by_side, means = {}, {}
    for side in ("away", "home"):
        opp = ctx.other(side)
        club, foe = ctx.club(side), ctx.club(opp)
        games = _num(teams.get(f"{side}_games_played"))
        foe_games = _num(teams.get(f"{opp}_games_played"))
        offence = rm[f"{side}_offence"]
        defence = rm[f"{opp}_defence"]
        share = rm[f"{opp}_starter_share"]
        sp_rate = rm[f"{opp}_starter_rate"]
        pen = rm[f"{opp}_bullpen_rate"]
        lines.append(
            f"{club} offence: {_fmt(teams.get(f'{side}_runs_scored_pg'))} runs per game "
            f"over {games:.0f} games, pulled toward the league rate to {offence:.2f}.")
        if rm[f"{opp}_starter_known"]:
            lines.append(
                f"{foe} run prevention: {share:.2f} of the game is {ctx.pitcher(opp)} at "
                f"{sp_rate:.2f} runs per nine (his FIP of {_fmt(features.get(f'{opp}_sp_fip'))} "
                f"times {strength.FIP_TO_RA_SCALE}, pulled toward the league rate), and "
                f"{1 - share:.2f} is the bullpen at {pen:.2f}, the club's whole season rate "
                f"standing in for it. That blends to {defence:.2f}.")
        else:
            lines.append(
                f"{foe} run prevention: no starter line on file for {ctx.pitcher(opp)}, so the "
                f"club's season runs allowed of {pen:.2f} stands for the whole game.")
        mean_pre = offence * defence / league
        bump = f" plus the {strength.HOME_FIELD_RUNS:.2f} run home field credit" if side == "home" else ""
        park_txt = (f", times the park factor of {rm['park_factor']:.3f}"
                    if rm["park_known"] else ", with no park factor available")
        lines.append(f"{club} expected runs: {offence:.2f} x {defence:.2f} / {league:.2f} = "
                     f"{mean_pre:.2f}{bump}{park_txt}, giving {rm[f'{side}_mean']:.2f}.")
        mean = rm[f"{side}_mean"]
        means[side] = mean
        # Sampling error of the inputs, one standard error.
        se_off = _se_rate(offence, games)
        if rm[f"{opp}_starter_known"]:
            innings = _num(features.get(f"{opp}_sp_innings")) or 0
            sd_s = _se_rate(sp_rate, innings / 9.0)
            sd_p = _se_rate(pen, foe_games)
            se_def = (math.sqrt((share * (sd_s or 0)) ** 2 + ((1 - share) * (sd_p or 0)) ** 2)
                      if sd_s is not None and sd_p is not None else None)
        else:
            se_def = _se_rate(pen, foe_games)
        if se_off is None or se_def is None:
            se_by_side[side] = None
        else:
            se_by_side[side] = mean * math.sqrt((se_off / offence) ** 2 + (se_def / defence) ** 2)
    ses = [se_by_side.get("away"), se_by_side.get("home")]
    total = means["away"] + means["home"]
    if all(s is not None for s in ses):
        total_se = math.sqrt(ses[0] ** 2 + ses[1] ** 2)
        for side in ("away", "home"):
            out[side] = {"team": ctx.abbr(side), "expected_runs": round(means[side], 2),
                         "low": round(means[side] - se_by_side[side], 2),
                         "high": round(means[side] + se_by_side[side], 2)}
        out["game"] = {"expected_total": round(total, 2),
                       "low": round(total - total_se, 2), "high": round(total + total_se, 2)}
        lines.append(f"Range: one standard error of the season rates behind each number "
                     f"(the {ctx.club('away')} {out['away']['low']:.1f} to {out['away']['high']:.1f}, "
                     f"the {ctx.club('home')} {out['home']['low']:.1f} to {out['home']['high']:.1f}, "
                     f"total {out['game']['low']:.1f} to {out['game']['high']:.1f}). That is the "
                     "uncertainty in the inputs, not the spread of possible scores.")
    else:
        for side in ("away", "home"):
            out[side] = {"team": ctx.abbr(side), "expected_runs": round(means[side], 2),
                         "low": None, "high": None}
        out["game"] = {"expected_total": round(total, 2), "low": None, "high": None}
    sd_one = math.sqrt(strength.DISPERSION * max(total / 2.0, 0.01))
    lines.append(f"A single game is far wider than that range: one standard deviation of one "
                 f"club's score in a single game is about {sd_one:.1f} runs.")
    lead = means["away"] - means["home"]
    out["leader"] = ("even" if abs(lead) < RUN_LEAD_MIN
                     else ctx.abbr("away" if lead > 0 else "home"))
    out["arithmetic"] = lines
    out["caveats"] = [
        "Weather is not in this arithmetic; no weather effect has been fitted or tested here.",
        "Lineups are not in this arithmetic; both clubs are priced as their season selves.",
        "The bullpen share uses each club's whole season runs allowed, which includes its starters.",
    ]
    if ctx.pitcher_stale:
        out["caveats"].append(_cap1(ctx.pitcher_phrase())
                              + ", so starter lines miss his newest outings.")
    if ctx.results_stale:
        out["caveats"].append(_cap1(ctx.results_phrase())
                              + "; the season rates stop there.")
    base = "advanced.sections.teams."
    out["evidence"] = [e for e in (
        ctx.ev(f"{base}away_runs_scored_pg", f"{ctx.club('away')} runs scored per game"),
        ctx.ev(f"{base}away_runs_allowed_pg", f"{ctx.club('away')} runs allowed per game"),
        ctx.ev(f"{base}home_runs_scored_pg", f"{ctx.club('home')} runs scored per game"),
        ctx.ev(f"{base}home_runs_allowed_pg", f"{ctx.club('home')} runs allowed per game"),
        ctx.ev("read_inputs.league_runs_per_game.value", "league runs per team per game"),
        ctx.ev("read_inputs.park_factor.factor", "park run factor")) if e]
    return out


# ---------------------------------------------------------------------------
# Market view
# ---------------------------------------------------------------------------

def _market_view(ctx: _Ctx, factors: list, run_env: dict) -> dict:
    pi = ctx.sec("price_improvement") or {}
    sides = pi.get("sides") or {}
    probs = {}
    for side in ("away", "home"):
        p = _num((sides.get(side) or {}).get("consensus_probability"))
        if p is not None:
            probs[side] = p
    verdicts = ctx.payload.get("price_verdicts") or {}
    books = (pi.get("dispersion") or {}).get("books")
    age = _num((verdicts.get("home") or verdicts.get("away") or {}).get("age_seconds"))
    out = {"available": False, "label": "What the price implies, compared with this read.",
           "sentences": [], "evidence": [], "agreement": "no price"}
    if len(probs) < 2:
        out["sentences"].append("No priced board is on this page for this game, so "
                                "there is nothing to compare this read against.")
        ctx.miss("Market price", "absent", ctx.gaps.get("price_improvement")
                 or "no multi-book board for this game")
        return out
    out["available"] = True
    fav = "away" if probs["away"] > probs["home"] else "home"
    dog = ctx.other(fav)
    out["implied"] = {s: {"team": ctx.abbr(s), "probability": round(probs[s], 4),
                          "fair_price": (verdicts.get(s) or {}).get("fair_price")}
                      for s in ("away", "home")}
    out["books"] = books
    out["observed_utc"] = pi.get("observed_utc")
    fair = (verdicts.get(fav) or {}).get("fair_price")
    fair_txt = f" (a fair price of {int(fair):+d})" if isinstance(fair, (int, float)) else ""
    sent = [f"Across {books if books else 'the'} books the market makes the "
            f"{ctx.club(fav)} a {probs[fav] * 100:.1f}% favourite{fair_txt} and the "
            f"{ctx.club(dog)} {probs[dog] * 100:.1f}%, with each book's margin removed."]
    out["evidence"] = [ctx.ev("advanced.sections.price_improvement.sides.away.consensus_probability",
                              f"{ctx.club('away')} price-implied share"),
                       ctx.ev("advanced.sections.price_improvement.sides.home.consensus_probability",
                              f"{ctx.club('home')} price-implied share"),
                       ctx.ev("advanced.sections.price_improvement.dispersion.books", "books on the board")]
    if age is not None:
        mins = age / 60.0
        sent.append(f"The board was captured {mins:.0f} minutes before this page was built"
                    + (", which is older than we like." if age > 1800 else "."))
    out["board_age_seconds"] = age

    # Our lean: team-favouring factors only, size times confidence.
    lean = 0.0
    for f in factors:
        if f["favours"] in (ctx.away, ctx.home) and f["factor"] != "park_weather":
            weight = _SIZE_RANK[f["size"]] * _CONF_MULT[f["confidence"]]
            lean += weight if f["favours"] == ctx.away else -weight
    side_lean = None if abs(lean) < LEAN_MIN else ("away" if lean > 0 else "home")
    out["lean"] = ctx.abbr(side_lean) if side_lean else "none"
    leader = run_env.get("leader") if run_env.get("available") else None
    thin = [m for m in ctx.missing if m["status"] in ("absent", "stale", "thin")]
    thin_n = len(thin)
    if side_lean is None:
        out["agreement"] = "no lean"
        sent.append("This read does not lean clearly toward either club, so it does "
                    "not agree or disagree with the price. On these inputs the price "
                    "is the better informed number.")
    elif side_lean == fav:
        out["agreement"] = "agrees"
        sent.append(f"This read leans toward the {ctx.club(side_lean)} too, so it "
                    "agrees with the market on direction. That is expected: starters "
                    "and run rates are already in the price. It says nothing about "
                    "whether the price is right.")
    else:
        out["agreement"] = "disagrees"
        sent.append(f"This read leans toward the {ctx.club(side_lean)}, the side the "
                    "market has as the underdog, so it disagrees with the price.")
        if thin_n >= 3 or any(f["confidence"] == "low" for f in factors[:3]):
            sent.append(f"With {thin_n} inputs missing or stale, the likelier explanation is "
                        "that our read is missing something the books have priced "
                        "in, a confirmed lineup, a starter we have no log for, a fresh "
                        "injury, not that the price is wrong.")
        else:
            sent.append("Even with the inputs we have, a disagreement with a board of "
                        "this many books is a question to check, not a finding.")
    if leader and leader != "even" and side_lean and ctx.abbr(side_lean) != leader:
        sent.append(f"Our run estimate leans the other way, to the {ctx.club(leader)}; "
                    "the pieces of this read are pulling against each other.")
    sent.append(RESEARCH_NOTE)
    out["sentences"] = sent
    return out


# ---------------------------------------------------------------------------
# What would change it, headline, assembly
# ---------------------------------------------------------------------------

def _what_would_change_it(ctx: _Ctx, factors: list) -> list:
    items = []
    keys = {f["factor"] for f in factors}
    starters = ctx.sec("starters") or {}
    away_known, home_known = bool(_sp(ctx, "away")), bool(_sp(ctx, "home"))
    if {"starting_pitching", "arsenal_results", "pitcher_regression"} & keys or not (away_known and home_known):
        extra = ""
        if not away_known or not home_known:
            missing_side = "away" if not away_known else "home"
            extra = (f" {ctx.pitcher(missing_side)} has no line on file, so news about "
                     "him would move this read the most.")
        items.append({"fact": "A change of starting pitcher.",
                      "because": (f"Both probables, {ctx.pitcher('away')} and "
                                  f"{ctx.pitcher('home')}, drive the pitching factors; a "
                                  "replacement or an opener voids them." + extra),
                      "evidence": [e for e in (ctx.ev("advanced.game.away_probable", "away probable"),
                                               ctx.ev("advanced.game.home_probable", "home probable")) if e]})
    lineups = ctx.sec("lineups")
    if not lineups:
        notes = []
        ev = []
        for side in ("away", "home"):
            platoon = (((ctx.sec("splits") or {}).get(side) or {}).get("platoon")) or {}
            if platoon.get("usable"):
                weaker = "left-handed" if platoon.get("weaker_against") == "L" else "right-handed"
                notes.append(f"{ctx.pitcher(side)} has been weaker against {weaker} bats "
                             f"({platoon.get('vs_left_faced')} and {platoon.get('vs_right_faced')} "
                             "batters faced on each side), so the make-up of the opposing lineup matters")
                ev.append(ctx.ev(f"advanced.sections.splits.{side}.platoon.gap",
                                 f"{ctx.pitcher(side)} OPS gap, left minus right"))
        items.append({"fact": "The lineups, once posted.",
                      "because": ("Platoon, depth and pitch-mix factors cannot be read until "
                                  "they are. " + (_cap1("; ".join(notes)) + "." if notes else "")).strip(),
                      "evidence": [e for e in ev if e]})
    else:
        names = []
        for side in ("away", "home"):
            batters = ((lineups.get(side) or {}).get("batters") or [])
            top = [b.get("name") for b in batters if (b.get("order") or 9) <= 3 and b.get("name")]
            if top:
                names.append(f"{ctx.club(side)}: {_join(top)}")
        items.append({"fact": "A late scratch from the top of either lineup.",
                      "because": ("The depth and platoon counts above come from the posted "
                                  "nine; a replacement changes both. Top of the order, "
                                  + "; ".join(names) + "."),
                      "evidence": []})
    park = ctx.sec("park") or {}
    weather = ctx.sec("weather") or {}
    roof = park.get("roof")
    if roof == "retractable":
        items.append({"fact": "Whether the roof is open or closed.",
                      "because": "The page does not give the roof state, and it decides whether the weather matters.",
                      "evidence": [ctx.ev("advanced.sections.park.roof", "roof type")]})
    elif roof == "open" and weather:
        items.append({"fact": "A change in the forecast before first pitch.",
                      "because": (f"The scoring setting uses {_fmt(weather.get('temp_f'), 0)} F, "
                                  f"{_fmt(weather.get('wind_mph'), 0)} mph wind and a "
                                  f"{_fmt(weather.get('precip_probability_pct'), 0)}% chance of rain; "
                                  "rain could also delay or shorten the game."),
                      "evidence": [e for e in (ctx.ev("advanced.sections.weather.temp_f", "forecast temperature (F)"),
                                               ctx.ev("advanced.sections.weather.wind_mph", "forecast wind (mph)")) if e]})
    if len(items) < 2:
        items.append({"fact": "A move in the price.",
                      "because": "The market has the freshest word on lineups and injuries; a sharp move "
                                 "after this read was built would mean something we do not see.",
                      "evidence": []})
    return items[:3]


def _headline(ctx: _Ctx, ranked: list, run_env: dict) -> str:
    live = [f for f in ranked if f["favours"] != "even" or f["factor"] == "park_weather"]
    top = None
    for f in live:
        if _SIZE_RANK[f["size"]] * _CONF_MULT[f["confidence"]] >= 0.6:
            top = f
            break
    away, home = ctx.club("away"), ctx.club("home")

    # A starter with no line is the largest hole in a read. When nothing else
    # in the read is better than slight-on-medium-data, say that first.
    best = _SIZE_RANK[top["size"]] * _CONF_MULT[top["confidence"]] if top else 0.0
    lacking = [s for s in ("away", "home")
               if ctx.sec("starters") and _sp(ctx, s) is None]
    if lacking and best < 1.2:
        known = [s for s in ("away", "home") if s not in lacking]
        if known:
            kn = _sp(ctx, known[0])
            return (f"{kn['name']} has a pitching line on file ({_fmt(kn['fip'])} FIP over "
                    f"{_fmt(kn['innings'], 0)} innings) and {ctx.pitcher(lacking[0])} does not, "
                    "so the starting pitching matchup cannot be read and nothing else on "
                    "this page is large enough to replace it.")
        return ("Neither probable starter has a pitching line on file, so the starting "
                "pitching matchup cannot be read and nothing else on this page is large "
                "enough to replace it.")
    if top is None:
        thin = [m["input"] for m in ctx.missing if m["status"] in ("absent", "stale")]
        tail = (f" Key inputs are missing or stale: {_join(thin[:3])}." if thin else "")
        return (f"No single factor clearly separates the {away} and the {home} in the "
                f"data we have, and that is a valid read.{tail}")
    parts = [top["short"].rstrip(".")]
    if top["confidence"] == "low":
        parts.append("the data behind it is thin")
    if top["factor"] != "starting_pitching":
        for side in ("away", "home"):
            if ctx.game.get(f"{side}_probable") and _sp(ctx, side) is None:
                parts.append(f"{ctx.pitcher(side)} has no pitching line on file")
    return "; ".join(parts) + "."


def _notices(ctx: _Ctx) -> list:
    notes = []
    state = str(ctx.game.get("detailed_state") or "").lower()
    started = state in _STARTED_STATES or (
        ctx.game.get("away_score") is not None and state not in ("pre-game", "scheduled", "warmup"))
    if started:
        notes.append(f"This game is already under way or finished ({ctx.game.get('detailed_state')}). "
                     "The read describes the game before first pitch and does not use the live score.")
    gt = ctx.game.get("game_type")
    if gt and gt != "R":
        notes.append(f"This is a {_GAME_TYPES.get(gt, 'postseason game')}. Team rates on this page "
                     "are regular season rates.")
    return notes


def _record_staleness(ctx: _Ctx) -> None:
    if not ctx.inputs:
        ctx.miss("Age of our data", "stale",
                 "this page does not say how old our results, pitcher logs and bullpen log are, "
                 "so none of them can be called current")
        return
    if ctx.results_through is None:
        ctx.miss("Team results", "stale", "our results store has no usable end date")
    elif ctx.results_stale:
        ctx.miss("Team results", "stale",
                 f"{ctx.results_phrase()}, so last-five, last-ten, rest and travel are "
                 "older than they look")
    if ctx.pitcher_through is None:
        ctx.miss("Pitcher logs", "stale", "our pitcher logs have no usable end date")
    elif ctx.pitcher_stale:
        ctx.miss("Pitcher logs", "stale",
                 f"{ctx.pitcher_phrase()}, so starters' season lines and last-three-start "
                 "figures miss anything newer, and a rest figure of 14 or more days is not "
                 "reliable")


def _record_gaps(ctx: _Ctx) -> None:
    for name, label in (("standings", "League standings"),
                        ("matchup_depth", "Matchup depth")):
        if name in ctx.gaps and name not in ctx.sections:
            ctx.miss(label, "absent", str(ctx.gaps[name]))
    if "splits" in ctx.gaps and not ctx.sec("splits"):
        ctx.miss("Pitcher platoon splits", "absent", str(ctx.gaps["splits"]))
    if ctx.sec("splits"):
        for side in ("away", "home"):
            if not (ctx.sec("splits") or {}).get(side):
                ctx.miss(f"{ctx.pitcher(side)} platoon split", "absent",
                         f"no platoon split is on file for {ctx.pitcher(side)}")
    splits = ctx.sec("splits") or {}
    for side, record in splits.items():
        as_of = ((record or {}).get("record") or {}).get("as_of")
        days = _days_between(as_of, ctx.date)
        if days is not None and days > PITCHER_STALE_DAYS:
            ctx.miss(f"{ctx.pitcher(side)} platoon split", "stale",
                     f"the split was last updated {str(as_of)[:10]}, {_plural(days, 'day')} before this game")
    if not ctx.sec("lineups") and "lineups" not in ctx.gaps:
        ctx.miss("Lineups", "absent", "no lineup is on this page")


_FACTORS = (
    _f_starting_pitching, _f_arsenal_results, _f_pitcher_regression, _f_hr_park,
    _f_pitcher_form, _f_platoon, _f_lineup_depth, _f_pitch_mix,
    _f_batter_vs_pitcher, _f_season_strength, _f_recent_form, _f_bullpen,
    _f_rest_travel, _f_park_weather,
)


def build_read(payload: dict) -> dict:
    """The written read of one game. `payload` is the game payload
    (`GET /game/{date}/{away}/{home}`), with an optional `read_inputs` block.

    Never raises: a factor that fails is reported in `missing` as an error and
    the rest of the read is still produced.
    """
    ctx = _Ctx(payload)
    _record_staleness(ctx)
    found = []
    for index, fn in enumerate(_FACTORS):
        try:
            factor = fn(ctx)
        except Exception as exc:  # noqa: BLE001 -- one factor never takes the read down
            ctx.miss(fn.__name__.replace("_f_", "").replace("_", " "), "error",
                     f"this factor could not be computed from the data on this page ({type(exc).__name__})")
            continue
        if factor:
            factor["_order"] = index
            found.append(factor)
    _record_gaps(ctx)
    try:
        run_env = _run_environment(ctx)
    except Exception as exc:  # noqa: BLE001
        run_env = {"label": RUN_LABEL, "available": False,
                   "reason": "the estimate could not be computed from this page's data",
                   "arithmetic": [], "caveats": [], "evidence": []}
        ctx.miss("Run estimate", "error", f"{type(exc).__name__}")
    ranked = sorted(found, key=lambda f: (-(_SIZE_RANK[f["size"]] * _CONF_MULT[f["confidence"]]),
                                          f["_order"]))
    for rank, f in enumerate(ranked, 1):
        f["rank"] = rank
        f.pop("_order", None)
    try:
        market = _market_view(ctx, ranked, run_env)
    except Exception as exc:  # noqa: BLE001
        market = {"available": False, "label": "What the price implies, compared with this read.",
                  "sentences": ["The price comparison could not be built from this page's data."],
                  "evidence": [], "agreement": "no price"}
        ctx.miss("Market price", "error", f"{type(exc).__name__}")
    out = {
        "label": LABEL,
        "as_of": ctx.as_of,
        "headline": _headline(ctx, ranked, run_env),
        "notices": _notices(ctx),
        "factors": ranked,
        "run_environment": run_env,
        "market_view": market,
        "what_would_change_it": _what_would_change_it(ctx, ranked),
        "missing": ctx.missing,
    }
    # The situation block is its own key and only when the payload carries a record: a read built
    # without one has exactly the keys it always had, and a record that cannot be shown costs the
    # block, never the read.
    try:
        block = situation_record.page_block((payload or {}).get("situation"), label=SITUATION_LABEL,
                                            limit=SITUATION_LINES)
    except Exception:  # noqa: BLE001 -- additive, never takes the read down
        block = None
    if block is not None:
        out["situation"] = block
    return out
