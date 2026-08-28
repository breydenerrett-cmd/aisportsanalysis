"""Turn historical games into detector selections that can be graded.

WHAT A SELECTION IS
-------------------
One detector, on one game, picking one side, at a price it could actually have
seen. It carries the de-vigged probability at recommendation time, the same at
the close, the price, and whether that side went on to win.

Everything hard about this module is making sure each of those four things is
what it claims to be.

THREE RULES THAT DECIDE WHETHER THE OUTPUT MEANS ANYTHING
---------------------------------------------------------
1. Only point-in-time-clean detectors run. require_clean raises on the rest, so
   a leaky detector cannot quietly contribute selections that flatter the whole
   family.

2. The dossier is built from clean sections ONLY. It is not enough for the
   detector to be clean if the dossier hands it a leaky section anyway -- so the
   leaky sections are never attached during a historical build, and a detector
   that reaches for one finds nothing rather than finding the future.

3. The recommendation price comes from a snapshot at least six hours before
   first pitch. Using the earliest price on file would sometimes mean a market
   that had barely opened with one book quoting it, and the closing line value
   measured against that is manufactured rather than earned.

FINDINGS WITHOUT A SIDE ARE NOT SELECTIONS
------------------------------------------
A detector that says "this park is a mile up" bears on the total, not on either
team, and grading it against a moneyline would be scoring it on a question it
never answered. Those findings are counted and excluded, with the count
reported, because "no selections" and "no findings" are different states.
"""

from __future__ import annotations

from src.core import odds as odds_math
from src.detect import base as detect
from src.detect import dossier as dossier_mod
from src.model import pointintime as pit
from src.pipeline import slate as slate_mod

# Sections a historical dossier may carry. Deliberately a whitelist: a new
# section is excluded until it has been audited, rather than included until
# someone notices.
HISTORICAL_SECTIONS = ("teams", "starters", "bullpen", "travel", "park", "market")


class SelectionError(RuntimeError):
    """Raised when selections cannot be built honestly."""


def clean_detectors(registry) -> list:
    """Only detectors whose every input accumulates forward."""
    out = []
    for name, detector in sorted(registry.items()):
        try:
            pit.require_clean(name)
        except pit.PointInTimeError:
            continue
        out.append(detector)
    return out


def _fair(bookmakers, home_name, away_name):
    """Consensus de-vigged moneyline across every book quoting it.

    A single book's number is that book's opinion plus its margin. Averaging the
    de-vigged probabilities across the board is closer to what the market
    thought, and it is what a base-rate control has to be measured against --
    otherwise the control moves with whichever book happened to be first in the
    list.
    """
    fairs = []
    for book in bookmakers or []:
        for market in book.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            prices = {o.get("name"): o.get("price")
                      for o in market.get("outcomes") or []}
            home, away = prices.get(home_name), prices.get(away_name)
            if home is None or away is None:
                continue
            try:
                fair_away, fair_home = odds_math.devig_two_way(away, home)
            except odds_math.OddsError:
                continue
            fairs.append((fair_away, fair_home, away, home, book.get("key")))
    if not fairs:
        return None
    return {
        "away_fair": sum(f[0] for f in fairs) / len(fairs),
        "home_fair": sum(f[1] for f in fairs) / len(fairs),
        # Best available price per side, which is what a bet would actually get.
        "away_price": max(f[2] for f in fairs),
        "home_price": max(f[3] for f in fairs),
        "books": len(fairs),
        "quotes": [{"book": f[4], "away_price": f[2], "home_price": f[3]}
                   for f in fairs],
    }


