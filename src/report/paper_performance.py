"""Read-only PAPER / RESEARCH PERFORMANCE surface (Task B3).

WHY THIS EXISTS
----------------
`src.accounts.paper` keeps one hash-chained ledger per system
(`data/paper_accounts/<system_id>.jsonl`), and `src.factory.scorecard`
already knows how to turn a sequence of `SettledBet`s into bankroll/ROI/
hit-rate numbers (`compute_realized_stats`). Nothing before this module
rolled every system's account up into one side-by-side standings table, a
per-class (CONTROL / MARKET_REFERENCE / FORWARD_TEST) rollup, a recent-picks
feed with resolved matchup names, or a reasoning-outcome breakdown. This
module is that read-only reporting layer -- it never appends to a ledger,
never runs a slate or a settle, and never computes a number the underlying
domain modules (`src.accounts.paper`, `src.factory.scorecard`,
`src.engine.settle_slate`, `src.report.engine_bridge`) do not already own.

THREE SYSTEM CLASSES, NEVER CONFLATED
---------------------------------------
Every standing/rollup carries the SAME `system_class` vocabulary
`src.report.engine_bridge.system_class` already defines: CONTROL (a null
baseline), MARKET_REFERENCE (republishes the board's own de-vigged
consensus), FORWARD_TEST (an unproven directional thesis). This module
classifies every system it reports on through that one function -- it
never re-derives or overrides the classification.

HONESTY NOTES
--------------
- Every account here is a PAPER account: flat 1-unit stakes, no real money,
  not audited, not a forecast of anything -- see `build_performance_payload`'s
  `disclaimer` field, which every caller of this data is expected to carry
  forward verbatim.
- `reasoning_split`'s UNTESTED bucket is not a gap in this module's join
  logic -- it is the expected, permanent state of every CONTROL and every
  MARKET_REFERENCE system, neither of which ever freezes a falsifiable
  mechanism claim to test (see `src.ledger.records.compute_thesis_outcome`).
- A `ReviewRecord.decision_key` written before the 2026-09-03 five-field
  fix (`src.factory.scorecard.decision_key_for`) is a 4-tuple that can never
  join to a decision again; `reasoning_split` counts those separately
  (`unjoinable_legacy`) rather than silently dropping or mis-joining them.

TOLERANCE
----------
Every public function here tolerates a missing directory or ledger file --
`data/paper_accounts/` absent, `evidence/paper_wagers_v2.jsonl` absent, an
account's own ledger file absent -- by returning an empty/zeroed result,
never by raising. A container that has not run a slate yet must still be
able to serve this endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.accounts.paper import PaperAccountError, PaperBet, SettledBet
from src.board.settle import LOSS, PUSH, VOID, WIN
from src.engine.settle_slate import PAPER_WAGERS_PATH, load_decisions, load_reviews
from src.factory.scorecard import compute_realized_stats
from src.ledger.chain import HashChainLedger
from src.ledger.writer import SCORECARD_LEDGER_PATH
from src.paths import data_path, processed_path
from src.pipeline import slate as slate_mod
from src.report import engine_bridge

LABEL = "PAPER / RESEARCH PERFORMANCE"
DISCLAIMER = (
    "Paper accounts only, flat 1-unit stakes, settled from official "
    "results. Not audited, not real-money returns, not a forecast."
)

CONTROL = engine_bridge.CONTROL
MARKET_REFERENCE = engine_bridge.MARKET_REFERENCE
FORWARD_TEST = engine_bridge.FORWARD_TEST
ALL_SYSTEMS = "ALL"
_CLASS_NAMES = (CONTROL, MARKET_REFERENCE, FORWARD_TEST, ALL_SYSTEMS)

_UNTESTED_NOTE = (
    "UNTESTED means the system made no checkable mechanism claim -- true "
    "by design for every CONTROL and every MARKET REFERENCE system, "
    "neither of which ever freezes a falsifiable thesis to test."
)

DEFAULT_ACCOUNTS_DIR = data_path("paper_accounts")
DEFAULT_EVENT_GAME_MAP_PATH = processed_path("event_game_map.jsonl")
DEFAULT_BOXSCORES_PATH = processed_path("boxscores_2026.jsonl")

_STARTING_BANKROLL = 1000.0


# ---------------------------------------------------------------------------
# Plain-JSONL readers (event_game_map.jsonl / boxscores_*.jsonl are ordinary
# processed-data files, not hash-chained ledgers).
# ---------------------------------------------------------------------------

def _read_plain_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


# ---------------------------------------------------------------------------
# Account ledgers -> settled bets
# ---------------------------------------------------------------------------

def _account_files(accounts_dir=None) -> list:
    d = Path(accounts_dir) if accounts_dir is not None else DEFAULT_ACCOUNTS_DIR
    if not d.exists():
        return []
    try:
        return sorted(d.glob("*.jsonl"))
    except OSError:
        return []


def _settled_bet_from_row(row: dict, *, default_system_id: str) -> Optional[SettledBet]:
    try:
        bet = PaperBet(
            bet_id=row["bet_id"],
            system_id=row.get("system_id", default_system_id),
            market_key=row["market_key"],
            selection_id=row["selection_id"],
            side=row["side"],
            line=row.get("line"),
            price_american=row["price_american"],
            settlement_rule=row["settlement_rule"],
            stake_units=row.get("stake_units", 1.0),
        )
        return SettledBet(bet=bet, outcome=row["outcome"],
                          profit_units=row["profit_units"])
    except (KeyError, PaperAccountError, TypeError):
        return None


def _load_settled(accounts_dir=None) -> dict:
    """`{system_id: [(day, bet_id, SettledBet), ...]}` in ledger append
    order, one entry per account file under `accounts_dir` (default
    `data/paper_accounts/`). A row this module cannot reconstruct into a
    `SettledBet` (malformed/partial) is skipped rather than raising -- the
    rest of that account's real history still gets reported."""
    out: dict = {}
    for f in _account_files(accounts_dir):
        system_id = f.stem
        try:
            raw = HashChainLedger(f).read()
        except Exception:
            raw = []
        rows = []
        for row in raw:
            settled = _settled_bet_from_row(row, default_system_id=system_id)
            if settled is None:
                continue
            rows.append((row.get("day"), row.get("bet_id"), settled))
        out[system_id] = rows
    return out


