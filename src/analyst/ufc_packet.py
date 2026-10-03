"""The UFC fight packet: everything the analyst may know about one bout, frozen.

THE SAME CONTRACT AS THE MLB PACKET, A DIFFERENT SPORT
------------------------------------------------------
`src/analyst/packet.py` explains why a packet exists (self-contained, frozen and
hashable, honest about holes) and the path grammar the critic checks claims
against. None of that changes here, and the shapes the critic and the ledger
read are the same on purpose: `markets` keyed by slot id, each market with its
`options` (lean first) and each option with `quotes` of `{book, price,
captured_utc}`; `slots`; `missing`; `limits`. The helpers that build an option,
a quote and a market are the MLB packet's own (`packet._option` and friends), so
there is exactly one definition of "the lean" and "the best quote".

WHAT COMES FROM WHERE
---------------------
The fighters, their rates, the style labels, the shared opponents, the previous
meetings, the physical comparison and the layoff all come from
`src.datasvc.ufc.matchup.matchup(store, a, b, as_of=<the bout's start>)`: the
data layer's own fact sheet, which already admits only bouts that started
strictly before that instant. The odds come from `matchup.bout_odds`, which maps
every price to its fighter by identity and refuses a row whose orientation is
not verified. This module adds no statistic of its own.

NO LEAKAGE, FOUR WAYS
---------------------
1. Features are as of the bout's SCHEDULED START. A result, the bout's own or a
   later one, is invisible to them: that is the data layer's rule, tested there.
2. The bout block is a whitelist (identity, event, start, state, weight class,
   rounds, segment, the two fighters). The winner, the method, the round and the
   time a finished bout carries never enter it.
3. A price enters only when its row was fetched before this packet was built AND
   strictly before the bout's scheduled start. The data layer keeps ONE odds row
   per provider per bout and overwrites it on every fetch, so a row fetched after
   the start (a closing line written once the fight was over) is dropped whole and
   `missing` says why. A row that cannot be dated is dropped too: a price that
   cannot be shown to precede the fight is not shown.
4. The live in-play provider ("ESPN Bet - Live Odds") is never used, whatever it
   quotes. `matchup` already skips it; the tests prove nothing of it survives.

Two blocks of the sheet are NOT as-of-date (the overall professional record and
the UFC.com career figures; the data layer labels both `as_of_safe: false`).
They are included only when their own fetch time is before the bout's start, so
neither can contain its result, and they are labelled as what they are.

THE SLOTS
---------
`moneyline`: two options (each fighter), the favourite first.
`rounds_total`: Over and Under the line, the likelier side first.
`method_<side>_<ko|sub|dec>`: ONE option each, a fighter to win by one method.
There is no "other side" of a method price (the six method outcomes are not a
two-way market), so those slots can be a TAKE or a PASS and never a
TAKE_OTHER_SIDE, exactly like the MLB one-sided home-run prop.

A slot exists only when every price it needs is quoted: both sides of the
moneyline, the line and both prices of the rounds total, the one price of a
method outcome. Nothing is inferred and nothing is filled in.

READING IT
----------
`how_to_read` is four sentences inside the packet: which fighter is `a`, that a
difference is a minus b, that a meeting is written from a's side, what a probability
without a margin is. The prompt cannot say these (they are about this packet's shape and
the packet is archived with every call), and a model that guesses which way a difference
points makes a confident claim the critic cannot catch, because the number it quotes is
real.

FIGHTER NAMES
-------------
A fighter with no name in the store is labelled "Fighter A" or "Fighter B" and
`bout.fighter_x.name_known` is false, with a `missing` entry. The packet never
invents a name; the CLI refuses to publish a bout whose fighters it cannot name.

Pure: no I/O of its own (it reads the store it is handed), no clock, no network,
no api/ import.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping, Optional

from src.analyst import packet as base
from src.datasvc.ufc import features as feat
from src.datasvc.ufc import matchup as mu
from src.situation import record as situation_record

PACKET_VERSION = "analyst_ufc_packet_v1"
# Arm B of the side-by-side test: the same packet with a `situation` section.
PACKET_VERSION_SITUATION = "analyst_ufc_packet_v1_situation"

# The data layer's own minimum for a rate to mean anything (matchup.MIN_FIGHTS_TIMED).
# A fighter with fewer fights in the store than this is called thin in `missing`.
THIN_FIGHTS = mu.MIN_FIGHTS_TIMED

# A UFC round is five minutes, in every bout. A fact of the sport, labelled as one,
# so a reader (and the critic's number check) can use "five-minute rounds".
ROUND_MINUTES = 5

METHODS = mu.METHODS                                         # ko_tko_dq, submission, decision
METHOD_SLUG = {"ko_tko_dq": "ko", "submission": "sub", "decision": "dec"}
METHOD_WORDS = {"ko_tko_dq": "KO/TKO/DQ", "submission": "submission", "decision": "decision"}
SIDES = ("a", "b")

FIGHTER_BASIS = "UFC bouts in the data store that started before this bout and have a result"
MATCHUP_BASIS = "the same bouts, both fighters compared"
CAREER_BASIS = ("as fetched, before this bout started; not limited to the data store's window, "
                "so it counts fights the store does not hold")

# Identifier keys dropped from the fighter sections: the model cannot use them and
# they only cost tokens. The bout block keeps the ones the ledger needs.
_DROP_KEYS = frozenset({"fighter_id", "opponent_id", "bout_id", "winner_id", "source_url"})


class UfcPacketError(ValueError):
    """The packet cannot be built for this bout (no such bout, no two fighters)."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def method_slot_id(side: str, method: str) -> str:
    return f"method_{side}_{METHOD_SLUG[method]}"


