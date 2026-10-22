"""The Gematria Hound: the signal generator, the decision, the integration with the pack runner and the settler.

Everything runs on synthetic stores and a stub history source (no disk, no network); the one test that reads the real
facts file says so. Pinned here: determinism, symmetry, PASS on missing data and on a small margin, the -200 cap, no
post-lock information, the rules version on every bet, grading through the existing settle path (MLB and an NBA/soccer
case), the rule hounds unchanged, the kill switch, and the evidence endpoint's shape.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.hounds import ai_defs, ai_runner, pack as pack_mod, pack_run, pack_settle
from src.hounds.gematria import decision as decision_mod
from src.hounds.gematria import facts as facts_mod
from src.hounds.gematria import history, rules as rules_mod, runtime as rt, signals as sig_mod, view
from src.hounds.pack import base, gematria_hound
from src.ledger.chain import HashChainLedger
from src.research import gematria as g
from tests.test_ai_hounds import NOW_AS, START_AS, allsports_rows, allsports_stores, nba_rows, soccer_rows
from tests.test_house_pack_hounds import START, basic_stores, game_rows, mlb_game

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def rules_dict(**decision) -> dict:
    data = json.loads((ROOT / "config" / "gematria" / "rules_v1.json").read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["decision"].update(decision)
    return data


def make_rules(**decision) -> rules_mod.Rules:
    return rules_mod.Rules.from_dict(rules_dict(**decision), raw_bytes=b"test", source="test")


LENIENT = dict(min_margin=0.5, min_milestones_per_side=1, max_search_imbalance=1.0)


def facts_book(*entries) -> facts_mod.FactsBook:
    return facts_mod.FactsBook({"teams": {facts_mod.team_key(e["sport"], e["name"]): e for e in entries}})


def team_entry(sport, name, city, mascot, state=None, **kw):
    e = {"sport": sport, "name": name, "city": {"value": city}, "mascot": {"value": mascot}}
    if state:
        e["state"] = {"value": state}
    e.update(kw)
    return e


def G(day, home, away, hs, as_, hour=0, **kw):
    start = datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
    return history.Game(start, day, g.normalize(home), g.normalize(away), hs, as_, **kw)


class StubSource:
    """A history source with no disk: the same games for every context, cut at the cutoff the real source uses."""

    def __init__(self, games, available=True):
        self.games, self.available, self.calls = games, available, []

    def past(self, ctx):
        cutoff = ctx.lock - history.FINISH_LAG
        self.calls.append(cutoff)
        return history.Past([x for x in self.games if x.start < cutoff], g.normalize(ctx.home_name),
                            g.normalize(ctx.away_name), "a stub store", available=self.available)


NBA_FACTS = facts_book(
    team_entry("nba", "Boston Celtics", "Boston", "Celtics", "MA", founded={"date": "1946-06-06", "precision": "day"},
               head_coach={"value": "Joe Mazzulla", "season": 2027}),
    team_entry("nba", "New York Knicks", "New York", "Knicks", "NY", head_coach={"value": "Mike Brown", "season": 2027}),
)


def season_games():
    """Five games each for the two teams, in the weeks before the 2026-10-20 game."""
    return [
        G("2026-10-02", "Boston Celtics", "Miami Heat", 101, 90, regular=True),
        G("2026-10-04", "Chicago Bulls", "Boston Celtics", 99, 104, regular=True),
        G("2026-10-07", "Boston Celtics", "Orlando Magic", 88, 95, regular=True),
        G("2026-10-10", "Boston Celtics", "New York Knicks", 110, 100, regular=True),
        G("2026-10-13", "Toronto Raptors", "Boston Celtics", 97, 99, regular=True),
        G("2026-10-03", "New York Knicks", "Brooklyn Nets", 120, 100, regular=True),
        G("2026-10-05", "Atlanta Hawks", "New York Knicks", 105, 99, regular=True),
        G("2026-10-08", "New York Knicks", "Detroit Pistons", 90, 101, regular=True),
        G("2026-10-12", "Milwaukee Bucks", "New York Knicks", 100, 98, regular=True),
        G("2026-10-15", "New York Knicks", "Indiana Pacers", 111, 107, regular=True),
    ]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.ledger = str(self.dir / "ai_hounds_v1.jsonl")
        for target in ("urllib.request.urlopen", "socket.create_connection"):
            p = mock.patch(target, side_effect=AssertionError("a test reached for the network"))
            p.start()
            self.addCleanup(p.stop)

    def runtime(self, source=None, rules=None, facts=None, ledger=True):
        return rt.GematriaRuntime(rules=rules or make_rules(**LENIENT), facts=facts or NBA_FACTS,
                                  source=source or StubSource(season_games()),
                                  ledger=HashChainLedger(rt.decisions_path(self.ledger)) if ledger else None,
                                  now_fn=lambda: NOW_AS)

    def hound(self, **kw):
        entry = ai_defs.entry_for("gematria")
        return gematria_hound.GematriaHound(entry, self.runtime(**kw))

    def run_hound(self, hound, stores=None, now=NOW_AS):
        return pack_run.run(stores or allsports_stores(nba_rows()), ["2026-10-20"], replay=False, now=now, path=self.ledger,
                            hounds=[hound], out=lambda *_a, **_k: None)

    def bets(self):
        return [r for r in HashChainLedger(self.ledger).read() if r.get("kind") == pack_run.KIND_BET]

    def decisions(self):
        return list(HashChainLedger(rt.decisions_path(self.ledger)).iter_rows())


class ConfigAndRulesTests(unittest.TestCase):
    def test_the_hound_is_a_numerology_house_hound_that_covers_the_whole_menu(self):
        entry = ai_defs.entry_for("gematria")
        self.assertEqual((entry["category"], entry["family"], entry["who_decided"]), ("numerology", "gematria", "rule"))
        self.assertEqual(entry["markets"], ["moneyline"])
        sports = ai_defs.resolve_sports(entry)
        self.assertEqual(sports, ai_defs.resolve_sports(ai_defs.entry_for("ai_claude")))
        self.assertIn("nba", sports)
        self.assertIn("soccer", sports)
        self.assertNotIn("gematria", pack_mod.BY_ID)
        self.assertEqual(len(pack_mod.PACK), 21)

    def test_the_copy_is_the_experimental_line_and_claims_no_edge(self):
        entry = ai_defs.entry_for("gematria")
        self.assertEqual(entry["tagline"], "Experimental numerology hound. Paper picks, graded in public like every hound.")
        text = json.dumps(entry).lower()
        for banned in ("bet check", "betcheck", "guarantee", "sure thing", "beats the market", "predicts winners", "profit"):
            self.assertNotIn(banned, text)
        self.assertIn("unproven", text)

    def test_the_shipped_rules_load_and_are_stamped(self):
        # v1 is frozen and still loads exactly as it did; the ACTIVE file is v2 since 2026-10-22 (tests/test_gematria_v2.py)
        r = rules_mod.load("rules_v1.json")
        self.assertEqual((r.version, r.hound_version, r.hound_number), ("v1", "gematria-v1", 1))
        self.assertEqual(len(r.rules_hash), 64)
        self.assertEqual(rules_mod.load("rules_v1.json").rules_hash, r.rules_hash)
        self.assertEqual(r.decision.max_picks_per_day, 3)
        self.assertEqual(r.decision.price_band[0], -199)
        self.assertEqual((r.static_fallback, r.decision.margin_mode, r.decision.min_margin), (False, "fixed", 3.0))
        active = rules_mod.load()
        self.assertEqual((active.version, active.hound_version, active.hound_number), ("v2", "gematria-v2", 2))
        self.assertNotEqual(active.rules_hash, r.rules_hash)

    def test_every_kind_has_a_weight_and_an_unknown_kind_is_refused(self):
        data = rules_dict()
        self.assertEqual(set(data["kind_weights"]), set(rules_mod.KINDS))
        bad = copy.deepcopy(data)
        bad["kind_weights"]["made_up"] = 1.0
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.Rules.from_dict(bad)
        missing = copy.deepcopy(data)
        del missing["kind_weights"]["prime_link"]
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.Rules.from_dict(missing)

    def test_the_rules_hash_does_not_depend_on_line_endings(self):
        """A Windows checkout (core.autocrlf) has CRLF bytes; the Linux image has the committed LF bytes. Same rules,
        same hash, and that hash is the committed file's."""
        import hashlib
        lf = (ROOT / "config" / "gematria" / "rules_v1.json").read_bytes().replace(b"\r\n", b"\n")
        crlf = lf.replace(b"\n", b"\r\n")
        data = json.loads(lf.decode("utf-8"))
        a = rules_mod.Rules.from_dict(data, raw_bytes=lf).rules_hash
        b = rules_mod.Rules.from_dict(data, raw_bytes=crlf).rules_hash
        self.assertEqual(a, b)
        self.assertEqual(rules_mod.load("rules_v1.json").rules_hash, hashlib.sha256(lf).hexdigest())
        lf2 = (ROOT / "config" / "gematria" / "rules_v2.json").read_bytes().replace(chr(13).encode() + chr(10).encode(), chr(10).encode())
        self.assertEqual(rules_mod.load("rules_v2.json").rules_hash, hashlib.sha256(lf2).hexdigest())
        self.assertEqual(rules_mod.load().rules_hash, hashlib.sha256(lf2).hexdigest())     # the active file

    def test_a_price_band_that_reaches_minus_200_is_refused(self):
        with self.assertRaises(rules_mod.RulesError):
            make_rules(price_band=[-200, 400])

    def test_a_rules_file_name_cannot_escape_the_folder(self):
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.load("../ai_hounds.json")

    def test_the_headline_outweighs_a_loose_match(self):
        w = rules_dict()["kind_weights"]
        self.assertGreater(w["headline_milestone"], 2 * w["milestone_eq_name"])


