"""Turn every source of hound bets into one normalised ``Bet`` shape.

Three kinds of source, all READ-ONLY (no ledger is ever written or edited here):

  engine   the 45 engine "systems" that already paper-trade every day:
           graded results from ``data/paper_accounts/<system>.jsonl`` (one
           append-only account ledger per system), the wager each came from
           (``evidence/paper_wagers_v2.jsonl``) and the frozen decision behind
           it (``evidence/decisions_v2.jsonl``, hot file + cold archive).
  card     the paused public MLB value card ("the Old Dog"), read through the
           card ledger's own read functions ``history_v2``.
  pack     any hash-chained ledger in the row shape the pack and user workers
           write (``evidence/hounds_house_v1.jsonl``,
           ``evidence/hounds_user_v1.jsonl``): bet rows carrying
           ``hound_id, date, game_id|event_id, sport, market, selection, line,
           price_average, price_best, book_count, lock_utc, start_utc, reason,
           who_decided, segment`` and graded rows carrying ``result`` and
           ``units``. A bet row and its graded row are merged by ``bet_id``
           (or by hound + event + market + selection + line + segment); one row
           holding both is fine too.

MEMORY. The decision ledger is ~39,000 rows of ~3 KB across the archive, so it
is streamed line by line, filtered by a compiled pattern on the system ids,
and only trimmed copies of the rows that matter are kept. Nothing here ever
builds a list of the whole store (production has 1 GB; the 2026-10-01 incident
was whole-store reads).

SEALED WINDOW. Outcomes dated 2026-01-01..2026-08-27 are never read: a graded
row or decision dated inside it is dropped before any other field is looked at
(``FIRST_OPEN_DAY``). The paper ledgers begin 2026-09-02 anyway.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.paths import data_path, evidence_path, repo_root

FIRST_OPEN_DAY = "2026-08-28"   # sealed window ends 2026-08-27; never read before this

RESULTS = ("win", "loss", "push", "void")
STREAM_KEEP = 3000              # newest stream items kept in memory
THESIS_CHARS = 420              # the reason shown on a bet row (first sentences)

MARKET_ALIASES = {
    "moneyline": "h2h", "ml": "h2h", "h2h": "h2h",
    "run_line": "spreads", "runline": "spreads", "spread": "spreads",
    "spreads": "spreads", "total": "totals", "totals": "totals",
    "f5": "h2h_1st_5_innings", "f5_moneyline": "h2h_1st_5_innings",
    "h2h_1st_5_innings": "h2h_1st_5_innings",
}
SIDES = ("home", "away", "over", "under")

PROVENANCE_TO_WHO = {"model_derived": "model"}

# A pack hound that decides by a seeded draw (coin, dart) says "random". The
# contract's closed set is code | model | rule (src.hounds.contract.WHO_DECIDED),
# and a seeded draw is made by code, so that is the word the page shows. Found
# 2026-10-18 reading evidence/hounds_house_v1.jsonl: the reader silently
# defaulted every random hound to "rule".
WHO_ALIASES = {"random": "code", "seeded": "code", "coin": "code"}


@dataclass
class Bet:
    hound_id: str
    segment: str = "forward"
    date: str = ""                  # the slate / decision day (UTC)
    decision_utc: Optional[str] = None
    start_utc: Optional[str] = None
    bet_id: str = ""
    event_id: Optional[str] = None
    sport: str = "mlb"
    market_key: str = ""
    side: Optional[str] = None
    line: Optional[str] = None
    price: Optional[int] = None             # the price the hound took
    price_average: Optional[int] = None     # board average, if the source gave it
    book: Optional[str] = None
    book_count: Optional[int] = None
    consensus_fair: Optional[float] = None
    result: Optional[str] = None            # win|loss|push|void, None = ungraded
    units: Optional[float] = None           # source-given units, if any
    who_decided: str = "rule"
    reason: str = ""
    selection_text: str = ""
    game_text: str = ""
    verdict: str = "play"
    decision: Optional[dict] = None         # trimmed engine decision (for CLV)
    # filled by src.hounds.boards:
    avg_price: Optional[int] = None
    avg_books: int = 0
    verified: Optional[bool] = None
    checkable: bool = False
    clv_pts: Optional[float] = None
    clv_measurable: bool = False

    @property
    def graded(self) -> bool:
        return self.result in RESULTS


@dataclass
class StreamRow:
    """A refusal (or any non-bet decision) for the stream."""
    hound_id: str
    date: str
    decided_utc: str
    event_id: Optional[str]
    market_key: str
    verdict: str
    reason: str
    side: Optional[str] = None
    line: Optional[str] = None


@dataclass
class Sources:
    """Where everything is read from. Tests point these at a fixture."""
    decisions: Path
    wagers: Path
    accounts_dir: Path
    multibook: Path
    card_v2: Optional[Path]      # evidence/cards_v2.jsonl
    house_hounds_cfg: Path
    house_pack_cfg: Path
    pack_ledgers: tuple = ()       # (("house", path), ("user", path)) -- kind, path
    # User hounds' names, rules and owners live in the app database, not in a ledger.
    # ``user_hounds()`` -> definitions (src.hounds.user_defs.definitions); ``user_stamp()`` ->
    # a cheap tuple folded into the cache key. Both None for a world with no app database.
    user_hounds: Optional[Callable[[], list]] = None
    user_stamp: Optional[Callable[[], tuple]] = None

    @staticmethod
    def default() -> "Sources":
        root = repo_root()
        from src.hounds import user_defs, user_engine
        from src.pipeline import snapshots
        return Sources(
            decisions=evidence_path("decisions_v2.jsonl"),
            wagers=evidence_path("paper_wagers_v2.jsonl"),
            accounts_dir=data_path("paper_accounts"),
            multibook=Path(snapshots.DEFAULT_MULTIBOOK_PATH),
            card_v2=evidence_path("cards_v2.jsonl"),
            house_hounds_cfg=root / "config" / "house_hounds.json",
            house_pack_cfg=root / "config" / "house_pack.json",
            pack_ledgers=(
                ("house", evidence_path("hounds_house_v1.jsonl")),
                # The user ledger sits beside the app database (user_engine.ledger_path),
                # outside the repository: the engine that writes it runs in the API process.
                ("user", Path(user_engine.ledger_path())),
            ),
            user_hounds=user_defs.definitions, user_stamp=user_defs.stamp,
        )

    def fingerprint(self) -> tuple:
        """Size + mtime of every input, archives included: the cache key.

        A handful of ``stat`` calls, never a read. A store whose archive gains
        a segment or whose hot file grows changes the key; nothing else does.
        """
        from src.pipeline import store_archive
        paths = [self.decisions, self.wagers, self.multibook,
                 self.house_hounds_cfg, self.house_pack_cfg]
        paths += [p for _, p in self.pack_ledgers]
        if self.card_v2 is not None:
            paths.append(self.card_v2)
        for store in (self.decisions, self.wagers, self.multibook):
            try:
                paths += store_archive.segments(store)
            except Exception:  # noqa: BLE001
                pass
        if self.accounts_dir.is_dir():
            paths += sorted(self.accounts_dir.glob("*.jsonl"))
        out = []
        for p in paths:
            try:
                st = os.stat(p)
                out.append((str(p), st.st_size, st.st_mtime_ns))
            except OSError:
                out.append((str(p), None, None))
        if self.user_stamp is not None:
            out.append(self.user_stamp())
        return tuple(out)


# ---- small helpers -------------------------------------------------------------

def jsonl_rows(path) -> Iterable[dict]:
    """Rows of a plain JSONL file; a missing file or a bad line is skipped."""
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def logical_rows(path, pattern: Optional["re.Pattern"] = None) -> Iterable[dict]:
    """Rows of a rotated store (archive segments then hot file), one at a time.

    ``pattern`` is a cheap text prefilter applied BEFORE json parsing; it may
    only ever over-match.
    """
    from src.pipeline import store_archive
    if not store_archive.exists(path):
        return
    for line in store_archive.iter_lines(path):
        line = line.strip()
        if not line:
            continue
        if pattern is not None and not pattern.search(line):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def safe_name(system_id: str) -> str:
    """Matches ``src.accounts.paper.default_ledger_path`` file naming."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in system_id)