def _instant(value: Any) -> Optional[datetime]:
    """A stored date string as an aware UTC datetime, or None. Reads ESPN's own
    spelling ("2026-10-11T00:00Z") as well as the usual ISO forms."""
    return feat.instant(value) if isinstance(value, str) else None


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return base._iso(moment)


def _scrub(node: Any) -> Any:
    """A copy with identifier keys dropped and every key made path-safe."""
    if isinstance(node, Mapping):
        return {base._clean_key(k): _scrub(v)
                for k, v in sorted(node.items(), key=lambda kv: str(kv[0]))
                if str(k) not in _DROP_KEYS}
    if isinstance(node, (list, tuple)):
        return [_scrub(v) for v in node]
    if isinstance(node, float) and not math.isfinite(node):
        return None
    return node


def _line(f: Mapping) -> dict:
    """One past fight as a short factual line, without the identifiers."""
    return {k: f.get(k) for k in ("date_utc", "opponent_name", "result", "method", "detail",
                                  "round", "time_s", "weight_class")}


def _label(name: Optional[str], side: str) -> str:
    return name if isinstance(name, str) and name.strip() else f"Fighter {side.upper()}"


# ---------------------------------------------------------------------------
# the fighter sections
# ---------------------------------------------------------------------------

def _figure(fig: Mapping) -> dict:
    out = {"value": fig.get("value")}
    for key in ("fights", "minutes", "num", "den", "opponents_without_history"):
        if key in fig:
            out[key] = fig[key]
    if fig.get("value") is None and fig.get("reason"):
        out["reason"] = fig["reason"]
    return out


def _fighter_values(features: Mapping) -> dict:
    """One fighter's numbers, compacted: no units (they are listed once in
    `figure_units`), no identifiers, no per-fight schedule detail."""
    sample = features["sample"]
    skipped = sample.get("skipped") or {}
    wc = features["weight_classes"]
    change = wc.get("most_recent_change")
    return {
        "record": features["record"],
        "streak": features["streak"],
        "sample": {
            "fights": sample["fights"], "minutes": sample["minutes"],
            "fights_with_own_stats": sample["fights_with_own_stats"],
            "fights_with_opponent_stats": sample["fights_with_opponent_stats"],
            "fights_with_both_stats": sample["fights_with_both_stats"],
            "fights_without_any_stats": len(sample.get("fights_without_any_stats") or []),
            "started_before_without_a_result": len(skipped.get("started_without_result") or []),
        },
        "figures": {name: _figure(fig) for name, fig in features["figures"].items()},
        "last_three": [_line(x) for x in features["last_three"]],
        "weight_classes": {
            "current": wc.get("current"),
            "most_recent_change": None if not change else {
                k: change.get(k) for k in ("from", "to", "date_utc", "direction")},
            "fought": wc.get("fought") or [],
        },
        "stance": (features.get("physical") or {}).get("stance"),
    }


