"""Task C1: the FROZEN PREGAME RECORD -- one day's engine calls, exactly as
they were written before first pitch, joined (never recomputed) against
whatever settlement fact exists for them today.

WHY THIS EXISTS
----------------
`src.report.engine_bridge` joins a decision to a game; `src.report.
paper_performance` rolls every system's paper account up into standings.
Neither answers the question a hosted demo actually needs first: "what did
the engine say about TODAY'S games, and how did those specific calls turn
out?" This module is that per-day surface -- one `DecisionRecord` row per
recommendation, unchanged, plus whatever `SettledBet` a paper account later
recorded against its `bet_id`. It reads both ledgers and joins them; it
never re-ranks, re-prices, or re-derives a probability either one carries.

FROZEN MEANS FROZEN
---------------------
A `DecisionRecord` written before first pitch is what the engine actually
said at that instant -- its price, consensus, book count, confidence grade
and reasons never change here, no matter what the board looks like when
this module runs. The settlement (win/loss/push, profit_units, the day it
settled) is a SEPARATE, LATER fact, joined onto the frozen row by `bet_id`
through the same paper-account ledgers `src.report.paper_performance`
already knows how to read -- never a second settlement authority, never a
re-grading of anything.

HONESTY, NOT OPTIMISM
-----------------------
No system on this ledger carries an independent model probability --
`p_model_provenance` is `none`/`placeholder`/`market_derived` on every live
row, and `edge_bps` is null everywhere (see `src.ledger.records`'s own
invariant: `edge_bps` may only be non-null when the probability is
`model_derived`, which nothing here is). This module never invents a
number where one is missing: a game whose final score cannot be joined to
`data/processed/boxscores_2026.jsonl` gets `final_score: null` and a
`final_score_reason` string, never a guess; a bet with no settlement row
gets `pending` or `unsettled` (distinguished honestly, never conflated) and
`profit_units: null`, never a zero standing in for "unknown".

READ-ONLY, ALWAYS
------------------
Every public function here only reads: `src.engine.settle_slate.
load_decisions`/the paper-wagers ledger, `src.report.paper_performance`'s
own settled-ledger loader (reused, not duplicated), `src.report.
engine_bridge.event_index`, `src.board.gamekey`'s event->game_pk map, and
`data/processed/boxscores_2026.jsonl` (the one final-score source this
project ships in its container image -- see that store's own module note
in `src.report.paper_performance`). Nothing here appends to a ledger, runs
a slate, or settles anything. Every function tolerates every one of those
sources being absent, empty, or malformed, and returns an honestly-empty
structure instead of raising -- a container that has not run a slate yet
must still be able to serve this surface.

NO CLOCK IN HERE
-------------------
Nothing in this module calls `datetime.now()`/`date.today()`. `day_record`
and `day_index` work purely off the `date`/`limit` a caller supplies plus
whatever the ledgers already say about "settled through when"; `record_
strip` takes `today` as an explicit argument for the same reason -- the API
layer (`api/daily.py`) owns the one legitimate clock read for this surface,
same discipline as `src.report.eod.build_review`.

STAKES ARE FLAT 1 UNIT, ALWAYS
----------------------------------
`src.accounts.paper.PaperBet` refuses to construct at any stake but
`FLAT_1U` (1.0) -- every recommendation below reports `stake_units: 1.0`
and the record as a whole carries `stake_policy: "FLAT_1U"`, never a
confidence-scaled number this project's staking policy does not support.
"""

from __future__ import annotations

from datetime import date as _date_cls, timedelta

from src.analysis import priceverdict
from src.board import gamekey
from src.core import odds as odds_math
from src.core.asof import game_pk_key
from src.engine.settle_slate import PAPER_WAGERS_PATH, load_decisions
from src.ledger.chain import HashChainLedger
from src.pipeline import slate as slate_mod
from src.report import engine_bridge
from src.report import paper_performance as pp

CONTROL = engine_bridge.CONTROL
MARKET_REFERENCE = engine_bridge.MARKET_REFERENCE
FORWARD_TEST = engine_bridge.FORWARD_TEST

LABEL = "FROZEN PREGAME RECORD"
STAKE_POLICY = "FLAT_1U"
BASIS = (
    "Every recommendation below is the row the engine froze before first "
    "pitch; prices and confidence are as of that instant, never restated."
)

# "value_points" is the payload's field name, and it was reaching a customer
# page inside an otherwise plain-English sentence. The measure it names is
# the same one the price verdict already calls value points on screen.
_STRONGEST_PREGAME_BASIS = (
    "The most value points of any staked play, chosen with no knowledge of "
    "the outcome."
)

