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

NOTHING HERE WRITES A LEDGER. The side effects are the in-memory cache, reading the ledgers named
in ``Sources``, and ONE small derived file: the last built public payloads (see "the saved copy"
below), so a restart can answer at once instead of "warming up".
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date as date_cls, timedelta
from typing import Optional

from src.core import odds as odds_math
from src.hounds import boards, house, ledgers, verdict as vd
from src.hounds.contract import (
    BetRow, ClvBlock, DEFAULT_PAGE_SIZE, HoundSummary, KIND_BASELINE, Record, ReplayBlock,
    RetiredBlock, SeriesPoint, SPARK_POINTS, STATUS_NOT_STARTED, StreamItem, VerdictBlock,
    WARMING_RETRY_SECONDS, graveyard_payload, leaderboard_payload, paginate, series_payload,
    stream_payload)
from src.hounds.ledgers import Bet, Sources
from src.report import clv

PROVENANCE_PRE = clv.PROVENANCE_PRE_COMMITMENT
logger = logging.getLogger("linehound.hounds")


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
    # Every measurable forward bet's closing-line value with the game it was on:
    # ``(hound_id, event_id, market_key, date, clv_pts)``. The learning loop's scorecard needs to
    # compare the champions with the random controls on THE SAME GAMES (src/hounds/learning/scorecard.py),
    # which the per-hound ``clv_points`` (date, pts) cannot do. A few thousand small tuples.
    clv_bets: list = field(default_factory=list)


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
        segment=bet.segment, verified=bet.verified, start_utc=bet.start_utc, recorded_utc=bet.recorded_utc,
        book_count=bet.book_count)


FORM_DAYS = 7           # "last 7 days" on the race page, counted back from the book's as-of day


def _fair_of(bet: Bet) -> Optional[float]:
    fair = bet.consensus_fair
    return fair if isinstance(fair, (int, float)) and 0 < fair < 1 else None


def _bet_brief(bet: Bet, teams: Optional[tuple], units: Optional[float]) -> dict:
    avg = bet.price_average if bet.price_average is not None else bet.avg_price
    return {"date": bet.date, "game": game_text(bet, teams), "selection": selection_text(bet, teams),
            "price": avg if avg is not None else bet.price, "units": _round(units),
            "market_fair": _round(_fair_of(bet))}


def last10_results(fgraded: list) -> list:
    """The last ten decided results, oldest first, as "W" / "L" / "P" (a push). Void bets are skipped. The
    same graded bets ``record`` counts; a list shorter than ten is simply a young model."""
    mark = {"win": "W", "loss": "L", "push": "P"}
    return [mark[b.result] for b in fgraded if b.result in mark][-10:]


def _decimal_of(american) -> Optional[float]:
    if not isinstance(american, (int, float)) or isinstance(american, bool) or american == 0:
        return None
    return 1.0 + american / 100.0 if american > 0 else 1.0 + 100.0 / abs(american)


def average_price_taken(fgraded: list) -> Optional[int]:
    """The typical price a model took, as an American price: the mean of the decimal prices, converted back.
    The price used is the board-average price when the bet has one, else the price taken. None with no priced bet."""
    decimals = []
    for b in fgraded:
        avg = b.price_average if b.price_average is not None else b.avg_price
        dec = _decimal_of(avg if avg is not None else b.price)
        if dec is not None and dec > 1.0:
            decimals.append(dec)
    if not decimals:
        return None
    mean = sum(decimals) / len(decimals)
    if mean <= 1.0:
        return None
    return int(round((mean - 1.0) * 100)) if mean >= 2.0 else int(round(-100.0 / (mean - 1.0)))


def clv_beat_share(points: list) -> Optional[dict]:
    """Of the bets with a measurable closing-line value, how many beat the close: {"n", "beat", "pct"}.
    ``pct`` is a share in 0..1. None when nothing is measurable. A bet at exactly the close counts as not beating it."""
    values = [v for _, v in points if isinstance(v, (int, float))]
    if not values:
        return None
    beat = sum(1 for v in values if v > 0)
    return {"n": len(values), "beat": beat, "pct": _round(beat / len(values), 4)}


