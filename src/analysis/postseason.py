"""Exact postseason series solver and bracket engine.

WHAT THIS FILE IS, AND WHAT IT IS NOT
--------------------------------------
This is tournament MATH, not a prediction. Nothing here estimates how good
any real team is. `exact_series_probability` and `simulate_series` turn
per-game win probabilities that the CALLER supplies into series- and
bracket-level probabilities; the bracket engine turns a caller-supplied
seeding plus a caller-supplied pairwise win-probability function into
normalized advancement probabilities. No real 2026 contender list, team
strength number, or "current standings" is hardcoded anywhere below -- see
`src/analysis/postseason_config.py`'s docstring for where the verified
tournament STRUCTURE (as opposed to any team's chances within it) came from.

Nothing here claims predictive advantage. A caller who feeds it a bad
win-probability estimate gets a bad answer out; this module's only job is
to get the SERIES MATH right given whatever per-game probabilities arrive.

THE CORE IDEA: A SERIES IS NOT ONE WIN PROBABILITY REUSED k TIMES
-------------------------------------------------------------------
A first-to-k series is an absorbing Markov chain over (wins, losses). Write
S(w, l) for "the designated team's probability of winning the series from
here, given it currently has w wins and l losses and is about to play game
w + l + 1" (0-indexed below: game index `w + l`). Then

    S(w, l) = p * S(w+1, l) + (1 - p) * S(w, l+1)
    p = game_probs[w + l]

with absorbing states S(k, l) = 1 (series won) and S(w, k) = 0 (series
lost) for any l, w < k. `p` is allowed to be a DIFFERENT number for every
game -- the whole point of carrying a list rather than one scalar is that
home-field advantage flips mid-series (a 2-2-1 or 2-3-2 pattern), and a
model that reused one number for every game would get the shape of a
series wrong even with a perfectly calibrated average.

`exact_series_probability` computes this recursion exactly (memoized, no
sampling). `simulate_series` is a Monte Carlo cross-check over the exact
same interface, so the two can be compared directly -- see that function's
docstring for why its reported error is NOT the same thing as uncertainty
in the game_probs themselves.

Pure stdlib. No I/O, no network, no randomness except through an explicit,
caller-supplied seed.
"""

from __future__ import annotations

import itertools
import math
import random
from typing import Callable, Mapping, Optional, Sequence

from src.analysis import postseason_config as pc


class PostseasonError(ValueError):
    """Raised when the inputs cannot support a series or bracket computation
    at all -- a malformed probability, a missing seed, an unresolvable
    World Series home-field tie. Loud on purpose: a silent fallback here
    would be a fabricated number wearing a real one's clothes."""


# ---------------------------------------------------------------------------
# C1a -- the exact solver
# ---------------------------------------------------------------------------

def _check_game_prob(p, game_index: int) -> None:
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise PostseasonError(
            f"game {game_index + 1}: win probability must be a number, got {p!r}")
    if not (0.0 <= p <= 1.0) or (isinstance(p, float) and math.isnan(p)):
        raise PostseasonError(
            f"game {game_index + 1}: win probability out of [0, 1]: {p!r}")


