"""Events, bouts and results: the schedule half of the UFC data layer.

Reads ESPN's public MMA JSON through a `PoliteFetcher` and produces the records of
`events.jsonl` and `bouts.jsonl` (docs/datasvc/UFC_SCHEMA.md). Nothing here writes
to disk: the caller saves the returned records through `UfcStore.upsert`, and the
fetcher keeps its own raw cache.

Functions
---------
    list_season_events(fetcher, year)                   -> [event_id]
    parse_event(event_json, *, fetched_utc, source_url) -> (event, bouts)   no results yet
    parse_status(status_json)                           -> dict             status + result
    crawl_event(fetcher, event_id)                      -> (event, bouts)
    crawl_season(fetcher, year, since=, until=)         -> (events, bouts)
    crawl_upcoming(fetcher, today, days=21)             -> (events, bouts)

Fields added to the contract (nothing renamed or repurposed)
------------------------------------------------------------
* events: `status_raw`, ESPN's status name (`STATUS_FINAL`...), null when the event
  JSON carries none.
* bouts: `status_raw`, same meaning for the bout. A bout that vanished from its card
  carries the marker `dropped_from_event` (see below), which is ours, not ESPN's.
* bouts: `title_bout` (bool) and `bout_types` (list of str, e.g. "UFC Women's
  Flyweight Title"), from the competition's `types`. On the cards checked (2009,
  2016, 2026) ESPN lists `types` only on title bouts, so an empty list reads as "not
  a title bout"; a card whose `types` ESPN omitted would read the same.

How the records are derived
---------------------------
* ESPN lists the bouts from the last fight to the main event; `bout_ids` and the
  returned bouts are ordered by `matchNumber` ascending (1 = main event), bouts
  without a number last. Fighter a is the competitor with `order` 1, b with `order` 2.
* `parse_event` cannot know a bout's status or result (the event JSON holds only a
  link to the status document), so its bouts are `status` "unknown" with every
  result field null. `winner_id` is the competitor flagged `winner`. ESPN flags no one
  for a draw, a no contest or a bout not yet fought, and so do we.
* An event's status is ESPN's own when it gives a recognised one; otherwise it is
  derived from its bouts (see `derive_event_status`).
* ESPN's empty strings (the "" description of a cancelled bout) are stored as null.
  The cancelled 2020 bout seen carries placeholder competitors ("TBA", "Opponent
  TBA") with ordinary athlete ids, so the fighters worker will meet athletes named
  "TBA"; nothing in the event JSON marks them as placeholders.

Statuses
--------
`STATUS_SCHEDULED`, `STATUS_FINAL` and `STATUS_CANCELED` were seen. `STATUS_IN_PROGRESS`
and `STATUS_POSTPONED` are ESPN's standard names and are mapped by name. Any other
name falls back to ESPN's `state` ("pre", "in", or "post" with `completed` true),
otherwise "unknown". `status_raw` always keeps the original.

Result methods (`result.name` as ESPN sends it -> `result_method`)
-------------------------------------------------------------------
    kotko                  KO_TKO
    submission             SUB
    decision---unanimous   DEC_UNANIMOUS
    decision---split       DEC_SPLIT
    decision---majority    DEC_MAJORITY
    dq                     DQ
    no-contest             NC
    draw                   DRAW
All eight were seen in live responses between 2009 and 2026 (the draw is UFC 256,
Figueiredo v Moreno: its name carries no qualifier). Anything else, for instance a
technical decision, is OTHER with `result_method_raw` kept, and the crawls list such
bouts in the `report` (key `unmapped_results`). DECISION stays in the vocabulary
but is not produced: every decision seen says which kind it was. `end_round`, `end_time_s`
and `fight_time_s` are set only for a final bout: ESPN's `clock` is the seconds into
the round (a decision shows the last round at 300.0), so fight time is
(round - 1) x 300 + clock.

Caching and freshness (what a crawl asks the network for)
---------------------------------------------------------
A final document does not change, so a cached final status is never requested again
(`refresh_final=True` re-reads everything, for an audit of overturned results). Every
other cached copy (an event, a list, a status that is not final) is requested again
when it is older than `max_age_s`; 0 means always. `crawl_event` reads the event
detail again unless it is younger than `max_age_s`, because that is the one document
that tells whether the card changed; `crawl_season` and `crawl_upcoming` also keep a
final event detail, so a finished card costs no request at all on a re-run.
Everything fetched is cached, so a crawl that stops (request cap, network) resumes by
running again.

A bout that is no longer on its event comes back as a copy of what we knew with
status `canceled` and `status_raw` `dropped_from_event`, its result fields null. What we
knew is the stored record from `known_bouts` (pass `store.bouts`) or, without it, the
bouts of the cached copy of the event JSON that a refresh replaced. A bout already
final, or with a winner, is never cancelled. Such a bout is not in the event's
`bout_ids`, which lists what ESPN lists now.

`report` (an optional dict, filled in place) lists what was missing, never guessed:
`status_not_found` (bouts whose status document is a 404, left "unknown"), `dropped`,
`unmapped_results` ([bout_id, raw name]), `final_without_winner` (final bouts with a
decisive method and nobody flagged), `events_not_found`, `season_lists_not_found`
(years, `crawl_upcoming` only), and for the batch crawls `events_listed` (a count) and
`events_crawled`.

A status fetched as final is trusted for good. If ESPN is found to complete a result
after calling it final (a detail added, a result overturned), crawl the affected
season again with `refresh_final=True`.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union

from src.datasvc.http import FetchError, NotFound, RequestCapReached, SourceBlocked
from src.datasvc.ufc import espn_urls

ROUND_SECONDS = 300.0
DROPPED_STATUS_RAW = "dropped_from_event"

STATUSES = ("scheduled", "in_progress", "final", "canceled", "postponed", "unknown")
METHODS = ("KO_TKO", "SUB", "DEC_UNANIMOUS", "DEC_SPLIT", "DEC_MAJORITY", "DECISION",
           "DQ", "NC", "DRAW", "OTHER")

CARD_SEGMENTS = {"main": "main", "prelims1": "prelims", "prelims2": "early_prelims"}

_STATUS_BY_NAME = {
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_IN_PROGRESS": "in_progress",
    "STATUS_FINAL": "final",
    "STATUS_CANCELED": "canceled",
    "STATUS_CANCELLED": "canceled",
    "STATUS_POSTPONED": "postponed",
}
_STATUS_BY_STATE = {"pre": "scheduled", "in": "in_progress"}

# ESPN result.name -> our method. Every key was seen in a live response (result ids 261,
# 262, 263, 264, 269, 277, 284 and 356); see tests/fixtures/espn_mma/w1_status_*.json.
RESULT_METHODS = {
    "kotko": "KO_TKO",
    "submission": "SUB",
    "decision---unanimous": "DEC_UNANIMOUS",
    "decision---split": "DEC_SPLIT",
    "decision---majority": "DEC_MAJORITY",
    "dq": "DQ",
    "no-contest": "NC",
    "draw": "DRAW",
}
# Methods after which nobody is flagged as the winner.
_NO_WINNER_METHODS = ("DRAW", "NC")

DateLike = Union[str, date, datetime]


# ---------------------------------------------------------------------------------
# small value helpers
# ---------------------------------------------------------------------------------

def _text(value) -> Optional[str]:
    """A stripped non-empty string, else None (ESPN sends "" for fields it has nothing for)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def _num(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_date(value: Optional[DateLike]) -> Optional[date]:
    """A date from a date, a datetime (taken in UTC) or an ISO string; None stays None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    return date.fromisoformat(text[:10]) if text else None


def _event_day(date_utc: Optional[str]) -> Optional[date]:
    """The UTC calendar day of an ESPN date string such as "2026-09-26T21:00Z"."""
    try:
        return _as_date(date_utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------
# status and result
# ---------------------------------------------------------------------------------

def map_status(type_block) -> str:
    """Our status for ESPN's `type` block ({"name", "state", "completed", ...})."""
    if not isinstance(type_block, dict):
        return "unknown"
    name = (_text(type_block.get("name")) or "").upper()
    if name in _STATUS_BY_NAME:
        return _STATUS_BY_NAME[name]
    state = (_text(type_block.get("state")) or "").lower()
    if state in _STATUS_BY_STATE:
        return _STATUS_BY_STATE[state]
    if state == "post" and type_block.get("completed") is True:
        return "final"
    return "unknown"


def map_result_method(raw_name: Optional[str]) -> Optional[str]:
    """Our method for ESPN's `result.name`: None when there is no result, OTHER when unseen."""
    name = _text(raw_name)
    if name is None:
        return None
    return RESULT_METHODS.get(name.lower(), "OTHER")


def parse_status(status_json) -> dict:
    """A bout's status document -> status, result and timing fields.

    Keys: status, status_raw, result_method, result_method_raw, result_detail,
    result_target, end_round, end_time_s, fight_time_s. The three timing fields are
    null unless the bout is final (a live bout's period and clock are not an end)."""
    doc = status_json if isinstance(status_json, dict) else {}
    type_block = doc.get("type") if isinstance(doc.get("type"), dict) else {}
    status = map_status(type_block)
    result = doc.get("result") if isinstance(doc.get("result"), dict) else {}
    target = result.get("target") if isinstance(result.get("target"), dict) else {}
    raw_method = _text(result.get("name"))

    end_round = end_time_s = fight_time_s = None
    if status == "final":
        period = _int(doc.get("period"))
        end_round = period if period is not None and period >= 1 else None
        if end_round is not None:
            end_time_s = _num(doc.get("clock"))
        if end_round is not None and end_time_s is not None:
            fight_time_s = (end_round - 1) * ROUND_SECONDS + end_time_s
    return {
        "status": status,
        "status_raw": _text(type_block.get("name")),
        "result_method": map_result_method(raw_method),
        "result_method_raw": raw_method,
        "result_detail": _text(result.get("description")),
        "result_target": _text(target.get("name")),
        "end_round": end_round,
        "end_time_s": end_time_s,
        "fight_time_s": fight_time_s,
    }


def derive_event_status(bout_statuses: Iterable[str]) -> str:
    """An event's status from its bouts' statuses (used when ESPN gives none for the event).

    Cancelled bouts are ignored unless every bout is cancelled. All final is final, any
    in progress is in progress, all scheduled is scheduled, some final and the rest
    still to come is in progress (the card is under way), all postponed is postponed;
    anything else, or no bouts, is unknown."""
    statuses = list(bout_statuses)
    if not statuses:
        return "unknown"
    active = [s for s in statuses if s != "canceled"]
    if not active:
        return "canceled"
    if "in_progress" in active:
        return "in_progress"
    if all(s == "final" for s in active):
        return "final"
    if all(s == "scheduled" for s in active):
        return "scheduled"
    if all(s == "postponed" for s in active):
        return "postponed"
    if "final" in active and all(s in ("final", "scheduled", "postponed") for s in active):
        return "in_progress"
    return "unknown"


# ---------------------------------------------------------------------------------
# parsing an event
# ---------------------------------------------------------------------------------

def _season_year(season) -> Optional[int]:
    if isinstance(season, dict):
        year = _int(season.get("year"))
        if year is not None:
            return year
        found = re.search(r"/seasons/(\d{4})", str(season.get("$ref") or ""))
        return int(found.group(1)) if found else None
    return _int(season)


def _competitor_ids(competitors) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(fighter a, fighter b, winner) ids: a has `order` 1, b has `order` 2."""
    by_order: Dict[int, str] = {}
    winners: List[str] = []
    for index, competitor in enumerate(competitors if isinstance(competitors, list) else []):
        if not isinstance(competitor, dict):
            continue
        fighter_id = (_text(competitor.get("id"))
                      or espn_urls.id_from_ref(competitor.get("athlete"), "athlete")
                      or espn_urls.id_from_ref(competitor, "competitor"))
        if fighter_id is None:
            continue
        # A competitor without an `order` takes its place in the list.
        by_order.setdefault(_int(competitor.get("order")) or index + 1, fighter_id)
        if competitor.get("winner") is True:
            winners.append(fighter_id)
    # Two competitors flagged as winner cannot both be right: name nobody.
    return by_order.get(1), by_order.get(2), (winners[0] if len(winners) == 1 else None)


def _parse_competition(comp: dict, *, event_id: str, fetched_utc: str, source_url: str) -> Optional[dict]:
    bout_id = _text(comp.get("id")) or espn_urls.id_from_ref(comp, "competition")
    if bout_id is None:
        return None     # a competition with no id cannot be stored under a key
    segment_block = comp.get("cardSegment") if isinstance(comp.get("cardSegment"), dict) else {}
    segment_raw = _text(segment_block.get("name"))
    segment = None
    if segment_raw is not None:
        segment = CARD_SEGMENTS.get(segment_raw.lower(), segment_raw.lower())
    format_block = comp.get("format") if isinstance(comp.get("format"), dict) else {}
    regulation = format_block.get("regulation") if isinstance(format_block.get("regulation"), dict) else {}
    type_block = comp.get("type") if isinstance(comp.get("type"), dict) else {}
    types = comp.get("types") if isinstance(comp.get("types"), list) else []
    bout_types = [t for t in (_text(x.get("text")) for x in types if isinstance(x, dict)) if t]
    a, b, winner = _competitor_ids(comp.get("competitors"))
    return {
        "bout_id": bout_id,
        "event_id": event_id,
        "date_utc": _text(comp.get("date")),
        "match_number": _int(comp.get("matchNumber")),
        "card_segment": segment,
        "card_segment_raw": segment_raw,
        "weight_class": _text(type_block.get("text")),
        "scheduled_rounds": _int(regulation.get("periods")),
        "description": _text(comp.get("description")),
        "status": "unknown",
        "status_raw": None,
        "fighter_a_id": a,
        "fighter_b_id": b,
        "winner_id": winner,
        "result_method": None,
        "result_method_raw": None,
        "result_detail": None,
        "result_target": None,
        "end_round": None,
        "end_time_s": None,
        "fight_time_s": None,
        "status_url": espn_urls.ref_url(comp.get("status")) or espn_urls.competition_status(event_id, bout_id),
        "title_bout": any("title" in t.lower() for t in bout_types),
        "bout_types": bout_types,
        "source_url": source_url,
        "fetched_utc": fetched_utc,
    }


def parse_event(event_json, *, fetched_utc: str, source_url: str) -> Tuple[dict, List[dict]]:
    """An event document -> (event record, bout records ordered by match number).

    The bouts carry no result and `status` "unknown" (see the module docstring); the
    event carries its own status when ESPN gives one."""
    if not isinstance(event_json, dict):
        raise ValueError("event JSON is not an object")
    event_id = _text(event_json.get("id")) or espn_urls.id_from_ref(event_json, "event")
    if event_id is None:
        raise ValueError("event JSON has no id")

    competitions = [c for c in (event_json.get("competitions") or []) if isinstance(c, dict)]
    indexed: List[Tuple[int, dict]] = []
    seen = set()
    for index, comp in enumerate(competitions):
        bout = _parse_competition(comp, event_id=event_id, fetched_utc=fetched_utc, source_url=source_url)
        if bout is not None and bout["bout_id"] not in seen:     # a repeated competition counts once
            seen.add(bout["bout_id"])
            indexed.append((index, bout))
    indexed.sort(key=lambda pair: (pair[1]["match_number"] is None, pair[1]["match_number"] or 0, pair[0]))
    bouts = [b for _, b in indexed]

    own_status = event_json.get("status") if isinstance(event_json.get("status"), dict) else {}
    status_block = own_status.get("type") if isinstance(own_status.get("type"), dict) else None
    venues = event_json.get("venues") if isinstance(event_json.get("venues"), list) else []
    venue_id = espn_urls.id_from_ref(venues[0], "venue") if venues else None
    if venue_id is None:    # no venue list: the first competition's own venue, if it names one
        for comp in competitions:
            venue = comp.get("venue") if isinstance(comp.get("venue"), dict) else {}
            venue_id = _text(venue.get("id"))
            if venue_id:
                break
    event = {
        "event_id": event_id,
        "name": _text(event_json.get("name")),
        "short_name": _text(event_json.get("shortName")),
        "date_utc": _text(event_json.get("date")),
        "season": _season_year(event_json.get("season")),
        "status": map_status(status_block),
        "status_raw": _text(status_block.get("name")) if status_block else None,
        "venue_id": venue_id,
        "bout_ids": [b["bout_id"] for b in bouts],
        "source_url": source_url,
        "fetched_utc": fetched_utc,
    }
    return event, bouts


# ---------------------------------------------------------------------------------
# fetching: the freshness rules
# ---------------------------------------------------------------------------------

def _get_json(fetcher, url: str, max_age_s: Optional[float]):
    """`get_json` with one rule: None = any cached copy, <= 0 = always ask, else a maximum age."""
    if max_age_s is None:
        return fetcher.get_json(url)
    if max_age_s <= 0:
        return fetcher.get_json(url, use_cache=False)
    return fetcher.get_json(url, max_age_s=max_age_s)


def _cached(fetcher, url: str):
    """The cached copy of `url`, parsed, or None. Never makes a request."""
    stamp = getattr(fetcher, "fetched_utc", None)
    if not callable(stamp) or stamp(url) is None:
        return None
    try:
        return fetcher.get_json(url)
    except (SourceBlocked, RequestCapReached):
        raise               # never swallowed: a browser check or the request cap stops the run
    except FetchError:      # a cached 404, or a copy that is not JSON, counts as no copy
        return None


def _fetched_utc(fetcher, url: str) -> str:
    stamp = getattr(fetcher, "fetched_utc", None)
    return (stamp(url) if callable(stamp) else None) or _now_iso()


def _age_s(fetcher, url: str) -> Optional[float]:
    stamp = getattr(fetcher, "fetched_utc", None)
    value = stamp(url) if callable(stamp) else None
    if not value:
        return None
    try:
        fetched = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - fetched).total_seconds()


def _is_final(doc) -> bool:
    """A document whose own status says final: a status document, or an event."""
    if not isinstance(doc, dict):
        return False
    block = doc.get("type")
    if not isinstance(block, dict) and isinstance(doc.get("status"), dict):
        block = doc["status"].get("type")
    return map_status(block) == "final"


def _fetch_kept_if_final(fetcher, url: str, max_age_s: Optional[float], *, keep_final: bool):
    """A document; a cached final one is returned without a request when `keep_final`."""
    if not keep_final:
        return _get_json(fetcher, url, max_age_s)
    if callable(getattr(fetcher, "fetched_utc", None)):         # a PoliteFetcher can say what it holds
        cached = _cached(fetcher, url)
        if cached is not None and _is_final(cached):
            return cached
        return _get_json(fetcher, url, max_age_s)
    # A fetcher that cannot say what it holds: ask the plain way (a held copy costs nothing,
    # a missing one is fetched now) and ask again only when what came back is not final.
    doc = fetcher.get_json(url)
    return doc if _is_final(doc) else _get_json(fetcher, url, max_age_s)


def _note(report: Optional[dict], key: str, value) -> None:
    if report is not None:
        report.setdefault(key, []).append(value)


# ---------------------------------------------------------------------------------
# assembling one crawled event
# ---------------------------------------------------------------------------------

def _group_known(known_bouts: Optional[Iterable[dict]]) -> Dict[str, List[dict]]:
    """Stored bout records by event id (read once; `known_bouts` may be a generator)."""
    grouped: Dict[str, List[dict]] = {}
    for bout in known_bouts or ():
        event_id, bout_id = _text(bout.get("event_id")), _text(bout.get("bout_id"))
        if event_id and bout_id:
            grouped.setdefault(event_id, []).append(bout)
    return grouped


def _dropped_bouts(event: dict, current_ids: set, *, previous_doc, known: Iterable[dict],
                   fetched_utc: str) -> List[dict]:
    """Bouts we knew on this event that its card no longer lists, as cancelled records."""
    earlier: Dict[str, dict] = {}
    if isinstance(previous_doc, dict):
        try:
            _, old_bouts = parse_event(previous_doc, fetched_utc=fetched_utc, source_url=event["source_url"])
        except ValueError:
            old_bouts = []
        for bout in old_bouts:
            earlier[bout["bout_id"]] = bout
    for bout in known:      # the stored record is the better base: it may hold a status we fetched
        earlier[_text(bout["bout_id"])] = dict(bout)
    out = []
    for bout_id in sorted(earlier):
        base = earlier[bout_id]
        if bout_id in current_ids or base.get("status") == "final" or base.get("winner_id"):
            continue    # still on the card, or a fight that was fought: leave it as it is
        record = dict(base)
        record.update({
            "status": "canceled", "status_raw": DROPPED_STATUS_RAW, "winner_id": None,
            "result_method": None, "result_method_raw": None, "result_detail": None,
            "result_target": None, "end_round": None, "end_time_s": None, "fight_time_s": None,
            "source_url": event["source_url"], "fetched_utc": fetched_utc,
        })
        out.append(record)
    return out


def _assemble(fetcher, event_doc, *, url: str, previous_doc, max_age_s: Optional[float],
              keep_final: bool, known: Iterable[dict], report: Optional[dict]) -> Tuple[dict, List[dict]]:
    """The event record and its bouts, statuses merged in, plus bouts dropped from the card."""
    fetched = _fetched_utc(fetcher, url)
    event, bouts = parse_event(event_doc, fetched_utc=fetched, source_url=url)
    for bout in bouts:
        try:
            status_doc = _fetch_kept_if_final(fetcher, bout["status_url"], max_age_s, keep_final=keep_final)
        except NotFound:
            _note(report, "status_not_found", bout["bout_id"])
            continue
        bout.update(parse_status(status_doc))
        stamp = _fetched_utc(fetcher, bout["status_url"])
        if stamp > bout["fetched_utc"]:
            bout["fetched_utc"] = stamp
        if bout["result_method"] == "OTHER":
            _note(report, "unmapped_results", [bout["bout_id"], bout["result_method_raw"]])
        if (bout["status"] == "final" and bout["winner_id"] is None
                and bout["result_method"] not in _NO_WINNER_METHODS + (None,)):
            _note(report, "final_without_winner", bout["bout_id"])
    if previous_doc == event_doc:
        previous_doc = None     # the cached copy was not replaced: nothing can have left the card
    dropped = _dropped_bouts(event, {b["bout_id"] for b in bouts}, previous_doc=previous_doc,
                             known=known, fetched_utc=fetched)
    for bout in dropped:
        _note(report, "dropped", bout["bout_id"])
    if event["status"] == "unknown":
        event["status"] = derive_event_status(b["status"] for b in bouts)
    return event, bouts + dropped


# ---------------------------------------------------------------------------------
# the crawl functions
# ---------------------------------------------------------------------------------

def list_season_events(fetcher, year: int, *, max_age_s: Optional[float] = None) -> List[str]:
    """Event ids of one calendar year, in ESPN's order, each once (every page of the list).

    `max_age_s` is the usual freshness rule (None: any cached copy); a past season never
    needs one, the season in progress does."""
    base = espn_urls.season_events(year)
    ids: Dict[str, None] = {}
    page, pages = 1, 1
    while page <= pages:
        doc = _get_json(fetcher, base if page == 1 else f"{base}&page={page}", max_age_s)
        if not isinstance(doc, dict):
            break
        for item in doc.get("items") or []:
            event_id = espn_urls.id_from_ref(item, "event")
            if event_id:
                ids.setdefault(event_id)
        pages = min(_int(doc.get("pageCount")) or 1, 50)
        page += 1
    return list(ids)


def crawl_event(fetcher, event_id, *, max_age_s: Optional[float] = 0.0, refresh_final: bool = False,
                known_bouts: Optional[Iterable[dict]] = None,
                report: Optional[dict] = None) -> Tuple[dict, List[dict]]:
    """One event with its bouts and their results: 1 + (number of bouts) requests when cold.

    The event detail is read again unless its cached copy is younger than `max_age_s`
    (0, the default, means always); a bout whose cached status is final is not
    requested. On a warm cache a finished card therefore costs exactly one request."""
    event_id = _text(event_id)
    if event_id is None:
        raise ValueError("event_id is required")
    url = espn_urls.event(event_id)
    previous = _cached(fetcher, url)
    doc = _get_json(fetcher, url, max_age_s)
    return _assemble(fetcher, doc, url=url, previous_doc=previous, max_age_s=max_age_s,
                     keep_final=not refresh_final, known=_group_known(known_bouts).get(event_id, []),
                     report=report)


def _crawl_listed(fetcher, event_ids: Iterable[str], *, wanted: Callable[[dict], bool],
                  max_age_s: Optional[float], refresh_final: bool, known_bouts,
                  report: Optional[dict]) -> Tuple[List[dict], List[dict]]:
    """Crawl each listed event whose document `wanted` accepts; events come back in date order."""
    known = _group_known(known_bouts)
    crawled: List[Tuple[dict, List[dict]]] = []
    for event_id in event_ids:
        url = espn_urls.event(event_id)
        previous = _cached(fetcher, url)
        try:
            doc = _fetch_kept_if_final(fetcher, url, max_age_s, keep_final=not refresh_final)
        except NotFound:
            _note(report, "events_not_found", event_id)
            continue
        if not wanted(doc):
            continue
        crawled.append(_assemble(fetcher, doc, url=url, previous_doc=previous, max_age_s=max_age_s,
                                 keep_final=not refresh_final, known=known.get(str(event_id), []),
                                 report=report))
        _note(report, "events_crawled", event_id)
    crawled.sort(key=lambda pair: (pair[0]["date_utc"] or "", pair[0]["event_id"]))
    return [event for event, _ in crawled], [bout for _, event_bouts in crawled for bout in event_bouts]


def crawl_season(fetcher, year: int, *, since: Optional[DateLike] = None, until: Optional[DateLike] = None,
                 max_age_s: Optional[float] = 0.0, refresh_final: bool = False,
                 known_bouts: Optional[Iterable[dict]] = None,
                 report: Optional[dict] = None) -> Tuple[List[dict], List[dict]]:
    """Every event of `year` dated from `since` to `until` (UTC days, both inclusive).

    A finished event already in the cache costs no request; anything else is read again
    when its copy is older than `max_age_s` (0 = always, so pass a longer age when
    crawling the season in progress, or use `crawl_upcoming`). An event's date is known
    only from its own document, so every event of the year is read once; those
    outside the dates are then left alone."""
    first, last = _as_date(since), _as_date(until)
    ids = list_season_events(fetcher, year, max_age_s=max_age_s)
    if report is not None:
        report["events_listed"] = len(ids)

    def wanted(doc) -> bool:
        if first is None and last is None:
            return True
        day = _event_day(doc.get("date") if isinstance(doc, dict) else None)
        return day is not None and (first is None or day >= first) and (last is None or day <= last)

    return _crawl_listed(fetcher, ids, wanted=wanted, max_age_s=max_age_s, refresh_final=refresh_final,
                         known_bouts=known_bouts, report=report)


def crawl_upcoming(fetcher, today: DateLike, *, days: int = 21, lookback_days: int = 3,
                   max_age_s: Optional[float] = 6 * 3600.0, far_max_age_s: float = 3 * 86400.0,
                   refresh_final: bool = False, known_bouts: Optional[Iterable[dict]] = None,
                   report: Optional[dict] = None) -> Tuple[List[dict], List[dict]]:
    """Events from `lookback_days` before `today` to `days` after it, re-read when they change.

    The days before today are included so a card that finished overnight gets its
    results on the next run. Events in the window are re-read when their cached copy
    is older than `max_age_s` (lower it on a fight night). An event the cache already
    places outside the window is not asked about again unless its copy is older than
    `far_max_age_s`, so a card far in the future is looked at every few days, not on
    every run. Season lists are read for every year the window touches. Pass
    `known_bouts=store.bouts` so a bout that left a card is found even when the raw
    cache was cleared."""
    today_date = _as_date(today)
    if today_date is None:
        raise ValueError("today is required")
    start = today_date - timedelta(days=lookback_days)
    end = today_date + timedelta(days=days)
    ids: Dict[str, None] = {}
    for year in sorted({start.year, today_date.year, end.year}):
        try:
            listed = list_season_events(fetcher, year, max_age_s=max_age_s)
        except NotFound:        # no list for that year (yet): nothing is listed, and we say so
            _note(report, "season_lists_not_found", year)
            continue
        for event_id in listed:
            ids.setdefault(event_id)
    if report is not None:
        report["events_listed"] = len(ids)

    def day_of(doc) -> Optional[date]:
        return _event_day(doc.get("date")) if isinstance(doc, dict) else None

    def in_window(doc) -> bool:
        day = day_of(doc)
        return day is not None and start <= day <= end

    selected: List[str] = []
    for event_id in ids:
        url = espn_urls.event(event_id)
        cached = _cached(fetcher, url)
        if cached is not None and day_of(cached) is not None and not in_window(cached):
            age = _age_s(fetcher, url)
            if _is_final(cached) or (age is not None and age <= far_max_age_s):
                continue        # outside the window by a copy recent enough to trust
        selected.append(event_id)

    return _crawl_listed(fetcher, selected, wanted=in_window, max_age_s=max_age_s,
                         refresh_final=refresh_final, known_bouts=known_bouts, report=report)
