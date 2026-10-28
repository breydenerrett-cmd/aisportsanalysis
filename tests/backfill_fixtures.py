"""Fixtures for the backfill and Deep review tests: an engine with a switchable backfill config, member lineages, and fake lineage answers.

Nothing here touches the network or the repository's data files: every store is a temp file, the clock is injected, the client is the
fake of tests/postmortem_fixtures.py. Used by tests/test_postmortem_backfill.py, tests/test_deep_review.py, tests/test_hindsight_feed.py.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace
from typing import List, Optional

from src.ai import deep_review as dr
from src.ai import postmortem_cost as cost
from src.ai import postmortem_parse as pm
from src.ai import postmortem_store as store
from src.ai import postmortems
from src.ai.usage import UsageStore
from src.hounds import version_chain
from tests.postmortem_fixtures import ENV, NOW, Clock, FakeClient, bet, hound_data, message


def old_bet(n: int, hound_id: str = "u-1", *, day: int = 10, result: Optional[str] = "loss", **kw):
    """A settled forward bet graded on 2026-10-<day>, well before the first scan's start line (so it is history, not backlog)."""
    return bet(n, hound_id=hound_id, result=result, date=f"2026-10-{day:02d}", graded_utc=f"2026-10-{day:02d}T23:30:00Z", **kw)


def user_row(hound_id: str, root: str, version_no: int, *, status: str = "running", name: str = "Dee", reason: str = "") -> dict:
    return {"id": hound_id, "root_id": root, "version_no": version_no, "status": status, "name": name, "created_at": f"2026-10-0{version_no}T00:00:00Z",
            "retire_reason": reason, "owner_user_id": 7}


def lineage_text(stats: dict, **over) -> str:
    """A well-formed lineage answer that uses only numbers the stats hold."""
    rec = stats["record"]
    body = {"headline": f"It has {rec['wins']} wins and {rec['losses']} losses over {stats['settled']} settled bets.",
            "working": ["Underdog picks held up better than favourites."],
            "failing": ["Spread bets lost more units than any other market."],
            "changes": ["Try dropping the spread rule first and watch the next group of bets."],
            "sample_note": f"This rests on {stats['settled']} settled bets, so treat it as a rough look."}
    body.update(over)
    return json.dumps(body)


def lineage_message(text: str, *, input_tokens: int = 4000, output_tokens: int = 2500, stop_reason: str = "end_turn", usage: object = "default"):
    """A response shaped like the SDK's Message for a lineage request: one text block, usage without any web search."""
    if usage == "default":
        usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                server_tool_use=None)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text, citations=None)], stop_reason=stop_reason, usage=usage)


