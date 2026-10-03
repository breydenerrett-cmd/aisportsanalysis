"""Cleaning for the acquisition-attribution fields the browser sends.

WHAT THIS IS FOR
-----------------
Every anonymous funnel event used to share one hashed sentinel, and the
campaign tags on the landing URL (utm_source, ...) died on the landing page:
they never reached the signup request, the account row, the Stripe Checkout
Session, or the paid event. "Which channel produced a paying subscriber" was
unanswerable. The browser now keeps a random per-visitor id and the FIRST
touch's UTM tags + referrer host in localStorage and sends them with the
signup (web/js/attribution.js); this module is the one place the server
decides what of that it will believe and keep.

WHAT IS KEPT AND WHAT IS NOT
-----------------------------
Only the keys in ALLOWED_KEYS, only strings, whitespace-trimmed, capped at
MAX_VALUE_LENGTH characters, and only characters from a conservative set --
these values end up as event properties, SQL parameters and Stripe metadata
values, and a public endpoint must not let a crafted link stuff arbitrary
text into any of them. `anon_id` must look like the random id the client
generates (letters, digits, `_`, `-`, 16-64 long) or it is dropped. No IP, no
user agent, no full referrer URL (host only), nothing derived or joined.
"""

from __future__ import annotations

import re
from typing import Dict, Mapping, Optional

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
ALLOWED_KEYS = UTM_KEYS + ("referrer_host",)
MAX_VALUE_LENGTH = 64

# Printable, URL-ish characters only. A UTM value is a tag a human typed into
# a link ("reddit", "spring_launch", "r/sportsbook"); anything outside this
# set (control characters, angle brackets, quotes) is dropped rather than
# stored, because it has never been a real tag.
_VALUE_RE = re.compile(r"^[A-Za-z0-9 _.\-/:+%@~]+$")
_ANON_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")

# OUR OWN TEST TRAFFIC IS NOT A CUSTOMER. A utm_source that is exactly
# "internal" or starts with "internal-" (internal-test, internal-brey, ...)
# marks a link the owner sent himself to walk the funnel. The funnel report
# (api/funnel.py) leaves those events out of every step, and the tester
# activity report (src/appstate/activation.py) leaves those users out of every
# count, from this ONE rule so the two cannot disagree. The hyphen matters:
# "international-bettors" is a customer.
INTERNAL_SOURCE = "internal"


def is_internal_source(value: object) -> bool:
    """True when `value` is a utm_source tagged as our own test traffic."""
    if not isinstance(value, str):
        return False
    value = value.strip().lower()
    return value == INTERNAL_SOURCE or value.startswith(INTERNAL_SOURCE + "-")


def clean_anon_id(raw: object) -> Optional[str]:
    """The client's random visitor id, or None if it is not shaped like one."""
    if isinstance(raw, str) and _ANON_ID_RE.match(raw.strip()):
        return raw.strip()
    return None


def clean_attribution(raw: object) -> Dict[str, str]:
    """`raw` reduced to the attribution fields this app keeps ({} for
    anything that is not a mapping). Keys: the UTM tags, `referrer_host`, and
    `anon_id`. Values that fail validation are dropped individually -- one bad
    tag does not discard the good ones next to it."""
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, str] = {}
    for key in ALLOWED_KEYS:
        value = raw.get(key)
        if not isinstance(value, str):
            continue
        value = value.strip()[:MAX_VALUE_LENGTH]
        if value and _VALUE_RE.match(value):
            out[key] = value
    anon = clean_anon_id(raw.get("anon_id"))
    if anon:
        out["anon_id"] = anon
    return out


def stripe_metadata(attribution: Mapping) -> Dict[str, str]:
    """The Checkout Session `metadata[...]` form fields for `attribution`.

    Stripe metadata keys are at most 40 characters and values at most 500;
    every key and value here is well inside both. `anon_id` is included so a
    payment can be tied back to the funnel's anonymous events."""
    return {f"metadata[{key}]": str(value)
            for key, value in (attribution or {}).items() if value}
