"""The browser half of "see the proof, pay, get access, come back, cancel".

No JS test runner exists in this repo, so this file does what its siblings do
-- pins the shipped source text -- and, where there is real logic, runs the
module itself under node when node is on PATH (the success page's polling
loop). Each test names the failure it guards:

  * a signed-out visitor meets a sign-in wall on the proof page
  * the success page showed an error and no retry while the webhook was late
  * the waitlist copy promised an email nothing can send
  * an active subscriber had no visible way to cancel
  * the sign-in page pointed at a "welcome email" that does not exist
  * attribution died on the landing page
  * the landing FAQ promised "no annual plan" forever
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401 -- CI runs the suite without it; route tests skip
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "js"


def _read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


class SignedOutVisitorCanReadTheProof(unittest.TestCase):
    def setUp(self):
        self.record = _read("cardrecord.js")
        self.dom = _read("dom.js")

    def test_the_record_page_offers_the_trial_to_a_signed_out_visitor(self):
        # CHANGED 2026-10-01: the wording is no longer a static 7-day string. It is
        # checkout.js's recordCtaLabel(): the trial length comes from /meta and the
        # button says "Request early access" unless checkout is on
        # (behaviour pinned in tests/test_checkout_copy_states.py).
        self.assertIn("recordCtaLabel(", self.record)
        self.assertIn("-day free trial to see tonight's card", _read("checkout.js"))
        self.assertNotIn("7-day", self.record)
        block = self.record.split("function signupCta(")[1].split("\n}\n")[0]
        self.assertIn('href: "#/signup"', block)
        self.assertIn("if (getToken()) return null;", block,
                      "a signed-in reader must not be sold the trial they already have")

    def test_the_cta_is_rendered_on_the_page(self):
        body = self.record.split("export async function renderCardRecord(")[1]
        self.assertIn('signupCta("top")', body)
        self.assertIn('signupCta("bottom")', body)

    def test_the_record_page_still_reads_the_two_public_endpoints_only(self):
        body = self.record.split("export async function renderCardRecord(")[1]
        self.assertIn("/card/record", body)
        self.assertIn("/card/history", body)

    def test_every_sign_in_gate_carries_a_start_free_trial_button(self):
        gate = self.dom.split("function renderAuthRequired(")[1].split("\n}\n")[0]
        self.assertIn('href: "#/signin"', gate)
        self.assertIn('href: "#/signup"', gate)
        # CHANGED 2026-10-01: "Start free trial" is gateLabel()'s trial-on wording;
        # the gate says "Request early access" unless /meta says on.
        self.assertIn("gateLabel(", gate)
        self.assertIn('"Start free trial"', _read("checkout.js"))

    def test_there_is_exactly_one_sign_in_gate(self):
        """A second gate elsewhere would not carry the button."""
        hits = [p.name for p in JS.glob("*.js")
                if "SIGN IN REQUIRED" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, ["dom.js"])


class SignInAndSignUpCopyIsTrue(unittest.TestCase):
    def setUp(self):
        self.signin = _read("signin.js")
        self.signup = _read("signup.js")

    def test_signin_does_not_mention_an_email_nothing_sends(self):
        self.assertNotIn("welcome email", self.signin.lower())
        self.assertIn("Paste the access token you were shown after checkout", self.signin)

    def test_no_file_under_web_promises_a_welcome_email(self):
        for path in list(JS.glob("*.js")) + list(WEB.glob("*.html")):
            with self.subTest(file=path.name):
                self.assertNotIn("welcome email", path.read_text(encoding="utf-8").lower())

    def test_signin_links_to_the_trial(self):
        self.assertIn('href: "#/signup"', self.signin)

    def test_the_waitlist_message_says_only_what_is_true(self):
        # CHANGED 2026-10-02 (owner: the first 20 testers get 7 days of early
        # access): the confirmation is decided in checkout.js, not here, and it
        # now carries the early-access facts. The three promises this test
        # exists to forbid are still forbidden, in both files.
        checkout = _read("checkout.js")
        self.assertIn("export const WAITLIST_CONFIRMATION =", checkout)
        self.assertIn("You're on the list.", checkout)
        self.assertNotIn("Checkout is not open yet. Your email is saved", self.signup)
        for source in (self.signup, checkout):
            self.assertNotIn("we'll email you", source.lower())
            self.assertNotIn("on the waitlist", source.lower())
            self.assertNotIn("when a beta spot opens", source.lower())

    def test_the_waitlisted_branch_renders_that_message(self):
        branch = self.signup.split('result.status === "waitlisted"')[1].split("} else if")[0]
        self.assertIn("WAITLIST_CONFIRMATION", branch)

    def test_heading_and_button_say_the_landing_cta_when_billing_is_on(self):
        # CHANGED 2026-10-01: no static "Start your 7-day free trial" -- the heading
        # and button text is checkout.js's ctaLabel(billing), whose trial length is
        # /meta's `trial_days` (behaviour pinned in tests/test_checkout_copy_states.py).
        self.assertIn("ctaLabel(billing)", self.signup)
        self.assertNotIn("7-day", self.signup)
        self.assertRegex(self.signup, r'text: billing\.on \? ctaText : "Checkout is not open yet\."')
        self.assertRegex(self.signup, r'text: billing\.on \? ctaText : "Save my email"')

    def test_billing_state_comes_from_meta_not_a_guess(self):
        # CHANGED 2026-10-01: the "on" decision moved to the one shared helper.
        self.assertIn("billing.checkout === \"on\"", _read("checkout.js"))
        self.assertIn("loadCheckoutState", self.signup)
        self.assertIn("meta()", _read("checkout.js"))

    def test_an_api_error_message_is_shown_instead_of_the_unrecognised_shape_line(self):
        self.assertIn('result.status === "error" && result.message', self.signup)


class SuccessPagePollsAndSignsTheBuyerIn(unittest.TestCase):
    def setUp(self):
        self.signup = _read("signup.js")

    def test_polling_is_every_two_seconds_for_sixty(self):
        self.assertIn("SIGNUP_POLL_INTERVAL_MS = 2000", self.signup)
        self.assertIn("SIGNUP_POLL_TIMEOUT_MS = 60000", self.signup)

    def test_the_waiting_state_is_named(self):
        self.assertIn("Finishing your signup...", self.signup)

    def test_the_token_is_stored_under_the_sign_in_pages_key(self):
        """setToken is api.js's writer for TOKEN_STORAGE_KEY, the same one
        signin.js calls -- one key, so checkout signs the buyer in."""
        self.assertIn("setToken(token)", self.signup)
        self.assertIn("setToken", _read("signin.js"))
        self.assertIn("TOKEN_STORAGE_KEY", _read("api.js"))

    def test_the_token_is_shown_once_with_the_save_note(self):
        self.assertIn("save this; it is your login on other devices", self.signup)
        self.assertIn('"data-hook": "signup-token"', self.signup)

    def test_the_buyer_is_routed_to_tonights_card(self):
        self.assertIn('href: "index.html#/today"', self.signup)
        self.assertIn("Go to tonight's card", self.signup)

    def test_a_late_webhook_gets_a_retry_not_a_dead_end(self):
        self.assertIn("signup-retry", self.signup)
        self.assertIn("Check again", self.signup)
        self.assertIn("#/support", self.signup)

    def test_the_session_id_is_removed_from_the_address_bar_after_use(self):
        self.assertIn("replaceState", self.signup)

    def test_main_still_routes_the_success_page(self):
        main = _read("main.js")
        self.assertIn('route === "signup" && rest[0] === "complete"', main)


class BillingLinkIsReachableForSubscribers(unittest.TestCase):
    def setUp(self):
        self.meta = _read("meta.js")

    def test_footer_has_a_billing_link_to_the_billing_view(self):
        self.assertIn('"data-hook": "footer-billing"', self.meta)
        self.assertIn('route("#/billing")', self.meta)

    def test_it_is_shown_only_when_signed_in(self):
        self.assertIn("billingLink.hidden = !getToken()", self.meta)

    def test_it_follows_sign_in_and_sign_out_without_a_reload(self):
        self.assertIn("TOKEN_CHANGED_EVENT", self.meta)
        api = _read("api.js")
        self.assertIn("TOKEN_CHANGED_EVENT", api)
        set_token = api.split("export function setToken(")[1].split("\n}\n")[0]
        clear_token = api.split("export function clearToken(")[1].split("\n}\n")[0]
        self.assertIn("announceTokenChange()", set_token)
        self.assertIn("announceTokenChange()", clear_token)

    def test_the_billing_view_has_the_cancel_button(self):
        self.assertIn('hook: "billing-cancel"', _read("billing.js"))

    def test_the_billing_route_is_wired(self):
        self.assertIn('route === "billing"', _read("main.js"))


class AttributionIsCapturedAndSent(unittest.TestCase):
    def test_landing_stores_the_first_touch(self):
        self.assertIn("captureFirstTouch()", _read("landing.js"))

    def test_first_touch_wins_and_is_in_local_storage(self):
        attr = _read("attribution.js")
        self.assertIn("localStorage", attr)
        self.assertIn("if (Object.keys(existing).length) return existing;", attr)
        for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
            self.assertIn(key, attr)
        self.assertIn("referrer_host", attr)
        self.assertNotIn("document.referrer;", attr.replace(" ", ""),
                         "the full referring URL must never be stored, only its host")

    def test_every_funnel_beacon_carries_the_visitor_id(self):
        api = _read("api.js")
        beacon = api.split("export function trackFunnelEvent(")[1].split("\n}\n")[0]
        self.assertIn("anon_id: getAnonId()", beacon)

    def test_signup_sends_attribution_and_the_beacon_carries_first_touch(self):
        signup = _read("signup.js")
        self.assertIn("attribution: attributionPayload()", signup)
        self.assertIn('trackFunnelEvent("signup_started", firstTouchProperties())', signup)

    def test_the_visitor_id_is_random_not_personal(self):
        attr = _read("attribution.js")
        self.assertIn("getRandomValues", attr)
        self.assertNotIn("email", attr.split("*/", 1)[1])
        self.assertNotIn("userAgent", attr)


class LandingFaqDoesNotPromiseForever(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "landing.html").read_text(encoding="utf-8")

    def test_no_annual_plan_is_gone_and_the_statement_stays_true(self):
        self.assertNotIn("No annual plan", self.html)
        self.assertNotIn("annual", self.html.lower(),
                         "the page has no annual plan, so it should not mention one at all")
        self.assertIn("One monthly plan today", self.html)

    def test_the_landing_proof_promise_still_points_at_the_record_page(self):
        self.assertIn('href="index.html#/record-card"', self.html)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MetaReportsWhetherCheckoutWorks(unittest.TestCase):
    def _meta(self, env):
        from api.meta import get_meta
        with mock.patch.dict(os.environ, env, clear=False):
            for key in list(os.environ):
                if key not in env and key in (
                        "BILLING_PROVIDER", "STRIPE_BETA_PRICE_ID", "PUBLIC_BASE_URL",
                        "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET"):
                    del os.environ[key]
            return get_meta()["billing"]

    def test_off_by_default(self):
        self.assertEqual(self._meta({})["checkout"], "off")

    FULL_ENV = {"BILLING_PROVIDER": "stripe", "STRIPE_BETA_PRICE_ID": "price_x",
                "PUBLIC_BASE_URL": "https://linehound.test", "STRIPE_API_KEY": "sk_test_x",
                "STRIPE_WEBHOOK_SECRET": "whsec_x"}

    def test_on_only_with_provider_key_price_webhook_secret_and_a_return_url(self):
        env = dict(self.FULL_ENV)
        info = self._meta(env)
        self.assertEqual(info["checkout"], "on")
        self.assertEqual(info["trial_days"], 7)
        self.assertEqual(info["price_cents"], 1999)

    def test_switched_on_but_no_price_id_is_unavailable_not_on(self):
        env = {"BILLING_PROVIDER": "stripe", "PUBLIC_BASE_URL": "https://linehound.test"}
        self.assertEqual(self._meta(env)["checkout"], "unavailable")

    def test_switched_on_but_no_return_url_is_unavailable_not_on(self):
        env = {"BILLING_PROVIDER": "stripe", "STRIPE_BETA_PRICE_ID": "price_x"}
        self.assertEqual(self._meta(env)["checkout"], "unavailable")

    def test_each_missing_piece_alone_makes_it_unavailable(self):
        """A real checkout needs ALL of: stripe provider, API key, price id,
        webhook secret, return URL. Missing the API key used to read "on"."""
        for missing in ("STRIPE_API_KEY", "STRIPE_BETA_PRICE_ID",
                        "STRIPE_WEBHOOK_SECRET", "PUBLIC_BASE_URL"):
            env = {k: v for k, v in self.FULL_ENV.items() if k != missing}
            self.assertEqual(self._meta(env)["checkout"], "unavailable", missing)

    def test_a_blank_key_or_secret_is_missing(self):
        for blank in ("STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET"):
            env = dict(self.FULL_ENV, **{blank: "   "})
            self.assertEqual(self._meta(env)["checkout"], "unavailable", blank)

    def test_meta_never_says_which_piece_is_missing(self):
        import json
        from api.meta import get_meta
        env = {k: v for k, v in self.FULL_ENV.items() if k != "STRIPE_WEBHOOK_SECRET"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
            blob = json.dumps(get_meta()["billing"])
        self.assertEqual(sorted(json.loads(blob)), ["checkout", "price_cents", "trial_days"])
        for needle in ("STRIPE", "WEBHOOK", "secret", "whsec", "sk_test", "price_x", "API_KEY"):
            self.assertNotIn(needle, blob)

    def test_provider_is_not_stripe_but_something_else_is_never_on(self):
        env = dict(self.FULL_ENV, BILLING_PROVIDER="somethingelse")
        self.assertNotEqual(self._meta(env)["checkout"], "on")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PollingLoopRunsUnderNode(unittest.TestCase):
    """The success page's polling logic, executed for real: the signup.js
    module is copied into a scratch directory marked as an ES module and its
    exported pollSignupToken is driven with a scripted fetch."""

    SCRIPT = r"""
