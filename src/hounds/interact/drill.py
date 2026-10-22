"""The hindsight drill (the owner calls it the BACKTEST: the page says "Backtest"): a dog's rule replayed over the last 7, 14 or 30 days of stored boards.

LABELLED HINDSIGHT, NEVER COUNTED. The boards were captured before the rule was run over them, and the person
asking could see how those games ended when they chose the rule, so a drill is a rehearsal and not evidence.
It is written into a TEMPORARY ledger that is thrown away; the real ledgers are never opened for writing, so a
drill cannot reach a dog's record, the leaderboard, the referee or the learning loop. Every result carries
``counted: false`` and the words "Backtest (hindsight, not counted in the record)".

SAME MACHINERY AS THE COACH'S HINDSIGHT (src/hounds/coach_grade.py ``grade_hindsight``):
  house dog  ``pack_run.run(..., replay=True)`` over the stores into a temp ledger, then ``pack_settle.settle``;
             the pack runner's own board at lock, -200 rule, price band and caps.
  user dog   (or a spec typed into the builder) ``user_engine.run(..., mode="replay")`` into a temp ledger, then
             ``user_settle.settle`` with the same results store the live tickets are graded on. The closing
             price is skipped (a drill reports wins, losses and units, not CLV), and no network is touched:
             NFL finals come from the local games store.

THE WINDOW is the last N completed Eastern days (yesterday back), never today: a game that has not started has
no result, and replay mode would otherwise evaluate it on a board from after its lock.

SMALL SAMPLES ARE SAID. Under 30 graded bets the result says so, and a drill never states an edge.

THE BACKTEST IS THIS SAME DRILL, SHOWN IN DOLLARS (owner ask 2026-10-19: a "Backtest" tab on every dog page and in
the studio, 7 / 14 / 30 days and "Season 2"). Every result also carries ``bankroll``: the picks' flat units turned
into dollars on the $1,000 paper bankroll with the bankroll module's own arithmetic (``bankroll.block``; 1u = $10,
a member dog's chosen stake, a house dog 1u), a ``usd`` figure on each ticket, and ``backtest_label``. Nothing is
counted: it is still ``counted: false`` and still written only into the throwaway ledger.

SEASON WINDOWS. ``season="s2"`` means "from the season's first day to yesterday". The replay's memory is the
constraint (a 30-day house drill peaks near 700 MB), so a window longer than ``MAX_SEASON_DAYS`` is the LAST 30
days of the season and says so (``season.clipped``); a season with no completed day yet is refused.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

from src.hounds import bankroll, seasons, user_engine, user_spec
from src.hounds.interact import common, fire
from src.ledger.chain import HashChainLedger

DAYS_CHOICES = (7, 14, 30)
LABEL = "Backtest (hindsight, not counted in the record)"
BACKTEST_LABEL = LABEL
MAX_SEASON_DAYS = 30
DISCLOSURE = ("This replays the hound's current rule over boards that were already captured. The rule was not live "
              "then, and you can see how those games ended, so this is a rehearsal and not evidence. It is "
              "never added to a record, a ranking or a verdict.")
SMALL_N = 30
PICKS_SHOWN = 40
CACHE_TTL_S = 1800.0
CACHE_MAX = 64

_cache: dict = {}
_cache_lock = threading.Lock()

# ONE DRILL AT A TIME, PROCESS-WIDE (red team 2026-10-19). A single 30-day house drill peaked at 686 MB and ran
# 55 s on a 1 GB machine, so two at once (or one beside a page-cache build) is an out-of-memory kill. A second
# request does not queue behind it, because queued requests pile up in threads: it is told to come back.
_drill_slot = threading.Lock()
BUSY_RETRY_AFTER_S = 30


# A member's Gematria-style hound weighs a game once, at the lock, like the house Gematria Hound, and the house hound refuses a
# replay (ai_defs.GEMATRIA_FORWARD_ONLY_MESSAGE); so does it.
GEMATRIA_FORWARD_ONLY_MESSAGE = ("A Gematria hound is forward-only. It weighs each game once, at the lock, from the board and the "
                                 "results stored by then, so a past day cannot be replayed honestly.")


class DrillError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, fields: Optional[dict] = None,
                 retry_after: Optional[int] = None):
        self.code = code
        self.status = status
        self.fields = fields or {}
        self.retry_after = retry_after
        super().__init__(message)


def window(days: int, now: datetime) -> tuple:
    """(first, last) Eastern dates: the last ``days`` completed days (7, 14 or 30)."""
    if days not in DAYS_CHOICES:
        raise DrillError("days_invalid", f"choose {', '.join(str(d) for d in DAYS_CHOICES)} days", 422)
    return _span(days, now)


def _span(days: int, now: datetime) -> tuple:
    """The same window for any whole number of days: the engine of ``window`` and of a season's window."""
    today = datetime.fromisoformat(common.eastern_date(now))
    last = (today - timedelta(days=1)).date()
    first = (today - timedelta(days=days)).date()
    return first.isoformat(), last.isoformat()