def _styles(side: Mapping) -> dict:
    return {
        "applies": [{k: s.get(k) for k in ("name", "summary", "evidence", "sample")}
                    for s in side.get("applies") or []],
        "does_not_apply": list(side.get("does_not_apply") or []),
        "not_assessed": [n.get("name") for n in side.get("not_assessed") or []],
    }


def _matchup_values(sheet: Mapping) -> dict:
    diffs = {}
    for name, d in sheet["differentials"].items():
        entry = {"a": d["a"], "b": d["b"], "diff": d["diff"]}
        if "thin_sample" in d:
            entry["thin_sample"] = d["thin_sample"]
        diffs[name] = entry
    shared = sheet["shared_opponents"]
    return {
        "differentials": diffs,
        "styles": {"a": _styles(sheet["styles"]["a"]), "b": _styles(sheet["styles"]["b"])},
        "shared_opponents": {
            "a_opponents": shared["a_opponents"], "b_opponents": shared["b_opponents"],
            "count": shared["count"],
            "items": [{"opponent_name": i.get("opponent_name"),
                       "a": [_line(x) for x in i["a"]], "b": [_line(x) for x in i["b"]]}
                      for i in shared["items"]],
        },
        "previous_meetings": [dict(_line(m), winner_name=m.get("winner_name"))
                              for m in sheet["previous_meetings"]],
        "physical": sheet["physical"],
        "layoff": sheet["layoff"],
    }


def _career(features: Mapping, side: str, start: Optional[datetime],
            cutoff: datetime) -> tuple:
    """`(values or None, as_of, missing)`: the two blocks that are not as-of-date,
    each kept only when its own fetch time precedes the bout (and this packet)."""
    values, stamps, missing = {}, [], []
    for key, label, name in (("career_record_incl_non_ufc", "overall_record", "overall record"),
                             ("ufccom_career", "ufccom_career", "UFC.com career figures")):
        block = features.get(key)
        if not block:
            continue                      # absence is already in the sheet's own missing list
        fetched = _instant(block.get("fetched_utc"))
        why = None
        if fetched is None:
            why = f"the {name} has no readable fetch time, so it cannot be shown to precede the bout"
        elif start is not None and fetched >= start:
            why = f"the {name} was fetched at or after the bout's scheduled start and could include its result"
        elif fetched > cutoff:
            why = f"the {name} was fetched after this packet was built"
        if why:
            missing.append({"item": f"fighter_{side}.{label}", "kind": "absent", "reason": why})
            continue
        if key == "career_record_incl_non_ufc":
            values[label] = {k: block.get(k) for k in ("label", "includes_non_ufc", "wins", "losses",
                                                       "draws", "no_contests", "fetched_utc")}
        else:
            values[label] = {"label": block.get("label"), "ufc_slug": block.get("ufc_slug"),
                             "fetched_utc": block.get("fetched_utc"),
                             "figures": block.get("figures") or {}}
        stamps.append(_iso(fetched))
    return (values or None), (max(stamps) if stamps else None), missing


def _fighter_missing(sheet: Mapping) -> list:
    """The sheet's own side-tagged gaps as packet `missing` entries. The sheet's
    bout-level entries ("no scheduled bout", "no odds row") are not copied: this
    module states its own, from what it can prove."""
    out = []
    for m in sheet["missing"]:
        side = m.get("side")
        if side in SIDES:
            out.append({"item": f"fighter_{side}.{m.get('figure')}", "kind": "absent",
                        "reason": str(m.get("reason") or "not computed")})
    return out