_field = engine_bridge._field  # dict-or-dataclass reader, reused not redefined


# ---------------------------------------------------------------------------
# Tolerant loaders -- every one of these degrades to an empty structure
# rather than raising, per this module's own docstring.
# ---------------------------------------------------------------------------

def _safe_decisions(decisions) -> tuple:
    if decisions is not None:
        return tuple(decisions)
    try:
        return load_decisions()
    except Exception:
        return ()


def _safe_wagers(wagers) -> tuple:
    """`wagers`, when given, is the FULL wager table (every date) -- every
    function below slices it to the date(s) it needs itself, exactly once
    per call, rather than each accepting a pre-filtered list the way
    `src.engine.settle_slate.wagers_for_date` does. `None` reads
    `evidence/paper_wagers_v2.jsonl` once, tolerantly."""
    if wagers is not None:
        return tuple(wagers)
    try:
        return tuple(HashChainLedger(PAPER_WAGERS_PATH).read())
    except Exception:
        return ()


def _safe_index(index) -> dict:
    if index is not None:
        return index
    try:
        return engine_bridge.event_index()
    except Exception:
        return {}


def _safe_boxscores(boxscores) -> tuple:
    if boxscores is not None:
        return tuple(boxscores)
    try:
        return tuple(pp._read_plain_jsonl(pp.DEFAULT_BOXSCORES_PATH))
    except Exception:
        return ()


def _safe_event_game_map() -> dict:
    """`{event_id: row}` from `data/processed/event_game_map.jsonl` -- a
    name/first-pitch fallback for an event `index` (the live multi-book
    event index) does not cover, e.g. a sealed backtest date or a game that
    has rolled out of the odds board's own capture window. Reuses
    `paper_performance`'s tolerant plain-JSONL reader (its own event-game-map
    index is keyed by `game_pk`, which does not fit this lookup -- this
    module needs `event_id`, so it builds its own dict over the same rows
    rather than re-reading the file a second way)."""
    try:
        rows = pp._read_plain_jsonl(pp.DEFAULT_EVENT_GAME_MAP_PATH)
    except Exception:
        rows = []
    out: dict = {}
    for row in rows:
        event_id = row.get("event_id")
        if event_id and event_id not in out:
            out[event_id] = row
    return out


def _safe_game_pk_map() -> dict:
    """`event_id -> game_pk` resolution map (`src.board.gamekey`), used
    only when neither a decision nor its wager already carries a resolved
    `game_pk` -- most wagers do (resolved at settle time -- see
    `src.engine.settle_slate._with_resolved_game_pk`), but some do not
    (every 2026-09-05 wager was unresolved at write time; see that
    module's own note)."""
    try:
        return gamekey.load_map()
    except Exception:
        return {}


def _box_final_scores(box_rows) -> dict:
    """`{game_pk: {"away": runs, "home": runs}}`, summed over EVERY inning
    of the `type == "linescore"` row for that `game_pk` -- the full-game
    score, unlike `src.engine.settle_slate.load_boxscore_first_five`'s
    innings-1-5-only sum. A `game_pk` with no linescore row (game not yet
    final, or this store simply never captured it) is absent from the
    returned dict, never zero-filled."""
    out: dict = {}
    for row in box_rows or ():
        if not isinstance(row, dict) or row.get("type") != "linescore":
            continue
        pk = game_pk_key(row.get("game_pk"))
        innings = row.get("innings") or []
        if pk is None or not innings:
            continue
        home = sum((i.get("home_runs", 0) or 0) for i in innings)
        away = sum((i.get("away_runs", 0) or 0) for i in innings)
        out[pk] = {"away": away, "home": home}
    return out


def _box_team_names(box_rows) -> dict:
    """`{game_pk: {"away": team_name, "home": team_name}}` -- the same
    fallback name source `paper_performance._boxscore_team_index` reads,
    adapted to take already-loaded rows (this module's `boxscores` param)
    rather than re-reading a path, since a caller may have injected a
    fixture with no file behind it at all."""
    out: dict = {}
    for row in box_rows or ():
        if not isinstance(row, dict) or row.get("type") not in ("pitcher", "batter"):
            continue
        pk = game_pk_key(row.get("game_pk"))
        side = row.get("side")
        team_name = row.get("team_name")
        if pk is None or side not in ("away", "home") or not team_name:
            continue
        out.setdefault(pk, {}).setdefault(side, team_name)
    return out


