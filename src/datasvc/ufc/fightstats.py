"""Per-fight statistics: one row per fighter per bout, from ESPN's competitor statistics.

Source: `espn_urls.competitor_statistics(event, bout, athlete)`, the "All Splits" totals of
one fighter in one bout. `parse_competitor_statistics` is a pure function of that JSON and
the bout record; `fetch_bout_stats` reads both fighters of a bout through the PoliteFetcher.

`STAT_MAP` maps each ESPN statistic name to `Stat(field, unit)` (it unpacks as `field, unit`);
the units are "count", "ratio_0_1", "seconds" and "epoch_seconds". `ROLE_OF` and `NOTE_OF`
(by ESPN name) say whether it is a "measure" of the fighter, a "ratio" ESPN derived from the
counts, or "metadata", and what it is. `FIELD_OF` / `ESPN_OF` translate in both directions.

Row (fight_stats.jsonl, key bout_id + fighter_id): `bout_id`, `fighter_id`, `opponent_id`,
`event_id`, `date_utc` (all from the bout record), every `STAT_MAP` field (null when ESPN did
not send it), `stats_complete`, `source_url`, `fetched_utc`, and two fields this module adds
to the contract:

    stats_missing    the STAT_MAP fields ESPN did not send ([] when stats_complete)
    unmapped_stats   {ESPN name: value} for statistics ESPN sent that STAT_MAP does not know
                     ({} today; a new ESPN statistic lands here instead of being dropped)

What the statistics are (checked on the 22 saved payloads: 21 fighter-bouts in 16 fought bouts
between 2005 and 2026, among them the three 2026-09-26 bouts and the 2016 fixture, plus one
unfought placeholder; the tests re-run every claim):

* Counts (units "count"): strikes, takedowns, knockdowns, advances, reversals. The nine
  position x target significant-strike counts (distance, clinch, ground x head, body, leg)
  sum exactly to `sig_strikes_attempted` / `sig_strikes_landed` in every fixture;
  `total_strikes_*` count every strike (significant or not), so they are >= the sig counts.
* `targetBreakdown{Head,Body,Leg}` and `posBreakdown{Distance,Clinch,Ground}` are NOT counts
  and NOT shares of the strikes thrown. Each is the significant-strike ACCURACY, landed /
  attempted, for one target (summed over the three positions) or one position (summed over
  the three targets). Example, Raoni Barcelos 2026-09-26: head 90 landed of 180 attempted =
  0.500 (his head share of attempts is 0.807, so it is not a share); body 34/40 = 0.850.
  They are stored as `sig_head_accuracy` ... `sig_ground_accuracy` so nobody reads them as
  shares. They are redundant with the counts; recompute from the counts when it matters.
* `takedownAccuracy` = takedowns landed / attempted. `slamRate` = takedowns slams /
  takedowns attempted (Khabib Nurmagomedov 2018-04-07: 2 slams, 15 attempts, 0.133; 15 is the
  only statistic equal to that denominator; this is the only non-zero slam count among the
  fixtures, so the formula rests on one example).
* All ratios are unit "ratio_0_1" with 3 decimals. ESPN's rounding can be 0.001 off the
  exact quotient (25/46 = 0.54348 is reported 0.544). A zero denominator makes the ratio
  undefined and ESPN is inconsistent about it: 0.0 in 24 of the 26 such cases in the
  fought fixtures, 1.0 in two (2025-07 clinch, 2026-06 ground). Use `safe_ratio` on the counts.
* `submissions` counts submission ATTEMPTS, not successful submissions (stored as
  `submission_attempts`): the loser of the 2026-09-26 main event, a KO, has 5, and the
  play-by-play of bouts 401924683 and 401914466 lists 2 and 1 "Submission Attempt" events,
  equal to the statistic.
* `timeInControl` is seconds of control (displayValue is the same number as m:ss: 381 =
  6:21), stored as `control_time_s`. ESPN did not record it before 2018: it is 0 in every
  fighter-bout probed from 2005 to 2017 (both fighters in 2017) even where takedowns landed
  or ground strikes were thrown (UFC 214, 2017-07-29: Jon Jones landed 15 ground head
  strikes, control 0), and non-zero in every year probed from 2018-04-07 (633 s) on. Before
  then a 0 means "not recorded", not "no control". The first recorded date is somewhere in
  (2017-07-29, 2018-04-07].
* `wallclock` is a Unix time in UTC seconds (displayValue is the same instant as ISO text),
  stored as `wallclock_epoch_s`. It is NOT a measure of the fighter: both fighters of a bout
  carry the same value, and it is hours after the final bell (the 2026-09-27 bouts are
  stamped 05:11 to 09:38 UTC; the play-by-play of bout 401924683 ends at 01:14 UTC), so it is
  when ESPN stamped the bout's statistics. It is kept, as metadata, because it is the only
  marker that the statistics were really posted (see the placeholder below). It is also the
  43rd statistic: ESPN sent 42 in every probed bout from 2005 to 2025-07-19 and 43 in every
  probed bout from 2026-06-20 (the change is in between).

Completeness. `stats_complete` is True only when all 43 statistics are present. Every bout
from before the wallclock appeared (all the probed ones through 2025-07-19) therefore has
`stats_complete` False with `stats_missing == ["wallclock_epoch_s"]` although all 42
measures are there: for history, test the specific fields you use (or that list), not the
flag. For a recent bout the flag is meaningful: ESPN serves a full set of statistics, all
zero and without a wallclock, before it has posted the real ones.

Placeholder statistics. ESPN does not answer 404 for a bout it has no statistics for. A bout
that has not been fought (UFC 332 on 2026-10-03, saved as
`w3_competitor_401912275_4412813_statistics_upcoming.json`) returns 200 with all 42
statistics equal to 0.0. A row built from that would say a fighter landed no strikes in a
fight that has not happened. So:
`parse_competitor_statistics` refuses (ValueError) a bout whose status is scheduled,
canceled or postponed; `fetch_bout_stats` does not read a bout known to be scheduled, in
progress, canceled or postponed, and returns no rows when every payload it gets is that
all-zero, unstamped placeholder (a final bout, or one of unknown status, whose statistics
are not posted yet). A fight in which both fighters really did nothing would be dropped
the same way; there is nothing to record for it.

What a 404 produces. `fetch_bout_stats` skips a fighter whose statistics answer 404: no row,
so a bout returns 0, 1 or 2 rows and a missing row means "ESPN has none". (No 404 was seen
in the 17 bouts saved or probed, 2005 to 2026; the policy is for the day one appears.) Any other
fetch problem (FetchError, RequestCapReached, SourceBlocked) propagates. The fetcher caches a
404 without expiry, so for a bout that finished within `recent_days` the fetch passes
`max_age_s` and a stale copy (a 404, or placeholders, read before ESPN posted the real
numbers) is read again after `recent_max_age_s`; older bouts are read once.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, NamedTuple, Optional, Union

from src.datasvc import http
from src.datasvc.ufc import espn_urls

COUNT = "count"
RATIO = "ratio_0_1"
SECONDS = "seconds"
EPOCH = "epoch_seconds"

UNITS = (COUNT, RATIO, SECONDS, EPOCH)
ROLES = ("measure", "ratio", "metadata")


class Stat(NamedTuple):
    """One entry of STAT_MAP: `field, unit = STAT_MAP["knockDowns"]` works, so do `.field`, `.unit`."""
    field: str   # snake case field in the fight_stats row
    unit: str    # one of UNITS


class _Entry(NamedTuple):
    field: str
    unit: str
    role: str    # "measure" (a count or duration of what the fighter did), "ratio" (ESPN's own
                 # quotient of counts), "metadata" (not a measure of the fighter)
    note: str    # what it is, as established from the fixtures


def _c(field: str, note: str) -> _Entry:
    return _Entry(field, COUNT, "measure", note)


# ESPN statistic name -> field, unit, role, note, in the order ESPN lists them.
_TABLE: Dict[str, _Entry] = {
    "knockDowns": _c("knockdowns", "knockdowns this fighter scored"),
    "totalStrikesAttempted": _c("total_strikes_attempted", "every strike thrown, significant or not"),
    "totalStrikesLanded": _c("total_strikes_landed", "every strike landed, significant or not"),
    "sigStrikesAttempted": _c("sig_strikes_attempted", "significant strikes thrown"),
    "sigStrikesLanded": _c("sig_strikes_landed", "significant strikes landed"),
    "sigDistanceHeadStrikesAttempted": _c("sig_distance_head_strikes_attempted", "significant strikes at distance to the head, thrown"),
    "sigDistanceHeadStrikesLanded": _c("sig_distance_head_strikes_landed", "significant strikes at distance to the head, landed"),
    "sigDistanceBodyStrikesAttempted": _c("sig_distance_body_strikes_attempted", "significant strikes at distance to the body, thrown"),
    "sigDistanceBodyStrikesLanded": _c("sig_distance_body_strikes_landed", "significant strikes at distance to the body, landed"),
    "sigDistanceLegStrikesAttempted": _c("sig_distance_leg_strikes_attempted", "significant strikes at distance to the legs, thrown"),
    "sigDistanceLegStrikesLanded": _c("sig_distance_leg_strikes_landed", "significant strikes at distance to the legs, landed"),
    "sigClinchBodyStrikesAttempted": _c("sig_clinch_body_strikes_attempted", "significant strikes in the clinch to the body, thrown"),
    "sigClinchBodyStrikesLanded": _c("sig_clinch_body_strikes_landed", "significant strikes in the clinch to the body, landed"),
    "sigClinchHeadStrikesAttempted": _c("sig_clinch_head_strikes_attempted", "significant strikes in the clinch to the head, thrown"),
    "sigClinchHeadStrikesLanded": _c("sig_clinch_head_strikes_landed", "significant strikes in the clinch to the head, landed"),
    "sigClinchLegStrikesAttempted": _c("sig_clinch_leg_strikes_attempted", "significant strikes in the clinch to the legs, thrown"),
    "sigClinchLegStrikesLanded": _c("sig_clinch_leg_strikes_landed", "significant strikes in the clinch to the legs, landed"),
    "sigGroundHeadStrikesAttempted": _c("sig_ground_head_strikes_attempted", "significant ground strikes to the head, thrown"),
    "sigGroundHeadStrikesLanded": _c("sig_ground_head_strikes_landed", "significant ground strikes to the head, landed"),
    "sigGroundBodyStrikesAttempted": _c("sig_ground_body_strikes_attempted", "significant ground strikes to the body, thrown"),
    "sigGroundBodyStrikesLanded": _c("sig_ground_body_strikes_landed", "significant ground strikes to the body, landed"),
    "sigGroundLegStrikesAttempted": _c("sig_ground_leg_strikes_attempted", "significant ground strikes to the legs, thrown"),
    "sigGroundLegStrikesLanded": _c("sig_ground_leg_strikes_landed", "significant ground strikes to the legs, landed"),
    "takedownsAttempted": _c("takedowns_attempted", "takedown attempts, the landed ones included"),
    "takedownsLanded": _c("takedowns_landed", "takedowns completed"),
    "takedownsSlams": _c("takedowns_slams", "takedowns recorded as slams; non-zero in only one fixture (2 of 6 landed)"),
    "takedownAccuracy": _Entry("takedown_accuracy", RATIO, "ratio", "takedowns_landed / takedowns_attempted; zero denominator is undefined"),
    "targetBreakdownHead": _Entry("sig_head_accuracy", RATIO, "ratio",
                                  "significant strikes landed / attempted at the head over all positions (NOT a share of strikes)"),
    "targetBreakdownBody": _Entry("sig_body_accuracy", RATIO, "ratio",
                                  "significant strikes landed / attempted at the body over all positions (NOT a share of strikes)"),
    "targetBreakdownLeg": _Entry("sig_leg_accuracy", RATIO, "ratio",
                                 "significant strikes landed / attempted at the legs over all positions (NOT a share of strikes)"),
    "posBreakdownDistance": _Entry("sig_distance_accuracy", RATIO, "ratio",
                                   "significant strikes landed / attempted at distance over all targets (NOT a share of strikes)"),
    "posBreakdownClinch": _Entry("sig_clinch_accuracy", RATIO, "ratio",
                                 "significant strikes landed / attempted in the clinch over all targets (NOT a share of strikes)"),
    "posBreakdownGround": _Entry("sig_ground_accuracy", RATIO, "ratio",
                                 "significant ground strikes landed / attempted over all targets (NOT a share of strikes)"),
    "advances": _c("advances", "positional advances; equals the sum of the four advance_to_* counts in every fixture"),
    "advanceToHalfGuard": _c("advance_to_half_guard", "advances to half guard"),
    "advanceToSide": _c("advance_to_side", "advances to side control"),
    "advanceToMount": _c("advance_to_mount", "advances to mount"),
    "advanceToBack": _c("advance_to_back", "advances to the back"),
    "reversals": _c("reversals", "reversals of position"),
    "submissions": _c("submission_attempts", "submission ATTEMPTS, not successful submissions"),
    "slamRate": _Entry("slam_rate", RATIO, "ratio", "takedowns_slams / takedowns_attempted (one non-zero example); zero denominator is undefined"),
    "timeInControl": _Entry("control_time_s", SECONDS, "measure",
                            "seconds of control; 0 means not recorded before 2018 (first recorded year is in (2017-07-29, 2018-04-07])"),
    "wallclock": _Entry("wallclock_epoch_s", EPOCH, "metadata",
                        "Unix time (UTC) ESPN stamped the bout's statistics; same for both fighters; not a measure; present only from 2026"),
}

# The public map: ESPN statistic name -> Stat(field, unit). Role and note are beside it.
STAT_MAP: Dict[str, Stat] = {espn: Stat(e.field, e.unit) for espn, e in _TABLE.items()}
ROLE_OF: Dict[str, str] = {espn: e.role for espn, e in _TABLE.items()}      # by ESPN name
NOTE_OF: Dict[str, str] = {espn: e.note for espn, e in _TABLE.items()}      # by ESPN name

FIELDS = tuple(e.field for e in _TABLE.values())
MEASURE_FIELDS = tuple(e.field for e in _TABLE.values() if e.role != "metadata")      # counts, seconds and ratios
COUNT_FIELDS = tuple(e.field for e in _TABLE.values() if e.role == "measure")         # counts and seconds only
METADATA_FIELDS = tuple(e.field for e in _TABLE.values() if e.role == "metadata")
FIELD_OF = {espn: e.field for espn, e in _TABLE.items()}
ESPN_OF = {e.field: espn for espn, e in _TABLE.items()}

# A bout in one of these states has no statistics yet; ESPN still answers 200 with zeros.
UNFOUGHT_STATUSES = frozenset({"scheduled", "canceled", "postponed"})
# fetch_bout_stats does not read these (a bout in progress has partial numbers, not final ones).
UNFINISHED_STATUSES = UNFOUGHT_STATUSES | {"in_progress"}

RECENT_DAYS = 4
RECENT_MAX_AGE_S = 6 * 3600


def safe_ratio(landed, attempted) -> Optional[float]:
    """landed / attempted, or None when there were no attempts (ESPN's own 0/0 is not reliable)."""
    if landed is None or not attempted:
        return None
    return landed / attempted


def _number(value) -> Optional[Union[int, float]]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _typed(number: Optional[float], unit: str):
    """Counts, seconds and epochs are whole numbers (int); ratios stay floats."""
    if number is None:
        return None
    if unit != RATIO and float(number).is_integer():
        return int(number)
    return float(number)


def _statistics(stats_json) -> Dict[str, Optional[float]]:
    """ESPN statistic name -> its `value` (never displayValue), flattened over the categories."""
    out: Dict[str, Optional[float]] = {}
    splits = (stats_json or {}).get("splits") or {}
    for category in splits.get("categories") or []:
        for stat in category.get("stats") or []:
            name = stat.get("name")
            if not name:
                continue
            value = _number(stat.get("value"))
            if name in out and out[name] != value:
                raise ValueError(f"statistic {name!r} appears twice with different values ({out[name]} and {value})")
            out.setdefault(name, value)
    return out


def _check_reference(stats_json, bout: dict, fighter_id: str) -> None:
    """The payload must be this fighter's statistics in this bout (its own $ref says which)."""
    ref = (stats_json or {}).get("$ref")
    if not ref:
        return
    for kind, expected in (("event", bout.get("event_id")), ("competition", bout.get("bout_id")),
                           ("competitor", fighter_id)):
        found = espn_urls.id_from_ref(ref, kind)
        if found is not None and expected is not None and found != str(expected):
            raise ValueError(f"statistics payload is for {kind} {found}, not {expected}: {ref}")


def parse_competitor_statistics(stats_json, *, bout: dict, fighter_id, fetched_utc: str, source_url: str) -> dict:
    """One fight_stats row from ESPN's statistics JSON for `fighter_id` in `bout`.

    `bout` is a bouts.jsonl record (bout_id, event_id, date_utc, fighter_a_id, fighter_b_id, status).
    Raises ValueError for a fighter who is not in the bout, a payload that belongs to another
    bout or fighter, and a bout that has not been fought (ESPN answers those with zeros).
    """
    fighter_id = str(fighter_id)
    side_a = None if bout.get("fighter_a_id") is None else str(bout["fighter_a_id"])
    side_b = None if bout.get("fighter_b_id") is None else str(bout["fighter_b_id"])
    if fighter_id == side_a:
        opponent_id = side_b
    elif fighter_id == side_b:
        opponent_id = side_a
    else:
        raise ValueError(f"fighter {fighter_id} is not in bout {bout.get('bout_id')} ({side_a} vs {side_b})")
    if bout.get("status") in UNFOUGHT_STATUSES:
        raise ValueError(f"bout {bout.get('bout_id')} is {bout['status']}: ESPN serves zeros for a bout "
                         "that has not been fought, and a row of zeros would be invented data")
    _check_reference(stats_json, bout, fighter_id)

    values = _statistics(stats_json)
    row = {"bout_id": str(bout["bout_id"]), "fighter_id": fighter_id, "opponent_id": opponent_id,
           "event_id": None if bout.get("event_id") is None else str(bout["event_id"]),
           "date_utc": bout.get("date_utc")}
    missing: List[str] = []
    for espn_name, stat in STAT_MAP.items():
        value = _typed(values.get(espn_name), stat.unit)
        row[stat.field] = value
        if value is None:
            missing.append(stat.field)
    row["stats_complete"] = not missing
    row["stats_missing"] = missing
    row["unmapped_stats"] = {name: _typed(values[name], COUNT) for name in sorted(values)
                             if name not in STAT_MAP and values[name] is not None}
    row["source_url"] = source_url
    row["fetched_utc"] = fetched_utc
    return row


def is_placeholder(row: dict) -> bool:
    """True for ESPN's "not posted yet" payload: every count and duration exactly 0, no wallclock.

    The ratios are ignored (they are derived, and ESPN's 0/0 is 0.0 in most payloads and 1.0
    in a few). One fighter can really have thrown and attempted nothing, so judge a bout by
    all its rows.
    """
    if any(row.get(field) is not None for field in METADATA_FIELDS):
        return False
    return all(row.get(field) == 0 for field in COUNT_FIELDS)


# -- fetching ----------------------------------------------------------------------


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def _parse_utc(value) -> Optional[datetime]:
    """ESPN's date form ("2026-09-27T00:00Z"), with or without seconds, as an aware UTC datetime.

    None for anything that is not a date."""
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


def _is_recent(bout: dict, now, days: float) -> bool:
    """Did the bout happen within `days` of `now`? An unreadable date counts as recent (read it fresh)."""
    when = _parse_utc(bout.get("date_utc"))
    if when is None:
        return True
    current = _parse_utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError(f"`now` is not a date: {now!r}")
    return (current - when) <= timedelta(days=days)


def fetch_bout_stats(fetcher, bout: dict, *, now=None, recent_days: float = RECENT_DAYS,
                     recent_max_age_s: float = RECENT_MAX_AGE_S, skip_unfinished: bool = True) -> List[dict]:
    """The fight_stats rows of both fighters of `bout` (fighter a first), through `fetcher`.

    Returns [] without a request for a bout known to be scheduled, in progress, canceled or
    postponed (`skip_unfinished`; a missing or "unknown" status is read, and the placeholder
    check below covers it); skips a fighter whose statistics answer 404 (no row); returns []
    when every payload is ESPN's all-zero placeholder. See the module docstring for why, and
    for the refresh of recent bouts.
    """
    if skip_unfinished and bout.get("status") in UNFINISHED_STATUSES:
        return []
    event_id, bout_id = str(bout["event_id"]), str(bout["bout_id"])
    max_age_s = recent_max_age_s if _is_recent(bout, now, recent_days) else None
    when_fetched = getattr(fetcher, "fetched_utc", None)
    rows: List[dict] = []
    for fighter_id in (bout.get("fighter_a_id"), bout.get("fighter_b_id")):
        if not fighter_id:
            continue
        url = espn_urls.competitor_statistics(event_id, bout_id, str(fighter_id))
        try:
            payload = fetcher.get_json(url, max_age_s=max_age_s)
        except http.NotFound:
            continue
        stamp = (when_fetched(url) if callable(when_fetched) else None) or _utc_now_iso()
        rows.append(parse_competitor_statistics(payload, bout=bout, fighter_id=fighter_id,
                                                fetched_utc=stamp, source_url=url))
    if rows and all(is_placeholder(row) for row in rows):
        return []
    return rows
