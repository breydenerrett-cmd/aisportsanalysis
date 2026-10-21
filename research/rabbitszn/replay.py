"""Replay the Gematria Hound's engine over the documented RabbitSZN games. DIAGNOSTICS ONLY, AND IN-SAMPLE.

    python research/rabbitszn/replay.py                 # table of every documented moneyline game the engine can place
    python research/rabbitszn/replay.py --csv out.csv   # the same rows as a CSV
    python research/rabbitszn/replay.py --json          # machine-readable, with the evidence

WHAT THIS IS NOT. It is not a backtest of the hound. The rules (config/gematria/rules_v1.json) were written after reading
these very posts, so every number here is IN-SAMPLE and says nothing about whether the rules work. It exists to answer two
narrow questions: (1) does the engine, run point-in-time on the documented games, land on the same SIDE the poster took,
which tests whether the engine reproduces his method; and (2) what does the record look like on this sample, which is
printed beside the poster's own record on the same games so the two are never confused with a result for the hound. The
hound's real record starts with its first forward pick.

POINT-IN-TIME. Each game is weighed with the same code the hound runs at the lock (``runtime.GematriaRuntime.weigh``): the
history is cut at lock - 6 hours, the lock being an hour before the game's start, so nothing played that day or later enters.
The start time is the game's real start when ``--starts`` knows it, else a stated default per sport (``DEFAULT_START_UTC``).
No board is replayed (we hold none for these games), so the PRICE band is not applied; a synthetic even board stands in and
the table says "price not applied". The -200 cap still shows: a documented pick priced -200 or worse is flagged, because the
hound may never output it.

NEVER READ: MLB outcomes dated 2026-01-01..2026-08-27 (``base.read_mlb_results`` drops them unread).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.hounds.gematria import facts as facts_mod                  # noqa: E402
from src.hounds.gematria import history, rules as rules_mod, runtime as rt     # noqa: E402
from src.hounds.pack import base                                    # noqa: E402
from src.research import gematria as g                              # noqa: E402

HERE = Path(__file__).resolve().parent
SPORT_ROW = {"NFL": "nfl", "CFB": "ncaaf", "NBA": "nba", "MLB": "mlb", "WNBA": "wnba", "NHL": "nhl"}
DEFAULT_START_UTC = {"nfl": "17:00", "ncaaf": "19:00", "nba": "23:00", "mlb": "23:00", "wnba": "23:00", "nhl": "23:00"}
EVEN_BOARD = {"markets": {"moneyline": {"line": None, "books": 5, "sides": {
    "home": {"price_average": -110, "price_best": -105, "book": "none", "book_count": 5, "fair": 0.5},
    "away": {"price_average": -110, "price_best": -105, "book": "none", "book_count": 5, "fair": 0.5}}}}}

# Short names the ledger uses -> the names the stored results and the facts use. Ambiguous ones (Washington, Indiana) need this.
ALIASES = {
    "ncaaf": {"washington": "Washington Huskies", "purdue": "Purdue Boilermakers", "app state": "App State Mountaineers",
              "appalachian state": "App State Mountaineers", "coastal carolina": "Coastal Carolina Chanticleers",
              "ohio state": "Ohio State Buckeyes", "indiana": "Indiana Hoosiers", "mississippi state": "Mississippi State Bulldogs",
              "msst": "Mississippi State Bulldogs", "lsu": "LSU Tigers", "cincinnati": "Cincinnati Bearcats",
              "west virginia": "West Virginia Mountaineers", "wisconsin": "Wisconsin Badgers", "ucla": "UCLA Bruins",
              "georgia southern": "Georgia Southern Eagles", "ga southern": "Georgia Southern Eagles",
              "old dominion": "Old Dominion Monarchs", "south alabama": "South Alabama Jaguars",
              "marshall": "Marshall Thundering Herd"},
}


def resolve_team(book: facts_mod.FactsBook, sport: str, text: str) -> Optional[str]:
    """The stored-results name for a ledger team name, or None when it cannot be placed unambiguously."""
    t = (text or "").strip()
    if not t:
        return None
    if t.lower() in ALIASES.get(sport, {}):
        return ALIASES[sport][t.lower()]
    teams = [e for e in (book.data.get("teams") or {}).values() if e.get("sport") == sport]
    key = g.normalize(t)
    exact = [e["name"] for e in teams if g.normalize(e["name"]) == key]
    if len(exact) == 1:
        return exact[0]
    loose = [e["name"] for e in teams if g.normalize(e["name"]).startswith(key) or g.normalize(e["name"]).endswith(key)
             or g.normalize((e.get("mascot") or {}).get("value", "")) == key]
    return loose[0] if len(loose) == 1 else None


def make_context(sport: str, day: str, away: str, home: str, start_utc: Optional[str], nfl_rows: list, mlb_rows: list) -> base.Context:
    hh = start_utc or DEFAULT_START_UTC.get(sport, "18:00")
    start = (datetime.fromisoformat(f"{day}T{hh}:00+00:00") if "T" not in hh else base.parse_utc(hh))
    lock = start - timedelta(minutes=base.LOCK_MINUTES)
    ctx = base.Context(sport=sport, event_id=f"replay:{day}:{away}:{home}", date=base.eastern_date(start), start=start, lock=lock,
                       away_name=away, home_name=home, away=None, home=None)
    cutoff = lock - history.FINISH_LAG
    ev = {"away_name": away, "home_name": home}
    if sport == "nfl":
        ctx.away, ctx.home = base.nfl_codes(ev)
        ctx.nfl_games = [r for r in nfl_rows if r.get("status") == "final"
                         and (base.parse_utc(r.get("kickoff_utc")) or lock) <= cutoff]
    elif sport == "mlb":
        ctx.away, ctx.home = base.mlb_codes(ev)
        ctx.mlb_games = [x for x in mlb_rows if x["date"] < ctx.date]
    return ctx


def load_rows(path: Path) -> List[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def replay(ledger_rows: List[dict], starts: Dict[str, str]) -> List[dict]:
    rules = rules_mod.load()
    book = facts_mod.load()
    runtime = rt.GematriaRuntime(rules=rules, facts=book, ledger=None)
    nfl_rows = base.read_nfl_games(str(ROOT / "data" / "datasvc" / "nfl" / "games.jsonl"))
    mlb_rows = base.read_mlb_results(str(ROOT / "data" / "historical" / "mlb_results.csv"))
    out = []
    for r in ledger_rows:
        if r.get("market") not in ("ML", "lean", "conditional") or r.get("side") not in ("home", "away"):
            continue
        sport = SPORT_ROW.get(r["sport"])
        row = {"pick_id": r["pick_id"], "date": r["post_date"], "sport": r["sport"], "matchup": f'{r["away"]} @ {r["home"]}',
               "his_selection": r["selection"], "his_side": r["side"], "his_price": r.get("price_selected"),
               "his_result": r.get("result", ""), "pick_strength": r.get("pick_strength"), "our": "", "code": "",
               "scores": "", "margin": "", "comparisons": "", "agrees": "", "note": ""}
        if not sport or not r["away"] or not r["home"]:
            row.update(our="n/a", code="not_placed", note="venue or sport not known from the posts")
            out.append(row)
            continue
        away, home = resolve_team(book, sport, r["away"]), resolve_team(book, sport, r["home"])
        if not away or not home:
            row.update(our="n/a", code="not_placed", note="team name not matched to the stored results")
            out.append(row)
            continue
        ctx = make_context(sport, r["post_date"], away, home, starts.get(r["pick_id"]), nfl_rows, mlb_rows)
        w = runtime.weigh(ctx, EVEN_BOARD)
        v = w.verdict
        row.update(code=v.code, note="price not applied")
        if w.block:
            row.update(scores=f'{w.block["scores"]["home"]:g}-{w.block["scores"]["away"]:g} (home-away)',
                       margin=f"{v.margin:+g}", comparisons=w.block["search_space"])
        if v.is_bet:
            row.update(our=v.side, agrees="yes" if v.side == r["side"] else "no")
        else:
            row.update(our="PASS")
        try:
            if r.get("price_selected") and int(r["price_selected"]) <= -200:
                row["note"] += "; his price is -200 or worse: the hound may never output it"
        except ValueError:
            pass
        if w.block:
            row["evidence"] = w.block["evidence"]
        out.append(row)
    return out


def summarise(rows: List[dict]) -> dict:
    placed = [r for r in rows if r["code"] != "not_placed"]
    picks = [r for r in placed if r["our"] in ("home", "away")]
    both = [r for r in picks if r["his_side"] in ("home", "away")]
    agree = [r for r in both if r["agrees"] == "yes"]
    wl = {"W": 0, "L": 0, "n/a": 0}
    for r in picks:
        res = (r.get("his_result") or "").upper()
        if res not in ("WIN", "LOSS"):
            wl["n/a"] += 1
        else:
            # a moneyline has two outcomes: when the engine took his side it shares his result, else the opposite one
            same = r["agrees"] == "yes"
            wl["W" if ((res == "WIN") == same) else "L"] += 1
    his = {"W": sum(1 for r in placed if (r.get("his_result") or "").upper() == "WIN"),
           "L": sum(1 for r in placed if (r.get("his_result") or "").upper() == "LOSS")}
    return {"documented_ml_rows": len(rows), "placed": len(placed), "engine_picks": len(picks), "engine_passes": len(placed) - len(picks),
            "same_side_as_him": len(agree), "agreement_rate": round(len(agree) / len(picks), 3) if picks else None,
            "engine_record_in_sample": wl, "his_record_on_placed_games": his,
            "pass_reasons": {c: sum(1 for r in placed if r["code"] == c) for c in sorted({r["code"] for r in placed})}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=Path, default=HERE / "ledger.csv")
    ap.add_argument("--starts", type=Path, default=HERE / "starts.json", help="optional {pick_id: ISO start time}")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    starts = json.loads(args.starts.read_text(encoding="utf-8")) if args.starts.exists() else {}
    rows = replay(load_rows(args.ledger), starts)
    summary = summarise(rows)
    if args.json:
        print(json.dumps({"rows": rows, "summary": summary, "label": "IN-SAMPLE DIAGNOSTIC; not a result for the hound"}, indent=1, default=str))
        return 0
    cols = ["pick_id", "date", "sport", "matchup", "his_selection", "his_price", "his_result", "our", "margin", "scores", "comparisons",
            "code", "agrees"]
    if args.csv:
        with args.csv.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols + ["pick_strength", "his_side", "note"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    print("IN-SAMPLE DIAGNOSTIC: the rules were written after reading these posts. Not a result for the hound.\n")
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    print("\n" + json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
