"""The api/ <-> src/ boundary is one-directional, and this test proves it.

WHY THIS TEST EXISTS
--------------------
api/ is the non-visual application skeleton: FastAPI, uvicorn, pydantic --
third-party dependencies src/ has never needed and must never acquire, or
every domain module quietly becomes untestable without a web framework
installed. The rule is simple to state and easy to violate by accident (one
convenience import in a detector, six months from now, and nobody notices
because both directories still import cleanly in an environment that
happens to have both installed): src/ imports NOTHING from api/, ever.

This test checks the property two ways, the same way
test_forward_evidence_tracked.py checks its property two ways: a static
grep over the source text (catches the import even if the module it names
does not exist yet), and a runtime import with third-party packages hidden
from the path (catches an import that only an installed pydantic/fastapi
would let slide silently).
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

# Matches `import api`, `import api.today`, `from api import x`,
# `from api.today import x` -- but not an unrelated identifier that merely
# contains "api" (e.g. `capital`, `rapid`).
API_IMPORT_RE = re.compile(r"^\s*(?:import\s+api(?:\.\w+)*\b|from\s+api(?:\.\w+)*\s+import\b)")


def _grep_src_for_api_imports() -> list:
    hits = []
    for path in sorted(SRC.rglob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if API_IMPORT_RE.match(line):
                hits.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()}")
    return hits


class ApiBoundaryTests(unittest.TestCase):

    def test_no_src_file_imports_api(self):
        """Static check: grep every src/ module for an `import api` /
        `from api` statement. Extends the pattern of
        test_forward_evidence_tracked.py -- a property of the repository,
        checked by text, not by trusting that nobody will ever add the line.
        """
        hits = _grep_src_for_api_imports()
        self.assertEqual(
            hits, [],
            "src/ must never import from api/ -- the boundary is one-way "
            "(api/ depends on src/, not the reverse). Offending line(s): "
            + "; ".join(hits))

    def test_src_imports_cleanly_with_no_third_party_packages_on_path(self):
        """Runtime check: src/ has to import with ONLY the stdlib and this
        repo on sys.path -- no fastapi, uvicorn, or pydantic reachable at
        all. A subprocess with -S (no site-packages) proves it for real,
        rather than trusting that nothing in src/ happens to `import api`
        (already covered above) or a third-party package api/ pulls in.
        """
        result = subprocess.run(
            [sys.executable, "-S", "-c",
             "import sys; sys.path.insert(0, %r); "
             "import src.pipeline.briefing; import src.analysis.contracts; "
             "import src.detect.dossier; print('OK')" % str(REPO)],
            cwd=REPO, capture_output=True, text=True, check=False)
        self.assertEqual(
            result.returncode, 0,
            "src/ failed to import with no third-party packages on the "
            "path (stdlib + repo only). This means something in src/ now "
            "depends on a package that should live only in api/.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
