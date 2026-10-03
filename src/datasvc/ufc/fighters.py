"""ESPN athletes as `fighters.jsonl` records (the shape is fixed by docs/datasvc/UFC_SCHEMA.md).

Sources, both through one `PoliteFetcher` (`espn_urls.athlete`, `espn_urls.athlete_records`):

* the athlete (`displayName`, `firstName`, `lastName`, `nickname`, `dateOfBirth`, `height`,
  `reach`, `weight`, `stance`, `weightClass`, `citizenship`, `active`, `slug`)
* the overall record (`records` -> the item named "overall": wins, losses, draws, noContests)

Record fields: fighter_id, name, first_name, last_name, nickname, dob, height_in, reach_in,
weight_lb, stance, weight_class, citizenship, active, record, espn_slug, aliases, source_url,
fetched_utc. `record` is {"wins", "losses", "draws"} plus "no_contests" whenever the records
carry it (the brief allows that field; nothing else was added to the contract).

How missing data looks in ESPN's JSON, and what this module does with it. ESPN does not
always leave a key out: it writes a measurement it does not have as a zero or a dash. Lucas
Armand (w2_athlete_5450121.json) has `"reach": 0.0` and `"stance": {"text": "--"}`. A zero
reach stored as a number would pass every "is it present" check and poison any reach
difference feature, so a height, reach or weight of zero or below, an empty string and "--"
are all stored as null, the same as an absent key. A mononym (Alatengheili) has no
`lastName` key: `last_name` is null and the one name is still a usable alias.

Things worth knowing about the source, found while capturing the fixtures:

* `active` is ESPN's flag and it lags. Jose Aldo is "Active" on ESPN and "Retired" on
  UFC.com. It is stored as ESPN says it; do not read it as a retirement signal.
* The eventlog lists every promotion the fighter has fought in: 17 of Ismail Naurdiev's
  first 25 entries are under `leagues/other`, which `espn_urls.event` (a UFC URL) cannot
  fetch. `eventlog_bouts` therefore keeps the UFC league only unless asked for everything.
* `?limit=200` returns the whole eventlog in one page (34 entries, pageCount 1). A paged
  response is still followed, in case ESPN ever clamps the limit.

Aliases are `names.normalise` of the display name, full name, first plus last name and
short name, plus the same names with runs of initials joined or split ("t j dillashaw" and
"tj dillashaw"), because sources disagree on "T.J." and "TJ". There is never a last name
on its own: `names.match` already finds "Naurdiev" inside "ismail naurdiev", and a bare
"silva" alias would make every Silva a perfect tie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from src.datasvc import names
from src.datasvc.http import FetchError, NotFound, RequestCapReached, SourceBlocked, PoliteFetcher
from src.datasvc.ufc import espn_urls

FIGHTER_FIELDS = (
    "fighter_id", "name", "first_name", "last_name", "nickname", "dob", "height_in", "reach_in",
    "weight_lb", "stance", "weight_class", "citizenship", "active", "record", "espn_slug",
    "aliases", "source_url", "fetched_utc",
)

# Text ESPN (and UFC.com) print for "we do not have this". Compared lower case.
_NO_VALUE_TEXT = frozenset({"", "--", "-", "n/a", "na", "none", "null", "unknown"})
_MIN_BIRTH_YEAR = 1900          # a date before this is a placeholder, not a birthday
_DATE_PART = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_EVENT_REF = re.compile(r"/leagues/([^/]+)/events/(\d+)")
_SUMMARY = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
_ALL_CAPS_PAIR = re.compile(r"^[A-Z]{2}$")


# -- small value cleaners ---------------------------------------------------------------

def clean_text(value) -> Optional[str]:
    """Whitespace collapsed; None for empty text and for "--"-style placeholders."""
    if value is None or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())
    return None if text.lower() in _NO_VALUE_TEXT else text


def positive_number(value) -> Optional[float]:
    """A measurement as a float, or None when it is absent, unparseable, zero or negative."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:       # NaN, or ESPN's 0.0 for "not recorded"
        return None
    return number


