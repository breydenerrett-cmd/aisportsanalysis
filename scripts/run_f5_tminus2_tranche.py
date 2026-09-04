"""Sanity tranche for the T-2h F5 snapshot-timing repair.

Owner authorization: docs/F5_REPAIR_RELEASE_GATE.md ("A small acquisition
sanity tranche may run first to verify the frozen rule behaves as expected").
This script runs ONLY the ~20-game tranche and stops -- it does not touch
the remaining ~4,290 games. That is a separate, later authorization.

Implements exactly docs/PREREG_F5_SNAPSHOT_RULE.md via src/pipeline/f5_tminus2.py:
T-2:00 before scheduled first pitch, +/-5min grid tolerance, pregame,
>=5 books, PRIMARY_SNAPSHOT_UNAVAILABLE on any miss with an explicit reason.
Nothing here evaluates a hypothesis, a win rate, or a profit -- it only
acquires and reports acquisition statistics.

USAGE
-----
    set -a; . ./.env; set +a
    python3 scripts/run_f5_tminus2_tranche.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import budget as budget_module  # noqa: E402
from src.pipeline import creditlog  # noqa: E402
from src.pipeline import f5_tminus2 as t2  # noqa: E402
from src.providers import odds as odds_provider  # noqa: E402

CALLER = "f5_tminus2_sanity_tranche"

# 20 games, hand-picked from the games already named in the existing
# odds_first_five store (the mismatch-scanner universe), spread across three
# seasons and across start-time-of-day (UTC hour 0-1 = West Coast late
# starts, 17-19 = day/early-evening starts, 22-23 = the ET evening block) so
# the tranche exercises the 5-minute grid at genuinely different points of
# the day, not just one recurring slot.
TRANCHE_GAME_PKS = [
    "718279",  # 2023-05-06 LAD@SD   00:40Z
    "717365",  # 2023-07-17 MIN@SEA  01:40Z
    "717435",  # 2023-07-09 OAK@BOS  17:35Z
    "716354",  # 2023-10-01 WSH@ATL  19:10Z
    "717189",  # 2023-07-31 PHI@MIA  22:40Z
    "717486",  # 2023-07-05 ATL@CLE  23:10Z
    "716377",  # 2023-09-30 BOS@BAL  23:15Z
    "746412",  # 2024-03-29 NYY@HOU  00:10Z
    "745229",  # 2024-07-20 HOU@SEA  01:40Z
    "747098",  # 2024-07-07 PHI@ATL  17:35Z
    "746820",  # 2024-09-29 CIN@CHC  19:20Z
    "745576",  # 2024-05-22 TEX@PHI  22:40Z
    "747037",  # 2024-05-17 SEA@BAL  23:05Z
    "747066",  # 2024-09-28 KC@ATL   23:20Z
    "778142",  # 2025-04-28 DET@HOU  00:10Z
    "776668",  # 2025-08-19 CIN@LAA  01:38Z
    "776758",  # 2025-08-13 COL@STL  18:15Z
    "777996",  # 2025-05-09 TEX@DET  22:40Z
    "777906",  # 2025-05-16 DET@TOR  23:07Z
    "776221",  # 2025-09-22 WSH@ATL  23:15Z
]

# ~11 credits/game observed elsewhere in this codebase's own historical
# per-event calls (1 events lookup + 1 market x HISTORICAL_MULTIPLIER); 20
# games is a ~220-credit worst case, matching the ~200-credit tranche size
# authorized in the mission. A hard ceiling, checked before every spend.
BUDGET_CEILING = 400


def _load_dotenv(path=".env") -> None:
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


def main() -> int:
    _load_dotenv()

    if not odds_provider.is_configured():
        raise SystemExit(odds_provider.SETUP_MESSAGE)

    quota_before = odds_provider.quota()
    remaining = quota_before.get("remaining")
    creditlog.log(remaining, quota_before.get("last"), CALLER + ".preflight")
    if remaining is None:
        raise SystemExit("refusing to run: could not read the credit balance")

    if remaining - BUDGET_CEILING <= budget_module.CREDIT_FLOOR:
        raise SystemExit(
            f"skipped: credit floor (remaining={remaining}, "
            f"ceiling={BUDGET_CEILING}, floor={budget_module.CREDIT_FLOOR})")

    print(f"credits remaining before: {remaining}")
    print(f"budget ceiling for this tranche: {BUDGET_CEILING}")
    print(f"games in tranche: {len(TRANCHE_GAME_PKS)}")

    schedule = t2.load_schedule()
    missing = [pk for pk in TRANCHE_GAME_PKS if pk not in schedule]
    if missing:
        print(f"WARNING: {len(missing)} tranche game_pk(s) not found in "
             f"mlb_results.csv: {missing}")

    def on_game(row):
        print(f"  {row['game_pk']} {row.get('date')} "
             f"{row.get('away_team')}@{row.get('home_team')}: "
             f"{row['status']}" + (f" ({row['reason']})" if row.get("reason") else ""))

    report = t2.run(TRANCHE_GAME_PKS, schedule=schedule, budget=BUDGET_CEILING,
                    on_game=on_game)

    quota_after = odds_provider.quota()
    creditlog.log(quota_after.get("remaining"), quota_after.get("last"),
                 CALLER + ".postflight")

    seasons_touched = sorted({row["date"][:4] for row in report["rows"]
                              if row.get("date")})
    primary_rows = []
    for season in seasons_touched:
        primary_rows.extend(t2.build_primary_view([season]))
    primary_path = t2.write_primary_view(
        [r for r in primary_rows if r["game_pk"] in set(TRANCHE_GAME_PKS)])

    # ---- report, with real numbers -----------------------------------
    print("\n" + "=" * 70)
    print("SANITY TRANCHE REPORT")
    print("=" * 70)
    print(f"requested            : {report['requested']}")
    print(f"attempted            : {report['attempted']}")
    print(f"skipped (already run): {report['skipped_already_attempted']}")
    print(f"OK (compliant)       : {report['ok']}")
    print(f"UNAVAILABLE          : {report['unavailable']}")
    print(f"reason breakdown     : {dict(report['reason_counts'])}")
    print(f"stopped_early        : {report['stopped_early']}")
    print(f"credits_spent        : {report['credits_spent']}")
    print(f"credits/game (attempted): "
         f"{report['credits_spent'] / report['attempted']:.2f}"
         if report["attempted"] else "n/a")
    print(f"credits_remaining    : {report['credits_remaining']}")
    print(f"quota remaining after: {quota_after.get('remaining')}")
    print(f"measured spend (quota delta): "
         f"{remaining - quota_after.get('remaining') if quota_after.get('remaining') is not None else None}")
    print(f"primary view written : {primary_path}")

    ok_rows = [r for r in report["rows"] if r["status"] == "OK"]
    devs = [t2.deviation_minutes(r["query_instant"], r["snapshot_at"])
           for r in ok_rows]
    devs = [d for d in devs if d is not None]
    if devs:
        devs_sorted = sorted(devs)
        n = len(devs_sorted)
        print("\ndeviation-from-target distribution (minutes, OK rows only):")
        print(f"  n={n} min={devs_sorted[0]:.2f} "
             f"median={devs_sorted[n // 2]:.2f} max={devs_sorted[-1]:.2f}")
        print(f"  all values: {[round(d, 2) for d in devs_sorted]}")
    else:
        print("\nno OK rows -- no deviation distribution to report.")

    book_counts = [r["book_count"] for r in report["rows"]]
    print(f"\nbook-count distribution (all attempted rows): "
         f"{sorted(Counter(book_counts).items())}")
    if ok_rows:
        ok_counts = sorted(r["book_count"] for r in ok_rows)
        print(f"book-count distribution (OK rows only): {ok_counts}")

    print("\n--- one full OK row, verbatim ---")
    if ok_rows:
        print(json.dumps(ok_rows[0], indent=2, sort_keys=True))
    else:
        print("(none -- no game in the tranche produced a compliant snapshot)")

    unavailable_rows = [r for r in report["rows"]
                        if r["status"] == "PRIMARY_SNAPSHOT_UNAVAILABLE"]
    print("\n--- one full UNAVAILABLE row, verbatim ---")
    if unavailable_rows:
        print(json.dumps(unavailable_rows[0], indent=2, sort_keys=True))
    else:
        print("(none -- every attempted game produced a compliant snapshot)")

    # NOT under evidence/ -- that path is reserved and off-limits per the
    # task boundaries. This is a local scratch report only.
    out_path = Path("/tmp/f5_tminus2_sanity_tranche_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "report": {k: v for k, v in report.items() if k != "rows"},
        "rows": report["rows"],
        "credits_remaining_before": remaining,
        "credits_remaining_after": quota_after.get("remaining"),
        "measured_credits_spent": (
            remaining - quota_after.get("remaining")
            if quota_after.get("remaining") is not None else None),
        "primary_view_path": primary_path,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nfull report written to {out_path}")

    print("\nSTOP: sanity tranche only. Do not proceed to the remaining "
         "~4,290 games without separate authorization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
