"""Odds: one row per provider per bout, from ESPN's competition odds.

Source: `espn_urls.competition_odds(event, bout)`: a list with one item per provider.
`parse_odds` is a pure function of that JSON and the bout record; `fetch_bout_odds` reads it
through the PoliteFetcher. Prices are American (ints), read from the `american` strings
(ESPN's own decimal and fractional forms are rounded copies of it).

Row (odds.jsonl, key bout_id + provider_id), the contract's fields: `bout_id`, `event_id`,
`provider_id`, `provider`, `a_ml_open|close|current`, `b_ml_open|close|current`,
`rounds_total`, `over_open|close|current`, `under_open|close|current`, `method_odds`,
`spread_raw`, `orientation` ("verified" or "unknown"), `is_closing`, `source_url`,
`fetched_utc`. Fields this module adds (the contract's are never renamed or repurposed):

    orientation_basis  how orientation was settled (below)
    a_side             "home" or "away": which ESPN side is fighter a (None when unknown)
    sides_raw          {"home": {...}, "away": {...}} ESPN's own sides, always kept:
                       athlete_id, favorite, ml_open|close|current, method_odds. When
                       orientation is "unknown" this is the only place the prices are.
    rounds_total_open|close|current   the over/under LINE at each phase. over_open and
                       under_open are priced at rounds_total_open, which can differ from the
                       closing line, so never pair an open price with the closing line.
                       `rounds_total` is the latest line ESPN has (current, else close, else open).
    draw_open|close|current   price of a draw, where a provider lists one (Betradar, 2019)
    in_play            True for a live in-play feed (provider name contains "live", i.e.
                       "ESPN Bet - Live Odds", id 59, seen in 2024 and 2025). Its prices move
                       during the fight: on 2024-04-13 it shows K. Green -3000 where every
                       pre-fight provider has -167 to -210 (Green won). It is never a
                       pre-fight price; filter it out of anything that predicts a fight.
    details            ESPN's `details` text ("M. Jackson -230": the favourite's short name
                       and price)
    props_url          the `propBets` $ref, recorded only (props are not fetched here)

Method of victory: `method_odds` = {"a": {"ko_tko_dq": {"open", "close", "current"},
"submission": {...}, "decision": {...}}, "b": {...}} (ESPN's `points` is the decision price),
None when the provider lists no method prices or the orientation is unknown. `spread_raw` is
kept as ESPN gave it, not interpreted: {"spread": item-level number (the HOME side's line in
all four items that have one), "home": {"spreadOdds", "open"|"close"|"current":
{"pointSpread", "spread"}}, "away": {...}}, None when the provider has no spread (only the
four 2026 DraftKings items have one).

`is_closing` is True when the bout was final when fetched and the row is not an in-play
feed, i.e. `current` is the closing line. A completed bout from DraftKings (2026) or ESPN BET
(2025) also carries an explicit `close` block; every other provider of a past bout has
`current` (some also `open`) and no `close`, and for those `current` is the last line ESPN
stored. An upcoming bout has no `close` (its `*_close` fields are null).

What the saved and probed responses show (38 provider rows, 9 bouts, 2019 to 2026):

* Odds are absent before 2019-09: the odds list is empty (count 0) for the 2016, 2017
  (UFC 214), 2018-04, 2019-03 and 2019-06-08 bouts probed; 6 providers on 2019-09-07
  (UFC 242) and 2021-07-10, 8 on 2022-12-10, 12 on 2024-04-13, 2 on 2025-07-19 (ESPN BET and
  its live feed), 1 in 2026 (DraftKings, id 100). The start is between 2019-06-08 and
  2019-09-07 (main events only were probed).
* Providers seen: DraftKings 100 (2026), DraftKings (old) 40, ESPN BET 58, ESPN Bet - Live
  Odds 59, Bet365 1001, Betradar 37, Caesars 38/45/52/57, Consensus 1004, Unibet 36, Wynn 32,
  BetfairSportsbook 50, PointsBet 48, Holland Casino 55, Titanbets 53, Sugarhouse 41, Rushbet 51.
* Which provider counts as the pre-fight price is the caller's choice (one row per provider is
  kept). From the samples: 2026 lists only DraftKings (100); 2025-07-19 lists ESPN BET (58),
  the one with open, close and current, plus the live feed; 2024 and earlier list many books
  with `current` and, from 2024, often `open`, never `close`. Whatever is chosen, leave out
  the `in_play` rows.
* A block can be missing anywhere: most providers send only `current`; some send no
  moneyline at all (Sugarhouse 2024: only the athletes and a total); some have a total
  with no prices (ESPN BET 2024). Each missing piece is null, never inferred.
* `moneylineWinner` and `spreadWinner` are false on every item including completed bouts, so
  they say nothing about who won and are ignored.

Orientation. ESPN names the two sides home and away; which of them is fighter a (the
competitor with `order` 1 in the bout record) is decided from the data, never assumed:

1. Each side carries an `athlete` $ref. If those ids are the bout's two fighters, that is the
   answer ("athlete_ref"). An id that is not in the bout, or the same id on both sides, makes
   the row "unknown" (the odds belong to another bout or are corrupt).
2. When `fighters` (id -> record with `name`, optionally `aliases`) is given, the favourite's
   short name in `details` ("R. Rosas Jr.") is matched to the two fighters (an initial plus
   the trailing name tokens, or the full name) and the favourite's side is taken from the
   `favorite` flag cross-checked with the price in `details`. With athlete refs this is a
   check: a disagreement makes the row "unknown" ("athlete_ref_vs_details_conflict").
   Without usable athlete refs it is the answer ("details_name").
3. Otherwise "unknown": a/b fields null, `method_odds` null, `sides_raw` still holds the prices.

Evidence: the athlete refs name both sides on all 38 rows and are always the bout's two
fighters; the favourite's name in `details` agrees with them on all 37 rows that have a
`details` (the 38th, Sugarhouse 2024, has none); the flagged favourite is the winner on all
28 rows of the 7 bouts that have both. In every probed bout home was the order-1 fighter
(9 of 9 bouts, 38 of 38 rows), including two where home was the underdog (UFC 282's draw,
UFC 332), so it is not "home = favourite" or "home = winner". The code does not rely on it:
the tests swap the sides, and swap which fighter is a, and the answer follows the refs.

What an empty or missing list produces: an empty list is a valid result (no rows); a 404 on
the odds URL also gives no rows. `fetch_bout_odds` reads an unfinished bout with `max_age_s`
so its prices refresh; a final bout is read once, but a cached copy fetched before the bout
could have finished (its date plus `settle_s`) is read again so that a pre-fight copy never
stands in for the closing line.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.datasvc import http, names
from src.datasvc.ufc import espn_urls

PHASES = ("open", "close", "current")
METHOD_KEYS = {"koTkoDq": "ko_tko_dq", "submission": "submission", "points": "decision"}

LIVE_MAX_AGE_S = 1800
SETTLE_S = 8 * 3600
MAX_PAGES = 10

_MINUS = chr(0x2212)          # the typographic minus sign some feeds use in front of a price
_LIVE = re.compile(r"\blive\b", re.IGNORECASE)
_DETAILS = re.compile(r"^(?P<name>.*\S)\s+(?P<price>[+\-" + _MINUS + r"]\d{2,5}|EVENS?)\s*$", re.IGNORECASE)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


# -- small readers ---------------------------------------------------------------------


def _american(value) -> Optional[int]:
    """An American price as an int, or None. "+195", "-238", 190.0 and "EVEN" are read; a
    value inside (-100, +100) is not a price and reads as None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().upper().replace(_MINUS, "-")
        if text in ("EVEN", "EVENS", "EV"):
            return 100
        try:
            number = float(text)
        except ValueError:
            return None
    if number != number or abs(number) < 100 or number != int(number):
        return None
    return int(number)


