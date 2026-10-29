"""Why it lost: the losses of a hound's settled bets, sorted into bad luck, a bad price, a bad read, or unclear.

THE OWNER'S QUESTION (2026-10-29, HOCKEYCHIEF's training card): "real analysis of why it lost: variance, bad luck, or bad
strategy?" The card used to answer with a weak-spot list built from five bets. This is the other half of that answer: every
settled LOSS is looked at once, with the three kinds of evidence the ledger and the hindsight reviews already hold, and the
card says in a few lines how many of the losses look like variance and how many look like process.

THE FOUR WORDS, AND WHAT EACH ONE NEEDS
  bad luck   the pick beat the closing line (``clv_pts`` above zero: the market later agreed with it) and still lost, or it
             lost a CLOSE game: by one (run, goal) in MLB, NHL, soccer and their kin, or by three points or fewer in NFL and
             basketball (``CLOSE_MARGIN``), measured from the final score the grader stored. Tennis, MMA and the rest have no
             margin rule, so they have CLV only. A row without a score has CLV only, and one without either is unclear.
  bad price  ``clv_pts`` below zero: the price moved away from the pick before the start, so the market disagreed with it.
  bad read   the hindsight review of that bet (``src/ai/postmortems.py``) says the loss was mostly PROCESS
             (``luck_vs_process == "mostly_process"``). Only a GROUNDED review counts (one that cites a source a search really
             returned), the same stance as ``postmortems.summary_for``, and only when a review exists: this module reads no
             review itself and calls no model. The caller hands them in (``postmortems=``) or the live reader below fetches them.
  unclear    none of the above applied.

PRECEDENCE. One loss gets one word. A hindsight "process" verdict beats every number (a review that had the recap in front of
it saw more than a price and a score), and a hindsight "mostly luck" verdict is bad luck. After that the CLOSING PRICE decides
(above zero is luck, below zero is a bad price) because it measures the pick against the market, which a one-goal margin does
not; the margin only speaks when the closing price is missing or exactly flat. "mixed" and "unclear" reviews fall through to
the numbers.

WHAT IT NEVER SAYS. It describes the past. It does not say the next version will win, and the verdict ("mostly variance") is
about these losses, not about the hound. Fewer than ``MIN_LOSSES_TO_SAY`` losses is said to be too few to tell. The streak line
reuses ``diagnosis.streak_check`` (the longest losing run and how often a run that long turns up when the same results are put
in a random order), so the card and the coach's own read quote one number.

Deterministic and read-only: no model client, no network, no clock. Paper only.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from src.hounds.interact import rites

KINDS = ("bad_luck", "bad_price", "bad_read", "unclear")
KIND_LABEL = {"bad_luck": "bad luck", "bad_price": "bad price", "bad_read": "bad read", "unclear": "unclear"}
MIN_LOSSES_TO_SAY = 5            # fewer losses than this cannot tell luck from a bad strategy, and the card says so
MAX_EXAMPLES = 3
MAX_LINES = 5

# How close a loss has to be to count as bad luck, in the sport's own points, from the final score. A sport not listed has no
# margin rule (tennis sets, a fight's decision): only the closing price speaks for it.
ONE_SCORE_SPORTS = ("MLB", "NHL", "HOCKEY", "BASEBALL", "SOCCER")
THREE_POINT_SPORTS = ("NFL", "NCAAF", "GRIDIRON", "NBA", "WNBA", "NCAAB", "BASKETBALL")
CLOSE_MARGIN = {**{s: 1.0 for s in ONE_SCORE_SPORTS}, **{s: 3.0 for s in THREE_POINT_SPORTS}}

LUCK_PROCESS = "mostly_process"
LUCK_LUCK = "mostly_luck"


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _line_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# the rows
# ---------------------------------------------------------------------------

def settled_rows(bets: Sequence, rows: Sequence) -> list:
    """One dict per SETTLED forward bet (win, loss, push), oldest first, with what the grader stored beside it: the final score
    (``away_score``, ``home_score``) and the closing-line value (``clv_pts``), read from the ledger's graded rows by ``bet_id``.
    A bet whose graded row has neither keeps the fields as None; nothing is made up."""
    from src.hounds import user_settle
    graded = {}
    for r in rows or ():
        if isinstance(r, Mapping) and r.get("kind") == user_settle.KIND_GRADED and r.get("bet_id"):
            graded[r["bet_id"]] = r
    out = []
    for b in bets:
        if b.result not in rites.SETTLED_RESULTS:
            continue
        g = graded.get(b.bet_id) or {}
        clv = _num(g.get("clv_pts"))
        if clv is None:
            clv = _num(getattr(b, "clv_pts", None))
        out.append({"bet_id": b.bet_id, "result": b.result, "sport": str(b.sport or "").upper(), "market": b.market_key,
                    "side": b.side, "line": b.line, "selection": getattr(b, "selection_text", "") or "", "date": b.date,
                    "away_score": _num(g.get("away_score")), "home_score": _num(g.get("home_score")), "clv_pts": clv,
                    "order": str(b.start_utc or b.decision_utc or b.date or "") + "|" + str(b.bet_id)})
    out.sort(key=lambda r: r["order"])
    return out


def shortfall(row: Mapping) -> Optional[float]:
    """How far from winning a bet lost by, in the sport's own points (0 is a tie or a push on the line), or None when the sport
    has no margin rule, the score is missing, or the market is one a score cannot grade (a prop)."""
    if row.get("sport") not in CLOSE_MARGIN:
        return None
    away, home = row.get("away_score"), row.get("home_score")
    if away is None or home is None:
        return None
    side, market = row.get("side"), row.get("market")
    if market in ("h2h", "moneyline") and side in ("home", "away"):
        return (away - home) if side == "home" else (home - away)
    if market in ("spreads", "spread") and side in ("home", "away"):
        line = _line_number(row.get("line"))
        if line is None:
            return None
        diff = (home - away) if side == "home" else (away - home)
        return -(diff + line)
    if market in ("totals", "total") and side in ("over", "under"):
        line = _line_number(row.get("line"))
        if line is None:
            return None
        total = away + home
        return (line - total) if side == "over" else (total - line)
    return None


def is_close(row: Mapping) -> Optional[bool]:
    """True when the loss was inside the sport's close margin, False when it was not, None when no margin could be read."""
    miss = shortfall(row)
    if miss is None:
        return None
    return 0.0 <= miss <= CLOSE_MARGIN[row["sport"]]


