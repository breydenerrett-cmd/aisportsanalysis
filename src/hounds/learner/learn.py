"""Phase 2: learn from the Learner's own settled bets, test forward, and PROPOSE. Never applies.

    python -m src.hounds.learner learn [--ledger P] [--now ISO] [--write]     # print the card; --write records it
    python -m src.hounds.learner apply PROPOSAL_ID --basis B --actor NAME     # the owner's step, nothing else calls it
    python -m src.hounds.learner veto PROPOSAL_ID --actor NAME
    python -m src.hounds.learner status

THE GUARD AGAINST FITTING TO LUCK (docs/TODO_UNTIL_SUNDAY.md item 8). The cutoff is eight days before ``now``. Training uses
only bets that STARTED and were GRADED before the cutoff; the next seven days of bets (started in ``[cutoff, cutoff+7d)``, graded
by ``now``) are the forward test and are never seen by the fit or by the choice of candidate segments. A segment is proposed
only if it was profitable on the training bets AND on the forward week AND the model's own predicted edge for it, on that
forward week, was positive. The last day before ``now`` is left out so that ungraded games cannot decide which bets count.

WITH FEWER THAN ``MIN_SETTLED`` SETTLED BETS it says "Not enough settled bets to learn yet." and proposes nothing. Below that, a
fitted model is a description of luck.

THE MODEL is plain Python: a standardised, L2-regularised logistic regression fitted by batch gradient descent, fixed iterations,
no random numbers, so the same bets give the same card byte for byte. numpy is not a dependency of this repo and is not used.
It predicts whether a bet wins; the card reports how its forward log-loss compares with the market's own de-vigged probability
(a model that cannot beat the price is not evidence of anything, and the card says so).

HONEST FRAMING: ``HONESTY`` rides on every card. The card says how many segments were tested; with the book's cut, some always
look good by chance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence

from src.hounds import learner
from src.hounds.learner import features as feat
from src.hounds.learner import state as lstate

MIN_SETTLED = 200               # "fewer than ~200 settled bets": the owner's floor (config/ai_hounds.json can raise it, never lower)
CUTOFF_DAYS = 8                 # cutoff = now - 8 days; the forward week is [cutoff, cutoff + 7 days); the last day is left to settle
FORWARD_DAYS = 7
MIN_TRAIN = 120                 # a fit on fewer is a description of luck even when the total clears MIN_SETTLED
MIN_FORWARD = 30                # the forward week needs this many settled bets to say anything
MIN_SEGMENT_TRAIN = 15
MIN_SEGMENT_FORWARD = 8
MAX_SEGMENTS = lstate.MAX_FOCUS_SEGMENTS
SETTLED = ("WIN", "LOSS", "PUSH")

CATEGORICAL = ("sport", "market", "role", "venue", "band", "day_of_week")
NUMERIC = ("books", "best_vs_avg_pts", "hours_to_start", "fair_move_pts", "line_move", "rest_edge", "start_hour_et",
           "fair_minus_break_even")
L2 = 1.0
ITERATIONS = 400
STEP = 0.2


# ---------------------------------------------------------------------------
# the settled bets
# ---------------------------------------------------------------------------

def settled_bets(rows: Sequence[Mapping], hound_id: str = learner.HOUND_ID) -> list:
    """Each of the hound's settled bets with its frozen features, as
    ``{key, features, result, units, stake, price, start, graded}``. The newest graded row for a bet counts (a late VOID is
    re-graded by the settler); a bet with no frozen features, or a result that is not WIN/LOSS/PUSH, is not a lesson."""
    from src.hounds.pack_run import KIND_BET, KIND_GRADED
    from src.hounds.pack import base

    graded = {}
    for r in rows:
        if r.get("kind") == KIND_GRADED and r.get("hound_id") == hound_id:
            graded[(r["event_id"], r["market"], r["selection"])] = r
    out = []
    for b in rows:
        if b.get("kind") != KIND_BET or b.get("hound_id") != hound_id or not b.get("learner_features"):
            continue
        g = graded.get((b["event_id"], b["market"], b["selection"]))
        if g is None or g.get("result") not in SETTLED or g.get("units_average_price") is None:
            continue
        out.append({"key": f"{b['event_id']}|{b['market']}|{b['selection']}", "features": b["learner_features"],
                    "result": g["result"], "units": float(g["units_average_price"]), "stake": float(g.get("stake") or 1.0),
                    "price": b["price_average"], "start": base.parse_utc(b["start_utc"]),
                    "graded": base.parse_utc(g.get("graded_utc"))})
    out.sort(key=lambda s: (s["start"], s["key"]))
    return [s for s in out if s["start"] is not None and s["graded"] is not None]


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

class Encoder:
    """One-hot for the categorical features, standardised numerics with a missing flag, fitted on the TRAINING bets only."""

    def __init__(self, train: Sequence[Mapping]):
        self.levels = {c: sorted({str(s["features"].get(c)) for s in train if s["features"].get(c) is not None}) for c in CATEGORICAL}
        self.stats, self.flagged = {}, []
        for n in NUMERIC:
            vals = [float(s["features"][n]) for s in train if s["features"].get(n) is not None]
            if len(vals) < len(train):
                self.flagged.append(n)
            mean = sum(vals) / len(vals) if vals else 0.0
            var = sum((v - mean) ** 2 for v in vals) / len(vals) if vals else 0.0
            self.stats[n] = (mean, math.sqrt(var) or 1.0)

    def vector(self, f: Mapping) -> list:
        v = [1.0]
        for c in CATEGORICAL:
            v.extend(1.0 if f.get(c) is not None and str(f.get(c)) == lvl else 0.0 for lvl in self.levels[c])
        for n in NUMERIC:
            mean, sd = self.stats[n]
            raw = f.get(n)
            v.append(0.0 if raw is None else (float(raw) - mean) / sd)
            if n in self.flagged:
                v.append(1.0 if raw is None else 0.0)
        return v


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def fit_logistic(X: Sequence[Sequence[float]], y: Sequence[int], *, l2: float = L2, iterations: int = ITERATIONS,
                 step: float = STEP) -> list:
    """Batch gradient descent on the L2-penalised log-loss (the intercept, column 0, is not penalised). Deterministic."""
    n, k = len(X), len(X[0])
    w = [0.0] * k
    for _ in range(iterations):
        grad = [0.0] * k
        for xi, yi in zip(X, y):
            err = _sigmoid(sum(a * b for a, b in zip(w, xi))) - yi
            for j in range(k):
                grad[j] += err * xi[j]
        for j in range(k):
            w[j] -= step * (grad[j] / n + (l2 / n * w[j] if j else 0.0))
    return w


def predict(w: Sequence[float], x: Sequence[float]) -> float:
    return _sigmoid(sum(a * b for a, b in zip(w, x)))


def log_loss(pairs: Sequence[tuple]) -> Optional[float]:
    """Mean log-loss of ``[(p, outcome)]``, probabilities clamped away from 0 and 1; None for an empty list."""
    if not pairs:
        return None
    return -sum(math.log(min(max(p, 1e-6), 1 - 1e-6) if o else 1 - min(max(p, 1e-6), 1 - 1e-6)) for p, o in pairs) / len(pairs)


# ---------------------------------------------------------------------------
# the proposal
# ---------------------------------------------------------------------------

def _roi(bets: Sequence[Mapping]) -> Optional[float]:
    staked = sum(b["stake"] for b in bets)
    return round(sum(b["units"] for b in bets) / staked, 4) if staked else None


def _record(bets: Sequence[Mapping]) -> dict:
    return {"n": len(bets), "wins": sum(1 for b in bets if b["result"] == "WIN"),
            "losses": sum(1 for b in bets if b["result"] == "LOSS"), "roi": _roi(bets)}


def _by_segment(bets: Sequence[Mapping]) -> dict:
    out: dict = {}
    for b in bets:
        seg = feat.segment_of(b["features"])
        if seg is not None:
            out.setdefault(seg, []).append(b)
    return out


def cutoff_for(now: datetime) -> datetime:
    day = (now - timedelta(days=CUTOFF_DAYS)).astimezone(timezone.utc)
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


def propose(rows: Sequence[Mapping], *, now: datetime, rules_version: int = 0, hound_id: str = learner.HOUND_ID,
            min_settled: int = MIN_SETTLED) -> dict:
    """The review card. Read only: it writes nothing and applies nothing. ``nothing`` is True, with a ``message``, whenever the
    bets cannot support a proposal. Same bets and same ``now`` give the same card."""
    from src.hounds.pack import base

    now = now.astimezone(timezone.utc)
    cutoff = cutoff_for(now)
    end = cutoff + timedelta(days=FORWARD_DAYS)
    allbets = [b for b in settled_bets(rows, hound_id) if b["graded"] <= now]
    train = [b for b in allbets if b["start"] < cutoff and b["graded"] < cutoff]
    forward = [b for b in allbets if cutoff <= b["start"] < end]
    card = {"as_of": base.iso(now), "cutoff": base.iso(cutoff), "forward_end": base.iso(end), "rules_version": rules_version,
            "settled": len(allbets), "train_n": len(train), "forward_n": len(forward), "nothing": True, "message": "",
            "segments": [], "changes": [], "segments_tested": 0, "model": None, "proposal_id": None, "basis": None,
            "honesty": learner.HONESTY, "paper_only": True}
    floor = max(MIN_SETTLED, int(min_settled))
    if len(allbets) < floor:
        card["message"] = f"{learner.NOT_ENOUGH} {len(allbets)} settled so far; it needs {floor} before it will propose anything."
        return card
    if len(train) < MIN_TRAIN or len(forward) < MIN_FORWARD:
        card["message"] = (f"{len(allbets)} settled, but only {len(train)} before the cutoff and {len(forward)} in the week after "
                           f"it (needs {MIN_TRAIN} and {MIN_FORWARD}). Nothing is proposed from a split this thin.")
        return card
    train_y = [1 if b["result"] == "WIN" else 0 for b in train if b["result"] != "PUSH"]
    if not any(train_y) or all(train_y):
        card["message"] = "The training bets are all wins or all losses, so there is nothing to fit. Nothing is proposed."
        return card
    enc = Encoder(train)
    fit_rows = [b for b in train if b["result"] != "PUSH"]
    w = fit_logistic([enc.vector(b["features"]) for b in fit_rows], train_y)
    phat = {b["key"]: predict(w, enc.vector(b["features"])) for b in forward}
    scored = [(b, phat[b["key"]]) for b in forward if b["result"] != "PUSH"]
    mkt_pairs = [(b["features"].get("consensus_fair"), 1 if b["result"] == "WIN" else 0) for b, _ in scored
                 if b["features"].get("consensus_fair") is not None]
    mdl_pairs = [(p, 1 if b["result"] == "WIN" else 0) for b, p in scored if b["features"].get("consensus_fair") is not None]
    mdl_ll, mkt_ll = log_loss(mdl_pairs), log_loss(mkt_pairs)
    card["model"] = {"kind": "logistic regression, plain Python", "features": list(CATEGORICAL) + list(NUMERIC),
                     "forward_log_loss": None if mdl_ll is None else round(mdl_ll, 4),
                     "market_log_loss": None if mkt_ll is None else round(mkt_ll, 4),
                     "beats_market_price": bool(mdl_ll is not None and mkt_ll is not None and mdl_ll < mkt_ll)}
    t_seg, f_seg = _by_segment(train), _by_segment(forward)
    candidates = [s for s, bs in t_seg.items() if len(bs) >= MIN_SEGMENT_TRAIN]
    card["segments_tested"] = len(candidates)
    held = []
    for seg in candidates:
        fb = f_seg.get(seg, [])
        if len(fb) < MIN_SEGMENT_FORWARD:
            continue
        t_roi, f_roi = _roi(t_seg[seg]), _roi(fb)
        edge = sum(phat[b["key"]] - base.break_even(b["price"]) for b in fb) / len(fb)
        if t_roi is not None and f_roi is not None and t_roi > 0 and f_roi > 0 and edge > 0:
            held.append((-f_roi, -t_roi, seg, round(edge, 4)))
    held.sort()
    if not held:
        card["message"] = (f"Tested {len(candidates)} segments on {len(train)} training bets and the next week's {len(forward)}. "
                           "None was profitable in both, so nothing is proposed. That is the usual result.")
        return card
    chosen = held[:MAX_SEGMENTS]
    changes = [{"id": "|".join(map(str, seg)), "text": f"Narrow toward {feat.segment_text(seg)}",
                "train": _record(t_seg[seg]), "forward": _record(f_seg[seg]), "model_edge": edge,
                "why": (f"Profitable on {len(t_seg[seg])} bets before the cutoff and on {len(f_seg[seg])} in the week after "
                        f"it, which the fit had not seen. {learner.HONESTY.split('. ')[1]}.")}
               for _fr, _tr, seg, edge in chosen]
    segments = [seg for _fr, _tr, seg, _e in chosen]
    basis = hashlib.sha256(json.dumps([hound_id, rules_version, card["cutoff"], [b["key"] for b in train],
                                       [list(s) for s in segments]], sort_keys=True).encode()).hexdigest()[:16]
    card.update({"nothing": False, "segments": segments, "changes": changes, "basis": basis, "proposal_id": f"lp-{basis[:10]}",
                 "message": f"{len(segments)} segment(s) held up on the forward week. Review before applying."})
    return card


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    from src.hounds import ai_defs
    from src.hounds.pack import base
    from src.ledger.chain import HashChainLedger

    ap = argparse.ArgumentParser(prog="python -m src.hounds.learner", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("learn", "apply", "veto", "status"))
    ap.add_argument("proposal_id", nargs="?")
    ap.add_argument("--ledger")
    ap.add_argument("--now")
    ap.add_argument("--write", action="store_true", help="record the card as a pending proposal (still not applied)")
    ap.add_argument("--basis")
    ap.add_argument("--actor", default="owner")
    args = ap.parse_args(argv)
    ledger = ai_defs.ledger_path(args.ledger)
    path = lstate.events_path(ledger)
    now = base.parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    try:
        if args.command == "status":
            st = lstate.read(path)
            print(json.dumps({"version": st["version"], "focus": [feat.segment_text(s) for s in st["focus"]],
                              "pending": st["pending"]["proposal_id"] if st["pending"] else None}, indent=2))
        elif args.command == "learn":
            rows = HashChainLedger(ledger).read()
            card = propose(rows, now=now, rules_version=lstate.read(path)["version"])
            print(json.dumps(card, indent=2, sort_keys=True))
            if args.write and not card["nothing"]:
                lstate.record_proposal(path, card, now=now)
        elif args.command == "apply":
            if not (args.proposal_id and args.basis):
                ap.error("apply needs a proposal id and --basis")
            lstate.apply(path, args.proposal_id, args.basis, actor=args.actor, now=now)
            print("applied; the Learner now draws most bets from the focus and keeps exploring")
        else:
            if not args.proposal_id:
                ap.error("veto needs a proposal id")
            lstate.veto(path, args.proposal_id, actor=args.actor, now=now)
            print("vetoed")
    except lstate.StateError as exc:
        print(f"refused ({exc.code}): {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
