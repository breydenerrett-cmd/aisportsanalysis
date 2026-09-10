"""The rickroll must be impossible to trigger by accident.

WHY THIS FILE EXISTS
---------------------
web/js/gotcha.js is a joke for one person: it says "GUARANTEED", "LOCK OF
THE DAY", "+EV", "FREE MONEY" and prints a fake 99.7% win probability --
every one of which tests/test_customer_language.py bans outright, because
they are the exact claims this product refuses to make. That is the joke.
Jacob has spent two days reading copy that religiously refuses all of it.

So the language scanner skips this ONE file by name. That exemption is a
hole, and this file is the price of it: the guard is not weakened, it is
narrowed to a file that provably cannot reach anyone who has not been sent
a specific link.

The real risk is not the vocabulary. It is that founding-beta outreach
starts this week, and a stranger's first impression of this product must
never be an undismissable interstitial. These tests exist so that stays
true after somebody edits this in six months, and so the joke can be
deleted cleanly when it stops being funny.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOTCHA_JS = REPO / "web" / "js" / "gotcha.js"
GOTCHA_CSS = REPO / "web" / "css" / "gotcha.css"
MAIN_JS = REPO / "web" / "js" / "main.js"
INDEX = REPO / "web" / "index.html"
LANDING = REPO / "web" / "landing.html"


def _code(path):
    """Source with comments stripped. gotcha.js documents its own trigger at
    length, naming the parameter repeatedly -- a raw scan would pass on the
    docstring while the code did something else entirely."""
    text = path.read_text(encoding="utf-8")
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


class ItCannotFireByAccident(unittest.TestCase):

    def setUp(self):
        self.code = _code(GOTCHA_JS)

    def test_there_is_exactly_one_trigger_and_it_is_an_exact_route_match(self):
        self.assertIn("GOTCHA_ROUTE", self.code)
        self.assertTrue(
            re.search(r"routeFromLocation\(\)\s*!==\s*GOTCHA_ROUTE", self.code),
            "the overlay does not gate on an exact hash-route match")

    def test_the_slug_does_not_announce_itself(self):
        """It was `?gotcha=jacob` first, which gave the whole thing away in
        the URL bar. The slug has to read like a real deep link, because the
        entire audience is one person who will look at it."""
        route = re.search(r'GOTCHA_ROUTE\s*=\s*"([^"]+)"', self.code)
        self.assertIsNotNone(route, "no GOTCHA_ROUTE constant")
        slug = route.group(1).lower()
        for tell in ("gotcha", "prank", "joke", "rick", "troll", "jacob",
                     "roll"):
            self.assertNotIn(
                tell, slug,
                f"the trigger slug {slug!r} contains {tell!r} -- it is "
                f"visible in the address bar before he clicks")

    def test_the_route_is_matched_whole_not_as_a_prefix(self):
        """A prefix match would fire on any hash that merely starts with the
        slug, which is a wider door than intended."""
        self.assertIn("!==", self.code)
        self.assertNotIn("startsWith(GOTCHA_ROUTE)", self.code)
        self.assertNotIn("indexOf(GOTCHA_ROUTE)", self.code)

    def test_no_time_or_chance_based_trigger(self):
        """A timer, a random roll or an nth-visitor counter would make this
        something that happens TO people rather than something one person is
        sent."""
        for banned in ("Math.random", "setInterval", "Date.now",
                       "getTime()", "navigator.userAgent"):
            self.assertNotIn(
                banned, self.code,
                f"gotcha.js references {banned!r} -- the trigger must be the "
                f"link and nothing else")

    def test_nothing_is_persisted(self):
        """A stored flag would re-fire on a later visit, when the joke has
        stopped being funny and he is trying to actually use the site."""
        for store in ("localStorage", "sessionStorage", "document.cookie",
                      "indexedDB"):
            self.assertNotIn(
                store, self.code,
                f"gotcha.js writes to {store} -- it would fire again on a "
                f"visit that carries no token")

    def test_it_returns_false_without_doing_anything(self):
        """The early return must come before any DOM is touched, or a
        mis-typed URL leaves debris on a real page."""
        body = self.code.split("export function maybeGotcha", 1)[1]
        guard = body.find("return false")
        first_dom = min(
            (i for i in (body.find("document.body"),
                         body.find("classList.add"),
                         body.find("appendChild")) if i != -1),
            default=-1)
        self.assertGreater(guard, 0, "no early return in maybeGotcha")
        self.assertLess(guard, first_dom,
                        "maybeGotcha touches the DOM before deciding whether "
                        "the token matched")

    def test_it_is_always_escapable(self):
        """A bit, not a trap. The dismiss button dodges twice and then
        works, and Escape works from the reveal onward."""
        self.assertIn("Escape", self.code)
        self.assertIn("dodges >= 2", self.code,
                      "the dodging dismiss button never relents")

    def test_the_landing_page_never_loads_it(self):
        """The marketing page is what a stranger from outreach hits. The
        joke lives only behind the app shell."""
        self.assertNotIn("gotcha", LANDING.read_text(encoding="utf-8"),
                         "the marketing page references the rickroll")


class ItIsCleanlyDeletable(unittest.TestCase):
    """When it stops being funny it should come out in one commit without
    touching a real surface."""

    def test_it_is_checked_on_hashchange_too_not_only_at_boot(self):
        """The most likely path is: he already has the site open, Brey sends
        the link, he taps it. That changes the hash without reloading, so a
        boot-only check would silently do nothing in exactly the case the
        prank is designed for."""
        main = _code(MAIN_JS)
        self.assertEqual(
            2, main.count("maybeGotcha()"),
            "maybeGotcha is not wired into both boot() and the hashchange "
            "listener")

    def test_only_main_js_references_it(self):
        offenders = []
        for path in sorted((REPO / "web" / "js").glob("*.js")):
            if path.name in ("gotcha.js", "main.js"):
                continue
            if "gotcha" in path.read_text(encoding="utf-8").lower():
                offenders.append(path.name)
        self.assertEqual([], offenders,
                         f"{offenders} reference the joke; it should be "
                         f"reachable only from main.js's boot()")

    def test_its_styles_are_fully_scoped(self):
        """Every selector must be under .gotcha* (or the html.gotcha-on
        scroll lock), so the stylesheet cannot affect a real screen even
        while it is loaded."""
        css = GOTCHA_CSS.read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        selectors = []
        for block in re.findall(r"([^{}]+)\{", css):
            for sel in block.split(","):
                sel = sel.strip()
                if not sel or sel.startswith(("@", "to", "from", "%")) \
                        or re.match(r"^\d", sel):
                    continue
                selectors.append(sel)
        stray = [s for s in selectors if ".gotcha" not in s]
        self.assertEqual([], stray,
                         f"unscoped selectors in gotcha.css: {stray}")


class TheLanguageExemptionIsNarrow(unittest.TestCase):

    def test_the_scanner_skips_exactly_one_file(self):
        from tests import test_web_structure as tws
        skipped = getattr(tws, "JOKE_FILES", None)
        self.assertIsNotNone(
            skipped,
            "test_web_structure.py has no declared exemption list; the joke "
            "file's banned vocabulary should be exempted by NAME, never by "
            "loosening the word list")
        self.assertEqual({"gotcha.js"}, set(skipped),
                         "the language exemption covers more than the joke")

    def test_the_real_guard_still_has_its_full_word_list(self):
        """Belt and braces: the exemption must not have been implemented by
        quietly dropping words instead."""
        from tests import test_customer_language as tcl
        from tests import test_web_structure as tws
        self.assertIs(tws.NoBannedCustomerVocabulary.HARD_BANNED,
                      tcl.HARD_BANNED)


if __name__ == "__main__":
    unittest.main()
