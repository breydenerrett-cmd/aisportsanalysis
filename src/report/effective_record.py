"""THE RECONCILED RECORD (task B1) -- one read-only surface answering
"what is the CURRENT rule's actual record, and what did the rule right
before it do", per sport, for every sport this product publishes picks in
(MLB, NFL, UFC/MMA).

WHY THIS EXISTS
---------------
The owner opened staging 2026-09-24 and saw the headline record read
"11-13, -4.95u, 2 nights" with "Our first card rule: 73-40, +7.61u over 13
nights. Counted separately." beneath it, and no split by sport. His
questions: did the record get worse, did we change the old bets, why
isn't it split by sport.

Nothing was altered. `api/meta.py::_card_record` already follows
`src.report.card.ACTIVE_CARD_RULE`, which flipped to "v2" at
`CUTOVER_DATE` (2026-09-23). V1's ledger (evidence/cards_v1.jsonl) is
frozen and still reads 13 days, 73-40, +7.6063u exactly as it always has;
V2 (evidence/cards_v2.jsonl) is a brand-new rule counting its own picks
from zero, by owner design (see `web/js/landing.js`'s `fillProofPanel`).
This module does not change either number. It reads
`src.appstate.card_ledger` (MLB, NFL and MMA all already publish and
settle through it) and reshapes what comes back onto ONE comparable
contract per (sport, rule) COHORT, so a page can show "current" and
"previous" side by side without re-deriving any V1-vs-V2 difference by
hand, and can do the same for NFL's retired favourites rule and UFC's
single, still-ungraded rule.

THIS MODULE WRITES NOTHING. Every function here reads
`src.appstate.card_ledger` and `src.ledger.chain.HashChainLedger` through
their existing public, read-only functions (`record`, `record_v2`,
`history`, `history_v2`, `verify`, `HashChainLedger(...).read()`). It
never calls `publish`, `publish_v2`, `settle`, or anything else that
appends to a ledger, and it never touches `src/appstate/settlement.py`.

DIMENSIONS TRACKED, PER COHORT
-------------------------------
sport, rule id, behavioural epoch (`status`: "current"/"previous"),
public/shadow (see PUBLIC ONLY, below), market type (game/prop/total,
plus V2's fills as their own class), pick vs fill, outcome status
(win/loss/push/void, plus unresolved = published-not-yet-settled),
first-publication date, settlement date span, and the stable selection
id the ledger already joins on (game_pk/game_id/player_id -- this module
never re-derives that key, only reads figures already keyed by it).

PUBLIC ONLY, BY CONSTRUCTION
------------------------------
This module reads exactly the ledger paths the live, no-token
`/card/record` route reads for each sport: `card_ledger.store_path(sport)`
for MLB-v1/NFL/MMA, `card_ledger.CARD_STORE_V2` for MLB-v2. It never opens
a `*_shadow*` or per-arm variant store (`CARD_STORE_V1_SHADOW`,
`CARD_STORE_V2_SHADOW_A/C/E`, the T3v `CARD_STORE_V2_VAR_*` paths) --
those are internal test arms a visitor's `/card/record` call never
returns, so "public" here is true by which file was opened, never a
label chosen because it flatters a number. Every cohort this module
returns carries `"public": True` for exactly that reason; there is no
code path in this file that could produce a shadow cohort at all.

THE MARKET-SET MISMATCH, RESOLVED NOT JUST LABELLED
------------------------------------------------------
V1's top-level `card_ledger.record()` counts GAME picks only (see
`api/meta.py::_card_record`'s own docstring). V2's
`record_v2()["combined"]` sums MAIN and PLUS_MONEY picks across every
kind it carries (game AND prop), excluding fills. Comparing those two
numbers directly compares different populations. Every cohort's headline
`wins`/`losses`/.../`profit_units` in THIS module is the same population
for every rule: every settled PICK (never a fill), every market kind that
rule carries, pooled -- computed here by summing V1's own `by_kind`
breakdown (game+prop+total) exactly the way V2's `combined` already pools
game+prop. The per-kind figures stay individually visible in
`market_breakdown`, so a reader (or a caller that wants the strict
game-only comparison) can still see that slice.

METRIC CONTRACT
-----------------
- W/L/push/void come from `card_ledger`'s own settled figures; nothing
  here re-grades a pick.
- `unresolved` (published, not yet settled) is carried explicitly, never
  dropped -- see `_pending_pick_count`/`_v2_pending_count`.
- ONE stake/ROI denominator everywhere: `n_staked` (picks that graded win
  or loss; pushes/voids never enter it) and `roi_pct = profit_units /
  n_staked * 100`, the exact formula `record()`/`record_v2()` already
  use. Never switched to a picks-published or target-winnings
  denominator -- see `STAKE_BASIS`.
- `days` counts distinct settled dates for THIS cohort only (what
  `record()`/`record_v2()` already return), never every date in the file.
- `unresolved_count` (a pick a settle pass looked at but could not yet
  resolve to win/loss/push/void -- distinct from a permanent void, and
  distinct from `pending_count`, which never reached a settle pass at
  all) is read defensively from the ledger and defaults to 0 rather than
  raising on a ledger that predates the concept. Never folded into
  `settled_count` or dropped -- see `_fig_from_summary`.
- A cohort this process could not read comes back with `available: False`
  and every figure `None` -- never an invented 0-0 (`_unavailable_cohort`).
  A cohort that read fine and genuinely has zero settlements (UFC,
  2026-09-24: results are entered by hand and none have been yet) reports
  the real zero WITH `grading_state`/`reason` naming why, so it can never
  be mistaken for a tested-and-tied record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.appstate import card_ledger
from src.ledger.chain import HashChainLedger

# Flat one-unit stakes, the only stake plan this project uses anywhere
# (card_ledger's own module docstring). Every cohort's `roi_pct` is
# `profit_units / n_staked * 100` -- amount risked, never target
# winnings -- and `n_staked` counts only picks that graded win or loss,
# never pushes, voids or picks still pending. Stated once, here, rather
# than repeated per cohort so "consistent across versions" is a fact
# about the code, not a claim in copy that could drift from it.
STAKE_BASIS = (
    "Flat 1 unit per settled pick. ROI is profit units divided by picks "
    "staked (wins + losses only) -- pushes, voids and picks still pending "
    "are never in that denominator. Same formula for every rule, every "
    "sport, every night.")

PUBLIC_SPORTS = ("mlb", "nfl", "mma")
SPORT_LABEL = {"mlb": "MLB", "nfl": "NFL", "mma": "UFC"}

_MARKET_NAME = {"game": "game", "prop": "player prop", "total": "run/point total"}
_MARKET_ORDER = ("game", "prop", "total")


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------

def _blank_fig() -> dict:
    return {"wins": 0, "losses": 0, "pushes": 0, "voids": 0, "unresolved": 0,
            "n_staked": 0, "profit_units": 0.0, "win_rate": None, "roi_pct": None}


def _finish_fig(fig: dict) -> dict:
    fig["profit_units"] = round(fig.get("profit_units") or 0.0, 4)
    fig["win_rate"] = (round(fig["wins"] / fig["n_staked"], 4)
                        if fig.get("n_staked") else None)
    fig["roi_pct"] = (round(fig["profit_units"] / fig["n_staked"] * 100.0, 3)
                       if fig.get("n_staked") else None)
    return fig


def _fig_from_summary(summary: Optional[Mapping]) -> dict:
    """One of `record()`'s `by_kind` sub-dicts (or `record_v2()`'s
    main/plus_money/fills/combined), reshaped onto this module's one
    cohort-figure contract. `summary` may be missing entirely (an older
    ledger row with no prop/total keys) -- that is zero activity in that
    market, not a read failure, so it becomes a real, explicit zero.

    `unresolved` is read defensively (`.get`, default 0): a settled row
    can now carry picks that went through a settle pass but are not yet a
    terminal win/loss/push/void (a partial-settlement carry-forward), and
    an older ledger row written before that concept existed simply has no
    such picks -- zero, not unknown."""
    summary = summary or {}
    fig = {
        "wins": summary.get("wins") or 0,
        "losses": summary.get("losses") or 0,
        "pushes": summary.get("pushes") or 0,
        "voids": summary.get("voids") or 0,
        "unresolved": summary.get("unresolved") or 0,
        "n_staked": summary.get("n_staked") or 0,
        "profit_units": summary.get("profit_units") or 0.0,
    }
    return _finish_fig(fig)


def _sum_figs(figs: Sequence[Mapping]) -> dict:
    out = _blank_fig()
    for fig in figs:
        for key in ("wins", "losses", "pushes", "voids", "unresolved", "n_staked"):
            out[key] += fig.get(key) or 0
        out["profit_units"] += fig.get("profit_units") or 0.0
    return _finish_fig(out)


def _market_note(breakdown: Mapping[str, Mapping]) -> str:
    active = [k for k in _MARKET_ORDER
              if k in breakdown and breakdown[k].get("n_staked")]
    if not active:
        return "No settled picks in any market yet."
    names = [_MARKET_NAME.get(k, k) for k in active]
    if len(names) == 1:
        return f"{names[0].capitalize()} picks only."
    return ("Combines " + ", ".join(names[:-1]) + " and " + names[-1]
            + " picks together.")


def _pending_pick_count(pending_days: Sequence[Mapping]) -> int:
    """Picks published but not yet settled, from `history()`'s own
    `pending_days` (V1/NFL/MMA shape: one dict per unsettled published
    date, carrying that date's `picks`/`prop_picks`/`total_picks`)."""
    total = 0
    for day in pending_days:
        total += len(day.get("picks") or ())
        total += len(day.get("prop_picks") or ())
        total += len(day.get("total_picks") or ())
    return total


def _unavailable_cohort(*, sport: str, rule_id: str, status: str, label: str,
                         error: str) -> dict:
    return {
        "sport": sport, "rule_id": rule_id, "status": status, "label": label,
        "public": True, "available": False,
        "grading_state": "unavailable",
        "reason": f"record unavailable: {error}",
        "notice": None,
        "days": None, "date_span": None, "first_published": None,
        "wins": None, "losses": None, "pushes": None, "voids": None,
        "unresolved": None,
        "n_staked": None, "win_rate": None, "profit_units": None,
        "roi_pct": None,
        "market_breakdown": None, "market_note": None,
        "fills": None, "fills_tracked": False, "withdrawn": None,
        "published_count": None, "pending_count": None,
        "settled_count": None, "unresolved_count": None,
        "chain_ok": None, "rows_checked": None,
    }


def _grading_state(*, published_dates: set, settled_days: int,
                    pending_count: int, ungraded_reason: Optional[str]) -> tuple:
    """(`grading_state`, `reason`|None) -- the honest-absence half of the
    metric contract: a cohort with real published picks and zero
    settlements must say so, and say WHY when a reason is known, rather
    than rendering a record that reads as a tested-and-tied 0-0."""
    if not published_dates:
        return "no_publications_yet", "No picks have been published yet."
    if settled_days == 0:
        base = (f"{pending_count} pick{'s' if pending_count != 1 else ''} "
                f"published, 0 graded yet.")
        return "published_not_settled", f"{base} {ungraded_reason}".strip() if ungraded_reason else base
    return "graded", None


# ---------------------------------------------------------------------------
# V1-shaped cohorts (MLB-v1, NFL either rule, MMA) -- all read through the
# same generic `record()`/`history()` pair, which already pools game/prop/
# total apart via `by_kind` regardless of sport.
# ---------------------------------------------------------------------------

def _v1_style_cohort(*, sport: str, path: str, rule_id: str, filter_rule: Optional[str],
                      status: str, label: str, notice: Optional[str] = None,
                      ungraded_reason: Optional[str] = None) -> dict:
    try:
        rec = card_ledger.record(path=path, rule=filter_rule)
        hist = card_ledger.history(path=path, rule=filter_rule, limit=None)
    except Exception as exc:  # noqa: BLE001 -- honest-absence, never a 500
        return _unavailable_cohort(sport=sport, rule_id=rule_id, status=status,
                                    label=label, error=str(exc))

    breakdown = {kind: _fig_from_summary(summary)
                 for kind, summary in (rec.get("by_kind") or {}).items()}
    headline = _sum_figs(list(breakdown.values())) if breakdown else _blank_fig()

    settled_days = hist.get("days") or []
    pending_days = hist.get("pending_days") or []
    settled_dates = {d.get("date") for d in settled_days if d.get("date")}
    pending_dates = {d.get("date") for d in pending_days if d.get("date")}
    published_dates = settled_dates | pending_dates
    date_span = ({"first": min(settled_dates), "last": max(settled_dates)}
                 if settled_dates else None)
    pending_count = _pending_pick_count(pending_days)
    # `settled_count`: picks graded to a TERMINAL outcome (win/loss/push/
    # void). `unresolved_count`: picks a settle pass has already looked at
    # but could not yet resolve (a partial-settlement carry-forward --
    # neither a final result nor "not attempted"). `pending_count`: picks
    # published but not in ANY settled row yet. Three distinct, explicit
    # counts -- never one silently folded into another.
    settled_count = headline["wins"] + headline["losses"] + headline["pushes"] + headline["voids"]
    unresolved_count = headline["unresolved"]

    grading_state, reason = _grading_state(
        published_dates=published_dates, settled_days=len(settled_dates),
        pending_count=pending_count, ungraded_reason=ungraded_reason)

    try:
        chain = card_ledger.verify(path=path)
        chain_ok = bool(getattr(chain, "ok", True))
        rows_checked = getattr(chain, "rows_checked", None)
    except Exception:  # noqa: BLE001
        chain_ok, rows_checked = None, None

    return {
        "sport": sport, "rule_id": rule_id, "status": status, "label": label,
        "public": True, "available": True,
        "grading_state": grading_state, "reason": reason, "notice": notice,
        "days": len(settled_dates), "date_span": date_span,
        "first_published": min(published_dates) if published_dates else None,
        **{k: headline[k] for k in
           ("wins", "losses", "pushes", "voids", "unresolved", "n_staked",
            "win_rate", "profit_units", "roi_pct")},
        "market_breakdown": breakdown, "market_note": _market_note(breakdown),
        "fills": None, "fills_tracked": False, "withdrawn": None,
        "published_count": settled_count + unresolved_count + pending_count,
        "pending_count": pending_count, "settled_count": settled_count,
        "unresolved_count": unresolved_count,
        "chain_ok": chain_ok, "rows_checked": rows_checked,
    }


# ---------------------------------------------------------------------------
# V2-shaped cohort (MLB current rule only) -- record_v2/history_v2 carry a
# different shape (price_class/entry_class, fills as their own state) and
# no ready-made market-kind breakdown, so this rebuilds one from
# history_v2's per-day `graded` entries (each already frozen with its own
# `kind` -- see card_ledger._frozen_v2_entry). Read-only: this walks
# already-settled rows and sums them, it never grades or writes anything.
# ---------------------------------------------------------------------------

def _v2_market_breakdown(hist_v2: Mapping) -> dict:
    # RESULT_UNRESOLVED: read via getattr, not a direct attribute
    # reference. card_ledger may or may not carry this constant depending
    # on when this module is imported against it (a third, non-terminal
    # grading outcome for a pick a settle pass could not yet resolve --
    # distinct from a permanent VOID); this module never writes to
    # card_ledger.py, so it degrades to the documented literal instead of
    # raising if the constant is absent.
    unresolved_value = getattr(card_ledger, "RESULT_UNRESOLVED", "UNRESOLVED")
    breakdown: dict = {}
    for day in hist_v2.get("days") or ():
        for entry in day.get("graded") or ():
            if entry.get("entry_class") == "fill" or entry.get("withdrawn"):
                continue
            kind = entry.get("kind") or "game"
            slot = breakdown.setdefault(kind, _blank_fig())
            result = entry.get("result")
            if result == card_ledger.RESULT_WIN:
                slot["wins"] += 1
            elif result == card_ledger.RESULT_LOSS:
                slot["losses"] += 1
            elif result == card_ledger.RESULT_PUSH:
                slot["pushes"] += 1
            elif result == card_ledger.RESULT_VOID:
                slot["voids"] += 1
            elif result == unresolved_value:
                slot["unresolved"] += 1
            if result in (card_ledger.RESULT_WIN, card_ledger.RESULT_LOSS):
                slot["n_staked"] += 1
                slot["profit_units"] += entry.get("profit_units") or 0.0
    return {kind: _finish_fig(fig) for kind, fig in breakdown.items()}


def _v2_published_rows(path: str) -> tuple:
    """(latest published row per date, set of settled dates) -- the same
    "first publication is frozen, a republish overwrites the SAME date's
    slot" shape `card_ledger.history`'s own `published_by_date` builds,
    read directly because `history_v2` (T5's V2 counterpart) exposes
    settled days only, with no pending-publication list of its own yet."""
    latest_published: dict = {}
    settled_dates: set = set()
    for row in HashChainLedger(path).read():
        if row.get("kind") == card_ledger.KIND_PUBLISHED:
            latest_published[row.get("date")] = row
        elif row.get("kind") == card_ledger.KIND_SETTLED:
            settled_dates.add(row.get("date"))
    return latest_published, settled_dates


def _v2_cohort(*, path: str, rule_id: str, status: str, label: str,
               notice: Optional[str] = None) -> dict:
    try:
        rec = card_ledger.record_v2(path=path)
        hist = card_ledger.history_v2(path=path, limit=None)
    except Exception as exc:  # noqa: BLE001
        return _unavailable_cohort(sport="mlb", rule_id=rule_id, status=status,
                                    label=label, error=str(exc))

    # `combined` already pools MAIN + PLUS_MONEY across every kind (never
    # fills) -- exactly the "all markets, picks only" population V1's
    # summed by_kind produces above, so both rules' headlines describe the
    # same population (B1's resolved-not-labelled market-set mismatch).
    headline = _fig_from_summary(rec.get("combined"))
    fills = _fig_from_summary(rec.get("fills"))
    breakdown = _v2_market_breakdown(hist)

    settled_days = hist.get("days") or []
    settled_dates = {d.get("date") for d in settled_days if d.get("date")}
    date_span = ({"first": min(settled_dates), "last": max(settled_dates)}
                 if settled_dates else None)

    latest_published, ledger_settled_dates = _v2_published_rows(path)
    published_dates = set(latest_published.keys())
    pending_count = sum(
        len(row.get("picks") or ()) + len(row.get("prop_picks") or ())
        for date, row in latest_published.items()
        if date not in ledger_settled_dates)
    settled_count = (headline["wins"] + headline["losses"]
                     + headline["pushes"] + headline["voids"]
                     + fills["wins"] + fills["losses"]
                     + fills["pushes"] + fills["voids"])
    unresolved_count = headline["unresolved"] + fills["unresolved"]

    grading_state, reason = _grading_state(
        published_dates=published_dates, settled_days=len(settled_dates),
        pending_count=pending_count, ungraded_reason=None)

    try:
        chain = card_ledger.verify(path=path)
        chain_ok = bool(getattr(chain, "ok", True))
        rows_checked = getattr(chain, "rows_checked", None)
    except Exception:  # noqa: BLE001
        chain_ok, rows_checked = None, None

    return {
        "sport": "mlb", "rule_id": rule_id, "status": status, "label": label,
        "public": True, "available": True,
        "grading_state": grading_state, "reason": reason, "notice": notice,
        "days": len(settled_dates), "date_span": date_span,
        "first_published": min(published_dates) if published_dates else None,
        **{k: headline[k] for k in
           ("wins", "losses", "pushes", "voids", "unresolved", "n_staked",
            "win_rate", "profit_units", "roi_pct")},
        "market_breakdown": breakdown, "market_note": _market_note(breakdown),
        "fills": fills, "fills_tracked": True,
        "withdrawn": rec.get("withdrawn"),
        "published_count": settled_count + unresolved_count + pending_count,
        "pending_count": pending_count, "settled_count": settled_count,
        "unresolved_count": unresolved_count,
        "chain_ok": chain_ok, "rows_checked": rows_checked,
    }


# ---------------------------------------------------------------------------
# Per-sport snapshots (current + previous, where a previous rule exists)
# ---------------------------------------------------------------------------

def mlb_snapshot(*, v1_path: Optional[str] = None, v2_path: Optional[str] = None) -> dict:
    """MLB's current rule (V2 since `card.CUTOVER_DATE`) and V1, its
    frozen predecessor, always shown adjacent -- V1 keeps its own record
    forever; nothing here ever pools the two."""
    from src.analysis import best_bets_card, daily_card
    from src.report import card as card_mod

    v1_path = v1_path or card_ledger.CARD_STORE
    v2_path = v2_path or card_ledger.CARD_STORE_V2
    v1_rule_id = daily_card.CARD_RULE
    v2_rule_id = best_bets_card.V2.rule_id

    current_is_v2 = card_mod.ACTIVE_CARD_RULE == "v2"
    v2_cohort = _v2_cohort(
        path=v2_path, rule_id=v2_rule_id,
        status="current" if current_is_v2 else "previous",
        label="Our value card")
    v1_cohort = _v1_style_cohort(
        sport="mlb", path=v1_path, rule_id=v1_rule_id, filter_rule=None,
        status="previous" if current_is_v2 else "current",
        label="Our first card rule")

    return {
        "sport": "mlb", "sport_label": SPORT_LABEL["mlb"],
        "current": v2_cohort if current_is_v2 else v1_cohort,
        "previous": v1_cohort if current_is_v2 else None,
        "cutover_date": card_mod.CUTOVER_DATE if current_is_v2 else None,
    }


def nfl_snapshot(*, path: Optional[str] = None) -> dict:
    """NFL's live value rule (NFL_CARD_V2) and the retired favourites rule
    it replaced 2026-09-20 (NFL_CARD_V1, retired after it published San
    Francisco -950) -- one ledger file, two rules, never pooled
    (`card_ledger.record`'s own `rule` filter)."""
    from src.report import nfl_card as nfl_report

    path = path or card_ledger.store_path("nfl")
    current = _v1_style_cohort(
        sport="nfl", path=path, rule_id=nfl_report.LIVE_RULE,
        filter_rule=nfl_report.LIVE_RULE, status="current",
        label="Our NFL value rule", notice=nfl_report.NOTICE)
    previous = _v1_style_cohort(
        sport="nfl", path=path, rule_id=nfl_report.RETIRED_RULE,
        filter_rule=nfl_report.RETIRED_RULE, status="previous",
        label="Our first NFL rule", notice=nfl_report.RETIRED_NOTICE)

    return {
        "sport": "nfl", "sport_label": SPORT_LABEL["nfl"],
        "current": current,
        "previous": previous,
        "cutover_date": "2026-09-20",
    }


# The one fact this module states about UFC's grading gap, sourced from
# src/report/ufc_card.py's own module docstring ("there is no results API
# to settle against: settle_for_date reads src.pipeline.ufc_results, the
# manually-entered store `ufc result` writes to") -- never invented here,
# and never rendered as "0-0" with no explanation.
MMA_UNGRADED_REASON = (
    "UFC has no automated results feed; results are entered by hand and "
    "none have been entered for these picks yet.")


def mma_snapshot(*, path: Optional[str] = None) -> dict:
    """UFC's single rule (UFC_CARD_V1). No previous rule exists -- this is
    the first and only one so far."""
    from src.report import ufc_card as ufc_report

    path = path or card_ledger.store_path("mma")
    current = _v1_style_cohort(
        sport="mma", path=path, rule_id=ufc_report.RULE_ID,
        filter_rule=None, status="current", label="Our UFC card",
        notice=ufc_report.NOTICE, ungraded_reason=MMA_UNGRADED_REASON)

    return {
        "sport": "mma", "sport_label": SPORT_LABEL["mma"],
        "current": current, "previous": None, "cutover_date": None,
    }


_SNAPSHOT_BY_SPORT = {"mlb": mlb_snapshot, "nfl": nfl_snapshot, "mma": mma_snapshot}


def sport_snapshot(sport: str, **kwargs) -> dict:
    """One sport's snapshot by key ("mlb"/"nfl"/"mma") -- the dispatch
    `build()` uses, exposed on its own so a caller (a route, a test) that
    only wants one sport does not have to build all three."""
    try:
        fn = _SNAPSHOT_BY_SPORT[sport]
    except KeyError:
        raise ValueError(f"unsupported sport {sport!r}; "
                         f"expected one of {PUBLIC_SPORTS}") from None
    return fn(**kwargs)


def build(*, now: Optional[datetime] = None) -> dict:
    """The full B1 surface: every supported sport's current/previous
    cohorts, reconciled onto one contract. Read-only; every ledger read
    failure is contained to the one affected cohort (`available: False`),
    never raised past this function."""
    now = now or datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "stake_basis": STAKE_BASIS,
        "sports": {sport: sport_snapshot(sport) for sport in PUBLIC_SPORTS},
    }
