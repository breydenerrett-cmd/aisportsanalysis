"""Synthetic champions, challengers and ledgers for the learning-loop tests. Nothing reads a live store.

``make_pair`` builds the bets of one champion and one challenger over a run of days with the
closing-line values already attached (the referee's input), so a test states the effect it wants
("the challenger is 2 points better on every shared slot") and reads the decision.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.hounds.ledgers import Bet
from src.hounds.learning import ledger as L

UTC = timezone.utc
FIRST_DAY = date(2026, 11, 2)


def scenario_clv(is_challenger: bool, event_id: str) -> float:
    """The closing-line value of the "must promote every time" scenario: +1.0 (challenger) or -1.0
    (champion) plus a per-slot noise of 0 to 0.5, so every paired difference lies in [1.5, 2.5] and the
    differences are NOT all equal.

    The noise is a function of the EVENT and the ROLE only, never of a bet id or a hound id. It used to
    be ``sum(map(ord, bet_id)) % 11``; the champion's and the challenger's bet ids differ by a prefix,
    so whenever the two prefixes' character sums agreed mod 11 (roughly one random id set in nine) the
    noise was identical on both sides, every difference was exactly +2.0, the cluster variance was
    exactly 0, the look had no p-value (the statistic gives none without variance) and the challenger
    could not cross. That was the intermittent failure: the TEST's data, not the referee's arithmetic."""
    digest = hashlib.sha256(f"{'chall' if is_challenger else 'champ'}|{event_id}".encode()).hexdigest()
    return (1.0 if is_challenger else -1.0) + (int(digest, 16) % 11) / 20


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def propose_raw(scope, *, cid="c-1", hound_id="professor_paws", kind="pack", created="2026-11-01T12:00:00Z",
                values=None, parent_version=1, parent_ref=None, category="stats", lineage=None,
                spec=None, spec_diff=None, hypothesis="A hypothesis that is long enough to pass.",
                evidence=("scorecard.record",)):
    spec = spec if spec is not None else {"values": values or {"GAP": 0.03, "SHRINK": 0.5}, "rule_text": "x"}
    return L.log_for(scope).append(
        L.K_PROPOSAL, now=utc(created), scope=scope.name, challenger_id=cid, hound_kind=kind,
        hound_id=hound_id, lineage_key=lineage or hound_id, category=category,
        parent_version=parent_version, parent_ref=parent_ref, spec=spec, spec_hash=f"hash-{cid}",
        spec_diff=spec_diff if spec_diff is not None else {"GAP": [0.02, 0.03]},
        hypothesis=hypothesis, evidence=list(evidence), proposed_by="coach")


def day_n(n: int) -> str:
    return (FIRST_DAY + timedelta(days=n)).isoformat()


def bet(hound_id, event_id, day, minute, clv, *, market="h2h", measurable=True, segment="forward",
        version=1, start_hour=19):
    return Bet(hound_id=hound_id, segment=segment, date=day,
               decision_utc=f"{day}T{start_hour - 1}:{minute:02d}:00Z",
               start_utc=f"{day}T{start_hour}:{minute:02d}:00Z", bet_id=f"{hound_id}:{event_id}:{market}",
               event_id=event_id, market_key=market, side="home", price=-110,
               clv_pts=clv, clv_measurable=measurable, hound_version=version, result="win", units=0.9)


def make_pair(*, days=30, per_day=4, champ_mean=-1.0, effect=0.0, noise=1.5, day_sd=1.0, seed=7,
              champ_id="professor_paws", chall_id="c-1", chall_bets_share=1.0, champ_bets_share=1.0,
              first_day=0, version=1):
    """(champion_bets, challenger_bets, event_ids). The challenger's value on a shared slot is the
    champion's plus ``effect``; ``chall_bets_share`` < 1 makes it pass on the rest (the pass-is-0 rule
    then applies)."""
    rng = random.Random(seed)
    champ, chall, events = [], [], []
    for d in range(days):
        day = day_n(first_day + d)
        shock = rng.gauss(0, day_sd)
        for i in range(per_day):
            eid = f"e{first_day + d:03d}-{i}"
            events.append(eid)
            base_value = champ_mean + shock + rng.gauss(0, noise)
            if rng.random() < champ_bets_share:
                champ.append(bet(champ_id, eid, day, i * 5, round(base_value, 4), version=version))
            if rng.random() < chall_bets_share:
                chall.append(bet(chall_id, eid, day, i * 5, round(base_value + effect + rng.gauss(0, 0.3), 4)))
    return champ, chall, events


def cover(scope, cid, event_ids, *, now="2026-11-01T13:00:00Z"):
    L.log_for(scope).append(L.K_COVERAGE, now=utc(now), scope=scope.name, covered={cid: list(event_ids)})


def temp_scope(tmp: str, name="house"):
    return L.Scope.house(Path(tmp)) if name == "house" else L.Scope.user(Path(tmp))
