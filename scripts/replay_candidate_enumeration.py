#!/usr/bin/env python3
"""Controlled reconstruction: how many moneyline sides each V2 publish could
have evaluated, against how many it did.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
It is NOT a replay of a published card. A replay would rebuild the whole
decision -- dossiers, features, the run model, every gate -- from the exact
inputs the publisher held at that instant, and this repository does not store
a point-in-time snapshot of the dossier/feature state, so that cannot be done
faithfully. Claiming otherwise would be the same mistake as reading a local
working tree and calling it the system's state.

It IS a controlled reconstruction of ONE stage: candidate ENUMERATION, from
the multibook odds store, which does keep every quote with its own
`observed_utc` and can therefore be cut back to any past instant exactly.
Each publish snapshot is reconstructed SEPARATELY, from quotes observed at or
before that snapshot's own `published_utc`. Snapshots are never merged, and a
side that appears in five snapshots is five observations of one contract, not
five bets.

WHICH GATES THIS CAN AND CANNOT DECIDE
--------------------------------------
Decided here, because they read the board alone:
  G1 (started)  -- enforced by dropping events already commenced at T
  G2 (books)    -- the book count at T
  G3 (stale)    -- the newest quote's age at T against `fresh_seconds`
  G4 (band)     -- the best price at T
  G5 (market)   -- the de-vigged consensus at T. THIS IS THE GATE AT ISSUE.
  G13 (no line shopping) -- consensus against the best price's break-even
Not decided here, because they read our own number, which needs the model and
the point-in-time features this reconstruction does not have:
  G6 (floor), G7 (value), G8 (disagreement)
They are reported as `model_input_unavailable`, never as passes. A count of
"candidates that would have been picks" is therefore NOT produced, and no
profitability claim is made or implied.

The de-vigged consensus comes from `src.analysis.prices.snapshot`, the
registered code, including its known bias (that function averages de-vigged
prices across all books INCLUDING the best one, which understates measured
price improvement -- see the corrected handoff). That bias affects
improvement arithmetic, which this script does not use; G5 reads the
consensus itself.

Output is deterministic: same store, same snapshots, same bytes. Nothing is
written to any live store, and no card is published.

    python scripts/replay_candidate_enumeration.py --date 2026-09-22
    python scripts/replay_candidate_enumeration.py --date 2026-09-22 \
        --out evidence/enumeration_reconstruction_2026-09-22.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import best_bets_card, prices  # noqa: E402
from src.pipeline import store_archive  # noqa: E402

CARD_STORE = "evidence/cards_v2.jsonl"
ODDS_STORE = "data/processed/odds_multibook.jsonl"
FROZEN_PARAMS = "data/processed/card_v2_frozen_params.json"

IMPLEMENTATION_REGISTERED = "consensus_side_favourite_only"
IMPLEMENTATION_CORRECTED = "moneyline_both_sides_v1"

MODEL_GATES = ("G6_FLOOR", "G7_VALUE", "G8_DISAGREEMENT")


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def _sha256(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "<absent>"


def _logical_store_digest(path: str) -> dict:
    """A rotated store is its archive segments plus its hot file. Hashing the
    hot file alone would call two different stores identical whenever the
    difference sat in a segment."""
    parts = [{"path": str(seg), "sha256": _sha256(seg)}
             for seg in sorted(str(s) for s in store_archive.segments(path))]
    parts.append({"path": str(path), "sha256": _sha256(path)})
    return {"logical_store": path, "parts": parts}


def _revision() -> dict:
    def git(*args):
        try:
            out = subprocess.run(["git", *args], capture_output=True,
                                 text=True, timeout=30)
            return out.stdout.strip() if out.returncode == 0 else "<unknown>"
        except (OSError, subprocess.SubprocessError):
            return "<unknown>"

    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_tracked_files": [
            l[3:] for l in git("status", "--porcelain").splitlines()
            if l and not l.startswith("??")
        ],
    }


# ---------------------------------------------------------------------------
# The board, cut back to one instant
# ---------------------------------------------------------------------------

def _parse(ts):
    if not ts:
        return None
    try:
        value = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _slate_date_et(commence_utc: datetime) -> str:
    """The America/New_York calendar date, the `SLATE_DATE` the capture
    script uses. Falls back to a fixed -4h offset if tzdata is absent, which
    is correct for every September date this project covers."""
    try:
        from zoneinfo import ZoneInfo

        return commence_utc.astimezone(ZoneInfo("America/New_York")).strftime(
            "%Y-%m-%d")
    except Exception:  # noqa: BLE001 - tzdata missing on a bare CI image
        return (commence_utc - timedelta(hours=4)).strftime("%Y-%m-%d")


def load_quotes(date: str, *, store: str = ODDS_STORE) -> dict:
    """`{event_id: [row, ...]}` for one slate date, every capture kept."""
    out: dict = {}
    for line in store_archive.iter_lines(store):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        commence = _parse(row.get("commence_time"))
        if commence is None or _slate_date_et(commence) != date:
            continue
        event = row.get("event_id")
        if not event:
            continue
        out.setdefault(event, []).append(row)
    return out


def board_at(rows, moment: datetime):
    """The newest quote per book at or before `moment`, plus the age of the
    freshest of them -- `best_bets_card.quote_age_seconds`'s input."""
    newest: dict = {}
    for row in rows:
        observed = _parse(row.get("observed_utc"))
        if observed is None or observed > moment:
            continue
        book = row.get("book")
        prev = newest.get(book)
        if prev is None or observed > prev[0]:
            newest[book] = (observed, row)
    if not newest:
        return [], None, None
    quotes = [r for _obs, r in sorted(newest.values(), key=lambda p: str(p[1].get("book")))]
    freshest = max(obs for obs, _r in newest.values())
    commence = _parse(quotes[0].get("commence_time"))
    return quotes, freshest, commence


