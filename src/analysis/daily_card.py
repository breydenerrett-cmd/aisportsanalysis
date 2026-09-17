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
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.analysis import propboard, strength
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

# THE CARD NO LONGER CHOOSES BETWEEN THE MONEYLINE AND THE RUN LINE.
#
# It used to, by comparing each market's model probability against that
# market's own consensus and taking whichever gap was larger. That
# comparison is dead because one of its two inputs is measured wrong:
# `src.analysis.strength` uses independent Poissons, and on 2026-09-10 two
# independent measurements put real run variance at 2.31x the mean rather
# than 1.0x (docs/PREREG_RUN_DISPERSION.md). The practical size of that
# error is on exactly the quantity a run line pays on -- 72.7% of real games
# are decided by two or more runs and the Poisson says 61.0%.
#
# So every run-line probability the card produced was roughly nine points
# low, the comparison was biased against the run line throughout, and the
# one run-line pick it did make on 2026-09-10 was selected by model error
# rather than by anything real. That pick stays in the ledger, frozen, with
# this note beside it; a record you can edit after the fact is not a record.
#
# The correction is NOT being applied yet. The pre-registered test passed
# every substantive check (calibration error fell 93% out of sample, and the
# moneyline improved) and FAILED its parameter-stability check at 0.3151
# against a 0.30 limit. The threshold is not moving. Rescue by threshold
# change is the one thing this project's research discipline exists to stop,
# and it does not become acceptable because the result is flattering.
#
# What replaces the choice is better than it anyway: the card publishes the
# moneyline and shows the run line beside it as an alternative, with the
# trade stated in words. No model has to be right for that to be useful, and
# a reader who wants the shorter price can take it knowing what it costs.
#
# T10 note (2026-09-17, coordinated with the copy-truth-sweep group): the
# overdispersion correction this comment calls "not being applied yet" is a
# DIFFERENT correction from `strength.DISPERSION`. `DISPERSION = 2.3352` was
# adopted into the live model on 2026-09-10 and has applied to every
# moneyline and run-line probability this module has computed since --
# see `strength.py`'s own comment above that constant. What stays
# unapplied is the separate run-line THRESHOLD correction referenced two
# paragraphs up (0.3151 against the 0.30 stability limit). So the run line
# is still only an alternative under V1 by rule -- this module's decision,
# unchanged since 2026-09-10 -- and not because any correction is missing
# from the model itself.
RUNLINE_AS_ALTERNATIVE = True

STANDARD_RUN_LINE = 1.5

