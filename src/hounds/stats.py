"""The numbers behind every hound, computed once per change of the ledgers.

``get_book()`` returns a ``HoundBook``: per hound a ``HoundSummary``, a
newest-first list of ``BetRow`` and a ``SeriesPoint`` series, plus the stream
and the as-of day. It is rebuilt only when the size or mtime of an input
changes (``Sources.fingerprint``: a few ``stat`` calls, never a read), the
same cache rule ``api/meta.py`` follows. A request never touches a ledger.

WHAT IS COUNTED
---------------
  * ``record``, ``clv``, ``verdict``, ``series``, ``verified`` and status use
    FORWARD bets only. Replay bets are summarised in ``replay`` and shown in
    the bet list, tagged, but never added to any forward figure
    (docs/PREREG_HOUND_VERDICT.md section 1a).
  * ``units_recorded_price`` is the hound's own recorded settlement (engine
    account ledgers carry ``profit_units``; a pack bet is settled from its
    recorded price). ``units_average_price`` re-settles the same bets at the
    board's average price at decision time and is null unless that board
    exists for at least 90% of the hound's priced bets.
  * ``clv`` counts a bet only if it is MEASURABLE (prereg section 1): a
    closing-line value exists, the decision was stamped pre-commencement, and
    the closing capture was fresh. Everything else is a named absence upstream
    (``src.report.clv``) and simply is not in ``n``.

NOTHING HERE WRITES ANYTHING. The only side effects are the in-memory cache and
reading the ledgers named in ``Sources``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date as date_cls, timedelta
from typing import Optional

from src.core import odds as odds_math
from src.hounds import boards, house, ledgers, verdict as vd
from src.hounds.contract import (
    BetRow, ClvBlock, HoundSummary, KIND_BASELINE, Record, ReplayBlock,
    RetiredBlock, SeriesPoint, SPARK_POINTS, StreamItem, VerdictBlock)
from src.hounds.ledgers import Bet, Sources
from src.report import clv

PROVENANCE_PRE = clv.PROVENANCE_PRE_COMMITMENT


@dataclass
class HoundData:
    summary: HoundSummary
    series: list
    bets: list                      # BetRow, newest first (forward + replay)
    clv_points: list = field(default_factory=list)   # [(day, pts)] measurable forward


@dataclass
class HoundBook:
    hounds: dict                    # id -> HoundData, definition order
    stream: list                    # StreamItem, newest first
    as_of: Optional[str]
    built_utc: str
    fingerprint: tuple
    build_seconds: float = 0.0


# ---- unit arithmetic ---------------------------------------------------------------

def settle_units(result: Optional[str], american: Optional[int]) -> Optional[float]:
    """Flat one-unit profit of ``result`` at ``american``; None if unknowable."""
    if result in ("push", "void"):
        return 0.0
    if result == "loss":
        return -1.0
    if result == "win" and american:
        return round(odds_math.american_to_decimal(american) - 1.0, 4)
    return None


def recorded_units(bet: Bet) -> Optional[float]:
    if bet.result in ("push", "void"):
        return 0.0
    if bet.units is not None:
        return bet.units
    return settle_units(bet.result, bet.price)


def average_units(bet: Bet) -> Optional[float]:
    avg = bet.price_average if bet.price_average is not None else bet.avg_price
    if bet.result in ("push", "void"):
        return 0.0
    if avg is None:
        return None
    return settle_units(bet.result, avg)


# ---- text -----------------------------------------------------------------------------

def _signed(line) -> str:
    if line is None:
        return ""
    text = str(line)
    return text if text.startswith("-") else f"+{text}"


def selection_text(bet: Bet, teams: Optional[tuple]) -> str:
    if bet.selection_text:
        return bet.selection_text
    away, home = teams if teams else (None, None)
    team = {"home": home, "away": away}.get(bet.side)
    if bet.market_key == "totals" and bet.side in ("over", "under"):
        return f"{bet.side.capitalize()} {bet.line}" if bet.line else bet.side.capitalize()
    if bet.market_key == "spreads" and bet.side in ("home", "away"):
        return f"{team or bet.side} {_signed(bet.line)} run line".replace("  ", " ")
    if bet.market_key == "h2h_1st_5_innings" and bet.side in ("home", "away"):
        return f"{team or bet.side + ' side'} first-5 moneyline"
    if bet.market_key == "h2h" and bet.side in ("home", "away"):
        return f"{team or bet.side + ' side'} moneyline"
    return " ".join(x for x in (bet.side, bet.market_key, bet.line) if x)


def game_text(bet: Bet, teams: Optional[tuple]) -> str:
    if bet.game_text:
        return bet.game_text
    if teams and all(teams):
        return f"{teams[0]} at {teams[1]}"
    return ""


# ---- CLV for a bet ---------------------------------------------------------------------

def _pack_decision(bet: Bet) -> dict:
    from src.board import ids
    provenance = None
    if bet.segment == "replay":
        provenance = "replay"
    else:
        start, locked = clv._moment(bet.start_utc), clv._moment(bet.decision_utc)
        if start is not None and locked is not None and locked < start:
            provenance = PROVENANCE_PRE
    return {
        "system_id": bet.hound_id, "market_key": bet.market_key,
        "line": bet.line, "price_american": bet.price, "verdict": "play",
        "selection_id": ids.selection_id(sport="mlb", market_key=bet.market_key,
                                         side=bet.side or "", line=bet.line),
        "event_id": bet.event_id, "decision_utc": bet.decision_utc,
        "book": bet.book, "record_provenance": provenance,
        "consensus_fair": bet.consensus_fair,
        "books_at_decision": bet.book_count, "friction": None,
    }


def attach_clv(bets: list, index: dict) -> None:
    for bet in bets:
        if bet.market_key not in clv.MARKET_SHAPES or bet.price is None:
            continue
        record = bet.decision if bet.decision is not None else (
            _pack_decision(bet) if bet.side else None)
        if record is None:
            continue
        try:
            measured = clv.measure_decision(record, index)
        except clv.ClvError:
            continue
        bps = measured.get("clv_bps")
        if bps is None:
            continue
        bet.clv_pts = round(bps / 100.0, 4)
        bet.clv_measurable = (
            bet.segment == "forward"
            and measured.get("record_provenance") == PROVENANCE_PRE
            and measured.get("closing_lead_stale") is False)


# ---- per hound -----------------------------------------------------------------------------

def _round(x, nd=4):
    return None if x is None else round(x, nd)


def _day_before(day: str) -> str:
    return (date_cls.fromisoformat(day) - timedelta(days=1)).isoformat()


def build_series(forward_graded: list, avg_available: bool) -> list:
    """One point per day with graded bets, preceded by a zero point."""
    if not forward_graded:
        return []
    by_day: dict = {}
    for bet in forward_graded:
        by_day.setdefault(bet.date, []).append(bet)
    days = sorted(by_day)
    out = [SeriesPoint(_day_before(days[0]), 0.0 if avg_available else None,
                       0.0, 0, None)]
    cum_rec = 0.0
    cum_avg = 0.0
    n_clv = 0
    sum_clv = 0.0
    for day in days:
        for bet in by_day[day]:
            cum_rec += recorded_units(bet) or 0.0
            cum_avg += average_units(bet) or 0.0
            if bet.clv_measurable and bet.clv_pts is not None:
                n_clv += 1
                sum_clv += bet.clv_pts
        out.append(SeriesPoint(
            date=day,
            cum_units_average_price=_round(cum_avg) if avg_available else None,
            cum_units_recorded_price=_round(cum_rec),
            bets_settled=len(by_day[day]),
            cum_clv_mean_pts=(_round(sum_clv / n_clv)
                              if n_clv >= vd.CLV_SERIES_MIN_BETS else None)))
    return out


def bet_row(bet: Bet, teams: Optional[tuple]) -> BetRow:
    avg = bet.price_average if bet.price_average is not None else bet.avg_price
    return BetRow(
        hound_id=bet.hound_id, date=bet.date, game=game_text(bet, teams),
        market=bet.market_key, selection=selection_text(bet, teams),
        line=bet.line, price=bet.price, price_average=avg, book=bet.book,
        consensus_fair=_round(bet.consensus_fair), result=bet.result,
        units=_round(recorded_units(bet)) if bet.graded else None,
        clv_pts=bet.clv_pts, who_decided=bet.who_decided, reason=bet.reason,
        segment=bet.segment, verified=bet.verified)


def summarize(defn: dict, bets: list, teams_of: dict, as_of: Optional[str]) -> HoundData:
    forward = [b for b in bets if b.segment == "forward"]
    replay = [b for b in bets if b.segment == "replay"]
    fgraded = sorted((b for b in forward if b.graded),
                     key=lambda b: (b.date, b.decision_utc or ""))

    def tally(rows, cls):
        rec = cls()
        for b in rows:
            rec.bets += 1
            if b.result == "win":
                rec.wins += 1
            elif b.result == "loss":
                rec.losses += 1
            elif b.result == "push":
                rec.pushes += 1
            elif b.result == "void":
                rec.voids += 1
            rec.units_recorded_price += recorded_units(b) or 0.0
        rec.units_recorded_price = round(rec.units_recorded_price, 4)
        return rec

    record = tally(fgraded, Record)
    priced = [b for b in fgraded if b.result not in ("push", "void")]
    with_avg = [b for b in priced if average_units(b) is not None]
    avg_available = bool(priced) and len(with_avg) / len(priced) >= vd.AVERAGE_PRICE_COVERAGE
    if avg_available:
        record.units_average_price = round(sum(average_units(b) or 0.0 for b in fgraded), 4)

    points = [(b.date, b.clv_pts) for b in fgraded
              if b.clv_measurable and b.clv_pts is not None]
    static_retired = defn.get("retired")
    if defn.get("card"):
        verdict = vd.not_measured_verdict(defn.get("verdict_sentence") or "")
        clv_block = None
    else:
        verdict = vd.verdict_for(points)
        clv_block = ClvBlock(n=verdict.n, mean_pts=verdict.mean_pts,
                             ci_low=verdict.ci_low, ci_high=verdict.ci_high) if verdict.n else None

    series = build_series(fgraded, avg_available)

    retired = None
    if static_retired:
        retired = RetiredBlock(date=static_retired.get("date"),
                               cause=static_retired.get("cause") or "retired")
    elif defn.get("kind") != "user" or defn.get("auto_retire"):
        rule_days = [(p.date, p.cum_units_average_price if avg_available
                      else p.cum_units_recorded_price) for p in series[1:]]
        found = vd.find_retirement(rule_days, points)
        if found:
            retired = RetiredBlock(date=found[0], cause=found[1])

    stamps = [b.decision_utc or b.date for b in forward if (b.decision_utc or b.date)]
    last_day = max((str(s)[:10] for s in stamps), default=None)
    status = vd.status_for(last_day, as_of, retired is not None)

    checkable = [b for b in priced if b.checkable]
    verified_n = sum(1 for b in checkable if b.verified)
    checkable_share = (len(checkable) / len(priced)) if priced else None
    verified_share = (verified_n / len(checkable)) if checkable else None
    verified = bool(
        checkable_share is not None and verified_share is not None
        and checkable_share >= vd.CHECKABLE_SHARE_OF_BETS
        and verified_share >= vd.VERIFIED_SHARE_OF_CHECKABLE)

    spark_src = [(p.cum_units_average_price if avg_available
                  else p.cum_units_recorded_price) for p in series]
    summary = HoundSummary(
        id=defn["id"], name=defn["name"], tagline=defn["tagline"],
        kind=defn["kind"], category=defn["category"], style=defn["style"],
        owner_display=defn.get("owner_display"), sports=defn["sports"],
        markets=defn["markets"], rule_text=defn["rule_text"], status=status,
        retired=retired, record=record, clv=clv_block,
        verdict=VerdictBlock(label=verdict.label, sentence=verdict.sentence,
                             units_note=vd.units_note(record.bets)),
        first_bet_utc=min(stamps, default=None), last_bet_utc=max(stamps, default=None),
        verified=verified, verified_share=_round(verified_share),
        checkable_share=_round(checkable_share),
        replay=(tally([b for b in replay if b.graded], ReplayBlock)
                if replay else None),
        spark=[_round(x, 3) for x in spark_src[-SPARK_POINTS:]],
        source=defn.get("source", ""))
    rows = sorted(bets, key=lambda b: (b.decision_utc or b.date or "", b.date),
                  reverse=True)
    return HoundData(
        summary=summary, series=series,
        bets=[bet_row(b, teams_of.get(b.event_id)) for b in rows],
        clv_points=points)


# ---- the whole book -----------------------------------------------------------------------------

def _stream(defs_by_id: dict, all_bets: dict, teams_of: dict, refusals: list) -> list:
    items = []
    for hid, bets in all_bets.items():
        name = defs_by_id[hid]["name"]
        for b in bets:
            if defs_by_id[hid].get("card") or b.segment != "forward":
                continue        # the paused card is history; replay is not "live"
            row = bet_row(b, teams_of.get(b.event_id))
            items.append(StreamItem(
                **{k: getattr(row, k) for k in row.__dataclass_fields__},
                hound_name=name, verdict="play", refused=False,
                decided_utc=b.decision_utc or b.date))
    for r in refusals:
        d = defs_by_id.get(r.hound_id)
        if d is None:
            continue
        teams = teams_of.get(r.event_id)
        items.append(StreamItem(
            hound_id=r.hound_id, date=r.date,
            game=" at ".join(teams) if teams and all(teams) else "",
            market=r.market_key, selection="(no bet)", line=r.line,
            who_decided="code", reason=r.reason, segment="forward",
            hound_name=d["name"], verdict=r.verdict, refused=True,
            decided_utc=r.decided_utc))
    items.sort(key=lambda i: (i.decided_utc or "", i.hound_id), reverse=True)
    return items[:ledgers.STREAM_KEEP]


def build(src: Sources) -> HoundBook:
    started = time.time()
    defs = house.definitions(src.house_hounds_cfg, src.house_pack_cfg)
    defs_by_id = {d["id"]: d for d in defs}

    engine_map = house.engine_system_map(defs)
    all_bets: dict = {d["id"]: [] for d in defs}
    bets, refusals = ledgers.engine_bets(src, engine_map)
    for b in bets:
        all_bets[b.hound_id].append(b)

    card_id = house.card_hound_id(defs)
    if card_id:
        all_bets[card_id].extend(ledgers.card_bets(src, card_id))

    for label, path in src.pack_ledgers:
        pbets, ldefs = ledgers.pack_ledger_rows(path)
        for hid, row in ldefs.items():
            if hid in defs_by_id:
                continue
            defs_by_id[hid] = _def_from_ledger(hid, row, label)
            all_bets.setdefault(hid, [])
        for b in pbets:
            if b.hound_id not in defs_by_id:
                defs_by_id[b.hound_id] = _def_from_ledger(b.hound_id, {}, label)
            all_bets.setdefault(b.hound_id, []).append(b)

    scan_bets = [b for hid, rows in all_bets.items()
                 if not defs_by_id[hid].get("card") for b in rows]
    dated = [b.date for b in scan_bets if b.date]
    index, teams_of = ({}, {})
    if scan_bets:
        index, teams_of = boards.scan(scan_bets, src.multibook,
                                      since=min(dated) if dated else None)
    attach_clv(scan_bets, index)

    stamps = [str(b.decision_utc or b.date)[:10] for rows in all_bets.values()
              for b in rows if b.segment == "forward" and (b.decision_utc or b.date)]
    stamps += [r.date for r in refusals if r.date]
    as_of = max(stamps, default=None)

    hounds = {}
    for hid, defn in defs_by_id.items():
        hounds[hid] = summarize(defn, all_bets.get(hid, []), teams_of, as_of)
    return HoundBook(
        hounds=hounds,
        stream=_stream(defs_by_id, all_bets, teams_of, refusals),
        as_of=as_of, built_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        fingerprint=src.fingerprint(), build_seconds=round(time.time() - started, 2))


def _def_from_ledger(hid: str, row: dict, label: str) -> dict:
    kind = row.get("kind_of") or ("user" if label == "user" else "house")
    if row.get("hound_kind") in ("house", "user", "baseline"):
        kind = row["hound_kind"]
    cat = str(row.get("category") or "").lower()
    d = {"id": hid, "name": row.get("name") or hid, "tagline": row.get("tagline") or "",
         "kind": kind,
         "category": cat if cat in ("stats", "history", "market", "math", "esoteric",
                                    "random", "mixed", "baseline") else "mixed",
         "style": row.get("style") or "", "owner_display": row.get("owner_display"),
         "sports": list(row.get("sports") or ["mlb"]),
         "markets": list(row.get("markets") or []),
         "rule_text": row.get("rule_text") or "",
         "system_id": None, "card": False, "retired": None,
         "verdict_sentence": None, "source": f"{label}_ledger"}
    if row.get("retired_by_owner") or str(row.get("status") or "") == "retired":
        d["retired"] = {"date": str(row.get("retired_on") or "")[:10] or None,
                        "cause": "retired by the owner"}
    return d


# ---- cache -----------------------------------------------------------------------------------------

_LOCK = threading.Lock()
_CACHE: dict = {"book": None}


def get_book(src: Optional[Sources] = None) -> HoundBook:
    """The cached book, rebuilt only if an input's size or mtime changed."""
    src = src or Sources.default()
    key = src.fingerprint()
    book = _CACHE["book"]
    if book is not None and book.fingerprint == key:
        return book
    with _LOCK:
        book = _CACHE["book"]
        if book is not None and book.fingerprint == key:
            return book
        book = build(src)
        _CACHE["book"] = book
        return book


def clear_cache() -> None:
    with _LOCK:
        _CACHE["book"] = None


def warm() -> HoundBook:
    """Build the book now (call at process start to keep the first request fast)."""
    return get_book()


# ---- views --------------------------------------------------------------------------------------------

def _order_key(data: HoundData):
    s = data.summary
    return (s.kind == KIND_BASELINE,
            {"running": 0, "benched": 1, "retired": 2}.get(s.status, 3),
            vd.LABEL_RANK.get(s.verdict.label, 9),
            -(s.clv.n if s.clv else 0), s.name)


def leaderboard(book: HoundBook) -> list:
    rows = [d for d in book.hounds.values() if d.summary.status != "retired"]
    rows.sort(key=_order_key)
    return [d.summary for d in rows]


def graveyard(book: HoundBook) -> list:
    rows = [d.summary for d in book.hounds.values() if d.summary.status == "retired"]
    rows.sort(key=lambda s: (s.retired.date or "") if s.retired else "", reverse=True)
    return rows


def summary_without_spark(summary: HoundSummary) -> HoundSummary:
    import copy
    s = copy.copy(summary)
    s.spark = None
    return s
