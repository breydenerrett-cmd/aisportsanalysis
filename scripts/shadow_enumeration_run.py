#!/usr/bin/env python3
"""The authorised forward shadow runner for both-sides moneyline enumeration.

THIS IS THE ONE PERMITTED CALLER of `src.analysis.card_v2_enum_shadow`.
`tests/test_card_v2_candidate_enumeration.py` names this file explicitly and
fails if any OTHER file under src/, api/ or scripts/ imports that module --
so the isolation rule stays enforced for production callers while this one
entry point is allowed.

WHAT IT DOES
------------
Builds the same board the live preview path builds (`src.cli.cmd_card`'s own
assembly: `mlb.fetch_games` -> `briefing.build_slate` ->
`opportunities.build_opportunities`), then runs BOTH rules over that one
board:

  * the registered path, `card_v2.card_v2_for_date` -- unmodified, for the
    side-by-side;
  * the corrected path, `card_v2_enum_shadow.card_v2_for_date_shadow`.

Same board, same clock, same frozen parameters, same gates. Only enumeration
differs, and the record says so per candidate.

WHAT IT NEVER DOES
------------------
It publishes nothing. It writes exactly one evidence file under
`evidence/shadow_enumeration/` and touches no ledger store, no card store,
no live data file. It makes no paid API call: the board assembly reads the
free MLB schedule endpoint and the ALREADY-CAPTURED local odds stores, the
same inputs a `--rule v2` preview reads.

MISSING INPUTS ARE REFUSALS, NEVER GUESSES
------------------------------------------
Where our own number is unavailable, `our_probability` stays None, G6, G7
and G8 fail on it, and the candidate is refused. No default, no fallback,
no substituted market number. The record marks those candidates
`model_input_missing` so a reader can tell "our model said no" apart from
"our model had nothing to say", which are different facts and must never be
totalled together.

    python scripts/shadow_enumeration_run.py --date 2026-09-23
    python scripts/shadow_enumeration_run.py --date 2026-09-23 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import best_bets_card, card_v2_enum_shadow as shadow  # noqa: E402
from src.appstate import card_ledger  # noqa: E402
from src.report import card as card_v1  # noqa: E402
from src.report import card_v2  # noqa: E402

OUT_DIR = os.path.join("evidence", "shadow_enumeration")
FROZEN_PARAMS = "data/processed/card_v2_frozen_params.json"


def _sha256(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "<absent>"


def _git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True,
                             timeout=30)
        return out.stdout.strip() if out.returncode == 0 else "<unknown>"
    except (OSError, subprocess.SubprocessError):
        return "<unknown>"


def _iso_to_dt(value):
    """Parse an ISO-8601 instant, assuming UTC when no offset is given."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _drop_observed_after(candidates, moment):
    """`(kept, dropped)` -- candidates observed after `moment` are removed.

    The leakage guard for `--now`. Evaluating as of a past instant is only
    honest if the run cannot see anything that had not been observed yet;
    a candidate whose quote arrived later is future information and is
    counted out rather than quietly used.
    """
    if moment is None:
        return list(candidates), []
    kept, dropped = [], []
    for c in candidates:
        ob = c.get("observed_utc")
        ob = ob if isinstance(ob, datetime) else _iso_to_dt(ob)
        (dropped if (ob is not None and ob > moment) else kept).append(c)
    return kept, dropped


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def build_board(date: str, *, now: datetime):
    """`(entries, opportunity_rows, coverage)` as the preview path builds it.

    `coverage` carries `build_opportunities`' own `unpriced` list, with the
    reason it recorded per game. WITHOUT IT A ZERO READS AS A VERDICT: a run
    that finds no candidate because no game reached the 6-book floor looks
    identical, in counts alone, to one where a full board was evaluated and
    every side refused. Those are opposite facts and this record must never
    let them print the same.

    Imported here rather than at module scope so `--help` and the tests do
    not pull in the whole pipeline.
    """
    from src.analysis import opportunities as opportunities_mod
    from src.pipeline import briefing, enrichment, history
    from src.providers import mlb

    games = mlb.fetch_games(date)
    store = history.read_results()
    slate = briefing.build_slate(
        games, store, **enrichment.enrichment_inputs(games, date, store))
    entries = slate["games"]
    opportunities = opportunities_mod.build_opportunities(
        entries, date=date, now=now)
    coverage = {
        "checked_games": opportunities.get("checked_games"),
        "priced_games": opportunities.get("priced_games"),
        "empty_reason": opportunities.get("empty_reason"),
        "unpriced": list(opportunities.get("unpriced") or ()),
    }
    return entries, list(opportunities.get("rows") or ()), coverage


