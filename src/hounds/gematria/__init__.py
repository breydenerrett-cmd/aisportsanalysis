"""The Gematria Hound: an experimental numerology hound that researches each upcoming game, ranks the two sides by how
many numerological coincidences each side's outcome produces, and publishes paper picks like every other hound.

THE STANCE (owner ruling, 2026-10-21): build it, make it work, improve its selection rules continuously, and do NOT
call it predictive until the public record says so. The hound is graded in public like the rest. It makes no claim.

Module map:
  facts      the facts layer (config/gematria/team_facts.json): names, cities, mascots, states, founding dates, coaches
  history    point-in-time results as of the lock (records, streaks, head-to-head, coach tenure, gaps since last win)
  rules      the versioned weights and thresholds (config/gematria/rules_v1.json), never edited after a pick was made
  signals    the both-sided, symmetric generator: typed evidence items per side, and the size of the search
  decision   pick the higher side only on a margin inside the price band; otherwise PASS with a reason
  runtime    the hound itself (src/hounds/pack/gematria_hound.py is the thin adapter the pack runner talks to)

The arithmetic (ciphers, primes, date numbers, spans) is src/research/gematria.py.
"""

HOUND_ID = "gematria"
CATEGORY = "numerology"
EXPERIMENTAL_LINE = "Experimental numerology hound. Paper picks, graded in public like every hound."
