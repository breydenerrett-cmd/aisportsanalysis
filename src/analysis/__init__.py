"""Analysis layer: derived, read-only views over the point-in-time stores.

Modules here consume the same audited inputs the research layer uses -- the
pitch store, the posted-lineup store, the handedness cache -- and reshape them
into plain-dict briefing sections. Nothing in this package touches the
network, writes a store, or fits anything: it observes, attaches the sample
behind every number, and says so explicitly when it cannot.

THE FALSIFICATION COUNT LIVES HERE, ONCE
----------------------------------------
Every product surface states how much has been tested and survived, because
that sentence is the product. It was stated in three places with three
different numbers -- the briefing header said "Thirteen" (V1 only), the
Ranker banner said "Twenty-four" (pre-V5), the per-game note said "27" --
and two of those appeared on the SAME rendered page. A reader who notices
that the page cannot count its own losers has no reason to believe anything
else on it, so the count is now one constant that every surface reads.

Authority: docs/RESUME.md, "V1 (13) · V2 (5) · V4 (6) · V5 (3) = 27
pre-registered hypotheses, zero survivors", four families. Raising these
numbers means a family actually ran; never edit them to fit a sentence.
"""

# Pre-registered hypotheses measured against outcomes, across all families.
HYPOTHESES_TESTED = 27
HYPOTHESIS_FAMILIES = 4
# Spelled out for prose that reads better with a word than a numeral.
HYPOTHESES_TESTED_WORD = "Twenty-seven"
HYPOTHESIS_FAMILIES_WORD = "four"
