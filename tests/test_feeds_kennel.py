"""The kennel news feed: GET /feeds/kennel.rss and the events behind it (src/hounds/kennel_feed.py).

The core is tested without FastAPI (Linux CI has none); the route tests skip cleanly where it is missing.
Every event is built from fixtures: no live ledger, no network, no clock.
"""

from __future__ import annotations

import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import kennel_feed as K
from src.hounds import user_spec
from src.hounds.contract import BetRow, HoundSummary, Record, RetiredBlock
from src.hounds.learning import ledger as L
from tests import _hounds_user_fixtures as UF
from tests import _learning_fixtures as LF

ROOT = Path(__file__).resolve().parents[1]

# Never the real coach report ledger: evidence/hounds_coach_v1.jsonl gains rows in production use, and a test
# that reads it passes or fails depending on what the coach has done that day (it went red on 2026-10-19,
# the morning the first real coach tip landed). Tests that want coach items pass ``coach=`` explicitly.
_NO_REAL_COACH = mock.patch("src.hounds.coach_report.build", return_value=None)


def setUpModule():
    _NO_REAL_COACH.start()


def tearDownModule():
    _NO_REAL_COACH.stop()
BANNED = re.compile(r"\block\b|guarantee|can't lose|sure thing|profit|lifetime|get rich", re.IGNORECASE)


def summary(hid, name, *, status="running", retired=None, kind="house") -> HoundSummary:
    return HoundSummary(id=hid, name=name, kind=kind, status=status,
                        retired=RetiredBlock(*retired) if retired else None, record=Record())


def row(hid, day, result, *, segment="forward") -> BetRow:
    return BetRow(hound_id=hid, date=day, result=result, segment=segment)


def book_of(*hounds):
    """hounds: (summary, [BetRow, ...] newest first)."""
    return SimpleNamespace(hounds={s.id: SimpleNamespace(summary=s, bets=list(bets)) for s, bets in hounds})


def results(hid, *outcomes, day="2026-10-17"):
    """BetRows for one day, ``outcomes`` oldest first, returned newest first like the stats book."""
    rows = [row(hid, day, o) for o in outcomes]
    return list(reversed(rows))


def items_of(xml_text):
    return ET.fromstring(xml_text).findall("./channel/item")


def proposal_event(cid, hound="professor_paws", utc="2026-10-01T12:00:00Z"):
    return {"kind": "proposal", "utc": utc, "challenger_id": cid, "scope": "house", "hound_kind": "pack",
            "hound_id": hound, "lineage_key": hound, "category": "stats", "parent_version": 1,
            "spec": {"values": {"GAP": 0.03}}, "spec_hash": "h", "spec_diff": {"GAP": [0.02, 0.03]},
            "hypothesis": "x" * 30, "evidence": ["a"]}


