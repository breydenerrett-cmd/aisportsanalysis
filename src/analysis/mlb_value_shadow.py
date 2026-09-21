"""MLB_VALUE_SHADOW_V1 -- a SHADOW forward test of value prices on MLB.

WHAT IT IS
----------
Owner direction, 2026-09-20: MLB's focus is batter TOTAL BASES and HITS
props, then RUN LINES; forward-test strategies every day for every bet type
and show which work; never a price at -200 or worse; find value, not
favourites. This module forward-tests ONE strategy -- the NFL_CARD_V2
leave-one-book-out value rule (src/analysis/lobo_value.py) -- on four MLB bet
types, each as its own ARM with its own rule id, its own ledger and its own
record. Arms are never pooled. Registration, constants and grading:
docs/PREREG_MLB_VALUE_SHADOW_V1.md.

  A_TOTAL_BASES  batter total bases, over and under
  B_HITS         batter hits, over and under (thin consensus -- see prereg)
  C_RUN_LINE     the MLB `spreads` market (normally +/-1.5), both sides
  D_GAME_TOTAL   the game total, over and under

WHAT IT IS NOT
--------------
  * Not on any customer surface. Nothing in api/ or src/report imports this
    module (tests/test_mlb_value_shadow.py greps for it), no row it writes
    is read by the card, and every decision row carries
    `customer_surface: false`.
  * Not the MLB V1 card. DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1 and
    evidence/cards_v1.jsonl are never read or written here.
  * Not the engine. No system, decision, paper wager or scorecard is
    touched.
  * No spend. It reads prices the capture already stored
    (batter_props.jsonl, odds_multibook.jsonl) and never imports a
    provider module, so it cannot make a network call.
  * Not a prediction. The fair price comes from the other books. A decision
    says "this book is paying more than the rest of the market thinks this
    is worth", nothing more.

THE DECISION (publish, run every capture slot)
----------------------------------------------
For each arm, for games on the given ET date whose first pitch is within
LOCK_LEAD_HOURS and still in the future: build each book's latest quote,
judge every fresh board with the LOBO rule, keep the best-EV candidate per
key -- (game_pk, player) for props, game_pk for C and D -- and write it
immediately as the decision of record. A key once written is final: later
runs skip it whatever its line has moved to. At most MAX_PER_DATE decisions
per arm per date; overflow is counted, never silently dropped. Games whose
odds event maps to no game_pk, or to an ambiguous one (doubleheaders), are
skipped and counted.

GRADING (settle, run by the daily loop)
---------------------------------------
From the box-score store (data/processed/boxscores_<yyyy>.jsonl), indexed by
game_pk so a suspended game that ends on a later date still grades:
  * a game whose linescore lists fewer than REGULATION_INNINGS innings (called
    early, "Completed Early") is VOID "game shortened" on EVERY arm.
  * props: the batter row whose accent-and-suffix-normalised name uniquely
    matches in that game; only if none does, a unique same-surname
    first-name-prefix match ("Leonardo" / "Leo"). Stat vs line. No row (or 0
    plate appearances): VOID "did not bat". Two matches: VOID "ambiguous
    name". The settled row records which join was used.
  * run line and total: the final score is the sum of the linescore's
    innings. If data/historical/mlb_results.csv also carries the game and
    disagrees, the decision stays unsettled (MISMATCH).
  * No final yet: unsettled, retried next run; VOID only once the decision
    date is VOID_AFTER_DAYS old.
The settle printout is COUNTS ONLY. The per-arm record is `record`.

GAME-LINE QUOTES (arms C, D)
----------------------------
Only rows from the board's newest capture instant are quoted: a book the
feed stopped returning has no live price (rows_at_newest_capture).

ONE ARM FAILS ALONE
-------------------
publish, settle, record and verify handle each arm separately: an arm whose
ledger cannot be read prints "<ARM>: ERROR ..." and the command exits 1, but
every other arm still runs.

ONE WRITER PER FILE
-------------------
The capture slot (forward-capture concurrency group) is the only writer of
<arm>_decisions.jsonl and <arm>_scans.jsonl; the daily loop (its own group)
is the only writer of <arm>_settled.jsonl. The two jobs run concurrently and
both commit; two writers appending to one file would conflict at
`git pull --rebase` and fork the hash chain.

CLI
---
  python3 -m src.analysis.mlb_value_shadow publish --date YYYY-MM-DD [--now ISO] [--dry-run] [--ledger-dir DIR]
  python3 -m src.analysis.mlb_value_shadow settle --recent [--now ISO] [--dry-run] [--ledger-dir DIR]
  python3 -m src.analysis.mlb_value_shadow record [--ledger-dir DIR]
  python3 -m src.analysis.mlb_value_shadow verify [--ledger-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from src.analysis import lobo_value as lobo
from src.core import odds as odds_math
from src.core.asof import game_pk_key
from src.ledger.chain import HashChainLedger, ROW_HASH_FIELD
from src.paths import evidence_path, historical_path, processed_path

FAMILY = "MLB_VALUE_SHADOW_V1"
SCHEMA_VERSION = "mlb_value_shadow_v1.0"

# ---------------------------------------------------------------------------
# REGISTERED CONSTANTS -- docs/PREREG_MLB_VALUE_SHADOW_V1.md. Any change is a
# new rule id with its own registration and record, never an edit here.
# tests/test_mlb_value_shadow.py pins each arm's constants_sha256 to the
# value printed in the prereg.
# ---------------------------------------------------------------------------
WORST_PRICE = -200            # owner ruling 2026-09-20; -199 passes, -200 never
MIN_EV = 0.02                 # under proportional, Shin AND power; lowest reported
FRESH_SECONDS = 30 * 60       # each book within 30 min of the board's newest quote
FRESH_BOARD_SECONDS = 60 * 60  # board's newest quote within 60 min of the run
MIN_OTHER_BOOKS = 5           # arms A, C, D (NFL_CARD_V2's value)
MIN_OTHER_BOOKS_HITS = 2      # arm B only: at most 4 books quote hits two-way
LOCK_LEAD_HOURS = 4.0         # decide only inside [first pitch - 4h, first pitch)
MAX_PER_DATE = 15             # per arm per ET date; a flood guard, overflow counted
VOID_AFTER_DAYS = 7           # no final after this many days: VOID "no final"
STAKE_UNITS = 1.0             # flat
REGULATION_INNINGS = 9        # fewer innings in the linescore: VOID "game shortened", every arm
NAME_PREFIX_MIN_LETTERS = 3   # the prop name-join fallback's shortest first-name prefix

KIND_DECISION = "decision"
KIND_SCAN = "scan"
KIND_SETTLED = "settled"

RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_PUSH = "PUSH"
RESULT_VOID = "VOID"

LABEL_THIN = "THIN_CONSENSUS"

SOURCE_PROPS = "batter_props"
SOURCE_MULTIBOOK = "odds_multibook"

GRADE_PROP = "prop"
GRADE_RUN_LINE = "run_line"
GRADE_TOTAL = "game_total"


def _params(min_other_books: int) -> lobo.LoboParams:
    return lobo.LoboParams(
        min_other_books=min_other_books,
        min_ev=MIN_EV,
        fresh_seconds=FRESH_SECONDS,
        fresh_board_seconds=FRESH_BOARD_SECONDS,
        worst_price=WORST_PRICE,
        devig_methods=lobo.DEVIG_METHODS,
    )


@dataclass(frozen=True)
class Arm:
    name: str
    rule_id: str
    source: str
    market: str
    grade_as: str
    params: lobo.LoboParams
    box_stat: Optional[str] = None
    label: Optional[str] = None

    def constants(self) -> dict:
        """Everything that defines this arm's decisions and grading. Its
        sha256 is written on every decision row and printed in the prereg."""
        return {
            "family": FAMILY,
            "rule_id": self.rule_id,
            "arm": self.name,
            "source_store": self.source,
            "market": self.market,
            "grade_as": self.grade_as,
            "box_stat": self.box_stat,
            "label": self.label,
            **self.params.as_dict(),
            "lock_lead_hours": LOCK_LEAD_HOURS,
            "max_per_date": MAX_PER_DATE,
            "void_after_days": VOID_AFTER_DAYS,
            "stake_units": STAKE_UNITS,
            "regulation_innings": REGULATION_INNINGS,
            "name_prefix_min_letters": (NAME_PREFIX_MIN_LETTERS
                                        if self.source == SOURCE_PROPS else None),
        }

    def constants_sha256(self) -> str:
        return lobo.canonical_sha256(self.constants())


ARMS = (
    Arm(name="A_TOTAL_BASES", rule_id=f"{FAMILY}_A_TOTAL_BASES",
        source=SOURCE_PROPS, market="batter_total_bases", grade_as=GRADE_PROP,
        params=_params(MIN_OTHER_BOOKS), box_stat="total_bases"),
    Arm(name="B_HITS", rule_id=f"{FAMILY}_B_HITS",
        source=SOURCE_PROPS, market="batter_hits", grade_as=GRADE_PROP,
        params=_params(MIN_OTHER_BOOKS_HITS), box_stat="h", label=LABEL_THIN),
    Arm(name="C_RUN_LINE", rule_id=f"{FAMILY}_C_RUN_LINE",
        source=SOURCE_MULTIBOOK, market="spreads", grade_as=GRADE_RUN_LINE,
        params=_params(MIN_OTHER_BOOKS)),
    Arm(name="D_GAME_TOTAL", rule_id=f"{FAMILY}_D_GAME_TOTAL",
        source=SOURCE_MULTIBOOK, market="totals", grade_as=GRADE_TOTAL,
        params=_params(MIN_OTHER_BOOKS)),
)
ARMS_BY_NAME = {arm.name: arm for arm in ARMS}


# ---------------------------------------------------------------------------
# Paths (resolved at call time so AISPORTS_DATA_DIR and tests can redirect)
# ---------------------------------------------------------------------------

def default_ledger_dir() -> Path:
    return evidence_path("mlb_value_shadow_v1")


def decisions_path(ledger_dir, arm: Arm) -> Path:
    return Path(ledger_dir) / f"{arm.name}_decisions.jsonl"


def scans_path(ledger_dir, arm: Arm) -> Path:
    return Path(ledger_dir) / f"{arm.name}_scans.jsonl"


def settled_path(ledger_dir, arm: Arm) -> Path:
    return Path(ledger_dir) / f"{arm.name}_settled.jsonl"


def default_props_path() -> Path:
    return processed_path("batter_props.jsonl")


def default_multibook_path() -> Path:
    return processed_path("odds_multibook.jsonl")


def default_map_path() -> Path:
    return processed_path("event_game_map.jsonl")


def default_box_path(year: str) -> Path:
    return processed_path(f"boxscores_{year}.jsonl")


def default_results_path() -> Path:
    return historical_path("mlb_results.csv")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _iso(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _eastern():
    """America/New_York, with the same fixed -04:00 fallback as
    src/pipeline/snapshots.py for tzdata-less containers."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def official_date(commence_time) -> str:
    """MLB's (Eastern) calendar date for a first pitch -- the same rule as
    src.pipeline.snapshots.official_date, re-stated here so this module
    never imports the capture module (which imports the odds provider)."""
    if commence_time is None:
        return ""
    text = str(commence_time).strip()
    if len(text) == 10:
        return text
    moment = lobo.parse_utc(text)
    if moment is None:
        return text[:10]
    return moment.astimezone(_EASTERN).date().isoformat()


