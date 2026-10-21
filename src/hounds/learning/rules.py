"""Every number of the learning loop, in one place, each quoted from docs/PREREG_LEARNING_LOOP.md.

Do not tune a constant to move a challenger's fate. A change is a new dated section of the
pre-registration first (the same rule the verdict referee lives by), and a test
(tests/test_hounds_learning_prereg.py) reads the pre-registration and fails if a number here is
not stated there.
"""

from __future__ import annotations

# ---- looks, spending, boundaries (prereg section 6) -----------------------------------------
LOOKS = (100, 150, 200, 250, 300)          # paired slots at which a challenger is examined
MAX_PAIRED = LOOKS[-1]
# One-sided alpha spent at each look. Sums to 0.025 (the union bound), more at the end where the
# sample is largest; "promote at the first look on a hunch" is exactly what this prevents.
ALPHA_SPEND = (0.002, 0.003, 0.005, 0.007, 0.008)
ALPHA_TOTAL = 0.025
MIN_DATES_PER_LOOK = 20                    # distinct slate dates a look's sample must span
EXPIRY_DAYS = 180                          # fewer than LOOKS[0] slots this long after the start
SETTLE_LAG_HOURS = 3                       # a slot counts only once its game is this far in the past

# ---- the comparison (prereg section 5) ---------------------------------------------------------
VOLUME_FLOOR_MIN_BETS = 50                 # a promoting challenger needs this many measurable bets
VOLUME_FLOOR_SHARE = 0.5                   # ... and at least this share of the champion's

# ---- system-wide false-discovery control (prereg section 7) --------------------------------------
BH_Q = 0.10
P_ADJ_FACTOR = len(LOOKS)                  # Bonferroni over the planned looks: p_adj = min(1, 5 p)
MAX_PROMOTIONS_PER_MONTH = 3               # per scope, per calendar month (UTC)
PROMOTION_COOLDOWN_DAYS = 30               # per hound

# ---- proposal guards (prereg section 3) -----------------------------------------------------------
MIN_GRADED_BEFORE_PROPOSAL = 50            # the champion version's own record must exist first
PROPOSAL_COOLDOWN_DAYS = 7                 # per hound lineage (held rounds count)
MAX_LIVE_PER_HOUND = 3
MAX_LIVE_PER_SCOPE = 30
DEDUPE_DAYS = 90                           # a retired (lost) challenger blocks a near-repeat this long
HYPOTHESIS_MIN, HYPOTHESIS_MAX = 20, 400
EVIDENCE_MIN, EVIDENCE_MAX = 1, 10
EVIDENCE_REF_MAX = 120
MAX_KNOBS_CHANGED = 2                      # pack hounds: knobs differing from the champion
NEAR_PRICE_DECIMAL = 0.10                  # user specs: price band ends within this are "the same"
NEAR_COUNT = 1                             # user specs: min_books / max_bets_per_day within this

# ---- the scorecard and the auto-pause (prereg sections 9 and 10) -----------------------------------
MATURE_BETS = 100                          # measurable bets since promotion before a promotion "matured"
HIT_RATE_FLOOR = 0.40
MIN_MATURED_FOR_FLOOR = 10
TRAIL_DAYS = 60
ROLLING_DAYS = (30, 90)
MIN_BETS_FOR_COMPARISON = 50
CONTROL_IDS = ("coin_flip_collie", "dartboard_dalmatian")
# Categories that are not "champions" for the better-than-chance line: the instruments, the seeded
# controls, and the for-fun hounds.
NON_CHAMPION_CATEGORIES = ("baseline", "random", "esoteric", "numerology")

# ---- the analyst prompt arm (prereg section 12) ------------------------------------------------------
ANALYST_LOOKS = (150, 225, 300, 375, 450)
ANALYST_MAX_PAIRED = ANALYST_LOOKS[-1]
ANALYST_MAX_LIVE = 1
ANALYST_MIN_TAKE_GAME_SHARE = 0.5

# ---- outcomes and roles ----------------------------------------------------------------------------------
ROLE_CHALLENGER = "challenger"
OUTCOME_PROMOTED = "promoted"
OUTCOME_RETIRED = "retired"
OUTCOME_UNDECIDED = "undecided"
OUTCOMES = (OUTCOME_PROMOTED, OUTCOME_RETIRED, OUTCOME_UNDECIDED)

SCOPE_HOUSE = "house"
SCOPE_USER = "user"
SCOPE_ANALYST = "analyst"        # an analyst prompt challenger lives in the house scope's ledgers
