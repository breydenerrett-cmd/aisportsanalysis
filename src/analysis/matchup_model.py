"""A matchup-aware per-game candidate, built ON TOP of the model the card
actually uses (`src.analysis.strength.model_line`), never a replacement for
it.

WHAT THIS FILE IS, AND WHAT IT IS NOT
--------------------------------------
`src.analysis.strength.model_line` is unmodified and untouched by this file.
Every number `strength.py` produces is still produced by `strength.py`'s own
arithmetic -- the FIP-to-runs conversion, the odds-ratio offence/defence
blend, the negative-binomial dispersion, all of it. This module does not
reimplement any of that and does not add a second, competing formula.

What it DOES do: build two different FEATURE DICTS for the same real game
and hand each one to the identical, unmodified `strength.model_line`. The
"frozen aggregate reference" feature dict carries only season-to-date team
rates -- exactly `src.pipeline.features.matchup_features`'s output, with no
starter, no bullpen, no park. The "richer" feature dict starts from that
same aggregate dict and adds real, point-in-time data for three conditions
`strength.run_means` already HAS a mechanism for but that the frozen
reference never supplies: which pitcher is starting, the bullpen's own
season relief rate (as opposed to its rotation-contaminated stand-in), and
the park the game is actually played in.

None of the three coefficients below are invented here. The FIP-to-runs
scale, the innings-share blend, and the park multiplier all already exist
inside `strength.py` and `src.pipeline.parkfactors`/`src.pipeline.pitchers`/
`src.pipeline.bullpen` -- published or measured elsewhere, with their own
docstrings and their own tests. This module's only job is SOURCING real
data for parameters that already exist, never adding a new one.

FACTOR DISPOSITIONS (see `FACTOR_DISPOSITIONS` below for the machine-
readable table)
------------------------------------------------------------------------
  starting_pitcher    MODEL-USED   -- real point-in-time FIP via
                                       src.pipeline.pitchers, blended into
                                       run prevention by strength.py's own
                                       innings-share mechanism.
  bullpen_quality      MODEL-USED   -- real point-in-time SEASON relief rate
                                       (src.pipeline.bullpen.relief_rate),
                                       distinct from recent-availability
                                       below, fed into strength.py's own
                                       bullpen_rate parameter.
  park_factor          MODEL-USED   -- real point-in-time home/road split
                                       factor (src.pipeline.parkfactors),
                                       fed into strength.py's own
                                       park_factor parameter (accepted by
                                       that module since before this file
                                       existed, but never wired to real data
                                       by the live card -- see
                                       docs/THE_CARD.md's omission list).
  bullpen_recent_availability   CONTEXT ONLY -- src.pipeline.bullpen.
                                       team_workload's per-reliever
                                       AVAILABLE / QUESTIONABLE /
                                       LIKELY_UNAVAILABLE tags for the 7
                                       days before the game. Genuinely
                                       distinct from bullpen_quality above
                                       (that is a SEASON rate; this is
                                       TONIGHT's usage). No coefficient
                                       anywhere in this project converts an
                                       availability tag into a run or
                                       win-probability adjustment, and none
                                       is invented here -- reported for a
                                       reader's judgment, never multiplied
                                       into a probability.
  rest_travel           CONTEXT ONLY -- src.pipeline.travel.travel_load's
                                       real point-in-time miles flown, time
                                       zones crossed and games-in-7-days
                                       count. That module's own docstring
                                       states the reason this stays context:
                                       "That this costs it runs tonight is a
                                       HYPOTHESIS, and one this module does
                                       not make." No fitted or assumed
                                       coefficient exists anywhere in this
                                       project translating travel load into
                                       runs, so none is applied here.
  lineup_composition     UNAVAILABLE  -- no point-in-time lineup-quality
                                       pipeline exists in this repo.
                                       `src.pipeline.lineups` /
                                       `lineup_store.py` capture WHO is in a
                                       lineup, not a validated strength
                                       number for that lineup relative to a
                                       team's season aggregate, and building
                                       one would mean inventing exactly the
                                       kind of unearned coefficient this
                                       project's evidence rules forbid.
  documented_injuries     UNAVAILABLE  -- no injury feed is ingested by any
                                       pipeline module in this repo.

CONFIRMED VS PROJECTED
-----------------------
`richer_features` takes `away_probable_id` / `home_probable_id` as
arguments rather than looking them up, and the caller states, for every
call, whether that id is a CONFIRMED probable (a game already on the books,
or a real historical start) or a PROJECTED one (a future round whose
starters are not yet announced -- see `scripts/postseason_demo.py`, which
never passes a projected id and instead leaves starting_pitcher UNAVAILABLE
for any game beyond the ones already scheduled). This module does not
guess a pitcher; a caller with no confirmed id passes `None`, and
`pitchers.pitcher_features` correctly reports `sp_known: False` for it, the
same as strength.py already does for a slate entry with no posted probable.

MONTE CARLO ERROR IS A SEPARATE AXIS
-------------------------------------
Nothing in this module runs a simulation. Any Monte Carlo cross-check on
top of the probabilities this module produces (e.g. `postseason.
simulate_series`) reports SAMPLING error only, entirely separate from and
never combined with the model/scenario uncertainty a reader should attach
to the feature dict itself (thin samples, missing starters, an approximate
neutral-site estimate -- all flagged explicitly in this module's output).

NO PREDICTIVE CLAIM. A richer feature dict can move `strength.model_line`'s
output number; whether that move is actually CLOSER to the true probability
is an empirical question this file does not answer and does not claim to
answer. See `scripts/postseason_demo.py`'s bounded comparison section for
what was and was not checked.

Pure. stdlib only. No I/O beyond what the caller-supplied `store` /
`pitcher_logs` / `bullpen_log` already carry.
"""

