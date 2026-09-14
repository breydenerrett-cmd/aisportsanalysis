"""JSON payload builders for the game-level API vertical slice: the slate
list (GET /games/{date}), one game's quick and advanced views
(GET /game/{date}/{away}/{home}), and the What Changed band
(GET /changed/{date}).

WHY THIS IS SEPARATE FROM api/today.py
---------------------------------------
today.py serialises a WHOLE slate entry (the dossier plus findings plus
synthesis) unfiltered -- appropriate for the one existing consumer, which
wants everything. These three views want three different SHAPES of the same
underlying entries: a thin summary row per game, a "what matters" quick read
for one game, and a full data dump for one game. Building those shapes here
(stdlib, pure functions over already-built slate entries) keeps api/games.py
a thin HTTP shell, the same division of labour today.py/app.py already use.

NOTHING HERE COMPUTES ANYTHING NEW
-----------------------------------
Every number in every payload already exists on the dossier, the finding, or
the synthesis item that `src.pipeline.briefing.build_slate` produced. This
module only selects, labels and reshapes. If a section is missing on the
dossier, the payload says so with the dossier's own gap reason -- it never
fabricates a placeholder. See src/report/dashboard.py, which follows the
identical rule for the HTML renderer; this is that rule's JSON twin.

EVIDENCE RULES, RESTATED AT THE WIRE
-------------------------------------
- market-implied consensus is a de-vigged probability from the board, never
  "the market's true read" -- the field is literally named
  `market_implied_consensus` so no caller can rename it into something it
  is not.
- price improvement is a better EXECUTION price (line-shopping value), never
  EV or edge. The field names and the `note` text both say so.
- no win-probability field is emitted anywhere in this module.
- every quantitative claim keeps the sample it rests on riding beside it.
- a quiet slate (no changed items) still reports how many games were
  checked, never an empty list with no context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import grade
from src.analysis import synthesis as synthesis_mod
from src.pipeline import mismatch as mismatch_mod


# ---------------------------------------------------------------------------
# Game identity
# ---------------------------------------------------------------------------

def _slug(value) -> str:
    """A URL-fragment-safe token. Never empty, so an id is never bare.

    Duplicated from src/report/dashboard.py's `_slug` rather than imported:
    that module is the HTML renderer and this one is the JSON API, and they
    should not have to change together just because both need the same tiny
    string-cleaning rule.
    """
    out = "".join(ch if ch.isalnum() else "-" for ch in str(value or ""))
    out = "-".join(part for part in out.split("-") if part)
    return out or "x"


def game_id(game: dict) -> str:
    """A stable id for one game: the two clubs and the official date.

    Doubleheaders are the one case where those three facts do not separate
    two games; MLB's own game number (or failing that the game_pk) is
    appended so each half gets its own id. This mirrors
    src/report/dashboard.py's anchor scheme so a game's HTML anchor and its
    API id name the same game the same way.
    """
    base = (f"{_slug(game.get('away_team'))}-{_slug(game.get('home_team'))}-"
            f"{_slug(game.get('date'))}")
    marker = game.get("game_number") or game.get("game_pk")
    return f"{base}-{_slug(marker)}" if marker else base


def find_entries(entries: list, away: str, home: str) -> list:
    """Every slate entry for this club pairing, case-insensitive on the
    abbreviation. Normally zero or one; more than one means a doubleheader,
    which the URL scheme `/game/{date}/{away}/{home}` has no room to
    disambiguate -- the caller decides what to do with more than one match
    rather than this function silently picking one.
    """
    away_u, home_u = (away or "").upper(), (home or "").upper()
    return [e for e in entries
            if (e["dossier"].game.get("away_team") or "").upper() == away_u
            and (e["dossier"].game.get("home_team") or "").upper() == home_u]


# ---------------------------------------------------------------------------
# Staleness: shared with api/today.py's odds-age computation
# ---------------------------------------------------------------------------

def _odds_age_seconds(observed_utc: Optional[str], *, now: datetime) -> Optional[float]:
    """Seconds between an observed quote and `now`. None if there is no quote
    to age -- absence over a fabricated age of zero. Same rule as
    api/today.py's `_odds_age_seconds`; kept as its own copy here because
    api/ imports FROM src/, never the reverse (tests/test_api_boundary.py),
    so this module (in src/) cannot import api/today.py's helper."""
    if not observed_utc:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max((now.astimezone(timezone.utc) - observed).total_seconds(), 0.0)


