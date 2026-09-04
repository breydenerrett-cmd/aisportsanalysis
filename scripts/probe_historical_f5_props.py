"""Measure -- not assume -- what a historical F5 / props purchase would actually buy.

WHY THIS EXISTS
---------------
docs/RESOURCE_POLICY.md requires a purchase spec before any large historical
buy, and every line of that spec has to be backed by a measurement rather than
a docs claim. The three facts that decide the buy are all unmeasured:

  1. What does ONE historical per-event call actually bill? The code assumes
     `HISTORICAL_MULTIPLIER * len(markets)` (src/pipeline/backfill.py:57) and
     nothing has ever compared that to the provider's own `x-requests-last`.
  2. Do F5 / pitcher-prop / batter-prop markets EXIST at a 2023 / 2024 / 2025
     historical timestamp, and at how many books? A market that returns an
     empty book list is worth zero credits regardless of price.
  3. What snapshot does the provider actually return for a requested instant?
     The requested time and the served `timestamp` are different fields, and
     the gap between them IS the cadence. docs/RESEARCH_CATALOGUE.md B5 grades
     every historical event class C/D; the served timestamp is how we find out
     whether that grade applies to prices too.

Each probe is ONE per-event historical fetch. Cost is bounded and printed
before anything is spent. Every quota read is appended to the credit log, so
the spend audits itself, and the run refuses to start below CREDIT_FLOOR or
outside the remaining daily envelope.

Output is a JSON report written to the path given by --out. Nothing under
data/watch/, data/processed/ or the odds stores is touched: this writes one
new file and appends to the credit log, nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import budget as budget_module  # noqa: E402
from src.pipeline import creditlog  # noqa: E402
from src.providers import odds as odds_provider  # noqa: E402

CALLER = "probe_historical_f5_props"

# One mid-season date per season, at the later of backfill.py's two snapshot
# instants (22:50Z catches the night slate). Dates are inside each season's
# measured coverage window in data/archive/historical/odds_first_five/.
# 2023-07-12 was the All-Star break: the only event on the board was the
# All-Star Game and the nearest archived snapshot was 19 hours from the
# instant we asked for. Replaced with an ordinary regular-season night.
PROBE_INSTANTS = {
    2023: "2023-07-18T22:50:00Z",
    2024: "2024-07-10T22:50:00Z",
    2025: "2025-07-09T22:50:00Z",
}

# Market groups to test, smallest useful bundle each. Named from
# src/providers/odds.py so a probe cannot drift from what a real pull requests.
MARKET_GROUPS = {
    "f5_h2h": ("h2h_1st_5_innings",),
    "f5_pair": ("h2h_1st_5_innings", "totals_1st_5_innings"),
    "pitcher_props": ("pitcher_strikeouts",),
    "batter_props": ("batter_hits", "batter_total_bases", "batter_home_runs"),
}


def _load_dotenv(path) -> None:
    """Same reader as src/cli.py: values already exported win, nothing printed."""
    import os
    env_file = Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _events(instant, timeout=30):
    """The historical /events lookup. Free or near-free; measured, not assumed."""
    return odds_provider._get_json_with_usage(
        f"historical/sports/{odds_provider.SPORT}/events",
        {"apiKey": odds_provider.api_key(), "date": instant},
        timeout=timeout)


def _event_odds(instant, event_id, markets, timeout=30):
    return odds_provider._get_json_with_usage(
        f"historical/sports/{odds_provider.SPORT}/events/{event_id}/odds",
        {"apiKey": odds_provider.api_key(),
         "regions": odds_provider.DEFAULT_REGION,
         "markets": ",".join(markets),
         "oddsFormat": odds_provider.ODDS_FORMAT,
         "date": instant},
        timeout=timeout)


def _shape(payload, requested_instant, markets):
    """Reduce a historical per-event payload to the facts the spec needs."""
    data = (payload or {}).get("data") or {}
    books = data.get("bookmakers") or []
    market_rows = {}
    outcomes = 0
    players = set()
    last_updates = set()
    for book in books:
        for market in (book.get("markets") or []):
            key = market.get("key")
            outs = market.get("outcomes") or []
            market_rows.setdefault(key, {"books": 0, "outcomes": 0})
            market_rows[key]["books"] += 1
            market_rows[key]["outcomes"] += len(outs)
            outcomes += len(outs)
            if market.get("last_update"):
                last_updates.add(market["last_update"])
            for out in outs:
                if out.get("description"):
                    players.add(out["description"])
        if book.get("last_update"):
            last_updates.add(book["last_update"])
    return {
        "requested_instant": requested_instant,
        "served_timestamp": (payload or {}).get("timestamp"),
        "previous_timestamp": (payload or {}).get("previous_timestamp"),
        "next_timestamp": (payload or {}).get("next_timestamp"),
        "event_id": data.get("id"),
        "commence_time": data.get("commence_time"),
        "home_team": data.get("home_team"),
        "away_team": data.get("away_team"),
        "requested_markets": list(markets),
        "books": sorted({b.get("key") for b in books if b.get("key")}),
        "book_count": len(books),
        "markets_returned": market_rows,
        "outcome_rows": outcomes,
        "distinct_players": sorted(players),
        "player_count": len(players),
        "book_last_update_samples": sorted(last_updates)[:4],
    }


def run(seasons, groups, out_path, dry_run=False) -> dict:
    quota = odds_provider.quota()
    remaining = quota.get("remaining")
    creditlog.log(remaining, quota.get("last"), CALLER + ".preflight")
    if remaining is None:
        raise SystemExit("refusing to probe: could not read the credit balance")

    status = budget_module.status()
    envelope_left = status.get("envelope_remaining_today")

    # Worst case: one events lookup per season plus one per-event call per
    # (season, group), each billed at the assumed multiplier. Real cost is
    # measured; this bound is only what we check the floor and envelope against.
    worst = 0
    for _season in seasons:
        worst += 1
        for name in groups:
            worst += odds_provider_multiplier() * len(MARKET_GROUPS[name])

    print(f"credits remaining : {remaining}")
    print(f"envelope left today: {envelope_left}")
    print(f"worst-case probe cost: {worst}")

    if remaining - worst <= budget_module.CREDIT_FLOOR:
        raise SystemExit("skipped: credit floor")
    if envelope_left is not None and worst > envelope_left:
        raise SystemExit(f"skipped: daily envelope ({worst} > {envelope_left})")
    if dry_run:
        return {"dry_run": True, "worst_case_credits": worst}

    report = {"caller": CALLER, "remaining_before": remaining,
              "worst_case_credits": worst, "probes": [], "events_lookups": []}

    for season in seasons:
        instant = PROBE_INSTANTS[season]
        try:
            payload, usage = _events(instant)
        except Exception as exc:  # noqa: BLE001 -- a dead season is a finding
            report["events_lookups"].append(
                {"season": season, "instant": instant, "error": f"{type(exc).__name__}: {exc}"})
            continue
        creditlog.log(usage.get("remaining"), usage.get("last"),
                      CALLER + f".events.{season}")
        events = (payload.get("data") if isinstance(payload, dict) else payload) or []
        report["events_lookups"].append({
            "season": season, "instant": instant,
            "served_timestamp": payload.get("timestamp") if isinstance(payload, dict) else None,
            "events_returned": len(events),
            "billed": usage.get("last"),
            "remaining_after": usage.get("remaining"),
        })
        if not events:
            continue
        # PICK A PRE-GAME EVENT, NOT events[0]. The first probe run took
        # whatever the feed listed first and drew games already in progress at
        # the requested instant -- F5 and prop markets are pulled from the
        # board once a game starts, so every one came back with zero books and
        # billed zero. That measured the wrong thing: "no market after first
        # pitch", not "no market in history". The event we want is one whose
        # commence_time is still in the future at the snapshot we asked for.
        served = payload.get("timestamp") if isinstance(payload, dict) else None
        cut = served or instant
        pregame = [e for e in events if (e.get("commence_time") or "") > cut]
        pregame.sort(key=lambda e: e.get("commence_time") or "")
        chosen = pregame[0] if pregame else events[0]
        event_id = chosen.get("id")
        report["events_lookups"][-1].update({
            "pregame_events": len(pregame),
            "chosen_event": event_id,
            "chosen_commence": chosen.get("commence_time"),
            "chosen_pregame": bool(pregame),
        })

        for name in groups:
            markets = MARKET_GROUPS[name]
            try:
                odds_payload, odds_usage = _event_odds(instant, event_id, markets)
            except Exception as exc:  # noqa: BLE001 -- an unavailable market is a finding
                report["probes"].append({
                    "season": season, "group": name, "instant": instant,
                    "event_id": event_id, "billed": 0,
                    "error": f"{type(exc).__name__}: {exc}"})
                continue
            creditlog.log(odds_usage.get("remaining"), odds_usage.get("last"),
                          CALLER + f".{name}.{season}")
            shape = _shape(odds_payload, instant, markets)
            shape.update({
                "season": season, "group": name,
                "billed": odds_usage.get("last"),
                "assumed_billed": odds_provider_multiplier() * len(markets),
                "remaining_after": odds_usage.get("remaining"),
            })
            report["probes"].append(shape)

    after = odds_provider.quota()
    creditlog.log(after.get("remaining"), after.get("last"), CALLER + ".postflight")
    report["remaining_after"] = after.get("remaining")
    report["credits_spent_measured"] = (
        remaining - after["remaining"] if after.get("remaining") is not None else None)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    return report


def odds_provider_multiplier() -> int:
    from src.pipeline import backfill
    return backfill.HISTORICAL_MULTIPLIER


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", default="2023,2024,2025")
    parser.add_argument("--groups", default=",".join(MARKET_GROUPS))
    parser.add_argument("--out", default="evidence/probe_historical_f5_props.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--env-file", default=".env",
        help="gitignored dotenv holding ODDS_API_KEY. Loaded into os.environ "
             "and never printed; a worktree has no .env of its own, so point "
             "this at the main checkout's file when probing from one.")
    args = parser.parse_args(argv)

    _load_dotenv(args.env_file)

    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    unknown = [g for g in groups if g not in MARKET_GROUPS]
    if unknown:
        raise SystemExit(f"unknown market group(s): {unknown}")
    bad = [s for s in seasons if s not in PROBE_INSTANTS]
    if bad:
        raise SystemExit(f"no probe instant defined for season(s): {bad}")

    report = run(seasons, groups, args.out, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
