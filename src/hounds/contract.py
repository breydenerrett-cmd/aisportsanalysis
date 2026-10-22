"""The JSON contract every /hounds route returns.

One shape, shared by the web pages (H2), the house pack, and user hounds
(H3), so a page written against a house hound renders a user hound unchanged.
Everything is a plain dataclass; ``to_json`` turns any of them (or a list or
dict of them) into JSON-ready primitives. Nothing here reads a ledger.

Rules the shapes encode:

  * ``paper_only`` is ``true`` and ``not_advice`` is present on EVERY payload.
  * A number that cannot be computed is ``null``, never zero and never a
    guess (``units_average_price``, ``clv``, ``cum_clv_mean_pts``).
  * ``record`` and ``clv`` and ``verdict`` describe FORWARD bets only. Replay
    bets (a rule applied to boards captured before it was written) live in the
    separate ``replay`` block and are never added to a forward figure
    (docs/PREREG_HOUND_VERDICT.md section 1a).
  * ``verdict.label`` is from the closed set in ``src.hounds.verdict.LABELS``
    and is never a function of units.

Field catalogue
---------------

HoundSummary
  id, name, tagline, kind ("house" | "user" | "baseline"), category
  ("stats" | "history" | "market" | "math" | "intangibles" | "esoteric" |
  "random" | "simple" | "mixed" | "baseline"), style (a short label), owner_display (user hounds only),
  sports [..], markets [..], rule_text (plain English, copyable),
  status ("running" | "benched" | "retired" | "not_started"), retired {date, cause} | null,
  record {bets, wins, losses, pushes, voids, units_recorded_price,
  units_average_price | null}, clv {n, mean_pts, ci_low, ci_high} | null,
  verdict {label, sentence, units_note, n} (ALL-TIME: the referee's badge is never windowed by a season; ``n`` is
  the measurable closing-line bets it rests on), first_bet_utc, last_bet_utc,
  open_bets (forward tickets not yet graded and not stale; added 2026-10-19), ungraded_bets (forward tickets more
  than 36 hours past their start with no grade; added 2026-10-19, see ``ticket_status``), settled / ranked (settled
  forward bets in the payload's season view and whether that reaches ``seasons.MIN_RANKED_BETS``; added
  2026-10-19), verified (bool), verified_share | null, checkable_share | null,
  replay {bets, wins, losses, pushes, voids, units_recorded_price} | null,
  spark [..] (last 30 points of cum_units_average_price; when the average
  price is unavailable for the hound it is the recorded-price series and
  spark_basis says so), spark_basis, source, persona {bio, catchphrase, vibe, roasts [5], brags [5],
  epitaph} | null (the voice of a house hound, from the config files; a user hound has none),
  form {streak {kind "W"|"L", length} | null, last7 {bets, wins, losses, units} | null, last_day {date,
  result "win"|"loss"|"flat", wins, losses, units} | null, best_bet {...} | null, worst_beat {...} |
  null, units_basis "average_price"|"recorded_price", last10 ["W"|"L"|"P", oldest first, at most 10],
  avg_price (American, the typical price taken) | null, clv_beat {n, beat, pct 0..1} | null (added
  2026-10-19, additive)} | null (forward bets only; derived from the same
  graded bets as ``record``, never a new measurement).

HoundDetail = HoundSummary + series [SeriesPoint] + bets (a page of BetRow).
SeriesPoint {date, cum_units_average_price, cum_units_recorded_price,
  bets_settled, cum_clv_mean_pts | null}; one point per day the hound had
  graded bets, preceded by a zero point on the day before its first bet.
BetRow {hound_id, date, game, market, selection, line, price, price_average,
  book, consensus_fair, result, units, clv_pts, who_decided ("code" | "model"
  | "rule"), reason, segment ("forward" | "replay"), verified (bool | null),
  status ("OPEN" | "GRADED" | "UNGRADED", stamped at read time by ``with_status``; "" on a refusal)}.
StreamItem = BetRow fields + hound_name + verdict ("play" | "refused_*") +
  refused (bool); result/units are null for a not-yet-graded decision.
Graveyard entries are HoundSummary with status "retired" and retired
  {date, cause} ("retired: down more than 25 units", "paused 2026-10-16: ...",
  "retired by the owner").
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.hounds import NOT_ADVICE, PAPER_ONLY

KIND_HOUSE = "house"
KIND_USER = "user"
KIND_BASELINE = "baseline"
KINDS = (KIND_HOUSE, KIND_USER, KIND_BASELINE)

# "intangibles" and "simple" are the house pack's own (config/house_pack.json) and the pages already
# knew them; they were missing here, so the reader quietly filed 4 pack hounds under "mixed" (found
# 2026-10-18 reading the real pack config).
#
# "ai-desk" and "persona" are the AI desk's (config/desk_hounds.json, docs/PREREG_DESK_HOUNDS.md): the
# desk hound argued by analysts, a bull, a bear and a head, and the personas that read the same data
# under one instruction each.
#
# "ai" is the AI hounds' (config/ai_hounds.json, docs/PREREG_AI_HOUNDS.md): one language model reads the board
# at each game's lock and bets or passes. Forward only; they have no replay and no backtest.
#
# "numerology" is the Gematria Hound's (config/ai_hounds.json, family "gematria"; src/hounds/gematria): a rule that counts
# numerical coincidences for each side. Experimental, paper only, forward only; it is listed with the AI hounds' config
# because it shares their ledger, sports gate and runner, but it asks no model.
CATEGORIES = ("stats", "history", "market", "math", "intangibles", "esoteric", "random",
              "simple", "mixed", "baseline", "ai-desk", "persona", "ai", "numerology")

# A hound that has never made a bet of any kind (the desk before its first publish) is "not_started":
# not benched (nothing has stopped), not running (nothing has run). Only a definition that says it is
# forward-only ever gets it (house.definitions marks the desk's); a user hound uses its store status.
STATUS_NOT_STARTED = "not_started"

WHO_DECIDED = ("code", "model", "rule")
SEGMENTS = ("forward", "replay")

# A ticket whose game started more than this many hours ago and still has no grade is UNGRADED, not open.
# 36 hours is the pack settler's own makeup window (``pack_settle.MAKEUP_HOURS``): the longest a game that was
# played at all is normally still waiting for the next morning's grading pass, a rainout's makeup aside.
# Found 2026-10-19: 11 bets from 2026-09-22 sat on a model page as "open" for a month because the settler had
# skipped them (tests/test_engine_settle_stranded_dates.py); the page must never call a month-old ticket open.
UNGRADED_AFTER_HOURS = 36
TICKET_OPEN, TICKET_GRADED, TICKET_UNGRADED = "OPEN", "GRADED", "UNGRADED"

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
SPARK_POINTS = 30

BASIS = (
    "Every hound makes simulated one-unit bets by a written rule, recorded "
    "before the game and graded afterwards. Units are the scoreboard. The "
    "badge asks something else: did the price the dog grabbed beat where the "
    "market closed? A dog stays a ROOKIE until it has 150 bets we can check "
    "against the close. Replay bets (old boards, rule written later) are "
    "shown apart and never count toward a badge. Paper only, not advice."
)


@dataclass
class Record:
    bets: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    voids: int = 0
    units_recorded_price: float = 0.0
    units_average_price: Optional[float] = None


@dataclass
class ReplayBlock:
    bets: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    voids: int = 0
    units_recorded_price: float = 0.0
    note: str = ("Replay: this rule was written after these boards were "
                 "captured. A rehearsal, not a forward test; never counted in "
                 "the verdict.")


@dataclass
class ClvBlock:
    n: int = 0
    mean_pts: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None


@dataclass
class VerdictBlock:
    label: str = "TOO EARLY"
    sentence: str = ""
    units_note: str = ""
    # Measurable closing-line bets behind the label, ALL-TIME (added 2026-10-19). The badge is the referee's
    # and is never windowed by a season, while ``clv`` follows the season; this is the count the badge rests on.
    n: Optional[int] = None


@dataclass
class RetiredBlock:
    date: Optional[str] = None
    cause: str = ""


@dataclass
class HoundSummary:
    id: str
    name: str
    tagline: str = ""
    kind: str = KIND_HOUSE
    category: str = "mixed"
    style: str = ""
    owner_display: Optional[str] = None
    sports: list = field(default_factory=list)
    markets: list = field(default_factory=list)
    rule_text: str = ""
    status: str = "running"
    retired: Optional[RetiredBlock] = None
    record: Record = field(default_factory=Record)
    clv: Optional[ClvBlock] = None
    verdict: VerdictBlock = field(default_factory=VerdictBlock)
    first_bet_utc: Optional[str] = None
    last_bet_utc: Optional[str] = None
    verified: bool = False
    verified_share: Optional[float] = None
    checkable_share: Optional[float] = None
    replay: Optional[ReplayBlock] = None
    spark: Optional[list] = None
    spark_basis: Optional[str] = None     # "average_price" | "recorded_price"
    source: str = ""
    persona: Optional[dict] = None        # voice only (config files); see docs/VOICE.md
    form: Optional[dict] = None           # streak, last 7 days, last settled day, best bet, worst beat
    open_bets: int = 0                    # forward tickets recorded, not graded, and not yet stale (added 2026-10-19)
    ungraded_bets: int = 0                # forward tickets more than UNGRADED_AFTER_HOURS past their start, no grade
    # Settled forward bets (win, loss, push) in THIS payload's view (a season or all-time), and whether that is
    # enough to be ranked there (src.hounds.seasons.MIN_RANKED_BETS). Added 2026-10-19, additive.
    settled: int = 0
    ranked: bool = False
    # The bankroll view of the same bets (``src.hounds.bankroll``, docs/BANKROLL.md; added 2026-10-19, additive):
    # a $1,000 paper account, 1 unit = $10, with windows by settle time. Payload builders below recompute its
    # windows against the clock. None only on a summary built outside ``stats.summarize``.
    bankroll: Optional[dict] = None
    # Forward settled bets in this view whose price was -200 or worse (the old rule; stats.beyond_cap). They stay
    # in the record and the money, and the digest and the "best bet" boxes keep away from them. Added 2026-10-19.
    old_rule_bets: int = 0


@dataclass
class SeriesPoint:
    date: str
    cum_units_average_price: Optional[float]
    cum_units_recorded_price: float
    bets_settled: int
    cum_clv_mean_pts: Optional[float]
    # The account balance in dollars after this day (``src.hounds.bankroll``): the start plus the stake-weighted
    # cumulative profit at the hound's price basis. The zero point is the opening balance. Added 2026-10-19.
    bankroll_usd: Optional[float] = None


@dataclass
class BetRow:
    hound_id: str
    date: str
    game: str = ""
    market: str = ""
    selection: str = ""
    line: Optional[str] = None
    price: Optional[int] = None
    price_average: Optional[int] = None
    book: Optional[str] = None
    consensus_fair: Optional[float] = None
    result: Optional[str] = None
    units: Optional[float] = None
    clv_pts: Optional[float] = None
    who_decided: str = "rule"
    reason: str = ""
    segment: str = "forward"
    verified: Optional[bool] = None
    # The two stamps behind the dog page's "locked in before the game" line (added 2026-10-18, additive).
    # ``start_utc`` is first pitch / kickoff; ``recorded_utc`` is when the row was WRITTEN (never the lock
    # deadline: a deadline is not a record). Either is None when the source did not carry it, and the page
    # then says less rather than guessing.
    start_utc: Optional[str] = None
    recorded_utc: Optional[str] = None
    # How many books were quoting the market when the bet was decided (added 2026-10-19, additive). None
    # when the source did not carry it; the pages then show the book alone.
    book_count: Optional[int] = None
    # True when the ticket sits at -200 or worse (``stats.beyond_cap``): the lists tag it "-200 or worse (old rule)".
    beyond_cap: bool = False
    # "OPEN" | "GRADED" | "UNGRADED" (``ticket_status``), stamped when a payload is built, not when the book is
    # cached, so the 36-hour line is exact at the moment of the request. "" until stamped and on a refusal.
    status: str = ""


@dataclass
class StreamItem(BetRow):
    hound_name: str = ""
    verdict: str = "play"
    refused: bool = False
    decided_utc: Optional[str] = None


# ---- ticket status ---------------------------------------------------------------

def _utc(value) -> Optional[datetime]:
    """A UTC datetime from an ISO stamp ("...Z" or an offset), or None when it does not parse."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _slate_end(day) -> Optional[datetime]:
    """The last instant of a slate date, as a UTC moment, or None when the date does not parse.

    A slate date is MLB's OFFICIAL date of the game: the EASTERN calendar date of first pitch (see
    src/hounds/seasons.py). Its last instant is therefore midnight at the end of that day in America/New_York, which
    is 04:00 UTC the next morning in daylight time and 05:00 UTC in winter, not 00:00 UTC. Reading it as UTC midnight
    (the first version) called a late west-coast game's ticket stale four to five hours too soon. The Eastern rules
    come from ``src.data.eastern`` (no tz database needed, so this holds on a Windows machine too).
    """
    from src.data.eastern import eastern
    text = str(day or "")[:10]
    try:
        local = datetime.fromisoformat(text) + timedelta(days=1)
    except ValueError:
        return None
    return local.replace(tzinfo=eastern()).astimezone(timezone.utc)


