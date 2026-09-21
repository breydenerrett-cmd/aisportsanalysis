"""src/analysis/lobo_value.py: the NFL_CARD_V2 value rule with its constants
as arguments.

The parity tests are the point of this file. MLB_VALUE_SHADOW_V1
(docs/PREREG_MLB_VALUE_SHADOW_V1.md) claims to reuse NFL_CARD_V2's method
unchanged; that claim is only true while `lobo_value`, handed NFL_CARD_V2's
constants, produces exactly what `nfl_value.value_candidates` produces. So it
is checked on the NFL test fixtures and on a seeded random sweep of boards
that exercises every branch (stale books, stale boards, thin lines, prices
at the floor, unparseable and un-de-viggable quotes, started games).
"""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import lobo_value as lobo
from src.analysis import nfl_value
from src.core import odds as odds_math

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
KICKOFF = (NOW + timedelta(hours=8)).isoformat().replace("+00:00", "Z")
HOME, AWAY = "Kansas City Chiefs", "Indianapolis Colts"


def _stamp(minutes_ago=0.0):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _row(book, market, *, minutes_ago=0.0, kickoff=KICKOFF, event="ev1", **prices):
    row = {"event_id": event, "commence_time": kickoff, "home_team": HOME,
           "away_team": AWAY, "book": book, "market": market,
           "observed_utc": _stamp(minutes_ago), "book_last_update": _stamp(minutes_ago),
           "sport": "nfl"}
    row.update(prices)
    return row


def _totals(book, over, under, total="44.5", **kw):
    return _row(book, "totals", total=total, over_price=over, under_price=under, **kw)


def _spread(book, home_line, home_price, away_price, **kw):
    return _row(book, "spreads", home_line=str(home_line), home_price=home_price,
                away_line=str(-float(home_line)), away_price=away_price, **kw)


def _h2h(book, home, away, **kw):
    return _row(book, None, home_price=home, away_price=away, **kw)


def _market(n, make):
    return [make(f"book{i}") for i in range(n)]


def _canon(cands):
    """Order-free, float-tolerant canonical form of a candidate list."""
    out = []
    for c in cands:
        out.append((
            c["event_id"], c["market"], c["line"], c["side"], c["price"], c["book"],
            round(c["fair_probability"], 12), round(c["ev"], 12), c["devig_method"],
            tuple(sorted((m, round(v, 12)) for m, v in c["ev_by_method"].items())),
            c["n_other_books"], c["home_team"], c["away_team"], c["commence_time"],
        ))
    return sorted(out, key=repr)


def _both(rows, now=NOW):
    return (_canon(nfl_value.value_candidates(rows, now=now)),
            _canon(lobo.value_candidates_multibook(rows, now=now,
                                                   params=lobo.NFL_CARD_V2_PARAMS)))


