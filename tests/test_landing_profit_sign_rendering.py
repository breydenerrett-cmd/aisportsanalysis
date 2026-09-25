"""THE RENDERING TEST THAT MATTERS (task B1, follow-up; extended after
owner review 2026-09-25): reversing a cohort's profit sign must never
change layout, ordering, or visual prominence on the landing page -- only
the glyph (+/-) and a colour. AND, the review's second finding: the
CURRENT and PREVIOUS rule must render through the identical component at
the identical size -- neither may be given prominence for being the one
that happens to be profitable this week.

tests/test_effective_record.py's own ProfitSignReversal class already
proves the sign half at the DATA layer (losing/winning cohorts share
every key, identical shape). This file proves the layer above it: that
web/js/landing.js and web/css/landing.css never turn sign, or role
(current vs previous), into anything a reader would read as "this one is
more prominent" -- bigger text, a different position, a hidden/shown
element, reordering, or an uncoloured figure sitting next to a coloured
one.

OWNER REVIEW, 2026-09-25 -- WHAT CHANGED SINCE THE FIRST VERSION OF THIS
FILE:
  1. `fillProofPanel` (hero) and `fillSportTile` (sport tiles) used to be
     two separate functions, each with its own `unitsNode.classList.add(
     ... ? "is-up" : "is-down")` call site -- TWO sites, pinned below by
     the old EXPECTED_SITES. They are now ONE function, `fillRuleBlock`,
     called identically for the hero panel and every sport tile, for
     BOTH the current and the previous cohort (see `fillRuleSet`). There
     is now exactly ONE such call site, and it is applied to both roles
     -- this file's `IsUpIsDownAreTheOnlySignBranches` class is updated
     to expect one site, not two, and a new class below
     (`CurrentAndPreviousAreSymmetric`) asserts it is reached for BOTH
     roles.
  2. The previous rule used to render as one `<p class="hero__proof-sub">`
     sentence built by `previousRuleSentence` -- no stat cells, no
     colour, visibly smaller than the current rule's three
     `.hero__stat` tiles. `previousRuleSentence` and that asymmetric
     markup are both gone; web/landing.html now carries a SECOND
     `.hero__rule-block` per rule-set (hero and each sport tile) with
     the identical `.hero__proof-grid` of three `.hero__stat` cells,
     in a fixed current-then-previous order -- verified structurally
     below, and live in artifacts/record_ui/*_v2.png (MLB's real
     current, -4.73u red, sits beside its real previous, +7.98u green,
     same size, same shape; NFL's real previous, -0.26u, sits under a
     dash-filled current and is correctly RED, not the uncoloured grey
     the old sentence would have given it).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "web" / "css" / "landing.css").read_text(encoding="utf-8")
JS = (REPO / "web" / "js" / "landing.js").read_text(encoding="utf-8")
HTML = (REPO / "web" / "landing.html").read_text(encoding="utf-8")

# The base rule stack, before any `@media` override. is-up/is-down are only
# ever asserted colour-only in the BASE stylesheet -- a media query is free
# to resize `.hero__stat-value` for a narrow viewport (it does, at 24px for
# mobile), which is a screen-size decision, not a sign decision, and is out
# of scope for this file.
_BASE_CSS = CSS.split("@media", 1)[0]


def _rule_body(css: str, selector: str) -> str:
    """The `{ ... }` body of exactly one CSS rule, by its literal selector
    text (e.g. ".hero__stat-value.is-up"). Fails loudly if the selector
    is missing or duplicated -- a silent `.search` that returns nothing
    would let this test pass on a renamed/removed class."""
    escaped = re.escape(selector)
    matches = re.findall(escaped + r"\s*\{([^}]*)\}", css)
    assert len(matches) == 1, f"expected exactly one rule for {selector!r}, found {len(matches)}"
    return matches[0]


def _block_html(root_html: str, hook: str) -> str:
    """One `<div data-hook="{hook}" ...> ... </div>` block, depth-tracked
    so nested divs (the stat cells) don't truncate it early."""
    marker = f'data-hook="{hook}"'
    start = root_html.index(marker)
    div_start = root_html.rindex("<div", 0, start)
    depth, i = 0, div_start
    while True:
        open_tag = root_html.find("<div", i)
        close_tag = root_html.find("</div>", i)
        if close_tag == -1:
            raise AssertionError(f"unterminated block markup for {hook}")
        if open_tag != -1 and open_tag < close_tag:
            depth += 1
            i = open_tag + 4
        else:
            depth -= 1
            i = close_tag + 6
            if depth == 0:
                return root_html[div_start:i]