def _sample_missing(features: Mapping, side: str) -> list:
    out = []
    s = features["sample"]
    n = s["fights"]
    item = f"fighter_{side}"
    if n == 0:
        out.append({"item": item, "kind": "absent",
                    "reason": "no UFC fights in the data store before this bout"})
        return out
    if n < THIN_FIGHTS:
        out.append({"item": item, "kind": "thin",
                    "reason": f"only {n} UFC fight(s) in the data store before this bout; rates and "
                              "style labels rest on a small sample"})
    if s["fights_with_own_stats"] == 0:
        out.append({"item": f"{item}.statistics", "kind": "absent",
                    "reason": f"none of the {n} fight(s) has fight statistics in the store"})
    elif s["fights_with_own_stats"] < n:
        out.append({"item": f"{item}.statistics", "kind": "thin",
                    "reason": f"{s['fights_with_own_stats']} of {n} fights have fight statistics in "
                              "the store; each figure says how many fights it rests on"})
    skipped = (s.get("skipped") or {}).get("started_without_result") or []
    if skipped:
        statuses = sorted({str(x.get("status")) for x in skipped})
        out.append({"item": f"{item}.earlier_bouts", "kind": "thin",
                    "reason": f"{len(skipped)} earlier bout(s) started before this one with no recorded "
                              f"result (status: {', '.join(statuses)}) and are not counted"})
    return out


# ---------------------------------------------------------------------------
# the odds
# ---------------------------------------------------------------------------

def _usable_odds(store, bout: Mapping, a_id: str, b_id: str, cutoff: datetime,
                 start: Optional[datetime]) -> tuple:
    """`(odds block, raw row, fetched, why_not)`. `why_not` is None only when the
    prices are provably pre-fight and attributable to the right fighters."""
    rows = store.odds_for_bout().get(str(bout["bout_id"])) or []
    if not rows:
        return None, None, None, "no odds row for this bout in the store"
    odds = mu.bout_odds(store, bout, a_id, b_id)
    if odds is None:
        return None, None, None, "no odds row for this bout in the store"
    if odds.get("provider") is None or odds.get("note"):
        return None, None, None, str(odds.get("note") or "no pre-fight prices for this bout")
    fetched = _instant(odds.get("fetched_utc"))
    if fetched is None:
        return None, None, None, ("the odds row has no readable capture time, so it cannot be shown "
                                  "to precede the bout")
    if odds.get("is_closing"):
        return None, None, fetched, (f"the odds row was fetched at {_iso(fetched)}, after the bout "
                                     "was over (it holds the closing line, not a pre-fight price)")
    if fetched > cutoff:
        return None, None, fetched, (f"the odds row was fetched at {_iso(fetched)}, after this packet "
                                     "was built")
    if start is not None and fetched >= start:
        return None, None, fetched, (f"the odds row was fetched at {_iso(fetched)}, at or after the "
                                     f"bout's scheduled start {_iso(start)}, so it is not a pre-fight price")
    raw = next((r for r in rows if str(r.get("provider_id")) == str(odds.get("provider_id"))
                and not r.get("in_play")), None)
    if raw is None:
        return None, None, fetched, "the odds row could not be matched to its provider"
    return odds, raw, fetched, None


def _quoted_option(selection: str, side: str, line: Optional[float], price: int, book: str,
                   seen: datetime, fair: Optional[float], implied: Optional[float],
                   open_price: Optional[int], open_line: Optional[float] = None) -> dict:
    opt = base._option(selection, side, line, [base._quote(book, price, seen)], fair)
    opt["implied_probability"] = None if implied is None else round(implied, 4)
    opt["open_price"] = open_price
    if open_line is not None:
        opt["open_line"] = open_line
    return opt


def _pair(block: Optional[Mapping], key: str, first: str, second: str) -> tuple:
    """(first value, second value) of one of a probability block's two-way
    sub-dicts, each None when the block or the entry is absent."""
    sub = (block or {}).get(key) or {}
    return sub.get(first), sub.get(second)


def _moneyline(odds, names, book, seen) -> Optional[dict]:
    ml = odds.get("moneyline") or {}
    cur, opening = ml.get("current"), ml.get("open")
    if not cur:
        return None
    pa, pb = base._price(cur.get("a")), base._price(cur.get("b"))
    if pa is None or pb is None:
        return None
    fair_a, fair_b = _pair(cur, "without_margin", "a", "b")
    imp_a, imp_b = _pair(cur, "implied", "a", "b")
    oa = base._price((opening or {}).get("a"))
    ob = base._price((opening or {}).get("b"))
    opt_a = _quoted_option(names["a"], "a", None, pa, book, seen, fair_a, imp_a, oa)
    opt_b = _quoted_option(names["b"], "b", None, pb, book, seen, fair_b, imp_b, ob)
    return base._market("moneyline", "moneyline", f"{names['a']} vs {names['b']} moneyline",
                        base._ordered(opt_a, opt_b))


