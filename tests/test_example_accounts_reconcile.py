"""EXAMPLE ACCOUNTS against the published record, on copies of the real rows.

The accounts are only worth showing if their totals ARE the site's published
record. These tests rebuild the real MLB V2, NFL and UFC ledger rows
(tests/fixtures/example_accounts, see tests/_example_accounts_fixtures.py),
read them with the ledger's own record and history functions, and check, pick
count, wins, losses, pushes, voids and units to four decimals:

  * MLB: the account is the counted record (16-17, 5 voids, -5.0463u) PLUS
    the postseason cohort the record keeps apart (0-2, -2.0u);
  * NFL (1-0, +0.9259u) and UFC (5-1, 1 void, +2.5027u): exactly the record;
  * every account's rows are the same picks as an independent walk of the raw
    ledger, joined by identity, not by count.

Runs without FastAPI: the route half is tests/test_example_accounts_route.py.
"""

from __future__ import annotations

import unittest

from src.appstate import card_ledger
from src.appstate import example_accounts as ea
from src.ledger.chain import HashChainLedger
from src.report import effective_record as er
from tests._example_accounts_fixtures import (
    PUBLISHED, fixture_ledgers, mlb_v2_payloads, ufc_text_with)


def _mark_postseason(days):
    """What api.card._mark_postseason does to history_v2's days, step for step
    (that function lives in a module that needs FastAPI to import)."""
    pks = er._postseason_game_pks({}) | (
        er._ledger_postseason_pks({"days": days}) - er._regular_game_pks({}))
    return [dict(d, graded=[dict(e, postseason=er._is_postseason_entry(e, pks))
                            for e in (d.get("graded") or [])]) for d in days]


def mlb_days(mark=True):
    days = card_ledger.history_v2(limit=None)["days"]
    return _mark_postseason(days) if mark else days


def mlb_reference():
    """The numbers /card/record serves for MLB, built the way
    api.card._card_record_uncached builds them."""
    payload = dict(card_ledger.record_v2())
    cohort = er.sport_snapshot("mlb")["current"]
    for key in ("days", "wins", "losses", "pushes", "voids", "n_staked", "profit_units"):
        payload[key] = cohort.get(key)
    payload["postseason"] = cohort.get("postseason")
    return ea.reference_from_record("mlb", payload)


def nfl_reference():
    from src.report import nfl_card
    return ea.reference_from_record("nfl", card_ledger.record(sport="nfl", rule=nfl_card.LIVE_RULE))


def ufc_reference():
    return ea.reference_from_record("ufc", card_ledger.record(sport="mma"))


def nfl_days():
    from src.report import nfl_card
    return card_ledger.history(limit=None, sport="nfl", rule=nfl_card.LIVE_RULE)["days"]


def ufc_days():
    return card_ledger.history(limit=None, sport="mma")["days"]


def sources(mark=True):
    mlb_rows, mlb_wait = ea.rows_from_v2_days(mlb_days(mark), "mlb")
    nfl_rows, nfl_wait = ea.rows_from_v1_days(nfl_days(), "nfl")
    ufc_rows, ufc_wait = ea.rows_from_v1_days(ufc_days(), "ufc")
    return {
        "mlb": {"rows": mlb_rows, "waiting": mlb_wait, "reference": mlb_reference()},
        "nfl": {"rows": nfl_rows, "waiting": nfl_wait, "reference": nfl_reference()},
        "ufc": {"rows": ufc_rows, "waiting": ufc_wait, "reference": ufc_reference()},
    }


def config(start="2026-09-22"):
    cfg = ea.load_config()
    cfg["start_date"] = start
    return cfg