def compute_form(fgraded: list, avg_available: bool, as_of: Optional[str], teams_of: dict) -> Optional[dict]:
    """The scoreboard a bettor reads first: streak, the last seven days, the last settled day, the best bet
    and the worst beat. Forward bets only, the same graded bets ``record`` counts, in the same units
    (the average price when the hound has it, else the recorded price). Derived, never a new measurement;
    None when nothing is graded.

    WORST BEAT is the lost bet the market thought most likely to win (the highest de-vigged fair
    probability on the row), the latest on a tie; with no fair probability on any loss it is the latest loss.
    """
    if not fgraded:
        return None

    def units_of(b: Bet) -> float:
        value = average_units(b) if avg_available else recorded_units(b)
        return value if value is not None else 0.0

    decided = [b for b in fgraded if b.result in ("win", "loss")]
    streak = None
    if decided:
        kind = decided[-1].result
        length = 0
        for b in reversed(decided):
            if b.result != kind:
                break
            length += 1
        streak = {"kind": "W" if kind == "win" else "L", "length": length}

    by_day: dict = {}
    for b in fgraded:
        by_day.setdefault(b.date, []).append(b)
    days = sorted(by_day)
    rows = by_day[days[-1]]
    total = round(sum(units_of(b) for b in rows), 4)
    last_day = {"date": days[-1], "bets": len(rows),
                "wins": sum(1 for b in rows if b.result == "win"),
                "losses": sum(1 for b in rows if b.result == "loss"),
                "units": total,
                "result": "win" if total > 0 else "loss" if total < 0 else "flat"}

    last7 = None
    anchor = str(as_of or days[-1])[:10]
    try:
        floor = (date_cls.fromisoformat(anchor) - timedelta(days=FORM_DAYS - 1)).isoformat()
    except ValueError:
        floor = None
    if floor:
        recent = [b for b in fgraded if floor <= str(b.date)[:10] <= anchor]
        last7 = {"bets": len(recent),
                 "wins": sum(1 for b in recent if b.result == "win"),
                 "losses": sum(1 for b in recent if b.result == "loss"),
                 "units": round(sum(units_of(b) for b in recent), 4)}

    wins = [b for b in decided if b.result == "win"]
    losses = [b for b in decided if b.result == "loss"]
    best_bet = worst_beat = None
    if wins:
        best = max(wins, key=lambda b: (units_of(b), b.date, b.decision_utc or ""))
        best_bet = _bet_brief(best, teams_of.get(best.event_id), units_of(best))
    if losses:
        worst = max(losses, key=lambda b: (_fair_of(b) if _fair_of(b) is not None else -1.0,
                                           b.date, b.decision_utc or ""))
        worst_beat = _bet_brief(worst, teams_of.get(worst.event_id), units_of(worst))
    return {"streak": streak, "last7": last7, "last_day": last_day, "best_bet": best_bet,
            "worst_beat": worst_beat,
            "units_basis": "average_price" if avg_available else "recorded_price",
            "last10": last10_results(fgraded), "avg_price": average_price_taken(fgraded)}


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
    if not bets and retired is None and defn.get("not_started_when_empty"):
        status = STATUS_NOT_STARTED       # the desk before its first publish: nothing has run, nothing has stopped
    elif (not forward and retired is None
            and defn.get("status_hint") in (vd.STATUS_RUNNING, vd.STATUS_BENCHED)):
        # A user hound with no bet yet: the referee's bench rule counts days since the last bet
        # and there is none, so it would read "benched" the minute it is created. The store
        # knows it is running.
        status = defn["status_hint"]

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
        spark_basis="average_price" if avg_available else "recorded_price",
        source=defn.get("source", ""),
        persona=defn.get("persona") if isinstance(defn.get("persona"), dict) else None,
        form=compute_form(fgraded, avg_available, as_of, teams_of),
        open_bets=sum(1 for b in forward if not b.graded))
    if summary.form is not None:
        summary.form["clv_beat"] = clv_beat_share(points)
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
    defs = house.definitions(src.house_hounds_cfg, src.house_pack_cfg, src.house_desk_cfg)
    defs_by_id = {d["id"]: d for d in defs}

    engine_map = house.engine_system_map(defs)
    all_bets: dict = {d["id"]: [] for d in defs}
    bets, refusals = ledgers.engine_bets(src, engine_map)
    for b in bets:
        all_bets[b.hound_id].append(b)

    card_id = house.card_hound_id(defs)
    if card_id:
        all_bets[card_id].extend(ledgers.card_bets(src, card_id))

    # User hounds: names and rules from the app database, bets from their ledger below.
    if src.user_hounds is not None:
        try:
            user_defs = src.user_hounds()
        except Exception:  # noqa: BLE001 -- an unreadable app db must not take the house hounds down
            logger.warning("hounds: user hound definitions unreadable", exc_info=True)
            user_defs = []
        for d in user_defs:
            if d["id"] not in defs_by_id:
                defs_by_id[d["id"]] = d
                all_bets[d["id"]] = []

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

    # The learning loop (docs/PREREG_LEARNING_LOOP.md section 8): a pack hound promoted from a challenger
    # has bets stamped with their version. The current version keeps the hound's id; each earlier version
    # becomes its own retired entry with its own record. No promotion on record: nothing changes.
    try:
        from src.hounds.learning import champions, lineage
        lineage.split_versions(
            defs_by_id, all_bets,
            [champions.events_path_beside(p) for label, p in src.pack_ledgers if label == "house"])
    except Exception:  # noqa: BLE001 -- a broken registry must not take the public race down
        logger.warning("hounds: could not split pack hounds by version", exc_info=True)

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
    clv_bets = [(hid, b.event_id, b.market_key, b.date, b.clv_pts)
                for hid, rows in all_bets.items() if not defs_by_id[hid].get("card")
                for b in rows if b.segment == "forward" and b.clv_measurable
                and b.clv_pts is not None and b.event_id]
    return HoundBook(
        hounds=hounds,
        stream=_stream(defs_by_id, all_bets, teams_of, refusals),
        as_of=as_of, built_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        fingerprint=src.fingerprint(), build_seconds=round(time.time() - started, 2),
        clv_bets=clv_bets)


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
    """Forget the in-memory book AND the saved copy (a script or a test; no request path calls this).
    The saved copy is a derived file, so dropping it loses nothing a rebuild does not restore; keeping
    it would let one test's world answer the next test's cold start."""
    with _LOCK:
        _CACHE["book"] = None
    _BG["error"] = None
    _BG["failed_at"] = 0.0
    _SNAP["written_built"] = None
    _SNAP["refused_logged"] = False
    _SERIES_REQUESTS.clear()
    path = snapshot_path()
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def warm() -> HoundBook:
    """Build the book now, on the calling thread (a script or a test; a request never calls this)."""
    return get_book()


