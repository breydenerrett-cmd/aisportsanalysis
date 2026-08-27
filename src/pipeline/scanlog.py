"""Append-only log of mismatch flags, and settlement against first-five results.

WHY THIS IS THE ONLY THING THAT CAN EVER TEST THE SCANNER
---------------------------------------------------------
Every threshold in src/pipeline/mismatch.py is a pre-registered guess. A full run of
FIP, ten points of K-BB%, a run per game of differential, 0.65 on the screen -- each
was set from baseball reasoning and not one has been validated against a result.

They cannot be validated backwards. The historical store holds no odds, so the market
screen -- one of the three suppressions, and the one carrying "advantages other people
aren't finding" -- cannot be run on a past game at all. And a threshold tuned against a
backtest stops being a hypothesis and becomes a description of that backtest.

So the scanner is graded forward, on games that had not been played when the flag was
recorded. That is the only genuinely sealed evidence available (see src/model/seal.py),
and it needs a log written before the games happen.

WHAT IS BEING GRADED, AND WHAT IS NOT
-------------------------------------
Not profit. Not return. The question is narrower and answerable:

    When the scanner flags a side, does that side win the first five more often than
    the price implied at the moment of flagging?

If the answer is no, the scanner is an expensive way to restate the market. If it is
yes, the scanner knows something -- which is still not the same as it being profitable
after vig, and this module never claims otherwise.

WHY PUSHES ARE EXCLUDED RATHER THAN SCORED
------------------------------------------
This falls out of the market's structure rather than being a convenience.

Every book offers h2h_1st_5_innings as a two-way market, so a tie through five is
refunded. De-vigging a two-way tie-refunded market yields P(win | no push), not P(win).
Grading only the non-push games therefore compares exactly like with like: a
conditional prediction against the condition it was made under.

Scoring pushes as half-wins, or dropping them from the numerator but not the
denominator, would compare a conditional probability against an unconditional outcome
and bias the result downward by roughly the push rate -- which is 15.9%, large enough
to turn a real effect into no effect.

THE COST OF A SCANNER THAT STAYS QUIET
--------------------------------------
Flags arrive at roughly one a day. A sample large enough to detect a few points of
edge is therefore a season's worth of waiting, and that is not a flaw in the logging;
it is the arithmetic consequence of a strategy whose whole point is to skip most days.
It is stated here so that a verdict is never quietly claimed on forty games.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core import odds as odds_math
from src.paths import evidence_path
from src.providers import mlb

DEFAULT_LOG = evidence_path("mismatch_flags.jsonl")

# Pre-registered, before a single flag was settled.
#
# 200 is not a comfortable number, it is a barely-adequate one. Detecting a 5-point
# edge over a ~0.60 base rate at conventional power needs several hundred; 200 is set
# as the point below which no verdict may be spoken at all, with a wider band for
# "leaning" so that a run of results is visible without being called.
MIN_FLAGS_FOR_VERDICT = 200
MIN_FLAGS_FOR_TREND = 50

# How far the realised hit rate must exceed the mean implied probability before the
# scanner is credited with knowing anything. Set above the noise a two-hundred-game
# sample carries, not at the point where a result would merely be interesting.
EDGE_PASS_MARGIN = 0.03


class ScanLogError(RuntimeError):
    """Raised when flags cannot be logged, read, or settled."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_flags(scan_result, path=DEFAULT_LOG, now=None) -> dict:
    """Append every flagged game to the immutable log.

    Candidates are NOT logged. A candidate is a game that cleared the talent bar and
    could not be priced, so there is no prediction to grade -- logging it would pad
    the sample with entries that can never resolve.

    The price at flag time is recorded alongside the side. Without it there is nothing
    to compare the outcome against, and a hit rate on its own says only that favourites
    win more often than underdogs.
    """
    flagged = scan_result.get("flagged") or []
    stamp = _timestamp(now)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    written = []
    with target.open("a", encoding="utf-8") as handle:
        for scan in flagged:
            entry = _entry(scan, stamp)
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            written.append(entry)

    return {"logged": len(written), "entries": written, "path": str(target)}


def _entry(scan, stamp) -> dict:
    screen = (scan.get("signals") or {}).get("market") or {}
    starters = (scan.get("signals") or {}).get("starters") or {}
    roster = (scan.get("signals") or {}).get("roster") or {}
    return {
        "logged_at": stamp,
        "game_pk": scan.get("game_pk"),
        "date": scan.get("date"),
        "away_team": scan.get("away_team"),
        "home_team": scan.get("home_team"),
        "side": scan.get("side"),
        "market": scan.get("market"),
        # The price is the whole point of the record. A flag without one cannot be
        # graded against anything.
        "away_price": screen.get("away_price"),
        "home_price": screen.get("home_price"),
        "implied_side_prob": screen.get("detail", {}).get("side_fair_prob"),
        "conditional_on_no_push": screen.get("detail", {}).get(
            "conditional_on_no_push", False),
        "starter_reason": starters.get("reason"),
        "roster_reason": roster.get("reason"),
        "starter_magnitude": starters.get("magnitude"),
        "roster_magnitude": roster.get("magnitude"),
    }


def read_log(path=DEFAULT_LOG) -> list:
    """Every entry ever appended, in order. Missing file is an empty log, not an error."""
    target = Path(path)
    if not target.exists():
        return []
    entries = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ScanLogError(f"{target}:{number} is not valid JSON") from exc
    return entries


