"""Which book writes prop player names we cannot join to an MLBAM id?

A prop we cannot settle is worth zero credits no matter what it costs, so the
purchase spec has to state the settlement join rate as a measurement. Joining
the first probe run's player names against data/historical/handedness.json gave
100% for every 2024 and 2025 payload and **68% (21/31) for 2023 batter props**,
missing on names like "Frederick Freeman", "Markus Betts" and "Boyce Mullins" --
formal/legal names where the rosters carry the common name.

That aggregate cannot say whether the 32% is ONE book's naming convention
(fixable with an alias table built once) or a 2023-wide feed property (a real
tax on every 2023 batter-prop row). The first probe folded players together
across books before writing its report, so the attribution was thrown away.

This re-fetches the SAME event and instant and keeps names per book. It is a
deliberate re-spend of ~40 credits to turn a blocking unknown into a fact.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import budget as budget_module  # noqa: E402
from src.pipeline import creditlog  # noqa: E402
from src.providers import odds as odds_provider  # noqa: E402
from scripts.probe_historical_f5_props import (  # noqa: E402
    _event_odds, _events, _load_dotenv)

CALLER = "probe_prop_name_join"
INSTANT = "2023-07-18T22:50:00Z"
MARKETS = ("batter_hits", "batter_total_bases", "batter_home_runs")
HANDEDNESS = "data/historical/handedness.json"


def norm(name: str) -> str:
    """Accent- and punctuation-insensitive match. Nothing fuzzier than that:
    a fuzzy match that silently pairs two different players is worse than a
    miss, because a miss is visible and a wrong settle is not."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace(".", "").replace("'", "").split())


def run(out_path, env_file, handedness_path) -> dict:
    _load_dotenv(env_file)
    quota = odds_provider.quota()
    remaining = quota.get("remaining")
    creditlog.log(remaining, quota.get("last"), CALLER + ".preflight")
    if remaining is None:
        raise SystemExit("refusing to probe: could not read the credit balance")
    envelope_left = budget_module.status().get("envelope_remaining_today")
    worst = 1 + 10 * len(MARKETS)
    print(f"credits remaining: {remaining}  envelope left: {envelope_left}  "
          f"worst case: {worst}")
    if remaining - worst <= budget_module.CREDIT_FLOOR:
        raise SystemExit("skipped: credit floor")
    if envelope_left is not None and worst > envelope_left:
        raise SystemExit(f"skipped: daily envelope ({worst} > {envelope_left})")

    hand = json.loads(Path(handedness_path).read_text(encoding="utf-8"))
    index = collections.defaultdict(list)
    for pid, rec in hand.items():
        index[norm(rec.get("name"))].append(pid)

    payload, usage = _events(INSTANT)
    creditlog.log(usage.get("remaining"), usage.get("last"), CALLER + ".events")
    events = (payload.get("data") if isinstance(payload, dict) else payload) or []
    served = payload.get("timestamp") if isinstance(payload, dict) else None
    pregame = sorted((e for e in events if (e.get("commence_time") or "") > (served or INSTANT)),
                     key=lambda e: e.get("commence_time") or "")
    if not pregame:
        raise SystemExit("no pre-game event at that instant")
    chosen = pregame[0]

    odds_payload, odds_usage = _event_odds(INSTANT, chosen["id"], MARKETS)
    creditlog.log(odds_usage.get("remaining"), odds_usage.get("last"), CALLER + ".odds")

    data = (odds_payload or {}).get("data") or {}
    per_book = {}
    for book in (data.get("bookmakers") or []):
        names = set()
        for market in (book.get("markets") or []):
            for outcome in (market.get("outcomes") or []):
                if outcome.get("description"):
                    names.add(outcome["description"])
        hit = sorted(n for n in names if norm(n) in index)
        miss = sorted(n for n in names if norm(n) not in index)
        per_book[book.get("key")] = {
            "players": len(names),
            "resolved": len(hit),
            "unresolved": miss,
            "resolve_rate": round(len(hit) / len(names), 3) if names else None,
        }

    report = {
        "caller": CALLER, "instant": INSTANT, "event_id": chosen["id"],
        "served_timestamp": (odds_payload or {}).get("timestamp"),
        "commence_time": data.get("commence_time"),
        "markets": list(MARKETS),
        "billed": odds_usage.get("last"),
        "handedness_players": len(hand),
        "per_book": per_book,
        "remaining_before": remaining,
    }
    after = odds_provider.quota()
    creditlog.log(after.get("remaining"), after.get("last"), CALLER + ".postflight")
    report["remaining_after"] = after.get("remaining")
    report["credits_spent_measured"] = (
        remaining - after["remaining"] if after.get("remaining") is not None else None)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    for key, row in sorted(per_book.items()):
        print(f"  {key:16s} {row['resolved']:3d}/{row['players']:3d} "
              f"({row['resolve_rate']}) miss={row['unresolved'][:6]}")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="evidence/probe_prop_name_join.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--handedness", default=HANDEDNESS)
    args = parser.parse_args(argv)
    run(args.out, args.env_file, args.handedness)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
