"""Does the opposing lineup's strikeout tendency improve the pitcher-specific K forecast?

Pure functions for ONE bounded, pre-registered paper comparison
(`docs/PREREG_K_OPPONENT.md`). Nothing here reads a file, a clock or a network;
`scripts/k_opponent_compare.py` does the I/O and hands rows in.

THE QUESTION
------------
`docs/research/K_BASELINE_RESULT.md` found that a starter's own history beats the
league rate. This asks the next smallest question: does knowing WHO he faces add
to that? One candidate, one fixed constant, one fixed bound, no search.

    BASELINE   the K_BASELINE candidate, exactly as registered: Poisson with
               mean = shrunk K rate x shrunk expected batters faced.
               It is `src.research.k_baseline.build_comparison_rows` called on
               EVERY start, unchanged; this module never re-implements it.
    CANDIDATE  the same Poisson with the per-batter K rate multiplied by
               factor = shrunk opposing-team K rate / league K rate, where the
               opposing team's rate is its batting strikeouts per plate
               appearance over ITS games strictly before the date, same season,
               shrunk toward the league rate with a fixed prior weight
               (OPP_PRIOR_PA) and bounded to [FACTOR_MIN, FACTOR_MAX].

Both are scored on P(strikeouts > line) at 3.5, 4.5, 5.5 and 6.5 and on the
absolute error of expected strikeouts, on the SAME starts, one row per start.
A start whose opposing team cannot be identified from stored data is dropped
from BOTH arms (counted by cause). No price is involved anywhere.

SIGN CONVENTION, STATED ONCE
----------------------------
    d = loss(BASELINE) - loss(CANDIDATE)        per start, log loss in nats
    d_mae = |K - E_baseline| - |K - E_candidate|

POSITIVE means the opponent-adjusted candidate predicted better.

DATA, AND WHAT THE OPPOSING TEAM'S RATE IS
------------------------------------------
`pitcher_logs.jsonl` carries no team, opponent or game id. `bullpen_log.jsonl`
carries `game_pk`, `team`, `started`, strikeouts and batters faced for EVERY
pitcher of a game, starters and relievers, so a team's BATTING strikeouts and
plate appearances in a game are the strikeouts and batters faced recorded by the
OTHER team's pitchers in that game. A start joins to its game on
(person_id, date) with `started` true. A game enters the history only if it is a
regular-season game in `mlb_results.csv` (the caller passes that map), has exactly
two team codes and one date, and every row is a valid integer figure; a game
recorded under two dates (a duplicated box score) is excluded wholesale.

POINT-IN-TIME, BY CONSTRUCTION
------------------------------
Everything for a start on date D comes from games dated STRICTLY BEFORE D: the
opposing team's record, the league reference rate. The walk adds a date's games
only after every start of that date has been scored. Every date is refused
unless it is inside 2023-01-01..2024-12-31 (`SealedDataError`); 2025 is
tuning-only and 2026-01-01..2026-08-27 is sealed.

Pure. stdlib only.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional, Sequence

from src.research import k_baseline as kb

# Re-exported so the guard, the sign convention, the interval and the rule are
# literally the K_BASELINE ones; a test pins the identity.
SealedDataError = kb.SealedDataError
assert_allowed_date = kb.assert_allowed_date
assert_allowed_season = kb.assert_allowed_season
in_window = kb.in_window
ALLOWED_SEASONS = kb.ALLOWED_SEASONS
LINES = kb.LINES
DECISIVE_LINES = kb.DECISIVE_LINES
line_key = kb.line_key
decide = kb.decide
SUPPORTED, WORSE, NOT_SUPPORTED = kb.SUPPORTED, kb.WORSE, kb.NOT_SUPPORTED
BOOTSTRAP_RESAMPLES = kb.BOOTSTRAP_RESAMPLES
BOOTSTRAP_SEED = kb.BOOTSTRAP_SEED

MARKET = kb.MARKET

# The one fixed shrinkage constant and the one fixed bound. Written down in
# docs/PREREG_K_OPPONENT.md before any comparison was computed; changing either
# is a new registration.
OPP_PRIOR_PA = 1000.0     # plate appearances of league-rate evidence in the opponent rate
FACTOR_MIN = 0.85
FACTOR_MAX = 1.15
HISTORY_DESCRIPTIVE_PA = 1000   # descriptive subset only: opponent has this much history


class KOpponentError(ValueError):
    """The inputs cannot be compared honestly."""


# ---------------------------------------------------------------------------
# The factor
# ---------------------------------------------------------------------------

def opponent_factor(team_k: int, team_pa: int, league_rate: float,
                    prior_pa: float = OPP_PRIOR_PA,
                    lo: float = FACTOR_MIN, hi: float = FACTOR_MAX) -> dict:
    """The registered factor and whether the bound bound.

        rate_T = (K_T + prior * r_ref) / (PA_T + prior)
        factor = rate_T / r_ref, clamped to [lo, hi]

    With no evidence (PA_T == 0) the factor is exactly 1.
    """
    if league_rate is None or not math.isfinite(league_rate) or league_rate <= 0:
        raise KOpponentError(f"league reference rate {league_rate!r} is unusable")
    if team_k < 0 or team_pa < 0 or team_k > team_pa:
        raise KOpponentError(f"impossible opponent record K={team_k} PA={team_pa}")
    rate = (team_k + prior_pa * league_rate) / (team_pa + prior_pa)
    raw = rate / league_rate
    factor = min(max(raw, lo), hi)
    bound = "low" if raw < lo else ("high" if raw > hi else None)
    return {"factor": factor, "raw_factor": raw, "bounded": bound,
            "opp_rate": rate}


def opponent_candidate_prediction(baseline_rate: float, baseline_expected_bf: float,
                                  factor: float) -> dict:
    """The baseline's own rate and expected batters faced, times the factor.
    The ONLY difference from the baseline arm."""
    mean = baseline_rate * factor * baseline_expected_bf
    return {"expected": mean,
            "over": {line_key(L): kb.poisson_over(mean, L) for L in LINES}}


# ---------------------------------------------------------------------------
# Games, from the bullpen log
# ---------------------------------------------------------------------------

def _valid_figure(value) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def extract_games(rows: Iterable[Mapping], regular_games: Mapping) -> dict:
    """Group bullpen-log pitching rows into games.

    `regular_games` maps game_pk -> ISO date for the regular-season games of
    `mlb_results.csv` (the caller built it from in-window rows only). Rows
    outside the evidence window are dropped the moment they are seen: not kept,
    not counted. Marker rows with no `person_id`/`game_pk` are counted and
    skipped. Returns

        {"games":   {game_pk: {"date", "pitching": {team: [k, bf]},
                               "starters": {person_id: team},
                               "rows": {person_id: (k, bf)}}},
         "excluded_starts": {(person_id, date): reason},
         "excluded_games": {game_pk: reason},
         "counts": {...}}

    A game is EXCLUDED, wholesale, when its rows carry more than one date
    (`multi_date`), a date other than the results date (`date_mismatch`), other
    than two team codes (`not_two_teams`), a duplicated pitcher
    (`duplicate_pitcher_row`) or an invalid figure (`invalid_k_bf`). A start in
    an excluded game stays unusable and is counted by that reason.
    """
    counts = {"in_window_rows": 0, "marker_rows": 0, "rows_not_regular_game": 0,
              "games_seen": 0, "games_used": 0}
    staged: dict = {}
    for row in rows:
        date = row.get("date")
        if not in_window(date if isinstance(date, str) else None):
            continue
        counts["in_window_rows"] += 1
        if row.get("person_id") is None or row.get("game_pk") is None:
            counts["marker_rows"] += 1
            continue
        pk = int(row["game_pk"])
        if pk not in regular_games:
            counts["rows_not_regular_game"] += 1
            continue
        staged.setdefault(pk, []).append(row)
    games: dict = {}
    excluded_games: dict = {}
    excluded_starts: dict = {}
    counts["games_seen"] = len(staged)
    for pk in sorted(staged):
        group = staged[pk]
        dates = {str(r["date"])[:10] for r in group}
        reason = None
        teams = {r.get("team") for r in group}
        if len(dates) > 1:
            reason = "multi_date"
        elif next(iter(dates)) != str(regular_games[pk])[:10]:
            reason = "date_mismatch"
        elif len(teams) != 2 or None in teams or "" in teams:
            reason = "not_two_teams"
        else:
            seen = set()
            for r in group:
                key = int(r["person_id"])
                if key in seen:
                    reason = "duplicate_pitcher_row"
                    break
                seen.add(key)
            if reason is None and not all(
                    _valid_figure(r.get("strikeouts"))
                    and _valid_figure(r.get("batters_faced"))
                    and r["strikeouts"] <= r["batters_faced"] for r in group):
                reason = "invalid_k_bf"
        if reason is not None:
            excluded_games[pk] = reason
            for r in group:
                if r.get("started") is True:
                    excluded_starts[(int(r["person_id"]), str(r["date"])[:10])] = reason
            continue
        date = next(iter(dates))
        assert_allowed_date(date)
        pitching: dict = {}
        starters: dict = {}
        per_person: dict = {}
        for r in group:
            cell = pitching.setdefault(r["team"], [0, 0])
            cell[0] += r["strikeouts"]
            cell[1] += r["batters_faced"]
            per_person[int(r["person_id"])] = (r["strikeouts"], r["batters_faced"])
            if r.get("started") is True:
                starters[int(r["person_id"])] = r["team"]
        games[pk] = {"date": date, "pitching": pitching, "starters": starters,
                     "rows": per_person}
        counts["games_used"] += 1
    counts["games_excluded"] = len(excluded_games)
    for reason in ("multi_date", "date_mismatch", "not_two_teams",
                   "duplicate_pitcher_row", "invalid_k_bf"):
        counts[f"games_excluded_{reason}"] = sum(
            1 for v in excluded_games.values() if v == reason)
    return {"games": games, "excluded_starts": excluded_starts,
            "excluded_games": excluded_games, "counts": counts}


def attach_opponents(starts: Sequence[Mapping], extracted: Mapping) -> dict:
    """Give each start its opposing team, or a counted reason it has none.

    `starts` is `k_baseline.extract_starts(...)["starts"]`; `extracted` is
    `extract_games(...)`. Returns {"opponents": {(person_id, date): {"game_pk",
    "team", "opponent"}}, "causes": {(person_id, date): cause}, "counts": {...}}.
    """
    games = extracted["games"]
    index: dict = {}
    for pk, g in games.items():
        for pid, team in g["starters"].items():
            index.setdefault((pid, g["date"]), []).append((pk, team))
    opponents: dict = {}
    causes: dict = {}
    counts = {"starts": 0, "with_opponent": 0, "no_game_match": 0,
              "ambiguous_game": 0, "game_excluded_multi_date": 0,
              "game_excluded_other": 0, "k_bf_disagree": 0}
    for s in starts:
        date = assert_allowed_date(s["date"])
        key = (s["person_id"], date)
        counts["starts"] += 1
        matches = index.get(key, [])
        cause = None
        if len(matches) > 1:
            cause = "ambiguous_game"
        elif not matches:
            reason = extracted["excluded_starts"].get(key)
            cause = ("no_game_match" if reason is None else
                     "game_excluded_multi_date" if reason == "multi_date" else
                     "game_excluded_other")
        else:
            pk, team = matches[0]
            game = games[pk]
            if game["rows"].get(s["person_id"]) != (s["k"], s["bf"]):
                cause = "k_bf_disagree"
            else:
                others = [t for t in game["pitching"] if t != team]
                if len(others) != 1:
                    cause = "game_excluded_other"
                else:
                    opponents[key] = {"game_pk": pk, "team": team,
                                      "opponent": others[0]}
        if cause is not None:
            causes[key] = cause
            counts[cause] += 1
        else:
            counts["with_opponent"] += 1
    return {"opponents": opponents, "causes": causes, "counts": counts}


# ---------------------------------------------------------------------------
# Point-in-time opponent history
# ---------------------------------------------------------------------------

def batting_events(games: Mapping, season: int) -> list:
    """[(date, game_pk, team, k, pa)] for one season, date ascending. A team's
    BATTING strikeouts and plate appearances in a game are the strikeouts and
    batters faced recorded by the other team's pitchers."""
    out = []
    for pk, g in games.items():
        date = assert_allowed_date(g["date"])
        if int(date[:4]) != season:
            continue
        teams = sorted(g["pitching"])
        for team in teams:
            other = [t for t in teams if t != team]
            if len(other) != 1:
                continue
            k, bf = g["pitching"][other[0]]
            out.append((date, pk, team, k, bf))
    out.sort(key=lambda e: (e[0], e[1], e[2]))
    return out


