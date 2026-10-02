"""Postseason picks are published, graded and SHOWN, but NOT COUNTED --
owner ruling, registration 11.1 (docs/PREREG_CARD_V2.md lines 1087-1089
and 3203-3205): "its game is a regular-season game (MLB `gameType` `R`,
read from the `game_type` frozen on the pick). Postseason picks are
published, graded and shown on the record, but not counted."

WHY THE FROZEN FIELD IS NOT WHAT CLASSIFIES A PICK HERE. `game_type` is
frozen "R" unconditionally on every prop candidate
(`src/report/card_v2.py:275`) and defaults to "R" on a game candidate
whose dossier carries no `game_type` at all (`card_v2.py:116`) -- see
docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md's E6. Every fixture
below therefore freezes `game_type: "R"` on its postseason entries too
(exactly like the real, buggy frozen field would), and classification
still has to come out right -- proving the RESULTS STORE
(`src.pipeline.history.read_results()`'s own `game_type` column, keyed by
`game_pk`), not the frozen field, is what actually decides.

None of these tests touch a real evidence/*.jsonl file or the real
data/historical/mlb_results.csv -- every ledger and every results store is
built and injected here, the same convention tests/test_effective_record.py
already documents in its own module docstring.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import card_ledger
from src.ledger.chain import HashChainLedger
from src.report import effective_record as er

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

REPO = Path(__file__).resolve().parents[1]


class _TempPathCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _path(self, name):
        return os.path.join(self._tmp.name, name)


# ---------------------------------------------------------------------------
# 1. effective_record.py -- the core split, at the module that owns it
# ---------------------------------------------------------------------------

class V2PostseasonSplit(_TempPathCase):
    """One settled date, three graded V2 entries: a regular-season GAME
    pick, a postseason GAME pick, and a postseason PROP pick frozen with
    `game_type: "R"` (the real bug, reproduced on purpose -- see this
    file's own module docstring). The injected results store is the only
    thing that tells the two games apart."""

    REG_PK = "716001"
    POST_PK = "716999"

    def _snapshot(self):
        v2_path = self._path("cards_v2.jsonl")
        ledger = HashChainLedger(v2_path)
        ledger.append({
            "date": "2026-09-29", "kind": card_ledger.KIND_SETTLED,
            "rule": "DAILY_CARD_BEST_BETS_V2",
            "graded": [
                # Regular season -- COUNTED.
                {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                 "result": "WIN", "profit_units": 0.90,
                 "game_pk": self.REG_PK, "game_type": "R"},
                # Postseason GAME pick -- frozen "R" (the card_v2.py bug),
                # but the results store says "F" (Wild Card). Must be
                # POSTSEASON, not counted.
                {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                 "result": "LOSS", "profit_units": -1.00,
                 "game_pk": self.POST_PK, "game_type": "R"},
                # Postseason PROP pick on the SAME postseason game, also
                # frozen "R" (props are frozen "R" unconditionally --
                # card_v2.py:275). Must ALSO be postseason, via `game_pk`
                # alone, with no reliable frozen field to help it.
                {"kind": "prop", "price_class": "PLUS_MONEY", "entry_class": "pick",
                 "result": "WIN", "profit_units": 1.40, "player": "Some Player",
                 "game_pk": self.POST_PK, "game_type": "R"},
            ],
        })
        results_store = {
            self.REG_PK: {"game_pk": self.REG_PK, "game_type": "R"},
            self.POST_PK: {"game_pk": self.POST_PK, "game_type": "F"},
        }
        snap = er.mlb_snapshot(v1_path=self._path("v1_empty.jsonl"),
                               v2_path=v2_path, results_store=results_store)
        return snap["current"]

    def test_counted_headline_reconciles_exactly_to_the_regular_season_entry(self):
        current = self._snapshot()
        self.assertEqual(current["wins"], 1)
        self.assertEqual(current["losses"], 0)
        self.assertEqual(current["n_staked"], 1)
        self.assertAlmostEqual(current["profit_units"], 0.90, places=6)

    def test_postseason_figure_pools_the_game_and_the_prop_pick(self):
        current = self._snapshot()
        postseason = current["postseason"]
        self.assertEqual(postseason["wins"], 1)   # the prop WIN
        self.assertEqual(postseason["losses"], 1)  # the postseason game LOSS
        self.assertEqual(postseason["n_staked"], 2)
        self.assertAlmostEqual(postseason["profit_units"], 0.40, places=6)
        self.assertEqual(postseason["days"], 1)
        self.assertEqual(postseason["label"], "Postseason (graded, not counted)")

    def test_frozen_game_type_r_never_overrides_the_results_store(self):
        """The specific bug this task exists to route around: every entry
        above is frozen `game_type: "R"`. If classification trusted that
        field alone, `postseason` would read all-zero and the postseason
        game/prop would silently inflate the counted figure instead."""
        current = self._snapshot()
        self.assertGreater(current["postseason"]["n_staked"], 0)
        self.assertEqual(current["wins"] + current["postseason"]["wins"], 2)
        self.assertEqual(current["losses"] + current["postseason"]["losses"], 1)

    def test_market_breakdown_excludes_the_postseason_prop_entirely(self):
        """The counted `market_breakdown` never gained a "prop" kind at
        all -- the only prop entry that graded was postseason, so it
        contributes to nothing counted, not even a zeroed prop slot."""
        current = self._snapshot()
        self.assertNotIn("prop", current["market_breakdown"])
        game = current["market_breakdown"]["game"]
        self.assertEqual((game["wins"], game["losses"]), (1, 0))

    def test_counted_scope_names_the_population(self):
        current = self._snapshot()
        self.assertEqual(current["counted_scope"],
                         "regular season only (registration 11.1)")

    def test_days_is_one_for_both_counted_and_postseason(self):
        """The one settled date has BOTH a counted entry and postseason
        entries -- it counts toward both cohorts' own `days`, never
        double-counted into one figure."""
        current = self._snapshot()
        self.assertEqual(current["days"], 1)
        self.assertEqual(current["postseason"]["days"], 1)


class V2PostseasonFillExcluded(_TempPathCase):
    """A postseason FILL (never a counted pick either way, per 11.1's own
    "fills are never counted picks" rule) must also not inflate the
    COUNTED `fills` figure -- the same "exclude postseason" rule applied
    to the one other counted figure this module reports apart from the
    headline."""

    def test_postseason_fill_excluded_from_counted_fills(self):
        v2_path = self._path("cards_v2.jsonl")
        ledger = HashChainLedger(v2_path)
        ledger.append({
            "date": "2026-09-29", "kind": card_ledger.KIND_SETTLED,
            "rule": "DAILY_CARD_BEST_BETS_V2",
            "graded": [
                {"kind": "game", "price_class": "MAIN", "entry_class": "fill",
                 "result": "WIN", "profit_units": 3.00,
                 "game_pk": "900001", "game_type": "R"},
            ],
        })
        results_store = {"900001": {"game_pk": "900001", "game_type": "D"}}
        snap = er.mlb_snapshot(v1_path=self._path("v1_empty.jsonl"),
                               v2_path=v2_path, results_store=results_store)
        current = snap["current"]
        self.assertEqual(current["fills"]["n_staked"], 0)
        self.assertEqual(current["fills"]["wins"], 0)
        # Still shows up in GROSS grading activity (settled_count), which
        # describes grading, never counting (see effective_record.py's own
        # comment on why settled_count/unresolved_count stay gross).
        self.assertEqual(current["settled_count"], 1)


# ---------------------------------------------------------------------------
# 2. V1's symmetric logic, exercised with a populated picks list (the
# shape every fixture in tests/test_effective_record.py leaves empty --
# see `_v1_postseason_breakdown`'s own docstring on why an empty list is
# the norm there). Proves the V1 path is not a no-op by construction, only
# a no-op on every ledger that has existed so far.
# ---------------------------------------------------------------------------

class V1PostseasonSplitWithPopulatedPicks(_TempPathCase):
    def test_a_postseason_pick_in_v1s_own_picks_list_is_excluded_and_shown_apart(self):
        from tests.test_effective_record import _published_row, _settled_row

        path = self._path("v1.jsonl")
        ledger = HashChainLedger(path)
        # Two game picks published and settled the same night: one
        # regular season (game_pk 1), one postseason (game_pk 2) -- V1
        # never freezes `game_type` at all (not in FROZEN_FIELDS), so
        # classification here can ONLY come from the results store.
        published = ledger.append(_published_row("2026-09-29", rule="R", n_picks=2))
        settled = dict(_settled_row(
            "2026-09-29", published_row_hash=published["row_hash"],
            wins=1, losses=1, profit_units=-0.10))
        settled["picks"] = [
            {"rank": 1, "bet": "reg", "game_pk": 1, "result": "WIN", "profit_units": 0.90},
            {"rank": 2, "bet": "post", "game_pk": 2, "result": "LOSS", "profit_units": -1.00},
        ]
        ledger.append(settled)

        results_store = {"2": {"game_pk": "2", "game_type": "D"}}
        cohort = er._v1_style_cohort(
            sport="mlb", path=path, rule_id="R", filter_rule="R",
            status="current", label="x",
            postseason_pks=er._postseason_game_pks(results_store))

        game = cohort["market_breakdown"]["game"]
        self.assertEqual((game["wins"], game["losses"]), (1, 0))
        self.assertAlmostEqual(game["profit_units"], 0.90, places=6)
        self.assertEqual(cohort["wins"], 1)
        self.assertEqual(cohort["losses"], 0)
        self.assertEqual(cohort["postseason"]["wins"], 0)
        self.assertEqual(cohort["postseason"]["losses"], 1)
        self.assertAlmostEqual(cohort["postseason"]["profit_units"], -1.00, places=6)
        # GROSS -- settled_count counts the grading activity, postseason
        # included (see _v1_style_cohort's own comment); unaffected by the
        # split above.
        self.assertEqual(cohort["settled_count"], 2)


# ---------------------------------------------------------------------------
# 3. api/card.py's V2 record branch -- counted flat fields + postseason
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ApiCardV2ExposesPostseasonSplit(unittest.TestCase):
    """`GET /card/record?rule=v2`'s flat top-level fields must be the
    COUNTED figure, and `postseason`/`counted_scope` must be present --
    wired through `effective_record`'s V2 cohort (api/card.py's own
    comment). Uses the frozen-`game_type`-is-genuinely-non-"R" path
    directly (rather than a results-store injection api/card.py has no
    parameter for) -- `V2PostseasonSplit` above already proves the
    results-store path; this test is about api/card.py's WIRING, not
    reproving classification.
    """

    def setUp(self):
        # GET /card/record is built once per ledger state (api/card.py's
        # _memo_public). This test swaps the ledger FUNCTIONS, not the file,
        # so without a reset it was handed whatever an earlier test in the
        # same process had cached from the real ledger (16 wins, not 1) and
        # passed or failed by the order the modules happened to run in.
        from api import card as card_mod
        from api import meta as meta_mod
        for reset in (card_mod.reset_public_cache_for_tests, meta_mod.reset_record_cache_for_tests):
            reset()
            self.addCleanup(reset)

    def _record_v2_fixture(self):
        blank = {"days": 0, "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
                "n_staked": 0, "profit_units": 0.0, "win_rate": None,
                "roi_pct": None}
        return {"since": None, "until": None, "main": dict(blank),
               "plus_money": dict(blank), "fills": dict(blank),
               "combined": dict(blank), "withdrawn": 0}

    def _history_v2_fixture(self):
        return {
            "days": [
                {"date": "2026-09-29", "graded": [
                    {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                     "result": "WIN", "profit_units": 0.85, "game_type": "R"},
                    {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                     "result": "LOSS", "profit_units": -1.00, "game_type": "F"},
                ]},
            ],
            "total_days": 1, "truncated": False,
        }

    def test_flat_fields_are_counted_and_postseason_key_is_present(self):
        from api import card as card_mod
        with mock.patch("src.appstate.card_ledger.record_v2",
                        return_value=self._record_v2_fixture()), \
             mock.patch("src.appstate.card_ledger.history_v2",
                        return_value=self._history_v2_fixture()):
            payload = card_mod.get_card_record(request=None, sport="mlb", rule="v2")

        # COUNTED: only the regular-season WIN.
        self.assertEqual(payload["wins"], 1)
        self.assertEqual(payload["losses"], 0)
        self.assertAlmostEqual(payload["profit_units"], 0.85, places=6)

        # The NESTED `combined` is untouched -- still the gross figure
        # `record_v2()` itself returned (all-zero in this mock, since the
        # mock never populates it; this only proves it was not silently
        # overwritten by the counted number above).
        self.assertEqual(payload["combined"]["wins"], 0)

        postseason = payload.get("postseason")
        self.assertIsNotNone(postseason)
        self.assertEqual(postseason["losses"], 1)
        self.assertAlmostEqual(postseason["profit_units"], -1.00, places=6)
        self.assertEqual(payload.get("counted_scope"),
                         "regular season only (registration 11.1)")


# ---------------------------------------------------------------------------
# 4. web/js/landing.js -- the postseason line renders only when present
# ---------------------------------------------------------------------------

class LandingRendersThePostseasonLineOnlyWhenPresent(unittest.TestCase):
    """Source-text checks, the same style tests/test_landing_profit_sign_
    rendering.py already uses for this file (no JS runtime in this
    stdlib-only suite)."""

    @classmethod
    def setUpClass(cls):
        cls.js = (REPO / "web" / "js" / "landing.js").read_text(encoding="utf-8")
        cls.html = (REPO / "web" / "landing.html").read_text(encoding="utf-8")

    def _fill_rule_block_body(self):
        body = self.js.split("function fillRuleBlock(")[1]
        return body.split("\nfunction ")[0]

    def test_fill_rule_block_reads_a_dedicated_postseason_hook(self):
        body = self._fill_rule_block_body()
        self.assertIn("${prefix}-postseason", body)

    def test_the_line_is_gated_on_postseason_activity(self):
        """Pinned by exact source text: the ONLY condition that shows the
        postseason line is n_staked or days being positive -- never
        `graded`, never role, never sport."""
        body = self._fill_rule_block_body()
        self.assertIn("postseason.n_staked > 0", body)
        self.assertIn("postseason.days > 0", body)
        self.assertIn(".hidden = true", body)
        self.assertIn(".hidden = false", body)

    def test_uses_the_same_wl_and_units_helpers_as_every_other_figure(self):
        body = self._fill_rule_block_body()
        self.assertIn("cohortWL(postseason)", body)
        self.assertIn("cohortUnitsText(postseason)", body)

    def test_says_graded_not_counted(self):
        body = self._fill_rule_block_body()
        self.assertIn("Graded, not counted.", body)

    def test_every_mlb_rule_block_carries_the_hook_hidden_by_default(self):
        for hook in ("hero-current-postseason", "hero-previous-postseason",
                    "sport-tile-mlb-current-postseason",
                    "sport-tile-mlb-previous-postseason"):
            marker = f'data-hook="{hook}"'
            self.assertIn(marker, self.html, hook)
            # `hidden` on the same element -- the no-JS/pre-fetch default
            # is invisible, exactly like sport-tile-mlb-markets already is.
            tag = re.search(re.escape(marker) + r"[^>]*", self.html)
            self.assertIsNotNone(tag)
            self.assertIn("hidden", tag.group(0), hook)


# ---------------------------------------------------------------------------
# 5. The docs erratum this task appends (docs/CARD_V2_IMPLEMENTATION_
# ERRATUM_2026-09-22.md) -- a light presence check, not a copy-edit test.
# ---------------------------------------------------------------------------

class DocsErratumRecordsTheFrozenFieldLimitation(unittest.TestCase):
    def test_a_new_dated_item_names_the_deferred_fix(self):
        text = (REPO / "docs" / "CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md").read_text(encoding="utf-8")
        self.assertIn("card_v2.py:275", text)
        self.assertIn("card_v2.py:116", text)
        self.assertIn("off-season", text.lower())
        # Earlier items (E1-E5) must survive untouched -- this is an
        # append, never an edit of what came before it.
        self.assertIn("## E1 —", text)
        self.assertIn("## E5 —", text)


if __name__ == "__main__":
    unittest.main()
