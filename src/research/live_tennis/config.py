"""The frozen constants of LIVE_TENNIS_V1 and the paths the test writes to.

Every number below is fixed by `docs/PREREG_LIVE_TENNIS.md` section 12 (the
FROZEN_CONSTANTS block); `tests/test_live_tennis_frozen.py` parses that block and
fails if any value here differs. The ledger's first row carries `fingerprint()`, and
the capture and the report refuse to run against a ledger written under a different
one, so a threshold cannot be edited after data exists without leaving a visible
break. A different specification is a new registration, not an edit of this file.

Paper only. Nothing in this package can place a bet, and nothing in it is read by
any customer surface.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping, Optional

from src.paths import data_path, evidence_path

# ---------------------------------------------------------------------------
# FROZEN (docs/PREREG_LIVE_TENNIS.md section 12). Edit only with a new registration.
# ---------------------------------------------------------------------------
RULE_ID = "LIVE_TENNIS_V1"
MODEL_ID = "MARKOV_V1"
SERVE_LEVEL_ATP = 0.64
SERVE_LEVEL_WTA = 0.56
SKILL_GAP_BOUND = 0.15
MIN_DECISION_SET = 2
MIN_FRESH_BOOKS = 3
BEST_IMPLIED_SUM_FLOOR = 0.99
GAP_THRESHOLD_PP = 3.0
DP_WINDOW_SECONDS = 240
MAX_DECISION_ATTEMPTS = 2
ATTEMPT_SPACING_SECONDS = 45
REF_MIN_DELAY_SECONDS = 600
REF_MAX_DELAY_SECONDS = 1500
REF_DEDICATED_AFTER_SECONDS = 900
PREMATCH_LEAD_MINUTES = 90
PREMATCH_REFRESH_MINUTES = 45
POLL_INTERVAL_SECONDS = 60
IDLE_POLL_INTERVAL_SECONDS = 300
DAILY_CREDIT_CAP = 200
PREMATCH_DAILY_SUBCAP = 60
MONTHLY_CREDIT_CAP = 4000
BET_FLOOR = 300
MATCH_FLOOR = 150
REFERENCE_COVERAGE_FLOOR = 0.70
STOP_DATE = "2027-01-31"
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261028

FROZEN_NAMES = (
    "RULE_ID", "MODEL_ID", "SERVE_LEVEL_ATP", "SERVE_LEVEL_WTA", "SKILL_GAP_BOUND",
    "MIN_DECISION_SET", "MIN_FRESH_BOOKS", "BEST_IMPLIED_SUM_FLOOR", "GAP_THRESHOLD_PP",
    "DP_WINDOW_SECONDS", "MAX_DECISION_ATTEMPTS", "ATTEMPT_SPACING_SECONDS",
    "REF_MIN_DELAY_SECONDS", "REF_MAX_DELAY_SECONDS", "REF_DEDICATED_AFTER_SECONDS",
    "PREMATCH_LEAD_MINUTES", "PREMATCH_REFRESH_MINUTES", "POLL_INTERVAL_SECONDS",
    "IDLE_POLL_INTERVAL_SECONDS", "DAILY_CREDIT_CAP", "PREMATCH_DAILY_SUBCAP",
    "MONTHLY_CREDIT_CAP", "BET_FLOOR", "MATCH_FLOOR", "REFERENCE_COVERAGE_FLOOR",
    "STOP_DATE", "BOOTSTRAP_RESAMPLES", "BOOTSTRAP_SEED",
)

# ---------------------------------------------------------------------------
# Not part of the freeze: names, paths and the switch.
# ---------------------------------------------------------------------------
REGISTRY_ID = "LIVE_TENNIS:setstart_markov_gap_clv:match_winner"
PREREG_DOC = "docs/PREREG_LIVE_TENNIS.md"
SCHEMA_VERSION = "live_tennis_v1.0"

ENV_SWITCH = "LIVE_TENNIS_TEST"          # must be "on" for ANY request or credit; default OFF
CREDIT_CALLER = "live_tennis.capture"    # the caller string every credit-log row carries
CREDIT_CALLER_PREMATCH = "live_tennis.capture.prematch"
CREDIT_BAND = "live_odds"                # budget.LIVE_ODDS: the direct-sum band, billed per call

SLAM_WORDS = ("wimbledon", "french_open", "us_open", "aus_open", "australian_open", "roland")


def constants() -> dict:
    """The frozen constants as one plain dict (what the fingerprint covers)."""
    return {name: globals()[name] for name in FROZEN_NAMES}


def fingerprint() -> str:
    """sha256 over the canonical JSON of every frozen constant."""
    body = json.dumps(constants(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def switch_on(env: Optional[Mapping] = None) -> bool:
    """True only when LIVE_TENNIS_TEST is explicitly 'on' (or 1/true/yes). The default is OFF."""
    source = os.environ if env is None else env
    return str(source.get(ENV_SWITCH) or "").strip().lower() in ("on", "1", "true", "yes")


def ledger_path():
    """The hash-chained paper ledger (decisions, bets, references, settlements): committed evidence."""
    return evidence_path("live_tennis_v1.jsonl")


def snapshots_path():
    """Every paid board, verbatim per tracked event: provenance for the ledger rows."""
    return data_path("research", "live_tennis", "snapshots.jsonl")


def heartbeat_path():
    """One row per tick, so downtime is counted and never reads as a quiet day."""
    return data_path("research", "live_tennis", "heartbeat.jsonl")


def tour_of(sport_key: str) -> Optional[str]:
    key = str(sport_key or "").lower()
    if key.startswith("tennis_atp"):
        return "atp"
    if key.startswith("tennis_wta"):
        return "wta"
    return None


def serve_level(tour: str) -> Optional[float]:
    return {"atp": SERVE_LEVEL_ATP, "wta": SERVE_LEVEL_WTA}.get(tour)


def sets_to_win(sport_key: str) -> int:
    """3 for an ATP key naming a Grand Slam, else 2 (best of 3)."""
    key = str(sport_key or "").lower()
    if key.startswith("tennis_atp") and any(word in key for word in SLAM_WORDS):
        return 3
    return 2