def _day(value) -> str:
    return str(value or "")[:10]


def _sealed(day: str) -> bool:
    return bool(day) and day < FIRST_OPEN_DAY


def _int_or_none(value) -> Optional[int]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _float_or_none(value) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def trim_thesis(text) -> str:
    text = str(text or "").strip()
    if len(text) <= THESIS_CHARS:
        return text
    cut = text[:THESIS_CHARS]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:stop + 1] if stop > 120 else cut.rstrip()) + " ..."


def who_decided_from(provenance) -> str:
    """p_model_provenance -> who decided (task spec): model_derived is the
    model; market_derived / placeholder / none are a written rule."""
    return PROVENANCE_TO_WHO.get(provenance, "rule")


# ---- engine systems -------------------------------------------------------------

_DECISION_KEEP = ("event_id", "system_id", "market_key", "selection_id", "line",
                  "decision_utc", "verdict", "price_american", "book",
                  "consensus_fair", "p_model_provenance", "record_provenance",
                  "refusal_reason", "books_at_decision", "friction",
                  "system_class", "stake_units")


def _trim_decision(row: dict) -> dict:
    out = {k: row.get(k) for k in _DECISION_KEEP}
    out["thesis"] = trim_thesis(row.get("thesis"))
    return out


def read_account(accounts_dir: Path, system_id: str) -> list:
    """Graded settlements for one system (its own append-only account ledger)."""
    path = Path(accounts_dir) / f"{safe_name(system_id)}.jsonl"
    rows = []
    for row in jsonl_rows(path):
        if "bet_id" not in row or row.get("outcome") not in RESULTS:
            continue
        if _sealed(_day(row.get("day"))):
            continue
        rows.append(row)
    return rows