def _rounds_total(odds, row, names, book, seen) -> Optional[dict]:
    rt = odds.get("rounds_total") or {}
    cur, opening = rt.get("current"), rt.get("open")
    if not cur:
        return None
    over, under = base._price(cur.get("over")), base._price(cur.get("under"))
    if over is None or under is None:
        return None
    # The line the CURRENT prices are posted at. The odds row keeps one line per phase
    # (`rounds_total_open|current`) and the open prices are priced at the open line, so
    # a line is read per phase and never borrowed from another. A row from before the
    # per-phase fields existed has only `rounds_total`.
    raw_line = row["rounds_total_current"] if "rounds_total_current" in row else row.get("rounds_total")
    line = base._clean_line(raw_line)
    if line is None or line <= 0:
        return None
    open_line = base._clean_line(row.get("rounds_total_open")) if "rounds_total_open" in row else None
    fair_o, fair_u = _pair(cur, "without_margin", "over", "under")
    imp_o, imp_u = _pair(cur, "implied", "over", "under")
    oo = base._price((opening or {}).get("over"))
    ou = base._price((opening or {}).get("under"))
    o = _quoted_option(f"Over {line:g}", "over", line, over, book, seen, fair_o, imp_o, oo, open_line)
    u = _quoted_option(f"Under {line:g}", "under", line, under, book, seen, fair_u, imp_u, ou, open_line)
    return base._market("rounds_total", "rounds_total",
                        f"{names['a']} vs {names['b']} total rounds", base._ordered(o, u))


def _methods(odds, names, book, seen) -> tuple:
    """`({slot_id: market}, quoted, margin_free)`: the method-of-victory slots."""
    block = odds.get("method") or {}
    cur, opening = block.get("current"), block.get("open")
    if not cur:
        return {}, 0, False
    fair, implied = cur.get("without_margin"), cur.get("implied")
    out, quoted = {}, 0
    for side in SIDES:
        for method in METHODS:
            price = base._price((cur.get(side) or {}).get(method))
            if price is None:
                continue
            quoted += 1
            f = ((fair or {}).get(side) or {}).get(method)
            i = ((implied or {}).get(side) or {}).get(method)
            op = base._price(((opening or {}).get(side) or {}).get(method))
            slot = method_slot_id(side, method)
            word = METHOD_WORDS[method]
            opt = _quoted_option(f"{names[side]} by {word}", side, None, price, book, seen, f, i, op)
            out[slot] = base._market(slot, "method", f"{names[side]} to win by {word}", [opt],
                                     {"fighter_side": side, "method": method})
    return out, quoted, fair is not None


# ---------------------------------------------------------------------------
# the packet
# ---------------------------------------------------------------------------

def _units(a: Mapping, b: Mapping) -> dict:
    out = {}
    for features in (a, b):
        for name, fig in features["figures"].items():
            if fig.get("unit"):
                out.setdefault(name, fig["unit"])
    return dict(sorted(out.items()))


def _store_start(store) -> Optional[str]:
    days = [m.date().isoformat() for m in (_instant(b.get("date_utc")) for b in store.bouts) if m]
    return min(days) if days else None


HOW_TO_READ = (
    "In sections.matchup.values, a is bout.fighter_a and b is bout.fighter_b. A difference is a minus b, "
    "so a positive one means fighter a has the larger number. previous_meetings are written from fighter "
    "a's side.",
    "A figure's fights and minutes are the sample behind it. A style label under applies carries the "
    "numbers it rests on; one under not_assessed was not judged because the sample was too small.",
    "fair_probability is the market's probability with the bookmaker's margin divided out (for a method "
    "price, only when all six are quoted). implied_probability keeps the margin. open_price is where the "
    "price opened and open_line where a total opened.",
    "figure_units says what each figure measures.",
)


