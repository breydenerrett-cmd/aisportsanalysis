"""Is the batter-prop board's probability calibrated against what actually
happened, and how does it compare to the market's own de-vigged number on
the same contracts?

WHY THIS EXISTS, DATED 2026-09-14
----------------------------------
`scripts/backtest_player_props.py` already measures whether `playerprops`
is calibrated, but it prices the DEFAULT line for a market
(`DEFAULT_LINES`), not the line a book actually quoted, and it never reads
a market price at all -- "no price was read by this script" is its own
closing line. `src.analysis.propboard`'s module docstring separately
measures that ranking BY the gap against the market is a losing strategy
(-13.4% vs -9.1%), but that measurement is about SELECTION, not about
whether either number -- ours or the market's -- is honest on its own.

Today's card (2026-09-14) is shipping zero prop picks (no lineup has
posted yet) and the live prop BOARD's top likely-and-clears-price contracts
are dominated by Coors Field unders where our number sits far above the
market's (Cronenworth Under 1.5 at -220: ours 84%, market 65%). That gap is
either a real edge or a park/pitcher blind spot in the model
(`playerprops.py`'s own docstring: "No park factor... No platoon split").
This script is how to tell the two apart with settled outcomes rather than
a hunch.

WHAT IT MEASURES
-----------------
For every settled contract in `batter_hits`, `batter_total_bases`, and
`batter_runs_scored` (both sides, one row per player-market-line-side per
date, using the LAST quote observed strictly before that game's first
pitch): the outcome (win/loss, via `src.board.settle_props.settle`), our
model's point-in-time probability (the board rebuilt exactly as
`src.report.props.board_for_date` builds it -- same league-rates-from-
history, same prior-box-scores-strictly-before-date, same posted-lineup
slot when one existed for that date), and the market's de-vigged
probability on the same contract.

POINT-IN-TIME, NOT RECORDED-ON-THE-ROW
----------------------------------------
`data/processed/batter_props.jsonl` carries a raw odds quote -- price, book,
observed_utc -- and NO model probability. There is nothing to read off the
row. So this script REBUILDS the board for each historical slate date using
only data that predates it: `playerprops.league_rates` over every batter
game strictly before the date, each batter's own prior game log (same
`<` -- never `<=`), and that date's posted lineup from
`data/historical/lineups.jsonl` when one exists (absent, `price_prop` falls
back to the batter's season average and the contract says which it used, in
`expected_pa_source`). This is what `propboard.build` already does; this
script drives it over one historical date at a time, the way
`backtest_player_props.py` drives `playerprops.price_prop` directly.

ONE THING THIS CANNOT RULE OUT, STATED UP FRONT: the boxscore store
(`data/processed/boxscores_2026.jsonl`) only goes back to 2026-08-30. A
prediction for 2026-09-03 sees at most four days of history, which is far
short of the `PA_REGRESSION=200`/`MIN_PA_FOR_A_RATE=40` design point and
will refuse most batters outright (counted in `refused`) rather than
publish a threadbare number. That is a POWER problem, not a LEAKAGE
problem -- no game contributes to its own prediction anywhere in this
script -- and the reliability table's early dates should be read
accordingly thin.

THE SETTLEMENT-RULE NAME MISMATCH, ALREADY DOCUMENTED, WORKED AROUND HERE
----------------------------------------------------------------------------
`src.board.daily_card` (around `PROP_MARKETS`, 2026-09-12 incident) already
records that `src.board.settle_props`'s registry keys runs as
`"batter_runs"`, not `propboard`'s own `"batter_runs_scored"` -- a contract
in that market would grade VOID forever if graded through the registry by
market name. This script never goes through the registry: `outcome_for_contract`
below calls `settle_props.settle()` directly with the STAT this module's own
`STAT_FOR_MARKET` names (`"r"`), bypassing the mismatched catalogue key
entirely. Existing behaviour (why the live card excludes runs from
`PROP_MARKETS`) is unaffected; this script only reads.

Deterministic. stdlib only. No network, no write to any store this project
reads from.

Usage:
    python scripts/probe_prop_calibration.py [--json] [--min-gap 0.10]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis import playerprops, propboard  # noqa: E402
from src.board import gamekey, settle_props  # noqa: E402
from src.paths import processed_path  # noqa: E402
from src.pipeline import batter_props, boxscores, lineup_store  # noqa: E402

BOX_STORE = processed_path("boxscores_2026.jsonl")
EPS = 1e-9

# The three markets this probe measures, named by the owner's brief
# (2026-09-14). `batter_home_runs` is excluded on purpose: no book quotes
# the under (`playerprops.NOT_DEVIGGABLE`), so there is no market
# probability to compare against. `batter_rbis` and
# `batter_hits_runs_rbis` are excluded because `playerprops.NOT_PUBLISHABLE`
# already measured them worse than a base rate -- there is nothing this
# script would tell a reader that module does not already say louder.
TARGET_MARKETS = ("batter_hits", "batter_total_bases", "batter_runs_scored")

# market -> the boxscore stat `src.board.settle_props.settle` grades it
# against. See the module docstring's note on the registry name mismatch
# for why this is read directly rather than through
# `settle_props.PROP_STAT_RULES`.
STAT_FOR_MARKET = {
    "batter_hits": "h",
    "batter_total_bases": "total_bases",
    "batter_runs_scored": "r",
}

# The reliability table's bucket edges, fixed by the brief.
BUCKET_EDGES = (0.5, 0.6, 0.7, 0.8)

# Below this a split is reading noise rather than a signal, and the report
# says so instead of printing a confident-looking number over 6 contracts.
MIN_SPLIT_N = 20

DEFAULT_SEED = 20260914
DEFAULT_BOOTSTRAP_ITERATIONS = 2000
DEFAULT_CI_ALPHA = 0.10  # a 90% CI -- fixed here, not tuned after looking


class ProbeError(ValueError):
    """The inputs cannot support this probe. Never raised for one bad row."""


# ---------------------------------------------------------------------------
# Pure functions: bucketing, scoring, the join. Exercised directly by
# tests/test_probe_prop_calibration.py on synthetic rows, no store involved.
# ---------------------------------------------------------------------------

def bucket_label(p: Optional[float]) -> Optional[str]:
    """Which reliability bucket `p` falls in, or None below the floor.

    The brief's four buckets are 0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8+. A
    probability below 0.5 is the DISFAVOURED side of some other contract's
    pair and is not a number this board would ever surface as a pick, so it
    is excluded from the table rather than binned somewhere misleading.
    """
    if p is None:
        return None
    if p < BUCKET_EDGES[0]:
        return None
    if p >= BUCKET_EDGES[-1]:
        return f"{BUCKET_EDGES[-1]:.0%}+"
    for lo, hi in zip(BUCKET_EDGES, BUCKET_EDGES[1:]):
        if lo <= p < hi:
            return f"{lo:.0%}-{hi:.0%}"
    return None  # unreachable given the checks above; no silent fallthrough


def _bucket_order() -> list:
    labels = [f"{lo:.0%}-{hi:.0%}"
              for lo, hi in zip(BUCKET_EDGES, BUCKET_EDGES[1:])]
    labels.append(f"{BUCKET_EDGES[-1]:.0%}+")
    return labels


def brier_score(pairs: Sequence[tuple]) -> Optional[float]:
    """Mean squared error of probability against outcome. Lower is better.
    None on an empty input -- 0.0 would claim a perfect score for no data."""
    if not pairs:
        return None
    return statistics.fmean((p - y) ** 2 for p, y in pairs)


def log_loss(pairs: Sequence[tuple]) -> Optional[float]:
    """Mean negative log-likelihood, clamped away from the 0/1 boundary the
    same way `backtest_player_props.py`'s `_log_loss` does, so one perfect-
    looking prediction cannot blow the whole mean up to infinity."""
    if not pairs:
        return None
    return statistics.fmean(
        -(y * math.log(min(max(p, EPS), 1 - EPS))
          + (1 - y) * math.log(1 - min(max(p, EPS), 1 - EPS)))
        for p, y in pairs)


def _line_str(line) -> str:
    """`settle_props._parse_line` insists on a decimal STRING on purpose
    (its own docstring: a caller's float "would silently mis-grade a push-
    adjacent line"). Every line this probe ever sees came IN as a string
    from the quote store and was turned into a float by `propboard.build`
    (`line = float(line_text)`); the three values in play (0.5, 1.5, 2.5)
    round-trip through `str(float(...))` exactly, so converting back here
    is not the lossy step the original warning is about.
    """
    return str(float(line))


def outcome_for_contract(contract: Mapping, box_row: Optional[Mapping]) -> str:
    """Grade one propboard contract against one boxscore batter row.

    Returns `win` / `loss` / `push` / `void`, exactly `settle_props.settle`'s
    vocabulary -- this is a thin adapter from a propboard contract's shape
    to a settle_props selection's shape, not a second settlement rule.
    `subject_id` is left unchecked (None): the caller already found `box_row`
    by matching player NAME to `date` (the only join key the prop feed and
    the box score share -- see `src.report.props._by_name`), so a second
    identity check here has nothing independent to verify against.
    """
    market = contract.get("market")
    stat = STAT_FOR_MARKET.get(market)
    if stat is None:
        raise ProbeError(f"no stat mapping for market {market!r}")
    side = str(contract.get("side") or "").lower()
    selection = {"subject_id": None, "stat": stat,
                 "line": _line_str(contract.get("line")), "side": side}
    return settle_props.settle(box_row, selection)


def to_y(outcome: str) -> Optional[int]:
    """win -> 1, loss -> 0, push/void -> None (excluded, not scored as a
    loss -- a push is not a miss and a void is not a fact about the model
    at all)."""
    if outcome == "win":
        return 1
    if outcome == "loss":
        return 0
    return None


# ---------------------------------------------------------------------------
# Store loading and point-in-time board reconstruction
# ---------------------------------------------------------------------------

def _by_name_index(batter_rows: Sequence[Mapping]) -> dict:
    """{player_name: [batter box rows, oldest first]}. Mirrors
    `src.report.props._by_name` exactly (same join key, same reason: the
    prop feed carries no player id)."""
    out: dict = {}
    for row in batter_rows:
        name = row.get("player_name")
        if name:
            out.setdefault(name, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: str(r.get("date") or ""))
    return out


def _box_row_for(by_name: Mapping, player: Optional[str], date: str,
                  home_team: Optional[str] = None,
                  away_team: Optional[str] = None) -> Optional[dict]:
    """This batter's own box row for `date`, or None. None is not an error
    here -- `outcome_for_contract` reads it as `settle()` reads any missing
    row: a `void`, because a quote posted for a batter who did not appear
    that day (scratch, rainout) settles nothing.

    JOIN GUARD, dated 2026-09-14 (Opus checker finding #6): the prop feed
    carries no player id, so this join is by NAME + date alone, and the box
    store can hold two different players who share a name on the same
    date -- confirmed on this store: two different Max Muncys (person_id
    691777 and 571970) both have rows on 2026-09-09, 09-11 and 09-12,
    inside the settled window. Without a team check, whichever of the two
    happens to sit first in the file wins every time, by file order rather
    than by fact. `home_team`/`away_team` (the event's own teams, from the
    prop row) narrow the candidates to the one whose `team_name` was
    actually playing in THIS game; a same-name row for a different game
    is excluded rather than guessed at, so `outcome_for_contract` reads a
    `None` here as a `void`, same as a scratch. Callers that do not have
    team context (the unit tests exercising the join in isolation) pass
    neither and get the pre-fix, name-and-date-only behaviour -- kept only
    because there is nothing yet to disambiguate with, not because it is
    safe.
    """
    if not player:
        return None
    candidates = [row for row in by_name.get(player) or ()
                  if str(row.get("date") or "")[:10] == date]
    if not candidates:
        return None
    if home_team is None and away_team is None:
        return candidates[0]
    allowed = {team for team in (home_team, away_team) if team}
    for row in candidates:
        if row.get("team_name") in allowed:
            return row
    return None


def _game_pk_commence_index() -> dict:
    """{str(game_pk): commence_time} from the event_id<->game_pk resolver
    store (`src.board.gamekey.load_map`) -- the only place this project
    records a UTC start time keyed by MLB `game_pk`, which is what
    `lineup_store` rows key on and carry no commence_time of their own.
    Needed by `_slots_for_date`'s leakage guard below; read once per probe
    run rather than once per date."""
    index: dict = {}
    for row in gamekey.load_map().values():
        game_pk = row.get("game_pk")
        commence = row.get("commence_time")
        if game_pk and commence:
            index[str(game_pk)] = commence
    return index


def _slots_for_date(date: str, lineup_index: Mapping,
                     game_pk_commence: Mapping) -> dict:
    """{player_name: batting slot} from the historical lineup store for
    `date`, or {} if none posted (or none provably PRE-first-pitch -- see
    below). Same slot logic as `src.report.props._slots_for`, reimplemented
    against an already-loaded `lineup_index` (`lineup_store.read()`) rather
    than importing that module's private helper, so this file owns its own
    small surface.

    LEAKAGE GUARD, dated 2026-09-14 (Opus checker finding #1): the live
    board only ever reads TODAY's lineup store, so a row in it is, in
    practice, always observed before that game's first pitch -- nothing
    enforces that in `lineup_store` itself, though, and replaying PAST
    dates breaks the assumption: `lineup_store.build` is commonly run well
    after a slate finishes (catching up the historical backfill), so a
    stored row's `observed_utc` is routinely AFTER the game it describes.
    Measured on this store as of 2026-09-14 (checker's own count): 64 of 65
    lineup rows were observed after their game's commence_time -- e.g.
    every 2026-09-09 game's lineup carries `observed_utc`
    "2026-09-10T10:11Z", fetched the next morning. Using that batting
    order would let the order that ACTUALLY took the field (which the
    market and the box score both already reflect) inform this probe's
    prediction for that same game -- a look-ahead the live board could
    never have had. So a lineup entry is used here only when its own
    `observed_utc` predates that entry's own `game_pk`'s `commence_time`
    (from `_game_pk_commence_index`); every other entry -- including one
    whose game_pk cannot be resolved to a commence_time at all -- is
    dropped, and `propboard.build`/`playerprops.price_prop` falls back to
    that batter's season average for it, exactly as for a game with no
    lineup posted yet.
    """
    slots: dict = {}
    for entry in (lineup_index or {}).values():
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("date") or "")[:10] != date:
            continue
        observed = entry.get("observed_utc")
        commence = game_pk_commence.get(str(entry.get("game_pk")))
        if not observed or not commence or observed >= commence:
            continue
        for side in ("away", "home"):
            for index, batter in enumerate(entry.get(side) or [], start=1):
                if not isinstance(batter, Mapping):
                    continue
                name = batter.get("name")
                try:
                    slot = int(batter.get("order") or index)
                except (TypeError, ValueError):
                    slot = index
                if name and 1 <= slot <= 9:
                    slots[name] = slot
    return slots


def _pre_first_pitch(rows: Sequence[Mapping]) -> list:
    """Only quotes observed strictly before that event's own commence_time.
    ISO-8601 Zulu strings compare correctly lexically -- the same assumption
    `propboard._newest_quotes` already makes for "newest" comparisons.
    Measured on the current store (2026-09-14): zero of 32,618 target-market
    rows fail this filter, i.e. nothing here has ever captured an in-game
    quote, but the filter is kept rather than trusted to stay that way."""
    return [r for r in rows
            if (r.get("observed_utc") or "") < (r.get("commence_time") or "")]


def build_date_contracts(date: str, prop_rows_all: Sequence[Mapping],
                          by_name: Mapping, all_batter_rows: Sequence[Mapping],
                          lineup_index: Mapping, game_pk_commence: Mapping) -> tuple:
    """One slate date's full contract population for `TARGET_MARKETS`,
    rebuilt exactly as `src.report.props.board_for_date` builds a live
    board, for a date the live board never actually ran against.

    Returns `(contracts, refused)`. `contracts` is `propboard.build`'s own
    unfiltered list -- BOTH sides of every contract, not `most_likely`'s
    probability > 0.5 subset -- because a Brier/log-loss/reliability report
    needs the full population this board ever prices, not just the half it
    would show a reader.
    """
    rows_for_date = _pre_first_pitch([
        r for r in prop_rows_all
        if r.get("game_date") == date and r.get("market") in TARGET_MARKETS])
    if not rows_for_date:
        return [], {}

    history = [r for r in all_batter_rows
               if str(r.get("date") or "")[:10] < date]
    if not history:
        return [], {"no_batter_history_before_this_date": len(rows_for_date)}
    try:
        league = playerprops.league_rates(history)
    except playerprops.PropError as exc:
        return [], {f"no_league_rate: {exc}": len(rows_for_date)}

    slots = _slots_for_date(date, lineup_index, game_pk_commence)
    built = propboard.build(rows_for_date, date=date, batters_by_name=by_name,
                            league=league, slots_by_player=slots)
    return built["contracts"], built["refused"]


def _group_refusal(reason: str) -> str:
    """Collapse `propboard.build`'s refusal reasons into a handful of
    buckets a reader can actually scan. `playerprops.PropError`'s "N plate
    appearances is below the 40 floor" message embeds the exact count, so
    grouping by the raw string (propboard's own dict key) produces one
    bucket per distinct PA count -- the same trap
    `backtest_player_props.py`'s `main()` already names and works around
    ("keying on the raw text produced one bucket per distinct
    plate-appearance count -- forty lines of noise"); this does the same
    grouping here rather than reinventing a different one."""
    if "below the" in reason and "floor" in reason:
        return "below the plate-appearance floor"
    return reason


def collect_records(prop_rows_all: Sequence[Mapping],
                     all_batter_rows: Sequence[Mapping],
                     lineup_index: Mapping) -> tuple:
    """Every settled (win/loss) contract across every slate date the store
    holds, plus the census of what could not be priced or could not be
    settled, so a thin-looking result is visibly thin rather than silently
    filtered.

    Returns `(records, refused_totals, outcome_totals)`.
    """
    by_name = _by_name_index(all_batter_rows)
    dates = sorted({r.get("game_date") for r in prop_rows_all
                    if r.get("market") in TARGET_MARKETS
                    and r.get("game_date")})
    game_pk_commence = _game_pk_commence_index()

    records: list = []
    refused_totals: Counter = Counter()
    outcome_totals: Counter = Counter()

    for date in dates:
        contracts, refused = build_date_contracts(
            date, prop_rows_all, by_name, all_batter_rows, lineup_index,
            game_pk_commence)
        for reason, n in refused.items():
            refused_totals[_group_refusal(reason)] += n

        home_by_event: dict = {}
        away_by_event: dict = {}
        for row in prop_rows_all:
            if row.get("game_date") != date:
                continue
            event_id = row.get("event_id")
            if event_id and event_id not in home_by_event:
                home_by_event[event_id] = row.get("home_team")
                away_by_event[event_id] = row.get("away_team")

        for contract in contracts:
            event_id = contract.get("event_id")
            box_row = _box_row_for(
                by_name, contract.get("player"), date,
                home_team=home_by_event.get(event_id),
                away_team=away_by_event.get(event_id))
            outcome = outcome_for_contract(contract, box_row)
            outcome_totals[outcome] += 1
            y = to_y(outcome)
            if y is None:
                continue
            p_model = contract.get("probability")
            p_market = contract.get("market_probability")
            if p_model is None:
                continue
            records.append({
                "date": date,
                "player": contract.get("player"),
                "market": contract.get("market"),
                "line": contract.get("line"),
                "side": contract.get("side"),
                "p_model": float(p_model),
                "p_market": (None if p_market is None else float(p_market)),
                "expected_pa_source": contract.get("expected_pa_source"),
                "home_team": home_by_event.get(contract.get("event_id")),
                "coors": home_by_event.get(contract.get("event_id"))
                         == "Colorado Rockies",
                "y": y,
                "outcome": outcome,
            })

    return records, refused_totals, outcome_totals


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def reliability_table(records: Sequence[Mapping], prob_key: str) -> list:
    buckets = defaultdict(list)
    for r in records:
        p = r.get(prob_key)
        label = bucket_label(p)
        if label is None:
            continue
        buckets[label].append((p, r["y"]))
    out = []
    for label in _bucket_order():
        rows = buckets.get(label) or []
        if not rows:
            out.append({"bucket": label, "n": 0})
            continue
        predicted = statistics.fmean(p for p, _ in rows)
        actual = statistics.fmean(y for _, y in rows)
        out.append({"bucket": label, "n": len(rows),
                    "predicted": round(predicted, 4),
                    "actual": round(actual, 4),
                    "gap": round(predicted - actual, 4)})
    return out


def _score_pairs(records: Sequence[Mapping], prob_key: str) -> Optional[dict]:
    pairs = [(r[prob_key], r["y"]) for r in records if r.get(prob_key) is not None]
    if not pairs:
        return None
    return {
        "n": len(pairs),
        "brier": round(brier_score(pairs), 5),
        "log_loss": round(log_loss(pairs), 5),
        "base_rate": round(statistics.fmean(y for _, y in pairs), 4),
        "mean_prediction": round(statistics.fmean(p for p, _ in pairs), 4),
    }


def scoreboard(records: Sequence[Mapping]) -> dict:
    with_market = [r for r in records if r.get("p_market") is not None]
    return {
        "n_total": len(records),
        "n_with_market_price": len(with_market),
        "ours": _score_pairs(records, "p_model"),
        "market": _score_pairs(with_market, "p_market"),
        "reliability_ours": reliability_table(records, "p_model"),
        "reliability_market": reliability_table(with_market, "p_market"),
    }


def _split_by(records: Sequence[Mapping], key) -> dict:
    groups = defaultdict(list)
    for r in records:
        groups[key(r)].append(r)
    out = {}
    for label, rows in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(rows) < MIN_SPLIT_N:
            out[str(label)] = {"n": len(rows),
                                "verdict": f"below the {MIN_SPLIT_N}-row floor"}
            continue
        out[str(label)] = scoreboard(rows)
    return out


def splits(records: Sequence[Mapping]) -> dict:
    return {
        "by_market": _split_by(records, lambda r: r["market"]),
        "by_side": _split_by(records, lambda r: r["side"]),
        "by_expected_pa_source": _split_by(
            records, lambda r: r.get("expected_pa_source") or "unknown"),
        "coors_vs_elsewhere": _split_by(
            records, lambda r: "coors" if r.get("coors") else "elsewhere"),
    }


def big_gap_question(records: Sequence[Mapping], min_gap: float) -> dict:
    """The owner's specific question: among contracts where OUR number
    exceeds the MARKET'S by `min_gap` or more, what actually happened --
    and how does that hit rate compare to each side's own prediction. This
    is exactly the population the current live prop board's top of the
    list is drawn from (Coors unders included), so this is the number that
    answers whether that top of the list is signal or a blind spot."""
    subset = [r for r in records
              if r.get("p_market") is not None
              and (r["p_model"] - r["p_market"]) >= min_gap]
    if len(subset) < MIN_SPLIT_N:
        return {"n": len(subset), "min_gap": min_gap,
                "verdict": f"below the {MIN_SPLIT_N}-row floor"}
    actual = statistics.fmean(r["y"] for r in subset)
    mean_ours = statistics.fmean(r["p_model"] for r in subset)
    mean_market = statistics.fmean(r["p_market"] for r in subset)
    coors_n = sum(1 for r in subset if r.get("coors"))
    return {
        "n": len(subset), "min_gap": min_gap,
        "actual_hit_rate": round(actual, 4),
        "mean_our_prediction": round(mean_ours, 4),
        "mean_market_prediction": round(mean_market, 4),
        "gap_vs_ours": round(mean_ours - actual, 4),
        "gap_vs_market": round(mean_market - actual, 4),
        "coors_rows": coors_n,
        "coors_share": round(coors_n / len(subset), 4),
    }


def bootstrap_brier_diff(records: Sequence[Mapping], *, seed: int = DEFAULT_SEED,
                          iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
                          alpha: float = DEFAULT_CI_ALPHA) -> Optional[dict]:
    """Date-clustered bootstrap CI on (our Brier - market Brier), seed fixed
    so the interval is reproducible rather than re-rolled per run. Clustered
    by DATE rather than by contract: contracts on the same slate share the
    same league-rate snapshot and often the same park/weather, so they are
    not independent draws, and resampling contracts directly would
    understate the true uncertainty.
    """
    with_market = [r for r in records if r.get("p_market") is not None]
    by_date = defaultdict(list)
    for r in with_market:
        by_date[r["date"]].append(r)
    dates = sorted(by_date)
    if not dates:
        return None

    point_our = brier_score([(r["p_model"], r["y"]) for r in with_market])
    point_mkt = brier_score([(r["p_market"], r["y"]) for r in with_market])
    if point_our is None or point_mkt is None:
        return None
    point_diff = point_our - point_mkt

    rng = random.Random(seed)
    diffs = []
    for _ in range(iterations):
        pooled = []
        for _pick in range(len(dates)):
            pooled.extend(by_date[dates[rng.randrange(len(dates))]])
        b_our = brier_score([(r["p_model"], r["y"]) for r in pooled])
        b_mkt = brier_score([(r["p_market"], r["y"]) for r in pooled])
        if b_our is None or b_mkt is None:
            continue
        diffs.append(b_our - b_mkt)

    if not diffs:
        return None
    diffs.sort()
    lo = diffs[max(0, int(len(diffs) * (alpha / 2)))]
    hi = diffs[min(len(diffs) - 1, int(len(diffs) * (1 - alpha / 2)))]
    return {
        "point_estimate": round(point_diff, 5),
        "ci": (round(lo, 5), round(hi, 5)),
        "confidence": round(1 - alpha, 2),
        "iterations": iterations, "n_dates": len(dates), "seed": seed,
        "interpretation": (
            "negative means OUR Brier is lower (better) than the market's; "
            "an interval that excludes zero says the difference is not "
            "explained by which dates got resampled"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_stores():
    prop_rows = batter_props.read_processed()
    batter_rows = [r for r in boxscores.read(BOX_STORE) if r.get("type") == "batter"]
    try:
        lineup_index = lineup_store.read()
    except Exception:  # noqa: BLE001 -- a missing/corrupt lineup store must
        # not kill a calibration probe; slots simply come back empty and
        # `expected_pa_source` says so per contract.
        lineup_index = {}
    return prop_rows, batter_rows, lineup_index


def build_report(min_gap: float = 0.10) -> dict:
    prop_rows, batter_rows, lineup_index = load_stores()
    records, refused_totals, outcome_totals = collect_records(
        prop_rows, batter_rows, lineup_index)

    return {
        "target_markets": list(TARGET_MARKETS),
        "prop_store_rows": len(prop_rows),
        "boxscore_batter_rows": len(batter_rows),
        "settled_records": len(records),
        "outcome_totals": dict(outcome_totals),
        "refused_totals": dict(refused_totals),
        "overall": scoreboard(records),
        "splits": splits(records),
        "big_gap": big_gap_question(records, min_gap),
        "bootstrap_brier_diff": bootstrap_brier_diff(records),
    }


def _print_score(label: str, score: Optional[dict]) -> None:
    if not score:
        print(f"  {label}: no data")
        return
    print(f"  {label}: n={score['n']}  brier={score['brier']:.5f}  "
          f"log_loss={score['log_loss']:.5f}  base_rate={score['base_rate']:.3f}  "
          f"mean_prediction={score['mean_prediction']:.3f}")


def _print_reliability(rows: list) -> None:
    print(f"    {'bucket':<10}{'n':>7}{'predicted':>11}{'actual':>9}{'gap':>8}")
    for row in rows:
        if row["n"] == 0:
            print(f"    {row['bucket']:<10}{'0':>7}")
            continue
        print(f"    {row['bucket']:<10}{row['n']:>7}{row['predicted']:>11.3f}"
              f"{row['actual']:>9.3f}{row['gap']:>+8.3f}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap", type=float, default=0.10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    report = build_report(min_gap=args.min_gap)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print(f"PROP CALIBRATION PROBE  markets={report['target_markets']}")
    print(f"  {report['prop_store_rows']} prop rows, "
          f"{report['boxscore_batter_rows']} boxscore batter rows")
    print(f"  settled records: {report['settled_records']}   "
          f"outcomes: {report['outcome_totals']}")
    if report["refused_totals"]:
        print(f"  refused (not priced): {report['refused_totals']}")

    print("\n=== OVERALL ===")
    _print_score("ours ", report["overall"]["ours"])
    _print_score("market", report["overall"]["market"])
    print("  reliability -- ours:")
    _print_reliability(report["overall"]["reliability_ours"])
    print("  reliability -- market:")
    _print_reliability(report["overall"]["reliability_market"])

    for name, group in report["splits"].items():
        print(f"\n=== SPLIT: {name} ===")
        for label, score in group.items():
            if "verdict" in score:
                print(f"  {label}: {score['verdict']} (n={score['n']})")
                continue
            print(f"  -- {label} --")
            _print_score("  ours ", score["ours"])
            _print_score("  market", score["market"])

    print(f"\n=== OURS >= MARKET + {args.min_gap:.0%} ===")
    print(f"  {report['big_gap']}")

    print("\n=== BOOTSTRAP: ours Brier - market Brier (date-clustered) ===")
    print(f"  {report['bootstrap_brier_diff']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
