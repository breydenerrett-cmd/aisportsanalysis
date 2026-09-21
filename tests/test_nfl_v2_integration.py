"""NFL_CARD_V2 wired into the ledger, the publisher, the CLI and the API.

Built 2026-09-20/21 from the adversarial review of the V2 change, before any
V2 pick was published. Each test class pins one confirmed finding; every one
of them failed against the code as it stood when the review ran:

  * one bet per game, across publishes, not only within one run;
  * the V1/V2 "never mix rules on one date" guard on the REAL publish path
    (`card publish --sport nfl`, what scripts/capture_slot.sh runs), not
    only on `publish_for_date`;
  * the record calendar never lists a retired rule's days as PENDING;
  * a graded NFL pick is joined to its published pick by game, never rank;
  * /card/record?sport=nfl verifies and counts the NFL ledger's own chain;
  * a frozen NFL card carries its basis/disclaimer, and no NFL card claims
    "our own probabilities are running uncalibrated";
  * an empty card after every kickoff says so, not "looked and declined".

Every ledger here is a temp file; nothing reads data/ or evidence/ and
nothing touches the network.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.analysis import nfl_card as nfl_v1
from src.analysis import nfl_value
from src.appstate import card_ledger
from src.report import nfl_card

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

V1 = "NFL_CARD_V1"
V2 = nfl_value.RULE_ID
DATE = "2026-09-27"
KICKOFF = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
HOME, AWAY = "Detroit Lions", "New York Jets"
GID = "2026_03_NYJ_DET"


def _z(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _row(book, market, at, kickoff, *, home=HOME, away=AWAY, event="ev-nyj-det",
         **prices):
    row = {"event_id": event, "commence_time": _z(kickoff), "home_team": home,
           "away_team": away, "book": book, "market": market,
           "observed_utc": _z(at), "book_last_update": _z(at), "sport": "nfl"}
    row.update(prices)
    return row


def _spreads(at, kickoff, home_line, soft_home, soft_away, **kw):
    """Six books at -110/-110 on `home_line` (every de-vig method puts each
    side at exactly 50%) and one "soft" book at `soft_home`/`soft_away`."""
    def quote(book, hp, ap):
        return _row(book, "spreads", at, kickoff, home_line=str(home_line),
                    away_line=str(-home_line), home_price=hp, away_price=ap, **kw)
    return [quote(f"book{i}", -110, -110) for i in range(6)] + [quote("soft", soft_home, soft_away)]


def _totals(at, kickoff, total, soft_over, soft_under, **kw):
    def quote(book, op, up):
        return _row(book, "totals", at, kickoff, total=str(total),
                    over_price=op, under_price=up, **kw)
    return [quote(f"book{i}", -110, -110) for i in range(6)] + [quote("soft", soft_over, soft_under)]


def _entries(kickoff=KICKOFF, game_id=GID, home=HOME, away=AWAY):
    return [{"game_id": game_id, "week": 3, "home_team": home, "away_team": away,
             "kickoff_utc": _z(kickoff)}]


def _picks_on(row, game_id=GID):
    return [p for p in (row.get("picks") or []) if p.get("game_id") == game_id]


class _TempLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = str(Path(self._tmp.name) / "cards_nfl.jsonl")
        self.mlb_path = str(Path(self._tmp.name) / "cards_mlb.jsonl")

    def _rows(self):
        return list(card_ledger._ledger(self.path).read())


# ---------------------------------------------------------------------------
# [1][4] ONE BET PER GAME, ACROSS PUBLISHES
# ---------------------------------------------------------------------------

class OneBetPerGameAcrossPublishes(_TempLedger):
    """`nfl_value.select` keeps one pick per game WITHIN one run. The ledger
    used to key an NFL pick on (game_id, market, line), so a later run whose
    best line on an already-locked game had moved (another number, the other
    side, another market) got a new key and was locked straight in beside
    the first -- two, sometimes opposite, graded bets on one game."""

    def test_a_moved_spread_never_adds_a_second_bet_on_a_locked_game(self):
        t1 = KICKOFF - timedelta(hours=3, minutes=30)          # inside the 4h lock
        first = nfl_card.publish_for_date(
            DATE, now=t1, entries=_entries(),
            rows=_spreads(t1, KICKOFF, -6.5, 105, -125), path=self.path)
        self.assertTrue(first["picks"][0]["locked"])
        self.assertIn("Detroit Lions -6.5", first["picks"][0]["bet"])

        t2 = KICKOFF - timedelta(hours=1, minutes=55)          # the board flipped
        nfl_card.publish_for_date(
            DATE, now=t2, entries=_entries(),
            rows=_spreads(t2, KICKOFF, -7.0, -126, 106), path=self.path)

        newest = card_ledger.published_row(DATE, path=self.path)
        on_game = _picks_on(newest)
        self.assertEqual(len(on_game), 1, [p["bet"] for p in on_game])
        self.assertIn("Detroit Lions -6.5", on_game[0]["bet"])
        self.assertEqual(on_game[0]["price"], 105)
        self.assertTrue(on_game[0]["locked"])

        settled = card_ledger.settle(DATE, {GID: {"home_score": 27, "away_score": 20}},
                                     path=self.path, sport="nfl")
        self.assertEqual(settled["n_picks"], 1)

    def test_the_provisional_pick_locks_and_blocks_the_next_runs_different_market(self):
        """The ordinary T-6h -> T-2h transition: an unlocked pick from the
        earlier run is locked AS LAST PUBLISHED by the first run inside the
        window, and that run's own (different) pick on the game is refused."""
        t1 = KICKOFF - timedelta(hours=6)
        first = nfl_card.publish_for_date(
            DATE, now=t1, entries=_entries(),
            rows=_spreads(t1, KICKOFF, -6.5, 105, -125), path=self.path)
        self.assertFalse(first["picks"][0]["locked"])

        t2 = KICKOFF - timedelta(hours=3, minutes=55)
        nfl_card.publish_for_date(
            DATE, now=t2, entries=_entries(),
            rows=_totals(t2, KICKOFF, 44.5, 108, -128), path=self.path)

        on_game = _picks_on(card_ledger.published_row(DATE, path=self.path))
        self.assertEqual(len(on_game), 1, [p["bet"] for p in on_game])
        self.assertEqual(on_game[0]["market"], "spread")
        self.assertTrue(on_game[0]["locked"])

    def test_an_unlocked_pick_is_still_replaced_by_a_better_read(self):
        """Outside the window nothing is a bet of record yet: a new read on
        the same game replaces the provisional pick (never joins it)."""
        t1 = KICKOFF - timedelta(hours=8)
        nfl_card.publish_for_date(
            DATE, now=t1, entries=_entries(),
            rows=_spreads(t1, KICKOFF, -6.5, 105, -125), path=self.path)
        t2 = KICKOFF - timedelta(hours=7)
        nfl_card.publish_for_date(
            DATE, now=t2, entries=_entries(),
            rows=_totals(t2, KICKOFF, 44.5, 108, -128), path=self.path)

        on_game = _picks_on(card_ledger.published_row(DATE, path=self.path))
        self.assertEqual([p["market"] for p in on_game], ["total"])
        self.assertFalse(on_game[0]["locked"])

    def test_the_ledger_itself_keeps_one_nfl_pick_per_game(self):
        """Belt and braces under the publisher: `card_ledger.publish` alone,
        handed a second NFL pick on a locked game, carries the locked one and
        drops the newcomer."""
        spread = {"game_id": GID, "sport": "nfl", "rank": 1, "market": "spread",
                  "line": -6.5, "side": "home", "price": 105, "bet": "Take Detroit Lions -6.5 at +105",
                  "first_pitch_utc": _z(KICKOFF)}
        total = {"game_id": GID, "sport": "nfl", "rank": 1, "market": "total",
                 "line": 44.5, "side": "over", "price": 108, "bet": "Over 44.5",
                 "first_pitch_utc": _z(KICKOFF)}
        card_ledger.publish({"date": DATE, "rule": V2, "picks": [spread]},
                            now=_z(KICKOFF - timedelta(hours=3)), path=self.path, sport="nfl")
        row = card_ledger.publish({"date": DATE, "rule": V2, "picks": [total]},
                                  now=_z(KICKOFF - timedelta(hours=2)), path=self.path, sport="nfl")
        self.assertEqual([p["market"] for p in row["picks"]], ["spread"])

    def test_mlb_keeps_its_own_pick_key(self):
        """MLB is untouched: its key is still (game_pk, market, line)."""
        pick = {"game_pk": 745001, "market": "run_line", "line": -1.5}
        self.assertEqual(card_ledger._pick_key(pick), ("745001", "run_line", -1.5))