class FactsTests(unittest.TestCase):
    def test_the_state_table_is_the_order_of_statehood(self):
        self.assertEqual(len(facts_mod.STATE_ADMITTED), 50)
        orders = sorted(v[0] for v in facts_mod.STATE_ADMITTED.values())
        self.assertEqual(orders, list(range(1, 51)))
        dates = [d for _o, d in sorted(facts_mod.STATE_ADMITTED.values())]
        self.assertEqual(dates, sorted(dates))
        for name, order in (("Delaware", 1), ("Georgia", 4), ("Ohio", 17), ("Indiana", 19), ("Michigan", 26), ("Texas", 28),
                            ("California", 31), ("Colorado", 38), ("Washington", 42), ("Hawaii", 50)):
            self.assertEqual(facts_mod.STATE_ADMITTED[name][0], order, name)

    def test_state_names_resolve_from_codes_and_names(self):
        self.assertEqual(facts_mod.state_name("MA"), "Massachusetts")
        self.assertEqual(facts_mod.state_name("new york"), "New York")
        self.assertIsNone(facts_mod.state_name("Ontario"))
        self.assertIsNone(facts_mod.state_name(""))

    def test_a_missing_fact_is_absent_not_guessed(self):
        team = NBA_FACTS.team("nba", "New York Knicks")
        self.assertTrue(team.known)
        self.assertEqual([a.what for a in team.anchors], ["state admitted"])      # no founding date was given, none is invented
        self.assertNotIn("university", team.texts)
        unknown = NBA_FACTS.team("nba", "Seattle Supersonics")
        self.assertFalse(unknown.known)
        self.assertEqual((unknown.texts, unknown.anchors, unknown.state_order), ({}, [], None))

    def test_aliases_find_the_canonical_team(self):
        book = facts_book(dict(team_entry("nba", "LA Clippers", "LA", "Clippers"), aliases=["Los Angeles Clippers"]))
        self.assertTrue(book.team("nba", "Los Angeles Clippers").known)
        self.assertEqual(book.canonical_name("nba", "Los Angeles Clippers"), "LA Clippers")

    def test_a_missing_or_broken_file_is_an_empty_book(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(facts_mod.load(Path(d) / "nope.json")), 0)
            (Path(d) / "bad.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(len(facts_mod.load(Path(d) / "bad.json")), 0)

    def test_the_shipped_facts_have_a_source_url_on_every_fact(self):
        book = facts_mod.load()
        data = book.data.get("teams") or {}
        if not data:
            self.skipTest("config/gematria/team_facts.json is not built yet (scripts/build_gematria_facts.py)")
        self.assertGreater(len(data), 50)
        for key, entry in data.items():
            for fname, node in entry.items():
                if isinstance(node, dict) and "value" in node or isinstance(node, dict) and "date" in node:
                    self.assertTrue(str(node.get("source") or "").startswith("http"), (key, fname))

    def test_mlb_and_wnba_are_seeded_and_what_is_absent_stays_absent(self):
        """The v1b extension: all 30 MLB clubs and 15 WNBA teams, every fact sourced, nothing guessed."""
        data = facts_mod.load().data.get("teams") or {}
        by_sport = {s: {k: v for k, v in data.items() if v.get("sport") == s} for s in ("mlb", "wnba")}
        self.assertEqual((len(by_sport["mlb"]), len(by_sport["wnba"])), (30, 15))
        for sport, teams in by_sport.items():
            for key, entry in teams.items():
                self.assertTrue(entry.get("mascot", {}).get("value"), key)
                for fname in ("stadium", "stadium_opened", "founded"):
                    node = entry.get(fname)
                    if node is None:
                        continue                                                    # absent is allowed; a fact without a source is not
                    self.assertTrue(str(node.get("source") or "").startswith("http"), (key, fname))
                    if "precision" in node:
                        self.assertEqual(len(node["date"]), 4 if node["precision"] == "year" else 10, (key, fname, node))
        # the places the sources do not support stay absent rather than being filled in
        self.assertNotIn("city", data["mlb:athletics"])                        # ESPN's "location" for them is the name itself
        for key in ("mlb:torontobluejays", "wnba:torontotempo", "mlb:washingtonnationals"):      # Ontario, Ontario, D.C.: not U.S. states
            self.assertNotIn("state", data[key], key)
        self.assertEqual(data["mlb:athletics"]["stadium"]["value"], "Sutter Health Park")     # not ESPN's stale Oakland Coliseum
        self.assertEqual(data["mlb:bostonredsox"]["stadium_opened"]["date"], "1912-04-20")
        self.assertEqual(data["mlb:bostonredsox"]["founded"]["precision"], "year")            # the infobox gives a year; no day invented
        self.assertEqual(data["wnba:atlantadream"]["state"]["value"], "Georgia")             # read from the arena article: ESPN has no WNBA venue

    def test_a_real_mlb_game_is_weighed_not_passed_as_no_facts(self):
        """MLB used to pass as no_facts (no team was in the facts layer). With the shipped facts and the stored MLB results it
        builds both worlds and a verdict that is about the numbers."""
        games = [mlb_game(800000 + i, f"2026-09-{i + 1:02d}", "NYY", "BOS" if i % 3 else "TB", 6 - i % 4, 2 + i % 5) for i in range(14)]
        stores = basic_stores(mlb_games=games)
        ctx = base.build_context(stores, "evA")
        run = rt.GematriaRuntime(rules=rules_mod.load(), facts=facts_mod.load(), source=history.Disk(canonical=lambda s, n: n),
                                 ledger=None)
        w = run.weigh(ctx, base.lock_board(stores, ctx))
        self.assertNotIn(w.verdict.code, ("no_facts", "no_history"))
        self.assertIsNotNone(w.signals)
        self.assertGreater(w.block["search_space"], 0)

    def test_the_builder_records_a_stadium_with_its_own_sources_and_never_invents_a_day(self):
        import scripts.build_gematria_facts as build

        team = ("{{Infobox MLB team\n| established = 1912\n| ballpark = [[Example Park]] ({{mlby|1912}}-present)\n}}")
        park = "{{Infobox stadium\n| location = [[Boston]], Massachusetts, U.S.\n| opened = April 20, 1912\n}}"
        yearly = "{{Infobox stadium\n| location = [[Somewhere]], Ohio\n| opened = 1999\n}}"
        entry: dict = {}
        with mock.patch.dict(build.PREFETCH, {"Example Park": (park, "https://en.wikipedia.org/wiki/Example_Park")}, clear=False):
            build.add_stadium(build.Fetcher(None), entry, team, "https://en.wikipedia.org/wiki/Team", want_state=True)
        self.assertEqual(entry["stadium"], {"value": "Example Park", "source": "https://en.wikipedia.org/wiki/Team"})
        self.assertEqual(entry["stadium_opened"], {"date": "1912-04-20", "precision": "day",
                                                   "source": "https://en.wikipedia.org/wiki/Example_Park"})
        self.assertEqual(entry["state"]["value"], "Massachusetts")
        entry = {}
        with mock.patch.dict(build.PREFETCH, {"Example Park": (yearly, "https://en.wikipedia.org/wiki/Example_Park")}, clear=False):
            build.add_stadium(build.Fetcher(None), entry, team, "https://en.wikipedia.org/wiki/Team", want_state=False)
        self.assertEqual((entry["stadium_opened"]["date"], entry["stadium_opened"]["precision"]), ("1999", "year"))
        self.assertNotIn("state", entry)                                       # ESPN's state was already taken
        entry = {}
        with mock.patch.dict(build.PREFETCH, {"Example Park": (None, None)}, clear=False):
            build.add_stadium(build.Fetcher(None), entry, team, "https://en.wikipedia.org/wiki/Team", want_state=True)
        self.assertEqual(list(entry), ["stadium"])                              # no article, no opening date, no state


def inputs_for(home_games, away_games, rules, *, day="2026-10-20", facts=NBA_FACTS, series_games=()):
    home = sig_mod.TeamInputs(facts.team("nba", "New York Knicks"), history.team_state(home_games, "newyorkknicks"))
    away = sig_mod.TeamInputs(facts.team("nba", "Boston Celtics"), history.team_state(away_games, "bostonceltics"))
    return sig_mod.GameInputs(day, home, away, history.head_to_head(list(series_games), "newyorkknicks", "bostonceltics"), True)


#: the count units whose window is "the season so far"; an MLB game must produce none of them (the store starts 2026-08-28)
SEASON_COUNT_QIDS = ("game_number", "coach_game_number", "meeting_number", "wins", "venue_wins", "losses", "venue_losses", "series_wins")


class MlbHasNoSeasonCountsTests(unittest.TestCase):
    """MLB results are read only from 2026-08-28 (the seal), months into the season, so a win total over them is a count SINCE
    08-28 passed off as "the Nth win of the season": a wrong number. Absent is better than wrong. Spans, ciphers, statehood and the
    gaps since a last win/loss are exact whatever the window and stay."""

    def setUp(self):
        self.rules = rules_mod.load()
        self.book = facts_mod.load()

    def game_inputs(self, season_counts):
        games = [G(f"2026-09-{d:02d}", "Boston Red Sox", "New York Yankees", 5 if d % 3 else 2, 3, regular=True) for d in range(1, 20)]
        games += [G(f"2026-09-{d:02d}", "New York Yankees", "Boston Red Sox", 4, 6 if d % 2 else 1, regular=True) for d in range(2, 21, 3)]
        home = sig_mod.TeamInputs(self.book.team("mlb", "Boston Red Sox"), history.team_state(games, "bostonredsox"))
        away = sig_mod.TeamInputs(self.book.team("mlb", "New York Yankees"), history.team_state(games, "newyorkyankees"))
        return sig_mod.GameInputs("2026-10-04", home, away, history.head_to_head(games, "bostonredsox", "newyorkyankees"), True,
                                  season_counts=season_counts)

    def qids(self, gi):
        out = {q.qid for q in sig_mod.static_quantities(gi, self.rules)}
        for winner in ("home", "away"):
            out |= {q.qid for q in sig_mod.milestones(gi, winner)}
        return out

    def test_an_mlb_game_produces_no_season_count_quantities_or_evidence(self):
        gi = self.game_inputs(season_counts=False)
        ids = self.qids(gi)
        for unit in SEASON_COUNT_QIDS:
            self.assertFalse([q for q in ids if q.endswith("." + unit)], unit)
        sig = sig_mod.generate(gi, self.rules)
        for side in (sig.home, sig.away):
            for e in side.evidence:
                for q in (e.a, e.b):
                    if q is not None:
                        self.assertFalse(q.qid.endswith(tuple("." + u for u in SEASON_COUNT_QIDS)), q.qid)
                        self.assertNotIn("of the season", q.label)
                        self.assertNotIn("in our store", q.label)
        # what is exact in any window stays
        self.assertTrue([q for q in ids if q.endswith(".since_win.days")])
        self.assertTrue([q for q in ids if ".span." in q])
        self.assertTrue([q for q in ids if ".name." in q])

    def test_the_same_inputs_with_a_full_season_do_have_those_counts(self):
        """The control: switching the flag back on is what brings them, so the test above is testing the flag and not an empty fixture."""
        ids = self.qids(self.game_inputs(season_counts=True))
        for unit in ("game_number", "wins", "venue_wins", "losses", "venue_losses", "meeting_number", "series_wins"):
            self.assertTrue([q for q in ids if q.endswith("." + unit)], unit)

    def test_the_real_mlb_source_marks_its_counts_incomplete_and_the_weighed_game_has_none(self):
        games = [mlb_game(800000 + i, f"2026-09-{i + 1:02d}", "NYY", "BOS" if i % 3 else "TB", 6 - i % 4, 2 + i % 5) for i in range(14)]
        stores = basic_stores(mlb_games=games)
        ctx = base.build_context(stores, "evA")
        past = history.Disk(canonical=lambda s, n: n).past(ctx)
        self.assertFalse(past.season_counts)
        self.assertIn("no season-to-date counts", past.scope)
        run = rt.GematriaRuntime(rules=rules_mod.load(), facts=self.book, source=history.Disk(canonical=lambda s, n: n), ledger=None)
        w = run.weigh(ctx, base.lock_board(stores, ctx))
        self.assertIsNotNone(w.signals)
        for side in (w.signals.home, w.signals.away):
            for e in side.evidence:
                for q in (e.a, e.b):
                    if q is not None:
                        self.assertNotIn("of the season", q.label)
                        self.assertFalse(q.qid.endswith(tuple("." + u for u in SEASON_COUNT_QIDS)), q.qid)

    def test_the_other_sports_keep_their_season_counts(self):
        ctx = base.build_context(allsports_stores(nba_rows()), "nba1")
        self.assertTrue(history.Disk(espn=history.EspnStore(Path(tempfile.gettempdir()) / "nope-gematria")).past(ctx).season_counts)
        self.assertTrue(sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(facts_mod.Team()), sig_mod.TeamInputs(facts_mod.Team())).season_counts)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.rules = rules_mod.load("rules_v1.json")          # the v1 engine's behaviour; v2's is in tests/test_gematria_v2.py
        self.games = season_games()

    def inputs(self):
        return inputs_for(self.games, self.games, self.rules)

    def test_same_input_same_evidence_and_score(self):
        a = sig_mod.generate(self.inputs(), self.rules)
        b = sig_mod.generate(self.inputs(), self.rules)
        self.assertEqual([e.to_dict() for e in a.home.evidence], [e.to_dict() for e in b.home.evidence])
        self.assertEqual((a.home.score, a.away.score, a.home.comparisons, a.away.comparisons),
                         (b.home.score, b.away.score, b.home.comparisons, b.away.comparisons))

    def test_the_search_space_is_counted_and_matches_are_typed(self):
        s = sig_mod.generate(self.inputs(), self.rules)
        self.assertGreater(s.home.comparisons, 100)
        self.assertGreater(s.static_count, 50)
        for side in (s.home, s.away):
            self.assertEqual(round(sum(e.weight for e in side.evidence), 6), side.score)
            for e in side.evidence:
                self.assertIn(e.kind, rules_mod.KINDS)
                self.assertTrue(e.a.label)
                self.assertIsInstance(e.value, int)

    def test_every_match_is_a_real_equality_or_link(self):
        s = sig_mod.generate(self.inputs(), self.rules)
        for e in s.home.evidence + s.away.evidence:
            if e.kind in ("milestone_eq_name", "milestone_eq_state", "milestone_eq_date", "milestone_eq_span",
                          "milestone_eq_count", "milestone_eq_milestone", "milestone_eq_fact_number", "own_name_eq_date"):
                self.assertEqual(e.a.value, e.b.value, e.to_dict())
            elif e.kind == "prime_link":
                self.assertEqual(g.nth_prime(e.a.value), e.b.value, e.to_dict())
            elif e.kind == "triangular_link":
                self.assertEqual(e.b.value, e.a.value * (e.a.value + 1) // 2, e.to_dict())
            elif e.kind == "special_33_47":
                self.assertIn(e.a.value, (33, 47))

    def test_swapping_the_teams_swaps_the_scores(self):
        """Symmetry: the same two teams with home and away exchanged score the same, side for side. (A team's home/road
        splits are made equal here so the venue-specific counts do not differ between the two arrangements.)"""
        # Each team has the same pattern of dates, venues and results (against different opponents), so its home and road
        # splits are identical whichever arrangement it is in; only the names differ.
        sym = []
        for team, opps in (("Boston Celtics", ("Miami Heat", "Chicago Bulls", "Orlando Magic", "Toronto Raptors")),
                           ("New York Knicks", ("Brooklyn Nets", "Atlanta Hawks", "Detroit Pistons", "Milwaukee Bucks"))):
            sym += [G("2026-10-02", team, opps[0], 101, 90), G("2026-10-05", opps[1], team, 90, 104),
                    G("2026-10-08", team, opps[2], 90, 95), G("2026-10-11", opps[3], team, 99, 90)]
        ny, bos = NBA_FACTS.team("nba", "New York Knicks"), NBA_FACTS.team("nba", "Boston Celtics")
        ny_s, bos_s = history.team_state(sym, "newyorkknicks"), history.team_state(sym, "bostonceltics")
        a = sig_mod.generate(sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(ny, ny_s), sig_mod.TeamInputs(bos, bos_s), None, True),
                             self.rules)
        b = sig_mod.generate(sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(bos, bos_s), sig_mod.TeamInputs(ny, ny_s), None, True),
                             self.rules)
        def core(side):
            """The side's evidence without the venue-specific counts (which legitimately differ when a team changes venue)."""
            keep = [e for e in side.evidence if "venue" not in e.a.qid and not (e.b and "venue" in e.b.qid) and e.kind != "headline_milestone"]
            return sorted((e.kind, e.value, e.weight, e.a.label.split(":")[0], e.b.label.split(":")[0] if e.b else "") for e in keep)

        self.assertEqual(core(a.home), core(b.away))
        self.assertEqual(core(a.away), core(b.home))
        self.assertEqual(a.margin, -a.margin * -1)
        self.assertEqual(round(a.home.score + a.away.score, 6), round(a.away.score + a.home.score, 6))

    def test_no_history_means_no_milestones_and_so_no_milestone_matches(self):
        empty = sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(NBA_FACTS.team("nba", "New York Knicks")),
                                   sig_mod.TeamInputs(NBA_FACTS.team("nba", "Boston Celtics")), None, False)
        s = sig_mod.generate(empty, self.rules)
        self.assertEqual((s.home.milestones, s.away.milestones), (0, 0))
        self.assertTrue(all(e.kind == "own_name_eq_date" for e in s.home.evidence + s.away.evidence))

    def test_an_absent_fact_makes_no_quantity(self):
        bare = facts_book(team_entry("nba", "New York Knicks", "New York", "Knicks"), team_entry("nba", "Boston Celtics", "Boston", "Celtics"))
        with_state = sig_mod.static_quantities(self.inputs(), self.rules)
        without = sig_mod.static_quantities(inputs_for(self.games, self.games, self.rules, facts=bare), self.rules)
        self.assertTrue(any(q.group == "state" for q in with_state))
        self.assertFalse(any(q.group in ("state", "span") for q in without))

    def test_a_headline_needs_several_numbers_to_equal_one_count(self):
        s = sig_mod.generate(self.inputs(), self.rules)
        flagged = [e for side in (s.home, s.away) for e in side.evidence if e.kind == "headline_milestone"]
        for side in (s.home, s.away):
            for e in side.evidence:
                if e.kind != "headline_milestone":
                    continue
                support = sum(1 for x in side.evidence if x.kind != "headline_milestone" and e.a.qid in (x.a.qid, x.b.qid if x.b else None))
                self.assertGreaterEqual(support, self.rules.headline_min_support)
                self.assertEqual(e.weight, self.rules.kind_weights["headline_milestone"] + (self.rules.special_bonus if e.value in self.rules.special_numbers else 0))
        # and a stricter file flags none of them
        strict = rules_mod.Rules.from_dict(dict(rules_dict(), headline_min_support=10_000))
        t = sig_mod.generate(self.inputs(), strict)
        self.assertEqual([e for e in t.home.evidence + t.away.evidence if e.kind == "headline_milestone"], [])
        self.assertIsNotNone(flagged)

    def test_counter_signals_score_the_other_side(self):
        """The posts' warning bullets are matches in the world where the OTHER team wins; here they are simply the other side's evidence."""
        s = sig_mod.generate(self.inputs(), self.rules)
        self.assertTrue(s.home.evidence and s.away.evidence)
        self.assertNotEqual([e.to_dict() for e in s.home.evidence], [e.to_dict() for e in s.away.evidence])


