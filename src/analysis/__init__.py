"""Analysis layer: derived, read-only views over the point-in-time stores.

Modules here consume the same audited inputs the research layer uses -- the
pitch store, the posted-lineup store, the handedness cache -- and reshape them
into plain-dict briefing sections. Nothing in this package touches the
network, writes a store, or fits anything: it observes, attaches the sample
behind every number, and says so explicitly when it cannot.

THE FALSIFICATION COUNT LIVES HERE, ONCE -- AND IT IS READ, NOT TYPED
---------------------------------------------------------------------
Every product surface states how much has been tested and survived, because
that sentence is the product. It was stated in three places with three
different numbers -- the briefing header said "Thirteen" (V1 only), the
Ranker banner said "Twenty-four" (pre-V5), the per-game note said "27" --
and two of those appeared on the SAME rendered page. So the count became one
constant that every surface reads.

Then the constant drifted too. On 2026-09-12 a Bet Check result read, in
block 07, "41 pre-registered hypotheses have been measured and none has
survived" (from the registry, via GET /meta) and, in block 10 on the same
screen, "27 pre-registered hypotheses across four families" (from the
constant below). A reader who notices that the page cannot count its own
losers has no reason to believe anything else on it.

The old comment defended the constant as a closed historical record. That
is why it drifted: a number nobody expects to change is a number nobody
re-checks. The registry -- data/research/alpha_registry.jsonl -- IS the
closed record, so it is read here at import and every surface follows. The
figures typed below are the LAST KNOWN values, used only when the registry
cannot be read at all, and `COUNTS_FROM_REGISTRY` says which happened so a
test or a page can tell.
"""

from __future__ import annotations

# What the registry said the last time someone looked. A fallback for a
# container with no data/ tree, never the primary source. Update these when
# they are visibly stale; a test compares them to the registry.
# The READ count, not the registered one: on 2026-09-12 the registry held
# 42 registrations of which 5 (four V3 forward-window tests and V7) had no
# verdict yet. The product had been saying 41 "tested"; 37 had been.
_LAST_KNOWN_HYPOTHESES = 37
_LAST_KNOWN_FAMILIES = 6

_UNITS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
          "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety")


def number_word(n: int) -> str:
    """0..99 in words, lowercase, hyphenated: 41 -> "forty-one".

    Prose on several surfaces reads better with a word than a numeral, and
    the word used to be typed by hand beside the numeral -- which is how
    "Twenty-seven" outlived 27.
    """
    n = int(n)
    if n < 0 or n > 99:
        return str(n)
    if n < 20:
        return _UNITS[n]
    tens, units = divmod(n, 10)
    return _TENS[tens] if units == 0 else f"{_TENS[tens]}-{_UNITS[units]}"


def research_counts() -> dict:
    """{"hypotheses", "families", "surviving", "source"} from the registry.

    `source` is "registry" or "last_known". Imported lazily so this package
    stays cheap to import and cannot form a cycle with src.research.
    """
    try:
        from src.research import alpha_registry
        counts = alpha_registry.public_research_counts()
        families = {
            row.get("family")
            for row in alpha_registry.read_all()
            if row.get("kind") == "hypothesis" and row.get("family")
        }
        return {
            "hypotheses": int(counts["hypotheses"]),
            # Registered AND read. A hypothesis registered before its data
            # exists is pre-registered but not measured, and every customer
            # sentence here says "measured".
            "read": int(counts.get("read", counts["hypotheses"])),
            "pending": int(counts.get("pending") or 0),
            "families": len(families),
            "surviving": int(counts.get("surviving") or 0),
            "source": "registry",
        }
    except Exception:  # noqa: BLE001 -- see the module docstring
        return {
            "hypotheses": _LAST_KNOWN_HYPOTHESES,
            "read": _LAST_KNOWN_HYPOTHESES,
            "pending": 0,
            "families": _LAST_KNOWN_FAMILIES,
            "surviving": 0,
            "source": "last_known",
        }


_COUNTS = research_counts()

# Pre-registered hypotheses measured against outcomes, across all families.
# The READ count: a registration whose data has not arrived yet is not a
# measurement and is counted in HYPOTHESES_PENDING instead.
HYPOTHESES_TESTED = _COUNTS["read"]
HYPOTHESES_PENDING = _COUNTS["pending"]
HYPOTHESIS_FAMILIES = _COUNTS["families"]
COUNTS_FROM_REGISTRY = _COUNTS["source"] == "registry"
# Spelled out for prose that reads better with a word than a numeral. The
# count word is capitalised because every sentence that uses it starts with
# it; the families word is not because none does.
HYPOTHESES_TESTED_WORD = number_word(HYPOTHESES_TESTED).capitalize()
HYPOTHESIS_FAMILIES_WORD = number_word(HYPOTHESIS_FAMILIES)