def _price(node) -> Optional[int]:
    """A price from ESPN's {"american": "+195", ...} node (or a bare number)."""
    if isinstance(node, dict):
        for key in ("american", "alternateDisplayValue"):
            price = _american(node.get(key))
            if price is not None:
                return price
        return None
    return _american(node)


def _line(node) -> Optional[float]:
    """The over/under line from a total node ({"value": 2.5, "american": "2.5"}) or a number."""
    candidates = []
    if isinstance(node, dict):
        candidates = [node.get("value"), node.get("american"), node.get("alternateDisplayValue")]
    else:
        candidates = [node]
    for candidate in candidates:
        if candidate is None or isinstance(candidate, bool):
            continue
        try:
            number = float(str(candidate).strip())
        except ValueError:
            continue
        if number == number and number > 0:
            return number
    return None


def _text(node) -> Optional[str]:
    if isinstance(node, dict):
        value = node.get("american", node.get("alternateDisplayValue"))
        return None if value is None else str(value)
    return None if node is None else str(node)


def _str_id(value) -> Optional[str]:
    return None if value is None or value == "" else str(value)


def _block(node, phase: str) -> dict:
    block = node.get(phase) if isinstance(node, dict) else None
    return block if isinstance(block, dict) else {}


# -- one side of the book ----------------------------------------------------------------