# ---------------------------------------------------------------------------
# [3] THE V1/V2 GUARD ON THE REAL PUBLISH PATH
# ---------------------------------------------------------------------------

class RuleGuardOnTheCliPublishPath(_TempLedger):
    """scripts/capture_slot.sh runs `card publish --sport nfl` every ~13
    minutes. That CLI branch used to build with `card_for_date` and write
    with `card_ledger.publish` directly, so `publish_for_date`'s refusal to
    put V2 onto a date already carrying a V1 card never ran in production:
    the V1 favourite was locked into a row stamped NFL_CARD_V2 and counted in
    V2's record."""

    def _seed_v1(self, kickoff, published_at):
        card_ledger.publish(
            {"date": DATE, "rule": V1, "picks": [{
                "game_id": "2026_03_NYJ_DAL", "sport": "nfl", "rank": 1,
                "market": "moneyline", "line": None, "side": "home", "price": -278,
                "bet": "Take Dallas Cowboys to win at -278",
                "first_pitch_utc": _z(kickoff)}]},
            now=_z(published_at), path=self.path, sport="nfl")

    def test_cli_publish_refuses_a_date_that_already_carries_a_v1_card(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        kickoff = now + timedelta(hours=2)
        self._seed_v1(kickoff, now - timedelta(hours=5))
        before = self._rows()

        args = argparse.Namespace(card_command="publish", sport="nfl",
                                  date=DATE, dry_run=False)
        with mock.patch("src.appstate.card_ledger.store_path", return_value=self.path), \
             mock.patch("src.pipeline.nfl_slate.entries_for_date",
                        return_value=_entries(kickoff=kickoff)), \
             mock.patch("src.pipeline.snapshots.read_multibook",
                        return_value=_spreads(now, kickoff, -6.5, 105, -125)):
            from src import cli
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.cmd_card(args)

        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(len(self._rows()), len(before), out.getvalue())
        newest = card_ledger.published_row(DATE, path=self.path)
        self.assertEqual(newest["rule"], V1)
        self.assertIn(V1, out.getvalue())
        self.assertNotIn("published:", out.getvalue())

    def test_publish_for_date_and_the_cli_build_through_one_function(self):
        """One guard, one place: both publishers call `card_to_publish`."""
        refusal = {"date": DATE, "sport": "nfl", "rule": V2, "picks": [], "count": 0,
                   "reason": "refused for the test", "refused": True}
        with mock.patch.object(nfl_card, "card_to_publish", return_value=refusal) as shared:
            out = nfl_card.publish_for_date(DATE, now=KICKOFF, path=self.path)
            self.assertEqual(out, {"published": False, "reason": "refused for the test"})
            from src import cli
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.cmd_card(argparse.Namespace(card_command="publish", sport="nfl",
                                                date=DATE, dry_run=True))
        self.assertEqual(shared.call_count, 2)
        self.assertIn("refused for the test", buf.getvalue())

    def test_the_ledger_refuses_to_merge_two_rules_on_one_nfl_date(self):
        kickoff = KICKOFF
        self._seed_v1(kickoff, kickoff - timedelta(hours=7))
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.publish(
                {"date": DATE, "rule": V2, "picks": [{
                    "game_id": GID, "sport": "nfl", "rank": 1, "market": "spread",
                    "line": -6.5, "side": "home", "price": 105, "bet": "x",
                    "first_pitch_utc": _z(kickoff)}]},
                now=_z(kickoff - timedelta(hours=2)), path=self.path, sport="nfl")


# ---------------------------------------------------------------------------
# [5][13][19] THE CALENDAR NEVER SHOWS A RETIRED RULE'S DAYS AS PENDING
# [6] THE GRADED -> PUBLISHED JOIN IS BY GAME, NEVER RANK
# ---------------------------------------------------------------------------

def _pick(game_id, *, rank=1, market="moneyline", line=None, side="home",
          price=-150, bet=None, home="Buffalo Bills", away="Miami Dolphins",
          book="bookA", kickoff="2026-09-17T17:00:00Z"):
    return {"game_id": game_id, "sport": "nfl", "rank": rank, "market": market,
            "line": line, "side": side, "price": price,
            "bet": bet or f"Take {home} at {price}", "label": "LEAN",
            "home_team": home, "away_team": away, "book": book,
            "first_pitch_utc": kickoff}


class HistoryUnderOneRule(_TempLedger):
    def _two_rule_ledger(self):
        # V1: 09-17 published and settled; 09-20 published, not yet settled.
        card_ledger.publish({"date": "2026-09-17", "rule": V1,
                             "picks": [_pick("g17", price=-225)]},
                            now="2026-09-17T12:00:00+00:00", path=self.path, sport="nfl")
        card_ledger.settle("2026-09-17", {"g17": {"home_score": 20, "away_score": 10}},
                           path=self.path, sport="nfl")
        card_ledger.publish({"date": "2026-09-20", "rule": V1,
                             "picks": [_pick("g20", price=-950,
                                             kickoff="2026-09-20T20:25:00Z")]},
                            now="2026-09-20T12:00:00+00:00", path=self.path, sport="nfl")
        # V2: 09-27 published and settled.
        card_ledger.publish({"date": "2026-09-27", "rule": V2,
                             "picks": [_pick("g27", market="spread", line=6.5, side="away",
                                             price=105, kickoff="2026-09-27T17:00:00Z")]},
                            now="2026-09-27T12:00:00+00:00", path=self.path, sport="nfl")
        card_ledger.settle("2026-09-27", {"g27": {"home_score": 23, "away_score": 17}},
                           path=self.path, sport="nfl")

    def test_v2_calendar_never_lists_a_v1_day_as_pending(self):
        self._two_rule_ledger()
        hist = card_ledger.history(path=self.path, rule=V2)
        self.assertEqual([d["date"] for d in hist["days"]], ["2026-09-27"])
        self.assertEqual(hist["pending_days"], [])

    def test_the_retired_rules_own_history_stays_reachable(self):
        self._two_rule_ledger()
        hist = card_ledger.history(path=self.path, rule=V1)
        self.assertEqual([d["date"] for d in hist["days"]], ["2026-09-17"])
        self.assertEqual([d["date"] for d in hist["pending_days"]], ["2026-09-20"])

    def test_no_rule_is_every_day_as_before(self):
        self._two_rule_ledger()
        hist = card_ledger.history(path=self.path)
        self.assertEqual([d["date"] for d in hist["days"]], ["2026-09-27", "2026-09-17"])
        self.assertEqual([d["date"] for d in hist["pending_days"]], ["2026-09-20"])

    def test_graded_nfl_picks_join_their_own_published_pick_by_game(self):
        """A composed Sunday card: the 1pm pick locked at rank 1, then after
        kickoff the 4:25 pick was published at rank 1 too. Joined by rank the
        Bills bet showed the Broncos and Seahawks and the other pick's book."""
        buf = _pick("2026_03_MIA_BUF", home="Buffalo Bills", away="Miami Dolphins",
                    market="spread", line=-3.0, price=100, book="bookA",
                    bet="Take Buffalo Bills -3 at +100", kickoff="2026-09-27T17:00:00Z")
        sea = _pick("2026_03_DEN_SEA", home="Seattle Seahawks", away="Denver Broncos",
                    market="total", line=44.5, side="over", price=108, book="bookB",
                    bet="Over 44.5 points", kickoff="2026-09-27T20:25:00Z")
        card_ledger.publish({"date": DATE, "rule": V2, "picks": [buf]},
                            now="2026-09-27T13:05:00+00:00", path=self.path, sport="nfl")
        row = card_ledger.publish({"date": DATE, "rule": V2, "picks": [sea]},
                                  now="2026-09-27T17:30:00+00:00", path=self.path, sport="nfl")
        self.assertEqual(sorted(p["rank"] for p in row["picks"]), [1, 1])
        card_ledger.settle(DATE, {"2026_03_MIA_BUF": {"home_score": 24, "away_score": 17},
                                  "2026_03_DEN_SEA": {"home_score": 30, "away_score": 10}},
                           path=self.path, sport="nfl")

        day = card_ledger.history(path=self.path, rule=V2)["days"][0]
        shown = {p["bet"]: (p["home_team"], p["away_team"], p["book"]) for p in day["picks"]}
        self.assertEqual(shown["Take Buffalo Bills -3 at +100"],
                         ("Buffalo Bills", "Miami Dolphins", "bookA"))
        self.assertEqual(shown["Over 44.5 points"],
                         ("Seattle Seahawks", "Denver Broncos", "bookB"))


# ---------------------------------------------------------------------------
# [9][23][24] WHAT A FROZEN / LIVE NFL CARD CARRIES
# [25] THE EMPTY REASON AFTER EVERY KICKOFF
# ---------------------------------------------------------------------------

class CardPayload(_TempLedger):
    def _publish_v2(self):
        t1 = KICKOFF - timedelta(hours=6)
        live = nfl_card.card_for_date(DATE, now=t1, entries=_entries(),
                                      rows=_spreads(t1, KICKOFF, -6.5, 105, -125),
                                      prefer_frozen=False, path=self.path)
        self.assertTrue(live["picks"])
        return live, card_ledger.publish(live, now=_z(t1), path=self.path, sport="nfl")

    def test_a_frozen_v2_card_carries_the_note_stored_with_it(self):
        _live, row = self._publish_v2()
        frozen = nfl_card.card_for_date(DATE, now=KICKOFF, path=self.path)
        self.assertTrue(frozen["frozen"])
        self.assertEqual(frozen["rule"], V2)
        self.assertEqual(frozen["basis"], nfl_value.CARD_BASIS)
        self.assertEqual(frozen["disclaimer"], nfl_value.CARD_DISCLAIMER)
        self.assertEqual(frozen["model_id"], nfl_value.MODEL_ID)
        self.assertEqual(frozen["frozen_at"], row["published_utc"])

    def test_a_frozen_v1_row_without_stored_text_falls_back_to_v1s_own(self):
        card_ledger.publish({"date": DATE, "rule": V1, "basis": None, "disclaimer": None,
                             "model_id": None, "picks": [_pick(GID, price=-278)]},
                            now=_z(KICKOFF - timedelta(hours=6)), path=self.path, sport="nfl")
        frozen = nfl_card.card_for_date(DATE, now=KICKOFF, path=self.path)
        self.assertEqual(frozen["rule"], V1)
        self.assertEqual(frozen["basis"], nfl_v1.CARD_BASIS)
        self.assertEqual(frozen["disclaimer"], nfl_v1.CARD_DISCLAIMER)
        self.assertEqual(frozen["model_id"], nfl_v1.MODEL_ID)
        self.assertIs(frozen["has_model"], False)

    def test_no_v2_card_claims_its_own_probabilities_are_uncalibrated(self):
        """web/js/card.js prints "Our own probabilities are running
        uncalibrated" whenever `calibrated === false`. V2 has no probability
        of its own to calibrate, so the field is None and `has_model` says
        why -- live and frozen alike."""
        live, _row = self._publish_v2()
        frozen = nfl_card.card_for_date(DATE, now=KICKOFF, path=self.path)
        for payload in (live, frozen):
            self.assertIsNot(payload.get("calibrated"), False)
            self.assertIs(payload["has_model"], False)
        empty = nfl_card.card_for_date(DATE, now=KICKOFF, entries=[], path=None,
                                       prefer_frozen=False)
        self.assertIsNot(empty.get("calibrated"), False)
        self.assertIs(empty["has_model"], False)

    def test_every_game_already_started_is_said_plainly(self):
        after = KICKOFF + timedelta(hours=1)
        board = _spreads(KICKOFF - timedelta(hours=2), KICKOFF, -6.5, 105, -125)
        card = nfl_card.card_for_date(DATE, now=after, entries=_entries(), rows=board,
                                      prefer_frozen=False, path=self.path)
        self.assertEqual(card["picks"], [])
        self.assertEqual(card["reason"], "Every game on this date has already started.")

    def test_a_date_with_games_still_to_play_is_not_called_started(self):
        before = KICKOFF - timedelta(hours=1)
        flat = _spreads(before, KICKOFF, -6.5, -110, -110)
        card = nfl_card.card_for_date(DATE, now=before, entries=_entries(), rows=flat,
                                      prefer_frozen=False, path=self.path)
        self.assertEqual(card["picks"], [])
        self.assertIn("priced better than the rest of the market", card["reason"])


# ---------------------------------------------------------------------------
# [8][14][21] THE NFL RECORD VERIFIES THE NFL CHAIN; ?rule= SELECTS A RULE
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class NflRecordRoutes(_TempLedger):
    def setUp(self):
        super().setUp()
        # MLB: five rows. NFL: V1 09-17 published + settled, V2 09-27
        # published -- three. Different counts on purpose, so a record that
        # counts the wrong file cannot pass by coincidence.
        for day in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"):
            card_ledger.publish({"date": day, "rule": "v1", "picks": [{
                "game_pk": 1, "market": "moneyline", "line": None, "side": "home",
                "price": -120, "bet": "b", "first_pitch_utc": f"{day}T23:00:00Z"}]},
                now=f"{day}T12:00:00+00:00", path=self.mlb_path)
        card_ledger.publish({"date": "2026-09-17", "rule": V1,
                             "picks": [_pick("g17", price=-225)]},
                            now="2026-09-17T12:00:00+00:00", path=self.path, sport="nfl")
        card_ledger.settle("2026-09-17", {"g17": {"home_score": 20, "away_score": 10}},
                           path=self.path, sport="nfl")
        card_ledger.publish({"date": DATE, "rule": V2,
                             "picks": [_pick(GID, market="spread", line=-6.5, price=105,
                                             kickoff=_z(KICKOFF))]},
                            now="2026-09-27T12:00:00+00:00", path=self.path, sport="nfl")
        self._patch = mock.patch(
            "src.appstate.card_ledger.store_path",
            side_effect=lambda sport=None: self.path if sport == "nfl" else self.mlb_path)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        from api import card as card_api
        self.api = card_api

    def test_the_nfl_record_counts_and_verifies_the_nfl_chain(self):
        payload = self.api.get_card_record(sport="nfl")
        self.assertTrue(payload["chain_ok"])
        self.assertEqual(payload["rows_checked"], len(self._rows()))
        self.assertNotEqual(payload["rows_checked"],
                            len(list(card_ledger._ledger(self.mlb_path).read())))

    def test_a_broken_nfl_chain_is_reported_broken_on_the_nfl_record(self):
        lines = Path(self.path).read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["basis"] = "edited after the fact"
        lines[0] = json.dumps(first, sort_keys=True)
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        payload = self.api.get_card_record(sport="nfl")
        self.assertFalse(payload["chain_ok"])
        mlb = self.api.get_card_record(sport="mlb")
        self.assertTrue(mlb["chain_ok"])

    def test_the_live_rule_is_the_default_and_the_retired_one_is_selectable(self):
        live = self.api.get_card_record(sport="nfl")
        self.assertEqual((live["rule"], live["days"]), (V2, 0))
        retired = self.api.get_card_record(sport="nfl", rule=V1)
        self.assertEqual((retired["rule"], retired["days"], retired["wins"]), (V1, 1, 1))
        self.assertEqual(retired["live_rule"], V2)

        hist_live = self.api.get_card_history(sport="nfl")
        self.assertEqual(hist_live["rule"], V2)
        self.assertEqual(hist_live["days"], [])
        self.assertEqual([d["date"] for d in hist_live["pending_days"]], [DATE])
        hist_v1 = self.api.get_card_history(sport="nfl", rule=V1)
        self.assertEqual([d["date"] for d in hist_v1["days"]], ["2026-09-17"])
        self.assertEqual(hist_v1["pending_days"], [])

    def test_an_unknown_nfl_rule_is_a_400(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            self.api.get_card_record(sport="nfl", rule="NFL_CARD_V9")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(fastapi.HTTPException) as ctx:
            self.api.get_card_history(sport="nfl", rule="v2")
        self.assertEqual(ctx.exception.status_code, 400)


class CliRecordVerifiesItsOwnSportsChain(_TempLedger):
    """`card record --sport nfl` printed the MLB ledger's chain status."""

    def test_cli_record_for_nfl_checks_the_nfl_chain(self):
        card_ledger.publish({"date": DATE, "rule": V2,
                             "picks": [_pick(GID, kickoff=_z(KICKOFF))]},
                            now="2026-09-27T12:00:00+00:00", path=self.path, sport="nfl")
        card_ledger.settle(DATE, {GID: {"home_score": 20, "away_score": 10}},
                           path=self.path, sport="nfl")
        card_ledger.publish({"date": "2026-09-01", "rule": "v1", "picks": [{
            "game_pk": 1, "market": "moneyline", "line": None, "side": "home",
            "price": -120, "bet": "b", "first_pitch_utc": "2026-09-01T23:00:00Z"}]},
            now="2026-09-01T12:00:00+00:00", path=self.mlb_path)
        lines = Path(self.path).read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["basis"] = "edited after the fact"
        lines[0] = json.dumps(first, sort_keys=True)
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")

        from src import cli
        with mock.patch("src.appstate.card_ledger.store_path",
                        side_effect=lambda sport=None: self.path if sport == "nfl" else self.mlb_path):
            out = io.StringIO()
            with redirect_stdout(out):
                cli.cmd_card(argparse.Namespace(card_command="record", sport="nfl",
                                                since=None, date=None))
        self.assertIn("chain: BROKEN", out.getvalue())


# ---------------------------------------------------------------------------
# PREREG RULE 6: AT MOST 5 PICKS PER DATE, NOT PER PUBLISH (2026-09-21)
# ---------------------------------------------------------------------------

def _games(n, kickoff, start=0):
    """Schedule entries for `n` synthetic games kicking off at `kickoff`."""
    entries = []
    for i in range(start, start + n):
        home, away, gid = f"Home {i}", f"Away {i}", f"G{i}"
        entries.append({"game_id": gid, "week": 3, "home_team": home,
                        "away_team": away, "kickoff_utc": _z(kickoff)})
    return entries


def _value_board(entries, at):
    rows = []
    for e in entries:
        kickoff = datetime.fromisoformat(e["kickoff_utc"].replace("Z", "+00:00"))
        rows += _spreads(at, kickoff, -3.0, 105, -125, home=e["home_team"],
                         away=e["away_team"], event=f"ev-{e['game_id']}")
    return rows


class FivePicksPerDate(_TempLedger):
    """With locked games held out of the fresh read, a Sunday built across
    kickoff windows used to reach 10 locked picks (review verifier,
    2026-09-21, scratchpad maxpicks.py). The fresh read now gets only the
    room the date's locked picks leave."""

    EARLY = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    LATE = datetime(2026, 9, 27, 20, 25, tzinfo=timezone.utc)

    def test_a_full_early_window_leaves_no_room_for_the_late_games(self):
        early = _games(5, self.EARLY, start=0)
        late = _games(5, self.LATE, start=5)
        t1 = datetime(2026, 9, 27, 13, 30, tzinfo=timezone.utc)   # early games lock
        first = nfl_card.publish_for_date(DATE, now=t1, entries=early + late,
                                          rows=_value_board(early, t1), path=self.path)
        self.assertEqual(len(first["picks"]), 5)
        self.assertTrue(all(p["locked"] for p in first["picks"]))

        t2 = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)   # late games lock
        nfl_card.publish_for_date(DATE, now=t2, entries=early + late,
                                  rows=_value_board(late, t2), path=self.path)
        newest = card_ledger.published_row(DATE, path=self.path)
        self.assertEqual(len(newest["picks"]), 5, [p["game_id"] for p in newest["picks"]])
        self.assertEqual({p["game_id"] for p in newest["picks"]}, {f"G{i}" for i in range(5)})

    def test_partial_early_window_fills_only_the_room_left_with_unique_ranks(self):
        early = _games(2, self.EARLY, start=0)
        late = _games(5, self.LATE, start=2)
        t1 = datetime(2026, 9, 27, 13, 30, tzinfo=timezone.utc)
        nfl_card.publish_for_date(DATE, now=t1, entries=early + late,
                                  rows=_value_board(early, t1), path=self.path)
        t2 = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        nfl_card.publish_for_date(DATE, now=t2, entries=early + late,
                                  rows=_value_board(late, t2), path=self.path)
        picks = card_ledger.published_row(DATE, path=self.path)["picks"]
        self.assertEqual(len(picks), 5)
        self.assertEqual(sorted(p["rank"] for p in picks), [1, 2, 3, 4, 5])


class LockTimeOnAFrozenCard(unittest.TestCase):
    """The page's "Locked at <time>" line and its stale-price warning read
    `frozen_at`/`prices_as_of`. A Sunday card is built across publishes; the
    newest row's publish time is the LAST publish, so it read "Locked at
    1:29 PM" above 10:00 AM games (review verifier, 2026-09-21)."""

    def _payload(self, lock_times):
        picks = [{"game_id": f"G{i}", "rank": i + 1, "locked": True, "locked_at": t}
                 for i, t in enumerate(lock_times)]
        return nfl_card._frozen_payload(DATE, {"rule": V2, "picks": picks,
                                               "published_utc": "2026-09-27T20:29:00+00:00"})

    def test_one_shared_lock_time_is_shown(self):
        out = self._payload(["2026-09-27T13:30:00+00:00"] * 2)
        self.assertEqual(out["frozen_at"], "2026-09-27T13:30:00+00:00")
        self.assertEqual(out["prices_as_of"], "2026-09-27T13:30:00+00:00")

    def test_several_lock_times_show_none_and_age_counts_from_the_oldest(self):
        out = self._payload(["2026-09-27T16:30:00+00:00", "2026-09-27T13:30:00+00:00"])
        self.assertIsNone(out["frozen_at"])
        self.assertEqual(out["prices_as_of"], "2026-09-27T13:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
