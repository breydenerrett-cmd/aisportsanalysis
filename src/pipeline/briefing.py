"""Assemble a whole slate's briefing: dossiers, detectors, verdicts.

The one place that knows how a day's analysis is put together. The CLI renders
what this produces; detectors and the dashboard both stay ignorant of each other.
"""

from __future__ import annotations

from src.detect import base as detect
from src.detect import dossier as dossier_mod
from src.pipeline import mismatch
from src.pipeline import slate as slate_mod


def build_slate(games, store, pitcher_logs=None, prices_by_matchup=None,
                weather_by_pk=None, lineups_by_pk=None, bullpen_by_team=None,
                detectors=None, information_time=None) -> dict:
    """One briefing for one date.

    The scanner's verdict and the detectors run over the same dossier, so a
    verdict can never disagree with the facts shown beneath it -- they are
    computed from one snapshot of one game's information.
    """
    entries, notes = [], []
    for game in games:
        key = (game.get("away_team"), game.get("home_team"))
        dossier = dossier_mod.build(
            game, store,
            pitcher_logs=pitcher_logs,
            prices=(prices_by_matchup or {}).get(key),
            weather=(weather_by_pk or {}).get(game.get("game_pk")),
            lineups=(lineups_by_pk or {}).get(game.get("game_pk")),
            bullpen={team: (bullpen_by_team or {}).get(team) for team in key
                     if (bullpen_by_team or {}).get(team)} or None,
            information_time=information_time,
        )
        findings = detect.run_all(dossier, detectors)
        scan = mismatch.scan_game(game, dossier.get("teams"), dossier.get("starters"))
        entries.append({
            "dossier": dossier,
            "findings": findings,
            "verdict": scan["verdict"],
            "side": scan.get("side"),
            "market": scan.get("market"),
            "summary": scan.get("summary"),
            "scan": scan,
        })

    if not any(e["verdict"] != mismatch.NO_PLAY for e in entries) and entries:
        notes.append(
            "No play on the whole slate. That is the normal case, not a failure "
            "of the scan -- two roughly major-league teams playing a close game "
            "is what most of a major-league day looks like.")

    return {
        "date": games[0].get("date") if games else None,
        "games": entries,
        "notes": notes,
    }
