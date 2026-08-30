"""Funnel tests: every exit door, on one synthetic world, plus the invariant.

The world is built so each of five specs -- one per numeric matrix feature --
takes a different exit: blocked_coverage, screen_dead, no_replication,
killed_by_battery, candidate. Outcomes are controllable per spec because a
spec only ever backs the side its OWN feature advantages: every fired game
here puts the signal on the away side, so "the backed side won" is just
home_won inverted, and disjoint game blocks keep the specs from sharing a
result.

The one test that matters most is the FDR denominator: the correction must
divide by ALL five specs even though three died before producing a pooled p.
That invariant -- the funnel gates spending, never the denominator -- is the
discipline the module exists to protect, and it is asserted explicitly.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src.data import parks
from src.pipeline import slate
from src.research import funnel
from src.research import scoreboard

DOSE = 0.25  # every fired game's |away - home|, comfortably over threshold

# Full club names feed the synthetic odds entries (the odds feed speaks full
# names); the matrix rows carry abbreviations resolved through the SAME two
# helpers selections.index_price_pairs uses, so both ends of the join agree by
# construction rather than by luck.
CARRIER = "New York Yankees"
BATTERY_OTHERS = ("Boston Red Sox", "Chicago Cubs",
                  "Los Angeles Dodgers", "Atlanta Braves")
CANDIDATE_TEAMS = ("Houston Astros", "San Diego Padres", "Texas Rangers",
                   "Toronto Blue Jays", "Baltimore Orioles",
                   "Cleveland Guardians")
SCREEN_TEAM = "Seattle Mariners"
NOREP_TEAM = "Philadelphia Phillies"
OPPONENT = "Miami Marlins"  # never backed, so never a concentration slice

FEATURES = {
    "blocked": "lineup_vs_primary_pitch",
    "screen": "lineup_platoon_share",
    "norep": "top_minus_bottom",
    "battery": "starter_platoon_gap",
    "candidate": "primary_pitch_share",
}


def _abbrev(full_name):
    return parks.canonical_team(slate.team_abbrev_from_name(full_name))


def _spec(name, feature, min_sample=20, direction="positive"):
    return {"name": name, "market": "h2h", "feature": feature,
            "side_rule": "back_advantaged", "threshold": 0.1,
            "min_sample": min_sample, "effect_floor": 0.01,
            "mechanism": "the market prices clubs, not tonight's nine",
            "direction": direction}


class World:
    """Synthetic matrix rows, price pairs and results that join for real."""

    def __init__(self, seasons=(2023, 2024)):
        self.matrix = {s: [] for s in seasons}
        self.pairs = {s: {} for s in seasons}
        self.results = {}
        self._pk = 0

    def add_game(self, season, day, away_full, home_full, home_won,
                 fired_feature=None, event_shift_hours=0):
        """One game: a matrix row, a priced pair and a result.

        `fired_feature` puts DOSE on the away side of that one feature; every
        other numeric feature reads 0.0 on both sides (covered, sub-threshold)
        except the blocked feature, which is None everywhere by design.
        `event_shift_hours` moves the odds event's commence_time off the
        game's own first pitch, to exercise the three-hour join gate.
        """
        self._pk += 1
        pk = str(700000 + self._pk)
        date = (dt.date(season, 4, 1) + dt.timedelta(days=day)).isoformat()
        start = f"{date}T23:10:00Z"

        row = {"game_pk": pk, "date": date, "start_time_utc": start,
               "away_team": _abbrev(away_full), "home_team": _abbrev(home_full)}
        for feature in funnel.NUMERIC_FEATURES:
            if feature == FEATURES["blocked"]:
                away_val = home_val = None
            elif feature == fired_feature:
                away_val, home_val = DOSE, 0.0
            else:
                away_val = home_val = 0.0
            row["away_" + feature] = away_val
            row["home_" + feature] = home_val
        self.matrix[season].append(row)

        # One book per game, alternating by day, both sides -110: the
        # consensus fair is exactly 0.5 so every expected effect is
        # hand-checkable, and the book key still varies for the battery.
        book = "bookA" if day % 2 == 0 else "bookB"
        bookmakers = [{"key": book, "markets": [{"key": "h2h", "outcomes": [
            {"name": home_full, "price": -110},
            {"name": away_full, "price": -110}]}]}]
        commence = start
        if event_shift_hours:
            stamp = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            commence = (stamp + dt.timedelta(hours=event_shift_hours)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.pairs[season][pk] = {
            "event_id": pk, "commence_time": commence,
            "home_team": home_full, "away_team": away_full,
            "open": {"snapshot_at": f"{date}T10:00Z", "gap_minutes": 420.0,
                     "bookmakers": bookmakers},
            "close": {"snapshot_at": f"{date}T22:00Z", "gap_minutes": 70.0,
                      "bookmakers": bookmakers},
            "distinct": True,
        }
        self.results[pk] = {"game_pk": pk, "date": date,
                            "home_won": "1" if home_won else "0"}
        return pk

    def fire(self, season, day, backed_full, want_win, feature):
        """A fired game: the backed team plays AWAY, so backed-won = not
        home_won and the outcome is set per spec without touching sides."""
        self.add_game(season, day, backed_full, OPPONENT,
                      home_won=not want_win, fired_feature=feature)

    def run(self, specs, **kwargs):
        kwargs.setdefault("scoreboard_path", None)
        return funnel.run(specs, matrix_rows=self.matrix,
                          price_pairs=self.pairs, results=self.results,
                          **kwargs)


def _five_spec_world():
    """180 games per season in disjoint blocks, one exit per spec.

    battery block: NYY backed 20 times, all wins; four other clubs 10 each at
    5-5 -- the season effect (+0.1667) replicates, but leaving NYY out leaves
    exactly 50% at implied 0.5, the pre-registered concentration kill.
    candidate block: six clubs backed 10 each at 7 or 6 wins -- the same
    +0.1667 with no club, book or date carrying it.
    screen block: 15-15 in 2023, effect zero, dead at level 1.
    norep block: 21-9 in 2023, 15-15 in 2024, dead at level 2.
    blocked spec: its feature is None on every game, dead at level 0.
    """
    world = World()
    for season in (2023, 2024):
        for i in range(20):  # the carrier: NYY always wins
            world.fire(season, i, CARRIER, True, FEATURES["battery"])
        for i in range(40):  # balanced ballast around the carrier
            world.fire(season, 20 + i, BATTERY_OTHERS[i % 4],
                       (i // 4) % 2 == 0, FEATURES["battery"])
        for i in range(60):  # the real thing: spread 40W/20L per season
            wins_for_team = 7 if i % 6 < 4 else 6
            world.fire(season, 60 + i, CANDIDATE_TEAMS[i % 6],
                       i // 6 < wins_for_team, FEATURES["candidate"])
        for i in range(30):  # screen: a coin flip both seasons
            world.fire(season, 120 + i, SCREEN_TEAM, i % 2 == 0,
                       FEATURES["screen"])
        for i in range(30):  # norep: 2023 shines, 2024 is a coin flip
            want = i < 21 if season == 2023 else i % 2 == 0
            world.fire(season, 150 + i, NOREP_TEAM, want, FEATURES["norep"])
    specs = [_spec(name, feature) for name, feature in FEATURES.items()]
    return specs, world


class SpecValidationTests(unittest.TestCase):
    def test_a_valid_spec_normalizes(self):
        spec = funnel.validate_spec(_spec("ok", FEATURES["screen"]))
        self.assertEqual(spec["threshold"], 0.1)
        self.assertEqual(spec["direction"], "positive")

    def test_mechanism_is_required_and_non_empty(self):
        spec = _spec("m", FEATURES["screen"])
        for bad in (None, "", "   "):
            spec["mechanism"] = bad
            with self.assertRaises(funnel.FunnelError):
                funnel.validate_spec(spec)

    def test_unknown_market_feature_side_rule_direction_raise(self):
        for key, bad in (("market", "totals"),
                         ("feature", "away_lineup_platoon_share"),
                         ("feature", "primary_pitch"),
                         ("side_rule", "back_underdog"),
                         ("direction", "up")):
            spec = _spec("x", FEATURES["screen"])
            spec[key] = bad
            with self.assertRaises(funnel.FunnelError):
                funnel.validate_spec(spec)

    def test_zero_threshold_and_bad_min_sample_raise(self):
        for key, bad in (("threshold", 0), ("threshold", -0.1),
                         ("min_sample", 0), ("min_sample", 2.5),
                         ("effect_floor", 0)):
            spec = _spec("x", FEATURES["screen"])
            spec[key] = bad
            with self.assertRaises(funnel.FunnelError):
                funnel.validate_spec(spec)

    def test_duplicate_names_are_rejected(self):
        specs = [_spec("twin", FEATURES["screen"]),
                 _spec("twin", FEATURES["norep"])]
        with self.assertRaises(funnel.FunnelError):
            World().run(specs)


class RegisterFamilyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "family.json"
        self.specs = [_spec("a", FEATURES["screen"]),
                      _spec("b", FEATURES["norep"])]

    def test_registers_and_freezes(self):
        payload = funnel.register_family(self.specs, self.path)
        self.assertEqual(payload["count"], 2)
        self.assertTrue(self.path.exists())

    def test_identical_reregistration_returns_the_original(self):
        first = funnel.register_family(
            self.specs, self.path,
            now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        again = funnel.register_family(
            self.specs, self.path,
            now=dt.datetime(2026, 2, 2, tzinfo=dt.timezone.utc))
        self.assertEqual(again["registered_at"], first["registered_at"])

    def test_a_changed_family_raises(self):
        funnel.register_family(self.specs, self.path)
        changed = [dict(self.specs[0], threshold=0.2), self.specs[1]]
        with self.assertRaises(funnel.FunnelError):
            funnel.register_family(changed, self.path)


class FunnelExitTests(unittest.TestCase):
    """One run of the five-spec world; every test reads the same output."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.sb_path = Path(cls._tmp.name) / "scoreboard.jsonl"
        cls.specs, cls.world = _five_spec_world()
        cls.rows = cls.world.run(cls.specs, started="2026-08-30T01:00:00Z",
                                 finished="2026-08-30T01:05:00Z",
                                 scoreboard_path=cls.sb_path)
        cls.by_name = {row["name"]: row for row in cls.rows}

    def test_every_exit_door_is_taken(self):
        self.assertEqual(
            {name: row["status"] for name, row in self.by_name.items()},
            {"blocked": "blocked_coverage", "screen": "screen_dead",
             "norep": "no_replication", "battery": "killed_by_battery",
             "candidate": "candidate"})

    def test_levels_reached(self):
        self.assertEqual(
            {name: row["level_reached"] for name, row in self.by_name.items()},
            {"blocked": 0, "screen": 1, "norep": 2, "battery": 3,
             "candidate": 3})

    def test_blocked_coverage_never_builds_selections(self):
        row = self.by_name["blocked"]
        self.assertEqual(row["expected_n"], 0)
        self.assertIsNone(row["n_2023"])

    def test_screen_dead_numbers(self):
        row = self.by_name["screen"]
        # 30 fired 2023 games at 15-15 and implied exactly 0.5: effect zero,
        # which is not "wins more than implied" however you squint.
        self.assertEqual(row["n_2023"], 30)
        self.assertAlmostEqual(row["effect_2023"], 0.0)

    def test_no_replication_flattens_in_2024(self):
        row = self.by_name["norep"]
        self.assertAlmostEqual(row["effect_2023"], 0.2)
        self.assertAlmostEqual(row["effect_2024"], 0.0)

    def test_battery_kill_names_the_concentration_check(self):
        row = self.by_name["battery"]
        self.assertIn("team_concentration", row["battery_fatal"])
        # It replicated honestly before dying -- both seasons +0.1667 -- which
        # is exactly why the battery has to exist.
        self.assertAlmostEqual(row["effect_2023"], round(10 / 60, 5))
        self.assertAlmostEqual(row["effect_2024"], round(10 / 60, 5))

    def test_candidate_survives_everything(self):
        row = self.by_name["candidate"]
        self.assertEqual(row["battery_fatal"], [])
        self.assertTrue(row["q_pass"])
        self.assertEqual(row["n_pooled"], 120)
        self.assertAlmostEqual(row["effect_pooled"], round(20 / 120, 5))
        self.assertLess(row["p_pooled"], 0.01)

    def test_selection_rows_carry_every_battery_key(self):
        # Rebuild one season's selections through the module's own helper and
        # check the battery contract keys are all present and non-None.
        spec = funnel.validate_spec(_spec("candidate", FEATURES["candidate"]))
        from src.model import selections as selections_mod
        index = selections_mod.index_price_pairs(self.world.pairs[2023])
        rows = funnel._selections_for(spec, self.world.matrix[2023], index,
                                      self.world.results, 2023)
        self.assertEqual(len(rows), 60)
        for key in ("date", "season", "side", "team", "book", "price",
                    "implied", "won", "dose"):
            self.assertTrue(all(r[key] is not None for r in rows), key)
        self.assertEqual(rows[0]["implied"], 0.5)
        self.assertEqual(rows[0]["dose"], DOSE)
        self.assertEqual({r["book"] for r in rows}, {"bookA", "bookB"})

    # THE test this module exists for. Three of five specs died before a
    # pooled p existed; the correction still divides by five, with the dead
    # specs entering at p = 1.0. If the denominator ever shrinks to "specs
    # that produced a p", the funnel has become p-hacking with extra steps.
    def test_fdr_denominator_is_the_full_spec_count(self):
        for row in self.rows:
            self.assertEqual(row["fdr_family_size"], len(self.specs))
        for name in ("blocked", "screen", "norep"):
            self.assertEqual(self.by_name[name]["p_fdr"], 1.0)
        # The candidate's BH threshold must be q * rank / 5. Its p and the
        # battery spec's are the only real ones, so its rank is 1 or 2: the
        # threshold is 0.02 or 0.04. Under a survivors-only denominator it
        # would be 0.10 -- catching exactly that regression.
        self.assertIn(self.by_name["candidate"]["fdr_threshold"],
                      (0.02, 0.04))

    def test_scoreboard_records_the_run(self):
        recorded = scoreboard.read(self.sb_path)
        self.assertEqual(len(recorded), 1)
        row = recorded[0]
        self.assertEqual(row["started"], "2026-08-30T01:00:00Z")
        self.assertEqual(row["hypotheses_screened"], 5)
        # blocked_coverage is not a kill: never tested, only unaffordable.
        self.assertEqual(row["hypotheses_killed"], 3)
        self.assertEqual(row["hypotheses_replicated"], 2)
        self.assertEqual(row["survivors"], 1)
        self.assertEqual(row["credits_spent"], 0)

    def test_format_table_lines_up(self):
        text = funnel.format_table(self.rows)
        lines = text.splitlines()
        self.assertEqual(len(lines), 1 + len(self.rows))
        self.assertIn("candidate", text)
        self.assertIn("killed_by_battery", text)
        self.assertIn("team_concentration", text)