import { pollSignupToken } from "./signup.js";
import { ApiError } from "./api.js";

const scenarios = JSON.parse(process.env.SCENARIOS);
const out = {};
for (const [name, plan] of Object.entries(scenarios)) {
  let call = 0;
  let clock = 0;
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    const step = plan.responses[Math.min(call, plan.responses.length - 1)];
    call += 1;
    if (step.network) throw new Error("offline");
    return { ok: step.status < 400, status: step.status,
             text: async () => JSON.stringify(step.body || {}) };
  };
  const sleeps = [];
  const result = await pollSignupToken("cs_test/1", {
    intervalMs: 2000, timeoutMs: 60000,
    sleep: async (ms) => { sleeps.push(ms); clock += ms; },
    now: () => clock,
  });
  out[name] = { token: result.token || null, timedOut: !!result.timedOut,
                errorStatus: result.error ? result.error.status : null,
                calls: call, sleeps: sleeps.length, firstUrl: urls[0] };
}
console.log(JSON.stringify(out));
"""

    def _run(self, scenarios):
        with tempfile.TemporaryDirectory() as tmp:
            for path in JS.glob("*.js"):
                shutil.copy(path, tmp)
            Path(tmp, "package.json").write_text('{"type": "module"}', encoding="utf-8")
            Path(tmp, "harness.mjs").write_text(self.SCRIPT, encoding="utf-8")
            env = dict(os.environ, SCENARIOS=json.dumps(scenarios))
            done = subprocess.run(["node", "harness.mjs"], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_polling_contract(self):
        ok = {"status": 200, "body": {"user_id": 3, "token": "tok_live"}}
        not_yet = {"status": 404, "body": {"detail": {"error": "not_found"}}}
        out = self._run({
            "late_webhook": {"responses": [not_yet, not_yet, not_yet, ok]},
            "immediate": {"responses": [ok]},
            "never_lands": {"responses": [not_yet]},
            "flaky_network_then_ok": {"responses": [{"network": True}, not_yet, ok]},
            "server_error": {"responses": [{"status": 500, "body": {"detail": "boom"}}]},
            "bad_request": {"responses": [{"status": 400, "body": {"detail": "bad"}}]},
        })
        # 404 means "not yet": keep asking every 2 s until the token arrives.
        self.assertEqual(out["late_webhook"]["token"], "tok_live")
        self.assertEqual(out["late_webhook"]["calls"], 4)
        self.assertEqual(out["late_webhook"]["sleeps"], 3)
        self.assertEqual(out["immediate"]["calls"], 1)
        self.assertEqual(out["immediate"]["sleeps"], 0)
        self.assertIn("session_id=cs_test%2F1", out["immediate"]["firstUrl"])
        # Never landing gives up at the 60 s deadline (30 polls at 2 s), not
        # forever and not at the first miss.
        self.assertTrue(out["never_lands"]["timedOut"])
        self.assertIsNone(out["never_lands"]["token"])
        self.assertGreaterEqual(out["never_lands"]["calls"], 29)
        self.assertLessEqual(out["never_lands"]["calls"], 31)
        # A dropped connection is retried like a 404.
        self.assertEqual(out["flaky_network_then_ok"]["token"], "tok_live")
        # Any other answer is a real refusal polling will not fix.
        self.assertEqual(out["server_error"]["errorStatus"], 500)
        self.assertEqual(out["server_error"]["calls"], 1)
        self.assertEqual(out["bad_request"]["errorStatus"], 400)


if __name__ == "__main__":
    unittest.main()