def _settlement_index(accounts_dir=None):
    """`({(system_id, bet_id): (day, outcome, profit_units)}, settled_through)`
    -- the one settlement fact-table every recommendation's `settlement`
    joins against, plus the latest day ANY account actually settled
    through (the pending-vs-unsettled boundary every caller below shares).
    Reuses `paper_performance._load_settled` (the same per-account
    hash-chain replay `system_standings`/`recent_picks` are built from)
    rather than re-parsing account ledgers a second way."""
    try:
        loaded = pp._load_settled(accounts_dir)
    except Exception:
        loaded = {}
    index: dict = {}
    settled_days = []
    for system_id, rows in loaded.items():
        for day, bet_id, settled in rows:
            if not bet_id:
                continue
            index[(system_id, bet_id)] = (day, settled.outcome, settled.profit_units)
            if day:
                settled_days.append(day)
    settled_through = max(settled_days) if settled_days else None
    return index, settled_through


# ---------------------------------------------------------------------------
# Decision/wager join keys -- the SAME 5-tuple
# `src.engine.settle_slate.run_settle` joins a wager back to its decision
# with (`decisions_by_key`), reused here rather than invented a second time.
# ---------------------------------------------------------------------------

def _decision_key(decision):
    return (_field(decision, "event_id"), _field(decision, "system_id"),
            _field(decision, "market_key"), _field(decision, "selection_id"),
            _field(decision, "decision_utc"))


def _wager_key(wager):
    return (wager.get("event_id"), wager.get("system_id"),
            wager.get("market_key"), wager.get("selection_id"),
            wager.get("decision_utc"))


def _resolve_game_pk(event_id, decisions_here, wagers_here, game_pk_map_idx):
    for d in decisions_here:
        pk = game_pk_key(_field(d, "game_pk"))
        if pk is not None:
            return pk
    for w in wagers_here:
        pk = game_pk_key(w.get("game_pk"))
        if pk is not None:
            return pk
    try:
        return gamekey.game_pk_for_event(event_id, game_pk_map_idx)
    except Exception:
        return None


def _stated_implied_probability(price_american):
    if price_american is None:
        return None
    try:
        return round(odds_math.american_to_probability(price_american), 4)
    except Exception:
        return None


def _settlement_for(system_id, bet_id, staked, date, settlement_idx, settled_through):
    if not staked or not bet_id:
        # Never staked: nothing was ever risked, so there is nothing to
        # settle -- "unsettled" is the honest permanent state, not "pending"
        # (which promises a result is still coming).
        return {"status": "unsettled", "profit_units": None, "settled_day": None}
    found = settlement_idx.get((system_id, bet_id))
    if found is not None:
        day, outcome, profit = found
        return {"status": outcome, "profit_units": profit, "settled_day": day}
    if settled_through is None or date > settled_through:
        status = "pending"  # normal: this date has not been settled yet
    else:
        status = "unsettled"  # anomalous: this date HAS settled elsewhere, but not this bet
    return {"status": status, "profit_units": None, "settled_day": None}