# ---- the request path: never wait for a build ---------------------------------------------------------
#
# WHY (2026-10-18). A cold build streams ~1,000,000 odds rows (5 to 10 s here, longer on the 1 GB
# machine). Doing that on the first visitor's request is the "spinning page" this app has already paid
# for once (api/warmup.py). Adding it to startup instead would put a multi-second, memory-heavy pass
# next to the cache warm-up on a machine that was OOM-killed for exactly that (2026-10-01). So: the
# request path asks ``get_book_nowait``, which answers from memory in microseconds. A cold start gets
# ``(None, "warming")`` and ONE background build is started; a book that has gone stale (a ledger
# changed) is served as it is while ONE rebuild runs. The build takes the process-wide build gate
# (src.appstate.freshness), so it is serialised with every other cache build and can never be the
# second thing running.

BUILD_RETRY_AFTER_FAILURE_S = 30.0
STATE_FRESH, STATE_STALE, STATE_WARMING, STATE_FAILED = "fresh", "stale", "warming", "failed"

_BG_LOCK = threading.Lock()
_BG: dict = {"thread": None, "error": None, "failed_at": 0.0, "builds": 0}


def peek_book() -> Optional[HoundBook]:
    """The cached book, fresh or stale, or None. Never builds, never touches a ledger."""
    return _CACHE["book"]


def _background_build(src: Sources) -> None:
    from src.appstate import freshness
    try:
        with freshness._gated_build():
            book = get_book(src)
        _BG["error"] = None
        write_snapshot(book)
    except Exception as exc:  # noqa: BLE001 -- recorded; the next request after the retry delay tries again
        logger.exception("hounds: background book build failed")
        _BG["error"] = repr(exc)
        _BG["failed_at"] = time.time()
    finally:
        _BG["builds"] += 1