def build(games, store, pitcher_logs, price_pairs, bullpen_by_team=None,
          registry=None, detectors=None) -> dict:
    """Selections for every clean detector across a set of played games.

    `price_pairs` maps (away_abbrev, home_abbrev, date) to the entry produced by
    backfill.price_pair.
    """
    chosen = detectors if detectors is not None else clean_detectors(
        registry or detect.registry())

    selections, counts = [], {
        "games": 0, "games_priced": 0, "findings": 0,
        "findings_without_a_side": 0, "unresolved": 0}

    for game in games:
        counts["games"] += 1
        pair = price_pairs.get((game.get("away_team"), game.get("home_team"),
                                game.get("date")))
        if not pair or not pair.get("distinct"):
            continue

        opening = _fair(pair["open"]["bookmakers"], pair["home_team"],
                        pair["away_team"])
        closing = _fair(pair["close"]["bookmakers"], pair["home_team"],
                        pair["away_team"])
        if not opening or not closing:
            continue
        counts["games_priced"] += 1

        dossier = _historical_dossier(game, store, pitcher_logs,
                                      bullpen_by_team, opening)
        home_won = _label(game.get("home_won"))
        if home_won is None:
            counts["unresolved"] += 1
            continue

        for detector in chosen:
            for finding in detector.safe_run(dossier):
                counts["findings"] += 1
                if finding.side not in (detect.AWAY, detect.HOME):
                    counts["findings_without_a_side"] += 1
                    continue
                picked_home = finding.side == detect.HOME
                selections.append({
                    "detector": finding.detector,
                    "date": game.get("date"),
                    "game_pk": game.get("game_pk"),
                    "away_team": game.get("away_team"),
                    "home_team": game.get("home_team"),
                    "side": finding.side,
                    "surprise": finding.surprise,
                    "won": bool(home_won) if picked_home else not home_won,
                    "implied": round(
                        opening["home_fair"] if picked_home
                        else opening["away_fair"], 5),
                    "closing_implied": round(
                        closing["home_fair"] if picked_home
                        else closing["away_fair"], 5),
                    "price": (opening["home_price"] if picked_home
                              else opening["away_price"]),
                    "books": opening["books"],
                    "lead_minutes": pair["open"]["gap_minutes"],
                })

    return {"selections": selections, "counts": counts,
            "detectors": [d.name for d in chosen]}


def _historical_dossier(game, store, pitcher_logs, bullpen_by_team, opening):
    """A dossier carrying only sections that can be reconstructed at that date.

    The leaky sections are not attached at all. A detector that reaches for one
    finds nothing, which is the correct historical answer -- and it is safer
    than attaching them and trusting every detector to decline.
    """
    from src.pipeline import travel as travel_mod

    # Every book from the recommendation snapshot, not just the consensus. The
    # stale-book detector's entire input is the spread between books, and
    # handing it a single consensus number silently produced zero selections on
    # the first run -- a detector that finds nothing looks identical to one with
    # nothing to find.
    prices = {"h2h": {"away_price": opening["away_price"],
                      "home_price": opening["home_price"]},
              "all_books": {"h2h": opening["quotes"]}}
    dossier = dossier_mod.build(
        game, store,
        pitcher_logs=pitcher_logs,
        prices=prices,
        bullpen=_bullpen_for(game, bullpen_by_team),
        travel={team: travel_mod.travel_load(store, team, game["date"],
                                             game["home_team"])
                for team in (game.get("away_team"), game.get("home_team"))
                if team},
    )
    for name in list(dossier.sections):
        if name not in HISTORICAL_SECTIONS:
            dossier.sections.pop(name)
            dossier.miss(name, "excluded from historical builds: not point-in-time")
    return dossier


def _label(value):
    """The home-win label as an integer, or None.

    The results store is a CSV, so this arrives as the STRING "0" or "1" -- and
    bool("0") is True. Coercing with bool() made every selection's outcome read
    as "did we pick the home side", which produced a 9.6-point apparent edge on
    a detector that mostly picks home teams. Nothing raised; the numbers were
    plausible; the whole discovery run was wrong.

    Anything that is not recognisably a label returns None so the game is
    counted as unresolved rather than silently scored.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value) if value in (0, 1) else None
    text = str(value).strip()
    if text in ("0", "1"):
        return int(text)
    if text.lower() in ("true", "false"):
        return int(text.lower() == "true")
    return None


def _bullpen_for(game, bullpen_by_team):
    if not bullpen_by_team:
        return None
    out = {}
    for team in (game.get("away_team"), game.get("home_team")):
        entry = (bullpen_by_team or {}).get((team, game.get("date")))
        if entry:
            out[team] = entry
    return out or None


def index_price_pairs(pairs) -> dict:
    """Key backfill.price_pair output by (away, home, date) abbreviations."""
    out = {}
    for entry in pairs.values():
        away = slate_mod.team_abbrev_from_name(entry.get("away_team"))
        home = slate_mod.team_abbrev_from_name(entry.get("home_team"))
        start = entry.get("commence_time") or ""
        if not (away and home and start):
            continue
        # A game's official date can differ from the UTC date of first pitch for
        # late west-coast starts, so both are indexed rather than guessing.
        for date in _candidate_dates(start):
            out[(away, home, date)] = entry
    return out


def _candidate_dates(commence_time) -> list:
    from datetime import datetime, timedelta
    try:
        stamp = datetime.fromisoformat(str(commence_time).replace("Z", "+00:00"))
    except ValueError:
        return []
    return [stamp.date().isoformat(),
            (stamp.date() - timedelta(days=1)).isoformat()]