def _shape(html: str, *, strip_prefix: str) -> list:
    """A block's structural skeleton: every tag name plus its `class`/
    `data-hook` SUFFIX (the given prefix, e.g. "sport-tile-mlb-current" or
    "sport-tile-mlb-previous", stripped), in document order -- text
    content and the prefix itself (which legitimately differs) are
    ignored; everything about SHAPE is kept."""
    shape = []
    for tag_match in re.finditer(r"<(\w+)([^>]*)>", html):
        tag, attrs = tag_match.groups()
        cls = re.search(r'class="([^"]*)"', attrs)
        hook = re.search(r'data-hook="([^"]*)"', attrs)
        hook_suffix = None
        if hook:
            hook_suffix = re.sub(r"^" + re.escape(strip_prefix), "", hook.group(1))
        shape.append((tag, cls.group(1) if cls else None, hook_suffix))
    return shape


class IsUpIsDownChangeOnlyColour(unittest.TestCase):
    """The only two CSS classes profit sign ever adds to a stat value
    (see IsUpIsDownAreTheOnlySignBranches below) must declare nothing but
    `color`. No font-size, font-weight, transform, order, width or
    padding -- any of those would make one sign visually louder than the
    other, which is the exact thing the owner ruled out."""

    ALLOWED_PROPERTIES = {"color"}

    def _assert_colour_only(self, selector: str):
        body = _rule_body(_BASE_CSS, selector)
        declared = {decl.split(":")[0].strip()
                    for decl in body.split(";") if decl.strip()}
        self.assertEqual(
            declared, self.ALLOWED_PROPERTIES,
            f"{selector} declares {declared - self.ALLOWED_PROPERTIES} beyond colour -- "
            "that would make the winning or losing figure visually louder than the other")

    def test_is_up_is_colour_only(self):
        self._assert_colour_only(".hero__stat-value.is-up")

    def test_is_down_is_colour_only(self):
        self._assert_colour_only(".hero__stat-value.is-down")

    def test_base_stat_value_rule_sets_the_shared_size_weight_and_font(self):
        """The size/weight/font that make W-L, units and nights read as
        one family of numbers lives on the UNCOLOURED base rule
        `.hero__stat-value`, which every stat cell -- current or
        previous -- carries regardless of sign or role, so is-up/is-down
        can only ever recolour something that was already identically
        sized."""
        body = _rule_body(_BASE_CSS, ".hero__stat-value")
        for prop in ("font-size", "font-weight", "line-height"):
            self.assertIn(prop, body, f"{prop} missing from the shared base rule")


