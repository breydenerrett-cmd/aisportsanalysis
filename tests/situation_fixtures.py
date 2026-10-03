"""Shared, offline fixtures for the situation layer tests.

A small MLB world, built by hand so every figure can be checked on paper:

REGULAR SEASON, 2025
  NYY hosts TB on 12 straight days, 2025-09-14 to 2025-09-25. NYY's runs for and against, in
  date order (d1 to d12):

      d1 5-2 W   d2 3-4 L   d3 6-1 W   d4 2-3 L   d5 7-5 W   d6 1-0 W
      d7 4-6 L   d8 3-2 W   d9 8-3 W   d10 2-1 W  d11 5-4 W  d12 0-3 L

  So NYY's last 5 (d8 to d12) are 4-1 with 18 runs for and 13 against (+5, 1.0 a game), its
  last 10 (d3 to d12) are 7-3 with 38 for and 28 against (+10, 1.0 a game), and it lost its
  last game. NYY's listed starters cycle Cole, Rodon, Schmidt, Fried, Warren: d3 and d8 are
  Schmidt's starts.
  BOS played three games at NYY in August (BOS 5-1, NYY 3-2, BOS 4-0) and two at TB
  (2025-09-26 BOS 3-2, 2025-09-27 TB 4-1).

POSTSEASON, 2025 (the format of 2022 on: six clubs a league, byes for the top two seeds)
  Wild Card Series (type F), four of them, all decided: TB beat BOS 2-1, TOR beat MIN 2-0,
  SEA beat DET 2-0, LAD beat SD 2-0. NYY played none of them: a bye.
  Division Series (type D), NYY against TB: G1 10-04 at NYY (NYY 5-2), G2 10-05 at NYY (TB 6-3),
  G3 10-07 at TB (NYY 4-1), G4 10-08 at TB (TB 6-2), G5 10-09 at NYY (NYY 3-1).

The analysed game is passed in separately each time; the rows hold everything else. Nothing
here reads the repo's data or a clock.
"""

from __future__ import annotations

NYY_RUNS = [(5, 2), (3, 4), (6, 1), (2, 3), (7, 5), (1, 0), (4, 6), (3, 2), (8, 3), (2, 1), (5, 4), (0, 3)]
NYY_STARTERS = [("Gerrit Cole", 1), ("Carlos Rodon", 2), ("Marcus Schmidt", 3), ("Max Fried", 4),
                ("Will Warren", 5)]


def g(pk, date, away, home, away_score, home_score, game_type="R", away_probable=None, away_probable_id=None,
      home_probable=None, home_probable_id=None, venue="", double_header="N", game_number=1) -> dict:
    """One finished game as the results store holds it (a CSV row: strings, '' for none)."""
    return {
        "game_pk": str(pk), "date": date, "start_time_utc": f"{date}T23:00:00Z", "venue": venue,
        "game_type": game_type, "away_team": away, "home_team": home,
        "away_probable": away_probable, "home_probable": home_probable,
        "away_probable_id": None if away_probable_id is None else str(away_probable_id),
        "home_probable_id": None if home_probable_id is None else str(home_probable_id),
        "away_score": str(away_score), "home_score": str(home_score),
        "winner": away if away_score > home_score else home,
        "home_won": "1" if home_score > away_score else "0",
        "double_header": double_header, "game_number": str(game_number),
    }


def regular_season() -> list:
    rows = []
    for i, (rf, ra) in enumerate(NYY_RUNS):
        name, pid = NYY_STARTERS[i % 5]
        rows.append(g(100 + i, f"2025-09-{14 + i:02d}", "TB", "NYY", ra, rf, home_probable=name,
                      home_probable_id=pid, away_probable="Taj Bradley", away_probable_id=90,
                      venue="Yankee Stadium"))
    rows += [
        g(201, "2025-08-10", "BOS", "NYY", 5, 1, away_probable="Garrett Crochet", away_probable_id=21,
          home_probable="Gerrit Cole", home_probable_id=1, venue="Yankee Stadium"),
        g(202, "2025-08-11", "BOS", "NYY", 2, 3, away_probable="Brayan Bello", away_probable_id=11,
          home_probable="Carlos Rodon", home_probable_id=2, venue="Yankee Stadium"),
        g(203, "2025-08-12", "BOS", "NYY", 4, 0, away_probable="Lucas Giolito", away_probable_id=31,
          home_probable="Marcus Schmidt", home_probable_id=3, venue="Yankee Stadium"),
        g(204, "2025-09-26", "BOS", "TB", 3, 2, away_probable="Brayan Bello", away_probable_id=11,
          home_probable="Taj Bradley", home_probable_id=90, venue="Tropicana Field"),
        g(205, "2025-09-27", "BOS", "TB", 1, 4, away_probable="Garrett Crochet", away_probable_id=21,
          home_probable="Shane Baz", home_probable_id=91, venue="Tropicana Field"),
    ]
    return rows


