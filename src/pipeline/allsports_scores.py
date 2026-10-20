"""Results for the all-sports families: The Odds API /scores into an append-only store, and the grader.

WHY THIS EXISTS
---------------
A member dog that bets the NBA, a cricket match or a soccer fixture has to be graded from SOME final score.
MLB and NFL bets are graded from their own results stores; every other family is graded here, from The
Odds API `/scores` (1 credit a call, 2 with `daysFrom`), so the dog's record is settled by the same vendor
that supplied the price.

THE STORE (data/processed/allsports_scores.jsonl, APPEND-ONLY)
---------------------------------------------------------------
Two row kinds, never rewritten, never deduplicated in place:
  score  one row per (event, change of state): the event id, start, teams, `completed`, both scores, the
         vendor's `scores` list verbatim, and `outcome` ("home", "away" or "draw") once both scores exist.
         A new row is appended only when the event's state differs from the last row stored for it.
  poll   one row per paid call: the key, `daysFrom`, how many events came back, the credits.
Every outcome is stored, the draw included; nothing is collapsed to a winner.

WHICH KEYS ARE POLLED, AND WHY NOT "EVERY ACTIVE KEY"
-----------------------------------------------------
The scheduled capture runs on a CI runner that cannot see the hounds ledger (it lives on the API
machine's volume), so it cannot ask "which keys have a pending bet". It asks the capture done store
instead: a key is polled when it has captured events that started at least an hour ago, inside the
`daysFrom` window, with no completed result stored yet, and was last polled at least
`scores_poll_interval_hours` ago. That bounds the spend to the keys that actually had games, at about
2 credits a poll, under their own sub-cap in the all-sports band.

GRADING (`grade_bet`)
---------------------
 * moneyline: the side with the higher score wins. A LEVEL score is a DRAW. Where the family's team
   moneyline is a three-way market (soccer, cricket, rugby, AFL, boxing: `draw_possible`), a draw LOSES a
   team moneyline, as the books settle it. Where it is not, a level score is a PUSH (stake returned): the
   books did not offer a draw, so the grader will not invent a loss.
 * spread: the bet's `line` is the PICKED side's own line; that side's margin plus the line, zero is a push.
 * total: both scores added against the line, equal is a push.
 * VOID: a game with no completed result 72 hours after its start (cancelled, abandoned, never scored,
   or a family with no result source), or one that completed without a score. Void is by name, with the
   reason recorded; a game that is merely late stays pending until the 72 hours are up.

Scores are what the vendor returns: points, goals, runs, sets or games. Where a sport's score is not the
unit its totals are priced in (tennis totals are games, `/scores` has sets), the family captures h2h only
(config/sports_catalog.json), so no such bet exists to be mis-graded. Known limit: an NHL shootout may be
counted in the vendor's final score, which can move a total graded on it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.capture import budget
from src.paths import processed_path
from src.pipeline import creditlog, snapshots
from src.providers import odds as odds_provider
from src.sports import catalog

LOG = logging.getLogger(__name__)

DEFAULT_STORE = processed_path("allsports_scores.jsonl")
CALLER = "allsports_scores.poll"

# The same four settled results the card ledger and the hounds ledger use (src.appstate.card_ledger); written
# out here so the capture side never imports the app-state layer.
RESULT_WIN, RESULT_LOSS, RESULT_PUSH, RESULT_VOID = "WIN", "LOSS", "PUSH", "VOID"

_SCORE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:/\s*\d+)?\s*(?:\(.*\))?\s*$")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_score(value) -> Optional[float]:
    """One team's score as a number: 112, "112", "2", or a cricket "152/6" (runs, wickets). Anything else
    (two innings joined with "&", text, null) is None: a score the grader cannot read is never guessed."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _SCORE_RE.match(str(value))
    return float(match.group(1)) if match else None


def outcome_of(home, away) -> Optional[str]:
    if home is None or away is None:
        return None
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "draw"


