"""Run a Hounds page's real script under node against a fake DOM built from the page's real HTML.

Shared by tests/test_hounds_web_*.py. See tests/hounds_web_harness.mjs for the scenario keys.
"""

from __future__ import annotations

import atexit
import itertools
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
    # the hound quiz (tests/test_hounds_quiz_web.py)
    "quiz": ("quiz.html", "hound-quiz.js"),
    "learning": ("learning.html", "hounds-learning.js"),
    # the training camp as a visitor gets it: the scorecard script and the camp's own (web/js/dog-camp.js) together
    "camp": ("learning.html", "camp_boot.js"),
    # the landing page's leaderboard panel: landing-board.js has no auto-run, so a two-line boot file runs it
    "landing_board": ("landing.html", "board_boot.js"),
    # the admin dashboard (tests/test_admin_dashboard.py); its fixtures are tests/admin_dashboard_fixtures.py
    "admin": ("admin.html", "admin-app.js"),
    # the kennel page (My kennel and a public kennel), the leaderboard's Kennels view, the shared navigation and the tabs.
    # The navigation and the tabs run on whichever page the scenario names with `page_html`.
    "kennel": ("kennel.html", "kennel.js"),
    "kennels_index": ("hounds.html", "kennels-index.js"),
    "nav": ("hounds.html", "nav.js"),
    "tabs": ("hound.html", "tabs.js"),
    # the live board, "What's on" (tests/test_live_board.py); its fixtures are tests/fixtures/sports_now.json
    "live": ("live.html", "live-board.js"),
    # the graveyard (tests/test_hounds_rites_web.py): every dog a member took out back
    "graveyard": ("graveyard.html", "graveyard.js"),
}

_tmp = None
_counter = itertools.count()


def _workdir() -> Path:
    global _tmp
    if _tmp is None:
        _tmp = tempfile.TemporaryDirectory()
        atexit.register(_tmp.cleanup)
        for path in (WEB / "js").glob("*.js"):
            shutil.copy(path, _tmp.name)
        shutil.copy(Path(__file__).parent / "hounds_web_harness.mjs", _tmp.name)
        Path(_tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(_tmp.name, "camp_boot.js").write_text(
            'import "./hounds-learning.js";\nimport "./dog-camp.js";\n', encoding="utf-8")
        Path(_tmp.name, "board_boot.js").write_text(
            'import { fillBoard } from "./landing-board.js";\nawait fillBoard();\n', encoding="utf-8")
    return Path(_tmp.name)


def run_page(page: str, **scenario) -> dict:
    html, module = PAGES[page]
    html = scenario.pop("page_html", html)
    work = _workdir()
    scenario["html"] = str(WEB / html)
    scenario["module"] = (work / module).as_uri()
    # In a file, not the environment: Linux caps one environment variable at 128 KB.
    scenario_file = work / f"scenario_{os.getpid()}_{next(_counter)}.json"
    scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
    env = dict(os.environ, SCENARIO_FILE=str(scenario_file))
    if scenario.get("tz"):
        env["TZ"] = scenario["tz"]
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