class Retired(unittest.TestCase):
    def test_a_retired_hound_is_an_item_with_its_own_date_and_a_plain_why(self):
        book = book_of((summary("basset", "Professor Paws", status="retired",
                                retired=("2026-09-12", "retired: down more than 25 units")), []))
        events = K.collect(book, states={}, user_rows=[])
        self.assertEqual(len(events), 1)
        xml = K.render_feed(events, base_url="https://example.test")
        item = items_of(xml)[0]
        self.assertEqual(item.findtext("title"), "\U0001F480 Professor Paws got put down")
        self.assertEqual(parsedate_to_datetime(item.findtext("pubDate")),
                         datetime(2026, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(item.find("guid").get("isPermaLink"), "false")
        self.assertEqual(item.findtext("guid"), "kennel:retired:basset:2026-09-12")
        desc = item.findtext("description")
        self.assertIn("down more than 25 units", desc)
        self.assertTrue(desc.endswith("Paper bets only, not advice. 21+."))
        self.assertEqual(item.findtext("link"),
                         "https://example.test/web/hound.html?id=basset&utm_source=zapier"
                         "&utm_medium=discord&utm_campaign=kennel_feed")

    def test_a_version_replaced_by_its_own_next_version_is_not_put_down(self):
        book = book_of(
            (summary("charlie@v1", "Charlie", status="retired",
                     retired=("2026-10-03", "superseded by version 2")), []),
            (summary("zed", "Zed", status="retired", retired=("2026-10-04", "superseded by version 3")), []))
        self.assertEqual(K.collect(book, states={}, user_rows=[]), [])

    def test_a_moderators_reason_is_not_repeated_on_a_public_feed(self):
        book = book_of((summary("u-1", "Some Dog", status="retired", kind="user",
                                retired=("2026-10-05", "retired by a moderator: a long private reason")), []))
        desc = K.collect(book, states={}, user_rows=[])[0]["why"]
        self.assertNotIn("private reason", desc)


class Streaks(unittest.TestCase):
    def events(self, *hounds):
        return K.streak_events(book_of(*hounds))

    def test_five_wins_in_a_row_on_the_latest_day_is_an_item(self):
        s = summary("beagle", "Beagle")
        ev = self.events((s, results("beagle", "loss", "win", "win", "win", "win", "win")))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["guid"], "kennel:beagle:2026-10-17:win_streak")
        self.assertEqual(ev[0]["title"], "\U0001F525 Beagle has won 5 in a row")
        self.assertIn("2026-10-17", ev[0]["why"])

    def test_five_losses_in_a_row_is_an_item(self):
        s = summary("collie", "Collie")
        ev = self.events((s, results("collie", "win", "loss", "loss", "loss", "loss", "loss", "loss")))
        self.assertEqual(ev[0]["guid"], "kennel:collie:2026-10-17:loss_streak")
        self.assertEqual(ev[0]["title"], "\U0001F976 Collie has lost 6 in a row")

    def test_four_is_not_a_streak_and_a_loss_breaks_the_run(self):
        s = summary("a", "A")
        self.assertEqual(self.events((s, results("a", "win", "win", "win", "win"))), [])
        self.assertEqual(self.events((s, results("a", "win", "win", "win", "win", "win", "loss"))), [])

    def test_pushes_neither_extend_nor_break_a_run_and_replay_rows_never_count(self):
        s = summary("a", "A")
        rows = results("a", "win", "win", "push", "win", "win", "win")
        self.assertEqual(len(self.events((s, rows))), 1)
        rows = results("a", "win", "win", "win", "win") + [row("a", "2026-10-18", "win", segment="replay")]
        self.assertEqual(self.events((s, rows)), [])

    def test_a_run_that_spans_days_is_dated_by_its_latest_settled_day(self):
        s = summary("a", "A")
        rows = [row("a", "2026-10-17", "win"), row("a", "2026-10-17", "win"), row("a", "2026-10-16", "win"),
                row("a", "2026-10-15", "win"), row("a", "2026-10-15", "win")]
        ev = self.events((s, rows))
        self.assertEqual(ev[0]["guid"], "kennel:a:2026-10-17:win_streak")
        self.assertEqual(ev[0]["pub"], datetime(2026, 10, 17, tzinfo=timezone.utc))

    def test_ungraded_bets_are_not_results(self):
        s = summary("a", "A")
        rows = results("a", "win", "win", "win", "win") + [row("a", "2026-10-17", None)]
        self.assertEqual(self.events((s, rows)), [])


class LearningEvents(unittest.TestCase):
    def state(self, *events):
        return L.fold(events)

    def test_a_promotion_is_a_new_version_item_at_the_promotion_time(self):
        st = self.state(proposal_event("c-1"),
                        {"kind": "promotion", "utc": "2026-10-20T04:00:00Z", "hound_id": "professor_paws",
                         "challenger_id": "c-1", "from_version": 1, "to_version": 2, "params": {}})
        ev = K.learning_events({"house": st}, {"professor_paws": "Professor Paws"})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["title"], "\U0001F3C6 Professor Paws made the team: new version v2")
        self.assertEqual(ev[0]["guid"], "kennel:promoted:c-1")
        self.assertEqual(ev[0]["pub"], datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc))

    def test_a_cut_challenger_is_a_tryout_item_with_the_tweak_and_a_plain_reason(self):
        st = self.state(proposal_event("c-2"),
                        {"kind": "decision", "utc": "2026-10-22T05:00:00Z", "challenger_id": "c-2",
                         "outcome": "retired", "reason": "harm", "hound_id": "professor_paws"})
        ev = K.learning_events({"house": st}, {"professor_paws": "Professor Paws"})
        self.assertEqual(ev[0]["title"], "✂️ Professor Paws's tryout got cut")
        self.assertEqual(ev[0]["guid"], "kennel:cut:c-2")
        self.assertIn("GAP 0.02 to 0.03", ev[0]["why"])
        self.assertIn("did worse", ev[0]["why"])

    def test_a_live_or_undecided_challenger_is_not_news(self):
        st = self.state(proposal_event("c-3"), proposal_event("c-4"),
                        {"kind": "decision", "utc": "2026-10-22T05:00:00Z", "challenger_id": "c-4",
                         "outcome": "undecided", "reason": "expired", "hound_id": "professor_paws"})
        self.assertEqual(K.learning_events({"house": st}, {}), [])


