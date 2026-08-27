"""Logistic regression in pure stdlib. Deliberately the simplest thing that works.

WHY LOGISTIC REGRESSION AND NOT SOMETHING FANCIER
-------------------------------------------------
Three reasons, in order of importance for this project:

1. It produces naturally calibrated probabilities. That is the entire requirement --
   a score cannot be compared to a betting price, and a probability that does not
   mean what it says manufactures phantom edge. Gradient-boosted trees usually score
   better on accuracy and worse on calibration, which is the wrong trade here.

2. It is interpretable. When the model says a team is 58%, the coefficients say which
   features drove it. On an unvalidated betting model that is not a nicety; it is how
   you notice the model has learned something absurd.

3. It is hard to overfit with regularization and few features. With ~2,000 rows,
   a flexible model would happily memorize the season.

A more flexible model earns consideration only after this one has been beaten
honestly on held-out data.

NUMERICAL NOTES
---------------
The sigmoid is computed in a branch-stable form because exp(-z) overflows for large
negative z. L2 regularization deliberately excludes the intercept -- penalizing it
would bias predictions away from the base rate for no principled reason.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# Defaults chosen by a documented sweep on the validation split, not by intuition.
# The first attempt used learning_rate=0.1 with patience=20 and stopped at epoch 3
# with near-zero weights, which looked exactly like "there is no signal in this
# data". There was signal; the optimizer had simply not moved yet. That failure
# mode is worth remembering: an under-trained model and a genuinely useless one
# produce the same flat result, and only a sweep distinguishes them.
DEFAULT_LEARNING_RATE = 0.3
DEFAULT_EPOCHS = 6000
DEFAULT_L2 = 1.0

# Improvement smaller than this counts as no improvement. Patience must be large
# enough to survive the plateau every gradient-descent run passes through early on.
CONVERGENCE_TOLERANCE = 1e-8
DEFAULT_PATIENCE = 300

_PROB_EPSILON = 1e-15


class ModelError(ValueError):
    """Raised when a model cannot be fitted, used, or loaded."""


def sigmoid(z: float) -> float:
    """Numerically stable logistic function.

    The naive 1/(1+exp(-z)) overflows for z around -750. Branching on the sign keeps
    the exponent negative in both cases.
    """
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def predict_one(weights, intercept, vector) -> float:
    if len(weights) != len(vector):
        raise ModelError(
            f"model expects {len(weights)} features, got {len(vector)}"
        )
    return sigmoid(intercept + sum(w * x for w, x in zip(weights, vector)))


def predict(model, matrix) -> list:
    """Predicted probabilities for a matrix of already-scaled rows."""
    weights, intercept = model["weights"], model["intercept"]
    return [predict_one(weights, intercept, row) for row in matrix]


def log_loss(probabilities, labels) -> float:
    if len(probabilities) != len(labels):
        raise ModelError("probabilities and labels must be the same length")
    if not labels:
        raise ModelError("no labels to score")
    total = 0.0
    for p, y in zip(probabilities, labels):
        p = min(max(p, _PROB_EPSILON), 1.0 - _PROB_EPSILON)
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / len(labels)


def fit(matrix, labels, learning_rate: float = DEFAULT_LEARNING_RATE,
        epochs: int = DEFAULT_EPOCHS, l2: float = DEFAULT_L2,
        val_matrix=None, val_labels=None, patience: int = DEFAULT_PATIENCE,
        verbose: bool = False) -> dict:
    """Fit by batch gradient descent on scaled features.

    When a validation split is supplied, the epoch with the best validation loss is
    kept rather than the final epoch. Returning the last epoch would hand back a
    model that has started memorizing the training split.
    """
    if not matrix:
        raise ModelError("cannot fit on an empty matrix")
    if len(matrix) != len(labels):
        raise ModelError(
            f"matrix has {len(matrix)} rows but there are {len(labels)} labels"
        )
    if not (0 < learning_rate <= 10):
        raise ModelError(f"learning_rate out of range: {learning_rate!r}")
    if l2 < 0:
        raise ModelError(f"l2 must not be negative: {l2!r}")

    n, width = len(matrix), len(matrix[0])
    weights = [0.0] * width
    intercept = 0.0

    history = []
    best = None
    best_val = None
    stale = 0

    for epoch in range(epochs):
        predictions = [predict_one(weights, intercept, row) for row in matrix]

        # Gradient of mean log loss. For logistic regression the derivative of the
        # loss with respect to the linear output is simply (prediction - label).
        errors = [p - y for p, y in zip(predictions, labels)]
        intercept_grad = sum(errors) / n
        weight_grads = [
            sum(errors[i] * matrix[i][j] for i in range(n)) / n + l2 * weights[j]
            for j in range(width)
        ]

        intercept -= learning_rate * intercept_grad
        for j in range(width):
            weights[j] -= learning_rate * weight_grads[j]

        train_loss = log_loss(predictions, labels)
        entry = {"epoch": epoch, "train_loss": train_loss}

        if val_matrix is not None and val_labels is not None:
            val_loss = log_loss(
                [predict_one(weights, intercept, row) for row in val_matrix],
                val_labels,
            )
            entry["val_loss"] = val_loss
            if best_val is None or val_loss < best_val - CONVERGENCE_TOLERANCE:
                best_val = val_loss
                best = {"weights": list(weights), "intercept": intercept,
                        "epoch": epoch, "val_loss": val_loss}
                stale = 0
            else:
                stale += 1
        else:
            if history and abs(history[-1]["train_loss"] - train_loss) < CONVERGENCE_TOLERANCE:
                stale += 1
            else:
                stale = 0

        history.append(entry)
        if verbose and epoch % 200 == 0:
            print(f"  epoch {epoch:>5}  train {train_loss:.5f}"
                  + (f"  val {entry['val_loss']:.5f}" if "val_loss" in entry else ""))
        if stale >= patience:
            break

    used_early_stop = best is not None
    final_weights = best["weights"] if used_early_stop else weights
    final_intercept = best["intercept"] if used_early_stop else intercept

    return {
        "weights": final_weights,
        "intercept": final_intercept,
        "epochs_run": len(history),
        "best_epoch": best["epoch"] if used_early_stop else len(history) - 1,
        "final_train_loss": history[-1]["train_loss"],
        "best_val_loss": best_val,
        "early_stopped": used_early_stop and best["epoch"] < len(history) - 1,
        "hyperparameters": {
            "learning_rate": learning_rate, "epochs": epochs,
            "l2": l2, "patience": patience,
        },
        "history": history,
    }


def coefficients(model, feature_names) -> list:
    """Feature weights sorted by absolute magnitude.

    On scaled features these are directly comparable: a weight of 0.4 moves the
    log-odds twice as much per standard deviation as a weight of 0.2. Sign says
    direction -- positive favours the home team, since the label is home_won.
    """
    weights = model["weights"]
    if len(weights) != len(feature_names):
        raise ModelError(
            f"model has {len(weights)} weights but {len(feature_names)} names"
        )
    pairs = [
        {"feature": name, "weight": round(w, 6), "abs_weight": abs(w)}
        for name, w in zip(feature_names, weights)
    ]
    pairs.sort(key=lambda p: p["abs_weight"], reverse=True)
    return pairs


def save(model, scaler, features, path, metadata=None) -> str:
    """Persist a model with everything needed to reproduce a prediction.

    The scaler is stored alongside the weights on purpose: a model applied to
    unscaled features silently produces nonsense rather than failing, so the two
    must never be separable.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "weights": model["weights"],
        "intercept": model["intercept"],
        "features": list(features),
        "scaler": scaler,
        "hyperparameters": model.get("hyperparameters"),
        "best_epoch": model.get("best_epoch"),
        "best_val_loss": model.get("best_val_loss"),
        "metadata": metadata or {},
        # Anything consuming a probability must be able to see this.
        "calibrated": False,
        "calibration_note": (
            "Fitted, but not validated against a market baseline. Historical "
            "closing odds are required to answer whether this beats the market, "
            "and none have been acquired. Do not treat these probabilities as "
            "an edge."
        ),
    }
    target.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return str(target)


def load(path) -> dict:
    target = Path(path)
    if not target.exists():
        raise ModelError(f"no model at {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelError(f"model at {target} is not valid JSON") from exc
    for key in ("weights", "intercept", "features", "scaler"):
        if key not in payload:
            raise ModelError(f"model at {target} is missing {key!r}")
    return payload
