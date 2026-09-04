"""Regression guard: every paid-capture `run()` must thread its OWN
credit-log store into the budget envelope check, never fall back to
`budget.spent_today()`'s real-disk default.

THE BUG THIS PINS (found and fixed 2026-09-04)
------------------------------------------------
`budget.can_spend()`'s FLOOR half is safe: every one of these five modules
already reads `remaining` fresh off `provider.quota()` each call and passes
it straight through (`can_spend(..., remaining=remaining)`), so the floor
check never touches disk. The ENVELOPE half is a different story --
`can_spend` re-derives `spent` via `budget.spent_today()`, a read of
data/processed/credit_log.jsonl, whenever a caller omits `spent`. None of
dense.run/prop_listing.run/prop_prices.run/derivative_markets.run/
batter_props.run did, before this fix.

That is invisible on a quiet day (a handful of small rows keeps
`spent_today()` well under the ~900/day `DAILY_ENVELOPE`), which is exactly
why it went unnoticed: a real, owner-approved ~36,451-credit historical
purchase logged today pushed the real log's `spent_today()` to ~26,174,
comfortably over the envelope, and every one of these five modules' unit
tests -- which assert that a fetch happens -- went red with ZERO code
change (54 failures/errors across tests/test_dense.py,
tests/test_prop_listing.py, tests/test_prop_prices.py,
tests/test_multibook.py, tests/test_derivative_markets.py). A suite that
can silently flip green<->red on which day a legitimate purchase landed
cannot gate anything, which is the whole reason this file exists.

THE FIX AND WHAT THIS GUARDS
-----------------------------
Each `run()` now takes a `credit_log_store` kwarg (default `None` == real
disk, so production behavior is byte-identical) threaded into
`can_spend(..., store=credit_log_store)` directly, or into a nested
`spent_today(store=credit_log_store)` passed as `can_spend(..., spent=...)`
(derivative_markets.run, batter_props.run -- the latter passes `spent=None`
outright for the non-droppable floor family, which is correct: that family
is EXEMPT from the envelope by `can_spend`'s own contract, see
`budget.can_spend`'s docstring point 1, so it never needs a store at all).
Every affected unit test now passes `tests.HERMETIC_CREDIT_LOG_STORE` -- a
path guaranteed to never exist -- instead of leaving this seam at its
real-disk default.

This test never runs `run()` and never touches the real credit log. It
statically inspects each module's AST -- never a substring/grep match,
because these modules discuss `budget_module`, `spent_today`, and the
credit log constantly in prose and in comments that would false-positive a
text search -- and fails the moment a future edit lets any of these five
`can_spend`/`spent_today` call sites go back to silently reading whatever
`data/processed/credit_log.jsonl` holds today.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "pipeline"

# Every paid-capture module whose `run()` gates a nonzero spend through
# `budget_module.can_spend`. weather_capture.py is deliberately NOT here --
# its one `can_spend("weather", 0)` call has `est_credits=0`, which
# `can_spend`'s own contract (see budget.py: "if family != NON_DROPPABLE_
# FAMILY and est_credits > 0") means never reaches the floor or envelope at
# all, so it has no `spent_today()` fallback to guard.
CAPTURE_MODULES = (
    "dense.py",
    "prop_listing.py",
    "prop_prices.py",
    "derivative_markets.py",
    "batter_props.py",
)

BUDGET_ALIAS = "budget_module"  # the import alias every module above uses


def _parse(filename: str) -> ast.Module:
    path = _SRC / filename
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_run(tree: ast.Module) -> ast.FunctionDef:
    """The module-level `def run(...)` -- the one paid-capture entry point
    each of these modules exposes. Fails loudly (not skips) if a module
    stops defining one under this name: a silently-vanished target proves
    nothing."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            return node
    raise AssertionError(f"no module-level `def run` found")


def _kwarg_names(call: ast.Call) -> set:
    return {kw.arg for kw in call.keywords if kw.arg is not None}