from __future__ import annotations

from datetime import date as _date_cls, timedelta as _timedelta_cls
from typing import Mapping, Optional, Sequence

from src.analysis import postseason
from src.analysis import strength
from src.pipeline import bullpen as bullpen_mod
from src.pipeline import features as features_mod
from src.pipeline import parkfactors as parkfactors_mod
from src.pipeline import pitchers as pitchers_mod
from src.pipeline import travel as travel_mod


class MatchupModelError(ValueError):
    """Raised when a matchup cannot be priced at all -- e.g. neither side of
    a proposed neutral-site estimate could be built. Loud on purpose, for
    the same reason `strength.StrengthError` and `postseason.
    PostseasonError` are: a silent 50/50 here would look like a considered
    call instead of an absence of one."""


# ---------------------------------------------------------------------------
# The disposition table. Every factor named in the Lane C task gets exactly
# one entry, and every entry appears verbatim in this module's own output
# (see `compare_game`'s "factor_dispositions" key) so a reader never has to
# trust a docstring to know what changed a number.
# ---------------------------------------------------------------------------

MODEL_USED = "MODEL-USED"
SCENARIO_INPUT = "SCENARIO INPUT"
CONTEXT_ONLY = "CONTEXT ONLY"
UNAVAILABLE = "UNAVAILABLE"

FACTOR_DISPOSITIONS = {
    "starting_pitcher": MODEL_USED,
    "bullpen_quality": MODEL_USED,
    "park_factor": MODEL_USED,
    "bullpen_recent_availability": CONTEXT_ONLY,
    "rest_travel": CONTEXT_ONLY,
    "lineup_composition": UNAVAILABLE,
    "documented_injuries": UNAVAILABLE,
}

FACTOR_NOTES = {
    "starting_pitcher": (
        "Real point-in-time FIP (src.pipeline.pitchers), blended by "
        "strength.py's own innings-share mechanism. Confirmed for a game "
        "already played or already on the board; never guessed for a "
        "future round with no posted probable."),
    "bullpen_quality": (
        "Real point-in-time SEASON relief rate, computed by this project's "
        "bullpen pipeline and fed into strength.py's own bullpen-rate "
        "input. Distinct from the separate recent-availability factor "
        "below."),
    "park_factor": (
        "Real point-in-time home/road split factor, computed by this "
        "project's park-factors pipeline and fed into strength.py's own "
        "park-factor input."),
    "bullpen_recent_availability": (
        "This project's bullpen pipeline reports each reliever's "
        "availability tag for the 7 days before the game. Reported, never "
        "applied: no coefficient in this project converts a tag into a "
        "probability adjustment."),
    "rest_travel": (
        "This project's travel pipeline reports real miles flown, time "
        "zones crossed and games played in the last 7 days. That module's "
        "own docstring calls the run cost a hypothesis it does not make; "
        "this file does not make it either."),
    "lineup_composition": (
        "No point-in-time lineup-quality pipeline exists in this repo -- "
        "lineups.py captures WHO is in a lineup, not a validated strength "
        "number for it."),
    "documented_injuries": "No injury feed is ingested by any pipeline module in this repo.",
}


