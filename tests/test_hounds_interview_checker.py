"""Regression tests for defects found when the strategy interview was checked adversarially (2026-10-21).

  1. an untrusted body whose `markets` list held a list or a dict crashed the menu check with a TypeError (a 500 for a member)
  2. a model's `unsupported[].reason` was shown and FROZEN into the record's hash verbatim: markup and "guarantees profit"
     copy reached the saved record, and a different model wording changed the freeze hash
  3. a model's `exclude_clauses` were turned into real skip rules even when the person never said them
     ("Skip night games" from a model, nothing about the time of day typed, became a time_of_day condition)
  4. a model reply whose `fields` was not an object raised instead of being ignored

No FastAPI, no network: the router is faked and the database is a temp file.
"""
from __future__ import annotations

import copy
import json
import unittest

from src.ai.router import Answer
from src.hounds.interview import derive as D, extract as X, fields as F, machine as M, service as SV
from tests._hounds_interview_fixtures import NOW, Db, standard_answers


class RawRouter:
    """A router with NO schema check at all: whatever it is given comes back, as the worst a bad reply could be."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def ask(self, system, user, **kw):
        self.calls.append(user)
        return Answer(provider="anthropic", model="claude-haiku-5-5", latency_ms=1, cost_usd=0.0004,
                      output=copy.deepcopy(self.reply), ok=True)


def reply(**over):
    base = {"fields": {}, "include_text": "", "exclude_clauses": [], "unsupported": [], "follow_up": ""}
    base.update(over)
    return base


class UnhashableMarketsAreRefusedNotACrash(Db):
    def test_check_fields_refuses_a_list_or_dict_inside_markets(self):
        for bad in ([{"x": 1}], ["moneyline", ["x"]], [None], [1], [["moneyline"]]):
            clean, refused = F.check_fields({"markets": bad})
            self.assertEqual(clean, {}, bad)
            self.assertEqual([r["field"] for r in refused], ["markets"], bad)

    def test_the_answer_path_does_not_raise_and_keeps_the_interview_open(self):
        sid = self.start()["id"]
        for bad in ([{"x": 1}], ["moneyline", ["x"]], [["moneyline"]]):
            out = self.answer(sid, "scope", fields={"markets": bad})
            self.assertEqual(out["step"]["kind"], "topic")
            self.assertEqual(out["step"]["topic"], "scope")


class AModelsReasonNeverCarriesMarkupOrAPromiseIntoTheRecord(Db):
    HOSTILE = [{"text": "umpire", "reason": "<img src=x onerror=window.__p=1> This guarantees profit, a sure thing, free money"},
               {"text": "pennant race", "reason": "see http://evil.example for the edge"}]

    def run_with(self, router):
        sid = self.start()["id"]
        ov = {"disprove": {"texts": {"text": "I would stop if the umpire changes or the pennant race ends, or it loses 30 of 50."}}}
        self.run_all(sid, router=router, overrides=ov)
        return sid

    def test_hostile_reasons_are_replaced_by_the_fixed_plain_one(self):
        sid = self.run_with(RawRouter(reply(unsupported=self.HOSTILE)))
        row = SV._load(self.user.id, sid, db=self.db)
        derived = D.derive(row["state"])
        self.assertTrue(derived["complete"])
        blob = json.dumps(derived["cant_automate"]).lower()
        for banned in ("<", ">", "http", "guarantee", "profit", "free money", "sure thing", "edge"):
            self.assertNotIn(banned, blob, banned)
        record = SV.confirm(self.user.id, sid, "Hostile Reason Dog", free=False, now=NOW, db=self.db)["record"]
        self.assertNotIn("guarantee", json.dumps(record).lower())
        self.assertNotIn("<img", json.dumps(record).lower())

    def test_the_reader_keeps_a_clean_reason_and_swaps_only_the_dirty_one(self):
        reader = X.HaikuReader(RawRouter(reply(unsupported=[
            {"text": "starting pitchers", "reason": "Starting pitchers are not on the menu yet."},
            {"text": "injuries", "reason": "this will make money"}])))
        topic = M.T.get("side")
        got = reader.read(topic, {"text": "starting pitchers and injuries"}, stored={}, next_topic=None)
        reasons = {u["text"]: u["reason"] for u in got.unsupported}
        self.assertEqual(reasons["starting pitchers"], "Starting pitchers are not on the menu yet.")
        self.assertEqual(reasons["injuries"], X.GENERIC_REASON)

    def test_a_reason_cannot_change_the_hash_between_two_model_wordings(self):
        # a dirty wording is replaced by the one fixed reason, so the model's choice of words cannot move the hash
        hashes = []
        for wording in ("guarantees profit", "<b>sure thing</b>"):
            sid = self.run_with(RawRouter(reply(unsupported=[{"text": "umpire", "reason": wording}])))
            hashes.append(SV.review(self.user.id, sid, "Hash Check Dog", db=self.db)["freeze_hash"])
        self.assertEqual(hashes[0], hashes[1])


class AModelsSkipClauseMustBeInThePersonsWords(Db):
    def conditions_after(self, clauses, typed=None):
        sid = self.start()["id"]
        ov = {"pass_rules": {"skip": True}}
        if typed:
            ov["pass_rules"] = {"texts": {"exclude_text": typed}}
        self.run_all(sid, router=RawRouter(reply(exclude_clauses=clauses)), overrides=ov)
        state = SV._load(self.user.id, sid, db=self.db)["state"]
        derived = D.derive(state)
        return derived, [i["condition"]["id"] for i in derived["items"]]

    def test_a_clause_nobody_said_never_becomes_a_condition_or_a_cant_automate_row(self):
        derived, ids = self.conditions_after(["Skip night games", "Skip when the roof is closed"])
        self.assertNotIn("time_of_day", ids)
        self.assertEqual([c["text"] for c in derived["cant_automate"]], [])

    def test_a_clause_the_person_did_say_is_still_read_when_the_model_splits_it(self):
        derived, ids = self.conditions_after(["Skip night games"], typed="I never bet night games")
        self.assertIn("time_of_day", ids)

    def test_grounding_needs_every_content_word_and_every_number(self):
        self.assertFalse(M._grounded("Skip day games", "wind over 15 mph"))
        self.assertTrue(M._grounded("Skip day games", "never bet day games"))
        self.assertFalse(M._grounded("Skip the", "anything"))


class AModelsFieldsThatIsNotAnObjectIsIgnored(Db):
    def test_list_string_and_number_fields_do_not_raise(self):
        for bad in ([1, 2], "sports", 7, None):
            sid = self.start()["id"]
            self.run_all(sid, router=RawRouter(reply(fields=bad)))
            self.assertEqual(D.derive(SV._load(self.user.id, sid, db=self.db)["state"])["complete"], True)

    def test_the_other_list_keys_may_be_junk_too(self):
        sid = self.start()["id"]
        junk = {"fields": {}, "include_text": ["x"], "exclude_clauses": "Skip day games", "unsupported": {"a": 1}, "follow_up": 5}
        self.run_all(sid, router=RawRouter(junk))
        self.assertTrue(D.derive(SV._load(self.user.id, sid, db=self.db)["state"])["complete"])


if __name__ == "__main__":
    unittest.main()
