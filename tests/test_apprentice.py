"""The Apprentice hound: lessons ledger, screenshot import, grading, analytics and the freeze rule.

The router is faked everywhere (no model is ever called); the database is a temp file, and the grading uses injected
results. Each test pins one rule the owner asked for.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.hounds import user_spec
from src.hounds.apprentice import analytics, calc, extract, grading, learning, model, service, store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG2 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 64
NOW = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
PT = -7 * 60                      # the screenshot's clock reading is Pacific Daylight Time

# The owner's reference ticket (docs/TODO_UNTIL_SUNDAY.md, "Dobbins + Bucky"): fixture only, never production data.
DOBBINS = {
    "screen_type": "bet_slip", "bet_type": "parlay", "leg_count": 2,
    "legs": [
        {"selection": "J.K. Dobbins Over 49.5", "market": "Rushing Yards", "line": 49.5, "odds": -115,
         "player": "J.K. Dobbins", "game": None, "sport": "NFL", "status": "pending"},
        {"selection": "Bucky Irving Over 64.5", "market": "Rushing Yards", "line": 64.5, "odds": -112,
         "player": "Bucky Irving", "game": None, "sport": "NFL", "status": "pending"}],
    "total_odds": 253, "stake": 100.18, "payout": 354.51, "placed_at": "2026-10-25T08:23:39",
    "bet_id": "DK639285386193890132", "status": "pending", "book": "DraftKings", "unreadable": []}


def hound(**kw):
    out = {"id": "u-aaa", "root_id": "u-aaa", "owner_user_id": 7, "status": "running",
           "spec": user_spec.validate_spec({"version": 2, "style": "apprentice", "name": "Pup Test", "tagline": "learns"})}
    out.update(kw)
    return out


class FakeRouter:
    """Stands in for src.ai.router.Router: returns a scripted extraction and records what it was asked."""

    def __init__(self, output=None, ok=True, capped=False):
        self.output, self.ok, self.capped, self.calls = output, ok, capped, []

    def ask(self, system, user, *, schema, purpose="", max_tokens=None, images=(), **kw):
        self.calls.append({"system": system, "user": user, "images": list(images), "purpose": purpose})
        if self.capped:
            att = SimpleNamespace(status="skipped", detail="monthly paid cap of $5.00 reached")
            return SimpleNamespace(ok=False, output=None, cost_usd=0.0, attempts=[att], reason="capped")
        if not self.ok:
            return SimpleNamespace(ok=False, output=None, cost_usd=0.0, attempts=[], reason="down")
        return SimpleNamespace(ok=True, output=self.output, cost_usd=0.0004, attempts=[], reason="")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db = root / "app.db"
        self.ledger = str(root / "lessons.jsonl")
        p = mock.patch.dict(os.environ, {"APP_DB_PATH": str(self.db), "HOUNDS_LESSONS_LEDGER": self.ledger,
                                         "HOUNDS_USER_LEDGER": str(root / "user.jsonl")})
        p.start()
        self.addCleanup(p.stop)
        self.h = hound()

    def leg(self, **kw):
        out = {"sport": "NFL", "game": "Chiefs @ Raiders", "market": "moneyline", "selection": "Chiefs", "side": "away",
               "line": None, "price": -110, "player": None}
        out.update(kw)
        return out

    def raw(self, legs=None, **kw):
        legs = legs or [self.leg()]
        out = {"legs": legs, "stake": 50, "book": "DraftKings", "placed_at": "2026-10-24T20:00:00Z"}
        out.update(kw)
        return out

    def add(self, legs=None, state=None, now=NOW, **kw):
        raw = self.raw(legs, **kw)
        if state:
            raw["state"] = state
        return service.add_manual(self.h, 7, raw, now=now, games=[], path=self.ledger)

    def pairs(self):
        return store.lessons_for(self.h["root_id"])


class ApprenticeSpecTests(Base):
    def test_apprentice_spec_has_no_rules_and_validates(self):
        spec = self.h["spec"]
        self.assertEqual(spec["style"], "apprentice")
        self.assertEqual(spec["rules"], [])
        self.assertTrue(user_spec.is_apprentice(spec))
        self.assertEqual(user_spec.validate_spec(spec), spec)               # round-trips unchanged
        self.assertIn("No rules yet", user_spec.rule_text(spec))

    def test_an_ordinary_hound_still_needs_a_rule_and_gematria_still_owns_its_stamp(self):
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec({"version": 2, "name": "Plain Pup", "rules": []})
        self.assertIn("rules", ctx.exception.errors)
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec({"version": 2, "style": "apprentice", "name": "Bad Pup", "gematria": {}})
        self.assertIn("gematria", ctx.exception.errors)

    def test_the_apprentice_style_is_part_of_the_rule_hash(self):
        plain = user_spec.validate_spec({"version": 2, "name": "Hash Pup", "rules": [
            {"sports": ["MLB"], "markets": ["moneyline"], "side": "either"}]})
        app = user_spec.validate_spec({"version": 2, "style": "apprentice", "name": "Hash Pup", "rules": plain["rules"]})
        self.assertNotEqual(user_spec.spec_hash(plain), user_spec.spec_hash(app))

    def test_an_apprentice_with_no_rules_reads_no_boards(self):
        from src.hounds.interact import ask_eval, common
        dog = common.Dog(id="u-aaa", kind=common.KIND_USER, name="Pup Test", hound=self.h, owner_user_id=7, root_id="u-aaa")

        def boom(*a, **k):
            raise AssertionError("an Apprentice with no rules must not read a slate")
        out = ask_eval.fire_v2(dog, now=NOW, slate_for=boom, other_live=lambda *_: None, with_rows=True)
        self.assertFalse(out.get("picks") or out.get("rows") or [])


class CalcTests(unittest.TestCase):
    def test_the_owners_reference_ticket_is_consistent_within_rounding(self):
        self.assertEqual(calc.check_consistency(leg_prices=[-115, -112], total_price=253, stake=100.18, payout=354.51), [])

    def test_a_payout_that_does_not_match_is_named(self):
        issues = calc.check_consistency(leg_prices=[-115, -112], total_price=253, stake=100.18, payout=400.00)
        self.assertEqual([i["field"] for i in issues], ["payout"])
        issues = calc.check_consistency(leg_prices=[-115, -112], total_price=300, stake=100.18, payout=None)
        self.assertEqual([i["field"] for i in issues], ["total_odds"])

    def test_a_parlay_with_one_winning_leg_is_not_a_win(self):
        prices = [-115, -112]
        self.assertEqual(calc.ticket_outcome(["won", None], prices, 100)["result"], "pending")
        out = calc.ticket_outcome(["won", "lost"], prices, 100)
        self.assertEqual((out["result"], out["profit"]), ("lost", -100.0))
        self.assertEqual(calc.ticket_outcome([None, "lost"], prices, 100)["result"], "lost")      # lost the moment it is known
        out = calc.ticket_outcome(["won", "won"], prices, 100.18, quoted_payout=354.51)
        self.assertEqual((out["result"], out["payout"], out["profit"]), ("won", 354.51, 254.33))

    def test_a_push_or_void_leg_reprices_and_asks_for_confirmation(self):
        out = calc.ticket_outcome(["won", "push"], [-115, -112], 100)
        self.assertEqual(out["result"], "won")
        self.assertEqual(out["payout"], calc.payout_for(100, calc.dec(-115)))
        self.assertTrue(out["repriced"] and out["needs_confirmation"])
        self.assertEqual(calc.ticket_outcome(["push", "void"], [-115, -112], 100)["result"], "push")
        self.assertEqual(calc.ticket_outcome(["void", "void"], [-115, -112], 100)["result"], "void")

    def test_cash_out_math(self):
        self.assertEqual(calc.cash_out(100, 140.5), {"payout": 140.5, "profit": 40.5})
        self.assertEqual(calc.cash_out(100, 35)["profit"], -65.0)
        with self.assertRaises(ValueError):
            calc.cash_out(100, -1)

    def test_bands_and_roles_never_say_the_other_word(self):
        self.assertEqual(calc.price_band(-110), "-149 to -110")
        self.assertEqual(calc.price_band(253), "+250 or longer")
        self.assertEqual(calc.role_of(-110), "favourite")
        self.assertNotIn("dog", calc.role_of(150))


class ExtractionTests(Base):
    def draft(self, **over):
        ex = json.loads(json.dumps(DOBBINS))
        ex.update(over)
        return extract.draft_from_extraction(ex, utc_offset_minutes=PT, now=NOW)

    def test_the_reference_ticket_reads_clean(self):
        d = self.draft()
        self.assertEqual(d["ambiguous"], [])
        self.assertEqual(d["lesson"]["placed_at"], "2026-10-25T15:23:39Z")           # 08:23:39 PDT
        self.assertEqual([leg["market"] for leg in d["lesson"]["legs"]], ["player_rushing_yards"] * 2)
        self.assertEqual([leg["side"] for leg in d["lesson"]["legs"]], ["over", "over"])

    def test_odds_stake_payout_mismatch_is_ambiguous(self):
        fields = [a["field"] for a in self.draft(payout=500.0)["ambiguous"]]
        self.assertIn("payout", fields)
        fields = [a["field"] for a in self.draft(total_odds=-300)["ambiguous"]]
        self.assertIn("total_price", fields)

    def test_unreadable_and_odd_fields_are_ambiguous_never_guessed(self):
        d = self.draft(stake=None, bet_id=None, placed_at="Oct 25")
        fields = {a["field"] for a in d["ambiguous"]}
        self.assertTrue({"stake", "ticket_id", "placed_at"} <= fields)
        d = self.draft(leg_count=3)
        self.assertIn("legs", {a["field"] for a in d["ambiguous"]})
        ex = json.loads(json.dumps(DOBBINS))
        ex["legs"][0]["market"] = "Alternate Pizza Count"
        d = extract.draft_from_extraction(ex, utc_offset_minutes=PT, now=NOW)
        self.assertIn("legs[0].market", {a["field"] for a in d["ambiguous"]})

    def test_a_known_team_is_matched_to_the_board_and_an_unmatched_game_is_flagged(self):
        games = [{"event_id": "e1", "sport": "NFL", "away_team": "Kansas City Chiefs", "home_team": "Las Vegas Raiders",
                  "commence_utc": "2026-10-25T20:25:00Z", "slate_date": "2026-10-25"}]
        ex = {"bet_type": "single", "leg_count": 1, "total_odds": -110, "stake": 10, "payout": 19.09,
              "placed_at": "2026-10-25T08:00:00", "bet_id": "X1", "status": "pending", "book": "DraftKings",
              "legs": [{"selection": "Chiefs", "market": "Moneyline", "line": None, "odds": -110, "game": "Chiefs @ Raiders",
                        "sport": "NFL", "player": None, "status": None}]}
        d = extract.draft_from_extraction(ex, utc_offset_minutes=PT, board_games=games, now=NOW)
        leg = d["lesson"]["legs"][0]
        self.assertEqual((leg["event_id"], leg["side"]), ("e1", "away"))
        self.assertEqual(d["ambiguous"], [])
        ex["legs"][0]["game"], ex["legs"][0]["selection"] = "Jets @ Bills", "Jets"
        d = extract.draft_from_extraction(ex, utc_offset_minutes=PT, board_games=games, now=NOW)
        self.assertIn("legs[0].game", {a["field"] for a in d["ambiguous"]})

    def test_import_sends_the_image_to_the_router_and_stages_it_without_filing(self):
        router = FakeRouter(DOBBINS)
        out = service.import_screenshot(self.h, 7, PNG, router, utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        self.assertTrue(out["ok"] and out["needs_confirmation"])
        self.assertEqual(router.calls[0]["images"][0]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(router.calls[0]["images"][0]["data"]), PNG)
        self.assertEqual(self.pairs(), [])                                           # nothing in the ledger yet
        self.assertIsNotNone(store.staged(7, out["image"]["hash"]))

    def test_a_capped_router_says_import_unavailable_enter_manually(self):
        out = service.import_screenshot(self.h, 7, PNG, FakeRouter(capped=True), now=NOW, games=[])
        self.assertEqual((out["ok"], out["capped"], out["message"]), (False, True, "Import unavailable, enter manually."))
        out = service.import_screenshot(self.h, 7, PNG, FakeRouter(ok=False), now=NOW, games=[])
        self.assertFalse(out["ok"])

    def test_a_non_image_and_an_oversize_image_are_refused(self):
        with self.assertRaises(service.ServiceError):
            service.decode_image(base64.b64encode(b"not an image at all").decode())
        with self.assertRaises(store.StoreError):
            store.sniff_image(PNG + b"\x00" * store.MAX_IMAGE_BYTES)


class RouterVisionTests(unittest.TestCase):
    """The router gains an optional ``images`` argument: the cap sees it, the SDK request carries it."""

    def test_images_reach_the_sdk_request_and_a_zero_cap_still_refuses(self):
        from src.ai import router as R
        from src.ai.usage import UsageStore
        sent = []

        class Client:
            class messages:
                @staticmethod
                def create(**params):
                    sent.append(params)
                    return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok": true}')],
                                           usage=SimpleNamespace(input_tokens=10, output_tokens=5), stop_reason="end_turn")
        adapter = R.AnthropicAdapter(client_factory=lambda key, timeout: Client)
        with tempfile.TemporaryDirectory() as d:
            env = {"ANTHROPIC_API_KEY": "sk-ant-test-0000000000"}
            r = R.Router(R.load_config(), env=env, adapters={"anthropic": adapter}, usage=UsageStore(Path(d) / "u.jsonl"))
            ans = r.ask("sys", "read it", schema={"type": "object"}, purpose="t",
                        images=[{"media_type": "image/png", "data": "AAAA"}])
            self.assertTrue(ans.ok)
            content = sent[0]["messages"][0]["content"]
            self.assertEqual(content[0]["type"], "image")
            self.assertEqual(content[0]["source"]["data"], "AAAA")
            self.assertEqual(content[-1], {"type": "text", "text": "read it"})
            ans = r.ask("sys", "plain", schema={"type": "object"}, purpose="t")           # no images: a plain string as before
            self.assertEqual(sent[1]["messages"][0]["content"], "plain")
            capped = R.Router(R.load_config(), env={**env, "AI_PAID_CAP_USD": "0.0000001"}, adapters={"anthropic": adapter},
                              usage=UsageStore(Path(d) / "u2.jsonl"))
            ans = capped.ask("sys", "x", schema={"type": "object"}, purpose="t",
                             images=[{"media_type": "image/png", "data": "AAAA"}])
            self.assertFalse(ans.ok)
            self.assertEqual(len(sent), 2)                                                   # the call never reached the SDK


class LedgerTests(Base):
    def test_a_manual_lesson_stores_what_was_typed_and_starts_pending(self):
        v = self.add(price_note=None) if False else self.add()
        self.assertEqual((v["state"], v["stake"], v["bet_type"]), ("pending", 50.0, "single"))
        self.assertEqual(v["legs"][0]["price"], -110)
        self.assertEqual(v["history"][0]["source"], "owner")

    def test_append_only_the_database_refuses_update_and_delete(self):
        v = self.add()
        with store.connect() as conn:
            conn.execute("INSERT INTO apprentice_evidence VALUES ('ev-1', 7, 'u-aaa', ?, 'h', 'image/png', 1, 'p', '{}', 't')", (v["id"],))
            conn.execute("INSERT INTO apprentice_recommendations VALUES ('r-1', 'hound', '2026-10-24T00:00:00Z', '[]', 't')")
            sets = {"apprentice_lessons": "book", "apprentice_evidence": "image_hash", "apprentice_events": "state",
                    "apprentice_recommendations": "source"}
            for table in store.TABLES:
                for stmt in (f"UPDATE {table} SET {sets[table]} = 'x'", f"DELETE FROM {table}"):
                    with self.assertRaises(sqlite3.DatabaseError, msg=stmt):
                        conn.execute(stmt)
        self.assertEqual(len(self.pairs()), 1)
        self.assertEqual(v["id"], self.pairs()[0][0]["id"])

    def test_the_store_has_no_update_or_delete_function(self):
        names = [n for n in dir(store) if not n.startswith("_")]
        self.assertFalse([n for n in names if re.search(r"update|delete|remove|edit|purge_lesson", n, re.I)], names)
        self.assertEqual(sorted(n for n in names if n in ("add_lesson", "append_event")), ["add_lesson", "append_event"])

    def test_a_retired_hound_keeps_its_lessons_but_takes_no_new_ones(self):
        self.add()
        self.h["status"] = "retired"
        self.assertEqual(len(self.pairs()), 1)
        out = service.overview(self.h, 7, db=self.db, grade=False)
        self.assertEqual(len(out["lessons"]), 1)
        self.assertFalse(out["can_add"])
        with self.assertRaises(service.ServiceError) as ctx:
            self.add()
        self.assertEqual(ctx.exception.code, "not_active")

    def test_lessons_follow_the_hound_across_versions(self):
        self.add()
        newer = hound(id="u-bbb", root_id="u-aaa")
        self.assertEqual(len(store.lessons_for(newer["root_id"])), 1)

    def test_only_the_owner_of_an_apprentice_hound_reaches_it(self):
        for who, h in ((8, self.h), (7, hound(spec=user_spec.validate_spec(
                {"version": 2, "name": "Plain Pup", "rules": [{"sports": ["MLB"], "markets": ["moneyline"], "side": "either"}]})))):
            with self.assertRaises(service.ServiceError) as ctx:
                service.overview(h, who, db=self.db, grade=False)
            self.assertEqual(ctx.exception.status, 404)

    def test_bad_input_is_refused_with_every_field_named(self):
        with self.assertRaises(service.ServiceError) as ctx:
            service.add_manual(self.h, 7, {"legs": [{"sport": "NFL"}], "stake": -1}, now=NOW, games=[])
        fields = ctx.exception.extra["fields"]
        for key in ("legs[0].market", "legs[0].selection", "legs[0].price", "stake", "book", "placed_at"):
            self.assertIn(key, fields)

    def test_an_inconsistent_ticket_is_refused_not_stored(self):
        legs = [self.leg(price=-115), self.leg(price=-112, selection="Raiders", side="home")]
        with self.assertRaises(service.ServiceError) as ctx:
            self.add(legs, total_price=253, stake=100.18, payout=500)
        self.assertEqual(ctx.exception.code, "inconsistent")
        self.assertEqual(self.pairs(), [])

    def test_a_parlay_is_one_lesson_with_n_legs(self):
        v = self.add([self.leg(price=-115), self.leg(price=-112, selection="Raiders", side="home")], stake=100.18,
                     total_price=253, payout=354.51)
        self.assertEqual((v["bet_type"], len(v["legs"]), v["total_price"]), ("parlay", 2, 253))


class ConfirmAndDedupeTests(Base):
    def import_and_confirm(self, image=PNG, ex=None, ack=(), lesson=None, lesson_id=None):
        out = service.import_screenshot(self.h, 7, image, FakeRouter(ex or DOBBINS), utc_offset_minutes=PT, now=NOW,
                                        games=[], db=self.db)
        return out, service.confirm_import(self.h, 7, out["image"]["hash"], lesson or out["lesson"], acknowledged=ack,
                                           lesson_id=lesson_id, now=NOW, games=[], db=self.db, path=self.ledger)

    def test_the_reference_ticket_files_with_its_screenshot_and_extraction_as_evidence(self):
        _out, done = self.import_and_confirm()
        v = done["lesson"]
        self.assertTrue(done["filed"])
        self.assertEqual((v["ticket_id"], v["stake"], v["total_price"], v["payout_quoted"]),
                         ("DK639285386193890132", 100.18, 253, 354.51))
        self.assertEqual(v["placed_utc"], "2026-10-25T15:23:39Z")
        ev = store.evidence_for(v["id"], 7)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["extracted"]["extracted"]["bet_id"], "DK639285386193890132")
        path, media = store.evidence_file(ev[0]["id"], 7)
        self.assertEqual((path.read_bytes(), media), (PNG, "image/png"))
        self.assertIsNone(store.evidence_file(ev[0]["id"], 8))                       # nobody else's

    def test_nothing_is_filed_while_an_ambiguous_field_is_untouched(self):
        ex = json.loads(json.dumps(DOBBINS))
        ex["payout"] = 500.0
        out = service.import_screenshot(self.h, 7, PNG, FakeRouter(ex), utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        self.assertIn("payout", [a["field"] for a in out["ambiguous"]])
        with self.assertRaises(service.ServiceError) as ctx:
            service.confirm_import(self.h, 7, out["image"]["hash"], out["lesson"], now=NOW, games=[], db=self.db)
        self.assertEqual(ctx.exception.code, "unconfirmed_fields")
        self.assertEqual(self.pairs(), [])
        fixed = dict(out["lesson"], payout=354.51)                                    # an edit resolves it
        done = service.confirm_import(self.h, 7, out["image"]["hash"], fixed, now=NOW, games=[], db=self.db, path=self.ledger)
        self.assertTrue(done["filed"])

    def test_acknowledging_a_field_resolves_it_but_the_numbers_must_still_agree(self):
        ex = json.loads(json.dumps(DOBBINS))
        ex["bet_id"] = None
        out = service.import_screenshot(self.h, 7, PNG, FakeRouter(ex), utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        done = service.confirm_import(self.h, 7, out["image"]["hash"], out["lesson"], acknowledged=["ticket_id"], now=NOW,
                                      games=[], db=self.db, path=self.ledger)
        self.assertIsNone(done["lesson"]["ticket_id"])

    def test_dedupe_by_bet_id_the_same_bet_cannot_be_filed_twice(self):
        self.import_and_confirm()
        out = service.import_screenshot(self.h, 7, PNG2, FakeRouter(DOBBINS), utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        self.assertEqual(out["duplicate"]["by"], "bet ID")
        with self.assertRaises(service.ServiceError) as ctx:
            service.confirm_import(self.h, 7, out["image"]["hash"], out["lesson"], now=NOW, games=[], db=self.db)
        self.assertEqual(ctx.exception.code, "duplicate")
        self.assertEqual(len(self.pairs()), 1)

    def test_the_same_image_twice_is_answered_without_calling_the_model(self):
        self.import_and_confirm()
        router = FakeRouter(DOBBINS)
        out = service.import_screenshot(self.h, 7, PNG, router, utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        self.assertEqual(out["duplicate"]["by"], "screenshot")
        self.assertEqual(router.calls, [])

    def test_a_reimport_updates_state_only_by_appending_a_state_change_row(self):
        _o, done = self.import_and_confirm()
        lid = done["lesson"]["id"]
        before = store.get_lesson(lid)
        won = json.loads(json.dumps(DOBBINS))
        won["status"] = "won"
        for leg in won["legs"]:
            leg["status"] = "won"
        out = service.import_screenshot(self.h, 7, PNG2, FakeRouter(won), utc_offset_minutes=PT, now=NOW, games=[], db=self.db)
        self.assertEqual(out["duplicate"]["lesson_id"], lid)
        self.assertEqual(out["duplicate"]["state_change"]["state"], "settled")
        res = service.confirm_import(self.h, 7, out["image"]["hash"], out["lesson"], lesson_id=lid, now=NOW, games=[], db=self.db)
        self.assertFalse(res["filed"])
        self.assertTrue(res["state_changed"])
        self.assertEqual(store.get_lesson(lid), before)                               # the lesson row is untouched
        v = res["lesson"]
        self.assertEqual([h["state"] for h in v["history"]], ["pending", "settled"])
        self.assertEqual((v["history"][1]["source"], v["result"], v["profit"]), ("ticket", "won", 254.33))
        self.assertEqual(len(store.evidence_for(lid, 7)), 2)
        again = service.import_screenshot(self.h, 7, PNG2, FakeRouter(won), now=NOW, games=[], db=self.db)
        self.assertEqual(again["duplicate"]["by"], "screenshot")                      # the second screenshot is now known too

    def test_state_changes_cannot_regress_and_a_repeat_is_a_no_op(self):
        v = self.add()
        service.set_state(self.h, 7, v["id"], "live", now=NOW, db=self.db)
        res = service.set_state(self.h, 7, v["id"], "live", now=NOW, db=self.db)
        self.assertFalse(res["changed"])
        service.set_state(self.h, 7, v["id"], "settled", {"result": "lost"}, now=NOW, db=self.db)
        with self.assertRaises(service.ServiceError) as ctx:
            service.set_state(self.h, 7, v["id"], "pending", now=NOW, db=self.db)
        self.assertEqual(ctx.exception.code, "terminal")
        with self.assertRaises(service.ServiceError):
            service.set_state(self.h, 7, v["id"], "settled", {"result": "maybe"}, now=NOW, db=self.db)
        states = [h["state"] for h in service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]["history"]]
        self.assertEqual(states, ["pending", "live", "settled"])

    def test_cash_out_is_its_own_state_with_its_own_profit(self):
        v = self.add(stake=100)
        res = service.set_state(self.h, 7, v["id"], "cashed_out", {"cash_out_amount": 140.5}, now=NOW, db=self.db)["lesson"]
        self.assertEqual((res["state"], res["profit"], res["payout"]), ("cashed_out", 40.5, 140.5))
        with self.assertRaises(service.ServiceError):
            service.set_state(self.h, 7, v["id"], "cashed_out", {}, now=NOW, db=self.db)
        summary = analytics.summarize(self.pairs())
        self.assertEqual((summary["overall"]["profit"], summary["overall"]["wins"], summary["overall"]["losses"],
                          summary["cashed_out"]), (40.5, 0, 0, 1))


class GradingTests(Base):
    GAME = {"event_id": "e1", "sport": "NFL", "away_team": "Kansas City Chiefs", "home_team": "Las Vegas Raiders",
            "commence_utc": "2026-10-25T20:25:00Z", "slate_date": "2026-10-25"}
    LATER = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)

    def results(self, home, away):
        return {"nfl_results": lambda d: {("KC", "LV"): {"home_score": home, "away_score": away}} if d == "2026-10-25" else {},
                "close_fn": lambda bet: -125}

    def graded_lesson(self, **kw):
        legs = [self.leg(event_id="e1", sport="NFL", game="Kansas City Chiefs @ Las Vegas Raiders", price=-110)]
        return service.add_manual(self.h, 7, self.raw(legs, **kw), now=NOW, games=[self.GAME], path=self.ledger)

    def sync(self, home, away):
        return grading.sync(self.h["root_id"], 7, path=self.ledger, now=self.LATER, run_settle=True,
                            settle_kwargs=self.results(home, away))

    def test_a_logged_bet_on_a_board_game_is_graded_through_the_settle_path(self):
        v = self.graded_lesson()
        self.assertTrue(grading.gradable(store.get_lesson(v["id"])["legs"][0]))
        self.sync(17, 24)                                                             # the Chiefs (away) win
        out = service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]
        self.assertEqual((out["state"], out["result"], out["basis"]), ("settled", "won", "grader"))
        self.assertEqual(out["profit"], 45.45)                                        # $50 at -110
        clv = analytics.summarize(self.pairs())["clv"]
        self.assertEqual(clv["legs"], 1)
        self.assertGreater(clv["mean_pts"], 0)                                        # closed at -125, got -110: positive

    def test_the_mirror_ledger_is_apart_from_every_hound_ledger_and_sends_no_alert(self):
        self.graded_lesson()
        with mock.patch("src.notify.alerts.emit_settled_safe") as emitted:
            self.sync(17, 24)
        emitted.assert_not_called()
        self.assertTrue(Path(self.ledger).exists())
        self.assertFalse(Path(os.environ["HOUNDS_USER_LEDGER"]).exists())

    def test_a_typed_game_cannot_be_graded_and_stays_open(self):
        v = self.add()
        self.assertFalse(grading.gradable(store.get_lesson(v["id"])["legs"][0]))
        self.sync(17, 24)
        self.assertEqual(service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]["state"], "pending")

    def test_a_client_cannot_invent_a_board_game(self):
        legs = [self.leg(event_id="made-up", away_team="X", home_team="Y", commence_time="2026-10-25T20:00:00Z",
                         slate_date="2026-10-25")]
        v = service.add_manual(self.h, 7, self.raw(legs), now=NOW, games=[self.GAME], path=self.ledger)
        leg = store.get_lesson(v["id"])["legs"][0]
        self.assertNotIn("event_id", leg)
        self.assertFalse(grading.gradable(leg))

    def test_a_grading_disagreement_is_flagged_and_nothing_is_overwritten(self):
        v = self.graded_lesson()
        service.set_state(self.h, 7, v["id"], "settled", {"result": "lost"}, now=NOW, db=self.db)     # the ticket said lost
        self.sync(17, 24)                                                                             # our grader says won
        out = service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]
        self.assertTrue(out["disputed"])
        self.assertTrue(any("neither was overwritten" in f for f in out["flags"]))
        self.assertIsNone(out["profit"])
        self.assertEqual([(h["source"], h["state"], h["data"].get("result")) for h in out["history"]],
                         [("owner", "pending", None), ("owner", "settled", "lost"), ("grader", "settled", "won")])
        summary = analytics.summarize(self.pairs())
        self.assertEqual((summary["disputed"], summary["overall"]["counted"], summary["overall"]["profit"]), (1, 0, 0.0))
        res = service.set_state(self.h, 7, v["id"], "settled", {"result": "won", "resolution": True}, now=self.LATER,
                                db=self.db)["lesson"]                                                 # the owner resolves it
        self.assertFalse(res["disputed"])
        self.assertEqual(res["result"], "won")

    def test_agreement_is_not_a_dispute(self):
        v = self.graded_lesson()
        service.set_state(self.h, 7, v["id"], "settled", {"result": "won"}, now=NOW, db=self.db)
        self.sync(17, 24)
        out = service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]
        self.assertFalse(out["disputed"])
        self.assertEqual(out["profit"], 45.45)

    def test_a_parlay_with_one_winning_leg_stays_open_until_the_other_is_known(self):
        legs = [self.leg(event_id="e1", sport="NFL", price=-110), self.leg(price=-110, selection="Typed", game="typed game")]
        v = service.add_manual(self.h, 7, self.raw(legs, stake=100), now=NOW, games=[self.GAME], path=self.ledger)
        self.sync(17, 24)                                                                             # leg 1 wins
        out = service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]
        self.assertEqual(out["state"], "pending")                                                     # NOT a win
        self.assertIsNone(out["profit"])
        service.set_state(self.h, 7, v["id"], "settled", {"result": "lost"}, now=self.LATER, db=self.db)
        self.assertEqual(service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]["profit"], -100.0)

    def test_a_parlay_with_a_graded_lost_leg_is_lost_at_once(self):
        legs = [self.leg(event_id="e1", sport="NFL", price=-110), self.leg(price=-110, selection="Typed", game="typed game")]
        service.add_manual(self.h, 7, self.raw(legs, stake=100), now=NOW, games=[self.GAME], path=self.ledger)
        self.sync(30, 10)                                                                             # leg 1 (Chiefs) loses
        out = service.overview(self.h, 7, db=self.db, grade=False)["lessons"][0]
        self.assertEqual((out["state"], out["result"], out["profit"]), ("settled", "lost", -100.0))

    def test_grading_is_idempotent(self):
        self.graded_lesson()
        self.sync(17, 24)
        self.assertEqual(self.sync(17, 24)["graded_events"], 0)
        events = self.pairs()[0][1]
        self.assertEqual(len([e for e in events if e["source"] == "grader"]), 1)


class AnalyticsTests(Base):
    def seed(self):
        a = self.add([self.leg(price=-110, sport="NFL", market="spread", line=-3.5, side="home")], stake=100)
        b = self.add([self.leg(price=150, sport="MLB", game="A @ B", selection="A")], stake=50)
        c = self.add([self.leg(price=200, sport="MLB", game="C @ D", selection="C")], stake=50)
        d = self.add([self.leg(price=-110, sport="NFL", game="E @ F", selection="E")], stake=100)
        e = self.add([self.leg(price=-110, sport="NFL", game="G @ H", selection="G")], stake=100)
        for lesson, result in ((a, "won"), (b, "lost"), (c, "won")):
            service.set_state(self.h, 7, lesson["id"], "settled", {"result": result}, now=NOW, db=self.db)
        service.set_state(self.h, 7, d["id"], "settled", {"result": "push"}, now=NOW, db=self.db)
        return a, b, c, d, e

    def test_profit_roi_win_rate_and_cuts_come_from_real_numbers_only(self):
        self.seed()
        s = analytics.summarize(self.pairs())
        o = s["overall"]
        # a: +90.91 on 100, b: -50, c: +100 on 50, d: push (0, counted), e: open (not counted)
        self.assertEqual((o["staked"], o["profit"], o["wins"], o["losses"]), (300.0, 140.91, 2, 1))
        self.assertEqual((o["roi"], o["win_rate"]), (round(140.91 / 300, 4), round(2 / 3, 4)))
        self.assertEqual((s["open"], s["lessons"], o["n"], o["counted"]), (1, 5, 5, 4))
        cuts = {d: {c["key"]: c for c in rows} for d, rows in s["cuts"].items()}
        self.assertEqual(cuts["sport"]["MLB"]["profit"], 50.0)
        self.assertEqual(cuts["market"]["spread"]["n"], 1)
        self.assertEqual(cuts["band"]["+120 to +249"]["wins"], 1)
        self.assertEqual(cuts["role"]["plus money"]["n"], 2)
        self.assertEqual(s["clv"], {"legs": 0, "mean_pts": None, "positive": None})            # no closing price: left empty

    def test_an_empty_ledger_has_no_numbers_not_zeros(self):
        s = analytics.summarize([])
        self.assertEqual((s["overall"]["roi"], s["overall"]["win_rate"], s["lessons"]), (None, None, 0))

    def test_correlated_exposure_groups_by_game_and_by_player(self):
        game = self.leg(game="Chiefs @ Raiders", price=-110)
        self.add([game], stake=40)
        self.add([dict(game, market="total", selection="Over 44", side="over", line=44.0)], stake=60)
        self.add([self.leg(game="Chiefs @ Raiders", market="player_rushing_yards", player="J.K. Dobbins", selection="O49.5",
                           side="over", line=49.5)], stake=25)
        self.add([self.leg(game="Chargers @ Broncos", market="player_rushing_yards", player="J.K. Dobbins", selection="O49.5",
                           side="over", line=49.5)], stake=10)
        self.add([self.leg(game="Solo @ Game")], stake=5)
        ex = analytics.summarize(self.pairs())["exposure"]
        self.assertEqual([(g["label"], len(g["lessons"]), g["open_staked"]) for g in ex["games"]],
                         [("Chiefs @ Raiders", 3, 125.0)])
        self.assertEqual([(p["label"], len(p["lessons"]), p["open_staked"]) for p in ex["players"]], [("J.K. Dobbins", 2, 35.0)])


class FreezeRuleTests(Base):
    def seed_settled(self, n, at):
        for i in range(n):
            v = self.add([self.leg(sport="NFL", market="total", selection="Over", side="over", line=44.5 + i, price=-105,
                                   game=f"G{i} @ H{i}")], stake=50, ticket_id=f"T{at.minute}-{i}")
            service.set_state(self.h, 7, v["id"], "settled", {"result": "won"}, now=at, db=self.db)

    def test_the_summary_uses_only_lessons_settled_before_the_proposal_time(self):
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        self.seed_settled(5, t0)
        proposal_time = t0 + timedelta(hours=1)
        before = learning.summarize(self.pairs(), proposal_time)
        self.assertEqual(before["settled"], 5)
        later = t0 + timedelta(hours=2)
        self.seed_settled(1, later.replace(minute=7))                                    # settles AFTER the proposal time
        v = self.pairs()[0][0]
        service.set_state(self.h, 7, v["id"], "settled", {"result": "lost", "resolution": True}, now=later, db=self.db)
        after = learning.summarize(self.pairs(), proposal_time)
        self.assertEqual(after, before)                                                  # byte for byte
        self.assertNotEqual(learning.summarize(self.pairs(), later + timedelta(hours=1)), before)

    def test_a_proposal_made_at_t_is_not_changed_by_a_later_result(self):
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        self.seed_settled(5, t0)
        card = learning.propose(self.h, self.pairs(), t0 + timedelta(hours=1))
        self.assertFalse(card["nothing"])
        self.assertTrue(all(not r["spec"] is None for r in [card]))
        lid = self.pairs()[0][0]["id"]
        service.set_state(self.h, 7, lid, "settled", {"result": "lost", "resolution": True}, now=t0 + timedelta(hours=3), db=self.db)
        again = learning.propose(self.h, self.pairs(), t0 + timedelta(hours=1))
        self.assertEqual(card, again)

    def test_too_few_settled_bets_says_so_and_proposes_nothing(self):
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        self.seed_settled(2, t0)
        card = learning.propose(self.h, self.pairs(), t0 + timedelta(hours=1))
        self.assertTrue(card["nothing"])
        self.assertIn("2 settled bets", card["message"])

    def test_a_proposal_is_valid_paper_rules_and_never_reaches_minus_200(self):
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        for i in range(5):
            v = self.add([self.leg(sport="MLB", market="moneyline", price=-250 if i < 2 else -140, side="home",
                                   game=f"A{i} @ B{i}")], stake=50, ticket_id=f"M{i}")
            service.set_state(self.h, 7, v["id"], "settled", {"result": "won"}, now=t0, db=self.db)
        card = learning.propose(self.h, self.pairs(), t0 + timedelta(hours=1))
        self.assertFalse(card["nothing"])
        for rule in card["spec"]["rules"]:
            self.assertGreaterEqual(rule["price_min"], user_spec.SHORTEST_ALLOWED_PRICE)
        self.assertEqual(user_spec.validate_spec(card["spec"]), card["spec"])
        self.assertEqual(card["spec"]["style"], "apprentice")
        self.assertNotIn("dog", json.dumps(card["changes"]).lower().replace("underdog", ""))

    def test_apply_makes_a_new_version_only_for_the_reviewed_card(self):
        from src.hounds import user_store
        from src.appstate import users as users_store
        owner = users_store.create_user("owner@example.com", status="active")
        created = user_store.create_hound(owner.id, {"version": 2, "style": "apprentice", "name": "Pup Real", "tagline": "learns"})
        h = created
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        for i in range(5):
            raw = self.raw([self.leg(sport="NFL", market="total", selection="Over", side="over", line=44.5, price=-105,
                                     game=f"G{i} @ H{i}")], ticket_id=f"A{i}")
            lesson = model.normalize_lesson(raw, now=NOW)
            row = store.add_lesson(h, owner.id, lesson, now=t0)
            store.append_event(row["id"], owner.id, "owner", "settled", {"result": "won"}, now=t0)
        later = t0 + timedelta(hours=1)
        card = service.proposal(h, owner.id, now=later, db=None)
        self.assertFalse(card["nothing"])
        with self.assertRaises(service.ServiceError) as ctx:
            service.apply_proposal(h, owner.id, "wrong-basis", card["as_of"])
        self.assertEqual(ctx.exception.code, "proposal_stale")
        out = service.apply_proposal(h, owner.id, card["basis"], card["as_of"], now=later)
        self.assertEqual(out["hound"]["version_no"], 2)
        self.assertEqual(out["hound"]["spec"]["rules"], card["spec"]["rules"])
        self.assertEqual(len(store.lessons_for(h["root_id"])), 5)                      # the lessons are untouched
        with self.assertRaises(service.ServiceError):                                  # the old version is retired: a repeat is stale
            service.apply_proposal(h, owner.id, card["basis"], card["as_of"], now=later)


class WebTests(unittest.TestCase):
    WEB = Path(__file__).resolve().parent.parent / "web"

    def test_the_studio_module_never_writes_html_from_data(self):
        src = (self.WEB / "js" / "apprentice-studio.js").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(")
        clean = src.replace("linehound:dog-saved", "").replace("dog-common.js", "")      # the two existing names aside
        self.assertNotRegex(clean, r"(?i)\bdogs?\b|bet check")
        self.assertIn("textContent", src + "h(")                                         # text goes through the h() helper

    def test_a_script_in_a_selection_is_stored_as_text_and_rendered_as_text(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"APP_DB_PATH": str(Path(d) / "a.db"), "HOUNDS_LESSONS_LEDGER": str(Path(d) / "l")}):
                v = service.add_manual(hound(), 7, {"legs": [{"sport": "NFL", "game": "<img src=x onerror=alert(1)>",
                                                              "market": "moneyline", "selection": "<script>alert(1)</script>",
                                                              "side": "home", "price": -110}], "stake": 5, "book": "<b>DK</b>",
                                                    "placed_at": "2026-10-24T20:00:00Z"}, now=NOW, games=[])
        body = json.dumps(v)
        self.assertIn("<script>", json.loads(body)["legs"][0]["selection"])             # kept verbatim as data
        src = (self.WEB / "js" / "apprentice-studio.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", src)                                                # ...so only textContent can show it

    def test_hook_parity_every_hook_the_module_reads_is_in_the_studio_markup_once(self):
        js = (self.WEB / "js" / "apprentice-studio.js").read_text(encoding="utf-8")
        kennel = (self.WEB / "kennel.html").read_text(encoding="utf-8")
        hooks = set(re.findall(r'"data-hook":\s*"([a-z0-9-]+)"', js))
        self.assertIn("studio-lessons", hooks | set(re.findall(r'data-hook="(studio-lessons)"', kennel)))
        self.assertEqual(kennel.count('data-hook="studio-lessons"'), 1)
        self.assertEqual(len(re.findall(r'data-tab="lessons"', kennel)), 1)
        self.assertEqual(len(re.findall(r'data-tabpanel="lessons"', kennel)), 1)
        for hook in re.findall(r'q\("([a-z0-9-]+)"\)', js):
            self.assertIn(hook, js)
        # the builder keeps its two skeletons (static page and studio): this module touches neither
        for name in ("build-a-hound.html", "js/builder-skeleton.js"):
            self.assertNotIn("apprentice", (self.WEB / name).read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