def refresh_async(src: Optional[Sources] = None) -> bool:
    """Start ONE background build unless one is already running (or one failed moments ago).
    True when a thread was started."""
    src = src or Sources.default()
    with _BG_LOCK:
        thread = _BG["thread"]
        if thread is not None and thread.is_alive():
            return False
        if time.time() - _BG["failed_at"] < BUILD_RETRY_AFTER_FAILURE_S and _BG["error"]:
            return False
        thread = threading.Thread(target=_background_build, args=(src,), daemon=True,
                                  name="hounds-book-build")
        _BG["thread"] = thread
        thread.start()
        return True


def building() -> bool:
    thread = _BG["thread"]
    return thread is not None and thread.is_alive()


def get_book_nowait(src: Optional[Sources] = None) -> tuple:
    """``(book | None, state)`` without ever waiting for a build.

    fresh    the cached book matches the inputs.
    stale    a book exists but an input changed; it is returned as it is and one rebuild is running.
    warming  nothing is cached yet; one build is running (or was just started). ``book`` is None.
    failed   nothing is cached and the last build raised; retried after BUILD_RETRY_AFTER_FAILURE_S.
    """
    src = src or Sources.default()
    book = _CACHE["book"]
    if book is not None and book.fingerprint == src.fingerprint():
        return book, STATE_FRESH
    refresh_async(src)
    if book is not None:
        return book, STATE_STALE
    if _BG["error"] and not building():
        return None, STATE_FAILED
    return None, STATE_WARMING


# ---- the saved copy: what a restart answers with while the first build runs ------------------------------
#
# WHY (2026-10-18). The app redeploys hourly and every restart empties the in-memory book, so the first
# GET /hounds after one answered ``warming_up`` for the 5 to 10 s the build takes. A once-a-day caller
# (the Zapier digest) that lands in that window gets an empty race and skips the day. So every successful
# background build also writes the PUBLIC payloads (leaderboard, graveyard, page 1 of the stream, the
# series for the ids people ask for) to ONE small JSON file on the persistent data volume, next to the app
# db (``users.db_path().parent``, never inside the repo: a redeploy replaces the repo, not the volume).
# A cold start serves that file at once, flagged ``stale: true`` with ``as_of`` = when it was BUILT (the
# data's own as-of day rides along as ``data_as_of``), while the ordinary single background rebuild,
# serialised on the build gate, replaces it. No file, a file older than 24 h, or a file that does not
# parse: the endpoint answers ``warming_up`` exactly as before. A day-old race is better than an empty
# one; past a day, saying nothing is the honest answer.
#
# The file holds only what the public routes already return (the envelope even carries the not-advice
# line). No user id or token enters it: a user hound appears exactly as the public route shows it (id,
# name, ``owner_display``, rule text), and ``HoundSummary`` has no field that holds anything private.

SNAPSHOT_FILENAME = "hounds_public_cache.json"
SNAPSHOT_VERSION = 1
SNAPSHOT_MAX_AGE_S = 24 * 3600
SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024
#: A saved copy stamped further in the future than this is a bad clock, not a fresh build.
SNAPSHOT_CLOCK_SKEW_S = 300
SNAPSHOT_SERIES_IDS = 12            # the series route's own cap (api.hounds.MAX_SERIES_IDS)
ENV_SNAPSHOT_PATH = "HOUNDS_SNAPSHOT_PATH"
_SNAP_KINDS = ("leaderboard", "graveyard", "stream", "series")

_SNAP: dict = {"written_built": None, "refused_logged": False}
_SERIES_REQUESTS: dict = {}          # hound id -> times asked for, this process only


def snapshot_path():
    """Where the saved copy lives: ``$HOUNDS_SNAPSHOT_PATH`` if set, else beside the app db."""
    override = (os.environ.get(ENV_SNAPSHOT_PATH) or "").strip()
    if override:
        from pathlib import Path
        return Path(override).expanduser()
    from src.appstate import users
    return users.db_path().parent / SNAPSHOT_FILENAME


def note_series_request(ids: list) -> None:
    """Count the hound ids the series route was asked for, so the saved copy keeps the ones in demand."""
    for hid in ids:
        _SERIES_REQUESTS[hid] = _SERIES_REQUESTS.get(hid, 0) + 1


