"""Probe the api-tennis.com Business-plan websocket feed
(wss://wss.api-tennis.com/live) to settle whether it changes check 9's
freshness verdict from docs/API_TENNIS_TRIAL_RESULTS.md.

Docs (fetched 2026-09-16, docs/documentation_websocket) show the JSON
message schema carries event/score/point-by-point/statistics fields only --
no odds, price, or suspended-flag field appears anywhere in the documented
schema. This script connects with the real trial key and records every
distinct message it receives for a bounded window, so the doc-based
conclusion is checked against what the vendor actually sends, not just what
its docs say it sends.

Writes newline-delimited JSON to --out (default
data/tennis_trial/ws_probe.jsonl): one record per received message with a
receipt timestamp and which of a fixed set of "price-shaped" field names
(odd, value, suspended, Set Betting, price) appear anywhere in it.

SECURITY: reads the key only via src.providers.api_tennis.client_from_env's
same .env-loading idiom (duplicated here, not imported, since this needs the
raw key string to build the wss:// query string -- never logged, never
written to --out, never included in any exception message).

ENVIRONMENT: requires SSL_CERT_FILE set in the process environment (this
machine's trust store is stale for this vendor). This script does NOT set
it and does NOT disable verification -- it builds a default ssl.SSLContext
via ssl.create_default_context(), which honours SSL_CERT_FILE when set by
the caller's shell.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.providers import ws_client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "tennis_trial" / "ws_probe.jsonl"
ENV_API_KEY = "API_TENNIS_KEY"
WS_URL_BASE = "wss://wss.api-tennis.com/live"

# Field names that would indicate this message carries pricing data, per the
# vendor's own REST field names (get_odds / get_live_odds use "odd",
# "value", "suspended"; "Set Betting" is the market name check 7 looks for).
_PRICE_FIELD_MARKERS = ("odd", "value", "suspended", "Set Betting", "price")


def _load_dotenv(path=None) -> None:
    env_file = Path(path) if path else REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _contains_price_marker(obj) -> list:
    """Walks the parsed JSON looking for any of _PRICE_FIELD_MARKERS as a
    dict key (case-sensitive, matching the vendor's own field spelling).
    Returns the list of markers found (empty if none)."""
    found = set()

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _PRICE_FIELD_MARKERS:
                    found.add(k)
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return sorted(found)


def run_probe(api_key: str, *, duration_seconds: float, out_path: Path,
              ssl_context: ssl.SSLContext, print_fn=print) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{WS_URL_BASE}?APIkey={api_key}&timezone=UTC"
    print_fn(f"connecting to {WS_URL_BASE} (query string withheld from output)...")
    client = ws_client.connect(url, ssl_context=ssl_context, timeout=20.0)
    print_fn("connected. handshake OK. listening...")

    deadline = time.monotonic() + duration_seconds
    message_count = 0
    price_marker_hits = 0
    distinct_event_keys = set()

    with out_path.open("a", encoding="utf-8") as fh:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            client._sock.settimeout(min(remaining, 30.0))
            try:
                message = client.recv_message()
            except (OSError, TimeoutError):
                continue
            if message is None:
                print_fn("server closed the connection.")
                break
            received_at = time.time()
            try:
                parsed = json.loads(message)
            except json.JSONDecodeError:
                parsed = None
            markers = _contains_price_marker(parsed) if parsed is not None else []
            if markers:
                price_marker_hits += 1
            event_key = None
            if isinstance(parsed, dict):
                event_key = parsed.get("event_key")
            elif isinstance(parsed, list):
                event_key = [m.get("event_key") for m in parsed if isinstance(m, dict)]
            if event_key is not None:
                if isinstance(event_key, list):
                    distinct_event_keys.update(e for e in event_key if e is not None)
                else:
                    distinct_event_keys.add(event_key)
            record = {
                "received_at": received_at,
                "price_markers_found": markers,
                "top_level_keys": sorted(parsed.keys()) if isinstance(parsed, dict) else None,
                "raw_len": len(message),
            }
            fh.write(json.dumps(record))
            fh.write("\n")
            fh.flush()
            message_count += 1
            if message_count % 10 == 0:
                print_fn(f"  {message_count} messages so far, {price_marker_hits} with price markers")

    client.close()
    print_fn(f"done. messages={message_count} price_marker_hits={price_marker_hits} "
             f"distinct_event_keys={len(distinct_event_keys)}")
    print_fn(f"wrote {out_path}")
    return 0


def main(argv=None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    api_key = (os.environ.get(ENV_API_KEY) or "").strip()
    if not api_key:
        print(f"{ENV_API_KEY} is not set")
        return 1

    ssl_context = ssl.create_default_context()
    try:
        return run_probe(api_key, duration_seconds=args.duration_seconds,
                          out_path=Path(args.out), ssl_context=ssl_context)
    except ws_client.WebSocketError as exc:
        print(f"websocket error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