# ---------------------------------------------------------------------------
# one loss
# ---------------------------------------------------------------------------

def _hindsight_word(review: Any) -> Optional[str]:
    """The ``luck_vs_process`` word of a GROUNDED review (a review given as a bare word is taken as grounded), else None."""
    if isinstance(review, str):
        return review
    if isinstance(review, Mapping) and review.get("grounded", True):
        word = review.get("luck_vs_process")
        return word if isinstance(word, str) else None
    return None


def classify(row: Mapping, review: Any = None) -> tuple:
    """``(kind, detail)`` for one LOSS, by the precedence in the module docstring. ``detail`` is a short fragment for the card."""
    word = _hindsight_word(review)
    if word == LUCK_PROCESS:
        return "bad_read", "the hindsight review blames the process"
    if word == LUCK_LUCK:
        return "bad_luck", "the hindsight review calls it mostly luck"
    clv = _num(row.get("clv_pts"))
    if clv is not None and clv > 0:
        return "bad_luck", f"it beat the closing price by {clv:.1f} pts and still lost"
    if clv is not None and clv < 0:
        return "bad_price", f"the price moved {abs(clv):.1f} pts against it before the start"
    close = is_close(row)
    if close:
        miss = shortfall(row)
        return "bad_luck", f"it lost a close one ({miss:g} from winning)"
    return "unclear", "no closing price or score separates it from a plain miss" if close is None else "it lost by more than a close margin"


# ---------------------------------------------------------------------------
# the breakdown
# ---------------------------------------------------------------------------

def _verdict(counts: Mapping, n: int) -> str:
    if n == 0:
        return "none"
    if n < MIN_LOSSES_TO_SAY:
        return "too_few"
    if counts["bad_luck"] * 2 > n:
        return "variance"
    if (counts["bad_price"] + counts["bad_read"]) * 2 > n:
        return "process"
    return "mixed"


def _headline(verdict: str, counts: Mapping, n: int) -> str:
    if verdict == "none":
        return "No settled losses to explain."
    noun = "loss" if n == 1 else "losses"
    if verdict == "too_few":
        return f"Only {n} {noun} so far, too few to tell bad luck from a bad strategy."
    if verdict == "variance":
        return f"Mostly variance: {counts['bad_luck']} of {n} losses beat the closing price or were close games."
    if verdict == "process":
        both = counts["bad_price"] + counts["bad_read"]
        return f"Mostly process: {both} of {n} losses took a price the market moved away from, or were a bad read."
    return f"Mixed: no single cause covers most of the {n} losses."


