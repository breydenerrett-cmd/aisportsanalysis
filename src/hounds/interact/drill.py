"""The hindsight drill: a dog's rule replayed over the last 7, 14 or 30 days of stored boards.

LABELLED HINDSIGHT, NEVER COUNTED. The boards were captured before the rule was run over them, and the person
asking could see how those games ended when they chose the rule, so a drill is a rehearsal and not evidence.
It is written into a TEMPORARY ledger that is thrown away; the real ledgers are never opened for writing, so a
drill cannot reach a dog's record, the leaderboard, the referee or the learning loop. Every result carries
``counted: false`` and the words "Hindsight drill: not counted".

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
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

from src.hounds import user_engine, user_spec
from src.hounds.interact import common, fire
from src.ledger.chain import HashChainLedger

DAYS_CHOICES = (7, 14, 30)
LABEL = "Hindsight drill: not counted"
DISCLOSURE = ("This replays the dog's current rule over boards that were already captured. The rule was not live "
              "then, and you can see how those games ended, so this is a rehearsal and not evidence. It is "
              "never added to a record, a ranking or a verdict.")
SMALL_N = 30
PICKS_SHOWN = 40
CACHE_TTL_S = 1800.0
CACHE_MAX = 64

_cache: dict = {}
_cache_lock = threading.Lock()


class DrillError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, fields: Optional[dict] = None):
        self.code = code
        self.status = status
        self.fields = fields or {}
        super().__init__(message)


def window(days: int, now: datetime) -> tuple:
    """(first, last) Eastern dates: the last ``days`` completed days."""
    if days not in DAYS_CHOICES:
        raise DrillError("days_invalid", f"choose {', '.join(str(d) for d in DAYS_CHOICES)} days", 422)
    today = datetime.fromisoformat(common.eastern_date(now))
    last = (today - timedelta(days=1)).date()
    first = (today - timedelta(days=days)).date()
    return first.isoformat(), last.isoformat()


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
    first, last = window(days, now)
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
            "reason": b.get("reason")})
    return _summary(picks)


# ---------------------------------------------------------------------------
# house dogs
# ---------------------------------------------------------------------------

def run_house(dog: common.Dog, days: int, *, now: Optional[datetime] = None, stores=None) -> dict:
    from src.hounds import pack_run, pack_settle
    from src.hounds.learning import champions
    from src.hounds.pack import base
    now = now or common.now_utc()
    first, last = window(days, now)
    dates = [d for d in dates_between(first, last) if d >= base.SEAL_FLOOR and not base.in_seal(d)]
    if not dates:
        raise DrillError("sealed", "that window is inside the sealed period", 422)
    if stores is None:
        since = max(base.SEAL_FLOOR, base.day_before(min(dates), 8))
        until = (datetime.fromisoformat(common.eastern_date(now)) + timedelta(days=2)).date().isoformat()
        with fire._heavy():
            stores = base.load_stores(since=since, until=until)
    hound = champions.champion_versions((dog.house,), champions.events_path_beside(pack_run.ledger_path()))[0]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "drill.jsonl")
        pack_run.run(stores, dates, replay=True, now=now, path=path, hounds=[hound], out=lambda *_a, **_k: None)
        pack_settle.settle(stores, now=now, path=path)
        rows = HashChainLedger(path).read()
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

def _summary(picks: list) -> dict:
    picks.sort(key=lambda p: (p["date"], p["game"], p["market"]))
    final = [p for p in picks if p["result"] in ("WIN", "LOSS", "PUSH")]
    wins = sum(1 for p in final if p["result"] == "WIN")
    losses = sum(1 for p in final if p["result"] == "LOSS")
    pushes = sum(1 for p in final if p["result"] == "PUSH")
    voids = sum(1 for p in picks if p["result"] in ("VOID", "UNRESOLVED"))
    pending = sum(1 for p in picks if p["result"] is None)

    def total(key):
        vals = [p[key] for p in final if isinstance(p.get(key), (int, float))]
        return round(sum(vals), 2) if vals else None
    decided = [p for p in final if isinstance(p.get("units_average_price"), (int, float))]
    best = sorted([p for p in decided if p["result"] == "WIN"], key=lambda p: -p["units_average_price"])[:3]
    worst = sorted([p for p in decided if p["result"] == "LOSS"], key=lambda p: p["units_average_price"])[:3]
    by_day: dict = {}
    for p in decided:
        d = by_day.setdefault(p["date"], {"date": p["date"], "bets": 0, "units": 0.0})
        d["bets"] += 1
        d["units"] = round(d["units"] + p["units_average_price"], 2)
    n = len(final)
    return {
        "record": {"bets": len(picks), "graded": n, "wins": wins, "losses": losses, "pushes": pushes,
                   "voids": voids, "pending": pending},
        "units_average_price": total("units_average_price"), "units_best_price": total("units_best_price"),
        "best": best, "worst": worst, "by_day": [by_day[d] for d in sorted(by_day)],
        "picks": picks[-PICKS_SHOWN:][::-1], "picks_total": len(picks),
        "small_sample": n < SMALL_N,
        "sample_note": (f"{n} graded {'bet' if n == 1 else 'bets'}: a small sample, so wins and losses this few "
                        "are mostly luck." if n < SMALL_N else
                        f"{n} graded bets. Even so, a rehearsal is not a forward result."),
    }


def _wrap(base: dict, *, dog: dict, rule: str, days: int, now: datetime) -> dict:
    first, last = window(days, now)
    out = dict(base)
    out.update({"label": LABEL, "disclosure": DISCLOSURE, "counted": False, "dog": dog, "rule_text": rule,
                "days": days, "window": {"first": first, "last": last}, "run_at": common.iso(now),
                "paper_only": True, "not_advice": user_spec.NOT_ADVICE})
    return out


def drill(*, days: int, dog: Optional[common.Dog] = None, spec: Optional[dict] = None,
          now: Optional[datetime] = None, **inject) -> dict:
    """Run a drill for a dog or a typed-in spec. Results are remembered for half an hour (same dog or spec, same
    days, same Eastern day) so the same button twice costs one pass."""
    now = now or common.now_utc()
    window(days, now)                                         # validates the days before any work
    if (dog is None) == (spec is None):
        raise DrillError("target_required", "drill a dog (dog_id) or a rule (spec), not both and not neither", 422)
    if dog is not None:
        if dog.kind == common.KIND_USER:
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
        hound = {"id": "drill-" + user_spec.spec_hash(norm)[:10], "spec": norm}
        ident = {"id": None, "name": "Your rule", "kind": "spec"}
        rule = user_spec.rule_text(norm)
        key = ("spec", user_spec.spec_hash(norm))
    cache_key = key + (days, common.eastern_date(now))
    if not inject:
        with _cache_lock:
            hit = _cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return hit[1]
    if ident["kind"] == "house":
        body = run_house(dog, days, now=now, **inject)
    else:
        body = run_user(hound, days, now=now, **inject)
    out = _wrap(body, dog=ident, rule=rule, days=days, now=now)
    if not inject:
        with _cache_lock:
            if len(_cache) >= CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            _cache[cache_key] = (time.monotonic(), out)
    return out


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