def _methods(side: dict) -> Optional[dict]:
    """{"ko_tko_dq": {"open", "close", "current"}, "submission": ..., "decision": ...} or None."""
    out, any_price = {}, False
    for espn_key, key in METHOD_KEYS.items():
        entry = {}
        for phase in PHASES:
            methods = _block(side, phase).get("victoryMethod")
            price = _price(methods.get(espn_key)) if isinstance(methods, dict) else None
            entry[phase] = price
            any_price = any_price or price is not None
        out[key] = entry
    return out if any_price else None


def _read_side(item: dict, key: str) -> dict:
    side = item.get(key) if isinstance(item.get(key), dict) else {}
    athlete = side.get("athlete")
    current = _price(_block(side, "current").get("moneyLine"))
    if current is None:
        current = _price(side.get("moneyLine"))
    return {
        "athlete_id": espn_urls.id_from_ref(athlete, "athlete") if athlete else None,
        "favorite": side["favorite"] if isinstance(side.get("favorite"), bool) else None,
        "ml_open": _price(_block(side, "open").get("moneyLine")),
        "ml_close": _price(_block(side, "close").get("moneyLine")),
        "ml_current": current,
        "method_odds": _methods(side),
    }


def _spread_raw(item: dict) -> Optional[dict]:
    """The spread exactly as ESPN gave it (its meaning in MMA is not confirmed)."""
    sides = {}
    for name, key in (("home", "homeAthleteOdds"), ("away", "awayAthleteOdds")):
        side = item.get(key)
        if not isinstance(side, dict):
            continue
        entry = {}
        if side.get("spreadOdds") is not None:
            entry["spreadOdds"] = side["spreadOdds"]
        for phase in PHASES:
            block = _block(side, phase)
            if "pointSpread" in block or "spread" in block:
                entry[phase] = {"pointSpread": _text(block.get("pointSpread")), "spread": _text(block.get("spread"))}
        if entry:
            sides[name] = entry
    if item.get("spread") is None and not sides:
        return None
    out = {"spread": item.get("spread")}
    out.update(sides)
    return out


# -- orientation --------------------------------------------------------------------------


def _name_tokens(record) -> List[List[str]]:
    """Every name a fighter record goes by, as token lists (name, aliases, first + last)."""
    if isinstance(record, str):
        found = [record]
    elif isinstance(record, dict):
        found = [record.get("name")] + list(record.get("aliases") or [])
        if record.get("first_name") and record.get("last_name"):
            found.append(f"{record['first_name']} {record['last_name']}")
    else:
        return []
    return [tokens for tokens in (names.tokens(n) for n in found if n) if tokens]


def _short_matches(short: List[str], full: List[str]) -> bool:
    """"R. Rosas Jr." matches "Raul Rosas Jr.": an initial plus the trailing name tokens, or equal."""
    if not short or not full:
        return False
    if short == full:
        return True
    if len(short) >= 2 and len(short[0]) == 1:
        rest = short[1:]
        return len(full) > len(rest) and full[0][:1] == short[0] and full[-len(rest):] == rest
    return False


def _favourite_side(details_price: Optional[int], home: dict, away: dict) -> Optional[str]:
    """Which side is the favourite, from the flags cross-checked with the price in `details`."""
    flagged = [s for s, d in (("home", home), ("away", away)) if d["favorite"] is True]
    if details_price is None:
        return flagged[0] if len(flagged) == 1 else None
    by_price = [s for s, d in (("home", home), ("away", away)) if d["ml_current"] == details_price]
    if len(by_price) != 1 or (flagged and flagged != by_price):
        return None
    return by_price[0]