def _board_staleness(section: Optional[dict], *, now: datetime) -> dict:
    """The age of the newest odds row a section carries, or an honest None.

    `section` is whatever board-shaped dict is in play -- price_improvement
    or the raw price_board -- both of which carry `observed_utc` from one
    capture instant (src/analysis/prices.py). A section with no board at all
    reports `has_board: False` rather than a fabricated fresh timestamp.
    """
    observed_utc = (section or {}).get("observed_utc")
    return {
        "observed_utc": observed_utc,
        "age_seconds": _odds_age_seconds(observed_utc, now=now),
        "has_board": bool(section) and not section.get("skipped"),
    }


# ---------------------------------------------------------------------------
# 1. Slate list -- GET /games/{date}
# ---------------------------------------------------------------------------

def _market_implied_consensus(market_section: Optional[dict],
                              price_improvement: Optional[dict] = None) -> Optional[dict]:
    """The de-vigged h2h consensus, if a market priced this game.

    Named `market_implied_consensus` deliberately -- see the module
    docstring's evidence-rules note. It is a probability implied by the
    board at one instant, not a read on who wins.

    TWO SOURCES FOR ONE NUMBER, AND WHY THE SECOND EXISTS (2026-09-07).
    The `market` section is the briefing's plain fair-price section, and it
    only exists when a caller hands `build_slate` a `prices_by_matchup`
    mapping -- the CLI does, the API does not. So on every API-built slate
    this returned None while `price_improvement` sat right beside it holding
    the same de-vigged consensus over nine books. The visible cost: the
    Gameday matchup panel printed "No priced market for this game yet" four
    lines under a Featured Bet quoting that same game at -196 across nine
    books, on the same screen, from the same capture instant. Two reads of
    one board must never disagree on whether the board exists.
    `price_improvement.sides.<side>.consensus_probability` is the identical
    quantity (src/analysis/prices.py de-vigs across the board and averages),
    so it is used when the `market` section is absent -- a fallback for the
    SOURCE of the number, never a second definition of it.

    A THIRD CASE, ADDED 2026-09-12 (checker findings #2/#3 on the fix for
    F-3 above). `market` is no longer only "absent or a live CLI fetch" --
    src.pipeline.briefing.build_slate can now also fill it from the
    multibook board itself (src.analysis.prices.legacy_quotes_from_board)
    when no caller supplied `prices_by_matchup`, which is every API-built
    slate. That board-derived h2h row is ONE book's de-vigged price, picked
    for the lowest hold -- reusing it here would print it under the label
    "fair price across the books" (web/js/labels.js FAIR_LONG), which it is
    not: it disagreed with the real board average by ~0.6 probability
    points on a realistic 7-book board (checker repro, 2026-09-12), and
    below the 6-book floor it printed a number at all on a row this same
    payload calls unpriced (`board_summary.has_board: False`). The board
    fallback tags that row `derived_from_board: True`
    (src/analysis/prices.py) precisely so this function can refuse it and
    fall through to `price_improvement` -- the real multi-book average, and
    None below the floor, exactly matching `board_summary`/`opportunities`
    on both counts. A live CLI quote (no tag) is still used directly, same
    as before this date.
    """
    h2h = (market_section or {}).get("markets", {}).get("h2h") if market_section else None
    if h2h and h2h.get("away_fair") is not None and not h2h.get("derived_from_board"):
        return {"away_fair": h2h.get("away_fair"), "home_fair": h2h.get("home_fair")}
    sides = (price_improvement or {}).get("sides") or {}
    away = (sides.get("away") or {}).get("consensus_probability")
    home = (sides.get("home") or {}).get("consensus_probability")
    if away is None or home is None:
        return None
    return {"away_fair": away, "home_fair": home}


def _board_summary(dossier, *, now: datetime) -> dict:
    price_improvement = dossier.get("price_improvement")
    dispersion = (price_improvement or {}).get("dispersion") or {}
    return {
        "books": dispersion.get("books"),
        **_board_staleness(price_improvement, now=now),
    }


def _data_quality(dossier) -> dict:
    """What this game's dossier does and does not have, plainly.

    `gaps` lists every section the dossier could not fill, with the reason
    it recorded -- so a client can see WHY a flag is false, not just that it
    is.
    """
    return {
        "has_market": dossier.get("market") is not None,
        "has_lineups": dossier.get("lineups") is not None,
        "has_starters": dossier.get("starters") is not None,
        "has_price_board": bool(dossier.get("price_improvement")),
        "gaps": dict(dossier.gaps),
    }


