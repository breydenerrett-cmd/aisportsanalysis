"""Standalone F5-moneyline calibration evaluation path (F5-H1, F5-H2).

WHY THIS MODULE IS STANDALONE, AND NOT BUILT ON `src/research/funnel.py`
-------------------------------------------------------------------------
`docs/PREREG_F5_FAMILIES.md` (b) is explicit: the funnel is a
feature-threshold SELECTION instrument (`validate_spec` requires a
`NUMERIC_FEATURES` feature, `back_advantaged`, `threshold > 0`). F5-H1 and
F5-H2 select nothing -- they grade the ENTIRE gradeable population (H1) or a
frozen, feature-side partition of it (H2's terciles) against its own price.
Forcing them through the funnel would mean inventing a fake feature and
threshold purely to satisfy validation, corrupting the registered spec.

This module's only new code is row construction. Everything else is reused
verbatim:
  - `src.model.discovery` for date-clustered effects, p-values, intervals.
  - `src.research.battery` at frozen `RULES_VERSION 2.0.0`, no bespoke rule.
  - `src.model.family.benjamini_hochberg` for the 2-member FDR correction.

WHAT A ROW IS
-------------
One row per gradeable game (`status == "OK"`, `decided is True` --
`src.research.f5_universe`'s definition, reused, never re-derived):
`{game_pk, date, season, book_count, side, implied, price, won}`. `implied`
is the cross-book mean de-vigged probability of the graded side at the
frozen T-2h snapshot; `won` is that side's F5 result. This shape is exactly
what `src.model.discovery.evaluate` and `src.research.battery.run` already
consume -- no adapter needed.

H1 grades the HOME side of every gradeable game. H2 grades the FAVOURITE
side (whichever side is priced >=0.5 fair), bucketed into terciles of
`p_fav` fit on the 2023 discovery half ONLY and applied frozen to 2024
(feature-side thresholds -- built from `p_fav`, never from an outcome, so
this crosses the discovery/replication split without leaking).

RUN-TIME GUARDS (fail closed, never filter silently)
-----------------------------------------------------
Before any row is built: the identity hash and the price-payload hash (A3)
are re-verified against the frozen manifest. After rows are built: the row
count must be exactly 3,682, the season split exactly 1,597/2,085, and every
row's date must fall inside the approved window. Any mismatch RAISES
`F5EvalError` -- this module never narrows the universe to make a guard
pass.

NO OUTCOME IS READ UNTIL EXPLICITLY ASKED FOR
------------------------------------------------
`dry_run=True` (the only mode authorised against real data by the mission
that built this module) builds every row with `won=None`, runs every
feature-side check (hashes, counts, window, tercile fit, tie-book
exclusion, per-book price diagnostics that don't need an outcome), and
STOPS before calling `discovery.evaluate` or `battery.run` -- both of which
require `won`. `run_full_evaluation` (real stats) is for the post-approval
run this mission does not authorise.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from src.core import odds as odds_math
from src.model import discovery, family
from src.paths import data_path, repo_root
from src.research import battery, f5_eligibility, f5_universe

MARKET_KEY = "h2h_1st_5_innings"

# The three A2 sensitivity conventions. "power" is `src.core.odds`'s name for
# the exponent-solved convention -- the literature also calls it the
# "multiplicative" or "odds-ratio" method (it removes more margin from
# longshots than proportional does, which is exactly the favourite-longshot
# signature A2 warns is confounded with F5-H2's own effect).
DEVIG_METHODS = {
    "proportional": "proportional",
    "multiplicative": "power",
    "shin": "shin",
}
PRIMARY_DEVIG_METHOD = "proportional"

EXPECTED_ROW_COUNT = 3682
EXPECTED_SEASON_SPLIT = {"2023": 1597, "2024": 2085}
WINDOW_START = f5_eligibility.APPROVED_WINDOW_START
WINDOW_END = f5_eligibility.APPROVED_WINDOW_END

# Amendment 2 (PREREG_F5_FAMILIES.md summary): F5-H1 floor 2.0pp, F5-H2
# floor 4.0pp per extreme tercile (raised from the draft's 3.0pp -- the
# per-tercile MDE at n~=417/2024-bucket was understated at 3.0pp).
H1_EFFECT_FLOOR = 0.020
H2_EFFECT_FLOOR = 0.040

# A4: per-book sign-replication is report-only and needs a judgeable sample.
BOOK_DIAGNOSTIC_MIN_N = battery.MIN_N

# A5: chi-square kill on 2024 bucket occupancy vs. the 2023-fit expected
# thirds, fatal below this p. Terciles -> 3 categories -> 2 degrees of
# freedom, which has the exact closed-form chi-square survival function
# used in `chi_square_p` (no scipy dependency needed or wanted here).
POPULATION_SHIFT_P_FATAL = 0.01

MIN_BUCKET_N_2024 = 300  # amendment 1

# B2 (post-adversarial amendment): the FDR family for this pre-registration
# is {F5-H1, F5-H2-bottom, F5-H2-top} -- three tested statistics, not two.
# The review recommended amending the frozen record's "fdr_m": 2 to match
# this code, rather than the reverse, precisely because F5-H2's two extreme
# terciles genuinely are two tests. `run_full_evaluation` asserts the p-list
# it builds is exactly this length before handing it to
# `family.benjamini_hochberg`, so a pooled/unpooled miscount cannot silently
# reappear as a wrong m.
FDR_M = 3

# M1: the standalone freeze mechanism this family needs -- `family.register`
# enumerates detector x market and cannot hold a family_id/member-record
# shape (M1, reproduced in the adversarial review). `data/research/` is
# tracked (unlike `data/historical/*`, `data/raw/*`), matching
# `f5_universe.MANIFEST_PATH` living in the same directory.
FROZEN_FAMILY_PATH = data_path("research", "f5", "family_frozen.json")

# The document this family's spec_sha256 is computed over. `spec_sha256`
# hashes the FINAL SPECIFICATION section plus the Post-adversarial
# amendments section -- never the adversarial-review narrative in between,
# which is analysis, not the registered text.
SPEC_DOC_PATH = repo_root() / "docs" / "PREREG_F5_FAMILIES.md"
_FINAL_SPEC_MARKER = "## FINAL SPECIFICATION"
_ADVERSARIAL_MARKER = "## Adversarial pre-registration review"
_AMENDMENTS_MARKER = "## Post-adversarial amendments"


class F5EvalError(RuntimeError):
    """Raised when the evaluation path cannot proceed honestly."""


# ---------------------------------------------------------------------------
# Guards -- run BEFORE any row is trusted
# ---------------------------------------------------------------------------

def verify_universe(*, primary_path=f5_universe.PRIMARY_VIEW_PATH,
                     settlement_path=f5_universe.SETTLEMENT_PATH,
                     raw_store=f5_universe.RAW_STORE,
                     manifest_path=f5_universe.MANIFEST_PATH) -> dict:
    """Re-verify both A3 hashes against the frozen manifest. Aborts (raises)
    on any mismatch rather than proceeding on a universe that may have moved.
    """
    frozen = f5_universe.read_manifest(manifest_path)
    recomputed = f5_universe.build_universe(
        primary_path=primary_path, settlement_path=settlement_path, raw_store=raw_store)

    if frozen["content_hash"] != recomputed["content_hash"]:
        raise F5EvalError(
            "identity-hash mismatch: the eligible F5 universe changed since "
            f"it was frozen (frozen={frozen['content_hash']}, "
            f"recomputed={recomputed['content_hash']}). Aborting -- this "
            "family's denominator cannot be trusted.")

    frozen_price_hash = frozen.get("price_payload_hash")
    if frozen_price_hash is None:
        raise F5EvalError(
            "the frozen manifest carries no price_payload_hash (A3) -- "
            "re-run src.research.f5_universe to add it before evaluating.")
    if frozen_price_hash != recomputed["price_payload_hash"]:
        raise F5EvalError(
            "price-payload-hash mismatch (A3): a book price moved since the "
            f"freeze (frozen={frozen_price_hash}, "
            f"recomputed={recomputed['price_payload_hash']}). Aborting -- a "
            "re-fetch or repair changed prices without moving the identity "
            "hash.")

    return {"content_hash": frozen["content_hash"],
            "price_payload_hash": frozen_price_hash, "verified": True}


def _verify_window(rows: list) -> None:
    """PIT guard: every row's `date` must fall inside the approved window.
    Raises on the first violation rather than filtering it out -- a row
    outside the window here means the universe filter upstream failed, and
    silently dropping it would hide that. Split out from `_verify_row_shape`
    so it is independently testable against a small synthetic sample (the
    real universe's exact 3,682/1,597/2,085 counts are not needed to prove
    this guard fires).
    """
    for row in rows:
        date = row["date"]
        if not (WINDOW_START <= str(date) <= WINDOW_END):
            raise F5EvalError(
                f"row for game_pk={row['game_pk']} is dated {date}, outside "
                f"the approved window {WINDOW_START}..{WINDOW_END}. Aborting "
                "rather than silently dropping it -- a row outside the "
                "window here means the universe filter upstream failed.")


def _verify_row_shape(rows: list) -> None:
    """Row-count, season-split and window guards. Raises, never filters."""
    if len(rows) != EXPECTED_ROW_COUNT:
        raise F5EvalError(
            f"expected exactly {EXPECTED_ROW_COUNT} gradeable rows, got "
            f"{len(rows)} -- the universe moved, or the join changed.")

    _verify_window(rows)

    by_season = {}
    for row in rows:
        by_season[row["season"]] = by_season.get(row["season"], 0) + 1
    if by_season != EXPECTED_SEASON_SPLIT:
        raise F5EvalError(
            f"season split is {by_season}, expected {EXPECTED_SEASON_SPLIT}")


# ---------------------------------------------------------------------------
# Source data
# ---------------------------------------------------------------------------

def _read_jsonl(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _load_settlement(path=f5_universe.SETTLEMENT_PATH) -> dict:
    return {str(r["game_pk"]): r for r in _read_jsonl(path)}


def load_gradeable_primary_rows(*, primary_path=f5_universe.PRIMARY_VIEW_PATH,
                                 settlement_path=f5_universe.SETTLEMENT_PATH) -> list:
    """The gradeable subset of the primary view: `status == "OK"` and
    `decided is True` -- reusing exactly `f5_universe`'s definition of
    gradeability, never re-derived here.

    Returns primary-view rows (unmodified, still carrying `books`) paired
    with their settled `winner`. NEVER reads `actual_first_pitch` or any
    settlement timestamp -- only `winner`/`complete`, the same two fields
    `f5_universe.build_universe` reads to define `decided`/`tie`.
    """
    primary_rows = _read_jsonl(primary_path)
    settlement = _load_settlement(settlement_path)

    out = []
    for row in primary_rows:
        if row.get("status") != "OK":
            continue
        settled = settlement.get(str(row["game_pk"]))
        if not settled or not settled.get("complete"):
            continue
        winner = settled.get("winner")
        if winner not in ("home", "away"):
            continue  # tie -- excluded from the gradeable set by construction
        out.append((row, winner))
    return out


# ---------------------------------------------------------------------------
# De-vig -- three conventions (A2)
# ---------------------------------------------------------------------------

def _book_pairs(primary_row: dict) -> list:
    """[(book_key, away_price, home_price), ...] for every book carrying
    both prices under MARKET_KEY. A book missing either price is excluded
    from the consensus -- never guessed."""
    out = []
    for book in primary_row.get("books") or []:
        market = book.get(MARKET_KEY) or {}
        away, home = market.get("away_price"), market.get("home_price")
        if away is None or home is None:
            continue
        out.append((book.get("key"), away, home))
    return out


def consensus_fair(primary_row: dict, method: str) -> dict | None:
    """Cross-book mean de-vigged (away_fair, home_fair) under `method`, plus
    the best (most favourable to a bettor) American price per side -- same
    "best available price" convention as `src.model.selections._fair`.

    Returns None if no book's pair de-vigs cleanly under this method (never
    happens on the frozen universe's two-way books, but a caller must not
    assume it can't).
    """
    away_fairs, home_fairs, away_prices, home_prices = [], [], [], []
    for _key, away, home in _book_pairs(primary_row):
        try:
            fair_away, fair_home = odds_math.devig_two_way(away, home, method=method)
        except odds_math.OddsError:
            continue
        away_fairs.append(fair_away)
        home_fairs.append(fair_home)
        away_prices.append(away)
        home_prices.append(home)
    if not away_fairs:
        return None
    return {
        "away_fair": sum(away_fairs) / len(away_fairs),
        "home_fair": sum(home_fairs) / len(home_fairs),
        "away_price": max(away_prices),
        "home_price": max(home_prices),
        "n_books": len(away_fairs),
    }


def devig_two_way_example() -> dict:
    """A hand-checkable two-way example (-150/+130), used by the validation
    test to confirm all three conventions AGREE closely on a coin-flip-
    adjacent market and PRODUCE the documented favourite-longshot divergence
    on a lopsided one. Not consumed by the evaluation path itself.
    """
    return {
        "moderate": {"away": 130, "home": -150},
        "lopsided": {"away": 450, "home": -900},
    }


# ---------------------------------------------------------------------------
# Row construction -- H1 (home side)
# ---------------------------------------------------------------------------

def build_h1_rows(gradeable, *, method=PRIMARY_DEVIG_METHOD, dry_run=False) -> list:
    """One row per gradeable game, grading the HOME side."""
    rows = []
    for primary_row, winner in gradeable:
        c = consensus_fair(primary_row, method)
        if c is None:
            raise F5EvalError(
                f"game_pk={primary_row['game_pk']} has >=5 books by "
                "construction but none de-vigged cleanly under "
                f"{method!r} -- this should not happen on the frozen "
                "universe; investigate before proceeding.")
        rows.append({
            "game_pk": str(primary_row["game_pk"]),
            "date": primary_row["date"],
            "season": str(primary_row["date"])[:4],
            "book_count": primary_row.get("book_count"),
            "side": "home",
            "implied": c["home_fair"],
            "price": c["home_price"],
            "won": None if dry_run else (winner == "home"),
        })
    return rows


# ---------------------------------------------------------------------------
# Row construction -- H2 (favourite side, terciles)
# ---------------------------------------------------------------------------

def build_h2_rows(gradeable, *, method=PRIMARY_DEVIG_METHOD, dry_run=False) -> list:
    """One row per gradeable game, grading the FAVOURITE side (`p_fav` >=
    0.5 by construction of picking the shorter-priced side). Carries
    `p_fav` and `fav_is_home` so a bucket assignment or population-shift
    check can be layered on afterward without recomputing the de-vig.
    """
    rows = []
    for primary_row, winner in gradeable:
        c = consensus_fair(primary_row, method)
        if c is None:
            raise F5EvalError(
                f"game_pk={primary_row['game_pk']} has >=5 books by "
                "construction but none de-vigged cleanly under "
                f"{method!r} -- this should not happen on the frozen "
                "universe; investigate before proceeding.")
        fav_is_home = c["home_fair"] >= c["away_fair"]
        p_fav = c["home_fair"] if fav_is_home else c["away_fair"]
        price = c["home_price"] if fav_is_home else c["away_price"]
        fav_won = (winner == "home") if fav_is_home else (winner == "away")
        rows.append({
            "game_pk": str(primary_row["game_pk"]),
            "date": primary_row["date"],
            "season": str(primary_row["date"])[:4],
            "book_count": primary_row.get("book_count"),
            "side": "home" if fav_is_home else "away",
            "p_fav": p_fav,
            "implied": p_fav,
            "price": price,
            "won": None if dry_run else fav_won,
        })
    return rows


def fit_terciles_2023(h2_rows) -> list:
    """Tercile edges of `p_fav`, fit on the 2023 rows ONLY -- feature-side
    (built from price, never from `won`), frozen and applied unchanged to
    2024 (amendment 1: terciles, not quintiles).

    Index quantiles (an edge is a real observed value), matching
    `battery._quartile_edges`'s convention so a degenerate band from
    duplicate values collapses the same way rather than silently existing.
    """
    values = sorted(r["p_fav"] for r in h2_rows if r["season"] == "2023")
    if not values:
        raise F5EvalError("no 2023 rows to fit tercile edges from")
    n = len(values)
    e1 = values[max(0, n // 3 - 1)]
    e2 = values[max(0, (2 * n) // 3 - 1)]
    edges = sorted({values[0], e1, e2, values[-1]})
    if len(edges) < 3:
        raise F5EvalError(
            "2023 p_fav has too little spread to fit three tercile bands")
    return edges


def _assign_buckets(h2_rows, edges) -> None:
    """In-place: attach `bucket` to every row (0 bottom / 1 middle / 2 top)
    using the FROZEN 2023 edges. `edges[1]` and `edges[-2]` are the interior
    cut points (the two-element-collapsed case, `edges[1] == edges[-2]`, is
    a degenerate middle band, not an error)."""
    lo_edge, hi_edge = edges[1], edges[-2]
    for row in h2_rows:
        if row["p_fav"] < lo_edge:
            row["bucket"] = 0
        elif row["p_fav"] >= hi_edge:
            row["bucket"] = 2
        else:
            row["bucket"] = 1


# ---------------------------------------------------------------------------
# A5 -- population-shift kill (chi-square on tercile occupancy)
# ---------------------------------------------------------------------------

def chi_square_p_df2(chi_square: float) -> float:
    """Exact chi-square survival function at 2 degrees of freedom.

    Terciles -> 3 occupancy categories -> df = 3 - 1 = 2, and chi-square
    with 2 degrees of freedom is exactly an Exponential(scale=2), whose
    survival function is a closed form (`exp(-x/2)`) -- no numeric
    integration or scipy dependency needed for the one df this module ever
    uses. `discovery.py` already keeps this project's stats stdlib-only for
    the same reason.
    """
    if chi_square < 0:
        raise F5EvalError(f"chi-square statistic must be >= 0, got {chi_square!r}")
    return math.exp(-chi_square / 2.0)


def population_shift_test(h2_rows_2023, h2_rows_2024) -> dict:
    """A5: chi-square of 2024 bucket occupancy against the 2023-fit expected
    thirds. Fatal at p < 0.01. Feature-side only (bucket membership comes
    from `p_fav`, never `won`) -- decided before any 2024 outcome is read.
    """
    n_2023 = len(h2_rows_2023)
    n_2024 = len(h2_rows_2024)
    if not n_2023 or not n_2024:
        raise F5EvalError("population-shift test needs both a 2023 and a "
                          "2024 bucketed sample")

    expected_props = [
        sum(1 for r in h2_rows_2023 if r["bucket"] == b) / n_2023
        for b in (0, 1, 2)
    ]
    observed = [sum(1 for r in h2_rows_2024 if r["bucket"] == b) for b in (0, 1, 2)]
    expected = [p * n_2024 for p in expected_props]

    chi_square = sum(
        ((o - e) ** 2) / e for o, e in zip(observed, expected) if e > 0)
    p = chi_square_p_df2(chi_square)
    return {
        "expected_props_2023": expected_props,
        "observed_2024": observed,
        "expected_2024": expected,
        "chi_square": round(chi_square, 5),
        "p": round(p, 6),
        "fatal": p < POPULATION_SHIFT_P_FATAL,
        "note": ("FATAL when p < "
                 f"{POPULATION_SHIFT_P_FATAL}: the 2023-fit tercile edges "
                 "are testing a materially different favourite/dog mix in "
                 "2024, not a replication of the same population (A5)"),
    }


# ---------------------------------------------------------------------------
# M1 -- standalone freeze mechanism (family.register cannot hold this shape)
# ---------------------------------------------------------------------------

def _extract_spec_text(full_text: str) -> str:
    """The exact text `spec_sha256` hashes: the FINAL SPECIFICATION section
    (up to, not including, the adversarial-review section) plus the
    Post-adversarial amendments section (to end of file). Raises if either
    marker is missing -- a family must not be frozen against a document that
    has not yet been amended for the findings this freeze depends on.
    """
    if _FINAL_SPEC_MARKER not in full_text:
        raise F5EvalError(
            f"{_FINAL_SPEC_MARKER!r} not found in spec text -- cannot "
            "compute spec_sha256 against a document that lacks it")
    if _AMENDMENTS_MARKER not in full_text:
        raise F5EvalError(
            f"{_AMENDMENTS_MARKER!r} not found in spec text -- amend the "
            "spec for the adversarial-review findings before freezing the "
            "family")
    spec_section = full_text.split(_FINAL_SPEC_MARKER, 1)[1]
    if _ADVERSARIAL_MARKER in spec_section:
        spec_section = spec_section.split(_ADVERSARIAL_MARKER, 1)[0]
    amendments_section = full_text.split(_AMENDMENTS_MARKER, 1)[1]
    return (_FINAL_SPEC_MARKER + spec_section
            + _AMENDMENTS_MARKER + amendments_section)


def spec_sha256(spec_path=SPEC_DOC_PATH) -> str:
    """sha256 over the FINAL SPECIFICATION + Post-adversarial amendments
    text, so a frozen family record can prove the spec has not moved
    underneath it since registration (M1)."""
    text = Path(spec_path).read_text(encoding="utf-8")
    return hashlib.sha256(_extract_spec_text(text).encode("utf-8")).hexdigest()


def freeze_family(path=FROZEN_FAMILY_PATH, *, spec_path=SPEC_DOC_PATH,
                   manifest_path=f5_universe.MANIFEST_PATH, now=None) -> dict:
    """M1: freeze `{F5-H1, F5-H2-bottom, F5-H2-top}` to an immutable JSON
    record. Refuses to overwrite an existing record -- once frozen, the
    record IS the pre-registration; silently changing it is exactly the
    rescue lever T8 forbids. This function is never called against the real
    `FROZEN_FAMILY_PATH` by anything in this module -- freezing the real
    family is a deliberate, reviewed, separate act.
    """
    target = Path(path)
    if target.exists():
        raise F5EvalError(
            f"a family record is already frozen at {target}. Refusing to "
            "overwrite it -- re-registering the family is a reviewed "
            "commit that deletes the old file first, deliberately.")

    manifest = f5_universe.read_manifest(manifest_path)
    record = {
        "family_id": "F5_MONEYLINE_CALIBRATION_2026H1",
        "members": ["F5-H1", "F5-H2-bottom", "F5-H2-top"],
        "effect_floor_pp": {"F5-H1": 2.0, "F5-H2-bottom": 4.0, "F5-H2-top": 4.0},
        "discovery": {"date_range": ["2023-05-10", "2023-12-31"], "n": 1597},
        "replication": {"date_range": ["2024-01-01", "2024-10-07"], "n": 2085},
        "fdr_q": family.FDR_Q,
        "fdr_m": FDR_M,
        "battery_rules_version": battery.RULES_VERSION,
        "universe_identity_hash": manifest["content_hash"],
        "universe_price_payload_hash": manifest["price_payload_hash"],
        "spec_sha256": spec_sha256(spec_path),
        "frozen_at": (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc).isoformat(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return record


def read_frozen_family(path=FROZEN_FAMILY_PATH) -> dict:
    target = Path(path)
    if not target.exists():
        raise F5EvalError(
            f"no family record frozen at {target}. Call freeze_family() to "
            "register {F5-H1, F5-H2-bottom, F5-H2-top} before running any "
            "evaluation -- a correction and a set of gates computed against "
            "an unregistered family is not a pre-registration.")
    return json.loads(target.read_text(encoding="utf-8"))


def _verify_frozen_family(hashes: dict, *, path=FROZEN_FAMILY_PATH,
                          spec_path=SPEC_DOC_PATH) -> dict:
    """M1: `run_full_evaluation`'s precondition. Raises unless the frozen
    record exists AND its universe hashes and spec_sha256 still match what
    is true right now -- a family frozen against yesterday's spec or a
    since-moved universe is not evidence for today's run.
    """
    record = read_frozen_family(path)
    current_spec_sha = spec_sha256(spec_path)
    if record.get("spec_sha256") != current_spec_sha:
        raise F5EvalError(
            "the frozen family's spec_sha256 no longer matches "
            f"{spec_path} -- the specification changed after the family "
            "was frozen. Aborting rather than running against a moved "
            "target.")
    if record.get("universe_identity_hash") != hashes["content_hash"]:
        raise F5EvalError(
            "the frozen family's universe_identity_hash does not match the "
            "just-reverified universe -- aborting.")
    if record.get("universe_price_payload_hash") != hashes["price_payload_hash"]:
        raise F5EvalError(
            "the frozen family's universe_price_payload_hash does not "
            "match the just-reverified universe -- aborting.")
    if record.get("fdr_m") != FDR_M:
        raise F5EvalError(
            f"the frozen record's fdr_m ({record.get('fdr_m')!r}) disagrees "
            f"with this module's FDR_M ({FDR_M!r}) -- B2 regression; the "
            "record and the code must agree before any run.")
    return record


# ---------------------------------------------------------------------------
# B1 -- two-leg screen/replication gates, and B3 -- mechanised verdicts
# ---------------------------------------------------------------------------

def evaluate_h1_screen(h1_rows_2023) -> dict:
    """B1: the 2023 screen leg for F5-H1 -- sign + point estimate >= floor
    ONLY (binding amendment above: no CI, no FDR on this leg). Reuses
    `discovery.evaluate` for the point estimate but the pass decision below
    reads only `effect`, never `p`/`ci` -- using them here would be exactly
    the "both legs need a CI" rule the spec rejected as a coin-flip filter.
    """
    result = discovery.evaluate("F5-H1-screen", h1_rows_2023)
    effect = result["effect"]
    passes = effect is not None and effect > 0 and effect >= H1_EFFECT_FLOOR
    return {"effect": effect, "n": result["decided"], "passes_screen": passes}


def evaluate_h2_bucket_screen(bucket_rows_2023, bucket_label, expected_sign) -> dict:
    """B1: the 2023 screen leg for one F5-H2 extreme tercile. `expected_sign`
    is +1 (top) or -1 (bottom) -- the fixed direction the spec pre-registers
    for that bucket."""
    result = discovery.evaluate(f"F5-H2-{bucket_label}-screen", bucket_rows_2023)
    effect = result["effect"]
    if effect is None:
        passes = False
    elif expected_sign > 0:
        passes = effect > 0 and effect >= H2_EFFECT_FLOOR
    else:
        passes = effect < 0 and abs(effect) >= H2_EFFECT_FLOOR
    return {"effect": effect, "n": result["decided"], "passes_screen": passes}


def _replication_gate(result_2024: dict, expected_sign: int) -> dict:
    """B1: the 2024 replication leg's sign-agreement and CI-excludes-zero
    checks, taken from a `discovery.evaluate` result already restricted to
    2024-only rows by the caller."""
    effect = result_2024.get("effect")
    ci = result_2024.get("ci")
    sign_agrees = effect is not None and (
        effect > 0 if expected_sign > 0 else effect < 0)
    ci_excludes_zero = bool(
        ci and (ci.get("low", 0) > 0 or ci.get("high", 0) < 0))
    return {"sign_agrees": sign_agrees, "ci_excludes_zero": ci_excludes_zero}


def devig_sign_survives_check(sensitivity: dict, bucket_label: str,
                               expected_sign: int) -> bool:
    """F5-H2's binding de-vig sign-survival pass criterion: the extreme-
    bucket 2024 effect must keep `expected_sign` under all three conventions
    (`sensitivity`, from `devig_sensitivity`). A convention under which the
    bucket has too few rows to produce an effect fails this check -- a
    missing sign cannot be said to have survived.
    """
    key = f"{bucket_label}_2024"
    for label in DEVIG_METHODS:
        effect = sensitivity[label][key]["effect"]
        if effect is None:
            return False
        if expected_sign > 0 and not (effect > 0):
            return False
        if expected_sign < 0 and not (effect < 0):
            return False
    return True


def compute_verdict(*, screen_passes: bool, replication_sign_agrees: bool,
                    replication_ci_excludes_zero: bool, survives_fdr: bool,
                    battery_survives: bool, bucket_n_ok: bool = True,
                    devig_sign_survives: bool = True,
                    population_shift_fatal: bool = False) -> str:
    """B3: mechanise the stopping/failure rules into ONE verdict, in this
    fixed precedence -- never left for a reader to infer from the raw
    statistics.

    1. POPULATION_SHIFT_FAIL -- checked first: M2 pre-registers this as
       decided before any outcome, so it must win over every
       outcome-dependent gate below it, not merely tiebreak against them.
    2. SCREEN_FAIL -- the 2023 leg fails sign/floor.
    3. REPLICATION_FAIL -- the 2024 bucket-n floor is unmet (blocked-
       coverage) or the 2024 sign/CI/FDR gate fails.
    4. DEVIG_SIGN_FAIL -- the extreme-bucket sign does not survive all three
       de-vig conventions.
    5. BATTERY_FAIL -- the frozen battery flags a fatal rule.
    6. SURVIVOR -- every gate above cleared.
    """
    if population_shift_fatal:
        return "POPULATION_SHIFT_FAIL"
    if not screen_passes:
        return "SCREEN_FAIL"
    if not bucket_n_ok:
        return "REPLICATION_FAIL"
    if not (replication_sign_agrees and replication_ci_excludes_zero
           and survives_fdr):
        return "REPLICATION_FAIL"
    if not devig_sign_survives:
        return "DEVIG_SIGN_FAIL"
    if not battery_survives:
        return "BATTERY_FAIL"
    return "SURVIVOR"


# ---------------------------------------------------------------------------
# A4 -- battery wiring with explicit skip recording, and per-book diagnostic
# ---------------------------------------------------------------------------

def run_battery(rows, *, effect_floor) -> dict:
    """Battery.run at the frozen rules, verbatim -- no bespoke rule. Records
    every check the battery itself reported as skipped, and why (A4), so a
    fatal rule that is quietly inert (rule 3, book_concentration -- these
    rows carry no per-row `book`, only a consensus) is never silently lost.
    """
    result = battery.run(rows, effect_floor=effect_floor)
    skipped = {name: check["skipped"] for name, check in result["report"].items()
               if isinstance(check, dict) and "skipped" in check}
    result["skipped_checks"] = skipped
    return result


def per_book_sign_replication(gradeable, *, method=PRIMARY_DEVIG_METHOD,
                              min_n=BOOK_DIAGNOSTIC_MIN_N) -> dict:
    """A4: per-book replication of the H1 sign, each book's OWN de-vigged
    price graded separately (never the consensus). Report-only -- book
    composition is known to churn across this window (A4), so a sign that
    exists only in the books present in one season is information a reader
    needs, not a kill test.
    """
    by_book = {}
    for primary_row, winner in gradeable:
        for key, away, home in _book_pairs(primary_row):
            try:
                _fair_away, fair_home = odds_math.devig_two_way(away, home, method=method)
            except odds_math.OddsError:
                continue
            by_book.setdefault(key, []).append({
                "date": primary_row["date"],
                "won": winner == "home",
                "implied": fair_home,
            })

    out = {}
    for book, rows in sorted(by_book.items()):
        if len(rows) < min_n:
            out[book] = {"n": len(rows),
                        "note": f"below the {min_n}-row floor; report only"}
            continue
        diffs = [(1.0 if r["won"] else 0.0) - r["implied"] for r in rows]
        diff_rows = [dict(r, _diff=d) for r, d in zip(rows, diffs)]
        effect = sum(diffs) / len(diffs)
        out[book] = {
            "n": len(rows),
            "effect": round(effect, 5),
            "p": round(discovery.clustered_two_sided_p(effect, diff_rows), 6),
            "sign": "+" if effect > 0 else ("-" if effect < 0 else "0"),
        }
    return out


# ---------------------------------------------------------------------------
# Full evaluation (requires `won` -- NOT run in dry_run mode)
# ---------------------------------------------------------------------------

def evaluate_h1(h1_rows) -> dict:
    return discovery.evaluate("F5-H1", h1_rows)


def evaluate_h2_bucket(bucket_rows, bucket_label) -> dict:
    return discovery.evaluate(f"F5-H2-{bucket_label}", bucket_rows)


def devig_sensitivity(gradeable, edges_by_method=None) -> dict:
    """A2: the extreme-tercile H2 effect under all three de-vig conventions.
    F5-H2's pass criterion requires the sign to survive all three; F5-H1's
    is report-only (a home/away split is close to symmetric across the
    price range, so the convention's differential effect largely cancels).
    """
    out = {}
    for label, method in DEVIG_METHODS.items():
        h2_rows = build_h2_rows(gradeable, method=method)
        edges = fit_terciles_2023(h2_rows)
        _assign_buckets(h2_rows, edges)
        rows_2024 = [r for r in h2_rows if r["season"] == "2024"]
        bottom = evaluate_h2_bucket([r for r in rows_2024 if r["bucket"] == 0],
                                    f"{label}-bottom")
        top = evaluate_h2_bucket([r for r in rows_2024 if r["bucket"] == 2],
                                 f"{label}-top")
        out[label] = {"edges": edges, "bottom_2024": bottom, "top_2024": top}
    return out


def run_full_evaluation(*, primary_path=f5_universe.PRIMARY_VIEW_PATH,
                         settlement_path=f5_universe.SETTLEMENT_PATH) -> dict:
    """The complete, outcome-reading evaluation. Not authorised to run
    against real data by the mission that built this module -- present so
    the path exists and is tested against synthetic data (validation item
    1), gated behind an explicit call so it can never run by accident from
    `run(dry_run=True)`.

    B1: F5-H1 and F5-H2's extreme terciles are each evaluated on a 2023
    screen leg (sign + floor only) and a SEPARATE 2024 replication leg (CI +
    FDR); nothing here evaluates F5-H1 against the pooled universe for any
    inferential purpose. M1: refuses to run unless the family is frozen
    (`freeze_family`) and its record still matches the live universe and
    spec text.
    """
    hashes = verify_universe(primary_path=primary_path, settlement_path=settlement_path)
    _verify_frozen_family(hashes)
    gradeable = load_gradeable_primary_rows(
        primary_path=primary_path, settlement_path=settlement_path)

    # ------------------------------------------------------------- F5-H1 --
    h1_rows = build_h1_rows(gradeable)
    _verify_row_shape(h1_rows)
    h1_2023 = [r for r in h1_rows if r["season"] == "2023"]
    h1_2024 = [r for r in h1_rows if r["season"] == "2024"]

    h1_screen = evaluate_h1_screen(h1_2023)
    h1_result = evaluate_h1(h1_2024)  # B1: 2024-only, never pooled
    h1_replication = _replication_gate(h1_result, expected_sign=1)
    h1_battery = run_battery(h1_2024, effect_floor=H1_EFFECT_FLOOR)  # 2024-leg only

    # ------------------------------------------------------------- F5-H2 --
    h2_rows = build_h2_rows(gradeable)
    _verify_row_shape(h2_rows)  # N2: H2 rows get the same shape guard as H1
    edges = fit_terciles_2023(h2_rows)
    _assign_buckets(h2_rows, edges)
    h2_2023 = [r for r in h2_rows if r["season"] == "2023"]
    h2_2024 = [r for r in h2_rows if r["season"] == "2024"]
    bottom_2023 = [r for r in h2_2023 if r["bucket"] == 0]
    top_2023 = [r for r in h2_2023 if r["bucket"] == 2]
    bottom_2024 = [r for r in h2_2024 if r["bucket"] == 0]
    top_2024 = [r for r in h2_2024 if r["bucket"] == 2]

    # A5/M2: feature-side only, decided before any 2024 outcome is read.
    shift = population_shift_test(h2_2023, h2_2024)

    bottom_screen = evaluate_h2_bucket_screen(bottom_2023, "bottom", expected_sign=-1)
    top_screen = evaluate_h2_bucket_screen(top_2023, "top", expected_sign=1)
    bottom_n_ok = len(bottom_2024) >= MIN_BUCKET_N_2024
    top_n_ok = len(top_2024) >= MIN_BUCKET_N_2024

    # M2: computed and published regardless of the population-shift kill --
    # exploratory/report-only for F5-H2 once A5 has fired, never skipped.
    h2_bottom_result = evaluate_h2_bucket(bottom_2024, "bottom")
    h2_top_result = evaluate_h2_bucket(top_2024, "top")
    bottom_replication = _replication_gate(h2_bottom_result, expected_sign=-1)
    top_replication = _replication_gate(h2_top_result, expected_sign=1)

    h2_bottom_battery = run_battery(bottom_2024, effect_floor=H2_EFFECT_FLOOR)
    h2_top_battery = run_battery(top_2024, effect_floor=H2_EFFECT_FLOOR)

    sensitivity = devig_sensitivity(gradeable)
    bottom_devig_ok = devig_sign_survives_check(sensitivity, "bottom", expected_sign=-1)
    top_devig_ok = devig_sign_survives_check(sensitivity, "top", expected_sign=1)

    # --------------------------------------------------------------- FDR --
    # B2: m=3 -- F5-H1 (2024 leg), F5-H2-bottom, F5-H2-top. H2's buckets
    # count regardless of the population-shift kill (M2): the kill is a
    # verdict override, not a reason to shrink the family.
    fdr_input = [
        {"name": "F5-H1", "p": h1_result["p"]},
        {"name": "F5-H2-bottom", "p": h2_bottom_result["p"]},
        {"name": "F5-H2-top", "p": h2_top_result["p"]},
    ]
    if len(fdr_input) != FDR_M:
        raise F5EvalError(
            f"FDR family size drifted: expected FDR_M={FDR_M}, built "
            f"{len(fdr_input)} p-values -- B2 regression.")
    corrected = family.benjamini_hochberg(fdr_input)
    by_name = {c["name"]: c for c in corrected}

    # ----------------------------------------------------------- verdicts --
    h1_verdict = compute_verdict(
        screen_passes=h1_screen["passes_screen"],
        replication_sign_agrees=h1_replication["sign_agrees"],
        replication_ci_excludes_zero=h1_replication["ci_excludes_zero"],
        survives_fdr=by_name["F5-H1"]["survives_fdr"],
        battery_survives=h1_battery["survives"])

    h2_bottom_verdict = compute_verdict(
        screen_passes=bottom_screen["passes_screen"],
        bucket_n_ok=bottom_n_ok,
        replication_sign_agrees=bottom_replication["sign_agrees"],
        replication_ci_excludes_zero=bottom_replication["ci_excludes_zero"],
        survives_fdr=by_name["F5-H2-bottom"]["survives_fdr"],
        devig_sign_survives=bottom_devig_ok,
        battery_survives=h2_bottom_battery["survives"],
        population_shift_fatal=shift["fatal"])

    h2_top_verdict = compute_verdict(
        screen_passes=top_screen["passes_screen"],
        bucket_n_ok=top_n_ok,
        replication_sign_agrees=top_replication["sign_agrees"],
        replication_ci_excludes_zero=top_replication["ci_excludes_zero"],
        survives_fdr=by_name["F5-H2-top"]["survives_fdr"],
        devig_sign_survives=top_devig_ok,
        battery_survives=h2_top_battery["survives"],
        population_shift_fatal=shift["fatal"])

    return {
        "h1": {
            "screen_2023": h1_screen,
            "result_2024": h1_result,
            "replication_gate": h1_replication,
            "battery": h1_battery,
            "survives_fdr": by_name["F5-H1"]["survives_fdr"],
            "verdict": h1_verdict,
        },
        "h2": {
            "edges_2023": edges,
            "bottom_n_2024": len(bottom_2024), "top_n_2024": len(top_2024),
            "bottom_meets_2024_floor": bottom_n_ok,
            "top_meets_2024_floor": top_n_ok,
            "population_shift": shift,
            "bottom": {
                "screen_2023": bottom_screen,
                "result_2024": h2_bottom_result,
                "replication_gate": bottom_replication,
                "battery": h2_bottom_battery,
                "devig_sign_survives": bottom_devig_ok,
                "survives_fdr": by_name["F5-H2-bottom"]["survives_fdr"],
                "verdict": h2_bottom_verdict,
            },
            "top": {
                "screen_2023": top_screen,
                "result_2024": h2_top_result,
                "replication_gate": top_replication,
                "battery": h2_top_battery,
                "devig_sign_survives": top_devig_ok,
                "survives_fdr": by_name["F5-H2-top"]["survives_fdr"],
                "verdict": h2_top_verdict,
            },
        },
        "devig_sensitivity": sensitivity,
        "per_book_h1": per_book_sign_replication(gradeable),
        "fdr_2024": corrected,
    }


# ---------------------------------------------------------------------------
# Entry point -- dry_run is the only mode this module's own mission
# authorises against real feature data.
# ---------------------------------------------------------------------------

def run(*, dry_run=True, primary_path=f5_universe.PRIMARY_VIEW_PATH,
        settlement_path=f5_universe.SETTLEMENT_PATH) -> dict:
    """`dry_run=True`: exercises row construction, both hash guards, the
    row-count/season-split/window guards, and the tercile fit -- all
    feature-side -- against real data, with `won` replaced by `None`
    everywhere and no `discovery.evaluate`/`battery.run` call made.
    `dry_run=False` calls `run_full_evaluation`, which reads `won`.
    """
    hashes = verify_universe(primary_path=primary_path, settlement_path=settlement_path)
    gradeable = load_gradeable_primary_rows(
        primary_path=primary_path, settlement_path=settlement_path)

    if not dry_run:
        result = run_full_evaluation(
            primary_path=primary_path, settlement_path=settlement_path)
        result["hashes"] = hashes
        result["dry_run"] = False
        return result

    h1_rows = build_h1_rows(gradeable, dry_run=True)
    _verify_row_shape(h1_rows)
    assert all(r["won"] is None for r in h1_rows), (
        "dry_run must never expose an outcome")

    h2_rows = build_h2_rows(gradeable, dry_run=True)
    assert all(r["won"] is None for r in h2_rows), (
        "dry_run must never expose an outcome")
    _verify_row_shape(h2_rows)  # N2: H2 gets the same shape guard as H1
    edges = fit_terciles_2023(h2_rows)  # feature-side: uses p_fav, not won
    _assign_buckets(h2_rows, edges)
    by_bucket = {b: sum(1 for r in h2_rows if r["season"] == "2024" and r["bucket"] == b)
                for b in (0, 1, 2)}

    return {
        "dry_run": True,
        "hashes": hashes,
        "row_counts": {"h1": len(h1_rows), "h2": len(h2_rows)},
        "season_split": {s: sum(1 for r in h1_rows if r["season"] == s)
                         for s in sorted({r["season"] for r in h1_rows})},
        "tercile_edges_2023": edges,
        "bucket_counts_2024": by_bucket,
        "note": ("no statistic computed -- won was never read; this is the "
                 "only mode authorised against real data until the family "
                 "is registered per PREREG_F5_FAMILIES.md (b)"),
    }