def _counts_line(counts: Mapping) -> str:
    return ", ".join(f"{KIND_LABEL[k]} {counts[k]}" for k in KINDS) + "."


def _streak_line(info: Mapping) -> Optional[str]:
    if not info or info.get("longest", 0) < 2:
        return None
    pct = round(float(info["chance"]) * 100)
    return (f"Longest losing run is {info['longest']}; a run that long turns up in {pct}% of random orders of the same results.")


def _example(row: Mapping, detail: str) -> str:
    what = (row.get("selection") or str(row.get("market") or "bet")).strip()
    day = f" ({row['date']})" if row.get("date") else ""
    return f"{what}{day}: {detail}."


def loss_breakdown(settled: Sequence[Mapping], postmortems: Optional[Mapping] = None) -> dict:
    """The losses among ``settled`` (``settled_rows``) sorted into ``bad_luck`` / ``bad_price`` / ``bad_read`` / ``unclear``.

    ``postmortems`` is ``{bet_id: review}`` where a review is the hindsight review dict (``luck_vs_process``, ``grounded``) or just
    its ``luck_vs_process`` word; None means no review could be read, and the bad read count is then zero by construction
    (``hindsight`` says so). Returns ``{n_losses, n_settled, counts, verdict, examples, streak, hindsight, summary, lines}``:
    ``examples`` are at most ``MAX_EXAMPLES`` short lines (a bad read first, then a bad price, bad luck, unclear), ``summary`` is
    the one-sentence verdict and ``lines`` are the three to five short lines the card prints."""
    reviews = postmortems if isinstance(postmortems, Mapping) else {}
    counts = {k: 0 for k in KINDS}
    found: dict = {k: [] for k in KINDS}
    losses = [r for r in settled if r.get("result") == "loss"]
    for r in losses:
        kind, detail = classify(r, reviews.get(r.get("bet_id")))
        counts[kind] += 1
        found[kind].append(_example(r, detail))
    n = len(losses)
    verdict = _verdict(counts, n)
    examples: list = []
    for kind in ("bad_read", "bad_price", "bad_luck", "unclear"):
        for text in found[kind]:
            if len(examples) < MAX_EXAMPLES:
                examples.append(text)
    streak = None
    decided = [r for r in settled if r.get("result") in ("win", "loss")]
    if len(decided) >= 2 and n:
        from src.hounds.interact import diagnosis
        streak = diagnosis.streak_check(decided)
    headline = _headline(verdict, counts, n)
    lines: list = []
    if n:
        lines.append(headline)
        lines.append(_counts_line(counts))
        extra = _streak_line(streak)
        if extra:
            lines.append(extra)
        for text in examples:
            if len(lines) < MAX_LINES:
                lines.append(text)
    return {"n_losses": n, "n_settled": len(settled), "counts": counts, "verdict": verdict, "examples": examples,
            "streak": streak, "hindsight": {"read": postmortems is not None, "reviewed": sum(1 for r in losses if r.get("bet_id") in reviews)},
            "summary": headline, "lines": lines}


# ---------------------------------------------------------------------------
# the live reader for the hindsight reviews (files only; no model is asked)
# ---------------------------------------------------------------------------

def live_hindsight(hound_id: str, bets: Sequence) -> Optional[dict]:
    """``{bet_id: review}`` for this hound's settled bets, from the hindsight review ledger (``postmortems.reviews_for_hound``:
    a file read, no model), or None when the ledger cannot be read. A bet is matched to its review by the same ticket key the
    reviewer wrote it under (``postmortem_store.bet_key`` over the bet's row). Never raises."""
    try:
        from src.ai import postmortem_store, postmortems
        from src.hounds import stats
        reviews = postmortems.default_engine().reviews_for_hound(hound_id)
        out = {}
        for b in bets:
            if b.result not in rites.SETTLED_RESULTS:
                continue
            review = reviews.get(postmortem_store.bet_key(hound_id, stats.bet_row(b, None)))
            if review:
                out[b.bet_id] = review
        return out
    except Exception:  # noqa: BLE001 -- the card is better without the hindsight line than not drawn at all
        return None
