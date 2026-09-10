"""Assemble THE CARD for one date from the stores. Read-only.

`src.analysis.daily_card` is the rule and the wording; it takes plain data
and touches nothing. This module is the plumbing that goes and gets that
data: slate entries, the moneyline board, the run-line board, the fitted
calibration, and the model line per game.

Read-only by construction. It fetches nothing from a network -- entries
arrive as an argument from whichever caller already built them (the API
cache, or the CLI) -- and it writes nothing. Publishing the card to the
frozen ledger is `src.appstate.card_ledger`'s job, deliberately kept
separate so that rendering a page can never append evidence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional, Sequence

from src.analysis import calibrate, daily_card, strength
from src.analysis import prices as prices_mod
from src.core import odds as odds_math
from src.detect import dossier as dossier_mod

CALIBRATION_STORE = os.path.join("data", "processed", "card_calibration.json")

# The main run line. Alternates are a different bet and are not considered
# here: the card publishes one standard, quotable number per game, and
# "Padres -1.5" is a bet a reader can find at any book on the list.
RUN_LINE = 1.5

# Run-line rows come from the same multibook store as the moneyline, and the
# same floor applies -- a consensus over fewer books is that handful's
# opinion, not a market's.
MIN_BOOKS = prices_mod.MIN_BOOKS


def load_calibration(path: str = CALIBRATION_STORE) -> Optional[calibrate.Calibration]:
    """The Platt fit written by `scripts/fit_card_calibration.py`, or None.

    None is a real answer and callers must handle it: an uncalibrated model
    says 73% about games that happen 60% of the time, so a card built
    without this file has to say so rather than quietly publish the raw
    number. `card_for_date` sets `calibrated: False` in that case.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, ValueError):
        return None
    try:
        return calibrate.Calibration(
            float(blob["a"]), float(blob["b"]), int(blob["n"]),
            float(blob.get("base_rate", 0.5)))
    except (KeyError, TypeError, ValueError):
        return None


def _flatten(entry) -> dict:
    """One entry's `teams` and `starters` sections as a single feature dict.

    `src.analysis.strength` reads the same key names `src.pipeline.features`
    emits, which is what lets one model serve both the live slate and the
    backtest without a translation layer that could drift between them.
    """
    dossier = entry.get("dossier")
    payload = (dossier.to_dict() if isinstance(dossier, dossier_mod.Dossier)
               else (dossier or {}))
    sections = payload.get("sections") or {}
    flat = {}
    for name in ("teams", "starters"):
        section = sections.get(name)
        if isinstance(section, dict):
            flat.update(section)
    return flat


def _game_identity(entry, *, date: str) -> dict:
    from src.pipeline import slate as slate_mod

    dossier = entry.get("dossier")
    payload = (dossier.to_dict() if isinstance(dossier, dossier_mod.Dossier)
               else (dossier or {}))
    game = payload.get("game") or {}
    away, home = game.get("away_team"), game.get("home_team")
    number = game.get("game_number") or 1
    return {
        "game_id": f"{away}-{home}-{date}-{number}",
        "game_pk": game.get("game_pk"),
        "event_id": game.get("event_id"),
        "date": date,
        "away_team": away,
        "home_team": home,
        # Nicknames, not abbreviations: the card's whole job is to say "Take
        # Padres -1.5", and "Take SD -1.5" is a different, worse sentence.
        "away_name": slate_mod.team_nickname(away),
        "home_name": slate_mod.team_nickname(home),
        "away_probable": game.get("away_probable"),
        "home_probable": game.get("home_probable"),
        "first_pitch_utc": game.get("start_time_utc"),
        "venue": game.get("venue"),
        "state": game.get("state"),
        "features": _flatten(entry),
    }


