"""Post-registration INSTRUMENT CHECKS for K_OPPONENT_V1. Descriptive; decides nothing.

Written AFTER the registered verdict because the gain was larger than the
registration's planning arithmetic expected (a surprise is a bug report until
shown otherwise). Prints only counts and summary numbers, never a row. Same
streaming reader as the registered script (an out-of-season raw line is
discarded before it is parsed). Fixed seeds, run once.

    python scripts/k_opponent_checks.py

1. Independent recount: for 300 sampled scored starts per season, the opposing
   team and its batting K / PA / games before the date are recomputed from the
   raw bullpen rows by separate code and compared with the harness row.
2. Placebo: the opposing team is shuffled among the starts of each date (seed
   777). A real signal should turn NEGATIVE; a leak or a bias would not.
3. Slope of the strikeout residual (K - E_baseline) on the applied shift
   (E_baseline * (factor - 1)). Near 1 means the factor is well scaled; a leak
   would give a slope far above 1.
4. The mean d split by whether the opposing team was the HOME team.
"""

from __future__ import annotations

import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import k_opponent_compare as script  # noqa: E402
from src.research import k_baseline as kb  # noqa: E402
from src.research import k_opponent as ko  # noqa: E402


def _inputs(season):
    years = script.seasons_needed(season)
    pitchers = list(script.stream_jsonl_years(script._abs(script.PITCHER_LOGS_PATH), years))
    extracted = kb.extract_starts(pitchers)
    regular = script.regular_games_for(script._abs(script.RESULTS_PATH), years)
    bullpen = list(script.stream_jsonl_years(script._abs(script.BULLPEN_LOG_PATH), years))
    games = ko.extract_games(bullpen, regular)
    attached = ko.attach_opponents(extracted["starts"], games)
    return pitchers, extracted, regular, bullpen, games, attached


def recount_mismatches(season, rows, bullpen, regular, games, sample=300, seed=12345):
    excluded = set(games["excluded_games"])
    raw = [r for r in bullpen if len(r) >= 13 and str(r["date"])[:4] == str(season)]
    by_game = collections.defaultdict(list)
    for r in raw:
        if r["game_pk"] in regular and r["game_pk"] not in excluded:
            by_game[r["game_pk"]].append(r)
    bad = 0
    for row in random.Random(seed).sample(rows, min(sample, len(rows))):
        starter = [r for r in raw if r["person_id"] == row["person_id"]
                   and r["date"] == row["date"] and r["started"]]
        team, pk = starter[0]["team"], starter[0]["game_pk"]
        opp = ({r["team"] for r in by_game[pk]} - {team}).pop()
        k = pa = n = 0
        for rs in by_game.values():
            if rs[0]["date"] >= row["date"] or opp not in {r["team"] for r in rs}:
                continue
            n += 1
            for r in rs:
                if r["team"] != opp:
                    k += r["strikeouts"]
                    pa += r["batters_faced"]
        if (opp, k, pa, n) != (row["opponent"], row["opp_k"], row["opp_pa"], row["opp_games"]):
            bad += 1
    return bad


def main():
    out = {}
    for season in kb.ALLOWED_SEASONS:
        pitchers, extracted, regular, bullpen, games, att = _inputs(season)
        home_of = {(r["person_id"], r["date"]): r["is_home"]
                   for r in pitchers if r.get("games_started") == 1}
        rows = ko.build_opponent_rows(
            season=season, starts=extracted["starts"], games=games["games"],
            opponents=att["opponents"], causes=att["causes"])["rows"]
        out[f"{season}_recount_mismatches_of_300"] = recount_mismatches(
            season, rows, bullpen, regular, games)
        prng = random.Random(777)
        by_date = collections.defaultdict(list)
        for key in att["opponents"]:
            by_date[key[1]].append(key)
        shuffled = {}
        for date in sorted(by_date):
            keys = sorted(by_date[date])
            vals = [att["opponents"][k] for k in keys]
            prng.shuffle(vals)
            shuffled.update(zip(keys, vals))
        placebo = ko.build_opponent_rows(
            season=season, starts=extracted["starts"], games=games["games"],
            opponents=shuffled, causes=att["causes"])["rows"]
        for lk in ("4.5", "5.5"):
            a = kb.clustered_mean_interval(kb.per_date_aggregates(placebo, f"d_{lk}"))
            out[f"{season}_placebo_{lk}"] = [a["estimate"], a["low"], a["high"], a["n"]]
            for label, want in (("opponent_home", False), ("opponent_away", True)):
                sub = [r for r in rows if home_of[(r["person_id"], r["date"])] is want]
                b = kb.clustered_mean_interval(kb.per_date_aggregates(sub, f"d_{lk}"))
                out[f"{season}_{label}_{lk}"] = [b["estimate"], b["low"], b["high"], b["n"]]
        xs = [r["e_base"] * (r["factor"] - 1) for r in rows]
        ys = [r["k"] - r["e_base"] for r in rows]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        out[f"{season}_residual_slope"] = (
            sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            / sum((x - mx) ** 2 for x in xs))
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
