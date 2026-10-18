"""The system scorecard: is the loop improving anything at all? (docs/PREREG_LEARNING_LOOP.md section 9b)

Three honest lines, computed once a day and stored as an event so the page reads a ledger, not a scan:

  (a) PROMOTION HIT RATE. Of promoted challengers whose new champion version has 100 measurable bets
      since promotion ("matured"), the share whose mean closing-line value over those first 100 is at
      or above the replaced champion's mean over the slots of the test that promoted the challenger.
      Null until a promotion has matured. Winner's-curse regression is expected, which is why the
      auto-pause floor is 0.40 and not 0.50.
  (b) BETTER THAN CHANCE. The champions' mean forward closing-line value over the last 30 and 90 days
      against the two random control hounds, taken ONLY over the games on which at least one champion
      and at least one control had a measurable bet. Null below 50 bets on either side. The only honest
      "are we better than chance" line: both sides pay the book's margin, so the difference is the point.
  (c) ACTIVITY AND THE FALSE-DISCOVERY BUDGET. Proposals, refusals, promotions, retirements, undos,
      live challengers against the caps, and what the Benjamini-Hochberg budget has spent.

AUTO-PAUSE (``evaluate_pause``): at least 10 matured promotions with a hit rate under 0.40, or the
champions trailing the controls on each of the last 60 daily scorecards. The pause itself is
``pause.pause``; only the owner's ``resume`` lifts it.

Pure given its inputs: the measured bets come from the stats book (``book.clv_bets``) and the matured
promotions' bets from a callable, so tests hand it fixtures.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Optional, Sequence

from src.hounds.learning import ledger as L
from src.hounds.learning import pause, rules


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


# ---- (b) champions against the random controls, on the same games ------------------------------------------

def champion_ids(hound_info: Mapping) -> set:
    """Running hounds that are not instruments, controls or for-fun hounds (prereg section 9b)."""
    out = set()
    for hid, info in hound_info.items():
        if "@v" in hid:
            continue                                   # an archived earlier version is not a champion
        if info.get("kind") == "baseline" or info.get("category") in rules.NON_CHAMPION_CATEGORIES:
            continue
        if info.get("status") == "retired":
            continue
        if hid in rules.CONTROL_IDS:
            continue
        out.add(hid)
    return out


def vs_random(clv_bets: Sequence[tuple], hound_info: Mapping, *, as_of: date, days: int) -> dict:
    """The champions' pooled mean CLV against the controls' over the last ``days`` days, same games."""
    first = (as_of - timedelta(days=days - 1)).isoformat()
    last = as_of.isoformat()
    champs, ctrls = champion_ids(hound_info), set(rules.CONTROL_IDS)
    champ_by_event: dict = {}
    ctrl_by_event: dict = {}
    for hid, event_id, _market, day, pts in clv_bets:
        if not (first <= str(day)[:10] <= last):
            continue
        if hid in champs:
            champ_by_event.setdefault(event_id, []).append(pts)
        elif hid in ctrls:
            ctrl_by_event.setdefault(event_id, []).append(pts)
    shared = set(champ_by_event) & set(ctrl_by_event)
    c_vals = [v for e in shared for v in champ_by_event[e]]
    r_vals = [v for e in shared for v in ctrl_by_event[e]]
    out = {"days": days, "games": len(shared), "champion_bets": len(c_vals), "control_bets": len(r_vals),
           "champion_mean": None, "control_mean": None, "difference": None, "enough": False}
    if len(c_vals) >= rules.MIN_BETS_FOR_COMPARISON and len(r_vals) >= rules.MIN_BETS_FOR_COMPARISON:
        out.update({"champion_mean": _mean(c_vals), "control_mean": _mean(r_vals), "enough": True})
        out["difference"] = round(out["champion_mean"] - out["control_mean"], 4)
    return out


# ---- (a) the promotion hit rate -------------------------------------------------------------------------------

def hit_rate(state: L.State, matured_fn: Callable) -> dict:
    """``matured_fn(promotion) -> (mean_of_first_100, n_measurable) | None`` supplies the new champion
    version's bets since promotion (the caller measures them)."""
    details = []
    for promo in state.promotions:
        replaced = promo.get("replaced_mean")
        got = matured_fn(promo) if promo.get("applied") else None
        row = {"challenger_id": promo.get("challenger_id"), "hound_id": promo.get("hound_id"),
               "to_version": promo.get("to_version"), "promoted_utc": promo.get("utc"),
               "replaced_mean": replaced, "new_mean": None, "n": 0, "matured": False, "hit": None}
        if got is not None:
            new_mean, n = got
            row.update({"new_mean": new_mean, "n": n})
            if n >= rules.MATURE_BETS and replaced is not None and new_mean is not None:
                row["matured"] = True
                row["hit"] = bool(new_mean >= replaced)
        details.append(row)
    matured = [d for d in details if d["matured"]]
    hits = sum(1 for d in matured if d["hit"])
    return {"promotions": len(details), "matured": len(matured), "hits": hits,
            "rate": round(hits / len(matured), 4) if matured else None,
            "floor": rules.HIT_RATE_FLOOR, "min_matured_for_floor": rules.MIN_MATURED_FOR_FLOOR,
            "details": details}


