"""A click-through to the public sample page is a counted, attributed view.

THE GAP (2026-10-05). Outreach links point at web/sample.html with
?utm_source=<lead>&utm_medium=<channel>&utm_campaign=<batch>. The page stored the first
touch but sent NO funnel event, so a lead who opened the link and did not sign up was invisible:
only signups carried a source, and "did the people I sent it to even look" had no answer. The
record page and postseason.html already send one `public_page_view` per load (web/js/pageview.js);
the sample page now calls that same function with the label "sample", and GET /admin/funnel
splits those views by source in `page_views.sample`, next to the signup columns of `by_source`.

WHAT THESE TESTS PIN
--------------------
Browser half (the REAL sample.js, pageview.js, attribution.js, api.js executed under node against
the fake DOM of tests/test_sample_brief.py; skipped when node is missing):
  * one beacon per load, page "sample", carrying utm_source / utm_medium / utm_campaign;
  * an untagged load still sends its view, with no invented source;
  * tracking that fails (blocked fetch, network error, a 500, blocked storage) does not change
    what the page renders;
  * the beacon carries only the page label, the UTM tags, the referrer HOST and the visitor's
    random id: no URL, no query parameter we did not ask for, nothing personal.
Server half (the real route functions, fed what node produced; skipped without FastAPI):
  * the view lands under its source in `page_views.sample` and in `by_source`;
  * `utm_source=internal-brey` is STORED but left out of every page_views count;
  * three loads by one visitor id are three views and one unique visitor;
  * a signup that follows, in the same browser, is credited to the sample's source;
  * a source tag never changes access: tagged requests to gated routes are still refused.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import attribution, billing, customers, events
from tests.test_appstate_billing import _FakeTransport
from tests.test_attribution_flow import _DbCase
from tests.test_sample_brief import HARNESS, brief

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"

TAGS = {"utm_source": "l009-tommy-lorenzo", "utm_medium": "x_account", "utm_campaign": "brief_01"}
OUTREACH = "?utm_source=l009-tommy-lorenzo&utm_medium=x_account&utm_campaign=brief_01"
FIRST_TOUCH_KEY = "linehound.first_touch"

# After the page has loaded, ask attribution.js what the signup form would send: the payload of
# POST /signup and the properties of its signup_started beacon (web/js/signup.js calls exactly these).
PROBE = HARNESS.replace("out.gets = gets;", """
try {
  const a = await import("./attribution.js");
  out.signupAttribution = a.attributionPayload();
  out.signupStartedProperties = a.firstTouchProperties() || null;
} catch (err) { out.probeFailed = String(err); }
out.gets = gets;""")
assert PROBE != HARNESS


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NodeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._node_tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._node_tmp.name)
        Path(cls._node_tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._node_tmp.name, "harness.mjs").write_text(PROBE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._node_tmp.cleanup()

    def load(self, **scenario):
        scenario.setdefault("brief", brief())
        env = dict(os.environ, SCENARIO=json.dumps(dict(kind="load", **scenario)))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._node_tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        out = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])
        self.assertFalse(out["crashed"], out["crashed"])
        self.assertNotIn("probeFailed", out)
        return out


class TheBeacon(NodeCase):
    def test_a_tagged_load_sends_exactly_one_page_view_carrying_the_tag(self):
        out = self.load(search=OUTREACH)
        self.assertEqual(out["posts"], ["/funnel/event"])
        beacon, = out["beacons"]
        self.assertEqual(beacon["kind"], "public_page_view")
        self.assertEqual(beacon["properties"], dict(TAGS, page="sample"))
        self.assertRegex(beacon["anon_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(out["stored"]["linehound.anon_id"], beacon["anon_id"])

    def test_each_load_is_one_view_so_two_loads_are_two_beacons(self):
        first = self.load(search=OUTREACH)
        again = self.load(search=OUTREACH, stored=first["stored"])
        self.assertEqual(len(first["beacons"]) + len(again["beacons"]), 2)
        # the returning browser keeps its visitor id
        self.assertEqual(first["beacons"][0]["anon_id"], again["beacons"][0]["anon_id"])

    def test_the_page_still_draws_the_brief_and_its_links(self):
        out = self.load(search=OUTREACH)
        self.assertEqual(out["callCount"], 2)
        self.assertEqual(len(out["links"]), 3)

    def test_an_untagged_load_still_counts_and_invents_no_source(self):
        out = self.load(search="")
        beacon, = out["beacons"]
        self.assertEqual(beacon["kind"], "public_page_view")
        self.assertEqual(beacon["properties"], {"page": "sample"})
        self.assertNotIn(FIRST_TOUCH_KEY, out["stored"])

    def test_first_touch_wins_and_the_view_carries_the_stored_one(self):
        earlier = {"utm_source": "reddit", "utm_medium": "post", "utm_campaign": "launch"}
        out = self.load(search=OUTREACH, stored={FIRST_TOUCH_KEY: json.dumps(earlier)})
        self.assertEqual(json.loads(out["stored"][FIRST_TOUCH_KEY]), earlier)
        self.assertEqual(out["beacons"][0]["properties"]["utm_source"], "reddit")

    def test_the_view_is_stored_with_the_same_touch_the_signup_will_read(self):
        out = self.load(search=OUTREACH)
        self.assertEqual(json.loads(out["stored"][FIRST_TOUCH_KEY]), TAGS)
        self.assertEqual({k: v for k, v in out["signupAttribution"].items() if k != "anon_id"}, TAGS)
        self.assertEqual(out["signupAttribution"]["anon_id"], out["beacons"][0]["anon_id"])
        self.assertEqual(out["signupStartedProperties"], TAGS)


class TrackingFailureNeverTouchesThePage(NodeCase):
    def test_a_failing_beacon_leaves_the_page_exactly_as_it_would_have_been(self):
        baseline = self.load(search=OUTREACH)
        for mode in ("sync", "reject", "http500"):
            with self.subTest(beaconFails=mode):
                out = self.load(search=OUTREACH, beaconFails=mode)
                self.assertEqual(len(out["beacons"]), 1, "the beacon was attempted")
                for key in ("text", "hooks", "links", "callCount", "facts", "footerChildren"):
                    self.assertEqual(out[key], baseline[key], key)
                self.assertEqual(json.loads(out["stored"][FIRST_TOUCH_KEY]), TAGS)

    def test_blocked_storage_and_a_failing_beacon_together_still_render(self):
        baseline = self.load(search=OUTREACH)
        out = self.load(search=OUTREACH, brokenStorage=True, beaconFails="reject")
        self.assertEqual(out["stored"], {})
        for key in ("text", "hooks", "links", "callCount", "facts"):
            self.assertEqual(out[key], baseline[key], key)

    def test_blocked_storage_alone_still_sends_an_attributed_view(self):
        out = self.load(search=OUTREACH, brokenStorage=True)
        self.assertEqual(out["beacons"][0]["properties"], dict(TAGS, page="sample"))
        self.assertEqual(out["callCount"], 2)

    def test_a_failing_brief_request_still_counts_the_view(self):
        out = self.load(search=OUTREACH, briefFails=True)
        self.assertEqual(len(out["beacons"]), 1)
        self.assertIn("sample-none", out["hooks"])


class NoPersonalDataInTheEvent(NodeCase):
    def test_only_the_page_label_the_tags_the_referrer_host_and_the_random_id_are_sent(self):
        out = self.load(
            search=OUTREACH + "&email=jane@example.com&token=SECRET123&utm_content=a&utm_term=b",
            referrer="https://old.reddit.com/r/mlb/comments/abc?user=jane")
        beacon, = out["beacons"]
        self.assertEqual(set(beacon), {"kind", "properties", "anon_id"})
        allowed = set(attribution.ALLOWED_KEYS) | {"page"}
        self.assertLessEqual(set(beacon["properties"]), allowed)
        self.assertEqual(beacon["properties"]["referrer_host"], "old.reddit.com")
        wire = json.dumps(beacon)
        for secret in ("jane", "example.com", "SECRET123", "comments/abc", "email", "token", "http"):
            self.assertNotIn(secret, wire)

    def test_every_property_passes_the_server_cleaner_unchanged(self):
        out = self.load(search=OUTREACH, referrer="https://old.reddit.com/r/mlb")
        props = dict(out["beacons"][0]["properties"])
        page = props.pop("page")
        self.assertEqual(attribution.clean_attribution(props), props)
        self.assertEqual(page, "sample")


# ---------------------------------------------------------------------------
# The server half, fed with what node actually produced.
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SampleViewsInTheAdminReport(_DbCase):
    def _post(self, props, anon="a" * 32, kind="public_page_view"):
        from api.funnel import FunnelEventRequest, post_funnel_event
        return post_funnel_event(FunnelEventRequest(kind=kind, properties=props, anon_id=anon))

    def _funnel(self):
        from api.funnel import get_admin_funnel
        return get_admin_funnel(_admin=None)

    def test_a_view_shows_under_its_source_in_page_views_and_by_source(self):
        self._post(dict(TAGS, page="sample"))
        funnel = self._funnel()
        sample = funnel["page_views"]["sample"]
        self.assertEqual((sample["views"], sample["unique_visitors"]), (1, 1))
        self.assertEqual(sample["by_source"], {"l009-tommy-lorenzo": {"views": 1, "unique_visitors": 1}})
        self.assertEqual(funnel["by_source"]["l009-tommy-lorenzo"]["public_page_view"], 1)

    def test_an_untagged_view_is_direct_not_a_made_up_source(self):
        self._post({"page": "sample"})
        self.assertEqual(list(self._funnel()["page_views"]["sample"]["by_source"]), ["(direct)"])

    def test_sample_views_are_split_from_the_other_public_pages(self):
        self._post(dict(TAGS, page="sample"))
        self._post(dict(TAGS, page="record-card"))
        self._post(dict(TAGS, page="record-card"))
        views = self._funnel()["page_views"]
        self.assertEqual((views["sample"]["views"], views["record-card"]["views"]), (1, 2))

    def test_an_internal_source_is_stored_but_left_out_of_the_page_view_counts(self):
        self._post({"page": "sample", "utm_source": "l012-real-lead"}, anon="b" * 32)
        self._post({"page": "sample", "utm_source": "internal-brey"}, anon="c" * 32)
        stored = [e for e in events.list_events(db=self.db) if e.kind == "public_page_view"]
        self.assertEqual(len(stored), 2, "the internal view is kept in storage")
        funnel = self._funnel()
        sample = funnel["page_views"]["sample"]
        self.assertEqual((sample["views"], sample["unique_visitors"]), (1, 1))
        self.assertEqual(list(sample["by_source"]), ["l012-real-lead"])
        self.assertEqual(funnel["internal_events_excluded"], 1)
        # it keeps its own labelled row beside the others, as every internal walk-through does
        self.assertEqual(funnel["by_source"]["internal-brey"]["public_page_view"], 1)

    def test_only_internal_and_internal_dash_are_excluded(self):
        for source in ("international-bettors", "Internal-Brey", "internal", "x-internal"):
            self._post({"page": "sample", "utm_source": source}, anon="d" * 32)
        sources = set(self._funnel()["page_views"]["sample"]["by_source"])
        self.assertEqual(sources, {"international-bettors", "x-internal"})

    def test_repeat_loads_by_one_visitor_are_views_but_one_unique_visitor(self):
        for _ in range(3):
            self._post(dict(TAGS, page="sample"), anon="e" * 32)
        self._post(dict(TAGS, page="sample"), anon="f" * 32)
        sample = self._funnel()["page_views"]["sample"]
        self.assertEqual((sample["views"], sample["unique_visitors"]), (4, 2))
        self.assertEqual(sample["by_source"]["l009-tommy-lorenzo"], {"views": 4, "unique_visitors": 2})

    def test_one_visitor_under_two_sources_is_one_visitor_in_total_and_one_in_each_row(self):
        self._post({"page": "sample", "utm_source": "a-lead"}, anon="e" * 32)
        self._post({"page": "sample", "utm_source": "b-lead"}, anon="e" * 32)
        sample = self._funnel()["page_views"]["sample"]
        self.assertEqual((sample["views"], sample["unique_visitors"]), (2, 1))

    def test_the_main_funnel_and_landing_baseline_are_untouched(self):
        self._post({"page": "sample", "utm_source": "x"}, anon="a" * 32)
        funnel = self._funnel()
        steps = {s["kind"]: s for s in funnel["steps"]}
        self.assertEqual(steps["landing_view"]["count"], 0)
        self.assertNotIn("public_page_view", steps)
        self.assertEqual(funnel["by_source"]["x"]["landing_view"], 0)

    def test_no_sample_views_means_no_sample_block_not_a_made_up_zero_row(self):
        self.assertEqual(self._funnel()["page_views"], {})

    def test_a_row_with_a_hand_written_page_is_filed_under_unknown(self):
        events.record_event_safe("anon:" + "a" * 32, events.PUBLIC_PAGE_VIEW,
                                 {"page": {"nested": "object"}, "utm_source": "x"})
        self.assertEqual(list(self._funnel()["page_views"]), ["(unknown)"])


@unittest.skipUnless(shutil.which("node") and HAS_FASTAPI, "node or fastapi not installed")
class SampleToSignupKeepsTheSource(_DbCase, NodeCase):
    """The lead opens the sample link, reads, and later uses 'Request early access' in the same
    browser: the account is credited to the sample's source, and the report shows view -> signup."""

    @classmethod
    def setUpClass(cls):
        NodeCase.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        NodeCase.tearDownClass.__func__(cls)

    def _provider(self, transport):
        return billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=transport,
            customer_ref_lookup=lambda uid: customers.get_customer_ref(uid, db=self.db),
            on_customer_created=lambda uid, cid: customers.upsert_customer(uid, cid, db=self.db))

    def test_the_signup_started_from_the_sample_carries_the_samples_first_touch(self):
        from api.funnel import FunnelEventRequest, get_admin_funnel, post_funnel_event
        from api.signup import SignupRequest, signup
        out = self.load(search=OUTREACH)
        # what the browser sent on arrival, replayed
        post_funnel_event(FunnelEventRequest(**out["beacons"][0]))
        # the signup form, opened later with the sample's address gone, sends the STORED touch
        post_funnel_event(FunnelEventRequest(kind="signup_started",
                                             properties=out["signupStartedProperties"],
                                             anon_id=out["signupAttribution"]["anon_id"]))
        transport = _FakeTransport()
        transport.queue(200, {"id": "cus_sample_lead"})
        transport.queue(200, {"id": "cs_sample_lead", "url": "https://checkout.stripe.com/sample"})
        with mock.patch.object(billing, "get_billing_provider", return_value=self._provider(transport)):
            signup(SignupRequest(email="sample-lead@example.com",
                                 attribution=out["signupAttribution"]), _rate_limit=None)
        funnel = get_admin_funnel(_admin=None)
        row = funnel["by_source"]["l009-tommy-lorenzo"]
        self.assertEqual((row["public_page_view"], row["signup_started"], row["account_created"]), (1, 1, 1))
        self.assertNotIn("(direct)", funnel["by_source"])
        self.assertEqual(funnel["page_views"]["sample"]["by_source"]["l009-tommy-lorenzo"]["views"], 1)


