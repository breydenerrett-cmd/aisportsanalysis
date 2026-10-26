"""The owner's own numbers, from the lessons ledger. Real dollars, real results, nothing modelled.

WHAT COUNTS. A lesson counts toward profit, ROI and win rate when it has a profit (``model.derive``: settled, void,
cashed out) and is not disputed. Open lessons and disputed lessons are counted apart and never folded in.
  * profit  = sum of payout - stake over counted lessons (a cash-out's profit is amount - stake);
  * ROI     = profit / stake summed over the same lessons, None with no stake;
  * win rate = won / (won + lost): pushes, voids and cash-outs are not decided by the game, so they are not in it.

CUTS. A single is cut by its one leg; a parlay is cut as its own thing: market "parlay", sport its legs' sport (or
"mixed"), price band and role by the ticket's combined price. Every group carries its own ``n`` so a small group reads as
small; no verdict words here.

EVIDENCE GRADES (owner's performance audit, 2026-10-25, ``model.evidence_grade``). Only grade A (a recommendation published
before the bet was placed, matched exactly) counts toward any "LINEHOUND picks" hit rate or ROI. Three views are kept apart:
(a) every published recommendation, placed or not; (b) executed tickets matched to a recommendation (grade A); (c) other
bettors' tickets (grade C), which are excluded from every total here, the cuts and the learning. B and D (no exact
pre-placement match, or an unknown bettor) are the owner's own numbers but never "LINEHOUND picks". A push counts as neither
a win nor a loss and is in the returned-amount reconciliation (``returned`` = stake + profit for every counted lesson).
A bankroll or balance screenshot is never evidence of anything (extract.py refuses it); profit here is only from tickets.

CLV is the closing-line value of the legs the grader settled where we captured the closing price for that game and
market (``user_settle.make_close_fn``, percentage points of implied probability). A leg with no closing price is left
out, never filled in. EXPOSURE groups lessons that ride on the same game or the same player, with the dollars still open.
"""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence

from src.hounds.apprentice import calc, model

MIN_GROUP = 1


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(text or "").lower()).strip()


def attributes(lesson: Mapping) -> dict:
    legs = lesson["legs"]
    if len(legs) == 1:
        leg = legs[0]
        return {"market": leg["market"], "sport": leg["sport"], "band": calc.price_band(leg["price"]),
                "role": calc.role_of(leg["price"])}
    sports = {leg["sport"] for leg in legs}
    return {"market": "parlay", "sport": sports.pop() if len(sports) == 1 else "mixed",
            "band": calc.price_band(lesson["total_price"]), "role": calc.role_of(lesson["total_price"])}


def _group(rows: Sequence[Mapping]) -> dict:
    counted = [r for r in rows if r["view"]["counts"]]
    staked = sum(r["lesson"]["stake"] for r in counted)
    profit = sum(r["view"]["profit"] for r in counted)
    won = sum(1 for r in counted if r["view"]["result"] == "won")
    lost = sum(1 for r in counted if r["view"]["result"] == "lost")
    returned = sum(r["view"]["payout"] for r in counted)
    pushes = sum(1 for r in counted if r["view"]["result"] == "push")
    return {"n": len(rows), "counted": len(counted), "staked": calc.money(staked), "profit": calc.money(profit),
            "returned": calc.money(returned), "pushes": pushes, "reconciles": abs(staked + profit - returned) < 0.005,
            "roi": None if staked <= 0 else round(profit / staked, 4), "wins": won, "losses": lost,
            "win_rate": None if won + lost == 0 else round(won / (won + lost), 4)}


def _clv(rows: Sequence[Mapping]) -> dict:
    values = []
    for r in rows:
        for v in (r["view"].get("leg_clv") or []):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values.append(float(v))
    if not values:
        return {"legs": 0, "mean_pts": None, "positive": None}
    return {"legs": len(values), "mean_pts": round(sum(values) / len(values), 3),
            "positive": round(sum(1 for v in values if v > 0) / len(values), 4)}


def exposure(rows: Sequence[Mapping]) -> dict:
    """Lessons on the same game or the same player. Only groups of two or more are returned (one is not a correlation)."""
    games: dict = {}
    players: dict = {}
    for r in rows:
        lesson, view = r["lesson"], r["view"]
        is_open = view["state"] in (model.PENDING, model.LIVE)
        seen_games, seen_players = set(), set()
        for leg in lesson["legs"]:
            gk = leg.get("event_id") or _norm(leg.get("game"))
            if gk and gk not in seen_games:
                seen_games.add(gk)
                games.setdefault(gk, {"key": gk, "label": leg.get("game") or gk, "lessons": [], "open_staked": 0.0, "staked": 0.0})
            if leg.get("player"):
                pk = _norm(leg["player"])
                if pk and pk not in seen_players:
                    seen_players.add(pk)
                    players.setdefault(pk, {"key": pk, "label": leg["player"], "lessons": [], "open_staked": 0.0, "staked": 0.0})
        for table, keys in ((games, seen_games), (players, seen_players)):
            for k in keys:
                g = table[k]
                g["lessons"].append(lesson["id"])
                g["staked"] += lesson["stake"]
                if is_open:
                    g["open_staked"] += lesson["stake"]

    def clean(table):
        out = []
        for g in table.values():
            if len(g["lessons"]) >= 2:
                out.append({**g, "staked": calc.money(g["staked"]), "open_staked": calc.money(g["open_staked"])})
        return sorted(out, key=lambda g: (-g["open_staked"], -len(g["lessons"]), g["key"]))
    return {"games": clean(games), "players": clean(players)}


