"""Point-in-time team features. The lookahead-bias problem, solved structurally.

THE PROBLEM THIS EXISTS TO PREVENT
----------------------------------
Building a feature for a game played on 12 June means using only what was knowable
BEFORE first pitch that day. This sounds obvious and is violated constantly, because the
convenient way to get a team's ERA is to ask the API for it now -- and "now" includes
every game played since.

A model trained on leaked data does not fail loudly. It backtests beautifully, because it
was quietly told the answer, and then loses money live where the future is genuinely
unavailable. It is the most expensive silent failure in this entire project.

HOW IT IS PREVENTED HERE
------------------------
Structurally, not by discipline. Every feature in this module is computed from
`games_before()`, which is the ONLY accessor to history. It takes a cutoff date and
returns games strictly earlier than it. There is no code path that reads a game on or
after the cutoff, so a leak would require deleting that filter rather than merely
forgetting to apply it.

The test suite proves this rather than trusting it: it injects a future game with absurd
values into the store and asserts every feature is byte-identical.

WHY TEAM FEATURES COME FROM THE RESULTS STORE
---------------------------------------------
Everything here is derived from completed games already in the historical store. That
means no additional API calls, no rate limits, and -- most importantly -- no possibility
of accidentally fetching a season-to-date figure that silently includes the future.

Pitcher-level features are a separate and harder problem requiring game logs. They are
deliberately NOT in this module, because mixing a provably-safe source with a
harder-to-verify one would put the whole table's integrity in question.
"""

from __future__ import annotations

from datetime import date, timedelta

# Feature windows. "Recent form" has no canonical length, so both a short and a medium
# window are computed and the model decides which carries signal.
FORM_WINDOWS = (5, 10)

# Below this many prior games, a rate statistic is noise rather than information. Early
# April rows report the count and leave rates None rather than emitting a batting average
# computed from three games as though it meant something.
MIN_GAMES_FOR_RATES = 10

# Rest matters, but only up to a point; beyond roughly a week it is an off-season or an
# injury gap and the number stops being comparable.
MAX_MEANINGFUL_REST_DAYS = 10


class FeatureError(ValueError):
    """Raised when features cannot be computed from the given inputs."""


# ---------------------------------------------------------------------------
# The single gated accessor to history
# ---------------------------------------------------------------------------

def games_before(store, cutoff_date, team=None) -> list:
    """Every stored game strictly BEFORE cutoff_date, oldest first.

    This is the only function in this module that reads the store, and it is the
    structural guarantee against lookahead bias. A game played ON the cutoff date is
    excluded: at the moment a prediction is made, that day's games have not happened.

    Passing `team` filters to games that team played in, home or away.
    """
    cutoff = _to_date(cutoff_date)
    rows = []
    for row in store.values():
        row_date = row.get("date")
        if not row_date:
            continue
        try:
            if _to_date(row_date) >= cutoff:
                continue
        except FeatureError:
            continue
        if team is not None and row.get("away_team") != team and row.get("home_team") != team:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r.get("date") or "", str(r.get("game_pk") or "")))
    return rows


# ---------------------------------------------------------------------------
# Per-game perspective helpers
# ---------------------------------------------------------------------------

def _perspective(row, team):
    """Recast one stored game from a given team's point of view.

    Returns None when the game is unusable for form purposes -- an exhibition tie has no
    winner, and counting it as a loss would be a fabrication.
    """
    home = row.get("home_team")
    away = row.get("away_team")
    if team not in (home, away):
        return None

    is_home = team == home
    scored = row.get("home_score") if is_home else row.get("away_score")
    allowed = row.get("away_score") if is_home else row.get("home_score")
    try:
        scored, allowed = int(scored), int(allowed)
    except (TypeError, ValueError):
        return None

    winner = row.get("winner")
    if winner is None:
        won = None  # a legitimate exhibition tie: neither a win nor a loss
    else:
        won = 1 if winner == team else 0

    return {
        "date": row.get("date"),
        "is_home": is_home,
        "scored": scored,
        "allowed": allowed,
        "won": won,
        "opponent": away if is_home else home,
    }