def deduplicate(entries) -> list:
    """Keep the FIRST flag for each game.

    Re-running a scan later in the day is normal and appends again -- but the later
    entry carries a price recorded closer to first pitch, which is a better price for
    reasons that have nothing to do with the scanner. Keeping the earliest entry means
    the record is always graded against the price that was actually available when the
    scanner spoke.
    """
    seen, kept = set(), []
    for entry in entries:
        key = (entry.get("game_pk"), entry.get("side"), entry.get("market"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)
    return kept


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

WON = "won"
LOST = "lost"
PUSHED = "pushed"
VOID = "void"
UNRESOLVED = "unresolved"


def settle(entries, results_by_pk) -> dict:
    """Grade each flag against the first five innings of its game.

    `results_by_pk` maps game_pk to a parsed game record carrying `first_five`.
    A game that is not final, not present, or whose first five did not finish is
    UNRESOLVED or VOID -- never a loss. A flag that never resolved is not evidence
    against the scanner, and folding it in as one would understate it.
    """
    settled = []
    for entry in deduplicate(entries):
        game = (results_by_pk or {}).get(entry.get("game_pk"))
        settled.append(_settle_one(entry, game))
    return {"settled": settled, "counts": _counts(settled)}


def _settle_one(entry, game) -> dict:
    record = dict(entry)
    record["outcome"] = UNRESOLVED
    record["first_five"] = None

    if game is None:
        record["settle_note"] = "no result for this game_pk"
        return record
    if game.get("state") != "final":
        record["settle_note"] = f"game is {game.get('state')}, not final"
        return record

    five = game.get("first_five") or {}
    record["first_five"] = {
        "away_runs": five.get("away_runs"), "home_runs": five.get("home_runs"),
        "total_runs": five.get("total_runs"), "winner": five.get("winner"),
    }

    if not five.get("complete"):
        # Void, not lost. A market that refunds is not a result.
        record["outcome"] = VOID
        record["settle_note"] = five.get("reason")
        return record

    winner = five.get("winner")
    if winner is None:
        record["outcome"] = PUSHED
        record["settle_note"] = "tied through five; the two-way market refunds"
        return record

    record["outcome"] = WON if winner == entry.get("side") else LOST
    record["settle_note"] = f"{winner} led through five"
    return record


def _counts(settled) -> dict:
    counts = {WON: 0, LOST: 0, PUSHED: 0, VOID: 0, UNRESOLVED: 0}
    for record in settled:
        counts[record["outcome"]] = counts.get(record["outcome"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(settled) -> dict:
    """Did the flagged side beat the price it was flagged at?

    The comparison is realised hit rate against MEAN IMPLIED PROBABILITY, over the
    decided games only. Both quantities are conditional on no push, because the
    two-way price is, so they live in the same space and can be subtracted.

    A hit rate on its own is meaningless here: the scanner flags mismatches, and a
    mismatch is usually a favourite, so a high hit rate is exactly what the price
    already predicted. Only the difference carries information.
    """
    records = settled["settled"] if isinstance(settled, dict) else list(settled)
    counts = _counts(records)

    decided = [r for r in records
               if r["outcome"] in (WON, LOST) and r.get("implied_side_prob") is not None]
    n = len(decided)

    result = {
        "flags_logged": len(records),
        "counts": counts,
        "decided": n,
        "hit_rate": None,
        "mean_implied": None,
        "edge": None,
        "verdict": "insufficient sample",
        "verdict_detail": None,
        "min_for_verdict": MIN_FLAGS_FOR_VERDICT,
    }

    if not n:
        result["verdict_detail"] = (
            "no flag has resolved to a win or a loss with a recorded price yet")
        return result

    wins = sum(1 for r in decided if r["outcome"] == WON)
    hit_rate = wins / n
    mean_implied = sum(r["implied_side_prob"] for r in decided) / n
    result.update({
        "hit_rate": round(hit_rate, 4),
        "mean_implied": round(mean_implied, 4),
        "edge": round(hit_rate - mean_implied, 4),
        "wins": wins,
        "losses": n - wins,
    })

    if n < MIN_FLAGS_FOR_TREND:
        result["verdict_detail"] = (
            f"{n} decided flags. Below {MIN_FLAGS_FOR_TREND} nothing here is a "
            "trend; at roughly one flag a day this is weeks of data, and a run of "
            "wins at this size is what a coin looks like.")
        return result

    if n < MIN_FLAGS_FOR_VERDICT:
        direction = "ahead of" if result["edge"] > 0 else "behind"
        result["verdict"] = "leaning"
        result["verdict_detail"] = (
            f"{n} decided flags, {direction} the price by {abs(result['edge']):.1%}. "
            f"Not a verdict -- that needs {MIN_FLAGS_FOR_VERDICT}. Reported so a run "
            "is visible without being called.")
        return result

    if result["edge"] >= EDGE_PASS_MARGIN:
        result["verdict"] = "beats the price"
        result["verdict_detail"] = (
            f"over {n} decided flags the flagged side won {hit_rate:.1%} against a "
            f"mean implied {mean_implied:.1%}, a margin of {result['edge']:.1%}. "
            "That is evidence the scanner knows something the price did not. It is "
            "NOT evidence of profitability, which depends on the vig actually paid "
            "and has not been measured.")
    else:
        result["verdict"] = "does not beat the price"
        result["verdict_detail"] = (
            f"over {n} decided flags the flagged side won {hit_rate:.1%} against a "
            f"mean implied {mean_implied:.1%}. The scanner is restating the market. "
            "The thresholds are the hypothesis that failed; tuning them against this "
            "sample would replace a hypothesis with a description of it.")
    return result


def _timestamp(now=None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
