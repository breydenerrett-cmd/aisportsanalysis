"""Fixtures for the coach report card tests: a fake tunable pack hound, deterministic boards and results.

The fake hound ``fake_dog`` bets the HOME moneyline when the board-average home price is at least
``MIN_PRICE`` (a module constant, exactly how a real tunable hound's knob works). Every fixture game has the
home club at +110, so the champion's value (100) bets every game and a suggestion of 120 passes every game: a
known, hand-checkable difference. Results are chosen per game, so a test decides whether the suggestion helps.

Nothing here reads a real store or ledger.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds import coach_card as C
from src.hounds.learning import tunables
from src.hounds.pack import base
from tests.test_house_pack_hounds import game_rows, mlb_game

UTC = timezone.utc
MODULE = "tests._coach_card_fakes_mod"

# a real module object registered under a name tunables.patched() can import_module
_mod = types.ModuleType(MODULE)
_mod.MIN_PRICE = 100
sys.modules[MODULE] = _mod


class FakeDog(base.Hound):
    id = "fake_dog"
    name = "Fake Dog"
    tagline = "t"
    category = "simple"
    style = "home dogs"
    sports = ("mlb",)
    markets = ("moneyline",)
    RULE = "Moneyline. Bet the home club when its price is +100 or more."

    def pick(self, board, ctx):
        home = base.side_info(board, "moneyline", "home")
        if not home or home["price_average"] < sys.modules[MODULE].MIN_PRICE:
            return []
        return [base.Selection("moneyline", "home", home["fair"], f"home dog at {home['price_average']:+d}")]


HOUND = FakeDog()
REGISTRY = {"fake_dog": HOUND}


def tunable_cfg() -> dict:
    knob = tunables.Knob(name="MIN_PRICE", label="Smallest home price that gets a bet", kind="int", default=100,
                         lo=100, hi=160, step=10,
                         renders=({"literal": "+100 or more", "format": "+{:.0f} or more", "scale": 1},))
    return {"fake_dog": tunables.TunableHound("fake_dog", "Fake Dog", "simple", MODULE,
                                              "Moneyline. Bet the home club when its price is +100 or more.",
                                              ("mlb",), ("moneyline",), {"MIN_PRICE": knob})}


def start_of(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T23:05:00").replace(tzinfo=UTC)


def lock_of(day: str) -> datetime:
    return start_of(day) - timedelta(minutes=60)


def iso_day(base_day: str, offset: int) -> str:
    return (datetime.fromisoformat(base_day) + timedelta(days=offset)).date().isoformat()


def stores_for(days_and_home_win) -> base.Stores:
    """One game per day, home club at +110 (away -130). ``days_and_home_win`` is [(day, bool)]: did the home
    club win. Every game is final in the results store."""
    st = base.Stores()
    games = []
    for i, (day, home_won) in enumerate(days_and_home_win):
        eid = f"fev{i}"
        start = start_of(day)
        for r in game_rows(eid, start, observed=start - timedelta(hours=10), home_ml=105, away_ml=-125):
            st.add_row(r)
        for r in game_rows(eid, start, observed=start - timedelta(hours=2), home_ml=110, away_ml=-130):
            st.add_row(r)
        st.event_map[eid] = {"game_pk": str(900000 + i), "event_id": eid}
        games.append(mlb_game(900000 + i, day, "NYY", "BOS", 2, 5) if home_won
                     else mlb_game(900000 + i, day, "NYY", "BOS", 5, 2))
    st.mlb_games = games
    st.mlb_covered = {g["date"] for g in games}
    st.bullpen = []
    st.finalize()
    return st


def suggestion_row(issue=1, recorded="2026-10-01T00:00:00Z", suggested=120, **extra) -> dict:
    cfg = tunable_cfg()["fake_dog"]
    champ = {"MIN_PRICE": 100}
    new = {"MIN_PRICE": suggested}
    row = {"issue": issue, "issue_url": f"https://github.com/x/y/issues/{issue}", "hound": "fake_dog",
           "hound_name": "Fake Dog", "champion_version": 1, "champion_values": champ, "suggested_values": new,
           "changes": C.change_list(cfg, champ, new),
           "hypothesis": "A higher bar should skip the weak spots.", "evidence": ["record.bets"],
           "mode": "practice", "challenger_id": None, "challenger_blocked_by": "not_enough_bets",
           "graded_forward_bets": 3, "recorded_utc": recorded, "issue_created_utc": recorded,
           "proposed_by": "zapier-coach"}
    row.update(extra)
    return row


def record(paths: C.Paths, **kw) -> dict:
    row = suggestion_row(**kw)
    now = C.parse(row["recorded_utc"])
    fields = {k: v for k, v in row.items()}
    return C.append(paths, C.K_SUGGESTION, now=now, **fields)


def paths_in(tmp: Path) -> C.Paths:
    return C.Paths.default(Path(tmp))