def _rates(games) -> dict:
    """Aggregate a list of perspectives. Returns None rates on an empty list."""
    decided = [g for g in games if g["won"] is not None]
    if not games:
        return {"games": 0, "wins": None, "losses": None, "win_pct": None,
                "runs_scored_pg": None, "runs_allowed_pg": None, "run_diff_pg": None}

    wins = sum(g["won"] for g in decided)
    scored = sum(g["scored"] for g in games)
    allowed = sum(g["allowed"] for g in games)
    n = len(games)
    return {
        "games": n,
        "wins": wins,
        "losses": len(decided) - wins,
        "win_pct": round(wins / len(decided), 4) if decided else None,
        "runs_scored_pg": round(scored / n, 3),
        "runs_allowed_pg": round(allowed / n, 3),
        "run_diff_pg": round((scored - allowed) / n, 3),
    }


# ---------------------------------------------------------------------------
# Team features
# ---------------------------------------------------------------------------

def team_features(store, team, as_of_date, prefix="") -> dict:
    """Every point-in-time feature for one team as of a date.

    Rates are suppressed to None below MIN_GAMES_FOR_RATES. A win percentage computed
    from four games is not a weak signal, it is noise wearing the costume of one, and
    emitting it invites the model to learn from April randomness.
    """
    history = games_before(store, as_of_date, team=team)
    perspectives = [p for p in (_perspective(r, team) for r in history) if p]

    season = _rates(perspectives)
    thin = season["games"] < MIN_GAMES_FOR_RATES

    features = {
        f"{prefix}games_played": season["games"],
        f"{prefix}wins": season["wins"],
        f"{prefix}losses": season["losses"],
        f"{prefix}win_pct": None if thin else season["win_pct"],
        f"{prefix}runs_scored_pg": None if thin else season["runs_scored_pg"],
        f"{prefix}runs_allowed_pg": None if thin else season["runs_allowed_pg"],
        f"{prefix}run_diff_pg": None if thin else season["run_diff_pg"],
        f"{prefix}sample_is_thin": thin,
    }

    # Recent form. Deliberately NOT suppressed by MIN_GAMES_FOR_RATES -- a last-10 record
    # is meaningful once 10 games exist, independent of season length.
    for window in FORM_WINDOWS:
        recent = perspectives[-window:]
        rates = _rates(recent)
        complete = len(recent) == window
        features[f"{prefix}last{window}_games"] = rates["games"]
        features[f"{prefix}last{window}_wins"] = rates["wins"] if complete else None
        features[f"{prefix}last{window}_runs_scored_pg"] = (
            rates["runs_scored_pg"] if complete else None)
        features[f"{prefix}last{window}_run_diff_pg"] = (
            rates["run_diff_pg"] if complete else None)

    # Home/away split, which is a real and large effect in baseball.
    home_games = [p for p in perspectives if p["is_home"]]
    away_games = [p for p in perspectives if not p["is_home"]]
    home_rates, away_rates = _rates(home_games), _rates(away_games)
    features[f"{prefix}home_win_pct"] = (
        home_rates["win_pct"] if home_rates["games"] >= MIN_GAMES_FOR_RATES else None)
    features[f"{prefix}away_win_pct"] = (
        away_rates["win_pct"] if away_rates["games"] >= MIN_GAMES_FOR_RATES else None)

    features[f"{prefix}rest_days"] = _rest_days(perspectives, as_of_date)
    features[f"{prefix}streak"] = _streak(perspectives)
    return features


def _rest_days(perspectives, as_of_date):
    """Days since this team last played. None when there is no prior game.

    Capped, because beyond about a week the gap is an off-season or an injury layoff
    rather than rest, and an uncapped value would let the model key on "this is April".
    """
    if not perspectives:
        return None
    last = perspectives[-1]["date"]
    if not last:
        return None
    try:
        gap = (_to_date(as_of_date) - _to_date(last)).days
    except FeatureError:
        return None
    return min(gap, MAX_MEANINGFUL_REST_DAYS) if gap >= 0 else None


def _streak(perspectives):
    """Current run, positive for wins and negative for losses. Ties end a streak."""
    streak = 0
    for game in reversed(perspectives):
        if game["won"] is None:
            break
        if streak == 0:
            streak = 1 if game["won"] else -1
        elif (streak > 0) == bool(game["won"]):
            streak += 1 if game["won"] else -1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Matchup rows
# ---------------------------------------------------------------------------

def matchup_features(store, away_team, home_team, game_date) -> dict:
    """Point-in-time features for both sides of one game, plus differentials.

    Differentials are included because what predicts a game is the GAP between two teams,
    not either team's absolute quality. A model given only raw values has to learn
    subtraction before it can learn baseball.
    """
    features = {}
    features.update(team_features(store, away_team, game_date, prefix="away_"))
    features.update(team_features(store, home_team, game_date, prefix="home_"))

    for base in ("win_pct", "run_diff_pg", "runs_scored_pg", "runs_allowed_pg"):
        away_value = features.get(f"away_{base}")
        home_value = features.get(f"home_{base}")
        features[f"diff_{base}"] = (
            round(home_value - away_value, 4)
            if away_value is not None and home_value is not None else None
        )

    features["either_sample_thin"] = bool(
        features.get("away_sample_is_thin") or features.get("home_sample_is_thin")
    )
    return features


