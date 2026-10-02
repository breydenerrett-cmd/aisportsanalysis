"""Tests for the automatic UFC result path (src/pipeline/ufc_autograde.py,
src/providers/balldontlie_mma.py, `ufc autograde`).

Every store path is a temp path and every provider is a fake or a fixture
built FROM THE DOCUMENTATION (tests/fixtures/ufc_autograde/, marked as not
captured) -- nothing here touches the real ledger, results store, or network.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.appstate import card_ledger
from src.pipeline import ufc_autograde as ag
from src.pipeline import ufc_results
from src.providers import balldontlie as bdl
from src.providers import balldontlie_mma as bdl_mma
from src.report import ufc_card as ufc_report

FIXTURE = (Path(__file__).parent / "fixtures" / "ufc_autograde"
           / "bdl_mma_docs_shape_2026-09-26.json")
NOW = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)
D1, D2 = "2026-09-22", "2026-09-26"

# The seven picks of docs/audit/2026-10-01/UFC_GRADING.md, as published
# (home, away, picked side, locked price, bout start) -- copied here so the
# test never reads the real evidence ledger.
PICKS = {
    D1: [
        ("g1", "Piero Guaylupo", "Callum Connor", "home", -116.47, "2026-09-22T23:40:00Z"),
        ("g2", "Emilio Quissua", "Damian Piwowarczyk", "away", -134.93, "2026-09-22T22:00:00Z"),
    ],
    D2: [
        ("g3", "Robert Bryczek", "Rodolfo Vieira", "away", -170.54, "2026-09-26T23:15:00Z"),
        ("g4", "Christian Edwards", "Rodolfo Bellato", "away", -178.46, "2026-09-26T22:50:00Z"),
        ("g5", "Raoni Barcelos", "Raul Rosas Jr", "away", -161.59, "2026-09-26T20:30:00Z"),
        ("g6", "Sedriques Dumas", "Mickey Gall", "away", -144.75, "2026-09-26T20:30:00Z"),
        ("g7", "Ailin Perez", "Norma Dumont", "home", -143.32, "2026-09-26T20:30:00Z"),
    ],
}
# What a person typed on 2026-10-01 (data/historical/ufc_results.jsonl).
HAND = {
    D1: [("Piero Guaylupo vs Callum Connor", "win", "Piero Guaylupo"),
         ("Damian Piwowarczyk vs Emilio Quissua", "win", "Damian Piwowarczyk")],
    D2: [("Rodolfo Vieira vs Robert Bryczek", "win", "Rodolfo Vieira"),
         ("Christian Edwards vs Rodolfo Bellato", "win", "Christian Edwards"),
         ("Raul Rosas Jr vs Raoni Barcelos", "win", "Raul Rosas Jr"),
         ("Mickey Gall vs Sedriques Dumas", "cancelled", None),
         ("Ailin Perez vs Norma Dumont", "win", "Ailin Perez")],
}


def pf(fid, a, b, *, winner=None, status=ag.STATUS_FINAL, outcome="auto",
       raw=None, event="E1"):
    if outcome == "auto":
        outcome = ufc_results.OUTCOME_WIN if winner else None
    return ag.ProviderFight(
        provider="fake", event_id=event, fight_id=str(fid), fighter1=a, fighter2=b,
        status=status, raw_status=raw or f"completed/{status}", outcome=outcome,
        winner=winner, fetched_utc=NOW.isoformat())


class FakeProvider(ag.UfcResultsProvider):
    name = "fake"

    def __init__(self, fights=(), error=None):
        self.fights, self.error, self.calls = list(fights), error, 0

    def fetch_fights(self, date, *, now):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.fights)


def bout(home="Fighter A", away="Fighter B", commence=None):
    return ag.BoutIdentity(date=D2, home=home, away=away, game_id="gid",
                           commence_utc=commence)


class ResolveBout(unittest.TestCase):
    def test_win_either_order_takes_spelling_from_the_published_pick(self):
        d = ag.resolve_bout(bout(), [pf(1, "fighter b", "FIGHTER A", winner="fighter a")])
        self.assertEqual((d.action, d.outcome, d.winner),
                         (ag.ACTION_RECORD, "win", "Fighter A"))
        self.assertEqual(d.provenance["provider_fight_id"], "1")

    def test_partial_name_is_not_a_match(self):
        d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter Bee", winner="Fighter A")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("ambiguous", d.reason)

    def test_surname_only_is_not_a_match(self):
        d = ag.resolve_bout(bout("Raul Rosas Jr", "Raoni Barcelos"),
                            [pf(1, "Rosas", "Barcelos", winner="Rosas")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_two_fights_matching_the_pairing_is_ambiguous(self):
        d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter B", winner="Fighter A"),
                                     pf(2, "Fighter B", "Fighter A", winner="Fighter B")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("ambiguous", d.reason)

    def test_non_final_statuses_grade_nothing(self):
        for raw in ("scheduled", "in_progress", "postponed", "delayed",
                    "suspended", "abandoned", "unknown"):
            with self.subTest(raw=raw):
                d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter B",
                                                winner="Fighter A",
                                                status=ag.STATUS_PENDING, raw=raw)])
                self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
                self.assertIn("not final", d.reason)

    def test_provider_cancelled_status_records_cancelled(self):
        d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter B",
                                        status=ag.STATUS_CANCELLED, raw="canceled")])
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "cancelled"))

    def test_draw_and_no_contest(self):
        for outcome in (ufc_results.OUTCOME_DRAW, ufc_results.OUTCOME_NO_CONTEST):
            with self.subTest(outcome=outcome):
                d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter B",
                                                outcome=outcome)])
                self.assertEqual((d.action, d.outcome, d.winner),
                                 (ag.ACTION_RECORD, outcome, None))

    def test_final_with_no_winner_and_no_marker_is_unresolved(self):
        d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter B", outcome=None)])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_winner_who_is_neither_published_fighter_is_unresolved(self):
        d = ag.resolve_bout(bout(), [pf(1, "Fighter A", "Fighter B", winner="Fighter C")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_no_fights_at_all_is_unresolved(self):
        self.assertEqual(ag.resolve_bout(bout(), []).action, ag.ACTION_UNRESOLVED)

    def test_replaced_fighter_means_the_published_pairing_did_not_happen(self):
        d = ag.resolve_bout(
            bout("Sedriques Dumas", "Mickey Gall"),
            [pf(5, "Sedriques Dumas", "Luis Hernandez", winner="Sedriques Dumas")])
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "cancelled"))
        self.assertIn("fighter replaced", d.provenance["basis"])
        self.assertEqual(d.provenance["provider_fight_id"], "5")

    def test_replacement_in_a_fight_not_final_yet_waits(self):
        d = ag.resolve_bout(
            bout("Sedriques Dumas", "Mickey Gall"),
            [pf(5, "Sedriques Dumas", "Luis Hernandez", status=ag.STATUS_PENDING,
                raw="scheduled")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_spelling_variant_of_the_missing_fighter_is_not_a_replacement(self):
        d = ag.resolve_bout(
            bout("Sedriques Dumas", "Mickey Gall"),
            [pf(5, "Sedriques Dumas", "Mickey Gaul", winner="Sedriques Dumas")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("ambiguous", d.reason)

    def test_neither_fighter_on_the_card_is_not_proof_of_cancellation(self):
        d = ag.resolve_bout(bout(), [pf(9, "X One", "Y Two", winner="X One")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)


class RecordResultProvenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "r.jsonl"

    def test_manual_row_is_unchanged(self):
        row = ufc_results.record_result(
            date=D2, fight="A One vs B Two", winner="A One", entered_by="me",
            now=NOW, path=self.path)
        self.assertEqual(set(row), {"date", "fight", "winner", "outcome",
                                    "entered_by", "entered_utc"})

    def test_automatic_row_carries_provenance(self):
        row = ufc_results.record_result(
            date=D2, fight="A One vs B Two", winner="A One", entered_by="auto:fake",
            now=NOW, path=self.path, provider="fake", provider_event_id=7,
            provider_fight_id=9, fetched_utc=NOW.isoformat(),
            raw_status="completed/final", basis="because")
        self.assertEqual(row["provider"], "fake")
        self.assertEqual(row["provider_event_id"], "7")
        self.assertEqual(row["provider_fight_id"], "9")
        self.assertEqual(row["raw_status"], "completed/final")
        self.assertEqual(row["fetched_utc"], NOW.isoformat())
        self.assertEqual(ufc_results.read_all(self.path)[0], row)

    def test_provenance_without_provider_is_refused(self):
        with self.assertRaises(ufc_results.UfcResultsError):
            ufc_results.record_result(
                date=D2, fight="A One vs B Two", winner="A One", entered_by="x",
                now=NOW, path=self.path, raw_status="final")

    def test_a_later_manual_row_supersedes_an_automatic_one(self):
        ufc_results.record_result(
            date=D2, fight="A One vs B Two", winner="A One", entered_by="auto:fake",
            now=NOW, path=self.path, provider="fake")
        ufc_results.record_result(
            date=D2, fight="B Two vs A One", winner="B Two", entered_by="brey",
            now=NOW + timedelta(minutes=1), path=self.path)
        found = ufc_results.result_for_fight(D2, "A One", "B Two", path=self.path)
        self.assertEqual((found["winner"], found["entered_by"]), ("B Two", "brey"))
        self.assertEqual(len(ufc_results.read_all(self.path)), 2)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = str(Path(self.tmp.name) / "cards_mma.jsonl")
        self.results = Path(self.tmp.name) / "ufc_results.jsonl"

    def publish(self, date, picks, ledger=None):
        card = {"date": date, "sport": "mma", "rule": ufc_report.RULE_ID, "count": len(picks),
                "picks": [{
                    "game_id": gid, "rank": i + 1, "sport": "mma", "home_team": home,
                    "away_team": away, "side": side,
                    "team": home if side == "home" else away, "market": "moneyline",
                    "line": None, "price": price, "book": "consensus",
                    "market_probability": 0.6, "model_probability": None,
                    "label": "FAVOURITE", "bet": "test", "why": ["test"],
                    "kickoff_utc": start, "first_pitch_utc": start, "experimental": True,
                } for i, (gid, home, away, side, price, start) in enumerate(picks)]}
        card_ledger.publish(card, now=(NOW - timedelta(days=1)).isoformat(),
                            path=ledger or self.ledger, sport="mma")

    def grade(self, date, provider, **kw):
        return ag.autograde_date(date, provider, now=NOW, ledger_path=self.ledger,
                                 results_path=self.results, **kw)


ONE = [("g1", "Fighter A", "Fighter B", "home", -150.0, "2026-09-26T20:00:00Z")]


class AutogradeDate(Base):
    def test_dry_run_writes_nothing_and_says_why(self):
        self.publish(D2, ONE)
        decisions = self.grade(D2, FakeProvider([pf(1, "Fighter A", "Fighter B",
                                                    winner="Fighter A")]), dry_run=True)
        self.assertEqual(decisions[0].action, ag.ACTION_RECORD)
        self.assertTrue(decisions[0].reason)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_records_one_row_with_provenance_and_auto_entered_by(self):
        self.publish(D2, ONE)
        self.grade(D2, FakeProvider([pf(1, "Fighter A", "Fighter B", winner="Fighter A",
                                        raw="completed/final")]))
        (row,) = ufc_results.read_all(self.results)
        self.assertEqual(row["entered_by"], "auto:fake")
        self.assertEqual((row["provider"], row["provider_event_id"],
                          row["provider_fight_id"], row["raw_status"]),
                         ("fake", "E1", "1", "completed/final"))
        self.assertEqual(row["fetched_utc"], NOW.isoformat())
        self.assertEqual((row["fight"], row["winner"]), ("Fighter A vs Fighter B", "Fighter A"))

    def test_rerun_never_duplicates(self):
        self.publish(D2, ONE)
        provider = FakeProvider([pf(1, "Fighter A", "Fighter B", winner="Fighter A")])
        self.grade(D2, provider)
        second = self.grade(D2, provider)
        self.assertEqual(second[0].action, ag.ACTION_SKIP)
        self.assertEqual(len(ufc_results.read_all(self.results)), 1)

    def test_a_manual_row_is_never_buried_by_a_rerun(self):
        self.publish(D2, ONE)
        ufc_results.record_result(date=D2, fight="Fighter A vs Fighter B", winner="Fighter B",
                                  entered_by="brey", now=NOW, path=self.results)
        decisions = self.grade(D2, FakeProvider(
            [pf(1, "Fighter A", "Fighter B", winner="Fighter A")]))
        self.assertEqual(decisions[0].action, ag.ACTION_SKIP)
        found = ufc_results.result_for_fight(D2, "Fighter A", "Fighter B", path=self.results)
        self.assertEqual((found["winner"], found["entered_by"]), ("Fighter B", "brey"))

    def test_manual_correction_after_an_automatic_row_wins_at_settlement(self):
        self.publish(D2, ONE)
        self.grade(D2, FakeProvider([pf(1, "Fighter A", "Fighter B", winner="Fighter A")]))
        ufc_results.record_result(date=D2, fight="Fighter A vs Fighter B", winner="Fighter B",
                                  entered_by="brey", now=NOW + timedelta(hours=1),
                                  path=self.results)
        row = ufc_report.settle_for_date(D2, now=NOW, path=self.ledger,
                                         results_path=self.results)
        self.assertEqual((row["wins"], row["losses"]), (0, 1))

    def test_bout_that_has_not_started_is_not_fetched_or_graded(self):
        self.publish(D2, [("g1", "Fighter A", "Fighter B", "home", -150.0,
                           "2026-09-27T20:00:00Z")])
        provider = FakeProvider([pf(1, "Fighter A", "Fighter B", winner="Fighter A")])
        decisions = self.grade(D2, provider)
        self.assertEqual(decisions[0].action, ag.ACTION_UNRESOLVED)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_provider_error_records_nothing(self):
        self.publish(D2, ONE)
        with self.assertRaises(ag.ProviderError):
            self.grade(D2, FakeProvider(error=ag.ProviderError("no key")))
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_unresolved_bout_writes_nothing_and_stays_unresolved_at_settlement(self):
        self.publish(D2, ONE)
        d = self.grade(D2, FakeProvider([pf(1, "Fighter A", "Fighter B", winner="Fighter A",
                                            status=ag.STATUS_PENDING, raw="in_progress")]))
        self.assertEqual(d[0].action, ag.ACTION_UNRESOLVED)
        self.assertEqual(ufc_results.read_all(self.results), [])
        row = ufc_report.settle_for_date(D2, now=NOW, path=self.ledger,
                                         results_path=self.results)
        self.assertEqual(row["unresolved"], 1)

    def test_nothing_published_returns_nothing(self):
        self.assertEqual(self.grade(D2, FakeProvider()), [])

    def test_already_graded_picks_are_not_touched(self):
        self.publish(D2, ONE)
        ufc_results.record_result(date=D2, fight="Fighter A vs Fighter B",
                                  winner="Fighter A", entered_by="brey", now=NOW,
                                  path=self.results)
        ufc_report.settle_for_date(D2, now=NOW, path=self.ledger, results_path=self.results)
        self.assertEqual(self.grade(D2, FakeProvider()), [])


class ReplaySevenHandGradedPicks(Base):
    """The audited 2026-10-01 grading, replayed through the automatic path
    with a fake provider returning the same facts, must settle identically."""

    def provider_for(self, date):
        if date == D1:
            return FakeProvider([
                pf(11, "Piero Guaylupo", "Callum Connor", winner="Piero Guaylupo"),
                pf(12, "Damian Piwowarczyk", "Emilio Quissua", winner="Damian Piwowarczyk")])
        return FakeProvider([
            pf(21, "Rodolfo Vieira", "Robert Bryczek", winner="Rodolfo Vieira"),
            pf(22, "Christian Edwards", "Rodolfo Bellato", winner="Christian Edwards"),
            pf(23, "Raul Rosas Jr", "Raoni Barcelos", winner="Raul Rosas Jr"),
            pf(24, "Sedriques Dumas", "Luis Hernandez", winner="Sedriques Dumas"),
            pf(25, "Ailin Perez", "Norma Dumont", winner="Ailin Perez")])

    def settle_all(self, ledger, results):
        rows = {}
        for date in (D1, D2):
            rows[date] = ufc_report.settle_for_date(
                date, now=NOW, path=ledger, results_path=results)
        return rows

    def test_identical_settled_rows(self):
        manual_ledger = str(Path(self.tmp.name) / "manual_cards.jsonl")
        manual_results = Path(self.tmp.name) / "manual_results.jsonl"
        for date in (D1, D2):
            self.publish(date, PICKS[date], ledger=manual_ledger)
            self.publish(date, PICKS[date])
            for fight, outcome, winner in HAND[date]:
                ufc_results.record_result(date=date, fight=fight, winner=winner,
                                          outcome=outcome, entered_by="hand",
                                          now=NOW, path=manual_results)
            decisions = self.grade(date, self.provider_for(date))
            self.assertTrue(all(d.action == ag.ACTION_RECORD for d in decisions),
                            [(d.bout.fight, d.reason) for d in decisions])

        manual = self.settle_all(manual_ledger, manual_results)
        auto = self.settle_all(self.ledger, self.results)

        def view(row):
            return [(p["game_id"], p["result"], p["profit_units"], p.get("reason"))
                    for p in row["picks"]]

        for date in (D1, D2):
            self.assertEqual(view(auto[date]), view(manual[date]))
            for key in ("wins", "losses", "voids", "unresolved", "profit_units"):
                self.assertEqual(auto[date][key], manual[date][key], (date, key))
        wins = sum(auto[d]["wins"] for d in auto)
        losses = sum(auto[d]["losses"] for d in auto)
        voids = sum(auto[d]["voids"] for d in auto)
        self.assertEqual((wins, losses, voids), (5, 1, 1))
        self.assertAlmostEqual(sum(auto[d]["profit_units"] for d in auto), 2.5027, places=4)
        for row in ufc_results.read_all(self.results):
            self.assertEqual(row["entered_by"], "auto:fake")


class BallDontLieProvider(Base):
    def fixture_provider(self):
        return bdl_mma.provider_from_fixture(str(FIXTURE))

    def test_fixture_is_marked_as_built_from_documentation(self):
        self.assertIn("NOT CAPTURED", json.loads(FIXTURE.read_text())["_provenance"])

    def test_parse_documented_fight_shape(self):
        payload = json.loads(FIXTURE.read_text())
        fights = [bdl_mma.parse_fight(f, fetched_utc="t") for f in payload["fights"]["data"]]
        first = fights[0]
        self.assertEqual((first.status, first.outcome, first.winner, first.event_id,
                          first.fight_id), ("final", "win", "Raul Rosas Jr", "90001", "1"))
        self.assertEqual(first.raw_status, "completed/final method=KO/TKO")

    def test_status_state_mapping(self):
        base = {"id": 1, "event": {"id": 2}, "fighter1": {"name": "A One"},
                "fighter2": {"name": "B Two"}, "winner": None}
        for state, expected in (("final", "final"), ("canceled", "cancelled"),
                                ("scheduled", "pending"), ("in_progress", "pending"),
                                ("postponed", "pending"), ("delayed", "pending"),
                                ("suspended", "pending"), ("abandoned", "pending"),
                                ("unknown", "pending"), (None, "pending")):
            self.assertEqual(
                bdl_mma.parse_fight({**base, "status_state": state}, fetched_utc="t").status,
                expected)

    def test_draw_and_no_contest_read_only_from_a_recognised_method(self):
        base = {"id": 1, "event": {"id": 2}, "fighter1": {"name": "A One"},
                "fighter2": {"name": "B Two"}, "winner": None, "status_state": "final"}
        outcome = lambda m: bdl_mma.parse_fight({**base, "result_method": m},
                                                fetched_utc="t").outcome
        self.assertEqual(outcome("Draw"), "draw")
        self.assertEqual(outcome("No Contest"), "no_contest")
        self.assertIsNone(outcome(None))
        self.assertIsNone(outcome("Overturned"))

    def test_fixture_provider_end_to_end_through_the_autograder(self):
        self.publish(D2, PICKS[D2])
        decisions = self.grade(D2, self.fixture_provider())
        by_fight = {d.bout.fight: d for d in decisions}
        self.assertTrue(all(d.action == ag.ACTION_RECORD for d in decisions))
        self.assertEqual(by_fight["Christian Edwards vs Rodolfo Bellato"].winner,
                         "Christian Edwards")
        gall = by_fight["Sedriques Dumas vs Mickey Gall"]
        self.assertEqual(gall.outcome, "cancelled")
        self.assertEqual(gall.provenance["provider"], "balldontlie")
        rows = ufc_results.read_all(self.results)
        self.assertEqual({r["entered_by"] for r in rows}, {"auto:balldontlie"})
        row = ufc_report.settle_for_date(D2, now=NOW, path=self.ledger,
                                         results_path=self.results)
        self.assertEqual((row["wins"], row["losses"], row["voids"]), (3, 1, 1))

    def _client_with_status(self, status):
        def transport(path, params, headers):
            return status, b""
        return bdl.Client("k", transport=transport, sleep=lambda _s: None,
                          config=bdl.ClientConfig(rate_per_minute=100000))

    def test_unentitled_key_is_a_clear_blocker(self):
        provider = bdl_mma.BallDontLieMmaProvider(self._client_with_status(401))
        with self.assertRaises(ag.ProviderError) as ctx:
            provider.fetch_fights(D2, now=NOW)
        self.assertIn("ALL-STAR", str(ctx.exception))

    def test_missing_key_is_a_clear_blocker_and_never_echoes_anything(self):
        with self.assertRaises(ag.ProviderError) as ctx:
            bdl_mma.BallDontLieMmaProvider.from_env({})
        self.assertIn("BALLDONTLIE_API_KEY", str(ctx.exception))


class AutogradeCli(Base):
    def run_cli(self, *extra):
        from src import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["ufc", "autograde", "--date", D2, "--fixture", str(FIXTURE),
                             "--ledger-path", self.ledger,
                             "--results-path", str(self.results), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_prints_decisions_and_writes_nothing(self):
        self.publish(D2, PICKS[D2])
        code, out, _ = self.run_cli("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("WOULD RECORD", out)
        self.assertIn("outcome=cancelled", out)
        self.assertIn("why:", out)
        self.assertIn("dry run -- nothing written", out)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_real_run_writes_then_second_run_skips(self):
        self.publish(D2, PICKS[D2])
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(len(ufc_results.read_all(self.results)), 5)
        self.assertIn("card settle --sport mma", out)
        _, out2, _ = self.run_cli()
        self.assertIn("5 skipped", out2)
        self.assertEqual(len(ufc_results.read_all(self.results)), 5)


if __name__ == "__main__":
    unittest.main()
