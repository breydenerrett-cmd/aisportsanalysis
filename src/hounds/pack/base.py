"""The house pack's shared machinery: the board at lock, the point-in-time context, the Hound.

WHAT A HOUND SEES
-----------------
A hound is asked about ONE game at that game's lock instant. It gets two things:

`board`    the market at lock (`build_board`): for each market on the board, its main line and,
           per side, the board-average price, the best price and its book, the book count and the
           consensus fair probability. Quotes observed after lock, or at or after the start, never
           enter it.
`context`  a `Context` built by `build_context` from stores that were themselves filtered to the
           lock instant: prior MLB games (dated strictly before the game's date, started at least
           five hours before lock, never inside the SEALED window), bullpen rows dated strictly
           before the game's date, NFL finals that kicked off at least six hours before lock, the
           open board, and the game's identity. Nothing else.

A hound returns a list of `Selection`s (zero or one in v1; the runner enforces one per game, the
-200 rule, the price band and the daily cap). `docs/PREREG_HOUSE_PACK_V1.md` is the rule book; the
numbers below are the ones frozen there.

THE SEALED WINDOW
-----------------
2026-01-01..2026-08-27 outcomes are sealed. `read_mlb_results` drops a row dated inside it before
any score in that row is looked at, and the bullpen reader does the same, so every 2026 "form" or
"rate" in the pack starts at 2026-08-28.

Stdlib only; reads the repo's stores through their own readers; no network, no clock (the runner
passes times in).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence

from src.core import odds as odds_math

SEAL_FIRST = "2026-01-01"
SEAL_LAST = "2026-08-27"
SEAL_FLOOR = "2026-08-28"

LOCK_MINUTES = 60
MAX_QUOTE_AGE = {"mlb": timedelta(hours=6), "nfl": timedelta(hours=48)}
OPEN_WINDOW = {"mlb": timedelta(hours=24), "nfl": timedelta(days=7)}
OPEN_MIN_LEAD = timedelta(minutes=60)
MIN_BOOKS = 3
PRICE_MIN = -199          # the owner's rule: never -200 or worse
PRICE_MAX = 400
MAX_PER_DAY = 3
MLB_PRIOR_GAME_LAG = timedelta(hours=5)
NFL_PRIOR_GAME_LAG = timedelta(hours=6)

MARKETS = ("moneyline", "spread", "total")
SIDES = {"moneyline": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under")}
FEED_MARKET = {None: "moneyline", "h2h": "moneyline", "spreads": "spread", "totals": "total"}


class PackError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------

def parse_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def eastern_date(moment: datetime) -> str:
    from src.data.eastern import eastern

    return moment.astimezone(eastern()).date().isoformat()


def in_seal(day: Any) -> bool:
    text = str(day or "")[:10]
    return SEAL_FIRST <= text <= SEAL_LAST


def day_before(day: str, n: int = 1) -> str:
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------

def to_american_int(decimal_price: float) -> int:
    value = odds_math.decimal_to_american(decimal_price)
    out = int(round(value))
    if -100 < out < 100:            # rounding at even money: -100 and +100 are the same price
        out = 100
    return out


def break_even(american: float) -> float:
    return 1.0 / odds_math.american_to_decimal(american)


def units_for(result: str, american: Optional[float], stake: float = 1.0) -> Optional[float]:
    if result in ("PUSH", "VOID"):
        return 0.0
    if american is None:
        return None
    if result == "WIN":
        return round(stake * (odds_math.american_to_decimal(american) - 1.0), 4)
    if result == "LOSS":
        return round(-stake, 4)
    return None


# ---------------------------------------------------------------------------
# quotes and the board
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def quote_from_row(row: Mapping) -> Optional[dict]:
    """One multibook row as {book, observed, market, line, prices: {side: price}}; None if unusable."""
    market = FEED_MARKET.get(row.get("market"))
    observed = parse_utc(row.get("observed_utc"))
    if market is None or observed is None or not row.get("book"):
        return None
    if market == "moneyline":
        a, h = _num(row.get("away_price")), _num(row.get("home_price"))
        line = None
        prices = {"home": h, "away": a}
    elif market == "spread":
        a, h = _num(row.get("away_price")), _num(row.get("home_price"))
        line = _num(row.get("home_line"))
        prices = {"home": h, "away": a}
    else:
        line = _num(row.get("total"))
        prices = {"over": _num(row.get("over_price")), "under": _num(row.get("under_price"))}
    if any(p is None or -100 < p < 100 for p in prices.values()):
        return None
    if market != "moneyline" and line is None:
        return None
    return {"book": str(row["book"]), "observed": observed, "market": market, "line": line,
            "prices": prices}


def _side_summary(entries: Sequence[tuple]) -> dict:
    """entries: (book, price, fair) for one side of one line."""
    decimals = [odds_math.american_to_decimal(p) for _, p, _ in entries]
    best_dec = max(decimals)
    # ties on price go to the alphabetically first book
    tied = sorted((entries[i][0], entries[i][1]) for i in range(len(entries)) if decimals[i] == best_dec)
    return {
        "price_average": to_american_int(sum(decimals) / len(decimals)),
        "price_best": int(round(tied[0][1])),
        "book": tied[0][0],
        "book_count": len(entries),
        "fair": round(sum(f for _, _, f in entries) / len(entries), 6),
    }


def _market_board(quotes: Sequence[dict], market: str) -> Optional[dict]:
    by_line: dict = {}
    for q in quotes:
        by_line.setdefault(q["line"], []).append(q)
    candidates = []
    for line, qs in by_line.items():
        if len(qs) < MIN_BOOKS:
            continue
        a, b = SIDES[market]
        rows_a, rows_b = [], []
        for q in qs:
            fa, fb = odds_math.devig_two_way(q["prices"][a], q["prices"][b])
            rows_a.append((q["book"], q["prices"][a], fa))
            rows_b.append((q["book"], q["prices"][b], fb))
        sa, sb = _side_summary(rows_a), _side_summary(rows_b)
        candidates.append((len(qs), -abs(sa["fair"] - 0.5), -abs(line or 0.0), line, {a: sa, b: sb}))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    n, _, _, line, sides = candidates[0]
    return {"line": line, "books": n, "sides": sides}


def build_board(quotes: Iterable[dict], *, at: datetime, start: datetime, sport: str) -> dict:
    """The board at instant `at`: each book's newest quote per market observed at or before `at`,
    strictly before `start`, no older than the sport's staleness window."""
    max_age = MAX_QUOTE_AGE[sport]
    newest: dict = {}
    for q in quotes:
        obs = q["observed"]
        if obs > at or obs >= start or obs < at - max_age:
            continue
        key = (q["market"], q["book"])
        if key not in newest or obs > newest[key]["observed"]:
            newest[key] = q
    board = {"as_of": iso(at), "markets": {}}
    for market in MARKETS:
        mq = [q for (m, _), q in newest.items() if m == market]
        mb = _market_board(mq, market)
        if mb is not None:
            board["markets"][market] = mb
    return board


