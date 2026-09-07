"""Tests for src.analysis.opportunities (Task B2).

Covers: ranking (value_points desc, None last, books desc as tiebreak),
the qualifying cut (top_n, word floor), empty_reason when nothing
qualifies, an INSUFFICIENT DATA row from a malformed price, the unpriced
list (no board / thin board / no priceable side), support/counter claim
attachment from findings, the engine rollup wiring, and the customer-
language tripwire against every string this module emits.
"""

from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone

from src.analysis import opportunities as opp
from src.detect import base
from src.detect.dossier import Dossier

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

NOW = datetime(2026, 9, 7, 18, 0, 0, tzinfo=timezone.utc)
OBSERVED = "2026-09-07T17:30:00Z"  # 30 min before NOW


def _game(away, home, game_pk, venue="Test Park", start="2026-09-07T23:05:00Z"):
    return {
        "away_team": away, "home_team": home, "date": "2026-09-07",
        "start_time_utc": start, "venue": venue, "game_pk": game_pk,
    }


def _side_detail(best_price, best_book, consensus_probability):
    return {"best_book": best_book, "best_price": best_price,
           "consensus_probability": consensus_probability,
           "improvement_points": 0.0, "improvement_return_pct": 0.0}


def _board(away_detail=None, home_detail=None, books=9, observed_utc=OBSERVED):
    sides = {}
    if away_detail is not None:
        sides["away"] = away_detail
    if home_detail is not None:
        sides["home"] = home_detail
    return {"sides": sides, "dispersion": {"books": books,
                                           "home_probability_range": 0.01},
           "label": "price improvement", "any_positive": True, "note": None,
           "observed_utc": observed_utc}


def _entry(game, board=None, findings=None, skipped_reason=None):
    dossier = Dossier(game, information_time=NOW)
    if skipped_reason is not None:
        dossier.miss("price_improvement", skipped_reason)
    elif board is not None:
        dossier.add("price_improvement", board)
    else:
        dossier.miss("price_improvement", "no multi-book observations for this game yet")
    return {"dossier": dossier, "findings": list(findings or ()),
           "verdict": "no_play", "side": None, "market": None, "summary": None}


def _finding(claim, side, sample_n=50, surprise=1.0):
    return base.Finding(
        detector="test_detector", kind=base.SIGNAL, claim=claim,
        baseline=0.25, sample={"n": sample_n}, surprise=surprise, side=side,
        evidence=base.PROVISIONAL)


