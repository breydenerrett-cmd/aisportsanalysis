"""Fixture payloads for the Hounds pages, BUILT BY THE REAL CONTRACT CODE.

NOT a test module (no test_ prefix). Used by tests/test_hounds_web_*.py and, run as a script, as a tiny
local server that serves web/ plus these payloads at the real URLs, so the three pages can be opened in a
browser without the API:

    python tests/hounds_web_fixtures.py            # http://127.0.0.1:8765/web/hounds.html
    python tests/hounds_web_fixtures.py --no-forward --port 8766

WHY THIS FILE WAS REWRITTEN (2026-10-18). The first version hand-wrote the payloads from a guess at the
contract (``forward`` / ``replay`` sub-objects, a ``sport`` list, ``summary`` text on stream items, a
``cause`` string on the graveyard, ``bets`` as a list, a menu of ``{id, label}`` and ``price_band``). The
pages passed against those guesses and would have shown an empty race against the real API. Every payload
here now comes out of ``src.hounds.contract`` (the dataclasses and payload builders the API routes call)
and ``src.hounds.user_spec.menu()``, so a field the pages read must be a field the contract has.

Every payload carries paper_only: true and the not-advice line. The numbers are made up and deterministic;
nothing here is a result of any real strategy.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from src.hounds import contract, user_spec, verdict as vd
from src.hounds.contract import (
    BetRow, ClvBlock, HoundSummary, Record, ReplayBlock, RetiredBlock, SeriesPoint, StreamItem,
    VerdictBlock, paginate)

# (id, name, category, style, kind, verdict label, forward bets, replay bets, status, tagline)
_HOUNDS = [
    ("closer", "Closer", "stats", "form and rest", "house", "BEATING THE CLOSE", 41, 160, "running", "Takes the price before it moves."),
    ("steamer", "Steamer", "market", "follows the line", "house", "NO DIFFERENT FROM THE MARKET", 38, 150, "running", "Rides early line moves."),
    ("almanac", "Almanac", "history", "head to head", "house", "TOO EARLY", 6, 90, "running", "Old matchups, new night."),
    ("poisson", "Poisson", "math", "run model", "house", "PAYING THE VIG", 44, 170, "running", "A model that shows its work."),
    ("vibes", "Vibes", "intangibles", "travel and rest", "house", "TOO EARLY", 5, 70, "running", "Tired teams, in theory."),
    ("moon-dog", "Moon Dog", "esoteric", "lunar phase", "house", "NO DIFFERENT FROM THE MARKET", 22, 95, "running", "Howls at the full moon."),
    ("coin-flip", "Coin Flip", "random", "control", "house", "PAYING THE VIG", 30, 120, "running", "A coin picks. The control."),
    ("blend", "Blend", "mixed", "three signals", "house", "TOO EARLY", 8, 80, "benched", "A little of everything."),
    ("plain-jane", "Plain Jane", "simple", "one rule", "house", "NO DIFFERENT FROM THE MARKET", 35, 140, "running", "One rule, no fuss."),
    ("always-fave", "Always Favourite", "baseline", "yardstick", "house", "PAYING THE VIG", 50, 200, "running", "Always the favourite, up to the cap."),
    ("always-dog", "Always Underdog", "baseline", "yardstick", "house", "PAYING THE VIG", 50, 200, "running", "Always the underdog."),
    ("home-field", "Home Field", "simple", "one rule", "house", "TOO EARLY", 9, 60, "running", "Home teams, nothing else."),
    ("rusty", "Rusty's Revenge", "mixed", "follows line moves", "user", "TOO EARLY", 0, 40, "running", "Built by a reader."),
]

_FWD = {row[0]: row[6] for row in _HOUNDS}
AS_OF = "2026-10-24"
BASIS = contract.BASIS


def _lcg(seed: str):
    state = sum(ord(c) * (i + 3) for i, c in enumerate(seed)) % 2147483647 or 1
    while True:
        state = (state * 48271) % 2147483647
        yield state / 2147483647


def _series_objs(hid: str, forward: bool) -> list:
    """The hound's FORWARD series as the contract has it (stats.build_series): a zero point the day before the
    first graded day, then one point per day with graded bets. ``bets_settled`` is that DAY's count, not a
    running total; the CLV mean is null until 20 measurable bets (verdict.CLV_SERIES_MIN_BETS)."""
    fb = _FWD.get(hid, 1) if forward else 0
    if fb <= 0:
        return []
    rnd = _lcg(hid)
    start = date(2026, 10, 18)
    days = min(7, fb)
    per_day = [fb // days] * days
    per_day[-1] += fb - sum(per_day)
    out = [SeriesPoint(date=(start - timedelta(days=1)).isoformat(), cum_units_average_price=0.0,
                       cum_units_recorded_price=0.0, bets_settled=0, cum_clv_mean_pts=None)]
    avg = rec = clv_sum = 0.0
    total = 0
    for i, count in enumerate(per_day):
        step = (next(rnd) - 0.5) * 1.6
        avg += step
        rec += step + 0.1
        total += count
        clv_sum += (next(rnd) - 0.5) * 2
        out.append(SeriesPoint(date=(start + timedelta(days=i)).isoformat(),
                               cum_units_average_price=round(avg, 2), cum_units_recorded_price=round(rec, 2),
                               bets_settled=count,
                               cum_clv_mean_pts=round(clv_sum / (i + 1), 2) if total >= vd.CLV_SERIES_MIN_BETS else None))
    return out


def _record(bets: int, hid: str) -> Record:
    rnd = _lcg(hid + "rec")
    wins = int(bets * (0.42 + next(rnd) * 0.12))
    pushes = 1 if bets > 20 else 0
    return Record(bets=bets, wins=wins, losses=bets - wins - pushes, pushes=pushes, voids=0,
                  units_recorded_price=round((next(rnd) - 0.5) * 8, 2),
                  units_average_price=round((next(rnd) - 0.5) * 8 - 0.4, 2))


def _clv(bets: int, hid: str, label: str):
    """CLV block whose sign agrees with the verdict, so the fixture never reads as self-contradicting."""
    if bets < 5:
        return None
    rnd = _lcg(hid + "clv")
    base = {"BEATING THE CLOSE": 1.4, "NO DIFFERENT FROM THE MARKET": 0.1, "TOO EARLY": 0.2, "PAYING THE VIG": -1.5}[label]
    mean = round(base + (next(rnd) - 0.5) * 0.4, 2)
    half = round(6 / (bets ** 0.5), 2)
    return ClvBlock(n=bets, mean_pts=mean, ci_low=round(mean - half, 2), ci_high=round(mean + half, 2))


VERDICT_SENTENCES = {
    "BEATING THE CLOSE": "The price it took beat the closing market by 1.40 points on average (95% interval 0.60 to 2.20) over 160 bets.",
    "NO DIFFERENT FROM THE MARKET": "Over 160 bets its price was +0.10 points from the closing market on average (95% interval -0.60 to 0.80); that cannot be told apart from zero.",
    "TOO EARLY": "Only 6 of its bets have a measurable closing price. At least 150 are needed before this means anything.",
    "PAYING THE VIG": "The price it took was worse than the closing market by 1.50 points on average (95% interval -2.30 to -0.70) over 170 bets.",
}


def _rule_text(style: str) -> str:
    return (f"Bet the {style} side in MLB moneylines when the average price across the books is between "
            f"-150 and +250 and at least 4 books are quoting it; at most 3 bets a day; the price is locked "
            f"60 minutes before first pitch. Never takes a price of -200 or worse.")


def summaries(forward: bool = True) -> list:
    """HoundSummary objects (the real dataclass) for every fixture hound."""
    out = []
    for hid, name, cat, style, kind, label, fbets, rbets, status, tagline in _HOUNDS:
        fb = fbets if forward else 0
        shown = label if fb else vd.TOO_EARLY
        series = _series_objs(hid, forward)
        replay = _record(rbets, hid + "r")
        out.append(HoundSummary(
            id=hid, name=name, tagline=tagline, kind=kind, category=cat, style=style,
            owner_display="Handler 3F2A" if kind == "user" else None, sports=["mlb"], markets=["moneyline"],
            rule_text=_rule_text(style), status=status, retired=None,
            record=_record(fb, hid) if fb else Record(),
            clv=_clv(fb, hid, shown) if fb else None,
            verdict=VerdictBlock(label=shown, sentence=VERDICT_SENTENCES[shown],
                                 units_note=vd.units_note(fb)),
            first_bet_utc="2026-10-18T19:05:00Z" if fb else None,
            last_bet_utc="2026-10-24T22:40:00Z" if fb else None,
            verified=hid != "rusty", verified_share=0.97 if hid != "rusty" and fb else None,
            checkable_share=1.0 if fb else None,
            replay=ReplayBlock(bets=rbets, wins=replay.wins, losses=replay.losses, pushes=replay.pushes,
                               voids=0, units_recorded_price=replay.units_recorded_price),
            spark=[p.cum_units_average_price for p in series][-30:], spark_basis="average_price",
            source="fixture"))
    return out


def hounds(forward: bool = True) -> list:
    return [contract.to_json(s) for s in summaries(forward)]


def leaderboard(forward: bool = True) -> dict:
    return contract.leaderboard_payload(summaries(forward), AS_OF)


def series(ids, forward: bool = True) -> dict:
    return contract.series_payload({i: _series_objs(i, forward) for i in ids}, AS_OF)


def stream() -> dict:
    items = [
        StreamItem(hound_id="closer", hound_name="Closer", date="2026-10-24", game="Yankees at Red Sox", market="moneyline",
                   selection="Yankees to win", price=-115, price_average=-120, book="bookB", who_decided="rule",
                   reason="Rule: the underdog. It backed the away side at the board average of -120 across 5 books.",
                   segment="forward", verdict="play", refused=False, decided_utc="2026-10-24T22:41:00Z"),
        StreamItem(hound_id="poisson", hound_name="Poisson", date="2026-10-24", game="Mariners at Astros", market="moneyline",
                   selection="(no bet)", who_decided="code", reason="Refused: too few books were quoting this market to trust a price.",
                   segment="forward", verdict="refused_thin", refused=True, decided_utc="2026-10-24T22:30:00Z"),
        StreamItem(hound_id="coin-flip", hound_name="Coin Flip", date="2026-10-24", game="Padres at Dodgers", market="total",
                   selection="Over 8.5", line="8.5", price=100, price_average=-108, book="bookA", who_decided="model",
                   reason="Seeded coin flip: over. A control.", segment="forward", verdict="play", refused=False,
                   decided_utc="2026-10-24T22:12:00Z"),
    ]
    return contract.stream_payload(paginate(items, 1, 25), AS_OF)


def graveyard() -> dict:
    s = HoundSummary(
        id="old-faithful", name="Old Faithful", tagline="Retired after a long run.", kind="user", category="mixed",
        style="underdogs", owner_display="Handler 9C01", sports=["mlb"], markets=["moneyline"],
        rule_text=_rule_text("underdog"), status="retired",
        retired=RetiredBlock(date="2026-10-20", cause="retired by the owner"),
        record=Record(bets=60, wins=28, losses=31, pushes=1, voids=0, units_recorded_price=-3.1, units_average_price=-4.0),
        clv=None, verdict=VerdictBlock(label="TOO EARLY", sentence=VERDICT_SENTENCES["TOO EARLY"], units_note=vd.units_note(60)),
        last_bet_utc="2026-10-20T20:00:00Z", spark=[], spark_basis="average_price", source="fixture")
    return contract.graveyard_payload([s], AS_OF)


def menu() -> dict:
    """The REAL menu, from the function GET /hounds/menu returns."""
    out = dict(user_spec.menu())
    return out


_SPEC = dict(name="Closer", tagline="Takes the price before it moves.", sports=["MLB"], markets=["moneyline"],
             side_rule="underdog", price_min=-150, price_max=250, min_books=4, max_bets_per_day=3, lock_minutes=60)


def spec(hid="closer") -> dict:
    """The REAL answer of GET /hounds/{id}/spec (api/hounds_create.py hound_spec): a spec to POST back, with a fresh name."""
    valid = user_spec.validate_spec(_SPEC)
    valid.pop("version", None)
    valid["name"] = "Closer II"
    return {"spec": valid, "copied_from": hid, "rule_text": user_spec.rule_text(user_spec.validate_spec(_SPEC)),
            "how": "POST /hounds with {\"spec\": <this spec>, \"copied_from\": <copied_from>}",
            "paper_only": True, "not_advice": user_spec.NOT_ADVICE}


def bet_rows(hid="closer", n=45) -> list:
    rnd = _lcg(hid + "bets")
    out = []
    results = ["win", "loss", "loss", "win", "push", "void"]
    who = ["rule", "code", "model"]
    for i in range(n):
        d = date(2026, 10, 24) - timedelta(days=i // 3)
        res = results[int(next(rnd) * len(results))]
        out.append(BetRow(
            hound_id=hid, date=d.isoformat(), game=f"NYY at BOS #{i + 1}", market="h2h",
            selection="Red Sox to win" if i % 2 else "Yankees to win", price=-115 + (i % 7) * 25,
            price_average=-120 + (i % 7) * 25, book="bookA", consensus_fair=0.52, result=res,
            units={"win": 0.83, "loss": -1.0, "push": 0.0, "void": 0.0}[res],
            clv_pts=round((next(rnd) - 0.5) * 4, 1), who_decided=who[i % 3],
            reason=f"Inside the price band; {4 + i % 3} books posting.",
            segment="forward" if hid != "rusty" else "replay"))
    return out


def bets(hid="closer", n=45) -> list:
    return [contract.to_json(b) for b in bet_rows(hid, n)]


def bets_payload(hid="closer", n=45, page=1, page_size=25, segment=None) -> dict:
    rows = [b for b in bet_rows(hid, n) if segment is None or b.segment == segment]
    return contract.bets_payload(hid, paginate(rows, page, page_size), AS_OF)


def detail(hid="closer", forward=True, n=45) -> dict:
    s = next(x for x in summaries(forward) if x.id == hid)
    return contract.hound_payload(s, _series_objs(hid, forward), paginate(bet_rows(hid, n), 1, 25), AS_OF)


def routes(forward: bool = True, bets_n: int = 45) -> dict:
    """Map of 'path' -> (status, body) for every GET the pages make. Series is keyed by prefix."""
    r = {"/hounds": (200, leaderboard(forward)), "/hounds/stream": (200, stream()),
         "/hounds/graveyard": (200, graveyard()), "/hounds/menu": (200, menu()),
         "/hounds/mine": (200, {"hounds": [], "limit_running": 3, "paper_only": True, "not_advice": user_spec.NOT_ADVICE})}
    for h in summaries(forward):
        r[f"/hounds/{h.id}"] = (200, detail(h.id, forward, bets_n))
        r[f"/hounds/{h.id}/spec"] = (200, spec(h.id))
        r[f"/hounds/{h.id}/bets"] = (200, bets_payload(h.id, bets_n))
    return r


def respond(path_and_query: str, forward: bool = True):
    path, _, query = path_and_query.partition("?")
    params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
    if path == "/hounds/series":
        ids = [i for i in params.get("ids", "").split(",") if i]
        return 200, series(ids, forward)
    if path.endswith("/bets") and path.startswith("/hounds/"):
        hid = path[len("/hounds/"):-len("/bets")]
        if hid in _FWD:
            return 200, bets_payload(hid, 45, int(params.get("page", 1)), int(params.get("page_size", 25)),
                                     params.get("segment"))
    return routes(forward).get(path, (404, {"detail": "Not Found"}))


def _serve(port: int, forward: bool):  # pragma: no cover - manual tool
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    web = Path(__file__).resolve().parent.parent / "web"
    types = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path
            if path.startswith("/hounds"):
                status, payload = respond(path, forward)
                return self._send(status, json.dumps(payload).encode(), "application/json")
            if path.startswith("/web/"):
                rel = path[len("/web/"):].split("?")[0]
                f = (web / rel).resolve()
                if web in f.parents and f.is_file() and f.suffix in types:
                    return self._send(200, f.read_bytes(), types[f.suffix])
            self._send(404, b'{"detail":"Not Found"}', "application/json")

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/hounds":
                spec_body = body.get("spec") or {}
                return self._send(200, json.dumps({"hound": {"id": "rusty", "name": spec_body.get("name")}}).encode(),
                                  "application/json")
            self._send(404, b'{"detail":"Not Found"}', "application/json")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"serving on http://127.0.0.1:{port}/web/hounds.html", flush=True)
    srv.serve_forever()


if __name__ == "__main__":  # pragma: no cover
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    _serve(port, forward="--no-forward" not in sys.argv)
