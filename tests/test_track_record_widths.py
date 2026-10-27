"""The track record page fits a 375 and 390 px phone and a 1440 px desktop, in a real headless Chrome.

A local stub answers GET /hounds/{id}/record with payloads built by the real builder (src/hounds/track_record.py): a busy hound (three months of
bets, two sports, a long name, long reasons, a -200 ticket, open and stale tickets, a compare), a one-bet hound and an empty one. For each width it
measures that the document does not scroll sideways, that nothing runs past the screen, that long names and sentences wrap instead of being cut,
and that every section drew. Set LINEHOUND_RECORD_SHOTS=<dir> to also write full-page PNGs. Skipped without node and Chrome.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
import unittest
from urllib.parse import urlparse

from src.hounds import track_record as tr
from tests.test_no_horizontal_overflow import CHROME, HAS_NODE, HERE, ROOT
from tests.test_track_record import NOW, bet, data_of, defn

LONG = "Underdog Gus the Third of His Name and the Rather Long Title"
WHY = ("Home favourite between -150 and -110 with at least 5 books quoting, the starting pitcher rested, and the line steady for three hours "
       "before the lock, so the rule took it.")


def busy_bets():
    out = []
    n = 0
    for month, days in (("08", range(3, 29, 2)), ("09", range(1, 29, 3)), ("10", range(1, 20))):
        for d in days:
            for k in range(2):
                n += 1
                sport = "mlb" if (n % 3) else "nba"
                market = ("h2h", "spreads", "totals")[n % 3]
                side = ("home", "away")[n % 2] if market != "totals" else ("over", "under")[n % 2]
                sel = {"home": "Red Sox moneyline", "away": "Yankees moneyline", "over": "Over 8.5", "under": "Under 8.5"}[side]
                if market == "spreads":
                    sel = "Red Sox -1.5 run line" if side == "home" else "Yankees +1.5 run line"
                win = (n * 7 + k) % 5 in (0, 1, 2)
                out.append(bet(n, "win" if win else "loss", sport=sport, market=market, side=side, price=(-125, 135, -110, 150, -145)[n % 5],
                               date=f"2026-{month}-{d:02d}", selection=sel, reason=WHY if n % 4 == 0 else "",
                               start=f"2026-{month}-{d:02d}T23:{(n * 7) % 60:02d}:00Z"))
    out.append(bet(900, "win", price=-250, avg=-250, date="2026-10-19"))
    out.append(bet(901, None, date="2026-10-19", start="2026-10-27T23:30:00Z"))
    out.append(bet(902, None, date="2026-10-24", start="2026-10-25T23:30:00Z"))
    out.append(bet(903, None, date="2026-09-02", start="2026-09-02T23:30:00Z"))
    return out


def payload(bets, name, hid):
    p = tr.build(data_of(bets, defn("user", hid, name)).view("all"), as_of="2026-10-19", now=NOW)
    p["hound"]["id"] = hid
    p["season"] = {"id": "all", "label": "All-time", "available": [{"id": "s2", "label": "Season 2"}, {"id": "all", "label": "All-time"}]}
    p["compare"] = {"period": "All-time", "mine": {"n": p["header"]["settled"], "roi_pct": p["header"]["roi_pct"], "win_pct": 53.0, "clv": 0.4},
                    "house_pack": {"hounds": 4, "bets": 310, "roi_pct": 1.4, "win_pct": 51.5, "clv": 0.3},
                    "leaderboard": {"hounds": 12, "bets": 480, "roi_pct": -1.8, "win_pct": 49.6, "clv": None},
                    "note": "Each average is across hounds, over the same period."}
    if p["header"]["settled"] > 20:
        p["header"]["clv"] = {"n": 64, "mean_pts": 0.4}
    return p


def build_api():
    return {"/hounds/u-1/record": (200, payload(busy_bets(), LONG, "u-1")),
            "/hounds/u-2/record": (200, payload([bet(1, "win")], "One Bet Betty", "u-2")),
            "/hounds/u-3/record": (200, payload([], "Fresh Fido", "u-3"))}


def make_handler(api):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, *a):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith("/web/"):
                return super().do_GET()
            hit = api.get(path) or (404, {"detail": "not in the fixture"})
            body = json.dumps(hit[1], default=str).encode()
            self.send_response(hit[0])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheRecordFitsEveryWidth(unittest.TestCase):
    WIDTHS = (375, 390, 1440)
    PATHS = ["/web/record.html?id=u-1", "/web/record.html?id=u-2", "/web/record.html?id=u-3"]

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(build_api()))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        shots = os.environ.get("LINEHOUND_RECORD_SHOTS") or "-"
        prefix = os.environ.get("LINEHOUND_RECORD_PREFIX") or "record"
        proc = subprocess.run(["node", str(HERE / "track_record_widths.mjs"), CHROME, base, ",".join(str(w) for w in cls.WIDTHS), shots, prefix] + cls.PATHS,
                              capture_output=True, text=True, encoding="utf-8", timeout=600)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"record widths script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_every_page_drew_at_every_width(self):
        self.assertEqual(len(self.results), len(self.WIDTHS) * len(self.PATHS))
        for r in self.results:
            self.assertTrue(r["bodyShown"], r)
            self.assertEqual(r["iw"], r["width"], r)
            self.assertEqual(r["cards"], 5, r)

    def test_nothing_scrolls_sideways(self):
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1 or r["wide"]]
        self.assertEqual(bad, [], "wider than the screen: " + json.dumps(bad, indent=1))

    def test_long_names_and_sentences_wrap_instead_of_being_cut(self):
        self.assertEqual([r for r in self.results if r["cut"]], [], "text cut off")
        self.assertTrue(all(r["title"].startswith(LONG) for r in self.results if r["path"].endswith("u-1")))

    def test_the_busy_hound_has_its_curve_months_and_tickets(self):
        for r in (r for r in self.results if r["path"].endswith("u-1")):
            self.assertEqual((r["svgs"], r["months"]), (1, 3), r)
            self.assertGreater(r["tickets"], 50, r)


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