def _limits(store_start: Optional[str]) -> list:
    since = f" (it begins {store_start})" if store_start else ""
    return [
        "Only the moneyline, the method of victory prices (each fighter by KO/TKO/DQ, by submission and "
        "by decision) and the rounds total are analyzed. Round betting, the spread and every other market "
        "are not.",
        "Every price is the current quote of one provider, with its capture time, taken before this packet "
        "was built and before the bout's scheduled start. The opening price is shown beside it.",
        "The scheduled start is the start of the bout's card segment, not the minute the bout begins.",
        "Fight counts and rates cover only the UFC fights in the data store" + since + ", not each fighter's "
        "whole career. A rate is a sum over the fights that had the statistic, and each figure says how many "
        "fights that was.",
        "Injuries, weight cuts, camp news, short-notice replacements, rankings and officials are not in the "
        "packet.",
        f"A UFC round is {ROUND_MINUTES} minutes.",
    ]


def build_packet(store, bout_id: str, *, built_at: str, cfg: Optional[Mapping] = None,
                 situation: Optional[Mapping] = None) -> dict:
    """One bout's frozen fact packet. Deterministic in the store's contents and
    its arguments: no clock, no network, no write.

    `situation` (a `src.situation.ufc.situation_for_bout` record) adds `sections.situation` and
    changes `packet_version`: arm B of the side-by-side test. Left None, the packet is exactly the
    one arm A has always had.

    `store` is a `src.datasvc.ufc.store.UfcStore`. `built_at` is the ISO UTC
    moment the packet is built (the caller's clock). Raises `UfcPacketError` for a
    bout that is not in the store or lacks two fighters, and `ValueError` for a
    `built_at` that is not a time.
    """
    from src.analyst import config as config_mod

    cfg = dict(cfg) if cfg is not None else config_mod.DEFAULTS
    try:
        cutoff = feat.parse_instant(built_at)
    except ValueError as exc:
        raise ValueError(f"built_at must be an ISO UTC time, got {built_at!r}") from exc
    bout = store.bout_by_id().get(str(bout_id))
    if bout is None:
        raise UfcPacketError(f"no bout {bout_id!r} in the store")
    a_id, b_id = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    if not a_id or not b_id or str(a_id) == str(b_id):
        raise UfcPacketError(f"bout {bout_id!r} does not name two different fighters")
    a_id, b_id = str(a_id), str(b_id)

    start = feat.bout_start(bout)
    as_of = start if start is not None else cutoff
    # `now=cutoff` keeps the sheet deterministic: it is read only to pick among several
    # scheduled bouts between the same pair, which this module does not use (it knows its bout).
    sheet = mu.matchup(store, a_id, b_id, as_of=as_of, now=cutoff)
    fa, fb = sheet["features"]["a"], sheet["features"]["b"]
    names = {"a": _label(fa.get("name"), "a"), "b": _label(fb.get("name"), "b")}
    named = {"a": bool(fa.get("name")), "b": bool(fb.get("name"))}

    missing: list = []
    for side in SIDES:
        if not named[side]:
            missing.append({"item": f"fighter_{side}.name", "kind": "absent",
                            "reason": f"no name is stored for this fighter yet; shown as {names[side]}"})
    if start is None:
        missing.append({"item": "bout.start", "kind": "absent",
                        "reason": "the bout has no readable scheduled start, so nothing can be shown to "
                                  "precede it and it cannot be published"})
    missing += _fighter_missing(sheet)
    missing += _sample_missing(fa, "a") + _sample_missing(fb, "b")

    event = store.event_by_id().get(bout.get("event_id")) or {}
    event_moment = _instant(event.get("date_utc")) or start
    bout_block = {
        "bout_id": str(bout["bout_id"]),
        "event_id": None if bout.get("event_id") is None else str(bout["event_id"]),
        "event_name": event.get("name"),
        "date": event_moment.date().isoformat() if event_moment else None,
        "start_utc": _iso(start),
        "state": bout.get("status"),
        "weight_class": bout.get("weight_class"),
        "scheduled_rounds": bout.get("scheduled_rounds"),
        "round_minutes": ROUND_MINUTES,
        "card_segment": bout.get("card_segment"),
        "match_number": bout.get("match_number"),
        "fighter_a": {"id": a_id, "name": names["a"], "name_known": named["a"]},
        "fighter_b": {"id": b_id, "name": names["b"], "name_known": named["b"]},
    }
    if isinstance(bout.get("title_bout"), bool):
        bout_block["title_bout"] = bout["title_bout"]
    if not event.get("name"):
        missing.append({"item": "bout.event", "kind": "absent",
                        "reason": "no event record for this bout in the store"})

    # --- the markets -----------------------------------------------------------
    markets: dict = {}
    odds, row, fetched, why = _usable_odds(store, bout, a_id, b_id, cutoff, start)
    if odds is None:
        missing.append({"item": "odds", "kind": "absent", "reason": why})
    else:
        book = str(odds.get("provider") or f"provider {odds.get('provider_id')}")
        for built in (_moneyline(odds, names, book, fetched),
                      _rounds_total(odds, row, names, book, fetched)):
            if built:
                markets[built["slot_id"]] = built
        for slot_id, label in (("moneyline", "moneyline"), ("rounds_total", "rounds total")):
            if slot_id not in markets:
                missing.append({"item": slot_id, "kind": "absent",
                                "reason": f"no current {label} price (both sides, and the line for a "
                                          "total) is quoted for this bout"})
        method_markets, quoted, margin_free = _methods(odds, names, book, fetched)
        markets.update(method_markets)
        if not quoted:
            missing.append({"item": "method", "kind": "absent",
                            "reason": "no current method of victory prices are quoted for this bout"})
        elif quoted < len(SIDES) * len(METHODS):
            missing.append({"item": "method", "kind": "thin",
                            "reason": f"only {quoted} of 6 method of victory prices are quoted, so their "
                                      "margin-free probabilities cannot be computed"})
        elif not margin_free:
            missing.append({"item": "method", "kind": "thin",
                            "reason": "the method prices have no margin-free probabilities"})
        stale = float(cfg.get("stale_quote_minutes", 180))
        age = (cutoff - fetched).total_seconds() / 60.0
        if age > stale:
            for slot_id, market in markets.items():
                missing.append({"item": slot_id, "kind": "stale",
                                "reason": f"the newest {market['label']} quote is {int(age)} minutes old"})

    ordered = ["moneyline", "rounds_total"] + [method_slot_id(s, m) for s in SIDES for m in METHODS]
    markets = {k: markets[k] for k in ordered if k in markets}

    # --- the sections ----------------------------------------------------------
    as_of_text = _iso(as_of)
    sections = {
        "fighter_a": {"as_of": as_of_text, "as_of_basis": FIGHTER_BASIS, "values": _fighter_values(fa)},
        "fighter_b": {"as_of": as_of_text, "as_of_basis": FIGHTER_BASIS, "values": _fighter_values(fb)},
        "matchup": {"as_of": as_of_text, "as_of_basis": MATCHUP_BASIS, "values": _matchup_values(sheet)},
    }
    for side, feats in (("a", fa), ("b", fb)):
        values, stamp, gaps = _career(feats, side, start, cutoff)
        missing += gaps
        if values:
            sections[f"career_{side}"] = {"as_of": stamp, "as_of_basis": CAREER_BASIS, "values": values}
    if situation is not None:
        sections["situation"] = situation_record.packet_section(situation)
    sections = _scrub(sections)

    missing = sorted({(m["item"], m["kind"], m["reason"]): m for m in missing}.values(),
                     key=lambda m: (m["item"], m["kind"], m["reason"]))
    return {
        "packet_version": PACKET_VERSION if situation is None else PACKET_VERSION_SITUATION,
        "built_at": _iso(cutoff),
        "bout": bout_block,
        "figure_units": _units(fa, fb),
        "sections": sections,
        "markets": markets,
        "slots": [{"slot_id": sid, "market": m["market"], "label": m["label"],
                   "selections": [o["selection"] for o in m["options"]]}
                  for sid, m in markets.items()],
        "missing": missing,
        "limits": _limits(_store_start(store)),
        "how_to_read": list(HOW_TO_READ),
    }


# ---------------------------------------------------------------------------
# lookups the critic, the grader and the ledger share (the MLB packet's own)
# ---------------------------------------------------------------------------

resolve_path = base.resolve_path
packet_hash = base.packet_hash
slot = base.slot
option = base.option
has_quote = base.has_quote
