"""Prediction log and settlement. The evidence engine.

WHY AN APPEND-ONLY PREDICTION LOG
---------------------------------
A prediction is only evidence if it was recorded BEFORE the game. A file that can be
edited after the fact is not a record, it is a draft -- and the temptation to quietly
adjust a prediction that aged badly is exactly what this log exists to remove.

So predictions are appended, never modified. Settlement writes to separate result
fields and never back over the original. If a prediction was wrong, the log says so
permanently.

WHAT IS GRADED AND WHAT IS NOT
------------------------------
Only genuinely final games. A postponed game is not a loss, a suspended game is not a
push, and an in-progress game is nothing at all. Each gets its own status so the
report can distinguish "we were wrong" from "this never resolved".

CLOSING LINE VALUE IS THE PRIMARY METRIC
----------------------------------------
Not win rate, not ROI. CLV -- whether a prediction was recorded at a better price than
the market closed at -- converges roughly ten times faster than ROI and is what
separates finding real inefficiency from running hot.

A prediction with no captured closing line is reported as ungraded for CLV rather than
being compared against the nearest available price. Substituting a stand-in would
corrupt the one metric the whole validation plan rests on.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.core import odds as odds_math
from src.pipeline import snapshots

DEFAULT_LOG = Path("data/processed/predictions.jsonl")

# Thresholds from docs/VALIDATION_CRITERIA.md, pre-registered before any results
# existed. Restated here so the code and the document cannot drift apart.
MIN_SAMPLE_FOR_ANY_VERDICT = 300
MIN_SAMPLE_FOR_TREND = 100
CLV_PASS_BEAT_RATE = 0.55
CLV_PASS_MEAN = 0.015


class GradingError(RuntimeError):
    """Raised when predictions cannot be logged, read, or settled."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_predictions(predictions, path=DEFAULT_LOG, model_version=None,
                    now=None) -> dict:
    """Append predictions to the immutable log.

    Each entry records the price available AT PREDICTION TIME. That price is what CLV
    is measured against later, so it must be captured now -- it cannot be recovered
    once the market moves.
    """
    usable = [p for p in predictions if p.get("usable")]
    if not usable:
        return {"logged": 0, "skipped": len(predictions), "path": str(path)}

    stamp = _timestamp(now)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with target.open("a", encoding="utf-8") as handle:
        for prediction in usable:
            entry = {
                "logged_utc": stamp,
                "model_version": model_version,
                "game_pk": prediction.get("game_pk"),
                "date": prediction.get("date"),
                "away_team": prediction.get("away_team"),
                "home_team": prediction.get("home_team"),
                "home_probability": prediction.get("home_probability"),
                "away_price_at_prediction": prediction.get("away_price"),
                "home_price_at_prediction": prediction.get("home_price"),
                "market_home_fair": prediction.get("market_home_fair"),
                "disagreement_home": prediction.get("disagreement_home"),
                "model_favours": prediction.get("model_favours"),
                # Whether the slate-level diagnostic said this ranking was
                # trustworthy. Recorded so a later review can separate predictions
                # made under a warning from those made without one.
                "ranking_was_meaningful": prediction.get("ranking_was_meaningful"),
            }
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
            written += 1

    return {"logged": written, "skipped": len(predictions) - written,
            "path": str(target), "logged_utc": stamp}