def _a_side_from_details(item: dict, home: dict, away: dict, fighters, a_id: Optional[str],
                         b_id: Optional[str]) -> Optional[str]:
    """Which ESPN side is fighter a, from the favourite's name in `details`; None when it cannot say."""
    if not fighters or not hasattr(fighters, "get") or not item.get("details") or a_id is None or b_id is None:
        return None
    found = _DETAILS.match(str(item["details"]))
    if not found:
        return None
    short = names.tokens(found.group("name"))
    price = _american(found.group("price"))
    favourite = _favourite_side(price, home, away)
    if favourite is None:
        return None
    matched = [fid for fid in (a_id, b_id)
               if any(_short_matches(short, tokens) for tokens in _name_tokens(fighters.get(fid)))]
    if len(matched) != 1:
        return None
    other = "away" if favourite == "home" else "home"
    return favourite if matched[0] == a_id else other


def _orientation(item: dict, bout: dict, home: dict, away: dict, fighters) -> Tuple[Optional[str], str]:
    """(a_side, basis): which ESPN side is fighter a, and how that was settled."""
    a_id, b_id = _str_id(bout.get("fighter_a_id")), _str_id(bout.get("fighter_b_id"))
    in_bout = {x for x in (a_id, b_id) if x is not None}
    by_ref: Optional[str] = None
    refs = [home["athlete_id"], away["athlete_id"]]
    if any(refs):
        if any(r is not None and r not in in_bout for r in refs):
            return None, "athlete_ref_not_in_bout"
        if refs[0] is not None and refs[0] == refs[1]:
            return None, "athlete_ref_same_on_both_sides"
        if a_id is not None and b_id is not None and a_id != b_id:
            if refs[0] is not None:
                by_ref = "home" if refs[0] == a_id else "away"
            else:
                by_ref = "away" if refs[1] == a_id else "home"
    by_name = _a_side_from_details(item, home, away, fighters, a_id, b_id)
    if by_ref is not None:
        if by_name is not None and by_name != by_ref:
            return None, "athlete_ref_vs_details_conflict"
        return by_ref, "athlete_ref" if by_name is None else "athlete_ref+details_name"
    if by_name is not None:
        return by_name, "details_name"
    return None, "undetermined"


# -- rows ---------------------------------------------------------------------------------


def _item_prices(item: dict, key: str, top_key: str) -> Dict[str, Optional[int]]:
    """over/under/draw price per phase from the item's open, close, current blocks."""
    out = {phase: _price(_block(item, phase).get(key)) for phase in PHASES}
    if out["current"] is None and top_key:
        out["current"] = _american(item.get(top_key))
    return out


def _provider_of(item: dict) -> Tuple[Optional[str], Optional[str]]:
    provider = item.get("provider") if isinstance(item.get("provider"), dict) else {}
    # The item's own $ref ends in /odds/<provider id>, which is the fallback.
    pid = _str_id(provider.get("id")) or espn_urls.id_from_ref(item.get("$ref"), "provider")
    return pid, provider.get("name")


def _copy_methods(methods: Optional[dict]) -> Optional[dict]:
    return None if methods is None else {key: dict(prices) for key, prices in methods.items()}