def season_window(season_id: str, now: datetime) -> dict:
    """``{id, label, start, days, clipped}``: the number of completed days from the season's first day to yesterday,
    never more than ``MAX_SEASON_DAYS`` (then it is the last that many days: ``clipped``)."""
    season = seasons.get(str(season_id or "").strip().lower())
    if season is None:
        raise DrillError("season_invalid", "that season is not on the calendar", 422)
    today = datetime.fromisoformat(common.eastern_date(now)).date()
    yesterday = today - timedelta(days=1)
    if season["end"] is not None and datetime.fromisoformat(season["end"]).date() < yesterday:
        raise DrillError("season_over", f"{season['label']} is over: pick 7, 14 or 30 days", 422)
    total = (yesterday - datetime.fromisoformat(season["start"]).date()).days + 1
    if total < 1:
        raise DrillError("season_empty", f"{season['label']} has no finished day to replay yet", 422)
    days = min(total, MAX_SEASON_DAYS)
    return {"id": season["id"], "label": season["label"], "start": season["start"], "days": days,
            "clipped": total > MAX_SEASON_DAYS, "days_in_season": total}


def dates_between(first: str, last: str) -> list:
    d0, d1 = datetime.fromisoformat(first), datetime.fromisoformat(last)
    return [(d0 + timedelta(days=i)).date().isoformat() for i in range((d1 - d0).days + 1)]


# ---------------------------------------------------------------------------
# user dogs and typed-in specs
# ---------------------------------------------------------------------------

def spec_from_request(raw) -> dict:
    """A spec typed into the builder, validated the way a created dog's is (the same gate). A drill spec needs no
    name of its own: it gets a neutral one, since nothing is created."""
    if not isinstance(raw, dict):
        raise DrillError("spec_invalid", "send the spec as an object", 422)
    candidate = dict(raw)
    candidate.setdefault("name", "Drill dog")
    candidate.setdefault("tagline", "")
    try:
        return user_spec.validate_spec(candidate)
    except user_spec.SpecError as exc:
        raise DrillError("spec_invalid", "that rule is not on the menu", 422, fields=exc.errors)


CHUNK_DAYS = 8                     # dates replayed per read of the store: bounds memory on a small machine


