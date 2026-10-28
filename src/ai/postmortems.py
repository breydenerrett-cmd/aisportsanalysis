"""HINDSIGHT REVIEWS: after a paper bet settles, Claude with web search says what happened and why (owner ask 2026-10-28).

    "export all matchups and analysis and betting reasons whenever a hound takes a bet ... a process using the Claude API (Sonnet or
    Haiku agents) to fully analyze each matchup and data and history and why it went the way it went, searching for news on each
    matchup, other analysts' takes on why and what happened. More info is of the utmost importance."

THE FLOW (one ``Engine.tick`` per live-settle pass, wired in ``api/app.py`` through ``live_settle.start_loop(after_pass=...)``)
  1. SCAN. Every settled FORWARD bet (a win or a loss) in the cached stats book whose grade came on or after the first scan's start
     line is put in the queue once (``postmortem_store.QueueStore``). A replay bet is never queued: it is hindsight already and is
     never counted. Bets graded before the feature existed are history, not backlog (``POSTMORTEM_SINCE`` moves the line back).
     Priority is member hounds, then house hounds, then The Learner, of which only 1 bet in ``LEARNER_SAMPLE_ONE_IN`` is reviewed
     (a deterministic draw on the bet key, so a re-scan cannot flip it).
  2. SUBMIT. Reviews are not urgent, so they go through the Message Batches API at half the token price: at most one batch per
     ``SUBMIT_MIN_INTERVAL`` unless a full batch is waiting. Each request is a Haiku 5.5 FAST review with web search (a recap,
     pre-game injuries and news, other analysts). No API key means the queue simply waits; the export keeps working.
  3. COLLECT. A finished batch is read back; each answer goes through ``postmortem_parse.parse_review`` (strict schema, sources
     only if a search really returned the URL) and into the append-only ledger. A LOSS, or a win of ``BIG_WIN_UNITS`` or more, then
     queues a DEEP review: Sonnet 5.5 with more searches that checks the fast review against the sources.
  4. FEED. ``summary_for(hound_id, limit)`` hands the coaching prompts and the hound chat compact lessons and per-factor tallies.

THE BUDGET IS A WALL (``POSTMORTEM_MONTHLY_USD``, default $20, env override). Spend is the API's own ``usage`` at real prices plus
$0.01 per web search (``postmortem_cost``), appended to the shared usage meter (``usage.UsageStore``, provider
``anthropic_postmortem``, so it neither counts against nor is hidden inside the hound runner's separate ``AI_PAID_CAP_USD``).
BEFORE a batch goes out, every request's WORST case (prompt, every search's results, every output token) is added to what the month
has spent plus what open batches have reserved, and the batch holds only the requests that fit, in priority order; the first that
does not fit stops the line (strict priority). A batch that is submitted reserves its worst case until its results are read.

LABELLED HINDSIGHT, EVERYWHERE (``postmortem_parse.LABEL``). A review is written after the result, from the web. It is never shown as
pre-game reasoning and nothing in it is a prediction or a tip. Paper only; nothing here can place a bet.

NO SECRETS IN LOGS. The key is read by name, handed to the SDK and nowhere else; a log line carries an exception's class name, never
its message (an SDK message can echo a header). Prompts go through ``router.check_prompt`` (no email, phone, id, key) first.

TWO WRITERS NEVER RUN: a lock file beside the queue (with an expiry, so a crashed holder frees itself) keeps two passes, or two
machines on one volume, from submitting the same bets twice.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.ai import postmortem_cost as cost_mod
from src.ai import postmortem_parse as pm
from src.ai import postmortem_store as store
from src.ai.usage import UsageStore

logger = logging.getLogger("linehound.ai.postmortems")

POSTMORTEM_MONTHLY_USD = 20.0
ENV_CAP = "POSTMORTEM_MONTHLY_USD"
ENV_FLAG = "POSTMORTEMS"                 # =off stops the tick (the queue and the export stay as they are)
ENV_SINCE = "POSTMORTEM_SINCE"           # YYYY-MM-DD: queue bets graded on or after this day
ENV_KEY = "ANTHROPIC_API_KEY"
PROVIDER = "anthropic_postmortem"        # the usage meter's label: kept apart from the hound runner's "anthropic"
OFF_VALUES = ("off", "0", "false", "no")

LEARNER_SAMPLE_ONE_IN = 5                # The Learner places ~50 paper bets a day; one in five is reviewed
BIG_WIN_UNITS = 2.0                      # a win of at least this many paper units earns the deep pass, like every loss
MAX_ATTEMPTS = 2                         # a request that fails in a way worth retrying is tried this many times in all
BATCH_MAX_REQUESTS = 20
SUBMIT_MIN_INTERVAL = timedelta(minutes=20)
BATCH_EXPIRES_AFTER = timedelta(hours=26)   # batches end within 24 hours; past this one never read is given up on
SINCE_GRACE = timedelta(hours=24)        # the first scan also queues what was graded in the day before it
LOCK_TTL = timedelta(minutes=10)
LOCK_FILE = "postmortem_lock"
CLIENT_TIMEOUT_S = 60.0
COOLDOWN_ERROR = timedelta(minutes=30)
COOLDOWN_AUTH = timedelta(hours=6)
RULE_TEXT_CHARS = 600
REASON_CHARS = 600
SUMMARY_LIMIT_DEFAULT = 12
SUMMARY_LIMIT_MAX = 50
SETTLED_FOR_REVIEW = ("win", "loss")

_PEEK = object()                         # "use the process-wide cached stats book" (None means "no book yet")
STATUS: Dict[str, Any] = {"last_tick_utc": None, "last_report": None, "last_error": None, "ticks": 0}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def monthly_cap(env: Optional[Mapping] = None) -> float:
    """``POSTMORTEM_MONTHLY_USD``, default 20. A value that is not a finite number is the default; a negative one means 0 (off)."""
    raw = str((env if env is not None else os.environ).get(ENV_CAP) or "").strip()
    if not raw:
        return POSTMORTEM_MONTHLY_USD
    try:
        value = float(raw)
    except ValueError:
        return POSTMORTEM_MONTHLY_USD
    return max(0.0, value) if math.isfinite(value) else POSTMORTEM_MONTHLY_USD


def api_key(env: Optional[Mapping] = None) -> Optional[str]:
    """The key by NAME, or None. Never logged, never returned to a page."""
    return str((env if env is not None else os.environ).get(ENV_KEY) or "").strip() or None


def enabled(env: Optional[Mapping] = None) -> bool:
    return str((env if env is not None else os.environ).get(ENV_FLAG) or "").strip().lower() not in OFF_VALUES


def tier_of(summary: Any) -> Optional[str]:
    """member | house | learner, or None for a hound that is never reviewed (the baseline controls)."""
    kind, category = getattr(summary, "kind", None), getattr(summary, "category", None)
    if kind == "user":
        return store.TIER_MEMBER
    if category == "learner":
        return store.TIER_LEARNER
    if kind == "house":
        return store.TIER_HOUSE
    return None


def wants_deep(bet: Mapping) -> bool:
    units = bet.get("units")
    return bet.get("result") == "loss" or (bet.get("result") == "win" and isinstance(units, (int, float))
                                           and not isinstance(units, bool) and units >= BIG_WIN_UNITS)


def _clip(value: Any, n: int) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "..."


def snapshot(summary: Any, row: Any, key: str) -> dict:
    """The facts of one settled bet the prompt and the ledger carry. JSON primitives only."""
    return {"bet_key": key, "hound_id": summary.id, "hound_name": summary.name, "hound_kind": summary.kind,
            "rule_text": _clip(summary.rule_text, RULE_TEXT_CHARS), "date": row.date, "start_utc": row.start_utc,
            "sport": row.sport, "game": row.game, "market": row.market, "selection": row.selection, "line": row.line,
            "price": row.price, "price_average": row.price_average, "clv_pts": row.clv_pts, "result": row.result,
            "units": row.units, "reason": _clip(row.reason, REASON_CHARS), "graded_utc": row.graded_utc}


def _graded_since(row: Any, since_iso: str) -> bool:
    graded = store.parse_iso(getattr(row, "graded_utc", None))
    if graded is not None:
        since = store.parse_iso(since_iso)
        return since is None or graded >= since
    return str(getattr(row, "date", "") or "")[:10] >= since_iso[:10]


def public_review(row: Mapping) -> dict:
    """A ledger row as a page may show it: the review, its depth, model and time, the label. No cost, no batch id."""
    return {"bet_key": row.get("bet_key"), "depth": row.get("depth"), "model": row.get("model"),
            "created_utc": row.get("created_utc"), "label": pm.LABEL, **dict(row.get("review") or {})}


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------

class Engine:
    """Everything is injected, so a test runs it against temp files, a fake clock and a fake client and never the network."""

    def __init__(self, *, queue: store.QueueStore, ledger: store.ReviewLedger, usage: UsageStore,
                 env: Optional[Mapping] = None, clock: Optional[Callable[[], datetime]] = None,
                 client_factory: Optional[Callable[[str, float], Any]] = None,
                 lock_path: Optional[os.PathLike] = None, peek_book: Optional[Callable[[], Any]] = None):
        self.queue, self.ledger, self.usage = queue, ledger, usage
        self.env = env if env is not None else os.environ
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._client_factory = client_factory
        self.lock_path = Path(lock_path) if lock_path is not None else queue.path.with_name(LOCK_FILE)
        self._peek_book = peek_book
        self._thread_lock = threading.Lock()
        self._scanned = None

    def now(self) -> datetime:
        return self._clock()

    # -- budget ---------------------------------------------------------------

    def cap(self) -> float:
        return monthly_cap(self.env)

    def committed(self) -> float:
        """What the month has spent plus what open batches may still cost."""
        return round(self.usage.month_spend(PROVIDER) + self.usage.reserved(PROVIDER), 8)

    def status(self) -> dict:
        return {"enabled": enabled(self.env), "key_present": api_key(self.env) is not None, "cap_usd": self.cap(),
                "spent_usd": self.usage.month_spend(PROVIDER), "reserved_usd": self.usage.reserved(PROVIDER),
                "queue": self.queue.counts(), "reviews": self.ledger.count()}

    # -- scan ----------------------------------------------------------------------

    def _since(self) -> str:
        override = str(self.env.get(ENV_SINCE) or "").strip()
        if override:
            try:
                return datetime.fromisoformat(override[:10]).strftime("%Y-%m-%dT00:00:00Z")
            except ValueError:
                logger.warning("%s is not a date; ignoring it", ENV_SINCE)
        self.queue.set_epoch(store.iso(self.now() - SINCE_GRACE))
        return self.queue.since() or store.iso(self.now() - SINCE_GRACE)

    def scan(self, book: Any) -> dict:
        """Queue every settled forward bet in ``book`` that has not been queued or skipped. Idempotent."""
        since = self._since()
        known = self.queue.known_snapshot()
        report = {"seen": 0, "queued": 0, "skipped": 0}
        for hound_id, data in book.hounds.items():
            summary = data.summary
            tier = tier_of(summary)
            if tier is None:
                continue
            for row in data.bets:
                if row.segment != "forward" or row.result not in SETTLED_FOR_REVIEW or not _graded_since(row, since):
                    continue
                key = store.bet_key(summary.id, row)
                report["seen"] += 1
                if key in known:
                    continue
                known.add(key)
                if tier == store.TIER_LEARNER and not pm.sample_hit(key, LEARNER_SAMPLE_ONE_IN):
                    self.queue.skip(key, "learner_sample")
                    report["skipped"] += 1
                    continue
                if self.queue.enqueue(snapshot(summary, row, key), tier):
                    report["queued"] += 1
        return report

    # -- the SDK client -----------------------------------------------------------------

    def _client(self, key: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(key, CLIENT_TIMEOUT_S)
        from src.ai import sdk_client
        return sdk_client.build_client(key, CLIENT_TIMEOUT_S)

    def _secrets(self) -> List[str]:
        """Every configured secret value, the Anthropic key included: a prompt that carries one is refused, never sent."""
        from src.ai import router
        out = router.secret_values(self.env)
        key = api_key(self.env)
        if key and key not in out:
            out.append(key)
        return out

    def _cooldown(self, error: Exception) -> None:
        status = getattr(error, "status_code", None)
        auth = status in (401, 403)
        until = self.now() + (COOLDOWN_AUTH if auth else COOLDOWN_ERROR)
        self.usage.record_cooldown(PROVIDER, until, f"{type(error).__name__}" + (f" HTTP {status}" if status else ""))

    # -- submit -------------------------------------------------------------------------

    def submit(self, client: Any) -> dict:
        now = self.now()
        cooling = self.usage.cooldown(PROVIDER)
        if cooling is not None:
            return {"submitted": 0, "reason": "cooling_down"}
        pending = self.queue.pending()
        if not pending:
            return {"submitted": 0, "reason": "queue_empty"}
        last = self.queue.last_submit()
        if last is not None and now - last < SUBMIT_MIN_INTERVAL and len(pending) < BATCH_MAX_REQUESTS:
            return {"submitted": 0, "reason": "batching", "pending": len(pending)}
        cap, committed = self.cap(), self.committed()
        requests: List[dict] = []
        chosen: List[tuple] = []
        reserve = 0.0
        stopped = None
        secrets = self._secrets()
        for item in pending:
            if len(requests) >= BATCH_MAX_REQUESTS:
                break
            depth = item["depth"]
            prior = None
            if depth == pm.DEPTH_DEEP:
                prior = ((self.ledger.get(item["bet_key"]).get("fast") or {}).get("review"))
            params, chars = pm.request_params(item["bet"], depth, prior)
            refused = _guard(params, secrets)
            if refused:
                self.queue.failed(item["bet_key"], depth, f"prompt_guard: {refused}", retry=False)
                continue
            model, max_tokens, uses, _effort = pm.DEPTH_PLAN[depth]
            worst = cost_mod.worst_case_cost(model, chars, max_tokens, uses, batch=True)
            if committed + reserve + worst > cap:
                stopped = "monthly_cap"
                break                                   # strict priority: nothing behind a request that does not fit goes first
            requests.append({"custom_id": pm.custom_id(item["bet_key"], depth), "params": params})
            chosen.append((item["bet_key"], depth))
            reserve += worst
        if not requests:
            return {"submitted": 0, "reason": stopped or "nothing_eligible", "cap_usd": cap, "committed_usd": committed}
        try:
            batch = client.messages.batches.create(requests=requests)
        except Exception as exc:  # noqa: BLE001 -- classified by name only; the message could echo a header
            self._cooldown(exc)
            logger.error("postmortem batch could not be submitted: %s", type(exc).__name__)
            return {"submitted": 0, "reason": "submit_failed", "error": type(exc).__name__}
        batch_id = str(batch.id)
        self.usage.record_batch_submit(batch_id=batch_id, provider=PROVIDER, model="mixed", reserved_usd=reserve,
                                       n_requests=len(requests), purpose="postmortem")
        self.queue.submitted(batch_id, chosen)
        return {"submitted": len(requests), "batch_id": batch_id, "reserved_usd": round(reserve, 6)}

    # -- collect --------------------------------------------------------------------------

    def collect(self, client: Any) -> dict:
        report = {"batches_read": 0, "reviews": 0, "failed": 0}
        for batch_id, info in self.queue.open_batches().items():
            try:
                batch = client.messages.batches.retrieve(batch_id)
                status = str(getattr(batch, "processing_status", ""))
            except Exception as exc:  # noqa: BLE001
                logger.error("postmortem batch status could not be read: %s", type(exc).__name__)
                continue
            if status == "ended":
                got = self._read_results(client, batch_id, info)
                report["batches_read"] += 1
                report["reviews"] += got["reviews"]
                report["failed"] += got["failed"]
                continue
            submitted = store.parse_iso(info.get("submitted"))
            if submitted is not None and self.now() - submitted > BATCH_EXPIRES_AFTER:
                for key, depth in info["items"]:
                    self._fail(key, depth, "batch_never_ended", retry=True)
                self.usage.record_batch_done(batch_id=batch_id, provider=PROVIDER, status="expired", actual_usd=0.0)
                self.queue.batch_closed(batch_id)
                report["failed"] += len(info["items"])
        return report

    def _fail(self, key: str, depth: str, reason: str, *, retry: bool) -> None:
        item = self.queue.get(key, depth)
        retry = retry and item is not None and item["attempts"] + 1 < MAX_ATTEMPTS
        self.queue.failed(key, depth, reason, retry=retry)

    def _read_results(self, client: Any, batch_id: str, info: dict) -> dict:
        out = {"reviews": 0, "failed": 0}
        total = 0.0
        seen = set()
        try:
            entries = list(client.messages.batches.results(batch_id))
        except Exception as exc:  # noqa: BLE001
            logger.error("postmortem batch results could not be read: %s", type(exc).__name__)
            return out                                   # the batch stays open: its reservation stays, the next tick tries again
        for entry in entries:
            ident = pm.split_custom_id(getattr(entry, "custom_id", ""))
            if ident is None:
                continue
            key, depth = ident
            item = self.queue.get(key, depth)
            if item is None or item["status"] != "submitted" or item["batch_id"] != batch_id:
                continue                                 # a result the queue no longer waits on: never applied twice
            seen.add(ident)
            spent = self._apply_result(entry, item, batch_id)
            total += spent[0]
            out["reviews" if spent[1] else "failed"] += 1
        for key, depth in info["items"]:
            if (key, depth) not in seen:
                item = self.queue.get(key, depth)
                if item is not None and item["status"] == "submitted" and item["batch_id"] == batch_id:
                    self._fail(key, depth, "no_result_in_batch", retry=True)
                    out["failed"] += 1
        self.usage.record_batch_done(batch_id=batch_id, provider=PROVIDER, status="ended", actual_usd=total)
        self.queue.batch_closed(batch_id)
        return out

    def _apply_result(self, entry: Any, item: dict, batch_id: str) -> tuple:
        """``(dollars, ok)`` for one batch entry. The money is recorded BEFORE the review is stored, so a crash in between can
        only double-count a replay (the cap errs toward spending less), never lose a charge."""
        key, depth = item["bet_key"], item["depth"]
        model, max_tokens, uses, _effort = pm.DEPTH_PLAN[depth]
        outcome = getattr(entry, "result", None)
        kind = str(getattr(outcome, "type", "errored"))
        purpose = f"postmortem:{depth}"
        if kind != "succeeded":
            etype = str(getattr(getattr(outcome, "error", None), "type", "") or kind)
            self.usage.record_call(provider=PROVIDER, model=model, status="error", cost_usd=0.0, error=etype, purpose=purpose)
            self._fail(key, depth, f"batch_{kind}:{etype}", retry=(etype != "invalid_request"))
            return 0.0, False
        evidence = pm.analyze_message(outcome.message)
        spent = cost_mod.usage_cost(model, evidence["usage"], batch=True)
        searches = cost_mod.web_searches_in(evidence["usage"])
        if spent is None:                                # no usage at all: charge the worst case, never zero
            params, chars = pm.request_params(item["bet"], depth)
            spent = cost_mod.worst_case_cost(model, chars, max_tokens, uses, batch=True)
        stop = evidence["stop_reason"]
        if stop == "refusal":
            self.usage.record_call(provider=PROVIDER, model=model, status="refused", cost_usd=spent, purpose=purpose)
            self._fail(key, depth, "refusal", retry=False)
            return spent, False
        review, problems = (None, ["pause_turn"]) if stop == "pause_turn" else pm.parse_review(evidence["text"], evidence, depth)
        if review is None:
            self.usage.record_call(provider=PROVIDER, model=model, status="invalid", cost_usd=spent,
                                   error="; ".join(problems)[:200], purpose=purpose)
            self._fail(key, depth, "invalid: " + "; ".join(problems)[:150], retry=True)
            return spent, False
        self.usage.record_call(provider=PROVIDER, model=model, status="ok", cost_usd=spent, purpose=purpose)
        bet = item["bet"]
        self.ledger.append(bet=bet, depth=depth, model=model, review=review, cost_usd=spent, web_searches=searches,
                           batch_id=batch_id)
        self.queue.done(key, depth)
        if depth == pm.DEPTH_FAST and wants_deep(bet):
            self.queue.enqueue(bet, item["tier"], pm.DEPTH_DEEP)
        return spent, True

    # -- one tick ----------------------------------------------------------------------------

    def _acquire(self) -> bool:
        now = self.now()
        for _attempt in range(2):
            try:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    until = store.parse_iso(self.lock_path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    until = None
                if until is not None and until > now:
                    return False
                try:
                    self.lock_path.unlink()
                except OSError:
                    return False
                continue
            with os.fdopen(fd, "w", encoding="ascii") as fh:
                fh.write(store.iso(now + LOCK_TTL))
            return True
        return False

    def _release(self) -> None:
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    def tick(self, book: Any = _PEEK) -> dict:
        """Scan, collect, submit. Never raises for a missing key, a missing book or a cap: each is a named reason in the report."""
        if not enabled(self.env):
            return {"disabled": True}
        if not self._thread_lock.acquire(blocking=False):
            return {"skipped": "another tick holds the lock"}
        try:
            if not self._acquire():
                return {"skipped": "another tick holds the lock"}
            try:
                report: Dict[str, Any] = {"at": store.iso(self.now())}
                if book is _PEEK:
                    book = self._peek_book() if self._peek_book is not None else _peek_default_book()
                if book is not None and book is not self._scanned:
                    report["scan"] = self.scan(book)
                    self._scanned = book
                key = api_key(self.env)
                if key is None:
                    report["waiting"] = "no_api_key"
                    return report
                try:
                    client = self._client(key)
                except ImportError:
                    report["waiting"] = "sdk_not_installed"
                    return report
                report["collect"] = self.collect(client)
                report["submit"] = self.submit(client)
                return report
            finally:
                self._release()
        finally:
            self._thread_lock.release()

    # -- reading for pages and prompts ------------------------------------------------------------

    def review_for(self, key: str) -> Optional[dict]:
        """The best review of one bet (the deep one when there is one), as a page may show it, or None."""
        rows = self.ledger.get(key)
        row = rows.get(pm.DEPTH_DEEP) or rows.get(pm.DEPTH_FAST)
        return public_review(row) if row else None

    def reviews_for_hound(self, hound_id: str, limit: int = 250) -> Dict[str, dict]:
        """{bet key: best review} for the newest reviewed bets of one hound."""
        out: Dict[str, dict] = {}
        for row in self.ledger.rows_for(hound_id, limit * 2):
            key = row.get("bet_key")
            have = out.get(key)
            if have is None or (row.get("depth") == pm.DEPTH_DEEP and have.get("depth") != pm.DEPTH_DEEP):
                out[key] = public_review(row)
            if len(out) >= limit:
                break
        return out

    def summary_for(self, hound_id: str, limit: int = SUMMARY_LIMIT_DEFAULT) -> dict:
        """Compact lessons and per-factor tallies for one hound, for the rebuild, fine-tune and chat prompts to consume.

        Always the same shape (zeros and empty lists for a hound with no reviews), so a consumer never branches on presence.
        Only GROUNDED reviews (at least one source a search really returned) feed ``lessons``, ``factors``, ``luck_vs_process``,
        ``reason_relevance`` and ``info_gaps``: an unsourced review is counted in ``reviews`` and nowhere else. One review per bet
        (the deep one when both exist). Every item is a fact about the past, labelled hindsight."""
        limit = max(1, min(int(limit), SUMMARY_LIMIT_MAX))
        digests = self.ledger.digests_for(hound_id)
        best: Dict[str, dict] = {}
        for d in digests:                                  # newest first: keep the deep row if there is one, else the newest
            have = best.get(d["bet_key"])
            if have is None or (d["depth"] == pm.DEPTH_DEEP and have["depth"] != pm.DEPTH_DEEP):
                best[d["bet_key"]] = d
        ordered = sorted(best.values(), key=lambda d: (d.get("created_utc") or "", d["bet_key"]), reverse=True)
        grounded = [d for d in ordered if d["grounded"]]
        factors: Dict[str, dict] = {}
        luck: Dict[str, int] = {}
        relevance: Dict[str, int] = {}
        for d in grounded:
            for tag in d["tags"]:
                cell = factors.setdefault(tag, {"n": 0, "wins": 0, "losses": 0})
                cell["n"] += 1
                if d["result"] in ("win", "loss"):
                    cell["wins" if d["result"] == "win" else "losses"] += 1
            if d["luck"]:
                luck[d["luck"]] = luck.get(d["luck"], 0) + 1
            if d["relevance"]:
                relevance[d["relevance"]] = relevance.get(d["relevance"], 0) + 1
        lessons, seen_text, gaps = [], set(), []
        for d in grounded:
            text = str(d.get("lesson") or "").strip()
            if text and text not in seen_text and len(lessons) < limit:
                seen_text.add(text)
                lessons.append({"bet_key": d["bet_key"], "date": d["date"], "game": d["game"], "selection": d["selection"],
                                "result": d["result"], "lesson": text, "luck_vs_process": d["luck"],
                                "reason_relevance": d["relevance"], "depth": d["depth"], "sources": d["sources"]})
            for gap in d["lacked"]:
                if gap not in gaps and len(gaps) < limit:
                    gaps.append(gap)
        return {"hound_id": hound_id, "label": pm.LABEL, "note": pm.NOTE, "as_of": store.iso(self.now()),
                "reviews": len(ordered), "grounded": len(grounded), "pending": len(self.queue.pending_keys(hound_id)),
                "lessons": lessons,
                "factors": dict(sorted(factors.items(), key=lambda kv: (-kv[1]["n"], kv[0]))),
                "luck_vs_process": dict(sorted(luck.items(), key=lambda kv: (-kv[1], kv[0]))),
                "reason_relevance": dict(sorted(relevance.items(), key=lambda kv: (-kv[1], kv[0]))),
                "info_gaps": gaps, "paper_only": True}


def _guard(params: Mapping, secrets: List[str]) -> Optional[str]:
    """A label of anything in a request's text that must not leave the building (``router.check_prompt``), else None."""
    from src.ai import router
    text = str(params.get("system") or "") + "\n" + "\n".join(
        str(m.get("content") or "") for m in params.get("messages") or ())
    found = router.check_prompt(text, secrets)
    return ", ".join(found) if found else None


