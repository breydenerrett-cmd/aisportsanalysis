"""The owner's performance audit (2026-10-25) on the Apprentice ledger: bettor, recommendation link, evidence grade and the
three views kept apart. Shares its fixtures with tests/test_apprentice.py."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.hounds.apprentice import analytics, calc, grading, service, store
from tests.test_apprentice import (DOBBINS, NOW, PNG, PNG2, PT, Base, FakeRouter, GradingTests)


class AuditAddOnTests(Base):
    GAME = {"event_id": "g-lac", "sport": "NFL", "away_team": "Los Angeles Chargers", "home_team": "Denver Broncos",
            "commence_utc": "2026-10-25T20:05:00Z", "slate_date": "2026-10-25"}
    REC_AT = "2026-10-24T18:00:00Z"
    PLACED = "2026-10-25T15:23:39Z"

    def legs(self, line=49.5):
        return [self.leg(event_id="g-lac", sport="NFL", market="player_rushing_yards", selection="J.K. Dobbins Over",
                         player="J.K. Dobbins", side="over", line=line, price=-115, game="Chargers @ Broncos")]

    def rec(self, rec_id="rec-1", at=None, line=49.5):
        return store.add_recommendation(rec_id, "hound:u-xyz", at or self.REC_AT, self.legs(line), now=NOW, db=self.db)

    def file(self, owner="Brey", rec_id=None, placed=None, ticket=None, legs=None, **kw):
        raw = self.raw(legs or self.legs(), owner=owner, recommendation_id=rec_id, placed_at=placed or self.PLACED, stake=100,
                       total_price=-115, ticket_id=ticket, **kw)
        return service.add_manual(self.h, 7, raw, now=NOW, games=[self.GAME], path=self.ledger)

    def test_the_four_grades(self):
        self.rec()
        a = self.file("Brey", "rec-1", ticket="A")
        b = self.file("Brey", None, ticket="B")
        c = self.file("Jacob", "rec-1", ticket="C")
        d = self.file("unknown", "rec-1", ticket="D")
        self.assertEqual([x["evidence_grade"] for x in (a, b, c, d)], ["A", "B", "C", "D"])
        self.assertEqual(a["recommended_at"], self.REC_AT)
        self.assertEqual((a["owner"], a["game_id"], a["placed_at"]), ("Brey", "g-lac", self.PLACED))

    def test_owner_defaults_to_unknown_and_an_unknown_name_is_refused(self):
        v = service.add_manual(self.h, 7, self.raw(), now=NOW, games=[], path=self.ledger)
        self.assertEqual((v["owner"], v["evidence_grade"]), ("unknown", "D"))
        with self.assertRaises(service.ServiceError) as ctx:
            service.add_manual(self.h, 7, self.raw(owner="Someone"), now=NOW, games=[])
        self.assertIn("owner", ctx.exception.extra["fields"])

    def test_a_recommendation_published_after_placement_or_not_exact_is_not_grade_a(self):
        self.rec("late", at="2026-10-25T16:00:00Z")
        self.rec("other-line", line=52.5)
        self.assertEqual(self.file("Brey", "late", ticket="L")["evidence_grade"], "B")
        self.assertEqual(self.file("Brey", "other-line", ticket="O")["evidence_grade"], "B")
        with self.assertRaises(service.ServiceError) as ctx:
            self.file("Brey", "nobody-published-this", ticket="Z")
        self.assertEqual(ctx.exception.code, "unknown_recommendation")

    def test_no_member_route_or_service_can_create_a_recommendation(self):
        self.assertFalse([n for n in dir(service) if "recommendation" in n and n.startswith("add")])
        api_src = (Path(__file__).resolve().parent.parent / "api" / "hounds_apprentice.py").read_text(encoding="utf-8")
        self.assertNotIn("add_recommendation", api_src)

    def test_only_grade_a_counts_as_a_linehound_pick_and_other_bettors_are_excluded(self):
        self.rec()
        self.rec("rec-unplaced", line=60.5)
        for ticket, who, rid, result in (("A", "Brey", "rec-1", "won"), ("B", "Brey", None, "lost"), ("C", "Jacob", "rec-1", "won")):
            v = self.file(who, rid, ticket=ticket)
            service.set_state(self.h, 7, v["id"], "settled", {"result": result}, now=NOW, db=self.db)
        out = service.overview(self.h, 7, db=self.db, grade=False)
        views = out["analytics"]["views"]
        b = views["b_executed"]
        self.assertEqual((b["counted"], b["wins"], b["profit"]), (1, 1, 86.96))
        self.assertEqual((views["c_other_bettors"]["n"], views["c_other_bettors"]["excluded"]), (1, True))
        self.assertEqual(views["unmatched"], {"b": 1, "d": 0})
        a = views["a_recommendations"]
        self.assertEqual((a["published"], a["placed"], a["unplaced"]), (2, 1, 1))          # the unplaced pick is listed
        self.assertEqual([i["result"] for i in a["items"] if i["id"] == "rec-1"], ["won"])
        overall = out["analytics"]["overall"]
        self.assertEqual((overall["n"], overall["profit"]), (2, round(86.96 - 100.0, 2)))   # Jacob's winner is not in these totals

    def test_a_push_is_neither_win_nor_loss_but_is_in_the_returned_amount(self):
        won = self.file("Brey", ticket="W")
        push = self.file("Brey", ticket="P")
        lost = self.file("Brey", ticket="L")
        for v, res in ((won, "won"), (push, "push"), (lost, "lost")):
            service.set_state(self.h, 7, v["id"], "settled", {"result": res}, now=NOW, db=self.db)
        o = analytics.summarize(self.pairs())["overall"]
        self.assertEqual((o["wins"], o["losses"], o["pushes"], o["win_rate"]), (1, 1, 1, 0.5))
        self.assertEqual((o["staked"], o["returned"], o["profit"]), (300.0, 286.96, -13.04))
        self.assertTrue(o["reconciles"])

    def test_a_bankroll_screenshot_is_never_evidence_and_nothing_is_staged(self):
        empty = {"screen_type": "bankroll", "bet_type": "unknown", "legs": [], "total_odds": None, "stake": None,
                 "payout": None, "placed_at": None, "bet_id": None, "status": None}
        out = service.import_screenshot(self.h, 7, PNG, FakeRouter(empty), now=NOW, games=[], db=self.db)
        self.assertEqual((out["ok"], out["not_a_bet_slip"]), (False, True))
        self.assertIn("not evidence", out["message"])
        self.assertIsNone(store.staged(7, store.image_hash(PNG), db=self.db))
        self.assertEqual(self.pairs(), [])

    def test_two_images_of_one_bet_id_count_once(self):
        for image in (PNG, PNG2):
            out = service.import_screenshot(self.h, 7, image, FakeRouter(DOBBINS), utc_offset_minutes=PT, now=NOW, games=[],
                                            db=self.db)
            try:
                service.confirm_import(self.h, 7, out["image"]["hash"], out["lesson"],
                                       lesson_id=(out["duplicate"] or {}).get("lesson_id"), now=NOW, games=[], db=self.db,
                                       path=self.ledger)
            except service.ServiceError:
                pass
        self.assertEqual(len(self.pairs()), 1)
        self.assertEqual(analytics.summarize(self.pairs())["overall"]["n"], 1)

    def test_the_reference_ticket_lost_because_one_leg_lost(self):
        """Final box scores: Irving 24-106 (O64.5 won), Dobbins 6-23 (O49.5 lost). The parlay is a LOSS."""
        lost = json.loads(json.dumps(DOBBINS))
        lost["status"] = "lost"
        lost["legs"][0]["status"], lost["legs"][1]["status"] = "lost", "won"
        out = service.import_screenshot(self.h, 7, PNG, FakeRouter(lost), utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        self.assertEqual(out["ticket_state"]["leg_statuses"], ["lost", "won"])
        done = service.confirm_import(self.h, 7, out["image"]["hash"], dict(out["lesson"], owner="Brey"), now=NOW, games=[],
                                      db=self.db, path=self.ledger)["lesson"]
        self.assertEqual((done["state"], done["result"], done["profit"], done["payout"]), ("settled", "lost", -100.18, 0.0))
        self.assertEqual(calc.ticket_outcome(["lost", "won"], [-115, -112], 100.18)["result"], "lost")
        self.assertEqual(done["legs"][1]["player"], "Bucky Irving")
        o = analytics.summarize(self.pairs())["overall"]
        self.assertEqual((o["wins"], o["losses"], o["profit"]), (0, 1, -100.18))

    def test_settlement_time_and_the_grader_closing_line_ride_on_the_view(self):
        v = self.file("Brey", ticket="S")
        res = service.set_state(self.h, 7, v["id"], "settled", {"result": "lost", "settlement_time": "2026-10-25T23:30:00Z"},
                                now=NOW, db=self.db)["lesson"]
        self.assertEqual(res["settlement_time"], "2026-10-25T23:30:00Z")
        with self.assertRaises(service.ServiceError):
            service.set_state(self.h, 7, v["id"], "settled", {"result": "won", "settlement_time": "tomorrow-ish"}, now=NOW,
                              db=self.db)
        legs = [self.leg(event_id="e1", sport="NFL", price=-110, game="Kansas City Chiefs @ Las Vegas Raiders")]
        g = service.add_manual(self.h, 7, self.raw(legs, owner="Brey"), now=NOW, games=[GradingTests.GAME], path=self.ledger)
        grading.sync(self.h["root_id"], 7, path=self.ledger, now=GradingTests.LATER, run_settle=True,
                     settle_kwargs=GradingTests().results(17, 24))
        out = [x for x in service.overview(self.h, 7, db=self.db, grade=False)["lessons"] if x["id"] == g["id"]][0]
        self.assertEqual((out["closing_line"], out["game_id"]), ([-125], "e1"))


if __name__ == "__main__":
    unittest.main()