class JoinGateTests(unittest.TestCase):
    def test_an_event_five_hours_off_goes_unpriced(self):
        """The 3h _resolve_pair gate must hold here too -- pricing a game
        from its neighbour's market was the catastrophic bug selections.py
        fixed, and the funnel imports that fix rather than re-earning it."""
        world = World()
        for i in range(10):
            want_win = i < 5
            shift = 5 if i == 0 else 0  # game 0's event is 5h adrift (a win)
            world.add_game(2023, i, SCREEN_TEAM, OPPONENT,
                           home_won=not want_win,
                           fired_feature=FEATURES["screen"],
                           event_shift_hours=shift)
        rows = world.run([_spec("gate", FEATURES["screen"], min_sample=5)])
        row = rows[0]
        # Nine selections, not ten: the drifted event is a neighbour, not a
        # price. Losing the win drops the screen to 4-5 and it dies honestly.
        self.assertEqual(row["n_2023"], 9)
        self.assertEqual(row["status"], "screen_dead")


class DirectionTests(unittest.TestCase):
    def test_negative_direction_confirms_on_a_negative_effect(self):
        """direction="negative": the market overrates the feature, so the
        funnel backs the OTHER side at construction time. The advantaged side
        losing more than implied then shows up as a POSITIVE effect for the
        backed side -- one sign convention everywhere, which is what lets the
        battery's positive-effect fatal rules judge every spec identically."""
        world = World()
        teams = CANDIDATE_TEAMS[:4]
        for season in (2023, 2024):
            for i in range(20):
                world.fire(season, i, teams[i % 4], i < 4,
                           FEATURES["candidate"])
        rows = world.run([_spec("fade", FEATURES["candidate"], min_sample=10,
                                direction="negative")])
        row = rows[0]
        self.assertEqual(row["status"], "candidate")
        # +0.3, not -0.3: the flip happened when the selections were built.
        self.assertAlmostEqual(row["effect_pooled"], 0.3)
        self.assertTrue(row["q_pass"])

    def test_positive_direction_kills_the_same_world_at_the_screen(self):
        world = World()
        teams = CANDIDATE_TEAMS[:4]
        for season in (2023, 2024):
            for i in range(20):
                world.fire(season, i, teams[i % 4], i < 4,
                           FEATURES["candidate"])
        rows = world.run([_spec("chase", FEATURES["candidate"],
                                min_sample=10)])
        self.assertEqual(rows[0]["status"], "screen_dead")


class SeasonGuardTests(unittest.TestCase):
    def test_sealed_seasons_are_rejected_structurally(self):
        world = World()
        with self.assertRaises(funnel.FunnelError):
            world.run([_spec("s", FEATURES["screen"])], seasons=(2024, 2025))


if __name__ == "__main__":
    unittest.main()
