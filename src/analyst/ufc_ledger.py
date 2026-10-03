"""The UFC analyst's record: append-only, hash-chained, apart from every other record.

THE SAME PATTERN AS THE MLB ANALYST'S LEDGER, ITS OWN FILE
----------------------------------------------------------
`src/analyst/ledger.py` is the MLB analyst's record and `src/appstate/card_ledger.py`
is the cards'. This module copies the pattern (frozen before the start, graded by a
separate row, corrections append and never rewrite) onto the same primitive,
`src.ledger.chain.HashChainLedger`: each row's hash covers its payload and the
previous row's hash, so editing or deleting any row breaks every hash after it and
`verify` names the first break. None of their code is edited and no row is shared.

    evidence/analyst_ufc_v1.jsonl          the calls, their grades, corrections
    evidence/analyst_ufc_packets_v1/       the frozen packets, gzip, named by hash
    evidence/analyst_ufc_usage_v1.jsonl    the cost log (the MLB log is not touched)

THREE KINDS OF ROW
------------------
`analyst_ufc_published`   the calls for one bout, written before it starts. Refused for
                          a bout that has started, whose scheduled start is unknown, or
                          whose state is not "scheduled". Carries the packet's hash and
                          the path of the frozen packet file, the model and the prompt
                          identity, the calls (each with its grading spec), every call
                          the critic struck (the audit trail) and the run's cost.
`analyst_ufc_graded`      the results of one published row, read from the data layer's
                          bout record. A later graded row for the same published row
                          replaces an earlier one only when it adds a result.
`analyst_ufc_correction`  fixes one call's grade; the row it corrects is untouched.

"BEFORE THE BOUT" MEANS BEFORE ITS SCHEDULED START
--------------------------------------------------
ESPN gives every bout of a card segment the segment's start (five main-card bouts
share one minute). The real bout starts later, so a bout is refused at its scheduled
start: the rule is conservative by construction, and a bout whose start the store
does not hold is refused, because nothing can be shown to precede it.

A bout can be published again (`refresh`) while it has not started and has not been
graded; every version stays in the file and only the NEWEST version of a bout counts.
Without `refresh` a published bout is frozen: the second `publish` returns the first row.

THE RECORD'S SMALL-SAMPLE RULE
------------------------------
Counts are always shown. A win rate or a return is withheld for a family until it has
`min_graded` graded calls (30), because a rate on twelve calls is a story, not a
measurement. Families are `moneyline`, `method` and `rounds_total`, counted on their own.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src import paths
from src.analyst import LABEL
from src.analyst import ledger as mlb_ledger
from src.analyst import packet as base
from src.analyst import ufc_analyst, ufc_grading
from src.ledger.chain import HashChainLedger, canonical_bytes

STORE = os.path.join("evidence", "analyst_ufc_v1.jsonl")
USAGE_STORE = os.path.join("evidence", "analyst_ufc_usage_v1.jsonl")
PACKET_DIR = os.path.join("evidence", "analyst_ufc_packets_v1")

KIND_PUBLISHED = "analyst_ufc_published"
KIND_GRADED = "analyst_ufc_graded"
KIND_CORRECTION = "analyst_ufc_correction"

# Only a bout still "scheduled" can be published. Anything else (in progress, final,
# canceled, postponed) has information the packet cannot exclude.
PUBLISHABLE_STATES = ("scheduled",)

CORRECTABLE = ("result", "profit_units", "reason")


class UfcLedgerError(RuntimeError):
    pass


class BoutStarted(UfcLedgerError):
    """Refused: the bout has started, or cannot be shown not to have."""


def _path(path: Optional[str], default: str) -> str:
    return path or str(paths.repo_root() / default)


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(_path(path, STORE))


def _utc(value: Any) -> Optional[datetime]:
    return base._parse_utc(value)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def rows(path: Optional[str] = None) -> list:
    return _ledger(path).read()


def latest_published(all_rows: Sequence[Mapping]) -> dict:
    """{bout_id: newest published row}. Later rows win: the file is ordered."""
    out: dict = {}
    for row in all_rows:
        if row.get("kind") == KIND_PUBLISHED:
            out[row["bout_id"]] = row
    return out


def _published_versions(all_rows: Sequence[Mapping], bout_id: str) -> list:
    return [r for r in all_rows if r.get("kind") == KIND_PUBLISHED and r.get("bout_id") == bout_id]


def latest_graded(all_rows: Sequence[Mapping]) -> dict:
    """{published row_hash: newest graded row for it}."""
    out: dict = {}
    for row in all_rows:
        if row.get("kind") == KIND_GRADED:
            out[row["published_row_hash"]] = row
    return out


def corrections_for(all_rows: Sequence[Mapping]) -> dict:
    """{(graded row_hash, slot_id): newest correction}."""
    out: dict = {}
    for row in all_rows:
        if row.get("kind") == KIND_CORRECTION:
            out[(row["graded_row_hash"], row["slot_id"])] = row
    return out


def effective_calls(graded: Optional[Mapping], corrections: Mapping) -> dict:
    """{slot_id: graded call with corrections applied} for one graded row."""
    out: dict = {}
    if graded is None:
        return out
    for call in graded.get("calls") or []:
        fixed = dict(call)
        corr = corrections.get((graded["row_hash"], call["slot_id"]))
        if corr:
            for key in CORRECTABLE:
                if key in corr["fields"]:
                    fixed[key] = corr["fields"][key]
            fixed["corrected"] = True
        out[call["slot_id"]] = fixed
    return out


# ---------------------------------------------------------------------------
# publishing
# ---------------------------------------------------------------------------

def _write_packet(packet: Mapping, digest: str, date: str, packet_dir: Optional[str]) -> str:
    root = Path(_path(packet_dir, PACKET_DIR))
    target = root / str(date) / f"{packet['bout']['bout_id']}_{digest[:12]}.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with open(target, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as fh:
                fh.write(canonical_bytes(packet))
    try:
        return target.relative_to(paths.repo_root()).as_posix()
    except ValueError:
        return str(target)


def read_packet(row: Mapping, *, root: Optional[Path] = None) -> dict:
    """The frozen packet a published row was made from. Raises if the file is missing or
    is not the packet whose hash the row carries."""
    ref = Path(row["packet_path"])
    target = ref if ref.is_absolute() else (root or paths.repo_root()) / ref
    with gzip.open(target, "rb") as fh:
        packet = json.loads(fh.read())
    if base.packet_hash(packet) != row["packet_hash"]:
        raise UfcLedgerError(f"{target} is not the packet {row['packet_hash'][:12]}")
    return packet


def publish_refusal(packet: Mapping, now: datetime, lock_lead_minutes: float = 0.0) -> Optional[str]:
    """Why this bout cannot be published at `now`, or None.

    The one place the "before the bout" rule lives. `publish` raises on it and the CLI
    asks it BEFORE calling the model, so a bout that cannot be published is never paid for.
    """
    bout = packet["bout"]
    start = _utc(bout.get("start_utc"))
    if start is None:
        return "the bout's scheduled start is unknown, so it cannot be shown to be ahead"
    if bout.get("state") not in PUBLISHABLE_STATES:
        return f"the bout is {bout.get('state')!r}, not scheduled"
    if now >= start - timedelta(minutes=float(lock_lead_minutes)):
        return (f"the bout's scheduled start {_iso(start)} has passed or is inside the "
                f"{lock_lead_minutes}-minute lock; nothing can be published")
    return None


def publish(packet: Mapping, verified, *, now: datetime, model: str,
            run: Optional[Mapping] = None, path: Optional[str] = None,
            packet_dir: Optional[str] = None, lock_lead_minutes: float = 0.0,
            refresh: bool = False) -> tuple:
    """Freeze one bout's analysis. Returns `(row, created)`.

    Refuses (BoutStarted) unless the bout is provably still ahead of us: scheduled start
    known and in the future by more than `lock_lead_minutes`, and the bout's state
    "scheduled". An existing published row is returned untouched (`created` False) unless
    `refresh`, which writes a new version while the bout is ungraded. Nothing but the
    ledger row and the packet file is written.
    """
    bout = packet["bout"]
    bid = bout["bout_id"]
    why = publish_refusal(packet, now, lock_lead_minutes)
    if why:
        raise BoutStarted(f"{bid}: {why}")
    all_rows = rows(path)
    existing = _published_versions(all_rows, bid)
    if existing and not refresh:
        return existing[-1], False
    if existing and any(g for g in all_rows if g.get("kind") == KIND_GRADED
                        and g.get("published_row_hash") == existing[-1]["row_hash"]):
        raise UfcLedgerError(f"{bid}: already graded; it cannot be published again")
    digest = base.packet_hash(packet)
    packet_path = _write_packet(packet, digest, bout.get("date") or "undated", packet_dir)
    calls = []
    for call in verified.calls:
        entry = dict(call)
        entry["grading"] = ufc_grading.spec_for(packet["markets"][call["slot_id"]],
                                                call["selection"], bout)
        calls.append(entry)
    payload = {
        "kind": KIND_PUBLISHED,
        "bout_id": bid, "event_id": bout.get("event_id"), "event_name": bout.get("event_name"),
        "date": bout.get("date"), "start_utc": bout.get("start_utc"),
        "weight_class": bout.get("weight_class"), "scheduled_rounds": bout.get("scheduled_rounds"),
        "card_segment": bout.get("card_segment"), "match_number": bout.get("match_number"),
        "fighters": {"a": {"id": bout["fighter_a"]["id"], "name": bout["fighter_a"]["name"]},
                     "b": {"id": bout["fighter_b"]["id"], "name": bout["fighter_b"]["name"]}},
        "published_utc": _iso(now),
        "version": len(existing) + 1,
        "supersedes": existing[-1]["row_hash"] if existing else None,
        "packet_hash": digest, "packet_path": packet_path,
        "packet_version": packet.get("packet_version"),
        "prompt_version": ufc_analyst.UFC_PROMPT_VERSION, "prompt_hash": ufc_analyst.prompt_hash(),
        "model": model,
        "summary": verified.summary, "summary_status": verified.summary_status,
        "summary_problems": list(verified.summary_problems),
        "calls": calls,
        "struck": [{"slot_id": s["slot_id"], "problems": s["problems"], "original": s["original"]}
                   for s in verified.struck],
        "model_critic": verified.model_critic,
        "run": dict(run or {}),
    }
    return _ledger(path).append(payload), True


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------

def _progress(old: Optional[Mapping], new_calls: Sequence[Mapping]) -> bool:
    """Does `new_calls` say something the previous graded row did not?"""
    if old is None:
        return True

    def pic(calls):
        return {c["slot_id"]: (c.get("result"), c.get("profit_units"),
                               (c.get("would_have") or {}).get("result")) for c in calls}
    return pic(old.get("calls") or []) != pic(new_calls)


def _card_order(row: Mapping) -> tuple:
    number = row.get("match_number")
    return (number is None, number if isinstance(number, int) else 0, row["bout_id"])


def grade_date(date: str, bouts_by_id: Mapping, *, now: datetime,
               path: Optional[str] = None) -> dict:
    """Grade every published bout of `date` that can be advanced. Appends one graded row
    per bout whose picture changed; returns counts and a reason for every bout left
    alone. Idempotent: running it again changes nothing. `bouts_by_id` is the data
    layer's bouts, {bout_id: bout record}; `date` is the event date the rows carry."""
    ledger = _ledger(path)
    all_rows = ledger.read()
    pubs = [p for p in latest_published(all_rows).values() if p.get("date") == date]
    graded_by_hash = latest_graded(all_rows)
    counts = {"published": len(pubs), "graded": 0, "unchanged": 0, "complete": 0, "notes": []}
    for pub in sorted(pubs, key=_card_order):
        previous = graded_by_hash.get(pub["row_hash"])
        if previous and previous.get("complete"):
            counts["complete"] += 1
            continue
        body = ufc_grading.grade_bout(pub, bouts_by_id.get(pub["bout_id"]))
        # An all-unresolved picture is not a grade: nothing is written until at least one
        # call has a result (or a passed side has one).
        meaningful = any(c["result"] in ufc_grading.SETTLED or c.get("would_have")
                         for c in body["calls"])
        if not meaningful or not _progress(previous, body["calls"]):
            counts["unchanged"] += 1
            counts["notes"].append(f"{pub['bout_id']}: no new result yet")
            continue
        ledger.append({
            "kind": KIND_GRADED, "bout_id": pub["bout_id"], "date": date,
            "published_row_hash": pub["row_hash"], "version": pub["version"],
            "graded_utc": _iso(now), "complete": body["complete"],
            "final": body["final"], "calls": body["calls"],
        })
        counts["graded"] += 1
        if body["complete"]:
            counts["complete"] += 1
    return counts