def settled_bets_by_system(accounts_dir=None) -> dict:
    """`{system_id: tuple[SettledBet, ...]}` -- every settled bet each
    system's own hash-chained account ledger has ever recorded, in append
    order. Tolerates a missing `accounts_dir` (empty dict)."""
    loaded = _load_settled(accounts_dir)
    return {sid: tuple(s for _, _, s in rows) for sid, rows in loaded.items()}


def _days_for(rows) -> list:
    return [d for d, _, _ in rows if d]


def system_standings(accounts_dir=None) -> list:
    """One row per system: settlement tally, staking/return, bankroll and
    drawdown, all straight out of `compute_realized_stats` -- this
    function invents no number of its own."""
    loaded = _load_settled(accounts_dir)
    out = []
    for system_id, rows in loaded.items():
        bets = tuple(s for _, _, s in rows)
        stats = compute_realized_stats(bets, starting_bankroll=_STARTING_BANKROLL)
        days = _days_for(rows)
        out.append({
            "system_id": system_id,
            "system_class": engine_bridge.system_class(system_id),
            "n_settled": stats.n_settled,
            "wins": stats.n_wins,
            "losses": stats.n_losses,
            "pushes": stats.n_pushes,
            "hit_rate": stats.hit_rate,
            "units_staked": stats.total_staked_units,
            "units_net": stats.total_profit_units,
            "return_on_units": stats.roi_units,
            "bankroll": stats.bankroll,
            "drawdown_max": stats.drawdown_max,
            "avg_odds_decimal": stats.avg_odds_decimal,
            "first_day": min(days) if days else None,
            "last_day": max(days) if days else None,
        })
    return out