def _text_of(value) -> Optional[str]:
    """`stance` and `weightClass` are objects with a `text`; accept a bare string too."""
    if isinstance(value, dict):
        value = value.get("text")
    return clean_text(value)


def _date_part(value) -> Optional[str]:
    match = _DATE_PART.match(str(value or "").strip())
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if year < _MIN_BIRTH_YEAR:
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return match.group(0)


def _count(value) -> Optional[int]:
    """A record count (ESPN sends 25.0) as an int; None when it is not a whole number >= 0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number < 0 or number != int(number):
        return None
    return int(number)


# -- names ------------------------------------------------------------------------------

def collapse_initials(normalised: str) -> str:
    """Join runs of single letters: "t j dillashaw" -> "tj dillashaw". Input is normalised."""
    out: List[str] = []
    run: List[str] = []
    for token in normalised.split():
        if len(token) == 1 and token.isalpha():
            run.append(token)
            continue
        if run:
            out.append("".join(run))
            run = []
        out.append(token)
    if run:
        out.append("".join(run))
    return " ".join(out)


def _split_caps_pairs(raw: str) -> str:
    """"TJ Dillashaw" -> "T J Dillashaw" (an all-capitals pair is two initials)."""
    return " ".join(" ".join(tok) if _ALL_CAPS_PAIR.match(tok) else tok for tok in raw.split())


def alias_forms(athlete: dict) -> List[str]:
    """Normalised names this athlete goes by, in order, without duplicates and never a bare surname."""
    first, last = clean_text(athlete.get("firstName")), clean_text(athlete.get("lastName"))
    full_from_parts = " ".join(p for p in (first, last) if p)
    forms: List[str] = []

    def add(form: str) -> None:
        if form and form not in forms:
            forms.append(form)

    for raw in (athlete.get("displayName"), athlete.get("fullName"), full_from_parts,
                athlete.get("shortName")):
        text = clean_text(raw)
        if not text:
            continue
        plain = names.normalise(text)
        add(plain)
        add(collapse_initials(plain))
        split = names.normalise(_split_caps_pairs(text))
        add(split)
    return forms


# -- parsing ----------------------------------------------------------------------------

def _overall_record(records_json) -> Optional[dict]:
    """{"wins", "losses", "draws"[, "no_contests"]} from the item named "overall", else None."""
    if not isinstance(records_json, dict):
        return None
    items = records_json.get("items") or []
    overall = next((i for i in items if isinstance(i, dict)
                    and (i.get("name") == "overall" or i.get("type") == "total")), None)
    if overall is None:
        return None
    stats = {s.get("name"): s.get("value") for s in overall.get("stats") or [] if isinstance(s, dict)}
    wins, losses, draws = _count(stats.get("wins")), _count(stats.get("losses")), _count(stats.get("draws"))
    if None in (wins, losses, draws):
        # No usable stats: fall back to the "25-8-0" summary the same item carries.
        match = _SUMMARY.match(str(overall.get("summary") or overall.get("displayValue") or ""))
        if not match:
            return None
        wins, losses, draws = (int(g) for g in match.groups())
    record = {"wins": wins, "losses": losses, "draws": draws}
    no_contests = _count(stats.get("noContests"))
    if no_contests is not None:
        record["no_contests"] = no_contests
    return record


def parse_athlete(athlete_json: dict, records_json: Optional[dict] = None, *,
                  fetched_utc: str, source_url: str) -> dict:
    """One `fighters.jsonl` record. Pure: no network, no clock."""
    if not isinstance(athlete_json, dict) or not str(athlete_json.get("id") or "").strip():
        raise ValueError("athlete JSON has no id")
    athlete = athlete_json
    first, last = clean_text(athlete.get("firstName")), clean_text(athlete.get("lastName"))
    name = (clean_text(athlete.get("displayName")) or clean_text(athlete.get("fullName"))
            or " ".join(p for p in (first, last) if p) or None)
    active = athlete.get("active")
    return {
        "fighter_id": str(athlete["id"]).strip(),
        "name": name,
        "first_name": first,
        "last_name": last,
        "nickname": clean_text(athlete.get("nickname")),
        "dob": _date_part(athlete.get("dateOfBirth")),
        "height_in": positive_number(athlete.get("height")),
        "reach_in": positive_number(athlete.get("reach")),
        "weight_lb": positive_number(athlete.get("weight")),
        "stance": _text_of(athlete.get("stance")),
        "weight_class": _text_of(athlete.get("weightClass")),
        "citizenship": clean_text(athlete.get("citizenship")),
        "active": active if isinstance(active, bool) else None,
        "record": _overall_record(records_json),
        "espn_slug": clean_text(athlete.get("slug")),
        "aliases": alias_forms(athlete),
        "source_url": source_url,
        "fetched_utc": fetched_utc,
    }


def name_index(fighters: Iterable[dict]) -> Dict[str, List[str]]:
    """{fighter_id: [names]} for `names.match`: the aliases, rebuilt from the name fields when absent."""
    index: Dict[str, List[str]] = {}
    for fighter in fighters:
        fid = str(fighter.get("fighter_id") or "").strip()
        if not fid:
            continue
        forms = [f for f in (fighter.get("aliases") or []) if f]
        if not forms:
            forms = alias_forms({"displayName": fighter.get("name"), "firstName": fighter.get("first_name"),
                                 "lastName": fighter.get("last_name")})
        index[fid] = forms
    return index


# -- eventlog ---------------------------------------------------------------------------

def eventlog_bouts(eventlog_json: dict, *, league: Optional[str] = "ufc") -> List[Tuple[str, str, bool]]:
    """(event_id, bout_id, played) for each entry of one eventlog page, in ESPN's order (newest first).

    By default only the UFC league is kept: the other entries (Bellator, regional shows) are
    bouts `espn_urls.event` cannot fetch. Pass league=None for every league or another slug
    ("other") for that one. A bout appearing twice is listed once; entries without an event
    or competition reference are skipped, never guessed.
    """
    events = (eventlog_json or {}).get("events") if isinstance(eventlog_json, dict) else None
    items = (events or {}).get("items") or []
    out: List[Tuple[str, str, bool]] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = (item.get("event") or {}).get("$ref") if isinstance(item.get("event"), dict) else None
        match = _EVENT_REF.search(str(ref or ""))
        if not match:
            continue
        item_league, event_id = match.group(1), match.group(2)
        if league is not None and item_league != league:
            continue
        bout_id = espn_urls.id_from_ref(item.get("competition"), "competition")
        if not bout_id or (event_id, bout_id) in seen:
            continue
        seen.add((event_id, bout_id))
        out.append((event_id, bout_id, item.get("played") is True))
    return out


def fetch_eventlog_bouts(fetcher: PoliteFetcher, fighter_id: str, *, league: Optional[str] = "ufc",
                         max_age_s: Optional[float] = None, max_pages: int = 20) -> List[Tuple[str, str, bool]]:
    """Every (event_id, bout_id, played) in a fighter's history, following pages if ESPN splits it.

    The first request asks for 200 entries, which covers a whole career in one page. If the
    answer reports more pages anyway, the rest are requested with the page size ESPN reports.
    """
    fid = str(fighter_id).strip()
    page = fetcher.get_json(espn_urls.athlete_eventlog(fid), max_age_s=max_age_s)
    bouts = eventlog_bouts(page, league=league)
    meta = (page.get("events") if isinstance(page, dict) else None) or {}
    try:
        page_count, page_size = int(meta.get("pageCount") or 1), int(meta.get("pageSize") or 200)
    except (TypeError, ValueError):
        page_count, page_size = 1, 200
    seen = {(event_id, bout_id) for event_id, bout_id, _ in bouts}
    for number in range(2, min(page_count, max_pages) + 1):
        url = f"{espn_urls.athlete_eventlog(fid, limit=page_size)}&page={number}"
        for event_id, bout_id, played in eventlog_bouts(fetcher.get_json(url, max_age_s=max_age_s), league=league):
            if (event_id, bout_id) not in seen:
                seen.add((event_id, bout_id))
                bouts.append((event_id, bout_id, played))
    return bouts


# -- fetching ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_fighter(fetcher: PoliteFetcher, fighter_id: str, *, with_records: bool = True,
                  max_age_s: Optional[float] = None) -> dict:
    """The athlete and (unless with_records is False) the overall record, as one record.

    Raises NotFound when the athlete is a 404. A 404 on the records alone leaves `record`
    null: the athlete is still returned, with what ESPN does have. `fetched_utc` is the older of
    the two fetch times, so the record is never newer than its stalest part. `max_age_s` is
    passed to the fetcher: a fighter's record changes after every bout, so a refresh passes it.
    """
    fid = str(fighter_id).strip()
    url = espn_urls.athlete(fid)
    athlete = fetcher.get_json(url, max_age_s=max_age_s)
    got = athlete.get("id") if isinstance(athlete, dict) else None
    if str(got or "").strip() != fid:
        raise ValueError(f"asked ESPN for athlete {fid} and got {got!r}")
    stamps = [fetcher.fetched_utc(url)]
    records = None
    if with_records:
        records_url = espn_urls.athlete_records(fid)
        try:
            records = fetcher.get_json(records_url, max_age_s=max_age_s)
            stamps.append(fetcher.fetched_utc(records_url))
        except NotFound:
            records = None
    fetched = min((s for s in stamps if s), default=None) or _now_iso()
    return parse_athlete(athlete, records, fetched_utc=fetched, source_url=url)


@dataclass
class FighterBatch:
    """What `fetch_fighters` got: the fighters, and one entry per id that could not be fetched.

    Each `failed` entry is {"fighter_id", "kind", "status", "message"}; kind is "not_found"
    (ESPN answered 404), "error" (any other failed request) or "bad_response".
    """

    fighters: List[dict] = field(default_factory=list)
    failed: List[dict] = field(default_factory=list)

    @property
    def not_found(self) -> List[str]:
        return [f["fighter_id"] for f in self.failed if f["kind"] == "not_found"]


def fetch_fighters(fetcher: PoliteFetcher, ids: Iterable[str], *, with_records: bool = True,
                   max_age_s: Optional[float] = None) -> FighterBatch:
    """Fetch each id once, in order. A 404 or a failed request for one fighter goes in `failed`.

    Two things end the batch instead: a browser check (SourceBlocked) and the run's request
    cap (RequestCapReached), as does a 401/403, which is a refusal and not a missing page.
    Pages already fetched are in the fetcher's cache, so running the same ids again resumes.
    """
    batch = FighterBatch()
    seen = set()
    for raw in ids:
        fid = str(raw).strip()
        if not fid or fid in seen:
            continue
        seen.add(fid)
        try:
            batch.fighters.append(fetch_fighter(fetcher, fid, with_records=with_records, max_age_s=max_age_s))
        except (SourceBlocked, RequestCapReached):
            raise
        except NotFound as exc:
            batch.failed.append({"fighter_id": fid, "kind": "not_found", "status": 404, "message": str(exc)})
        except FetchError as exc:
            if exc.status in (401, 403):
                raise
            batch.failed.append({"fighter_id": fid, "kind": "error", "status": exc.status, "message": str(exc)})
        except ValueError as exc:
            batch.failed.append({"fighter_id": fid, "kind": "bad_response", "status": None, "message": str(exc)})
    return batch
