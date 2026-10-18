"""Run a Hounds page's real script under node against a fake DOM built from the page's real HTML.

Shared by tests/test_hounds_web_*.py. See tests/hounds_web_harness.mjs for the scenario keys.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
HAS_NODE = shutil.which("node") is not None

PAGES = {
    "hounds": ("hounds.html", "hounds-page.js"),
    "hound": ("hound.html", "hounds-detail.js"),
    "build": ("build-a-hound.html", "hounds-build.js"),
}

_tmp = None


def _workdir() -> Path:
    global _tmp
    if _tmp is None:
        _tmp = tempfile.TemporaryDirectory()
        atexit.register(_tmp.cleanup)
        for path in (WEB / "js").glob("*.js"):
            shutil.copy(path, _tmp.name)
        shutil.copy(Path(__file__).parent / "hounds_web_harness.mjs", _tmp.name)
        Path(_tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
    return Path(_tmp.name)


def run_page(page: str, **scenario) -> dict:
    html, module = PAGES[page]
    work = _workdir()
    scenario["html"] = str(WEB / html)
    scenario["module"] = (work / module).as_uri()
    env = dict(os.environ, SCENARIO=json.dumps(scenario))
    proc = subprocess.run(["node", "hounds_web_harness.mjs"], cwd=work, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=90)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")]
    if proc.returncode != 0 or not lines:
        raise AssertionError(f"harness failed ({proc.returncode}): {proc.stderr[-2000:]}\n{proc.stdout[-1000:]}")
    out = json.loads(lines[-1][2:])
    if out.get("crashed"):
        raise AssertionError(out["crashed"])
    return out


def run_js(source: str) -> object:
    """Evaluate a snippet that imports hounds-core.js / hounds-chart.js-free pure helpers and prints JSON."""
    work = _workdir()
    (work / "snippet.mjs").write_text(source, encoding="utf-8")
    proc = subprocess.run(["node", "snippet.mjs"], cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])
