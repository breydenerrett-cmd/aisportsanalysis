"""The bets spreadsheet: one row for every bet a hound ever recorded, with the reason it gave and (when one exists) the hindsight review.

OWNER ASK 2026-10-28: "export all matchups and analysis and betting reasons whenever a hound takes a bet and make it an exportable
spreadsheet." This module builds the rows and the file; ``api/hounds_postmortems.py`` serves it, ``web/js/record-postmortems.js`` links it.

WHAT A ROW IS. A ``BetRow`` of the hound's all-time view (the same rows the track-record page reads, so the sheet cannot disagree
with the page): slate day, game start, when the row was written, sport and league, matchup, market, side, pick, line, the price
taken, the board's average price, the closing-line value where it was measured, the stake, the result and units, the hound's own
recorded REASON (the rule and the conditions that fired, as stored on the ticket before the game), who decided, and then the
hindsight columns.

HONEST COLUMNS.
  * REPLAY is shown, and labelled. A replay row says ``replay (hindsight, never counted)`` in the Segment column and ``no`` in
    "Counted in record"; only a settled forward bet says ``yes``. An open ticket says ``not settled yet``.
  * The CLOSING-LINE VALUE is the stored measure (points); the closing PRICE itself is not stored per bet, so there is no column
    for it and none is derived. A bet whose close could not be measured has an empty cell, never a zero.
  * STAKE is the member hound's own stake in paper units (default 1, ``bankroll.stake_of``); the house pack stakes one unit.
  * The hindsight columns are headed "Hindsight:" and are empty unless a review exists. Their status column says reviewed, queued
    or not reviewed (a bet graded before reviews began, a Learner bet the sample passed over, a replay bet, an open ticket). A
    review is written after the result, from web sources: it is never pre-game reasoning.

ALL VERSIONS (owner ask 2026-10-28: past versions' results stay on record). ``GET /hounds/{id}/export?versions=all`` is the same sheet for
EVERY version of the hound's lineage, oldest version first, with a "Version" column (v1, v2, ...) and a "Version status" column
(running, replaced by a later version, retired, buried). The default sheet is unchanged: no extra columns. A bet's ID is made from its
own version's hound id, so the IDs stay unique across versions.

CSV ALWAYS, XLSX ONLY IF ``openpyxl`` IS INSTALLED (it is not in ``api/requirements.txt``, so today the answer is CSV and the
route says so). The CSV carries a UTF-8 byte-order mark so Excel reads accents and quotes correctly. CELLS ARE NEUTRALISED against
spreadsheet formulas: a text cell that starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return gets a leading apostrophe
(OWASP's CSV-injection rule), because the review text is written from web pages and a hound's reason is free text. A cell that
is a plain number (a line of ``-1.5``) is left alone.

Paper only. Nothing here can place a bet.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from src.ai.postmortem_store import bet_key
from src.hounds import bankroll
from src.hounds.contract import TICKET_GRADED, ticket_status
from src.hounds.track_record import infer_side

SEGMENT_FORWARD = "forward"
SEGMENT_REPLAY = "replay (hindsight, never counted)"
COUNTED_YES, COUNTED_NO, COUNTED_OPEN = "yes", "no", "not settled yet"

SPORT_OF_FAMILY = {
    "MLB": "Baseball", "BASEBALL": "Baseball", "NFL": "Football", "NCAAF": "Football", "GRIDIRON": "Football",
    "NBA": "Basketball", "WNBA": "Basketball", "NCAAB": "Basketball", "BASKETBALL": "Basketball", "NHL": "Hockey",
    "HOCKEY": "Hockey", "SOCCER": "Soccer", "TENNIS": "Tennis", "CRICKET": "Cricket", "MMA": "MMA", "BOXING": "Boxing",
    "RUGBY": "Rugby", "AFL": "Australian football",
}

REVIEW_REVIEWED, REVIEW_QUEUED, REVIEW_NONE, REVIEW_NA = "reviewed", "queued", "not reviewed", "n/a"

#: (key, header). Order is the order of the columns. The "Hindsight:" headers are the post-mortem columns.
COLUMNS = (
    ("bet_id", "Bet ID"),
    ("hound_id", "Hound ID"),
    ("hound", "Hound"),
    ("date", "Slate date"),
    ("start_utc", "Game start (UTC)"),
    ("recorded_utc", "Recorded (UTC)"),
    ("sport", "Sport"),
    ("league", "League"),
    ("matchup", "Matchup"),
    ("market", "Market"),
    ("side", "Side"),
    ("pick", "Pick"),
    ("line", "Line"),
    ("price", "Price taken"),
    ("price_average", "Average price (board)"),
    ("clv_pts", "Closing-line value (pts)"),
    ("stake_units", "Stake (paper units)"),
    ("result", "Result"),
    ("units", "Units won or lost"),
    ("status", "Ticket status"),
    ("segment", "Segment"),
    ("counted", "Counted in record"),
    ("reason", "Hound's recorded reason (before the game)"),
    ("who_decided", "Decided by"),
    ("review_status", "Hindsight: review status"),
    ("review_depth", "Hindsight: depth"),
    ("review_model", "Hindsight: model"),
    ("review_time", "Hindsight: reviewed (UTC)"),
    ("what_happened", "Hindsight: what happened"),
    ("key_factors", "Hindsight: key factors"),
    ("reason_relevance", "Hindsight: was the hound's reason relevant"),
    ("reason_assessment", "Hindsight: assessment of the reason"),
    ("luck_vs_process", "Hindsight: luck or process"),
    ("info_lacked", "Hindsight: what the hound did not know"),
    ("lesson", "Hindsight: lesson"),
    ("analyst_takes", "Hindsight: other analysts' takes"),
    ("deeper_notes", "Hindsight: deeper notes"),
    ("sources", "Hindsight: sources"),
    ("confidence", "Hindsight: confidence"),
)
HEADERS = [h for _k, h in COLUMNS]

#: The all-versions sheet: the same columns with the version beside the hound's name.
VERSION_COLUMNS = (("version", "Version"), ("version_status", "Version status"))
COLUMNS_ALL_VERSIONS = COLUMNS[:3] + VERSION_COLUMNS + COLUMNS[3:]

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def available_formats() -> tuple:
    """("csv",) always; ("csv", "xlsx") when ``openpyxl`` can be imported."""
    try:
        import openpyxl  # noqa: F401, PLC0415 -- optional by design
    except ImportError:
        return ("csv",)
    return ("csv", "xlsx")


def safe_cell(value: Any) -> Any:
    """A cell value that no spreadsheet will run as a formula. Numbers and plain numeric strings pass through unchanged."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text and text[0] in FORMULA_STARTS and not _NUMBER.match(text.strip()):
        return "'" + text
    return text


