"""Fixtures for the all-sports tests: fake Odds API payloads and a fake provider. Nothing here touches the
network or a real store."""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone

from src.sports import catalog

NOW = datetime(2026, 10, 20, 18, 0, 0, tzinfo=timezone.utc)
ENV = {"ODDS_API_KEY": "test-key-not-real"}


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sport_entry(key, title=None, *, active=True, outrights=False, group="Basketball"):
    return {"key": key, "group": group, "title": title or key, "description": title or key,
            "active": active, "has_outrights": outrights}


def raw_event(event_id, home, away, start, *, books=("book_a", "book_b", "book_c"), h2h=(-120, 100),
              draw=None, total=None, spread=None):
    """One /odds event. h2h: (home, away) price; draw: price of the Draw outcome (three-way);
    total: (point, over, under); spread: (home_point, home_price, away_price)."""
    bookmakers = []
    for book in books:
        markets = [{"key": "h2h", "last_update": iso(start), "outcomes": (
            [{"name": home, "price": h2h[0]}, {"name": away, "price": h2h[1]}]
            + ([{"name": "Draw", "price": draw}] if draw is not None else []))}]
        if total:
            markets.append({"key": "totals", "last_update": iso(start), "outcomes": [
                {"name": "Over", "price": total[1], "point": total[0]},
                {"name": "Under", "price": total[2], "point": total[0]}]})
        if spread:
            markets.append({"key": "spreads", "last_update": iso(start), "outcomes": [
                {"name": home, "price": spread[1], "point": spread[0]},
                {"name": away, "price": spread[2], "point": -spread[0]}]})
        bookmakers.append({"key": book, "title": book, "last_update": iso(start), "markets": markets})
    return {"id": event_id, "sport_key": "x", "commence_time": iso(start), "home_team": home,
            "away_team": away, "bookmakers": bookmakers}


def list_item(event):
    return {k: event[k] for k in ("id", "sport_key", "commence_time", "home_team", "away_team")}


class FakeOdds:
    """The injected provider seams for allsports_capture.run: sports list, per-key events and odds."""

    def __init__(self, sports, events_by_key, remaining=90000, bill=None):
        self.sports = sports
        self.events_by_key = events_by_key
        self.remaining = remaining
        self.bill = bill or {}
        self.odds_calls = []
        self.event_calls = []

    def fetch_sports(self):
        return list(self.sports)

    def list_events(self, key):
        self.event_calls.append(key)
        return [list_item(e) for e in self.events_by_key.get(key, [])]

    def fetch_odds(self, key, markets, regions):
        self.odds_calls.append((key, tuple(markets), tuple(regions)))
        cost = self.bill.get(key, len(markets) * len(regions))
        self.remaining -= cost
        # the vendor returns only the markets that were asked for
        events = copy.deepcopy(self.events_by_key.get(key, []))
        for event in events:
            for book in event["bookmakers"]:
                book["markets"] = [m for m in book["markets"] if m["key"] in markets]
        return events, {"remaining": self.remaining, "last": cost}

    def quota(self):
        return {"remaining": self.remaining}


def config(**capture):
    """The real catalog with `capture` keys overridden (a deep copy: nothing leaks between tests)."""
    cfg = copy.deepcopy(catalog.load())
    cfg["capture"].update(capture)
    return cfg


class Paths:
    def __init__(self, root):
        self.done = os.path.join(root, "done.jsonl")
        self.sports = os.path.join(root, "sports.jsonl")
        self.multibook = os.path.join(root, "multibook.jsonl")
        self.credit = os.path.join(root, "credit_log.jsonl")
        self.scores = os.path.join(root, "scores.jsonl")

    def kwargs(self):
        return {"done_path": self.done, "sports_path": self.sports, "multibook_path": self.multibook,
                "credit_store": self.credit}


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def minutes(n):
    return timedelta(minutes=n)
