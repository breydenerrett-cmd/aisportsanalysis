"""T2v: the variant runner must never be able to spend an API call.

Registration 17.6: "the publish job builds the candidate pool once per
publish run ... Zero additional API spend, by construction rather than by
policy." The way this file makes that a guarantee rather than a promise is
that `card_variants.py` cannot import a capture client at all -- checked on
the module's own AST (so a `# noqa`-style workaround can't hide it) and on
`sys.modules` after importing it in a fresh interpreter (so a transitive
import through some other path would also be caught).

The `sys.modules` check runs in a subprocess, not in this process: by the
time the suite reaches this file, other test modules have already imported
capture modules, so this process's `sys.modules` says nothing about what
importing card_variants pulls in. Deleting entries here to fake a clean slate
is not an option either -- a second copy of `src.providers.odds` then gets
imported later in the run, and code holding the first copy stops catching
the second copy's exceptions. That is what broke tests.test_f5_tminus2 on
3.11+ only: from 3.11, `mock.patch("src.providers.odds.quota")` (in
tests.test_cli_capture_commands_run) resolves its target with importlib and
so re-imports the deleted module, while src.pipeline.f5_tminus2 still holds
the first copy and its `except MarketsUnavailableAtDate` no longer matches.
"""

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.analysis import best_bets_card
from src.analysis import card_variants

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Modules that actually reach the network for odds/board capture. If
# card_variants ever needs one of these, that is exactly the "no additional
# API spend" guarantee breaking and this list is the place a reviewer will
# look.
_CAPTURE_MODULES = (
    "src.pipeline.live_odds",
    "src.providers.odds",
    "src.pipeline.nfl_capture",
)


def _module_source_path():
    return card_variants.__file__


# Runs in a fresh interpreter: import the named module, then report which of
# the capture modules are now loaded. Nothing else is imported first.
_PROBE = (
    "import importlib, json, sys\n"
    "importlib.import_module(sys.argv[1])\n"
    "print(json.dumps(sorted(m for m in sys.argv[2:] if m in sys.modules)))\n"
)


def _capture_modules_loaded_by_importing(module_name):
    """Capture modules present after importing `module_name` from scratch."""
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, module_name, *_CAPTURE_MODULES],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"importing {module_name} in a fresh interpreter failed:\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _top_level_imports(tree: ast.Module):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestNoCapture(unittest.TestCase):
    def test_module_ast_imports_no_capture_client(self):
        with open(_module_source_path(), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = _top_level_imports(tree)
        for capture_mod in _CAPTURE_MODULES:
            self.assertNotIn(capture_mod, imported)
            # also catch importing a submodule (e.g. "src.pipeline")
            # that would itself pull in the capture module as a side effect
            self.assertFalse(
                any(m == capture_mod.rsplit(".", 1)[0] for m in imported),
                f"card_variants.py imports the package containing {capture_mod}",
            )

    def test_capture_modules_not_pulled_in_by_importing_card_variants(self):
        loaded = _capture_modules_loaded_by_importing("src.analysis.card_variants")
        self.assertEqual(
            loaded, [],
            f"importing src.analysis.card_variants pulls in capture module(s) {loaded}")

    def test_the_probe_sees_a_transitive_capture_import(self):
        # Control: without it an empty list above could mean the probe is
        # blind. nfl_capture reaches src.providers.odds only through
        # src.pipeline.snapshots, so this also proves transitive imports show.
        loaded = _capture_modules_loaded_by_importing("src.pipeline.nfl_capture")
        self.assertIn("src.pipeline.nfl_capture", loaded)
        self.assertIn("src.providers.odds", loaded)


def _candidate(game_pk, price=-140, our_probability=0.62, price_class=None, kind="game"):
    return {
        "kind": kind,
        "game_pk": game_pk,
        "game_id": game_pk,
        "player_id": None,
        "market": "moneyline",
        "side": "home",
        "line": None,
        "price": price,
        "our_probability": our_probability,
        "market_probability": 0.58,
        "first_pitch_utc": "2026-09-20T23:05:00Z",
        "observed_utc": "2026-09-20T18:00:00Z",
        "game_type": "R",
        "books": 8,
        "take": True,
    }


class TestOnePoolFourArms(unittest.TestCase):
    def setUp(self):
        self.now = "2026-09-20T14:00:00Z"
        self.pool = [_candidate(5001), _candidate(5002, price=140, our_probability=0.45)]

    def test_run_family_calls_select_once_per_arm(self):
        calls = []
        real_select = best_bets_card.select

        def spy(*args, **kwargs):
            calls.append(kwargs.get("params"))
            return real_select(*args, **kwargs)

        best_bets_card.select = spy
        try:
            card_variants.run_family(self.pool, now=self.now)
        finally:
            best_bets_card.select = real_select
        self.assertEqual(len(calls), 4)
        self.assertEqual({p.rule_id for p in calls}, {a.rule_id for a in card_variants.ARMS.values()})

    def test_all_four_results_share_one_pool_hash(self):
        results = card_variants.run_family(self.pool, now=self.now)
        hashes = {r["pool_hash"] for r in results.values()}
        self.assertEqual(len(hashes), 1)
        self.assertEqual(hashes.pop(), card_variants.pool_hash(self.pool))

    def test_same_pool_object_passed_to_every_arm(self):
        seen_pool_ids = []
        real_select = best_bets_card.select

        def spy(candidates, **kwargs):
            seen_pool_ids.append(id(candidates))
            return real_select(candidates, **kwargs)

        best_bets_card.select = spy
        try:
            card_variants.run_family(self.pool, now=self.now)
        finally:
            best_bets_card.select = real_select
        self.assertEqual(len(set(seen_pool_ids)), 1, "every arm must see the identical pool object")
        self.assertEqual(seen_pool_ids[0], id(self.pool))


class TestNoArmScoreboard(unittest.TestCase):
    """Registration 17's ban on a running per-arm win-loss-units readout
    (see the module docstring): if this test ever needs to change to pass,
    stop and re-read why it exists first."""

    _FORBIDDEN_NAME_FRAGMENTS = ("record", "scoreboard", "win_loss", "units", "leaderboard")

    def test_module_defines_no_per_arm_record_function(self):
        public_funcs = [
            name
            for name in vars(card_variants)
            if not name.startswith("_") and callable(getattr(card_variants, name))
            and getattr(getattr(card_variants, name), "__module__", None) == card_variants.__name__
        ]
        offenders = [
            name for name in public_funcs
            if any(frag in name.lower() for frag in self._FORBIDDEN_NAME_FRAGMENTS)
        ]
        self.assertEqual(offenders, [], f"per-arm scoreboard-shaped function(s) found: {offenders}")

    def test_run_family_result_carries_no_units_or_record_key(self):
        results = card_variants.run_family(
            [_candidate(5001), _candidate(5002, price=140, our_probability=0.45)],
            now="2026-09-20T14:00:00Z",
        )
        for arm_id, result in results.items():
            for key in result:
                self.assertNotIn("units", key.lower())
                self.assertNotIn("scoreboard", key.lower())
                self.assertNotIn("win_loss", key.lower())


if __name__ == "__main__":
    unittest.main()