def _join(items: Iterable[Any], sep: str = "\n") -> str:
    return sep.join(str(i) for i in items if i not in (None, ""))


def _league_of(sport: Any) -> str:
    from src.sports import catalog
    code = str(sport or "").upper()
    return catalog.label(code) if code else ""


def _counted(row: Any, status: str) -> str:
    if row.segment != SEGMENT_FORWARD:
        return COUNTED_NO
    if status != TICKET_GRADED or row.result not in ("win", "loss", "push"):
        return COUNTED_OPEN if status != TICKET_GRADED else COUNTED_NO       # a void is graded but is not in the record
    return COUNTED_YES


def _review_cells(row: Any, key: str, review: Optional[Mapping], queued: bool) -> Dict[str, Any]:
    cells: Dict[str, Any] = {k: "" for k, _h in COLUMNS[24:]}
    if row.segment != SEGMENT_FORWARD:
        cells["review_status"] = REVIEW_NA
        return cells
    if review is None:
        cells["review_status"] = REVIEW_QUEUED if queued else REVIEW_NONE
        return cells
    takes = [f"{t.get('outlet')}: {t.get('take')} ({t.get('url')})" for t in review.get("analyst_takes") or ()]
    sources = [f"{s.get('title') or s.get('url')} [{s.get('kind')}] {s.get('url')}" for s in review.get("sources") or ()]
    cells.update({
        "review_status": REVIEW_REVIEWED if review.get("grounded") else "reviewed (no sources found)",
        "review_depth": review.get("depth", ""), "review_model": review.get("model", ""),
        "review_time": review.get("created_utc", ""), "what_happened": review.get("what_happened", ""),
        "key_factors": _join(review.get("key_factors") or ()), "reason_relevance": review.get("reason_relevance", ""),
        "reason_assessment": review.get("reason_assessment", ""), "luck_vs_process": review.get("luck_vs_process", ""),
        "info_lacked": _join(review.get("info_hound_lacked") or ()), "lesson": review.get("lesson", ""),
        "analyst_takes": _join(takes), "deeper_notes": review.get("deeper_notes", ""), "sources": _join(sources),
        "confidence": review.get("confidence", "")})
    return cells


