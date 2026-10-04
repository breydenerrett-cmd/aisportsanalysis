"""The pilot's `prepare` can take its packet from the data service (`DataClient`), and it is the same packet.

The consumer that makes the data service more than routes: the supervised-session pilot builds the
analyst's frozen packet, and with `client=` it asks the data service for it instead of running the
analyst's loader itself. Everything after the packet (the request, the hash, the checker, the ledger) is
unchanged, so the one thing that must be true is that the packet is identical. Offline: the loader and
the schedule are injected, nothing reads the repo's stores.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.analyst import pilot
from src.analyst import packet as packet_mod
from src.datasvc.client import DataClient
from src.datasvc.mlb import service as svc
from tests import analyst_fixtures as F
from tests import test_analyst_pilot as P
from tests.test_datasvc_mlb_service import schedule_game


def service(items=None, games=None, fetch_error=None):
    """An MlbService whose loader returns the SAME items the pilot's loader returns."""
    held = list(items) if items is not None else [P.item()]

    def fetch(date):
        if fetch_error:
            raise RuntimeError(fetch_error)
        return [dict(g) for g in (games if games is not None else [schedule_game()])]

    return svc.MlbService(fetch_games=fetch, loader=lambda date, games, now: list(held), stores=(),
                          clock=lambda: F.NOW, config_loader=lambda: dict(F.CFG))


class PrepareFromTheDataService(P.Env):
    def prepare_via_client(self, svc_, *, scratch=None, game="NYY@TB", **extra):
        return pilot.prepare(F.DATE, game, scratch=scratch, cfg=F.CFG, root=self.root,
                             client=DataClient(mlb=svc_, clock=lambda: F.NOW), now=lambda: self.now,
                             out=self.out.append, **extra)

    def read(self, name, root=None):
        folder = pilot.game_folder(F.DATE, "NYY", "TB", root or self.root)
        return json.loads((folder / name).read_text(encoding="utf-8"))

    def test_the_packet_hash_is_identical_to_the_loader_path(self):
        self.assertEqual(self.prepare(), pilot.EXIT_OK)
        via_loader = {name: self.read(name) for name in pilot.FILES}
        loader_text = (pilot.game_folder(F.DATE, "NYY", "TB", self.root) / "packet.json").read_text(encoding="utf-8")

        other = Path(self._tmp.name) / "client_root"
        other.mkdir()
        self.assertEqual(pilot.prepare(F.DATE, "NYY@TB", cfg=F.CFG, root=other, client=DataClient(
            mlb=service(), clock=lambda: F.NOW), now=lambda: self.now, out=self.out.append), pilot.EXIT_OK)
        via_client = {name: self.read(name, other) for name in pilot.FILES}
        client_text = (pilot.game_folder(F.DATE, "NYY", "TB", other) / "packet.json").read_text(encoding="utf-8")

        self.assertEqual(via_client["prepare.json"]["packet_hash"], via_loader["prepare.json"]["packet_hash"])
        self.assertEqual(packet_mod.packet_hash(via_client["packet.json"]),
                         packet_mod.packet_hash(via_loader["packet.json"]))
        self.assertEqual(client_text, loader_text)                           # the very same bytes on disk
        self.assertEqual(via_client["request.json"], via_loader["request.json"])   # so the model sees the same request

    def test_prepare_json_adds_only_the_source_and_the_data_version(self):
        self.prepare()
        plain = self.read("prepare.json")
        other = Path(self._tmp.name) / "client_root"
        other.mkdir()
        pilot.prepare(F.DATE, "NYY@TB", cfg=F.CFG, root=other, client=DataClient(mlb=service(), clock=lambda: F.NOW),
                      now=lambda: self.now, out=self.out.append)
        served = self.read("prepare.json", other)
        self.assertEqual(served.pop("packet_source"), "data_client")
        self.assertTrue(served.pop("data_version").startswith("dv1-"))
        self.assertEqual(served, plain)
        self.assertNotIn("packet_source", plain)                             # the default path is unchanged

    def test_a_folder_prepared_from_the_data_service_loads_like_any_other(self):
        self.assertEqual(self.prepare_via_client(service()), pilot.EXIT_OK)
        prepared = pilot.load_prepared(str(pilot.game_folder(F.DATE, "NYY", "TB", self.root)))
        self.assertEqual(prepared.meta["packet_source"], "data_client")
        self.assertEqual(packet_mod.packet_hash(prepared.packet), prepared.meta["packet_hash"])

    def test_the_refusals_use_the_loader_paths_words(self):
        self.assertEqual(self.prepare_via_client(service(), game="BOS@BAL"), pilot.EXIT_ERROR)
        self.assertIn(f"no games found for {F.DATE} matching BOS@BAL", self.text)
        self.out.clear()
        two = service(items=[P.item(), P.item()], games=[schedule_game(pk=1), schedule_game(pk=2)])
        self.assertEqual(self.prepare_via_client(two), pilot.EXIT_ERROR)
        self.assertIn("the pilot handles one game at a time", self.text)

    def test_an_unreachable_schedule_is_a_refusal_with_the_reason_and_writes_nothing(self):
        self.assertEqual(self.prepare_via_client(service(fetch_error="provider down")), pilot.EXIT_ERROR)
        self.assertIn("provider down", self.text)
        self.assertFalse(pilot.game_folder(F.DATE, "NYY", "TB", self.root).exists())

    def test_the_game_must_still_be_publishable_before_a_session_is_spent(self):
        started = P.item(payload=F.payload("final", with_scores=True))
        self.assertEqual(self.prepare_via_client(service(items=[started], games=[schedule_game(state="final")])),
                         pilot.EXIT_ERROR)
        self.assertIn("SKIP", self.text)

    def test_a_loader_and_a_client_together_are_refused(self):
        self.assertEqual(pilot.prepare(F.DATE, "NYY@TB", cfg=F.CFG, root=self.root, loader=lambda d: [P.item()],
                                       client=DataClient(mlb=service()), now=lambda: self.now, out=self.out.append),
                         pilot.EXIT_ERROR)
        self.assertIn("not both", self.text)

    def test_the_scratch_rehearsal_works_from_the_data_service_too(self):
        scratch = str(Path(self._tmp.name) / "rehearsal")
        self.assertEqual(self.prepare_via_client(service(), scratch=scratch), pilot.EXIT_OK)
        self.assertTrue(json.loads(Path(scratch, "prepare.json").read_text(encoding="utf-8"))["rehearsal"])


if __name__ == "__main__":
    unittest.main()