def _window_rows(first: str, last: str, sports) -> dict:
    """{slate_date: [row]} for every game whose Eastern date is in ``first..last``, from ONE pass over the
    multibook store. Rows keep only the fields ``build_games`` and the engine read, and their two timestamps
    are parsed ONCE per distinct value (the engine's ``_utc`` returns a datetime as it is), which is most of
    the cost of replaying a month."""
    from src.pipeline import snapshots
    keep = ("market", "event_id", "sport") + user_engine._KEEP_FIELDS
    by_date: dict = {}
    slate_of: dict = {}
    stamps: dict = {}

    def parsed(text):
        hit = stamps.get(text)
        if hit is None:
            hit = stamps[text] = user_engine._utc(text)
        return hit
    for sport in sorted({s.lower() for s in sports}):
        since = snapshots.window_for_date(first, sport)[0]
        until = snapshots.window_for_date(last, sport)[1]
        for row in snapshots.iter_multibook(snapshots.DEFAULT_MULTIBOOK_PATH, sport=sport, since=since, until=until):
            raw = row.get("commence_time")
            start = parsed(raw)
            observed = parsed(row.get("observed_utc"))
            if start is None or observed is None:
                continue
            slate = slate_of.get(raw)
            if slate is None:
                slate = slate_of[raw] = user_engine.slate_date_of(start)
            if slate < first or slate > last:
                continue
            slim = {k: row[k] for k in keep if k in row}
            slim["commence_time"], slim["observed_utc"] = start, observed
            by_date.setdefault(slate, []).append(slim)
    return by_date


def _shift(day: str, n: int) -> str:
    return (datetime.fromisoformat(day) + timedelta(days=n)).date().isoformat()


def _local_nfl_results():
    """date -> {(away_code, home_code): scores} from the local games store (no network)."""
    from src import paths
    from src.hounds.pack import base
    from src.sports import nfl_teams
    rows = base.read_nfl_games(os.path.join(str(paths.repo_root()), "data", "datasvc", "nfl", "games.jsonl"))
    by_date: dict = {}
    for g in rows:
        if g.get("status") != "final" or g.get("home_score") is None or g.get("away_score") is None:
            continue
        kick = base.parse_utc(g.get("kickoff_utc"))
        if kick is None:
            continue
        key = (g.get("away_team"), g.get("home_team"))
        by_date.setdefault(base.eastern_date(kick), {})[key] = {
            "home_score": g["home_score"], "away_score": g["away_score"]}
    return lambda date: by_date.get(date, {})


def run_user(hound: dict, days: int, *, now: Optional[datetime] = None, rows_by_date: Optional[dict] = None,
             mlb_results=None, nfl_results=None, game_pk_index=None) -> dict:
    """Replay a user rule. ``hound`` is ``{id, spec, ...}``; the injection points are the tests'."""
    from src.hounds import user_settle
    now = now or common.now_utc()
    first, last = _span(days, now)
    spec = hound["spec"]
    dates = dates_between(first, last)
    if game_pk_index is None:
        game_pk_index = user_engine._load_game_pk_index()
    drill_hound = {"id": hound["id"], "spec": spec, "spec_hash": user_spec.spec_hash(spec),
                   "created_at": "2000-01-01T00:00:00Z"}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "drill.jsonl")
        for start in range(0, len(dates), CHUNK_DAYS):
            chunk = dates[start:start + CHUNK_DAYS]
            if rows_by_date is not None:
                window_rows = rows_by_date
            else:
                with fire._heavy():              # one slice of the store in memory at a time
                    window_rows = _window_rows(_shift(chunk[0], -1), _shift(chunk[-1], 1), spec["sports"])
            for date in chunk:
                near = []
                for offset in (-1, 0, 1):
                    near.extend(window_rows.get(_shift(date, offset), ()))
                user_engine.run(date, [drill_hound], near, ledger=path, now=now, mode="replay",
                                game_pk_index=game_pk_index)
            window_rows = None
        user_settle.settle(ledger=path, now=now, lookback_days=days + 3, mlb_results=mlb_results,
                           nfl_results=nfl_results or _local_nfl_results(), close_fn=lambda _bet: None,
                           game_pk_index=game_pk_index)
        rows = HashChainLedger(path).read()
    return summarize_user(rows)


