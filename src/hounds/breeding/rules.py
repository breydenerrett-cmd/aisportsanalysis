"""Every number of the breeding program, each quoted from docs/PREREG_BREEDING.md.

Do not tune a constant to change who breeds or who is culled. A change is a new dated section of the
pre-registration first; tests/test_hounds_breeding.py reads the pre-registration and fails if a number
here is not stated there.
"""

from __future__ import annotations

from datetime import date

# ---- cadence (prereg section 1) ---------------------------------------------------------------------
ANCHOR_DATE = date(2026, 10, 21)          # the first cycle date after the registration
CADENCE_DAYS = 3
CYCLE_HOUR_UTC = 12                       # a cycle runs at the first slot at or after 12:00 UTC
MAX_MISSED_ROWS = 10                      # missed cycle dates recorded per tick, at most

# ---- fitness (prereg section 2) ---------------------------------------------------------------------
MIN_SETTLED_FOR_ELIGIBLE = 25             # settled forward bets before a member can breed or be culled
SHRINK_PRIOR_BETS = 50                    # shrunk CLV = mean * m / (m + 50)
FITNESS_DECIMALS = 4                      # shrunk CLV is compared rounded to this many places
SETTLED_RESULTS = ("WIN", "LOSS", "PUSH")

# ---- parents and babies (prereg sections 3 to 5) ---------------------------------------------------------
PARENT_POOL = 4                           # the top 4 eligible members
MUTATION_PROBABILITY = 0.5
CROSSOVER_PROBABILITY = 0.5               # a knob comes from the better parent below this draw
MUTATION_STEPS = 1
# Section 13 (amendment 2026-10-19): a single-parent baby or a cull replacement moves ONE knob TWO steps, so it
# clears the learning loop's near-duplicate guard (every knob within one step). Crossovers keep MUTATION_STEPS.
SINGLE_PARENT_STEPS = 2
MAX_LITTERS_PER_CYCLE = 2                 # proposals per cycle, refused ones included
MAX_LIVE_BABIES = 6

# ---- culling (prereg section 6) -------------------------------------------------------------------------
CULL_MIN_ELIGIBLE = 4                     # culling runs only with at least this many eligible members
CULL_BOTTOM = 2
CULL_MIN_SETTLED = 40
CULL_BELOW = 0.0                          # shrunk CLV strictly below this
CONTROL_IDS = ("coin_flip_collie", "dartboard_dalmatian", "numerology_newfie", "lunar_lab")
CONTROL_CATEGORIES = ("random", "esoteric", "baseline")
CULL_REASON = "breeding_cull"

# ---- auto-pause (prereg section 8) ------------------------------------------------------------------------
PAUSE_AFTER_BAD_CYCLES = 3
BAD_ENDINGS = (("retired", "harm"), ("undecided", "expired"))   # HURT, TOO EARLY

PROPOSED_BY = "breeding"

# ---- ledger row kinds (prereg section 10) ------------------------------------------------------------------
K_CYCLE = "cycle"
K_BIRTH = "birth"
K_REFUSED = "birth_refused"
K_CULL = "cull"
K_PAUSE = "pause"
K_RESUME = "resume"
LEDGER_VERSION = 1
LEDGER_FILE = "hounds_breeding_v1.jsonl"

OUTCOME_RAN = "ran"
OUTCOME_SKIPPED = "skipped"
OUTCOME_MISSED = "missed"