def wild_card() -> list:
    return [
        g(301, "2025-09-30", "BOS", "TB", 2, 4, "F", away_probable="Garrett Crochet", away_probable_id=21,
          home_probable="Drew Rasmussen", home_probable_id=92, venue="Tropicana Field"),
        g(302, "2025-10-01", "BOS", "TB", 5, 3, "F", away_probable="Brayan Bello", away_probable_id=11,
          home_probable="Ryan Pepiot", home_probable_id=93, venue="Tropicana Field"),
        g(303, "2025-10-02", "BOS", "TB", 1, 3, "F", away_probable="Lucas Giolito", away_probable_id=31,
          home_probable="Shane McClanahan", home_probable_id=94, venue="Tropicana Field"),
        g(311, "2025-09-30", "MIN", "TOR", 1, 3, "F"), g(312, "2025-10-01", "MIN", "TOR", 2, 5, "F"),
        g(321, "2025-09-30", "SEA", "DET", 4, 1, "F"), g(322, "2025-10-01", "SEA", "DET", 3, 2, "F"),
        g(331, "2025-09-30", "LAD", "SD", 3, 2, "F"), g(332, "2025-10-01", "LAD", "SD", 6, 1, "F"),
    ]


def division_series() -> list:
    """NYY (bye) against TB (through the Wild Card Series). NYY wins the series 3-2."""
    return [
        g(401, "2025-10-04", "TB", "NYY", 2, 5, "D", away_probable="Drew Rasmussen", away_probable_id=92,
          home_probable="Gerrit Cole", home_probable_id=1, venue="Yankee Stadium"),
        g(402, "2025-10-05", "TB", "NYY", 6, 3, "D", away_probable="Ryan Pepiot", away_probable_id=93,
          home_probable="Carlos Rodon", home_probable_id=2, venue="Yankee Stadium"),
        g(403, "2025-10-07", "NYY", "TB", 4, 1, "D", away_probable="Max Fried", away_probable_id=4,
          home_probable="Shane McClanahan", home_probable_id=94, venue="Tropicana Field"),
        g(404, "2025-10-08", "NYY", "TB", 2, 6, "D", away_probable="Will Warren", away_probable_id=5,
          home_probable="Taj Bradley", home_probable_id=90, venue="Tropicana Field"),
        g(405, "2025-10-09", "TB", "NYY", 1, 3, "D", away_probable="Drew Rasmussen", away_probable_id=92,
          home_probable="Gerrit Cole", home_probable_id=1, venue="Yankee Stadium"),
    ]


def world() -> list:
    return regular_season() + wild_card() + division_series()


def game(pk, date, away, home, game_type="R", **kw) -> dict:
    """The game being analysed, as the schedule gives it: no score."""
    out = {"game_pk": pk, "date": date, "start_time_utc": f"{date}T23:00:00Z", "game_type": game_type,
           "away_team": away, "home_team": home, "venue": kw.pop("venue", None)}
    out.update(kw)
    return out


def regular_game() -> dict:
    """BOS at NYY on 2025-09-28, the game the form and rest figures above are checked for."""
    return game(901, "2025-09-28", "BOS", "NYY", venue="Yankee Stadium",
                away_probable="Brayan Bello", away_probable_id=11,
                home_probable="Marcus Schmidt", home_probable_id=3)


def division_game(number: int) -> dict:
    """Game `number` of the NYY-TB Division Series (the row for it exists in `division_series`)."""
    rows = {r["game_pk"]: r for r in division_series()}
    row = rows[str(400 + number)]
    return game(400 + number, row["date"], row["away_team"], row["home_team"], "D",
                venue=row["venue"], away_probable=row["away_probable"],
                away_probable_id=row["away_probable_id"], home_probable=row["home_probable"],
                home_probable_id=row["home_probable_id"])
