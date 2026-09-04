"""Derive the two league baselines the mechanism predicates compare against.

WHY A SCRIPT AND NOT A SETTLEMENT-TIME COMPUTATION
----------------------------------------------------
A threshold that is recomputed every time settlement runs is a threshold
that quietly re-scores every pick already settled under the old one. So the
two numbers this prints are FROZEN as literals in
`src.engine.mechanism_predicates`, with their window and sample recorded in
docs/PREREG_MECHANISM_CHECKS.md, and this script exists so anyone can
reproduce them from the same store.

WHY A HELD-OUT WINDOW
-----------------------
The window is chosen to carry NO wager of this project's, so neither
baseline can be a function of a game we bet or an outcome we cared about.
This is the same posture `src.evolab.registry`'s threshold ladder takes: a
marginal distribution over games, with no price, no bet and no result of
ours anywhere in it.

    python3 scripts/derive_mechanism_baselines.py 2026-08-15 2026-08-27
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import gameflow  # noqa: E402
from src.review import mechanism_eval as me  # noqa: E402


def derive(start: str, end: str, path=None) -> dict:
    rows = gameflow.read(path or gameflow.default_store_path(start))
    game_pks = sorted({r.get("game_pk") for r in rows
                       if r.get("type") == gameflow.ROW_TYPE_GAME
                       and start <= (r.get("date") or "") <= end})
    pa = reached = ground = air = 0
    games = 0
    for game_pk in game_pks:
        flow = gameflow.load_game(rows, game_pk)
        if flow is None:
            continue
        games += 1
        plays = flow["plays"]
        for side in ("away", "home"):
            starter = me.starter_faced_by(plays, side)
            for play in me._pa_rows(plays, side, starter):
                pa += 1
                if play.get("event_type") in me.REACHED_BASE_EVENT_TYPES:
                    reached += 1
        for side in ("away", "home"):
            starter = me.starter_faced_by(plays, side)
            share, total = me.ground_ball_out_share(plays, starter)
            if share is not None:
                ground += round(share * total)
                air += total - round(share * total)
    return {
        "window": f"{start}..{end}", "games": games,
        "plate_appearances_vs_starters": pa, "reached": reached,
        "reached_base_rate": (reached / pa) if pa else None,
        "batted_ball_outs": ground + air, "ground_ball_outs": ground,
        "ground_ball_out_share": (ground / (ground + air)) if (ground + air) else None,
    }


if __name__ == "__main__":
    start, end = sys.argv[1], sys.argv[2]
    result = derive(start, end)
    for key, value in result.items():
        print(f"{key:34s} {value}")