def season_league_rate(games: Mapping, season: int) -> Optional[float]:
    """League strikeouts per plate appearance over ALL games of a season (every
    pitcher, both teams). Used only for the PRIOR season, which is wholly
    before any date of the season being scored."""
    k = bf = 0
    for g in games.values():
        date = assert_allowed_date(g["date"])
        if int(date[:4]) != season:
            continue
        for kk, b in g["pitching"].values():
            k += kk
            bf += b
    return k / bf if bf else None


class OpponentHistory:
    """Team batting records and the league record from games STRICTLY BEFORE the
    date last passed to `advance_to`. Monotone: dates may not go backwards."""

    def __init__(self, events: Sequence):
        self._events = list(events)
        self._i = 0
        self._cursor = None
        self.team: dict = {}        # team -> [k, pa, games]
        self.league_k = 0
        self.league_pa = 0

    def advance_to(self, date: str) -> None:
        date = assert_allowed_date(date)
        if self._cursor is not None and date < self._cursor:
            raise KOpponentError(f"history asked to go back from {self._cursor} to {date}")
        self._cursor = date
        while self._i < len(self._events) and self._events[self._i][0] < date:
            _d, _pk, team, k, pa = self._events[self._i]
            cell = self.team.setdefault(team, [0, 0, 0])
            cell[0] += k
            cell[1] += pa
            cell[2] += 1
            self.league_k += k
            self.league_pa += pa
            self._i += 1

    def team_record(self, team) -> tuple:
        k, pa, n = self.team.get(team, (0, 0, 0))
        return k, pa, n

    def league_rate(self) -> Optional[float]:
        return self.league_k / self.league_pa if self.league_pa else None


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