def engine_bets(src: Sources, system_to_hound: dict) -> tuple:
    """``(bets, stream_rows)`` for the engine systems named in ``system_to_hound``.

    Every paper wager of those systems becomes a Bet (graded when its account
    ledger holds a settlement for the same ``bet_id``); refusals become
    ``StreamRow`` (deduplicated: the newest per system, game and market).
    """
    ids = sorted(system_to_hound)
    if not ids:
        return [], []
    graded = {}
    for sid in ids:
        for row in read_account(src.accounts_dir, sid):
            graded[row["bet_id"]] = row

    pattern = re.compile('"system_id": ?"(?:%s)"' % "|".join(re.escape(i) for i in ids))
    wagers = {}
    for row in logical_rows(src.wagers, pattern):
        if row.get("system_id") not in system_to_hound:
            continue
        if _sealed(_day(row.get("date"))):
            continue
        wagers[row.get("bet_id")] = row

    wanted = {}
    for bet_id, w in wagers.items():
        wanted[(w.get("event_id"), w.get("system_id"), w.get("market_key"),
                w.get("selection_id"), w.get("decision_utc"))] = bet_id
    decisions_by_bet = {}
    refusals = {}
    for row in logical_rows(src.decisions, pattern):
        sid = row.get("system_id")
        if sid not in system_to_hound:
            continue
        day = _day(row.get("decision_utc"))
        if _sealed(day) or day < FIRST_OPEN_DAY:
            continue
        key = (row.get("event_id"), sid, row.get("market_key"),
               row.get("selection_id"), row.get("decision_utc"))
        if key in wanted:
            decisions_by_bet[wanted[key]] = _trim_decision(row)
        verdict = row.get("verdict")
        if verdict and verdict != "play":
            rkey = (sid, row.get("event_id"), row.get("market_key"))
            prev = refusals.get(rkey)
            if prev is None or (row.get("decision_utc") or "") > prev.decided_utc:
                refusals[rkey] = StreamRow(
                    hound_id=system_to_hound[sid], date=day,
                    decided_utc=row.get("decision_utc") or "",
                    event_id=row.get("event_id"),
                    market_key=row.get("market_key") or "", verdict=verdict,
                    reason=_refusal_sentence(row), line=row.get("line"))

    bets = []
    for bet_id, w in wagers.items():
        sid = w.get("system_id")
        g = graded.get(bet_id)
        dec = decisions_by_bet.get(bet_id)
        provenance = (dec or {}).get("p_model_provenance")
        bet = Bet(
            hound_id=system_to_hound[sid], segment="forward",
            date=_day(w.get("date")), decision_utc=w.get("decision_utc"),
            bet_id=str(bet_id), event_id=w.get("event_id"), sport="mlb",
            market_key=w.get("market_key") or "", side=w.get("side"),
            line=w.get("line"), price=_int_or_none(w.get("price_american")),
            book=(dec or {}).get("book"),
            book_count=(dec or {}).get("books_at_decision"),
            consensus_fair=(dec or {}).get("consensus_fair"),
            who_decided=who_decided_from(provenance),
            reason=(dec or {}).get("thesis", ""), decision=dec,
        )
        # A decision stamped as written after (or without regard to) first
        # pitch is not a forward record, whatever ledger it sits in.
        if dec is not None and dec.get("record_provenance") not in (
                None, "live_pre_commencement"):
            bet.segment = "replay"
        if g is not None:
            bet.result = g.get("outcome")
            bet.units = _float_or_none(g.get("profit_units"))
            bet.date = _day(g.get("day")) or bet.date
        bets.append(bet)
    return bets, list(refusals.values())


