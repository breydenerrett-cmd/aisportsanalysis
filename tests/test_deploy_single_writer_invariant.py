"""Single-writer deployment invariant: deploy/fly.staging.toml pins the
alpha to exactly ONE running Fly machine specifically because two of this
app's own in-process-only stores (src/appstate/ratelimit.py's fixed-window
limiter, src/appstate/freshness.py's TTL cache) would silently give each
additional worker process its own private counter/cache if more than one
ran -- correctness (a rate limit that no longer limits across workers, a
cache that no longer caches across them) would degrade QUIETLY instead of
failing loud. deploy/fly.staging.toml already names the sqlite
single-writer half of this reasoning in its own comments; this file pins
the other half, which lives in prose in two separate src/ modules that
nothing else cross-checks against the deploy config.

This test does not re-derive or re-exercise either module's actual
in-process behavior -- that already has its own coverage
(tests/test_appstate_ratelimit.py, tests/test_appstate_freshness.py). Its
job is narrower and specific to the INVARIANT: prove the deploy config and
each module's own documented admission of being per-process have not
drifted apart. A future engineer bumping max_machines_running for more
throughput, without first replacing these two in-process stores with a
shared one, is exactly the silent-correctness-loss this test exists to
catch at review time -- and a future engineer who DOES replace one of them
with a real shared store (Redis, e.g.) should see this test fail the
moment the docstring's own admission is removed, as the signal that the
invariant (and this test) need revisiting together, not a stale green
check nobody looks at again.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FLY_STAGING_TOML = REPO / "deploy" / "fly.staging.toml"
RATELIMIT_PY = REPO / "src" / "appstate" / "ratelimit.py"
FRESHNESS_PY = REPO / "src" / "appstate" / "freshness.py"

# The word both modules' docstrings use, independently, to admit they hold
# per-process state with no cross-process sharing -- ratelimit.py's
# "IN-PROCESS, NOT DISTRIBUTED" section ("a per-process dict guarded by a
# lock") and freshness.py's "No cross-process sharing" section ("an
# in-memory, per-process cache"). Grepped for rather than hard-coded
# true/false so a future rewording or removal of the admission fails this
# test loud, instead of the test silently passing against code that no
# longer says what it asserts.
_IN_PROCESS_PHRASE = "per-process"

_MAX_MACHINES_RE = re.compile(r'^\s*max_machines_running\s*=\s*(\d+)', re.MULTILINE)


class SingleWriterInvariantTests(unittest.TestCase):

    def test_fly_staging_caps_max_machines_running_at_one(self):
        toml_text = FLY_STAGING_TOML.read_text(encoding="utf-8")
        match = _MAX_MACHINES_RE.search(toml_text)
        self.assertIsNotNone(
            match, "deploy/fly.staging.toml must set max_machines_running")
        # See module docstring: this cap is load-bearing for TWO reasons
        # today, not one -- sqlite's single-writer-across-processes
        # constraint (fly.staging.toml's own comment already names this)
        # AND the in-process-only rate limiter/freshness cache this test
        # exists to keep honest. Raising it silently breaks whichever of
        # the two nobody happened to be thinking about at the time.
        self.assertEqual(
            int(match.group(1)), 1,
            "deploy/fly.staging.toml raised max_machines_running above 1 -- "
            "this is only safe once BOTH src/appstate/ratelimit.py and "
            "src/appstate/freshness.py are backed by something shared "
            "across processes (see this test's module docstring)")

    def test_ratelimit_module_documents_itself_as_in_process_only(self):
        text = RATELIMIT_PY.read_text(encoding="utf-8")
        self.assertIn(
            _IN_PROCESS_PHRASE, text,
            "src/appstate/ratelimit.py no longer documents itself as "
            f"{_IN_PROCESS_PHRASE!r} -- if it now has a real cross-process "
            "backing store, the single-machine deploy invariant this file "
            "pins may no longer need to hold on this store's account "
            "(sqlite's own single-writer constraint may still require it)")

    def test_freshness_module_documents_itself_as_in_process_only(self):
        text = FRESHNESS_PY.read_text(encoding="utf-8")
        self.assertIn(
            _IN_PROCESS_PHRASE, text,
            "src/appstate/freshness.py no longer documents itself as "
            f"{_IN_PROCESS_PHRASE!r} -- if it now has a real cross-process "
            "backing store, the single-machine deploy invariant this file "
            "pins may no longer need to hold on this store's account "
            "(sqlite's own single-writer constraint may still require it)")


if __name__ == "__main__":
    unittest.main()