def ticket_status(result: Optional[str], start_utc, date, now: Optional[datetime] = None) -> str:
    """``GRADED``, ``OPEN`` or ``UNGRADED`` for one ticket.

    A ticket with a result is GRADED. One without is OPEN until its game started more than
    ``UNGRADED_AFTER_HOURS`` ago (strictly: exactly 36 hours is still OPEN), then UNGRADED. When the start is
    unknown the slate date stands in for it, counted as the END of that day in America/New_York (the game's official date), so a ticket with no start
    is never called ungraded sooner than 36 hours after its slate day closed. With neither a start nor a
    readable date there is no clock to judge by and the ticket stays OPEN: the page never claims more than the
    record supports.
    """
    if result is not None:
        return TICKET_GRADED
    reference = _utc(start_utc) or _slate_end(date)
    if reference is None:
        return TICKET_OPEN
    now = now or datetime.now(timezone.utc)
    return TICKET_UNGRADED if now - reference > timedelta(hours=UNGRADED_AFTER_HOURS) else TICKET_OPEN


def with_status(rows: list, now: Optional[datetime] = None) -> list:
    """Copies of ``rows`` (BetRow or StreamItem) with ``status`` stamped. A refusal is not a ticket and keeps
    its empty status."""
    now = now or datetime.now(timezone.utc)
    return [r if getattr(r, "refused", False)
            else dataclasses.replace(r, status=ticket_status(r.result, r.start_utc, r.date, now))
            for r in rows]


