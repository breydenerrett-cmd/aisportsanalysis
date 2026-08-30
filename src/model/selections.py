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
from src.data import parks
from src.model import pointintime as pit
from src.model import rebuilt_sections as rebuilt_sections_mod
from src.pipeline import slate as slate_mod

# Sections a historical dossier may carry. Deliberately a whitelist: a new
# section is excluded until it has been audited, rather than included until
# someone notices.
HISTORICAL_SECTIONS = ("teams", "starters", "bullpen", "travel", "park", "market")

# Sections a historical dossier may ALSO carry when they are rebuilt from the
# pitch-level store (src/model/rebuilt_sections.py). Point-in-time BECAUSE
# sourced from the rebuilt store: every number is accumulated forward from
# per-pitch rows carrying their own dates, so a cutoff is a filter and nothing
# after it can contribute. The identically named live-fetch sections remain
# excluded -- these are only attached when the caller supplies the rebuilt
# inputs, never from the live endpoints.
REBUILT_SECTIONS = ("splits", "arsenals", "lineups", "matchup_history")

# How far an odds event's commence_time may sit from the game's own first pitch
# and still be the same game. The two populations are far apart: a game's own
# event agrees with the MLB schedule to within minutes, while the nearest WRONG
# event -- the other game of a series sharing a (away, home, date) key -- is a
# doubleheader partner four-plus hours away or the next night at ~24. Three
# hours splits them with room on both sides.
MAX_EVENT_GAP_SECONDS = 3 * 3600


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
          registry=None, detectors=None, acc_for_date=None, lineups_by_pk=None,
          handedness=None) -> dict:
    """Selections for every clean detector across a set of played games.

    `price_pairs` maps (away_abbrev, home_abbrev, date) to a LIST of candidate
    entries produced by backfill.price_pair -- a list because consecutive games
    between the same clubs land on the same key (each event is indexed under
    two dates), and the game's own start time is what picks between them.

    When `acc_for_date` (a callable date -> rebuilt accumulation, e.g. backed
    by rebuilt.build_snapshots), `lineups_by_pk` (lineup_store.read output) and
    `handedness` are supplied, the four rebuilt sections are attached so the
    lineup-and-pitch detectors can run historically; without them those
    sections stay absent, exactly as before.
    """
    chosen = detectors if detectors is not None else clean_detectors(
        registry or detect.registry())

    selections, counts = [], {
        "games": 0, "games_priced": 0, "findings": 0,
        "findings_without_a_side": 0, "unresolved": 0}

    for game in games:
        counts["games"] += 1
        # Both sides of the join must pass through the same canonicalizer, the
        # same as the live match in slate.match_events. The results store keeps
        # the MLB Stats API spellings (AZ, and ATH from 2025), while the price
        # index is keyed from odds-feed club names (ARI/OAK); comparing them
        # raw silently drops every game those clubs play as "unpriced".
        pair = _resolve_pair(
            price_pairs.get((parks.canonical_team(game.get("away_team") or ""),
                             parks.canonical_team(game.get("home_team") or ""),
                             game.get("date"))), game)
        if not pair or not pair.get("distinct"):
            continue

        opening = _fair(pair["open"]["bookmakers"], pair["home_team"],
                        pair["away_team"])
        closing = _fair(pair["close"]["bookmakers"], pair["home_team"],
                        pair["away_team"])
        if not opening or not closing:
            continue
        counts["games_priced"] += 1

        rebuilt_data = None
        if acc_for_date is not None:
            # lineup_store.read keys by str(game_pk) -- documented in its
            # tests as the CSV-round-trip convention -- so the join coerces
            # explicitly rather than trusting the game record's key type.
            rebuilt_data = rebuilt_sections_mod.sections_for_game(
                acc_for_date(game.get("date")), game,
                (lineups_by_pk or {}).get(str(game.get("game_pk"))),
                handedness or {})
        dossier = _historical_dossier(game, store, pitcher_logs,
                                      bullpen_by_team, opening, rebuilt_data)
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


