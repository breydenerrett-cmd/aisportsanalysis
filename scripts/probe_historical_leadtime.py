"""Does the archive hold an OPENING F5/prop line, or only a close?

WHY THIS IS A THIRD SCRIPT AND NOT A THIRD CHECK
------------------------------------------------
`scripts/probe_historical_boundaries.py` tried to measure lead time by asking
for a slate at T-24h, T-6h and T-1h and taking the soonest pre-game event each
time. That silently measured three DIFFERENT games, each about an hour from its
own first pitch -- it answered "is there a market near first pitch" three times,
which is not the question. The result is kept in the evidence file, labelled,
rather than deleted.

The question needs ONE event id held fixed while the instant moves. Odds API
event ids are stable across historical snapshots, so the same game can be asked
for a day out and an hour out, and the difference between the two answers is
the thing a line-movement or opening-price hypothesis would actually trade.

What comes back decides a spec line: if F5 and prop markets are only quoted in
the last hour, then no opening-to-close family is testable historically at any
price, and the buy shrinks to close-only questions.
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
    _event_odds, _load_dotenv, _shape)

CALLER = "probe_historical_leadtime"

# New York Yankees @ Tampa Bay Rays, first pitch 2024-07-10T22:51:00Z. Chosen
# because the mid-season probe already resolved this id and confirmed 12 books
# quote its F5 line at T-6min, so a thinner answer further out is a real
# absence rather than a dead event id.
EVENT_ID = "c666105e14d197ecb795e910049bc678"
FIRST_PITCH = "2024-07-10T22:51:00Z"
MARKETS = ("h2h_1st_5_innings", "pitcher_strikeouts")

INSTANTS = (
    ("T-48h", "2024-07-08T22:50:00Z"),
    ("T-24h", "2024-07-09T22:50:00Z"),
    ("T-12h", "2024-07-10T10:50:00Z"),
    ("T-6h", "2024-07-10T16:50:00Z"),
    ("T-1h", "2024-07-10T21:50:00Z"),
    ("T-6m", "2024-07-10T22:45:00Z"),
)


def run(out_path, env_file) -> dict:
    _load_dotenv(env_file)
    quota = odds_provider.quota()
    remaining = quota.get("remaining")
    creditlog.log(remaining, quota.get("last"), CALLER + ".preflight")
    if remaining is None:
        raise SystemExit("refusing to probe: could not read the credit balance")
    envelope_left = budget_module.status().get("envelope_remaining_today")
    worst = 10 * len(MARKETS) * len(INSTANTS)
    print(f"credits remaining: {remaining}  envelope left: {envelope_left}  "
          f"worst case: {worst}")
    if remaining - worst <= budget_module.CREDIT_FLOOR:
        raise SystemExit("skipped: credit floor")
    if envelope_left is not None and worst > envelope_left:
        raise SystemExit(f"skipped: daily envelope ({worst} > {envelope_left})")

    report = {"caller": CALLER, "event_id": EVENT_ID, "first_pitch": FIRST_PITCH,
              "markets": list(MARKETS), "remaining_before": remaining,
              "worst_case_credits": worst, "lead_times": []}

    for label, instant in INSTANTS:
        row = {"label": label, "instant": instant}
        try:
            payload, usage = _event_odds(instant, EVENT_ID, MARKETS)
        except Exception as exc:  # noqa: BLE001 -- an absent market is the finding
            row["error"] = f"{type(exc).__name__}: {exc}"
            report["lead_times"].append(row)
            continue
        creditlog.log(usage.get("remaining"), usage.get("last"), CALLER + "." + label)
        shape = _shape(payload, instant, MARKETS)
        row["billed"] = usage.get("last")
        row.update({k: shape[k] for k in
                    ("served_timestamp", "previous_timestamp", "next_timestamp",
                     "book_count", "books", "markets_returned", "outcome_rows",
                     "player_count", "distinct_players",
                     "book_last_update_samples")})
        report["lead_times"].append(row)

    after = odds_provider.quota()
    creditlog.log(after.get("remaining"), after.get("last"), CALLER + ".postflight")
    report["remaining_after"] = after.get("remaining")
    report["credits_spent_measured"] = (
        remaining - after["remaining"] if after.get("remaining") is not None else None)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="evidence/probe_historical_leadtime.json")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    run(args.out, args.env_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