def read_log(path=DEFAULT_LOG) -> list:
    """Read every logged prediction. A truncated final line costs one entry."""
    target = Path(path)
    if not target.exists():
        return []
    entries = []
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def deduplicate(entries) -> list:
    """Keep the FIRST prediction for each game.

    Re-running predict on the same slate appends again. The first entry is the one
    made with the least information and the earliest price, so it is the honest one to
    grade. Keeping the last would let a prediction be improved after the market moved.
    """
    seen, kept = set(), []
    for entry in entries:
        key = (entry.get("game_pk"), entry.get("model_version"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)
    return kept


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

def settle(entries, results_store, snapshot_rows=None) -> dict:
    """Grade logged predictions against final results.

    Returns graded entries plus counts by status. A prediction whose game is not final
    is `pending`, not wrong -- conflating the two would make the record look worse or
    better than it is depending on when the report happened to run.
    """
    graded, pending, unresolved = [], [], []

    by_game = _index_snapshots(snapshot_rows)

    for entry in entries:
        game = results_store.get(str(entry.get("game_pk")))
        if game is None:
            pending.append({**entry, "status": "pending",
                            "reason": "game not in results store"})
            continue

        home_won = game.get("home_won")
        if home_won in (None, ""):
            unresolved.append({**entry, "status": "unresolved",
                               "reason": "game has no decided winner"})
            continue

        home_won = int(home_won)
        probability = entry.get("home_probability")
        if probability is None:
            unresolved.append({**entry, "status": "unresolved",
                               "reason": "no model probability logged"})
            continue

        record = {
            **entry,
            "status": "graded",
            "home_won": home_won,
            "predicted_home": probability > 0.5,
            "correct": (probability > 0.5) == bool(home_won),
            "brier": round((probability - home_won) ** 2, 6),
        }

        clv = _closing_line_value(entry, by_game)
        record.update(clv)
        graded.append(record)

    return {
        "graded": graded,
        "pending": pending,
        "unresolved": unresolved,
        "counts": {
            "graded": len(graded),
            "pending": len(pending),
            "unresolved": len(unresolved),
        },
    }


def _closing_line_value(entry, snapshots_by_game) -> dict:
    """CLV for one prediction, or an explicit reason it could not be computed."""
    side = entry.get("model_favours")
    price = (entry.get("home_price_at_prediction") if side == "home"
             else entry.get("away_price_at_prediction"))
    if side is None or price is None:
        return {"clv_graded": False,
                "clv_reason": "no price recorded at prediction time"}

    series = _find_series(snapshots_by_game, entry.get("away_team"),
                          entry.get("home_team"), entry.get("date"))
    if not series:
        return {"clv_graded": False,
                "clv_reason": "no odds snapshots captured for this game"}

    closing = snapshots.closing_observation(series)
    if closing is None:
        return {"clv_graded": False,
                "clv_reason": "no snapshot taken before first pitch"}

    field = "home_price" if side == "home" else "away_price"
    closing_price = (closing.get("prices") or {}).get(field)
    if closing_price is None:
        return {"clv_graded": False,
                "clv_reason": f"closing snapshot has no {field}"}

    try:
        value = snapshots.closing_line_value(price, closing_price)
    except odds_math.OddsError as exc:
        return {"clv_graded": False, "clv_reason": f"unusable prices: {exc}"}

    return {
        "clv_graded": True,
        "clv_side": side,
        "clv_price_taken": price,
        "clv_closing_price": closing_price,
        "clv_cents": value["cents"],
        "clv_prob_edge": value["prob_edge"],
        "clv_beat_close": value["beat_close"],
    }


# The odds feed timestamps games in UTC; MLB assigns an official (local) date. A
# game starting 01:45 UTC on the 28th has an official date of the 27th, so keying
# snapshots by the UTC date misses EVERY West Coast night game -- a large and
# systematic class, failing silently. Matching therefore allows the two dates to
# differ by up to a day.
MAX_DATE_OFFSET_DAYS = 1


def _index_snapshots(snapshot_rows) -> dict:
    """Index snapshot series by (away_abbrev, home_abbrev) -> [(date, series)].

    Deliberately NOT keyed by date, because the date is exactly what disagrees
    between the two sources.
    """
    index = {}
    if not snapshot_rows:
        return index
    for key, series in snapshots.group_by_game(snapshot_rows).items():
        away_name, home_name, day = key
        away, home = _abbrev(away_name), _abbrev(home_name)
        if away and home:
            index.setdefault((away, home), []).append((day, series))
    return index


def _find_series(index, away, home, game_date):
    """Find the snapshot series for a game, tolerating the UTC/official date gap.

    Returns None rather than a loose match when nothing lands inside the tolerance.
    A wrong series would attach another game's closing price, which is worse than
    leaving CLV ungraded.
    """
    from src.data.parks import canonical_team
    if not (away and home and game_date):
        return None
    candidates = index.get((canonical_team(away), canonical_team(home)))
    if not candidates:
        return None

    try:
        target = date.fromisoformat(game_date)
    except (TypeError, ValueError):
        return None

    best, best_gap = None, None
    for day, series in candidates:
        try:
            gap = abs((date.fromisoformat(day) - target).days)
        except (TypeError, ValueError):
            continue
        if gap <= MAX_DATE_OFFSET_DAYS and (best_gap is None or gap < best_gap):
            best, best_gap = series, gap
    return best


def _abbrev(club_name):
    """Resolve an odds-feed club name to this project's canonical abbreviation.

    Reuses the single resolver in slate rather than adding a second mapping. Two
    mappings that agree today drift apart later, and the failure is silent.
    """
    from src.pipeline import slate
    return slate.team_abbrev_from_name(club_name)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(settled) -> dict:
    """Summarise graded predictions, with sample-size honesty built in.

    Every aggregate carries its sample size, and the verdict field refuses to draw a
    conclusion below the pre-registered threshold no matter how good the numbers look.
    """
    graded = settled["graded"]
    n = len(graded)
    if not n:
        return {
            "n": 0, "verdict": "no graded predictions yet",
            "can_conclude": False,
            "note": "Nothing has settled. This is the expected state early on.",
        }

    correct = sum(1 for g in graded if g["correct"])
    brier = sum(g["brier"] for g in graded) / n

    clv_graded = [g for g in graded if g.get("clv_graded")]
    clv_n = len(clv_graded)
    beat = sum(1 for g in clv_graded if g["clv_beat_close"])
    mean_clv = (sum(g["clv_prob_edge"] for g in clv_graded) / clv_n
                if clv_n else None)

    can_conclude = clv_n >= MIN_SAMPLE_FOR_ANY_VERDICT
    can_describe_trend = clv_n >= MIN_SAMPLE_FOR_TREND

    if can_conclude:
        beat_rate = beat / clv_n
        passes = beat_rate >= CLV_PASS_BEAT_RATE and (mean_clv or 0) >= CLV_PASS_MEAN
        verdict = ("CLV criteria met" if passes else "CLV criteria NOT met")
    elif can_describe_trend:
        verdict = (f"trend only -- {clv_n} CLV-graded predictions, "
                   f"{MIN_SAMPLE_FOR_ANY_VERDICT} needed for a verdict")
    else:
        verdict = (f"far too few to say anything -- {clv_n} CLV-graded, "
                   f"{MIN_SAMPLE_FOR_ANY_VERDICT} needed")

    return {
        "n": n,
        "accuracy": round(correct / n, 4),
        "brier": round(brier, 6),
        "clv_n": clv_n,
        "clv_beat_rate": round(beat / clv_n, 4) if clv_n else None,
        "clv_mean_prob_edge": round(mean_clv, 6) if mean_clv is not None else None,
        "clv_ungraded": n - clv_n,
        "clv_ungraded_reasons": _reason_counts(graded),
        "can_conclude": can_conclude,
        "can_describe_trend": can_describe_trend,
        "verdict": verdict,
        "thresholds": {
            "min_sample": MIN_SAMPLE_FOR_ANY_VERDICT,
            "beat_rate": CLV_PASS_BEAT_RATE,
            "mean_clv": CLV_PASS_MEAN,
        },
        "note": (
            "Accuracy and Brier are reported for completeness but are NOT the "
            "criteria. CLV is, because it converges far faster and measures whether "
            "real inefficiency was found rather than whether the coin landed right."
        ),
    }


def _reason_counts(graded) -> dict:
    counts = {}
    for entry in graded:
        if entry.get("clv_graded"):
            continue
        reason = entry.get("clv_reason", "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _timestamp(now=None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()