class IsUpIsDownAreTheOnlySignBranches(unittest.TestCase):
    """Every place landing.js reads a cohort's `profit_units` sign and
    lets it influence rendering, pinned by exact source text. A change
    here is a change to what sign is allowed to do -- it should force a
    human to re-read this test, not slip through silently.

    ONE site now, not two (see this file's module docstring, point 1):
    `fillRuleBlock` is the single renderer for the hero panel AND every
    sport tile, for BOTH the current and previous cohort."""

    EXPECTED_SITE = 'unitsNode.classList.add(cohort.profit_units >= 0 ? "is-up" : "is-down");'

    def test_the_one_known_site_branches_on_class(self):
        self.assertIn(self.EXPECTED_SITE, JS,
                      f"expected sign-branch site not found verbatim: {self.EXPECTED_SITE!r}")

    def test_no_other_classlist_call_is_conditioned_on_profit_or_sign(self):
        """Every `classList.add`/`classList.toggle` call in the file,
        keyed only to the one pinned site above -- a NEW conditional
        class keyed off wins/losses/profit anywhere else would be exactly
        the kind of "make the favourable one stand out more" regression
        this test exists to catch."""
        calls = re.findall(r"\S*classList\.(?:add|toggle)\([^)]*\);?", JS)
        sign_conditioned = [c for c in calls if "is-up" in c or "is-down" in c]
        self.assertEqual(sign_conditioned, [self.EXPECTED_SITE])

    def test_no_style_width_order_or_hidden_toggle_keyed_to_profit_units(self):
        """Profit sign must never reach `.style`, `.hidden`, DOM
        insertion order, or element creation -- only a CSS class name and
        the +/- glyph. Scans every line that mentions `profit_units` for
        those side effects."""
        forbidden = (".style.", ".hidden", ".order", "insertBefore",
                     "appendChild", "prepend", "remove(")
        offending = []
        for line in JS.splitlines():
            if "profit_units" not in line:
                continue
            if any(token in line for token in forbidden):
                offending.append(line.strip())
        self.assertEqual(offending, [],
                         f"profit-sign-conditioned line touches layout/visibility: {offending}")

    def test_sign_only_ever_selects_a_glyph_or_a_class_never_a_branch_in_control_flow(self):
        """`cohort.profit_units >= 0 ? ... : ...` is a TERNARY expression
        producing a value (a glyph or a class name), never `if (sign
        comparison) { <different DOM> } else { <other DOM> }` control
        flow that could build two different structures. A real if/else
        keyed to the SIGN (a >, <, >= or <= comparison against
        profit_units) would mean the two cases can drift in shape; this
        asserts none exists. `if (typeof ... === "number")` presence
        guards are a different thing (both signs take that branch
        identically) and are not matched."""
        self.assertNotRegex(
            JS, r"if\s*\([^)]*profit_units\s*[<>]=?[^)]*\)\s*\{",
            "an if-statement branches on profit sign -- sign should only "
            "ever pick a glyph/class via a ternary, never fork control flow")


