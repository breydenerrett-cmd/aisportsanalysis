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
from src.paths import evidence_path
from src.pipeline import snapshots

# Tracked, not under data/. A prediction is evidence only because it was written down
# before the game; gitignoring it means the record vanishes with the working copy and
# the CLV plan restarts from zero with nothing to show it ever ran. See evidence_path.
DEFAULT_LOG = evidence_path("predictions.jsonl")

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

    `snapshots.game_key` (via `group_by_game`) already canonicalizes both team
    fields to this project's abbreviations -- it has to, to bucket the odds
    feed's full club names ('St. Louis Cardinals') together with anything
    keyed by abbreviation. So the away/home slots of `key` below are already
    resolved; this function no longer runs its own second pass over them.
    """
    index = {}
    if not snapshot_rows:
        return index
    for key, series in snapshots.group_by_game(snapshot_rows).items():
        away, home, day = key
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


# ---------------------------------------------------------------------------
# Forward-ledger closing-price backfill
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS
# ----------------
# Commit 65f499a fixed `snapshots.game_key` to canonicalize club names on
# both sides of the settlement-closing join (see
# tests/test_settlement_closing_join.py): ledger rows carry this project's
# abbreviations, the snapshot store carries the odds feed's full club
# names, and the join compared the two literally for months. The fix
# cannot repair a row already on disk -- forward-ledger settlements are
# immutable evidence (src/pipeline/ledger.py's module docstring: appended,
# never modified) -- so a settlement written before the fix keeps
# `closing: null` forever. What CAN change is whether that null is still
# explained by a real gap or was only ever the join bug;
# `cli.cmd_closing_audit` answers that, read-only. This section is the
# write side: for every settlement whose close the fixed join can now
# find, append one `closing_backfill` row recording the derived close,
# where it came from, and the CLV it implies -- never touching the
# original settlement line.
#
# WHY THE SAME DEFINITION AS `cli._settlement_closing`, NOT `_find_series`
# -------------------------------------------------------------------------
# `_index_snapshots`/`_find_series` above power a different, deliberately
# more forgiving join (date-tolerant, reused as-is by the prediction log's
# CLV and by src.appstate.settlement's saved-bet closing price -- see that
# module's docstring). Re-checked against the live store, that tolerance
# finds a series for settlements that `cli._settlement_closing`'s exact
# `game_key` match reports as "no snapshots recorded for this game" -- the
# two joins can disagree about whether a close exists at all for the same
# row. `cmd_closing_audit` -- the tool this backfill has to agree with --
# is built on `_settlement_closing`, so the backfill re-derives the close
# the same way it does: `snapshots.game_key` + `group_by_game` +
# `closing_observation`, no date slack. Using the looser join here would
# silently attach a different game's price than closing-audit reported as
# derivable, or backfill a row closing-audit calls genuinely absent.
#
# WHY CLV IS H2H-ONLY HERE
# -------------------------
# A settlement's `closing` has only ever been an h2h observation --
# `_settlement_closing` records it for every recommendation regardless of
# which market (if any) was flagged, because h2h is the only market this
# join identifies at all. So CLV here is computed only from the h2h price
# recorded on the recommendation (`prices.h2h.<side>_price`, the board as
# it stood when the recommendation was written) against the h2h close --
# never against a first_five/spreads/totals pick price, which would
# silently compare two different markets. Extending closing identification
# itself to those markets is explicitly a separate lane; this backfill
# does not start it.

BACKFILL = "closing_backfill"
CLOSING_SOURCE = "odds_snapshots"
BACKFILL_REASON = "abbreviation join bug 65f499a"


def find_backfillable_closings(ledger_entries, snapshot_rows, *, now=None) -> dict:
    """What can be appended right now, without appending anything.

    Pure and side-effect free -- `closing-backfill --dry-run` and the real
    run share this exact computation, so a dry run can never claim
    something the real run then fails to produce, and calling it twice
    with the same inputs is safe (idempotent by construction: a settlement
    already covered by a valid backfill is reported under
    `already_backfilled`, not re-added to `to_append`).

    Returns a dict:
      to_append           -- new `closing_backfill` row dicts, one per
                              newly-derivable settlement, ready to append.
      derivable           -- [{game_pk, away_team, home_team, date,
                              closing}] for null-original settlements not
                              yet backfilled whose close IS now findable.
      not_derivable       -- [{game_pk, away_team, home_team, date,
                              reason}] for null-original settlements not
                              yet backfilled whose close still is not
                              findable, with `_settlement_closing`'s own
                              reason string (so this list's reasons read
                              identically to `closing-audit`'s).
      already_backfilled  -- game_pks that already carry a valid backfill
                              row and are skipped.
      no_recommendation   -- game_pks with a null-original settlement but
                              no matching recommendation row to join with.
    """
    from src.pipeline import ledger  # local: no cycle (ledger never imports
                                      # grading) -- kept local so this
                                      # module's own import list, read top
                                      # to bottom, still describes what it
                                      # needs for its OWN primary job (the
                                      # prediction-log CLV path above).

    settled = ledger.settlements(ledger_entries)
    recs_by_pk = {r.get("game_pk"): r for r in ledger.recommendations(ledger_entries)}
    already = read_backfills(ledger_entries)
    snapshot_series = snapshots.group_by_game(snapshot_rows)
    stamp = _timestamp(now)

    to_append, derivable, not_derivable = [], [], []
    already_backfilled, no_recommendation = [], []

    for pk, settlement in settled.items():
        if settlement.get("closing") is not None:
            continue  # never touch a settlement that already has a close
        if pk in already:
            already_backfilled.append(pk)
            continue
        rec = recs_by_pk.get(pk)
        if rec is None:
            no_recommendation.append(pk)
            continue

        closing, reason = _ledger_closing(rec, snapshot_series)
        identity = {"game_pk": pk, "away_team": rec.get("away_team"),
                    "home_team": rec.get("home_team"), "date": rec.get("date")}
        if closing is None:
            not_derivable.append({**identity, "reason": reason})
            continue

        derivable.append({**identity, "closing": closing})
        to_append.append(_backfill_row(pk, rec, closing, stamp))

    return {
        "to_append": to_append,
        "derivable": derivable,
        "not_derivable": not_derivable,
        "already_backfilled": already_backfilled,
        "no_recommendation": no_recommendation,
    }


def _ledger_closing(rec, snapshot_series):
    """(closing, reason) for one recommendation row -- the exact same
    definition, and the exact same reason strings, as
    `cli._settlement_closing`. Duplicated rather than imported: cli.py is
    the entry point that calls into this pipeline layer, not the other way
    around, so it must never be imported from here.
    """
    key = snapshots.game_key(rec.get("away_team"), rec.get("home_team"),
                             rec.get("commence_time"))
    series = snapshot_series.get(key)
    if not series:
        return None, "no snapshots recorded for this game"
    observation = snapshots.closing_observation(series, rec.get("commence_time"))
    if observation is None:
        return None, "no snapshot observed before first pitch"
    return {
        "market": "h2h",
        "book": observation.get("book"),
        "observed_utc": observation.get("observed_utc"),
        "book_last_update": observation.get("book_last_update"),
        "book_stale_seconds": observation.get("book_stale_seconds"),
        "book_stale": observation.get("book_stale"),
        "prices": observation.get("prices"),
    }, None


def _ledger_clv(rec, closing) -> dict:
    """CLV for a backfilled settlement, off the h2h price only (see module
    note above). Same shape and vocabulary as `_closing_line_value` so a
    reader already familiar with `clv_graded`/`clv_reason` recognizes this
    immediately as the same kind of fact.
    """
    side = rec.get("side")
    if side not in ("home", "away"):
        return {"clv_graded": False,
                "clv_reason": "no side recorded on the recommendation"}
    field = "home_price" if side == "home" else "away_price"
    pick_price = ((rec.get("prices") or {}).get("h2h") or {}).get(field)
    if pick_price is None:
        return {"clv_graded": False,
                "clv_reason": "no h2h price recorded on the recommendation"}
    closing_price = (closing.get("prices") or {}).get(field)
    if closing_price is None:
        return {"clv_graded": False,
                "clv_reason": f"closing snapshot has no {field}"}
    try:
        value = snapshots.closing_line_value(pick_price, closing_price)
    except odds_math.OddsError as exc:
        return {"clv_graded": False, "clv_reason": f"unusable prices: {exc}"}
    return {"clv_graded": True, "clv_side": side, **value}


def _backfill_row(game_pk, rec, closing, stamp) -> dict:
    """One `closing_backfill` row: the derived close, its provenance, and
    the CLV it implies. `ref` is the settlement's `game_pk` -- its
    identifier in `ledger.settlements()`'s keying, and today also unique
    per settlement (see tests/test_pipeline_ledger.py; no game is settled
    twice in the live ledger) -- so it names exactly which immutable row
    this corrects without touching it.
    """
    return {
        "kind": BACKFILL,
        "ref": game_pk,
        "closing_price": closing,
        "closing_observed_utc": closing.get("observed_utc"),
        "closing_source": CLOSING_SOURCE,
        "derived_utc": stamp,
        "clv": _ledger_clv(rec, closing),
        "reason": BACKFILL_REASON,
    }


def read_backfills(ledger_entries) -> dict:
    """Valid `closing_backfill` rows, keyed by the settlement `ref` (game_pk)
    they correct. This is the one place that decides "prefer the backfill
    when the original is null" -- every reader of a ledger closing should
    call this (or `effective_closing`, below) rather than re-deriving the
    rule, so the preference can never be implemented two different ways.

    First valid row per ref wins (same rule as `deduplicate`'s
    first-prediction-per-game, above: the earliest record is the one
    actually checked against the store at the time; a later duplicate adds
    nothing, and a later CONFLICTING one is exactly the silent overwrite
    this function exists to refuse).

    A row is valid only if:
      * `ref` names a settlement that actually exists in this same set of
        entries, AND that settlement's own `closing` is still null (a
        backfill can never override, or appear to correct, a settlement
        that already has a real close -- a tampered or stale row claiming
        otherwise is ignored outright, never trusted); and
      * it carries a non-null `closing_price`.

    Anything else -- an orphaned `ref`, a row targeting an already-closed
    settlement, a second row for a `ref` already covered -- is silently
    excluded. It is not an error: the ledger is append-only, so a bad row
    already on disk cannot be deleted, only out-voted by this rule.
    """
    from src.pipeline import ledger

    settled_closing = {}
    for entry in ledger_entries:
        if entry.get("kind") == ledger.SETTLEMENT:
            settled_closing[entry.get("game_pk")] = entry.get("closing")

    valid = {}
    for entry in ledger_entries:
        if entry.get("kind") != BACKFILL:
            continue
        ref = entry.get("ref")
        if ref in valid:
            continue  # first valid row per ref wins; later ones ignored
        if entry.get("closing_price") is None:
            continue
        if ref not in settled_closing or settled_closing[ref] is not None:
            continue  # no such settlement, or its original was never null
        valid[ref] = entry
    return valid


def effective_closing(settlement, backfills):
    """The closing dict a reader should use for one settlement row: its own
    `closing` when that is not null, else a valid backfill's
    `closing_price`, else None. `backfills` is `read_backfills`'s return
    value -- already excludes anything that would try to override a
    non-null original, so this function does not need to re-check that.
    """
    original = settlement.get("closing")
    if original is not None:
        return original
    backfill = backfills.get(settlement.get("game_pk"))
    return backfill["closing_price"] if backfill else None


def ledger_closing_coverage(ledger_entries) -> dict:
    """Rows with a closing price (original or backfill) over settled rows,
    grouped by the recommendation's own `market` field.

    The close itself is always h2h (see module note above); grouping by
    the RECOMMENDATION's market and reporting each group separately is
    what keeps this honest -- a single blended percentage would hide, for
    example, every first_five settlement staying uncovered behind a large
    no-play bucket that is fully covered.
    """
    from src.pipeline import ledger

    recs_by_pk = {r.get("game_pk"): r for r in ledger.recommendations(ledger_entries)}
    settled = ledger.settlements(ledger_entries)
    backfills = read_backfills(ledger_entries)

    by_market = {}
    for pk, settlement in settled.items():
        rec = recs_by_pk.get(pk)
        market = (rec.get("market") if rec else None) or "unspecified (no_play/market_unavailable)"
        bucket = by_market.setdefault(
            market, {"settled": 0, "with_closing": 0, "from_original": 0, "from_backfill": 0})
        bucket["settled"] += 1
        if settlement.get("closing") is not None:
            bucket["with_closing"] += 1
            bucket["from_original"] += 1
        elif pk in backfills:
            bucket["with_closing"] += 1
            bucket["from_backfill"] += 1
    return by_market


def append_ledger_rows(rows, path) -> None:
    """Append `closing_backfill` rows to the forward ledger file, in the
    exact on-disk format `ledger._append_entries` writes (sorted keys,
    ragged-trailing-newline repair) so a backfill row is byte-for-byte
    consistent with every `recommendation`/`settlement` row already there.
    Never opens the file for anything but appending -- see CLAUDE.md and
    ledger.py's own module docstring: this store is evidence.
    """
    if not rows:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ragged = False
    if target.exists() and target.stat().st_size:
        with target.open("rb") as handle:
            handle.seek(-1, 2)
            ragged = handle.read(1) != b"\n"
    with target.open("a", encoding="utf-8") as handle:
        if ragged:
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
