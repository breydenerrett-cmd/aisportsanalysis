"""Every published decision must explain itself, and must not overclaim.

These are regression tests for the owner directive of 2026-09-04: a
published pick has to read "I'm picking this bet because xyz", in English,
with the actual numbers in it -- not "evolab genome 606be696ff199952:
(('top_minus_bottom', 1),)", which is what the ledger carried before.

Three properties are pinned here, each one a story about a specific way the
product could go wrong:

  1. NO HASH WHERE A NAME EXISTS. A thesis or a rendered pick that shows a
     16-hex identity where a team, market or feature name was available is
     the original defect. Identity keys stay on the record's own fields.
  2. A MARKET_DERIVED PICK SAYS IT CARRIES NO EDGE. Its p_model IS the
     market's own de-vigged consensus; a reader who is not told that will
     read a confident-looking probability as a forecast.
  3. NO EDGE CLAIM WITHOUT AN EDGE. `edge_bps` is structurally None for
     every provenance but `model_derived`, and no model_derived system is
     registered today, so no thesis anywhere may assert value.

Property 3 is additionally checked against the REAL published ledger
(`evidence/decisions_v2.jsonl`), because that file is the thing a customer
would actually read. Property 1 is NOT checked against the ledger: rows
published before this change are frozen history and carry the old
hash-shaped thesis by construction -- rewriting them would be falsifying a
hash chain, which is a far worse sin than an ugly old row.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.board.readable import (
    BOOK_DISPLAY_NAMES,
    GameTeams,
    render_selection,
    side_for_selection,
)
from src.board.ids import selection_id
from src.engine.adapters.evolab_system import (
    MARKET_DERIVED_SYSTEMS,
    REGISTERED_SYSTEMS,
    TrivialAlwaysHomeSpreadSystem,
    TrivialUnderTotalSystem,
)
from src.engine.explain import claims_edge, evolab_thesis, explain_signal
from src.engine.glue import TrivialAlwaysHomeSystem
from src.engine.snapshot import PointMeta, PriceBlindSnapshot
from src.ledger.records import (
    PROBABILITY_PROVENANCE_MARKET_DERIVED,
    PROBABILITY_PROVENANCE_MODEL_DERIVED,
)
from src.paths import evidence_path

# A 16-hex run is exactly what `src.board.ids.selection_id` and an evolab
# `strategy_id` look like. Bounded on both sides so a wOBA value or a date
# can never be mistaken for one.
HASH_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")

# Feature values chosen to clear the top rung of every ladder, so every
# registered genome that can fire, fires. Nothing here is read from the real
# feature store: this is a unit test of PROSE, not of feature computation.
LOUD_FEATURES = {
    "away_lineup_platoon_share": 0.90, "home_lineup_platoon_share": 0.10,
    "away_lineup_vs_primary_pitch": 0.400, "home_lineup_vs_primary_pitch": 0.100,
    "away_primary_pitch_share": 0.600, "home_primary_pitch_share": 0.100,
    "away_top_minus_bottom": 0.300, "home_top_minus_bottom": 0.010,
    "away_starter_velocity_gap": 8.00, "home_starter_velocity_gap": 0.50,
    "away_starter_groundball_share": 0.600, "home_starter_groundball_share": 0.100,
}

ALL_MARKETS = ("h2h", "spreads", "totals", "h2h_1st_5_innings")


def loud_snapshot() -> PriceBlindSnapshot:
    return PriceBlindSnapshot(
        game_pk="test-game", t="2026-09-02T20:00:00+00:00",
        point_class="LATE_BOARD", features=dict(LOUD_FEATURES),
        available_markets=ALL_MARKETS,
        books_by_market={m: 9 for m in ALL_MARKETS},
        point_meta=PointMeta(observed_utc="2026-09-02T20:00:00+00:00",
                             simultaneous=True),
        lineup_posted=True,
    )


def all_proposals():
    """Every proposal every registered system makes on one loud snapshot."""
    view = loud_snapshot()
    out = []
    for system in REGISTERED_SYSTEMS:
        for proposal in system.propose(view):
            out.append((system, proposal))
    return out


class TestNoHashWhereANameExists(unittest.TestCase):
    def test_registered_systems_produce_no_hash_shaped_thesis(self):
        proposals = all_proposals()
        self.assertTrue(proposals, "no registered system proposed at all")
        fired_genomes = 0
        for system, proposal in proposals:
            with self.subTest(system=system.id):
                self.assertIsNotNone(proposal.thesis)
                found = HASH_RE.findall(proposal.thesis)
                # A genome's own strategy_id may appear ONCE, at the end, as
                # attribution -- never as the explanation.
                self.assertLessEqual(
                    len(found), 1,
                    f"{system.id} thesis carries hash(es) {found}")
                if found:
                    self.assertIn("Strategy: evolab genome", proposal.thesis)
                    self.assertNotIn(found[0], proposal.thesis.split(
                        "Strategy: evolab genome")[0])
                    fired_genomes += 1
        self.assertGreater(
            fired_genomes, 0,
            "no evolab genome fired on the loud snapshot -- this test would "
            "pass vacuously")

    def test_evolab_thesis_names_the_actual_feature_value(self):
        thesis = evolab_thesis(
            "606be696ff199952", "h2h", "away",
            (("top_minus_bottom", 1),), dict(LOUD_FEATURES))
        # The value, the threshold, the rung and the sample all appear.
        self.assertIn("away 0.300 wOBA", thesis)
        self.assertIn("home 0.010 wOBA", thesis)
        self.assertIn("0.290 wOBA", thesis)          # the gap
        self.assertIn("0.042 wOBA", thesis)          # the rung 1 threshold
        self.assertIn("75th percentile", thesis)
        self.assertIn("4,838 games with both sides measured", thesis)
        self.assertIn("top-of-order minus bottom-of-order", thesis)

    def test_absent_feature_value_is_reported_absent_never_invented(self):
        sentence = explain_signal("top_minus_bottom", 0, "away",
                                  {"away_top_minus_bottom": 0.3})
        self.assertIn("home unavailable", sentence)
        self.assertIn("a gap of unavailable", sentence)

    def test_rendered_selection_is_english_not_a_hash(self):
        teams = GameTeams(home="Atlanta Braves", away="San Francisco Giants")
        cases = [
            (dict(market_key="spreads", side="home", line="-1.5",
                  price_american=-118, book="draftkings"),
             "Atlanta Braves (home) -1.5 run line (-118, DraftKings)"),
            (dict(market_key="totals", side="over", line="8.5",
                  price_american=105, book="fanduel"),
             "Over 8.5 total runs (+105, FanDuel)"),
            (dict(market_key="h2h", side="away", price_american=130,
                  book="betmgm"),
             "San Francisco Giants (away) moneyline (+130, BetMGM)"),
        ]
        for kwargs, expected in cases:
            with self.subTest(**kwargs):
                self.assertEqual(
                    render_selection(teams=teams, **kwargs), expected)

    def test_unknown_team_degrades_to_english_never_to_a_hash(self):
        text = render_selection(market_key="h2h", side="home",
                                price_american=-135, book="betmgm")
        self.assertEqual(text, "the home side moneyline (-135, BetMGM)")
        self.assertFalse(HASH_RE.findall(text))

    def test_unknown_book_key_is_printed_verbatim_not_invented(self):
        text = render_selection(market_key="h2h", side="home",
                                price_american=-135, book="somenewbook")
        self.assertIn("somenewbook", text)
        self.assertNotIn("somenewbook", BOOK_DISPLAY_NAMES)

    def test_side_is_recovered_from_the_selection_hash(self):
        sid = selection_id(sport="mlb", market_key="totals", side="under",
                           line="8.5")
        self.assertEqual(side_for_selection("totals", sid, "8.5"), "under")
        # None over guess when nothing matches.
        self.assertIsNone(side_for_selection("totals", "0" * 16, "8.5"))


class TestMarketDerivedSaysItCarriesNoEdge(unittest.TestCase):
    def test_every_market_derived_thesis_denies_an_edge(self):
        view = loud_snapshot()
        seen = 0
        for system in MARKET_DERIVED_SYSTEMS:
            for proposal in system.propose(view):
                seen += 1
                thesis = proposal.thesis.lower()
                self.assertEqual(proposal.p_model_provenance,
                                 PROBABILITY_PROVENANCE_MARKET_DERIVED)
                self.assertIn("market's own probability", thesis)
                self.assertIn("no edge", thesis)
                self.assertFalse(claims_edge(proposal.thesis))
        self.assertGreater(seen, 0)

    def test_placeholder_controls_say_they_are_controls(self):
        view = loud_snapshot()
        for system in (TrivialAlwaysHomeSystem(), TrivialUnderTotalSystem(),
                       TrivialAlwaysHomeSpreadSystem()):
            for proposal in system.propose(view):
                with self.subTest(system=system.id):
                    self.assertIn("DELIBERATE CONTROL", proposal.thesis)
                    self.assertFalse(claims_edge(proposal.thesis))


class TestNoEdgeClaimWithoutAnEdge(unittest.TestCase):
    def test_claims_edge_detects_real_claims(self):
        for text in ("we have a 3% edge here", "this is +EV",
                     "the line is mispriced", "an expected profit of 2 units",
                     "a clear probability advantage", "profitable long run"):
            with self.subTest(text=text):
                self.assertTrue(claims_edge(text))

    def test_claims_edge_allows_explicit_denials(self):
        for text in ("edge_bps is structurally None",
                     "no edge is claimed", "edge_bps is null by construction",
                     "no edge_bps can ever be computed for it"):
            with self.subTest(text=text):
                self.assertFalse(claims_edge(text))

    def test_no_registered_system_claims_an_edge(self):
        for system, proposal in all_proposals():
            with self.subTest(system=system.id):
                self.assertNotEqual(proposal.p_model_provenance,
                                    PROBABILITY_PROVENANCE_MODEL_DERIVED,
                                    "a model_derived system was registered -- "
                                    "this test's premise needs revisiting")
                self.assertFalse(claims_edge(proposal.thesis))

    def test_published_ledger_never_claims_an_edge_it_does_not_have(self):
        """The real published file, not a fixture: this is what a reader
        would see. A row whose `edge_bps` is None may not assert value."""
        path = Path(evidence_path("decisions_v2.jsonl"))
        if not path.exists():  # pragma: no cover -- fresh clone, nothing published
            self.skipTest("no published decisions ledger in this checkout")
        checked = 0
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                row = row.get("record", row)
                thesis = row.get("thesis")
                if not thesis or row.get("edge_bps") is not None:
                    continue
                checked += 1
                self.assertFalse(
                    claims_edge(thesis),
                    f"published row {row.get('row_hash')} has edge_bps=None "
                    f"but its thesis claims value: {thesis!r}")
        self.assertGreater(checked, 0, "no published theses were checked")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
