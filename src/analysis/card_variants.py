"""T2v -- the variant runner. Four arms, one shared candidate pool.

WHY THIS FILE EXISTS AND WHAT IT MUST NEVER DO
-----------------------------------------------
Registration section 17 answers question 12 with a family of four rule
variants instead of a single disputed constant. All four have to prove, on
every publish run, that they screened the identical board -- otherwise a
"the loose arm found more picks" claim could just as easily mean the loose
arm was handed a fresher or larger pool. `pool_hash` is the mechanism that
makes that claim checkable rather than trusted (registration 17.6).

This module is deliberately **not** part of the registration's
`code_fingerprint` (11.2): the four arms all select through
`best_bets_card.select`, so nothing in this file can change what A1 actually
publishes. Its own sha256 becomes the `code_hash` on T0d's alpha-registry
sweep row instead, which is the correct place to pin "did the runner change"
without conflating it with "did the published rule change".

THE CONSTRAINT THAT IS PART OF THE REGISTRATION, NOT A STYLE CHOICE
---------------------------------------------------------------------
Registration 17.4 clause 4 promotes an arm only on its own sealed-window
verdict, read at the registered floors, months from now. A running
per-arm win-loss-units line would let anyone (including us) watch the arms
race in real time and be tempted to act on it before the sample is real --
exactly the p-hacking-by-dashboard failure the four-arm design is supposed to
prevent. So this module computes and exposes:

  - that the arms screened the same pool (`pool_hash`, identical across arms)
  - how far apart the arms' SELECTIONS sit, per date (`discordant`, on
    picks only, no dollar or unit figure attached)
  - nothing else. There is no `arm_record`, `arm_scoreboard`, or any function
    that returns each arm's win-loss-units -- see
    `tests/test_card_variants_one_board.py` for the test that pins this
    absence structurally, not just by convention.

Every `now` is an argument. There is no clock read here, no file read, no
capture-client import: the candidate pool is handed in by the caller that
already paid for the capture (registration 17.6's "zero additional API
spend, by construction").
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

from src.analysis import best_bets_card

# The family's alpha-registry identity (T0d writes this into the sweep row
# alongside this module's own sha256). Not a rule_id -- rule_ids stay on
# best_bets_card.RuleParams, one per arm.
FAMILY_ID = "CARD_V2_VARIANTS_2026_09"

# Re-exported rather than redefined: best_bets_card.ARMS/PUBLISHED_ARM are
# already the ordered {"A1": ..., "A2": ..., "A3": ..., "A4": ...} mapping
# registration 17.1 specifies, built by `dataclasses.replace(V2, ...)` so a
# fifth field can never drift silently (see that module's own comment above
# A1/A2/A3/A4). Redefining them here would create a second source of truth
# for exactly the thing registration 17.1 says must not vary accidentally.
ARMS = best_bets_card.ARMS
PUBLISHED_ARM = best_bets_card.PUBLISHED_ARM


def _canonical(value: Any) -> Any:
    """Recursively sort mapping keys and coerce to JSON-stable primitives so
    `pool_hash` depends only on the candidate pool's *content*, never on
    dict insertion order or object identity. Candidates arrive as plain
    Mapping/Sequence/scalar data (the shape `select()` itself consumes), so
    this does not need to handle arbitrary Python objects."""
    if isinstance(value, Mapping):
        return {k: _canonical(value[k]) for k in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def pool_hash(candidates: Sequence[Mapping[str, Any]]) -> str:
    """sha256 over a canonical JSON serialisation of the candidate pool.

    Two arms given the same pool object, or two equal-but-distinct pool
    objects, always produce the same value; any difference in the board --
    a stale read, a partial capture, a candidate one arm didn't see -- is
    visible as a hash mismatch rather than something only discoverable by
    diffing every row by hand.
    """
    canon = [_canonical(dict(c)) for c in candidates]
    blob = json.dumps(canon, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def run_family(
    candidates: Sequence[Mapping[str, Any]],
    *,
    now: Any,
    prior_by_arm: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict:
    """Run all four arms on the same in-memory pool, once each.

    `candidates` is passed by reference to every arm's `select()` call --
    never copied, never re-derived -- so "all four arms screened the same
    pool" is true by construction and not merely by the hash matching after
    the fact (the hash is still attached so a caller can *prove* it without
    re-deriving anything). `select()` itself does not mutate its
    `candidates` argument (it builds a new dict per candidate internally),
    so passing the identical object to all four calls is safe.
    """
    prior_by_arm = prior_by_arm or {}
    shared_hash = pool_hash(candidates)

    results: dict = {}
    for arm_id, params in ARMS.items():
        result = best_bets_card.select(
            candidates,
            now=now,
            params=params,
            prior=prior_by_arm.get(arm_id),
        )
        result["pool_hash"] = shared_hash
        result["family_id"] = FAMILY_ID
        result["arm"] = arm_id
        result["published"] = arm_id == PUBLISHED_ARM
        results[arm_id] = result
    return results


def _pick_identity(entry: Mapping[str, Any]) -> tuple:
    """The frozen identity a pick is compared on: game/player, market, side
    and line, deliberately NOT price or score, because two arms disagreeing
    on markdown can price the same bet differently without that being a
    "different pick" for discordance purposes."""
    return (
        entry.get("player_id") or entry.get("game_id") or entry.get("game_pk"),
        entry.get("market"),
        entry.get("side"),
        entry.get("line"),
    )


def _picks_by_class(result: Mapping[str, Any], price_class: Optional[str]) -> dict:
    all_picks = list(result.get("picks") or ()) + list(result.get("prop_picks") or ())
    return {
        _pick_identity(p): p
        for p in all_picks
        if price_class is None or p.get("price_class") == price_class
    }


def discordant(
    result_a: Mapping[str, Any],
    result_b: Mapping[str, Any],
    *,
    price_class: Optional[str] = None,
) -> dict:
    """The discordant set between two arms' results, on picks only.

    Registration 17.4 clause 2 requires both directions computed on every
    read ("G11's dedup and G12's ceiling can reshuffle when the scores
    change and nesting is not guaranteed by construction"), so this returns
    `only_a` and `only_b` separately rather than a single symmetric-
    difference count that would hide which side actually has the extra
    picks. It is a description, not a statistic: no CLV, no units, no
    win-loss anywhere near it -- that belongs to the sealed-window read in
    T8v, not to a function every publish run calls.
    """
    picks_a = _picks_by_class(result_a, price_class)
    picks_b = _picks_by_class(result_b, price_class)
    keys_a, keys_b = set(picks_a), set(picks_b)
    only_a = [picks_a[k] for k in sorted(keys_a - keys_b, key=str)]
    only_b = [picks_b[k] for k in sorted(keys_b - keys_a, key=str)]
    shared = [picks_a[k] for k in sorted(keys_a & keys_b, key=str)]
    return {"only_a": only_a, "only_b": only_b, "shared": shared}