def _has_started(first_pitch_utc, now: datetime) -> bool:
    """True when first pitch is at or before `now`.

    A game that has started is not a pick, and this is the check that the
    2026-09-09 slip was missing when it published 21 in-progress games as
    live recommendations. Unknown first-pitch time counts as STARTED, not as
    pregame: a partial schedule must fail closed.
    """
    if not first_pitch_utc:
        return True
    try:
        when = datetime.fromisoformat(str(first_pitch_utc).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= now.astimezone(timezone.utc)


def run_line_rows(date: str, *, rows=None, run_line: float = RUN_LINE) -> dict:
    """{game_id: {"away": {...}, "home": {...}}} for the standard run line.

    Built from the same multibook store and the same `prices.snapshot` the
    moneyline uses -- one de-vig, one book floor, one definition of best
    price. Nothing market-specific is invented here.

    The store carries BOTH sides of a spread on one row (`home_line`/
    `home_price`, `away_line`/`away_price`), so none of the 2026-09-09
    pairing problem applies: there is no pairing decision to get wrong. Rows
    at any line other than the standard one are skipped rather than pooled
    into it -- Padres -1.5 and Padres -2.5 are different bets and averaging
    them would produce a fair price for neither.
    """
    from src.pipeline import slate as slate_mod
    from src.pipeline import snapshots

    source = snapshots.pregame_rows(
        snapshots.read_multibook() if rows is None else rows)

    grouped = {}
    for row in source:
        if row.get("market") != "spreads":
            continue
        if snapshots.official_date(row.get("commence_time")) != date:
            continue
        try:
            home_line = float(str(row.get("home_line")))
            away_line = float(str(row.get("away_line")))
        except (TypeError, ValueError):
            continue
        if abs(abs(home_line) - run_line) > 1e-9 or abs(home_line + away_line) > 1e-9:
            continue
        away = slate_mod.team_abbrev_from_name(row.get("away_team") or "")
        home = slate_mod.team_abbrev_from_name(row.get("home_team") or "")
        if not away or not home:
            continue
        key = (away, home, date, home_line)
        grouped.setdefault(key, []).append(row)

    out = {}
    for (away, home, day, home_line), group in grouped.items():
        quotes = prices_mod.latest_instant([
            {"ts": r.get("observed_utc"), "book": r.get("book"),
             "away_price": r.get("away_price"), "home_price": r.get("home_price")}
            for r in group])
        if not quotes:
            continue
        snap = prices_mod.snapshot(quotes)
        if snap.get("skipped"):
            continue
        sides = snap.get("sides") or {}
        detail = {}
        for side in ("away", "home"):
            info = sides.get(side) or {}
            if info.get("skipped") or info.get("best_price") is None:
                continue
            detail[side] = {
                "best_price": info.get("best_price"),
                "best_book": info.get("best_book"),
                "consensus_probability": info.get("consensus_probability"),
                "books": (snap.get("dispersion") or {}).get("books"),
                "line": home_line if side == "home" else -home_line,
                "observed_utc": quotes[0].get("ts"),
            }
        if detail:
            # Doubleheaders share a matchup key here; game 1 is the only one
            # the standard board covers on this store, so the key is the
            # single-game shape the entries produce.
            out[f"{away}-{home}-{day}-1"] = detail
    return out


def moneyline_rows(opportunity_rows: Sequence) -> dict:
    """{game_id: {"away": row, "home": row}} from opportunities rows."""
    out = {}
    for row in opportunity_rows or ():
        gid, side = row.get("game_id"), row.get("side")
        if not gid or side not in ("away", "home"):
            continue
        if row.get("market") != "h2h":
            continue
        out.setdefault(gid, {})[side] = row
    return out


def card_for_date(entries: Sequence, opportunity_rows: Sequence, *, date: str,
                  now: Optional[datetime] = None,
                  calibration=None, multibook_rows=None) -> dict:
    """The published card for one date.

    Never raises on a thin slate; an empty schedule produces an empty card
    with `reason` set, which is a different statement from "nothing cleared
    the bar" and is the only empty state this surface has.
    """
    now = now or datetime.now(timezone.utc)
    cal = calibration if calibration is not None else load_calibration()

    games, model_lines = [], {}
    started = 0
    feature_rows = [_flatten(e) for e in entries or ()]
    league_rpg = strength.league_runs_per_game(feature_rows)

    for entry in entries or ():
        game = _game_identity(entry, date=date)
        if _has_started(game["first_pitch_utc"], now):
            started += 1
            continue
        if not league_rpg:
            continue
        try:
            line = strength.model_line(game["features"], league_rpg=league_rpg,
                                       run_line=RUN_LINE)
        except strength.StrengthError:
            continue
        if cal is not None:
            raw = line["p_home"]
            line["p_home_raw"] = raw
            line["p_home"] = cal.apply(raw)
            line["p_away"] = 1.0 - line["p_home"]
        games.append(game)
        model_lines[game["game_id"]] = line

    candidates = daily_card.build_pick_candidates(
        games,
        model_lines=model_lines,
        moneyline_rows=moneyline_rows(opportunity_rows),
        runline_rows=run_line_rows(date, rows=multibook_rows),
    )
    payload = daily_card.select(candidates)
    payload.update({
        "date": date,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "games_on_slate": len(entries or ()),
        "games_started": started,
        "games_open": len(games),
        "calibrated": cal is not None and cal.n >= calibrate.MIN_FIT_GAMES,
        "calibration": cal.to_dict() if cal is not None else None,
        "model_id": strength.MODEL_ID,
        "model_basis": strength.MODEL_BASIS,
    })
    if not payload["picks"]:
        payload["reason"] = _empty_reason(entries, started, len(games),
                                          len(candidates))
    return payload


def _empty_reason(entries, started, open_games, candidates) -> str:
    """Why there is no card, in the reader's terms.

    Every branch names a fact about the WORLD -- no games, all started, no
    prices -- and never a fact about our own confidence. "Nothing cleared the
    bar" is not among them and cannot be: this surface has no bar to clear.
    """
    if not entries:
        return "There are no major-league games scheduled today."
    if open_games == 0 and started:
        return (f"All {started} of today's games have already started. "
                f"Tomorrow's card goes up when the lines open.")
    if candidates == 0:
        return ("The books have not posted prices for today's games yet. "
                "The card goes up as soon as they do.")
    return "Today's card is not available."


def american_from_probability(p) -> Optional[int]:
    """A model probability as a price, for the "our number" line."""
    try:
        return int(round(odds_math.probability_to_american(p)))
    except (odds_math.OddsError, TypeError, ValueError):
        return None
