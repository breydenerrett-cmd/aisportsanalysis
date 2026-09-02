"""Structural checks on design/linehound-v2/IMPLEMENTATION_MANIFEST.json.

This is NOT a product-behavior test -- it is a build-artifact sanity check
for the machine-readable manifest 3-4 parallel Sonnet workers read to know
which files they own and which fields they may bind to. It asserts
STRUCTURE only (parses, every artboard has a tier and a target file, every
named API endpoint actually exists as a route). Field-name cross-checking
against docs/API_CONTRACTS.md and src/analysis/*payload*.py is a WEAK
check by design -- see the manifest's own governing rule ("every number
appears only if an implementer can trace it to a real field") -- so a miss
is reported via a collected list and a soft assertion at the very end,
never a hard per-field failure, because:
  - some manifest fields are legitimately client-side derivations
    (`count(has_board == true)`, `now - observed_utc`) that will never
    appear as a literal string in either source;
  - some are sourced from api/signup.py, src/appstate/billing.py, or
    src/appstate/customers.py directly, which docs/API_CONTRACTS.md does
    not document today (see that doc's own scope) and which are not in
    src/analysis/ at all.
A hard failure here would either be flaky against harmless doc drift, or
would force fabricating matches -- both worse than reporting misses.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "design" / "linehound-v2" / "IMPLEMENTATION_MANIFEST.json"
API_CONTRACTS_DOC = REPO_ROOT / "docs" / "API_CONTRACTS.md"
API_DIR = REPO_ROOT / "api"
ANALYSIS_DIR = REPO_ROOT / "src" / "analysis"

ROUTE_DECORATOR_RE = re.compile(
    r'@\w+\.(?:get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'
)


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _route_path_to_regex(route: str) -> re.Pattern:
    """Turn a FastAPI route template ('/game/{date}/{away}/{home}') into a
    regex that also matches the manifest's occasional human phrasing of
    the same route with real-looking placeholders, by treating every
    {...} segment as a wildcard path segment."""
    escaped = re.escape(route)
    # re.escape turns "{" into "\{" -- swap each escaped placeholder for a
    # wildcard segment matcher.
    pattern = re.sub(r"\\\{[^}]*\\\}", r"[^/]+", escaped)
    return re.compile(f"^{pattern}$")


def _discover_real_routes() -> set:
    """Every route path declared with an @app.get/post/put/delete/patch(...)
    decorator anywhere under api/*.py, verbatim (with {param} templates
    intact)."""
    routes = set()
    for path in API_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in ROUTE_DECORATOR_RE.finditer(text):
            routes.add(match.group(1))
    return routes


def _endpoint_method_and_path(endpoint: str) -> str:
    """Manifest api_endpoints entries look like 'GET /today',
    'POST /billing/reactivate', or occasionally a bare path or a
    parenthesised note ('GET /signup/complete?session_id=...'). Strip the
    verb and any query string / trailing note; return the path only."""
    text = endpoint.strip()
    text = re.sub(r"^(GET|POST|PUT|DELETE|PATCH)\s+", "", text)
    text = text.split("?", 1)[0]
    text = text.split(" ", 1)[0]
    return text.strip()


class ManifestParsesAndHasStructure(unittest.TestCase):
    """The manifest is valid JSON with the shape workers actually read."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    def test_manifest_file_exists_and_parses(self):
        self.assertTrue(MANIFEST_PATH.exists(), f"missing {MANIFEST_PATH}")
        self.assertIsInstance(self.manifest, dict)

    def test_has_an_artboards_list(self):
        self.assertIn("artboards", self.manifest)
        self.assertIsInstance(self.manifest["artboards"], list)
        self.assertGreater(len(self.manifest["artboards"]), 0)

    def test_artboard_count_matches_the_canvas_footer(self):
        # The .dc.html's own footer says 38 artboards -- see
        # artboard_count_resolution in the manifest for the discrepancy
        # with the freeze commit's "35".
        self.assertEqual(len(self.manifest["artboards"]), 38)

    def test_artboard_count_resolution_is_present_and_explains_the_gap(self):
        resolution = self.manifest.get("artboard_count_resolution")
        self.assertIsInstance(resolution, dict, "manifest must explain 35 vs 38")
        self.assertEqual(resolution.get("physical_artboard_count"), 38)
        self.assertEqual(resolution.get("numbered_slot_count"), 35)
        extras = resolution.get("the_three_extras")
        self.assertIsInstance(extras, list)
        self.assertEqual(len(extras), 3)

    def test_every_artboard_id_is_unique(self):
        ids = [a.get("id") for a in self.manifest["artboards"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate artboard id(s)")

    def test_every_artboard_has_a_tier(self):
        for artboard in self.manifest["artboards"]:
            with self.subTest(artboard=artboard.get("id")):
                self.assertIn("tier", artboard)
                self.assertIn(
                    artboard["tier"], ("A", "B"),
                    f"{artboard.get('id')}: tier must be 'A' or 'B', "
                    f"got {artboard.get('tier')!r}",
                )

    def test_every_artboard_has_at_least_one_target_file(self):
        for artboard in self.manifest["artboards"]:
            with self.subTest(artboard=artboard.get("id")):
                js = artboard.get("target_js_files") or []
                css = artboard.get("target_css_files") or []
                self.assertGreater(
                    len(js) + len(css), 0,
                    f"{artboard.get('id')}: needs at least one target_js_files "
                    f"or target_css_files entry",
                )

    def test_every_artboard_has_required_top_level_keys(self):
        required = {
            "id", "family", "title", "tier", "viewport",
            "dc_html_line_start", "dc_html_line_end", "target_js_files",
            "target_css_files", "api_endpoints", "fields_used",
            "fields_NOT_available", "states_designed", "motion_notes_line",
        }
        for artboard in self.manifest["artboards"]:
            with self.subTest(artboard=artboard.get("id")):
                missing = required - set(artboard.keys())
                self.assertFalse(missing, f"{artboard.get('id')} missing {missing}")

    def test_line_ranges_are_ordered_and_within_the_source_file(self):
        total_lines = self.manifest.get("source_dc_html_total_lines")
        self.assertIsInstance(total_lines, int)
        for artboard in self.manifest["artboards"]:
            with self.subTest(artboard=artboard.get("id")):
                start = artboard["dc_html_line_start"]
                end = artboard["dc_html_line_end"]
                self.assertIsInstance(start, int)
                self.assertIsInstance(end, int)
                self.assertLess(start, end, f"{artboard['id']}: start >= end")
                self.assertGreaterEqual(start, 1)
                self.assertLessEqual(end, total_lines)

    def test_tier_b_artboard_carries_an_explicit_gate_warning(self):
        """The one Tier B artboard (the Ranker / Featured Bet flagship) must
        document the Engine-2 gate in its own entry -- this is the
        highest-risk artboard for a worker to implement against live data
        by mistake, so the manifest must not let that note be optional."""
        tier_b = [a for a in self.manifest["artboards"] if a["tier"] == "B"]
        self.assertEqual(
            len(tier_b), 1,
            f"expected exactly one Tier B artboard, found {[a['id'] for a in tier_b]}",
        )
        artboard = tier_b[0]
        note = (artboard.get("note") or "") + json.dumps(artboard.get("fields_NOT_available", []))
        self.assertIn("Engine 2", artboard.get("note", ""),
                       "Tier B artboard must name the Engine-2 gate explicitly")


class ApiEndpointsExistAsRealRoutes(unittest.TestCase):
    """Every api_endpoints entry must name a route this repo's api/*.py
    actually declares -- a manifest pointing workers at a route that does
    not exist is worse than no manifest."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()
        cls.real_routes = _discover_real_routes()
        cls.real_route_patterns = [
            (route, _route_path_to_regex(route)) for route in cls.real_routes
        ]

    def test_at_least_one_route_was_discovered(self):
        # Sanity check on the discovery regex itself -- if this fails the
        # other assertions in this class are meaningless, not passing.
        self.assertGreater(len(self.real_routes), 10)
        self.assertIn("/today", self.real_routes)
        self.assertIn("/betcheck", self.real_routes)

    def test_every_named_endpoint_matches_a_real_route(self):
        unmatched = []
        for artboard in self.manifest["artboards"]:
            for endpoint in artboard.get("api_endpoints", []):
                path = _endpoint_method_and_path(endpoint)
                if not path.startswith("/"):
                    # A prose note rather than a route (none expected today,
                    # but don't crash the suite if one shows up) -- skip
                    # rather than false-fail on non-route text.
                    continue
                matched = any(pattern.match(path) for _, pattern in self.real_route_patterns)
                if not matched:
                    unmatched.append((artboard["id"], endpoint, path))
        self.assertFalse(
            unmatched,
            "api_endpoints naming a route that does not exist under api/*.py: "
            f"{unmatched}",
        )


class FieldsUsedTraceToADocumentedSource(unittest.TestCase):
    """Weak, report-don't-fail-hard check: every fields_used entry should be
    findable, as a substring, somewhere in docs/API_CONTRACTS.md or
    src/analysis/*payload*.py. This intentionally cannot be a hard
    per-field assertion -- see the module docstring."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()
        corpus_parts = []
        if API_CONTRACTS_DOC.exists():
            corpus_parts.append(API_CONTRACTS_DOC.read_text(encoding="utf-8"))
        for path in sorted(ANALYSIS_DIR.glob("*payload*.py")):
            corpus_parts.append(path.read_text(encoding="utf-8"))
        cls.corpus = "\n".join(corpus_parts)

    def _field_head(self, field: str) -> str:
        """A fields_used entry is often 'field.name (a parenthetical
        explanation)' or 'field_a / field_b'. Reduce to the first
        dotted/bracketed identifier-looking token, which is what we can
        realistically expect verbatim in a contract doc or payload module."""
        token = field.split(" (")[0].split(" -- ")[0].strip()
        token = token.split(" / ")[0].strip()
        token = token.split(",")[0].strip()
        # Strip a leading enum-style "verdict = " / "status = " prefix.
        token = re.split(r"\s*=\s*", token)[0].strip()
        # "quick.top_findings[]" -> "quick.top_findings" (array-suffix is
        # notation, never part of a field's actual name in either source).
        token = token.rstrip("[]")
        # "board_summary.{books,observed_utc,...}" has no single matchable
        # token as written -- fall back to the object prefix before the
        # brace-expansion, which IS how both sources name it.
        if "{" in token:
            token = token.split("{", 1)[0].rstrip(".")
        return token.strip()

    def test_report_field_coverage_without_hard_failure(self):
        misses = []
        checked = 0
        for artboard in self.manifest["artboards"]:
            for field in artboard.get("fields_used", []):
                head = self._field_head(field)
                # Skip prose-only entries with no identifier-like token
                # (e.g. a plain-English description with no field name) --
                # a weak check should not flag sentences as misses.
                if not re.search(r"[A-Za-z_]{3,}", head):
                    continue
                checked += 1
                # A dotted path like "teams.win_pct" -- accept a match on
                # the leaf name too, since the doc may render it as
                # `teams.win_pct` or just `win_pct` in prose.
                candidates = [head]
                if "." in head:
                    candidates.append(head.rsplit(".", 1)[-1])
                if head not in self.corpus and not any(
                    c in self.corpus for c in candidates if c != head
                ):
                    misses.append((artboard["id"], field))
        # Structural assertion only, per the task's instruction: confirm we
        # actually checked a meaningful number of fields (the weak check
        # itself must not silently no-op), then report -- never hard-fail
        # on individual misses.
        self.assertGreater(checked, 50, "field-coverage check saw too few fields to be meaningful")
        if misses:
            print(
                f"\n[test_v2_manifest] fields_used with no substring match in "
                f"docs/API_CONTRACTS.md or src/analysis/*payload*.py "
                f"({len(misses)} of {checked} checked):"
            )
            for artboard_id, field in misses:
                print(f"  - {artboard_id}: {field!r}")


if __name__ == "__main__":
    unittest.main()
