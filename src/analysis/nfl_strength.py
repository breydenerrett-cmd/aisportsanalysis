"""
NFL team-strength model from nflverse team-week stats.

WHY THIS EXISTS
---------------
This is a v0, point-in-time strength model that estimates team performance
using simple EPA (Expected Points Added) averaging. It makes NO fitted claims
and does NOT claim any predictive edge; it is an explicitly documented
assumption set. Any user-facing application of this model must note it as
experimental research.

The model calculates offensive EPA per play, averages by team and opponent,
and uses these to estimate expected point margins and win probabilities
under a normal distribution assumption. All parameters are documented
constants, not fitted, and the design is intentionally simple to separate
assumptions from optimization.
"""

import math
from typing import Optional, Dict, List, Any

# nflverse team-week column names; can be re-pointed in one place
EPA_COLUMNS = ("passing_epa", "rushing_epa")
PLAY_COLUMNS = ("attempts", "carries")

# Model constants (not fitted)
HOME_FIELD_POINTS = 1.5
PLAYS_PER_GAME = 63.0
MARGIN_SIGMA = 13.5  # NFL margin standard deviation
THIN_BELOW_GAMES = 3


def _offense_epa_per_play(row: Dict[str, Any]) -> Optional[float]:
    """
    Calculate offensive EPA per play for a single game observation.

    Sums all EPA columns and divides by total plays. Returns None if any
    required column is missing or total plays is zero.
    """
    # Sum EPA columns
    total_epa = 0.0
    for col in EPA_COLUMNS:
        if col not in row:
            return None
        total_epa += row[col]

    # Sum play columns
    total_plays = 0.0
    for col in PLAY_COLUMNS:
        if col not in row:
            return None
        total_plays += row[col]

    if total_plays == 0:
        return None

    return total_epa / total_plays


def team_ratings(
    rows: List[Dict[str, Any]],
    *,
    season: int,
    through_week: int
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate team strength ratings for a season through a specific week.

    Uses only rows with matching season and week < through_week (point-in-time).
    For each team, calculates:
    - off_epa: mean offensive EPA/play over its games
    - def_epa_allowed: mean of opponent's offensive EPA/play against this team
    - rating: off_epa - def_epa_allowed
    - games: number of games

    Teams with no prior rows are absent from the result.
    """
    # Filter to relevant rows
    relevant = [
        row for row in rows
        if row.get("season") == season and row.get("week", -1) < through_week
    ]

    # Build index: (week, team, opponent_team) -> row for quick lookup
    row_index = {}
    for row in relevant:
        key = (row.get("week"), row.get("team"), row.get("opponent_team"))
        row_index[key] = row

    # Collect offensive games by team
    team_offensive = {}  # team -> list of epa_per_play
    team_games_count = {}  # team -> count of games

    for row in relevant:
        team = row.get("team")
        if team is None:
            continue

        epa = _offense_epa_per_play(row)
        if epa is None:
            continue

        if team not in team_offensive:
            team_offensive[team] = []
            team_games_count[team] = 0

        team_offensive[team].append(epa)
        team_games_count[team] += 1

    # Calculate defensive EPA allowed (opponent's offensive EPA against this team)
    team_defensive = {}  # team -> list of opponent's epa_per_play

    for row in relevant:
        team = row.get("team")
        opponent = row.get("opponent_team")
        week = row.get("week")

        if team is None or opponent is None:
            continue

        # Find the opponent's row for this same game
        opp_key = (week, opponent, team)
        if opp_key in row_index:
            opp_row = row_index[opp_key]
            opp_epa = _offense_epa_per_play(opp_row)
            if opp_epa is not None:
                if team not in team_defensive:
                    team_defensive[team] = []
                team_defensive[team].append(opp_epa)

    # Build ratings dictionary
    ratings = {}
    for team in team_offensive:
        off_epas = team_offensive[team]
        def_epas = team_defensive.get(team, [])

        off_mean = sum(off_epas) / len(off_epas)
        def_mean = sum(def_epas) / len(def_epas) if def_epas else 0.0

        ratings[team] = {
            "off_epa": off_mean,
            "def_epa_allowed": def_mean,
            "rating": off_mean - def_mean,
            "games": len(off_epas)
        }

    return ratings


def expected_margin(
    home: str,
    away: str,
    ratings: Dict[str, Any],
    *,
    neutral_site: bool = False
) -> Optional[float]:
    """
    Calculate expected point margin for a matchup.

    margin = (rating_home - rating_away) * PLAYS_PER_GAME + home_field_points

    Returns None if either team is missing from ratings.
    """
    if home not in ratings or away not in ratings:
        return None

    home_rating = ratings[home]["rating"]
    away_rating = ratings[away]["rating"]

    margin = (home_rating - away_rating) * PLAYS_PER_GAME
    if not neutral_site:
        margin += HOME_FIELD_POINTS

    return margin


def win_probability(margin: float, *, sigma: float = MARGIN_SIGMA) -> float:
    """
    Calculate probability home team wins given expected margin.

    Uses normal CDF: Phi(margin / sigma) = 0.5 * (1 + erf(margin / (sigma * sqrt(2)))).
    """
    return 0.5 * (1.0 + math.erf(margin / (sigma * math.sqrt(2.0))))


def game_probability(
    home: str,
    away: str,
    ratings: Dict[str, Any],
    *,
    neutral_site: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Calculate full probabilities for a matchup.

    Returns dict with:
    - p_home: probability home team wins
    - p_away: probability away team wins
    - expected_margin: expected point margin (negative favors away)
    - games_home: number of prior games for home team
    - games_away: number of prior games for away team
    - thin: True if either team has < THIN_BELOW_GAMES games

    Returns None if expected_margin is None (missing team).
    """
    margin = expected_margin(home, away, ratings, neutral_site=neutral_site)
    if margin is None:
        return None

    p_home = win_probability(margin)
    p_away = 1.0 - p_home

    games_home = ratings[home]["games"]
    games_away = ratings[away]["games"]
    thin = games_home < THIN_BELOW_GAMES or games_away < THIN_BELOW_GAMES

    return {
        "p_home": p_home,
        "p_away": p_away,
        "expected_margin": margin,
        "games_home": games_home,
        "games_away": games_away,
        "thin": thin
    }


def model_side(prob: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Determine which side the model favors based on probabilities.

    Returns "home" if p_home > 0.5, "away" if < 0.5, None at exactly 0.5.
    Returns None if prob is None.
    """
    if prob is None:
        return None

    p_home = prob["p_home"]
    if p_home > 0.5:
        return "home"
    elif p_home < 0.5:
        return "away"
    else:
        return None