def _snapshot_series_ids(book: HoundBook) -> list:
    asked = sorted((i for i in _SERIES_REQUESTS if i in book.hounds),
                   key=lambda i: (-_SERIES_REQUESTS[i], i))
    order = [s.id for s in leaderboard(book)]
    out: list = []
    for hid in asked + order:
        if hid not in out:
            out.append(hid)
    return out[:SNAPSHOT_SERIES_IDS]


def build_snapshot(book: HoundBook) -> dict:
    ids = _snapshot_series_ids(book)
    return {
        "version": SNAPSHOT_VERSION,
        "built_utc": book.built_utc,
        "leaderboard": leaderboard_payload(leaderboard(book), book.as_of),
        "graveyard": graveyard_payload(graveyard(book), book.as_of),
        "stream": stream_payload(paginate(book.stream, 1, DEFAULT_PAGE_SIZE), book.as_of),
        "series": series_payload({i: book.hounds[i].series for i in ids}, book.as_of),
    }


def write_snapshot(book: HoundBook) -> bool:
    """Save the public payloads of ``book`` atomically (temp file in the same directory, then
    ``os.replace``, so a reader never sees half a file). Never raises: a failure here must not turn a
    good build into a failed one. Refuses, and says so once, if the file would pass 2 MB."""
    if _SNAP["written_built"] == book.built_utc:
        return False
    try:
        data = json.dumps(build_snapshot(book), separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        logger.exception("hounds: the saved copy could not be serialised; none written")
        return False
    if len(data) > SNAPSHOT_MAX_BYTES:
        if not _SNAP["refused_logged"]:
            _SNAP["refused_logged"] = True
            logger.warning("hounds: the saved copy would be %d bytes (cap %d); not written",
                           len(data), SNAPSHOT_MAX_BYTES)
        return False
    path = snapshot_path()
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError:
        logger.exception("hounds: the saved copy could not be written")
        return False
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    _SNAP["written_built"] = book.built_utc
    return True


def _parse_utc(text) -> Optional[float]:
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def load_snapshot(now: Optional[float] = None) -> Optional[dict]:
    """The saved copy if it exists, parses, has every part and is under 24 h old; else None."""
    path = snapshot_path()
    try:
        if path.stat().st_size > SNAPSHOT_MAX_BYTES:
            return None
        snap = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(snap, dict) or snap.get("version") != SNAPSHOT_VERSION:
        return None
    if not all(isinstance(snap.get(k), dict) for k in _SNAP_KINDS):
        return None
    built = _parse_utc(snap.get("built_utc"))
    if built is None:
        return None
    age = (time.time() if now is None else now) - built
    if age > SNAPSHOT_MAX_AGE_S or age < -SNAPSHOT_CLOCK_SKEW_S:
        return None
    return snap


def saved_payload(kind: str, ids: Optional[list] = None, page: int = 1,
                  page_size: int = DEFAULT_PAGE_SIZE) -> Optional[dict]:
    """The saved copy of one public route's answer, marked ``stale: true``, or None when there is no
    usable copy or it cannot answer THIS request (a stream page past 1, a series id it did not keep:
    a partial answer would read as a complete one, so those fall back to ``warming_up``)."""
    if kind == "stream" and (page != 1 or page_size != DEFAULT_PAGE_SIZE):
        return None
    snap = load_snapshot()
    if snap is None:
        return None
    payload = snap[kind]
    if kind == "series":
        have = payload.get("series")
        if not isinstance(have, dict) or any(i not in have for i in (ids or [])):
            return None
        payload = {**payload, "series": {i: have[i] for i in (ids or [])}}
    payload = dict(payload)
    payload["data_as_of"] = payload.get("as_of")
    payload["as_of"] = snap["built_utc"]
    payload["stale"] = True
    payload["retry_after_seconds"] = WARMING_RETRY_SECONDS
    return payload


# ---- views --------------------------------------------------------------------------------------------

def _order_key(data: HoundData):
    s = data.summary
    return (s.kind == KIND_BASELINE,
            {"running": 0, "benched": 1, "not_started": 2, "retired": 3}.get(s.status, 4),
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