def board_at_line(quotes: Iterable[dict], *, at: datetime, start: datetime, sport: str,
                  market: str, line: Optional[float]) -> Optional[dict]:
    """Like `build_board` for one market but forced to one line (the close for CLV)."""
    max_age = MAX_QUOTE_AGE[sport]
    newest: dict = {}
    for q in quotes:
        if q["market"] != market or q["line"] != line:
            continue
        obs = q["observed"]
        if obs > at or obs >= start or obs < at - max_age:
            continue
        if q["book"] not in newest or obs > newest[q["book"]]["observed"]:
            newest[q["book"]] = q
    if not newest:
        return None
    a, b = SIDES[market]
    rows_a, rows_b = [], []
    for q in newest.values():
        fa, fb = odds_math.devig_two_way(q["prices"][a], q["prices"][b])
        rows_a.append((q["book"], q["prices"][a], fa))
        rows_b.append((q["book"], q["prices"][b], fb))
    return {"line": line, "books": len(newest), "sides": {a: _side_summary(rows_a), b: _side_summary(rows_b)}}


def open_board(quotes: Sequence[dict], *, lock: datetime, start: datetime, sport: str) -> Optional[dict]:
    """The moneyline consensus at the earliest capture instant (within the open window) that has at
    least MIN_BOOKS books, if that instant is at least OPEN_MIN_LEAD before lock."""
    lo = start - OPEN_WINDOW[sport]
    instants: dict = {}
    for q in quotes:
        if q["market"] != "moneyline":
            continue
        obs = q["observed"]
        if obs < lo or obs > lock or obs >= start:
            continue
        instants.setdefault(obs, {})[q["book"]] = q
    for obs in sorted(instants):
        if obs > lock - OPEN_MIN_LEAD:
            return None
        books = instants[obs]
        if len(books) >= MIN_BOOKS:
            mb = _market_board(list(books.values()), "moneyline")
            if mb is not None:
                return {"as_of": iso(obs), "markets": {"moneyline": mb}}
    return None