def _day_lookup(accounts_dir=None) -> dict:
    """`{(system_id, bet_id): day}` across every account -- the sort key
    `class_rollups`/`cumulative_series` need but a bare `SettledBet` does
    not carry (it has no `day` field; only the raw ledger row does)."""
    out = {}
    for system_id, rows in _load_settled(accounts_dir).items():
        for day, bet_id, _ in rows:
            out[(system_id, bet_id)] = day
    return out


def class_rollups(standings, bets_by_system, accounts_dir=None) -> dict:
    """`{CONTROL|MARKET_REFERENCE|FORWARD_TEST|ALL: {...}}`, each recomputed
    via `compute_realized_stats` over that class's bets concatenated across
    systems and sorted by (day, bet_id) -- chronological order matters for
    a shared bankroll/drawdown replay, which is why this never just
    concatenates `bets_by_system`'s per-system tuples in dict-iteration
    order.

    `accounts_dir`, when given, MUST be the same directory `bets_by_system`
    was built from (`settled_bets_by_system(accounts_dir)`) -- it exists
    only to recover each bet's `day` for the sort, never to re-derive the
    bets themselves.
    """
    day_of = _day_lookup(accounts_dir)
    class_of = {s["system_id"]: s["system_class"] for s in standings}
    buckets = {name: [] for name in _CLASS_NAMES}
    for system_id, bets in (bets_by_system or {}).items():
        cls = class_of.get(system_id) or engine_bridge.system_class(system_id)
        for bet in bets:
            bet_id = bet.bet.bet_id
            day = day_of.get((system_id, bet_id)) or ""
            item = (day, bet_id, bet)
            if cls in buckets:
                buckets[cls].append(item)
            buckets[ALL_SYSTEMS].append(item)

    out = {}
    for cls, items in buckets.items():
        items.sort(key=lambda t: (t[0], t[1]))
        stats = compute_realized_stats(
            tuple(b for _, _, b in items), starting_bankroll=_STARTING_BANKROLL)
        out[cls] = {
            "n_settled": stats.n_settled,
            "wins": stats.n_wins,
            "losses": stats.n_losses,
            "pushes": stats.n_pushes,
            "units_staked": stats.total_staked_units,
            "units_net": stats.total_profit_units,
            "return_on_units": stats.roi_units,
            "hit_rate": stats.hit_rate,
            "drawdown_max": stats.drawdown_max,
        }
    return out


def cumulative_series(class_name, accounts_dir=None) -> list:
    """`[{day, units_net}, ...]`, one point per distinct settled day, for
    `class_name` in CONTROL/MARKET_REFERENCE/FORWARD_TEST/ALL -- a running
    sum of `profit_units` over that class's bets in (day, bet_id) order,
    snapshotted at the end of each day (matching each account's own
    peak/drawdown replay discipline: chronological, never re-ordered by
    magnitude)."""
    loaded = _load_settled(accounts_dir)
    items = []
    for system_id, rows in loaded.items():
        cls = engine_bridge.system_class(system_id)
        if class_name != ALL_SYSTEMS and cls != class_name:
            continue
        for day, bet_id, settled in rows:
            items.append((day or "", bet_id, settled))
    items.sort(key=lambda t: (t[0], t[1]))

    out: list = []
    running = 0.0
    last_day = None
    for day, _bet_id, settled in items:
        running += settled.profit_units
        if not out or day != last_day:
            out.append({"day": day or None, "units_net": running})
            last_day = day
        else:
            out[-1]["units_net"] = running
    return out


# ---------------------------------------------------------------------------
# Matchup resolution (wager.game_pk / event_id -> away/home names)
# ---------------------------------------------------------------------------

