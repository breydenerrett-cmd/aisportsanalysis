"""The report of LIVE_TENNIS_V1 (docs/PREREG_LIVE_TENNIS.md sections 7, 8 and 13).

Two parts, and the line between them is the point:

  ALWAYS        counts, coverage and credits: decision points armed, decisions by status and by exclusion reason,
                bets, references and the counted causes of no reference, outcomes settled, ticks and their errors,
                credits spent by day. Nothing that could be read as a result.
  PAST FLOORS   the decisive M2 with its match-clustered interval, M1, the verdict, and the descriptive extras.
                Only when ALL of: at least BET_FLOOR bets with a valid reference, from at least MATCH_FLOOR distinct
                matches, and a reference coverage of at least REFERENCE_COVERAGE_FLOOR of all bets. Below any
                floor no effect statistic of any kind is printed (no peeking, no interim M2, no units).

The state is one of, and these are never run together (an empty result must not read as a verdict):

  NO_DATA        no ledger yet, or a genesis row and no decision point: nothing was captured, so nothing is concluded
  COLLECTING     data exists, a floor is not met, the stop date has not passed
  PASS           floors met, M2's 95% match-clustered interval entirely above zero AND M1 above zero
  FAIL           floors met and not PASS
  INCONCLUSIVE   the stop date passed with a floor unmet, or the constants fingerprint or the hash chain is broken

PASS maps to registry result `candidate` (never `survivor`), FAIL to `null`, INCONCLUSIVE to `below_floor`. The verdict is
appended to the alpha registry once, only by `--record-verdict`, only for a final state.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from src.model import discovery
from src.research.live_tennis import board, clv, config, decision as decision_mod, guard
from src.research.live_tennis.ledger import PaperLedger

NO_DATA, COLLECTING, PASS, FAIL, INCONCLUSIVE = "NO_DATA", "COLLECTING", "PASS", "FAIL", "INCONCLUSIVE"
REGISTRY_RESULT = {PASS: "candidate", FAIL: "null", INCONCLUSIVE: "below_floor"}


def _mean(values: Sequence[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _interval(rows: List[dict], key: str) -> dict:
    return discovery.clustered_bootstrap(
        rows, lambda sample: _mean([r[key] for r in sample]),
        resamples=config.BOOTSTRAP_RESAMPLES, seed=config.BOOTSTRAP_SEED)


def _read_heartbeats(path) -> List[dict]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def credits_by_day(rows: Iterable[Mapping]) -> Dict[str, int]:
    out: Dict[str, int] = defaultdict(int)
    for row in rows:
        if str(row.get("caller") or "").startswith(config.CREDIT_CALLER):
            out[str(row.get("utc") or "")[:10]] += int(row.get("credits_used_last") or 0)
    return dict(sorted(out.items()))


def counts(ledger: PaperLedger, heartbeats: Sequence[Mapping], credit_rows: Sequence[Mapping]) -> dict:
    rows = ledger.rows()
    by_kind = Counter(r.get("kind") for r in rows)
    decisions = [r for r in rows if r.get("kind") == "decision"]
    refs = [r for r in rows if r.get("kind") == "reference" and not r.get("shadow")]
    no_refs = [r for r in rows if r.get("kind") == "no_reference" and not r.get("shadow")]
    bets = [d for d in decisions if d.get("status") == decision_mod.BET]
    by_status = Counter(d.get("status") for d in decisions)
    by_reason = Counter(d.get("reason") for d in decisions if d.get("reason"))
    ref_ids = {r["dp_id"] for r in refs}
    daily = credits_by_day(credit_rows)
    refused = Counter()
    errors = 0
    for beat in heartbeats:
        errors += len(beat.get("errors") or [])
        for item in beat.get("refused") or []:
            refused[str(item.get("reason") or "").split(" (")[0]] += 1
    unmatched = {e for beat in heartbeats for e in (beat.get("unmatched_live") or [])}
    return {
        "armed": by_kind.get("armed", 0), "decisions": len(decisions), "by_status": dict(by_status),
        "by_reason": dict(by_reason), "attempt_rows": by_kind.get("attempt", 0), "bets": len(bets),
        "shadow_bets": sum(1 for d in decisions if d.get("shadow_bet")),
        "references": len(refs), "no_reference": len(no_refs),
        "no_reference_causes": dict(Counter(r.get("cause") for r in no_refs)),
        "bets_pending_reference": sum(1 for b in bets if b["dp_id"] not in ref_ids
                                      and b["dp_id"] not in {r["dp_id"] for r in no_refs}),
        "outcomes": by_kind.get("outcome", 0), "ticks": len(heartbeats),
        "ticks_with_espn": sum(1 for b in heartbeats if b.get("espn_ok")), "tick_errors": errors,
        "guard_refusals": dict(refused), "unmatched_live_events": len(unmatched),
        "credits_total": sum(daily.values()), "credits_by_day": daily,
        "credits_per_active_day": (sum(daily.values()) / len(daily)) if daily else None,
    }


def floors(ledger: PaperLedger) -> dict:
    rows = ledger.rows()
    bets = [r for r in rows if r.get("kind") == "decision" and r.get("status") == decision_mod.BET]
    refs = {r["dp_id"]: r for r in rows if r.get("kind") == "reference" and not r.get("shadow")}
    with_ref = [b for b in bets if b["dp_id"] in refs]
    matches = {b["event_id"] for b in with_ref}
    coverage = (len(with_ref) / len(bets)) if bets else None
    met = (len(with_ref) >= config.BET_FLOOR and len(matches) >= config.MATCH_FLOOR
           and coverage is not None and coverage >= config.REFERENCE_COVERAGE_FLOOR)
    return {"bets": len(bets), "bets_with_reference": len(with_ref), "matches": len(matches), "coverage": coverage,
            "bet_floor": config.BET_FLOOR, "match_floor": config.MATCH_FLOOR,
            "coverage_floor": config.REFERENCE_COVERAGE_FLOOR, "met": met}


def _effect_rows(ledger: PaperLedger) -> List[dict]:
    rows = ledger.rows()
    decisions = {r["dp_id"]: r for r in rows if r.get("kind") == "decision"}
    out = []
    for ref in rows:
        if ref.get("kind") != "reference" or ref.get("shadow") or ref.get("dp_id") not in decisions:
            continue
        out.append({"date": ref["event_id"], "dp_id": ref["dp_id"], "m1": ref["m1"], "m2": ref["m2"],
                    "m2_best": ref["m2_best"], "other_m1": ref["other_m1"], "other_m2": ref["other_m2"],
                    "selection": ref["m2"] - ref["other_m2"]})
    return out


def _descriptive(ledger: PaperLedger, effect: List[dict]) -> dict:
    rows = ledger.rows()
    decisions = {r["dp_id"]: r for r in rows if r.get("kind") == "decision"}
    refs = {r["dp_id"]: r for r in rows if r.get("kind") == "reference"}
    outcomes = {r["dp_id"]: r for r in rows if r.get("kind") == "outcome"}
    out: dict = {}
    out["m2_best"] = {"mean": _mean([r["m2_best"] for r in effect]), **_interval(effect, "m2_best"),
                      "label": "includes price improvement from line shopping, never edge"}
    out["other_side_m2"] = {"mean": _mean([r["other_m2"] for r in effect])}
    out["selection_effect"] = {"mean": _mean([r["selection"] for r in effect]), **_interval(effect, "selection")}
    # permissive freshness: every DP the loose variant would bet (real or shadow) that has a reference board
    perm = []
    for dp, dec in decisions.items():
        view = dec.get("permissive")
        ref = refs.get(dp)
        if not view or view.get("status") != decision_mod.BET or ref is None or view.get("entry") is None:
            continue
        metrics = clv.clv(view["side"], view["board"], ref["ref_board"])
        perm.append({"date": dec["event_id"], "m2": metrics["m2"], "m1": metrics["m1"]})
    out["permissive_m2"] = ({"n": len(perm), "mean": _mean([r["m2"] for r in perm]), **_interval(perm, "m2"),
                             "label": "permissive freshness, stale-quote contamination check, descriptive only"}
                            if perm else {"n": 0})
    # outcomes: units, Brier
    settled = [outcomes[dp] for dp in outcomes if outcomes[dp].get("bet_result") in ("WIN", "LOSS", "VOID")]
    graded = [o for o in settled if o["bet_result"] != "VOID"]
    out["units"] = {"bets_settled": len(settled), "void": len(settled) - len(graded),
                    "profit_at_average_price": sum(o["profit_avg"] for o in settled),
                    "profit_at_best_price": sum(o["profit_best"] for o in settled),
                    "label": "descriptive, flat 1 unit, not a result"}
    brier_m, brier_c, n_b = [], [], 0
    set_brier = []
    for o in outcomes.values():
        if o.get("match_winner_home") is not None and o.get("model_p_match_home") is not None \
                and o.get("consensus_home_at_decision") is not None:
            y = 1.0 if o["match_winner_home"] else 0.0
            brier_m.append((o["model_p_match_home"] - y) ** 2)
            brier_c.append((o["consensus_home_at_decision"] - y) ** 2)
        if o.get("set_winner_home") is not None and o.get("model_p_set_home") is not None:
            y = 1.0 if o["set_winner_home"] else 0.0
            set_brier.append((o["model_p_set_home"] - y) ** 2)
    out["brier"] = {"n": len(brier_m), "model_match": _mean(brier_m), "consensus_match": _mean(brier_c),
                    "set_n": len(set_brier), "model_set": _mean(set_brier)}
    # model minus consensus by sets-won score, by tour, by favourite/underdog
    gaps: Dict[str, List[float]] = defaultdict(list)
    ages: List[float] = []
    for dec in decisions.values():
        if dec.get("status") not in (decision_mod.BET, decision_mod.NO_BET) or not dec.get("board"):
            continue
        mc = dec["board"]["consensus_home"]
        p = (dec.get("model") or {}).get("p_match_home")
        if p is None:
            continue
        diff = 100.0 * (p - mc)
        gaps[f"score {dec['sets_won_home']}-{dec['sets_won_away']}"].append(diff)
        gaps[f"tour {dec['tour']}"].append(diff)
        gaps["home favourite" if mc >= 0.5 else "home underdog"].append(diff)
        t_resp = board.parse_utc(dec.get("t_decision"))
        for quote in dec.get("fresh_quotes") or []:
            stamp = board.parse_utc(quote.get("last_update"))
            if t_resp and stamp:
                ages.append((t_resp - stamp).total_seconds())
    out["model_minus_consensus_pp"] = {k: {"n": len(v), "mean": _mean(v)} for k, v in sorted(gaps.items())}
    ages.sort()
    out["fresh_quote_age_s"] = ({"n": len(ages), "median": ages[len(ages) // 2], "p90": ages[min(len(ages) - 1, int(0.9 * len(ages)))]}
                                if ages else {"n": 0})
    return out


def build(ledger: Optional[PaperLedger] = None, *, now: Optional[datetime] = None, heartbeat_path=None,
          credit_rows: Optional[Sequence[Mapping]] = None, credit_stores: Optional[Sequence] = None) -> dict:
    ledger = ledger or PaperLedger()
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    heartbeats = _read_heartbeats(heartbeat_path if heartbeat_path is not None else config.heartbeat_path())
    credit = list(credit_rows) if credit_rows is not None else guard.read_rows(credit_stores)
    report: dict = {"rule_id": config.RULE_ID, "generated_utc": board.iso_utc(moment), "registry_id": config.REGISTRY_ID,
                    "stop_date": config.STOP_DATE}
    genesis = ledger.genesis()
    chain = ledger.verify() if ledger.path.exists() else None
    problem = ledger.fingerprint_problem()
    report["integrity"] = {
        "ledger_exists": ledger.path.exists(), "chain_ok": (chain.ok if chain else None),
        "chain_break": (None if chain is None or chain.ok else chain.reason), "fingerprint_problem": problem,
        "prereg_sha256_at_genesis": (genesis or {}).get("prereg_sha256"),
        "first_capture_utc": (genesis or {}).get("first_capture_utc")}
    report["counts"] = counts(ledger, heartbeats, credit) if ledger.path.exists() else None
    fl = floors(ledger) if ledger.path.exists() else None
    report["floors"] = fl
    past_stop = moment.date() > date.fromisoformat(config.STOP_DATE)
    broken = bool(problem) or (chain is not None and not chain.ok)
    n_decisions = (report["counts"] or {}).get("decisions", 0)
    if broken:
        state, note = INCONCLUSIVE, ("the ledger's hash chain or its constants fingerprint is broken; no result is "
                                     "computed (docs/PREREG_LIVE_TENNIS.md section 8)")
    elif genesis is None or n_decisions == 0:
        state, note = NO_DATA, ("no decision point has been captured yet: nothing is concluded. This is the absence of "
                                "input, not a refusal and not a result")
    elif not fl["met"]:
        if past_stop:
            state, note = INCONCLUSIVE, (f"the stop date {config.STOP_DATE} passed with a floor unmet: "
                                         f"{fl['bets_with_reference']} of {config.BET_FLOOR} bets with a reference, "
                                         f"{fl['matches']} of {config.MATCH_FLOOR} matches, coverage {fl['coverage']}")
        else:
            state, note = COLLECTING, ("a floor is not met yet, so no effect statistic is shown: "
                                       f"{fl['bets_with_reference']}/{config.BET_FLOOR} bets with a reference, "
                                       f"{fl['matches']}/{config.MATCH_FLOOR} matches, coverage "
                                       f"{'n/a' if fl['coverage'] is None else round(fl['coverage'], 3)}"
                                       f"/{config.REFERENCE_COVERAGE_FLOOR}")
    else:
        effect = _effect_rows(ledger)
        m2 = _interval(effect, "m2")
        m1_mean = _mean([r["m1"] for r in effect])
        m2_mean = _mean([r["m2"] for r in effect])
        report["effect"] = {"n": len(effect), "m2_mean": m2_mean, "m2_interval": m2, "m1_mean": m1_mean,
                            "resamples": config.BOOTSTRAP_RESAMPLES, "seed": config.BOOTSTRAP_SEED}
        low = m2.get("low")
        if low is not None and low > 0 and m1_mean is not None and m1_mean > 0:
            state, note = PASS, ("M2's 95% match-clustered interval is entirely above zero and M1 is above zero. "
                                 "This licenses registering a replication window with the falsification battery; it is "
                                 "not a promotion, a pick or a claim of profit")
        else:
            direction = "below" if (m2_mean is not None and m2_mean < 0) else "not above"
            state, note = FAIL, (f"the floors are met and the PASS rule is not: M2 mean {m2_mean:+.3f} points "
                                 f"({direction} zero), M1 mean {m1_mean:+.3f}")
        report["descriptive"] = _descriptive(ledger, effect)
    report["state"], report["note"] = state, note
    report["registry_result"] = REGISTRY_RESULT.get(state) if state != COLLECTING and state != NO_DATA else None
    return report


def render(report: Mapping) -> str:
    lines = [f"LIVE_TENNIS_V1  {report['generated_utc']}", f"STATE  {report['state']}", f"  {report['note']}"]
    integ = report["integrity"]
    lines.append(f"ledger: exists={integ['ledger_exists']} chain_ok={integ['chain_ok']} "
                 f"first_capture={integ['first_capture_utc']}")
    if integ.get("fingerprint_problem"):
        lines.append(f"  FINGERPRINT PROBLEM: {integ['fingerprint_problem']}")
    c = report.get("counts")
    if c:
        lines += [f"decision points armed {c['armed']}  decisions {c['decisions']}  by status {c['by_status']}",
                  f"  reasons {c['by_reason']}",
                  f"  bets {c['bets']}  shadow {c['shadow_bets']}  references {c['references']}  "
                  f"no reference {c['no_reference']} {c['no_reference_causes']}  pending {c['bets_pending_reference']}",
                  f"  outcomes settled {c['outcomes']}  ticks {c['ticks']} (espn ok {c['ticks_with_espn']}, "
                  f"errors {c['tick_errors']})  unmatched live events {c['unmatched_live_events']}",
                  f"  guard refusals {c['guard_refusals']}",
                  f"credits: {c['credits_total']} total, "
                  f"{'n/a' if c['credits_per_active_day'] is None else round(c['credits_per_active_day'], 1)} per active day; "
                  f"by day {c['credits_by_day']}"]
    fl = report.get("floors")
    if fl:
        lines.append(f"floors: bets with reference {fl['bets_with_reference']}/{fl['bet_floor']}, matches "
                     f"{fl['matches']}/{fl['match_floor']}, coverage "
                     f"{'n/a' if fl['coverage'] is None else round(fl['coverage'], 3)}/{fl['coverage_floor']}, met={fl['met']}")
    if "effect" in report:
        e = report["effect"]
        lines.append(f"M2 (decisive) mean {e['m2_mean']:+.3f} pts  95% [{e['m2_interval'].get('low')}, "
                     f"{e['m2_interval'].get('high')}]  n={e['n']}  M1 mean {e['m1_mean']:+.3f}")
        lines.append("descriptive (cannot change the verdict): " + json.dumps(report.get("descriptive"), sort_keys=True, default=str))
    return "\n".join(lines)


def record_verdict(report: Mapping, *, registry_path=None, now: Optional[datetime] = None) -> dict:
    """Append the verdict to the alpha registry ONCE, for a final state only. Raises ValueError otherwise."""
    from src.research import alpha_registry as reg

    if report["state"] not in REGISTRY_RESULT:
        raise ValueError(f"state {report['state']} is not final: nothing to record")
    row = {
        "kind": "verdict", "id": config.REGISTRY_ID, "read_utc": (now or datetime.now(timezone.utc)).isoformat(),
        "result": REGISTRY_RESULT[report["state"]], "p": None,
        "effect": (report.get("effect") or {}).get("m2_mean"),
        "ci": ([report["effect"]["m2_interval"]["low"], report["effect"]["m2_interval"]["high"]]
               if report.get("effect") and report["effect"]["m2_interval"].get("low") is not None else None),
        "battery_version": None,
        "forward_window": {"start": (report["integrity"].get("first_capture_utc") or "")[:10] or None,
                           "n": (report.get("floors") or {}).get("bets_with_reference"), "pending": False},
        "note": f"{report['state']}: {report['note']}",
    }
    return reg.record_verdict(row, registry_path) if registry_path is not None else reg.record_verdict(row)
