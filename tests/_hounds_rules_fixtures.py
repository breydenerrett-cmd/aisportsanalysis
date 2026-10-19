"""Fixtures for the rule-set (version-2) hound tests: a slate with game boards and a player-prop board, a
FactBook built from rows in hand, and spec helpers. Nothing here reads a live store.

The standard game is tests/_hounds_user_fixtures.py's (Seattle at home, Boston away, 23:10Z, 2026-10-20),
so a version-1 and a version-2 hound can be run on the same boards and compared. The prop board adds two
players:

  Pat Slugger   Seattle, batter total bases line 1.5, 5 books. The baseline board (16:00Z) has the over at
                -110; the gate board (21:05Z, 5 minutes before the 120-minute lock) has it at -130, so the
                market moved toward the over. A LATE board (22:20Z) must never be used.
  Sam Contact   Boston, batter hits line 0.5, over at -150 at the gate board, under +120.
  Hank Heavy    Seattle, batter total bases line 0.5, over at -300 (the -200 cap must refuse it).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.hounds import user_spec
from src.hounds.user_facts import FactBook
from tests._hounds_user_fixtures import (AWAY, BOOKS, DATE, EVENT, HOME, START, T_LATE, T_LOCK, T_OPEN,
                                         board_rows, standard_rows, utc)

T_BASE = "2026-10-20T16:00:00Z"
T_GATE = "2026-10-20T21:05:00Z"
NOW = utc("2026-10-20T21:30:00Z")       # after a 120-minute lock (21:10Z), before the 23:10Z start


def prop_rows(observed: str, rows) -> list:
    """Batter-store-shaped rows. rows: [(player, market, line, side, price, book)]."""
    out = []
    for player, market, line, side, price, book in rows:
        out.append({"event_id": EVENT, "market": market, "player": player, "book": book, "line": str(line),
                    "side": side, "price": price, "observed_utc": observed, "commence_time": START,
                    "home_team": HOME, "away_team": AWAY, "game_date": DATE})
    return out


def standard_props() -> list:
    rows = []
    for t, over, under in ((T_BASE, -110, -110), (T_GATE, -130, 105), (T_LATE, -400, 300)):
        rows += prop_rows(t, [("Pat Slugger", "batter_total_bases", 1.5, "Over", over, b) for b in BOOKS]
                          + [("Pat Slugger", "batter_total_bases", 1.5, "Under", under, b) for b in BOOKS])
    rows += prop_rows(T_GATE, [("Sam Contact", "batter_hits", 0.5, "Over", -150, b) for b in BOOKS[:3]]
                      + [("Sam Contact", "batter_hits", 0.5, "Under", 120, b) for b in BOOKS[:3]]
                      + [("Hank Heavy", "batter_total_bases", 0.5, "Over", -300, b) for b in BOOKS[:3]]
                      # a home-run prop quoted only on the over, by two books
                      + [("Pat Slugger", "batter_home_runs", 0.5, "Over", 320, b) for b in BOOKS[:2]])
    return rows


def box(player: str, team: str, day: str, pk: int, **stats) -> dict:
    base = {"type": "batter", "date": day, "game_pk": pk, "player_name": player, "team_name": team, "pa": 4,
            "ab": 4, "h": 0, "hr": 0, "rbi": 0, "r": 0, "total_bases": 0, "hits_runs_rbi": 0, "k": 0}
    base.update(stats)
    return base


def history_rows() -> list:
    """Slugger hit in each of his last 3 games (totals bases 2, 3, 2); Contact is 0-for in the last 3."""
    rows = []
    for i, (day, tb) in enumerate((("2026-10-14", 1), ("2026-10-15", 0), ("2026-10-16", 2), ("2026-10-17", 3),
                                   ("2026-10-18", 2))):
        rows.append(box("Pat Slugger", "Seattle Mariners", day, 900 + i, h=1 if tb else 0, total_bases=tb,
                        hr=1 if tb == 3 else 0))
        rows.append(box("Sam Contact", "Boston Red Sox", day, 900 + i, h=0))
    return rows


def team_games() -> list:
    """Seattle: won its last three (10-16, 10-17, 10-18). Boston: lost its last two (10-16, 10-17) and was
    off on 10-18, so it has 2 days off against Seattle's 1."""
    def g(day, home, away, hs, as_, hour="23:10:00Z"):
        return {"date": day, "start_utc": f"{day}T{hour}", "home": home, "away": away, "home_score": hs,
                "away_score": as_, "game_pk": f"g{day}{home}"}
    return [
        g("2026-10-15", "SEA", "TEX", 2, 3), g("2026-10-15", "BOS", "NYY", 4, 2),
        g("2026-10-16", "SEA", "TEX", 5, 1), g("2026-10-16", "BOS", "NYY", 1, 6),
        g("2026-10-17", "SEA", "TEX", 3, 2), g("2026-10-17", "BOS", "NYY", 0, 4),
        g("2026-10-18", "SEA", "TEX", 6, 2),
        # A game on the slate date itself, and one that had not finished at the lock: neither may count.
        {"date": "2026-10-20", "start_utc": "2026-10-20T17:00:00Z", "home": "BOS", "away": "TEX", "home_score": 9,
         "away_score": 0, "game_pk": "gsame"},
    ]