def summarize_user(rows: Iterable[dict]) -> dict:
    bets = {r["bet_id"]: r for r in rows if r.get("kind") == user_engine.KIND_BET}
    graded = {r["bet_id"]: r for r in rows if r.get("kind") == "hound_user_graded"}
    picks = []
    for bid, b in bets.items():
        g = graded.get(bid)
        picks.append({
            "date": b["slate_date"], "game": f"{b['away_team']} @ {b['home_team']}", "market": b["market"],
            "selection": b["selection"], "price_average": b["price"], "price_best": b["best_price"],
            "result": g["result"] if g else None, "units_average_price": g.get("units_average_price") if g else None,
            "units_best_price": g.get("units_best_price") if g else None,
            "reason": b.get("reason"), "stake_units": b.get("stake_units")})
    return _summary(picks)


# ---------------------------------------------------------------------------
# house dogs
# ---------------------------------------------------------------------------

def run_house(dog: common.Dog, days: int, *, now: Optional[datetime] = None, stores=None) -> dict:
    from src.hounds import pack_run, pack_settle
    from src.hounds.learning import champions
    from src.hounds.pack import base
    now = now or common.now_utc()
    first, last = _span(days, now)
    dates = [d for d in dates_between(first, last) if d >= base.SEAL_FLOOR and not base.in_seal(d)]
    if not dates:
        raise DrillError("sealed", "that window is inside the sealed period", 422)
    hound = champions.champion_versions((dog.house,), champions.events_path_beside(pack_run.ledger_path()))[0]
    # The WHOLE replay (load, run, settle) holds the process-wide build gate, not just the load: the stores are the
    # biggest thing in memory while the replay walks them, so no page-cache rebuild may run beside it.
    with fire._heavy():
        if stores is None:
            since = max(base.SEAL_FLOOR, base.day_before(min(dates), 8))
            until = (datetime.fromisoformat(common.eastern_date(now)) + timedelta(days=2)).date().isoformat()
            stores = base.load_stores(since=since, until=until)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "drill.jsonl")
            pack_run.run(stores, dates, replay=True, now=now, path=path, hounds=[hound],
                         out=lambda *_a, **_k: None)
            pack_settle.settle(stores, now=now, path=path)
            rows = HashChainLedger(path).read()
        stores = None                                  # let go of the store before the gate is released
    return summarize_house(rows)


def summarize_house(rows: Iterable[dict]) -> dict:
    from src.hounds import pack_run
    key = lambda r: (r["hound_id"], r["event_id"], r["market"], r["selection"])      # noqa: E731
    bets = {key(r): r for r in rows if r.get("kind") == pack_run.KIND_BET}
    graded = {key(r): r for r in rows if r.get("kind") == pack_run.KIND_GRADED}
    picks = []
    for k, b in bets.items():
        g = graded.get(k)
        picks.append({
            "date": b["date"], "game": f"{b['away']} @ {b['home']}", "market": b["market"],
            "selection": b["selection"], "price_average": b["price_average"], "price_best": b["price_best"],
            "result": g["result"] if g else None, "units_average_price": g.get("units_average_price") if g else None,
            "units_best_price": g.get("units_best_price") if g else None, "reason": b.get("reason")})
    return _summary(picks)


# ---------------------------------------------------------------------------
# the result
# ---------------------------------------------------------------------------

def _stake(pick: dict) -> float:
    """Units staked on a pick: the member dog's own chosen stake (the bankroll module's rule: a nonsense value is
    one unit), else 1."""
    value = pick.get("stake_units")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) <= bankroll.MAX_STAKE_UNITS:
        return bankroll.FLAT_STAKE_UNITS
    return float(value)


def _usd(pick: dict) -> Optional[float]:
    """The pick's profit in paper dollars (units at the board-average price x stake x $ per unit), None when it
    is not decided or has no unit figure."""
    units = pick.get("units_average_price")
    if pick.get("result") not in ("WIN", "LOSS", "PUSH") or not isinstance(units, (int, float)):
        return None
    return round(units * _stake(pick) * bankroll.params().unit_usd, 2)


