"""GET /card/{date}?sport=mma after the UFC pause cut-off (owner decision
2026-10-03): no picks, `paused: true`, the reason, and no live favourites card.

THE DEFECT THIS CLOSES
----------------------
The UFC branch of api/card.py served the FROZEN row when a date had one and
otherwise BUILT a card from the multibook store on the spot (`ufc_card.
card_for_date`, live branch) and handed it back as provisional picks. Stopping
the capture slot from publishing would have left every date with no row
showing the favourites rule as live picks. So after the cut-off the route
answers before any of that runs.

HOW "NO LIVE BUILD" IS PROVED
-----------------------------
Not by looking at what came back. Every way to build or read a live card is
replaced with a call that RAISES (the builder, the multibook read, the ledger
read, the cache) and the route is asked for a paused date: it answers anyway,
and the tripwires were never touched. The same tripwires are then shown to be
live on the other side of the line, so a pass cannot mean "nothing was wired".

FAIL CLOSED
-----------
The deployed image did not copy config/ when this was written. A missing,
malformed or nonsensical config must therefore still pause every date after
2026-10-03 (the built-in date), while 2026-10-03 and earlier are served as
before. Every kind of broken config is tried, and so is a different working
directory with a decoy config in it.

Route tests skip where FastAPI is absent. Every config here is a temp file
swapped in by patching the helper's path; the committed config is read only by
the tests that are about the committed config.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401 -- CI runs the suite without it; route tests skip
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import card_ledger, freshness
from src.appstate import ufc_public_card as upc
from src.pipeline import snapshots
from tests.test_activation_routes import _AppCase
from tests.test_ufc_public_card import THE_REASON

NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)

# What card_ledger.published_row hands back for a published card: the shape of
# a real evidence/cards_mma_v1.jsonl row (2026-10-03), trimmed to one bout.
FROZEN_ROW = {
    "kind": "card_published", "date": "2026-10-03", "rule": "UFC_CARD_V1",
    "published_utc": "2026-10-03T18:11:11.958006+00:00",
    "basis": "the basis", "disclaimer": "the disclaimer", "model_id": "ufc_consensus_v1",
    "picks": [{"game_id": "bout1", "rank": 1, "sport": "mma", "market": "moneyline",
               "side": "home", "home_team": "B. Fighter", "away_team": "A. Fighter",
               "bet": "B. Fighter to win at -143 (consensus)", "price": -143.0,
               "first_pitch_utc": "2026-10-03T23:40:00Z", "locked": False}],
}

PAUSED_DATES = ("2026-10-04", "2026-10-10", "2026-12-31", "2027-01-01", "2099-12-31")
PUBLIC_DATES = ("2026-10-03", "2026-10-02", "2026-09-26", "2025-01-01")


def _canon(payload) -> str:
    return json.dumps(payload, sort_keys=True)


class _FakeRequest:
    """Enough of a Request for _record_page_view: no user, so nothing is
    recorded, and this object is what the recorder is asked about."""

    class state:  # noqa: N801
        user_id = None


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _ApiCase(unittest.TestCase):
    def setUp(self):
        from api import card as card_api
        from src.report import ufc_card

        self.card_api = card_api
        self.ufc_card = ufc_card
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

        upc._WARNED.clear()
        quiet = logging.NullHandler()      # the fallback's warning is expected here
        logging.getLogger(upc.__name__).addHandler(quiet)
        self.addCleanup(logging.getLogger(upc.__name__).removeHandler, quiet)

        # a cache of this test's own, so nothing leaks between tests
        self.cache = freshness.SingleFlightTTLCache(ttl_s=60.0)
        self.patch(card_api, "_mma_card_cache", self.cache)
        card_api.reset_public_cache_for_tests()
        self.addCleanup(card_api.reset_public_cache_for_tests)

    # -- helpers -------------------------------------------------------------

    def patch(self, target, name, *args, **kwargs):
        patcher = mock.patch.object(target, name, *args, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def trip(self):
        """Every way of building or reading a live UFC card now RAISES. Returns
        the mocks so a test can show none of them was touched."""
        return {
            "builder": self.patch(self.ufc_card, "card_for_date",
                                  side_effect=AssertionError("the live UFC card builder ran")),
            "multibook": self.patch(snapshots, "read_multibook",
                                    side_effect=AssertionError("the multibook store was read")),
            "ledger": self.patch(card_ledger, "published_row",
                                 side_effect=AssertionError("the ledger was read")),
        }

    def use_config(self, content=None, *, name="ufc_public_card.json"):
        """Point the helper at a temp file (written when `content` is given, a
        path that does not exist when it is None)."""
        path = self.dir / name
        if content is not None:
            path.write_text(content, encoding="utf-8")
        self.patch(upc, "config_path", return_value=path)
        return path

    def ask(self, date_str, **kwargs):
        return self.card_api.get_card_for_date(date_str, request=None, sport="mma", **kwargs)

    def assert_paused(self, payload, date_str, last="2026-10-03"):
        self.assertIs(payload["paused"], True)
        self.assertEqual(payload["picks"], [])
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["reason"], THE_REASON)
        self.assertEqual(payload["date"], date_str)
        self.assertEqual(payload["sport"], "mma")
        self.assertEqual(payload["paused_after"], last)


class ThePausedAnswer(_ApiCase):
    def test_a_date_after_the_cut_off_is_paused_with_the_reason_and_no_picks(self):
        for date_str in PAUSED_DATES:
            with self.subTest(date_str):
                self.assert_paused(self.ask(date_str), date_str)

    def test_it_is_the_one_json_object_a_page_can_read(self):
        payload = self.ask("2026-10-10")
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertNotIn("rule", payload)
        self.assertNotIn("all_bets", payload)

    def test_no_live_build_is_attempted_after_the_cut_off(self):
        tripwires = self.trip()
        for date_str in PAUSED_DATES:
            with self.subTest(date_str):
                self.assert_paused(self.ask(date_str), date_str)
        for name, mocked in tripwires.items():
            with self.subTest(tripwire=name):
                mocked.assert_not_called()

    def test_the_tripwires_are_live_on_the_other_side_of_the_line(self):
        """A pass above must not mean nothing was wired: on the cut-off day the
        same tripwires fire."""
        self.trip()
        with self.assertRaises(AssertionError):
            self.ask("2026-10-03")

    def test_the_cache_is_never_touched_for_a_paused_date(self):
        cache = mock.Mock()
        cache.get.side_effect = AssertionError("the cache was used")
        self.patch(self.card_api, "_mma_card_cache", cache)
        self.assert_paused(self.ask("2026-10-10"), "2026-10-10")
        cache.get.assert_not_called()

    def test_get_card_today_applies_the_same_rule(self):
        class FakeDay(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 10)

        tripwires = self.trip()
        self.patch(self.card_api, "date_cls", FakeDay)
        payload = self.card_api.get_card_today(request=None, sport="mma")
        self.assert_paused(payload, "2026-10-10")
        tripwires["builder"].assert_not_called()

    def test_get_card_today_on_the_cut_off_day_is_not_paused(self):
        class FakeDay(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 3)

        builder = self.patch(self.ufc_card, "card_for_date", return_value={"sport": "mma", "picks": []})
        self.patch(self.card_api, "date_cls", FakeDay)
        self.assertEqual(self.card_api.get_card_today(request=None, sport="mma"),
                         {"sport": "mma", "picks": []})
        builder.assert_called_once()

    def test_the_pause_is_ufc_only(self):
        """Tennis and NFL answer a date after 2026-10-03 exactly as they did."""
        from src.report import nfl_card

        nfl = self.patch(nfl_card, "card_for_date", return_value={"sport": "nfl", "picks": []})
        self.patch(self.card_api, "_nfl_card_cache", freshness.SingleFlightTTLCache(ttl_s=60.0))
        got = self.card_api.get_card_for_date("2026-10-10", request=None, sport="nfl")
        self.assertEqual(got, {"sport": "nfl", "picks": []})
        nfl.assert_called_once()
        tennis = self.card_api.get_card_for_date("2026-10-10", request=None, sport="tennis")
        self.assertEqual(tennis["sport"], "tennis")
        self.assertNotIn("paused", tennis)

    def test_the_paused_answer_is_a_plain_page_view_not_a_value_action(self):
        """`surface` is what makes a request count toward a tester's
        activation and the per-feature numbers, and nothing was served."""
        recorder = self.patch(self.card_api, "_record_page_view")
        request = _FakeRequest()
        self.card_api.get_card_for_date("2026-10-10", request=request, sport="mma")
        recorder.assert_called_with(request, "card", "2026-10-10")
        self.assertEqual(recorder.call_args.kwargs, {})

    def test_a_published_day_still_records_a_value_action(self):
        recorder = self.patch(self.card_api, "_record_page_view")
        self.patch(self.ufc_card, "card_for_date", return_value={"sport": "mma", "picks": []})
        request = _FakeRequest()
        self.card_api.get_card_for_date("2026-10-03", request=request, sport="mma")
        recorder.assert_called_once_with(request, "card", "2026-10-03", surface="card", sport="mma")


class TheCutOffDayAndEarlierAreServedAsToday(_ApiCase):
    def test_a_published_card_is_served_byte_for_byte(self):
        self.patch(card_ledger, "published_row", return_value=FROZEN_ROW)
        expected = self.ufc_card.card_for_date("2026-10-03", now=NOW)
        for date_str in ("2026-10-03",):
            served = self.ask(date_str)
            self.assertEqual(_canon(served), _canon(expected))
        self.assertIs(served["frozen"], True)
        self.assertEqual(served["picks"], FROZEN_ROW["picks"])
        self.assertEqual((served["rule"], served["sport"], served["date"]),
                         ("UFC_CARD_V1", "mma", "2026-10-03"))
        self.assertNotIn("paused", served)
        self.assertNotIn("paused_after", served)

    def test_the_live_branch_is_still_there_on_and_before_the_cut_off(self):
        """A date with no published row is still built from the store: the
        pause moved the line, it did not remove the code below it."""
        self.patch(card_ledger, "published_row", return_value=None)
        store = self.patch(snapshots, "read_multibook", return_value=[])
        for date_str in ("2026-10-03", "2026-10-02"):
            with self.subTest(date_str):
                served = self.ask(date_str)
                self.assertIs(served["frozen"], False)
                self.assertEqual(served["reason"], "No UFC bouts captured for this date.")
                self.assertNotIn("paused", served)
        self.assertEqual(store.call_count, 2)

    def test_the_cache_still_fronts_the_live_branch(self):
        builder = self.patch(self.ufc_card, "card_for_date",
                             return_value={"sport": "mma", "picks": [], "marker": 1})
        first = self.ask("2026-10-03")
        second = self.ask("2026-10-03")
        self.assertEqual(first, second)
        self.assertEqual(builder.call_count, 1)

    def test_the_builder_gets_the_requested_date_and_a_utc_now(self):
        builder = self.patch(self.ufc_card, "card_for_date", return_value={"sport": "mma", "picks": []})
        self.ask("2026-10-02")
        builder.assert_called_once()
        self.assertEqual(builder.call_args.args, ("2026-10-02",))
        self.assertIsNotNone(builder.call_args.kwargs["now"].tzinfo)
        self.assertEqual(set(builder.call_args.kwargs), {"now"})


class AMissingOrBrokenConfigFailsClosed(_ApiCase):
    """The coordinator's requirement: do not let a missing config file silently
    re-enable live favourites in the API."""

    def broken_configs(self):
        sub = self.dir / "a_directory"
        sub.mkdir()
        return {
            "missing file": None,
            "not json": "this is { not json",
            "empty file": "",
            "a list": "[]",
            "key missing": json.dumps({"decided": "2026-10-03"}),
            "date is not a date": json.dumps({upc.CONFIG_KEY: "soon"}),
            "date is a number": json.dumps({upc.CONFIG_KEY: 20261017}),
            "unpadded date": json.dumps({upc.CONFIG_KEY: "2026-10-7"}),
        }, sub

    def test_every_kind_of_broken_config_still_pauses_a_later_date(self):
        configs, directory = self.broken_configs()
        for name, content in configs.items():
            with self.subTest(name):
                upc._WARNED.clear()
                self.use_config(content)
                with mock.patch.object(self.ufc_card, "card_for_date",
                                       side_effect=AssertionError("built")) as builder, \
                        mock.patch.object(snapshots, "read_multibook",
                                          side_effect=AssertionError("read")) as store:
                    for date_str in PAUSED_DATES:
                        self.assert_paused(self.ask(date_str), date_str)
                builder.assert_not_called()
                store.assert_not_called()

    def test_a_config_path_that_is_a_directory_still_pauses_a_later_date(self):
        _configs, directory = self.broken_configs()
        self.patch(upc, "config_path", return_value=directory)
        self.assert_paused(self.ask("2026-10-10"), "2026-10-10")

    def test_a_broken_config_still_serves_the_cut_off_day_and_earlier(self):
        """The fallback is the owner's date, not "everything paused": tonight's
        card, already published, is still served."""
        configs, _directory = self.broken_configs()
        self.patch(card_ledger, "published_row", return_value=FROZEN_ROW)
        for name, content in configs.items():
            with self.subTest(name):
                self.use_config(content)
                # a cache of its own each time, so the date check is what is
                # being exercised and not a hit left by the previous config
                self.patch(self.card_api, "_mma_card_cache",
                           freshness.SingleFlightTTLCache(ttl_s=60.0))
                for date_str in PUBLIC_DATES:
                    served = self.ask(date_str)
                    self.assertNotIn("paused", served, date_str)
                    self.assertIs(served["frozen"], True, date_str)
                    self.assertEqual(served["picks"], FROZEN_ROW["picks"], date_str)

    def test_a_missing_config_is_logged_so_the_gap_is_visible(self):
        upc._WARNED.clear()
        self.use_config(None, name="not_there.json")
        with self.assertLogs(upc.__name__, level="WARNING") as logged:
            self.ask("2026-10-10")
        self.assertIn("not_there.json", logged.output[0])

    def test_the_path_is_the_repository_root_not_the_working_directory(self):
        """A working directory with a decoy config that says 2099 must not move
        the line: the committed config, found from the repository root, does."""
        decoy = self.dir / "elsewhere"
        (decoy / "config").mkdir(parents=True)
        (decoy / "config" / "ufc_public_card.json").write_text(
            json.dumps({upc.CONFIG_KEY: "2099-12-31"}), encoding="utf-8")
        here = os.getcwd()
        os.chdir(decoy)
        self.addCleanup(os.chdir, here)
        self.assert_paused(self.ask("2026-10-10"), "2026-10-10")


class AGoodConfigMovesTheLine(_ApiCase):
    def test_a_later_date_in_the_config_serves_up_to_it(self):
        self.use_config(json.dumps({upc.CONFIG_KEY: "2026-10-10"}))
        builder = self.patch(self.ufc_card, "card_for_date", return_value={"sport": "mma", "picks": []})
        self.assertEqual(self.ask("2026-10-10"), {"sport": "mma", "picks": []})
        builder.assert_called_once()
        self.assert_paused(self.ask("2026-10-11"), "2026-10-11", last="2026-10-10")
        self.assertEqual(builder.call_count, 1)

    def test_the_committed_config_is_what_a_good_deploy_reads(self):
        self.assert_paused(self.ask("2026-10-04"), "2026-10-04")
        self.assertEqual(upc.configured_last_public_date(), "2026-10-03")


class TheRecordIsUnchanged(_ApiCase):
    """The record routes do not read the pause: the UFC record keeps showing
    with the pause in force, and is identical with it switched off."""

    def record_and_history(self, config_content):
        self.card_api.reset_public_cache_for_tests()
        with mock.patch.object(upc, "config_path",
                               return_value=self.dir / "record_config.json"):
            (self.dir / "record_config.json").write_text(config_content, encoding="utf-8")
            record = self.card_api.get_card_record(sport="mma")
            history = self.card_api.get_card_history(sport="mma")
        return record, history

    def test_the_ufc_record_is_the_ledgers_record_and_carries_no_pause(self):
        record, _history = self.record_and_history(json.dumps({upc.CONFIG_KEY: "2026-10-03"}))
        ledger = card_ledger.record(sport="mma")
        for key in ("wins", "losses", "pushes", "n_staked", "days"):
            with self.subTest(key):
                self.assertEqual(record[key], ledger[key])
        self.assertEqual(record["rule"], "UFC_CARD_V1")
        self.assertEqual(record["sport"], "mma")
        self.assertIs(record["chain_ok"], True)
        self.assertGreaterEqual(record["n_staked"], 6, "the record the pause leaves in place")
        self.assertNotIn("paused", record)

    def test_the_record_and_the_history_are_identical_with_the_pause_off(self):
        paused_record, paused_history = self.record_and_history(
            json.dumps({upc.CONFIG_KEY: "2026-10-03"}))
        open_record, open_history = self.record_and_history(
            json.dumps({upc.CONFIG_KEY: "2099-12-31"}))
        self.assertEqual(_canon(paused_record), _canon(open_record))
        self.assertEqual(_canon(paused_history), _canon(open_history))

    def test_the_history_still_lists_the_settled_ufc_days(self):
        _record, history = self.record_and_history(json.dumps({upc.CONFIG_KEY: "2026-10-03"}))
        self.assertEqual(history["sport"], "mma")
        self.assertEqual(history["rule"], "UFC_CARD_V1")
        self.assertGreaterEqual(len(history["days"]), 2)
        self.assertNotIn("paused", history)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ThePausedAnswerThroughTheRealApp(_AppCase):
    """The real ASGI app (the activation tests' harness: a temp database, a real
    token, content builders stubbed, caches fresh): the paid gate, the plain page
    view and the unchanged cut-off day, end to end."""

    PAUSED = "2026-10-10"
    CUT_OFF = "2026-10-03"

    def test_a_paused_date_is_a_200_with_the_reason_and_no_picks(self):
        token = self.grant().token
        status, body = self.get("/card/" + self.PAUSED, token, query="sport=mma")
        self.assertEqual(status, 200)
        self.assertIs(body["paused"], True)
        self.assertEqual(body["picks"], [])
        self.assertEqual(body["reason"], THE_REASON)
        self.assertEqual(body["date"], self.PAUSED)

    def test_it_records_one_plain_page_view_and_no_value_action(self):
        token = self.grant().token
        self.get("/card/" + self.PAUSED, token, query="sport=mma")
        views = self.page_views()
        self.assertEqual(len(views), 1)
        self.assertEqual(dict(views[0].properties), {"route": "card", "date": self.PAUSED})
        self.assertEqual(self.value_actions(), [])

    def test_the_cut_off_day_is_served_and_still_counts_as_a_ufc_value_action(self):
        token = self.grant().token
        status, body = self.get("/card/" + self.CUT_OFF, token, query="sport=mma")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"sport": "mma", "picks": []})
        actions = self.value_actions()
        self.assertEqual(len(actions), 1)
        self.assertEqual(dict(actions[0].properties),
                         {"route": "card", "date": self.CUT_OFF, "feature": "ufc",
                          "surface": "card", "sport": "mma"})

    def test_the_paid_gate_is_still_on_a_paused_date(self):
        self.assertEqual(self.get("/card/" + self.PAUSED, None, query="sport=mma")[0], 401)
        self.assertEqual(
            self.get("/card/" + self.PAUSED, "tok_not_real", query="sport=mma")[0], 401)
        self.assertEqual(self.page_views(), [])

    def test_the_public_record_is_still_open_without_a_token(self):
        for path in ("/card/record", "/card/history"):
            with self.subTest(path):
                status, body = self.get(path, None, query="sport=mma")
                self.assertEqual(status, 200)
                self.assertNotIn("paused", body)
        _status, record = self.get("/card/record", None, query="sport=mma")
        self.assertEqual(record["rule"], "UFC_CARD_V1")
        self.assertGreaterEqual(record["n_staked"], 6)


if __name__ == "__main__":
    unittest.main()