# ---------------------------------------------------------------------------
# Board-only gate outcomes
# ---------------------------------------------------------------------------

def board_gates(*, price, consensus, books, age_seconds, params):
    """G2, G3, G4, G5 and G13 for one side. Model gates are not guessed."""
    fails = []
    if books is None or books < params.game_min_books:
        fails.append("G2_BOOKS")
    if age_seconds is None or age_seconds > params.fresh_seconds:
        fails.append("G3_STALE")
    if price is None or not best_bets_card.in_band(price, params):
        fails.append("G4_BAND")
    pcls = best_bets_card.price_class(price) if price is not None else None
    if pcls == "MAIN":
        floor = params.main_market_floor
        if floor is not None and not (consensus is not None and consensus > floor):
            fails.append("G5_MARKET")
    elif pcls == "PLUS_MONEY":
        floor = params.plus_market_floor
        if floor is not None and not (
                consensus is not None and floor <= consensus < 0.50):
            fails.append("G5_MARKET")
    else:
        fails.append("G5_MARKET")
    if params.no_line_shopping and price is not None:
        be = best_bets_card.breakeven(price)
        if be is not None and consensus is not None and consensus > be:
            fails.append("G13_LINE_SHOPPING")
    return pcls, fails


# ---------------------------------------------------------------------------
# One snapshot
# ---------------------------------------------------------------------------

