"""Phase 1 of learning: read the owner's settled lessons, then PROPOSE paper rules in the owner's style.

FREEZE RULE (owner approved, tested): the pattern summary behind a proposal is computed ONLY from lessons that settled
BEFORE the proposal's time. ``frozen`` rebuilds every lesson from the events recorded before ``as_of`` alone, so a
result, a cash-out or a resolution that arrives afterwards cannot reach a proposal that is already on the table, and a
proposal made at time T can be recomputed byte for byte later. (A lesson filed but not yet settled at T is open at T.)

THE PROPOSAL goes through the existing Retune shape: ``propose`` is read only and returns a review card (what would
change, with the reasons and the numbers), ``apply`` makes a NEW VERSION of the hound through ``user_store.create_version``
(the one place that makes versions; the old version and every ticket on it stay as they were) only after the owner
confirms the card's ``basis``, and a card drawn for a rule that has since changed is refused as stale. Once applied the
hound bets PAPER tickets by its new rules like any hound: normal graded tickets in the hound's own ledger, apart from the
lessons (which are real money and live in their own tables and ledger). The -200 cap is not a setting: a rule's price
range never reaches -200 or worse, even when the owner's winners did.

HONEST FRAMING: with the vig, most patterns found in a small sample are noise. Every cut carries its ``n`` and the
diagnosis module's own sample-size level; nothing here says a pattern will keep winning.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.hounds import user_rules, user_spec, user_store
from src.hounds.apprentice import analytics, calc, model

MIN_SEGMENT = 3                 # fewer lessons than this in a cut is noise, not a pattern (the training module's own floor)
MAX_NEW_RULES = 3
MIN_SETTLED_TO_PROPOSE = 5      # the training module's own floor for a first proposal
HONESTY = ("These come from your own settled bets and carry no promise. With the book's cut, most patterns in a small "
           "sample are luck. Applying makes a new version that bets paper tickets only; your logged bets stay as they are.")
LEAD_BUCKETS = (("under an hour before the start", 0, 60), ("1 to 6 hours before the start", 60, 360),
                ("more than 6 hours before the start", 360, 10 ** 9))


def frozen(pairs: Sequence[tuple], as_of: datetime) -> list:
    """The lessons as they stood at ``as_of``: events recorded at or after it are dropped, and a lesson with none left is
    not a lesson yet. Returns ``[(lesson, events)]``."""
    cut = model.iso(as_of)
    out = []
    for lesson, events in pairs:
        before = [e for e in events if e["at_utc"] < cut]
        if before:
            out.append((lesson, before))
    return out


def _lead_minutes(lesson: Mapping) -> Optional[float]:
    times = [model.parse_time(leg.get("commence_time")) for leg in lesson["legs"]]
    placed = model.parse_time(lesson["placed_utc"])
    if placed is None or any(t is None for t in times):
        return None
    return (min(times) - placed).total_seconds() / 60.0


def _venue(lesson: Mapping) -> Optional[str]:
    if len(lesson["legs"]) != 1:
        return None
    return lesson["legs"][0].get("side")


def summarize(pairs: Sequence[tuple], as_of: datetime) -> dict:
    """The owner's patterns from lessons settled before ``as_of``: cuts by sport, market, price band, kind of price, side
    and how long before the start it was placed, each with its record, ROI and the diagnosis module's sample level."""
    from src.hounds.interact import diagnosis
    rows = [r for r in analytics.own_rows(analytics.build_rows(frozen(pairs, as_of))) if r["view"]["counts"]
            and r["view"]["state"] in (model.SETTLED,) and r["view"]["result"] in ("won", "lost", "push")]
    units = {r["lesson"]["id"]: r["view"]["profit"] / r["lesson"]["stake"] for r in rows}

    def dims(r) -> dict:
        lead = _lead_minutes(r["lesson"])
        bucket = next((label for label, lo, hi in LEAD_BUCKETS if lead is not None and lo <= lead < hi), None)
        return {**r["attrs"], "side": _venue(r["lesson"]), "timing": bucket}

    cuts = []
    for dim in ("sport", "market", "band", "role", "side", "timing"):
        tagged = [(dims(r)[dim], r) for r in rows]
        for key in sorted({k for k, _ in tagged if k is not None}):
            seg = [r for k, r in tagged if k == key]
            rest = [r for k, r in tagged if k != key]
            seg_u, rest_u = [units[r["lesson"]["id"]] for r in seg], [units[r["lesson"]["id"]] for r in rest]
            g = analytics._group(seg)
            z = diagnosis._z(seg_u, rest_u)
            cuts.append({"dimension": dim, "key": key, **g, "level": diagnosis.level_of(len(seg), z, cap="medium"),
                         "pushes": len(seg) - g["wins"] - g["losses"]})
    ids = sorted(r["lesson"]["id"] for r in rows)
    return {"as_of": model.iso(as_of), "settled": len(rows), "lesson_ids": ids,
            "overall": analytics._group(rows), "cuts": cuts,
            "basis": hashlib.sha256((model.iso(as_of) + "|" + ",".join(ids)).encode()).hexdigest()[:16]}


