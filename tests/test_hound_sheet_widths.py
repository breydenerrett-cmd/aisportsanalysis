"""The hound sheet (the studio drawer every hound opens in) fits a 375 and 390 px phone and a 1440 px desktop, in a real headless Chrome.

For each tab (Record, Rules, Rules with the editor open, Unleash, Backtest, Look) of the Gematria Hound, a hound with an open ticket and a hound
with a very long name, it measures: the page does not scroll sideways; nothing inside the sheet runs past the screen (the Rules tab's example
chip used to); the sheet and its body do not scroll sideways; the full name and the record line are not cut; the tab bar is sticky, scrolls
inside itself and has the chosen tab in view.

Set LINEHOUND_SHEET_SHOTS=<dir> to also write the screenshots (before/after evidence for the owner). Skipped without node and Chrome.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
import unittest
from urllib.parse import urlparse

from tests import hounds_web_fixtures as F
from tests.test_kennel_page import TheStudio, dog, kit, mine
from tests.test_no_horizontal_overflow import CHROME, HAS_NODE, HERE, ROOT

LONG = "Underdog Gus the Third of His Name and the Rather Long Title"
RULE = "Bet home underdogs between +120 and +200 when they are on 2+ days rest, at most 2 bets a day."


def _rows(n, open_n, hid):
    from src.hounds import contract
    out = []
    for i, row in enumerate(F.bet_rows("closer", n + open_n)):
        item = contract.to_json(row)
        item.update(hound_id=hid, event_id=f"ev-{hid}-{i}", game=f"Boston Red Sox at New York Yankees #{i}", selection=f"Boston Red Sox to win #{i}")
        if i < open_n:
            item.update(result=None, units=None, clv_pts=None, status="OPEN")
        else:
            item.update(result="loss", units=-1.0)
        out.append(item)
    return out


def build_api():
    from src.hounds import user_spec
    from tests import _hounds_rules_fixtures as F2
    events = [["2026-10-22", 1761120000, -1.0, 1.0, "l"], ["2026-10-23", 1761206400, 0.83, 1.0, "w"], ["2026-10-24", 1761292800, -1.0, 1.0, "l"],
              ["2026-10-25", 1761379200, -1.0, 1.0, "l"]]
    gem = dog("u-1", "Gematria Hound", wins=1, losses=3, bets=4, units=-2.17, version_no=3, style="gematria")
    gem["bankroll"] = dict(gem["bankroll"], start=2500.0, current=2445.75, pnl_usd=-54.25, return_pct=-2.17, unit_usd=25.0, events=events, small_sample=True)
    doc = dog("u-2", "Doctor Data Dog", open_bets=1, bets=0, version_no=1)
    doc["bankroll"] = dict(doc["bankroll"], start=2500.0, current=2500.0, pnl_usd=0.0, return_pct=0.0, unit_usd=25.0, events=[])
    long = dog("u-3", LONG, wins=2, losses=2, bets=4, units=0.4, version_no=12)
    dogs = [gem, doc, long]
    mine_dogs = []
    for d in dogs:
        m = {"id": d["id"], "name": d["name"], "tagline": "", "status": "running", "version_no": d["version_no"], "color": "mint", "badge": "crown",
             "record": d["record"], "rule_sentences": [RULE]}
        m["spec"] = json.loads(json.dumps(user_spec.validate_spec(F2.v2(name=d["name"][:24], rules=[F2.rule(side="away", price_min=100)]))))
        mine_dogs.append(m)
    status, body = mine(dogs)
    body["kennel_name"] = "Gus and Company Kennel"
    api = {"/hounds/kennels/mine": (status, body), "/hounds/mine": (200, {"hounds": mine_dogs, "limit_running": 5}),
           "/hounds/builder/menu": (200, json.loads(json.dumps(user_spec.builder_menu()))),
           "/hounds/live/status": (200, {"awaiting_final": 18, "final_ungraded": 0, "last_graded_utc": "2026-10-26T17:46:00Z"})}
    for d in dogs:
        api[f"/hounds/{d['id']}/kit"] = (200, kit(d["id"], name=d["name"]))
        api[f"/hounds/{d['id']}/manual"] = (200, {"tickets": [], "record": {}, "limit_per_day": 5})
        api[f"/hounds/{d['id']}/ask"] = (200, {"greeting": ["Woof. Ask me about my bets."], "suggestions": ["Why that pick?"]})
    return api


def make_handler(api):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, *a):
            pass

        def _send(self, status, payload):
            body = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            path = url.path
            if path.startswith("/web/"):
                return super().do_GET()
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "hounds" and parts[2] == "bets":
                hid = parts[1]
                is_open = "status=open" in (url.query or "")
                if hid == "u-2":
                    items = _rows(0, 1, hid) if is_open else _rows(0, 1, hid)
                else:
                    items = [] if is_open else _rows(3, 0, hid)
                return self._send(200, {"items": items, "total": len(items)})
            hit = api.get(path)
            if hit is None:
                hit = (404, {"detail": "not in the fixture"})
            return self._send(*hit)

        def do_POST(self):
            path = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            if path.endswith("/fire"):
                return self._send(200, {"headline": "Nothing qualifies right now.", "picks": [], "closest_misses": [], "recorded": [], "notes": [],
                                        "preview_note": "Paper only.", "viewer_is_owner": True,
                                        "slate": {"counts_line": "11 games today · 4 started · 7 checked now", "groups": [], "line": ""}})
            if path.endswith("/drill"):
                from tests.test_backtest_kennel_web import result
                return self._send(200, result(days=7))
            if path.endswith("/builder/preview"):
                return self._send(200, {"qualifying": 0, "would_bet": 0, "picks": [], "sentences": [], "max_bets_per_day": 2, "paper_only": True})
            return self._send(404, {"detail": "not in the fixture"})

    return Handler


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheSheetFitsEveryWidth(unittest.TestCase):
    WIDTHS = (375, 390, 1440)
    JOBS = ["u-1:record", "u-1:rules", "u-1:rules-edit", "u-1:fire", "u-1:backtest", "u-1:look", "u-2:record", "u-2:fire", "u-3:record", "u-3:rules-edit"]

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(build_api()))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        shots = os.environ.get("LINEHOUND_SHEET_SHOTS") or "-"
        prefix = os.environ.get("LINEHOUND_SHEET_PREFIX") or "after"
        proc = subprocess.run(["node", str(HERE / "hound_sheet_widths.mjs"), CHROME, base, ",".join(str(w) for w in cls.WIDTHS), shots, prefix] + cls.JOBS,
                              capture_output=True, text=True, encoding="utf-8", timeout=600)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"sheet script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_every_tab_was_measured_with_the_sheet_open(self):
        self.assertEqual(len(self.results), len(self.WIDTHS) * len(self.JOBS))
        for r in self.results:
            self.assertTrue(r["studioOpen"], r)
            self.assertEqual(r["iw"], r["width"], r)

    def test_nothing_scrolls_sideways(self):
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1 or r["wide"] or r["bodySw"] > r["bodyCw"] + 1 or r["studioSw"] > r["studioCw"] + 1]
        self.assertEqual(bad, [], "wider than the screen: " + json.dumps(bad, indent=1))

    def test_the_full_name_and_record_line_are_never_cut(self):
        bad = [r for r in self.results if r["titleCut"] or r["subCut"]]
        self.assertEqual(bad, [], json.dumps(bad, indent=1))
        long_names = [r["title"] for r in self.results if r["path"].startswith("u-3")]
        self.assertTrue(long_names and all(t == LONG for t in long_names), long_names)

    def test_the_tab_bar_is_sticky_and_keeps_the_chosen_tab_in_view(self):
        for r in self.results:
            self.assertEqual(r["tabsPos"], "sticky", r)
            self.assertTrue(r["activeVisible"], r)
        narrow = [r for r in self.results if r["width"] < 700]
        self.assertTrue(all(r["tabsSw"] > r["tabsCw"] for r in narrow), "on a phone the bar scrolls sideways inside itself")


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
