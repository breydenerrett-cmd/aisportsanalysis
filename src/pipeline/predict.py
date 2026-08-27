"""Apply a fitted model to upcoming games and compare it against the market.

WHAT THIS PRODUCES AND WHAT IT DOES NOT
---------------------------------------
It produces DISAGREEMENT: the gap between the model's probability and the market's
de-vigged probability for each game.

Disagreement is not edge. Edge means being right more often than the price implies,
and that is a claim about the future which only settled results can support. A model
that disagrees with the market is, on the available evidence, simply a model that is
wrong in a different direction than the market is.

Every output here is therefore framed as a comparison, never as a recommendation. The
`edge` field is deliberately named `disagreement` for the same reason nothing is called
xFIP: the label is what people remember.

WHY THE FEATURE PATH IS SHARED WITH TRAINING
--------------------------------------------
Predictions are built through exactly the same functions that built the training rows.
If prediction-time features were assembled by a second code path -- even one that looks
equivalent -- any divergence between them would silently degrade every prediction while
both paths individually appeared correct. Training/serving skew is a classic and
extremely hard bug to see, and the cheapest defence is to have only one path.
"""

from __future__ import annotations

from src.core import odds as odds_math
from src.model import logistic
from src.pipeline import features as feature_builder
from src.pipeline import pitchers as pitcher_builder


class PredictionError(RuntimeError):
    """Raised when a prediction cannot be produced."""


def predict_game(model_payload, store, game, pitcher_logs=None,
                 fip_constant=None) -> dict:
    """Model probability for one upcoming game.

    `game` is a parsed schedule record. Its own outcome is naturally unavailable, and
    the point-in-time accessors would exclude it anyway.
    """
    away = game.get("away_team")
    home = game.get("home_team")
    game_date = game.get("date")
    if not (away and home and game_date):
        raise PredictionError(
            f"game {game.get('game_pk')!r} is missing teams or a date"
        )

    row = feature_builder.matchup_features(store, away, home, game_date)
    if pitcher_logs is not None:
        row.update(pitcher_builder.matchup_pitcher_features(
            pitcher_logs, game.get("away_probable_id"),
            game.get("home_probable_id"), game_date, fip_constant=fip_constant,
        ))

    expected = model_payload["features"]
    missing = [f for f in expected if row.get(f) is None]
    if missing:
        return {
            "game_pk": game.get("game_pk"),
            "away_team": away, "home_team": home, "date": game_date,
            "home_probability": None,
            "usable": False,
            "reason": (
                f"{len(missing)} required feature(s) unavailable: "
                f"{', '.join(missing[:4])}"
                + ("..." if len(missing) > 4 else "")
            ),
            "missing_features": missing,
        }

    scaler = model_payload["scaler"]
    vector = [float(row[f]) for f in expected]
    scaled = [
        (value - scaler["means"][i]) / scaler["stds"][i]
        for i, value in enumerate(vector)
    ]
    probability = logistic.predict_one(
        model_payload["weights"], model_payload["intercept"], scaled
    )

    return {
        "game_pk": game.get("game_pk"),
        "away_team": away, "home_team": home, "date": game_date,
        "start_time_utc": game.get("start_time_utc"),
        "away_probable": game.get("away_probable"),
        "home_probable": game.get("home_probable"),
        "home_probability": round(probability, 6),
        "away_probability": round(1.0 - probability, 6),
        "usable": True,
        "reason": None,
    }


