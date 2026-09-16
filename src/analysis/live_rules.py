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
from typing import Mapping, Optional

RULE_IDS = ("mlb_favorite_trails_after_3", "mlb_starter_pulled_early", "nfl_favorite_trails_halftime")


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


def evaluate_all(*, pregame: Mapping, state: Mapping,
                 quote: Optional[Mapping]) -> list[dict]:
    """Evaluate all rules for this game's sport.

    Returns:
        List of candidates (dicts from evaluate() that fired and have quotes).
    """
    sport = pregame.get("sport", "mlb")
    candidates = []

    if sport == "mlb":
        rules = ["mlb_favorite_trails_after_3", "mlb_starter_pulled_early"]
    elif sport == "nfl":
        rules = ["nfl_favorite_trails_halftime"]
    else:
        return []

    for rule_id in rules:
        candidate = evaluate(rule_id, pregame=pregame, state=state, quote=quote)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


# ---------------------------------------------------------------------------
# MLB Rules
# ---------------------------------------------------------------------------

def _mlb_favorite_trails_after_3(pregame: Mapping, state: Mapping,
                                  quote: Optional[Mapping]) -> Optional[dict]:
    """Favourite is heavy favourite, trails by 1-2 runs at end of 3rd.

    Rule fires when:
    - favorite_prob >= 0.55
    - Third inning has ended (inning == 3 and inning_state == "End") OR
      (inning == 4 and half == "top" and outs == 0: top of the 4th)
    - Favourite trails by exactly 1 or 2 runs

    Candidate side: the favourite.
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

    # Trail by 1 or 2: margin is -1 or -2
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
            "inning": inning,
            "inning_state": inning_state,
            "margin": margin,
            "favorite_prob": pregame.get("favorite_prob"),
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

    # Get quote for opponent (the side NOT the favourite)
    opponent_side = "away" if favorite_side == "home" else "home"
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
            "inning": inning,
            "margin": margin,
            "pitcher_changed": True,
        }
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

    Candidate side: the favourite.
    """
    # Check probability threshold (None = no pre-game favourite, no rule).
    if (pregame.get("favorite_prob") or 0) < 0.60:
        return None

    # Check if game is not completed
    if state.get("completed", False):
        return None

    # Check halftime proxy: elapsed time
    observed_utc_str = quote.get("observed_utc") if quote else state.get("observed_utc")
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

    # Trail by 1-7: margin is -1 to -7
    # Get quote for favourite side
    quotes = quote.get("quotes") if quote else None
    price = median_price(quotes, favorite_side)
    if price is None:
        return None

    # Build candidate
    home_team = pregame.get("home_team")
    away_team = pregame.get("away_team")
    team = home_team if favorite_side == "home" else away_team

    state_id = _make_state_id(pregame.get("game_id"), observed_utc_str)

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
        "observed_utc": observed_utc_str,
        "trigger": {
            "elapsed_minutes": round(elapsed, 1),
            "margin": margin,
            "favorite_prob": pregame.get("favorite_prob"),
        }
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
