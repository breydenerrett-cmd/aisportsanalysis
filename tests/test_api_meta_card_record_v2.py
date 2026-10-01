"""Regression: GET /card/record for MLB must not 500.

Found during task B1's verification pass (2026-09-25), not introduced by
it. `api/card.py::get_card_record`'s MLB-v2 branch called
`_effective_record_extras("mlb", None)` -- a name that was never
defined anywhere in the file. Confirmed live:

    >>> from api.card import get_card_record
    >>> get_card_record(request=None, sport="mlb", rule="v2")
    NameError: name '_effective_record_extras' is not defined

`card_mod.ACTIVE_CARD_RULE` flipped to "v2" at CUTOVER_DATE
(2026-09-23, src/report/card.py), so `_resolve_rule(None)` -- what every
caller with no explicit `?rule=` gets, i.e. the record page's default
request -- already resolves to "v2". This was not a dormant edge case;
it was the default path for MLB's own public record route the moment
V2 went live.

`_effective_record_extras` now exists in api/card.py, giving that
branch the same `chain_ok`/`chain_detail`/`rows_checked`/`previous_rule`
fields the non-early-return branches for NFL/UFC already carry (see
`_previous_rule_cohort` just above it) -- read-only, same honest-absence
rule as everywhere else on this surface.
"""

from __future__ import annotations