# ---------------------------------------------------------------------------
# League context
# ---------------------------------------------------------------------------

def league_rpg_from_store(store: Mapping, cutoff_date: str, *,
                          same_season_only: bool = True) -> Optional[float]:
    """Average runs per team per game, strictly before `cutoff_date`.

    `strength.league_runs_per_game` reads already-built FEATURE rows (the
    `away_runs_scored_pg` / `home_runs_scored_pg` keys `features.
    matchup_features` emits) -- exactly what the live card and
    `scripts/backtest_card.py` already have lying around from building the
    slate/training table. This module has no such table lying around for an
    arbitrary historical or hypothetical matchup, so this function measures
    the identical quantity directly off the raw results store instead: it
    is the same "runs scored per team per game" definition, just sourced
    from `away_score`/`home_score` rather than from a pre-aggregated row.
    Point-in-time by the same rule as everything else here -- `date <
    cutoff_date`, never `<=`.
    """
    cutoff = str(cutoff_date)
    season = cutoff[:4]
    total_runs = 0
    total_team_games = 0
    for row in (store or {}).values():
        date = str(row.get("date") or "")
        if not date or date >= cutoff:
            continue
        if same_season_only and date[:4] != season:
            continue
        try:
            away_score = int(row.get("away_score"))
            home_score = int(row.get("home_score"))
        except (TypeError, ValueError):
            continue
        total_runs += away_score + home_score
        total_team_games += 2
    if total_team_games == 0:
        return None
    return total_runs / total_team_games


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------

def aggregate_reference_features(store: Mapping, away_team: str, home_team: str,
                                 game_date: str) -> dict:
    """The FROZEN AGGREGATE REFERENCE feature dict: season-to-date team rates
    only, exactly `src.pipeline.features.matchup_features`'s output. This is
    what `strength.model_line` sees when a caller supplies no starter, no
    bullpen and no park -- i.e. its documented fallback behaviour, unchanged.
    """
    return features_mod.matchup_features(store, away_team, home_team, game_date)


def richer_features(store: Mapping, pitcher_logs: Mapping, bullpen_log,
                    away_team: str, home_team: str,
                    away_probable_id: Optional[int], home_probable_id: Optional[int],
                    game_date: str, *, same_season_only: bool = True) -> dict:
    """The aggregate reference PLUS three real, point-in-time conditions:
    starting pitcher, season bullpen quality, and park. Every mechanism this
    calls into already exists; nothing here is a new coefficient.

    `away_probable_id` / `home_probable_id` may be `None` -- a genuinely
    unknown starter is passed through as `None` and
    `pitchers.pitcher_features` reports `sp_known: False` for it exactly as
    it would for a live slate entry with no posted probable. This function
    never invents a probable.
    """
    feats = dict(aggregate_reference_features(store, away_team, home_team, game_date))

    # `pitcher_logs=None` means "no starter data source at all" (e.g. a
    # future round with no probables announced yet) -- treated the same as
    # an empty log, which correctly reports sp_known: False for both sides
    # rather than raising. This is UNAVAILABLE starting_pitcher, not a
    # guess: see matchup_model's factor-disposition docstring.
    feats.update(pitchers_mod.matchup_pitcher_features(
        pitcher_logs if pitcher_logs is not None else {},
        away_probable_id, home_probable_id, game_date))

    away_rel = bullpen_mod.relief_rate(bullpen_log, away_team, game_date,
                                       same_season_only=same_season_only)
    home_rel = bullpen_mod.relief_rate(bullpen_log, home_team, game_date,
                                       same_season_only=same_season_only)
    feats["away_bullpen_rate"] = away_rel.get("rate")
    feats["home_bullpen_rate"] = home_rel.get("rate")
    feats["away_bullpen_detail"] = away_rel
    feats["home_bullpen_detail"] = home_rel

    pf = parkfactors_mod.park_factors(store, game_date, same_season_only=same_season_only)
    feats["park_factor"] = parkfactors_mod.factor_for(pf, home_team)
    feats["park_factor_detail"] = pf.get(home_team)

    return feats