def side_info(board: Mapping, market: str, side: str) -> Optional[dict]:
    mb = (board.get("markets") or {}).get(market)
    if not mb:
        return None
    return mb["sides"].get(side)


def other(side: str) -> str:
    return {"home": "away", "away": "home", "over": "under", "under": "over"}[side]


# ---------------------------------------------------------------------------
# selections and hounds
# ---------------------------------------------------------------------------

@dataclass
class Selection:
    market: str
    side: str
    score: float
    reason: str
    stake: float = 1.0


class Hound:
    """One pack hound. Subclasses set the class attributes and implement `pick`.

    `RULE` is the plain-English rule; `config/house_pack.json` carries it verbatim (a test holds
    the two together). `pick` must be a pure function of (board, context)."""

    id: str = ""
    name: str = ""
    tagline: str = ""
    category: str = ""
    style: str = ""
    sports: tuple = ()
    markets: tuple = ()
    who_decided: str = "rule"
    RULE: str = ""
    band: tuple = (PRICE_MIN, PRICE_MAX)

    def pick(self, board: Mapping, context: "Context") -> List[Selection]:
        raise NotImplementedError

    def applies_to(self, sport: str) -> bool:
        return sport in self.sports


def seed_bytes(hound_id: str, event_id: str) -> bytes:
    return hashlib.sha256(f"{hound_id}|{event_id}".encode("utf-8")).digest()


# ---------------------------------------------------------------------------
# stores (read once per run; filtered per game by build_context)
# ---------------------------------------------------------------------------

def mlb_code(value: Any) -> Optional[str]:
    """One spelling per MLB club: the results store writes AZ/ATH, the odds-name map ARI/OAK.
    `src.data.parks.canonical_team` is the repo's one alias table."""
    if not isinstance(value, str) or not value.strip():
        return None
    from src.data.parks import canonical_team

    return canonical_team(value)