class BackfillRig:
    """An engine over temp files with a fake clock, a fake client, a switchable backfill config and member-hound version rows.

    ``lineages`` False (the default) leaves the lineage Deep reviews out, so a test of the past-bet backfill counts only past bets."""

    def __init__(self, *, on: bool = True, cap: float = 25.0, user_rows: Optional[List[dict]] = None, env: Optional[dict] = None,
                 start=NOW, month_cap: Optional[float] = None, lineages: bool = False):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.clock = Clock(start)
        self.client = FakeClient()
        self.env = dict(ENV if env is None else env)
        if month_cap is not None:
            self.env[postmortems.ENV_CAP] = str(month_cap)
        self.cfg = {"on": on, "cap_usd": cap}
        self.user_rows: List[dict] = list(user_rows or [])
        self.queue = store.QueueStore(os.path.join(self.dir, "q.jsonl"), clock=self.clock)
        self.ledger = store.ReviewLedger(os.path.join(self.dir, "l.jsonl"), clock=self.clock)
        self.deep = store.DeepReviewLedger(os.path.join(self.dir, "d.jsonl"), clock=self.clock)
        self.usage = UsageStore(os.path.join(self.dir, "u.jsonl"), clock=self.clock)
        self.engine = postmortems.Engine(
            queue=self.queue, ledger=self.ledger, usage=self.usage, env=self.env, clock=self.clock,
            client_factory=lambda key, timeout: self.client, lock_path=os.path.join(self.dir, "lock"), peek_book=lambda: None,
            deep_ledger=self.deep, backfill_config=lambda: self.cfg,
            chains_loader=(lambda book: version_chain.build_chains(book.hounds, self.user_rows)) if lineages else (lambda book: {}))

    def close(self):
        self.tmp.cleanup()

    def tick(self, book, minutes: int = 0) -> dict:
        if minutes:
            self.clock.advance(minutes=minutes)
        return self.engine.tick(book)

    def queue_text(self) -> str:
        try:
            with open(self.queue.path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def backfill_items(self, depth: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
        out = [i for i in self.queue._items.values() if i["origin"] == store.ORIGIN_BACKFILL]          # noqa: SLF001 -- a test reads the log's state
        return [i for i in out if (depth is None or i["depth"] == depth) and (status is None or i["status"] == status)]

    def worst_of(self, key: str, depth: str = "fast") -> float:
        item = self.queue.get(key, depth)
        params, chars = pm.request_params(item["bet"], depth)
        model, max_tokens, uses, _effort = pm.DEPTH_PLAN[depth]
        return cost.worst_case_cost(model, chars, max_tokens, uses, batch=True)

    def answer_lineages(self, batch_no: int = -1) -> None:
        """Script a well-formed answer for every lineage request in a batch (the fake answers the rest with a hindsight review)."""
        for req in self.client.batches.created[batch_no]:
            key_depth = pm.split_custom_id(req["custom_id"])
            if key_depth and key_depth[1] == pm.DEPTH_LINEAGE:
                stats = self.queue.get(*key_depth)["bet"]["stats"]
                self.client.batches.answers[req["custom_id"]] = SimpleNamespace(type="succeeded", message=lineage_message(lineage_text(stats)))


def many_old_bets(hound_id: str, n: int, *, first_n: int = 1, day: int = 10, result_cycle=("loss", "win", "loss")) -> list:
    return [old_bet(first_n + i, hound_id, day=day, result=result_cycle[i % len(result_cycle)]) for i in range(n)]


def stored_review(*, lesson: str = "A rested starter is only as good as his health report.", urls=None, **over) -> dict:
    """A review as the ledger stores it: the shared fixture's answer put through the real parser (so it has every key a digest reads)."""
    from tests.postmortem_fixtures import review_json
    evidence = pm.analyze_message(message(review=review_json(lesson=lesson, **over), urls=urls))
    review, problems = pm.parse_review(evidence["text"], evidence)
    assert review is not None, problems
    return review


def add_review(ledger, hound_id: str, n: int, *, result: str = "loss", date: str = "2026-10-20", lesson: str = "A rested starter is only as good as his health report.",
               depth: str = "fast", grounded: bool = True, tags=None) -> str:
    """Put one stored hindsight review for one bet of ``hound_id`` in the ledger. Returns the bet key."""
    row = old_bet(n, hound_id, result=result, day=int(date[-2:]))
    data = hound_data(hound_id, [row])
    key = store.bet_key(hound_id, row)
    extra = {"factor_tags": tags} if tags else {}
    review = stored_review(lesson=lesson, urls=None if grounded else {}, **extra)
    ledger.append(bet=postmortems.snapshot(data.summary, row, key), depth=depth, model="claude-haiku-5-5", review=review, cost_usd=0.03,
                  web_searches=3, batch_id="b")
    return key


def add_deep(deep_ledger, lineage_key: str, *, settled: int = 12, headline: str = "It lost more than it won across both versions.",
             key: str = "", hound_ids=("u-1", "u-2")) -> str:
    """Append one Deep review row for a lineage with counted stats beside the words."""
    stats = dr.compute_stats("Dee", [{"label": f"v{i + 1}", "status": "running", "hound_id": h, "rule_text": "Back a rested starter.",
                                     "bets": many_old_bets(h, settled // len(hound_ids), first_n=1 + 100 * i)} for i, h in enumerate(hound_ids)])
    review = {"headline": headline, "working": ["Underdog picks held up better than favourites."], "failing": ["Spread bets lost the most units."],
              "changes": ["Try dropping the spread rule first."], "sample_note": "A small sample, so a rough look."}
    review_key = key or dr.review_key(lineage_key, deep_ledger.last_settled(lineage_key), settled)
    deep_ledger.append(lineage_key=lineage_key, review_key=review_key, hound_ids=list(hound_ids), settled=settled, stats=stats, review=review,
                       model=dr.MODEL, cost_usd=0.0165, batch_id="b")
    return review_key