class NewDogs(unittest.TestCase):
    def user_row(self, hid, name, created, version_no=1):
        spec = user_spec.validate_spec(UF.spec_dict(name=name))
        return {"id": hid, "name": name, "spec": spec, "created_at": created, "version_no": version_no}

    def test_a_first_version_is_a_new_dog_and_a_later_version_is_not(self):
        rows = [self.user_row("u-1", "Dog Days", "2026-10-10T09:30:00Z"),
                self.user_row("u-2", "Dog Days Two", "2026-10-11T09:30:00Z", version_no=2)]
        ev = K.new_hound_events(rows)
        self.assertEqual([e["title"] for e in ev], ["\U0001F436 New dog in the kennel: Dog Days"])
        self.assertEqual(ev[0]["guid"], "kennel:new:u-1")
        self.assertEqual(ev[0]["pub"], datetime(2026, 10, 10, 9, 30, tzinfo=timezone.utc))
        self.assertIn("Its rule:", ev[0]["why"])

    def test_a_name_can_never_become_a_mention(self):
        ev = K.new_hound_events([{"id": "u-1", "name": "@everyone Dog", "created_at": "2026-10-10T09:30:00Z",
                                  "version_no": 1, "spec": user_spec.validate_spec(UF.spec_dict())}])
        self.assertNotIn("@", ev[0]["title"])


class TheFeed(unittest.TestCase):
    def big_world(self):
        hounds = []
        for i in range(40):
            hounds.append((summary(f"h{i:02d}", f"Hound {i}", status="retired",
                                   retired=(f"2026-09-{(i % 28) + 1:02d}", "retired: down more than 25 units")), []))
        return book_of(*hounds)

    def test_newest_first_capped_at_thirty_and_valid_xml(self):
        xml = K.render_feed(K.collect(self.big_world(), states={}, user_rows=[]))
        items = items_of(xml)
        self.assertEqual(len(items), 30)
        stamps = [parsedate_to_datetime(i.findtext("pubDate")) for i in items]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertEqual(ET.fromstring(xml).tag, "rss")

    def test_two_polls_of_an_unchanged_world_are_byte_identical(self):
        book = self.big_world()
        one = K.render_feed(K.collect(book, states={}, user_rows=[]))
        two = K.render_feed(K.collect(book, states={}, user_rows=[]))
        self.assertEqual(one, two)
        guids = [i.findtext("guid") for i in items_of(one)]
        self.assertEqual(len(guids), len(set(guids)))

    def test_pubdates_are_the_events_own_times_never_now(self):
        xml = K.render_feed(K.collect(self.big_world(), states={}, user_rows=[]))
        for item in items_of(xml):
            self.assertEqual(parsedate_to_datetime(item.findtext("pubDate")).year, 2026)
            self.assertEqual(parsedate_to_datetime(item.findtext("pubDate")).month, 9)

    def test_an_empty_kennel_is_a_valid_empty_feed(self):
        xml = K.render_feed([])
        self.assertEqual(items_of(xml), [])
        self.assertIsNone(ET.fromstring(xml).find("./channel/lastBuildDate"))

    def test_voice_has_no_lock_or_guarantee_talk_and_every_item_ends_with_the_line(self):
        world = book_of(
            (summary("a", "A", status="retired", retired=("2026-10-01", "retired: down more than 25 units")), []),
            (summary("b", "B"), results("b", "win", "win", "win", "win", "win")))
        st = L.fold([proposal_event("c-9", "b"),
                     {"kind": "promotion", "utc": "2026-10-02T00:00:00Z", "hound_id": "b",
                      "challenger_id": "c-9", "from_version": 1, "to_version": 2, "params": {}}])
        xml = K.render_feed(K.collect(world, states={"house": st}, user_rows=[]))
        items = items_of(xml)
        self.assertGreaterEqual(len(items), 3)
        for item in items:
            text = item.findtext("title") + " " + item.findtext("description")
            self.assertIsNone(BANNED.search(text), text)
            self.assertTrue(item.findtext("description").endswith("Paper bets only, not advice. 21+."))

    def test_the_base_url_comes_from_the_apps_own_setting(self):
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://linehound.app/"}):
            self.assertEqual(K.site_base_url(), "https://linehound.app")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(K.site_base_url(), "https://linehound.app")