def _int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def read_mlb_results(path: str, *, since: str = SEAL_FLOOR) -> List[dict]:
    """Finished MLB games from the results CSV, normalised. Rows dated inside the SEALED window are
    dropped on their date field alone, before any other field is read."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            day = row.get("date") or ""
            if in_seal(day) or day < since:
                continue
            a, h = _int(row.get("away_score")), _int(row.get("home_score"))
            out.append({
                "game_pk": str(row.get("game_pk")), "date": day, "start_utc": row.get("start_time_utc"),
                "game_type": row.get("game_type"), "away": mlb_code(row.get("away_team")),
                "home": mlb_code(row.get("home_team")), "away_score": a, "home_score": h,
                "source": "results",
            })
    return out


def read_mlb_manifest_dates(path: str) -> set:
    try:
        with open(path, encoding="utf-8") as fh:
            dates = (json.load(fh) or {}).get("dates") or {}
    except (OSError, ValueError):
        return set()
    return {d for d in dates if d >= SEAL_FLOOR}


def read_boxscore_finals(path: str, *, skip_pks: set, start_by_pk: Mapping, since: str = SEAL_FLOOR) -> List[dict]:
    """Final scores summed from the box-score store's pitcher lines, for games the results store
    does not hold. Each side's runs = runs charged to the OTHER side's pitchers; accepted only
    when both sides' pitchers recorded at least 24 outs (eight innings)."""
    from src.pipeline.slate import team_abbrev_from_name

    games: dict = {}
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or '"pitcher"' not in line:
                continue
            r = json.loads(line)
            day = str(r.get("date") or "")
            if r.get("type") != "pitcher" or in_seal(day) or day < since:
                continue
            pk = str(r.get("game_pk"))
            if pk in skip_pks:
                continue
            g = games.setdefault(pk, {"date": day, "runs": {"away": 0, "home": 0},
                                      "outs": {"away": 0, "home": 0}, "team": {}})
            side = r.get("side")
            if side not in ("away", "home"):
                continue
            g["runs"][side] += int(r.get("r") or 0)
            g["outs"][side] += int(r.get("outs") or 0)
            g["team"][side] = mlb_code(team_abbrev_from_name(r.get("team_name")))
    out = []
    for pk, g in games.items():
        if min(g["outs"].values()) < 24 or not g["team"].get("away") or not g["team"].get("home"):
            continue
        out.append({"game_pk": pk, "date": g["date"], "start_utc": start_by_pk.get(pk),
                    "game_type": None, "away": g["team"]["away"], "home": g["team"]["home"],
                    "away_score": g["runs"]["home"], "home_score": g["runs"]["away"],
                    "source": "boxscore_sum"})
    return out


def read_bullpen(path: str) -> List[dict]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            day = str(r.get("date") or "")
            if in_seal(day) or day < SEAL_FLOOR:
                continue
            if r.get("team"):
                r["team"] = mlb_code(r["team"])
            out.append(r)
    return out


def read_nfl_games(path: str) -> List[dict]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def read_event_map(path: str) -> dict:
    out: dict = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("resolved") and r.get("game_pk") and not r.get("ambiguous"):
                out[r["event_id"]] = r
    return out


@dataclass
class Stores:
    """Everything a run reads, loaded once. Tests build this directly with synthetic rows."""
    quotes_by_event: dict = field(default_factory=dict)     # event_id -> [quote]
    events: dict = field(default_factory=dict)              # event_id -> {sport, away_name, home_name, commence: [(observed, commence)]}
    mlb_games: list = field(default_factory=list)
    mlb_covered: set = field(default_factory=set)            # dates the results/boxscore stores cover
    bullpen: list = field(default_factory=list)
    bullpen_dates: set = field(default_factory=set)
    nfl_games: list = field(default_factory=list)
    event_map: dict = field(default_factory=dict)            # MLB event_id -> map row

    def add_row(self, row: Mapping) -> None:
        sport = row.get("sport") or "mlb"
        if sport not in ("mlb", "nfl"):
            return
        q = quote_from_row(row)
        if q is None:
            return
        eid = row["event_id"]
        self.quotes_by_event.setdefault(eid, []).append(q)
        ev = self.events.setdefault(eid, {"sport": sport, "away_name": row.get("away_team"),
                                          "home_name": row.get("home_team"), "commence": []})
        c = parse_utc(row.get("commence_time"))
        if c is not None:
            ev["commence"].append((q["observed"], c))

    def finalize(self) -> None:
        for ev in self.events.values():
            ev["commence"].sort()
        self.bullpen_dates = {str(r.get("date")) for r in self.bullpen}


def load_stores(*, since: str, until: Optional[str] = None, root: Optional[str] = None) -> Stores:
    """Read the real stores. `since`/`until` bound the odds read (observed dates)."""
    from src import paths
    from src.pipeline import snapshots

    base = root or str(paths.repo_root())
    st = Stores()
    for row in snapshots.iter_multibook(sport=None, since=since, until=until):
        st.add_row(row)
    st.event_map = read_event_map(os.path.join(base, "data", "processed", "event_game_map.jsonl"))
    st.mlb_games = read_mlb_results(os.path.join(base, "data", "historical", "mlb_results.csv"))
    have = {g["game_pk"] for g in st.mlb_games}
    start_by_pk = {str(r["game_pk"]): r.get("commence_time") for r in st.event_map.values()}
    box = read_boxscore_finals(os.path.join(base, "data", "processed", "boxscores_2026.jsonl"),
                               skip_pks=have, start_by_pk=start_by_pk)
    st.mlb_games.extend(box)
    st.mlb_covered = read_mlb_manifest_dates(os.path.join(base, "data", "historical", "mlb_results.manifest.json"))
    st.mlb_covered |= {g["date"] for g in box}
    st.bullpen = read_bullpen(os.path.join(base, "data", "historical", "bullpen_log.jsonl"))
    st.nfl_games = read_nfl_games(os.path.join(base, "data", "datasvc", "nfl", "games.jsonl"))
    st.finalize()
    return st


