"""Temporary beta legal disclaimer, as a backend concern.

WHY THIS EXISTS
----------------
docs/LAUNCH_DECISIONS.md, DECIDED BY BREY 2026-09-01, item 4: a temporary,
clearly-labeled beta disclaimer is required now (information/research
product, no outcome/profit guarantees, users responsible for their own
wagering decisions). FINAL customer-facing legal copy is explicitly
flagged for Brey/counsel review before paid/public launch -- this module
is NOT that final copy. It exists so every surface that shows the
disclaimer (GET /meta today, a future UI banner) reads it from one place
instead of each surface inventing its own wording, and so the day counsel
signs off on final copy there is exactly one constant to replace.

id="beta-v1" and requires_final_legal_review=True are load-bearing, not
decoration: a caller (or a future test) can gate paid-launch readiness on
requires_final_legal_review flipping to False, which only happens when
someone deliberately edits this file after real legal review -- it can
never flip itself.

Stdlib only, like the rest of src/analysis/ -- see
tests/test_api_boundary.py for the rule this keeps.
"""

from __future__ import annotations

DISCLAIMER_ID = "beta-v1"

# The three statements DECIDED BY BREY requires, worded plainly and kept
# free of the tout vocabulary tests/test_customer_language.py bans project
# wide (no "guaranteed", no "edge", no claim that the product wins bets).
BETA_DISCLAIMER = (
    "BETA -- TEMPORARY NOTICE, PENDING FINAL LEGAL REVIEW. "
    "This product provides sports-betting information and research. "
    "It does not guarantee outcomes or profits, for any user or any bet. "
    "You are solely responsible for your own wagering decisions, including "
    "whether to bet at all. Nothing here is a betting edge, a locked-in "
    "result, or a guarantee of any outcome -- it is information to inform "
    "a decision you make and own."
)


def get_disclaimer() -> dict:
    """The disclaimer as a machine-readable payload for API responses.

    A fresh dict on every call -- callers (e.g. api/meta.py) may embed
    this in a larger JSON response; handing back a shared mutable object
    would let one caller's mutation leak into another's response.
    """
    return {
        "id": DISCLAIMER_ID,
        "temporary": True,
        "requires_final_legal_review": True,
        "text": BETA_DISCLAIMER,
    }
