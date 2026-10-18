"""Shared, offline fixtures for the desk hounds tests.

One synthetic MLB game (NYY at TB, tests/analyst_fixtures.py) and one synthetic NFL game (BUF at KC,
tests/nfl_analyst_fixtures.py), a temp folder standing in for the repo root, an injected clock, and canned
stage answers built FROM the packet so they are valid by construction. Nothing here reads the repo's data,
calls a model or touches a network (the `a-test-that-reads-the-disk` lesson).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.hounds.desk import prepare as prepare_mod
from src.hounds.desk import publish, roles, session, state
from tests import analyst_fixtures as F
from tests import nfl_analyst_fixtures as NF

ROOT = Path(__file__).resolve().parent.parent

SENTENCE = "The market looks about right to me and the data gives no strong reason to depart from it. "


def prose(n_words: int) -> str:
    """Plain lower-case prose of exactly `n_words` words: no number, no name, no banned word."""
    words = (SENTENCE * (n_words // 10 + 2)).split()[:n_words]
    return " ".join(words) + "."


def mlb_item(state_="pending", **overrides):
    base = {
        "payload": F.payload(state_), "multibook_rows": [dict(r, event_id="evt-nyy-tb") for r in F.multibook_rows()],
        "team_total_rows": F.team_total_rows(), "batter_prop_rows": F.batter_prop_rows(),
        "pitcher_prop_rows": F.pitcher_prop_rows(), "prop_board": F.prop_board(),
        "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
        "section_as_of": {"teams": "2026-10-02", "starters": "2026-10-02"},
    }
    base.update(overrides)
    return base


class Env(unittest.TestCase):
    """A temp repo root, a clock, and helpers to prepare a game and write answers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.out: list = []
        self.now = F.NOW

    @property
    def text(self) -> str:
        return "\n".join(self.out)

    def clock(self):
        return lambda: self.now

    # --- preparing ---------------------------------------------------------------------------
    def prepare_mlb(self, *items, game="NYY@TB", date=F.DATE, rehearsal=False):
        return prepare_mod.prepare(date, game, cfg=F.CFG, root=self.root, loader=lambda d: list(items) or [mlb_item()],
                                   now=self.clock(), out=self.out.append, rehearsal=rehearsal)

    def prepare_nfl(self, *, game="BUF@KC", rows=None, date=NF.DATE, rehearsal=False):
        if not hasattr(self, "_store"):
            self._store = NF.make_store(self.root / "league")
        return prepare_mod.prepare(date, game, sport="nfl", cfg=NF.CFG, root=self.root, store=self._store,
                                   rows=NF.odds_rows() if rows is None else rows,
                                   now=lambda: NF.NOW, out=self.out.append, rehearsal=rehearsal)

    def mlb_game(self) -> "state.Game":
        return state.load(state.game_folder("mlb", F.DATE, "NYY", "TB", self.root))

    def nfl_game(self) -> "state.Game":
        return state.load(state.game_folder("nfl", NF.DATE, "BUF", "KC", self.root))

    # --- answers -----------------------------------------------------------------------------
    @staticmethod
    def write(path: Path, value) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path


def report_answer(packet, stage, *, text=None, findings=None, focus=None, text_derived=None):
    role = roles.ROLES[stage]
    lo, hi = role.words
    lean = packet["markets"]["moneyline"]["lean"] if "moneyline" in packet["markets"] else None
    base_finding = {"claim": "The market names a favourite in this game.",
                    "evidence": [{"path": "markets.moneyline.lean", "value": lean}], "derived": []}
    return {"text": text if text is not None else prose((lo + hi) // 2),
            "text_derived": text_derived or [],
            "findings": findings if findings is not None else [base_finding],
            "focus": focus if focus is not None else []}


def option_index(packet, slot_id, selection) -> int:
    return [o["selection"] for o in packet["markets"][slot_id]["options"]].index(selection)


def take(packet, slot_id, selection, probability, *, price=None, book=None, reasons=None, case_against=None):
    """One TAKE decision on the option's best quote, valid by construction."""
    i = option_index(packet, slot_id, selection)
    opt = packet["markets"][slot_id]["options"][i]
    price = opt["best"]["price"] if price is None else price
    book = opt["best"]["book"] if book is None else book
    return {
        "slot_id": slot_id, "selection": selection, "verdict": "TAKE", "price": price, "book": book,
        "probability": probability,
        "reasons": reasons or [{"claim": "The quote is the best price in the data for this side.",
                                "evidence": [{"path": f"markets.{slot_id}.options[{i}].best.price",
                                              "value": opt["best"]["price"]}], "derived": []}],
        "case_against": case_against or {
            "claim": "The books already make the other side the favourite.",
            "evidence": [{"path": f"markets.{slot_id}.lean", "value": packet["markets"][slot_id]["lean"]}],
            "derived": []},
        "what_would_change_it": "A lineup change or a price move would change the call.",
    }


def decision_answer(packet, stage, takes=(), *, summary=None, summary_derived=None):
    role = roles.ROLES[stage]
    lo, hi = role.words
    return {"summary": summary if summary is not None else prose((lo + hi) // 2),
            "summary_derived": summary_derived or [], "decisions": list(takes)}


def just_above_fair(packet, slot_id, selection, bump=0.04) -> float:
    """A stated probability that beats the books' number and the average price's break-even by `bump`."""
    opt = packet["markets"][slot_id]["options"][option_index(packet, slot_id, selection)]
    from src.hounds.desk import risk
    avg = risk.board_average(opt)
    return round(max(opt["fair_probability"], risk.break_even(avg)) + bump, 4)


def other_item(away, home, pk):
    """A second synthetic game: the shared one under other clubs and another game pk."""
    item = mlb_item()
    adv = item["payload"]["advanced"]
    adv["away_team"], adv["home_team"] = away, home
    adv["game_id"] = f"{away}-{home}-2026-10-03-1"
    adv["game"].update(away_team=away, home_team=home, game_pk=pk)
    return item


class Flow(Env):
    """Helpers to drive a prepared game through its stages."""

    def setUp(self):
        super().setUp()
        self.takes: dict = {}          # stage -> [take builder(packet) -> decision]

    def silent(self, *_):
        pass

    def plan(self, **kw):
        return session.plan(F.DATE, cfg=F.CFG, now=self.clock(), out=self.out.append, root=self.root, **kw)

    def check_all(self):
        return session.check_all(F.DATE, now=self.clock(), out=self.out.append, root=self.root)

    def answer_for(self, game, stage):
        role = roles.ROLES[stage]
        if role.kind == roles.KIND_REPORT:
            return report_answer(game.packet, stage)
        takes = [t(game.packet) for t in self.takes.get(stage, [])]
        return decision_answer(game.packet, stage, takes)

    def drive(self, rounds=6):
        """Plan, answer every job cleanly, check; repeat until nothing is left to ask."""
        for _ in range(rounds):
            result = self.plan()
            if not result["jobs"]:
                return result
            for job in result["jobs"]:
                self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
            self.check_all()
        return self.plan()

    def publish(self, **kw):
        kw.setdefault("model", "claude-sonnet-5-5")
        return publish.publish(self.mlb_game(), cfg=F.CFG, now=self.clock(), out=self.out.append,
                               root=self.root, **kw)
