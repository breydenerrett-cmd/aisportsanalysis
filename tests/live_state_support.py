"""Shared fixtures and builders for the live game state tests (tests/test_live_state_*.py).

The fixtures in tests/fixtures/live_state/ are REAL responses captured on 2026-10-29 from the NHL Stats API
(score/now, one boxscore and one play-by-play for a game in its 2nd period and one in its 1st intermission) and from ESPN's
ATP and WTA scoreboards, trimmed to the keys the code reads. NO test here touches the network: every fetch is a function
over these files, and every clock is injected.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures" / "live_state"
GAME, INTERMISSION_GAME = "2026020213", "2026020211"          # VAN at SJS (2nd period, 16:19 left); BUF at ANA (1st intermission)
START = datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)      # their scheduled start (7:00 PM PT)
NOW = datetime(2026, 10, 30, 2, 40, tzinfo=timezone.utc)       # when the fixtures were read, give or take a minute
TENNIS_NOW = datetime(2026, 10, 30, 0, 30, tzinfo=timezone.utc)
TENNIS_START = datetime(2026, 10, 30, 1, 35, tzinfo=timezone.utc)   # Rakhimova v Joint


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def fixture_fetch(url: str) -> dict:
    """A stand-in for the network over the captured files; an unknown URL raises, like a 404."""
    if "scoreboard" in url:
        return load("espn_tennis_wta.json" if "/wta/" in url else "espn_tennis_atp.json")
    if url.endswith("/score/now"):
        return load("nhl_score_now.json")
    gid = url.split("/")[-2]
    kind = "boxscore" if url.endswith("/boxscore") else "pbp" if url.endswith("/play-by-play") else None
    if kind is None or gid not in (GAME, INTERMISSION_GAME):
        raise OSError(f"no fixture for {url}")
    return load(f"nhl_{kind}_{gid}.json")


def pbp(gid: str = GAME) -> dict:
    return load(f"nhl_pbp_{gid}.json")


def box(gid: str = GAME) -> dict:
    return load(f"nhl_boxscore_{gid}.json")


def with_play(doc: dict, **fields) -> dict:
    """A copy of a play-by-play with ONE extra play appended after the latest, in the same period, `fields` merged in
    (situationCode, typeDescKey, timeRemaining, details ...). The play gets the next sortOrder."""
    out = copy.deepcopy(doc)
    last = max(out["plays"], key=lambda p: p["sortOrder"])
    play = {"eventId": last["eventId"] + 1, "sortOrder": last["sortOrder"] + 1,
            "periodDescriptor": copy.deepcopy(out["periodDescriptor"]), "timeInPeriod": "03:40", "timeRemaining": "16:20",
            "situationCode": last["situationCode"], "typeDescKey": "stoppage", "typeCode": 516, "details": {}}
    play.update(fields)
    out["plays"].append(play)
    return out


def with_code(doc: dict, code: str, **fields) -> dict:
    return with_play(doc, situationCode=code, **fields)


def at(seconds: float, base: datetime = NOW) -> datetime:
    return base + timedelta(seconds=seconds)