class TheRecordThisTestReadsIsTheOneTheSitePublished(unittest.TestCase):
    """If these fail the fixtures are not what they were copied as, and every
    other test in this file is measuring the wrong thing."""

    def test_the_published_figures_from_the_fixture_rows(self):
        with fixture_ledgers():
            mlb = mlb_reference()
            self.assertEqual(mlb["counted"], PUBLISHED["mlb_counted"])
            self.assertEqual(mlb["postseason"], PUBLISHED["mlb_postseason"])
            self.assertEqual(nfl_reference()["counted"], PUBLISHED["nfl"])
            self.assertEqual(ufc_reference()["counted"], PUBLISHED["ufc"])

    def test_the_postseason_cohort_is_the_two_losses_of_2026_10_01(self):
        with fixture_ledgers():
            flagged = [(d["date"], e["result"]) for d in mlb_days() for e in d["graded"]
                       if e["postseason"] and not e["withdrawn"] and e["entry_class"] != "fill"]
        self.assertEqual(flagged, [("2026-10-01", "LOSS"), ("2026-10-01", "LOSS")])


class EverySportReconcilesExactly(unittest.TestCase):
    def setUp(self):
        ctx = fixture_ledgers()
        self.paths = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.src = sources()

    def test_mlb_is_the_counted_record_plus_the_postseason_picks(self):
        rec = ea.reconcile("mlb", self.src["mlb"]["rows"], self.src["mlb"]["reference"])
        self.assertTrue(rec["ok"], rec["problems"])
        self.assertEqual(rec["account"], {"picks": 40, "wins": 16, "losses": 19, "pushes": 0,
                                          "voids": 5, "units": -7.0463})
        counted, post = PUBLISHED["mlb_counted"], PUBLISHED["mlb_postseason"]
        for key in ("picks", "wins", "losses", "pushes", "voids"):
            self.assertEqual(rec["account"][key], counted[key] + post[key], key)
        self.assertEqual(rec["account"]["units"], round(counted["units"] + post["units"], 4))

    def test_nfl_is_the_record_exactly(self):
        rec = ea.reconcile("nfl", self.src["nfl"]["rows"], self.src["nfl"]["reference"])
        self.assertTrue(rec["ok"], rec["problems"])
        self.assertEqual(rec["account"], PUBLISHED["nfl"])

    def test_ufc_is_the_record_exactly_with_its_void(self):
        rec = ea.reconcile("ufc", self.src["ufc"]["rows"], self.src["ufc"]["reference"])
        self.assertTrue(rec["ok"], rec["problems"])
        self.assertEqual(rec["account"], PUBLISHED["ufc"])

    def test_the_whole_payload_is_available_and_all_sports_is_the_three_added_up(self):
        payload = ea.build_payload(config(), self.src)
        self.assertTrue(payload["available"], payload.get("reason"))
        self.assertTrue(all(r["ok"] for r in payload["reconciled"].values()))
        self.assertEqual(payload["reconciled"]["all"]["account"],
                         {"picks": 48, "wins": 22, "losses": 20, "pushes": 0, "voids": 6, "units": -3.6177})
        self.assertEqual(payload["as_of"], "2026-10-01")

    def test_the_default_accounts_end_where_the_arithmetic_says(self):
        payload = ea.build_payload(config(), self.src)
        units = {"mlb": -7.0463, "nfl": 0.9259, "ufc": 2.5027, "all": -3.6177}
        by_id = {a["id"]: a["series"] for a in payload["accounts"]}
        for view, u in units.items():
            self.assertEqual(by_id["flat100"][view]["total_units"], u)
            self.assertAlmostEqual(by_id["flat100"][view]["final_balance"], 10000 + 100 * u, places=6)
            self.assertAlmostEqual(by_id["flat250"][view]["final_balance"], 10000 + 250 * u, places=6)
            self.assertAlmostEqual(by_id["starter"][view]["final_balance"], 1000 + 10 * u, places=6)
        # percent staking compounds day to day, so it is not start + 1% x units
        self.assertNotAlmostEqual(by_id["pct1"]["mlb"]["final_balance"], 10000 + 100 * -7.0463, places=2)
        self.assertGreater(by_id["pct1"]["mlb"]["final_balance"], 10000 + 100 * -7.0463)

    def test_a_later_start_date_is_a_plain_filter_and_still_reconciles(self):
        payload = ea.build_payload(config("2026-09-23"), self.src)
        self.assertTrue(payload["available"])
        rec = payload["reconciled"]["mlb"]
        self.assertEqual(rec["account"]["picks"], 40)             # what the record counts, all of it
        self.assertEqual(rec["from_start"]["picks"], 19)           # minus the 21 picks of 09-22
        self.assertEqual(payload["accounts"][0]["series"]["mlb"]["picks"], 19)

    def test_the_postseason_days_are_flagged_and_the_regular_season_days_are_not(self):
        payload = ea.build_payload(config(), self.src)
        daily = payload["accounts"][0]["series"]["mlb"]["daily"]
        self.assertEqual([d["date"] for d in daily if d["postseason"]], ["2026-10-01"])
        self.assertEqual(payload["accounts"][0]["series"]["mlb"]["postseason_picks"], 2)

    def test_the_days_with_no_picks_are_not_rows(self):
        """09-26, 09-27, 09-29 and 09-30 published fills only for MLB (and 09-27
        held one withdrawn entry): no pick, so no row, and nothing was bet."""
        daily = ea.build_payload(config(), self.src)["accounts"][0]["series"]["mlb"]["daily"]
        self.assertEqual([d["date"] for d in daily],
                         ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-10-01"])

    def test_the_account_and_the_record_agree_pick_by_pick_with_an_independent_walk(self):
        """Joined by identity, not by count: the set of picks (and each pick's
        result and units) is the set an independent walk of the raw ledger finds."""
        rows = {}
        for r in self.src["mlb"]["rows"]:
            rows[r["pick_id"]] = (r["result"], float(r["units"]))
        newest = {}
        for row in HashChainLedger(self.paths["v2"]).read():
            if row.get("kind") == card_ledger.KIND_SETTLED:
                newest[row["date"]] = row
        independent = {}
        for date, row in newest.items():
            for e in row["graded"]:
                if e.get("withdrawn") or e.get("entry_class") == "fill" or e["result"] == "UNRESOLVED":
                    continue
                game = e.get("game_pk") if e.get("game_pk") is not None else e.get("game_id")
                who = e.get("player_id") or e.get("player") or e.get("team_name") or e.get("team")
                key = "|".join(str(p) for p in (date, "mlb", e.get("kind") or "game", game, who,
                                                e.get("market"), e.get("line"), e.get("side")))
                units = float(e["profit_units"]) if e["result"] in ("WIN", "LOSS") else 0.0
                independent[key] = (e["result"], units)
        self.assertEqual(rows, independent)
        self.assertEqual(len(rows), 40)


class WhyTheNaiveCountIsNotTheRecord(unittest.TestCase):
    """A pass over the history's entries with entry_class "pick" gives MLB
    20-20 and -4.12 units. The record is 16-17 (plus 0-2 postseason). The
    difference is exactly two rules, and this proves it entry by entry."""

    def test_the_naive_pass_and_the_two_rules_that_account_for_the_difference(self):
        with fixture_ledgers():
            days = mlb_days()
        naive = [e for d in days for e in d["graded"] if e["entry_class"] == "pick"]
        n = lambda es, r: sum(1 for e in es if e["result"] == r)
        units = lambda es: round(sum(e["profit_units"] or 0.0 for e in es if e["result"] in ("WIN", "LOSS")), 4)
        self.assertEqual((n(naive, "WIN"), n(naive, "LOSS"), n(naive, "VOID")), (20, 20, 6))
        self.assertEqual(units(naive), -4.1187)

        withdrawn = [e for e in naive if e["withdrawn"]]
        kept = [e for e in naive if not e["withdrawn"]]
        # Rule 1: a withdrawn entry was taken off the card before the game
        # and is not a pick the card published (record_v2 counts it as `withdrawn`).
        self.assertEqual((n(withdrawn, "WIN"), n(withdrawn, "LOSS"), n(withdrawn, "VOID")), (4, 1, 1))
        self.assertEqual(units(withdrawn), 2.9276)
        self.assertEqual((n(kept, "WIN"), n(kept, "LOSS"), n(kept, "VOID"), units(kept)),
                         (16, 19, 5, -7.0463))

        counted = [e for e in kept if not e["postseason"]]
        postseason = [e for e in kept if e["postseason"]]
        # Rule 2: the counted record leaves the postseason out (registration
        # 11.1), so 16-19 becomes 16-17 and the two postseason losses stand apart.
        self.assertEqual((n(counted, "WIN"), n(counted, "LOSS"), n(counted, "VOID"), units(counted)),
                         (16, 17, 5, -5.0463))
        self.assertEqual((n(postseason, "WIN"), n(postseason, "LOSS"), units(postseason)), (0, 2, -2.0))
        # Both are player props, which freeze game_type "R" whatever the game is
        # (ERRATUM E6), so the record knows them as postseason by their card's
        # date: 2026-10-01 is inside the season's postseason calendar.
        self.assertEqual({(e["kind"], e["game_type"]) for e in postseason}, {("prop", "R")})

    def test_fills_never_enter_either_count(self):
        with fixture_ledgers():
            days = mlb_days()
        fills = [e for d in days for e in d["graded"] if e["entry_class"] == "fill" and not e["withdrawn"]]
        self.assertEqual(len(fills), 39)                       # 26-10 with 3 voids: bet by nobody
        rows, _ = ea.rows_from_v2_days(days, "mlb")
        self.assertEqual(len(rows), 40)


class ADeliberatelyCorruptedRowIsRefusedNotShownWrong(unittest.TestCase):
    def test_a_postseason_game_that_loses_its_flag_no_longer_reconciles(self):
        """_mark_postseason swallows its own errors and returns the days
        unmarked. Then two postseason losses look like regular season, the
        counted figure is 16-19 against a record of 16-17, and nothing is shown."""
        with fixture_ledgers():
            days = mlb_days(mark=False)
            rows, wait = ea.rows_from_v2_days(days, "mlb")
            src = sources()
            src["mlb"]["rows"], src["mlb"]["waiting"] = rows, wait
            payload = ea.build_payload(config(), src)
        self.assertFalse(payload["available"])
        self.assertIn("MLB", payload["reason"])
        self.assertTrue(payload["reconciled"]["mlb"]["problems"])

    def test_a_ufc_row_whose_picks_do_not_add_up_to_its_own_totals_is_refused(self):
        """A valid chain, a corrupted row: the day says +1.5997u and its two
        picks say otherwise. The rows are not trusted, so there is nothing to show."""
        changed = []

        def corrupt(row):
            if row.get("kind") == "card_settled" and row.get("date") == "2026-09-22" and row.get("picks"):
                row["picks"][0]["profit_units"] += 0.25
                changed.append(row["date"])

        text = ufc_text_with(corrupt)
        self.assertEqual(changed, ["2026-09-22"])
        with fixture_ledgers(ufc_text=text):
            self.assertTrue(card_ledger.verify(sport="mma").ok)        # the chain is intact
            with self.assertRaises(ea.AccountsError):
                ea.rows_from_v1_days(ufc_days(), "ufc")

    def test_a_win_with_no_units_in_the_ledger_is_refused(self):
        payloads = mlb_v2_payloads()
        for row in payloads:
            if row.get("kind") == "card_settled":
                for entry in row["graded"]:
                    if entry["result"] == "WIN" and not entry.get("withdrawn") and entry["entry_class"] == "pick":
                        entry["profit_units"] = None
                        break
                break
        with fixture_ledgers(v2_payloads=payloads):
            with self.assertRaises(ea.AccountsError):
                ea.rows_from_v2_days(mlb_days(), "mlb")

    def test_one_extra_win_in_the_published_record_is_refused(self):
        with fixture_ledgers():
            src = sources()
        ref = dict(src["nfl"]["reference"]["counted"])
        ref.update(wins=2, picks=2)
        src["nfl"]["reference"] = {"counted": ref, "postseason": None, "combined": None}
        payload = ea.build_payload(config(), src)
        self.assertFalse(payload["available"])
        self.assertIn("NFL", payload["reason"])


if __name__ == "__main__":
    unittest.main()
