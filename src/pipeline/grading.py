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
# WHY CLV IS H2H-ONLY -- FOR H2H ROWS
# -------------------------------------
# A settlement's `closing` has only ever been an h2h observation --
# `_settlement_closing` records it for every recommendation regardless of
# which market (if any) was flagged, because h2h is the only market this
# join identifies at all. So CLV on an h2h backfill row is computed only
# from the h2h price recorded on the recommendation
# (`prices.h2h.<side>_price`, the board as it stood when the
# recommendation was written) against the h2h close -- never against a
# first_five/spreads/totals pick price, which would silently compare two
# different markets.
#
# L18 EXTENDS THE BACKFILL TO SPREADS AND TOTALS -- CLV STAYS NULL THERE
# ------------------------------------------------------------------------
# `market=` below lets this same mechanism record a spreads or totals
# close too (same store, same PIT rule, via `snapshots.market_closing_observation`
# -- the identical lookup `grading.ledger_closing_coverage`/`closing-audit`
# already use, so a spreads/totals backfill row can never disagree with
# what closing-audit called derivable). A settlement has never had a
# per-market `closing` field for anything but h2h, so there is no
# non-null-original guard to apply for these two markets -- every
# still-not-backfilled settled game is a candidate, exactly what
# `closing-audit` counted as "derivable".
#
# CLV for a spreads/totals row stays deliberately ungraded. A line
# market's price is only comparable to another price for THE SAME LINE;
# `closing_line_value`'s cents/prob-edge diff assumes both prices quote
# the same bet, which holds for h2h (there is only ever one number to
# lay) but not for a spread or total, where the point itself can move
# between the pick and the close. Nothing this project writes to the
# ledger today records the POINT taken at recommendation time for these
# markets (`ledger._prices` keeps only price/total fields, never
# `home_line`/`away_line` -- and in any case no recommendation has ever
# flagged an actual spread or total pick, only full-game h2h or
# first-five). Computing a number anyway -- treating the close's price as
# though it quoted the same line the pick did -- would be exactly the
# fabrication CLAUDE.md forbids. So every spreads/totals backfill row
# records the close (line AND price, whatever the store captured) and
# reports `clv_graded: False` with a `clv_reason` naming the missing
# fair-price model, honestly, rather than a number nobody could defend.

BACKFILL = "closing_backfill"
CLOSING_SOURCE = "odds_snapshots"
BACKFILL_REASON = "abbreviation join bug 65f499a"
# Why a DIFFERENT reason for spreads/totals rows: h2h's null was a bug --
# a close existed in the store all along, hidden by the abbreviation join.
# Spreads/totals nulls are not a bug at all -- `ledger.settle` has simply
# never had a writer for anything but the h2h close, so every one of these
# settlements was ALWAYS going to read closing=null for its market until
# something like this backfill recorded one.
LINE_MARKET_BACKFILL_REASON = "market close not recorded at settlement (h2h-only writer)"
LINE_MARKET_CLV_REASON = "line-market CLV needs a fair-price model this system does not have"


