"""The day-level top-N ranking: deterministic, honest about its basis.

`src.engine.slate.SELECTION_RULE` answers "which record for one GAME gets
staked". `DAY_RANKING_RULE` answers the owner's question instead -- across
the whole slate, which are this system's best ten? -- and these tests pin
the three properties that make that answer trustworthy:

  * it ranks on PRICE STANDING, which is execution quality, never on a
    fabricated edge (no registered system can even produce an `edge_bps`);
  * a record with no consensus has NO basis value and is ranked last as
    such, never given a zero that would let it outrank real standings;
  * the order is a total order with no tie broken by dict/iteration order,
    so the same slate produces the same ten on any machine.
"""

from __future__ import annotations

import unittest

from src.board.ids import selection_id
from src.engine import slate
from src.ledger.records import PROBABILITY_PROVENANCE_NONE

HOME_SEL = selection_id(sport="mlb", market_key="h2h", side="home")
AWAY_SEL = selection_id(sport="mlb", market_key="h2h", side="away")


def make_record(*, system_id="sys", event_id="e1", selection_id_=HOME_SEL,
                 price_american=-110, consensus_fair=0.55, books=8,
                 vig=0.04, verdict="play"):
    """A DecisionRecord carrying only the fields the ranking reads, with
    every other field filled with a plainly inert value. Built through the
    real frozen record (not a stand-in) so the ranking is tested against
    the type it will actually be handed."""
    from src.ledger.records import DecisionRecord

    return DecisionRecord(
        engine_version="engine-1", system_id=system_id,
        system_version="test-1", registry_fingerprint="",
        frame_fingerprint=None, snapshot_fingerprint="fp",
        game_pk=None, event_id=event_id,
        decision_utc="2026-09-02T20:00:00+00:00", point_class="LATE_BOARD",
        information_time="2026-09-02T20:00:00+00:00",
        recorded_utc="2026-09-02T20:00:00+00:00", verdict=verdict,
        selection_id=selection_id_, market_key="h2h", line=None,
        book="draftkings", price_american=price_american,
        consensus_fair=consensus_fair, books_at_decision=books,
        friction={"vig": vig, "book_count": books, "staleness_seconds": 0,
                  "dispersion": 0.01},
        p_model=None, p_model_interval=None, edge_bps=None,
        price_improvement_bps=None, rating=None,
        thesis="test", evidence=["test"], counterarguments=[],
        supporting_systems=[system_id], refusal_reason=None,
        assumption_exposure={}, stake_units=0.0, known_at_grade="A",
        p_model_provenance=PROBABILITY_PROVENANCE_NONE,
        value_basis="price_standing_only:no_calibrated_p_model",
    )


def game(game_key, records):
    return slate.GameOutcome(
        game_key=game_key, game_pk=None, t="2026-09-02T20:00:00+00:00",
        commence_time="2026-09-02T23:00:00+00:00", skipped_reason=None,
        records=tuple(records), new_decisions=len(records),
        duplicate_decisions=0, staked_bet_ids=(), duplicate_wagers=0)


class TestPriceStanding(unittest.TestCase):
    def test_standing_is_consensus_minus_implied_in_bps(self):
        # -110 implies 0.5238...; a consensus of 0.5738 stands +500 bps.
        record = make_record(price_american=-110, consensus_fair=0.5738095238)
        self.assertEqual(slate.price_standing_bps(record), 500)

    def test_missing_consensus_or_price_is_none_never_zero(self):
        self.assertIsNone(
            slate.price_standing_bps(make_record(consensus_fair=None)))
        # A `play` always carries a price (DecisionRecord enforces it), so
        # the priceless case is a non-play verdict -- which is exactly the
        # record shape whose standing must come back absent, not zero.
        self.assertIsNone(slate.price_standing_bps(
            make_record(price_american=None, verdict="market_unavailable")))


class TestDayRanking(unittest.TestCase):
    def test_best_standing_ranks_first_across_games(self):
        games = [
            game("g1", [make_record(event_id="e1", consensus_fair=0.53)]),
            game("g2", [make_record(event_id="e2", consensus_fair=0.60)]),
            game("g3", [make_record(event_id="e3", consensus_fair=0.56)]),
        ]
        ranked = slate.rank_day_by_system(games)["sys"]
        self.assertEqual([p.rank for p in ranked], [1, 2, 3])
        self.assertEqual([p.record.event_id for p in ranked],
                         ["e2", "e3", "e1"])
        self.assertGreater(ranked[0].price_standing_bps,
                           ranked[1].price_standing_bps)

    def test_no_basis_ranks_last_and_is_reported_as_absent(self):
        games = [
            game("g1", [make_record(event_id="e1", consensus_fair=None)]),
            game("g2", [make_record(event_id="e2", consensus_fair=0.53)]),
        ]
        ranked = slate.rank_day_by_system(games)["sys"]
        self.assertEqual([p.record.event_id for p in ranked], ["e2", "e1"])
        self.assertIsNone(ranked[-1].price_standing_bps)

    def test_only_play_verdicts_are_ranked(self):
        games = [game("g1", [
            make_record(event_id="e1", verdict="refused_thin"),
            make_record(event_id="e2", verdict="play"),
        ])]
        ranked = slate.rank_day_by_system(games)["sys"]
        self.assertEqual([p.record.event_id for p in ranked], ["e2"])

    def test_top_n_is_honoured_and_defaults_to_ten(self):
        games = [game(f"g{i}", [make_record(event_id=f"e{i}",
                                            consensus_fair=0.50 + i / 1000)])
                 for i in range(15)]
        self.assertEqual(len(slate.rank_day_by_system(games)["sys"]),
                         slate.DEFAULT_TOP_N_PER_SYSTEM_PER_DAY)
        self.assertEqual(len(slate.rank_day_by_system(games, top_n=3)["sys"]),
                         3)

    def test_each_system_is_ranked_separately(self):
        games = [game("g1", [
            make_record(system_id="a", event_id="e1", consensus_fair=0.60),
            make_record(system_id="b", event_id="e1", consensus_fair=0.53),
        ])]
        ranked = slate.rank_day_by_system(games)
        self.assertEqual(sorted(ranked), ["a", "b"])
        self.assertEqual(ranked["a"][0].rank, 1)
        self.assertEqual(ranked["b"][0].rank, 1)

    def test_ties_break_deterministically_not_by_iteration_order(self):
        """Identical standings must not be ordered by whichever record was
        appended first -- the whole point of a pre-registered total order."""
        forward = [game("g1", [
            make_record(event_id="e1", selection_id_=AWAY_SEL),
            make_record(event_id="e1", selection_id_=HOME_SEL),
        ])]
        backward = [game("g1", [
            make_record(event_id="e1", selection_id_=HOME_SEL),
            make_record(event_id="e1", selection_id_=AWAY_SEL),
        ])]
        self.assertEqual(
            [p.record.selection_id for p in slate.rank_day_by_system(forward)["sys"]],
            [p.record.selection_id for p in slate.rank_day_by_system(backward)["sys"]])

    def test_every_ranked_pick_names_its_basis(self):
        games = [game("g1", [make_record()])]
        pick = slate.rank_day_by_system(games)["sys"][0]
        self.assertEqual(pick.basis, slate.DAY_RANKING_BASIS)
        self.assertIn("NOT an edge", pick.basis)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