def compare_to_market(prediction, away_price, home_price,
                      method: str = "proportional") -> dict:
    """Compare a model probability against the DE-VIGGED market price.

    The de-vig is not optional and is not done by the caller. Comparing against raw
    implied probability overstates disagreement on favourites, which is exactly where
    a betting system is most likely to convince itself it has found something.
    """
    if prediction.get("home_probability") is None:
        return {**prediction, "comparable": False,
                "reason": prediction.get("reason") or "no model probability"}

    try:
        away_fair, home_fair = odds_math.devig_two_way(
            away_price, home_price, method=method)
    except odds_math.OddsError as exc:
        return {**prediction, "comparable": False,
                "reason": f"market prices unusable: {exc}"}

    home_model = prediction["home_probability"]
    disagreement_home = home_model - home_fair

    return {
        **prediction,
        "comparable": True,
        "away_price": away_price,
        "home_price": home_price,
        "market_home_fair": round(home_fair, 6),
        "market_away_fair": round(away_fair, 6),
        "market_margin": round(
            odds_math.margin([away_price, home_price]), 6),
        # Named "disagreement", never "edge". Edge is a claim about being right,
        # which nothing here has established.
        "disagreement_home": round(disagreement_home, 6),
        "disagreement_abs": round(abs(disagreement_home), 6),
        "model_favours": "home" if disagreement_home > 0 else "away",
        "devig_method": method,
    }


def disagreement_is_robust(prediction, away_price, home_price,
                           methods=("proportional", "shin", "power")) -> dict:
    """Check whether the disagreement survives every de-vig method.

    Different methods distribute the bookmaker's margin differently, and on lopsided
    markets they diverge meaningfully. A disagreement that appears under one method and
    vanishes under another is an artefact of that choice rather than a property of the
    model, and treating it as real is a way to manufacture signal from arithmetic.
    """
    results = {}
    for method in methods:
        compared = compare_to_market(prediction, away_price, home_price,
                                     method=method)
        if not compared.get("comparable"):
            return {"robust": False, "reason": compared.get("reason"),
                    "by_method": results}
        results[method] = compared["disagreement_home"]

    values = list(results.values())
    same_side = all(v > 0 for v in values) or all(v < 0 for v in values)
    return {
        "robust": same_side,
        "by_method": {k: round(v, 6) for k, v in results.items()},
        "spread": round(max(values) - min(values), 6),
        "min_abs": round(min(abs(v) for v in values), 6),
        "reason": None if same_side else
                  "de-vig methods disagree on which side the model favours",
    }


def ignorance_check(comparisons) -> dict:
    """Detect the failure mode where disagreement is driven by market confidence.

    THE TRAP THIS EXISTS TO CATCH.

    A model with little discriminative power sits near the base rate on every game --
    say 0.53 give or take a few points. The market does not: it moves to 0.75 when an
    ace faces a bullpen game, and to 0.35 the other way.

    Subtract those and the largest "disagreements" appear exactly where the market is
    most confident. It looks like the model has found the biggest mispricings. It has
    found the games it understands least. The gap is a measure of what the market knows
    and the model does not.

    Acting on that ranking is worse than betting at random, because it systematically
    selects against the market's strongest information.

    Detection: if the size of the disagreement tracks how far the market has moved from
    even money, the ranking is measuring ignorance. Reported as a correlation, with a
    flag when it is strong enough to invalidate ranking games by disagreement.
    """
    usable = [c for c in comparisons if c.get("comparable")]
    if len(usable) < 3:
        return {"checked": False,
                "reason": f"only {len(usable)} comparable game(s); need at least 3"}

    gaps = [c["disagreement_abs"] for c in usable]
    market_confidence = [abs(c["market_home_fair"] - 0.5) for c in usable]
    model_spread = _stdev([c["home_probability"] for c in usable])
    market_spread = _stdev([c["market_home_fair"] for c in usable])

    correlation = _correlation(market_confidence, gaps)

    # A model whose predictions barely vary cannot be discriminating between games,
    # whatever its calibration looks like. This alone invalidates ranking by
    # disagreement: if the model is nearly constant, the ranking is just the market's
    # ranking inverted.
    flat = model_spread < 0.5 * market_spread if market_spread > 0 else False

    # Correlation on a single slate is extremely noisy -- six games is not a sample.
    # It is reported at any size but only allowed to raise the alarm on its own once
    # there are enough games for the number to mean anything.
    correlation_is_meaningful = len(usable) >= 20
    driven_by_market = (
        correlation is not None and correlation > 0.7 and correlation_is_meaningful
    )

    reasons = []
    if flat:
        reasons.append(
            f"the model's predictions vary {round(model_spread / market_spread, 2)}x "
            "as much as the market's, so it is barely discriminating between games"
        )
    if driven_by_market:
        reasons.append(
            f"disagreement correlates {correlation:.2f} with how confident the market "
            "is, so the largest gaps are the games the model understands least"
        )

    return {
        "checked": True,
        "games": len(usable),
        "model_spread": round(model_spread, 5),
        "market_spread": round(market_spread, 5),
        "spread_ratio": (round(model_spread / market_spread, 3)
                         if market_spread > 0 else None),
        "correlation_gap_vs_market_confidence": (
            round(correlation, 4) if correlation is not None else None),
        "correlation_is_meaningful": correlation_is_meaningful,
        "model_is_flat": flat,
        "disagreement_driven_by_market": driven_by_market,
        # Either condition is disqualifying on its own. Requiring both would let a
        # nearly-constant model pass whenever one slate's correlation happened to
        # land low, which is exactly the case that most needs the warning.
        "ranking_is_meaningful": not (flat or driven_by_market),
        "warning": (
            "Ranking games by disagreement is NOT meaningful here: "
            + "; ".join(reasons)
            + ". Acting on that ranking selects against the market's strongest "
            "information, which is worse than betting at random."
        ) if reasons else None,
    }