def _board_book_count(dossier) -> int:
    """How many books this game's board actually holds, read from whichever
    of the two board-derived sections is populated. Mirrors `_board_summary`
    above rather than re-deriving a count some other way."""
    dispersion = (dossier.get("price_improvement") or {}).get("dispersion") or {}
    books = dispersion.get("books")
    if books is not None:
        return books
    quotes = (dossier.get("multibook_board") or {}).get("quotes") or []
    return len(quotes)


def _verdict_reason(entry: dict) -> Optional[str]:
    """Why THIS market_unavailable verdict landed here -- null for every
    other verdict.

    THE DEFECT THIS CLOSES (2026-09-12, live on staging). Before
    src.pipeline.briefing.build_slate could build a market section from the
    multibook board (src.analysis.prices.legacy_quotes_from_board), every
    market_unavailable row on the API path carried the identical
    data_quality.gaps.market string -- "no prices on the board for this
    game" -- whether or not a board had actually been captured for the
    game. On the Today page that sentence sat under KC@BOS's hero while the
    card two lines above it quoted the same game, from the same board, at
    -212. Once the board reaches the dossier, the only way a candidate can
    still land on market_unavailable is a real gap: no board was ever
    captured, or a board exists but only ever carries a full-game price
    while the scan routed this game to the first five (the multibook store
    is moneyline-only -- src.analysis.prices.boards_by_matchup's own
    docstring -- so a first-five price is never on it at all). This
    function names which of those two happened, instead of repeating one
    sentence for both.
    """
    if entry.get("verdict") != mismatch_mod.MARKET_UNAVAILABLE:
        return None
    dossier = entry["dossier"]
    if not dossier.get("market"):
        return "No book on our board quoted this game."
    scan = entry.get("scan") or {}
    # `books` backs both branches below. Checker finding #4 (2026-09-12):
    # `_board_book_count` returns 0 when neither price_improvement nor
    # multibook_board is on the dossier (an explicit caller supplied a
    # market with no accompanying board -- not reachable through today's
    # api/ callers, but not impossible), and a "0 books" or "the board is
    # real: 0 books" sentence is the identical contradiction this whole
    # fix exists to remove, just spelled with a number instead of a
    # missing hero. Both branches fall back to the plain "no book quoted
    # this game" sentence whenever the count is 0.
    books = _board_book_count(dossier)
    if scan.get("market") == mismatch_mod.MARKET_F5:
        if not books:
            return "No book on our board quoted this game."
        # Plain English, 2026-09-12: "talent bar" and "routed to" are our
        # words for our machinery, pulled off the slate page on 09-10
        # (web/js/games.js) and caught coming back here by the second check.
        # today.js renders this string verbatim as the hero body.
        return (
            "This game passed our first screen on the first five innings, "
            "and the board we hold has no first-five price for it. The "
            f"full-game prices are real: {books} book"
            f"{'' if books == 1 else 's'} quoting.")
    # The routed market was full-game and the dossier's market section
    # exists yet still lacks a full-game price -- an explicit caller gap
    # (a hand-built prices_by_matchup carrying only an F5 quote, say).
    # Checker finding #4's milder sibling: when the board IS populated,
    # naming its book count is honest and the F5 branch's sentence above
    # already sets that expectation; when it is not, the original blanket
    # sentence still applies.
    if not books:
        return "No book on our board quoted this game."
    return (
        "This game passed our first screen on the full game, and the board "
        "we hold has no full-game price for it yet, though "
        f"{books} book{'' if books == 1 else 's'} "
        f"{'is' if books == 1 else 'are'} quoting the game.")