def correct(bout_id: str, slot_id: str, fields: Mapping, reason: str, *,
            now: datetime, path: Optional[str] = None) -> dict:
    """Append a correction to one graded call. The graded row is untouched."""
    bad = set(fields) - set(CORRECTABLE)
    if bad or not fields:
        raise UfcLedgerError(f"a correction may set only {list(CORRECTABLE)}")
    if not reason or not str(reason).strip():
        raise UfcLedgerError("a correction needs a reason")
    all_rows = rows(path)
    pub = latest_published(all_rows).get(bout_id)
    graded = latest_graded(all_rows).get(pub["row_hash"]) if pub else None
    if graded is None or slot_id not in {c["slot_id"] for c in graded["calls"]}:
        raise UfcLedgerError(f"no graded call {slot_id!r} for {bout_id!r}")
    return _ledger(path).append({
        "kind": KIND_CORRECTION, "bout_id": bout_id, "slot_id": slot_id,
        "graded_row_hash": graded["row_hash"], "fields": dict(fields),
        "reason": str(reason).strip(), "corrected_utc": _iso(now)})


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

def call_title(spec: Mapping) -> str:
    """What a call is about, in words a reader can use: the market's name."""
    return ufc_grading.FAMILY_LABELS.get(spec.get("family"), str(spec.get("family") or ""))


