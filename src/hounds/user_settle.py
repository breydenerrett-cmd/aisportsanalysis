"""Grade the user hounds' paper bets from the results the cards already use.

SAME RESULTS, SAME RULES
------------------------
A bet is graded by the card ledger's own `grade_pick` / `grade_total_pick` against the MLB results
store (`src.pipeline.history.read_results`, keyed by game_pk) or the NFL scores
(`src.pipeline.nfl_slate`), so a hound and a card can never disagree about who won a game. This
module imports the card ledger to call it and never writes to it.

TWO PRICES, ONE GRADE
---------------------
`profit_units` is the profit of one unit at the bet's AVERAGE price (the headline: owner ruling
2026-09-21). `profit_units_best` is the same result at the best single price recorded. Both are
paper arithmetic, not a claim that anyone staked anything.

WHAT IS WRITTEN, AND WHAT IS NOT
--------------------------------
Only a SETTLED bet gets a row: WIN, LOSS, PUSH or VOID. A game with no final score yet writes
nothing, so a rain-out never looks like a bad night and the ledger stays small. One graded row per
bet, ever; a rerun adds nothing.

POSTPONED GAMES: "PENDING MAKEUP"
---------------------------------
Same standing policy as `src/engine/settle_slate.py` (tests/test_postponed_game_settle.py): a game
Postponed and made up under the SAME game_pk is pending, reported with its makeup date, never an
error, and settled once from that final when the results store has it. `postponed_lookup` is the
injection point (production passes `history.postponed_makeup`, which asks the schedule; a lookup
that fails or answers nothing is never read as "pending"). A VOID follows the existing contract:
`result["void"]` truthy on the result mapping, or an unusable price.

CLI:  python -m src.hounds.user_settle run [--recent DAYS] [--ledger PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional, Sequence

from src.appstate import card_ledger
from src.core import odds as odds_math
from src.hounds import user_engine
from src.ledger.chain import HashChainLedger

KIND_GRADED = "hound_user_graded"
DEFAULT_LOOKBACK_DAYS = 14

SETTLED = (card_ledger.RESULT_WIN, card_ledger.RESULT_LOSS, card_ledger.RESULT_PUSH,
           card_ledger.RESULT_VOID)


def _profit_at(result: str, price) -> Optional[float]:
    if result == card_ledger.RESULT_WIN:
        try:
            return round(odds_math.american_to_decimal(price) - 1.0, 4)
        except (odds_math.OddsError, TypeError, ValueError):
            return None
    if result == card_ledger.RESULT_LOSS:
        return -1.0
    return 0.0


def _resolve_mlb_result(bet: Mapping, results: Mapping, index: Optional[Mapping]) -> tuple:
    """(game_pk, result row | None). The bet's own game_pk first, then the event map, then a
    unique (date, away, home) match in the results store. A doubleheader match is ambiguous and
    stays pending: a guess would grade the wrong game."""
    from src.board import gamekey
    pk = bet.get("game_pk")
    if pk is None and index:
        pk = gamekey.game_pk_for_event(bet.get("event_id"), index)
    if pk is not None:
        return str(pk), results.get(str(pk))
    away, home = gamekey._team_key(bet.get("away_team")), gamekey._team_key(bet.get("home_team"))
    if away is None or home is None:
        return None, None
    hits = [(k, r) for k, r in results.items()
            if r.get("date") == bet.get("slate_date") and r.get("away_team") == away
            and r.get("home_team") == home]
    if len(hits) == 1:
        return str(hits[0][0]), hits[0][1]
    return None, None


def _pick_for(bet: Mapping, identity) -> dict:
    market = bet["market"]
    pick = {"price": bet["price"], "side": bet["side"]}
    if bet["sport"] == "NFL":
        pick.update({"sport": "nfl", "game_id": identity})
    else:
        pick["game_pk"] = identity
    if market == "moneyline":
        pick["market"] = "moneyline"
    elif market == "spread":
        pick.update({"market": "spread" if bet["sport"] == "NFL" else "run_line",
                     "line": bet.get("line")})
    else:
        pick.update({"market": "total", "line": bet.get("line")})
    return pick


def grade_bet(bet: Mapping, result: Mapping, identity) -> dict:
    """One bet against one result mapping -> the card ledger's grade dict."""
    pick = _pick_for(bet, identity)
    if bet["market"] == "total":
        return card_ledger.grade_total_pick(pick, result)
    return card_ledger.grade_pick(pick, result)


