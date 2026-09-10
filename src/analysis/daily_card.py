"""THE CARD -- three to five bets, every day, said in English.

WHAT CHANGED AND WHY
--------------------
Every customer-facing surface in this product before today answered the
question "where is this bet cheapest". None of them answered "what should I
bet". The owner's instruction on 2026-09-10 was blunt about it: if the game
is Nationals-Padres there needs to be a bet, and it needs to say take the
Padres, and the page may never again tell a paying reader that nothing
cleared the bar.

So this module always returns picks. `MIN_PICKS` is a floor, not a target,
and the floor is met by lowering the LABEL rather than by inventing a claim
-- a pick published on a thin night says so on its own face.

THE RULE, PRE-REGISTERED
------------------------
Fixed here in code before the slate is read, so it cannot be chosen with the
candidate list in view:

  1. Every game that has not started and carries a moneyline on at least
     `prices.MIN_BOOKS` books is a candidate.
  2. The SIDE is whichever the de-vigged market consensus makes more likely.
     That is the market's opinion, not ours, and the copy says so.
  3. Our own run model (`src.analysis.strength`, calibrated walk-forward by
     `src.analysis.calibrate`) must AGREE that side is more likely. Where it
     disagrees, the pick is demoted, not promoted -- see WHY BELOW.
  4. The MARKET is the moneyline unless the run line prices the same opinion
     better against the model's own distribution, in which case it is the
     run line. One bet per game, never both.
  5. Rank by consensus confidence, tie-break on price standing. Publish at
     most `MAX_PICKS`.
  6. If fewer than `MIN_PICKS` survive step 3, fill from the demoted pile in
     the same order, each carrying `SPLIT` -- our model and the market do not
     agree on this one, and the reader is told that in those words.

WHY A DISAGREEMENT DEMOTES RATHER THAN PROMOTES
-----------------------------------------------
This is the single most counter-intuitive line in the file and it is the one
that keeps the 2026-09-09 incident from happening again in a new costume.

The obvious product is "our model says 62%, the market says 54%, bet it".
That is what every handicapping site sells. It requires the model to be
BETTER than the market, and ours is not: measured walk-forward over 1,896
games of 2026 (`scripts/backtest_card.py`), the model beats a coin that
knows only the home-field base rate by 0.0012 nats. A market beats that
baseline by an order of magnitude more. A model that weak, ranked by its
disagreements, selects its own largest errors -- with total confidence,
because the size of the disagreement IS the size of the error.

Uncalibrated it was worse still: it said 73% on games the home team won 60%
of. The ordering was fine; the scale was fiction. Platt scaling fixed the
scale. Nothing fixes the fact that the market knows more.

So the model is used for the one thing a weak-but-honest model is good for:
agreement. When two independent reads point the same way, the pick is
ordinary. When they split, the reader is told they split.

WHAT THIS CARD DOES NOT CLAIM
-----------------------------
It does not claim an edge. It does not claim positive expected value. It
does not claim the picks will win more than they lose against the price.
Backing market favourites wins a majority of individual bets and still loses
money at the vig, and the page has to say that where the reader can see it,
because a customer who works it out for themselves after a month is a
customer who was misled.

What it does claim is exactly this: a specific bet, at a named price and a
named book, published before first pitch, frozen, and graded in public
whether it wins or loses. That is the product.

Pure. stdlib only. Every input arrives as an argument.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

from src.analysis import strength
from src.core import odds as odds_math

# ---------------------------------------------------------------------------
# The shape of the card
# ---------------------------------------------------------------------------

# NEVER FEWER THAN THIS, on any night, for any reason short of an empty
# schedule. The floor is met by demoting labels, never by inventing a claim.
MIN_PICKS = 3
MAX_PICKS = 5

# One bet per game. Two bets on one game are one opinion sold twice, and a
# reader who takes both has double the stake on a single outcome without
# having chosen to.
MAX_PER_GAME = 1

# Confidence bands. These name how sure the MARKET is that this side WINS
# THE GAME -- not how sure we are, and not how likely the bet is to be
# profitable, which is a different question the page answers separately.
#
# The band is always read off the MONEYLINE consensus, even when the pick
# ends up being a run line. `confidence` below is that number and nothing
# else. An earlier draft labelled from whichever market got quoted, so a
# game could be ranked by its run-line consensus and labelled by its
# moneyline one; the card then listed a LEAN above a STRONG and the two
# numbers on the same card disagreed about the same game.
BAND_STRONG = 0.62
BAND_LEAN = 0.55

LABEL_STRONG = "STRONG"
LABEL_LEAN = "LEAN"
LABEL_SLIGHT = "SLIGHT"
LABEL_SPLIT = "SPLIT"

# A run line is preferred over the moneyline only when the model's own
# distribution prices it better by more than this, in probability points.
# A margin this small is not a claim about which is the better bet; it is a
# tie-break that stops the card flapping between two markets on rounding.
RUNLINE_PREFERENCE_POINTS = 0.02

STANDARD_RUN_LINE = 1.5

CARD_RULE = "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1"
CARD_BASIS = (
    "The side is whichever the multi-book market makes more likely. Our own "
    "run model has to agree, or the pick is labelled SPLIT. The bet is the "
    "moneyline unless the run line prices the same opinion better. Ranked by "
    "how confident the market is."
)
CARD_DISCLAIMER = (
    "These are reads, not guarantees, and they are not claims of positive "
    "expected value. Backing the more likely side wins most individual bets "
    "and still loses money at the vig. Every pick here is published before "
    "first pitch, frozen, and graded win or lose."
)


class CardError(ValueError):
    """The card could not be built at all -- no schedule, no prices."""


# ---------------------------------------------------------------------------
# Plain English
# ---------------------------------------------------------------------------

def _fmt_price(american) -> str:
    if american is None:
        return "—"
    n = int(round(float(american)))
    return f"+{n}" if n > 0 else str(n)


def _fmt_pct(p) -> str:
    return "—" if p is None else f"{round(float(p) * 100)}%"


def _fmt_runs(x) -> str:
    return "—" if x is None else f"{float(x):.1f}"


def _bet_sentence(pick) -> str:
    """The instruction, on its own line, with nothing else in it.

    This is the sentence the owner asked for by name: "Take Padres +1.5 for
    this value." No hedge, no register, no market jargon -- the reasoning
    goes underneath, where a reader who wants it will find it.
    """
    if pick["market"] == "run_line":
        line = f"+{STANDARD_RUN_LINE}" if pick["is_underdog"] else f"-{STANDARD_RUN_LINE}"
        return f"Take {pick['team_name']} {line} at {_fmt_price(pick['price'])}"
    return f"Take {pick['team_name']} to win at {_fmt_price(pick['price'])}"


def _why_sentences(pick) -> list:
    """Two or three sentences of real numbers. No word here is invented and
    none of them is a term of art a reader would have to look up."""
    out = []
    us, them = pick["us"], pick["them"]
    out.append(
        f"{pick['team_name']} score {_fmt_runs(us['runs_scored'])} runs a game "
        f"and give up {_fmt_runs(us['runs_allowed'])}. "
        f"{pick['opponent_name']} score {_fmt_runs(them['runs_scored'])} and "
        f"give up {_fmt_runs(them['runs_allowed'])}.")

    if pick.get("starter_name") and pick.get("opp_starter_name"):
        out.append(
            f"{pick['starter_name']} starts against "
            f"{pick['opp_starter_name']}.")

    # BOTH NUMBERS IN THIS SENTENCE ARE MONEYLINE NUMBERS, because the
    # sentence is about who WINS. On a run-line pick `market_probability` and
    # `model_probability` have been overwritten with cover probabilities, and
    # printing those under the words "to win" would describe the wrong bet.
    market_pct = _fmt_pct(pick["confidence"])
    model_pct = _fmt_pct(pick.get("model_probability_moneyline",
                                  pick["model_probability"]))
    if pick["label"] == LABEL_SPLIT:
        out.append(
            f"The market makes {pick['team_name']} a {market_pct} bet to win. "
            f"Our own numbers make it {model_pct} — we do not agree on this "
            f"one, and it is on the card because the slate was thin.")
    else:
        out.append(
            f"The market makes {pick['team_name']} a {market_pct} bet to win "
            f"and our own numbers agree at {model_pct}.")

    if pick["market"] == "run_line":
        out.append(
            f"We are taking the run line rather than the moneyline: "
            f"{pick['team_name']} have to "
            + ("stay within a run" if pick["is_underdog"]
               else "win by two or more")
            + f", and at {_fmt_price(pick['price'])} that pays better for the "
              f"same read.")

    if pick.get("price_note"):
        out.append(pick["price_note"])
    return out


def _price_note(best_price, consensus_probability, book, books) -> Optional[str]:
    """Where the price stands, in words, or nothing.

    Says nothing at all rather than dressing up a rounding error: below
    `PRICE_NOTE_FLOOR_POINTS` the gap is smaller than the movement between
    two captures and calling it out would be noise sold as insight.
    """
    if best_price is None or consensus_probability is None:
        return None
    try:
        stated = odds_math.american_to_probability(best_price)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    points = (consensus_probability - stated) * 100.0
    if points >= PRICE_NOTE_FLOOR_POINTS:
        return (f"{_fmt_price(best_price)} at {book} is the best of "
                f"{books} books — a little better than everyone else.")
    return f"{_fmt_price(best_price)} at {book} is the best of {books} books."


# Below this the price difference is inside the noise between two captures.
PRICE_NOTE_FLOOR_POINTS = 1.0


def _label(confidence: float, agrees: bool) -> str:
    """`confidence` is ALWAYS the moneyline consensus. See the band comments."""
    if not agrees:
        return LABEL_SPLIT
    if confidence >= BAND_STRONG:
        return LABEL_STRONG
    if confidence >= BAND_LEAN:
        return LABEL_LEAN
    return LABEL_SLIGHT


# ---------------------------------------------------------------------------
# Building one game's candidate
# ---------------------------------------------------------------------------

def _consensus_side(row_away, row_home):
    """Which side the de-vigged consensus makes more likely, or None.

    Both rows are `src.analysis.opportunities` rows for the same game -- they
    carry `market_implied_probability`, which is already de-vigged across the
    board at one capture instant.
    """
    pa = (row_away or {}).get("market_implied_probability")
    ph = (row_home or {}).get("market_implied_probability")
    if pa is None or ph is None:
        return None
    return ("away", pa) if pa > ph else ("home", ph)


def _model_probability(line: Mapping, side: str) -> float:
    return line["p_away"] if side == "away" else line["p_home"]


def _model_runline_probability(line: Mapping, side: str, *, underdog: bool) -> float:
    """The model's probability that this side covers the standard run line.

    Delegates to `strength.run_line_probability` rather than re-deriving it:
    the four cover cases are easy to get backwards, so they are written down
    once, next to the distribution they come from, and tested there.
    """
    return strength.run_line_probability(line, side, underdog=underdog)


def build_pick_candidates(games: Sequence, *, model_lines: Mapping,
                          moneyline_rows: Mapping,
                          runline_rows: Optional[Mapping] = None) -> list:
    """One candidate per game, or none for games that cannot carry a pick.

    `games`      -- dicts with event/game identity, teams, first pitch, and a
                    flattened feature mapping under "features".
    `model_lines`-- {game_id: strength.model_line(...) output}
    `moneyline_rows` -- {game_id: {"away": row, "home": row}} from
                    `src.analysis.opportunities`
    `runline_rows`   -- {game_id: {"away": {...}, "home": {...}}} carrying
                    `consensus_probability`, `best_price`, `best_book`,
                    `books`, `line`; optional, and its absence simply means
                    every pick is a moneyline.
    """
    runline_rows = runline_rows or {}
    out = []
    for game in games:
        gid = game.get("game_id")
        ml = moneyline_rows.get(gid) or {}
        line = model_lines.get(gid)
        if not line:
            continue
        picked = _consensus_side(ml.get("away"), ml.get("home"))
        if not picked:
            continue
        side, market_p = picked
        model_p = _model_probability(line, side)
        agrees = model_p > 0.5

        row = ml.get(side) or {}
        is_underdog = (row.get("best_price") or 0) > 0

        candidate = {
            "game_id": gid,
            "event_id": game.get("event_id"),
            "game_pk": game.get("game_pk"),
            "date": game.get("date"),
            "first_pitch_utc": game.get("first_pitch_utc"),
            "away_team": game.get("away_team"),
            "home_team": game.get("home_team"),
            "side": side,
            "team": game.get("away_team") if side == "away" else game.get("home_team"),
            "team_name": (game.get("away_name") or game.get("away_team")
                          if side == "away"
                          else game.get("home_name") or game.get("home_team")),
            "opponent_name": (game.get("home_name") or game.get("home_team")
                              if side == "away"
                              else game.get("away_name") or game.get("away_team")),
            "market": "moneyline",
            "line": None,
            "price": row.get("best_price"),
            "book": row.get("best_book"),
            "books": row.get("books"),
            "observed_utc": row.get("observed_utc"),
            # `confidence` NEVER changes when the pick switches to the run
            # line: it is the moneyline consensus, it is what the label and
            # the ranking read, and it is the one number on the card that
            # means the same thing on every pick.
            "confidence": market_p,
            "market_probability": market_p,
            "model_probability": model_p,
            "agrees": agrees,
            "is_underdog": is_underdog,
            "starter_name": (game.get("away_probable") if side == "away"
                             else game.get("home_probable")),
            "opp_starter_name": (game.get("home_probable") if side == "away"
                                 else game.get("away_probable")),
            "us": _team_numbers(game, side),
            "them": _team_numbers(game, "home" if side == "away" else "away"),
            "model": {
                "away_mean": round(line["away_mean"], 3),
                "home_mean": round(line["home_mean"], 3),
                "expected_total": round(line["expected_total"], 2),
                "expected_margin": round(line["expected_margin"], 3),
                "model_id": line.get("model_id"),
            },
        }
        candidate["price_note"] = _price_note(
            row.get("best_price"), row.get("market_implied_probability"),
            row.get("best_book"), row.get("books"))

        _maybe_switch_to_run_line(candidate, line, runline_rows.get(gid) or {})
        candidate["label"] = _label(candidate["confidence"], agrees)
        out.append(candidate)
    return out


def _team_numbers(game: Mapping, side: str) -> dict:
    f = game.get("features") or {}
    return {
        "runs_scored": f.get(f"{side}_runs_scored_pg"),
        "runs_allowed": f.get(f"{side}_runs_allowed_pg"),
        "wins": f.get(f"{side}_wins"),
        "losses": f.get(f"{side}_losses"),
    }


def _maybe_switch_to_run_line(candidate: dict, line: Mapping, rl: Mapping) -> None:
    """Swap the moneyline for the run line when the run line prices the same
    opinion better against the model's own distribution.

    "Better" is measured as model probability minus the run line's OWN
    de-vigged consensus, against the same quantity on the moneyline. Both
    numbers come off one joint distribution, so preferring one is a statement
    about price shape, not a second opinion about the game.
    """
    side = candidate["side"]
    row = rl.get(side) or {}
    price = row.get("best_price")
    cons = row.get("consensus_probability")
    if price is None or cons is None:
        return

    underdog = (candidate["price"] or 0) > 0
    p_cover = _model_runline_probability(line, side, underdog=underdog)
    ml_gap = candidate["model_probability"] - (candidate["market_probability"] or 0.0)
    rl_gap = p_cover - cons
    if rl_gap <= ml_gap + RUNLINE_PREFERENCE_POINTS:
        return

    candidate.update({
        "market": "run_line",
        "line": (STANDARD_RUN_LINE if underdog else -STANDARD_RUN_LINE),
        "price": price,
        "book": row.get("best_book"),
        "books": row.get("books"),
        "is_underdog": underdog,
        "model_probability_moneyline": candidate["model_probability"],
        "model_probability": p_cover,
        "market_probability_moneyline": candidate["market_probability"],
        "market_probability": cons,
    })
    candidate["price_note"] = _price_note(price, cons, row.get("best_book"),
                                          row.get("books"))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _rank_key(c):
    """Confidence first, then price standing. Both descending.

    `confidence` is the MONEYLINE consensus on every pick, including run-line
    picks -- so the order is "how sure is the market about who wins", one
    question asked the same way of every game, rather than a mix of two
    markets' numbers that cannot be compared with each other.

    Price standing is the tie-break and never the lead, for the same reason
    it is never the lead anywhere else in this repo: it is execution quality,
    it is derived from the same prices as the consensus it is measured
    against, and a card that ranked by it would be ranking by which book was
    slowest to move.
    """
    stated = None
    try:
        if c.get("price") is not None:
            stated = odds_math.american_to_probability(c["price"])
    except (TypeError, ValueError, ZeroDivisionError):
        stated = None
    standing = ((c.get("market_probability") or 0.0) - stated) if stated is not None else -1.0
    return (-(c.get("confidence") or 0.0), -standing)


def select(candidates: Sequence, *, min_picks: int = MIN_PICKS,
           max_picks: int = MAX_PICKS) -> dict:
    """The published card, plus a full account of what was left out.

    Returns `{"picks": [...], "filled": n, "considered": n, "rule": ...}`.
    `filled` is how many picks came off the demoted pile to reach the floor,
    and it is reported rather than hidden -- a reader is entitled to know
    that tonight's third pick is on the card because it is the third-best
    thing available and not because anything about it was convincing.
    """
    agreed = sorted([c for c in candidates if c.get("agrees")], key=_rank_key)
    split = sorted([c for c in candidates if not c.get("agrees")], key=_rank_key)

    picks, seen = [], set()
    for c in agreed:
        if len(picks) >= max_picks:
            break
        if c["game_id"] in seen:
            continue
        seen.add(c["game_id"])
        picks.append(c)

    filled = 0
    for c in split:
        if len(picks) >= min_picks:
            break
        if c["game_id"] in seen:
            continue
        seen.add(c["game_id"])
        picks.append(c)
        filled += 1

    for i, pick in enumerate(picks, start=1):
        pick["rank"] = i
        pick["bet"] = _bet_sentence(pick)
        pick["why"] = _why_sentences(pick)

    return {
        "picks": picks,
        "filled": filled,
        "considered": len(candidates),
        "agreed": len(agreed),
        "split": len(split),
        "rule": CARD_RULE,
        "basis": CARD_BASIS,
        "disclaimer": CARD_DISCLAIMER,
        "min_picks": min_picks,
        "max_picks": max_picks,
    }