# ---------------------------------------------------------------------------
# games and the point-in-time context
# ---------------------------------------------------------------------------

@dataclass
class Context:
    sport: str
    event_id: str
    date: str
    start: datetime
    lock: datetime
    away_name: str
    home_name: str
    away: Optional[str]                  # club codes
    home: Optional[str]
    game_pk: Optional[str] = None
    nfl_game_id: Optional[str] = None
    open_board: Optional[dict] = None
    mlb_games: list = field(default_factory=list)       # finished, before lock
    mlb_covered: set = field(default_factory=set)
    bullpen: list = field(default_factory=list)
    bullpen_dates: set = field(default_factory=set)
    nfl_games: list = field(default_factory=list)       # finals, before lock
    nfl_schedule: list = field(default_factory=list)    # 2026 schedule identity rows (no scores)
    cache: dict = field(default_factory=dict)           # per-context memo shared by hounds


def start_at(ev: Mapping, before: Optional[datetime] = None) -> Optional[datetime]:
    """The feed's start on the newest capture at or before `before` (newest overall if None)."""
    best = None
    for observed, commence in ev.get("commence") or ():
        if before is not None and observed > before:
            break
        best = commence
    return best


def resolve_start(ev: Mapping) -> Optional[datetime]:
    """start = commence_time on the newest capture at or before (that capture's commence - lock)."""
    pairs = ev.get("commence") or ()
    if not pairs:
        return None
    start = pairs[-1][1]
    for _ in range(4):           # converge: a start moved after an early capture
        s = start_at(ev, start - timedelta(minutes=LOCK_MINUTES))
        if s is None or s == start:
            break
        start = s
    return start


def nfl_codes(ev: Mapping) -> tuple:
    from src.sports import nfl_teams

    return nfl_teams.abbrev(ev.get("away_name")), nfl_teams.abbrev(ev.get("home_name"))


def mlb_codes(ev: Mapping) -> tuple:
    from src.pipeline.slate import team_abbrev_from_name

    return (mlb_code(team_abbrev_from_name(ev.get("away_name"))),
            mlb_code(team_abbrev_from_name(ev.get("home_name"))))


def _nfl_game_for(stores: Stores, away: str, home: str, start: datetime) -> Optional[dict]:
    for g in stores.nfl_games:
        if g.get("away_team") == away and g.get("home_team") == home and g.get("status") != "removed":
            k = parse_utc(g.get("kickoff_utc"))
            if k is not None and abs(k - start) <= timedelta(hours=12):
                return g
    return None