def _is_budget_call(node: ast.AST, attr: str) -> bool:
    """True if `node` is a Call to `budget_module.<attr>(...)`, matched by
    AST shape (an Attribute access on the known import alias), never by
    scanning the source text for the name -- the docstrings above and in
    every module here use `spent_today`/`can_spend` constantly in prose."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == attr
            and isinstance(func.value, ast.Name) and func.value.id == BUDGET_ALIAS)


class CreditLogSeamExistsTests(unittest.TestCase):
    """Every affected `run()` must expose the injection seam at all."""

    def test_run_takes_a_credit_log_store_parameter(self):
        for filename in CAPTURE_MODULES:
            with self.subTest(module=filename):
                run_fn = _find_run(_parse(filename))
                arg_names = {a.arg for a in run_fn.args.args} | \
                    {a.arg for a in run_fn.args.kwonlyargs}
                self.assertIn(
                    "credit_log_store", arg_names,
                    f"{filename}'s run() lost its `credit_log_store` seam -- "
                    "without it a test cannot redirect the envelope check "
                    "away from the real, mutating credit_log.jsonl")


class EnvelopeCheckIsHermeticTests(unittest.TestCase):
    """The call sites that actually matter: can_spend/spent_today must be
    wired to the seam, not left on the real-disk default."""

    def test_every_spent_today_call_passes_an_explicit_store(self):
        for filename in CAPTURE_MODULES:
            with self.subTest(module=filename):
                run_fn = _find_run(_parse(filename))
                calls = [n for n in ast.walk(run_fn)
                         if _is_budget_call(n, "spent_today")]
                for call in calls:
                    self.assertIn(
                        "store", _kwarg_names(call),
                        f"{filename}: a `{BUDGET_ALIAS}.spent_today(...)` "
                        "call inside run() has no `store=` kwarg, so it "
                        "reads the real data/processed/credit_log.jsonl -- "
                        "this is exactly the 2026-09-04 regression; pass "
                        "`store=credit_log_store`")

    def test_every_can_spend_call_avoids_the_ambient_envelope_default(self):
        for filename in CAPTURE_MODULES:
            with self.subTest(module=filename):
                run_fn = _find_run(_parse(filename))
                calls = [n for n in ast.walk(run_fn)
                         if _is_budget_call(n, "can_spend")]
                self.assertTrue(calls, f"{filename}: run() no longer calls "
                                        f"{BUDGET_ALIAS}.can_spend at all")
                for call in calls:
                    kwargs = _kwarg_names(call)
                    # Either the call passes its own `store=` straight
                    # through (dense/prop_listing/prop_prices' pattern), or
                    # it passes `spent=` explicitly -- a literal `None` (the
                    # non-droppable floor family, exempt from the envelope
                    # by `can_spend`'s own contract) or a nested,
                    # store-scoped `spent_today(...)` call (derivative_
                    # markets/batter_props' pattern, already checked by
                    # `test_every_spent_today_call_passes_an_explicit_store`
                    # above). What is NEVER acceptable is neither: that is
                    # `can_spend` falling through to `spent_today(now=now,
                    # store=store)` with `store=None`, i.e. real disk.
                    self.assertTrue(
                        "store" in kwargs or "spent" in kwargs,
                        f"{filename}: a `{BUDGET_ALIAS}.can_spend(...)` call "
                        "inside run() passes neither `store=` nor `spent=` -- "
                        "its envelope decision falls back to reading the "
                        "real, mutating credit_log.jsonl")


CREDITLOG_ALIAS = "creditlog"  # the import alias every module above uses


def _is_creditlog_log_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == "log"
            and isinstance(func.value, ast.Name) and func.value.id == CREDITLOG_ALIAS)


class BudgetBandIsExplicitAtEveryWriteTests(unittest.TestCase):
    """Owner amendment (2026-09-04): band classification must be explicit
    and durable, declared by the writer at write time via `budget_band=`,
    never inferred later from a caller string. Every `creditlog.log(...)`
    call inside one of these five modules' `run()` must pass `budget_band=`
    -- and, since these ARE the live-capture entry points, it must be
    `budget_module.LIVE_CAPTURE` specifically, not some other band."""

    def test_every_creditlog_log_call_declares_live_capture(self):
        for filename in CAPTURE_MODULES:
            with self.subTest(module=filename):
                run_fn = _find_run(_parse(filename))
                calls = [n for n in ast.walk(run_fn)
                         if _is_creditlog_log_call(n)]
                self.assertTrue(calls, f"{filename}: run() no longer calls "
                                        "creditlog.log at all")
                for call in calls:
                    band_kwargs = [kw for kw in call.keywords
                                   if kw.arg == "budget_band"]
                    self.assertTrue(
                        band_kwargs,
                        f"{filename}: a `creditlog.log(...)` call inside "
                        "run() has no `budget_band=` kwarg -- this is the "
                        "2026-09-04 amendment's regression: an unbanded row "
                        "falls back to legacy caller-name classification "
                        "instead of declaring its own band explicitly")
                    value = band_kwargs[0].value
                    self.assertTrue(
                        isinstance(value, ast.Attribute)
                        and value.attr == "LIVE_CAPTURE"
                        and isinstance(value.value, ast.Name)
                        and value.value.id == BUDGET_ALIAS,
                        f"{filename}: `budget_band=` on a live-capture "
                        f"module's own creditlog.log call must be "
                        f"`{BUDGET_ALIAS}.LIVE_CAPTURE`")


if __name__ == "__main__":
    unittest.main()