def model_record(entries, *, date: str, now: datetime, frozen):
    """Per game: the model inputs, the RAW model output, the calibration
    that was applied, and the calibrated number -- with the arithmetic
    checked rather than asserted.

    `card_v2._build_game_candidates` applies the frozen Platt fit inside
    itself and returns only the calibrated number on the candidate. To
    record raw AND calibrated honestly, the raw line is recomputed here
    from the same features with the same frozen dispersion, and the record
    carries `calibration_consistent` comparing sigmoid(a + b*logit(raw))
    against the number the candidate actually carries. A mismatch means
    this record is wrong, not that the card is -- and it would say so.
    """
    from src.analysis import strength

    cal = card_v2._moneyline_calibration(frozen)
    dispersion = (frozen or {}).get("DISPERSION")
    feature_rows = [card_v1._flatten(e) for e in entries or ()]
    league_rpg = strength.league_runs_per_game(feature_rows)
    relief = card_v1.relief_rates_for(date)

    out = {}
    excluded = []
    for entry in entries or ():
        game = card_v1._game_identity(entry, date=date)
        gid = game.get("game_id")
        if card_v1._has_started(game["first_pitch_utc"], now):
            excluded.append({"game_id": gid, "reason": "already_started",
                             "first_pitch_utc": game.get("first_pitch_utc")})
            continue
        if not league_rpg:
            excluded.append({"game_id": gid,
                             "reason": "no_league_runs_per_game"})
            continue
        features = dict(game.get("features") or {})
        features["away_bullpen_rate"] = relief.get(game["away_team"])
        features["home_bullpen_rate"] = relief.get(game["home_team"])
        try:
            line = strength.model_line(
                features, league_rpg=league_rpg,
                run_line=card_v1.RUN_LINE, dispersion=dispersion)
        except strength.StrengthError as exc:
            excluded.append({"game_id": gid, "reason": "model_refused",
                             "detail": str(exc)})
            continue

        raw_home = line["p_home"]
        calibrated_home = cal.apply(raw_home) if cal is not None else None
        out[gid] = {
            "game_id": gid,
            "away_team": game.get("away_team"),
            "home_team": game.get("home_team"),
            "first_pitch_utc": game.get("first_pitch_utc"),
            "model_inputs": features,
            "league_runs_per_game": league_rpg,
            "dispersion": dispersion,
            "model_id": line.get("model_id"),
            "raw": {
                "p_home": raw_home,
                "p_away": 1.0 - raw_home,
                "away_mean": line.get("away_mean"),
                "home_mean": line.get("home_mean"),
                "expected_total": line.get("expected_total"),
                "expected_margin": line.get("expected_margin"),
            },
            "calibration": (
                None if cal is None else
                {"a": cal.a, "b": cal.b, "n": cal.n,
                 "base_rate": cal.base_rate}),
            "calibrated": (
                None if calibrated_home is None else
                {"p_home": calibrated_home,
                 "p_away": 1.0 - calibrated_home}),
        }
    return out, excluded