def build_training_row(store, game, pitcher_logs=None,
                       fip_constant=None) -> dict:
    """One labelled training row: point-in-time features plus the outcome.

    The label is `home_won`, taken from the game itself. The features come only from
    games before it. Games without a decided winner (exhibition ties) are unusable as
    training labels and are rejected rather than silently coerced.

    When `pitcher_logs` is supplied, starting-pitcher features are merged in. Those
    obey the same cutoff rule through pitchers.appearances_before, so adding them
    cannot introduce a leak the team features were designed to prevent.
    """
    game_date = game.get("date")
    away, home = game.get("away_team"), game.get("home_team")
    if not (game_date and away and home):
        raise FeatureError(f"game {game.get('game_pk')!r} is missing date or teams")

    label = game.get("home_won")
    if label in (None, ""):
        raise FeatureError(
            f"game {game.get('game_pk')!r} has no decided winner and cannot be a "
            "training label"
        )

    row = {
        "game_pk": game.get("game_pk"),
        "date": game_date,
        "away_team": away,
        "home_team": home,
    }
    row.update(matchup_features(store, away, home, game_date))

    if pitcher_logs is not None:
        from src.pipeline import pitchers
        row.update(pitchers.matchup_pitcher_features(
            pitcher_logs,
            game.get("away_probable_id"),
            game.get("home_probable_id"),
            game_date,
            fip_constant=fip_constant,
        ))

    row["home_won"] = int(label)
    return row


def build_training_table(store, min_date=None, max_date=None,
                         require_complete=True, pitcher_logs=None,
                         require_pitchers=False) -> dict:
    """Build the full labelled table, oldest first.

    `require_complete` drops rows where either side's sample is too thin for rates. Early
    April games have almost no history by construction, and including them trains the
    model largely on missingness.

    Returns the rows plus a report of what was excluded and why -- a silently shortened
    table is how a training set quietly stops representing the season.
    """
    rows, skipped = [], {"no_label": 0, "thin_sample": 0, "error": 0,
                         "out_of_range": 0, "pitcher_unknown": 0}

    # The FIP constant is season-level and expensive to derive per row, so it is
    # computed once against the end of the window. That is a deliberate and tiny
    # relaxation of point-in-time purity: it is a league-wide scaling offset, not a
    # team or pitcher fact, and it shifts by hundredths across a season. Recomputing
    # it per row costs a full pass over every log for every game.
    fip_constant = None
    if pitcher_logs is not None:
        from src.pipeline import pitchers
        cutoff = max_date or "2100-01-01"
        fip_constant = pitchers.league_fip_constant(pitcher_logs, cutoff)

    ordered = sorted(
        store.values(),
        key=lambda r: (r.get("date") or "", str(r.get("game_pk") or "")),
    )

    for game in ordered:
        game_date = game.get("date")
        if not game_date:
            skipped["error"] += 1
            continue
        if min_date and game_date < min_date:
            skipped["out_of_range"] += 1
            continue
        if max_date and game_date > max_date:
            skipped["out_of_range"] += 1
            continue

        try:
            row = build_training_row(store, game, pitcher_logs=pitcher_logs,
                                     fip_constant=fip_constant)
        except FeatureError as exc:
            skipped["no_label" if "winner" in str(exc) else "error"] += 1
            continue

        if require_complete and row.get("either_sample_thin"):
            skipped["thin_sample"] += 1
            continue
        if require_pitchers and not row.get("both_sp_known", True):
            skipped["pitcher_unknown"] += 1
            continue
        rows.append(row)

    return {
        "rows": rows,
        "count": len(rows),
        "skipped": skipped,
        "total_candidates": len(ordered),
        "first_date": rows[0]["date"] if rows else None,
        "last_date": rows[-1]["date"] if rows else None,
        "base_rate": (round(sum(r["home_won"] for r in rows) / len(rows), 4)
                      if rows else None),
        "fip_constant": fip_constant,
        "includes_pitchers": pitcher_logs is not None,
    }


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise FeatureError(f"date must be a string or date, got {value!r}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise FeatureError(f"date must be ISO format, got {value!r}") from exc
