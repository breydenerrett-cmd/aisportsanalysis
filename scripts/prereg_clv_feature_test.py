#!/usr/bin/env python3
"""Run the pre-registered forward test in docs/PREREG_CLV_FEATURE_LEAD.md.

THE SPEC IS THE DOCUMENT, NOT THIS FILE. Every parameter below is copied from
the pre-registration and must not be edited to change an answer -- that is
`docs/RESEARCH_CATALOGUE.md` T8, "no rescue by threshold change," and it is
the only thing that makes a forward test worth running at all.

The test exists as a script rather than as a note-to-self because the failure
mode of a hypothesis nobody automated is that it quietly never gets tested,
and the person who would have run it is the same person hoping it works.

Reports one of three states and nothing else:

  PENDING       fewer than the pre-registered 60 games have accumulated
  SUPPORTED     effect > 0 and one-sided p < 0.05
  NOT SUPPORTED anything else, INCLUDING a large effect that misses p, and a
                large NEGATIVE effect (H1 is directional -- a negative result
                refutes it, it does not become a discovery about the other
                direction)
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# --- Copied verbatim from the pre-registration. Do not tune. ---------------
FEATURE = "lineup_vs_primary_pitch"
WINDOW_START_UTC = "2026-09-10T00:00:00+00:00"
MIN_GAMES = 60
TRIALS = 10_000
ALPHA = 0.05
SEED = 20260910
DOC = "docs/PREREG_CLV_FEATURE_LEAD.md"


def _features_by_system():
    from src.engine.adapters import evolab_system
    out = {}
    for system in evolab_system.REGISTERED_SYSTEMS:
        sid = getattr(system, "id", None)
        genome = getattr(system, "genome", None)
        if not sid or genome is None:
            continue
        signals = genome.to_dict().get("signals") or []
        out[sid] = {s.get("feature") for s in signals if isinstance(s, dict)}
    return out


def _effect(sample, feats):
    with_f = [r["move"] for r in sample if r["has"]]
    without = [r["move"] for r in sample if not r["has"]]
    if not with_f or not without:
        return None
    return statistics.mean(with_f) - statistics.mean(without)


def run():
    from src.report import clv

    feats = _features_by_system()
    skipped_no_time = [0]
    eligible_before_window = [0]
    rows = []
    for m in clv.measure():
        if not clv.is_publishable(m):
            continue
        if m.get("consensus_move_bps") is None:
            continue
        sid = m.get("system_id")
        if sid not in feats:
            continue
        # DECISION time, per the amendment recorded in the document. Read
        # from one named field with no fallback chain: a fallback would let a
        # renamed field quietly admit or exclude everything, and the window
        # is the axis that decides what is admissible at all.
        frozen = m.get("decision_utc")
        if not frozen:
            skipped_no_time[0] += 1
            continue
        if str(frozen) < WINDOW_START_UTC:
            eligible_before_window[0] += 1
            continue
        rows.append({"game": m.get("game_pk") or m.get("event_id"),
                     "system": sid,
                     "has": FEATURE in feats[sid],
                     "move": m["consensus_move_bps"]})

    games = {r["game"] for r in rows}
    print(f"pre-registered test: {DOC}")
    print(f"feature   : {FEATURE}")
    print(f"window    : decision frozen >= {WINDOW_START_UTC}")
    print(f"accrued   : {len(rows)} decisions over {len(games)} games "
          f"(need {MIN_GAMES})")

    # A filter that silently matches nothing looks exactly like a window that
    # has not filled yet, and would sit at PENDING forever without anyone
    # noticing. These two lines make the difference visible: rows that were
    # publishable but fell before the window prove the pipeline reaches this
    # code, and a row missing decision_utc entirely is a schema change, not a
    # quiet day.
    print(f"  (publishable but pre-window: {eligible_before_window[0]}; "
          f"missing decision_utc: {skipped_no_time[0]})")
    if skipped_no_time[0]:
        print("  WARNING: rows without decision_utc -- the CLV row schema "
              "may have changed; this test's window would silently exclude "
              "them all")

    if len(games) < MIN_GAMES:
        print(f"\nVERDICT: PENDING -- {MIN_GAMES - len(games)} more games "
              f"needed. The window does not get shortened.")
        return 0

    obs = _effect(rows, feats)
    if obs is None:
        print("\nVERDICT: NOT SUPPORTED -- one arm is empty, so no "
              "comparison exists")
        return 1

    by_game = defaultdict(list)
    for r in rows:
        by_game[r["game"]].append(r)

    rng = random.Random(SEED)
    null = []
    for _ in range(TRIALS):
        shuffled = []
        for game_rows in by_game.values():
            flags = [r["has"] for r in game_rows]
            rng.shuffle(flags)
            for r, flag in zip(game_rows, flags):
                shuffled.append({"has": flag, "move": r["move"]})
        e = _effect(shuffled, feats)
        if e is not None:
            null.append(e)

    p = sum(1 for e in null if e >= obs) / len(null)   # one-sided, directional
    print(f"\nobserved effect: {obs:+.2f} bps")
    print(f"permuted null  : mean {statistics.mean(null):+.2f}, "
          f"95th pct {sorted(null)[int(.95 * len(null))]:+.2f}")
    print(f"one-sided p    : {p:.4f}  (threshold {ALPHA})")

    if obs > 0 and p < ALPHA:
        print("\nVERDICT: SUPPORTED")
        print("  Licenses a pre-registered, versioned, FORWARD-EPOCH-ONLY "
              "ranker change. Licenses no customer-facing edge claim, no win "
              "probability, and no variable staking.")
        return 0

    print("\nVERDICT: NOT SUPPORTED")
    print("  Reported as-is. The window is not extended, the threshold is "
          "not moved, and no other feature is promoted in its place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
