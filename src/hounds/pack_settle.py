"""Settle the house pack: grade each bet from the results stores, with its closing price and CLV.

    python -m src.hounds.pack_settle             # grade every ungraded bet that can be graded
    python -m src.hounds.pack_settle --report    # print the per-hound table (markdown)

GRADES
------
MLB from the results store (`data/historical/mlb_results.csv`, rows inside the SEALED window
dropped unread), falling back to the box-score store summed per side for a game the results store
never fetched (accepted only with 24+ outs per side). NFL from `data/datasvc/nfl/games.jsonl` rows
with status `final`.

EVERY OTHER FAMILY (the AI hounds bet the whole dog menu: NBA, NHL, soccer, tennis ...) is graded by
``allsports_scores.grade_bet`` against ``data/processed/allsports_scores.jsonl``, the SAME function and store the
member dogs' ``user_settle`` uses, so a Claude Hound bet and a member dog's bet on one game can never disagree
about who won: a draw LOSES a team moneyline in a three-way family and is a PUSH elsewhere, a cancelled game or one
with no completed score 72 hours after the start is a VOID with the reason named, and tennis and MMA read the free
ESPN results the scores store already holds. The store is read lazily (only when such a bet is owed) and can be
injected as ``Stores.allsports_results``.

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
from src.pipeline import allsports_scores

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


def resolve_pk(bet: Mapping, stores: base.Stores, mlb: Mapping) -> Optional[str]:
    """The game_pk of a bet whose map row was ambiguous (a doubleheader): the k-th odds event of this
    pair on this date (by start) is the game with the k-th game_number among the map's candidates.
    None when the counts disagree or a candidate has no result yet."""
    if bet.get("game_pk"):
        return str(bet["game_pk"])
    m = stores.event_map.get(bet["event_id"])
    cands = [str(c.get("game_pk")) for c in (m or {}).get("candidates") or []]
    if not cands or any(c not in mlb or mlb[c].get("game_number") is None for c in cands):
        return None
    same = []
    for eid, ev in stores.events.items():
        if ev.get("sport") != "mlb":
            continue
        start = base.resolve_start(ev)
        if start is None or base.eastern_date(start) != bet["date"]:
            continue
        if base.mlb_codes(ev) == (bet.get("away_code"), bet.get("home_code")):
            same.append((start, eid))
    same.sort()
    order = sorted(cands, key=lambda c: mlb[c]["game_number"])
    if len(same) != len(order):
        return None
    for (_, eid), pk in zip(same, order):
        if eid == bet["event_id"]:
            return pk
    return None


def find_result(bet: Mapping, mlb: Mapping, nfl: Mapping, stores: Optional[base.Stores] = None) -> tuple:
    """(result row normalised to {away_score, home_score, start, date, source} or None, raw found?)."""
    if bet["sport"] == "mlb":
        pk = resolve_pk(bet, stores, mlb) if stores is not None else bet.get("game_pk")
        g = mlb.get(str(pk)) if pk else None
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


def allsports_index(stores: base.Stores) -> dict:
    """{event_id: score row} for the all-sports families, read once per Stores (or injected on it)."""
    if stores.allsports_results is None:
        stores.allsports_results = allsports_scores.load_index()
    return stores.allsports_results


def grade_allsports(bet: Mapping, stores: base.Stores, *, now: datetime) -> Optional[tuple]:
    """(result, note, res) for a bet on a family outside MLB and NFL, from the member dogs' own grader; None while
    the bet is still pending. ``res`` is shaped like ``find_result``'s so the graded row's shape is the same."""
    row = allsports_index(stores).get(bet["event_id"])
    graded = allsports_scores.grade_bet(bet, row, now)
    if graded["result"] is None:
        return None
    away, home = graded.get("away_score"), graded.get("home_score")
    res = None
    if away is not None and home is not None:
        res = {"away_score": away, "home_score": home, "source": (row or {}).get("source") or "allsports_scores"}
    return graded["result"], graded.get("reason"), res


def grade_bet(bet: Mapping, stores: base.Stores, mlb: Mapping, nfl: Mapping, *, now: datetime) -> Optional[dict]:
    start = base.parse_utc(bet["start_utc"])
    result, note = None, None
    if bet["sport"] not in ("mlb", "nfl"):
        out = grade_allsports(bet, stores, now=now)
        if out is None:
            return None                       # no completed score yet, inside the 72-hour wait
        result, note, res = out
    else:
        res, _ = find_result(bet, mlb, nfl, stores)
    if result is not None:
        pass                                  # graded above by the member dogs' grader
    elif res is None:
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
        "game_pk": (resolve_pk(bet, stores, mlb) if bet["sport"] == "mlb" else None),
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
        # A final grade stands, except a VOID for "no result" when a result has since appeared (a
        # backfilled store, a doubleheader matched later): that is re-graded and the new row names
        # the row it corrects. The ledger is append-only; the newest graded row counts.
        late_void = (prior is not None and prior.get("result") == "VOID"
                     and str(prior.get("note") or "").startswith("no result"))
        if prior is not None and prior.get("result") in FINAL and not late_void:
            counts["already"] += 1
            continue
        g = grade_bet(bet, stores, mlb, nfl, now=now)
        if g is None:
            counts["pending"] += 1
            continue
        if prior is not None and (prior.get("result"), prior.get("note")) == (g["result"], g["note"]):
            counts["already"] += 1
            continue
        if prior is not None:
            g["corrects"] = prior.get("row_hash")
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
    # A ledger that holds AI bets on other families needs those families' boards for the close and CLV.
    sports = sorted({b["sport"] for b in bets} | set(base.DEFAULT_SPORTS))
    stores = base.load_stores(since=since, until=until, sports=sports)
    print(settle(stores, now=datetime.now(timezone.utc), path=args.ledger))
    return 0


if __name__ == "__main__":
    sys.exit(main())