def build_context(stores: Stores, event_id: str) -> Optional[Context]:
    ev = stores.events.get(event_id)
    if ev is None:
        return None
    start = resolve_start(ev)
    if start is None:
        return None
    lock = start - timedelta(minutes=LOCK_MINUTES)
    sport = ev["sport"]
    away, home = (mlb_codes(ev) if sport == "mlb" else nfl_codes(ev))
    ctx = Context(sport=sport, event_id=event_id, date=eastern_date(start), start=start, lock=lock,
                  away_name=ev.get("away_name"), home_name=ev.get("home_name"), away=away, home=home)
    quotes = stores.quotes_by_event.get(event_id) or []
    ctx.open_board = open_board(quotes, lock=lock, start=start, sport=sport)
    if sport == "mlb":
        m = stores.event_map.get(event_id)
        ctx.game_pk = str(m["game_pk"]) if m else None
        cutoff = lock - MLB_PRIOR_GAME_LAG
        for g in stores.mlb_games:
            if g["date"] >= ctx.date:
                continue
            s = parse_utc(g.get("start_utc"))
            if s is not None and s > cutoff:
                continue
            ctx.mlb_games.append(g)
        ctx.mlb_games.sort(key=lambda g: (g["date"], str(g.get("start_utc") or ""), g["game_pk"]))
        ctx.mlb_covered = {d for d in stores.mlb_covered if d < ctx.date}
        ctx.bullpen = [r for r in stores.bullpen if str(r.get("date")) < ctx.date]
        ctx.bullpen_dates = {d for d in stores.bullpen_dates if d < ctx.date}
    else:
        g = _nfl_game_for(stores, away, home, start) if away and home else None
        ctx.nfl_game_id = g.get("game_id") if g else None
        cutoff = lock - NFL_PRIOR_GAME_LAG
        for row in stores.nfl_games:
            k = parse_utc(row.get("kickoff_utc"))
            if k is None or row.get("game_id") == ctx.nfl_game_id:
                continue
            if row.get("status") == "final" and k <= cutoff:
                ctx.nfl_games.append(row)
            if str(row.get("season")) == str(start.year if start.month > 2 else start.year - 1) and k < start:
                ctx.nfl_schedule.append({"game_id": row.get("game_id"), "away_team": row.get("away_team"),
                                         "home_team": row.get("home_team"), "kickoff_utc": row.get("kickoff_utc"),
                                         "gameday": row.get("gameday")})
        ctx.nfl_games.sort(key=lambda r: r.get("kickoff_utc") or "")
        ctx.nfl_schedule.sort(key=lambda r: r.get("kickoff_utc") or "")
    return ctx


def lock_board(stores: Stores, ctx: Context) -> dict:
    return build_board(stores.quotes_by_event.get(ctx.event_id) or [], at=ctx.lock, start=ctx.start,
                       sport=ctx.sport)


# ---------------------------------------------------------------------------
# shared feature helpers (pure, on a Context)
# ---------------------------------------------------------------------------

def mlb_team_games(ctx: Context, team: str) -> list:
    """The club's finished games in the context (oldest first) as {date, home, opp, rf, ra, won, park}."""
    out = []
    for g in ctx.mlb_games:
        if g.get("away_score") is None or g.get("home_score") is None:
            continue
        if g["home"] == team:
            rf, ra, opp = g["home_score"], g["away_score"], g["away"]
        elif g["away"] == team:
            rf, ra, opp = g["away_score"], g["home_score"], g["home"]
        else:
            continue
        out.append({"date": g["date"], "home": g["home"] == team, "opp": opp, "rf": rf, "ra": ra,
                    "won": rf > ra, "park": g["home"], "game_type": g.get("game_type"),
                    "game_pk": g["game_pk"]})
    return out


def nfl_team_games(ctx: Context, team: str, *, season: Optional[int] = None) -> list:
    out = []
    for g in ctx.nfl_games:
        if season is not None and str(g.get("season")) != str(season):
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None:
            continue
        if g.get("home_team") == team:
            pf, pa, opp = hs, as_, g.get("away_team")
        elif g.get("away_team") == team:
            pf, pa, opp = as_, hs, g.get("home_team")
        else:
            continue
        out.append({"kickoff": g.get("kickoff_utc"), "gameday": g.get("gameday"), "opp": opp,
                    "pf": pf, "pa": pa, "won": pf > pa, "tied": pf == pa})
    return out


def nfl_season(ctx: Context) -> int:
    return ctx.start.year if ctx.start.month > 2 else ctx.start.year - 1


def selection_label(ctx: Context, market: str, side: str, line: Optional[float]) -> str:
    if market == "total":
        return f"{'Over' if side == 'over' else 'Under'} {line:g}"
    team = ctx.home_name if side == "home" else ctx.away_name
    if market == "moneyline":
        return f"{team} ML"
    signed = line if side == "home" else (-line if line is not None else None)
    return f"{team} {signed:+g}"
