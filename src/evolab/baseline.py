"""Phase 2A: a penalised logistic model of the RESIDUAL against the close.

The pre-registration is `docs/EVOLAB_PHASE2A_BASELINE.md`, frozen (§1-§8)
before any score in this module was computed. One question: do the
point-in-time matrix features carry predictive information the market's own
closing price does not already hold?

THE OFFSET IS THE WHOLE POINT
-----------------------------
    eta_i = logit(p_market_i) + b0 + x_i . beta

`logit(p_market)` enters with its coefficient PINNED AT 1 and is never
fitted and never penalised. A model that merely rediscovers the market
therefore earns exactly nothing: the only route to a lower log-loss is
information the close lacks. Three nested models are reported so that "the
market is slightly miscalibrated" can never be read as "our features
predict": M0 the market alone, M1 the market plus a free intercept, M2 the
market plus intercept plus penalised features.

NOT EVIDENCE
------------
Train 2023, evaluate 2024 -- both inside the exploratory, non-evidential
sandbox (docs/EVOLUTION_LAB_ASSESSMENT.md §7, Decision 1). 2025 is
tuning-only and is not read here; sealed 2026 is not read here. The seasons
this module will accept are pinned to (2023, 2024) structurally, the same
guard `matrix.ALLOWED_SEASONS` uses.

NO NUMPY, NO SCIPY
------------------
Newton/IRLS with a ridge-augmented Hessian solved by Gaussian elimination
with partial pivoting (L2), and glmnet-style coordinate descent on the IRLS
quadratic (L1). Both start from zero, both are deterministic, both are
pinned by tests against closed-form and planted-coefficient cases.
"""

from __future__ import annotations

import csv
import json
import math

from pathlib import Path

from src.data import parks
from src.model import discovery, selections
from src.pipeline import backfill
from src.research import matrix

RESULTS_PATH = Path("data/historical/mlb_results.csv")
DEFAULT_OUT_DIR = Path("data/research/evolab")

TRAIN_SEASON = 2023
EVAL_SEASON = 2024
ALLOWED_SEASONS = (TRAIN_SEASON, EVAL_SEASON)

# The same consensus floor every module in the repo uses.
MIN_BOOKS = 6

# Probabilities are clamped exactly as elobench._log_loss clamps them, so a
# degenerate forecast cannot post an infinite loss and dominate a mean.
CLAMP = 1e-6

# The frozen penalty grid (doc §4), identical for both norms.
PENALTY_GRID = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0,
                3000.0, 10000.0, 30000.0)

CV_FOLDS = 5

# Base quantities and the side each one is read from. matrix.py crosses
# sides ONCE: an away_-prefixed value describes the AWAY LINEUP's matchup,
# i.e. it is measured against the HOME starter. So a lineup-shaped quantity
# is read on its own prefix and a starter-shaped quantity on the opposite
# one. Getting this backwards yields a confident, precisely wrong sign on
# every game, which is why the mapping is a table and not an expression.
#   (name, home_prefix, away_prefix)
BASE_QUANTITIES = (
    ("lineup_platoon_share", "home", "away"),
    ("lineup_vs_primary_pitch", "home", "away"),
    ("top_minus_bottom", "home", "away"),
    ("history_woba", "home", "away"),
    ("history_pa", "home", "away"),
    ("starter_platoon_gap", "away", "home"),
    ("starter_velocity_gap", "away", "home"),
    ("starter_groundball_share", "away", "home"),
    ("primary_pitch_share", "away", "home"),
)

# Column order: every home-minus-away contrast, then every game-level mean.
COLUMN_NAMES = tuple(["d_" + q[0] for q in BASE_QUANTITIES]
                     + ["m_" + q[0] for q in BASE_QUANTITIES])


class BaselineError(RuntimeError):
    """Raised when the Phase 2A baseline cannot run honestly."""


# ---------------------------------------------------------------------------
# Small math, in pure Python
# ---------------------------------------------------------------------------

