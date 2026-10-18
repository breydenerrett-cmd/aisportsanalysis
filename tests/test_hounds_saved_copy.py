"""The saved copy: a restart answers GET /hounds at once instead of "warming up".

The app redeploys hourly and every restart empties the in-memory book, so the first GET /hounds used to
answer ``warming_up`` for the 5 to 10 s the build takes; a once-a-day caller (a scheduled digest) that
landed there skipped its day. ``stats.write_snapshot`` saves the public payloads beside the app db after
each good background build; ``stats.saved_payload`` serves them (``stale: true``, ``as_of`` = when they
were built) while the one rebuild runs. These tests pin the rules: a fresh copy is served and a rebuild is
started; a copy over 24 h old, a corrupt one, or none at all is ignored (``warming_up``, as before); the
write is atomic; the file holds nothing private and never passes 2 MB; and the page says "Updated ..."
when it shows a saved copy.

Every test points ``HOUNDS_SNAPSHOT_PATH`` at its own temp file, so none reads or writes a real data
volume (the lesson of tests/test_hounds_stats.py: an un-injected store makes a test pass by machine).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import stats
from src.hounds.ledgers import Sources
from tests import _hounds_fixtures as F
from tests import hounds_web_fixtures as WF
from tests.hounds_web_runner import HAS_NODE, run_page

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds import router


def _utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class SavedCopyBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src = F.make_world(root / "world")
        self.path = root / "volume" / "hounds_public_cache.json"
        self._env = mock.patch.dict(os.environ, {stats.ENV_SNAPSHOT_PATH: str(self.path)})
        self._env.start()
        self._default = mock.patch.object(Sources, "default", staticmethod(lambda: self.src))
        self._default.start()
        stats.clear_cache()

    def tearDown(self):
        stats.clear_cache()
        self._default.stop()
        self._env.stop()
        self._tmp.cleanup()

    def built(self):
        return stats.get_book(self.src)

    def go_cold(self):
        """What a restart does to memory, leaving the saved file where it is."""
        stats._CACHE["book"] = None
        stats._BG.update(error=None, failed_at=0.0, thread=None)

    def age_the_copy(self, built_epoch: float):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["built_utc"] = _utc(built_epoch)
        self.path.write_text(json.dumps(data), encoding="utf-8")


class WritingTheCopy(SavedCopyBase):
    def test_a_good_build_is_written_and_reads_back_as_stale(self):
        book = self.built()
        self.assertTrue(stats.write_snapshot(book))
        out = stats.saved_payload("leaderboard")
        self.assertIs(out["stale"], True)
        self.assertEqual(out["as_of"], book.built_utc)            # when it was built, not the data's day
        self.assertEqual(out["data_as_of"], book.as_of)
        self.assertEqual([h["id"] for h in out["hounds"]], [s.id for s in stats.leaderboard(book)])
        self.assertIs(out["paper_only"], True)
        self.assertNotIn("warming_up", out)

    def test_the_background_build_writes_the_file(self):
        self.assertFalse(self.path.exists())
        self.assertTrue(stats.refresh_async(self.src))
        stats._BG["thread"].join(timeout=60)
        self.assertTrue(self.path.exists())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["version"], stats.SNAPSHOT_VERSION)

    def test_the_write_is_atomic_a_temp_file_in_the_same_directory_then_a_replace(self):
        book = self.built()
        calls = []
        real_replace = os.replace

        def spy(src, dst):
            calls.append((Path(src), Path(dst), Path(dst).exists()))
            return real_replace(src, dst)

        with mock.patch("src.hounds.stats.os.replace", spy):
            self.assertTrue(stats.write_snapshot(book))
        (tmp, dst, existed_before), = calls
        self.assertEqual(tmp.parent, dst.parent)                  # same volume, so the replace is atomic
        self.assertNotEqual(tmp, dst)
        self.assertFalse(existed_before)                          # the real name appeared only at the replace
        self.assertFalse(tmp.exists())
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_a_failed_replace_leaves_the_old_copy_intact_and_no_temp_file(self):
        stats.write_snapshot(self.built())
        before = self.path.read_bytes()
        stats._SNAP["written_built"] = None
        with mock.patch("src.hounds.stats.os.replace", side_effect=OSError("disk full")), \
                self.assertLogs(stats.logger, "ERROR"):
            self.assertFalse(stats.write_snapshot(self.built()))  # never raises: the build still succeeded
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def test_one_build_is_written_once(self):
        book = self.built()
        self.assertTrue(stats.write_snapshot(book))
        self.assertFalse(stats.write_snapshot(book))

    def test_the_file_holds_only_the_public_payload_no_ids_tokens_or_secrets(self):
        stats.write_snapshot(self.built())
        text = self.path.read_text(encoding="utf-8")
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    keys.add(str(k).lower())
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(json.loads(text))
        for banned in ("user_id", "token", "password", "secret", "email", "api_key", "session", "owner_id"):
            self.assertFalse([k for k in keys if banned in k], banned)
        for banned in ("sha256", "Bearer ", "APP_DB_PATH", str(self._tmp.name)):
            self.assertNotIn(banned, text)
        self.assertEqual(set(json.loads(text)), {"version", "built_utc", "leaderboard", "graveyard", "stream", "series"})

    def test_a_file_over_2_mb_is_refused_and_said_once(self):
        book = self.built()
        with mock.patch.object(stats, "SNAPSHOT_MAX_BYTES", 200), \
                mock.patch.object(stats.logger, "warning") as warn:
            self.assertFalse(stats.write_snapshot(book))
            stats._SNAP["written_built"] = None
            self.assertFalse(stats.write_snapshot(book))
        self.assertFalse(self.path.exists())
        self.assertEqual(warn.call_count, 1)

    def test_the_cap_is_two_megabytes(self):
        self.assertEqual(stats.SNAPSHOT_MAX_BYTES, 2 * 1024 * 1024)

    def test_the_default_path_is_beside_the_app_db_never_in_the_repo(self):
        with mock.patch.dict(os.environ, {stats.ENV_SNAPSHOT_PATH: ""}):
            from src.appstate import users
            self.assertEqual(stats.snapshot_path(), users.db_path().parent / stats.SNAPSHOT_FILENAME)
            repo = Path(__file__).resolve().parent.parent
            self.assertNotIn(repo / "src", stats.snapshot_path().parents)

    def test_the_series_kept_are_the_ids_asked_for_most_then_the_leaderboard_order(self):
        book = self.built()
        order = [s.id for s in stats.leaderboard(book)]
        last = order[-1]
        stats.note_series_request([last])
        stats.note_series_request([last, "not-a-hound"])
        ids = stats._snapshot_series_ids(book)
        self.assertEqual(ids[0], last)
        self.assertNotIn("not-a-hound", ids)
        self.assertEqual(len(ids), len(set(ids)))


class ReadingTheCopy(SavedCopyBase):
    def test_older_than_24_hours_is_ignored(self):
        stats.write_snapshot(self.built())
        self.age_the_copy(time.time() - 24 * 3600 - 60)
        self.assertIsNone(stats.load_snapshot())
        self.assertIsNone(stats.saved_payload("leaderboard"))

    def test_just_under_24_hours_is_served(self):
        stats.write_snapshot(self.built())
        self.age_the_copy(time.time() - 24 * 3600 + 600)
        self.assertIsNotNone(stats.saved_payload("leaderboard"))

    def test_a_copy_stamped_in_the_future_is_a_bad_clock_and_ignored(self):
        stats.write_snapshot(self.built())
        self.age_the_copy(time.time() + 3600)
        self.assertIsNone(stats.load_snapshot())

    def test_corrupt_copies_are_ignored(self):
        stats.write_snapshot(self.built())
        good = self.path.read_text(encoding="utf-8")
        data = json.loads(good)
        broken = {
            "garbage": "not json at all {{{",
            "truncated": good[: len(good) // 2],
            "empty": "",
            "a list": "[1, 2, 3]",
            "wrong version": json.dumps({**data, "version": 99}),
            "missing part": json.dumps({k: v for k, v in data.items() if k != "stream"}),
            "part is not an object": json.dumps({**data, "graveyard": [1]}),
            "bad built stamp": json.dumps({**data, "built_utc": "yesterday"}),
            "no built stamp": json.dumps({k: v for k, v in data.items() if k != "built_utc"}),
        }
        for name, text in broken.items():
            with self.subTest(name):
                self.path.write_text(text, encoding="utf-8")
                self.assertIsNone(stats.load_snapshot())
                self.assertIsNone(stats.saved_payload("leaderboard"))

    def test_no_file_is_none(self):
        self.assertIsNone(stats.saved_payload("leaderboard"))

    def test_the_stream_copy_is_page_one_only(self):
        stats.write_snapshot(self.built())
        self.assertIsNotNone(stats.saved_payload("stream"))
        self.assertIsNone(stats.saved_payload("stream", page=2))
        self.assertIsNone(stats.saved_payload("stream", page_size=5))

    def test_a_series_request_the_copy_cannot_fully_answer_is_not_answered_in_part(self):
        book = self.built()
        stats.write_snapshot(book)
        have = list(json.loads(self.path.read_text(encoding="utf-8"))["series"]["series"])
        out = stats.saved_payload("series", ids=have[:1])
        self.assertEqual(list(out["series"]), have[:1])
        self.assertIsNone(stats.saved_payload("series", ids=have[:1] + ["never-saved"]))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AColdStartAnswersFromTheCopy(SavedCopyBase):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def cold_with_copy(self):
        book = self.built()
        stats.write_snapshot(book)
        self.go_cold()
        return book

    def test_a_fresh_copy_is_served_at_once_as_stale_and_one_rebuild_starts(self):
        book = self.cold_with_copy()
        with mock.patch.object(stats, "refresh_async", return_value=True) as rebuild:
            r = self.client.get("/hounds")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIs(body["stale"], True)
        self.assertNotIn("warming_up", body)
        self.assertEqual(body["as_of"], book.built_utc)
        self.assertTrue(body["hounds"])
        self.assertEqual(r.headers["cache-control"], "no-store")  # a stale answer must not sit in a shared cache
        rebuild.assert_called_once()

    def test_the_other_public_routes_serve_the_copy_too(self):
        book = self.cold_with_copy()
        ids = [s.id for s in stats.leaderboard(book)][:3]
        with mock.patch.object(stats, "refresh_async", return_value=True):
            grave = self.client.get("/hounds/graveyard").json()
            stream = self.client.get("/hounds/stream").json()
            series = self.client.get("/hounds/series?ids=" + ",".join(ids)).json()
        for body in (grave, stream, series):
            self.assertIs(body["stale"], True)
            self.assertNotIn("warming_up", body)
        self.assertEqual(list(series["series"]), ids)

    def test_the_real_rebuild_replaces_the_copy(self):
        self.cold_with_copy()
        first = self.client.get("/hounds").json()
        self.assertIs(first["stale"], True)
        stats._BG["thread"].join(timeout=60)
        second = self.client.get("/hounds").json()
        self.assertNotIn("stale", second)
        self.assertNotIn("warming_up", second)
        self.assertEqual(stats._BG["builds"] >= 1, True)

    def test_per_hound_routes_still_warm(self):
        self.cold_with_copy()
        with mock.patch.object(stats, "refresh_async", return_value=True):
            body = self.client.get("/hounds/alpha").json()
        self.assertIs(body["warming_up"], True)

    def test_a_copy_over_24_hours_old_is_ignored_and_the_endpoint_warms(self):
        self.cold_with_copy()
        self.age_the_copy(time.time() - 25 * 3600)
        with mock.patch.object(stats, "refresh_async", return_value=True):
            body = self.client.get("/hounds").json()
        self.assertIs(body["warming_up"], True)
        self.assertNotIn("stale", body)

    def test_a_corrupt_copy_is_ignored_and_the_endpoint_warms(self):
        self.cold_with_copy()
        self.path.write_text("{ this is not json", encoding="utf-8")
        with mock.patch.object(stats, "refresh_async", return_value=True):
            body = self.client.get("/hounds").json()
        self.assertIs(body["warming_up"], True)
        self.assertEqual(body["hounds"], [])

    def test_no_copy_warms_as_before(self):
        with mock.patch.object(stats, "refresh_async", return_value=True):
            body = self.client.get("/hounds").json()
        self.assertIs(body["warming_up"], True)

    def test_a_failed_first_build_still_serves_a_good_copy_and_503s_without_one(self):
        self.cold_with_copy()
        stats._BG.update(error="boom", failed_at=time.time(), thread=None)
        body = self.client.get("/hounds").json()
        self.assertIs(body["stale"], True)
        self.path.unlink()
        self.assertEqual(self.client.get("/hounds").status_code, 503)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePageSaysWhenItShowsASavedCopy(unittest.TestCase):
    BUILT = "2026-10-18T05:07:09Z"

    def stale(self, payload):
        return [200, {**payload, "stale": True, "as_of": self.BUILT, "data_as_of": payload.get("as_of"),
                      "retry_after_seconds": 5}]

    def test_an_updated_note_shows_while_stale_and_goes_when_the_real_answer_lands(self):
        r = {k: list(v) for k, v in WF.routes(True, 45).items()}
        ids = [h["id"] for h in WF.hounds(True)]
        r["/hounds/series"] = [200, WF.series(ids, True)]
        fresh = {"/hounds": [1, [200, WF.leaderboard()]], "/hounds/stream": [1, [200, WF.stream()]],
                 "/hounds/graveyard": [1, [200, WF.graveyard()]]}
        r["/hounds"] = self.stale(WF.leaderboard())
        r["/hounds/stream"] = self.stale(WF.stream())
        r["/hounds/graveyard"] = self.stale(WF.graveyard())
        queries = [dict(name="basis", sel="[data-hook='hounds-basis']", mode="text"),
                   dict(name="notes", sel="[data-hook='stale-note']", mode="count"),
                   dict(name="rows", sel="[data-hook='hounds-list'] .hd-row", mode="count"),
                   dict(name="warming", sel="[data-kind='warming']", mode="count")]
        out = run_page("hounds", routes=r, switchAfter=fresh, captureInitial=queries,
                       actions=[dict(do="fire_timers", wait=120)], queries=queries)
        first = out["captures"]["initial"]
        self.assertIn("Updated Oct 18 05:07 UTC", first["basis"])
        self.assertNotIn("As of", first["basis"])
        self.assertEqual(first["notes"], 2)                       # the stream and the graveyard say so too
        self.assertGreater(first["rows"], 0)                      # the saved race is shown, not a spinner
        self.assertEqual(first["warming"], 0)
        final = out["final"]
        self.assertNotIn("Updated", final["basis"])               # the real answer replaced it
        self.assertIn("As of", final["basis"])
        self.assertEqual(final["notes"], 0)
        self.assertEqual(final["rows"], first["rows"])


if __name__ == "__main__":
    unittest.main()