def bullpen_availability_context(bullpen_log, team: str, game_date: str) -> dict:
    """CONTEXT ONLY -- see `FACTOR_NOTES['bullpen_recent_availability']`.
    Returned alongside a comparison, never folded into either feature dict."""
    return bullpen_mod.team_workload(bullpen_log, team, game_date)


def rest_travel_context(store: Mapping, team: str, game_date: str, tonight_venue: str) -> dict:
    """CONTEXT ONLY -- see `FACTOR_NOTES['rest_travel']`. Returned alongside
    a comparison, never folded into either feature dict."""
    return travel_mod.travel_load(store, team, game_date, tonight_venue)


# ---------------------------------------------------------------------------
# Running the (unmodified) baseline model
# ---------------------------------------------------------------------------

def model_line_or_none(features: Mapping, *, league_rpg: float, run_line: float = 1.5,
                       totals=None, dispersion: Optional[float] = None):
    """`(line, error)` -- exactly one is None. Never raises: a caller
    comparing many games wants to know WHICH ones could not be priced, not
    have the whole comparison die on the first thin sample."""
    try:
        return strength.model_line(features, league_rpg=league_rpg, run_line=run_line,
                                   totals=totals, dispersion=dispersion), None
    except strength.StrengthError as exc:
        return None, str(exc)


def compare_game(store: Mapping, pitcher_logs: Mapping, bullpen_log,
                 away_team: str, home_team: str,
                 away_probable_id: Optional[int], home_probable_id: Optional[int],
                 game_date: str, *, league_rpg: float, run_line: float = 1.5,
                 totals=None, dispersion: Optional[float] = None,
                 same_season_only: bool = True) -> dict:
    """The bounded baseline-vs-richer comparison for ONE game: both feature
    dicts, both run through the IDENTICAL unmodified `strength.model_line`,
    so any numeric difference between them comes only from which real data
    each was given -- never from a different formula.
    """
    baseline_feats = aggregate_reference_features(store, away_team, home_team, game_date)
    richer_feats = richer_features(store, pitcher_logs, bullpen_log, away_team, home_team,
                                   away_probable_id, home_probable_id, game_date,
                                   same_season_only=same_season_only)

    baseline_line, baseline_err = model_line_or_none(
        baseline_feats, league_rpg=league_rpg, run_line=run_line, totals=totals,
        dispersion=dispersion)
    richer_line, richer_err = model_line_or_none(
        richer_feats, league_rpg=league_rpg, run_line=run_line, totals=totals,
        dispersion=dispersion)

    return {
        "away_team": away_team,
        "home_team": home_team,
        "game_date": game_date,
        "baseline": {
            "p_home": baseline_line["p_home"] if baseline_line else None,
            "error": baseline_err,
            "line": baseline_line,
        },
        "richer": {
            "p_home": richer_line["p_home"] if richer_line else None,
            "error": richer_err,
            "line": richer_line,
            "starter_known": bool(richer_feats.get("both_sp_known")),
            "bullpen_known": bool(richer_line["bullpen_known"]) if richer_line else None,
            "park_factor": richer_feats.get("park_factor"),
            "park_thin": bool((richer_feats.get("park_factor_detail") or {}).get("thin", True)),
        },
        "p_home_delta": (
            round(richer_line["p_home"] - baseline_line["p_home"], 4)
            if baseline_line and richer_line else None
        ),
        "factor_dispositions": dict(FACTOR_DISPOSITIONS),
    }


# ---------------------------------------------------------------------------
# Neutral-site win probability for the postseason bracket engine
# ---------------------------------------------------------------------------

