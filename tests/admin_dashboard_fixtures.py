"""Fixture payloads for the admin dashboard (web/admin.html), in the shapes api/admin.py,
api/funnel.py and api/support.py send. NOT a test module (no test_ prefix).

Used by tests/test_admin_dashboard.py and, run as a script, as a tiny local server that serves web/
and these payloads at the real URLs, so the page can be opened in a browser without the API:

    python tests/admin_dashboard_fixtures.py            # http://127.0.0.1:8766/web/admin.html
    token: fixture-token

Everything is made up and deterministic relative to ``now``: the people are example.test addresses,
the counts are small on purpose (the page must say a small sample is small), and the POSTs answer
with a canned token that is obviously fake.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_TOKEN = "fixture-token"
ISSUED_TOKEN = "lh_FIXTURE_ACCESS_TOKEN_0123456789abcdef"


def iso(moment: datetime) -> str:
    return moment.isoformat()


def build(now: datetime | None = None) -> dict:
    """GET path -> payload, every date relative to ``now``."""
    now = now or datetime.now(timezone.utc)
    ago = lambda **kw: iso(now - timedelta(**kw))          # noqa: E731
    ahead = lambda **kw: iso(now + timedelta(**kw))        # noqa: E731

    # ---- people -------------------------------------------------------------------------------
    users = [
        # id, email, status, plan, joined, tester?, tester_expires, comp?, comp_revoked?
        (14, "wes.waiting@example.test", "waitlisted", "none", ago(hours=5), False, None, False, False),
        (13, "nora.next@example.test", "waitlisted", "none", ago(days=1, hours=2), False, None, False, False),
        (12, "tim.tester@example.test", "active", "none", ago(days=3), True, ahead(hours=30), False, False),
        (11, "tess.tester@example.test", "active", "none", ago(days=4), True, ahead(days=5), False, False),
        (10, "old.tester@example.test", "active", "none", ago(days=12), True, ago(days=2), False, False),
        (9, "fran.free@example.test", "active", "none", ago(days=6), False, None, True, False),
        (8, "flo.former@example.test", "active", "none", ago(days=9), False, None, False, True),
        (7, "pat.payer@example.test", "active", "beta", ago(days=20), False, None, False, False),
        (6, "sam.suspended@example.test", "suspended", "none", ago(days=21), False, None, False, False),
        (5, "ivy.invited@example.test", "invited", "none", ago(days=22), False, None, False, False),
        (4, "pete.pending@example.test", "pending_payment", "none", ago(days=2), False, None, False, False),
        (3, "will.waiting@example.test", "waitlisted", "none", ago(days=7), False, None, False, False),
        (2, "wanda.waiting@example.test", "waitlisted", "none", ago(days=8), False, None, False, False),
        (1, "wyatt.waiting@example.test", "waitlisted", "none", ago(days=9), False, None, False, False),
    ]
    users_payload = {"users": [
        {"id": u[0], "email": u[1], "status": u[2], "plan": u[3], "created_at": u[4], "tester": u[5],
         "tester_granted_at": ago(days=5) if u[5] else None, "tester_expires_at": u[6],
         "comp": u[7], "comp_revoked": u[8]} for u in users]}

    def tester(uid, email, expires, last_active):
        return {"user_id": uid, "email": email, "status": "active", "granted_at": ago(days=5),
                "expires_at": expires, "first_used_at": ago(days=4), "extensions": [],
                "activated": True, "last_active_at": last_active, "active_days": 2, "returning": False,
                "features": {"card": 2}}
    testers_payload = {"testers": [
        tester(12, "tim.tester@example.test", ahead(hours=30), ago(hours=3)),
        tester(11, "tess.tester@example.test", ahead(days=5), ago(days=1)),
        tester(10, "old.tester@example.test", ago(days=2), ago(days=3)),
    ], "granted": 3, "limit": 20, "remaining": 17, "ttl_days": 7}

    comps_payload = {"comps": [
        {"user_id": 9, "email": "fran.free@example.test", "status": "active", "granted_at": ago(days=6),
         "reason": "friend of the project", "granted_by": "admin", "revoked_at": None,
         "revoked_reason": None, "first_used_at": ago(days=5), "active": True},
        {"user_id": 8, "email": "flo.former@example.test", "status": "active", "granted_at": ago(days=9),
         "reason": "early signup", "granted_by": "admin", "revoked_at": ago(days=2),
         "revoked_reason": "asked to leave", "first_used_at": None, "active": False},
    ], "active": 1, "token_years": 10}

    # ---- overview -----------------------------------------------------------------------------
    daily = {}
    for i in range(13, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily[day] = {"landing_view": 6 + (i * 5) % 17, "public_page_view": 2 + (i * 3) % 7,
                      "signup_started": 1 + i % 3}
        if i % 3 != 1:
            daily[day]["account_created"] = 1 + (i % 2)
    store = lambda age, rows: {"present": True, "rows": rows, "newest_row_age_seconds": age,   # noqa: E731
                               "newest_row_utc": ago(seconds=age), "status": "ok", "reason": None}
    overview = {
        "users": {"total": len(users), "by_status": {"waitlisted": 5, "active": 6, "suspended": 1,
                                                      "invited": 1, "pending_payment": 1},
                  "by_plan": {"none": 13, "beta": 1}},
        "invites_outstanding": 1,
        "events": {"daily_counts_by_kind": daily},
        "store_health": {
            "status": "degraded", "generated_at": iso(now), "process": {"status": "ok"},
            "app_db": {"reachable": True, "path": "/data/app/app.db", "reason": None},
            "odds": {"odds_multibook": store(2 * 3600 + 840, 18234)},
            "forward_captures": {
                "odds_snapshots": store(5 * 3600, 90211),
                "f5_close": store(40 * 3600, 3310),
                "prop_listing": store(5 * 86400, 12001),
                "probables_watch": {"present": True, "rows": 0, "newest_row_age_seconds": None, "newest_row_utc": None,
                                    "status": "empty", "reason": "probables_watch.jsonl exists but holds no rows"},
                "transactions_watch": {"present": False, "rows": None, "newest_row_age_seconds": None,
                                       "newest_row_utc": None, "status": "missing",
                                       "reason": "transactions_watch.jsonl is absent -- nothing has been captured yet"},
                "lineups_watch": {"present": True, "rows": 12, "newest_row_age_seconds": None, "newest_row_utc": None,
                                  "status": "unreadable",
                                  "reason": "lineups_watch.jsonl holds 12 row(s) but none carry a parseable fetched_utc"},
            },
            "data_freshness": {"baseball_date": "2026-10-18", "expected_through": "2026-10-18", "core_stale": False,
                               "stale": ["standings"], "oldest_core_through": "2026-10-17",
                               "stores": {"results": {"through": "2026-10-18", "lag_days": 0, "stale": False, "reason": None},
                                          "standings": {"through": "2026-10-12", "lag_days": 6, "stale": True,
                                                        "reason": "standings are 6 days behind"}},
                               "guard": {"enabled": True}},
            "checkout": {"status": "off", "provider": "null", "mode": None,
                         "reason": "billing provider is the null provider; no payment can be taken"},
            "reasons": ["lineups_watch: lineups_watch.jsonl holds 12 row(s) but none carry a parseable fetched_utc"],
        },
        "version": "0.9.3-fixture",
    }

    funnel = {
        "start": (now - timedelta(days=13)).strftime("%Y-%m-%d"), "end": now.strftime("%Y-%m-%d"),
        "steps": [
            {"kind": "landing_view", "count": 212, "conversion_from": None, "conversion_pct_from_previous": None},
            {"kind": "cta_click", "count": 61, "conversion_from": "landing_view", "conversion_pct_from_previous": 28.8},
            {"kind": "free_bet_check", "count": 24, "conversion_from": "landing_view", "conversion_pct_from_previous": 11.3},
            {"kind": "signup_started", "count": 33, "conversion_from": "cta_click", "conversion_pct_from_previous": 54.1},
            {"kind": "account_created", "count": 14, "conversion_from": "signup_started", "conversion_pct_from_previous": 42.4},
            {"kind": "checkout_started", "count": 0, "conversion_from": "account_created", "conversion_pct_from_previous": 0.0},
            {"kind": "checkout_completed", "count": 0, "conversion_from": "checkout_started", "conversion_pct_from_previous": None},
            {"kind": "invite_redeemed", "count": 3, "conversion_from": "checkout_completed", "conversion_pct_from_previous": None},
            {"kind": "bet_check_run", "count": 9, "conversion_from": "invite_redeemed", "conversion_pct_from_previous": 300.0},
            {"kind": "bet_saved", "count": 2, "conversion_from": "bet_check_run", "conversion_pct_from_previous": 22.2},
        ],
        "by_source": {"reddit-mlb": {"landing_view": 120, "account_created": 6},
                      "x-thread": {"landing_view": 70, "signup_started": 9, "account_created": 5},
                      "internal-test": {"landing_view": 22}},
        "page_views": {"sample": {"views": 40, "unique_visitors": 31,
                                  "by_source": {"reddit-mlb": {"views": 25, "unique_visitors": 20}}}},
        "internal_events_excluded": 22,
    }

    support = {"messages": [
        {"id": 3, "user_id": None, "email": "asker@example.test", "subject": "Lost my access code",
         "body": "I closed the tab before I copied it.\nCan you send a new one?", "created_at": ago(hours=6),
         "status": "open", "answered_at": None},
        {"id": 2, "user_id": 11, "email": None, "subject": "Odds look old on the card",
         "body": "The Dodgers price has not moved since this morning.", "created_at": ago(days=2),
         "status": "answered", "answered_at": ago(days=1, hours=20)},
        {"id": 1, "user_id": None, "email": "thanks@example.test", "subject": "Thanks",
         "body": "Nice work.", "created_at": ago(days=6), "status": "closed", "answered_at": ago(days=5)},
    ]}

    revenue = {"price_cents": 1999, "paying": 1, "trialing": 0, "cancel_scheduled": 0, "canceled": 0,
               "unpaid": 0, "mrr_cents": 1999, "mrr_gross_cents": 1999, "mrr_usd": 19.99,
               "signups_total": len(users), "signups_by_source": {"(direct)": 14},
               "paying_by_source": {"(direct)": 1}, "trialing_by_source": {}}

    return {
        "/admin/overview": overview, "/admin/users": users_payload, "/admin/testers": testers_payload,
        "/admin/comps": comps_payload, "/admin/funnel": funnel, "/admin/support": support,
        "/admin/revenue": revenue,
    }


def issued(email: str, *, kind: str = "tester", expires: str | None = None) -> dict:
    """What a grant / re-issue answers: the access token ONCE."""
    return {"user_id": 99, "email": email, "token": ISSUED_TOKEN, "kind": kind,
            "expires_at": expires or iso(datetime.now(timezone.utc) + timedelta(days=7)),
            "testers_granted": 4, "testers_limit": 20, "revoked_tokens": 1}


# ---------------------------------------------------------------------------------------------
# A tiny server: serves web/ and the GET fixtures; POSTs answer with a canned response.
# ---------------------------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    payloads = build()

    def log_message(self, *args):  # quiet
        pass

    def _json(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _admin_ok(self):
        if self.headers.get("X-Admin-Token") == FIXTURE_TOKEN:
            return True
        self._json(401, {"detail": {"error": "unauthorized", "message": "bad admin token"}})
        return False

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/admin/"):
            if self._admin_ok():
                body = self.payloads.get(path)
                self._json(200 if body is not None else 404, body if body is not None else {"detail": "Not Found"})
            return
        rel = path[len("/web/"):] if path.startswith("/web/") else path.lstrip("/")
        target = (ROOT / "web" / rel).resolve()
        if not str(target).startswith(str(ROOT / "web")) or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        kinds = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kinds.get(target.suffix, "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._admin_ok():
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?")[0]
        if path in ("/admin/testers", "/admin/testers/extend", "/admin/comps", "/admin/users/reissue"):
            kind = "comp" if path == "/admin/comps" else "tester"
            self._json(200, issued(body.get("email") or f"user{body.get('user_id')}@example.test", kind=kind))
        elif path == "/admin/comps/revoke" or path.startswith("/admin/support/"):
            self._json(200, {"ok": True})
        else:
            self._json(404, {"detail": "Not Found"})


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8766
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"http://127.0.0.1:{port}/web/admin.html  (admin token: {FIXTURE_TOKEN})", flush=True)
    server.serve_forever()
