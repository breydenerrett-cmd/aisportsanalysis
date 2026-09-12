"""Every static import in web/js resolves to a file that exists.

There is no build step: the browser loads the ES-module graph straight
from disk, and one missing module fails the whole graph -- the app
renders nothing, with no error in the page. On 2026-09-12 two view
modules were deleted while today.js still imported one of them (a
`void renderOpportunities;` reference nobody was reading), and the app
was blank on staging until the next push. A grep for the importer had
been cut short by `head`.

This is the check that would have gone red before that push. It reads
every `from "./x.js"` and `import("./x.js")` in every module and asserts
the target is on disk. Plain text, no JS engine, like the other web
structure tests.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

STATIC = re.compile(r"""^\s*(?:import|export)\b[^;]*?\bfrom\s+["'](\./[^"']+)["']""", re.M)
DYNAMIC = re.compile(r"""\bimport\(\s*["'](\./[^"']+)["']\s*\)""")


def _imports(path: Path):
    text = path.read_text(encoding="utf-8")
    # Strip block and line comments: docstrings here quote old import
    # lines as history.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("//"))
    return sorted(set(STATIC.findall(text)) | set(DYNAMIC.findall(text)))


class EveryImportResolves(unittest.TestCase):

    def test_no_module_imports_a_file_that_is_not_there(self):
        missing = []
        for module in sorted(WEB_JS.glob("*.js")):
            for target in _imports(module):
                if not (module.parent / target).is_file():
                    missing.append(f"{module.name} -> {target}")
        self.assertEqual(missing, [],
                         "these imports point at files that do not exist; the browser "
                         "will load nothing:\n" + "\n".join(missing))

    def test_the_scanner_sees_the_graph(self):
        """A regex that stopped matching would turn the test above green
        forever. main.js alone imports a dozen views."""
        self.assertGreater(len(_imports(WEB_JS / "main.js")), 8)
        self.assertIn("./games.js", _imports(WEB_JS / "main.js"))

    def test_the_deleted_views_are_imported_by_nothing(self):
        for module in sorted(WEB_JS.glob("*.js")):
            for target in _imports(module):
                self.assertNotIn(target, ("./featuredbet.js", "./opportunities.js"),
                                 f"{module.name} imports a deleted module")


if __name__ == "__main__":
    unittest.main()