def _event_game_map_index(path=None) -> dict:
    """`{str(game_pk): {"away_team", "home_team", "event_id"}}`, first row
    wins per `game_pk` -- `event_game_map.jsonl` is append-only-ish
    resolution history, and the earliest resolved row is as good a name
    source as any later one for a game that has already been played."""
    out: dict = {}
    for row in _read_plain_jsonl(path or DEFAULT_EVENT_GAME_MAP_PATH):
        game_pk = row.get("game_pk")
        if game_pk is None:
            continue
        key = str(game_pk)
        if key in out:
            continue
        out[key] = {
            "away_team": row.get("away_team"),
            "home_team": row.get("home_team"),
            "event_id": row.get("event_id"),
        }
    return out


def _boxscore_team_index(path=None) -> dict:
    """`{str(game_pk): {"away": team_name, "home": team_name}}`, derived
    from the `side`/`team_name` every pitcher/batter row in
    `boxscores_*.jsonl` already carries -- a fallback name source for a
    `game_pk` `event_game_map.jsonl` never resolved."""
    out: dict = {}
    for row in _read_plain_jsonl(path or DEFAULT_BOXSCORES_PATH):
        if row.get("type") not in ("pitcher", "batter"):
            continue
        game_pk = row.get("game_pk")
        side = row.get("side")
        team_name = row.get("team_name")
        if game_pk is None or side not in ("away", "home") or not team_name:
            continue
        key = str(game_pk)
        entry = out.setdefault(key, {})
        entry.setdefault(side, team_name)
    return out


def _abbrev_or_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return slate_mod.team_abbrev_from_name(name) or name


def _matchup_for(wager: dict, *, game_map: dict, box_map: dict,
                 event_idx: dict) -> tuple:
    """`(away_team, home_team, matchup, resolved: bool)` for one wager row.
    `resolved` is False only when this function had NOTHING (no
    `event_game_map` row, no boxscore row, no live multibook event) to name
    the game with -- the one case `recent_picks` falls back to
    `'event <8 chars>'` and `build_performance_payload` counts."""
    game_pk = wager.get("game_pk")
    key = str(game_pk) if game_pk is not None else None

    entry = game_map.get(key) if key else None
    if entry and (entry.get("away_team") or entry.get("home_team")):
        away, home = entry.get("away_team"), entry.get("home_team")
    else:
        box = box_map.get(key) if key else None
        away, home = (box.get("away"), box.get("home")) if box else (None, None)

    if not (away and home):
        event_id = wager.get("event_id")
        info = event_idx.get(event_id) if event_id else None
        if info:
            away = away or info.get("away_name")
            home = home or info.get("home_name")

    if not (away and home):
        raw = str(wager.get("event_id") or wager.get("bet_id") or "")
        return None, None, f"event {raw[:8]}", False

    away_out, home_out = _abbrev_or_name(away), _abbrev_or_name(home)
    return away_out, home_out, f"{away_out} @ {home_out}", True


# ---------------------------------------------------------------------------
# Wagers (evidence/paper_wagers_v2.jsonl)
# ---------------------------------------------------------------------------

def _load_wagers(wagers_path=None) -> list:
    try:
        return HashChainLedger(wagers_path or PAPER_WAGERS_PATH).read()
    except Exception:
        return []


