"""Top Opportunities: the day's best-priced sides, ranked, from price
verdicts alone.

WHAT THIS IS
------------
One row per priced (game, side): the best available American price on the
board, the de-vigged multi-book consensus it is measured against, and the
single-word `price_verdict` (`src.analysis.priceverdict.build_price_verdict`)
that comparison earns. Rows are ranked by `value_points` -- how much
better-than-fair the best price is -- and the top few whose word clears the
LEAN floor are `qualifying`: this is Task B2's "Top Opportunities" surface.

WHAT THIS IS NOT
----------------
Not a ranking by expected value, not a model's picks, not a prediction of
who wins. Every row's `independent_model` field is the literal statement
that no independent model probability exists yet, verbatim from
`priceverdict.build_price_verdict`. A game whose board is thin, stale, or
absent never enters `rows` at all -- it is named in `unpriced`, with why,
rather than padded into the ranking with a manufactured number.

ENGINE INTEREST IS A SEPARATE AXIS, NEVER A REASON FOR THE VERDICT
--------------------------------------------------------------------
Each row's `engine` key (when engine data is supplied) is
`src.report.engine_bridge.summarize_game`'s rollup of what the forward-test
systems did on this game -- CONTROL and MARKET_REFERENCE decisions never
surface as "interest" there, only FORWARD_TEST plays do, and they ride
alongside the price verdict rather than inside it. The price verdict's
`word` is computed from the board alone, before `engine` is ever
considered, and is never adjusted because a forward-test system also
picked the side.

PURE. This module reads no file and calls no network: `entries` (the
already-built slate, from `api.games._build_entries`), `date`, `now`, and
`engine_by_key` (the already-built join, from
`src.report.engine_bridge.decisions_for_date`) are all passed in.
`engine_bridge.summarize_game` is a pure rollup over data already handed
in, not a read, and is the one thing this module borrows from that module.

stdlib only. No fastapi/pydantic import (tests/test_api_boundary.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import derivative_prices
from src.analysis import gamepayload
from src.analysis import priceverdict
from src.analysis import synthesis as synthesis_mod
from src.report import engine_bridge

MARKET = "h2h"

# The three words a price verdict must clear to be worth showing as an
# opportunity at all -- FAIR PRICE and worse are, by construction, not a
# better-than-fair price, so they never qualify regardless of rank.
QUALIFYING_WORDS = ("STRONG VALUE", "VALUE", "LEAN")

EMPTY_REASON = "NO QUALIFYING BEST BETS RIGHT NOW"

LABEL = ("TOP OPPORTUNITIES — price versus de-vigged consensus "
         "(line-shopping value), not predictions")

_SIDES = (("away", "home"), ("home", "away"))


def _findings_by_side(entry: dict) -> dict:
    """`{"away": [Finding, ...], "home": [Finding, ...]}` for one entry --
    `neither`-sided findings support neither side and are dropped here."""
    out = {"away": [], "home": []}
    for finding in entry.get("findings") or ():
        side = getattr(finding, "side", None)
        if side in out:
            out[side].append(finding)
    return out


def _claim_wire(finding, limit: int) -> list:
    out = []
    for f in list(finding)[:limit]:
        label, _meaning = synthesis_mod.EVIDENCE_LABELS.get(
            f.evidence, (f.evidence, ""))
        out.append({
            "statement": f.claim,
            "sample_n": synthesis_mod.sample_size(f.sample),
            "evidence_label": label,
        })
    return out


def _engine_summary_for(entry: dict, engine_by_key: Optional[dict]) -> Optional[dict]:
    if not engine_by_key:
        return None
    game = entry["dossier"].game
    # Canonical abbreviations (ATH -> OAK, AZ -> ARI) -- engine_bridge.game_key
    # is the one place that decides how a game is keyed for this join.
    key = engine_bridge.game_key(game.get("away_team"), game.get("home_team"),
                                 game.get("date"))
    summaries = engine_by_key.get(key)
    return engine_bridge.summarize_game(summaries) if summaries else None


def _sort_key(row: dict):
    """value_points desc (None last), then books desc (None/absent last)."""
    vp = row.get("value_points")
    has_vp = vp is not None
    books = row.get("books")
    return (0 if has_vp else 1, -(vp if has_vp else 0.0),
            -(books if books is not None else -1))


def _unpriced_entry(game: dict, gid: str, reason: str) -> dict:
    return {
        "game_id": gid,
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "first_pitch_utc": game.get("start_time_utc"),
        "reason": reason,
    }


def _derivative_rows(date, now, entries, candidates=None) -> list:
    """Every non-moneyline contract on this date, priced the same way the
    moneyline above is priced.

    First-five totals and moneylines, team totals, alternate lines and
    pitcher strikeouts were captured daily and shown nowhere, because this
    module used to look at `MARKET` alone. They go through the SAME
    `priceverdict.build_price_verdict` as the moneyline: same six-book
    floor, same evidence tiers, same vocabulary. A contract below the floor
    keeps its row and carries `thin_or_unavailable_reason` with no verdict,
    so the reader sees the market exists and why it is not called.
    """
    if candidates is None:
        candidates = derivative_prices.candidates_for_date(date)

    # Derivative rows name their clubs, not this product's game ids. Joining
    # on the two club names is what lets a first-five line sit on the same
    # card as the game's moneyline; a contract whose clubs are not on this
    # slate keeps a null game_id rather than being attached to a guess.
    by_clubs = {}
    for entry in entries:
        game = entry["dossier"].game
        by_clubs[(game.get("away_team"), game.get("home_team"))] = (
            gamepayload.game_id(game), game)

    rows = []
    for cand in candidates:
        joined = by_clubs.get((cand.get("away_team"), cand.get("home_team")))
        gid, game = joined if joined else (None, {})
        row = {
            "game_id": gid,
            "away_team": cand.get("away_team"),
            "home_team": cand.get("home_team"),
            "first_pitch_utc": game.get("start_time_utc") or cand.get("commence_time"),
            "venue": game.get("venue"),
            "side": cand.get("side"),
            "market": cand.get("market"),
            "market_noun": cand.get("market_noun"),
            "line": cand.get("line"),
            "player": cand.get("player"),
            "wager_text": cand.get("wager_text"),
            "best_price": cand.get("best_price"),
            "best_book": cand.get("best_book"),
            "books": cand.get("books"),
            "observed_utc": cand.get("observed_utc"),
            # No findings exist for a derivative contract: the research
            # record is written against full-game sides. Empty lists, never
            # the moneyline's findings borrowed onto a different bet.
            "support_claims": [],
            "counter_claims": [],
            "engine": None,
        }
        if cand.get("consensus_probability") is None:
            row.update({
                "age_seconds": None,
                "market_implied_probability": None,
                "stated_implied_probability": None,
                "value_points": None,
                "price_verdict": None,
                "independent_model": priceverdict.NO_MODEL,
                "reasons": [],
                "risks": [],
                "thin_or_unavailable_reason": cand.get("thin_reason"),
            })
            rows.append(row)
            continue

        verdict = priceverdict.build_price_verdict(
            american_price=cand["best_price"],
            consensus_probability=cand["consensus_probability"],
            books=cand.get("books"), observed_utc=cand.get("observed_utc"),
            now=now, best_price=cand["best_price"],
            best_book=cand.get("best_book"))
        row.update({
            "age_seconds": verdict["age_seconds"],
            "market_implied_probability": verdict["market_implied_probability"],
            "stated_implied_probability": verdict["stated_implied_probability"],
            "value_points": verdict["value_points"],
            "price_verdict": verdict,
            "independent_model": verdict["independent_model"],
            "reasons": list(verdict["reasons"]),
            "risks": list(verdict["risks"]),
            "thin_or_unavailable_reason": None,
        })
        rows.append(row)

    rows.sort(key=_sort_key)
    return rows


def build_opportunities(entries, *, date, now=None, engine_by_key=None,
                        top_n: int = 5, derivative_candidates=None) -> dict:
    """The Top Opportunities payload for one date's already-built slate.

    `entries` is the list `api.games._build_entries` produces (each a dict
    with `dossier`/`findings`/`verdict`/`side`/`market`/`summary`, per
    `src.pipeline.briefing.make_entry`). `engine_by_key` is
    `src.report.engine_bridge.decisions_for_date(date)`'s return, or `None`
    when no engine data is available -- every row's `engine` key is then
    `None` rather than a fabricated rollup.
    """
    now = now or datetime.now(timezone.utc)
    entries = list(entries or ())
    rows = []
    unpriced = []

    for entry in entries:
        dossier = entry["dossier"]
        game = dossier.game
        gid = gamepayload.game_id(game)

        section = dossier.get("price_improvement")
        if not section or section.get("skipped"):
            reason = (dossier.gaps.get("price_improvement")
                      or (section or {}).get("skipped")
                      or "no multi-book observations for this game")
            unpriced.append(_unpriced_entry(game, gid, reason))
            continue

        sides = section.get("sides") or {}
        dispersion = section.get("dispersion") or {}
        books = dispersion.get("books")
        observed_utc = section.get("observed_utc")
        findings_by_side = _findings_by_side(entry)
        engine_summary = _engine_summary_for(entry, engine_by_key)

        produced_any = False
        for side, other in _SIDES:
            detail = sides.get(side) or {}
            if detail.get("skipped") or detail.get("best_price") is None:
                continue
            produced_any = True
            best_price = detail.get("best_price")
            best_book = detail.get("best_book")
            consensus_probability = detail.get("consensus_probability")

            verdict = priceverdict.build_price_verdict(
                american_price=best_price,
                consensus_probability=consensus_probability,
                books=books, observed_utc=observed_utc, now=now,
                best_price=best_price, best_book=best_book)

            side_team = game.get("away_team") if side == "away" else game.get("home_team")
            rows.append({
                "game_id": gid,
                "away_team": game.get("away_team"),
                "home_team": game.get("home_team"),
                "first_pitch_utc": game.get("start_time_utc"),
                "venue": game.get("venue"),
                "side": side,
                "market": MARKET,
                "wager_text": f"{side_team} moneyline",
                "best_price": best_price,
                "best_book": best_book,
                "books": books,
                "observed_utc": observed_utc,
                "age_seconds": verdict["age_seconds"],
                "market_implied_probability": verdict["market_implied_probability"],
                "stated_implied_probability": verdict["stated_implied_probability"],
                "value_points": verdict["value_points"],
                "price_verdict": verdict,
                "independent_model": verdict["independent_model"],
                "reasons": list(verdict["reasons"]),
                "risks": list(verdict["risks"]),
                "support_claims": _claim_wire(findings_by_side.get(side, ()), 3),
                "counter_claims": _claim_wire(findings_by_side.get(other, ()), 3),
                "engine": engine_summary,
                "thin_or_unavailable_reason": None,
            })

        if not produced_any:
            unpriced.append(_unpriced_entry(
                game, gid, "no priceable quote on either side"))

    rows.sort(key=_sort_key)

    # Every other market on the board. `rows` stays moneyline-only because
    # that is the shape the moneyline surfaces already consume; the ranking
    # below draws from BOTH, so the best-priced bet on the slate wins on
    # price whether it is a moneyline, a first-five under or a strikeout
    # prop. That is the whole reason this section exists.
    derivative = _derivative_rows(date, now, entries, derivative_candidates)
    derivative_priced = [r for r in derivative if r["price_verdict"] is not None]

    ranked = sorted(rows + derivative_priced, key=_sort_key)
    qualifying = [r for r in ranked
                  if r["price_verdict"]["word"] in QUALIFYING_WORDS][:top_n]
    priced_games = len({r["game_id"] for r in rows})

    return {
        "date": date,
        "generated_at": now.isoformat(),
        "checked_games": len(entries),
        "priced_games": priced_games,
        "rows": rows,
        "derivative_rows": derivative,
        "derivative_priced": len(derivative_priced),
        "derivative_thin": len(derivative) - len(derivative_priced),
        "qualifying": qualifying,
        "empty_reason": None if qualifying else EMPTY_REASON,
        "unpriced": unpriced,
        "basis": priceverdict.BASIS,
        "label": LABEL,
    }