def settle(*, ledger: Optional[str] = None, now: Optional[datetime] = None,
           lookback_days: int = DEFAULT_LOOKBACK_DAYS,
           mlb_results: Optional[Mapping] = None,
           nfl_results: Optional[Callable[[str], Mapping]] = None,
           postponed_lookup: Optional[Callable] = None,
           game_pk_index: Optional[Mapping] = None,
           close_fn: Optional[Callable[[Mapping], Optional[int]]] = None) -> dict:
    """Grade every settled-able ungraded bet from the last `lookback_days`. Returns a report.

    mlb_results: {game_pk: results-store row} (default: the repository store, read once).
    nfl_results: date -> {(away_code, home_code): {'home_score','away_score'}} (default: the NFL
    scores through src.pipeline.nfl_slate; any failure leaves those bets pending).
    postponed_lookup: (game_pk, slate_date) -> history.postponed_makeup-shaped dict or None.
    close_fn: bet -> the board's AVERAGE closing price for the bet's side and line, or None
    (default: read from the captured board; None leaves CLV null, never a guess)."""
    now = now or datetime.now(timezone.utc)
    store = HashChainLedger(user_engine.ledger_path(ledger))
    rows = store.read()
    graded_ids = {r["bet_id"] for r in rows if r.get("kind") == KIND_GRADED}
    cutoff = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    todo = [r for r in rows if r.get("kind") == user_engine.KIND_BET and r["bet_id"] not in graded_ids
            and r["slate_date"] >= cutoff]
    report = {"considered": len(todo), "graded": 0, "pending": 0, "pending_makeup": [],
              "by_result": {}, "paper_only": True}
    if not todo:
        return report

    results = mlb_results
    if results is None and any(b["sport"] == "MLB" for b in todo):
        from src.pipeline import history
        results = history.read_results()
    if game_pk_index is None and any(b["sport"] == "MLB" and b.get("game_pk") is None for b in todo):
        game_pk_index = user_engine._load_game_pk_index()
    nfl_cache: dict = {}
    close_fn = close_fn or make_close_fn()

    for bet in sorted(todo, key=lambda b: (b["slate_date"], b["bet_id"])):
        start = user_engine._utc(bet["commence_time"])
        if start is not None and start > now:
            report["pending"] += 1
            continue
        result = None
        identity = None
        if bet["sport"] == "MLB":
            identity, result = _resolve_mlb_result(bet, results or {}, game_pk_index)
        else:
            from src.sports import nfl_teams
            date = bet["slate_date"]
            if date not in nfl_cache:
                try:
                    fetch = nfl_results or default_nfl_results
                    nfl_cache[date] = fetch(date) or {}
                except Exception as exc:  # noqa: BLE001 -- no scores yet is pending, not an error
                    print(f"hounds settle: NFL scores for {date} unavailable: {exc!r}",
                          file=sys.stderr)
                    nfl_cache[date] = {}
            key = (nfl_teams.abbrev(bet.get("away_team")), nfl_teams.abbrev(bet.get("home_team")))
            result = nfl_cache[date].get(key)
            identity = bet["event_id"]
        if result is None:
            if (bet["sport"] == "MLB" and identity is not None and postponed_lookup is not None
                    and start is not None and now - start > timedelta(hours=18)):
                try:
                    info = postponed_lookup(identity, bet["slate_date"])
                except Exception:  # noqa: BLE001 -- an unanswered lookup is never "pending"
                    info = None
                if info and info.get("status") == "pending_makeup":
                    report["pending_makeup"].append(
                        {"bet_id": bet["bet_id"], "game_pk": identity,
                         "makeup_date": info.get("makeup_date")})
            report["pending"] += 1
            continue
        graded = grade_bet(bet, result, identity)
        outcome = graded["result"]
        if outcome not in SETTLED:
            report["pending"] += 1
            continue
        try:
            close = close_fn(bet)
        except Exception as exc:  # noqa: BLE001 -- no close price leaves CLV null
            print(f"hounds settle: close price unavailable for {bet['bet_id']}: {exc!r}",
                  file=sys.stderr)
            close = None
        row = {
            "kind": KIND_GRADED, "ledger_version": user_engine.LEDGER_VERSION, "paper_only": True,
            "bet_id": bet["bet_id"], "hound_id": bet["hound_id"], "result": outcome,
            "profit_units": _profit_at(outcome, bet["price"]),
            "profit_units_best": _profit_at(outcome, bet["best_price"]),
            "away_score": graded.get("away_score"), "home_score": graded.get("home_score"),
            "reason": graded.get("reason"), "close_price": close,
            "clv_pts": clv_points(bet["price"], close), "graded_utc": user_engine._iso(now),
            "slate_date": bet["slate_date"],
        }
        store.append(row)
        report["graded"] += 1
        report["by_result"][outcome] = report["by_result"].get(outcome, 0) + 1
    return report