def _refusal_sentence(row: dict) -> str:
    verdict = str(row.get("verdict") or "")
    why = row.get("refusal_reason")
    base = {
        "refused_thin": "Refused: too few books were quoting this market to trust a price.",
        "refused_stale": "Refused: the quotes on the board were too old to act on.",
    }.get(verdict, f"Refused ({verdict.replace('refused_', '')}).")
    return f"{base} {why}".strip() if why else base


# ---- the paused public card (the Old Dog) ------------------------------------------

def card_bets(src: Sources, hound_id: str) -> list:
    """The graded entries of the V2 public card, via its own read function.

    Picks and fills are both counted (the public record counts both). A
    withdrawn entry is not a bet. An unresolved entry is not graded. The
    ledger is read once through ``card_ledger.history_v2`` and never written.
    """
    try:
        from src.appstate import card_ledger
        history = card_ledger.history_v2(
            path=str(src.card_v2) if src.card_v2 else None, limit=None)
    except Exception:  # noqa: BLE001
        return []
    out = []
    mapping = {"WIN": "win", "LOSS": "loss", "PUSH": "push", "VOID": "void"}
    for day in history.get("days") or ():
        date = _day(day.get("date"))
        if not date or _sealed(date):
            continue
        for entry in day.get("graded") or ():
            if entry.get("withdrawn"):
                continue
            result = mapping.get(str(entry.get("result") or "").upper())
            if result is None:
                continue
            kind = entry.get("kind")
            player = entry.get("player")
            side = entry.get("side")
            if kind == "prop" and player:
                market = entry.get("market") or "prop"
                selection = f"{player} {side or ''} {entry.get('line') if entry.get('line') is not None else ''} {market}".replace("  ", " ").strip()
                game = ""
            else:
                market = entry.get("market") or "h2h"
                selection = str(entry.get("bet") or entry.get("team_name")
                                or entry.get("team") or market)
                game = " at ".join(x for x in (entry.get("away_team"),
                                               entry.get("home_team")) if x)
            out.append(Bet(
                hound_id=hound_id, segment="forward", date=date,
                decision_utc=entry.get("locked_at"),
                start_utc=entry.get("first_pitch_utc"),
                bet_id=f"card:{date}:{len(out)}", sport="mlb",
                market_key=str(market), side=str(side) if side else None,
                line=None if entry.get("line") is None else str(entry.get("line")),
                price=_int_or_none(entry.get("price")), book=entry.get("book"),
                consensus_fair=_float_or_none(entry.get("market_probability")),
                result=result, units=_float_or_none(entry.get("profit_units")),
                who_decided="model",
                reason=str(entry.get("why") or entry.get("reason") or
                           "A pick or fill on the public MLB value card."),
                selection_text=selection, game_text=game))
    return out


# ---- pack / user ledgers ---------------------------------------------------------------

def _market_of(row: dict) -> str:
    raw = str(row.get("market") or row.get("market_key") or "").strip().lower()
    return MARKET_ALIASES.get(raw, raw)


def _side_of(row: dict) -> Optional[str]:
    side = str(row.get("side") or "").strip().lower()
    if side in SIDES:
        return side
    selection = str(row.get("selection") or "").strip().lower()
    if selection in SIDES:
        return selection
    first = selection.split(" ")[0] if selection else ""
    return first if first in ("over", "under") else None


def pack_ledger_rows(path) -> tuple:
    """``(bets, hound_defs)`` from one hash-chained pack/user ledger."""
    return pack_rows(jsonl_rows(path))