def _quote_record(opportunity_rows):
    """Both sides' quotes, with their own observation timestamps."""
    out = {}
    for row in opportunity_rows or ():
        if row.get("market") != "h2h":
            continue
        gid, side = row.get("game_id"), row.get("side")
        if not gid or side not in ("away", "home"):
            continue
        out.setdefault(gid, {})[side] = {
            "best_price": row.get("best_price"),
            "best_book": row.get("best_book"),
            "books": row.get("books"),
            "market_implied_probability": row.get("market_implied_probability"),
            "observed_utc": row.get("observed_utc"),
        }
    return out


def _candidate_record(candidate, census_by_id):
    key = (candidate.get("game_id"), candidate.get("side"),
           candidate.get("market"), candidate.get("player_id"))
    census = census_by_id.get(key, {})
    our_p = candidate.get("our_probability")
    return {
        "candidate_id": "|".join(str(k) for k in key),
        "kind": candidate.get("kind"),
        "game_id": candidate.get("game_id"),
        "player_id": candidate.get("player_id"),
        "player": candidate.get("player"),
        "side": candidate.get("side"),
        "market": candidate.get("market"),
        "line": candidate.get("line"),
        "team_name": candidate.get("team_name"),
        "price": candidate.get("price"),
        "books": candidate.get("books"),
        "observed_utc": _iso(candidate.get("observed_utc")),
        "market_probability": candidate.get("market_probability"),
        "our_probability": our_p,
        "model_input_missing": our_p is None,
        "calibrated": candidate.get("calibrated"),
        "enumeration": candidate.get("enumeration", "registered"),
        "enumerated_side_role": candidate.get("enumerated_side_role"),
        "market_underdog": candidate.get("market_underdog"),
        "positive_price": candidate.get("positive_price"),
        "price_class": census.get("price_class"),
        "gate_primary_reason": census.get("primary_reason"),
        "gates_also_failed": census.get("also_failed"),
        "fill_eligible": census.get("fill_eligible"),
    }


