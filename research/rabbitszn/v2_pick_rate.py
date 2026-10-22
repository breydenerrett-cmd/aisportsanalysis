"""How many picks per day would the Gematria rules make on the stored boards? PICK COUNTS ONLY.

    python research/rabbitszn/v2_pick_rate.py --days 2026-10-14,2026-10-15,... [--rules rules_v2.json] [--set min_z=1.25]

This is the calibration tool for rules v2 (research/rabbitszn/METHOD.md, "Rules v2: pre-registration"). The owner's instruction was to
match the reference handicapper's pick RATE (about 2 to 5 picks a day across sports when games exist) and to look at nothing else. So
this script reads, for each day, the stored multibook captures (the boards) and the facts and the rules, weighs every game that had
not started at 15:00 UTC of that day, and prints HOW MANY it would take: per day, uncapped and capped at the rules' daily maximum, plus
how many games each pass reason removed. It reads no outcome of any game it weighs and no grade of any pick, prints no side or
price of a pick, and cannot be pointed at one: the only things it imports from the program are the board reader, the engine and
the rules. (The ENGINE's season basis reads past scores, cut before the read instant, to make its counts; that is the rules' own
input, the same live or here. The script never sees them, and no pick's result exists at the instant it weighs.)

``--set key=value`` overrides one decision key (for a sweep); it never writes a rules file.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.hounds import user_engine, user_gematria, user_spec          # noqa: E402
from src.hounds.gematria import rules as rules_mod, runtime as rt     # noqa: E402

EVALUATE_AT_UTC = "T15:00:00+00:00"     # a morning-of read: every game that starts later that day is weighed on the board standing then


def load_rules(name: str, overrides: dict) -> rules_mod.Rules:
    path = rules_mod.config_dir() / name
    data = json.loads(path.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    for key, value in overrides.items():
        (data["decision"] if key in data["decision"] else data)[key] = value
    return rules_mod.Rules.from_dict(data, raw_bytes=json.dumps(data, sort_keys=True).encode(), source=name)


def day_counts(day: str, rules: rules_mod.Rules) -> dict:
    now = datetime.fromisoformat(day + EVALUATE_AT_UTC)
    rows = [{k: r[k] for k in ("market", "event_id", "sport", "observed_utc") + user_engine._KEEP_FIELDS if k in r}
            for r in user_engine.iter_rows(day, user_spec.SPORTS)]
    games = user_engine.build_games(rows, near_date=day)
    games = {e: g for e, g in games.items() if g.commence is not None and user_engine.slate_date_of(g.commence) == day and g.commence > now}
    weigher = user_gematria.Weigher(games, runtime=rt.GematriaRuntime(rules=rules, ledger=None))
    codes: Counter = Counter()
    for event_id in sorted(games):
        got = weigher.weigh(event_id, as_of=now)
        codes["no_context" if got is None else got[2].verdict.code] += 1
    picks = codes.get("bet", 0)
    return {"day": day, "games": len(games), "picks_uncapped": picks, "picks_capped": min(picks, rules.decision.max_picks_per_day),
            "reasons": {k: v for k, v in sorted(codes.items()) if k != "bet"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", required=True, help="comma list of slate dates, YYYY-MM-DD")
    ap.add_argument("--rules", default="rules_v2.json")
    ap.add_argument("--set", action="append", default=[], help="key=value override of one decision key (numbers are read as numbers)")
    args = ap.parse_args(argv)
    overrides = {}
    for item in args.set:
        key, _, value = item.partition("=")
        try:
            overrides[key] = json.loads(value)
        except ValueError:
            overrides[key] = value
    rules = load_rules(args.rules, overrides)
    out = [day_counts(day.strip(), rules) for day in args.days.split(",") if day.strip()]
    for row in out:
        print(json.dumps(row))
    played = [r for r in out if r["games"] >= 4]
    if played:
        capped = sorted(r["picks_capped"] for r in played)
        print(json.dumps({"days_with_4_or_more_games": len(played), "capped_per_day": capped, "median": capped[len(capped) // 2],
                          "mean": round(sum(capped) / len(capped), 2)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
