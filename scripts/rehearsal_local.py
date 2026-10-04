#!/usr/bin/env python3
"""LOCAL dry run of the purchase rehearsal, to prove scripts/rehearsal_watch.py
reads a REAL server's log before the owner does the staging click-through.

It starts uvicorn on 127.0.0.1 (never any other host), with a throwaway
database and the in-process Stripe stand-in (a synthetic `sk_test_synthetic_*`
key that can never be a real credential), plays the rehearsal's requests with
hand-signed webhooks, stops the server, and feeds the server's own log to the
watcher. Every secret here is a synthetic constant written in this file; no
real key is read, printed or needed, and no card is typed anywhere.

    python scripts/rehearsal_local.py            # port 8947
    python scripts/rehearsal_local.py --port 8950 --keep-log local.log

Exit 0 only when every required step reads PASS. This is LOCAL evidence: it
proves our code and the watcher agree on log lines, not that Stripe delivers.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.appstate import billing  # noqa: E402
import rehearsal_watch  # noqa: E402

WEBHOOK_SECRET = "whsec_local_rehearsal_synthetic"
ADMIN_TOKEN = "local-rehearsal-admin-synthetic"
PAID_THROUGH_EPOCH = 4070908800  # 2099-01-01, what the stand-in reports


def call(base, method, path, *, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, _json(raw)
    except urllib.error.HTTPError as err:
        return err.code, _json(err.read())


def _json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def signed_webhook(base, event):
    payload = json.dumps(event).encode("utf-8")
    stamp = int(time.time())
    digest = hmac.new(WEBHOOK_SECRET.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return call(base, "POST", "/billing/webhook", body=payload,
                headers={"Stripe-Signature": f"t={stamp},v1={digest}"})


def play(base):
    """The rehearsal's requests, in the owner's order."""
    out = []
    status, signup = call(base, "POST", "/signup", body={"email": "rehearsal-local@example.com"})
    out.append(("signup", status))
    user_id = signup["user_id"]
    customer, sub = billing.FAKE_TRANSPORT_CUSTOMER_ID, billing.FAKE_TRANSPORT_SUBSCRIPTION_ID
    out.append(("early success page", call(base, "GET", f"/signup/complete?session_id={billing.FAKE_TRANSPORT_SESSION_ID}")[0]))
    now = int(time.time())
    out.append(("webhook completed", signed_webhook(base, {
        "id": "evt_local_1", "type": "checkout.session.completed", "created": now,
        "data": {"object": {"id": billing.FAKE_TRANSPORT_SESSION_ID, "client_reference_id": str(user_id),
                            "customer": customer, "subscription": sub,
                            "payment_status": "no_payment_required"}}})[0]))
    out.append(("webhook subscription.created", signed_webhook(base, {
        "id": "evt_local_2", "type": "customer.subscription.created", "created": now,
        "data": {"object": {"id": sub, "customer": customer, "status": "active",
                            "created": now, "current_period_end": PAID_THROUGH_EPOCH}}})[0]))
    out.append(("webhook invoice.paid", signed_webhook(base, {
        "id": "evt_local_3", "type": "invoice.paid", "created": now,
        "data": {"object": {"id": "in_local_1", "customer": customer, "subscription": sub,
                            "status": "paid", "billing_reason": "subscription_create",
                            "lines": {"data": [{"subscription": sub,
                                                "period": {"end": PAID_THROUGH_EPOCH}}]}}}})[0]))
    status, got = call(base, "GET", f"/signup/complete?session_id={billing.FAKE_TRANSPORT_SESSION_ID}")
    out.append(("success page token", status))
    token = got["token"] if isinstance(got, dict) else ""
    auth = {"Authorization": f"Bearer {token}"}
    out.append(("success page re-read", call(base, "GET", f"/signup/complete?session_id={billing.FAKE_TRANSPORT_SESSION_ID}")[0]))
    out.append(("paid gate", call(base, "GET", "/ufc/fight-night", headers=auth)[0]))
    out.append(("cancel", call(base, "POST", "/billing/cancel", headers=auth)[0]))
    out.append(("webhook payment_failed", signed_webhook(base, {
        "id": "evt_local_4", "type": "invoice.payment_failed", "created": now + 5,
        "data": {"object": {"id": "in_local_2", "customer": customer, "subscription": sub,
                            "attempt_count": 1, "paid": False}}})[0]))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8947)
    parser.add_argument("--keep-log", help="also write the server log to this file")
    args = parser.parse_args(argv)
    base = f"http://127.0.0.1:{args.port}"
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "server.log"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("STRIPE_", "BILLING_", "APP_PUBLIC", "PUBLIC_BASE"))}
        env.update({
            "APP_DB_PATH": str(Path(tmp) / "app.db"), "APP_ADMIN_TOKEN": ADMIN_TOKEN,
            "BILLING_PROVIDER": "stripe", "STRIPE_FAKE_TRANSPORT": "1",
            "STRIPE_API_KEY": billing.FAKE_TRANSPORT_KEY_PREFIX + "_local_rehearsal",
            "STRIPE_BETA_PRICE_ID": billing.FAKE_TRANSPORT_PRICE_ID,
            "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
            "PUBLIC_BASE_URL": "https://rehearsal-local.example"})
        with open(log_path, "wb") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1",
                 "--port", str(args.port)], cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.time() + 180
                while time.time() < deadline:
                    if server.poll() is not None:
                        print("server exited early; see log", file=sys.stderr)
                        return 2
                    try:
                        if call(base, "GET", "/health")[0] == 200:
                            break
                    except (urllib.error.URLError, OSError):
                        pass
                    time.sleep(1)
                else:
                    print("server never became reachable", file=sys.stderr)
                    return 2
                steps = play(base)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    server.kill()
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if args.keep_log:
            Path(args.keep_log).write_text(text, encoding="utf-8")
    for name, status in steps:
        print(f"{name}: {status}")
    print()
    result = rehearsal_watch.scan(text.splitlines())
    print(rehearsal_watch.render(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