_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})


def norm_name(name) -> str:
    """Player-name key for joining a prop to the box score: accents
    stripped (NFKD), lower case, "(2002)"-style parentheses dropped, periods
    and apostrophes dropped, hyphens as spaces, trailing Jr/Sr/II/III/IV
    dropped, single-spaced."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    for ch in (".", "'", "’", "`"):
        text = text.replace(ch, "")
    text = text.replace("-", " ").replace(",", " ")
    tokens = text.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


NAME_JOIN_EXACT = "exact"
NAME_JOIN_PREFIX = "first_name_prefix"


def first_name_prefix_match(a: str, b: str) -> bool:
    """The grading join's fallback, for two NORMALISED names: the same
    surname tokens, different first names, and one first name a prefix of
    the other of at least NAME_PREFIX_MIN_LETTERS letters ("leo bernal" /
    "leonardo bernal"). Never a different first name ("colson montgomery" /
    "braden montgomery"), never an initial, never a one-token name."""
    ta, tb = str(a or "").split(), str(b or "").split()
    if len(ta) < 2 or len(tb) < 2 or ta[1:] != tb[1:] or ta[0] == tb[0]:
        return False
    short, long_ = sorted((ta[0], tb[0]), key=len)
    return len(short) >= NAME_PREFIX_MIN_LETTERS and long_.startswith(short)


def _line_text(value) -> Optional[str]:
    number = lobo.to_float(value)
    if number is None:
        return None
    return f"{number:g}"


def _iter_jsonl(path, *, needle_groups: Sequence[Sequence[str]] = (), keep=None):
    """Stream a JSONL store. `needle_groups` is a text prefilter that may
    only over-match: a line is parsed only if, for EVERY group, it contains
    at least one of that group's needles. `keep` is the exact check on the
    parsed row. Corrupt lines are skipped."""
    target = Path(path)
    if not target.exists():
        return
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            if needle_groups and not all(any(n in line for n in group)
                                         for group in needle_groups):
                continue
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if keep is not None and not keep(row):
                continue
            yield row


def _date_needles(date: str) -> tuple:
    """A game on ET date D starts on UTC date D or D+1, so every row for it
    carries one of those two strings. Bare dates, no key or spacing -- a
    prefilter must never under-match (src/pipeline/snapshots.py records the
    incident where it did)."""
    day = date_cls.fromisoformat(date)
    return (day.isoformat(), (day + timedelta(days=1)).isoformat())


def _observed_by(row: Mapping, now: datetime) -> bool:
    seen = lobo.parse_utc(row.get("observed_utc"))
    return seen is not None and seen <= now


# ---------------------------------------------------------------------------
# Store readers
# ---------------------------------------------------------------------------

def load_game_map(path=None) -> dict:
    """{event_id: row}, last write wins -- src.board.gamekey.load_map's rule,
    re-stated so this module never imports gamekey (which imports the MLB
    provider). tests/test_mlb_value_shadow.py pins the two together."""
    out: dict = {}
    for row in _iter_jsonl(path or default_map_path()):
        event_id = row.get("event_id")
        if event_id is not None:
            out[str(event_id)] = row
    return out


def map_event(event_id, game_map: Mapping) -> tuple:
    """(game_pk or None, skip reason or None)."""
    entry = game_map.get(str(event_id)) if event_id is not None else None
    if not entry:
        return None, "unmapped"
    gpk = game_pk_key(entry.get("game_pk"))
    if gpk is None:
        return None, "unmapped"
    if entry.get("ambiguous"):
        return None, "ambiguous"
    return gpk, None


def read_prop_rows(date: str, *, now: datetime, markets: Sequence[str],
                   path=None) -> list:
    """batter_props rows for games on ET `date`, in `markets`, observed by
    `now`."""
    market_set = set(markets)
    groups = (tuple(f'"{m}"' for m in markets), _date_needles(date))

    def keep(row):
        return (row.get("market") in market_set
                and official_date(row.get("commence_time")) == date
                and _observed_by(row, now))

    return list(_iter_jsonl(path or default_props_path(), needle_groups=groups, keep=keep))


def read_multibook_rows(date: str, *, now: datetime, markets: Sequence[str],
                        path=None) -> list:
    """MLB odds_multibook rows (no `sport` key, or sport "mlb") for games on
    ET `date`, in `markets`, observed by `now`."""
    market_set = set(markets)
    groups = (tuple(f'"{m}"' for m in markets), _date_needles(date))

    def keep(row):
        return (row.get("market") in market_set
                and (row.get("sport") or "mlb") == "mlb"
                and official_date(row.get("commence_time")) == date
                and _observed_by(row, now))

    return list(_iter_jsonl(path or default_multibook_path(), needle_groups=groups, keep=keep))


# ---------------------------------------------------------------------------
# Prop adapter: batter_props rows -> LOBO quotes
# ---------------------------------------------------------------------------

def prop_boards(rows: Iterable[Mapping], *, now: datetime) -> dict:
    """{(event_id, market): [quote]} from batter_props rows.

    A book's quote set is its NEWEST observation of that game and market:
    every row captured at that instant. (The store only writes a row when
    the book's update stamp changed, so an older observation's rows are the
    book's current quote until a newer one exists.) Within it, one player at
    one line is two-way only with exactly one Over and one Under row; a
    one-sided book (betrivers quotes Over only) or a duplicated row gives a
    quote with pair None -- never judged, never in a consensus, but its time
    still counts toward the board's freshness, as in nfl_value.

    line_key is (normalised player, line), so a book is compared only with
    books quoting the same player at the same number.
    """
    newest: dict = {}
    for row in rows:
        seen = lobo.parse_utc(row.get("observed_utc"))
        if seen is None:
            continue
        key = (row.get("event_id"), row.get("market"), row.get("book"))
        if key not in newest or seen > newest[key]:
            newest[key] = seen

    grouped: dict = defaultdict(lambda: defaultdict(lambda: {"over": [], "under": []}))
    for row in rows:
        key = (row.get("event_id"), row.get("market"), row.get("book"))
        seen = lobo.parse_utc(row.get("observed_utc"))
        if seen is None or seen != newest.get(key):
            continue
        kickoff = lobo.parse_utc(row.get("commence_time"))
        if kickoff is None or kickoff <= now:
            continue
        line_text = _line_text(row.get("line"))
        player_norm = norm_name(row.get("player"))
        side = str(row.get("side") or "").strip().lower()
        if line_text is None or not player_norm or side not in ("over", "under"):
            continue
        grouped[key][(player_norm, line_text)][side].append(row)

    boards: dict = defaultdict(list)
    for (event_id, market, book), by_line in grouped.items():
        for (player_norm, line_text), sides in by_line.items():
            overs, unders = sides["over"], sides["under"]
            sample = (overs or unders)[0]
            pair = None
            if len(overs) == 1 and len(unders) == 1:
                line = float(line_text)
                pair = (("over", line, overs[0].get("price")),
                        ("under", line, unders[0].get("price")))
            times = [lobo.quote_time(r) for r in overs + unders]
            times = [t for t in times if t is not None]
            boards[(event_id, market)].append({
                "book": book,
                "line_key": (player_norm, line_text),
                "pair": pair,
                "quote_time": min(times) if times else None,
                "meta": {
                    "event_id": event_id,
                    "market": market,
                    "player": sample.get("player"),
                    "player_norm": player_norm,
                    "line_text": line_text,
                    "home_team": sample.get("home_team"),
                    "away_team": sample.get("away_team"),
                    "commence_time": sample.get("commence_time"),
                    "observed_utc": sample.get("observed_utc"),
                    "book_last_update": sample.get("book_last_update"),
                    "capture_phase": sample.get("capture_phase"),
                },
            })
    return boards


def rows_at_newest_capture(rows: Iterable[Mapping]) -> list:
    """Game-line rows from each board's (game and market's) newest capture
    instant only.

    The multi-book store writes every book the feed returns at every
    capture (src/pipeline/snapshots.py multibook_rows), so a book missing
    from the board's newest capture was not quoting that market then -- it
    was pulled (a listed-pitcher change, weather) or dropped by the feed.
    Its older row is not a live price and is never quoted: not judged, not
    in anyone's consensus. The MLB counterpart of the prop adapter's "a
    player the book no longer lists at its newest observation is not quoted
    by that book". lobo_value.multibook_boards is left as NFL_CARD_V2 has it
    (its parity test pins that); this filter runs before it, for MLB only.
    """
    rows = list(rows)
    newest: dict = {}
    for row in rows:
        seen = lobo.parse_utc(row.get("observed_utc"))
        if seen is None:
            continue
        key = (row.get("event_id"), row.get("market") or "h2h")
        if key not in newest or seen > newest[key]:
            newest[key] = seen
    out = []
    for row in rows:
        seen = lobo.parse_utc(row.get("observed_utc"))
        key = (row.get("event_id"), row.get("market") or "h2h")
        if seen is not None and seen == newest.get(key):
            out.append(row)
    return out


def boards_for_arm(arm: Arm, rows: Iterable[Mapping], *, now: datetime) -> dict:
    rows = [r for r in rows if r.get("market") == arm.market]
    if arm.source == SOURCE_PROPS:
        return prop_boards(rows, now=now)
    return lobo.multibook_boards(rows_at_newest_capture(rows), now=now, markets=(arm.market,))


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

def _empty_counts() -> dict:
    return {
        "boards_seen": 0,             # upcoming game-and-market boards on the date
        "boards_outside_window": 0,   # first pitch more than LOCK_LEAD_HOURS away
        "boards_stale": 0,            # in window, newest quote over an hour old
        "boards_judged": 0,           # in window and fresh
        "lines_judged": 0,            # book-lines with enough other books
        "candidates": 0,              # book-line-sides clearing the bar
        "keys": 0,                    # distinct decision keys among them
        "held": 0,                    # keys already decided (lock is final)
        "skipped_unmapped": 0,        # key's game has no game_pk
        "skipped_ambiguous": 0,       # key's game_pk is an ambiguous match
        "capped": 0,                  # new keys over MAX_PER_DATE
        "new_decisions": 0,
    }


def decision_key(arm: Arm, game_pk: str, player_norm: Optional[str]) -> str:
    if arm.source == SOURCE_PROPS:
        return f"{arm.name}|{game_pk}|{player_norm}"
    return f"{arm.name}|{game_pk}"


def _rank_key(cand: Mapping) -> tuple:
    """Highest EV first; deterministic tie-breaks so a rerun on the same
    rows always picks the same candidate."""
    return (-cand["ev"], -cand["n_other_books"], str(cand["book"]),
            str(cand["side"]), float(cand["line"] if cand["line"] is not None else 0.0))


def decide_arm(arm: Arm, boards: Mapping, *, now: datetime, date: str,
               game_map: Mapping, held_keys: set, decided_on_date: int) -> tuple:
    """(new decision rows, counts). Pure: the caller appends the rows."""
    counts = _empty_counts()
    lock_seconds = LOCK_LEAD_HOURS * 3600.0
    best: dict = {}
    for (event_id, _market), quotes in sorted(boards.items(), key=lambda kv: str(kv[0])):
        kickoffs = [lobo.parse_utc(q["meta"].get("commence_time")) for q in quotes]
        kickoffs = [k for k in kickoffs if k is not None and k > now]
        if not kickoffs:
            continue
        first_pitch = min(kickoffs)
        counts["boards_seen"] += 1
        if (first_pitch - now).total_seconds() > lock_seconds:
            counts["boards_outside_window"] += 1
            continue
        judged = lobo.judge_board(quotes, now=now, params=arm.params)
        if not judged["fresh"]:
            counts["boards_stale"] += 1
            continue
        counts["boards_judged"] += 1
        counts["lines_judged"] += judged["lines_judged"]
        counts["candidates"] += len(judged["candidates"])
        if not judged["candidates"]:
            continue
        board_newest = lobo.newest_quote_time(quotes)
        game_pk, skip = map_event(event_id, game_map)
        for cand in judged["candidates"]:
            meta = cand["meta"]
            if skip is not None:
                cand_key = (skip, event_id, meta.get("player_norm"))
            else:
                cand_key = decision_key(arm, game_pk, meta.get("player_norm"))
            entry = dict(cand, game_pk=game_pk, skip=skip, first_pitch=first_pitch,
                         board_newest=board_newest)
            if cand_key not in best or _rank_key(entry) < _rank_key(best[cand_key]):
                best[cand_key] = entry

    counts["keys"] = len(best)
    fresh_keys = []
    for cand_key, entry in best.items():
        if entry["skip"] == "unmapped":
            counts["skipped_unmapped"] += 1
        elif entry["skip"] == "ambiguous":
            counts["skipped_ambiguous"] += 1
        elif cand_key in held_keys:
            counts["held"] += 1
        else:
            fresh_keys.append((cand_key, entry))

    fresh_keys.sort(key=lambda kv: _rank_key(kv[1]))
    room = max(0, MAX_PER_DATE - decided_on_date)
    rows = []
    for cand_key, entry in fresh_keys:
        if len(rows) >= room:
            counts["capped"] += 1
            continue
        rows.append(_decision_row(arm, cand_key, entry, now=now, date=date))
    counts["new_decisions"] = len(rows)
    return rows, counts


def _decision_row(arm: Arm, key: str, entry: Mapping, *, now: datetime, date: str) -> dict:
    meta = entry["meta"]
    price = entry["price"]
    line = float(entry["line"])
    return {
        "kind": KIND_DECISION,
        "family": FAMILY,
        "rule_id": arm.rule_id,
        "arm": arm.name,
        "schema_version": SCHEMA_VERSION,
        "constants_sha256": arm.constants_sha256(),
        "customer_surface": False,
        "label": arm.label,
        "recorded_utc": _iso(now),
        "decision_key": key,
        "date": date,
        "event_id": meta.get("event_id"),
        "game_pk": entry["game_pk"],
        "home_team": meta.get("home_team"),
        "away_team": meta.get("away_team"),
        "first_pitch_utc": _iso(entry["first_pitch"]),
        "minutes_to_first_pitch": round((entry["first_pitch"] - now).total_seconds() / 60.0, 1),
        "market": arm.market,
        "player": meta.get("player"),
        "player_norm": meta.get("player_norm"),
        "line": line,
        "line_text": meta.get("line_text") or f"{line:g}",
        "side": entry["side"],
        "price": price,
        "decimal_price": odds_math.american_to_decimal(price),
        "book": entry["book"],
        "fair_probability": entry["fair_probability"],
        "ev": entry["ev"],
        "devig_method": entry["devig_method"],
        "ev_by_method": entry["ev_by_method"],
        "fair_by_method": entry["fair_by_method"],
        "n_other_books": entry["n_other_books"],
        "other_books": entry["other_books"],
        "quote_time": _iso(entry["quote_time"]),
        "quote_observed_utc": meta.get("observed_utc"),
        "board_newest_utc": _iso(entry["board_newest"]),
        "capture_phase": meta.get("capture_phase"),
        "stake_units": STAKE_UNITS,
    }


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------

def _rows_of_kind(path: Path, kind: str) -> list:
    return [r for r in HashChainLedger(path).read() if r.get("kind") == kind]


def _last_scan_counts(path: Path, date: str) -> Optional[dict]:
    last = None
    for row in _rows_of_kind(path, KIND_SCAN):
        if row.get("date") == date:
            last = row.get("counts")
    return last


def publish(date: str, *, now: Optional[datetime] = None, dry_run: bool = False,
            ledger_dir=None, arms: Optional[Sequence[str]] = None,
            props_path=None, multibook_path=None, map_path=None) -> dict:
    """Judge every selected arm for ET `date` at `now` and (unless dry_run)
    append new decisions and a scan row. Returns {arm: {counts, decisions}}.

    Each arm runs on its own: an arm whose ledger cannot be read or
    appended (a line JSON cannot parse -- a leftover conflict marker, a
    truncated append) comes back as {"error": ...} and the others still
    run. The CLI prints the error and exits non-zero.
    """
    date_cls.fromisoformat(date)  # refuse a malformed date before any read
    now = now or datetime.now(timezone.utc)
    ledger_dir = Path(ledger_dir) if ledger_dir else default_ledger_dir()
    selected = [ARMS_BY_NAME[name] for name in (arms or [a.name for a in ARMS])]

    game_map = load_game_map(map_path)
    prop_markets = [a.market for a in selected if a.source == SOURCE_PROPS]
    line_markets = [a.market for a in selected if a.source == SOURCE_MULTIBOOK]
    prop_rows = (read_prop_rows(date, now=now, markets=prop_markets, path=props_path)
                 if prop_markets else [])
    line_rows = (read_multibook_rows(date, now=now, markets=line_markets, path=multibook_path)
                 if line_markets else [])

    summary = {}
    for arm in selected:
        rows = prop_rows if arm.source == SOURCE_PROPS else line_rows
        try:
            summary[arm.name] = _publish_arm(arm, rows, now=now, date=date, dry_run=dry_run,
                                             ledger_dir=ledger_dir, game_map=game_map)
        except Exception as exc:  # noqa: BLE001 -- one arm's broken file must not stop the rest
            summary[arm.name] = {"error": _error_text(exc), "counts": None, "decisions": []}
    return summary


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _publish_arm(arm: Arm, rows, *, now: datetime, date: str, dry_run: bool,
                 ledger_dir: Path, game_map: Mapping) -> dict:
    boards = boards_for_arm(arm, rows, now=now)
    existing = _rows_of_kind(decisions_path(ledger_dir, arm), KIND_DECISION)
    held = {r.get("decision_key") for r in existing}
    on_date = sum(1 for r in existing if r.get("date") == date)
    decisions, counts = decide_arm(arm, boards, now=now, date=date, game_map=game_map,
                                   held_keys=held, decided_on_date=on_date)
    written = []
    if not dry_run:
        ledger = HashChainLedger(decisions_path(ledger_dir, arm))
        for row in decisions:
            written.append(ledger.append(row))
        spath = scans_path(ledger_dir, arm)
        if _last_scan_counts(spath, date) != counts:
            HashChainLedger(spath).append({
                "kind": KIND_SCAN, "family": FAMILY, "rule_id": arm.rule_id,
                "arm": arm.name, "schema_version": SCHEMA_VERSION,
                "date": date, "recorded_utc": _iso(now), "counts": counts,
            })
    return {"counts": counts, "decisions": written if not dry_run else decisions}


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------

@dataclass
class BoxIndex:
    batters: dict      # {(game_pk, norm_name): {player_id: row}}
    finals: dict       # {game_pk: set of (away_runs, home_runs, innings listed)}


def load_box_index(years: Iterable[str], *, box_paths: Optional[Mapping] = None) -> BoxIndex:
    """Index the box-score store(s) by game_pk (never by date, so a game
    suspended and finished on a later date still grades). Batter rows are
    de-duplicated by player_id within a game so a re-ingested game cannot
    turn one player into an "ambiguous name".

    A final carries the number of innings its linescore lists, because the
    ingest treats "Completed Early" (a game called after 5 innings) as final
    and writes only the innings played. The store writes an unplayed bottom
    half as 0 runs, so a game the home side won without batting in the 9th
    lists 9 innings: the count cannot tell 8.5 from 9, and it does not need
    to -- both are regulation."""
    batters: dict = defaultdict(dict)
    finals: dict = defaultdict(set)
    for year in sorted(set(years)):
        # Injected paths are the whole world: a year they do not name is
        # read from nowhere, never from the default store.
        path = box_paths.get(year) if box_paths is not None else default_box_path(year)
        if path is None:
            continue
        for row in _iter_jsonl(path):
            gpk = game_pk_key(row.get("game_pk"))
            if gpk is None:
                continue
            kind = row.get("type")
            if kind == "batter":
                pid = row.get("player_id")
                ident = pid if pid is not None else ("name", row.get("player_name"))
                batters[(gpk, norm_name(row.get("player_name")))][ident] = row
            elif kind == "linescore":
                innings = row.get("innings") or []
                if not innings:
                    continue
                away = sum(int(i.get("away_runs") or 0) for i in innings)
                home = sum(int(i.get("home_runs") or 0) for i in innings)
                finals[gpk].add((away, home, len(innings)))
    return BoxIndex(batters=dict(batters), finals=dict(finals))


def load_results_scores(path=None) -> dict:
    """{game_pk: (away_score, home_score)} from mlb_results.csv, for the
    cross-check only. Missing file: empty."""
    target = Path(path) if path else default_results_path()
    out: dict = {}
    if not target.exists():
        return out
    with target.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            gpk = game_pk_key(row.get("game_pk"))
            try:
                away, home = int(row.get("away_score")), int(row.get("home_score"))
            except (TypeError, ValueError):
                continue
            if gpk is not None:
                out[gpk] = (away, home)
    return out


def _void(reason: str) -> dict:
    return {"result": RESULT_VOID, "profit_units": 0.0, "reason": reason}


def grade_decision(decision: Mapping, box: BoxIndex, results: Mapping, *,
                   now: datetime) -> Optional[dict]:
    """The settled outcome for one decision, or None to leave it pending.

    A pending decision carries no row at all; `{"pending": "mismatch"}` is
    returned (not written) when the two final-score sources disagree so the
    caller can count it.
    """
    arm = ARMS_BY_NAME[decision["arm"]]
    gpk = game_pk_key(decision.get("game_pk"))
    try:
        age_days = (now.date() - date_cls.fromisoformat(decision["date"])).days
    except (KeyError, TypeError, ValueError):
        age_days = 0
    expired = age_days >= VOID_AFTER_DAYS

    final_set = box.finals.get(gpk) or set()
    if len(final_set) != 1:
        if len(final_set) > 1:
            return _void("box-score linescores disagree") if expired else {"pending": "mismatch"}
        return _void("no final") if expired else None
    away, home, innings = next(iter(final_set))

    if arm.grade_as == GRADE_PROP:
        if innings < REGULATION_INNINGS:
            return dict(_void("game shortened"), innings=innings)
        return dict(_grade_prop(arm, decision, box, gpk), innings=innings)

    csv_score = results.get(gpk)
    if csv_score is not None and tuple(csv_score) != (away, home):
        return _void("final score sources disagree") if expired else {"pending": "mismatch"}
    if innings < REGULATION_INNINGS:
        # Books give run lines and totals action only after 9 innings (8.5
        # with the home side ahead); a called game is void, never graded on
        # its partial score. Every arm voids it the same way.
        return dict(_void("game shortened"), away_score=away, home_score=home, innings=innings)

    from src.appstate import card_ledger

    score = {"away_score": away, "home_score": home}
    if arm.grade_as == GRADE_RUN_LINE:
        graded = card_ledger.grade_pick({"market": "run_line", "side": decision.get("side"),
                                         "line": float(decision["line"]),
                                         "price": decision.get("price")}, score)
    else:
        graded = card_ledger.grade_total_pick({"side": decision.get("side"),
                                               "line": float(decision["line"]),
                                               "price": decision.get("price")}, score)
    out = {"result": graded["result"],
           "profit_units": round(float(graded.get("profit_units") or 0.0) * STAKE_UNITS, 4),
           "away_score": away, "home_score": home, "innings": innings}
    if graded.get("reason"):
        out["reason"] = graded["reason"]
    return out


def match_batter(box: BoxIndex, game_pk: str, player_norm: Optional[str]) -> tuple:
    """({player_id: box row}, join method) for a prop's player in one game.

    The exact normalised-name join first. Only when it finds no row, the
    first-name-prefix fallback (first_name_prefix_match) over that game's
    batters -- "Leonardo Bernal" in the props feed is "Leo Bernal" in the
    box score. Returns ({}, None) when neither joins."""
    exact = box.batters.get((game_pk, player_norm)) or {}
    if exact:
        return dict(exact), NAME_JOIN_EXACT
    fallback: dict = {}
    for (gpk, name), rows in box.batters.items():
        if gpk == game_pk and first_name_prefix_match(player_norm, name):
            fallback.update(rows)
    if fallback:
        return fallback, NAME_JOIN_PREFIX
    return {}, None


def _grade_prop(arm: Arm, decision: Mapping, box: BoxIndex, gpk: str) -> dict:
    from src.board import settle_props

    matches, join = match_batter(box, gpk, decision.get("player_norm"))
    joined = {"name_join": join}
    if not matches:
        return dict(_void("did not bat"), **joined)
    if len(matches) > 1:
        return dict(_void("ambiguous name"), **joined)
    row = next(iter(matches.values()))
    joined.update(box_player_id=row.get("player_id"), box_player_name=row.get("player_name"))
    if not row.get("pa"):
        return dict(_void("did not bat"), **joined)
    try:
        outcome = settle_props.settle(row, {
            "subject_id": None, "stat": arm.box_stat,
            "line": str(decision.get("line_text")),
            "side": decision.get("side"),
        })
    except settle_props.SettleError as exc:
        return dict(_void(f"unsettleable selection: {exc}"), **joined)
    stat_value = row.get(arm.box_stat)
    if outcome == "void":
        return dict(_void("box row carries no value for the stat"), **joined)
    if outcome == "push":
        return {"result": RESULT_PUSH, "profit_units": 0.0, "stat_value": stat_value, **joined}
    won = outcome == "win"
    try:
        profit = (odds_math.american_to_decimal(decision["price"]) - 1.0) if won else -1.0
    except (odds_math.OddsError, TypeError, ValueError, KeyError):
        return dict(_void("unusable price"), **joined)
    return {"result": RESULT_WIN if won else RESULT_LOSS,
            "profit_units": round(profit * STAKE_UNITS, 4), "stat_value": stat_value, **joined}


def settle_recent(*, now: Optional[datetime] = None, ledger_dir=None, dry_run: bool = False,
                  box_paths: Optional[Mapping] = None, results_path=None) -> dict:
    """Grade every unsettled decision of every arm. Returns COUNTS ONLY:
    {arm: {graded, voids, unsettled, mismatches}}, plus "error" on an arm
    whose ledger could not be read or appended -- the other arms still
    grade."""
    now = now or datetime.now(timezone.utc)
    ledger_dir = Path(ledger_dir) if ledger_dir else default_ledger_dir()

    counts = {arm.name: {"graded": 0, "voids": 0, "unsettled": 0, "mismatches": 0}
              for arm in ARMS}
    pending_by_arm = {}
    years = set()
    for arm in ARMS:
        try:
            decisions = _rows_of_kind(decisions_path(ledger_dir, arm), KIND_DECISION)
            done = {r.get("decision_row_hash")
                    for r in _rows_of_kind(settled_path(ledger_dir, arm), KIND_SETTLED)}
        except Exception as exc:  # noqa: BLE001 -- one arm's broken file must not stop the rest
            counts[arm.name]["error"] = _error_text(exc)
            continue
        pending = [d for d in decisions if d.get(ROW_HASH_FIELD) not in done]
        pending_by_arm[arm.name] = pending
        years.update(str(d.get("date") or "")[:4] for d in pending if d.get("date"))

    if not any(pending_by_arm.values()):
        return counts

    box = load_box_index(years, box_paths=box_paths)
    results = load_results_scores(results_path)
    for arm in ARMS:
        if arm.name not in pending_by_arm:
            continue
        try:
            _settle_arm(arm, pending_by_arm[arm.name], box, results, now=now,
                        dry_run=dry_run, ledger_dir=ledger_dir, counts=counts[arm.name])
        except Exception as exc:  # noqa: BLE001 -- one arm's broken file must not stop the rest
            counts[arm.name]["error"] = _error_text(exc)
    return counts


def _settle_arm(arm: Arm, pending: Sequence[Mapping], box: BoxIndex, results: Mapping, *,
                now: datetime, dry_run: bool, ledger_dir: Path, counts: dict) -> None:
    ledger = HashChainLedger(settled_path(ledger_dir, arm))
    for decision in pending:
        outcome = grade_decision(decision, box, results, now=now)
        if outcome is None or "pending" in outcome:
            counts["unsettled"] += 1
            if outcome is not None:
                counts["mismatches"] += 1
            continue
        if outcome["result"] == RESULT_VOID:
            counts["voids"] += 1
        else:
            counts["graded"] += 1
        if dry_run:
            continue
        row = {
            "kind": KIND_SETTLED, "family": FAMILY, "rule_id": arm.rule_id,
            "arm": arm.name, "schema_version": SCHEMA_VERSION,
            "decision_row_hash": decision.get(ROW_HASH_FIELD),
            "decision_key": decision.get("decision_key"),
            "date": decision.get("date"), "game_pk": decision.get("game_pk"),
            "settled_utc": _iso(now),
            **outcome,
        }
        row.setdefault("reason", None)
        ledger.append(row)


# ---------------------------------------------------------------------------
# Record (per arm, never pooled)
# ---------------------------------------------------------------------------

# How far a scanned date got, lowest to highest. A date is classed by the
# furthest any run that day got, so an empty day says WHICH kind of empty it
# was -- and value the rule found but could not decide (its game had no
# game_pk, or an ambiguous one) is never reported as the rule declining.
DAY_CLASSES = (
    "no board",                                    # no upcoming board on the date
    "never run inside the lock window",            # boards, all more than 4h out
    "board too old to judge",                      # in window, newest quote > 1h old
    "too few books to judge any line",             # judged, no line had N other books
    "looked and declined",                         # lines compared, none cleared the bar
    "value found but game unmapped or ambiguous",  # candidates, all on unmappable games
    "decided",                                     # at least one decision on the date
)


def _day_rank(counts: Mapping) -> int:
    if (counts.get("skipped_unmapped") or 0) + (counts.get("skipped_ambiguous") or 0):
        return 5
    if counts.get("lines_judged"):
        return 4
    if counts.get("boards_judged"):
        return 3
    if counts.get("boards_stale"):
        return 2
    if counts.get("boards_seen"):
        return 1
    return 0


def record(*, ledger_dir=None) -> dict:
    """{arm: record}. W-L-P-V, pending, staked (W+L+P at 1u), units, ROI%,
    mean claimed EV, each scanned date's kind of outcome (DAY_CLASSES), and
    the keys skipped as unmapped / ambiguous and capped. There is no
    all-arms total, by design. An arm whose files cannot be read comes back
    as {"error": ...}; the other arms are still recorded."""
    ledger_dir = Path(ledger_dir) if ledger_dir else default_ledger_dir()
    out = {}
    for arm in ARMS:
        try:
            out[arm.name] = _record_arm(arm, ledger_dir)
        except Exception as exc:  # noqa: BLE001 -- one arm's broken file must not stop the rest
            out[arm.name] = {"rule_id": arm.rule_id, "label": arm.label,
                             "error": _error_text(exc)}
    return out


def _record_arm(arm: Arm, ledger_dir: Path) -> dict:
    decisions = _rows_of_kind(decisions_path(ledger_dir, arm), KIND_DECISION)
    settled = {r.get("decision_row_hash"): r
               for r in _rows_of_kind(settled_path(ledger_dir, arm), KIND_SETTLED)}
    scans = _rows_of_kind(scans_path(ledger_dir, arm), KIND_SCAN)
    tally = {RESULT_WIN: 0, RESULT_LOSS: 0, RESULT_PUSH: 0, RESULT_VOID: 0}
    units = 0.0
    pending = 0
    for d in decisions:
        s = settled.get(d.get(ROW_HASH_FIELD))
        if s is None:
            pending += 1
            continue
        tally[s.get("result")] = tally.get(s.get("result"), 0) + 1
        units += float(s.get("profit_units") or 0.0)
    staked = (tally[RESULT_WIN] + tally[RESULT_LOSS] + tally[RESULT_PUSH]) * STAKE_UNITS

    decided = len(DAY_CLASSES) - 1
    decided_dates = {d.get("date") for d in decisions}
    days: dict = {}
    # Scan counts are per run, and a skipped key is counted again by every
    # later run that sees it, so a date contributes its PEAK, never a sum.
    peaks: dict = defaultdict(lambda: {"skipped_unmapped": 0, "skipped_ambiguous": 0,
                                       "capped": 0})
    for scan in scans:
        date = scan.get("date")
        c = scan.get("counts") or {}
        rank = decided if date in decided_dates else _day_rank(c)
        days[date] = max(days.get(date, 0), rank)
        for field in peaks[date]:
            peaks[date][field] = max(peaks[date][field], int(c.get(field) or 0))
    for date in decided_dates:
        days[date] = decided
    by_kind = defaultdict(int)
    for rank in days.values():
        by_kind[DAY_CLASSES[rank]] += 1

    evs = [float(d.get("ev") or 0.0) for d in decisions]
    return {
        "rule_id": arm.rule_id,
        "label": arm.label,
        "decisions": len(decisions),
        "wins": tally[RESULT_WIN], "losses": tally[RESULT_LOSS],
        "pushes": tally[RESULT_PUSH], "voids": tally[RESULT_VOID],
        "pending": pending,
        "staked_units": staked,
        "units": round(units, 4),
        "roi_pct": round(100.0 * units / staked, 2) if staked else None,
        "mean_claimed_ev_pct": round(100.0 * sum(evs) / len(evs), 2) if evs else None,
        "days": dict(by_kind),
        "skipped_unmapped": sum(p["skipped_unmapped"] for p in peaks.values()),
        "skipped_ambiguous": sum(p["skipped_ambiguous"] for p in peaks.values()),
        "capped": sum(p["capped"] for p in peaks.values()),
    }


def verify(*, ledger_dir=None) -> dict:
    """{file name: {ok, rows, reason}} for every arm's three chains. A file
    that cannot even be read (a line JSON cannot parse) is reported not ok,
    never raised, so the other files are still checked."""
    ledger_dir = Path(ledger_dir) if ledger_dir else default_ledger_dir()
    out = {}
    for arm in ARMS:
        for path in (decisions_path(ledger_dir, arm), scans_path(ledger_dir, arm),
                     settled_path(ledger_dir, arm)):
            try:
                result = HashChainLedger(path).verify()
            except Exception as exc:  # noqa: BLE001 -- report it, check the rest
                out[path.name] = {"ok": False, "rows": 0,
                                  "reason": f"unreadable: {_error_text(exc)}"}
                continue
            out[path.name] = {"ok": result.ok, "rows": result.rows_checked,
                              "reason": result.reason}
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt_price(price) -> str:
    n = int(round(float(price)))
    return f"+{n}" if n > 0 else str(n)


def _describe(row: Mapping) -> str:
    game = f"{row.get('away_team')} @ {row.get('home_team')}"
    price = _fmt_price(row["price"])
    if row.get("player"):
        what = f"{row['player']} {row['side'].title()} {row['line_text']}"
    elif row.get("market") == "spreads":
        team = row.get("home_team") if row.get("side") == "home" else row.get("away_team")
        what = f"{team} {row['line']:+g}"
    else:
        what = f"{row['side'].title()} {row['line']:g}"
    return (f"{row['arm']}: {game} -- {what} {price} @ {row['book']} | EV "
            f"{100.0 * row['ev']:.2f}% (lowest of 3), fair {100.0 * row['fair_probability']:.1f}%, "
            f"{row['n_other_books']} other books, {row.get('minutes_to_first_pitch')} min to first pitch")


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    moment = lobo.parse_utc(text)
    if moment is None:
        raise SystemExit(f"--now: cannot parse {text!r}")
    return moment


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m src.analysis.mlb_value_shadow",
                                     description=f"{FAMILY}: shadow forward test (never customer-facing)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pub = sub.add_parser("publish", help="judge the date's boards and lock new decisions")
    p_pub.add_argument("--date", required=True, help="ET slate date YYYY-MM-DD")
    p_pub.add_argument("--now", help="judge as of this UTC instant (rows observed later are ignored)")
    p_pub.add_argument("--dry-run", action="store_true", help="print what would be decided; write nothing")
    p_pub.add_argument("--ledger-dir", help="ledger directory (default evidence/mlb_value_shadow_v1)")
    p_pub.add_argument("--arms", help="comma-separated arm names (default: all)")

    p_set = sub.add_parser("settle", help="grade pending decisions (counts only)")
    p_set.add_argument("--recent", action="store_true",
                       help="every pending decision (the only mode; accepted for readability)")
    p_set.add_argument("--now", help="settle as of this UTC instant")
    p_set.add_argument("--dry-run", action="store_true", help="count what would settle; write nothing")
    p_set.add_argument("--ledger-dir")

    p_rec = sub.add_parser("record", help="per-arm W-L, units and ROI (run log only)")
    p_rec.add_argument("--ledger-dir")

    p_ver = sub.add_parser("verify", help="verify every hash chain")
    p_ver.add_argument("--ledger-dir")

    args = parser.parse_args(argv)
    tag = "mlb value shadow"

    if args.command == "publish":
        arms = [a.strip() for a in args.arms.split(",")] if args.arms else None
        if arms:
            unknown = [a for a in arms if a not in ARMS_BY_NAME]
            if unknown:
                print(f"{tag}: unknown arm(s) {unknown}; known: {sorted(ARMS_BY_NAME)}")
                return 2
        summary = publish(args.date, now=_parse_now(args.now), dry_run=args.dry_run,
                          ledger_dir=args.ledger_dir, arms=arms)
        mode = "DRY RUN, nothing written" if args.dry_run else "shadow only, never on the card"
        print(f"{tag} publish {args.date} ({mode})")
        for name, item in summary.items():
            for row in item["decisions"]:
                print(f"  {'WOULD LOCK' if args.dry_run else 'LOCKED'} {_describe(row)}")
        # One line per arm, last, so a tailed log always shows every arm --
        # including one that failed.
        for name, item in summary.items():
            if item.get("error"):
                print(f"  {name}: ERROR {item['error']}")
                continue
            c = item["counts"]
            print(f"  {name}: boards {c['boards_seen']} (outside window {c['boards_outside_window']}, "
                  f"stale {c['boards_stale']}, judged {c['boards_judged']}), book-lines judged "
                  f"{c['lines_judged']}, candidates {c['candidates']}, new {c['new_decisions']}, "
                  f"held {c['held']}, capped {c['capped']}, unmapped {c['skipped_unmapped']}, "
                  f"ambiguous {c['skipped_ambiguous']}")
        return 1 if any(item.get("error") for item in summary.values()) else 0

    if args.command == "settle":
        counts = settle_recent(now=_parse_now(args.now), ledger_dir=args.ledger_dir,
                               dry_run=args.dry_run)
        mode = " (DRY RUN, nothing written)" if args.dry_run else ""
        print(f"{tag} settle{mode} -- counts only")
        for name, c in counts.items():
            print(f"  {name}: graded {c['graded']}, voids {c['voids']}, unsettled {c['unsettled']}"
                  + (f", MISMATCH {c['mismatches']}" if c["mismatches"] else "")
                  + (f"; ERROR {c['error']}" if c.get("error") else ""))
        return 1 if any(c.get("error") for c in counts.values()) else 0

    if args.command == "record":
        print(f"{tag} record -- per arm, never pooled, never on a customer surface")
        failed = False
        for name, r in record(ledger_dir=args.ledger_dir).items():
            label = f" [{r['label']}]" if r["label"] else ""
            if r.get("error"):
                failed = True
                print(f"  {name}{label}: ERROR {r['error']}")
                continue
            roi = "n/a" if r["roi_pct"] is None else f"{r['roi_pct']:+.2f}%"
            ev = "n/a" if r["mean_claimed_ev_pct"] is None else f"{r['mean_claimed_ev_pct']:.2f}%"
            days = ", ".join(f"{k} {v}" for k, v in sorted(r["days"].items())) or "no scans"
            print(f"  {name}{label}: {r['decisions']} decisions, {r['wins']}-{r['losses']}"
                  f"-{r['pushes']} (W-L-P), {r['voids']} void, {r['pending']} pending, "
                  f"units {r['units']:+.2f} on {r['staked_units']:.0f} staked, ROI {roi}, "
                  f"mean claimed EV {ev}; days: {days}; keys skipped: unmapped "
                  f"{r['skipped_unmapped']}, ambiguous {r['skipped_ambiguous']}, capped {r['capped']}")
        return 1 if failed else 0

    if args.command == "verify":
        bad = 0
        for name, v in verify(ledger_dir=args.ledger_dir).items():
            status = "ok" if v["ok"] else f"BROKEN: {v['reason']}"
            bad += 0 if v["ok"] else 1
            print(f"  {name}: {v['rows']} rows, {status}")
        return 1 if bad else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