# ---- (c) activity and the false-discovery budget ----------------------------------------------------------------

def activity(state: L.State, *, now: datetime) -> dict:
    cs = list(state.challengers.values())
    month = L.month_of(L.iso(now))
    promoted = [c for c in cs if c.status == rules.OUTCOME_PROMOTED]
    bound = 0.0
    for c in promoted:
        p = (c.decision or {}).get("bh", {}) or {}
        bound += float(p.get("p_adj") or 0.0)
    return {
        "proposals": len(cs), "refusals": len(state.refusals), "held_rounds": len(state.helds),
        "promotions": len(state.promotions), "retirements": sum(1 for c in cs if c.status == rules.OUTCOME_RETIRED),
        "undecided": sum(1 for c in cs if c.status == rules.OUTCOME_UNDECIDED),
        "undos": len(state.undos), "live": len(state.live()),
        "caps": {"live_per_hound": rules.MAX_LIVE_PER_HOUND, "live_per_scope": rules.MAX_LIVE_PER_SCOPE},
        "false_discovery_budget": {
            "q": rules.BH_Q, "month": month,
            "promotions_this_month": state.promotions_in_month(month),
            "monthly_cap": rules.MAX_PROMOTIONS_PER_MONTH,
            "expected_false_promotions_bound": round(bound, 4),
            "note": "the sum of the adjusted p-values of every promotion: an upper bound on how many "
                    "of them are expected to be null results",
        },
    }


# ---- the pause rule ------------------------------------------------------------------------------------------------

def trailing_streak(state: L.State, today: date, today_diff: Optional[float]) -> int:
    """Consecutive calendar days ending ``today`` whose scorecard shows champions below the controls
    on the rolling 30 days. A missing day or a null comparison ends the streak (it counts as not trailing)."""
    by_day = {}
    for sc in state.scorecards:
        diff = (((sc.get("payload") or {}).get("vs_random") or {}).get("windows") or {}).get("30", {})
        by_day[str(sc.get("date"))] = diff.get("difference")
    by_day[today.isoformat()] = today_diff
    n = 0
    for i in range(rules.TRAIL_DAYS):
        d = (today - timedelta(days=i)).isoformat()
        v = by_day.get(d)
        if v is None or not v < 0:
            break
        n += 1
    return n


def evaluate_pause(state: L.State, hit: dict, today: date, today_diff: Optional[float]) -> Optional[str]:
    """The reason to pause, or None."""
    if (hit["matured"] >= rules.MIN_MATURED_FOR_FLOOR and hit["rate"] is not None
            and hit["rate"] < rules.HIT_RATE_FLOOR):
        return (f"promotion hit rate {hit['rate']:.2f} is under the {rules.HIT_RATE_FLOOR:.2f} floor "
                f"over {hit['matured']} matured promotions")
    streak = trailing_streak(state, today, today_diff)
    if streak >= rules.TRAIL_DAYS:
        return (f"the champions have trailed the random controls on each of the last {rules.TRAIL_DAYS} "
                f"daily scorecards")
    return None


# ---- the whole card ---------------------------------------------------------------------------------------------------

