"""What a lesson is, and how its current state is DERIVED from its append-only history.

A lesson row never changes. Its state does, by APPENDING events (``store.append_event``); the state a page shows is
computed here from those events. Three kinds of source write events:

  owner   the member typed a state ("it won", "I cashed out for $40")
  ticket  a later screenshot of the same ticket said so (a re-import appends one of these, never an edit)
  grader  our own results loop graded the legs (src/hounds/apprentice/grading.py)

owner and ticket are ONE channel, "the book's word" (both are what the sportsbook says happened to real money); the
grader is the other. When the two channels both name a settled result and the results differ, the lesson is DISPUTED:
flagged, never overwritten, and left out of profit, ROI and win rate until the owner appends a resolution event.
Nothing here guesses which side is right.

STATES: pending, live, settled (result won / lost / push), void, cashed_out (with the amount).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from src.hounds import user_rules, user_spec
from src.hounds.apprentice import calc

PENDING, LIVE, SETTLED, VOID, CASHED_OUT = "pending", "live", "settled", "void", "cashed_out"
STATES = (PENDING, LIVE, SETTLED, VOID, CASHED_OUT)
TERMINAL = (SETTLED, VOID, CASHED_OUT)
SOURCES = ("owner", "ticket", "grader")
BETTORS = ("Brey", "Jacob", "unknown")           # whose real money it was (owner audit 2026-10-25); default unknown
GRADES = ("A", "B", "C", "D")
BOOK_SOURCES = ("owner", "ticket")

BASE_MARKETS = ("moneyline", "spread", "total")
# the props a member can name (the ones we can grade, plus the common football ones we only record)
EXTRA_PROP_MARKETS = ("player_rushing_yards", "player_receiving_yards", "player_passing_yards", "player_receptions",
                      "player_anytime_td", "other")
MARKETS = BASE_MARKETS + tuple(user_rules.PROP_MARKETS) + EXTRA_PROP_MARKETS
SIDES = ("home", "away", "over", "under", "yes", "no")
MAX_LEGS = 12
MAX_STAKE = 1_000_000.0
MAX_TEXT = 120
_ID_RE = re.compile(r"^[A-Za-z0-9._\-:]{1,64}$")


class LessonError(ValueError):
    def __init__(self, fields: Mapping[str, str], code: str = "invalid"):
        self.fields = dict(fields)
        self.code = code
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.fields.items()))


def _text(value: Any, limit: int = MAX_TEXT) -> Optional[str]:
    if value is None:
        return None
    out = " ".join(str(value).split())
    return out[:limit] or None


def _price(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        p = int(round(float(str(value).replace("+", ""))))
    except (TypeError, ValueError):
        return None
    return p if (p >= 100 or p <= -100) and abs(p) <= 100000 else None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        out = float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) < 1e9 else None


def parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        out = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_leg(raw: Any, i: int, errors: dict) -> Optional[dict]:
    p = f"legs[{i}]."
    if not isinstance(raw, Mapping):
        errors[f"legs[{i}]"] = "must be an object"
        return None
    sport = _text(raw.get("sport"), 20)
    if sport not in user_spec.SPORTS:
        errors[p + "sport"] = "pick a sport from the list"
    market = _text(raw.get("market"), 40)
    if market not in MARKETS:
        errors[p + "market"] = "pick a market from the list"
    selection = _text(raw.get("selection"))
    if not selection:
        errors[p + "selection"] = "say what was bet on"
    side = _text(raw.get("side"), 10)
    if side is not None and side not in SIDES:
        errors[p + "side"] = "must be home, away, over, under, yes or no"
    price = _price(raw.get("price"))
    if price is None:
        errors[p + "price"] = "needs the price you got, like -115 or +253"
    line = None
    if raw.get("line") not in (None, ""):
        line = _number(raw.get("line"))
        if line is None:
            errors[p + "line"] = "must be a number"
    if market in MARKETS and market not in ("moneyline", "player_anytime_td", "other") and line is None:
        errors.setdefault(p + "line", "this market needs a line")
    player = _text(raw.get("player"), 60)
    if market in MARKETS and market not in BASE_MARKETS and market != "other" and not player:
        errors[p + "player"] = "a player prop needs the player"
    out = {"sport": sport, "game": _text(raw.get("game")), "market": market, "selection": selection, "side": side,
           "line": line, "price": price, "player": player}
    # what the BOARD told the server (never the client): identity for grading, CLV and exposure
    for key in ("event_id", "away_team", "home_team", "commence_time", "slate_date", "game_pk"):
        if raw.get(key) not in (None, ""):
            out[key] = str(raw[key])[:80]
    return out


def normalize_lesson(raw: Mapping, *, now: Optional[datetime] = None) -> dict:
    """The validated, canonical lesson, or ``LessonError`` naming every problem at once (nothing is repaired)."""
    errors: dict = {}
    if not isinstance(raw, Mapping):
        raise LessonError({"lesson": "must be an object"})
    now = now or datetime.now(timezone.utc)
    legs_raw = raw.get("legs")
    legs: list = []
    if not isinstance(legs_raw, (list, tuple)) or not legs_raw:
        errors["legs"] = "add at least one leg"
    elif len(legs_raw) > MAX_LEGS:
        errors["legs"] = f"at most {MAX_LEGS} legs"
    else:
        for i, item in enumerate(legs_raw):
            leg = normalize_leg(item, i, errors)
            if leg is not None:
                legs.append(leg)
    stake = _number(raw.get("stake"))
    if stake is None or stake <= 0 or stake > MAX_STAKE:
        errors["stake"] = "needs the amount you staked, in dollars"
        stake = None
    book = _text(raw.get("book"), 40)
    if not book:
        errors["book"] = "say which book"
    placed = parse_time(raw.get("placed_at"))
    if placed is None:
        errors["placed_at"] = "needs the time the bet was placed"
    elif placed > now + timedelta(hours=1):
        errors["placed_at"] = "cannot be in the future"
    bettor = raw.get("owner") if raw.get("owner") not in (None, "") else "unknown"
    if bettor not in BETTORS:
        errors["owner"] = "choose Brey, Jacob or unknown"
    rec_id = _text(raw.get("recommendation_id"), 64)
    if rec_id is not None and not _ID_RE.match(rec_id):
        errors["recommendation_id"] = "letters, numbers and - _ . : only"
    ticket_id = _text(raw.get("ticket_id"), 64)
    if ticket_id is not None and not _ID_RE.match(ticket_id):
        errors["ticket_id"] = "letters, numbers and - _ . : only"
    total = None
    if raw.get("total_price") not in (None, ""):
        total = _price(raw.get("total_price"))
        if total is None:
            errors["total_price"] = "must be an American price like +253"
    payout = None
    if raw.get("payout") not in (None, ""):
        payout = _number(raw.get("payout"))
        if payout is None or payout < 0:
            errors["payout"] = "must be a dollar amount"
    if errors:
        raise LessonError(errors)
    bet_type = "single" if len(legs) == 1 else "parlay"
    prices = [leg["price"] for leg in legs]
    if bet_type == "single":
        if total is not None and total != prices[0]:
            raise LessonError({"total_price": "a single's price is its leg's price"})
        total = prices[0]
    elif total is None:
        total = calc.to_american(calc.parlay_decimal(prices))
    problems = calc.check_consistency(leg_prices=prices, total_price=total, stake=stake, payout=payout)
    if problems:
        # a real ticket the member typed that disagrees with itself is refused, not stored: they fix the typo and resubmit
        raise LessonError({p["field"]: p["reason"] for p in problems}, code="inconsistent")
    return {"bet_type": bet_type, "legs": legs, "stake": calc.money(stake), "book": book, "placed_utc": iso(placed),
            "ticket_id": ticket_id, "total_price": total, "payout_quoted": None if payout is None else calc.money(payout),
            "bettor": bettor, "recommendation_id": rec_id}


# ---------------------------------------------------------------------------
# evidence grade (owner's performance audit, 2026-10-25)
# ---------------------------------------------------------------------------

def _fold(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _same_line(a: Any, b: Any) -> bool:
    if a in (None, "") and b in (None, ""):
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


def leg_matches(leg: Mapping, rec_leg: Mapping) -> bool:
    """EXACT: the same game, market, player-or-selection, side and line. A different line is a different bet."""
    game_l = leg.get("event_id") or _fold(leg.get("game"))
    game_r = rec_leg.get("event_id") or _fold(rec_leg.get("game"))
    if not game_l or not game_r or game_l != game_r:
        return False
    if leg.get("market") != rec_leg.get("market"):
        return False
    who_l, who_r = _fold(leg.get("player") or leg.get("selection")), _fold(rec_leg.get("player") or rec_leg.get("selection"))
    if not who_l or who_l != who_r:
        return False
    if (leg.get("side") or None) != (rec_leg.get("side") or None):
        return False
    return _same_line(leg.get("line"), rec_leg.get("line"))


def evidence_grade(lesson: Mapping, rec: Optional[Mapping]) -> tuple:
    """(grade, reason). Only A may count toward any "LINEHOUND picks" hit rate or ROI.

    A  Brey's ticket, linked to a recommendation that was published BEFORE the bet was placed and that every leg matches exactly
    B  Brey's ticket with no such match (researched, but nothing proves the pick came first or that it is the same bet)
    C  another bettor's ticket (Jacob)
    D  whose ticket it is was not said (unknown); a duplicate of a filed bet never reaches here (it is refused at filing)"""
    who = lesson.get("bettor") or "unknown"
    if who == "Jacob":
        return "C", "another bettor's ticket"
    if who != "Brey":
        return "D", "the bettor is unknown"
    if rec is None:
        return "B", "no recommendation is linked"
    when, placed = parse_time(rec.get("recommended_utc")), parse_time(lesson.get("placed_utc"))
    if when is None or placed is None or not when < placed:
        return "B", "the recommendation was not published before the bet was placed"
    rec_legs = rec.get("legs") or []
    legs = lesson.get("legs") or []
    if len(rec_legs) != len(legs) or not all(any(leg_matches(l, r) for r in rec_legs) for l in legs):
        return "B", "the bet does not match the recommendation exactly (player or team, market, line)"
    return "A", "published before placement and matched exactly"


# ---------------------------------------------------------------------------
# derived state
# ---------------------------------------------------------------------------

def _settled_key(ev: Mapping) -> Optional[str]:
    """What an event says happened to the ticket, comparably: 'won', 'lost', 'push', 'void', or None (not a result)."""
    if ev["state"] == SETTLED:
        return (ev.get("data") or {}).get("result")
    if ev["state"] == VOID:
        return "void"
    return None


def derive(lesson: Mapping, events: list) -> dict:
    """The lesson's current view from its events (oldest first). Pure."""
    stake = float(lesson["stake"])
    book = [e for e in events if e["source"] in BOOK_SOURCES]
    grader = [e for e in events if e["source"] == "grader"]
    last_book, last_grader = (book[-1] if book else None), (grader[-1] if grader else None)
    flags: list = []
    state, data, basis = PENDING, {}, "owner"
    # the book's word wins over "pending" but a pending/live book event never hides a settled grader event
    if last_book is not None and last_book["state"] in TERMINAL:
        state, data, basis = last_book["state"], dict(last_book.get("data") or {}), last_book["source"]
    elif last_grader is not None and last_grader["state"] in TERMINAL:
        state, data, basis = last_grader["state"], dict(last_grader.get("data") or {}), "grader"
    elif last_book is not None:
        state, data, basis = last_book["state"], dict(last_book.get("data") or {}), last_book["source"]
    disputed = False
    bk = max((e for e in book if _settled_key(e)), key=lambda e: e["seq"], default=None)
    gk = max((e for e in grader if _settled_key(e)), key=lambda e: e["seq"], default=None)
    if bk is not None and gk is not None and _settled_key(bk) != _settled_key(gk):
        resolved = any((e.get("data") or {}).get("resolution") and e["seq"] > max(bk["seq"], gk["seq"]) for e in book)
        if not resolved:
            disputed = True
            flags.append(f"our grader read this as {_settled_key(gk)} and the ticket says {_settled_key(bk)}; "
                         "neither was overwritten. Resolve it to count it.")
    if last_grader is not None and (last_grader.get("data") or {}).get("needs_confirmation") and basis == "grader":
        flags.append("a leg was pushed or voided, so the payout is our repricing; confirm it against the ticket")
    result = data.get("result") if state == SETTLED else ("void" if state == VOID else None)
    payout = profit = None
    if disputed:
        pass
    elif state == SETTLED and result == "won":
        payout = data.get("payout")
        if payout is None:
            payout = lesson.get("payout_quoted")
        if payout is None:
            payout = calc.payout_for(stake, calc.dec(lesson["total_price"]))
        payout = calc.money(payout)
        profit = calc.money(payout - stake)
    elif state == SETTLED and result == "lost":
        payout, profit = 0.0, -calc.money(stake)
    elif state in (VOID,) or (state == SETTLED and result == "push"):
        payout, profit = calc.money(stake), 0.0
    elif state == CASHED_OUT and data.get("cash_out_amount") is not None:
        c = calc.cash_out(stake, data["cash_out_amount"])
        payout, profit = c["payout"], c["profit"]
    terminal = [e for e in events if e["state"] in TERMINAL
                and ((e["source"] == "grader") if basis == "grader" else (e["source"] in BOOK_SOURCES))]
    settled_at = (data.get("settlement_time") or (terminal[-1]["at_utc"] if terminal and state in TERMINAL else None))
    gr = [e for e in grader if e["state"] in TERMINAL]
    closes = (gr[-1].get("data") or {}).get("leg_close") if gr else None
    return {"id": lesson["id"], "state": state, "result": result, "basis": basis, "disputed": disputed, "flags": flags,
            "settlement_time": settled_at, "closing_line": closes,
            "payout": payout, "profit": profit, "cash_out_amount": data.get("cash_out_amount"),
            "leg_results": (last_grader.get("data") or {}).get("leg_results") if last_grader else None,
            "counts": bool(profit is not None and not disputed),
            "history": [{"seq": e["seq"], "at": e["at_utc"], "source": e["source"], "state": e["state"],
                         "data": e.get("data") or {}} for e in events]}