def _rule_for(sport: str, market: str, rows: Sequence[Mapping]) -> Optional[dict]:
    prices = sorted(r["lesson"]["legs"][0]["price"] for r in rows)
    sides = [r["lesson"]["legs"][0].get("side") for r in rows]
    pmin, pmax = max(prices[0], user_spec.SHORTEST_ALLOWED_PRICE), min(prices[-1], user_spec.LONGEST_ALLOWED_PRICE)
    if pmin > pmax:
        return None                                  # every winner was at -200 or worse: nothing a hound may bet
    side = "either"
    for s in ("home", "away", "over", "under"):
        if sides and sides.count(s) / len(sides) >= 0.75:
            side = s
    return {"label": "", "sports": [sport], "markets": [market], "side": side, "price_min": pmin, "price_max": pmax,
            "line_min": None, "line_max": None, "min_books": user_spec.DEFAULT_MIN_BOOKS_PROP
            if user_rules.market_kind(market) == "prop" else user_spec.DEFAULT_MIN_BOOKS_GAME, "when": None}


def propose(hound: Mapping, pairs: Sequence[tuple], now: Optional[datetime] = None) -> dict:
    """The read-only review card. Writes nothing. ``nothing`` is true (with a message) when no cut clears the floors."""
    from src.hounds.interact import training
    now = now or datetime.now(timezone.utc)
    summary = summarize(pairs, now)
    card = {"as_of": summary["as_of"], "summary": summary, "changes": [], "spec": None, "nothing": True, "message": "",
            "basis": f"{training.proposal_basis(hound['id'], hound['spec'])}@{summary['basis']}",
            "honesty": HONESTY, "paper_only": True}
    if summary["settled"] < MIN_SETTLED_TO_PROPOSE:
        card["message"] = (f"{summary['settled']} settled bets so far. It needs {MIN_SETTLED_TO_PROPOSE} before it can "
                           "say anything about your style.")
        return card
    frozen_rows = [r for r in analytics.own_rows(analytics.build_rows(frozen(pairs, now))) if r["view"]["counts"]
                   and r["view"]["state"] == model.SETTLED and len(r["lesson"]["legs"]) == 1]
    pairs_key: dict = {}
    for r in frozen_rows:
        leg = r["lesson"]["legs"][0]
        if leg["market"] in user_rules.ALL_MARKETS:
            pairs_key.setdefault((leg["sport"], leg["market"]), []).append(r)
    ranked = []
    for (sport, market), seg in pairs_key.items():
        g = analytics._group(seg)
        if len(seg) >= MIN_SEGMENT and g["profit"] > 0:
            ranked.append((-(g["roi"] or 0), sport, market, seg, g))
    ranked.sort(key=lambda t: t[:3])
    rules, changes = [], []
    for _roi, sport, market, seg, g in ranked:
        if len(rules) >= MAX_NEW_RULES:
            break
        rule = _rule_for(sport, market, [r for r in seg if r["view"]["result"] == "won"] or seg)
        if rule is None:
            continue
        try:
            user_spec.validate_spec({**{k: v for k, v in hound["spec"].items()}, "rules": rules + [rule]})
        except user_spec.SpecError:
            continue
        rules.append(rule)
        changes.append({"id": f"{sport}:{market}", "n": g["n"], "record": f"{g['wins']}-{g['losses']}",
                        "roi": g["roi"], "text": f"Back {sport} {market} between {rule['price_min']:+d} and "
                                                 f"{rule['price_max']:+d}" + ("" if rule["side"] == "either" else f", {rule['side']} side"),
                        "why": f"{g['wins']}-{g['losses']} on {g['n']} of your bets there, {g['roi']:+.0%} on the money staked"})
    if not rules:
        card["message"] = "None of your cuts has enough settled bets and a profit to turn into a rule yet."
        return card
    spec = {k: v for k, v in hound["spec"].items() if k not in ("sports", "markets")}
    spec["rules"] = rules
    spec["max_bets_per_day"] = min(spec.get("max_bets_per_day", 2), user_spec.MAX_BETS_RANGE[1])
    spec = user_spec.validate_spec(spec)
    card.update({"spec": spec, "changes": changes, "nothing": False})
    return card


class ApplyError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def apply(hound: Mapping, owner_id: int, pairs: Sequence[tuple], basis: str, *, as_of: str,
          now: Optional[datetime] = None, db=None) -> dict:
    """Make the proposal a new version of the hound. The owner must send the card's ``basis`` and ``as_of``; the proposal is
    RECOMPUTED at ``as_of`` from the frozen lessons and refused if it no longer matches (a different rule, or a card
    from before a different set of lessons)."""
    if hound["owner_user_id"] != owner_id:
        raise ApplyError("not_found", "no such hound", 404)
    moment = model.parse_time(as_of)
    if moment is None:
        raise ApplyError("bad_request", "as_of must be the time on the proposal card", 422)
    card = propose(hound, pairs, moment)
    if card["basis"] != basis:
        raise ApplyError("proposal_stale", "That proposal is out of date. Open it again and look at what changed.")
    if card["nothing"] or card["spec"] is None:
        raise ApplyError("nothing_to_change", card["message"] or "There is nothing to apply.")
    try:
        new = user_store.create_version(hound["id"], card["spec"], actor=f"owner:{owner_id}",
                                        reason="apprentice proposal from its lessons", now=now, db=db)
    except user_store.StoreError as exc:
        raise ApplyError(exc.code, str(exc), 404 if exc.code == "not_found" else 409)
    except user_spec.SpecError as exc:
        raise ApplyError("spec_invalid", "The proposed rule did not pass the menu's checks.", 422) from exc
    return {"hound": new, "changes": card["changes"], "paper_only": True}