def recent_picks(limit: int = 50, *, accounts_dir=None, wagers_path=None,
                 event_game_map_path=None, boxscores_path=None) -> list:
    """Newest-first feed of wagers, settled or pending, with a resolved
    matchup name where one exists anywhere in the stores this module
    knows how to read."""
    wagers = _load_wagers(wagers_path)
    if not wagers:
        return []

    settled_by_system = _load_settled(accounts_dir)
    settled_index: dict = {}
    for system_id, rows in settled_by_system.items():
        for day, bet_id, settled in rows:
            settled_index[(system_id, bet_id)] = (day, settled)

    game_map = _event_game_map_index(event_game_map_path)
    box_map = _boxscore_team_index(boxscores_path)
    try:
        event_idx = engine_bridge.event_index()
    except Exception:
        event_idx = {}

    rows = []
    for wager in wagers:
        system_id = wager.get("system_id")
        bet_id = wager.get("bet_id")
        date = wager.get("date")
        found = settled_index.get((system_id, bet_id))
        if found is not None:
            day, settled = found
            outcome = settled.outcome
            profit_units = settled.profit_units
        else:
            day, outcome, profit_units = date, "pending", None

        away_team, home_team, matchup, _resolved = _matchup_for(
            wager, game_map=game_map, box_map=box_map, event_idx=event_idx)

        rows.append({
            "day": day,
            "date": date,
            "away_team": away_team,
            "home_team": home_team,
            "matchup": matchup,
            "market_key": wager.get("market_key"),
            "side": wager.get("side"),
            "line": wager.get("line"),
            "price_american": wager.get("price_american"),
            "system_id": system_id,
            "system_class": engine_bridge.system_class(system_id),
            "outcome": outcome,
            "profit_units": profit_units,
            "bet_id": bet_id,
            # sort-only fields, stripped below
            "_decision_utc": wager.get("decision_utc") or "",
        })

    rows.sort(key=lambda r: (r["day"] or "", r["_decision_utc"], r["bet_id"] or ""),
              reverse=True)
    for r in rows:
        del r["_decision_utc"]
    return rows[: max(int(limit), 0)]


def unresolved_matchup_count(picks) -> int:
    """How many `recent_picks` rows fell back to the `'event <8 chars>'`
    label -- this module's own honesty metric on itself, surfaced by the
    real-data check rather than hidden."""
    return sum(1 for p in picks if p.get("matchup", "").startswith("event "))


# ---------------------------------------------------------------------------
# Reasoning split (evidence/reviews_v2.jsonl)
# ---------------------------------------------------------------------------

_THESIS_OUTCOMES = ("CONFIRMED", "REFUTED", "VARIANCE", "UNTESTED")


def reasoning_split(review_path=None) -> dict:
    """Every settled bet's mechanism-check outcome, tallied and cross-cut
    against win/loss -- `ReviewRecord.settled` and `.thesis_outcome` are
    both self-contained on the review row, so this needs no join back to a
    decision to build the matrix (only the legacy/joined split below reads
    `decision_key`'s length)."""
    try:
        reviews = load_reviews(path=review_path)
    except Exception:
        reviews = ()

    counts = {name: 0 for name in _THESIS_OUTCOMES}
    matrix = {
        "won_reasoning_confirmed": 0,
        "won_reasoning_refuted": 0,
        "lost_reasoning_confirmed": 0,  # == VARIANCE
        "lost_reasoning_refuted": 0,
        "untested": 0,
    }
    joined = 0
    unjoinable_legacy = 0

    for review in reviews:
        outcome = review.thesis_outcome
        if outcome in counts:
            counts[outcome] += 1

        if len(review.decision_key) == 5:
            joined += 1
        else:
            unjoinable_legacy += 1

        settled = review.settled
        if outcome == "CONFIRMED" and settled == WIN:
            matrix["won_reasoning_confirmed"] += 1
        elif outcome == "REFUTED" and settled == WIN:
            matrix["won_reasoning_refuted"] += 1
        elif outcome == "VARIANCE":
            matrix["lost_reasoning_confirmed"] += 1
        elif outcome == "REFUTED" and settled in (LOSS, PUSH):
            matrix["lost_reasoning_refuted"] += 1
        elif outcome == "UNTESTED":
            matrix["untested"] += 1

    return {
        "counts": counts,
        "matrix": matrix,
        "joined": joined,
        "unjoinable_legacy": unjoinable_legacy,
        "note": _UNTESTED_NOTE,
    }


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def _latest_scorecard_windows(scorecard_path=None) -> dict:
    try:
        rows = HashChainLedger(scorecard_path or SCORECARD_LEDGER_PATH).read()
    except Exception:
        rows = []
    out: dict = {}
    for row in rows:
        system_id = row.get("system_id")
        window = row.get("window")
        if not system_id or window is None:
            continue
        if system_id not in out or str(window) > str(out[system_id]):
            out[system_id] = window
    return out