def score_row(event: Mapping, observed: str, sport_key: str) -> dict:
    """One vendor /scores event as a store row (every field verbatim where it exists)."""
    scores = event.get("scores")
    by_name = {}
    for item in scores or []:
        if isinstance(item, Mapping) and item.get("name") is not None:
            by_name[item["name"]] = parse_score(item.get("score"))
    home, away = by_name.get(event.get("home_team")), by_name.get(event.get("away_team"))
    return {
        "kind": "score", "observed_utc": observed, "sport_key": sport_key, "event_id": event.get("id"),
        "commence_time": event.get("commence_time"), "home_team": event.get("home_team"),
        "away_team": event.get("away_team"), "completed": bool(event.get("completed")),
        "home_score": home, "away_score": away, "outcome": outcome_of(home, away),
        "scores": scores, "last_update": event.get("last_update"),
    }


def _signature(row: Mapping) -> tuple:
    return (bool(row.get("completed")), row.get("home_score"), row.get("away_score"),
            json.dumps(row.get("scores"), sort_keys=True), row.get("commence_time"), row.get("void_reason"))


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

def _read(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    out = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("allsports_scores: %s:%s is not valid JSON (interrupted append); skipped", target, number)
    return out


def _append(path, rows: list) -> int:
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if snapshots._ends_ragged(target):
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def load_index(path=DEFAULT_STORE) -> dict:
    """{event_id: the newest `score` row} from the store. A completed row is never replaced by a later
    row that is not completed (a re-listed event cannot un-finish a game)."""
    index: dict = {}
    for row in _read(path):
        if row.get("kind") != "score" or not row.get("event_id"):
            continue
        prior = index.get(row["event_id"])
        if prior is not None and prior.get("completed") and not row.get("completed"):
            continue
        index[row["event_id"]] = row
    return index


def append_scores(events: list, observed: str, sport_key: str, path=DEFAULT_STORE) -> int:
    """Append a `score` row for every event whose state differs from its last stored row."""
    index = load_index(path)
    rows = []
    for event in events or []:
        if not isinstance(event, Mapping) or not event.get("id"):
            continue
        row = score_row(event, observed, sport_key)
        prior = index.get(row["event_id"])
        if prior is not None and _signature(prior) == _signature(row):
            continue
        rows.append(row)
        index[row["event_id"]] = row
    return _append(path, rows)


def append_result_rows(rows: list, path=DEFAULT_STORE) -> int:
    """Append `score` rows built by another results source (src/pipeline/allsports_free_results.py: ESPN tennis
    and MMA), under the same rule as `append_scores`: a row is written only when the event's state differs from
    its last stored row, and nothing already written is touched."""
    index = load_index(path)
    fresh = []
    for row in rows or []:
        if row.get("kind") != "score" or not row.get("event_id"):
            continue
        prior = index.get(row["event_id"])
        if prior is not None and _signature(prior) == _signature(row):
            continue
        fresh.append(row)
        index[row["event_id"]] = row
    return _append(path, fresh)


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------

def _void(reason: str, home=None, away=None) -> dict:
    return {"result": RESULT_VOID, "reason": reason, "away_score": away, "home_score": home}


def grade_bet(bet: Mapping, result: Optional[Mapping], now: datetime, *, void_after_hours: float = 72.0,
              config: Optional[Mapping] = None) -> dict:
    """A paper bet on any all-sports family against its stored result -> {"result", "reason", scores}.

    result None means the bet is still pending (no completed result, and fewer than `void_after_hours`
    since the start). See the module docstring for the rules."""
    start = _parse(bet.get("commence_time") or bet.get("start_utc"))
    expired = start is not None and now - start >= timedelta(hours=void_after_hours)
    code = str(bet.get("sport") or "").upper()
    fam = catalog.family(code, config)
    if result is None or not result.get("completed"):
        if expired and fam is not None and fam.get("settles") == "none":
            return _void(f"no result source for {fam['label']}; voided {void_after_hours:g} hours after the start")
        if expired and fam is not None and fam.get("settles") == "free_results":
            return _void(f"no matching result in the free {fam['label']} results feed {void_after_hours:g} hours "
                         f"after the start (an event the feed does not cover, a name it could not match "
                         f"with certainty, or a match never played)")
        if expired:
            return _void(f"no final score within {void_after_hours:g} hours of the start (cancelled, "
                         f"abandoned or never scored)")
        return {"result": None}
    home, away = result.get("home_score"), result.get("away_score")
    if result.get("void_reason"):
        # A result source that knows the bet is void (a tennis walkover or early retirement, an MMA draw or
        # no contest): the reason it recorded is the reason the bet shows.
        return _void(str(result["void_reason"]), home, away)
    if home is None or away is None:
        return _void("the game completed without a readable final score")
    market, side = bet.get("market"), bet.get("side")
    line = bet.get("line")
    final = f"{home:g}-{away:g} (home-away)"
    if market == "moneyline":
        if side not in ("home", "away"):
            return _void(f"unknown side {side!r}", home, away)
        outcome = outcome_of(home, away)
        if outcome == "draw":
            if catalog.draw_possible(code, config):
                return {"result": RESULT_LOSS, "away_score": away, "home_score": home,
                        "reason": f"Final {final}: a draw loses a team moneyline in a three-way market"}
            return {"result": RESULT_PUSH, "away_score": away, "home_score": home,
                    "reason": f"Final {final}: level, and this sport's moneyline has no draw, so the stake is returned"}
        won = outcome == side
        return {"result": RESULT_WIN if won else RESULT_LOSS,
                "away_score": away, "home_score": home, "reason": f"Final {final}"}
    if market == "spread":
        if side not in ("home", "away") or not isinstance(line, (int, float)):
            return _void("a spread bet without a side or a line", home, away)
        margin = home - away
        adjusted = (margin if side == "home" else -margin) + float(line)
        if abs(adjusted) < 1e-9:
            return {"result": RESULT_PUSH, "away_score": away, "home_score": home,
                    "reason": f"Final {final}: the spread landed exactly on the margin"}
        return {"result": RESULT_WIN if adjusted > 0 else RESULT_LOSS,
                "away_score": away, "home_score": home, "reason": f"Final {final}"}
    if market == "total":
        if side not in ("over", "under") or not isinstance(line, (int, float)):
            return _void("a total bet without a side or a line", home, away)
        total = home + away
        if abs(total - float(line)) < 1e-9:
            return {"result": RESULT_PUSH, "away_score": away, "home_score": home,
                    "reason": f"Final {final}: the total landed exactly on the line"}
        won = (total > line) if side == "over" else (total < line)
        return {"result": RESULT_WIN if won else RESULT_LOSS,
                "away_score": away, "home_score": home, "reason": f"Final {final}, total {total:g}"}
    return _void(f"unknown market {market!r}", home, away)


# ---------------------------------------------------------------------------
# which keys to poll, and the run
# ---------------------------------------------------------------------------

def keys_to_poll(done_rows: list, scores_rows: list, now: datetime, cap: Mapping,
                 config: Optional[Mapping] = None) -> list:
    """[(sport_key, unresolved_events)] most-unresolved first: keys with captured events that started at
    least an hour ago, inside the `daysFrom` window, with no completed result stored, and not polled within
    `scores_poll_interval_hours`. A key whose family is settled from a free feed (`settles` =
    `free_results`: tennis, MMA) is never polled here: /scores does not list those sports and each call
    would cost credits to learn nothing."""
    days = int(cap["scores_days_from"] or 3)
    oldest = now - timedelta(days=days)
    newest = now - timedelta(hours=1)
    finished = {r["event_id"] for r in scores_rows if r.get("kind") == "score" and r.get("completed")}
    last_poll: dict = {}
    for r in scores_rows:
        if r.get("kind") == "poll":
            stamp = _parse(r.get("observed_utc"))
            if stamp is not None and (r.get("sport_key") not in last_poll or stamp > last_poll[r["sport_key"]]):
                last_poll[r["sport_key"]] = stamp
    pending: dict = {}
    for r in done_rows:
        if r.get("kind") != "phase" or not r.get("sport_key") or not r.get("event_id"):
            continue
        start = _parse(r.get("commence_utc"))
        if start is None or not (oldest <= start <= newest) or r["event_id"] in finished:
            continue
        pending.setdefault(r["sport_key"], set()).add(r["event_id"])
    interval = timedelta(hours=float(cap["scores_poll_interval_hours"]))
    out = []
    for key, events in pending.items():
        fam = catalog.family(catalog.family_for_key(key, config), config)
        if fam is not None and fam.get("settles") == "free_results":
            continue
        last = last_poll.get(key)
        if last is not None and now - last < interval:
            continue
        out.append((key, len(events)))
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def run(*, now=None, env=None, config: Optional[Mapping] = None, fetch_scores: Optional[Callable] = None,
        quota: Optional[Callable] = None, record_credit: Optional[Callable] = None,
        done_path=None, store_path=DEFAULT_STORE, credit_store=None, plan_only: bool = False) -> dict:
    """One scores tick: poll the keys that have unresolved captured events, under the scores sub-cap."""
    from src.pipeline import allsports_capture as cap_mod
    clock = cap_mod._now(now)
    cap = catalog.capture_config(config)
    result = {"observed_utc": _iso(clock), "keys": [], "polled": [], "credits": 0, "rows": 0,
              "skipped": {}, "halt": None}
    if not cap.get("enabled", True) or cap_mod.switched_off(env):
        result["halt"] = "disabled"
        return result
    if not odds_provider.is_configured(env):
        result["halt"] = "odds provider not configured"
        return result
    done_rows = cap_mod._read_rows(done_path or cap_mod.DEFAULT_DONE_PATH)
    keys = keys_to_poll(done_rows, _read(store_path), clock, cap, config)
    result["keys"] = [k for k, _n in keys]
    if plan_only or not keys:
        return result
    days_from = int(cap["scores_days_from"]) if cap.get("scores_days_from") else None
    est = 2 if days_from else 1
    real_provider = quota is None
    if fetch_scores is None:
        fetch_scores = lambda key, days: odds_provider.fetch_sport_scores_with_usage(  # noqa: E731
            key, days, env=env)
    if quota is None:
        quota = lambda: odds_provider.quota(env)  # noqa: E731
    if record_credit is None:
        record_credit = lambda remaining, used: creditlog.log(  # noqa: E731
            remaining, used, CALLER, store=credit_store or creditlog.DEFAULT_STORE, now=clock,
            budget_band=budget.ALLSPORTS)
    remaining = None
    try:
        q = quota()
        remaining = q.get("remaining") if isinstance(q, dict) else None
    except Exception as exc:  # noqa: BLE001
        LOG.warning("allsports_scores: quota unreadable: %s", exc)
    if remaining is None and real_provider:
        remaining = budget.remaining_today(now=clock, store=credit_store)
    unlogged = 0
    for key, _n in keys:
        decision = budget.can_spend_allsports(
            est + unlogged, now=clock, store=credit_store, remaining=remaining, config=config,
            sub_cap=int(cap["scores_daily_cap_credits"]), caller_prefix="allsports_scores")
        if not decision.allowed:
            result["skipped"][key] = decision.reason
            if "credit floor" in decision.reason or "daily cap" in decision.reason \
                    or "quota unreadable" in decision.reason:
                result["halt"] = decision.reason
                break
            continue
        try:
            events, usage = fetch_scores(key, days_from)
        except Exception as exc:  # noqa: BLE001
            result["skipped"][key] = f"fetch error: {exc}"
            continue
        usage = usage or {}
        billed = usage.get("last")
        if billed is None:
            billed = est
        observed = snapshots._timestamp(clock)
        written = append_scores(events, observed, key, store_path)
        _append(store_path, [{"kind": "poll", "observed_utc": observed, "sport_key": key,
                              "days_from": days_from, "events": len(events or []), "credits": billed}])
        if record_credit(usage.get("remaining"), billed) is False:
            unlogged += int(billed or 0)
        if usage.get("remaining") is not None:
            remaining = usage["remaining"]
        result["credits"] += int(billed or 0)
        result["rows"] += written
        result["polled"].append(key)
    return result


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.pipeline.allsports_scores")
    parser.add_argument("--plan", action="store_true", help="print the keys that would be polled; spend nothing")
    args = parser.parse_args(argv)
    result = run(plan_only=args.plan)
    print(f"  allsports scores: {len(result['keys'])} key(s) due, {len(result['polled'])} polled, "
          f"{result['credits']} credit(s), {result['rows']} result row(s)")
    if result.get("halt"):
        print(f"    halt: {result['halt']}")
    for key, why in sorted(result["skipped"].items()):
        print(f"    skipped {key}: {why}")
    from src.pipeline import allsports_free_results
    for line in allsports_free_results.summary_lines(allsports_free_results.run(plan_only=args.plan)):
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