def find_backfillable_closings(ledger_entries, snapshot_rows, *, market="h2h",
                               now=None) -> dict:
    """What can be appended right now, without appending anything.

    `market` selects which of h2h/spreads/totals this call backfills --
    default "h2h" so every existing caller (and every existing test that
    calls this without a `market=` argument) keeps its exact prior
    behaviour, byte for byte. first_five is deliberately not offered here
    -- see the module note above the per-market coverage section: it is a
    separate, sparser store and a separate decision.

    Pure and side-effect free -- `closing-backfill --dry-run` and the real
    run share this exact computation, so a dry run can never claim
    something the real run then fails to produce, and calling it twice
    with the same inputs is safe (idempotent by construction: a settlement
    already covered by a valid backfill for THIS market is reported under
    `already_backfilled`, not re-added to `to_append`).

    Returns a dict:
      to_append           -- new `closing_backfill` row dicts, one per
                              newly-derivable settlement, ready to append.
      derivable           -- [{game_pk, away_team, home_team, date,
                              closing}] for settlements not yet backfilled
                              for this market whose close IS now findable.
      not_derivable       -- [{game_pk, away_team, home_team, date,
                              reason}] for settlements not yet backfilled
                              for this market whose close still is not
                              findable (reason strings agree with
                              `closing-audit`'s for this market).
      already_backfilled  -- game_pks that already carry a valid backfill
                              row for this market and are skipped.
      no_recommendation   -- game_pks with no closing recorded for this
                              market yet but no matching recommendation
                              row to join with.
    """
    from src.pipeline import ledger  # local: no cycle (ledger never imports
                                      # grading) -- kept local so this
                                      # module's own import list, read top
                                      # to bottom, still describes what it
                                      # needs for its OWN primary job (the
                                      # prediction-log CLV path above).

    settled = ledger.settlements(ledger_entries)
    recs_by_pk = {r.get("game_pk"): r for r in ledger.recommendations(ledger_entries)}
    already = read_backfills(ledger_entries, market=market)
    # h2h keeps its original join (group_by_game + game_key, byte-identical
    # to before); spreads/totals reuse the SAME market-aware index
    # closing-audit itself is built on, so the two can never disagree
    # about what is derivable.
    snapshot_series = (snapshots.group_by_game(snapshot_rows) if market == "h2h"
                       else snapshots.market_series_index(snapshot_rows, market=market))
    stamp = _timestamp(now)

    to_append, derivable, not_derivable = [], [], []
    already_backfilled, no_recommendation = [], []

    for pk, settlement in settled.items():
        if market == "h2h" and settlement.get("closing") is not None:
            continue  # never touch a settlement that already has a close
        if pk in already:
            already_backfilled.append(pk)
            continue
        rec = recs_by_pk.get(pk)
        if rec is None:
            no_recommendation.append(pk)
            continue

        closing, reason = _ledger_closing(rec, snapshot_series, market=market)
        identity = {"game_pk": pk, "away_team": rec.get("away_team"),
                    "home_team": rec.get("home_team"), "date": rec.get("date")}
        if closing is None:
            not_derivable.append({**identity, "reason": reason})
            continue

        derivable.append({**identity, "closing": closing})
        to_append.append(_backfill_row(pk, rec, closing, stamp, market=market))

    return {
        "to_append": to_append,
        "derivable": derivable,
        "not_derivable": not_derivable,
        "already_backfilled": already_backfilled,
        "no_recommendation": no_recommendation,
    }


def _ledger_closing(rec, snapshot_series, market="h2h"):
    """(closing, reason) for one recommendation row.

    market="h2h" is the exact same definition, and the exact same reason
    strings, as `cli._settlement_closing` -- duplicated rather than
    imported: cli.py is the entry point that calls into this pipeline
    layer, not the other way around, so it must never be imported from
    here. UNCHANGED by this lane; every h2h caller reads the identical
    (closing, reason) it always has.

    Any other market reuses `snapshots.market_closing_observation` --
    the same PIT rule, over the market-aware index built above -- so its
    reason strings ("not_captured" / "no snapshot observed before first
    pitch") already agree with `closing-audit`'s.
    """
    if market == "h2h":
        key = snapshots.game_key(rec.get("away_team"), rec.get("home_team"),
                                 rec.get("commence_time"))
        series = snapshot_series.get(key)
        if not series:
            return None, "no snapshots recorded for this game"
        observation = snapshots.closing_observation(series, rec.get("commence_time"))
        if observation is None:
            return None, "no snapshot observed before first pitch"
    else:
        observation, reason = snapshots.market_closing_observation(
            snapshot_series, rec.get("away_team"), rec.get("home_team"),
            rec.get("commence_time"))
        if observation is None:
            return None, reason
    return {
        "market": market,
        "book": observation.get("book"),
        "observed_utc": observation.get("observed_utc"),
        "book_last_update": observation.get("book_last_update"),
        "book_stale_seconds": observation.get("book_stale_seconds"),
        "book_stale": observation.get("book_stale"),
        "prices": observation.get("prices"),
    }, None


def _ledger_clv(rec, closing, market="h2h") -> dict:
    """CLV for a backfilled settlement.

    market="h2h": off the h2h price only (see module note above), UNCHANGED
    by this lane -- same body, same reason strings, as before L18.

    Any other market: always ungraded (see `LINE_MARKET_CLV_REASON`'s note
    above -- a spread/total's price is only comparable to another price
    quoting the SAME line, and this project records neither the point
    taken at pick time nor a fair-price model that could translate across
    a line move). Same shape and vocabulary as `_closing_line_value` so a
    reader already familiar with `clv_graded`/`clv_reason` recognizes this
    immediately as the same kind of fact, never a silently-skipped field.
    """
    if market != "h2h":
        return {"clv_graded": False, "clv_reason": LINE_MARKET_CLV_REASON}
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