def build_rows(pairs: Sequence[tuple], recs: Optional[Mapping] = None) -> list:
    """[(lesson, events)] -> [{"lesson", "view", "attrs", "grade"}], with the grader's leg CLV carried onto the view.
    ``recs`` is {recommendation id: recommendation}; a lesson linking an id that is not in it is graded as unlinked."""
    rows = []
    for lesson, events in pairs:
        view = model.derive(lesson, events)
        grade, why = model.evidence_grade(lesson, (recs or {}).get(lesson.get("recommendation_id")))
        view["grade"], view["grade_reason"] = grade, why
        grader = [e for e in events if e["source"] == "grader" and e["state"] in model.TERMINAL]
        view["leg_clv"] = (grader[-1]["data"].get("leg_clv") if grader else None)
        rows.append({"lesson": lesson, "view": view, "attrs": attributes(lesson), "grade": grade})
    return rows


def own_rows(rows: Sequence[Mapping]) -> list:
    """The owner's own bets: everything except another bettor's tickets (grade C)."""
    return [r for r in rows if r["grade"] != "C"]


def views(rows: Sequence[Mapping], recs: Sequence[Mapping]) -> dict:
    """The audit's three views, kept apart. (a) all published recommendations (a recommendation nobody placed is listed);
    (b) executed tickets matched to a recommendation, the ONLY numbers that are "LINEHOUND picks"; (c) other bettors'
    tickets, listed and excluded."""
    graded_a = [r for r in rows if r["grade"] == "A"]
    linked: dict = {}
    for r in rows:
        if r["lesson"].get("recommendation_id"):
            linked.setdefault(r["lesson"]["recommendation_id"], []).append(r)
    a_view = []
    for rec in recs:
        mine = linked.get(rec["id"], [])
        a_rows = [r for r in mine if r["grade"] == "A"]
        a_view.append({"id": rec["id"], "source": rec["source"], "recommended_utc": rec["recommended_utc"], "legs": rec["legs"],
                       "placed": bool(mine), "matched_tickets": [r["lesson"]["id"] for r in a_rows],
                       "result": a_rows[0]["view"]["result"] if a_rows and a_rows[0]["view"]["counts"] else None})
    return {"a_recommendations": {"published": len(recs), "placed": sum(1 for x in a_view if x["placed"]),
                                  "unplaced": sum(1 for x in a_view if not x["placed"]), "items": a_view},
            "b_executed": {**_group(graded_a), "lesson_ids": [r["lesson"]["id"] for r in graded_a],
                           "label": "LINEHOUND picks: tickets placed after a published recommendation and matching it exactly"},
            "c_other_bettors": {"excluded": True, "n": sum(1 for r in rows if r["grade"] == "C"),
                                "items": [{"id": r["lesson"]["id"], "owner": r["lesson"].get("bettor"), "stake": r["lesson"]["stake"],
                                           "state": r["view"]["state"], "result": r["view"]["result"]}
                                          for r in rows if r["grade"] == "C"]},
            "unmatched": {"b": sum(1 for r in rows if r["grade"] == "B"), "d": sum(1 for r in rows if r["grade"] == "D")}}


def summarize(pairs: Sequence[tuple], recs: Sequence[Mapping] = ()) -> dict:
    every = build_rows(pairs, {r["id"]: r for r in recs})
    rows = own_rows(every)
    out = {"overall": _group(rows), "cuts": {}, "clv": _clv(rows), "exposure": exposure(rows),
           "open": sum(1 for r in rows if r["view"]["state"] in (model.PENDING, model.LIVE)),
           "disputed": sum(1 for r in rows if r["view"]["disputed"]),
           "cashed_out": sum(1 for r in rows if r["view"]["state"] == model.CASHED_OUT),
           "lessons": len(rows), "views": views(every, recs),
           "note": "Totals are the owner's own bets. Another bettor's tickets are excluded; only a ticket placed after a published "
                   "recommendation and matching it exactly counts as a LINEHOUND pick."}
    for dim in ("market", "sport", "band", "role"):
        keys = sorted({r["attrs"][dim] for r in rows})
        out["cuts"][dim] = [{"key": k, **_group([r for r in rows if r["attrs"][dim] == k])} for k in keys]
    return out
