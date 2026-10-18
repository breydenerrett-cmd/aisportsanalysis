"""Fixture payloads for the Hounds pages, in the shape of the contract the API workers are building to.

NOT a test module (no test_ prefix). Used by tests/test_hounds_web_*.py and, run as a script, as a tiny
local server that serves web/ plus these payloads at the real URLs, so the three pages can be opened in a
browser before the real endpoints exist:

    python tests/hounds_web_fixtures.py            # http://127.0.0.1:8765/web/hounds.html
    python tests/hounds_web_fixtures.py --no-forward --port 8766

Every payload carries paper_only: true and a not-advice line. The numbers are made up and deterministic;
nothing here is a result of any real strategy.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

NOT_ADVICE = "Paper results only. Not advice. No real bet is placed."
BASIS = ("Forward results are paper bets placed after each rule was written; the verdict compares the price "
         "taken with the closing price using a test written before the race started.")

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
    ("rusty", "Rusty's Revenge", "stats", "grudge matches", "user", "TOO EARLY", 0, 40, "running", "Built by a reader."),
]


_FWD = {row[0]: row[6] for row in _HOUNDS}


def _lcg(seed: str):
    state = sum(ord(c) * (i + 3) for i, c in enumerate(seed)) % 2147483647 or 1
    while True:
        state = (state * 48271) % 2147483647
        yield state / 2147483647


def _points(hid: str, forward: bool):
    """cum_units_average_price / recorded / bets_settled / cum_clv_mean_pts for replay and (optionally) forward."""
    rnd = _lcg(hid)
    out = []
    avg = rec = 0.0
    clv_sum = 0.0
    n = 0
    start = date(2026, 9, 14)
    for i in range(30):
        d = start + timedelta(days=i)
        step = (next(rnd) - 0.5) * 2.4
        avg += step
        rec += step + 0.15
        n += 3
        clv_sum += (next(rnd) - 0.55) * 3
        out.append({"date": d.isoformat(), "cum_units_average_price": round(avg, 2),
                    "cum_units_recorded_price": round(rec, 2), "bets_settled": n,
                    "cum_clv_mean_pts": round(clv_sum / max(1, i + 1), 2), "segment": "replay"})
    if forward:
        avg = rec = 0.0
        n = 0
        clv_sum = 0.0
        fstart = date(2026, 10, 18)
        for i in range(7):
            d = fstart + timedelta(days=i)
            step = (next(rnd) - 0.5) * 1.6
            avg += step
            rec += step + 0.1
            n += 2
            clv_sum += (next(rnd) - 0.5) * 2
            out.append({"date": d.isoformat(), "cum_units_average_price": round(avg, 2),
                        "cum_units_recorded_price": round(rec, 2), "bets_settled": n,
                        "cum_clv_mean_pts": round(clv_sum / (i + 1), 2), "segment": "forward"})
    return out


def _record(bets: int, hid: str):
    rnd = _lcg(hid + "rec")
    wins = int(bets * (0.42 + next(rnd) * 0.12))
    pushes = 1 if bets > 20 else 0
    losses = bets - wins - pushes
    return {"bets": bets, "wins": wins, "losses": losses, "pushes": pushes, "voids": 0,
            "units_recorded_price": round((next(rnd) - 0.5) * 8, 2),
            "units_average_price": round((next(rnd) - 0.5) * 8 - 0.4, 2)}


def _clv(bets: int, hid: str, verdict: str = "TOO EARLY"):
    """CLV block whose sign agrees with the verdict, so the fixture never reads as self-contradicting."""
    if bets < 5:
        return None
    rnd = _lcg(hid + "clv")
    base = {"BEATING THE CLOSE": 1.4, "NO DIFFERENT FROM THE MARKET": 0.1, "TOO EARLY": 0.2, "PAYING THE VIG": -1.5}[verdict]
    mean = round(base + (next(rnd) - 0.5) * 0.4, 2)
    half = round(6 / (bets ** 0.5), 2)
    return {"n": bets, "mean_pts": mean, "ci_low": round(mean - half, 2), "ci_high": round(mean + half, 2)}


VERDICT_SENTENCES = {
    "BEATING THE CLOSE": "Prices taken were better than the closing prices by more than chance usually produces.",
    "NO DIFFERENT FROM THE MARKET": "Prices taken cannot be told apart from the closing prices.",
    "TOO EARLY": "Not enough settled bets for the test to say anything.",
    "PAYING THE VIG": "Prices taken were worse than the closing prices.",
}


def hounds(forward: bool = True):
    out = []
    for hid, name, cat, style, kind, verdict, fbets, rbets, status, tagline in _HOUNDS:
        fb = fbets if forward else 0
        series = _points(hid, forward and fbets > 0)
        spark_src = [p for p in series if p["segment"] == ("forward" if fb else "replay")]
        out.append({
            "id": hid, "name": name, "tagline": tagline, "kind": kind, "owner_display": "rusty_r" if kind == "user" else None,
            "category": cat, "style": style, "sport": ["mlb"], "markets": ["moneyline"],
            "rule_text": f"Bet the {style} side in MLB moneylines when the best price is between -200 and +250 "
                         f"and at least 4 books are posting; at most 3 bets a day; lock the price 30 minutes "
                         f"before the start. Never take a price of -200 or worse.",
            "status": status,
            "record": _record(fb, hid) if fb else {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
                                                   "units_recorded_price": 0, "units_average_price": 0},
            "clv": _clv(fb, hid, verdict),
            "forward": {"record": _record(fb, hid), "clv": _clv(fb, hid, verdict)} if fb else {"record": {"bets": 0}, "clv": None},
            "replay": {"record": _record(rbets, hid + "r"), "clv": _clv(rbets, hid + "r", verdict)},
            "verdict": {"label": verdict if fb or verdict == "TOO EARLY" else "TOO EARLY",
                        "sentence": VERDICT_SENTENCES[verdict if fb or verdict == "TOO EARLY" else "TOO EARLY"]},
            "first_bet_utc": "2026-10-18T19:05:00Z" if fb else None,
            "last_bet_utc": "2026-10-24T22:40:00Z" if fb else None,
            "verified": hid != "rusty",
            "spark": [p["cum_units_average_price"] for p in spark_src][-30:],
            "spark_segment": "forward" if fb else "replay",
        })
    return out


def leaderboard(forward: bool = True):
    return {"hounds": hounds(forward), "as_of": "2026-10-24T23:00:00Z", "basis": BASIS,
            "paper_only": True, "not_advice": NOT_ADVICE}


def series(ids, forward: bool = True):
    return {"series": {i: _points(i, forward and _FWD.get(i, 1) > 0) for i in ids}, "paper_only": True, "not_advice": NOT_ADVICE}


def stream():
    return {"items": [
        {"at": "2026-10-24T22:41:00Z", "hound_id": "closer", "hound_name": "Closer", "category": "stats", "who_decided": "rule",
         "summary": "Took NYY moneyline at -120: inside the price band, 5 books posting."},
        {"at": "2026-10-24T22:30:00Z", "hound_id": "poisson", "hound_name": "Poisson", "category": "math", "who_decided": "model",
         "summary": "Model gave BOS 54.1%; passed because the best price was -210, past the cap."},
        {"at": "2026-10-24T22:12:00Z", "hound_id": "coin-flip", "hound_name": "Coin Flip", "category": "random", "who_decided": "code",
         "summary": "Coin landed tails: took the away side, SEA +105."},
    ], "page": {"next": None}, "paper_only": True, "not_advice": NOT_ADVICE}


def graveyard():
    return {"hounds": [
        {"id": "old-faithful", "name": "Old Faithful", "cause": "Retired by its builder after 60 bets; the test could not separate it from the market.",
         "record": {"bets": 60, "wins": 28, "losses": 31, "pushes": 1}, "verdict": {"label": "NO DIFFERENT FROM THE MARKET"},
         "last_bet_utc": "2026-10-20T20:00:00Z", "status": "retired", "kind": "user", "category": "simple"},
    ], "paper_only": True, "not_advice": NOT_ADVICE}


def menu():
    return {"sports": [{"id": "mlb", "label": "MLB"}, {"id": "nfl", "label": "NFL"}],
            "markets": [{"id": "moneyline", "label": "Moneyline"}, {"id": "run_line", "label": "Run line / spread"},
                        {"id": "total", "label": "Game total"}],
            "side_rules": [{"id": "underdog", "label": "the underdog"}, {"id": "favourite", "label": "the favourite"},
                           {"id": "home", "label": "the home team"}, {"id": "away", "label": "the away team"}],
            "price_band": {"min": -200, "max": 400}, "books": {"min": 1, "max": 10},
            "max_bets_per_day": {"min": 1, "max": 5}, "lock_minutes": [15, 30, 60, 120],
            "paper_only": True, "not_advice": NOT_ADVICE}


def spec(hid="closer"):
    return {"spec": {"sports": ["mlb"], "markets": ["moneyline"], "side_rule": "underdog", "price_min": -150,
                     "price_max": 250, "min_books": 4, "max_bets_per_day": 3, "lock_minutes": 30},
            "paper_only": True, "not_advice": NOT_ADVICE}


def bets(hid="closer", n=45):
    rnd = _lcg(hid + "bets")
    out = []
    results = ["win", "loss", "loss", "win", "push", "void"]
    who = ["rule", "code", "model"]
    for i in range(n):
        d = date(2026, 10, 24) - timedelta(days=i // 3)
        res = results[int(next(rnd) * len(results))]
        out.append({"date": d.isoformat(), "game": f"NYY @ BOS #{i + 1}", "market": "moneyline",
                    "selection": "BOS" if i % 2 else "NYY", "price": -120 + (i % 7) * 25, "book": "BookA",
                    "consensus_fair": 0.52, "result": res,
                    "units": {"win": 0.83, "loss": -1.0, "push": 0.0, "void": 0.0}[res],
                    "clv_pts": round((next(rnd) - 0.5) * 4, 1), "who_decided": who[i % 3],
                    "reason": f"Inside the price band; {4 + i % 3} books posting.", "segment": "forward"})
    return out


def detail(hid="closer", forward=True, n=45):
    base = next(h for h in hounds(forward) if h["id"] == hid)
    return dict(base, bets=bets(hid, n), paper_only=True, not_advice=NOT_ADVICE)


def routes(forward: bool = True, bets_n: int = 45):
    """Map of 'path' -> (status, body) for every GET the pages make. Series is keyed by prefix."""
    r = {"/hounds": (200, leaderboard(forward)), "/hounds/stream": (200, stream()),
         "/hounds/graveyard": (200, graveyard()), "/hounds/menu": (200, menu()), "/hounds/mine": (200, {"hounds": [], "limit": 3})}
    for h in hounds(forward):
        r[f"/hounds/{h['id']}"] = (200, detail(h["id"], forward, bets_n))
        r[f"/hounds/{h['id']}/spec"] = (200, spec(h["id"]))
    return r


def respond(path_and_query: str, forward: bool = True):
    path, _, query = path_and_query.partition("?")
    if path == "/hounds/series":
        ids = [i for i in (dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("ids", "")).split(",") if i]
        return 200, series(ids, forward)
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
                return self._send(200, json.dumps({"id": "rusty", "name": body.get("name")}).encode(), "application/json")
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