def freshness(accounts_dir=None, wagers_path=None, scorecard_path=None,
             decisions_path=None) -> dict:
    """A snapshot of how current this whole surface is: the newest settled
    day across every account, how many wagers have not settled yet (and on
    which dates), each system's latest published scorecard window, and the
    raw decision/wager totals this payload was built from."""
    loaded = _load_settled(accounts_dir)
    settled_ids: dict = {}
    all_days: list = []
    for system_id, rows in loaded.items():
        settled_ids[system_id] = {bet_id for _, bet_id, _ in rows}
        all_days.extend(_days_for(rows))
    settled_through = max(all_days) if all_days else None

    wagers = _load_wagers(wagers_path)
    pending_dates = set()
    pending_wagers = 0
    for wager in wagers:
        system_id = wager.get("system_id")
        bet_id = wager.get("bet_id")
        if bet_id not in settled_ids.get(system_id, ()):
            pending_wagers += 1
            if wager.get("date"):
                pending_dates.add(wager["date"])

    try:
        decisions_total = len(load_decisions(path=decisions_path))
    except Exception:
        decisions_total = 0

    return {
        "settled_through": settled_through,
        "pending_wagers": pending_wagers,
        "pending_dates": sorted(pending_dates),
        "latest_scorecard_windows": _latest_scorecard_windows(scorecard_path),
        "decisions_total": decisions_total,
        "wagers_total": len(wagers),
    }


# ---------------------------------------------------------------------------
# The whole payload
# ---------------------------------------------------------------------------

_CLASS_SORT_ORDER = {FORWARD_TEST: 0, MARKET_REFERENCE: 1, CONTROL: 2}


def _systems_sorted(standings) -> list:
    """FORWARD_TEST first (by settled count, most-active first), then
    MARKET_REFERENCE, then CONTROL -- the order this task's own
    deliverable spec names, never alphabetical or ledger-discovery order."""
    return sorted(
        standings,
        key=lambda s: (
            _CLASS_SORT_ORDER.get(s["system_class"], 3),
            -s["n_settled"],
            s["system_id"],
        ),
    )


def build_performance_payload(limit: int = 50, *, accounts_dir=None,
                              wagers_path=None, review_path=None,
                              decisions_path=None, scorecard_path=None,
                              event_game_map_path=None,
                              boxscores_path=None, now=None) -> dict:
    """The whole `GET /performance` payload -- standings, class rollups,
    a recent-picks feed, the reasoning-outcome split, and freshness, all
    assembled from the read-only sources above. Never raises on missing
    stores: an empty repo (no accounts, no wagers, no reviews yet) produces
    a structurally complete, honestly-empty payload."""
    from datetime import datetime, timezone

    standings = system_standings(accounts_dir)
    bets_by_system = settled_bets_by_system(accounts_dir)
    classes = class_rollups(standings, bets_by_system, accounts_dir)
    picks = recent_picks(
        limit, accounts_dir=accounts_dir, wagers_path=wagers_path,
        event_game_map_path=event_game_map_path, boxscores_path=boxscores_path)
    notes = []
    unresolved = unresolved_matchup_count(picks)
    if unresolved:
        notes.append(
            f"{unresolved} of {len(picks)} recent picks could not be "
            "matched to a named matchup and fell back to an event-id label."
        )

    return {
        "label": LABEL,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "disclaimer": DISCLAIMER,
        "freshness": freshness(
            accounts_dir, wagers_path=wagers_path,
            scorecard_path=scorecard_path, decisions_path=decisions_path),
        "classes": classes,
        "systems": _systems_sorted(standings),
        "recent_picks": picks,
        "reasoning_split": reasoning_split(review_path),
        "series": {
            FORWARD_TEST: cumulative_series(FORWARD_TEST, accounts_dir),
            ALL_SYSTEMS: cumulative_series(ALL_SYSTEMS, accounts_dir),
        },
        "notes": notes,
    }
