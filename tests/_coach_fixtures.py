"""Shared fixtures for the coach brief and coach intake tests: a temp house scope, a temp tunables config, a temp
pack ledger and a synthetic book. Nothing here reads a live store."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.hounds.contract import ClvBlock, HoundSummary, Record, VerdictBlock
from src.hounds.learning import coach_brief as B
from src.hounds.learning import ledger as L
from src.hounds.learning import tunables
from tests import _learning_fixtures as LF

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
KNOB = {"name": "GAP", "label": "How far the model must beat the market (probability)", "kind": "float",
        "default": 0.02, "min": 0.015, "max": 0.04, "step": 0.005,
        "renders": [{"literal": "2.0 points or more", "format": "{:.1f} points or more", "scale": 100}]}
KNOB_INT = {"name": "BARS", "label": "Pitches", "kind": "int", "default": 120, "min": 80, "max": 200,
            "step": 20, "renders": [{"literal": "120 or more pitches", "format": "{:.0f} or more pitches",
                                     "scale": 1}]}


def tunable_config(path: Path, ids) -> dict:
    hounds = [{"id": hid, "name": hid.replace("_", " ").title(), "category": "stats",
               "module": "src.hounds.pack.stats", "rule_text": "Bets when it is 2.0 points or more.",
               "sports": ["mlb"], "markets": ["moneyline"], "tunable": [dict(KNOB), dict(KNOB_INT)]}
              for hid in ids]
    hounds.append({"id": "plain_dog", "name": "Plain Dog", "rule_text": "no knobs"})   # not tunable: never listed
    path.write_text(json.dumps({"hounds": hounds}), encoding="utf-8")
    return tunables.load(path)


def pack_ledger(path: Path, counts: dict) -> None:
    """counts: {(hound_id, version): graded forward bets}."""
    rows = []
    for (hid, version), n in counts.items():
        for i in range(n):
            bet = {"kind": "hound_bet", "hound_id": hid, "date": "2026-10-01", "event_id": f"{hid}-{version}-{i}",
                   "sport": "mlb", "market": "moneyline", "side": "home", "segment": "forward",
                   "bet_id": f"{hid}-{version}-{i}", "price_average": 110, "price_best": 112}
            if version > 1:
                bet["hound_version"] = version
            rows.append(bet)
            rows.append({"kind": "hound_graded", "hound_id": hid, "bet_id": bet["bet_id"], "result": "win",
                         "units_best_price": 1.12})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def book_of(ids) -> SimpleNamespace:
    hounds = {}
    for hid in ids:
        s = HoundSummary(id=hid, name=hid.replace("_", " ").title(), tagline="t", category="stats", style="s",
                         sports=["mlb"], markets=["moneyline"], rule_text="Bets when it is 2.0 points or more.",
                         record=Record(bets=60, wins=33, losses=27, units_recorded_price=4.2,
                                       units_average_price=3.1),
                         clv=ClvBlock(n=58, mean_pts=0.4, ci_low=-0.2, ci_high=1.0),
                         verdict=VerdictBlock(label="TOO EARLY", sentence="Not enough bets to say."))
        hounds[hid] = SimpleNamespace(summary=s, bets=[])
    return SimpleNamespace(hounds=hounds)


class World:
    """A temp house scope + config + ledger, with the helpers each test needs."""

    def __init__(self, ids=("alpha_pup", "beta_pup"), graded=60):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ids = tuple(ids)
        self.scope = L.Scope.house(self.root / "evidence")
        self.user_scope = L.Scope.user(self.root / "app")
        self.cfg = tunable_config(self.root / "house_pack.json", self.ids)
        self.ledger = self.root / "hounds_house_v1.jsonl"
        pack_ledger(self.ledger, {(hid, 1): graded for hid in self.ids})
        self.book = book_of(self.ids + ("plain_dog",))

    def close(self):
        self._tmp.cleanup()

    def brief(self, *, coach_on=True, now=NOW, paused=False) -> dict:
        with mock.patch("src.hounds.learning.pause.is_paused", return_value=paused):
            return B.build(self.book, scope_map={"house": self.scope, "user": self.user_scope},
                           tun_cfg=self.cfg, champion_ledger=self.ledger, coach_on=coach_on, now=now)

    def propose(self, cid, hound="alpha_pup", created="2026-11-19T00:00:00Z", values=None):
        return LF.propose_raw(self.scope, cid=cid, hound_id=hound, created=created,
                              values=values or {"GAP": 0.03})

    def end(self, cid, outcome="retired", reason="harm", utc="2026-11-10T00:00:00Z", hound="alpha_pup"):
        L.log_for(self.scope).append(L.K_DECISION, now=LF.utc(utc), scope="house", challenger_id=cid,
                                     hound_id=hound, outcome=outcome, reason=reason)