# ---------------------------------------------------------------------------
# closing price and CLV
# ---------------------------------------------------------------------------

def clv_points(bet_price, close_price) -> Optional[float]:
    """Closing-line value in percentage points of implied probability: positive when the price the
    hound was graded at is LONGER than the average close for the same side (the market later
    agreed with it). Both prices are board averages, so their vig is comparable and cancels."""
    if bet_price is None or close_price is None:
        return None
    try:
        p_bet = 1.0 / odds_math.american_to_decimal(bet_price)
        p_close = 1.0 / odds_math.american_to_decimal(close_price)
    except (odds_math.OddsError, TypeError, ValueError):
        return None
    return round((p_close - p_bet) * 100.0, 3)


def make_close_fn(rows_for: Optional[Callable[[str, str], list]] = None):
    """Build a `close_fn(bet)`: the average price on the bet's side at the LAST pre-game capture
    of its market, only when the consensus line is the line that was bet (a moved line is a
    different bet, so no CLV is claimed). `rows_for(date, sport)` returns raw board rows; the
    default reads the repository store once per date and sport."""
    cache: dict = {}

    def loader(date: str, sport: str):
        if rows_for is not None:
            return rows_for(date, sport)
        return user_engine.load_rows(date, [sport])

    def close_fn(bet: Mapping) -> Optional[int]:
        key = (bet["slate_date"], bet["sport"])
        if key not in cache:
            cache[key] = user_engine.build_games(loader(*key))
        game = cache[key].get(bet["event_id"])
        if game is None:
            return None
        stamps = sorted(game.captures.get(bet["market"], {}))
        for t in reversed(stamps):
            board = user_engine.build_board(bet["market"], game.captures[bet["market"]][t])
            if board is None:
                continue
            if bet["market"] == "spread":
                own = board["line"] if bet["side"] == "home" else -board["line"]
                if bet.get("line") is None or abs(own - bet["line"]) > 1e-9:
                    return None
            if bet["market"] == "total" and (bet.get("line") is None
                                              or abs(board["line"] - bet["line"]) > 1e-9):
                return None
            return user_engine.average_price([p for _, p in board["sides"][bet["side"]]])
        return None

    return close_fn


# ---------------------------------------------------------------------------
# records, CLV summary, a plain verdict
# ---------------------------------------------------------------------------

MIN_VERDICT_BETS = 30