def pack_rows(rows: Iterable) -> tuple:
    """``(bets, hound_defs)`` from ledger rows already in hand (the file reader above, or a test)."""
    merged: dict = {}
    defs: dict = {}
    by_row_hash: dict = {}      # a bet row's own row_hash -> its merge key
    for row in rows:
        kind = row.get("kind")
        if kind in ("hound", "hound_def", "hound_meta"):
            hid = row.get("hound_id") or row.get("id")
            if hid:
                defs[str(hid)] = row
            continue
        hid = row.get("hound_id")
        if not hid:
            continue
        # ``slate_date`` is the user engine's original name for ``date`` (rows written before it
        # also wrote the contract's names stay readable).
        date = _day(row.get("date") or row.get("slate_date") or row.get("lock_utc"))
        if _sealed(date):
            continue
        event = row.get("event_id") or row.get("game_id")
        market = _market_of(row)
        # How a graded row finds its bet: an explicit bet_id; else the hash of
        # the bet row it grades (the house pack writes ``bet_row_hash``, and
        # its graded rows carry no ``line``, so the fallback key below never
        # matches a spread or a total and the bet showed up twice, once
        # ungraded); else the fallback key. Found 2026-10-18 on the real pack
        # ledger: 126 "bets" for a hound that made 63.
        key = row.get("bet_id")
        if not key and row.get("bet_row_hash") in by_row_hash:
            key = by_row_hash[row["bet_row_hash"]]
        if not key:
            key = "|".join(str(x) for x in (
                hid, event, market, row.get("selection") or row.get("side"),
                row.get("line"), row.get("segment") or "forward"))
        if row.get("row_hash") and row.get("result") is None:
            by_row_hash[row["row_hash"]] = key
        bet = merged.get(key)
        if bet is None:
            bet = Bet(hound_id=str(hid), bet_id=str(key))
            merged[key] = bet
        bet.date = date or bet.date
        bet.event_id = str(event) if event is not None else bet.event_id
        bet.sport = str(row.get("sport") or bet.sport or "mlb").lower()
        bet.market_key = market or bet.market_key
        side = _side_of(row)
        bet.side = side or bet.side
        text = str(row.get("selection") or "").strip()
        if text and text.lower() not in SIDES:
            bet.selection_text = text      # a bare side is rebuilt from team names
        if row.get("line") is not None:
            bet.line = str(row["line"])
        # The two prices. ``price_best`` is the price recorded at lock (units_recorded_price);
        # ``price_average`` the board average (units_average_price). The user engine's original
        # names for them were ``best_price`` and ``price`` (= the average); read those too, so a
        # ledger row from before the engine wrote the contract's names means the same thing.
        best = _int_or_none(row.get("price_best"))
        if best is None:
            best = _int_or_none(row.get("best_price"))
        avg = _int_or_none(row.get("price_average"))
        if avg is None and row.get("best_price") is not None:
            avg = _int_or_none(row.get("price"))
        legacy = (None if row.get("best_price") is not None
                  else _int_or_none(row.get("price") or row.get("price_american")))
        taken = best if best is not None else (legacy if legacy is not None else avg)
        if taken is not None:
            bet.price = taken
        if avg is not None:
            bet.price_average = avg
        if row.get("book") or row.get("best_book"):
            bet.book = str(row.get("book") or row.get("best_book"))
        count = row.get("book_count", row.get("n_books"))
        if count is not None:
            bet.book_count = _int_or_none(count)
        if row.get("lock_utc"):
            bet.decision_utc = row["lock_utc"]
        if row.get("start_utc") or row.get("commence_time"):
            bet.start_utc = row.get("start_utc") or row.get("commence_time")
        if row.get("reason"):
            bet.reason = str(row["reason"])
        who = str(row.get("who_decided") or "").lower()
        who = WHO_ALIASES.get(who, who)
        if who in ("code", "model", "rule"):
            bet.who_decided = who
        segment = str(row.get("segment") or ("replay" if row.get("provenance") == "replay" else "")
                      or bet.segment or "forward").lower()
        bet.segment = segment if segment in ("forward", "replay") else "forward"
        if row.get("consensus_fair") is not None:
            bet.consensus_fair = _float_or_none(row["consensus_fair"])
        result = str(row.get("result") or "").lower()
        if result in RESULTS:
            bet.result = result
            # ``units`` is units at the RECORDED (best) price; the house pack
            # names it ``units_best_price``. ``profit_units`` is deliberately
            # NOT read: in the user ledger it is profit at the AVERAGE price,
            # and ``average_units`` recomputes that from ``price_average``.
            units = None
            for field_name in ("units", "units_best_price", "profit_units_best"):
                if row.get(field_name) is not None:
                    units = row[field_name]
                    break
            if units is not None:
                bet.units = _float_or_none(units)
    return list(merged.values()), defs
