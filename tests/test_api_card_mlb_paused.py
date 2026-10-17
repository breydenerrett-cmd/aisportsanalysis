"""GET /card/{date} for MLB after the value-picks pause cut-off (owner decision
2026-10-16): no picks, `paused: true`, the reason, the links a reader should
use instead, and no live build.

HOW "NO LIVE BUILD" IS PROVED
-----------------------------
Not by looking at what came back. Every way to read or build an MLB card (the
ledger read, the entry builder, the opportunities builder, the V1 and V2
builders, the caches) is replaced with a call that RAISES, and the route is
asked for a paused date: it answers anyway and none of them was touched. The
same tripwires are then shown to be live on the other side of the line (the
cut-off day), so a pass cannot mean nothing was wired.

The record routes (`/card/record`, `/card/history`) do not read the pause.

Route tests skip where FastAPI is absent. Every config here is a temp file
swapped in by patching the helper's path.
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401 -- CI runs the suite without it; route tests skip
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import freshness
from src.appstate import mlb_public_card as mpc

PAUSED_DATES = ("2026-10-17", "2026-10-23", "2026-12-31", "2027-01-01", "2099-12-31")
PUBLIC_DATES = ("2026-10-16", "2026-10-15", "2026-09-22", "2025-01-01")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _ApiCase(unittest.TestCase):
    def setUp(self):
        from api import card as card_api
        from src.report import card as card_mod
        from src.report import card_v2

        self.card_api = card_api
        self.card_mod = card_mod
        self.card_v2 = card_v2
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        mpc._WARNED.clear()
        quiet = logging.NullHandler()
        logging.getLogger(mpc.__name__).addHandler(quiet)
        self.addCleanup(logging.getLogger(mpc.__name__).removeHandler, quiet)
        card_api.reset_public_cache_for_tests()
        self.addCleanup(card_api.reset_public_cache_for_tests)

    def patch(self, target, name, *args, **kwargs):
        patcher = mock.patch.object(target, name, *args, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def trip(self):
        """Every way of reading or building an MLB card now RAISES."""
        def boom(what):
            return {"side_effect": AssertionError(f"{what} ran")}
        return {
            "frozen": self.patch(self.card_mod, "frozen_card", **boom("the v1 ledger read")),
            "frozen_v2": self.patch(self.card_v2, "frozen_card_v2", **boom("the v2 ledger read")),
            "entries": self.patch(self.card_api, "_build_entries", **boom("the entry builder")),
            "live_cache": self.patch(self.card_api, "_mlb_live_card_cache",
                                     mock.Mock(get=mock.Mock(side_effect=AssertionError("cache")))),
            "v1": self.patch(self.card_mod, "card_for_date", **boom("the v1 builder")),
            "v2": self.patch(self.card_v2, "card_v2_for_date", **boom("the v2 builder")),
        }

    def use_config(self, content=None, name="mlb_public_card.json"):
        path = self.dir / name
        if content is not None:
            path.write_text(content, encoding="utf-8")
        self.patch(mpc, "config_path", return_value=path)
        return path

    def ask(self, date_str, **kwargs):
        return self.card_api.get_card_for_date(date_str, request=None, sport="mlb", **kwargs)

    def assert_paused(self, payload, date_str, last="2026-10-16"):
        self.assertIs(payload["paused"], True)
        self.assertEqual(payload["picks"], [])
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["reason"], mpc.PAUSED_REASON)
        self.assertEqual(payload["date"], date_str)
        self.assertEqual(payload["sport"], "mlb")
        self.assertEqual(payload["paused_after"], last)
        self.assertEqual([l["href"] for l in payload["links"]],
                         ["#/record-card", "sample.html", "#/odds"])


class ThePausedAnswer(_ApiCase):
    def test_a_date_after_the_cut_off_is_paused_with_the_reason_and_the_links(self):
        for date_str in PAUSED_DATES:
            with self.subTest(date_str):
                self.assert_paused(self.ask(date_str), date_str)

    def test_every_rule_value_is_paused(self):
        for rule in (None, "v1", "v2"):
            with self.subTest(rule=rule):
                self.assert_paused(self.ask("2026-10-17", rule=rule), "2026-10-17")

    def test_an_invalid_rule_is_still_a_400_not_a_paused_answer(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self.ask("2026-10-17", rule="v9")
        self.assertEqual(caught.exception.status_code, 400)

    def test_no_card_is_read_or_built_after_the_cut_off(self):
        tripwires = self.trip()
        for date_str in PAUSED_DATES:
            with self.subTest(date_str):
                self.assert_paused(self.ask(date_str), date_str)
                self.assert_paused(self.ask(date_str, rule="v2"), date_str)
        for name, mocked in tripwires.items():
            with self.subTest(tripwire=name):
                if hasattr(mocked, "get"):
                    mocked.get.assert_not_called()
                else:
                    mocked.assert_not_called()

    def test_the_tripwires_are_live_on_the_other_side_of_the_line(self):
        self.trip()
        with self.assertRaises(AssertionError):
            self.ask("2026-10-16")
        with self.assertRaises(AssertionError):
            self.ask("2026-10-16", rule="v2")

    def test_get_card_today_applies_the_same_rule(self):
        class FakeDay(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 17)

        self.trip()
        self.patch(self.card_api, "date_cls", FakeDay)
        self.assert_paused(self.card_api.get_card_today(request=None, sport="mlb"), "2026-10-17")

    def test_the_cut_off_day_is_not_paused_today(self):
        class FakeDay(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 16)

        # the active rule is v2, so today's card is read through its ledger
        frozen = {"sport": "mlb", "picks": [{"rank": 1}], "frozen_at": None}
        self.patch(self.card_v2, "frozen_card_v2", return_value=dict(frozen))
        self.patch(self.card_api, "date_cls", FakeDay)
        served = self.card_api.get_card_today(request=None, sport="mlb")
        self.assertNotIn("paused", served)
        self.assertEqual(served["picks"], [{"rank": 1}])

    def test_the_paused_answer_is_recorded_as_a_card_view(self):
        # The page still serves product content (the reason, the record and brief links), and the
        # activation contract (tests/test_activation_routes.py) counts every labelled route once.
        recorder = self.patch(self.card_api, "_record_page_view")
        request = object()
        self.card_api.get_card_for_date("2026-10-17", request=request, sport="mlb")
        recorder.assert_called_with(request, "card", "2026-10-17", surface="card")

    def test_the_payload_is_json_and_carries_no_rule_or_prices(self):
        payload = self.ask("2026-10-17")
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        for key in ("rule", "all_bets", "prop_picks", "prices_as_of", "published_utc"):
            self.assertNotIn(key, payload)

    def test_other_sports_are_not_paused_by_this(self):
        tennis = self.card_api.get_card_for_date("2026-10-17", request=None, sport="tennis")
        self.assertEqual(tennis["sport"], "tennis")
        self.assertNotIn("paused", tennis)


class OnAndBeforeTheCutOffNothingMoves(_ApiCase):
    def test_a_frozen_card_is_served_as_before(self):
        row = {"sport": "mlb", "rule": "DAILY_CARD_BEST_BETS_V2", "picks": [{"rank": 1}],
               "frozen_at": "2026-10-16T15:00:00+00:00"}
        frozen = self.patch(self.card_mod, "frozen_card", return_value=dict(row))
        for date_str in PUBLIC_DATES:
            with self.subTest(date_str):
                served = self.ask(date_str, rule="v1")
                self.assertNotIn("paused", served)
                self.assertNotIn("paused_after", served)
                self.assertEqual(served["picks"], [{"rank": 1}])
                self.assertEqual(served["date"], date_str)
        self.assertEqual(frozen.call_count, len(PUBLIC_DATES))

    def test_the_v2_preview_path_is_still_there_on_the_cut_off_day(self):
        row = {"sport": "mlb", "rule": "DAILY_CARD_BEST_BETS_V2", "picks": []}
        self.patch(self.card_v2, "frozen_card_v2", return_value=dict(row))
        served = self.ask("2026-10-16", rule="v2")
        self.assertNotIn("paused", served)
        self.assertEqual(served["rule"], "DAILY_CARD_BEST_BETS_V2")


class AMissingOrBrokenConfigFailsClosed(_ApiCase):
    CONFIGS = {
        "missing file": None,
        "not json": "this is { not json",
        "empty file": "",
        "a list": "[]",
        "key missing": json.dumps({"decided": "2026-10-16"}),
        "date is not a date": json.dumps({mpc.CONFIG_KEY: "soon"}),
        "date is a number": json.dumps({mpc.CONFIG_KEY: 20261030}),
    }

    def test_every_kind_of_broken_config_still_pauses_a_later_date(self):
        for name, content in self.CONFIGS.items():
            with self.subTest(name):
                mpc._WARNED.clear()
                self.use_config(content)
                tripwires = self.trip()
                for date_str in PAUSED_DATES:
                    self.assert_paused(self.ask(date_str), date_str)
                tripwires["v1"].assert_not_called()

    def test_a_broken_config_still_serves_the_cut_off_day_and_earlier(self):
        self.patch(self.card_mod, "frozen_card",
                   return_value={"sport": "mlb", "picks": [{"rank": 1}], "frozen_at": None})
        for name, content in self.CONFIGS.items():
            with self.subTest(name):
                self.use_config(content)
                for date_str in PUBLIC_DATES:
                    self.assertNotIn("paused", self.ask(date_str, rule="v1"), date_str)

    def test_a_missing_config_is_logged_so_the_gap_is_visible(self):
        mpc._WARNED.clear()
        self.use_config(None, name="not_there.json")
        with self.assertLogs(mpc.__name__, level="WARNING") as logged:
            self.ask("2026-10-17")
        self.assertIn("not_there.json", logged.output[0])


class AGoodConfigMovesTheLine(_ApiCase):
    def test_a_later_date_in_the_config_serves_up_to_it(self):
        self.use_config(json.dumps({mpc.CONFIG_KEY: "2026-10-20"}))
        self.patch(self.card_mod, "frozen_card",
                   return_value={"sport": "mlb", "picks": [], "frozen_at": None})
        self.assertNotIn("paused", self.ask("2026-10-20", rule="v1"))
        self.assert_paused(self.ask("2026-10-21"), "2026-10-21", last="2026-10-20")

    def test_the_committed_config_is_what_a_good_deploy_reads(self):
        self.assert_paused(self.ask("2026-10-17"), "2026-10-17")
        self.assertEqual(mpc.configured_last_public_date(), "2026-10-16")


class TheRecordRoutesDoNotReadThePause(_ApiCase):
    def test_the_record_is_identical_with_the_pause_on_and_off(self):
        def record_with(content):
            self.card_api.reset_public_cache_for_tests()
            path = self.dir / "record_config.json"
            path.write_text(content, encoding="utf-8")
            with mock.patch.object(mpc, "config_path", return_value=path):
                return (self.card_api.get_card_record(sport="mlb"),
                        self.card_api.get_card_history(sport="mlb"))

        paused_record, paused_history = record_with(json.dumps({mpc.CONFIG_KEY: "2026-10-16"}))
        open_record, open_history = record_with(json.dumps({mpc.CONFIG_KEY: "2099-12-31"}))
        self.assertEqual(json.dumps(paused_record, sort_keys=True, default=str),
                         json.dumps(open_record, sort_keys=True, default=str))
        self.assertEqual(json.dumps(paused_history, sort_keys=True, default=str),
                         json.dumps(open_history, sort_keys=True, default=str))
        self.assertNotIn("paused", paused_record)
        self.assertNotIn("paused", paused_history)


class TheCacheIsNeverFilledForAPausedDate(_ApiCase):
    def test_a_paused_date_leaves_no_entry_for_a_later_reader(self):
        cache = freshness.SingleFlightTTLCache(ttl_s=60.0)
        self.patch(self.card_api, "_mlb_live_card_cache", cache)
        self.assert_paused(self.ask("2026-10-17"), "2026-10-17")
        built = self.patch(self.card_api, "_build_entries", return_value=([], [], {}))
        self.patch(self.card_mod, "frozen_card", return_value=None)
        self.use_config(json.dumps({mpc.CONFIG_KEY: "2026-10-17"}))
        self.patch(self.card_mod, "card_for_date", return_value={"sport": "mlb", "picks": []})
        self.patch(self.card_api.opportunities_mod, "build_opportunities", return_value={"rows": []})
        served = self.ask("2026-10-17", rule="v1")
        self.assertNotIn("paused", served)
        built.assert_called_once()


if __name__ == "__main__":
    unittest.main()
