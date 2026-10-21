"""Strip what must not leave the building, before it is stored or sent anywhere.

The router refuses a prompt that looks like it holds an email, a phone number, a government id or a key
(src/ai/router.py `check_prompt`), and an interview is people typing about themselves ("text me at ..."), so
the refusal would be a regular event and every one would end the AI's part of the conversation. Removing the
text first keeps the guard as a net and not a gate. The replacement is a visible token, so the person can see
what was taken out and why the model never read it.

This runs on every free-text slot of every answer at intake: what is removed is never stored either.
"""

from __future__ import annotations

import re

from src.ai import router as ai_router

# A phone number: optional country code, then 3-3-4 digits with optional separators. Wider than the router's
# own pattern on purpose (it also catches "5551234567" and "(555)123-4567"), because the router's is the net.
_PHONE = re.compile(r"(?<![\d.])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?![\d])")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

REMOVED_EMAIL = "[email removed]"
REMOVED_PHONE = "[phone removed]"
REMOVED_ID = "[id removed]"
REMOVED_KEY = "[key removed]"


def strip_personal(text: str) -> str:
    """`text` with emails, phone numbers, government ids and key-shaped strings replaced by visible tokens."""
    out = str(text or "")
    out = _EMAIL.sub(REMOVED_EMAIL, out)
    out = _SSN.sub(REMOVED_ID, out)
    out = ai_router._REDACT_RE.sub(REMOVED_KEY, out)
    out = _PHONE.sub(REMOVED_PHONE, out)
    return out


def clean_text(text, *, limit: int) -> str:
    """Control characters out, whitespace tidied, personal data out, cut to `limit`. Newlines survive because a
    list typed one-per-line is how people give several skip rules."""
    raw = "".join(ch for ch in str(text or "") if ch >= " " or ch in "\n\t")
    lines = [" ".join(line.split()) for line in raw.replace("\r", "").split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return strip_personal(cleaned)[:limit]
