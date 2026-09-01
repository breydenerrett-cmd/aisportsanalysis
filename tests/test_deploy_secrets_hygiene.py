"""deploy/secrets.md's NEVER-COMMIT rule, made machine-checkable.

Two independent checks, same reasoning as test_api_boundary.py's "check
the property two ways": a rule stated only in prose gets violated by
accident the first time someone is in a hurry.

1. No `.env` file is tracked by git (only `.env.example`, which is
   `!`-allowed in `.gitignore` and holds no real values).
2. No committed file outside `docs/` contains a string shaped like a live
   or test Stripe secret key (`sk_live_...` / `sk_test_...`). `docs/` is
   excluded because this launch-decisions packet needs to be able to
   discuss the *shape* of Stripe's key prefixes in prose without that
   prose itself tripping the scan -- see docs/LAUNCH_DECISIONS.md and this
   file's own deploy/secrets.md, which both say the words "sk_live_" /
   "sk_test_" without ever pairing them with a real key body.

Runs against `git ls-files`, not a directory walk -- the property this
test cares about is what's actually COMMITTED, not what happens to sit in
a local working tree (a real .env sits right there in this checkout,
untracked, and must not fail this test).
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent

# Real Stripe secret keys are `sk_live_`/`sk_test_` followed by a long
# alphanumeric body -- long enough (20+ chars) that this does not
# false-positive on the bare prefix appearing in prose (e.g. this test's
# own docstring, or deploy/secrets.md's table, which say "sk_live_" and
# "sk_test_" without a key body attached).
STRIPE_KEY_RE = re.compile(r"sk_(live|test)_[A-Za-z0-9]{20,}")


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


class NoEnvFileTrackedTest(unittest.TestCase):
    def test_no_dotenv_file_is_committed(self):
        tracked = _tracked_files()
        offenders = [
            f for f in tracked
            if pathlib.Path(f).name == ".env"
            or (pathlib.Path(f).name.startswith(".env.")
                and pathlib.Path(f).name != ".env.example")
        ]
        self.assertEqual(offenders, [],
                         f".env-shaped file(s) committed: {offenders}")


class NoRealLookingStripeKeyCommittedTest(unittest.TestCase):
    def test_no_stripe_secret_key_shape_outside_docs(self):
        tracked = _tracked_files()
        offenders = []
        for rel in tracked:
            path = REPO / rel
            if rel.startswith("docs/") or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable -- not a text secret leak
            if STRIPE_KEY_RE.search(text):
                offenders.append(rel)
        self.assertEqual(offenders, [],
                         f"Stripe secret-key-shaped string committed outside "
                         f"docs/: {offenders}")


if __name__ == "__main__":
    unittest.main()