def _build_rec(decision, wager, settlement_idx, settled_through, date):
    if decision is not None:
        system_id = _field(decision, "system_id")
        cls = engine_bridge.system_class(system_id)
        market_key = _field(decision, "market_key")
        line = _field(decision, "line")
        price_american = _field(decision, "price_american")
        decision_utc = _field(decision, "decision_utc")
        verdict = _field(decision, "verdict")
        consensus_fair = _field(decision, "consensus_fair")
        books_at_decision = _field(decision, "books_at_decision")
        known_at_grade = _field(decision, "known_at_grade")
        p_model_provenance = _field(decision, "p_model_provenance")
        thesis = _field(decision, "thesis") if cls == FORWARD_TEST else None
        counterarguments = engine_bridge._counterargument_wire(
            _field(decision, "counterarguments"))
        side = (wager.get("side") if wager else None) or _field(decision, "selection_id")
    else:
        # A wager with no matching DecisionRecord (ledger drift/rotation) --
        # never invented, reported with every decision-only field null
        # rather than guessed at.
        system_id = wager.get("system_id")
        cls = engine_bridge.system_class(system_id)
        market_key = wager.get("market_key")
        line = wager.get("line")
        price_american = wager.get("price_american")
        decision_utc = wager.get("decision_utc")
        verdict = "play"  # it was staked, so it was a play, whatever the missing row said
        consensus_fair = None
        books_at_decision = None
        known_at_grade = None
        p_model_provenance = None
        thesis = None
        counterarguments = []
        side = wager.get("side") or wager.get("selection_id")

    market_implied_probability = consensus_fair
    stated_implied_probability = _stated_implied_probability(price_american)
    # THE BOOK FLOOR APPLIES HERE TOO (2026-09-07). `consensus_fair` is
    # whatever the engine averaged at decision time, and on the run line that
    # was routinely TWO books -- src/analysis/prices.py refuses to call
    # anything below MIN_BOOKS a consensus, and priceverdict returns
    # INSUFFICIENT DATA there for exactly this reason. Subtracting a price
    # from a two-book average produced numbers like +14.01 and -15.01 points,
    # and `strongest_pregame` then crowned a two-book run line as the day's
    # best-supported play. That is a rank built on noise, so below the floor
    # this reports no value at all and says why. `consensus_fair` and
    # `books_at_decision` still ride along untouched: the frozen record keeps
    # what the engine recorded, we simply refuse to derive a comparison from it.
    if (books_at_decision or 0) >= priceverdict.MIN_BOOKS:
        value_points = priceverdict.value_points(
            consensus_fair, stated_implied_probability)
        value_points_reason = None
    else:
        value_points = None
        value_points_reason = (
            f"{books_at_decision if books_at_decision is not None else 0} "
            f"book(s) quoted at decision time; below the "
            f"{priceverdict.MIN_BOOKS}-book floor a consensus means nothing, "
            "so no value comparison is reported")

    bet_id = wager.get("bet_id") if wager else None
    staked = wager is not None

    return {
        "system_id": system_id,
        "system_class": cls,
        "market_key": market_key,
        "side": side,
        "line": line,
        "price_american": price_american,
        "decision_utc": decision_utc,
        "verdict": verdict,
        "consensus_fair": consensus_fair,
        "books_at_decision": books_at_decision,
        "market_implied_probability": market_implied_probability,
        "stated_implied_probability": stated_implied_probability,
        "value_points": value_points,
        "value_points_reason": value_points_reason,
        "known_at_grade": known_at_grade,
        "p_model_provenance": p_model_provenance,
        "stake_units": 1.0,
        "thesis": thesis,
        "counterarguments": counterarguments,
        "bet_id": bet_id,
        "staked": staked,
        "settlement": _settlement_for(
            system_id, bet_id, staked, date, settlement_idx, settled_through),
    }


def _rec_sort_key(rec):
    """Staked first, then by |value_points| descending (a rec with no
    value_points sorts after every rec that has one, within its staked
    tier), then system_id -- the exact order this task's spec names."""
    staked_rank = 0 if rec["staked"] else 1
    vp = rec["value_points"]
    vp_rank = -abs(vp) if vp is not None else float("inf")
    return (staked_rank, vp_rank, rec["system_id"] or "")


def _final_score_for(game_pk, box_final_scores):
    if game_pk is None:
        return None, "game_pk could not be resolved for this event, so no boxscore row could be matched"
    row = box_final_scores.get(game_pk)
    if row is None:
        return None, f"no linescore row found in boxscores_2026.jsonl for game_pk={game_pk}"
    return {"away": row["away"], "home": row["home"]}, None


def _game_status(final_score, date, settled_through):
    """"final"/"scheduled"/"unknown" from data alone -- this module never
    reads a clock, so "scheduled" is inferred only from the SAME
    settled_through boundary the settlement join already uses: a date no
    account has settled through yet is presumed still ahead; a date that
    HAS settled elsewhere but whose boxscore this module still could not
    join is a genuine "unknown", never quietly relabelled "scheduled"."""
    if final_score is not None:
        return "final"
    if settled_through is not None and date <= settled_through:
        return "unknown"
    return "scheduled"


def _game_for_event(all_keys, decisions_here_by_key, wagers_here_by_key, *, date,
                     away_abbrev, home_abbrev, away_name, home_name, commence,
                     game_pk, box_final_scores, settlement_idx, settled_through):
    canon_away, canon_home, _ = engine_bridge.game_key(away_abbrev, home_abbrev, date)

    recs = []
    for key in all_keys:
        d = decisions_here_by_key.get(key)
        w = wagers_here_by_key.get(key)
        recs.append(_build_rec(d, w, settlement_idx, settled_through, date))
    recs.sort(key=_rec_sort_key)

    final_score, final_score_reason = _final_score_for(game_pk, box_final_scores)
    status = _game_status(final_score, date, settled_through)

    n_staked = sum(1 for r in recs if r["staked"])
    wins = losses = pushes = pending = 0
    settled_profits = []
    for r in recs:
        st = r["settlement"]["status"]
        if st == "win":
            wins += 1
            settled_profits.append(r["settlement"]["profit_units"] or 0.0)
        elif st == "loss":
            losses += 1
            settled_profits.append(r["settlement"]["profit_units"] or 0.0)
        elif st == "push":
            pushes += 1
            settled_profits.append(r["settlement"]["profit_units"] or 0.0)
        elif st == "pending":
            pending += 1
        # "unsettled" (staked but anomalously never settled) is reported on
        # its own rec and intentionally left out of this 4-bucket tally --
        # see _settlement_for's own docstring for the distinction.

    return {
        "game_key": [canon_away, canon_home, date],
        "away_team": canon_away,
        "home_team": canon_home,
        "away_name": away_name,
        "home_name": home_name,
        "first_pitch_utc": commence,
        "status": status,
        "final_score": final_score,
        "final_score_reason": final_score_reason,
        "n_recommendations": len(recs),
        "n_staked": n_staked,
        "recommendations": recs,
        "settled_units_net": (sum(settled_profits) if settled_profits else None),
        "record": {"wins": wins, "losses": losses, "pushes": pushes, "pending": pending},
    }