def parse_odds(odds_json, *, bout: dict, fetched_utc: str, source_url: str, fighters=None) -> List[dict]:
    """The odds rows (one per provider) for `bout` from ESPN's odds list.

    `bout` is a bouts.jsonl record (bout_id, event_id, fighter_a_id, fighter_b_id, status);
    `fighters` maps fighter id -> record with `name` and is only used to cross-check or, without
    athlete refs, settle orientation. An empty list gives []. The first item of a repeated
    provider id wins.
    """
    items = odds_json if isinstance(odds_json, list) else (odds_json or {}).get("items") or []
    final = bout.get("status") == "final"
    rows: List[dict] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        provider_id, provider_name = _provider_of(item)
        if provider_id is None or provider_id in seen:
            continue
        seen.add(provider_id)
        home, away = _read_side(item, "homeAthleteOdds"), _read_side(item, "awayAthleteOdds")
        a_side, basis = _orientation(item, bout, home, away, fighters)
        a = None if a_side is None else (home if a_side == "home" else away)
        b = None if a_side is None else (away if a_side == "home" else home)
        in_play = bool(provider_name and _LIVE.search(str(provider_name)))

        lines = {phase: _line(_block(item, phase).get("total")) for phase in PHASES}
        if lines["current"] is None:
            lines["current"] = _line(item.get("overUnder"))
        overs = _item_prices(item, "over", "overOdds")
        unders = _item_prices(item, "under", "underOdds")
        draws = _item_prices(item, "draw", "")

        row = {
            "bout_id": str(bout["bout_id"]),
            "event_id": _str_id(bout.get("event_id")),
            "provider_id": provider_id,
            "provider": provider_name,
            "orientation": "unknown" if a_side is None else "verified",
            "orientation_basis": basis,
            "a_side": a_side,
            "is_closing": bool(final and not in_play),
            "in_play": in_play,
            "rounds_total": lines["current"] if lines["current"] is not None
            else (lines["close"] if lines["close"] is not None else lines["open"]),
            "method_odds": None if a is None or (a["method_odds"] is None and b["method_odds"] is None)
            else {"a": _copy_methods(a["method_odds"]), "b": _copy_methods(b["method_odds"])},
            "spread_raw": _spread_raw(item),
            "details": item.get("details"),
            "props_url": espn_urls.ref_url(item.get("propBets")),
            "sides_raw": {"home": home, "away": away},
            "source_url": source_url,
            "fetched_utc": fetched_utc,
        }
        for phase in PHASES:
            row[f"a_ml_{phase}"] = None if a is None else a[f"ml_{phase}"]
            row[f"b_ml_{phase}"] = None if b is None else b[f"ml_{phase}"]
            row[f"rounds_total_{phase}"] = lines[phase]
            row[f"over_{phase}"] = overs[phase]
            row[f"under_{phase}"] = unders[phase]
            row[f"draw_{phase}"] = draws[phase]
        rows.append(row)
    return rows


# -- fetching ------------------------------------------------------------------------------


def _parse_utc(value) -> Optional[datetime]:
    """ESPN's date form ("2026-09-27T00:00Z") as an aware UTC datetime; None for anything else."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    found = _ISO.match(str(value or "").strip())
    if not found:
        return None
    year, month, day, hour, minute, second, zone = found.groups()
    try:
        moment = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0),
                          tzinfo=timezone.utc)
    except ValueError:
        return None
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        moment -= sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return moment


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cached_before_settled(fetcher, url: str, bout: dict, settle_s: float) -> bool:
    """Is the cached copy of a final bout's odds older than the moment the bout could have ended?"""
    stamp = getattr(fetcher, "fetched_utc", None)
    cached = _parse_utc(stamp(url)) if callable(stamp) else None
    start = _parse_utc(bout.get("date_utc"))
    if cached is None or start is None:
        return False
    return cached < start + timedelta(seconds=settle_s)


def fetch_bout_odds(fetcher, bout: dict, *, fighters=None, live_max_age_s: float = LIVE_MAX_AGE_S,
                    settle_s: float = SETTLE_S, max_pages: int = MAX_PAGES) -> List[dict]:
    """The odds rows of `bout` through `fetcher` ([] when ESPN lists none, or answers 404)."""
    url = espn_urls.competition_odds(str(bout["event_id"]), str(bout["bout_id"]))
    kwargs: dict = {}
    if bout.get("status") == "final":
        if _cached_before_settled(fetcher, url, bout, settle_s):
            kwargs["use_cache"] = False
    else:
        kwargs["max_age_s"] = live_max_age_s
    items: list = []
    page = 1
    while True:
        page_url = url if page == 1 else f"{url}?page={page}"
        try:
            payload = fetcher.get_json(page_url, **kwargs)
        except http.NotFound:
            if page == 1:
                return []
            break
        items.extend((payload or {}).get("items") or [])
        try:
            page_count = int((payload or {}).get("pageCount") or 1)
        except (TypeError, ValueError):
            page_count = 1
        if page >= page_count or page >= max_pages:
            break
        page += 1
    when_fetched = getattr(fetcher, "fetched_utc", None)
    stamp = (when_fetched(url) if callable(when_fetched) else None) or _utc_now_iso()
    return parse_odds({"items": items}, bout=bout, fetched_utc=stamp, source_url=url, fighters=fighters)