class ProductionReadersAreTheRealOnes(unittest.TestCase):
    def test_collect_reads_the_learning_ledgers_and_the_user_store(self):
        """collect() with no seams uses the two default learning scopes and the app database. Point both at
        temp files and prove a promotion written through the real ledger API appears."""
        with tempfile.TemporaryDirectory() as tmp:
            house = L.Scope.house(Path(tmp) / "house")
            user = L.Scope.user(Path(tmp) / "user")
            LF.propose_raw(house, cid="c-5", hound_id="professor_paws")
            L.log_for(house).append(L.K_PROMOTION, now=LF.utc("2026-10-25T00:00:00Z"), scope="house",
                                    hound_id="professor_paws", lineage_key="professor_paws",
                                    challenger_id="c-5", from_version=1, to_version=2, params={}, applied=True)
            with mock.patch.object(L, "default_scopes", return_value={"house": house, "user": user}), \
                    mock.patch("src.hounds.user_defs.db_exists", return_value=False):
                ev = K.collect(book_of((summary("professor_paws", "Professor Paws"), [])))
        self.assertEqual([e["guid"] for e in ev], ["kennel:promoted:c-5"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Route(unittest.TestCase):
    def client(self, book):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.feeds import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def patches(self, book, tmp):
        scopes = {"house": L.Scope.house(Path(tmp) / "h"), "user": L.Scope.user(Path(tmp) / "u")}
        return (mock.patch("src.hounds.stats.get_book_nowait", return_value=(book, "fresh")),
                mock.patch.object(L, "default_scopes", return_value=scopes),
                mock.patch("src.hounds.coach_report.build", return_value=None),     # never the real report ledger
                mock.patch("src.hounds.user_defs.db_exists", return_value=False))

    def test_the_route_serves_rss_with_the_right_type_and_is_stable(self):
        book = book_of((summary("basset", "Professor Paws", status="retired",
                                retired=("2026-09-12", "retired: down more than 25 units")), []))
        with tempfile.TemporaryDirectory() as tmp:
            a, b, c, d = self.patches(book, tmp)
            with a, b, c, d:
                client = self.client(book)
                r1, r2 = client.get("/feeds/kennel.rss"), client.get("/feeds/kennel.rss")
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertTrue(r1.headers["content-type"].startswith("application/rss+xml"))
        self.assertEqual(r1.text, r2.text)
        self.assertEqual(len(items_of(r1.text)), 1)

    def test_while_the_book_is_warming_it_answers_503_not_a_partial_feed(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.feeds import router
        app = FastAPI()
        app.include_router(router)
        with mock.patch("src.hounds.stats.get_book_nowait", return_value=(None, "warming")):
            r = TestClient(app).get("/feeds/kennel.rss")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers["retry-after"], "30")


class MountOrder(unittest.TestCase):
    def test_the_feeds_router_is_mounted_between_the_hounds_create_and_hounds_routers(self):
        text = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        create = text.index("app.include_router(hounds_create_router)")
        feeds = text.index("app.include_router(feeds_router)")
        catchall = text.index("app.include_router(hounds_router)")
        self.assertLess(create, feeds)
        self.assertLess(feeds, catchall)

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_coach_brief_resolves_to_its_own_route_not_the_hound_id_catch_all(self):
        """Through the REAL app, in its real mount order: a request for /hounds/coach-brief reaches the
        brief, not ``GET /hounds/{id}`` (which would answer 404 'no such hound' for an unknown id)."""
        import api.app as app_mod
        from fastapi.testclient import TestClient
        with mock.patch("api.feeds.coach_brief.build", return_value={"sentinel": "the brief"}), \
                mock.patch("src.hounds.stats.get_book_nowait", return_value=(book_of(), "fresh")):
            r = TestClient(app_mod.app).get("/hounds/coach-brief")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"sentinel": "the brief"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