def reconstruct(snapshot_ts: datetime, quotes_by_event: dict, *, params):
    events_total = len(quotes_by_event)
    counts = {
        "events_on_slate": events_total,
        "events_with_a_board_at_t": 0,
        "events_already_commenced_at_t": 0,
        "events_no_quote_at_t": 0,
        "events_below_book_floor": 0,
        "sides_enumerated_registered": 0,
        "sides_enumerated_corrected": 0,
        "sides_added_by_correction": 0,
    }
    added_rows = []
    by_primary_reason = {}

    for event in sorted(quotes_by_event):
        quotes, freshest, commence = board_at(quotes_by_event[event],
                                              snapshot_ts)
        if not quotes:
            counts["events_no_quote_at_t"] += 1
            continue
        if commence is not None and commence <= snapshot_ts:
            counts["events_already_commenced_at_t"] += 1
            continue
        shot = prices.snapshot(quotes)
        if shot.get("skipped"):
            counts["events_below_book_floor"] += 1
            continue
        counts["events_with_a_board_at_t"] += 1

        sides = shot["sides"]
        books = shot["dispersion"]["books"]
        age = (snapshot_ts - freshest).total_seconds() if freshest else None

        priced = {s: d for s, d in sides.items() if not d.get("skipped")}
        if not priced:
            continue
        favourite = max(priced,
                        key=lambda s: priced[s]["consensus_probability"])

        counts["sides_enumerated_registered"] += 1
        counts["sides_enumerated_corrected"] += len(priced)

        for side, detail in sorted(priced.items()):
            if side == favourite:
                continue
            counts["sides_added_by_correction"] += 1
            price = detail["best_price"]
            consensus = detail["consensus_probability"]
            pcls, fails = board_gates(price=price, consensus=consensus,
                                      books=books, age_seconds=age,
                                      params=params)
            primary = fails[0] if fails else "board_gates_all_passed"
            by_primary_reason[primary] = by_primary_reason.get(primary, 0) + 1
            added_rows.append({
                "event_id": event,
                "side": side,
                "away_team": quotes[0].get("away_team"),
                "home_team": quotes[0].get("home_team"),
                "best_price": price,
                "best_book": detail["best_book"],
                "market_probability": consensus,
                "market_underdog": consensus < 0.50,
                "positive_price": price is not None and price > 0,
                "price_class": pcls,
                "books": books,
                "quote_age_seconds": round(age, 1) if age is not None else None,
                "board_gate_primary_reason": primary,
                "board_gates_also_failed": fails[1:],
                "model_gates": {g: "model_input_unavailable"
                                for g in MODEL_GATES},
            })

    return counts, by_primary_reason, added_rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    ap.add_argument("--card-store", default=CARD_STORE)
    ap.add_argument("--odds-store", default=ODDS_STORE)
    ap.add_argument("--out", default=None,
                    help="write the manifest+result JSON here")
    ap.add_argument("--max-added-rows", type=int, default=40,
                    help="per-snapshot cap on listed added sides; the COUNTS "
                         "are never capped and the cap is recorded")
    ap.add_argument("--pin-inputs", default=None,
                    help="write the exact quote rows this run consumed to "
                         "this path, sorted and deduplicated, and record its "
                         "sha256 in the manifest. The live odds store rotates "
                         "and other jobs rewrite stores this reconstruction "
                         "reads; a pinned extract is what keeps the result "
                         "reproducible after that happens.")
    args = ap.parse_args(argv)

    params = best_bets_card.V2

    snapshots = []
    for line in store_archive.iter_lines(args.card_store):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("date") != args.date:
            continue
        snapshots.append({
            "published_utc": row.get("published_utc"),
            "rule": row.get("rule"),
            "n_picks": row.get("n_picks"),
            "n_fills": row.get("n_fills"),
            "n_entries_listed": len(row.get("all_bets") or ()),
            "n_plus_money_picks": row.get("n_plus_money_picks"),
            "code_fingerprint": row.get("code_fingerprint"),
        })
    snapshots.sort(key=lambda s: s["published_utc"] or "")

    quotes_by_event = load_quotes(args.date, store=args.odds_store)

    pinned = None
    if args.pin_inputs:
        rows = []
        for event in sorted(quotes_by_event):
            for row in quotes_by_event[event]:
                rows.append(json.dumps(row, sort_keys=True))
        rows = sorted(set(rows))
        with open(args.pin_inputs, "w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(row + "\n")
        pinned = {"path": args.pin_inputs, "rows": len(rows),
                  "sha256": _sha256(args.pin_inputs),
                  "note": "every quote row this reconstruction consumed for "
                          "this slate date, sorted and deduplicated; replaces "
                          "the rotating live store as the citable input"}

    results = []
    for snap in snapshots:
        moment = _parse(snap["published_utc"])
        if moment is None:
            results.append({**snap, "status": "unparseable_published_utc"})
            continue
        counts, reasons, added = reconstruct(moment, quotes_by_event,
                                             params=params)
        if counts["events_on_slate"] == 0:
            status = "inputs_unavailable"
        elif counts["events_with_a_board_at_t"] == 0:
            status = "no_board_at_this_instant"
        else:
            status = "reconstructed"
        listed = sorted(added, key=lambda r: (r["event_id"], r["side"]))
        results.append({
            **snap,
            "status": status,
            "counts": counts,
            "added_sides_by_board_gate_primary_reason": dict(
                sorted(reasons.items())),
            "added_sides_listed": listed[: args.max_added_rows],
            "added_sides_listed_truncated_at": args.max_added_rows,
            "added_sides_listed_total": len(listed),
        })

    payload = {
        "kind": "controlled_reconstruction",
        "not_a_replay_because": (
            "no point-in-time snapshot of the dossier/feature state exists, "
            "so our own number cannot be rebuilt as the publisher held it; "
            "only the odds board is reconstructible to an exact instant"),
        "counting_units": {
            "events_*": "one scheduled game",
            "sides_*": "one side of one game moneyline contract",
            "books": "one bookmaker quote on one board",
            "snapshots": "one publish run; never pooled across runs",
        },
        "manifest": {
            "date": args.date,
            "revision": _revision(),
            "enumeration_implementations": {
                "before": IMPLEMENTATION_REGISTERED,
                "after": IMPLEMENTATION_CORRECTED,
            },
            "rule_params": {
                "rule_id": params.rule_id,
                "ceiling": params.ceiling,
                "floor": params.floor,
                "game_min_books": params.game_min_books,
                "fresh_seconds": params.fresh_seconds,
                "worst_price": params.worst_price,
                "best_price": params.best_price,
                "main_market_floor": params.main_market_floor,
                "plus_market_floor": params.plus_market_floor,
            },
            "parameter_version": {
                "path": FROZEN_PARAMS,
                "sha256": _sha256(FROZEN_PARAMS),
            },
            "inputs": [
                _logical_store_digest(args.odds_store),
                _logical_store_digest(args.card_store),
            ],
            "pinned_input_extract": pinned,
            "inputs_NOT_reconstructible": [
                {"input": "dossier / feature state per game",
                 "why": "no point-in-time snapshot is stored; the live "
                        "dossier is rebuilt each run and overwritten",
                 "affects": "our own number, and therefore G6, G7, G8"},
                {"input": "player prop board at each publish instant",
                 "why": "the prop board is not stored per instant; only the "
                        "published entries survive",
                 "affects": "every prop candidate, which is every entry all "
                            "seven of these cards actually listed"},
                {"input": "pitcher and bullpen logs as held at each publish",
                 "why": "the log stores are rewritten in place by the daily "
                        "job; a concurrent repair to the refresh path may "
                        "change them further",
                 "affects": "model inputs, hence the same three gates"},
            ],
            "prior_locked_state": {
                "source": args.card_store,
                "note": "each snapshot's own all_bets carries locked / "
                        "locked_at per entry, so the prior locked set IS "
                        "recoverable from the card store and is covered by "
                        "its hash above",
            },
            "snapshots_evaluated": [s["published_utc"] for s in snapshots],
            "gates_decided_here": ["G1_STARTED", "G2_BOOKS", "G3_STALE",
                                   "G4_BAND", "G5_MARKET",
                                   "G13_LINE_SHOPPING"],
            "gates_not_decided_here": list(MODEL_GATES),
        },
        "snapshots": results,
    }

    text = json.dumps(payload, indent=2, sort_keys=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    for snap in results:
        c = snap.get("counts") or {}
        print(f"  {snap['published_utc']}  {snap['status']:>24}  "
              f"listed={snap['n_entries_listed']:>2}  "
              f"sides_before={c.get('sides_enumerated_registered', 0):>2}  "
              f"sides_after={c.get('sides_enumerated_corrected', 0):>2}  "
              f"added={c.get('sides_added_by_correction', 0):>2}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