def _build_games_for_date(date, decisions_all, wagers_all, idx, decisions_by_key_global,
                           event_game_map_by_event, box_team_idx, box_final_scores,
                           game_pk_map_idx, settlement_idx, settled_through):
    day_wagers = [w for w in wagers_all
                 if isinstance(w, dict) and w.get("date") == date]

    decisions_here_by_event: dict = {}
    for d in decisions_all:
        event_id = _field(d, "event_id")
        info = idx.get(event_id)
        if info and info.get("date") == date:
            decisions_here_by_event.setdefault(event_id, []).append(d)

    wagers_here_by_event: dict = {}
    for w in day_wagers:
        event_id = w.get("event_id")
        if event_id is not None:
            wagers_here_by_event.setdefault(event_id, []).append(w)

    event_ids = {e for e in decisions_here_by_event if e is not None}
    event_ids |= {e for e in wagers_here_by_event if e is not None}

    games = []
    unresolved = 0
    for event_id in sorted(event_ids):
        decisions_here = list(decisions_here_by_event.get(event_id, ()))
        wagers_here = list(wagers_here_by_event.get(event_id, ()))

        decisions_here_by_key = {_decision_key(d): d for d in decisions_here}
        wagers_here_by_key = {}
        for w in wagers_here:
            key = _wager_key(w)
            wagers_here_by_key[key] = w
            if key not in decisions_here_by_key:
                d = decisions_by_key_global.get(key)
                if d is not None:
                    decisions_here_by_key[key] = d
        all_keys = set(decisions_here_by_key) | set(wagers_here_by_key)
        if not all_keys:
            continue

        game_pk = _resolve_game_pk(event_id, decisions_here, wagers_here, game_pk_map_idx)

        away_abbrev = home_abbrev = away_name = home_name = commence = None
        info = idx.get(event_id)
        if info and info.get("date") == date:
            away_abbrev, home_abbrev = info.get("away_abbrev"), info.get("home_abbrev")
            away_name, home_name = info.get("away_name"), info.get("home_name")
            commence = info.get("commence_time")
        if not (away_abbrev and home_abbrev):
            gm = event_game_map_by_event.get(event_id)
            if gm and (gm.get("away_team") or gm.get("home_team")):
                away_name = away_name or gm.get("away_team")
                home_name = home_name or gm.get("home_team")
                away_abbrev = slate_mod.team_abbrev_from_name(away_name) or away_name
                home_abbrev = slate_mod.team_abbrev_from_name(home_name) or home_name
                commence = commence or gm.get("commence_time")
        if not (away_abbrev and home_abbrev) and game_pk:
            names = box_team_idx.get(game_pk)
            if names and (names.get("away") or names.get("home")):
                away_name = away_name or names.get("away")
                home_name = home_name or names.get("home")
                away_abbrev = slate_mod.team_abbrev_from_name(away_name) or away_name
                home_abbrev = slate_mod.team_abbrev_from_name(home_name) or home_name

        if not (away_abbrev and home_abbrev):
            unresolved += 1
            continue

        games.append(_game_for_event(
            all_keys, decisions_here_by_key, wagers_here_by_key, date=date,
            away_abbrev=away_abbrev, home_abbrev=home_abbrev,
            away_name=away_name, home_name=home_name, commence=commence,
            game_pk=game_pk, box_final_scores=box_final_scores,
            settlement_idx=settlement_idx, settled_through=settled_through))

    games.sort(key=lambda g: (g["game_key"][0], g["game_key"][1]))
    return games, unresolved


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def day_record(date, *, decisions=None, wagers=None, accounts_dir=None,
               boxscores=None, index=None) -> dict:
    """One day's FROZEN PREGAME RECORD: every game that had at least one
    engine decision or paper wager on `date`, each recommendation exactly
    as its `DecisionRecord` froze it, joined against whatever settlement
    fact its `bet_id` (if any) has today."""
    decisions_all = _safe_decisions(decisions)
    wagers_all = _safe_wagers(wagers)
    idx = _safe_index(index)
    box_rows = _safe_boxscores(boxscores)
    event_game_map_by_event = _safe_event_game_map()
    box_team_idx = _box_team_names(box_rows)
    box_final_scores = _box_final_scores(box_rows)
    game_pk_map_idx = _safe_game_pk_map()
    settlement_idx, settled_through = _settlement_index(accounts_dir)
    decisions_by_key_global = {_decision_key(d): d for d in decisions_all}

    games, unresolved = _build_games_for_date(
        date, decisions_all, wagers_all, idx, decisions_by_key_global,
        event_game_map_by_event, box_team_idx, box_final_scores,
        game_pk_map_idx, settlement_idx, settled_through)

    notes = []
    if unresolved:
        notes.append(
            f"{unresolved} event(s) with a decision or wager on {date} "
            "could not be matched to a named game (no live board entry, no "
            "event_game_map row, no boxscore team names) and were left out "
            "of this record rather than shown with a guessed matchup.")

    return {
        "date": date,
        "games": games,
        "rollup": day_rollup(games),
        "freshness": {"settled_through": settled_through},
        "notes": notes,
        "stake_policy": STAKE_POLICY,
        "label": LABEL,
        "basis": BASIS,
    }