def _stdev(values) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def _correlation(xs, ys):
    """Pearson correlation. None when either series is constant."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = (sum(v * v for v in dx) ** 0.5) * (sum(v * v for v in dy) ** 0.5)
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denominator


def predict_slate(model_payload, store, games, pitcher_logs=None,
                  odds_by_matchup=None) -> dict:
    """Predict a full slate and, where prices exist, compare against the market."""
    fip_constant = None
    if pitcher_logs is not None:
        latest = max((g.get("date") or "" for g in games), default="2100-01-01")
        fip_constant = pitcher_builder.league_fip_constant(pitcher_logs, latest)

    predictions, unusable = [], []
    for game in games:
        try:
            prediction = predict_game(model_payload, store, game,
                                      pitcher_logs=pitcher_logs,
                                      fip_constant=fip_constant)
        except PredictionError as exc:
            unusable.append({"game_pk": game.get("game_pk"), "reason": str(exc)})
            continue

        if not prediction["usable"]:
            unusable.append(prediction)
            continue

        prices = (odds_by_matchup or {}).get(
            (prediction["away_team"], prediction["home_team"]))
        if prices:
            prediction = compare_to_market(prediction, prices["away_price"],
                                           prices["home_price"])
            if prediction.get("comparable"):
                prediction["robustness"] = disagreement_is_robust(
                    prediction, prices["away_price"], prices["home_price"])
        predictions.append(prediction)

    comparable = [p for p in predictions if p.get("comparable")]
    robust = [p for p in comparable if p.get("robustness", {}).get("robust")]
    ignorance = ignorance_check(comparable)

    return {
        "ignorance_check": ignorance,
        "predictions": predictions,
        "unusable": unusable,
        "count": len(predictions),
        "comparable_count": len(comparable),
        "robust_count": len(robust),
        "largest_disagreement": (
            max((p["disagreement_abs"] for p in comparable), default=None)),
        "mean_disagreement": (
            round(sum(p["disagreement_abs"] for p in comparable) / len(comparable), 6)
            if comparable else None),
        "fip_constant": fip_constant,
        "warning": (
            "These are DISAGREEMENTS with the market, not edges. Edge means being "
            "right more often than the price implies, which requires settled results "
            "this project does not yet have. Do not bet on these."
        ),
    }