def _validate_series_inputs(game_probs: Sequence[float], k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise PostseasonError(f"k must be a positive integer, got {k!r}")
    needed = 2 * k - 1
    if len(game_probs) < needed:
        raise PostseasonError(
            f"need at least {needed} per-game probabilities for a "
            f"first-to-{k} series (best-of-{needed}); got {len(game_probs)}")


def _absorbing_distribution(game_probs: Sequence[float], k: int) -> dict:
    """The recursion in this module's docstring, generalized to carry a
    length breakdown instead of a single scalar.

    Returns {games_played: (p_win_at_that_length, p_loss_at_that_length)}.
    Memoized on (w, l) alone -- the next game's index is always w + l, so
    there is nothing else to key on.

    A branch is never explored when its own probability is exactly zero
    (`if p > 0.0` / `if p < 1.0` below), so once a game's probability makes
    the OTHER outcome certain (p == 0 or p == 1, i.e. a forced sweep from
    here), `game_probs` is never read at any index past that point. This is
    what "clinching stops the series" means at the level of this function,
    not just at the level of its numeric output -- see the clinch tests in
    tests/test_postseason_solver.py, which plant `float("nan")` at indices a
    correct implementation must never reach.
    """
    memo: dict = {}

    def rec(w: int, l: int) -> dict:
        if w == k:
            return {w + l: (1.0, 0.0)}
        if l == k:
            return {w + l: (0.0, 1.0)}
        key = (w, l)
        cached = memo.get(key)
        if cached is not None:
            return cached
        p = game_probs[w + l]
        _check_game_prob(p, w + l)
        merged: dict = {}
        if p > 0.0:
            for length, (pw, pl) in rec(w + 1, l).items():
                a, b = merged.get(length, (0.0, 0.0))
                merged[length] = (a + p * pw, b + p * pl)
        if p < 1.0:
            q = 1.0 - p
            for length, (pw, pl) in rec(w, l + 1).items():
                a, b = merged.get(length, (0.0, 0.0))
                merged[length] = (a + q * pw, b + q * pl)
        memo[key] = merged
        return merged

    return rec(0, 0)


def exact_series_probability(game_probs: Sequence[float], k: int) -> dict:
    """Exact probability the designated team wins a first-to-`k` series.

    `game_probs[i]` is that team's win probability in game i (0-indexed);
    only `game_probs[0 : 2*k - 1]` can ever matter and indices past where
    the series has already been clinched are never read (see
    `_absorbing_distribution`). Raises `PostseasonError` if fewer than
    `2*k - 1` entries are supplied, or if an entry that IS read is not a
    number in [0, 1].

    Returns a dict:
      p_win / p_loss           -- sum to 1.0
      length_probs              {games_played: probability}, sums to 1.0
      length_probs_win/_loss    same, split by who won; each sub-sums to
                                 p_win / p_loss respectively
      k, games_used             echoed back for convenience
    """
    _validate_series_inputs(game_probs, k)
    dist = _absorbing_distribution(game_probs, k)
    p_win = sum(pw for pw, _pl in dist.values())
    p_loss = sum(pl for _pw, pl in dist.values())
    length_probs = {n: pw + pl for n, (pw, pl) in dist.items()}
    length_probs_win = {n: pw for n, (pw, pl) in dist.items() if pw > 0.0}
    length_probs_loss = {n: pl for n, (pw, pl) in dist.items() if pl > 0.0}
    return {
        "p_win": p_win,
        "p_loss": p_loss,
        "k": k,
        "games_used": 2 * k - 1,
        "length_probs": length_probs,
        "length_probs_win": length_probs_win,
        "length_probs_loss": length_probs_loss,
    }


def simulate_series(game_probs: Sequence[float], k: int, *,
                    n_sims: int, seed: int) -> dict:
    """Monte Carlo cross-check for `exact_series_probability`, over the
    identical per-game probabilities and the identical stopping rule.

    The loop below exits the instant either side reaches `k` wins, so a
    swept series draws exactly `k` random numbers per simulated replay,
    never `2*k - 1` -- the same "clinching stops the series" property the
    exact solver has, enforced here by the `while` condition itself rather
    than by an optimization.

    `standard_error` is the MONTE CARLO SAMPLING ERROR ONLY: sqrt(p(1-p)/n),
    how far THIS finite-sample estimate can be expected to wander from what
    `exact_series_probability` returns for the SAME `game_probs`. It says
    nothing about whether `game_probs` is itself a good estimate of
    anything real -- that is model/scenario uncertainty, belongs entirely
    to whoever produced `game_probs`, and must never be added to, averaged
    with, or otherwise confused with this number. A caller that wants both
    reports them as two separate figures, not one blended one.

    Deterministic and reproducible: `random.Random(seed)` draws the same
    sequence every time for the same seed, on any machine, forever (CPython
    guarantees this for its Mersenne Twister implementation).
    """
    _validate_series_inputs(game_probs, k)
    if isinstance(n_sims, bool) or not isinstance(n_sims, int) or n_sims < 1:
        raise PostseasonError(f"n_sims must be a positive integer, got {n_sims!r}")
    rng = random.Random(seed)
    wins = 0
    length_counts: dict = {}
    for _ in range(n_sims):
        w = l = 0
        while w < k and l < k:
            p = game_probs[w + l]
            _check_game_prob(p, w + l)
            if rng.random() < p:
                w += 1
            else:
                l += 1
        length_counts[w + l] = length_counts.get(w + l, 0) + 1
        if w == k:
            wins += 1
    p_win = wins / n_sims
    standard_error = math.sqrt(p_win * (1.0 - p_win) / n_sims)
    return {
        "p_win": p_win,
        "p_loss": 1.0 - p_win,
        "standard_error": standard_error,
        "n_sims": n_sims,
        "seed": seed,
        "k": k,
        "length_probs": {n: c / n_sims for n, c in length_counts.items()},
    }


# ---------------------------------------------------------------------------
# Per-game probabilities from a home/away pattern
# ---------------------------------------------------------------------------

_MIN_GAME_PROB = 0.01
_MAX_GAME_PROB = 0.99


def game_probs_from_pattern(p_neutral: float, home_flags: Sequence[bool], *,
                            home_edge: float) -> list:
    """Per-game win probabilities for 'the designated team' across a series,
    given a neutral-site strength and where each game is played.

    `home_flags[i]` is True when the designated team is the home team in
    game i. `home_edge` is added on a home game and subtracted on a road
    game, then the result is clipped to [_MIN_GAME_PROB, _MAX_GAME_PROB] so
    a lopsided neutral strength plus the edge can never round off into a
    fabricated certainty.

    `home_edge` has no built-in default and must be passed explicitly:
    picking a number here without evidence would itself be the fabricated
    value this project's evidence rules forbid. Callers own that number.
    """
    if isinstance(p_neutral, bool) or not isinstance(p_neutral, (int, float)):
        raise PostseasonError(f"p_neutral must be a number, got {p_neutral!r}")
    if not (0.0 <= p_neutral <= 1.0):
        raise PostseasonError(f"p_neutral out of [0, 1]: {p_neutral!r}")
    if isinstance(home_edge, bool) or not isinstance(home_edge, (int, float)):
        raise PostseasonError(f"home_edge must be a number, got {home_edge!r}")
    out = []
    for is_home in home_flags:
        p = p_neutral + (home_edge if is_home else -home_edge)
        out.append(min(max(p, _MIN_GAME_PROB), _MAX_GAME_PROB))
    return out


# ---------------------------------------------------------------------------
# C1b -- bracket engine
#
# Every function below takes the tournament SHAPE from postseason_config
# (verified format) and takes the PARTICIPANTS and their pairwise
# probabilities from the caller (a "conditional bracket": a named,
# verified-or-projected seeding, never hardcoded here). Two leagues are
# walked independently through Wild Card -> Division Series -> LCS by
# EXACT enumeration of every combination of round outcomes (weighted by
# their joint probability, not sampled), then combined into the World
# Series.
#
# STATED SIMPLIFICATION: series within the same round are treated as
# independent random outcomes (e.g. the AL's 3-vs-6 and 4-vs-5 Wild Card
# results do not influence each other). This mirrors how the games
# themselves are unrelated contests and is the standard treatment; it is
# named here rather than left implicit, the same way strength.py names its
# own independence assumption between two teams' Poisson run totals.
# ---------------------------------------------------------------------------

TeamInfo = Mapping  # {"team": str, "seed": int, "win_pct": Optional[float]}
WinProbFn = Callable[[str, str], float]


def _home_field_holder(a_info: TeamInfo, b_info: TeamInfo, round_format: dict) -> str:
    """'a' or 'b': which side holds home-field advantage in this series,
    per `round_format["home_field_by"]`. Raises rather than guessing when
    the record-based rule (World Series) hits an exact tie -- see
    postseason_config's module docstring for why that tie is not resolvable
    from the inputs this engine models."""
    rule = round_format["home_field_by"]
    if rule == pc.HOME_FIELD_BY_SEED:
        sa, sb = a_info.get("seed"), b_info.get("seed")
        if sa is None or sb is None:
            raise PostseasonError(
                f"{round_format['name']} is seed-based but seed is missing "
                f"for {a_info.get('team')!r} or {b_info.get('team')!r}")
        if sa == sb:
            raise PostseasonError(
                f"{round_format['name']}: {a_info.get('team')!r} and "
                f"{b_info.get('team')!r} share seed {sa!r}")
        return "a" if sa < sb else "b"
    if rule == pc.HOME_FIELD_BY_RECORD:
        wa, wb = a_info.get("win_pct"), b_info.get("win_pct")
        if wa is None or wb is None:
            raise PostseasonError(
                f"{round_format['name']} home field is record-based but "
                f"win_pct is missing for {a_info.get('team')!r} or "
                f"{b_info.get('team')!r}")
        if wa == wb:
            raise PostseasonError(
                f"{round_format['name']}: {a_info['team']!r} and "
                f"{b_info['team']!r} are tied on regular-season win_pct "
                f"({wa!r}); MLB's real tiebreak (head-to-head, then "
                f"division record, then intraleague record) needs data "
                f"this engine does not model -- resolve it explicitly "
                f"rather than let this guess (see postseason_config.py)")
        return "a" if wa > wb else "b"
    raise PostseasonError(f"unknown home_field_by rule: {rule!r}")


def series_probabilities_for_round(a_info: TeamInfo, b_info: TeamInfo,
                                   round_format: dict, win_prob_fn: WinProbFn,
                                   *, home_edge: float) -> dict:
    """One series' full detail: who hosts which games (venue AND chronology,
    taken verbatim from the verified `round_format["home_pattern"]`), the
    per-game probabilities that pattern implies, and the exact series
    outcome. `win_prob_fn(team_a, team_b)` must return team_a's NEUTRAL-SITE
    win probability; this function is the only place home-field is added.
    """
    p_a_neutral = win_prob_fn(a_info["team"], b_info["team"])
    holder = _home_field_holder(a_info, b_info, round_format)
    pattern = round_format["home_pattern"]
    a_pattern = pattern if holder == "a" else tuple(not flag for flag in pattern)
    game_probs = game_probs_from_pattern(p_a_neutral, a_pattern, home_edge=home_edge)
    outcome = exact_series_probability(game_probs, round_format["k"])
    return {
        "round": round_format["name"],
        "team_a": a_info["team"],
        "team_b": b_info["team"],
        "home_field_holder": a_info["team"] if holder == "a" else b_info["team"],
        "p_team_a_wins": outcome["p_win"],
        "p_team_b_wins": outcome["p_loss"],
        "length_probs": outcome["length_probs"],
        "team_a_home_pattern": a_pattern,
        "game_probs_team_a": game_probs,
    }


def _series_outcomes(a_info: TeamInfo, b_info: TeamInfo, round_format: dict,
                     win_prob_fn: WinProbFn, *, home_edge: float):
    """[(winner_info, prob), (winner_info, prob)] plus the full series
    detail dict, for one series."""
    detail = series_probabilities_for_round(a_info, b_info, round_format,
                                            win_prob_fn, home_edge=home_edge)
    return [(a_info, detail["p_team_a_wins"]),
            (b_info, detail["p_team_b_wins"])], detail


def _round_outcomes(series_list):
    """series_list: one [(winner_info, prob), (winner_info, prob)] per
    INDEPENDENT series in a round. Returns [(winners_tuple, joint_prob), ...]
    for every combination, joint_prob = product of the chosen probabilities
    (see the independence simplification stated in this section's header)."""
    combos = []
    for choice in itertools.product(*series_list):
        winners = tuple(c[0] for c in choice)
        prob = 1.0
        for _winner, p in choice:
            prob *= p
        combos.append((winners, prob))
    return combos


def _require_league_seeds(league_seeds: Mapping[int, TeamInfo]) -> None:
    for seed in pc.FIELD_SEEDS:
        if seed not in league_seeds:
            raise PostseasonError(f"missing seed {seed} in league_seeds")
    teams = [info["team"] for info in league_seeds.values()]
    if len(set(teams)) != len(teams):
        raise PostseasonError(f"duplicate team name(s) in league_seeds: {teams!r}")


def league_pennant_probabilities(league_seeds: Mapping[int, TeamInfo],
                                 win_prob_fn: WinProbFn, *,
                                 home_edge: float) -> dict:
    """One league's Wild Card -> Division Series -> LCS, walked EXACTLY:
    every combination of round outcomes is enumerated and weighted by its
    joint probability, never sampled.

    `league_seeds`: {1: team_info, ..., 6: team_info}. Each team_info needs
    at least {"team": name, "seed": n}; include "win_pct" too if this
    league's pennant winner will be fed into `world_series_probabilities`
    (the World Series step needs it and does not know in advance which
    team will actually reach it).

    Returns probabilities that sum to an EXACT integer across the 6 seeds,
    by construction, and are asserted as such in
    tests/test_postseason_bracket.py:
      reaches_division_series  sums to 4.0 (2 byes + 2 Wild Card winners)
      reaches_lcs               sums to 2.0 (2 Division Series winners)
      wins_pennant               sums to 1.0 (1 pennant winner)
    plus `series_detail`, every series solved along the way, for audit.
    """
    _require_league_seeds(league_seeds)

    detail = []
    reaches_ds = {league_seeds[s]["team"]: 0.0 for s in pc.FIELD_SEEDS}
    for s in pc.BYE_SEEDS:
        reaches_ds[league_seeds[s]["team"]] = 1.0

    wc_outcomes_by_key = {}
    for key in pc.WILD_CARD_SERIES_KEYS:
        hi_seed, lo_seed = pc.WILD_CARD_PAIRINGS[key]
        outcomes, d = _series_outcomes(league_seeds[hi_seed], league_seeds[lo_seed],
                                       pc.WILD_CARD, win_prob_fn, home_edge=home_edge)
        detail.append(d)
        wc_outcomes_by_key[key] = outcomes
        for info, p in outcomes:
            reaches_ds[info["team"]] += p

    reaches_lcs = {league_seeds[s]["team"]: 0.0 for s in pc.FIELD_SEEDS}
    pennant = {league_seeds[s]["team"]: 0.0 for s in pc.FIELD_SEEDS}

    wc_series_ordered = [wc_outcomes_by_key[key] for key in pc.WILD_CARD_SERIES_KEYS]
    for winners, wc_prob in _round_outcomes(wc_series_ordered):
        winners_by_key = dict(zip(pc.WILD_CARD_SERIES_KEYS, winners))
        # Fixed bracket, NOT re-seeded after the Wild Card round (verified --
        # see postseason_config.FORMAT_VERIFICATION).
        ds_matchups = [
            (league_seeds[1], winners_by_key[pc.DS_OPPONENT_SERIES_FOR_SEED[1]]),
            (league_seeds[2], winners_by_key[pc.DS_OPPONENT_SERIES_FOR_SEED[2]]),
        ]
        ds_outcomes = []
        for a, b in ds_matchups:
            outcomes, d = _series_outcomes(a, b, pc.DIVISION_SERIES, win_prob_fn,
                                           home_edge=home_edge)
            detail.append(dict(d, path_prob=wc_prob))
            ds_outcomes.append(outcomes)

        for (ds1_winner, ds2_winner), ds_prob in _round_outcomes(ds_outcomes):
            path_prob = wc_prob * ds_prob
            reaches_lcs[ds1_winner["team"]] += path_prob
            reaches_lcs[ds2_winner["team"]] += path_prob

            lcs_outcomes, d = _series_outcomes(ds1_winner, ds2_winner, pc.LCS,
                                               win_prob_fn, home_edge=home_edge)
            detail.append(dict(d, path_prob=path_prob))
            for info, p in lcs_outcomes:
                pennant[info["team"]] += path_prob * p

    return {
        "reaches_division_series": reaches_ds,
        "reaches_lcs": reaches_lcs,
        "wins_pennant": pennant,
        "series_detail": detail,
    }


def world_series_probabilities(al_pennant: Mapping[str, float],
                               nl_pennant: Mapping[str, float],
                               al_team_info: Mapping[str, TeamInfo],
                               nl_team_info: Mapping[str, TeamInfo],
                               win_prob_fn: WinProbFn, *,
                               home_edge: float) -> dict:
    """Combine both leagues' pennant-winner distributions into World Series
    win probabilities. Every (AL team, NL team) pair with nonzero joint
    probability gets its own exact series solve -- home field for each
    follows `postseason_config.WORLD_SERIES["home_field_by"] == "record"`,
    i.e. whichever of the two actually-arriving pennant winners has the
    better regular-season win_pct, NOT whichever had the better seed.

    `wins_world_series` sums to 1.0 across however many distinct pairings
    have nonzero probability (asserted in tests/test_postseason_bracket.py).
    """
    ws_win: dict = {}
    detail = []
    for al_team, p_al in al_pennant.items():
        if p_al <= 0.0:
            continue
        for nl_team, p_nl in nl_pennant.items():
            if p_nl <= 0.0:
                continue
            joint = p_al * p_nl
            a_info = al_team_info[al_team]
            b_info = nl_team_info[nl_team]
            d = series_probabilities_for_round(a_info, b_info, pc.WORLD_SERIES,
                                               win_prob_fn, home_edge=home_edge)
            detail.append(dict(d, path_prob=joint))
            ws_win[al_team] = ws_win.get(al_team, 0.0) + joint * d["p_team_a_wins"]
            ws_win[nl_team] = ws_win.get(nl_team, 0.0) + joint * d["p_team_b_wins"]
    return {"wins_world_series": ws_win, "series_detail": detail}


def bracket_probabilities(bracket: Mapping[str, Mapping[int, TeamInfo]],
                          win_prob_fn: WinProbFn, *, home_edge: float) -> dict:
    """The full 12-team postseason, both leagues plus the World Series, in
    one call.

    `bracket`: {"AL": {1: team_info, ..., 6: team_info}, "NL": {...}} --
    always supplied by the caller. This function never assumes or hardcodes
    which teams are in it; every "current contenders" question is the
    caller's, asked and answered outside this module. Every team_info must
    carry "team", "seed", and "win_pct" (win_pct is required here because
    the pennant winner is not known in advance and the World Series step
    needs whichever team actually gets there to have one).
    """
    for lg in pc.LEAGUES:
        if lg not in bracket:
            raise PostseasonError(f"missing league {lg!r} in bracket")

    all_teams = [info["team"] for lg in pc.LEAGUES for info in bracket[lg].values()]
    if len(set(all_teams)) != len(all_teams):
        raise PostseasonError(f"duplicate team name(s) across the bracket: {all_teams!r}")

    per_league = {}
    for lg in pc.LEAGUES:
        per_league[lg] = league_pennant_probabilities(bracket[lg], win_prob_fn,
                                                       home_edge=home_edge)

    al_info = {info["team"]: info for info in bracket["AL"].values()}
    nl_info = {info["team"]: info for info in bracket["NL"].values()}
    ws = world_series_probabilities(
        per_league["AL"]["wins_pennant"], per_league["NL"]["wins_pennant"],
        al_info, nl_info, win_prob_fn, home_edge=home_edge)

    return {"AL": per_league["AL"], "NL": per_league["NL"], "world_series": ws}
