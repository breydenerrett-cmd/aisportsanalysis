"""Builders for the LIVE_TENNIS_V1 tests: ESPN scoreboard documents, Odds API events, a scripted world and a fake clock.

Nothing here touches the network, the real ledger or the real credit log. A test that needs a world builds a
`World`, hands its seams to a `Runner` with temp paths, and moves the clock itself.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.research.live_tennis import config
from src.research.live_tennis.runner import Seams

KEY = "tennis_atp_test_open"
HOME = "Alex Homeplayer"
AWAY = "Bob Awayplayer"
START = "2026-11-02T10:00:00Z"
MATCH_ID = "900001"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def competition(match_id: str, a_name: str, b_name: str, *, status: str, state: str, sets: List[Tuple[int, int]],
                start: str = "2026-11-02T10:00Z", winner: Optional[str] = None, possession: Optional[str] = None) -> dict:
    """One ESPN singles competition. `a` is order 1, `b` order 2; `winner` is 'a' / 'b' / None."""
    def competitor(order: int, name: str, mine: List[int], flagged: Optional[bool], serving: bool) -> dict:
        body = {"order": order, "id": f"{match_id}-{order}", "type": "athlete",
                "athlete": {"displayName": name, "fullName": name},
                "linescores": [{"value": float(g)} for g in mine]}
        if flagged is not None:
            body["winner"] = flagged
        if serving:
            body["possession"] = True
        return body

    a_games = [a for a, _ in sets]
    b_games = [b for _, b in sets]
    return {"id": match_id, "startDate": start, "date": start,
            "status": {"type": {"name": status, "state": state}},
            "competitors": [competitor(1, a_name, a_games, (winner == "a") if winner else None, possession == "a"),
                            competitor(2, b_name, b_games, (winner == "b") if winner else None, possession == "b")],
            "round": {"displayName": "Round 1"}, "notes": []}


def scoreboard(*competitions: dict, tournament: str = "Test Open") -> dict:
    return {"events": [{"id": "10", "name": tournament,
                        "groupings": [{"grouping": {"displayName": "Men's Singles"}, "competitions": list(competitions)}]}]}


def empty_scoreboard() -> dict:
    return {"events": []}


def odds_event(event_id: str = "evt-1", *, home: str = HOME, away: str = AWAY, commence: str = START,
               quotes: Optional[List[dict]] = None) -> dict:
    """A raw Odds API event. `quotes` are {book, last_update, home, away} (American prices)."""
    books = []
    for q in quotes or []:
        books.append({"key": q["book"], "last_update": q["last_update"],
                      "markets": [{"key": "h2h", "last_update": q["last_update"],
                                   "outcomes": [{"name": home, "price": q["home"]}, {"name": away, "price": q["away"]}]}]})
    return {"id": event_id, "sport_key": KEY, "commence_time": commence, "home_team": home, "away_team": away,
            "bookmakers": books}


def listing(event: dict) -> dict:
    return {k: event[k] for k in ("id", "commence_time", "home_team", "away_team")}


def quotes(when: str, spec: List[Tuple[str, int, int]]) -> List[dict]:
    return [{"book": b, "last_update": when, "home": h, "away": a} for b, h, a in spec]


class FakeClock:
    def __init__(self, start: str):
        self.now = utc(start)

    def __call__(self) -> datetime:
        return self.now

    def set(self, text: str) -> None:
        self.now = utc(text)

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class World:
    """A scripted world. `espn` is a callable returning the scoreboard doc for the current moment (per tour);
    `odds` is the list of raw events a paid call returns; every call is recorded."""

    def __init__(self, start: str):
        self.clock = FakeClock(start)
        self.atp_doc: dict = empty_scoreboard()
        self.wta_doc: dict = empty_scoreboard()
        self.after_atp_doc: Optional[dict] = None          # what the SECOND read (the bracket) returns, if different
        self.events: List[dict] = []
        self.odds_events: List[dict] = []
        self.remaining = 50000
        self.espn_calls = 0
        self.odds_calls: List[str] = []
        self.listing_calls = 0
        self.fail_odds = False
        self._reads_since_buy = 0
        self._bought = False

    def espn_json(self, url: str) -> dict:
        self.espn_calls += 1
        tour = "atp" if "/atp/" in url else "wta"
        if tour == "wta":
            return self.wta_doc
        if self._bought and self.after_atp_doc is not None:
            return self.after_atp_doc
        return self.atp_doc

    def list_events(self, key: str) -> List[dict]:
        self.listing_calls += 1
        return [listing(e) for e in self.events]

    def fetch_odds(self, key: str):
        if self.fail_odds:
            raise RuntimeError("boom")
        self.odds_calls.append(key)
        self._bought = True
        self.remaining -= 1
        return list(self.odds_events), {"remaining": self.remaining, "last": 1, "used": 1}

    def seams(self) -> Seams:
        def keys():
            return [KEY]

        def quota():
            return {"remaining": self.remaining, "last": 0}

        def sleep(seconds: float) -> None:
            self.clock.advance(seconds)

        return Seams(clock=self.clock, espn_json=self.espn_json, list_keys=keys, list_events=self.list_events,
                     fetch_odds=self.fetch_odds, quota=quota, sleep=sleep)

    def end_tick(self) -> None:
        """Call between ticks so the bracket's 'after' doc stops applying until the next paid call."""
        self._bought = False


def read_jsonl(path) -> List[dict]:
    target = Path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
