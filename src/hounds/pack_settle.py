"""Settle the house pack: grade each bet from the results stores, with its closing price and CLV.

    python -m src.hounds.pack_settle             # grade every ungraded bet that can be graded
    python -m src.hounds.pack_settle --report    # print the per-hound table (markdown)

GRADES
------
MLB from the results store (`data/historical/mlb_results.csv`, rows inside the SEALED window
dropped unread), falling back to the box-score store summed per side for a game the results store
never fetched (accepted only with 24+ outs per side). NFL from `data/datasvc/nfl/games.jsonl` rows
with status `final`.

WIN / LOSS / PUSH (landed on the line) / VOID / UNRESOLVED (a result row with no usable score; it
is replaced when a later run finds the score).

PENDING MAKEUP
--------------
No result yet: the bet stays pending (no graded row) for 4 days after its start. A result whose
start is more than 36 hours after the bet's start (played as a makeup) grades VOID; still no result
4 days after the start grades VOID. A makeup is a new odds event and gets its own bets.

CLOSE AND CLV
-------------
The close is the board at the instant just before the start, on the bet's own line.
`clv_pts = 100 x (close consensus fair - break-even of price_average)`; null with no close on
that line. Units at the board-average price (the owner's grading ruling) and at the best price.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import pack as pack_mod
from src.hounds.pack import base
from src.hounds.pack_run import KIND_BET, KIND_GRADED, ledger_path
from src.ledger.chain import HashChainLedger

PENDING_DAYS = 4
MAKEUP_HOURS = 36
FINAL = ("WIN", "LOSS", "PUSH", "VOID")


def _key(row: Mapping) -> tuple:
    return row["hound_id"], row["event_id"], row["market"], row["selection"]


def mlb_results_index(stores: base.Stores) -> dict:
    out: dict = {}
    for g in stores.mlb_games:
        out.setdefault(str(g["game_pk"]), g)
    return out


def nfl_results_index(stores: base.Stores) -> dict:
    return {g.get("game_id"): g for g in stores.nfl_games}


def grade_score(market: str, side: str, market_line: Optional[float], away: int, home: int) -> str:
    if market == "moneyline":
        if home == away:
            return "PUSH"
        return "WIN" if (home > away) == (side == "home") else "LOSS"
    if market == "spread":
        diff = home + market_line - away          # home cover margin
        if diff == 0:
            return "PUSH"
        return "WIN" if (diff > 0) == (side == "home") else "LOSS"
    total = home + away
    if total == market_line:
        return "PUSH"
    return "WIN" if (total > market_line) == (side == "over") else "LOSS"


def find_result(bet: Mapping, mlb: Mapping, nfl: Mapping) -> tuple:
    """(result row normalised to {away_score, home_score, start, date, source} or None, raw found?)."""
    if bet["sport"] == "mlb":
        g = mlb.get(str(bet.get("game_pk")))
        if g is None:
            return None, False
        return {"away_score": g.get("away_score"), "home_score": g.get("home_score"),
                "start": base.parse_utc(g.get("start_utc")), "date": g.get("date"),
                "source": g.get("source", "results")}, True
    g = nfl.get(bet.get("nfl_game_id"))
    if g is None or g.get("status") != "final":
        return None, False
    return {"away_score": g.get("away_score"), "home_score": g.get("home_score"),
            "start": base.parse_utc(g.get("kickoff_utc")), "date": g.get("gameday"),
            "source": "nfl_games"}, True


def close_of(stores: base.Stores, bet: Mapping) -> Optional[dict]:
    start = base.parse_utc(bet["start_utc"])
    quotes = stores.quotes_by_event.get(bet["event_id"]) or []
    return base.board_at_line(quotes, at=start, start=start, sport=bet["sport"], market=bet["market"],
                              line=bet.get("market_line"))


def grade_bet(bet: Mapping, stores: base.Stores, mlb: Mapping, nfl: Mapping, *, now: datetime) -> Optional[dict]:
    start = base.parse_utc(bet["start_utc"])
    res, _ = find_result(bet, mlb, nfl)
    result, note = None, None
    if res is None:
        if now < start + timedelta(days=PENDING_DAYS):
            return None                       # pending makeup / not yet final
        result, note = "VOID", f"no result {PENDING_DAYS} days after the start"
    else:
        moved = False
        if res["start"] is not None:
            moved = res["start"] - start > timedelta(hours=MAKEUP_HOURS)
        elif res.get("date"):
            moved = (date.fromisoformat(res["date"]) - date.fromisoformat(bet["date"])).days >= 2
        if moved:
            result, note = "VOID", "played as a makeup more than 36 hours after the bet's start"
        elif res["away_score"] is None or res["home_score"] is None:
            result, note = "UNRESOLVED", "result row has no score"
        else:
            result = grade_score(bet["market"], bet["side"], bet.get("market_line"),
                                 int(res["away_score"]), int(res["home_score"]))
    stake = float(bet.get("stake") or 1.0)
    close = close_of(stores, bet)
    close_side = close["sides"][bet["side"]] if close else None
    clv = None
    if close_side is not None:
        clv = round(100.0 * (close_side["fair"] - base.break_even(bet["price_average"])), 3)
    return {
        "kind": KIND_GRADED, "pack": pack_mod.PACK_ID, "hound_id": bet["hound_id"], "event_id": bet["event_id"],
        "market": bet["market"], "selection": bet["selection"], "side": bet["side"], "date": bet["date"],
        "sport": bet["sport"], "segment": bet.get("segment"), "bet_row_hash": bet.get("row_hash"),
        "result": result, "note": note, "stake": stake,
        "units_average_price": base.units_for(result, bet["price_average"], stake) if result != "UNRESOLVED" else None,
        "units_best_price": base.units_for(result, bet["price_best"], stake) if result != "UNRESOLVED" else None,
        "close_price": close_side["price_average"] if close_side else None,
        "close_fair": close_side["fair"] if close_side else None,
        "close_books": close["books"] if close else None,
        "clv_pts": clv,
        "final_score": ({"away": res["away_score"], "home": res["home_score"]} if res else None),
        "result_source": res["source"] if res else None,
        "graded_utc": base.iso(now),
    }


def settle(stores: base.Stores, *, now: datetime, path: Optional[str] = None) -> dict:
    led = HashChainLedger(ledger_path(path))
    rows = led.read()
    graded: dict = {}
    for r in rows:
        if r.get("kind") == KIND_GRADED:
            graded[_key(r)] = r
    mlb, nfl = mlb_results_index(stores), nfl_results_index(stores)
    counts = {"graded": 0, "pending": 0, "already": 0}
    for bet in rows:
        if bet.get("kind") != KIND_BET:
            continue
        prior = graded.get(_key(bet))
        if prior is not None and prior.get("result") in FINAL:
            counts["already"] += 1
            continue
        g = grade_bet(bet, stores, mlb, nfl, now=now)
        if g is None:
            counts["pending"] += 1
            continue
        if prior is not None and prior.get("result") == g["result"]:
            counts["already"] += 1
            continue
        led.append(g)
        graded[_key(bet)] = g
        counts["graded"] += 1
    return counts


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------

_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
         10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000}


def t975(df: int) -> float:
    if df <= 0:
        return float("nan")
    keys = sorted(_T975)
    for k in keys:
        if df <= k:
            return _T975[k]
    return 1.96


def clustered_ci(values: Sequence[tuple]) -> tuple:
    """values: (cluster, x). Mean and a cluster-robust 95% interval (t with G-1 df); None if G < 2."""
    if not values:
        return None, None, None, 0
    n = len(values)
    mean = sum(x for _, x in values) / n
    clusters: dict = {}
    for c, x in values:
        clusters.setdefault(c, []).append(x)
    g = len(clusters)
    if g < 2:
        return mean, None, None, g
    s = sum((sum(xs) - len(xs) * mean) ** 2 for xs in clusters.values())
    se = math.sqrt(g / (g - 1) * s) / n
    t = t975(g - 1)
    return mean, mean - t * se, mean + t * se, g


def summary(rows: Sequence[Mapping], *, segment: Optional[str] = None) -> list:
    bets = [r for r in rows if r.get("kind") == KIND_BET and (segment is None or r.get("segment") == segment)]
    graded: dict = {}
    for r in rows:
        if r.get("kind") == KIND_GRADED:
            graded[_key(r)] = r
    out = []
    for hound in pack_mod.PACK:
        hb = [b for b in bets if b["hound_id"] == hound.id]
        rec = {"W": 0, "L": 0, "P": 0, "V": 0, "U": 0, "pending": 0}
        units = 0.0
        units_best = 0.0
        staked = 0.0
        clv = []
        for b in hb:
            g = graded.get(_key(b))
            if g is None:
                rec["pending"] += 1
                continue
            letter = {"WIN": "W", "LOSS": "L", "PUSH": "P", "VOID": "V", "UNRESOLVED": "U"}[g["result"]]
            rec[letter] += 1
            if g["result"] in ("WIN", "LOSS", "PUSH"):
                units += g["units_average_price"] or 0.0
                units_best += g["units_best_price"] or 0.0
                staked += float(g.get("stake") or 1.0)
                if g.get("clv_pts") is not None:
                    clv.append((b["date"], g["clv_pts"]))
        mean, lo, hi, days = clustered_ci(clv)
        out.append({"hound_id": hound.id, "name": hound.name, "category": hound.category, "bets": len(hb),
                    "record": rec, "units_average_price": round(units, 2), "units_best_price": round(units_best, 2),
                    "staked": round(staked, 2), "clv_n": len(clv), "clv_mean": mean, "clv_lo": lo, "clv_hi": hi,
                    "clv_days": days})
    return out


def _f(x: Optional[float], fmt: str = "{:+.2f}") -> str:
    return "n/a" if x is None else fmt.format(x)


def render_table(summ: Sequence[Mapping]) -> list:
    lines = ["| Hound | Category | Bets | W-L-P (void) | Units @ avg | Units @ best | CLV mean (pts) | 95% CI (date-clustered) | Days |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in summ:
        r = s["record"]
        rec = f"{r['W']}-{r['L']}-{r['P']} ({r['V']})" + (f", {r['pending']} pending" if r["pending"] else "")
        ci = "n/a" if s["clv_lo"] is None else f"{s['clv_lo']:+.2f} to {s['clv_hi']:+.2f}"
        lines.append(f"| {s['name']} | {s['category']} | {s['bets']} | {rec} | {_f(s['units_average_price'])} | "
                     f"{_f(s['units_best_price'])} | {_f(s['clv_mean'])} | {ci} | {s['clv_days']} |")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.pack_settle", description=__doc__.splitlines()[0])
    ap.add_argument("--ledger")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--segment", choices=("replay", "forward"))
    args = ap.parse_args(argv)
    led = HashChainLedger(ledger_path(args.ledger))
    if args.report:
        for line in render_table(summary(led.read(), segment=args.segment)):
            print(line)
        return 0
    bets = [r for r in led.read() if r.get("kind") == KIND_BET]
    if not bets:
        print("no bets to settle")
        return 0
    first = min(b["date"] for b in bets)
    last = max(b["date"] for b in bets)
    since = max(base.SEAL_FLOOR, base.day_before(first, 8))
    until = (date.fromisoformat(last) + timedelta(days=2)).isoformat()
    stores = base.load_stores(since=since, until=until)
    print(settle(stores, now=datetime.now(timezone.utc), path=args.ledger))
    return 0


if __name__ == "__main__":
    sys.exit(main())