def build_opponent_rows(*, season, starts: Sequence[Mapping], games: Mapping,
                        opponents: Mapping, causes: Mapping,
                        min_league_starts: int = kb.MIN_LEAGUE_STARTS,
                        min_prior_starts: int = kb.MIN_PRIOR_STARTS,
                        prior_pa: float = OPP_PRIOR_PA,
                        limit: Optional[int] = None) -> dict:
    """Score every comparable start of one season under both arms.

    The BASELINE rows come from `k_baseline.build_comparison_rows(...)` called
    on EVERY start, so the baseline is the registered one, probability for
    probability, whatever this study can or cannot identify. A scored start
    with no identified opposing team is dropped from both arms and counted by
    cause. ONE ROW PER START; the two arms live in the one row.

    Returns {"rows", "baseline_rows", "counts"}.
    """
    season = assert_allowed_season(season)
    built = kb.build_comparison_rows(
        season=season, starts=starts, min_league_starts=min_league_starts,
        min_prior_starts=min_prior_starts)
    prior_season = season - 1
    prior_rate = (season_league_rate(games, prior_season)
                  if prior_season in ALLOWED_SEASONS else None)
    history = OpponentHistory(batting_events(games, season))
    counts = {"baseline_scored": built["counts"]["scored"],
              "scored": 0, "factor_exactly_one": 0, "bounded_low": 0,
              "bounded_high": 0, "no_reference_rate": 0,
              "excluded_no_opponent": 0}
    for cause in ("no_game_match", "ambiguous_game", "game_excluded_multi_date",
                  "game_excluded_other", "k_bf_disagree"):
        counts[f"excluded_{cause}"] = 0
    out = []
    for base in built["rows"]:                      # date ascending
        if limit is not None and counts["scored"] >= limit:
            break
        date = assert_allowed_date(base["date"])
        key = (base["person_id"], date)
        opp = opponents.get(key)
        if opp is None:
            counts["excluded_no_opponent"] += 1
            counts[f"excluded_{causes.get(key, 'no_game_match')}"] += 1
            continue
        history.advance_to(date)                    # games strictly before `date`
        r_ref = (history.league_rate() if base["pool"] == "same_season"
                 else prior_rate)
        if r_ref is None or r_ref <= 0:
            counts["no_reference_rate"] += 1
            continue
        k_t, pa_t, n_t = history.team_record(opp["opponent"])
        fac = opponent_factor(k_t, pa_t, r_ref, prior_pa=prior_pa)
        cand = opponent_candidate_prediction(base["k_rate"], base["expected_bf"],
                                             fac["factor"])
        k = base["k"]
        row = {"date": date, "person_id": base["person_id"],
               "opponent": opp["opponent"], "team": opp["team"],
               "game_pk": opp["game_pk"], "k": k, "bf": base["bf"],
               "prior_starts": base["prior_starts"], "pool": base["pool"],
               "short_start": base["short_start"],
               "opp_games": n_t, "opp_pa": pa_t, "opp_k": k_t, "r_ref": r_ref,
               "opp_rate": fac["opp_rate"], "factor": fac["factor"],
               "raw_factor": fac["raw_factor"], "bounded": fac["bounded"],
               "k_rate": base["k_rate"], "expected_bf": base["expected_bf"],
               "e_base": base["e_cand"], "e_cand": cand["expected"],
               "d_mae": kb.paired_abs_error(base["e_cand"], cand["expected"], k)}
        for L in LINES:
            lk = line_key(L)
            y = base[f"y_{lk}"]
            row[f"y_{lk}"] = y
            # BASELINE here is the K_BASELINE CANDIDATE arm.
            row[f"p_base_{lk}"] = base[f"p_cand_{lk}"]
            row[f"p_cand_{lk}"] = cand["over"][lk]
            row[f"d_{lk}"] = kb.paired_difference(
                base[f"p_cand_{lk}"], cand["over"][lk], y)
        out.append(row)
        counts["scored"] += 1
        if fac["factor"] == 1.0:
            counts["factor_exactly_one"] += 1
        if fac["bounded"] == "low":
            counts["bounded_low"] += 1
        elif fac["bounded"] == "high":
            counts["bounded_high"] += 1
    return {"rows": out, "baseline_rows": built["rows"], "counts": counts}


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _quantile(sorted_values: Sequence[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def line_summary(rows: Sequence[Mapping], line: float) -> dict:
    lk = line_key(line)
    n = len(rows)
    out = {"line": float(line), "n": n}
    if not n:
        return out
    y, pb, pc = f"y_{lk}", f"p_base_{lk}", f"p_cand_{lk}"
    out["base_rate"] = _mean([r[y] for r in rows])
    out["mean_p_baseline"] = _mean([r[pb] for r in rows])
    out["mean_p_candidate"] = _mean([r[pc] for r in rows])
    out["log_loss_baseline"] = _mean([kb.log_loss_one(r[pb], r[y]) for r in rows])
    out["log_loss_candidate"] = _mean([kb.log_loss_one(r[pc], r[y]) for r in rows])
    out["brier_baseline"] = _mean([kb.brier_one(r[pb], r[y]) for r in rows])
    out["brier_candidate"] = _mean([kb.brier_one(r[pc], r[y]) for r in rows])
    paired = kb.clustered_mean_interval(kb.per_date_aggregates(rows, f"d_{lk}"))
    paired["minimum_detectable_effect_80pct"] = (
        None if paired["se"] is None else 2.8 * paired["se"])
    out["paired"] = paired
    return out


def mae_summary(rows: Sequence[Mapping]) -> dict:
    n = len(rows)
    out = {"n": n}
    if not n:
        return out
    out["mean_k"] = _mean([r["k"] for r in rows])
    out["mean_expected_baseline"] = _mean([r["e_base"] for r in rows])
    out["mean_expected_candidate"] = _mean([r["e_cand"] for r in rows])
    out["mae_baseline"] = _mean([abs(r["k"] - r["e_base"]) for r in rows])
    out["mae_candidate"] = _mean([abs(r["k"] - r["e_cand"]) for r in rows])
    paired = kb.clustered_mean_interval(kb.per_date_aggregates(rows, "d_mae"))
    paired["minimum_detectable_effect_80pct"] = (
        None if paired["se"] is None else 2.8 * paired["se"])
    out["paired"] = paired
    return out


def factor_summary(rows: Sequence[Mapping]) -> dict:
    if not rows:
        return {"n": 0}
    f = sorted(r["factor"] for r in rows)
    return {"n": len(f), "min": f[0], "q25": _quantile(f, 0.25),
            "median": _quantile(f, 0.5), "q75": _quantile(f, 0.75),
            "max": f[-1], "mean": _mean(f),
            "share_exactly_one": sum(1 for v in f if v == 1.0) / len(f),
            "share_bounded_low": sum(1 for r in rows if r["bounded"] == "low") / len(rows),
            "share_bounded_high": sum(1 for r in rows if r["bounded"] == "high") / len(rows)}


def _block(rows: Sequence[Mapping]) -> dict:
    return {"lines": {line_key(L): line_summary(rows, L) for L in LINES},
            "expected_strikeouts_mae": mae_summary(rows)}


def summarise_season(rows: Sequence[Mapping]) -> dict:
    """Everything the artifact reports for one season, from scored rows."""
    history = [r for r in rows if r["opp_pa"] >= HISTORY_DESCRIPTIVE_PA]
    return {
        "all_scored": _block(rows),
        "opponent_history_at_least_1000_pa_descriptive": _block(history),
        "factor": factor_summary(rows),
        "per_date": {line_key(L): [[d, t, n] for d, t, n in
                                   kb.per_date_aggregates(rows, f"d_{line_key(L)}")]
                     for L in LINES},
        "per_date_mae": [[d, t, n] for d, t, n in
                         kb.per_date_aggregates(rows, "d_mae")],
    }
