"""The hound's TRACK RECORD: one payload for web/record.html (docs/HOUND_LOOP_PLAN.md, phase 3).

Built for ANY hound, a member's or a house hound, from the same ``stats.HoundData`` the leaderboard reads, so the page
cannot disagree with the race. Nothing is measured here that the hound page does not already measure; this module only
CUTS the settled forward bets and says what the cuts show, in plain words.

WHAT IS COUNTED
  * the record, units, ROI, closing-line value, streak and curve come from the FORWARD settled bets of the view (all-time or one
    season). A replay (hindsight) ticket is never in any of them, and never listed: this page is the live record.
  * OPEN tickets (recorded, not graded, not stale) are listed apart and are never in a count. A ticket more than 36 hours past
    its start with no grade is listed as "waiting on a grade", also apart.
  * the breakdowns are ``diagnosis.diagnose`` over the same bets: sport, market, price band, favourite or underdog, home or away.
    ``diagnose`` rates every cut by its size (``too_few`` under 5 bets), so a thin cut is said to be thin, never read.
  * units are on the hound's own basis (the board's average price when it covers the bets, else the recorded price), the same
    one the header, the curve and the calendar use, so the page adds up.

NOTHING IS GUESSED. A missing closing-line value is omitted, not zero. Compare is None when no other hound has settled a bet.
No sentence here forecasts, recommends, or calls a result a profit claim: each is a fact about settled paper bets.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Sequence

from src.hounds import stats
from src.hounds.contract import (
    KIND_HOUSE, TICKET_GRADED, TICKET_OPEN, TICKET_UNGRADED, BetRow, envelope, ticket_status, to_json)
from src.hounds.interact import diagnosis
from src.hounds.ledgers import Bet

SETTLED = ("win", "loss", "push")
TICKET_CAP = 250                 # the ticket list carries this many of the newest settled tickets (a filter works inside them)
OPEN_CAP = 40
CALENDAR_CAP = 180               # days of calendar kept
SMALL_SAMPLE = 20                # settled bets under this: the header says the record is a small sample
COMPARE_MIN_HOUNDS = 1

HINDSIGHT_NOTE = ("This is the live paper record. A backtest is hindsight, so it is never counted here.")
UNITS_NOTE = ("Units are paper units at each hound's own stake basis (the board's average price when it has it). "
              "A record describes settled bets; it does not say what comes next.")

#: the cuts the page shows, in order: (group id in diagnosis, title, noun for a sentence, keys kept)
GROUP_PLAN = (
    ("sport", "By sport", "sport", None),
    ("market", "By market", "market", None),
    ("band", "By price band", "price band", None),
    ("role", "Favourite or underdog", "kind of pick", None),
    ("venue", "Home or away", "side", ("home", "away")),
)


# ---------------------------------------------------------------------------
# a BetRow, as the diagnosis wants a bet
# ---------------------------------------------------------------------------

_AT = re.compile(r"\s+(?:at|@)\s+", re.IGNORECASE)


def infer_side(row: BetRow) -> Optional[str]:
    """home | away | over | under, from what a ticket row carries (it has the selection and the game, not the side)."""
    sel = str(row.selection or "").strip().lower()
    market = str(row.market or "").lower()
    if "total" in market or sel.startswith(("over ", "under ")) or sel in ("over", "under"):
        first = sel.split(" ")[0]
        return first if first in ("over", "under") else None
    parts = _AT.split(str(row.game or "").strip(), maxsplit=1)
    if len(parts) == 2:
        away, home = parts[0].strip().lower(), parts[1].strip().lower()
        if home and sel.startswith(home):
            return "home"
        if away and sel.startswith(away):
            return "away"
    first = sel.split(" ")[0] if sel else ""
    return first if first in ("home", "away") else None


def _as_bets(rows: Sequence[BetRow], basis: str, default_sport: Optional[str]) -> list:
    out = []
    for i, r in enumerate(rows):
        out.append(Bet(
            hound_id=r.hound_id, segment=r.segment, date=r.date, decision_utc=r.recorded_utc or r.start_utc, start_utc=r.start_utc,
            recorded_utc=r.recorded_utc, bet_id=f"{r.event_id or r.date}|{r.market}|{r.selection}|{i}", event_id=r.event_id,
            sport=str(r.sport or default_sport or ""), market_key=r.market or "", side=infer_side(r), line=r.line, price=r.price,
            price_average=r.price_average if basis == "average_price" else None, book=r.book, book_count=r.book_count,
            result=r.result, units=r.units))
    return out


def _units(bet: Bet, basis: str) -> float:
    value = stats.average_units(bet) if basis == "average_price" else stats.recorded_units(bet)
    return float(value) if value is not None else 0.0


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def _bets_word(n: int) -> str:
    return "1 bet" if n == 1 else f"{n} bets"


def _rec(r: dict) -> str:
    return f"{r['wins']}-{r['losses']}" + (f"-{r['pushes']}" if r["pushes"] else "")


def _u(x: float) -> str:
    return f"{x:+.1f}u"


def _cut_row(f: dict) -> dict:
    return {"key": str(f["id"]).split(":", 1)[1], "label": f["label"], "n": f["n"], "wins": f["wins"], "losses": f["losses"],
            "pushes": f["pushes"], "units": f["units"], "units_per_bet": f["units_per_bet"], "win_pct": f["win_pct"],
            "level": f["level"], "level_text": f["level_text"], "thin": f["level"] == "too_few", "direction": f["direction"]}


def plain_line(rows: Sequence[dict], noun: str) -> str:
    """One plain sentence: what is working, what is not, and which cuts are too thin to judge. Facts about the past only."""
    total = sum(r["n"] for r in rows)
    if not rows or total == 0:
        return "No settled bets in this cut yet."
    if len(rows) == 1:
        r = rows[0]
        return (f"Every settled bet so far is in one {noun} ({r['label']}: {_rec(r)}, {_u(r['units'])}, {_bets_word(r['n'])}), "
                "so there is nothing to compare yet.")
    solid = [r for r in rows if not r["thin"]]
    thin = [r for r in rows if r["thin"]]
    parts = []
    good = max((r for r in solid if r["units"] > 0), key=lambda r: (r["units"], r["n"]), default=None)
    bad = min((r for r in solid if r["units"] < 0), key=lambda r: (r["units"], -r["n"]), default=None)
    if good:
        parts.append(f"What's working: {good['label']}, {_rec(good)}, {_u(good['units'])} over {_bets_word(good['n'])}.")
    if bad:
        parts.append(f"What's not: {bad['label']}, {_rec(bad)}, {_u(bad['units'])} over {_bets_word(bad['n'])}.")
    if not good and not bad:
        if solid:
            parts.append("Nothing stands out: every cut with enough bets is level.")
        else:
            return (f"Only {_bets_word(total)} across these cuts so far (each cut has under {diagnosis.MIN_FACTOR_BETS}), "
                    "too few to say what's working or not.")
    if thin and solid:
        parts.append("Too few to judge: " + "; ".join(f"{r['label']} (only {_bets_word(r['n'])})" for r in thin) + ".")
    if total < SMALL_SAMPLE:
        parts.append("A small sample, so a gap here can easily be chance.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# the pieces
# ---------------------------------------------------------------------------

def _header(summary, settled_rows: list, basis: str, units_each: list) -> dict:
    rec = summary.record
    wins = sum(1 for r in settled_rows if r.result == "win")
    losses = sum(1 for r in settled_rows if r.result == "loss")
    pushes = sum(1 for r in settled_rows if r.result == "push")
    n = wins + losses + pushes
    units = round(sum(units_each), 2)
    roi = round(units / n * 100.0, 1) if n else None
    clv = summary.clv
    streak = (summary.form or {}).get("streak")
    return {"wins": wins, "losses": losses, "pushes": pushes, "settled": n, "units": units, "units_basis": basis,
            "roi_pct": roi,
            "roi_note": "Paper units won or lost per settled bet, as a percent of one flat unit staked.",
            "clv": ({"n": clv.n, "mean_pts": clv.mean_pts} if clv is not None and clv.n and clv.mean_pts is not None else None),
            "streak": ({"kind": streak.get("kind"), "length": streak.get("length")} if isinstance(streak, dict) else None),
            "small_sample": n < SMALL_SAMPLE,
            "sample_note": (f"Only {_bets_word(n)} settled so far, too few to read much into the record." if n < SMALL_SAMPLE else ""),
            "last10": (summary.form or {}).get("last10") or [],
            "record_text": f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")}


def _curve(settled_rows: list, units_each: list) -> list:
    """Cumulative paper units after each slate day (oldest first), starting at zero."""
    by_day: dict = {}
    for r, u in zip(settled_rows, units_each):
        by_day[r.date] = by_day.get(r.date, 0.0) + u
    out, run = [], 0.0
    for day in sorted(by_day):
        run += by_day[day]
        out.append({"date": day, "units": round(run, 2)})
    return out


def _calendar(settled_rows: list, units_each: list) -> list:
    by_day: dict = {}
    for r, u in zip(settled_rows, units_each):
        d = by_day.setdefault(r.date, {"date": r.date, "wins": 0, "losses": 0, "pushes": 0, "units": 0.0})
        d["wins" if r.result == "win" else "losses" if r.result == "loss" else "pushes"] += 1
        d["units"] += u
    days = []
    for day in sorted(by_day)[-CALENDAR_CAP:]:
        d = by_day[day]
        d["units"] = round(d["units"], 2)
        d["result"] = "win" if d["units"] > 0 else "loss" if d["units"] < 0 else "flat"
        days.append(d)
    return days


def _ticket(r: BetRow, units: Optional[float], status: str) -> dict:
    return {"date": r.date, "game": r.game, "selection": r.selection, "market": r.market, "sport": r.sport, "price": r.price,
            "price_average": r.price_average, "line": r.line, "result": r.result, "units": units, "reason": r.reason or "",
            "start_utc": r.start_utc, "recorded_utc": r.recorded_utc, "clv_pts": r.clv_pts, "beyond_cap": bool(r.beyond_cap),
            "status": status, "book": r.book}


def _breakdowns(table: dict) -> list:
    by_group: dict = {}
    for f in table["rows"]:
        if f["kind"] in ("segment", "whole"):
            by_group.setdefault(f["group"], []).append(f)
    out = []
    for gid, title, noun, keep in GROUP_PLAN:
        cuts = [f for f in by_group.get(gid, ()) if keep is None or str(f["id"]).split(":", 1)[1] in keep]
        rows = [_cut_row(f) for f in cuts]
        out.append({"group": gid, "title": title, "rows": rows, "line": plain_line(rows, noun),
                    "thin_rows": sum(1 for r in rows if r["thin"])})
    return out


def build(data: "stats.HoundData", *, as_of: Optional[str] = None, season: Optional[dict] = None,
          compare: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """The track-record payload for one hound's view (``HoundData.view(season)``)."""
    now = now or datetime.now(timezone.utc)
    summary = data.summary
    basis = summary.spark_basis or "recorded_price"
    forward = [b for b in data.bets if b.segment == "forward"]                       # replay (hindsight) never enters
    settled = sorted((b for b in forward if b.result in SETTLED), key=lambda b: (b.date or "", b.recorded_utc or b.start_utc or ""))
    default_sport = summary.sports[0] if isinstance(summary.sports, list) and len(summary.sports) == 1 else None
    bets = _as_bets(settled, basis, default_sport)
    units_each = [_units(b, basis) for b in bets]
    table = diagnosis.diagnose(bets, {})
    header = _header(summary, settled, basis, units_each)

    newest = list(reversed(list(zip(settled, units_each))))
    tickets = [_ticket(r, u, TICKET_GRADED) for r, u in newest[:TICKET_CAP]]
    open_rows, waiting_rows = [], []
    for r in sorted((b for b in forward if b.result is None), key=lambda b: (b.start_utc or b.date or "")):
        status = ticket_status(r.result, r.start_utc, r.date, now)
        (open_rows if status == TICKET_OPEN else waiting_rows).append(_ticket(r, None, status))
    return envelope({
        "hound": {"id": summary.id, "name": summary.name, "kind": summary.kind, "sports": summary.sports,
                  "status": summary.status, "tagline": summary.tagline, "rule_text": summary.rule_text,
                  "is_house": summary.kind == KIND_HOUSE},
        "season": season, "as_of": as_of,
        "header": header,
        "curve": _curve(settled, units_each),
        "bankroll": summary.bankroll,
        "breakdowns": _breakdowns(table),
        "diagnosis_note": table["meta"]["note"],
        "calendar": _calendar(settled, units_each),
        "tickets": tickets, "tickets_total": len(settled), "tickets_shown": len(tickets),
        "open": open_rows[:OPEN_CAP], "open_total": len(open_rows),
        "waiting": waiting_rows[:OPEN_CAP], "waiting_total": len(waiting_rows),
        "compare": compare,
        "hindsight_note": HINDSIGHT_NOTE, "units_note": UNITS_NOTE,
    })