def _bout_view(pub: Mapping, graded: Optional[Mapping], corrections: Mapping) -> dict:
    grades = effective_calls(graded, corrections)
    calls = []
    for c in pub["calls"]:
        item = {k: c.get(k) for k in ("slot_id", "market", "selection", "verdict", "price", "book",
                                      "fair_estimate", "confidence", "reasons", "pass_price",
                                      "what_would_change_it", "verification")}
        spec = c.get("grading") or {}
        item["family"] = spec.get("family")
        item["title"] = call_title(spec)
        g = grades.get(c["slot_id"])
        if g:
            item["result"] = g.get("result")
            item["would_have"] = g.get("would_have")
        calls.append(item)
    final = (graded or {}).get("final")
    return {
        "bout_id": pub["bout_id"], "event_id": pub.get("event_id"), "date": pub.get("date"),
        "start_utc": pub.get("start_utc"), "published_utc": pub["published_utc"],
        "model": pub["model"], "version": pub["version"],
        "fighter_a": pub["fighters"]["a"]["name"], "fighter_b": pub["fighters"]["b"]["name"],
        "weight_class": pub.get("weight_class"), "scheduled_rounds": pub.get("scheduled_rounds"),
        "card_segment": pub.get("card_segment"), "match_number": pub.get("match_number"),
        "summary": pub["summary"], "summary_status": pub["summary_status"],
        "calls": calls,
        "final": final,
        "result_text": ufc_grading.result_text(final, pub["fighters"]),
        "graded": graded is not None,
    }


