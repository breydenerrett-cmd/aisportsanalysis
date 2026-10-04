#!/usr/bin/env python3
"""Watch staging log lines while the owner does the purchase rehearsal.

Usage (the parent runs this; the owner never needs to):

    fly logs -a linehound-staging | python scripts/rehearsal_watch.py
    fly logs -a linehound-staging --no-tail > staging.log
    python scripts/rehearsal_watch.py staging.log --since 2026-10-04T19:00:00Z

It reads log lines (stdin, or a file), prints one line the first time each
rehearsal step is seen, and a PASS / NOT SEEN table at the end (end of input,
or Ctrl-C when piped from a live `fly logs`). Exit status 0 only when every
required step passed. It never makes a network call and never needs a secret.

WHAT IT MATCHES: only lines the code really emits today.

  * the request log, api/app.py through src/appstate/reqlog.py:
        method=POST path=/billing/webhook status=200 latency_ms=3.1 user=-
    `path` is the route template; `user` is `-` or 16 hex characters.
  * the webhook line, src/appstate/billing.py (apply_stripe_webhook_event):
        billing: webhook type='invoice.paid' event='evt_...' user=<16 hex|-> paid_through='...'|- status='active'|-
    One per processed event except invoice.payment_failed, which has its own:
        billing: invoice.payment_failed user=<16 hex|-> subscription='sub_...' attempt='1'
  * failure lines: `billing: checkout|cancel|reactivate provider call failed ...`

WHAT IT CANNOT SEE (no line is written today, so nothing is invented):
  * a checkout session being CREATED. The only trace is the request line for
    POST /signup, /billing/checkout or /billing/tester-checkout with status 200,
    and that is 200 even when billing answers "not configured" or "error". The
    step is therefore labelled weak; `checkout.session.completed` arriving is the
    proof that a session existed and was paid.
  * the Stripe-hosted page, the card form, and Stripe's own dashboard.

Fly prefixes each line with a timestamp and ANSI colour codes, and can glue two
log writes onto one line; matching is done with re.finditer over the whole line
so both are tolerated.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from typing import Iterable, List, Optional

ANSI = re.compile(r"\x1b?\[\d+(?:;\d+)*m")
FLY_TS = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")
USER = r"(-|[0-9a-f]{16})"
REQUEST = re.compile(
    r"method=([A-Z]+) path=(\S+) status=(\d{3}) latency_ms=[\d.]+ user=" + USER)
WEBHOOK = re.compile(
    r"billing: webhook type='([^']*)' event='([^']*)' user=" + USER
    + r" paid_through=(-|'[^']*') status=(-|'[^']*')")
FAILED = re.compile(
    r"billing: invoice\.payment_failed user=" + USER
    + r" subscription=(\S+) attempt=(\S+)")
PROVIDER_FAILED = re.compile(r"billing: (checkout|cancel|reactivate) provider call failed")

CHECKOUT_PATHS = ("/signup", "/billing/checkout", "/billing/tester-checkout")

# (key, label, required). Order is the order the owner does them in.
STEPS = [
    ("checkout_requested", "checkout requested (request line only; weak, see doc)", True),
    ("session_completed", "checkout.session.completed processed", True),
    ("invoice_paid", "invoice.paid processed", True),
    ("access_granted", "access granted: paid_through set by a payment event", True),
    ("gate_open", "paid gate opened: GET /ufc/fight-night 200 (or 503, no UFC data) for a signed-in user", True),
    # Not required: the browser cannot reach the re-read after the tab is closed (signup.js drops the
    # session id from the address after the first read; review 2026-10-04). Seen only if that changes.
    ("return_after_close", "optional: return after closing the success page: second /signup/complete 200", False),
    ("cancel", "cancel: POST /billing/cancel 200 for a signed-in user", True),
    ("payment_failed", "invoice.payment_failed processed (decline case)", True),
    ("gate_refused", "optional: paid gate refused after expiry (402)", False),
]
LABEL = {key: label for key, label, _ in STEPS}
REQUIRED = {key: req for key, _, req in STEPS}


class Result:
    """First matching line per step, plus any warnings."""

    def __init__(self) -> None:
        self.seen: dict = {}
        self.warnings: List[str] = []
        self._complete_200s = 0
        self._after_session = False

    def mark(self, key: str, line: str) -> Optional[str]:
        if key in self.seen:
            return None
        self.seen[key] = line
        return key

    def passed(self, key: str) -> bool:
        return key in self.seen

    @property
    def ok(self) -> bool:
        return all(self.passed(k) for k, req in REQUIRED.items() if req)


def _clean(line: str) -> str:
    return ANSI.sub("", line).rstrip("\r\n")


def _line_time(line: str) -> Optional[datetime]:
    match = FLY_TS.match(ANSI.sub("", line))
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_since(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def feed(result: Result, raw: str, *, since: Optional[datetime] = None) -> List[str]:
    """Apply one raw log line to `result`; return the step keys newly seen."""
    when = _line_time(raw)
    if since is not None and when is not None and when < since:
        return []
    line = _clean(raw)
    new: List[str] = []

    def mark(key: str) -> None:
        if result.mark(key, line) is not None:
            new.append(key)

    for match in PROVIDER_FAILED.finditer(line):
        result.warnings.append(f"WARN billing provider call failed ({match.group(1)}): {line.strip()[:200]}")

    for match in WEBHOOK.finditer(line):
        event_type, _event_id, _user, paid_through, _status = match.groups()
        if event_type == "checkout.session.completed":
            mark("session_completed")
            result._after_session = True
        elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
            mark("invoice_paid")
        if paid_through != "-" and event_type in (
                "invoice.paid", "invoice.payment_succeeded",
                "customer.subscription.created", "customer.subscription.updated"):
            mark("access_granted")

    if FAILED.search(line):
        mark("payment_failed")

    for match in REQUEST.finditer(line):
        method, path, status, user = match.groups()
        status_n = int(status)
        if method == "POST" and path in CHECKOUT_PATHS and status_n == 200:
            mark("checkout_requested")
        elif method == "GET" and path == "/signup/complete" and status_n == 200:
            result._complete_200s += 1
            if result._after_session and result._complete_200s >= 2:
                mark("return_after_close")
        elif method == "GET" and path == "/ufc/fight-night":
            # 503 ("UFC data is not readable right now") is also past the
            # paid gate; staging may hold no UFC data (PURCHASE_REHEARSAL.md).
            if status_n in (200, 503) and user != "-":
                mark("gate_open")
            elif status_n == 402 and user != "-":
                mark("gate_refused")
        elif method == "POST" and path == "/billing/cancel" and status_n == 200 and user != "-":
            mark("cancel")
        elif path == "/billing/webhook" and status_n in (400, 501):
            result.warnings.append(
                f"WARN webhook answered {status_n} (signature or secret problem): {line.strip()[:200]}")
        elif path.startswith("/billing") and status_n >= 500:
            result.warnings.append(f"WARN {method} {path} answered {status_n}: {line.strip()[:200]}")
    return new


def scan(lines: Iterable[str], *, since: Optional[datetime] = None) -> Result:
    result = Result()
    for raw in lines:
        feed(result, raw, since=since)
    return result


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def render(result: Result) -> str:
    out = []
    for key, label, required in STEPS:
        if result.passed(key):
            out.append(f"PASS      {label}")
            out.append(f"            {_ascii(result.seen[key].strip())[:220]}")
        else:
            out.append(f"NOT SEEN  {label}" + ("" if required else "  (not required)"))
    for warning in result.warnings:
        out.append(_ascii(warning))
    out.append("RESULT: " + ("ALL REQUIRED STEPS PASSED" if result.ok else "STEPS STILL MISSING"))
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("logfile", nargs="?", help="log file to read; stdin when omitted")
    parser.add_argument("--since", help="ignore Fly-timestamped lines older than this ISO time")
    args = parser.parse_args(argv)
    since = parse_since(args.since) if args.since else None
    stream = open(args.logfile, encoding="utf-8", errors="replace") if args.logfile else sys.stdin
    result = Result()
    try:
        for raw in stream:
            for key in feed(result, raw, since=since):
                print(_ascii(f"PASS      {LABEL[key]}"), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if args.logfile:
            stream.close()
    print()
    print(render(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