class RankingTests(unittest.TestCase):
    def test_ranked_by_value_points_desc_then_books_desc(self):
        # Game A away side: strong value (best 150 vs consensus 0.50 -> big vp)
        entries = [
            _entry(_game("AAA", "BBB", 1),
                  board=_board(away_detail=_side_detail(150, "book1", 0.50),
                              books=9)),
            # Game B away side: modest positive vp, fewer books -> ranks below A
            _entry(_game("CCC", "DDD", 2),
                  board=_board(away_detail=_side_detail(105, "book2", 0.49),
                              books=6)),
            # Game C: no board at all -> unpriced, never in rows
            _entry(_game("EEE", "FFF", 3), skipped_reason="no board captured"),
        ]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self.assertEqual(payload["checked_games"], 3)
        self.assertEqual(len(payload["unpriced"]), 1)
        self.assertEqual(payload["unpriced"][0]["away_team"], "EEE")
        rows = payload["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["away_team"], "AAA")
        self.assertEqual(rows[1]["away_team"], "CCC")
        self.assertGreater(rows[0]["value_points"], rows[1]["value_points"])

    def test_none_value_points_sort_last(self):
        insufficient_board = _board(
            away_detail=_side_detail(0, "book1", 0.50))  # price=0 is invalid
        good_board = _board(away_detail=_side_detail(150, "book2", 0.50))
        entries = [
            _entry(_game("ZZZ", "YYY", 1), board=insufficient_board),
            _entry(_game("AAA", "BBB", 2), board=good_board),
        ]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        rows = payload["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["away_team"], "AAA")
        self.assertIsNotNone(rows[0]["value_points"])
        self.assertIsNone(rows[1]["value_points"])
        self.assertEqual(rows[1]["price_verdict"]["word"], "INSUFFICIENT DATA")

    def test_books_desc_is_the_tiebreak_on_equal_value_points(self):
        detail_a = _side_detail(150, "book1", 0.50)
        detail_b = _side_detail(150, "book2", 0.50)
        entries = [
            _entry(_game("LOW", "X1", 1), board=_board(away_detail=detail_a, books=6)),
            _entry(_game("HIGH", "X2", 2), board=_board(away_detail=detail_b, books=11)),
        ]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        rows = payload["rows"]
        self.assertEqual(rows[0]["away_team"], "HIGH")
        self.assertEqual(rows[1]["away_team"], "LOW")


class QualifyingTests(unittest.TestCase):
    def test_qualifying_is_capped_at_top_n_and_word_floor(self):
        entries = []
        # Six games, each a STRONG VALUE away side (vp well above 3.0), plus
        # one FAIR PRICE game that must never qualify.
        for i in range(6):
            entries.append(_entry(
                _game(f"S{i}", f"H{i}", i),
                board=_board(away_detail=_side_detail(200 + i, f"book{i}", 0.60),
                            books=9)))
        entries.append(_entry(
            _game("FAIRAWAY", "FAIRHOME", 99),
            board=_board(away_detail=_side_detail(-110, "bookx", 0.524),
                        books=9)))
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW,
                                          top_n=5)
        self.assertEqual(len(payload["qualifying"]), 5)
        for row in payload["qualifying"]:
            self.assertIn(row["price_verdict"]["word"], opp.QUALIFYING_WORDS)
        self.assertIsNone(payload["empty_reason"])

    def test_empty_reason_when_nothing_qualifies(self):
        entries = [_entry(
            _game("AWY", "HOM", 1),
            board=_board(away_detail=_side_detail(-110, "book1", 0.524),
                        books=9))]  # FAIR PRICE, does not qualify
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self.assertEqual(payload["qualifying"], [])
        self.assertEqual(payload["empty_reason"], opp.EMPTY_REASON)

    def test_no_games_is_an_honest_empty_payload(self):
        payload = opp.build_opportunities([], date="2026-09-07", now=NOW)
        self.assertEqual(payload["checked_games"], 0)
        self.assertEqual(payload["priced_games"], 0)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["unpriced"], [])
        self.assertEqual(payload["empty_reason"], opp.EMPTY_REASON)


class UnpricedTests(unittest.TestCase):
    def test_thin_board_reason_is_carried_verbatim(self):
        entries = [_entry(_game("A", "B", 1),
                          skipped_reason="5 books quoted; below the 6-book floor")]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self.assertEqual(len(payload["unpriced"]), 1)
        self.assertIn("below the 6-book floor", payload["unpriced"][0]["reason"])

    def test_both_sides_skipped_lands_in_unpriced_not_rows(self):
        board = _board(away_detail={"skipped": "no priceable quote on this side"},
                       home_detail={"skipped": "no priceable quote on this side"})
        entries = [_entry(_game("A", "B", 1), board=board)]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(len(payload["unpriced"]), 1)


