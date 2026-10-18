"""The desk package loads and runs without FastAPI, a model client or a network.

The hounds pages run in the web image and the scheduled session runs a plain Python; neither may need an HTTP
framework to import this package, and nothing in it may call a model or a network (the project has no API key and
this family must never grow a path that uses one).
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "hounds" / "desk"

MODULES = ("src.hounds.desk", "src.hounds.desk.roles", "src.hounds.desk.schemas", "src.hounds.desk.risk",
           "src.hounds.desk.builder", "src.hounds.desk.checks", "src.hounds.desk.state",
           "src.hounds.desk.prepare", "src.hounds.desk.session", "src.hounds.desk.publish",
           "src.hounds.desk.ledger", "src.hounds.desk.grade", "src.hounds.desk.disagree",
           "src.hounds.desk.cli")

PROBE = r"""
import importlib, sys
for blocked in ("fastapi", "starlette", "uvicorn", "anthropic", "httpx", "requests", "aiohttp"):
    sys.modules[blocked] = None          # an import of any of these now raises ImportError
for name in %r:
    importlib.import_module(name)
loaded = sorted(m for m in sys.modules if m.split(".")[0] in ("fastapi", "starlette", "uvicorn", "anthropic")
                and sys.modules[m] is not None)
print("OK", loaded)
"""


class LoadsWithoutFastApi(unittest.TestCase):
    def test_every_module_imports_with_the_http_frameworks_blocked(self):
        proc = subprocess.run([sys.executable, "-c", PROBE % (MODULES,)], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=120,
                              env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertTrue(proc.stdout.startswith("OK []"), proc.stdout)

    def test_the_cli_help_runs_without_them(self):
        proc = subprocess.run([sys.executable, "-c",
                               "import sys\nsys.modules['fastapi']=None\nsys.modules['starlette']=None\n"
                               "from src.hounds.desk import cli\ncli.build_parser().format_help()\nprint('OK')"],
                              cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                              env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])


class NothingCallsAModelOrANetwork(unittest.TestCase):
    FORBIDDEN = (r"\bsocket\b", r"urlopen", r"urllib\.request", r"http\.client", r"\bsubprocess\b",
                 r"ANTHROPIC_API_KEY", r"post_message", r"urllib_post", r"\.analyze\(", r"\bos\.system\b",
                 r"\bimport requests\b")

    def test_no_module_in_the_package_reaches_for_one(self):
        for path in sorted(PACKAGE.glob("*.py")):
            code = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#"))
            # the docstrings may NAME these things (to say they are not used); code may not call them
            body = re.sub(r'"""[\s\S]*?"""', "", code)
            for pattern in self.FORBIDDEN:
                self.assertIsNone(re.search(pattern, body), f"{path.name} contains {pattern!r}")

    def test_no_module_places_or_sizes_a_bet(self):
        for path in sorted(PACKAGE.glob("*.py")):
            body = re.sub(r'"""[\s\S]*?"""', "", path.read_text(encoding="utf-8")).lower()
            for needle in ("place_bet", "stake_size", "kelly", "bankroll"):
                self.assertNotIn(needle, body, f"{path.name} mentions {needle}")


if __name__ == "__main__":
    unittest.main()
