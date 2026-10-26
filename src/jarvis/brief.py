"""Build, explain, file and render one Jarvis briefing.

THE PIPELINE (all of it stops at ``as_of``)
-------------------------------------------
  boards      ``board.read_game_rows`` / ``read_prop_rows`` -> the board at ``as_of`` and the open board
  evaluate    every selection: price ban, book count, probability, expected value, lineup rule -> eligible or a reason
  rank        confidence tier first, then expected value (no invented blend of the two)
  singles     ``one_side.keep_first`` (one side per game), then at most ``MAX_PER_MARKET`` of one market, top five
  parlays     best two-leg pairs from DIFFERENT games, never sharing a leg, at most two
  vanished    what cleared the bar on the open board and does not now
  file        every published pick -> ``apprentice.store.add_recommendation`` (source "jarvis")

WHERE THE PROBABILITY COMES FROM, AND WHY IT IS ALWAYS "EXPERIMENTAL"
---------------------------------------------------------------------
  model       a stored model output for the game (``context.model_for_game``): only the moneyline has one
  consensus   otherwise the leave-one-out no-vig consensus of the other books (``board.selections``)
A consensus pick's "edge" is a PRICE GAP: one book pays more than the rest of the market thinks fair. It carries
no information the market does not have (the repo's own diagnosis: no information edge, the vig is the loss), so
it is shown as that and never as skill. ``CALIBRATED_SOURCES`` is empty on purpose: no forward source has passed a
calibration check, so every probability is labelled EXPERIMENTAL. A source added to the set drops the label.

CONFIDENCE is about the PRICE INFORMATION (how many books, how tight they agree, how fresh, whether the lineup
and starters are confirmed, whether a stored model agrees with the market). It is never a chance of winning.

NO PROFIT CLAIMS. Wording says "expected value if the probability is right" and "estimate". The text never says
a pick is a lock, a sure thing or earns anything; ``tests/test_jarvis.py`` sweeps the rendered text for that.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from src.hounds import one_side, user_rules
from src.jarvis import board as bd
from src.jarvis import context as ctxmod

MIN_EV = 0.01                  # a pick's expected value at the best price must be at least +1% of the stake
MAX_PLAUSIBLE_EV = 0.15        # a CONSENSUS edge above this is a stale or mis-keyed quote, not a find
MODEL_DISAGREE = 0.05          # a stored model this far from the market makes the pick low confidence
STALE_BOARD_S = 2 * 3600       # the newest quote for a pick older than this before ``as_of`` is not a price to act on
MAX_SINGLES = 5
MIN_SINGLES = 3
MAX_PARLAYS = 2
MAX_PER_MARKET = 2             # so the briefing is not five copies of one prop market
PARLAY_POOL = 8                # parlay legs come from the best of this many eligible singles
MAX_VANISHED = 8
CALIBRATED_SOURCES: frozenset = frozenset()   # none yet; see the module docstring
SOURCE = "jarvis"
SCHEMA = "jarvis_briefing_v1"
CONF_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
MAX_AS_OF_FUTURE = timedelta(minutes=5)

DISCLAIMER = ("Paper bets only. This is an estimate-based briefing, not advice and not a promise of any result. "
              "21+. If gambling stops being fun, call 1-800-GAMBLER (1-800-426-2537).")
RULES = [
    "Nothing shorter than -199 is ever offered, as a pick, a parlay leg or a maximum acceptable price.",
    "One side per game: a parlay never takes two legs from one game, and singles never take both sides of one.",
    "Pregame knowledge is frozen: only rows observed before the as-of time were read, and games already started are left out.",
    "Every probability here is an estimate from a source not yet shown to be calibrated, so each says EXPERIMENTAL.",
]
_BANNED_WORDS = re.compile(r"\b(lock|guarantee[ds]?|sure thing|can't lose|free money|profit|bet check)\b", re.I)


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------

def token(moment: datetime) -> str:
    """The viewer-local time token the site already uses (web/js/local-time.js turns it into the reader's zone)."""
    return f"[[w:{bd.iso(moment)}]]"


def _signed(value: float) -> str:
    text = f"{value:+g}"
    return text


def _team(event: Mapping, side: str) -> str:
    return str(event.get("home_team") if side == "home" else event.get("away_team"))


def selection_label(sel: Mapping) -> str:
    market, side, line = sel["market"], sel["side"], sel["line"]
    if market == "moneyline":
        return f"{_team(sel, side)} moneyline"
    if market == "spread":
        return f"{_team(sel, side)} {_signed(line)}"
    if market == "total":
        return f"{side.capitalize()} {line:g}"
    label = user_rules.MARKET_LABELS.get(market, market)
    return f"{sel['player']} {side} {line:g} ({label.lower()})"


def game_label(sel: Mapping) -> str:
    return f"{sel['away_team']} at {sel['home_team']}"


def _fold(name: Any) -> str:
    return user_rules.fold_player(str(name or ""))


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

def _model_probability(sel: Mapping, model: Optional[Mapping]) -> Optional[dict]:
    if sel["market"] != "moneyline" or not model:
        return None
    p_home = model["home_probability"]
    return {"probability": p_home if sel["side"] == "home" else 1.0 - p_home, "model": model["model"], "detail": model}


def _player_in_lineup(player: str, ctx: Mapping) -> Optional[tuple]:
    """(side, slot) when the player is in a posted lineup, None otherwise (only meaningful once lineups are posted)."""
    want = _fold(player)
    for side in ("home", "away"):
        for slot in (ctx.get("lineups") or {}).get(side) or []:
            if _fold(slot["name"]) == want:
                return side, slot["slot"]
    return None


def evaluate(sels: list, contexts: Mapping, models: Mapping, as_of: datetime, *, check_stale: bool = True) -> list:
    """One record per selection: ``status`` is "eligible" or the reason it is not. Never drops silently."""
    out = []
    for s in sels:
        rec = dict(s)
        rec["status"] = "eligible"
        ctx = contexts.get(s["event_id"]) or {}
        model = _model_probability(s, models.get(s["event_id"]))
        p = model["probability"] if model else s["fair"]
        rec["probability"], rec["source"] = p, ("model" if model else "consensus")
        rec["model"] = model
        if not bd.price_allowed(s["best_price"], s["average_price"]):
            rec["status"] = "price_at_the_ban"
        elif s["books"] < bd.MIN_BOOKS:
            rec["status"] = "thin_market"
        elif p is None:
            rec["status"] = "no_consensus"
        else:
            rec["ev"] = bd.expected_value(p, s["best_price"])
            rec["break_even"] = 1.0 / bd.decimal_of(s["best_price"])
            if rec["ev"] < MIN_EV:
                rec["status"] = "ev_below_floor"
            elif not model and rec["ev"] > MAX_PLAUSIBLE_EV:
                rec["status"] = "ev_implausible_quote"
            elif check_stale and bd.age_minutes(s["observed"], as_of) * 60 > STALE_BOARD_S:
                rec["status"] = "stale_board"
            elif s["player"] and ctx.get("lineups_posted") and _player_in_lineup(s["player"], ctx) is None:
                rec["status"] = "not_in_posted_lineup"
        out.append(rec)
    return out


def confidence(rec: Mapping, ctx: Mapping, as_of: datetime) -> tuple:
    """(tier, [why]) for the PRICE INFORMATION behind a pick. HIGH needs three of the four good signs and no flag."""
    points, why = 0, []
    if rec["books"] >= 6:
        points += 1
        why.append(f"{rec['books']} books quote it")
    else:
        why.append(f"only {rec['books']} books quote it")
    if rec.get("fair_spread") is not None and rec["fair_spread"] <= 0.02:
        points += 1
        why.append(f"the other books agree within {rec['fair_spread'] * 100:.1f} points")
    elif rec.get("fair_spread") is not None:
        why.append(f"the other books differ by {rec['fair_spread'] * 100:.1f} points")
    age = bd.age_minutes(rec["observed"], as_of)
    if age <= 60:
        points += 1
        why.append(f"newest quote is {age:.0f} min old")
    else:
        why.append(f"newest quote is {age:.0f} min old")
    if ctx:
        if rec["player"]:
            if ctx.get("lineups_posted"):
                points += 1
                why.append("lineups are posted and he is in one")
            else:
                points -= 1
                why.append("lineups are not posted, so he is not confirmed to play")
        elif ctx["probables"]["home"] and ctx["probables"]["away"]:
            points += 1
            why.append("both probable pitchers are on file")
        else:
            why.append("probable pitchers: no data")
    model = rec.get("model")
    if model and rec.get("fair_all") is not None:
        gap = abs(model["probability"] - rec["fair_all"])
        if gap >= MODEL_DISAGREE:
            points -= 1
            why.append(f"the stored model is {gap * 100:.1f} points from the market")
        else:
            points += 1
            why.append("the stored model is close to the market")
        if (model["detail"].get("starter_input_class") or "CONFIRMED_CURRENT") != "CONFIRMED_CURRENT":
            points -= 1
            why.append("the model's starters are projected, not confirmed")
    tier = "HIGH" if points >= 3 else "MEDIUM" if points == 2 else "LOW"
    if model and rec.get("fair_all") is not None and abs(model["probability"] - rec["fair_all"]) >= MODEL_DISAGREE:
        tier = "LOW"           # a model far from the market caps the tier whatever else is good
    if rec["player"] and not (ctx and ctx.get("lineups_posted")):
        tier = "LOW"           # a prop on a player not confirmed to start is never above LOW
    return tier, why


def _context_lines(rec: Mapping, ctx: Mapping) -> list:
    if not ctx:
        return ["Game context: no data (the odds event is not mapped to a game yet)."]
    lines = []
    pr = ctx["probables"]
    lines.append("Probables: " + (f"{pr['away']['name']} (away) vs {pr['home']['name']} (home)"
                                  if pr["home"] and pr["away"] else "no data"))
    if rec["player"] and ctx.get("lineups_posted"):
        where = _player_in_lineup(rec["player"], ctx)
        lines.append(f"Lineup: posted; {rec['player']} bats {where[1]} for the {where[0]} side" if where else "Lineup: posted")
    else:
        lines.append("Lineup: " + ("posted" if ctx.get("lineups_posted") else "not posted yet (no data)"))
    lines.append("Umpire: " + (str(ctx["umpire"]) if ctx.get("umpire") else "no data"))
    w = ctx.get("weather")
    if w:
        bits = [f"{w['temp_f']:g} F" if w.get("temp_f") is not None else None,
                f"wind {w['wind_mph']:g} mph from {w['wind_from_deg']:g} deg" if w.get("wind_mph") is not None and w.get("wind_from_deg") is not None else None,
                f"{w['precip_probability_pct']:g}% rain" if w.get("precip_probability_pct") is not None else None,
                f"roof {w['roof']}" if w.get("roof") else None]
        lines.append("Weather (stored forecast): " + ", ".join(b for b in bits if b))
    else:
        lines.append("Weather: no data")
    tx = ctx.get("transactions") or []
    lines.append("Transactions (72h): " + ("; ".join(f"{t['team']} {t['player'] or 'player'} {t['category']}" for t in tx[:5])
                                          + (f" (+{len(tx) - 5} more)" if len(tx) > 5 else "") if tx else "none on file"))
    lines.append("Injuries: " + ctxmod.NO_DATA + " (no injury feed is stored for this sport)")
    return lines


def explain(rec: dict, ctx: Mapping, as_of: datetime, max_price: Optional[int]) -> dict:
    """Reasons, how it could lose and what to avoid, every sentence built from this pick's own stored numbers."""
    p, be, ev = rec["probability"], rec["break_even"], rec["ev"]
    best = bd.american_text(rec["best_price"])
    reasons, lose, avoid = [], [], []
    if rec["source"] == "model":
        m = rec["model"]
        reasons.append(f"{m['model']} (stored, not recalibrated) puts this at {_pct(p)}; break-even at {best} is {_pct(be)}.")
        if rec.get("fair_all") is not None:
            reasons.append(f"The {rec['books']} books' no-vig market says {_pct(rec['fair_all'])}.")
    else:
        reasons.append(f"Best price {best} at {rec['best_book']}; the other {rec['other_books']} books' no-vig consensus is "
                       f"{_pct(p)} against a break-even of {_pct(be)} at that price.")
        reasons.append("That is a price gap against the rest of the market, not information the market lacks.")
    reasons.append(f"Expected value {ev * 100:+.1f}% of the stake if that probability is right; "
                   f"average price {bd.american_text(rec['average_price'])} across {rec['books']} books.")
    reasons.extend(_context_lines(rec, ctx))
    lose.append(f"It loses about {_pct(1 - p)} of the time even if the estimate is exactly right.")
    lose.append(f"The cushion over break-even is {(p - be) * 100:.1f} points; a probability that high by that much removes the edge.")
    if rec["label"] == "EXPERIMENTAL":
        lose.append("The probability is EXPERIMENTAL: this source has not been shown to be calibrated.")
    if rec["source"] == "model" and rec.get("fair_all") is not None and abs(p - rec["fair_all"]) >= MODEL_DISAGREE:
        lose.append(f"Our stored model and the market are {abs(p - rec['fair_all']) * 100:.1f} points apart; in the repo's own "
                    "measurements the market has tracked results at least as well as our models.")
    if rec["player"] and not ctx.get("lineups_posted"):
        lose.append("The lineup is not posted; if he does not start this bet has no action or loses, depending on the book.")
    if rec["market"] == "total" and ctx and ctx.get("weather"):
        lose.append("Wind and temperature move totals and the forecast can change before first pitch.")
    avoid.append(f"Do not take it worse than {bd.american_text(max_price)}; below that the expected value is under {MIN_EV * 100:.0f}%.")
    if rec["market"] in ("spread", "total") or rec["player"]:
        avoid.append(f"Only at {rec['line']:g}: a different line is a different bet.")
    avoid.append("Do not add the other side of this game (one side per game).")
    if rec["player"]:
        avoid.append("Skip it if the lineup posts without him.")
    return {"reasons": reasons, "could_lose": lose, "avoid": avoid}


def _identity(rec: Mapping) -> tuple:
    return (rec["event_id"], rec["market"], rec["side"], rec["line"], rec.get("player"))


def pick_view(rec: Mapping, ctx: Mapping, as_of: datetime, rank: int) -> dict:
    tier, why = confidence(rec, ctx, as_of)
    label = "calibrated" if rec["source"] in CALIBRATED_SOURCES else "EXPERIMENTAL"
    mp = bd.max_price(rec["probability"], MIN_EV)
    full = {**rec, "label": label}
    view = {
        "rank": rank, "kind": "single", "sport_market": rec["market"], "side": rec["side"], "line": rec["line"],
        "player": rec["player"], "label_text": selection_label(rec), "game": game_label(rec),
        "event_id": rec["event_id"], "first_pitch_utc": rec["commence_time"],
        "first_pitch": token(bd.parse_time(rec["commence_time"])),
        "best_price": rec["best_price"], "best_book": rec["best_book"], "average_price": rec["average_price"],
        "books": rec["books"], "captured_utc": bd.iso(rec["observed"]), "captured": token(rec["observed"]),
        "max_acceptable_price": mp, "probability": round(rec["probability"], 4), "break_even": round(rec["break_even"], 4),
        "market_fair": None if rec.get("fair_all") is None else round(rec["fair_all"], 4),
        "expected_value": round(rec["ev"], 4), "probability_source": rec["source"],
        "model": None if not rec.get("model") else rec["model"]["model"],
        "confidence": tier, "confidence_why": why, "label": label,
    }
    view.update(explain(full, ctx, as_of, mp))
    return view


# ---------------------------------------------------------------------------
# singles, parlays, vanished edges
# ---------------------------------------------------------------------------

def rank_key(rec: Mapping, ctx: Mapping, as_of: datetime) -> tuple:
    tier, _ = confidence(rec, ctx, as_of)
    return (-CONF_RANK[tier], -rec["ev"], rec["event_id"], rec["market"], str(rec["player"]), rec["side"])


def choose_singles(eligible: list, contexts: Mapping, as_of: datetime) -> tuple:
    """(ranked eligible after the one-side rule, the singles shown, refusals by code)."""
    ranked = sorted(eligible, key=lambda r: rank_key(r, contexts.get(r["event_id"]) or {}, as_of))
    dropped: list = []
    kept = one_side.keep_first(ranked, lambda r: (r["event_id"], r["market"], r["side"], r["player"], r["line"]),
                               dropped=dropped, hound_id=SOURCE)
    per_market: dict = {}
    shown = []
    for r in kept:
        if per_market.get(r["market"], 0) >= MAX_PER_MARKET:
            continue
        per_market[r["market"]] = per_market.get(r["market"], 0) + 1
        shown.append(r)
        if len(shown) == MAX_SINGLES:
            break
    return kept, shown, [(r, c) for r, c in dropped]


def _game_key(rec: Mapping) -> tuple:
    return (rec["home_team"], rec["away_team"], rec["commence_time"])


def choose_parlays(kept: list, contexts: Mapping, as_of: datetime) -> tuple:
    """(parlays, reason when fewer than two). Two legs from different games; never both sides of one game."""
    pool = kept[:PARLAY_POOL]
    pairs = []
    for a, b in itertools.combinations(pool, 2):
        if _game_key(a) == _game_key(b) or a["event_id"] == b["event_id"]:
            continue
        p = a["probability"] * b["probability"]
        dec = bd.decimal_of(a["best_price"]) * bd.decimal_of(b["best_price"])
        ev = p * (dec - 1.0) - (1.0 - p)
        if ev >= MIN_EV:
            pairs.append((ev, a, b, p, dec))
    pairs.sort(key=lambda t: (-t[0], _identity(t[1]), _identity(t[2])))
    chosen, used = [], set()
    for ev, a, b, p, dec in pairs:
        if _identity(a) in used or _identity(b) in used:
            continue
        chosen.append((ev, a, b, p, dec))
        used.update([_identity(a), _identity(b)])
        if len(chosen) == MAX_PARLAYS:
            break
    games = {_game_key(r) for r in pool}
    reason = None
    if len(chosen) < MAX_PARLAYS:
        reason = ("no parlay: the slate has one game with a priced pick, and legs from one game are correlated and could hold "
                  "both sides" if len(games) < 2 else "fewer than two legs from different games cleared the bar together")
    out = []
    for i, (ev, a, b, p, dec) in enumerate(chosen, 1):
        legs = [pick_view(x, contexts.get(x["event_id"]) or {}, as_of, 0) for x in (a, b)]
        tiers = [l["confidence"] for l in legs]
        mp_dec = (1.0 + MIN_EV) / p
        out.append({
            "rank": i, "kind": "parlay", "legs": legs, "probability": round(p, 4), "break_even": round(1.0 / dec, 4),
            "best_price": int(round(bd.odds_math.decimal_to_american(dec))), "expected_value": round(ev, 4),
            "max_acceptable_price": int(round(bd.odds_math.decimal_to_american(mp_dec))),
            "confidence": min(tiers, key=lambda t: CONF_RANK[t]), "label": "EXPERIMENTAL",
            "label_text": " + ".join(l["label_text"] for l in legs),
            "reasons": [f"Both legs cleared the bar on their own (combined probability {_pct(p)}, break-even {_pct(1.0 / dec)}).",
                        "The games are different, so no leg can hold the other side of a game.",
                        "The legs are treated as independent, which they only approximately are."],
            "could_lose": [f"A parlay loses if either leg loses; this one wins about {_pct(p)} of the time even if both estimates are right.",
                           "Both probabilities are EXPERIMENTAL, so the combined number is too."],
            "avoid": ["Do not take a leg at a worse price than its own maximum acceptable price.",
                      "Do not swap in a different line for either leg."]})
    return out, reason


def vanished_edges(open_recs: list, current_recs: list, current_eligible: set, as_of: datetime) -> list:
    """Selections that cleared the bar on the open board and are not eligible now, with what happened to them."""
    now_by = {_identity(r): r for r in current_recs}
    out = []
    for r in sorted((x for x in open_recs if x["status"] == "eligible"), key=lambda x: -x["ev"]):
        key = _identity(r)
        if key in current_eligible:
            continue
        cur = now_by.get(key)
        if cur is None:
            what = "no longer quoted at this line (the line moved or the market closed)"
            now = None
        else:
            now = {"best_price": cur["best_price"], "expected_value": None if "ev" not in cur else round(cur["ev"], 4),
                   "why_not": cur["status"]}
            what = (f"best price moved from {bd.american_text(r['best_price'])} to {bd.american_text(cur['best_price'])}"
                    if cur["best_price"] != r["best_price"] else "the consensus moved toward the price")
        out.append({"label_text": selection_label(r), "game": game_label(r),
                    "open": {"best_price": r["best_price"], "best_book": r["best_book"], "expected_value": round(r["ev"], 4),
                             "captured": token(r["observed"])},
                    "now": now, "what_happened": what})
        if len(out) == MAX_VANISHED:
            break
    return out


# ---------------------------------------------------------------------------
# the briefing
# ---------------------------------------------------------------------------

def build_briefing(date: str, as_of: Optional[datetime] = None, *, sport: str = "mlb", now: Optional[datetime] = None,
                   multibook_path: Optional[Path] = None) -> dict:
    """The briefing for one Eastern date, built from rows observed at or before ``as_of`` (default: now)."""
    now = now or datetime.now(timezone.utc)
    as_of = bd.parse_time(as_of) if as_of is not None else now
    if as_of is None or as_of > now + MAX_AS_OF_FUTURE:
        raise ValueError("as_of must be a time that has already happened")
    game_rows = bd.read_game_rows(date, as_of, sport, multibook_path)
    events = {r["event_id"]: {"away_team": r["away_team"], "home_team": r["home_team"], "commence_time": r["commence_time"]}
              for r in game_rows}
    prop_rows = bd.read_prop_rows(events, as_of, sport) if events else []
    all_rows = game_rows + prop_rows
    contexts, models = {}, {}
    if sport == "mlb" and events:
        pks = ctxmod.event_game_pks(as_of)
        names = ctxmod.player_names()
        for eid, ev in events.items():
            contexts[eid] = ctxmod.game_context(ev, pks.get(eid), as_of, names)
            m = ctxmod.model_for_game(ev, pks.get(eid), as_of)
            if m:
                models[eid] = m
    current = bd.board_at(all_rows, as_of)
    opening = bd.board_at(all_rows, as_of, which="first")
    cur_recs = evaluate(bd.all_selections(current), contexts, models, as_of)
    open_recs = evaluate(bd.all_selections(opening), contexts, models, as_of, check_stale=False)
    eligible = [r for r in cur_recs if r["status"] == "eligible"]
    kept, shown, refused = choose_singles(eligible, contexts, as_of)
    singles = [pick_view(r, contexts.get(r["event_id"]) or {}, as_of, i) for i, r in enumerate(shown, 1)]
    parlays, parlay_reason = choose_parlays(kept, contexts, as_of)
    vanished = (vanished_edges(open_recs, cur_recs, {_identity(r) for r in eligible}, as_of)
                if bd.window_start(all_rows) and bd.window_start(all_rows) < bd.newest(all_rows) else [])
    excluded: dict = {}
    for r in cur_recs:
        if r["status"] != "eligible":
            excluded[r["status"]] = excluded.get(r["status"], 0) + 1
    for _, code in refused:
        excluded[code] = excluded.get(code, 0) + 1
    brief = {
        "schema": SCHEMA, "date": date, "sport": sport, "as_of": bd.iso(as_of), "generated_utc": bd.iso(now),
        "paper_only": True, "disclaimer": DISCLAIMER, "rules": RULES,
        "singles": singles, "parlays": parlays, "parlay_note": parlay_reason, "vanished_edges": vanished,
        "excluded": dict(sorted(excluded.items())),
        "games": [{"event_id": eid, "game": f"{e['away_team']} at {e['home_team']}", "first_pitch_utc": e["commence_time"],
                   "first_pitch": token(bd.parse_time(e["commence_time"])), "context": contexts.get(eid),
                   "stored_model": None if eid not in models else {k: (bd.iso(v) if isinstance(v, datetime) else v)
                                                                   for k, v in models[eid].items()}}
                  for eid, e in sorted(events.items(), key=lambda kv: (kv[1]["commence_time"], kv[0]))],
        "inputs": {"games_on_board": len(events), "game_quotes_read": len(game_rows), "prop_quotes_read": len(prop_rows),
                   "selections_evaluated": len(cur_recs), "eligible": len(eligible), "games_with_context": sum(1 for c in contexts.values() if c.get("game_pk")),
                   "games_with_stored_model": len(models)},
        "status": "ok" if singles else ("no_board" if not events else "nothing_cleared"),
        "published": False, "filed": [],
    }
    brief["headline"] = headline(brief)
    if len(singles) < MIN_SINGLES and events:
        brief["short_note"] = (f"Only {len(singles)} single(s) cleared the bar (need expected value of at least {MIN_EV * 100:.0f}%, "
                               "at least four books, no pick shorter than -199, one side per game). Nothing was padded.")
    return brief


def headline(brief: Mapping) -> str:
    when = token(bd.parse_time(brief["as_of"]))
    n, m = len(brief["singles"]), len(brief["parlays"])
    if brief["status"] == "no_board":
        return (f"Jarvis {brief['date']} ({brief['sport'].upper()}) as of {when}: no priced pre-game board for this date "
                "(no games listed, or every game had started). Nothing to brief.")
    if not n:
        return (f"Jarvis {brief['date']} ({brief['sport'].upper()}) as of {when}: a board existed "
                f"({brief['inputs']['selections_evaluated']} selections) and none cleared the bar.")
    top = brief["singles"][0]
    return (f"Jarvis {brief['date']} ({brief['sport'].upper()}) as of {when}: {n} single(s), {m} parlay(s). "
            f"Top: {top['label_text']} {bd.american_text(top['best_price'])} ({top['label']}, {top['confidence'].lower()} confidence).")


# ---------------------------------------------------------------------------
# filing and saving
# ---------------------------------------------------------------------------

def _leg_for(view: Mapping, event: Mapping, sport: str) -> dict:
    market = view["sport_market"]
    selection = view["player"] or (view["label_text"].split(" moneyline")[0] if market == "moneyline"
                                   else view["label_text"].rsplit(" ", 1)[0] if market == "spread" else view["side"].capitalize())
    return {"sport": sport.upper(), "game": view["game"], "event_id": view["event_id"], "market": market,
            "selection": selection, "side": view["side"], "line": view["line"], "price": view["best_price"],
            "player": view["player"], "commence_time": view["first_pitch_utc"]}


def recommendation_id(date: str, legs: list) -> str:
    """Stable per (date, bets): re-running a briefing never files a second copy, so the FIRST publish time stands."""
    ident = sorted([l["event_id"], l["market"], l["side"], l["line"], l.get("player")] for l in legs)
    digest = hashlib.sha256(json.dumps([date, ident], sort_keys=True, default=str).encode()).hexdigest()
    return f"jv-{date}-{digest[:14]}"


def file_picks(brief: dict, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """File every published single and parlay through ``apprentice.store.add_recommendation`` (source "jarvis").

    The publish time is the real clock, never ``as_of``: a briefing computed for an earlier instant cannot
    back-date itself to earn an evidence grade. A pick already filed (same date and bets) keeps its first time.
    """
    from src.hounds.apprentice import store
    now = now or datetime.now(timezone.utc)
    events = {g["event_id"]: g for g in brief["games"]}
    filed = []
    for item in brief["singles"] + brief["parlays"]:
        views = item["legs"] if item["kind"] == "parlay" else [item]
        legs = [_leg_for(v, events.get(v["event_id"]) or {}, brief["sport"]) for v in views]
        rec_id = recommendation_id(brief["date"], legs)
        status = "filed"
        try:
            rec = store.add_recommendation(rec_id, SOURCE, bd.iso(now), legs, now=now, db=db)
        except store.StoreError as exc:
            if exc.code != "duplicate":
                raise
            status, rec = "already_filed", store.get_recommendation(rec_id, db=db)
        item["recommendation_id"] = rec_id
        item["published_utc"] = rec["recommended_utc"]
        item["published"] = token(bd.parse_time(rec["recommended_utc"]))
        filed.append({"recommendation_id": rec_id, "kind": item["kind"], "label_text": item["label_text"], "status": status,
                      "published_utc": rec["recommended_utc"]})
    brief["filed"], brief["published"] = filed, True
    return brief


def output_dir() -> Path:
    """Where owner outputs live: JARVIS_DIR, else beside the app database (the Fly volume in production)."""
    override = (os.environ.get("JARVIS_DIR") or "").strip()
    if override:
        return Path(override)
    from src.appstate import users as users_store
    return users_store.db_path().parent / "jarvis"


def save(brief: Mapping, folder: Optional[Path] = None) -> Path:
    """Write the dated, as-of-stamped copy and the date's ``latest`` copy; returns the stamped path."""
    folder = folder or output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = brief["as_of"].replace(":", "").replace("-", "")
    text = json.dumps(brief, indent=2, sort_keys=True, default=str)
    path = folder / f"{brief['date']}__{stamp}.json"
    path.write_text(text, encoding="utf-8")
    (folder / f"{brief['date']}__latest.json").write_text(text, encoding="utf-8")
    return path


def load_latest(date: str, folder: Optional[Path] = None) -> Optional[dict]:
    path = (folder or output_dir()) / f"{date}__latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"\[\[w:([^\]\s]+)\]\]")
_WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def to_pacific(moment: datetime) -> datetime:
    """The Pacific wall clock for a UTC instant without a tz database (US rules written out, as src/data/eastern.py)."""
    from src.data.eastern import nth_sunday
    utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    start = datetime.combine(nth_sunday(utc.year, 3, 2), datetime.min.time()) + timedelta(hours=10)   # 02:00 PST
    end = datetime.combine(nth_sunday(utc.year, 11, 1), datetime.min.time()) + timedelta(hours=9)     # 02:00 PDT
    return utc + timedelta(hours=-7 if start <= utc < end else -8)


def pacific_text(moment: datetime) -> str:
    local = to_pacific(moment)
    hour = local.hour % 12 or 12
    return f"{_WEEK[local.weekday()]} {_MONTH[local.month - 1]} {local.day} {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} PT"


def resolve_tokens(text: str) -> str:
    """Every ``[[w:ISO]]`` turned into Pacific text (the CLI's plain-text reader; pages use web/js/local-time.js)."""
    def one(m):
        moment = bd.parse_time(m.group(1))
        return pacific_text(moment) if moment else ""
    return _TOKEN.sub(one, text)


def _pick_lines(p: Mapping, indent: str = "") -> list:
    out = [f"{indent}{p['label_text']}  [{p['label']}]  confidence {p['confidence']}"]
    if p["kind"] == "single":
        out.append(f"{indent}  {p['game']}  first pitch {p['first_pitch']}")
        out.append(f"{indent}  best {bd.american_text(p['best_price'])} at {p['best_book']}, average {bd.american_text(p['average_price'])} "
                   f"across {p['books']} books, captured {p['captured']}")
        out.append(f"{indent}  max acceptable price {bd.american_text(p['max_acceptable_price'])}")
        out.append(f"{indent}  probability {_pct(p['probability'])} vs break-even {_pct(p['break_even'])}, "
                   f"expected value {p['expected_value'] * 100:+.1f}% if the estimate is right (source: {p['probability_source']})")
    else:
        for leg in p["legs"]:
            out.append(f"{indent}  leg: {leg['label_text']} {bd.american_text(leg['best_price'])} at {leg['best_book']} "
                       f"(max {bd.american_text(leg['max_acceptable_price'])}; {leg['game']}; captured {leg['captured']})")
        out.append(f"{indent}  combined {bd.american_text(p['best_price'])}, max acceptable {bd.american_text(p['max_acceptable_price'])}, "
                   f"probability {_pct(p['probability'])} vs break-even {_pct(p['break_even'])}, "
                   f"expected value {p['expected_value'] * 100:+.1f}% if the estimates are right")
    for title, key in (("Why", "reasons"), ("How it could lose", "could_lose"), ("Avoid", "avoid")):
        out.append(f"{indent}  {title}:")
        out.extend(f"{indent}    - {line}" for line in p[key])
    if p.get("published"):
        out.append(f"{indent}  filed {p.get('recommendation_id')} at {p['published']}")
    return out


def render(brief: Mapping) -> str:
    """The briefing as plain text (tokens still in; ``resolve_tokens`` makes them Pacific)."""
    lines = [brief["headline"], "", brief["disclaimer"], ""]
    if brief.get("short_note"):
        lines += [brief["short_note"], ""]
    lines.append("SINGLES")
    for p in brief["singles"]:
        lines.append(f" #{p['rank']}")
        lines.extend(_pick_lines(p, " "))
        lines.append("")
    if not brief["singles"]:
        lines += [" none", ""]
    lines.append("PARLAYS (two legs, different games)")
    for p in brief["parlays"]:
        lines.append(f" #{p['rank']}")
        lines.extend(_pick_lines(p, " "))
        lines.append("")
    if brief.get("parlay_note"):
        lines += [" " + brief["parlay_note"], ""]
    lines.append("EDGES THAT VANISHED SINCE THE OPEN")
    for v in brief["vanished_edges"]:
        now = "gone" if not v["now"] else f"now {bd.american_text(v['now']['best_price'])}"
        lines.append(f" - {v['label_text']} ({v['game']}): open {bd.american_text(v['open']['best_price'])} at {v['open']['best_book']} "
                     f"({v['open']['expected_value'] * 100:+.1f}%), {now}: {v['what_happened']}")
    if not brief["vanished_edges"]:
        lines.append(" none (or the open and current boards are the same capture)")
    lines += ["", "LEFT OUT (count by reason): " + (", ".join(f"{k} {v}" for k, v in brief["excluded"].items()) or "nothing"), ""]
    lines.append("INPUTS")
    inp = brief["inputs"]
    lines.append(f" games on the board {inp['games_on_board']}, game quotes read {inp['game_quotes_read']}, prop quotes read "
                 f"{inp['prop_quotes_read']}, games with watch-file context {inp['games_with_context']}, with a stored model "
                 f"{inp['games_with_stored_model']}")
    for g in brief["games"]:
        c = g.get("context") or {}
        lines.append(f" - {g['game']} ({g['first_pitch']}): missing " + (", ".join(c.get("missing") or []) or "nothing") if c else
                     f" - {g['game']} ({g['first_pitch']}): no context (no data)")
    lines += ["", "RULES"] + [f" - {r}" for r in brief["rules"]]
    if brief["filed"]:
        lines += ["", f"FILED {len(brief['filed'])} recommendation(s) with source {SOURCE}."]
    text = "\n".join(lines)
    if _BANNED_WORDS.search(text.replace(brief["disclaimer"], "")):
        raise ValueError("rendered briefing contains a banned phrase")
    return text
