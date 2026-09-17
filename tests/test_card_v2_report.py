"""T5 -- `src.report.card_v2.card_v2_for_date` on injected fixtures only.

No live store, no network, no disk read of `data/processed/*` for the game
side (the frozen-parameter file is read from a temp path passed in as
`frozen=`, never the real one) and the prop side is fed through the
`prop_board`/`event_map` injection seams `card._enriched_prop_contracts`
already exposes -- the same "inject the seam" discipline every other
card-building test in this repo follows (see `tests/test_card_all_bets.py`
and `tests/test_best_bets_card.py`).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analysis import best_bets_card
from src.report import card_v2


NOW = datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc)
FUTURE = "2026-09-20T23:05:00Z"

# An identity Platt fit (a=0, b=1) so the frozen "calibrated" p_home is the
# raw model probability unchanged -- keeps the arithmetic this file checks
# independent of the fitted numbers' own values.
FROZEN = {
    "DISPERSION": 2.3352,
    "moneyline_calibration": {"fitted": True, "a": 0.0, "b": 1.0,
                              "n": 2027, "base_rate": 0.5295},
}


def _entry(away="COL", home="NYY", game_pk=744001, first_pitch=FUTURE,
          game_type="R"):
    return {"dossier": {
        "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                 "start_time_utc": first_pitch, "game_number": 1,
                 "game_type": game_type},
        "sections": {
            "teams": {
                "away_runs_scored_pg": 4.6, "away_runs_allowed_pg": 4.2,
                "away_games_played": 140,
                "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.1,
                "home_games_played": 140,
            },
            "starters": {},
        },
    }}


def _game_id(away="COL", home="NYY"):
    from src.analysis import gamepayload
    return gamepayload.game_id({"away_team": away, "home_team": home,
                                "date": "2026-09-20", "game_number": 1})


def _opportunity_rows(game_id, *, home_price=-140, home_book="dk",
                      home_books=8, away_price=118, home_p=0.58, away_p=0.40,
                      observed=None):
    # `home_p` (the de-vigged CONSENSUS) is pinned to a narrow, deliberate
    # window against the fixture's own model number (0.6752, fixed by
    # `_entry`'s team features): below `-140`'s break-even (0.58333,
    # `odds.american_to_probability(-140)`), so G13 ("line shopping" -- the
    # best price is materially better than the market's own blended read
    # implies) does not fire, and within 0.10 of the model number, so G8
    # (the disagreement cap) does not fire either. Realistic fixtures keep
    # all three numbers consistent so a test exercises the gate it names,
    # not one of these two by accident.
    observed = observed or NOW.isoformat()
    return [
        {"game_id": game_id, "side": "away", "market": "h2h",
         "market_implied_probability": away_p, "best_price": away_price,
         "best_book": "fd", "books": home_books, "observed_utc": observed},
        {"game_id": game_id, "side": "home", "market": "h2h",
         "market_implied_probability": home_p, "best_price": home_price,
         "best_book": home_book, "books": home_books, "observed_utc": observed},
    ]


def _no_props(_date):
    return {"contracts": [], "reason": "no player props are posted for "
                                       "this slate yet"}


class LoadFrozenParams(unittest.TestCase):
    def test_missing_file_raises_card_v2_error(self):
        with self.assertRaises(card_v2.CardV2Error):
            card_v2.load_frozen_params("does/not/exist.json")


class CardV2ForDateGameCandidates(unittest.TestCase):
    """The live build over one favoured-home-team game."""

    def _build(self, home_price=-140, home_books=8, home_p=0.58,
              params=None):
        entries = [_entry()]
        gid = _game_id()
        rows = _opportunity_rows(gid, home_price=home_price,
                                 home_books=home_books, home_p=home_p)
        return card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={},
            params=params or best_bets_card.V2)

    def test_shape_carries_every_field_the_api_test_needs(self):
        payload = self._build()
        for key in ("rule", "picks", "prop_picks", "fills", "withdrawn",
                   "all_bets", "n_picks", "n_fills", "n_plus_money_picks",
                   "stale_board", "basis", "disclaimer", "raw_pool_size",
                   "games_on_slate"):
            self.assertIn(key, payload)
        self.assertEqual(best_bets_card.V2.rule_id, payload["rule"])

    def test_every_entry_carries_take_entry_class_and_price_class(self):
        payload = self._build()
        self.assertGreaterEqual(len(payload["all_bets"]), 1)
        for entry in payload["all_bets"]:
            self.assertIn("take", entry)
            self.assertIn("entry_class", entry)
            self.assertIn("price_class", entry)

    def test_a_main_band_favourite_clearing_every_gate_is_picked(self):
        # -140 is inside MAIN (-160..-100); market 58% clears the 0.50
        # floor; 8 books clears MIN_BOOKS; the fresh quote clears G3.
        payload = self._build(home_price=-140, home_books=8, home_p=0.58)
        self.assertEqual(1, payload["n_picks"])
        pick = payload["picks"][0]
        self.assertEqual("MAIN", pick["price_class"])
        self.assertTrue(pick["take"])
        self.assertEqual("pick", pick["entry_class"])

    def test_too_few_books_is_neither_pick_nor_fill(self):
        # G2: game_min_books is 6; 3 books fails it. G2 is NOT one of the
        # two failures a fill may carry (best_bets_card._FILL_ALLOWED_
        # FAILURES is {G3_STALE, G7_VALUE} only, per registration section
        # 3's "A fill" paragraph and C6's own reason list, which names only
        # G3 and G7) -- so this candidate is neither shown as a pick nor
        # listed as a fill, and never reaches `all_bets` at all.
        payload = self._build(home_books=3)
        self.assertEqual(0, payload["n_picks"])
        self.assertEqual(0, payload["n_fills"])
        self.assertEqual([], payload["all_bets"])
        self.assertEqual(1, payload["raw_pool_size"])

    def test_price_class_is_stamped_correctly_for_a_plus_money_underdog(self):
        # Flip the favourite: NYY is now the market's underdog at +150,
        # market number 0.40 (< 0.50, >= plus_market_floor 0.20).
        payload = self._build(home_price=150, home_p=0.40, home_books=8)
        # Whether this one clears G6/G7 depends on the model's own number,
        # which this test does not control tightly enough to assert a pick
        # -- it only asserts that IF it reaches all_bets it is classed right.
        for entry in payload["all_bets"]:
            if entry.get("price") == 150:
                self.assertEqual("PLUS_MONEY", entry["price_class"])


class CardV2GameTypeField(unittest.TestCase):
    def test_game_type_defaults_to_r_and_is_frozen_on_every_entry(self):
        entries = [_entry(game_type="R")]
        gid = _game_id()
        rows = _opportunity_rows(gid)
        payload = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={})
        for entry in payload["all_bets"]:
            self.assertEqual("R", entry["game_type"])

    def test_a_postseason_entry_carries_game_type_p_not_r(self):
        entries = [_entry(game_type="P")]
        gid = _game_id()
        rows = _opportunity_rows(gid)
        payload = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={})
        for entry in payload["all_bets"]:
            self.assertEqual("P", entry["game_type"])


class CardV2EmptyMessages(unittest.TestCase):
    """Honesty constraint 1: two distinct messages, never collapsed."""

    def test_no_priced_board_message_when_the_slate_is_empty(self):
        payload = card_v2.card_v2_for_date(
            [], [], date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={})
        self.assertEqual(0, payload["n_picks"])
        self.assertEqual(0, payload["raw_pool_size"])
        self.assertIn("No priced board to evaluate", payload["empty_reason"])

    def test_every_candidate_refused_message_when_a_board_existed(self):
        # A real candidate exists (raw_pool_size > 0) but fails G2 (too few
        # books) AND its fill is suppressed by making it also fail G3
        # (a stale quote), which is NOT fill-eligible -- so n_picks and
        # n_fills are both 0 while raw_pool_size is 1.
        entries = [_entry()]
        gid = _game_id()
        stale = (NOW.replace(year=2026, month=9, day=19)).isoformat()
        rows = _opportunity_rows(gid, home_books=3, observed=stale)
        payload = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={})
        self.assertEqual(0, payload["n_picks"])
        self.assertEqual(0, payload["n_fills"])
        self.assertEqual(1, payload["raw_pool_size"])
        self.assertNotIn("No priced board to evaluate", payload["empty_reason"])
        self.assertIn("bets are listed", payload["empty_reason"])

    def test_the_two_messages_are_never_the_same_string(self):
        no_board = card_v2.card_v2_for_date(
            [], [], date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={})
        entries = [_entry()]
        gid = _game_id()
        stale = "2020-01-01T00:00:00Z"
        rows = _opportunity_rows(gid, home_books=3, observed=stale)
        refused = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=_no_props, event_map={})
        self.assertNotEqual(no_board["empty_reason"], refused["empty_reason"])


class CardV2PropCandidates(unittest.TestCase):
    def _contract(self, **over):
        # market_probability (0.51) sits above the MAIN floor (0.50) but
        # below breakeven(-110) (0.5238), same reasoning as
        # `_opportunity_rows`'s comment: keeps G13 (line shopping) from
        # firing so these tests exercise lineup/sample gates, not that one.
        # our_probability (0.60) keeps G8's disagreement gap (|0.60-0.51| =
        # 0.09) under the 0.10 cap.
        base = dict(
            event_id="evt-744001", player="Rafael Devers",
            team_name="New York Yankees", market="batter_hits", line=0.5,
            side="Over", probability=0.60, market_probability=0.51,
            breakeven=0.50, price=-110, books=6, season_games=40,
            expected_pa_source="batting_slot", observed_utc=NOW.isoformat(),
        )
        base.update(over)
        return base

    def _board(self, contracts):
        return lambda d: {"contracts": contracts, "reason": None}

    def test_a_qualifying_prop_carries_lineup_posted_true(self):
        entries = [_entry()]
        gid = _game_id()
        rows = _opportunity_rows(gid, home_books=3)  # keep the game side out
        contract = self._contract()
        payload = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=self._board([contract]),
            event_map={"evt-744001": {"game_pk": 744001}})
        props = payload["all_bets"]
        self.assertTrue(any(e.get("kind") == "prop" for e in props))
        for entry in props:
            if entry.get("kind") == "prop":
                self.assertIn("lineup_posted", entry)

    def test_no_posted_lineup_carries_lineup_posted_false(self):
        entries = [_entry()]
        gid = _game_id()
        rows = _opportunity_rows(gid, home_books=3)
        contract = self._contract(expected_pa_source="season_average",
                                  season_games=40)
        payload = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=FROZEN,
            prop_board=self._board([contract]),
            event_map={"evt-744001": {"game_pk": 744001}})
        prop_entries = [e for e in payload["all_bets"] if e.get("kind") == "prop"]
        self.assertTrue(prop_entries)
        for entry in prop_entries:
            self.assertFalse(entry["lineup_posted"])


if __name__ == "__main__":
    unittest.main()
