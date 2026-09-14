"""Local-time rewrite (pacific_time track, 2026-09-14) -- static structural
checks, same "read the file as text, never run a server" spirit as
tests/test_web_structure.py.

THE DEFECT THIS FILE NAMES: every clock on the site was hardcoded to
America/New_York and every rendered string appended a literal " ET"
suffix, so a Pacific viewer (the owner) read every first pitch three
hours later than it actually is ("6:40 PM ET" when the game is really
3:40 PM PT). The fix (web/js/dom.js's formatLocalClock/formatLocalDate/
localZoneAbbr, plus every call site that used to append " ET" itself) now
shows each VIEWER their own wall-clock time with their own zone's real
abbreviation, resolved from the browser via Intl -- no zone hardcoded,
falling back to America/Los_Angeles only when Intl itself cannot resolve
one.

WHAT STAYS HARDCODED ON PURPOSE: slate DATE boundaries (which calendar
night a game belongs to) are not a display concern -- they are a join
key. web/js/today.js's `currentEasternDateIso` and web/js/dom.js's
`formatSlateDate` both stay pinned (Eastern calendar / UTC-pinned noon,
respectively) and are the two documented exceptions below.

HOW I KNOW EACH CHECK FAILS ON THE PRE-FIX CODE: every regex/substring
below was extracted directly from grepping the pre-fix files in this same
session (America/New_York inside formatEasternTime/formatEasternClock/
formatEasternDate's own Intl calls; `${clock} ET`-shaped template
literals in web/js/today.js, games.js, odds.js, betcheck.js, states.js,
main.js; the literal phrase "ALL TIMES ET" in web/js/today.js,
web/js/games.js and web/js/meta.js; timeZoneName was never requested
anywhere). Each assertion is the direct negation of something that grep
found in the code before this track's edit.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
JS_DIR = WEB_DIR / "js"

# This track's files (per the orchestrator's file ownership list) plus
# dom.js, which is where the shared helpers live.
OWNED_JS_FILES = [
    "dom.js", "labels.js", "today.js", "games.js", "odds.js", "betcheck.js",
    "meta.js", "states.js", "tiles.js", "main.js", "dayrecap.js", "props.js",
    "recordstrip.js", "matchups.js", "landing-live.js",
]

DOM_JS = JS_DIR / "dom.js"
TODAY_JS = JS_DIR / "today.js"
LANDING_HTML = WEB_DIR / "landing.html"

# A literal " ET" suffix immediately before the string/template literal
# closes -- the exact shape every one of the pre-fix `${clock} ET`
# call sites had (today.js/games.js/odds.js/betcheck.js/states.js/main.js).
LITERAL_ET_SUFFIX = re.compile(r' ET["`\']')

# The other pre-fix pattern: a whole hardcoded header phrase
# (today.js/games.js/meta.js each had this verbatim).
ALL_TIMES_ET_PHRASE = "ALL TIMES ET"


def _non_comment_lines(path: Path):
    """Yield (lineno, line) for lines that are not a `//` line comment or
    a `*`-prefixed block-comment continuation -- this codebase's block
    comments consistently open with `/**`/`/*` and prefix every following
    line with ` * ` (see web/js/dom.js, games.js, etc. throughout), so
    stripping lines whose lstripped text starts with `//` or `*` removes
    comment prose (including this file's own historical "used to append
    a literal \" ET\"" notes) without needing a real JS parser.
    """
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        yield i, raw


class NoHardcodedEasternInDisplayHelpers(unittest.TestCase):
    """dom.js's shared clock/date helpers must resolve the viewer's own
    zone via Intl, never hardcode America/New_York."""

    def test_dom_js_defines_local_time_helpers(self):
        src = DOM_JS.read_text(encoding="utf-8")
        for name in ("resolveDisplayTimeZone", "formatLocalClock", "formatLocalDate", "localZoneAbbr"):
            self.assertIn(name, src, f"dom.js must define {name}")

    def test_local_time_helpers_resolve_zone_from_intl_not_a_hardcoded_zone(self):
        src = DOM_JS.read_text(encoding="utf-8")
        self.assertIn("Intl.DateTimeFormat().resolvedOptions().timeZone", src,
            "the viewer's zone must come from the browser's own Intl resolution")
        # The only allowed hardcoded zone anywhere in dom.js is the
        # documented Pacific fallback for when Intl cannot resolve one at
        # all -- never America/New_York (the old bug) as a display zone.
        self.assertIn('"America/Los_Angeles"', src,
            "the no-zone-resolvable fallback must be the owner's own zone, Pacific")

    def test_dom_js_has_no_hardcoded_america_new_york_in_code(self):
        # Pre-fix, formatEasternTime/formatEasternClock/formatEasternDate
        # each had `timeZone: "America/New_York"` as executable code. This
        # asserts none remains outside of comment prose.
        offenders = [(n, l) for n, l in _non_comment_lines(DOM_JS) if "America/New_York" in l]
        self.assertEqual(offenders, [], f"dom.js still hardcodes America/New_York in code: {offenders}")

    def test_format_local_clock_requests_short_zone_name(self):
        src = DOM_JS.read_text(encoding="utf-8")
        # Slice out just the formatLocalClock function body.
        match = re.search(r"function formatLocalClock\(isoUtc\) \{.*?\n\}", src, re.DOTALL)
        self.assertIsNotNone(match, "formatLocalClock must exist in dom.js")
        body = match.group(0)
        self.assertIn('timeZoneName: "short"', body,
            "formatLocalClock must ask Intl for the zone abbreviation (timeZoneName: short)")

    def test_old_export_names_kept_as_aliases_for_the_other_track(self):
        # web/js/card.js and web/js/cardrecord.js (owned by the other
        # track) import formatEasternTime/formatEasternClock directly --
        # this track must not rename or remove them.
        src = DOM_JS.read_text(encoding="utf-8")
        self.assertIn("export function formatEasternTime(isoUtc)", src)
        self.assertIn("export function formatEasternClock(isoUtc)", src)
        card_js = (JS_DIR / "card.js").read_text(encoding="utf-8")
        self.assertIn("formatEasternTime", card_js,
            "card.js (owned by another track) still calls formatEasternTime unmodified")


class NoLiteralEtSuffixInRenderedStrings(unittest.TestCase):
    """No file this track owns may compose a rendered string that
    hardcodes the Eastern abbreviation -- every clock now carries its own
    viewer-resolved zone abbreviation already."""

    def test_no_owned_js_file_appends_a_literal_et_suffix(self):
        for name in OWNED_JS_FILES:
            path = JS_DIR / name
            offenders = [(n, l) for n, l in _non_comment_lines(path) if LITERAL_ET_SUFFIX.search(l)]
            self.assertEqual(offenders, [],
                f"{name} still composes a literal ' ET' suffix in code: {offenders}")

    def test_no_owned_js_file_hardcodes_all_times_et_header(self):
        for name in OWNED_JS_FILES:
            path = JS_DIR / name
            offenders = [(n, l) for n, l in _non_comment_lines(path) if ALL_TIMES_ET_PHRASE in l]
            self.assertEqual(offenders, [],
                f"{name} still hardcodes the literal phrase 'ALL TIMES ET': {offenders}")

    def test_landing_html_has_no_literal_et_suffix(self):
        # landing.html's hero__vs-time node is a static placeholder that
        # landing-live.js (formatEasternTime -> the local-time alias)
        # overwrites on load; pre-fix it hardcoded "7:40pm ET" in markup.
        text = LANDING_HTML.read_text(encoding="utf-8")
        offenders = [ln for ln in text.splitlines() if LITERAL_ET_SUFFIX.search(ln) or ALL_TIMES_ET_PHRASE in ln]
        self.assertEqual(offenders, [], f"landing.html still hardcodes an ET suffix: {offenders}")


class SlateDateBoundaryStaysOnEasternCalendarOnPurpose(unittest.TestCase):
    """The one documented, intentional exception: a slate DATE key is not
    a displayed clock, so it is not part of this rewrite."""

    def test_current_eastern_date_iso_is_the_only_remaining_hardcoded_zone(self):
        # today.js's currentEasternDateIso deliberately still reads
        # America/New_York -- it answers "which slate does the reader's
        # right-now belong to", a join key against GET /today's own UTC
        # calendar date, not a clock a viewer reads. Every OTHER occurrence
        # of a hardcoded zone in this track's files must be gone.
        today_offenders = [(n, l) for n, l in _non_comment_lines(TODAY_JS) if "America/New_York" in l]
        self.assertEqual(len(today_offenders), 1,
            f"expected exactly one hardcoded-zone line (currentEasternDateIso), found: {today_offenders}")
        lineno, line = today_offenders[0]
        self.assertIn('timeZone: "America/New_York"', line)

        src = TODAY_JS.read_text(encoding="utf-8")
        fn_match = re.search(r"function currentEasternDateIso\(\)[\s\S]*?\n\}", src)
        self.assertIsNotNone(fn_match, "currentEasternDateIso must still exist in today.js")
        start_line = src[: fn_match.start()].count("\n") + 1
        end_line = src[: fn_match.end()].count("\n") + 1
        self.assertTrue(start_line <= lineno <= end_line,
            "the one remaining hardcoded America/New_York must live inside currentEasternDateIso "
            "(the slate date-key helper), not some other display path")

    def test_other_owned_files_never_hardcode_america_new_york(self):
        for name in OWNED_JS_FILES:
            if name == "today.js":
                continue  # covered above -- its one exception is checked separately
            path = JS_DIR / name
            offenders = [(n, l) for n, l in _non_comment_lines(path) if "America/New_York" in l]
            self.assertEqual(offenders, [], f"{name} hardcodes America/New_York: {offenders}")


if __name__ == "__main__":
    unittest.main()
