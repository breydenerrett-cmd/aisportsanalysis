"""Grade the market's own bullpen opinion against what innings 6-9 actually did.

THE QUANTITY BEING TESTED
-------------------------
A full-game price and a first-five price on the same team differ by exactly one
thing: innings six through nine. So

    full_game_fair - first_five_fair

is not a proxy for the market's view of the bullpens. It IS that view, in
probability units, published nightly and read by nobody.

This module asks whether it is any good. The outcome it is measured against is
directly observable: a game's first five have a leader, the full game has a
winner, and the cases where those differ are exactly the games innings six to
nine decided.

THE INSTANT PROBLEM, WHICH IS THE WHOLE DIFFICULTY
--------------------------------------------------
The two prices must come from the SAME MOMENT. A full-game price taken nine
hours out and a first-five price taken fifteen minutes out differ by the
bullpens AND by nine hours of market movement, and the second term is much
larger than the first.

The full-game backfill holds three snapshots a day; the first-five backfill
holds one per candidate game. So each first-five price is paired with the
nearest full-game snapshot in time, the separation is recorded, and pairs
further apart than MAX_PAIR_MINUTES are refused rather than used with a caveat.
A number built from mismatched instants is not a weaker version of this
measurement; it is a measurement of something else.

WHAT A POSITIVE RESULT WOULD AND WOULD NOT MEAN
-----------------------------------------------
If the implied shift predicts who wins innings 6-9, that says the market prices
bullpens competently -- which is interesting, and is NOT an edge. The edge, if
there is one, is in disagreeing with it, and that needs our own bullpen read on
the same games. Both are computed; only the second could ever be a bet.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.core import odds as odds_math

# Beyond this, the two prices are separated more by time than by bullpens.
MAX_PAIR_MINUTES = 90.0


class BullpenGradeError(RuntimeError):
    """Raised when the grading cannot be done honestly."""


def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _consensus_fair(bookmakers, market_key, home_name, away_name):
    """De-vigged consensus across every book quoting one market."""
    fairs = []
    for book in bookmakers or []:
        for market in book.get("markets") or []:
            if market.get("key") != market_key:
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
            fairs.append((fair_away, fair_home))
    if not fairs:
        return None
    return {"away_fair": sum(f[0] for f in fairs) / len(fairs),
            "home_fair": sum(f[1] for f in fairs) / len(fairs),
            "books": len(fairs)}


def pair_prices(first_five_rows, full_game_snapshots) -> dict:
    """Match each first-five price to the nearest full-game snapshot in time.

    `full_game_snapshots` is the raw season file from the odds backfill.
    Returns pairs plus a census of why rows were dropped -- a grading that
    silently keeps only what worked cannot be trusted about what it kept.
    """
    by_event = {}
    for record in full_game_snapshots:
        stamp = _parse(record.get("snapshot_at"))
        if stamp is None:
            continue
        for event in record.get("events") or []:
            by_event.setdefault(event.get("id"), []).append((stamp, event))

    pairs, dropped = [], {"no full-game snapshot": 0, "too far apart": 0,
                          "no first-five price": 0, "no full-game price": 0}

    for row in first_five_rows:
        data = row.get("data") or {}
        five_stamp = _parse(row.get("snapshot_at"))
        candidates = by_event.get(row.get("event_id")) or []
        if five_stamp is None or not candidates:
            dropped["no full-game snapshot"] += 1
            continue

        stamp, event = min(candidates,
                           key=lambda c: abs((c[0] - five_stamp).total_seconds()))
        separation = abs((stamp - five_stamp).total_seconds()) / 60.0
        if separation > MAX_PAIR_MINUTES:
            dropped["too far apart"] += 1
            continue

        home_name = data.get("home_team") or event.get("home_team")
        away_name = data.get("away_team") or event.get("away_team")
        five = _consensus_fair(data.get("bookmakers"), "h2h_1st_5_innings",
                               home_name, away_name)
        if not five:
            dropped["no first-five price"] += 1
            continue
        full = _consensus_fair(event.get("bookmakers"), "h2h",
                               home_name, away_name)
        if not full:
            dropped["no full-game price"] += 1
            continue

        pairs.append({
            "date": row.get("date"),
            "game_pk": row.get("game_pk"),
            "away_team": row.get("away_team"),
            "home_team": row.get("home_team"),
            "separation_minutes": round(separation, 1),
            "full_home_fair": round(full["home_fair"], 5),
            "five_home_fair": round(five["home_fair"], 5),
            # The market's bullpen opinion, in probability units.
            "implied_shift": round(full["home_fair"] - five["home_fair"], 5),
            "full_books": full["books"], "five_books": five["books"],
        })
    return {"pairs": pairs, "dropped": dropped}


def attach_outcomes(pairs, results_by_pk) -> dict:
    """What innings six to nine actually did, per pair.

    `late_home_gain` is the honest outcome variable: whether the home side
    improved its standing between the end of the fifth and the end of the game.
    A game tied through five that the home team wins is a gain; a home lead
    through five that becomes a loss is a loss. Games whose first five did not
    finish are void, not zero.
    """
    graded, dropped = [], {"no result": 0, "not final": 0, "first five void": 0}
    for pair in pairs:
        game = (results_by_pk or {}).get(pair["game_pk"])
        if not game:
            dropped["no result"] += 1
            continue
        if game.get("state") != "final":
            dropped["not final"] += 1
            continue
        five = game.get("first_five") or {}
        if not five.get("complete"):
            dropped["first five void"] += 1
            continue
        home_won = game.get("home_won")
        if home_won is None:
            dropped["no result"] += 1
            continue

        five_winner = five.get("winner")
        # -1, 0 or +1 for the home side's position after five.
        five_state = 0 if five_winner is None else (1 if five_winner == "home" else -1)
        final_state = 1 if home_won else -1
        graded.append(dict(
            pair,
            five_state=five_state,
            final_state=final_state,
            # Did the home side gain ground after the fifth?
            late_home_gain=int(final_state > five_state),
            late_home_loss=int(final_state < five_state),
            changed_hands=int(five_state != 0 and final_state != five_state),
        ))
    return {"graded": graded, "dropped": dropped}


def grade(graded) -> dict:
    """Does a larger implied shift actually predict the home side gaining late?

    Split at the median rather than at a threshold nobody chose. A threshold
    picked to make the split look good is the tuning this whole structure exists
    to prevent, and the median is the one cut that cannot be argued with.
    """
    if len(graded) < 40:
        return {"n": len(graded),
                "verdict": f"only {len(graded)} graded pairs; not worth reading"}

    shifts = sorted(g["implied_shift"] for g in graded)
    median = shifts[len(shifts) // 2]
    high = [g for g in graded if g["implied_shift"] > median]
    low = [g for g in graded if g["implied_shift"] <= median]

    def rate(rows, key):
        return round(sum(r[key] for r in rows) / len(rows), 4) if rows else None

    result = {
        "n": len(graded),
        "median_shift": round(median, 5),
        "high_group": {"n": len(high),
                       "late_home_gain": rate(high, "late_home_gain"),
                       "late_home_loss": rate(high, "late_home_loss")},
        "low_group": {"n": len(low),
                      "late_home_gain": rate(low, "late_home_gain"),
                      "late_home_loss": rate(low, "late_home_loss")},
        "changed_hands_rate": rate(graded, "changed_hands"),
        "mean_separation_minutes": round(
            sum(g["separation_minutes"] for g in graded) / len(graded), 1),
    }
    gain_high = result["high_group"]["late_home_gain"]
    gain_low = result["low_group"]["late_home_gain"]
    if gain_high is not None and gain_low is not None:
        result["difference"] = round(gain_high - gain_low, 4)
        result["direction_expected"] = (
            "a larger implied shift means the market favours the home bullpen, "
            "so the high group should gain late more often")
    return result
