"""The chrome group's own redesign tests for sport.js/shell.js/meta.js
(DESIGN_BUILD_PLAN.json tasks CHR-1, CHR-7, CHR-8; DESIGN_SYSTEM.md
section 3, "The shell").

Created by this build (it did not exist before) -- see this task's own
instructions: "create it if the plan owns it and it does not exist:
assertions for renderSportLevel, the SPORTS registry including nfl,
tennis, nba and nhl as coming soon per the owner's 2026-09-15 decision
that NBA and NHL are added as coming soon, no #/live link in sport.js,
and the footer SUMMARY."

Some overlap with tests/test_web_sport_routes.py is deliberate: that file
is the pre-existing, plan-owned NFL-wiring test this build updates in
place; this file is the new, redesign-specific one the task asks for by
name. Static text scans only, matching the rest of tests/ -- this repo's
suite has no JS execution harness.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"


def _read(name: str) -> str:
    return (WEB_JS / name).read_text(encoding="utf-8")


def _non_comment_lines(name: str):
    """Same helper as tests/test_web_local_time.py and
    tests/test_web_sport_routes.py -- strips `//` and `*`-prefixed block-
    comment continuation lines so doc-comment prose does not trip a check
    meant for executable code."""
    path = WEB_JS / name
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        yield i, raw


class SportsRegistryIncludesFourComingSoonSports(unittest.TestCase):
    """Owner addition, 2026-09-15 (beyond DESIGN_BUILD_PLAN.json's CHR-1
    task text): "the SPORTS registry also carries nba and nhl with status
    coming_soon and homes #/nba and #/nhl."

    AMENDED 2026-09-19: NFL and Tennis went live (docs/DESIGN_SYSTEM.md
    section 3 amendment) -- this class's name is now stale (only two
    sports are coming_soon, not four) but is kept rather than renamed so
    this file's own history stays legible; its two NFL/Tennis assertions
    are replaced with the live-status equivalents rather than deleted."""

    def setUp(self):
        self.text = _read("sport.js")

    def test_registry_is_exported(self):
        self.assertIn("export const SPORTS", self.text)

    def test_mlb_live(self):
        self.assertIn('key: "mlb"', self.text)
        self.assertIn('status: "live"', self.text)

    def test_nfl_live(self):
        self.assertIn(
            'key: "nfl",\n    label: "NFL",\n    status: "live",\n    home: "#/nfl"',
            self.text,
        )

    def test_tennis_live(self):
        self.assertIn(
            'key: "tennis",\n    label: "Tennis",\n    status: "live",\n    home: "#/tennis"',
            self.text,
        )

    def test_nba_coming_soon(self):
        self.assertIn(
            'key: "nba", label: "NBA", status: "coming_soon", home: "#/nba"',
            self.text,
        )

    def test_nhl_coming_soon(self):
        self.assertIn(
            'key: "nhl", label: "NHL", status: "coming_soon", home: "#/nhl"',
            self.text,
        )


class TopStripShowsNoComingSoonLinksToday(unittest.TestCase):
    """Decision 4 (SITE_REDESIGN_2026-09-15.md) originally read: "Top
    right, in red: 'NFL · COMING SOON' and 'TENNIS · COMING SOON'."
    AMENDED 2026-09-19: both graduated to live tabs, so the strip's
    coming-soon list (`TOP_STRIP_COMING_SOON`) is empty today. NBA/NHL
    stay registered `coming_soon` but are still not one of that list's
    entries -- DESIGN_SYSTEM.md never places them in the phone sport row
    or the desktop rail heading list either, so renderSportLevel must not
    loop generically over every coming_soon entry (that would surface
    NBA/NHL the moment either is registered, which is not what D6 asked
    for)."""

    def setUp(self):
        self.text = _read("sport.js")

    def test_renderSportLevel_is_exported_with_the_fixed_signature(self):
        self.assertIn("export function renderSportLevel", self.text)
        self.assertIn(
            'renderSportLevel(host, activeSport, { placement, linkPrefix = "" } = {})',
            self.text,
        )

    def test_the_soon_links_are_a_named_list_not_a_generic_filter(self):
        self.assertIn("const TOP_STRIP_COMING_SOON = [];", self.text)
        self.assertIn("for (const key of TOP_STRIP_COMING_SOON)", self.text)
        # A generic filter would read SPORTS for every coming_soon entry and
        # render a link for each one registered, not the named list -- code
        # only, since this file's own doc comments now explain (in prose)
        # why that pattern is avoided, which legitimately names it.
        offenders = [(n, l) for n, l in _non_comment_lines("sport.js") if "SPORTS.filter" in l]
        self.assertEqual(offenders, [], f"sport.js uses SPORTS.filter in code: {offenders}")

    def test_live_sports_render_as_tabs(self):
        self.assertIn('status !== "live"', self.text)
        self.assertIn("sportlevel__tab", self.text)

    def test_nfl_and_tennis_are_live_not_in_the_coming_soon_list(self):
        # The literal pair must not appear as a CODE list any more -- they
        # graduated to tabs (SportsRegistryIncludesFourComingSoonSports.
        # test_nfl_live/test_tennis_live above). Doc comments are allowed to
        # keep naming the pair as history (this file's own amendment note
        # does exactly that), so this checks code lines only.
        offenders = [(n, l) for n, l in _non_comment_lines("sport.js") if '["nfl", "tennis"]' in l]
        self.assertEqual(offenders, [], f"sport.js still uses [\"nfl\", \"tennis\"] as a code list: {offenders}")


class LiveLeavesThePublicChrome(unittest.TestCase):
    """D5: "#/live stays reachable by URL for internal testing" -- but
    nothing in the shared chrome links to it. sport.js is the module that
    used to render the "Live" link; it must carry none now."""

    def test_sport_js_has_no_live_link(self):
        offenders = [(n, l) for n, l in _non_comment_lines("sport.js") if "#/live" in l or '"Live"' in l]
        self.assertEqual(offenders, [], f"sport.js still references #/live or \"Live\" in code: {offenders}")

    def test_shell_js_has_no_live_link(self):
        offenders = [(n, l) for n, l in _non_comment_lines("shell.js") if "#/live" in l]
        self.assertEqual(offenders, [], f"shell.js still references #/live in code: {offenders}")


class ShellStatusLineTargetsTheHeaderNotTheStrip(unittest.TestCase):
    """DESIGN_SYSTEM.md section 3, "Status line": "It lives in the page
    header, not the strip" -- setShellStatus now reads/writes
    [data-hook='page-status'] (layout.js's pageHeader()), not the old,
    permanent [data-hook='board-status'] strip node."""

    def setUp(self):
        self.text = _read("shell.js")

    def test_keeps_setShellStatus_exact_signature(self):
        self.assertIn("export function setShellStatus(text, options = {})", self.text)

    def test_keeps_setShellStatusFromStaleness_exported_by_name(self):
        # games.js imports this by name -- it must not be renamed.
        self.assertIn("export function setShellStatusFromStaleness", self.text)

    def test_targets_the_page_header_status_node(self):
        self.assertIn("page-status", self.text)
        # "board-status" is still mentioned in doc-comment prose explaining
        # what changed and why -- the check is that no *code* line reads
        # or writes that old hook any more.
        offenders = [(n, l) for n, l in _non_comment_lines("shell.js") if "board-status" in l]
        self.assertEqual(offenders, [], f"shell.js still references the old board-status hook in code: {offenders}")

    def test_stale_threshold_is_not_a_flat_ninety_minutes(self):
        # The old STALE_AFTER_SECONDS = 900 (15 min) / any single flat
        # constant is replaced by a game-hours-aware pair matching the
        # real ~13/60-minute capture cadence (forward-capture.yml,
        # capture_slot.sh), not one flat number applied regardless of
        # whether a first pitch is close.
        self.assertNotIn("STALE_AFTER_SECONDS", self.text)
        self.assertIn("STALE_GAME_HOURS_SECONDS", self.text)
        self.assertIn("STALE_QUIET_HOURS_SECONDS", self.text)

    def test_mountSportLevel_replaces_mountSportSwitcher(self):
        self.assertIn("export function mountSportLevel", self.text)
        offenders = [(n, l) for n, l in _non_comment_lines("shell.js")
                     if "mountSportSwitcher" in l or "renderSportSwitcher" in l]
        self.assertEqual(offenders, [], f"shell.js still calls the old switcher functions in code: {offenders}")

    def test_mounts_into_the_shared_sport_level_host_hook(self):
        self.assertIn("sport-level-host", self.text)


class FooterSummaryMatchesTheRedesign(unittest.TestCase):
    """DESIGN_SYSTEM.md section 5's replacement table (shell-07): the old
    "Three to five bets a day, frozen before first pitch and graded
    after" overclaim is replaced."""

    def setUp(self):
        self.text = _read("meta.js")

    def test_summary_constant_exists_with_the_new_wording(self):
        self.assertIn(
            "Beta. Every pick here is part of an ongoing test — published "
            "before each game and graded as it stood at its lock, win or "
            "lose. This is analysis, not advice. Nothing here is a "
            "guarantee; bet at your own risk.",
            self.text,
        )

    def test_old_overclaim_language_is_gone_from_the_summary_constant(self):
        self.assertNotIn("frozen before first pitch and graded", self.text)

    def test_play_responsibly_stays_uppercase_in_source(self):
        # tests/test_shared_footer.py pins this case-sensitively too --
        # duplicated here since this file is the redesign-specific check
        # the task asked for by name ("the footer SUMMARY").
        self.assertIn("PLAY RESPONSIBLY", self.text)


if __name__ == "__main__":
    unittest.main()
