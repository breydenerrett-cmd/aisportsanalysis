"""Lane C demonstration: baseline vs. matchup-aware richer candidate, run
through the ALREADY-EXISTING exact series solver and bracket engine
(`src.analysis.postseason`, commit 221682eb -- untouched by this script).

TWO DEMONSTRATIONS, BOTH WRITTEN TO evidence/postseason/
-----------------------------------------------------------
1. ONE REAL-TEAM SERIES: the 2024 World Series (NYY @ LAD, LAD won it 4-1),
   entirely real teams, real starters, real venues, already decided. Used
   for MECHANICS VALIDATION ONLY, per this task's brief -- a solved
   historical series is not evidence either model has skill, only that the
   series-math machinery in `postseason.py` correctly turns whatever
   per-game probabilities a model supplies into a series probability.

2. ONE CONDITIONAL BRACKET: the full 12-team 2026 postseason field, derived
   from `data/historical/standings.jsonl`'s one captured snapshot
   (2026-09-08) -- NOT the final seeding (the regular season does not end
   until 2026-09-27, four days after wild-card seeding closes and 19 days
   after that snapshot was captured). This is named explicitly everywhere
   the bracket's output appears: CONDITIONAL on the 2026-09-08 standings,
   never asserted as the real 2026-09-29 field.

THE SEALED WINDOW
------------------
2026-01-01..2026-08-27 is a sealed evaluation period for this research
program and is never read by this script. Every 2026 row this script
touches (team aggregates, bullpen log) is filtered to
`date >= SEALED_END_EXCLUSIVE` before being handed to any feature-building
function -- see `_unsealed_2026_store` / `_unsealed_2026_bullpen_log`
below. The 2026 standings snapshot itself (2026-09-08) is a single already-
public capture, not a range read, and needs no filtering.

BASELINE, UNMODIFIED
----------------------
`src.analysis.strength.model_line` (the model `src/report/card_v2.py`
actually calls) and `src.analysis.postseason`'s solver/bracket engine
(commit 221682eb) are both used exactly as they already exist. Nothing in
either file is edited by this script or by `src/analysis/matchup_model.py`.

NO PREDICTIVE CLAIM anywhere in this script's output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import matchup_model as mm
from src.analysis import postseason
from src.analysis import postseason_config as pc
from src.analysis import strength
from src.paths import repo_root
from src.pipeline import bullpen as bullpen_mod
from src.pipeline import history
from src.pipeline import parkfactors
from src.pipeline import pitchers as pitchers_mod

EVIDENCE_DIR = repo_root() / "evidence" / "postseason"

# The sealed evaluation window for this research program. Never read.
SEALED_START = "2026-01-01"
SEALED_END_EXCLUSIVE = "2026-08-28"  # first UNSEALED date; 08-27 itself stays sealed


def _unsealed_2026_store(store: dict) -> dict:
    """`store`, with every 2026 row inside [SEALED_START, SEALED_END_EXCLUSIVE)
    removed. Non-2026 rows (2023-25, used for the World Series demo) pass
    through untouched -- only 2026 has a sealed window."""
    out = {}
    for key, row in store.items():
        date = str(row.get("date") or "")
        if date.startswith("2026") and date < SEALED_END_EXCLUSIVE:
            continue
        out[key] = row
    return out


def _unsealed_2026_bullpen_log(log: list) -> list:
    out = []
    for row in log:
        date = str(row.get("date") or "")
        if date.startswith("2026") and date < SEALED_END_EXCLUSIVE:
            continue
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Demonstration 1 -- the 2024 World Series, real teams, real games, solved
# exactly through postseason.exact_series_probability.
# ---------------------------------------------------------------------------

def run_world_series_2024_demo(store, pitcher_logs, bullpen_log) -> dict:
    series_start = "2024-10-25"  # frozen point-in-time cutoff for every
    # team-aggregate / bullpen-rate / park-factor lookup below -- the
    # engine does not model in-series updating of season rates, the same
    # kind of stated simplification postseason.py's own docstring names for
    # round independence. Per-game STARTER and VENUE still vary game to
    # game below, because those are the real, game-specific facts.

    # The five real games actually played (LAD won 4-1; games 6-7 never
    # happened). Starters are the ACTUAL historical starters for each game
    # -- confirmed after the fact, not a pre-series prediction of who would
    # start games 3-5. This is exactly why the task scopes postseason data
    # to MECHANICS validation: using the real starters is legitimate for
    # checking the series solver's arithmetic, not for claiming foresight.
    games = [
        {"date": "2024-10-25", "away": "NYY", "home": "LAD",
         "away_sp": 543037, "home_sp": 656427, "venue": "Dodger Stadium", "played": True},
        {"date": "2024-10-26", "away": "NYY", "home": "LAD",
         "away_sp": 607074, "home_sp": 808967, "venue": "Dodger Stadium", "played": True},
        {"date": "2024-10-28", "away": "LAD", "home": "NYY",
         "away_sp": 621111, "home_sp": 657376, "venue": "Yankee Stadium", "played": True},
        {"date": "2024-10-29", "away": "LAD", "home": "NYY",
         "away_sp": 676508, "home_sp": 661563, "venue": "Yankee Stadium", "played": True},
        {"date": "2024-10-30", "away": "LAD", "home": "NYY",
         "away_sp": 656427, "home_sp": 543037, "venue": "Yankee Stadium", "played": True},
        # Games 6-7 were NEVER PLAYED -- the series clinched at game 5. They
        # exist here only because exact_series_probability requires a full
        # best-of-2k-1 = 7 length list; per that function's own docstring, a
        # branch past the clinch point is never actually read (the clinch
        # tests in tests/test_postseason_solver.py plant NaN at exactly
        # these indices to prove it). No starter is known for a game that
        # never happened, so both are left unconfirmed (None) rather than
        # guessed.
        {"date": None, "away": "NYY", "home": "LAD",
         "away_sp": None, "home_sp": None, "venue": "Dodger Stadium", "played": False},
        {"date": None, "away": "NYY", "home": "LAD",
         "away_sp": None, "home_sp": None, "venue": "Dodger Stadium", "played": False},
    ]
    actual_winner_by_game = ["LAD", "LAD", "LAD", "NYY", "LAD"]

    league_rpg = mm.league_rpg_from_store(store, series_start)

    per_game = []
    baseline_probs_lad = []
    richer_probs_lad = []
    for g in games:
        cmp_ = mm.compare_game(
            store, pitcher_logs, bullpen_log, g["away"], g["home"],
            g["away_sp"], g["home_sp"], series_start, league_rpg=league_rpg)

        if g["home"] == "LAD":
            p_lad_baseline = cmp_["baseline"]["p_home"]
            p_lad_richer = cmp_["richer"]["p_home"]
        else:
            p_lad_baseline = (1.0 - cmp_["baseline"]["p_home"]
                              if cmp_["baseline"]["p_home"] is not None else None)
            p_lad_richer = (1.0 - cmp_["richer"]["p_home"]
                            if cmp_["richer"]["p_home"] is not None else None)

        baseline_probs_lad.append(p_lad_baseline)
        richer_probs_lad.append(p_lad_richer)
        per_game.append({
            "date": g["date"], "played": g["played"],
            "away": g["away"], "home": g["home"],
            "venue": g["venue"],
            "away_sp_id": g["away_sp"], "home_sp_id": g["home_sp"],
            "p_lad_baseline": round(p_lad_baseline, 4) if p_lad_baseline is not None else None,
            "p_lad_richer": round(p_lad_richer, 4) if p_lad_richer is not None else None,
            "richer_park_factor": cmp_["richer"]["park_factor"],
            "richer_starter_known": cmp_["richer"]["starter_known"],
            "richer_bullpen_known": cmp_["richer"]["bullpen_known"],
        })

    if any(p is None for p in baseline_probs_lad) or any(p is None for p in richer_probs_lad):
        raise RuntimeError("could not price every 2024 World Series game -- see per_game errors")

    baseline_series = postseason.exact_series_probability(baseline_probs_lad, k=4)
    richer_series = postseason.exact_series_probability(richer_probs_lad, k=4)

    # Monte Carlo cross-check on the RICHER model's per-game probabilities
    # only, reported as its own, separate figure -- sampling error, never
    # combined with model/scenario uncertainty (see module docstrings).
    mc = postseason.simulate_series(richer_probs_lad, k=4, n_sims=200_000, seed=20260924)

    return {
        "demonstration": "2024 World Series (NYY @ LAD), real teams and real games, "
                         "MECHANICS VALIDATION ONLY -- not evidence of model skill",
        "series_start_cutoff": series_start,
        "league_rpg_as_of_cutoff": league_rpg,
        "designated_team": "LAD",
        "actual_result": "LAD won the series 4-1",
        "actual_game_winners": actual_winner_by_game,
        "per_game": per_game,
        "baseline_series_solve": {
            "p_lad_wins_series": round(baseline_series["p_win"], 4),
            "length_probs": {str(k_): round(v, 4) for k_, v in baseline_series["length_probs"].items()},
        },
        "richer_series_solve": {
            "p_lad_wins_series": round(richer_series["p_win"], 4),
            "length_probs": {str(k_): round(v, 4) for k_, v in richer_series["length_probs"].items()},
        },
        "richer_monte_carlo_cross_check": {
            "p_lad_wins_series": round(mc["p_win"], 4),
            "standard_error_SAMPLING_ONLY": round(mc["standard_error"], 5),
            "n_sims": mc["n_sims"], "seed": mc["seed"],
            "note": "Monte Carlo SAMPLING error only -- how far this finite-sample "
                    "estimate can wander from richer_series_solve for the SAME "
                    "per-game probabilities. Says nothing about whether those "
                    "per-game probabilities are themselves accurate; that is "
                    "model/scenario uncertainty and belongs to the feature dicts "
                    "in per_game above, never added to this number.",
        },
        "baseline_vs_richer_series_delta": round(
            richer_series["p_win"] - baseline_series["p_win"], 4),
        "factor_dispositions": dict(mm.FACTOR_DISPOSITIONS),
    }


# ---------------------------------------------------------------------------
# Demonstration 1, v2 -- 2026-09-25 Opus review of the v1 World Series demo
# above found three problems and required fixes without touching the v1
# output file. This function is entirely NEW; `run_world_series_2024_demo`
# above is untouched, still defined, and no longer called from `main()` (so
# evidence/postseason/world_series_2024_demo.json is never rewritten).
#
# FIX 1 -- PER-FACTOR ATTRIBUTION. A combined richer p_home cannot show
# which factor caused how much of the move. `mm.attribution_breakdown`
# isolates starter-only, bullpen-only and park-only against the identical
# baseline, for every real game, with every raw input alongside.
#
# FIX 2 -- THE HINDSIGHT LEAK. v1's "richer_series_solve" (0.5788) priced
# every game with its ACTUAL starter, including games 2-5, which nobody
# could know before game 1. This version adds `pre_series_forecast`, which
# uses ONLY the real announced game-1 starters plus a rotation PROJECTED
# from each team's own starts strictly before the series (`mm.
# recent_starters` / `mm.project_rotation` -- cycling in order of recency,
# never reading a future appearance). The original hindsight number is kept
# too, under `hindsight_series_solve`, explicitly labelled as hindsight and
# not a forecast, for comparison -- never presented as the headline.
#
# FIX 3 -- STATE EVOLUTION. `state_table` has one row per k = 0..5 (the
# series win/loss count after k real games), each giving
# `mm.conditional_series_win_prob` (the exact solver, reused unmodified via
# padding -- see that function's docstring) and the starter ASSUMED for
# every remaining game: games already played get their real starter; every
# other game, including 6 and 7, gets a starter PROJECTED from what was
# known right after game k -- never "starter unknown".
# ---------------------------------------------------------------------------

def run_world_series_2024_demo_v2(store, pitcher_logs, bullpen_log) -> dict:
    series_start = "2024-10-25"  # same frozen point-in-time cutoff as v1,
    # for every team-aggregate / bullpen-rate / park-factor lookup below.

    K_SERIES = 4
    N_REAL_GAMES = 5
    DATES = ["2024-10-25", "2024-10-26", "2024-10-28", "2024-10-29", "2024-10-30"]
    # WORLD_SERIES home_pattern (True, True, False, False, False, True, True)
    # with LAD holding home field -- identical shape v1 used, extended to the
    # full 7 slots (games 6-7 never played in reality).
    HOME_BY_GAME = ["LAD", "LAD", "NYY", "NYY", "NYY", "LAD", "LAD"]
    AWAY_BY_GAME = ["NYY" if h == "LAD" else "LAD" for h in HOME_BY_GAME]
    VENUE_BY_GAME = ["Dodger Stadium" if h == "LAD" else "Yankee Stadium" for h in HOME_BY_GAME]
    # Real, historical starters -- FACTS for games 0-4 (0-indexed), which
    # already happened. Keyed by team so either side of any game can be
    # looked up regardless of who is home that game.
    ACTUAL_SP = {
        "LAD": {0: 656427, 1: 808967, 2: 621111, 3: 676508, 4: 656427},
        "NYY": {0: 543037, 1: 607074, 2: 657376, 3: 661563, 4: 543037},
    }
    ACTUAL_WINNER = ["LAD", "LAD", "LAD", "NYY", "LAD"]  # games 0..4

    league_rpg = mm.league_rpg_from_store(store, series_start)

    def price_lad(away, home, away_sp, home_sp):
        feats = mm.richer_features(store, pitcher_logs, bullpen_log, away, home,
                                   away_sp, home_sp, series_start, same_season_only=True)
        line, err = mm.model_line_or_none(feats, league_rpg=league_rpg)
        if line is None:
            raise RuntimeError(f"cannot price {away} @ {home}: {err}")
        p_home = line["p_home"]
        return p_home if home == "LAD" else 1.0 - p_home

    # ---- FIX 1: per-factor attribution, every real game ----
    attribution_by_game = []
    for i in range(N_REAL_GAMES):
        home, away = HOME_BY_GAME[i], AWAY_BY_GAME[i]
        away_sp, home_sp = ACTUAL_SP[away][i], ACTUAL_SP[home][i]
        att = mm.attribution_breakdown(store, pitcher_logs, bullpen_log, away, home,
                                       away_sp, home_sp, series_start, league_rpg=league_rpg)
        attribution_by_game.append({
            "game_number": i + 1, "date": DATES[i], "away": away, "home": home,
            "venue": VENUE_BY_GAME[i], **att,
        })

    # ---- FIX 2 & FIX 3, second review (2026-09-25): a corrected rotation
    # projection shared by BOTH the pre-series forecast and every state-
    # table row, so the two can never drift apart (asserted by
    # tests/test_postseason_demo.py::StateTableConsistencyTests).
    #
    # `mm.build_rotation_pool` finds each team's presently active starters
    # (>= 2 starts in the trailing 30 days, normalized to `int` ids -- the
    # id-type bug the second review found). `mm.project_team_rotation`
    # then walks games 0..6 in order: known games (index 0, always -- teams
    # always announce a series opener -- plus any index < k, already
    # played) keep their real starter; every other game is assigned to
    # whichever pool member has rested longest, never a pitcher who started
    # in the previous 3 team games. See both functions' docstrings.
    lad_pool = mm.build_rotation_pool(store, "LAD", series_start)
    nyy_pool = mm.build_rotation_pool(store, "NYY", series_start)

    def build_row(k):
        """One state-table row's (game_probs, starters_detail) for `k` real
        games already played. `k == 0` IS the pre-series forecast."""
        known_lad = {i: ACTUAL_SP["LAD"][i] for i in range(max(k, 1))}
        known_nyy = {i: ACTUAL_SP["NYY"][i] for i in range(max(k, 1))}
        lad_plan = mm.project_team_rotation(lad_pool, known_lad, 7)
        nyy_plan = mm.project_team_rotation(nyy_pool, known_nyy, 7)

        game_probs, starters = [], []
        for i in range(k, 7):
            home, away = HOME_BY_GAME[i], AWAY_BY_GAME[i]
            home_sp, home_src = (lad_plan if home == "LAD" else nyy_plan)[i]
            away_sp, away_src = (lad_plan if away == "LAD" else nyy_plan)[i]
            if i == 0:
                # Relabelled for readability only -- project_team_rotation
                # already marks it "actual"; game 1 is always known because
                # a series opener's starters are always pre-announced.
                home_src = away_src = "actual_announced_game1"
            p_lad = price_lad(away, home, away_sp, home_sp)
            game_probs.append(p_lad)
            starters.append({
                "game_number": i + 1, "home": home, "away": away,
                "home_sp_id": home_sp, "home_sp_source": home_src,
                "away_sp_id": away_sp, "away_sp_source": away_src,
                "p_lad": round(p_lad, 4),
            })
        return game_probs, starters

    state_table = []
    for k in range(0, 6):
        wins = ACTUAL_WINNER[:k].count("LAD")
        losses = k - wins
        remaining_probs, remaining_starters = build_row(k)
        p_series = mm.conditional_series_win_prob(remaining_probs, wins, losses, K_SERIES)
        state_table.append({
            "k": k, "lad_wins": wins, "lad_losses": losses,
            "p_lad_wins_series": round(p_series, 4),
            "remaining_games": remaining_starters,
        })

    # k == 0 IS the pre-series forecast -- same function call, same numbers,
    # by construction (not merely by coincidence checked after the fact).
    pre_series_game_probs_lad, pre_series_starters = build_row(0)
    pre_series_solve = postseason.exact_series_probability(pre_series_game_probs_lad, K_SERIES)
    pre_series_mc = postseason.simulate_series(pre_series_game_probs_lad, K_SERIES,
                                               n_sims=200_000, seed=20260925)

    # ---- The original v1 number, kept for comparison but relabeled ----
    hindsight_game_probs_lad = []
    for i in range(7):
        home, away = HOME_BY_GAME[i], AWAY_BY_GAME[i]
        home_sp = ACTUAL_SP[home].get(i)  # None for games 6-7 -- never played
        away_sp = ACTUAL_SP[away].get(i)
        hindsight_game_probs_lad.append(price_lad(away, home, away_sp, home_sp))
    hindsight_solve = postseason.exact_series_probability(hindsight_game_probs_lad, K_SERIES)
    hindsight_mc = postseason.simulate_series(hindsight_game_probs_lad, K_SERIES,
                                              n_sims=200_000, seed=20260925)

    return {
        "demonstration": "2024 World Series v2 -- per-factor attribution, a "
                         "hindsight-free pre-series forecast, and a k=0..5 "
                         "state table. MECHANICS VALIDATION ONLY.",
        "fixes_applied": {
            "1_per_factor_attribution": "attribution_by_game",
            "2_hindsight_leak": "pre_series_forecast (honest) vs "
                                "hindsight_series_solve (relabeled, kept for comparison)",
            "3_state_evolution": "state_table",
        },
        "series_start_cutoff": series_start,
        "league_rpg_as_of_cutoff": league_rpg,
        "designated_team": "LAD",
        "actual_result": "LAD won the series 4-1",
        "actual_game_winners": ACTUAL_WINNER,
        "attribution_by_game": attribution_by_game,
        "pre_series_forecast": {
            "label": "HONEST PRE-SERIES FORECAST -- game 1 uses the real "
                     "announced starters; every other game is projected from "
                     "each team's own active rotation as of 2024-10-25 "
                     "(>=2 starts in the trailing 30 days), assigning the "
                     "pool member rested longest and never repeating a "
                     "starter within 3 team games (never a future appearance)",
            "rotation_pool": {"LAD": lad_pool, "NYY": nyy_pool},
            "per_game": pre_series_starters,
            "p_lad_wins_series": round(pre_series_solve["p_win"], 4),
            "length_probs": {str(k_): round(v, 4)
                             for k_, v in pre_series_solve["length_probs"].items()},
            "monte_carlo_cross_check": {
                "p_lad_wins_series": round(pre_series_mc["p_win"], 4),
                "standard_error_SAMPLING_ONLY": round(pre_series_mc["standard_error"], 5),
                "n_sims": pre_series_mc["n_sims"], "seed": pre_series_mc["seed"],
            },
        },
        "hindsight_series_solve": {
            "label": "HINDSIGHT STARTERS, NOT A FORECAST -- every real game "
                     "(1-5) uses the starter who ACTUALLY pitched, which was "
                     "not knowable before that game; kept only for "
                     "comparison against pre_series_forecast, never the "
                     "headline number. This is v1's 0.5788.",
            "p_lad_wins_series": round(hindsight_solve["p_win"], 4),
            "length_probs": {str(k_): round(v, 4)
                             for k_, v in hindsight_solve["length_probs"].items()},
            "monte_carlo_cross_check": {
                "p_lad_wins_series": round(hindsight_mc["p_win"], 4),
                "standard_error_SAMPLING_ONLY": round(hindsight_mc["standard_error"], 5),
                "n_sims": hindsight_mc["n_sims"], "seed": hindsight_mc["seed"],
            },
        },
        "state_table": state_table,
        "state_table_note": (
            "Row k is conditioned on the REAL record after k games, via "
            "mm.conditional_series_win_prob -- k certain wins/losses padded "
            "onto postseason.exact_series_probability, which is otherwise "
            "unmodified. Games already played (and game 1 always) use real "
            "starters; every other remaining game, including 6 and 7, is "
            "assigned to whichever rotation-pool member has rested longest "
            "as of right after game k, excluding anyone who started in the "
            "previous 3 team games -- never left as 'unknown', never a "
            "repeat within 4 consecutive team games."),
        "factor_dispositions": dict(mm.FACTOR_DISPOSITIONS),
    }


# ---------------------------------------------------------------------------
# Demonstration 2 -- the conditional 2026 bracket, derived from the one
# standings snapshot in data/historical/standings.jsonl.
# ---------------------------------------------------------------------------

def _load_standings_snapshot() -> list:
    path = repo_root() / "data" / "historical" / "standings.jsonl"
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def derive_conditional_seeding(rows: list) -> dict:
    """`{"AL": {1: team_info, ..., 6: team_info}, "NL": {...}}`, using MLB's
    real seeding rule (verified in postseason_config.py): the three division
    leaders seeded 1-3 by regular-season win_pct, the three next-best clubs
    (by the feed's own wildcard_rank) seeded 4-6. Derived entirely from the
    snapshot rows -- no team is hardcoded.
    """
    captured_at = {r.get("captured_at") for r in rows}
    if len(captured_at) != 1:
        raise RuntimeError(f"expected one standings snapshot, found {captured_at!r}")

    by_league = {"AL": [], "NL": []}
    league_id_map = {103: "AL", 104: "NL"}
    for r in rows:
        lg = league_id_map.get(r.get("league_id"))
        if lg:
            by_league[lg].append(r)

    seeding = {}
    for lg, teams in by_league.items():
        leaders = sorted((t for t in teams if t.get("division_leader")),
                         key=lambda t: -t["win_pct"])
        wildcards = sorted((t for t in teams if not t.get("division_leader")
                           and t.get("wildcard_rank") is not None),
                          key=lambda t: t["wildcard_rank"])[:3]
        if len(leaders) != 3 or len(wildcards) != 3:
            raise RuntimeError(f"{lg}: expected 3 division leaders and 3 wild cards, "
                               f"got {len(leaders)} and {len(wildcards)}")
        seeds = {}
        for i, t in enumerate(leaders, start=1):
            seeds[i] = {"team": t["team_abbrev"], "seed": i, "win_pct": t["win_pct"]}
        for i, t in enumerate(wildcards, start=4):
            seeds[i] = {"team": t["team_abbrev"], "seed": i, "win_pct": t["win_pct"]}
        seeding[lg] = seeds

    return {"seeding": seeding, "captured_at": captured_at.pop(),
            "source": "data/historical/standings.jsonl (one snapshot)"}


def run_2026_conditional_bracket_demo(store, bullpen_log, standings_rows=None) -> dict:
    """`standings_rows` is the injection seam for the one standings snapshot
    the seeding is derived from. Left `None` it reads the live
    `data/historical/standings.jsonl`, exactly as before -- but since
    2026-10-05 the daily loop APPENDS a snapshot per day to that file, so the
    live read now raises "expected one standings snapshot" (see
    `derive_conditional_seeding`). A test that needs a stable bracket must
    pass its own single-snapshot rows rather than depend on the file."""
    snapshot_rows = (standings_rows if standings_rows is not None
                     else _load_standings_snapshot())
    derived = derive_conditional_seeding(snapshot_rows)
    seeding = derived["seeding"]

    unsealed_store = _unsealed_2026_store(store)
    unsealed_pen = _unsealed_2026_bullpen_log(bullpen_log)

    # Latest unsealed date actually in the store -- the point-in-time
    # cutoff for every aggregate/bullpen/park lookup the bracket uses.
    unsealed_2026_dates = sorted(
        d for d in (str(r.get("date") or "") for r in unsealed_store.values())
        if d.startswith("2026"))
    if not unsealed_2026_dates:
        raise RuntimeError("no unsealed 2026 games available for the bracket demo")
    as_of = unsealed_2026_dates[-1]

    league_rpg = mm.league_rpg_from_store(unsealed_store, as_of, same_season_only=True)
    if not league_rpg:
        raise RuntimeError(f"no league run rate available as of {as_of}")

    HOME_EDGE = 0.03  # SCENARIO INPUT, not fitted: half of strength.py's own
    # HOME_FIELD_RUNS (0.20 runs) translated to a rough win-probability
    # units order-of-magnitude, used ONLY to shape the pattern of per-game
    # probabilities postseason.game_probs_from_pattern needs on top of the
    # already-symmetrized neutral estimate below. Labelled a scenario input,
    # never described as learned -- see postseason.py's own
    # game_probs_from_pattern docstring, which requires this be passed
    # explicitly rather than defaulted for exactly this reason.

    def make_win_prob_fn(use_richer: bool):
        cache = {}

        def fn(team_a, team_b):
            key = (team_a, team_b, use_richer)
            if key not in cache:
                cache[key] = mm.neutral_win_prob(
                    unsealed_store, None, unsealed_pen, team_a, team_b, as_of,
                    league_rpg=league_rpg, use_richer=use_richer,
                    same_season_only=True)
            return cache[key]
        return fn

    def bracket_with(use_richer: bool):
        # postseason's bracket engine wants win_prob_fn(a, b) -> a's neutral
        # win prob; mm.neutral_win_prob already returns exactly that.
        fn = make_win_prob_fn(use_richer)
        return postseason.bracket_probabilities(seeding, fn, home_edge=HOME_EDGE)

    baseline_bracket = bracket_with(use_richer=False)
    richer_bracket = bracket_with(use_richer=True)

    # DATA-QUALITY HONESTY CHECK. The unsealed window is short (~26 days as
    # of this run), so bullpen_rate and park_factor for every seeded team
    # are measured here directly and their `thin` flags reported alongside
    # the bracket numbers -- a reader should not credit a factor with
    # "numerically responding" without also seeing how thin the sample
    # behind that response is.
    all_seeded_teams = sorted({t["team"] for lg in seeding.values() for t in lg.values()})
    relief_by_team = bullpen_mod.relief_rates_by_team(unsealed_pen, as_of, same_season_only=True)
    park_by_team = parkfactors.park_factors(unsealed_store, as_of, same_season_only=True)
    data_quality = {
        team: {
            "bullpen_rate": (relief_by_team.get(team) or {}).get("rate"),
            "bullpen_thin": (relief_by_team.get(team) or {}).get("thin", True),
            "bullpen_innings": (relief_by_team.get(team) or {}).get("innings"),
            "park_factor": (park_by_team.get(team) or {}).get("factor"),
            "park_thin": (park_by_team.get(team) or {}).get("thin", True),
        }
        for team in all_seeded_teams
    }

    def summarize(bracket):
        return {
            "AL_reaches_lcs": {t: round(p, 4) for t, p in bracket["AL"]["reaches_lcs"].items()},
            "AL_wins_pennant": {t: round(p, 4) for t, p in bracket["AL"]["wins_pennant"].items()},
            "NL_reaches_lcs": {t: round(p, 4) for t, p in bracket["NL"]["reaches_lcs"].items()},
            "NL_wins_pennant": {t: round(p, 4) for t, p in bracket["NL"]["wins_pennant"].items()},
            "wins_world_series": {t: round(p, 4)
                                  for t, p in bracket["world_series"]["wins_world_series"].items()},
        }

    return {
        "demonstration": "CONDITIONAL 2026 postseason bracket -- NOT the final field",
        "seeding_snapshot_captured_at": derived["captured_at"],
        "seeding_source": derived["source"],
        "seeding": {lg: {i: t["team"] for i, t in seeds.items()}
                   for lg, seeds in seeding.items()},
        "seeding_caveat": (
            "Derived from the single 2026-09-08 standings.jsonl snapshot. The "
            "regular season does not end until 2026-09-27 (docs/SEASON_END_PLAN.md) "
            "-- games played after 2026-09-08 are NOT reflected in this seeding, and "
            "no fresher snapshot was available in this store. This bracket is "
            "CONDITIONAL on that snapshot, not a claim about the real 2026-09-29 field."),
        "features_as_of": as_of,
        "league_rpg_as_of": round(league_rpg, 4),
        "sealed_window_excluded": f"[{SEALED_START}, {SEALED_END_EXCLUSIVE})",
        "home_edge_scenario_input": HOME_EDGE,
        "neutral_win_prob_note": (
            "win_prob_fn is an APPROXIMATE neutral-site estimate (average of "
            "pricing the matchup with each side at home) -- see "
            "matchup_model.neutral_win_prob's docstring for why it cannot be exact "
            "without editing the frozen strength.py module."),
        "baseline_bracket": summarize(baseline_bracket),
        "richer_bracket": summarize(richer_bracket),
        "richer_factors_used_in_bracket": ["park_factor", "bullpen_quality"],
        "richer_factors_not_used_in_bracket": {
            "starting_pitcher": "no probable pitchers exist yet for a round that "
                                "has not been scheduled -- UNAVAILABLE for this "
                                "bracket, unlike the World Series demo where real "
                                "historical starters were confirmed facts",
        },
        "richer_data_quality_by_team": data_quality,
        "richer_data_quality_caveat": (
            "The unsealed window backing bullpen_rate and park_factor above runs "
            f"only from {SEALED_END_EXCLUSIVE} to {as_of} (~26 days) -- most or all "
            "teams' park_factor comes back neutral/thin at that sample size (see "
            "park_thin), and several bullpen_rate values are themselves flagged "
            "thin. Where thin is true, treat that team's richer-vs-baseline "
            "movement as a real but noisy short-sample signal, not a settled read."),
        "factor_dispositions": dict(mm.FACTOR_DISPOSITIONS),
    }


# ---------------------------------------------------------------------------
# v3 -- third review, 2026-09-27. Owner requirement: MODEL-USED, SCENARIO
# INPUT, CONTEXT ONLY and UNAVAILABLE must stay DISTINCT in every output.
# Neither v2's World Series artifact-level `factor_dispositions` nor the
# (not-yet-written-by-main) 2026 bracket's correctly reflected that most of
# the games they cover use a PROJECTED starter, not a confirmed one -- both
# claimed a flat "starting_pitcher: MODEL-USED" regardless.
#
# LABELS ONLY. Both functions below call the EXISTING v2/v1 builder AS IS
# and only ever read or copy its return value -- neither one calls
# strength.model_line, postseason.exact_series_probability,
# postseason.simulate_series, or any other probability-producing code a
# second time with different inputs. Every probability, length_probs entry
# and Monte Carlo figure in a v3 artifact is therefore IDENTICAL to the
# corresponding v2/v1 one by construction, not merely by having been
# checked once -- asserted directly in
# tests/test_postseason_demo.py::V3ProbabilitiesMatchEarlierVersionTests.
# ---------------------------------------------------------------------------

def _labelled_starter_row(game_row: dict) -> dict:
    """One pre_series_forecast/state_table game row, with its OWN
    per-game `factor_dispositions` attached (`mm.per_game_factor_
    dispositions`, computed from that row's own `*_sp_source`). A shallow
    copy plus one new key -- every existing value in `game_row`, including
    its `p_lad`, is carried over untouched."""
    out = dict(game_row)
    out["factor_dispositions"] = mm.per_game_factor_dispositions(
        game_row["away_sp_source"], game_row["home_sp_source"])
    return out


def run_world_series_2024_demo_v3(store, pitcher_logs, bullpen_log) -> dict:
    """v2, relabelled. `attribution_by_game` needs no change here: it comes
    from `mm.attribution_breakdown`, itself fixed (third review) to say
    MODEL-USED only when both probable ids are real, so v2's own
    attribution rows are already correct and are carried over as is.
    `pre_series_forecast` and `state_table` get a per-game
    `factor_dispositions` each; the artifact-level `factor_dispositions`
    drops `starting_pitcher` entirely rather than default to one label for
    an artifact that mixes MODEL-USED and SCENARIO INPUT games.
    """
    v2 = run_world_series_2024_demo_v2(store, pitcher_logs, bullpen_log)

    v3 = dict(v2)
    v3["pre_series_forecast"] = dict(
        v2["pre_series_forecast"],
        per_game=[_labelled_starter_row(g) for g in v2["pre_series_forecast"]["per_game"]])
    v3["state_table"] = [
        dict(row, remaining_games=[_labelled_starter_row(g) for g in row["remaining_games"]])
        for row in v2["state_table"]
    ]

    top_level = dict(v2["factor_dispositions"])
    del top_level["starting_pitcher"]
    v3["factor_dispositions"] = top_level
    v3["factor_dispositions_note"] = (
        "starting_pitcher has NO single artifact-level disposition here -- "
        "this artifact mixes real, already-played games with a projected "
        "rotation. attribution_by_game's 5 real games are MODEL-USED "
        "(see each row's own factor_dispositions); game 1 of "
        "pre_series_forecast and of every state_table row is MODEL-USED "
        "for the same reason a series opener's starters are always "
        "announced; every OTHER game in pre_series_forecast and in "
        "state_table is SCENARIO INPUT, never MODEL-USED, because its "
        "starter is a rotation projection, not a fact. Read each game's "
        "own factor_dispositions.starting_pitcher rather than this "
        "artifact-level map for that factor.")
    v3["evidence_scope_note"] = (
        "The 131 games / 33 series in data/historical/mlb_results.csv "
        "(2023-2025) are an EVALUATION SUBSTRATE for exercising this "
        "project's series and bracket mechanics -- observed history, not "
        "evidence of predictive skill. Nothing in this demonstration "
        "claims otherwise.")
    v3["labelling_fix_note"] = (
        "v3 changes LABELS ONLY, per the 2026-09-27 review. Every "
        "probability, length_probs entry and Monte Carlo figure in this "
        "file is copied unchanged from run_world_series_2024_demo_v2's own "
        "return value -- see this script's v3 section header and "
        "tests/test_postseason_demo.py's byte-identical-probability check.")
    v3["demonstration"] = v2["demonstration"] + " v3 adds a per-game factor_dispositions map to every game."
    return v3


def run_2026_conditional_bracket_demo_v3(store, bullpen_log, standings_rows=None) -> dict:
    """The bracket, relabelled. Every round here is an unscheduled future
    game, so `starting_pitcher` is uniformly UNAVAILABLE -- not MODEL-USED
    (the bug) and not SCENARIO INPUT (no rotation projection is attempted
    for a round this far out; see `richer_factors_not_used_in_bracket`,
    already present in v1/this function's own output).
    """
    v1 = run_2026_conditional_bracket_demo(store, bullpen_log, standings_rows)

    v3 = dict(v1)
    top_level = dict(v1["factor_dispositions"])
    top_level["starting_pitcher"] = mm.UNAVAILABLE
    v3["factor_dispositions"] = top_level
    v3["evidence_scope_note"] = (
        "The 131 games / 33 series in data/historical/mlb_results.csv "
        "(2023-2025) are an EVALUATION SUBSTRATE for exercising this "
        "project's series and bracket mechanics -- observed history, not "
        "evidence of predictive skill. Nothing in this demonstration "
        "claims otherwise.")
    v3["labelling_fix_note"] = (
        "v3 changes LABELS ONLY, per the 2026-09-27 review: "
        "factor_dispositions.starting_pitcher now says UNAVAILABLE, "
        "matching what richer_factors_not_used_in_bracket already said, "
        "instead of the module-default MODEL-USED this artifact incorrectly "
        "carried before. Every probability in AL/NL/world_series below is "
        "copied unchanged from run_2026_conditional_bracket_demo's own "
        "return value.")
    v3["demonstration"] = v1["demonstration"] + " -- v3 corrects factor_dispositions.starting_pitcher to UNAVAILABLE."
    return v3


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """2026-09-27 third review: only the v3 artifacts are (re)built by this
    entry point now. `run_world_series_2024_demo` (v1),
    `run_2026_conditional_bracket_demo` (v1) and
    `run_world_series_2024_demo_v2` are all left fully defined above,
    unmodified, and `run_world_series_2024_demo_v2` / `run_2026_conditional_
    bracket_demo` are still CALLED (by the two `_v3` functions, to build on
    their output) -- but nothing here writes to
    evidence/postseason/world_series_2024_demo.json,
    evidence/postseason/world_series_2024_demo_v2.json, or
    evidence/postseason/bracket_2026_conditional_demo.json. All three were
    written by earlier runs of this script and are left untouched by this
    one.
    """
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    store = history.read_results()
    pitcher_logs = pitchers_mod.read_logs()
    bullpen_log = bullpen_mod.read_log()

    print("Building 2024 World Series demonstration v3 (per-game factor_dispositions)...")
    ws_demo_v3 = run_world_series_2024_demo_v3(store, pitcher_logs, bullpen_log)
    ws_v3_path = EVIDENCE_DIR / "world_series_2024_demo_v3.json"
    ws_v3_path.write_text(json.dumps(ws_demo_v3, indent=2, sort_keys=False), encoding="utf-8")
    print(f"  wrote {ws_v3_path}")
    print(f"  pre-series forecast P(LAD wins series) = "
          f"{ws_demo_v3['pre_series_forecast']['p_lad_wins_series']}")
    print(f"  hindsight (not a forecast) P(LAD wins series) = "
          f"{ws_demo_v3['hindsight_series_solve']['p_lad_wins_series']}")
    print(f"  actual result: {ws_demo_v3['actual_result']}")
    print(f"  state table: {[(r['k'], r['lad_wins'], r['lad_losses'], r['p_lad_wins_series']) for r in ws_demo_v3['state_table']]}")
    print(f"  artifact-level factor_dispositions has starting_pitcher: "
          f"{'starting_pitcher' in ws_demo_v3['factor_dispositions']} (should be False -- dropped)")

    print("\nBuilding conditional 2026 bracket demonstration v3 (starting_pitcher disposition fix)...")
    bracket_demo_v3 = run_2026_conditional_bracket_demo_v3(store, bullpen_log)
    bracket_v3_path = EVIDENCE_DIR / "bracket_2026_conditional_demo_v3.json"
    bracket_v3_path.write_text(json.dumps(bracket_demo_v3, indent=2, sort_keys=False), encoding="utf-8")
    print(f"  wrote {bracket_v3_path}")
    print(f"  factor_dispositions.starting_pitcher = "
          f"{bracket_demo_v3['factor_dispositions']['starting_pitcher']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
