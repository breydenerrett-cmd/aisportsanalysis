"""Every API call must give up and say so. No request may hang forever.

WHAT HAPPENED
-------------
On the evening of 2026-09-10 the owner opened #/today and #/games on his
phone and watched "LOADING THE SLATE" spin for minutes. No error, no retry,
nothing to tell him anything was wrong. His words: "if there's anybody that
has any excitement about what we're doing and then gets to these pages and
the slates aren't loading there's literally no point."

The staging box had stopped answering while still accepting connections.
`fetch` has no default timeout, so the promise never settled -- `dom.js`'s
`renderError`, which handles this case correctly and says "We could not
reach the board", was never reached at all.

**A 503 was never the problem.** That rejects immediately and renders the
error state properly. The silent case is a server holding the socket open
and never writing a response, which is what an overloaded container does
before it dies, and it is the one case an unbounded wait handles worst.

WHAT IS PINNED HERE
-------------------
Not the timeout's exact value -- that is a judgement and may move. What is
pinned is that a bound EXISTS on both halves of a request, because the
failure was silent: no test went red, no function was wrong, and the only
symptom was a customer staring at an animation.

Source-level, against comment-stripped text, for the reason
tests/test_today_one_answer.py gives: these files document their own
failures in prose containing the exact strings under test, so matching raw
text would pass on the documentation.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "web" / "js"


def _code(name):
    """A module's source with comments stripped."""
    text = (JS / name).read_text(encoding="utf-8")
    out, in_block = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("/*"):
            in_block = True
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("//") or s.startswith("*"):
            continue
        out.append(line)
    return "\n".join(out)


class NoRequestMayHangForever(unittest.TestCase):

    def setUp(self):
        self.api = _code("api.js")

    def test_a_timeout_is_declared(self):
        self.assertIn("DEFAULT_TIMEOUT_MS", self.api,
                      "api.js no longer declares a request timeout; a server "
                      "that accepts the connection and never answers will "
                      "spin the skeleton forever again")

    def test_the_timeout_is_a_real_duration(self):
        """A zero or absent value disables the bound while keeping the name."""
        match = re.search(r"DEFAULT_TIMEOUT_MS\s*=\s*(\d+)", self.api)
        self.assertIsNotNone(match, "DEFAULT_TIMEOUT_MS is not a literal")
        millis = int(match.group(1))
        self.assertGreater(millis, 0, "a zero timeout disables the bound")
        self.assertLessEqual(
            millis, 60000,
            "a timeout over a minute is not a timeout as far as a reader on "
            "a phone is concerned -- the owner's complaint was about minutes")

    def test_an_abort_controller_actually_arms_it(self):
        """Declaring a constant is not enforcing it."""
        self.assertIn("AbortController", self.api)
        self.assertIn("controller.abort()", self.api)
        self.assertRegex(self.api, r"signal\s*=\s*controller\.signal",
                         "the controller is built but never attached to the "
                         "request, so aborting it does nothing")

    def test_the_body_read_is_covered_too(self):
        """THE ONE THAT IS EASY TO MISS. A response that sends its status
        line and then stalls leaves `await response.text()` hanging with the
        headers already in hand -- the same spinner, one step later. The
        abort signal covers the body read only because the same controller
        is used for the whole request and `response.text()` is guarded."""
        after_fetch = self.api.split("await fetch(", 1)[-1]
        self.assertIn("await response.text()", after_fetch)
        self.assertRegex(
            after_fetch,
            r"try\s*\{\s*\n\s*text\s*=\s*await response\.text\(\)",
            "response.text() is not inside a try, so a stall there escapes "
            "the timeout handling and reaches the view as an unhandled "
            "rejection instead of a rendered error")

    def test_a_timeout_reports_as_a_network_failure_not_a_status(self):
        """renderError branches on `status`. A timeout must arrive with a
        null status so it renders 'We could not reach the board' rather than
        'Status: undefined' -- and crucially never reads as the server
        answering 'no games'."""
        self.assertRegex(
            self.api, r"timedOut[\s\S]{0,400}?ApiError\(null",
            "a timed-out request must raise ApiError with a null status")

    def test_the_timer_is_cleared_on_every_path(self):
        """A surviving timer would abort a LATER request that reused the
        controller, or keep the page awake on mobile for no reason."""
        self.assertGreaterEqual(
            self.api.count("clearTimeout(timer)"), 2,
            "clearTimeout must run on the failure path and on the success "
            "path; one call means one of them leaks")

    def test_callers_can_override_it(self):
        """A genuinely slower endpoint must be able to ask for more time
        rather than forcing the global bound up for everything."""
        self.assertIn("options.timeoutMs", self.api)
        self.assertRegex(
            self.api, r"delete init\.timeoutMs",
            "timeoutMs is passed straight into fetch(); harmless today but "
            "it is not a fetch option and will confuse the next reader")


class TheErrorStateSaysSomethingTrue(unittest.TestCase):
    """`renderError`'s network branch is what a timeout now reaches."""

    def setUp(self):
        self.dom = _code("dom.js")

    def test_the_network_branch_exists(self):
        self.assertIn("We could not reach the board.", self.dom)

    def test_it_does_not_claim_the_slate_is_empty(self):
        """The distinction the owner cares about: a service outage must not
        read as 'we looked and there is nothing tonight'."""
        self.assertIn("it is not the same as", self.dom)

    def test_the_detail_is_available_without_being_shouted(self):
        self.assertIn("Technical detail", self.dom)


if __name__ == "__main__":
    unittest.main()
