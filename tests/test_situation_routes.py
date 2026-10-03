"""The routes that serve the Situation block: GET /game/{date}/{away}/{home} and the UFC fight-night bout.

Both are display only and fail soft. The provider of the MLB record is injected (no store is read);
the UFC route is driven with the data layer's synthetic world. Skipped without FastAPI, like every
route test.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analysis import matchup_read, ufc_read
from tests import analyst_fixtures as AF
from tests import situation_fixtures as SF
from tests import ufc_analyst_fixtures as UF

if HAS_FASTAPI:
    from api import games as games_mod
    from api import ufc_fights
    from src.analyst import source
    from src.appstate import freshness
    from src.providers import mlb

DATE = "2025-10-04"


def schedule():
    return [{"game_pk": 401, "date": DATE, "away_team": "TB", "home_team": "NYY", "game_type": "D",
             "venue": "Yankee Stadium", "start_time_utc": f"{DATE}T23:05:00Z",
             "away_probable": "Drew Rasmussen", "home_probable": "Gerrit Cole"}]


class _Empty:
    games, season_records = [], {}


def provider_for(rows=None):
    """A provider like `source.mlb_situation_provider` that reads no store."""
    # the world's newest game before 2025-10-04 is 2025-10-02; the manifest confirms the day between
    return source.mlb_situation_provider(results=rows or SF.world(), covered_dates=["2025-10-03"],
                                         history_loader=lambda: _Empty())


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheGameRoute(unittest.TestCase):
    def setUp(self):
        self._entries, self._situation = games_mod._entries_cache, games_mod._situation_cache
        games_mod._entries_cache = freshness.SingleFlightTTLCache(
            ttl_s=games_mod.ENTRIES_CACHE_TTL_S, stale_while_revalidate_s=games_mod.ENTRIES_STALE_WINDOW_S)
        games_mod._situation_cache = freshness.SingleFlightTTLCache(ttl_s=games_mod.ENTRIES_CACHE_TTL_S)
        self.addCleanup(self.restore)

    def restore(self):
        games_mod._entries_cache, games_mod._situation_cache = self._entries, self._situation

    def get(self, provider):
        with patch.object(mlb, "fetch_games", return_value=schedule()), \
                patch.object(source, "mlb_situation_provider", return_value=provider):
            return games_mod.get_game(DATE, "TB", "NYY")

    def test_the_payload_carries_the_record_and_the_read_carries_the_block(self):
        payload = self.get(provider_for())
        blob = json.loads(json.dumps(payload))
        self.assertEqual(blob["situation"]["sport"], "mlb")
        self.assertEqual(blob["situation"]["as_of"], DATE)
        block = blob["read"]["situation"]
        self.assertGreaterEqual(len(block["lines"]), 3)
        for line in block["lines"]:
            found, value = matchup_read.resolve_path(blob, line["evidence"]["path"])
            self.assertTrue(found, line["evidence"])
            self.assertEqual(value, line["evidence"]["value"])

    def test_the_block_says_what_the_record_says(self):
        payload = self.get(provider_for())
        sentences = [ln["sentence"] for ln in payload["read"]["situation"]["lines"]]
        self.assertEqual(sentences[0], "Game 1 of the Division Series (best of 5).")

    def test_a_provider_that_fails_costs_the_block_never_the_page_or_the_read(self):
        def broken(_item):
            raise RuntimeError("no results store")
        payload = self.get(broken)
        self.assertIsNone(payload["situation"])
        self.assertIsNotNone(payload["read"])
        self.assertNotIn("situation", payload["read"])
        self.assertIn("quick", payload)

    def test_the_record_is_cached_per_game(self):
        calls = []
        inner = provider_for()

        def counting(item):
            calls.append(1)
            return inner(item)
        with patch.object(mlb, "fetch_games", return_value=schedule()), \
                patch.object(source, "mlb_situation_provider", return_value=counting):
            games_mod.get_game(DATE, "TB", "NYY")
            games_mod.get_game(DATE, "TB", "NYY")
        self.assertEqual(len(calls), 1)

    def test_the_situation_is_not_a_dossier_section_so_arm_a_cannot_see_it(self):
        """A dossier section feeds the card's model and the analyst's frozen packet, so the situation
        rides beside the dossier, never inside it."""
        from src.analyst import packet as packet_mod
        payload = self.get(provider_for())
        self.assertNotIn("situation", payload["advanced"]["sections"])
        self.assertNotIn("situation", payload["advanced"].get("gaps", {}))
        kw = dict(multibook_rows=AF.multibook_rows(), cfg=AF.CFG)
        with_situation = packet_mod.build_packet(payload, built_at=AF.BUILT_AT, **kw)
        without = dict(payload)
        without.pop("situation")
        without["read"] = {k: v for k, v in payload["read"].items() if k != "situation"}
        no_situation = packet_mod.build_packet(without, built_at=AF.BUILT_AT, **kw)
        self.assertNotIn("situation", with_situation["sections"])
        self.assertEqual(packet_mod.packet_hash(with_situation), packet_mod.packet_hash(no_situation))

    def test_the_provider_is_given_the_games_own_fields(self):
        seen = []
        inner = provider_for()

        def spy(item):
            seen.append(item["payload"]["advanced"]["game"])
            return inner(item)
        self.get(spy)
        self.assertEqual((seen[0]["away_team"], seen[0]["home_team"], seen[0]["game_type"]), ("TB", "NYY", "D"))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheUfcRoute(unittest.TestCase):
    NOW = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = UF.make_store(Path(self._tmp.name))
        self.bout = self.store.bout_by_id()["9101"]

    def test_the_bout_carries_the_record_and_its_read_the_block(self):
        out = ufc_fights._bout_payload(self.store, self.bout, self.NOW)
        self.assertEqual(out["situation"]["sport"], "ufc")
        block = out["read"]["situation"]
        self.assertEqual(block["lines"][0]["sentence"], "The main event, main card, scheduled for 5 rounds.")
        for line in block["lines"]:
            found, value = ufc_read.resolve_path(out, line["evidence"]["path"])
            self.assertTrue(found, line["evidence"])
            self.assertEqual(value, line["evidence"]["value"])

    def test_the_record_reuses_the_sheets_features_and_matches_one_built_without_it(self):
        from src.situation import ufc as situation_ufc
        out = ufc_fights._bout_payload(self.store, self.bout, self.NOW)
        self.assertEqual(json.loads(json.dumps(out["situation"])),
                         json.loads(json.dumps(situation_ufc.situation_for_bout(self.store, "9101"))))

    def test_a_situation_that_cannot_be_built_costs_the_block_not_the_read(self):
        with patch.object(ufc_fights.situation_ufc, "situation_for_bout", side_effect=ValueError("boom")):
            out = ufc_fights._bout_payload(self.store, self.bout, self.NOW)
        self.assertIsNone(out["situation"])
        self.assertIsNotNone(out["read"])
        self.assertNotIn("situation", out["read"])
        self.assertIsNone(out["unavailable"])

    def test_a_dataset_that_cannot_be_read_is_still_the_whole_cards_problem(self):
        from api import datasvc
        with patch.object(ufc_fights.situation_ufc, "situation_for_bout",
                          side_effect=datasvc.DataUnavailable("bouts")):
            with self.assertRaises(datasvc.DataUnavailable):
                ufc_fights._bout_payload(self.store, self.bout, self.NOW)

    def test_a_cancelled_bout_has_no_situation_either(self):
        bout = dict(self.bout, status="canceled")
        out = ufc_fights._bout_payload(self.store, bout, self.NOW)
        self.assertNotIn("situation", out)
        self.assertIsNotNone(out["unavailable"])


if __name__ == "__main__":
    unittest.main()