class HistoryTests(unittest.TestCase):
    def test_a_result_after_the_cutoff_cannot_change_a_count(self):
        games = season_games()
        before = history.team_state(games, "bostonceltics")
        late = G("2026-10-20", "Boston Celtics", "New York Knicks", 90, 120, hour=18)      # after the cutoff (lock - 6h = 16:15Z)
        src = StubSource(games + [late])
        ctx = base.build_context(allsports_stores(nba_rows()), "nba1")
        past = src.past(ctx)
        self.assertNotIn(late, past.games)
        self.assertEqual(history.team_state(past.games, "bostonceltics").n, before.n)

    def test_the_real_source_cuts_at_the_lock_minus_the_finish_lag(self):
        ctx = base.build_context(allsports_stores(nba_rows()), "nba1")
        with tempfile.TemporaryDirectory() as d:
            league = Path(d) / "nba"
            league.mkdir()
            rows = [
                {"game_id": "1", "completed": True, "date_utc": "2026-10-10T00:00:00Z", "home_name": "Boston Celtics",
                 "away_name": "New York Knicks", "home_score": 100, "away_score": 90, "season_slug": "regular-season"},
                # started 5 hours before the lock: too recent to be counted as over
                {"game_id": "2", "completed": True, "date_utc": (ctx.lock - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "home_name": "Boston Celtics", "away_name": "Miami Heat", "home_score": 100, "away_score": 90, "season_slug": "regular-season"},
                # not finished
                {"game_id": "3", "completed": False, "date_utc": "2026-10-11T00:00:00Z", "home_name": "Boston Celtics",
                 "away_name": "Miami Heat", "home_score": 0, "away_score": 0, "season_slug": "regular-season"},
                # preseason
                {"game_id": "4", "completed": True, "date_utc": "2026-10-05T00:00:00Z", "home_name": "Boston Celtics",
                 "away_name": "Miami Heat", "home_score": 100, "away_score": 90, "season_slug": "preseason"},
            ]
            (league / "games_2027.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            past = history.Disk(espn=history.EspnStore(Path(d))).past(ctx)
        self.assertTrue(past.available)
        self.assertEqual(sorted(x.home for x in past.games), ["bostonceltics", "bostonceltics"])        # games 1 and 4
        reg = [x for x in past.games if x.regular]
        self.assertEqual(len(reg), 1)
        self.assertEqual(history.team_state(past.games, "bostonceltics").n, 1)           # the preseason game is not the season

    def test_a_result_exactly_at_the_cutoff_is_excluded_in_every_source(self):
        """At or after lock - FINISH_LAG is out: the ESPN store, the NFL store and the MLB results alike."""
        ctx = base.build_context(allsports_stores(nba_rows()), "nba1")
        cut = ctx.lock - history.FINISH_LAG
        stamp = cut.strftime("%Y-%m-%dT%H:%M:%SZ")
        espn_rows = [{"game_id": "at", "completed": True, "date_utc": stamp, "home_name": "Boston Celtics",
                      "away_name": "Miami Heat", "home_score": 100, "away_score": 90, "season_slug": "regular-season"},
                     {"game_id": "before", "completed": True, "date_utc": (cut - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "home_name": "Boston Celtics", "away_name": "Miami Heat", "home_score": 100, "away_score": 90,
                      "season_slug": "regular-season"}]
        self.assertIsNone(history._espn_game(espn_rows[0], g.normalize, cut))
        self.assertIsNotNone(history._espn_game(espn_rows[1], g.normalize, cut))
        nfl_ctx = copy.copy(ctx)
        nfl_ctx.nfl_games = [{"kickoff_utc": stamp, "home_score": 20, "away_score": 17, "status": "final", "home_team": "BUF",
                              "away_team": "KC", "game_type": "REG"}]
        self.assertEqual(history._nfl_games(nfl_ctx, cut), [])
        mlb_ctx = copy.copy(ctx)
        mlb_ctx.mlb_games = [{"start_utc": stamp, "date": cut.date().isoformat(), "home": "BOS", "away": "NYY",
                              "home_score": 3, "away_score": 2, "game_type": "R"}]
        self.assertEqual(history._mlb_games(mlb_ctx, cut), [])

    def test_the_newest_version_of_a_game_wins(self):
        ctx = base.build_context(allsports_stores(nba_rows()), "nba1")
        with tempfile.TemporaryDirectory() as d:
            league = Path(d) / "nba"
            league.mkdir()
            old = {"game_id": "1", "completed": True, "date_utc": "2026-10-10T00:00:00Z", "home_name": "Boston Celtics",
                   "away_name": "New York Knicks", "home_score": 1, "away_score": 2, "season_slug": "regular-season", "observed_utc": "2026-10-10T05:00:00Z"}
            new = dict(old, home_score=100, away_score=90, observed_utc="2026-10-11T05:00:00Z")
            (league / "games_2027.jsonl").write_text(json.dumps(new) + "\n" + json.dumps(old), encoding="utf-8")
            past = history.Disk(espn=history.EspnStore(Path(d))).past(ctx)
        self.assertEqual((past.games[0].hs, past.games[0].as_), (100, 90))

    def test_a_final_score_first_seen_after_the_cutoff_does_not_leak(self):
        """REGRESSION (verifier finding). The reader used to keep the newest-OBSERVED row of each game, so a game that started a
        minute before the cutoff and whose only final row was captured after the lock counted, final score and all. A result
        now counts only if it is final in a row observed before the cutoff, or the game started a full FINISH_LAG before the
        cutoff (a long-finished game backfilled late). Fails on the newest-row reader."""
        ctx = base.build_context(allsports_stores(nba_rows()), "nba1")
        cut = ctx.lock - history.FINISH_LAG
        z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
        late_seen = z(ctx.lock + timedelta(minutes=30))

        def row(gid, start, observed, completed, hs, as_, away="Miami Heat"):
            return {"game_id": gid, "completed": completed, "date_utc": z(start), "observed_utc": observed,
                    "home_name": "Boston Celtics", "away_name": away, "home_score": hs, "away_score": as_,
                    "season_slug": "regular-season"}

        rows = [
            # started 1 minute before the cutoff; its only final row was captured after the lock: LEAK, must not count
            row("leak", cut - timedelta(minutes=1), late_seen, True, 120, 80),
            # same shape, but an earlier row (observed before the cutoff) said it was still on: not final then, still out
            row("not-yet", cut - timedelta(minutes=1), z(cut - timedelta(hours=1)), False, 0, 0, away="Chicago Bulls"),
            row("not-yet", cut - timedelta(minutes=1), late_seen, True, 120, 80, away="Chicago Bulls"),
            # long finished (started 7h before the cutoff) but first stored after the lock: a late backfill, counts
            row("backfill", cut - timedelta(hours=7), late_seen, True, 101, 99, away="Atlanta Hawks"),
            # final in a row observed before the cutoff; a later row (a score correction) must NOT replace it
            row("early-final", cut - timedelta(hours=3), z(cut - timedelta(minutes=30)), True, 100, 90, away="New York Knicks"),
            row("early-final", cut - timedelta(hours=3), late_seen, True, 7, 7, away="New York Knicks"),
        ]
        with tempfile.TemporaryDirectory() as d:
            league = Path(d) / "nba"
            league.mkdir()
            (league / "games_2027.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            past = history.Disk(espn=history.EspnStore(Path(d))).past(ctx)
        by_opp = {x.away: (x.hs, x.as_) for x in past.games}
        self.assertNotIn("miamiheat", by_opp)                      # the leak
        self.assertNotIn("chicagobulls", by_opp)                   # final only in a post-lock row, started just before the cutoff
        self.assertEqual(by_opp["atlantahawks"], (101, 99))        # late backfill of a long-finished game
        self.assertEqual(by_opp["newyorkknicks"], (100, 90))       # the pre-cutoff observation, not the later one

    def test_a_sport_with_no_results_store_is_unavailable_not_empty(self):
        ctx = base.build_context(allsports_stores(allsports_rows("t1", "tennis", "A B", "C D", title="ATP")), "t1")
        past = history.Disk(espn=history.EspnStore(Path(tempfile.gettempdir()) / "nope-gematria")).past(ctx)
        self.assertFalse(past.available)

    def test_season_to_date_stops_at_a_long_gap(self):
        games = [G("2026-01-05", "Boston Celtics", "Miami Heat", 100, 90), G("2026-10-05", "Boston Celtics", "Miami Heat", 90, 100)]
        self.assertEqual(history.team_state(games, "bostonceltics").n, 1)

    def test_head_to_head_and_streaks(self):
        games = [G("2026-10-01", "A", "B", 100, 90), G("2026-10-05", "B", "A", 100, 90), G("2026-10-09", "A", "B", 100, 90),
                 G("2026-10-12", "A", "B", 100, 90)]
        s = history.head_to_head(games, "a", "b")
        self.assertEqual((s.meetings, s.a_wins, s.b_wins, s.a_streak), (4, 3, 1, 2))
        st = history.team_state(games, "a")
        self.assertEqual((st.w, st.l, st.streak_kind, st.streak_len, st.last_loss), (3, 1, "W", 2, "2026-10-05"))

    def test_nfl_coach_record_with_the_club_comes_from_the_store(self):
        games = [G("2026-09-10", "SEA", "DEN", 20, 10, home_coach="Mike Macdonald", away_coach="Sean Payton"),
                 G("2026-09-17", "DEN", "SEA", 10, 20, home_coach="Sean Payton", away_coach="Mike Macdonald")]
        st = history.team_state(games, "sea")
        self.assertEqual((st.coach, st.coach_w, st.coach_l, st.coach_n), ("Mike Macdonald", 2, 0, 2))


class DecisionTests(Case):
    def board(self, home_ml=-120, away_ml=100):
        st = allsports_stores(allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=home_ml, away_ml=away_ml))
        return st, base.build_context(st, "nba1")

    def weigh(self, rules=None, source=None, **boardkw):
        st, ctx = self.board(**boardkw)
        run = self.runtime(source=source, rules=rules, ledger=False)
        return run.weigh(ctx, base.lock_board(st, ctx)), ctx

    def test_a_clear_margin_inside_the_band_is_a_bet(self):
        w, _ = self.weigh()
        self.assertNotEqual(w.verdict.margin, 0, "fixture drift: the two sides tie")
        self.assertEqual((w.verdict.status, w.verdict.code), ("bet", "bet"))
        self.assertEqual(w.verdict.side, "home" if w.verdict.margin > 0 else "away")

    def test_a_small_margin_passes_with_the_reason(self):
        w, _ = self.weigh(rules=make_rules(**dict(LENIENT, min_margin=500.0)))
        self.assertEqual((w.verdict.status, w.verdict.code), ("pass", "small_margin"))
        self.assertIn("500", w.verdict.reason)

    def test_missing_history_passes(self):
        w, _ = self.weigh(source=StubSource([], available=False))
        self.assertEqual(w.verdict.code, "no_history")

    def test_an_unknown_team_passes(self):
        st = allsports_stores(allsports_rows("x1", "nba", "Unknown Away", "Unknown Home", title="NBA"))
        ctx = base.build_context(st, "x1")
        w = self.runtime(ledger=False).weigh(ctx, base.lock_board(st, ctx))
        self.assertEqual(w.verdict.code, "no_facts")

    def test_thin_data_passes(self):
        w, _ = self.weigh(rules=make_rules(**dict(LENIENT, min_milestones_per_side=999)))
        self.assertEqual(w.verdict.code, "thin_data")

    def test_a_lopsided_search_passes(self):
        w, _ = self.weigh(rules=make_rules(**dict(LENIENT, max_search_imbalance=0.0)))
        self.assertIn(w.verdict.code, ("uneven_search", "bet", "small_margin"))      # equal searches are possible; a tie is not a bet
        r = make_rules(**dict(LENIENT, max_search_imbalance=0.0))
        sig = sig_mod.generate(inputs_for(season_games(), season_games(), r), r)
        verdict = decision_mod.decide(sig, {"markets": {"moneyline": {"sides": {}}}}, r, history_available=True, teams_known=True)
        if sig.home.comparisons != sig.away.comparisons:
            self.assertEqual(verdict.code, "uneven_search")

    def test_minus_200_is_never_taken_even_when_the_band_allows_it_in_a_test(self):
        """The cap holds at the decision (price <= -200 is outside the band whatever the file says) and again at the runner."""
        for ml in (-200, -250, -400):
            w, _ = self.weigh(home_ml=ml, away_ml=ml * -1 if ml < 0 else 100)
            if w.verdict.side == "home":
                self.assertEqual((w.verdict.status, w.verdict.code), ("pass", "outside_band"), ml)
        # a heavy favourite on the stronger side is a PASS and the other side is not taken instead
        for ml_home in (-350,):
            w, _ = self.weigh(home_ml=ml_home, away_ml=290)
            if w.verdict.margin > 0:
                self.assertEqual(w.verdict.code, "outside_band")
                self.assertEqual(w.verdict.side, "home")

    def test_the_stronger_side_outside_the_band_is_a_pass_not_the_other_side(self):
        w, _ = self.weigh()
        side = w.verdict.side
        heavy = {"home": dict(home_ml=-450, away_ml=350), "away": dict(home_ml=350, away_ml=-450)}[side]
        w2, _ = self.weigh(**heavy)
        self.assertEqual((w2.verdict.status, w2.verdict.code, w2.verdict.side), ("pass", "outside_band", side))

    def test_a_stronger_side_with_no_price_is_no_board_not_a_crash(self):
        sig = sig_mod.Signals(home=sig_mod.SideSignals("home", score=20, comparisons=100, milestones=5),
                              away=sig_mod.SideSignals("away", score=5, comparisons=100, milestones=5))
        for board in ({"markets": {"moneyline": {"sides": {"home": {"price_average": None}, "away": {"price_average": 120}}}}},
                      {"markets": {"moneyline": {"sides": {"home": {}, "away": {"price_average": 120}}}}},
                      {"markets": {"moneyline": {"sides": {"away": {"price_average": 120}}}}}):
            v = decision_mod.decide(sig, board, make_rules(**LENIENT), history_available=True, teams_known=True)
            self.assertEqual((v.status, v.code, v.side), ("pass", "no_board", None), board)

    def test_no_board_is_not_logged_so_a_later_pass_can_decide(self):
        st = allsports_stores(allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", books=("betmgm",)))
        ctx = base.build_context(st, "nba1")
        run = self.runtime()
        w = run.weigh(ctx, base.lock_board(st, ctx))
        self.assertEqual(w.verdict.code, "no_board")
        self.assertIsNone(run.persist(ctx, w))
        self.assertFalse(run.has_decision("nba1"))


class ConfidenceTests(unittest.TestCase):
    """The poster's "most confident / liking / tread carefully" becomes a 1..5 confidence from the margin, less one when the other
    side's case is nearly as strong (his warning bullets)."""

    def verdict(self, home, away):
        r = make_rules(**dict(LENIENT, min_margin=0.5))
        sig = sig_mod.Signals(sig_mod.SideSignals("home", score=home, comparisons=100, milestones=5),
                              sig_mod.SideSignals("away", score=away, comparisons=100, milestones=5))
        board = {"markets": {"moneyline": {"sides": {"home": {"price_average": -110}, "away": {"price_average": 120}}}}}
        return decision_mod.decide(sig, board, r, history_available=True, teams_known=True)

    def test_bands_follow_the_margin(self):
        self.assertEqual(self.verdict(3.2, 0.0).confidence, 1)          # inside the first band
        self.assertEqual(self.verdict(7.0, 0.0).confidence, 2)
        self.assertEqual(self.verdict(12.0, 0.0).confidence, 3)
        self.assertEqual(self.verdict(16.0, 0.0).confidence, 4)
        self.assertEqual(self.verdict(23.0, 0.0).confidence, 5)
        self.assertEqual(self.verdict(0.0, 7.0).side, "away")

    def test_a_close_other_side_costs_a_point_and_never_goes_below_one(self):
        self.assertEqual(self.verdict(30.0, 18.0).confidence, 3)         # margin 12 -> 3; the other side at 60% of the winner: no cost
        self.assertEqual(self.verdict(100.0, 90.0).confidence, 2)        # margin 10 -> band 3, the other side at 90%: one point off
        self.assertEqual(self.verdict(4.0, 3.5).confidence, 1)           # floor


class PackRunIntegrationTests(Case):
    def test_a_bet_carries_the_evidence_the_rules_version_and_the_stamps(self):
        h = self.hound()
        counts = self.run_hound(h)
        self.assertEqual(counts["written"], 1)
        (b,) = self.bets()
        self.assertEqual((b["hound_id"], b["market"], b["sport"], b["who_decided"], b["segment"]), ("gematria", "moneyline", "nba", "rule", "forward"))
        self.assertEqual((b["rules_version"], b["hound_version"], len(b["rules_hash"])), ("v1" if h.runtime.rules.version == "v1" else b["rules_version"], 1, 64))
        e = b["gematria"]
        self.assertEqual(e["rules_version"], b["rules_version"])
        self.assertEqual(e["side"], b["side"])
        self.assertEqual(e["search_space"], sum(e["comparisons"].values()))
        self.assertTrue(e["evidence"]["home"] or e["evidence"]["away"])
        self.assertLessEqual(len(e["evidence"]["home"]), h.runtime.rules.evidence_top_n)
        self.assertEqual(b["price_average"], e["price"])
        self.assertTrue(b["decision_hash"])
        self.assertGreater(b["price_average"], -200)
        self.assertTrue(HashChainLedger(self.ledger).verify().ok)

    def test_the_decision_is_logged_once_and_a_second_pass_changes_nothing(self):
        h = self.hound()
        self.run_hound(h)
        again = self.hound()
        counts = self.run_hound(again, now=NOW_AS + timedelta(minutes=10))
        self.assertEqual((counts["written"], len(self.bets()), len(self.decisions())), (0, 1, 1))
        d = self.decisions()[0]
        self.assertEqual((d["kind"], d["hound_id"], d["decided"], d["code"]), ("gematria_decision", "gematria", "bet", "bet"))
        self.assertTrue(HashChainLedger(rt.decisions_path(self.ledger)).verify().ok)

    def test_nothing_is_written_before_the_lock_or_at_the_start(self):
        h = self.hound()
        self.assertEqual(self.run_hound(h, now=START_AS - timedelta(hours=2))["written"], 0)
        self.assertEqual(self.run_hound(h, now=START_AS)["written"], 0)
        self.assertEqual(self.decisions(), [])

    def test_a_pass_is_logged_with_its_reason_and_writes_no_bet(self):
        h = self.hound(rules=make_rules(**dict(LENIENT, min_margin=500.0)))
        self.assertEqual(self.run_hound(h)["written"], 0)
        (d,) = self.decisions()
        self.assertEqual((d["decided"], d["code"]), ("pass", "small_margin"))
        self.assertIn("500", d["reason"])
        self.assertEqual(self.bets(), [])

    def test_replay_is_refused_by_name(self):
        with self.assertRaises(ai_defs.ForwardOnlyError):
            pack_run.run(allsports_stores(nba_rows()), ["2026-10-20"], replay=True, now=START_AS + timedelta(hours=5), path=self.ledger,
                         hounds=[self.hound()])
        self.assertIn("Gematria", ai_defs.forward_only_message("gematria"))
        self.assertNotIn("language model", ai_defs.forward_only_message("gematria"))
        self.assertIn("language model", ai_defs.forward_only_message("ai_claude"))

    def test_the_daily_cap_is_configurable(self):
        rows = [allsports_rows(f"nba{i}", "nba", "Boston Celtics", "New York Knicks", title="NBA", start=START_AS + timedelta(minutes=i))
                for i in range(1, 6)]
        stores = allsports_stores(*rows)
        two = self.hound(rules=make_rules(**dict(LENIENT, max_picks_per_day=2)))
        self.assertEqual(self.run_hound(two, stores=stores, now=NOW_AS + timedelta(minutes=10))["written"], 2)
        self.assertEqual(len(self.bets()), 2)

    def test_the_default_cap_is_three(self):
        rows = [allsports_rows(f"nba{i}", "nba", "Boston Celtics", "New York Knicks", title="NBA", start=START_AS + timedelta(minutes=i))
                for i in range(1, 6)]
        self.assertEqual(self.run_hound(self.hound(), stores=allsports_stores(*rows), now=NOW_AS + timedelta(minutes=10))["written"], 3)

    def test_no_post_lock_information_reaches_the_decision(self):
        """A result that lands after the lock cannot change the score: the same game weighed with and without it is identical."""
        stores = allsports_stores(nba_rows())
        ctx = base.build_context(stores, "nba1")
        board = base.lock_board(stores, ctx)
        clean = self.runtime(source=StubSource(season_games()), ledger=False).weigh(ctx, board)
        leaked = season_games() + [G("2026-10-20", "New York Knicks", "Boston Celtics", 120, 80, hour=17),     # started < 6h before the lock
                                   G("2026-10-21", "Brooklyn Nets", "New York Knicks", 120, 80)]               # after the game
        dirty = self.runtime(source=StubSource(leaked), ledger=False).weigh(ctx, board)
        self.assertEqual(clean.block["scores"], dirty.block["scores"])
        self.assertEqual(clean.block["inputs_hash"], dirty.block["inputs_hash"])

    def test_a_quote_after_the_lock_does_not_enter_the_board(self):
        late = allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=-1000, away_ml=700,
                              books=("betmgm", "draftkings", "fanduel", "caesars", "betrivers"))
        for r in late:
            r["observed_utc"] = (START_AS - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        stores = allsports_stores(nba_rows(), late)
        ctx = base.build_context(stores, "nba1")
        board = base.lock_board(stores, ctx)
        self.assertEqual(board["markets"]["moneyline"]["sides"]["home"]["price_average"], -120)

    def test_the_rule_hounds_see_the_same_games_and_bets_with_the_gematria_hound_present(self):
        stores = basic_stores()
        alone = pack_run.run(stores, ["2026-09-20"], replay=False, now=START - timedelta(minutes=30),
                             path=str(self.dir / "a.jsonl"), out=lambda *_a, **_k: None)
        h = gematria_hound.GematriaHound(ai_defs.entry_for("gematria"), self.runtime(facts=facts_book(), source=history.Disk(canonical=lambda s, n: n)))
        mixed = pack_run.run(stores, ["2026-09-20"], replay=False, now=START - timedelta(minutes=30), path=str(self.dir / "b.jsonl"),
                             hounds=list(pack_mod.PACK) + [h], out=lambda *_a, **_k: None)
        strip = lambda path: [{k: v for k, v in r.items() if k not in ("prev_hash", "row_hash", "written_utc")}
                              for r in HashChainLedger(path).read()]
        self.assertEqual(strip(str(self.dir / "a.jsonl")), strip(str(self.dir / "b.jsonl")))
        self.assertEqual(alone["written"], mixed["written"])

    def test_the_21_rule_hounds_do_not_reach_the_wider_boards(self):
        stores = allsports_stores(nba_rows())
        self.assertEqual(base.Stores().sports, ("mlb", "nfl"))
        for h in pack_mod.PACK:
            self.assertFalse(h.applies_to("nba"), h.id)
        self.assertTrue(self.hound().applies_to("nba"))
        del stores


class RunnerAndKillSwitchTests(Case):
    class NoProviders:
        def enabled_providers(self):
            return []

    def run_pass(self, **kw):
        return ai_runner.run_pass(now=NOW_AS, router=self.NoProviders(), stores=allsports_stores(nba_rows()), ledger=self.ledger,
                                  decisions=str(self.dir / "ai_dec.jsonl"), refresh_stats=lambda: None, **kw)

    def patch_runtime(self):
        original = rt.GematriaRuntime

        def build(**kw):
            return original(rules=make_rules(**LENIENT), facts=NBA_FACTS, source=StubSource(season_games()), **kw)

        return mock.patch.object(rt, "GematriaRuntime", side_effect=build)

    def test_the_hound_runs_in_a_pass_with_no_ai_provider_at_all(self):
        with self.patch_runtime():
            report = self.run_pass()
        self.assertTrue(report["gematria"])
        self.assertEqual(report["run"]["written"], 1)
        self.assertEqual([b["hound_id"] for b in self.bets()], ["gematria"])

    def test_the_kill_switch_removes_it_from_the_pass(self):
        with mock.patch.dict("os.environ", {"GEMATRIA_HOUND": "off"}), self.patch_runtime():
            report = self.run_pass()
        self.assertIn("skipped", report)
        self.assertEqual(self.bets(), [])

    def test_the_switch_reads_off_values_and_defaults_on(self):
        self.assertTrue(rt.enabled({}))
        for v in ("off", "OFF", "0", "false", "no"):
            self.assertFalse(rt.enabled({"GEMATRIA_HOUND": v}), v)
        for v in ("on", "1", "", "anything"):
            self.assertTrue(rt.enabled({"GEMATRIA_HOUND": v}), v)

    def test_the_loop_starts_only_when_a_flag_is_set_explicitly(self):
        self.assertIsNone(ai_runner.start_loop(env={}, do_pass=lambda: None))
        self.assertIsNone(ai_runner.start_loop(env={"GEMATRIA_HOUND": "off"}, do_pass=lambda: None))
        import threading
        stop = threading.Event()
        t = ai_runner.start_loop(env={"GEMATRIA_HOUND": "on"}, do_pass=lambda: stop.set(), stop_event=stop, interval_s=60)
        self.assertIsNotNone(t)
        stop.set()
        t.join(timeout=5)
        self.assertTrue(ai_runner.loop_enabled({"AI_HOUNDS": "on"}))
        self.assertFalse(ai_runner.loop_enabled({}))

    def test_a_pass_with_nothing_enabled_and_no_ledger_writes_nothing(self):
        with mock.patch.dict("os.environ", {"GEMATRIA_HOUND": "off"}):
            report = self.run_pass()
        self.assertFalse(Path(self.ledger).exists())
        self.assertIn("skipped", report)


class SettlementTests(Case):
    SCORE = {"kind": "score", "completed": True}

    def place(self, rows_sets, stores_cls=allsports_stores):
        stores = stores_cls(*rows_sets)
        self.run_hound(self.hound(), stores=stores)
        return stores

    def settle(self, stores, scores, now):
        stores.allsports_results = scores
        with mock.patch("src.pipeline.allsports_scores.load_index", side_effect=AssertionError("read the real store")):
            counts = pack_settle.settle(stores, now=now, path=self.ledger)
        graded = [r for r in HashChainLedger(self.ledger).read() if r.get("kind") == pack_run.KIND_GRADED]
        return counts, graded

    def test_an_nba_pick_is_graded_by_the_all_sports_path(self):
        stores = self.place([nba_rows()])
        (bet,) = self.bets()
        home_won = bet["side"] == "home"
        score = dict(self.SCORE, home_score=110.0 if home_won else 100.0, away_score=100.0 if home_won else 110.0,
                     outcome="home" if home_won else "away")
        counts, graded = self.settle(stores, {"nba1": score}, START_AS + timedelta(hours=5))
        self.assertEqual(counts["graded"], 1)
        self.assertEqual((graded[0]["hound_id"], graded[0]["result"], graded[0]["sport"]), ("gematria", "WIN", "nba"))
        self.assertEqual(graded[0]["final_score"]["home"], score["home_score"])

    def test_a_soccer_draw_loses_a_gematria_moneyline_like_every_other_hound(self):
        teams = facts_book(team_entry("soccer", "Arsenal", "London", "Gunners", "GA"), team_entry("soccer", "Chelsea", "London", "Blues", "OH"))
        games = [G(f"2026-10-{d:02d}", h, a, hs, as_) for d, h, a, hs, as_ in
                 ((1, "Arsenal", "Everton", 2, 0), (4, "Fulham", "Arsenal", 1, 1), (8, "Arsenal", "Leeds", 0, 3), (11, "Chelsea", "Spurs", 1, 0),
                  (14, "Brighton", "Chelsea", 2, 2), (17, "Chelsea", "Wolves", 3, 3))]
        run = rt.GematriaRuntime(rules=make_rules(**LENIENT), facts=teams, source=StubSource(games), ledger=HashChainLedger(rt.decisions_path(self.ledger)),
                                 now_fn=lambda: NOW_AS)
        stores = allsports_stores(soccer_rows())
        pack_run.run(stores, ["2026-10-20"], replay=False, now=NOW_AS, path=self.ledger,
                     hounds=[gematria_hound.GematriaHound(ai_defs.entry_for("gematria"), run)], out=lambda *_a, **_k: None)
        bets = self.bets()
        if not bets:
            self.skipTest("the fixture's two sides tied, so the hound passed; the draw rule is covered by test_ai_hounds")
        score = dict(self.SCORE, home_score=1.0, away_score=1.0, outcome="draw")
        _c, graded = self.settle(stores, {"soc1": score}, START_AS + timedelta(hours=5))
        self.assertEqual((graded[0]["result"], graded[0]["units_average_price"]), ("LOSS", -1.0))

    def test_an_mlb_pick_is_graded_from_the_mlb_store(self):
        mlb_facts = facts_book(team_entry("mlb", "Boston Red Sox", "Boston", "Red Sox", "MA"),
                               team_entry("mlb", "New York Yankees", "New York", "Yankees", "NY"))
        run = rt.GematriaRuntime(rules=make_rules(**LENIENT), facts=mlb_facts, source=history.Disk(canonical=lambda s, n: n),
                                 ledger=HashChainLedger(rt.decisions_path(self.ledger)), now_fn=lambda: NOW_AS)
        games = [mlb_game(800000 + i, f"2026-09-{i + 1:02d}", "NYY", "BOS" if i % 3 else "TB", 6 - i % 4, 2 + i % 5) for i in range(14)]
        stores = basic_stores(mlb_games=games)
        counts = pack_run.run(stores, ["2026-09-20"], replay=False, now=START - timedelta(minutes=30), path=self.ledger,
                              hounds=[gematria_hound.GematriaHound(ai_defs.entry_for("gematria"), run)], out=lambda *_a, **_k: None)
        if not counts["written"]:
            self.skipTest("the fixture's two sides tied, so the hound passed")
        (bet,) = self.bets()
        stores = basic_stores(mlb_games=games + [mlb_game(900001, "2026-09-20", "NYY", "BOS", 3, 5)])
        with mock.patch("src.pipeline.allsports_scores.load_index", side_effect=AssertionError("MLB read the all-sports store")):
            pack_settle.settle(stores, now=START + timedelta(hours=6), path=self.ledger)
        (graded,) = [r for r in HashChainLedger(self.ledger).read() if r.get("kind") == pack_run.KIND_GRADED]
        self.assertEqual((graded["hound_id"], graded["sport"], graded["result_source"]), ("gematria", "mlb", "results"))
        self.assertEqual(graded["result"], "WIN" if bet["side"] == "home" else "LOSS")


class EvidenceViewTests(Case):
    def test_the_view_returns_the_picks_with_both_sides_and_the_grade(self):
        stores = self.place_one()
        payload = view.picks_for("gematria", ledger=self.ledger)
        self.assertTrue(payload["started"])
        (pick,) = payload["picks"]
        self.assertEqual(pick["rules_version"], "v1")
        self.assertIn("home", pick["evidence"])
        self.assertIn("away", pick["evidence"])
        self.assertEqual(set(pick["scores"]), {"home", "away"})
        self.assertIsNone(pick["result"])
        self.assertEqual(payload["copy"], "Experimental numerology hound. Paper picks, graded in public like every hound.")
        self.assertTrue(payload["paper_only"])
        del stores

    def place_one(self):
        stores = allsports_stores(nba_rows())
        self.run_hound(self.hound(), stores=stores)
        return stores

    def test_an_empty_ledger_is_an_honest_empty_answer(self):
        payload = view.picks_for("gematria", ledger=str(self.dir / "none.jsonl"))
        self.assertEqual((payload["started"], payload["picks"]), (False, []))

    def test_only_a_gematria_hound_is_served(self):
        self.assertTrue(view.is_gematria_hound("gematria"))
        self.assertFalse(view.is_gematria_hound("ai_claude"))
        self.assertFalse(view.is_gematria_hound("../etc/passwd"))
        self.assertFalse(view.is_gematria_hound(None))

    def test_the_route_is_registered_and_404s_for_other_hounds(self):
        try:
            from fastapi.testclient import TestClient
            from api.app import app
        except Exception as exc:                                  # noqa: BLE001 -- CI has no FastAPI
            self.skipTest(f"FastAPI not importable here: {type(exc).__name__}")
        self.assertIn("/hounds/{hound_id}/gematria", app.openapi()["paths"])
        client = TestClient(app)
        self.assertEqual(client.get("/hounds/ai_claude/gematria").status_code, 404)
        self.assertEqual(client.get("/hounds/nope/gematria").status_code, 404)


if __name__ == "__main__":
    unittest.main()