def _rec_summary(game, rec) -> dict:
    return {
        "matchup": f"{game['away_team']} @ {game['home_team']}",
        "market_key": rec["market_key"],
        "side": rec["side"],
        "line": rec["line"],
        "price_american": rec["price_american"],
        "value_points": rec["value_points"],
        # `.get` on purpose: a summary must survive being handed a partially
        # built rec (tests do exactly that) rather than raising on a key it
        # only ever uses to EXPLAIN an absent number.
        "value_points_reason": rec.get("value_points_reason"),
        "books_at_decision": rec.get("books_at_decision"),
        "system_class": rec["system_class"],
        "profit_units": rec["settlement"]["profit_units"],
        "settlement_status": rec["settlement"]["status"],
    }


def day_rollup(games) -> dict:
    """The day-wide numbers rolled up from an already-built `games` list
    (as `day_record` produces it, or any equivalent caller-built list) --
    never re-reads a ledger itself, so `day_index` can call this once per
    date over data it already loaded."""
    pairs = [(g, r) for g in games for r in g["recommendations"]]
    n_games = len(games)
    n_recommendations = len(pairs)
    n_staked = sum(1 for _, r in pairs if r["staked"])

    wins = losses = pushes = pending = 0
    units_staked = 0.0
    units_net = 0.0
    odds_decimals = []
    by_market: dict = {}
    by_class: dict = {}
    settled_recs = []
    staked_recs = []

    for g, r in pairs:
        if not r["staked"]:
            continue
        staked_recs.append((g, r))
        status = r["settlement"]["status"]
        market_key = r["market_key"] or "unknown"
        cls = r["system_class"]
        bm = by_market.setdefault(
            market_key, {"wins": 0, "losses": 0, "pushes": 0, "units_net": 0.0})
        # `units_staked` added 2026-09-10 so a caller can compute a RETURN
        # per class, not just a unit total. The Daily Recap gallery rendered
        # the pooled wins/losses/units as each day's headline while the
        # record strip directly above it had already been fixed to exclude
        # CONTROL and MARKET_REFERENCE and captioned to say so -- two numbers
        # for the same product, three inches apart, disagreeing. The gallery
        # could not show the forward-test slice instead, because this bucket
        # carried no denominator.
        bc = by_class.setdefault(
            cls, {"wins": 0, "losses": 0, "pushes": 0, "units_net": 0.0,
                  "units_staked": 0.0})

        if status in ("win", "loss", "push"):
            profit = r["settlement"]["profit_units"] or 0.0
            units_net += profit
            bm["units_net"] += profit
            bc["units_net"] += profit
            if status != "push":
                # Same convention as src.accounts.paper.PaperAccount:
                # a push/void never counted toward stake exposure.
                units_staked += 1.0
                bc["units_staked"] += 1.0
            if status == "win":
                wins += 1; bm["wins"] += 1; bc["wins"] += 1
            elif status == "loss":
                losses += 1; bm["losses"] += 1; bc["losses"] += 1
            else:
                pushes += 1; bm["pushes"] += 1; bc["pushes"] += 1
            if r["price_american"] is not None:
                try:
                    odds_decimals.append(odds_math.american_to_decimal(r["price_american"]))
                except Exception:
                    pass
            settled_recs.append((profit, r["decision_utc"] or "", g, r))
        elif status == "pending":
            pending += 1
        # "unsettled" staked bets: counted in n_staked/units_staked-eligible
        # pool only once actually settled -- left out of every other tally
        # here for the same reason _game_for_event leaves them out of
        # `record`, never silently folded into "pending".

    return_on_units = (units_net / units_staked) if units_staked else None
    avg_odds_decimal = (sum(odds_decimals) / len(odds_decimals)) if odds_decimals else None

    best_bet = worst_bet = strongest_pregame = None
    if settled_recs:
        best = min(settled_recs, key=lambda t: (-t[0], t[1]))
        worst = min(settled_recs, key=lambda t: (t[0], t[1]))
        best_bet = _rec_summary(best[2], best[3])
        worst_bet = _rec_summary(worst[2], worst[3])

    vp_recs = [(g, r) for g, r in staked_recs if r["value_points"] is not None]
    if vp_recs:
        g_, r_ = min(vp_recs, key=lambda t: (-t[1]["value_points"], t[1]["decision_utc"] or ""))
        strongest_pregame = _rec_summary(g_, r_)
        strongest_pregame["basis"] = _STRONGEST_PREGAME_BASIS

    return {
        "n_games": n_games,
        "n_recommendations": n_recommendations,
        "n_staked": n_staked,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "units_staked": units_staked,
        "units_net": units_net,
        "return_on_units": return_on_units,
        "avg_odds_decimal": avg_odds_decimal,
        "by_market": by_market,
        "by_class": by_class,
        "best_bet": best_bet,
        "worst_bet": worst_bet,
        "strongest_pregame": strongest_pregame,
    }


