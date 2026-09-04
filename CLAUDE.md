# How to respond in this project

**Be concise. This is the most important rule here.**

- Answer in a few lines. Not paragraphs.
- No artifacts, no design pamphlets. Plain text.
- No preamble, no recap, no summarizing what you just did.
- Detail goes in `docs/`, not in chat.
- If a full explanation is genuinely needed, ask first.

Brey has asked for this repeatedly. Ignoring it is the main way to get this wrong.

---

# Standing policies — read these before planning work

These are owner directives, recorded so they survive context loss. **After a
context reset, do not revert to the older behaviour they replaced.**

**`docs/MODEL_ROUTING_POLICY.md` — use the cheapest model that can do the
work correctly.** Fable orchestrates and does not personally do routine
implementation. Haiku for simple/mechanical work. **Sonnet is the default
serious worker and where most engineering happens.** Opus ONLY for difficult
architecture, deep statistical/methodological reasoning, adversarial review,
or complex debugging AFTER the issue is isolated -- and then with a focused
evidence packet, never a whole repo to rediscover. A large task alone does
not justify Opus. Deterministic code before model tokens: if Python or bash
answers it exactly (sweeps, enumeration, statistics, joins, bulk
diagnostics), run it. Every worker gets a narrow mission, explicit
deliverable, effort budget and stop condition; workers stop and report the
blocker rather than retrying endlessly.
**Do NOT default to Opus workers.**

**`docs/RESOURCE_POLICY.md` — credits renew monthly and unused credits are
worth ZERO at reset.** ~100,000/month. Optimize for maximum trustworthy
research value per cycle, not minimum spend: **be disciplined, not cheap.**
Roughly 25-35% reserved for live/forward capture (the existing 900/day
envelope), 40-50% historical backfill and new-market research, 10-20%
probes, 10% contingency. Storage is purchasable and must never be the reason
to limit the strategy population -- normalize records and split hot from cold
instead. iCloud never holds active repos, databases or mutating ledgers.
**Do NOT revert to credit austerity.**

Neither policy relaxes any evidence standard. Pre-registration before
evaluation, published losers, 2025 tuning-only, sealed 2026, no promotion
without the full gate, no rescue by threshold change, point-in-time
correctness. Credits buy more data, never a weaker gate.
