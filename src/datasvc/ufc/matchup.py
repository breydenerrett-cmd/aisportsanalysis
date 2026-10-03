"""The matchup fact sheet: two fighters side by side, with the booked bout and its odds.

This is the page an analyst (or the AI analyst) reads before forming a view. It
contains facts and nothing else: no prediction, no pick, no edge, no "value". The only
probabilities in it are the MARKET's own, labelled as such (`implied` is the price
turned into a probability; `without_margin` is that probability after the bookmaker's
margin is divided out). They are not ours and must not be read as ours.

LEAKAGE
-------
`as_of` is the one moment everything is measured at. When a scheduled bout between the
two fighters exists it defaults to that bout's start (the question being asked is what
each fighter had done when they walked in); otherwise to now. Both fighters' features,
the shared opponents and the previous meetings all go through
`features.completed_fights`, which admits only bouts that started strictly before it,
so nothing in the sheet can see the fight it describes. The odds are the exception by
nature: they are the prices as fetched (`fetched_utc`), not prices as of `as_of`.

THE ODDS BLOCK
--------------
Prices are American. `implied` = 100/(p+100) for a plus price and |p|/(|p|+100) for a
minus price. A market's margin is the sum of the implied probabilities minus 1 over
every outcome that can happen in it (two for a moneyline or a rounds total, six for
method of victory); `without_margin` divides each implied probability by that sum.
Removing the margin needs every price of the market: with one side missing the
implied figures are still shown but `margin` and `without_margin` are None.

The store labels the two sides of an odds row a and b of the BOUT. This sheet's a and
b are whoever the caller passed first, so the odds are mapped by fighter identity
and never by position: asking for (b, a) swaps the sides of every price. A row whose
orientation is not "verified" is shown with its prices withheld, because a price on
the wrong fighter is worse than no price.

STYLE LABELS
------------
Simple descriptive labels over the figures, each with its thresholds written down in
STYLE_RULES below and in docs/datasvc/UFC_FEATURES.md, and each with a minimum sample.
A label that cannot be judged because the sample is too small is reported as
`not_assessed` with the reason, never as "does not apply": no label is not the same
claim as "assessed and failed".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.datasvc.ufc import features as feat

FACTS_ONLY = ("Facts only. No prediction, no pick. The probabilities in the odds block are the market's own, "
              "not an estimate made here.")

# -- thresholds ------------------------------------------------------------------------
#
# Round-number starting points chosen to sit clearly above or below an ordinary roster
# fighter. They are descriptive labels, not fitted to outcomes and not tuned against
# results, and they should be recalibrated against percentiles of the store's own
# distribution once the full backfill exists.

MIN_FIGHTS_TIMED = 3           # fights with the statistic behind a rate or a ratio
MIN_MINUTES_TIMED = 30.0       # and at least this many fight minutes in that sample
MIN_FIGHTS_RESULTS = 5         # fights with a known method behind a share of results

WRESTLER_TAKEDOWNS_PER_15 = 2.0
WRESTLER_CONTROL_SHARE = 0.20
SUBMISSION_ATTEMPTS_PER_15 = 1.0
STRIKER_DISTANCE_SHARE = 0.75
STRIKER_MAX_TAKEDOWNS_PER_15 = 1.0
VOLUME_STRIKES_PER_MIN = 5.0
KNOCKOUT_KNOCKDOWNS_PER_15 = 0.75
FINISHER_FINISH_RATE = 0.60
VULNERABLE_BEEN_FINISHED_RATE = 0.30
DISTANCE_RATE = 0.60
HARD_TO_TAKE_DOWN_DEFENCE = 0.80
HARD_TO_TAKE_DOWN_MIN_ATTEMPTS = 10


@dataclass(frozen=True)
class Condition:
    figure: str
    op: str                          # ">=" or "<"
    threshold: float
    min_fights: int
    min_minutes: Optional[float] = None
    min_den: Optional[float] = None  # e.g. opponents' takedown attempts behind a defence figure
    den_label: str = "attempts"

    def text(self) -> str:
        return f"{self.figure} {self.op} {self.threshold:g}"


@dataclass(frozen=True)
class StyleRule:
    name: str
    summary: str
    conditions: Tuple[Condition, ...]

    def text(self) -> str:
        return " and ".join(c.text() for c in self.conditions)


def _timed(figure, op, threshold, **kw) -> Condition:
    return Condition(figure, op, threshold, MIN_FIGHTS_TIMED, MIN_MINUTES_TIMED, **kw)


def _results(figure, op, threshold) -> Condition:
    return Condition(figure, op, threshold, MIN_FIGHTS_RESULTS)


STYLE_RULES: Tuple[StyleRule, ...] = (
    StyleRule("wrestler", "lands takedowns often and spends real time in control",
              (_timed("takedowns_landed_per_15", ">=", WRESTLER_TAKEDOWNS_PER_15),
               _timed("control_time_share", ">=", WRESTLER_CONTROL_SHARE))),
    StyleRule("submission_threat", "throws submission attempts often",
              (_timed("submission_attempts_per_15", ">=", SUBMISSION_ATTEMPTS_PER_15),)),
    StyleRule("striker", "lands most of his significant strikes at distance and rarely takes anyone down",
              (_timed("sig_strike_share_distance", ">=", STRIKER_DISTANCE_SHARE),
               _timed("takedowns_landed_per_15", "<", STRIKER_MAX_TAKEDOWNS_PER_15))),
    StyleRule("volume_striker", "lands significant strikes at a high rate",
              (_timed("sig_strikes_landed_per_min", ">=", VOLUME_STRIKES_PER_MIN),)),
    StyleRule("knockout_threat", "scores knockdowns at a high rate",
              (_timed("knockdowns_landed_per_15", ">=", KNOCKOUT_KNOCKDOWNS_PER_15),)),
    StyleRule("finisher", "most of his fights end in a finishing win",
              (_results("finish_rate", ">=", FINISHER_FINISH_RATE),)),
    StyleRule("vulnerable_to_finish", "a large share of his fights end in a finishing loss",
              (_results("been_finished_rate", ">=", VULNERABLE_BEEN_FINISHED_RATE),)),
    StyleRule("goes_the_distance", "most of his fights go to the judges' scorecards",
              (_results("distance_rate", ">=", DISTANCE_RATE),)),
    StyleRule("hard_to_take_down", "stops most takedown attempts, against enough attempts to mean it",
              (_timed("takedown_defence", ">=", HARD_TO_TAKE_DOWN_DEFENCE,
                      min_den=HARD_TO_TAKE_DOWN_MIN_ATTEMPTS, den_label="opponent takedown attempts"),)),
)


def _condition_status(cond: Condition, figures: dict) -> Tuple[str, Optional[str], Optional[float]]:
    """("holds" | "fails" | "not_assessed", reason, value)."""
    fig = figures.get(cond.figure) or {}
    value = fig.get("value")
    if value is None:
        return "not_assessed", f"{cond.figure}: {fig.get('reason') or 'not computed'}", None
    if fig.get("fights", 0) < cond.min_fights:
        return "not_assessed", f"{cond.figure}: needs {cond.min_fights} fights, has {fig.get('fights', 0)}", value
    if cond.min_minutes is not None and fig.get("minutes", 0.0) < cond.min_minutes:
        return "not_assessed", f"{cond.figure}: needs {cond.min_minutes:g} fight minutes, has {fig.get('minutes', 0.0):g}", value
    if cond.min_den is not None and (fig.get("den") or 0) < cond.min_den:
        return ("not_assessed",
                f"{cond.figure}: needs {cond.min_den:g} {cond.den_label}, has {fig.get('den') or 0:g}", value)
    holds = value >= cond.threshold if cond.op == ">=" else value < cond.threshold
    return ("holds" if holds else "fails"), None, value


def style_descriptors(fighter_features: dict) -> dict:
    """The style labels that apply to one fighter, those that do not, and those not judged.

    A rule is an AND of conditions. If every condition could be judged it applies or it
    does not. If some could not be judged but one that could has already failed, the rule
    cannot hold and is "does_not_apply". Otherwise it is "not_assessed" with the reasons.
    Conditions are tested against the figures as reported (already rounded), so the
    evidence shown is exactly what was compared.
    """
    figures = fighter_features["figures"]
    applies, fails, unjudged = [], [], []
    for rule in STYLE_RULES:
        results = [_condition_status(c, figures) for c in rule.conditions]
        statuses = [r[0] for r in results]
        if "fails" in statuses:
            fails.append(rule.name)
        elif "not_assessed" in statuses:
            unjudged.append({"name": rule.name, "reason": "; ".join(r[1] for r in results if r[0] == "not_assessed")})
        else:
            used = [figures[c.figure] for c in rule.conditions]
            applies.append({
                "name": rule.name, "summary": rule.summary, "rule": rule.text(),
                "evidence": {c.figure: figures[c.figure]["value"] for c in rule.conditions},
                "sample": {"fights": min(f["fights"] for f in used),
                           "minutes": min(f["minutes"] for f in used)}})
    return {"applies": applies, "does_not_apply": fails, "not_assessed": unjudged,
            "checked": [r.name for r in STYLE_RULES]}


# -- differentials ----------------------------------------------------------------------

# Figures where a minus b means something. Height, reach, age and layoff have their own
# blocks; counts that are just a sample size are not differenced except experience.
TIMED_FIGURES = (
    "sig_strikes_landed_per_min", "sig_strikes_absorbed_per_min", "sig_strike_accuracy",
    "sig_strike_defence", "knockdowns_landed_per_15", "knockdowns_suffered_per_15",
    "takedowns_landed_per_15", "takedown_accuracy", "takedown_defence", "control_time_share",
    "submission_attempts_per_15",
)
RESULT_FIGURES = (
    "win_rate", "finish_rate", "been_finished_rate", "distance_rate", "average_fight_time_s",
    "strength_of_schedule",
)
DIFFERENTIAL_FIGURES = ("ufc_fights",) + RESULT_FIGURES + TIMED_FIGURES


def _thin(fig: dict, timed: bool) -> bool:
    if fig.get("value") is None:
        return True
    if timed:
        return fig["fights"] < MIN_FIGHTS_TIMED or fig["minutes"] < MIN_MINUTES_TIMED
    return fig["fights"] < MIN_FIGHTS_RESULTS


def differentials(fa: dict, fb: dict) -> dict:
    out = {}
    for name in DIFFERENTIAL_FIGURES:
        a, b = fa["figures"][name], fb["figures"][name]
        va, vb = a["value"], b["value"]
        entry = {
            "unit": a["unit"], "a": va, "b": vb,
            "diff": None if va is None or vb is None else round(va - vb, 4),
            "a_sample": {"fights": a["fights"], "minutes": a["minutes"]},
            "b_sample": {"fights": b["fights"], "minutes": b["minutes"]},
        }
        if name != "ufc_fights":
            timed = name in TIMED_FIGURES
            entry["thin_sample"] = _thin(a, timed) or _thin(b, timed)
        out[name] = entry
    return out


# -- odds -------------------------------------------------------------------------------

METHODS = ("ko_tko_dq", "submission", "decision")
SNAPSHOTS = ("open", "close", "current")


def american_to_probability(price: Any) -> Optional[float]:
    """The probability an American price implies, margin included; None for anything else.

    American prices are never strictly between -100 and +100, so a value there (or a
    zero, a bool, a string) is a data fault and is refused rather than converted.
    """
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price):
        return None
    if price >= 100:
        return 100.0 / (price + 100.0)
    if price <= -100:
        return -price / (-price + 100.0)
    return None


def remove_margin(prices: Dict[str, Any]) -> dict:
    """`prices` maps each outcome of ONE market to its American price.

    Returns {"implied", "margin", "without_margin"}; the last two are None unless every
    outcome has a usable price, because dividing out a margin from part of a market
    divides by the wrong total.
    """
    implied = {k: american_to_probability(v) for k, v in prices.items()}
    shown = {k: None if v is None else round(v, 4) for k, v in implied.items()}
    if not implied or any(v is None for v in implied.values()):
        return {"implied": shown, "margin": None, "without_margin": None}
    total = sum(implied.values())
    return {"implied": shown, "margin": round(total - 1.0, 4),
            "without_margin": {k: round(v / total, 4) for k, v in implied.items()}}


def _is_price(value: Any) -> bool:
    return american_to_probability(value) is not None


def _method_price(method_odds: Any, side: str, snapshot: str, method: str) -> Optional[float]:
    """One method price out of `method_odds`, whichever way the odds worker nested it.

    The contract names the three methods and the sides but does not fix the nesting of
    open/close, so this walks the dict taking, at each level, any key that is still
    wanted (side, snapshot, method). It accepts snapshot-side-method, side-snapshot-method
    and side-method-snapshot. A price that does not say which snapshot it is (no level
    matched the snapshot) is refused: calling a single unlabelled price "open" would be a guess.
    """
    wanted = {"side": side, "snapshot": snapshot, "method": method}
    node = method_odds
    while isinstance(node, dict) and wanted:
        for role, value in list(wanted.items()):
            if value in node:
                node = node[value]
                del wanted[role]
                break
        else:
            return None
    return node if not wanted and _is_price(node) else None


def _moneyline(row: dict, a_key: str, b_key: str) -> dict:
    out = {}
    for snap in SNAPSHOTS:
        pa, pb = row.get(f"{a_key}_ml_{snap}"), row.get(f"{b_key}_ml_{snap}")
        out[snap] = None if pa is None and pb is None else {"a": pa, "b": pb, **remove_margin({"a": pa, "b": pb})}
    return out


def _rounds_total(row: dict) -> dict:
    out = {"line": row.get("rounds_total")}
    for snap in SNAPSHOTS:
        over, under = row.get(f"over_{snap}"), row.get(f"under_{snap}")
        out[snap] = None if over is None and under is None else {
            "over": over, "under": under, **remove_margin({"over": over, "under": under})}
    return out


def _nest_method(flat: Optional[dict]) -> Optional[dict]:
    """{"a_submission": x, ...} back to {"a": {"submission": x, ...}, "b": {...}}."""
    if flat is None:
        return None
    return {side: {m: flat[f"{side}_{m}"] for m in METHODS} for side in ("a", "b")}


def _method_market(row: dict, a_key: str, b_key: str) -> dict:
    out = {}
    for snap in SNAPSHOTS:
        prices = {side: {m: _method_price(row.get("method_odds"), key, snap, m) for m in METHODS}
                  for side, key in (("a", a_key), ("b", b_key))}
        flat = {f"{side}_{m}": p for side, ms in prices.items() for m, p in ms.items()}
        if all(p is None for p in flat.values()):
            out[snap] = None
            continue
        shown = remove_margin(flat)
        out[snap] = {"a": prices["a"], "b": prices["b"], "implied": _nest_method(shown["implied"]),
                     "margin": shown["margin"], "without_margin": _nest_method(shown["without_margin"])}
    return out


def _primary_row(rows: Sequence[dict]) -> dict:
    """DraftKings (provider id 100, the one ESPN carries) first, then by provider id."""
    return sorted(rows, key=lambda r: (str(r.get("provider_id")) != "100", str(r.get("provider_id"))))[0]


def bout_odds(store, bout: dict, a_id: str, b_id: str, *, detail: str = "full") -> Optional[dict]:
    """The bout's odds with `a_id` as side a and `b_id` as side b, or None when there is no row.

    `detail="current"` is the compact form the API's upcoming list uses: open and current
    moneyline and the current rounds total, without the method market.
    """
    rows = store.odds_for_bout().get(bout["bout_id"])
    if not rows:
        return None
    row = _primary_row(rows)
    block = {
        "provider": row.get("provider"), "provider_id": row.get("provider_id"),
        "fetched_utc": row.get("fetched_utc"), "is_closing": row.get("is_closing"),
        "as_of_safe": False,        # prices as fetched, never prices as of the sheet's as_of
        "orientation": row.get("orientation"),
        "other_providers": [{"provider_id": r.get("provider_id"), "provider": r.get("provider")}
                            for r in rows if r is not row],
    }
    sides = {str(bout.get("fighter_a_id")): "a", str(bout.get("fighter_b_id")): "b"}
    a_key, b_key = sides.get(str(a_id)), sides.get(str(b_id))
    if row.get("orientation") != "verified" or a_key is None or b_key is None or a_key == b_key:
        why = ("orientation is not verified" if row.get("orientation") != "verified"
               else "these are not the bout's two fighters")
        block.update({"moneyline": None, "rounds_total": None, "method": None,
                      "note": f"prices withheld: the odds row's sides could not be matched to these fighters ({why})"})
        return block
    block["moneyline"] = _moneyline(row, a_key, b_key)
    block["rounds_total"] = _rounds_total(row)
    block["method"] = _method_market(row, a_key, b_key)
    if detail == "current":
        block["moneyline"] = {k: block["moneyline"][k] for k in ("open", "current")}
        block["rounds_total"] = {k: block["rounds_total"][k] for k in ("line", "current")}
        block["method"] = None
    return block


# -- the booked bout ---------------------------------------------------------------------

def _event_name(store, bout: dict) -> Optional[str]:
    event = store.event_by_id().get(bout.get("event_id")) or {}
    return event.get("name")


def bout_summary(store, bout: dict) -> dict:
    return {
        "bout_id": bout["bout_id"], "event_id": bout.get("event_id"), "event_name": _event_name(store, bout),
        "date_utc": bout.get("date_utc"), "weight_class": bout.get("weight_class"),
        "scheduled_rounds": bout.get("scheduled_rounds"), "card_segment": bout.get("card_segment"),
        "match_number": bout.get("match_number"), "description": bout.get("description"),
        "status": bout.get("status"),
    }


def scheduled_bout(store, a_id: str, b_id: str, now: datetime) -> Tuple[Optional[dict], List[str]]:
    """The scheduled bout between the two, and the ids of any other scheduled bouts they have.

    Prefers the earliest bout starting at or after `now`, then the latest one before it (a
    bout whose status was never refreshed), then one with no start time.
    """
    pair = {str(a_id), str(b_id)}
    found = [(feat.bout_start(b), b["bout_id"], b) for b in store.bouts_by_fighter().get(str(a_id), ())
             if {str(b.get("fighter_a_id")), str(b.get("fighter_b_id"))} == pair and b.get("status") == "scheduled"]
    if not found:
        return None, []
    future = sorted((t for t in found if t[0] is not None and t[0] >= now), key=lambda t: (t[0], t[1]))
    past = sorted((t for t in found if t[0] is not None and t[0] < now), key=lambda t: (t[0], t[1]))
    undated = [t for t in found if t[0] is None]
    ordered = future + past[::-1] + undated
    return ordered[0][2], [t[1] for t in ordered[1:]]


# -- comparison blocks --------------------------------------------------------------------

def _by_opponent(fights: Sequence[feat.Fight]) -> Dict[str, List[feat.Fight]]:
    out: Dict[str, List[feat.Fight]] = {}
    for f in fights:
        out.setdefault(f.opponent_id, []).append(f)
    return out


def shared_opponents(store, fights_a: Sequence[feat.Fight], fights_b: Sequence[feat.Fight],
                     a_id: str, b_id: str) -> dict:
    """Opponents both fighters beat, lost to, drew with or had a no contest against, before as_of.

    Each side lists its fights against the opponent oldest first (a rematch gives two).
    The counts of each fighter's distinct opponents are included so an empty list can be
    read: no overlap between two real histories is a different statement from a fighter
    with no history at all.
    """
    opp_a, opp_b = _by_opponent(fights_a), _by_opponent(fights_b)
    common = (set(opp_a) & set(opp_b)) - {str(a_id), str(b_id)}
    fighters = store.fighter_by_id()
    items = []
    for oid in sorted(common, key=lambda o: ((fighters.get(o) or {}).get("name") or "", o)):
        items.append({"opponent_id": oid, "opponent_name": (fighters.get(oid) or {}).get("name"),
                      "a": [feat.fight_line(store, f) for f in opp_a[oid]],
                      "b": [feat.fight_line(store, f) for f in opp_b[oid]]})
    return {"a_opponents": len(opp_a), "b_opponents": len(opp_b), "count": len(items), "items": items}


def previous_meetings(store, fights_a: Sequence[feat.Fight], b_id: str) -> List[dict]:
    """Earlier fights between the two (results from a's side), oldest first."""
    fighters = store.fighter_by_id()
    out = []
    for f in fights_a:
        if f.opponent_id != str(b_id):
            continue
        line = feat.fight_line(store, f)
        winner = f.bout.get("winner_id")
        line["winner_id"] = winner
        line["winner_name"] = (fighters.get(winner) or {}).get("name") if winner else None
        out.append(line)
    return out


def _physical(fa: dict, fb: dict) -> dict:
    def side(f):
        figs = f["figures"]
        h, r = figs["height_in"]["value"], figs["reach_in"]["value"]
        return {"height_in": h, "reach_in": r,
                "reach_minus_height_in": None if h is None or r is None else round(r - h, 2),
                "age_years": figs["age_years"]["value"], "stance": f["physical"]["stance"]}

    a, b = side(fa), side(fb)
    diffs = {k: None if a[k] is None or b[k] is None else round(a[k] - b[k], 2)
             for k in ("height_in", "reach_in", "reach_minus_height_in", "age_years")}
    sa, sb = a["stance"], b["stance"]
    return {"a": a, "b": b, "differences": diffs,
            "stance_matchup": f"{sa} vs {sb}" if sa and sb else None,
            "same_stance": (sa.strip().lower() == sb.strip().lower()) if sa and sb else None}


def _layoff(fa: dict, fb: dict, as_of: str) -> dict:
    da, db = fa["figures"]["days_since_last_fight"]["value"], fb["figures"]["days_since_last_fight"]["value"]
    longer = None
    if da is not None and db is not None:
        longer = "a" if da > db else "b" if db > da else "equal"
    return {"measured_to": as_of, "a_days": da, "b_days": db,
            "a_last_fight_utc": fa["record"]["last_fight_utc"], "b_last_fight_utc": fb["record"]["last_fight_utc"],
            "difference_days": None if da is None or db is None else da - db, "longer_layoff": longer}


# -- the public function -------------------------------------------------------------------

def matchup(store, a_id: str, b_id: str, as_of: Any = None, *, now: Optional[datetime] = None) -> dict:
    """The fact sheet for a versus b.

    `as_of` defaults to the start of the scheduled bout between them if there is one,
    otherwise to `now` (default: the current time). Raises ValueError when a and b are the
    same fighter or `as_of` is unreadable, and `features.UnknownFighter` for an unknown id.
    """
    a_id, b_id = str(a_id), str(b_id)
    if a_id == b_id:
        raise ValueError("a and b are the same fighter")
    now = feat.parse_instant(now) if now is not None else datetime.now(timezone.utc)

    bout, others = scheduled_bout(store, a_id, b_id, now)
    start = feat.bout_start(bout) if bout else None
    if as_of is not None:
        cutoff, source = feat.parse_instant(as_of), "argument"
    elif start is not None:
        cutoff, source = start, "scheduled_bout_start"
    else:
        cutoff, source = now, "now"

    fa = feat.features_as_of(store, a_id, cutoff)
    fb = feat.features_as_of(store, b_id, cutoff)
    fights_a = feat.completed_fights(store, a_id, cutoff)
    fights_b = feat.completed_fights(store, b_id, cutoff)

    missing = [{"side": "a", "fighter_id": a_id, **m} for m in fa["missing"]]
    missing += [{"side": "b", "fighter_id": b_id, **m} for m in fb["missing"]]
    odds = None
    if bout is None:
        missing.append({"side": None, "figure": "bout", "reason": "no scheduled bout between these fighters in the store"})
    else:
        odds = bout_odds(store, bout, a_id, b_id)
        if odds is None:
            missing.append({"side": None, "figure": "odds", "reason": "no odds row for the scheduled bout"})
        elif odds.get("note"):
            missing.append({"side": None, "figure": "odds", "reason": odds["note"]})

    bout_block = None
    if bout is not None:
        bout_block = dict(bout_summary(store, bout), other_scheduled_bout_ids=others)

    as_of_text = feat.iso_utc(cutoff)
    return {
        "a": {"fighter_id": a_id, "name": fa["name"]},
        "b": {"fighter_id": b_id, "name": fb["name"]},
        "as_of": as_of_text,
        "as_of_source": source,
        "leakage_rule": feat.LEAKAGE_RULE,
        "note": FACTS_ONLY,
        "bout": bout_block,
        "odds": odds,
        "features": {"a": fa, "b": fb},
        "differentials": differentials(fa, fb),
        "styles": {"a": style_descriptors(fa), "b": style_descriptors(fb)},
        "shared_opponents": shared_opponents(store, fights_a, fights_b, a_id, b_id),
        "previous_meetings": previous_meetings(store, fights_a, b_id),
        "physical": _physical(fa, fb),
        "layoff": _layoff(fa, fb, as_of_text),
        "missing": missing,
    }