def _historical_dossier(game, store, pitcher_logs, bullpen_by_team, opening,
                        rebuilt_data=None):
    """A dossier carrying only sections that can be reconstructed at that date.

    The leaky sections are not attached at all. A detector that reaches for one
    finds nothing, which is the correct historical answer -- and it is safer
    than attaching them and trusting every detector to decline.

    `rebuilt_data` is the (sections, reasons) pair from
    rebuilt_sections.sections_for_game. Those sections are attached AFTER the
    whitelist sweep, so the only way splits/arsenals/lineups/matchup_history
    appear on a historical dossier is from the rebuilt store -- the live-fetch
    versions are still stripped even if a future caller wires them in.
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
    if rebuilt_data is not None:
        sections, reasons = rebuilt_data
        for name in REBUILT_SECTIONS:
            if name in sections:
                dossier.gaps.pop(name, None)
                dossier.add(name, sections[name])
            else:
                dossier.miss(name, "rebuilt section unavailable: "
                             + reasons.get(name, "not built"))
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
    """Key backfill.price_pair output by (away, home, date) abbreviations.

    Each key holds a LIST. Because every event is indexed under two dates,
    consecutive games between the same clubs share a key, and a plain
    assignment let the later game silently overwrite the earlier one -- 55% of
    matched 2023 games were then priced from, and graded against, the NEXT
    game's odds. Both candidates are kept and _resolve_pair picks by the
    game's own start time.
    """
    out = {}
    for entry in pairs.values():
        # Canonicalized to match the canonicalized lookup in build(): the two
        # ends of a join must never disagree on a club's spelling.
        away = parks.canonical_team(
            slate_mod.team_abbrev_from_name(entry.get("away_team")) or "")
        home = parks.canonical_team(
            slate_mod.team_abbrev_from_name(entry.get("home_team")) or "")
        start = entry.get("commence_time") or ""
        if not (away and home and start):
            continue
        # A game's official date can differ from the UTC date of first pitch for
        # late west-coast starts, so both are indexed rather than guessing.
        for date in _candidate_dates(start):
            out.setdefault((away, home, date), []).append(entry)
    return out


def _resolve_pair(candidates, game):
    """The one odds event that IS this game, or None.

    The (away, home, date) key cannot distinguish two games of a series, so the
    tie is broken by time: the event whose commence_time sits within
    MAX_EVENT_GAP_SECONDS of the game's own first pitch. A lone candidate gets
    the same check -- when a game's own event is missing from the odds archive,
    the surviving candidate is its neighbour, and pricing a game from another
    game's market is corruption, not coverage. No usable start time on the
    game means the tie cannot be broken honestly, so the game goes unpriced.
    """
    if not candidates:
        return None
    if isinstance(candidates, dict):  # a caller passing bare entries directly
        candidates = [candidates]
    start = _parse_utc(game.get("start_time_utc"))
    if start is None:
        # The docstring's own rule, previously honoured only for multiple
        # candidates: no usable start time means the gate cannot run, and a
        # lone candidate is exactly as likely to be the neighbouring game as
        # a tied one is. Unpriced, not guessed.
        return None
    best, best_gap = None, None
    for entry in candidates:
        commence = _parse_utc(entry.get("commence_time"))
        if commence is None:
            continue
        try:
            gap = abs((commence - start).total_seconds())
        except TypeError:  # naive vs aware -- not comparable, not a match
            continue
        if gap <= MAX_EVENT_GAP_SECONDS and (best_gap is None or gap < best_gap):
            best, best_gap = entry, gap
    return best


def _parse_utc(stamp):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def _candidate_dates(commence_time) -> list:
    from datetime import datetime, timedelta
    try:
        stamp = datetime.fromisoformat(str(commence_time).replace("Z", "+00:00"))
    except ValueError:
        return []
    return [stamp.date().isoformat(),
            (stamp.date() - timedelta(days=1)).isoformat()]
