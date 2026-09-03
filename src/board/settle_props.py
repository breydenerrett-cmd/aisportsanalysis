"""Pure settlement rules for player-prop and game-state selections.

WHY THIS EXISTS
----------------
`src.pipeline.boxscores` stores the box line. Nothing turns a box line plus a
posted prop selection into a graded outcome -- that is what a backtest and a
self-review both need, and it is the ten-graded-examples gate this module
exists to satisfy. Every function here is pure: box row and selection in,
one of `win` / `loss` / `push` / `void` out. No I/O, no store, no network --
this module is deliberately NOT wired into the CLI or the daily loop yet.

WHAT "row" MEANS
-----------------
A `box row` is one row from a `data/processed/boxscores_<yyyy>.jsonl` store
as produced by `src.pipeline.boxscores.build_rows` / `src.providers.mlb.
parse_boxscore` / `parse_linescore` -- a dict with a `type` of `"pitcher"`,
`"batter"`, or `"linescore"`, plus the stat fields those functions write.

WHAT A SELECTION MEANS
------------------------
`{"subject_id": <player_id or None>, "stat": <str>, "line": "<decimal str>",
"side": "over" | "under"}`. `line` is a STRING on purpose -- "6.5" parses to
an exact float with no surprise, but a caller that already has a float
(6.4999999999) would silently mis-grade a push-adjacent line; forcing the
string in front of the parse makes that mistake visible at the call site
instead of buried in this module.

PUSH VS VOID
-------------
A `push` is a real graded outcome: the stat lands exactly on a line that
allows a tie (an integer stat against a whole-number line, e.g. 6 Ks vs a
6.0 line -- .5 lines never push). A `void` is not a graded outcome at all:
the row does not exist for the requested subject (wrong player_id, or the
`type` does not carry that stat, e.g. asking a `linescore` row for a batter
stat) or the game was not settleable (row is absent). Never fabricated:
`void` is the honest answer when the data cannot support a grade, not a
guess.
"""

from __future__ import annotations

# Stats that live on a "pitcher"-type box row.
PITCHER_STATS = frozenset({"outs", "ip", "h", "er", "r", "bb", "k", "pitches",
                            "batters_faced"})

# Stats that live on a "batter"-type box row, including the two computed at
# ingest time (total_bases, hits_runs_rbi).
BATTER_STATS = frozenset({"pa", "ab", "h", "doubles", "triples", "hr", "r",
                           "rbi", "bb", "k", "sb", "total_bases",
                           "hits_runs_rbi"})

# Stats that live on the "linescore" row and are not keyed by a player at all.
GAME_STATS = frozenset({"first_inning_scored"})


class SettleError(RuntimeError):
    """Raised when a selection itself is malformed (not when data is missing --
    a missing row grades `void`, it does not raise)."""


def settle(row: dict | None, selection: dict) -> str:
    """Grade one selection against one box row. Returns win/loss/push/void.

    `row` is the box-store row for the selection's subject (the caller is
    responsible for finding it -- this function does not search a store, it
    grades one row it is handed). `row=None` means "no row for this subject
    in this game" and always grades `void`.
    """
    stat = selection.get("stat")
    side = selection.get("side")
    if side not in ("over", "under"):
        raise SettleError(f"side must be 'over' or 'under', got {side!r}")

    if row is None:
        return "void"

    if stat in GAME_STATS:
        return _settle_boolean_stat(row, stat, selection)

    line = _parse_line(selection.get("line"))
    row_type = row.get("type")
    # "h" (hits) is a legitimate stat name on BOTH families -- a pitcher's
    # hits allowed and a batter's hits are different numbers on different
    # row shapes. Deciding by the ROW's own type first (rather than by
    # membership in one set checked before the other) is what makes both
    # readings reachable instead of one silently shadowing the other.
    if row_type == "pitcher":
        if stat not in PITCHER_STATS:
            return "void"
    elif row_type == "batter":
        if stat not in BATTER_STATS:
            return "void"
    elif stat not in (PITCHER_STATS | BATTER_STATS):
        raise SettleError(f"unknown stat {stat!r}")
    else:
        return "void"

    subject_id = selection.get("subject_id")
    if subject_id is not None and row.get("player_id") != subject_id:
        return "void"

    value = row.get(stat)
    if value is None:
        return "void"

    return _grade_over_under(float(value), line, side)


def _settle_boolean_stat(row: dict, stat: str, selection: dict) -> str:
    if row.get("type") != "linescore":
        return "void"
    value = row.get(stat)
    if value is None:
        return "void"
    side = selection["side"]
    happened = bool(value)
    if side == "over":  # "over" == yes for a boolean prop
        return "win" if happened else "loss"
    return "loss" if happened else "win"


# Catalogue settlement_rule name -> the box-row stat it grades. Every key
# here matches a MARKET_CATALOGUE market key exactly (props are named the
# same as their settlement rule -- there is no indirection to keep track
# of), and every value is a key in PITCHER_STATS or BATTER_STATS above.
PROP_STAT_RULES: dict[str, str] = {
    "pitcher_strikeouts": "k",
    "pitcher_outs": "outs",
    "pitcher_hits_allowed": "h",
    "pitcher_earned_runs": "er",
    "pitcher_walks": "bb",
    "batter_hits": "h",
    "batter_total_bases": "total_bases",
    "batter_home_runs": "hr",
    "batter_rbis": "rbi",
    "batter_runs": "r",
    "batter_walks": "bb",
    "batter_strikeouts": "k",
    "batter_stolen_bases": "sb",
    "batter_hits_runs_rbis": "hits_runs_rbi",
}


def _make_stat_rule(stat: str):
    """Bind `settle` to one fixed stat, giving a callable(row, selection)
    that ignores whatever `stat` the caller's selection carries and grades
    the stat this catalogue entry actually names -- the registry key is the
    stat, the selection only needs to carry subject_id/line/side."""

    def rule(row, selection):
        bound_selection = dict(selection, stat=stat)
        return settle(row, bound_selection)

    rule.__name__ = f"settle_props_{stat}"
    return rule


# The callables registered into src.board.settle.SETTLEMENT_RULES. Built once
# at import time; register_all() below is what actually plugs them in, kept
# separate so importing this module never has the side effect of mutating a
# different module's shared registry.
PROP_SETTLEMENT_RULES: dict[str, object] = {
    key: _make_stat_rule(stat) for key, stat in PROP_STAT_RULES.items()
}

_registered = False


def register_all() -> None:
    """Plug every prop settlement rule into src.board.settle's registry.

    Idempotent: calling this more than once (e.g. because both
    src.board.__init__ and a direct importer call it) is safe -- register_rule
    itself already refuses to silently overwrite a *different* callable, and
    the module-level flag here just avoids the redundant work, not a
    correctness requirement.
    """
    global _registered
    if _registered:
        return
    from src.board import settle as settle_module

    for key, fn in PROP_SETTLEMENT_RULES.items():
        settle_module.register_rule(key, fn, kind="prop")
    _registered = True


def _parse_line(raw) -> float:
    if not isinstance(raw, str):
        raise SettleError(f"line must be a decimal string, got {raw!r}")
    try:
        return float(raw)
    except ValueError as exc:
        raise SettleError(f"line must parse as a number, got {raw!r}") from exc


def _grade_over_under(value: float, line: float, side: str) -> str:
    if value == line:
        return "push"
    cleared = value > line
    if side == "over":
        return "win" if cleared else "loss"
    return "loss" if cleared else "win"