def compute(scope: L.Scope, *, now: datetime, clv_bets: Sequence[tuple], hound_info: Mapping,
            matured_fn: Callable, state: Optional[L.State] = None) -> dict:
    """The scorecard payload for one scope (not stored). ``state`` defaults to the scope's own."""
    st = state or L.read_state(scope)
    today = now.date() if now.tzinfo is None else now.astimezone(timezone.utc).date()
    windows = {str(d): vs_random(clv_bets, hound_info, as_of=today, days=d) for d in rules.ROLLING_DAYS}
    hit = hit_rate(st, matured_fn)
    act = activity(st, now=now)
    streak = trailing_streak(st, today, windows["30"]["difference"])
    reason = evaluate_pause(st, hit, today, windows["30"]["difference"])
    paused_now = pause.is_paused(scope)
    last_pause = st.last_pause()
    return {
        "scope": scope.name, "date": today.isoformat(),
        "promotion_hit_rate": hit,
        "vs_random": {
            "windows": windows, "controls": list(rules.CONTROL_IDS),
            "champions_counted": len(champion_ids(hound_info)),
            "basis": ("Champions' mean closing-line value against the two random control hounds, over "
                      "the same games only. Both pay the book's margin, so a champion that is no better "
                      "than chance sits at the controls' level; 'enough' needs 50 bets on each side."),
            "trailing_days": streak,
        },
        "activity": act,
        "pause": {"paused": paused_now or reason is not None,
                  "reason": (reason or (last_pause or {}).get("reason")) if paused_now else reason,
                  "since": (last_pause or {}).get("utc") if paused_now else None,
                  "owner_must_resume": True,
                  "rules": {"hit_rate_floor": rules.HIT_RATE_FLOOR,
                            "min_matured_promotions": rules.MIN_MATURED_FOR_FLOOR,
                            "trailing_days": rules.TRAIL_DAYS}},
        "chain": L.chain_report(scope),
        "paper_only": True,
    }


def store(scope: L.Scope, payload: dict, *, now: datetime) -> dict:
    """Append the day's scorecard (once per date), then apply the pause rule to it."""
    st = L.read_state(scope)
    if any(str(sc.get("date")) == payload["date"] for sc in st.scorecards):
        return {"stored": False, "reason": "already stored today"}
    L.log_for(scope).append(L.K_SCORECARD, now=now, scope=scope.name, date=payload["date"], payload=payload)
    pause_reason = None
    if not pause.is_paused(scope):
        diff = payload["vs_random"]["windows"]["30"]["difference"]
        pause_reason = evaluate_pause(L.read_state(scope), payload["promotion_hit_rate"],
                                      date.fromisoformat(payload["date"]), diff)
        if pause_reason:
            pause.pause(scope, pause_reason, now=now)
    return {"stored": True, "paused": pause_reason}


def run_daily(scope: L.Scope, *, now: datetime, clv_bets: Sequence[tuple], hound_info: Mapping,
              matured_fn: Callable) -> dict:
    payload = compute(scope, now=now, clv_bets=clv_bets, hound_info=hound_info, matured_fn=matured_fn)
    out = store(scope, payload, now=now)
    out["payload"] = payload
    return out


# ---- merging the two scopes for the public page ----------------------------------------------------------------------------

def latest(scope: L.Scope) -> Optional[dict]:
    sc = L.read_state(scope).latest_scorecard()
    return dict(sc["payload"], stored_utc=sc.get("utc")) if sc and sc.get("payload") else None


def merge(cards: Mapping) -> dict:
    """Sum the counts of the scopes' scorecards; the chance line is shared, so the freshest one is used."""
    present = {k: v for k, v in cards.items() if v}
    if not present:
        return {}
    keys = ("promotions", "matured", "hits")
    hit = {k: sum(c["promotion_hit_rate"][k] for c in present.values()) for k in keys}
    hit["rate"] = round(hit["hits"] / hit["matured"], 4) if hit["matured"] else None
    hit["floor"] = rules.HIT_RATE_FLOOR
    hit["min_matured_for_floor"] = rules.MIN_MATURED_FOR_FLOOR
    act_keys = ("proposals", "refusals", "held_rounds", "promotions", "retirements", "undecided", "undos", "live")
    act = {k: sum(c["activity"][k] for c in present.values()) for k in act_keys}
    fd = {"q": rules.BH_Q,
          "promotions_this_month": sum(c["activity"]["false_discovery_budget"]["promotions_this_month"]
                                       for c in present.values()),
          "monthly_cap_per_scope": rules.MAX_PROMOTIONS_PER_MONTH,
          "expected_false_promotions_bound": round(sum(
              c["activity"]["false_discovery_budget"]["expected_false_promotions_bound"]
              for c in present.values()), 4)}
    freshest = max(present.values(), key=lambda c: c.get("date") or "")
    return {"promotion_hit_rate": hit, "vs_random": freshest["vs_random"], "activity": act,
            "false_discovery_budget": fd,
            "paused": any((c.get("pause") or {}).get("paused") for c in present.values()),
            "pause_reasons": [dict(scope=k, reason=c["pause"].get("reason"), since=c["pause"].get("since"))
                              for k, c in present.items() if (c.get("pause") or {}).get("paused")]}
