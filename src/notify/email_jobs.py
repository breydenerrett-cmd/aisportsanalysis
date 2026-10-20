"""Who gets which email, and when: the Keep hook, the nightly result, the Sunday pack, and the loop that runs them.

WHERE THE DATA COMES FROM. Never from the clock's idea of "tonight". The nightly result reads the user hounds'
hash-chained ledger (``user_engine.ledger_path()``, beside the app database): a ticket is reported when the
ledger holds a graded row for it (``user_settle.KIND_GRADED``) that this user has not already been told about.
"Already told" is the ``refs`` column of the send log (bet ids), so a ticket is in exactly one nightly email even
if the job runs late, runs twice or the machine restarts mid-run. ``LOOKBACK_HOURS`` only stops the first run
ever from replaying history. A day with nothing newly graded sends nothing; there is no "your hound sat out"
filler (playbook R7).

WHEN. The loop wakes every ``TICK_SECONDS`` and acts only inside the send window, in Eastern time:
the nightly from 09:00, the Sunday pack from 10:00, both until 11:00 (the playbook allows no send outside
07:00 to 11:00 ET). Before the nightly it waits until a settle pass has finished since 09:00
(``settle_gate``): ``user_runner`` settles every 15 minutes, so that is "after overnight settlement" without
guessing a time. A run that finishes with no failures is recorded in the send log and not repeated that day; a
run with failures is retried on the next tick, up to ``email.MAX_ATTEMPTS`` per user.

SINGLE WRITER. Production is one machine on sqlite and this is one daemon thread started from api/app.py.
The ledger scan runs under the process-wide build gate (``freshness._gated_build``) like every other heavy read
on the 1 GB machine and holds only per-hound counters plus the handful of graded rows inside the window; the
HTTP sends happen after the gate is released.

OFF UNLESS ``RESEND_API_KEY`` IS SET (``start_loop`` returns None otherwise), and ``EMAIL_JOBS=off`` turns it off
even then. The Sunday pack is off on top of that unless ``EMAIL_SUNDAY=on`` and config/business.json has a
``postal_address`` (owner 2026-10-20: transactional only until there is one; ``sunday_enabled``).

Nothing here places a bet or suggests one; every figure is a paper figure.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from src.notify import email as mail
from src.notify import email_prefs as prefs
from src.notify import email_render as render

logger = logging.getLogger("linehound.notify.jobs")

ENV_JOBS = "EMAIL_JOBS"
ENV_SUNDAY = "EMAIL_SUNDAY"      # opt-in for the Sunday pack; see sunday_enabled
TICK_SECONDS = 300.0
WAIT_FOR_WARMUP_SECONDS = 600.0

NIGHTLY_HOUR = 9                 # Eastern: the nightly may go from here ...
SUNDAY_HOUR = 10                 # ... and the Sunday pack from here ...
WINDOW_END_HOUR = 11             # ... and nothing goes at or after this hour (playbook backlog 2: 07:00-11:00 ET)
SUNDAY_WEEKDAY = 6               # Monday is 0
LOOKBACK_HOURS = 36              # a nightly never reaches further back than this
WEEK_DAYS = 7
HOUSE_TOP_N = 3

JOB_NIGHTLY = "nightly"
JOB_SUNDAY = "sunday"

# Addresses that can never receive mail. The example accounts (docs/EXAMPLE_ACCOUNTS.md) and test fixtures use
# them; sending to one only bounces and costs the sending domain its reputation.
_RESERVED_DOMAINS = ("example.com", "example.org", "example.net", "invalid", "test", "localhost")
_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

STATUS: dict = {"enabled": False, "ticks": 0, "last_tick_utc": None, "last_error": None, "last_runs": {}}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _eastern():
    from src.pipeline import snapshots
    return snapshots._EASTERN


def et(now: datetime) -> datetime:
    return now.astimezone(_eastern())


def et_date(now: datetime) -> str:
    return et(now).date().isoformat()


def deliverable(address: Any) -> bool:
    text = str(address or "").strip().lower()
    if not _ADDRESS.match(text):
        return False
    domain = text.rpartition("@")[2]
    return not any(domain == r or domain.endswith("." + r) for r in _RESERVED_DOMAINS)


# ---------------------------------------------------------------------------
# context: every outside thing a job touches, injectable
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    """Production leaves everything unset. Tests inject a temp database, ledger and send log, a fake transport,
    a fixed clock and a canned house leaderboard, so nothing touches the real disk or the network."""
    now: Optional[datetime] = None
    db: Optional[Path] = None
    ledger: Optional[str] = None
    http: Optional[Callable] = None
    log: Optional[mail.SendLog] = None
    env: Optional[Mapping] = None
    sleep: Callable[[float], None] = mail.time.sleep
    house_top: Optional[Callable[[], Optional[list]]] = None
    settle_gate: Optional[Callable[[datetime], bool]] = None
    address: Optional[str] = None            # the postal address; None reads config/business.json
    secret: Optional[bytes] = None           # the unsubscribe-link signing secret; None reads/creates it
    extra: dict = field(default_factory=dict)

    def moment(self) -> datetime:
        return self.now or _utcnow()

    def send_log(self) -> mail.SendLog:
        return self.log or mail.default_log()

    def postal(self) -> Optional[str]:
        return self.address if self.address is not None else prefs.postal_address()

    def unsubscribe(self, user_id: int) -> str:
        return prefs.unsubscribe_url(user_id, env=self.env, secret=self.secret)


@contextlib.contextmanager
def _gate():
    try:
        from src.appstate import freshness
        gate = freshness._gated_build()
    except Exception:  # noqa: BLE001 -- no gate available (a bare test) is not a reason to skip the job
        gate = contextlib.nullcontext()
    with gate:
        yield


def _send(ctx: Ctx, message: dict, *, user_id, kind: str, date: str, refs=()) -> dict:
    return mail.send(message, user_id=user_id, kind=kind, date=date, refs=refs, http=ctx.http,
                     log=ctx.send_log(), env=ctx.env, sleep=ctx.sleep, now=ctx.moment())


# ---------------------------------------------------------------------------
# dogs, and what the ledger says about them
# ---------------------------------------------------------------------------

def _get(obj: Any, name: str, default=None):
    return obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)


def _parse_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def kennels(hounds: list) -> dict:
    """{owner_user_id: [dog, ...]} where a dog is one LINEAGE (all versions of a rule share a name and one
    account): {"root_id", "name", "id" (newest version), "ids" (every version)}. A lineage its owner removed
    from the kennel is not a dog any more and is never emailed about."""
    from src.hounds import user_store
    by_owner: dict = {}
    for h in hounds:
        by_owner.setdefault(h["owner_user_id"], []).append(h)
    out: dict = {}
    for owner, rows in by_owner.items():
        gone = user_store.removed_roots(rows)
        lineages: dict = {}
        for h in rows:
            if h["root_id"] in gone:
                continue
            lineages.setdefault(h["root_id"], []).append(h)
        dogs = []
        for root, versions in lineages.items():
            versions.sort(key=lambda v: (v["version_no"], v["id"]))
            newest = versions[-1]
            dogs.append({"root_id": root, "name": newest["name"], "id": newest["id"],
                         "ids": [v["id"] for v in versions], "created_at": newest["created_at"]})
        dogs.sort(key=lambda d: (d["created_at"], d["id"]))
        if dogs:
            out[owner] = dogs
    return out


def scan_ledger(ledger_file: Optional[str], hound_ids: set, since: datetime, until: datetime,
                *, with_bets: bool) -> dict:
    """One streaming pass (two when ``with_bets``) over the user hounds' ledger.

    Returns ``{"totals": {hound_id: {w, l, p, v, units}}, "window": {hound_id: [graded]}, "bets": {bet_id: row}}``.
    ``totals`` are the hound's whole forward record (a replay row never counts, the same rule the public record
    keeps); ``window`` is every graded row with ``since < graded_utc <= until``; ``bets`` holds only the bet rows
    those graded rows refer to. Units are stake-weighted, the quantity the bankroll view is built on."""
    from src.hounds import user_engine, user_settle
    from src.ledger.chain import HashChainLedger
    path = user_engine.ledger_path(ledger_file)
    store = HashChainLedger(path)
    totals: dict = {}
    window: dict = {}
    wanted: set = set()
    for row in store.iter_rows():
        if row.get("kind") != user_settle.KIND_GRADED or row.get("hound_id") not in hound_ids:
            continue
        if row.get("segment") == "replay":
            continue
        hid = row["hound_id"]
        result = row.get("result")
        stake_units = row.get("profit_stake_units")
        value = stake_units if stake_units is not None else row.get("profit_units")
        t = totals.setdefault(hid, {"w": 0, "l": 0, "p": 0, "v": 0, "units": 0.0})
        key = {"WIN": "w", "LOSS": "l", "PUSH": "p", "VOID": "v"}.get(result)
        if key is None:
            continue
        t[key] += 1
        t["units"] += float(value or 0.0)
        graded_at = _parse_utc(row.get("graded_utc"))
        if graded_at is not None and since < graded_at <= until:
            window.setdefault(hid, []).append({"bet_id": row["bet_id"], "result": result,
                                               "units": None if value is None else float(value),
                                               "graded_utc": row.get("graded_utc")})
            wanted.add(row["bet_id"])
    bets: dict = {}
    if with_bets and wanted:
        for row in store.iter_rows():
            if row.get("kind") == user_engine.KIND_BET and row.get("bet_id") in wanted:
                bets[row["bet_id"]] = row
    return {"totals": totals, "window": window, "bets": bets}


def _lineage_totals(dog: Mapping, scan: Mapping) -> dict:
    out = {"w": 0, "l": 0, "p": 0, "v": 0, "units": 0.0}
    for hid in dog["ids"]:
        t = scan["totals"].get(hid)
        if t:
            for k in out:
                out[k] += t[k]
    return out


def _bankroll_of(units_total: float) -> float:
    from src.hounds import bankroll
    p = bankroll.params()
    return p.start + units_total * p.unit_usd


def _start_usd() -> float:
    from src.hounds import bankroll
    return bankroll.params().start


def _ticket(bet: Mapping, graded: Mapping) -> dict:
    game = (f"{bet.get('away_team')} at {bet.get('home_team')}"
            if bet.get("away_team") and bet.get("home_team") else "")
    return {"selection": bet.get("selection") or str(bet.get("side") or "").title(),
            "market": bet.get("market"), "sport": bet.get("sport") or "", "game": game,
            "price": bet.get("price"), "result": graded["result"], "units": graded["units"],
            "bet_id": bet["bet_id"]}


# ---------------------------------------------------------------------------
# audience
# ---------------------------------------------------------------------------

def _audience(ctx: Ctx) -> list:
    """[(user, [dog, ...])] for every account that has a dog and a sendable address."""
    from src.appstate import users as users_store
    from src.hounds import user_store
    by_owner = kennels(user_store.list_all(db=ctx.db))
    out = []
    for user in users_store.list_users(db=ctx.db):
        dogs = by_owner.get(user.id)
        if dogs and user.status != "suspended":
            out.append((user, dogs))
    return out


# ---------------------------------------------------------------------------
# (a) Keep confirmation
# ---------------------------------------------------------------------------

def send_keep_confirmation(user, dog, *, ctx: Optional[Ctx] = None) -> dict:
    """The Keep email: dog name, a link to its page, and what happens tonight. Sent once per user, ever (the
    caller is meant to call it when a free account saves its FIRST dog; this makes the promise true even if it
    is called again). Never raises; a no-op while ``RESEND_API_KEY`` is unset. ``user`` and ``dog`` may be the
    ``users.User`` / ``hounds`` row or any mapping with ``id``, ``email`` / ``id``, ``name``."""
    ctx = ctx or Ctx()
    try:
        user_id, address = _get(user, "id"), _get(user, "email")
        dog_id, dog_name = _get(dog, "id"), _get(dog, "name")
        if user_id is None or not dog_id or not dog_name:
            return {"status": "skipped", "reason": "no user or dog", "to": mail.mask_email(address)}
        if not deliverable(address):
            return {"status": "skipped", "reason": "undeliverable address", "to": mail.mask_email(address)}
        if not mail.enabled(ctx.env):
            mail.note_disabled()
            return {"status": mail.R_DISABLED, "http": None, "id": None, "to": mail.mask_email(address)}
        log = ctx.send_log()
        if log.ever_sent(user_id, mail.KIND_KEEP):
            return {"status": mail.R_DUPLICATE, "http": None, "id": None, "to": mail.mask_email(address)}
        message = render.keep_confirmation(
            to=str(address).strip(), dog_name=str(dog_name),
            dog_url=prefs.dog_url(str(dog_id), "keep", env=ctx.env),
            unsubscribe_url=ctx.unsubscribe(int(user_id)), address=ctx.postal())
        return _send(ctx, message, user_id=user_id, kind=mail.KIND_KEEP, date=et_date(ctx.moment()),
                     refs=[f"dog:{dog_id}"])
    except Exception as exc:  # noqa: BLE001 -- a confirmation email must never break the signup that called it
        logger.error("keep confirmation failed: %s", mail.scrub(repr(exc)))
        return {"status": mail.R_FAILED, "http": None, "id": None, "to": mail.mask_email(_get(user, "email"))}


def send_keep_confirmation_async(user, dog, *, ctx: Optional[Ctx] = None) -> Optional[threading.Thread]:
    """``send_keep_confirmation`` on a daemon thread, for a request that must not wait on Resend. Returns None
    (and starts nothing) while sending is disabled."""
    if not mail.enabled(ctx.env if ctx else None):
        mail.note_disabled()
        return None
    thread = threading.Thread(target=send_keep_confirmation, args=(user, dog), kwargs={"ctx": ctx},
                              daemon=True, name="email-keep")
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# (b) the nightly result
# ---------------------------------------------------------------------------

def run_nightly(ctx: Optional[Ctx] = None) -> dict:
    """Send each user ONE email covering every ticket of theirs graded since they were last told, or nothing.

    Returns a counts report (also written to the send log as a run row): ``users`` considered, ``sent``,
    ``no_bets`` (nothing newly graded), ``unsubscribed``, ``undeliverable``, ``duplicate``, ``failed``."""
    ctx = ctx or Ctx()
    now = ctx.moment()
    date = et_date(now)
    counts = {"users": 0, "sent": 0, "no_bets": 0, "unsubscribed": 0, "undeliverable": 0,
              "duplicate": 0, "failed": 0, "disabled": 0}
    with _gate():
        audience = _audience(ctx)
        hound_ids = {hid for _, dogs in audience for d in dogs for hid in d["ids"]}
        scan = (scan_ledger(ctx.ledger, hound_ids, now - timedelta(hours=LOOKBACK_HOURS), now, with_bets=True)
                if hound_ids else {"totals": {}, "window": {}, "bets": {}})
        off = prefs.unsubscribed_ids(db=ctx.db)
    log = ctx.send_log()
    start = _start_usd()
    for user, dogs in audience:
        counts["users"] += 1
        if user.id in off:
            counts["unsubscribed"] += 1
            continue
        if not deliverable(user.email):
            counts["undeliverable"] += 1
            continue
        told = log.refs_sent(user.id, mail.KIND_NIGHTLY)
        blocks, refs = [], []
        for dog in dogs:
            tickets = []
            for hid in dog["ids"]:
                for graded in scan["window"].get(hid, ()):
                    bet = scan["bets"].get(graded["bet_id"])
                    if bet is None or graded["bet_id"] in told or not render.price_shown(bet.get("price")):
                        continue
                    tickets.append((graded["graded_utc"], _ticket(bet, graded)))
            if not tickets:
                continue
            tickets.sort(key=lambda t: (str(t[0]), t[1]["bet_id"]))
            season = _lineage_totals(dog, scan)
            if not any(t["result"] in ("WIN", "LOSS", "PUSH") for _, t in tickets):
                continue                      # a hound whose only graded tickets are voids has nothing to report
            blocks.append({"id": dog["id"], "name": dog["name"], "url": prefs.dog_url(dog["id"], "nightly", env=ctx.env),
                           "tickets": [t for _, t in tickets],
                           "season": {"w": season["w"], "l": season["l"], "p": season["p"]},
                           "bankroll": _bankroll_of(season["units"])})
            refs += [t["bet_id"] for _, t in tickets]
        if not blocks:
            counts["no_bets"] += 1
            continue
        message = render.nightly_result(
            to=user.email, dogs=blocks, unsubscribe_url=ctx.unsubscribe(user.id),
            kennel_url=prefs.kennel_url("nightly", env=ctx.env), address=ctx.postal(), start_usd=start)
        result = _send(ctx, message, user_id=user.id, kind=mail.KIND_NIGHTLY, date=date, refs=refs)
        _tally(counts, result["status"])
    return _finish_run(ctx, JOB_NIGHTLY, date, counts, now)


# ---------------------------------------------------------------------------
# (c) the Sunday pack
# ---------------------------------------------------------------------------

def house_top_three(payload: Optional[Mapping]) -> Optional[list]:
    """The house pack's top three by paper bankroll, from the public leaderboard payload, or None when there
    is no payload. Only house hounds with at least the ranking minimum of settled bets are eligible (the
    playbook's R9 rule: never rank a handful of bets); a pack with nobody eligible gives an empty list."""
    if not payload:
        return None
    rows = []
    for h in payload.get("hounds") or []:
        bk = h.get("bankroll") or {}
        if h.get("kind") != "house" or h.get("status") == "retired" or bk.get("current") is None:
            continue
        if int(bk.get("settled") or 0) < int(bk.get("small_sample_min") or 20):
            continue
        rec = h.get("record") or {}
        rows.append({"name": h.get("name"), "id": h.get("id"), "w": int(rec.get("wins") or 0),
                     "l": int(rec.get("losses") or 0), "p": int(rec.get("pushes") or 0),
                     "bankroll": float(bk["current"])})
    rows.sort(key=lambda r: (-r["bankroll"], -(r["w"] + r["l"] + r["p"]), str(r["name"])))
    return rows[:HOUSE_TOP_N]


def _default_house_top() -> Optional[list]:
    """The saved copy of the public leaderboard (the one the site serves while it rebuilds). Never builds the
    book: a build streams about a million odds rows and has no business running for an email."""
    try:
        from src.hounds import stats
        return house_top_three(stats.saved_payload("leaderboard"))
    except Exception as exc:  # noqa: BLE001 -- the pack section is optional; the week per hound is not
        logger.warning("house leaderboard unavailable for the Sunday pack: %s", mail.scrub(repr(exc)))
        return None


def run_sunday(ctx: Optional[Ctx] = None) -> dict:
    """The week per hound plus the house pack's top three, to every user with a hound who has not paused
    emails. Unlike the nightly this goes out on a quiet week too (the leaderboard is the news)."""
    ctx = ctx or Ctx()
    now = ctx.moment()
    date = et_date(now)
    counts = {"users": 0, "sent": 0, "unsubscribed": 0, "undeliverable": 0, "duplicate": 0,
              "failed": 0, "disabled": 0, "no_bets": 0}
    with _gate():
        audience = _audience(ctx)
        hound_ids = {hid for _, dogs in audience for d in dogs for hid in d["ids"]}
        scan = (scan_ledger(ctx.ledger, hound_ids, now - timedelta(days=WEEK_DAYS), now, with_bets=False)
                if hound_ids else {"totals": {}, "window": {}, "bets": {}})
        off = prefs.unsubscribed_ids(db=ctx.db)
    top = (ctx.house_top or _default_house_top)()
    start = _start_usd()
    for user, dogs in audience:
        counts["users"] += 1
        if user.id in off:
            counts["unsubscribed"] += 1
            continue
        if not deliverable(user.email):
            counts["undeliverable"] += 1
            continue
        blocks = []
        for dog in dogs:
            week = {"w": 0, "l": 0, "p": 0, "units": 0.0}
            for hid in dog["ids"]:
                for graded in scan["window"].get(hid, ()):
                    key = {"WIN": "w", "LOSS": "l", "PUSH": "p"}.get(graded["result"])
                    if key:
                        week[key] += 1
                        week["units"] += float(graded["units"] or 0.0)
            season = _lineage_totals(dog, scan)
            blocks.append({"id": dog["id"], "name": dog["name"], "url": prefs.dog_url(dog["id"], "sunday", env=ctx.env),
                           "week": week, "season": {"w": season["w"], "l": season["l"], "p": season["p"]},
                           "bankroll": _bankroll_of(season["units"])})
        message = render.sunday_pack(
            to=user.email, dogs=blocks, house_top=top, unsubscribe_url=ctx.unsubscribe(user.id),
            leaderboard_url=prefs.leaderboard_url("sunday", env=ctx.env), address=ctx.postal(), start_usd=start)
        result = _send(ctx, message, user_id=user.id, kind=mail.KIND_SUNDAY, date=date)
        _tally(counts, result["status"])
    return _finish_run(ctx, JOB_SUNDAY, date, counts, now)


# ---------------------------------------------------------------------------
# admin test
# ---------------------------------------------------------------------------

def send_admin_test(to: str, ctx: Optional[Ctx] = None) -> dict:
    """The admin's test email. A fresh key every call (user 0, the second), so testing twice sends twice."""
    ctx = ctx or Ctx()
    now = ctx.moment()
    address = str(to or "").strip()
    if not _ADDRESS.match(address):
        return {"status": "invalid_address", "to": mail.mask_email(address)}
    message = render.admin_test_message(to=address, unsubscribe_url=ctx.unsubscribe(0), address=ctx.postal())
    return _send(ctx, message, user_id=0, kind=mail.KIND_TEST,
                 date=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


# ---------------------------------------------------------------------------
# bookkeeping
# ---------------------------------------------------------------------------

def _tally(counts: dict, status: str) -> None:
    key = {mail.R_SENT: "sent", mail.R_DISABLED: "disabled", mail.R_DUPLICATE: "duplicate",
           mail.R_GAVE_UP: "duplicate"}.get(status, "failed")
    counts[key] += 1


def _finish_run(ctx: Ctx, job: str, date: str, counts: dict, now: datetime) -> dict:
    report = {"job": job, "date": date, **counts}
    if counts.get("disabled") == 0:       # a disabled run left no trace; do not claim it ran
        mail.record_run(ctx.send_log(), job=job, date=date, counts=counts, now=now)
    STATUS["last_runs"][job] = {"date": date, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "counts": dict(counts)}
    logger.info("email job %s %s: %s", job, date, counts)
    return report


# ---------------------------------------------------------------------------
# the schedule
# ---------------------------------------------------------------------------

def _run_done(log: mail.SendLog, job: str, date: str) -> bool:
    """A run row for (job, date) with no failures: nothing left to retry today."""
    return any(r.get("type") == mail.ROW_RUN and r.get("job") == job and r.get("date") == date
               and not (r.get("counts") or {}).get("failed") for r in log.rows())


def default_settle_gate(now: datetime) -> bool:
    """True once a settle pass has finished since NIGHTLY_HOUR:00 Eastern today, or when no engine runs in this
    process (nothing to wait for)."""
    from src.hounds import user_runner
    state = user_runner.status()
    if not state.get("enabled"):
        return True
    if state.get("running"):
        return False
    last = _parse_utc(state.get("last_pass_utc"))
    local = et(now)
    opened = local.replace(hour=NIGHTLY_HOUR, minute=0, second=0, microsecond=0)
    return last is not None and last >= opened.astimezone(timezone.utc)


def due_jobs(now: datetime) -> list:
    local = et(now)
    jobs = []
    if NIGHTLY_HOUR <= local.hour < WINDOW_END_HOUR:
        jobs.append(JOB_NIGHTLY)
    if local.weekday() == SUNDAY_WEEKDAY and SUNDAY_HOUR <= local.hour < WINDOW_END_HOUR:
        jobs.append(JOB_SUNDAY)
    return jobs


def tick(ctx: Optional[Ctx] = None) -> dict:
    """One wake-up: run whichever jobs are due and not already done today. Returns {job: report | reason}."""
    ctx = ctx or Ctx()
    now = ctx.moment()
    out: dict = {}
    for job in due_jobs(now):
        date = et_date(now)
        if _run_done(ctx.send_log(), job, date):
            out[job] = "done"
            continue
        if job == JOB_NIGHTLY and not (ctx.settle_gate or default_settle_gate)(now):
            out[job] = "waiting for settlement"
            continue
        if job == JOB_SUNDAY and not sunday_enabled(ctx):
            out[job] = "off"
            continue
        out[job] = run_nightly(ctx) if job == JOB_NIGHTLY else run_sunday(ctx)
    return out


def sunday_enabled(ctx: Ctx) -> bool:
    """The Sunday pack is OFF by default (owner 2026-10-20: transactional email only until there is a postal
    address). It runs only when ``EMAIL_SUNDAY=on`` AND config/business.json has a ``postal_address``."""
    source = ctx.env if ctx.env is not None else os.environ
    if str(source.get(ENV_SUNDAY) or "").strip().lower() not in ("on", "1", "true", "yes"):
        return False
    return bool(ctx.postal())


def tick_safely(ctx: Optional[Ctx] = None) -> dict:
    """``tick`` that never raises: a failure is logged and shown on /admin/email/status."""
    try:
        report = tick(ctx)
        STATUS["last_error"] = None
        return report
    except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad tick
        logger.exception("email tick failed")
        STATUS["last_error"] = mail.scrub(repr(exc))
        return {"error": STATUS["last_error"]}
    finally:
        STATUS["ticks"] += 1
        STATUS["last_tick_utc"] = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def jobs_enabled(env: Optional[Mapping] = None) -> bool:
    source = env if env is not None else os.environ
    if str(source.get(ENV_JOBS) or "").strip().lower() in ("off", "0", "false", "no"):
        return False
    return mail.enabled(env)


def start_loop(*, ready: Optional[Callable[[], bool]] = None, stop_event: Optional[threading.Event] = None,
               env: Optional[Mapping] = None, tick_s: float = TICK_SECONDS,
               do_tick: Callable[[], object] = tick_safely) -> Optional[threading.Thread]:
    """Start the ONE daemon thread, or return None (starting nothing) unless ``RESEND_API_KEY`` is set and
    ``EMAIL_JOBS`` is not ``off``. It waits for ``ready()`` (the first cache warm-up pass, so it never competes
    with a cold start), then ticks every ``tick_s``."""
    if not jobs_enabled(env):
        if not mail.enabled(env):
            mail.note_disabled()
        return None
    event = stop_event if stop_event is not None else threading.Event()
    STATUS["enabled"] = True

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            do_tick()
            if event.wait(tick_s):
                return

    thread = threading.Thread(target=loop, daemon=True, name="email-jobs")
    thread.start()
    logger.info("email jobs loop started, tick=%ss", tick_s)
    return thread


# ---------------------------------------------------------------------------
# admin status
# ---------------------------------------------------------------------------

def status_report(ctx: Optional[Ctx] = None) -> dict:
    """What GET /admin/email/status shows: enabled or not, the loop, the last runs, and send counts. No
    address, key, body or token in it (the log holds masked addresses only, and none is repeated here)."""
    ctx = ctx or Ctx()
    rows = ctx.send_log().rows()
    now = ctx.moment()
    cutoff = now - timedelta(days=7)
    sent: dict = {}
    failed: dict = {}
    runs = []
    for r in rows:
        if r.get("type") == mail.ROW_RUN:
            runs.append({"job": r.get("job"), "date": r.get("date"), "at": r.get("ts"), "counts": r.get("counts")})
            continue
        stamp = _parse_utc(r.get("ts"))
        if stamp is None or stamp < cutoff:
            continue
        if r.get("status") == mail.STATUS_SENT:
            sent[r.get("kind")] = sent.get(r.get("kind"), 0) + 1
        elif r.get("status") == mail.STATUS_FAILED:
            failed[r.get("kind")] = failed.get(r.get("kind"), 0) + 1
    try:
        paused = len(prefs.unsubscribed_ids(db=ctx.db))
    except Exception:  # noqa: BLE001
        paused = None
    return {"enabled": mail.enabled(ctx.env), "from": mail.sender_address(ctx.env),
            "loop": {"running": bool(STATUS["enabled"]), "ticks": STATUS["ticks"],
                     "last_tick_utc": STATUS["last_tick_utc"], "last_error": STATUS["last_error"]},
            "windows_et": {"nightly": f"{NIGHTLY_HOUR:02d}:00-{WINDOW_END_HOUR:02d}:00",
                           "sunday": f"{SUNDAY_HOUR:02d}:00-{WINDOW_END_HOUR:02d}:00"},
            "last_runs": runs[-10:], "sent_last_7_days": sent, "failed_last_7_days": failed,
            "paused_users": paused, "postal_address_set": ctx.postal() is not None,
            "sunday_enabled": sunday_enabled(ctx), "paper_only": True}