def day_index(limit=30, *, decisions=None, wagers=None, accounts_dir=None,
              boxscores=None, index=None) -> list:
    """Newest-first, one entry per date with at least one wager or engine
    decision -- every ledger is loaded exactly once here (never once per
    date) so this stays cheap enough to back a daily-recap gallery."""
    decisions_all = _safe_decisions(decisions)
    wagers_all = _safe_wagers(wagers)
    idx = _safe_index(index)
    box_rows = _safe_boxscores(boxscores)
    event_game_map_by_event = _safe_event_game_map()
    box_team_idx = _box_team_names(box_rows)
    box_final_scores = _box_final_scores(box_rows)
    game_pk_map_idx = _safe_game_pk_map()
    settlement_idx, settled_through = _settlement_index(accounts_dir)
    decisions_by_key_global = {_decision_key(d): d for d in decisions_all}

    dates = set()
    for w in wagers_all:
        if isinstance(w, dict):
            d = w.get("date")
            if d:
                dates.add(d)
    for d in decisions_all:
        info = idx.get(_field(d, "event_id"))
        if info and info.get("date"):
            dates.add(info["date"])

    ordered_dates = sorted(dates, reverse=True)[:max(int(limit), 0)]

    out = []
    for date in ordered_dates:
        games, _unresolved = _build_games_for_date(
            date, decisions_all, wagers_all, idx, decisions_by_key_global,
            event_game_map_by_event, box_team_idx, box_final_scores,
            game_pk_map_idx, settlement_idx, settled_through)
        r = day_rollup(games)
        out.append({
            "date": date,
            "n_games": r["n_games"],
            "n_recommendations": r["n_recommendations"],
            "n_staked": r["n_staked"],
            "wins": r["wins"],
            "losses": r["losses"],
            "pushes": r["pushes"],
            "pending": r["pending"],
            "units_staked": r["units_staked"],
            "units_net": r["units_net"],
            "return_on_units": r["return_on_units"],
            "avg_odds_decimal": r["avg_odds_decimal"],
            "settled": r["pending"] == 0,
            # Carried so the gallery card can show the FORWARD_TEST slice
            # rather than the pooled figures beside it. The rollup has
            # always computed this; the gallery payload simply never
            # forwarded it, so web/js/dayrecap.js had nothing to render but
            # the pooled number -- directly beneath a record strip captioned
            # "our forward-test systems only".
            "by_class": r["by_class"],
            "best_bet": r["best_bet"],
            "worst_bet": r["worst_bet"],
            "strongest_pregame": r["strongest_pregame"],
        })
    return out


# This note is served on GET /record and rendered under the record strip on
# Today and Results, so it is prose a customer reads. It used to name three
# payload fields (units_net, return_on_units, settled_through) inside an
# otherwise plain-English sentence. Same meaning, said in words.
_RECORD_STRIP_NOTE = (
    "A window with no settled bets reports no units and no return rather "
    "than a fabricated number, and the settled-through date names the "
    "latest day this record actually has a confirmed outcome for."
)


