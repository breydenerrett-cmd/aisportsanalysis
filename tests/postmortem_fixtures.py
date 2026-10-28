"""Shared fixtures for the hindsight-review tests: a fake stats book, a fake Anthropic client with a Message Batches API, a fake clock.

Nothing here touches the network or the repository's data files: every store is a temp file, the clock is injected, the client is a
fake that records every request and answers from a script. Used by tests/test_postmortems*.py, tests/test_bet_export.py.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

from src.ai import postmortem_parse as pm
from src.ai import postmortem_store as store
from src.ai import postmortems
from src.ai.usage import UsageStore
from src.hounds.contract import BetRow, HoundSummary
from src.hounds.stats import HoundData

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
KEY = "sk-ant-api03-TESTKEYTESTKEYTESTKEY0123456789"
ENV = {"ANTHROPIC_API_KEY": KEY}


class Clock:
    def __init__(self, start: datetime = NOW):
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def bet(n: int = 1, *, hound_id: str = "u-1", result: Optional[str] = "loss", segment: str = "forward", units: Optional[float] = None,
        date: str = "2026-10-28", graded_utc: Optional[str] = "2026-10-28T19:30:00Z", sport: str = "mlb", reason: str = "Fires on a rested starter at plus money.",
        price: int = 120, **kw) -> BetRow:
    if units is None and result:
        units = {"loss": -1.0, "push": 0.0, "void": 0.0}.get(result, round(price / 100.0 if price > 0 else 100.0 / abs(price), 4))
    fields = dict(hound_id=hound_id, date=date, game=f"Team A{n} at Team B{n}", market="h2h", selection=f"Team B{n} moneyline", line=None,
                  price=price, price_average=price - 5, result=result, units=units if result else None, clv_pts=0.6, who_decided="rule",
                  reason=reason, segment=segment, start_utc=f"{date}T23:05:00Z", recorded_utc=f"{date}T18:0{n % 10}:00Z",
                  event_id=f"ev{n}", sport=sport, graded_utc=graded_utc if result else None)
    fields.update(kw)
    return BetRow(**fields)


def summary(hound_id: str = "u-1", *, kind: str = "user", category: str = "mixed", name: Optional[str] = None,
            rule_text: str = "Back a rested starter at plus money.") -> HoundSummary:
    return HoundSummary(id=hound_id, name=name or f"Hound {hound_id}", kind=kind, category=category, rule_text=rule_text, sports=["mlb"])


def hound_data(hound_id: str = "u-1", bets: Optional[list] = None, **kw) -> HoundData:
    return HoundData(summary=summary(hound_id, **kw), series=[], bets=list(bets if bets is not None else [bet()]))


def book_of(*datas: HoundData):
    return SimpleNamespace(hounds={d.summary.id: d for d in datas})


def review_json(**over) -> dict:
    out = {"what_happened": "Team B1 lost 5-2 after the starter left in the fourth inning with a blister.",
           "key_factors": ["the starter left early", "the bullpen gave up three"], "factor_tags": ["starter_performance", "bullpen_or_depth"],
           "reason_relevance": "partly_valid", "reason_assessment": "The rested-starter angle was fine, but the starter was hurt in game.",
           "luck_vs_process": "mixed", "info_hound_lacked": ["the starter had a blister reported by the team before the game"],
           "lesson": "A rested starter is only as good as his health report.",
           "analyst_takes": [{"outlet": "Example Sports", "take": "The lineup was thin against lefties.", "url": "https://example.com/recap"}],
           "sources": [{"url": "https://example.com/recap", "title": "Recap", "kind": "recap"},
                       {"url": "https://example.org/injuries", "title": "Injury report", "kind": "injury"}],
           "confidence": "high"}
    out.update(over)
    return out


URLS = {"https://example.com/recap": "Recap", "https://example.org/injuries": "Injury report"}


def message(text: Optional[str] = None, *, review: Optional[dict] = None, urls: Optional[Dict[str, str]] = None, searches: int = 3,
            input_tokens: int = 20000, output_tokens: int = 1500, stop_reason: str = "end_turn", usage: object = "default",
            citations: Optional[list] = None):
    """A response shaped like the SDK's Message: text, web_search_tool_result blocks, usage with server_tool_use."""
    blocks = []
    if urls is None:
        urls = URLS
    if urls:
        blocks.append(SimpleNamespace(type="server_tool_use", name="web_search", input={"query": "x"}))
        blocks.append(SimpleNamespace(type="web_search_tool_result", content=[
            SimpleNamespace(type="web_search_result", url=u, title=t, page_age=None) for u, t in urls.items()]))
    body = text if text is not None else json.dumps(review if review is not None else review_json())
    blocks.append(SimpleNamespace(type="text", text=body, citations=citations))
    if usage == "default":
        usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_creation_input_tokens=0,
                                cache_read_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=searches))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)


class FakeBatches:
    def __init__(self):
        self.created: List[list] = []
        self.status = "ended"
        self.answers: Dict[str, object] = {}                 # custom_id -> result object
        self.fail_create: Optional[Exception] = None
        self.retrieved: List[str] = []

    def create(self, requests):
        if self.fail_create is not None:
            raise self.fail_create
        self.created.append(list(requests))
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}")

    def retrieve(self, batch_id):
        self.retrieved.append(batch_id)
        return SimpleNamespace(processing_status=self.status)

    def results(self, batch_id):
        index = int(batch_id.rsplit("_", 1)[1]) - 1
        out = []
        for req in self.created[index]:
            cid = req["custom_id"]
            result = self.answers.get(cid) or SimpleNamespace(type="succeeded", message=message())
            out.append(SimpleNamespace(custom_id=cid, result=result))
        return out


class FakeClient:
    def __init__(self):
        self.messages = SimpleNamespace(batches=FakeBatches())

    @property
    def batches(self) -> FakeBatches:
        return self.messages.batches


class Rig:
    """An engine over temp files, a fake clock and a fake client. ``rig.engine.tick(book)`` is the whole pipeline."""

    def __init__(self, env: Optional[dict] = None, *, client: Optional[FakeClient] = None, start: datetime = NOW):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.clock = Clock(start)
        self.client = client or FakeClient()
        self.env = dict(ENV if env is None else env)
        self.built: List[str] = []
        self.queue = store.QueueStore(os.path.join(self.dir, "q.jsonl"), clock=self.clock)
        self.ledger = store.ReviewLedger(os.path.join(self.dir, "l.jsonl"), clock=self.clock)
        self.usage = UsageStore(os.path.join(self.dir, "u.jsonl"), clock=self.clock)

        def factory(key, timeout):
            self.built.append(key)
            return self.client

        self.engine = postmortems.Engine(queue=self.queue, ledger=self.ledger, usage=self.usage, env=self.env, clock=self.clock,
                                         client_factory=factory, lock_path=os.path.join(self.dir, "lock"), peek_book=lambda: None)

    def close(self):
        self.tmp.cleanup()

    def submit_all(self, book) -> str:
        """Scan, force a batch out now, return its id."""
        self.engine.tick(book)
        return f"msgbatch_{len(self.client.batches.created)}"