CARD_RULE = "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1"
# T10b / CTS-1 (docs/DESIGN_BUILD_PLAN.json, R16-05 copy-truth-sweep,
# 2026-09-17, coordinated with that group). Only these two string VALUES
# changed -- CARD_RULE, every other constant in this module and every
# selection function are untouched, and this edit carries no change to what
# V1 selects or how it is labelled internally (registration section 10 for
# DAILY_CARD_BEST_BETS_V2 treats this as not a change to V1's selection).
# CARD_BASIS dropped "or the pick is labelled SPLIT" (SPLIT is being retired
# from every customer-facing surface, not from this module's LABEL_SPLIT
# constant or _label()'s own logic) and "confident" (banned register: a
# probability is not a feeling). CARD_DISCLAIMER dropped "still loses money
# at the vig", replaced with the amendment's own restated conclusion --
# registration section 0: "no edge, no positive expected return and no
# guarantee" -- and dropped "frozen", which named an internal mechanism
# (the ledger's lock) rather than a fact the reader needs.
CARD_BASIS = (
    "The side is whichever the multi-book market makes more likely. Our own "
    "run model has to agree. The bet is the moneyline unless the run line "
    "prices the same opinion better. Ranked by how likely the market makes "
    "it."
)
CARD_DISCLAIMER = (
    "These are reads, not guarantees, and they are not claims of positive "
    "expected value. Backing the more likely side wins most individual bets "
    "and shows no positive estimated return under the market benchmark. "
    "Every pick here is published before first pitch and graded win or "
    "lose."
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


def _format_american(price) -> str:
    """"-205", "+118". The sign is the whole meaning of the number."""
    if price is None:
        return "—"
    try:
        value = int(round(float(price)))
    except (TypeError, ValueError):
        return "—"
    return f"+{value}" if value > 0 else str(value)


def _breakeven_pct(price) -> Optional[str]:
    """How often this price has to win before it stops losing money.

    This is the implied probability of the STATED price, vig and all --
    deliberately not de-vigged. A reader is not being told what the market
    thinks; they are being told what THEY have to be right about to come out
    level, and the vig is part of what they pay. The de-vigged consensus is
    already on the same line as `market_probability`.

    Returns None on an unusable price rather than a placeholder: a sentence
    asserting a break-even it could not compute is worse than one that
    stops early.
    """
    if price is None:
        return None
    try:
        implied = odds_math.american_to_probability(price)
    except (odds_math.OddsError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not implied or not 0.0 < implied < 1.0:
        return None
    return f"{round(implied * 100)}%"


def _bet_sentence(pick) -> str:
    """The instruction, on its own line, with nothing else in it.

    This is the sentence the owner asked for by name: "Take Padres +1.5 for
    this value." No hedge, no register, no market jargon -- the reasoning
    goes underneath, where a reader who wants it will find it.
    """
    if pick["market"] == "run_line":
        line = f"+{STANDARD_RUN_LINE:g}" if pick["is_underdog"] else f"-{STANDARD_RUN_LINE:g}"
        return f"Take {pick['team_name']} {line} at {_fmt_price(pick['price'])}"
    return f"Take {pick['team_name']} to win at {_fmt_price(pick['price'])}"


def _why_sentences(pick) -> list:
    """A few sentences of real numbers. No word here is invented and none of
    them is a term of art a reader would have to look up.

    THE DOCSTRING USED TO SAY "two or three" AND THE FUNCTION RETURNED FIVE:
    the runs comparison, the starter matchup, market-versus-us, the run-line
    trade, and a price note. On the card that rendered as a paragraph per
    pick, and the owner's reading of the result on 2026-09-10 was "a lot of
    AI slop language and a lot of fluff... keep it minimal, to the point."

    What survives is what a reader acts on: who scores and who gives up runs,
    who is pitching, how confident the market and we are, and -- when the bet
    is a run line rather than a moneyline -- what that actually means.
    """
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
    # EXPLICIT None, not `.get(key, default)`.
    #
    # Nothing ever WRITES `model_probability_moneyline` -- it is read here
    # and frozen by src/appstate/card_ledger.py, which means every pick in
    # evidence/cards_v1.jsonl carries it as an explicit null. `.get(key,
    # default)` returns the default only when the key is ABSENT, so a pick
    # re-read from the ledger would take None and render the model's
    # percentage as an em dash -- the number missing from the sentence that
    # exists to compare it.
    moneyline_p = pick.get("model_probability_moneyline")
    if moneyline_p is None:
        moneyline_p = pick.get("model_probability")
    model_pct = _fmt_pct(moneyline_p)
    if pick["label"] == LABEL_SPLIT:
        out.append(
            f"The market makes {pick['team_name']} a {market_pct} bet to win. "
            f"Our own numbers make it {model_pct} — we do not agree on this "
            f"one, and it is on the card because the slate was thin.")
    else:
        # "AGREE" USED TO MEAN TWO DIFFERENT THINGS IN ONE SENTENCE.
        #
        # `agrees` is a question about the WINNER -- `model_p > 0.5`, set in
        # select(). It says nothing about price. But this sentence rendered
        # it as agreement between two NUMBERS, and the two numbers are
        # directly comparable: `confidence` is the de-vigged multi-book
        # consensus and `model_probability` is Platt-calibrated, so both are
        # honest probabilities of the same event.
        #
        # So on 2026-09-11 the live card read "the market makes Mariners a
        # 60% bet to win and our own numbers agree at 54%" -- on four of its
        # five picks the model was BELOW the market, which is the direction
        # that removes the reason to bet, and the page called it agreement.
        # A reader cannot be expected to notice that 54 < 60 undoes the
        # sentence containing it.
        #
        # The fix is only wording. It changes no selection, no ranking and
        # no pick count: the card still publishes what it published, it just
        # stops describing a gap against us as though it were support.
        gap_points = (pick["model_probability"] - pick["confidence"]) * 100.0
        # THE NUMBER THE PRICE ACTUALLY REQUIRES, which the card has never
        # printed.
        #
        # The owner, 2026-09-11, looking at a published pick reading "the
        # market makes Dodgers a 65% bet to win and our own numbers agree at
        # 51%" at a price of -205: "the value just isn't there still".
        # He was right and the page gave him no way to see it -- -205 needs
        # 67.2% to break even, so 51% is not a close call, it is a bet our
        # own model says loses. Two percentages were on the page and the
        # third, the only one that decides, was not.
        #
        # MONEYLINE PICKS ONLY. On a run-line pick this sentence is about
        # who WINS while `price` is for a different bet entirely (see the
        # comment above on both numbers being moneyline numbers), and
        # printing that break-even here would attach one bet's threshold to
        # another bet's sentence.
        needed_pct = None
        if pick.get("market") == "moneyline":
            needed_pct = _breakeven_pct(pick.get("price"))
        # The threshold sentence, appended to whichever comparison follows.
        # Stated as what the PRICE needs, never as a verdict on the bet: the
        # reader is given the third number and left to do the one comparison
        # that matters.
        needs = (f" At {_format_american(pick['price'])} you need "
                 f"{needed_pct} to break even."
                 if needed_pct else "")

        if abs(gap_points) < AGREEMENT_BAND_POINTS:
            out.append(
                f"The market makes {pick['team_name']} a {market_pct} bet to "
                f"win and our own numbers land in the same place at "
                f"{model_pct}.{needs}")
        elif gap_points > 0:
            out.append(
                f"The market makes {pick['team_name']} a {market_pct} bet to "
                f"win. Our own numbers make it {model_pct} — a little higher "
                f"than the market, so the price is in your favour.{needs}")
        else:
            out.append(
                f"The market makes {pick['team_name']} a {market_pct} bet to "
                f"win. Our own numbers make it {model_pct} — lower than the "
                f"market, so we agree on the winner but the price is against "
                f"you. This is a read on the game, not value at this "
                f"price.{needs}")

    alt = pick.get("alternative")
    if alt and alt.get("trade"):
        # THE ALTERNATIVE IS OFFERED, NOT RECOMMENDED. Nothing in this
        # sentence depends on our run distribution being right, which is the
        # point -- see RUNLINE_AS_ALTERNATIVE.
        out.append("If you want the other side of that trade: " + alt["trade"])

    # THE PRICE NOTE IS NOT A REASON TO TAKE A BET. It read "-149 at
    # draftkings is the best of 8 books" -- line shopping, which the owner
    # ruled off the customer surface on 2026-09-10: "that has to stop. None
    # of that's important. Nobody fucking cares."
    #
    # The field is still computed and still on the pick, because the book and
    # its price are shown beside every bet already; it is no longer dressed
    # up as part of the case FOR the bet.
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

# How far the model probability has to sit from the de-vigged market
# consensus before the card describes a DIRECTION rather than saying the two
# landed in the same place. Both quantities are honest probabilities of the
# same event, so the comparison is meaningful -- but the model is calibrated
# on n=1896 and the consensus moves between captures, so a fraction of a
# point apart is not a disagreement worth narrating. Two points is
# deliberately wider than PRICE_NOTE_FLOOR_POINTS: that floor bounds capture
# noise on one price, this one has to clear capture noise AND calibration
# noise on two different estimates.
AGREEMENT_BAND_POINTS = 2.0


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

        _attach_run_line(candidate, runline_rows.get(gid) or {})
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


def _attach_run_line(candidate: dict, rl: Mapping) -> None:
    """Attach the same side's run line as an ALTERNATIVE, never as the pick.

    No model comparison decides anything here -- see RUNLINE_AS_ALTERNATIVE
    for why the comparison that used to live in this function was removed.
    What is attached is the market's own price for the same opinion,
    together with the trade stated in words, so a reader who wants the
    shorter number can take it knowing exactly what it costs them.

    The tradeoff sentence is composed from the price and the side alone.
    Nothing in it depends on our distribution being right.
    """
    side = candidate["side"]
    row = rl.get(side) or {}
    price = row.get("best_price")
    if price is None:
        return

    # THE LINE IS READ, NEVER INFERRED. An earlier draft derived it from the
    # sign of the moneyline price -- favourite implies -1.5, underdog
    # implies +1.5 -- which is wrong whenever the two markets disagree about
    # who is favoured, and they disagree often on a near-pick'em game.
    # Measured live on 2026-09-10: it printed "White Sox -1.5 at -185 pays
    # more", when -185 was the price for +1.5 and pays LESS than the -104
    # moneyline beside it. A bet instruction naming the wrong line is worse
    # than no alternative at all, and it is the same mistake the price board
    # made with spreads in the 2026-09-09 incident.
    line = row.get("line")
    if not isinstance(line, (int, float)):
        return
    line = float(line)
    if abs(abs(line) - STANDARD_RUN_LINE) > 1e-9:
        # Not the standard run line, so not the alternative this is for.
        return

    taking_runs = line > 0
    if taking_runs:
        trade = (f"{candidate['team_name']} +{STANDARD_RUN_LINE:g} at "
                 f"{_fmt_price(price)} is the safer side — it wins if they "
                 f"lose by one or win outright — and it pays less.")
    else:
        trade = (f"{candidate['team_name']} -{STANDARD_RUN_LINE:g} at "
                 f"{_fmt_price(price)} pays more, and needs them to win by "
                 f"two or more.")
    underdog = taking_runs

    candidate["alternative"] = {
        "market": "run_line",
        "line": line,
        "price": price,
        "book": row.get("best_book"),
        "books": row.get("books"),
        "consensus_probability": row.get("consensus_probability"),
        "is_underdog": underdog,
        "bet": (f"Take {candidate['team_name']} "
                f"{'+' if line > 0 else ''}{line:g} at {_fmt_price(price)}"),
        "trade": trade,
    }


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


# ---------------------------------------------------------------------------
# GAME TOTALS ON THE CARD
# ---------------------------------------------------------------------------
#
# ADDED 2026-09-14. The owner that morning: "merge the today bets for ALL
# BETS not just MLs include all best bets like player props ... we dont need
# a set time for analysis on props or MLs or all other Bets we havent gotten
# to yet, like run lines and the niche bets" -- totals named by name. The
# moneyline rule above (`select`) and the prop rule below (`select_props`)
# both already publish only where the market's opinion and our own agree;
# totals get the same shape, not a new one.
#
# THE RULE, PRE-REGISTERED, RIGHT HERE, BEFORE THE SLATE IS READ:
#
#   1. Candidates come from the multi-book totals board, at each game's OWN
#      consensus line -- the total the most books are currently quoting for
#      that game (`src.report.card.total_rows`). There is no single standard
#      total the way the run line has 1.5: a total moves with the park and
#      the day's two starters, so the line itself is read off the board
#      rather than fixed in advance.
#   2. The SIDE is whichever the de-vigged multi-book consensus makes more
#      likely at that line -- over or under -- read the same way `select`
#      reads the moneyline consensus.
#   3. AGREEMENT. Our own run model must ALSO make that side more likely
#      than not, at that exact line -- `src.model.strength.market_probabilities`
#      by way of `src.report.card`, which is the caller responsible for
#      passing this game's own total line into `model_line(totals=...)` so
#      `p_over` is computed at the market's own number, not a different one.
#      Disagreement drops the candidate outright. There is no fallback pile
#      for totals the way a thin moneyline night fills from its SPLIT pile:
#      a total nobody agrees on is not a total pick, full stop.
#   4. CLEARS ITS PRICE. Our probability for that side must beat the
#      break-even its best available price demands.
#   5. Ranked by MARKET probability, descending -- the same axis the
#      moneyline card ranks on, how sure the market is, not how sure we are.
#   6. At most `MAX_TOTAL_PICKS`, no minimum. A thin totals board is a true
#      state, exactly like a thin prop board (see `MAX_PROP_PICKS` below) --
#      nothing here fills a floor by lowering a label.
#
# Labelled by the SAME bands the moneyline card uses (STRONG/LEAN/SLIGHT),
# read off the MARKET probability -- there is no SPLIT label here either,
# because for a total pick disagreement is disqualifying, never a demotion.

MAX_TOTAL_PICKS = 3

TOTAL_CARD_RULE = "DAILY_CARD_TOTAL_MARKET_SIDE_MODEL_AGREEMENT_V1"
TOTAL_CARD_BASIS = (
    "The total side is whichever the multi-book market makes more likely, "
    "at that game's own consensus line. Our own run model has to agree "
    "that side is more likely too, and the price has to clear its own "
    "break-even. Ranked by how confident the market is. At most three.")


def _total_label(market_probability: float) -> str:
    """Same bands as the moneyline card (`_label`), read off the MARKET
    probability -- a total pick has already passed the agreement gate
    before it reaches this function, so there is nothing left to disagree
    about and no SPLIT label to assign."""
    if market_probability >= BAND_STRONG:
        return LABEL_STRONG
    if market_probability >= BAND_LEAN:
        return LABEL_LEAN
    return LABEL_SLIGHT


def _total_bet_sentence(c: Mapping) -> str:
    """"Take Over 8.5 runs at -110." The matchup lives in the pick's own
    meta (away/home team), not in this sentence -- the same split the
    moneyline and prop bet sentences use."""
    side_word = "Over" if c.get("side") == "over" else "Under"
    return (f"Take {side_word} {c.get('line'):g} runs at "
            f"{_fmt_price(c.get('price'))}")


def _total_why_sentences(c: Mapping) -> list:
    """One sentence, both numbers, the register `_why_sentences`' own
    agreement branch uses for the moneyline: the market's number, our
    number, and what the price needs."""
    side_word = "Over" if c.get("side") == "over" else "Under"
    market_pct = _fmt_pct(c.get("market_probability"))
    model_pct = _fmt_pct(c.get("model_probability"))
    sentence = (
        f"{c.get('away_name') or c.get('away_team')} at "
        f"{c.get('home_name') or c.get('home_team')}: the market makes "
        f"{side_word} {c.get('line'):g} runs a {market_pct} bet and our "
        f"own run numbers agree at {model_pct}.")
    needed_pct = _breakeven_pct(c.get("price"))
    if needed_pct:
        sentence += (f" At {_format_american(c.get('price'))} you need "
                     f"{needed_pct} to break even.")
    return [sentence]


def _is_whole_number(line) -> bool:
    try:
        return float(line).is_integer()
    except (TypeError, ValueError):
        return False


def build_total_candidates(games: Sequence, *, model_lines: Mapping,
                           total_rows: Mapping) -> list:
    """One candidate per game whose total clears every gate, or none.

    `total_rows` -- {game_id: {"line", "over": {...}, "under": {...},
    "books", "observed_utc"}}, from `src.report.card.total_rows`.
    `model_lines` -- {game_id: strength.model_line(...) output}; the CALLER
    (`src.report.card.card_for_date`) is responsible for having passed this
    game's own total line into `model_line(totals=[line])` so `p_over`
    carries a probability at the exact line the market is quoting --
    otherwise there is nothing here to agree or disagree with.
    """
    out = []
    for game in games:
        gid = game.get("game_id")
        detail = total_rows.get(gid)
        if not detail:
            continue
        line = detail.get("line")
        if not isinstance(line, (int, float)):
            continue
        over = detail.get("over") or {}
        under = detail.get("under") or {}
        over_p = over.get("consensus_probability")
        under_p = under.get("consensus_probability")
        if over_p is None or under_p is None:
            continue
        side, market_p = (("over", over_p) if over_p > under_p
                          else ("under", under_p))

        line_row = model_lines.get(gid)
        if not line_row:
            continue
        p_over_map = line_row.get("p_over") or {}
        p_over = p_over_map.get(line)
        if p_over is None:
            continue

        # WHOLE-NUMBER LINES CAN PUSH. FIXED 2026-09-14 (Opus checker
        # problem 1). `p_over[L]` is `P(total_runs > L)`, strict -- it
        # already excludes a push on the OVER side. But the old code read
        # the UNDER side as `1.0 - p_over[L]`, which is `P(total_runs <=
        # L)`: on a whole-number line that FOLDS the push in with the Under
        # win. The market's de-vigged number and the price's own break-even
        # are both measured ignoring the push (a push refunds the stake; it
        # settles neither side), so comparing a push-inflated Under against
        # either one is comparing numbers on two different bases.
        #
        # Live, BAL@NYM 8.0 on 2026-09-14: P(over) = 0.4754, P(push) =
        # 0.0754. The push-inflated Under read 0.5246 -- clearing -110's own
        # 52.38% break-even -- when the push-EXCLUDED Under is really
        # 0.4858, under it and under 0.5: the model actually leans Over. The
        # card published "Take Under 8 runs" on a false agreement and a
        # false clears-price claim, both.
        #
        # `p_over[L - 0.5]` is `P(total_runs > L - 0.5)`, which for an
        # integer `total_runs` equals `P(total_runs >= L)` -- so
        # `p_over[L - 0.5] - p_over[L]` is exactly the push mass, and both
        # sides read correctly once it is divided back out:
        #   Over,  push excluded: p_over[L] / (1 - push)
        #   Under, push excluded: (1 - p_over[L - 0.5]) / (1 - push)
        # `src.report.card.card_for_date` is the caller responsible for
        # having asked the model about `L - 0.5` too (see its own comment)
        # for exactly a whole-number line; if it did not, there is nothing
        # here to measure the push with and the candidate is refused rather
        # than measured wrong -- same discipline as the "line never asked
        # about" refusal just above.
        if _is_whole_number(line):
            p_at_half_below = p_over_map.get(float(line) - 0.5)
            if p_at_half_below is None:
                continue
            push = p_at_half_below - p_over
            if not (0.0 <= push < 1.0):
                continue  # float noise or a malformed grid -- refuse, don't guess
            denom = 1.0 - push
            if denom <= 0.0:
                continue
            model_p = ((p_over / denom) if side == "over"
                      else ((1.0 - p_at_half_below) / denom))
        else:
            model_p = p_over if side == "over" else 1.0 - p_over
        if not (model_p > 0.5):
            continue  # AGREEMENT. No fallback pile -- see the module note.

        info = over if side == "over" else under
        price = info.get("best_price")
        if price is None:
            continue
        try:
            breakeven = odds_math.american_to_probability(price)
        except (odds_math.OddsError, TypeError, ValueError, ZeroDivisionError):
            continue
        if not (0.0 < breakeven < 1.0) or not (model_p > breakeven):
            continue  # CLEARS ITS PRICE.

        out.append({
            "kind": "total",
            "game_id": gid,
            "game_pk": game.get("game_pk"),
            "event_id": game.get("event_id"),
            "away_team": game.get("away_team"),
            "home_team": game.get("home_team"),
            "away_name": game.get("away_name"),
            "home_name": game.get("home_name"),
            "first_pitch_utc": game.get("first_pitch_utc"),
            "line": line,
            "side": side,
            "price": price,
            "book": info.get("best_book"),
            "books": detail.get("books"),
            "market_probability": market_p,
            "model_probability": model_p,
            "observed_utc": detail.get("observed_utc"),
            "label": _total_label(market_p),
        })
    return out


def select_totals(candidates: Sequence, *,
                  max_picks: int = MAX_TOTAL_PICKS) -> dict:
    """The card's total picks: at most `max_picks`, no floor -- every
    candidate handed in already agreed and cleared its price
    (`build_total_candidates`); this only ranks and caps."""
    ranked = sorted(candidates,
                    key=lambda c: -(c.get("market_probability") or 0.0))
    picks = list(ranked[:max_picks])
    for i, pick in enumerate(picks, start=1):
        pick["rank"] = i
        pick["bet"] = _total_bet_sentence(pick)
        pick["why"] = _total_why_sentences(pick)
    return {
        "picks": picks,
        "considered": len(candidates),
        "rule": TOTAL_CARD_RULE,
        "basis": TOTAL_CARD_BASIS,
        "max_picks": max_picks,
    }


# ---------------------------------------------------------------------------
# PLAYER PROPS ON THE CARD
# ---------------------------------------------------------------------------
#
# ADDED 2026-09-12. The owner, this morning: "Did you wire everything? It's
# still showing ML's" -- the card is moneyline-first by rule (nothing above
# this line changes), but the likeliest player props that clear their price
# belong beside it, frozen and graded the same way.
#
# THE RULE, and it is `src.analysis.propboard`'s rule, not a new one:
#
#   1. Market: `propboard.assessable` -- `batter_hits` or `batter_total_bases`
#      only. Never home runs (no fair price exists to clear -- see that
#      module's docstring) and never any other likelihood-only market.
#   2. "More likely than not": probability > `propboard.LIKELY_FLOOR` (0.50).
#   3. "Clears its price": our probability beats the break-even the price
#      demands -- `probability > breakeven`.
#   4. A posted lineup, not the season-average fallback:
#      `expected_pa_source == "batting_slot"`.
#   5. The player's game has not started.
#   6. One pick per player -- his highest-probability surviving contract.
#   7. Ranked by OUR probability, descending, and ONLY that. Never by the
#      gap over the price: `propboard`'s own module docstring carries the
#      measurement for why (`scripts/probe_prop_value.py`, -13.4% selecting
#      on the gap against -9.1% for the control) and this file does not
#      re-litigate it.
#   8. `MAX_PROP_PICKS` picks, no minimum -- a thin prop board is a true
#      state, not a hole to fill with a demoted contract the way game picks
#      fill to `MIN_PICKS`.
#
# Pure, exactly like everything above it: every contract arrives as an
# argument, already carrying the game identity (`game_pk`, `event_id`,
# `away_team`, `home_team`, `first_pitch_utc`, `team`) that
# `src.report.card` joined on before calling this. This module does not
# reach for a schedule -- that would make it impure, and the whole point of
# `src.report.card` existing as a separate file is that IT does the
# reaching, and this file only decides.

MAX_PROP_PICKS = 3

# ADDED 2026-09-14 (Opus checker problem 4, second half). A pre-lineup
# contract's `probability` is built on `season_rate`, which is this
# batter's own rate over `season_games` PRIOR box rows -- often a
# double-digit sample two weeks into a season. Live today, the top three
# `all_bets` rows (84%/81%/78%) all rested on 11-13 games, and 5 of the top
# 10 prop contracts on the whole board were UNDERS at Coors Field, which is
# the shape a small-sample season rate produces when it has not yet met a
# park or an opposing pitcher (see docs/PRODUCT_DOCTRINE.md 5.4 and "the
# instrument is the suspect" in this repo's own research discipline). This
# gate is deliberately narrow: it only touches a PRE-LINEUP contract
# (`select_props(require_lineup=False)`, `expected_pa_source ==
# "season_average"`) -- a contract WITH a posted lineup is unaffected, and
# `season_games` missing entirely (a caller that built its own contract by
# hand rather than through `propboard.build`, which always sets it) is not
# refused either, since there is nothing here to measure the sample against.
MIN_SEASON_GAMES_FOR_PRELINEUP = 15

# THE MARKETS THE CARD WILL PICK FROM, declared here and nowhere else.
#
# 2026-09-12, caught by the second check before it shipped: the first draft
# gated on `propboard.assessable`, which is every market the board can
# publish AND de-vig -- three markets, not two. `batter_runs_scored` is
# assessable, so a runs contract could reach the card, and the card's own
# sentence builders only know hits and total bases: the bet would have
# printed "Take Juan Soto under 0.5 batter_runs_scored at -140" -- a payload
# field name on the front page -- and settlement (src/board/settle_props)
# keys runs as 'batter_runs', so the pick would have graded VOID forever
# with "no settlement rule" beside it on the record. Two runs contracts on
# the real 2026-09-12 board passed every other filter; they missed the card
# only because three hits/total-bases contracts happened to rank above
# them. The gate is now this tuple, and tests hold it equal to the sentence
# builders' vocabulary and inside the settlement rules.
PROP_MARKETS = ("batter_hits", "batter_total_bases")

PROP_CARD_RULE = "DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1"
PROP_CARD_BASIS = (
    "Player props that are more likely than not, clear their price, and "
    "have a posted lineup behind them. Ranked by how likely we make it, "
    "never by how big the gap against the price is. One pick per player, "
    "at most three."
)


def _prop_game_started(first_pitch_utc, now: datetime) -> bool:
    """Same fail-closed rule as `src.report.card._has_started`, duplicated
    rather than imported: `src.report` is the plumbing layer and imports
    THIS module, so the reverse import would be a cycle. An unreadable or
    absent first-pitch time counts as started -- a prop pick with no known
    kickoff time is not one this file will publish."""
    if not first_pitch_utc:
        return True
    try:
        when = datetime.fromisoformat(str(first_pitch_utc).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= now.astimezone(timezone.utc)


def _prop_label(probability: float) -> str:
    """Same bands as the moneyline card, read off OUR probability this
    time -- a prop pick has no separate market-vs-model split to report, so
    there is no SPLIT label here. Every candidate that reaches this function
    already cleared `propboard.LIKELY_FLOOR`, so SLIGHT is a real floor, not
    a name for "everything left over"."""
    if probability >= BAND_STRONG:
        return LABEL_STRONG
    if probability >= BAND_LEAN:
        return LABEL_LEAN
    return LABEL_SLIGHT


_PROP_MARKET_WORD = {"batter_hits": "hits", "batter_total_bases": "total bases"}


def _prop_bet_sentence(c: Mapping) -> str:
    """"Take Rafael Devers over 0.5 hits at -140." One line, one instruction,
    same register as `_bet_sentence` above."""
    line = c.get("line")
    line_str = f"{float(line):g}" if isinstance(line, (int, float)) else str(line)
    word = _PROP_MARKET_WORD.get(c.get("market"), c.get("market") or "")
    side = str(c.get("side") or "").lower()
    return (f"Take {c.get('player')} {side} {line_str} {word} "
            f"at {_fmt_price(c.get('price'))}")


def _ordinal(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _prop_why_sentences(c: Mapping) -> list:
    """Two sentences, built from the numbers already on the contract --
    never a verdict, never "value", never "edge". The season rate and the
    plate-appearance estimate come from `propboard.build` (the batter rows
    the board already read); nothing here recomputes them.

    FIXED 2026-09-12 (checker problem 3). `season_rate` on the contract is
    always the OVER outcome's rate -- `propboard.build` writes the same
    value onto both the Over and the Under contract for a line (that
    module's own `_season_rate`). The first draft of this function quoted
    it unconditionally, so an Under pick's why-sentence read the batter's
    HIT rate next to a `probability` that was the batter's MISS rate for
    the same threshold -- two numbers about the same bet that looked like
    they disagreed. Measured live: Kevin McGonigle Under 1.5 hits, our
    probability 0.758 (STRONG), rendered "has at least 2 hits in 18% of his
    games" -- the number for the side of the bet nobody took. On an Under
    the clause and the rate now both describe what the UNDER needs: at most
    `need - 1`, at a rate of `1 - season_rate`.
    """
    market = c.get("market")
    line = c.get("line") or 0.0
    need = int(math.floor(float(line))) + 1
    player = c.get("player") or "This batter"
    is_under = str(c.get("side") or "").strip().lower() == "under"

    def _at_least(word: str) -> str:
        return "at least one " + word if need <= 1 else f"at least {need} {word}s"

    def _at_most(word: str) -> str:
        cap = need - 1
        if cap <= 0:
            return f"no {word}s"
        return (f"{cap} {word}" if cap == 1 else f"{cap} {word}s") + " or fewer"

    if market == "batter_hits":
        clause = _at_most("hit") if is_under else _at_least("hit")
    elif market == "batter_total_bases":
        clause = _at_most("total base") if is_under else _at_least("total base")
    else:
        clause = (f"stays under {line:g} in {market}" if is_under
                  else f"clears {line:g} in {market}")

    season_rate = c.get("season_rate")
    if season_rate is None:
        rate = None
    else:
        rate = 1.0 - float(season_rate) if is_under else float(season_rate)

    # FIXED 2026-09-14 (Opus checker problem 4). The rate above comes from
    # `propboard._season_rate`, which reads this batter's PRIOR BOX ROWS --
    # often a double-digit sample this early in a slate, not a season. Live
    # today: Jake Cronenworth's 84% probability and Ozzie Albies's 81% both
    # rest on `season_games` of 11 and 13. The sentence used to say "in
    # 100% of his games this season" -- true of the 11 games on file, false
    # of the word "season", and the two top-of-card pre-lineup picks read as
    # a full season's evidence when they were a season-average estimate
    # built on two weeks of it. If `season_games` is on the contract, the
    # sentence names the sample instead of implying the whole season; a
    # contract with no `season_games` at all (only possible from a caller
    # that built its own contract by hand, never `propboard.build`) keeps
    # the older phrasing rather than claim a sample size it cannot show.

    # OUR NUMBER LEADS (2026-09-12, seen on the first live build). The
    # sentence used to open with the season rate alone -- "Connor Norby has
    # at least one total base in 55% of his games this season" -- on a pick
    # labelled STRONG whose price needs 63%. The 55% is an input (the
    # batter's rate per game); our probability is that rate lifted by the
    # trips a 2nd-place hitter gets tonight, and it is the number the pick
    # stands on. Left unsaid, the reader had a rate below the break-even
    # and a label that said the opposite, and no way to see the step
    # between them. Same shape as the game pick's "Our own numbers make it
    # 62%".
    probability = c.get("probability")
    ours = (f"Our own numbers make it {_fmt_pct(float(probability))}. "
            if probability is not None else "")
    season_games = c.get("season_games")
    if rate is not None and isinstance(season_games, (int, float)) and season_games > 0:
        n = int(season_games)
        sample = (f"all {n}" if abs(rate - 1.0) < 1e-9
                  else f"{_fmt_pct(rate)} of the {n}")
        first = f"{ours}{player} has {clause} in {sample} games we have for him this season"
    elif rate is not None:
        first = f"{ours}{player} has {clause} in {_fmt_pct(rate)} of his games this season"
    else:
        first = f"{ours}{player} has {clause} in his prior games this season"

    slot = c.get("batting_slot")
    expected_pa = c.get("expected_pa")
    pa_source = c.get("expected_pa_source")
    if slot and expected_pa:
        first += (f"; batting {_ordinal(slot)} tonight, he should get about "
                  f"{float(expected_pa):.1f} trips to the plate.")
    elif pa_source == "season_average" and expected_pa:
        # ADDED 2026-09-14 for pre-lineup props (the owner: analysis "needs
        # to be ran pre emptively before any games"). No batting order is
        # posted for this game yet, so there is no slot to name -- the pick
        # says so, in these words, rather than let a reader think a posted
        # order stands behind the estimate.
        first += (f"; tonight's lineup is not posted yet, so this uses his "
                  f"season-average {float(expected_pa):.1f} trips to the "
                  f"plate.")
    elif slot:
        first += f", batting {_ordinal(slot)} tonight."
    elif expected_pa:
        first += f", with about {float(expected_pa):.1f} trips to the plate."
    else:
        first += "."

    market_probability = c.get("market_probability")
    if market_probability is not None:
        second = f"The market makes it {_fmt_pct(market_probability)}."
    else:
        second = "The market has no two-way price posted to compare against."
    needed_pct = _breakeven_pct(c.get("price"))
    if needed_pct:
        second += (f" At {_format_american(c.get('price'))} you need "
                   f"{needed_pct} to break even.")

    return [first, second]


def _build_prop_pick(c: Mapping, *, position: int) -> dict:
    """One contract, in the shared prop-pick shape -- the same shape whether
    it just got selected here or is being read back off a frozen ledger row.
    """
    probability = float(c.get("probability") or 0.0)
    pick = {
        "kind": "prop",
        "position": position,
        "rank": position,
        "label": _prop_label(probability),
        "player": c.get("player"),
        "team": c.get("team"),
        "game_pk": c.get("game_pk"),
        "event_id": c.get("event_id"),
        "away_team": c.get("away_team"),
        "home_team": c.get("home_team"),
        "first_pitch_utc": c.get("first_pitch_utc"),
        "market": c.get("market"),
        "line": c.get("line"),
        "side": c.get("side"),
        "probability": round(probability, 4),
        "market_probability": (
            None if c.get("market_probability") is None
            else round(float(c["market_probability"]), 4)),
        "breakeven": round(float(c.get("breakeven") or 0.0), 4),
        "price": c.get("price"),
        "book": c.get("book"),
        "books": c.get("books"),
        "batting_slot": c.get("batting_slot"),
        "expected_pa": c.get("expected_pa"),
        "expected_pa_source": c.get("expected_pa_source"),
        # ADDED 2026-09-14 (Opus checker problem 4) so the receipt carries
        # the sample size the why-sentence names, not just the sentence
        # text itself.
        "season_games": c.get("season_games"),
        # ADDED 2026-09-14. Whether a posted batting order stands behind
        # this estimate, or the batter's own season-average trips to the
        # plate stand in for it -- see `select_props`'s `require_lineup`.
        # Read straight off `expected_pa_source` rather than carried as a
        # separate input, so it can never say something the estimate it
        # describes does not.
        "lineup_posted": c.get("expected_pa_source") == "batting_slot",
        "observed_utc": c.get("observed_utc"),
        "locked": False,
        "locked_at": None,
    }
    pick["bet"] = _prop_bet_sentence(c)
    pick["why"] = _prop_why_sentences(c)
    return pick


def select_props(contracts: Sequence, *, now: Optional[datetime] = None,
                 max_picks: int = MAX_PROP_PICKS,
                 require_lineup: bool = True) -> list:
    """The card's player-prop picks: at most `max_picks`, no floor.

    `contracts` are the prop board's contracts for the date
    (`src.report.props.board_for_date` -> `propboard.build`), already
    enriched with game identity by `src.report.card` before this is called.
    Ranked by OUR probability, descending, and never by the gap over the
    price -- see the module-level comment above this section for the full
    rule and why the gap is disqualified.

    `require_lineup` -- ADDED 2026-09-14. The owner: analysis "needs to be
    ran pre emptively before any games." Default TRUE keeps this function's
    original behaviour (a `season_average` contract is never a pick) for
    every existing caller; `src.report.card._build_prop_picks` -- the live
    card's own caller -- passes FALSE so a contract priced off the batter's
    season-average plate appearances can reach the card before any lineup
    posts. Either way the pick says which estimate it stands on
    (`lineup_posted` on the built pick, and the why-sentence), and a
    `batting_slot` contract for the same player replaces a season-average
    one on the very next publish while the pick is still open -- the
    existing open-pick replacement in `card_ledger.publish` (an unlocked
    pick is rewritten wholesale by the next run's read, same game and
    market), not a new mechanism.
    """
    now = now or datetime.now(timezone.utc)

    eligible = []
    for c in contracts or ():
        market = c.get("market")
        # Membership in PROP_MARKETS, not `propboard.assessable` -- see the
        # constant's comment for the runs-scored contract that got through.
        if market not in PROP_MARKETS or not propboard.assessable(market):
            continue
        probability = c.get("probability")
        if probability is None or not (probability > propboard.LIKELY_FLOOR):
            continue
        breakeven = c.get("breakeven")
        if breakeven is None or not (probability > breakeven):
            continue
        if require_lineup and c.get("expected_pa_source") != "batting_slot":
            continue
        if (not require_lineup) and c.get("expected_pa_source") != "batting_slot":
            games = c.get("season_games")
            if (isinstance(games, (int, float))
                    and games < MIN_SEASON_GAMES_FOR_PRELINEUP):
                continue  # sample too thin to stand alone before a lineup posts
        if _prop_game_started(c.get("first_pitch_utc"), now):
            continue
        # The declared rank source gates selection too (2026-09-14): a prop
        # the merged list would refuse to rank is not a card pick. Under
        # "both" that means the market must also call it more likely than
        # not -- see `prop_rank_probability`. Under "model" this is a no-op.
        if PROP_RANK_SOURCE != "model" and not prop_rank_probability(c):
            continue
        eligible.append(c)

    def _rank_p(c):
        return (prop_rank_probability(c) if PROP_RANK_SOURCE != "model"
                else (c.get("probability") or 0.0))

    # One pick per player: his own best-ranked surviving contract.
    best_by_player: dict = {}
    for c in eligible:
        player = c.get("player")
        current = best_by_player.get(player)
        if current is None or (_rank_p(c), c.get("probability") or 0.0) > (
                _rank_p(current), current.get("probability") or 0.0):
            best_by_player[player] = c

    # RANKED BY PROBABILITY, NEVER BY THE GAP -- by the declared rank source
    # (the market's number under "both"), then our own number, then the
    # player name only for a deterministic order on an exact tie.
    ranked = sorted(best_by_player.values(),
                    key=lambda c: (-_rank_p(c), -(c.get("probability") or 0.0),
                                   str(c.get("player") or "")))

    return [_build_prop_pick(c, position=i)
            for i, c in enumerate(ranked[:max_picks], start=1)]


# ---------------------------------------------------------------------------
# PROP RANKING SOURCE -- a declared seam, not yet decided
# ---------------------------------------------------------------------------
#
# ADDED 2026-09-14 for the merged list below. `select_props` above still
# ranks its OWN array by our probability alone, and that rule stays exactly
# as measured (see the module comment above it) -- this is a SEPARATE
# question. When a prop pick sits in the ONE merged list beside game and
# total picks, which number does it rank against them by? A parallel
# calibration track may find our probability, the market's, or agreement
# between the two is the right read for that cross-kind comparison; until it
# reports, the merged list reads our own number, the same one the prop
# board's own ranking already uses, so the two never contradict each other
# about which prop matters more. `PROP_RANK_SOURCE` is the one place that
# decision is set -- the integrator sets it, not this file's author.
#
# SET TO "both" 2026-09-14 by the integrator, from
# docs/PROP_CALIBRATION_2026-09-14.md (rev. 2) and its checker's rerun. Why:
#  * the market's de-vigged number scored at least as well as ours on every
#    cut measured (Brier 0.2406 vs 0.2469 overall, and in all three markets);
#  * ours is miscalibrated toward UNDERS: Overs hit 53.2% against our 48.4%
#    (n=600), and among contracts both numbers call likely, Unders hit 53.6%
#    against our 61.7% (n=332) while Overs hit 61.3% against 61.7%;
#  * where ours ran 10+ points above the market, n=32 hit 40.6% against our
#    62.1% (the market said 50.2%).
# The sample is thin (5 dates; 09-12 alone is 69% of rows), so this is not
# proof the market is right. It is a refusal to rank a prop above a game on
# our number alone when the only settled evidence says our number runs high,
# most of all on the Unders topping today's board. "both" also puts the
# merged list on ONE axis: game and total picks already rank by the market's
# probability. It never selects or ranks by the gap between the two numbers;
# each number is checked against its own floor and price.
PROP_RANK_SOURCE = "both"  # "model" | "market" | "both"


def prop_rank_probability(contract: Mapping) -> float:
    """The probability a prop pick is ranked by in the MERGED list only --
    `select_props`'s own selection and ranking are untouched by this.

    "model"  -- our own probability.
    "market" -- the de-vigged market probability.
    "both"   -- ranked by the market's number, but only when the market's
                own number is above 50% AND our number clears the
                contract's break-even (the actual gate below, and the
                declared setting since 2026-09-14 -- the market is never
                itself checked against break-even here, only against the
                50% floor); a contract that fails either ranks last (0.0)
                rather than raising, because this function has to return a
                number for every prop pick handed to it, not refuse some.
    """
    if PROP_RANK_SOURCE == "market":
        return contract.get("market_probability") or 0.0
    if PROP_RANK_SOURCE == "both":
        # THE BOTH-GATE (orchestrator, 2026-09-14, after the integration pass).
        # The integrator's first cut required the MARKET's number to clear the
        # break-even too. A market number that beats the best available
        # price's break-even is a price discrepancy between books -- line
        # shopping, which this product does not sell -- and it held back
        # nearly every prop on the board, the same way no moneyline pick on
        # today's card clears its price by the market's number either. The
        # gate is the one docs/PROP_CALIBRATION_2026-09-14.md declares:
        # the MARKET says more likely than not (probability first, on the
        # number measured to be better calibrated), OUR number clears the
        # price, and the pick ranks by the market's number -- the same axis
        # game picks rank on. Its checker measured that this filters little
        # of our number's over-confidence (12 of 600); that is why the card
        # shows both numbers and the break-even on every prop, and why the
        # pick ranks by the market's number, never ours.
        breakeven = contract.get("breakeven")
        market_p = contract.get("market_probability")
        model_p = contract.get("probability")
        if breakeven is None or market_p is None or model_p is None:
            return 0.0
        if not (market_p > propboard.LIKELY_FLOOR) or not (model_p > breakeven):
            return 0.0
        return market_p
    return contract.get("probability") or 0.0


# ---------------------------------------------------------------------------
# THE MERGED LIST -- every kind of bet, ranked on one axis
# ---------------------------------------------------------------------------
#
# ADDED 2026-09-14. The owner: "merge the today bets for ALL BETS not just
# MLs include all best bets like player props". `picks`, `total_picks` and
# `prop_picks` stay exactly as they are -- the ledger freezes them and
# `card_ledger.settle` grades them, by kind, unchanged; nothing about this
# function feeds back into any of the three. `all_bets` is a VIEW built
# fresh, every time, from whichever version of those three arrays is being
# served (live or frozen), so it can never disagree with the arrays it was
# built from.

def merge_all_bets(picks: Sequence, total_picks: Sequence,
                   prop_picks: Sequence) -> list:
    """One ranked list spanning all three kinds.

    Ranked by the probability each kind's OWN rule already ranks it by:
    market probability for a game or a total pick (both read
    `market_probability` off the same de-vigged consensus), and
    `prop_rank_probability` for a prop pick. `index` is the pick's position
    in ITS OWN array -- `picks[index]` for a "game" item, `total_picks
    [index]` for a "total" one, `prop_picks[index]` for a "prop" one -- so
    the merge never copies a pick, it only orders references to the three
    arrays a caller already has.
    """
    # `lineup_posted` ON EVERY ITEM. FIXED 2026-09-14 (Opus checker problem
    # 3). A game or total pick never turns on a lineup, so it carries `None`
    # -- neither True nor False, because both would claim a fact this kind
    # of pick has no opinion about. A prop pick carries whatever
    # `_build_prop_pick` put on it (see that function): the merged list is a
    # VIEW over the three arrays, so this can only ever read the value that
    # is already there, never decide one. Without this field a page drawing
    # its ranking straight off `all_bets` showed "STRONG Take Jake
    # Cronenworth under 1.5 hits at -220" at position 1-3 with nothing
    # marking that no lineup was posted -- the pre-lineup label existed only
    # on `prop_picks[index]`, one hop away from the list a reader actually
    # reads top to bottom.
    items = []
    for i, p in enumerate(picks or ()):
        items.append({
            "kind": "game", "index": i,
            "probability": p.get("market_probability"),
            "label": p.get("label"), "bet": p.get("bet"),
            "first_pitch_utc": p.get("first_pitch_utc"),
            "lineup_posted": None,
        })
    for i, p in enumerate(total_picks or ()):
        items.append({
            "kind": "total", "index": i,
            "probability": p.get("market_probability"),
            "label": p.get("label"), "bet": p.get("bet"),
            "first_pitch_utc": p.get("first_pitch_utc"),
            "lineup_posted": None,
        })
    for i, p in enumerate(prop_picks or ()):
        # `None`, not 0.0, when the declared rank source refuses to rank this
        # prop (2026-09-14): under "both" a prop whose market number misses
        # its price came back 0.0 and the payload said "0%" for a bet our own
        # number puts at 62%. `None` claims nothing, and still sorts last.
        rank_p = prop_rank_probability(p)
        items.append({
            "kind": "prop", "index": i,
            "probability": rank_p if rank_p else None,
            "label": p.get("label"), "bet": p.get("bet"),
            "first_pitch_utc": p.get("first_pitch_utc"),
            "lineup_posted": p.get("lineup_posted"),
        })
    items.sort(key=lambda it: -(it.get("probability") or 0.0))
    for position, item in enumerate(items, start=1):
        item["position"] = position
    return items