def sigmoid(z) -> float:
    """Logistic, written branchwise so a large |z| cannot overflow exp."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    value = math.exp(z)
    return value / (1.0 + value)


def logit(p) -> float:
    """Log-odds of a probability, clamped away from the poles."""
    clamped = min(max(float(p), CLAMP), 1.0 - CLAMP)
    return math.log(clamped / (1.0 - clamped))


def log_loss(probability, outcome) -> float:
    clamped = min(max(probability, CLAMP), 1.0 - CLAMP)
    return -math.log(clamped if outcome else 1.0 - clamped)


def brier(probability, outcome) -> float:
    return (probability - (1.0 if outcome else 0.0)) ** 2


def solve(matrix_rows, rhs) -> list:
    """Gaussian elimination with partial pivoting. Raises when singular."""
    n = len(rhs)
    work = [list(row) + [rhs[i]] for i, row in enumerate(matrix_rows)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(work[r][col]))
        if abs(work[pivot][col]) < 1e-14:
            raise BaselineError("singular system in solve()")
        work[col], work[pivot] = work[pivot], work[col]
        pivot_value = work[col][col]
        for row in range(col + 1, n):
            factor = work[row][col] / pivot_value
            if factor == 0.0:
                continue
            for k in range(col, n + 1):
                work[row][k] -= factor * work[col][k]
    out = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = work[row][n] - sum(work[row][k] * out[k]
                                   for k in range(row + 1, n))
        out[row] = total / work[row][row]
    return out


def _soft_threshold(value, amount) -> float:
    if value > amount:
        return value - amount
    if value < -amount:
        return value + amount
    return 0.0


# ---------------------------------------------------------------------------
# Fitting -- the offset never moves
# ---------------------------------------------------------------------------

def predict(x_rows, offsets, b0, beta) -> list:
    out = []
    for x, offset in zip(x_rows, offsets):
        eta = offset + b0
        for value, coefficient in zip(x, beta):
            eta += value * coefficient
        out.append(sigmoid(eta))
    return out


def fit_l2(x_rows, y, offsets, penalty, *, max_iterations=100,
           tolerance=1e-10) -> dict:
    """Newton/IRLS for SUM NLL + (penalty/2)*||beta||^2, intercept free.

    The offset enters every eta with a coefficient of 1 and is never a
    parameter. Step-halving guards the rare Newton overshoot; starting from
    zero makes the fit deterministic.
    """
    n = len(y)
    if n == 0:
        raise BaselineError("cannot fit on zero rows")
    p = len(x_rows[0]) if x_rows else 0
    dim = p + 1  # intercept first, then beta

    def objective(theta):
        total = 0.0
        for i in range(n):
            eta = offsets[i] + theta[0]
            row = x_rows[i]
            for j in range(p):
                eta += row[j] * theta[j + 1]
            # -log sigmoid(eta) when y=1, -log(1-sigmoid(eta)) when y=0,
            # written as the numerically stable softplus form.
            total += _softplus(eta) - (y[i] * eta)
        return total + 0.5 * penalty * sum(v * v for v in theta[1:])

    theta = [0.0] * dim
    value = objective(theta)
    for _ in range(max_iterations):
        gradient = [0.0] * dim
        hessian = [[0.0] * dim for _ in range(dim)]
        for i in range(n):
            row = x_rows[i]
            eta = offsets[i] + theta[0]
            for j in range(p):
                eta += row[j] * theta[j + 1]
            mu = sigmoid(eta)
            weight = mu * (1.0 - mu)
            residual = mu - y[i]
            full = (1.0,) + tuple(row)
            for a in range(dim):
                gradient[a] += residual * full[a]
                wa = weight * full[a]
                for b in range(a, dim):
                    hessian[a][b] += wa * full[b]
        for a in range(1, dim):
            gradient[a] += penalty * theta[a]
            hessian[a][a] += penalty
        # Symmetry: only the upper triangle was accumulated.
        for a in range(dim):
            for b in range(a):
                hessian[a][b] = hessian[b][a]
        # A tiny ridge on the intercept keeps a separable fold solvable; it
        # is 1e-9, far below any penalty on the grid, and applies to the
        # intercept only where no penalty otherwise exists.
        hessian[0][0] += 1e-9
        try:
            step = solve(hessian, [-g for g in gradient])
        except BaselineError:
            break
        scale = 1.0
        for _ in range(30):
            candidate = [theta[a] + scale * step[a] for a in range(dim)]
            candidate_value = objective(candidate)
            if candidate_value <= value + 1e-12:
                break
            scale *= 0.5
        else:
            break
        moved = max(abs(scale * s) for s in step) if step else 0.0
        theta, value = candidate, candidate_value
        if moved < tolerance:
            break
    return {"b0": theta[0], "beta": list(theta[1:]), "penalty": penalty,
            "objective": value, "norm": "l2"}


def _softplus(z) -> float:
    if z > 0.0:
        return z + math.log1p(math.exp(-z))
    return math.log1p(math.exp(z))


def fit_l1(x_rows, y, offsets, penalty, *, max_outer=50, max_inner=200,
           tolerance=1e-9) -> dict:
    """Coordinate descent on the IRLS quadratic: SUM NLL + penalty*|beta|_1.

    The glmnet construction. Each outer step forms the weighted least
    squares approximation at the current fit, then cycles coordinates with
    soft-thresholding; the intercept is updated unpenalised. The offset is
    held out of the working response so it can never be fitted.
    """
    n = len(y)
    if n == 0:
        raise BaselineError("cannot fit on zero rows")
    p = len(x_rows[0]) if x_rows else 0
    b0, beta = 0.0, [0.0] * p

    for _ in range(max_outer):
        previous = [b0] + list(beta)
        weights, working = [0.0] * n, [0.0] * n
        for i in range(n):
            eta = offsets[i] + b0
            row = x_rows[i]
            for j in range(p):
                eta += row[j] * beta[j]
            mu = sigmoid(eta)
            weight = max(mu * (1.0 - mu), 1e-5)
            weights[i] = weight
            # The fitted part excluding the offset, plus the Newton step.
            working[i] = (eta - offsets[i]) + (y[i] - mu) / weight

        # Residual of the working response against the current linear fit.
        residual = [0.0] * n
        for i in range(n):
            fit = b0
            row = x_rows[i]
            for j in range(p):
                fit += row[j] * beta[j]
            residual[i] = working[i] - fit
        weight_total = sum(weights)
        denominators = [sum(weights[i] * x_rows[i][j] * x_rows[i][j]
                            for i in range(n)) for j in range(p)]

        for _ in range(max_inner):
            largest = 0.0
            shift = sum(weights[i] * residual[i] for i in range(n)) / weight_total
            if shift != 0.0:
                b0 += shift
                for i in range(n):
                    residual[i] -= shift
                largest = max(largest, abs(shift))
            for j in range(p):
                if denominators[j] <= 0.0:
                    continue
                partial = sum(weights[i] * x_rows[i][j] * residual[i]
                              for i in range(n)) + denominators[j] * beta[j]
                updated = _soft_threshold(partial, penalty) / denominators[j]
                delta = updated - beta[j]
                if delta == 0.0:
                    continue
                beta[j] = updated
                for i in range(n):
                    residual[i] -= delta * x_rows[i][j]
                largest = max(largest, abs(delta))
            if largest < tolerance:
                break

        moved = max(abs(a - b) for a, b in zip([b0] + list(beta), previous))
        if moved < tolerance:
            break
    return {"b0": b0, "beta": beta, "penalty": penalty, "norm": "l1"}


def fit_intercept_only(y, offsets, **kwargs) -> dict:
    """M1: the market plus one free constant. No features at all."""
    return fit_l2([[] for _ in y], y, offsets, 0.0, **kwargs)


# ---------------------------------------------------------------------------
# Rows: matrix features joined to outcome and to the de-vigged close
# ---------------------------------------------------------------------------

def read_results(path=RESULTS_PATH) -> dict:
    """Regular-season rows with a recorded outcome, keyed by game_pk (str)."""
    out = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("game_type") or "R") != "R":
                continue
            if row.get("home_won") in (None, ""):
                continue
            out[str(row.get("game_pk"))] = row
    return out


def sides_for_row(row) -> dict:
    """Base quantity -> (home-side value, away-side value), None allowed.

    The single place the away_/home_ crossing is undone, via BASE_QUANTITIES.
    """
    out = {}
    for name, home_prefix, away_prefix in BASE_QUANTITIES:
        out[name] = (_quantity(row, home_prefix, name),
                     _quantity(row, away_prefix, name))
    return out


def _quantity(row, prefix, name):
    if name == "history_woba":
        entry = row.get(prefix + "_lineup_vs_starter_history") or {}
        return entry.get("woba")
    if name == "history_pa":
        entry = row.get(prefix + "_lineup_vs_starter_history") or {}
        pa = entry.get("pa")
        # 0 PA is a FACT (no shared history), not a gap: log1p(0) = 0.
        return math.log1p(pa) if isinstance(pa, (int, float)) else None
    return row.get(prefix + "_" + name)


def build_rows(season, *, matrix_rows=None, results=None, price_pairs=None,
               out_dir=matrix.DEFAULT_OUT_DIR) -> dict:
    """Eligible rows for one season, plus the count of every exclusion.

    Eligibility (doc §5): a matrix row (so a posted lineup), a regular-season
    outcome, exactly one odds event resolved by start time, and a close
    consensus quoted by at least MIN_BOOKS books. `distinct` is carried on
    each row rather than filtered here, so the primary analysis and its
    pre-registered no-distinctness sensitivity read the same build.
    """
    if season not in ALLOWED_SEASONS:
        raise BaselineError(
            f"season {season} is outside the Phase 2A split {ALLOWED_SEASONS}; "
            f"2025 is tuning-only and 2026 is sealed")
    if matrix_rows is None:
        matrix_rows = list(matrix.read(season, out_dir=out_dir).values())
    if results is None:
        results = read_results()
    if price_pairs is None:
        price_pairs = backfill.price_pair(season)
    index = selections.index_price_pairs(price_pairs)

    rows, excluded = [], {"no_result": 0, "no_price_pair": 0,
                          "thin_consensus": 0}
    for source in sorted(matrix_rows, key=lambda r: (str(r.get("date")),
                                                     str(r.get("game_pk")))):
        game = results.get(str(source.get("game_pk")))
        if not game:
            excluded["no_result"] += 1
            continue
        key = (parks.canonical_team(game["away_team"]),
               parks.canonical_team(game["home_team"]), game["date"])
        pair = selections._resolve_pair(index.get(key), game)
        if not pair or not pair.get("close"):
            excluded["no_price_pair"] += 1
            continue
        fair = selections._fair(pair["close"]["bookmakers"],
                                pair["home_team"], pair["away_team"])
        if not fair or fair["books"] < MIN_BOOKS:
            excluded["thin_consensus"] += 1
            continue
        rows.append({
            "game_pk": str(source.get("game_pk")),
            "date": game["date"],
            "cutoff": source.get("cutoff"),
            "home_won": 1.0 if str(game["home_won"]) in ("1", "True", "true")
                        else 0.0,
            "market_home": fair["home_fair"],
            "offset": logit(fair["home_fair"]),
            "books": fair["books"],
            "distinct": bool(pair.get("distinct")),
            "sides": sides_for_row(source),
        })
    return {"rows": rows, "excluded": excluded}


# ---------------------------------------------------------------------------
# Design matrix: impute on training constants, contrast, standardise
# ---------------------------------------------------------------------------

def impute_constants(rows) -> dict:
    """Base quantity -> pooled mean over BOTH sides of the training rows.

    Pooled across sides rather than per side, so the imputation itself
    cannot import a home/away asymmetry. A quantity with no observed value
    anywhere in training imputes to 0.0 and is recorded as such.
    """
    out = {}
    for name, _home, _away in BASE_QUANTITIES:
        total, count = 0.0, 0
        for row in rows:
            for value in row["sides"][name]:
                if value is not None:
                    total += float(value)
                    count += 1
        out[name] = (total / count) if count else 0.0
    return out


def design(rows, constants) -> list:
    """One list of COLUMN_NAMES values per row: contrasts, then means."""
    out = []
    for row in rows:
        contrasts, means = [], []
        for name, _home, _away in BASE_QUANTITIES:
            home, away = row["sides"][name]
            home = constants[name] if home is None else float(home)
            away = constants[name] if away is None else float(away)
            contrasts.append(home - away)
            means.append(0.5 * (home + away))
        out.append(contrasts + means)
    return out


def standardisation(x_rows) -> dict:
    """Column means and standard deviations, plus the kept-column mask.

    A column with no training variance is DROPPED (doc §4) rather than
    divided by zero or silently kept as a constant.
    """
    if not x_rows:
        raise BaselineError("cannot standardise zero rows")
    width = len(x_rows[0])
    n = len(x_rows)
    means, deviations, kept = [], [], []
    for j in range(width):
        column = [row[j] for row in x_rows]
        mean = sum(column) / n
        variance = sum((v - mean) ** 2 for v in column) / n
        deviation = math.sqrt(variance)
        means.append(mean)
        deviations.append(deviation)
        if deviation > 1e-12:
            kept.append(j)
    return {"means": means, "deviations": deviations, "kept": kept}


def standardise(x_rows, scaling) -> list:
    means, deviations, kept = (scaling["means"], scaling["deviations"],
                               scaling["kept"])
    return [[(row[j] - means[j]) / deviations[j] for j in kept]
            for row in x_rows]


# ---------------------------------------------------------------------------
# Cross-validation inside the training season only
# ---------------------------------------------------------------------------

def date_folds(rows, folds=CV_FOLDS) -> list:
    """Fold index per row, GROUPED BY DATE.

    Games on one slate share weather, news and market conditions; splitting
    a slate across folds leaks. Distinct dates are sorted and assigned
    fold = index mod folds, which is deterministic and needs no seed.
    """
    dates = sorted({row["date"] for row in rows})
    assignment = {date: i % folds for i, date in enumerate(dates)}
    return [assignment[row["date"]] for row in rows]


def cross_validate(rows, penalties=PENALTY_GRID, *, norm="l2",
                   folds=CV_FOLDS) -> dict:
    """Mean out-of-fold log-loss per penalty, on training rows only.

    Imputation and standardisation constants are recomputed from each
    fold's own training rows, so a fold's held-out games never touch the
    constants used to score them.
    """
    assignment = date_folds(rows, folds)
    present = sorted(set(assignment))
    if len(present) < 2:
        raise BaselineError("cross-validation needs at least two folds")
    fitter = fit_l2 if norm == "l2" else fit_l1

    scores = {}
    for penalty in penalties:
        total, count = 0.0, 0
        for fold in present:
            train = [r for r, f in zip(rows, assignment) if f != fold]
            held = [r for r, f in zip(rows, assignment) if f == fold]
            if not train or not held:
                continue
            constants = impute_constants(train)
            raw_train = design(train, constants)
            scaling = standardisation(raw_train)
            x_train = standardise(raw_train, scaling)
            x_held = standardise(design(held, constants), scaling)
            fitted = fitter([list(r) for r in x_train],
                            [r["home_won"] for r in train],
                            [r["offset"] for r in train], penalty)
            probabilities = predict(x_held, [r["offset"] for r in held],
                                    fitted["b0"], fitted["beta"])
            for probability, row in zip(probabilities, held):
                total += log_loss(probability, row["home_won"])
                count += 1
        scores[penalty] = total / count if count else float("inf")
    best = min(penalties, key=lambda p: (scores[p], p))
    return {"scores": {str(k): round(v, 6) for k, v in scores.items()},
            "chosen": best, "norm": norm}


# ---------------------------------------------------------------------------
# The evaluation
# ---------------------------------------------------------------------------

def evaluate(train_rows, eval_rows, *, penalties=PENALTY_GRID,
             folds=CV_FOLDS, norms=("l2", "l1")) -> dict:
    """Fit on train, score on eval, never the other way round.

    Everything the eval season sees -- imputation constants, standardisation
    constants, the penalty, the coefficients -- is a function of the
    training rows alone.
    """
    if not train_rows or not eval_rows:
        raise BaselineError("both a training and an evaluation set are needed")

    constants = impute_constants(train_rows)
    raw_train = design(train_rows, constants)
    scaling = standardisation(raw_train)
    x_train = standardise(raw_train, scaling)
    x_eval = standardise(design(eval_rows, constants), scaling)
    y_train = [r["home_won"] for r in train_rows]
    offsets_train = [r["offset"] for r in train_rows]
    offsets_eval = [r["offset"] for r in eval_rows]
    kept_names = [COLUMN_NAMES[j] for j in scaling["kept"]]

    m1 = fit_intercept_only(y_train, offsets_train)
    market = [r["market_home"] for r in eval_rows]
    recalibrated = predict([[] for _ in eval_rows], offsets_eval,
                           m1["b0"], [])

    models = {}
    for norm in norms:
        selection = cross_validate(train_rows, penalties, norm=norm,
                                   folds=folds)
        fitter = fit_l2 if norm == "l2" else fit_l1
        fitted = fitter([list(r) for r in x_train], y_train, offsets_train,
                        selection["chosen"])
        models[norm] = {
            "cv": selection,
            "b0": fitted["b0"],
            "coefficients": dict(zip(kept_names, fitted["beta"])),
            "probabilities": predict(x_eval, offsets_eval, fitted["b0"],
                                     fitted["beta"]),
        }

    outcomes = [r["home_won"] for r in eval_rows]
    forecasts = {"m0_market": market, "m1_recalibrated": recalibrated}
    for norm in norms:
        forecasts["m2_" + norm] = models[norm]["probabilities"]

    losses = {name: [log_loss(p, y) for p, y in zip(values, outcomes)]
              for name, values in forecasts.items()}
    briers = {name: [brier(p, y) for p, y in zip(values, outcomes)]
              for name, values in forecasts.items()}
    n = len(eval_rows)
    summary = {name: {"log_loss": round(sum(values) / n, 5),
                      "brier": round(sum(briers[name]) / n, 5)}
               for name, values in losses.items()}

    comparisons = {}
    pairs = [("m1_recalibrated", "m0_market")]
    for norm in norms:
        pairs.append(("m2_" + norm, "m0_market"))
        pairs.append(("m2_" + norm, "m1_recalibrated"))
    for left, right in pairs:
        # Positive = the left model is WORSE than the right one, the same
        # sign convention docs/BENCHMARK_ELO.md froze.
        scored = [{"date": row["date"],
                   "_diff": losses[left][i] - losses[right][i]}
                  for i, row in enumerate(eval_rows)]
        mean = sum(r["_diff"] for r in scored) / n
        comparisons[f"{left}_minus_{right}"] = {
            "mean_diff": mean,
            "clustered_p": round(discovery.clustered_two_sided_p(mean, scored),
                                 6),
        }

    return {
        "train_games": len(train_rows),
        "eval_games": n,
        "train_dates": len({r["date"] for r in train_rows}),
        "eval_dates": len({r["date"] for r in eval_rows}),
        "columns": kept_names,
        "dropped_columns": [COLUMN_NAMES[j] for j in range(len(COLUMN_NAMES))
                            if j not in set(scaling["kept"])],
        "impute_constants": {k: round(v, 6) for k, v in constants.items()},
        "m1_intercept": m1["b0"],
        "models": {norm: {"cv": models[norm]["cv"],
                          "b0": models[norm]["b0"],
                          "coefficients": {k: v for k, v in
                                           models[norm]["coefficients"].items()}}
                   for norm in norms},
        "summary": summary,
        "comparisons": comparisons,
    }


def leakage_checks(train_rows, eval_rows) -> dict:
    """The doc §8 checklist that can be answered mechanically.

    Run unconditionally, not only when the result is surprising: a check
    performed solely after a win is a check whose result was already known.
    """
    def _cutoffs(rows):
        """Every row's accumulation cutoff against its own game date.

        `after` must be zero -- that would be a real leak. `equal` is NOT
        one: matrix._cutoff_for anchors a game to the first day of its own
        month, so a game played on the 1st has cutoff == date, and rebuilt
        gates on `game_date < cutoff` strictly, which still excludes every
        pitch from the game's own day. Reported separately rather than
        folded in, because a check that cannot distinguish the two says
        nothing.
        """
        counts = {"before": 0, "equal": 0, "after": 0}
        for row in rows:
            cutoff, date = row.get("cutoff"), row.get("date")
            if not cutoff or not date:
                counts["after"] += 1  # unprovable is treated as unsafe
                continue
            if str(cutoff) < str(date):
                counts["before"] += 1
            elif str(cutoff) == str(date):
                counts["equal"] += 1
            else:
                counts["after"] += 1
        return counts

    everything = list(train_rows) + list(eval_rows)
    keys = [r["game_pk"] for r in everything]
    # A real check, not an assertion: rebuild the design from rows whose
    # market price has been moved, and confirm not one column moves. The
    # only market number the model may see is the offset.
    constants = impute_constants(train_rows)
    moved = [dict(r, market_home=0.5, offset=0.0) for r in everything]
    design_shifts = sum(
        1 for before, after in zip(design(everything, constants),
                                   design(moved, constants))
        if before != after)
    return {
        "train_cutoff_vs_game_date": _cutoffs(train_rows),
        "train_games": len(train_rows),
        "eval_cutoff_vs_game_date": _cutoffs(eval_rows),
        "eval_games": len(eval_rows),
        "duplicate_game_pks": len(keys) - len(set(keys)),
        "train_eval_overlap": len({r["game_pk"] for r in train_rows}
                                  & {r["game_pk"] for r in eval_rows}),
        "design_columns_moved_by_price": design_shifts,
        "note": ("the offset is the only market number the model sees; every "
                 "design column comes from matrix.py, which reads pitches "
                 "before its own monthly cutoff and no price at all"),
    }


def run(*, out_dir=DEFAULT_OUT_DIR, matrix_dir=matrix.DEFAULT_OUT_DIR,
        write=True, penalties=PENALTY_GRID, norms=("l2", "l1")) -> dict:
    """The single scoring run the pre-registration authorises.

    Primary: the Elo benchmark's own eligibility, distinct close snapshot
    included, so the evaluation universe is the same 2024 games
    docs/BENCHMARK_ELO.md scored. Sensitivity: the same analysis with the
    distinctness filter dropped, pre-registered in doc §5.
    """
    built = {season: build_rows(season, out_dir=matrix_dir)
             for season in ALLOWED_SEASONS}

    out = {"train_season": TRAIN_SEASON, "eval_season": EVAL_SEASON,
           "excluded": {str(s): built[s]["excluded"] for s in ALLOWED_SEASONS},
           "penalty_grid": list(penalties), "cv_folds": CV_FOLDS,
           "min_books": MIN_BOOKS, "columns": list(COLUMN_NAMES)}

    for label, require_distinct in (("primary", True), ("sensitivity", False)):
        train = [r for r in built[TRAIN_SEASON]["rows"]
                 if r["distinct"] or not require_distinct]
        held = [r for r in built[EVAL_SEASON]["rows"]
                if r["distinct"] or not require_distinct]
        out[label] = evaluate(train, held, penalties=penalties, norms=norms)
        out[label]["requires_distinct_close"] = require_distinct
        out[label]["leakage_checks"] = leakage_checks(train, held)

    if write:
        target = Path(out_dir) / "phase2a_baseline.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        out["artifact"] = str(target)
    return out