def slate_game_summary(entry: dict, *, now: datetime) -> dict:
    """One row of the slate list: identity, first pitch, consensus, board
    summary and data-quality flags. Nothing here is a finding or a verdict
    detail -- that lives in the quick/advanced views for one game."""
    dossier = entry["dossier"]
    game = dossier.game
    row = {
        "game_id": game_id(game),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "date": game.get("date"),
        "first_pitch_utc": game.get("start_time_utc"),
        "venue": game.get("venue"),
        "verdict": entry.get("verdict"),
        "market_implied_consensus": _market_implied_consensus(
            dossier.get("market"), dossier.get("price_improvement")),
        "board_summary": _board_summary(dossier, now=now),
        "data_quality": _data_quality(dossier),
        "verdict_reason": _verdict_reason(entry),
    }
    # THE KNOWLEDGE GRADE -- how complete our read of this game is, from the
    # census above and nothing else. Not a forecast and not a ranking on
    # price; src/analysis/grade.py's docstring carries the bands and the
    # measurement that forbids grading on the price gap.
    row["knowledge"] = grade.knowledge_grade(
        game=game, data_quality=row["data_quality"],
        board_summary=row["board_summary"],
        lineups=dossier.get("lineups"), gaps=dossier.gaps)
    return row


def build_slate_list(entries: list, *, date: Optional[str] = None,
                     now: Optional[datetime] = None, notes: Optional[list] = None) -> dict:
    """The full slate-list payload for GET /games/{date}.

    A slate with zero games still returns this shape with an empty `games`
    list and `checked_games: 0` -- the caller (api/games.py) is the one that
    knows whether "zero games" means an off day or an unknown date, and
    reports that distinction as a structured error or an honest empty slate
    accordingly.
    """
    now = now or datetime.now(timezone.utc)
    return {
        "date": date,
        "generated_at": now.isoformat(),
        "checked_games": len(entries),
        "games": [slate_game_summary(e, now=now) for e in entries],
        "notes": list(notes or []),
        # Printed once beside the first grade a page shows. Served rather
        # than typed client-side so the two cannot drift.
        "knowledge_legend": list(grade.legend()),
    }


# ---------------------------------------------------------------------------
# 2a. Quick view -- part of GET /game/{date}/{away}/{home}
# ---------------------------------------------------------------------------

def _finding_wire(finding) -> dict:
    """A Finding as JSON, sample and evidence label carried explicitly --
    the same fields src/report/dashboard.py's `_finding` puts on the wire,
    reused here rather than reinvented so the two never drift on what a
    finding's JSON shape is."""
    label, meaning = synthesis_mod.EVIDENCE_LABELS.get(
        finding.evidence, (finding.evidence, ""))
    return {
        "detector": finding.detector,
        "claim": finding.claim,
        "sample": finding.sample,
        "sample_n": synthesis_mod.sample_size(finding.sample),
        "surprise": finding.surprise,
        "side": finding.side,
        "evidence": finding.evidence,
        "evidence_label": label,
        "evidence_meaning": meaning,
    }


def _top_findings(entry: dict) -> list:
    """The ranked, sample-and-evidence-labelled items synthesis already
    computed for this entry -- read back rather than recomputed, so the
    quick view can never disagree with what `make_entry` put in
    `entry["synthesis"]`."""
    summary = entry.get("synthesis") or {}
    items = summary.get("items") or []
    return [{
        "statement": item.get("statement"),
        "category": item.get("category"),
        "sample": item.get("sample"),
        "sample_n": item.get("sample_n"),
        "below_floor": item.get("below_floor"),
        "evidence": item.get("evidence"),
        "evidence_label": item.get("evidence_label"),
        "evidence_meaning": item.get("evidence_meaning"),
        "source": item.get("source"),
    } for item in items]


def _price_section(dossier, *, now: datetime) -> dict:
    """Best-available price vs consensus-as-price, staleness attached.

    "Consensus-as-price" here means the de-vigged consensus PROBABILITY
    restated as a price comparison point -- never a prediction, never an EV
    figure. `price_improvement`'s own `label`/`note` text (already vetted by
    tests/test_customer_language.py's evidence-language checks) rides along
    unchanged.
    """
    section = dossier.get("price_improvement")
    if not section or section.get("skipped"):
        return {"available": False,
                "reason": dossier.gaps.get("price_improvement")
                          or (section or {}).get("skipped")
                          or "no multi-book observations for this game"}
    sides = {}
    for side in ("away", "home"):
        detail = (section.get("sides") or {}).get(side) or {}
        if detail.get("skipped"):
            sides[side] = {"skipped": detail["skipped"]}
            continue
        sides[side] = {
            "best_price": detail.get("best_price"),
            "best_book": detail.get("best_book"),
            "consensus_probability": detail.get("consensus_probability"),
            "improvement_probability_points": detail.get("improvement_points"),
            "improvement_return_pct": detail.get("improvement_return_pct"),
        }
    dispersion = section.get("dispersion") or {}
    return {
        "available": True,
        "sides": sides,
        "books": dispersion.get("books"),
        "home_probability_range": dispersion.get("home_probability_range"),
        "label": section.get("label"),
        "note": section.get("note"),
        "staleness": _board_staleness(section, now=now),
    }