def backtest_bankroll(final: list) -> dict:
    """The graded picks as a $1,000 paper account, by the SAME arithmetic the live bankroll uses
    (``bankroll.block``): flat units, 1u = $10, a member dog's own stake. Picks are taken in date order, so the
    drawdown is the account's real worst fall in this window. None-valued units count as 0, as the record does."""
    events = []
    for i, p in enumerate(final):
        flat = p.get("units_average_price")
        flat = float(flat) if isinstance(flat, (int, float)) else 0.0
        stake = _stake(p)
        events.append(bankroll.Event(settle=None, units=flat * stake, flat=flat, stake=stake,
                                     result=p["result"].lower(), order=(p["date"], f"{i:06d}")))
    block = bankroll.block(events, basis="average")
    keep = ("start", "current", "pnl_usd", "return_pct", "units_total", "unit_usd", "unit_pct", "settled",
            "wagered_usd", "yield_pct", "max_drawdown_usd", "max_drawdown_pct", "currency", "basis",
            "events")             # units only: the page reprices the replay at the viewer's own unit size (unit_size.py)
    out = {k: block[k] for k in keep}
    out["label"] = bankroll.public_block()["label"]
    return out


def _summary(picks: list) -> dict:
    picks.sort(key=lambda p: (p["date"], p["game"], p["market"]))
    for p in picks:
        p["stake_units"] = _stake(p)
        p["usd"] = _usd(p)
    final = [p for p in picks if p["result"] in ("WIN", "LOSS", "PUSH")]
    for i, p in enumerate(final):
        p["ev"] = i       # this pick's place in ``bankroll.events`` (same order), so a page can price it at the viewer's sizing
    wins = sum(1 for p in final if p["result"] == "WIN")
    losses = sum(1 for p in final if p["result"] == "LOSS")
    pushes = sum(1 for p in final if p["result"] == "PUSH")
    voids = sum(1 for p in picks if p["result"] in ("VOID", "UNRESOLVED"))
    pending = sum(1 for p in picks if p["result"] is None)

    def total(key):
        vals = [p[key] for p in final if isinstance(p.get(key), (int, float))]
        return round(sum(vals), 2) if vals else None
    decided = [p for p in final if isinstance(p.get("units_average_price"), (int, float))]
    best = sorted([p for p in decided if p["result"] == "WIN"], key=lambda p: -p["usd"])[:3]
    worst = sorted([p for p in decided if p["result"] == "LOSS"], key=lambda p: p["usd"])[:3]
    by_day: dict = {}
    for p in decided:
        d = by_day.setdefault(p["date"], {"date": p["date"], "bets": 0, "units": 0.0, "usd": 0.0})
        d["bets"] += 1
        d["units"] = round(d["units"] + p["units_average_price"], 2)
        d["usd"] = round(d["usd"] + p["usd"], 2)
    n = len(final)
    return {
        "record": {"bets": len(picks), "graded": n, "wins": wins, "losses": losses, "pushes": pushes,
                   "voids": voids, "pending": pending},
        "units_average_price": total("units_average_price"), "units_best_price": total("units_best_price"),
        "bankroll": backtest_bankroll(final),
        "best": best, "worst": worst, "by_day": [by_day[d] for d in sorted(by_day)],
        "picks": picks[-PICKS_SHOWN:][::-1], "picks_total": len(picks),
        "small_sample": n < SMALL_N,
        "sample_note": (f"{n} graded {'bet' if n == 1 else 'bets'}: a small sample, so wins and losses this few "
                        "are mostly luck." if n < SMALL_N else
                        f"{n} graded bets. Even so, a rehearsal is not a forward result."),
    }


def _wrap(base: dict, *, dog: dict, rule: str, days: int, now: datetime, season: Optional[dict] = None) -> dict:
    first, last = _span(days, now)
    out = dict(base)
    out.update({"label": LABEL, "backtest_label": BACKTEST_LABEL, "disclosure": DISCLOSURE, "counted": False,
                "dog": dog, "rule_text": rule, "days": days, "window": {"first": first, "last": last},
                "season": season, "run_at": common.iso(now), "paper_only": True,
                "not_advice": user_spec.NOT_ADVICE})
    return out


