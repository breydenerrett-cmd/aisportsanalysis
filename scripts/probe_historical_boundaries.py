"""Two spec lines the mid-season probe cannot answer: how far BACK, and how far AHEAD.

`scripts/probe_historical_f5_props.py` measures one mid-July night per season.
That establishes cost, books and cadence, but leaves two purchase-spec fields
unmeasured, and both change the size of the buy:

  YEARS COVERED. docs/COLLECTION_POLICY.md says first-five history "begins in
  mid-May 2023" and prop history "from ~May 2023", both as prose. If April 2023
  is dead the buy is ~2.6 seasons, not 3, and the plan must not budget dates the
  provider will answer 422 on forever.

  OPENING vs CLOSING. Everything the archive holds was captured near first
  pitch. A backtest that can only ever see the close cannot test a
  line-movement or opening-price hypothesis at all. The question is whether F5
  and prop markets are quoted -- and archived -- a day out, or whether they only
  appear in the last hour.

Both are answered by asking for the SAME kind of thing at different instants
and recording what comes back, including the empty answers. An empty payload
bills zero (measured in the first probe run), so a boundary miss is close to
free; the cost is dominated by the hits.

Same guards as the first probe: floor, envelope, credit log, JSON out.
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
from scripts.probe_historical_f5_props import (  # noqa: E402
    _events, _event_odds, _load_dotenv, _shape)

CALLER = "probe_historical_boundaries"

# (label, instant, markets). Back-boundary walk in 2023, then a lead-time walk
# on one ordinary 2024 night: T-24h, T-6h, T-1h against the same slate.
CHECKS = (
    ("back_2023_03_31", "2023-03-31T22:50:00Z", ("h2h_1st_5_innings",)),
    ("back_2023_04_20", "2023-04-20T22:50:00Z", ("h2h_1st_5_innings",)),
    ("back_2023_05_10", "2023-05-10T22:50:00Z", ("h2h_1st_5_innings",)),
    ("back_2023_04_20_props", "2023-04-20T22:50:00Z", ("pitcher_strikeouts",)),
    ("lead_2024_T24h", "2024-07-09T23:00:00Z", ("h2h_1st_5_innings", "pitcher_strikeouts")),
    ("lead_2024_T6h", "2024-07-10T17:00:00Z", ("h2h_1st_5_innings", "pitcher_strikeouts")),
    ("lead_2024_T1h", "2024-07-10T22:00:00Z", ("h2h_1st_5_innings", "pitcher_strikeouts")),
)


def run(out_path, env_file) -> dict:
    _load_dotenv(env_file)
    quota = odds_provider.quota()
    remaining = quota.get("remaining")
    creditlog.log(remaining, quota.get("last"), CALLER + ".preflight",
                  budget_band=budget_module.HISTORICAL_BACKFILL)
    if remaining is None:
        raise SystemExit("refusing to probe: could not read the credit balance")

    status = budget_module.status()
    envelope_left = status.get("envelope_remaining_today")
    worst = sum(1 + 10 * len(m) for _label, _i, m in CHECKS)
    print(f"credits remaining: {remaining}  envelope left: {envelope_left}  "
          f"worst case: {worst}")
    if remaining - worst <= budget_module.CREDIT_FLOOR:
        raise SystemExit("skipped: credit floor")
    if envelope_left is not None and worst > envelope_left:
        raise SystemExit(f"skipped: daily envelope ({worst} > {envelope_left})")

    report = {"caller": CALLER, "remaining_before": remaining,
              "worst_case_credits": worst, "checks": []}

    for label, instant, markets in CHECKS:
        row = {"label": label, "instant": instant, "markets": list(markets)}
        try:
            payload, usage = _events(instant)
        except Exception as exc:  # noqa: BLE001 -- a dead instant is the finding
            row["events_error"] = f"{type(exc).__name__}: {exc}"
            report["checks"].append(row)
            continue
        creditlog.log(usage.get("remaining"), usage.get("last"), CALLER + "." + label,
                      budget_band=budget_module.HISTORICAL_BACKFILL)
        events = (payload.get("data") if isinstance(payload, dict) else payload) or []
        served = payload.get("timestamp") if isinstance(payload, dict) else None
        row.update({"events_served_timestamp": served,
                    "events_returned": len(events),
                    "events_billed": usage.get("last")})
        cut = served or instant
        pregame = sorted((e for e in events if (e.get("commence_time") or "") > cut),
                         key=lambda e: e.get("commence_time") or "")
        row["pregame_events"] = len(pregame)
        if not pregame:
            report["checks"].append(row)
            continue
        chosen = pregame[0]
        row["chosen_commence"] = chosen.get("commence_time")
        try:
            odds_payload, odds_usage = _event_odds(instant, chosen["id"], markets)
        except Exception as exc:  # noqa: BLE001 -- 422 unavailable-at-date is the finding
            row["odds_error"] = f"{type(exc).__name__}: {exc}"
            report["checks"].append(row)
            continue
        creditlog.log(odds_usage.get("remaining"), odds_usage.get("last"),
                      CALLER + "." + label + ".odds",
                      budget_band=budget_module.HISTORICAL_BACKFILL)
        shape = _shape(odds_payload, instant, markets)
        row["billed"] = odds_usage.get("last")
        row["shape"] = {k: shape[k] for k in
                        ("served_timestamp", "previous_timestamp", "next_timestamp",
                         "commence_time", "book_count", "books", "markets_returned",
                         "outcome_rows", "player_count", "book_last_update_samples")}
        report["checks"].append(row)

    after = odds_provider.quota()
    creditlog.log(after.get("remaining"), after.get("last"), CALLER + ".postflight",
                  budget_band=budget_module.HISTORICAL_BACKFILL)
    report["remaining_after"] = after.get("remaining")
    report["credits_spent_measured"] = (
        remaining - after["remaining"] if after.get("remaining") is not None else None)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="evidence/probe_historical_boundaries.json")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    report = run(args.out, args.env_file)
    print(json.dumps(report, indent=2, sort_keys=True)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
