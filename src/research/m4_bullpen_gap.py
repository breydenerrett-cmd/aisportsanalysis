"""M4 -- is the market's own bullpen opinion internally consistent?

THE STRUCTURAL IDEA
-------------------
A book publishes two prices on the same game: the full-game moneyline and the
first-five-innings moneyline. The difference between them is not an opinion we
have to supply -- it IS the book's stated view of what the bullpens are worth.
If it prices a team at 55% for five innings and 52% for nine, it is saying the
relief corps costs that team three points.

That makes this the only hypothesis in the family that does not require us to
outguess anyone. We are checking whether two numbers the same book published at
the same moment are mutually consistent with what actually happened. Internal
inconsistency is a pricing error no matter who understands baseball better.

WHAT IS MEASURED
----------------
For each game with both prices:

  implied_f5    -- de-vigged home probability over innings 1-5
  implied_full  -- de-vigged home probability over the full game
  gap           -- implied_full - implied_f5, the market's bullpen view

Then against outcomes: does the F5 price forecast the F5 result well, does the
full price forecast the full result well, and is the gap systematically biased
in one direction?

THE BINDING CONSTRAINT, STATED BEFORE THE RUN
----------------------------------------------
Only a few hundred games in 2023-24 carry F5 prices with books attached. That
is small, and this hypothesis may simply be underpowered. If it is, the finding
is "underpowered" -- which is not the same claim as "no effect" and will not be
written up as one.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core import odds as odds_math
from src.model import discovery
from src.pipeline import slate as slate_mod
from src.data import parks
from src.research import f5_store

F5_ODDS_STORE = Path("data/historical/odds_first_five")

# Bias buckets over the implied bullpen gap, in probability points. A negative
# gap says the market expects the bullpens to cost the home team.
GAP_BUCKETS = ((-1.0, -0.02), (-0.02, -0.005), (-0.005, 0.005),
               (0.005, 0.02), (0.02, 1.0))


def _abbrev(name):
    if not name:
        return None
    try:
        return parks.canonical_team(slate_mod.team_abbrev_from_name(name))
    except Exception:  # noqa: BLE001 -- an unknown club drops the row, never guesses
        return None


def _consensus(bookmakers, market_key, away_name, home_name):
    """Mean de-vigged home probability across books quoting one market."""
    values = []
    for book in bookmakers or []:
        for market in book.get("markets") or []:
            if market.get("key") != market_key:
                continue
            prices = {o.get("name"): o.get("price")
                      for o in market.get("outcomes") or []}
            away, home = prices.get(away_name), prices.get(home_name)
            if away is None or home is None:
                continue
            try:
                _, home_fair = odds_math.devig_two_way(away, home)
            except odds_math.OddsError:
                continue
            values.append(home_fair)
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def read_f5_odds(season, store=F5_ODDS_STORE) -> list:
    """Stored first-five odds records for one season that actually carry books."""
    target = Path(store) / f"mlb_{season}.jsonl"
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if (record.get("data") or {}).get("bookmakers"):
            out.append(record)
    return out


def rows(seasons=(2023, 2024), odds_store=F5_ODDS_STORE,
         results_store=f5_store.DEFAULT_STORE, paths_by_event=None) -> list:
    """One row per game carrying both implied probabilities and both outcomes.

    A row needs the F5 price, the full-game price at the same moment, a settled
    five innings and a settled game. Anything missing drops the row rather than
    substituting a default -- a rain-shortened game in particular is void, not a
    zero, and `f5_store` already refuses to settle one.
    """
    settled = f5_store.read(results_store)
    out = []
    for season in seasons:
        for record in read_f5_odds(season, odds_store):
            data = record.get("data") or {}
            books = data.get("bookmakers") or []
            away_name = data.get("away_team") or record.get("away_team")
            home_name = data.get("home_team") or record.get("home_team")

            f5_probability, f5_books = _consensus(
                books, "h2h_1st_5_innings", away_name, home_name)
            if f5_probability is None:
                continue

            game_pk = str(record.get("game_pk"))
            outcome = settled.get(game_pk)
            if outcome is None or not outcome.get("complete"):
                continue
            # A five-inning moneyline can genuinely tie, and the provider
            # records that as None -- distinct from "not settled", which
            # `complete` already ruled out above. Ties are carried through and
            # counted, then excluded from win rates, because dropping them here
            # would hide fifteen percent of the sample.
            winner = outcome.get("winner")
            if winner not in ("away", "home", None):
                continue

            full_probability = None
            if paths_by_event is not None:
                path = paths_by_event.get(record.get("event_id"))
                if path is not None:
                    full_probability = path

            out.append({
                "game_pk": game_pk,
                "event_id": record.get("event_id"),
                "date": record.get("date"),
                "away_team": _abbrev(away_name),
                "home_team": _abbrev(home_name),
                "f5_probability": f5_probability,
                "f5_books": f5_books,
                "full_probability": full_probability,
                # A first five can end level, which the moneyline voids. Kept
                # as its own state so it is excluded from win rates rather than
                # scored as a loss for both sides.
                "f5_winner": winner,
                "f5_home_won": winner == "home",
                "f5_tie": winner is None,
            })
    return out


def calibration(data) -> dict:
    """Does the F5 price forecast the F5 result? Ties excluded, and counted."""
    decided = [r for r in data if not r["f5_tie"]]
    if len(decided) < 10:
        return {"n": len(decided), "ties": len(data) - len(decided),
                "reason": "below the sample floor"}
    for row in decided:
        row["_diff"] = (1.0 if row["f5_home_won"] else 0.0) - row["f5_probability"]
    effect = sum(r["_diff"] for r in decided) / len(decided)
    return {
        "n": len(decided),
        "ties": len(data) - len(decided),
        "actual_home_rate": sum(r["f5_home_won"] for r in decided) / len(decided),
        "implied_home_rate": sum(r["f5_probability"] for r in decided) / len(decided),
        "effect": effect,
        "clustered_p": discovery.clustered_two_sided_p(effect, decided),
        "ci": discovery.clustered_bootstrap(
            decided, lambda subset: sum(s["_diff"] for s in subset) / len(subset)),
    }


def gap_bias(data) -> dict:
    """Is the implied bullpen gap biased, and does the bias scale with it?

    Needs the full-game probability alongside the F5 one, so it returns a
    reason rather than a number when the caller did not supply paths.
    """
    usable = [r for r in data
              if r.get("full_probability") is not None and not r["f5_tie"]]
    if len(usable) < 10:
        return {"n": len(usable),
                "reason": "no full-game probability joined, or below the floor"}
    for row in usable:
        row["gap"] = row["full_probability"] - row["f5_probability"]

    buckets = {}
    for row in usable:
        for low, high in GAP_BUCKETS:
            if low <= row["gap"] < high:
                buckets.setdefault((low, high), []).append(row)
                break

    def score(subset):
        for row in subset:
            row["_diff"] = (1.0 if row["f5_home_won"] else 0.0) - row["f5_probability"]
        effect = sum(r["_diff"] for r in subset) / len(subset)
        return {"n": len(subset), "mean_gap": sum(r["gap"] for r in subset) / len(subset),
                "effect": effect,
                "clustered_p": discovery.clustered_two_sided_p(effect, subset)}

    return {
        "n": len(usable),
        "mean_gap": sum(r["gap"] for r in usable) / len(usable),
        "overall": score(usable),
        "by_gap": {f"{low:+.3f}..{high:+.3f}": score(subset)
                   for (low, high), subset in sorted(buckets.items())},
    }


def evaluate(seasons=(2023, 2024), odds_store=F5_ODDS_STORE,
             results_store=f5_store.DEFAULT_STORE, paths_by_event=None) -> dict:
    data = rows(seasons, odds_store, results_store, paths_by_event)
    if not data:
        return {"n": 0, "reason": "no game had both an F5 price and a settled five innings"}
    return {
        "n": len(data),
        "dates": len({r["date"] for r in data}),
        "f5_calibration": calibration(data),
        "gap_bias": gap_bias(data),
    }