import unittest

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class CardRecordMlbV2DoesNotRaise(unittest.TestCase):
    def test_explicit_rule_v2_does_not_raise(self):
        from api.card import get_card_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        self.assertIsInstance(payload, dict)

    def test_default_rule_resolves_to_v2_and_does_not_raise(self):
        """No `?rule=` at all -- the record page's actual default
        request -- must resolve through the same branch and succeed,
        since ACTIVE_CARD_RULE is "v2" (docs/CARD_V2_BUILD_PLAN.md,
        CUTOVER_DATE 2026-09-23)."""
        from api.card import get_card_record
        from src.report import card as card_mod
        self.assertEqual(card_mod.ACTIVE_CARD_RULE, "v2",
                         "this test assumes today's active rule; if it has "
                         "changed, the default-path assertion below no "
                         "longer exercises the v2 branch")
        payload = get_card_record(request=None, sport="mlb")
        self.assertEqual(payload.get("rule"), "v2")

    def test_v2_record_carries_the_extras_every_other_sport_gets(self):
        from api.card import get_card_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        for key in ("sport", "chain_ok", "chain_detail", "rows_checked",
                   "previous_rule", "postseason", "counted_scope"):
            self.assertIn(key, payload, key)
        self.assertEqual(payload["sport"], "mlb")

    def test_chain_verified_is_v2s_own_store_not_v1s(self):
        """A bare `card_ledger.verify()` with no explicit path defaults
        to V1's file (`store_path`) -- this must verify
        `CARD_STORE_V2` explicitly, or `rows_checked` would silently
        describe the wrong ledger for a V2 record page."""
        from api.card import get_card_record
        from src.appstate import card_ledger
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        expected = card_ledger.verify(path=card_ledger.CARD_STORE_V2)
        self.assertEqual(payload["rows_checked"], getattr(expected, "rows_checked", None))

    def test_previous_rule_is_v1s_cohort(self):
        from api.card import get_card_record
        from src.analysis import daily_card
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        previous = payload.get("previous_rule")
        if previous is not None:  # honest-absence: only assert shape when present
            self.assertEqual(previous.get("rule_id"), daily_card.CARD_RULE)
            self.assertEqual(previous.get("status"), "previous")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class CardRecordMlbV2FlatAliasesMatchRecordLinesExpectation(unittest.TestCase):
    """A second, independent bug found in the same pass, same root cause:
    even once `get_card_record` stopped raising, its V2 payload nested
    every figure under `main`/`plus_money`/`fills`/`combined` -- a shape
    V1's `record()` never had. THREE separate readers of this exact route
    (`web/js/card.js`'s `recordLine`, `web/js/recordstrip.js`'s
    `renderCardRecordStrip`, `web/js/cardrecord.js`'s detail page) all
    read `rec.wins`/`rec.losses`/`rec.n_staked`/`rec.days`/
    `rec.profit_units`/`rec.win_rate`/`rec.roi_pct` at the TOP level, the
    shape V1 always returned. `recordLine`'s own guard is literally `!rec
    || !rec.n_staked` -- with no flat `n_staked`, that guard fires and the
    card page tells a reader "Nothing graded yet" while MLB's real V2
    record (verified live during this task) was 14-15, -4.73u over 3
    nights. A confident false claim, not a missing feature -- the
    product's one hard rule.

    Verified live in a real browser against the running app
    (http://localhost:8000): before this fix, `fetch('/card/record')`
    returned `n_staked: undefined`; after, `n_staked: 29` matching
    `combined.n_staked`.
    """

    ALIAS_KEYS = ("days", "wins", "losses", "pushes", "voids", "n_staked",
                 "profit_units", "win_rate", "roi_pct")

    def test_every_flat_alias_matches_the_combined_figure_it_mirrors(self):
        from api.card import get_card_record
        # CHANGED 2026-10-01. The flat keys used to mirror `combined`, and
        # this test said so. api/card.py moved them to effective_record's
        # counted cohort (regular season only, registration 11.1) because
        # `combined` pools postseason entries in; the two were equal only
        # while the ledger held no postseason card. It has held some since
        # 2026-09-29, so the assertion that matters is the documented one:
        # the flat keys equal the counted record the rest of the site shows.
        from src.report import effective_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        counted = effective_record.build()["sports"]["mlb"]["current"]
        for key in self.ALIAS_KEYS:
            self.assertIn(key, payload, f"flat `{key}` missing from the v2 record payload")
            self.assertEqual(payload[key], counted.get(key),
                             f"flat `{key}` disagrees with the counted record's {key}")

    def test_the_nested_shape_is_untouched(self):
        """This fix only ADDS flat keys -- main/plus_money/fills/combined
        keep exactly the apart-never-pooled shape R5 requires; a reader
        of the detailed breakdown must see no change."""
        from api.card import get_card_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        for key in ("main", "plus_money", "fills", "combined"):
            self.assertIn(key, payload, key)
            self.assertIsInstance(payload[key], dict, key)

    def test_recordlines_own_guard_would_not_fire_on_a_real_settled_record(self):
        """`recordLine(rec)`'s guard, transcribed verbatim from
        web/js/card.js: `if (!rec || !rec.n_staked) { "Nothing graded
        yet." }`. Simulated here in Python against the real payload so a
        future change to either side (the alias, or the guard) that
        breaks this pairing fails a test instead of shipping a false
        "nothing graded yet" claim."""
        from api.card import get_card_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        combined = payload.get("combined") or {}
        if not combined.get("n_staked"):
            self.skipTest("today's live V2 ledger has no settled picks yet -- "
                          "nothing to assert the guard against")
        would_render_nothing_graded_yet = not payload or not payload.get("n_staked")
        self.assertFalse(
            would_render_nothing_graded_yet,
            "combined has settled picks but the flat alias is falsy -- "
            "recordLine would render a false 'Nothing graded yet.'")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class HeroPreviousRuleEqualsSportTilePrevious(unittest.TestCase):
    """Owner review, 2026-09-25: the hero panel said "Our first card
    rule: 73-40, +7.61u over 13 nights" and the MLB sport tile said
    "151-79, +7.98u" -- same rule, same 13 nights, two different numbers
    on one page. Root cause: `api/meta.py::_card_record()` built
    `previous_rule` from `card_ledger.record()` (GAME picks only); the
    sport tile read `src.report.effective_record`'s V1 cohort (GAME PLUS
    PROP, pooled). Fixed by making `_card_record`'s `previous_rule` read
    the exact same effective_record cohort -- this test proves that
    equality on TODAY's real live ledger, not a synthetic fixture, since
    the bug was only ever visible against real data (the mismatch a
    reader saw was 73-40 vs 151-79, both real numbers)."""

    def test_previous_rule_figures_match_the_effective_record_cohort(self):
        from api.meta import get_meta
        from src.report import effective_record

        meta = get_meta()
        hero_previous = meta["card_record"].get("previous_rule")
        tile_previous = meta["effective_record"]["sports"]["mlb"].get("previous")

        if hero_previous is None or tile_previous is None:
            self.skipTest("no previous-rule cohort available on today's live ledger")

        for key in ("wins", "losses", "pushes", "voids", "days", "profit_units"):
            self.assertEqual(hero_previous[key], tile_previous[key],
                             f"hero previous_rule.{key} disagrees with the sport tile's "
                             "own previous cohort -- the two surfaces must read one source")

    def test_previous_rule_pools_game_and_prop_not_game_only(self):
        """The specific population bug, pinned directly: `previous_rule`
        must NOT equal `card_ledger.record()`'s bare (game-only) figure
        once a game+prop pooled figure differs from it. On today's real
        ledger this is 73-40 (game only) vs 151-79 (pooled) -- if this
        cohort's game-only slice ever equals its own pooled headline
        (e.g. a ledger with no prop picks at all), the two numbers would
        coincidentally match and this assertion would need the ledger's
        real shape re-checked, not weakened."""
        from src.appstate import card_ledger
        from src.report import effective_record

        previous = effective_record.mlb_snapshot().get("previous")
        if previous is None or not previous.get("available"):
            self.skipTest("no V1 cohort available on today's live ledger")
        game_only = card_ledger.record()
        game_only_wl = (game_only.get("wins"), game_only.get("losses"))
        pooled_wl = (previous.get("wins"), previous.get("losses"))
        prop_breakdown = (previous.get("market_breakdown") or {}).get("prop") or {}
        if not prop_breakdown.get("n_staked"):
            self.skipTest("no settled prop picks on today's live ledger -- "
                          "game-only and pooled would coincide")
        self.assertNotEqual(game_only_wl, pooled_wl,
                            "pooled previous_rule matches the game-only figure exactly -- "
                            "re-verify this fixture still reflects real prop activity")
        self.assertEqual(pooled_wl[0], game_only_wl[0] + prop_breakdown["wins"])
        self.assertEqual(pooled_wl[1], game_only_wl[1] + prop_breakdown["losses"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RecordFlatFieldsEqualEffectiveRecordsCountedCohort(unittest.TestCase):
    """Owner ruling, 2026-09-28 (registration 11.1): postseason picks are
    published, graded and shown, but not counted. Live-ledger version of
    tests/test_postseason_not_counted.py's mocked
    `ApiCardV2ExposesPostseasonSplit` -- on TODAY's real ledger (MLB's
    2026 regular season ends 2026-09-27, the Wild Card round starts
    2026-09-29, docs/SEASON_END_PLAN.md) there is no real postseason
    activity yet, so `postseason` reads zero and the counted figure
    equals the same real numbers `CardRecordMlbV2FlatAliasesMatchRecord
    LinesExpectation` already pins against `combined` above -- but the
    SOURCE has to be effective_record's counted cohort, not `combined`
    directly, by construction, so a real postseason night from
    2026-09-29 on cannot silently re-inflate this route's headline
    again."""

    def test_flat_fields_match_effective_records_counted_v2_cohort(self):
        from api.card import get_card_record
        from src.report import effective_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        current = effective_record.sport_snapshot("mlb").get("current") or {}
        for key in ("days", "wins", "losses", "pushes", "voids", "profit_units"):
            self.assertEqual(payload.get(key), current.get(key), key)
        self.assertEqual(payload.get("postseason"), current.get("postseason"))
        self.assertEqual(payload.get("counted_scope"), current.get("counted_scope"))

    def test_postseason_key_has_the_headline_shape(self):
        from api.card import get_card_record
        payload = get_card_record(request=None, sport="mlb", rule="v2")
        postseason = payload.get("postseason")
        self.assertIsNotNone(postseason)
        for key in ("wins", "losses", "pushes", "voids", "unresolved",
                   "n_staked", "profit_units", "days", "date_span", "label"):
            self.assertIn(key, postseason, key)
        self.assertEqual(postseason["label"], "Postseason (graded, not counted)")


if __name__ == "__main__":
    unittest.main()