def drill(*, days: int = 14, dog: Optional[common.Dog] = None, spec: Optional[dict] = None,
          now: Optional[datetime] = None, season: Optional[str] = None, **inject) -> dict:
    """Run a drill for a dog or a typed-in spec. Results are remembered for half an hour (same dog or spec, same
    days, same Eastern day) so the same button twice costs one pass. ``season`` (a season id) replaces ``days``
    with that season's completed days so far (``season_window``)."""
    now = now or common.now_utc()
    season_info = None
    if season:
        season_info = season_window(season, now)
        days = season_info["days"]
    else:
        window(days, now)                                     # validates the days before any work
    if (dog is None) == (spec is None):
        raise DrillError("target_required", "drill a dog (dog_id) or a rule (spec), not both and not neither", 422)
    if dog is not None:
        if getattr(dog, "forward_only", False):
            from src.hounds import ai_defs
            raise DrillError("ai_forward_only", ai_defs.forward_only_message(dog.id), 422)
        if dog.kind == common.KIND_USER:
            if user_spec.is_gematria(dog.spec):
                raise DrillError("gematria_forward_only", GEMATRIA_FORWARD_ONLY_MESSAGE, 422)
            hound = {"id": dog.id, "spec": dog.spec}
            ident = {"id": dog.id, "name": dog.name, "kind": "user"}
            rule = common.rule_english(dog)
            key = ("user", dog.id, user_spec.spec_hash(dog.spec))
        elif dog.kind == common.KIND_HOUSE:
            ident = {"id": dog.id, "name": dog.name, "kind": "house"}
            rule = common.rule_text(dog)
            key = ("house", dog.id)
            hound = None
        else:
            raise DrillError("not_drillable", f"{dog.name} cannot be drilled: only house dogs and builder dogs run a rule on demand", 422)
    else:
        norm = spec_from_request(spec)
        if user_spec.is_gematria(norm):
            raise DrillError("gematria_forward_only", GEMATRIA_FORWARD_ONLY_MESSAGE, 422)
        hound = {"id": "drill-" + user_spec.spec_hash(norm)[:10], "spec": norm}
        ident = {"id": None, "name": "Your rule", "kind": "spec"}
        rule = user_spec.rule_text(norm)
        key = ("spec", user_spec.spec_hash(norm))
    cache_key = key + (days, season_info and season_info["id"], common.eastern_date(now))
    if not inject:
        with _cache_lock:
            hit = _cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return hit[1]
    if not _drill_slot.acquire(blocking=False):
        raise DrillError("drill_busy", "another drill is running; try again in a moment", 429,
                         retry_after=BUSY_RETRY_AFTER_S)
    try:
        if ident["kind"] == "house":
            body = run_house(dog, days, now=now, **inject)
        else:
            body = run_user(hound, days, now=now, **inject)
    finally:
        _drill_slot.release()
        gc.collect()          # hand the replay's rows back now, not at the next collection, on a 1 GB machine
    out = _wrap(body, dog=ident, rule=rule, days=days, now=now, season=season_info)
    if not inject:
        with _cache_lock:
            if len(_cache) >= CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            _cache[cache_key] = (time.monotonic(), out)
    return out


def peek(dog: common.Dog, days: int, now: Optional[datetime] = None) -> Optional[dict]:
    """The remembered drill for this dog and window, or None. Free: it never touches the engine or the one-drill
    slot, so Ask can answer a repeat of a replay for anyone, signed in or not."""
    now = now or common.now_utc()
    if dog.kind == common.KIND_USER and dog.spec is not None:
        key = ("user", dog.id, user_spec.spec_hash(dog.spec))
    elif dog.kind == common.KIND_HOUSE:
        key = ("house", dog.id)
    else:
        return None
    with _cache_lock:
        hit = _cache.get(key + (days, common.eastern_date(now)))
        return hit[1] if hit and time.monotonic() - hit[0] < CACHE_TTL_S else None


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