def _backfill_row(game_pk, rec, closing, stamp, market="h2h") -> dict:
    """One `closing_backfill` row: the derived close, its provenance, and
    the CLV it implies. `ref` is the settlement's `game_pk` -- its
    identifier in `ledger.settlements()`'s keying, and today also unique
    per settlement (see tests/test_pipeline_ledger.py; no game is settled
    twice in the live ledger) -- so it names exactly which immutable row
    this corrects without touching it. `market` (new in L18) says which
    market's close this row records, so `ref` + `market` together identify
    one backfill target -- a game can carry at most one valid backfill
    per market (`read_backfills` enforces that), never one overall.
    """
    return {
        "kind": BACKFILL,
        "ref": game_pk,
        "market": market,
        "closing_price": closing,
        "closing_observed_utc": closing.get("observed_utc"),
        "closing_source": CLOSING_SOURCE,
        "derived_utc": stamp,
        "clv": _ledger_clv(rec, closing, market=market),
        "reason": BACKFILL_REASON if market == "h2h" else LINE_MARKET_BACKFILL_REASON,
    }


def read_backfills(ledger_entries, market="h2h") -> dict:
    """Valid `closing_backfill` rows FOR ONE MARKET, keyed by the
    settlement `ref` (game_pk) they correct. This is the one place that
    decides "prefer the backfill when the original is null" -- every
    reader of a ledger closing should call this (or `effective_closing`,
    below) rather than re-deriving the rule, so the preference can never
    be implemented two different ways.

    `market` defaults to "h2h" so every pre-L18 caller (and every existing
    test that omits the argument) reads exactly what it always has. A row
    with no `market` field at all -- every `closing_backfill` row written
    before L18 -- is treated as `"h2h"`, since h2h was the only market
    this ever wrote before now.

    First valid row per ref wins (same rule as `deduplicate`'s
    first-prediction-per-game, above: the earliest record is the one
    actually checked against the store at the time; a later duplicate adds
    nothing, and a later CONFLICTING one is exactly the silent overwrite
    this function exists to refuse).

    A row is valid only if:
      * its `market` (defaulting to "h2h") matches the one asked for;
      * `ref` names a settlement that actually exists in this same set of
        entries; for market="h2h" specifically, that settlement's own
        `closing` must also still be null (a backfill can never override,
        or appear to correct, a settlement that already has a real close
        -- a tampered or stale row claiming otherwise is ignored outright,
        never trusted); spreads/totals have no such original field to
        check, so existence of the settlement is the only gate; and
      * it carries a non-null `closing_price`.

    Anything else -- an orphaned `ref`, a row targeting an already-closed
    h2h settlement, a second row for a `ref`+market already covered -- is
    silently excluded. It is not an error: the ledger is append-only, so a
    bad row already on disk cannot be deleted, only out-voted by this rule.
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
        if entry.get("market", "h2h") != market:
            continue
        ref = entry.get("ref")
        if ref in valid:
            continue  # first valid row per ref wins; later ones ignored
        if entry.get("closing_price") is None:
            continue
        if ref not in settled_closing:
            continue  # orphaned ref: no such settlement at all
        if market == "h2h" and settled_closing[ref] is not None:
            continue  # h2h original was never null; never override it
        valid[ref] = entry
    return valid


def effective_closing(settlement, backfills, market="h2h"):
    """The closing dict a reader should use for one settlement row, for one
    market: its own `closing` when `market` is "h2h" and that field is not
    null, else a valid backfill's `closing_price`, else None. `backfills`
    is `read_backfills(..., market=market)`'s return value -- already
    excludes anything that would try to override a non-null h2h original,
    so this function does not need to re-check that. Spreads and totals
    have no per-market field on the settlement itself to prefer over the
    backfill -- the backfill IS the only place either is ever recorded --
    so for those markets this goes straight to `backfills`.
    """
    if market == "h2h":
        original = settlement.get("closing")
        if original is not None:
            return original
    backfill = backfills.get(settlement.get("game_pk"))
    return backfill["closing_price"] if backfill else None


# ---------------------------------------------------------------------------
# Per-market closing coverage (L17)
# ---------------------------------------------------------------------------
#
# WHY THIS ASKS THE SAME QUESTION FOUR TIMES, NOT ONCE
# ------------------------------------------------------
# A settlement fixes the whole game -- who won it, what the final score
# was, who was ahead after five. That is enough to grade an h2h bet, a
# spread bet, a totals bet, or a first-five bet against it, whichever (if
# any) was actually recommended. So "can a closing price be identified for
# this settled game" is really four separate questions, one per market,
# each against the store that actually captures it: h2h/spreads/totals
# share odds_snapshots.jsonl; first_five lives in the far sparser
# f5_close.jsonl (see snapshots.MARKET_STORE_KEY). Asking it once, grouped
# by whatever the RECOMMENDATION happened to flag -- this function's
# previous shape -- answers a different question ("was the bet actually
# made gradeable") and hides three of the four markets' coverage entirely
# behind a single "market=None" bucket, since this system has so far only
# ever flagged full-game or first-five recommendations, never a spread or a
# total.
#
# WHY H2H, SPREADS, AND TOTALS CAN ALL BE "recorded" NOW -- FIRST_FIVE STILL CANNOT
# ------------------------------------------------------------------------------------
# A settlement's own `closing` field has only ever carried an h2h price;
# spreads and totals have no equivalent field on the settlement itself.
# L18 gave spreads and totals a `closing_backfill` writer (`market=` on
# `find_backfillable_closings`, above) alongside h2h's, so `from_backfill`
# for those two markets is no longer always zero -- it counts valid
# per-market backfill rows via `read_backfills(ledger_entries,
# market=market)`. first_five still has no backfill mechanism at all --
# that store is sparser and its own separate decision (see L18's task
# boundary) -- so `from_original`/`from_backfill`/`with_closing` stay
# honestly zero for it; what CAN be reported for it is what the store
# WOULD support if something chose to record it, under
# `derivable_not_recorded` -- a dry-run number, never written anywhere.

MARKET_SOURCE = {
    "h2h": "odds_snapshots",
    "spreads": "odds_snapshots",
    "totals": "odds_snapshots",
    "first_five": "f5_close",
}


def ledger_closing_coverage(ledger_entries, snapshot_rows=None, f5_rows=None) -> dict:
    """Per-market closing coverage over every settled forward-ledger game.

    Returns {market: {settled, with_closing, from_original, from_backfill,
    derivable_not_recorded, not_derivable, source}} for each of
    snapshots.MARKET_STORE_KEY's four markets, evaluated against EVERY
    settled game -- not just the ones a recommendation happened to flag for
    that market -- because the question this answers is about the CAPTURED
    STORES' coverage, not about which bets were made.

    `with_closing` (= `from_original` + `from_backfill`) is what is already
    evidence on the ledger -- h2h, spreads, and totals via
    `read_backfills(..., market=market)` (h2h alone also via its
    settlement's own `closing` field), first_five never (see module note
    above). `derivable_not_recorded` is additional games whose close a
    fresh, read-only lookup against the store can find right now but that
    the ledger has never recorded -- true only of first_five once h2h,
    spreads, and totals are backfilled, since a run of `closing-backfill
    --market all` clears the other three to zero.
    `not_derivable` is a reason histogram: `"not_captured"` (the store holds
    nothing for this game in this market at all) versus `"no snapshot
    observed before first pitch"` (it holds something, just not early
    enough) versus `"no matching recommendation row"` (the settlement has
    no recommendation to read away/home/commence_time from) -- the same
    three-way split `snapshots.market_closing_observation` always draws,
    plus the recommendation-lookup failure this function itself can hit.

    `snapshot_rows`/`f5_rows` default to reading the live stores; pass small
    fixtures directly in tests, the same convention `find_backfillable_closings`
    already uses.
    """
    from src.pipeline import ledger, snapshots

    recs_by_pk = {r.get("game_pk"): r for r in ledger.recommendations(ledger_entries)}
    settled = ledger.settlements(ledger_entries)

    if snapshot_rows is None:
        snapshot_rows = snapshots.read()
    if f5_rows is None:
        f5_rows = snapshots.read(path=snapshots.DEFAULT_F5_CLOSE_PATH)

    by_market = {}
    for market in snapshots.MARKET_STORE_KEY:
        rows_for_market = f5_rows if market == "first_five" else snapshot_rows
        index = snapshots.market_series_index(rows_for_market, market=market)
        # first_five has no backfill writer at all (out of this lane's
        # scope), so this always comes back {} for it -- no special case
        # needed to keep it at zero.
        backfills = read_backfills(ledger_entries, market=market)
        bucket = {
            "settled": len(settled), "with_closing": 0, "from_original": 0,
            "from_backfill": 0, "derivable_not_recorded": 0,
            "not_derivable": {}, "source": MARKET_SOURCE[market],
        }
        for pk, settlement in settled.items():
            if market == "h2h" and settlement.get("closing") is not None:
                bucket["from_original"] += 1
                bucket["with_closing"] += 1
                continue
            if pk in backfills:
                bucket["from_backfill"] += 1
                bucket["with_closing"] += 1
                continue

            rec = recs_by_pk.get(pk)
            if rec is None:
                reason = "no matching recommendation row"
                bucket["not_derivable"][reason] = bucket["not_derivable"].get(reason, 0) + 1
                continue

            observation, reason = snapshots.market_closing_observation(
                index, rec.get("away_team"), rec.get("home_team"), rec.get("commence_time"))
            if observation is not None:
                bucket["derivable_not_recorded"] += 1
            else:
                bucket["not_derivable"][reason] = bucket["not_derivable"].get(reason, 0) + 1
        by_market[market] = bucket
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
