"""Shared fixtures for the strategy-interview tests: a temp app database, a fake router (no network, ever) and the
standard set of answers. Nothing here reads a live store.

THE FAKE ROUTER answers like src/ai/router.py's Router.ask: it checks the reply against the schema the caller passed
(so a reply the real router would call invalid fails the test), returns an `Answer`, and records every prompt it was
sent, so a test can prove what did and did not leave the building.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.ai import schema as schema_mod
from src.ai.router import Answer
from src.appstate import users as users_store
from src.hounds.interview import service as SV

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)


class FakeRouter:
    """`replies` is a callable (topic_id, user_prompt) -> dict | None. None is "no answer" (capped, cooling down, down)."""

    def __init__(self, replies=None, *, raises: Exception = None):
        self.replies = replies or (lambda topic, user: None)
        self.raises = raises
        self.calls = []

    def ask(self, system, user, *, schema, validator=None, providers=None, purpose="", max_tokens=None):
        self.calls.append({"system": system, "user": user, "purpose": purpose, "max_tokens": max_tokens})
        if self.raises:
            raise self.raises
        topic = re.search(r"TOPIC JUST ASKED: (.+)", user).group(1).strip()
        reply = self.replies(topic, user)
        if reply is None:
            return Answer(provider=None, model=None, latency_ms=1, cost_usd=0.0, output=None, ok=False,
                          reason="no answer (anthropic: skipped - monthly paid cap of $5.00 reached)")
        problems = schema_mod.validate(reply, schema)
        assert not problems, f"the fake reply would be invalid for the real router: {problems}"
        return Answer(provider="anthropic", model="claude-haiku-5-5", latency_ms=5, cost_usd=0.0004, output=reply, ok=True)


def reading(fields=None, include_text="", exclude=None, unsupported=None, follow_up="What prices will it take, and how many books must quote it?"):
    return {"fields": fields or {}, "include_text": include_text, "exclude_clauses": exclude or [],
            "unsupported": unsupported or [], "follow_up": follow_up}


class Db(unittest.TestCase):
    """A temp app database, one paid account and one free account."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)
        self.user = users_store.create_user("paid@example.com", status="active", db=self.db)
        self.free = users_store.create_user("free@example.com", status="active", plan="free", db=self.db)

    # -- driving an interview -----------------------------------------------------------------------
    def start(self, user=None, *, free=False):
        user = user or self.user
        return SV.start(user.id, free=free, now=NOW, db=self.db)

    def answer(self, sid, topic, user=None, router=None, **payload):
        user = user or self.user
        return SV.answer(user.id, sid, topic, payload, router=router, now=NOW, db=self.db)

    def run_all(self, sid, user=None, router=None, overrides=None):
        """Answer every topic with STANDARD (a topic's payload may be replaced by `overrides`); returns the last view."""
        out = None
        for topic, payload in standard_answers(overrides):
            out = self.answer(sid, topic, user=user, router=router, **payload)
        return out


STANDARD_TEXT = ("Bet home underdogs between +120 and +200 when the team has at least 2 days of rest. "
                 "Skip when the wind is over 15 mph.")


def standard_answers(overrides=None):
    """A complete, consistent interview: MLB moneyline home underdogs, +120 to +200, rested, skips high wind."""
    base = {
        "scope": {"fields": {"sports": ["MLB"], "markets": ["moneyline"], "timing": "pregame"}},
        "side": {"fields": {"side": "home"}, "texts": {"text": STANDARD_TEXT}},
        "price": {"fields": {"min_books": 3, "line_timing": "lock"}},
        "data": {"data": ["weather", "rest"]},
        "examples": {"texts": {"trigger_text": "Mariners at home against the Red Sox", "skip_text": "Any game in a dome"}},
        "pass_rules": {"skip": True},
        "limits": {"fields": {"max_bets_per_day": 2, "lock_minutes": 120}},
        "stake": {"fields": {"stake_units": 1.0}},
        "history": {"skip": True},
        "disprove": {"texts": {"text": "If it loses 30 of its first 50 bets."}},
        "publish": {"fields": {"publish_ok": False, "attribution": "anonymous"}},
    }
    base.update(overrides or {})
    return list(base.items())