def _peek_default_book() -> Any:
    from src.hounds import stats
    return stats.peek_book()


# ---------------------------------------------------------------------------
# the process-wide engine and the module-level doors
# ---------------------------------------------------------------------------

_ENGINE: Optional[Engine] = None
_ENGINE_LOCK = threading.Lock()


def default_engine() -> Engine:
    """The one engine of this process: files beside the app database, the real clock, the real SDK."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from src.ai.router import default_usage_path
            queue_path, ledger_path = store.default_paths()
            _ENGINE = Engine(queue=store.QueueStore(queue_path), ledger=store.ReviewLedger(ledger_path),
                             usage=UsageStore(default_usage_path()))
        return _ENGINE


def reset_default_engine() -> None:
    """For tests: forget the process-wide engine so the next call builds one against the current environment."""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def tick_safely(**kwargs) -> dict:
    """One tick that never raises: the live-settle loop calls this after each pass, and a bug here must never stop grading."""
    try:
        report = default_engine().tick(**kwargs)
        STATUS.update(last_report=report, last_error=None)
        return report
    except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad tick
        logger.error("postmortem tick failed: %s", type(exc).__name__)
        STATUS["last_error"] = type(exc).__name__
        return {"error": type(exc).__name__}
    finally:
        STATUS["ticks"] += 1
        STATUS["last_tick_utc"] = store.iso(datetime.now(timezone.utc))


def summary_for(hound_id: str, limit: int = SUMMARY_LIMIT_DEFAULT, *, engine: Optional[Engine] = None) -> dict:
    """THE FEED FOR COACHING (see ``Engine.summary_for``): compact lessons and per-factor tallies for one hound's hindsight reviews.

    ``summary_for(hound_id, limit)`` -> {hound_id, label, note, as_of, reviews, grounded, pending, lessons: [{bet_key, date, game,
    selection, result, lesson, luck_vs_process, reason_relevance, depth, sources}], factors: {tag: {n, wins, losses}},
    luck_vs_process: {word: n}, reason_relevance: {word: n}, info_gaps: [str], paper_only}. A hound with no reviews gets the same
    keys with zeros and empty lists; a failure to read the ledger gives the same shape too (never an exception to the prompt builder)."""
    try:
        return (engine or default_engine()).summary_for(hound_id, limit)
    except Exception as exc:  # noqa: BLE001 -- a coaching prompt must not fail because a ledger could not be read
        logger.error("postmortem summary failed: %s", type(exc).__name__)
        return {"hound_id": hound_id, "label": pm.LABEL, "note": pm.NOTE, "as_of": None, "reviews": 0, "grounded": 0,
                "pending": 0, "lessons": [], "factors": {}, "luck_vs_process": {}, "reason_relevance": {}, "info_gaps": [],
                "paper_only": True}
