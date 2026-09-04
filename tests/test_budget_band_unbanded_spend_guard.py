"""Regression guard: no envelope decision anywhere may read the UNBANDED
daily total.

THE BUG THIS PINS (found 2026-09-04, second round)
----------------------------------------------------
The 2026-09-04 band-fix (`budget_band` on every credit-log row;
`capture_spent_today()` restricting the envelope check to the LIVE_CAPTURE
band) landed correctly in `src.capture.budget.can_spend`'s own default path
-- omit `spent=` and it calls `capture_spent_today()`, band-correct. But
`batter_props.run` and `derivative_markets.run` did not omit it: both
explicitly computed

    spent=budget_module.spent_today(store=credit_log_store)

and handed that UNBANDED total to `can_spend(..., spent=...)`, silently
overriding the correct default with the same unbanded read the whole band
system exists to avoid. A same-day ~47,000-credit approved historical
backfill (a different band entirely) then pushed that unbanded total over
`DAILY_ENVELOPE`, and both families were refused with "skipped: daily
envelope" despite real live-capture spend that day being a few dozen
credits. `tests/test_capture_credit_log_hermeticity.py`'s
`test_every_can_spend_call_avoids_the_ambient_envelope_default` did not
catch this: it only checks that a `can_spend(...)` call passes `store=` or
`spent=` SOME explicit value -- proving the call is hermetic (test-isolated)
tells you nothing about whether that value is band-correct. A call can be
perfectly hermetic and still be wrong in exactly this way.

THE INVARIANT THIS GUARDS
--------------------------
Anywhere in `src/`, a `can_spend(...)` call's `spent=` argument -- if given
at all -- must never be fed by a bare, unbanded `spent_today(...)` call.
The only band-correct ways to supply `spent=` are: omit it (the `can_spend`
default, which is `capture_spent_today()`), pass literal `None`, or pass a
`capture_spent_today(...)` call directly (which is itself
`spent_today(..., band=LIVE_CAPTURE)` under the hood -- see budget.py).

This is checked structurally via `ast`, not by scanning source text for the
name `spent_today` -- every module in this package discusses
`spent_today`/`capture_spent_today`/bands constantly in prose and comments,
which would false-positive any substring search. `src/capture/budget.py`
itself is exempt: it is where `spent_today`, `capture_spent_today`, and
`can_spend` are DEFINED, so it necessarily contains the bare name in
implementation code that is not, itself, a caller's envelope decision.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"

# The module that defines spent_today/capture_spent_today/can_spend. Its own
# body legitimately contains bare `spent_today` -- that is the definition,
# not a caller reading an unbanded total to gate a spend.
_BUDGET_MODULE_PATH = _SRC / "capture" / "budget.py"


def _iter_source_files():
    for path in sorted(_SRC.rglob("*.py")):
        if path == _BUDGET_MODULE_PATH:
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _attr_name(node: ast.AST):
    """The trailing attribute name of a Call's func, e.g. `can_spend` for
    `budget_module.can_spend(...)`, or None if `node` isn't shaped that way
    (a bare-name call, a subscript, etc.) -- deliberately alias-agnostic so
    this does not depend on every module importing `budget` under the same
    name."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _contains_bare_spent_today_call(node: ast.AST) -> bool:
    """True if `node`'s subtree contains a call to a `.spent_today(...)`
    attribute that is NOT `.capture_spent_today(...)` -- i.e. a call to the
    unbanded reader. `capture_spent_today` itself ends in `_spent_today` but
    is matched exactly by name, so it is never confused with the bare one."""
    for sub in ast.walk(node):
        name = _attr_name(sub)
        if name == "spent_today":
            return True
    return False


class NoUnbandedSpendFeedsAnEnvelopeDecisionTests(unittest.TestCase):
    """The structural guard: every `can_spend(...)` call's `spent=` kwarg,
    wherever it appears in `src/`, must never be fed by a bare
    `spent_today(...)` call."""

    def test_every_can_spend_call_site_in_src(self):
        checked_any_call = False
        for path in _iter_source_files():
            tree = _parse(path)
            for node in ast.walk(tree):
                if _attr_name(node) != "can_spend":
                    continue
                checked_any_call = True
                spent_kwargs = [kw for kw in node.keywords if kw.arg == "spent"]
                if not spent_kwargs:
                    # Omitted entirely -- falls through to can_spend's own
                    # band-correct default (capture_spent_today()). Fine.
                    continue
                for kw in spent_kwargs:
                    with self.subTest(file=str(path.relative_to(_REPO_ROOT)),
                                       lineno=node.lineno):
                        self.assertFalse(
                            _contains_bare_spent_today_call(kw.value),
                            f"{path.relative_to(_REPO_ROOT)}:{node.lineno}: "
                            "a can_spend(...) call's spent= argument is fed "
                            "by a bare, UNBANDED spent_today(...) call -- "
                            "this is the 2026-09-04 second-round regression "
                            "(batter_props.run/derivative_markets.run). Use "
                            "capture_spent_today(...), or omit spent= "
                            "entirely and let can_spend's own default "
                            "(capture_spent_today()) supply it.")
        self.assertTrue(
            checked_any_call,
            "found zero can_spend(...) call sites under src/ -- this guard "
            "cannot prove anything if the thing it's guarding has vanished; "
            "check _iter_source_files()/_attr_name() against a repo "
            "restructure before trusting a green run")

    def test_capture_spent_today_itself_is_band_scoped_to_live_capture(self):
        """Pins the one exemption this guard relies on: `capture_spent_today`
        must actually restrict to LIVE_CAPTURE, or "use capture_spent_today
        instead" (the fix this guard demands everywhere else) would just be
        moving the same bug sideways."""
        import src.capture.budget as budget_module

        tree = _parse(_BUDGET_MODULE_PATH)
        target = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "capture_spent_today":
                target = node
                break
        self.assertIsNotNone(
            target, "src/capture/budget.py no longer defines "
                     "capture_spent_today() -- this guard's one exemption "
                     "no longer exists")
        calls = [n for n in ast.walk(target)
                 if _attr_name(n) is None and isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "spent_today"]
        self.assertTrue(
            calls, "capture_spent_today() no longer calls spent_today() at "
                   "all -- inspect its new implementation by hand")
        for call in calls:
            band_kwargs = {kw.arg: kw.value for kw in call.keywords}
            self.assertIn(
                "band", band_kwargs,
                "capture_spent_today()'s spent_today(...) call has no "
                "band= kwarg -- it would read every band, defeating the "
                "one exemption this guard grants it")
            value = band_kwargs["band"]
            self.assertTrue(
                isinstance(value, ast.Name) and value.id == "LIVE_CAPTURE",
                "capture_spent_today()'s spent_today(band=...) is not "
                "LIVE_CAPTURE -- it no longer means what its name and every "
                "caller of it assume")
        # Behavioral belt-and-suspenders: LIVE_CAPTURE must actually be the
        # band spent_today's own filtering keys off, not just a same-named
        # local unrelated to it.
        self.assertEqual(budget_module.LIVE_CAPTURE, "live_capture")


if __name__ == "__main__":
    unittest.main()