class RowContentTests(unittest.TestCase):
    def test_row_carries_support_and_counter_claims_capped_at_three(self):
        away_findings = [_finding(f"away claim {i}", base.AWAY) for i in range(4)]
        home_findings = [_finding("home claim", base.HOME)]
        entries = [_entry(
            _game("AWY", "HOM", 1),
            board=_board(away_detail=_side_detail(150, "book1", 0.55), books=9),
            findings=away_findings + home_findings)]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        row = payload["rows"][0]
        self.assertEqual(row["side"], "away")
        self.assertEqual(len(row["support_claims"]), 3)  # capped from 4
        self.assertEqual(len(row["counter_claims"]), 1)
        self.assertEqual(row["counter_claims"][0]["statement"], "home claim")
        self.assertIsNone(row["thin_or_unavailable_reason"])
        self.assertEqual(row["independent_model"], "NO INDEPENDENT MODEL YET")
        self.assertEqual(row["wager_text"], "AWY moneyline")
        self.assertEqual(row["market"], "h2h")

    def test_engine_rollup_attached_when_engine_by_key_has_the_game(self):
        entries = [_entry(
            _game("AWY", "HOM", 1),
            board=_board(away_detail=_side_detail(150, "book1", 0.55), books=9))]
        engine_by_key = {
            ("AWY", "HOM", "2026-09-07"): [
                {"system_class": "FORWARD_TEST", "verdict": "play", "staked": True,
                "p_model_provenance": "none", "counterarguments": []},
            ],
        }
        payload = opp.build_opportunities(
            entries, date="2026-09-07", now=NOW, engine_by_key=engine_by_key)
        row = payload["rows"][0]
        self.assertIsNotNone(row["engine"])
        self.assertEqual(row["engine"]["n_decisions"], 1)
        self.assertEqual(len(row["engine"]["forward_test_plays"]), 1)

    def test_engine_is_none_when_no_engine_data_supplied(self):
        entries = [_entry(
            _game("AWY", "HOM", 1),
            board=_board(away_detail=_side_detail(150, "book1", 0.55), books=9))]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self.assertIsNone(payload["rows"][0]["engine"])

    def test_priced_games_counts_distinct_games_not_rows(self):
        entries = [_entry(
            _game("AWY", "HOM", 1),
            board=_board(away_detail=_side_detail(150, "book1", 0.55),
                        home_detail=_side_detail(-140, "book2", 0.45), books=9))]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self.assertEqual(len(payload["rows"]), 2)  # both sides priced
        self.assertEqual(payload["priced_games"], 1)


class LabelAndBasisTests(unittest.TestCase):
    def test_label_and_basis_present_and_clean(self):
        payload = opp.build_opportunities([], date="2026-09-07", now=NOW)
        self.assertIn("TOP OPPORTUNITIES", payload["label"])
        self.assertIn("NO INDEPENDENT MODEL", payload["basis"].upper())


class CustomerLanguageTripwireTests(unittest.TestCase):
    """Every string this module can emit -- label, basis, wager_text,
    reasons/risks, unpriced reasons -- must clear the same banned-language
    scan tests/test_customer_language.py runs over the source file."""

    def _assert_clean(self, text, where):
        for pattern, phrase in HARD_BANNED:
            self.assertNotRegex(text, pattern, f"{where}: banned {phrase!r} in {text!r}")
        for pattern, phrase in NEGATION_ONLY:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                window = text[max(0, m.start() - 90):m.start()]
                self.assertTrue(
                    NEGATORS.search(window),
                    f"{where}: {phrase!r} affirmed with no negation in {text!r}")

    def test_full_payload_strings_are_clean(self):
        away_findings = [_finding("a supporting claim", base.AWAY)]
        home_findings = [_finding("a counter claim", base.HOME)]
        entries = [
            _entry(_game("AWY", "HOM", 1),
                  board=_board(away_detail=_side_detail(150, "book1", 0.55),
                              home_detail=_side_detail(-140, "book2", 0.45),
                              books=9),
                  findings=away_findings + home_findings),
            _entry(_game("ZZZ", "YYY", 2), skipped_reason="no board captured"),
        ]
        payload = opp.build_opportunities(entries, date="2026-09-07", now=NOW)
        self._assert_clean(payload["label"], "label")
        self._assert_clean(payload["basis"], "basis")
        for row in payload["rows"]:
            self._assert_clean(row["wager_text"], "wager_text")
            for r in row["reasons"]:
                self._assert_clean(r, "reasons")
            for r in row["risks"]:
                self._assert_clean(r, "risks")
            for c in row["support_claims"] + row["counter_claims"]:
                self._assert_clean(c["statement"], "claim statement")
        for u in payload["unpriced"]:
            self._assert_clean(u["reason"], "unpriced reason")


if __name__ == "__main__":
    unittest.main()