def neutral_win_prob(store: Mapping, pitcher_logs: Optional[Mapping], bullpen_log,
                     team_a: str, team_b: str, game_date: str, *, league_rpg: float,
                     use_richer: bool, dispersion: Optional[float] = None,
                     same_season_only: bool = True,
                     probable_by_team: Optional[Mapping] = None) -> float:
    """`team_a`'s approximate NEUTRAL-SITE win probability, for
    `postseason.bracket_probabilities`'s `win_prob_fn` contract.

    STATED APPROXIMATION. `strength.py` adds home field as a fixed RUN
    CREDIT inside a Poisson mean, which is a nonlinear transform -- there is
    no way to subtract it back out exactly without editing that frozen
    module, which this task forbids. What this function does instead:
    price the matchup twice, once with each team at home, and average team
    A's win probability across the two. That symmetrizes out most, not all,
    of the home-field and park effect (park differs by which stadium is
    used in each half of the average too), and is reported as an
    approximation rather than an exact neutral estimate. Named here rather
    than left implicit, the same way `postseason.py`'s own bracket engine
    names its round-independence simplification.

    Raises `MatchupModelError` if EITHER half of the average cannot be
    priced (e.g. a team with no games in a filtered/point-in-time store).
    """
    probable_by_team = probable_by_team or {}

    def _feats(away, home):
        if use_richer:
            return richer_features(
                store, pitcher_logs, bullpen_log, away, home,
                probable_by_team.get(away), probable_by_team.get(home),
                game_date, same_season_only=same_season_only)
        return aggregate_reference_features(store, away, home, game_date)

    feats_a_home = _feats(team_b, team_a)
    feats_b_home = _feats(team_a, team_b)

    line_a_home, err_a = model_line_or_none(feats_a_home, league_rpg=league_rpg,
                                            dispersion=dispersion)
    line_b_home, err_b = model_line_or_none(feats_b_home, league_rpg=league_rpg,
                                            dispersion=dispersion)
    if line_a_home is None or line_b_home is None:
        raise MatchupModelError(
            f"cannot price {team_a!r} vs {team_b!r} as of {game_date!r}: "
            f"{err_a or ''} {err_b or ''}".strip())

    p_a_as_home = line_a_home["p_home"]
    p_a_as_away = 1.0 - line_b_home["p_home"]
    return (p_a_as_home + p_a_as_away) / 2.0


# ---------------------------------------------------------------------------
# Per-factor attribution (owner requirement, 2026-09-25 review): "respond
# numerically to at least two real matchup conditions, with the input that
# caused each delta explained." A single combined p_home cannot show which
# factor did what; this isolates each MODEL-USED factor on its own, one at
# a time, against the SAME frozen aggregate reference.
# ---------------------------------------------------------------------------

def attribution_breakdown(store: Mapping, pitcher_logs: Mapping, bullpen_log,
                          away_team: str, home_team: str,
                          away_probable_id: Optional[int], home_probable_id: Optional[int],
                          game_date: str, *, league_rpg: float, run_line: float = 1.5,
                          totals=None, dispersion: Optional[float] = None,
                          same_season_only: bool = True) -> dict:
    """`p_home` for FIVE feature dicts on the identical game -- baseline,
    baseline+starter-only, baseline+bullpen-only, baseline+park-only, and
    all three together -- plus the delta each isolated factor produced from
    baseline, plus every raw input value behind those deltas (both
    starters' ids and FIP, both bullpen rates, the park factor). Every
    variant runs through the identical unmodified `strength.model_line`;
    the only thing that ever changes between variants is which real data
    was added to the SAME baseline feature dict.
    """
    baseline_feats = aggregate_reference_features(store, away_team, home_team, game_date)

    starter_feats = dict(baseline_feats)
    starter_feats.update(pitchers_mod.matchup_pitcher_features(
        pitcher_logs if pitcher_logs is not None else {},
        away_probable_id, home_probable_id, game_date))

    away_rel = bullpen_mod.relief_rate(bullpen_log, away_team, game_date,
                                       same_season_only=same_season_only)
    home_rel = bullpen_mod.relief_rate(bullpen_log, home_team, game_date,
                                       same_season_only=same_season_only)
    bullpen_feats = dict(baseline_feats)
    bullpen_feats["away_bullpen_rate"] = away_rel.get("rate")
    bullpen_feats["home_bullpen_rate"] = home_rel.get("rate")

    pf = parkfactors_mod.park_factors(store, game_date, same_season_only=same_season_only)
    park_factor_value = parkfactors_mod.factor_for(pf, home_team)
    park_feats = dict(baseline_feats)
    park_feats["park_factor"] = park_factor_value

    all_three_feats = richer_features(
        store, pitcher_logs, bullpen_log, away_team, home_team,
        away_probable_id, home_probable_id, game_date, same_season_only=same_season_only)

    variants = {
        "baseline": baseline_feats,
        "plus_starter": starter_feats,
        "plus_bullpen": bullpen_feats,
        "plus_park": park_feats,
        "all_three": all_three_feats,
    }

    p_home_by_variant, error_by_variant = {}, {}
    for name, feats in variants.items():
        line, err = model_line_or_none(feats, league_rpg=league_rpg, run_line=run_line,
                                       totals=totals, dispersion=dispersion)
        p_home_by_variant[name] = line["p_home"] if line else None
        error_by_variant[name] = err

    baseline_p = p_home_by_variant["baseline"]
    delta_from_baseline = {
        name: (round(p_home_by_variant[name] - baseline_p, 4)
              if p_home_by_variant[name] is not None and baseline_p is not None else None)
        for name in ("plus_starter", "plus_bullpen", "plus_park", "all_three")
    }

    return {
        "away_team": away_team, "home_team": home_team, "game_date": game_date,
        "p_home_by_variant": {k: (round(v, 4) if v is not None else None)
                              for k, v in p_home_by_variant.items()},
        "error_by_variant": error_by_variant,
        "delta_from_baseline": delta_from_baseline,
        "inputs": {
            "away_sp_id": away_probable_id,
            "home_sp_id": home_probable_id,
            "away_sp_known": starter_feats.get("away_sp_known"),
            "home_sp_known": starter_feats.get("home_sp_known"),
            "away_sp_fip": starter_feats.get("away_sp_fip"),
            "home_sp_fip": starter_feats.get("home_sp_fip"),
            "away_bullpen_rate": away_rel.get("rate"),
            "home_bullpen_rate": home_rel.get("rate"),
            "away_bullpen_innings": away_rel.get("innings"),
            "home_bullpen_innings": home_rel.get("innings"),
            "away_bullpen_thin": away_rel.get("thin"),
            "home_bullpen_thin": home_rel.get("thin"),
            "park_factor": park_factor_value,
            "park_thin": (pf.get(home_team) or {}).get("thin"),
        },
        "factor_dispositions": dict(FACTOR_DISPOSITIONS),
    }