# ---------------------------------------------------------------------------
# A source tag is a label, never a key.
# ---------------------------------------------------------------------------

async def _asgi_get(app, path, query=b"", headers=()):
    """One request through the real app, no HTTP client (this environment has none)."""
    sent = []
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query,
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
             "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80)}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ASourceTagNeverChangesAccess(_DbCase):
    TAGGED = OUTREACH[1:].encode()

    def _get(self, path, query=TAGGED, headers=()):
        from api.app import app
        return asyncio.run(_asgi_get(app, path, query, headers))

    def test_tagged_requests_to_gated_routes_are_still_refused(self):
        for path in ("/today", "/card/2026-10-03", "/games/2026-10-03"):
            for query in (self.TAGGED, b"utm_source=internal-brey", b"utm_source=admin&role=admin&token=x"):
                with self.subTest(path=path, query=query):
                    self.assertEqual(self._get(path, query), 401)

    def test_a_tag_in_place_of_a_token_is_not_a_token(self):
        for header in ("Bearer l009-tommy-lorenzo", "Bearer utm_source=internal-brey"):
            with self.subTest(header=header):
                self.assertEqual(self._get("/today", headers=[("Authorization", header)]), 401)

    def test_a_tag_does_not_open_the_admin_report(self):
        with mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": "local-test-admin-token"}):
            self.assertEqual(self._get("/admin/funnel"), 401)
            self.assertEqual(self._get("/admin/funnel", headers=[("X-Admin-Token", "l009-tommy-lorenzo")]), 401)
            self.assertEqual(self._get("/admin/funnel",
                                       headers=[("X-Admin-Token", "local-test-admin-token")]), 200)

    def test_recording_a_tagged_view_creates_no_account_and_grants_nothing(self):
        from api.funnel import FunnelEventRequest, post_funnel_event
        from src.appstate import users as users_store
        post_funnel_event(FunnelEventRequest(kind="public_page_view",
                                             properties=dict(TAGS, page="sample"), anon_id="a" * 32))
        self.assertEqual(users_store.list_users(db=self.db), [])
        self.assertEqual(self._get("/today"), 401)


if __name__ == "__main__":
    unittest.main()