def clv_summary(values: Sequence[float]) -> Optional[dict]:
    """{n, mean_pts, ci_low, ci_high} (95%, normal approximation), or None with no values. The
    interval needs two or more values; with one it is null rather than a made-up width."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return None
    mean = sum(vals) / n
    if n < 2:
        return {"n": n, "mean_pts": round(mean, 3), "ci_low": None, "ci_high": None}
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    half = 1.96 * (var ** 0.5) / (n ** 0.5)
    return {"n": n, "mean_pts": round(mean, 3), "ci_low": round(mean - half, 3),
            "ci_high": round(mean + half, 3)}


def records_by_hound(rows: Sequence[Mapping]) -> dict:
    """{hound_id: {record, clv, graded, first_bet_utc, last_bet_utc}} from ledger rows.
    `units_average_price` is profit at the graded (average) price; `units_recorded_price` is the
    same results at the best single price recorded beside it."""
    bets: dict = {}
    graded: dict = {}
    for row in rows:
        if row.get("kind") == user_engine.KIND_BET:
            bets[row["bet_id"]] = row
        elif row.get("kind") == KIND_GRADED:
            graded[row["bet_id"]] = row
    out: dict = {}
    for bet in sorted(bets.values(), key=lambda b: (b["recorded_utc"], b["bet_id"])):
        rec = out.setdefault(bet["hound_id"], {
            "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
                       "units_recorded_price": 0.0, "units_average_price": 0.0},
            "first_bet_utc": bet["recorded_utc"], "last_bet_utc": bet["recorded_utc"],
            "clv_values": []})
        r = rec["record"]
        r["bets"] += 1
        rec["last_bet_utc"] = bet["recorded_utc"]
        g = graded.get(bet["bet_id"])
        if g is None:
            continue
        key = {"WIN": "wins", "LOSS": "losses", "PUSH": "pushes", "VOID": "voids"}[g["result"]]
        r[key] += 1
        r["units_average_price"] = round(r["units_average_price"] + (g["profit_units"] or 0.0), 4)
        r["units_recorded_price"] = round(
            r["units_recorded_price"] + (g["profit_units_best"] or 0.0), 4)
        if g.get("clv_pts") is not None:
            rec["clv_values"].append(g["clv_pts"])
    for rec in out.values():
        rec["clv"] = clv_summary(rec.pop("clv_values"))
        r = rec["record"]
        rec["graded"] = r["wins"] + r["losses"] + r["pushes"] + r["voids"]
    return out


def verdict_for(record_entry: Optional[Mapping]) -> dict:
    """A plain, hedged verdict from the closing-line check. The shared verdict module
    (src/hounds/verdict.py, owned by the house-hound worker) supersedes this when it lands; this
    stays honest on its own: it never turns a short record into a claim."""
    graded = (record_entry or {}).get("graded", 0)
    clv = (record_entry or {}).get("clv")
    if graded < MIN_VERDICT_BETS:
        return {"label": "too_early",
                "sentence": f"{graded} graded paper bets so far; it takes {MIN_VERDICT_BETS} before "
                            f"any verdict is shown."}
    if not clv or clv["ci_low"] is None:
        return {"label": "unclear", "sentence": "Enough bets, but no closing prices to check against."}
    if clv["ci_low"] > 0:
        return {"label": "ahead_of_close",
                "sentence": "Its prices have tended to be better than the closing average, "
                            "by more than chance alone would usually give."}
    if clv["ci_high"] < 0:
        return {"label": "behind_close",
                "sentence": "Its prices have tended to be worse than the closing average."}
    return {"label": "unclear",
            "sentence": "Its prices are about level with the closing average; the record cannot "
                        "separate skill from luck yet."}


def default_nfl_results(date: str) -> dict:
    """{(away_code, home_code): {'home_score','away_score'}} for finals on `date`, from the same
    scores the NFL card settles on. Raises if the schedule or scores cannot be fetched."""
    from src.pipeline import nfl_slate
    games = nfl_slate.nfl.schedule_for_date(date)
    by_id = nfl_slate.results_for_date(date, games=games)
    out = {}
    for game in games:
        res = by_id.get(game.get("game_id"))
        if res:
            out[(game.get("away_team"), game.get("home_team"))] = res
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.hounds.user_settle")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--recent", type=int, default=DEFAULT_LOOKBACK_DAYS)
    p_run.add_argument("--ledger")
    args = parser.parse_args(argv)
    from src.pipeline import history
    report = settle(ledger=args.ledger, lookback_days=args.recent,
                    postponed_lookup=lambda pk, day: history.postponed_makeup(pk, day))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