def _bankroll():
    """``src.hounds.bankroll``, imported on use (it imports this module's time parser)."""
    from src.hounds import bankroll
    return bankroll


# ---- serialisation ---------------------------------------------------------------

def to_json(obj: Any) -> Any:
    """Dataclasses, lists, tuples and dicts to JSON-ready primitives."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_json(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    return obj


_HOUNDMASTER: dict = {"loaded": False, "block": None}


def houndmaster_block() -> Optional[dict]:
    """The kennel boss's lines (config/house_pack.json, ``houndmaster``): the roasts and brags the site
    uses for a hound with no lines of its own. Voice only. None when the file or key is missing, and the
    pages then carry their own short fallback."""
    if not _HOUNDMASTER["loaded"]:
        block = None
        try:
            import json
            from src.paths import repo_root
            with open(repo_root() / "config" / "house_pack.json", encoding="utf-8") as fh:
                loaded = json.load(fh).get("houndmaster")
            block = loaded if isinstance(loaded, dict) else None
        except (OSError, ValueError, ImportError):
            block = None
        _HOUNDMASTER["block"] = block
        _HOUNDMASTER["loaded"] = True
    return _HOUNDMASTER["block"]


def envelope(payload: dict) -> dict:
    """Stamp ``paper_only`` and the not-advice line on any payload."""
    out = dict(payload)
    out["paper_only"] = PAPER_ONLY
    out["not_advice"] = NOT_ADVICE
    return out


def page_args(page: Any, page_size: Any = None) -> tuple:
    """Clamp ``(page, page_size)``: page >= 1, 1 <= size <= MAX_PAGE_SIZE."""
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(page_size) if page_size is not None else DEFAULT_PAGE_SIZE
    except (TypeError, ValueError):
        size = DEFAULT_PAGE_SIZE
    return page, max(1, min(MAX_PAGE_SIZE, size))


def paginate(items: list, page: Any, page_size: Any = None) -> dict:
    page, size = page_args(page, page_size)
    total = len(items)
    start = (page - 1) * size
    return {"page": page, "page_size": size, "total": total,
            "pages": max(1, -(-total // size)),
            "items": items[start:start + size]}


# ---- the "warming up" payload --------------------------------------------------------

WARMING_RETRY_SECONDS = 5
WARMING_MESSAGE = ("The race is warming up: the numbers are being worked out from the "
                   "stored boards and this takes a few seconds the first time. Nothing is "
                   "wrong and nothing is missing; try again in a moment.")


def warming_payload(empty: dict) -> dict:
    """What every GET /hounds route answers (HTTP 200, within a second) while the first build of
    the stats is still running: the route's own shape EMPTY, plus ``warming_up: true``. A page
    that ignores the flag renders an empty race, never a made-up one; a page that reads it shows
    the message and asks again after ``retry_after_seconds``. Never cached."""
    out = dict(empty)
    out.update({"warming_up": True, "retry_after_seconds": WARMING_RETRY_SECONDS,
                "message": WARMING_MESSAGE, "as_of": None})
    return envelope(out)


# ---- payload builders --------------------------------------------------------------

def leaderboard_payload(summaries: list, as_of: Optional[str], season: Optional[dict] = None) -> dict:
    """``season`` is ``seasons.meta(...)`` for the view the summaries were worked out for (absent: no key)."""
    out = {"as_of": as_of, "basis": BASIS, "houndmaster": houndmaster_block(),
           "bankroll_rules": _bankroll().public_block(), "hounds": to_json(_bankroll().refreshed_all(summaries))}
    if season is not None:
        out["season"] = season
    return envelope(out)


def hound_payload(summary: HoundSummary, series: list, bets_page: dict,
                  as_of: Optional[str], season: Optional[dict] = None) -> dict:
    out = to_json(_bankroll().refreshed(summary))
    out["bankroll_rules"] = _bankroll().public_block()
    out["series"] = to_json(series)
    out["bets"] = {**bets_page, "items": to_json(with_status(bets_page["items"]))}
    out["as_of"] = as_of
    out["basis"] = BASIS
    out["houndmaster"] = houndmaster_block()
    if season is not None:
        out["season"] = season
    return envelope(out)


def filter_by_status(rows: list, status: Optional[str], now: Optional[datetime] = None) -> list:
    """``status`` "open" keeps the tickets not yet graded and not stale, "ungraded" the ones more than
    ``UNGRADED_AFTER_HOURS`` past their start with no grade, "graded" the graded ones; anything else keeps all.
    The model page lists open, ungraded and graded tickets separately, and a month-old bet is never "open"."""
    if status == "graded":
        return [b for b in rows if b.result is not None]
    if status in ("open", "ungraded"):
        want = TICKET_OPEN if status == "open" else TICKET_UNGRADED
        now = now or datetime.now(timezone.utc)
        return [b for b in rows if ticket_status(b.result, b.start_utc, b.date, now) == want]
    return rows


BET_OUTCOMES = ("won", "lost", "push")
BET_SORTS = ("newest", "biggest_win", "biggest_loss", "price")
_OUTCOME_RESULTS = {"won": ("win", "won", "w"), "lost": ("loss", "lost", "l"), "push": ("push", "p")}


def refine_bets(rows: list, outcome: Optional[str] = None, sort: Optional[str] = None) -> list:
    """The hound page's ticket filter and order. ``outcome`` (won | lost | push) keeps tickets with that grade; ``sort``
    (newest | biggest_win | biggest_loss | price) reorders them: newest is the list's own order, the wins and losses are by
    the units each moved (biggest first), price is the longest price first. An unknown word changes nothing; the sort is
    stable, so ties keep the newest-first order they came in."""
    if outcome in _OUTCOME_RESULTS:
        wanted = _OUTCOME_RESULTS[outcome]
        rows = [b for b in rows if str(b.result or "").lower() in wanted]
    if sort == "biggest_win":
        return sorted(rows, key=lambda b: -(b.units if isinstance(b.units, (int, float)) else float("-inf")))
    if sort == "biggest_loss":
        return sorted(rows, key=lambda b: (b.units if isinstance(b.units, (int, float)) else float("inf")))
    if sort == "price":
        def dec(b):
            p = b.price_average if isinstance(b.price_average, (int, float)) else b.price
            if not isinstance(p, (int, float)) or p == 0:
                return float("-inf")
            return 1 + (p / 100.0 if p > 0 else 100.0 / -p)
        return sorted(rows, key=lambda b: -dec(b))
    return rows


def bets_payload(hound_id: str, bets_page: dict, as_of: Optional[str], season: Optional[dict] = None) -> dict:
    out = {"hound_id": hound_id, "as_of": as_of, **{**bets_page, "items": to_json(with_status(bets_page["items"]))}}
    if season is not None:
        out["season"] = season
    return envelope(out)


def stream_payload(page: dict, as_of: Optional[str]) -> dict:
    return envelope({"as_of": as_of,
                     **{**page, "items": to_json(with_status(page["items"]))}})


def graveyard_payload(entries: list, as_of: Optional[str]) -> dict:
    return envelope({"as_of": as_of, "basis": BASIS, "houndmaster": houndmaster_block(),
                     "bankroll_rules": _bankroll().public_block(), "hounds": to_json(_bankroll().refreshed_all(entries))})


def series_payload(series_by_id: dict, as_of: Optional[str], season: Optional[dict] = None) -> dict:
    out = {"as_of": as_of, "bankroll_rules": _bankroll().public_block(),
           "series": {k: to_json(v) for k, v in series_by_id.items()}}
    if season is not None:
        out["season"] = season
    return envelope(out)
