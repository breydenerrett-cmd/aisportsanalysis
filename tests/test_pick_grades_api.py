"""``GET /hounds/{id}/bets`` carries a ``grades`` block on every ticket, additively, computed on read.

The route is exercised against a stub stats book (no ledger on disk): the glue under test is how the route finds the hound's
whole record, widens it to its lineage, keeps the page's filters out of the history, and leaves everything else in the payload
exactly as it was. The pure grader has its own file (tests/test_pick_grades.py). Skipped where FastAPI is not installed.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import ledgers, pick_grades_feed, stats, user_view
from src.hounds.contract import BetRow
from src.hounds.stats import HoundData

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds import router

T0 = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


def stamp(dt):
    return dt.isoformat().replace("+00:00", "Z")


def row(hound, i, result, *, segment="forward", start_day=0, price_average=-110, **kw):
    placed = T0 + timedelta(days=start_day + i)
    fields = dict(hound_id=hound, date=placed.strftime("%Y-%m-%d"), game=f"A{i} at B{i}", market="totals",
                  selection=f"Over {8 + i % 3}.5", line=f"{8 + i % 3}.5", price=-105, price_average=price_average,
                  result=result, segment=segment, event_id=f"{hound}-e{i}", sport="nhl",
                  start_utc=stamp(placed + timedelta(hours=1)), recorded_utc=stamp(placed + timedelta(minutes=2)),
                  lock_utc=stamp(placed), book_count=7, clv_pts=0.5 if result else None,
                  graded_utc=None if result is None else stamp(placed + timedelta(hours=6)),
                  units=0.9 if result == "win" else -1.0 if result == "loss" else None)
    fields.update(kw)
    return BetRow(**fields)


def data_of(rows):
    """A HoundData holding ``rows`` newest first, as the stats book does."""
    ordered = sorted(rows, key=lambda b: (b.date, b.recorded_utc or ""), reverse=True)
    return HoundData(summary=None, series=[], bets=ordered)


def hound_rows(hound, outcomes, **kw):
    out = [row(hound, i, r, **kw) for i, r in enumerate(outcomes)]
    return out


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class BetsRouteCarriesGrades(unittest.TestCase):
    def setUp(self):
        # alpha: ten settled forward bets (6-4), one open forward pick, one replay row. bravo/charlie are two versions of one lineage.
        results = ["win", "loss", "win", "win", "loss", "win", "loss", "win", "loss", "win"]
        self.alpha = hound_rows("alpha", results) + [row("alpha", 10, None), row("alpha", 11, "win", segment="replay")]
        self.v1 = hound_rows("v1", results)                       # an older version: ten settled bets
        self.v2 = [row("v2", 10, None, start_day=0)]               # the newer version's first, open, pick
        self.book = SimpleNamespace(as_of="2026-10-20", hounds={
            "alpha": data_of(self.alpha), "v1": data_of(self.v1), "v2": data_of(self.v2)})
        patches = [mock.patch.object(stats, "get_book_nowait", lambda: (self.book, stats.STATE_FRESH)),
                   mock.patch.object(pick_grades_feed, "lineage_ids",
                                     lambda hid: ["v1", "v2"] if hid in ("v1", "v2") else [hid])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def bets(self, hound="alpha", query=""):
        r = self.client.get(f"/hounds/{hound}/bets{query}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def pick(self, hound="alpha", event="alpha-e10"):
        """The one unsettled forward ticket, found by its game (its date is long past, so a status filter would call it ungraded)."""
        return next(b for b in self.bets(hound, "?segment=forward&page_size=50")["items"] if b["event_id"] == event)

    def test_every_forward_ticket_carries_value_confidence_and_clv_blocks(self):
        body = self.bets("alpha", "?page_size=50&segment=forward")
        self.assertEqual(len(body["items"]), 11)
        for item in body["items"]:
            g = item["grades"]
            self.assertEqual(set(g), {"value", "confidence", "clv"})
            self.assertEqual(set(g["value"]), {"score", "label", "slice", "shrunk_rate", "implied", "reason"})
            self.assertEqual(set(g["confidence"]), {"score", "label", "parts", "reason"})

    def test_the_open_pick_is_graded_from_everything_settled_before_it(self):
        g = self.pick()["grades"]
        self.assertEqual(g["value"]["slice"]["n"], 10)
        self.assertEqual((g["value"]["slice"]["w"], g["value"]["slice"]["l"]), (6, 4))
        self.assertEqual(g["value"]["label"], "Fair")
        self.assertIsNone(g["clv"])                                # an open pick has no closing line yet
        self.assertTrue(g["confidence"]["reason"].endswith("Not a win chance."))

    def test_the_first_bets_of_a_hound_are_not_yet_available_not_zero(self):
        items = self.bets("alpha", "?segment=forward&page_size=50")["items"]
        first = min(items, key=lambda b: b["recorded_utc"])
        self.assertEqual(first["grades"]["value"]["label"], "Not yet available")
        self.assertIsNone(first["grades"]["value"]["score"])
        self.assertIsNone(first["grades"]["confidence"]["score"])

    def test_a_filter_narrows_the_page_never_the_history(self):
        full = {b["event_id"]: b["grades"] for b in self.bets("alpha", "?segment=forward&page_size=50")["items"]}
        seen = 0
        for query in ("status=ungraded", "status=graded&outcome=won", "sort=price&page_size=3", "season=all&page=2&page_size=4",
                      "status=graded&page_size=2"):
            for item in self.bets("alpha", f"?{query}&segment=forward")["items"]:
                seen += 1
                self.assertEqual(item["grades"], full[item["event_id"]], query)
        self.assertGreater(seen, 8)

    def test_a_replay_ticket_has_no_grades(self):
        replay = [b for b in self.bets("alpha", "?page_size=50")["items"] if b["segment"] == "replay"]
        self.assertEqual(len(replay), 1)
        self.assertIsNone(replay[0]["grades"])

    def test_the_replay_row_is_not_history_for_a_forward_pick(self):
        before = self.pick()["grades"]
        self.book.hounds["alpha"] = data_of(self.alpha + [row("alpha", 0, "win", segment="replay", start_day=-40)])
        after = self.pick()["grades"]
        self.assertEqual(before, after)

    def test_the_payload_is_the_old_payload_plus_one_key(self):
        with mock.patch.object(pick_grades_feed, "attach_grades", lambda payload, *a, **k: payload):
            plain = self.bets("alpha", "?page_size=50")
        graded = self.bets("alpha", "?page_size=50")
        self.assertEqual({k: v for k, v in graded.items() if k != "items"}, {k: v for k, v in plain.items() if k != "items"})
        self.assertEqual(len(plain["items"]), len(graded["items"]))
        for old, new in zip(plain["items"], graded["items"]):
            self.assertIn("grades", new)
            self.assertEqual(old, {k: v for k, v in new.items() if k != "grades"})

    def test_a_later_settlement_cannot_change_an_earlier_pick_grade(self):
        pick_before = self.pick()["grades"]
        later = [row("alpha", 40 + i, "win") for i in range(20)]                  # 20 more wins, all settled long after the pick
        self.book.hounds["alpha"] = data_of(self.alpha + later)
        pick_after = self.pick()["grades"]
        self.assertEqual(pick_before, pick_after)

    def test_a_new_version_is_graded_on_its_lineage(self):
        v2_pick = self.bets("v2", "?segment=forward")["items"][0]
        # the open pick is placed on day 10; the older version's ten bets settled on days 0 to 9, so all ten are its history
        self.assertEqual(v2_pick["grades"]["value"]["slice"]["n"], 10)

    def test_without_the_lineage_the_hounds_own_version_is_used(self):
        with mock.patch.object(pick_grades_feed, "lineage_ids", lambda hid: [hid]):
            v2_pick = self.bets("v2", "?segment=forward")["items"][0]
        self.assertEqual(v2_pick["grades"]["value"]["label"], "Not yet available")

    def test_a_grading_failure_leaves_the_list_intact(self):
        with mock.patch.object(pick_grades_feed.pick_grades, "grades_for_page", side_effect=RuntimeError("boom")):
            body = self.bets("alpha", "?page_size=50")
        self.assertEqual(len(body["items"]), 12)
        self.assertTrue(all("grades" not in b for b in body["items"]))

    def test_grading_reads_and_writes_no_file(self):
        with mock.patch("builtins.open", side_effect=AssertionError("grading must not touch a file")):
            self.assertEqual(len(self.bets("alpha", "?page_size=50")["items"]), 12)

    def test_the_rows_in_the_book_are_not_changed_by_a_request(self):
        before = [vars(b).copy() for b in self.book.hounds["alpha"].bets]
        self.bets("alpha", "?page_size=50")
        self.assertEqual(before, [vars(b) for b in self.book.hounds["alpha"].bets])


class MemberHoundOutsideTheBook(unittest.TestCase):
    """A member hound created after the cached book was built is served by ``user_view.bets_for``; it carries grades too."""

    def test_bets_for_attaches_the_same_block(self):
        rows = hound_rows("mine", ["win", "loss", "win", "win", "loss", "win", "loss", "win", "loss", "win"]) + [row("mine", 10, None)]
        with mock.patch.object(user_view, "hound_data", lambda hid, **kw: data_of(rows) if hid == "mine" else None), \
                mock.patch.object(stats, "peek_book", lambda: None), \
                mock.patch.object(pick_grades_feed, "lineage_ids", lambda hid: [hid]):
            payload = user_view.bets_for("mine")
        item = next(b for b in payload["items"] if b["event_id"] == "mine-e10")
        self.assertEqual(item["grades"]["value"]["slice"]["n"], 10)
        self.assertEqual(item["grades"]["value"]["label"], "Fair")


class GradesByKey(unittest.TestCase):
    """The Analyze report's way to the same grades: keyed by ticket, from the same history, and nothing for a replay ticket."""

    def test_every_forward_ticket_is_graded_as_the_list_grades_it_and_a_replay_ticket_is_left_out(self):
        results = ["win", "loss", "win", "win", "loss", "win", "loss", "win", "loss", "win"]
        own = data_of(hound_rows("alpha", results) + [row("alpha", 10, None), row("alpha", 11, "win", segment="replay")])
        with mock.patch.object(pick_grades_feed, "lineage_ids", lambda hid: [hid]):
            keyed = pick_grades_feed.grades_by_key("alpha", own, lambda vid: None, lambda bet: bet.event_id)
            forward = [b for b in own.bets if b.segment == "forward"]
            listed = pick_grades_feed.pick_grades.grades_for_page(pick_grades_feed.history_for("alpha", own, lambda vid: None), forward)
        self.assertEqual(set(keyed), {f"alpha-e{i}" for i in range(11)})
        self.assertEqual(keyed, {b.event_id: g for b, g in zip(forward, listed)})
        self.assertEqual(keyed["alpha-e10"]["value"]["slice"]["n"], 10)

    def test_a_broken_grader_raises_so_the_caller_decides_what_it_costs(self):
        own = data_of(hound_rows("alpha", ["win"]))
        with mock.patch.object(pick_grades_feed, "lineage_ids", lambda hid: [hid]),                 mock.patch.object(pick_grades_feed.pick_grades, "grades_for_page", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                pick_grades_feed.grades_by_key("alpha", own, lambda vid: None, lambda bet: bet.event_id)


class TheLineageLookup(unittest.TestCase):
    """Every version of a member hound's lineage is history for the newest; anything odd falls back to the hound's own version."""

    def ids(self, hound_id, *, exists=True, found=None, boom=None):
        from src.hounds import user_defs, user_store
        lineage = (mock.Mock(side_effect=boom) if boom else mock.Mock(return_value=[{"id": i} for i in (found or [])]))
        with mock.patch.object(user_defs, "db_exists", lambda: exists), mock.patch.object(user_store, "lineage", lineage):
            return pick_grades_feed.lineage_ids(hound_id)

    def test_a_member_hounds_versions_oldest_first(self):
        self.assertEqual(self.ids("v3", found=["v1", "v2", "v3"]), ["v1", "v2", "v3"])

    def test_a_house_hound_or_an_unknown_one_is_its_own_lineage(self):
        self.assertEqual(self.ids("alpha", found=[]), ["alpha"])
        self.assertEqual(self.ids("alpha", exists=False, found=["x", "y"]), ["alpha"])

    def test_a_lineage_that_does_not_name_the_hound_is_not_trusted(self):
        self.assertEqual(self.ids("v3", found=["other-1", "other-2"]), ["v3"])

    def test_a_failed_lookup_falls_back_to_the_hounds_own_version(self):
        with self.assertLogs(pick_grades_feed.logger, level="ERROR"):
            self.assertEqual(self.ids("v3", boom=RuntimeError("db locked")), ["v3"])


class LockStampReachesTheTicket(unittest.TestCase):
    """The ledger row's ``lock_utc`` rides to the public ticket, so the grader has the placement instant to be point-in-time."""

    def test_a_ledger_bet_row_keeps_its_lock_stamp(self):
        rows = [{"kind": "bet", "bet_id": "b1", "hound_id": "h1", "slate_date": "2026-10-20", "sport": "nhl", "event_id": "e1",
                 "market": "totals", "side": "over", "line": "5.5", "price": -110, "best_price": -105, "n_books": 7,
                 "lock_utc": "2026-10-20T23:00:00Z", "recorded_utc": "2026-10-20T23:01:00Z", "selection": "Over 5.5"},
                {"kind": "graded", "bet_id": "b1", "hound_id": "h1", "result": "win", "graded_utc": "2026-10-21T04:00:00Z",
                 "clv_pts": 0.4}]
        bets, _ = ledgers.pack_rows(rows)
        ticket = stats.bet_row(bets[0], None)
        self.assertEqual(ticket.lock_utc, "2026-10-20T23:00:00Z")
        self.assertEqual(ticket.graded_utc, "2026-10-21T04:00:00Z")
        self.assertEqual((ticket.price, ticket.price_average, ticket.book_count), (-105, -110, 7))


if __name__ == "__main__":
    unittest.main()
