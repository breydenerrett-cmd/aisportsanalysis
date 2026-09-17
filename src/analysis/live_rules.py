"""Live in-play research rules. Pre-registered v0 hypotheses.

WHY THIS EXISTS
---------------
These three rules are experimental forward tests registered on 2026-09-14
BEFORE the first observation. They evaluate live game state against pre-game
expectations to identify market inefficiencies. They are research instruments,
never picks, and never touch the card ledger.

Each rule fires under specific game conditions and returns a candidate bet
at the median price observed across books, if available.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional, Union

RULE_IDS = ("mlb_favorite_trails_after_3", "mlb_starter_pulled_early", "nfl_favorite_trails_halftime")

# R16-L5 (docs/LIVE_BETTING_SYSTEM.md 3.1 "Rule status"): a rule not
# registered or forward-testing captures nothing. The real registry has no
# "forward-testing" value defined yet (data/research/alpha_registry.jsonl's
# `status` defaults to "registered" -- see src.research.alpha_registry), but
# the design doc names both, so both are accepted here.
ALLOWED_RULE_STATUSES = frozenset({"registered", "forward-testing"})
UNREGISTERED_STATUS = "unregistered"

RegistryStatus = Union[None, Mapping[str, str], Callable[[str], str]]


def median_price(quotes: Optional[list[dict]], side: str) -> Optional[int]:
    """Median American price for a side across books, or None if unavailable.

    Args:
        quotes: List of {"book", "home_price", "away_price"} dicts, or None.
        side: "home" or "away".

    Returns:
        Median American price as int, or None if no quote has the side.
    """
    if not quotes:
        return None

    prices = []
    price_key = f"{side}_price"
    for quote in quotes:
        price = quote.get(price_key)
        if price is not None:
            prices.append(price)

    if not prices:
        return None

    prices_sorted = sorted(prices)
    n = len(prices_sorted)
    if n % 2 == 1:
        return int(prices_sorted[n // 2])
    # Even count: use lower of the two middle values
    return int(prices_sorted[n // 2 - 1])


MIN_FRESH_BOOKS = 3
DEFAULT_MAX_QUOTE_AGE_S = 60


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fresh_median_price(quotes: Optional[list[dict]], side: str, *, t0_utc: str,
                       captured_utc: str, max_age_s: float = DEFAULT_MAX_QUOTE_AGE_S,
                       min_fresh_books: int = MIN_FRESH_BOOKS) -> dict:
    """R16-L5/D9: the fresh-price rule from docs/LIVE_BETTING_SYSTEM.md 3.1
    (retrieval-time reading, the default until R16-L9 classifies
    `last_update`, per that section: "Retrieval time, or undetermined").

    A book's quote is FRESH when its `last_update` is at or after T0 and its
    age at capture (`captured_utc` minus `last_update`) is `max_age_s` or
    less. The logged price is the median (lower middle on an even count,
    same as `median_price`) across fresh books' prices for `side`, and needs
    at least `min_fresh_books` fresh books; below that, PRICED status is
    refused and no price is invented.

    Args:
        quotes: [{"book", "home_price", "away_price", "last_update"}, ...].
        side: "home" or "away".
        t0_utc: the trigger's T0 (`observed_utc` of the state row that
            satisfied the trigger condition).
        captured_utc: this capture's own `observed_utc`.

    Returns:
        {"price": int|None, "fresh_books": [...], "fresh_count": int,
         "excluded_stale": int, "excluded_no_last_update": int}. `price` is
        None (never a placebo number) whenever fewer than `min_fresh_books`
        books are fresh, even if the plain (unfiltered) median would exist.
    """
    result = {"price": None, "fresh_books": [], "fresh_count": 0,
              "excluded_stale": 0, "excluded_no_last_update": 0}
    if not quotes:
        return result

    t0 = _parse_dt(t0_utc)
    captured = _parse_dt(captured_utc)
    if t0 is None or captured is None:
        return result

    price_key = f"{side}_price"
    fresh = []
    for quote in quotes:
        last_update = _parse_dt(quote.get("last_update"))
        if last_update is None:
            result["excluded_no_last_update"] += 1
            continue
        if last_update < t0:
            result["excluded_stale"] += 1
            continue
        age_s = (captured - last_update).total_seconds()
        if age_s < 0 or age_s > max_age_s:
            result["excluded_stale"] += 1
            continue
        if quote.get(price_key) is None:
            continue
        fresh.append(quote)

    result["fresh_books"] = fresh
    result["fresh_count"] = len(fresh)
    if len(fresh) < min_fresh_books:
        return result

    prices = sorted(q[price_key] for q in fresh)
    n = len(prices)
    price = prices[n // 2] if n % 2 == 1 else prices[n // 2 - 1]
    result["price"] = int(price)
    return result


def evaluate(rule_id: str, *, pregame: Mapping, state: Mapping,
             quote: Optional[Mapping]) -> Optional[dict]:
    """Evaluate a single rule.

    Args:
        rule_id: One of RULE_IDS.
        pregame: {"sport", "game_id", "favorite": "home"|"away",
                  "favorite_prob": float, "home_team", "away_team",
                  "starter_ids": {"home": id, "away": id} (mlb only),
                  "kickoff_utc": datetime str (nfl only)}.
        state: Live state row (mlb: livefeed_mlb shape;
               nfl: livefeed_nfl shape).
        quote: {"observed_utc": datetime str, "quotes": [...]}, or None.

    Returns:
        {"rule_id", "sport", "game_id", "side", "team", "bet", "price",
         "books", "state_id", "observed_utc", "trigger": {...}}, or None.
    """
    if rule_id == "mlb_favorite_trails_after_3":
        return _mlb_favorite_trails_after_3(pregame, state, quote)
    elif rule_id == "mlb_starter_pulled_early":
        return _mlb_starter_pulled_early(pregame, state, quote)
    elif rule_id == "nfl_favorite_trails_halftime":
        return _nfl_favorite_trails_halftime(pregame, state, quote)
    return None


def _rules_for_sport(sport: str) -> list[str]:
    if sport == "mlb":
        return ["mlb_favorite_trails_after_3", "mlb_starter_pulled_early"]
    if sport == "nfl":
        return ["nfl_favorite_trails_halftime"]
    return []


def default_registry_status(path=None) -> dict[str, str]:
    """Rule status for every RULE_IDS entry, read from the real alpha
    registry (R16-L5). NEVER call this from a test -- pass `registry_status`
    to `evaluate_all`/`check_all_triggers` instead, so a test never touches
    the real ledger file (the acceptance criterion this exists to satisfy).

    A registration row's `id` may be the bare rule id (e.g.
    "mlb_favorite_trails_after_3") or the LIVE_V0 naming convention
    ("LIVE_V0:mlb_favorite_trails_after_3:h2h", per
    docs/PREREG_MULTI_SPORT_2026-09-14.md, where the rule id sits in the
    MIDDLE of the colon-separated id, not at either end) -- both are
    matched. A rule with
    no matching registered row is "unregistered": it captures nothing until
    one exists. Any failure to read the registry (missing file, bad JSON)
    also yields "unregistered" for every rule -- fail closed, never invent a
    status that lets an unproven rule spend a credit.
    """
    status = {rid: UNREGISTERED_STATUS for rid in RULE_IDS}
    try:
        from src.research import alpha_registry
        rows = alpha_registry.read_all(path)
    except Exception:
        return status

    for row in rows:
        if row.get("kind") not in ("hypothesis", "sweep", "audit"):
            continue
        row_id = str(row.get("id") or "")
        row_id_parts = row_id.split(":")
        for rid in RULE_IDS:
            if row_id == rid or rid in row_id_parts:
                status[rid] = row.get("status") or UNREGISTERED_STATUS

    return status


def registry_status_for_sport(sport: str, registry_status: RegistryStatus = None) -> dict[str, str]:
    """Public convenience: resolved {rule_id: status} for every rule this
    sport runs, via the same resolution `evaluate_all`/`check_all_triggers`
    use. Exists for the window-evidence artifact (`live_window.tick`),
    which must report registry status even for a rule whose trigger
    condition was never checked because an earlier gate already excluded
    it -- `check_all_triggers` alone never surfaces that distinction.
    """
    return _resolve_registry_status(registry_status, _rules_for_sport(sport))


def _resolve_registry_status(registry_status: RegistryStatus, rules: list[str]) -> dict[str, str]:
    """Turn the injected `registry_status` (None, a dict, or a callable) into
    a plain {rule_id: status} map for exactly the rules being evaluated.

    None means "use the real registry" (production default); a dict or
    callable is what every test passes, so no test call ever reaches disk.
    """
    if registry_status is None:
        return default_registry_status()
    if callable(registry_status):
        return {rid: (registry_status(rid) or UNREGISTERED_STATUS) for rid in rules}
    return dict(registry_status)


def evaluate_all(*, pregame: Mapping, state: Mapping,
                 quote: Optional[Mapping],
                 registry_status: RegistryStatus = None) -> list[dict]:
    """Evaluate all rules for this game's sport, gated by registry status.

    R16-L5: a rule whose registry status is not "registered" or
    "forward-testing" is skipped entirely -- it fires no trigger and
    captures nothing, however its game state looks. `registry_status` is
    injectable (None: real registry; dict or rule_id -> status callable:
    everything a test needs) so this never has to touch
    `data/research/alpha_registry.jsonl` in a test.

    Returns:
        List of candidates (dicts from evaluate() that fired and have quotes).
    """
    sport = pregame.get("sport", "mlb")
    rules = _rules_for_sport(sport)
    if not rules:
        return []

    status_map = _resolve_registry_status(registry_status, rules)

    candidates = []
    for rule_id in rules:
        if status_map.get(rule_id, UNREGISTERED_STATUS) not in ALLOWED_RULE_STATUSES:
            continue
        candidate = evaluate(rule_id, pregame=pregame, state=state, quote=quote)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def rule_diagnostic(rule_id: str, *, pregame: Mapping, state: Mapping) -> Optional[dict]:
    """Structured, always-on diagnostic for one rule against one state row.

    Unlike `check_trigger` (yes/no, no quote), this reports the ACTUAL
    observed values whether or not the condition holds, plus a `distance`:
    0.0 when the condition holds, otherwise a nonnegative score comparable
    only within the same rule_id (smaller = closer to firing; the units mix
    different fields on purpose and are never compared across rule_ids).

    Built for the window-evidence artifact (docs/LIVE_BETTING_SYSTEM.md 3.1
    closest-miss reporting): the 2026-09-16 incident this exists to prevent
    was a 511-tick, zero-candidate window with no record of what the
    evaluator actually saw. Tracking the minimum `distance` seen across a
    window's ticks, per (game, rule), is what lets a reader learn "TOR
    margin=-1, favorite_prob=0.551" instead of a bare zero.

    Returns None for a rule_id this sport does not run (mirrors
    `_rules_for_sport`) -- never invents a cross-sport diagnostic.
    """
    if rule_id == "mlb_favorite_trails_after_3":
        return _diag_mlb_favorite_trails_after_3(pregame, state)
    if rule_id == "mlb_starter_pulled_early":
        return _diag_mlb_starter_pulled_early(pregame, state)
    if rule_id == "nfl_favorite_trails_halftime":
        return _diag_nfl_favorite_trails_halftime(pregame, state)
    return None


def _diag_mlb_favorite_trails_after_3(pregame: Mapping, state: Mapping) -> dict:
    favorite_prob = pregame.get("favorite_prob")
    favorite_side = pregame.get("favorite")
    inning = state.get("inning")
    inning_state = state.get("inning_state")
    half = state.get("half")
    outs = state.get("outs")
    home_runs = state.get("home_runs")
    away_runs = state.get("away_runs")

    third_ended = (inning == 3 and inning_state == "End") or (
        inning == 4 and half == "top" and outs == 0)

    margin = None
    if favorite_side in ("home", "away") and home_runs is not None and away_runs is not None:
        margin = (home_runs - away_runs) if favorite_side == "home" else (away_runs - home_runs)

    condition_met = bool(
        (favorite_prob or 0) >= 0.55 and third_ended
        and margin is not None and -2 <= margin <= -1)

    prob_gap = max(0.0, 0.55 - favorite_prob) if favorite_prob is not None else float("inf")
    timing_gap = 0.0 if third_ended else 1.0
    if margin is None:
        margin_gap = float("inf")
    elif -2 <= margin <= -1:
        margin_gap = 0.0
    else:
        margin_gap = min(abs(margin - (-1)), abs(margin - (-2)))

    return {
        "rule_id": "mlb_favorite_trails_after_3",
        "condition_met": condition_met,
        "distance": 0.0 if condition_met else prob_gap * 100 + timing_gap * 50 + margin_gap,
        "values": {
            "favorite_prob": favorite_prob,
            "favorite_side": favorite_side,
            "inning": inning,
            "inning_state": inning_state,
            "half": half,
            "outs": outs,
            "margin": margin,
            "observed_utc": state.get("observed_utc"),
        },
    }


def _diag_mlb_starter_pulled_early(pregame: Mapping, state: Mapping) -> dict:
    favorite_side = pregame.get("favorite")
    half = state.get("half")
    inning = state.get("inning", 0)
    current_pitcher = state.get("pitcher_id")
    starter_ids = pregame.get("starter_ids") or {}
    pregame_starter = starter_ids.get(favorite_side) if favorite_side in ("home", "away") else None
    home_runs = state.get("home_runs")
    away_runs = state.get("away_runs")

    favorite_on_defense = (
        (favorite_side == "home" and half == "top")
        or (favorite_side == "away" and half == "bottom"))

    margin = None
    if favorite_side in ("home", "away") and home_runs is not None and away_runs is not None:
        margin = (home_runs - away_runs) if favorite_side == "home" else (away_runs - home_runs)

    pitcher_changed = (
        current_pitcher is not None and pregame_starter is not None
        and current_pitcher != pregame_starter)

    condition_met = bool(
        favorite_on_defense and (inning or 0) <= 4 and pitcher_changed
        and margin is not None and margin >= 0)

    half_gap = 0.0 if favorite_on_defense else 1.0
    inning_gap = 0.0 if (inning or 0) <= 4 else float((inning or 0) - 4)
    if current_pitcher is None or pregame_starter is None:
        pitcher_gap = float("inf")
    else:
        pitcher_gap = 0.0 if pitcher_changed else 1.0
    margin_gap = 0.0 if (margin is not None and margin >= 0) else (
        float("inf") if margin is None else abs(margin))

    return {
        "rule_id": "mlb_starter_pulled_early",
        "condition_met": condition_met,
        "distance": 0.0 if condition_met else (
            half_gap * 50 + inning_gap * 20 + pitcher_gap * 30 + margin_gap),
        "values": {
            "favorite_side": favorite_side,
            "half": half,
            "inning": inning,
            "current_pitcher": current_pitcher,
            "pregame_starter": pregame_starter,
            "margin": margin,
            "observed_utc": state.get("observed_utc"),
        },
    }


def _diag_nfl_favorite_trails_halftime(pregame: Mapping, state: Mapping) -> dict:
    favorite_prob = pregame.get("favorite_prob")
    favorite_side = pregame.get("favorite")
    completed = bool(state.get("completed", False))
    observed_utc_str = state.get("observed_utc")
    commence_utc_str = pregame.get("kickoff_utc") or state.get("commence_time")
    home_score = state.get("home_score")
    away_score = state.get("away_score")

    elapsed = None
    if observed_utc_str and commence_utc_str:
        observed_dt = _parse_dt(observed_utc_str)
        commence_dt = _parse_dt(commence_utc_str)
        if observed_dt is not None and commence_dt is not None:
            elapsed = (observed_dt - commence_dt).total_seconds() / 60

    margin = None
    if favorite_side in ("home", "away") and home_score is not None and away_score is not None:
        margin = (home_score - away_score) if favorite_side == "home" else (away_score - home_score)

    in_window = elapsed is not None and 80 <= elapsed <= 100
    condition_met = bool(
        (favorite_prob or 0) >= 0.60 and not completed and in_window
        and margin is not None and -7 <= margin <= -1)

    prob_gap = max(0.0, 0.60 - favorite_prob) if favorite_prob is not None else float("inf")
    completed_gap = 1.0 if completed else 0.0
    if elapsed is None:
        elapsed_gap = float("inf")
    elif in_window:
        elapsed_gap = 0.0
    else:
        elapsed_gap = min(abs(elapsed - 80), abs(elapsed - 100))
    if margin is None:
        margin_gap = float("inf")
    elif -7 <= margin <= -1:
        margin_gap = 0.0
    else:
        margin_gap = min(abs(margin - (-1)), abs(margin - (-7)))

    return {
        "rule_id": "nfl_favorite_trails_halftime",
        "condition_met": condition_met,
        "distance": 0.0 if condition_met else (
            prob_gap * 100 + completed_gap * 200 + elapsed_gap + margin_gap),
        "values": {
            "favorite_prob": favorite_prob,
            "favorite_side": favorite_side,
            "completed": completed,
            "elapsed_minutes": round(elapsed, 1) if elapsed is not None else None,
            "margin": margin,
            "observed_utc": observed_utc_str,
        },
    }


def check_trigger(rule_id: str, *, pregame: Mapping, state: Mapping) -> Optional[dict]:
    """Whether `rule_id`'s trigger CONDITION holds right now -- no quote, no
    price, no registry check. Pure and cheap on purpose: this is what a
    caller runs on every poll, for every game, BEFORE spending any credit on
    an in-play fetch (3.1: "capture only on a registered trigger in this
    poll"). Returns the same `trigger` dict `evaluate()` would attach to a
    priced candidate, or None if the condition does not hold.
    """
    if rule_id == "mlb_favorite_trails_after_3":
        return _trigger_mlb_favorite_trails_after_3(pregame, state)
    if rule_id == "mlb_starter_pulled_early":
        return _trigger_mlb_starter_pulled_early(pregame, state)
    if rule_id == "nfl_favorite_trails_halftime":
        return _trigger_nfl_favorite_trails_halftime(pregame, state)
    return None


def check_all_triggers(*, pregame: Mapping, state: Mapping,
                       registry_status: RegistryStatus = None) -> dict[str, dict]:
    """{rule_id: trigger_info} for every registered/forward-testing rule
    whose trigger condition holds right now, for this one game and poll.

    This is the gate a runner checks BEFORE deciding to spend a credit on an
    in-play fetch (3.1) -- distinct from `evaluate_all`, which additionally
    needs a quote to price a candidate. Both share the same registry gate
    (`_resolve_registry_status`): a rule that is not registered or
    forward-testing appears in neither.
    """
    sport = pregame.get("sport", "mlb")
    rules = _rules_for_sport(sport)
    if not rules:
        return {}

    status_map = _resolve_registry_status(registry_status, rules)

    fired: dict[str, dict] = {}
    for rule_id in rules:
        if status_map.get(rule_id, UNREGISTERED_STATUS) not in ALLOWED_RULE_STATUSES:
            continue
        info = check_trigger(rule_id, pregame=pregame, state=state)
        if info is not None:
            fired[rule_id] = info
    return fired


# ---------------------------------------------------------------------------
# MLB Rules
# ---------------------------------------------------------------------------

def _trigger_mlb_favorite_trails_after_3(pregame: Mapping, state: Mapping) -> Optional[dict]:
    """Trigger condition only, no quote: favourite is heavy favourite,
    trails by 1-2 runs at end of 3rd. See `_mlb_favorite_trails_after_3` for
    the full rule (this is its trigger half, split out so a runner can check
    it -- and decide whether to spend a credit -- before any quote exists).

    Rule fires when:
    - favorite_prob >= 0.55
    - Third inning has ended (inning == 3 and inning_state == "End") OR
      (inning == 4 and half == "top" and outs == 0: top of the 4th)
    - Favourite trails by exactly 1 or 2 runs
    """
    # Check probability threshold. A None favourite probability (fewer than
    # six books before the game) means no pre-game favourite and no rule.
    if (pregame.get("favorite_prob") or 0) < 0.55:
        return None

    # Check inning threshold: third inning has ended
    inning = state.get("inning")
    inning_state = state.get("inning_state")
    half = state.get("half")
    outs = state.get("outs")

    third_ended = False
    if inning == 3 and inning_state == "End":
        third_ended = True
    elif inning == 4 and half == "top" and outs == 0:
        # Top of the 4th, nobody out: the 3rd has just ended. Exactly the
        # 4th, not "4 or later" -- a first observation in the 7th is a
        # different game state and a different hypothesis.
        third_ended = True

    if not third_ended:
        return None

    # Check run margin: favourite trails by 1 or 2 runs
    favorite_side = pregame.get("favorite")
    home_runs = state.get("home_runs", 0)
    away_runs = state.get("away_runs", 0)

    if favorite_side == "home":
        margin = home_runs - away_runs
    else:
        margin = away_runs - home_runs

    if margin >= 0 or margin < -2:  # Not trailing or trailing by more than 2
        return None

    return {
        "favorite_side": favorite_side,
        "inning": inning,
        "inning_state": inning_state,
        "margin": margin,
        "favorite_prob": pregame.get("favorite_prob"),
    }


def _mlb_favorite_trails_after_3(pregame: Mapping, state: Mapping,
                                  quote: Optional[Mapping]) -> Optional[dict]:
    """Favourite is heavy favourite, trails by 1-2 runs at end of 3rd.

    Candidate side: the favourite. See `_trigger_mlb_favorite_trails_after_3`
    for the trigger condition; this adds pricing on top of it.
    """
    trigger_info = _trigger_mlb_favorite_trails_after_3(pregame, state)
    if trigger_info is None:
        return None

    favorite_side = trigger_info["favorite_side"]

    # Get quote for favourite side
    quotes = quote.get("quotes") if quote else None
    price = median_price(quotes, favorite_side)
    if price is None:
        return None

    # Build candidate
    home_team = pregame.get("home_team")
    away_team = pregame.get("away_team")
    team = home_team if favorite_side == "home" else away_team

    state_id = _make_state_id(pregame.get("game_id"), state.get("observed_utc"))

    return {
        "rule_id": "mlb_favorite_trails_after_3",
        "sport": "mlb",
        "game_id": pregame.get("game_id"),
        "side": favorite_side,
        "team": team,
        "bet": f"{team} moneyline, in play",
        "price": price,
        "books": len(quotes) if quotes else 0,
        "state_id": state_id,
        "observed_utc": quote.get("observed_utc") if quote else state.get("observed_utc"),
        "trigger": {
            "inning": trigger_info["inning"],
            "inning_state": trigger_info["inning_state"],
            "margin": trigger_info["margin"],
            "favorite_prob": trigger_info["favorite_prob"],
        }
    }


def _mlb_starter_pulled_early(pregame: Mapping, state: Mapping,
                               quote: Optional[Mapping]) -> Optional[dict]:
    """Starter pulled before 4 innings while favourite leads or is tied.

    Rule fires when:
    - Favourite is on defence (half matches favourite's side logic)
    - inning <= 4
    - Pitcher changed from the starter recorded in `pregame["starter_ids"]`
    - Favourite leads or is tied

    Candidate side: the opponent.

    THE CONTRACT ON `pregame["starter_ids"]` (D12, docs/LIVE_BETTING_SYSTEM.md
    section 2.3). The rule's registered text says "the favourite's STARTING
    pitcher" -- the pitcher who actually took the mound -- not "the pitcher
    the schedule listed as probable before the game". Before first pitch
    those are usually the same person, but a late scratch or an opener means
    they are not, and this rule would then fire on the very first batter of
    the game because the "pregame starter" it is comparing against was never
    the real starter.

    `live_rules.py` has no state history of its own -- it evaluates one tick
    at a time and remembers nothing between calls -- so it cannot determine
    "the first pitcher seen on the favourite's defence" by itself. THE
    CALLER MUST: seed `pregame["starter_ids"][favorite_side]` with the
    pregame PROBABLE pitcher only until the game's first live state row with
    a non-null `pitcher_id` on the favourite's defensive half-inning is
    observed, and from that tick onward pass the pitcher_id OBSERVED on that
    first such row instead -- never the probable, once a real one has been
    seen. `livefeed_mlb.build_pregame_context` documents the same contract
    on its `starter_ids` field and returns the pregame probable pitcher as
    the only value knowable before any state row exists; a live tick loop
    (`live_window.tick`, once wired to the builder) is what must perform the
    overwrite this docstring describes, using `first_defensive_pitcher`
    below against that game's accumulated state rows.

    Until a caller performs that overwrite, this rule is comparing against
    the probable pitcher exactly as before -- correct pregame, potentially
    wrong the instant a late scratch or opener is used, which is exactly
    the gap D12 records (EXPLORATORY: 0 of 121 forward games differed in
    2026, so rare, not impossible).
    """
    trigger_info = _trigger_mlb_starter_pulled_early(pregame, state)
    if trigger_info is None:
        return None

    favorite_side = trigger_info["favorite_side"]
    opponent_side = trigger_info["opponent_side"]

    # Get quote for opponent (the side NOT the favourite)
    quotes = quote.get("quotes") if quote else None
    price = median_price(quotes, opponent_side)
    if price is None:
        return None

    # Build candidate
    home_team = pregame.get("home_team")
    away_team = pregame.get("away_team")
    opponent_team = away_team if favorite_side == "home" else home_team

    state_id = _make_state_id(pregame.get("game_id"), state.get("observed_utc"))

    return {
        "rule_id": "mlb_starter_pulled_early",
        "sport": "mlb",
        "game_id": pregame.get("game_id"),
        "side": opponent_side,
        "team": opponent_team,
        "bet": f"{opponent_team} moneyline, in play",
        "price": price,
        "books": len(quotes) if quotes else 0,
        "state_id": state_id,
        "observed_utc": quote.get("observed_utc") if quote else state.get("observed_utc"),
        "trigger": {
            "inning": trigger_info["inning"],
            "margin": trigger_info["margin"],
            "pitcher_changed": True,
        }
    }


def _trigger_mlb_starter_pulled_early(pregame: Mapping, state: Mapping) -> Optional[dict]:
    """Trigger condition only, no quote: see
    `_mlb_starter_pulled_early`'s docstring for the full contract on
    `pregame["starter_ids"]` this depends on (D12)."""
    favorite_side = pregame.get("favorite")

    # Check if favourite is on defence
    half = state.get("half")
    if favorite_side == "home" and half != "top":
        return None  # Home team favourite, but it's bottom, so they're batting
    if favorite_side == "away" and half != "bottom":
        return None  # Away team favourite, but it's top, so they're batting

    # Check inning (must be <= 4)
    inning = state.get("inning", 0)
    if inning > 4:
        return None

    # Check pitcher changed
    current_pitcher = state.get("pitcher_id")
    starter_ids = pregame.get("starter_ids") or {}
    pregame_starter = starter_ids.get(favorite_side)

    if current_pitcher is None or pregame_starter is None:
        return None

    if current_pitcher == pregame_starter:
        return None  # Starter hasn't changed

    # Check favourite's score (leads or tied)
    home_runs = state.get("home_runs", 0)
    away_runs = state.get("away_runs", 0)

    if favorite_side == "home":
        margin = home_runs - away_runs
    else:
        margin = away_runs - home_runs

    if margin < 0:  # Favourite is trailing
        return None

    opponent_side = "away" if favorite_side == "home" else "home"
    return {
        "favorite_side": favorite_side,
        "opponent_side": opponent_side,
        "inning": inning,
        "margin": margin,
    }


# ---------------------------------------------------------------------------
# NFL Rules
# ---------------------------------------------------------------------------

def _nfl_favorite_trails_halftime(pregame: Mapping, state: Mapping,
                                   quote: Optional[Mapping]) -> Optional[dict]:
    """Heavy favourite trails by 1-7 points at halftime.

    Halftime is PROXIED by elapsed time: 80 to 100 minutes after commence_time
    at observed_utc, not completed.

    Rule fires when:
    - favorite_prob >= 0.60
    - Elapsed time is 80-100 minutes after commence_time
    - Game is not yet completed
    - Favourite trails by 1 to 7 points

    Candidate side: the favourite. Evaluated every poll (D5/R16-L5), not
    only on score changes -- see `_trigger_nfl_favorite_trails_halftime`.
    """
    observed_utc_str = quote.get("observed_utc") if quote else state.get("observed_utc")

    trigger_info = _trigger_nfl_favorite_trails_halftime(
        pregame, state, observed_utc_override=observed_utc_str)
    if trigger_info is None:
        return None

    favorite_side = trigger_info["favorite_side"]

    # Get quote for favourite side
    quotes = quote.get("quotes") if quote else None
    price = median_price(quotes, favorite_side)
    if price is None:
        return None

    # Build candidate
    home_team = pregame.get("home_team")
    away_team = pregame.get("away_team")
    team = home_team if favorite_side == "home" else away_team

    state_id = _make_state_id(pregame.get("game_id"), trigger_info["observed_utc"])

    return {
        "rule_id": "nfl_favorite_trails_halftime",
        "sport": "nfl",
        "game_id": pregame.get("game_id"),
        "side": favorite_side,
        "team": team,
        "bet": f"{team} moneyline, in play",
        "price": price,
        "books": len(quotes) if quotes else 0,
        "state_id": state_id,
        "observed_utc": trigger_info["observed_utc"],
        "trigger": {
            "elapsed_minutes": trigger_info["elapsed_minutes"],
            "margin": trigger_info["margin"],
            "favorite_prob": trigger_info["favorite_prob"],
        }
    }


def _trigger_nfl_favorite_trails_halftime(pregame: Mapping, state: Mapping,
                                          observed_utc_override: Optional[str] = None) -> Optional[dict]:
    """Trigger condition only, no quote: this is a TIME-based trigger (the
    halftime proxy), so it is evaluated on every poll regardless of whether
    the score changed (fixes D5) -- a caller must call this every tick, for
    every live NFL game, not only when `state` differs from the last poll.

    `observed_utc_override` lets a caller (and `_nfl_favorite_trails_halftime`
    itself, once a quote exists) supply the quote's own `observed_utc`
    instead of the state row's, matching the pre-refactor behaviour where the
    elapsed-time check preferred the quote's timestamp when one was already
    in hand; a pure trigger check with no quote yet falls back to the state
    row's `observed_utc`.
    """
    # Check probability threshold (None = no pre-game favourite, no rule).
    if (pregame.get("favorite_prob") or 0) < 0.60:
        return None

    # Check if game is not completed
    if state.get("completed", False):
        return None

    # Check halftime proxy: elapsed time
    observed_utc_str = observed_utc_override or state.get("observed_utc")
    if not observed_utc_str:
        return None

    commence_utc_str = pregame.get("kickoff_utc") or state.get("commence_time")
    if not commence_utc_str:
        return None

    try:
        observed_dt = datetime.fromisoformat(observed_utc_str.replace("Z", "+00:00"))
        if observed_dt.tzinfo is None:
            observed_dt = observed_dt.replace(tzinfo=timezone.utc)

        commence_dt = datetime.fromisoformat(commence_utc_str.replace("Z", "+00:00"))
        if commence_dt.tzinfo is None:
            commence_dt = commence_dt.replace(tzinfo=timezone.utc)

        elapsed = (observed_dt - commence_dt).total_seconds() / 60  # minutes
    except (ValueError, TypeError):
        return None

    if elapsed < 80 or elapsed > 100:
        return None

    # Check score margin: favourite trails by 1 to 7 points
    favorite_side = pregame.get("favorite")
    home_score = state.get("home_score", 0)
    away_score = state.get("away_score", 0)

    if favorite_side == "home":
        margin = home_score - away_score
    else:
        margin = away_score - home_score

    if margin >= 0 or margin < -7:  # Not trailing or trailing by more than 7
        return None

    return {
        "favorite_side": favorite_side,
        "observed_utc": observed_utc_str,
        "elapsed_minutes": round(elapsed, 1),
        "margin": margin,
        "favorite_prob": pregame.get("favorite_prob"),
    }


def first_defensive_pitcher(state_rows, favorite_side: str) -> Optional[int]:
    """The pitcher_id first observed on `favorite_side`'s defence, or None.

    Implements the "starter" `_mlb_starter_pulled_early`'s docstring (D12)
    requires the caller to compute: not the pregame probable pitcher, but
    the pitcher actually seen on the mound once the game is under way.

    Args:
        state_rows: `livefeed_mlb` state rows for ONE game, in observation
            order (oldest first) -- e.g. `livefeed_mlb.read_states(date)`
            filtered to one `game_pk`.
        favorite_side: "home" or "away" -- the favourite is on DEFENCE when
            the OPPOSITE side is batting: home favourite -> top half (away
            bats), away favourite -> bottom half.

    Returns:
        The first non-null `pitcher_id` recorded while the favourite was on
        defence, in row order, or None if no such row exists yet (the game
        has not reached that state, or every row is missing a pitcher_id).
        Never invents a value: an empty or all-None input returns None.
    """
    defensive_half = "top" if favorite_side == "home" else "bottom"
    for row in state_rows or []:
        if row.get("half") != defensive_half:
            continue
        pitcher_id = row.get("pitcher_id")
        if pitcher_id is not None:
            return pitcher_id
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _make_state_id(game_id: str, observed_utc: Optional[str]) -> str:
    """Build a short stable id from game_id and observed_utc.

    Used as state_id for dedup: sha1(game_id + observed_utc)[:16].
    """
    import hashlib

    if not game_id or not observed_utc:
        return hashlib.sha1(b"").hexdigest()[:16]

    key = f"{game_id}:{observed_utc}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
