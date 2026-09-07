"""Read-only bridge from the engine's decision/wager ledgers to the game
surface: which SYSTEM CLASS made which call about which real game, joined
by `event_id` through the multi-book store's own team names.

WHY THIS EXISTS
----------------
The engine's ledgers (`src.engine.settle_slate.load_decisions`,
`wagers_for_date`) speak `event_id` and `system_id`. The game surface
(`api/games.py`, `src/analysis/opportunities.py`) speaks
`(away_abbrev, home_abbrev, date)`. Nothing joined the two before this
module -- every join here is identity only (which decision belongs to
which game), never a re-derivation of the decision's own numbers.

READ-ONLY, ALWAYS
------------------
Every function in this module only reads ledgers (`HashChainLedger(...).read()`
via `load_decisions`/`wagers_for_date`) and the multi-book store
(`src.pipeline.snapshots.read_multibook`). Nothing here appends, settles,
or runs a slate. Every function tolerates a missing store -- the container
this runs in may not have every store on disk -- returning an empty
structure rather than raising.

THREE SYSTEM CLASSES, NEVER CONFLATED
---------------------------------------
- CONTROL (`trivial_*`): a null baseline, never a reason to bet.
- MARKET_REFERENCE (`market_derived_consensus_*`): republishes the board's
  own de-vigged consensus as `p_model` -- restating the market, not beating
  it.
- FORWARD_TEST (anything else): an unproven directional thesis
  (`p_model` is None; `p_model_provenance` is never `model_derived` on any
  live system). Only a FORWARD_TEST play may ever be shown as "engine
  interest", and only tagged FORWARD TEST / UNPROVEN -- see
  `src/analysis/opportunities.py`, which is the one caller that renders
  these summaries to a customer.
"""

from __future__ import annotations

from typing import Optional

from src.data import parks
from src.engine.settle_slate import load_decisions, wagers_for_date
from src.pipeline import slate as slate_mod
from src.pipeline import snapshots


def game_key(away, home, date) -> tuple:
    """The key an engine-decision join is filed under, and the only key to
    look one up by: CANONICAL abbreviations plus the MLB official date.

    Same lesson as src/analysis/prices.matchup_key: the MLB schedule says
    ATH and AZ where the odds feed's club names resolve to OAK and ARI.
    Comparing raw abbreviations silently dropped the Athletics' engine
    decisions on 2026-09-07 (every other game joined; TOR@ATH came back
    `engine: None`). An unknown abbreviation falls back to its upper-cased
    self rather than raising -- a join must never take a page down."""
    def _canon(value):
        try:
            return parks.canonical_team(value or "")
        except parks.ParkError:
            return str(value or "").strip().upper()
    return (_canon(away), _canon(home), date)

CONTROL = "CONTROL"
MARKET_REFERENCE = "MARKET_REFERENCE"
FORWARD_TEST = "FORWARD_TEST"

_CONTROL_PREFIX = "trivial_"
_MARKET_REFERENCE_PREFIX = "market_derived_consensus_"

FATAL = "FATAL"


def system_class(system_id) -> str:
    """CONTROL / MARKET_REFERENCE / FORWARD_TEST for one `system_id`.

    Prefix rules only -- `src.engine.adapters.evolab_system.REGISTERED_SYSTEMS`
    is where these ids are actually minted; this function never imports that
    module, so a new forward-test system needs no change here to classify
    correctly (it falls through to FORWARD_TEST, the conservative default).
    An unset/empty id is FORWARD_TEST too, for the same reason: unknown is
    never treated as a null baseline or as the market itself.
    """
    if not system_id or not isinstance(system_id, str):
        return FORWARD_TEST
    if system_id.startswith(_CONTROL_PREFIX):
        return CONTROL
    if system_id.startswith(_MARKET_REFERENCE_PREFIX):
        return MARKET_REFERENCE
    return FORWARD_TEST


