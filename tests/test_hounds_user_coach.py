"""src/hounds/user_coach.py: the Houndmaster door and every guard on it."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import user_coach as coach
from src.hounds import user_engine, user_settle, user_spec, user_store
from tests._hounds_user_fixtures import spec_dict

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def ledger_rows(hound_id: str, n: int, *, clv: float = 0.5) -> list:
    """n bets, all graded, for one hound (enough for records, verdicts and the 50-bet guard)."""
    rows = []
    for i in range(n):
        bet_id = f"b-{hound_id}-{i}"
        rows.append({"kind": user_engine.KIND_BET, "bet_id": bet_id, "hound_id": hound_id,
                     "recorded_utc": f"2026-10-{(i % 28) + 1:02d}T12:00:00Z", "slate_date": "2026-10-01",
                     "selection": f"Team {i} to win", "market": "moneyline", "price": 120})
        rows.append({"kind": user_settle.KIND_GRADED, "bet_id": bet_id, "hound_id": hound_id,
                     "result": "WIN" if i % 2 else "LOSS", "profit_units": 1.2 if i % 2 else -1.0,
                     "profit_units_best": 1.3 if i % 2 else -1.0,
                     "clv_pts": clv + (0.1 if i % 3 else -0.1)})
    return rows


class CoachCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.cfg = tmp / "hounds_coach.json"
        self._patches = [mock.patch.object(users_store, "db_path", lambda: self.db),
                         mock.patch.dict(os.environ, {coach.CONFIG_ENV: str(self.cfg)})]
        for p in self._patches:
            p.start()
        self.user = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.set_switch(True)
        self.hound = user_store.create_hound(
            self.user.id, spec_dict(name="Dog Days", markets=["moneyline", "spread"],
                                    side_rule="underdog", max_bets_per_day=3, min_books=2,
                                    price_min=-150, price_max=250),
            coach_opt_in=True, now=NOW - timedelta(days=30))
        self.rows = ledger_rows(self.hound["id"], 50)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def set_switch(self, on):
        self.cfg.write_text(json.dumps({"enabled": on}), encoding="utf-8")

    def open_round(self, hound=None, now=NOW):
        h = hound or self.hound
        return user_store.insert_round(h["id"], "test", now)

    def body(self, **spec_over):
        spec = dict(self.hound["spec"])
        spec.update(spec_over)
        return json.dumps({"spec": spec, "reason": "Spreads lose; keep moneylines only.",
                           "quip": "Fewer chews, better bones."})

    def send(self, rnd, body, *, hound=None, now=NOW, ts=None, sig=None, rows=None):
        h = hound or self.hound
        ts = str(int(now.timestamp())) if ts is None else ts
        sig = coach.sign(rnd["secret"], ts, h["id"], body) if sig is None else sig
        return coach.submit(h["id"], round_id=rnd["round_id"], ts=ts, sig=sig, body=body, now=now,
                            rows=self.rows if rows is None else rows)

    def refused(self, code, *args, **kw):
        with self.assertRaises(coach.CoachError) as ctx:
            self.send(*args, **kw)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception


class KillSwitch(CoachCase):
    def test_default_is_off_for_every_missing_or_malformed_state(self):
        for content in (None, "", "not json", "[]", '{"enabled": "true"}', '{"enabled": 1}',
                        '{"enabled": false}', "{}"):
            with self.subTest(content=content):
                if content is None:
                    self.cfg.unlink(missing_ok=True)
                else:
                    self.cfg.write_text(content, encoding="utf-8")
                self.assertFalse(coach.coach_enabled())

    def test_it_is_read_on_every_request_and_blocks_both_doors(self):
        rnd = self.open_round()
        self.set_switch(False)
        self.refused("coach_disabled", rnd, self.body(max_bets_per_day=2))
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(self.hound["id"], issued_by="admin", now=NOW, rows=self.rows)
        self.assertEqual(ctx.exception.code, "coach_disabled")
        self.set_switch(True)                                     # flipped back: no restart needed
        self.assertEqual(self.send(rnd, self.body(max_bets_per_day=2))["decision"], "applied")

    def test_the_repository_default_file_ships_off(self):
        shipped = Path(__file__).resolve().parent.parent / "config" / "hounds_coach.json"
        self.assertIs(json.loads(shipped.read_text(encoding="utf-8"))["enabled"], False)


class Signing(CoachCase):
    def test_a_good_proposal_is_applied_as_a_new_version_and_the_old_one_is_kept(self):
        rnd = self.open_round()
        out = self.send(rnd, self.body(markets=["moneyline"]))
        self.assertEqual(out["decision"], "applied")
        new, old = out["new_hound"], user_store.get_hound(self.hound["id"])
        self.assertEqual((new["version_of"], new["version_no"], new["status"]),
                         (self.hound["id"], 2, "running"))
        self.assertEqual(new["spec"]["markets"], ["moneyline"])
        self.assertEqual(old["spec"], self.hound["spec"])        # the old record is not rewritten
        self.assertEqual(old["status"], "retired")
        self.assertTrue(new["coach_opt_in"])

    def test_the_new_version_starts_with_a_fresh_record(self):
        out = self.send(self.open_round(), self.body(markets=["moneyline"]))
        records = user_settle.records_by_hound(self.rows)
        self.assertEqual(records[self.hound["id"]]["record"]["bets"], 50)   # old version keeps its own
        self.assertNotIn(out["new_hound"]["id"], records)                   # new one starts at zero

    def test_a_wrong_signature_is_refused_and_does_not_burn_the_key(self):
        rnd = self.open_round()
        body = self.body(max_bets_per_day=2)
        self.refused("bad_signature", rnd, body, sig="0" * 64)
        self.refused("bad_signature", rnd, body, sig=coach.sign("wrong-secret", "1", self.hound["id"], body))
        self.assertIsNone(user_store.get_round(rnd["round_id"])["used_at"])
        self.assertEqual(self.send(rnd, body)["decision"], "applied")

    def test_a_signature_covers_the_body_the_path_and_the_timestamp(self):
        rnd = self.open_round()
        body = self.body(max_bets_per_day=2)
        ts = str(int(NOW.timestamp()))
        good = coach.sign(rnd["secret"], ts, self.hound["id"], body)
        self.refused("bad_signature", rnd, body + " ", ts=ts, sig=good)             # body changed
        self.refused("bad_signature", rnd, body, ts=str(int(NOW.timestamp()) + 1), sig=good)
        self.refused("bad_signature", rnd, body, ts=ts, sig=coach.sign(rnd["secret"], ts, "u-other", body))

    def test_a_reused_key_is_refused(self):
        rnd = self.open_round()
        self.send(rnd, self.body(max_bets_per_day=2))
        self.refused("round_used", rnd, self.body(max_bets_per_day=1))

    def test_an_expired_key_is_refused(self):
        rnd = self.open_round()
        later = NOW + user_store.ROUND_TTL + timedelta(seconds=1)
        self.refused("round_expired", rnd, self.body(max_bets_per_day=2), now=later)

    def test_a_stale_or_garbled_timestamp_is_refused(self):
        rnd = self.open_round()
        body = self.body(max_bets_per_day=2)
        old_ts = str(int((NOW - timedelta(minutes=16)).timestamp()))
        self.refused("stale_timestamp", rnd, body, ts=old_ts, sig=coach.sign(rnd["secret"], old_ts, self.hound["id"], body))
        self.refused("bad_timestamp", rnd, body, ts="yesterday", sig="x")

    def test_a_round_for_another_hound_or_an_unknown_round_is_refused(self):
        other = user_store.create_hound(self.user.id, spec_dict(name="Other Pack"), coach_opt_in=True)
        rnd = self.open_round(other)
        self.refused("bad_round", rnd, self.body(), hound=self.hound)
        self.refused("bad_round", {"round_id": "r-nope", "secret": "x"}, self.body())

    def test_a_key_is_burned_at_once_even_if_the_proposal_is_refused(self):
        rnd = self.open_round()
        self.refused("widening_refused", rnd, self.body(max_bets_per_day=5))
        self.refused("round_used", rnd, self.body(max_bets_per_day=2))


class Narrowing(CoachCase):
    def widened(self, **over):
        rnd = self.open_round()
        exc = self.refused("widening_refused", rnd, self.body(**over))
        diary = user_store.diary_for(self.hound["id"])
        self.assertEqual(diary[0]["decision"], "rejected")
        self.assertIsNone(diary[0]["new_hound_id"])
        self.assertEqual(user_store.get_hound(self.hound["id"])["status"], "running")   # nothing applied
        return str(exc)

    def test_widening_a_market_is_refused(self):
        self.assertIn("markets", self.widened(markets=["moneyline", "spread", "total"], side_rule="market_moved_toward"))

    def test_adding_a_sport_is_refused(self):
        self.assertIn("sports", self.widened(sports=["MLB", "NFL"]))

    def test_raising_max_bets_is_refused_and_lowering_or_keeping_is_allowed(self):
        self.assertIn("max_bets_per_day", self.widened(max_bets_per_day=4))
        self.assertEqual(self.send(self.open_round(), self.body(max_bets_per_day=3))["decision"], "held")

    def test_lowering_max_bets_is_applied(self):
        self.assertEqual(self.send(self.open_round(), self.body(max_bets_per_day=1))["decision"], "applied")

    def test_widening_the_price_band_or_lowering_min_books_is_refused(self):
        self.assertIn("price band", self.widened(price_max=400))
        self.assertIn("price band", self.widened(price_min=-190))
        self.assertIn("min_books", self.widened(min_books=1))

    def test_changing_the_name_or_tagline_is_refused(self):
        self.assertIn("name", self.widened(name="Renamed Pack"))

    def test_a_price_at_or_beyond_the_cap_is_always_refused_by_the_menu(self):
        rnd = self.open_round()
        exc = self.refused("spec_invalid", rnd, self.body(price_min=-250))
        self.assertIn("price_min", str(exc))

    def test_a_narrowed_band_a_raised_min_books_and_a_new_side_rule_pass(self):
        out = self.send(self.open_round(), self.body(price_min=-120, price_max=200, min_books=4,
                                                      side_rule="away"))
        self.assertEqual(out["decision"], "applied")
        self.assertEqual(out["new_hound"]["spec"]["side_rule"], "away")


class Allowance(CoachCase):
    def test_not_opted_in_is_refused_at_both_doors(self):
        user_store.set_coach_opt_in(self.hound["id"], False)
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(self.hound["id"], issued_by="admin", now=NOW, rows=self.rows)
        self.assertEqual(ctx.exception.code, "not_opted_in")
        self.refused("not_opted_in", self.open_round(), self.body(max_bets_per_day=2))

    def test_fewer_than_fifty_graded_bets_since_the_last_version_is_refused_with_a_reason(self):
        short = ledger_rows(self.hound["id"], 49)
        exc = self.refused("not_enough_bets", self.open_round(), self.body(max_bets_per_day=2), rows=short)
        self.assertIn("49", str(exc))
        self.assertIn("50", str(exc))
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(self.hound["id"], issued_by="admin", now=NOW, rows=short)
        self.assertEqual(ctx.exception.code, "not_enough_bets")

    def test_bets_from_an_earlier_version_do_not_count_toward_the_new_one(self):
        out = self.send(self.open_round(), self.body(max_bets_per_day=2))
        new = out["new_hound"]
        later = NOW + timedelta(days=8)
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(new["id"], issued_by="admin", now=later, rows=self.rows)   # old bets only
        self.assertEqual(ctx.exception.code, "not_enough_bets")
        enough = self.rows + ledger_rows(new["id"], 50)
        self.assertIn("round_id", coach.issue_round(new["id"], issued_by="admin", now=later, rows=enough))

    def test_one_round_per_hound_per_seven_days_across_versions(self):
        out = self.send(self.open_round(), self.body(max_bets_per_day=2))
        new = out["new_hound"]
        rows = self.rows + ledger_rows(new["id"], 50)
        for days, ok in ((1, False), (6, False), (7, True)):
            with self.subTest(days=days):
                at = NOW + timedelta(days=days, minutes=1) if days == 7 else NOW + timedelta(days=days)
                if ok:
                    self.assertIn("round_id", coach.issue_round(new["id"], issued_by="admin", now=at, rows=rows))
                else:
                    with self.assertRaises(coach.CoachError) as ctx:
                        coach.issue_round(new["id"], issued_by="admin", now=at, rows=rows)
                    self.assertEqual(ctx.exception.code, "too_soon")

    def test_too_soon_is_also_enforced_when_a_round_is_submitted(self):
        user_store.add_diary(round_id="r-old", hound=self.hound, decision="held", decided_by="coach",
                             now=NOW - timedelta(days=3))
        self.refused("too_soon", self.open_round(), self.body(max_bets_per_day=2))

    def test_a_hold_uses_the_allowance_too(self):
        out = self.send(self.open_round(), self.body())          # identical spec
        self.assertEqual(out["decision"], "held")
        self.assertIsNone(out["new_hound"])
        self.refused("too_soon", self.open_round(now=NOW + timedelta(hours=1)), self.body(max_bets_per_day=2),
                     now=NOW + timedelta(hours=1))

    def test_a_refused_proposal_does_not_use_the_allowance(self):
        self.refused("widening_refused", self.open_round(), self.body(max_bets_per_day=5))
        self.assertEqual(self.send(self.open_round(), self.body(max_bets_per_day=2))["decision"], "applied")

    def test_only_one_open_round_at_a_time(self):
        coach.issue_round(self.hound["id"], issued_by="admin", now=NOW, rows=self.rows)
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(self.hound["id"], issued_by="admin", now=NOW, rows=self.rows)
        self.assertEqual(ctx.exception.code, "round_open")

    def test_a_benched_or_retired_hound_cannot_be_coached(self):
        user_store.retire_hound(self.hound["id"], by="owner", reason="done")
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(self.hound["id"], issued_by="admin", now=NOW, rows=self.rows)
        self.assertEqual(ctx.exception.code, "not_running")


class Text(CoachCase):
    def test_reason_and_quip_limits_and_filter(self):
        long_reason = json.dumps({"spec": self.hound["spec"], "reason": "x" * 201, "quip": ""})
        self.refused("bad_text", self.open_round(), long_reason)
        long_quip = json.dumps({"spec": self.hound["spec"], "reason": "ok", "quip": "q" * 91})
        self.refused("bad_text", self.open_round(), long_quip)
        rude = json.dumps({"spec": self.hound["spec"], "reason": "this is shit", "quip": ""})
        self.refused("bad_text", self.open_round(), rude)
        markup = json.dumps({"spec": self.hound["spec"], "reason": "<script>x</script>", "quip": ""})
        self.refused("bad_text", self.open_round(), markup)
        empty = json.dumps({"spec": self.hound["spec"], "reason": " ", "quip": ""})
        self.refused("bad_text", self.open_round(), empty)

    def test_exact_limits_are_accepted(self):
        body = json.dumps({"spec": dict(self.hound["spec"], max_bets_per_day=2),
                           "reason": "r" * 200, "quip": "q" * 90})
        out = self.send(self.open_round(), body)
        self.assertEqual((len(out["reason"]), len(out["quip"])), (200, 90))

    def test_only_spec_reason_and_quip_are_accepted(self):
        extra = json.dumps({"spec": self.hound["spec"], "reason": "ok", "quip": "", "retire": True})
        self.refused("bad_body", self.open_round(), extra)
        self.refused("bad_body", self.open_round(), "not json")
        self.refused("bad_body", self.open_round(), json.dumps({"reason": "ok"}))


class UndoAndDiary(CoachCase):
    def apply(self):
        return self.send(self.open_round(), self.body(markets=["moneyline"]))["new_hound"]

    def test_undo_retires_the_coached_version_and_resumes_the_previous_rule_as_a_new_version(self):
        coached = self.apply()
        out = coach.undo(coached["id"], now=NOW + timedelta(days=1))
        self.assertEqual(out["retired"]["status"], "retired")
        resumed = out["resumed"]
        self.assertEqual(resumed["version_of"], coached["id"])
        self.assertEqual(resumed["spec"], self.hound["spec"])
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(user_store.get_hound(coached["id"])["spec"]["markets"], ["moneyline"])  # kept
        self.assertEqual([h["version_no"] for h in user_store.lineage(resumed["id"])], [1, 2, 3])

    def test_an_uncoached_version_cannot_be_undone_and_neither_can_a_retired_one(self):
        with self.assertRaises(coach.CoachError) as ctx:
            coach.undo(self.hound["id"])
        self.assertEqual(ctx.exception.code, "not_coached")
        coached = self.apply()
        coach.undo(coached["id"])
        with self.assertRaises(coach.CoachError) as ctx:
            coach.undo(coached["id"])
        self.assertEqual(ctx.exception.code, "not_running")

    def test_undo_still_works_when_the_kill_switch_is_off(self):
        coached = self.apply()
        self.set_switch(False)
        self.assertEqual(coach.undo(coached["id"])["resumed"]["status"], "running")

    def test_undo_does_not_reopen_the_allowance(self):
        coached = self.apply()
        resumed = coach.undo(coached["id"], now=NOW + timedelta(days=1))["resumed"]
        rows = self.rows + ledger_rows(resumed["id"], 50)
        with self.assertRaises(coach.CoachError) as ctx:
            coach.issue_round(resumed["id"], issued_by="admin", now=NOW + timedelta(days=2), rows=rows)
        self.assertEqual(ctx.exception.code, "too_soon")

    def test_the_diary_has_one_row_per_round_with_everything_that_was_decided(self):
        coached = self.apply()
        coach.undo(coached["id"], now=NOW + timedelta(days=1))
        entries = coach.diary(coached["id"], rows=self.rows)["entries"]
        self.assertEqual([e["decision"] for e in entries], ["undone", "applied"])
        applied = entries[1]
        for key in ("round_id", "hound_id", "decided_at", "verdict", "decision", "old_spec",
                    "new_spec", "reason", "quip", "decided_by", "new_hound_id"):
            self.assertIn(key, applied)
        self.assertEqual(applied["decided_by"], "coach")
        self.assertEqual(entries[0]["decided_by"], "owner")
        self.assertEqual(applied["verdict"]["graded"], 50)
        self.assertEqual(applied["old_spec"], self.hound["spec"])
        self.assertEqual(applied["new_spec"]["markets"], ["moneyline"])
        self.assertEqual(applied["quip"], "Fewer chews, better bones.")

    def test_refused_rounds_are_in_the_diary_too(self):
        self.refused("widening_refused", self.open_round(), self.body(max_bets_per_day=5))
        entry = coach.diary(self.hound["id"], rows=self.rows)["entries"][0]
        self.assertEqual(entry["decision"], "rejected")
        self.assertIn("widening_refused", entry["reason"])


class Metrics(CoachCase):
    def test_counts_and_comparison_are_null_until_each_side_has_fifty_bets(self):
        coached = self.send(self.open_round(), self.body(markets=["moneyline"]))["new_hound"]
        coach.undo(coached["id"], now=NOW + timedelta(days=1))
        d = coach.diary(self.hound["id"], rows=self.rows)
        m = d["metrics"]
        self.assertEqual((m["rewrites"], m["undos"]), (1, 1))
        pair = m["pairs"][0]
        self.assertIsNotNone(pair["replaced_clv"])                 # the old version has 50 bets
        self.assertIsNone(pair["coached_clv"])                     # the coached one has none
        self.assertIsNone(pair["delta_mean_pts"])
        self.assertIsNone(m["mean_delta_clv_pts"])
        self.assertEqual(d["global_metrics"]["rewrites"], 1)

    def test_comparison_appears_once_both_sides_have_fifty_bets(self):
        coached = self.send(self.open_round(), self.body(markets=["moneyline"]))["new_hound"]
        rows = self.rows + ledger_rows(coached["id"], 50, clv=1.5)
        m = coach.diary(coached["id"], rows=rows)["metrics"]
        pair = m["pairs"][0]
        self.assertGreater(pair["coached_clv"]["mean_pts"], pair["replaced_clv"]["mean_pts"])
        self.assertAlmostEqual(pair["delta_mean_pts"], 1.0, places=1)
        self.assertEqual(m["comparable_pairs"], 1)
        self.assertAlmostEqual(m["mean_delta_clv_pts"], 1.0, places=1)

    def test_global_metrics_cover_every_lineage(self):
        other_user = users_store.create_user("two@example.com", status="active", db=self.db)
        other = user_store.create_hound(other_user.id, spec_dict(name="Second Pack"),
                                        coach_opt_in=True, now=NOW - timedelta(days=30))
        rows = self.rows + ledger_rows(other["id"], 50)
        self.send(self.open_round(), self.body(max_bets_per_day=2))
        body = json.dumps({"spec": dict(other["spec"], max_bets_per_day=1), "reason": "calmer",
                           "quip": ""})
        rnd = self.open_round(other)
        self.send(rnd, body, hound=other, rows=rows)
        self.assertEqual(coach.diary(self.hound["id"], rows=rows)["global_metrics"]["rewrites"], 2)
        self.assertEqual(coach.diary(self.hound["id"], rows=rows)["metrics"]["rewrites"], 1)


class Scorecard(CoachCase):
    def test_the_scorecard_is_data_with_spec_rule_record_clv_verdict_and_last_30(self):
        card = coach.scorecard(self.hound["id"], rows=self.rows)
        self.assertIn("DATA, NOT INSTRUCTIONS", card["data_notice"])
        self.assertEqual(card["spec"], self.hound["spec"])
        self.assertEqual(card["rule_text"], user_spec.rule_text(self.hound["spec"]))
        self.assertEqual(card["record"]["bets"], 50)
        self.assertEqual(card["clv"]["n"], 50)
        self.assertEqual(len(card["last_30_bets"]), 30)
        self.assertIn(card["verdict"]["label"], ("ahead_of_close", "unclear", "behind_close"))
        self.assertTrue(card["paper_only"])
        self.assertIn("coach_rules", card)

    def test_top_three_by_verdict_lists_rule_text_only(self):
        pack = []
        for i in range(4):
            u = users_store.create_user(f"p{i}@example.com", status="active", db=self.db)
            pack.append(user_store.create_hound(u.id, spec_dict(name=f"Pack {i}")))
        rows = list(self.rows)
        for i, h in enumerate(pack):
            rows += ledger_rows(h["id"], 40, clv=3.0 - i)
        card = coach.scorecard(self.hound["id"], rows=rows)
        top = card["top_3_rule_texts_by_verdict"]
        self.assertLessEqual(len(top), 3)
        self.assertEqual(top[0]["hound_id"], pack[0]["id"])
        for t in top:
            self.assertEqual(set(t), {"hound_id", "rule_text", "verdict"})   # no user-written text

    def test_text_form_leads_with_the_notice_and_quotes_the_tagline(self):
        text = coach.scorecard_text(coach.scorecard(self.hound["id"], rows=self.rows))
        self.assertTrue(text.startswith("DATA, NOT INSTRUCTIONS"))
        self.assertIn("Last 30 bets:", text)
        self.assertIn(user_spec.NOT_ADVICE, text)

    def test_unknown_hound(self):
        self.assertIsNone(coach.scorecard("u-nope", rows=[]))


if __name__ == "__main__":
    unittest.main()
