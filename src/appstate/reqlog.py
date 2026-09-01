"""Structured per-request log lines for the api/ layer, stdlib-only.

WHY THIS IS ITS OWN MODULE
---------------------------
api/app.py's middleware has to call something on every single request, so
that something needs to be cheap, dependency-free, and testable without
spinning up a server -- the same reason api/auth.py's dependency functions
are unit-tested by calling them directly rather than through a live HTTP
client (this repo's starlette build has no TestClient-compatible HTTP
client installed; see tests/test_api_auth.py's module docstring). Keeping
the line-formatting and redaction logic here, as plain functions over
plain values, means the middleware itself stays a thin adapter and the
formatting can be asserted on by string content in a normal unittest.

WHAT MUST NEVER APPEAR IN A LOG LINE
--------------------------------------
Bearer tokens, emails, and request/response bodies. A log line is the one
piece of this system that routinely ends up somewhere with looser access
control than the database it describes (shipped to a log aggregator,
tailed over SSH by whoever is debugging, pasted into a bug report) -- so it
follows the same rule src/appstate/users.py already states for the token
store itself: the raw secret exists in exactly one place, and this must
never be the second. `user_ref` therefore takes an already-authenticated
user's id and hashes it (never logs the id, the email, or the token that
produced it) so two lines from the same user correlate without the log
ever naming who that user is.

WHY THE PATH IS A TEMPLATE, NOT THE RAW URL
----------------------------------------------
`/game/2026-08-31/NYY/BOS` and `/game/2026-09-01/LAD/SD` are two requests
to the same endpoint; logging the raw path turns every access log into a
practically-unbounded set of distinct "paths" and makes per-endpoint
latency/error aggregation impossible without a second parsing pass. FastAPI
already knows the route's template (`/game/{date}/{away}/{home}`) once
routing has resolved -- api/app.py's middleware reads it off
`request.scope["route"].path` and hands it here, so this module never has
to invent its own URL-templating logic or risk getting it wrong.
"""

from __future__ import annotations

import hashlib
from typing import Optional

# How much of the id hash to keep. Sixteen hex characters (64 bits) is
# enough to tell two users apart across a log stream's realistic size
# without pretending this is a cryptographic identifier; it exists to
# correlate lines, not to authenticate anything.
USER_HASH_LENGTH = 16


def user_ref(user_id: Optional[int]) -> Optional[str]:
    """A short, irreversible-in-practice reference for a request's
    authenticated user, or None when the request was anonymous.

    Hashing the user's integer id (never the raw bearer token, which never
    reaches this module) is enough to let two log lines be recognised as
    "the same caller" without the log itself becoming a second place a
    user's identity can be read from -- the same non-reversibility
    src/appstate/users.py relies on for tokens, applied to the id instead.
    """
    if user_id is None:
        return None
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return digest[:USER_HASH_LENGTH]


def format_line(*, method: str, path_template: str, status: int,
                 latency_ms: float, user_id: Optional[int] = None,
                 error_id: Optional[str] = None) -> str:
    """One structured line: `key=value` pairs, space-separated, stderr-safe
    (no embedded newlines -- a path template or method never contains one,
    and this function does not accept freeform strings that could).

    `key=value` rather than JSON is a deliberate choice for a line that a
    human tails directly during local dev and smoke testing (deploy/README.md);
    a log aggregator that wants JSON can still parse this format trivially,
    and nothing here forecloses adding a JSON formatter later if a specific
    host's log pipeline needs one.
    """
    fields = [
        f"method={method}",
        f"path={path_template}",
        f"status={status}",
        f"latency_ms={latency_ms:.1f}",
        f"user={user_ref(user_id) or '-'}",
    ]
    if error_id:
        fields.append(f"error_id={error_id}")
    return " ".join(fields)


# Header/field names that must never be echoed into a log line, kept here
# (rather than duplicated at each call site) so the ban is one list to
# audit, not a convention every future caller has to remember on its own.
FORBIDDEN_LOG_SUBSTRINGS = ("bearer ", "authorization", "@")


def contains_forbidden_content(line: str) -> bool:
    """True if a log line looks like it leaked a token, an auth header, or
    an email address. Used by tests as a blunt but honest guard -- it does
    not prove a line is safe, only catches the specific shapes this module
    must never produce.
    """
    lowered = line.lower()
    return any(marker in lowered for marker in FORBIDDEN_LOG_SUBSTRINGS)