class CurrentAndPreviousAreSymmetric(unittest.TestCase):
    """Owner review, 2026-09-25: "the current rule gets three large
    tiles and the previous rule gets one small grey sentence... Both
    rules must use the same component at the same size... Apply
    is-up/is-down the same way to both cohorts." This class asserts all
    three requirements directly, for the hero panel and every sport tile.
    """

    # (root data-hook, current-role prefix, previous-role prefix)
    RULE_SETS = (
        ("hero-proof", "hero-current", "hero-previous"),
        ("sport-tile-mlb", "sport-tile-mlb-current", "sport-tile-mlb-previous"),
        ("sport-tile-nfl", "sport-tile-nfl-current", "sport-tile-nfl-previous"),
        ("sport-tile-ufc", "sport-tile-ufc-current", "sport-tile-ufc-previous"),
    )

    def test_current_and_previous_blocks_both_exist_in_fixed_order(self):
        """Both blocks are ALWAYS in the markup (never rendered only
        conditionally by JS), and current always precedes previous in
        document order -- the fixed order the owner required, which
        cannot depend on which cohort is winning because it is decided
        by markup position, not by data."""
        for _root_hook, current_prefix, previous_prefix in self.RULE_SETS:
            current_block = f'data-hook="{current_prefix}-block"'
            previous_block = f'data-hook="{previous_prefix}-block"'
            self.assertIn(current_block, HTML, current_prefix)
            self.assertIn(previous_block, HTML, previous_prefix)
            self.assertLess(HTML.index(current_block), HTML.index(previous_block),
                            f"{current_prefix}: current block must precede previous in the markup")

    def test_current_and_previous_blocks_share_the_identical_structural_shape(self):
        """Same tags, same classes, same stat-cell count and order --
        the ONLY difference between the two blocks' shapes is which
        prefix each `data-hook` carries (current vs previous), which is
        stripped before comparing. This is the literal "same component at
        the same size" requirement."""
        for _root_hook, current_prefix, previous_prefix in self.RULE_SETS:
            current_html = _block_html(HTML, f"{current_prefix}-block")
            previous_html = _block_html(HTML, f"{previous_prefix}-block")
            current_shape = _shape(current_html, strip_prefix=current_prefix)
            previous_shape = _shape(previous_html, strip_prefix=previous_prefix)
            self.assertEqual(current_shape, previous_shape,
                             f"{current_prefix} vs {previous_prefix}: block shapes diverge -- "
                             "the previous rule must render through the identical component")

    def test_each_block_carries_exactly_three_stat_cells_in_the_same_order(self):
        """won-lost, units, nights -- the same three, same order, in
        BOTH the current and the previous block, so neither role's block
        can be laid out to give one figure more visual weight."""
        for _root_hook, current_prefix, previous_prefix in self.RULE_SETS:
            for prefix in (current_prefix, previous_prefix):
                html = _block_html(HTML, f"{prefix}-block")
                hooks = re.findall(rf'data-hook="{re.escape(prefix)}-(wl|units|days)"', html)
                self.assertEqual(hooks, ["wl", "units", "days"], prefix)

    def test_only_one_renderer_fills_both_roles(self):
        """`fillRuleBlock` is called for "current" and "previous" from
        the SAME loop (`fillRuleSet`), with no per-role branch choosing a
        different function -- the guarantee that current and previous
        cannot silently diverge in behaviour even if their markup shapes
        match today."""
        self.assertIn("function fillRuleSet(", JS)
        fill_rule_set_body = JS.split("function fillRuleSet(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("fillRuleBlock(", fill_rule_set_body)
        # Exactly one call site inside the loop -- not one branch per role.
        self.assertEqual(fill_rule_set_body.count("fillRuleBlock("), 1,
                         "fillRuleSet calls fillRuleBlock more than once -- "
                         "current and previous should share one call site inside one loop")

    def test_hero_and_mlb_tile_read_the_same_snapshot_object(self):
        """The hero panel used to read a separately-derived
        `meta.card_record` while the MLB tile read
        `meta.effective_record.sports.mlb` -- the exact populations
        mismatch the owner found (73-40 vs 151-79). `fillProofPanel` now
        reads `meta.effective_record.sports.mlb` too, the identical
        object `fillSportTiles` hands the MLB tile, so the two cannot
        disagree by construction."""
        fill_proof_panel = JS.split("async function fillProofPanel()", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("meta.effective_record.sports", fill_proof_panel)
        self.assertIn("mlb", fill_proof_panel)
        self.assertNotIn("meta.card_record", fill_proof_panel,
                         "fillProofPanel still reads the separately-derived card_record "
                         "for its stat cells -- the hero/tile mismatch this guards against "
                         "can reappear")


class SportTilesShareOneMarkupShape(unittest.TestCase):
    """The MLB/NFL/UFC tiles in web/landing.html are separate DOM
    subtrees (different sports, never pooled per B1's own rule), but
    they must be the SAME shape -- same classes, same rule-block count,
    same element order -- regardless of which sport's number happens to
    be positive this week. Verified structurally here; verified live
    (real ledger, real colours) in artifacts/record_ui/."""

    TILE_PREFIXES = ("sport-tile-mlb", "sport-tile-nfl", "sport-tile-ufc")

    def _tile_html(self, prefix: str) -> str:
        return _block_html(HTML, prefix)

    def test_all_three_sport_tiles_have_the_identical_structural_shape(self):
        shapes = {prefix: _shape(self._tile_html(prefix), strip_prefix=prefix)
                 for prefix in self.TILE_PREFIXES}
        mlb_shape = shapes["sport-tile-mlb"]
        for prefix, shape in shapes.items():
            self.assertEqual(shape, mlb_shape,
                             f"{prefix} tile's markup shape diverges from MLB's -- "
                             "one sport's tile must never gain/lose structure vs another's")

    def test_each_tile_carries_both_a_current_and_a_previous_rule_block(self):
        for prefix in self.TILE_PREFIXES:
            html = self._tile_html(prefix)
            self.assertIn(f'data-hook="{prefix}-current-block"', html, prefix)
            self.assertIn(f'data-hook="{prefix}-previous-block"', html, prefix)


class NoPredecessorMeansNoBlockNotDashes(unittest.TestCase):
    """Owner review, 2026-09-25 (second pass): "The UFC tile renders a
    'PREVIOUS RULE (RETIRED)' block full of dashes, but UFC has never had
    a previous rule... An empty 'retired rule' block implies a rule that
    never existed... When `previous` is None or unavailable because no
    predecessor exists, omit the previous block entirely. Keep the
    dashes for the case where a predecessor exists but has no graded
    nights."

    Two cases, covered separately:
      1. NO PREDECESSOR EXISTS AT ALL (UFC -- `effective_record.
         mma_snapshot`'s `previous` is Python `None`, not a cohort
         object). The previous block must be `hidden` -- structurally,
         in the static markup (the honest no-JS/pre-fetch default), and
         by landing.js at runtime whenever `snapshot.previous` is
         null/undefined.
      2. A PREDECESSOR EXISTS BUT IS UNGRADED (MLB/NFL always return a
         real cohort dict for `previous`, even one with
         `grading_state !== "graded"` -- see effective_record.py's
         `_v1_style_cohort`, which never returns `None`). That block
         must stay visible, with dashes and the cohort's own `reason` --
         unchanged from before this review.
    """

    def test_ufcs_previous_block_is_hidden_in_the_static_markup(self):
        """The honest no-JS/pre-fetch default: UFC's previous block
        carries the `hidden` attribute directly in web/landing.html, so
        a visitor who never runs JS (or whose /meta fetch fails) never
        sees a fabricated "previous rule" for the one sport that has
        never had one."""
        block = _block_html(HTML, "sport-tile-ufc-previous-block")
        opening_tag = block.split(">", 1)[0]
        self.assertRegex(opening_tag, r"\bhidden\b",
                         "sport-tile-ufc-previous-block must carry `hidden` in the "
                         "static markup -- UFC has never had a previous rule")

    def test_mlb_and_nfls_previous_blocks_are_not_hidden_in_the_static_markup(self):
        """MLB and NFL both have a real predecessor (V1's frozen rule;
        NFL's retired favourites rule) -- their blocks must NOT carry
        `hidden` in the static markup, or a real previous-rule record
        would be suppressed by default."""
        for prefix in ("sport-tile-mlb", "sport-tile-nfl", "hero"):
            block = _block_html(HTML, f"{prefix}-previous-block")
            opening_tag = block.split(">", 1)[0]
            self.assertNotRegex(opening_tag, r"\bhidden\b", prefix)

    def test_fillRuleSet_hides_the_previous_block_only_when_the_cohort_is_null(self):
        """Pinned by exact source text: the ONLY condition that hides a
        previous block is `!bySlot.previous` (the cohort object itself
        being null/undefined) -- never `available`, never
        `grading_state`. A predecessor that exists but reads
        `available: false` or has an ungraded `grading_state` must NOT
        hit this branch; it must still reach `fillRuleBlock` and render
        with dashes."""
        fill_rule_set = JS.split("function fillRuleSet(root, prefix, snapshot) {", 1)[1]
        fill_rule_set = fill_rule_set.split("\n}\n", 1)[0]
        self.assertIn('role === "previous" && !bySlot.previous', fill_rule_set)
        self.assertIn("blockNode.hidden = true", fill_rule_set)
        # The hide condition must never also check `available` or
        # `grading_state` -- widening it to "unavailable OR ungraded"
        # would hide MLB/NFL's real (but currently ungraded) previous
        # rules too, which the owner explicitly said to keep dash-filled
        # and visible, not omitted.
        hide_branch = fill_rule_set.split('if (role === "previous"', 1)[1].split("continue;", 1)[0]
        self.assertNotIn("available", hide_branch)
        self.assertNotIn("grading_state", hide_branch)

    def test_fillRuleSet_unhides_and_fills_the_block_when_a_predecessor_exists(self):
        """The `else` path of the same hide check: when `bySlot.previous`
        is truthy, the block is explicitly un-hidden
        (`blockNode.hidden = false`) and `fillRuleBlock` is still called
        -- so a predecessor that exists but has not graded a night keeps
        rendering through the normal dashes/reason path, exactly as
        before this review."""
        fill_rule_set = JS.split("function fillRuleSet(root, prefix, snapshot) {", 1)[1]
        fill_rule_set = fill_rule_set.split("\n}\n", 1)[0]
        self.assertIn("blockNode.hidden = false", fill_rule_set)
        self.assertIn("fillRuleBlock(root, `${prefix}-${role}`, bySlot[role], label);",
                     fill_rule_set)

    def test_current_block_is_never_conditionally_hidden(self):
        """Only `role === "previous"` can hide a block -- the current
        role always renders (a sport's active rule is never itself
        absent), so no equivalent `role === "current"` hide branch may
        exist."""
        fill_rule_set = JS.split("function fillRuleSet(root, prefix, snapshot) {", 1)[1]
        fill_rule_set = fill_rule_set.split("\n}\n", 1)[0]
        self.assertNotIn('role === "current" &&', fill_rule_set)


if __name__ == "__main__":
    unittest.main()