class NflConstantsAreCopiedExactly(unittest.TestCase):
    def test_the_copied_params_equal_nfl_value_globals(self):
        p = lobo.NFL_CARD_V2_PARAMS
        self.assertEqual(p.min_other_books, nfl_value.MIN_OTHER_BOOKS)
        self.assertEqual(p.min_ev, nfl_value.MIN_EV)
        self.assertEqual(p.fresh_seconds, nfl_value.FRESH_SECONDS)
        self.assertEqual(p.fresh_board_seconds, nfl_value.FRESH_BOARD_SECONDS)
        self.assertEqual(p.worst_price, nfl_value.WORST_PRICE)
        self.assertEqual(tuple(p.devig_methods), tuple(nfl_value.DEVIG_METHODS))

    def test_lobo_value_never_imports_nfl_value(self):
        # An NFL edit must never silently move an MLB arm.
        import ast
        from pathlib import Path
        tree = ast.parse(Path(lobo.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(f"{node.module}.{a.name}" for a in node.names)
        self.assertFalse([m for m in imported if "nfl_value" in m], imported)


class ParityOnNflFixtures(unittest.TestCase):
    """Every scenario tests/test_nfl_value.py pins, run through both."""

    SCENARIOS = {
        "outlier over": lambda: _market(6, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)],
        "minus 200 home": lambda: _market(6, lambda b: _h2h(b, -300, 300)) + [_h2h("soft", -200, 180)],
        "minus 199 home": lambda: _market(6, lambda b: _h2h(b, -300, 300)) + [_h2h("soft", -199, 180)],
        "stale book": lambda: _market(6, lambda b: _totals(b, -110, -110)) + [_totals("asleep", 120, -140, minutes_ago=120)],
        "lonely number": lambda: _market(6, lambda b: _spread(b, -3.0, -110, -110)) + [_spread("lonely", -3.5, 120, -140)],
        "four others": lambda: _market(4, lambda b: _totals(b, -110, -110)) + [_totals("outlier", 110, -130)],
        "started": lambda: (_market(6, lambda b: _totals(b, -110, -110, kickoff=_stamp(5)))
                            + [_totals("outlier", 110, -130, kickoff=_stamp(5))]),
        "latest only": lambda: (_market(6, lambda b: _totals(b, -110, -110))
                                + [_totals("outlier", 110, -130, minutes_ago=10),
                                   _totals("outlier", -110, -110, minutes_ago=1)]),
        "long dog proportional only": lambda: _market(6, lambda b: _h2h(b, -320, 260)) + [_h2h("soft", -400, 290)],
        "long dog all three": lambda: _market(6, lambda b: _h2h(b, -320, 260)) + [_h2h("soft", -400, 310)],
        "near even total": lambda: _market(6, lambda b: _totals(b, -105, -115)) + [_totals("outlier", 110, -130)],
        "old board": lambda: (_market(6, lambda b: _totals(b, -110, -110, minutes_ago=16 * 60))
                              + [_totals("outlier", 110, -130, minutes_ago=16 * 60)]),
        "board inside the hour": lambda: (_market(6, lambda b: _totals(b, -110, -110, minutes_ago=59))
                                          + [_totals("outlier", 110, -130, minutes_ago=59)]),
    }

    def test_every_scenario_matches(self):
        for name, build in self.SCENARIOS.items():
            with self.subTest(scenario=name):
                nfl, ours = _both(build())
                self.assertEqual(nfl, ours)

    def test_the_scenarios_are_not_all_empty(self):
        non_empty = [n for n, b in self.SCENARIOS.items() if _both(b())[0]]
        self.assertGreaterEqual(len(non_empty), 5, non_empty)


class ParityOnRandomBoards(unittest.TestCase):
    """A seeded sweep. Asserts the sweep produced plenty of candidates, so the
    equality cannot pass by both sides returning nothing."""

    def _random_rows(self, rng):
        rows = []
        for g in range(rng.randint(1, 4)):
            event = f"ev{g}"
            kickoff = (NOW + timedelta(minutes=rng.choice([-30, 20, 180, 600]))
                       ).isoformat().replace("+00:00", "Z")
            board_age = rng.choice([0, 0, 0, 10, 45, 70, 300])
            for b in range(rng.randint(2, 11)):
                book = f"b{b}"
                for market in ("spreads", "totals", "h2h"):
                    for _ in range(rng.randint(1, 2)):
                        age = board_age + rng.choice([0, 0, 1, 5, 20, 29, 31, 40, 90])
                        dog = rng.choice([100, 105, 110, 115, 120, 130, 150, 200, 260, 300, 400])
                        fav = -rng.choice([100, 105, 110, 115, 120, 130, 150, 199, 200, 250, 320, 450])
                        if rng.random() < 0.5:
                            fav, dog = dog, fav
                        kw = dict(minutes_ago=age, kickoff=kickoff, event=event)
                        if market == "spreads":
                            line = rng.choice([-1.5, -1.5, -1.5, 1.5, -2.5])
                            row = _spread(book, line, fav, dog, **kw)
                        elif market == "totals":
                            row = _totals(book, fav, dog, total=rng.choice(["8.5", "8.5", "9.0", "7.5"]), **kw)
                        else:
                            row = _h2h(book, fav, dog, **kw)
                        if rng.random() < 0.03:
                            row["home_price"] = row["over_price"] = None   # unparseable
                        if rng.random() < 0.05:
                            row["book_last_update"] = None                  # capture time only
                        rows.append(row)
        rng.shuffle(rows)
        return rows

    def test_seeded_sweep_matches_and_is_not_vacuous(self):
        rng = random.Random(20260920)
        total = 0
        for trial in range(400):
            rows = self._random_rows(rng)
            nfl, ours = _both(rows)
            self.assertEqual(nfl, ours, f"trial {trial}")
            total += len(nfl)
        self.assertGreater(total, 100, "the sweep must exercise the candidate path")


class ParameterisedRules(unittest.TestCase):
    """The constants really are arguments -- the MLB arms depend on it."""

    def _quote(self, book, over, under, *, minutes_ago=0.0, line_key=("p", "1.5")):
        return {"book": book, "line_key": line_key,
                "pair": (("over", 1.5, over), ("under", 1.5, under)),
                "quote_time": NOW - timedelta(minutes=minutes_ago), "meta": {"book": book}}

    def _params(self, **kw):
        base = dict(min_other_books=2, min_ev=0.02, fresh_seconds=1800,
                    fresh_board_seconds=3600, worst_price=-200)
        base.update(kw)
        return lobo.LoboParams(**base)

    def test_min_other_books_is_the_argument(self):
        quotes = [self._quote("x", -110, -110), self._quote("y", -110, -110),
                  self._quote("soft", 110, -130)]
        two = lobo.judge_board(quotes, now=NOW, params=self._params(min_other_books=2))
        three = lobo.judge_board(quotes, now=NOW, params=self._params(min_other_books=3))
        self.assertEqual([c["book"] for c in two["candidates"]], ["soft"])
        self.assertEqual(three["candidates"], [])
        self.assertEqual(three["lines_judged"], 0)

    def test_worst_price_is_the_argument(self):
        quotes = [self._quote("x", -300, 250), self._quote("y", -300, 250),
                  self._quote("soft", -150, 120)]
        loose = lobo.judge_board(quotes, now=NOW, params=self._params(worst_price=-400))
        strict = lobo.judge_board(quotes, now=NOW, params=self._params(worst_price=-150))
        self.assertTrue([c for c in loose["candidates"] if c["side"] == "over"])
        self.assertFalse([c for c in strict["candidates"] if c["side"] == "over"])

    def test_book_freshness_is_the_argument(self):
        quotes = [self._quote("x", -110, -110), self._quote("y", -110, -110),
                  self._quote("soft", 110, -130, minutes_ago=20)]
        wide = lobo.judge_board(quotes, now=NOW, params=self._params(fresh_seconds=1800))
        narrow = lobo.judge_board(quotes, now=NOW, params=self._params(fresh_seconds=600))
        self.assertTrue(wide["candidates"])
        self.assertFalse(narrow["candidates"])

    def test_a_book_twice_on_one_line_is_dropped_from_that_line(self):
        quotes = [self._quote("x", -110, -110), self._quote("y", -110, -110),
                  self._quote("soft", 110, -130), self._quote("soft", 115, -135)]
        out = lobo.judge_board(quotes, now=NOW, params=self._params())
        self.assertEqual(out["candidates"], [])

    def test_the_reported_ev_is_the_lowest_of_the_methods(self):
        quotes = [self._quote("x", -320, 260), self._quote("y", -320, 260),
                  self._quote("soft", -400, 310)]
        out = lobo.judge_board(quotes, now=NOW, params=self._params())
        dog = [c for c in out["candidates"] if c["side"] == "under"][0]
        self.assertEqual(dog["ev"], min(dog["ev_by_method"].values()))
        self.assertEqual(dog["fair_probability"], min(dog["fair_by_method"].values()))
        expected = {}
        for m in lobo.DEVIG_METHODS:
            _, fair = odds_math.devig_two_way(-320, 260, method=m)
            expected[m] = fair * odds_math.american_to_decimal(310) - 1.0
        for m in lobo.DEVIG_METHODS:
            self.assertAlmostEqual(dog["ev_by_method"][m], expected[m], places=12)

    def test_canonical_sha256_ignores_key_order(self):
        self.assertEqual(lobo.canonical_sha256({"a": 1, "b": [1, 2]}),
                         lobo.canonical_sha256({"b": [1, 2], "a": 1}))


if __name__ == "__main__":
    unittest.main()
