"""docs/datasvc/CLIENT.md says what the code does: the generated tables match, and the examples run.

The doc is the source of the three examples: they are read out of the file and executed against synthetic
stores, so an example that stops working (a renamed key, a changed shape) fails here before a reader finds it.
The route table is generated from the router and the basis table from `client.BASIS`; both are compared to the
doc, and the doc says how to regenerate them. Offline throughout.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.datasvc import client as core
from src.datasvc.client import DataClient
from tests import _nfl_world as W
from tests import analyst_fixtures as F
from tests.test_datasvc_mlb_service import World
from tests.test_datasvc_ufc_api import HAS_FASTAPI
from tests.test_datasvc_ufc_features import build_store

if HAS_FASTAPI:
    from api import datasvc

DOC = Path(__file__).resolve().parent.parent / "docs" / "datasvc" / "CLIENT.md"


def block(text: str, name: str) -> str:
    match = re.search(rf"<!-- {name}:begin -->\n(.*?)\n<!-- {name}:end -->", text, re.S)
    assert match, f"{name} markers missing from {DOC}"
    return match.group(1)


def examples(text: str) -> dict:
    found = dict(re.findall(r"<!-- example: (\w+) -->\n```python\n(.*?)\n```", text, re.S))
    return found


class Doc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")

    def test_the_basis_table_is_the_codes(self):
        self.assertEqual(block(self.text, "basis"), core.basis_reference(),
                         "regenerate with: python -m src.datasvc.client")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_the_route_table_is_generated_from_the_router(self):
        self.assertEqual(block(self.text, "routes"), datasvc.route_reference(),
                         "regenerate with: python -m api.datasvc")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_every_route_of_the_router_is_in_the_doc(self):
        table = block(self.text, "routes")
        for route in datasvc.router.routes:
            if getattr(route, "include_in_schema", False):
                self.assertIn(f"`{route.path}`", table)

    def test_the_capability_table_names_every_capability_the_client_has(self):
        for capability in core.CAPABILITIES["ufc"]:
            self.assertIn(f"| `{capability}` |", self.text)

    def test_there_are_exactly_three_examples(self):
        self.assertEqual(set(examples(self.text)), {"ufc_matchup", "nfl_closing_line", "mlb_packet"})


class ExamplesRun(unittest.TestCase):
    """Each example is exec'd as written, with `client` bound to a client over synthetic stores."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.ufc = build_store(root / "ufc")
        cls.ufc.write_manifest()
        cls.nfl = W.build_world(root / "nfl")
        cls.nfl.write_manifest()
        (root / "mlb").mkdir()
        cls.world = World(root / "mlb")
        cls.code = examples(DOC.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_example(self, name, clock):
        client = DataClient(ufc=Path(self._tmp.name) / "ufc", nfl=Path(self._tmp.name) / "nfl",
                            mlb=self.world.service, clock=lambda: clock)
        namespace = {"client": client}
        exec(compile(self.code[name], f"CLIENT.md:{name}", "exec"), namespace)
        return namespace

    def test_ufc_matchup(self):
        ns = self.run_example("ufc_matchup", datetime(2026, 10, 3, 15, tzinfo=timezone.utc))
        self.assertTrue(ns["packet"]["available"])
        self.assertTrue(ns["version"].startswith("dv1-"))
        self.assertEqual(ns["odds_basis"], "reconstructed_later")
        self.assertIsInstance(ns["open_questions"], list)
        self.assertNotIn("reasons", ns)

    def test_ufc_matchup_with_an_unknown_name_takes_the_other_branch(self):
        code = self.code["ufc_matchup"].replace("Ben Brawler", "Zed Nobody")
        client = DataClient(ufc=Path(self._tmp.name) / "ufc", clock=lambda: datetime(2026, 10, 3, tzinfo=timezone.utc))
        ns = {"client": client}
        exec(compile(code, "CLIENT.md:ufc_matchup(unknown)", "exec"), ns)
        self.assertFalse(ns["packet"]["available"])
        self.assertTrue(ns["reasons"][0]["reason"])

    def test_nfl_closing_line(self):
        ns = self.run_example("nfl_closing_line", datetime(2025, 10, 20, 12, tzinfo=timezone.utc))
        self.assertEqual(ns["spread"], 3.0)
        self.assertTrue(ns["one_value"])

    def test_mlb_packet(self):
        ns = self.run_example("mlb_packet", F.NOW)
        self.assertEqual(ns["packet"]["packet_version"], "analyst_packet_v1")
        self.assertIn("moneyline", ns["markets"])
        self.assertEqual(ns["coverage"], {"through": None, "stale": True})   # no results store here: said, not fresh
        self.assertTrue(ns["version"].startswith("dv1-"))


if __name__ == "__main__":
    unittest.main()
