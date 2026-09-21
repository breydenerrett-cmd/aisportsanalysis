"""Structural checks for the sport-level bar and registry (DESIGN_SYSTEM.md
section 3, "Sport level and sub menu").

REWRITTEN 2026-09-15 for the chrome-group redesign (CHR-1/CHR-7/CHR-8).
The old sport switcher (`renderSportSwitcher`, three links plus "Live")
is replaced by one `SPORTS` registry and `renderSportLevel`, which renders
live sports as tabs and exactly two coming-soon sports ("NFL · COMING
SOON", "TENNIS · COMING SOON", D4) as red text links -- never a generic
loop over every `coming_soon` entry, since NBA and NHL (owner addition,
2026-09-15, beyond DESIGN_BUILD_PLAN.json's own CHR-1 text) are also
registered as `coming_soon` but are NOT one of the two shown there, in
the phone sport row, or in the desktop rail heading list (DESIGN_SYSTEM.md
places none of those for NBA/NHL). `#/live` stays reachable only by a
typed URL -- D5, nothing in sport.js links to it any more.

Static text scans only, same "read the file as text, never run a server"
approach as tests/test_web_structure.py -- this repo's whole tests/
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
    """Yield (lineno, line) for lines that are not a `//` line comment or a
    `*`-prefixed block-comment continuation -- same approach as
    tests/test_web_local_time.py's helper of the same name, so doc-comment
    prose that legitimately mentions "#/live" or "renderSportSwitcher" as
    history does not fail a check meant for executable code."""
    path = WEB_JS / name
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        yield i, raw


class SportJsExports(unittest.TestCase):
    def setUp(self):
        self.text = _read("sport.js")

    def test_exports_parseSport(self):
        self.assertIn("export function parseSport", self.text)

    def test_exports_SPORTS_registry(self):
        self.assertIn("export const SPORTS", self.text)

    def test_exports_renderSportLevel(self):
        self.assertIn("export function renderSportLevel", self.text)

    def test_exports_NFL_NOTICE(self):
        # card.js/cardrecord.js (kept on disk, unmodified and unrouted per
        # DESIGN_SYSTEM.md section 6) still import this name directly --
        # it must not be renamed or dropped here.
        self.assertIn("export const NFL_NOTICE", self.text)

    def test_NFL_NOTICE_contains_experimental_notice(self):
        self.assertIn("Experimental selections", self.text)

    def test_renderSportSwitcher_is_deleted(self):
        offenders = [(n, l) for n, l in _non_comment_lines("sport.js") if "renderSportSwitcher" in l]
        self.assertEqual(offenders, [], f"renderSportSwitcher still referenced in code: {offenders}")

    def test_no_live_link_anywhere(self):
        # D5: Live leaves the public chrome. Nothing in sport.js's actual
        # code (doc-comment prose may still explain the history) may build
        # an href pointing at #/live.
        offenders = [(n, l) for n, l in _non_comment_lines("sport.js") if "#/live" in l]
        self.assertEqual(offenders, [], f"sport.js still builds a #/live reference in code: {offenders}")


class SportsRegistryShape(unittest.TestCase):
    """DESIGN_SYSTEM.md section 3: one registry, {key, label, status,
    home, submenu, plan}. MLB, NFL and Tennis are 'live' entries (NFL and
    Tennis since 2026-09-19 -- amended below, this class's docstring
    originally called them "the two D4 names for the red strip", which
    stopped being true the moment both graduated to tabs); NBA and NHL are
    registered (owner addition, 2026-09-15) but stay coming_soon and are
    not shown in the top strip."""

    def setUp(self):
        self.text = _read("sport.js")

    def test_mlb_is_live_with_gameday_home(self):
        self.assertIn('key: "mlb"', self.text)
        self.assertIn('status: "live"', self.text)
        self.assertIn('home: "#/today"', self.text)

    def test_mlb_submenu_has_five_items_hash_immediately_before_label(self):
        # tests/test_whose_record_is_it.py's own regex requires `hash`
        # immediately before `label` on the RESULTS entry -- this is the
        # exact field order sport.js's SPORTS registry must use.
        for pair in (
            '{ hash: "#/today", label: "GAMEDAY"',
            '{ hash: "#/games", label: "MATCHUPS"',
            '{ hash: "#/props", label: "PROPS"',
            '{ hash: "#/record-card", label: "RESULTS"',
            '{ hash: "#/mybets", label: "BETS"',
        ):
            self.assertIn(pair, self.text, f"MLB submenu is missing {pair!r}")

    def test_nfl_is_live_with_its_own_home_and_submenu(self):
        # AMENDED 2026-09-19: NFL went live with a two-item submenu
        # mirroring MLB's field order (hash immediately before label).
        self.assertIn('key: "nfl"', self.text)
        self.assertIn('status: "live"', self.text)
        self.assertIn('home: "#/nfl"', self.text)
        self.assertIn('{ hash: "#/nfl", label: "GAMEDAY"', self.text)
        self.assertIn('{ hash: "#/nfl/record", label: "RESULTS"', self.text)

    def test_tennis_is_live_with_its_own_home(self):
        # AMENDED 2026-09-19: Tennis went live as a research-only board --
        # no pick, slip or record surface, so its own submenu stays a
        # single BOARD entry rather than mirroring MLB's five items.
        self.assertIn('key: "tennis"', self.text)
        self.assertIn('home: "#/tennis"', self.text)
        self.assertIn('{ hash: "#/tennis", label: "BOARD"', self.text)

    def test_nba_and_nhl_are_registered_coming_soon(self):
        # Owner addition beyond DESIGN_BUILD_PLAN.json's CHR-1 task text
        # (2026-09-15): registered so #/nba and #/nhl resolve and other
        # code can read their labels, without being one of the entries in
        # TOP_STRIP_COMING_SOON (see RenderSportLevelBehaviour below).
        self.assertIn(
            'key: "nba", label: "NBA", status: "coming_soon", home: "#/nba"',
            self.text,
        )
        self.assertIn(
            'key: "nhl", label: "NHL", status: "coming_soon", home: "#/nhl"',
            self.text,
        )


class RenderSportLevelBehaviour(unittest.TestCase):
    def setUp(self):
        self.text = _read("sport.js")

    def test_accepts_the_fixed_signature(self):
        self.assertIn(
            'export function renderSportLevel(host, activeSport, '
            '{ placement, linkPrefix = "" } = {})',
            self.text,
        )

    def test_soon_links_are_a_named_list_not_a_generic_filter(self):
        # AMENDED 2026-09-19: the loop that builds the coming-soon links
        # iterates `TOP_STRIP_COMING_SOON`, a literal (currently empty)
        # list -- NFL and TENNIS were that list's only two names until
        # both went live; the mechanism is unchanged (never
        # `SPORTS.filter(coming_soon)`, which would also print NBA/NHL).
        self.assertIn("const TOP_STRIP_COMING_SOON = [];", self.text)
        self.assertIn("for (const key of TOP_STRIP_COMING_SOON)", self.text)
        offenders = [(n, l) for n, l in _non_comment_lines("sport.js") if "SPORTS.filter" in l]
        self.assertEqual(offenders, [], f"sport.js uses SPORTS.filter in code: {offenders}")

    def test_uses_the_sportlevel_component_classes(self):
        # components.css (foundation-owned) already defines this exact
        # component under the comment "sport level bar (sport.js's
        # renderSportLevel)" -- these class names are the fixed contract
        # between the two files.
        for cls in ("sportlevel", "sportlevel__tabs", "sportlevel__tab",
                    "sportlevel__spacer", "sportlevel__soon", "sportlevel__soon-link"):
            self.assertIn(cls, self.text)

    def test_coming_soon_link_text_says_coming_soon(self):
        self.assertIn("COMING SOON", self.text)


class ParseSportBehaviour(unittest.TestCase):
    def setUp(self):
        self.text = _read("sport.js")

    def test_strips_a_leading_mlb_segment(self):
        # DESIGN_SYSTEM.md section 3: "parseSport also strips a leading
        # 'mlb' segment" -- resolved inside the router, not via a second,
        # separate stripping step.
        self.assertIn('first === "mlb"', self.text)

    def test_recognizes_registered_sport_keys(self):
        self.assertIn("SPORTS.some", self.text)


class MainJsSportDispatch(unittest.TestCase):
    """main.js is owned by a different chrome task (CHR-9, built
    concurrently). These assertions are DESIGN_BUILD_PLAN.json's own
    tests_to_update instructions for how main.js must eventually wire
    sport.js's/shell.js's new exports. A failure here while that file is
    still mid-rewrite is an expected concurrent-build state, not a defect
    in sport.js/shell.js/meta.js -- see this build's own report rather
    than editing main.js from this task."""

    def setUp(self):
        self.text = _read("main.js")

    def test_imports_parseSport_from_sport_js(self):
        self.assertIn('from "./sport.js"', self.text)
        self.assertIn("parseSport", self.text)

    def test_no_longer_imports_renderSportSwitcher(self):
        self.assertNotIn("renderSportSwitcher", self.text)

    def test_imports_mountSportLevel_from_shell_js(self):
        self.assertIn("mountSportLevel", self.text)

    def test_no_longer_imports_mountSportSwitcher(self):
        self.assertNotIn("mountSportSwitcher", self.text)

    def test_still_routes_mlb_today(self):
        # renderToday is the router's fallback branch (no "route ===
        # 'today'" literal is required -- MLB with no other route match
        # is the default), so this checks the call is still wired rather
        # than pinning one specific dispatch shape.
        self.assertIn("renderToday", self.text)

    def test_still_routes_existing_mlb_destinations(self):
        for route in ("games", "betcheck", "mybets", "performance", "props", "record-card"):
            self.assertIn(f'route === "{route}"', self.text)


class CardJsNflSupport(unittest.TestCase):
    """NFL is routed and live (2026-09-20). card.js shows the one shared
    experimental notice -- whose sentence is NFL_NOTICE's word for word --
    and must not add a second NFL-only copy: the go-live pass printed the
    same sentence twice in a row at the top of the NFL card."""

    def setUp(self):
        self.text = _read("card.js")

    def test_shows_one_notice_not_two(self):
        self.assertEqual(self.text.count("experimentalNotice()"), 1)
        self.assertNotIn("card-nfl-notice", self.text)


class CardRecordJsNflSupport(unittest.TestCase):
    def setUp(self):
        self.text = _read("cardrecord.js")

    def test_imports_NFL_NOTICE(self):
        self.assertIn('from "./sport.js"', self.text)
        self.assertIn("NFL_NOTICE", self.text)


class LabelsNflExports(unittest.TestCase):
    """Unrelated to this build (labels_nfl.js is untouched by every chrome
    task), kept so this is the one file exercising it at all."""

    def setUp(self):
        self.text = _read("labels_nfl.js")

    def test_contains_kickoff(self):
        self.assertIn("kickoff", self.text.lower())

    def test_exports_NFL_WORDING(self):
        self.assertIn("export const NFL_WORDING", self.text)


if __name__ == "__main__":
    unittest.main()