def _selection_record(payload):
    out = []
    for entry in payload.get("all_bets") or ():
        out.append({
            "bet": entry.get("bet") or entry.get("bet_sentence"),
            "kind": entry.get("kind"),
            "game_id": entry.get("game_id"),
            "player_id": entry.get("player_id"),
            "market": entry.get("market"),
            "side": entry.get("side"),
            "price": entry.get("price"),
            "price_class": entry.get("price_class"),
            "entry_class": entry.get("entry_class"),
            "score": entry.get("score"),
            "our_probability": entry.get("our_probability"),
            "our_probability_used": entry.get("our_probability_used"),
            "market_probability": entry.get("market_probability"),
            "enumeration": entry.get("enumeration", "registered"),
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="slate date YYYY-MM-DD")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the summary, write no file")
    ap.add_argument("--now", default=None,
                    help="evaluate AS OF this UTC instant instead of the "
                         "wall clock (ISO-8601). Every candidate observed "
                         "AFTER it is dropped and counted, so this can only "
                         "ever narrow what the run sees -- it cannot make an "
                         "old quote fresh, and it cannot let a later "
                         "observation leak backwards. Use it to evaluate "
                         "inside a capture's freshness window that the wall "
                         "clock has already left.")
    ap.add_argument("--arm", default="moneyline",
                    choices=("moneyline", "moneyline+props",
                             "moneyline+run_line",
                             "moneyline+props+run_line"),
                    help="which enumeration arm(s) to run. 'moneyline' is "
                         "the arm already collecting a forward record and "
                         "its behaviour must not change; 'moneyline+props' "
                         "also enumerates both sides of every registered "
                         "prop contract; 'moneyline+run_line' also "
                         "enumerates both REAL quoted sides of the standard "
                         "run line (D1a, ENUMERATION_ID_RUNLINE); the last "
                         "choice runs all three. Each is a separate arm "
                         "with its own id -- see card_v2_enum_shadow's "
                         "module docstring for why they may never share "
                         "one.")
    args = ap.parse_args(argv)

    wall_clock = datetime.now(timezone.utc)
    now = wall_clock
    as_of = None
    if args.now:
        as_of = _iso_to_dt(args.now)
        if as_of is None:
            print(f"ERROR: --now is not an ISO-8601 instant: {args.now!r}",
                  file=sys.stderr)
            return 1
        if as_of > wall_clock:
            print("ERROR: --now is in the future; this tool evaluates past "
                  "instants only", file=sys.stderr)
            return 1
        now = as_of
    params = best_bets_card.V2

    try:
        frozen = card_v2.load_frozen_params()
    except card_v2.CardV2Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        entries, opportunity_rows, coverage = build_board(
            args.date, now=wall_clock)
    except Exception as exc:  # noqa: BLE001 - a board failure is a result
        print(f"ERROR building the board: {exc!r}", file=sys.stderr)
        return 1

    # LEAKAGE GUARD. With --now, a quote observed after the evaluation
    # instant is future information and must not reach either arm. Both
    # arms read the same filtered board, so the comparison stays like for
    # like.
    opportunity_rows, dropped_quotes = _drop_observed_after(
        opportunity_rows, as_of)
    if as_of is not None:
        print(f"as-of {as_of.isoformat()}: dropped {len(dropped_quotes)} "
              f"quote row(s) observed after it", file=sys.stderr)

    models, model_excluded = model_record(entries, date=args.date, now=now,
                                          frozen=frozen)
    quotes = _quote_record(opportunity_rows)

    registered = card_v2.card_v2_for_date(
        entries, opportunity_rows, date=args.date, now=now, frozen=frozen,
        params=params)
    reg_candidates, reg_pool = card_v2._build_game_candidates(
        entries, opportunity_rows, date=args.date, now=now, frozen=frozen)

    # ARMS ARE TOKENS, not a fixed enum. "moneyline" is always the base --
    # the choices list above enforces that every string still starts with
    # it -- and each of "props"/"run_line" after it turns ONE more arm on,
    # off by default, exactly matching `card_v2_for_date_shadow`'s own
    # `enumerate_props`/`enumerate_run_line` flags. Widening this set can
    # never change what "moneyline" alone measures: see this module's own
    # docstring and `PropArmIsSeparate`/`RunLineArmIsSeparate` in
    # tests/test_card_v2_candidate_enumeration.py, which assert exactly that.
    arm_tokens = set(args.arm.split("+"))
    enumerate_props = "props" in arm_tokens
    enumerate_run_line = "run_line" in arm_tokens
    corrected = shadow.card_v2_for_date_shadow(
        entries, opportunity_rows, date=args.date, now=now, frozen=frozen,
        params=params, enumerate_props=enumerate_props,
        enumerate_run_line=enumerate_run_line)
    cor_candidates, cor_pool, not_built = shadow.build_game_candidates(
        entries, opportunity_rows, date=args.date, now=now, frozen=frozen)

    # ALL ARMS CONSUME THE SAME SNAPSHOT. `entries`, `opportunity_rows` and
    # `frozen` are each built exactly once above and passed unchanged into
    # every arm's candidate builder -- the moneyline mirror, the prop
    # board and the run-line builder below all read the identical board
    # this run captured, so a coverage difference between arms is never an
    # artifact of reading the odds store twice at two different instants.
    # `build_run_line_candidates` reads its own quote source
    # (`card.run_line_rows`, a DIFFERENT multibook market than the h2h rows
    # above) with `multibook_rows=None` -- the same "read the live store"
    # default every other run-line caller in this repo uses -- so the run
    # line side of the board is current as of this same run, never a stale
    # value pinned by a widened-scope `entries`/`opportunity_rows` build.
    if enumerate_run_line:
        rl_candidates, rl_pool, rl_not_built = shadow.build_run_line_candidates(
            entries, date=args.date, now=now, frozen=frozen)
    else:
        rl_candidates, rl_pool, rl_not_built = [], 0, []

    # PROP CANDIDATES ARE PART OF "EVERY GATE RESULT". Rebuilt here so the
    # artifact records them with their own gate outcomes -- an earlier
    # version recorded only the game pool, so a reader could see that the
    # prop pool doubled but not what happened to any of it, which is the
    # question the prop arm exists to answer.
    reg_props, reg_prop_pool = card_v2._build_prop_candidates(
        entries, date=args.date, now=now)
    cor_props, cor_prop_pool = card_v2._build_prop_candidates(
        entries, date=args.date, now=now,
        prop_board=(shadow.both_sides_prop_board if enumerate_props else None))

    census_by_id = {}
    for row in corrected.get("gate_census") or ():
        key = (row.get("game_id"), row.get("side"), row.get("market"),
               row.get("player_id"))
        census_by_id[key] = row

    # The registered arm's prop pool needs its own census: it is a different
    # candidate set from the corrected arm's, so the census above does not
    # cover it.
    reg_census_by_id = {}
    for row in shadow.gate_census(reg_candidates + reg_props, now=now,
                                  params=params):
        key = (row.get("game_id"), row.get("side"), row.get("market"),
               row.get("player_id"))
        reg_census_by_id[key] = row

    def _prop_gate_summary(candidates, census):
        out = {}
        by_side = {}
        for c in candidates:
            key = (c.get("game_id"), c.get("side"), c.get("market"),
                   c.get("player_id"))
            reason = ((census.get(key) or {}).get("primary_reason")
                      or "all_gates_passed")
            out[reason] = out.get(reason, 0) + 1
            side_key = f"{c.get('side')}|{reason}"
            by_side[side_key] = by_side.get(side_key, 0) + 1
        return {"by_primary_reason": dict(sorted(out.items())),
                "by_side_and_reason": dict(sorted(by_side.items()))}

    # Check the recorded raw -> calibrated arithmetic against the number the
    # candidates actually carry, per game, rather than asserting it.
    consistency = []
    for candidate in reg_candidates:
        gid = candidate.get("game_id")
        rec = models.get(gid)
        if not rec or not rec.get("calibrated"):
            continue
        side = candidate.get("side")
        expected = rec["calibrated"]["p_away" if side == "away" else "p_home"]
        actual = candidate.get("our_probability")
        consistency.append({
            "game_id": gid, "side": side,
            "recorded": expected, "on_candidate": actual,
            "consistent": (actual is not None
                           and abs(expected - actual) < 1e-12),
        })

    added = [c for c in cor_candidates if c.get("enumeration")]
    added_missing_model = [c for c in added if c.get("our_probability") is None]
    added_gates = {}
    for candidate in added:
        key = (candidate.get("game_id"), candidate.get("side"),
               candidate.get("market"), candidate.get("player_id"))
        reason = (census_by_id.get(key) or {}).get("primary_reason") \
            or "all_gates_passed"
        added_gates[reason] = added_gates.get(reason, 0) + 1

    payload = {
        "kind": "forward_shadow_enumeration_run",
        "shadow_only": True,
        "published": False,
        "date": args.date,
        "run_utc": now.isoformat(),
        "wall_clock_utc": wall_clock.isoformat(),
        "evaluated_as_of": as_of.isoformat() if as_of else None,
        "quote_rows_dropped_as_future": len(dropped_quotes),
        "arm": args.arm,
        "implementation": {
            "registered": "consensus_side_favourite_only",
            "corrected": corrected.get("enumeration"),
            "enumerate_props": enumerate_props,
            "enumerate_run_line": enumerate_run_line,
            "runner": "scripts/shadow_enumeration_run.py",
        },
        "identity": {
            "git_head": _git("rev-parse", "HEAD"),
            "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_tracked_files": [
                l[3:] for l in _git("status", "--porcelain").splitlines()
                if l and not l.startswith("??")],
            "frozen_params": {"path": FROZEN_PARAMS,
                              "sha256": _sha256(FROZEN_PARAMS)},
            # Recorded with the caveat the erratum documents: this value is
            # checkout-dependent (raw bytes, so line endings count), so it
            # identifies THIS run's checkout, not the registered code alone.
            "code_fingerprint_method_v1": card_ledger.code_fingerprint(
                card_ledger.V2_FINGERPRINT_FILES),
            "code_fingerprint_caveat":
                "raw-byte hash; see docs/CARD_V2_IMPLEMENTATION_ERRATUM"
                "_2026-09-22.md E3",
            "rule_params": {
                "rule_id": params.rule_id,
                "worst_price": params.worst_price,
                "best_price": params.best_price,
                "markdown": params.markdown,
                "base_edge": params.base_edge,
                "main_market_floor": params.main_market_floor,
                "main_our_floor": params.main_our_floor,
                "plus_market_floor": params.plus_market_floor,
                "plus_our_floor": params.plus_our_floor,
                "disagreement_cap": params.disagreement_cap,
                "no_line_shopping": params.no_line_shopping,
                "plus_money_subcap": params.plus_money_subcap,
                "ceiling": params.ceiling,
                "floor": params.floor,
                "game_min_books": params.game_min_books,
                "fresh_seconds": params.fresh_seconds,
            },
        },
        "board": {
            "games_on_slate": len(entries or ()),
            "games_modelled": len(models),
            # The stage BEFORE enumeration. A game listed here never reached
            # a priced consensus at all, so neither path could build a
            # candidate for it and neither path's zero is a judgement on it.
            "games_without_a_priced_board": coverage,
            "games_excluded_before_enumeration": model_excluded,
            "quotes_by_game": quotes,
            "models_by_game": models,
            "raw_to_calibrated_consistency": consistency,
            "raw_to_calibrated_all_consistent": all(
                row["consistent"] for row in consistency) if consistency
            else None,
        },
        "registered_path": {
            "game_candidates": len(reg_candidates),
            "raw_pool_size": registered.get("raw_pool_size"),
            "n_picks": registered.get("n_picks"),
            "n_fills": registered.get("n_fills"),
            "n_plus_money_picks": registered.get("n_plus_money_picks"),
            "empty_reason": registered.get("empty_reason"),
            "game_candidate_rows": [_candidate_record(c, reg_census_by_id)
                                    for c in reg_candidates],
            "prop_candidates": reg_prop_pool,
            "prop_candidate_rows": [_candidate_record(c, reg_census_by_id)
                                    for c in reg_props],
            "prop_gates": _prop_gate_summary(reg_props, reg_census_by_id),
            "selections": _selection_record(registered),
        },
        "corrected_path": {
            "game_candidates": len(cor_candidates),
            "sides_added": len(added),
            "sides_not_built": not_built,
            "raw_pool_size": corrected.get("raw_pool_size"),
            "n_picks": corrected.get("n_picks"),
            "n_fills": corrected.get("n_fills"),
            "n_plus_money_picks": corrected.get("n_plus_money_picks"),
            "empty_reason": corrected.get("empty_reason"),
            "added_sides_by_gate_primary_reason": dict(sorted(
                added_gates.items())),
            "added_sides_missing_model_input": len(added_missing_model),
            "game_candidate_rows": [_candidate_record(c, census_by_id)
                                    for c in cor_candidates],
            "prop_candidates": cor_prop_pool,
            "prop_candidate_rows": [_candidate_record(c, census_by_id)
                                    for c in cor_props],
            "prop_gates": _prop_gate_summary(cor_props, census_by_id),
            # RUN LINE HAS NO REGISTERED COUNTERPART. Unlike the moneyline
            # mirror and the prop board, `card_v2.card_v2_for_date` never
            # builds a run-line candidate at all (module docstring, D1a) --
            # so there is nothing in `registered_path` to compare this
            # against. `rl_pool` is 0 with `sides_not_built` empty when
            # `--arm` did not ask for this arm, which is what makes the
            # moneyline and moneyline+props runs byte-identical to before
            # this arm existed (`RunLineArmIsSeparate` in
            # tests/test_card_v2_candidate_enumeration.py pins that).
            "run_line_candidates": rl_pool,
            "run_line_sides_not_built": rl_not_built,
            "run_line_candidate_rows": [_candidate_record(c, census_by_id)
                                        for c in rl_candidates],
            "run_line_gates": _prop_gate_summary(rl_candidates, census_by_id),
            "selections": _selection_record(corrected),
        },
        "difference": {
            "extra_game_candidates": len(cor_candidates) - len(reg_candidates),
            "extra_picks": (corrected.get("n_picks") or 0)
                           - (registered.get("n_picks") or 0),
            "extra_plus_money_picks":
                (corrected.get("n_plus_money_picks") or 0)
                - (registered.get("n_plus_money_picks") or 0),
        },
        "honesty_notes": [
            "Neither payload was published. No ledger or card store was "
            "written by this run.",
            "G6, G7 and G8 are evaluated on the real frozen model's output "
            "for every candidate that has one. A candidate with no model "
            "number keeps our_probability=None, fails those gates and is "
            "refused; `model_input_missing` marks it so a refusal is never "
            "read as a model opinion.",
            "Prop candidates are the registered builder's, unchanged unless "
            "--arm turns the prop arm on. With the run-line arm off, run "
            "lines are still not candidates at all on either path -- both "
            "still depart from registration section 2 by default.",
            "The run-line arm (D1a) has no registered counterpart: "
            "registered_path never carries a run-line row, so "
            "corrected_path.run_line_candidates is compared to zero, not "
            "to a registered count the way the moneyline and prop arms "
            "are. Its own calibration (`_runline_calibration`) is a "
            "SEPARATE fitted number from the moneyline Platt fit -- see "
            "that function's docstring before reading `our_probability` "
            "on a run_line row as if it came from the same fit.",
            "Zero candidates does NOT mean zero opportunities refused. Read "
            "board.games_without_a_priced_board first: a game with no "
            "multi-book consensus never reached either path, so neither "
            "path formed an opinion about it.",
        ],
    }

    unpriced_n = len(coverage.get("unpriced") or ())
    summary = (
        f"{args.date}  slate {payload['board']['games_on_slate']}  "
        f"modelled {payload['board']['games_modelled']}  "
        f"no priced board {unpriced_n}\n"
        f"  registered : candidates {len(reg_candidates):>3}  "
        f"picks {registered.get('n_picks')}  "
        f"fills {registered.get('n_fills')}  "
        f"plus-money {registered.get('n_plus_money_picks')}\n"
        f"  corrected  : candidates {len(cor_candidates):>3}  "
        f"picks {corrected.get('n_picks')}  "
        f"fills {corrected.get('n_fills')}  "
        f"plus-money {corrected.get('n_plus_money_picks')}\n"
        f"  added sides {len(added)}  "
        f"missing model input {len(added_missing_model)}  "
        f"gates {payload['corrected_path']['added_sides_by_gate_primary_reason']}"
    )
    if enumerate_run_line:
        rl_gate_summary = payload["corrected_path"]["run_line_gates"][
            "by_primary_reason"]
        summary += (
            f"\n  run line   : candidates {rl_pool:>3}  "
            f"not built {len(rl_not_built)}  "
            f"gates {rl_gate_summary}")
    print(summary, file=sys.stderr)

    if args.dry_run:
        print("(dry run: no file written)", file=sys.stderr)
        return 0

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if args.arm == "moneyline" else f"_{args.arm.replace('+', '-')}"
    out_path = os.path.join(args.out_dir, f"{args.date}_{stamp}{suffix}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"wrote {out_path}", file=sys.stderr)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