def _window(label, from_date, to_date, wagers_all, settlement_idx, *,
           system_class=None) -> "dict | None":
    """`system_class`, when given, keeps only wagers whose
    `engine_bridge.system_class(system_id)` matches it -- e.g.
    `engine_bridge.FORWARD_TEST`, so the headline strip reports the
    product's own record rather than the null baselines and the
    market-reference republishers (doctrine section 6: "Only settled,
    published, FORWARD_TEST rows. No backtests, replays, unpublished
    positions or controls."). `None` keeps every class, unfiltered --
    still the right choice for a diagnostic caller who wants the whole
    ledger, never the default for anything a customer reads.
    """
    rows = [w for w in wagers_all
           if isinstance(w, dict) and w.get("date")
           and from_date <= w["date"] <= to_date
           and (system_class is None
                or engine_bridge.system_class(w.get("system_id")) == system_class)]
    if not rows:
        return None
    wins = losses = pushes = pending = n_settled = 0
    units_net = 0.0
    units_staked = 0.0
    for w in rows:
        key = (w.get("system_id"), w.get("bet_id"))
        found = settlement_idx.get(key)
        if found is None:
            pending += 1
            continue
        _day, outcome, profit = found
        n_settled += 1
        profit = profit or 0.0
        units_net += profit
        if outcome != "push":
            units_staked += 1.0
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        elif outcome == "push":
            pushes += 1
    return {
        "label": label, "from_date": from_date, "to_date": to_date,
        "wins": wins, "losses": losses, "pushes": pushes,
        "units_net": (units_net if n_settled else None),
        "return_on_units": ((units_net / units_staked) if units_staked else None),
        "n_settled": n_settled, "pending": pending,
    }


def record_strip(today=None, *, decisions=None, wagers=None, accounts_dir=None,
                 boxscores=None, index=None) -> dict:
    """TODAY / LAST 7 DAYS / LAST 30 DAYS units-net tiles, plus
    `settled_through`. `today` is the caller's own ISO date -- this
    function never reads a clock (see the module docstring).

    FORWARD_TEST ONLY (doctrine section 6, fixed 2026-09-09). Every window
    was previously pooling every registered system -- measured live, that
    made CONTROL and MARKET_REFERENCE roughly 90% of what a customer's
    first-seen number on the site actually was. `all_classes` carries the
    identical windows over the WHOLE ledger, unfiltered, so a caller that
    genuinely needs the diagnostic view (an internal page, a future
    per-cohort comparison) still has it -- it is simply no longer what
    `today`/`last_7`/`last_30` mean by default.

    This is a bounded fix, not doctrine section 6's full design: the section
    specifies an ALL-TIME, COHORT-based record (Top 3 / Top 5 / Published /
    Research, never a time window) as the actual headline, with 7/30-day
    windows secondary. That redesign needs its own pass -- cohort tags only
    exist for picks published under `engine slip`, which went live
    2026-09-09, so an all-time Top-3 query today would return almost
    nothing. Class-filtering the existing windows removes the worst of the
    dishonesty immediately without shipping a headline that looks broken on
    day one for an unrelated reason.
    """
    wagers_all = _safe_wagers(wagers)
    settlement_idx, settled_through = _settlement_index(accounts_dir)

    if not today:
        return {
            "today": None, "last_7": None, "last_30": None,
            "settled_through": settled_through,
            "note": "no 'today' date supplied -- " + _RECORD_STRIP_NOTE,
        }
    try:
        today_d = _date_cls.fromisoformat(str(today))
    except (ValueError, TypeError):
        return {
            "today": None, "last_7": None, "last_30": None,
            "settled_through": settled_through,
            "note": f"'today'={today!r} is not a valid ISO date -- " + _RECORD_STRIP_NOTE,
        }

    today_s = today_d.isoformat()
    last7_from = (today_d - timedelta(days=6)).isoformat()
    last30_from = (today_d - timedelta(days=29)).isoformat()
    ft = engine_bridge.FORWARD_TEST

    return {
        "today": _window("TODAY", today_s, today_s, wagers_all, settlement_idx,
                         system_class=ft),
        "last_7": _window("LAST 7 DAYS", last7_from, today_s, wagers_all,
                          settlement_idx, system_class=ft),
        "last_30": _window("LAST 30 DAYS", last30_from, today_s, wagers_all,
                           settlement_idx, system_class=ft),
        "all_classes": {
            "today": _window("TODAY", today_s, today_s, wagers_all, settlement_idx),
            "last_7": _window("LAST 7 DAYS", last7_from, today_s, wagers_all,
                              settlement_idx),
            "last_30": _window("LAST 30 DAYS", last30_from, today_s, wagers_all,
                               settlement_idx),
        },
        "settled_through": settled_through,
        "note": _RECORD_STRIP_NOTE,
    }