def weather_rows(game_pk: str = "824000") -> list:
    return [
        {"game_pk": game_pk, "observed_utc": "2026-10-20T15:00:00Z", "forecast_hour_offset_hours": 0.2,
         "temp_f": 48.0, "wind_mph": 14.0, "wind_from_deg": 200, "roof": "open", "precip_probability_pct": 10},
        # observed AFTER the lock (21:10Z): must never be read
        {"game_pk": game_pk, "observed_utc": "2026-10-20T21:20:00Z", "forecast_hour_offset_hours": 0.1,
         "temp_f": 90.0, "wind_mph": 2.0, "wind_from_deg": 20, "roof": "open", "precip_probability_pct": 90},
    ]


KNOWN_PLAYERS = frozenset({"pat slugger", "sam contact", "hank heavy", "aaron judge", "shohei ohtani"})


def patch_players(names=KNOWN_PLAYERS):
    """The box-score store decides who is a 'known player' when a spec names one; a test must not read the
    machine's store (it would pass or fail by checkout), so it names its own."""
    from unittest import mock
    return mock.patch("src.hounds.user_facts.known_player_keys", lambda root=None: frozenset(names))


def facts(**over) -> FactBook:
    kw = dict(mlb_games=team_games(), box_rows=history_rows(), weather_rows=weather_rows())
    kw.update(over)
    return FactBook(**kw)


PK_INDEX = {EVENT: {"game_pk": 824000}}


def rule(**over) -> dict:
    base = dict(sports=["MLB"], markets=["moneyline"], side="either", price_min=-199, price_max=1000,
                min_books=3)
    base.update(over)
    return base


def v2(rules=None, **over) -> dict:
    spec = dict(version=2, name=over.pop("name", "Rules Dog"), lock_minutes=120, max_bets_per_day=2,
                rules=rules if rules is not None else [rule()])
    spec.update(over)
    return spec


def hound(hid: str = "u-v2a", created_at: str = "2026-01-01T00:00:00Z", **over) -> dict:
    spec = user_spec.validate_spec(v2(**over))
    return {"id": hid, "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": created_at}


__all__ = ["patch_players", "KNOWN_PLAYERS", "T_BASE", "T_GATE", "NOW", "PK_INDEX", "standard_rows", "standard_props", "facts", "hound", "v2", "rule",
           "prop_rows", "box", "history_rows", "team_games", "weather_rows", "board_rows", "utc", "DATE", "EVENT",
           "T_OPEN", "T_LOCK", "T_LATE", "BOOKS"]
