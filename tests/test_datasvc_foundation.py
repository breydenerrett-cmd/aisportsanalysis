"""The data service foundation: fetcher, JSONL store, name matching, ESPN URLs, UFC store.

No network: the fetcher gets a fake opener, clock and sleep.
"""
import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from src.datasvc import http, names, store
from src.datasvc.ufc import espn_urls
from src.datasvc.ufc.store import UfcStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"


class FakeResponse:
    def __init__(self, status, body, ctype="application/json"):
        self.status = status
        self._body = body
        msg = email.message.Message()
        msg["content-type"] = ctype
        self.headers = msg

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Serves queued answers per canonical URL; records every call."""

    def __init__(self):
        self.answers = {}
        self.calls = []

    def queue(self, url, *answers):
        self.answers.setdefault(http.canonical_url(url), []).extend(answers)

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        answer = self.answers[url].pop(0)
        if isinstance(answer, tuple) and answer[0] == "http_error":
            _, code, retry_after = answer
            hdrs = email.message.Message()
            if retry_after is not None:
                hdrs["Retry-After"] = str(retry_after)
            raise urllib.error.HTTPError(url, code, "err", hdrs, io.BytesIO(b"{}"))
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return FakeResponse(status, body)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 4))
        self.now += seconds


def fetcher(tmp, opener, clock, **kw):
    return http.PoliteFetcher(cache_dir=Path(tmp), opener=opener, sleep=clock.sleep,
                              clock=clock.clock, now_iso=lambda: "2026-10-03T18:00:00Z", **kw)


URL = "http://sports.core.api.espn.com/v2/sports/mma/athletes/4412813?lang=en&region=us"


class CanonicalUrl(unittest.TestCase):
    def test_https_and_no_lang_or_region_and_sorted_params(self):
        self.assertEqual(http.canonical_url(URL),
                         "https://sports.core.api.espn.com/v2/sports/mma/athletes/4412813")
        self.assertEqual(http.canonical_url("http://Example.com/x?b=2&lang=en&a=1"),
                         "https://example.com/x?a=1&b=2")

    def test_a_browser_check_page_is_recognised(self):
        self.assertTrue(http.looks_like_challenge(b"<title>Checking your browser...</title>"))
        self.assertFalse(http.looks_like_challenge(b'{"id": "1"}'))


class PoliteFetcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener, self.clock = FakeOpener(), FakeClock()

    def test_second_read_comes_from_the_cache(self):
        self.opener.queue(URL, (200, b'{"id": "4412813"}'))
        f = fetcher(self.tmp.name, self.opener, self.clock)
        self.assertEqual(f.get_json(URL)["id"], "4412813")
        self.assertEqual(f.get_json(URL.replace("http://", "https://"))["id"], "4412813")
        self.assertEqual(len(self.opener.calls), 1)
        self.assertEqual((f.stats["requests"], f.stats["cache_hits"]), (1, 1))
        self.assertEqual(f.fetched_utc(URL), "2026-10-03T18:00:00Z")

    def test_a_404_is_cached_and_raised_both_times(self):
        self.opener.queue(URL, (404, b""))
        f = fetcher(self.tmp.name, self.opener, self.clock)
        for _ in range(2):
            with self.assertRaises(http.NotFound):
                f.get_json(URL)
        self.assertEqual(len(self.opener.calls), 1)

    def test_a_503_is_retried_with_backoff_then_succeeds(self):
        self.opener.queue(URL, ("http_error", 503, None), (200, b"{}"))
        f = fetcher(self.tmp.name, self.opener, self.clock, backoff_s=2.0)
        self.assertEqual(f.get_json(URL), {})
        self.assertIn(2.0, self.clock.slept)
        self.assertEqual(f.stats["retries"], 1)

    def test_retry_after_is_honoured_up_to_a_minute(self):
        self.opener.queue(URL, ("http_error", 429, 600), (200, b"{}"))
        f = fetcher(self.tmp.name, self.opener, self.clock, backoff_s=1.0)
        f.get_json(URL)
        self.assertIn(60.0, self.clock.slept)

    def test_a_400_is_not_retried(self):
        self.opener.queue(URL, ("http_error", 400, None))
        f = fetcher(self.tmp.name, self.opener, self.clock)
        with self.assertRaises(http.FetchError) as ctx:
            f.get_json(URL)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(self.opener.calls), 1)

    def test_retries_stop_after_the_limit(self):
        self.opener.queue(URL, *[("http_error", 502, None)] * 3)
        f = fetcher(self.tmp.name, self.opener, self.clock, retries=2)
        with self.assertRaises(http.FetchError):
            f.get_json(URL)
        self.assertEqual(len(self.opener.calls), 3)

    def test_the_request_cap_stops_the_run(self):
        a, b = URL, URL.replace("4412813", "4001851")
        self.opener.queue(a, (200, b"{}"))
        f = fetcher(self.tmp.name, self.opener, self.clock, max_requests=1)
        f.get_json(a)
        with self.assertRaises(http.RequestCapReached):
            f.get_json(b)
        self.assertEqual(len(self.opener.calls), 1)

    def test_a_browser_check_raises_and_is_never_cached(self):
        page = b"<html><title>Checking your browser</title><noscript>This site requires JavaScript</noscript>"
        self.opener.queue(URL, (200, page), (200, page))
        f = fetcher(self.tmp.name, self.opener, self.clock)
        for _ in range(2):
            with self.assertRaises(http.SourceBlocked):
                f.get_text(URL)
        self.assertEqual(len(self.opener.calls), 2)

    def test_requests_are_spaced_by_the_delay(self):
        a, b = URL, URL.replace("4412813", "4001851")
        self.opener.queue(a, (200, b"{}"))
        self.opener.queue(b, (200, b"{}"))
        f = fetcher(self.tmp.name, self.opener, self.clock, delay_s=0.5)
        f.get_json(a)
        f.get_json(b)
        self.assertEqual(self.clock.slept, [0.5])

    def test_max_age_refetches_a_stale_copy(self):
        self.opener.queue(URL, (200, b'{"v": 1}'), (200, b'{"v": 2}'))
        f = fetcher(self.tmp.name, self.opener, self.clock)
        self.assertEqual(f.get_json(URL)["v"], 1)
        # The cached copy says it was fetched at 18:00 on 2026-10-03, long before "now".
        self.assertEqual(f.get_json(URL, max_age_s=60)["v"], 2)

    def test_non_json_is_a_fetch_error(self):
        self.opener.queue(URL, (200, b"<html>not json</html>"))
        f = fetcher(self.tmp.name, self.opener, self.clock)
        with self.assertRaises(http.FetchError):
            f.get_json(URL)


class JsonlStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "x.jsonl"

    def test_written_sorted_by_key_with_stable_bytes(self):
        store.write_jsonl(self.path, [{"id": "2", "b": 1, "a": 2}, {"id": "1", "z": 0}], key="id")
        first = self.path.read_bytes()
        store.write_jsonl(self.path, [{"id": "1", "z": 0}, {"a": 2, "b": 1, "id": "2"}], key="id")
        self.assertEqual(self.path.read_bytes(), first)
        self.assertEqual([r["id"] for r in store.read_jsonl(self.path)], ["1", "2"])
        self.assertNotIn(b"\r\n", first)

    def test_a_duplicate_key_is_an_error(self):
        with self.assertRaises(ValueError):
            store.write_jsonl(self.path, [{"id": "1"}, {"id": "1"}], key="id")

    def test_a_missing_key_field_is_an_error(self):
        with self.assertRaises(ValueError):
            store.write_jsonl(self.path, [{"id": ""}], key="id")

    def test_upsert_counts_ignore_fetch_time(self):
        store.write_jsonl(self.path, [{"id": "1", "v": 1, "fetched_utc": "a"}], key="id")
        counts = store.upsert(self.path, [{"id": "1", "v": 1, "fetched_utc": "b"},
                                          {"id": "2", "v": 1}], key="id")
        self.assertEqual(counts, {"added": 1, "updated": 0, "unchanged": 1, "total": 2})
        counts = store.upsert(self.path, [{"id": "1", "v": 2}], key="id")
        self.assertEqual(counts["updated"], 1)

    def test_composite_keys(self):
        store.write_jsonl(self.path, [{"b": "1", "f": "9"}, {"b": "1", "f": "8"}], key=("b", "f"))
        self.assertEqual([r["f"] for r in store.read_jsonl(self.path)], ["8", "9"])

    def test_manifest_matches_the_files(self):
        store.write_jsonl(self.path, [{"id": "1"}], key="id")
        manifest = store.write_manifest(Path(self.tmp.name), {"x.jsonl": {"records": 1, "newest": None}})
        self.assertEqual(manifest["files"]["x.jsonl"]["sha256"], store.file_sha256(self.path))
        on_disk = json.loads((Path(self.tmp.name) / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["files"]["x.jsonl"]["records"], 1)


class NameMatching(unittest.TestCase):
    PEOPLE = {
        "1": ["Ismail Naurdiev"],
        "2": ["Marvin Vettori"],
        "3": ["José Aldo"],
        "4": ["Anderson Silva"],
        "5": ["Thiago Silva"],
    }

    def test_normalise_folds_accents_case_punctuation_and_nicknames(self):
        self.assertEqual(names.normalise('José "Junior" Aldo'), "jose aldo")
        self.assertEqual(names.normalise("Jan Błachowicz"), "jan blachowicz")
        self.assertEqual(names.normalise("Jiří Procházka"), "jiri prochazka")
        self.assertEqual(names.normalise("O'Malley,  Sean"), "omalley sean")

    def test_exact_and_partial_matches(self):
        self.assertEqual(names.match("jose aldo", self.PEOPLE).best, "3")
        self.assertEqual(names.match("Naurdiev", self.PEOPLE).best, "1")
        self.assertEqual(names.match("Vettori", self.PEOPLE).best, "2")

    def test_an_ambiguous_query_names_the_candidates_and_picks_nobody(self):
        result = names.match("Silva", self.PEOPLE)
        self.assertIsNone(result.best)
        self.assertTrue(result.ambiguous)
        self.assertEqual({c[0] for c in result.candidates}, {"4", "5"})

    def test_no_match(self):
        result = names.match("Conor McGregor", self.PEOPLE)
        self.assertIsNone(result.best)
        self.assertFalse(result.ambiguous)


class EspnUrls(unittest.TestCase):
    def test_ids_are_read_from_real_refs(self):
        comp = json.loads((FIXTURES / "competitor_401924683_5060467.json").read_text(encoding="utf-8"))
        ref = comp["statistics"]
        self.assertEqual(espn_urls.id_from_ref(ref, "event"), "600061266")
        self.assertEqual(espn_urls.id_from_ref(ref, "competition"), "401924683")
        self.assertEqual(espn_urls.id_from_ref(ref, "competitor"), "5060467")
        self.assertEqual(espn_urls.id_from_ref(comp["athlete"], "athlete"), "5060467")

    def test_ref_url_is_the_canonical_form(self):
        self.assertEqual(espn_urls.ref_url({"$ref": URL}), espn_urls.athlete("4412813"))

    def test_builders(self):
        self.assertTrue(espn_urls.competitor_statistics("1", "2", "3").endswith("/events/1/competitions/2/competitors/3/statistics/0"))
        self.assertTrue(espn_urls.scoreboard("2026-10-03").endswith("dates=20261003"))
        self.assertIn("dates=2026", espn_urls.season_events(2026))


class UfcStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UfcStore(Path(self.tmp.name))

    def test_round_trip_and_indexes(self):
        self.store.upsert("bouts", [
            {"bout_id": "2", "event_id": "e2", "date_utc": "2026-09-27T00:00Z", "fighter_a_id": "a", "fighter_b_id": "b"},
            {"bout_id": "1", "event_id": "e1", "date_utc": "2026-05-01T00:00Z", "fighter_a_id": "a", "fighter_b_id": "c"},
        ])
        self.store.upsert("fight_stats", [{"bout_id": "1", "fighter_id": "a", "date_utc": "2026-05-01T00:00Z", "knockdowns": 1}])
        self.assertEqual([b["bout_id"] for b in self.store.bouts_by_fighter()["a"]], ["1", "2"])
        self.assertEqual(self.store.stats_for()[("1", "a")]["knockdowns"], 1)
        self.assertEqual(self.store.newest("bouts"), "2026-09-27T00:00Z")

    def test_manifest_lists_only_files_that_exist(self):
        self.store.upsert("events", [{"event_id": "e1", "date_utc": "2026-09-26T21:00Z"}])
        manifest = self.store.write_manifest()
        self.assertEqual(list(manifest["files"]), ["events.jsonl"])
        self.assertEqual(manifest["files"]["events.jsonl"]["newest"], "2026-09-26T21:00Z")


if __name__ == "__main__":
    unittest.main()
