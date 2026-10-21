"""Read API over the MLB statsapi box-score store: the ESPN-fed leagues' reads, MLB data, sealed window enforced.

`MlbBoxService` is an `EspnService` over `MlbBoxStore`: schedule, game, team_history, player_history,
team_averages, team_splits, player_averages and player_splits behave exactly as they do for NBA or NHL
(including the point-in-time `as_of` rules). What differs:

* a date, `before` or `as_of` that reaches into the sealed window (2026-01-01..2026-08-27) is refused by name;
* standings, injuries, rosters and play-by-play are not stored here (the existing MLB stores and
  `DataClient.mlb_service()` carry standings, lineups and transactions);
* data starts on the day the layer started (2026-10-20): earlier dates are empty, not reconstructed.
"""

from __future__ import annotations

from typing import Any, Optional

from src.datasvc.client import unavailable
from src.datasvc.espn.service import CAPABILITIES, EspnService
from src.datasvc.mlb import seal
from src.datasvc.mlb.statsapi import ATTRIBUTION, LEAGUE, MlbBoxStore

_NOT_STORED = {
    "players": "rosters are not stored in the MLB box-score layer; player lines are (player_history)",
    "standings": "standings are not stored here (data/historical/standings.jsonl and DataClient.mlb_service carry them)",
    "injuries": "injuries are not stored here (the transactions watch carries IL moves)",
    "play_by_play": "play-by-play is not stored for MLB",
}


def _sealed_refusal(**dates: Optional[str]) -> Optional[dict]:
    for name, value in dates.items():
        if value and seal.is_sealed(value):
            return unavailable((name, f"{str(value)[:10]} is inside the sealed window "
                                      f"{seal.SEALED_FIRST}..{seal.SEALED_LAST}: MLB outcomes there are never read"))
    return None


class MlbBoxService(EspnService):
    def __init__(self, store: Optional[MlbBoxStore] = None, *, clock=None):
        super().__init__(store or MlbBoxStore(), clock=clock)

    def _league(self, league: str):
        if str(league).lower() != "mlb":
            raise KeyError(f"MlbBoxService serves 'mlb', not {league!r}")
        return LEAGUE

    def leagues(self):
        return [{"code": "mlb", "title": LEAGUE.title, "family": LEAGUE.family, "has_players": True,
                 "has_injuries": False, "stored": self.store.league_dir("mlb").exists()}]

    def capabilities(self, league: str = "mlb") -> dict:
        caps = {k: {"available": True, "via": v} for k, v in CAPABILITIES.items()}
        for name, reason in _NOT_STORED.items():
            caps[name] = {"available": False, "reason": reason}
        return caps

    def _ok(self, league: str, kind: str, data: Any, rows, as_of, **meta) -> dict:
        out = super()._ok(league, kind, data, rows, as_of, **meta)
        out["meta"]["source"] = "MLB statsapi (statsapi.mlb.com)"
        out["meta"]["attribution"] = ATTRIBUTION
        out["meta"]["sealed_window"] = f"{seal.SEALED_FIRST}..{seal.SEALED_LAST} outcomes are never read"
        out["meta"]["starts"] = seal.FORWARD_FROM.isoformat()
        return out

    # standings / injuries / rosters / play-by-play are not stored here
    def players(self, league: str = "mlb", **kw) -> dict:
        return unavailable(("players", _NOT_STORED["players"]))

    def standings(self, league: str = "mlb", **kw) -> dict:
        return unavailable(("standings", _NOT_STORED["standings"]))

    def injuries(self, league: str = "mlb", **kw) -> dict:
        return unavailable(("injuries", _NOT_STORED["injuries"]))

    def play_by_play(self, league: str = "mlb", *a, **kw) -> dict:
        return unavailable(("play_by_play", _NOT_STORED["play_by_play"]))

    # the sealed-window refusals, then the shared implementation
    def schedule(self, league: str, *, date=None, as_of=None, **kw):
        return _sealed_refusal(date=date, as_of=as_of) or super().schedule(league, date=date, as_of=as_of, **kw)

    def game(self, league: str, game_id: str, *, as_of=None):
        return _sealed_refusal(as_of=as_of) or super().game(league, game_id, as_of=as_of)

    def team_history(self, league: str, team: str, *, before=None, as_of=None, **kw):
        return _sealed_refusal(before=before, as_of=as_of) or super().team_history(league, team, before=before, as_of=as_of, **kw)

    def player_history(self, league: str, player_id: str, *, before=None, as_of=None, **kw):
        return _sealed_refusal(before=before, as_of=as_of) or super().player_history(league, player_id, before=before, as_of=as_of, **kw)

    def team_averages(self, league: str, team=None, *, as_of=None, **kw):
        return _sealed_refusal(as_of=as_of) or super().team_averages(league, team, as_of=as_of, **kw)

    def team_splits(self, league: str, team: str, *, as_of=None, **kw):
        return _sealed_refusal(as_of=as_of) or super().team_splits(league, team, as_of=as_of, **kw)

    def player_averages(self, league: str, player_id=None, *, as_of=None, **kw):
        return _sealed_refusal(as_of=as_of) or super().player_averages(league, player_id, as_of=as_of, **kw)

    def player_splits(self, league: str, player_id: str, *, as_of=None, **kw):
        return _sealed_refusal(as_of=as_of) or super().player_splits(league, player_id, as_of=as_of, **kw)