# ---------------------------------------------------------------------------
# compare: this hound against the house pack and the whole leaderboard, the same period
# ---------------------------------------------------------------------------

def _line_of(summary) -> Optional[dict]:
    rec = summary.record
    n = rec.wins + rec.losses + rec.pushes
    if n <= 0:
        return None
    units = rec.units_average_price if rec.units_average_price is not None else rec.units_recorded_price
    decided = rec.wins + rec.losses
    return {"n": n, "units": units, "roi_pct": round(units / n * 100.0, 1),
            "win_pct": round(rec.wins / decided * 100.0, 1) if decided else None,
            "clv": summary.clv.mean_pts if summary.clv is not None and summary.clv.n else None}


def _mean(xs: Sequence) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _group(lines: Sequence[dict]) -> Optional[dict]:
    if len(lines) < COMPARE_MIN_HOUNDS:
        return None
    return {"hounds": len(lines), "bets": sum(x["n"] for x in lines), "roi_pct": _mean(x["roi_pct"] for x in lines),
            "win_pct": _mean(x["win_pct"] for x in lines), "clv": _mean(x["clv"] for x in lines)}


def compare_block(summaries: Sequence, hound_id: str, mine: Optional[dict], season: Optional[dict]) -> Optional[dict]:
    """``summaries`` are the same season's view of every hound in the book. The hound itself is left out of both averages.
    Each average is the plain mean of the hounds' own figures (a hound with one bet counts as much as one with two hundred, and
    the block says how many hounds and bets are behind it). None when no other hound has settled a bet."""
    others = [(s, _line_of(s)) for s in summaries if s.id != hound_id]
    others = [(s, ln) for s, ln in others if ln is not None]
    pack = _group([ln for s, ln in others if s.kind == KIND_HOUSE])
    board = _group([ln for _s, ln in others])
    if pack is None and board is None:
        return None
    return {"period": (season or {}).get("label") or "All-time", "mine": mine, "house_pack": pack, "leaderboard": board,
            "note": "Each average is across hounds, over the same period. Hounds with few bets move it a lot."}


def mine_line(data: "stats.HoundData") -> Optional[dict]:
    return _line_of(data.summary)


__all__ = ["build", "compare_block", "mine_line", "plain_line", "infer_side", "to_json"]
