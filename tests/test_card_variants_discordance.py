"""T2v: `discordant` is a description (picks only, both directions, split by
price_class) never a statistic. Registration 17.4 clause 2 requires both
directions on every read because G11/G12 can reshuffle when scores change."""

import unittest

from src.analysis import card_variants


def _pick(game_pk, market="moneyline", side="home", line=None, price_class="MAIN",
          kind="game"):
    return {
        "kind": kind,
        "game_pk": game_pk,
        "game_id": game_pk,
        "player_id": None,
        "market": market,
        "side": side,
        "line": line,
        "price_class": price_class,
    }


class TestDiscordant(unittest.TestCase):
    def test_symmetric_no_diff_when_sets_equal(self):
        picks = [_pick(1), _pick(2)]
        a = {"picks": list(picks), "prop_picks": []}
        b = {"picks": list(picks), "prop_picks": []}
        result = card_variants.discordant(a, b)
        self.assertEqual(result["only_a"], [])
        self.assertEqual(result["only_b"], [])
        self.assertEqual(len(result["shared"]), 2)

    def test_superset_case_only_b_is_exactly_the_added_picks(self):
        a = {"picks": [_pick(1)], "prop_picks": []}
        b = {"picks": [_pick(1), _pick(2), _pick(3)], "prop_picks": []}
        result = card_variants.discordant(a, b)
        self.assertEqual(result["only_a"], [])
        self.assertEqual({p["game_pk"] for p in result["only_b"]}, {2, 3})

    def test_mixed_case_both_directions_nonempty(self):
        """One-directional implementations fail this: A drops a pick B
        doesn't have while B adds one A doesn't have."""
        a = {"picks": [_pick(1), _pick(2)], "prop_picks": []}
        b = {"picks": [_pick(2), _pick(3)], "prop_picks": []}
        result = card_variants.discordant(a, b)
        self.assertEqual({p["game_pk"] for p in result["only_a"]}, {1})
        self.assertEqual({p["game_pk"] for p in result["only_b"]}, {3})
        self.assertEqual({p["game_pk"] for p in result["shared"]}, {2})

    def test_reads_picks_only_never_a_fill(self):
        a = {"picks": [], "prop_picks": [], "fills": [_pick(9)]}
        b = {"picks": [_pick(9)], "prop_picks": [], "fills": []}
        result = card_variants.discordant(a, b)
        # The fill in `a` must not be treated as a pick: it is not "shared".
        self.assertEqual(result["only_a"], [])
        self.assertEqual({p["game_pk"] for p in result["only_b"]}, {9})

    def test_splits_by_price_class(self):
        a = {"picks": [_pick(1, price_class="MAIN")], "prop_picks": []}
        b = {
            "picks": [
                _pick(1, price_class="MAIN"),
                _pick(2, price_class="PLUS_MONEY"),
            ],
            "prop_picks": [],
        }
        main_only = card_variants.discordant(a, b, price_class="MAIN")
        self.assertEqual(main_only["only_b"], [])

        plus_only = card_variants.discordant(a, b, price_class="PLUS_MONEY")
        self.assertEqual({p["game_pk"] for p in plus_only["only_b"]}, {2})

    def test_computes_no_statistic(self):
        a = {"picks": [_pick(1)], "prop_picks": []}
        b = {"picks": [_pick(1), _pick(2)], "prop_picks": []}
        result = card_variants.discordant(a, b)
        for forbidden in ("clv", "units", "roi", "win_loss", "p_value"):
            self.assertNotIn(forbidden, {k.lower() for k in result})


if __name__ == "__main__":
    unittest.main()
