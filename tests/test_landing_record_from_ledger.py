"""The landing page's record sentence reads the ledger, not a typed figure.

On 2026-09-12 web/landing.html said "2 wins, 1 loss. A second night has
graded since -- 9 picks, 7 wins, 2 losses. Across both: 9 wins, 3 losses."
True that morning; wrong the morning after the next settlement, on the page
whose pitch is that it counts honestly. The research count drifted the same
way (tests/test_research_count_is_computed.py). GET /meta now carries
`card_record` from src/appstate/card_ledger.record(), landing.js fills the
hook, and the markup's no-JS fallback names NO figure -- a sentence with no
number in it cannot go stale.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class TheLandingFallbackNamesNoFigure(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "landing.html").read_text(encoding="utf-8")

    def test_the_hook_exists_once(self):
        self.assertEqual(self.html.count('data-hook="card-record"'), 1)

    def test_the_fallback_carries_no_running_total(self):
        fallback = re.search(r'data-hook="card-record"[^>]*>([^<]*)<', self.html)
        self.assertIsNotNone(fallback)
        text = fallback.group(1)
        self.assertNotRegex(text, r"\d", f"a figure in the no-JS fallback goes stale: {text!r}")
        self.assertIn("record page", text.lower())

    def test_no_typed_running_record_survives_anywhere_on_the_page(self):
        """The exact shape that drifted: "N wins, M losses" outside the
        first-night sentence (which is a dated historical fact)."""
        body = re.sub(r"<!--.*?-->", " ", self.html, flags=re.S)
        body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        hits = [m.group(0) for m in re.finditer(r"\b\d+ wins?, \d+ loss(?:es)?\b", body)]
        self.assertEqual(hits, ["2 wins, 1 loss"],
                         "a running record is typed into the page; it belongs on /meta")


class LandingJsFillsItFromMeta(unittest.TestCase):
    def setUp(self):
        self.js = (WEB / "js" / "landing.js").read_text(encoding="utf-8")

    def test_it_reads_the_hook_and_meta(self):
        body = self.js.split("async function fillCardRecord(")[1].split("\nfunction ")[0]
        self.assertIn("[data-hook='card-record']", body)
        self.assertIn("meta.card_record", body)
        self.assertIn("fetchMeta()", body)

    def test_boot_calls_it(self):
        boot = self.js.split("function boot() {")[1]
        self.assertIn("fillCardRecord();", boot)

    def test_the_sentence_refuses_partial_records(self):
        """A null from /meta (unreadable ledger) must leave the fallback:
        the guard has to check every figure it prints, and days >= 1."""
        body = self.js.split("export function recordSentence(")[1].split("\n}\n")[0]
        for field in ("rec.wins", "rec.losses", "rec.days"):
            self.assertIn(f'typeof {field} !== "number"', body)
        self.assertIn("rec.days < 1", body)
        self.assertIn("return null", body)

    def test_the_sentence_reports_losses_and_voids(self):
        body = self.js.split("export function recordSentence(")[1].split("\n}\n")[0]
        self.assertIn('"losses"', body)
        self.assertIn('"voids"', body)
        self.assertIn('"pushes"', body)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MetaServesTheLedgerRecord(unittest.TestCase):
    """`api.meta._card_record` follows `card.ACTIVE_CARD_RULE` (its own
    docstring, written at T5): V1's `record()` while V1 is the published
    card, `effective_record`'s COUNTED V2 cohort from the T13 cutover on.

    UPDATED 2026-09-28 (postseason ruling, registration 11.1). This used
    to read `record_v2()["combined"]` directly, which pools postseason
    picks in -- see `_card_record`'s own comment. It now reads
    `effective_record.sport_snapshot("mlb")["current"]`, the one place
    postseason is already excluded, so mocking `record_v2` alone no
    longer fully determines the v2 figure: `history_v2` (which carries
    the per-entry `game_pk`/`result`/`profit_units` this module's headline
    is rebuilt from) has to be mocked too, consistently. Both paths are
    covered here rather than just whichever one happens to be active in
    this checkout, since ACTIVE_CARD_RULE itself is what this build
    changes."""

    def test_meta_carries_v2s_combined_figures_since_the_t13_cutover(self):
        from api import meta as meta_api
        from src.appstate import card_ledger
        from src.report import card as card_mod
        self.assertEqual("v2", card_mod.ACTIVE_CARD_RULE)
        blank = {"days": 3, "wins": 2, "losses": 1, "pushes": 0, "voids": 0,
                "n_staked": 3, "profit_units": 1.0, "win_rate": 0.667,
                "roi_pct": 10.0}
        # `history_v2`'s own shape (three settled nights, no `game_pk` on
        # any entry -- so none classifies as postseason, see
        # effective_record._is_postseason_entry) tallying to EXACTLY
        # `blank`'s wins/losses/profit_units/days above: 2 wins (+0.8,
        # +0.6), 1 loss (-0.4), 3 distinct dates.
        history_fixture = {
            "days": [
                {"date": "2026-09-01", "graded": [
                    {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                     "result": "WIN", "profit_units": 0.8}]},
                {"date": "2026-09-02", "graded": [
                    {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                     "result": "WIN", "profit_units": 0.6}]},
                {"date": "2026-09-03", "graded": [
                    {"kind": "game", "price_class": "MAIN", "entry_class": "pick",
                     "result": "LOSS", "profit_units": -0.4}]},
            ],
            "total_days": 3, "truncated": False,
        }
        with mock.patch.object(card_ledger, "record_v2",
                              return_value={"combined": blank, "fills": {}, "withdrawn": 0}), \
             mock.patch.object(card_ledger, "history_v2", return_value=history_fixture):
            payload = meta_api.get_meta()
        # profit_units added 2026-09-22 for the landing hero's proof panel;
        # previous_rule carries V1's frozen record on its own labelled line.
        got = dict(payload["card_record"])
        prev = got.pop("previous_rule")
        # POSTSEASON, GRADED BUT NOT COUNTED (registration 11.1) -- this
        # fixture carries none (no entry's `game_pk` is in the postseason
        # set), so the sub-figure is present but empty, and `counted_scope`
        # names the population the flat figures above now are.
        postseason = got.pop("postseason")
        counted_scope = got.pop("counted_scope")
        self.assertEqual(got, {k: blank.get(k) for k in
                               ("days", "wins", "losses", "pushes", "voids", "profit_units")})
        self.assertIsNotNone(postseason)
        self.assertEqual(postseason.get("n_staked"), 0)
        self.assertIn("regular season only", counted_scope)
        self.assertEqual(prev["label"], "Our first card rule")
        # UPDATED, owner review 2026-09-25: this assertion used to compare
        # `prev` against `card_ledger.record()` directly -- V1's GAME-ONLY
        # figure (73-40) -- and passed, because that WAS what `_card_record`
        # built `previous_rule` from. That was the exact bug the review
        # caught: the hero panel (this payload) said "73-40, +7.61u" while
        # the MLB sport tile, reading `src.report.effective_record`'s V1
        # cohort (game PLUS prop pooled), said "151-79, +7.98u" for the
        # same rule, same 13 nights. `_card_record` now sources
        # `previous_rule` from that same effective_record cohort, so this
        # test now asserts equality against IT, not against the game-only
        # figure that caused the mismatch. See
        # tests/test_api_meta_card_record_v2.py's
        # HeroPreviousRuleEqualsSportTilePrevious for the live-ledger
        # version of this same check.
        from src.report import effective_record
        v1_cohort = effective_record.mlb_snapshot().get("previous") or {}
        self.assertEqual(prev["wins"], v1_cohort.get("wins"))
        self.assertEqual(prev["losses"], v1_cohort.get("losses"))
        # And explicitly NOT the game-only figure whenever prop picks
        # exist to make the two differ -- the population bug, pinned.
        v1_game_only = card_ledger.record()
        if (v1_cohort.get("market_breakdown") or {}).get("prop", {}).get("n_staked"):
            self.assertNotEqual(prev["wins"], v1_game_only.get("wins"))

    def test_meta_reads_v1_record_when_active_card_rule_is_v1(self):
        from api import meta as meta_api
        from src.appstate import card_ledger
        from src.report import card as card_mod
        with mock.patch.object(card_mod, "ACTIVE_CARD_RULE", "v1"):
            rec = card_ledger.record()
            payload = meta_api.get_meta()
        self.assertEqual(payload["card_record"],
                         {k: rec.get(k) for k in
                          ("days", "wins", "losses", "pushes", "voids", "profit_units")})

    def test_meta_never_guesses_when_the_ledger_is_unreadable(self):
        """UPDATED 2026-09-28: a V2 read failure now degrades to
        `effective_record`'s own honest-absence cohort (that module's own
        docstring: "available: False and every figure None -- never an
        invented 0-0") rather than `_card_record`'s outer `except`
        catching a raised exception directly -- `_v2_cohort` already
        catches `record_v2`/`history_v2` failures itself and returns that
        cohort, so `_card_record` never sees the exception at all any
        more. The days/wins/losses/pushes/voids/profit_units figures are
        still every one of them None, exactly as before: only the
        MECHANISM changed. `previous_rule` (V1, a separate ledger this
        mock never touches) is a deliberate improvement -- it still
        carries a real figure, because a V2 failure and a V1 read are no
        longer one shared failure domain."""
        from api import meta as meta_api
        with mock.patch("src.appstate.card_ledger.record_v2",
                        side_effect=RuntimeError("gone")):
            payload = meta_api.get_meta()
        got = dict(payload["card_record"])
        self.assertIsNone(got.pop("postseason"))
        self.assertIsNone(got.pop("counted_scope"))
        self.assertIsNotNone(got.pop("previous_rule"))
        self.assertEqual(got, {"days": None, "wins": None, "losses": None,
                              "pushes": None, "voids": None, "profit_units": None})


if __name__ == "__main__":
    unittest.main()