def _field(obj, name, default=None):
    """`obj.name` for a real record, or `obj[name]` for a plain dict -- so
    this module accepts either a real `DecisionRecord` (what
    `load_decisions` returns) or a pre-built dict (what a test fixture may
    pass instead of constructing one), per this task's own allowance."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def event_index(rows=None) -> dict:
    """`{event_id: {away_abbrev, home_abbrev, away_name, home_name,
    commence_time, date}}`, built once from the multi-book store's own
    event rows (the same store `src.analysis.prices` reads boards from) --
    the one place an odds `event_id` is translated into the abbreviations
    and MLB official date the rest of the game surface keys on.

    Tolerates a missing/unreadable store: `snapshots.read_multibook`
    already returns `[]` for a missing file, and any other failure here is
    caught rather than propagated, since a container without this store
    must still serve the rest of the game surface.
    """
    try:
        source = snapshots.read_multibook() if rows is None else rows
    except Exception:
        return {}
    out: dict = {}
    for row in source or ():
        event_id = row.get("event_id")
        if not event_id or event_id in out:
            continue
        away_name, home_name = row.get("away_team"), row.get("home_team")
        commence = row.get("commence_time")
        try:
            date = snapshots.official_date(commence) if commence else None
        except Exception:
            date = None
        out[event_id] = {
            "away_abbrev": slate_mod.team_abbrev_from_name(away_name or ""),
            "home_abbrev": slate_mod.team_abbrev_from_name(home_name or ""),
            "away_name": away_name,
            "home_name": home_name,
            "commence_time": commence,
            "date": date,
        }
    return out


def _counterargument_wire(counterarguments) -> list:
    out = []
    for ca in counterarguments or ():
        if isinstance(ca, dict):
            out.append({"severity": ca.get("severity"), "cause": ca.get("cause"),
                        "detail": ca.get("detail")})
        else:
            out.append({"severity": getattr(ca, "severity", None),
                        "cause": getattr(ca, "cause", None),
                        "detail": getattr(ca, "detail", None)})
    return out


def _wager_lookup(wagers) -> dict:
    """`{(event_id, system_id): wager_row}`, first row wins -- one wager per
    (event, system) is the normal case; a duplicate is a re-run artifact,
    never a second decision to prefer over the first."""
    out: dict = {}
    for row in wagers or ():
        key = (row.get("event_id"), row.get("system_id"))
        out.setdefault(key, row)
    return out


def decisions_for_date(date, decisions=None, wagers=None) -> dict:
    """`{(away_abbrev, home_abbrev, date): [summary, ...]}` for every
    engine decision whose event resolves to a game on `date`.

    `decisions`/`wagers` are dependency-injected (default: the real
    ledgers, `load_decisions()` / `wagers_for_date(date)`) so a caller --
    tests above all -- can pass a small fixture instead of touching disk.
    Both reads, and the `event_index()` join, are wrapped so a missing or
    unreadable store degrades to "no engine decisions joined" rather than
    a 500 reaching a customer.
    """
    try:
        decisions = load_decisions() if decisions is None else decisions
    except Exception:
        decisions = ()
    try:
        wagers = wagers_for_date(date) if wagers is None else wagers
    except Exception:
        wagers = ()
    try:
        idx = event_index()
    except Exception:
        idx = {}

    wager_idx = _wager_lookup(wagers)
    out: dict = {}
    for decision in decisions or ():
        event_id = _field(decision, "event_id")
        info = idx.get(event_id)
        if not info or info.get("date") != date:
            continue
        away, home = info.get("away_abbrev"), info.get("home_abbrev")
        if not away or not home:
            continue
        system_id = _field(decision, "system_id")
        wager = wager_idx.get((event_id, system_id))
        selection_id = _field(decision, "selection_id")
        side_or_selection = (wager.get("side") if wager else None) or selection_id
        cls = system_class(system_id)
        summary = {
            "system_id": system_id,
            "system_class": cls,
            "verdict": _field(decision, "verdict"),
            "market_key": _field(decision, "market_key"),
            "side_or_selection": side_or_selection,
            "line": _field(decision, "line"),
            "price_american": _field(decision, "price_american"),
            "consensus_fair": _field(decision, "consensus_fair"),
            "books_at_decision": _field(decision, "books_at_decision"),
            "p_model_provenance": _field(decision, "p_model_provenance"),
            "known_at_grade": _field(decision, "known_at_grade"),
            "counterarguments": _counterargument_wire(
                _field(decision, "counterarguments")),
            # A thesis is ever shown ONLY for a FORWARD_TEST system -- a
            # CONTROL's or MARKET_REFERENCE's "thesis" (if either even
            # carries one) is never customer-facing reasoning.
            "thesis": _field(decision, "thesis") if cls == FORWARD_TEST else None,
            "decision_utc": _field(decision, "decision_utc"),
            "staked": wager is not None,
        }
        out.setdefault(game_key(away, home, date), []).append(summary)
    return out


def summarize_game(summaries) -> dict:
    """One game's rollup of `decisions_for_date`'s per-decision summaries.

    `forward_test_plays` names the ONLY class of decision this codebase
    ever presents as "engine interest" -- a CONTROL playing is meaningless
    by construction, and a MARKET_REFERENCE playing is just the board
    talking to itself.
    """
    summaries = list(summaries or ())
    n_play = sum(1 for s in summaries if s.get("verdict") == "play")
    n_staked = sum(1 for s in summaries if s.get("staked"))
    forward_test_plays = [
        s for s in summaries
        if s.get("system_class") == FORWARD_TEST and s.get("verdict") == "play"
    ]
    market_reference_present = any(
        s.get("system_class") == MARKET_REFERENCE for s in summaries)
    fatal_counterarguments = [
        ca for s in summaries for ca in (s.get("counterarguments") or ())
        if ca.get("severity") == FATAL
    ]
    provenance_counts: dict = {}
    for s in summaries:
        prov = s.get("p_model_provenance")
        provenance_counts[prov] = provenance_counts.get(prov, 0) + 1
    return {
        "n_decisions": len(summaries),
        "n_play": n_play,
        "n_staked": n_staked,
        "forward_test_plays": forward_test_plays,
        "market_reference_present": market_reference_present,
        "fatal_counterarguments": fatal_counterarguments,
        "provenance_counts": provenance_counts,
    }
