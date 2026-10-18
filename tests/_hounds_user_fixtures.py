"""Fixture boards, hounds and results for the user-hound tests. Nothing here reads a live store.

The standard game starts at 23:10Z on 2026-10-20 (Eastern date 2026-10-20). A 120-minute hound locks
at 21:10Z, so the board it must use is the 21:05Z capture; the 22:20Z capture exists to prove a later
board is never used, and the 19:55Z capture is the 'first capture' a movement rule compares with.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.hounds import user_spec

DATE = "2026-10-20"
START = "2026-10-20T23:10:00Z"
HOME, AWAY = "Seattle Mariners", "Boston Red Sox"
EVENT = "evt0001"
T_OPEN = "2026-10-20T19:55:00Z"
T_LOCK = "2026-10-20T21:05:00Z"
T_LATE = "2026-10-20T22:20:00Z"

BOOKS = ("book_a", "book_b", "book_c", "book_d", "book_e")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def board_rows(observed: str, *, event_id: str = EVENT, home: str = HOME, away: str = AWAY,
               start: str = START, sport: str | None = None, moneyline=None, spread=None,
               total=None) -> list:
    """Raw multibook rows for one capture. moneyline: [(book, home_price, away_price)];
    spread: (home_line, [(book, home_price, away_price)]); total: (line, [(book, over, under)])."""
    base = {"observed_utc": observed, "event_id": event_id, "commence_time": start,
            "home_team": home, "away_team": away}
    if sport:
        base["sport"] = sport
    rows = []
    for book, hp, ap in moneyline or ():
        rows.append({**base, "book": book, "book_last_update": observed, "home_price": hp,
                     "away_price": ap})
    if spread:
        line, quotes = spread
        for book, hp, ap in quotes:
            rows.append({**base, "market": "spreads", "book": book, "book_last_update": observed,
                         "home_line": f"{line:g}", "home_price": hp, "away_line": f"{-line:g}",
                         "away_price": ap})
    if total:
        line, quotes = total
        for book, op, up in quotes:
            rows.append({**base, "market": "totals", "book": book, "book_last_update": observed,
                         "total": f"{line:g}", "over_price": op, "under_price": up})
    return rows


def standard_rows(**kw) -> list:
    """Open, lock and late captures of the standard game. Home is the favourite, away the dog."""
    rows = []
    rows += board_rows(T_OPEN, moneyline=[(b, -125, 105) for b in BOOKS],
                       spread=(-1.5, [(b, 150, -180) for b in BOOKS]),
                       total=(8.0, [(b, -105, -115) for b in BOOKS]), **kw)
    rows += board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS],
                       spread=(-1.5, [(b, 160, -190) for b in BOOKS]),
                       total=(8.5, [(b, -105, -115) for b in BOOKS]), **kw)
    rows += board_rows(T_LATE, moneyline=[(b, -170, 150) for b in BOOKS],
                       spread=(-1.5, [(b, 180, -215) for b in BOOKS]),
                       total=(9.0, [(b, -105, -115) for b in BOOKS]), **kw)
    return rows


def spec_dict(**over) -> dict:
    base = dict(name="Dog Days", tagline="", sports=["MLB"], markets=["moneyline"],
                side_rule="underdog", price_min=100, price_max=250, min_books=3,
                max_bets_per_day=2, lock_minutes=120)
    base.update(over)
    return base


def hound(hid: str = "u-test1", created_at: str = "2026-01-01T00:00:00Z", **over) -> dict:
    spec = user_spec.validate_spec(spec_dict(**over))
    return {"id": hid, "spec": spec, "spec_hash": user_spec.spec_hash(spec),
            "created_at": created_at}


def result_row(pk, date, away, home, away_score, home_score, **extra) -> dict:
    """A results-store row (scores are strings there, like the CSV)."""
    row = {"game_pk": str(pk), "date": date, "away_team": away, "home_team": home,
           "away_score": str(away_score), "home_score": str(home_score)}
    row.update(extra)
    return row