def event_view(event_id: str, *, path: Optional[str] = None,
               all_rows: Optional[Sequence[Mapping]] = None) -> Optional[dict]:
    """The published analysis of every bout of one event, in card order (the main event
    first), merged with its grades; None when nothing was published for the event.
    Reads only the ledger: no model call, ever."""
    all_rows = rows(path) if all_rows is None else all_rows
    pubs = [p for p in latest_published(all_rows).values() if str(p.get("event_id")) == str(event_id)]
    if not pubs:
        return None
    graded_by_hash = latest_graded(all_rows)
    corrections = corrections_for(all_rows)
    pubs.sort(key=_card_order)
    return {
        "event_id": str(event_id), "event_name": pubs[0].get("event_name"), "date": pubs[0].get("date"),
        "bouts": [_bout_view(p, graded_by_hash.get(p["row_hash"]), corrections) for p in pubs],
    }


def _blank_family() -> dict:
    return {"taken": 0, "taken_other_side": 0, "passes": 0, "graded": 0, "wins": 0,
            "losses": 0, "pushes": 0, "voids": 0, "unresolved": 0, "units": 0.0,
            "passes_would_have_won": 0, "passes_would_have_lost": 0,
            "passes_would_have_pushed": 0}


def record(*, path: Optional[str] = None, min_graded: int = 30,
           all_rows: Optional[Sequence[Mapping]] = None, recent: int = 20) -> dict:
    """The public record, by market family. Pure fold over the ledger.

    A win rate and a return appear for a family only at `min_graded` graded calls (win,
    loss or push); below that they are None and `withheld_reason` says why. Counts always
    appear. Only the NEWEST version of each bout counts, and corrections are applied.
    """
    all_rows = rows(path) if all_rows is None else all_rows
    graded_by_hash = latest_graded(all_rows)
    corrections = corrections_for(all_rows)
    families = {f: _blank_family() for f in ufc_grading.FAMILIES}
    settled = published = 0
    recent_calls: list = []
    for pub in latest_published(all_rows).values():
        published += 1
        graded = graded_by_hash.get(pub["row_hash"])
        results = effective_calls(graded, corrections)
        if graded and graded.get("complete"):
            settled += 1
        for c in pub["calls"]:
            fam = (c.get("grading") or {}).get("family")
            if fam not in families:
                continue
            f = families[fam]
            verdict = c["verdict"]
            g = results.get(c["slot_id"])
            if verdict == "PASS":
                f["passes"] += 1
                would = ((g or {}).get("would_have") or {}).get("result")
                key = {"WIN": "passes_would_have_won", "LOSS": "passes_would_have_lost",
                       "PUSH": "passes_would_have_pushed"}.get(would)
                if key:
                    f[key] += 1
                continue
            f["taken"] += 1
            if verdict == "TAKE_OTHER_SIDE":
                f["taken_other_side"] += 1
            res = (g or {}).get("result", ufc_grading.UNRESOLVED)
            if res == ufc_grading.WIN:
                f["wins"] += 1
            elif res == ufc_grading.LOSS:
                f["losses"] += 1
            elif res == ufc_grading.PUSH:
                f["pushes"] += 1
            elif res == ufc_grading.VOID:
                f["voids"] += 1
            else:
                f["unresolved"] += 1
            if res in (ufc_grading.WIN, ufc_grading.LOSS, ufc_grading.PUSH):
                f["graded"] += 1
                f["units"] += float((g or {}).get("profit_units") or 0.0)
            if res in ufc_grading.SETTLED:
                recent_calls.append({
                    "date": pub["date"], "fighter_a": pub["fighters"]["a"]["name"],
                    "fighter_b": pub["fighters"]["b"]["name"], "family": fam,
                    "selection": c["selection"], "verdict": verdict, "price": c.get("price"),
                    "result": res, "reason": (g or {}).get("reason")})
    out_fams = {}
    for name, f in families.items():
        shown = dict(f)
        decided = f["wins"] + f["losses"]
        if f["graded"] >= min_graded:
            shown["win_rate"] = round(f["wins"] / decided, 4) if decided else None
            shown["units"] = round(f["units"], 2)
            shown["withheld_reason"] = None
        else:
            shown["win_rate"] = None
            shown["units"] = None
            shown["withheld_reason"] = (f"fewer than {min_graded} graded calls "
                                        f"({f['graded']} so far)")
        out_fams[name] = shown
    recent_calls.sort(key=lambda c: (c["date"] or "", c["family"]), reverse=True)
    return {
        "label": LABEL,
        "min_graded": min_graded,
        "bouts_published": published, "bouts_settled": settled,
        "families": out_fams, "recent": recent_calls[:recent],
    }


