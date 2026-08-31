"""Assemble a whole slate's briefing: dossiers, detectors, verdicts.

The one place that knows how a day's analysis is put together. The CLI renders
what this produces; detectors and the dashboard both stay ignorant of each other.
"""

from __future__ import annotations

from src.analysis import matchup as matchup_mod
from src.analysis import prices as prices_mod
from src.detect import base as detect
from src.detect import dossier as dossier_mod
from src.pipeline import lineups as lineup_mod
from src.pipeline import mismatch
from src.pipeline import slate as slate_mod


def build_slate(games, store, pitcher_logs=None, prices_by_matchup=None,
                weather_by_pk=None, lineups_by_pk=None, bullpen_by_team=None,
                handedness=None, splits_by_pk=None, matchups_by_pk=None,
                travel_by_pk=None, arsenals=None, batter_arsenals=None,
                news_by_pk=None, matchup_depth_by_pk=None,
                price_improvement_by_key=None, detectors=None,
                information_time=None) -> dict:
    """One briefing for one date.

    The scanner's verdict and the detectors run over the same dossier, so a
    verdict can never disagree with the facts shown beneath it -- they are
    computed from one snapshot of one game's information.
    """
    entries, notes = [], []

    # Matchup depth is derived from inputs this function already holds (the
    # posted lineups, the handedness cache, the pitch store), so it is built
    # here rather than passed in from every caller -- the CLI gets it for
    # free. One walk of the pitch store per slate, and none at all when no
    # lineup is posted. Tests (and any caller that wants control) inject
    # `matchup_depth_by_pk` instead, the same way news_by_pk is injected.
    if matchup_depth_by_pk is None:
        matchup_depth_by_pk = matchup_mod.depth_by_pk(
            games, lineups_by_pk, handedness)
    # Price improvement comes from the multi-book capture store, read once
    # per slate; tests inject price_improvement_by_key the same way. A store
    # that does not exist yet simply yields no sections, and every dossier
    # then carries the honest gap instead.
    if price_improvement_by_key is None:
        price_improvement_by_key = prices_mod.by_matchup()
    for game in games:
        key = (game.get("away_team"), game.get("home_team"))
        dossier = dossier_mod.build(
            game, store,
            pitcher_logs=pitcher_logs,
            prices=(prices_by_matchup or {}).get(key),
            weather=(weather_by_pk or {}).get(game.get("game_pk")),
            lineups=_lineup_section(
                (lineups_by_pk or {}).get(game.get("game_pk")), handedness, game,
                batter_arsenals),
            splits=(splits_by_pk or {}).get(game.get("game_pk")),
            matchups=(matchups_by_pk or {}).get(game.get("game_pk")),
            travel=(travel_by_pk or {}).get(game.get("game_pk")),
            arsenals=_arsenal_section(game, arsenals),
            news=(news_by_pk or {}).get(game.get("game_pk")),
            matchup_depth=(matchup_depth_by_pk or {}).get(game.get("game_pk")),
            price_improvement=(price_improvement_by_key or {}).get(
                (game.get("away_team"), game.get("home_team"),
                 game.get("date"))),
            bullpen={team: (bullpen_by_team or {}).get(team) for team in key
                     if (bullpen_by_team or {}).get(team)} or None,
            information_time=information_time,
        )
        findings = detect.run_all(dossier, detectors)
        scan = mismatch.scan_game(game, dossier.get("teams"), dossier.get("starters"))

        # Stage two, using the price for the market the scan actually routed to.
        # Fetching first-five prices and then never screening with them left the
        # briefing permanently stuck on "candidate" -- it could describe a game
        # but never reach a verdict on one.
        if scan["verdict"] == mismatch.CANDIDATE:
            quote = _routed_price(dossier, scan["market"])
            scan = mismatch.apply_market_screen(
                scan, quote.get("away_price"), quote.get("home_price"))

        entries.append({
            "dossier": dossier,
            "findings": findings,
            "verdict": scan["verdict"],
            "side": scan.get("side"),
            "market": scan.get("market"),
            "summary": scan.get("summary"),
            "scan": scan,
        })

    unavailable = sum(1 for e in entries
                      if e["verdict"] == mismatch.MARKET_UNAVAILABLE)
    if unavailable:
        notes.append(
            f"{unavailable} game(s) cleared the talent bar but had no price on "
            "the market they were routed to. That is a different result from no "
            "play, and it is common: measured on three seasons, more than a "
            "third of flagged games have no first-five market at all.")

    if not any(e["verdict"] not in (mismatch.NO_PLAY, mismatch.MARKET_UNAVAILABLE)
               for e in entries) and entries:
        notes.append(
            "No play on the whole slate. That is the normal case, not a failure "
            "of the scan -- two roughly major-league teams playing a close game "
            "is what most of a major-league day looks like.")

    return {
        "date": games[0].get("date") if games else None,
        "games": entries,
        "notes": notes,
    }


def _arsenal_section(game, arsenals):
    """Each starter's arsenal, most-used pitch first."""
    if not arsenals:
        return None
    section = {}
    for side, key in (("away", "away_probable_id"), ("home", "home_probable_id")):
        rows = arsenals.get(str(game.get(key)))
        if rows:
            section[side] = rows
    return section or None


def _lineup_section(posted, handedness, game, batter_arsenals=None):
    """Posted lineup plus the platoon composition it presents to each starter."""
    if not posted:
        return None
    section = {}
    # A lineup's platoon composition is only meaningful against the hand of the
    # pitcher it actually faces, so each side is paired with the OPPOSING
    # starter. Crossing these over is the sort of mistake that produces a
    # confident, precisely wrong number on every game.
    for side, opposing_starter in (("away", "home_probable_id"),
                                   ("home", "away_probable_id")):
        slots = posted.get(side) or []
        pitcher_id = game.get(opposing_starter)
        throws = ((handedness or {}).get(str(pitcher_id)) or {}).get("throws")
        section[side] = {
            "batters": slots,
            "handedness": lineup_mod.lineup_handedness(slots, handedness or {}),
            "platoon_advantage": lineup_mod.platoon_advantage_share(
                slots, handedness or {}, throws),
            "faces_starter_throwing": throws,
            # Each hitter's measured line against each pitch type, grouped by
            # pitch so a detector can ask one question of the whole lineup.
            "vs_pitch": _lineup_vs_pitch(slots, batter_arsenals),
        }
    return section


def _lineup_vs_pitch(slots, batter_arsenals):
    grouped = {}
    for slot in slots or []:
        for row in (batter_arsenals or {}).get(str(slot.get("person_id")), []):
            grouped.setdefault(row.get("pitch_type"), []).append(
                dict(row, batter=slot.get("name")))
    return grouped


def _routed_price(dossier, market):
    """The moneyline for the market a scan was routed to.

    Screening a first-five routing against a full-game price compares two
    different quantities -- the first-five price is conditional on no push --
    so the market is chosen by the routing rather than by what happens to be
    available.
    """
    section = dossier.get("market") or {}
    key = ("h2h_1st_5_innings" if market == mismatch.MARKET_F5 else "h2h")
    return (section.get("markets") or {}).get(key) or {}