# ---------------------------------------------------------------------------
# Rotation projection -- for a pre-series/mid-series forecast that never
# reads a pitcher's future appearance (owner requirement, first review: "A
# pre-series forecast may use only the announced game-1 starters plus a
# projected rotation... never use a pitcher's future appearance.").
#
# `build_rotation_pool` + `project_team_rotation` together replace an
# earlier `project_rotation` (a plain fixed-list round-robin cycle) that a
# SECOND review found wrong: it ordered candidates most-recent-start-FIRST
# and cycled through them in that order, which projects whoever JUST
# started to start again almost immediately -- the opposite of how a
# rotation rests a pitcher -- and its recency list mixed `int` and `str`
# pitcher ids (store rows are strings, hand-written ids are ints), which
# silently broke "is this pitcher already used" comparisons. See these two
# functions' own docstrings for the corrected rule.
# ---------------------------------------------------------------------------

def _to_int_id(value) -> Optional[int]:
    """A pitcher id, normalized to `int` -- never a bare `.get()`. The
    results store round-trips through CSV, so a probable-pitcher id read
    from it is a STRING ("543037"), while an id a caller writes by hand
    (e.g. a games list literal in a demo script) is typically an `int`.
    Comparing the two for equality or set-membership without normalizing
    first silently fails (`"543037" != 543037`), which is exactly the bug
    identified in the 2026-09-25 second review: a just-used starter's
    string id was not recognized as "already used" against his own int id
    recorded elsewhere, so he could be re-projected the very next game.
    Every function in this module that reads a probable id off a store row
    goes through this one converter."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def recent_starters(store: Mapping, team: str, cutoff_date: str, *,
                    limit: Optional[int] = None) -> list:
    """Distinct probable-pitcher ids (normalized to `int`) who started for
    `team`, most-recent start first, from games STRICTLY BEFORE
    `cutoff_date` -- regular season and any earlier postseason round both
    count equally, since both are real, already-known information as of
    `cutoff_date`. A pitcher who started more than once keeps only his most
    recent appearance's position. Never reads a row on or after
    `cutoff_date`, so this can never see who actually started a game the
    caller is trying to project.
    """
    cutoff = str(cutoff_date)
    rows = sorted(
        (r for r in (store or {}).values()
         if str(r.get("date") or "") < cutoff and team in (r.get("away_team"), r.get("home_team"))),
        key=lambda r: r.get("date") or "", reverse=True)
    seen_ids, ordered = set(), []
    for row in rows:
        raw = row.get("home_probable_id") if row.get("home_team") == team else row.get("away_probable_id")
        pid = _to_int_id(raw)
        if pid is None or pid in seen_ids:
            continue
        seen_ids.add(pid)
        ordered.append(pid)
        if limit and len(ordered) >= limit:
            break
    return ordered


# How far back a start still counts toward "this pitcher is presently in the
# active rotation" (`build_rotation_pool`'s `window_days`). 30 days is
# roughly 5-6 turns of a normal 5-day rotation -- long enough that a
# healthy current starter always clears it, short enough that a pitcher
# who has not started in over a month (hurt, demoted, or left off a
# postseason roster) does not. Fixed and documented here, not fitted: it
# is a rotation-membership heuristic, not a model coefficient, and the
# 2026-09-25 review's own real-data check (a Yankees starter with 29
# 2024 starts but none in the 30 days before the World Series, correctly
# excluded at this setting) is this constant's justification, not a fit.
ROTATION_WINDOW_DAYS = 30

# Below this many starts WITHIN the window, a pitcher is a spot/opener
# appearance, not a rotation member. Owner requirement, 2026-09-25 review.
ROTATION_MIN_STARTS_IN_WINDOW = 2

# How many distinct pitchers a projected rotation ever draws from. 5 is a
# standard MLB rotation size; in practice a short-window postseason team
# usually has 4 (see module tests) and this only ever caps the pool from
# above.
ROTATION_POOL_SIZE = 5

# A pitcher must not be projected to start again within this many of his
# team's own PRECEDING games (this series's already-known/projected starts
# count, exactly as much as real pre-series ones). Owner requirement,
# 2026-09-25 review: "A pitcher who started in the previous 3 team games
# must never be projected. That means at least 4 days, since WS off-days
# are not modelled" -- i.e. this is a GAME-COUNT rule, not a calendar-date
# rule, and this module never reads a date to enforce it.
ROTATION_MIN_REST_GAMES = 3


def build_rotation_pool(store: Mapping, team: str, cutoff_date: str, *,
                        window_days: int = ROTATION_WINDOW_DAYS,
                        min_starts: int = ROTATION_MIN_STARTS_IN_WINDOW,
                        pool_size: int = ROTATION_POOL_SIZE) -> list:
    """Candidate ids (`int`, most-recent-last-start FIRST) for `team`'s
    presently active projected rotation, as of `cutoff_date`.

    A candidate needs at least `min_starts` starts for `team` within the
    trailing `window_days` before `cutoff_date` -- filtering out a reliever
    with a single spot/opener start (owner requirement (d), 2026-09-25
    review) AND a starter who has not pitched recently enough to still be
    on the active rotation, even with a long career total (the same
    review's real-data example: a Yankees starter with 29 2024 starts but
    his last one 30 days before the World Series and none in the ALDS or
    ALCS -- correctly excluded here because he clears `min_starts` over the
    full season but not within `window_days`).

    Never reads a row on or after `cutoff_date`.
    """
    cutoff = str(cutoff_date)
    try:
        window_start = (_to_date(cutoff) - _timedelta(days=window_days)).isoformat()
    except MatchupModelError:
        window_start = None

    counts_in_window: dict = {}
    last_start: dict = {}
    for row in (store or {}).values():
        date = str(row.get("date") or "")
        if not date or date >= cutoff:
            continue
        if team not in (row.get("away_team"), row.get("home_team")):
            continue
        raw = row.get("home_probable_id") if row.get("home_team") == team else row.get("away_probable_id")
        pid = _to_int_id(raw)
        if pid is None:
            continue
        if pid not in last_start or date > last_start[pid]:
            last_start[pid] = date
        if window_start is None or date >= window_start:
            counts_in_window[pid] = counts_in_window.get(pid, 0) + 1

    eligible = [pid for pid, c in counts_in_window.items() if c >= min_starts]
    eligible.sort(key=lambda pid: last_start[pid], reverse=True)
    return eligible[:pool_size]


def project_team_rotation(pool: Sequence, known_starters: Mapping, n_games: int, *,
                          min_rest_games: int = ROTATION_MIN_REST_GAMES) -> dict:
    """One team's starter for every game index `0..n_games-1`: whatever
    `known_starters` says for the indices it covers, PROJECTED for every
    other index. Returns `{index: (pitcher_id, "actual" | "projected")}`.

    PROJECTION RULE (owner requirement (b), 2026-09-25 review): the next
    start goes to whichever `pool` member has gone LONGEST since his last
    start -- real or already-projected earlier in THIS walk ("counting
    this series's starts") -- excluding anyone who started in the previous
    `min_rest_games` games for this team. A pitcher therefore never repeats
    within `min_rest_games + 1` consecutive team games.

    `pool` must already be ordered most-recent-last-start-first (exactly
    what `build_rotation_pool` returns); this function reverses it once to
    get "who has rested longest is first in line," then maintains that
    ordering as a queue: every start (known or projected) moves that
    pitcher to the back.

    Never reads index `>= i` while deciding game `i` -- the walk is
    strictly left to right and a game's own assignment can only depend on
    games already assigned earlier in the SAME call.
    """
    if not pool:
        raise MatchupModelError("no rotation pool to project a rotation from")

    recency_order = list(reversed(pool))  # front = rested longest = next up
    recent_window: list = []              # last `min_rest_games` starters

    def touch(pid):
        if pid in recency_order:
            recency_order.remove(pid)
            recency_order.append(pid)
        recent_window.append(pid)
        while len(recent_window) > min_rest_games:
            recent_window.pop(0)

    out = {}
    for i in range(n_games):
        if i in known_starters:
            pid = known_starters[i]
            out[i] = (pid, "actual")
            touch(pid)
            continue
        excluded = set(recent_window)
        candidates = [pid for pid in recency_order if pid not in excluded]
        if not candidates:
            raise MatchupModelError(
                f"no eligible rotation member for game index {i}: pool of "
                f"{len(pool)} is too small for a minimum rest of "
                f"{min_rest_games} games")
        chosen = candidates[0]
        out[i] = (chosen, "projected")
        touch(chosen)
    return out


def _timedelta(days):
    return _timedelta_cls(days=days)


def _to_date(value):
    if isinstance(value, _date_cls):
        return value
    try:
        return _date_cls.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise MatchupModelError(f"date must be ISO format, got {value!r}") from exc


# ---------------------------------------------------------------------------
# Series state conditioning -- reuses postseason.exact_series_probability
# UNMODIFIED (owner requirement, 2026-09-25 review: "series forecasts must
# evolve by game state and rotation").
# ---------------------------------------------------------------------------

def conditional_series_win_prob(future_game_probs: Sequence, wins: int, losses: int,
                                k_series: int) -> float:
    """P(the designated team wins a first-to-`k_series` series), CONDITIONED
    on already having `wins` wins and `losses` losses, computed by reusing
    `postseason.exact_series_probability` completely unmodified.

    THE TRICK. That function's recursion always starts at (0, 0) and reads
    `game_probs` in order. Prepending `wins` certain-win games (p=1.0) and
    `losses` certain-loss games (p=0.0) makes the very same (0, 0)-start
    recursion pass through exactly the (wins, losses) state before it ever
    reads a real probability -- each forced game is a deterministic, order-
    independent transition (see postseason.py's own docstring on p=0/p=1
    branches never being explored), so the ORDER of the padding among
    itself does not matter, only the COUNT. This needs no change to
    postseason.py at all.

    `future_game_probs` must have exactly `2*k_series - 1 - wins - losses`
    entries -- the games not yet decided. If the series is already clinched
    (`wins == k_series` or `losses == k_series`), those entries are
    constructed but never actually read by the solver -- the same "clinch
    stops the series" property the solver already guarantees, verified
    directly by `tests/test_matchup_model.py` planting NaN there, the same
    way `tests/test_postseason_solver.py` already does for the unconditioned
    case.
    """
    if isinstance(wins, bool) or isinstance(losses, bool) or wins < 0 or losses < 0:
        raise MatchupModelError(f"wins/losses must be non-negative integers, got {wins!r}/{losses!r}")
    needed = 2 * k_series - 1 - wins - losses
    if len(future_game_probs) != needed:
        raise MatchupModelError(
            f"conditional_series_win_prob: expected {needed} remaining game "
            f"probabilities for {wins} wins / {losses} losses in a first-to-"
            f"{k_series} series, got {len(future_game_probs)}")
    padded = [1.0] * wins + [0.0] * losses + list(future_game_probs)
    return postseason.exact_series_probability(padded, k_series)["p_win"]