def build_quick_view(entry: dict, *, now: Optional[datetime] = None) -> dict:
    """The quick payload for one game: top findings and the price section.

    Deliberately thin -- everything else the system knows about this game is
    the advanced view's job (`build_advanced_view`).
    """
    now = now or datetime.now(timezone.utc)
    dossier = entry["dossier"]
    game = dossier.game
    return {
        "game_id": game_id(game),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "verdict": entry.get("verdict"),
        "side": entry.get("side"),
        "market": entry.get("market"),
        "summary": entry.get("summary"),
        "headline": (entry.get("synthesis") or {}).get("headline"),
        "top_findings": _top_findings(entry),
        "price": _price_section(dossier, now=now),
    }


# ---------------------------------------------------------------------------
# 2b. Advanced view -- part of GET /game/{date}/{away}/{home}
# ---------------------------------------------------------------------------

def build_advanced_view(entry: dict, *, now: Optional[datetime] = None) -> dict:
    """The full data dump for one game: every dossier section, verbatim,
    plus every gap the dossier recorded with its reason.

    This is the "explicit nulls with a reason, never fabricated" contract
    made literal: a section with data is present under its own name; a
    section without it is absent from `sections` and present in `gaps`
    instead, naming why. Nothing here re-derives a number a section already
    computed -- this function only serialises.
    """
    now = now or datetime.now(timezone.utc)
    dossier = entry["dossier"]
    game = dossier.game
    return {
        "game_id": game_id(game),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "game": dict(game),
        "verdict": entry.get("verdict"),
        "side": entry.get("side"),
        "market": entry.get("market"),
        "summary": entry.get("summary"),
        "information_time": dossier.information_time.isoformat(),
        "sections": dict(dossier.sections),
        "gaps": dict(dossier.gaps),
        "findings": [_finding_wire(f) for f in entry.get("findings", [])],
        "staleness": _board_staleness(dossier.get("price_improvement"), now=now),
    }


# ---------------------------------------------------------------------------
# 3. What Changed band -- GET /changed/{date}
# ---------------------------------------------------------------------------

def _changed_items_for_entry(entry: dict) -> list:
    """One item per roster event on this game's dossier, game context
    attached so the band can list events across a whole slate without the
    caller having to re-join them to a game."""
    dossier = entry["dossier"]
    game = dossier.game
    section = dossier.get("what_changed")
    events = (section or {}).get("events") or []
    items = []
    for event in events:
        items.append({
            "game_id": game_id(game),
            "away_team": game.get("away_team"),
            "home_team": game.get("home_team"),
            "class": event.get("class"),
            "headline": event.get("headline"),
            "tier": event.get("tier"),
            "tier_sentence": event.get("tier_sentence"),
            "basis": list(event.get("basis") or []),
            "reasons": list(event.get("reasons") or []),
            "timing": event.get("timing"),
            "seen_utc": event.get("seen_utc"),
            "inadmissible": bool(event.get("inadmissible")),
            "summary": event.get("summary"),
            "not_an_edge": section.get("not_an_edge"),
            "cutoff": section.get("cutoff"),
        })
    return items


def build_changed_items(entries: list, *, date: Optional[str] = None,
                        now: Optional[datetime] = None) -> dict:
    """The What Changed band for a whole slate.

    Every item is timestamped (`seen_utc`, the instant our poller first saw
    it bounded or unbounded per `timing`) and source-dated (`cutoff`, the
    point-in-time boundary the player's own record was read against). A
    quiet slate -- the ordinary case -- reports how many games were checked
    rather than handing back an empty list with no context (the evidence
    rule this endpoint exists to satisfy).
    """
    now = now or datetime.now(timezone.utc)
    items = []
    for entry in entries:
        items.extend(_changed_items_for_entry(entry))
    items.sort(key=lambda item: item.get("seen_utc") or "", reverse=True)
    notes = ([f"Checked {len(entries)} game(s); no roster events since our own "
             "last look."] if entries and not items else [])
    return {
        "date": date,
        "generated_at": now.isoformat(),
        "checked_games": len(entries),
        "items": items,
        "notes": notes,
    }
