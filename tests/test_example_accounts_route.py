"""GET /card/accounts: public, reconciled, cheap, and never wrong.

Runs against temporary ledgers rebuilt from the real rows (tests/fixtures/
example_accounts); nothing here reads evidence/ or any live data file. Needs
FastAPI, so it is skipped on a runner without it (the arithmetic and the
reconciliation have their own FastAPI-free files).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from src.appstate import card_ledger
from src.appstate import example_accounts as ea
from tests._example_accounts_fixtures import (
    PUBLISHED, fixture_ledgers, mlb_v2_payloads, ufc_text_with)

try:
    from api.app import app
    from api import card as card_api
    from api import meta as meta_api
    HAS_FASTAPI = True
except Exception:  # noqa: BLE001 -- fastapi lives only in api/'s deps
    HAS_FASTAPI = False


def asgi_get(path, headers=None):
    path, _, query = path.partition("?")
    captured = {"body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
             "root_path": "", "headers": [(b"host", b"test")] + list(headers or []),
             "client": ("test", 1), "server": ("test", 80)}
    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    try:
        body = json.loads(captured["body"])
    except ValueError:
        body = None
    return captured.get("status"), body


class RouteCase(unittest.TestCase):
    ledger_kwargs: dict = {}

    def setUp(self):
        from src.report import effective_record
        ctx = fixture_ledgers(**self.ledger_kwargs)
        self.paths = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        # /meta's own per-ledger-state memo, which the accounts route reads
        # pending counts from. Every page load fills it, so it is hot when the
        # record page asks for the accounts; built here once, from the fixture
        # ledgers, so the "no ledger re-read" tests measure the accounts route.
        parts = {"effective_record": effective_record.build()}
        patch = mock.patch.object(meta_api, "_record_parts", lambda: parts)
        patch.start()
        self.addCleanup(patch.stop)
        card_api.reset_public_cache_for_tests()
        self.addCleanup(card_api.reset_public_cache_for_tests)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ThePublicRoute(RouteCase):
    def test_no_token_is_needed_and_it_is_not_captured_by_the_date_route(self):
        status, body = asgi_get("/card/accounts")
        self.assertEqual(status, 200)
        self.assertIs(body["available"], True)

    def test_a_stale_token_in_the_browser_is_ignored_not_a_401(self):
        status, body = asgi_get("/card/accounts", headers=[(b"authorization", b"Bearer not-a-real-token")])
        self.assertEqual(status, 200)
        self.assertTrue(body["available"])

    def test_the_route_sits_on_the_public_router_with_the_per_ip_limiter(self):
        route = [r for r in card_api.public_router.routes if r.path == "/card/accounts"]
        self.assertEqual(len(route), 1)
        self.assertTrue(route[0].dependencies)
        self.assertNotIn("/card/accounts", [r.path for r in card_api.router.routes])

    def test_the_shape_is_stable(self):
        body = card_api.get_card_accounts()
        self.assertEqual(set(body), {"available", "start_date", "as_of", "min_graded_for_percent", "sports",
                                     "accounts", "reconciled", "pending", "notes", "postseason_note"})
        self.assertEqual(body["start_date"], "2026-09-22")
        self.assertEqual(body["as_of"], "2026-10-01")
        self.assertEqual([s["key"] for s in body["sports"]], ["mlb", "nfl", "ufc", "all"])
        self.assertEqual([a["id"] for a in body["accounts"]], ["flat100", "flat250", "pct1", "starter"])
        for account in body["accounts"]:
            self.assertEqual(set(account), {"id", "label", "start_balance", "staking", "series"})
            self.assertEqual(set(account["series"]), {"mlb", "nfl", "ufc", "all"})
            for series in account["series"].values():
                self.assertEqual(set(series), {
                    "sport", "label", "start_balance", "final_balance", "total_units", "picks", "wins",
                    "losses", "pushes", "voids", "graded", "days", "lowest_balance", "lowest_date",
                    "return_pct", "small_sample", "postseason_picks", "daily"})
                for day in series["daily"]:
                    self.assertEqual(set(day), {
                        "date", "picks", "wins", "losses", "pushes", "voids", "units", "stake", "result",
                        "balance", "postseason", "postseason_picks", "partial"})
        self.assertEqual(set(body["reconciled"]), {"mlb", "nfl", "ufc", "all"})
        self.assertEqual(body["notes"], list(ea.NOTES))
        self.assertEqual(body["postseason_note"], ea.POSTSEASON_NOTE)

    def test_it_carries_no_email_no_user_and_no_pick_name(self):
        body = card_api.get_card_accounts()
        blob = json.dumps(body)
        self.assertIsNone(re.search(r"@|email|token|user", blob, re.I))
        # Tonight's picks are paid. The fixture's unsettled 2026-10-03 card
        # holds named players; none of them may appear, only a count.
        tonight = [r for r in mlb_v2_payloads() if r.get("kind") == "card_published"][-1]
        names = {e.get("player") for e in tonight["all_bets"] if e.get("player")}
        self.assertTrue(names)
        for name in names:
            self.assertNotIn(name, blob)
        self.assertEqual(body["pending"], [{"sport": "mlb", "picks": 8}, {"sport": "ufc", "picks": 3}])
        self.assertNotIn("2026-10-03", blob)

    def test_the_numbers_are_the_numbers_the_record_route_serves(self):
        body = card_api.get_card_accounts()
        mlb = card_api.get_card_record()
        self.assertEqual(body["reconciled"]["mlb"]["counted_record"]["wins"], mlb["wins"])
        self.assertEqual(body["reconciled"]["mlb"]["counted_record"]["losses"], mlb["losses"])
        self.assertEqual(body["reconciled"]["mlb"]["counted_record"]["units"], mlb["profit_units"])
        self.assertEqual(body["reconciled"]["mlb"]["postseason_record"]["losses"], mlb["postseason"]["losses"])
        for view, sport in (("nfl", "nfl"), ("ufc", "mma")):
            rec = card_api.get_card_record(sport=sport)
            ref = body["reconciled"][view]["counted_record"]
            self.assertEqual((ref["wins"], ref["losses"], ref["voids"], ref["units"]),
                             (rec["wins"], rec["losses"], rec["voids"], rec["profit_units"]))
        self.assertEqual(body["reconciled"]["mlb"]["counted_record"], PUBLISHED["mlb_counted"])
        self.assertEqual(body["reconciled"]["nfl"]["counted_record"], PUBLISHED["nfl"])
        self.assertEqual(body["reconciled"]["ufc"]["counted_record"], PUBLISHED["ufc"])
        self.assertTrue(all(r["ok"] for r in body["reconciled"].values()))

    def test_the_default_accounts_end_where_the_record_says(self):
        body = card_api.get_card_accounts()
        by_id = {a["id"]: a["series"] for a in body["accounts"]}
        self.assertAlmostEqual(by_id["flat100"]["mlb"]["final_balance"], 9295.37, places=6)
        self.assertAlmostEqual(by_id["flat100"]["all"]["final_balance"], 9638.23, places=6)
        self.assertAlmostEqual(by_id["flat250"]["all"]["final_balance"], 9095.575, places=6)
        self.assertAlmostEqual(by_id["starter"]["all"]["final_balance"], 963.823, places=6)
        self.assertFalse(any(d["partial"] for a in body["accounts"]
                             for s in a["series"].values() for d in s["daily"]))   # nothing is mid-settlement
        self.assertEqual(by_id["flat100"]["ufc"]["picks"], 7)
        self.assertEqual(by_id["flat100"]["ufc"]["small_sample"], True)
        self.assertIsNone(by_id["flat100"]["ufc"]["return_pct"])
        self.assertIsNone(by_id["flat100"]["nfl"]["return_pct"])
        self.assertIsNotNone(by_id["flat100"]["all"]["return_pct"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ItReadsWhatTheRecordPageAlreadyRead(RouteCase):
    def test_after_the_record_page_has_loaded_the_accounts_read_no_ledger_again(self):
        """The record page asks for /card/record and /card/history?limit=60 for
        its sport. Those fill the public memo; the accounts route must build
        from those entries and read no ledger of its own."""
        for sport in ("mlb", "nfl", "mma"):
            card_api.get_card_record(sport=sport)
            card_api.get_card_history(limit=60, sport=sport)
        spies = {name: mock.patch.object(card_ledger, name, wraps=getattr(card_ledger, name))
                 for name in ("record", "record_v2", "history", "history_v2", "verify")}
        started = {name: patch.start() for name, patch in spies.items()}
        try:
            body = card_api.get_card_accounts()
        finally:
            for patch in spies.values():
                patch.stop()
        self.assertTrue(body["available"])
        for name, spy in started.items():
            self.assertEqual(spy.call_count, 0, f"/card/accounts re-read the ledger through {name}()")

    def test_a_second_request_is_the_same_object_not_a_rebuild(self):
        first = card_api.get_card_accounts()
        with mock.patch.object(card_api, "_accounts_uncached", side_effect=AssertionError("rebuilt")):
            self.assertIs(card_api.get_card_accounts(), first)

    def test_opening_the_accounts_first_still_costs_one_build_of_each_not_two(self):
        card_api.get_card_accounts()
        spies = {name: mock.patch.object(card_ledger, name, wraps=getattr(card_ledger, name))
                 for name in ("record_v2", "history_v2")}
        started = {name: patch.start() for name, patch in spies.items()}
        try:
            for sport in ("mlb", "nfl", "mma"):
                card_api.get_card_record(sport=sport)
                card_api.get_card_history(limit=60, sport=sport)
        finally:
            for patch in spies.values():
                patch.stop()
        for name, spy in started.items():
            self.assertEqual(spy.call_count, 0, f"the record page re-read the ledger through {name}()")

    def test_a_ledger_change_is_picked_up_on_the_next_request(self):
        first = card_api.get_card_accounts()
        card_ledger.CARD_STORE_V2  # patched path from the fixture
        with open(self.paths["ufc"], "a", encoding="utf-8") as fh:
            fh.write("\n")
        second = card_api.get_card_accounts()
        self.assertIsNot(first, second)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ABadConfigIsUnavailableNotACrash(RouteCase):
    def _use_config(self, text):
        path = os.path.join(self.paths["dir"], "example_accounts.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        patch = mock.patch.object(ea, "CONFIG_PATH", path)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_file_that_is_not_json(self):
        self._use_config("{ nope")
        body = card_api.get_card_accounts()
        self.assertIs(body["available"], False)
        self.assertIn("settings", body["reason"])
        self.assertNotIn("accounts", body)

    def test_a_file_with_an_impossible_account(self):
        self._use_config(json.dumps({"start_date": "2026-09-22", "accounts": [
            {"id": "x", "label": "x", "start_balance": 100,
             "staking": {"kind": "flat", "amount": 500}}]}))
        self.assertIs(card_api.get_card_accounts()["available"], False)

    def test_a_missing_file(self):
        patch = mock.patch.object(ea, "CONFIG_PATH", os.path.join(self.paths["dir"], "absent.json"))
        patch.start()
        self.addCleanup(patch.stop)
        self.assertIs(card_api.get_card_accounts()["available"], False)

    def test_fixing_the_file_is_picked_up_without_a_ledger_change(self):
        self._use_config("{ nope")
        self.assertIs(card_api.get_card_accounts()["available"], False)
        with open(ea.CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({"start_date": "2026-09-22", "accounts": [
                {"id": "only", "label": "Only", "start_balance": 5000,
                 "staking": {"kind": "flat", "amount": 50}}]}, fh)
        body = card_api.get_card_accounts()
        self.assertTrue(body["available"])
        self.assertEqual([a["id"] for a in body["accounts"]], ["only"])

    def test_the_status_is_still_200_so_the_record_page_is_not_broken(self):
        self._use_config("{ nope")
        status, body = asgi_get("/card/accounts")
        self.assertEqual(status, 200)
        self.assertIs(body["available"], False)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ACorruptedLedgerGivesUnavailableNeverAWrongBalance(RouteCase):
    def test_a_row_edited_after_it_was_written_breaks_the_chain_and_nothing_is_shown(self):
        self.assertTrue(card_api.get_card_accounts()["available"])
        path = self.paths["v2"]
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        edited, n = re.subn(r'"profit_units":\s*-1\.0\b', '"profit_units": -0.5', text, count=1)
        self.assertEqual(n, 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(edited)
        body = card_api.get_card_accounts()
        self.assertIs(body["available"], False)
        self.assertIn("tamper check", body["reason"])
        self.assertNotIn("accounts", body)
        # ...and the record route says the same thing about itself
        self.assertIs(card_api.get_card_record()["chain_ok"], False)

    def test_a_record_that_does_not_match_the_rows_is_refused(self):
        real = card_api._card_record_uncached

        def off_by_one_win(request=None, sport="mlb", rule=None):
            out = dict(real(request, sport, rule))
            if sport == "nfl":
                out["wins"] += 1
                out["by_kind"] = {k: dict(v) for k, v in out["by_kind"].items()}
                out["by_kind"]["game"]["wins"] += 1
            return out

        with mock.patch.object(card_api, "_card_record_uncached", off_by_one_win):
            body = card_api.get_card_accounts()
        self.assertIs(body["available"], False)
        self.assertIn("NFL", body["reason"])
        self.assertFalse(body["reconciled"]["nfl"]["ok"])

    def test_an_unexpected_failure_is_one_sentence_and_is_not_remembered(self):
        with mock.patch.object(card_api, "_accounts_sources", side_effect=RuntimeError("boom")):
            body = card_api.get_card_accounts()
        self.assertIs(body["available"], False)
        self.assertNotIn("boom", json.dumps(body))
        self.assertTrue(card_api.get_card_accounts()["available"])

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class APickWithAResultNobodyKnows(RouteCase):
    def setUp(self):
        payloads = mlb_v2_payloads()
        row = [r for r in payloads if r.get("kind") == "card_settled"][0]
        victim = [e for e in row["graded"] if e["entry_class"] == "pick" and not e.get("withdrawn")
                  and e["result"] == "LOSS"][0]
        victim["result"] = "MAYBE"
        type(self).ledger_kwargs = {"v2_payloads": payloads}
        self.addCleanup(lambda: type(self).ledger_kwargs.clear())
        super().setUp()

    def test_it_is_not_guessed_at(self):
        body = card_api.get_card_accounts()
        self.assertIs(body["available"], False)
        self.assertNotIn("accounts", body)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AUfcRowWithAnInconsistentDayIsRefused(RouteCase):
    @staticmethod
    def _corrupt(row):
        if row.get("kind") == "card_settled" and row.get("date") == "2026-09-22" and row.get("picks"):
            row["picks"][0]["profit_units"] += 0.25

    def setUp(self):
        type(self).ledger_kwargs = {"ufc_text": ufc_text_with(self._corrupt)}
        self.addCleanup(lambda: type(self).ledger_kwargs.clear())
        super().setUp()

    def test_the_chain_verifies_so_only_the_reconciliation_can_catch_it(self):
        self.assertIs(card_api.get_card_record(sport="mma")["chain_ok"], True)

    def test_the_endpoint_says_it_cannot_show_balances(self):
        body = card_api.get_card_accounts()
        self.assertIs(body["available"], False)
        self.assertIn("do not add up", body["reason"])
        self.assertNotIn("accounts", body)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdayThatIsOnlyPartlySettled(RouteCase):
    """The public history withholds a day with an unresolved pick (it would
    list tonight's unplayed bets); the record still counts the day's finished
    picks. The accounts must count them too, or they would differ from the
    record by that day, and must say the day is partial."""

    def setUp(self):
        payloads = mlb_v2_payloads()
        row = [r for r in payloads if r.get("kind") == "card_settled" and r["date"] == "2026-10-01"][0]
        victim = [e for e in row["graded"]
                  if e["entry_class"] == "pick" and not e.get("withdrawn") and e["result"] == "LOSS"][0]
        victim["result"] = "UNRESOLVED"
        victim["profit_units"] = None
        type(self).ledger_kwargs = {"v2_payloads": payloads}
        self.addCleanup(lambda: type(self).ledger_kwargs.clear())
        super().setUp()

    def test_the_control_the_public_history_really_withholds_that_day(self):
        history = card_api.get_card_history(limit=60, sport="mlb")
        self.assertNotIn("2026-10-01", [d["date"] for d in history["days"]])
        self.assertEqual(history["withheld_days"], 1)

    def test_the_day_counts_what_has_finished_and_is_marked_partial(self):
        body = card_api.get_card_accounts()
        self.assertTrue(body["available"], body.get("reason"))
        rec = body["reconciled"]["mlb"]
        self.assertEqual(rec["account"]["picks"], 39)           # 40 less the one still waiting
        self.assertEqual(rec["postseason_record"]["picks"], 1)
        day = [d for d in body["accounts"][0]["series"]["mlb"]["daily"] if d["date"] == "2026-10-01"][0]
        self.assertTrue(day["partial"])
        self.assertTrue(day["postseason"])
        self.assertEqual(day["picks"], 1)
        self.assertNotIn("UNRESOLVED", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