def build_rows(data: Any, *, reviews: Optional[Mapping[str, Mapping]] = None, queued: Optional[set] = None,
               now: Any = None, version: Optional[Mapping] = None) -> List[Dict[str, Any]]:
    """The sheet's rows for one hound's all-time ``HoundData`` (``view("all")``), oldest first.

    ``reviews`` is {bet key: public review}; ``queued`` the set of bet keys whose fast review is waiting. Both default to empty,
    so the sheet is complete (and says "not reviewed") with no ledger at all. ``version`` ({"label", "status"}) fills the all-versions
    sheet's two extra cells; without it the rows are exactly the default sheet's."""
    summary = data.summary
    reviews = reviews or {}
    queued = queued or set()
    out: List[Dict[str, Any]] = []
    ordered = sorted(data.bets, key=lambda b: (b.date or "", b.recorded_utc or b.start_utc or "", b.selection or ""))
    for r in ordered:
        key = bet_key(summary.id, r)
        status = r.status or ticket_status(r.result, r.start_utc, r.date, now)
        family = str(r.sport or "").upper()
        cells = {
            "bet_id": key, "hound_id": summary.id, "hound": summary.name, "date": r.date, "start_utc": r.start_utc,
            "recorded_utc": r.recorded_utc, "sport": SPORT_OF_FAMILY.get(family, family.title() if family else ""),
            "league": _league_of(r.sport), "matchup": r.game, "market": r.market, "side": infer_side(r) or "",
            "pick": r.selection, "line": r.line, "price": r.price, "price_average": r.price_average, "clv_pts": r.clv_pts,
            "stake_units": bankroll.stake_of(r, summary.kind), "result": r.result or "open", "units": r.units,
            "status": status, "segment": SEGMENT_FORWARD if r.segment == SEGMENT_FORWARD else SEGMENT_REPLAY,
            "counted": _counted(r, status), "reason": r.reason or "", "who_decided": r.who_decided}
        cells.update(_review_cells(r, key, reviews.get(key), key in queued))
        if version is not None:
            cells.update(version=version.get("label", ""), version_status=version.get("status", ""))
        out.append(cells)
    return out


def build_rows_all_versions(versions: Sequence[Mapping], *, now: Any = None) -> List[Dict[str, Any]]:
    """Every bet of every version of a lineage, version by version, oldest version first (and oldest bet first inside each).

    ``versions`` is ``[{"data": HoundData, "label": "v1", "status": "running", "reviews": {...}, "queued": set()}]``. A version's
    replay rows are shown and labelled exactly as in the single-version sheet."""
    out: List[Dict[str, Any]] = []
    for v in versions:
        out.extend(build_rows(v["data"], reviews=v.get("reviews"), queued=v.get("queued"), now=now,
                              version={"label": v.get("label", ""), "status": v.get("status", "")}))
    return out


def to_csv(rows: Sequence[Mapping], columns: Sequence[tuple] = COLUMNS) -> bytes:
    """UTF-8 with a byte-order mark, header row first, every cell neutralised (``safe_cell``)."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([h for _k, h in columns])
    for row in rows:
        writer.writerow([safe_cell(row.get(k)) for k, _h in columns])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def to_xlsx(rows: Sequence[Mapping], columns: Sequence[tuple] = COLUMNS) -> Optional[bytes]:
    """An .xlsx workbook through ``openpyxl``, or None when it is not installed (the route then offers the CSV)."""
    try:
        from openpyxl import Workbook                        # noqa: PLC0415 -- optional by design
        from openpyxl.styles import Alignment, Font          # noqa: PLC0415
    except ImportError:
        return None
    book = Workbook()
    sheet = book.active
    sheet.title = "Bets"
    sheet.append([h for _k, h in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    wide = {"matchup": 34, "pick": 30, "reason": 60, "what_happened": 70, "key_factors": 60, "reason_assessment": 60,
            "info_lacked": 50, "lesson": 50, "analyst_takes": 70, "deeper_notes": 70, "sources": 70}
    for row in rows:
        values = []
        for key, _h in columns:
            value = safe_cell(row.get(key))
            values.append(value)
        sheet.append(values)
    for idx, (key, header) in enumerate(columns, start=1):
        letter = sheet.cell(row=1, column=idx).column_letter
        sheet.column_dimensions[letter].width = wide.get(key, max(12, min(26, len(header) + 2)))
        if key in wide:
            for cell in sheet[letter][1:]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def filename(hound_id: str, fmt: str, today: Optional[date] = None, all_versions: bool = False) -> str:
    """``linehound-<hound id>-bets-<YYYY-MM-DD>.<fmt>`` (``-bets-all-versions-`` for the all-versions sheet) with the id reduced to
    letters, digits, dot, underscore and hyphen."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(hound_id))[:60] or "hound"
    return f"linehound-{safe}-bets-{'all-versions-' if all_versions else ''}{(today or date.today()).isoformat()}.{fmt}"