# ---------------------------------------------------------------------------
# integrity
# ---------------------------------------------------------------------------

def verify(path: Optional[str] = None, *, root: Optional[Path] = None) -> dict:
    """Walk the chain, then check every published row's packet file against its hash.
    `{"ok": bool, "rows": n, "problems": [...]}`."""
    result = _ledger(path).verify()
    problems = []
    if not result.ok:
        problems.append(f"chain broken at line {result.broken_at_line}: {result.reason}")
    for row in rows(path):
        if row.get("kind") != KIND_PUBLISHED:
            continue
        try:
            read_packet(row, root=root)
        except (OSError, ValueError, UfcLedgerError, EOFError) as exc:
            problems.append(f"{row.get('bout_id')}: packet file: {exc}")
    return {"ok": not problems, "rows": result.rows_checked, "problems": problems}


# ---------------------------------------------------------------------------
# cost log (the MLB log is not touched: this one is its own file)
# ---------------------------------------------------------------------------

def log_usage(*, date: str, bout_id: str, run_id: str, outcome: str, model: str,
              usage: Mapping, cost_usd: float, attempts: int, cfg: Mapping,
              now: datetime, extra: Optional[Mapping] = None,
              path: Optional[str] = None) -> dict:
    """One row per bout attempt: what it cost, from the usage the API returned."""
    return mlb_ledger.log_usage(
        date=date, game_id=bout_id, run_id=run_id, outcome=outcome, model=model, usage=usage,
        cost_usd=cost_usd, attempts=attempts, cfg=cfg, now=now,
        extra={"sport": "ufc", "bout_id": bout_id, **(extra or {})},
        path=_path(path, USAGE_STORE))


def usage_by_day(path: Optional[str] = None) -> dict:
    return mlb_ledger.usage_by_day(_path(path, USAGE_STORE))
